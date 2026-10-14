r"""样例插件（卡 229 / T-G346）：给 timeflow 加「阅读打卡」—— **不改核心一行**。

它声明了两个钩子，正好覆盖卡规格点名的两条真需求：
    ① register_routes → 加一条 API 路由（"加功能"的代表）；
    ② register_rules  → 加一条口径 / 派生读数（复用 `core/behavior.py` 那张表，
      可切、可影子、可一键回退 —— **不并列造第二张口径表**）。

装法（在项目根目录；路径分隔符 Windows 是 ``;``，类 Unix 是 ``:``）：
    set TIMEFLOW_PLUGINS=examples\05_plugin_demo\plugin.py
    python -X utf8 tools/serve.py
    → GET /api/plugins                 看装了什么 / 有没有坏（坏插件会原样报在这）
    → GET /api/plugins/reading/today   新路由：今天记了多少阅读分钟
    → GET /api/settings/behavior       新口径与核心口径同列

卸法：去掉环境变量再重启 → 一切回到原样（装配不落盘、无残留，判据见
`tests/test_plugins.py`）。本插件只用核心的公开接口（`facts` / `behavior`），
遵守同一套口径：facts 只读补记、本地日历、失败不静默。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from timeflow.core import behavior, facts

if TYPE_CHECKING:
    import sqlite3

KIND = "reading.logged"      # 事实 kind：自由字符串，**不用改表**（见 examples/01）
KEY = "reading.counts_today"  # 口径 key：进 core/behavior.py 那张表
COUNT, SKIP = "count", "skip"


def register_routes(app: Any, conn: sqlite3.Connection) -> None:
    """扩展点①：加一条**只读**路由 —— 今天记了多少阅读分钟。"""

    @app.get("/api/plugins/reading/today")
    def reading_today() -> dict[str, Any]:
        # 日期口径与核心一致：本地日历、日界 00:00（不拿 UTC 比今天）
        since = datetime.now().strftime("%Y-%m-%dT00:00:00")
        rows = facts.query(conn, kind=KIND, since=since)
        minutes = sum(int(r.get("value_num") or 0) for r in rows)
        return {"kind": KIND, "entries": len(rows), "minutes": minutes}


def register_rules(add_rule: Any) -> None:
    """扩展点②：加一条「可重算的派生口径」—— 阅读打卡算不算今日产出。

    默认位 = 引入这条口径时的现状（阅读本来不参与"产出"读数 → 让它算，
    是这个插件带给用户的新读数；不想算就在设置页切到"不算"，一键可回）。
    """
    add_rule(
        behavior.Rule(
            key=KEY,
            title="阅读打卡算不算今日产出",
            question="今天记了「阅读打卡」，要不要把它算成今天的一份产出？",
            variants=(
                behavior.Variant(COUNT, "算：阅读也算产出", "本插件引入时的默认做法"),
                behavior.Variant(SKIP, "不算：只看任务", "关掉它，阅读不进产出读数"),
            ),
            default=COUNT,
        ),
        compare_fn=_compare,
    )


def _compare(conn: sqlite3.Connection, current: str) -> list[behavior.DiffRow]:
    """影子对比（只读）：换一侧口径重算同一批阅读事实，报"会变的地方"。"""
    since = datetime.now().strftime("%Y-%m-%dT00:00:00")
    rows = facts.query(conn, kind=KIND, since=since)
    counted, skipped = "算 1 份产出", "不算产出"
    out: list[behavior.DiffRow] = []
    for r in sorted(rows, key=lambda x: (str(x["occurred_at"]), str(x["id"]))):
        mine, theirs = (
            (counted, skipped) if current == COUNT else (skipped, counted)
        )
        out.append(
            behavior.DiffRow(
                label=f"「{r.get('value_text') or '阅读'}」{int(r.get('value_num') or 0)} 分钟",
                current=mine,
                shadow=theirs,
            )
        )
    return out
