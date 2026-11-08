"""云门禁 profile 的测试侧读法（不是产品代码）。

为什么测试要读 profile：卡 E35 那批钉子问的是「**engineering 这趟门禁端到端会怎么做**」，
而 engineering 的值在泛用化之后住在 scripts/cloud/profiles/engineering.toml。
骨架本身只认键、不认仓 ⇒ 只看骨架文本已经**问不出**那个问题了。

所以测试侧的 haystack 是 `run_gate.sh --render` 的输出：骨架 + 这份 profile 渲染成的平铺脚本。
它既保持「断言的是脚本真实形状」这个口径，又要求 profile 必须真的把值还原回脚本
（profile 写错 ⇒ 渲染结果里没有那个值 ⇒ 断言红）。
"""
from __future__ import annotations

import functools
import subprocess
import sys
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent
CLOUD = ROOT / "scripts" / "cloud"
RUN_GATE = CLOUD / "run_gate.sh"
PROFILES = CLOUD / "profiles"


def profile_path(name: str) -> Path:
    return PROFILES / (name + ".toml")


def load_profile(name: str) -> dict:
    """读一份 profile 的原始 TOML（断言「这个仓声明了什么」时用它）。"""
    with open(profile_path(name), "rb") as fh:
        return tomllib.load(fh)


@functools.cache
def render(name: str = "engineering") -> str:
    """`run_gate.sh --render` 的输出 = 骨架 + 这份 profile 的平铺脚本（不执行、不联网）。"""
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(CLOUD / "profile.py"), "render",
         "--skeleton", str(RUN_GATE), "--profile", str(profile_path(name))],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 0, f"渲染 {name} 失败（rc={proc.returncode}）：\n{proc.stderr}"
    return proc.stdout


def skeleton() -> str:
    """骨架原文（断言「骨架不认识任何仓」时用它 —— 有字面量就说明漏抽了）。"""
    return RUN_GATE.read_bytes().decode("utf-8", "replace")
