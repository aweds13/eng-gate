"""卡 A340（T-AG542）钉子：pool 的「一分钟里派了几趟」闸（移植自 magpie 的 MaxRPM）.

判据原文见 `复盘/卡/卡A340-一分钟里派得太快就不派.md`。十条钉子逐字对那张表
（后两条是裁定 1 加的：`note_stamp` 与 `give_back` 是一对，照 magpie 的 `reserve` + `giveBack`）：

| 用例名 | 断言什么 |
|---|---|
| `test_decide_allows_when_no_stamps` | 空 stamps ⇒ allowed=True、wait_s==0.0、next_at==now |
| `test_decide_takes_nth_from_the_end_plus_61` | limit=2、[now-10s, now-5s] ⇒ next_at==now-10s+61s |
| | 且 wait_s==51.0 |
| `test_decide_prunes_older_than_61s` | [now-70s, now-5s]、limit=2 ⇒ allowed=True |
| `test_decide_refuses_when_wait_longer_than_longest` | 要等 200s > longest=120 ⇒ allowed=False |
| | 且 why 含「超过最长等待」 |
| `test_decide_zero_limit_never_bites` | limit=0 + 100 条 stamps ⇒ allowed=True |
| `test_decide_future_stamp_is_refused_and_said_so` | 未来时刻 ⇒ allowed=False |
| | 且 why 含「记录里有未来时间」 |
| `test_rpm_toml_broken_raises_not_zero` | 坏 TOML / 负数 / >MAX_RPM ⇒ RpmError |
| | 文件不存在 ⇒ {} |
| `test_reverse_rpm_window_without_slack` | **反向**：WINDOW_S 61→60 时这条必须红 |
| `test_give_back_removes_the_exact_stamp` | 同秒不同微秒的两条戳，`give_back` 只删中那一条 |
| | （按值删，不是「删最后一条」） |
| `test_give_back_is_idempotent` | 重复还 / 还没有的号 / 没有的戳 ⇒ 都不抛、不误删、不留空数组 |

★ 最后一条是反向钉子（不是正向断言）：它故意把窗口边界压在 `now - 60s` 上 ——
  实占 61 秒时那条记录还没过期（还在窗口里，所以现在派不了），
  一旦有人把 `WINDOW_S` 改成 60，`now - 60s` 恰好落在 `<= now - 60s` 上被 prune
  ⇒ 判成「可以派」⇒ 红。
  **那 1 秒是 magpie 在 CI 负载下实测挖出来的**（`internal/gateway/rpm.go:46-51` 的源码注释：
  第一个请求要拨号 + TLS 握手才到达 vendor，裸窗口会让 vendor 在它自己那一分钟里看到多一个）；
  丢了它就会「本地放行、上游 429」。
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from pool import rpm  # noqa: E402

TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 30, 12, 0, 0, tzinfo=TZ)


def _ago(seconds: float, *, now: datetime = NOW) -> datetime:
    return now - timedelta(seconds=seconds)


# ============================================================ ① 空账本：直接放行
def test_decide_allows_when_no_stamps() -> None:
    """没派过 ⇒ 现在就能派；`next_at` 就是 `now`、`wait_s` 就是 0.0（不许给个「假的最早时刻」）。"""
    got = rpm.decide("demo", [], limit=2, now=NOW)
    assert got.allowed is True
    assert got.next_at == NOW
    assert got.wait_s == 0.0


# ============================================================ ② 倒数第 limit 个 + 61
def test_decide_takes_nth_from_the_end_plus_61() -> None:
    """钉住「取倒数第 limit 个时间点 + 61 秒」，**不是**「数一数 60 秒里有几个」。

    `[now-10s, now-5s]`、上限 2：两条都在窗口里 ⇒ 位置要等**倒数第 2 个**（= now-10s）过窗，
    也就是 `now-10s+61s`，还要等 51 秒。
    ★ 若有人改成「数 60 秒内有几条 ≥ limit 就等到最早那条 + 60」，
      这里会算成 now-10s+60s ⇒ wait_s=50.0 ⇒ 红。
    """
    stamps = [_ago(10), _ago(5)]
    got = rpm.decide("demo", stamps, limit=2, now=NOW)
    assert got.allowed is False
    assert got.next_at == stamps[0] + timedelta(seconds=61)
    assert got.wait_s == 51.0


# ============================================================ ③ 过窗的丢掉
def test_decide_prunes_older_than_61s() -> None:
    """`now-70s` 那条已经过窗（> 61 秒）⇒ 丢掉；只剩一条 ⇒ 上限 2 还有位置 ⇒ 现在就能派。"""
    got = rpm.decide("demo", [_ago(70), _ago(5)], limit=2, now=NOW)
    assert got.allowed is True
    assert got.wait_s == 0.0
    assert got.next_at == NOW


# ============================================================ ④ 超过最长等待就拒
def test_decide_refuses_when_wait_longer_than_longest() -> None:
    """最长的等是 120 秒（magpie 的 `rpmLongest`）：算出来要等 200 秒 ⇒ 立刻拒，不睡等。

    ★ 为什么这条必须专门钉：不钉的话，最自然的写法是「等不满也照样把 `next_at` 交出去」——
      调用方于是要么挂住派活进程，要么自己睡到那个时刻（本卡明令禁止睡够窗口）。
      要等 200 秒的形态只能由**未来时刻**造出来（正常记录最坏也就等 61 秒）：唯一那条在
      `now+139s`，位置 = 它 + 61s = `now+200s` ⇒ 等 200 秒 > 120 ⇒ 拒。
    """
    got = rpm.decide("demo", [_ago(-139)], limit=1, now=NOW, longest=120.0)
    assert got.allowed is False
    assert got.wait_s == 200.0
    assert "超过最长等待" in got.why

    # 同一个账本、放宽到 300 秒 ⇒ 位置还是那个位置，但不再算「超长」。
    relaxed = rpm.decide("demo", [_ago(-139)], limit=1, now=NOW, longest=300.0)
    assert relaxed.allowed is False, "位置没到就还是不许派 —— 放宽的只是「等不起」那条"
    assert relaxed.wait_s == 200.0
    assert "超过最长等待" not in relaxed.why


# ============================================================ ⑤ 0 = 关闸
def test_decide_zero_limit_never_bites() -> None:
    """`limit=0` 是**关闸**（不限），不是全拒 —— 照 `reserve()` 里 `longest > 0` 那条同向的宽容。"""
    stamps = [_ago(s) for s in range(1, 101)]
    got = rpm.decide("demo", stamps, limit=0, now=NOW)
    assert got.allowed is True
    assert got.wait_s == 0.0
    assert got.next_at == NOW


# ============================================================ ⑥ 钟坏了：未来时刻
def test_decide_future_stamp_is_refused_and_said_so() -> None:
    """账本里有未来时刻（钟坏了）⇒ 不许崩：按 prune 口径它们未过期 ⇒ 拒。

    而且 `why` 得说清是钟的事（别让人去怀疑额度或模型）。
    """
    stamps = [_ago(-30), _ago(-10)]
    got = rpm.decide("demo", stamps, limit=1, now=NOW)
    assert got.allowed is False
    assert "记录里有未来时间" in got.why
    assert "超过最长等待" not in got.why


# ============================================================ ⑦ 人写配置：写错就喊
def test_rpm_toml_broken_raises_not_zero(tmp_path: Path) -> None:
    """坏 TOML / 负数 / 超 MAX_RPM ⇒ RpmError（**绝不许静默当 0**：0 = 不限 = 悄悄松开判据）。"""
    assert rpm.load_rpm(tmp_path / "absent.toml") == {}

    broken = tmp_path / "broken.toml"
    broken.write_text("[accounts\ncodearts-1 = 2\n", encoding="utf-8", newline="")
    with pytest.raises(rpm.RpmError):
        rpm.load_rpm(broken)

    negative = tmp_path / "negative.toml"
    negative.write_text('[accounts]\ncodearts-1 = -1\n', encoding="utf-8", newline="")
    with pytest.raises(rpm.RpmError) as neg:
        rpm.load_rpm(negative)
    assert "-1" in str(neg.value), "越界要点名收到的值，别只说「越界」"

    too_big = tmp_path / "too-big.toml"
    too_big.write_text(f"[accounts]\ncodearts-1 = {rpm.MAX_RPM + 1}\n", encoding="utf-8",
                       newline="")
    with pytest.raises(rpm.RpmError) as big:
        rpm.load_rpm(too_big)
    assert str(rpm.MAX_RPM + 1) in str(big.value)

    ok = tmp_path / "ok.toml"
    ok.write_text('[accounts]\ncodearts-1 = 0\ntrae-1 = 3\n', encoding="utf-8", newline="")
    assert rpm.load_rpm(ok) == {"codearts-1": 0, "trae-1": 3}


# ============================================================ ⑧ 反向钉子：那 1 秒 slack
def test_reverse_rpm_window_without_slack() -> None:
    """★ 反向钉子：**把 `WINDOW_S` 从 61 改成 60，这条必须红。**

    做法（逐字照卡规格判据 8）：`limit=1`、`stamps=[now-60s]`，断言 `allowed is False`
    —— 61 秒窗口下那条记录**还没**过期（`now-60s > now-61s` ⇒ 在窗口里），所以现在派不了，
    要等到 `now-60s+61s`（还要等 1 秒）。

    改成 60 之后：`now-60s` 恰好落在 prune 的 `<= now-60s` 上被丢掉 ⇒ 账本空了 ⇒ `allowed=True`
    ⇒ `assert got.allowed is False` 当场红。

    ★ 为什么这 1 秒不是「多留一点保险」：magpie 的源码注释（`internal/gateway/rpm.go:46-51`）
      逐字写着它是在 CI 负载下**实测挖出来的** —— 第一个请求要拨号 + TLS 握手才到达 vendor，
      裸窗口会让 vendor 在它自己那一分钟里看到多一个（`TestMaxRPMWaitsForRoomInTheMinute`
      在 CI 负载下红，且每次把第一个请求在路上按住 150ms 都会红）。丢了它 = 本地放行、上游 429。
    """
    stamps = [_ago(60)]
    got = rpm.decide("demo", stamps, limit=1, now=NOW)
    assert got.allowed is False, "窗口是 61 秒：now-60s 的记录还没过期，现在不该放行"
    assert got.next_at == stamps[0] + timedelta(seconds=61)
    assert got.wait_s == 1.0


# ============================================================ ⑨ 还一趟：按值删，不是删最后一条
def test_give_back_removes_the_exact_stamp(tmp_path: Path) -> None:
    """`give_back` 照 magpie 的 `giveBack`（`rpm.go:141-154`）：在表里**从后往前找第一个相等**的删.

    ★ 这两条戳**同一秒、不同微秒**：只按秒比、或者图省事「删最后一条」，都会删错。
    """
    early = NOW.replace(microsecond=0)
    late = NOW.replace(microsecond=500_000)
    rpm.note_stamp("demo", early, root=tmp_path)
    rpm.note_stamp("demo", late, root=tmp_path)
    assert rpm.read_stamps(root=tmp_path)["demo"] == [early, late]

    rpm.give_back("demo", late, root=tmp_path)
    assert rpm.read_stamps(root=tmp_path)["demo"] == [early], "删的必须是 late，不是「最后一条」"

    rpm.give_back("demo", early, root=tmp_path)
    assert "demo" not in rpm.read_stamps(root=tmp_path), "删空了要把这个号整条清掉，不留空数组"


# ============================================================ ⑩ 还一趟：幂等、不许误删、不留空数组
def test_give_back_is_idempotent(tmp_path: Path) -> None:
    """重复还、还没有的号、表里没有的那个戳 —— **都不许抛、不许误删**.

    ★ 第三条最容易写错：如果拿「找到第一个 `>=` 的」代替「找到第一个 `==` 的」，
      一个**更早**的、根本不在表里的戳就会把表里那条删掉 —— 那就是悄悄放行一趟。
    """
    rpm.give_back("nobody", NOW, root=tmp_path)  # 还没有的号：空操作，不许抛
    assert rpm.read_stamps(root=tmp_path) == {}

    rpm.note_stamp("demo", NOW, root=tmp_path)
    rpm.give_back("demo", NOW, root=tmp_path)
    rpm.give_back("demo", NOW, root=tmp_path)  # 重复还：第二次是空操作
    assert rpm.read_stamps(root=tmp_path) == {}

    rpm.note_stamp("demo", NOW, root=tmp_path)
    rpm.give_back("demo", NOW - timedelta(seconds=5), root=tmp_path)  # 表里没有的更早戳
    assert rpm.read_stamps(root=tmp_path)["demo"] == [NOW], "没有的戳不许误删表里那条"
    ledger = (tmp_path / "gates" / "diag" / "pool-rpm.json").read_text(encoding="utf-8")
    assert "[]" not in ledger, "账本里不许出现空数组"
