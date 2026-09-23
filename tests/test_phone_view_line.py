"""G 批 · T-G16：手机上更完整的**看**（离线缓存上的今日/逾期/该提醒了/今天该复习）。

口径（承接 T-B5 与 T-G10，没有新增需要拍板的东西）：
- 手机能看的，仍然是**上次联网时看到的样子**（缓存，不是实时）—— 界面上明说，不假装实时；
- **提醒只在界面上标出来，不发系统通知**（与电脑端 T-B5 的移动端口径一致）；
- 只读区里**没有能改数据的按钮**（手机上能改的仍只有完成/撤销/打卡）——
  这条有护栏：只读区出现写动作就是失败；
- 数字不在这里重算：摘要直接用后端 `summaryLine` 的同一份字段，逾期天数/提醒状态都是后端算好的。
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from timeflow.api.app import create_app

ROOT = Path(__file__).resolve().parent.parent
WEB_INDEX = ROOT / "src" / "web" / "index.html"


def _html() -> str:
    return WEB_INDEX.read_text(encoding="utf-8")


def _offline_source() -> str:
    """`renderOffline` 整段（从函数头到下一个顶层 `async function`）。"""
    return _html().split("async function renderOffline(m){", 1)[1].split("\nasync function ", 1)[0]


def _cache_paths() -> list[str]:
    """界面里那份"离线要看哪些接口"的清单（**一份声明**，缓存与测试都认它）。"""
    block = _html().split("const OFFLINE_CACHE_PATHS=", 1)[1].split("};", 1)[0]
    return re.findall(r"'(/api/[a-z/]+)'", block)


def _seen_block() -> str:
    """只读区那个模板（`const seen=` 那一段）—— 只含"上次看到的"四段，不含可写区。"""
    return _offline_source().split("const seen=`", 1)[1].split("`;", 1)[0]


def _capture_block() -> str:
    """可写区那个模板（`const capture=` 那一段）—— 离线记一笔 + 离线勾完成。"""
    return _offline_source().split("const capture=", 1)[1].split("const queue=", 1)[0]


def test_every_cached_path_is_a_real_route(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """★ 护栏：手机上要缓存的那几个接口**必须真的存在**。

    为什么值得一条：路径写错一个字（或后端改了名），手机不会报错 —— 它只是"什么都看不到"，
    而那种坏法在真机上极难发现（尤其在断网时才发现）。这里拿 `app.routes` 对账。
    """
    paths = _cache_paths()
    assert "/api/mydays" in paths and "/api/overdue" in paths
    assert "/api/reminders/due" in paths and "/api/review/due" in paths and "/api/summary" in paths
    app = create_app(str(tmp_path / "a.db"))
    routes = {str(getattr(r, "path", "")) for r in app.routes}
    missing = [p for p in paths if p not in routes]
    assert not missing, f"界面在缓存这些接口，但后端没有：{missing}"


def test_cached_endpoints_answer_for_real(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """缓存的那几个接口在真服务上都答得上来（不是只在列表里存在）。"""
    client = TestClient(create_app(str(tmp_path / "b.db")))
    for path in _cache_paths():
        got = client.get(path)
        assert got.status_code == 200, f"{path} 答不上来：{got.status_code}"
    # 提醒与复习这两个是**列表**（手机按列表渲染），摘要是**对象**（按字段渲染）
    assert isinstance(client.get("/api/reminders/due").json(), list)
    assert isinstance(client.get("/api/review/due").json(), list)
    assert isinstance(client.get("/api/summary").json(), dict)


def test_seen_block_is_read_only() -> None:
    """只读区里**不许有写动作** —— 提醒是"标出来"，不是"点掉"；逾期也不是"就地处理"。

    手机上能改数据的只有三样：完成 / 撤销完成 / 习惯打卡，它们都在**可写区**（离线记一笔、
    离线勾完成）。只读区出现 `offline-*` 写动作（或任何别的 data-action）就是越界。
    """
    seen = _seen_block()
    for write_action in ("offline-done", "offline-habit", "offline-task-add", "offline-memo-add",
                         "offline-feedback-save", "offline-clear"):
        assert write_action not in seen, f"只读区出现了写动作：{write_action}"
    assert 'data-action="' not in seen, "只读区不该有任何动作按钮"
    for title in ("该提醒了（", "今天该复习（", "逾期（"):
        assert title in seen, f"只读区少了「{title}」这一段"


def test_phone_says_what_is_not_realtime_and_no_notifications() -> None:
    """两句实话必须写在手机上：**不是实时**、**只标不通知**。"""
    src = _offline_source()
    assert "上次看到的（只读）" in src
    assert "上次联网时看到的样子" in src
    assert "只标出来、不发系统通知" in src
    # 摘要用与电脑端同一份字段拼（不在手机上另造一套口径）
    assert "summaryLine(seenSummary)" in src
    # 提醒时间要显示出来（"什么时候该动"是"看"的一部分）
    assert "提醒时间 " in src


def test_reminder_time_is_on_the_actionable_rows_too() -> None:
    """可写那份清单（离线勾完成）也带提醒时间 —— 看与做在同一张卡上，不用来回翻。"""
    capture = _capture_block()
    row = capture.split("离线勾完成", 1)[1]
    assert "t.remind_at" in row and "提醒 " in row


def test_cached_more_than_tasks(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """缓存清单从"任务/习惯/备忘/反馈"扩到"今日/逾期/提醒/复习/摘要"——

    这一条是这一卡的核心改动，钉住它免得以后被顺手删掉（删了手机就"看不全"）。
    """
    paths = set(_cache_paths())
    assert {"/api/tasks", "/api/habits", "/api/memos", "/api/feedback"} <= paths
    assert {"/api/mydays", "/api/overdue", "/api/reminders/due", "/api/review/due",
            "/api/summary"} <= paths
    # 缓存的键与清单一一对应（渲染时按这些键找）
    keys_block = _html().split("const OFFLINE_CACHE_KEYS=[", 1)[1].split("];", 1)[0]
    for key in ("mydays", "overdue", "reminders", "reviewDue", "summary"):
        assert f"'{key}'" in keys_block, f"缓存键少了 {key}"
