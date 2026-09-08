"""桌面程序壳：启动 uvicorn（本地） + pywebview 窗口；若 pywebview 不可用则回退到浏览器。

对应 SR-NF16（本地优先）/ SR-NF1（界面）。
"""

from __future__ import annotations

import threading
import webbrowser

import uvicorn

from timeflow.api.app import create_app
from timeflow.config import load_settings


def main() -> None:
    settings = load_settings()
    app = create_app(settings.database.path)
    port = 8520
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    try:
        import webview

        webview.create_window("timeflow", f"http://127.0.0.1:{port}", width=1080, height=720)
        webview.start()
    except Exception:
        webbrowser.open(f"http://127.0.0.1:{port}")
        thread.join()


if __name__ == "__main__":
    main()
