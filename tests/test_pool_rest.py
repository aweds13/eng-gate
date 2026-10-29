r"""rest 时长四真值（卡 A332 · T-AG534）—— magpie `restAfterMarked` 的 pool 版。

为什么值当测：pool 之前只有四态枚举，**连一个 rest 时长常量都没有**，「歇多久」全靠
`wb_dispatch.DEFAULT_QUOTA_WAIT = 300` 兜底。magpie 的四真值（credit 30 分钟 / quota 有
续期就歇到那时 / quota 没续期 15 分钟 / rate 指数退避）一条都没搬过来 —— 搬错一条的表现
是**少歇**（撞墙）或**多歇**（白等），两种都不可接受。

★ 本文件钉的五件事：
  ① 四真值各走各的分支：credit **是** 1800，不是 quota 的 900；
  ② `rest_cap off` **只**挡 `other`（`routing.go:1182` 的 `why == failOther` 是硬条件），
     401/403 永远挡在 off 之外；
  ③ 不认的 `why`、越界的 `rest_cap_s` 都抛 `ValueError` —— 不许静默兜底、不许 clamp；
  ④ `status()` 只多了 `rest_until` / `rest_by` 两个键，四态名字与 `why` 文案一个字没动；
  ⑤ `status()` 里不许出现网络或 sleep（它现在零网络，插一行就必须变红）。

★ 测试**不许靠真实钟表**：`now` 一律注入 `NOW`。
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pool_quota  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上

NOW = "2026-10-12T23:28:00+08:00"
HOUR = 3600
DAY = 24 * HOUR


# ================================================================ 四真值


def test_rest_quota_with_reset_uses_resets_by():
    """有续期时间就歇到那时，`by="resets"`（`routing.go:1126-1127`）。"""
    st = pool_quota.rest_after(
        why="quota", status=429, reset_at="2026-10-13T01:28:00+08:00", now=NOW
    )
    assert st["seconds"] == 7200
    assert st["by"] == "resets"
    assert st["why"] == "quota"
    assert st["capped"] is False
    assert st["rest_until"] == "2026-10-13T01:28:00+08:00"


def test_rest_quota_without_reset_is_fifteen_minutes():
    """没有续期时间 ⇒ magpie 自己的 quotaRest = 15 分钟，且 `capped`（`:1143` 的 guessed）。"""
    st = pool_quota.rest_after(why="quota", status=429, reset_at=None, now=NOW)
    assert st["seconds"] == 900
    assert st["by"] == "quota"
    assert st["capped"] is True
    assert st["rest_until"] == "2026-10-12T23:43:00+08:00"


def test_rest_credit_is_thirty_minutes():
    """没钱了 ⇒ creditRest = 30 分钟，**不是** quotaRest 的 900（`routing.go:1094-1095`）。"""
    st = pool_quota.rest_after(why="credit", status=402, reset_at=None, now=NOW)
    assert st["seconds"] == 1800
    assert st["seconds"] != pool_quota.QUOTA_REST_S
    assert st["by"] == "credit"
    assert st["why"] == "credit"


def test_rest_quota_reset_is_capped_by_eight_days():
    """续期时间再远也压到 8 天（`routing.go:1148` longestQuota）。"""
    st = pool_quota.rest_after(
        why="quota", status=429, reset_at="2026-11-21T23:28:00+08:00", now=NOW
    )
    assert st["seconds"] == 8 * DAY
    assert st["by"] == "resets"
    assert st["capped"] is True


def test_rest_monthly_window_gets_thirty_five_days():
    """月窗口命中 ⇒ 上限换 35 天（`routing.go:1145-1147`）。"""
    st = pool_quota.rest_after(
        why="quota",
        status=429,
        reset_at="2026-11-21T23:28:00+08:00",
        full_until="2026-11-22T00:00:00+08:00",
        now=NOW,
    )
    assert st["seconds"] == 35 * DAY
    assert st["by"] == "resets"


def test_rest_reset_in_past_is_zero_but_not_off():
    """钟倒流 ⇒ `seconds=0`、`by="resets"`、`capped=False`；**不许**当成「立刻可用」。"""
    st = pool_quota.rest_after(
        why="quota", status=429, reset_at="2026-10-12T22:28:00+08:00", now=NOW
    )
    assert st["seconds"] == 0
    assert st["by"] == "resets"
    assert st["capped"] is False


# ================================================================ off 只挡 other


def test_rest_cap_off_skips_only_other_failures():
    """★ `off` 只挡「无因失败」：quota 仍 900，rate 仍退避，401 挡在 off 之外（`:1182`）。"""
    off = pool_quota.REST_CAP_OFF
    other = pool_quota.rest_after(
        why="other", status=500, reset_at=None, rest_cap_s=off, now=NOW
    )
    assert (other["seconds"], other["by"]) == (0, "off")
    quota = pool_quota.rest_after(
        why="quota", status=429, reset_at=None, rest_cap_s=off, now=NOW
    )
    assert (quota["seconds"], quota["by"]) == (900, "quota")
    rate = pool_quota.rest_after(
        why="rate", status=429, reset_at=None, rest_cap_s=off, now=NOW
    )
    assert (rate["seconds"], rate["by"]) == (60, "cooldown")
    credit = pool_quota.rest_after(
        why="credit", status=402, reset_at=None, rest_cap_s=off, now=NOW
    )
    assert (credit["seconds"], credit["by"]) == (1800, "credit")
    for status in (401, 403):
        guarded = pool_quota.rest_after(
            why="other", status=status, reset_at=None, rest_cap_s=off, now=NOW
        )
        assert guarded["by"] == "backoff", f"{status} 不许被 rest-cap off 吞掉"
        assert guarded["seconds"] == 60


def test_rest_auth_never_gets_off():
    """`auth` 在 magpie 的 switch 里没有 case ⇒ 走 default 退避，永远拿不到 off。"""
    st = pool_quota.rest_after(
        why="auth", status=401, reset_at=None, rest_cap_s=pool_quota.REST_CAP_OFF, now=NOW
    )
    assert st["by"] == "backoff"
    assert st["seconds"] == 60


# ================================================================ 退避


def test_rest_rate_backoff_doubles_and_caps():
    """`min(60 << (n-1), 30min)`：60,120,240,480,960,1800,1800（`:1436-1439`）。"""
    got = [
        pool_quota.rest_after(
            why="rate", status=429, reset_at=None, failures=n, now=NOW
        )["seconds"]
        for n in range(1, 8)
    ]
    assert got == [60, 120, 240, 480, 960, 1800, 1800]
    assert pool_quota.rest_after(
        why="rate", status=429, reset_at=None, failures=1, now=NOW
    )["by"] == "cooldown"
    assert pool_quota.rest_after(
        why="rate", status=429, reset_at=None, failures=2, now=NOW
    )["by"] == "backoff"


def test_rest_other_backoff_caps_at_ten_minutes():
    """`other` 的退避上限是 longestRetry = 10 分钟（`:1221`），比 rate 的 30 分钟短。"""
    got = [
        pool_quota.rest_after(
            why="other", status=500, reset_at=None, failures=n, now=NOW
        )["seconds"]
        for n in (1, 2, 5, 9)
    ]
    assert got == [60, 120, 600, 600]
    assert pool_quota.rest_after(
        why="other", status=500, reset_at=None, failures=4, now=NOW
    )["by"] == "backoff"


def test_rest_rate_takes_longer_vendor_retry_after():
    """供应商说更久且 ≥ 退避值 ⇒ 用它，`by="retry-after"`（`:1452-1454`）。"""
    st = pool_quota.rest_after(
        why="rate", status=429, reset_at="2026-10-13T00:18:00+08:00", now=NOW
    )
    assert st["seconds"] == 3000
    assert st["by"] == "retry-after"


def test_rest_rate_ignores_shorter_vendor_retry_after():
    """供应商说的比退避值短 ⇒ **不**用它（`said >= d` 才换，`:1453`）。"""
    st = pool_quota.rest_after(
        why="rate", status=429, reset_at="2026-10-12T23:28:30+08:00", now=NOW, failures=3
    )
    assert st["seconds"] == 240
    assert st["by"] == "backoff"


def test_rest_retry_after_is_compressed_by_longest_wait():
    """供应商的时间先被 `min(d, longestWait=1h)` 压过（`:1592-1619`）。"""
    st = pool_quota.rest_after(
        why="rate", status=429, reset_at="2026-10-13T01:28:00+08:00", now=NOW, failures=1
    )
    assert st["seconds"] == HOUR
    assert st["by"] == "retry-after"
    assert st["capped"] is True


# ================================================================ 坏值 / 不认的分类


def test_rest_unknown_class_raises():
    """不认的 `why` 抛 `ValueError` —— **不许**静默回 `"other"`。"""
    with pytest.raises(ValueError, match="不认的失败分类"):
        pool_quota.rest_after(why="whatever", status=500, reset_at=None, now=NOW)


@pytest.mark.parametrize("cap", [-2, pool_quota.MAX_QUOTA_REST_MIN * 60 + 1])
def test_rest_cap_out_of_range_raises(cap: int):
    """越界的 `rest_cap_s` 抛 `ValueError`，**不 clamp**（`concurrency.go:352-361`）。"""
    with pytest.raises(ValueError):
        pool_quota.rest_after(
            why="other", status=500, reset_at=None, rest_cap_s=cap, now=NOW
        )


def test_rest_cap_in_range_is_honoured():
    """范围内的 `rest_cap_s` 当上限用（照 `RestCapOr`，`concurrency.go:349`）。"""
    st = pool_quota.rest_after(
        why="other", status=500, reset_at=None, rest_cap_s=30, failures=3, now=NOW
    )
    assert st["seconds"] == 30
    assert st["capped"] is True


# ================================================================ classify


@pytest.mark.parametrize(
    ("status", "body", "want"),
    [
        (402, "Insufficient Balance", "credit"),
        (400, "your credit is not enough, 余额不足", "credit"),
        (429, "rate limit reached, 将在 2026-10-13 01:00:00 UTC+8 重置", "quota"),
        (429, "Too many requests per minute", "rate"),
        (429, "try again in 30s", "rate"),
        (429, "monthly usage limit reached", "quota"),
        (503, "RESOURCE_EXHAUSTED", "quota"),
        (500, "internal server error", "other"),
        (401, "invalid api key", "auth"),
        (403, "forbidden", "auth"),
    ],
)
def test_classify_five_kinds(status: int, body: str, want: str):
    assert pool_quota.classify(status, body) == want
    assert want in pool_quota.WHY_KINDS


def test_classify_ignores_urls():
    """URL 里的 `rate` 之类字样不算数（magpie 先 `wordsOf` 去 URL，`:366/:243`）。"""
    body = "see https://example.com/docs/rate-limit-per-minute for help"
    assert pool_quota.classify(500, body) == "other"


# ================================================================ status() 只加两个键


def _record(tmp_path: Path, *, reset_raw: str | None, kind: str = "限流") -> None:
    pool_quota.record(
        card="A332",
        model="deepseek-v4.1-flash",
        pool="p",
        kind=kind,
        reset_raw=reset_raw,
        root=tmp_path,
    )


def test_status_carries_rest_keys_and_keeps_four_states(tmp_path: Path):
    """四态名字与 `why` 文案一个字不改；只多 `rest_until` / `rest_by`。"""
    _record(tmp_path, reset_raw="2026-10-12 23:58:00 UTC+8")
    st = pool_quota.status(card="A332", model="deepseek-v4.1-flash", now=NOW, root=tmp_path)
    assert st["state"] == "限流中"
    assert st["rest_by"] == "resets"
    assert st["rest_until"] == "2026-10-12T23:58:00+08:00"
    assert st["why"] == "reset_at > now（剩余 1800 秒）"

    _record(tmp_path, reset_raw="解析不出来的字符串", kind="余额耗尽")
    st2 = pool_quota.status(card="A332", model="deepseek-v4.1-flash", now=NOW, root=tmp_path)
    assert st2["state"] == "余额耗尽"
    assert st2["rest_by"] == "quota"
    assert st2["rest_until"] == "2026-10-12T23:43:00+08:00"
    assert st2["why"] == "有记录但没有重置时间 ⇒ 不自动等，只能探"

    _record(tmp_path, reset_raw="2026-10-12 16:52:45 UTC+8")
    st3 = pool_quota.status(card="A332", model="deepseek-v4.1-flash", now=NOW, root=tmp_path)
    assert st3["state"] == "已过期，需重新探测"
    assert st3["rest_by"] == "resets"
    assert st3["rest_until"] == NOW

    st4 = pool_quota.status(card="A332", model="never-seen", now=NOW, root=tmp_path)
    assert st4["state"] == "未记录"
    assert st4["rest_until"] is None
    assert st4["rest_by"] is None
    assert st4["why"] == "没有这条记录 ⇒ 不猜（★ 不许默认当可用）"


#: `status()` 里**不许**出现的字样 —— 它是「读记录 + 读钟表」的函数，零网络零等待。
FORBIDDEN_IN_STATUS = (
    "urllib",
    "requests",
    "httpx",
    "socket",
    "urlopen",
    "http.client",
    "time.sleep",
    "sleep(",
)


def test_status_has_no_network_or_sleep():
    """★ 反向钉子：`status()` 里插一行网络调用或 sleep，这条必须变红。"""
    src = inspect.getsource(pool_quota.status)
    hits = [word for word in FORBIDDEN_IN_STATUS if word in src]
    assert hits == [], f"status() 里出现了网络/等待：{hits}"


def test_pool_quota_module_imports_no_network_library():
    """整个模块零网络依赖（卡 201 以来的硬约束，本卡不许破坏）。"""
    mod_src = Path(pool_quota.__file__).read_text(encoding="utf-8")
    head = mod_src.split("\n\n", 1)[0] + mod_src.split("ROOT = Path", 1)[0]
    for word in ("import requests", "import urllib", "import httpx", "import socket"):
        assert word not in head, f"模块头部出现了网络依赖：{word}"
