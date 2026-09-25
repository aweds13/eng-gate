"""人读排版 —— **只排版，不取数、不算数**。

每条命令的 JSON 原样来自 HTTP 边界（`call.py`），这里只把同一份 JSON 折成几行中文。
这条界线是刻意的：任何"算一算再显示"都会变成第二套口径（界面一处、CLI 一处），
而口径只能有一处。需要原始数字就用 `--json`。

唯一一处问时间的地方是 `today` 的那个日期标签（`/api/summary` 的响应里没有日期）——
走的是全仓唯一的时钟出口 `timeflow.clock`（T-G62），不自己取 `date.today()`。
"""

from __future__ import annotations

from typing import Any

from timeflow import clock


def _rec(data: Any) -> dict[str, Any]:
    return data if isinstance(data, dict) else {}


def _rows(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def _text(rec: dict[str, Any], key: str, default: str = "") -> str:
    value = rec.get(key)
    return default if value is None else str(value)


def _num(rec: dict[str, Any], key: str) -> float:
    value = rec.get(key)
    return float(value) if isinstance(value, (int, float)) else 0.0


def _minutes(hours: Any) -> int:
    """小时 → 分钟（只做单位换算，不改口径；四舍五入到整分钟）。"""
    return round(float(hours) * 60) if isinstance(hours, (int, float)) else 0


def _titles(rows: list[dict[str, Any]], key: str = "title", limit: int = 10) -> list[str]:
    out = [f"  · {_text(row, key) or '（无标题）'}" for row in rows[:limit]]
    if len(rows) > limit:
        out.append(f"  …另有 {len(rows) - limit} 条（--json 看全）")
    return out


def _when(due: str) -> str:
    return f"（截止 {due}）" if due else ""


def today(data: Any) -> list[str]:
    rec = _rec(data)
    debt = _rows(rec.get("debt_items"))
    lines = [
        clock.today_iso() + " · 专注 " + str(_minutes(rec.get("invest_hours"))) + " 分钟"
        + " · 手动投入 " + str(rec.get("manual_hours", 0)) + " 小时",
        "复习 " + str(rec.get("review_count", 0)) + " 张 · 产出 "
        + str(rec.get("output_count", 0)) + " 条（KPI " + str(rec.get("output_kpi", 0))
        + " / 资产 " + str(rec.get("output_asset", 0)) + "）· 习惯 "
        + str(rec.get("habit_count", 0)) + " 次 · 收益 " + str(rec.get("gain_count", 0)),
        "债务 " + str(rec.get("debt_count", 0)) + " 项",
    ]
    for item in debt[:10]:
        lines.append(
            "  · " + _text(item, "title") + "（逾期 " + str(item.get("overdue_days", 0))
            + " 天 / " + _text(item, "degree") + "）"
        )
    if len(debt) > 10:
        lines.append("  …另有 " + str(len(debt) - 10) + " 项（--json 看全）")
    return lines


def plan(data: Any) -> list[str]:
    rows = _rows(data)
    if not rows:
        return ["今天的清单是空的。"]
    lines = ["今天 " + str(len(rows)) + " 项"]
    lines += [f"  · {_text(row, 'title')}{_when(_text(row, 'due_date'))}" for row in rows[:20]]
    if len(rows) > 20:
        lines.append("  …另有 " + str(len(rows) - 20) + " 项（--json 看全）")
    return lines


def overdue(data: Any) -> list[str]:
    rows = _rows(data)
    if not rows:
        return ["没有逾期项。"]
    return ["逾期 " + str(len(rows)) + " 项"] + [
        f"  · {_text(row, 'title')}{_when(_text(row, 'due_date'))}" for row in rows[:20]
    ]


def due(data: Any) -> list[str]:
    rows = _rows(data)
    if not rows:
        return ["今天没有到期的复习卡。"]
    return ["到期复习 " + str(len(rows)) + " 张"] + [
        "  · " + _text(row, "title") + "（到期 " + _text(row, "due_date")
        + " · 已复习 " + str(row.get("reps", 0)) + " 次）"
        for row in rows[:20]
    ]


def done(data: Any) -> list[str]:
    rec = _rec(data)
    tasks = _rows(rec.get("tasks"))
    steps = _rows(rec.get("steps"))
    outputs = _rows(rec.get("outputs"))
    lines = [
        _text(rec, "date") + " 做成了 " + str(len(tasks)) + " 件任务 · " + str(len(steps))
        + " 步 · " + str(len(outputs)) + " 条产出（KPI " + str(rec.get("output_kpi", 0))
        + " / 资产 " + str(rec.get("output_asset", 0)) + "）"
    ]
    lines += [f"  · 任务 {_text(row, 'title')}" for row in tasks[:10]]
    lines += [f"  · 步骤 {_text(row, 'title')}" for row in steps[:10]]
    lines += [
        "  · 产出 " + _text(row, "kind") + " ×" + str(row.get("value", 0))
        + ("：" + _text(row, "note") if _text(row, "note") else "")
        for row in outputs[:10]
    ]
    return lines


def week(data: Any) -> list[str]:
    rec = _rec(data)
    days = _rows(rec.get("days"))
    peak = max([_num(day, "focus_minutes") for day in days] or [0.0])
    lines = [
        _text(rec, "start") + " ~ " + _text(rec, "end") + " · 专注 "
        + str(rec.get("focus_hours", 0)) + " 小时 · 手动 " + str(rec.get("manual_hours", 0))
        + " 小时",
        "复习 " + str(rec.get("review_count", 0)) + " 张 · 产出 "
        + str(rec.get("output_count", 0)) + " 条 · 有投入 " + str(rec.get("active_days", 0))
        + " 天 · 周日债务 " + str(rec.get("debt_count", 0)) + " 项",
    ]
    for day in days:
        minutes = _num(day, "focus_minutes")
        bar = "█" * (round(8 * minutes / peak) if peak else 0)
        lines.append(f"  {_text(day, 'date')} {bar} {round(minutes)} 分")
    note = _text(rec, "steady_note")
    if note:
        lines.append("  " + note)
    return lines


def trend(data: Any) -> list[str]:
    rows = _rows(data)
    if not rows:
        return ["窗口里没有数据。"]
    return [
        "  " + _text(row, "date") + " 专注 " + str(round(_num(row, "focus_minutes"))) + " 分"
        + " · 复习 " + str(row.get("review_count", 0))
        + " · 产出 " + str(row.get("output_count", 0))
        + " · 债务 " + str(row.get("debt_count", 0))
        for row in rows
    ]


def habits(data: Any) -> list[str]:
    rows = _rows(data)
    if not rows:
        return ["还没有习惯。"]
    return ["习惯 " + str(len(rows)) + " 个"] + [
        "  · " + _text(row, "name") + "（连续 " + str(row.get("streak", 0)) + " 天 · 近一年 "
        + str(len(row.get("logs") or [])) + " 天）"
        for row in rows[:20]
    ]


def check(data: Any) -> list[str]:
    """自检 / 同步现状：**原样列字段**，不挑不拼（免得 CLI 与接口的口径各说各话）。"""
    rec = _rec(data)
    if not rec:
        return ["没有返回值。"]
    return [f"  {key}: {value}" for key, value in rec.items()]


def tasks(data: Any) -> list[str]:
    rows = _rows(data)
    if not rows:
        return ["没有任务。"]
    lines = ["任务 " + str(len(rows)) + " 条"]
    lines += [f"  · {_text(row, 'title')}{_when(_text(row, 'due_date'))}" for row in rows[:30]]
    if len(rows) > 30:
        lines.append("  …另有 " + str(len(rows) - 30) + " 条（--json 看全）")
    return lines


def upcoming(data: Any) -> list[str]:
    rows = _rows(data)
    if not rows:
        return ["近期没有临期/逾期的考核项。"]
    lines = ["临期与逾期 " + str(len(rows)) + " 项"]
    for row in rows[:20]:
        days = row.get("days_until")
        if days is None:
            when = "没有截止日"
        elif isinstance(days, int) and days < 0:
            when = "已逾期 " + str(-days) + " 天"
        else:
            when = "还有 " + str(days) + " 天"
        course = _text(row, "course_name")
        # 考核项字段叫 `name`（`title` 是任务那边的叫法）—— 两个都认，免得又靠猜
        label = _text(row, "title") or _text(row, "name")
        lines.append("  · " + label + (f"（{course}）" if course else "") + " · " + when)
    return lines


def focus(data: Any) -> list[str]:
    rec = _rec(data)
    if not rec:
        return ["现在没有进行中的专注。"]
    return [
        "进行中：任务 " + (_text(rec, "task_id") or "（未绑定任务）"),
        "  开始于 " + _text(rec, "started_at"),
    ]


def board(data: Any) -> list[str]:
    rec = _rec(data)
    groups = _rows(rec.get("groups"))
    lines = [
        "视角 " + _text(rec, "view") + " · 共 " + str(rec.get("total", 0)) + " 条 · 显示 "
        + str(rec.get("shown", 0)) + " 条"
    ]
    note = _text(rec, "note")
    if note:
        lines.append("  " + note)
    for group in groups:
        lines.append("  " + _text(group, "assignee") + "（" + str(group.get("count", 0)) + " 条）")
        for item in _rows(group.get("items"))[:20]:
            title = _text(item, "task_title") or "（任务已删除）"
            lines.append("    · " + title + " [" + _text(item, "status") + "]")
    return lines
