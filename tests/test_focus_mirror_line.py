"""跨端同步专注（SR-F3.4 / N17 / T-G20）的测试。

口径（用户 2026-09-23 定）：**实时启动 + 结束时再同步**。
- 实时启动：任一台开始专注，另一台**当场**看到「别处正在专注」（只读镜像）；
- 结束时再同步：结束不做实时推，记录各自入库，之后走已有的同步包通道合并。

两条硬边界（本文件主要就钉这两条）：
1. **镜像不重复记账**：别处只读查询后，投入口径一分不多（同一段时间记两笔 = 数字失真）；
2. **镜像不许停对面的计时**：界面侧的证据在 DOM 探针（镜像卡里 0 个 `data-action`），
   这里钉数据侧 —— 只读查询不改任何一行。
"""

from __future__ import annotations

import pytest

from timeflow.core import focus as fc
from timeflow.storage import db


@pytest.fixture
def conn(tmp_path):
    c = db.connect(str(tmp_path / "t.db"))
    yield c
    c.close()


# ---------------------------------------------------------------- device_id 落库与回传

def test_active_session_reports_device_id(conn) -> None:
    """`device_id` 必须回传：界面靠它判断"这条是不是我自己开的"（不然镜像判不出来）。"""
    fc.start_session(conn, kind=fc.KIND_PLAIN, device_id="cl-abc123")
    active = fc.active_session(conn)
    assert active is not None
    assert active["device_id"] == "cl-abc123"


def test_device_id_is_trimmed(conn) -> None:
    fc.start_session(conn, kind=fc.KIND_PLAIN, device_id="  ph-9f8e7d  ")
    active = fc.active_session(conn)
    assert active is not None and active["device_id"] == "ph-9f8e7d"


@pytest.mark.parametrize("raw", [None, "", "   ", "\t\n"])
def test_blank_device_id_becomes_none(conn, raw: str | None) -> None:
    """空白 → NULL：不能让 `""` 混进来（界面会把空串当"有来源"，判断就错）。"""
    fc.start_session(conn, kind=fc.KIND_PLAIN, device_id=raw)
    active = fc.active_session(conn)
    assert active is not None and active["device_id"] is None


def test_device_id_is_truncated_not_rejected(conn) -> None:
    """超长只截断、不报错：它只是客户端标识，为此拒绝开始专注对用户毫无意义。"""
    fc.start_session(conn, kind=fc.KIND_PLAIN, device_id="x" * 200)
    active = fc.active_session(conn)
    assert active is not None
    assert active["device_id"] == "x" * fc.MAX_DEVICE_LEN


def test_legacy_session_without_device_id_is_none(conn) -> None:
    """老数据（T-G20 之前开的）`device_id` 是 NULL —— 界面按"我开的"处理，
    保证「重开页面恢复计时」这条既有行为不变。"""
    sid = fc.start_session(conn, kind=fc.KIND_PLAIN)
    active = fc.active_session(conn)
    assert active is not None and active["id"] == sid and active["device_id"] is None


# ---------------------------------------------------------------- 边界 ① 镜像不重复记账

def test_peeking_from_another_client_does_not_write_anything(conn) -> None:
    """另一台设备"看"三次：行数、投入、事实都不许变（镜像只是照镜子）。"""
    sid = fc.start_session(conn, kind=fc.KIND_TOMATO, device_id="cl-desktop")
    before_rows = conn.execute("SELECT COUNT(*) AS n FROM focus_sessions").fetchone()["n"]
    before_facts = conn.execute("SELECT COUNT(*) AS n FROM facts").fetchone()["n"]
    for _ in range(3):
        active = fc.active_session(conn)          # 手机那边就是这么"看"的
        assert active is not None and active["id"] == sid
        assert active["device_id"] == "cl-desktop"  # 手机据此知道"不是我开的"
    assert conn.execute("SELECT COUNT(*) AS n FROM focus_sessions").fetchone()["n"] == before_rows
    assert conn.execute("SELECT COUNT(*) AS n FROM facts").fetchone()["n"] == before_facts
    assert fc.today_focus_minutes(conn) == 0.0


def test_second_client_cannot_start_a_parallel_session(conn) -> None:
    """另一台设备想"我也开始一个" → 被拒（否则同一段时间记两笔投入）。"""
    fc.start_session(conn, kind=fc.KIND_PLAIN, device_id="cl-desktop")
    with pytest.raises(ValueError) as err:
        fc.start_session(conn, kind=fc.KIND_PLAIN, device_id="ph-phone")
    assert "已有进行中的专注" in str(err.value)


def test_one_session_one_invest_entry_across_clients(conn) -> None:
    """端到端：电脑开 → 手机只读 → 电脑结束 = **一条**记录、**一笔**投入（不重复）。"""
    sid = fc.start_session(conn, kind=fc.KIND_PLAIN, device_id="cl-desktop")
    assert fc.active_session(conn) is not None          # 手机看到的
    fc.finish_session(conn, sid, 1500, fc.STATUS_FINISHED)
    assert fc.active_session(conn) is None              # 手机那边镜像随之消失
    assert fc.today_focus_minutes(conn) == 25.0
    kinds = [r["kind"] for r in conn.execute("SELECT kind FROM facts").fetchall()]
    assert kinds.count("focus.finished") == 1           # 只有一笔投入事实
