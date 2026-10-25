"""卡 E38（T-AG492）：`sync_counts.py` 的根**不再按文件位置算**。

病：`ROOT = Path(__file__).resolve().parent.parent` 把「工具住在哪个仓」当成「账本住在哪个仓」
⇒ 在卡树里用 `../../tools/sync_counts.py` 跑，改的是**主树**的 `复盘/交接-重构进度.md`
（E38 现场把主树弄脏一次，靠 `git checkout -- .` 才还原）。

判据（★ 一律**子进程 + 环境变量**，不许 `monkeypatch.setattr(module, "ROOT", …)` ——
在卡树里两个根恰好相等，改模块常量等于假绿）：
1. `PIPE_DATA=<临时数据根>` ⇒ 只改那份，工具所在树逐字不动；
2. 脚本住在 A 树、当前目录是 B 树（B 有数据根标记）⇒ 改 **B**，A 逐字不动（E38 的真复现）；
3. `--check` 发现漂移 ⇒ 退 1 且**一个字节都不写**；
4. `PIPE_DATA` 与「当前目录像数据根」同时成立 ⇒ **PIPE_DATA 赢**（显式 > 推断）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "sync_counts.py"

STALE = "台账进度：done 0 / partial 0 / todo 0 / deferred 0（共 0 条，豁免 0）\n"


def _tree(base: Path, name: str, *, done: int) -> Path:
    """造一棵「像数据根」的树：台账 + 两份交接文档（数字故意写旧）。"""
    root = base / name
    (root / "docs").mkdir(parents=True)
    (root / "复盘").mkdir(parents=True)
    entries = "".join(
        f'[entries."T-G{900 + i}"]\nid = "T-G{900 + i}"\nstatus = "done"\n' for i in range(done)
    )
    (root / "docs" / "traceability.toml").write_text(entries or "[meta]\nx = 1\n", encoding="utf-8")
    (root / "复盘" / "交接-重构进度.md").write_text("# 交接\n\n" + STALE, encoding="utf-8")
    (root / "复盘" / "长任务执行协议.md").write_text("# 协议\n\n" + STALE, encoding="utf-8")
    return root


def _env(data: Path | None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "PIPE_DATA"}
    if data is not None:
        env["PIPE_DATA"] = str(data)
    return env


def _run(script: Path, cwd: Path, env: dict[str, str], *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(script), *extra],
        cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, check=False,
    )


def _handoff(root: Path) -> str:
    return (root / "复盘" / "交接-重构进度.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------- 1. PIPE_DATA 指哪改哪


def test_pipe_data_edits_only_that_tree(tmp_path: Path) -> None:
    """★ `PIPE_DATA` 指到临时目录时，`sync_counts` 只改那份，工具所在树一个字不动。"""
    data = _tree(tmp_path, "data", done=2)
    tool_tree = _tree(tmp_path, "toolloc", done=0)
    script = tool_tree / "tools" / "sync_counts.py"
    script.parent.mkdir(parents=True)
    script.write_bytes(SCRIPT.read_bytes())
    (tool_tree / "tools" / "pipe_root.py").write_bytes(
        (ROOT / "tools" / "pipe_root.py").read_bytes())

    before_tool = _handoff(tool_tree)
    r = _run(script, tmp_path, _env(data))
    assert r.returncode == 0, r.stdout + r.stderr

    got = _handoff(data)
    assert "done 2 /" in got, got
    assert "（共 2 条" in got, got
    assert _handoff(tool_tree) == before_tool, "工具所在的树被改了（根算错了）"


# ---------------------------------------------------------------- 2. 在卡树里跑，不许改主树


def test_running_from_a_card_tree_does_not_touch_the_main_tree(tmp_path: Path) -> None:
    """★ E38 的真复现：脚本住在主树，**当前目录是卡树** ⇒ 改卡树，主树逐字不动。

    旧实现按 `__file__` 推根 ⇒ 改的是主树（主树被弄脏过一次）。现在按 `data_root()`：
    当前目录有 `docs/traceability.toml` ⇒ 它就是数据根。
    """
    main_tree = _tree(tmp_path, "main", done=0)
    script = main_tree / "tools" / "sync_counts.py"
    script.parent.mkdir(parents=True)
    script.write_bytes(SCRIPT.read_bytes())
    (main_tree / "tools" / "pipe_root.py").write_bytes(
        (ROOT / "tools" / "pipe_root.py").read_bytes())
    card_tree = _tree(tmp_path, "card", done=3)

    before_main = _handoff(main_tree)
    r = _run(script, card_tree, _env(None))
    assert r.returncode == 0, r.stdout + r.stderr

    assert "done 3 /" in _handoff(card_tree), _handoff(card_tree)
    assert _handoff(main_tree) == before_main, "★ 在卡树里跑却改了主树（E38 的病）"


# ---------------------------------------------------------------- 3. --check 只报不写


def test_check_reports_stale_and_writes_nothing(tmp_path: Path) -> None:
    """漂移 ⇒ 退 1 并点名；**一个字节都不写**（`--check` 是可接进门禁的只读口径）。"""
    data = _tree(tmp_path, "data", done=1)
    before = _handoff(data)
    r = _run(SCRIPT, tmp_path, _env(data), "--check")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "需要更新" in (r.stdout + r.stderr)
    assert _handoff(data) == before


# ---------------------------------------------------------------- 4. 显式 > 推断


def test_pipe_data_wins_over_cwd(tmp_path: Path) -> None:
    """`PIPE_DATA` 与「当前目录像数据根」同时成立 ⇒ **PIPE_DATA 赢**（显式不能被推断盖掉）。"""
    data = _tree(tmp_path, "data", done=2)
    cwd_tree = _tree(tmp_path, "cwd", done=0)
    before_cwd = _handoff(cwd_tree)

    r = _run(SCRIPT, cwd_tree, _env(data))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "done 2 /" in _handoff(data)
    assert _handoff(cwd_tree) == before_cwd, "cwd 抢了 PIPE_DATA 的位置"
