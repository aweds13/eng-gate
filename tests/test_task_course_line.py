"""F1/F5 · T-C12：任务「类型 + 所属课程」（SR-F5.4 学校任务带课程标签）。

用户需求原话（2026-09-19）：
> "有的作业任务它是课程相关的……我能选择它是作业类型的话。我能绑定到那个课程上。"

覆盖：
- schema v10 → v11 加两列（`task_type` / `course_id`）：幂等、老行一律「普通」+ 无课程、
  缺 tasks 表的残缺库不失败；
- 类型词表与 `course_assessments` 已有的四种学校事项同口径（作业/考试/论文/小测）+「普通」；
  非法类型**拒绝**（不静默降级成「普通」——那会让人以为绑定生效了）；
- 「类型 ↔ 课程」是一对，按**改完之后的状态**校验：
  - 挂课程必须课程存在（拒绝拼错的 id）；
  - **「普通」不允许挂课程**（拒绝而不是偷偷清掉：静默清空 = 数据丢失）；
  - 只传 `task_type='普通'` 而库里还挂着课程 → 同样拒绝，并要求一起清空课程；
- 清空课程 = 存 NULL（不是空串）；
- 改类型/课程**不发事实、不动账本**（它只是任务的属性，不是"发生了什么"）；
- Repeat 继承类型与课程；**课程被删后不再连累生成下一次**（回落"不挂课程"）；
- 跨端 `sync.merge_task`：远端带了就覆盖、没带就保留本地（别把"哪门课的作业"抹掉）；
- 任务详情/列表读到的 `course_name` 由后端给出；课程已删 → `None`（任务不跟着消失）。
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import academic as ac
from timeflow.core import sync as sync
from timeflow.core import tasks as tm
from timeflow.storage import db as db_mod


def _client(tmp_path, name: str = "course.db") -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(create_app(str(tmp_path / name)))


def _make_v10_db(path: str) -> None:
    """手工造一个 v10 旧库：tasks 齐全但**没有 task_type / course_id**。"""
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    raw.execute("INSERT INTO schema_version (version) VALUES (10)")
    raw.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, due_date TEXT,"
        " group_name TEXT, repeat_days INTEGER, parent_id TEXT, is_myday INTEGER DEFAULT 0,"
        " status TEXT, created_at TEXT, updated_at TEXT, version INTEGER DEFAULT 1,"
        " note TEXT, priority TEXT DEFAULT '中', flagged INTEGER DEFAULT 0, attach TEXT,"
        " remind_at TEXT)"
    )
    raw.execute(
        "INSERT INTO tasks (id,title,status,created_at,updated_at,version,priority)"
        " VALUES ('old1','旧作业','未开始','2026-01-01','2026-01-01',1,'高')"
    )
    raw.commit()
    raw.close()


# ---------------------------------------------------------------- 迁移（v11）

def test_upgrade_v10_adds_type_and_course(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """v10 → v11：补两列；老行一律「普通」+ 无课程 —— 不帮用户猜"哪条是作业"。"""
    p = str(tmp_path / "v10.db")
    _make_v10_db(p)

    conn = db_mod.connect(p)
    ver = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    assert int(ver["version"]) == db_mod.SCHEMA_VERSION
    row = conn.execute(
        "SELECT title, task_type, course_id FROM tasks WHERE id='old1'"
    ).fetchone()
    assert row["title"] == "旧作业"
    assert row["task_type"] == "普通"
    assert row["course_id"] is None
    conn.close()


def test_upgrade_v11_is_idempotent_and_missing_table_safe(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """迁移幂等（重复连接不报错）；残缺库没有 tasks 表时**跳过加列不失败**。"""
    p = str(tmp_path / "v10b.db")
    _make_v10_db(p)
    for _ in range(3):
        c = db_mod.connect(p)
        cols = {r["name"] for r in c.execute("PRAGMA table_info(tasks)").fetchall()}
        assert {"task_type", "course_id"} <= cols
        c.close()

    broken = str(tmp_path / "broken.db")
    raw = sqlite3.connect(broken)
    raw.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    raw.execute("INSERT INTO schema_version (version) VALUES (10)")
    raw.commit()
    raw.close()
    c = db_mod.connect(broken)  # 不抛异常即通过
    c.close()


# ---------------------------------------------------------------- 校验口径

def test_type_defaults_to_normal_without_course(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "a.db"))
    t = tm.create_task(conn, title="随手一件事")
    assert t.task_type == "普通" and t.course_id is None
    conn.close()


def test_illegal_type_is_rejected_not_downgraded(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """非法类型拒绝：静默存成「普通」会让用户以为绑定生效了。"""
    conn = db_mod.connect(str(tmp_path / "b.db"))
    with pytest.raises(ValueError, match="非法任务类型"):
        tm.create_task(conn, title="x", task_type="预习")
    with pytest.raises(ValueError, match="任务类型不能为空"):
        tm.create_task(conn, title="x", task_type="")
    conn.close()


def test_homework_can_bind_existing_course(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "c.db"))
    cid = ac.create_course(conn, name="高等数学")
    t = tm.create_task(conn, title="第三章习题", task_type="作业", course_id=cid)
    assert t.task_type == "作业" and t.course_id == cid
    assert tm.course_name(conn, t.course_id) == "高等数学"
    conn.close()


def test_unknown_course_is_rejected(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "d.db"))
    with pytest.raises(ValueError, match="课程不存在"):
        tm.create_task(conn, title="x", task_type="作业", course_id="nope123")
    conn.close()


def test_normal_type_cannot_hold_course(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """「普通」= 与课程无关：带着课程建/改一律**拒绝**（不静默清空）。"""
    conn = db_mod.connect(str(tmp_path / "e.db"))
    cid = ac.create_course(conn, name="线性代数")
    with pytest.raises(ValueError, match="不挂课程"):
        tm.create_task(conn, title="x", task_type="普通", course_id=cid)
    # 改：本来挂着的课程，被单独改成「普通」也要拒绝（要求一起清空课程）
    t = tm.create_task(conn, title="作业A", task_type="作业", course_id=cid)
    with pytest.raises(ValueError, match="不挂课程"):
        tm.update_task(conn, t.id, task_type="普通")
    after = tm.update_task(conn, t.id, task_type="普通", course_id=None)
    assert after.task_type == "普通" and after.course_id is None
    conn.close()


def test_update_course_only_checks_current_type(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """只传 `course_id` 时按**当前类型**判断：普通任务不能靠"只改课程"绕过规则。"""
    conn = db_mod.connect(str(tmp_path / "f.db"))
    cid = ac.create_course(conn, name="大学物理")
    normal = tm.create_task(conn, title="普通任务")
    with pytest.raises(ValueError, match="不挂课程"):
        tm.update_task(conn, normal.id, course_id=cid)
    hw = tm.create_task(conn, title="作业B", task_type="作业")
    assert tm.update_task(conn, hw.id, course_id=cid).course_id == cid
    # 清空课程：存 NULL，不是空串
    cleared = tm.update_task(conn, hw.id, course_id=None)
    assert cleared.course_id is None and cleared.task_type == "作业"
    row = conn.execute("SELECT course_id FROM tasks WHERE id=?", (hw.id,)).fetchone()
    assert row["course_id"] is None
    conn.close()


def test_type_change_does_not_touch_facts_or_ledger(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """类型/课程只是任务属性：改它不发事实、不动账本（不是"发生了什么"）。"""
    conn = db_mod.connect(str(tmp_path / "g.db"))
    cid = ac.create_course(conn, name="数据结构")
    t = tm.create_task(conn, title="实验报告", task_type="论文")
    before = conn.execute("SELECT COUNT(*) AS n FROM facts").fetchone()["n"]
    tm.update_task(conn, t.id, course_id=cid)
    tm.update_task(conn, t.id, task_type="作业")
    after = conn.execute("SELECT COUNT(*) AS n FROM facts").fetchone()["n"]
    assert before == after
    conn.close()


def test_repeat_inherits_type_and_course(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Repeat 继承类型与课程（每周的作业还是那门课的作业）。"""
    conn = db_mod.connect(str(tmp_path / "h.db"))
    cid = ac.create_course(conn, name="英语")
    t = tm.create_task(
        conn, title="每周作文", due_date="2026-09-01", repeat_days=7,
        task_type="作业", course_id=cid,
    )
    tm.complete_task(conn, t.id)
    nxt = [x for x in tm.list_tasks(conn) if x.id != t.id]
    assert len(nxt) == 1
    assert nxt[0].task_type == "作业" and nxt[0].course_id == cid
    conn.close()


def test_repeat_survives_deleted_course(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """课程被删掉后，重复任务照旧生成（回落"不挂课程"）—— 课程删除不级联，也不连累主链。"""
    conn = db_mod.connect(str(tmp_path / "i.db"))
    cid = ac.create_course(conn, name="已撤销的课")
    t = tm.create_task(
        conn, title="每周作业", due_date="2026-09-01", repeat_days=7,
        task_type="作业", course_id=cid,
    )
    conn.execute("DELETE FROM courses WHERE id=?", (cid,))
    conn.commit()
    tm.complete_task(conn, t.id)  # 不抛异常
    nxt = [x for x in tm.list_tasks(conn) if x.id != t.id]
    assert len(nxt) == 1 and nxt[0].task_type == "作业" and nxt[0].course_id is None
    # 原任务仍在（课程删除不影响任务本体），只是名字查不到了
    assert tm.get_task(conn, t.id).course_id == cid
    assert tm.course_name(conn, cid) is None
    conn.close()


# ---------------------------------------------------------------- 跨端合并

def test_merge_keeps_local_type_when_remote_omits_it(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """远端不带 task_type/course_id（老客户端）→ 保留本地值，别把"哪门课的作业"抹掉。"""
    conn = db_mod.connect(str(tmp_path / "j.db"))
    cid = ac.create_course(conn, name="概率论")
    t = tm.create_task(conn, title="作业C", task_type="作业", course_id=cid)
    sync.merge_task(conn, {
        "id": t.id, "title": "作业C（改）", "version": 99, "updated_at": "2099-01-01T00:00:00",
    })
    merged = tm.get_task(conn, t.id)
    assert merged.title == "作业C（改）"
    assert merged.task_type == "作业" and merged.course_id == cid
    conn.close()


def test_merge_applies_remote_type_when_present(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "k.db"))
    t = tm.create_task(conn, title="一件事")
    sync.merge_task(conn, {
        "id": t.id, "title": "一件事", "version": 99, "updated_at": "2099-01-01T00:00:00",
        "task_type": "考试", "course_id": None,
    })
    assert tm.get_task(conn, t.id).task_type == "考试"
    conn.close()


# ---------------------------------------------------------------- API

def test_api_create_and_patch_with_course(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """API 全链路：课程名由后端给出，列表/详情不必自己拉课程表。"""
    c = _client(tmp_path)
    cid = c.post("/api/courses", json={"name": "离散数学"}).json()["id"]
    created = c.post("/api/tasks", json={
        "title": "第二次作业", "task_type": "作业", "course_id": cid,
    })
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["task_type"] == "作业" and body["course_name"] == "离散数学"

    tid = body["id"]
    patched = c.patch(f"/api/tasks/{tid}", json={"task_type": "考试", "course_id": None})
    assert patched.status_code == 200, patched.text
    assert patched.json()["task_type"] == "考试" and patched.json()["course_id"] is None
    # 列表里也带课程名（卡片直接用，不额外请求）
    listed = c.get("/api/tasks").json()
    assert [t["task_type"] for t in listed if t["id"] == tid] == ["考试"]


def test_api_rejects_bad_type_and_bad_course(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """非法值一律 400 + 人话（不是 500，也不是"假装成功"）。"""
    c = _client(tmp_path)
    assert c.post("/api/tasks", json={"title": "x", "task_type": "预习"}).status_code == 400
    cid = c.post("/api/courses", json={"name": "统计"}).json()["id"]
    assert c.post("/api/tasks", json={
        "title": "x", "task_type": "普通", "course_id": cid,
    }).status_code == 400
    t = c.post("/api/tasks", json={"title": "y"}).json()
    r = c.patch(f"/api/tasks/{t['id']}", json={"task_type": "作业", "course_id": "nope"})
    assert r.status_code == 400 and "课程不存在" in r.json()["detail"]


def test_api_detail_shows_deleted_course_as_none(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """课程被删：任务照旧活着，只是 course_name 没了（界面显示「课程已删」）。"""
    c = _client(tmp_path)
    cid = c.post("/api/courses", json={"name": "临时课"}).json()["id"]
    tid = c.post("/api/tasks", json={
        "title": "作业D", "task_type": "作业", "course_id": cid,
    }).json()["id"]
    conn = db_mod.connect(str(tmp_path / "course.db"))
    conn.execute("DELETE FROM courses WHERE id=?", (cid,))
    conn.commit()
    conn.close()
    got = c.get(f"/api/tasks/{tid}").json()
    assert got["course_id"] == cid and got["course_name"] is None
