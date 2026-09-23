"""FastAPI REST（SR-F7.3 AI 接口 + 供前端）。本地优先。

create_app(db_path) 封装为工厂；路由对任务做 CRUD / My Day / 逾期 / 多分组 / 轻债务摘要，
并预留后续域（专注/习惯/学业/复习/备忘录）的接口落点。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

if TYPE_CHECKING:
    import sqlite3

import time
from dataclasses import asdict
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from timeflow import logs, vocab
from timeflow.config import load_settings
from timeflow.core import academic as ac
from timeflow.core import ai as ai_mod
from timeflow.core import attach as attach_mod
from timeflow.core import behavior, insights, syncpack, vault
from timeflow.core import facts as facts_mod
from timeflow.core import feedback as fb
from timeflow.core import focus as fc
from timeflow.core import lan as lan_mod
from timeflow.core import memo as memo
from timeflow.core import notify as notify_mod
from timeflow.core import remind as remind_mod
from timeflow.core import review as rv
from timeflow.core import sync as sync_mod
from timeflow.core import tasks as tm
from timeflow.core import team as team
from timeflow.core.focus import guard as fg
from timeflow.core.ledger import ledger
from timeflow.storage import backup as backup_mod
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
    # 附件（T-B4）：建任务时一起带上（元素 `{target, title}`）
    attach: list[dict[str, Any]] = []
    # 提醒（T-B5）：本地时间「2026-09-20T08:30」；空=不提醒
    remind_at: str | None = None
    # 任务类型 + 所属课程（SR-F5.4 / T-C12）：普通/作业/考试/论文/小测；只有非「普通」才允许挂课程
    task_type: str = tm.DEFAULT_TASK_TYPE
    course_id: str | None = None


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
    # 分组**路径**列表（`高数 / 作业`）：重名放开后名字可能撞车，路径才是能认的那一个（T-F10）
    groups: list[str] = []
    # 分组的 **id**：勾选/取消按 id 走（名字不再当标识）
    group_ids: list[str] = []
    # 团队分配（SR-F7.1）：任务卡片上直接可见「谁负责 / 进展到哪」，不必另开页面
    assignments: list[AssigneeOut] = []
    # 子任务进度（SR-F1.6）：父任务卡片上直接显示「2/3 步已完成」，不必点进去数
    subtask_done: int = 0
    subtask_total: int = 0
    # 「当前该做哪一步」（N10 / F 批 · T-F4）：第一个未完成子任务的标题与截止日（没有 → None）。
    # 用户原话：「子步骤完成前，它变成主任务的一个显现（任务卡里显示一个子步骤）」。
    current_step: str | None = None
    current_step_due: str | None = None
    # 备注（SR-F1.4 / T-B1）：卡片列表不渲染，只在详情面板显示/编辑（渐进聚焦）
    note: str | None = None
    # 优先级（SR-F1.2 / T-B2）：卡片上是小色标；三档 高/中/低
    priority: str = tm.DEFAULT_PRIORITY
    # 手动标记（SR-F1.3 / T-B3）：卡片上一枚小旗，Flagged 视图按它筛
    flagged: bool = False
    # 附件 / 要求链接（SR-F1.4 / T-B4）：`{target, title}` 列表；打开规则见 core/attach.py
    attach: list[dict[str, Any]] = []
    # 提醒（SR-F1.4 / T-B5）：本地时间；界面按 已过/今天/临期 标出（通知通道待选型）
    remind_at: str | None = None
    # 提醒的界面口径（`over`/`today`/`soon`/`later`；None=没设或已完成）——
    # **由领域层算**（`tm.reminder_state`），前端不自己拿当前时间去比（免得口径分叉）
    reminder_state: str | None = None
    # 派生逾期天数（F 批 · T-F7）：**0 = 没逾期**。字段里的 `status` 是"存下来的状态"
    # （新建时截止日已过才写「逾期」），这里是"按今天算出来的逾期" ——
    # 详情面板两个都显示，就不会再出现"列在逾期栏里、面板却写未开始"的自相矛盾。
    overdue_days: int = 0
    # 任务类型 + 所属课程（SR-F5.4 / T-C12）：`course_name` 由后端查名字给出，
    # 列表卡片因此不必先拉一遍课程表；课程已删 → None（界面显示「课程已删」，任务不受影响）
    task_type: str = tm.DEFAULT_TASK_TYPE
    course_id: str | None = None
    course_name: str | None = None
    # 「进行中」的显式顺序（F 批 · T-F1）：只在「进行中」时有值；界面按它排上/下
    doing_rank: int | None = None
    # **谁建的**（G 批 · T-G6）：`me` / `ai`。界面据此标「AI 建的」；它也是 AI 边界的判据
    # （AI 只能勾 `ai` 的）。由创建路径写死，**接口不接受手改**（不在 `TaskIn`/PATCH 白名单里）。
    created_by: str = tm.CREATOR_ME
    # 嵌套层数（N10 / F 批 · T-F5）：1 = 大任务（顶层）、2 = 子任务、3 = 子步骤。
    # 界面据此显示「子任务 / 子步骤」徽标与缩进；上限 3 层由领域层拦。
    depth: int = 1
    # 下面三项**只有档案接口（`GET /api/tasks/archived`）会填**（F 批 · T-F2）：
    # 档案视图是一屏列表，得一次把"自动/手动归档 + 完成日 + 试了几回"都算好（各一次聚合查询），
    # 不能给每张卡各查一遍（那是 N+1）；别的接口保持默认值，页面也不读它们。
    auto_archived: bool = False  # True = 完成满 N 天自动收入；False = 手动归档/不在档案里
    completed_on: str | None = None  # 完成日（来自 `task.completed` 事实；没有就退回 updated_at）
    attempt_count: int = 0  # 「试了几回」（T-F3 的事实）


# 会**在本机打开文件/程序**或改服务端设置的接口，只接受本机页面调用。
# 为什么需要：服务开着 CORS 且监听回环，若不看来源，随便一个网页都能让本机去开东西
# （localhost 服务被跨站调用的经典风险）。带 Origin 的请求必须是 127.0.0.1/localhost/::1。
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def require_local_origin(request: Request) -> None:
    """只接受本机页面调用（**或已配对的同一 WiFi 设备** —— 跨端场景 ②）。

    为什么需要这道守卫：服务开着 CORS，若不看来源，随便一个网页都能让本机去开文件 / 改设置
    （localhost 服务被跨站调用的经典风险。跨站页面**发不出**配对码，所以配对过的来源是可信的）。
    为什么"配对过就当作本机页面"：局域网开着时，手机就是"你在用这个工具"的另一只手；
    该问的是"你是不是本人"，而配对码已经回答了（见 `core/lan.py`）。
    """
    origin = request.headers.get("origin")
    if not origin:
        return  # 无 Origin：本机脚本 / curl / 同源 GET —— 放行
    host = urlsplit(origin).hostname
    if host in _LOOPBACK_HOSTS:
        return
    if getattr(request.state, "paired", False):
        return  # 已配对（配对码对过）：当作本机页面
    if getattr(request.state, "lan_open", False):
        raise HTTPException(
            status_code=403, detail="这个接口只允许本机页面调用（这台设备还没和电脑配对）"
        )
    raise HTTPException(status_code=403, detail="这个接口只允许本机页面调用")


def _out(
    t: tm.Task,
    conn: sqlite3.Connection,
    *,
    auto_archived: bool = False,
    completed_on: str | None = None,
    attempt_count: int = 0,
    depth: int | None = None,
) -> TaskOut:
    """任务 → 接口对象。三个关键字参数只有档案接口会传（见 `TaskOut` 那段注释）。

    `depth`（T-F5）：不传就现算（**只在真有父任务时才查** —— 绝大多数任务是顶层的，
    不该为了一个显示字段给每张卡都走一遍父链）；树的接口已经知道层数，直接传进来。
    """
    groups = tm.task_group_paths(conn, t.id)
    group_ids = tm.task_group_ids(conn, t.id)
    progress, current = tm.subtask_view(conn, t.id)
    if depth is None:
        depth = tm.task_depth(conn, t.id) if t.parent_id else 1
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
        group_ids=group_ids,
        assignments=[
            AssigneeOut(**a)  # type: ignore[arg-type]
            for a in team.assignments_for_task(conn, t.id)
        ],
        subtask_done=progress["done"],
        subtask_total=progress["total"],
        # 「当前该做哪一步」（N10 / T-F4）：给任务卡用 —— 大任务卡上看一步，不是把所有步骤堆出来
        current_step=current.title if current else None,
        current_step_due=current.due_date if current else None,
        note=t.note,
        priority=t.priority,
        flagged=t.flagged,
        attach=[dict(i) for i in t.attach],
        remind_at=t.remind_at,
        reminder_state=tm.reminder_state(t),
        overdue_days=tm.overdue_days(t),
        task_type=t.task_type,
        course_id=t.course_id,
        course_name=tm.course_name(conn, t.course_id),
        doing_rank=t.doing_rank,
        created_by=t.created_by,
        auto_archived=auto_archived,
        completed_on=completed_on,
        attempt_count=attempt_count,
        depth=depth,
    )


def create_app(
    db_path: str | None = None, *, allow_lan: bool | None = None, port: int = 8520
) -> FastAPI:
    """建应用。

    `allow_lan`（跨端场景 ②）：**这台服务是否对局域网开着**。
    默认取 `[net] allow_lan`（默认 false）。由**启动方**
    （`tools/serve.py` / `app/main.py`）传进来 —— 因为它和"绑哪个地址"必须是**同一个决定**：
    只有真的绑了 `0.0.0.0`，配对门才有意义；反过来，门开着但只绑回环，也谈不上风险。
    `port` 只用于界面上拼"手机该敲哪个地址"。
    """
    settings = load_settings()
    lan_open = settings.net.allow_lan if allow_lan is None else bool(allow_lan)
    # 解析后的库路径：计划任务的 `--db` 要用**绝对路径**（任务的工作目录不是项目根）
    db_path = db_path or settings.database.path
    # 并发约定（见 storage/db.py）：HTTP 服务多线程共享 conn 变量，但底层**每线程一个连接**，
    # 否则一个请求的 commit() 会打断另一个请求的事务（表现为「快速点击 → 操作未完成」）。
    conn = db.thread_local(db_path)

    def _guard_defaults() -> fg.GuardConfig:
        """专注白名单/勿扰的**装机默认值**（来自 config.toml 的 [focus]）。

        界面没改过就用它；改过则以 `app_settings` 里的为准（逐项独立，见 guard.get_settings）。
        """
        return fg.GuardConfig(
            block_by_default=settings.focus.block_by_default,
            dnd_windows=list(settings.focus.do_not_disturb),
        )

    # 第 2 步：各线只发事实，跨线联动由订阅器接线（幂等，重复建 app 不叠加）
    from timeflow.core.focus import subscribers as focus_subscribers

    focus_subscribers.register(conn)

    # 结构化日志 + 调试开关（SR-NF13）：一行一条 JSON；**只记事件与关键字段，不记正文**
    log_file = logs.setup_logging()
    logs.log_event("app_start", db_path=str(db_path), schema_version=db.SCHEMA_VERSION)

    app = FastAPI(title="timeflow", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def lan_gate(request: Request, call_next: Any) -> Any:
        """局域网（②）的门：**开着时**非本机请求必须带配对码；关着时这段是空操作。

        判定本身是纯函数（`core/lan.gate`），所以能用真值表一条条测（见
        `tests/test_lan_pairing_line.py`）。这里只负责：取客户端地址 → 问门 → 要么放行
        （并把 `paired` 记进 `request.state`，给 `require_local_origin` 用）要么回原文。
        """
        request.state.lan_open = lan_open
        request.state.paired = False
        if lan_open:
            host = request.client.host if request.client else None
            decision = lan_mod.gate(
                conn, host, request.url.path, lan_mod.read_code_from(request)
            )
            if not decision["ok"]:
                return JSONResponse(
                    {"detail": str(decision.get("detail") or "")},
                    status_code=int(decision["status"]),
                )
            request.state.paired = bool(decision.get("paired"))
        return await call_next(request)

    @app.middleware("http")
    async def log_key_paths(request: Request, call_next: Any) -> Any:
        """关键路径日志：**改动类请求**（POST/PATCH/PUT/DELETE）记一条（方法/路径/状态/耗时）。

        为什么不记 GET：读接口量最大、信息最少，记了只会把日志淹掉；
        为什么不记请求正文：那是用户写的内容（隐私最小化，见 `timeflow/logs.py` 的约定）。
        """
        started = time.perf_counter()
        response = await call_next(request)
        if request.method != "GET":
            logs.log_event(
                "api_write",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                ms=round((time.perf_counter() - started) * 1000, 1),
            )
        return response

    web_dir = Path(__file__).resolve().parent.parent.parent / "web"

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        """健康检查（SR-NF13）：只报**能自证的事实** —— 库通不通、schema 版本、几张表的条数。

        刻意不报"一切正常"这种空话：`database_ok=false` 时把错误原因带出来。
        """
        info: dict[str, Any] = {"status": "ok", "schema_version": None, "database_ok": True}
        try:
            row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            info["schema_version"] = None if row is None else int(row["version"])
            info["tasks"] = int(conn.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"])
            info["facts"] = int(conn.execute("SELECT COUNT(*) AS n FROM facts").fetchone()["n"])
        except Exception as exc:  # noqa: BLE001 —— 健康检查必须"永远能回答"，不能自己 500
            info["status"] = "degraded"
            info["database_ok"] = False
            info["error"] = str(exc)[-200:]
        info["debug"] = logs.debug_enabled()
        info["log_file"] = None if log_file is None else str(log_file)
        return info

    @app.get("/api/config")
    def config() -> dict[str, Any]:
        return {
            "accent_color": settings.app.accent_color,
            "theme": settings.app.theme,
            "gpa_scale": settings.academic.gpa_scale,
            # 番茄钟时长（T-G23）：界面拿它做**倒计时**与到点提示。
            # 以前这里没暴露，界面只能 `cfg.pomodoro_minutes||25` —— 于是 config.toml 里改过的
            # 值一直不生效（按钮上永远写 25 分），属于"配置项是死的"。
            "pomodoro_minutes": settings.focus.pomodoro_minutes,
        }

    # ---- 局域网访问 + 配对码（SR-NF17 / G 批 · T-G10b = 跨端场景 ②）----
    # 三条接口，口径都是一处：`core/lan.py`。
    def _lan_status(request: Request) -> dict[str, Any]:
        host = request.client.host if request.client else None
        return lan_mod.status(
            conn,
            lan_open=lan_open,
            config_allow_lan=settings.net.allow_lan,
            port=port,
            loopback=lan_mod.is_loopback(host),
        )

    @app.get("/api/settings/lan")
    def get_lan(request: Request) -> dict[str, Any]:
        """局域网现状。★ **配对码只在回环请求里出现** —— 这是这道门的底线。

        局域网设备能读数据，但读不到"钥匙"本身（否则随便谁配一次就把它传出去了）。
        非本机请求时 `code` 是空串、`code_visible=false`，界面据此显示
        「配对码只能在那台电脑上看」。
        """
        return _lan_status(request)

    @app.put("/api/settings/lan")
    def put_lan(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        """改配对码（**只有那台电脑能改**）：传 `pairing_code` = 换成它；传空 = 换一个新的。"""
        require_local_origin(request)
        host = request.client.host if request.client else None
        if not lan_mod.is_loopback(host):
            raise HTTPException(status_code=403, detail="配对码只能在那台电脑上改（这是故意的）")
        raw = payload.get("pairing_code")
        try:
            lan_mod.rotate(conn, None if raw in (None, "") else str(raw))
        except ValueError as exc:  # 非法值 → 400 带原话，不静默回落
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _lan_status(request)

    @app.post("/api/lan/selfcheck")
    def lan_selfcheck() -> dict[str, Any]:
        """本机网络自检（T-G10c）：把"手机为什么连不上"里**能在电脑上查的那一半**查出来。

        查：这台服务开没开局域网、有哪些局域网地址、**从这台机器自己**能不能经那些地址访问自己
        （能 = 地址在、绑定对、防火墙至少没拦本机自连）。
        **查不到**：校园网 / 公共 WiFi 的**客户端隔离**（那是"手机 → 电脑"的事，电脑上试不出来）——
        所以这里不假装能判，直接把排查顺序（热点优先）写进 `hint`。
        """
        return lan_mod.selfcheck(port, lan_open=lan_open)

    @app.post("/api/lan/pair")
    def pair(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        """配对：拿配对码换"能读数据"。

        这个接口**没有** origin 守卫（它就是给"还没配对的设备"用的），
        但有失败节流（连续错太多次锁一会儿）—— 见 `core/lan.py`。
        """
        if not lan_open:
            raise HTTPException(
                status_code=409,
                detail="这台服务没有开局域网访问（本机自己不需要配对）—— "
                       "在电脑上用 `python tools/serve.py --lan` 起，或把 config.toml 的 "
                       "[net] allow_lan 改成 true。",
            )
        host = request.client.host if request.client else None
        got = payload.get("code")
        out = lan_mod.check_pair(conn, host, None if got is None else str(got))
        if not out["ok"]:
            raise HTTPException(status_code=int(out["status"]), detail=str(out["detail"]))
        return {"ok": True, "detail": out["detail"], "header": lan_mod.HEADER}

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

    # ---- 附件 / 要求链接（SR-F1.4 / T-B4）：增删在任务上，打开规则走 /api/attach/* ----
    @app.post("/api/tasks/{task_id}/attachments", response_model=TaskOut)
    def add_attachment(task_id: str, payload: dict[str, Any]) -> TaskOut:
        """加一条附件/要求链接（网址或本地路径）；同一 target 幂等不加。"""
        try:
            task = tm.add_attachment(
                conn, task_id, str(payload.get("target", "")), payload.get("title")
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return _out(task, conn)

    @app.delete("/api/tasks/{task_id}/attachments/{index}", response_model=TaskOut)
    def remove_attachment(task_id: str, index: int) -> TaskOut:
        """按下标删一条；越界 400、任务不存在 404。"""
        try:
            task = tm.remove_attachment(conn, task_id, index)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return _out(task, conn)

    @app.post("/api/attach/open")
    def open_attach(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        """打开一条附件（T-B4 / SR-F5.3 的"跳转要求"）。

        三层规则在 `core/attach.py`（**打开方式与白名单取服务端设置**，不接受请求参数指定，
        否则任何页面都能要求"直接打开"）；这个接口会在本机打开文件夹/程序，故加来源守卫。
        打不开时返回 `action="copy"` + 路径 —— 界面必须复制路径并出声（不许静默失败）。
        `dry_run=True` 只解析不执行（测试 / 先看会发生什么）。
        """
        require_local_origin(request)
        settings_now = attach_mod.get_settings(conn)
        try:
            return attach_mod.open_target(
                payload.get("target", ""),
                settings_now["mode"],
                settings_now["whitelist"],
                dry_run=bool(payload.get("dry_run")),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/api/settings/attach")
    def get_attach_settings() -> dict[str, Any]:
        """附件打开方式（当前值 + 可选值 + 规则说明；规则只有一份，前端不复述）。"""
        return {**attach_mod.get_settings(conn), **attach_mod.describe_rules()}

    # ---- 「完成 N 天后进档案」的 N（N11 / F 批 · T-F2）----
    # 口径（用户 2026-09-21）：「过几天再归档」—— "几天"是习惯问题，所以可配置；
    # 默认值来自 config.toml（`[tasks] archive_after_days = 3`），本机改过的存 app_settings 并优先
    # （与专注白名单/勿扰同一套机制，不另造一套配置）。
    @app.get("/api/settings/archive")
    def get_archive_settings() -> dict[str, Any]:
        """`{after_days, default_after_days, max_after_days, note}`（只读口径说明也在里面）。"""
        return tm.archive_settings(conn, settings.tasks.archive_after_days)

    @app.put("/api/settings/archive")
    def put_archive_settings(payload: dict[str, Any]) -> dict[str, Any]:
        """改 N（0~365 的整数，0 = 完成当天就收走）。非法值 400，**不静默落默认值**。"""
        try:
            tm.set_archive_after_days(
                conn, payload.get("after_days"), settings.tasks.archive_after_days
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return tm.archive_settings(conn, settings.tasks.archive_after_days)

    # ---- 口径与一键回退（SR-NF8 / D 批 · T-D11）----
    # 口径（2026-09-21 用户选 B 案）：机制前向 + 拿 T-F8 的计债口径当样板对比。
    # 三条路由：读整表（含影子差异）/ 切一条口径 / 回默认位（一键回退）。
    @app.get("/api/settings/behavior")
    def get_behavior() -> dict[str, Any]:
        """每条口径的当前做法 + 默认位 + **影子差异**（纯读，不改任何东西）。"""
        return behavior.report(conn)

    @app.put("/api/settings/behavior")
    def put_behavior(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        """切换一条口径。非法 key / 非法做法 → 400（**不静默落默认值**）。只接受本机页面。"""
        require_local_origin(request)
        try:
            behavior.set_variant(conn, payload.get("key"), payload.get("variant"))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return behavior.report(conn)

    @app.post("/api/settings/behavior/reset")
    def post_behavior_reset(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        """一键回退：删掉本机那条设置，回到**默认位**（不是把当前值再写一遍）。"""
        require_local_origin(request)
        try:
            behavior.reset_variant(conn, payload.get("key"))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return behavior.report(conn)

    # ---- 可配置词表（SR-NF7 / G 批 · T-G1）：复习形式 / 热力图维度 ----
    # 口径（2026-09-21 用户定，见 `复盘/口径定案-待定清单.md` §6）：**能不改核心就加的只有词表**；
    # 加字段（要 schema 迁移）与加功能（要领域函数+路由+界面）如实标注做不到。
    # 三条路由**通用**：加一张新词表 = 在 `timeflow/vocab.py` 加一条声明，路由与界面都不用改。
    def _vocab_defaults() -> dict[str, dict[str, str]]:
        """config.toml 里的文件级默认（本机在设置页改过的存 `app_settings` 并优先）。"""
        return {
            vocab.REVIEW_FORMS.key: dict(settings.review.forms),
            vocab.HEATMAP_DIMENSIONS.key: dict(settings.insights.heatmap_dimensions),
        }

    @app.get("/api/settings/vocab")
    def get_vocab() -> dict[str, Any]:
        """所有词表 + 各自的默认值与说明（界面通用渲染，前端不写死任何中文词表）。"""
        return vocab.report(conn, _vocab_defaults())

    @app.put("/api/settings/vocab")
    def put_vocab(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        """改一张词表（整张替换）。非法 id/标签/条数 → 400 带后端原话（**不静默回落**）。"""
        require_local_origin(request)
        try:
            table = vocab.by_key(payload.get("key"))
            vocab.set_items(conn, table, payload.get("items"), _vocab_defaults().get(table.key))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return vocab.report(conn, _vocab_defaults())

    @app.post("/api/settings/vocab/reset")
    def post_vocab_reset(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        """回到配置/内置默认（删掉本机那条设置，而不是把当前值再写一遍）。"""
        require_local_origin(request)
        try:
            vocab.reset(conn, vocab.by_key(payload.get("key")))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return vocab.report(conn, _vocab_defaults())

    @app.get("/api/insights/heatmap-dimensions")
    def heatmap_dimensions() -> dict[str, Any]:
        """热力图现在有哪些维度可看（顺序 = 界面按钮顺序）+ 单位/种类（G 批 · T-G1）。"""
        return insights.heatmap_dimensions(conn, settings.insights.heatmap_dimensions)

    # ---- 沉淀型 markdown（SR-F8 / G 批 · T-G4）----
    # 口径（2026-09-21 用户定，见 `复盘/口径定案-待定清单.md` §7）：**数据库是权威、md 是产物**；
    # 每天一个 md；目录可配置；**不写进 Obsidian 笔记目录**（红线 SR-F8.2）。
    # 自动导出是"产物"：失败只记错（`export.last_error`），**不挡完成/记备忘这些主流程**。
    @app.get("/api/settings/export")
    def get_export_settings() -> dict[str, Any]:
        """导出目录现状 + 今天那份在不在 + 上次写的时间/错误（说明由后端给，界面不复述）。"""
        return vault.describe(
            conn,
            settings.export.dir,
            default_vault=settings.export.vault,
            default_vault_dir=settings.export.vault_dir,
        )

    @app.put("/api/settings/export")
    def put_export_settings(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        """改导出目录（**当场确保建得出来**，建不了 400 带原话，并把配置回滚）。

        导出目录落在 Obsidian 的 Vault 里 → 400 拒绝（红线 SR-F8.2 机器化）。
        """
        require_local_origin(request)
        try:
            return vault.set_dir(
                conn,
                payload.get("dir"),
                settings.export.dir,
                default_vault=settings.export.vault,
                default_vault_dir=settings.export.vault_dir,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.post("/api/export/day")
    def export_day(payload: dict[str, Any]) -> dict[str, Any]:
        """手动导出某一天（不传 `day` = 今天）。失败 400 带原话（手动动作要当场看到问题）。"""
        try:
            result = vault.export_day(
                conn,
                payload.get("day"),
                settings.export.dir,
                default_vault_dir=settings.export.vault_dir,
            )
        except (OSError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e) or e.__class__.__name__) from e
        return {"ok": True, **asdict(result)}

    # ---- Obsidian 跳转（SR-F8.2 / G 批 · T-G5）----
    # 口径（2026-09-21 用户定，见 `复盘/口径定案-待定清单.md` §7）：引用句柄能**一键调出 Obsidian**
    # （`obsidian://open?vault=…&file=…`），**只读跳转** —— 软件不往 Vault 里写任何东西。
    # 名字是跳转的前提；根目录只用来把**绝对路径**句柄换算成 Vault 内的位置
    # （顺带才校验得了"这个句柄在不在库里"）。
    def _ref_url(item: dict[str, Any]) -> dict[str, Any]:
        """给一条带 `ref_handle` 的记录补上跳转信息（`ref_url` + 不能跳时的 `ref_reason`）。"""
        handle = item.get("ref_handle")
        if handle:
            info = vault.link(
                conn,
                handle,
                default_vault=settings.export.vault,
                default_vault_dir=settings.export.vault_dir,
            )
            item["ref_url"] = info["url"]
            item["ref_reason"] = info["reason"]
        return item

    def _with_ref_url(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [_ref_url(item) for item in items]

    @app.put("/api/settings/vault")
    def put_vault_settings(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        """改 Obsidian 设置（Vault 名字 + 可选根目录）。非法/不存在/包住导出目录 → 400 带原话。"""
        require_local_origin(request)
        try:
            return vault.set_vault(
                conn,
                payload.get("vault"),
                payload.get("vault_dir"),
                default_vault=settings.export.vault,
                default_vault_dir=settings.export.vault_dir,
                default_dir=settings.export.dir,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.post("/api/vault/open")
    def open_in_vault(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        """跳进 Obsidian 打开一个引用句柄（**只读**：不写 Vault，也不在里面建东西）。

        调不起 Obsidian 时 `ok=false` 且 `reason` 给原话，界面退回"复制链接 + 提示"（不许静默）。
        """
        require_local_origin(request)
        return vault.open_handle(
            conn,
            payload.get("handle"),
            default_vault=settings.export.vault,
            default_vault_dir=settings.export.vault_dir,
        )

    # ---- AI 接口（SR-F7.3 + OP-34 / N23 + N46；G 批 · T-G6）----
    # 口径（2026-09-21 用户定，见 `复盘/口径定案-待定清单.md` §2 乙案）：**只读 + 新增 +
    # 勾自己建的**；判据是"动的是不是你亲手写的东西"；**默认关**。规则与措辞都在
    # `core/ai.py` 一处（这里只做 HTTP 落地：404/400/403 的翻译与来源校验）。
    # 注意：**整组 `/api/ai/*` 都要求本机来源** —— 网页读不到也写不了，只有本机程序能调。
    @app.get("/api/settings/ai")
    def get_ai_settings() -> dict[str, Any]:
        """AI 接口现状 + 边界自述（说明由后端给，界面不复述规则）。只读。"""
        return ai_mod.describe(conn, settings.ai.enabled)

    @app.put("/api/settings/ai")
    def put_ai_settings(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        """打开/关闭 AI 接口（**默认关**；非法值 400 带原话）。只接受本机页面调用。"""
        require_local_origin(request)
        try:
            return ai_mod.set_enabled(conn, payload.get("enabled"), settings.ai.enabled)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    def _ai_guard(request: Request) -> None:
        """AI 组统一的入口闸：**本机来源** + **开关开着**，不过就 403 带原话。"""
        require_local_origin(request)
        try:
            ai_mod.require_enabled(conn, settings.ai.enabled)
        except ValueError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e

    @app.get("/api/ai/ping")
    def ai_ping(request: Request) -> dict[str, Any]:
        """自证：接口开着、边界是什么、能给的动作有哪些（**不读你的数据**）。"""
        _ai_guard(request)
        body = ai_mod.describe(conn, settings.ai.enabled)
        body["ok"] = True
        body["note"] = "这是边界自述，不含你的任务内容。"
        return body

    @app.get("/api/ai/tasks")
    def ai_tasks(
        request: Request,
        view: str | None = None,
        assignee: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """读任务列表（只读）。`view` 与人侧三视图同口径（important/planned/flagged）。

        `assignee` 过滤「分配给我/某人」的任务（N46 的"接收任务"）；默认只给活动任务。
        """
        _ai_guard(request)
        try:
            tasks = tm.tasks_in_view(conn, view) if view else tm.list_tasks(conn)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        if assignee:
            tasks = [
                t
                for t in tasks
                if any(
                    str(a["assignee"]) == assignee
                    for a in team.assignments_for_task(conn, t.id)
                )
            ]
        capped = max(1, min(int(limit), 200))
        return {
            "count": len(tasks[:capped]),
            "total": len(tasks),
            "items": [_out(t, conn) for t in tasks[:capped]],
            "boundary": ai_mod.BOUNDARY,
        }

    @app.get("/api/ai/tasks/{task_id}")
    def ai_task(task_id: str, request: Request) -> dict[str, Any]:
        """读一个任务 + 它的步骤树（只读；前序 + 层数，与人侧树接口同口径）。"""
        _ai_guard(request)
        try:
            task = tm.get_task(conn, task_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        nodes = tm.task_tree(conn, task_id)
        return {
            "task": _out(task, conn),
            "steps": [
                {"task": _out(n.task, conn, depth=n.depth), "depth": n.depth} for n in nodes
            ],
        }

    @app.post("/api/ai/tasks")
    def ai_create_task(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        """**新增**：建任务；给了 `parent_id` 就是**给那个任务加一个步骤**（= 回报进展）。

        归属写 `created_by='ai'`（AI 只能勾它自己建的，所以这个标记是边界的前提）。
        只认下面这几个字段：多传的字段**明确拒绝**（不静默忽略 —— 否则 AI 以为设上了）。
        """
        _ai_guard(request)
        allowed = {"title", "parent_id", "due_date", "is_myday", "note", "priority"}
        extra = sorted(set(payload) - allowed)
        if extra:
            raise HTTPException(
                status_code=400,
                detail=f"不认识的字段：{extra}（这一版只支持 {sorted(allowed)}）—— "
                "改/删字段没有接口，这是 AI 边界的一部分。",
            )
        title = str(payload.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="任务标题不能为空")
        try:
            if payload.get("parent_id"):
                task = tm.create_subtask(
                    conn,
                    str(payload["parent_id"]),
                    title,
                    due_date=payload.get("due_date"),
                    created_by=tm.CREATOR_AI,
                )
            else:
                task = tm.create_task(
                    conn,
                    title,
                    due_date=payload.get("due_date"),
                    is_myday=bool(payload.get("is_myday", False)),
                    note=payload.get("note"),
                    priority=payload.get("priority") or tm.DEFAULT_PRIORITY,
                    created_by=tm.CREATOR_AI,
                )
        except KeyError:
            raise HTTPException(status_code=404, detail="父任务不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"ok": True, "task": _out(task, conn), "created_by": task.created_by}

    @app.post("/api/ai/tasks/{task_id}/complete")
    def ai_complete_task(task_id: str, request: Request) -> dict[str, Any]:
        """**勾完成**：只允许勾 AI 自己建的（你建的 → 400 带原话）。

        走的是和人**完全同一条**路（`tm.complete_task(..., actor="ai")`）：账本、联动、
        重复任务生成全都一致，只是事实的 `source` 记 `ai`（可审计）。
        """
        _ai_guard(request)
        try:
            task = ai_mod.require_own(conn, task_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        try:
            done = tm.complete_task(conn, task.id, actor=tm.CREATOR_AI)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        # 与人侧同一套：完成之后把当天那份 md 写出来（失败只记错，不挡这次调用）
        vault.try_export(
            conn, None, settings.export.dir, default_vault_dir=settings.export.vault_dir
        )
        return {"ok": True, "task": _out(done, conn)}

    # 边界兜底：这一版**没有**改/删接口。被显式调用时给一句能看懂的原话，
    # 而不是一个含义不明的 404（规格 R4：「AI 调用写/改/删：明确拒绝，不静默改」）。
    def _ai_refuse(method: str) -> HTTPException:
        listing = "；".join(f"{m} {p}" for m, p, _ in ai_mod.SURFACE)
        return HTTPException(
            status_code=403 if method != "GET" else 404,
            detail=f"AI 接口这一版只有：{listing}。"
            f"{'改/删' if method != 'GET' else '这个路径'}没有接口 —— "
            "边界是「只读 + 新增 + 勾自己建的」（见设置页「AI 接口」）。",
        )

    @app.api_route(
        "/api/ai/{rest:path}", methods=["PATCH", "PUT", "DELETE"], include_in_schema=False
    )
    def ai_refuse_write(rest: str, request: Request) -> dict[str, Any]:
        _ai_guard(request)
        raise _ai_refuse(request.method)

    @app.api_route(
        "/api/ai/{rest:path}", methods=["GET", "POST"], include_in_schema=False
    )
    def ai_refuse_unknown(rest: str, request: Request) -> dict[str, Any]:
        _ai_guard(request)
        raise _ai_refuse(request.method)

    # ---- 学校通知的合作接口（SR-F10.1 / G 批 · T-G14）----
    # 规格 `docs/specification/domains/F10-notify.md` 的定位：**监测由独立脚本做，主工具只提供
    # 合作接口**。这一版落地的是**收件箱**：脚本投递 → 去重/来源标记 → 你点一下转任务/提醒。
    # **不抓取**（主工具不去连学校网站）；**默认关**（同 AI 接口的"默认收严"）；
    # 投递入口要求本机来源（跨站网页偷着投递会被拦）。
    @app.get("/api/settings/notify")
    def get_notify_settings() -> dict[str, Any]:
        """合作接口现状 + 认哪些字段 + 收件箱计数（说明由后端给，界面不复述规则）。只读。"""
        return notify_mod.describe(conn, settings.notify.school_enabled)

    @app.put("/api/settings/notify")
    def put_notify_settings(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        """打开/关闭学校通知的合作接口（**默认关**；非法值 400 带原话）。只接受本机页面调用。"""
        require_local_origin(request)
        try:
            return notify_mod.set_enabled(
                conn, payload.get("enabled"), settings.notify.school_enabled
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/api/notify/school")
    def list_school_notices(status: str | None = None, limit: int = 100) -> dict[str, Any]:
        """读收件箱（新的在前 + 三个状态计数）。**读不要求接口开着**：收到的东西是你的数据。"""
        try:
            items = notify_mod.notices(conn, status=status or None, limit=limit)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {
            "items": items,
            "count": len(items),
            "settings": notify_mod.describe(conn, settings.notify.school_enabled),
        }

    @app.post("/api/notify/school")
    def receive_school_notice(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        """**外部脚本投递一条通知**（F10 的合作接口本体）。

        要求：本机来源 + 开关开着（否则 403 带原话 —— "未接入"不是故障）。
        重复投递不会新增行：返回 `duplicate=True`；只带上标题的那种重复投递
        **不会**把上次的链接/摘要/截止日抹掉。
        """
        require_local_origin(request)
        try:
            return notify_mod.receive(conn, payload, default_enabled=settings.notify.school_enabled)
        except notify_mod.NotConnectedError as e:
            # 「没接入」≠「参数错」：前者要用户去设置页点开关，后者要脚本改代码 → 两种状态码
            raise HTTPException(status_code=403, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.post("/api/notify/school/{notice_id}/to-task")
    def school_notice_to_task(
        notice_id: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """把某条通知转成任务/提醒（**你点一下才发生**；走和人手建任务完全相同的路径）。幂等。"""
        body = payload or {}
        try:
            return notify_mod.to_task(
                conn,
                notice_id,
                is_myday=bool(body.get("is_myday", False)),
                remind_at=body.get("remind_at"),
                due_date=body.get("due_date"),
                priority=body.get("priority"),
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="通知不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.post("/api/notify/school/{notice_id}/ignore")
    def school_notice_ignore(
        notice_id: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """标成已忽略 / 改回待看（不删行：删了下次投递又回来，反而像"没收到过"）。"""
        body = payload or {}
        try:
            return notify_mod.ignore(conn, notice_id, ignored=bool(body.get("ignored", True)))
        except KeyError:
            raise HTTPException(status_code=404, detail="通知不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    # ---- 备份与恢复（SR-NF12 / SR-F9.3）----
    # 口径（2026-09-21 用户定）：设置页列出最近几个备份，点一个就能恢复。
    @app.get("/api/settings/backups")
    def get_backups() -> dict[str, Any]:
        """同目录下的备份（最新在前，最多 20 条）+ 口径说明。只读。"""
        path = Path(str(db_path))
        return {
            "db": path.name,
            "dir": str(path.parent),
            "items": backup_mod.list_backups(path)[:20],
            "note": "恢复会把整库回到那个时间点（**连设置一起**）；恢复前会先自动再备份一次现库，"
                    "所以选错了还能回去。",
        }

    @app.post("/api/settings/restore")
    def post_restore(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        """从备份恢复（**不可逆动作** → 界面必须二次确认）。只接受本机页面调用。

        实现见 `storage/backup.py`：在线备份 API 写内容（不替换文件）+ 恢复前先备份现库 +
        老 schema 就地升级；备份比程序新时如实报 `newer_than_app`。
        """
        require_local_origin(request)
        try:
            return backup_mod.restore(db_path, str(payload.get("name") or ""), conn)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    # ---- 到点提醒的通知通道（T-B5 后半）：计划任务 + 系统通知（用户选 B′）----
    @app.get("/api/settings/reminder")
    def get_reminder_settings() -> dict[str, Any]:
        """到点通知的状态（是否启用、计划任务在不在、上次通知时间/结果/错误）。

        都是**事实**：没装就是没装，弹失败会把原因带出来（不谎报"已提醒"）。
        """
        return remind_mod.status(conn)

    @app.put("/api/settings/reminder")
    def put_reminder_settings(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        """打开/关闭到点通知、切换提醒方式。打开会**注册 Windows 计划任务**（关掉会删掉它，可逆）。

        改系统状态，所以要求来源本机；注册失败时设置不落库（避免"以为开了其实没开"）。
        `style`：`alarm`=闹钟式（留在屏幕上 + 循环响铃）/ `gentle`=温和通知。
        """
        require_local_origin(request)
        try:
            if "style" in payload:
                remind_mod.set_style(conn, payload["style"])
            if "enabled" in payload:
                remind_mod.set_enabled(conn, bool(payload["enabled"]), db_path=db_path)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return remind_mod.status(conn)

    @app.post("/api/reminders/test")
    def test_reminder(request: Request) -> dict[str, Any]:
        """弹一条测试通知（让你当场确认效果；按当前"提醒方式"弹）。会弹窗，故要求来源本机。"""
        require_local_origin(request)
        ok, detail = remind_mod.show_notification(
            "timeflow 提醒测试",
            "看到这条就说明到点提醒能用。",
            remind_mod.get_style(conn),
        )
        remind_mod.record_result(conn, ok, detail)
        return {"ok": ok, "detail": detail, **remind_mod.status(conn)}

    @app.post("/api/reminders/stop")
    def stop_ringing(request: Request) -> dict[str, Any]:
        """**停止响铃**（T-B5c）：清掉还在屏幕上/通知中心里的闹钟式提醒。

        为什么需要这个接口：闹钟式通知是"一直响到你关掉"，而关掉的入口只有通知上的 ✕ ——
        用户在应用里应当也有一个"别响了"的按钮。幂等（本来没有也算成功）；失败**不静默**，原样返回原因。
        """
        require_local_origin(request)
        ok, detail = remind_mod.clear_notifications()
        return {"ok": ok, "detail": detail}

    # ---- 提醒（SR-F1.4 / T-B5）：字段与"该提醒了"的只读数据源 ----
    @app.get("/api/reminders/due")
    def due_reminders(now: str | None = None) -> list[TaskOut]:
        """到点该提醒的任务（`remind_at <= now`，排除完成/取消/归档/已删），按提醒时间正序。

        `now` 可用本地时间字符串覆盖（便于测试/演示）；缺省用本机当前时间。
        只读：不改任务、不发事实 —— **通知通道另说**（选型见复盘 §八，未接入前界面自己标出来）。
        """
        moment: datetime | None = None
        if now:
            try:
                moment = datetime.fromisoformat(now)
            except ValueError:
                raise HTTPException(status_code=400, detail="now 需是本地时间字符串") from None
        return [_out(t, conn) for t in tm.due_reminders(conn, moment)]

    @app.get("/api/reminders")
    def reminders() -> list[dict[str, Any]]:
        """所有设了提醒且任务还"活着"的条目：`{task_id, title, remind_at, state}`。

        `state` 是**界面口径**（`over`/`today`/`soon`/`later`），来自领域层 `reminder_state` ——
        卡片、详情、将来的通知通道共用同一份判断，不各算一套。
        """
        out: list[dict[str, Any]] = []
        for t in tm.list_tasks(conn):
            state = tm.reminder_state(t)
            if state is None:
                continue
            out.append({
                "task_id": t.id,
                "title": t.title,
                "remind_at": t.remind_at,
                "state": state,
            })
        out.sort(key=lambda x: str(x["remind_at"]))
        return out

    @app.put("/api/settings/attach")
    def put_attach_settings(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        """改打开方式 / 白名单（服务端持久化；可执行/脚本类不许进白名单）。"""
        require_local_origin(request)
        try:
            attach_mod.set_settings(conn, payload.get("mode"), payload.get("whitelist"))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {**attach_mod.get_settings(conn), **attach_mod.describe_rules()}

    def _require_groups(group_ids: list[str]) -> None:
        """任务上要挂的每个分组都必须**已经存在**（T-G33）。

        为什么单独先验一遍，而不是等 `set_task_groups` 抛错：关联发生在**任务建完/改完之后**，
        等它抛错时那条任务**已经落库** —— 客户端看到报错、库里却多一条（重试就多两条）。
        所以把输入先验干净：这一类的"半成品"就不存在了。

        口径与 `POST /api/tasks/{task_id}/group` 那条路由**一致**：分组不存在 = **404**，
        并把是哪个 id 说出来（照抄领域层 `get_group` 的原话，别自己另造一句）。

        （残留边界，如实写：验证通过之后若再出数据库级错误，任务仍然留下 —— 两个 core 函数
        各自 commit，没有跨函数事务。要彻底解决得动事务边界，不在这一卡里做。）
        """
        missing: list[str] = []
        for gid in group_ids:
            key = str(gid or "").strip()
            if not key or key in missing:
                continue
            try:
                tm.get_group(conn, key)
            except KeyError as e:
                missing.append(str(e.args[0]) if e.args else key)
        if missing:
            raise HTTPException(status_code=404, detail="；".join(missing))

    @app.post("/api/tasks", response_model=TaskOut)
    def create_task(payload: TaskIn) -> TaskOut:
        try:
            _require_groups(payload.groups)
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
                attach=[dict(i) for i in payload.attach],
                remind_at=payload.remind_at,
                task_type=payload.task_type,
                course_id=payload.course_id,
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

    @app.get("/api/tasks/doing")
    def doing_tasks() -> list[TaskOut]:
        """「进行中」清单（F 批 · T-F1）：可以同时多个，顺序由用户自己定（`doing_rank`）。

        注意：本路由必须声明在 `/api/tasks/{task_id}` 之前，否则 "doing" 会被当成 task_id。
        """
        return [_out(t, conn) for t in tm.doing_tasks(conn)]

    @app.get("/api/tasks/archived")
    def archived_tasks() -> list[TaskOut]:
        """档案视图（F 批 · T-F1 + T-F2，最近进档案的在前）：
        **手动归档的 + 完成满 N 天自动收入的**。

        两种来源都在这里（档案的用法是"回头看"，分两处看会漏掉一半），
        界面用 `auto_archived` 区分并分别显示「完成 N 天后自动收入」/「手动归档」。
        "试了几回"（T-F3）与完成日也在这条接口里一次算好（各一次聚合查询，不给卡片各查一遍）。

        注意：本路由必须声明在 `/api/tasks/{task_id}` 之前，否则 "archived" 会被当成 task_id。
        """
        entries = tm.archive_entries(conn)
        counts = tm.attempt_counts(conn, [e.task.id for e in entries])
        return [
            _out(
                e.task,
                conn,
                auto_archived=e.auto,
                completed_on=e.completed_on,
                attempt_count=counts.get(e.task.id, 0),
            )
            for e in entries
        ]

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

        `groups` 先验（T-G33）：不存在的分组 → **404「分组不存在」**。以前这里两种 404 混成一句 ——
        分组不存在也报「任务不存在」，**指错了对象**（任务好好的）。
        """
        fields = {k: v for k, v in payload.items() if k != "groups"}
        if "groups" in payload:
            _require_groups(payload["groups"])
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
            task = tm.complete_task(conn, task_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        # md 是产物（T-G4）：写完最好，写不成只记错 —— 不许因为磁盘/路径问题让"完成"失败
        vault.try_export(
            conn, None, settings.export.dir, default_vault_dir=settings.export.vault_dir
        )
        return _out(task, conn)

    @app.post("/api/tasks/{task_id}/uncomplete", response_model=TaskOut)
    def uncomplete_task(task_id: str, payload: dict[str, Any] | None = None) -> TaskOut:
        """撤销完成（OP-5 可逆）：发 task.uncompleted 反向事实并恢复状态。"""
        restore = (payload or {}).get("restore_status", tm.STATUS_TODO)
        try:
            task = tm.uncomplete_task(conn, task_id, restore_status=restore)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        # 撤销之后**重新导出**：md 跟着回到"这一天没做成它"（数据库权威，md 是产物）
        vault.try_export(
            conn, None, settings.export.dir, default_vault_dir=settings.export.vault_dir
        )
        return _out(task, conn)

    # ---- 状态机：进行中 / 待定 / 取消 / 归档（F 批 · T-F1）----
    # 口径见 `复盘/口径定案-待定清单.md` §1。这些动作**都不动账本**
    # （债务只看 `overdue_tasks`，与"我在怎么安排这件事"无关），只留 `task.status_changed` 事实。
    def _status_action(task_id: str, action: str) -> TaskOut:
        """状态动作共用一条错误口径：任务不存在 → 404，非法跃迁 → 400（不静默）。"""
        try:
            return _out(status_actions[action](conn, task_id), conn)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    status_actions: dict[str, Any] = {
        "start": tm.start_task,
        "stop": tm.stop_task,
        "park": tm.park_task,
        "unpark": tm.un_park_task,
        "cancel": tm.cancel_task,
        "archive": tm.archive_task,
        "unarchive": tm.unarchive_task,
    }

    @app.post("/api/tasks/{task_id}/start", response_model=TaskOut)
    def start_task(task_id: str) -> TaskOut:
        """放进「进行中」（T-F1）：**可以同时多个**，序号自动排到最后。"""
        return _status_action(task_id, "start")

    @app.post("/api/tasks/{task_id}/stop", response_model=TaskOut)
    def stop_task(task_id: str) -> TaskOut:
        """移出「进行中」（T-F1）：回到「未开始」；截止日已过则回到「逾期」。"""
        return _status_action(task_id, "stop")

    @app.post("/api/tasks/{task_id}/park", response_model=TaskOut)
    def park_task(task_id: str) -> TaskOut:
        """搁置为「待定」（T-F1）：闲置/挂在那儿、没放弃、**不计债**、不提醒、不进 My Day。"""
        return _status_action(task_id, "park")

    @app.post("/api/tasks/{task_id}/unpark", response_model=TaskOut)
    def unpark_task(task_id: str) -> TaskOut:
        """把「待定 / 取消」取回（T-F1）。"""
        return _status_action(task_id, "unpark")

    @app.post("/api/tasks/{task_id}/cancel", response_model=TaskOut)
    def cancel_task(task_id: str) -> TaskOut:
        """取消任务（T-F1）：打错了 / 没必要做了 —— ≈删除但留痕。"""
        return _status_action(task_id, "cancel")

    @app.post("/api/tasks/{task_id}/archive", response_model=TaskOut)
    def archive_task(task_id: str) -> TaskOut:
        """收进档案（T-F1）：默认视图不再显示，可在「档案」里查阅（可撤销）。"""
        return _status_action(task_id, "archive")

    @app.post("/api/tasks/{task_id}/unarchive", response_model=TaskOut)
    def unarchive_task(task_id: str) -> TaskOut:
        """撤销归档（T-F1）。"""
        return _status_action(task_id, "unarchive")

    @app.post("/api/tasks/{task_id}/doing-move", response_model=TaskOut)
    def move_doing(task_id: str, payload: dict[str, Any] | None = None) -> TaskOut:
        """调「进行中」的先后（T-F1）：`{direction: up|down}`，与相邻一条换序号。

        为什么不做拖拽：段2 决策（触屏/键鼠/可测性都不划算）—— 上/下按钮 + 显式序号。
        """
        direction = str((payload or {}).get("direction", ""))
        try:
            return _out(tm.move_doing(conn, task_id, direction), conn)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    # ---- 「尝试失败」显式计次（N11 / F 批 · T-F3）----
    # 口径（`复盘/口径定案-待定清单.md` §1）：**只认显式点击**，不自动从"推到明天/取消"推断
    # —— 这个数字要可信。一次点击一条事实；`note` 可选（将来进 md 存档）。
    def _attempt_body(task_id: str) -> dict[str, Any]:
        """试了几回 + 历次说明：GET 与 POST 用同一份读法，免得两处各算一套。"""
        return {"count": tm.attempt_count(conn, task_id), "notes": tm.attempt_notes(conn, task_id)}

    @app.get("/api/tasks/{task_id}/attempts")
    def list_attempts(task_id: str) -> dict[str, Any]:
        """「试了几回」（T-F3）：`{count, notes}`。任务不存在 404。"""
        try:
            tm.get_task(conn, task_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        return _attempt_body(task_id)

    @app.post("/api/tasks/{task_id}/attempt-failed")
    def attempt_failed(task_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """记一次「尝试失败」（T-F3）：`{note?}` 可选；返回记完之后的 `{task, count, notes}`。

        这里**不改状态**：失败之后做什么（取消 / 待定 / 推到明天）是用户下一步的选择。
        """
        note = str((payload or {}).get("note", "") or "")
        try:
            task = tm.attempt_failed(conn, task_id, note)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"task": _out(task, conn), **_attempt_body(task_id)}

    @app.get("/api/tasks/{task_id}/subtasks")
    def list_subtasks(task_id: str) -> list[TaskOut]:
        """子任务列表（未完成在前）。任务不存在 404。"""
        try:
            tm.get_task(conn, task_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        return [_out(t, conn) for t in tm.subtasks(conn, task_id)]

    @app.get("/api/tasks/{task_id}/tree")
    def task_tree(task_id: str) -> list[TaskOut]:
        """整棵子树（F 批 · T-F5）：**前序**（父在子前），每条带绝对 `depth`（2/3…）。

        N10/SR-F1.6 的「任务树/折叠呈现」用这一份：三层都能摆出来，
        界面不必自己"先取子、再逐个取孙子"。任务不存在 404。
        """
        try:
            tm.get_task(conn, task_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        return [_out(n.task, conn, depth=n.depth) for n in tm.task_tree(conn, task_id)]

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
        """分组列表（含任务计数 / `parent_id` / `depth` / `path`）—— **按树的前序**（父在子前）。

        F 批 · T-F5：分组可嵌套。界面靠这一份数据做缩进与路径显示，
        不在前端另拼一遍树（"父在子前"这套顺序只写一处）。
        """
        return tm.list_groups(conn)

    @app.post("/api/groups", status_code=201)
    def create_group(payload: dict[str, Any]) -> dict[str, Any]:
        """新建分组（OP-11）。空名 400；**同一个父下重名 400**（不静默复用，免得以为建了新组）。

        `{parent_id}` 可选：给了就建成那个分组的**子分组**（T-F5）；
        父不存在 404、超过层数上限 400（都不静默）。
        T-F10：**跨父可以重名**（「高数 / 作业」与「英语 / 作业」都行），只有同层撞名才算重复。
        """
        name = str(payload.get("name", "")).strip()
        if not name:
            raise HTTPException(status_code=400, detail="分组名不能为空") from None
        raw_parent = payload.get("parent_id")
        parent_id = None if raw_parent is None else str(raw_parent)
        sibling = [
            g for g in tm.list_groups(conn)
            if str(g["name"]) == name and str(g["parent_id"] or "") == (parent_id or "")
        ]
        if sibling:
            where = str(sibling[0]["path"])
            raise HTTPException(status_code=400, detail=f"分组「{where}」已存在") from None
        try:
            gid = tm.create_group(conn, name, parent_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="父分组不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return tm.get_group(conn, gid)

    @app.patch("/api/groups/{group_id}")
    def rename_group(group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """重命名分组（OP-11）。空名 400；不存在 404；改到已有名字 = 与那个分组合并（幂等）。

        嵌套之后多两条边界（T-F5）：**有子分组时不能合并**、**不能合并进自己的子孙** ——
        都 400 带原话，不静默把子分组甩到顶层或造出一个环。
        """
        if "name" not in payload:
            raise HTTPException(status_code=400, detail="缺少 name") from None
        try:
            return tm.rename_group(conn, group_id, str(payload["name"]))
        except KeyError:
            raise HTTPException(status_code=404, detail="分组不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.post("/api/groups/{group_id}/parent")
    def set_group_parent(group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """把分组移到另一个分组下（`{parent_id}`，null = 移到顶层）—— T-F5 的"移进去/移出来"。

        成环 / 超层数 / 父不存在：400·404 带原话（不静默）。
        """
        parent_id = payload.get("parent_id")
        try:
            return tm.set_group_parent(
                conn, group_id, None if parent_id is None else str(parent_id)
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="分组不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.delete("/api/groups/{group_id}")
    def delete_group(group_id: str) -> dict[str, Any]:
        """删除分组（OP-11）：**只删分组与关联，任务本身保留**。不存在 404。

        T-F5：**有子分组时 400**（要求先把子分组移走或删掉）—— 一次点击悄悄级联删掉
        看不见的几层，比让人多走一步更容易出事。
        """
        try:
            tm.get_group(conn, group_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="分组不存在") from None
        try:
            unbound = tm.delete_group(conn, group_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
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
        """把任务加入/移出某分组（`{group_id, on}`）。任务不存在 404；分组不存在 404。

        T-F10 起**按分组 id**：分组名允许重名（「高数 / 作业」与「英语 / 作业」同名），
        名字不再是能认的标识。返回改动后的**路径**列表（界面直接显示）。
        """
        try:
            tm.get_task(conn, task_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        group_id = str(payload.get("group_id", ""))
        try:
            paths = tm.toggle_task_group(conn, task_id, group_id, bool(payload.get("on", True)))
        except KeyError:
            raise HTTPException(status_code=404, detail="分组不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {
            "task_id": task_id,
            "groups": paths,
            "group_ids": tm.task_group_ids(conn, task_id),
        }

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

    @app.get("/api/today/done")
    def today_done(day: str | None = None) -> ledger.TodayDone:
        """**今天做成了什么**（T-C11 / 契约 OP-48）：完成任务 / 完成步骤 / 产出分两类。

        只读事实层，供今日页那张可展开的「今天做成了什么」用它 —— 数字与明细同源。
        `day` 可用 `YYYY-MM-DD` 覆盖（便于测试/回看某天）。
        """
        if day is not None:
            from datetime import date as _date

            try:
                _date.fromisoformat(day)
            except ValueError:
                raise HTTPException(status_code=400, detail="非法日期") from None
        return ledger.today_done(conn, day)

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
        """专注白名单 / 勿扰时段（当前值 + 口径说明）。

        GAP-F3-02 收口：以前只回读 config.toml、**没有任何写入口**；现在默认值仍来自 config.toml，
        但本机在设置页改过的值存在 `app_settings` 里并优先（见 `core/focus/guard.py`）。
        """
        return {**fg.get_settings(conn, _guard_defaults()), **fg.describe_rules()}

    @app.put("/api/settings/focus-guard")
    def put_focus_guard(payload: dict[str, Any], request: Request) -> dict[str, object]:
        """改专注白名单 / 勿扰时段。与附件打开方式一样**服务端持有 + 只接受本机页面**。

        非法值 400（不静默落默认值、不静默清空）；`block_by_default` 必须是真布尔。
        """
        require_local_origin(request)
        try:
            return fg.set_settings(
                conn,
                defaults=_guard_defaults(),
                block_by_default=payload.get("block_by_default"),
                whitelist=payload.get("whitelist"),
                do_not_disturb=payload.get("do_not_disturb"),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

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

    @app.get("/api/insights/repeat-rhythm")
    def insights_repeat_rhythm(days: int = insights.DEFAULT_RHYTHM_DAYS) -> insights.RepeatRhythm:
        """近 N 天的重复任务节奏（SR-F1.5b / T-G25）；1≤days≤180，默认 8 周。

        每条 = 一个重复事项（同一标题 + 同一周期）；格子按**排期日**画 —— 口径在领域层，
        连说明一起返回（`note`），界面不复述规则。
        """
        if not 1 <= days <= insights.MAX_RHYTHM_DAYS:
            raise HTTPException(
                status_code=400, detail=f"days 需在 1~{insights.MAX_RHYTHM_DAYS} 之间"
            )
        return insights.repeat_rhythm(conn, days=days)

    @app.get("/api/insights/groups")
    def insights_groups(days: int = insights.DEFAULT_TREND_DAYS) -> list[insights.GroupInsight]:
        """近 N 天投入按任务分组（领域）分布；任务可属多分组，各组之和可能大于总投入。"""
        if not 1 <= days <= insights.MAX_TREND_DAYS:
            raise HTTPException(
                status_code=400, detail=f"days 需在 1~{insights.MAX_TREND_DAYS} 之间"
            )
        return insights.group_insights(conn, days=days)

    @app.get("/api/insights/academic-vs-self")
    def insights_academic_vs_self(
        days: int = insights.DEFAULT_TREND_DAYS,
    ) -> insights.AcademicSplit:
        """学业投入 vs 自学投入（SR-F5.1b / T-C10）：只统计**绑定了任务**的专注 ——
        挂课程 = 学业、没挂课程 = 自学、未绑定（或任务已清理）**单列**；手动投入不参与。"""
        if not 1 <= days <= insights.MAX_TREND_DAYS:
            raise HTTPException(
                status_code=400, detail=f"days 需在 1~{insights.MAX_TREND_DAYS} 之间"
            )
        return insights.academic_vs_self(conn, days=days)

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

    # ---- 考核项的"要求链接"（SR-F5.3 / T-B4）：与任务附件**共用同一字段与打开规则** ----
    @app.post("/api/assessments/{assessment_id}/attachments")
    def add_assessment_attachment(
        assessment_id: str, payload: dict[str, Any]
    ) -> dict[str, object]:
        try:
            return ac.add_assessment_attachment(
                conn, assessment_id, str(payload.get("target", "")), payload.get("title")
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="考核项不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.delete("/api/assessments/{assessment_id}/attachments/{index}")
    def remove_assessment_attachment(
        assessment_id: str, index: int
    ) -> dict[str, object]:
        try:
            return ac.remove_assessment_attachment(conn, assessment_id, index)
        except KeyError:
            raise HTTPException(status_code=404, detail="考核项不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

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
    @app.get("/api/review/meta")
    def review_meta() -> dict[str, object]:
        """复习的可选项（形式 / 执行源）—— 中文词表只在后端一处，界面拿它渲染。

        形式词表可配置（G 批 · T-G1）：默认来自 config.toml `[review] forms`，
        本机在设置页改过的存 `app_settings` 并优先。
        """
        return rv.meta(conn, settings.review.forms)

    @app.post("/api/review/items")
    def create_review(payload: dict[str, Any]) -> dict[str, str]:
        try:
            return {"id": rv.create_item(
                conn,
                title=payload["title"],
                form=payload.get("form"),
                source=payload.get("source", "internal"),
                ref_handle=payload.get("ref_handle"),
                task_id=payload.get("task_id"),
                forms_defaults=settings.review.forms,
            )}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.patch("/api/review/items/{item_id}")
    def update_review(item_id: str, payload: dict[str, Any]) -> dict[str, object]:
        """改复习卡的**定义类字段**（T-C6 形式 / T-C7 引用句柄 / 标题、执行源）。

        排期字段（due_date/interval/ease/reps）不给人手改 —— 那是 FSRS 的记忆状态。
        `EDITABLE_FIELDS` 同时用来**过滤请求体**：领域层的参数名不会被 body 里的同名键撞上。
        """
        body = {k: v for k, v in payload.items() if k in rv.EDITABLE_FIELDS}
        try:
            return rv.update_item(conn, item_id, forms_defaults=settings.review.forms, **body)
        except KeyError:
            raise HTTPException(status_code=404, detail="复习卡不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/api/review/items/{item_id}")
    def get_review(item_id: str) -> dict[str, object]:
        try:
            return _ref_url(rv.get_item(conn, item_id))
        except KeyError:
            raise HTTPException(status_code=404, detail="复习卡不存在") from None

    @app.post("/api/tasks/{task_id}/to-review")
    def task_to_review(task_id: str, payload: dict[str, Any] | None = None) -> dict[str, object]:
        """把任务**升级成复习卡**（T-C5 / SR-F6.6）：卡的标题默认取任务标题。

        幂等：同一个任务已经升级过 → 返回已有的那张卡（`created=false`），不会越点越多张。
        """
        try:
            task = tm.get_task(conn, task_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        body = payload or {}
        existing = rv.items_for_task(conn, task_id)
        if existing:
            return {"created": False, "card": existing[0], "cards": existing}
        try:
            item_id = rv.create_item(
                conn,
                title=str(body.get("title") or task.title),
                form=body.get("form"),
                source=body.get("source", "internal"),
                ref_handle=body.get("ref_handle"),
                task_id=task_id,
                forms_defaults=settings.review.forms,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"created": True, "card": rv.get_item(conn, item_id), "cards": []}

    @app.get("/api/tasks/{task_id}/review-cards")
    def task_review_cards(task_id: str) -> list[dict[str, object]]:
        """某任务升级出来的复习卡（只读）：详情面板据此显示"已做成卡"。"""
        try:
            tm.get_task(conn, task_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        return _with_ref_url(rv.items_for_task(conn, task_id))

    @app.get("/api/review/due")
    def review_due() -> list[dict[str, object]]:
        return _with_ref_url(rv.due_items(conn))

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

    @app.get("/api/review/today")
    def review_today() -> list[dict[str, object]]:
        """**今天复习过的卡**（带这次记的是哪一档）—— 界面「今天复习过的」那一段与「改判」入口。"""
        return rv.reviewed_today_items(conn)

    @app.post("/api/review/{item_id}/regrade")
    def regrade_review(item_id: str, payload: dict[str, Any]) -> dict[str, object]:
        """把当日最近一次反馈改成另一档（T-G13）= 撤销 + 按新档重来：排期按同一快照重算、
        投入不重复计、原来那次留在流水里（`review.undone` + `review.regraded`）。"""
        try:
            return rv.regrade(conn, item_id, payload["feedback"])
        except KeyError:
            raise HTTPException(status_code=404, detail="复习卡不存在") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

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

    @app.get("/api/team/board")
    def team_board(
        view: str = team.VIEW_MANAGER, me: str = "", status: str | None = None
    ) -> dict[str, object]:
        """团队视角页（SR-F7.1 / OP-33）：管理者 / 执行者两种看法，**同一份分配记录**。

        执行者视角要你给一个名字（`me`）—— 执行者是自由文本、本工具没有账号体系，
        所以"我是谁"由你说，工具不猜（没填 → 空列表 + 一句说明，不报错）。
        """
        try:
            return team.board(conn, view=view, me=me, status=status or None)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    # ---- SR-F8 备忘录/知识资产 ----
    @app.post("/api/memos")
    def create_memo(payload: dict[str, Any]) -> dict[str, str]:
        try:
            memo_id = memo.create_memo(
                conn,
                text=payload["text"],
                ref_handle=payload.get("ref_handle"),
                task_id=payload.get("task_id"),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        # 备忘录是**沉淀型内容**（约定层）：写完自动落一份 md（失败只记错，见 T-G4）
        vault.try_export(
            conn, None, settings.export.dir, default_vault_dir=settings.export.vault_dir
        )
        return {"id": memo_id}

    @app.get("/api/memos")
    def list_memos() -> list[dict[str, object]]:
        # 备忘录挂着引用句柄时给一条**能直接跳 Obsidian** 的链接（T-G5，只读）
        return _with_ref_url(memo.list_memos(conn))

    @app.delete("/api/memos/{memo_id}")
    def delete_memo(memo_id: str) -> dict[str, str]:
        """删除备忘录（幂等）；关联任务不自动删除。删完重新导出（md 跟着数据库走）。"""
        memo.delete_memo(conn, memo_id)
        vault.try_export(
            conn, None, settings.export.dir, default_vault_dir=settings.export.vault_dir
        )
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
            entry_id = memo.add_output_entry(
                conn, value=payload["value"], kind=payload.get("kind", "asset"),
                note=payload.get("note"), ref_handle=payload.get("ref_handle"),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        # 产出（温故知新那类沉淀）也落 md（T-G4）
        vault.try_export(
            conn, None, settings.export.dir, default_vault_dir=settings.export.vault_dir
        )
        return {"id": entry_id}

    @app.get("/api/ledger/outputs")
    def ledger_outputs(date_str: str | None = None) -> list[dict[str, object]]:
        """某日产出流水（产出轴，含是否已撤销）；默认今天。"""
        return memo.list_outputs(conn, day=date_str)

    @app.delete("/api/ledger/output/{entry_id}")
    def ledger_output_retract(entry_id: str) -> dict[str, object]:
        """撤销一条产出（追加 `output.retracted` 反向事实，不删历史）。撤完重新导出。"""
        try:
            changed = memo.retract_output_entry(conn, entry_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="产出记录不存在") from None
        vault.try_export(
            conn, None, settings.export.dir, default_vault_dir=settings.export.vault_dir
        )
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

    # ---- 跨端同步：同步包（导出/导入）（SR-F9.2 / SR-NF17；G 批 · T-G8 = 场景 ③）----
    # 口径（2026-09-21 用户定，见 `复盘/口径定案-待定清单.md` §3）：**③ 先做**（走文件的合并机制，
    # 它是 ① 的地基）；规则与措辞都在 `core/syncpack.py` 一处。两条硬边界写在这里：
    #   - **导入默认不删你本地的东西**（远程墓碑只防复活 + 继续传给下一台）；
    #     要连「对方删掉的」也一起删，导入时传 `apply_deletions=true`
    #     （T-G8b，用户 2026-09-23 定的口径：「覆盖，可以选择是否删除」）——
    #     那时**本地更新过的那种仍然不删**；
    #   - 覆盖/保留/删除**逐条记进冲突日志**（不静默覆盖），界面能看见"为什么动了这一行"。
    @app.post("/api/sync/export")
    def sync_export(request: Request) -> dict[str, Any]:
        """导出一份同步包到**数据库同目录**（原子写），返回路径与条数。

        位置选在库旁边：与 `.bak-*` 备份同一个地方，用户找得到、也能"打开目录"。
        """
        require_local_origin(request)
        try:
            result = syncpack.export_pack(conn, Path(str(db_path)).parent)
        except (OSError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e) or e.__class__.__name__) from e
        return {"ok": True, **asdict(result)}

    @app.post("/api/sync/import")
    def sync_import(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        """导入一份同步包（`dry_run=true` 只预览、一个字节都不写）。

        `apply_deletions`（T-G8b）：要不要把"对方删过的东西"也在这边删掉 —— **默认 false**。
        预览与真导入走**同一套判断**（`plan_merge` → 执行），所以预览里 `totals.deleted`
        就是真导入会删掉的行数。

        非法包 / 不是我们的格式 / 来自更新版本 → **400 带原话**（不许"尽力猜"）。

        **局域网设备只能传内容、不能指路径**（T-G15）：手机直接上传走的是 `pack`（包内容），
        `path` 是"在电脑上读一个文件"的便利口子。判据看的是**页面的来源**（Origin），
        不是 TCP 来源 —— 本机脚本/命令行**没有 Origin**，照旧可以指路径；
        而从**局域网地址**打开的那个页面（手机、或别人电脑上的浏览器）不行：
        配对码证明的是"你是本人"，不是"你可以让这台电脑去读盘上任意一个路径"。
        两条路合并的是**同一套规则**。
        """
        require_local_origin(request)
        dry = bool(payload.get("dry_run"))
        apply_del = bool(payload.get("apply_deletions"))
        try:
            pack = payload.get("pack")
            if pack is None:
                origin = request.headers.get("origin")
                host = urlsplit(origin).hostname if origin else None
                if origin and not lan_mod.is_loopback(host):
                    raise HTTPException(
                        status_code=403,
                        detail="从局域网地址打开的这个页面不能指定电脑上的文件路径："
                        "请把包的内容（pack）直接发过来（手机上的「直接传到电脑」就是这么做的）。",
                    )
                pack = syncpack.load_pack(str(payload.get("path") or ""))
            report = syncpack.merge_pack(
                conn, pack, dry_run=dry, apply_deletions=apply_del
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"ok": True, "apply_deletions": apply_del, **report.as_dict()}

    @app.get("/api/sync/status")
    def sync_status() -> dict[str, object]:
        """同步现状（OP-40/OP-41）：**只报事实** —— 走文件能用、走网络还没做（不谎报）。"""
        return {**sync_mod.status(conn), **syncpack.status(conn)}

    @app.get("/api/sync/logs")
    def sync_logs() -> list[dict[str, object]]:
        """最近的冲突/覆盖记录（**不静默覆盖**的可视面）：含结果与一句"差在哪"。"""
        rows = conn.execute(
            "SELECT * FROM sync_logs ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
        keys = set(rows[0].keys()) if rows else set()
        return [
            {"id": r["id"], "entity": r["entity"], "entity_id": r["entity_id"],
             "local_ts": r["local_ts"], "remote_ts": r["remote_ts"],
             "result": (r["result"] if "result" in keys else None),
             "note": (r["note"] if "note" in keys else None),
             "created_at": r["created_at"]}
            for r in rows
        ]

    # 静态前端入口：/ （index.html）、/manifest.json、/sw.js、图标等
    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")

    return app
