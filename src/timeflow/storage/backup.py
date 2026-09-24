"""数据库备份与恢复（SR-NF12 / SR-F9.3「重要数据可备份、可回滚」）。

口径（2026-09-21 用户定：设置页列出最近几个备份、点一下恢复）：

- **什么时候自动备份**：起服务前（`tools/serve.py`）与开窗口前（`app/main.py`）各一次。
  为什么放在"启动前"：升级代码后首次连接会跑 schema 迁移，**迁移前**留一份才叫保险。
- **恢复怎么做的**：用 SQLite 的**在线备份 API**（`Connection.backup`）把选中备份的**内容**
  写回当前库，**不替换文件** —— 在 Windows 上替换一个正被连接打开的文件会失败，
  而且就算换成功，已经打开的连接页缓存还是旧的（会出现"恢复了但界面没变"这种鬼故事）。
- **恢复是"可逆"的**：恢复前**先再备份一次现库**，所以选错了还能回去（这一点必须写进界面）。
- **老备份的 schema**：恢复后就地跑一遍 `db._migrate`，升到当前版本；
  如果备份比当前程序**更新**（降级场景），不改它、但在返回值里**如实报告**版本差。

`app_settings` 那张 key/value 表也在库里，所以回复一份备份会连设置一起回到那个时间点 ——
这是"回到过去"的本意，但界面要说清（否则用户会以为只有任务被回滚）。
"""

from __future__ import annotations

import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from timeflow import clock
from timeflow.storage import db as db_mod

SUFFIX = ".bak-"
_STAMP = "%Y%m%d-%H%M%S"


def backup_name(db_path: Path | str, when: datetime | None = None) -> str:
    """备份文件名：`<库名>.bak-<YYYYmmdd-HHMMSS>`（与 `tools/serve.py` 一直以来的写法一致）。"""
    path = Path(db_path)
    stamp = (when or clock.now()).strftime(_STAMP)
    return f"{path.name}{SUFFIX}{stamp}"


def make_backup(db_path: Path | str) -> Path | None:
    """备份现库；库不存在则跳过（首次运行会新建）。返回备份路径。"""
    path = Path(db_path)
    if not path.exists():
        return None
    target = path.with_name(backup_name(path))
    # 同一秒内连按两次：换个后缀，别互相覆盖（宁可多一份，也不要静默丢一份）
    n = 2
    while target.exists():
        target = path.with_name(f"{backup_name(path)}-{n}")
        n += 1
    shutil.copy2(path, target)
    return target


def list_backups(db_path: Path | str) -> list[dict[str, object]]:
    """同目录下的备份，**按时间倒序**（最新在前）。`at` 优先取文件名里的时间戳。"""
    path = Path(db_path)
    if not path.parent.exists():
        return []
    out: list[dict[str, object]] = []
    for item in path.parent.glob(f"{path.name}{SUFFIX}*"):
        if not item.is_file():
            continue
        tail = item.name[len(path.name) + len(SUFFIX):]   # 形如 "20260921-163000"（或改过的名）
        at, parsed = "", False
        m = re.match(r"^(\d{8})-(\d{6})", tail)
        if m:
            try:
                at = datetime.strptime(f"{m.group(1)}-{m.group(2)}", _STAMP).isoformat(
                    timespec="seconds"
                )
                parsed = True
            except ValueError:
                at = ""
        stat = item.stat()
        out.append({
            "name": item.name,
            "size": stat.st_size,
            "at": at or datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            # 手动改过名的也照样列出来，但标一下 —— 不静默当成正常备份
            "parsed": parsed,
        })
    out.sort(key=lambda d: str(d["at"]), reverse=True)
    return out


def resolve_backup(db_path: Path | str, name: str) -> Path:
    """校验备份名并解析成路径。

    只允许**同目录下的文件名**（不许带路径、不许 `..`）—— 这是个会覆盖真实数据的接口，
    名字校验是这一层唯一的安全边界。
    """
    path = Path(db_path)
    raw = str(name or "").strip()
    if not raw or "/" in raw or "\\" in raw or raw in {".", ".."} or Path(raw).name != raw:
        raise ValueError("备份名不合法（只能是文件名）")
    candidate = (path.parent / raw).resolve()
    if candidate.parent != path.parent.resolve():
        raise ValueError("备份必须与数据库在同一个目录")
    if not candidate.name.startswith(path.name + SUFFIX):
        raise ValueError(f"不是本库的备份（应为 {path.name}{SUFFIX}<时间戳>）")
    if not candidate.is_file():
        raise ValueError(f"找不到这个备份：{raw}")
    return candidate


def restore(db_path: Path | str, name: str, conn: object) -> dict[str, object]:
    """把某个备份的内容写回当前库。**恢复前先再备份一次现库**（可逆）。"""
    path = Path(db_path)
    source = resolve_backup(path, name)
    safety = make_backup(path)                      # ① 先留退路
    dest = db_mod.raw_conn(conn)                    # ② 拿真连接（代理不行）
    before = _schema_version(dest)
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        src.backup(dest)                            # ③ 在线备份：整库内容覆盖
    finally:
        src.close()
    db_mod.migrate(dest)                            # ④ 老备份就地升到当前 schema
    after = _schema_version(dest)
    return {
        "restored": source.name,
        "safety_backup": safety.name if safety else None,
        "schema_before": before,
        "schema_after": after,
        "schema_now": db_mod.SCHEMA_VERSION,
        # 降级场景如实报出来（恢复了一个"未来版本"的库，字段可能读不出来）
        "newer_than_app": after > db_mod.SCHEMA_VERSION,
    }


def _schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    except sqlite3.Error:
        return 0
    return int(row[0]) if row else 0
