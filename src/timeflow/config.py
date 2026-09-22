"""配置加载与校验（pydantic + env 覆盖）。对应 SR-NF14。

读取 config.toml（若存在），合并默认值；环境变量可覆盖（如 TIMEFLOW_DATABASE__PATH）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import tomllib
from pydantic import BaseModel, Field, field_validator

from timeflow import vocab

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


class AcademicConfig(BaseModel):
    # GPA 制式：不同学校不同（4.0 制 / 5.0 制），可切换
    gpa_scale: str = "4.0"


class TasksConfig(BaseModel):
    # 「完成 N 天后进档案」（N11 / T-F2）：默认 3 天。
    # 这里是**默认值**：本机在设置页改过的存 `app_settings` 并优先
    # （与专注白名单/勿扰同一套机制，不另造一套配置）。
    archive_after_days: int = 3


class ReviewConfig(BaseModel):
    # 复习形式词表（SR-NF7 / G 批 · T-G1）：默认 = 内置那三种。
    # **校验和默认值都来自 `timeflow/vocab.py` 一处声明** —— 配置里写错了当场报错（不静默回落），
    # 本机在设置页改过的存 `app_settings` 并优先。
    forms: dict[str, str] = Field(default_factory=lambda: dict(vocab.REVIEW_FORMS.builtin))

    @field_validator("forms")
    @classmethod
    def _check_forms(cls, value: dict[str, str]) -> dict[str, str]:
        return vocab.parse(value, vocab.REVIEW_FORMS)


class InsightsConfig(BaseModel):
    # 时间热力图的维度词表（SR-NF7 / G 批 · T-G2）：改的是"用哪些维度看、排第几、叫什么"。
    heatmap_dimensions: dict[str, str] = Field(
        default_factory=lambda: dict(vocab.HEATMAP_DIMENSIONS.builtin)
    )

    @field_validator("heatmap_dimensions")
    @classmethod
    def _check_dimensions(cls, value: dict[str, str]) -> dict[str, str]:
        return vocab.parse(value, vocab.HEATMAP_DIMENSIONS)


class ExportConfig(BaseModel):
    # 沉淀型 markdown 的落盘目录（SR-F8 / G 批 · T-G4）：默认项目下 `export/`。
    # **相对路径一律相对项目根**（与调用方的工作目录无关）；本机在设置页改过的存
    # `app_settings` 并优先。红线 SR-F8.2：这里**不该指到 Obsidian 的笔记目录**
    # （只写独立共享目录）。
    dir: str = "export"

    # Obsidian 跳转（SR-F8.2 / G 批 · T-G5）：`vault` 是**库的名字**（`obsidian://` 协议用，
    # 不一定等于文件夹名）；`vault_dir` 是库的根目录（可选）—— 只用来把绝对路径句柄换算成
    # Vault 内的位置。**只读跳转**：软件不往 Vault 里写东西，也不替你在里面建目录。
    vault: str = ""
    vault_dir: str = ""


class Settings(BaseModel):
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    app: AppConfig = Field(default_factory=AppConfig)
    ledger: LedgerConfig = Field(default_factory=LedgerConfig)
    focus: FocusConfig = Field(default_factory=FocusConfig)
    academic: AcademicConfig = Field(default_factory=AcademicConfig)
    tasks: TasksConfig = Field(default_factory=TasksConfig)
    review: ReviewConfig = Field(default_factory=ReviewConfig)
    insights: InsightsConfig = Field(default_factory=InsightsConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)


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
