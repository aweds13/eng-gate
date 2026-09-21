"""备份与恢复（SR-NF12 / SR-F9.3「重要数据可备份、可回滚」）。

口径（2026-09-21 用户定：设置页列出最近几个备份、点一下恢复）。要钉住的几件事：

- **恢复是"可逆"的**：恢复前自动再备份一次现库 —— 所以选错了能回去（不是嘴上说说，测它真有）；
- **恢复用在线备份 API 写内容**，不替换文件（Windows 上替换正被连接打开的文件会失败）；
- **备份名是唯一的安全边界**：不许带路径、不许 `..`、必须是本库的备份（这接口会覆盖真实数据）；
- 老备份的 schema 就地升级；比程序**新**的备份如实报告（降级场景不假装没事）。
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import tasks as tm
from timeflow.storage import backup as bk
from timeflow.storage import db as db_mod


@pytest.fixture()
def db_path(tmp_path):  # type: ignore[no-untyped-def]
    path = tmp_path / "t.db"
    conn = db_mod.connect(str(path))
    yield path
    conn.close()


# ---------------------------------------------------------------- 备份

def test_make_backup_skips_missing_db(tmp_path) -> None:  # type: ignore[no-untyped-def]
    assert bk.make_backup(tmp_path / "nope.db") is None


def test_make_backup_names_and_never_overwrites(db_path: Path) -> None:
    one = bk.make_backup(db_path)
    two = bk.make_backup(db_path)          # 同一秒内再来一次
    assert one is not None and two is not None
    assert one.name.startswith("t.db.bak-") and one.exists()
    assert two.name != one.name and two.exists(), "同一秒内两次备份不许互相覆盖"


def test_list_backups_sorted_newest_first_and_marks_renamed(db_path: Path) -> None:
    bk.make_backup(db_path)
    renamed = db_path.parent / f"{db_path.name}{bk.SUFFIX}手改的名字"
    shutil.copy2(db_path, renamed)
    # 把改名的那份 mtime 压到很早 —— 它的时间只能从 mtime 猜，正好验证"排序仍按时间倒序"
    old = time.time() - 86400
    os.utime(renamed, (old, old))
    items = bk.list_backups(db_path)
    assert items[-1]["name"] == renamed.name, "名字解析不出时间戳的排最后（用 mtime 兜底）"
    assert items[-1]["parsed"] is False, "名字解析不出时间戳要如实标出来"
    assert items[0]["parsed"] is True
    for item in items:
        assert set(item) == {"name", "size", "at", "parsed"} and int(str(item["size"])) > 0


# ---------------------------------------------------------------- 名字校验（安全边界）

@pytest.mark.parametrize("bad", ["../evil.db", "sub/t.db.bak-1", "..", "", "别的库.db",
                                 "t.db.bak-x/../t.db"])
def test_resolve_backup_rejects_bad_names(db_path: Path, bad: str) -> None:
    with pytest.raises(ValueError):
        bk.resolve_backup(db_path, bad)


def test_resolve_backup_rejects_missing_file(db_path: Path) -> None:
    with pytest.raises(ValueError):
        bk.resolve_backup(db_path, f"{db_path.name}{bk.SUFFIX}20200101-000000")


# ---------------------------------------------------------------- 恢复

def test_restore_brings_old_content_back_and_keeps_a_way_out(db_path: Path) -> None:
    conn = db_mod.connect(str(db_path))
    tm.create_task(conn, title="第一件事")
    made = bk.make_backup(db_path)
    assert made is not None
    tm.create_task(conn, title="第二件事")            # 备份之后又加了一件
    assert len(tm.list_tasks(conn)) == 2

    out = bk.restore(db_path, made.name, conn)

    assert out["restored"] == made.name
    assert out["safety_backup"], "恢复前必须先留一份现库 —— 否则这一步不可逆"
    titles = [t.title for t in tm.list_tasks(conn)]
    assert titles == ["第一件事"], f"恢复后应回到备份那一刻：{titles}"
    # 退路真的存在，而且**内容就是恢复前那份**（第二件事在里面）
    safety = db_path.parent / str(out["safety_backup"])
    assert safety.exists()
    old = db_mod.connect(str(safety))
    assert {t.title for t in tm.list_tasks(old)} == {"第一件事", "第二件事"}
    old.close()
    conn.close()


def test_restore_reports_a_newer_schema_honestly(db_path: Path) -> None:
    """恢复一个"未来版本"的备份：不改它，但必须报出来（别假装没事）。"""
    conn = db_mod.connect(str(db_path))
    future = db_path.parent / f"{db_path.name}{bk.SUFFIX}20990101-000000"
    shutil.copy2(db_path, future)
    raw = sqlite3.connect(str(future))
    raw.execute("UPDATE schema_version SET version = 99")
    raw.commit()
    raw.close()

    out = bk.restore(db_path, future.name, conn)

    assert out["newer_than_app"] is True and out["schema_after"] == 99
    assert out["schema_now"] == db_mod.SCHEMA_VERSION
    conn.close()


# ---------------------------------------------------------------- API

def _client(tmp_path):  # type: ignore[no-untyped-def]
    return TestClient(create_app(str(tmp_path / "api.db")))


def test_api_backups_list_and_restore_roundtrip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path)
    client.post("/api/tasks", json={"title": "留下的"})
    made = bk.make_backup(tmp_path / "api.db")
    assert made is not None
    client.post("/api/tasks", json={"title": "后来加的"})

    listed = client.get("/api/settings/backups")
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["db"] == "api.db" and body["items"] and "note" in body

    got = client.post("/api/settings/restore", json={"name": made.name})
    assert got.status_code == 200, got.text
    assert got.json()["restored"] == made.name
    titles = [t["title"] for t in client.get("/api/tasks").json()]
    assert titles == ["留下的"]


def test_api_restore_rejects_bad_name_and_cross_site(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path)
    assert client.post("/api/settings/restore", json={"name": "../t.db"}).status_code == 400
    assert client.post("/api/settings/restore", json={}).status_code == 400
    client.get("/api/tasks")                 # 先碰一下库：thread_local 是懒连接，不碰不会建文件
    made = bk.make_backup(tmp_path / "api.db")
    assert made is not None
    cross = client.post("/api/settings/restore", json={"name": made.name},
                        headers={"Origin": "https://evil.example"})
    assert cross.status_code == 403, "恢复是会覆盖真实数据的接口，必须只接受本机页面"


# ---------------------------------------------------------------- 启动入口（桌面形态 / 备份时机）

ROOT = Path(__file__).resolve().parent.parent


def test_serve_backs_up_has_window_flag_and_never_falls_back_silently() -> None:
    """`tools/serve.py`：起服务前备份（口径共用 storage/backup）+ `--window` 开桌面窗口。

    用户 2026-09-21 定"装 pywebview、走窗口形态"。窗口开不了时**必须说出原因**再退回浏览器 ——
    静默回退会让人以为自己在用桌面版，实际是浏览器（这个项目一直的原则：失败必出声）。
    """
    src = (ROOT / "tools" / "serve.py").read_text(encoding="utf-8")
    assert '"--window"' in src and "def _run_window(" in src
    assert "make_backup" in src, "起服务前要先备份（真正的口径在 storage/backup.py）"
    assert "退回浏览器" in src and "{exc}" in src, "窗口开不了要说原因，不许静默回退"
    assert "webview.create_window" in src and "webbrowser.open" in src, "回退到浏览器这条路要留着"


def test_desktop_entry_backs_up_and_reports_fallback() -> None:
    """`timeflow` 入口（窗口形态）：**也要备份**，回退同样要出声。

    为什么单独钉"也要备份"：以前只有 `tools/serve.py` 备份，走窗口入口反而不备份 ——
    同一件事两套行为，属于隐患（起窗口前同样会跑 schema 迁移）。
    """
    src = (ROOT / "src" / "timeflow" / "app" / "main.py").read_text(encoding="utf-8")
    assert "make_backup" in src, "走 timeflow 入口时也要备份"
    assert "import webview" in src and "webview.create_window" in src
    assert "webbrowser.open" in src, "保留浏览器回退"
    assert "退回浏览器" in src and "exc" in src, "回退必须出声"
