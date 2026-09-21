"""专注白名单与勿扰（SR-F3.3）。对应 AC 专注。

默认「阻止非白名单」：默认只允许白名单内来源；block_by_default 可由配置关闭。
勿扰时段：专注时段内按起止时间判断是否处于勿扰。桌面端/移动端可分别配置
（由 API 传入 platform，底层同样判定逻辑）。

**设置的存放**（T-D6 / GAP-F3-02）：白名单与勿扰时段是**用户在本机界面里改的运行期设置**，
放 `app_settings`（通用 key/value 表，与附件打开方式、到点通知开关同一处）；
`config.toml` 里的 `[focus]` 是**装机默认值** —— 界面没改过时以它为准。
边界：本模块只做**配置与判定**，不做系统级屏蔽（那需要桌面壳能力）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import sqlite3


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


# ---------------------------------------------------------------- 设置（app_settings 持久化）
KEY_BLOCK = "focus_block_by_default"
KEY_WHITELIST = "focus_whitelist"
KEY_DND = "focus_dnd"
MAX_ITEMS = 50  # 白名单 / 勿扰窗口各限 50 条（挡住畸形请求，也不给人无限堆）
_WINDOW_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)$")


def _get_raw(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def _put(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def _as_list(raw: object) -> list[object]:
    if isinstance(raw, str):
        return [x for x in raw.split(",")]
    if isinstance(raw, (list, tuple, set)):
        return list(raw)
    raise ValueError("得是一个列表")


def parse_sources(raw: object) -> list[str]:
    """白名单来源：非空字符串、去空白、去重保序。超长/超量一律 ValueError（不静默丢弃）。"""
    out: list[str] = []
    for item in _as_list(raw):
        text = str(item or "").strip()
        if not text:
            continue  # 界面里加了个空行不算错
        if len(text) > 60:
            raise ValueError(f"白名单条目太长（≤60 字）：{text[:20]}…")
        if text not in out:
            out.append(text)
    if len(out) > MAX_ITEMS:
        raise ValueError(f"白名单最多 {MAX_ITEMS} 条")
    return out


def parse_windows(raw: object) -> list[str]:
    """勿扰时段：必须 `HH:MM-HH:MM`（24 小时制；允许跨午夜，如 22:00-07:00）。"""
    out: list[str] = []
    for item in _as_list(raw):
        text = str(item or "").strip()
        if not text:
            continue
        if not _WINDOW_RE.match(text):
            raise ValueError(f"勿扰时段要写成 HH:MM-HH:MM（24 小时制）：{text}")
        if text not in out:
            out.append(text)
    if len(out) > MAX_ITEMS:
        raise ValueError(f"勿扰时段最多 {MAX_ITEMS} 条")
    return out


def get_settings(
    conn: sqlite3.Connection, defaults: GuardConfig | None = None
) -> dict[str, object]:
    """当前专注设置：**默认值来自 config.toml，本机在界面里改过的以表里为准**（逐项独立）。"""
    base = defaults or GuardConfig()
    raw_block = _get_raw(conn, KEY_BLOCK)
    raw_wl = _get_raw(conn, KEY_WHITELIST)
    raw_dnd = _get_raw(conn, KEY_DND)
    return {
        "block_by_default": base.block_by_default if raw_block is None else raw_block == "1",
        "whitelist": sorted(base.allowed) if raw_wl is None else parse_sources(raw_wl.split(",")),
        "do_not_disturb": (
            list(base.dnd_windows) if raw_dnd is None else parse_windows(raw_dnd.split(","))
        ),
    }


def to_config(data: dict[str, object]) -> GuardConfig:
    """把设置字典变回 `GuardConfig` —— 让 `is_allowed` / `is_do_not_disturb` 与界面同一份口径。"""
    allowed = data["whitelist"]
    windows = data["do_not_disturb"]
    return GuardConfig(
        block_by_default=bool(data["block_by_default"]),
        dnd_windows=[str(x) for x in (windows if isinstance(windows, (list, set, tuple)) else [])],
        allowed={str(x) for x in (allowed if isinstance(allowed, (list, set, tuple)) else [])},
    )


def set_settings(
    conn: sqlite3.Connection,
    block_by_default: object = None,
    whitelist: object = None,
    do_not_disturb: object = None,
    defaults: GuardConfig | None = None,
) -> dict[str, object]:
    """改设置（三项可单独改）。非法值一律 ValueError —— **不静默落默认值、不静默清空**。"""
    if block_by_default is not None:
        if not isinstance(block_by_default, bool):
            raise ValueError("block_by_default 只能是 true / false")
        _put(conn, KEY_BLOCK, "1" if block_by_default else "0")
    if whitelist is not None:
        _put(conn, KEY_WHITELIST, ",".join(parse_sources(whitelist)))
    if do_not_disturb is not None:
        _put(conn, KEY_DND, ",".join(parse_windows(do_not_disturb)))
    conn.commit()
    return get_settings(conn, defaults)


def describe_rules() -> dict[str, Any]:
    """给界面用的口径说明（规则只有一份，前端不自己复述）。"""
    return {
        "note": "白名单 = 专注时允许用的来源；勿扰时段内不打扰。**只做配置与判定**，"
        "不做系统级屏蔽（那需要桌面壳能力）。",
        "window_format": "HH:MM-HH:MM",
        "max_items": MAX_ITEMS,
    }
