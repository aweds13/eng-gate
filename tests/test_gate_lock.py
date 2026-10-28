r"""钉 `gates/diag/gate_lock.py` 的死主清理（卡 E16 · `T-AG467`）。

## 为什么有这张测试

`gate_lock.py` 的租约（T-G169）判「锁多久没动」，**不判持有者死没死** —— 这是有意的
（`acquire` 与 `run_gates` 是两次进程调用，pid 正常就会是死的）。但它留下一个洞：
落地进程被 `job_kill` 掐掉之后，锁**留在磁盘上**，后来的人只能干等租约（3 小时），
或者人肉 `cat` 锁文件 + 比对进程表 + `--force`。

卡 E16 补的是**收窄的**例外：租约**未过期** + **同机** + 持有者进程**确实已不存在**
⇒ 再等一个宽限期（默认 60s，防 pid 复用）才清；**判不了就一律不清**。

## 这张测试钉住什么（每条都在旧码上会红）

| # | 钉子 | 旧码坏掉会红在哪 |
|---|---|---|
| ① | 死主锁 ⇒ 宽限满后清掉 + 拿到锁（退 0 + 打印清锁行） | 旧码只等租约（3 小时）⇒ 退 3 |
| ② | 活主锁（pid = 当前进程）⇒ **不许清**，等超时退 3 | 清掉活锁 = 把正在跑的门禁偷走（又撞端口） |
| ③ | 无 `pid` 字段 ⇒ 不许清，退 3，报行含「判不了持有者身份」 | 猜着清 = 别人的活锁被清走 |
| ④ | `--grace 0` ⇒ 不清死主锁（回到旧行为） | 开关形同虚设 |
| ⑤ | 跨机（`host` 不同）⇒ 不许清 | 拿本机的进程表去判另一台机器的 pid |

## 怎么跑（★ 不碰真锁、不碰真门禁）

每个用例在 `tmp_path` 里 `git init` 一个**假仓库**，把 `TF_GATE_PORT_BASE` 指到一个
不会撞真段的号码 ⇒ `lock_path()` 落在 `tmp/gates/diag/gates-<base>.lock`，
真仓库的锁文件一个字节都不动。
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GATE_LOCK = ROOT / "gates" / "diag" / "gate_lock.py"

#: 假仓库用的端口段（真仓现在用的是 8xxx / 9xxx 那些；这里离得远一点，免得撞上）。
BASE = 9471


def _mk_repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    repo.mkdir()
    for args in (("init", "-q"), ("config", "user.email", "nail@example.invalid"),
                 ("config", "user.name", "nail")):
        # text=True 必给 encoding：云机 cp936 解码中文会崩，本机 utf-8 看不出来。
        # errors="replace"：宁可拿到带替换符的中文，也不要整条炸掉。
        subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                text=True, encoding="utf-8", errors="replace",
                       check=False)
    (repo / "gates" / "diag").mkdir(parents=True)
    return repo


def _lock_file(repo: Path) -> Path:
    return repo / "gates" / "diag" / f"gates-{BASE}.lock"


def _write_lock(repo: Path, *, card: str = "OLD", pid: object = 0,
                lease: int = 10800, host: str | None = None,
                with_pid: bool = True) -> Path:
    """造一把「租约内」的锁（mtime = 现在 ⇒ age≈0）。

    `with_pid=False` 造**旧格式**锁（没有 `pid` 字段）；`host` 给了就写进 `host`（跨机用）。
    """
    payload: dict[str, object] = {
        "card": card, "base": BASE, "lease": lease,
        "at": "2026-10-25T00:00:00", "cwd": str(repo),
    }
    if with_pid:
        payload["pid"] = pid
    if host is not None:
        payload["host"] = host
    p = _lock_file(repo)
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "TF_GATE_PORT_BASE": str(BASE)}
    # ★ 铁律 24：`gates/diag/` 里跑 python 一律 `-P -X utf8`（同目录同名脚本会顶掉标准库）。
    return subprocess.run([sys.executable, "-P", "-X", "utf8", str(GATE_LOCK), *args],
                          cwd=str(repo), env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _out(done: subprocess.CompletedProcess) -> str:
    return (done.stdout or "") + (done.stderr or "")


def _gate_lock_mod():
    spec = importlib.util.spec_from_file_location("gate_lock_under_test", GATE_LOCK)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _dead_pid() -> int:
    """找一个**确实不存在**的 pid（靠实现自己判，别猜）。"""
    mod = _gate_lock_mod()
    for cand in (4_000_004, 4_000_008, 4_000_012, 3_999_996):
        if mod._pid_alive(cand) is False:
            return cand
    pytest.skip("这台机器找不到一个确定不存在的 pid（夹具没法造死主锁）")
    return 0


# ------------------------------------------------------------------ ① 死主 ⇒ 清掉 + 拿到
def test_dead_owner_lock_is_cleared_after_grace(tmp_path: Path) -> None:
    """★ 钉子 1：租约内 + pid 已不存在 ⇒ 宽限期满清掉并打印清锁行，最终**拿到锁**（退 0）。"""
    repo = _mk_repo(tmp_path)
    dead = _dead_pid()
    _write_lock(repo, card="DEADOWNER", pid=dead, lease=10800)

    done = _run(repo, "acquire", "--card", "NEW", "--wait", "60", "--grace", "1")

    out = _out(done)
    assert done.returncode == 0, out
    assert "清掉死主的锁" in out, out
    assert f"pid={dead}" in out, out
    assert "进程已不存在" in out, out
    assert "拿到了" in out, out
    info = json.loads(_lock_file(repo).read_text(encoding="utf-8"))
    assert info.get("card") == "NEW", f"清完之后新锁应该是自己的：{info}"


# ------------------------------------------------------------- ② 活主 ⇒ 不许清，超时退 3
def test_live_owner_lock_is_not_cleared(tmp_path: Path) -> None:
    """★ 钉子 2：持有者 pid = **当前进程**（活着）⇒ 宽限期后仍不许清，等超时退 3。"""
    repo = _mk_repo(tmp_path)
    _write_lock(repo, card="LIVEOWNER", pid=os.getpid(), lease=10800)

    done = _run(repo, "acquire", "--card", "NEW", "--wait", "2", "--grace", "1")

    out = _out(done)
    assert done.returncode == 3, out
    assert "清掉死主的锁" not in out, f"活主锁被清了 —— 这是在偷别人正在跑的门禁：{out}"
    info = json.loads(_lock_file(repo).read_text(encoding="utf-8"))
    assert info.get("card") == "LIVEOWNER", info


# ------------------------------------------------------ ③ 没有 pid 字段 ⇒ 判不了，退 3
def test_lock_without_pid_is_never_cleared(tmp_path: Path) -> None:
    """★ 钉子 3：锁文件里没有 `pid` 字段 ⇒ **不许清**，退 3，报行明说「判不了持有者身份」。"""
    repo = _mk_repo(tmp_path)
    _write_lock(repo, card="NOPID", lease=10800, with_pid=False)

    done = _run(repo, "acquire", "--card", "NEW", "--wait", "2", "--grace", "1")

    out = _out(done)
    assert done.returncode == 3, out
    assert "判不了持有者身份" in out, out
    assert "清掉死主的锁" not in out, out
    assert _lock_file(repo).exists(), "判不了身份的锁不许清"


# ------------------------------------------------------------- ④ --grace 0 ⇒ 回到旧行为
def test_grace_zero_restores_old_behaviour(tmp_path: Path) -> None:
    """★ 钉子 4：`--grace 0` ⇒ 死主锁**也不清**（回到卡 E16 之前：只按租约判）。"""
    repo = _mk_repo(tmp_path)
    dead = _dead_pid()
    _write_lock(repo, card="DEADOWNER", pid=dead, lease=10800)

    done = _run(repo, "acquire", "--card", "NEW", "--wait", "2", "--grace", "0")

    out = _out(done)
    assert done.returncode == 3, out
    assert "清掉死主的锁" not in out, out
    assert _lock_file(repo).exists(), "grace=0 时不许清死主锁"


# ------------------------------------------------------------ ⑤ 跨机 ⇒ 不许清（判不了）
def test_cross_machine_lock_is_not_cleared(tmp_path: Path) -> None:
    """★ 钉子 5：锁里写着**另一台机器** ⇒ 拿本机进程表判人家 = 猜 ⇒ 只等，不清。"""
    repo = _mk_repo(tmp_path)
    dead = _dead_pid()
    _write_lock(repo, card="FARAWAY", pid=dead, lease=10800, host="another-host")

    done = _run(repo, "acquire", "--card", "NEW", "--wait", "2", "--grace", "1")

    out = _out(done)
    assert done.returncode == 3, out
    assert "另一台机器" in out, out
    assert "清掉死主的锁" not in out, out


# ---------------------------------------------------------------- 附：默认宽限期 = 60s
def test_default_grace_is_60(tmp_path: Path) -> None:
    """`--grace` 默认 60（卡 E16 判据 4）；改默认值要有人看见。"""
    repo = _mk_repo(tmp_path)
    done = _run(repo, "acquire", "--help")
    out = _out(done)
    assert done.returncode == 0, out
    assert "--grace" in out and "60" in out, out


# ------------------------------------- ⑥ release 不再只认当前 cwd 的端口段（卡 E16）
#
# 病灶（`tools/tf_commit.py:41` 记过原话）：锁按段分把（`gates-<base>.lock`），而
# `release` 只找 `lock_path()` 那一把 ⇒ 段不对时它说「没有锁，无需释放」退 0，
# 真正的那把锁还挂着，白占一个全局并发名额。现在先扫**全部段**。

def _write_other_segment_lock(repo: Path, *, base: int, card: str, pid: int) -> Path:
    p = repo / "gates" / "diag" / f"gates-{base}.lock"
    p.write_text(json.dumps({"card": card, "pid": pid, "base": base, "lease": 10800},
                            ensure_ascii=False), encoding="utf-8")
    return p


def test_release_finds_the_lock_in_another_segment(tmp_path: Path) -> None:
    """★ 钉「release 只认当前 cwd 端口段」：锁在**另一段**也要释放得掉（退 0 + 点出段号）。"""
    repo = _mk_repo(tmp_path)
    other = 9472
    p = _write_other_segment_lock(repo, base=other, card="MINE", pid=1234)

    done = _run(repo, "release", "--card", "MINE")     # env 段 = 9471，锁在 9472

    out = _out(done)
    assert done.returncode == 0, out
    assert not p.exists(), f"另一段的锁没释放掉 ⇒ 又只能人肉 --force：{out}"
    assert f"base={other}" in out, f"释放了却没说清是哪一段：{out}"


def test_release_names_the_holder_instead_of_saying_no_lock(tmp_path: Path) -> None:
    """★ 钉「点名持有者」：你的卡不在任何段、但别的段有别人的锁 ⇒ 退 4 并**点名**
    （不许再把「锁在别的段」静默说成「没有锁」）。"""
    repo = _mk_repo(tmp_path)
    p = _write_other_segment_lock(repo, base=9472, card="OTHER", pid=4321)

    done = _run(repo, "release", "--card", "MINE")

    out = _out(done)
    assert done.returncode == 4, out
    assert "OTHER" in out and "9472" in out, f"没点名持有者：{out}"
    assert "没有锁" not in out, f"别的段有锁却说「没有锁」：{out}"
    assert p.exists(), "别人的锁不许被 release"


# ------------------------------------- ⑦ status 点名持有者（卡 E16 第三处）
def test_status_names_the_holder(tmp_path: Path) -> None:
    """★ 钉「状态输出不点名持有者」：status 必须给出 段 / card / pid / 已持有秒数 /
    持有者进程是否还活着 / 剩余租约。"""
    repo = _mk_repo(tmp_path)
    _write_lock(repo, card="LIVEOWNER", pid=os.getpid(), lease=10800)

    done = _run(repo, "status")

    out = _out(done)
    assert done.returncode == 0, out
    assert "LIVEOWNER" in out, out
    assert f"pid={os.getpid()}" in out, out
    assert f"段 base={BASE}" in out, out
    assert "已 0s" in out or "已 1s" in out, out       # 已持有秒数
    assert "租约剩" in out, out                        # 剩余租约
    assert "持有者进程=活着" in out, f"没点名「进程还活着吗」：{out}"
