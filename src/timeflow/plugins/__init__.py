r"""插件注册路径（卡 229 / T-G346 · SR-NF7）——「加字段 / 加功能不改核心」的最小落地。

T-D9 留下的原话：「真正的插件注册机制仍没有」。本模块只补**一条**注册路径，不做框架。

**一个插件 = 一个 .py 文件**，声明下面两个可选钩子（哪个需要声明哪个）：

    def register_routes(app, conn):      # 扩展点①：加 API 路由（"加功能"的代表）
        @app.get("/api/你的路由")
        def your_route(): ...

    def register_rules(add_rule):        # 扩展点②：加口径 / 派生读数（"加字段"的代表）
        add_rule(behavior.Rule(...), compare_fn)

★ 口径**复用** `core/behavior.py` 那一张表：插件口径与核心口径在 `/api/settings/behavior`
里同列，切换 / 影子对比 / 一键回退全套照旧 —— **不并列造第二张口径表**。
实现口径：装配时把 `Rule` 绑进 `behavior.RULES`（那张表在 `rule_by_key` / `report` 里都是
运行时现读的），卸载时恢复原表 —— 核心源文件一字不改（判据在 `tests/test_plugins.py`）。

**装配是声明式的**：`apply(app, conn, paths)` 表示「现在装的就是这一组」——
先卸干净再装，同一份输入两次装配结果逐字节相同；`uninstall(app)` 把路由、口径、
模块缓存全部收回，回到没装过的原样。生产语义：卸载 = 清掉 `TIMEFLOW_PLUGINS` 再重启。

**失败必须看得见**（不许静默吞）：坏插件（导入即炸 / 钩子抛错 / 口径不合法 /
路由撞已有路径 / 一个钩子都没声明）原样报进报告，`GET /api/plugins` 随时可查，
服务本体不受牵连。

插件清单从哪来：环境变量 `TIMEFLOW_PLUGINS`（路径分隔符分开的 .py 文件或目录，
目录取其中每个不以下划线开头的 .py），或调用方直接传 `paths`。
"""

from __future__ import annotations

import importlib.util
import os
import sys
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

from starlette.routing import Mount

from timeflow import logs
from timeflow.core import behavior

if TYPE_CHECKING:
    import sqlite3
    import types
    from collections.abc import Callable

    from fastapi import FastAPI

#: 插件清单环境变量：os.pathsep 分隔（Windows 是 ``;``，类 Unix 是 ``:``）。
ENV_KEY = "TIMEFLOW_PLUGINS"

#: 状态墙：插件装了什么 / 坏在哪，随时可查（"失败必须看得见"的那一面）。
STATUS_ROUTE = "/api/plugins"

_HOOKS = ("register_routes", "register_rules")

# ---- 进程内的插件状态（与核心同款约束：口径表全进程只有一套）----
#: 核心口径表的原样（首次导入本包时拍下，卸载时恢复）。
_ORIGINAL_RULES: tuple[behavior.Rule, ...] = behavior.RULES
#: 本进程插件加进口径表的 key（卸载时按它核对收回干净）。
_RULE_KEYS: list[str] = []
#: 已导入的插件模块（卸载时清出 sys.modules，不留缓存残留）。
_MODULES: dict[str, types.ModuleType] = {}
_SEQ = 0


# ------------------------------------------------ 口径扩展点（复用 behavior 那张表）
def _add_rule(rule: behavior.Rule, compare_fn: behavior.CompareFn | None = None) -> None:
    """把一条「可重算的派生口径」装进 `core/behavior.py` 那张表。

    护栏与核心同款（见 `tests/test_behavior_rollback_line.py`）：只收 derived、
    至少两种做法、默认位必须是自己的做法、key 不撞 —— 违反当场 ValueError，
    **不静默落默认值**。顺序不能反：先绑表再挂影子对比（`register_compare` 要求
    key 已在表里）。
    """
    if not isinstance(rule, behavior.Rule):
        raise ValueError("插件口径必须是一条 behavior.Rule")
    if rule.kind != behavior.DERIVED:
        raise ValueError(f"「{rule.title}」不是可重算的派生口径 —— 只有 derived 能进这张表")
    ids = [v.id for v in rule.variants]
    if len(ids) < 2 or len(ids) != len(set(ids)):
        raise ValueError(f"「{rule.title}」至少要两种且不重名的做法，影子才有另一侧可比")
    if rule.default not in ids:
        raise ValueError(f"「{rule.title}」的默认位必须是自己的某个做法")
    if not (rule.title and rule.question):
        raise ValueError("口径的 title / question 不能为空（界面上要给用户看原话）")
    if rule.key in {r.key for r in behavior.RULES}:
        raise ValueError(f"口径 key 撞了已有的：{rule.key}")
    behavior.RULES = behavior.RULES + (rule,)
    _RULE_KEYS.append(rule.key)
    if compare_fn is not None:
        behavior.register_compare(rule.key, compare_fn)


# ---------------------------------------------------------------- 装卸（进程内）
def _reset(app: FastAPI) -> None:
    """卸干净：本 app 的插件路由、插件口径、模块缓存（重复装配 / 卸载前的必经一步）。"""
    for route in getattr(app.state, "plugin_routes", []):
        with suppress(ValueError):  # 已经不在了（例如路由表被整体重建）—— 不纠缠
            app.router.routes.remove(route)
    app.state.plugin_routes = []
    behavior.RULES = _ORIGINAL_RULES
    _RULE_KEYS.clear()
    for name in _MODULES:
        sys.modules.pop(name, None)
    _MODULES.clear()


def _err(plugin: str, stage: str, exc: BaseException) -> dict[str, str]:
    return {"plugin": plugin, "stage": stage, "detail": f"{type(exc).__name__}: {exc}"}


def _hoist_before_mounts(app: FastAPI, added: list[Any]) -> None:
    """把插件加的路由挪到**第一个 mount 之前**。

    为什么必须有这一步：`create_app()` 最后会 `mount("/", StaticFiles...)` 兜住一切 ——
    独立补装（`apply` 在建 app 之后被调）追加的路由排在 mount 后面，**永远轮不到**。
    """
    for route in added:
        app.router.routes.remove(route)
        idx = next(
            (i for i, r in enumerate(app.router.routes) if isinstance(r, Mount)),
            len(app.router.routes),
        )
        app.router.routes.insert(idx, route)


def _hook_routes(
    app: FastAPI, conn: sqlite3.Connection, module: types.ModuleType,
    plugin: str, report: dict[str, Any],
) -> None:
    """调插件的 `register_routes(app, conn)`；失败 / 撞已有路径都拆干净并报出来。"""
    before = len(app.router.routes)
    try:
        module.register_routes(app, conn)
    except Exception as exc:  # noqa: BLE001 —— 坏插件要原样报出来，不许它带崩服务
        del app.router.routes[before:]
        report["errors"].append(_err(plugin, "routes", exc))
        return
    added = list(app.router.routes[before:])
    taken = {getattr(r, "path", None) for r in app.router.routes[:before]}
    clash = [str(getattr(r, "path", "")) for r in added if getattr(r, "path", None) in taken]
    if clash:
        # 撞已有路径 = 遮挡老行为 → 拆掉（既有契约不许被插件改写）
        del app.router.routes[before:]
        report["errors"].append(
            _err(plugin, "routes", ValueError(f"路由路径撞了已有接口：{', '.join(clash)}"))
        )
        return
    app.state.plugin_routes.extend(added)
    _hoist_before_mounts(app, added)
    report["routes"].extend(str(getattr(r, "path", "")) for r in added)


def _hook_rules(module: types.ModuleType, plugin: str, report: dict[str, Any]) -> None:
    try:
        module.register_rules(_add_rule)
    except Exception as exc:  # noqa: BLE001 —— 同上：报出来，不静默
        report["errors"].append(_err(plugin, "rules", exc))


def _install_status_route(app: FastAPI) -> None:
    def plugin_status() -> dict[str, Any]:
        """插件装配现状（卡 229：坏插件在这里原样可见，不静默吞）。"""
        return dict(getattr(app.state, "plugins", {}))

    app.add_api_route(STATUS_ROUTE, plugin_status, methods=["GET"])
    status_route = app.router.routes[-1]
    app.state.plugin_routes.append(status_route)
    _hoist_before_mounts(app, [status_route])


# ---------------------------------------------------------------- 装配入口
def default_paths() -> list[Path]:
    """`TIMEFLOW_PLUGINS` 解析成插件文件清单；没设 = 一个都不装（零配置 = 零变化）。"""
    raw = os.environ.get(ENV_KEY, "")
    specs = [s.strip() for s in raw.split(os.pathsep) if s.strip()]
    return _expand(specs)


def _expand(specs: list[str]) -> list[Path]:
    out: list[Path] = []
    seen: set[Path] = set()
    for spec in specs:
        path = Path(spec)
        files = sorted(path.glob("*.py")) if path.is_dir() else [path]
        for f in files:
            resolved = f.resolve()
            if resolved in seen or f.name.startswith("_"):
                continue
            seen.add(resolved)
            out.append(resolved)
    return out


def _import_plugin(path: Path, errors: list[dict[str, str]]) -> types.ModuleType | None:
    """按文件导入插件模块；导入即炸的坏插件报进 errors（stage=import），返回 None。"""
    global _SEQ
    _SEQ += 1
    name = f"_timeflow_plugin_{_SEQ:03d}_{path.stem}"
    try:
        spec = importlib.util.spec_from_file_location(name, str(path))
        if spec is None or spec.loader is None:
            raise ImportError(f"不是可导入的 Python 文件：{path.name}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module  # 官方配方：dataclass 等机制依赖这一步
        spec.loader.exec_module(module)
        _MODULES[name] = module
        return module
    except Exception as exc:  # noqa: BLE001 —— 导入失败是"看得见的失败"，不是服务故障
        sys.modules.pop(name, None)
        errors.append(_err(str(path), "import", exc))
        return None


def apply(app: FastAPI, conn: sqlite3.Connection, paths: list[str] | None = None) -> dict[str, Any]:
    """声明式装配：「现在装的就是这一组」。

    先卸干净（进程内路由 / 口径 / 模块缓存），再逐个装；报告原样返回，
    同时挂在 `app.state.plugins` 与 `GET /api/plugins` 上。
    `paths=None` 时读 `TIMEFLOW_PLUGINS`；`create_app()` 传的就是它。
    """
    _reset(app)
    report: dict[str, Any] = {
        "loaded": [], "errors": [], "routes": [], "rules": [], "env_key": ENV_KEY,
    }
    for path in (_expand(paths) if paths is not None else default_paths()):
        module = _import_plugin(path, report["errors"])
        if module is None:
            continue
        plugin = str(path)
        hooks = [h for h in _HOOKS if hasattr(module, h)]
        if not hooks:
            msg = "一个钩子都没声明（register_routes / register_rules）"
            report["errors"].append(_err(plugin, "hooks", ValueError(msg)))
            continue
        n_err = len(report["errors"])
        if "register_routes" in hooks:
            _hook_routes(app, conn, module, plugin, report)
        if "register_rules" in hooks:
            _hook_rules(module, plugin, report)
        if len(report["errors"]) == n_err:
            report["loaded"].append(plugin)
    report["rules"] = list(_RULE_KEYS)
    app.state.plugins = report
    _install_status_route(app)
    logs.log_event("plugins_applied", loaded=len(report["loaded"]), errors=len(report["errors"]))
    return report


def uninstall(app: FastAPI) -> None:
    """卸载：拆掉本 app 的插件路由、收回插件口径、清模块缓存 —— 回到没装过的原样。

    `/api/plugins` 这面状态墙保留（清空后的报告 = 出厂时的样子）；
    彻底不要这条路径 = 不走 `apply`（`create_app()` 总会调它）。
    """
    _reset(app)
    app.state.plugins = {
        "loaded": [], "errors": [], "routes": [], "rules": [], "env_key": ENV_KEY,
    }
    _install_status_route(app)
    logs.log_event("plugins_uninstalled")


#: 供判据直接验护栏用的别名（`tests/test_plugins.py`）。
add_rule: Callable[..., None] = _add_rule
