"""F 批 · T-F2：完成 N 天后进档案 + 档案视图（N11 的任务存档）。

**口径（用户 2026-09-21 定，`复盘/口径定案-待定清单.md` §1）**：
- 「完成」不是立刻进档案，而是**过几天再归档** —— N 可配置，默认 3 天；
- 判定做成**派生**（完成日 + N ≤ 今天 ⇒ 默认视图不再显示），**不写回状态**：
  写回就需要定时器/惰性写入点，而本项目明确避免定时任务（与 T-F7 逾期同一套理由）；
- **档案视图把两拨合起来**：手动归档的 + 完成满 N 天自动收入的，
  每条显示「过去尝试」次数（T-F3 的事实）与备注（N11 的"详细信息写在本子、列表记笔记名"）。

覆盖：
- N 的读/写/边界/坏数据兜底（设置存 `app_settings`，默认值来自 config.toml）；
- 派生归档的**临界点**（刚好 N 天 = 已归档，N−1 天 = 还在列表里）；
- **完成日取事实、不取 `updated_at`**：完成之后编辑一下（`updated_at` 被推后）不会重置归档倒计时
  —— 这是本卡选事实的直接理由，专门钉一条；
- 派生归档**不改状态**（`status` 还是「完成」，可撤销完成回到列表）；
- 档案视图：自动/手动两种来源、排序、「试了几回」与备注；
- 智能视图（important/planned/flagged）同样不再显示自动归档的；
- API：`GET /api/tasks/archived`（含 `auto_archived`/`completed_on`/`attempt_count`）、
  `GET/PUT /api/settings/archive`（非法值 400）。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import facts as facts_mod
from timeflow.core import tasks as tm
from timeflow.storage import db as db_mod


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "archive.db"))
    facts_mod.clear()
    yield c
    c.close()
    facts_mod.clear()


def _client(tmp_path, name: str = "archive_api.db") -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(create_app(str(tmp_path / name)))


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def _backdate_done(conn, task_id: str, days: int) -> None:  # type: ignore[no-untyped-def]
    """把「完成」事实挪到 N 天前 —— 模拟"这任务是几天前完成的"。

    为什么改事实而不是 `updated_at`：本卡的判定就是看事实（见 `completion_dates` 的注释），
    改 updated_at 反而测不到"编辑不影响倒计时"这件事。
    """
    conn.execute(
        "UPDATE facts SET occurred_at = ? WHERE kind = 'task.completed' AND subject_id = ?",
        (_days_ago(days) + "T10:00:00", task_id),
    )
    conn.commit()


# ---------------------------------------------------------------- N 的设置


def test_default_archive_days_is_three(conn) -> None:  # type: ignore[no-untyped-def]
    """默认「完成 3 天后进档案」；本机改过用表里的值，且**读的是整数**。"""
    assert tm.archive_after_days(conn) == 3
    assert tm.DEFAULT_ARCHIVE_AFTER_DAYS == 3

    assert tm.set_archive_after_days(conn, 7) == 7
    assert tm.archive_after_days(conn) == 7
    assert tm.set_archive_after_days(conn, "0") == 0  # 界面传字符串也认（0 = 当天就收）
    assert tm.archive_after_days(conn) == 0


def test_archive_days_rejects_bad_values(conn) -> None:  # type: ignore[no-untyped-def]
    """非法值一律拒绝，**不静默落默认值**（否则界面显示的值和实际口径会不一致）。"""
    for bad in (-1, 366, "三天", None, True, 3.5):
        with pytest.raises(ValueError):
            tm.set_archive_after_days(conn, bad)
    assert tm.archive_after_days(conn) == 3  # 一个坏值都没写进去


def test_broken_setting_falls_back_to_default(conn) -> None:  # type: ignore[no-untyped-def]
    """表里是坏数据（手工改过）→ 退回默认值，不让一条坏设置把任务列表打挂。"""
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?,?)",
        (tm.KEY_ARCHIVE_AFTER_DAYS, "很久"),
    )
    conn.commit()
    assert tm.archive_after_days(conn) == 3


def test_archive_settings_readout(conn) -> None:  # type: ignore[no-untyped-def]
    """给界面的读数包含当前值/默认值/上限/口径说明（规则只有一份，前端不复述）。"""
    info = tm.archive_settings(conn)
    assert info["after_days"] == 3
    assert info["default_after_days"] == 3
    assert info["max_after_days"] == tm.MAX_ARCHIVE_AFTER_DAYS
    assert "撤销完成" in str(info["note"])


# ---------------------------------------------------------------- 派生归档


def test_completed_task_is_filed_after_n_days(conn) -> None:  # type: ignore[no-untyped-def]
    """**临界点**：刚好满 N 天 = 已进档案（默认视图不再显示）；N−1 天 = 还在列表里。"""
    task = tm.create_task(conn, "三天前完成的")
    tm.complete_task(conn, task.id)

    _backdate_done(conn, task.id, 2)
    assert [t.id for t in tm.list_tasks(conn)] == [task.id]  # 第 2 天：还在
    assert tm.archive_entries(conn) == []

    _backdate_done(conn, task.id, 3)
    assert tm.list_tasks(conn) == []  # 第 3 天：收走
    entries = tm.archive_entries(conn)
    assert [(e.task.id, e.auto) for e in entries] == [(task.id, True)]
    assert entries[0].completed_on == _days_ago(3)


def test_filing_does_not_write_back_status(conn) -> None:  # type: ignore[no-untyped-def]
    """派生归档**不改状态**：`status` 还是「完成」，撤销完成就回到列表（不需要"撤销归档"）。"""
    task = tm.create_task(conn, "收走的事")
    tm.complete_task(conn, task.id)
    _backdate_done(conn, task.id, 9)

    assert tm.list_tasks(conn) == []
    assert tm.get_task(conn, task.id).status == tm.STATUS_DONE  # 没被偷偷改成「归档」

    tm.uncomplete_task(conn, task.id)
    assert [t.id for t in tm.list_tasks(conn)] == [task.id]  # 撤销完成 = 回到列表


def test_editing_after_done_does_not_reset_the_clock(conn) -> None:  # type: ignore[no-untyped-def]
    """完成之后**编辑一下不会重置归档倒计时**（这是取事实、不取 `updated_at` 的直接理由）。

    `updated_at` 是"最后一次改动"：补一句备注就会把它推到今天 —— 若按它算，
    这任务就要再等 N 天，而用户看到的却是"我三天前就完成了"。
    """
    task = tm.create_task(conn, "完成后又补了备注")
    tm.complete_task(conn, task.id)
    _backdate_done(conn, task.id, 5)
    assert tm.archive_entries(conn)[0].completed_on == _days_ago(5)

    tm.update_task(conn, task.id, note="补一句：这题最后是问同学才懂的")
    assert tm.get_task(conn, task.id).updated_at[:10] == _days_ago(0)  # updated_at 被推到了今天
    assert tm.archive_entries(conn)[0].completed_on == _days_ago(5)  # 完成日没变
    assert tm.list_tasks(conn) == []  # 照样在档案里


def test_n_zero_files_on_the_same_day(conn) -> None:  # type: ignore[no-untyped-def]
    """N = 0（"当天就收走"）也成立：完成当天就进档案 —— 边界值不当特例跳过。"""
    tm.set_archive_after_days(conn, 0)
    task = tm.create_task(conn, "做完就收")
    tm.complete_task(conn, task.id)
    assert tm.list_tasks(conn) == []
    assert [e.task.id for e in tm.archive_entries(conn)] == [task.id]


def test_done_without_fact_falls_back_to_updated_at(conn) -> None:  # type: ignore[no-untyped-def]
    """没有完成事实的老数据（手工造的库）→ 退回 `updated_at` 的日期，**不猜、不报错**。"""
    task = tm.create_task(conn, "老数据：没有完成事实")
    conn.execute("UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                 (tm.STATUS_DONE, _days_ago(10) + "T09:00:00", task.id))
    conn.commit()

    assert tm.get_task(conn, task.id).status == tm.STATUS_DONE
    assert tm.completed_on(conn, tm.get_task(conn, task.id)) == _days_ago(10)
    assert [e.task.id for e in tm.archive_entries(conn)] == [task.id]


def test_manual_archive_and_auto_archive_share_one_view(conn) -> None:  # type: ignore[no-untyped-def]
    """档案视图 = 手动归档的 + 完成满 N 天自动收入的（两拨合起来，界面用徽标分开）。"""
    manual = tm.create_task(conn, "我自己收的")
    tm.archive_task(conn, manual.id)

    auto = tm.create_task(conn, "过几天自然收的")
    tm.complete_task(conn, auto.id)
    _backdate_done(conn, auto.id, 4)

    entries = tm.archive_entries(conn)
    assert sorted((e.task.title, e.auto) for e in entries) == [
        ("我自己收的", False), ("过几天自然收的", True)
    ]
    # 手动归档的那条没有完成日（它从没完成过）—— 不给一个编出来的日期
    manual_entry = next(e for e in entries if e.task.id == manual.id)
    assert manual_entry.completed_on is None


def test_archive_view_is_newest_first(conn) -> None:  # type: ignore[no-untyped-def]
    """按"进档案的那天"降序：回头查阅时新的先看。"""
    for title, days in (("最早的", 9), ("中间的", 5), ("最近的", 3)):
        t = tm.create_task(conn, title)
        tm.complete_task(conn, t.id)
        _backdate_done(conn, t.id, days)

    assert [e.task.title for e in tm.archive_entries(conn)] == ["最近的", "中间的", "最早的"]


def test_smart_views_also_hide_auto_filed(conn) -> None:  # type: ignore[no-untyped-def]
    """智能视图与「全部任务」同一条基线：自动归档的不再冒出来（否则"收走"只是半句话）。"""
    task = tm.create_task(conn, "重要的老活", priority="高")
    tm.complete_task(conn, task.id)
    assert [t.id for t in tm.tasks_in_view(conn, tm.VIEW_IMPORTANT)] == [task.id]

    _backdate_done(conn, task.id, 4)
    assert tm.tasks_in_view(conn, tm.VIEW_IMPORTANT) == []


def test_completion_dates_is_one_query_for_many(conn) -> None:  # type: ignore[no-untyped-def]
    """批版取完成日：一次查多个任务，撤销完成再完成取**最新**那次。"""
    a = tm.create_task(conn, "甲")
    b = tm.create_task(conn, "乙")
    tm.complete_task(conn, a.id)
    tm.complete_task(conn, b.id)
    _backdate_done(conn, a.id, 6)
    _backdate_done(conn, b.id, 2)

    dates = tm.completion_dates(conn, [a.id, b.id])
    assert dates == {a.id: _days_ago(6), b.id: _days_ago(2)}
    assert tm.completion_dates(conn, []) == {}

    # 撤销完成再完成：多一条事实，取最新那条（= 现在这次完成）
    tm.uncomplete_task(conn, a.id)
    tm.complete_task(conn, a.id)
    assert tm.completion_dates(conn, [a.id])[a.id] == _days_ago(0)


def test_attempt_counts_batch(conn) -> None:  # type: ignore[no-untyped-def]
    """批版「试了几回」（档案视图一屏列表用）：没有失败记录的任务不出现在结果里。"""
    a = tm.create_task(conn, "甲")
    b = tm.create_task(conn, "乙")
    c = tm.create_task(conn, "丙")
    tm.attempt_failed(conn, a.id, "试了两次")
    tm.attempt_failed(conn, a.id)
    tm.attempt_failed(conn, c.id)

    assert tm.attempt_counts(conn, [a.id, b.id, c.id]) == {a.id: 2, c.id: 1}
    assert tm.attempt_counts(conn, []) == {}


# ---------------------------------------------------------------- API


def test_api_archive_view_shows_history(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """档案接口：`auto_archived` / `completed_on` / `attempt_count` / 备注都在一条里。"""
    client = _client(tmp_path)
    task = client.post("/api/tasks", json={"title": "反复试过的活"}).json()
    client.post(f"/api/tasks/{task['id']}/attempt-failed", json={"note": "先试了 A 方案"})
    client.post(f"/api/tasks/{task['id']}/attempt-failed", json={"note": "B 方案也不行"})
    client.patch(f"/api/tasks/{task['id']}", json={"note": "笔记：第三章的推导"})
    client.post(f"/api/tasks/{task['id']}/complete")

    # 刚完成：还在默认列表里，档案里没有
    assert [t["id"] for t in client.get("/api/tasks").json()] == [task["id"]]
    assert client.get("/api/tasks/archived").json() == []

    # 接口层没有"改事实时间"的入口（也不该有），测试直接开库把完成事实挪到 3 天前
    from timeflow.storage import db as _db

    raw = _db.connect(str(tmp_path / "archive_api.db"))
    _backdate_done(raw, task["id"], 3)
    raw.close()

    archived = client.get("/api/tasks/archived").json()
    assert len(archived) == 1
    item = archived[0]
    assert item["auto_archived"] is True
    assert item["attempt_count"] == 2
    assert item["completed_on"] == _days_ago(3)
    assert item["note"] == "笔记：第三章的推导"
    assert item["status"] == "完成"  # 派生归档不改状态
    assert client.get("/api/tasks").json() == []  # 默认列表里已经收走
    # 详情与其它接口照旧能查到它（撤销完成就能回到列表）
    assert client.get(f"/api/tasks/{task['id']}").json()["status"] == "完成"


def test_api_archive_view_includes_manual_archive(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """手动归档的也在同一条接口里，`auto_archived` 为 false（界面据此换按钮）。"""
    client = _client(tmp_path)
    task = client.post("/api/tasks", json={"title": "手动收的"}).json()
    client.post(f"/api/tasks/{task['id']}/archive")

    archived = client.get("/api/tasks/archived").json()
    assert [(x["title"], x["auto_archived"], x["completed_on"]) for x in archived] == [
        ("手动收的", False, None)
    ]


def test_api_archive_settings_roundtrip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """设置读写：默认 3；改成 7 之后立刻生效（完成 5 天的任务还是"没到点"）。"""
    client = _client(tmp_path)
    assert client.get("/api/settings/archive").json()["after_days"] == 3

    moved = client.put("/api/settings/archive", json={"after_days": 7}).json()
    assert moved["after_days"] == 7
    assert moved["default_after_days"] == 3

    task = client.post("/api/tasks", json={"title": "五天前完成的"}).json()
    client.post(f"/api/tasks/{task['id']}/complete")
    from timeflow.storage import db as _db

    raw = _db.connect(str(tmp_path / "archive_api.db"))
    _backdate_done(raw, task["id"], 5)
    raw.close()

    assert client.get("/api/tasks/archived").json() == []  # 7 天没到
    assert len(client.get("/api/tasks").json()) == 1
    client.put("/api/settings/archive", json={"after_days": 5})
    assert len(client.get("/api/tasks/archived").json()) == 1  # 到点了


def test_api_archive_settings_rejects_bad_value(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """非法 N → 400（不静默落默认值），值保持原样。"""
    client = _client(tmp_path)
    for bad in (-1, 999, "三天"):
        r = client.put("/api/settings/archive", json={"after_days": bad})
        assert r.status_code == 400
    assert client.get("/api/settings/archive").json()["after_days"] == 3
