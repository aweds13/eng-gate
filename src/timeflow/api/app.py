"""FastAPI REST（SR-F7.3 AI 接口 + 供前端）。本地优先。

create_app(db_path) 封装为工厂；路由对任务做 CRUD / My Day / 逾期 / 轻债务摘要。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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


def _out(t: tm.Task) -> TaskOut:
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
        return [_out(t) for t in tm.list_tasks(conn)]

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
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return _out(t)

    @app.get("/api/tasks/{task_id}", response_model=TaskOut)
    def get_task(task_id: str) -> TaskOut:
        try:
            return _out(tm.get_task(conn, task_id))
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None

    @app.patch("/api/tasks/{task_id}", response_model=TaskOut)
    def update_task(task_id: str, payload: dict[str, Any]) -> TaskOut:
        try:
            return _out(tm.update_task(conn, task_id, **payload))
        except (KeyError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.delete("/api/tasks/{task_id}")
    def delete_task(task_id: str) -> dict[str, str]:
        tm.delete_task(conn, task_id)
        return {"deleted": task_id}

    @app.post("/api/tasks/{task_id}/complete", response_model=TaskOut)
    def complete_task(task_id: str) -> TaskOut:
        try:
            return _out(tm.complete_task(conn, task_id))
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/api/mydays")
    def mydays() -> list[TaskOut]:
        return [_out(t) for t in tm.myday_tasks(conn)]

    @app.get("/api/overdue")
    def overdue() -> list[TaskOut]:
        return [_out(t) for t in tm.overdue_tasks(conn)]

    @app.get("/api/summary")
    def summary() -> ledger.LedgerSummary:
        return ledger.summary(
            conn, mild=settings.ledger.debt_mild, medium=settings.ledger.debt_medium
        )

    @app.post("/api/tasks/{task_id}/myday")
    def toggle_myday(task_id: str) -> TaskOut:
        task = tm.get_task(conn, task_id)
        return _out(tm.update_task(conn, task_id, is_myday=not task.is_myday))

    return app
