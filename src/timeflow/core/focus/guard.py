"""专注白名单与勿扰（SR-F3.3）。对应 AC 专注。

默认「阻止非白名单」：默认只允许白名单内来源；block_by_default 可由配置关闭。
勿扰时段：专注时段内按起止时间判断是否处于勿扰。桌面端/移动端可分别配置
（由 API 传入 platform，底层同样判定逻辑）。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GuardConfig:
    block_by_default: bool = True
    dnd_windows: list[str] = field(default_factory=list)  # ["22:00-07:00"]
    allowed: set[str] = field(default_factory=set)  # 白名单来源


def is_allowed(config: GuardConfig, source: str, platform: str | None = None) -> bool:
    """判断某来源是否允许在专注时使用。

    若 block_by_default 为 True，仅白名单内来源（按平台细分的 allowed）放行；
    否则全部放行。白名单内来源恒放行（覆盖阻止逻辑）。
    """
    if source in config.allowed:
        return True
    return not config.block_by_default


def _window_contains(window: str, minutes: int) -> bool:
    """判断当前分钟(0-1439)是否落在 'HH:MM-HH:MM' 窗口内（处理跨午夜）。"""
    start_s, end_s = window.split("-")
    sh, sm = map(int, start_s.split(":"))
    eh, em = map(int, end_s.split(":"))
    start = sh * 60 + sm
    end = eh * 60 + em
    if start <= end:
        return start <= minutes < end
    return minutes >= start or minutes < end  # 跨午夜


def is_do_not_disturb(config: GuardConfig, now_minutes: int) -> bool:
    """判断当前时刻是否处于勿扰时段。now_minutes = hour*60+minute。"""
    return any(_window_contains(w, now_minutes) for w in config.dnd_windows)
