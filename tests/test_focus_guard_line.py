"""专注白名单 / 勿扰设置（SR-F3.3 / GAP-F3-02）：口径、校验、持久化与来源守卫。

以前 `/api/focus/guard` **只回读 config.toml、没有任何写入口**（审计记为 GAP-F3-02），
所以设置页无处可改。现在：默认值仍来自 config.toml，本机在界面里改过的存 `app_settings` 并优先 ——
逐项独立（只改了白名单，勿扰仍用配置值）。

两条硬口径：
- **非法值一律 400**（不静默落默认值、不静默清空）—— 静默清空等于数据丢失；
- 改设置**只接受本机页面**（带 Origin 的跨站请求 403），与附件打开方式同一套守卫。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core.focus import guard as fg
from timeflow.storage import db as db_mod

if TYPE_CHECKING:
    import sqlite3


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "g.db"))
    yield c
    c.close()


# ---------------------------------------------------------------- 解析与校验

def test_parse_sources_trims_dedupes_and_keeps_order() -> None:
    assert fg.parse_sources(["vscode", " 微信 ", "vscode", "", "  "]) == ["vscode", "微信"]


def test_parse_sources_rejects_too_long_and_too_many() -> None:
    with pytest.raises(ValueError):
        fg.parse_sources(["x" * 61])
    with pytest.raises(ValueError):
        fg.parse_sources([f"s{i}" for i in range(fg.MAX_ITEMS + 1)])
    with pytest.raises(ValueError):
        fg.parse_sources(123)          # 既不是列表也不是逗号串


@pytest.mark.parametrize("win", ["22:00-07:00", "00:00-23:59", "09:30-10:00"])
def test_parse_windows_accepts_24h(win: str) -> None:
    assert fg.parse_windows([win]) == [win]


@pytest.mark.parametrize("win", ["25:00-07:00", "7:00-9:00", "22:00~07:00", "22:00", "abc"])
def test_parse_windows_rejects_bad_format(win: str) -> None:
    with pytest.raises(ValueError):
        fg.parse_windows([win])


def test_window_boundary_semantics_still_hold() -> None:
    """跨午夜窗口的判定没被这次改动弄坏（22:00-07:00 应覆盖 23:00 与 06:00，不覆盖 12:00）。"""
    cfg = fg.GuardConfig(dnd_windows=["22:00-07:00"])
    assert fg.is_do_not_disturb(cfg, 23 * 60) is True
    assert fg.is_do_not_disturb(cfg, 6 * 60) is True
    assert fg.is_do_not_disturb(cfg, 12 * 60) is False
    assert fg.is_do_not_disturb(cfg, 7 * 60) is False  # 右端开区间


# ---------------------------------------------------------------- 持久化 + 与配置合并

def test_settings_fall_back_to_config_then_persist(conn: sqlite3.Connection) -> None:
    defaults = fg.GuardConfig(block_by_default=True, dnd_windows=["23:00-23:30"], allowed={"旧的"})
    assert fg.get_settings(conn, defaults) == {
        "block_by_default": True, "whitelist": ["旧的"], "do_not_disturb": ["23:00-23:30"],
    }
    got = fg.set_settings(conn, whitelist=["vscode"], defaults=defaults)
    assert got["whitelist"] == ["vscode"]
    assert got["do_not_disturb"] == ["23:00-23:30"], "只改了白名单，勿扰应仍是配置默认值"
    assert fg.get_settings(conn, defaults)["whitelist"] == ["vscode"], "改过之后要以表里为准"


def test_settings_can_clear_whitelist_explicitly(conn: sqlite3.Connection) -> None:
    """空列表 = **明确清空**（与"没传这个字段"不同）—— 别把两者混成一种。"""
    fg.set_settings(conn, whitelist=["a", "b"])
    assert fg.get_settings(conn)["whitelist"] == ["a", "b"]
    assert fg.set_settings(conn, whitelist=[])["whitelist"] == []
    assert fg.get_settings(conn)["whitelist"] == []       # 传了 None 才是不动
    assert fg.set_settings(conn, do_not_disturb=["07:00-08:00"])["whitelist"] == []


def test_set_settings_rejects_bad_values_without_writing(conn: sqlite3.Connection) -> None:
    fg.set_settings(conn, whitelist=["keep"])
    with pytest.raises(ValueError):
        fg.set_settings(conn, whitelist=["keep", "x" * 99])
    assert fg.get_settings(conn)["whitelist"] == ["keep"], "校验失败不许留下半个改动"
    with pytest.raises(ValueError):
        fg.set_settings(conn, block_by_default="yes")
    assert fg.get_settings(conn)["block_by_default"] is True


def test_to_config_round_trips_for_judgement() -> None:
    """界面存下来的设置能变回 `GuardConfig` —— 配置与判定**共用同一份口径**。"""
    cfg = fg.to_config({"block_by_default": False, "whitelist": ["vscode"],
                        "do_not_disturb": ["22:00-07:00"]})
    assert fg.is_allowed(cfg, "随便什么") is True          # 一律放行
    assert fg.is_allowed(cfg, "vscode") is True
    strict = fg.to_config({"block_by_default": True, "whitelist": ["vscode"], "do_not_disturb": []})
    assert fg.is_allowed(strict, "别的") is False
    assert fg.is_allowed(strict, "vscode") is True


# ---------------------------------------------------------------- API 与守卫

def _client(tmp_path):  # type: ignore[no-untyped-def]
    return TestClient(create_app(str(tmp_path / "api.db")))


def test_get_guard_reports_settings_and_rules(tmp_path) -> None:  # type: ignore[no-untyped-def]
    got = _client(tmp_path).get("/api/focus/guard")
    assert got.status_code == 200, got.text
    body = got.json()
    assert set(body) >= {"block_by_default", "whitelist", "do_not_disturb", "note",
                         "window_format", "max_items"}


def test_put_guard_roundtrip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    c = _client(tmp_path)
    put = c.put("/api/settings/focus-guard",
                json={"block_by_default": False, "whitelist": ["vscode", "微信"],
                      "do_not_disturb": ["22:00-07:00"]})
    assert put.status_code == 200, put.text
    assert put.json()["whitelist"] == ["vscode", "微信"]
    assert c.get("/api/focus/guard").json()["block_by_default"] is False
    assert c.get("/api/focus/guard").json()["do_not_disturb"] == ["22:00-07:00"]


def test_put_guard_rejects_illegal_values(tmp_path) -> None:  # type: ignore[no-untyped-def]
    c = _client(tmp_path)
    bad_window = c.put("/api/settings/focus-guard", json={"do_not_disturb": ["25:00-07:00"]})
    assert bad_window.status_code == 400
    assert c.put("/api/settings/focus-guard", json={"block_by_default": "yes"}).status_code == 400
    assert c.put("/api/settings/focus-guard", json={"whitelist": 123}).status_code == 400
    # 逗号串也收（curl / 手写方便），但会按逗号拆开 —— 这是**有意**的宽松，不是静默降级
    assert c.put("/api/settings/focus-guard",
                 json={"whitelist": "vscode,微信"}).json()["whitelist"] == ["vscode", "微信"]


def test_put_guard_refuses_cross_site(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """改服务端设置的接口只接受本机页面（跨站 403）—— 与附件打开方式同一套守卫。"""
    c = _client(tmp_path)
    bad = c.put("/api/settings/focus-guard", json={"whitelist": ["x"]},
                headers={"Origin": "https://evil.example"})
    assert bad.status_code == 403
    ok = c.put("/api/settings/focus-guard", json={"whitelist": ["x"]},
               headers={"Origin": "http://127.0.0.1:8520"})
    assert ok.status_code == 200
