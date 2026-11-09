r"""一行说完「现在能不能派」—— magpie `statusline` 移植进 pool（卡 A358 · T-AG571）。

## 为什么有它

pool 已经能答「这个 (卡, 模型) 此刻是什么态」（`tools/pool_quota.py` 的四态 + `render()` 多行
报告，每行都在念判据）。答不出的是另一件事：**一眼能看完、不占屏**的一行。

magpie 的 `internal/cli/statusline_cli.go`（全文 172 行）解决的就是这件事 —— Claude Code 只在
那条命令结束时显示一行，所以多一个字都是噪音。它有三个硬决定，本模块逐字照抄：

1. **问不到就打空行**（`statusline_cli.go:67` `return ""`）。空行 = 「这行不说话」；`"?"` 会被
   读成「有一个不知道的额度」—— 那是**多说了**。
2. **星号只给最新的那一条，且紧贴名字**（`:149` `name += "*"`）。`"A318*"` 不是 `"A318 *"`。
3. **`>= 1 小时` 不带秒**（`:151` 五对替换 + `:168` 只到整数百分比）—— 这是「一行」的硬约束。

## 与 `render()` 的关系（两份格式各有各的家）

`tools/pool_quota.py:519-535 render(st)` 是**多行**报告，它存在的理由是「把判据念出来」；
本模块是**一行**，它存在的理由是「不占屏」。所以：

* **不许**改 `render()` 一个字节，也**不许**给它加 `one_line=True` 开关（一个函数两种输出形态，
  两份测试会互相咬）；
* **不许**把 `_hms`（`HH:MM:SS`）改成 `short_hms`（`1h40m`）—— 前者是 `render()` 的判据。

## 纯判定：零 IO、零网络、不读钟

输入只有 `states` / `only` / `now` 三个参数。「现在」由调用方（`tools/pool_quota.py`）算好并
写进 `states["now"]` / `remaining_seconds`；本模块**不读文件、不读钟、不联网**（判据 15 由
`tests/test_pool_quota_line.py` 的 `ast` 钉子盯着）。

## 缺口（如实，进 changelog 的 gaps）

1. **pool 基本画不出百分比。** magpie 的 `w.Used`（`quotas.go:128`）在 pool 侧几乎零来源：真
   `gates/diag/quota-state.json` 的记录没有 `used`；仓外账本的 `used_percent` 今天只有 codearts
   写得进来（`tools/pool_accounts.py` 的 `record_probe_result()`，卡 E97 起的唯一写方），其它平台
   仍无，且窗口边界仍缺（`reset` / `span` 零来源 ⇒ `holds` 仍走 `clock`）。⇒ 一格只能是一个态
   标记 + 倒计时。**这不是取舍，是没料。**
2. **`LastServedAt` / `Last` 无对应物。** magpie 的 `*` 咬的是「这个号上次**答过话**」
   （`served.go:24` 30 天窗口）；pool 只有 `recorded_at`（上次**读到额度**的时刻）。本模块用
   `recorded_at` 顶替，**语义已经漂了** —— 星号在 pool 里该读作「最新读到的」。
3. **`windows` 多窗无对应物。** 一个 (卡, 模型) 只有一个 `reset_at` ⇒ magpie 的六级 switch
   （`Unlimited`/`Balance`/`Text`/`ResetsAt`/default）一支都用不上。
4. **`alias` / `user` / `provider` 三个可比值无对应物。** 本模块等比缩到三个串：
   `card` / `model` / `card/model`。
5. **`MAX_ONLY = 32` 没有 magpie 出处。** magpie 的 `only` 是人打的、无上限。这条是本设计
   **新加**的护栏：将来若被脚本调用，无上限的 `only` 会变成一次 O(n·m) 扫描。**别把它写进
   「照 magpie 移植」的话里。**
6. **只在合成读数上验过。** 真 `quota-state.json` 里 `kind` 的取值是 `"限流"` / `"余额耗尽"`，
   而 `status()` 产出的是四个中文字面量（`"限流中"` 等）—— **`kind` 与 `state` 是两套字面量**。
   本模块只认 `status()` 的产出，不认 `kind`。

## 用法

    from pool.quota_line import one_line
    print(one_line(states, only=("A318",), now="2026-10-31T12:00:00+08:00"))
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime
    from typing import Any

__all__ = [
    "CELL_SEP",
    "HOUR_MIN",
    "MAX_ONLY",
    "MINUTE_S",
    "NO_DATA",
    "SEP",
    "SHORT",
    "STAR",
    "UNKNOWN_HMS",
    "freshest",
    "matches",
    "one_line",
    "pick",
    "short_hms",
    "short_state",
]

#: 段与段之间的分隔符（照 `statusline_cli.go:88` 的 `strings.Join(parts, " | ")`）。
SEP: str = " | "

#: 一格之内的分隔符（照 `statusline_cli.go:171` 的 `strings.Join(cells, " ")`）。
CELL_SEP: str = " "

#: 「最新那条」的星号（照 `statusline_cli.go:149`）—— **紧贴名字，前面不加空格**。
STAR: str = "*"

#: 四态 → 一格里的那个短标记。`""` 表示「这里要用 `short_hms` 算出来的倒计时」。
SHORT: dict[str, str] = {
    "限流中": "",
    "已过期，需重新探测": "过期",
    "余额耗尽": "耗尽",
    "未记录": "未记录",
}

#: 算不出来时的占位（照 `tools/pool_quota.py:511-516` `_hms` 的同款口径）。
UNKNOWN_HMS: str = "?"

#: 一小时 / 一分钟的秒数 —— `HOUR_MIN` 是「带不带秒」那条硬约束的分界线。
HOUR_MIN: int = 3600
MINUTE_S: int = 60

#: 「没有可显示的东西」的返回值 = 空串（照 `statusline_cli.go:67` 的 `return ""`）。
#: **不是** `"?"`、**不是** `"（无）"` —— 空行 = 这行不说话；`"?"` = 多说了有个不知道的额度。
NO_DATA: str = ""

#: `only` 的条数上限。★ **这条没有 magpie 出处**（magpie 的 `only` 由人打、无上限）：
#: 它是 pool **新加**的护栏，为的是将来被脚本调用时别把无上限的 `only` 变成一次 O(n·m) 扫描。
MAX_ONLY: int = 32


def short_state(st: Mapping[str, Any]) -> str:
    """四态 → 一格里的那个短标记。

    `限流中` 的标记是 `short_hms(st["remaining_seconds"])`（**不是** `_hms` 的 `HH:MM:SS`）。
    不认识的 `state` 直接 `KeyError`（照 `tools/pool/holds.py:142-144` `why_text` 的口径：
    只认那一小撮原串，别的直接炸，**不编话兜底**）。
    """
    tag = SHORT[st["state"]]
    if tag:
        return tag
    return short_hms(st["remaining_seconds"])


def short_hms(seconds: int | None) -> str:
    """秒数 → 一格里的倒计时：`6024 → "1h40m"`、`59 → "0m59s"`、`None / 负数 → "?"`。

    ★ **`>= 3600` 不许带秒**（`6024` 是 `"1h40m"`，不是 `"1h40m24s"`）—— 这是「一行」的硬约束
    （照 `statusline_cli.go:151` 的五对替换：`" hours"→"h"`、`" days"→"d"`）。
    """
    if seconds is None or seconds < 0:
        return UNKNOWN_HMS
    total = int(seconds)
    if total >= HOUR_MIN:
        return f"{total // HOUR_MIN}h{total % HOUR_MIN // MINUTE_S}m"
    minutes, rest = divmod(total, MINUTE_S)
    return f"{minutes}m{rest}s"


def matches(st: Mapping[str, Any], only: Sequence[str]) -> bool:
    """这个 (卡, 模型) 命中 `only` 里的任何一个吗 —— **且只比三个字符串**。

    照 `statusline_cli.go:128-137` 的 `statuslineMatches`，从五个可比值等比缩到三个：
    `st["card"]` / `st["model"]` / `f"{card}/{model}"`。**空串不参与**；比较大小写不敏感。
    """
    card = str(st["card"] or "")
    model = str(st["model"] or "")
    pool = (card, model, f"{card}/{model}")
    want = {o.casefold() for o in only if o}
    return any(c and c.casefold() in want for c in pool)


def pick(states: Sequence[Mapping[str, Any]], *,
         only: Sequence[str] = ()) -> list[dict[str, Any]]:
    """谁能占一格（对应 `statusline_cli.go:108-126` `statuslineCards`）。

    三条，顺序即判定：

    1. 丢掉 `state == "未记录"` 的条目、丢掉 `recorded_at` 为 `None` 的条目，**其余全留**
       （`未记录` 不占屏 —— 没读到过任何东西就不说话）；
    2. `only` 非空 ⇒ 只留 `matches()` 命中的，且**「最近那批优先」不生效**
       （照 `:122` 的 `len(only) == 0 &&`：人点名要看的，不许被日期裁掉）；
    3. `only` 为空 ⇒ 只留 `recorded_at` **最晚那一天**的那批（同一天 = 同一个
       `recorded_at[:10]`，照 `:122` 的 `len(served) > 0 ⇒ return served`）。
    """
    only = tuple(only or ())
    if len(only) > MAX_ONLY:
        raise ValueError(f"only 最多 {MAX_ONLY} 条（pool 的护栏，不是 magpie 的口径）")
    kept = [dict(st) for st in states
            if st["state"] != "未记录" and st.get("recorded_at") is not None]
    if only:
        return [st for st in kept if matches(st, only)]
    if not kept:
        return []
    days = [str(st["recorded_at"])[:10] for st in kept]
    latest = max(days)
    return [st for st, day in zip(kept, days, strict=True) if day == latest]


def freshest(states: Sequence[Mapping[str, Any]]) -> str:
    """`recorded_at` 最新那条的 `f"{card}/{model}"`；判不出 ⇒ `""`；并列取**第一条**。

    ★ 缺口 2：pool 没有 magpie 的 `LastServedAt`（「上次答过话」），这里用 `recorded_at`
    （「上次读到额度」）顶替 —— 语义已经漂了，星号该读作「最新读到的」。
    """
    best_at: str | None = None
    key = NO_DATA
    for st in states:
        at = st.get("recorded_at")
        if at is None:
            continue
        at = str(at)
        if best_at is None or at > best_at:  # 严格大于 ⇒ 并列保留先出现的那条
            best_at = at
            key = f"{st['card']}/{st['model']}"
    return key if best_at is not None else NO_DATA


def one_line(states: Sequence[Mapping[str, Any]], *, only: Sequence[str] = (),
             now: datetime | str | None = None) -> str:
    """唯一出口：把这些态说成一行。**没有可显示的东西 ⇒ `""`**（照 `statusline_cli.go:67`）。

    一格的拼法逐字（判据 9）：`f"{card}/{model}"` +（`*` 若 freshest）+ `CELL_SEP` +
    `short_state(st)`；段间只用 `SEP`。**输入顺序即输出顺序**（不排序、不按卡聚合 —— 排序归
    调用方，本函数只渲染）。

    `now` 只被接收、**不被读取**：判断「现在」归 `status()`（本函数不读钟，判据 15）。
    """
    del now  # 明文声明：本函数不读钟（`remaining_seconds` 已由调用方算好）
    picked = pick(states, only=only)
    if not picked:
        return NO_DATA
    star = freshest(picked)
    cells: list[str] = []
    for st in picked:
        name = f"{st['card']}/{st['model']}"
        if name == star:
            name += STAR
        cells.append(name + CELL_SEP + short_state(st))
    return SEP.join(cells)
