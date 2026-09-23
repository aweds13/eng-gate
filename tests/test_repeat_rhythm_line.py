"""重复节奏视图（`SR-F1.5b` / N9 / T-G25）的测试。

规格那句：「重复任务到点按上次完成自动生成下一次；**节奏可用时间热力图管理**」——
前半句早就 done（`process_repeats`），后半句一直没做（台账 gaps 写着"热力图是「天 × 指标」，
没有按任务/重复节奏的视图"）。本文件钉这条投影的口径：

1. 一条"节奏" = 同一个重复事项的那些轮次（**同一标题 + 同一周期**；每完成一轮生成下一行）；
2. 格子按**排期日**（那一轮的 `due_date`）画，不是按完成日；
3. `done` 认「现在状态是完成」或「归档 + 有 `task.completed` 事实」—— **归档 ≠ 做完**；
4. 取消 / 搁置 / 归档未完成 = `off`（如实标出来，不算完成也不算"没做"）；
5. 窗口外的轮次不进图；被彻底删掉的轮次不进图；
6. **不推算未来的排期**（周期是"每 N 天"，锚点会漂）—— 这条是规格里最容易做假的地方。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from timeflow.core import insights
from timeflow.core import tasks as tm
from timeflow.storage import db


@pytest.fixture
def conn(tmp_path):
    c = db.connect(str(tmp_path / "t.db"))
    yield c
    c.close()


def _day(offset: int = 0) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def _repeat(conn, title: str, due: str, every: int = 1, **kw):
    return tm.create_task(conn, title=title, due_date=due, repeat_days=every, **kw)


# ---------------------------------------------------------------- 基本形状

def test_no_repeat_tasks_is_empty_not_error(conn) -> None:
    tm.create_task(conn, title="不重复的活儿", due_date=_day())
    got = insights.repeat_rhythm(conn)
    assert got.series == []
    assert got.note and "排期日" in got.note


def test_cells_are_keyed_by_due_date_not_completion_date(conn) -> None:
    """格子跟**排期日**走：晚做了的事也画在"该做的那天"上（节奏问的是"该做的那天做没做"）。"""
    task = _repeat(conn, "背单词", _day(-2), every=1)
    tm.complete_task(conn, task.id)          # 今天才完成，但排期是前天
    got = insights.repeat_rhythm(conn)
    assert [(c.date, c.state) for c in got.series[0].cells] == [(_day(-2), "done")]


def test_same_title_and_period_group_into_one_series(conn) -> None:
    """每完成一轮就生成下一行 —— 一个重复事项在库里是**一串**，视图里要合成一条。"""
    first = _repeat(conn, "背单词", _day(-3), every=1)
    tm.complete_task(conn, first.id)
    second = _repeat(conn, "背单词", _day(-2), every=1)
    tm.complete_task(conn, second.id)
    third = _repeat(conn, "背单词", _day(-1), every=1)
    got = insights.repeat_rhythm(conn)
    assert len(got.series) == 1
    s = got.series[0]
    assert (s.title, s.repeat_days, s.planned, s.done) == ("背单词", 1, 3, 2)
    assert [c.date for c in s.cells] == [_day(-3), _day(-2), _day(-1)]
    assert [c.state for c in s.cells] == ["done", "done", "missed"]
    assert third.id  # 第三轮那行确实在库里（只是这一轮没做）


def test_different_period_splits_series(conn) -> None:
    """同一标题但周期不同 = 两件事（不猜"这俩是不是同一个"）。"""
    _repeat(conn, "背单词", _day(-2), every=1)
    _repeat(conn, "背单词", _day(-2), every=7)
    got = insights.repeat_rhythm(conn)
    assert sorted(s.repeat_days for s in got.series) == [1, 7]


# ---------------------------------------------------------------- 三种状态

def test_cancelled_and_parked_are_off_not_done(conn) -> None:
    cancelled = _repeat(conn, "晨跑", _day(-3), every=1)
    tm.cancel_task(conn, cancelled.id)
    parked = _repeat(conn, "晨跑", _day(-2), every=1)
    tm.park_task(conn, parked.id)
    slept = _repeat(conn, "晨跑", _day(-1), every=1)     # 没动它：还活着但没做
    got = insights.repeat_rhythm(conn)
    assert [c.state for c in got.series[0].cells] == ["off", "off", "missed"]
    assert got.series[0].done == 0
    assert slept.id  # 用一下，免得被 lint 当未使用


def test_archived_without_completion_is_not_done(conn) -> None:
    """**归档 ≠ 做完**：未完成的也能归档 —— 所以归档只认「有 `task.completed` 事实」的那种。"""
    archived_open = _repeat(conn, "周复盘", _day(-2), every=7)
    tm.archive_task(conn, archived_open.id)
    archived_done = _repeat(conn, "周复盘", _day(-1), every=7)
    tm.complete_task(conn, archived_done.id)
    tm.archive_task(conn, archived_done.id)
    states = [c.state for c in insights.repeat_rhythm(conn).series[0].cells]
    assert states == ["off", "done"]


def test_deleted_round_is_skipped(conn) -> None:
    """被彻底删掉的轮次不进图（它已经不是排期了）。"""
    gone = _repeat(conn, "背单词", _day(-2), every=1)
    tm.delete_task(conn, gone.id)          # 软删除（T-?/OP-6）：留一行「已删」
    tm.purge_task(conn, gone.id)           # 彻底删除：图里不该再有它
    _repeat(conn, "背单词", _day(-1), every=1)
    cell_dates = [c.date for c in insights.repeat_rhythm(conn).series[0].cells]
    assert cell_dates == [_day(-1)]


# ---------------------------------------------------------------- 窗口与数量

def test_window_filters_old_rounds(conn) -> None:
    """窗口外的轮次不进图（默认 8 周）；窗口内的都在。"""
    _repeat(conn, "背单词", _day(-100), every=1)
    _repeat(conn, "背单词", _day(-10), every=1)
    got = insights.repeat_rhythm(conn, days=56)
    assert [c.date for c in got.series[0].cells] == [_day(-10)]


def test_days_is_clamped_like_other_insights(conn) -> None:
    _repeat(conn, "背单词", _day(-1), every=1)
    assert insights.repeat_rhythm(conn, days=0).days == 1
    assert insights.repeat_rhythm(conn, days=10_000).days == insights.MAX_RHYTHM_DAYS


def test_undated_round_never_shows_up(conn) -> None:
    """没有排期日的轮次画不出来（也不猜它在哪一天）—— 图里不该冒出空格子。"""
    _repeat(conn, "背单词", _day(-1), every=1)
    tm.create_task(conn, title="背单词", repeat_days=1)   # 无 due_date
    got = insights.repeat_rhythm(conn)
    assert sum(s.planned for s in got.series) == 1


def test_two_series_render_planned_and_done_counts(conn) -> None:
    for off in (-6, -5):
        t = _repeat(conn, "背单词", _day(off), every=1)
        tm.complete_task(conn, t.id)
    _repeat(conn, "背单词", _day(-4), every=1)
    got = insights.repeat_rhythm(conn)
    s = got.series[0]
    assert (s.planned, s.done) == (3, 2)
    assert "完成" not in got.note or "做完了" in got.note  # 说明里给的是状态词，不是分数


# ---------------------------------------------------------------- API

def test_api_shape_and_validation(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from timeflow.api.app import create_app

    client = TestClient(create_app(str(tmp_path / "api.db")))
    task = client.post(
        "/api/tasks",
        json={"title": "背单词", "due_date": _day(-1), "repeat_days": 1, "is_myday": True},
    ).json()
    client.post(f"/api/tasks/{task['id']}/complete")
    got = client.get("/api/insights/repeat-rhythm").json()
    assert got["days"] == insights.DEFAULT_RHYTHM_DAYS
    assert got["series"][0]["title"] == "背单词"
    assert got["series"][0]["cells"][0]["state"] == "done"
    assert client.get("/api/insights/repeat-rhythm?days=0").status_code == 400
    assert client.get("/api/insights/repeat-rhythm?days=999").status_code == 400
