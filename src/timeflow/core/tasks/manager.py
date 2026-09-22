"""任务管理领域逻辑。对应 SR-F1.1~F1.9（My Day / 状态机 / 分组 / 子任务 / Repeat / 逾期）。

纯领域逻辑，不碰 SQL（sqlite 由 storage 层处理，本层用连接对象）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

from timeflow.core import attach as attach_mod
from timeflow.core import behavior

STATUS_TODO = "未开始"
STATUS_DOING = "进行中"
STATUS_DONE = "完成"
STATUS_OVERDUE = "逾期"
STATUS_CANCELLED = "取消"
STATUS_ARCHIVED = "归档"
STATUS_DELETED = "已删"
# 「待定」（F 批 · T-F1；用户 2026-09-21 定的新状态）：
# 「闲置或者挂在那儿、没放弃、不计债」—— **不叫「悬赏」**（那个词在约定层已经是"完成收益"的意思，
# 不能一词两义）。行为同「取消」：不进 My Day、不提醒、不参与债务，但仍在「全部任务」里看得见。
STATUS_PENDING = "待定"

VALID_STATUS = {
    STATUS_TODO,
    STATUS_DOING,
    STATUS_DONE,
    STATUS_OVERDUE,
    STATUS_CANCELLED,
    STATUS_ARCHIVED,
    STATUS_DELETED,
    STATUS_PENDING,
}

# 默认视图（列表 / My Day / 逾期 / 债务）不可见的状态：归档 + 已删（软删除）。
HIDDEN_STATUSES = (STATUS_ARCHIVED, STATUS_DELETED)

# 「搁置类」状态：**不计债、不进 My Day、不提醒**，但仍在「全部任务」里看得见（留痕，不是消失）。
# 依据：`复盘/口径定案-待定清单.md` §1 —— 用户 2026-09-21 定「待定」计债务吗 → 不计债，
# 行为同「取消」。债务由 `overdue_tasks` 派生（`ledger.summary`），所以在这里排除就等于不计债。
PARKED_STATUSES = (STATUS_CANCELLED, STATUS_PENDING)

# 「进行中」的排序号口径（T-F1）：序号小的排前面；没排过序的（NULL）排最后。
_DOING_ORDER_BY = " ORDER BY doing_rank IS NULL, doing_rank, updated_at"

# **谁建的**（G 批 · T-G6，口径见 `复盘/口径定案-待定清单.md` §2 乙案）：
# `me` = 你（界面/手工建的，也是**默认**）；`ai` = 只有 `/api/ai/*` 那条路会写。
# 判据是"**动的是不是你亲手写的东西**"：AI 只能勾自己建的，不许碰你建的 —— 所以这个值
# 必须落在字段上（约定拦不住代码），但不参与任何排序/统计，只做归属与边界判断。
CREATOR_ME = "me"
CREATOR_AI = "ai"
VALID_CREATORS = (CREATOR_ME, CREATOR_AI)
CREATOR_LABELS = {CREATOR_ME: "我建的", CREATOR_AI: "AI 建的"}

# 事实的 `source` 口径（T-G6）：「这件事是谁做的」——人做的沿用历史值 `desktop`（**不改历史含义**），
# AI 接口做的记 `ai`。于是"AI 干过什么"在事实层一次查询就能捞出来，而不是只能看当前状态。
ACTOR_SOURCES = {CREATOR_ME: "desktop", CREATOR_AI: "ai"}

# 优先级（SR-F1.2 / 段2 决策）：只有三档，**默认「中」**；不做 1–5 数字分级，也不做拖拽排序。
PRIORITY_HIGH = "高"
PRIORITY_MID = "中"
PRIORITY_LOW = "低"
VALID_PRIORITIES = (PRIORITY_HIGH, PRIORITY_MID, PRIORITY_LOW)
DEFAULT_PRIORITY = PRIORITY_MID
_PRIORITY_RANK = {PRIORITY_HIGH: 0, PRIORITY_MID: 1, PRIORITY_LOW: 2}

# 任务类型 + 所属课程（SR-F5.4 学校任务带课程标签 / T-C12，用户 2026-09-19 要求）。
# 词表**复用 `course_assessments.name` 已有的四种学校事项**（考试/作业/论文/小测）+ 普通，
# 不另造一套说法；只有「非普通」才允许挂课程 —— 挂了课程就意味着这件事属于某门课。
TASK_TYPE_NORMAL = "普通"
VALID_TASK_TYPES = (TASK_TYPE_NORMAL, "作业", "考试", "论文", "小测")
DEFAULT_TASK_TYPE = TASK_TYPE_NORMAL
COURSE_TASK_TYPES = tuple(t for t in VALID_TASK_TYPES if t != TASK_TYPE_NORMAL)

# 排序口径（三处统一：列表 / My Day / 逾期）：**截止日 → 优先级 → 创建时间**；无截止日排最后。
# 写成 SQL 片段是为了让三处用**同一份**口径，避免"各视图各排各的"（那正是 SR-F1.2 要收的口子）。
_ORDER_BY = (
    " ORDER BY due_date IS NULL, due_date,"
    " CASE priority WHEN '高' THEN 0 WHEN '中' THEN 1 WHEN '低' THEN 2 ELSE 1 END,"
    " created_at"
)

# 三个智能视图（SR-F1.3 / T-B3）：口径写在**领域层**，界面只负责显示
# （免得同一套筛选在前端/后端/测试三处各写一遍）。
VIEW_IMPORTANT = "important"
VIEW_PLANNED = "planned"
VIEW_FLAGGED = "flagged"
# 视图 → SQL 条件（取自白名单，不拼用户输入）
_VIEW_WHERE = {
    VIEW_IMPORTANT: "priority = '高'",
    VIEW_PLANNED: "due_date IS NOT NULL",
    VIEW_FLAGGED: "flagged = 1",
}
VALID_VIEWS = tuple(_VIEW_WHERE)


@dataclass
class Task:
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
    # 备注（SR-F1.4 / T-B1）：人写的说明，列表不显示、详情面板可写（渐进聚焦）。
    # 默认值放在最后，老代码按位置构造 Task 也不会被破坏。
    note: str | None = None
    # 优先级（SR-F1.2 / T-B2）：高/中/低，默认「中」。
    priority: str = DEFAULT_PRIORITY
    # 手动标记（SR-F1.3 / T-B3）：用户自己按的标记位，Flagged 视图就是它。
    flagged: bool = False
    # 附件 / 要求链接（SR-F1.4 / T-B4）：元素 `{target, title}`；打开规则见 core/attach.py。
    attach: list[dict[str, str | None]] = field(default_factory=list)
    # 提醒（SR-F1.4 / T-B5）：本地时间字符串 `YYYY-MM-DDTHH:MM`，可空=不提醒。
    remind_at: str | None = None
    # 任务类型（SR-F5.4 / T-C12）：普通/作业/考试/论文/小测，默认「普通」。
    task_type: str = DEFAULT_TASK_TYPE
    # 所属课程（SR-F5.4 / T-C12）：指向 `courses.id`；只有非「普通」才能挂（`_check_course_pair`）。
    course_id: str | None = None
    # 「进行中」的显式顺序（F 批 · T-F1）：序号小的排前面；非「进行中」一律 NULL。
    # 由领域层维护（`start_task` / `move_doing`），不走 `update_task` 的字段白名单。
    doing_rank: int | None = None
    # **谁建的**（G 批 · T-G6）：`me`（你）/ `ai`（AI 接口建的）。
    # 这是 AI 边界的**判据**（用户 2026-09-21 乙案：AI 只能动它自己建的东西），
    # 不是界面装饰 —— 所以它由创建路径写死，**不给人手改**、也不进 PATCH 白名单。
    created_by: str = CREATOR_ME


def _row_to_task(row: sqlite3.Row) -> Task:
    keys = set(row.keys())
    return Task(
        id=row["id"],
        title=row["title"],
        due_date=row["due_date"],
        group_name=row["group_name"],
        repeat_days=row["repeat_days"],
        parent_id=row["parent_id"],
        is_myday=bool(row["is_myday"]),
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        version=row["version"],
        # 缺列兜底：迁移（v6/v7/v8）已保证列存在，但残缺库/手工建的测试库可能没有
        note=row["note"] if "note" in keys else None,
        priority=row["priority"] if "priority" in keys else DEFAULT_PRIORITY,
        flagged=bool(row["flagged"]) if "flagged" in keys else False,
        attach=attach_mod.load_attach(row["attach"]) if "attach" in keys else [],
        remind_at=row["remind_at"] if "remind_at" in keys else None,
        task_type=(
            row["task_type"] if "task_type" in keys and row["task_type"] else DEFAULT_TASK_TYPE
        ),
        course_id=row["course_id"] if "course_id" in keys else None,
        doing_rank=row["doing_rank"] if "doing_rank" in keys else None,
        # 缺列兜底：v16 之前建的库没有这列 —— 那些行都是"我建的"（不猜成 AI）
        created_by=(
            str(row["created_by"])
            if "created_by" in keys and row["created_by"] in VALID_CREATORS
            else CREATOR_ME
        ),
    )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _today() -> str:
    return date.today().isoformat()


def _check_creator(value: object) -> str:
    """`created_by` 只有两档（我 / AI）—— 别的一律拒绝。

    不静默当"我建的"：那会**悄悄放宽 AI 边界**（AI 传个怪值就被当成自己的东西）。
    """
    text = str(value or "").strip()
    if text not in VALID_CREATORS:
        raise ValueError(
            f"created_by 只能是 {VALID_CREATORS[0]}（我建的）"
            f"或 {VALID_CREATORS[1]}（AI 建的）：{value!r}"
        )
    return text


def _check_priority(value: object) -> str:
    """优先级只有三档（高/中/低）—— 别的一律拒绝，不静默降级（避免"设了高却没生效"）。"""
    if value not in VALID_PRIORITIES:
        raise ValueError(f"非法优先级: {value}（只能是 高/中/低）")
    return str(value)


def _check_task_type(value: object) -> str:
    """任务类型只有五档（普通/作业/考试/论文/小测）—— 非法值拒绝，不静默降级成普通。

    为什么拒绝而不是回落默认值：用户明确选了「作业」却存成「普通」，他会以为绑定生效了。
    """
    if value is None or str(value).strip() == "":
        raise ValueError(f"任务类型不能为空（只能是 {'/'.join(VALID_TASK_TYPES)}）")
    text = str(value).strip()
    if text not in VALID_TASK_TYPES:
        raise ValueError(f"非法任务类型: {value}（只能是 {'/'.join(VALID_TASK_TYPES)}）")
    return text


def _check_course_pair(conn: sqlite3.Connection, task_type: str, course_id: object) -> str | None:
    """校验「类型 ↔ 课程」这一对，返回规整后的 course_id。**按合并后的最终状态校验**。

    规则（T-C12）：
    - 空值 = 不挂课程（存 NULL，不写空串）；
    - 挂了课程就必须存在（拒绝拼错的 id，不写进库）；
    - **只有非「普通」类型才允许挂课程** —— 挂了课程这件事本身就在说"它属于某门课"，
      「普通」是"与课程无关"，两者不能同时成立。这里拒绝而不是偷偷清掉课程：
      清掉是静默数据丢失，用户会以为保存成功了。
    """
    text = None if course_id is None else str(course_id).strip()
    if not text:
        return None
    if task_type == TASK_TYPE_NORMAL:
        kinds = "/".join(COURSE_TASK_TYPES)
        raise ValueError(f"「{TASK_TYPE_NORMAL}」类型不挂课程：请把类型改成 {kinds}，或清空课程")
    row = conn.execute("SELECT 1 FROM courses WHERE id = ?", (text,)).fetchone()
    if row is None:
        raise ValueError(f"课程不存在: {text}（先到学业页建课程，或清空课程选择）")
    return text


def course_name(conn: sqlite3.Connection, course_id: str | None) -> str | None:
    """课程 id → 课程名（只用于显示）。课程已删 → None（**任务不跟着消失**，显示「课程已删」）。"""
    if not course_id:
        return None
    row = conn.execute("SELECT name FROM courses WHERE id = ?", (course_id,)).fetchone()
    return str(row["name"]) if row is not None else None


# 提醒时间：本地时间字符串 `YYYY-MM-DDTHH:MM`（前端 datetime-local 就是这个形状）。
# 为什么不用 UTC：本项目全部日期口径都是**本地时间**（见 U-07「日期框默认今天」的教训，
# 用 UTC 会在东八区晚上差一天）；提醒要跟着用户的钟表走。
_REMIND_FORMATS = ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S")


def _check_remind_at(value: object) -> str | None:
    """校验并规整提醒时间。空值 = 清除提醒（存 NULL，不写空串）；非法值拒绝（不猜、不静默忽略）。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in _REMIND_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%dT%H:%M")
        except ValueError:
            continue
    raise ValueError(f"提醒时间格式不对: {value}（要「2026-09-20 08:30」这样的日期+时间）")


def reminder_state(task: Task, now: datetime | None = None) -> str | None:
    """提醒的**界面口径**（一处定义，卡片/详情/自检都用它）：`over` / `today` / `soon` / `later`。

    - `over`  = 已经到点或过点（该提醒了）；
    - `today` = 今天稍后；
    - `soon`  = 7 天内；
    - `later` = 更远；
    - `None`  = 没设提醒 / 任务已完成或已搁置（完成后不再催——**不打扰**是基调）。
    为什么放领域层：这是"什么时候算该提醒"的**口径**，写在前端就会和通知通道各算一套。
    """
    if not task.remind_at or task.status in (STATUS_DONE, *PARKED_STATUSES, *HIDDEN_STATUSES):
        return None
    now = now or datetime.now()
    try:
        when = datetime.fromisoformat(task.remind_at)
    except ValueError:
        return None
    delta_days = (when.date() - now.date()).days
    if when <= now:
        return "over"
    if delta_days == 0:
        return "today"
    if delta_days <= 7:
        return "soon"
    return "later"


def _created_date(task: Task) -> date | None:
    """任务创建日（只取 `created_at` 的日期部分）；解析不出来返回 `None`（不猜、不崩）。"""
    try:
        return date.fromisoformat(task.created_at[:10])
    except (TypeError, ValueError):
        return None


def _is_stale_undated_myday(task: Task, today: date) -> bool:
    """**无截止日、但昨天（或更早）就该做的 My Day 任务** —— AC-4 补充口径里的那种"老账"。

    T-F8（用户 2026-09-21 定案 A）：这类任务**算一笔债务**，天数**从创建日算起**
    —— 它本来就是"昨天没做完"才进逾期栏的，`created_at` 是它身上唯一可用的日期。

    这个判定被 `overdue_tasks()`（要不要列进逾期栏）和 `overdue_days()`（算几天）
    **共用**：T-F8 的缺陷正是这两处各判各的 —— 列进去了、天数字段却硬返回 0，
    于是摘要行写「逾期共 1 项」而明细一条都列不出来。

    注意 `created_at` 只是**近似**（近似"它什么时候进的 My Day"）：`tasks` 表没有记
    "哪天被放进 My Day"，这是 AC-4 落地时就有的近似，本卡只是让天数与"是否入选"同源。
    """
    if task.due_date is not None or not task.is_myday:
        return False
    if task.status == STATUS_DONE or task.status in PARKED_STATUSES:
        return False
    if task.status in HIDDEN_STATUSES:
        return False
    created = _created_date(task)
    return created is not None and created < today


def overdue_days(task: Task, today: str | None = None) -> int:
    """**派生**的逾期天数（F 批 · T-F7；无截止日的 My Day 老账见 T-F8）：
    `0` = 没逾期，否则 = 已逾期多少天。

    为什么要派生、而不是把 `逾期` 写回 `status`（T-F7 的修法选择）：
    - `overdue_tasks()` 早就是**派生**的（AC-4/AC-5：截止日过了就进逾期栏），
      「完成 N 天后进档案」也是派生的（T-F2）—— 再搞一套"到点改状态"的写入 = 两套真相，
      还要一个定时器/惰性写入点（本项目明确避免定时任务）；
    - 真正的问题是**详情面板自相矛盾**：字段写着「未开始」、界面却把它列在逾期栏里标红。
      修法是让**显示也走同一个派生口径**（`TaskOut.overdue_days`），而不是把 6 个地方写状态。
    - 口径：已完成 / 已搁置（取消·待定）/ 归档 / 已删 → 0（逾期只对"还在手上的事"有意义）；
      截止日 < 今天 → 相差天数；**没截止日的 My Day 老账 → 从创建日算起**（T-F8 定案 A），
      其它没截止日的 → 0。**不计折算**，只报天数（债务=天数/程度）。

    不变式（T-F8 要保的就是这条）：`overdue_days(t) > 0` ⟺ `t` 在 `overdue_tasks()(t)` 里。
    """
    if task.status == STATUS_DONE or task.status in PARKED_STATUSES:
        return 0
    if task.status in HIDDEN_STATUSES:
        return 0
    t = today or _today()
    today_d = date.fromisoformat(t)
    if task.due_date is not None:
        if task.due_date >= t:
            return 0
        return (today_d - date.fromisoformat(task.due_date)).days
    if _is_stale_undated_myday(task, today_d):
        created = _created_date(task)
        if created is not None:
            return (today_d - created).days
    return 0


def due_reminders(conn: sqlite3.Connection, now: datetime | None = None) -> list[Task]:
    """到点该提醒的任务（T-B5）：`remind_at <= now` 且任务还"活着"（非完成/搁置/归档/已删）。

    按提醒时间正序 —— 越早该提醒的越靠前。**只读**：不改任务、不发事实
    （通知只是"把已知时间说出来"，不改变任何账目）。
    """
    moment = (now or datetime.now()).strftime("%Y-%m-%dT%H:%M")
    rows = conn.execute(
        "SELECT * FROM tasks WHERE remind_at IS NOT NULL AND remind_at <= ? "
        "AND status NOT IN (?,?,?,?,?) ORDER BY remind_at",
        (moment, STATUS_DONE, *PARKED_STATUSES, *HIDDEN_STATUSES),
    ).fetchall()
    return [_row_to_task(r) for r in rows]


def create_task(
    conn: sqlite3.Connection,
    title: str,
    due_date: str | None = None,
    group_name: str | None = None,
    repeat_days: int | None = None,
    parent_id: str | None = None,
    is_myday: bool = False,
    note: str | None = None,
    priority: str = DEFAULT_PRIORITY,
    flagged: bool = False,
    attach: list[dict[str, str | None]] | None = None,
    remind_at: str | None = None,
    task_type: str = DEFAULT_TASK_TYPE,
    course_id: str | None = None,
    created_by: str = CREATOR_ME,
) -> Task:
    """新建任务（AC-1）。校验标题非空；若 due 过去且未完成，初始状态标逾期。

    `created_by`（T-G6）只有两条路会传 `ai`：`core/ai.py` 的建任务/加步骤。界面与手工调用
    一律默认 `me` —— **默认值就是"你建的"**，这样"忘了传"只会更严（AI 边界不会因为漏传而放宽）。
    """
    title = title.strip()
    if not title:
        raise ValueError("任务标题不能为空")
    created_by = _check_creator(created_by)
    priority = _check_priority(priority)
    remind_at = _check_remind_at(remind_at)
    task_type = _check_task_type(task_type)
    course_id = _check_course_pair(conn, task_type, course_id)
    now = _now()
    task_id = uuid.uuid4().hex[:12]
    status = STATUS_TODO
    if due_date and due_date < _today():
        status = STATUS_OVERDUE
    conn.execute(
        """
        INSERT INTO tasks
        (id, title, due_date, group_name, repeat_days, parent_id, is_myday, status,
         created_at, updated_at, version, note, priority, flagged, attach, remind_at,
         task_type, course_id, created_by)
        VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?,?,?,?)
        """,
        (
            task_id,
            title,
            due_date,
            group_name,
            repeat_days,
            parent_id,
            int(is_myday),
            status,
            now,
            now,
            note,
            priority,
            int(bool(flagged)),
            attach_mod.dump_attach(attach_mod.load_attach(attach or [])),
            remind_at,
            task_type,
            course_id,
            created_by,
        ),
    )
    conn.commit()
    return get_task(conn, task_id)


def get_task(conn: sqlite3.Connection, task_id: str) -> Task:
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise KeyError(f"任务不存在: {task_id}")
    return _row_to_task(row)


def list_tasks(conn: sqlite3.Connection, active_only: bool = True) -> list[Task]:
    """任务列表（**按统一口径排序**：截止日 → 优先级 → 创建时间）。

    `active_only=True` 时排除「归档 / 已删（软删除）」**以及"完成满 N 天、已自动进档案"的**
    （T-F2：派生归档也算"不在默认视图里"，否则"过几天收走"这件事在列表上根本看不见）。
    回收站（`active_only=False`）也走同一排序，让"最近该处理的"排前面。
    """
    sql = "SELECT * FROM tasks"
    params: tuple[object, ...] = ()
    if active_only:
        sql += " WHERE status NOT IN (?,?)"
        params = HIDDEN_STATUSES
    rows = conn.execute(sql + _ORDER_BY, params).fetchall()
    tasks = [_row_to_task(r) for r in rows]
    return _hide_auto_filed(conn, tasks) if active_only else tasks


def tasks_in_view(conn: sqlite3.Connection, view: str) -> list[Task]:
    """智能视图（SR-F1.3 / T-B3）：`important` / `planned` / `flagged`。

    口径（**在领域层定死，界面不自己筛**）：
    - `important` = 优先级「高」（T-B2 的字段）；
    - `planned`   = **有截止日**（Planned 的本义是"排进日历的事"）；
    - `flagged`   = **手动标记位**（用户自己按的，不是自动推断"重要"）。
    基线同「全部任务」：只隐藏**归档 / 已删**（完成的仍如实显示；但**完成满 N 天已自动进档案的
    也不显示** —— 那也是"归档了"，见 T-F2），排序同统一口径。
    未知视图名 → ValueError（由 API 转 400），**不静默返回全部**（那会让人以为筛选生效了）。
    """
    if view not in _VIEW_WHERE:
        raise ValueError(f"未知视图: {view}（只能是 {'/'.join(VALID_VIEWS)}）")
    where = _VIEW_WHERE[view]  # 取自白名单字典，不含用户输入
    rows = conn.execute(
        f"SELECT * FROM tasks WHERE status NOT IN (?,?) AND {where}" + _ORDER_BY,  # noqa: S608
        HIDDEN_STATUSES,
    ).fetchall()
    return _hide_auto_filed(conn, [_row_to_task(r) for r in rows])


def update_task(
    conn: sqlite3.Connection, task_id: str, *, actor: str = CREATOR_ME, **fields: object
) -> Task:
    """更新任务字段（AC-2/AC-3）。只允许白名单字段，version+1，刷新 updated_at。

    第 2 步子任务 2：状态在「完成 ↔ 非完成」之间切换时发事实
    （完成发 `task.completed`，撤销发 `task.uncompleted`），使账本/联动只依赖事实层。
    `actor`（T-G6）：**谁做的**这件事 —— 只影响事实的 `source`（`ai` 就是 AI 接口做的），
    不影响任何字段与账本口径（同一条路、同一套规则，AI 不享受第二套算法）。
    """
    allowed = {
        "title",
        "due_date",
        "group_name",
        "repeat_days",
        "parent_id",
        "is_myday",
        "status",
        "note",
        "priority",
        "flagged",
        "attach",
        "remind_at",
        "task_type",
        "course_id",
    }
    # 注意：用"键在 payload 里"判断，而不是"值不是 None" ——
    # 否则 `parent_id=None` / `due_date=None` 这类**清空操作**会被静默忽略（实测踩到）。
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_task(conn, task_id)
    actor = _check_creator(actor)
    if "status" in updates and updates["status"] not in VALID_STATUS:
        raise ValueError(f"非法状态: {updates['status']}")
    if "priority" in updates:
        # 优先级**不可清空**（没有"无优先级"这一态）：非法/None 一律拒绝，不静默变默认值
        _check_priority(updates["priority"])
    if "flagged" in updates:
        # 布尔位统一收敛成 0/1（接口传的是 JSON true/false，这里再收一道，免得写进 1/"1"/None）
        updates["flagged"] = int(bool(updates["flagged"]))
    if "attach" in updates:
        # 附件列表：规整 + 落成 JSON 文本（坏数据在这里被挡下，不让它进库）
        updates["attach"] = attach_mod.dump_attach(attach_mod.load_attach(updates["attach"]))
    if "remind_at" in updates:
        # 提醒时间：空值=清除（NULL）；非法格式拒绝（不静默忽略）
        updates["remind_at"] = _check_remind_at(updates["remind_at"])
    before = get_task(conn, task_id)
    if "status" in updates:
        # 「进行中」的排序号（F 批 · T-F1）由领域层维护，**不由调用方直接写**：
        # 进去给一个末尾序号、离开就清成 NULL —— 免得留下"停在进行中"的幽灵序号
        # （序号是"我正在做的先后"，任务不在进行中了，序号就没有意义）。
        if updates["status"] == STATUS_DOING and before.status != STATUS_DOING:
            updates["doing_rank"] = _next_doing_rank(conn)
        elif updates["status"] != STATUS_DOING and before.status == STATUS_DOING:
            updates["doing_rank"] = None
    if "task_type" in updates or "course_id" in updates:
        # 类型与课程是一对：**按改完之后的状态**校验（只传 course_id 时也要看当前类型，
        # 只传 task_type='普通' 时也要看当前课程）—— 单看某一列会放过"普通 + 挂课程"这种组合。
        new_type = (
            _check_task_type(updates["task_type"]) if "task_type" in updates else before.task_type
        )
        updates["task_type"] = new_type
        updates["course_id"] = _check_course_pair(
            conn, new_type, updates.get("course_id", before.course_id)
        )
    sets = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(
        f"UPDATE tasks SET {sets}, updated_at = ?, version = version + 1 WHERE id = ?",
        (*updates.values(), _now(), task_id),
    )
    conn.commit()
    after = get_task(conn, task_id)
    if before.status != after.status:
        _publish_status_facts(conn, before, after, actor)
    return after


def _publish_status_facts(
    conn: sqlite3.Connection, before: Task, after: Task, actor: str = CREATOR_ME
) -> None:
    """状态跃迁 → 事实（完成/撤销、软删除/恢复、以及 T-F1 的搁置类状态变化）。

    为什么要记「搁置类」状态变化（进行中/待定/取消/归档）：N11 要求**过去做过的事可追溯**，
    而事实层正是"发生了什么"的地方 —— 归档时间、什么时候搁置的，都要能查（档案视图读它）。
    注意：`先做/搁置` 都**不动账本**（债务只看 `overdue_tasks`，与这里的记账无关）。
    """
    from timeflow.core import facts as facts_mod

    if after.status == STATUS_DONE and before.status != STATUS_DONE:
        facts_mod.record(
            conn,
            kind="task.completed",
            subject_type="task",
            subject_id=after.id,
            value_text=after.title,
            extra={
                "title": after.title,
                "due_date": after.due_date,
                "from_status": before.status,
                "completed_on": _today(),
            },
            source=ACTOR_SOURCES[actor],
        )
        facts_mod.publish(
            "task.completed",
            {"task_id": after.id, "title": after.title, "from_status": before.status},
        )
    elif before.status == STATUS_DONE and after.status != STATUS_DONE:
        facts_mod.record(
            conn,
            kind="task.uncompleted",
            subject_type="task",
            subject_id=after.id,
            value_text=after.title,
            extra={"title": after.title, "to_status": after.status, "reverted_on": _today()},
            source=ACTOR_SOURCES[actor],
        )
        facts_mod.publish(
            "task.uncompleted",
            {"task_id": after.id, "title": after.title, "to_status": after.status},
        )
    if after.status == STATUS_DELETED and before.status != STATUS_DELETED:
        facts_mod.record(
            conn,
            kind="task.deleted",
            subject_type="task",
            subject_id=after.id,
            value_text=after.title,
            extra={"title": after.title, "from_status": before.status, "deleted_on": _today()},
            source=ACTOR_SOURCES[actor],
        )
        facts_mod.publish(
            "task.deleted",
            {"task_id": after.id, "title": after.title, "from_status": before.status},
        )
    elif before.status == STATUS_DELETED and after.status != STATUS_DELETED:
        facts_mod.record(
            conn,
            kind="task.restored",
            subject_type="task",
            subject_id=after.id,
            value_text=after.title,
            extra={"title": after.title, "to_status": after.status, "restored_on": _today()},
            source=ACTOR_SOURCES[actor],
        )
        facts_mod.publish(
            "task.restored",
            {"task_id": after.id, "title": after.title, "to_status": after.status},
        )
    elif after.status != STATUS_DONE and before.status != STATUS_DONE:
        # 其余状态变化（进行中 / 待定 / 取消 / 归档 …）：只留一条「状态改了」的事实。
        # **不动账本**（债务、投入都不看它）—— 这些动作是"我在怎么安排这件事"，不是"做成了什么"。
        # 上面「完成 / 撤销完成」两条已经各自记过事实，这里用状态条件排掉，免得一条变化记两笔。
        facts_mod.record(
            conn,
            kind="task.status_changed",
            subject_type="task",
            subject_id=after.id,
            value_text=after.title,
            extra={
                "title": after.title,
                "from_status": before.status,
                "to_status": after.status,
                "changed_on": _today(),
            },
            source=ACTOR_SOURCES[actor],
        )
        facts_mod.publish(
            "task.status_changed",
            {
                "task_id": after.id,
                "title": after.title,
                "from_status": before.status,
                "to_status": after.status,
            },
        )


def delete_task(conn: sqlite3.Connection, task_id: str) -> Task:
    """删除任务（OP-6）：**软删除** —— 置 status=已删、发 `task.deleted` 事实。

    可逆：`restore_task` 撤销软删除。默认视图（列表 / My Day / 逾期 / 债务）都会隐藏已删任务；
    数据与事实历史保留，不物理删除（对齐「可回退」约定 N34）。
    """
    current = get_task(conn, task_id)
    if current.status == STATUS_DELETED:
        return current  # 幂等
    return update_task(conn, task_id, status=STATUS_DELETED)


def restore_task(
    conn: sqlite3.Connection,
    task_id: str,
    restore_status: str = STATUS_TODO,
) -> Task:
    """撤销软删除（OP-6 可逆）：置回指定状态并发 `task.restored` 事实（幂等）。"""
    current = get_task(conn, task_id)
    if current.status != STATUS_DELETED:
        return current
    if restore_status not in VALID_STATUS or restore_status == STATUS_DELETED:
        raise ValueError(f"非法恢复状态: {restore_status}")
    return update_task(conn, task_id, status=restore_status)


def purge_task(conn: sqlite3.Connection, task_id: str) -> None:
    """彻底删除（不可逆）。

    只允许删**已删（回收站）里的任务**：这是界面上「彻底删除 / 清空回收站」的入口，
    目的是让回收站不会无限堆积，同时避免误用——活动中的任务必须先走 `delete_task`（软删除）。
    幂等：任务已不存在时什么都不做。
    """
    try:
        current = get_task(conn, task_id)
    except KeyError:
        return
    if current.status != STATUS_DELETED:
        raise ValueError("只有回收站里（已删）的任务才能彻底删除")
    conn.execute("DELETE FROM task_groups WHERE task_id = ?", (task_id,))
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()


def purge_deleted_tasks(conn: sqlite3.Connection) -> int:
    """清空回收站：物理删除所有「已删」任务，返回删除条数（幂等，无已删任务时返回 0）。"""
    rows = conn.execute("SELECT id FROM tasks WHERE status = ?", (STATUS_DELETED,)).fetchall()
    ids = [str(r["id"]) for r in rows]
    for task_id in ids:
        purge_task(conn, task_id)
    return len(ids)


def myday_tasks(conn: sqlite3.Connection, today: str | None = None) -> list[Task]:
    """My Day 集合（AC-4）：is_myday=1 且非完成/搁置（取消·待定）/归档/已删；**按统一口径排序**。"""
    rows = conn.execute(
        "SELECT * FROM tasks WHERE is_myday = 1 AND status NOT IN (?,?,?,?,?)" + _ORDER_BY,
        (STATUS_DONE, *PARKED_STATUSES, *HIDDEN_STATUSES),
    ).fetchall()
    return [_row_to_task(r) for r in rows]


def _sort_key(task: Task) -> tuple[int, str, int, str]:
    """Python 侧排序键 —— 与 `_ORDER_BY` **同口径**（无截止日最后 → 截止日 → 优先级 → 创建时间）。

    为什么要有第二份：逾期栏是"SQL 查出来的 + 无截止日但昨天就该做的 My Day"两拨合并，
    只能先在 SQL 里排、再在 Python 里重排一次；两份口径必须一致，否则逾期栏与列表顺序会打架。
    """
    return (
        1 if task.due_date is None else 0,
        task.due_date or "",
        _PRIORITY_RANK.get(task.priority, 1),
        task.created_at,
    )


def overdue_tasks(conn: sqlite3.Connection, today: str | None = None) -> list[Task]:
    """逾期任务（AC-5）：未完成且 due_date < 今天（不强推，只如实列出）；**按统一口径排序**。

    AC-4 补充：无截止日但**昨日仍未完成的 My Day 任务**也自动移入逾期栏
    （My Day=今天要做的集合，没做完不假装消失）；这类"老账"的天数从 `created_at`
    算起（T-F8 定案 A），判定由 `_is_stale_undated_myday()` 与 `overdue_days()` **共用**，
    保证"列在栏里的"就是"算得出天数的"。

    「待定 / 取消」不出现在这里 —— 搁置的东西**不计债**（T-F1）。
    """
    t = today or _today()
    t_date = date.fromisoformat(t)
    rows = conn.execute(
        "SELECT * FROM tasks WHERE due_date IS NOT NULL AND due_date < ? "
        "AND status NOT IN (?,?,?,?,?)" + _ORDER_BY,
        (t, STATUS_DONE, *PARKED_STATUSES, *HIDDEN_STATUSES),
    ).fetchall()
    overdue = [_row_to_task(r) for r in rows]

    # 无 due 但过期的 My Day 任务：加入 My Day 的日期早于今天（用 created_at 日期近似）
    myday_rows = conn.execute(
        "SELECT * FROM tasks WHERE due_date IS NULL AND is_myday = 1 AND status NOT IN (?,?,?,?,?)",
        (STATUS_DONE, *PARKED_STATUSES, *HIDDEN_STATUSES),
    ).fetchall()
    for r in myday_rows:
        task = _row_to_task(r)
        if _is_stale_undated_myday(task, t_date):
            overdue.append(task)
    overdue.sort(key=_sort_key)
    return overdue


# ---------------------------------------------------------------- 子任务（SR-F1.6 / OP-12）
# 嵌套的最大层数（F 批 · T-F5）：用户定的形状是「大任务 → 子任务 → 子步骤」三层。
# 分组用同一个上限（`groups.MAX_GROUP_DEPTH`）—— 两处都是"分类/拆解"的深度，
# 各写一个数字迟早会互相矛盾。
MAX_TASK_DEPTH = 3


def subtask_progress(conn: sqlite3.Connection, task_id: str) -> dict[str, int]:
    """子任务进度：{done, total}（没有子任务时 total=0）。"""
    rows = conn.execute("SELECT status FROM tasks WHERE parent_id = ?", (task_id,)).fetchall()
    total = len(rows)
    done = sum(1 for r in rows if r["status"] == STATUS_DONE)
    return {"done": done, "total": total}


def subtasks(conn: sqlite3.Connection, task_id: str) -> list[Task]:
    """列出子任务：未完成在前，再按截止日（无截止日最后）；同状态按创建时间。

    「未完成在前」这条顺序就是 **T-F4 的「当前该做哪一步」** 的依据：
    列表第一个未完成的，就是这一步。
    """
    rows = conn.execute(
        "SELECT * FROM tasks WHERE parent_id = ? "
        "ORDER BY (status = ?) ASC, due_date IS NULL, due_date, created_at",
        (task_id, STATUS_DONE),
    ).fetchall()
    return [_row_to_task(r) for r in rows]


def current_step(conn: sqlite3.Connection, task_id: str) -> Task | None:
    """**当前该做的那一步**（N10 / T-F4）：第一个未完成的子任务；没有子任务/全做完了 → None。

    用户原话：「子步骤完成前，它变成主任务的一个显现（任务卡里显示一个子步骤）」——
    所以主任务卡上只显示**一步**（不是把所有步骤堆出来），显示的就是这一个。
    """
    for child in subtasks(conn, task_id):
        if child.status != STATUS_DONE:
            return child
    return None


def subtask_view(conn: sqlite3.Connection, task_id: str) -> tuple[dict[str, int], Task | None]:
    """一次查询同时给出「进度 + 当前该做哪一步」（列表接口每张卡都要这两个读数）。

    为什么合成一个函数：`_out()` 给每张卡都要这两样，分两次查就是白白多一倍查询；
    而且两者必须**同一份子任务顺序/口径** —— 分开写迟早会出现"进度说剩 2 步、
    当前步骤却显示已完成那一步"这种自相矛盾。
    """
    kids = subtasks(conn, task_id)
    done = sum(1 for k in kids if k.status == STATUS_DONE)
    current = next((k for k in kids if k.status != STATUS_DONE), None)
    return {"done": done, "total": len(kids)}, current


def _would_cycle(conn: sqlite3.Connection, task_id: str, parent_id: str) -> bool:
    """把 task_id 挂到 parent_id 下会不会成环（沿父链上溯，撞到自己就是环）。"""
    seen: set[str] = set()
    cursor: str | None = parent_id
    while cursor and cursor not in seen:
        if cursor == task_id:
            return True
        seen.add(cursor)
        row = conn.execute("SELECT parent_id FROM tasks WHERE id = ?", (cursor,)).fetchone()
        cursor = str(row["parent_id"]) if row and row["parent_id"] else None
    return False


def task_depth(conn: sqlite3.Connection, task_id: str) -> int:
    """任务层数：顶层（大任务）= 1，子任务 = 2，子步骤 = 3（沿 `parent_id` 上溯）。

    上限 `MAX_TASK_DEPTH` 是用户定的形状：「大任务 → 子任务 → 子步骤」。
    坏数据成环时停在 `MAX_TASK_DEPTH+1`，不空转（`_would_cycle` 负责不让新的环产生）。
    """
    depth = 1
    row = conn.execute("SELECT parent_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
    cursor = str(row["parent_id"]) if row and row["parent_id"] else None
    seen = {task_id}
    while cursor and cursor not in seen and depth <= MAX_TASK_DEPTH:
        seen.add(cursor)
        depth += 1
        up = conn.execute("SELECT parent_id FROM tasks WHERE id = ?", (cursor,)).fetchone()
        cursor = str(up["parent_id"]) if up and up["parent_id"] else None
    return depth


def _subtree_height(conn: sqlite3.Connection, task_id: str) -> int:
    """以 task_id 为根的子树有几层（只算自己 = 1）。"""
    kids = conn.execute("SELECT id FROM tasks WHERE parent_id = ?", (task_id,)).fetchall()
    if not kids:
        return 1
    return 1 + max(_subtree_height(conn, str(k["id"])) for k in kids)


@dataclass
class TaskNode:
    """子树里的一个节点（F 批 · T-F5）：任务 + **绝对层数**
    （1 = 大任务、2 = 子任务、3 = 子步骤）。"""

    task: Task
    depth: int


def task_tree(conn: sqlite3.Connection, root_id: str) -> list[TaskNode]:
    """整棵子树（**前序**：父在子前），每个节点带绝对层数。

    N10/SR-F1.6 的「任务树/折叠呈现」用这一份数据：三层都要摆得出来，
    所以界面**不必**自己递归（先取子、再逐个取孙子 = 界面里再写一遍树）。
    坏数据成环时跳过重复节点，不无限递归。
    """
    out: list[TaskNode] = []

    def walk(parent_id: str, depth: int, guard: set[str]) -> None:
        for child in subtasks(conn, parent_id):
            if child.id in guard:
                continue
            out.append(TaskNode(task=child, depth=depth))
            walk(child.id, depth + 1, guard | {child.id})

    walk(root_id, task_depth(conn, root_id) + 1, {root_id})
    return out


def _autocomplete_parent(
    conn: sqlite3.Connection, parent_id: str | None, actor: str = CREATOR_ME
) -> Task | None:
    """子任务全完成时**自动完成父任务**（OP-12 联动）。

    父任务若还有别的未完成子任务，`complete_task` 会抛 ValueError —— 那不是错误，
    只是"还没到时候"，这里静默忽略。
    `actor` 原样往下传（T-G6）：**联动导致的完成算系统行为**，但事实的 `source` 如实记
    "这次是谁触发的" —— 于是"AI 勾掉最后一个步骤、把父任务带完成"这种情况查得出来。
    """
    if not parent_id:
        return None
    progress = subtask_progress(conn, parent_id)
    if progress["total"] == 0 or progress["done"] < progress["total"]:
        return None
    try:
        return complete_task(conn, parent_id, actor=actor)
    except (KeyError, ValueError):
        return None


def create_subtask(
    conn: sqlite3.Connection,
    parent_id: str,
    title: str,
    due_date: str | None = None,
    *,
    created_by: str = CREATOR_ME,
) -> Task:
    """新建子任务（OP-12）。父任务不存在 → KeyError；标题空 → ValueError。

    继承父任务的 My Day 归属（子任务跟着父任务出现在今天的清单里）；
    建完若父任务的子任务已全部完成 → 自动完成父任务。
    **第三层封顶**（T-F5）：父任务已经是第三层（子步骤）时拒绝 ——
    用户的形状是「大任务 → 子任务 → 子步骤」三层，再往下界面就没地方摆了。
    `created_by`（T-G6）：AI 加步骤走这条路，归属跟着写 `ai`（边界判据就是它）。
    """
    parent = get_task(conn, parent_id)
    if not title.strip():
        raise ValueError("子任务标题不能为空")
    if task_depth(conn, parent_id) >= MAX_TASK_DEPTH:
        raise ValueError(
            f"任务最多 {MAX_TASK_DEPTH} 层（大任务 → 子任务 → 子步骤）："
            "「子步骤」下面不能再拆了"
        )
    child = create_task(
        conn,
        title.strip(),
        due_date=due_date,
        parent_id=parent_id,
        is_myday=parent.is_myday,
        created_by=created_by,
    )
    _autocomplete_parent(conn, parent_id)
    return get_task(conn, child.id)


def set_task_parent(
    conn: sqlite3.Connection, task_id: str, parent_id: str | None
) -> Task:
    """改父任务（OP-12 边界：**禁止成环** + **最多 `MAX_TASK_DEPTH` 层**）。

    `parent_id=None` 表示脱离父任务。三层上限是用户定的（「大任务 → 子任务 → 子步骤」）：
    超过就 ValueError（带现有层数），**不静默截断**（悄悄把孙子挂成儿子比报错更难查）。
    """
    if parent_id is not None:
        if parent_id == task_id:
            raise ValueError("任务不能作为自己的子任务")
        get_task(conn, parent_id)  # 父任务不存在 → KeyError
        if _would_cycle(conn, task_id, parent_id):
            raise ValueError("不能把任务挂到它自己的子任务下（会成环）")
        height = _subtree_height(conn, task_id)
        if task_depth(conn, parent_id) + height > MAX_TASK_DEPTH:
            raise ValueError(
                f"任务最多 {MAX_TASK_DEPTH} 层（大任务 → 子任务 → 子步骤）："
                f"这棵子树有 {height} 层，挂到「{get_task(conn, parent_id).title}」下就超了"
            )
    return update_task(conn, task_id, parent_id=parent_id)


def complete_task(
    conn: sqlite3.Connection, task_id: str, *, actor: str = CREATOR_ME
) -> Task:
    """完成任务（AC-7 联动）：若为父任务，仅当全部子任务完成才自动完成；否则标记完成。

    第 2 步：完成时发 `task.completed` 事实（幂等——已完成的重复调用不再发）。
    第 5 步（OP-8）：完成设了重复的任务后，自动生成下一次（只生成一次）。
    `actor`（T-G6）：AI 接口勾步骤时传 `ai`，事实的 `source` 如实记 —— 账本口径不变
    （完成就是完成，不因为"谁做的"而算法不同）。
    """
    actor = _check_creator(actor)  # 先校验：任务已经完成也**不放过**非法 actor（不静默）
    current = get_task(conn, task_id)
    if current.status == STATUS_DONE:
        return current
    children = conn.execute("SELECT * FROM tasks WHERE parent_id = ?", (task_id,)).fetchall()
    if children and any(_row_to_task(c).status != STATUS_DONE for c in children):
        raise ValueError("存在未完成的子任务，父任务不能自动完成")
    done = update_task(conn, task_id, status=STATUS_DONE, actor=actor)
    if done.repeat_days is not None:
        process_repeats(conn)
    # 子任务全完成 → 父任务自动完成（OP-12 联动）。
    # 放在最后、并且只在"确实还有父任务"时递归一层 —— 链式向上（子→父→祖父）不会无限递归：
    # 每上一层，`complete_task` 都会先检查那一层的子任务是否全完成。
    if done.parent_id:
        _autocomplete_parent(conn, done.parent_id, actor)
    return done


def uncomplete_task(
    conn: sqlite3.Connection,
    task_id: str,
    restore_status: str = STATUS_TODO,
) -> Task:
    """撤销完成（OP-5 可逆）：发 `task.uncompleted` 反向事实并恢复状态（幂等）。"""
    current = get_task(conn, task_id)
    if current.status != STATUS_DONE:
        return current
    if restore_status not in VALID_STATUS or restore_status == STATUS_DONE:
        raise ValueError(f"非法恢复状态: {restore_status}")
    return update_task(conn, task_id, status=restore_status)


def toggle_flag(conn: sqlite3.Connection, task_id: str) -> Task:
    """手动标记开关（T-B3 / Flagged 视图的唯一入口）：翻转 `flagged`，幂等可反复按。

    注意：标记只是"我自己圈出来要留意"，**不发事实、不改状态、不动账本**
    （与「优先级」「备注」同属任务定义，不是"发生了什么"）。
    """
    current = get_task(conn, task_id)
    return update_task(conn, task_id, flagged=not current.flagged)


# ---------------------------------------------------------------- 状态机（F 批 · T-F1）
# 口径来源：`复盘/口径定案-待定清单.md` §1（用户 2026-09-21 给出的完整设计）。
# 这一段补的是**代码里从来没有入口**的几个状态：进行中 / 归档（此前谁也不会写它们），
# 以及约定层新加的「待定」。所有动作都**不发账本事实**，只留 `task.status_changed`。


def _next_doing_rank(conn: sqlite3.Connection) -> int:
    """下一个「进行中」的排序号：排在现有最后（没人排过 → 1）。"""
    row = conn.execute(
        "SELECT COALESCE(MAX(doing_rank), 0) + 1 AS n FROM tasks WHERE status = ?",
        (STATUS_DOING,),
    ).fetchone()
    return int(row["n"]) if row else 1


def _write_doing_rank(conn: sqlite3.Connection, task_id: str, rank: int | None) -> None:
    """只改排序号：**不动 `updated_at`**（换顺序不是"这条内容变了"，别把完成时间/重复基准弄歪），
    版本号照加（并发口径一致）。"""
    conn.execute(
        "UPDATE tasks SET doing_rank = ?, version = version + 1 WHERE id = ?", (rank, task_id)
    )
    conn.commit()


def resting_status(task: Task, today: str | None = None) -> str:
    """「停下来」之后回到哪个状态：截止日已过 → `逾期`，否则 → `未开始`。

    为什么要有这条：`create_task` 建任务时就是按这个口径写状态的（截止日已过直接标逾期），
    「移出进行中 / 撤销归档」也得回到同一个口径，否则同一个任务会有两套说法。
    """
    if task.due_date and task.due_date < (today or _today()):
        return STATUS_OVERDUE
    return STATUS_TODO


def doing_tasks(conn: sqlite3.Connection) -> list[Task]:
    """「进行中」清单（T-F1）：**可以同时多个**，顺序由用户自己定。

    「方便我看到底自己在做什么任务」（用户原话）——所以这是一份"我现在手上有什么"的读数，
    不是"只能做一件"的锁。排序键：`doing_rank`（没排过序的排最后）。
    """
    rows = conn.execute(
        "SELECT * FROM tasks WHERE status = ?" + _DOING_ORDER_BY, (STATUS_DOING,)
    ).fetchall()
    return [_row_to_task(r) for r in rows]


def start_task(conn: sqlite3.Connection, task_id: str) -> Task:
    """把任务放进「进行中」（幂等）。**可以同时多个**；序号自动排到末尾。

    边界：已完成 / 已归档 / 已删 / 已取消 / 待定的任务不能直接"在做" ——
    先撤销完成、或撤销归档，否则会出现"已完成 + 进行中"同时成立的怪状态。
    """
    current = get_task(conn, task_id)
    if current.status == STATUS_DOING:
        return current
    if current.status == STATUS_DONE:
        raise ValueError("已完成的任务不能置为进行中（先撤销完成）")
    if current.status in HIDDEN_STATUSES:
        raise ValueError(f"「{current.status}」的任务不能置为进行中（先撤销归档/删除）")
    if current.status in PARKED_STATUSES:
        raise ValueError(f"「{current.status}」的任务不能置为进行中（先取回）")
    return update_task(conn, task_id, status=STATUS_DOING)


def stop_task(conn: sqlite3.Connection, task_id: str) -> Task:
    """移出「进行中」（幂等）：回到 `resting_status`（截止日已过则回到「逾期」）。"""
    current = get_task(conn, task_id)
    if current.status != STATUS_DOING:
        return current
    return update_task(conn, task_id, status=resting_status(current))


def park_task(conn: sqlite3.Connection, task_id: str) -> Task:
    """搁置为「待定」（幂等）：闲置 / 挂在那儿、**没放弃、不计债**。

    行为同「取消」（T-F1 决策）：不进 My Day、不提醒、不参与债务；
    但**仍在「全部任务」里看得见**（它是"先放着"，不是"没了"）。
    已完成的任务不给置待定（先撤销完成）——避免"完成了又待定"这种自相矛盾。
    """
    current = get_task(conn, task_id)
    if current.status == STATUS_PENDING:
        return current
    if current.status == STATUS_DONE:
        raise ValueError("已完成的任务不置为待定（先撤销完成）")
    if current.status == STATUS_DELETED:
        raise ValueError("已删除的任务不置为待定（先恢复）")
    return update_task(conn, task_id, status=STATUS_PENDING)


def cancel_task(conn: sqlite3.Connection, task_id: str) -> Task:
    """取消任务（幂等）：打错了 / 没必要做了 —— ≈删除但**留痕**（不进默认的逾期与债务）。

    已完成的任务不能直接取消：那等于"**撤销完成 + 取消**"两件事一起做，
    而撤销完成会连带回退收益读数（`task.uncompleted`）—— 不该在一次点击里偷偷发生。
    要这样处理就分两步：先撤销完成，再取消。
    """
    current = get_task(conn, task_id)
    if current.status == STATUS_CANCELLED:
        return current
    if current.status == STATUS_DONE:
        raise ValueError("已完成的任务不能直接取消（先撤销完成）")
    if current.status == STATUS_DELETED:
        raise ValueError("已删除的任务不能取消（先恢复）")
    return update_task(conn, task_id, status=STATUS_CANCELLED)


def un_park_task(conn: sqlite3.Connection, task_id: str) -> Task:
    """把「待定 / 取消」取回（幂等）：回到 `resting_status`（截止日已过则回到「逾期」）。"""
    current = get_task(conn, task_id)
    if current.status not in PARKED_STATUSES:
        return current
    return update_task(conn, task_id, status=resting_status(current))


def archive_task(conn: sqlite3.Connection, task_id: str) -> Task:
    """收进档案（幂等）：默认视图不再显示，可在「档案」里查阅（可撤销）。

    口径：档案主要是**完成后**的归宿（用户原话：「完成某个任务之后，他就进入档案中，
    方便我后期以后的查阅」），但**手动归档不强制先完成** ——
    取消掉的、搁置的也该有地方收，否则"整理一下列表"这件事没法做。
    自动归档（完成 N 天后）是另一条路（T-F2），两条都会出现在档案视图里。
    """
    current = get_task(conn, task_id)
    if current.status == STATUS_ARCHIVED:
        return current
    if current.status == STATUS_DELETED:
        raise ValueError("已删除的任务不能归档（先恢复）")
    return update_task(conn, task_id, status=STATUS_ARCHIVED)


def unarchive_task(conn: sqlite3.Connection, task_id: str) -> Task:
    """撤销归档（幂等）：回到 `resting_status`（截止日已过则回到「逾期」）。"""
    current = get_task(conn, task_id)
    if current.status != STATUS_ARCHIVED:
        return current
    return update_task(conn, task_id, status=resting_status(current))


def archived_tasks(conn: sqlite3.Connection) -> list[Task]:
    """显式归档的任务（`status = 归档`），最近归档的排前面。

    注意：这只是档案的一半 —— **完成 N 天后自动进档案**是**派生**的（T-F2），
    不写回状态；档案视图要把两拨合起来看。
    """
    rows = conn.execute(
        "SELECT * FROM tasks WHERE status = ? ORDER BY updated_at DESC", (STATUS_ARCHIVED,)
    ).fetchall()
    return [_row_to_task(r) for r in rows]


# ---------------------------------------------------------------- 完成 N 天后进档案（N11 / T-F2）
# 口径（用户 2026-09-21）：完成**不是立刻**进档案，而是「过几天再归档」——
# 「归档是说我完成某个任务之后，他就进入档案中，方便我后期以后的查阅」。
# 落地为**派生**判定（完成日 + N ≤ 今天 ⇒ 默认视图不再显示、档案视图里出现），
# 不写回 `status`：写回就需要一个定时器/惰性写入点，而本项目明确避免定时任务
# （与 T-F7 的逾期同一套理由：一处口径，一处判定）。
DEFAULT_ARCHIVE_AFTER_DAYS = 3
MAX_ARCHIVE_AFTER_DAYS = 365
KEY_ARCHIVE_AFTER_DAYS = "tasks_archive_after_days"
_COMPLETED_KIND = "task.completed"


def _setting_raw(conn: sqlite3.Connection, key: str) -> str | None:
    """读一条本机设置（`app_settings` 通用 key/value 表；与附件/专注设置同一处）。"""
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def _put_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def _valid_archive_days(days: object) -> int:
    """N 必须是 0..365 的整数（0 = 完成当天就收走）。非法一律 ValueError，**不静默落默认值**。"""
    if isinstance(days, bool) or not isinstance(days, (int, str)):
        raise ValueError("after_days 只能是 0~365 的整数")
    try:
        value = int(str(days).strip())
    except ValueError:
        raise ValueError("after_days 只能是 0~365 的整数") from None
    if value < 0 or value > MAX_ARCHIVE_AFTER_DAYS:
        raise ValueError(f"after_days 要在 0~{MAX_ARCHIVE_AFTER_DAYS} 之间")
    return value


def archive_after_days(conn: sqlite3.Connection, default: int | None = None) -> int:
    """「完成几天后进档案」的当前值（T-F2）：本机改过用表里的，否则用配置默认（3 天）。

    读的时候**容错**：表里是坏数据（手工改过/老版本写的）→ 退回默认值，
    不让一条坏设置把整个任务列表打挂。（写的时候相反：非法值直接拒绝。）
    """
    fallback = DEFAULT_ARCHIVE_AFTER_DAYS if default is None else int(default)
    raw = _setting_raw(conn, KEY_ARCHIVE_AFTER_DAYS)
    if raw is None:
        return fallback
    try:
        return _valid_archive_days(raw)
    except ValueError:
        return fallback


def set_archive_after_days(
    conn: sqlite3.Connection, days: object, default: int | None = None
) -> int:
    """改「完成几天后进档案」（T-F2）。返回改完之后的值；非法值 ValueError（400，不静默）。"""
    value = _valid_archive_days(days)
    _put_setting(conn, KEY_ARCHIVE_AFTER_DAYS, str(value))
    conn.commit()
    return archive_after_days(conn, default)


def archive_settings(conn: sqlite3.Connection, default: int | None = None) -> dict[str, object]:
    """给界面用的设置读数（当前值 / 默认值 / 上限 / 口径说明）—— 规则只有一份，前端不复述。"""
    fallback = DEFAULT_ARCHIVE_AFTER_DAYS if default is None else int(default)
    return {
        "after_days": archive_after_days(conn, fallback),
        "default_after_days": fallback,
        "max_after_days": MAX_ARCHIVE_AFTER_DAYS,
        "note": "完成之后不是立刻收走：满 N 天自动进档案（0 = 当天就收）。"
                "档案里仍能看见，撤销完成就会回到列表。",
    }


def completion_dates(conn: sqlite3.Connection, task_ids: list[str]) -> dict[str, str]:
    """一次查出这些任务各自的「完成日」（`YYYY-MM-DD`）；没记录的不出现在结果里。

    为什么取事实 `task.completed` 而不是 `updated_at`：`updated_at` 是"最后一次改动"——
    完成之后**随手补一句备注就会把它推后**，归档倒计时于是被重置，
    「完成 N 天后进档案」就永远不触发（那正是本卡要的"过几天再归档"，不能被编辑搅黄）。
    事实记的是**完成那一刻**；撤销完成再完成会再来一条，取最新那条（= 现在这次完成）。
    查不到事实（老库 / 手工造的数据）→ 调用方退回 `updated_at`，**不猜、不报错**。
    """
    if not task_ids:
        return {}
    marks = ",".join("?" * len(task_ids))
    rows = conn.execute(
        f"SELECT subject_id, MAX(occurred_at) AS done_at FROM facts "
        f"WHERE kind = ? AND subject_id IN ({marks}) GROUP BY subject_id",
        (_COMPLETED_KIND, *task_ids),
    ).fetchall()
    return {str(r["subject_id"]): str(r["done_at"])[:10] for r in rows}


def completed_on(conn: sqlite3.Connection, task: Task) -> str | None:
    """单个任务的完成日（取不到事实时退回 `updated_at` 的日期部分，见 `completion_dates`）。"""
    if task.status != STATUS_DONE:
        return None
    found = completion_dates(conn, [task.id]).get(task.id)
    return found or task.updated_at[:10]


def auto_filed(task: Task, done_on: str | None, today: str, days: int) -> bool:
    """**派生**判定：这个任务是不是"完成满 N 天、已经自动进档案"了（T-F2）。

    - 只有「完成」态才有这回事（手动归档是另一条路，`archived_tasks`）；
    - 判据是**完成日 + N ≤ 今天**（没有完成日就不判：宁可不收，也不把没收走的东西藏起来）；
    - **不写回状态**：`status` 还是「完成」，档案视图里如实标"完成 N 天后自动收入"。
    """
    if task.status != STATUS_DONE or not done_on:
        return False
    cutoff = (date.fromisoformat(today) - timedelta(days=days)).isoformat()
    return done_on <= cutoff


def _hide_auto_filed(conn: sqlite3.Connection, tasks: list[Task]) -> list[Task]:
    """从默认视图里去掉"已经自动进档案的"完成件（T-F2）。

    只对**完成态**做一次聚合查询（`completion_dates`），不给每个任务各查一次 ——
    列表接口不该因为加了个派生判定就变成 N+1 次查询。
    """
    done = [t for t in tasks if t.status == STATUS_DONE]
    if not done:
        return tasks
    today = _today()
    days = archive_after_days(conn)
    dates = completion_dates(conn, [t.id for t in done])
    filed = {t.id for t in done if auto_filed(t, dates.get(t.id) or t.updated_at[:10], today, days)}
    return [t for t in tasks if t.id not in filed]


@dataclass
class ArchiveEntry:
    """档案里的一条（T-F2）：`auto=True` 是"完成 N 天后自动收入"，`False` 是手动归档。"""

    task: Task
    auto: bool
    completed_on: str | None


def archive_entries(
    conn: sqlite3.Connection, today: str | None = None, days: int | None = None
) -> list[ArchiveEntry]:
    """档案视图（N11 / T-F2）：**手动归档的** + **完成满 N 天自动收入的**，两拨合起来看。

    为什么要合：档案的用法是"回头看"（用户原话「方便我后期以后的查阅」）——
    分两个地方看会让人漏掉一半；两种来源在界面里用徽标分开标明。
    排序：按"进档案的那天"降序（完成件看完成日，手动归档看最后改动），新的先看。
    """
    t = today or _today()
    n = archive_after_days(conn) if days is None else days
    rows = conn.execute(
        "SELECT * FROM tasks WHERE status IN (?, ?)", (STATUS_ARCHIVED, STATUS_DONE)
    ).fetchall()
    tasks = [_row_to_task(r) for r in rows]
    dates = completion_dates(conn, [x.id for x in tasks])
    entries: list[ArchiveEntry] = []
    for task in tasks:
        fallback = task.updated_at[:10] if task.status == STATUS_DONE else None
        done_on = dates.get(task.id) or fallback
        if task.status == STATUS_ARCHIVED:
            entries.append(ArchiveEntry(task=task, auto=False, completed_on=done_on))
        elif auto_filed(task, done_on, t, n):
            entries.append(ArchiveEntry(task=task, auto=True, completed_on=done_on))
    entries.sort(key=lambda e: e.completed_on or e.task.updated_at[:10], reverse=True)
    return entries


def move_doing(conn: sqlite3.Connection, task_id: str, direction: str) -> Task:
    """调「进行中」的先后（T-F1）：`direction` = `up` / `down`，与相邻的一条换序号。

    为什么是"上/下按钮"而不是拖拽：段2 决策**不做拖拽排序**（触屏/键鼠/可测性都不划算），
    序号就是这一件事的顺序。已在头/尾 → 原地不动（幂等，不报错）；
    非「进行中」的任务 → ValueError（排序对不在进行中的任务没有意义）。
    """
    if direction not in ("up", "down"):
        raise ValueError("方向只能是 up / down")
    current = get_task(conn, task_id)
    if current.status != STATUS_DOING:
        raise ValueError("只有「进行中」的任务能调顺序")
    items = doing_tasks(conn)
    # 先规整成 1..N（老数据可能没序号/序号重复）：顺序保持现状，再把相邻两条换过来。
    for i, item in enumerate(items, start=1):
        _write_doing_rank(conn, item.id, i)
    index = next(i for i, item in enumerate(items) if item.id == task_id)
    swap = index - 1 if direction == "up" else index + 1
    if swap < 0 or swap >= len(items):
        return get_task(conn, task_id)
    _write_doing_rank(conn, task_id, swap + 1)
    _write_doing_rank(conn, items[swap].id, index + 1)
    return get_task(conn, task_id)


# ---------------------------------------------------------------- 「尝试失败」（N11 / T-F3）
# 事实类型名单独抽成常量：领域层与档案视图（T-F2 的「过去尝试」）都按它计数，
# 名字散落在两处字符串里迟早会分叉。
ATTEMPT_FAILED = "task.attempt.failed"


def attempt_failed(conn: sqlite3.Connection, task_id: str, note: str = "") -> Task:
    """记一次「尝试失败」（N11 / T-F3）：**只认显式点击**，绝不从别的动作推断。

    为什么只认显式（用户 2026-09-21 决定）：「试了 N 回」是给自己的读数，**数字要可信** ——
    如果它由"推到明天/取消"推断出来，那它记的就是我的猜测，不是事实。

    - 一次点击 = 一条 `task.attempt.failed` 事实（同一天失败两次就是两条，如实计数）；
    - `note` 是可选的一句说明（"试到哪儿了/为什么不成"），存 `value_text`，将来进 md 存档；
    - **不改状态**：失败之后要做什么是下一步的选择（取消 / 待定 / 推到明天 / 先不动），
      这个动作只负责把"试过、没成"记下来 —— 所以它也不动账本、不动 `updated_at` 之外的任何字段。
    - 边界：完成 / 搁置（取消·待定）/ 归档 / 已删 → ValueError。这些任务已不在"手上"，
      记"尝试失败"没有意义（要记就先撤销完成/取回/撤销归档）。
    """
    current = get_task(conn, task_id)
    if current.status == STATUS_DONE:
        raise ValueError("已完成的任务不记「尝试失败」（先撤销完成）")
    if current.status in PARKED_STATUSES:
        raise ValueError(f"「{current.status}」的任务不记「尝试失败」（先取回）")
    if current.status in HIDDEN_STATUSES:
        raise ValueError(f"「{current.status}」的任务不记「尝试失败」（先撤销归档/删除）")
    from timeflow.core import facts as facts_mod

    text = (note or "").strip()
    facts_mod.record(
        conn,
        kind=ATTEMPT_FAILED,
        subject_type="task",
        subject_id=current.id,
        value_text=text or None,
        extra={"title": current.title, "note": text, "failed_on": _today()},
        source="desktop",
    )
    facts_mod.publish(
        ATTEMPT_FAILED, {"task_id": current.id, "title": current.title, "note": text}
    )
    return current


def attempt_count(conn: sqlite3.Connection, task_id: str) -> int:
    """这个任务「试了几回」（T-F3）：数 `task.attempt.failed` 事实。

    为什么数事实、不在 `tasks` 上加一个计数字段：N11 要的是"过去做过的尝试"，
    那是**历史**（将来还要进 md 存档、要能审计）；事实层就是干这个的（R1：只读事实层）。
    """
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM facts WHERE kind = ? AND subject_id = ?",
        (ATTEMPT_FAILED, task_id),
    ).fetchone()
    return int(row["n"] or 0)


def attempt_counts(conn: sqlite3.Connection, task_ids: list[str]) -> dict[str, int]:
    """一次查出这些任务各自「试了几回」（T-F3）—— 没有失败记录的不出现在结果里。

    为什么要有批版：档案视图是一屏列表，逐张卡调 `attempt_count` 就是 N+1 次查询。
    """
    if not task_ids:
        return {}
    marks = ",".join("?" * len(task_ids))
    rows = conn.execute(
        f"SELECT subject_id, COUNT(*) AS n FROM facts "
        f"WHERE kind = ? AND subject_id IN ({marks}) GROUP BY subject_id",
        (ATTEMPT_FAILED, *task_ids),
    ).fetchall()
    return {str(r["subject_id"]): int(r["n"] or 0) for r in rows}


def attempt_notes(conn: sqlite3.Connection, task_id: str, limit: int = 20) -> list[str]:
    """历次失败留下的说明（**新的在前**，只取有字的，最多 `limit` 条）。

    没写说明的那几次不在这里出现（它们只体现在 `attempt_count` 里）——
    空字符串塞进"过去尝试"列表只会变成一排空行。
    """
    rows = conn.execute(
        "SELECT value_text FROM facts WHERE kind = ? AND subject_id = ? "
        "ORDER BY occurred_at DESC, recorded_at DESC",
        (ATTEMPT_FAILED, task_id),
    ).fetchall()
    notes: list[str] = []
    for row in rows:
        text = str(row["value_text"] or "").strip()
        if not text:
            continue
        notes.append(text)
        if len(notes) >= limit:
            break
    return notes


@dataclass
class DebtStep:
    """挂在债务卡下面的一步（T-F9）：它自己逾期几天 + 属于哪个任务。"""

    task: Task
    overdue_days: int


@dataclass
class DebtGroup:
    """债务里的一张卡（T-F9，用户 2026-09-21 定）：

    「可以在债务那里，建个**父任务状态卡**，然后挂」—— 逾期的东西不再一条条平铺，
    而是**归到"还在手上的那个父任务"上**：父任务一张卡，它逾期的子孙**挂在卡下面**。

    - `root`：这张卡的父任务（沿父链上溯到**最高一层还活着的祖先**，见 `_debt_root`）；
    - `own_days`：父任务**自己**逾期几天（0 = 它自己没到点 / 没截止日，天数全来自挂着的步）；
    - `steps`：挂在它下面的逾期子孙（按天数降序）—— 每一层都挂（子任务、子步骤都算）。
    """

    root: Task
    own_days: int
    steps: list[DebtStep]

    @property
    def overdue_days(self) -> int:
        """这张卡"欠了多少天" = 父任务自己的天数与挂着的步里**最狠的那个**（取最大值）。

        为什么取最大而不是相加：卡代表的是"这件事"欠了多久，不是"把几条加起来折算成一条"
        （约定层：债务 = 逾期天数/程度，**不做折算**）。
        """
        return max([self.own_days, *(s.overdue_days for s in self.steps), 0])


def _debt_root(conn: sqlite3.Connection, task: Task) -> Task:
    """沿父链上溯到**最高一层"还在手上"的祖先**（T-F9 的"父任务状态卡"就是它）。

    完成 / 搁置（取消·待定）/ 归档 / 已删的祖先**不配当卡**（"搁置不计债"这条不能被绕过去）——
    遇到就停在它下面那一层：项目已经取消了，但那一步还欠着，那一张卡就是这一步自己。
    """
    root = task
    guard = {task.id}
    while root.parent_id and root.parent_id not in guard:
        guard.add(root.parent_id)
        try:
            parent = get_task(conn, root.parent_id)
        except KeyError:  # 父任务被硬删了：就当它是顶层，不炸
            break
        if parent.status == STATUS_DONE or parent.status in PARKED_STATUSES:
            break
        if parent.status in HIDDEN_STATUSES:
            break
        root = parent
    return root


def debt_groups(
    conn: sqlite3.Connection,
    today: str | None = None,
    *,
    undated_counts: bool | None = None,
) -> list[DebtGroup]:
    """债务卡（T-F9）：把逾期的东西**归到还活着的父任务上**，按"欠得最狠"的排前面。

    口径（用户 2026-09-21 定）：债务里建**父任务状态卡**，逾期的子孙**挂在卡下面** ——
    于是同一件事（大任务 + 它的某一步过期）在债务里只占**一张卡**，而不是父一条、子一条。
    `debt_count` = **卡的张数**（不是逾期条目的条数），与明细天然同源。

    逾期的判定本身仍走 `overdue_tasks()` / `overdue_days()`（一处口径）——
    本函数只负责"归到哪张卡上"，不改"算不算逾期"。

    `undated_counts`（T-D11）就是那条**口径开关**：无截止日的 My Day 老账算不算债。
    `None`（默认）= 跟着本机当前口径走（读 `core/behavior.py`）；显式传值是**影子对比**在用
    —— 同一份库、两套口径各算一遍，就得到"切过去会变成什么样"。
    开关只动**债务**这一侧：逾期栏的天数照旧（T-F9 定过"逾期栏是工作清单、债务是阅读清单"，
    两套读法不互相牵动）。
    """
    t = today or _today()
    counted = behavior.undated_myday_counted(conn) if undated_counts is None else undated_counts
    groups: dict[str, DebtGroup] = {}
    for task in overdue_tasks(conn, t):
        days = overdue_days(task, t)
        if task.due_date is None and not counted:
            days = 0  # 老口径（T-F8 之前）：没截止日的老账列在逾期栏，但不算债
        if days <= 0:
            continue
        root = _debt_root(conn, task)
        card = groups.get(root.id)
        if card is None:
            card = DebtGroup(root=root, own_days=0, steps=[])
            groups[root.id] = card
        if root.id == task.id:
            card.own_days = max(card.own_days, days)
        else:
            card.steps.append(DebtStep(task=task, overdue_days=days))
    cards = list(groups.values())
    for card in cards:
        card.steps.sort(key=lambda s: s.overdue_days, reverse=True)
    cards.sort(key=lambda c: c.overdue_days, reverse=True)
    return cards


def debt_count(conn: sqlite3.Connection, today: str | None = None) -> int:
    """债务卡张数（T-F9）—— 账本 / 洞察 / 周结算**共用这一个**，免得三处各算一套。"""
    return len(debt_groups(conn, today))


def compare_debt_undated_myday(
    conn: sqlite3.Connection,
    current: str,
    today: str | None = None,
) -> list[behavior.DiffRow]:
    """T-D11 的样板对比：**同一份库、两套口径各算一遍债务**，列出会变的地方（只读）。

    为什么拿这条当样板：它最容易让人觉得"数字怎么突然变了"—— 无截止日的 My Day 老账
    从"不计债"改成"从创建日算起"之后，债务卡可能**多出几张**、卡的**天数会变大**。

    `current` 是当前做法（`core/behavior.py` 传进来）：**现在用哪一侧，哪一侧就摆在
    "当前"那一列** —— 开关翻过之后两侧对调，不能写死。
    """
    t = today or _today()
    counted = {c.root.id: c for c in debt_groups(conn, t, undated_counts=True)}
    uncounted = {c.root.id: c for c in debt_groups(conn, t, undated_counts=False)}
    if current == behavior.VARIANT_UNCOUNTED:
        now, other = uncounted, counted
    else:
        now, other = counted, uncounted

    def label_of(card_id: str) -> str:
        card = now.get(card_id) or other.get(card_id)
        return card.root.title if card is not None else card_id

    rows: list[behavior.DiffRow] = []
    for cid in sorted(set(now) | set(other), key=label_of):
        mine, theirs = now.get(cid), other.get(cid)
        mine_days = mine.overdue_days if mine is not None else None
        theirs_days = theirs.overdue_days if theirs is not None else None
        if mine_days == theirs_days:
            continue  # 两套口径下这张卡没差别 → 不是"会变的地方"
        rows.append(
            behavior.DiffRow(
                label=f"债务卡「{label_of(cid)}」",
                current="不在债务里" if mine_days is None else f"{mine_days} 天",
                shadow="不在债务里" if theirs_days is None else f"{theirs_days} 天",
            )
        )
    return rows


# 注册给 `core/behavior.py`：加一条新口径 = 一条 Rule + 一个 compare + 这一行（见模块开头）。
behavior.register_compare(behavior.KEY_DEBT_UNDATED_MYDAY, compare_debt_undated_myday)


# ---------------------------------------------------------------- 附件 / 要求链接（SR-F1.4 / T-B4）
def add_attachment(
    conn: sqlite3.Connection,
    task_id: str,
    target: str,
    title: str | None = None,
) -> Task:
    """给任务加一条附件/要求链接（T-B4）。同一个 target 加两次是误操作 → 幂等不加。

    只存引用（网址或本地路径），**不复制文件内容**（对齐 conventions 的存储边界）。
    """
    current = get_task(conn, task_id)
    items = attach_mod.add_attachment_item(current.attach, target, title)
    return update_task(conn, task_id, attach=items)


def remove_attachment(conn: sqlite3.Connection, task_id: str, index: int) -> Task:
    """按下标删一条附件（T-B4）。越界 → ValueError（不静默无操作）。"""
    current = get_task(conn, task_id)
    items = attach_mod.remove_attachment_item(current.attach, index)
    return update_task(conn, task_id, attach=items)


def process_repeats(conn: sqlite3.Connection) -> int:
    """Repeat（AC-8 / OP-8）：为「已完成且设了重复」的任务生成下一次。返回本次生成数。

    口径：
    - 基准是**上次完成时间**（`updated_at`，完成即写）；无截止日的任务不生成（无从推算下一次）。
    - **幂等**：同一任务只生成一次下一次 —— 以 `task.repeat.generated` 事实为准
      （该事实随生成一起写入，既做去重依据，也留下可审计痕迹）。
    - 继承：标题 / 分组 / 重复周期 / 是否 My Day（下一次仍进今天，保持动线连续）
      + **优先级**（T-B2：优先级是"这件事有多要紧"，属于任务定义，不该每周期掉回默认「中」）
      + **类型与课程**（T-C12：每周的作业还是那门课的作业，不该每周期掉回「普通」）。
      **备注不继承**（T-B1：备注往往是这一次的具体说明，抄到下一周期会变成误导）。
    """
    generated = 0
    for row in conn.execute(
        "SELECT * FROM tasks WHERE repeat_days IS NOT NULL AND status = ?", (STATUS_DONE,)
    ).fetchall():
        task = _row_to_task(row)
        if task.due_date is None:
            continue
        if _repeat_already_generated(conn, task.id):
            continue
        last = datetime.fromisoformat(task.updated_at).date()
        next_due = (last + timedelta(days=task.repeat_days or 0)).isoformat()
        # 课程可能已经被删掉了：这时**回到"不挂课程"**继续生成下一次，
        # 而不是让生成抛错、连累"完成任务"这条主链（课程删除不级联，任务照旧活着）。
        repeat_course = (
            task.course_id if (task.course_id and course_name(conn, task.course_id)) else None
        )
        next_task = create_task(
            conn,
            title=task.title,
            due_date=next_due,
            group_name=task.group_name,
            repeat_days=task.repeat_days,
            parent_id=task.parent_id,
            is_myday=task.is_myday,
            priority=task.priority,
            task_type=task.task_type,
            course_id=repeat_course,
        )
        _record_repeat_generated(conn, task, next_task, next_due)
        generated += 1
    return generated


def _repeat_already_generated(conn: sqlite3.Connection, task_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM facts WHERE kind = 'task.repeat.generated' AND subject_id = ? LIMIT 1",
        (task_id,),
    ).fetchone()
    return row is not None


def _record_repeat_generated(
    conn: sqlite3.Connection,
    task: Task,
    next_task: Task,
    next_due: str,
) -> None:
    """记录「已生成下一次」事实：既是幂等依据，也让重复动线可追溯。"""
    from timeflow.core import facts as facts_mod

    extra = {
        "title": task.title,
        "repeat_days": task.repeat_days,
        "next_task_id": next_task.id,
        "next_due": next_due,
    }
    facts_mod.record(
        conn,
        kind="task.repeat.generated",
        subject_type="task",
        subject_id=task.id,
        value_num=float(task.repeat_days or 0),
        value_text=next_task.id,
        extra=extra,
        source="desktop",
    )
    facts_mod.publish(
        "task.repeat.generated",
        {"task_id": task.id, "next_task_id": next_task.id, "next_due": next_due, **extra},
    )
