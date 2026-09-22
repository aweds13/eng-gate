"""F 批 · T-F10：分组名**允许重名**（用户 2026-09-21 定：「允许重名」）。

**为什么这不是一行改动**：老口径是"分组名全局唯一"（`groups.name` 上有 UNIQUE），
而"任务属于哪些分组"当时是**按名字**存的（`get_task_groups` 返回名字、界面按 `data-name` 勾选）——
名字一重复，同一个名字就指不回是哪一个分组。所以这一卡两件事一起做：

1. **schema v15**：重建 `groups` 表去掉全局 `UNIQUE(name)`，改为**同层（同一父下）唯一**
   （`COALESCE(parent_id,'')` 上的唯一索引；不套 COALESCE 的话"两个同名顶层分组"会漏过去）；
2. **成员关系改按 id**：`toggle_task_group` / `set_task_groups` 收 **group_id**；
   `TaskOut.groups` 给**路径**（显示用）、`TaskOut.group_ids` 给 id（勾选状态用）；
   洞察按**路径**归桶（否则「高数 / 作业」和「英语 / 作业」会被混成一格）。

覆盖：
- v14→v15 迁移（去掉全局唯一 + 幂等 + 老数据与关联完好）；
- 跨父重名可行、**同层重名仍然不行**（顶层两个同名也拦住）；
- 「没有就建、有就用」变成**同层**语义：换个父就是另一个分组，不会把别处的同名组搬过来；
- 改名：同层撞名 = 合并；跨层同名 = 允许（不再当合并）；
- 成员关系按 id：加入/移出/覆盖式设置；不存在 id → KeyError（不静默建组）；
- 路径/ id 在 `TaskOut` 与 API 里都对（重名时靠路径分辨）；
- 洞察按路径分开归桶。
"""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import facts as facts_mod
from timeflow.core import insights as ins
from timeflow.core import tasks as tm
from timeflow.storage import db as db_mod


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "names.db"))
    facts_mod.clear()
    yield c
    c.close()
    facts_mod.clear()


def _client(tmp_path, name: str = "names_api.db") -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(create_app(str(tmp_path / name)))


# ---------------------------------------------------------------- v15 迁移


def test_upgrade_v14_to_v15_drops_global_unique(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """老库（v14）升级：全局唯一没了、**同一父下唯一**还在，老分组与任务关联都没动。"""
    path = str(tmp_path / "old.db")
    c = db_mod.connect(path)
    gid = tm.create_group(c, "高数")
    step = tm.create_group(c, "第三章", parent_id=gid)
    task = tm.create_task(c, "刷题")
    tm.set_task_groups(c, task.id, [gid, step])
    c.execute("UPDATE schema_version SET version = 14")
    c.commit()
    c.close()

    c2 = db_mod.connect(path)
    # 版本号用常量比（**别写死数字**：schema 每加一版就会红一次，纯噪声 —— T-G6 的 v16 踩到）
    assert c2.execute("SELECT version FROM schema_version").fetchone()["version"] == (
        db_mod.SCHEMA_VERSION
    )
    # 跨父重名：现在能建了
    other = tm.create_group(c2, "英语")
    same_name = tm.create_group(c2, "第三章", parent_id=other)
    assert same_name != step
    assert tm.group_path(c2, same_name) == "英语 / 第三章"
    # 同层重名：约束仍然拦住（领域层那条路会先"复用"，所以直接插库来验证索引真的在）
    with pytest.raises(sqlite3.IntegrityError):
        c2.execute(
            "INSERT INTO groups (id, name, parent_id) VALUES ('dup', '第三章', ?)", (gid,)
        )
    c2.rollback()
    # 老关联完好
    assert tm.task_group_ids(c2, task.id) == sorted(
        [gid, step], key=lambda g: tm.group_path(c2, g)
    )
    c2.close()


def test_upgrade_v15_is_idempotent(conn) -> None:  # type: ignore[no-untyped-def]
    """重复升级不炸（重建有幂等判据：UNIQUE 自动索引没了就跳过）。"""
    gid = tm.create_group(conn, "高数")
    db_mod._migrate_v15(conn)
    db_mod._migrate_v15(conn)
    assert tm.get_group(conn, gid)["name"] == "高数"
    assert [g["path"] for g in tm.list_groups(conn)] == ["高数"]


# ---------------------------------------------------------------- 重名


def test_same_name_under_different_parents(conn) -> None:  # type: ignore[no-untyped-def]
    """「高数 / 作业」与「英语 / 作业」可以同时存在 —— 这就是"允许重名"要的东西。"""
    math = tm.create_group(conn, "高数")
    eng = tm.create_group(conn, "英语")
    m_hw = tm.create_group(conn, "作业", parent_id=math)
    e_hw = tm.create_group(conn, "作业", parent_id=eng)

    assert m_hw != e_hw
    assert sorted(g["path"] for g in tm.list_groups(conn)) == [
        "英语", "英语 / 作业", "高数", "高数 / 作业"
    ]


def test_same_name_under_same_parent_is_reused_or_rejected(conn) -> None:  # type: ignore[no-untyped-def]
    """同层重名：领域层**复用**（"没有就建、有就用"），API 层**400**（免得以为建了新组）。"""
    math = tm.create_group(conn, "高数")
    first = tm.create_group(conn, "作业", parent_id=math)
    assert tm.create_group(conn, "作业", parent_id=math) == first  # 复用
    assert len([g for g in tm.list_groups(conn) if g["name"] == "作业"]) == 1


def test_top_level_duplicate_names_also_blocked(conn) -> None:  # type: ignore[no-untyped-def]
    """顶层（`parent_id` 为空）也必须拦住 —— 唯一索引要套 `COALESCE`，
    否则 SQLite 会把多个 NULL 当成互不相同，两个同名顶层分组就漏过去了。"""
    first = tm.create_group(conn, "杂事")
    assert tm.create_group(conn, "杂事") == first
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO groups (id, name, parent_id) VALUES ('dup', '杂事', NULL)")
    conn.rollback()


def test_create_group_does_not_steal_same_named_group_elsewhere(conn) -> None:  # type: ignore[no-untyped-def]
    """换个父建同名分组 = **新分组**，不会把别处的同名分组悄悄搬过来。"""
    math = tm.create_group(conn, "高数")
    eng = tm.create_group(conn, "英语")
    m_hw = tm.create_group(conn, "作业", parent_id=math)
    e_hw = tm.create_group(conn, "作业", parent_id=eng)

    assert tm.get_group(conn, m_hw)["parent_id"] == math
    assert tm.get_group(conn, e_hw)["parent_id"] == eng


# ---------------------------------------------------------------- 改名：只同层合并


def test_rename_merges_only_within_the_same_parent(conn) -> None:  # type: ignore[no-untyped-def]
    """同层撞名 = 合并（老行为，只缩到同层）；**跨层同名允许**（就是重名）。"""
    math = tm.create_group(conn, "高数")
    eng = tm.create_group(conn, "英语")
    e_hw = tm.create_group(conn, "作业", parent_id=eng)
    e_tmp = tm.create_group(conn, "临时", parent_id=eng)
    m_hw = tm.create_group(conn, "作业", parent_id=math)
    t = tm.create_task(conn, "刷题")
    tm.toggle_task_group(conn, t.id, e_tmp, True)

    # 英语下的「临时」改名成「作业」（**同层**已有）→ 合并，关联跟着过去
    merged = tm.rename_group(conn, e_tmp, "作业")
    assert merged["id"] == e_hw
    assert tm.task_group_ids(conn, t.id) == [e_hw]
    assert [g["path"] for g in tm.list_groups(conn) if g["name"] == "作业"] == [
        "英语 / 作业", "高数 / 作业"
    ]

    # 高数下的「作业」改成「英语」（**跨层**同名）→ 不合并，只是重名
    renamed = tm.rename_group(conn, m_hw, "英语")
    assert renamed["id"] == m_hw and renamed["path"] == "高数 / 英语"
    assert len([g for g in tm.list_groups(conn) if g["name"] == "英语"]) == 2
    assert tm.task_group_ids(conn, t.id) == [e_hw]  # 关联没被合并弄丢


# ---------------------------------------------------------------- 按 id 的成员关系


def test_membership_is_by_id(conn) -> None:  # type: ignore[no-untyped-def]
    """加入/移出/覆盖式设置都按 id；不存在的 id → KeyError（不静默建一个"差不多"的组）。"""
    a = tm.create_group(conn, "甲")
    b = tm.create_group(conn, "乙")
    t = tm.create_task(conn, "任务")

    tm.set_task_groups(conn, t.id, [a, b])
    assert set(tm.task_group_ids(conn, t.id)) == {a, b}
    tm.toggle_task_group(conn, t.id, a, False)
    assert tm.task_group_ids(conn, t.id) == [b]
    with pytest.raises(KeyError):
        tm.toggle_task_group(conn, t.id, "甲", True)  # 名字不是 id
    with pytest.raises(KeyError):
        tm.set_task_groups(conn, t.id, [a, "nope"])


def test_membership_entries_and_paths_for_duplicate_names(conn) -> None:  # type: ignore[no-untyped-def]
    """重名时靠**路径**分辨：`task_group_entries` 给 id + name + path，界面勾选按 id。"""
    math = tm.create_group(conn, "高数")
    eng = tm.create_group(conn, "英语")
    m_hw = tm.create_group(conn, "作业", parent_id=math)
    e_hw = tm.create_group(conn, "作业", parent_id=eng)
    t = tm.create_task(conn, "两门课的作业")

    tm.toggle_task_group(conn, t.id, e_hw, True)
    entries = tm.task_group_entries(conn, t.id)
    assert entries == [{"id": e_hw, "name": "作业", "path": "英语 / 作业"}]
    assert tm.task_group_paths(conn, t.id) == ["英语 / 作业"]
    # 两个同名分组的 id 不同 → 谁也不会认错
    assert {g["id"] for g in tm.list_groups(conn) if g["name"] == "作业"} == {m_hw, e_hw}


def test_insights_bucket_by_path_not_name(conn) -> None:  # type: ignore[no-untyped-def]
    """洞察按**路径**归桶：两个都叫「作业」的分组必须分成两格，不能混成一个。"""
    math = tm.create_group(conn, "高数")
    eng = tm.create_group(conn, "英语")
    m_hw = tm.create_group(conn, "作业", parent_id=math)
    e_hw = tm.create_group(conn, "作业", parent_id=eng)
    today = date.today().isoformat()

    a = tm.create_task(conn, "数学作业")
    b = tm.create_task(conn, "英语作业")
    tm.set_task_groups(conn, a.id, [m_hw])
    tm.set_task_groups(conn, b.id, [e_hw])
    facts_mod.record(
        conn, kind="focus.finished", subject_type="task", subject_id=a.id,
        value_num=3600.0, occurred_at=f"{today}T10:00:00",
    )
    facts_mod.record(
        conn, kind="focus.finished", subject_type="task", subject_id=b.id,
        value_num=600.0, occurred_at=f"{today}T11:00:00",
    )

    got = {g.group: g.focus_hours for g in ins.group_insights(conn, days=7)}
    assert got == {"高数 / 作业": 1.0, "英语 / 作业": 0.17}


# ---------------------------------------------------------------- API


def test_api_allows_duplicate_names_across_parents(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """接口：跨父重名 201；同层重名 400（带路径原话）；勾选按 `group_id`。"""
    client = _client(tmp_path)
    math = client.post("/api/groups", json={"name": "高数"}).json()
    eng = client.post("/api/groups", json={"name": "英语"}).json()
    m_hw = client.post("/api/groups", json={"name": "作业", "parent_id": math["id"]}).json()
    e_hw = client.post("/api/groups", json={"name": "作业", "parent_id": eng["id"]}).json()
    assert (m_hw["path"], e_hw["path"]) == ("高数 / 作业", "英语 / 作业")

    clash = client.post("/api/groups", json={"name": "作业", "parent_id": math["id"]})
    assert clash.status_code == 400 and "高数 / 作业" in clash.json()["detail"]

    task = client.post("/api/tasks", json={"title": "两门课的作业"}).json()
    out = client.post(f"/api/tasks/{task['id']}/group",
                      json={"group_id": e_hw["id"], "on": True}).json()
    assert out["groups"] == ["英语 / 作业"] and out["group_ids"] == [e_hw["id"]]

    card = next(t for t in client.get("/api/tasks").json() if t["id"] == task["id"])
    assert card["groups"] == ["英语 / 作业"]
    assert card["group_ids"] == [e_hw["id"]]

    # 按名字传不再是合法输入（名字允许重名，指不回是哪一个）→ 404，不静默挑一个
    bad = client.post(f"/api/tasks/{task['id']}/group", json={"group_id": "作业", "on": True})
    assert bad.status_code == 404
