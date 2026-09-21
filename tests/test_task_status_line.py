"""F 批 · T-F1：任务状态机 —— 新增「待定」+ 补「进行中 / 归档」入口。

口径来源：`复盘/口径定案-待定清单.md` §1（**用户 2026-09-21 给出的完整设计**）：
- 「待定」= 闲置/挂在那儿、**没放弃、不计债**（行为同「取消」：不提醒、不进 My Day，
  但仍在「全部任务」里看得见）；
- 「进行中」= 我自己标"现在在做这个"，**可以同时多个**，先后用显式序号自己排（**不做拖拽**）；
- 「归档」= 收进档案、方便以后查阅（可撤销）；
- 「取消」= 打错了 / 没必要做了 —— ≈删除但留痕。

覆盖：
- schema v13 → `tasks.doing_rank`（幂等、老行为 NULL、缺表不失败）；
- 「待定」不计债（`overdue_tasks` / `ledger.summary` 都不含）、不提醒、不进 My Day、仍在列表；
- 「进行中」可多个 + 序号排序 + 上/下交换 + 头尾幂等 + 退出清序号；
- 非法跃迁一律 **ValueError / API 400**（已完成不置进行中、已删不搁置…）；
- 归档隐藏/可撤销；状态变化只留 `task.status_changed` 事实（完成/删除仍走各自的事实，不记两笔）；
- API：七个状态动作 + `GET /api/tasks/doing` + `doing-move`。
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import facts as facts_mod
from timeflow.core import tasks as tm
from timeflow.core.ledger import ledger
from timeflow.storage import db as db_mod

PAST = "2020-01-01"  # 一定已过（各测试只关心"是不是逾期"，不关心具体哪天）


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "status.db"))
    facts_mod.clear()
    yield c
    c.close()
    facts_mod.clear()


def _client(tmp_path, name: str = "status_api.db") -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(create_app(str(tmp_path / name)))


def _facts(conn: sqlite3.Connection, task_id: str) -> list[dict]:  # type: ignore[type-arg]
    return facts_mod.query(conn, kind="task.", subject_type="task", subject_id=task_id)


# ---------------------------------------------------------------- 迁移（v13）


def _make_v12_db(path: str) -> None:
    """手工造一个 v12 旧库：tasks 有类型/课程，**没有 doing_rank**。"""
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    raw.execute("INSERT INTO schema_version (version) VALUES (12)")
    raw.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, due_date TEXT,"
        " group_name TEXT, repeat_days INTEGER, parent_id TEXT, is_myday INTEGER DEFAULT 0,"
        " status TEXT, created_at TEXT, updated_at TEXT, version INTEGER DEFAULT 1,"
        " note TEXT, priority TEXT DEFAULT '中', flagged INTEGER DEFAULT 0,"
        " task_type TEXT DEFAULT '普通', course_id TEXT)"
    )
    raw.execute(
        "INSERT INTO tasks (id,title,status,created_at,updated_at,version)"
        " VALUES ('old1','旧任务','未开始','2026-01-01','2026-01-01',1)"
    )
    raw.commit()
    raw.close()


def test_upgrade_v12_adds_doing_rank(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """v12 → v13：补 `doing_rank` 列，老行一律 **NULL**（没排过序，界面排在最后 —— 不猜顺序）。"""
    p = str(tmp_path / "v12.db")
    _make_v12_db(p)

    conn = db_mod.connect(p)
    assert int(conn.execute("SELECT version FROM schema_version").fetchone()["version"]) == (
        db_mod.SCHEMA_VERSION
    )
    row = conn.execute("SELECT title, doing_rank FROM tasks WHERE id='old1'").fetchone()
    assert row["title"] == "旧任务"
    assert row["doing_rank"] is None
    conn.close()


def test_upgrade_v13_is_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = str(tmp_path / "v12b.db")
    _make_v12_db(p)
    for _ in range(3):
        c = db_mod.connect(p)
        assert int(c.execute("SELECT version FROM schema_version").fetchone()["version"]) == (
            db_mod.SCHEMA_VERSION
        )
        assert tm.list_tasks(c)[0].doing_rank is None
        c.close()


# ---------------------------------------------------------------- 「待定」口径


def test_pending_is_a_valid_status(conn: sqlite3.Connection) -> None:
    """「待定」进状态词表（约定层那次是人定的，决策记录在 `口径定案-待定清单` §1）。"""
    assert tm.STATUS_PENDING == "待定"
    assert tm.STATUS_PENDING in tm.VALID_STATUS
    assert tm.STATUS_PENDING in tm.PARKED_STATUSES
    assert tm.STATUS_PENDING not in tm.HIDDEN_STATUSES  # 搁置 ≠ 消失：仍在全部任务里看得见


def test_park_keeps_task_visible_but_out_of_work_views(conn: sqlite3.Connection) -> None:
    """待定 = 挂在那儿没放弃：**列表看得见**，但不进 My Day / 逾期 / 提醒。"""
    t = tm.create_task(
        conn, "先放着的一件事", due_date=PAST, is_myday=True, remind_at="2020-01-01T09:00"
    )
    assert [x.id for x in tm.overdue_tasks(conn)] == [t.id]  # 搁置前：确实在逾期栏里
    assert len(tm.due_reminders(conn)) == 1

    got = tm.park_task(conn, t.id)

    assert got.status == "待定"
    assert [x.id for x in tm.list_tasks(conn)] == [t.id]  # 仍在列表（留痕）
    assert tm.myday_tasks(conn) == []
    assert tm.overdue_tasks(conn) == []
    assert tm.due_reminders(conn) == []
    assert ledger.summary(conn).debt_count == 0  # **不计债**
    assert tm.park_task(conn, t.id).status == "待定"  # 幂等


def test_cancelled_task_does_not_count_as_debt_either(conn: sqlite3.Connection) -> None:
    """「取消」与「待定」同一条口径：搁置类不计债（取消走新动作，不再靠 PATCH 直改状态）。"""
    t = tm.create_task(conn, "不用做了", due_date=PAST)
    assert ledger.summary(conn).debt_count == 1
    tm.cancel_task(conn, t.id)
    assert ledger.summary(conn).debt_count == 0
    assert tm.overdue_tasks(conn) == []
    assert [x.id for x in tm.list_tasks(conn)] == [t.id]


def test_unpark_returns_to_resting_status(conn: sqlite3.Connection) -> None:
    """取回 = 回到「未开始」；截止日已过则回到「逾期」（与 `create_task` 同一口径）。"""
    past = tm.create_task(conn, "过期的待定", due_date=PAST)
    future = tm.create_task(conn, "还早的待定", due_date="2999-01-01")
    tm.park_task(conn, past.id)
    tm.park_task(conn, future.id)

    assert tm.un_park_task(conn, past.id).status == "逾期"
    assert tm.un_park_task(conn, future.id).status == "未开始"
    assert tm.un_park_task(conn, future.id).status == "未开始"  # 幂等（已不在搁置类里）


def test_park_rejects_done_and_deleted(conn: sqlite3.Connection) -> None:
    """已完成不给置待定（"完成了又待定"自相矛盾）；已删要先恢复 —— 拒绝而不是静默。"""
    done = tm.create_task(conn, "已经完成的")
    tm.complete_task(conn, done.id)
    with pytest.raises(ValueError):
        tm.park_task(conn, done.id)
    # 「取消」同理：对已完成的任务按取消 = 撤销完成 + 取消两件事一起做（会连带回退收益读数），
    # 所以拒绝，要求先撤销完成 —— 一次点击不偷偷做两件事。
    with pytest.raises(ValueError):
        tm.cancel_task(conn, done.id)

    gone = tm.create_task(conn, "删掉的")
    tm.delete_task(conn, gone.id)
    with pytest.raises(ValueError):
        tm.park_task(conn, gone.id)
    with pytest.raises(ValueError):
        tm.cancel_task(conn, gone.id)
    with pytest.raises(ValueError):
        tm.archive_task(conn, gone.id)


# ---------------------------------------------------------------- 「进行中」与顺序


def test_doing_allows_multiple_tasks_in_user_order(conn: sqlite3.Connection) -> None:
    a = tm.create_task(conn, "第一件")
    b = tm.create_task(conn, "第二件")
    c = tm.create_task(conn, "第三件")

    for t in (a, b, c):
        tm.start_task(conn, t.id)

    assert [t.id for t in tm.doing_tasks(conn)] == [a.id, b.id, c.id]  # 进来的顺序就是序号
    assert tm.get_task(conn, a.id).doing_rank == 1
    assert tm.start_task(conn, a.id).status == "进行中"  # 幂等，且不改序号
    assert tm.get_task(conn, a.id).doing_rank == 1


def test_move_doing_swaps_neighbours_and_stops_at_edges(conn: sqlite3.Connection) -> None:
    a = tm.create_task(conn, "A")
    b = tm.create_task(conn, "B")
    c = tm.create_task(conn, "C")
    for t in (a, b, c):
        tm.start_task(conn, t.id)

    tm.move_doing(conn, c.id, "up")
    assert [t.id for t in tm.doing_tasks(conn)] == [a.id, c.id, b.id]
    tm.move_doing(conn, c.id, "down")
    assert [t.id for t in tm.doing_tasks(conn)] == [a.id, b.id, c.id]
    # 到头/到尾：原地不动（幂等，不报错）
    assert tm.move_doing(conn, a.id, "up").id == a.id
    assert [t.id for t in tm.doing_tasks(conn)] == [a.id, b.id, c.id]
    assert tm.move_doing(conn, c.id, "down").id == c.id


def test_move_doing_rejects_non_doing_and_bad_direction(conn: sqlite3.Connection) -> None:
    t = tm.create_task(conn, "没在做")
    with pytest.raises(ValueError):
        tm.move_doing(conn, t.id, "up")
    tm.start_task(conn, t.id)
    with pytest.raises(ValueError):
        tm.move_doing(conn, t.id, "左")


def test_stop_clears_rank_and_returns_to_resting_status(conn: sqlite3.Connection) -> None:
    """移出进行中：序号清成 NULL（不留幽灵序号），状态回到未开始 / 逾期。"""
    future = tm.create_task(conn, "还早")
    past = tm.create_task(conn, "过期了", due_date=PAST)
    tm.start_task(conn, future.id)
    tm.start_task(conn, past.id)

    assert tm.stop_task(conn, future.id).status == "未开始"
    assert tm.get_task(conn, future.id).doing_rank is None
    assert tm.stop_task(conn, past.id).status == "逾期"
    assert tm.stop_task(conn, past.id).status == "逾期"  # 幂等（已经不在进行中）


def test_patching_status_away_from_doing_clears_rank(conn: sqlite3.Connection) -> None:
    """走通用 PATCH（`update_task(status=...)`）也要清序号 —— 否则两条路各写各的。"""
    t = tm.create_task(conn, "在做的")
    tm.start_task(conn, t.id)
    assert tm.get_task(conn, t.id).doing_rank == 1

    tm.update_task(conn, t.id, status="取消")
    assert tm.get_task(conn, t.id).doing_rank is None


def test_start_rejects_done_archived_parked(conn: sqlite3.Connection) -> None:
    """非法跃迁一律 ValueError（不静默变成"完成 + 进行中"同时成立）。"""
    done = tm.create_task(conn, "完成的")
    tm.complete_task(conn, done.id)
    with pytest.raises(ValueError):
        tm.start_task(conn, done.id)

    parked = tm.create_task(conn, "搁置的")
    tm.park_task(conn, parked.id)
    with pytest.raises(ValueError):
        tm.start_task(conn, parked.id)

    archived = tm.create_task(conn, "归档的")
    tm.archive_task(conn, archived.id)
    with pytest.raises(ValueError):
        tm.start_task(conn, archived.id)


# ---------------------------------------------------------------- 归档


def test_archive_hides_from_default_list_and_is_reversible(conn: sqlite3.Connection) -> None:
    t = tm.create_task(conn, "收起来的事", is_myday=True)
    tm.archive_task(conn, t.id)

    assert tm.get_task(conn, t.id).status == "归档"
    assert tm.list_tasks(conn) == []  # 默认列表不再显示
    assert tm.myday_tasks(conn) == []
    assert [x.id for x in tm.archived_tasks(conn)] == [t.id]  # 档案里能翻出来
    assert tm.overdue_tasks(conn) == []
    assert tm.archive_task(conn, t.id).status == "归档"  # 幂等

    assert tm.unarchive_task(conn, t.id).status == "未开始"
    assert [x.id for x in tm.list_tasks(conn)] == [t.id]
    assert tm.unarchive_task(conn, t.id).status == "未开始"  # 幂等


# ---------------------------------------------------------------- 事实


def test_status_change_records_one_fact(conn: sqlite3.Connection) -> None:
    """搁置类状态变化只留一条 `task.status_changed`（不动账本，但要可追溯）。"""
    t = tm.create_task(conn, "留痕用")

    tm.start_task(conn, t.id)
    tm.park_task(conn, t.id)
    tm.archive_task(conn, t.id)

    kinds = [f["kind"] for f in _facts(conn, t.id)]
    assert kinds == ["task.status_changed"] * 3
    got = _facts(conn, t.id)
    assert got[0]["extra"]["to_status"] == "进行中"
    assert got[1]["extra"]["from_status"] == "进行中"
    assert got[1]["extra"]["to_status"] == "待定"
    assert got[2]["extra"]["to_status"] == "归档"
    assert ledger.summary(conn).debt_count == 0  # 这些动作都不动账本


def test_done_transition_does_not_double_record(conn: sqlite3.Connection) -> None:
    """完成走 `task.completed`，**不再额外记一条** `task.status_changed`（一条变化一笔）。

    注意「进行中→完成」前面的「未开始→进行中」本来就该留一条 status_changed，
    所以这里断言的是：完成那一步只让 `task.completed` +1，没让 status_changed 再多一条。
    """
    t = tm.create_task(conn, "完成它")
    tm.start_task(conn, t.id)
    before = [f["kind"] for f in _facts(conn, t.id)]
    assert before == ["task.status_changed"]

    tm.complete_task(conn, t.id)

    kinds = [f["kind"] for f in _facts(conn, t.id)]
    assert kinds == ["task.status_changed", "task.completed"]


# ---------------------------------------------------------------- API


def test_api_state_actions_round_trip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path)
    created = client.post("/api/tasks", json={"title": "走接口", "due_date": PAST}).json()
    tid = created["id"]
    assert created["status"] == "逾期"

    assert client.post(f"/api/tasks/{tid}/park").json()["status"] == "待定"
    assert client.get("/api/overdue").json() == []
    assert client.get("/api/summary").json()["debt_count"] == 0

    assert client.post(f"/api/tasks/{tid}/unpark").json()["status"] == "逾期"
    assert client.post(f"/api/tasks/{tid}/cancel").json()["status"] == "取消"
    assert client.post(f"/api/tasks/{tid}/archive").json()["status"] == "归档"
    assert client.get("/api/tasks").json() == []
    assert [t["id"] for t in client.get("/api/tasks/archived").json()] == [tid]
    assert client.post(f"/api/tasks/{tid}/unarchive").json()["status"] == "逾期"


def test_api_doing_list_and_move(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path, "doing.db")
    ids = [client.post("/api/tasks", json={"title": f"任务{i}"}).json()["id"] for i in range(3)]
    for tid in ids:
        client.post(f"/api/tasks/{tid}/start")

    doing = client.get("/api/tasks/doing").json()
    assert [t["id"] for t in doing] == ids
    assert [t["doing_rank"] for t in doing] == [1, 2, 3]

    moved = client.post(f"/api/tasks/{ids[2]}/doing-move", json={"direction": "up"}).json()
    assert moved["doing_rank"] == 2
    assert [t["id"] for t in client.get("/api/tasks/doing").json()] == [ids[0], ids[2], ids[1]]

    assert client.post(f"/api/tasks/{ids[0]}/stop").json()["status"] == "未开始"
    assert [t["id"] for t in client.get("/api/tasks/doing").json()] == [ids[2], ids[1]]


def test_api_state_action_errors_are_honest(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """任务不存在 → 404；非法跃迁 → 400（带上原因），不静默、不 500。"""
    client = _client(tmp_path, "errors.db")
    assert client.post("/api/tasks/nope/start").status_code == 404
    assert client.post("/api/tasks/nope/archive").status_code == 404
    assert client.post("/api/tasks/nope/doing-move", json={"direction": "up"}).status_code == 404

    tid = client.post("/api/tasks", json={"title": "完成的"}).json()["id"]
    client.post(f"/api/tasks/{tid}/complete")
    bad = client.post(f"/api/tasks/{tid}/start")
    assert bad.status_code == 400
    assert "完成" in bad.json()["detail"]

    assert client.post(f"/api/tasks/{tid}/doing-move", json={"direction": "up"}).status_code == 400
