"""timeflow 桌面启动器 —— 双击图标：无黑窗起服务 → 等端口 → 开浏览器。

用途（卡 A273）：timeflow 是用户自己的个人管理工具，**不依赖 DSH** 也要能双击打开。
本文件后缀 `.pyw`：由 `pythonw.exe` 运行时**不弹控制台窗口**。

判据（都由本文件自己保证）：
- 端口已经在听 ⇒ 直接开浏览器，不重复起服务（幂等）。
- 服务没起 ⇒ 用 `pythonw` + `CREATE_NO_WINDOW` 起 `tools/stack.py start timeflow`，
  等端口最长 20 秒；等不到就弹一个能看懂的错误框（不静默失败）。
- 不管起没起成功，都**不留下黑窗**。
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import webbrowser

ROOT = r"D:/repo/engineering"
HOST = "127.0.0.1"
PORT = 8520
URL = f"http://{HOST}:{PORT}/"
WAIT_SECONDS = 20.0
CREATE_NO_WINDOW = 0x08000000


def port_open(timeout: float = 1.0) -> bool:
    """端口在听 = 服务活着。"""
    try:
        with socket.create_connection((HOST, PORT), timeout=timeout):
            return True
    except OSError:
        return False


def start_service() -> None:
    """后台起服务：pythonw，不弹窗，输出丢弃（细节看 gates/diag/stack-actions.log）。"""
    subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "tools", "stack.py"), "start", "timeflow"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )


def complain(message: str) -> None:
    """起不来时给一个人话框（不静默）。"""
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        from tkinter import messagebox

        messagebox.showerror("timeflow 没起来", message)
        root.destroy()
    except Exception:
        pass


def main() -> int:
    if not port_open():
        start_service()
        deadline = time.time() + WAIT_SECONDS
        while time.time() < deadline and not port_open():
            time.sleep(0.5)
    # 测试用：TF_LAUNCH_DRY=1 时只起服务、不开浏览器（便于无人值守自测）。
    if os.environ.get("TF_LAUNCH_DRY") == "1":
        return 0
    if not port_open(timeout=2.0):
        complain(
            f"等了 {WAIT_SECONDS:.0f} 秒，{URL} 还是连不上。\n\n"
            f"手动排查：在仓库根跑  python -X utf8 tools/stack.py status\n"
            f"日志：{os.path.join(ROOT, 'gates', 'diag', 'stack-actions.log')}"
        )
        return 1
    webbrowser.open(URL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
