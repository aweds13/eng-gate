"""核「每道门硬超时」会不会咬（T-G196 · 卡 100）。

## 为什么有这张测试

病根：**一道门卡死 = 整趟门禁永久挂死**。2026-10-01 落卡 092 时，`ui_flow` 那道门真卡死
56 分钟（正常 386 秒）——`scripts/run_gates.py` 一直 `communicate()` 等它，锁租约到了也不杀。
本卡给每道门加硬超时：到点 → 掐**整棵进程树**（不是只杀父的，否则 `node` 底下的 `serve.py`
与无头 `msedge` 会变孤儿占端口）→ 记 `exit_code = 124` + `timeout=True`、summary 写清
「超时 N 秒被掐」并报门名/pid/子进程数 → **判红**；其余门的结论照常收完。

## 怎么验（用假门，不真跑真机门）

假门 = `sleep`（本机 Git 自带）；走 `start_gate()` / `finish_gate()` 这条**真路径**，
`monkeypatch` 两个 `LOG_DIR`（假的日志别落进仓库）。每条判据都配**反例**：正常门不许被误掐、
`TF_GATE_DOOR_TIMEOUT=0` 要关得掉。

## 边界（如实写，未覆盖）

- **不跑 `main()` 全量**（本卡明确"改门禁自己时跑全量会自相矛盾"）。所以"整趟退非 0"用
  `gates_ok()` 钉 —— 那是 `main()` 收口时**用的同一条判据**（`exit_code=124` 落进 `!= 0`）。
- 假门是 `sleep`（Git 自带）；"子进程真被收掉"那条用 `python` 包一层再 spawn 一个 `sleep`。
- 只钉 Windows 的 `taskkill /T` 路径（本仓主力在 Windows）；POSIX 分支没在本机跑过。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import run_gates as rg  # noqa: E402 —— 需要先用 sys.path 把 scripts/ 挂上


def _sleep_cmd(seconds: float) -> list[str]:
    """假门：睡 `seconds` 秒然后退出（就这一件事，跑不出别的读数）。

    ★ 卡 E44：**不许依赖 PATH 上的 `sleep`**。裸 Windows（云机 Windows Server）上没有
    这个可执行文件，`shutil.which("sleep")` 返回 None ⇒ 一整族「假门」用例在那里直接红
    （主控实测：云机 pass1 报「本机 PATH 里没有 sleep，假门造不出来」）。改用解释器自己，
    跨平台且版本跟着 `sys.executable` 走。
    """
    return [sys.executable, "-c", f"import time; time.sleep({float(seconds)})"]


def _alive(pid: int) -> bool:
    """进程 `pid` 还活着吗（僵尸不算）。本用例要 psutil 才判得了。"""
    ps = rg._psutil()
    assert ps is not None, "本用例需要 psutil 才判得了子进程死活"
    try:
        proc = ps.Process(pid)
        return proc.is_running() and proc.status() != ps.STATUS_ZOMBIE
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _logs_into_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """假门的日志落 tmp（别把 `gates/logs/<假门名>.log` 甩进真仓库）。"""
    monkeypatch.setattr(rg, "LOG_DIR", tmp_path / "logs")


# ------------------------------------------------------------------ door_timeout 解析

def test_door_timeout_default_override_and_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认 1800；覆盖生效；坏值退回默认（不静默）；`0` = 关（None）。"""
    monkeypatch.delenv("TF_GATE_DOOR_TIMEOUT", raising=False)
    assert rg.door_timeout() == 1800

    monkeypatch.setenv("TF_GATE_DOOR_TIMEOUT", "42")
    assert rg.door_timeout() == 42

    monkeypatch.setenv("TF_GATE_DOOR_TIMEOUT", "abc")
    assert rg.door_timeout() == 1800  # 坏值 → 退回默认

    monkeypatch.setenv("TF_GATE_DOOR_TIMEOUT", "0")
    assert rg.door_timeout() is None  # 关掉这条路


# ------------------------------------------------------ 文档判据指向真源（卡 160 · T-G260）
#
# 来路 INV-31：门禁/工具文档里的判据描述会落后于代码 —— `门禁四要素.md` 曾写
# 「run_gates 没给每道门超时」，而代码早就有 `DEFAULT_DOOR_TIMEOUT`（卡 100 / T-G196）。
# 判据：那一页的「超时」描述必须**指向真源**（`DEFAULT_DOOR_TIMEOUT`），别复述一个会漂的数值。

def test_door_timeout_doc_points_at_the_truth_source() -> None:
    """★ `门禁四要素.md` 不许再说「每道门没有超时」——要指向 `DEFAULT_DOOR_TIMEOUT`。

    反例（先红）：文档里还有「没有超时」这句（代码早有硬超时）⇒ 本用例当场红。
    另钉：门数不许写死旧值（`17 道门`）——真源是门表 / `gates/last.json`。
    """
    doc = (ROOT / "复盘" / "门禁四要素.md").read_text(encoding="utf-8")
    assert "DEFAULT_DOOR_TIMEOUT" in doc, "文档没指向真源（DEFAULT_DOOR_TIMEOUT）"
    assert "没有超时" not in doc, "文档还写着过时的『每道门没有超时』"
    assert "17 道门" not in doc, "门数写死在文档里了（真源 = 门表 / gates/last.json）"


# ------------------------------------------------------------------ 主判据：超时被掐 + 判红

def test_timeout_kills_gate_records_124_and_others_survive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """★ 假门 `sleep 60` + 超时 3 秒 → 被掐、`exit_code==124`、summary 有「超时」与秒数、
    整趟退非 0；**其它假门照常收完**（证明其余结论不被超时吞掉）。"""
    monkeypatch.setenv("TF_GATE_DOOR_TIMEOUT", "3")
    timeout = rg.door_timeout()
    assert timeout == 3

    results: list[dict[str, object]] = []
    slow_proc, slow_t0, why = rg.start_gate("slow", _sleep_cmd(60))
    assert slow_proc is not None, why
    results.append(rg.finish_gate("slow", slow_proc, slow_t0, timeout))

    # 超时之后，同一趟里**别的门照常收完**（读秒正常绿）
    quick_proc, quick_t0, why2 = rg.start_gate("quick", _sleep_cmd(0.2))
    assert quick_proc is not None, why2
    results.append(rg.finish_gate("quick", quick_proc, quick_t0, timeout))

    slow, quick = results[0], results[1]
    assert slow["exit_code"] == 124                      # timeout(1) 的约定俗成
    assert slow["timeout"] is True                       # 机器可读
    assert "超时" in str(slow["summary"])                 # 人话
    assert "3" in str(slow["summary"])                   # 秒数
    assert int(slow["killed_pid"]) == slow_proc.pid      # 点名了是哪道门/哪个 pid
    assert quick["exit_code"] == 0                       # 其余门收完
    assert "timeout" not in quick
    assert rg.gates_ok(results) is False                 # 整趟退非 0（超时不被吞掉）


# ------------------------------------------------------------------ 反例

def test_normal_gate_is_not_killed_when_within_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """★ 反例：假门 `sleep 0.2` + 超时 60 秒 → **正常绿**（别把正常的门也掐了）。"""
    monkeypatch.setenv("TF_GATE_DOOR_TIMEOUT", "60")
    timeout = rg.door_timeout()

    proc, t0, why = rg.start_gate("quick", _sleep_cmd(0.2))
    assert proc is not None, why
    item = rg.finish_gate("quick", proc, t0, timeout)

    assert item["exit_code"] == 0
    assert "timeout" not in item
    assert rg.gates_ok([item]) is True


def test_zero_env_disables_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 反例：`TF_GATE_DOOR_TIMEOUT=0` → 不掐（这条路要关得掉）。

    造一个**跑 2 秒**的假门：关掉超时后它必须**自然跑完**（exit 0、耗时 ≥1.5 秒）——
    若还有人在暗处设了个小默认值，这道门会被掐成 124。"""
    monkeypatch.setenv("TF_GATE_DOOR_TIMEOUT", "0")
    timeout = rg.door_timeout()
    assert timeout is None

    proc, t0, why = rg.start_gate("two_seconds", _sleep_cmd(2))
    assert proc is not None, why
    item = rg.finish_gate("two_seconds", proc, t0, timeout)

    assert item["exit_code"] == 0
    assert "timeout" not in item
    assert float(item["seconds"]) >= 1.5  # 真等它跑完了，不是被提前掐的


# ------------------------------------------------------------------ 子进程真被收掉

def test_timeout_kills_the_whole_tree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """★ 假门里再 spawn 一个 `sleep` → 超时掐树后，**那孙子进程也不再活着**。

    这一条盯的正是卡死那串的形态（`node` 底下挂着 `serve.py` + 无头 `msedge`）：
    只杀父的会留下孤儿占端口。"""
    monkeypatch.setenv("TF_GATE_DOOR_TIMEOUT", "3")
    pidfile = tmp_path / "child.pid"
    code = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.argv[1], '-c', 'import time; time.sleep(60)'])\n"
        "open(sys.argv[2], 'w').write(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    cmd = [sys.executable, "-c", code, sys.executable, str(pidfile)]

    proc, t0, why = rg.start_gate("tree", cmd)
    assert proc is not None, why
    item = rg.finish_gate("tree", proc, t0, rg.door_timeout())

    assert item["exit_code"] == 124
    assert int(item["killed_children"]) >= 1  # 报出了"掐了几个子进程"

    child_pid = int(pidfile.read_text(encoding="utf-8").strip())
    deadline = time.time() + 5  # 给 OS 一点时间回收（有界，不空转）
    while _alive(child_pid) and time.time() < deadline:
        time.sleep(0.1)
    assert not _alive(child_pid), f"子进程 {child_pid} 还活着 —— 整树没掐干净"


def test_fake_gate_runs_without_sleep_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 卡 E44：PATH 上没有 `sleep` 时假门照样造得出来（裸 Windows 的形态）。

    这就是「换到云机 Windows Server 不许整族红」的机器钉子 —— 修之前 `_sleep_cmd`
    直接 `assert SLEEP`，PATH 一收窄就红。
    """
    import subprocess as _sp

    monkeypatch.setenv("PATH", str(Path(sys.executable).parent))
    done = _sp.run(_sleep_cmd(0.05), capture_output=True, timeout=30)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
