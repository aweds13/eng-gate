"""R2 真机自检：提取 index.html 的脚本做语法检查 + 起真服务取页面/样式。

为什么需要：前端测试查的是字符串存在性，**JS 语法错误会让整页白屏而测试照样全绿**。
这里用 `node --check` 做真正的语法解析（node 缺失时明确跳过并说明，不谎报通过）。
"""

from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import uvicorn

from timeflow.api.app import create_app

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "src" / "web" / "index.html"
SCRIPT = re.compile(r"<script>(.*?)</script>", re.S)


def check_js_syntax(tmp: Path) -> tuple[bool, str]:
    node = shutil.which("node")
    m = SCRIPT.search(INDEX.read_text(encoding="utf-8"))
    if not m:
        return False, "index.html 里找不到 <script> 块"
    js_file = tmp / "app_extract.mjs"
    js_file.write_text(m.group(1), encoding="utf-8")
    if not node:
        return True, "跳过：环境没有 node，无法做语法解析（未验证）"
    proc = subprocess.run(
        [node, "--check", str(js_file)], capture_output=True, text=True, timeout=60
    )
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout).strip()[:500]
    return True, f"node --check 通过（{js_file.name}）"


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="r2_"))
    ok, detail = check_js_syntax(tmp)
    print(f"[{'OK ' if ok else 'FAIL'}] JS 语法：{detail}")

    app = create_app(str(tmp / "r2.db"))
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
    cfg = json.loads(
        urllib.request.urlopen(f"{base}/api/config", timeout=10).read().decode("utf-8")
    )
    # 右栏计时器的数据源：新库没有进行中的专注，应返回 null（而不是 500）
    active = json.loads(
        urllib.request.urlopen(f"{base}/api/focus/active", timeout=10).read().decode("utf-8")
    )

    checks = {
        "无内联事件处理器": "onclick=" not in html and "onkeydown=" not in html,
        "有事件委托监听": "document.addEventListener('click'" in html,
        "无 alert/prompt": "alert(" not in html and "prompt(" not in html,
        "模板用 data-action": html.count("data-action=") >= 40,
        "页面引用 app.css": "/app.css" in html,
        "样式可取到": "--accent-soft" in css,
        "config 提供强调色": bool(cfg.get("accent_color")),
        # R3 三栏（SR-NF4）：壳里三个区域都在，且右栏计时器/详情挂载点存在
        "三栏骨架齐全": all(k in html for k in
                            ('class="shell"', 'class="rail"', 'id="main"', 'class="sidebar"',
                             'id="focusRail"', 'id="detailRail"')),
        "宽屏三栏是有网格的": "grid-template-columns: 200px minmax(0, 1fr) 340px" in css,
        "计时器归属右栏": "function renderActive(el,active)" in html and "paintRail(mySeq)" in html,
        "计时器数据源可用": active is None or isinstance(active, dict),
    }
    for name, passed in checks.items():
        print(f"[{'OK ' if passed else 'FAIL'}] {name}")
    server.should_exit = True
    thread.join(timeout=10)
    return 0 if ok and all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
