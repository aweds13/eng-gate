#!/usr/bin/env python
r"""dsh_skills_link —— 把技能目录挂成 `.dsh/skills/<名>` 的 junction（卡 206 · T-G314）。

## 为什么有它

用户 2026-10-13：*「我大概都是在你 DSH 这里工作，所以尽量不要让我切来切去」*。
DSH 的技能扫描根里 **rank 100 = `<项目>/.dsh/skills`**（项目级）—— 放在那儿，**一进这个项目
技能就在**（不用记、不用切、不用 `/点名`）。本仓的 `skills/` 是框架的人机接口，DSH 认的
`SKILL.md` 格式与它几乎一致 ⇒ **一份真源、两个 harness 都读**。

做法：给 `skills/` 下**每个技能目录**（含 `SKILL.md` 的子目录）在 `.dsh/skills/<名>` 建一个
**目录 junction**（Windows 目录联接），指向 `../../skills/<名>` —— **零副本、单向**（真源仍在
`skills/`，入库、被钉子扫）。junction 是**本机派生物**，`.dsh/` 已进 `.gitignore`。

## ★ 只挂技能目录

`skills/` 下还有 `README.md` / `GLUE-harness.md` / `nails/` —— **一个都不许挂**。理由：DSH 的技能
扫描**还认平铺形态** `<root>/<名>.md`，把整份 `skills/` 挂进去，那两个 `.md` 会被当成没有
frontmatter 的**坏技能**；`nails/` 不是技能（没有 `SKILL.md`）。
⇒ 判据：**只挂含 `SKILL.md` 的子目录**，且 `.dsh/skills` 下**只能**是这套技能。

## 用法

    python -X utf8 tools/dsh_skills_link.py            # 建：缺的补、对的跳过；有冲突就停
    python -X utf8 tools/dsh_skills_link.py --check    # 只核对（红 = 退 1，点名哪一个）
    python -X utf8 tools/dsh_skills_link.py --list     # 打印「技能名 → 目标」，人读
    python -X utf8 tools/dsh_skills_link.py --root <项目根>   # 换根（测试 / 别的仓）

退出码：`0` 绿；`1` 有冲突 / 核对不过；`2` 用法或环境错误（非 Windows / mklink 失败）。

★ **幂等**：跑两次结果一样。已存在且**指向正确** ⇒ 跳过（打印一句）；已存在但**指向错**
（或不是 junction）⇒ **报错并停下**，**不静默重建**（那会把「有人手工改过」这件事抹掉）。
"""

from __future__ import annotations

import argparse
import os
import stat
import subprocess
import sys
from pathlib import Path

# `python -P -X utf8 tools/dsh_skills_link.py`（-P 不把脚本目录放进 sys.path）也要能 import pool：
_TOOLS_DIR = str(Path(__file__).resolve().parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from pool.no_window import NO_WINDOW  # noqa: E402  ★ 卡 148：子进程一律不弹窗（唯一真源）

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIRNAME = "skills"
LINK_RELDIR = Path(".dsh") / "skills"
SKILL_ENTRY = "SKILL.md"
#: junction 的重分析点标签（`stat` 在非 Windows 上没有这个名字 ⇒ 兜底写字面值）。
MOUNT_POINT_TAG = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)
#: `os.readlink` 在 Windows 上给出的设备前缀（比较前剥掉）。
_DEVICE_PREFIXES = ("\\\\?\\", "\\??\\")


class LinkError(Exception):
    """建 junction 失败（mklink 非零 / 环境不支持）。"""


def skills_root(root: Path) -> Path:
    """技能真源目录：`<root>/skills`。"""
    return root / SKILLS_DIRNAME


def link_root(root: Path) -> Path:
    """junction 落点目录：`<root>/.dsh/skills`。"""
    return root / LINK_RELDIR


def skill_names(skills_dir: Path) -> list[str]:
    """`skills/` 下**含 SKILL.md 的子目录**名（排序）—— 只有这些是技能。"""
    if not skills_dir.is_dir():
        return []
    return sorted(
        child.name
        for child in skills_dir.iterdir()
        if child.is_dir() and (child / SKILL_ENTRY).is_file()
    )


def expected_target(link_dir: Path, name: str) -> str:
    """应指向的目标（归一化的 `link_dir/../../skills/<name>`，比较 / 人读都用它）。"""
    return os.path.normpath(str(link_dir / ".." / ".." / SKILLS_DIRNAME / name))


def _strip_device_prefix(raw: str) -> str:
    for prefix in _DEVICE_PREFIXES:
        if raw.startswith(prefix):
            return raw[len(prefix):]
    return raw


def _key(path: str) -> str:
    """比较用的路径键：剥设备前缀 + 归一 + 大小写不敏感（Windows 路径）。"""
    return os.path.normcase(os.path.normpath(_strip_device_prefix(path)))


def is_junction(path: Path) -> bool:
    """是不是一个目录 junction（按重分析点标签判，不用 `islink` —— 它对 junction 恒假）。"""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return getattr(st, "st_reparse_tag", 0) == MOUNT_POINT_TAG


def junction_target(path: Path) -> str | None:
    """junction 实际存的目标（归一化）；不是 junction / 读不出来 ⇒ None。"""
    if not is_junction(path):
        return None
    try:
        raw = os.readlink(path)
    except OSError:
        return None
    return os.path.normpath(_strip_device_prefix(raw))


def link_status(link_dir: Path, name: str) -> str:
    """一个应挂条目的状态：`ok` / `missing` / `not-junction` / `wrong` / `target-missing`。"""
    link = link_dir / name
    want = expected_target(link_dir, name)
    if not os.path.lexists(link):
        return "missing"
    if not is_junction(link):
        return "not-junction"
    if _key(junction_target(link) or "") != _key(want):
        return "wrong"
    if not os.path.isdir(want):
        return "target-missing"
    return "ok"


def _extra_entries(link_dir: Path, names: list[str]) -> list[str]:
    """`.dsh/skills` 下**不属于这套技能**的条目名（只允许那套技能，多一个都算）。"""
    if not link_dir.is_dir():
        return []
    return sorted(child.name for child in link_dir.iterdir() if child.name not in names)


def check(root: Path) -> list[str]:
    """核对：返回问题清单（空 = 绿）。只读。"""
    skills_dir = skills_root(root)
    link_dir = link_root(root)
    names = skill_names(skills_dir)
    problems: list[str] = []
    if not skills_dir.is_dir():
        problems.append(f"[没技能] {skills_dir} 不存在")
        return problems
    if not names:
        problems.append(f"[没技能] {skills_dir} 下没有含 {SKILL_ENTRY} 的子目录")
    for name in names:
        link = link_dir / name
        want = expected_target(link_dir, name)
        st = link_status(link_dir, name)
        if st == "missing":
            problems.append(f"[缺] {name}：{link} 没挂（应指向 {want}）")
        elif st == "not-junction":
            problems.append(f"[非 junction] {name}：{link} 已存在但不是目录联接（有人手工改过？）")
        elif st == "wrong":
            problems.append(f"[指错] {name}：{link} → {junction_target(link)}（应指向 {want}）")
        elif st == "target-missing":
            problems.append(f"[目标不在] {name}：{link} → {want} 指到不存在的目录")
    for extra in _extra_entries(link_dir, names):
        problems.append(
            f"[多余] {extra}：{link_dir / extra} 不是技能（只有含 {SKILL_ENTRY} 的目录才该挂）"
        )
    return problems


def make_junction(link: Path, target: Path) -> None:
    """建一个目录 junction（`mklink /J`）。失败抛 `LinkError`。"""
    argv = ["cmd", "/c", "mklink", "/J", str(link), str(target)]
    done = subprocess.run(argv, capture_output=True, **NO_WINDOW)
    if done.returncode != 0:
        msg = (done.stdout or done.stderr or b"").decode("utf-8", "replace").strip()
        raise LinkError(f"mklink /J 失败（退出码 {done.returncode}）：{msg}")


def link(root: Path) -> int:
    """建 / 补 junction：缺的补、对的跳过；有冲突（指错 / 非 junction / 多余）就停。"""
    if os.name != "nt":
        print("[FAIL] 目录 junction 只存在于 Windows —— 本工具不适用", file=sys.stderr)
        return 2
    skills_dir = skills_root(root)
    link_dir = link_root(root)
    names = skill_names(skills_dir)
    if not names:
        print(f"[FAIL] {skills_dir} 下没有含 {SKILL_ENTRY} 的子目录", file=sys.stderr)
        return 1

    # 先扫冲突：已存在但不对 ⇒ 报错停下，**什么都不建**（不许静默重建）。
    conflicts: list[str] = []
    for name in names:
        st = link_status(link_dir, name)
        if st == "not-junction":
            conflicts.append(f"[非 junction] {name}：{link_dir / name} 已存在但不是目录联接")
        elif st == "wrong":
            conflicts.append(
                f"[指错] {name}：{link_dir / name} → {junction_target(link_dir / name)}"
                f"（应指向 {expected_target(link_dir, name)}）"
            )
        elif st == "target-missing":
            conflicts.append(
                f"[目标不在] {name}：{link_dir / name} → {expected_target(link_dir, name)} 不存在"
            )
    for extra in _extra_entries(link_dir, names):
        conflicts.append(
            f"[多余] {extra}：{link_dir / extra} 不是技能（只有含 {SKILL_ENTRY} 的目录才该挂）"
        )
    if conflicts:
        print(f"[FAIL] .dsh 技能 junction 有冲突（{len(conflicts)} 条）—— 不静默重建：",
              file=sys.stderr)
        for item in conflicts:
            print("  ·", item, file=sys.stderr)
        return 1

    link_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        link_path = link_dir / name
        if link_status(link_dir, name) == "ok":
            print(f"[跳过] {name}（已挂且指向正确）")
            continue
        try:
            make_junction(link_path, skills_dir / name)
        except LinkError as exc:
            print(f"[FAIL] {name}：{exc}", file=sys.stderr)
            return 2
        print(f"[建 ] {name} → {skills_dir / name}")
    return 0


def list_links(root: Path) -> int:
    """打印「技能名 → 目标」，人读。恒退 0（只报，不判）。"""
    skills_dir = skills_root(root)
    link_dir = link_root(root)
    names = skill_names(skills_dir)
    if not names:
        print(f"（{skills_dir} 下没找到技能目录）")
        return 0
    for name in names:
        link = link_dir / name
        st = link_status(link_dir, name)
        target = junction_target(link) or expected_target(link_dir, name)
        mark = "（未挂）" if st == "missing" else ""
        print(f"{name} → {target}  [{st}]{mark}")
    for extra in _extra_entries(link_dir, names):
        print(f"{extra} → {list_link_target(link_dir / extra)}  [多余]")
    return 0


def list_link_target(path: Path) -> str:
    """给 `--list` 用：一条目的实际目标（不是 junction 就写它是什么）。"""
    if is_junction(path):
        return junction_target(path) or "（读不出）"
    if path.is_dir():
        return "（真目录，非 junction）"
    return "（不是 junction）"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="把 skills/ 下的技能目录挂成 .dsh/skills/<名> 的 junction（默认动作 = 建）",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true",
                      help="只核对（红 = 退 1，点名哪一个 / 哪条多余）")
    mode.add_argument("--list", dest="list_mode", action="store_true",
                      help="打印「技能名 → 目标」，人读")
    parser.add_argument("--root", default=str(REPO_ROOT),
                        help="项目根（默认本仓根；测试 / 别的仓用）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    if args.check:
        problems = check(root)
        if problems:
            print(f"[FAIL] .dsh 技能 junction 核对不过（{len(problems)} 条）：", file=sys.stderr)
            for item in problems:
                print("  ·", item, file=sys.stderr)
            return 1
        print(f"[OK ] {len(skill_names(skills_root(root)))} 个技能 junction 都在且指向正确")
        return 0
    if args.list_mode:
        return list_links(root)
    return link(root)


if __name__ == "__main__":
    raise SystemExit(main())
