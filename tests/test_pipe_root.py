"""工具根 vs 数据根（卡 A326）的钉子。

四条：三条口径 + 两条真跑（`wb_notify` / `wb_plan` 在 `PIPE_DATA` 指到别处时，
必须读那个目录的账本与产物，不许回本仓）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"


def _env(**over: str) -> dict[str, str]:
    env = dict(os.environ)
    for k in ("PIPE_DATA", "PIPE_HOME"):
        env.pop(k, None)
    env.update(over)
    return env


def _ledger(path: Path, card: str = "DEMO") -> None:
    (path / "docs").mkdir(parents=True, exist_ok=True)
    body = (
        '[base]\nreviewed = "38522420"\n'
        f'[[cards]]\nid = "{card}"\ntask = "T-{card}"\ntitle = "demo"\n'
        f'tree = ".wt/{card}"\nspec = "复盘/卡/卡{card}.md"\nfiles = []\n'
        'risk = "low"\nstatus = "pending"\n'
    )
    (path / "docs" / "workbacklog.toml").write_text(body, encoding="utf-8")


def test_data_root_honours_pipe_data(tmp_path: Path) -> None:
    sys.path.insert(0, str(TOOLS))
    try:
        import pipe_root
    finally:
        sys.path.pop(0)
    old = os.environ.get("PIPE_DATA")
    os.environ["PIPE_DATA"] = str(tmp_path)
    try:
        assert pipe_root.data_root() == tmp_path.resolve()
    finally:
        if old is None:
            os.environ.pop("PIPE_DATA", None)
        else:
            os.environ["PIPE_DATA"] = old


def test_data_root_falls_back_to_cwd_with_ledger(tmp_path: Path, monkeypatch) -> None:
    _ledger(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PIPE_DATA", raising=False)
    sys.path.insert(0, str(TOOLS))
    try:
        import pipe_root
    finally:
        sys.path.pop(0)
    assert pipe_root.data_root() == tmp_path.resolve()


def test_wb_notify_reads_and_writes_the_data_root(tmp_path: Path) -> None:
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    (diag / "wb-DEMO.verdict.txt").write_text("判决：正常收工（退出码 0）\n", encoding="utf-8")
    _ledger(tmp_path)
    run = subprocess.run(
        [sys.executable, "-X", "utf8", str(TOOLS / "wb_notify.py"), "--once"],
        cwd=str(tmp_path),
        env=_env(PIPE_DATA=str(tmp_path)),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert run.returncode == 0, run.stderr
    written = diag / "notifications.jsonl"
    assert written.exists(), f"没写到数据根：{run.stdout}"
    rows = [json.loads(x) for x in written.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert rows and rows[0]["card"] == "DEMO"


def test_wb_plan_reads_the_ledger_from_the_data_root(tmp_path: Path) -> None:
    _ledger(tmp_path, "ZZ1")
    run = subprocess.run(
        [sys.executable, "-X", "utf8", str(TOOLS / "wb_plan.py"), "check"],
        cwd=str(TOOLS.parent),
        env=_env(PIPE_DATA=str(tmp_path)),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    out = run.stdout + run.stderr
    # 判据：它读的是数据根的账本（只提到 ZZ1），不是工具所在仓的 200 张卡。
    assert "ZZ1" in out, out[-800:]
    assert "A272" not in out, out[-800:]
