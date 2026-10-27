#!/usr/bin/env python
r"""check_mapping —— 核对动作映射表里的命令与产物是否还真实存在（纯只读）。

## 为什么有它

`skills/softeng-manage/references/mapping.md` 把「一句话 → 动作 → 真命令 → 判据」形式化。
表一旦过期（脚本改名、技能改名），agent 照着敲就会错，而且错得很自信。
本工具把「表」和「仓」对齐：表里每条命令的脚本、每个产物路径的父目录、每个技能名，
都必须在这棵树里找得到。

## 判据（红 = 退 1）

- §B 表里反引号内的 `.py` 路径必须存在（含 `<占位符>` 的行跳过）。
- `.md` 路径必须存在。
- `skills/<名>` 形式的技能必须存在。
- 不检查 `git` / `npx` / `ls` 这类系统命令（它们不在仓里）。

用法：

    python -X utf8 tools/check_mapping.py            # 人读
    python -X utf8 tools/check_mapping.py --json     # 机读
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / "skills" / "softeng-manage" / "references" / "mapping.md"

TICKED = re.compile(r"`([^`\n]+)`")
SKILL_REF = re.compile(r"skills/([a-z0-9][a-z0-9-]*)")


def _section_b_lines(text: str) -> list[str]:
    """只取 §B 的表行：从 '## B.' 到下一个 '## ' 之间、以 '|' 开头的行。"""
    lines: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("## B."):
            inside = True
            continue
        if inside and line.startswith("## "):
            break
        if inside and line.lstrip().startswith("|"):
            lines.append(line)
    return lines


def check(root: Path = ROOT) -> tuple[list[str], int]:
    """返回（问题列表, 核对的引用条数）。"""
    mapping = root / MAPPING.relative_to(ROOT)
    if not mapping.exists():
        return [f"映射表不存在：{mapping.relative_to(root)}"], 0
    problems: list[str] = []
    checked = 0
    rows = _section_b_lines(mapping.read_text(encoding="utf-8"))
    for line in rows:
        for token in TICKED.findall(line):
            for ref in token.split():
                if any(ch in ref for ch in "<>{}"):  # 占位符本身不核对
                    continue
                if ref.endswith((".py", ".md")):
                    checked += 1
                    if not (root / ref).exists():
                        problems.append(f"找不到：{ref}")
            for name in SKILL_REF.findall(token):
                if name.startswith("softeng-manage") or name.endswith(".md"):
                    continue
                checked += 1
                if not (root / "skills" / name).is_dir():
                    problems.append(f"技能不存在：skills/{name}")
    return problems, checked


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="核对动作映射表与仓库的一致性")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args(argv)
    problems, checked = check()
    if args.json:
        print(json.dumps({"ok": not problems, "checked": checked,
                          "problems": problems}, ensure_ascii=False))
    else:
        for p in problems:
            print(f"  [FAIL] {p}")
        state = "OK " if not problems else "FAIL"
        print(f"  [{state}] 映射表核对 {checked} 条引用，断 {len(problems)} 条")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
