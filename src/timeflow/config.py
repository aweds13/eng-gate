"""配置加载与校验（pydantic + env 覆盖）。对应 SR-NF14。

读取 config.toml（若存在），合并默认值；环境变量可覆盖（如 TIMEFLOW_DATABASE__PATH）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import tomllib
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent.parent  # 项目根（src/timeflow/config.py -> 根）


class DatabaseConfig(BaseModel):
    path: str = "data/timeflow.db"


class AppConfig(BaseModel):
    accent_color: str = "#3b82f6"
    theme: str = "light"


class LedgerConfig(BaseModel):
    debt_mild: int = 3
    debt_medium: int = 7


class FocusConfig(BaseModel):
    block_by_default: bool = True
    do_not_disturb: list[str] = []
    pomodoro_minutes: int = 25


class Settings(BaseModel):
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    app: AppConfig = Field(default_factory=AppConfig)
    ledger: LedgerConfig = Field(default_factory=LedgerConfig)
    focus: FocusConfig = Field(default_factory=FocusConfig)


def _read_toml(config_path: Path | None) -> dict[str, Any]:
    path = config_path or (ROOT / "config.toml")
    if path.exists():
        with path.open("rb") as f:
            return tomllib.load(f)
    return {}


def _env_override(data: dict[str, Any], prefix: str = "TIMEFLOW_") -> dict[str, Any]:
    """把 TIMEFLOW_DATABASE__PATH 这类环境变量套进嵌套 dict。简化：仅演示顶层/双层键。"""
    result = data
    for key, val in os.environ.items():
        if not key.startswith(prefix):
            continue
        rest = key[len(prefix) :].lower().split("__")
        node = result
        for part in rest[:-1]:
            node = node.setdefault(part, {})
        node[rest[-1]] = val
    return result


def load_settings(config_path: Path | None = None) -> Settings:
    raw = _env_override(_read_toml(config_path))
    return Settings.model_validate(raw)


def settings() -> Settings:
    return load_settings()
