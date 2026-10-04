"""门禁串行锁的租约与续租（T-G161）。

为什么有这个文件：`gates/diag/gate_lock.py` 是「跨树一把」的门禁串行锁。063 实测它会在
**自己还持锁跑门禁时**被判成陈旧锁、被别的卡拿走 —— 根因两条：①默认租约 1800s 小于
「一张反证卡连跑三趟全量门禁」的常见时长；②租约是**从 acquire 起算的静态计时**，跑门禁期间
锁文件没人动，于是「多久没动」一路涨到过期。本卡把默认租约改大 + 新增 `renew` 子命令，
这个测试把「陈旧判定 / 续租生效 / 不许别人续 / 串行没松」四条钉住。

★ `gates/diag/` 不是包（没有 `__init__.py`）→ 按路径用 `importlib` 加载，
  `import gates.diag.gate_lock` 会失败。
★ 每个用例把 `lock_path` monkeypatch 到 `tmp_path` —— **绝不碰跨树共享的真锁**
  `gates/diag/gates.lock`（那是并行期别的卡正在用的锁）。
★ 「多久没动」靠**拨 mtime**（`os.utime`）来造，不靠长时间 sleep —— 满负载下 sleep 会漂成假红。
★ 允许用环境变量 `GATE_LOCK_UNDER_TEST` 换一份实现来跑（本卡的「先红后绿」：不改工作区文件，
  把旧实现指给本测试，看它红）。
"""
from __future__ import annotations

import importlib.util
import os
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GL_SRC = Path(
    os.environ.get("GATE_LOCK_UNDER_TEST", str(REPO / "gates" / "diag" / "gate_lock.py"))
)


def _load():
    spec = importlib.util.spec_from_file_location("gate_lock_under_test", GL_SRC)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def gl(tmp_path, monkeypatch):
    """加载被测模块，并把它的锁文件指到本用例的临时目录。"""
    mod = _load()
    monkeypatch.setattr(mod, "lock_path", lambda: tmp_path / "gates.lock")
    return mod


def _backdate(lock: Path, seconds: int) -> None:
    """把锁文件 mtime 拨到 `seconds` 秒前，等价于「放了这么久没人动」。"""
    old = time.time() - seconds
    os.utime(lock, (old, old))


def test_default_lease_is_three_hours(gl):
    """默认租约 = 10800s（3 小时）—— 够一张反证卡连跑三趟全量门禁。"""
    assert gl.DEFAULT_STALE_AFTER == 10800


def test_stale_lock_is_cleaned_and_reacquired(gl, capsys):
    """超过租约未动 → status 报「可被清」，另一个卡能清掉并拿到。"""
    lease = 2
    assert gl.cmd_acquire("A", wait=0, stale_after=lease) == 0
    lock = gl.lock_path()
    _backdate(lock, lease + 5)

    gl.cmd_status(lease)
    assert "可被清" in capsys.readouterr().out

    assert gl.cmd_acquire("B", wait=0, stale_after=lease) == 0
    assert gl._read(gl.lock_path()).get("card") == "B"


def test_renew_resets_age_and_prevents_stale(gl, capsys):
    """★ 核心：续租把 mtime 刷回现在 —— 续租前「陈旧」、续租后「租约内」。"""
    lease = 2
    assert gl.cmd_acquire("A", wait=0, stale_after=lease) == 0
    lock = gl.lock_path()
    _backdate(lock, lease + 5)  # 不续租的话，它已经陈旧了

    gl.cmd_status(lease)
    assert "可被清" in capsys.readouterr().out  # 续租前：陈旧

    assert gl.cmd_renew("A") == 0
    assert gl._age(lock) < 1  # age 重新从 0 起算

    gl.cmd_status(lease)
    out = capsys.readouterr().out
    assert "租约内" in out  # 续租后：不陈旧
    assert "可被清" not in out

    # 反证：没被当陈旧 → 别的卡拿不走（串行仍在）
    assert gl.cmd_acquire("B", wait=0, stale_after=lease) == 3
    assert gl._read(lock).get("card") == "A"


def test_renew_rejected_for_other_card_and_mtime_untouched(gl, capsys):
    """★ 不许别人续：非持有者的 renew 被拒（非 0），且原锁文件 mtime 一个字都不动。"""
    assert gl.cmd_acquire("A", wait=0, stale_after=60) == 0
    lock = gl.lock_path()
    _backdate(lock, 100)
    before = os.stat(lock).st_mtime

    rc = gl.cmd_renew("B")
    assert rc != 0
    assert os.stat(lock).st_mtime == before  # 被拒就不许动锁
    assert gl._read(lock).get("card") == "A"
    capsys.readouterr()


def test_two_cards_cannot_both_hold(gl, capsys):
    """★ 串行没松：两个不同卡号「同时」acquire，只有一个成功（另一个退 3）。"""
    results: dict[str, int] = {}
    barrier = threading.Barrier(2)

    def worker(card: str) -> None:
        barrier.wait()
        results[card] = gl.cmd_acquire(card, wait=0, stale_after=9999)

    threads = [threading.Thread(target=worker, args=(c,)) for c in ("A", "B")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results.values()) == [0, 3]
    assert gl._read(gl.lock_path()).get("card") in results
    capsys.readouterr()


# ================================================ 卡 163 INV-28：续租线程真读数
def test_renewer_thread_actually_refreshes_mtime(gl, capsys):
    """★ 卡 163 INV-28：续租线程真的把 mtime 续了 —— 不只是 cmd_renew 存在，而是 mtime 真变了。

    模拟 landing.py 的续租接线：起一个后台线程定期调 cmd_renew，跑一会儿后停。
    断言：renew 被调过、mtime 是新的、锁没被别人拿走（串行仍在）。
    """
    lease = 10
    assert gl.cmd_acquire("A", wait=0, stale_after=lease) == 0
    lock = gl.lock_path()
    _backdate(lock, lease + 5)  # 不续租的话已经陈旧了

    stop = threading.Event()
    renew_count = [0]

    def renewer() -> None:
        while not stop.wait(0.02):
            if gl.cmd_renew("A") == 0:
                renew_count[0] += 1

    t = threading.Thread(target=renewer, daemon=True)
    t.start()
    time.sleep(0.15)  # 让续租线程跑几次
    stop.set()
    t.join(timeout=1)

    assert renew_count[0] > 0, "续租线程必须真的调了 cmd_renew"
    assert gl._age(lock) < 1, "续租后 mtime 必须是新的"

    # 反证：续租后别人拿不走（串行仍在）
    assert gl.cmd_acquire("B", wait=0, stale_after=lease) == 3
    assert gl._read(lock).get("card") == "A"
    capsys.readouterr()
