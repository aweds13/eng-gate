"""门禁锁「按端口段分把 + 全局并发上限」的钉子测试（T-G169）。

为什么有这个文件：`gates/diag/gate_lock.py` 原来是「跨树一把」全局锁 —— 七张卡排队，
最后一张可能等 40 分钟。062（T-G156）已把端口按树隔离并实测两段可同时跑真机门，
所以「同一时刻整机只许一趟」已无必要；必要条件收敛成两条：
**同一个端口段不许两趟并行** + **整机并行趟数有上限（内存）**。
本卡把锁改成「每段一把（`TF_GATE_PORT_BASE` → `gates-<BASE>.lock`；不设 = 原路径
`gates.lock` 逐字不变）+ 全局限额（`TF_GATE_MAX_CONCURRENT`，默认 2）」，
这个测试把五条钉住：
  ① 不同段可以同时拿到；
  ② 同一段第二个必须等（互斥没松）；
  ③ 全局上限起作用（=1 串行、=2 两段并行）；
  ④ 续租仍生效、别人不能续、租约过期后空位回归（067/T-G161 的判据回归）；
  ⑤ 路径向后兼容（不设变量 = `gates.lock`；非法值退默认段，与 `run_gates.py` 同口径）。

★ `gates/diag/` 不是包（没有 `__init__.py`）→ 按路径用 `importlib` 加载。
★ 每个用例把 `main_root` monkeypatch 到 `tmp_path` —— **绝不碰跨树共享的真锁**
  `gates/diag/gates*.lock`（那是并行期别的卡正在用的锁；本卡铁律：默认段那把一个字不许动）。
★ 「多久没动」靠**拨 mtime**（`os.utime`）来造，不靠长时间 sleep —— 满负载下 sleep 会漂成假红。
★ 跑测试的 shell 可能带着 `TF_GATE_PORT_BASE=9061`（本卡自己的门禁段）——
  fixture 里先 `delenv` 隔离，再按用例 `setenv`，否则读数会被环境污染。
★ 允许用环境变量 `GATE_LOCK_UNDER_TEST` 换一份实现来跑（本卡的「先红后绿」：不改工作区文件，
  把旧实现 `b90c4e4:gates/diag/gate_lock.py` 指给本测试，看它红）。
"""
from __future__ import annotations

import importlib.util
import json
import os
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GL_SRC = Path(
    os.environ.get("GATE_LOCK_UNDER_TEST", str(REPO / "gates" / "diag" / "gate_lock.py"))
)


def _load():
    spec = importlib.util.spec_from_file_location("gate_lock_multi_under_test", GL_SRC)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def gl(tmp_path, monkeypatch):
    """加载被测模块：锁目录指到本用例的临时目录 + 环境变量隔离。"""
    mod = _load()
    monkeypatch.setattr(mod, "main_root", lambda: tmp_path)
    monkeypatch.delenv("TF_GATE_PORT_BASE", raising=False)
    monkeypatch.delenv("TF_GATE_MAX_CONCURRENT", raising=False)
    # 端口探测只读且可能误报「忙」——测试里关掉（互斥/名额断言不依赖它）。
    monkeypatch.setattr(mod, "_ports_busy", lambda: [])
    return mod


def _backdate(lock: Path, seconds: int) -> None:
    """把锁文件 mtime 拨到 `seconds` 秒前，等价于「放了这么久没人动」。"""
    old = time.time() - seconds
    os.utime(lock, (old, old))


def test_different_segments_can_hold_together(gl, monkeypatch):
    """★ ① 不同段可以同时拿到：两个 BASE 各 acquire → 都成功，各是一把独立锁文件。"""
    monkeypatch.setenv("TF_GATE_PORT_BASE", "9701")
    assert gl.cmd_acquire("A", wait=0, stale_after=9999) == 0
    monkeypatch.setenv("TF_GATE_PORT_BASE", "9703")
    assert gl.cmd_acquire("B", wait=0, stale_after=9999) == 0

    names = {p.name for p in gl.all_lock_paths()}
    assert names == {"gates-9701.lock", "gates-9703.lock"}
    assert gl._read(gl.lock_dir() / "gates-9701.lock").get("card") == "A"
    assert gl._read(gl.lock_dir() / "gates-9703.lock").get("card") == "B"


def test_same_segment_second_must_wait(gl, monkeypatch):
    """★ ② 同一段第二个必须等：同 BASE 两次 acquire，第二个拿不到（wait=0 立刻退 3）。"""
    monkeypatch.setenv("TF_GATE_PORT_BASE", "9705")
    assert gl.cmd_acquire("A", wait=0, stale_after=9999) == 0
    assert gl.cmd_acquire("B", wait=0, stale_after=9999) == 3
    assert gl._read(gl.lock_path()).get("card") == "A"  # 锁还是 A 的，没被偷


def test_global_limit_one_forces_second_segment_to_wait(gl, monkeypatch):
    """★ ③a 全局上限 =1：第二个段必须等（退回「全局串行」旧行为）。"""
    monkeypatch.setenv("TF_GATE_MAX_CONCURRENT", "1")
    monkeypatch.setenv("TF_GATE_PORT_BASE", "9707")
    assert gl.cmd_acquire("A", wait=0, stale_after=9999) == 0
    monkeypatch.setenv("TF_GATE_PORT_BASE", "9709")
    assert gl.cmd_acquire("B", wait=0, stale_after=9999) == 3
    # 超限自删：B 没拿到就不该留下锁文件（名额没被 B 占着）
    assert not (gl.lock_dir() / "gates-9709.lock").exists()


def test_global_limit_two_allows_two_segments(gl, monkeypatch):
    """★ ③b 全局上限 =2（默认）：两个段能同时拿到。"""
    monkeypatch.setenv("TF_GATE_MAX_CONCURRENT", "2")
    monkeypatch.setenv("TF_GATE_PORT_BASE", "9707")
    assert gl.cmd_acquire("A", wait=0, stale_after=9999) == 0
    monkeypatch.setenv("TF_GATE_PORT_BASE", "9709")
    assert gl.cmd_acquire("B", wait=0, stale_after=9999) == 0
    assert len(gl._active_locks(9999)) == 2


def test_renew_still_works_and_others_cannot(gl, monkeypatch):
    """★ ④a 续租回归（T-G161）：同卡能续、别人的卡续不了、续完别人仍拿不走。"""
    monkeypatch.setenv("TF_GATE_PORT_BASE", "9711")
    assert gl.cmd_acquire("A", wait=0, stale_after=2) == 0
    lock = gl.lock_path()
    _backdate(lock, 7)  # 不续租的话已经陈旧

    assert gl.cmd_renew("A") == 0
    assert gl._age(lock) < 1  # mtime 刷回现在，age 从 0 起算
    assert gl.cmd_renew("B") == 5  # 别人的锁续不了
    assert gl.cmd_acquire("B", wait=0, stale_after=2) == 3  # 续租后没陈旧 → 拿不走
    assert gl._read(lock).get("card") == "A"


def test_expired_lease_returns_capacity(gl, monkeypatch):
    """★ ④b 租约过期 → 空位自动回归：上限 1 时，A 过期后 B（另一个段）能拿到，不会永远等。"""
    monkeypatch.setenv("TF_GATE_MAX_CONCURRENT", "1")
    monkeypatch.setenv("TF_GATE_PORT_BASE", "9713")
    assert gl.cmd_acquire("A", wait=0, stale_after=2) == 0
    _backdate(gl.lock_path(), 7)  # A 的租约过了

    monkeypatch.setenv("TF_GATE_PORT_BASE", "9715")
    assert gl.cmd_acquire("B", wait=0, stale_after=9999) == 0  # 名额回归，B 拿到
    # 名额没泄漏：现在租约内的只有 B 一把
    assert [info.get("card") for _, info, _ in gl._active_locks(9999)] == ["B"]


def test_lock_path_backward_compatible(gl, monkeypatch):
    """★ ⑤ 路径向后兼容：不设变量 = gates.lock（逐字不变）；设了 = gates-<BASE>.lock；
    非法值退默认段（与 scripts/run_gates.py 的 port_base() 同口径）。"""
    assert gl.lock_path().name == "gates.lock"

    monkeypatch.setenv("TF_GATE_PORT_BASE", "9721")
    assert gl.lock_path().name == "gates-9721.lock"

    monkeypatch.setenv("TF_GATE_PORT_BASE", "not-a-number")
    assert gl.lock_path().name == "gates.lock"  # WARN + 退默认段

    monkeypatch.setenv("TF_GATE_PORT_BASE", "1")  # 越界（<1024）
    assert gl.lock_path().name == "gates.lock"


def test_lock_file_records_base_and_lease(gl, monkeypatch):
    """锁文件记下自己的段与租约 —— status 的「租约剩余」与名额扫描都靠它。"""
    monkeypatch.setenv("TF_GATE_PORT_BASE", "9723")
    assert gl.cmd_acquire("A", wait=0, stale_after=1234) == 0
    info = json.loads(gl.lock_path().read_text(encoding="utf-8"))
    assert info["base"] == 9723
    assert info["lease"] == 1234
    assert info["card"] == "A"


def test_status_lists_every_segment(gl, monkeypatch, capsys):
    """status 一眼看出哪些段各被谁占着（每把锁的持有者 + 租约剩余都列出来）。"""
    monkeypatch.setenv("TF_GATE_PORT_BASE", "9725")
    assert gl.cmd_acquire("A", wait=0, stale_after=9999) == 0
    monkeypatch.setenv("TF_GATE_PORT_BASE", "9727")
    assert gl.cmd_acquire("B", wait=0, stale_after=9999) == 0

    assert gl.cmd_status(9999) == 0
    out = capsys.readouterr().out
    assert "gates-9725.lock" in out and "card=A" in out
    assert "gates-9727.lock" in out and "card=B" in out
    assert "租约剩" in out
    assert "TF_GATE_MAX_CONCURRENT=2" in out  # 默认上限 2


def test_default_max_concurrent_is_two(gl):
    """★ 默认上限 2（卡规格定的：保守保护内存；别默认 7 —— 那是拿机器去赌）。"""
    assert gl.DEFAULT_MAX_CONCURRENT == 2
    assert gl.max_concurrent() == 2
