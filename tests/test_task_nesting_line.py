"""F 批 · T-F5：大任务三层嵌套 + 分组可嵌套。

**口径（用户 2026-09-21，`复盘/口径定案-待定清单.md` §1）**：
- 任务：**「大任务 → 子任务 → 子步骤」三层封顶**（`MAX_TASK_DEPTH = 3`），禁成环（已有）；
- 分组：`groups` 加 `parent_id`（schema **v14**）**可嵌套**，层数上限与任务同一个数字；
- **保留「任务可属多个分组」**（`task_groups` 不动，SR-F1.3 那条不变）；
- 分组名**仍然全局唯一** —— 成员关系本来就是按名字存的（`get_task_groups` 返回名字、
  界面按名字勾选），同名就指不回是哪一个；所以界面显示**路径**消歧义。

覆盖：
- v13→v14 迁移（加列 + 幂等 + 老数据 parent_id 为空 = 全是顶层，行为不变）；
- 任务三层：`task_depth` / 第四层被拒 / `task_tree` 前序 + 绝对层数 / 移父时按**整棵子树**算高度；
- 分组嵌套：树序列表（父在子前）、`path`、`depth`、建子分组、移到别处（含移回顶层）、
  **禁成环**、**超层数**、**有子分组不能删**、**有子分组不能"改名合并"**；
- 多归属不受影响（一个任务仍可同时属于父分组与子分组，`task_groups` 是平的多对多）；
- API：树的接口、`TaskOut.depth`、分组增删改与移父的 400/404。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import facts as facts_mod
from timeflow.core import tasks as tm
from timeflow.storage import db as db_mod


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "nest.db"))
    facts_mod.clear()
    yield c
    c.close()
    facts_mod.clear()


def _client(tmp_path, name: str = "nest_api.db") -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(create_app(str(tmp_path / name)))


def _chain(conn, n: int = 3) -> list[tm.Task]:  # type: ignore[no-untyped-def]
    """建一条 大任务 → 子任务 → 子步骤 的链，返回三层任务。"""
    top = tm.create_task(conn, "第 1 层：大任务")
    mid = tm.create_subtask(conn, top.id, "第 2 层：子任务")
    leaf = tm.create_subtask(conn, mid.id, "第 3 层：子步骤")
    return [top, mid, leaf]


# ---------------------------------------------------------------- v14 迁移


def test_upgrade_v13_to_v14_adds_parent_id(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """v13 老库升级：`groups.parent_id` 加上，老分组都是顶层（行为不变）。"""
    path = str(tmp_path / "old.db")
    c = db_mod.connect(path)
    gid = tm.create_group(c, "老分组")
    c.execute("UPDATE schema_version SET version = 13")
    c.commit()
    c.close()

    c2 = db_mod.connect(path)
    row = c2.execute("PRAGMA table_info(groups)").fetchall()
    assert "parent_id" in {str(r["name"]) for r in row}
    version = c2.execute("SELECT version FROM schema_version").fetchone()["version"]
    assert version == db_mod.SCHEMA_VERSION
    assert tm.get_group(c2, gid)["parent_id"] is None
    assert tm.get_group(c2, gid)["depth"] == 1
    c2.close()


def test_upgrade_v14_is_idempotent(conn) -> None:  # type: ignore[no-untyped-def]
    """重复升级不炸（加列是幂等的）。"""
    db_mod._migrate_v14(conn)
    db_mod._migrate_v14(conn)
    assert tm.list_groups(conn) == []


# ---------------------------------------------------------------- 任务三层


def test_task_depth_and_three_level_cap(conn) -> None:  # type: ignore[no-untyped-def]
    """层数：顶层 = 1、子任务 = 2、子步骤 = 3；**第四层被拒**（不静默截断）。"""
    top, mid, leaf = _chain(conn)
    assert tm.task_depth(conn, top.id) == 1
    assert tm.task_depth(conn, mid.id) == 2
    assert tm.task_depth(conn, leaf.id) == 3
    assert tm.MAX_TASK_DEPTH == 3

    with pytest.raises(ValueError) as e:
        tm.create_subtask(conn, leaf.id, "第 4 层：不该建出来")
    assert "最多 3 层" in str(e.value)
    assert tm.subtasks(conn, leaf.id) == []


def test_task_tree_is_preorder_with_depth(conn) -> None:  # type: ignore[no-untyped-def]
    """整棵子树：**前序**（父在子前）+ 绝对层数 —— N10「任务树/折叠呈现」靠它。"""
    top, mid, leaf = _chain(conn)
    other = tm.create_subtask(conn, top.id, "另一支")

    nodes = tm.task_tree(conn, top.id)
    assert [(n.task.title, n.depth) for n in nodes] == [
        ("第 2 层：子任务", 2),
        ("第 3 层：子步骤", 3),
        ("另一支", 2),
    ]
    assert tm.task_tree(conn, leaf.id) == []  # 叶子没有子树
    assert other.id in {n.task.id for n in nodes}


def test_reparent_checks_whole_subtree_height(conn) -> None:  # type: ignore[no-untyped-def]
    """移父时按**整棵子树**算高度：把"自己 + 底下还有一层"的中间层挂到第三层下面 → 拒绝。"""
    top, mid, leaf = _chain(conn)
    other_top = tm.create_task(conn, "另一个大任务")
    # 把 mid（子树 2 层：mid + leaf）挂到另一个顶层下 → 2 + 1 = 3 层，刚好放得下
    moved = tm.set_task_parent(conn, mid.id, other_top.id)
    assert tm.task_depth(conn, moved.id) == 2
    assert tm.task_depth(conn, leaf.id) == 3

    # 再想把 top（子树 3 层）挂到 mid 下面 → 4 层，拒绝
    with pytest.raises(ValueError) as e:
        tm.set_task_parent(conn, top.id, leaf.id)
    assert "最多 3 层" in str(e.value)


def test_reparent_still_rejects_cycles(conn) -> None:  # type: ignore[no-untyped-def]
    """成环仍然拒绝（老边界不能被新上限盖掉）。"""
    top, mid, _leaf = _chain(conn)
    with pytest.raises(ValueError):
        tm.set_task_parent(conn, top.id, mid.id)
    with pytest.raises(ValueError):
        tm.set_task_parent(conn, top.id, top.id)


# ---------------------------------------------------------------- 分组嵌套


def test_group_tree_order_path_and_depth(conn) -> None:  # type: ignore[no-untyped-def]
    """分组列表是**树序**（父在子前），每条带 `depth` 与 `path`。"""
    g1 = tm.create_group(conn, "高数")
    g2 = tm.create_group(conn, "第三章", parent_id=g1)
    tm.create_group(conn, "英语")

    listed = tm.list_groups(conn)
    assert [(g["name"], g["depth"], g["path"], g["parent_id"]) for g in listed] == [
        ("英语", 1, "英语", None),
        ("高数", 1, "高数", None),
        ("第三章", 2, "高数 / 第三章", g1),
    ]
    assert tm.group_path(conn, g2) == "高数 / 第三章"
    assert tm.group_depth(conn, g2) == 2


def test_group_depth_is_capped(conn) -> None:  # type: ignore[no-untyped-def]
    """分组层数上限与任务同一个数字：第三层下再建子分组 → 拒绝。"""
    g1 = tm.create_group(conn, "甲")
    g2 = tm.create_group(conn, "乙", parent_id=g1)
    g3 = tm.create_group(conn, "丙", parent_id=g2)
    assert tm.group_depth(conn, g3) == 3
    assert tm.MAX_GROUP_DEPTH == tm.MAX_TASK_DEPTH

    with pytest.raises(ValueError) as e:
        tm.create_group(conn, "丁", parent_id=g3)
    assert "最多 3 层" in str(e.value)


def test_group_can_be_moved_and_moved_back(conn) -> None:  # type: ignore[no-untyped-def]
    """「移进去 / 移出来」：`set_group_parent` 两个方向都行，幂等重复设置不报错。"""
    g1 = tm.create_group(conn, "项目 A")
    g2 = tm.create_group(conn, "阶段一")

    moved = tm.set_group_parent(conn, g2, g1)
    assert moved["parent_id"] == g1 and moved["path"] == "项目 A / 阶段一"
    assert tm.set_group_parent(conn, g2, g1)["path"] == "项目 A / 阶段一"  # 幂等

    back = tm.set_group_parent(conn, g2, None)
    assert back["parent_id"] is None and back["path"] == "阶段一"


def test_group_move_rejects_cycle_and_too_deep(conn) -> None:  # type: ignore[no-untyped-def]
    """成环 / 超层数（按整棵子树算）→ 拒绝，都带原话。"""
    g1 = tm.create_group(conn, "甲")
    g2 = tm.create_group(conn, "乙", parent_id=g1)
    g3 = tm.create_group(conn, "丙", parent_id=g2)

    with pytest.raises(ValueError) as e:
        tm.set_group_parent(conn, g1, g3)  # 挂到自己的孙子下
    assert "成环" in str(e.value)
    with pytest.raises(ValueError):
        tm.set_group_parent(conn, g1, g1)  # 挂到自己下

    # 甲这棵子树 3 层，挂到丙（第 3 层）下 → 5 层，拒绝
    g4 = tm.create_group(conn, "丁")
    with pytest.raises(ValueError) as e:
        tm.set_group_parent(conn, g4, g3)
    assert "最多 3 层" in str(e.value)


def test_group_with_children_cannot_be_deleted_or_merged(conn) -> None:  # type: ignore[no-untyped-def]
    """有子分组时**不能删**、**不能"改名合并"** —— 否则子分组会被悄悄甩到顶层。"""
    g1 = tm.create_group(conn, "甲")
    tm.create_group(conn, "乙", parent_id=g1)
    tm.create_group(conn, "丙")  # 另一个顶层，用来当合并目标

    with pytest.raises(ValueError) as e:
        tm.delete_group(conn, g1)
    assert "子分组" in str(e.value)
    with pytest.raises(ValueError) as e2:
        tm.rename_group(conn, g1, "丙")
    assert "子分组" in str(e2.value)

    # 把子分组先移走之后就能删了（边界是"有子分组"，不是"曾经有"）
    child = next(g for g in tm.list_groups(conn) if g["name"] == "乙")
    tm.set_group_parent(conn, str(child["id"]), None)
    assert tm.delete_group(conn, g1) == 0


def test_nested_groups_keep_multi_membership(conn) -> None:  # type: ignore[no-untyped-def]
    """嵌套不影响 SR-F1.3：一个任务仍可**同时**属于父分组与子分组（平的多对多）。"""
    g1 = tm.create_group(conn, "高数")
    tm.create_group(conn, "第三章", parent_id=g1)
    task = tm.create_task(conn, "刷第三章习题")

    tm.toggle_task_group(conn, task.id, "高数", True)
    tm.toggle_task_group(conn, task.id, "第三章", True)
    assert tm.get_task_groups(conn, task.id) == ["第三章", "高数"]

    counts = {g["name"]: g["task_count"] for g in tm.list_groups(conn)}
    assert counts == {"高数": 1, "第三章": 1}  # 各算各的，不重复计


def test_group_path_survives_missing_parent(conn) -> None:  # type: ignore[no-untyped-def]
    """父分组被删（坏数据）时路径不该炸：只显示能查到的那部分。"""
    g1 = tm.create_group(conn, "孤儿父")
    g2 = tm.create_group(conn, "孤儿子", parent_id=g1)
    conn.execute("DELETE FROM groups WHERE id = ?", (g1,))
    conn.commit()
    assert tm.group_path(conn, g2) == "孤儿子"


# ---------------------------------------------------------------- API


def test_api_task_tree_and_depth(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """`GET /api/tasks/{id}/tree` 给前序 + 层数；`TaskOut.depth` 在列表里也带着。"""
    client = _client(tmp_path)
    top = client.post("/api/tasks", json={"title": "大任务"}).json()
    mid = client.post(f"/api/tasks/{top['id']}/subtasks", json={"title": "子任务"}).json()
    leaf = client.post(f"/api/tasks/{mid['id']}/subtasks", json={"title": "子步骤"}).json()
    assert (top["depth"], mid["depth"], leaf["depth"]) == (1, 2, 3)

    tree = client.get(f"/api/tasks/{top['id']}/tree").json()
    assert [(n["title"], n["depth"]) for n in tree] == [("子任务", 2), ("子步骤", 3)]
    assert client.get(f"/api/tasks/{leaf['id']}/tree").json() == []
    assert client.get("/api/tasks/nope/tree").status_code == 404

    # 第四层：400 带原话
    r = client.post(f"/api/tasks/{leaf['id']}/subtasks", json={"title": "第四层"})
    assert r.status_code == 400 and "最多 3 层" in r.json()["detail"]


def test_api_group_nesting_roundtrip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """分组接口：建子分组 / 移父 / 树序列表 / 删除边界。"""
    client = _client(tmp_path)
    g1 = client.post("/api/groups", json={"name": "高数"}).json()
    g2 = client.post("/api/groups", json={"name": "第三章", "parent_id": g1["id"]}).json()
    assert (g2["depth"], g2["path"]) == (2, "高数 / 第三章")

    names = [g["title"] if "title" in g else g["path"] for g in client.get("/api/groups").json()]
    assert names == ["高数", "高数 / 第三章"]  # 树序：父在子前

    moved = client.post(f"/api/groups/{g2['id']}/parent", json={"parent_id": None}).json()
    assert moved["parent_id"] is None and moved["path"] == "第三章"

    # 有子分组时不能删；父分组不存在 → 404；成环 → 400
    client.post(f"/api/groups/{g2['id']}/parent", json={"parent_id": g1["id"]})
    assert client.delete(f"/api/groups/{g1['id']}").status_code == 400
    assert client.post("/api/groups", json={"name": "新组", "parent_id": "nope"}).status_code == 404
    cyc = client.post(f"/api/groups/{g1['id']}/parent", json={"parent_id": g2["id"]})
    assert cyc.status_code == 400 and "成环" in cyc.json()["detail"]
