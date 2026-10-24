"""技能根守卫：确认**默认预设**也看得见仓库旁边的软工技能根（卡 E19 / T-AG472）。

**为什么要有它**：2026-10-24 21:54 那次 `cordis.patch.yml` 被重写后，9 个软工技能
（8 个 `pipe-*` + `softeng-manage`）从会话里整体消失 —— 因为预设切换把
`skill-filesystem.customSkillDirs` 换成了另一个根。主控当时手工给默认预设追了一个根，
但没有任何机器判据守着它，下次谁再应用一次策略，同样的静默丢失会重演。

**只读，不自作主张改预设**：本模块只解析、只报告。改 profile 是人的事。

## 解析口径（不做 YAML 解析，按行读）

`cordis.patch.yml` 里有 `!!js` 标签，安全 YAML 载入会直接报错，所以按行扫：

- 一段以 `- id: skill-filesystem` 开头（缩进记下来，作为这一段的作用域）；
- 段内 `customSkillDirs:` 之后、缩进更深的 `- ` 行是一条根；不以 `- ` 开头的续行
  （`!!js` 表达式折行）接到上一条，**原样保留，不展开**；
- 段名取这一段之前最近的 `- id: preset-<x>`（没有就记 `<unknown>`）。

## 判据

- **默认预设** = `customSkillDirs` 里出现 `!!js` 的那一段；它必须包含 `--expect` 给的根
  （默认 `C:/Users/example/.dsh/skills-softeng`）。
- 其余预设声明了自己的根 —— **只报不判**（它们用别的技能根是合理的）。
- 文件不存在 / 解析不出任何 `skill-filesystem` 段 ⇒ 退 `2` 并打「判不了」——
  **不许当成绿**（判不出陈旧就报 skip，不报 pass）。

## 退出码

`0` 全绿 · `1` 默认预设缺根（逐条点名「哪一段 / 当前根 / 缺哪一个」）· `2` 判不了。
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

DEFAULT_EXPECT = "C:/Users/example/.dsh/skills-softeng"
DEFAULT_PROFILE = pathlib.Path(
    os.environ.get("USERPROFILE", os.environ.get("HOME", "~"))
) / ".dsh" / "profiles" / "desktop" / "cordis.patch.yml"


def _norm(path: str) -> str:
    """比路径用的规范化：反斜杠换正斜杠、去尾斜杠、小写（Windows 不认大小写）。"""
    return path.strip().replace("\\", "/").rstrip("/").lower()


class Segment:
    """一个 preset 里的 `skill-filesystem` 段。"""

    def __init__(self, preset: str, line_no: int) -> None:
        self.preset = preset
        self.line_no = line_no
        self.roots: list[str] = []

    @property
    def is_default(self) -> bool:
        """默认预设：`customSkillDirs` 里有 `!!js` 表达式。"""
        return any("!!js" in root for root in self.roots)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def parse_segments(text: str) -> list[Segment]:
    """按行切出所有 `skill-filesystem` 段。解析不出来就给空列表（调用方判 2）。"""
    lines = text.splitlines()
    segments: list[Segment] = []
    current: Segment | None = None
    seg_indent = 0
    in_dirs = False
    dirs_indent = -1
    preset = "<unknown>"
    for idx, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if stripped.startswith("- id: preset-"):
            preset = stripped.split("- id:", 1)[1].strip()
            continue
        if stripped.startswith("- id: skill-filesystem"):
            current = Segment(preset, idx)
            segments.append(current)
            seg_indent = _indent(raw)
            in_dirs = False
            continue
        if current is None:
            continue
        ind = _indent(raw)
        if ind <= seg_indent and stripped:
            # 段结束：退回到同级或更外层的新条目
            current = None
            in_dirs = False
            continue
        if stripped.startswith("customSkillDirs:"):
            in_dirs = True
            dirs_indent = ind
            continue
        if not in_dirs or not stripped:
            continue
        if stripped.startswith("- ") and ind > dirs_indent:
            current.roots.append(stripped[2:].strip())
        elif ind > dirs_indent and current.roots:
            # `!!js` 折行：接上一条，原样保留
            current.roots[-1] = current.roots[-1] + " " + stripped
        elif ind <= dirs_indent:
            in_dirs = False
    return segments


def check(profile: pathlib.Path, expect: str) -> tuple[int, list[str]]:
    """返回 (退出码, 要打印的行)。"""
    if not profile.exists():
        return 2, [f"[FAIL] 判不了：profile 补丁不存在 → {profile}"]

    try:
        text = profile.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:  # 判不了要明说，不许当成绿
        return 2, [f"[FAIL] 判不了：profile 读不出来（{exc}）→ {profile}"]

    segments = [seg for seg in parse_segments(text) if seg.roots]
    if not segments:
        return 2, [
            "[FAIL] 判不了：这份 profile 里找不到任何带 customSkillDirs 的 "
            f"skill-filesystem 段 → {profile}"
        ]

    out: list[str] = [f"[INFO] profile = {profile}"]
    defaults = [seg for seg in segments if seg.is_default]
    for seg in segments:
        kind = "默认预设" if seg.is_default else "其它预设"
        out.append(f"[INFO] {kind} {seg.preset}（第 {seg.line_no} 行）")
        for root in seg.roots:
            shown = root if len(root) <= 90 else root[:87] + "..."
            out.append(f"        - {shown}")

    if not defaults:
        return 1, out + [
            "[FAIL] 默认预设（customSkillDirs 里带 !!js 的那一段）没找到 —— "
            "判不了它有没有仓库技能根，按缺根处理"
        ]

    want = _norm(expect)
    missing = [seg for seg in defaults if not any(_norm(r) == want for r in seg.roots)]
    if missing:
        out.append(f"[FAIL] 默认预设缺仓库技能根：{expect}")
        for seg in missing:
            out.append(f"        - 段 {seg.preset}（第 {seg.line_no} 行）没包含它")
        return 1, out

    out.append(f"[OK ] 默认预设已含仓库技能根：{expect}")
    return 0, out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="技能根守卫（只读）")
    ap.add_argument("--check", action="store_true", help="核对并给退出码")
    ap.add_argument("--profile", default=str(DEFAULT_PROFILE), help="profile 补丁路径")
    ap.add_argument("--expect", default=DEFAULT_EXPECT, help="默认预设必须包含的技能根")
    args = ap.parse_args(argv)

    code, lines = check(pathlib.Path(args.profile), args.expect)
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
