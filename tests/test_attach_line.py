"""F1/F5 主线 · 段2 · T-B4：附件 / 要求链接（SR-F1.4a「附件」+ SR-F5.3「跳转本地文件/网站」）。

覆盖：
- schema v8 → v9：`tasks.attach` 与 `course_assessments.attach` 两列 + `app_settings` 表
  （幂等、老行 NULL、缺表不失败）；
- 打开规则（`core/attach.py`，**纯函数可测**）：网址→浏览器；目录→开目录；本地文件按
  白名单 / 模式（folder 默认 · direct · auto 文档类定位）/ 安全底线（可执行脚本类永不直接打开）；
  路径不存在 → `copy`（失败必提示，不静默）；
- 设置：模式与白名单**存服务端**（不由请求参数决定）；非法模式/非法扩展名拒绝；
  可执行类不许进白名单；
- 接口：任务附件增删（幂等去重、越界 400、任务不存在 404）；`/api/attach/open`（dry_run 只解析；
  **跨站来源被 403 挡住**）；考核项附件复用同一字段；
- 口径：附件只是引用（不复制文件、不发 facts、不动账本）。
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import academic as ac
from timeflow.core import attach as at
from timeflow.core import sync as sync
from timeflow.core import tasks as tm
from timeflow.storage import db as db_mod


def _client(tmp_path, name: str = "attach.db") -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(create_app(str(tmp_path / name)))


def _make_v8_db(path: str) -> None:
    """手工造一个 v8 旧库：tasks/course_assessments 都没有 attach，也没有 app_settings 表。"""
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    raw.execute("INSERT INTO schema_version (version) VALUES (8)")
    raw.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, due_date TEXT,"
        " group_name TEXT, repeat_days INTEGER, parent_id TEXT, is_myday INTEGER DEFAULT 0,"
        " status TEXT, created_at TEXT, updated_at TEXT, version INTEGER DEFAULT 1,"
        " note TEXT, priority TEXT DEFAULT '中', flagged INTEGER DEFAULT 0)"
    )
    raw.execute(
        "CREATE TABLE course_assessments (id TEXT PRIMARY KEY, course_id TEXT NOT NULL,"
        " name TEXT NOT NULL, due_date TEXT, weight REAL, score REAL, note TEXT,"
        " created_at TEXT)"
    )
    raw.execute(
        "INSERT INTO tasks (id,title,status,created_at,updated_at,version)"
        " VALUES ('old1','旧任务','未开始','2026-01-01','2026-01-01',1)"
    )
    raw.execute(
        "INSERT INTO course_assessments (id,course_id,name) VALUES ('a1','c1','期中')"
    )
    raw.commit()
    raw.close()


# ---------------------------------------------------------------- 迁移（v9）

def test_upgrade_v8_adds_attach_columns_and_settings_table(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = str(tmp_path / "v8.db")
    _make_v8_db(p)

    conn = db_mod.connect(p)
    ver = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    assert int(ver["version"]) == db_mod.SCHEMA_VERSION
    for table in ("tasks", "course_assessments"):
        cols = {str(r["name"]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        assert "attach" in cols, f"{table} 缺 attach 列"
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='app_settings'"
    ).fetchone() is not None
    # 老行没有附件 → 读出空列表（不猜）
    assert tm.get_task(conn, "old1").attach == []
    assert ac.get_assessment(conn, "a1")["attach"] == []
    conn.close()


def test_upgrade_v9_is_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = str(tmp_path / "v8b.db")
    _make_v8_db(p)
    for _ in range(3):
        c = db_mod.connect(p)
        cols = [str(r["name"]) for r in c.execute("PRAGMA table_info(tasks)").fetchall()]
        assert cols.count("attach") == 1
        c.close()


def test_v9_missing_tables_does_not_fail(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """残缺库（两张表都没有）升级时跳过加列，但 app_settings 仍建出来，不抛异常。"""
    p = str(tmp_path / "broken.db")
    raw = sqlite3.connect(p)
    raw.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    raw.execute("INSERT INTO schema_version (version) VALUES (8)")
    raw.commit()
    raw.close()

    conn = db_mod.connect(p)
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='app_settings'"
    ).fetchone() is not None
    conn.close()


def test_bad_json_in_attach_does_not_break_reading(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """手改过库 / 老数据：坏 JSON、非数组、缺 target 的元素都要能安然跳过
    （不许让任务列表打不开）。"""
    conn = db_mod.connect(str(tmp_path / "bad.db"))
    t = tm.create_task(conn, "任务")
    conn.execute("UPDATE tasks SET attach = ? WHERE id = ?", ("{不是 JSON", t.id))
    conn.commit()
    assert tm.get_task(conn, t.id).attach == []

    conn.execute(
        "UPDATE tasks SET attach = ? WHERE id = ?",
        ('[{"title":"没有 target"}, {"target":"  "}, "字符串", 3]', t.id),
    )
    conn.commit()
    assert tm.get_task(conn, t.id).attach == []
    conn.close()


# ---------------------------------------------------------------- 打开规则（纯函数）

def _files(tmp_path):  # type: ignore[no-untyped-def]
    """真建一个目录 + 一个 pdf + 一个 exe：判定按**真实文件系统**走，测试也用真文件。"""
    folder = tmp_path / "课件"
    folder.mkdir()
    pdf = folder / "第3章.pdf"
    pdf.write_text("x", encoding="utf-8")
    exe = folder / "安装包.exe"
    exe.write_text("x", encoding="utf-8")
    return folder, pdf, exe


def test_resolve_url_goes_to_browser(tmp_path) -> None:  # type: ignore[no-untyped-def]
    r = at.resolve("https://example.com/要求", at.MODE_FOLDER, [])
    assert r["kind"] == "url" and r["action"] == "browser"
    # http/https 之外的不当网址处理（不是路径也不存在 → copy，如实说）
    assert at.resolve("ftp://x/y", at.MODE_AUTO, [])["action"] == "copy"


def test_resolve_directory_opens_folder(tmp_path) -> None:  # type: ignore[no-untyped-def]
    folder, _pdf, _exe = _files(tmp_path)
    r = at.resolve(str(folder), at.MODE_FOLDER, [])
    assert r["kind"] == "dir" and r["action"] == "folder"


def test_resolve_local_file_by_mode(tmp_path) -> None:  # type: ignore[no-untyped-def]
    _folder, pdf, _exe = _files(tmp_path)
    # 默认（folder）：只开文件夹
    assert at.resolve(str(pdf), at.MODE_FOLDER, [])["action"] == "folder"
    # direct：用默认程序打开
    assert at.resolve(str(pdf), at.MODE_DIRECT, [])["action"] == "direct"
    # auto：文档类 → 定位到文件
    assert at.resolve(str(pdf), at.MODE_AUTO, [])["action"] == "select"
    # auto 下未知类型（txt 之外的怪扩展名）→ 只开文件夹
    weird = tmp_path / "数据.zzz"
    weird.write_text("x", encoding="utf-8")
    assert at.resolve(str(weird), at.MODE_AUTO, [])["action"] == "folder"


def test_whitelist_overrides_mode(tmp_path) -> None:  # type: ignore[no-untyped-def]
    _folder, pdf, _exe = _files(tmp_path)
    r = at.resolve(str(pdf), at.MODE_FOLDER, [".pdf"])
    assert r["action"] == "direct" and r["whitelisted"] is True


def test_executable_never_direct_opens(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """安全底线：可执行/脚本类**任何模式**都只到文件夹（点开本地文件等于从文档里启动程序）。"""
    _folder, _pdf, exe = _files(tmp_path)
    for mode in at.VALID_MODES:
        r = at.resolve(str(exe), mode, [])
        assert r["action"] == "folder", f"{mode} 下 .exe 不该直接打开"
    # 白名单里也不允许（入口就拒绝）
    with pytest.raises(ValueError):
        at.check_whitelist_entry(".exe")
    with pytest.raises(ValueError):
        at.parse_whitelist(["exe"])


def test_missing_path_returns_copy_with_reason(tmp_path) -> None:  # type: ignore[no-untyped-def]
    r = at.resolve(str(tmp_path / "不存在.pdf"), at.MODE_AUTO, [".pdf"])
    assert r["action"] == "copy" and "不存在" in r["reason"]
    assert r["file_url"] is not None  # 仍然给一个 file:// 供展示/兜底


def test_unknown_mode_is_rejected() -> None:
    with pytest.raises(ValueError):
        at.resolve("https://a.b", "随便开", [])
    assert at.MODE_FOLDER in at.VALID_MODES and at.DEFAULT_MODE == at.MODE_FOLDER


# ---------------------------------------------------------------- 执行（注入 runner，避免真弹窗）

def test_open_target_executes_and_degrades_on_failure(tmp_path) -> None:  # type: ignore[no-untyped-def]
    _folder, pdf, _exe = _files(tmp_path)
    calls: list[tuple[str, str]] = []

    def ok_runner(action: str, path: str) -> tuple[bool, str]:
        calls.append((action, path))
        return True, "已打开"

    got = at.open_target(str(pdf), at.MODE_AUTO, [], runner=ok_runner)
    assert got["action"] == "select" and got["executed"] is True
    assert calls == [("select", str(pdf))]

    def fail_runner(action: str, path: str) -> tuple[bool, str]:
        return False, "打不开：权限不足"

    bad = at.open_target(str(pdf), at.MODE_AUTO, [], runner=fail_runner)
    # 失败 → 退化为"复制路径 + 提示"，且原因如实带上
    assert bad["action"] == "copy" and bad["executed"] is False
    assert "权限不足" in bad["reason"]


def test_open_target_dry_run_does_not_execute(tmp_path) -> None:  # type: ignore[no-untyped-def]
    _folder, pdf, _exe = _files(tmp_path)

    def boom(action: str, path: str) -> tuple[bool, str]:
        raise AssertionError("dry_run 不该真的执行")

    got = at.open_target(str(pdf), at.MODE_DIRECT, [], dry_run=True, runner=boom)
    assert got["dry_run"] is True and got["executed"] is False
    assert got["action"] == "direct"  # 解析结果仍然照实给


def test_run_open_rejects_non_local_actions() -> None:
    ok, detail = at.run_open("browser", "https://a.b")
    assert ok is False and "不由本机执行" in detail


# ---------------------------------------------------------------- 设置（服务端）

def test_settings_default_and_update(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "set.db"))
    got = at.get_settings(conn)
    assert got["mode"] == at.DEFAULT_MODE == at.MODE_FOLDER  # 默认最保守
    assert got["whitelist"] == []  # 白名单默认空（显式放行）

    after = at.set_settings(conn, mode=at.MODE_AUTO, whitelist=[".PDF", ".md", ".md"])
    assert after["mode"] == "auto"
    assert after["whitelist"] == [".pdf", ".md"]  # 规整 + 去重
    # 只改一个字段时不覆盖另一个
    assert at.set_settings(conn, mode="direct")["whitelist"] == [".pdf", ".md"]
    conn.close()


def test_settings_reject_bad_values(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "set2.db"))
    with pytest.raises(ValueError):
        at.set_settings(conn, mode="随便")
    with pytest.raises(ValueError):
        at.set_settings(conn, whitelist=[".exe"])
    with pytest.raises(ValueError):
        at.set_settings(conn, whitelist=["a b"])
    assert at.get_settings(conn)["mode"] == at.MODE_FOLDER  # 失败没有落库
    conn.close()


# ---------------------------------------------------------------- 任务附件 API

def test_task_attachment_crud(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path)
    tid = client.post("/api/tasks", json={"title": "交作业"}).json()["id"]

    got = client.post(
        f"/api/tasks/{tid}/attachments",
        json={"target": "https://x.example/要求", "title": "要求页"},
    ).json()
    assert got["attach"] == [{"target": "https://x.example/要求", "title": "要求页"}]

    # 同一个 target 再点一次：幂等（不去重会产生两条一模一样的）
    again = client.post(
        f"/api/tasks/{tid}/attachments", json={"target": "https://x.example/要求"}
    ).json()
    assert len(again["attach"]) == 1

    # 建任务时也能直接带附件
    with_attach = client.post(
        "/api/tasks",
        json={"title": "自带附件", "attach": [{"target": "D:\\课件\\a.pdf", "title": "讲义"}]},
    ).json()
    assert with_attach["attach"][0]["target"] == "D:\\课件\\a.pdf"

    assert client.delete(f"/api/tasks/{tid}/attachments/0").json()["attach"] == []
    assert client.delete(f"/api/tasks/{tid}/attachments/0").status_code == 400  # 越界
    assert client.post(
        "/api/tasks/nope/attachments", json={"target": "x"}
    ).status_code == 404
    assert client.post(
        f"/api/tasks/{tid}/attachments", json={"target": "   "}
    ).status_code == 400


def test_attachment_is_not_a_fact_and_not_in_ledger(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """附件只存引用：不发 facts、不动账本（与备注/优先级/标记同口径）。"""
    client = _client(tmp_path, "ledger.db")
    tid = client.post("/api/tasks", json={"title": "任务", "due_date": "2030-01-01"}).json()["id"]
    before = client.get("/api/summary").json()

    client.post(f"/api/tasks/{tid}/attachments", json={"target": "https://a.b/c"})
    assert client.get(f"/api/tasks/{tid}/facts").json() == []
    assert client.get("/api/summary").json() == before


def test_attach_open_endpoint(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path, "open.db")
    # 冷启动默认 mode=folder：本地文件 → 只开文件夹（dry_run，不真弹窗）
    pdf = tmp_path / "讲义.pdf"
    pdf.write_text("x", encoding="utf-8")
    r = client.post("/api/attach/open", json={"target": str(pdf), "dry_run": True}).json()
    assert r["action"] == "folder" and r["kind"] == "file" and r["executed"] is False

    # 改成「按格式自动」后：文档类 → 定位到文件
    client.put("/api/settings/attach", json={"mode": "auto"})
    r2 = client.post("/api/attach/open", json={"target": str(pdf), "dry_run": True}).json()
    assert r2["action"] == "select"

    # 网址 → 交给浏览器（后端不代开）
    r3 = client.post("/api/attach/open", json={"target": "https://a.b/c"}).json()
    assert r3["action"] == "browser" and r3["executed"] is False

    # 路径不存在 → copy（失败必提示）
    r4 = client.post("/api/attach/open", json={"target": str(tmp_path / "没有.pdf")}).json()
    assert r4["action"] == "copy" and "不存在" in r4["reason"]

    # 空 target → 400
    assert client.post("/api/attach/open", json={"target": ""}).status_code == 400


def test_settings_api_roundtrip_and_400(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path, "setapi.db")
    got = client.get("/api/settings/attach").json()
    assert got["mode"] == "folder" and got["whitelist"] == []
    assert {m["value"] for m in got["modes"]} == set(at.VALID_MODES)
    assert ".pdf" in got["doc_extensions"]

    upd = client.put(
        "/api/settings/attach", json={"mode": "auto", "whitelist": [".pdf", ".md"]}
    ).json()
    assert upd["mode"] == "auto" and upd["whitelist"] == [".pdf", ".md"]
    assert client.put("/api/settings/attach", json={"mode": "乱写"}).status_code == 400
    assert client.put("/api/settings/attach", json={"whitelist": [".bat"]}).status_code == 400


def test_cross_origin_is_rejected(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """来源守卫：会**在本机开东西**的接口不接受外部网页调用（本机页面照常）。"""
    client = _client(tmp_path, "origin.db")
    evil = {"Origin": "https://evil.example"}
    assert client.post(
        "/api/attach/open", json={"target": "https://a.b", "dry_run": True}, headers=evil
    ).status_code == 403
    assert client.put(
        "/api/settings/attach", json={"mode": "direct"}, headers=evil
    ).status_code == 403
    # 本机页面（同源）正常
    assert client.put(
        "/api/settings/attach",
        json={"mode": "direct"},
        headers={"Origin": "http://127.0.0.1:8520"},
    ).status_code == 200
    # 读接口不受影响
    assert client.get("/api/settings/attach").status_code == 200


# ---------------------------------------------------------------- 学业考核项复用

def test_assessment_reuses_attachment_field(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path, "acad.db")
    cid = client.post("/api/courses", json={"name": "高数"}).json()["id"]
    aid = client.post(
        "/api/assessments", json={"course_id": cid, "name": "期中", "note": "闭卷"}
    ).json()["id"]

    got = client.post(
        f"/api/assessments/{aid}/attachments",
        json={"target": "https://x.example/考纲", "title": "考纲"},
    ).json()
    assert got["attach"] == [{"target": "https://x.example/考纲", "title": "考纲"}]
    # 列表里也带上（前端直接渲染）
    listed = client.get("/api/assessments").json()
    assert listed[0]["attach"][0]["title"] == "考纲"
    # 临期提醒那条也带（同一个 _assessment_row）
    upcoming = client.get("/api/assessments/upcoming").json()
    assert all("attach" in a for a in upcoming)

    assert client.delete(
        f"/api/assessments/{aid}/attachments/0"
    ).json()["attach"] == []
    assert client.delete(f"/api/assessments/{aid}/attachments/0").status_code == 400
    assert client.post(
        "/api/assessments/nope/attachments", json={"target": "x"}
    ).status_code == 404


# ---------------------------------------------------------------- 跨端

def test_sync_merge_carries_attach_and_keeps_local_when_absent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "sync.db"))
    tid = tm.create_task(conn, "本地").id
    tm.add_attachment(conn, tid, "https://local.example/1", "本地链接")

    # ① 远端带了 attach → 以远端为准
    sync.merge_task(conn, {
        "id": tid, "title": "远端", "attach": [{"target": "https://remote.example/2"}],
        "updated_at": "2030-01-01T00:00:00", "version": 9,
    })
    assert tm.get_task(conn, tid).attach == [{"target": "https://remote.example/2", "title": None}]

    # ② 远端没带这个字段 → 保留本地附件（不静默抹掉）
    sync.merge_task(conn, {
        "id": tid, "title": "远端二", "updated_at": "2031-01-01T00:00:00", "version": 10,
    })
    got = tm.get_task(conn, tid)
    assert got.title == "远端二"
    assert got.attach == [{"target": "https://remote.example/2", "title": None}]

    # ③ 远端 attach 是坏数据 → 收敛成空列表，但不拒绝整条合并
    sync.merge_task(conn, {
        "id": tid, "title": "远端三", "attach": "{坏 JSON",
        "updated_at": "2032-01-01T00:00:00", "version": 11,
    })
    assert tm.get_task(conn, tid).attach == []
    conn.close()
