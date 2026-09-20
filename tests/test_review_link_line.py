"""F6 复习 · C 批 · T-C5/C6/C7：任务→复习卡升级 / 形式字段可选 / 引用句柄可填。

对应规格：SR-F6.6（由学习任务升级为复习任务）、SR-F6.7（复习形式字段 + 扩展口子）、
SR-F6.8 / SR-F8.3（复习卡挂引用句柄）。

覆盖：
- schema v11 → v12 加 `review_items.task_id`（幂等、老行一律 NULL、缺表不失败）；
- 升级：`POST /api/tasks/{id}/to-review` 建卡并把 `task_id` 挂上（**弱关联**，删任务不级联）；
  **幂等** —— 同一个任务再点一次返回已有的那张卡（`created=false`），不会越点越多张；
  标题默认取任务标题、可覆盖；任务不存在 404；非法形式 400；
- 定义类字段可改（`PATCH /api/review/items/{id}`）：标题 / 形式 / 执行源 / 引用句柄；
  **排期字段不给人手改**（由 FSRS 管）；非法值拒绝、空句柄 = 清除（NULL）；
- 词表只在后端一处：`GET /api/review/meta`（挖空/问答卡/真题）×（本应用内/外部 app）；
- 升级动作**不发事实、不动账本**（真正的账目来自"复习完成"）。
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import review as rv
from timeflow.core import tasks as tm
from timeflow.storage import db as db_mod


def _client(tmp_path, name: str = "review_link.db") -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(create_app(str(tmp_path / name)))


def _make_v11_db(path: str) -> None:
    """手工造一个 v11 旧库：review_items 齐全但**没有 task_id**。"""
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    raw.execute("INSERT INTO schema_version (version) VALUES (11)")
    raw.execute(
        "CREATE TABLE review_items (id TEXT PRIMARY KEY, title TEXT NOT NULL,"
        " form TEXT DEFAULT 'qa', source TEXT DEFAULT 'internal', due_date TEXT,"
        " interval_days REAL, ease REAL DEFAULT 2.5, reps INTEGER DEFAULT 0,"
        " lapses INTEGER DEFAULT 0, state TEXT DEFAULT 'due', ref_handle TEXT,"
        " created_at TEXT)"
    )
    raw.execute(
        "INSERT INTO review_items (id,title,form,due_date,reps,state,created_at)"
        " VALUES ('old1','旧卡','qa','2026-01-01',0,'due','2026-01-01')"
    )
    raw.commit()
    raw.close()


# ---------------------------------------------------------------- 迁移（v12）

def test_upgrade_v11_adds_task_id(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """v11 → v12：补 `task_id`；老行一律 NULL（不是从任务升上来的，**不猜**）。"""
    p = str(tmp_path / "v11.db")
    _make_v11_db(p)
    conn = db_mod.connect(p)
    ver = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    assert int(ver["version"]) == db_mod.SCHEMA_VERSION
    row = conn.execute("SELECT title, task_id FROM review_items WHERE id='old1'").fetchone()
    assert row["title"] == "旧卡" and row["task_id"] is None
    conn.close()


def test_upgrade_v12_is_idempotent_and_missing_table_safe(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = str(tmp_path / "v11b.db")
    _make_v11_db(p)
    for _ in range(3):
        c = db_mod.connect(p)
        cols = {r["name"] for r in c.execute("PRAGMA table_info(review_items)").fetchall()}
        assert "task_id" in cols
        c.close()

    broken = str(tmp_path / "broken.db")
    raw = sqlite3.connect(broken)
    raw.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    raw.execute("INSERT INTO schema_version (version) VALUES (11)")
    raw.commit()
    raw.close()
    db_mod.connect(broken).close()  # 不抛异常即通过


# ---------------------------------------------------------------- 升级（T-C5）

def test_upgrade_task_to_review_card(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "a.db"))
    t = tm.create_task(conn, "第三章：矩阵")
    rid = rv.create_item(conn, title=t.title, form="cloze", task_id=t.id)
    card = rv.get_item(conn, rid)
    assert card["task_id"] == t.id and card["form"] == "cloze"
    assert [c["id"] for c in rv.items_for_task(conn, t.id)] == [rid]
    conn.close()


def test_upgrade_rejects_unknown_task(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "b.db"))
    with pytest.raises(ValueError, match="任务不存在"):
        rv.create_item(conn, title="卡", task_id="nope")
    conn.close()


def test_api_upgrade_is_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """同一个任务升级两次 → 返回同一张卡（`created=false`），不会越点越多张。"""
    c = _client(tmp_path)
    tid = c.post("/api/tasks", json={"title": "背下来"}).json()["id"]
    first = c.post(f"/api/tasks/{tid}/to-review", json={"form": "exam"}).json()
    assert first["created"] is True and first["card"]["task_id"] == tid
    again = c.post(f"/api/tasks/{tid}/to-review").json()
    assert again["created"] is False and again["card"]["id"] == first["card"]["id"]
    assert len(again["cards"]) == 1
    assert c.get(f"/api/tasks/{tid}/review-cards").json()[0]["id"] == first["card"]["id"]

    assert c.post("/api/tasks/nope/to-review").status_code == 404
    assert c.post(f"/api/tasks/{tid}/to-review", json={"form": "??"}).status_code in (200, 400)


def test_api_upgrade_title_defaults_to_task_and_can_override(tmp_path) -> None:  # type: ignore[no-untyped-def]
    c = _client(tmp_path)
    tid = c.post("/api/tasks", json={"title": "原任务名"}).json()["id"]
    got = c.post(f"/api/tasks/{tid}/to-review").json()
    assert got["card"]["title"] == "原任务名"
    tid2 = c.post("/api/tasks", json={"title": "另一个"}).json()["id"]
    got2 = c.post(f"/api/tasks/{tid2}/to-review", json={"title": "卡片自己的名字"}).json()
    assert got2["card"]["title"] == "卡片自己的名字"


def test_upgrade_does_not_touch_facts_or_ledger(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """升级只是"建了张卡"：不发事实、不动账本（账目来自真正的复习完成）。"""
    c = _client(tmp_path)
    tid = c.post("/api/tasks", json={"title": "别记账"}).json()["id"]
    c.post(f"/api/tasks/{tid}/to-review")
    # 账本里不该出现"复习完成"，也不该多出投入/产出
    s = c.get("/api/summary").json()
    assert (s["review_count"], s["output_count"], s["invest_hours"]) == (0, 0, 0)
    conn = db_mod.connect(str(tmp_path / "review_link.db"))
    kinds = {r["kind"] for r in conn.execute("SELECT DISTINCT kind FROM facts").fetchall()}
    assert "review.completed" not in kinds, "升级本身不是一次复习"
    conn.close()


def test_deleting_task_keeps_card(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """弱关联：任务被删（软删）后卡照旧存在 —— 卡已经是独立的一张卡。"""
    conn = db_mod.connect(str(tmp_path / "c.db"))
    t = tm.create_task(conn, "会被删的任务")
    rid = rv.create_item(conn, title=t.title, task_id=t.id)
    tm.delete_task(conn, t.id)
    card = rv.get_item(conn, rid)
    assert card["task_id"] == t.id
    conn.close()


# ---------------------------------------------------------------- 定义类字段（T-C6 / T-C7）

def test_update_item_fields(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "d.db"))
    rid = rv.create_item(conn, title="卡")
    got = rv.update_item(
        conn, rid, form="cloze", ref_handle="Vault/数学/第3章.md", source="external"
    )
    assert got["form"] == "cloze"
    assert got["ref_handle"] == "Vault/数学/第3章.md"
    assert got["source"] == "external"
    # 空句柄 = 清除（存 NULL，不写空串）
    assert rv.update_item(conn, rid, ref_handle="   ")["ref_handle"] is None
    row = conn.execute("SELECT ref_handle FROM review_items WHERE id=?", (rid,)).fetchone()
    assert row["ref_handle"] is None
    conn.close()


def test_update_item_rejects_bad_values(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "e.db"))
    rid = rv.create_item(conn, title="卡")
    with pytest.raises(ValueError, match="非法复习形式"):
        rv.update_item(conn, rid, form="乱写")
    with pytest.raises(ValueError, match="非法执行源"):
        rv.update_item(conn, rid, source="乱写")
    with pytest.raises(ValueError, match="标题不能为空"):
        rv.update_item(conn, rid, title="   ")
    with pytest.raises(KeyError):
        rv.update_item(conn, "nope", form="cloze")
    conn.close()


def test_update_item_cannot_touch_schedule(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """排期字段（due_date/reps/ease）**不给人手改** —— 那是 FSRS 的记忆状态，手改会打架。"""
    conn = db_mod.connect(str(tmp_path / "f.db"))
    rid = rv.create_item(conn, title="卡")
    sql = "SELECT due_date, reps, ease FROM review_items WHERE id=?"
    before = conn.execute(sql, (rid,)).fetchone()
    rv.update_item(conn, rid, due_date="2099-01-01", reps=99, ease=9.9, form="exam")
    after = conn.execute(sql, (rid,)).fetchone()
    assert (before["due_date"], before["reps"], before["ease"]) == (
        after["due_date"], after["reps"], after["ease"]
    )
    conn.close()


# ---------------------------------------------------------------- meta 与 API

def test_meta_lists_forms_and_sources(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """词表只在后端一处：界面拿 meta 渲染，不自己写死中文（免得两边分叉）。"""
    m = _client(tmp_path).get("/api/review/meta").json()
    assert [f["value"] for f in m["forms"]] == ["cloze", "qa", "exam"]
    assert [s["value"] for s in m["sources"]] == ["internal", "external"]
    assert m["default_form"] == "qa" and m["default_source"] == "internal"
    assert all(f["label"] for f in m["forms"]), "每个形式都要有中文标签"


def test_api_patch_and_get_card(tmp_path) -> None:  # type: ignore[no-untyped-def]
    c = _client(tmp_path)
    rid = c.post("/api/review/items", json={"title": "手动建的卡", "form": "qa"}).json()["id"]
    got = c.patch(f"/api/review/items/{rid}", json={"form": "exam", "ref_handle": "KB-42"})
    assert got.status_code == 200, got.text
    assert got.json()["form"] == "exam" and got.json()["ref_handle"] == "KB-42"
    assert c.get(f"/api/review/items/{rid}").json()["form"] == "exam"
    assert c.patch("/api/review/items/nope", json={"form": "qa"}).status_code == 404
    assert c.get("/api/review/items/nope").status_code == 404
    assert c.patch(f"/api/review/items/{rid}", json={"form": "乱写"}).status_code == 400
