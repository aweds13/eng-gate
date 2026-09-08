"""备忘录 + 知识资产引用句柄（SR-F8.1~F8.4）。对应 AC 备忘录。

备忘录：碎片化任务/想法本地随手记；可顺手建成任务 + 加到期。
知识资产：本软件**只存引用句柄**（Vault 相对路径 / KB-... 资源 ID），
读/写 Obsidian、PDF 库交给「知识资产项目」，本软件不直接碰 Vault 文件。
产出评价器接口（SR-F8.4）：第一版手动粗颗粒入口，合同待知识管理项目对齐。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


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
    """记一条产出流水（产出轴）。第一版手动粗颗粒；value 由用户/评价器给出。"""
    eid = _uid()
    conn.execute(
        "INSERT INTO ledger_entries (id, axis, kind, value, date, note, ref_handle, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (eid, "output", kind, value, date.today().isoformat(), note, ref_handle, _now()),
    )
    conn.commit()
    return eid


def add_invest_entry(
    conn: sqlite3.Connection,
    value: float,
    kind: str = "focus",
    note: str | None = None,
) -> str:
    """记一条投入流水（投入轴）。"""
    eid = _uid()
    conn.execute(
        "INSERT INTO ledger_entries (id, axis, kind, value, date, note, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (eid, "invest", kind, value, date.today().isoformat(), note, _now()),
    )
    conn.commit()
    return eid
