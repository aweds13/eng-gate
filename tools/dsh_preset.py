"""软工预设（preset-softeng）的仓内真源与安装器。

真源：docs/presets/softeng.patch.yml —— 一段 `- insert:` 补丁块，抄自
desktop profile 已组装好的 preset-standard，再改三处（id/name/order、
persona 前缀、skill-filesystem 的 customSkillDirs），并删掉 tool-pwsh 行。

为什么要删 tool-pwsh：ctx.shell 只能有一个实现（本机是 bash-sandbox），
而 preset 里的 tool-pwsh 行只要求注入 "shell" 服务，留着就会变成一个
【叫 pwsh、实际跑 bash】的工具 —— 比没有更糟。

用法：
    python -X utf8 tools/dsh_preset.py --check
    python -X utf8 tools/dsh_preset.py --install C:/Users/example/.dsh/profiles/desktop
"""

from __future__ import annotations

import argparse
import datetime
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRAGMENT = ROOT / "docs" / "presets" / "softeng.patch.yml"


def check_text(text: str) -> list[str]:
    """对补丁片段做结构检查；返回问题列表（空 = 通过）。"""
    problems: list[str] = []
    if not text.startswith("- insert:"):
        problems.append("片段必须以 `- insert:` 开头（裸 id 行只会改已有行，不会新增）")
    if text.count("- id: preset-softeng") != 1:
        problems.append("必须有且只有一条 `- id: preset-softeng`")
    if "id: softeng" not in text:
        problems.append("缺少预设内部 id：softeng")
    if "tool-pwsh" in text:
        problems.append("不许出现 tool-pwsh（会变成叫 pwsh、实际跑 bash 的假工具）")
    if "tool-bash" not in text:
        problems.append("缺少 tool-bash 行（本机 shell 只有 bash 一个实现）")
    else:
        idx = text.index("tool-bash")
        window = text[idx: idx + 160]
        if "disabled: false" not in window:
            problems.append("tool-bash 必须是 disabled: false")
    if "skills-softeng" not in text:
        problems.append("skill-filesystem 必须指向 softeng 专属技能目录")
    return problems


def check_file(path: Path = FRAGMENT) -> list[str]:
    if not path.is_file():
        return [f"找不到片段文件：{path}"]
    return check_text(path.read_text(encoding="utf-8"))


def install(profile: Path, fragment: Path = FRAGMENT) -> int:
    """把片段追加进 profile 的 cordis.patch.yml；已存在则什么都不做。"""
    patch = profile / "cordis.patch.yml"
    if not patch.is_file():
        print(f"[FAIL] 没有这个文件：{patch}")
        return 1
    text = patch.read_text(encoding="utf-8")
    if "preset-softeng" in text:
        print("[OK ] 目标 profile 里已经有 preset-softeng，跳过")
        return 0
    problems = check_file(fragment)
    if problems:
        print("[FAIL] 片段自身不合规：")
        for p in problems:
            print("  - " + p)
        return 1
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = patch.with_name(patch.name + f".bak-preset-{stamp}")
    shutil.copy2(patch, backup)
    body = text.rstrip() + "\n\n" + fragment.read_text(encoding="utf-8")
    patch.write_text(body, encoding="utf-8")
    print(f"[OK ] 已装入 {patch}（备份 {backup.name}）")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dsh_preset")
    ap.add_argument("--check", action="store_true", help="检查仓内片段")
    ap.add_argument("--install", metavar="PROFILE", help="装进指定 profile 目录")
    args = ap.parse_args(argv)
    if args.install:
        return install(Path(args.install))
    problems = check_file()
    if problems:
        print("[FAIL] 软工预设片段不合规：")
        for p in problems:
            print("  - " + p)
        return 1
    print(f"[OK ] 软工预设片段合规：{FRAGMENT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
