#!/usr/bin/env python
"""钉子② —— 每个 SKILL.md 必须有 frontmatter（name + description）与必需小节（卡 180 §③）。
卡 209（T-G318）在本钉子上**只加**四条，原有判据一条不松。

原有判据（一条不动）：
  - skills/ 下一个 SKILL.md 都没有 ⇒ 红；
  - 缺 frontmatter（首行不是 `---`）；
  - frontmatter 缺 `name` 或 `description`（或为空）；
  - `name` 不是 kebab-case，或与所在目录名不一致；
  - 正文缺「什么时候用」「什么时候别用」「前置检查」「真命令」「怎么读结果」「常见错与处置」任一节。

卡 209 新增四条（口径写在这里，别处不许再解释一遍）：

A. 长度上限 —— SKILL.md ≤ MAX_LINES（120）行；超出 ⇒ 红，点名文件并报实际行数。

B. 流程数上限 —— 正文里「流程级」小节 ≤ MAX_FLOWS（3）；超出 ⇒ 红并点名超出的那条。
   ★「流程级」的口径（不许含糊）：
     · 只数**标题行**：行首 `## ` 或 `### `（二 / 三级标题）；**围栏代码块（``` / ~~~）里的
       `#` 注释不算**（先把围栏内的整段剔掉再数）；一级标题（`# `）是技能名，也不算。
     · 六个固定小节（什么时候用 / 什么时候别用 / 前置检查 / 真命令 / 怎么读结果 / 常见错与处置）
       是**骨架**，**不计入**流程数。
     · 其余每一个 `##` / `###` 标题 = 一条「流程」（一个独立的做法 / 子流程）。

C. ★★ 验收必须指向脚本 ——「怎么读结果」小节里**每条口径**必须指向一个**真实存在的脚本**。
   ★ 口径：
     · 条目 = 该小节里每个以 `- ` / `* ` 开头的列表项（空行断条，续行并入上一条）。
     · 条目里必须出现**反引号包裹**的一段文字，其中含一个**仓库相对路径**，且：
         ① 后缀是脚本（`.py` / `.mjs` / `.js` / `.sh`）；
         ② 落在允许的脚本根之一：`tools/` · `skills/`（含 `skills/**/scripts/**`）·
            `framework/cli/`（★ 本仓 pipe CLI 的真实所在，这五份 skill 的验收程序就是它）；
         ③ `REPO_ROOT / 路径` **真实存在**（假指针不算）。
     · ★ 允许的写法：`python -X utf8 tools/xxx.py --check` ·
       `python -X utf8 framework/cli/main.py gate --json`。
     · ★ 不许的写法：「看输出对不对」「退出码 0 就是过」—— 条目里没有任何脚本路径。
     · 指不出来 ⇒ 红并点名是哪一条。

D. 人类理解版 —— 每个技能目录下必须有 `NOTES.md`，且含三节（逐字）：
   「这一层在防哪类错误」/「失败过什么（带读数）」/「脚本接口与以后怎么改」。
   缺文件或缺节 ⇒ 红并点名。

只读：不改任何文件。
"""
from __future__ import annotations

import re
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILLS_ROOT.parent

KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REQUIRED_SECTIONS = [
    "什么时候用", "什么时候别用", "前置检查", "真命令", "怎么读结果", "常见错与处置",
]

# ===== 卡 209（T-G318）四条新判据的口径常数 =====
MAX_LINES = 120
MAX_FLOWS = 3
READ_SECTION = "怎么读结果"
NOTES_NAME = "NOTES.md"
NOTES_SECTIONS = ["这一层在防哪类错误", "失败过什么（带读数）", "脚本接口与以后怎么改"]

FLOW_HEADING = re.compile(r"^#{2,3}\s+\S")
FENCE_LINE = re.compile(r"^\s*(```|~~~)")
SECTION_HEADING = re.compile(r"^##\s+(.*\S)\s*$")
ITEM_LINE = re.compile(r"^\s*[-*]\s+")
CODE_SPAN = re.compile(r"`([^`]+)`")
SCRIPT_TOKEN = re.compile(r"[0-9A-Za-z_./\\-]+\.(?:py|mjs|js|sh)\b")
SCRIPT_SUFFIXES = (".py", ".mjs", ".js", ".sh")
SCRIPT_ROOTS = ("tools/", "skills/", "framework/cli/")


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


def strip_fences(text: str) -> str:
    """剔掉围栏代码块（``` / ~~~ 成对）—— 里面的 `#` 注释不是标题。"""
    kept: list[str] = []
    inside = False
    for line in text.splitlines():
        if FENCE_LINE.match(line):
            inside = not inside
            continue
        if not inside:
            kept.append(line)
    return "\n".join(kept)


def section_text(body: str, title: str) -> str | None:
    """取 `## <title>` 小节的正文（到下一个二级标题为止，不含标题行）。没这一节 ⇒ None。"""
    lines = body.splitlines()
    start = None
    for i, line in enumerate(lines):
        m = SECTION_HEADING.match(line)
        if m and m.group(1).strip() == title:
            start = i + 1
            break
    if start is None:
        return None
    out: list[str] = []
    for line in lines[start:]:
        if SECTION_HEADING.match(line):
            break
        out.append(line)
    return "\n".join(out)


def flow_titles(body: str) -> list[str]:
    """正文里「流程级」小节标题（口径见模块 docstring B）—— 六个固定小节不算。"""
    titles: list[str] = []
    for line in strip_fences(body).splitlines():
        if not FLOW_HEADING.match(line):
            continue
        title = line.split(None, 1)[1].strip()
        if title in REQUIRED_SECTIONS:
            continue
        titles.append(title)
    return titles


def result_items(section: str) -> list[str]:
    """把「怎么读结果」小节切成一条条口径（`- ` / `* ` 开头；空行断条，续行并入）。"""
    items: list[str] = []
    cur: str | None = None
    for raw in section.splitlines():
        if ITEM_LINE.match(raw):
            if cur is not None:
                items.append(cur)
            cur = raw.strip()
        elif cur is not None and raw.strip():
            cur += " " + raw.strip()
        elif not raw.strip() and cur is not None:
            items.append(cur)
            cur = None
    if cur is not None:
        items.append(cur)
    return items


def points_to_real_script(item: str) -> bool:
    """这一条口径里有没有一个「真实存在的脚本路径」（口径见模块 docstring C）。"""
    for span in CODE_SPAN.findall(item):
        for token in SCRIPT_TOKEN.findall(span):
            path = token.replace("\\", "/")
            while path.startswith("./"):
                path = path[2:]
            if not path.endswith(SCRIPT_SUFFIXES):
                continue
            if not path.startswith(SCRIPT_ROOTS):
                continue
            if (REPO_ROOT / path).is_file():
                return True
    return False


def _clip(text: str, width: int = 48) -> str:
    """把一条口径压成一行短摘要（红行里点名用）。"""
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[:width] + "…"


def skill_problems(path: Path) -> list[str]:
    """一个 SKILL.md 的全部问题（原有 + 卡 209 四条）。"""
    rel = path.relative_to(REPO_ROOT).as_posix()
    text = path.read_text(encoding="utf-8")
    problems: list[str] = []

    fm, body = parse_frontmatter(text)
    if fm is None:
        problems.append(f"{rel}: 缺 frontmatter（首行必须是 ---）")
    else:
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

    # —— 卡 209 §1.1 长度上限 ——
    n_lines = len(text.splitlines())
    if n_lines > MAX_LINES:
        problems.append(f"{rel}: SKILL.md 太长（{n_lines} 行 > 上限 {MAX_LINES} 行）")

    # —— 卡 209 §1.2 流程数上限 ——
    flows = flow_titles(body)
    if len(flows) > MAX_FLOWS:
        extra = "、".join(flows[MAX_FLOWS:])
        problems.append(f"{rel}: 流程级小节 {len(flows)} 条 > 上限 {MAX_FLOWS}（超出：{extra}）")

    # —— 卡 209 §1.3 「怎么读结果」每条口径必须指向真脚本 ——
    result = section_text(body, READ_SECTION)
    if result is not None:
        for item in result_items(result):
            if not points_to_real_script(item):
                problems.append(f"{rel}: 「{READ_SECTION}」有一条口径没指向真脚本：{_clip(item)}")

    # —— 卡 209 §1.4 人类理解版 NOTES.md ——
    notes = path.parent / NOTES_NAME
    if not notes.is_file():
        problems.append(f"{rel}: 目录下缺 {NOTES_NAME}（人类理解版）")
    else:
        notes_rel = notes.relative_to(REPO_ROOT).as_posix()
        notes_text = notes.read_text(encoding="utf-8")
        for section in NOTES_SECTIONS:
            if section not in notes_text:
                problems.append(f"{notes_rel}: 缺小节「{section}」")
    return problems


def main() -> int:
    skill_files = sorted(SKILLS_ROOT.rglob("SKILL.md"))
    if not skill_files:
        print("钉子② 红：skills/ 下一个 SKILL.md 都没有")
        return 1

    problems: list[str] = []
    for path in skill_files:
        problems.extend(skill_problems(path))

    if problems:
        print("钉子② 红：SKILL.md 格式不合规")
        for p in problems:
            print("  -", p)
        return 1
    print(
        f"钉子② 绿：{len(skill_files)} 个 SKILL.md 都有 frontmatter（name + description）"
        f"与必需小节，且过卡 209 四条（≤{MAX_LINES} 行 / 流程 ≤{MAX_FLOWS} / "
        f"「{READ_SECTION}」指向真脚本 / 有 {NOTES_NAME} 三节）"
    )
    for path in skill_files:
        print("  -", path.relative_to(REPO_ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
