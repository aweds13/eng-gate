#!/usr/bin/env python
"""钉子① —— skills 里引用的每个命令名，都能在框架 CLI 里找到（卡 180 §③）。

判据（机器可判）：
  - 扫 skills/**/SKILL.md 里的 `pipe <命令>` 引用（只从**代码段 / 围栏代码块 / 标题**里取，
    避免散文里的英文词被误当命令）；
  - 与 CLI 的 `--help`（含各子命令的 `--help`）对账；
  - 引用了 CLI 里不存在的命令（或组下不存在的子命令）⇒ 红（退出码 1）。

只读：不改任何文件。
CLI 解析顺序：优先本仓 `framework/cli/main.py`（确定性），否则 PATH 上的 `pipe`。
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parents[1]        # skills/
REPO_ROOT = SKILLS_ROOT.parent                            # 仓库根
FRAMEWORK_CLI = REPO_ROOT / "framework" / "cli" / "main.py"

FENCE_RE = re.compile(r"^\s*```")
SPAN_RE = re.compile(r"`([^`]*)`")
REF_RE = re.compile(r"\bpipe\s+([a-z][a-z0-9-]*)(?:\s+([a-z][a-z0-9-]*))?")
POSITIONAL_RE = re.compile(r"^ {4}([a-z][a-z0-9-]*)\b")


def _cli_argv() -> list[str]:
    """返回调用 CLI 的 argv 前缀。"""
    if FRAMEWORK_CLI.is_file():
        return [sys.executable, str(FRAMEWORK_CLI)]
    on_path = shutil.which("pipe")
    if on_path:
        return [on_path]
    raise SystemExit("找不到 CLI：既没有 framework/cli/main.py，也没有 PATH 上的 pipe")


def _run_help(argv: list[str]) -> str:
    proc = subprocess.run(argv + ["--help"], capture_output=True, text=True, encoding="utf-8")
    return (proc.stdout or "") + (proc.stderr or "")


def _positional_tokens(help_text: str) -> list[str]:
    tokens = []
    for line in help_text.splitlines():
        m = POSITIONAL_RE.match(line)
        if m:
            tokens.append(m.group(1))
    return tokens


def discover_commands(base: list[str]) -> tuple[set[str], dict[str, set[str]]]:
    """返回 (顶层命令集, {组: 子命令集})。"""
    top = _positional_tokens(_run_help(base))
    groups: dict[str, set[str]] = {}
    for token in top:
        children = _positional_tokens(_run_help(base + [token]))
        if children:
            groups[token] = set(children)
    return set(top), groups


def command_refs(text: str):
    """产出 (行号, 第一个词, 第二个词或 None)；只从代码段 / 围栏 / 标题里取。"""
    refs = []
    in_fence = False
    for i, line in enumerate(text.splitlines(), start=1):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        segments: list[str] = []
        if in_fence:
            segments.append(line)
        else:
            segments.extend(SPAN_RE.findall(line))
            if line.lstrip().startswith("#"):
                segments.append(line)
        for seg in segments:
            for m in REF_RE.finditer(seg):
                refs.append((i, m.group(1), m.group(2)))
    return refs


def main() -> int:
    base = _cli_argv()
    top, groups = discover_commands(base)
    problems: list[str] = []
    skill_files = sorted(SKILLS_ROOT.rglob("SKILL.md"))
    for path in skill_files:
        rel = path.relative_to(REPO_ROOT).as_posix()
        for line_no, first, second in command_refs(path.read_text(encoding="utf-8")):
            if first not in top:
                problems.append(
                    f"{rel}:{line_no} 引用了不存在的命令 `pipe {first}`"
                    f"（合法顶层命令：{' '.join(sorted(top))}）"
                )
            elif first in groups and second is not None and second not in groups[first]:
                problems.append(
                    f"{rel}:{line_no} 引用了不存在的子命令 `pipe {first} {second}`"
                    f"（合法：{' '.join(sorted(groups[first]))}）"
                )

    if problems:
        print("钉子① 红：skills 引用了 CLI 里不存在的命令")
        for p in problems:
            print("  -", p)
        return 1
    print(f"钉子① 绿：{len(skill_files)} 个 SKILL.md 的命令引用全部在 CLI 帮助里找到")
    print(f"  合法顶层命令：{' '.join(sorted(top))}")
    for g, cs in sorted(groups.items()):
        print(f"  组 {g}：{' '.join(sorted(cs))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
