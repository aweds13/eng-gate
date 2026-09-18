"""起一个「旧版本前端」预览服务，用同一个后端，供与当前界面对比（临时调试工具）。

为什么需要：前端大改之后，"是不是改崩了"只能靠**看**。但回退 git 只能整份代码回退，
而界面需要的是「旧前端 + 现后端」并排跑：当前界面在 8520，旧界面在另一个端口，同一个库、同一份数据。

做法：从 git 历史按字节取出某个提交的 `src/web/index.html` 与 `app.css` 直接服务；
页面里注入 `<base href="现后端">`，于是 `/api/...`、`/manifest.json` 等请求都打到正在跑的那个后端，
而样式与脚本用旧版本自己的 —— 这就是"改之前的界面"。

用法：
    python -X utf8 tools/ui_ab.py <rev> [--port 8521] [--backend http://127.0.0.1:8520]
    # 例：python -X utf8 tools/ui_ab.py ca7c7cb --port 8521     # R3 三栏之前 = 单列版
    # 然后浏览器开 http://127.0.0.1:8521/ 与 http://127.0.0.1:8520/ 并排看

注意：只读 git 历史，不写工作区；不启动第二个后端、不动数据库。
"""

from __future__ import annotations

import argparse
import functools
import http.server
import re
import socketserver
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = {"index.html": "src/web/index.html", "app.css": "src/web/app.css"}


def read_rev(rev: str, path: str) -> bytes | None:
    blob = subprocess.run(
        ["git", "show", f"{rev}:{path}"], cwd=ROOT, capture_output=True, check=False
    )
    return blob.stdout if blob.returncode == 0 else None


def build_html(rev: str, backend: str) -> bytes:
    raw = read_rev(rev, FILES["index.html"])
    if raw is None:
        raise SystemExit(f"git 历史里没有 {rev}:{FILES['index.html']}")
    html = raw.decode("utf-8")
    # 旧页面的 /app.css、/api/... 都是根路径：base 指到现后端，再单独把样式换回旧版自己的
    html = re.sub(r"(<head[^>]*>)", rf'\1\n<base href="{backend}/">', html, count=1)
    html = html.replace(
        "</head>", '<link rel="stylesheet" href="/old-app.css"></head>', 1
    )
    return html.encode("utf-8")


class Handler(http.server.BaseHTTPRequestHandler):
    rev = ""
    backend = ""
    html = b""
    css = b""

    def do_GET(self) -> None:  # noqa: N802 —— http.server 约定
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send(self.html, "text/html; charset=utf-8")
        elif path == "/old-app.css":
            self._send(self.css, "text/css; charset=utf-8")
        elif path == "/__rev":
            self._send(f"{self.rev} -> backend {self.backend}".encode(), "text/plain")
        else:
            self.send_error(404, "本服务只提供旧版 index.html / app.css；接口请走 base 指定的后端")

    def _send(self, body: bytes, ctype: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:  # 静音
        return


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("rev", help="要预览的提交（如 ca7c7cb = R3 之前）")
    ap.add_argument("--port", type=int, default=8521)
    ap.add_argument("--backend", default="http://127.0.0.1:8520")
    args = ap.parse_args()

    css = read_rev(args.rev, FILES["app.css"])
    Handler.rev = args.rev
    Handler.backend = args.backend
    Handler.html = build_html(args.rev, args.backend)
    Handler.css = css or "/* 该提交还没有抽出 app.css（R1 之前） */".encode()

    handler = functools.partial(Handler)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", args.port), handler) as httpd:
        print(f"[旧版前端] {args.rev}  ->  http://127.0.0.1:{args.port}/")
        print(f"[同一个后端] {args.backend}   （当前界面对着它自己的端口）")
        print("[提示] Ctrl+C 停止；本服务只读 git 历史，不碰工作区与数据库")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[停止]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
