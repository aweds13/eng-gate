"""卡 A360 · T-AG572：输出速度的判据（「什么情况不许报速度」）。

钉子名逐字照设计原件 `_port_design_wave5.md` §2.1「测试钉子名」那一列（**名字一个不改**）：

  ① ``test_window_rejects_untimed``
     没写出来（`out<=0`）/ 首字时间未知（`ttft<=0`，**pool 侧的常态**）/ 窗口太短
     （`w<MIN_DECODE_MS`）三种不可测；★ 另加 `w=99` 与 `w=100` 的**边界成对**
     —— 设计原件 §2.1 反向变异表点名：只测 `w=50` 那一侧，`MinDecodeMs 100→99` 会**空转**。
  ② ``test_window_rejects_too_fast``
     `out*1000 > MAX_DECODE_SPEED*w` 这条**边界两侧**：`out=10000,w=1000` 恰好等于 ⇒ 过；
     `out=10001` ⇒ 回 0（`MaxDecodeSpeed 10000→10001` 的变异靠它咬住）。
  ③ ``test_reasoning_counts_only_the_answer``
     有推理且有首字 ⇒ token = `out - reasoning`、窗口从 `first_text` 起 = `(50, 3000)`。
  ④ ``test_reasoning_without_any_text_tells_nothing``
     有推理、无首字、无 `first_reasoning` ⇒ `(0,0)`（不能拿推理的 token 冒充答案）；
     ★ 另钉 `ttft=0` 的那条（`reasoning=150, first_text=2000` 仍是 `(0,0)`）——
     设计原件漏写的那条，防「`if ttft <= 0` 被挪到 `reasoning` 分支之前」静默改义。
  ⑤ ``test_first_reasoning_start``
     走 `first_reasoning` 那一支：起点 `600`。★ **期望值按 magpie 源码，不按设计原件** ——
     原件的 `(50, 4400)` 在自己的 Go 依据下不成立（`usage.go:622-623` 只改 `start` 不改
     `out`；且 `flow*HeldShare=400 < w=4400` 会先被末端爆发那道闸拦掉）。逐字交代见该用例。
     同一条里钉 magpie 自己的 live 样本（`internal/gateway/testdata/reasoning-speed-visible.json`
     经 `reasoning_speed_test.go:376` 断言 `76/731`）—— 它是「token 不扣 reasoning」的实证。
  ⑥ ``test_held_burst_tells_nothing``
     末端爆发：`flow*HELD_SHARE < w` ⇒ `(0,0)`。★ 两侧都钉（`HeldShare 4→3` 与 `4→5`
     各咬一边），否则其中一位改了没人发现。
  ⑦ ``test_reason_pace_boundary_both_sides``（名字原件就写的是 `reason`，不改）
     `THINK_PACE` 那条**边界两侧**：日常参数两边都不触发 ⇒ 用刻意构造的量级
     （`out=10000, w=1000~1200, reasoning=1000`）让它恰好落在 20 的两侧。
  ⑧ ``test_reasoning_hidden_gate``
     `reasoning_hidden=True, first_text=0` ⇒ `(0,0)`；`first_text>0` ⇒ **继续走** `tells`
     （不是无条件回 0）。
  ⑨ ``test_codex_thresholds_both_sides``
     `CODEX_WINDOW_MS` 与 `CODEX_BODY_TOKENS` 两对边界（严格小于：恰好等于门槛算够长）。
  ⑩ ``test_constants_verbatim``
     六个常量逐字（卡规格判据 13）。
  ⑪ ``test_usage_line_gains_no_speed_key``
     `append_usage_line()` 的键集里**不许**出现任何速度/首字键（判据 14 的外面那道）。
  ⑫ ``test_no_module_imports_pool_speed``
     `tools/**/*.py` 里**没有任何一处** import `pool.speed`（卡规格判据 14，源码级断言）。

★ 三条纪律：
1. **判据只许一份**：每条断言都调被测实现，不在本文件另抄一份 `if` —— 唯一例外是 ⑫ 与 ⑪
   的**扫描器**（它们判的是源码形状，不是算术）。
2. **反向钉子先证前提**：⑫ 先断言「真扫到了东西」（文件数 ≥ 30），防扫描器退化成恒真空转。
3. **导入口径**：走包路径 `from tools.pool import speed`（`tools/` 没有 `__init__.py`，
   靠 namespace package —— 实测可用），**不往 `sys.path` 里塞**，本仓不许 `noqa`。

★ 零接线：本文件**不 import** `tools/wb_dispatch.py`（⑪ 用 AST 读源码，不执行它）。
"""

from __future__ import annotations

import ast
from pathlib import Path

from tools.pool import speed

ROOT = Path(__file__).resolve().parent.parent

#: `append_usage_line()` 今天写出去的 11 个业务键（`tools/wb_dispatch.py:1601-1605` 实测）。
USAGE_KEYS = (
    "卡", "模型", "轮次", "开始", "结束", "用时分钟",
    "input_tokens", "output_tokens", "cache_read", "退出码", "判决",
)

#: 速度/首字类键名里**不许**出现的片段（判据 14 的「外面那道」）。
SPEED_WORDS = ("ttft", "first_text", "flow", "tok_per_s", "tps", "speed", "速度")


# ============================================================ ① 窗口：三种不可测
def test_window_rejects_untimed() -> None:
    """`out<=0` / `ttft<=0` / `w<MIN_DECODE_MS` 三种都回 0；★ `w=99` 与 `w=100` 成对。"""
    # 没写出来就没有速度（判据 1）。
    assert speed.window(out=0, ms=1000, ttft=1) == 0
    assert speed.window(out=-1, ms=1000, ttft=1) == 0
    # 首字时间未知 ⇒ 不可测（判据 2）。★ 这是 pool 侧的常态：不产 ttft。
    assert speed.window(out=10, ms=1000, ttft=0) == 0
    # `w = 50 < MIN_DECODE_MS(100)` ⇒ 不可测（判据 3）。
    assert speed.window(out=10, ms=1000, ttft=950) == 0
    # ★ 边界成对（设计原件 §2.1 反向变异表：只测 w=50 会让 `MinDecodeMs 100→99` 空转）。
    assert speed.window(out=1, ms=100, ttft=1) == 0, "w=99 必须判不可测"
    assert speed.window(out=1, ms=101, ttft=1) == 100, "w=100 恰好够长，必须过"


# ============================================================ ② 窗口：太快
def test_window_rejects_too_fast() -> None:
    """`out*1000 > MAX_DECODE_SPEED*w` 的边界两侧（判据 4）。"""
    # w=1000；10000*1000 = 10,000,000 > 10000*1000 为假 ⇒ 过。
    assert speed.window(out=10000, ms=1001, ttft=1) == 1000
    # 抬到 10001：10,001,000 > 10,000,000 为真 ⇒ 回 0。
    assert speed.window(out=10001, ms=1001, ttft=1) == 0


# ============================================================ ③ 有推理：只算答案
def test_reasoning_counts_only_the_answer() -> None:
    """有推理且有首字 ⇒ 只算答案（`out - reasoning`），窗口从 `first_text` 起（判据 6）。"""
    assert speed.tells(
        out=200, reasoning=150, ms=5000, ttft=500, first_text=2000, flow=0
    ) == (50, 3000)


# ============================================================ ④ 有推理无首字
def test_reasoning_without_any_text_tells_nothing() -> None:
    """有推理、无首字、无 `first_reasoning` ⇒ 不可测（判据 7）。"""
    assert speed.tells(out=200, reasoning=150, ms=5000, ttft=500, first_text=0, flow=0) == (0, 0)
    # ★ 设计原件漏的那条：`ttft=0` 时**先**回 (0,0)，不许因为「有首字」就绕过 ttft 那道。
    assert speed.tells(
        out=200, reasoning=150, ms=5000, ttft=0, first_text=2000, flow=0
    ) == (0, 0)
    # 空序列与 None 同义（卡规格「不许做」末条）。
    assert speed.tells(
        out=200, reasoning=150, ms=5000, ttft=500, first_text=0, flow=100, first_reasoning=[]
    ) == speed.tells(
        out=200, reasoning=150, ms=5000, ttft=500, first_text=0, flow=100, first_reasoning=None
    )


# ============================================================ ⑤ first_reasoning 起点
def test_first_reasoning_start() -> None:
    """走 `first_reasoning` 那一支：`start = 600`。

    ★ 期望值**按 magpie 源码**，不按设计原件。原件（与卡规格判据 8）写
    `tells(200, 150, 5000, 500, 0, 100, [600]) == (50, 4400)`，两处不成立：

    1. `usage.go:622-623` 的 `firstReasoning` 分支**只改 `start`**，不 `out = out - reasoning`
       （原件注释：`can time all output from firstReasoning`）⇒ token 是 `200`。
    2. 同一组入参 `w = 5000 - 600 = 4400`，`usage.go:626` 的 `flow*HeldShare < w` 实测
       `100*4 = 400 < 4400` 为真 ⇒ **先被末端爆发那道闸拦掉**，回 `(0,0)`。

    实证：magpie 自己的 live 样本 `internal/gateway/testdata/reasoning-speed-visible.json`
    （`reasoning_speed_test.go:376` 断言 `76/731`）—— `76` 是 `out` 原值（不是 `out-37`），
    且 `flow*4 = 748 > w = 731` 恰好**擦着**末端爆发那道闸过去。见下。
    """
    # 起点确实是 600 —— 把 flow 拿掉看不出来（那时回 0 是 HeldShare 那道闸），
    # 所以用 magpie 的 live 样本把「起点 600 且不看 HeldShare 也会被拦」和「起点生效」分开钉：
    # 样本里 start = 6787，取不到 6787 就算不出 731。
    assert speed.tells(
        out=76, reasoning=37, ms=7518, ttft=6787, first_text=0, flow=187,
        first_reasoning=[6787],
    ) == (76, 731), "live 样本：token 不扣 reasoning、窗口从 6787 起 = 731、flow 擦边过"
    # 起点抬到 7000 ⇒ w = 518，`187*4 = 748 < 518` 为假、但 `76*1000 > 10000*518` 也假 ⇒
    # 只是窗口变了 ⇒ 必须真的从 first_reasoning[0] 起算。
    assert speed.tells(
        out=76, reasoning=37, ms=7518, ttft=6787, first_text=0, flow=187,
        first_reasoning=[7000],
    ) == (76, 518), "起点改用 first_reasoning[0]=7000（不是 ttft=6787）"
    # 额定那组（设计原件判据 8 的入参）：源码真值是 (0,0)，不是 (50,4400)。
    assert speed.tells(
        out=200, reasoning=150, ms=5000, ttft=500, first_text=0, flow=100,
        first_reasoning=[600],
    ) == (0, 0), "HeldShare 先拦：100*4 = 400 < w = 4400"
    # 三个前置条件各一条（`firstReasoning[0] >= ttft` / `flow > 0` / `reasoning <= out`）。
    assert speed.tells(
        out=200, reasoning=150, ms=5000, ttft=700, first_text=0, flow=100,
        first_reasoning=[600],
    ) == (0, 0), "first_reasoning[0] < ttft ⇒ 不成立"
    assert speed.tells(
        out=200, reasoning=150, ms=5000, ttft=500, first_text=0, flow=0,
        first_reasoning=[600],
    ) == (0, 0), "flow = 0 ⇒ 那一支不走"
    assert speed.tells(
        out=100, reasoning=150, ms=5000, ttft=500, first_text=0, flow=100,
        first_reasoning=[600],
    ) == (0, 0), "reasoning > out ⇒ 那一支不走"


# ============================================================ ⑥ 末端爆发
def test_held_burst_tells_nothing() -> None:
    """`flow * HELD_SHARE < w` ⇒ 不可测（判据 9）；★ 两侧都钉。"""
    # 判据 9 原样：flow=100、w=3000 ⇒ 400 < 3000 ⇒ (0,0)。
    assert speed.tells(
        out=200, reasoning=150, ms=5000, ttft=500, first_text=2000, flow=100
    ) == (0, 0)
    # ★ 边界两侧（`HeldShare 4→3` 咬上一条，`4→5` 咬这一条）：
    # flow=100、w=400 ⇒ 400 < 400 为假 ⇒ 过（改成 3 就变真 ⇒ 会红）。
    assert speed.tells(out=100, reasoning=0, ms=401, ttft=1, first_text=0, flow=100) == (100, 400)
    # flow=100、w=401 ⇒ 400 < 401 为真 ⇒ 不可测（改成 5 就变假 ⇒ 会红）。
    assert speed.tells(out=100, reasoning=0, ms=402, ttft=1, first_text=0, flow=100) == (0, 0)


# ============================================================ ⑦ THINK_PACE 两侧
def test_reason_pace_boundary_both_sides() -> None:
    """`THINK_PACE` 那条**边界两侧**（判据 10）。

    判据是 `out * (first_text - ttft) > THINK_PACE * reasoning * w`（`out` 此处是**扣过推理的
    答案 token**）。日常参数（判据 6 那组 `50*1500 vs 20*150*3000`）两个方向都不触发，所以
    用刻意构造的量级把它顶到边界两侧 —— 固定答案 900 / 推理 800 / `w=1000`（门槛 `20*800*1000
    = 16,000,000`），只动「推理花了多久」`first_text - ttft`：

    * 不触发的一侧：差 `17,000` ⇒ `900*17,000 = 15,300,000 ≤ 16,000,000` ⇒ 报得出来；
    * 触发的 一侧：差 `18,100` ⇒ `900*18,100 = 16,290,000 > 16,000,000` ⇒ 回 `(0,0)`。

    ★ 两侧各自咬住一个方向：`THINK_PACE 20→21`（门槛升到 16,800,000）让**触发侧**变不触发；
    `20→19`（门槛降到 15,200,000）让**不触发侧**变触发。只写一侧，另一个方向改了没人发现。
    """
    # 不触发的一侧：差 17,000 ⇒ 15,300,000 ≤ 16,000,000 ⇒ 报得出来 (900, 1000)。
    assert speed.tells(
        out=1700, reasoning=800, ms=18500, ttft=500, first_text=17500, flow=0
    ) == (900, 1000)
    # 触发的一侧：差 18,100 ⇒ 16,290,000 > 16,000,000 ⇒ 不可测。
    assert speed.tells(
        out=1700, reasoning=800, ms=19600, ttft=500, first_text=18600, flow=0
    ) == (0, 0)
    # 反例证「这道闸只对『有推理且有首字』的轮次生效」：同样尺寸、reasoning=0 ⇒ 起点仍是 ttft，
    # 窗口 = 3600 - 500 = 3100，不受 ThinkPace 影响。
    assert speed.tells(
        out=10000, reasoning=0, ms=3600, ttft=500, first_text=2600, flow=0
    ) == (10000, 3100)


# ============================================================ ⑧ reasoning_hidden
def test_reasoning_hidden_gate() -> None:
    """`(Record) Decode` 那道先闸（判据 11）：藏了推理又没首字 ⇒ `(0,0)`；有首字则继续。"""
    assert speed.tells_record(
        output=200, reasoning=150, millis=5000, ttft=500, first_text=0,
        flow=0, reasoning_hidden=True,
    ) == (0, 0)
    # first_text>0 ⇒ **继续走 tells**，不是无条件回 0（否则这条用例左右不分）。
    assert speed.tells_record(
        output=200, reasoning=150, millis=5000, ttft=500, first_text=2000,
        flow=0, reasoning_hidden=True,
    ) == speed.tells(
        out=200, reasoning=150, ms=5000, ttft=500, first_text=2000, flow=0
    ) == (50, 3000)
    # reasoning_hidden=False 时与直接调 tells 逐字一致。
    assert speed.tells_record(
        output=200, reasoning=0, millis=5000, ttft=500, first_text=0, flow=0,
    ) == speed.tells(out=200, reasoning=0, ms=5000, ttft=500, first_text=0, flow=0) == (200, 4500)


# ============================================================ ⑨ Codex 两对边界
def test_codex_thresholds_both_sides() -> None:
    """`codex_short` 两对边界（判据 12）：严格小于 ⇒ 恰好等于门槛算够长。"""
    assert speed.codex_short(w=999, n=100) is True, "窗口差 1ms ⇒ 太短"
    assert speed.codex_short(w=1000, n=100) is False, "窗口恰好 1000 ⇒ 够长（不是 <）"
    assert speed.codex_short(w=2000, n=99) is True, "token 差 1 ⇒ 太少"
    assert speed.codex_short(w=2000, n=100) is False, "token 恰好 100 ⇒ 够长（不是 <）"


# ============================================================ ⑩ 常量逐字
def test_constants_verbatim() -> None:
    """六个常量逐字（判据 13）—— 改任何一位都是换判据，不是调参。"""
    assert speed.MIN_DECODE_MS == 100
    assert speed.MAX_DECODE_SPEED == 10000
    assert speed.HELD_SHARE == 4
    assert speed.THINK_PACE == 20
    assert speed.CODEX_WINDOW_MS == 1000
    assert speed.CODEX_BODY_TOKENS == 100


# ============================================================ ⑪ 用量行不长速度键
def _append_usage_line_keys() -> tuple[set[str], set[str]]:
    """从 `tools/wb_dispatch.py` 的源码里读出 `append_usage_line` 那行 dict 的键（AST，不执行）。"""
    src = (ROOT / "tools" / "wb_dispatch.py").read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "append_usage_line":
            keys: set[str] = set()
            for inner in ast.walk(node):
                if isinstance(inner, ast.Dict):
                    for key in inner.keys:
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            keys.add(key.value)
            return keys, set()
    raise AssertionError("`tools/wb_dispatch.py` 里找不到 `append_usage_line` —— 前提坏了")


def test_usage_line_gains_no_speed_key() -> None:
    """`append_usage_line()` 的键集里不许出现任何速度/首字键（判据 14 的外面那道）。"""
    keys, _ = _append_usage_line_keys()
    # 先证前提：真读到了那 11 个业务键（否则下面「没有速度键」是恒真空转）。
    assert set(USAGE_KEYS) <= keys, f"读到的键不全：{sorted(keys)}"
    offenders = sorted(k for k in keys for word in SPEED_WORDS if word in k.lower())
    assert offenders == [], (
        f"`append_usage_line` 长了速度/首字键 {offenders} —— pool 今天不产这些数，"
        "加上去只能接假数（卡 A360 判据 14）"
    )


# ============================================================ ⑫ 不许接线
def _imports_pool_speed(src: str) -> list[str]:
    """一段源码里有没有 import `pool.speed`（`import x` / `from ... import ...` 两种写法都看）。"""
    hits: list[str] = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            hits += [
                f"行{node.lineno} import {alias.name}"
                for alias in node.names
                if alias.name in {"pool.speed", "tools.pool.speed"}
            ]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            level = "." * node.level
            names = [alias.name for alias in node.names]
            if module in {"pool.speed", "tools.pool.speed"}:
                hits.append(f"行{node.lineno} from {level}{module} import …")
            elif module in {"pool", "tools.pool"} and "speed" in names:
                hits.append(f"行{node.lineno} from {level}{module} import speed")
            elif module == "" and node.level == 2 and "speed" in names:
                hits.append(f"行{node.lineno} from {level} import speed（包内相对导入）")
    return hits


def test_no_module_imports_pool_speed() -> None:
    """`tools/**/*.py` 里没有任何一处 import `pool.speed`（判据 14）。

    理由：pool 今天不产 `ttft` / `first_text` / `flow`，接进去只能接假数 —— 那正是本卡要消灭
    的东西。将来真有数了，唯一入口是 `append_usage_line` 的键集，那是另一张卡。
    """
    files = sorted((ROOT / "tools").rglob("*.py"))
    # 先证前提：真扫到了东西（防扫描器退化成恒真空转）。
    assert len(files) >= 30, f"只扫到 {len(files)} 个文件 —— 扫描器坏了，不是仓干净"
    self_path = ROOT / "tools" / "pool" / "speed.py"
    offenders: list[str] = []
    for path in files:
        if path == self_path:  # 自己不算接线
            continue
        src = path.read_bytes().decode("utf-8", errors="replace")
        offenders += [f"{path.relative_to(ROOT)}: {hit}" for hit in _imports_pool_speed(src)]
    assert offenders == [], "tools/ 里有人接线了 pool.speed：\n" + "\n".join(offenders)


# ============================================================ ⑬ 正常一条仍要报得出来
def test_a_normal_reply_still_tells_a_speed() -> None:
    """判据 5：判据只在**该拦**的时候拦 —— 正常一条必须报得出来（否则整道闸成了恒真空转）。"""
    assert speed.tells(
        out=200, reasoning=0, ms=5000, ttft=500, first_text=0, flow=0
    ) == (200, 4500)
