"""卡 A366：dispatch_shim 的四条判据（卡号 / 树 / 干跑 argv / 按卡查规格）。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from pool import dispatch_shim  # noqa: E402 - 先挂 tools/ 再 import（同仓库其余测试）
from pool.no_window import NO_WINDOW  # noqa: E402 - 同上

SHIM = TOOLS / "pool" / "dispatch_shim.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(SHIM), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT), **NO_WINDOW,
    )


def test_bad_card_is_refused_with_original_words() -> None:
    done = _run("--card", "bad card", "--dry-run")
    assert done.returncode == 2
    assert "卡号不合法：bad card" in done.stdout


def test_bad_tree_is_refused_before_any_dispatch() -> None:
    done = _run("--card", "D1", "--tree", "../etc", "--dry-run")
    assert done.returncode == 2
    assert "树不合法：../etc" in done.stdout


def test_dry_run_prints_the_real_dispatcher_argv() -> None:
    done = _run("--card", "D1", "--dry-run")
    assert done.returncode == 0, done.stdout + done.stderr
    line = done.stdout.strip()
    assert line.startswith("[干跑] ")
    assert "wb_dispatch.py" in line
    assert "--execute" in line and "--detach" in line
    assert "--spec" in line


def test_spec_is_resolved_from_the_ledger_not_the_client() -> None:
    assert dispatch_shim._resolve_spec("D1").endswith(".md")
    assert dispatch_shim._resolve_spec("999") == ""
