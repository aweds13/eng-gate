"""桌面程序壳：启动 uvicorn（本地） + pywebview 窗口；若 pywebview 不可用则回退到浏览器。

对应 SR-NF16（本地优先）/ SR-NF1（界面）/ AC-11（桌面形态）。

三条口径（2026-09-21 用户定"装 pywebview、走窗口形态"时一并理顺）：
- **起窗口前也备份**：以前只有 `tools/serve.py` 备份，走 `timeflow` 这个入口反而不备份 ——
  同一件事两套行为，属于隐患；现在两边共用 `storage/backup.make_backup`。
- **回退必须出声**：窗口开不了要**说出原因**（依赖缺失 / WebView2 运行时缺失 / 其它），
  再退回浏览器。"静默回退"会让用户以为自己在用桌面版，实际是浏览器 —— 不许这样。
- **局域网访问（G 批 · T-G10b / 场景 ②）**：窗口模式也认 `[net] allow_lan` ——
  开了就绑 `0.0.0.0`（手机能连）、并打印地址与配对码；**窗口自己仍然走回环**。
  默认关（口径同 N16「默认收严、用户再放宽」）。

★ **同一个入口也是命令行**（T-G64）：第一个词是已知子命令（`timeflow today`）或 `--help`
时走 `timeflow.cli`（只读命令，**不开窗口、不起服务**）。**不带参数的行为一个没改** ——
桌面用户怎么用还是怎么用；只有明确敲了子命令才走命令那条路。
"""

from __future__ import annotations

import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn

from timeflow.api.app import create_app
from timeflow.cli.main import CLI_WORDS
from timeflow.cli.main import main as cli_main
from timeflow.config import load_settings
from timeflow.core import lan as lan_mod
from timeflow.storage import backup as backup_mod
from timeflow.storage import db as db_mod


def main(argv: list[str] | None = None) -> None:
    args = [str(a) for a in (sys.argv[1:] if argv is None else argv)]
    # 只加不改：只有**明确**敲了子命令（或 --help/-h）才走 CLI，其余一律开窗口
    if args and (args[0] in CLI_WORDS or args[0] in ("-h", "--help")):
        raise SystemExit(cli_main(args))

    settings = load_settings()
    db_path = Path(settings.database.path)
    made = backup_mod.make_backup(db_path)
    if made is not None:
        print(f"[已备份] {db_path.name} -> {made.name}")

    port = 8520
    lan = bool(settings.net.allow_lan)
    app = create_app(str(db_path), allow_lan=lan, port=port)
    # 窗口自己永远走回环：绑 0.0.0.0 只是"也让局域网设备能连"，不是"让窗口去连局域网"
    host = "0.0.0.0" if lan else "127.0.0.1"
    if lan:
        conn = db_mod.connect(str(db_path))
        try:
            for line in lan_mod.banner(port, lan_mod.code(conn)):
                print(line)
        finally:
            conn.close()

    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}"
    try:
        import webview
    except Exception as exc:  # noqa: BLE001 —— 依赖问题要说清，不静默
        print(f"[退回浏览器] 打不开窗口：import webview 失败（{exc}）")
        webbrowser.open(url)
        thread.join()
        return
    try:
        webview.create_window("timeflow", url, width=1080, height=720)
        webview.start()
    except Exception as exc:  # noqa: BLE001 —— 缺 WebView2 运行时等
        print(f"[退回浏览器] 窗口起不来：{exc}")
        print(f"[提示] 仍然可以用浏览器打开 {url}")
        webbrowser.open(url)
        thread.join()


if __name__ == "__main__":
    main()
