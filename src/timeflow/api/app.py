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
from timeflow.core import tasks as tm
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
        return {"accent_color": settings.app.accent_color, "theme": settings.app.theme}

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

    return app
