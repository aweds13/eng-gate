"""按需从 git 历史导出「改前快照」，供人工并排 diff（不参与构建）。

为什么需要：前端重构（R1/R2）改的是同一个文件，`git log` 能回退，
但**眼睛需要一份能直接打开的旧文件**。
本脚本把指定提交里的文件按字节导出到 `snapshots/<标签>__<短提交>/`（该目录已 gitignore）。

用法：
    python -X utf8 tools/snapshot.py                      # 导出内置的两份前端对照快照
    python -X utf8 tools/snapshot.py add <rev> <标签> <路径> [更多路径...]
    python -X utf8 tools/snapshot.py list

注意：按字节写入，不碰编码与换行（避免快照与真实历史不一致而误导对比）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPS = ROOT / "snapshots"

# 内置对照点：(提交, 标签, 文件列表)
BUILTIN: list[tuple[str, str, list[str]]] = [
    ("52a3766", "frontend-before-R1", ["src/web/index.html"]),
    ("84e6837", "frontend-after-R1-before-R2", ["src/web/index.html", "src/web/app.css"]),
]


def export(rev: str, label: str, files: list[str]) -> None:
    out = SNAPS / f"{label}__{rev}"
    out.mkdir(parents=True, exist_ok=True)
    for f in files:
        blob = subprocess.run(
            ["git", "show", f"{rev}:{f}"], cwd=ROOT, capture_output=True, check=False
        )
        if blob.returncode != 0:
            print(f"  跳过（{rev} 无此文件）: {f}")
            continue
        (out / Path(f).name).write_bytes(blob.stdout)
        print(f"  {f} -> {out.name}/{Path(f).name}  ({len(blob.stdout)} bytes)")


def main(argv: list[str]) -> int:
    if argv and argv[0] == "list":
        if not SNAPS.exists():
            print("（还没有快照）")
            return 0
        for d in sorted(SNAPS.iterdir()):
            print(f"  {d.name}/  {[p.name for p in sorted(d.iterdir())]}")
        return 0

    if argv and argv[0] == "add":
        if len(argv) < 4:
            print("用法: add <rev> <标签> <路径> [更多路径...]", file=sys.stderr)
            return 2
        rev, label, *files = argv[1:]
        print(f"[导出] {rev} · {label}")
        export(rev, label, files)
        return 0

    print("[导出内置对照快照]")
    for rev, label, files in BUILTIN:
        export(rev, label, files)
    print(f"\n目录：{SNAPS}")
    print("对比方式：直接并排打开，或 `git diff 52a3766 -- src/web/index.html`")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
