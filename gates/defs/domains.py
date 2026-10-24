"""改动面 → **必需档** 的唯一映射表（卡 A327 · T-AG442）。

为什么只有这一份：提交闸（`tools/wb_review.py` 第 ③′ 条）与门禁（`scripts/run_gates.py`
的 `--profile / --profiles`）必须**问同一张表**，否则两边一漂就会「门禁觉得够了、提交闸
觉得不够」——那正是卡 147 当初要拦的事。

口径（三条，别改语义）：

1. **并集**：改动面里每一个文件都按表查一遍，必需档取**并集**（改了 `src/` 与 `docs/`
   就要 lang + product + audit）。
2. **fail closed**：任何一个文件落不进表里 ⇒ 直接返回**全量三档**。宁可多跑，不许漏跑。
3. **表里只有"哪几档"，没有"跑哪道门"**：档的组成在 `run_gates.GATE_PROFILES`（卡 A321），
   这里只回答"这次改动最少要跑哪几档"。
"""

from __future__ import annotations

from typing import Final

# 档名与 `scripts/run_gates.py` 的 `GATE_PROFILES` 一致（那边有钉子保证每道门恰好一档）
ALL_PROFILES: Final[frozenset[str]] = frozenset({"lang", "audit", "product"})

# (前缀, 必需档)。**顺序无关**，一律取并集；前缀按 POSIX 分隔符写（git 的路径就是 POSIX）。
REQUIRED_PROFILES: Final[tuple[tuple[str, frozenset[str]], ...]] = (
    # 被判的那个产品：跑起来 + 真浏览器渲染
    ("src/", frozenset({"lang", "product"})),
    ("examples/", frozenset({"lang", "product"})),
    ("harness/", frozenset({"lang", "product"})),
    # 框架自己的实现与测试：语言门 + 契约门（台账/封存/Task: 都在 audit 里）
    ("tools/", frozenset({"lang", "audit"})),
    ("scripts/", frozenset({"lang", "audit"})),
    ("tests/", frozenset({"lang", "audit"})),
    ("gates/", frozenset({"lang", "audit"})),
    # 纯文本层：不碰代码，契约门就够
    ("docs/", frozenset({"audit"})),
    ("复盘/", frozenset({"audit"})),
    ("skills/", frozenset({"audit"})),
)

# 根目录那几个"散落的文本文件"（不带目录前缀）
_ROOT_FILES: Final[tuple[str, ...]] = (
    "README.md",
    "AGENTS.md",
    "harness.toml",
    "pipeline.toml",
    "pyproject.toml",
)


def _profiles_for_path(path: str) -> frozenset[str] | None:
    """单个文件落在哪一档；落不进表就回 None（调用方据此退回全量）。"""
    p = path.replace("\\", "/").lstrip("./")
    if not p:
        return None
    for prefix, profiles in REQUIRED_PROFILES:
        if p.startswith(prefix):
            return profiles
    if "/" not in p and (p in _ROOT_FILES or p.endswith(".md")):
        return frozenset({"audit"})
    return None


def required_profiles(paths: list[str] | tuple[str, ...]) -> frozenset[str]:
    """这次改动**最少**要跑哪几档。空清单 ⇒ 全量（没证据就别省）。"""
    if not paths:
        return ALL_PROFILES
    need: frozenset[str] = frozenset()
    for path in paths:
        one = _profiles_for_path(str(path))
        if one is None:
            return ALL_PROFILES
        need |= one
    return need or ALL_PROFILES


def explain(paths: list[str] | tuple[str, ...]) -> str:
    """给 trailer / 报错用的一句话：`必需 lang+audit（判不出 ⇒ 全量就别省）`。"""
    need = required_profiles(paths)
    if need == ALL_PROFILES:
        return "必需 lang+audit+product（全量：有路径判不出档）"
    return "必需 " + "+".join(sorted(need))
