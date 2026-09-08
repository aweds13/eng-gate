"""备份脚本：把本地数据 + 配置备份到 backups/（带时间戳）。

用法：python scripts/backup.py
规则：数据「不出本地/不上云」，备份目录 backups/ 仅在本地（已 gitignore）。
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CONFIG = ROOT / "config.toml"


def main() -> int:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = ROOT / "backups" / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    if DATA_DIR.exists():
        for db in DATA_DIR.glob("*.db*"):
            dest = backup_dir / db.name
            shutil.copy2(db, dest)
            copied += 1
    if CONFIG.exists():
        shutil.copy2(CONFIG, backup_dir / "config.toml")
        copied += 1

    print(f"[backup] 备份完成: {backup_dir}（{copied} 个文件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
