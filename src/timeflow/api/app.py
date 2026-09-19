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
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from timeflow.config import load_settings
from timeflow.core import academic as ac
from timeflow.core import facts as facts_mod
from timeflow.core import feedback as fb
from timeflow.core import focus as fc
from timeflow.core import insights
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
    note: str | None = None
    # 优先级（SR-F1.2 / T-B2）：高/中/低，默认「中」；非法值由领域层拒绝（400）
    priority: str = tm.DEFAULT_PRIORITY
    # 手动标记（SR-F1.3 / T-B3）：Flagged 视图就是它
    flagged: bool = False


class AssigneeOut(BaseModel):
    id: str
    assignee: str
    assigner: str
    status: str
    note: str | None = None


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
    # 团队分配（SR-F7.1）：任务卡片上直接可见「谁负责 / 进展到哪」，不必另开页面
    assignments: list[AssigneeOut] = []
    # 子任务进度（SR-F1.6）：父任务卡片上直接显示「2/3 步已完成」，不必点进去数
    subtask_done: int = 0
    subtask_total: int = 0
    # 备注（SR-F1.4 / T-B1）：卡片列表不渲染，只在详情面板显示/编辑（渐进聚焦）
    note: str | None = None
    # 优先级（SR-F1.2 / T-B2）：卡片上是小色标；三档 高/中/低
    priority: str = tm.DEFAULT_PRIORITY
    # 手动标记（SR-F1.3 / T-B3）：卡片上一枚小旗，Flagged 视图按它筛
    flagged: bool = False


def _out(t: tm.Task, conn: sqlite3.Connection) -> TaskOut:
    groups = tm.get_task_groups(conn, t.id)
    progress = tm.subtask_progress(conn, t.id)
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
        assignments=[
            AssigneeOut(**a)  # type: ignore[arg-type]
            for a in team.assignments_for_task(conn, t.id)
        ],
        subtask_done=progress["done"],
        subtask_total=progress["total"],
        note=t.note,
        priority=t.priority,
        flagged=t.flagged,
    )


def create_app(db_path: str | None = None) -> FastAPI:
    settings = load_settings()
    # 并发约定（见 storage/db.py）：HTTP 服务多线程共享 conn 变量，但底层**每线程一个连接**，
    # 否则一个请求的 commit() 会打断另一个请求的事务（表现为「快速点击 → 操作未完成」）。
    conn = db.thread_local(db_path or settings.database.path)

    # 第 2 步：各线只发事实，跨线联动由订阅器接线（幂等，重复建 app 不叠加）
    from timeflow.core.focus import subscribers as focus_subscribers

    focus_subscribers.register(conn)

    app = FastAPI(title="timeflow", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    web_dir = Path(__file__).resolve().parent.parent.parent / "web"

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
    def list_tasks(view: str | None = None) -> list[TaskOut]:
        """任务列表；`?view=important|planned|flagged` 走智能视图口径（SR-F1.3 / T-B3）。

        筛选口径**在领域层**（`tm.tasks_in_view`），界面不自己筛 —— 否则同一套"什么算重要"
        会在前端/后端/测试三处各写一遍。未知视图名 → 400（不静默返回全部）。
        """
        try:
            items = tm.list_tasks(conn) if view is None else tm.tasks_in_view(conn, view)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return [_out(t, conn) for t in items]

    @app.post("/api/tasks/{task_id}/flag", response_model=TaskOut)
    def toggle_flag(task_id: str) -> TaskOut:
        """手动标记开关（T-B3）：翻转 Flagged；幂等（按一次翻一次），不发事实、不动账本。"""
        try:
            return _out(tm.toggle_flag(conn, task_id), conn)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None

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
                note=payload.note,
                priority=payload.priority,
                flagged=payload.flagged,
            )
            if payload.groups:
                tm.set_task_groups(conn, t.id, payload.groups)
            return _out(t, conn)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/api/tasks/deleted")
    def deleted_tasks() -> list[TaskOut]:
        """已删任务（软删除回收站）：仅用于撤销入口展示。

        注意：本路由必须声明在 `/api/tasks/{task_id}` 之前，否则 "deleted" 会被当成 task_id。
        """
        rows = [
            t for t in tm.list_tasks(conn, active_only=False) if t.status == tm.STATUS_DELETED
        ]
        return [_out(t, conn) for t in rows]

    @app.post("/api/tasks/purge-deleted")
    def purge_deleted_tasks() -> dict[str, int]:
        """清空回收站：物理删除全部已删任务，返回条数（幂等）。

        注意：本路由必须声明在 `/api/tasks/{task_id}` 之前，否则 "purge-deleted" 会被当成 task_id。
        """
        return {"purged": tm.purge_deleted_tasks(conn)}

    @app.get("/api/tasks/{task_id}", response_model=TaskOut)
    def get_task(task_id: str) -> TaskOut:
        try:
            return _out(tm.get_task(conn, task_id), conn)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None

    @app.patch("/api/tasks/{task_id}", response_model=TaskOut)
    def update_task(task_id: str, payload: dict[str, Any]) -> TaskOut:
        """编辑任务（OP-9）：标题/截止/分组/备注/优先级/重复/My Day/父任务。

        `KeyError` = 任务不存在 → **404**（以前被 `(KeyError, ValueError)` 一起吞成 400，
        还会把 `str(KeyError)` 的引号一起显示出来 —— 实测踩到）。
        """
        fields = {k: v for k, v in payload.items() if k != "groups"}
        try:
            t = tm.update_task(conn, task_id, **fields)
            if "groups" in payload:
                tm.set_task_groups(conn, task_id, payload["groups"])
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return _out(t, conn)

    @app.delete("/api/tasks/{task_id}")
    def delete_task(task_id: str) -> dict[str, str]:
        """软删除（OP-6）：置「已删」并留 `task.deleted` 事实；可用 `/restore` 撤销。"""
        try:
            t = tm.delete_task(conn, task_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        return {"deleted": task_id, "status": t.status}

    @app.post("/api/tasks/{task_id}/restore", response_model=TaskOut)
    def restore_task(task_id: str, payload: dict[str, Any] | None = None) -> TaskOut:
        """撤销软删除（OP-6 可逆）：置回指定状态（默认「未开始」）。"""
        restore = (payload or {}).get("restore_status", tm.STATUS_TODO)
        try:
            return _out(tm.restore_task(conn, task_id, restore_status=restore), conn)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.delete("/api/tasks/{task_id}/purge")
    def purge_task(task_id: str) -> dict[str, str]:
        """彻底删除（**不可逆**，OP-6）：只允许删回收站里（已删）的任务。

        为什么要有：只软删除的话回收站会越积越多，总得有个真正的清理出口。
        活动中的任务必须先软删除（DELETE /api/tasks/{id}），这里拒绝（400），避免误用。
        """
        try:
            tm.purge_task(conn, task_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"purged": task_id}

    @app.post("/api/tasks/{task_id}/complete", response_model=TaskOut)
    def complete_task(task_id: str) -> TaskOut:
        try:
            return _out(tm.complete_task(conn, task_id), conn)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.post("/api/tasks/{task_id}/uncomplete", response_model=TaskOut)
    def uncomplete_task(task_id: str, payload: dict[str, Any] | None = None) -> TaskOut:
        """撤销完成（OP-5 可逆）：发 task.uncompleted 反向事实并恢复状态。"""
        restore = (payload or {}).get("restore_status", tm.STATUS_TODO)
        try:
            return _out(tm.uncomplete_task(conn, task_id, restore_status=restore), conn)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/api/tasks/{task_id}/subtasks")
    def list_subtasks(task_id: str) -> list[TaskOut]:
        """子任务列表（未完成在前）。任务不存在 404。"""
        try:
            tm.get_task(conn, task_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        return [_out(t, conn) for t in tm.subtasks(conn, task_id)]

    @app.post("/api/tasks/{task_id}/subtasks", response_model=TaskOut, status_code=201)
    def add_subtask(task_id: str, payload: dict[str, Any]) -> TaskOut:
        """新建子任务（OP-12）。父任务不存在 404；标题空 400。

        子任务全完成时父任务自动完成（`create_subtask` 内部联动）。
        """
        try:
            child = tm.create_subtask(
                conn, task_id, str(payload.get("title", "")), payload.get("due_date")
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return _out(child, conn)

    @app.post("/api/tasks/{task_id}/parent")
    def set_task_parent(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """改父任务（`{parent_id}`，null 表示脱离父任务）。**成环 / 自己作父 一律 400**。"""
        parent_id = payload.get("parent_id")
        try:
            t = tm.set_task_parent(conn, task_id, None if parent_id is None else str(parent_id))
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"task_id": t.id, "parent_id": t.parent_id}

    @app.get("/api/tasks/{task_id}/facts")
    def task_facts(task_id: str) -> list[dict[str, Any]]:
        """某任务的事实流水（完成/撤销），供前端展示与验收核对。"""
        try:
            tm.get_task(conn, task_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        return facts_mod.query(
            conn,
            kind="task.",
            subject_type="task",
            subject_id=task_id,
        )

    @app.get("/api/mydays")
    def mydays(include_reviews: bool = False) -> list[Any]:
        """My Day（AC-4）。`include_reviews=1` 时并入到期复习卡（SR-F6.3 / OP-28，不强制）。"""
        items: list[Any] = [_out(t, conn) for t in tm.myday_tasks(conn)]
        if include_reviews:
            items.extend(rv.myday_entries(conn))
        return items

    @app.get("/api/overdue")
    def overdue() -> list[TaskOut]:
        return [_out(t, conn) for t in tm.overdue_tasks(conn)]

    @app.get("/api/groups")
    def groups() -> list[dict[str, Any]]:
        """分组列表（含任务计数）。"""
        return tm.list_groups(conn)

    @app.post("/api/groups", status_code=201)
    def create_group(payload: dict[str, Any]) -> dict[str, Any]:
        """新建分组（OP-11）。空名 400；**重名 400**（不允许静默复用，免得用户以为建了新组）。"""
        name = str(payload.get("name", "")).strip()
        if not name:
            raise HTTPException(status_code=400, detail="分组名不能为空") from None
        existing = {str(g["name"]) for g in tm.list_groups(conn)}
        if name in existing:
            raise HTTPException(status_code=400, detail=f"分组「{name}」已存在") from None
        gid = tm.create_group(conn, name)
        return tm.get_group(conn, gid)

    @app.patch("/api/groups/{group_id}")
    def rename_group(group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """重命名分组（OP-11）。空名 400；不存在 404；改到已有名字 = 与那个分组合并（幂等）。"""
        if "name" not in payload:
            raise HTTPException(status_code=400, detail="缺少 name") from None
        try:
            return tm.rename_group(conn, group_id, str(payload["name"]))
        except KeyError:
            raise HTTPException(status_code=404, detail="分组不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.delete("/api/groups/{group_id}")
    def delete_group(group_id: str) -> dict[str, Any]:
        """删除分组（OP-11）：**只删分组与关联，任务本身保留**。不存在 404。"""
        try:
            tm.get_group(conn, group_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="分组不存在") from None
        unbound = tm.delete_group(conn, group_id)
        return {"deleted": group_id, "unbound_tasks": unbound}

    @app.get("/api/groups/{group_id}/tasks")
    def group_tasks(group_id: str) -> list[TaskOut]:
        """某分组下的任务（点分组看任务）。不存在 404。"""
        try:
            tm.get_group(conn, group_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="分组不存在") from None
        ids = set(tm.tasks_in_group(conn, group_id))
        return [_out(t, conn) for t in tm.list_tasks(conn) if t.id in ids]

    @app.post("/api/tasks/{task_id}/group")
    def toggle_task_group(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """把任务加入/移出某分组（`{name, on}`）。任务不存在 404；空名 400。"""
        try:
            tm.get_task(conn, task_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        name = str(payload.get("name", ""))
        try:
            names = tm.toggle_task_group(conn, task_id, name, bool(payload.get("on", True)))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"task_id": task_id, "groups": names}

    @app.get("/api/summary")
    def summary() -> ledger.LedgerSummary:
        return ledger.summary(
            conn, mild=settings.ledger.debt_mild, medium=settings.ledger.debt_medium
        )

    @app.get("/api/summary/weekly")
    def weekly_summary(week_of: str | None = None) -> ledger.WeekSummary:
        """周结算（OP-15）：默认本周（周一起算），`week_of` 传该周任意一天。"""
        if week_of is not None:
            try:
                from datetime import date as _date

                _date.fromisoformat(week_of)
            except ValueError:
                raise HTTPException(status_code=400, detail="非法日期") from None
        return ledger.weekly_summary(conn, week_of=week_of)

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
        try:
            sid = fc.start_session(conn, kind=kind, task_id=task_id, device_id=device_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"id": sid, "status": fc.STATUS_ACTIVE}

    @app.get("/api/focus/active")
    def focus_active() -> dict[str, object] | None:
        """当前进行中的专注（无则 null）；供前端重开页面恢复计时。"""
        return fc.active_session(conn)

    @app.post("/api/focus/{session_id}/finish")
    def focus_finish(session_id: str, payload: dict[str, Any]) -> dict[str, str]:
        duration = int(payload.get("duration_sec", 0))
        status = payload.get("status", fc.STATUS_FINISHED)
        try:
            fc.finish_session(conn, session_id, duration, status)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e)) from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
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

    @app.get("/api/habits")
    def list_habits() -> list[dict[str, object]]:
        """全部习惯 + 连续天数 + 最近 90 天打卡（列表与日历热力图数据源，SR-F4.2）。"""
        return fb.list_habits(conn)

    @app.post("/api/habits/{habit_id}/toggle")
    def toggle_habit(habit_id: str, on_date: str | None = None) -> dict[str, bool]:
        return {"done": fb.toggle_habit_log(conn, habit_id, on_date)}

    @app.patch("/api/habits/{habit_id}")
    def rename_habit(habit_id: str, payload: dict[str, Any]) -> dict[str, str]:
        """重命名习惯（空名拒绝）。"""
        try:
            fb.update_habit(conn, habit_id, str(payload.get("name", "")))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"id": habit_id}

    @app.delete("/api/habits/{habit_id}")
    def delete_habit(habit_id: str) -> dict[str, str]:
        """删除习惯及其打卡记录（幂等）。"""
        fb.delete_habit(conn, habit_id)
        return {"deleted": habit_id}

    @app.get("/api/habits/{habit_id}")
    def get_habit(habit_id: str) -> dict[str, object]:
        return {"streak": fb.habit_streak(conn, habit_id), "logs": fb.habit_logs(conn, habit_id)}

    @app.get("/api/selfcheck")
    def selfcheck() -> dict[str, object]:
        return fb.self_check(conn)

    # ---- 可视化数据底座（SR-F2.7 / SR-F4.2：后端出数据，前端出图形）----
    @app.get("/api/insights/daily")
    def insights_daily(days: int = insights.DEFAULT_TREND_DAYS) -> list[insights.DayInsight]:
        """近 N 天逐日时序（专注/手动/复习/产出/习惯/债务快照）；1≤days≤90。"""
        if not 1 <= days <= insights.MAX_TREND_DAYS:
            raise HTTPException(
                status_code=400, detail=f"days 需在 1~{insights.MAX_TREND_DAYS} 之间"
            )
        return insights.daily_insights(conn, days=days)

    @app.get("/api/insights/groups")
    def insights_groups(days: int = insights.DEFAULT_TREND_DAYS) -> list[insights.GroupInsight]:
        """近 N 天投入按任务分组（领域）分布；任务可属多分组，各组之和可能大于总投入。"""
        if not 1 <= days <= insights.MAX_TREND_DAYS:
            raise HTTPException(
                status_code=400, detail=f"days 需在 1~{insights.MAX_TREND_DAYS} 之间"
            )
        return insights.group_insights(conn, days=days)

    @app.get("/api/insights/heatmap")
    def insights_heatmap(days: int = insights.DEFAULT_HEATMAP_DAYS) -> list[insights.HeatmapCell]:
        """近 N 天逐日多指标（时间热力图：投入/手动/复习/产出/债务快照）；1≤days≤400。"""
        if not 1 <= days <= insights.MAX_HEATMAP_DAYS:
            raise HTTPException(
                status_code=400, detail=f"days 需在 1~{insights.MAX_HEATMAP_DAYS} 之间"
            )
        return insights.heatmap(conn, days=days)

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

    @app.get("/api/assessments/upcoming")
    def upcoming_assessments(days: int = 14) -> list[dict[str, object]]:
        """临期/逾期考核项（OP-25）：只取未录成绩的；带 `days_until`（负=逾期，None=无截止日）。"""
        if not 0 <= days <= 365:
            raise HTTPException(status_code=400, detail="days 需在 0~365 之间")
        return ac.upcoming_assessments(conn, days=days)

    @app.delete("/api/assessments/{assessment_id}")
    def delete_assessment(assessment_id: str) -> dict[str, str]:
        ac.delete_assessment(conn, assessment_id)
        return {"deleted": assessment_id}

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
        """GPA（按 scale，缺省用配置）+ 学分 + **加权平均成绩**（Σ学分×成绩 / Σ学分，百分制）。

        两个口径并存：GPA 是绩点加权，加权平均成绩是原始分加权 —— 都在这里一次返回，
        前端切 4.0/5.0 制时只重取这一个接口。
        """
        gpa_scale = scale or settings.academic.gpa_scale
        if gpa_scale not in ac.VALID_GPA_SCALES:
            raise HTTPException(status_code=400, detail=f"非法 GPA 制式: {gpa_scale}")
        g, credits = ac.gpa(conn, gpa_scale)
        avg, avg_credits = ac.weighted_average(conn)
        return {
            "gpa": g,
            "credits": credits,
            "scale": gpa_scale,
            "weighted_average": avg,
            "weighted_credits": avg_credits,
        }

    @app.get("/api/grades")
    def list_grades() -> list[dict[str, object]]:
        """成绩明细（SR-F5.1 / N32 的学业可视化数据源：卡片 + 多维呈现）。"""
        return ac.all_grade_rows(conn)

    @app.delete("/api/grades/{grade_id}")
    def delete_grade(grade_id: str) -> dict[str, str]:
        """删除一条成绩（OP-23 可逆）；GPA 随之重算。"""
        ac.delete_grade(conn, grade_id)
        return {"deleted": grade_id}

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

    @app.post("/api/review/{item_id}/undo")
    def undo_review(item_id: str, payload: dict[str, Any] | None = None) -> dict[str, object]:
        """撤销当日最近一次复习反馈（OP-27 可逆）：回退 FSRS 字段 + 追加 `review.undone` 事实。"""
        on_date = (payload or {}).get("date")
        try:
            return rv.undo_review(conn, item_id, on_date=on_date)
        except KeyError:
            raise HTTPException(status_code=404, detail="复习卡不存在") from None

    @app.get("/api/review/{item_id}/facts")
    def review_facts(item_id: str) -> list[dict[str, Any]]:
        """某复习卡的事实流水（复习完成），供前端展示与验收核对。"""
        exists = conn.execute(
            "SELECT 1 FROM review_items WHERE id = ?", (item_id,)
        ).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="复习卡不存在")
        return facts_mod.query(
            conn, kind="review.completed", subject_type="review_item", subject_id=item_id
        )

    # ---- SR-F7 团队/AI 协作 ----
    @app.post("/api/team/assign")
    def team_assign(payload: dict[str, Any]) -> dict[str, str]:
        try:
            return {"id": team.assign_task(
                conn,
                task_id=payload["task_id"],
                assignee=payload["assignee"],
                assigner=payload.get("assigner", "me"),
                note=payload.get("note"),
            )}
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.patch("/api/team/assign/{assignment_id}")
    def team_status(assignment_id: str, payload: dict[str, Any]) -> dict[str, str]:
        try:
            team.update_assignment_status(conn, assignment_id, payload["status"])
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
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

    @app.delete("/api/memos/{memo_id}")
    def delete_memo(memo_id: str) -> dict[str, str]:
        """删除备忘录（幂等）；关联任务不自动删除。"""
        memo.delete_memo(conn, memo_id)
        return {"deleted": memo_id}

    @app.post("/api/memos/{memo_id}/to-task")
    def memo_to_task(memo_id: str, payload: dict[str, Any] | None = None) -> dict[str, str]:
        """把备忘录转成任务（SR-F8 R2）：备忘录保留并记下 task_id。"""
        body = payload or {}
        try:
            tid = memo.memo_to_task(
                conn,
                memo_id,
                due_date=body.get("due_date"),
                is_myday=bool(body.get("is_myday", True)),
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="备忘录不存在") from None
        return {"task_id": tid}

    # B 系统产出/投入流水（SR-F8.4 产出评价器接口，第一版手动）
    @app.post("/api/ledger/output")
    def ledger_output(payload: dict[str, Any]) -> dict[str, str]:
        try:
            return {"id": memo.add_output_entry(
                conn, value=payload["value"], kind=payload.get("kind", "asset"),
                note=payload.get("note"), ref_handle=payload.get("ref_handle"),
            )}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/api/ledger/outputs")
    def ledger_outputs(date_str: str | None = None) -> list[dict[str, object]]:
        """某日产出流水（产出轴，含是否已撤销）；默认今天。"""
        return memo.list_outputs(conn, day=date_str)

    @app.delete("/api/ledger/output/{entry_id}")
    def ledger_output_retract(entry_id: str) -> dict[str, object]:
        """撤销一条产出（追加 `output.retracted` 反向事实，不删历史）。"""
        try:
            changed = memo.retract_output_entry(conn, entry_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="产出记录不存在") from None
        return {"entry_id": entry_id, "retracted": changed}

    @app.post("/api/ledger/invest")
    def ledger_invest(payload: dict[str, Any]) -> dict[str, str]:
        """手动投入（OP-13）。**单位：秒**（与专注事实同口径）。"""
        try:
            return {"id": memo.add_invest_entry(
                conn, value=payload["value"], kind=payload.get("kind", "focus"),
                note=payload.get("note"),
            )}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/api/ledger/invests")
    def ledger_invests(date_str: str | None = None) -> list[dict[str, object]]:
        """某日手动投入流水（含是否已撤销）；默认今天。秒为存储口径，另附 minutes。"""
        return memo.list_invests(conn, day=date_str)

    @app.delete("/api/ledger/invest/{entry_id}")
    def ledger_invest_retract(entry_id: str) -> dict[str, object]:
        """撤销一条手动投入（追加 `invest.retracted` 反向事实，不删历史）。"""
        try:
            changed = memo.retract_invest_entry(conn, entry_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="投入记录不存在") from None
        return {"entry_id": entry_id, "retracted": changed}

    # ---- SR-F9 跨端同步 (LWW + 去重) ----
    @app.post("/api/sync/tasks")
    def sync_tasks(payload: dict[str, Any]) -> dict[str, Any]:
        records = payload.get("records", [])
        results = [sync_mod.merge_task(conn, r) for r in records]
        return {"merged": results}

    @app.get("/api/sync/status")
    def sync_status() -> dict[str, object]:
        """同步状态（OP-40/OP-41）：只报告事实，跨端传输未实现时 `enabled=false`（不谎报）。"""
        return sync_mod.status(conn)

    @app.get("/api/sync/logs")
    def sync_logs() -> list[dict[str, object]]:
        rows = conn.execute("SELECT * FROM sync_logs ORDER BY created_at DESC LIMIT 50").fetchall()
        return [
            {"id": r["id"], "entity": r["entity"], "entity_id": r["entity_id"],
             "local_ts": r["local_ts"], "remote_ts": r["remote_ts"]}
            for r in rows
        ]

    # 静态前端入口：/ （index.html）、/manifest.json、/sw.js、图标等
    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")

    return app
