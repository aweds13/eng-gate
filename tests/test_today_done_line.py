"""F2/F1 · C 批 · T-C4 + T-C11：「今日产出分两类」+「今天做成了什么（可展开，含子步骤）」。

用户原话要点（2026-09-19）：
> "我点那个今日产出，学校 KPI 两条、知识资产三条……点这两个文字，会像选项卡一样蹦出来，
>  然后蹦出我完成哪些 KPI。……大任务很难一天全部推进完。所以我感觉是**你突出我完成那些步骤
>  也是很重要**，就是希望能看到自己完成哪些子步骤。"

覆盖：
- `ledger.summary()` 产出**按两类分开报**（`output_kpi` / `output_asset`），已撤销的不计，
  `output_count` 仍是总数；
- `ledger.today_done()`（只读事实层投影）：
  - `tasks` = 今天完成且**现在仍是完成**的非子任务（按 id 去重；完成→撤销→再完成只算一条）；
  - **今天完成又被撤销的不算"做成了"**（数字不许比明细多）；
  - `steps` = 今天完成的子步骤（带父任务标题）；`parents` = 父任务 + 进度（今天几步 / 共几步）；
  - `outputs` = 今天产出（**已撤销的如实列出并标记**，但不计入两类条数）；
  - 昨天的完成不算今天；父任务被硬删也不炸（`parent_title` 为 None）；
- API `GET /api/today/done`（含 `day` 覆盖与非法日期 400）；
- 前端护栏：三个可点开的项（**原地展开，不是弹窗**）+ 文案与"只读事实层"的诚实说明。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import facts as facts_mod
from timeflow.core import memo as memo_mod
from timeflow.core import tasks as tm
from timeflow.core.ledger import ledger
from timeflow.storage import db as db_mod

YESTERDAY = (date.today() - timedelta(days=1)).isoformat()


def _client(tmp_path, name: str = "today_done.db") -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(create_app(str(tmp_path / name)))


# ---------------------------------------------------------------- T-C4 产出分两类

def test_summary_splits_output_into_two_kinds(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "a.db"))
    memo_mod.add_output_entry(conn, kind="kpi", value=1, note="数学卷子")
    memo_mod.add_output_entry(conn, kind="asset", value=2, note="笔记")
    memo_mod.add_output_entry(conn, kind="asset", value=1, note="会被撤销")
    revoked = memo_mod.list_outputs(conn)[-1]["entry_id"]
    memo_mod.retract_output_entry(conn, str(revoked))

    s = ledger.summary(conn)
    assert s.output_kpi == 1 and s.output_asset == 1
    assert s.output_count == 2, "总数与明细同源：撤销的不算"
    conn.close()


# ---------------------------------------------------------------- T-C11 今天做成了什么

def test_today_done_empty(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "b.db"))
    d = ledger.today_done(conn)
    assert d.tasks == [] and d.steps == [] and d.parents == [] and d.outputs == []
    assert d.output_kpi == 0 and d.output_asset == 0
    conn.close()


def test_today_done_tasks_and_steps_with_parent_progress(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """完成的**整件任务**与**子步骤**分开列；步骤按父任务分组，带"该任务进度 x/y 步"。"""
    conn = db_mod.connect(str(tmp_path / "c.db"))
    parent = tm.create_task(conn, "高数作业")
    s1 = tm.create_subtask(conn, parent.id, "第 1 题")
    s2 = tm.create_subtask(conn, parent.id, "第 2 题")
    tm.create_subtask(conn, parent.id, "第 3 题")  # 没做完 → 进度分母要算上
    tm.complete_task(conn, s1.id)
    tm.complete_task(conn, s2.id)
    whole = tm.create_task(conn, "背单词")
    tm.complete_task(conn, whole.id)

    d = ledger.today_done(conn)
    assert [t.title for t in d.tasks] == ["背单词"], "子步骤不该混进「完成任务」"
    assert [s.title for s in d.steps] == ["第 1 题", "第 2 题"]
    assert all(s.parent_title == "高数作业" for s in d.steps)
    assert len(d.parents) == 1
    p = d.parents[0]
    assert (p.done_today, p.done_total, p.total_steps) == (2, 2, 3)
    conn.close()


def test_today_done_ignores_other_days(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """只算**今天**：把完成事实的时间改成昨天 → 不进今天的"做成了什么"（历史不冒充今天）。"""
    conn = db_mod.connect(str(tmp_path / "d.db"))
    t = tm.create_task(conn, "昨天做完的")
    tm.complete_task(conn, t.id)  # 先真完成（状态=完成），再把事实时间挪到昨天
    conn.execute(
        "UPDATE facts SET occurred_at = ? WHERE subject_id = ? AND kind = 'task.completed'",
        (f"{YESTERDAY}T10:00:00", t.id),
    )
    conn.commit()
    assert ledger.today_done(conn).tasks == []
    assert [x.title for x in ledger.today_done(conn, YESTERDAY).tasks] == ["昨天做完的"]
    conn.close()


def test_today_done_excludes_undone(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """今天完成又被撤销 → **不算"做成了"**（数字与明细同源，不许虚报）。"""
    conn = db_mod.connect(str(tmp_path / "e.db"))
    t = tm.create_task(conn, "做了又撤销")
    tm.complete_task(conn, t.id)
    assert [x.title for x in ledger.today_done(conn).tasks] == ["做了又撤销"]
    tm.uncomplete_task(conn, t.id)
    assert ledger.today_done(conn).tasks == []
    conn.close()


def test_today_done_dedupes_repeat_completions(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """完成 → 撤销 → 再完成：今天只有**一条**明细（否则同一件事会被数两次）。"""
    conn = db_mod.connect(str(tmp_path / "f.db"))
    t = tm.create_task(conn, "反复横跳")
    for _ in range(2):
        tm.complete_task(conn, t.id)
        tm.uncomplete_task(conn, t.id)
    tm.complete_task(conn, t.id)
    d = ledger.today_done(conn)
    assert len(d.tasks) == 1 and len([f for f in _completed_facts(conn)]) == 3
    conn.close()


def _completed_facts(conn) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    return facts_mod.query(conn, kind="task.completed")


def test_today_done_outputs_flag_retracted(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """产出明细列出今天全部条目；**已撤销的如实标注但不计入条数**。"""
    conn = db_mod.connect(str(tmp_path / "g.db"))
    memo_mod.add_output_entry(conn, kind="kpi", value=1, note="卷子")
    memo_mod.add_output_entry(conn, kind="asset", value=1, note="撤销我")
    revoked = str(memo_mod.list_outputs(conn)[-1]["entry_id"])
    memo_mod.retract_output_entry(conn, revoked)

    d = ledger.today_done(conn)
    assert len(d.outputs) == 2 and sum(1 for o in d.outputs if o.retracted) == 1
    assert d.output_kpi == 1 and d.output_asset == 0
    conn.close()


def test_today_done_survives_deleted_parent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """父任务被硬删：明细还在、`parent_title` 为 None —— 不许整页报错。"""
    conn = db_mod.connect(str(tmp_path / "h.db"))
    parent = tm.create_task(conn, "会被删的父任务")
    step = tm.create_subtask(conn, parent.id, "做了一半")
    tm.complete_task(conn, step.id)
    conn.execute("DELETE FROM tasks WHERE id = ?", (parent.id,))
    conn.commit()
    d = ledger.today_done(conn)
    assert len(d.steps) == 1 and d.steps[0].parent_title is None
    assert d.parents[0].title is None and d.parents[0].done_today == 1
    conn.close()


# ---------------------------------------------------------------- API

def test_api_today_done_shape_and_day_override(tmp_path) -> None:  # type: ignore[no-untyped-def]
    c = _client(tmp_path)
    tid = c.post("/api/tasks", json={"title": "今天的活"}).json()["id"]
    c.post(f"/api/tasks/{tid}/complete")
    got = c.get("/api/today/done").json()
    assert got["date"] == date.today().isoformat()
    assert [t["title"] for t in got["tasks"]] == ["今天的活"]
    assert got["steps"] == [] and got["parents"] == []

    other = c.get(f"/api/today/done?day={YESTERDAY}").json()
    assert other["tasks"] == [] and other["date"] == YESTERDAY
    assert c.get("/api/today/done?day=不是日期").status_code == 400


def test_api_summary_reports_two_output_kinds(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """两类各自**报条数**（与 `output_count` 同一口径：条目数，不是 value 累加）。"""
    c = _client(tmp_path)
    c.post("/api/ledger/output", json={"kind": "kpi", "value": 2, "note": "KPI"})
    c.post("/api/ledger/output", json={"kind": "asset", "value": 1, "note": "资产"})
    s = c.get("/api/summary").json()
    assert (s["output_kpi"], s["output_asset"], s["output_count"]) == (1, 1, 2)
    d = c.get("/api/today/done").json()
    assert (d["output_kpi"], d["output_asset"]) == (1, 1)
    assert len(d["outputs"]) == 2  # 明细与条数同源
