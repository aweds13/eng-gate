"""CLI 的命令清单 —— **每条都挂到命令表里的一条操作上**。

这个文件是「CLI 也是那张表的投影」这句话的落点：一条命令 =
`(名字, 契约 OP, 路由, 参数, 排版)`。`scripts/check_commands.py` 逐条核对：
那条 OP **在**命令表里、那条路由**是**那条 OP 的、名字不重复、表里的 `cli` 字段
与这里**双向**对得上。对不上就门禁红 —— 所以这里不可能悄悄长出一套"命令表里没有的命令"。

## 只读与写入（T-G64 建 → T-G65 加写入）

- `COMMANDS`：**只读**那批（14 条），硬口径是「每条路由都是 `GET`」—— 在 T-G64 那一版里
  写操作还排在后面等 AI 边界口径；
- `WRITE_COMMANDS`：**写**那批（6 条，T-G65）。用户 2026-09-25 定的口径三条：
  ① 只做**界面上已有的那些**（所以每条写命令的 OP 的 `ui` 必须非空，由门禁判）；
  ② **默认关** —— 每次调用都要显式带 `--allow-write`（见 `main.py`，那里有机器判据）；
  ③ 语义**与界面完全一样**（不发明第二套写法）。

★ **"这条是不是写"没有第二个字段**：直接由**路由方法**算（`GET` 之外都是写）。
   多一个 `write = true` 就是第二个真源，早晚与路由漂开 —— 门禁那边也是按方法判的。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from timeflow.cli import render

if TYPE_CHECKING:  # pragma: no cover —— 只为类型注解
    from collections.abc import Callable

#: 只读命令只认这个方法（写命令走别的方法，见 `is_write`）
READ_METHOD = "GET"


@dataclass(frozen=True)
class Param:
    """一个参数（也是 MCP 的 tool schema 里那一行）。

    `where` 决定它去哪儿 —— 这条是"边界原样"的一部分：路径参数进 URL、查询参数进 query、
    别的进 JSON body。**不猜**：写在命令表里，由门禁核对（写命令的 body 参数必须真被那条路由收下）。
    """

    name: str
    kind: str  # "int" | "str" | "bool"
    help: str
    default: str | None = None
    where: str = "query"  # "query" | "path" | "body"

    @property
    def required(self) -> bool:
        """**路径参数**没有默认值就是必填（它是 URL 的一部分，缺了那条路根本不是那条路）。

        为什么只对路径参数这么判：查询参数里有一批"边界自己有默认"的（`days` 默认 14、
        `view` 默认普通视图），把它们标成必填就与边界打架了 —— 边界才是唯一的校验处。
        """
        return self.where == "path" and self.default is None


@dataclass(frozen=True)
class Command:
    name: str
    op: str  # 契约 OP（机器核对：必须在 docs/commands.toml 里）
    route: str  # "GET /api/…"（机器核对：必须是那条 OP 的路由之一）
    title: str  # 一句话（人读帮助 + MCP 的工具描述）
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
        title="现在有没有在专注",
        human=render.focus,
    ),
    Command(
        name="board",
        op="OP-33",
        route="GET /api/team/board",
        title="团队视角（管理者 / 执行者）",
        human=render.board,
        params=(
            Param("view", "str", "manager（默认）/ executor"),
            Param("me", "str", "执行者视角的名字"),
        ),
    ),
    Command(
        name="sync",
        op="OP-41",
        route="GET /api/sync/status",
        title="同步现状",
        human=render.check,
    ),
)


WRITE_COMMANDS: tuple[Command, ...] = (
    Command(
        name="add-task",
        op="OP-1",
        route="POST /api/tasks",
        title="新建任务（默认不进今天的清单）",
        human=lambda data: render.receipt(data, "已新建任务"),
        params=(
            Param("title", "str", "任务标题（必填）", where="body"),
            Param("due_date", "str", "截止日 YYYY-MM-DD", where="body"),
            Param("group_name", "str", "分组名", where="body"),
            Param("is_myday", "bool", "直接放进今天的清单", "false", where="body"),
            Param("priority", "str", "优先级：高 / 中 / 低", "中", where="body"),
            Param("note", "str", "备注", where="body"),
            Param("flagged", "bool", "标星", "false", where="body"),
        ),
    ),
    Command(
        name="complete",
        op="OP-5",
        route="POST /api/tasks/{task_id}/complete",
        title="完成任务",
        human=lambda data: render.receipt(data, "已完成任务"),
        params=(Param("task_id", "str", "任务 id", where="path"),),
    ),
    Command(
        name="myday",
        op="OP-2",
        route="POST /api/tasks/{task_id}/myday",
        title="把任务放进 / 移出今天的清单",
        human=lambda data: render.receipt(data, "已切换今天的清单"),
        params=(Param("task_id", "str", "任务 id", where="path"),),
    ),
    Command(
        name="focus-start",
        op="OP-3",
        route="POST /api/focus/start",
        title="开始专注",
        human=lambda data: render.receipt(data, "专注已开始"),
        params=(
            Param("kind", "str", "tomato（番茄钟）/ plain（正计时）", "tomato", where="body"),
            Param("task_id", "str", "挂到哪个任务上", where="body"),
        ),
    ),
    Command(
        name="focus-finish",
        op="OP-4",
        route="POST /api/focus/{session_id}/finish",
        title="结束专注 / 放弃 / 记中断",
        human=lambda data: render.receipt(data, "专注已结束"),
        params=(
            Param("session_id", "str", "专注 id", where="path"),
            Param("duration_sec", "int", "这次专注多少秒", "0", where="body"),
            Param(
                "status",
                "str",
                "finished（结束，计入投入）/ abandoned（放弃）/ interrupted（记中断）",
                "finished",
                where="body",
            ),
        ),
    ),
    Command(
        name="memo",
        op="OP-35",
        route="POST /api/memos",
        title="随手记一条",
        human=lambda data: render.receipt(data, "已记下"),
        params=(
            Param("text", "str", "记什么（必填）", where="body"),
            Param("task_id", "str", "挂到某个任务上", where="body"),
            Param("ref_handle", "str", "引用句柄", where="body"),
        ),
    ),
)


def all_commands() -> tuple[Command, ...]:
    """只读 + 写（顺序按契约表里的次序感：先读后写）。"""
    return COMMANDS + WRITE_COMMANDS


def is_write(command: Command) -> bool:
    """写命令 = 路由方法不是 `GET`。★ 唯一真源就是路由本身（不加 `write = true` 那种字段）。"""
    return not command.route.startswith(f"{READ_METHOD} ")


def method_of(command: Command) -> str:
    return command.route.partition(" ")[0]


def by_name() -> dict[str, Command]:
    return {command.name: command for command in all_commands()}


def names() -> list[str]:
    return [command.name for command in all_commands()]


def read_names() -> list[str]:
    return [command.name for command in COMMANDS]


def write_names() -> list[str]:
    return [command.name for command in WRITE_COMMANDS]
