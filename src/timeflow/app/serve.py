"""无窗口入口 `timeflow-web`：只起本地服务、不开桌面窗口（不需要 pywebview）。

对应轨外 089（A 档，用户拍板）：`pywebview` 从硬依赖挪进 `optional-dependencies[pc]`，
于是"只想在浏览器 / 手机上用"的人不必为了用这个工具先装一个桌面壳。想开窗口仍走
`timeflow`（`timeflow.app.main`）；这里给它一个**不碰窗口**的孪生入口。

口径**与 `timeflow.app.main` 一致**（就三件，照着做，别自创）：

1. **起服务前先备份**：与 `main.py` / `tools/serve.py` 共用 `timeflow.storage.backup.make_backup`
   （升级代码后首次连接会跑 schema 迁移，迁移前留一份才叫保险）。
2. **认 `[net] allow_lan`**：开了就绑 `0.0.0.0`（同一 WiFi 下的手机能连），并打印
   `timeflow.core.lan.banner(...)` 的地址与配对码；**默认关**（口径同 N16「默认收严、再放宽」）。
3. **打印人话的访问地址**。

★ 与 `main.py` 的区别**只有一处**：这里**不开窗口** —— 不引入 `webview`、不建窗口、
  也不去打开系统浏览器。它是给"浏览器 / 手机用"那条路准备的，所以干净地不起 GUI。
★ 这里**不是** `tools/serve.py` 的复制品：那个是开发用脚本（有 `--fresh` / `--window` /
  `--today` 等）；本模块是产品入口，只保留上面三条口径。

端口与 `main.py` 一致（8520）；另接受一个可选 `--port`（不打就 8520），方便端口被占时换一个。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

from timeflow.api.app import create_app
from timeflow.config import load_settings
from timeflow.core import lan as lan_mod
from timeflow.storage import backup as backup_mod
from timeflow.storage import db as db_mod

DEFAULT_PORT = 8520


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="timeflow-web",
        description="只起本地服务、不开桌面窗口（不需要 pywebview）",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="监听端口（默认 8520）")
    args = parser.parse_args([str(a) for a in (sys.argv[1:] if argv is None else argv)])

    settings = load_settings()
    db_path = Path(settings.database.path)
    # ① 起服务前先备份（与 main.py / tools/serve.py 同一套口径）
    made = backup_mod.make_backup(db_path)
    if made is not None:
        print(f"[已备份] {db_path.name} -> {made.name}")

    port = args.port
    lan = bool(settings.net.allow_lan)
    app = create_app(str(db_path), allow_lan=lan, port=port)
    host = "0.0.0.0" if lan else "127.0.0.1"

    # ③ 人话的访问地址（本机永远从回环打开；绑 0.0.0.0 只是"也让局域网设备能连"）
    url = f"http://127.0.0.1:{port}"
    print(f"[启动] {url}  （库：{db_path}）")

    # ② 局域网：**默认关**；开了就打地址与配对码（说什么、怎么说在 core/lan.banner 一处）
    if lan:
        conn = db_mod.connect(str(db_path))
        try:
            for line in lan_mod.banner(port, lan_mod.code(conn)):
                print(line)
        finally:
            conn.close()
    else:
        print("[提示] Ctrl+C 停止；数据全在本机，不出网"
              "（手机连不上；要连就改 config.toml 的 [net] allow_lan 后重启）")

    # 无窗口：服务直接在主线程里跑（没有窗口要兼顾，不必起后台线程）
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
