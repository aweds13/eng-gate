r"""额度等待子命令（卡 A328 · T-AG530）的测试 —— 等 / 刷新 / 反向钉子。

为什么值当测：magpie 有 `quota wait`（按记录等续期、clamp 到 1 分钟..10 分钟、
留 30 秒余量、刷新 30 秒抑制），本仓 `tools/pool_quota.py` 只有 `status` ——
派活器只能自己写 `DEFAULT_QUOTA_WAIT = 300` 睡死 5 分钟。

★ 本文件钉的三件事：
  ① `round_wait` 的晨量纪律（+30s 余量、下限 60s、上限 600s、未知续期睡满 600s）；
  ② `wait` **不许凭空判成功** —— `已过期` / `余额耗尽` / `未记录` 三态都不绿，
    连「被人换成永远返回 `可派` 的假 status」也必须在 timeout 处退 1（反向钉子）；
  ③ `refresh` 的 30 秒抑制只是省重复问，且**不联网**。
★ 测试不许靠真实钟表：`now` 一律注入固定值 `NOW`；`time.sleep` 一律 monkeypatch（不真睡）。
  ⚠️ `record()` 自己写 `recorded_at` 走的是**真实钟表**，所以凡是要参与判据的记录，
     一律由 `_record(..., recorded_at=...)` 显式钉死，不留给真钟。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pool_quota  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上

#: 固定「现在」（同 `tests/test_quota_clock.py`）—— 测试不许靠真实钟表。
NOW = "2026-10-12T23:28:00+08:00"

#: 起点之前的一条「旧记录」时间（证明「没探过」）。
STALE = "2026-10-12T22:00:00+08:00"


def _set_recorded_at(tmp_path: Path, card: str, model: str, value: str) -> None:
    """把沙箱记录里的 `recorded_at` 钉成给定值（`record()` 写的是真实钟表，不许拿来判）。"""
    path = tmp_path / pool_quota.STATE_REL
    data = json.loads(path.read_text(encoding="utf-8"))
    data["cards"][card][model]["recorded_at"] = value
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _record(tmp_path: Path, *, reset_raw: str, kind: str = "限流",
            card: str = "201", model: str = "deepseek-v4.1-flash",
            recorded_at: str = STALE) -> tuple[str, str]:
    """落一条记录到沙箱（不碰真实仓库的 gates/diag/），并把 `recorded_at` 钉成 `STALE`。"""
    pool_quota.record(
        card=card, model=model, pool="codebuddy", kind=kind,
        reset_raw=reset_raw, source_log="wb-201.jsonl", root=tmp_path,
    )
    _set_recorded_at(tmp_path, card, model, recorded_at)
    return card, model


def _fake_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """替掉 `time.sleep` —— 返回「睡过多少秒」的清单（**一条真实睡眠都不许有**）。"""
    slept: list[float] = []
    monkeypatch.setattr(pool_quota.time, "sleep", lambda s: slept.append(s))
    return slept


# ================================================================ wait 四条


def test_wait_returns_zero_when_state_expired_and_rerecorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ 成功路径只有一条：`已过期` 之后**看到一条比起点更新的记录**才退 0。

    过期 ≠ 可用 —— 但「有人探过并落了新记录」就是证据。第一次 status 是过期态且记录
    是旧的（`STALE`）⇒ 继续等；第二轮里把 `recorded_at` 换成比起点新的值 ⇒ 退 0。
    """
    card, model = _record(tmp_path, reset_raw="2026-10-12 16:52:45 UTC+8")  # 6 小时前
    slept = _fake_sleep(monkeypatch)
    real_status = pool_quota.status
    calls = {"n": 0}

    def status_then_rerecord(**kwargs):
        calls["n"] += 1
        if calls["n"] >= 2:  # 第二轮：假装探测过，落一条比起点更新的记录
            newer = (kwargs["now"] + pool_quota.timedelta(seconds=10)).isoformat()
            _set_recorded_at(tmp_path, card, model, newer)
        return real_status(**kwargs)

    monkeypatch.setattr(pool_quota, "status", status_then_rerecord)
    rc = pool_quota.wait_until(card=card, model=model, timeout="2h", quiet=True,
                               now=NOW, root=tmp_path)
    assert rc == pool_quota.EXIT_OK
    assert rc == 0
    assert slept  # 至少睡过一轮才重新看（没有凭空立刻变绿）
    assert calls["n"] >= 2


def test_wait_times_out_with_exit_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`已过期` 但**始终没有新记录** ⇒ 一路等，到 `--timeout` 退 1（过期不许当可用）。"""
    card, model = _record(tmp_path, reset_raw="2026-10-12 16:52:45 UTC+8")
    slept = _fake_sleep(monkeypatch)
    rc = pool_quota.wait_until(card=card, model=model, timeout="2m", quiet=True,
                               now=NOW, root=tmp_path)
    assert rc == pool_quota.EXIT_TIMEOUT == 1
    assert sum(slept) >= 120 - 1  # 真等满了上限才退（没提前乐观返回）


def test_wait_unknown_model_never_goes_green(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`未记录` ⇒ 不猜 ⇒ 等到超时退 1（不许默认当可用）。"""
    _fake_sleep(monkeypatch)
    rc = pool_quota.wait_until(card="999", model="从没记过的模型", timeout="1m", quiet=True,
                               now=NOW, root=tmp_path)
    assert rc == pool_quota.EXIT_TIMEOUT
    assert pool_quota.status(card="999", model="从没记过的模型", now=NOW,
                             root=tmp_path)["state"] == "未记录"


def test_reverse_wait_ignores_record_hits_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ 反向钉子：把 `status()` 换成永远返回 `可派` 的假货 ⇒ `wait` 仍必须在超时处退 1。

    证明 `wait` **不靠乐观假设**变绿：它只认「一条比起点更新的记录」，
    连一个谎报可用的 status 都骗不过它。
    """
    card, model = _record(tmp_path, reset_raw="2026-10-12 23:58:00 UTC+8")
    slept = _fake_sleep(monkeypatch)

    def always_ok(**kwargs):
        return {"card": kwargs["card"], "model": kwargs["model"], "state": "可派",
                "can_dispatch": True, "need_probe": False, "reset_at": None,
                "recorded_at": None, "now": str(kwargs.get("now")),
                "remaining_seconds": 0, "expired_seconds": None, "why": "假货"}

    monkeypatch.setattr(pool_quota, "status", always_ok)
    rc = pool_quota.wait_until(card=card, model=model, timeout="1m", quiet=True,
                               now=NOW, root=tmp_path)
    assert rc == pool_quota.EXIT_TIMEOUT == 1  # 没有一条比起点更新的记录 ⇒ 不许变绿
    assert sum(slept) >= 60 - 1


# ================================================================ round_wait 两条


def test_round_wait_margin_and_clamp() -> None:
    """`round_wait`：+30 秒余量、下限 60 秒、上限 600 秒，`why` 里念出 clamp 区间。"""
    # 剩 2 小时 ⇒ 7200 + 30 clamp 到 600
    far = "2026-10-13T01:28:00+08:00"
    assert pool_quota.round_wait(far, now=NOW)[0] == pool_quota.WAIT_MAX_S == 600
    # 剩 100 秒 ⇒ 100 + 30 = 130（既不撞下限也不撞上限）
    mid = "2026-10-12T23:29:40+08:00"
    assert pool_quota.round_wait(mid, now=NOW)[0] == 130
    # 剩 5 秒 ⇒ 5 + 30 = 35 clamp 到下限 60
    soon = "2026-10-12T23:28:05+08:00"
    assert pool_quota.round_wait(soon, now=NOW)[0] == pool_quota.WAIT_MIN_S == 60
    # 已经过期（负数）⇒ 仍返回下限 60，**不许负数 / 不许 0**（防忙等）
    past = "2026-10-12T16:52:45+08:00"
    assert pool_quota.round_wait(past, now=NOW)[0] == 60
    _seconds, why = pool_quota.round_wait(mid, now=NOW)
    assert str(pool_quota.WAIT_MARGIN_S) in why
    assert str(pool_quota.WAIT_MIN_S) in why and str(pool_quota.WAIT_MAX_S) in why


def test_round_wait_unknown_reset_sleeps_ten_minutes() -> None:
    """续期未知 / 解析不出 ⇒ 睡满上限 600 秒，并说明「未知续期」。"""
    assert pool_quota.round_wait(None, now=NOW) == (
        600, "未知续期 ⇒ 睡满上限")
    assert pool_quota.round_wait(None, now=NOW)[0] == pool_quota.WAIT_MAX_S
    assert pool_quota.round_wait("不是时间", now=NOW)[0] == 600
    assert pool_quota.round_wait("", now=NOW)[0] == 600
    assert "未知续期" in pool_quota.round_wait("不是时间", now=NOW)[1]


# ================================================================ refresh 两条


def test_refresh_within_gap_does_not_probe(tmp_path: Path) -> None:
    """30 秒内问过 ⇒ 不再问（打印「跳过」），且**不联网**、不改记录。"""
    assert pool_quota.REFRESH_GAP_S == 30
    first = pool_quota.refresh_once(card="201", model="m1", now=NOW, root=tmp_path)
    assert first["probe"] is True
    assert "需要重新探测" in first["why"]
    assert first["network"] is False
    assert (tmp_path / pool_quota.REFRESH_REL).exists()  # 时间戳落了盘

    # 10 秒后再问 ⇒ 跳过
    later = "2026-10-12T23:28:10+08:00"
    second = pool_quota.refresh_once(card="201", model="m1", now=later, root=tmp_path)
    assert second["probe"] is False
    assert "跳过" in second["why"]
    assert second["seconds_since_last"] == 10
    # 30 秒整的边界：`< REFRESH_GAP_S` 才算「内」⇒ 30 秒已经过了，要问
    assert pool_quota.refreshed_within(pool_quota.refresh_key("201", "m1"),
                                       now="2026-10-12T23:28:30+08:00", root=tmp_path) == 30
    after = pool_quota.refresh_once(card="201", model="m1",
                                    now="2026-10-12T23:28:30+08:00", root=tmp_path)
    assert after["probe"] is True  # 正好 30 秒 ⇒ 不落在「30 秒内」


def test_refresh_after_gap_probes(tmp_path: Path) -> None:
    """超过 30 秒 ⇒ 重新问（更新时间戳）；坏 JSON ⇒ 当作没问过，立刻可问。"""
    pool_quota.note_refreshed(pool_quota.refresh_key("201", "m1"), now=NOW, root=tmp_path)
    out = pool_quota.refresh_once(card="201", model="m1",
                                  now="2026-10-12T23:29:00+08:00", root=tmp_path)
    assert out["probe"] is True  # 60 秒 > 30 秒 ⇒ 要问
    assert out["seconds_since_last"] == 60
    assert "需要重新探测" in out["why"]

    # 坏 JSON ⇒ `None` ⇒ 立刻可问（读不懂不许把刷新冻住）
    (tmp_path / pool_quota.REFRESH_REL).write_text("{不是 JSON", encoding="utf-8")
    assert pool_quota.refreshed_within("201|m1", now=NOW, root=tmp_path) is None
    assert pool_quota.refresh_once(card="201", model="m1", now=NOW,
                                   root=tmp_path)["probe"] is True
    # key 小写化：`M1` 与 `m1` 是同一条
    assert pool_quota.refresh_key("201", "M1") == pool_quota.refresh_key("201", "m1") == "201|m1"
    # 时间戳目录/文件是 `gates/diag/quota-refresh.json`
    assert pool_quota.refresh_stamp_path(tmp_path) == tmp_path / "gates/diag/quota-refresh.json"


# ================================================================ 零网络 / 不碰旧签名


def test_wait_and_refresh_never_touch_network(tmp_path: Path) -> None:
    """`wait` / `refresh` 都不许发网络 —— 本模块连 `requests` / `urllib` 都不许 import。"""
    source = (ROOT / "tools" / "pool_quota.py").read_text(encoding="utf-8")
    for forbidden in ("requests", "urllib", "http.client", "httpx", "socket"):
        assert forbidden not in source, f"{forbidden} 不许出现在 pool_quota.py 里"
    # CLI 两个子命令都得在，且 `wait` 默认上限是 6h（不是 DEFAULT_QUOTA_WAIT = 300）
    assert pool_quota.parse_timeout("6h") == 21600
    assert pool_quota.parse_timeout("30s") == 30
    assert pool_quota.parse_timeout("5m") == 300
    assert pool_quota.parse_timeout("2h") == 7200
    with pytest.raises(ValueError):
        pool_quota.parse_timeout("很久")


def test_wait_cli_default_timeout_is_six_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    """★ CLI 的 `wait --timeout` 默认是 **6h**，不是 `DEFAULT_QUOTA_WAIT = 300` 秒。

    派活器里那个 300 是「睡死 5 分钟」的老口径（`tools/wb_dispatch.py:218`）；
    把 `wait` 的上限默认成它，就等于「等 5 分钟就报超时」—— 本钉子专门咬这个。
    """
    seen: dict[str, object] = {}

    def fake_wait_until(**kwargs):
        seen.update(kwargs)
        return pool_quota.EXIT_OK

    monkeypatch.setattr(pool_quota, "wait_until", fake_wait_until)
    rc = pool_quota.main(["wait", "--card", "999", "--model", "假模型"])
    assert rc == pool_quota.EXIT_OK
    assert seen["timeout"] == "6h"
    assert pool_quota.parse_timeout(str(seen["timeout"])) == 21600
    assert pool_quota.parse_timeout(str(seen["timeout"])) != 300  # 不是老口径的 5 分钟
    # 缺 `--card` 由 argparse 处理 ⇒ 退 2（EXIT_USAGE），不是 1（超时）
    assert pool_quota.EXIT_USAGE == 2
    with pytest.raises(SystemExit) as excinfo:
        pool_quota.main(["wait", "--model", "假模型"])
    assert excinfo.value.code == pool_quota.EXIT_USAGE
