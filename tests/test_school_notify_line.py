"""G 批 · T-G14：学校通知的**合作接口**（SR-F10.1）。

规格里这一条原写着"后置"，用户 2026-09-23「全做」——于是提前的是**接口**那半截。

规格的定位（`docs/specification/domains/F10-notify.md`）：
> 监测由**独立脚本/软件**实现；主工具只提供**合作接口**……主工具**不直接抓取**外部网站。
> 外部监测结果可通过合作接口转成任务/提醒（只读或新增，**待定**）。外部脚本不可用：
> 主工具不崩、不报错；只提示未接入。非法/重复通知：去重、来源标记。字段保持扩展位，不写死。

这一版把"待定"落成三条**不需要用户再拍板**的取舍（都能从这里看出来）：
1. **只做收件箱**：投递进来先只落在 `school_notices`（"新增"这个动作由脚本做）；
2. **转任务是你点一下才发生**（`to_task`）—— 自动把外部内容变成你的任务清单，
   那是在替你决定"什么算我的事"，属产品口径，不擅自定；
3. **默认关**（同 N16「默认收严」）：没接入时主工具什么都不做。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import notify
from timeflow.core import tasks as tm
from timeflow.storage import db as db_mod

if TYPE_CHECKING:
    import sqlite3


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "notify.db"))
    yield c
    c.close()


def _payload(**kw: object) -> dict[str, object]:
    body: dict[str, object] = {"source": "教务处网站", "title": "期中考试安排已发布"}
    body.update(kw)
    return body


# ---- 开关（默认关 = "未接入"）----

def test_default_off_is_not_a_failure(conn: sqlite3.Connection) -> None:
    """默认关：投递被拒**并带原话**，但这不是故障（不抓取、不轮询、不报错就是"未接入"）。"""
    assert notify.enabled(conn) is False
    with pytest.raises(notify.NotConnectedError, match="设置页"):
        notify.receive(conn, _payload())
    # NotConnectedError 是 ValueError 的子类：老的调用方按 ValueError 接也不会漏
    assert issubclass(notify.NotConnectedError, ValueError)


def test_switch_only_takes_booleans(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="只认 true/false"):
        notify.set_enabled(conn, "maybe")
    assert notify.set_enabled(conn, "on")["enabled"] is True
    assert notify.set_enabled(conn, "off")["enabled"] is False


# ---- 投递 + 去重 + 扩展位 ----

def test_receive_stores_notice_with_source_and_extra(conn: sqlite3.Connection) -> None:
    notify.set_enabled(conn, True)
    got = notify.receive(
        conn,
        _payload(external_id="2026-0917-01", url="https://example.edu/x",
                 summary="考场在第 3 教学楼", at="2026-09-17T09:30",
                 due_date="2026-10-08", 我加的新字段="照存不误"),
    )
    assert got["created"] is True and got["duplicate"] is False
    n = got["notice"]
    assert n["source"] == "教务处网站" and n["title"] == "期中考试安排已发布"
    assert n["at"] == "2026-09-17T09:30:00"          # 时间补秒、统一成本地时间串
    assert n["due_date"] == "2026-10-08"
    assert n["status"] == notify.STATUS_NEW and n["status_label"] == "待看"
    assert n["received_at"] and n["task_id"] is None
    # 规格：字段保持扩展位，不写死 —— 认不出来的照存
    assert n["extra"] == {"我加的新字段": "照存不误"}


def test_duplicate_posts_update_the_same_row_only_with_what_was_sent(
    conn: sqlite3.Connection,
) -> None:
    """**去重靠数据库的指纹唯一索引**，不靠脚本自觉；重复投递只覆盖"这次真的带了"的字段。

    为什么强调后半句：脚本再投一次只带标题（很常见），若把链接/摘要/截止日一并写成空，
    那是**数据丢失**而不是更新。
    """
    notify.set_enabled(conn, True)
    first = notify.receive(conn, _payload(external_id="A-1", url="https://example.edu/x",
                                         due_date="2026-10-08", 来源批次="第 1 批"))
    again = notify.receive(conn, _payload(external_id="A-1", title="期中考试安排（改）",
                                         来源批次="第 2 批"))
    assert again["duplicate"] is True and again["updated"] is True
    assert again["id"] == first["id"]                    # 同一行，不是新增
    n = again["notice"]
    assert n["title"] == "期中考试安排（改）"
    assert n["url"] == "https://example.edu/x" and n["due_date"] == "2026-10-08"  # 没被抹掉
    assert n["extra"] == {"来源批次": "第 2 批"}           # extra 是合并，不是替换
    same = notify.receive(conn, _payload(external_id="A-1", title="期中考试安排（改）"))
    assert same["duplicate"] is True and same["updated"] is False   # 一模一样 → 什么都不做
    assert len(notify.notices(conn)) == 1


def test_dedupe_without_external_id_uses_source_title_and_time(conn: sqlite3.Connection) -> None:
    notify.set_enabled(conn, True)
    notify.receive(conn, _payload(at="2026-09-17"))
    notify.receive(conn, _payload(at="2026-09-17"))            # 同来源同标题同时间 → 同一条
    notify.receive(conn, _payload(at="2026-09-18"))            # 时间不同 → 另一条
    notify.receive(conn, _payload(source="班级群", at="2026-09-17"))   # 来源不同 → 另一条
    assert len(notify.notices(conn)) == 3


def test_bad_payloads_are_refused_with_words(conn: sqlite3.Connection) -> None:
    notify.set_enabled(conn, True)
    bad_payloads: list[tuple[dict[str, object], str]] = [
        ({"title": "只有标题"}, "source"),
        ({"source": "教务处"}, "title"),
        ({"source": "教务处", "title": "  "}, "title"),
        ({"source": "教务处", "title": "x", "at": "9月17日"}, "at"),
        ({"source": "教务处", "title": "x", "at": "2026-09-17T25:00"}, "at"),
        ({"source": "教务处", "title": "x", "due_date": "2026-13-40"}, "due_date"),
        ({"source": "教务处", "title": "x", "url": "ftp://example.edu"}, "url"),
        ({"source": "教务处", "title": "y" * 400}, "title"),
    ]
    for body, why in bad_payloads:
        with pytest.raises(ValueError, match=why):
            notify.receive(conn, body)
    assert notify.notices(conn) == []          # 一条都没落库（不静默塞半条）


# ---- 转任务（人点一下才发生）----

def test_to_task_walks_the_normal_task_path(conn: sqlite3.Connection) -> None:
    notify.set_enabled(conn, True)
    nid = notify.receive(conn, _payload(external_id="A-2", url="https://example.edu/x",
                                        summary="考场见通知", at="2026-09-17T09:30",
                                        due_date="2026-10-08"))["id"]
    out = notify.to_task(conn, nid, is_myday=True)
    task = tm.get_task(conn, out["task_id"])
    assert out["created"] is True
    assert task.title == "期中考试安排已发布"
    assert task.due_date == "2026-10-08"                    # 通知里说了截止就用它
    assert task.is_myday is True
    assert "来自学校通知：教务处网站" in (task.note or "")   # 以后查得出这条任务从哪来
    assert "https://example.edu/x" in (task.note or "")
    assert out["notice"]["status"] == notify.STATUS_CONVERTED
    assert out["notice"]["task_id"] == task.id


def test_to_task_is_idempotent_and_survives_a_purge(conn: sqlite3.Connection) -> None:
    notify.set_enabled(conn, True)
    nid = notify.receive(conn, _payload(external_id="A-3"))["id"]
    first = notify.to_task(conn, nid)
    again = notify.to_task(conn, nid)
    assert again["created"] is False and again["task_id"] == first["task_id"]

    # 任务被彻底删掉后**允许重新转**：否则这条通知永远转不出任务了
    tm.delete_task(conn, first["task_id"])
    tm.purge_task(conn, first["task_id"])
    redone = notify.to_task(conn, nid)
    assert redone["created"] is True and redone["task_id"] != first["task_id"]


def test_to_task_can_pass_remind_and_priority(conn: sqlite3.Connection) -> None:
    notify.set_enabled(conn, True)
    nid = notify.receive(conn, _payload(external_id="A-4"))["id"]
    out = notify.to_task(conn, nid, remind_at="2026-10-07T20:00", priority="高")
    task = tm.get_task(conn, out["task_id"])
    assert task.remind_at == "2026-10-07T20:00" and task.priority == "高"
    # 非法值照样拒绝（换一条没转过的通知 —— 已转的那条走幂等分支，不再看这次传的参数）
    other = notify.receive(conn, _payload(external_id="A-4b"))["id"]
    with pytest.raises(ValueError):
        notify.to_task(conn, other, priority="超级高")
    picked = next(n for n in notify.notices(conn) if n["id"] == other)
    assert picked["status"] == notify.STATUS_NEW   # 没转成，状态没动（不静默标成已转）


def test_to_task_does_not_need_the_switch_on(conn: sqlite3.Connection) -> None:
    """开关管的是"脚本能不能投递"；**收件箱里的东西是你的数据** —— 关掉接口也该能处理。"""
    notify.set_enabled(conn, True)
    nid = notify.receive(conn, _payload(external_id="A-5"))["id"]
    notify.set_enabled(conn, False)
    out = notify.to_task(conn, nid)
    assert out["created"] is True
    assert len(notify.notices(conn)) == 1            # 关掉接口后收件箱照样看得见
    assert notify.describe(conn)["total"] == 1


# ---- 忽略 / 列表 ----

def test_ignore_is_reversible_and_refuses_converted(conn: sqlite3.Connection) -> None:
    notify.set_enabled(conn, True)
    nid = notify.receive(conn, _payload(external_id="A-6"))["id"]
    assert notify.ignore(conn, nid)["status"] == notify.STATUS_IGNORED
    assert notify.ignore(conn, nid, ignored=False)["status"] == notify.STATUS_NEW
    notify.to_task(conn, nid)
    with pytest.raises(ValueError, match="已经转成任务"):
        notify.ignore(conn, nid)


def test_notices_filter_and_limits(conn: sqlite3.Connection) -> None:
    notify.set_enabled(conn, True)
    notify.receive(conn, _payload(external_id="B-1", title="一号"))
    two = notify.receive(conn, _payload(external_id="B-2", title="二号"))["id"]
    notify.ignore(conn, two)

    assert [n["title"] for n in notify.notices(conn)] == ["二号", "一号"]   # 新的在前
    assert [n["title"] for n in notify.notices(conn, status=notify.STATUS_IGNORED)] == ["二号"]
    assert len(notify.notices(conn, limit=1)) == 1
    with pytest.raises(ValueError, match="非法状态"):
        notify.notices(conn, status="bogus")
    with pytest.raises(ValueError, match="limit"):
        notify.notices(conn, limit=0)


def test_missing_notice_is_keyerror(conn: sqlite3.Connection) -> None:
    for call in (notify.to_task, notify.ignore):
        with pytest.raises(KeyError):
            call(conn, "nope")


def test_describe_tells_the_truth(conn: sqlite3.Connection) -> None:
    notify.set_enabled(conn, True)
    notify.receive(conn, _payload(external_id="C-1"))
    d = notify.describe(conn)
    assert d["enabled"] is True and d["default_enabled"] is False and d["total"] == 1
    assert {s["value"] for s in d["statuses"]} == set(notify.STATUSES)
    assert "不去网上抓" in d["boundary"] and "点一下" in d["boundary"]
    assert "/api/notify/school" in d["example"]
    assert any(f["name"] == "source" and f["required"] for f in d["fields"])


# ---- 接口（真 HTTP 走一遍）----

def test_api_flow(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "n.db")))
    assert client.get("/api/settings/notify").json()["enabled"] is False
    # 没开 → **403**（"未接入"，不是参数错）；开了但少字段 → 400
    assert client.post("/api/notify/school", json=_payload()).status_code == 403
    assert client.put("/api/settings/notify", json={"enabled": True}).json()["enabled"] is True
    assert client.post("/api/notify/school", json={"title": "没有来源"}).status_code == 400
    assert client.put("/api/settings/notify", json={"enabled": "maybe"}).status_code == 400

    got = client.post("/api/notify/school", json=_payload(
        external_id="D-1", due_date="2026-10-08", url="https://example.edu/x")).json()
    assert got["created"] is True
    assert client.post("/api/notify/school", json=_payload(external_id="D-1")).json()[
        "duplicate"] is True

    listing = client.get("/api/notify/school").json()
    assert listing["count"] == 1 and listing["items"][0]["source"] == "教务处网站"
    assert listing["settings"]["enabled"] is True

    task = client.post(f"/api/notify/school/{got['id']}/to-task", json={"is_myday": True}).json()
    assert task["created"] is True and task["notice"]["status"] == "converted"
    assert client.get(f"/api/tasks/{task['task_id']}").json()["title"] == "期中考试安排已发布"

    assert client.post("/api/notify/school/nope/to-task").status_code == 404
    assert client.post("/api/notify/school/nope/ignore").status_code == 404
    assert client.post(f"/api/notify/school/{got['id']}/ignore").status_code == 400  # 已转任务
    assert client.get("/api/notify/school", params={"status": "bogus"}).status_code == 400


def test_api_rejects_cross_site_writes(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """跨站网页偷着投递 / 偷着开开关 —— 都拦（整组要求本机来源）。"""
    client = TestClient(create_app(str(tmp_path / "n2.db")))
    evil = {"Origin": "https://evil.example"}
    assert client.put("/api/settings/notify", json={"enabled": True},
                      headers=evil).status_code == 403
    assert client.post("/api/notify/school", json=_payload(), headers=evil).status_code == 403


# ---- 跨端 / 迁移 ----

def test_school_notices_stay_local_by_design(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """**这一版不跨端**（写在这里免得以后当成漏了）：通知是外部脚本送进来的收件箱，
    不是你自己写的东西；转成**任务**之后，任务本身照常跨端。"""
    from timeflow.core import syncpack

    client = TestClient(create_app(str(tmp_path / "n3.db")))
    client.put("/api/settings/notify", json={"enabled": True})
    client.post("/api/notify/school", json=_payload(external_id="E-1"))
    pack = client.post("/api/sync/export", json={}).json()
    assert "school_notices" not in pack["tables"]
    assert "school_notices" in syncpack.EXCLUDED_TABLES


def test_schema_v18_creates_the_inbox(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """新库与"老库升上来"都要有这张表（结构补齐那条不变式的一部分）。"""
    conn = db_mod.connect(str(tmp_path / "v18.db"))
    cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(school_notices)")}
    assert {"id", "source", "fingerprint", "title", "at", "due_date", "received_at",
            "status", "task_id", "extra", "updated_at"} <= cols
    assert int(conn.execute("SELECT version FROM schema_version").fetchone()["version"]) == (
        db_mod.SCHEMA_VERSION
    )
    conn.close()
