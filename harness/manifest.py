r"""harness/ 复制体读项目胶水的**唯一解析处**（卡 088 · T-G183）。

为什么有它：harness/ 下的复制体是从 tools/ 原样复制来的，但项目专有值（路径这类"在本仓
长在哪"的知识）不许再写死在代码里 —— 全部收进仓根 `harness.toml`，只经本模块读。这样复制体
搬到别处时，改一份 TOML 就能落地（这就是"可独立出来"的缝）。

硬口径（卡 §1.2）：
  · **没有默认值可偷偷用**：文件缺失 / 不是合法 TOML / 缺段 / 缺键 / 键名拼错（= 未知键）/
    多写未知段 / 值不是非空字符串 → 一律抛 `ManifestError`，说清「哪个键 · 在哪个文件 · 期望什么」。
  · `path(..., must_exist=True)` 解析出的路径必须真实存在，否则同样抛错。
    `must_exist=False`（默认）只做路径解析、不查盘 —— 给"当字符串拼命令 / 做成员判定"的键用，
    这些键即使指向的文件暂不在盘上（例如整包复制到临时目录）也不该让工具崩。
  · 相对路径一律相对仓根 `ROOT`（= 本文件上两级；与原件 `tools/*.py` 同深度，解析结果一致）。

旁路（**唯一**的显式旁路，不是默认值）：环境变量 `HARNESS_TOML` 给绝对路径时读那份配置 ——
给测试与"写错要报错"的现场演示用；不设时只读 `ROOT/harness.toml`。
"""

from __future__ import annotations

import os
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "harness.toml"
ENV_OVERRIDE = "HARNESS_TOML"

# 允许出现的全部键（白名单即 schema）：多一个键 = 拼错，当场报错而不是静默忽略。
SCHEMA: dict[str, frozenset[str]] = {
    "paths": frozenset({
        "backlog",       # wb_plan 默认排班表（must_exist）
        "workbench",     # 派活器所在目录（拼命令 / 认进程）
        "gate_lock",     # wb_state 查锁脚本
        "gates_runner",  # wb_state 认门禁进程的脚本
        "ledger",        # wb_plan 受保护共享文件 ×6
        "changelog",
        "handoff",
        "handoff_card",
        "gates_state",
        "gates_reuse",
    }),
}


class ManifestError(Exception):
    """harness.toml 读不了 / 键缺失或拼错 / 路径不存在 —— 明确报错，不静默、不退回默认值。"""


def config_path() -> Path:
    """当前生效的配置路径：设了 HARNESS_TOML（绝对路径）用它，否则仓根 harness.toml。"""
    raw = os.environ.get(ENV_OVERRIDE, "").strip()
    return Path(raw) if raw else CONFIG_PATH


def load(path: str | Path | None = None) -> dict[str, dict[str, str]]:
    """读并**严格校验**一份配置，返回 {段: {键: 非空字符串}}。

    任何不合法都抛 ManifestError（错处说清键名、文件、期望）。直接传 `path` 时读那一份、
    不走环境变量、不碰缓存 —— 测试就用这个口。
    """
    cfg_path = Path(path) if path is not None else config_path()
    if not cfg_path.is_file():
        raise ManifestError(
            f"配置文件不存在：{cfg_path}（harness 复制体必须有它；"
            f"期望一份含 [paths] 表的 TOML，合法键：{sorted(SCHEMA['paths'])}）"
        )
    try:
        raw = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ManifestError(f"配置文件不是合法 TOML：{cfg_path}：{exc}") from exc
    if not isinstance(raw, dict):
        raise ManifestError(f"配置顶层必须是表（在 {cfg_path}）")

    extra_sections = sorted(set(raw) - set(SCHEMA))
    if extra_sections:
        raise ManifestError(
            f"配置出现未知段 {extra_sections}（在 {cfg_path}；合法段只有：{sorted(SCHEMA)}）"
            f" —— 多写/拼错都不允许，复制体只读它真用到的键"
        )

    clean: dict[str, dict[str, str]] = {}
    for section, legal_keys in SCHEMA.items():
        table = raw.get(section)
        if table is None:
            raise ManifestError(
                f"配置缺段 [{section}]（在 {cfg_path}；该段必须含键：{sorted(legal_keys)}）"
            )
        if not isinstance(table, dict):
            raise ManifestError(
                f"[{section}] 必须是 TOML 表（在 {cfg_path}；拿到 {type(table).__name__}）"
            )
        unknown = sorted(set(table) - legal_keys)
        if unknown:
            raise ManifestError(
                f"配置出现未知键 {unknown}（在 {cfg_path} 的 [{section}]；合法键："
                f"{sorted(legal_keys)}）—— 拼错了就报错，不静默忽略"
            )
        filled: dict[str, str] = {}
        for key in sorted(legal_keys):
            if key not in table:
                raise ManifestError(
                    f"配置缺键 {section}.{key}（在 {cfg_path}；期望非空字符串路径，"
                    f"相对路径相对仓根 {ROOT}）"
                )
            value = table[key]
            if not isinstance(value, str) or not value.strip():
                raise ManifestError(
                    f"配置键 {section}.{key} 必须是非空字符串（在 {cfg_path}；拿到 {value!r}）"
                )
            filled[key] = value.strip()
        clean[section] = filled
    return clean


_CACHE: tuple[Path, dict[str, dict[str, str]]] | None = None


def _current() -> dict[str, dict[str, str]]:
    global _CACHE
    cfg_path = config_path()
    if _CACHE is None or _CACHE[0] != cfg_path:
        _CACHE = (cfg_path, load(cfg_path))
    return _CACHE[1]


def get(key: str) -> str:
    """取一个 `段.键` 的原始字符串值。

    键名形状错 / 键不存在 → ManifestError（不返回 None 兜默认）。
    """
    section, dot, name = key.partition(".")
    if not dot or not name:
        raise ManifestError(
            f"键名必须是 '段.键' 形状（拿到 {key!r}；合法如 paths.backlog）"
        )
    table = _current().get(section)
    if table is None or name not in table:
        legal = sorted(SCHEMA.get(section, frozenset()))
        raise ManifestError(
            f"配置缺键 {key}（在 {config_path()}；段 [{section}] 的合法键：{legal}）"
        )
    return table[name]


def path(key: str, *, must_exist: bool = False) -> Path:
    """取键并解析成路径：相对值相对仓根 ROOT，绝对值原样用。

    must_exist=True 时盘上必须存在该文件/目录，否则 ManifestError 指名报键与期望。
    """
    value = get(key)
    resolved = Path(value)
    if not resolved.is_absolute():
        resolved = ROOT / resolved
    if must_exist and not resolved.exists():
        raise ManifestError(
            f"配置键 {key} 指向的路径不存在：{resolved}（在 {config_path()}；"
            f"期望该文件/目录真实存在 —— 键拼错或文件挪位请改配置，不许静默兜底）"
        )
    return resolved
