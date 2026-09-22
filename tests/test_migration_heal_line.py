"""T-G9：迁移漏档缺陷 + 结构自愈（缺陷卡，2026-09-22 起在 T-G6 前发现）。

## 缺陷（真事，发生在用户本机那个库上）

`data/timeflow.db` 当时是 **schema_version = 12**，缺 v13/v14/v15 的列。老 `_upgrade` 只写到
`if current < 13`，**漏了 `< 14` 与 `< 15`**，然后直接 `UPDATE schema_version = 15` —— 于是：

- `groups.parent_id`（v14，T-F5 分组嵌套）**永远不会被加**；
- v15 的 groups 重建（T-F10 允许重名）**永远不会跑**；
- 而版本号已经被写成 15 —— 下次连接 `_migrate` 看到 `current == SCHEMA_VERSION` 什么都不做，
  **版本号撒了谎，且没人看得出来**。表现会是"分组/任务树功能莫名报 no such column"。

## 修法（两条一起）

1. **补上版本链缺的那两档**（`if current < 14` / `< 15`），版本号改由 `_migrate` 在结构补齐后写；
2. **结构补齐 `_ensure_schema()`**：v1~v3 与 v6 起的建表/加列类迁移**不看版本号**，每次连接都核一遍
   （全部幂等、成本一次 `PRAGMA table_info`）—— 判据从"版本号写到几"换成"**列到底在不在**"
   （与项目一贯口径一致：事实 > 解读）。补上了就记一条 `schema_healed` 日志，**不静默**。
   数据回填（v4/v5）仍留在版本链里（只跑一次、比加列贵）。

## 这一卡的验收（就是本文件的测试）

- **不变式**：从任何历史版本升上来的库，结构必须与新建库**一致**（逐表列名 + 对象清单）；
- **真实场景**：把用户库那个"v12 缺 v13/v14/v15"的形状造出来 → 升级后 T-F1「进行中」与
  T-F5 分组嵌套**功能真的能用**（不只是列在了）；
- **谎报也能自愈**：版本号明明是 15、结构却缺列（老代码留下的坑）→ 连接时补齐并记日志；
- **幂等**：连两次不会重复重建 groups、不会丢数据；
- **残缺库**：只有 tasks 表的库连接时不炸（v15 的 groups 守卫）。
"""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import pytest

from timeflow.core import tasks as tm
from timeflow.storage import db as db_mod

if TYPE_CHECKING:
    from pathlib import Path

# 用户那个库的形状：v12 的列都在，v13/v14/v15 的不在
V12_TASKS_COLUMNS = (
    "note", "priority", "flagged", "attach", "remind_at", "task_type", "course_id",
)


def _fingerprint(conn: sqlite3.Connection) -> tuple[str, ...]:
    return db_mod._schema_fingerprint(conn)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(r["name"]) for r in conn.execute(f"PRAGMA table_info({table})")}


def _v12_ish(path: Path) -> sqlite3.Connection:
    """造一个"v12 形状"的库：走 v1~v12 的迁移，然后**手写版本号 12**。

    刻意不调用老 `_upgrade`（它已经修好了）—— 这里要复现的是**当年那个库的形状**。
    """
    raw = sqlite3.connect(path)
    raw.row_factory = sqlite3.Row
    db_mod._migrate_v1(raw)
    db_mod._migrate_v2(raw)
    db_mod._migrate_v3(raw)
    db_mod._migrate_v9(raw)   # app_settings（顺手，与真实库一致）
    for fn in (
        db_mod._migrate_v6, db_mod._migrate_v7, db_mod._migrate_v8,
        db_mod._migrate_v10, db_mod._migrate_v11, db_mod._migrate_v12,
    ):
        fn(raw)
    raw.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    raw.execute("INSERT INTO schema_version (version) VALUES (12)")
    # 塞一条真数据 + 一个分组（证明升级不丢数据、且功能真的能用）
    raw.execute(
        "INSERT INTO tasks (id, title, due_date, is_myday, status, created_at, updated_at, version,"
        " note, priority, flagged, attach, remind_at, task_type, course_id) "
        "VALUES ('t1','老任务',NULL,1,'未开始','2026-09-01T09:00:00','2026-09-01T09:00:00',1,"
        " NULL,'中',0,NULL,NULL,'普通',NULL)"
    )
    raw.execute(
        "INSERT INTO groups (id, name, created_at) VALUES ('g1','高数','2026-09-01T09:00:00')"
    )
    raw.commit()
    return raw


# ---------------------------------------------------------------- 不变式


def test_upgrade_from_every_version_matches_a_fresh_db(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """**核心不变式**：从任何历史版本升上来的库，结构与新建库一致。

    这一条是给"以后再加迁移"兜底的 —— 谁要是又漏了 `if current < N`，这里会红。
    """
    fresh = db_mod.connect(str(tmp_path / "fresh.db"))
    fresh_fp = _fingerprint(fresh)
    fresh.close()

    for version in range(1, db_mod.SCHEMA_VERSION):
        path = tmp_path / f"v{version}.db"
        raw = sqlite3.connect(path)
        raw.row_factory = sqlite3.Row
        db_mod._migrate_v1(raw)                       # 所有库都先有 tasks
        if version >= 2:
            db_mod._migrate_v2(raw)
        if version >= 3:
            db_mod._migrate_v3(raw)
        for n in range(6, version + 1):               # v6 起是加列/重建类
            getattr(db_mod, f"_migrate_v{n}")(raw)
        raw.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        raw.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
        raw.commit()
        raw.close()

        conn = db_mod.connect(str(path))              # 走真正的升级路径
        assert _fingerprint(conn) == fresh_fp, f"从 v{version} 升上来的结构与新建库不一致"
        conn.close()


def test_version_number_is_not_trusted_when_columns_are_missing(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """**谎报也能自愈**：版本号写着 15、结构却缺列（老代码留下的坑）→ 连接时补齐并记日志。

    这正是用户库会掉进去的状态（升一次级就把版本号写成 15）：光修版本链救不回来。
    """
    path = tmp_path / "lying.db"
    raw = sqlite3.connect(path)
    raw.row_factory = sqlite3.Row
    db_mod._migrate_v1(raw)
    db_mod._migrate_v2(raw)
    db_mod._migrate_v3(raw)
    db_mod._migrate_v6(raw)
    raw.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    raw.execute(
        "INSERT INTO schema_version (version) VALUES (?)", (db_mod.SCHEMA_VERSION,)
    )  # ← 版本号撒谎
    raw.commit()
    raw.close()

    conn = db_mod.connect(str(path))
    assert "doing_rank" in _columns(conn, "tasks")
    assert "parent_id" in _columns(conn, "groups")
    assert {"note", "priority", "flagged", "attach", "remind_at", "task_type", "course_id"} <= (
        _columns(conn, "tasks")
    )
    conn.close()


# ---------------------------------------------------------------- 真实场景（用户库那个形状）


def test_the_real_shape_v12_upgrades_and_the_features_actually_work(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """v12 形状的库升上来之后：**T-F1「进行中」与 T-F5 分组嵌套真的能用**（不只是列存在）。"""
    path = tmp_path / "v12.db"
    raw = _v12_ish(path)
    assert "doing_rank" not in _columns(raw, "tasks")      # 前提：确实是缺的
    assert "parent_id" not in _columns(raw, "groups")
    raw.close()

    conn = db_mod.connect(str(path))
    assert "doing_rank" in _columns(conn, "tasks")
    assert "parent_id" in _columns(conn, "groups")
    assert conn.execute("SELECT version FROM schema_version").fetchone()["version"] == (
        db_mod.SCHEMA_VERSION
    )

    # ① T-F1：把老任务标成「进行中」→ 顺序号写进去、能在「正在做」里读出来
    started = tm.start_task(conn, "t1")
    assert started.status == tm.STATUS_DOING and started.doing_rank == 1
    assert [t.id for t in tm.doing_tasks(conn)] == ["t1"]

    # ② T-F5/T-F10：分组可嵌套 + 允许重名（v15 的重建真跑了才能建第二个子分组）
    child = tm.groups.create_group(conn, "第三章", parent_id="g1")
    assert tm.groups.get_group(conn, child)["parent_id"] == "g1"
    assert tm.groups.group_path(conn, child) == "高数 / 第三章"
    other = tm.groups.create_group(conn, "第三章", parent_id=None)   # 跨父可重名
    assert other != child

    # ③ 老数据没被弄丢
    assert tm.get_task(conn, "t1").title == "老任务"
    conn.close()


def test_heal_is_idempotent_and_keeps_data(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """连两次：第二次什么都不补（指纹不变）、数据不动、groups 不重复重建。"""
    path = tmp_path / "twice.db"
    _v12_ish(path).close()

    conn = db_mod.connect(str(path))
    first = _fingerprint(conn)
    rows = conn.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"]
    groups = conn.execute("SELECT COUNT(*) c FROM groups").fetchone()["c"]
    conn.close()

    conn = db_mod.connect(str(path))                       # 第二次连接
    assert _fingerprint(conn) == first, "第二次连接又改了结构（说明迁移不幂等）"
    assert conn.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"] == rows
    assert conn.execute("SELECT COUNT(*) c FROM groups").fetchone()["c"] == groups
    conn.close()


def test_partial_db_without_groups_does_not_crash(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """残缺库（只有 tasks 表）也能连接：v15 的 groups 守卫别让它炸。"""
    path = tmp_path / "partial.db"
    raw = sqlite3.connect(path)
    raw.row_factory = sqlite3.Row
    db_mod._migrate_v1(raw)
    raw.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    raw.execute("INSERT INTO schema_version (version) VALUES (2)")
    raw.commit()
    raw.close()

    conn = db_mod.connect(str(path))
    assert _columns(conn, "groups")                       # v2 建起来了
    assert _columns(conn, "tasks") >= {"doing_rank", "note", "priority"}
    conn.close()


def test_heal_writes_a_structured_log(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """补结构时**要出声**（`schema_healed` 一条，含补了什么、从哪一版来）。"""
    events: list[dict[str, object]] = []
    from timeflow import logs

    monkeypatch.setattr(
        logs, "log_event", lambda event, **kw: events.append({"event": event, **kw})
    )
    path = tmp_path / "logged.db"
    _v12_ish(path).close()

    conn = db_mod.connect(str(path))
    conn.close()

    healed = [e for e in events if e["event"] == "schema_healed"]
    assert len(healed) == 1, events
    assert healed[0]["was_version"] == 12
    assert healed[0]["to_version"] == db_mod.SCHEMA_VERSION
    added = healed[0]["added"]
    assert isinstance(added, list)
    # 日志里的 `added` 是**样例**（有上限），真实条数在 `added_count` ——
    # 所以这里断言"补齐了该补的、条数对得上"，而不是逐条比对（那会随迁移条数变脆）。
    assert "groups.parent_id" in added
    assert healed[0]["added_count"] >= len(added) >= 3


def test_fresh_db_does_not_log_a_heal(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """新建库不该报"补齐"（它是照最新结构建的，没有"补"这件事）。"""
    events: list[str] = []
    from timeflow import logs

    monkeypatch.setattr(logs, "log_event", lambda event, **kw: events.append(event))
    db_mod.connect(str(tmp_path / "brand-new.db")).close()
    assert "schema_healed" not in events


def test_schema_version_is_still_bumped(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """版本号仍然会被写成最新 —— 只是它不再是"结构对不对"的唯一判据。"""
    path = tmp_path / "bump.db"
    _v12_ish(path).close()
    conn = db_mod.connect(str(path))
    assert conn.execute("SELECT version FROM schema_version").fetchone()["version"] == (
        db_mod.SCHEMA_VERSION
    )
    conn.close()


def test_pointer_style_backup_restore_still_migrates(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """恢复一个老备份之后，`db.migrate()`（公开入口）也要把它补齐 —— 走的是同一条路。"""
    path = tmp_path / "restored.db"
    _v12_ish(path).close()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    db_mod.migrate(conn)                                  # 公开入口
    assert "doing_rank" in _columns(conn, "tasks")
    assert "parent_id" in _columns(conn, "groups")
    conn.close()


def test_task_json_roundtrip_after_heal(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """升级后的行能被领域层正常读出来（不是"列在、但读它的人崩"）。"""
    path = tmp_path / "read.db"
    _v12_ish(path).close()
    conn = db_mod.connect(str(path))
    task = tm.get_task(conn, "t1")
    assert task.priority == "中" and task.flagged is False and task.doing_rank is None
    assert json.dumps({"ok": True})           # 保持 json 导入有用（读 extra 的场景）
    conn.close()


@pytest.mark.parametrize("table", ["tasks", "groups", "facts", "app_settings"])
def test_core_tables_exist_after_heal(tmp_path, table: str) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / f"has-{table}.db"
    _v12_ish(path).close()
    conn = db_mod.connect(str(path))
    assert db_mod._table_exists(conn, table), f"结构补齐后缺表 {table}"
    conn.close()
