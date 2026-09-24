"""沉淀型内容写 Markdown（SR-F8 / 约定层第 9~11 行；G 批 · T-G4 / T-G5）。

**约定层要什么**（`docs/specification/conventions.md`）：
> **沉淀型**内容（任务完成记录、任务信息、备忘录、温故知新产出、任务存档、复习材料引用）
> → Markdown，沉淀至知识资产、与 AI 对齐；计算/核心型 → 结构化索引。
> 沉淀型 Markdown 放**独立共享目录**（frontmatter 带 type+命名空间），**与 Obsidian 笔记分目录**。

**红线**（`SR-F8.2`）：**不得直接写外部知识资产库（Obsidian 笔记、知识管理的 PDF/KB）** ——
所以本模块只往**用户自己指定的独立目录**写（默认项目下的 `export/`），
**绝不往 Obsidian 的 vault 里写**。

**T-G5：往 Obsidian 跳（只读）** —— "打开 vault 里的东西"用 `obsidian://open?vault=…&file=…`：
- 用户填 **Vault 名字**（协议要的那个名字，不一定等于文件夹名）+ 可选**Vault 根目录**；
- 根目录的用处只有一个：把**绝对路径**句柄换算成 Vault 内的相对位置；填了才能校验"在不在 Vault 里"；
- **红线做成机器拦得住的**（不靠记性）：导出目录落在 Vault 里时，
  ① 保存目录 → 400 拒绝；② 保存 Vault 根 → 400 拒绝；③ 真写文件前再拒一次（配置写歪也拦得住）；
- 跳转动作**只读**：读设置、拼 URL、交给系统打开 —— 全程不碰 Vault 里的任何文件
  （测试里用"跳前跳后 Vault 目录清单不变"钉住）。

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
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from timeflow import clock, logs
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
KEY_VAULT = "export.vault"  # T-G5：Obsidian 库的名字（`obsidian://` 协议用）
KEY_VAULT_DIR = "export.vault_dir"  # T-G5：Obsidian 库的根目录（用来换算绝对路径）

DEFAULT_DIR_NAME = "export"
FRONTMATTER_TYPE = "timeflow-daily"
NAMESPACE = "timeflow"

# Obsidian 的 URI scheme（只读跳转；本模块**不调用任何写 Vault 的接口**）
OURI_PREFIX = "obsidian://open"
RED_LINE = "红线 SR-F8.2：不直接写外部知识资产库（Obsidian 笔记）"

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


def _abs(text: str) -> Path:
    """配置里的一个目录字符串 → **绝对路径**（相对路径一律相对项目根，与调用方 cwd 无关）。"""
    path = Path(os.path.expandvars(text)).expanduser()
    return path if path.is_absolute() else (ROOT / path)


def resolve_dir(conn: sqlite3.Connection, default_dir: str = DEFAULT_DIR_NAME) -> Path:
    """现在生效的导出目录（**绝对路径**）：本机改过 → config → 默认 `export/`。"""
    raw = _get_raw(conn, KEY_DIR) or default_dir
    return _abs(_check_dir(raw))


def set_dir(
    conn: sqlite3.Connection,
    value: object,
    default_dir: str = DEFAULT_DIR_NAME,
    *,
    default_vault: str = "",
    default_vault_dir: str = "",
) -> dict[str, Any]:
    """改导出目录（**当场确保建得出来**，建不了就报错 —— 不静默留个写不进去的配置）。"""
    text = _check_dir(value)
    # 先过红线再落库：导出目录不许落在 Vault 里（T-G5 把这条从"文档里写着"变成"拦得住"）
    _reject_export_in_vault(_abs(text), resolve_vault_dir(conn, default_vault_dir))
    _put_raw(conn, KEY_DIR, text)
    conn.commit()
    try:
        ensure_dir(resolve_dir(conn, default_dir))
    except ValueError:
        conn.execute("DELETE FROM app_settings WHERE key = ?", (KEY_DIR,))
        conn.commit()
        raise
    return describe(
        conn,
        default_dir,
        default_vault=default_vault,
        default_vault_dir=default_vault_dir,
    )


def ensure_dir(path: Path) -> Path:
    """确保目录存在且**真的是目录**；建不了就 ValueError 带原话（不静默、不猜）。"""
    if path.exists() and not path.is_dir():
        raise ValueError(f"导出目录被一个同名文件占着：{path}（换个路径，或先把它挪走）")
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ValueError(f"建不了导出目录：{path}（{e.strerror or e}）") from e
    return path


# ---------------------------------------------------------------- Obsidian（T-G5，只读）
def _check_vault_name(value: object) -> str:
    text = str(value or "").strip()
    if "\x00" in text:
        raise ValueError("Vault 名字里有非法字符")
    return text


def resolve_vault_name(conn: sqlite3.Connection, default_vault: str = "") -> str:
    """现在生效的 Vault 名字（本机改过 → 配置 → 空 = 跳转关着）。"""
    raw = _get_raw(conn, KEY_VAULT)
    return (default_vault if raw is None else raw).strip()


def resolve_vault_dir(conn: sqlite3.Connection, default_vault_dir: str = "") -> Path | None:
    """现在生效的 Vault 根目录（**绝对路径**）；没填就是 None（只能跳相对句柄）。"""
    raw = _get_raw(conn, KEY_VAULT_DIR)
    text = (default_vault_dir if raw is None else raw).strip()
    if not text:
        return None
    path = Path(os.path.expandvars(text)).expanduser()
    return path if path.is_absolute() else (ROOT / path)


def _rel_to(child: Path, parent: Path) -> Path | None:
    """`child` 相对 `parent` 的位置；不在里面就 None。

    **先 normcase 再比**：Windows 上路径大小写不敏感 —— Python 3.12+ 的 `relative_to`
    已经自带大小写折叠，但**不把结论押在解释器版本上**：这里显式归一，
    3.11 及更早（`D:\\Notes\\Vault` vs `d:\\notes\\vault\\out` 会判成"不相干"）同样拦得住。
    """
    try:
        return Path(os.path.normcase(str(child.resolve()))).relative_to(
            Path(os.path.normcase(str(parent.resolve())))
        )
    except (OSError, ValueError):
        return None


def _inside(child: Path, parent: Path) -> bool:
    """`child` 是否在 `parent` 之内（**含相等**）。路径不存在也算得出来（非严格 resolve）。"""
    return _rel_to(child, parent) is not None


def _reject_export_in_vault(directory: Path, vault_dir: Path | None) -> None:
    """红线机器化：导出目录落在 Obsidian 库里 → 拒绝（带原话，告诉用户怎么改）。"""
    if vault_dir is None or not _inside(directory, vault_dir):
        return
    raise ValueError(
        f"导出目录不能放在 Obsidian 的 Vault 里：{directory} 在 {vault_dir} 之内。"
        f"{RED_LINE} —— 换一个与 Vault 分开的目录（约定层第 11 行要的正是"
        "「独立共享目录、与 Obsidian 笔记分目录」）。"
    )


def _norm_rel(text: str) -> str | None:
    """把句柄整理成 Vault 内的相对路径；**含 `..` 一律不算**（不许借句柄跳出 Vault）。"""
    parts = [p for p in text.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    return "/".join(parts)


def to_vault_file(handle: object, vault_dir: Path | None) -> tuple[str | None, str]:
    """把引用句柄换成 Vault 内的相对路径；换不出来就说明为什么（不猜、不静默）。

    两种句柄都认：① **Vault 相对路径**（`notes/数学.md`、`KB-1234`）直接用；
    ② **绝对路径** —— 得填了「Vault 根目录」才换算得出，且必须在 Vault 里面。
    """
    text = str(handle or "").strip()
    if not text:
        return None, "这条记录没有引用句柄"
    path = Path(os.path.expandvars(text)).expanduser()
    absolute = path.is_absolute() or bool(re.match(r"^[A-Za-z]:[\\/]", text))
    if not absolute:
        rel = _norm_rel(text)
        if rel is None:
            return None, f"引用句柄里不能有 `..`（会跳出 Vault）：{text}"
        return rel, ""
    if vault_dir is None:
        return None, "这是个绝对路径，但还没填「Vault 根目录」—— 算不出它在 Vault 里的位置"
    rel_path = _rel_to(path, vault_dir)
    if rel_path is None:
        return None, f"这个路径不在 Vault 里（Vault 根：{vault_dir}）—— 不能用 Obsidian 打开"
    rel = _norm_rel(str(rel_path))
    if rel is None:
        return None, f"这个路径就是 Vault 根目录本身：{vault_dir}"
    return rel, ""


def obsidian_url(vault: str, file: str) -> str:
    """拼 `obsidian://open?vault=…&file=…`。

    **逐段编码**（`/` 保留为分隔符、段内字符全编码）：这样句柄里的 `&`、`#`、空格不会
    跑成额外的协议参数（等于把"句柄"钉死在 file 这一个位置上）。
    """
    segments = [quote(s, safe="") for s in file.split("/")]
    return f"{OURI_PREFIX}?vault={quote(vault, safe='')}&file={'/'.join(segments)}"


def link(
    conn: sqlite3.Connection,
    handle: object,
    *,
    default_vault: str = "",
    default_vault_dir: str = "",
) -> dict[str, Any]:
    """给界面用的**跳转信息**：能跳就给 `url`，不能跳就给一句人话（`reason`）。**纯读。**"""
    name = resolve_vault_name(conn, default_vault)
    if not name:
        return {
            "url": "",
            "file": "",
            "vault": "",
            "reason": "还没填「Vault 名字」—— 在设置页「导出（Markdown）」里填上就能一键跳",
        }
    file, reason = to_vault_file(handle, resolve_vault_dir(conn, default_vault_dir))
    if file is None:
        return {"url": "", "file": "", "vault": name, "reason": reason}
    return {"url": obsidian_url(name, file), "file": file, "vault": name, "reason": ""}


def _start(url: str) -> tuple[bool, str]:
    """交给系统打开一个 URL（Windows 走 `os.startfile` —— 自定义协议由注册表接）。

    **只交出去、不执行 Vault 里的任何东西**：这里打开的是一个 `obsidian://` 协议链接。
    """
    try:
        if sys.platform.startswith("win"):
            os.startfile(url)  # noqa: S606 —— 打开的是本机应用自己的协议链接，不是外部输入
            return True, "已在 Obsidian 打开"
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([opener, url])  # noqa: S603,S607
        return True, "已在 Obsidian 打开"
    except OSError as e:
        return False, f"调不起 Obsidian（{e}）—— 装了 Obsidian 吗？协议链接已复制，可自己粘到地址栏"


def open_handle(
    conn: sqlite3.Connection,
    handle: object,
    *,
    default_vault: str = "",
    default_vault_dir: str = "",
    dry_run: bool = False,
    runner: Any = None,
) -> dict[str, Any]:
    """跳进 Obsidian 打开一个引用句柄（**只读**：不读也不写 Vault 里的文件）。

    `dry_run=True` 只算 URL 不真开（测试与"先看看会发生什么"用）；
    `runner` 可注入（测试替换掉真实打开动作，免得测试弹用户的 Obsidian）。
    """
    info = link(conn, handle, default_vault=default_vault, default_vault_dir=default_vault_dir)
    result: dict[str, Any] = {
        "ok": bool(info["url"]),
        "executed": False,
        "executed_detail": "",
        "dry_run": bool(dry_run),
        **info,
    }
    if not info["url"]:
        return result
    if dry_run:
        result["executed_detail"] = "（演练：未真正打开）"
        return result
    ok, detail = (runner or _start)(info["url"])
    result["executed"] = bool(ok)
    result["executed_detail"] = detail
    if not ok:
        result["ok"] = False
        result["reason"] = detail
    return result


def set_vault(
    conn: sqlite3.Connection,
    vault: object = "",
    vault_dir: object = "",
    *,
    default_vault: str = "",
    default_vault_dir: str = "",
    default_dir: str = DEFAULT_DIR_NAME,
) -> dict[str, Any]:
    """改 Obsidian 设置（Vault 名字 + 可选根目录）。**校验全过才落库**。

    没填名字 = 关掉跳转（不是错误）；填了根目录就必须**真的存在**（软件不会替你在 Vault 里建目录，
    那本身就是"动知识资产库"）；导出目录被这个根目录包住 → 拒绝（红线）。
    """
    name = _check_vault_name(vault)
    raw_dir = str(vault_dir or "").strip()
    target: Path | None = None
    if raw_dir:
        if "\x00" in raw_dir:
            raise ValueError("Vault 根目录里有非法字符")
        path = Path(os.path.expandvars(raw_dir)).expanduser()
        target = path if path.is_absolute() else (ROOT / path)
        if not target.exists():
            raise ValueError(
                f"这个 Vault 根目录不存在：{target}（填 Obsidian 库的根目录 —— "
                "软件不会替你在 Vault 里建目录）"
            )
        if not target.is_dir():
            raise ValueError(f"这个 Vault 根目录不是一个目录：{target}")
        # 反着也要拦：这个根目录把**现在的导出目录**包进去了（顺序换了，红线一样）
        export_dir = resolve_dir(conn, default_dir)
        if _inside(export_dir, target):
            raise ValueError(
                f"这个 Vault 根目录把现在的导出目录包进去了：{export_dir} 在 {target} 之内。"
                f"{RED_LINE} —— 先把导出目录换到 Vault 外面（上面那一栏），再填 Vault。"
            )
    _put_raw(conn, KEY_VAULT, name)
    _put_raw(conn, KEY_VAULT_DIR, raw_dir)
    conn.commit()
    return describe(
        conn,
        default_dir,
        default_vault=default_vault,
        default_vault_dir=default_vault_dir,
    )



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
    generated_at = clock.now().isoformat(timespec="seconds")
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
    conn: sqlite3.Connection,
    day: str | None = None,
    default_dir: str = DEFAULT_DIR_NAME,
    *,
    default_vault_dir: str = "",
) -> ExportResult:
    """把某一天写成一份 md（**原子写**：先写 `.tmp` 再 replace，不留半截文件）。

    失败一律 ValueError / OSError 带原话 —— 调用方决定是"报错给用户"（手动导出）
    还是"记下来继续"（自动导出，见 `try_export`）。
    """
    target_day = day or clock.today_iso()
    try:
        date.fromisoformat(target_day)
    except (TypeError, ValueError):
        raise ValueError(f"日期得写成 2026-09-21 这样：{day!r}") from None
    # 落盘前再过一次红线：配置文件里把导出目录写进了 Vault 时，这里也拦得住
    # （手动导出会当场看到原话；自动导出只记错 —— 两条路都不许**静默**往 Vault 里写）
    _reject_export_in_vault(
        resolve_dir(conn, default_dir), resolve_vault_dir(conn, default_vault_dir)
    )
    directory = ensure_dir(resolve_dir(conn, default_dir))
    content = render_day(conn, target_day)
    path = directory / f"{target_day}.md"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8", newline="\n")
    os.replace(tmp, path)

    done = ledger.today_done(conn, target_day)
    written_at = clock.now().isoformat(timespec="seconds")
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
    conn: sqlite3.Connection,
    day: str | None = None,
    default_dir: str = DEFAULT_DIR_NAME,
    *,
    default_vault_dir: str = "",
) -> ExportResult | None:
    """**自动导出**：成功就返回结果，失败只记错（不抛）—— md 是产物，不许挡住主流程。"""
    try:
        return export_day(conn, day, default_dir, default_vault_dir=default_vault_dir)
    except (OSError, ValueError) as e:
        detail = str(e) or e.__class__.__name__
        _put_raw(conn, KEY_LAST_ERROR, detail)
        conn.commit()
        logs.log_event("export_failed", level=40, detail=detail)
        return None


def status(conn: sqlite3.Connection, default_dir: str = DEFAULT_DIR_NAME) -> dict[str, Any]:
    """给界面的现状：目录、今天那份在不在、上次写的时间与错误（**错误不许静默消失**）。"""
    directory = resolve_dir(conn, default_dir)
    today = clock.today_iso()
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
    conn: sqlite3.Connection,
    default_dir: str = DEFAULT_DIR_NAME,
    *,
    default_vault: str = "",
    default_vault_dir: str = "",
) -> dict[str, Any]:
    """设置页要的整包：现状 + Obsidian 设置 + 口径说明（说明由后端给，界面不复述）。"""
    st = status(conn, default_dir)
    name = resolve_vault_name(conn, default_vault)
    vault_dir = resolve_vault_dir(conn, default_vault_dir)
    overlap = bool(vault_dir is not None and _inside(Path(st["dir"]), vault_dir))
    return {
        **st,
        # Obsidian（T-G5）：名字是跳转的前提，根目录只用来换算绝对路径
        "vault": name,
        "vault_dir": "" if vault_dir is None else str(vault_dir),
        "default_vault": default_vault,
        "default_vault_dir": default_vault_dir,
        "vault_configured": bool(name),
        "vault_overlap": (
            f"**现在的导出目录在 Vault 里面**：{st['dir']} —— {RED_LINE}；"
            "导出会拒写，请把导出目录换到 Vault 外面"
        ) if overlap else "",
        "vault_note": "填上 Vault 名字，复习卡/备忘里挂的引用句柄就能一键跳进 Obsidian"
                      "（`obsidian://` 协议，**只读跳转**）；再填 Vault 根目录，"
                      "绝对路径句柄也认（换算成 Vault 内的位置）。"
                      "软件**不往 Vault 里写任何东西**，也不会替你在里面建目录。",
        "note": "**数据库是权威，md 是产物**：软件把每天发生的事写成一份 md（一天一个文件、"
                "先写临时文件再替换，不会有半截文件）。你在 md 里手改的内容**不会被读回**，"
                "下次导出会覆盖 —— 要改就改软件里的数据。",
        "where": "写在**你自己指定的独立目录**里（默认项目下 `export/`）—— "
                 "**不写进 Obsidian 的笔记目录**（红线 SR-F8.2：不直接写外部知识资产库）；"
                 "导出目录一旦落在 Vault 里，保存和导出都会被拒绝。",
    }
