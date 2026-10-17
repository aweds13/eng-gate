"""卡 A276：timeflow 桌面启动器的钉子（只读源码，不真起服务）。

判据口径：
- 必须是 `.pyw`（用 `pythonw.exe` 跑才不弹黑窗）；
- 起服务必须带 `CREATE_NO_WINDOW`，且用 `stack.py start timeflow`；
- 端口已在听就**不重复起**（幂等）；起不来要弹人话框，不静默；
- 保留 `TF_LAUNCH_DRY` 开关给无人值守自测用。
"""

from __future__ import annotations

from pathlib import Path

LAUNCHER = Path(__file__).resolve().parents[1] / "tools" / "launch_timeflow.pyw"


def test_launcher_is_pyw_and_targets_timeflow() -> None:
    assert LAUNCHER.suffix == ".pyw", "启动器必须是 .pyw（否则会弹黑窗）"
    source = LAUNCHER.read_text(encoding="utf-8")
    assert '"timeflow"' in source and '"start"' in source
    assert "PORT = 8520" in source


def test_launcher_never_shows_console_window() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")
    assert "CREATE_NO_WINDOW" in source
    assert "creationflags=CREATE_NO_WINDOW" in source, "起服务时必须带 CREATE_NO_WINDOW"


def test_launcher_is_idempotent_and_visible_on_failure() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")
    # 幂等：先探端口，已在听就只开浏览器
    assert "if not port_open():" in source
    # 失败可见：起不来必须弹框（不许静默退出）
    assert "messagebox.showerror" in source
    # 起完才开浏览器
    assert "webbrowser.open(URL)" in source
    # 自测开关
    assert "TF_LAUNCH_DRY" in source
