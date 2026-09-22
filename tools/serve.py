"""一键起本地服务：备份现有库 -> 起 uvicorn（默认 8520）-> 打印访问地址。

用法：
    python -X utf8 tools/serve.py            # 用默认库 data/timeflow.db
    python -X utf8 tools/serve.py --window    # 起服务 + 开**桌面窗口**（pywebview）
    python -X utf8 tools/serve.py --port 8530
    python -X utf8 tools/serve.py --fresh     # 用临时空库（演示/试验用，不动真实数据）
    python -X utf8 tools/serve.py --debug     # 开调试日志（logs/timeflow.jsonl 记更细）

为什么不是直接一句 uvicorn：项目默认库是真实数据，升级代码后首次连接会跑 schema 迁移；
先自动备份一份 `.bak-<时间戳>` 更稳妥（对齐 conventions「重要数据可备份、可回滚」）。
备份的写法与"从备份恢复"共用 `timeflow.storage.backup`（**只有一处口径**）。

`--window` 是什么：桌面程序形态（AC-11）。窗口开不了时**会说出原因**再退回浏览器，
不静默 —— 用户 2026-09-21 的验收项之一就是"窗口到底开不开"。
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


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
    args = parser.parse_args()

    if args.debug:
        # 调试开关只影响日志级别，不改变任何业务行为（见 src/timeflow/logs.py 的约定）
        os.environ["TF_DEBUG"] = "1"

    if args.host not in ("127.0.0.1", "localhost"):
        print("[拒绝] 本项目本地优先：只允许绑定回环地址", file=sys.stderr)
        return 2

    import tempfile

    from timeflow.config import load_settings

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

    import uvicorn

    from timeflow.api.app import create_app

    url = f"http://{args.host}:{args.port}"
    print(f"[启动] {url}  （库：{db_path}）")
    print("[提示] Ctrl+C 停止；数据全在本机，不出网")

    if args.window:
        return _run_window(create_app(str(db_path)), args.host, args.port)

    uvicorn.run(create_app(str(db_path)), host=args.host, port=args.port, log_level="warning")
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
