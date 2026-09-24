"""备忘录 + 知识资产引用句柄（SR-F8.1~F8.4）。对应 AC 备忘录。

备忘录：碎片化任务/想法本地随手记；可顺手建成任务 + 加到期。
知识资产：本软件**只存引用句柄**（Vault 相对路径 / KB-... 资源 ID），
读/写 Obsidian、PDF 库交给「知识资产项目」，本软件不直接碰 Vault 文件。
产出评价器接口（SR-F8.4）：第一版手动粗颗粒入口，合同待知识管理项目对齐。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from timeflow import clock

if TYPE_CHECKING:
    import sqlite3


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> str:
    return clock.now().isoformat(timespec="seconds")


def create_memo(
    conn: sqlite3.Connection,
    text: str,
    ref_handle: str | None = None,
    task_id: str | None = None,
) -> str:
    """记一条备忘录；ref_handle 为可选的知识资产引用句柄（Vault路径/KB-id）。"""
    text = text.strip()
    if not text:
        raise ValueError("备忘录内容不能为空")
    mid = _uid()
    conn.execute(
        "INSERT INTO memos (id, text, ref_handle, task_id, created_at) VALUES (?,?,?,?,?)",
        (mid, text, ref_handle, task_id, _now()),
    )
    conn.commit()
    return mid


def delete_memo(conn: sqlite3.Connection, memo_id: str) -> None:
    """删除备忘录（幂等）。关联任务不自动删除（R2：两者互相关联但不连坐）。"""
    conn.execute("DELETE FROM memos WHERE id = ?", (memo_id,))
    conn.commit()


def memo_to_task(
    conn: sqlite3.Connection,
    memo_id: str,
    due_date: str | None = None,
    is_myday: bool = True,
) -> str:
    """把备忘录转成任务（SR-F8 R2）：备忘录保留，并在其上记录 task_id，二者互相可查。

    入口在备忘录页（「转为任务」）；标题沿用备忘录正文（超长由前端截断显示）。
    """
    row = conn.execute("SELECT * FROM memos WHERE id = ?", (memo_id,)).fetchone()
    if row is None:
        raise KeyError(f"备忘录不存在: {memo_id}")
    from timeflow.core import tasks as tm

    task = tm.create_task(
        conn, title=str(row["text"]), due_date=due_date, is_myday=is_myday
    )
    conn.execute("UPDATE memos SET task_id = ? WHERE id = ?", (task.id, memo_id))
    conn.commit()
    return task.id


def list_memos(conn: sqlite3.Connection) -> list[dict[str, object]]:
    """列出全部备忘录（倒序，最新在前）。"""
    rows = conn.execute("SELECT * FROM memos ORDER BY created_at DESC").fetchall()
    return [
        {
            "id": r["id"],
            "text": r["text"],
            "ref_handle": r["ref_handle"],
            "task_id": r["task_id"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


# ---- 产出评价器接口（SR-F8.4）----
def add_output_entry(
    conn: sqlite3.Connection,
    value: float,
    kind: str = "asset",
    note: str | None = None,
    ref_handle: str | None = None,
) -> str:
    """记一条产出流水（产出轴）。第一版手动粗颗粒；value 由用户/评价器给出。

    第 5 步（产出轴物化）：除旧表 `ledger_entries`（兼容保留）外，同时发 `output.manual` **事实**，
    使产出与投入一样由事实层承载（F2 规格 §4 定案的新/旧两条路）。
    """
    eid = _uid()
    today = clock.today_iso()
    conn.execute(
        "INSERT INTO ledger_entries (id, axis, kind, value, date, note, ref_handle, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (eid, "output", kind, value, today, note, ref_handle, _now()),
    )
    conn.commit()
    _record_output_fact(
        conn, entry_id=eid, kind=kind, value=value, note=note,
        ref_handle=ref_handle, occurred_on=today,
    )
    return eid


def retract_output_entry(conn: sqlite3.Connection, entry_id: str) -> bool:
    """撤销一条产出（OP-38 可逆）：追加 `output.retracted` 反向事实，不删历史。幂等。"""
    from timeflow.core import facts as facts_mod

    target = _find_output_fact(conn, entry_id)
    if target is None:
        raise KeyError(f"产出记录不存在: {entry_id}")
    if _is_retracted(conn, entry_id):
        return False
    target_kind = str(target["value_text"] or "")
    raw_value = target["value_num"]
    target_value = float(raw_value) if isinstance(raw_value, (int, float)) else 0.0
    extra = {
        "entry_id": entry_id,
        "kind": target_kind,
        "value": target_value,
        "migrated": False,
    }
    facts_mod.record(
        conn,
        kind="output.retracted",
        subject_type="output",
        subject_id=entry_id,
        value_num=target_value,
        value_text=target_kind,
        extra=extra,
        source="desktop",
    )
    facts_mod.publish("output.retracted", {"entry_id": entry_id, **extra})
    return True


def _record_output_fact(
    conn: sqlite3.Connection,
    entry_id: str,
    kind: str,
    value: float,
    note: str | None,
    ref_handle: str | None,
    occurred_on: str,
) -> None:
    from timeflow.core import facts as facts_mod

    if value < 0:
        raise ValueError("产出值不能为负")
    extra = {
        "entry_id": entry_id,
        "kind": kind,
        "note": note,
        "ref_handle": ref_handle,
    }
    facts_mod.record(
        conn,
        kind="output.manual",
        subject_type="output",
        subject_id=entry_id,
        value_num=float(value),
        value_text=kind,
        extra=extra,
        source="desktop",
    )
    facts_mod.publish("output.manual", {"entry_id": entry_id, **extra})


def _output_facts(conn: sqlite3.Connection, day: str | None = None) -> list[dict[str, object]]:
    """某日产出事实（默认今天，按发生时刻归属）。"""
    from timeflow.core import facts as facts_mod

    d = day or clock.today_iso()
    return facts_mod.query(
        conn, kind="output.manual", since=f"{d}T00:00:00", until=f"{d}T23:59:59"
    )


def list_outputs(conn: sqlite3.Connection, day: str | None = None) -> list[dict[str, object]]:
    """某日产出流水（含是否已撤销），供前端展示与核对。"""
    out: list[dict[str, object]] = []
    for fact in _output_facts(conn, day):
        entry_id = str(fact["subject_id"])
        extra_obj = fact["extra"]
        extra: dict[str, object] = extra_obj if isinstance(extra_obj, dict) else {}
        out.append(
            {
                "entry_id": entry_id,
                "kind": fact["value_text"],
                "value": fact["value_num"],
                "note": extra.get("note"),
                "ref_handle": extra.get("ref_handle"),
                "occurred_at": fact["occurred_at"],
                "retracted": _is_retracted(conn, entry_id),
            }
        )
    return out


def _find_output_fact(
    conn: sqlite3.Connection, entry_id: str
) -> dict[str, object] | None:
    from timeflow.core import facts as facts_mod

    rows = facts_mod.query(
        conn, kind="output.manual", subject_type="output", subject_id=entry_id
    )
    return rows[-1] if rows else None


def _is_retracted(conn: sqlite3.Connection, entry_id: str) -> bool:
    from timeflow.core import facts as facts_mod

    return bool(
        facts_mod.query(
            conn, kind="output.retracted", subject_type="output", subject_id=entry_id
        )
    )


def add_invest_entry(
    conn: sqlite3.Connection,
    value: float,
    kind: str = "focus",
    note: str | None = None,
) -> str:
    """记一条手动投入（投入轴）。

    **单位口径（2026-09-18 用户确认）：秒**，与 `focus.finished` 完全同口径 ——
    这样 `ledger.summary()` 里手动投入 = `sum(value_num)/3600`，无需按来源换算。

    除旧表 `ledger_entries`（兼容保留）外，同时发 `invest.manual` 事实；
    账本按「`invest.manual` − `invest.retracted`」计 `manual_hours`，
    且**不**并入 `invest_hours`（后者保持「只算专注」，口径不混）。
    """
    if value < 0:
        raise ValueError("投入值不能为负")
    eid = _uid()
    today = clock.today_iso()
    conn.execute(
        "INSERT INTO ledger_entries (id, axis, kind, value, date, note, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (eid, "invest", kind, value, today, note, _now()),
    )
    conn.commit()
    _record_invest_fact(conn, entry_id=eid, kind=kind, value=value, note=note, occurred_on=today)
    return eid


def retract_invest_entry(conn: sqlite3.Connection, entry_id: str) -> bool:
    """撤销一条手动投入（OP-13 可逆）：追加 `invest.retracted` 反向事实，不删历史。幂等。"""
    from timeflow.core import facts as facts_mod

    target = _find_invest_fact(conn, entry_id)
    if target is None:
        raise KeyError(f"投入记录不存在: {entry_id}")
    if _is_invest_retracted(conn, entry_id):
        return False
    target_kind = str(target["value_text"] or "")
    raw_value = target["value_num"]
    target_value = float(raw_value) if isinstance(raw_value, (int, float)) else 0.0
    extra = {
        "entry_id": entry_id,
        "kind": target_kind,
        "seconds": target_value,
        "migrated": False,
    }
    facts_mod.record(
        conn,
        kind="invest.retracted",
        subject_type="invest",
        subject_id=entry_id,
        value_num=target_value,
        value_text=target_kind,
        extra=extra,
        source="desktop",
    )
    facts_mod.publish("invest.retracted", {"entry_id": entry_id, **extra})
    return True


def _record_invest_fact(
    conn: sqlite3.Connection,
    entry_id: str,
    kind: str,
    value: float,
    note: str | None,
    occurred_on: str,
) -> None:
    """发 `invest.manual` 事实（value_num = 秒）。"""
    from timeflow.core import facts as facts_mod

    extra = {"entry_id": entry_id, "kind": kind, "note": note}
    facts_mod.record(
        conn,
        kind="invest.manual",
        subject_type="invest",
        subject_id=entry_id,
        value_num=float(value),
        value_text=kind,
        extra=extra,
        source="desktop",
    )
    facts_mod.publish("invest.manual", {"entry_id": entry_id, **extra, "seconds": float(value)})


def _invest_facts(conn: sqlite3.Connection, day: str | None = None) -> list[dict[str, object]]:
    """某日手动投入事实（默认今天）。"""
    from timeflow.core import facts as facts_mod

    d = day or clock.today_iso()
    return facts_mod.query(
        conn, kind="invest.manual", since=f"{d}T00:00:00", until=f"{d}T23:59:59"
    )


def list_invests(conn: sqlite3.Connection, day: str | None = None) -> list[dict[str, object]]:
    """某日手动投入流水（含是否已撤销），供前端展示与核对。"""
    out: list[dict[str, object]] = []
    for fact in _invest_facts(conn, day):
        entry_id = str(fact["subject_id"])
        extra_obj = fact["extra"]
        extra: dict[str, object] = extra_obj if isinstance(extra_obj, dict) else {}
        raw_seconds = fact["value_num"]
        seconds = float(raw_seconds) if isinstance(raw_seconds, (int, float)) else 0.0
        out.append(
            {
                "entry_id": entry_id,
                "kind": fact["value_text"],
                "seconds": seconds,
                "minutes": round(seconds / 60.0, 1),
                "note": extra.get("note"),
                "occurred_at": fact["occurred_at"],
                "retracted": _is_invest_retracted(conn, entry_id),
            }
        )
    return out


def _find_invest_fact(conn: sqlite3.Connection, entry_id: str) -> dict[str, object] | None:
    from timeflow.core import facts as facts_mod

    rows = facts_mod.query(
        conn, kind="invest.manual", subject_type="invest", subject_id=entry_id
    )
    return rows[-1] if rows else None


def _is_invest_retracted(conn: sqlite3.Connection, entry_id: str) -> bool:
    from timeflow.core import facts as facts_mod

    return bool(
        facts_mod.query(
            conn, kind="invest.retracted", subject_type="invest", subject_id=entry_id
        )
    )
