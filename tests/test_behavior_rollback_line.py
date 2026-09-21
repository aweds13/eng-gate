"""D 批 · T-D11：口径开关 + 影子对比（SR-NF8 / N37「敏感改动 shadow + 一键回退」）。

**规格原话**（`docs/specification/nonfunctional.md`）：
> 必须：模块单测+回归；敏感改动（改基线/排序）**shadow + 一键回退**（开关默认不改变现状）。

**口径（2026-09-21 用户选 B 案）**：机制**前向生效** + 拿 T-F8 的**计债口径**当样板做一次
真实对比；边界一并钉死 —— **只有"可重算的派生口径"进这张表**，动数据的事（schema 迁移 /
改状态 / 删东西）走既有的**备份与恢复**，不假装能一键回退。

覆盖：
- **默认位 = 现状位**：没写过设置就是"什么都没变"（T-F8 的计债口径照旧生效）；
- 切到老口径后债务数字真的变（卡没了），而**数据没被动过**（任务、My Day、逾期栏、天数都在）；
- **一键回退**（reset）= 删掉本机那条设置回到默认位，不是把当前值再写一遍；
- 开关**只管债务这一侧**：有截止日的逾期卡不受影响，逾期栏条目与天数也不受影响；
- **影子**：只报"会变的地方"、**纯读**（跑完数字与事实都没变）、两侧不会说反（切换后对调）、
  没差异就说"没有区别"、样例按 `MAX_SAMPLES` 截断；
- **护栏**：注册表里只能是 `derived` 口径、`default` 必须是自己的某个做法、key 不重复；
- 账本 / 洞察 / 自检**共用同一个读数**（切一次口径三处一起变，不三处各算一套）；
- API：`GET/PUT /api/settings/behavior` + `POST /api/settings/behavior/reset`（非法 key/做法 400）。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import behavior
from timeflow.core import facts as facts_mod
from timeflow.core import feedback as fb
from timeflow.core import insights as ins
from timeflow.core import tasks as tm
from timeflow.core.ledger import ledger
from timeflow.storage import db as db_mod

KEY = behavior.KEY_DEBT_UNDATED_MYDAY


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "behavior.db"))
    facts_mod.clear()
    yield c
    c.close()
    facts_mod.clear()


def _client(tmp_path, name: str = "behavior_api.db") -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(create_app(str(tmp_path / name)))


def _ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def _backdate(conn, task_id: str, stamp: str) -> None:  # type: ignore[no-untyped-def]
    """直接改 `created_at`：字段白名单里没有它（"什么时候建的"不该被编辑）。"""
    conn.execute("UPDATE tasks SET created_at = ? WHERE id = ?", (stamp, task_id))
    conn.commit()


def _stale_myday(conn, title: str, days: int):  # type: ignore[no-untyped-def]
    """无截止日、`days` 天前就进了 My Day 的老账（T-F8 那种"老任务"）。"""
    task = tm.create_task(conn, title, is_myday=True)
    _backdate(conn, task.id, _ago(days) + "T09:00:00")
    return task


def _setting_rows(conn) -> list[str]:  # type: ignore[no-untyped-def]
    """本机存了哪几条**口径设置**（键带前缀，与附件/专注/提醒那些设置同表不同前缀）。"""
    rows = conn.execute(
        "SELECT key FROM app_settings WHERE key LIKE ? ORDER BY key",
        (behavior.SETTING_PREFIX + "%",),
    ).fetchall()
    return [str(r["key"]) for r in rows]


# ---------------------------------------------------------------- 默认位 = 现状位


def test_default_is_status_quo(conn) -> None:  # type: ignore[no-untyped-def]
    """没动过设置 = 停在默认位 = **现状位**：T-F8 的计债口径照旧生效。"""
    rule = behavior.rule_by_key(KEY)
    assert rule.default == behavior.VARIANT_FROM_CREATED  # 已上线的口径，现状位就是"新做法"
    assert behavior.current_variant(conn, rule) == rule.default
    assert behavior.is_default(conn, rule) is True
    assert behavior.undated_myday_counted(conn) is True

    _stale_myday(conn, "昨天没做完的", 5)
    assert tm.debt_count(conn) == 1
    assert tm.debt_groups(conn)[0].overdue_days == 5  # 天数从创建日算起


def test_switch_to_legacy_side_drops_the_debt(conn) -> None:  # type: ignore[no-untyped-def]
    """切到老口径（T-F8 之前）：这类老账**不进债务卡**，但**数据一点没动**。"""
    task = _stale_myday(conn, "昨天没做完的", 5)
    assert tm.debt_count(conn) == 1

    behavior.set_variant(conn, KEY, behavior.VARIANT_UNCOUNTED)
    assert behavior.undated_myday_counted(conn) is False
    assert tm.debt_count(conn) == 0
    assert tm.debt_groups(conn) == []

    # **数据没被动过**：任务还在、还在 My Day、逾期栏照旧列它、天数照旧算得出来
    # （开关是"怎么读"，不是"改数据"—— 逾期栏是干活的地方，不该被债务口径牵动）
    live = tm.get_task(conn, task.id)
    assert live.is_myday is True
    assert {t.id for t in tm.overdue_tasks(conn)} == {task.id}
    assert tm.overdue_days(live) == 5


def test_reset_goes_back_to_default(conn) -> None:  # type: ignore[no-untyped-def]
    """一键回退 = **删掉本机那条设置**（回到默认位），不是把当前值再写一遍。"""
    _stale_myday(conn, "昨天没做完的", 5)
    behavior.set_variant(conn, KEY, behavior.VARIANT_UNCOUNTED)
    assert tm.debt_count(conn) == 0
    assert _setting_rows(conn) == [behavior.SETTING_PREFIX + KEY]

    behavior.reset_variant(conn, KEY)
    assert _setting_rows(conn) == []          # 设置被删掉，而不是留个"等于默认"的值
    assert behavior.is_default(conn, behavior.rule_by_key(KEY)) is True
    assert tm.debt_count(conn) == 1


def test_set_variant_is_idempotent(conn) -> None:  # type: ignore[no-untyped-def]
    """设同一个值两次不会写出两行（`app_settings` 是 key/value，靠 `ON CONFLICT` 覆盖）。"""
    behavior.set_variant(conn, KEY, behavior.VARIANT_UNCOUNTED)
    behavior.set_variant(conn, KEY, behavior.VARIANT_UNCOUNTED)
    assert _setting_rows(conn) == [behavior.SETTING_PREFIX + KEY]


# ---------------------------------------------------------------- 只管债务这一侧


def test_switch_leaves_due_dated_debt_alone(conn) -> None:  # type: ignore[no-untyped-def]
    """开关只管"无截止日的 My Day 老账"：有截止日的逾期卡两套口径下都在。"""
    fixed = tm.create_task(conn, "有截止日的逾期", due_date=_ago(9))
    _stale_myday(conn, "昨天没做完的", 5)

    assert tm.debt_count(conn) == 2
    behavior.set_variant(conn, KEY, behavior.VARIANT_UNCOUNTED)
    cards = tm.debt_groups(conn)
    assert [(c.root.id, c.overdue_days) for c in cards] == [(fixed.id, 9)]


# ---------------------------------------------------------------- 影子对比


def test_shadow_lists_only_what_changes(conn) -> None:  # type: ignore[no-untyped-def]
    """影子只报**会变的地方**：老账那张卡会消失 → 1 处不同，另一列写清变成什么。"""
    task = _stale_myday(conn, "昨天没做完的", 5)
    tm.create_task(conn, "有截止日的逾期", due_date=_ago(9))  # 不受影响 → 不该进差异

    sh = behavior.report(conn)["items"][0]["shadow"]
    assert sh["available"] is True
    assert sh["diff_count"] == 1
    assert sh["samples"] == [
        {"label": f"债务卡「{task.title}」", "current": "5 天", "shadow": "不在债务里"}
    ]
    assert "1 处不同" in sh["summary"]


def test_shadow_is_read_only(conn) -> None:  # type: ignore[no-untyped-def]
    """影子是**纯读**：跑完债务数字、任务状态、事实条数都不变。"""
    task = _stale_myday(conn, "昨天没做完的", 5)
    before = (tm.debt_count(conn), tm.get_task(conn, task.id).status, facts_mod.count(conn))

    behavior.report(conn)
    behavior.report(conn)

    after = (tm.debt_count(conn), tm.get_task(conn, task.id).status, facts_mod.count(conn))
    assert after == before
    assert behavior.is_default(conn, behavior.rule_by_key(KEY)) is True  # 影子不会偷偷动开关


def test_shadow_sides_swap_with_current(conn) -> None:  # type: ignore[no-untyped-def]
    """切换之后两侧**对调**：不能把"当前"和"影子"说反（这是最容易写错的地方）。"""
    _stale_myday(conn, "昨天没做完的", 5)
    behavior.set_variant(conn, KEY, behavior.VARIANT_UNCOUNTED)

    sh = behavior.report(conn)["items"][0]["shadow"]
    assert sh["variant"] == behavior.VARIANT_FROM_CREATED
    assert sh["samples"][0]["current"] == "不在债务里"
    assert sh["samples"][0]["shadow"] == "5 天"


def test_shadow_says_no_difference(conn) -> None:  # type: ignore[no-untyped-def]
    """没有会变的东西就明说"没有区别"（不许编差异出来）。"""
    tm.create_task(conn, "有截止日的逾期", due_date=_ago(3))
    sh = behavior.report(conn)["items"][0]["shadow"]
    assert sh["available"] is True
    assert sh["diff_count"] == 0
    assert sh["samples"] == []
    assert "没有区别" in sh["summary"]


def test_shadow_samples_are_capped(conn) -> None:  # type: ignore[no-untyped-def]
    """样例按 `MAX_SAMPLES` 截断：差异条数照实报，界面别变成表格软件。"""
    for i in range(behavior.MAX_SAMPLES + 2):
        _stale_myday(conn, f"老账 {i}", i + 1)

    sh = behavior.report(conn)["items"][0]["shadow"]
    assert sh["diff_count"] == behavior.MAX_SAMPLES + 2
    assert len(sh["samples"]) == behavior.MAX_SAMPLES


# ---------------------------------------------------------------- 三处同一个数字


def test_ledger_insights_selfcheck_share_the_switch(conn) -> None:  # type: ignore[no-untyped-def]
    """账本 / 洞察 / 自检**共用**同一个读数：切一次口径，三处一起变（不三处各算一套）。"""
    _stale_myday(conn, "昨天没做完的", 5)
    today = date.today().isoformat()
    assert (ledger.summary(conn).debt_count, ins._cell(conn, today).debt_count,
            fb.self_check(conn, today)["debt_count"]) == (1, 1, 1)

    behavior.set_variant(conn, KEY, behavior.VARIANT_UNCOUNTED)
    assert (ledger.summary(conn).debt_count, ins._cell(conn, today).debt_count,
            fb.self_check(conn, today)["debt_count"]) == (0, 0, 0)


# ---------------------------------------------------------------- 护栏（收紧口径）


def test_registry_is_derived_and_consistent() -> None:
    """**只有可重算的派生口径能进表**（T-D11 定的边界）：注册表自带这几条护栏。"""
    keys = [r.key for r in behavior.RULES]
    assert len(keys) == len(set(keys))  # key 不重复
    assert behavior.RULES, "注册表不能是空的 —— 那这个机制就是空转的"
    for rule in behavior.RULES:
        ids = [v.id for v in rule.variants]
        assert rule.kind == behavior.DERIVED, rule.key  # 不可逆的改动不许进这张表
        assert len(ids) >= 2, rule.key                  # 只有一种做法就没有"另一侧"可比
        assert len(ids) == len(set(ids)), rule.key
        assert rule.default in ids, rule.key            # 默认位必须是自己的某个做法
        assert rule.title and rule.question and rule.variants[0].label


def test_unknown_key_or_variant_is_rejected(conn) -> None:  # type: ignore[no-untyped-def]
    """非法 key / 非法做法一律 ValueError 带原话（**不静默落默认值**）。"""
    with pytest.raises(ValueError, match="没有这条口径"):
        behavior.set_variant(conn, "tasks.nope", behavior.VARIANT_FROM_CREATED)
    with pytest.raises(ValueError, match="没有这种做法"):
        behavior.set_variant(conn, KEY, "nope")
    with pytest.raises(ValueError):
        behavior.set_variant(conn, 123, behavior.VARIANT_FROM_CREATED)
    with pytest.raises(ValueError):
        behavior.reset_variant(conn, "tasks.nope")
    assert _setting_rows(conn) == []  # 三连败之后仍没写出任何设置


def test_dirty_setting_falls_back_to_default(conn) -> None:  # type: ignore[no-untyped-def]
    """库里那条值不认识（手改过库/老版本）→ 退回默认位，不让整个账本读不出来。"""
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?,?)",
        (behavior.SETTING_PREFIX + KEY, "老版本的怪值"),
    )
    conn.commit()
    rule = behavior.rule_by_key(KEY)
    assert behavior.current_variant(conn, rule) == rule.default
    assert tm.debt_count(conn) == 0  # 没有老账，读数正常（没炸）


# ---------------------------------------------------------------- API


def test_api_reports_and_switches_and_resets(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """三条路由：读整表（含影子）/ 切一条口径 / 回默认位。"""
    client = _client(tmp_path)
    task = client.post("/api/tasks", json={"title": "昨天没做完的", "is_myday": True}).json()
    # 「什么时候建的」没有编辑入口 → 直接改库造一张"5 天前的老账"（与领域测试同一手法）
    raw = db_mod.connect(str(tmp_path / "behavior_api.db"))
    try:
        _backdate(raw, task["id"], _ago(5) + "T09:00:00")
    finally:
        raw.close()

    body = client.get("/api/settings/behavior").json()
    assert body["note"] and body["switch_note"]       # 口径说明由后端给，前端不复述
    item = body["items"][0]
    assert item["key"] == KEY and item["is_default"] is True
    assert [v["id"] for v in item["variants"]] == [behavior.VARIANT_FROM_CREATED,
                                                  behavior.VARIANT_UNCOUNTED]
    assert item["shadow"]["diff_count"] == 1
    assert client.get("/api/summary").json()["debt_count"] == 1

    switched = client.put("/api/settings/behavior",
                          json={"key": KEY, "variant": behavior.VARIANT_UNCOUNTED}).json()
    assert switched["items"][0]["current"] == behavior.VARIANT_UNCOUNTED
    assert switched["items"][0]["is_default"] is False
    assert client.get("/api/summary").json()["debt_count"] == 0   # 界面上数字真的跟着变

    back = client.post("/api/settings/behavior/reset", json={"key": KEY}).json()
    assert back["items"][0]["is_default"] is True
    assert client.get("/api/summary").json()["debt_count"] == 1


def test_api_rejects_bad_key_and_variant(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """400 带后端原话（不静默落默认值、也不 500）。"""
    client = _client(tmp_path, "behavior_bad.db")
    bad_key = client.put("/api/settings/behavior", json={"key": "tasks.nope", "variant": "x"})
    assert bad_key.status_code == 400
    assert "没有这条口径" in bad_key.json()["detail"]

    bad_variant = client.put("/api/settings/behavior", json={"key": KEY, "variant": "x"})
    assert bad_variant.status_code == 400
    assert "没有这种做法" in bad_variant.json()["detail"]

    missing = client.put("/api/settings/behavior", json={})
    assert missing.status_code == 400
    assert client.post("/api/settings/behavior/reset", json={}).status_code == 400
