"""一键起本地服务：备份现有库 -> 起 uvicorn（默认 8520）-> 打印访问地址。

用法：
    python -X utf8 tools/serve.py            # 用默认库 data/timeflow.db（只监听本机）
    python -X utf8 tools/serve.py --window    # 起服务 + 开**桌面窗口**（pywebview）
    python -X utf8 tools/serve.py --port 8530
    python -X utf8 tools/serve.py --fresh     # 用临时空库（演示/试验用，不动真实数据）
    python -X utf8 tools/serve.py --debug     # 开调试日志（logs/timeflow.jsonl 记更细）
    python -X utf8 tools/serve.py --lan       # **显式**开一次局域网访问（默认关；手机能连）
    python -X utf8 tools/serve.py --today 2026-06-15   # **假时钟**：把"今天"钉住（只给验证层用）

`--today` 是什么（T-G62）：把 `timeflow.clock` 的「今天」钉在某一天（那一年的本地正午）。
渲染黄金里有两个视图锚在「今天」上（`habit` / `stats` 的热力图窗口与首日标签），
不钉住的话它们**跨过午夜就自己变红**（2026-09-25 00:0x 实测红 6 份）。
采集工具（`render_check.mjs` / `ui_flow_check.mjs`）起服务时传同一个日期，并给浏览器注入
`Date` 垫片钉到同一天 —— 两边不一致就等于伪造了一个界面。**产品路径永远不传这个参数。**

为什么不是直接一句 uvicorn：项目默认库是真实数据，升级代码后首次连接会跑 schema 迁移；
先自动备份一份 `.bak-<时间戳>` 更稳妥（对齐 conventions「重要数据可备份、可回滚」）。
备份的写法与"从备份恢复"共用 `timeflow.storage.backup`（**只有一处口径**）。

`--window` 是什么：桌面程序形态（AC-11）。窗口开不了时**会说出原因**再退回浏览器，
不静默 —— 用户 2026-09-21 的验收项之一就是"窗口到底开不开"。

`--lan` 是什么（SR-NF17 场景 ② / T-G10b）：把服务绑到 `0.0.0.0`，于是**同一 WiFi 下的手机**
能打开它；同时装上**配对码那道门**（非本机设备要带码才能读数据）。
**默认关**（口径同 N16「默认收严、用户再放宽」）；开的时候会把地址、配对码、
以及"同一 WiFi 下别的设备也可能访问到"这句代价一并打印出来（见 `core/lan.banner`）。
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _lan_module() -> object:
    """拿到 `timeflow.core.lan`（把 src 加进 sys.path；与 `backup()` 同一套做法）。"""
    sys.path.insert(0, str(ROOT / "src"))
    from timeflow.core import lan as lan_mod

    return lan_mod


def backup(db_path: Path) -> Path | None:
    """备份现库（薄封装：真正的口径在 `timeflow.storage.backup.make_backup`）。"""
    sys.path.insert(0, str(ROOT / "src"))
    from timeflow.storage import backup as backup_mod

    target = backup_mod.make_backup(db_path)
    if target is None:
        print(f"[跳过备份] {db_path} 不存在（首次运行会新建）")
    else:
        print(f"[已备份] {db_path.name} -> {target.name}")
    return target


def peek(db_path: Path) -> None:
    if not db_path.exists():
        return
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        ver = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        tasks = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()
        facts = conn.execute("SELECT COUNT(*) FROM facts").fetchone()
        print(
            f"[库内容] schema v{ver[0] if ver else '?'} · 任务 {tasks[0]} 条 · 事实 {facts[0]} 条"
        )
        conn.close()
    except Exception as exc:  # noqa: BLE001 —— 只读探察失败不应挡住启动
        print(f"[库内容] 读取失败（不影响启动）：{exc}")


def can_bind(port: int, host: str = "127.0.0.1") -> bool:
    """★ 卡 250：挑端口用「能不能 bind」判定（照 dsh-pilot 的 canBind），不靠 HTTP 探测。

    HTTP 探测会骗人：端口被非 HTTP 的东西占着（裸 socket）⇒ 超时 ⇒ 误判「空闲」；
    端口上是别的 HTTP 服务 ⇒ 探测成功 ⇒ 误判「我们的活着」。bind 不会：
    占着就是占着（含被占用、权限不足），一次给真话。
    """
    import socket

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def pick_port(
    start: int, host: str = "127.0.0.1", tries: int = 10
) -> tuple[int | None, list[int]]:
    """从 `start` 起逐个试 bind：第一个能 bind 的胜出；全忙 ⇒ (None, 试过的端口清单)。"""
    tried: list[int] = []
    for port in range(start, start + tries):
        tried.append(port)
        if can_bind(port, host):
            return port, tried
    return None, tried


def _health_probe(base_url: str, timeout: float) -> tuple[str, object]:
    """取 `/api/health` 的**身份指纹**（我们服务的自述，现成端点，SR-NF13）。

    返回 (verdict, 详情)：`no_response`（连不上/没回话）｜ `mismatch`（有响应但不是我们）
    ｜ `alive`（自述对得上）。指纹判据：JSON 对象且 `status∈{ok,degraded}`、
    带 `database_ok` 与 `schema_version` —— 这是本项目 `/api/health` 的固定形状。
    """
    import json as _json
    import urllib.error
    import urllib.request

    url = base_url.rstrip("/") + "/api/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        return "mismatch", f"HTTP {exc.code}"
    except Exception:  # noqa: BLE001 —— 拒连/超时/非 HTTP 回话都算「没响应」
        return "no_response", None
    try:
        info = _json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return "mismatch", f"非 JSON 自述：{raw[:60]!r}"
    if (
        isinstance(info, dict)
        and info.get("status") in ("ok", "degraded")
        and "database_ok" in info
        and "schema_version" in info
    ):
        return "alive", info
    return "mismatch", info


def check_alive(base_url: str, timeout: float = 2.0) -> tuple[bool, str]:
    """判活 + **验明正身**（卡 250）：先取 `/api/health` 指纹，再下结论。

    - 指纹对 ⇒ 「活着」✓；
    - 有响应但指纹对不上（别的服务）⇒ 「验明失败」并拒绝接入，带下一步排查命令
      （照 pilot 的「错误即修复指令」口径）✓；
    - 端口根本没有响应 ⇒ 「没起」✓。
    """
    verdict, detail = _health_probe(base_url, timeout)
    base = base_url.rstrip("/")
    port = base.rsplit(":", 1)[-1]
    if verdict == "alive":
        status = detail.get("status") if isinstance(detail, dict) else "?"  # type: ignore[union-attr]
        return True, f"[活着] {base} 是本项目服务（/api/health 指纹对：status={status}）"
    if verdict == "mismatch":
        return False, (
            f"[验明失败] {base} 上是别的服务（/api/health 指纹对不上：{detail}）"
            f"—— 拒绝接入。\n"
            f"  下一步：netstat -ano | findstr :{port} 看谁占着端口；"
            f"curl {base}/api/health 核对指纹；或换端口重起："
            f"python tools/serve.py --port <别的端口>"
        )
    return False, (
        f"[没起] {base} 没有响应（连接被拒或超时）。\n"
        f"  下一步：手动起一次看真实报错：python tools/serve.py --port {port}"
    )


def wait_alive(
    base_url: str, timeout: float = 15.0, poll: float = 0.25
) -> tuple[bool, str]:
    """接入前的轮询判活（服务刚起还没就绪要等）；**验明失败立即返回**——
    对方的身份不会越等越对。超时仍没起来 ⇒ 返回最后一次「没起」。"""
    import time

    deadline = time.monotonic() + timeout
    last = (False, "")
    while True:
        ok, msg = check_alive(base_url)
        if ok:
            return True, msg
        if "验明失败" in msg:
            return False, msg
        last = (ok, msg)
        if time.monotonic() >= deadline:
            return last
        time.sleep(poll)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8520)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--fresh", action="store_true", help="用临时空库，不动真实数据")
    parser.add_argument("--no-backup", action="store_true")
    parser.add_argument(
        "--window",
        action="store_true",
        help="起服务后开桌面窗口（pywebview）；开不了会说原因并退回浏览器",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="开调试日志（logs/timeflow.jsonl 记更细；等价 TF_DEBUG=1）",
    )
    parser.add_argument(
        "--lan",
        action="store_true",
        help="显式开启局域网访问（默认关）：绑 0.0.0.0 + 装配对码那道门，手机才能连",
    )
    parser.add_argument(
        "--today",
        default="",
        help="假时钟：把「今天」钉在 YYYY-MM-DD（只给验证层用；产品路径不要传）",
    )
    args = parser.parse_args()

    if args.today:
        # 假时钟（T-G62）：`timeflow.clock` 认这个环境变量；设了就落到那一天的本地正午。
        # 起服务时设（而不是运行期改）—— 采集工具每次都起一个新服务，口径单一。
        os.environ["TIMEFLOW_FAKE_TODAY"] = args.today
        print(f"[假时钟] 「今天」被钉在 {args.today}（本地正午）—— 只给验证层用")

    if args.debug:
        # 调试开关只影响日志级别，不改变任何业务行为（见 src/timeflow/logs.py 的约定）
        os.environ["TF_DEBUG"] = "1"

    import tempfile

    from timeflow.config import load_settings

    settings = None
    db_path: Path
    if args.fresh:
        fresh_dir = Path(tempfile.mkdtemp(prefix="timeflow_fresh_"))
        db_path = fresh_dir / "timeflow.db"
        # 「新鲜库」就该是干净的：markdown 落盘目录也指到临时目录，
        # 否则演示数据会写进仓库的 `export/`（T-G4 的自动导出）
        os.environ.setdefault("TIMEFLOW_EXPORT__DIR", str(fresh_dir / "export"))
        print(f"[临时库] {db_path}")
    else:
        settings = load_settings()
        db_path = Path(settings.database.path)
        if not db_path.is_absolute():
            db_path = ROOT / db_path
        peek(db_path)
        if not args.no_backup:
            backup(db_path)

    # 局域网（②）：**显式**开关 —— `--lan` 或者配置里的 `[net] allow_lan = true`。
    # 它和"绑哪个地址"是同一个决定，所以在这里一次性定下来（运行期改不了，界面也这么写）。
    lan = bool(args.lan or (settings is not None and settings.net.allow_lan))
    host = "0.0.0.0" if lan else args.host
    if not lan and args.host not in ("127.0.0.1", "localhost"):
        print("[拒绝] 本项目本地优先：只允许绑定回环地址", file=sys.stderr)
        print("      要同一 WiFi 下的手机也能连，用：python tools/serve.py --lan", file=sys.stderr)
        return 2

    # ★ 卡 250：挑端口用「能不能 bind」—— bind 失败（被占用/权限不足）⇒ 报忙并顺延；
    # 全忙 ⇒ 非零退出，把试过哪些端口原样打出来。
    port, tried = pick_port(args.port, host)
    if port is None:
        print(
            f"[端口全忙] 从 {args.port} 起连试 {len(tried)} 个端口都被占用：{tried}",
            file=sys.stderr,
        )
        print("      换个起点：python tools/serve.py --port <端口>", file=sys.stderr)
        return 2
    if port != args.port:
        print(f"[端口顺延] {args.port} bind 失败（被占用），顺延到 {port}")
    args.port = port

    import uvicorn

    from timeflow.api.app import create_app

    lan_mod = _lan_module()
    browse = "127.0.0.1" if lan else host
    url = f"http://{browse}:{args.port}"
    print(f"[启动] {url}  （库：{db_path}）")
    if lan:
        # 配对码落库（重启不变）；打印地址与代价 —— 说什么、怎么说在 `core/lan.banner` 一处
        from timeflow.storage import db as db_mod

        conn = db_mod.connect(str(db_path))
        try:
            for line in lan_mod.banner(args.port, lan_mod.code(conn)):  # type: ignore[attr-defined]
                print(line)
        finally:
            conn.close()
    else:
        print("[提示] Ctrl+C 停止；数据全在本机，不出网（手机连不上；要连用 --lan）")

    app = create_app(str(db_path), allow_lan=lan, port=args.port)
    if args.window:
        return _run_window(app, browse, args.port)

    uvicorn.run(app, host=host, port=args.port, log_level="warning")
    return 0


def _run_window(app: object, host: str, port: int) -> int:
    """起服务 + 开桌面窗口（AC-11）。窗口开不了**必须说出原因**，不静默。"""
    import threading

    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, log_level="warning")  # type: ignore[arg-type]
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    # ★ 卡 250：接入前先判活 + 验明正身 —— 指纹不对（端口被别的服务抢了）⇒ 拒绝接入；
    # 一直没响应（服务没起来）⇒ 也别开窗口，把原因说出来。
    ok, msg = wait_alive(f"http://{host}:{port}", timeout=15.0)
    if not ok:
        print(msg, file=sys.stderr)
        server.should_exit = True
        return 2
    print(msg)
    try:
        import webview
    except Exception as exc:  # noqa: BLE001 —— 依赖缺失/导入失败都要说清
        import webbrowser

        print(f"[退回浏览器] 打不开窗口：import webview 失败（{exc}）")
        webbrowser.open(f"http://{host}:{port}")
        thread.join()
        return 0
    try:
        webview.create_window("timeflow", f"http://{host}:{port}", width=1080, height=720)
        webview.start()
    except Exception as exc:  # noqa: BLE001 —— 窗口起不来（缺 WebView2 运行时等）
        import webbrowser

        print(f"[退回浏览器] 窗口起不来：{exc}")
        print(f"[提示] 仍然可以用浏览器打开 {f'http://{host}:{port}'}")
        webbrowser.open(f"http://{host}:{port}")
        thread.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
