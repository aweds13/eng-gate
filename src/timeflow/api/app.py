"""FastAPI REST（SR-F7.3 AI 接口 + 供前端）。本地优先。

create_app(db_path) 封装为工厂；路由对任务做 CRUD / My Day / 逾期 / 多分组 / 轻债务摘要，
并预留后续域（专注/习惯/学业/复习/备忘录）的接口落点。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import sqlite3

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from timeflow.config import load_settings
from timeflow.core import academic as ac
from timeflow.core import feedback as fb
from timeflow.core import focus as fc
from timeflow.core import memo as memo
from timeflow.core import review as rv
from timeflow.core import sync as sync_mod
from timeflow.core import tasks as tm
from timeflow.core import team as team
from timeflow.core.ledger import ledger
from timeflow.storage import db


class TaskIn(BaseModel):
    title: str
    due_date: str | None = None
    group_name: str | None = None
    repeat_days: int | None = None
    parent_id: str | None = None
    is_myday: bool = False
    groups: list[str] = []


class TaskOut(BaseModel):
    id: str
    title: str
    due_date: str | None
    group_name: str | None
    repeat_days: int | None
    parent_id: str | None
    is_myday: bool
    status: str
    created_at: str
    updated_at: str
    version: int
    groups: list[str] = []


def _out(t: tm.Task, conn: sqlite3.Connection) -> TaskOut:
    groups = tm.get_task_groups(conn, t.id)
    return TaskOut(
        id=t.id,
        title=t.title,
        due_date=t.due_date,
        group_name=t.group_name,
        repeat_days=t.repeat_days,
        parent_id=t.parent_id,
        is_myday=t.is_myday,
        status=t.status,
        created_at=t.created_at,
        updated_at=t.updated_at,
        version=t.version,
        groups=groups,
    )


def create_app(db_path: str | None = None) -> FastAPI:
    settings = load_settings()
    conn = db.connect(db_path or settings.database.path)

    app = FastAPI(title="timeflow", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    web_index = Path(__file__).resolve().parent.parent.parent / "web" / "index.html"

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(web_index)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/config")
    def config() -> dict[str, Any]:
        return {
            "accent_color": settings.app.accent_color,
            "theme": settings.app.theme,
            "gpa_scale": settings.academic.gpa_scale,
        }

    @app.get("/api/tasks")
    def list_tasks() -> list[TaskOut]:
        return [_out(t, conn) for t in tm.list_tasks(conn)]

    @app.post("/api/tasks", response_model=TaskOut)
    def create_task(payload: TaskIn) -> TaskOut:
        try:
            t = tm.create_task(
                conn,
                title=payload.title,
                due_date=payload.due_date,
                group_name=payload.group_name,
                repeat_days=payload.repeat_days,
                parent_id=payload.parent_id,
                is_myday=payload.is_myday,
            )
            if payload.groups:
                tm.set_task_groups(conn, t.id, payload.groups)
            return _out(t, conn)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/api/tasks/{task_id}", response_model=TaskOut)
    def get_task(task_id: str) -> TaskOut:
        try:
            return _out(tm.get_task(conn, task_id), conn)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None

    @app.patch("/api/tasks/{task_id}", response_model=TaskOut)
    def update_task(task_id: str, payload: dict[str, Any]) -> TaskOut:
        try:
            fields = {k: v for k, v in payload.items() if k != "groups"}
            t = tm.update_task(conn, task_id, **fields)
            if "groups" in payload:
                tm.set_task_groups(conn, task_id, payload["groups"])
            return _out(t, conn)
        except (KeyError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.delete("/api/tasks/{task_id}")
    def delete_task(task_id: str) -> dict[str, str]:
        tm.delete_task(conn, task_id)
        return {"deleted": task_id}

    @app.post("/api/tasks/{task_id}/complete", response_model=TaskOut)
    def complete_task(task_id: str) -> TaskOut:
        try:
            return _out(tm.complete_task(conn, task_id), conn)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/api/mydays")
    def mydays() -> list[TaskOut]:
        return [_out(t, conn) for t in tm.myday_tasks(conn)]

    @app.get("/api/overdue")
    def overdue() -> list[TaskOut]:
        return [_out(t, conn) for t in tm.overdue_tasks(conn)]

    @app.get("/api/groups")
    def groups() -> list[dict[str, Any]]:
        return tm.list_groups(conn)

    @app.get("/api/summary")
    def summary() -> ledger.LedgerSummary:
        return ledger.summary(
            conn, mild=settings.ledger.debt_mild, medium=settings.ledger.debt_medium
        )

    @app.post("/api/tasks/{task_id}/myday")
    def toggle_myday(task_id: str) -> TaskOut:
        task = tm.get_task(conn, task_id)
        return _out(tm.update_task(conn, task_id, is_myday=not task.is_myday), conn)

    # ---- SR-F3 专注计时 ----
    @app.post("/api/focus/start")
    def focus_start(payload: dict[str, Any]) -> dict[str, str]:
        kind = payload.get("kind", fc.KIND_TOMATO)
        task_id = payload.get("task_id")
        device_id = payload.get("device_id")
        sid = fc.start_session(conn, kind=kind, task_id=task_id, device_id=device_id)
        return {"id": sid, "status": fc.STATUS_FINISHED}

    @app.post("/api/focus/{session_id}/finish")
    def focus_finish(session_id: str, payload: dict[str, Any]) -> dict[str, str]:
        duration = int(payload.get("duration_sec", 0))
        status = payload.get("status", fc.STATUS_FINISHED)
        fc.finish_session(conn, session_id, duration, status)
        return {"id": session_id, "status": status}

    @app.get("/api/focus/today")
    def focus_today() -> dict[str, float]:
        return {"focus_minutes": fc.today_focus_minutes(conn)}

    @app.get("/api/focus/tasks/{task_id}")
    def focus_task_sessions(task_id: str) -> list[dict[str, object]]:
        return fc.sessions_by_task(conn, task_id)

    @app.get("/api/focus/guard")
    def focus_guard() -> dict[str, object]:
        cfg = settings.focus
        return {
            "block_by_default": cfg.block_by_default,
            "do_not_disturb": cfg.do_not_disturb,
        }

    # ---- SR-F4 反馈/习惯/自检 ----
    @app.post("/api/feedback")
    def set_feedback(payload: dict[str, Any]) -> dict[str, str]:
        fb.set_daily_feedback(
            conn,
            on_date=payload.get("date"),
            plan_note=payload.get("plan_note"),
            executed=payload.get("executed"),
            gap_note=payload.get("gap_note"),
            focus_minutes=payload.get("focus_minutes"),
        )
        return {"status": "ok"}

    @app.get("/api/feedback")
    def get_feedback(date: str | None = None) -> dict[str, object] | None:
        return fb.get_feedback(conn, on_date=date)

    @app.post("/api/habits")
    def create_habit(payload: dict[str, Any]) -> dict[str, str]:
        return {"id": fb.create_habit(conn, payload["name"])}

    @app.post("/api/habits/{habit_id}/toggle")
    def toggle_habit(habit_id: str, on_date: str | None = None) -> dict[str, bool]:
        return {"done": fb.toggle_habit_log(conn, habit_id, on_date)}

    @app.get("/api/habits/{habit_id}")
    def get_habit(habit_id: str) -> dict[str, object]:
        return {"streak": fb.habit_streak(conn, habit_id), "logs": fb.habit_logs(conn, habit_id)}

    @app.get("/api/selfcheck")
    def selfcheck() -> dict[str, object]:
        return fb.self_check(conn)

    # ---- SR-F5 学业追踪 ----
    @app.post("/api/courses")
    def create_course(payload: dict[str, Any]) -> dict[str, str]:
        return {"id": ac.create_course(
            conn,
            name=payload["name"],
            credits=payload.get("credits"),
            teacher=payload.get("teacher"),
            note=payload.get("note"),
        )}

    @app.get("/api/courses")
    def list_courses() -> list[dict[str, object]]:
        return ac.list_courses(conn)

    @app.post("/api/assessments")
    def add_assessment(payload: dict[str, Any]) -> dict[str, str]:
        return {"id": ac.add_assessment(
            conn,
            course_id=payload["course_id"],
            name=payload["name"],
            due_date=payload.get("due_date"),
            weight=payload.get("weight"),
            score=payload.get("score"),
            note=payload.get("note"),
        )}

    @app.get("/api/assessments")
    def list_assessments(course_id: str | None = None) -> list[dict[str, object]]:
        return ac.list_assessments(conn, course_id)

    @app.post("/api/grades")
    def add_grade(payload: dict[str, Any]) -> dict[str, str]:
        return {"id": ac.add_grade(
            conn,
            score=payload["score"],
            credits=payload["credits"],
            course_id=payload.get("course_id"),
            term=payload.get("term"),
        )}

    @app.get("/api/gpa")
    def get_gpa(scale: str | None = None) -> dict[str, Any]:
        # scale 查询参数可临时切换（4.0 / 5.0），缺省用配置值
        gpa_scale = scale or settings.academic.gpa_scale
        if gpa_scale not in ac.VALID_GPA_SCALES:
            raise HTTPException(status_code=400, detail=f"非法 GPA 制式: {gpa_scale}")
        g, credits = ac.gpa(conn, gpa_scale)
        return {"gpa": g, "credits": credits, "scale": gpa_scale}

    # ---- SR-F6 复习间隔重复 ----
    @app.post("/api/review/items")
    def create_review(payload: dict[str, Any]) -> dict[str, str]:
        return {"id": rv.create_item(
            conn,
            title=payload["title"],
            form=payload.get("form", "qa"),
            source=payload.get("source", "internal"),
            ref_handle=payload.get("ref_handle"),
        )}

    @app.get("/api/review/due")
    def review_due() -> list[dict[str, object]]:
        return rv.due_items(conn)

    @app.post("/api/review/{item_id}/review")
    def do_review(item_id: str, payload: dict[str, Any]) -> dict[str, object]:
        try:
            return rv.review(conn, item_id, payload["feedback"])
        except KeyError:
            raise HTTPException(status_code=404, detail="复习卡不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    # ---- SR-F7 团队/AI 协作 ----
    @app.post("/api/team/assign")
    def team_assign(payload: dict[str, Any]) -> dict[str, str]:
        return {"id": team.assign_task(
            conn,
            task_id=payload["task_id"],
            assignee=payload["assignee"],
            assigner=payload.get("assigner", "me"),
            note=payload.get("note"),
        )}

    @app.patch("/api/team/assign/{assignment_id}")
    def team_status(assignment_id: str, payload: dict[str, Any]) -> dict[str, str]:
        team.update_assignment_status(conn, assignment_id, payload["status"])
        return {"id": assignment_id}

    @app.get("/api/team/assignments")
    def team_assignments(assignee: str | None = None) -> list[dict[str, object]]:
        return team.assignments(conn, assignee)

    # ---- SR-F8 备忘录/知识资产 ----
    @app.post("/api/memos")
    def create_memo(payload: dict[str, Any]) -> dict[str, str]:
        try:
            return {"id": memo.create_memo(
                conn,
                text=payload["text"],
                ref_handle=payload.get("ref_handle"),
                task_id=payload.get("task_id"),
            )}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/api/memos")
    def list_memos() -> list[dict[str, object]]:
        return memo.list_memos(conn)

    # B 系统产出/投入流水（SR-F8.4 产出评价器接口，第一版手动）
    @app.post("/api/ledger/output")
    def ledger_output(payload: dict[str, Any]) -> dict[str, str]:
        return {"id": memo.add_output_entry(
            conn, value=payload["value"], kind=payload.get("kind", "asset"),
            note=payload.get("note"), ref_handle=payload.get("ref_handle"),
        )}

    @app.post("/api/ledger/invest")
    def ledger_invest(payload: dict[str, Any]) -> dict[str, str]:
        return {"id": memo.add_invest_entry(
            conn, value=payload["value"], kind=payload.get("kind", "focus"),
            note=payload.get("note"),
        )}

    # ---- SR-F9 跨端同步 (LWW + 去重) ----
    @app.post("/api/sync/tasks")
    def sync_tasks(payload: dict[str, Any]) -> dict[str, Any]:
        records = payload.get("records", [])
        results = [sync_mod.merge_task(conn, r) for r in records]
        return {"merged": results}

    @app.get("/api/sync/logs")
    def sync_logs() -> list[dict[str, object]]:
        rows = conn.execute("SELECT * FROM sync_logs ORDER BY created_at DESC LIMIT 50").fetchall()
        return [
            {"id": r["id"], "entity": r["entity"], "entity_id": r["entity_id"],
             "local_ts": r["local_ts"], "remote_ts": r["remote_ts"]}
            for r in rows
        ]

    return app
