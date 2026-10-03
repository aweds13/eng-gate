#!/usr/bin/env python
"""钉子② —— 每个 SKILL.md 必须有 frontmatter（name + description）与必需小节（卡 180 §③）。

红（退出码 1）的情形：
  - skills/ 下一个 SKILL.md 都没有；
  - 缺 frontmatter（首行不是 `---`）；
  - frontmatter 缺 `name` 或 `description`（或为空）；
  - `name` 不是 kebab-case，或与所在目录名不一致；
  - 正文缺「什么时候用」「什么时候别用」「前置检查」「真命令」「怎么读结果」「常见错与处置」任一节。

只读：不改任何文件。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILLS_ROOT.parent

KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REQUIRED_SECTIONS = ["什么时候用", "什么时候别用", "前置检查", "真命令", "怎么读结果", "常见错与处置"]


def parse_frontmatter(text: str):
    """返回 (frontmatter dict 或 None, 正文)。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            fm = {}
            for raw in lines[1:i]:
                if ":" in raw and not raw.lstrip().startswith("#"):
                    key, _, value = raw.partition(":")
                    fm[key.strip()] = value.strip()
            return fm, "\n".join(lines[i + 1:])
    return None, text


def main() -> int:
    skill_files = sorted(SKILLS_ROOT.rglob("SKILL.md"))
    problems: list[str] = []
    if not skill_files:
        print("钉子② 红：skills/ 下一个 SKILL.md 都没有")
        return 1

    for path in skill_files:
        rel = path.relative_to(REPO_ROOT).as_posix()
        fm, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        if fm is None:
            problems.append(f"{rel}: 缺 frontmatter（首行必须是 ---）")
            continue
        name = fm.get("name", "")
        desc = fm.get("description", "")
        if not name:
            problems.append(f"{rel}: frontmatter 缺 name")
        if not desc:
            problems.append(f"{rel}: frontmatter 缺 description")
        if name and not KEBAB.match(name):
            problems.append(f"{rel}: name `{name}` 不是 kebab-case")
        if name and name != path.parent.name:
            problems.append(f"{rel}: name `{name}` 与目录名 `{path.parent.name}` 不一致")
        for section in REQUIRED_SECTIONS:
            if section not in body:
                problems.append(f"{rel}: 正文缺「{section}」")

    if problems:
        print("钉子② 红：SKILL.md 格式不合规")
        for p in problems:
            print("  -", p)
        return 1
    print(f"钉子② 绿：{len(skill_files)} 个 SKILL.md 都有 frontmatter（name + description）与必需小节")
    for path in skill_files:
        print("  -", path.relative_to(REPO_ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
