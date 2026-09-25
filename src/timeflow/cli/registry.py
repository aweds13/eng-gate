"""CLI 的命令清单 —— **每条都挂到命令表里的一条只读操作上**。

这个文件是「CLI 也是那张表的投影」这句话的落点：一条命令 =
`(名字, 契约 OP, 路由, 参数, 排版)`。`scripts/check_commands.py` 逐条核对：
那条 OP **在**命令表里、那条路由**是**那条 OP 的、OP 的 `kind` **是** read/derive、
路由方法**是** GET、名字不重复、表里的 `cli` 字段与这里**双向**对得上。
对不上就门禁红 —— 所以这里不可能悄悄长出一套"命令表里没有的命令"。

**只读**是硬口径（T-G30 §4.3 第 2 步）：写操作 CLI 排最后，要等 AI 边界口径
（用户已定"AI 只写事实"）。所以这里每条路由都必须是 `GET`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from timeflow.cli import render

if TYPE_CHECKING:  # pragma: no cover —— 只为类型注解
    from collections.abc import Callable

#: 路由方法白名单：只读 CLI 只认 GET（写操作 CLI 是另一张卡）
READ_METHOD = "GET"


@dataclass(frozen=True)
class Param:
    """一个查询参数（也是 MCP 的 tool schema 里那一行）。"""

    name: str
    kind: str  # "int" | "str"
    help: str
    default: str | None = None


@dataclass(frozen=True)
class Command:
    name: str
    op: str  # 契约 OP（机器核对：必须在 docs/commands.toml 里）
    route: str  # "GET /api/…"（机器核对：必须是那条 OP 的路由之一）
    title: str  # 一句话（人读帮助 + 以后 MCP 的工具描述）
    human: Callable[[Any], list[str]]  # 人读排版（只排版）
    params: tuple[Param, ...] = field(default=())


COMMANDS: tuple[Command, ...] = (
    Command(
        name="today",
        op="OP-7",
        route="GET /api/summary",
        title="今日摘要：专注 / 手动投入 / 复习 / 产出 / 习惯 / 债务",
        human=render.today,
    ),
    Command(
        name="plan",
        op="OP-28",
        route="GET /api/mydays",
        title="今天的清单（My Day）",
        human=render.plan,
    ),
    Command(
        name="overdue",
        op="OP-16",
        route="GET /api/overdue",
        title="逾期项",
        human=render.overdue,
    ),
    Command(
        name="due",
        op="OP-28",
        route="GET /api/review/due",
        title="今天到期的复习卡",
        human=render.due,
    ),
    Command(
        name="done",
        op="OP-48",
        route="GET /api/today/done",
        title="今天做成了什么（任务 / 步骤 / 产出）",
        human=render.done,
        params=(Param("day", "str", "看哪一天（YYYY-MM-DD，默认今天）"),),
    ),
    Command(
        name="week",
        op="OP-15",
        route="GET /api/summary/weekly",
        title="周结算（周一起算）+ 逐日走势",
        human=render.week,
        params=(Param("week_of", "str", "该周任意一天（YYYY-MM-DD，默认本周）"),),
    ),
    Command(
        name="trend",
        op="OP-15",
        route="GET /api/insights/daily",
        title="近 N 天逐日时序",
        human=render.trend,
        params=(Param("days", "int", "看多少天（1~90，默认 14）", "14"),),
    ),
    Command(
        name="habits",
        op="OP-19",
        route="GET /api/habits",
        title="习惯列表（连续天数 + 打卡天数）",
        human=render.habits,
    ),
    Command(
        name="check",
        op="OP-20",
        route="GET /api/selfcheck",
        title="自检（本周专注 / 债务 / 习惯打卡）",
        human=render.check,
    ),
    Command(
        name="tasks",
        op="OP-45",
        route="GET /api/tasks",
        title="任务列表（可选智能视图）",
        human=render.tasks,
        params=(Param("view", "str", "智能视图：important / planned / flagged"),),
    ),
    Command(
        name="upcoming",
        op="OP-25",
        route="GET /api/assessments/upcoming",
        title="临期与逾期考核项（只列未录成绩的）",
        human=render.upcoming,
        params=(Param("days", "int", "看多少天内（0~365，默认 14）", "14"),),
    ),
    Command(
        name="focus",
        op="OP-51",
        route="GET /api/focus/active",
        title="现在有没有在专注（没有就是没有）",
        human=render.focus,
    ),
    Command(
        name="board",
        op="OP-33",
        route="GET /api/team/board",
        title="团队视角（管理者 / 执行者，同一份分配记录）",
        human=render.board,
        params=(
            Param("view", "str", "manager（默认）/ executor"),
            Param("me", "str", "执行者视角要一个名字（本工具没有账号体系）"),
        ),
    ),
    Command(
        name="sync",
        op="OP-41",
        route="GET /api/sync/status",
        title="同步现状（只报事实；网络那条路没做就如实说没做）",
        human=render.check,
    ),
)


def by_name() -> dict[str, Command]:
    return {command.name: command for command in COMMANDS}


def names() -> list[str]:
    return [command.name for command in COMMANDS]
