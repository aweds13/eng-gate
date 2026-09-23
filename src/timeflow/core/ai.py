"""AI 接口的**边界**（SR-F7.3 / OP-34 / N23 + N46；G 批 · T-G6）。

**规格要什么**（`docs/specification/domains/F7-team.md` R4 + `conventions.md` 第 34 行）：
> AI 接口：本地 API **第一版只读 + 新增，不改不删**。

**用户定的口径**（2026-09-21，见 `复盘/口径定案-待定清单.md` §2，**乙案**）：
> 判据从"改不改"换成"**动的是不是你亲手写的东西**" —— **AI 能勾它自己建的步骤，不能碰你建的**。
> 进展**用子步骤表达**（加步骤本身就是"新增"，天然符合 N23）；AI 的动作要**可审计、可撤销、
> 可回溯"这是 AI 干的"**；**默认关**（口径同 N16"默认收严、用户再放宽"）。

**所以这一版的实际边界**（五句话，代码与界面都按它写）：

1. **读**：任务列表 / 单个任务（含它的步骤树）——只读，不改任何东西；
2. **新增**：建任务、**加步骤**（`parent_id` 指向某任务）——新增即"回报进展"的正规形式；
3. **报告进展**（N46 / OP-32，T-G21）：`POST /api/ai/tasks/{id}/progress` 记一条
   `task.progress.reported` 事实（一句话，`source=ai`，只追加、可撤销）——**任务字段一个字节不动**，
   所以它**不需要** `created_by='ai'`：AI 往**你建的任务**上报进展正是这条链的本意；
   要不要据此勾完成**仍然是你的事**（**不自动标完成** —— 你看到再勾，数字才可信）；
4. **勾完成**：**只能勾 `created_by='ai'` 的**（AI 自己建的）；碰你建的一律 **400 带原话**，
   不静默忽略 —— 静默忽略会让 AI 以为"已经帮你做完了"；
5. **改 / 删**：这一版**没有**这些路由；被显式调用时返回 **403/404 + 一句原话**（`app.py` 里的
   兜底路由），而不是一个含义不明的 404。

**几件容易搞混的事，在这里一次说清**：

- **"谁建的"落在字段上**（`tasks.created_by`，schema v16）：边界要拦得住就必须有事实依据，
  光靠"约定"拦不住代码（这也是 T-G9 的教训：**记录 ≠ 事实**）。
- **AI 的动作照发事实**：状态变化走**和人完全同一条路**（`complete_task(..., actor="ai")`），
  事实的 `source` 记 `ai` —— 于是"AI 干过什么"一条查询就能捞出来（`facts.query`），
  而且**账本口径一点没变**（完成就是完成，不因为谁做的换算法）。
- **"新增"的可回溯性来自 `created_by`**（不是事实）：建任务/加步骤本来就**不发事实**
  （人建任务也不发）—— 为 AI 单独造一个 `task.created` 事实会造成"同一件事两种记法"。
  所以归属看字段、状态变化看事实，两条路各管一段，写在这里免得后人误会。
- **报告进展走的是事实，不是字段**（T-G21）：`created_by` 管不到它 —— 那是**故意**的，
  因为它本来就要能落在你建的任务上（报告 ≠ 改）。撤销也留痕：人侧
  `POST /api/tasks/{id}/progress/retract` 追加一条 `task.progress.retracted` 指回原事实，
  **原事实一个字不删**（同 `review.undone`）；AI 没有撤销接口 —— 撤销是"人对界面上的读数负责"
  的动作，多一条 AI 撤销的路就多一处会漂的边界（AI 真要改口，在下一条报告里说清就够了）。
- **联动导致的完成算系统行为**：AI 勾掉最后一个步骤时父任务会被系统自动完成（OP-12 联动），
  哪怕父任务是你建的 —— 因为**那条规则跟谁点的无关**（你自己点也会这样），
  事实的 `source` 仍如实记 `ai`，所以查得出来。
- **整组 `/api/ai/*` 都要求本机来源**（`require_local_origin`）：网页读不到、也写不了，
  只有本机程序（Hermes / 脚本）能调。
- **默认关**：不开就是所有 `/api/ai/*` 一律 403 带原话（`require_enabled`）——
  与"专注白名单""到点通知"同一套"默认收严"的取向。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from timeflow.core.tasks import manager as tm

if TYPE_CHECKING:
    import sqlite3

# 设置键：`app_settings` 是通用 key/value 表（与附件/专注/归档/口径/导出同一处）
KEY_ENABLED = "ai.enabled"

DEFAULT_ENABLED = False

# 归属值复用任务领域层那一套常量（一处定义，免得两边各写一份字符串）
CREATOR_AI = tm.CREATOR_AI
CREATOR_ME = tm.CREATOR_ME

# 这一版对外**明确提供**的动作（写给界面与 AI 自己看：`GET /api/ai/ping` 会带上它）
SURFACE: tuple[tuple[str, str, str], ...] = (
    ("GET", "/api/ai/ping", "自证：接口开着吗、边界是什么（不读你的数据）"),
    ("GET", "/api/ai/tasks", "读任务列表（只读；可选 view / assignee / limit）"),
    ("GET", "/api/ai/tasks/{id}", "读一个任务 + 它的步骤树（只读）"),
    ("POST", "/api/ai/tasks", "新增：建任务；给 parent_id 就是**加一个步骤**"),
    ("POST", "/api/ai/tasks/{id}/progress", "**回报进展**：往任务上记一条事实（不碰它的字段）"),
    ("POST", "/api/ai/tasks/{id}/complete", "勾完成：**只能勾 AI 自己建的**（你建的 → 400）"),
)

BOUNDARY = (
    "**只读 + 新增 + 勾自己建的**：AI 能读任务、能建任务与步骤，能往任意任务上**记一条进展事实**，"
    "**只能勾它自己建的**；你建的东西它碰不了（会返回 400 带原话，不静默）。"
    "改/删这一版没有接口 —— 调了会明确拒绝（403/404 + 一句原话）。"
)

WHY = (
    "为什么这么收：N23 要的是\"第一版只读+新增，避免覆盖你的操作\"；"
    "而\"回报进展\"有两条正规形式：**加一个步骤**（新增）与**记一条进展事实**"
    "（T-G21，`source=ai`、只追加、可撤销 —— 状态仍由你勾，AI 不改）。"
    "判据因此从\"改不改\"换成\"**动的是不是你亲手写的东西**\"（你 2026-09-21 定的乙案）。"
)

# 给界面用的示例（照抄就能跑；界面不自己拼命令，免得与真实路由漂）
EXAMPLE = (
    "# 先看边界（不会读你的数据）\n"
    "curl http://127.0.0.1:8000/api/ai/ping\n"
    "# 读任务列表 / 读一个任务与它的步骤\n"
    "curl http://127.0.0.1:8000/api/ai/tasks\n"
    "curl http://127.0.0.1:8000/api/ai/tasks/<任务id>\n"
    "# 回报进展（其一）：给某个任务加一个步骤（= 新增）\n"
    'curl -X POST http://127.0.0.1:8000/api/ai/tasks \\\n'
    '  -H "Content-Type: application/json" \\\n'
    '  -d \'{"title":"读完第 3 章","parent_id":"<任务id>"}\'\n'
    "# 回报进展（其二）：往那个任务上记一条进展事实（T-G21）\n"
    'curl -X POST http://127.0.0.1:8000/api/ai/tasks/<任务id>/progress \\\n'
    '  -H "Content-Type: application/json" \\\n'
    '  -d \'{"note":"读完第 3 章，课后 1-5 做完，第 6 题卡住"}\'\n'
    "# 勾掉自己刚建的那个步骤（勾你建的会被 400 拒绝）\n"
    "curl -X POST http://127.0.0.1:8000/api/ai/tasks/<步骤id>/complete"
)


# ---------------------------------------------------------------- 开关（默认关）
def _get_raw(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def _put_raw(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def enabled(conn: sqlite3.Connection, default: bool = DEFAULT_ENABLED) -> bool:
    """AI 接口开着吗（本机设置 → config → **默认关**）。"""
    raw = _get_raw(conn, KEY_ENABLED)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def set_enabled(
    conn: sqlite3.Connection, value: object, default: bool = DEFAULT_ENABLED
) -> dict[str, Any]:
    """打开/关闭 AI 接口。**不猜**：只认布尔（`true/false`、`1/0`、`"on"/"off"`），
    其它一律拒绝 —— 免得"填了个怪值"被静默当成开或关。"""
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        on = True
    elif text in {"0", "false", "no", "off", ""}:
        on = False
    else:
        raise ValueError(f"AI 开关只认 true/false：{value!r}")
    _put_raw(conn, KEY_ENABLED, "true" if on else "false")
    conn.commit()
    return describe(conn, default)


def require_enabled(conn: sqlite3.Connection, default: bool = DEFAULT_ENABLED) -> None:
    """没开就拒绝（带原话）。**默认关**是安全取向，不是 bug。"""
    if enabled(conn, default):
        return
    raise ValueError(
        "AI 接口默认是**关**的：请先在设置页「AI 接口」里打开，再让本机程序调它"
        "（这是 N16「默认收严、用户再放宽」的取向）。"
    )


# ---------------------------------------------------------------- 归属（边界判据）
def is_ai_created(task: tm.Task) -> bool:
    return task.created_by == CREATOR_AI


def creator_label(task: tm.Task) -> str:
    """给人看的一句话（界面徽标与报错原话共用，免得两处措辞各写一份）。"""
    return tm.CREATOR_LABELS.get(task.created_by, task.created_by)


def require_own(conn: sqlite3.Connection, task_id: str) -> tm.Task:
    """**边界的核心一行**：只允许动 AI 自己建的东西。

    - 任务不存在 → `KeyError`（调用方转 404）；
    - 不是你建的（`created_by='me'`）→ **`ValueError` 带原话**，明确告诉你"这是你建的，
      AI 不许碰" —— 不静默跳过（静默跳过会让 AI 以为已经做完了）。
    """
    task = tm.get_task(conn, task_id)  # 不存在 → KeyError
    if task.created_by != CREATOR_AI:
        raise ValueError(
            f"「{task.title}」是**你亲手建的**（created_by={task.created_by}），"
            "AI 只能勾它自己建的 —— 这条边界是 2026-09-21 定案"
            "（乙案：动的是不是你亲手写的东西）。"
        )
    return task


# ---------------------------------------------------------------- 给界面/AI 的自述
def describe(conn: sqlite3.Connection, default: bool = DEFAULT_ENABLED) -> dict[str, Any]:
    """设置页与 `/api/ai/ping` 共用的自述（说明由后端给，界面与 AI 都不复述规则）。"""
    return {
        "enabled": enabled(conn, default),
        "default_enabled": bool(default),
        "configured": _get_raw(conn, KEY_ENABLED) is not None,
        "surface": [{"method": m, "path": p, "what": w} for m, p, w in SURFACE],
        "boundary": BOUNDARY,
        "why": WHY,
        "example": EXAMPLE,
        "note": "AI 的每一次状态变化都发事实（`source=ai`，可审计可撤销）；"
                "它建的任务/步骤带 `created_by=ai` 标记，界面上有徽标。"
                "**回报进展**（T-G21）是往任务上记一条事实 —— 不改那个任务，界面上显示成"
                "「AI 报告：…（时间）」，你不点头它就不会被当成完成。"
                "**默认关**：不开的话这一组接口一律 403。",
    }
