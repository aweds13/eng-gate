r"""输出速度的**判据**：什么情况不许报速度（卡 A360 · 台账号 T-AG572）。

**移植自** magpie `internal/usage/usage.go` 与 `internal/usage/ledger.go`（设计原件
`D:/repo/program/_ext/_port_design_wave5.md` §2.1，逐行对齐）；判据的唯一来源是
`复盘/卡/卡A360-什么情况不许报速度.md`。

## 判据问的是哪个问题

★ 本模块回答的是「**什么情况不许报速度**」，**不是**「怎么算速度」。速度快慢由调用方自算
（`tokens * 1000 / window_ms`）；本模块只交出两样东西：**能算的窗口毫秒**与**能算的 token**，
以及一套**说不许算**的情形。返回值 `0`（毫秒）与 `(0, 0)`（tokens, 窗口）都只有一个意思 ——
**不可测**。调用方拿到 0 就不报速度、不显示、不参与任何均值。**不许把「不可测」写成 0 速度**
（那会把一条排队 4.5 秒的回复显示成「很慢」）。

要闭的那个真错：**拿墙钟冒充速度**。一条 5 秒的回复里有 4.5 秒是排队与首字延迟，用
`output_tokens / 总时长` 算出来的「速度」是假的，而且会**系统性偏低**（把快的号看不出来）。

## ② pool 今天零生产方（这一条必须一起读）

**pool 今天零生产方，本模块上线当天一行也不被调用。** 理由是实测的：`gates/diag/wb-usage.jsonl`
只有 `用时分钟`（`tools/wb_dispatch.py:1591 append_usage_line` 的键集里没有任何首字/流转/速度
字段），而 242 份 `gates/diag/wb-*.jsonl` 的 `result` 事件键里**没有** `ttft_ms` /
`first_text_ms` / `flow_ms`（对比 magpie `internal/gateway/usage_ingest.go:77` 的 `ingestFields`
有这三个名字）。⇒ `window()` / `tells()` 在 pool 侧今天**必然走到「不可测」出口**（`ttft <= 0`
那一道），判据在、数据面空。

★ 所以「不许接线」是**判据**而不是洁癖：接进去只能接假数，那正是本卡要消灭的东西。`tools/`
全目录没有任何一处 import 本模块（钉子在 `tests/test_pool_speed_tells.py`，源码级断言）。
将来真有数了，唯一的入口是 `append_usage_line` 的键集（加 `ttft_ms` / `first_text_ms` /
`flow_ms` 三个键）—— 那是另一张卡，**本模块不碰它**。

## 与 magpie 的逐行对应

| 本模块 | magpie 原件 |
|---|---|
| `MIN_DECODE_MS` / `MAX_DECODE_SPEED` | `usage.go:566-569` |
| `window()` | `usage.go:573-580` |
| `tells()` | `usage.go:616-641` |
| `HELD_SHARE` / `THINK_PACE` | `usage.go:647-650` |
| `tells_record()` | `usage.go:657-663` |
| `CODEX_WINDOW_MS` / `CODEX_BODY_TOKENS` | `ledger.go:810-811` |
| `codex_short()` | `ledger.go:824` |

原件那七段逐字（照抄，**一位都不许改** —— 改了就是换判据，不是调参）::

    // usage.go:566-569
    const ( MinDecodeMs = 100; MaxDecodeSpeed = 10000 )
    // usage.go:573-580
    func DecodeWindow(out int, ms, ttft int64) int64 {
        w := ms - ttft
        if out <= 0 || ttft <= 0 || w < MinDecodeMs
            || int64(out)*1000 > MaxDecodeSpeed*w { return 0 }
        return w }
    // usage.go:616-641
    func DecodeOf(out, reasoning int, ms, ttft, firstText, flow int64,
        firstReasoning ...int64) (tokens int, w int64) {
        start := ttft
        if reasoning > 0 {
            if firstText > 0 { out, start = out-reasoning, firstText
            } else if len(firstReasoning) > 0 && firstReasoning[0] >= ttft
                && flow > 0 && reasoning <= out { start = firstReasoning[0]
            } else { return 0, 0 } }
        if ttft <= 0 { return 0, 0 }
        if w = DecodeWindow(out, ms, start); w == 0 { return 0, 0 }
        if flow > 0 && flow*HeldShare < w { return 0, 0 }
        if reasoning > 0 && firstText > 0
            && int64(out)*(firstText-ttft) > ThinkPace*int64(reasoning)*w { return 0, 0 }
        return out, w }
    // usage.go:647-650
    const ( HeldShare = 4; ThinkPace = 20 )
    // usage.go:657-663
    func (r Record) Decode() (tokens int, w int64) {
        if r.ReasoningHidden && r.FirstText <= 0 { return 0, 0 }
        return DecodeOf(r.Output, r.Reasoning, r.Millis, r.TTFT,
            r.FirstText, r.Flow, r.FirstReasoning) }
    // ledger.go:810-811
    const ( CodexWindowMs = 1000; CodexBodyTokens = 100 )
    // ledger.go:824
    if w > 0 && r.codexTurn() && (w < CodexWindowMs || n < CodexBodyTokens) { … }


原件里三处「为什么」的逐字注释（`usage.go:564-566`）：

> The bounds are wide of any real stream: the fastest vendors write a few thousand tokens a
> second, and a tenth of a second is the least a stream's timing tells anything by.

`usage.go:643-646`：

> HeldShare and ThinkPace tell a reply held back and let go in a burst (DecodeOf): its content
> came in under a quarter of its window, or its answer at over 20 times the pace its reasoning
> came.

## 五处缺口（如实说，不许当成已解决）

1. **零生产方**：见上。`ttft` / `first_text` / `flow` 三个数 pool 今天没有任何写方。
2. **`MIN_DECODE_MS` / `MAX_DECODE_SPEED` 是经验值**：原件注释只有那一句话的解释，两个数
   **不是**从数据里推出来的。照抄而不自行调（改它 = 换判据）。
3. **`first_reasoning` 无来源**：pool 的日志里没有单独的「首个推理块」事件，今天调用方只能
   传 `None`（或空序列 —— 与 `None` 同义）。
4. **`reasoning_hidden` 无来源**：magpie 从 vendor 的响应判断推理是否被藏；pool 只看工人日志，
   判不出「这一轮有没有把推理藏起来」。
5. **`codex_short()` 只搬那一道闸**，没搬它在 `ledger.go:824` 上下文里的用法 —— 那里还要求
   `r.codexTurn()`（`r.Source == "log" && r.Agent == "codex" && r.TTFT > 0`），pool 侧没有
   「这是不是 Codex 的 turn」这个概念。

★ 另外只在**合成数据**上验过：所有钉子都是构造出来的整数，没有拿一条真实的 magpie 流式记录
对账（那需要 Go 环境跑 `go test`）。

## 与设计原件判据 8 的一处冲突（按源码实现，如实交代）

设计原件（与卡规格判据 8）写 `tells(out=200, reasoning=150, ms=5000, ttft=500, first_text=0,
flow=100, first_reasoning=[600]) == (50, 4400)`。**这条期望值在它自己的 Go 依据下不成立**，
两处：

* `usage.go:622-623` 的 `first_reasoning` 分支**只改 `start`**（`start = firstReasoning[0]`），
  **不**像 `first_text` 分支那样 `out = out - reasoning`。原件注释也明说「can time **all
  output** from firstReasoning」。所以 token 是 `200`，不是 `50`。
* 同一组入参下 `w = 5000 - 600 = 4400`，而 `usage.go:626` 的 `flow > 0 && flow*HeldShare < w`
  实测为 `100 * 4 = 400 < 4400` ⇒ 真 ⇒ **先被「末端爆发」那道闸拦掉，返回 `(0, 0)`**，
  根本走不到返回值。

⇒ 本模块按 `usage.go:616-641` 实现（`first_reasoning` 分支不动 `out`），钉子
`test_first_reasoning_start` 钉的是源码真值，并在该用例里逐字写了这处出入。
这与本卡缺口 3（`_magpie_features.md` 的 F41 条把 Codex 阈值写错一个数量级，实测
`CodexWindowMs = 1000` / `CodexBodyTokens = 100`，在 `ledger.go:810-811`）是同一类错误：
**清单/设计稿抄错，源码是准的**。

## 边界（如实写）

* 本模块**纯算术**：零 I/O、零网络、零 sleep、不读环境、不读账本、不 import 本仓任何模块
  （只用 `collections.abc` 的 `Sequence` 做注解）。可被任何调用方安全 import。
* 全部比较用 `int`。★ 不许引入 `float` 中间量：原件全是 `int64`，`out * 1000 > MAX * w` 这种
  写法在 float 下会在边界上抖动（`10000 * 1000` 恰好等于 `10000 * 1000`，翻身就错判）。
* `first_reasoning` 是 `Sequence[int] | None`；**空序列与 `None` 同义**（原件是变参
  `firstReasoning ...int64`，只读 `[0]`）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 只在注解里用（本文件已开 `from __future__ import annotations`）
    from collections.abc import Sequence

# ---------------------------------------------------------------- 常量
#
# 六个数值逐字取自 magpie 源码（行号见模块 docstring 那张对应表）。★ 都**不是**策略旋钮：
# 它们标定的是「这段时间/token 数够不够说明任何事」，改成可配置就等于换判据。

#: magpie `usage.go:567 MinDecodeMs` —— 短于这么长的窗口说不清任何事（一成的秒）。
MIN_DECODE_MS: int = 100

#: magpie `usage.go:568 MaxDecodeSpeed` —— 每秒 token 上限；超了只可能是「爆发」不是流式写出。
MAX_DECODE_SPEED: int = 10000

#: magpie `usage.go:648 HeldShare` —— 内容只落在窗口的四分之一以内 ⇒ 是末端爆发。
HELD_SHARE: int = 4

#: magpie `usage.go:649 ThinkPace` —— 答案比推理快 20 倍以上 ⇒ 首字是随爆发一起到的。
THINK_PACE: int = 20

#: magpie `ledger.go:810 CodexWindowMs` —— Codex 那一档要求的最小窗口。
CODEX_WINDOW_MS: int = 1000

#: magpie `ledger.go:811 CodexBodyTokens` —— Codex 那一档要求的最小 token 数。
CODEX_BODY_TOKENS: int = 100


def window(out: int, ms: int, ttft: int) -> int:
    """原件 `usage.go:574 DecodeWindow`：返回写这些 token 花掉的毫秒；0 = 不可测。

    四种「不可测」（原件那一个 `if` 的四段，顺序即判据）：**没写出来**（`out <= 0`）、
    **首字时间未知**（`ttft <= 0` —— ★ 这是 pool 侧的常态）、**窗口太短**
    （`w < MIN_DECODE_MS`）、**快到不可能是流式写出**（`out * 1000 > MAX_DECODE_SPEED * w`）。

    窗口是 `ms - ttft`：**首字之后**那一段，不是整轮墙钟（含排队与工具调用）。拿
    `duration_ms` 冒充它就是本模块要消灭的那个错。
    """
    w = ms - ttft
    if out <= 0 or ttft <= 0 or w < MIN_DECODE_MS or out * 1000 > MAX_DECODE_SPEED * w:
        return 0
    return w


def tells(
    out: int,
    reasoning: int,
    ms: int,
    ttft: int,
    first_text: int,
    flow: int,
    first_reasoning: Sequence[int] | None = None,
) -> tuple[int, int]:
    """原件 `usage.go:617 DecodeOf`：返回 (tokens, 窗口毫秒)；(0, 0) = 不可测。

    有推理的那一轮**只算答案**：`out - reasoning`（推理的 token 写在首字之前，落在窗口外，
    算进来会把「2,000 的思考 + 200 的回答、1.5 秒」读成 1,467 tok/s）。三种起点：

    * `first_text > 0` ⇒ 从首字起，token = `out - reasoning`；
    * 否则 `first_reasoning[0] >= ttft` 且 `flow > 0` 且 `reasoning <= out` ⇒ 从首个推理块起，
      **token 仍是 `out`**（原件「can time all output from firstReasoning」）；
    * 都不满足 ⇒ `(0, 0)`（**不能拿推理的 token 冒充答案**）。

    两道「末端爆发」闸（`usage.go:626-631`）：内容只落在窗口 `1 / HELD_SHARE` 以内 ⇒ 不可测；
    答案比推理快 `THINK_PACE` 倍以上 ⇒ 不可测（首字是随爆发一起到的）。
    """
    start = ttft
    if reasoning > 0:
        if first_text > 0:
            out, start = out - reasoning, first_text
        elif (
            first_reasoning is not None
            and len(first_reasoning) > 0
            and first_reasoning[0] >= ttft
            and flow > 0
            and reasoning <= out
        ):
            start = first_reasoning[0]
        else:
            return 0, 0
    if ttft <= 0:
        return 0, 0
    w = window(out, ms, start)
    if w == 0:
        return 0, 0
    if flow > 0 and flow * HELD_SHARE < w:
        return 0, 0
    if reasoning > 0 and first_text > 0 and out * (first_text - ttft) > THINK_PACE * reasoning * w:
        return 0, 0
    return out, w


def tells_record(
    *,
    output: int,
    reasoning: int,
    millis: int,
    ttft: int,
    first_text: int,
    flow: int,
    reasoning_hidden: bool = False,
    first_reasoning: Sequence[int] | None = None,
) -> tuple[int, int]:
    """原件 `usage.go:657 (Record) Decode`：先过 `reasoning_hidden` 那一道，再转 `tells`。

    推理被 vendor 藏起来、又拿不到首字 ⇒ 那次「没有答案文本」不是「答案在推理里」，而是
    **推理根本没进流**，起点无从得知 ⇒ `(0, 0)`。有首字则照常走 `tells`（不是无条件回 0）。
    """
    if reasoning_hidden and first_text <= 0:
        return 0, 0
    return tells(output, reasoning, millis, ttft, first_text, flow, first_reasoning)


def codex_short(w: int, n: int) -> bool:
    """原件 `ledger.go:824` 的那一道：窗口或 token 不到 Codex 的门槛 ⇒ 不算速度。

    原件判据逐字是 `w < CodexWindowMs || n < CodexBodyTokens`（**严格小于**：恰好等于门槛
    就算够长）。★ 只对 Codex 的 turn 适用（原件前置 `r.codexTurn()`），
    **不许**当通用门槛套到别的轮次上 —— 那会把一次正常快回答判成不可测。
    """
    return w < CODEX_WINDOW_MS or n < CODEX_BODY_TOKENS
