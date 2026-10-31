"""按**请求**而不是按轮统计结局（移植自 magpie `internal/usage/usage.go:777-806`）。

★ 与 magpie 的差别（如实）：
  · magpie 的 `Tries`/`HandedOn` 由网关的**路由重试**写；pool 的是 `wb_dispatch` 的
    **续跑循环**（`should_resume`），两者语义不同一层：magpie 的重试是「换上游再试一次」，
    pool 的续跑是「同一个工人带同一会话接着干」。所以 `Tries` 在 pool 侧叫「续了几轮」。
  · magpie 有 `RouteID` 能把「同一次请求的多个 try」串起来；pool **没有**这种 id，
    只能按「同卡、连续轮次、前一轮 handed_on」串 —— 这是**弱口径**，见 §6。
★ 本模块**只读**，不改 `wb-usage.jsonl` 一个字节。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from typing import Any

# ============================================================ 为什么按请求算（而不按轮）
#
# `gates/diag/wb-usage.jsonl` 里**每轮一行**，于是「轮数」随处可算（`usage_summary()` 的
# 「本卡 N 轮」、`ledger_spend.sums()` 的 `calls`）—— 那些读的是**轮**，是对的，本模块
# 一个都不改（改它们就是把「按轮」偷换成「按请求」，两套口径混成一份）。
#
# 缺的是另一半：**这个请求最后到底成没成、一共试了几次**。`轮次` 只给序号，给不出
# 「第 2 行的失败是否被第 3 行接住」；`判决` 是自由文本，拿它猜结构就是拿字符串猜。
# ⇒ 结局判据收在这里**一份**（照 magpie `Totals.count()`）：交出去的 try 既不是请求，
#   也不是它自己的失败。谁要「按请求算」就调本模块，**不许**另写一份（第二份真源）。
#
# 判据逐条有出处（改之前先读那一行 Go）：
#   · `is_failed()`     ← `internal/usage/ledger.go:50`（差异见下）
#   · `is_outcome()`    ← `internal/usage/usage.go:777-806` 的 `if r.HandedOn { return }`
#   · `request_of()`    ← `internal/usage/usage.go:178-188` 的 `Tries`/`HandedOn`
#   · `count_requests()`← `internal/usage/usage.go:777-806` 的 `Totals.count()`
#
# ## 与原件的一处差异（如实记，别照抄 Go）
#
# `ledger.go:50` 是 `r.Status >= 400 || r.Error != ""` —— 那是 **HTTP 状态码 + 上游错误串**。
# pool 的 `退出码` 是**进程退出码**（0 成功 / 4 工人非零 / 6 被掐 / 7 额度停），`判决` 是
# **判决文本**（正常收工写的就是非空串「正常收工」）。两样都不是原件那两样的同构物，所以：
#   · **`code != 0` 判失败**：`code >= 400` 只能认出 HTTP 那一段，`code=1` 那种会被漏掉
#     （钉子 `test_is_failed_uses_the_exit_code_not_the_verdict_text` 第三组输入正是 `code=1`）；
#   · **`reason` 只在 `!= "" and != "正常收工"` 时才算失败**：照抄 `reason != ""` 会把每一行
#     都判成失败 —— pool 的正常收工判决就是非空串。
#
# ## 用法
#
#     from pool import outcomes
#     totals = outcomes.count_requests(rows, card="A355")
#     # {"requests": 1, "errors": 0, "retried": 1, "handed_on": 1}
#
# `rows` 是 `wb-usage.jsonl` 读出来的 dict 列表（老行没有 `tries`/`handed_on` 键也不崩）。
# `count_requests()` **不返回 token** —— token 归 `tools/pool/ledger_spend.py` 的 `sums()`；
# 两条口径不混（一条按人头、一条按用量）。

#: 行里「本请求一共试了几轮（含自己这一轮）」的键（`usage.go:187` `Tries`）。
OUTCOME_TRIES = "tries"
#: 行里「这一轮失败并把请求交给了下一轮」的键（`usage.go:188` `HandedOn`）。
OUTCOME_HANDED_ON = "handed_on"
#: 行里「上游自报的结束原因」的键（`usage.go:161` `Stop`；`""` = 没报，不写 `"none"`）。
OUTCOME_STOP = "stop"
#: 三个 service tier（`usage.go:100-102`）；各自独立，`tier_served` 绝不从别的推。
OUTCOME_TIERS = ("tier_asked", "tier_sent", "tier_served")

#: `count_requests()` 返回的四个键（照 `usage.go:777-806` 的三个计数器 + 交出去的 try）。
COUNT_KEYS: tuple[str, ...] = ("requests", "errors", "retried", "handed_on")

#: pool 侧「正常收工」的判决文本 —— `append_usage_line()` 写的就是这一串（`reason or …`）。
#: ★ 它不是公开判据的一部分，只是把 `is_failed()` 里那个字面量收一处（别在多处硬写）。
_NORMAL_STOP = "正常收工"


@dataclass(frozen=True)
class Outcome:
    """一行的**结局视图**（判据 3/5/6/7/8）。

    缺键的老行读成「一轮一请求」：不崩、也**不**当 `handed_on`（老行就是不知道）。
    """

    card: str
    round: int                 # ← 行里的 "轮次"
    tries: int = 1             # ← 本请求一共试了几轮（含自己这一轮）
    handed_on: bool = False    # ← 这一轮失败并把请求交给了下一轮
    stop: str = ""             # ← 上游自报的结束原因（"" = 没报）
    tier_asked: str = ""
    tier_sent: str = ""
    tier_served: str = ""


def _int(row: Mapping[str, Any], key: str, *, floor: int | None = None) -> int:
    """行里的一个整数列：只认 int（`bool` 不算），缺 / 坏 ⇒ `floor`（给了的话）或 0 —— 不猜。"""
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return 0 if floor is None else floor
    if floor is not None and value < floor:
        return floor
    return value


def _text(row: Mapping[str, Any], key: str) -> str:
    """行里的一个字符串列：不是 str 就当空串（`""` 恰好是「上游没报」的正确取值）。"""
    value = row.get(key)
    return value if isinstance(value, str) else ""


def is_failed(code: int, reason: str) -> bool:
    """这一轮算不算失败 —— **看退出码**；判决文本只在它不是「正常收工」时才算一笔。

    ★ 为什么不是 `ledger.go:50` 的逐字移植（`code >= 400 or reason != ""`）：
      · `code >= 400` 是 **HTTP 状态码**的口径；pool 的 `退出码` 是**进程退出码**，
        `code=1` 那种失败会被它整条漏掉；
      · pool 的 `reason` 是**判决文本**，正常收工写的就是非空串「正常收工」，
        照抄 `reason != ""` 会把每一行都判成失败。
    ⇒ 两处都按 pool 的真实取值写死，见模块注释「与原件的一处差异」。
    """
    if code != 0:
        return True
    return bool(reason) and reason != _NORMAL_STOP


def is_outcome(row: Mapping[str, Any]) -> bool:
    """只有**非** `handed_on` 的行才是「请求的结局」（`usage.go:777-806` 的 `if r.HandedOn`）。"""
    return not row.get(OUTCOME_HANDED_ON)


def request_of(rows: Sequence[Mapping[str, Any]], *, card: str) -> list[Outcome]:
    """把该卡的行读成 `Outcome` 列表（**按行序**，不重排、不去重、不合并）。

    ★ 弱口径（如实）：magpie 用 `RouteID` 把「同一次请求的多个 try」串起来，pool 没有这个
      id，只能靠「同卡 + 连续 `轮次` + 前一轮 `handed_on`」推断 —— 所以这里既不排序也不
      合并：串法属于读方，`count_requests()` 只数**结局行**、不猜串。同卡并发两条流水时
      这个推断会错（届时得加显式 id，那是另一张卡）。
    """
    outcomes: list[Outcome] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("卡") != card:
            continue
        outcomes.append(Outcome(
            card=card,
            round=_int(row, "轮次"),
            tries=_int(row, OUTCOME_TRIES, floor=1),
            handed_on=bool(row.get(OUTCOME_HANDED_ON, False)),
            stop=_text(row, OUTCOME_STOP),
            tier_asked=_text(row, OUTCOME_TIERS[0]),
            tier_sent=_text(row, OUTCOME_TIERS[1]),
            tier_served=_text(row, OUTCOME_TIERS[2]),
        ))
    return outcomes


def count_requests(rows: Sequence[Mapping[str, Any]], *, card: str) -> dict[str, int]:
    """`{"requests", "errors", "retried", "handed_on"}` —— 口径逐字照 `usage.go:777-806`。

    * `handed_on` 的行**不计** `requests`、**不计** `errors`（它是交出去的 try，不是结局）；
    * `errors` = 是结局**且** `is_failed(code, reason)`；
    * `retried` = 是结局、**不**失败、且 `tries > 1`（后来的 try 答上了，不是失败）；
    * **不返回 token**（token 归 `ledger_spend.sums()`；本条是「按人头」，那是「按用量」）。

    老行（没有 `tries`/`handed_on` 键）不崩：`tries=1`、`handed_on=False`（判据 8）。
    """
    totals = dict.fromkeys(COUNT_KEYS, 0)
    for row in rows:
        if not isinstance(row, dict) or row.get("卡") != card:
            continue
        if row.get(OUTCOME_HANDED_ON, False):
            totals["handed_on"] += 1
            continue
        totals["requests"] += 1
        if is_failed(_int(row, "退出码"), _text(row, "判决")):
            totals["errors"] += 1
        elif _int(row, OUTCOME_TRIES, floor=1) > 1:
            totals["retried"] += 1
    return totals
