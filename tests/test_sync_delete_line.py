"""跨端删除的**可选项**（G 批 · T-G8b；用户 2026-09-23 定「覆盖，可以选择是否删除」）。

背景：v1 的边界是「导入**永不**删本地数据」（远程墓碑只防复活 + 继续传播）。
用户拍板后改成：**默认照旧不删，但导入时可以选「同时应用删除」**。这里的边界更细：

1. **默认 false**（保守）—— 老行为一个字不改；
2. 开了之后也不是无条件删：**本地那一行在"对方删除之后"又改过 → 不删**（记一条冲突说明）。
   理由："你后来还动过它"比"对方删了它"更能说明你的意图；
3. 判据是**本地那一行还在不在**，不是"这条墓碑我见没见过"——
   先按默认导过一次（只记墓碑、行留着），之后再勾上「同时应用删除」导一次，**那一次也该删**。
   （这条是实测踩出来的：原本"墓碑已知道就 continue"会把第二次导入整个跳过，
   用户会觉得"我勾了却没删"。）
4. `dry_run`（预览）与真导入走**同一套判断**：预览给出的 `totals.deleted` 就是会删掉的行数，
   而预览**一个字节都不写**。

时间戳都是显式的（`2026-09-2xT…`），不依赖"跑得快不快"。
"""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import facts as facts_mod
from timeflow.core import syncpack
from timeflow.storage import db as db_mod

DAY = "2026-09-23"


def _db(tmp_path, name: str, device: str):  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / name))
    facts_mod.clear()
    syncpack._put_raw(conn, syncpack.KEY_DEVICE_ID, device)  # noqa: SLF001
    conn.commit()
    return conn


def _task_row(task_id: str, title: str, *, updated_at: str) -> dict[str, object]:
    """包里的一条任务（字段与库里一致；只写我们关心的那几列）。"""
    return {
        "id": task_id, "title": title, "due_date": None, "group_name": None,
        "repeat_days": None, "parent_id": None, "is_myday": 0, "status": "未开始",
        "created_at": updated_at, "updated_at": updated_at, "version": 1,
        "note": None, "priority": "中", "flagged": 0, "attach": "[]", "remind_at": None,
        "task_type": "普通", "course_id": None, "doing_rank": None, "created_by": "me",
    }


def _pack(device: str, *, tables: dict | None = None, tombstones: list | None = None) -> dict:
    return {
        "format": syncpack.FORMAT, "format_version": syncpack.FORMAT_VERSION,
        "schema_version": 17, "device_id": device, "created_at": f"{DAY}T10:00:00",
        "tables": tables or {}, "tombstones": tombstones or [],
        "counts": {k: len(v) for k, v in (tables or {}).items()},
        "note": "测试用包",
    }


def _tomb(entity: str, entity_id: str, at: str) -> dict[str, str]:
    return {"entity": entity, "entity_id": entity_id, "deleted_at": at}


def _insert_task(conn, task_id: str, title: str, updated_at: str) -> None:
    conn.execute(
        "INSERT INTO tasks (id, title, is_myday, status, created_at, updated_at, version)"
        " VALUES (?,?,0,'未开始',?,?,1)",
        (task_id, title, updated_at, updated_at),
    )
    conn.commit()


# ---------------------------------------------------------------- ① 默认不删
def test_default_keeps_the_local_row_and_only_records_a_tombstone(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """默认（不勾）＝ 老行为：**行留着**，只记墓碑（好继续传给下一台）。"""
    mine = _db(tmp_path, "mine.db", "mine-1")
    _insert_task(mine, "t1", "会被删掉的", f"{DAY}T09:00:00")
    pack = _pack("other-1", tombstones=[_tomb("tasks", "t1", f"{DAY}T10:00:00")])

    report = syncpack.merge_pack(mine, pack)
    assert report.deleted == 0
    assert mine.execute("SELECT COUNT(*) n FROM tasks WHERE id='t1'").fetchone()["n"] == 1
    assert report.tombstone_added == 1
    row = mine.execute("SELECT * FROM sync_tombstones WHERE entity_id='t1'").fetchone()
    assert row is not None and row["deleted_at"] == f"{DAY}T10:00:00"
    assert any("本地保留" in str(c["result"]) for c in report.conflicts)


# ---------------------------------------------------------------- ② 勾上就删
def test_applying_deletions_removes_the_local_row(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """勾「同时应用删除」→ 本机这一行也删掉，并**逐条留痕**（不静默删）。"""
    mine = _db(tmp_path, "mine.db", "mine-1")
    _insert_task(mine, "t1", "会被删掉的", f"{DAY}T09:00:00")
    pack = _pack("other-1", tombstones=[_tomb("tasks", "t1", f"{DAY}T10:00:00")])

    report = syncpack.merge_pack(mine, pack, apply_deletions=True)
    assert report.deleted == 1
    assert report.kept_after_delete == 0
    assert mine.execute("SELECT COUNT(*) n FROM tasks WHERE id='t1'").fetchone()["n"] == 0
    logs = mine.execute("SELECT * FROM sync_logs WHERE entity_id='t1'").fetchall()
    assert any("本地也删了" in str(r["result"]) for r in logs), "删了必须留痕"
    assert "删掉 1 行" in " ".join(report.notes)


def test_a_locally_changed_row_is_not_deleted(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """**本地在对方删除之后又改过 → 不删**（"你后来还动过它"更能说明你的意图）。"""
    mine = _db(tmp_path, "mine.db", "mine-1")
    _insert_task(mine, "t1", "我后来改过的", f"{DAY}T11:00:00")   # 比删除时刻晚
    pack = _pack("other-1", tombstones=[_tomb("tasks", "t1", f"{DAY}T10:00:00")])

    report = syncpack.merge_pack(mine, pack, apply_deletions=True)
    assert report.deleted == 0 and report.kept_after_delete == 1
    assert mine.execute("SELECT COUNT(*) n FROM tasks WHERE id='t1'").fetchone()["n"] == 1
    assert any("本地更新过" in str(c["result"]) for c in report.conflicts)


def test_applying_later_still_deletes_what_was_known_before(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """★ 先按默认导过一次（只记墓碑、行留着），之后再勾上删 —— **那一次也该删**。

    判据是"本地那一行还在不在"，不是"这条墓碑我见没见过"。
    """
    mine = _db(tmp_path, "mine.db", "mine-1")
    _insert_task(mine, "t1", "会被删掉的", f"{DAY}T09:00:00")
    pack = _pack("other-1", tombstones=[_tomb("tasks", "t1", f"{DAY}T10:00:00")])

    first = syncpack.merge_pack(mine, pack)                     # 默认：不删
    assert first.deleted == 0 and first.tombstone_added == 1
    second = syncpack.merge_pack(mine, pack, apply_deletions=True)   # 这次勾上了
    assert second.deleted == 1, "墓碑早就知道，但本地这一行还在 → 勾了就该删"
    assert mine.execute("SELECT COUNT(*) n FROM tasks WHERE id='t1'").fetchone()["n"] == 0


def test_dry_run_reports_but_changes_nothing(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """预览与真导入**同一套判断**：预览给出会删几行，但一个字节都不写。"""
    mine = _db(tmp_path, "mine.db", "mine-1")
    _insert_task(mine, "t1", "会被删掉的", f"{DAY}T09:00:00")
    pack = _pack("other-1", tombstones=[_tomb("tasks", "t1", f"{DAY}T10:00:00")])

    preview = syncpack.merge_pack(mine, pack, dry_run=True, apply_deletions=True)
    assert preview.deleted == 1 and preview.dry_run is True
    assert mine.execute("SELECT COUNT(*) n FROM tasks WHERE id='t1'").fetchone()["n"] == 1
    assert mine.execute("SELECT COUNT(*) n FROM sync_tombstones").fetchone()["n"] == 0, \
        "预览连墓碑都不该写"


def test_second_apply_is_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """再导一次：没有行可删了 → 计数 0，不报错、也不重复记日志。"""
    mine = _db(tmp_path, "mine.db", "mine-1")
    _insert_task(mine, "t1", "会被删掉的", f"{DAY}T09:00:00")
    pack = _pack("other-1", tombstones=[_tomb("tasks", "t1", f"{DAY}T10:00:00")])
    first = syncpack.merge_pack(mine, pack, apply_deletions=True)
    logs_after_first = mine.execute("SELECT COUNT(*) n FROM sync_logs").fetchone()["n"]
    second = syncpack.merge_pack(mine, pack, apply_deletions=True)
    assert first.deleted == 1 and second.deleted == 0
    assert mine.execute("SELECT COUNT(*) n FROM sync_logs").fetchone()["n"] == logs_after_first


def test_relations_travel_with_their_task(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """删除也按主键走：任务的**关系行**（task_groups）与任务一起删（两边各有一条墓碑）。"""
    mine = _db(tmp_path, "mine.db", "mine-1")
    _insert_task(mine, "t1", "带分组的", f"{DAY}T09:00:00")
    mine.execute("INSERT INTO groups (id, name) VALUES ('g1','高数')")
    mine.execute("INSERT INTO task_groups (task_id, group_id) VALUES ('t1','g1')")
    mine.commit()
    pack = _pack("other-1", tombstones=[
        _tomb("tasks", "t1", f"{DAY}T10:00:00"),
        _tomb("task_groups", "t1|g1", f"{DAY}T10:00:00"),
    ])

    report = syncpack.merge_pack(mine, pack, apply_deletions=True)
    assert report.deleted == 2, "任务与它的关系行都要删（复合主键用 | 拼）"
    assert mine.execute("SELECT COUNT(*) n FROM task_groups").fetchone()["n"] == 0
    assert mine.execute("SELECT COUNT(*) n FROM tasks WHERE id='t1'").fetchone()["n"] == 0
    # 分组本身没被删（对面只删了任务与关系）
    assert mine.execute("SELECT COUNT(*) n FROM groups WHERE id='g1'").fetchone()["n"] == 1


def test_deleted_row_is_not_resurrected_by_an_older_pack(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """删掉之后再收到一份**旧的**包（还带着那条任务）→ 不许复活。"""
    mine = _db(tmp_path, "mine.db", "mine-1")
    _insert_task(mine, "t1", "会被删掉的", f"{DAY}T09:00:00")
    row = _task_row("t1", "会被删掉的", updated_at=f"{DAY}T09:00:00")
    old_pack = _pack("other-1", tables={"tasks": [row]},
                     tombstones=[_tomb("tasks", "t1", f"{DAY}T10:00:00")])
    syncpack.merge_pack(mine, old_pack, apply_deletions=True)
    assert mine.execute("SELECT COUNT(*) n FROM tasks WHERE id='t1'").fetchone()["n"] == 0

    again = syncpack.merge_pack(mine, _pack("other-1", tables={"tasks": [row]}))
    assert again.inserted == 0 and again.tombstoned == 1
    assert mine.execute("SELECT COUNT(*) n FROM tasks WHERE id='t1'").fetchone()["n"] == 0


# ---------------------------------------------------------------- ③ 接口层
def _client(tmp_path, name: str = "api.db"):  # type: ignore[no-untyped-def]
    return TestClient(create_app(str(tmp_path / name)))


def test_api_defaults_to_not_deleting(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """接口默认 `apply_deletions=false`：与以前一样（不删），且回显这个选择。"""
    client = _client(tmp_path)
    row = _task_row("t9", "对方那边有", updated_at=f"{DAY}T09:00:00")
    pack = _pack("other-1", tables={"tasks": [row]},
                 tombstones=[_tomb("tasks", "t9", f"{DAY}T10:00:00")])
    got = client.post("/api/sync/import", json={"pack": pack, "dry_run": True}).json()
    assert got["apply_deletions"] is False and got["totals"]["deleted"] == 0
    client.post("/api/sync/import", json={"pack": pack})
    assert any(t["title"] == "对方那边有" for t in client.get("/api/tasks").json()), \
        "导入的行在；墓碑只记不删（本机原本没有这一行，所以没什么可删）"


def test_api_can_apply_deletions(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """`apply_deletions=true` 能真的删掉本机那一行（走完整接口）。

    删除时刻取**远期**：这里本机那一行是"刚刚建的"，若写固定日期就成了**定时炸弹**
    （日期一过，本地行就"比删除更新"，规则会正确地不删 → 用例开始红）。
    """
    client = _client(tmp_path)
    mine = client.post("/api/tasks", json={"title": "我这边会被删的"}).json()
    pack = _pack("other-1", tombstones=[_tomb("tasks", mine["id"], "2099-01-01T00:00:00")])

    preview = client.post("/api/sync/import",
                          json={"pack": pack, "dry_run": True, "apply_deletions": True}).json()
    assert preview["totals"]["deleted"] == 1
    assert any(t["id"] == mine["id"] for t in client.get("/api/tasks").json()), "预览不许动库"

    applied = client.post("/api/sync/import",
                          json={"pack": pack, "apply_deletions": True}).json()
    assert applied["totals"]["deleted"] == 1
    assert not any(t["id"] == mine["id"] for t in client.get("/api/tasks").json())


def test_api_still_refuses_our_own_pack_and_reports_honestly(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """老规矩没变：自己的包 400；状态里 `network_sync` 仍如实为 false（② 只是"能连上"）。"""
    client = _client(tmp_path)
    mine = client.post("/api/tasks", json={"title": "本机的一条"}).json()
    exported = client.post("/api/sync/export", json={}).json()
    own = client.post("/api/sync/import",
                      json={"path": exported["path"], "apply_deletions": True})
    assert own.status_code == 400 and "自己导给自己" in own.json()["detail"]
    status = client.get("/api/sync/status").json()
    assert status["file_sync"] is True and status["network_sync"] is False
    assert "同时应用删除" in status["note"]
    assert mine["id"]


def test_environment_does_not_leak_between_tests(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """（守卫）本文件不设环境变量、不碰真实库 —— 顺手确认临时库是干净的。"""
    conn = db_mod.connect(str(tmp_path / "clean.db"))
    assert conn.execute("SELECT COUNT(*) n FROM tasks").fetchone()["n"] == 0
    assert conn.execute("SELECT COUNT(*) n FROM sync_tombstones").fetchone()["n"] == 0
    assert os.environ.get("TIMEFLOW_DATABASE__PATH") is None
    conn.close()
    facts_mod.clear()
