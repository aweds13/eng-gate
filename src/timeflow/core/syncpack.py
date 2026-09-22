"""跨端同步的**同步包**与**合并机制**（SR-F9.2 / SR-NF17 / N25；G 批 · T-G8 = 场景 ③）。

**口径**（用户 2026-09-21 定，见 `复盘/口径定案-待定清单.md` §3）：
> **③ 先做**：定义**同步包文件格式** + 合并机制（谁新谁旧 / 同一条不重复 / 冲突留痕）
> + 导出/导入入口。它是 ① 的**地基**（手机导出的是一个同格式的包），
> 而且能在两个库之间立刻验证。顺序是 **③ → ① → ②**（依赖决定的，不是偏好）。

这一版（③，电脑 ↔ 电脑，**走文件**）的三条规矩：

1. **同步的是"你的数据"，不同步的是"这台机器的事"**：包里没有 `app_settings`（导出目录 /
   Vault / AI 开关 / 口径开关都是本机的）、没有 `sync_logs`（本机的冲突历史）、
   没有 `schema_version`（结构由迁移管）。于是"把包拷到另一台机器"不会改掉对方的设置。
2. **合并不静默**：谁新谁旧按 **version → updated_at** 判（`sync.newer_is_win`，与既有语义一致）；
   覆盖、保留本地、按墓碑跳过**逐条记进 `sync_logs`**（带 `result` 与一句"差在哪"），界面看得见。
3. **导入永不删你的东西**：远程墓碑（"那边删过这个"）只用于**防止复活**与**继续传给下一台**，
   **不删本地已有的行** —— 默认保守（这条是 v1 明确边界，见复盘文档）。

**三类表，三套合并规则**（表的性质不同，不能一刀切）：

- **LWW 行**（tasks / habits / groups / course_assessments / review_items / team_assignments /
  feedback_logs / memos）：同 id 内容一样 → 跳过；远端较新 → 覆盖（记日志）；
  否则保留本地（记日志）；
- **只增行**（facts / focus_sessions / grades / courses / ledger_entries）：这些是"发生过的事 /
  建过的东西"，**只插不改**；同 id 内容不同 → 只记冲突，不动本地；
- **关系行**（task_groups / habit_logs）：只有"在不在"（没有时间可判新旧），缺则插；
  **被墓碑拦住就不插**。

**墓碑（`sync_tombstones`）为什么必要**：没有它，"在 A 机器上彻底删掉的东西"会被 B 机器的旧包
**原样带回来**（`tasks` 软删除走 LWW 没问题，但 `purge_task`、删备忘、删成绩、取消打卡是**硬删**）。
墓碑由 v17 的**删除触发器**自动产生 —— 一个声明式的地方管全部，不靠"记得在每个删除入口写一行"。
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from timeflow import logs
from timeflow.core import sync as sync_mod

if TYPE_CHECKING:
    import sqlite3

# 包的身份（写进文件，导入时校验：**不是我们的包就别硬塞**）
FORMAT = "timeflow-sync"
FORMAT_VERSION = 1

# 设置键（`app_settings` 通用表）：本机设备号 + 上次导出/导入的痕迹
KEY_DEVICE_ID = "sync.device_id"
KEY_LAST_EXPORT = "sync.last_export"
KEY_LAST_IMPORT = "sync.last_import"

# 三类表（顺序固定：包里可读，报告里也好对）
LWW_TABLES: tuple[str, ...] = (
    "tasks",
    "habits",
    "groups",
    "course_assessments",
    "review_items",
    "team_assignments",
    "feedback_logs",
    "memos",
)
APPEND_TABLES: tuple[str, ...] = (
    "facts",
    "focus_sessions",
    "courses",
    "grades",
    "ledger_entries",
)
RELATION_TABLES: tuple[str, ...] = ("task_groups", "habit_logs")
TOMBSTONE_TABLE = "sync_tombstones"
SYNCED_TABLES: tuple[str, ...] = LWW_TABLES + APPEND_TABLES + RELATION_TABLES

# 明确**不同步**的（写进包里当自我说明，也写进界面）
EXCLUDED_TABLES: tuple[str, ...] = ("app_settings", "sync_logs", "schema_version")

# 判"内容是否一样"时忽略的列：本机自己的记账列（设备号/版本/时间），不算内容
_IGNORED_COLUMNS = frozenset({"updated_at", "version", "device_id"})

MAX_CONFLICT_SAMPLES = 20


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- 设置（设备号等）
def _get_raw(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def _put_raw(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def device_id(conn: sqlite3.Connection) -> str:
    """本机设备号（首次用时生成并记住）。

    用途有两个，都是"如实"用途：① 写进包，让人看得出这份包从哪台机器来；
    ② LWW 打平时的**确定性**决胜（两边时间戳一模一样时不至于各说各话）。
    """
    existing = peek_device_id(conn)
    if existing:
        return existing
    fresh = uuid.uuid4().hex[:12]
    _put_raw(conn, KEY_DEVICE_ID, fresh)
    conn.commit()
    return fresh


def peek_device_id(conn: sqlite3.Connection) -> str | None:
    """只看设备号，**不生成、不落库** —— 预览（dry_run）要求"一个字节都不写"。"""
    return _get_raw(conn, KEY_DEVICE_ID)


# ---------------------------------------------------------------- 建包（导出）
def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(r["name"]) for r in conn.execute(f"PRAGMA table_info({table})")]


def _rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    cursor = conn.execute(f"SELECT * FROM {table}")
    return [dict(r) for r in cursor.fetchall()]


def build_pack(conn: sqlite3.Connection, *, device: str | None = None) -> dict[str, Any]:
    """把整库该同步的东西装进一个 dict（**只读**，不写任何东西）。

    包里按表给行；每张表只装**真实存在的列**（老库缺列时不假装有）。
    """
    dev = device or device_id(conn)
    tables: dict[str, list[dict[str, Any]]] = {}
    for table in SYNCED_TABLES:
        if not _exists(conn, table):
            continue
        tables[table] = _rows(conn, table)
    tombstones = _rows(conn, TOMBSTONE_TABLE) if _exists(conn, TOMBSTONE_TABLE) else []
    return {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "schema_version": _schema_version(conn),
        "device_id": dev,
        "created_at": _now(),
        "tables": tables,
        "tombstones": tombstones,
        "counts": {name: len(rows) for name, rows in tables.items()},
        "note": "同步的是你的数据；**不含**本机设置（导出目录 / Vault / AI 开关 / 口径开关）、"
                "本机的冲突日志与 schema 版本。导入**不会删**你本地的任何东西。",
    }


def _exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
    )


def _schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    return int(row["version"]) if row is not None else 0


@dataclass
class ExportResult:
    """一次导出的结果（够界面说清"写到哪了、装了多少"）。"""

    path: str
    bytes: int
    device_id: str
    tables: dict[str, int]
    rows: int
    tombstones: int
    created_at: str


def default_filename(device: str, at: str | None = None) -> str:
    """`sync-<设备号>-<时间戳>.json` —— 文件名自带来源与时间，拷来拷去不会认错。"""
    stamp = (at or _now()).replace("-", "").replace(":", "").replace("T", "-")
    return f"sync-{device}-{stamp}.json"


def export_pack(
    conn: sqlite3.Connection, out_dir: Path | str, *, device: str | None = None
) -> ExportResult:
    """把同步包**原子写**到 `out_dir`（先写 `.tmp` 再 replace，不留半截文件）。

    失败一律 `OSError` / `ValueError` 带原话（调用方决定怎么提示）——不静默。
    """
    pack = build_pack(conn, device=device)
    directory = Path(out_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ValueError(f"建不了同步包目录：{directory}（{e.strerror or e}）") from e
    path = directory / default_filename(str(pack["device_id"]), str(pack["created_at"]))
    # 同一秒里连点两次导出 → 文件名会撞。**要么换名、要么覆盖**：这里换名，
    # 免得"上一份包"在你还想留着做对照时被悄悄替换掉。
    if path.exists():
        stem, suffix = path.name[:-5], path.suffix
        index = 2
        while True:
            candidate = directory / f"{stem}-{index}{suffix}"
            if not candidate.exists():
                path = candidate
                break
            index += 1
    text = json.dumps(pack, ensure_ascii=False, indent=2)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)

    written_at = _now()
    _put_raw(conn, KEY_LAST_EXPORT, json.dumps(
        {"at": written_at, "path": str(path), "rows": sum(pack["counts"].values())},
        ensure_ascii=False,
    ))
    conn.commit()
    logs.log_event(
        "sync_export", path=str(path), device_id=pack["device_id"],
        rows=sum(pack["counts"].values()), tombstones=len(pack["tombstones"]),
    )
    return ExportResult(
        path=str(path),
        bytes=len(text.encode("utf-8")),
        device_id=str(pack["device_id"]),
        tables=dict(pack["counts"]),
        rows=sum(pack["counts"].values()),
        tombstones=len(pack["tombstones"]),
        created_at=str(pack["created_at"]),
    )


# ---------------------------------------------------------------- 读包
def load_pack(path: Path | str) -> dict[str, Any]:
    """读一个同步包文件并**校验**（不是我们的格式 / 版本太新 → ValueError 带原话）。"""
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"找不到这个文件：{p}")
    try:
        raw: object = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"这个文件不是合法的 JSON：{p}（{e}）") from e
    return check_pack(raw)


def check_pack(pack: object) -> dict[str, Any]:
    """校验包本身。**明确拒绝**比"尽力猜"好：猜错了就是把别人的数据合进来。"""
    if not isinstance(pack, dict):
        raise ValueError("同步包应该是 JSON 对象")
    if pack.get("format") != FORMAT:
        raise ValueError(
            f"这不是 timeflow 的同步包（format={pack.get('format')!r}，应该是 {FORMAT!r}）"
        )
    ver = pack.get("format_version")
    if not isinstance(ver, int) or ver > FORMAT_VERSION:
        raise ValueError(
            f"这份包的格式版本比本程序新（{ver} > {FORMAT_VERSION}）—— 先升级程序再导入"
        )
    if not isinstance(pack.get("tables"), dict):
        raise ValueError("同步包里没有 tables")
    return pack


# ---------------------------------------------------------------- 规划（纯读）与执行
@dataclass
class Action:
    """一条待执行的动作（**先规划、后执行**：于是"预览"与实际导入是同一套判断）。"""

    kind: str            # insert / update / tombstone_add / keep
    table: str
    entity_id: str
    reason: str = ""     # 'remote_newer' / 'tombstoned' / 'content_differs' / 'remote_deleted'
    local: dict[str, Any] = field(default_factory=dict)
    remote: dict[str, Any] = field(default_factory=dict)


# 各表的**主键列**（合并靠它定位"同一条"）。**不能假设都叫 `id`** ——
# `feedback_logs` 的主键是 `date`，`task_groups` / `habit_logs` 是复合键。
# （这条是实测踩到的：原先假设 `id`，于是整张 `feedback_logs` 被**静默跳过** ——
#  而"每日反馈"恰恰是用户手写的东西。现在有护栏测试拿 PRAGMA 对账，见
#  `tests/test_sync_pack_line.py::test_primary_key_map_matches_the_real_tables`。）
PRIMARY_KEYS: dict[str, tuple[str, ...]] = {
    "task_groups": ("task_id", "group_id"),
    "habit_logs": ("habit_id", "date"),
    "feedback_logs": ("date",),
}
DEFAULT_PK: tuple[str, ...] = ("id",)


def pk_columns(table: str) -> tuple[str, ...]:
    return PRIMARY_KEYS.get(table, DEFAULT_PK)


def row_key(table: str, row: dict[str, Any]) -> str:
    """一行在包里的**统一标识**：单主键就是它，复合主键用 `|` 拼（与墓碑同口径）。"""
    cols = pk_columns(table)
    if len(cols) == 1:
        return str(row.get(cols[0]))
    return "|".join(str(row.get(c)) for c in cols)


def _content(row: dict[str, Any]) -> dict[str, Any]:
    """内容指纹（忽略本机记账列）。用于判"一样不一样"——不一样才需要做决定。"""
    return {k: v for k, v in row.items() if k not in _IGNORED_COLUMNS}


def _as_int(value: object, default: int = 0) -> int:
    """宽松取整（包里来的东西可能是 str/float/None）—— 拿不准就用 `default`。"""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _pack_row_ts(row: dict[str, Any]) -> str:
    """这一行的"什么时候改的"：优先 `updated_at`，退回 `created_at`，再退回空串。

    空串表示**无从判断** —— 那种情况按"本地赢、记一条冲突"处理（不静默覆盖）。
    """
    return str(row.get("updated_at") or row.get("created_at") or "")


def _local_rows(conn: sqlite3.Connection, table: str) -> dict[str, dict[str, Any]]:
    rows = _rows(conn, table) if _exists(conn, table) else []
    return {row_key(table, r): r for r in rows}


def _local_tombstones(conn: sqlite3.Connection) -> set[tuple[str, str]]:
    if not _exists(conn, TOMBSTONE_TABLE):
        return set()
    return {
        (str(r["entity"]), str(r["entity_id"]))
        for r in conn.execute(f"SELECT entity, entity_id FROM {TOMBSTONE_TABLE}").fetchall()
    }


def plan_merge(
    conn: sqlite3.Connection, pack: dict[str, Any], *, device: str | None = None
) -> tuple[list[Action], list[dict[str, Any]]]:
    """**纯读**地算出这次导入要做什么，返回 `(动作列表, 冲突/说明列表)`。

    规划与执行分开的好处：界面能"先预览再确认"（同一套判断，不会预览说一套、执行做另一套），
    dry-run 也就不用"跑一半回滚"这种危险做法。
    """
    check_pack(pack)
    local_dev = device or peek_device_id(conn) or ""
    remote_dev = str(pack.get("device_id") or "?")
    if remote_dev == local_dev and local_dev:
        raise ValueError(
            "这份包就是本机导出的（设备号相同）—— 自己导给自己没有意义；"
            "请在另一台机器上导出、在这台机器上导入。"
        )
    actions: list[Action] = []
    conflicts: list[dict[str, Any]] = []
    tombstones = _local_tombstones(conn)

    tables: dict[str, Any] = pack["tables"]
    for table in SYNCED_TABLES:
        remote_rows = tables.get(table) or []
        if not isinstance(remote_rows, list) or not remote_rows:
            continue
        local = _local_rows(conn, table)
        for remote in remote_rows:
            if not isinstance(remote, dict):
                continue
            key = row_key(table, remote)
            if not key or key == "None":
                continue
            here = local.get(key)
            if here is None:
                if (table, key) in tombstones:
                    actions.append(Action("keep", table, key, "tombstoned", remote=remote))
                    conflicts.append({
                        "entity": table, "entity_id": key, "result": "按墓碑跳过",
                        "note": "本机删过它（墓碑），不因为这份包把它带回来",
                    })
                    continue
                actions.append(Action("insert", table, key, remote=remote))
                continue
            if _content(here) == _content(remote):
                actions.append(Action("keep", table, key, "same", local=here, remote=remote))
                continue
            if table in LWW_TABLES:
                remote_newer = sync_mod.newer_is_win(
                    str(here.get("updated_at") or here.get("created_at") or ""),
                    _pack_row_ts(remote),
                    _as_int(here.get("version")),
                    _as_int(remote.get("version")),
                )
                if remote_newer:
                    actions.append(Action("update", table, key, "remote_newer", here, remote))
                    conflicts.append({
                        "entity": table, "entity_id": key, "result": "覆盖（远端较新）",
                        "local_ts": _pack_row_ts(here), "remote_ts": _pack_row_ts(remote),
                        "note": _diff_note(here, remote),
                    })
                else:
                    actions.append(Action("keep", table, key, "local_wins", here, remote))
                    conflicts.append({
                        "entity": table, "entity_id": key, "result": "保留本地（本地不旧）",
                        "local_ts": _pack_row_ts(here), "remote_ts": _pack_row_ts(remote),
                        "note": _diff_note(here, remote),
                    })
                continue
            # 只增行 / 关系行：内容不同就**不动本地**，只留一条冲突（不静默）
            actions.append(Action("keep", table, key, "content_differs", here, remote))
            conflicts.append({
                "entity": table, "entity_id": key, "result": "保留本地（这类行只增不改）",
                "note": _diff_note(here, remote),
            })

    # 远程墓碑：**并入本地**（好继续传给下一台），但**不删本地已有的行**（v1 边界）
    for tomb in pack.get("tombstones") or []:
        if not isinstance(tomb, dict):
            continue
        entity, eid = str(tomb.get("entity") or ""), str(tomb.get("entity_id") or "")
        if not entity or not eid:
            continue
        if (entity, eid) in tombstones:
            continue
        actions.append(Action("tombstone_add", entity, eid, "remote_deleted",
                              remote={"deleted_at": tomb.get("deleted_at")}))
        conflicts.append({
            "entity": entity, "entity_id": eid, "result": "远程已删（本地保留）",
            "note": "那边删过它；这里**不替你删**（v1 导入不删任何本地数据），只记下墓碑",
        })
    return actions, conflicts


def _diff_note(local: dict[str, Any], remote: dict[str, Any]) -> str:
    """人话说明"哪儿不一样"（最多三处，够看清就行，不把整行堆进日志）。"""
    diffs = [
        f"{k}: {local.get(k)!r} → {remote.get(k)!r}"
        for k in sorted(set(local) | set(remote))
        if k not in _IGNORED_COLUMNS and local.get(k) != remote.get(k)
    ]
    return "；".join(diffs[:3]) + ("…" if len(diffs) > 3 else "")


@dataclass
class MergeReport:
    """一次导入的结果（**给人看的**：动了多少、为什么、按什么规则）。"""

    dry_run: bool
    from_device: str
    pack_created_at: str
    pack_schema_version: int
    tables: dict[str, dict[str, int]]
    inserted: int
    updated: int
    kept: int
    tombstoned: int
    tombstone_added: int
    conflicts: list[dict[str, Any]]      # **样例**（最多 `MAX_CONFLICT_SAMPLES` 条，界面看）
    conflict_count: int                  # 真实条数（日志里是全部）
    notes: list[str]
    applied_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "from_device": self.from_device,
            "pack_created_at": self.pack_created_at,
            "pack_schema_version": self.pack_schema_version,
            "tables": self.tables,
            "totals": {
                "inserted": self.inserted,
                "updated": self.updated,
                "kept": self.kept,
                "tombstoned": self.tombstoned,
                "tombstone_added": self.tombstone_added,
            },
            "conflicts": self.conflicts,
            "conflict_count": self.conflict_count,
            "notes": self.notes,
            "applied_at": self.applied_at,
        }


def summarize(
    actions: list[Action],
    conflicts: list[dict[str, Any]],
    pack: dict[str, Any],
    *,
    dry_run: bool,
) -> MergeReport:
    tables: dict[str, dict[str, int]] = {}
    for a in actions:
        bucket = tables.setdefault(
            a.table, {"inserted": 0, "updated": 0, "kept": 0, "tombstoned": 0}
        )
        if a.kind == "insert":
            bucket["inserted"] += 1
        elif a.kind == "update":
            bucket["updated"] += 1
        elif a.kind == "keep" and a.reason == "tombstoned":
            bucket["tombstoned"] += 1
        elif a.kind == "keep":
            bucket["kept"] += 1
    inserted = sum(b["inserted"] for b in tables.values())
    updated = sum(b["updated"] for b in tables.values())
    kept = sum(b["kept"] for b in tables.values())
    tombstoned = sum(b["tombstoned"] for b in tables.values())
    tombstone_added = sum(1 for a in actions if a.kind == "tombstone_add")
    notes: list[str] = []
    if inserted:
        notes.append(f"新增 {inserted} 行（本地没有的）")
    if updated:
        notes.append(f"覆盖 {updated} 行（远端较新；逐条记在冲突日志里）")
    if kept:
        notes.append(f"保留本地 {kept} 行（本地不旧或这类行只增不改）")
    if tombstoned:
        notes.append(f"按墓碑跳过 {tombstoned} 行（本机删过，不被旧包复活）")
    if tombstone_added:
        notes.append(f"记下 {tombstone_added} 条远程墓碑（继续传给下一台；**不删本地数据**）")
    if not actions:
        notes.append("没有需要合并的东西（两边的这些表已经一致）")
    return MergeReport(
        dry_run=dry_run,
        from_device=str(pack.get("device_id") or "?"),
        pack_created_at=str(pack.get("created_at") or ""),
        pack_schema_version=_as_int(pack.get("schema_version")),
        tables=tables,
        inserted=inserted,
        updated=updated,
        kept=kept,
        tombstoned=tombstoned,
        tombstone_added=tombstone_added,
        conflicts=conflicts[:MAX_CONFLICT_SAMPLES],
        conflict_count=len(conflicts),
        notes=notes,
        applied_at=_now(),
    )


def _insert_row(conn: sqlite3.Connection, table: str, row: dict[str, Any]) -> None:
    cols = [c for c in table_columns(conn, table) if c in row]
    values = [row[c] for c in cols]
    # 老包/别人的包可能没有 `updated_at`（v17 之前导出的，或者别的工具生成的）——
    # 那就用它的 `created_at` 顶上：**跨端判新旧必须有时间**，留空等于"永远最旧"。
    if (
        "updated_at" in table_columns(conn, table)
        and (row.get("updated_at") in (None, ""))
        and row.get("created_at")
    ):
        cols = [*cols, "updated_at"]
        values = [*values, row["created_at"]]
    if not cols:
        return
    placeholders = ",".join("?" for _ in cols)
    conn.execute(
        f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) VALUES ({placeholders})",
        tuple(values),
    )


def _update_row(conn: sqlite3.Connection, table: str, key: str, row: dict[str, Any]) -> None:
    """按主键覆盖（LWW 用）。主键列与"本机记账列"不写进去。"""
    cols = [c for c in table_columns(conn, table) if c in row]
    keep_out = {"version", "device_id", *pk_columns(table)}
    sets = [c for c in cols if c not in keep_out]
    if not sets:
        return
    where, values = _where_pk(table, key)
    assignments = ", ".join(f"{c} = ?" for c in sets + (["version"] if "version" in row else []))
    params = [row[c] for c in sets]
    if "version" in row:
        params.append(row["version"])
    conn.execute(f"UPDATE {table} SET {assignments} WHERE {where}", (*params, *values))


def _where_pk(table: str, key: str) -> tuple[str, list[str]]:
    """主键 → `WHERE` 片段与参数值（复合键用 `|` 拆回去）。"""
    pk = pk_columns(table)
    if len(pk) == 1:
        return f"{pk[0]} = ?", [key]
    parts = key.split("|")
    if len(parts) != len(pk):
        raise ValueError(f"{table} 的主键对不上：{key!r}")
    return " AND ".join(f"{c} = ?" for c in pk), parts


def merge_pack(
    conn: sqlite3.Connection,
    pack: dict[str, Any],
    *,
    dry_run: bool = False,
    device: str | None = None,
) -> MergeReport:
    """把一份同步包合并进本地（`dry_run=True` 只算不动）。

    规则见模块开头那张表。**导入不删本地任何数据**；覆盖与保留都逐条记进 `sync_logs`。
    """
    actions, conflicts = plan_merge(conn, pack, device=device)
    report = summarize(actions, conflicts, pack, dry_run=dry_run)
    if dry_run:
        return report

    for a in actions:
        if a.kind == "insert":
            _insert_row(conn, a.table, a.remote)
        elif a.kind == "update":
            _update_row(conn, a.table, a.entity_id, a.remote)
        elif a.kind == "tombstone_add":
            conn.execute(
                f"INSERT INTO {TOMBSTONE_TABLE} (entity, entity_id, deleted_at) VALUES (?,?,?) "
                "ON CONFLICT(entity, entity_id) DO UPDATE SET deleted_at = excluded.deleted_at",
                (a.table, a.entity_id, str(a.remote.get("deleted_at") or _now())),
            )
    # 冲突/覆盖**逐条**留痕（`sync_logs` 是本机的，不随包走）：报告里只放样例，日志里是全量
    for c in conflicts:
        conn.execute(
            "INSERT INTO sync_logs (id, entity, entity_id, local_ts, remote_ts, created_at, "
            "result, note) VALUES (?,?,?,?,?,?,?,?)",
            (
                uuid.uuid4().hex[:12],
                str(c.get("entity")),
                str(c.get("entity_id")),
                str(c.get("local_ts") or ""),
                str(c.get("remote_ts") or ""),
                _now(),
                str(c.get("result") or ""),
                str(c.get("note") or "")[:400],
            ),
        )
    _put_raw(conn, KEY_LAST_IMPORT, json.dumps(
        {
            "at": report.applied_at,
            "from_device": report.from_device,
            "totals": {
                "inserted": report.inserted,
                "updated": report.updated,
                "kept": report.kept,
                "tombstoned": report.tombstoned,
                "tombstone_added": report.tombstone_added,
            },
            "conflict_count": report.conflict_count,
        },
        ensure_ascii=False,
    ))
    conn.commit()
    logs.log_event(
        "sync_import", from_device=report.from_device, inserted=report.inserted,
        updated=report.updated, kept=report.kept, tombstoned=report.tombstoned,
    )
    return report


# ---------------------------------------------------------------- 给界面的现状
def status(conn: sqlite3.Connection) -> dict[str, Any]:
    """同步现状（**只报事实**）：设备号、上次导出/导入、冲突数、墓碑数、边界说明。"""
    conflicts = conn.execute("SELECT COUNT(*) AS n FROM sync_logs").fetchone()["n"]
    tombstones = (
        conn.execute(f"SELECT COUNT(*) AS n FROM {TOMBSTONE_TABLE}").fetchone()["n"]
        if _exists(conn, TOMBSTONE_TABLE)
        else 0
    )

    def _parsed(key: str) -> dict[str, Any] | None:
        raw = _get_raw(conn, key)
        if not raw:
            return None
        try:
            got = json.loads(raw)
        except ValueError:
            return None
        return got if isinstance(got, dict) else None

    return {
        # `file_sync` 是**真的能用了**（③ 落地）：导出/导入同步包。
        # `network_sync` 仍然没有（①②未做）——分开报，不拿一个布尔糊过去。
        "file_sync": True,
        "network_sync": False,
        "device_id": device_id(conn),
        "tombstones": int(tombstones or 0),
        "conflict_logs": int(conflicts or 0),
        "last_export": _parsed(KEY_LAST_EXPORT),
        "last_import": _parsed(KEY_LAST_IMPORT),
        "synced_tables": list(SYNCED_TABLES),
        "excluded_tables": list(EXCLUDED_TABLES),
        "note": "**走文件**的跨端同步：在一台机器导出同步包，拷到另一台导入。"
                "合并按 **version → updated_at** 判谁新；覆盖与保留都记进冲突日志（不静默）；"
                "**导入不会删你本地的任何东西**（远程删过的只记墓碑，不替你删）。"
                "同一 WiFi 直连（②）与手机离线（①）还没做。",
    }
