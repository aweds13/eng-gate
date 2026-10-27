"""把仓库 `skills/` 里的技能挂进 CodeBuddy 工人的技能目录（`.codeartsdoer/skills/`）。

为什么需要它：号池工人跑的是 CodeBuddy CLI，它只认 `.codeartsdoer/skills/`；
而判据/操作知识的真源在本仓 `skills/`（`pipe-card` / `pipe-gate` / `pipe-land` …）。
`.codeartsdoer/` 在 `.gitignore:99` 里，所以这是**本机运行时登记**，不进 git。

用法：
    python -X utf8 tools/sync_worker_skills.py            # 挂上（幂等）
    python -X utf8 tools/sync_worker_skills.py --check    # 只报告，不动手
    python -X utf8 tools/sync_worker_skills.py --unlink   # 摘掉本脚本建的链接

判据：每个 `skills/<name>/SKILL.md` 都要在 `.codeartsdoer/skills/<name>/SKILL.md` 可见。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "skills"
DST = ROOT / ".codeartsdoer" / "skills"
# 同一套技能还要能被两类 DSH 会话看见：仓内 .dsh/skills（任意会话）与
# ~/.dsh/skills-softeng（软工预设的自定义根）。三处判据合并，避免「工人看得到、
# 软工会话看不到」这种漂移。
EXTRA_DSTS = [ROOT / ".dsh" / "skills", Path.home() / ".dsh" / "skills-softeng"]
ALL_DSTS = [DST, *EXTRA_DSTS]
MARK = ".linked-by-sync_worker_skills"


def skill_dirs() -> list[Path]:
    if not SRC.is_dir():
        return []
    return sorted(p for p in SRC.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())


def is_linked(path: Path) -> bool:
    if path.is_symlink():
        return True
    return (path / MARK).exists()


def link(src: Path, dst: Path) -> str:
    if os.name == "nt":
        r = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(dst), str(src)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if r.returncode != 0:
            raise OSError((r.stdout or "") + (r.stderr or ""))
        return "junction"
    os.symlink(src, dst, target_is_directory=True)
    return "symlink"


def status(dst: Path | None = None) -> list[tuple[str, bool]]:
    target = dst or DST
    return [(p.name, (target / p.name / "SKILL.md").is_file()) for p in skill_dirs()]


def missing_by_target() -> dict[str, list[str]]:
    """每个登记目录缺哪些技能（判据：目标里有没有 SKILL.md）。"""
    out: dict[str, list[str]] = {}
    for dst in ALL_DSTS:
        out[str(dst)] = [name for name, ok in status(dst) if not ok]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--check", action="store_true", help="只报告")
    ap.add_argument("--unlink", action="store_true", help="摘掉本脚本建的链接")
    a = ap.parse_args()

    if not SRC.is_dir():
        print(f"[FAIL] 没有 skills/ 目录：{SRC}")
        return 2

    dirs = skill_dirs()
    if not dirs:
        print(f"[FAIL] {SRC} 下没有含 SKILL.md 的技能目录")
        return 2

    if a.check:
        worst = 0
        for dst in ALL_DSTS:
            st = status(dst)
            bad = [n for n, ok in st if not ok]
            for n, ok in st:
                print(f"  {'[OK ]' if ok else '[MISS]'} {n}")
            print(f"[{'OK ' if not bad else 'FAIL'}] {len(st) - len(bad)}/{len(st)} 已登记到 {dst}")
            worst |= 1 if bad else 0
        return worst

    for dst in ALL_DSTS:
        dst.mkdir(parents=True, exist_ok=True)

    if a.unlink:
        n = 0
        for p in sorted(DST.iterdir()):
            if p.is_dir() and is_linked(p):
                if p.is_symlink():
                    p.unlink()
                else:
                    subprocess.run(
                        ["cmd", "/c", "rmdir", str(p)],
                        capture_output=True, text=True,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                n += 1
        print(f"[OK ] 摘掉 {n} 个链接")
        return 0

    made = 0
    for root in ALL_DSTS:
        for p in dirs:
            dst = root / p.name
            if dst.exists():
                continue
            try:
                kind = link(p, dst)
                where = dst.relative_to(ROOT.parent) if str(dst).startswith(str(ROOT)) else dst
                print(f"  [OK ] {where}（{kind}）")
                made += 1
            except OSError as e:
                print(f"  [FAIL] {dst}: {str(e).strip()[:120]}")
                print("         （没有 junction 权限：手工把 skills/<name> 复制到该目录）")
                return 1

    worst = 0
    for dst in ALL_DSTS:
        st = status(dst)
        bad = [n for n, ok in st if not ok]
        print(f"[{'OK ' if not bad else 'FAIL'}] {len(st) - len(bad)}/{len(st)} 可见：{dst}")
        worst |= 1 if bad else 0
    print(f"[OK ] 新挂 {made} 个")
    return worst


if __name__ == "__main__":
    sys.exit(main())
