"""TOML 语法预检（T-G52）—— 用 1 秒把「哪一份、哪一行、哪一列」说清楚。

## 为什么有它

`docs/traceability.toml` 是台账的唯一真源，而它的一个坑**已经在同一个会话里踩了 8 次**：
正文里写了 ASCII 双引号（TOML 基本串不允许）→ **整份文件解析不了** → `audit` 与
`audit_titles` 双双报红，而且报的是 `tomllib` 的原始错误（`Expected newline or end of
document after a statement (at line 1442, column 66)`）—— 我还得自己去数第 1442 行在哪、
第 66 列是什么，每次白花两三分钟。

它**不是门禁、不写任何产物**：只是把同一件已经会失败的事**提前并说人话**。
调用点：`run_gates.py` 在开跑之前先调一次（失败就直接停，别让两道门白跑一趟），
也可以单独跑：

    python -X utf8 scripts/check_toml.py
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent
_LOC = re.compile(r"at line (\d+), column (\d+)")
_HINT = (
    "常见原因：TOML 基本串里写了 ASCII 双引号 —— 中文正文用「」，"
    '或把引号写成 \\"（这条坑已踩 8 次，见 复盘/视觉线地图.md §6）'
)


def toml_files() -> list[Path]:
    """仓库里**会进版本库**的 TOML（`--others` 把新写的也算上，`--exclude-standard` 排掉忽略的）。

    为什么不直接 `rglob`：工作区里有一堆沙箱残留目录（`m_*` / `um*` / `.p_*`），
    递归进去只会读到别人的垃圾，还会让"预检通过（N 份）"里的 N 每次都不一样。
    """
    out = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files",
         "--cached", "--others", "--exclude-standard", "*.toml"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    ).stdout.split()
    return [ROOT / p for p in out]


def check_one(path: Path) -> list[str]:
    """解析一份 TOML；有问题就返回**给人看**的说明（空列表 = 这份没问题）。"""
    text = path.read_text(encoding="utf-8")
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        rel = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)
        m = _LOC.search(str(exc))
        if not m:
            return [f"{rel} 解析失败：{exc}"]
        line_no, col = int(m.group(1)), int(m.group(2))
        lines = text.splitlines()
        src = lines[line_no - 1] if 0 < line_no <= len(lines) else ""
        if len(src) > 160:
            src = src[:160] + "…"
        return [
            f"{rel} 解析失败：{exc}\n"
            f"   第 {line_no} 行：{src}\n"
            f"   第 {col} 列 ↑\n"
            f"   {_HINT}"
        ]
    return []


def check_all() -> list[str]:
    """仓库里所有 TOML 逐个解析，汇总成一段**给人看**的说明（空列表 = 全过）。"""
    problems: list[str] = []
    for path in toml_files():
        problems += check_one(path)
    return problems


def main() -> int:
    files = toml_files()
    problems = check_all()
    if problems:
        for p in problems:
            print(f"[FAIL] {p}")
        return 1
    print(f"[OK ] TOML 语法预检通过（{len(files)} 份）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
