"""`SR-F2.8` **现状特征测试**（T-G141 · 卡 050）—— 只钉现状，零功能。

**为什么有这张卡**（用户 2026-09-26 裁定）：F2.8（重规划/债务重组）在软件开发完成前
**暂时不做**，但要一张**只钉现状**的护栏：现在正确的语义是
「债务是**读出来的**（纯派生），没有任何清零/重组的写库路径」。
将来做 F2.8 时最容易犯的错就是把它实现成**写库清零**（那就变成两套真相）。
这条护栏让将来那个人必须**先有意识地改掉这个测试**，而不是悄悄把语义弄坏。

钉三条（每条都有反向判据，改动见卡规格 §2.3 的「三贴」）：
- ① 债务读路径（`overdue_tasks` / `debt_groups` / `debt_count`，真名 grep 自
  `src/timeflow/core/tasks/manager.py`）执行期间**对数据库的写语句必须是 0**，
  且同输入同输出（纯函数性质）；
- ② 逾期的学校硬考核（`task_type ∈ COURSE_TASK_TYPES`，即 作业/考试/论文/小测，
  词表派生自 `manager.VALID_TASK_TYPES`，不写死）计入债务，且**反复读、再读也在**
  —— 没有「读一次就消化」的路径；
- ③ 不存在清零/重组路径：接口路由表里没有带写方法的债务/重组端点，
  且 `src/**/*.py` 里 grep `重组|重规划|replan|clear_debt|reset_debt` **零命中**
  —— 将来有人加了路由或实现 → 这里红，那正是它该做的事。

判据都是**相对**的：真名、类型词表、路由表都从源码/`create_app` 现场推导，
不写死行号、条数、编号（会漂）。

与既有测试的关系：`tests/test_task_debt_card_line.py`（T-F9）钉的是债务**归卡语义**
（父卡/挂步/三处同源），本文件钉的是**「纯派生、零写库、无清零路径」**这个不变式
—— 两者不重叠，故独立成文件（卡规格 §2.6）。
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from timeflow.api.app import create_app
from timeflow.core import facts as facts_mod
from timeflow.core import tasks as tm
from timeflow.storage import db as db_mod

# 写语句判据：任何 INSERT/UPDATE/DELETE/REPLACE/建表/删表/改表/VACUUM 都算写。
_WRITE_SQL = re.compile(r"\b(INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER|VACUUM)\b", re.I)

# 清零/重组的实现判据（与卡规格 §2.3③ 同一词表，直接扫源码，让「加了实现」必红）。
_FORBIDDEN_SRC = re.compile(r"重组|重规划|replan|clear_debt|reset_debt")

# 路由判据：写方法（POST/PUT/PATCH/DELETE）的端点路径里不许出现债务/重组字样。
# 读路径（GET /api/overdue、GET /api/summary 里的 debt_items）不受影响。
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_FORBIDDEN_ROUTE = re.compile(r"debt|replan|重规划|重组", re.I)

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "debt_derived.db"))
    facts_mod.clear()
    yield c
    c.close()
    facts_mod.clear()


def _ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


# ---------------------------------------------------------------- 钉①：纯派生，读时零写库


def test_debt_read_paths_issue_zero_write_sql(conn) -> None:  # type: ignore[no-untyped-def]
    """债务读路径执行期间，落在这条连接上的**写语句必须是 0**。

    判法（选型见复盘）：用 sqlite3 自带的 `set_trace_callback` 记录这条连接上
    **真实执行**的每一条 SQL —— 不 patch 内部、不依赖有没有 UoW 抽象，
    语句只要发出就躲不掉；按写语句正则筛出写操作，一条都不许有。
    """
    today = date.today().isoformat()
    stmts: list[str] = []
    conn.set_trace_callback(stmts.append)
    try:
        tm.overdue_tasks(conn, today)
        tm.debt_groups(conn, today)
        tm.debt_count(conn, today)
    finally:
        conn.set_trace_callback(None)
    writes = [s for s in stmts if _WRITE_SQL.search(s)]
    assert writes == []


def test_debt_reads_are_pure_functions_of_the_db(conn) -> None:  # type: ignore[no-untyped-def]
    """**同输入同输出**：同一份库、同一个「今天」，读两遍结果逐项相等（纯函数性质）。"""
    today = date.today().isoformat()
    tm.create_task(conn, "高数作业", due_date=_ago(9))
    tm.create_task(conn, "另一件事", due_date=_ago(1))

    assert tm.overdue_tasks(conn, today) == tm.overdue_tasks(conn, today)
    assert tm.debt_groups(conn, today) == tm.debt_groups(conn, today)
    assert tm.debt_count(conn, today) == tm.debt_count(conn, today) == 2


# ---------------------------------------------------------------- 钉②：逾期硬考核计入债务且不消失


@pytest.mark.parametrize("task_type", tm.COURSE_TASK_TYPES)
def test_overdue_hard_assessment_counts_and_never_vanishes(
    conn,  # type: ignore[no-untyped-def]
    task_type,  # type: ignore[no-untyped-def]
) -> None:
    """已逾期的 作业/考试/论文/小测 计入债务，且**反复读、再读也在**。

    F2.8 的红线之一是「学校硬考核逾期**不可**重组清零」—— 现状里它不仅没有清零路径
    （钉③），连「读一次就消化」的隐性路径也不许有：债务是每次**重新读出来**的。
    """
    today = date.today().isoformat()
    task = tm.create_task(conn, f"{task_type}·逾期硬考核", due_date=_ago(3), task_type=task_type)

    for _ in range(3):  # 反复读：读数不因「被读过」而变化
        cards = tm.debt_groups(conn, today)
        assert [c.root.id for c in cards] == [task.id]
        assert tm.debt_count(conn, today) == 1
        assert task.id in {t.id for t in tm.overdue_tasks(conn, today)}


# ---------------------------------------------------------------- 钉③：不存在清零/重组路径


def test_no_write_route_for_debt_reset_or_replan(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """接口路由表（真源 = `create_app()` 现场注册出来的路由）里，
    **写方法**的端点不许带债务/重组字样 —— 有人加了 `POST /api/debt/reset` 之类 → 红。"""
    app = create_app(str(tmp_path / "routes.db"))
    offenders = sorted(
        f"{sorted(r.methods)} {r.path}"
        for r in app.routes
        if getattr(r, "methods", set()) & _WRITE_METHODS
        and _FORBIDDEN_ROUTE.search(getattr(r, "path", ""))
    )
    assert offenders == []


def test_no_replan_or_clear_implementation_in_src() -> None:
    """`src/**/*.py` 里 grep `重组|重规划|replan|clear_debt|reset_debt` 必须**零命中**
    —— 有人往 src 里写了重组/清零实现（哪怕只是先埋个函数名）→ 红。"""
    hits = [
        str(p.relative_to(REPO_ROOT))
        for p in sorted((REPO_ROOT / "src").rglob("*.py"))
        if _FORBIDDEN_SRC.search(p.read_text(encoding="utf-8"))
    ]
    assert hits == []
