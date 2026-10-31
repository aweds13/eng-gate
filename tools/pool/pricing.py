"""定价算术（移植自 magpie `internal/catalog/{catalog.go,openrouter.go}`）。

★ **本模块不含价目表**：`Price` 一律由调用方构造，与 `tools/pool/ledger_spend.py` 的
  「不内置价目表」同一条纪律。这里只有**算术**：十进制位移、严格大于的分档、整单按档计、
  1 小时缓存写的 2× 规则。
★ 与 magpie 的差别：原件有「有效价五级优先级」（自定价 → <provider>/* → 目录 → models.dev →
  Same as），那一层依赖 `internal/provider/pricing*.go`（★ 该文件实测不存在，只有仅文档证据），
  **本模块不实现**。价从哪来是调用方的事。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

#: USD / 百万 token ⇒ USD / token（`catalog.go:342` 那个 `/ 1e6`）。
COST_SCALE: int = 1_000_000
#: `per_token()` 的十进制位移位数（`openrouter.go:37` 的 `- 6`）。
DISPLACE_DIGITS: int = 6
#: 1 小时缓存写价 = 入价 × 2（`catalog.go:284` 的 `2 * p.Input`）。
ONE_HOUR_FACTOR: float = 2.0
#: `one_hour_for()` 认模型的那条线索（`catalog.go:278` 的 `strings.Contains(..., "claude")`）。
CLAUDE_HINT: str = "claude"


@dataclass(frozen=True)
class Tier:
    """一档价：`prompt` **严格大于** `above` 时整单用这一档（`catalog.go:308-317`）。

    `above` 是 token 数；其余四个是 USD / 百万 token。`cache_write_1h` 缺席（0.0）= 还没定
    1 小时价，此时 `one_hour()` 退回 `cache_write`（`catalog.go:320-325`）。
    """

    above: int
    input: float
    output: float
    cache_read: float
    cache_write: float
    cache_write_1h: float = 0.0


@dataclass(frozen=True)
class Price:
    """一份价（USD / 百万 token）。**本模块不构造任何具体厂商的价**。

    `tiers` 按 `above` 升序给（原件在解析时排序，这里相信调用方 —— 见 `at()` 的「超过的最高
    一档」只跟顺序有关）。全程纯算术，**不打错误**：没有「无价」这个值，无价 = 调用方不给键。
    """

    input: float = 0.0
    output: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0
    cache_write_1h: float = 0.0
    tiers: tuple[Tier, ...] = ()


def per_token(per_million: float) -> str:
    """`USD / 百万 token` ⇒ `USD / token` 的字符串，走**十进制位移**，不做浮点除法。

    逐字对 `internal/catalog/openrouter.go:30-45`：先把数写成十进制字面量，再把小数点往左
    挪 `DISPLACE_DIGITS`（6）位；整数部分不够 7 位就左补 0（补出来的 0 之后会被 `lstrip` 掉），
    小数部分跟着一起挪、末尾 0 全剪掉。

    ★ 为什么不能用除法：`0.3 / 1e6` 得 `2.9999999999999997e-07`，而 API 面要的是逐字的
    `"0.0000003"` —— 原件注释（`openrouter.go:28`）点名说过这件事。
    负数按 `max(perMillion, 0)` 当 0（`per_token(-5) == "0"`）。
    """
    floor = max(per_million, 0.0)
    text = format(Decimal(repr(floor)), "f")
    whole, _, frac = text.partition(".")
    width = DISPLACE_DIGITS + 1
    if len(whole) < width:
        whole = "0" * (width - len(whole)) + whole
    cut = len(whole) - DISPLACE_DIGITS
    whole, frac = whole[:cut].lstrip("0"), (whole[cut:] + frac).rstrip("0")
    if not whole:
        whole = "0"
    if not frac:
        return whole
    return f"{whole}.{frac}"


def openrouter_pricing(price: Price) -> dict[str, str]:
    """OpenRouter 形状的价目表（`openrouter.go:16-26`）。

    `prompt` / `completion` **永远在**（价 0 也给 `"0"`）；两个 cache 键**只在有价时在**
    —— **绝不给 0**：原件的「无价」表达方式是键不存在（`if pr.CacheRead > 0`），不是给 0，
    因为「0 元」与「不知道价」在读者眼里会长得一样。

    ★ 今天**没有消费者**（pool 没有 `/v1/models` 面）—— 只搬输出形状，见卡 A354 缺口 3。
    """
    out: dict[str, str] = {"prompt": per_token(price.input), "completion": per_token(price.output)}
    if price.cache_read > 0:
        out["input_cache_read"] = per_token(price.cache_read)
    if price.cache_write > 0:
        out["input_cache_write"] = per_token(price.cache_write)
    return out


def one_hour_for(model_id: str, price: Price) -> Price:
    """给 claude 系补 1 小时缓存写价：`2 × 入价`，**分档里每一档也各自补一遍**。

    逐字对 `internal/catalog/catalog.go:277-287`（`OneHourFor`）：三个闸
    ——`cache_write <= 0`（连 5 分钟价都没有，2× 无意义）、`cache_write_1h > 0`（已有价不覆盖）、
    模型 id 里不含 `CLAUDE_HINT`（Anthropic 的规则，不是通用规则）—— 任一命中就**原样返回**。
    非 claude 的 id 因此原样返回；分档里已经有 1 小时价的那一档也原样保留。

    ★ 原件是就地改指针；这里 `Price` 是 frozen 的，返回**新**对象（同值语义）。
    """
    if price.cache_write <= 0 or price.cache_write_1h > 0 or CLAUDE_HINT not in model_id.lower():
        return price
    tiers = tuple(
        replace(tier, cache_write_1h=ONE_HOUR_FACTOR * tier.input) if tier.cache_write_1h <= 0
        else tier
        for tier in price.tiers
    )
    return replace(price, cache_write_1h=ONE_HOUR_FACTOR * price.input, tiers=tiers)


def at(price: Price, prompt_tokens: int) -> Price:
    """取**它超过的最高一档**，整单按那一档（`catalog.go:308-317`）。

    ★ 边界是**严格大于**（`prompt > t.Above`）：`prompt == above` 不算进这一档。
    ★ 是**整单按档**，不是分段累进 —— 原件注释逐字 `bills the whole request at the tier`。
    返回的那份 `Price` 的 `tiers` 是空的（原件里 `flat` 就不带档），再分一次档没有意义。
    """
    flat = Price(
        input=price.input,
        output=price.output,
        cache_read=price.cache_read,
        cache_write=price.cache_write,
        cache_write_1h=price.cache_write_1h,
    )
    for tier in price.tiers:
        if prompt_tokens > tier.above:
            flat = Price(
                input=tier.input,
                output=tier.output,
                cache_read=tier.cache_read,
                cache_write=tier.cache_write,
                cache_write_1h=tier.cache_write_1h,
            )
    return flat


def one_hour(price: Price) -> float:
    """1 小时缓存写的单价：有 `cache_write_1h` 用它，**否则退回 `cache_write`**。

    逐字对 `catalog.go:320-325`：退回 5 分钟价，**不是**退回 0、也**不是**抛 —— 缺 1 小时价时
    「按 5 分钟价算」是保守的近似，退回 0 等于把这段账白送。
    """
    return price.cache_write_1h if price.cache_write_1h > 0 else price.cache_write


def cost(
    price: Price,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read: int = 0,
    cache_write: int = 0,
    cache_write_1h: int = 0,
) -> float:
    """一次调用的总价（USD）。逐字对 `catalog.go:337-342`（`CostSplit`）。

    ★ 分档看的是 **`input + cache_read + cache_write` 三项之和**（`catalog.go:319`），
      不是 `input` 一项 —— 缓存命中的 token 也算进这次请求的 prompt 长度。
    ★ `cache_write_1h` 先夹到 `[0, cache_write]`：负数当 0，超过总数的部分当总数
      （1 小时写不能比写总量还多）。
    ★ 口径提醒：本函数算**四样相加**（含 `cache_read`），与 `ledger_spend.sums()` 的
      `tokens = input + output + cache_write`（不含 `cache_read`，抄 `budget.go:69-75`）**不同
      且都对**。两者**各自独立**：本函数的结果不许回灌 `sums()` 的 tokens，`sums()` 的 tokens
      也不许喂给本函数。
    """
    one_hour_tokens = min(max(cache_write_1h, 0), max(cache_write, 0))
    flat = at(price, input_tokens + cache_read + cache_write)
    total = (
        input_tokens * flat.input
        + output_tokens * flat.output
        + cache_read * flat.cache_read
        + (cache_write - one_hour_tokens) * flat.cache_write
        + one_hour_tokens * one_hour(flat)
    )
    return total / COST_SCALE


def unpriced_calls(calls: Sequence[dict[str, Any]]) -> int:
    """**没有价**的调用有几条（原件在 `usage.Record` 上判 `Price` 为 nil 或零值）。

    「有价」= 这一行带 `price` 键，值是个非空映射，且里面**至少有一个数 > 0**；其余一律算
    没有价（键缺席 / `None` / 不是映射 / 空映射 / 全 0）。

    ★ 数值两种形状都认：`float`/`int`，以及**数字字符串**（`openrouter_pricing()` 产出的就是
      字符串 —— 它的输出直接喂回来必须算「有价」，否则这个判据会把每个有价的 OpenRouter 行
      都数成无价）。

    ★ 调用方口径（判据）：`unpriced_calls(...) > 0` 才显示，**0 时不许打印
      `"0 calls unpriced"`** —— 一行「0 条无价」除了噪声什么都不是。

    ★ 缺口（如实）：本函数只能吃**调用方传进来的 dict 序列**。pool 的用量行
      （`gates/diag/wb-usage.jsonl`）没有 `price` 字段、也没有「这次调用有没有价」的标记，
      所以它与真实账本**还没有接线** —— 是「结构上还没做」，不是「做不到」。
    """
    return sum(1 for call in calls if not _has_price(call.get("price")))


def _has_price(raw: object) -> bool:
    """这一行的价算不算「有」：非空映射且至少一个数 > 0（`None` / 空 / 全 0 都不算）。

    数值认 `int` / `float` / 数字字符串三种（`openrouter_pricing()` 给的就是字符串）。
    """
    if not isinstance(raw, Mapping):
        return False
    for value in raw.values():
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float) and float(value) > 0:
            return True
        if isinstance(value, str):
            try:
                if float(value) > 0:
                    return True
            except ValueError:
                continue
    return False
