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
import urllib.error
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


def _rail_nav(html: str) -> str:
    """取出左栏导航那一段（用于检查「设置」入口是否在宽屏左栏里）。"""
    return html.split('class="rail"', 1)[1].split("</nav>", 1)[0]


def _json_call(base: str, path: str, method: str = "GET", payload: dict | None = None,
               headers: dict | None = None) -> tuple[int, object]:
    """打真服务的 JSON 接口，返回 (状态码, 解析结果)。"""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{base}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:  # 4xx/5xx 也要看得到状态码
        return e.code, None


def live_attach_checks(base: str, tmp: Path) -> dict[str, bool]:
    """T-B4 真机自检：附件打开规则在**真服务 + 真文件系统**上的行为。

    只走 `dry_run`（不真的弹资源管理器/开程序）——验的是"规则与解析"这段；
    真正弹窗那一下由用户点「打开」触发，属于人工确认项（见 CHECKPOINT 说明）。
    """
    folder = tmp / "课件"
    folder.mkdir(exist_ok=True)
    pdf = folder / "第3章.pdf"
    pdf.write_text("x", encoding="utf-8")

    _, default_run = _json_call(
        base, "/api/attach/open", "POST", {"target": str(pdf), "dry_run": True}
    )
    _json_call(base, "/api/settings/attach", "PUT", {"mode": "auto"})
    _, auto_run = _json_call(
        base, "/api/attach/open", "POST", {"target": str(pdf), "dry_run": True}
    )
    _, url_run = _json_call(base, "/api/attach/open", "POST", {"target": "https://example.com/x"})
    _, missing_run = _json_call(
        base, "/api/attach/open", "POST", {"target": str(tmp / "没有这个.pdf")}
    )
    dir_run = _json_call(
        base, "/api/attach/open", "POST", {"target": str(folder), "dry_run": True}
    )[1]
    bad_mode = _json_call(base, "/api/settings/attach", "PUT", {"mode": "乱写"})[0]
    bad_ext = _json_call(base, "/api/settings/attach", "PUT", {"whitelist": [".exe"]})[0]
    cross = _json_call(
        base, "/api/attach/open", "POST", {"target": str(pdf), "dry_run": True},
        headers={"Origin": "https://evil.example"},
    )[0]

    def action(payload: object) -> object:
        return payload.get("action") if isinstance(payload, dict) else None

    return {
        "附件规则（默认只到文件夹）": action(default_run) == "folder",
        "附件规则（按格式→定位文件）": action(auto_run) == "select",
        "附件规则（网址交浏览器）": action(url_run) == "browser",
        "附件规则（路径不存在→复制兜底）": action(missing_run) == "copy",
        "附件规则（目录→开目录）": action(dir_run) == "folder",
        "打开方式非法值被拒": bad_mode == 400,
        "白名单拒绝可执行类": bad_ext == 400,
        "跨站来源被拒（本机接口守卫）": cross == 403,
    }


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
        "宽屏三栏是弹性布局": "flex: 0 0 168px" in css and "max-width: 820px" in css,
        "断点互斥(980/979)": "@media (min-width: 980px)" in css
        and "@media (max-width: 979px)" in css,
        "计时器归属右栏": "function renderActive(el,active)" in html and "paintRail(mySeq)" in html,
        "计时器数据源可用": active is None or isinstance(active, dict),
        # 设置页（用户要求统一收拢）+ 挤压/遮挡修复的样式约定
        "左栏有设置入口": 'data-view="setting"' in _rail_nav(html),
        "挤压修复样式在位": ".new button { flex: none }" in css and ".field" in css,
        "暗色令牌可取到": '[data-theme="dark"]' in css,
        # 智能视图可达（T-B3）：左栏 / 全部任务页 / 设置页都有入口 ——
        # 手机端（≤640px）左栏导航被 CSS 隐藏，所以不能只靠左栏（否则手机上直接进不去）。
        "智能视图可达": all(
            f'data-view="{v}"' in _rail_nav(html) and f'data-view="{v}"' in html
            for v in ("important", "planned", "flagged")
        ) and html.count("smartViewNavHTML(") >= 3,
    }
    # 视图路由自检：每个 data-view 要么是合法视图，要么是已注册的动作（点了没反应最难查）
    views = set(re.findall(r"const VIEWS=\[([^\]]*)\]", html)[0].replace("'", "").split(","))
    views = {v.strip() for v in views if v.strip()}
    actions = set(re.findall(r"'([a-z-]+)':\s*(?:el\s*=>|\()", html.split("const ACTIONS")[1]))
    targets = set(re.findall(r'data-view="([a-z-]+)"', html))
    unknown = sorted(targets - views - actions)
    checks["data-view 全部有落点"] = not unknown
    if unknown:
        print(f"[提示] 以下 data-view 既不是视图也没注册动作：{unknown}")
    checks.update(live_attach_checks(base, tmp))
    for name, passed in checks.items():
        print(f"[{'OK ' if passed else 'FAIL'}] {name}")
    server.should_exit = True
    thread.join(timeout=10)
    return 0 if ok and all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
