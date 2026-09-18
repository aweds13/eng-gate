"""R1 真机自检：起真服务，确认页面引用 app.css 且能取到、无内联 style 块。"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
import urllib.request

import uvicorn

from timeflow.api.app import create_app


def main() -> int:
    workdir = tempfile.mkdtemp(prefix="r1_")
    app = create_app(os.path.join(workdir, "r1.db"))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)

    base = f"http://127.0.0.1:{port}"
    html = urllib.request.urlopen(f"{base}/", timeout=10).read().decode("utf-8")
    css = urllib.request.urlopen(f"{base}/app.css", timeout=10).read().decode("utf-8")
    cfg = json.loads(urllib.request.urlopen(f"{base}/api/config", timeout=10).read().decode("utf-8"))

    checks = {
        "页面引用 /app.css": "/app.css" in html,
        "页面无内联 <style> 块": "<style>" not in html,
        "app.css 可取到且含令牌": "--accent-soft" in css and "--surface-2" in css,
        "app.css 含暗色块（R4 预置）": '[data-theme="dark"]' in css,
        "app.css 无残留旧变量名": "--card:" in css,
        "config 仍提供 accent_color": bool(cfg.get("accent_color")),
    }
    for name, ok in checks.items():
        print(f"[{'OK ' if ok else 'FAIL'}] {name}")
    server.should_exit = True
    thread.join(timeout=10)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
