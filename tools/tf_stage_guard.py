"""提交前的**白名单越界校验** —— 防「顺手改了别的东西、还一起提交进去」。

背景（卡 095 · 机器替代②）：以前每次提交前手写一段 python 比对
`git diff --cached --name-only` 与允许列表 —— 纯机械判据，交给机器。

判据：
  · 取 `git -c core.quotepath=false diff --cached --name-only`（**仓库相对路径原样**）；
  · 任何**不在**允许列表里的路径 → 打印越界项，退 **2**；
  · 全部在允许列表里 → 打印「staged N 个文件全在白名单」，退 **0**；
  · ★ **暂存区为空 → 退 3**：空集永远满足「全在白名单」，那是**假绿灯**，不许当通过。

★ 为什么钉死 `core.quotepath=false`：git 默认把非 ASCII 路径做**八进制转义**
（`复盘/卡.md` → `\345\244\215...`），拿它去和白名单里的中文路径比会**永远不匹配**——
这个坑本仓踩过，所以路径一律按仓库相对路径原样比。

用法：
    python -X utf8 tools/tf_stage_guard.py --allow tools/a.py docs/b.md
    python -X utf8 tools/tf_stage_guard.py --allow-file 白名单.txt
    # 允许列表支持 glob（fnmatch，如 `tools/*.py`）；清单文件：每行一个路径，`#` 开头是注释。
"""
from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def staged_paths(root: Path = ROOT) -> list[str]:
    """暂存区里的仓库相对路径（原样，不做八进制转义）。"""
    proc = subprocess.run(
        ["git", "-c", "core.quotepath=false", "diff", "--cached", "--name-only"],
        cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git diff --cached 失败")
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


def outside_allow(staged: list[str], allow: list[str]) -> list[str]:
    """暂存区里**不在**允许列表（fnmatch）里的路径 —— 越界项，顺序保持原样。"""
    allow = [a.replace("\\", "/") for a in allow]
    out: list[str] = []
    for path in staged:
        rel = path.replace("\\", "/")
        if not any(fnmatch.fnmatch(rel, pat) for pat in allow):
            out.append(path)
    return out


def load_allow_file(path: str) -> list[str]:
    """清单文件：每行一个路径；跳过空行与 `#` 注释行。"""
    text = Path(path).read_text(encoding="utf-8")
    return [ln.strip() for ln in text.splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="提交前白名单越界校验：暂存区里混进白名单外的路径就拒提交")
    parser.add_argument("--allow", nargs="*", default=None, metavar="PATH",
                        help="允许的路径（可给多个；支持 glob）")
    parser.add_argument("--allow-file", default=None, metavar="FILE",
                        help="每行一个路径的清单文件（`#` 开头为注释）")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    allow = list(args.allow or [])
    if args.allow_file:
        if not Path(args.allow_file).exists():
            print(f"[FAIL] 白名单清单文件不存在：{args.allow_file}", file=sys.stderr)
            return 2
        allow += load_allow_file(args.allow_file)

    try:
        staged = staged_paths(ROOT)
    except RuntimeError as exc:
        print(f"[FAIL] 读暂存区失败：{exc}", file=sys.stderr)
        return 2

    if not staged:
        print("暂存区为空 —— 没有可提交的东西；"
              "空集永远满足「全在白名单」，那是假绿灯，不算通过（退 3）", flush=True)
        return 3

    outside = outside_allow(staged, allow)
    if outside:
        print(f"越界：暂存区里有 {len(outside)} 个路径不在白名单里（拒提交）：", flush=True)
        for path in outside:
            print(f"    {path}", flush=True)
        return 2

    print(f"staged {len(staged)} 个文件全在白名单", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
