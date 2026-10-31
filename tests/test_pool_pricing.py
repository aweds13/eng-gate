"""卡 A354 · T-AG567 —— 定价算术的 17 条钉子（`tools/pool/pricing.py`）。

判据原文见 `复盘/卡/卡A354-定价算术.md` 与设计原件 §F42（`_ext/_port_design_wave4.md:1452-1475`）。
名字逐字照设计原件，顺序同上。

★ 三条最容易做成假牙的地方，都写进对应钉子的 docstring：
  ① `per_token` 断言的是**逐字字符串**（不是数值相等）—— 用浮点除法必然崩在第一颗上；
  ② `at()` 是**严格大于**，且钉子 5 必须**成对**（272,000 不算 / 272,001 算）；
  ③ 钉子 8 的夹具**必须让 `input`/`cache_read`/`cache_write` 三项都非 0**（判据 6 说
     `cost()` 传给 `at()` 的是三项之和；三项里只要有一项为 0，只传 `input` 也可能跨档
     ⇒ 那条钉就是假牙）。
"""

from __future__ import annotations

import ast
import importlib
import inspect
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

# ★ 本卡禁令是「不许用 lint 豁免蒙过去」，所以这里一条豁免都不挂，改走 `import_module`：
#   挂完 sys.path 后用赋值语句取值，E402（模块级 import 必须在文件顶部）根本触发不到，
#   判据一个字都不用放松。
pricing = importlib.import_module("pool.pricing")
ledger_spend = importlib.import_module("pool.ledger_spend")


# --------------------------------------------------------------------------- 1–4：per_token
def test_per_token_displaces_the_decimal_point_not_divides() -> None:
    """判据 1：`0.3 USD / 百万` ⇒ 逐字 `"0.0000003"`，走十进制位移，**不是**浮点除法。

    反向验证：把实现换成 `str(per_million / 1e6)` ⇒ 这条红
    （`0.3 / 1e6` 得 `2.9999999999999997e-07`，正是原件注释 `openrouter.go:28` 点名要避免的那个）。
    """
    assert pricing.per_token(0.3) == "0.0000003"
    # 两个「看起来也对」的错答案，钉死在断言里：
    assert pricing.per_token(0.3) != "2.9999999999999997e-07"
    assert pricing.per_token(0.3) != "0.00000030000000000000004"


def test_per_token_pads_short_whole_parts() -> None:
    """判据 2 前半：整数部分不够 7 位要左补 0（`20 → "0.00002"`、`1 → "0.000001"`）。"""
    assert pricing.per_token(20) == "0.00002"
    assert pricing.per_token(1) == "0.000001"
    assert pricing.per_token(0) == "0"


def test_per_token_keeps_the_fraction_while_shifting() -> None:
    """判据 3：小数位要跟着一起位移，**不许截断**（`1.25 → "0.00000125"`）。

    ★ 缺口 6：`1.25` 这条是按 `FormatFloat(-1, 64)` + 字符串位移**推的**，没跑 Go 对账 ——
      正确性证据只有算法本身与 `0.3`/`20` 两条同源样本。
    """
    assert pricing.per_token(1.25) == "0.00000125"


def test_per_token_clamps_negatives_to_zero() -> None:
    """判据 2 后半：`max(perMillion, 0)` —— 负数当 0，不是 `"-"` 开头的怪字符串。"""
    assert pricing.per_token(-5) == "0"
    assert pricing.per_token(-0.3) == "0"


# --------------------------------------------------------------------------- 5–7：at（分档）
def test_at_is_strictly_greater_than_the_tier() -> None:
    """判据 4：边界是**严格大于** —— 272,000 **不算**超档，272,001 **算**。两条必须成对。

    ★ 为什么必须成对：反向变异把 `>` 改成 `>=` 时，只会让「272,000 不算」那一条崩，
      「272,001 算」仍绿。只写一半的钉子咬不住 `>=`，那就是假牙。
    """
    tier = pricing.Tier(above=272_000, input=2.0, output=4.0, cache_read=0.2, cache_write=2.5)
    price = pricing.Price(input=1.0, output=2.0, cache_read=0.1, cache_write=1.25, tiers=(tier,))

    even = pricing.at(price, 200_000 + 72_000)  # 恰好 272,000
    assert even.input == 1.0, "等号不算超档：272,000 必须留在基础价"

    over = pricing.at(price, 272_001)
    assert over.input == 2.0, "272,001 已经超过 272,000 档 ⇒ 整单按那一档"


def test_at_takes_the_highest_tier_it_is_over() -> None:
    """判据 5：取**超过的最高一档** —— 不是最低档，也不是最高档。

    三档 100 / 272,000 / 500,000 下 `prompt=300,000` ⇒ 只有 100 与 272,000 两档被超过，
    取 272,000 那档（500,000 那档没被超过）。
    """
    price = pricing.Price(
        input=1.0,
        output=1.0,
        cache_read=1.0,
        cache_write=1.0,
        tiers=(
            pricing.Tier(above=100, input=2.0, output=2.0, cache_read=2.0, cache_write=2.0),
            pricing.Tier(above=272_000, input=3.0, output=3.0, cache_read=3.0, cache_write=3.0),
            pricing.Tier(above=500_000, input=4.0, output=4.0, cache_read=4.0, cache_write=4.0),
        ),
    )
    flat = pricing.at(price, 300_000)
    assert flat.input == 3.0, "300,000 超过 100 与 272,000 两档，取其中最高的 272,000"
    assert flat.output == 3.0
    assert flat.cache_read == 3.0
    assert flat.cache_write == 3.0
    # 整单按档（不是分段累进）：价就是这一档的价，不掺基础价
    assert flat.tiers == (), "原件里的 flat 不带档"


def test_at_with_no_tiers_returns_the_base_price() -> None:
    """判据 5 边界：没有档 ⇒ 原价原样返回（不掉成 0、不抛）。"""
    price = pricing.Price(input=1.0, output=2.0, cache_read=0.1, cache_write=1.25)
    flat = pricing.at(price, 10_000_000)
    assert (flat.input, flat.output, flat.cache_read, flat.cache_write) == (1.0, 2.0, 0.1, 1.25)


# --------------------------------------------------------------------------- 8–10：cost
def test_cost_counts_cached_and_written_tokens_into_the_tier() -> None:
    """判据 6：`cost()` 传给 `at()` 的是 **`input + cache_read + cache_write`**，不是 `input` 一项。

    ★ 夹具为什么必须是 100 / 100 / 100：边界档设在 250。三项之和 = 300 > 250 ⇒ 必须跨档；
      而只传 `input`（=100）就不跨档。**三项里只要有一项为 0**，只传 `input` 也可能跨档，
      这条钉就咬不住「只传 input」的变异 ⇒ 假牙。所以三项都非 0，且都写进断言。
    """
    base = pricing.Price(input=1.0, output=1.0, cache_read=1.0, cache_write=1.0)
    tier = pricing.Tier(above=250, input=2.0, output=2.0, cache_read=2.0, cache_write=2.0)
    price = pricing.Price(
        input=base.input,
        output=base.output,
        cache_read=base.cache_read,
        cache_write=base.cache_write,
        tiers=(tier,),
    )
    total = pricing.cost(
        price, input_tokens=100, output_tokens=0, cache_read=100, cache_write=100
    )
    # 跨过 250 档 ⇒ 四样都按 2.0 计：(100 + 0 + 100 + 100) * 2.0 = 600，再 / 1e6
    assert total == 600 / pricing.COST_SCALE
    # 反向：若只按 input 选档，落回基础价 1.0 ⇒ 300 / 1e6（数字不同，钉得住）
    assert total != 300 * 1.0 / pricing.COST_SCALE


def test_cost_clamps_one_hour_writes_between_zero_and_cache_write() -> None:
    """判据 7：`cache_write_1h` 先夹到 `[0, cache_write]`，两个方向都钉。

    超过总数（999 / cache_write=10）⇒ 按 10 计 1 小时价、0 按 5 分钟价；
    负数（-5）⇒ 按 0 计（全部走 5 分钟价）。
    """
    price = pricing.Price(
        input=1.0, output=0.0, cache_read=0.0, cache_write=2.0, cache_write_1h=4.0
    )
    high = pricing.cost(
        price, input_tokens=0, output_tokens=0, cache_write=10, cache_write_1h=999
    )
    # 10 个 token 全按 1 小时价 4.0：10 * 4.0 / 1e6
    assert high == 10 * 4.0 / pricing.COST_SCALE

    low = pricing.cost(
        price, input_tokens=0, output_tokens=0, cache_write=10, cache_write_1h=-5
    )
    # 负数当 0 ⇒ 10 个 token 全按 5 分钟价 2.0
    assert low == 10 * 2.0 / pricing.COST_SCALE


def test_cost_is_zero_when_every_price_is_zero() -> None:
    """判据 10：价全 0 ⇒ `0.0`（不是 `0`、不抛、不 `None`）。"""
    total = pricing.cost(
        pricing.Price(),
        input_tokens=1_000,
        output_tokens=2_000,
        cache_read=3_000,
        cache_write=4_000,
        cache_write_1h=5_000,
    )
    assert total == 0.0
    assert isinstance(total, float)


# --------------------------------------------------------------------------- 11：one_hour
def test_one_hour_falls_back_to_the_five_minute_price() -> None:
    """判据 8：没有 1 小时价时**退回 `cache_write`** —— 不是退回 0、也不是抛。"""
    assert pricing.one_hour(pricing.Price(cache_write=1.25)) == 1.25
    assert pricing.one_hour(pricing.Price(cache_write=1.25, cache_write_1h=2.4)) == 2.4
    assert pricing.one_hour(pricing.Price()) == 0.0


# --------------------------------------------------------------------------- 12：one_hour_for
def test_one_hour_for_only_touches_claude_and_only_when_unset() -> None:
    """判据 9/10：只动 claude、只在未设时动、`cache_write<=0` 不动、系数是 **2×**、分档里也设。

    反向变异有两条都落在这颗钉子上：删掉 claude 判断 ⇒ 非 claude 被设成 `2*input`；
    系数 `2.0` 改 `1.25` ⇒ 数字对不上。
    """
    price = pricing.Price(
        input=1.0,
        output=2.0,
        cache_read=0.1,
        cache_write=1.25,
        tiers=(pricing.Tier(above=100, input=2.0, output=4.0, cache_read=0.2, cache_write=2.5),),
    )

    # ① 非 claude：原样返回（连 tiers 都不动）
    plain = pricing.one_hour_for("gpt-5-mini", price)
    assert plain == price

    # ② claude 且未设 ⇒ 2 * input，分档里每一档也各自 2 * tier.input
    got = pricing.one_hour_for("claude-opus-5-5", price)
    assert got.cache_write_1h == 2.0 * price.input
    assert got.cache_write_1h == 2.0
    assert [tier.cache_write_1h for tier in got.tiers] == [2.0 * price.tiers[0].input]
    assert got.tiers[0].cache_write_1h == 4.0
    # 其他价一个都没动
    assert (got.input, got.output, got.cache_read, got.cache_write) == (1.0, 2.0, 0.1, 1.25)

    # ③ 已设过（幂等、不覆盖已有价）
    preset = pricing.Price(input=1.0, cache_write=1.25, cache_write_1h=9.0)
    assert pricing.one_hour_for("claude-opus-5-5", preset) == preset

    # ④ cache_write <= 0 ⇒ 不改（连 5 分钟价都没有，2× 无意义）
    no_write = pricing.Price(input=1.0, cache_write=0.0)
    assert pricing.one_hour_for("claude-opus-5-5", no_write) == no_write


# ---------------------------------------------------------------------- 13–14：openrouter
def test_openrouter_pricing_never_gives_zero_for_cache_keys() -> None:
    """判据 11：`input_cache_read` / `input_cache_write` **只在 > 0 时在** —— 绝不给 0。

    ★ 如实交代：这条只钉「价 0 时键不在」，钉子 14 钉「prompt/completion 在」。
      一个「无条件写所有键」的实现在钉子 14 上仍绿 —— **两条合起来**才定位得到。
    """
    empty_cache = pricing.openrouter_pricing(pricing.Price(input=0.3, output=15.0))
    assert "input_cache_read" not in empty_cache
    assert "input_cache_write" not in empty_cache
    assert "0" not in (empty_cache["prompt"], empty_cache["completion"])

    has_cache = pricing.openrouter_pricing(
        pricing.Price(input=0.3, output=15.0, cache_read=0.03, cache_write=0.375)
    )
    assert has_cache["input_cache_read"] == "0.00000003"
    assert has_cache["input_cache_write"] == "0.000000375"


def test_openrouter_pricing_always_has_prompt_and_completion() -> None:
    """判据 11 前半：价全 0 时 `prompt`/`completion` 两个键**仍在**，且都是 `"0"`。

    ★ 只断言这两个键**在**（不断言键集恰好是两元）。这是设计原件 §F42 反向变异 5 的如实交代：
      一个「无条件写所有键」的实现在**这条**上仍绿 —— 挡住它的是钉子 13（价 0 时键不在）。
      两条钉子的力气全在**成对**上，这里不许把钉子 14 写成能单独咬住变异 5 的样子，
      否则「两条合起来才定位得到」这个判断就没有证据了。
    """
    zero = pricing.openrouter_pricing(pricing.Price())
    assert "prompt" in zero
    assert "completion" in zero
    assert zero["prompt"] == "0"
    assert zero["completion"] == "0"


# --------------------------------------------------------------------------- 15：unpriced_calls
def test_unpriced_calls_counts_only_rows_without_a_price() -> None:
    """判据 12：混合 3 行有价 + 2 行无价 ⇒ 2；无价的四种形状都要算进去。

    无价 = `price` 键缺席 / `None` / 空映射 / 全 0（「0 元」与「不知道价」在读者眼里
    长得一样，所以全 0 也算不知道）。
    """
    rows = [
        {"id": "a", "price": {"prompt": "0.0000003"}},
        {"id": "b", "price": {"prompt": 0.0000003, "completion": 0.000015}},
        {"id": "c", "price": {"input_cache_read": "0.00000003"}},
        {"id": "d"},
        {"id": "e", "price": None},
    ]
    assert pricing.unpriced_calls(rows) == 2
    # 空映射与全 0 也是没有价；空序列 ⇒ 0（调用方这时不许打印任何东西）
    assert pricing.unpriced_calls([{"price": {}}, {"price": {"prompt": 0}}]) == 2
    assert pricing.unpriced_calls([]) == 0


# --------------------------------------------------------------------------- 16–17：边界自证
def test_pricing_module_holds_no_vendor_price_table() -> None:
    r"""判据 13：本模块**不许**内置任何厂商单价。

    判据级：`grep -c "gpt-\|claude-opus-5\|gemini-" tools/pool/pricing.py == 0` ——
    下面用 `re.findall` 做等价断言（命中列表必须为空）。

    ★ 这是本卡最重要的边界：**搬算术，不搬数据**。
    """
    source = inspect.getsource(pricing)
    hits = re.findall(r"gpt-|claude-opus-5|gemini-", source)
    assert hits == [], f"pricing.py 里出现了厂商名：{hits}"


def test_cost_does_not_feed_ledger_spend_tokens() -> None:
    """判据：两个口径**各自独立** —— 谁都不许调用谁（双向断言，**只看代码、不看 docstring**）。

    `pricing.cost()` 算四样相加（含 `cache_read`）；`ledger_spend.sums()` 的
    `tokens = input + output + cache_write`（不含 `cache_read`，逐字抄 `budget.go:69-75`）。
    两个口径**不同且都对** ⇒ 一旦互相喂数，就必然有一边把账算错。

    ★ 为什么不能直接 `assert "ledger_spend" not in 源码全文`：`pricing.py` 的模块 docstring
      **按设计原件逐字**写着「与 `tools/pool/ledger_spend.py` 的同一条纪律」——
      那句必须在，用全文子串断言就是自相矛盾。所以用 AST 取**代码里真正被引用的名字**：
      导入、属性根、调用，一个都不许是对方。
    """
    spend_src = inspect.getsource(ledger_spend)
    assert "pricing.cost" not in spend_src, "ledger_spend 里出现了 pricing.cost 的调用"
    assert "pricing" not in _code_names(ledger_spend), "ledger_spend 的代码引用了 pricing"
    assert "ledger_spend" not in _code_names(pricing), "pricing 的代码引用了 ledger_spend"


def _code_names(module: object) -> set[str]:
    """模块**代码**里出现过的名字（导入名 / 属性根 / 调用名）—— docstring 与注释不算。"""
    tree = ast.parse(inspect.getsource(module))  # type: ignore[arg-type]
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
        elif isinstance(node, ast.Attribute):
            root = node
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name):
                names.add(root.id)
        elif isinstance(node, ast.Name):
            names.add(node.id)
    return names
