"""计划任务跑的脚本：查一次"该提醒了"，弹系统通知，然后立刻退出。

由 `core/remind.py` 注册的 Windows 计划任务每分钟调用一次（`pythonw` 启动 → 不闪控制台窗口）。
也可以手动跑（排查用）：

```powershell
python -X utf8 src/timeflow/app/remind.py --check          # 只看状态，不弹通知
python -X utf8 src/timeflow/app/remind.py --now 2026-09-20T08:30   # 指定"现在"（演示/测试）
python -X utf8 src/timeflow/app/remind.py --test           # 弹一条测试通知
```

**为什么要单独一个可执行入口**：计划任务的命令行不能依赖当前工作目录/PYTHONPATH，
所以这里自己把 `src/` 加进 `sys.path`，并且用绝对路径打开数据库（`--db`，缺省读 config.toml）。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

# 计划任务的工作目录不是项目根：自己把 src/ 放进 sys.path，保证 import timeflow 一定成功
_SRC = Path(__file__).resolve().parents[2]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from timeflow.core import remind as remind_mod  # noqa: E402 —— 必须在上面那段 sys.path 之后
from timeflow.storage import db as db_mod  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="timeflow 到点提醒（计划任务调它）")
    ap.add_argument("--db", default=None, help="数据库路径（缺省读 config.toml）")
    ap.add_argument("--now", default=None, help="把'现在'当成这个本地时间（演示/排查用）")
    ap.add_argument("--check", action="store_true", help="只打印状态，不弹通知")
    ap.add_argument("--test", action="store_true", help="弹一条测试通知")
    args = ap.parse_args(argv)

    conn = db_mod.connect(args.db or remind_mod._default_db_path())
    try:
        if args.check:
            st = remind_mod.status(conn)
            for k, v in st.items():
                print(f"{k}: {v}")
            return 0
        if args.test:
            style = remind_mod.get_style(conn)
            ok, detail = remind_mod.show_notification(
                "timeflow 提醒测试", "看到这条就说明系统通知能用。", style
            )
            print(("OK " if ok else "FAIL ") + detail)
            return 0 if ok else 1
        moment = datetime.fromisoformat(args.now) if args.now else None
        results = remind_mod.notify_due(conn, moment)
        for r in results:
            print(("OK " if r["sent"] else "FAIL ") + f"{r['title']} · {r['detail']}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
