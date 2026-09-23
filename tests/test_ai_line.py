"""G 批 · T-G6：AI 接口的边界（SR-F7.3 / OP-34 / N23 + N46）。

**口径（用户 2026-09-21 定，见 `复盘/口径定案-待定清单.md` §2 的乙案）**：
- AI 接口第一版是 **只读 + 新增**；判据从"改不改"换成"**动的是不是你亲手写的东西**" ——
  **AI 能勾它自己建的步骤，不能碰你建的**；
- 进展**用子步骤表达**（加步骤本身就是"新增"，天然符合 N23）；
- AI 的动作**可审计、可撤销、可回溯"这是 AI 干的"**；
- **默认关**（口径同 N16「默认收严、用户再放宽」）。

覆盖：
- 默认关：整组 `/api/ai/*` 一律 403 带原话；打开/关闭的开关落在本机设置（三层默认）；
- 只读：读列表 / 读一个任务 + 步骤树（不改任何东西）；
- 新增：建任务、加步骤（`created_by='ai'`）、字段白名单（多传字段明确拒绝）、层数上限照样管；
- **边界**：AI 勾自己建的 → 200（事实 `source=ai`）；勾你建的（步骤**或**顶层任务）→ 400 带原话、
  状态一个字节不动、**不发事实**（不静默、也不留半条痕迹）；
- 联动：AI 勾掉最后一个步骤把父任务带完成 —— 系统联动照常，事实如实记 `source=ai`；
- 改/删：`PATCH/PUT/DELETE /api/ai/**` → 403 带原话；未知 GET/POST 路径 → 404 带原话；
- 来源：跨站 Origin 调不了（读写都 403）；关掉之后已建的 AI 项仍在（归属字段不变）；
- **回报进展**（T-G21，N46 / OP-32）：AI 往**你建的**任务上记一条 `task.progress.reported`
  （`source=ai`）→ 200 且**任务字段一个字节不动**（状态/版本号/备注都不变）—— 报告是新增事实，
  所以它**不需要** `created_by='ai'`（与「勾完成」那条边界正相反）；空话 / 多传字段 400、
  任务不存在 404、已删（回收站）400；撤销 = **追加** `task.progress.retracted` 指回原事实、
  原事实不删、一层层往回撤（没有可撤的 → 400 不静默）；卡片/详情要的
  `progress_count / progress_note / progress_at / progress_label` 由人侧接口带出；
- 账本口径不变：AI 完成的也照记（同一条路，不享受第二套算法）；
- 迁移 v16：老行 `created_by='me'`（不猜）、幂等、`_ensure_schema` 认它、新建库第一次连接就有这列；
- 人侧接口带出 `created_by`（界面徽标用）；非法 `created_by` 拒绝。
"""

from __future__ import annotations

import sqlite3
import time
from datetime import date

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import ai as ai_mod
from timeflow.core import facts as facts_mod
from timeflow.core import tasks as tm
from timeflow.storage import db as db_mod


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "ai.db"))
    facts_mod.clear()
    yield c
    c.close()
    facts_mod.clear()


def _client(tmp_path, name: str = "ai_api.db") -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(create_app(str(tmp_path / name)))


def _open(client: TestClient) -> None:
    assert client.put("/api/settings/ai", json={"enabled": True}).json()["enabled"] is True


def _sources(conn) -> list[str | None]:  # type: ignore[no-untyped-def]
    return [
        r["source"]
        for r in conn.execute(
            "SELECT source FROM facts WHERE kind = 'task.completed' ORDER BY recorded_at"
        ).fetchall()
    ]


# ---------------------------------------------------------------- 开关（默认关）


def test_everything_is_403_until_you_turn_it_on(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """**默认关**：整组 `/api/ai/*` 一律 403 带原话（读也拦 —— 网页读不到你的任务）。"""
    client = _client(tmp_path)
    assert client.get("/api/settings/ai").json()["enabled"] is False
    assert client.get("/api/settings/ai").json()["default_enabled"] is False

    for method, path in (
        ("get", "/api/ai/ping"),
        ("get", "/api/ai/tasks"),
        ("post", "/api/ai/tasks"),
        ("post", "/api/ai/tasks/x/progress"),
    ):
        call = getattr(client, method)
        resp = call(path, json={}) if method == "post" else call(path)
        assert resp.status_code == 403, (method, path, resp.status_code)
        assert "默认是**关**的" in resp.json()["detail"]


def test_switch_is_three_layered_and_rejects_junk(conn) -> None:  # type: ignore[no-untyped-def]
    """开关：本机设置优先于 config；只认布尔，怪值 400（**不静默当开或关**）。"""
    assert ai_mod.enabled(conn) is False
    assert ai_mod.enabled(conn, default=True) is True          # config 里的默认
    ai_mod.set_enabled(conn, False)
    assert ai_mod.enabled(conn, default=True) is False         # 本机设置优先
    ai_mod.set_enabled(conn, "on")
    assert ai_mod.enabled(conn) is True
    with pytest.raises(ValueError, match="只认 true/false"):
        ai_mod.set_enabled(conn, "也许吧")
    assert ai_mod.describe(conn)["configured"] is True


def test_api_switch_round_trip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path, "switch.db")
    off = client.put("/api/settings/ai", json={"enabled": False}).json()
    assert off["enabled"] is False
    _open(client)
    body = client.get("/api/ai/ping").json()
    assert body["ok"] is True and body["boundary"] and body["surface"]
    assert client.put("/api/settings/ai", json={"enabled": "怪值"}).status_code == 400
    assert client.put("/api/settings/ai", json={"enabled": False}).json()["enabled"] is False


def test_foreign_origin_cannot_touch_the_ai_surface(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """跨站网页读写都拦（整组要求本机来源）—— 只有本机程序能调。"""
    client = _client(tmp_path, "origin.db")
    _open(client)
    evil = {"Origin": "https://evil.example"}
    assert client.get("/api/ai/tasks", headers=evil).status_code == 403
    assert client.post("/api/ai/tasks", json={"title": "x"}, headers=evil).status_code == 403
    assert client.put("/api/settings/ai", json={"enabled": False}, headers=evil).status_code == 403
    ok_origin = {"Origin": "http://127.0.0.1:8000"}
    assert client.get("/api/ai/tasks", headers=ok_origin).status_code == 200


# ---------------------------------------------------------------- 只读


def test_read_tasks_and_steps(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """只读：列表 + 单任务（含步骤树）。读的动作**不改**任何东西（版本号与状态都不动）。"""
    client = _client(tmp_path, "read.db")
    _open(client)
    parent = client.post("/api/tasks", json={"title": "大任务", "is_myday": True}).json()
    client.post(f"/api/tasks/{parent['id']}/subtasks", json={"title": "第 1 步"})
    before = client.get(f"/api/tasks/{parent['id']}").json()

    listing = client.get("/api/ai/tasks").json()
    assert listing["total"] == 2 and len(listing["items"]) == 2
    assert listing["boundary"]
    one = client.get(f"/api/ai/tasks/{parent['id']}").json()
    assert one["task"]["id"] == parent["id"]
    assert [s["task"]["title"] for s in one["steps"]] == ["第 1 步"]
    assert one["steps"][0]["depth"] == 2
    assert client.get(f"/api/tasks/{parent['id']}").json() == before, "只读不能改东西"
    assert client.get("/api/ai/tasks/nope").status_code == 404


def test_read_filters_are_the_same_as_the_human_views(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """`view` / `assignee` 与人侧同口径（不另造一套筛选规则）。"""
    client = _client(tmp_path, "filter.db")
    _open(client)
    high = client.post("/api/tasks", json={"title": "重要的", "priority": "高"}).json()
    client.post("/api/tasks", json={"title": "普通的"})
    client.post("/api/team/assign", json={"task_id": high["id"], "assignee": "Hermes"})

    only_high = client.get("/api/ai/tasks?view=important").json()
    assert [t["title"] for t in only_high["items"]] == ["重要的"]
    mine_then = client.get("/api/ai/tasks?assignee=Hermes").json()
    assert [t["id"] for t in mine_then["items"]] == [high["id"]]
    assert client.get("/api/ai/tasks?limit=1").json()["count"] == 1
    assert client.get("/api/ai/tasks?view=查无此视图").status_code == 400


# ---------------------------------------------------------------- 新增


def test_create_task_and_step_are_marked_as_ai(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """新增：建任务 / 加步骤（给 `parent_id`）= 回报进展；归属写 `ai`。"""
    client = _client(tmp_path, "create.db")
    _open(client)
    mine = client.post("/api/tasks", json={"title": "你建的", "is_myday": True}).json()
    assert mine["created_by"] == "me"

    made = client.post("/api/ai/tasks", json={"title": "AI 建的", "is_myday": True}).json()
    assert made["created_by"] == "ai" and made["task"]["created_by"] == "ai"

    step = client.post(
        "/api/ai/tasks", json={"title": "读完第 3 章", "parent_id": mine["id"]}
    ).json()
    assert step["task"]["created_by"] == "ai"
    assert step["task"]["parent_id"] == mine["id"]
    assert step["task"]["is_myday"] is True, "步骤跟着父任务的 My Day（与人侧同一条路）"
    assert client.get(f"/api/tasks/{mine['id']}/subtasks").json()[0]["id"] == step["task"]["id"]


def test_create_rejects_unknown_fields_and_bad_input(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """**不静默忽略**：多传字段 400（否则 AI 以为设上了）；空标题 / 不存在的父任务也 400/404。"""
    client = _client(tmp_path, "badcreate.db")
    _open(client)
    resp = client.post("/api/ai/tasks", json={"title": "x", "status": "完成"})
    assert resp.status_code == 400 and "不认识的字段" in resp.json()["detail"]
    assert client.post("/api/ai/tasks", json={"title": "   "}).status_code == 400
    assert client.post("/api/ai/tasks", json={"title": "x", "parent_id": "nope"}).status_code == 404


def test_create_respects_the_three_level_limit(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """AI 也不能绕过「最多三层」那条（同一条领域规则，不因为是谁调的就松）。"""
    client = _client(tmp_path, "depth.db")
    _open(client)
    top = client.post("/api/ai/tasks", json={"title": "大任务"}).json()["task"]
    mid = client.post("/api/ai/tasks", json={"title": "子任务", "parent_id": top["id"]}).json()
    leaf = client.post(
        "/api/ai/tasks", json={"title": "子步骤", "parent_id": mid["task"]["id"]}
    ).json()
    too_deep = client.post(
        "/api/ai/tasks", json={"title": "第四层", "parent_id": leaf["task"]["id"]}
    )
    assert too_deep.status_code == 400 and "最多 3 层" in too_deep.json()["detail"]


# ---------------------------------------------------------------- 边界（这一卡的核心）


def test_ai_can_complete_its_own_step(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """AI 勾**自己建的**步骤：200，事实 `source=ai`（可回溯）。"""
    client = _client(tmp_path, "own.db")
    _open(client)
    step = client.post("/api/ai/tasks", json={"title": "AI 的步骤"}).json()["task"]
    done = client.post(f"/api/ai/tasks/{step['id']}/complete")
    assert done.status_code == 200 and done.json()["task"]["status"] == "完成"

    raw = db_mod.connect(str(tmp_path / "own.db"))
    assert _sources(raw) == ["ai"], "AI 的完成要在事实里留 source=ai"
    raw.close()


def test_ai_cannot_touch_what_you_created(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """**你建的，AI 碰不了**：400 带原话、状态不变、**不发事实**（不静默、也不留半条痕迹）。"""
    client = _client(tmp_path, "yours.db")
    _open(client)
    mine = client.post("/api/tasks", json={"title": "你建的事", "is_myday": True}).json()
    step = client.post(f"/api/tasks/{mine['id']}/subtasks", json={"title": "你建的步骤"}).json()

    for target in (mine["id"], step["id"]):
        resp = client.post(f"/api/ai/tasks/{target}/complete")
        assert resp.status_code == 400, resp.text
        assert "你亲手建的" in resp.json()["detail"]
        assert client.get(f"/api/tasks/{target}").json()["status"] != "完成"

    raw = db_mod.connect(str(tmp_path / "yours.db"))
    assert _sources(raw) == [], "被你拦下的勾选不该留下任何事实"
    raw.close()


def test_linkage_completion_is_recorded_honestly(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """AI 勾掉**最后一个**步骤 → 父任务被系统联动完成（父任务是你建的也一样）：
    联动是"跟谁点的无关"的系统规则，但事实如实记 `source=ai`，所以查得出来。"""
    client = _client(tmp_path, "linkage.db")
    _open(client)
    parent = client.post("/api/tasks", json={"title": "你建的大任务", "is_myday": True}).json()
    ai_step = client.post(
        "/api/ai/tasks", json={"title": "AI 的步骤", "parent_id": parent["id"]}
    ).json()["task"]
    your_step = client.post(
        f"/api/tasks/{parent['id']}/subtasks", json={"title": "你建的步骤"}
    ).json()
    client.post(f"/api/tasks/{your_step['id']}/complete")      # 你勾你自己的：还剩 AI 那步

    assert client.get(f"/api/tasks/{parent['id']}").json()["status"] != "完成"
    assert client.post(f"/api/ai/tasks/{ai_step['id']}/complete").status_code == 200
    assert client.get(f"/api/tasks/{parent['id']}").json()["status"] == "完成"

    raw = db_mod.connect(str(tmp_path / "linkage.db"))
    assert _sources(raw) == ["desktop", "ai", "ai"], "三次完成各记来源：你一次、AI 的步骤一次、" \
                                                    "联动把父任务带完成又一次"
    # 更强的一条：父任务的那条事实**也是 ai**（联动是系统行为，但"谁触发的"如实记下来）
    rows = raw.execute(
        "SELECT subject_id, source FROM facts WHERE kind='task.completed' ORDER BY recorded_at"
    ).fetchall()
    assert (parent["id"], "ai") in [(r["subject_id"], r["source"]) for r in rows]
    raw.close()


def test_completing_its_own_task_twice_is_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path, "twice.db")
    _open(client)
    task = client.post("/api/ai/tasks", json={"title": "AI 的任务"}).json()["task"]
    assert client.post(f"/api/ai/tasks/{task['id']}/complete").status_code == 200
    assert client.post(f"/api/ai/tasks/{task['id']}/complete").status_code == 200
    raw = db_mod.connect(str(tmp_path / "twice.db"))
    assert _sources(raw) == ["ai"], "重复勾不重复记事实（与人侧同一套幂等）"
    raw.close()


def test_ai_completion_counts_in_the_ledger_like_any_other(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """账本口径**不变**：AI 完成的也算完成收益（不因为是谁做的换算法）。"""
    client = _client(tmp_path, "ledger.db")
    _open(client)
    before = client.get("/api/summary").json()["gain_count"]
    task = client.post("/api/ai/tasks", json={"title": "AI 干完的"}).json()["task"]
    client.post(f"/api/ai/tasks/{task['id']}/complete")
    assert client.get("/api/summary").json()["gain_count"] == before + 1


def test_ownership_field_is_not_user_writable(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """`created_by` 由创建路径写死：人侧 PATCH 改不动它（否则边界可以自己给自己发通行证）。"""
    client = _client(tmp_path, "nowrite.db")
    task = client.post("/api/tasks", json={"title": "你建的"}).json()
    patched = client.patch(f"/api/tasks/{task['id']}", json={"created_by": "ai"}).json()
    assert patched["created_by"] == "me"


# ---------------------------------------------------------------- 报告进展（T-G21）


def _progress_facts(conn) -> list[tuple[str, str | None, str | None]]:  # type: ignore[no-untyped-def]
    """`(kind, source, value_text)`，按发生时间 —— 报告与撤销都留痕，所以两条都要看得见。"""
    return [
        (str(r["kind"]), r["source"], r["value_text"])
        for r in conn.execute(
            "SELECT kind, source, value_text FROM facts "
            "WHERE kind LIKE 'task.progress.%' ORDER BY occurred_at, recorded_at"
        ).fetchall()
    ]


def test_progress_report_is_a_fact_not_a_field_change(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """**这一卡的核心**：AI 往**你建的**任务上报进展 → 200，而且任务**一个字节没变**。

    为什么它跟"勾完成"不一样（那条是 400）：报告是**新增一条事实**，不碰你的任何字段 ——
    所以它不需要 `created_by='ai'`。这也正是"AI 当执行者"的落点：它干完一段就记一句，
    要不要据此勾完成仍然是**你**的事（后端**不自动标完成**）。
    """
    client = _client(tmp_path, "progress.db")
    _open(client)
    mine = client.post("/api/tasks", json={"title": "你建的大任务", "note": "我的备注"}).json()
    before = client.get(f"/api/tasks/{mine['id']}").json()

    resp = client.post(
        f"/api/ai/tasks/{mine['id']}/progress", json={"note": "读完第 3 章，第 6 题卡住"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True and body["boundary"]
    assert body["report"]["note"] == "读完第 3 章，第 6 题卡住"
    assert body["report"]["actor"] == "ai" and body["report"]["label"] == "AI 报告"

    after = client.get(f"/api/tasks/{mine['id']}").json()
    assert after["status"] == before["status"] == "未开始", "报告不该动状态"
    assert after["version"] == before["version"], "报告不该动版本号（它没改任务）"
    assert after["note"] == "我的备注", "报告不该碰你的备注"
    assert after["progress_count"] == 1
    assert after["progress_note"] == "读完第 3 章，第 6 题卡住"
    assert after["progress_at"] and after["progress_label"] == "AI 报告"

    raw = db_mod.connect(str(tmp_path / "progress.db"))
    assert _progress_facts(raw) == [("task.progress.reported", "ai", "读完第 3 章，第 6 题卡住")]
    raw.close()


def test_progress_report_rejects_empty_and_unknown_and_deleted(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """**不静默**：空话 400、多传字段 400、任务不存在 404、回收站里的任务 400。

    已删那条的理由同「尝试失败」：那张卡已经不在你手上，报告没人会看到（先恢复再报）。
    """
    client = _client(tmp_path, "badprogress.db")
    _open(client)
    task = client.post("/api/tasks", json={"title": "你建的"}).json()
    empty = client.post(f"/api/ai/tasks/{task['id']}/progress", json={"note": "   "})
    assert empty.status_code == 400 and "一句话" in empty.json()["detail"]
    assert client.post(f"/api/ai/tasks/{task['id']}/progress").status_code == 400
    extra = client.post(
        f"/api/ai/tasks/{task['id']}/progress", json={"note": "x", "status": "完成"}
    )
    assert extra.status_code == 400 and "不认识的字段" in extra.json()["detail"]
    assert client.post("/api/ai/tasks/nope/progress", json={"note": "x"}).status_code == 404

    client.delete(f"/api/tasks/{task['id']}")  # 软删 → 回收站
    gone = client.post(f"/api/ai/tasks/{task['id']}/progress", json={"note": "x"})
    assert gone.status_code == 400 and "回收站" in gone.json()["detail"]

    raw = db_mod.connect(str(tmp_path / "badprogress.db"))
    assert _progress_facts(raw) == [], "被拦下的报告一条事实都不该留"
    raw.close()


def test_progress_report_on_a_done_task_is_still_a_fact(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """完成之后报进展**允许**：那也是一条真事实（"AI 说它做完了"），不该由状态去否决。"""
    client = _client(tmp_path, "doneprog.db")
    _open(client)
    task = client.post("/api/tasks", json={"title": "已经完成的事"}).json()
    client.post(f"/api/tasks/{task['id']}/complete")
    assert client.post(
        f"/api/ai/tasks/{task['id']}/progress", json={"note": "补做完了附带的一节"}
    ).status_code == 200
    assert client.get(f"/api/tasks/{task['id']}").json()["progress_count"] == 1


def test_retract_is_append_only_and_peels_one_at_a_time(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """撤销 = **追加** `task.progress.retracted` 指回原事实（原事实不删）+ 一层层往回撤。

    与「复习改判」（`review.undone`）同款：留痕，不是抹掉。撤完就没有可撤的了 → **400 带原话**
    （不静默当成功 —— 否则界面会告诉你"撤了"，而事实层什么都没有）。
    """
    client = _client(tmp_path, "retract.db")
    _open(client)
    task = client.post("/api/tasks", json={"title": "你建的"}).json()
    client.post(f"/api/ai/tasks/{task['id']}/progress", json={"note": "第一条"})
    client.post(f"/api/ai/tasks/{task['id']}/progress", json={"note": "第二条"})
    assert client.get(f"/api/tasks/{task['id']}").json()["progress_count"] == 2

    first = client.post(f"/api/tasks/{task['id']}/progress/retract")
    assert first.status_code == 200 and first.json()["note"] == "第二条", "撤的是**最近一条**"
    shown = client.get(f"/api/tasks/{task['id']}").json()
    assert shown["progress_count"] == 1 and shown["progress_note"] == "第一条", "更早那条露出来"

    assert client.post(f"/api/tasks/{task['id']}/progress/retract").status_code == 200
    assert client.get(f"/api/tasks/{task['id']}").json()["progress_count"] == 0
    none_left = client.post(f"/api/tasks/{task['id']}/progress/retract")
    assert none_left.status_code == 400 and "没有可撤销" in none_left.json()["detail"]
    assert client.post("/api/tasks/nope/progress/retract").status_code == 404

    raw = db_mod.connect(str(tmp_path / "retract.db"))
    assert _progress_facts(raw) == [
        ("task.progress.reported", "ai", "第一条"),
        ("task.progress.reported", "ai", "第二条"),
        ("task.progress.retracted", "desktop", "第二条"),
        ("task.progress.retracted", "desktop", "第一条"),
    ], "两条原事实都还在（只是被指回去了）；撤销本身也留痕"
    raw.close()


def test_progress_reports_are_readable_over_the_ai_surface(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """AI 报过什么，AI 自己下一次读任务时看得见（`progress_*` 在只读接口上就带出来了）。"""
    client = _client(tmp_path, "airead.db")
    _open(client)
    task = client.post("/api/ai/tasks", json={"title": "AI 建的任务"}).json()["task"]
    client.post(f"/api/ai/tasks/{task['id']}/progress", json={"note": "写到一半"})
    one = client.get(f"/api/ai/tasks/{task['id']}").json()["task"]
    assert one["progress_count"] == 1 and one["progress_note"] == "写到一半"
    assert client.get("/api/ai/tasks").json()["items"][0]["progress_note"] == "写到一半"


# ---------------------------------------------------------------- 改 / 删：明确拒绝


def test_write_methods_are_refused_with_words(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """改/删这一版没有接口 → **明确拒绝**（403 + 原话 + 现有动作清单），不是含义不明的 404。"""
    client = _client(tmp_path, "refuse.db")
    _open(client)
    for method, path in (
        ("patch", "/api/ai/tasks/x"),
        ("put", "/api/ai/tasks/x"),
        ("delete", "/api/ai/tasks/x"),
    ):
        resp = getattr(client, method)(path)
        assert resp.status_code == 403, (method, resp.text)
        assert "只读 + 新增 + 勾自己建的" in resp.json()["detail"]
        assert "GET /api/ai/tasks" in resp.json()["detail"]
    unknown = client.get("/api/ai/nope")
    assert unknown.status_code == 404 and "只有：" in unknown.json()["detail"]


def test_turning_it_off_does_not_delete_anything(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """关掉之后：已建的 AI 项**还在**（归属不变）、接口又回到 403。"""
    client = _client(tmp_path, "offagain.db")
    _open(client)
    made = client.post("/api/ai/tasks", json={"title": "AI 建的"}).json()["task"]
    client.put("/api/settings/ai", json={"enabled": False})
    assert client.get("/api/ai/tasks").status_code == 403
    still = client.get(f"/api/tasks/{made['id']}").json()
    assert still["created_by"] == "ai" and still["title"] == "AI 建的"


# ---------------------------------------------------------------- 领域层与迁移


def test_manager_defaults_to_me_and_rejects_junk(conn) -> None:  # type: ignore[no-untyped-def]
    """领域层默认值就是"你建的"（**忘了传只会更严**），非法值拒绝。"""
    task = tm.create_task(conn, "默认归属")
    assert task.created_by == tm.CREATOR_ME
    with pytest.raises(ValueError, match="created_by 只能是"):
        tm.create_task(conn, "怪值", created_by="robot")
    assert tm.CREATOR_LABELS[tm.CREATOR_AI] == "AI 建的"
    assert tm.ACTOR_SOURCES[tm.CREATOR_AI] == "ai"


def test_actor_of_facts_follows_who_did_it(conn) -> None:  # type: ignore[no-untyped-def]
    """事实的 `source`：人做的仍是 `desktop`（不改历史含义），AI 做的记 `ai`。"""
    mine = tm.create_task(conn, "你建的", is_myday=True)
    tm.complete_task(conn, mine.id)
    theirs = tm.create_task(conn, "AI 建的", created_by=tm.CREATOR_AI)
    tm.complete_task(conn, theirs.id, actor=tm.CREATOR_AI)
    assert _sources(conn) == ["desktop", "ai"]
    with pytest.raises(ValueError, match="created_by 只能是"):
        tm.complete_task(conn, mine.id, actor="robot")


def test_ai_created_survives_row_roundtrip(conn) -> None:  # type: ignore[no-untyped-def]
    """写进库再读出来（`_row_to_task` 的兜底：缺列/怪值都当"你建的"，不猜成 AI）。"""
    task = tm.create_task(conn, "AI 的", created_by=tm.CREATOR_AI)
    assert tm.get_task(conn, task.id).created_by == "ai"
    conn.execute("UPDATE tasks SET created_by = '怪值' WHERE id = ?", (task.id,))
    conn.commit()
    assert tm.get_task(conn, task.id).created_by == tm.CREATOR_ME


def test_migration_v16_is_idempotent_and_defaults_to_me(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """v16：老行一律 `me`（**不猜**）；重复连接幂等；结构补齐认得这一列。"""
    path = tmp_path / "v15.db"
    raw = sqlite3.connect(path)
    raw.row_factory = sqlite3.Row
    db_mod._migrate_v1(raw)
    db_mod._migrate_v2(raw)
    raw.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    raw.execute("INSERT INTO schema_version (version) VALUES (15)")
    raw.execute(
        "INSERT INTO tasks (id, title, is_myday, status, created_at, updated_at, version) "
        "VALUES ('old','老任务',1,'未开始','2026-09-01T09:00:00','2026-09-01T09:00:00',1)"
    )
    raw.commit()
    raw.close()

    conn = db_mod.connect(str(path))
    assert conn.execute("SELECT version FROM schema_version").fetchone()["version"] == (
        db_mod.SCHEMA_VERSION
    )
    assert tm.get_task(conn, "old").created_by == tm.CREATOR_ME
    # 幂等：再连一次指纹不变
    first = db_mod._schema_fingerprint(conn)
    conn.close()
    conn = db_mod.connect(str(path))
    assert db_mod._schema_fingerprint(conn) == first
    conn.close()


def test_fresh_db_has_the_column_on_the_first_connect(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """新建库**第一次连接**就要有这一列 —— 漏了的话 AI 建任务会当场 no such column。

    （这一条不是假想：加 v16 时我就漏了 `_create_all`，是 T-G9 加的 `schema_healed` 日志
    在冒烟时把它喊出来的 —— 所以顺手把"第一次连接"钉住。）
    """
    conn = db_mod.connect(str(tmp_path / "fresh.db"))
    assert "created_by" in {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}
    task = tm.create_task(conn, "第一次连接就建 AI 任务", created_by=tm.CREATOR_AI)
    assert tm.get_task(conn, task.id).created_by == "ai"
    conn.close()


def test_expired_due_date_still_marks_overdue(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """AI 建任务走的是同一条创建路径：过期截止日照样标「逾期」（不另写一套判断）。"""
    client = _client(tmp_path, "due.db")
    _open(client)
    made = client.post("/api/ai/tasks", json={"title": "早就该做的", "due_date": "2020-01-01"})
    assert made.json()["task"]["status"] == tm.STATUS_OVERDUE
    assert date.today().isoformat() == time.strftime("%Y-%m-%d")
