"""沉淀型内容写 Markdown（SR-F8 / 约定层第 9~11 行；G 批 · T-G4）。

**约定层要什么**（`docs/specification/conventions.md`）：
> **沉淀型**内容（任务完成记录、任务信息、备忘录、温故知新产出、任务存档、复习材料引用）
> → Markdown，沉淀至知识资产、与 AI 对齐；计算/核心型 → 结构化索引。
> 沉淀型 Markdown 放**独立共享目录**（frontmatter 带 type+命名空间），**与 Obsidian 笔记分目录**。

**红线**（`SR-F8.2`）：**不得直接写外部知识资产库（Obsidian 笔记、知识管理的 PDF/KB）** ——
所以本模块只往**用户自己指定的独立目录**写（默认项目下的 `export/`），**不碰 Obsidian 的 vault**
（"打开 vault 里的东西"是 T-G5 的 `obsidian://` 跳转，只读不写）。

**几条口径（2026-09-21 用户定，见 `复盘/口径定案-待定清单.md` §7）**：
- **数据库是权威，md 是产物**：md 里手改的内容**不会被读回**，下次导出会覆盖 ——
  这句话写进了文件头与界面（否则用户会以为改了 md 就算改了数据）。
- **每天一个 md**（`2026-09-21.md`）：像日志，AI 读一天一个很顺，文件数可控。
- **目录可配置**：默认软件目录下 `export/`，可以指到任意路径（`config.toml [export] dir`
  或设置页；本机改过的存 `app_settings` 并优先 —— 与附件/专注/归档同一套机制）。
- **写了就不挡主流程**：导出是**产物**，失败只记错（`export.last_error` + 结构化日志），
  不让"完成一个任务"因为磁盘满/路径只读而失败（`try_export`）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from timeflow import logs
from timeflow.core import feedback as fb
from timeflow.core import insights as ins
from timeflow.core import memo as memo_mod
from timeflow.core.ledger import ledger

if TYPE_CHECKING:
    import sqlite3

# 设置键（`app_settings` 是通用 key/value 表，与附件/专注/归档/口径同一处）
KEY_DIR = "export.dir"
KEY_LAST_AT = "export.last_written_at"
KEY_LAST_ERROR = "export.last_error"

DEFAULT_DIR_NAME = "export"
FRONTMATTER_TYPE = "timeflow-daily"
NAMESPACE = "timeflow"

# 星期几的中文（标题里带一个，人读起来有坐标）
_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

# 项目根：相对目录一律相对它解析 —— 于是"默认 export/"在哪里与调用方的工作目录无关
ROOT = Path(__file__).resolve().parent.parent.parent.parent


@dataclass
class ExportResult:
    """一次导出的结果（够界面显示"写到哪了、写了多少"）。"""

    day: str
    path: str
    bytes: int
    tasks: int
    steps: int
    memos: int
    outputs: int
    written_at: str


# ---------------------------------------------------------------- 设置（目录）
def _get_raw(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def _put_raw(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def _check_dir(value: object) -> str:
    """校验导出目录：非空、不含 NUL。**不在这时创建**（创建见 `ensure_dir`，失败要报原话）。"""
    text = str(value or "").strip()
    if not text:
        raise ValueError("导出目录不能为空（填一个路径，如 export 或 D:/timeflow-export）")
    if "\x00" in text:
        raise ValueError("导出目录里有非法字符")
    return text


def resolve_dir(conn: sqlite3.Connection, default_dir: str = DEFAULT_DIR_NAME) -> Path:
    """现在生效的导出目录（**绝对路径**）：本机改过 → config → 默认 `export/`。"""
    raw = _get_raw(conn, KEY_DIR) or default_dir
    path = Path(os.path.expandvars(_check_dir(raw))).expanduser()
    return path if path.is_absolute() else (ROOT / path)


def set_dir(
    conn: sqlite3.Connection, value: object, default_dir: str = DEFAULT_DIR_NAME
) -> dict[str, Any]:
    """改导出目录（**当场确保建得出来**，建不了就报错 —— 不静默留个写不进去的配置）。"""
    text = _check_dir(value)
    _put_raw(conn, KEY_DIR, text)
    conn.commit()
    try:
        ensure_dir(resolve_dir(conn, default_dir))
    except ValueError:
        conn.execute("DELETE FROM app_settings WHERE key = ?", (KEY_DIR,))
        conn.commit()
        raise
    return describe(conn, default_dir)


def ensure_dir(path: Path) -> Path:
    """确保目录存在且**真的是目录**；建不了就 ValueError 带原话（不静默、不猜）。"""
    if path.exists() and not path.is_dir():
        raise ValueError(f"导出目录被一个同名文件占着：{path}（换个路径，或先把它挪走）")
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ValueError(f"建不了导出目录：{path}（{e.strerror or e}）") from e
    return path


# ---------------------------------------------------------------- 渲染（每天一个 md）
def _weekday(day: str) -> str:
    try:
        return _WEEKDAYS[date.fromisoformat(day).weekday()]
    except (TypeError, ValueError):
        return ""


def _frontmatter(day: str, generated_at: str) -> str:
    """frontmatter：**约定层要求带 type + 命名空间**，好让 AI / Obsidian 认得出这是谁写的。"""
    return (
        "---\n"
        f"type: {FRONTMATTER_TYPE}\n"
        f"namespace: {NAMESPACE}\n"
        f"date: {day}\n"
        f"generated_at: {generated_at}\n"
        f"source: timeflow\n"
        "---\n"
    )


HEADER_NOTE = (
    "<!-- 本文件由 timeflow 生成：**数据库是权威**，在这里手改不会被读回，"
    "下次导出会覆盖（要改就改软件里的数据）。 -->\n"
)


def _done_lines(done: ledger.TodayDone) -> list[str]:
    lines: list[str] = []
    for t in done.tasks:
        lines.append(f"- [x] {t.title}")
    for s in done.steps:
        parent = [p for p in done.parents if p.id == s.parent_id]
        progress = (
            f"（父任务进度 {parent[0].done_total}/{parent[0].total_steps}）" if parent else ""
        )
        lines.append(f"- [x] {s.parent_title or '未命名'} · {s.title}{progress}")
    return lines


def _invest_lines(conn: sqlite3.Connection, day: str) -> list[str]:
    """投入那几行：**全是 0 就不写**（"专注 0 分钟"这种噪声不该占篇幅，见 `render_day` 的空态）。"""
    cell = ins.day_cell(conn, day)
    lines: list[str] = []
    if cell.focus_minutes:
        lines.append(f"- 专注 {round(cell.focus_minutes)} 分钟")
    if cell.manual_minutes:
        lines.append(f"- 手动补录 {round(cell.manual_minutes)} 分钟")
    if cell.review_count or cell.output_count:
        lines.append(f"- 复习 {cell.review_count} 张 · 产出 {cell.output_count} 条")
    if cell.debt_count:
        lines.append(f"- 当日债务 {cell.debt_count} 项（快照）")
    return lines


def _num(value: object) -> str:
    """数值写好看点：`1.0` → `1`（md 是给人/AI 读的，不是调试输出）。"""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(value)
    return str(int(number)) if number.is_integer() else str(round(number, 2))


def _output_lines(done: ledger.TodayDone) -> list[str]:
    lines: list[str] = []
    for o in done.outputs:
        kind = {"kpi": "KPI", "asset": "资产"}.get(str(o.kind), str(o.kind))
        retracted = "（已撤销，不计入）" if o.retracted else ""
        note = f"：{o.note}" if o.note else ""
        lines.append(f"- {kind} ×{_num(o.value)}{note}{retracted}")
    return lines


def _memo_lines(conn: sqlite3.Connection, day: str) -> list[str]:
    lines: list[str] = []
    for m in memo_mod.list_memos(conn):
        if str(m.get("created_at") or "")[:10] != day:
            continue
        text = str(m.get("text") or "").strip().replace("\n", " ")
        handle = m.get("ref_handle")
        suffix = f"（引用：{handle}）" if handle else ""
        lines.append(f"- {text}{suffix}")
    return lines


def _feedback_lines(conn: sqlite3.Connection, day: str) -> list[str]:
    row = fb.get_feedback(conn, day)
    if not row:
        return []
    lines: list[str] = []
    for label, key in (("计划", "plan_note"), ("执行", "executed"), ("差距", "gap_note")):
        value = str(row.get(key) or "").strip()
        if value:
            lines.append(f"- **{label}**：{value}")
    return lines


def render_day(conn: sqlite3.Connection, day: str) -> str:
    """某一天的 markdown（**纯函数式**：同一份数据渲染出同一份文本，除 `generated_at`）。"""
    generated_at = datetime.now().isoformat(timespec="seconds")
    done = ledger.today_done(conn, day)
    parts: list[str] = [
        _frontmatter(day, generated_at),
        "\n",
        HEADER_NOTE,
        "\n",
        f"# {day} {_weekday(day)}".rstrip(),
        "\n",
    ]
    sections: list[tuple[str, list[str]]] = [
        ("完成", _done_lines(done)),
        ("投入", _invest_lines(conn, day)),
        ("产出", _output_lines(done)),
        ("备忘", _memo_lines(conn, day)),
        ("每日反馈", _feedback_lines(conn, day)),
    ]
    empty = True
    for title, lines in sections:
        if not lines:
            continue
        empty = False
        parts += [f"\n## {title}\n", "\n".join(lines), "\n"]
    if empty:
        parts += ["\n（这一天还没有记录。）\n"]
    return "".join(parts)


# ---------------------------------------------------------------- 写出
def note_path(conn: sqlite3.Connection, day: str, default_dir: str = DEFAULT_DIR_NAME) -> Path:
    """每天一个 md 的路径（`<目录>/2026-09-21.md`）。"""
    return resolve_dir(conn, default_dir) / f"{day}.md"


def export_day(
    conn: sqlite3.Connection, day: str | None = None, default_dir: str = DEFAULT_DIR_NAME
) -> ExportResult:
    """把某一天写成一份 md（**原子写**：先写 `.tmp` 再 replace，不留半截文件）。

    失败一律 ValueError / OSError 带原话 —— 调用方决定是"报错给用户"（手动导出）
    还是"记下来继续"（自动导出，见 `try_export`）。
    """
    target_day = day or date.today().isoformat()
    try:
        date.fromisoformat(target_day)
    except (TypeError, ValueError):
        raise ValueError(f"日期得写成 2026-09-21 这样：{day!r}") from None
    directory = ensure_dir(resolve_dir(conn, default_dir))
    content = render_day(conn, target_day)
    path = directory / f"{target_day}.md"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8", newline="\n")
    os.replace(tmp, path)

    done = ledger.today_done(conn, target_day)
    written_at = datetime.now().isoformat(timespec="seconds")
    _put_raw(conn, KEY_LAST_AT, written_at)
    _put_raw(conn, KEY_LAST_ERROR, "")
    conn.commit()
    return ExportResult(
        day=target_day,
        path=str(path),
        bytes=len(content.encode("utf-8")),
        tasks=len(done.tasks),
        steps=len(done.steps),
        memos=len(_memo_lines(conn, target_day)),
        outputs=len(done.outputs),
        written_at=written_at,
    )


def try_export(
    conn: sqlite3.Connection, day: str | None = None, default_dir: str = DEFAULT_DIR_NAME
) -> ExportResult | None:
    """**自动导出**：成功就返回结果，失败只记错（不抛）—— md 是产物，不许挡住主流程。"""
    try:
        return export_day(conn, day, default_dir)
    except (OSError, ValueError) as e:
        detail = str(e) or e.__class__.__name__
        _put_raw(conn, KEY_LAST_ERROR, detail)
        conn.commit()
        logs.log_event("export_failed", level=40, detail=detail)
        return None


def status(conn: sqlite3.Connection, default_dir: str = DEFAULT_DIR_NAME) -> dict[str, Any]:
    """给界面的现状：目录、今天那份在不在、上次写的时间与错误（**错误不许静默消失**）。"""
    directory = resolve_dir(conn, default_dir)
    today = date.today().isoformat()
    path = directory / f"{today}.md"
    exists = path.is_file()
    return {
        "dir": str(directory),
        "default_dir": default_dir,
        "configured": _get_raw(conn, KEY_DIR) is not None,
        "exists": directory.is_dir(),
        "today": today,
        "note_path": str(path),
        "note_exists": exists,
        "note_bytes": path.stat().st_size if exists else 0,
        "last_written_at": _get_raw(conn, KEY_LAST_AT),
        "last_error": _get_raw(conn, KEY_LAST_ERROR) or "",
    }


def describe(
    conn: sqlite3.Connection, default_dir: str = DEFAULT_DIR_NAME
) -> dict[str, Any]:
    """设置页要的整包：现状 + 口径说明（说明由后端给，界面不复述）。"""
    return {
        **status(conn, default_dir),
        "note": "**数据库是权威，md 是产物**：软件把每天发生的事写成一份 md（一天一个文件、"
                "先写临时文件再替换，不会有半截文件）。你在 md 里手改的内容**不会被读回**，"
                "下次导出会覆盖 —— 要改就改软件里的数据。",
        "where": "写在**你自己指定的独立目录**里（默认项目下 `export/`）—— "
                 "**不写进 Obsidian 的笔记目录**（红线 SR-F8.2：不直接写外部知识资产库）。",
    }
