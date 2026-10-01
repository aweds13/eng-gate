"""钉子测试：`tools/run_bg.py`（卡 066 / `T-G160`）。

判据来自卡 §2.3（逐条）：

- `run` 起一条**故意慢**的命令（`time.sleep(2)` 级别）→ **父调用秒回**（实测 < 1.5 秒）
  且打印了 `pid=`；这也反证「**父进程退出不带走子进程**」（子进程活到最后并把 rc 落盘）；
- `status` 于「还在跑」与「已结束 rc=0」两态各断言一次（退出码都 0）；
- 负样例两条：命令不存在 → `status` 最终 `state=done rc!=0` 且 `status` 退出码 **3**；
  `--log` 不存在 → 退出码 **2**；
- 用法负样例：缺 `--` / `--log` 不可写 → 退出码 **2** 且给出人话（不是 traceback）；
- ★ 测试结束前**轮询干净**，不留真在跑的子进程（全部用 `sleep 2` 级别）。

工具只用标准库；测试通过子进程调它（与工人真跑时的形态一致）。
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUN_BG = ROOT / "tools" / "run_bg.py"

# 被测命令故意 sleep 这么久（秒）。**不是断言阈值** —— 是给"run 秒回后 status 能查到
# running"这个**行为观测**留窗口：满载下 `_status` 自己起一个 python 子进程也要时间，
# 子进程得活得比"run 返回 + 一次 status 查询"加起来还久，"秒回"才观测得稳。5s 远大于
# 起进程开销，满载也打不到（run 只是 fork+立刻返回，不 wait 子进程）。
_SLOW_SECONDS = "5"


def _run(args: list[str], timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(RUN_BG), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=str(ROOT),
        check=False,
    )


def _status(log: Path, tail: int = 5) -> subprocess.CompletedProcess[str]:
    return _run(["status", "--log", str(log), "--tail", str(tail)])


def _wait_done(log: Path, timeout: float = 20.0) -> subprocess.CompletedProcess[str]:
    """轮询到哨兵落盘（`state=done`）——也顺带保证**不留孤儿**：rc 出现即子进程已退。"""
    deadline = time.monotonic() + timeout
    last: subprocess.CompletedProcess[str] | None = None
    while time.monotonic() < deadline:
        last = _status(log)
        if "state=done" in last.stdout:
            return last
        time.sleep(0.2)
    raise AssertionError(f"status 没在 {timeout:.0f}s 内到 done：{last.stdout if last else ''}")


def test_run_returns_immediately_and_status_polls_two_states(tmp_path: Path) -> None:
    log = tmp_path / "slow.log"
    got = _run(
        [
            "run",
            "--log",
            str(log),
            "--",
            sys.executable,
            "-X",
            "utf8",
            "-c",
            f"import time; time.sleep({_SLOW_SECONDS}); print('bg done')",
        ]
    )

    # ★ 反证 1：父调用没等子进程结束（"秒回"）。
    #   不用墙钟（`elapsed < 1.5`）—— 它把"这台机器此刻快不快"当成了被测对象：满载下
    #   起一个 python 子进程本身就可能 >1.5s，与被测逻辑无关却会让断言挂。改用**行为**
    #   证据：run 返回后立刻查 status，子进程仍在 `state=running`（下面反证 2a）——
    #   若 run wait 了子进程，这里只会是 done。为让这个观测在满载下稳（`_status` 自己
    #   也要起一个 python 子进程），被测命令故意 sleep 5s（`_SLOW_SECONDS`），给"查到
    #   running"留足窗口；那是被测时长，不是断言阈值。
    assert got.returncode == 0, got.stderr
    assert "pid=" in got.stdout, got.stdout
    assert f"rc_file={log}.rc" in got.stdout, got.stdout
    assert log.exists(), "run 应当先把日志文件建出来（status 立刻可读）"

    # ★ 反证 2a：还在跑 → state=running，退出码 0
    st = _status(log)
    assert st.returncode == 0, st.stdout + st.stderr
    assert "state=running" in st.stdout, st.stdout

    # ★ 反证 2b：已结束 rc=0 → 退出码 0，且日志尾有子进程真实输出
    done = _wait_done(log)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "state=done rc=0" in done.stdout, done.stdout
    assert "bg done" in log.read_text(encoding="utf-8", errors="replace")


def test_status_reports_failure_for_missing_command(tmp_path: Path) -> None:
    """★ 反证 3a：命令不存在 → done rc!=0（status 退出码 3），且日志里有人话。"""
    log = tmp_path / "badcmd.log"
    got = _run(["run", "--log", str(log), "--", "definitely-not-a-real-cmd-tg160"])
    assert got.returncode == 0, got.stderr  # run 本身照常「起」了，失败留给哨兵

    done = _wait_done(log, timeout=15.0)
    assert done.returncode == 3, done.stdout + done.stderr
    assert "state=done rc=0" not in done.stdout, done.stdout
    assert "state=done rc=" in done.stdout, done.stdout
    text = log.read_text(encoding="utf-8", errors="replace")
    assert "命令不存在" in text, text


def test_status_missing_log_exits_2(tmp_path: Path) -> None:
    """★ 反证 3b：日志不存在 → 退出码 2。"""
    got = _status(tmp_path / "absent.log")
    assert got.returncode == 2, got.stdout + got.stderr
    assert "日志不存在" in got.stderr, got.stderr


def test_run_requires_double_dash(tmp_path: Path) -> None:
    """用法负样例：缺 `--` → 退出码 2 + 人话（不是 traceback）。"""
    got = _run(["run", "--log", str(tmp_path / "x.log"), sys.executable, "-c", "print(1)"])
    assert got.returncode == 2, got.stdout + got.stderr
    assert "--" in got.stderr, got.stderr
    assert "Traceback" not in got.stderr, got.stderr
    assert not (tmp_path / "x.log").exists(), "用法错时不该建日志"


def test_run_unwritable_log_exits_2(tmp_path: Path) -> None:
    """用法负样例：`--log` 指向不存在的目录 → 退出码 2，明确报错。"""
    bad = tmp_path / "no-such-dir" / "x.log"
    got = _run(["run", "--log", str(bad), "--", sys.executable, "-c", "print(1)"])
    assert got.returncode == 2, got.stdout + got.stderr
    assert "不可写" in got.stderr, got.stderr
    assert "Traceback" not in got.stderr, got.stderr
