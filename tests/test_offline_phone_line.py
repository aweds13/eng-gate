"""手机离线记（G 批 · T-G10 / SR-NF17 / 跨端场景 ①）。

**为什么这样测**：手机侧是 JS + IndexedDB，而本环境**跑不了浏览器**。
但"造包"那一段在 `src/web/offline.js` 里是**纯函数** —— 于是这里用 `node` 跑**页面用的同一个文件**
造出一份真包（`tools/phone_check.mjs`），再在这边**真导入**一次，逐条验：
任务/习惯/备忘/反馈真的落地、账本真的算对、重复导入不重复、导入不删本地东西、冲突真的留痕。

这样测的价值：它拦的是"手机造出的包电脑吃不下 / 吃下了但账目不对"这类**只有跨端才出现**的错，
而不是"某个字符串在文件里"（那是前端护栏那一层的事）。

覆盖面之外（做不到的，如实写在这里）：真实浏览器里的 IndexedDB 读写、下载文件、
DevTools 离线模式下的界面表现 —— 只能在用户机器上点（见 `复盘/手机离线记-T-G10.md` §五）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from timeflow.core import attach as attach_mod
from timeflow.core import facts as facts_mod
from timeflow.core import sync as sync_mod
from timeflow.core import syncpack
from timeflow.core.ledger import ledger
from timeflow.storage import db as db_mod

ROOT = Path(__file__).resolve().parent.parent
PHONE_CHECK = ROOT / "tools" / "phone_check.mjs"
OFFLINE_JS = ROOT / "src" / "web" / "offline.js"

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="环境没有 node，无法真跑手机侧的造包代码")

DAY = "2026-09-23"
AT = "2026-09-23T20:15:00"
CACHED_ID = "phonecheck-cached"


@pytest.fixture(scope="module")
def phone(tmp_path_factory):  # type: ignore[no-untyped-def]
    """跑一次 node，拿回"手机上记完、导出的一份包"（含清单：里面用了哪些 id）。"""
    out = tmp_path_factory.mktemp("phone")
    pack = out / "phone.json"
    manifest = out / "manifest.json"
    proc = subprocess.run(
        [str(NODE), str(PHONE_CHECK), str(pack), str(manifest)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, cwd=str(ROOT),
    )
    assert proc.returncode == 0, f"手机侧自检没过：{proc.stdout}\n{proc.stderr}"
    return {"pack": json.loads(pack.read_text(encoding="utf-8")),
            "manifest": json.loads(manifest.read_text(encoding="utf-8"))}


@pytest.fixture(scope="module")
def phone_undo(tmp_path_factory):  # type: ignore[no-untyped-def]
    """同一份东西，但手机上是**撤销完成**（`--undo`）。"""
    out = tmp_path_factory.mktemp("phone_undo")
    pack = out / "phone.json"
    manifest = out / "manifest.json"
    proc = subprocess.run(
        [str(NODE), str(PHONE_CHECK), str(pack), str(manifest), "--undo"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, cwd=str(ROOT),
    )
    assert proc.returncode == 0, f"手机侧自检没过（--undo）：{proc.stdout}\n{proc.stderr}"
    return json.loads(pack.read_text(encoding="utf-8"))


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "phone.db"))
    facts_mod.clear()
    yield c
    c.close()
    facts_mod.clear()


def _seed_cached_task(conn, status: str = "未开始") -> None:  # type: ignore[no-untyped-def]
    """手机上**缓存里那条任务**在电脑上的样子（id / version / 备注 / 附件都要对得上）。"""
    conn.execute(
        "INSERT INTO tasks (id, title, due_date, group_name, repeat_days, parent_id, is_myday,"
        " status, created_at, updated_at, version, note, priority, flagged, attach, remind_at,"
        " task_type, course_id, doing_rank, created_by)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (CACHED_ID, "缓存里的任务", None, None, None, None, 1, status,
         "2026-09-22T09:00:00", "2026-09-22T09:00:00", 3, "电脑上写的备注", "高", 0,
         attach_mod.dump_attach([{"target": "D:/课件/第3章.pdf", "title": "课件"}]),
         None, "普通", None, None, "me"),
    )
    conn.commit()


def _task(conn, task_id: str):  # type: ignore[no-untyped-def]
    return conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()


def _columns(conn, table: str) -> set[str]:  # type: ignore[no-untyped-def]
    return {str(r["name"]) for r in conn.execute(f"PRAGMA table_info({table})")}


# ---------------------------------------------------------------- 包本身
def test_phone_pack_is_accepted_by_the_desktop_check(phone) -> None:  # type: ignore[no-untyped-def]
    """手机包必须**过得了电脑侧的校验**（format / format_version / tables 三关）。"""
    pack = syncpack.check_pack(phone["pack"])
    assert pack["format"] == syncpack.FORMAT
    assert pack["format_version"] == syncpack.FORMAT_VERSION <= syncpack.FORMAT_VERSION
    assert pack["device_id"].startswith("ph-"), "手机设备号要有 ph- 前缀（与电脑一眼分得开）"
    assert pack["tables"] and "tombstones" in pack
    counts = phone["manifest"]["counts"]
    for table, n in counts.items():
        assert len(pack["tables"][table]) == n, f"{table} 的行数与 counts 不符"


def test_phone_rows_only_use_columns_that_exist_locally(conn, phone) -> None:  # type: ignore[no-untyped-def]
    """**这一条最要紧**：手机包里每一行只能用电脑库里真有的列。

    `TaskOut` 带着一堆派生字段（groups / overdue_days / course_name …），
    手机要是照原样塞进包里，就是给电脑塞它没有的列。护栏两头对账：
    ① 包里实际出现的键 ⊆ 手机侧声明的白名单；② 那份白名单 ⊆ 真库的 `PRAGMA table_info`。
    """
    fields = phone["manifest"]["fields"]
    for table, rows in phone["pack"]["tables"].items():
        real = _columns(conn, table)
        assert real, f"电脑库里没有 {table} 这张表"
        extra = set(fields[table]) - real
        assert not extra, f"{table} 的白名单里有库里没有的列：{extra}"
        for row in rows:
            assert set(row) <= real, f"{table} 的行里有库里没有的列：{set(row) - real}"
    assert "app_settings" not in phone["pack"]["tables"], "本机设置不该跟着手机包走"


def test_phone_primary_key_map_matches_the_desktop(phone) -> None:  # type: ignore[no-untyped-def]
    """两边的主键口径必须一致（不一致 → 同一条会被当成两条）。"""
    declared = phone["manifest"]["primary_keys"]
    for table, keys in declared.items():
        assert tuple(keys) == syncpack.PRIMARY_KEYS[table], f"{table} 的主键口径两边不一样"


# ---------------------------------------------------------------- 真导入
def test_a_phone_completion_lands_and_the_ledger_counts_it(conn, phone) -> None:  # type: ignore[no-untyped-def]
    """手机上勾了完成 → 电脑那边任务变完成、事实落地、**账本的「完成收益」真的 +1**。"""
    _seed_cached_task(conn)
    report = syncpack.merge_pack(conn, phone["pack"])
    assert report.inserted > 0

    row = _task(conn, CACHED_ID)
    assert row["status"] == "完成"
    assert row["version"] == 4, "version 要比电脑上的 3 大（LWW 优先比 version）"
    assert row["updated_at"] == AT

    fact = conn.execute(
        "SELECT * FROM facts WHERE subject_id = ?", (CACHED_ID,)
    ).fetchone()
    assert fact is not None and fact["kind"] == "task.completed"
    assert fact["source"] == "phone", "手机做的事要如实标来源"
    assert fact["occurred_at"] == AT, "发生时间要用**手机上那一刻**（不是导入那一刻）"
    assert json.loads(fact["extra"])["completed_on"] == DAY

    summary = ledger.summary(conn, DAY)
    assert summary.gain_count == 1, "完成收益要算上手机那条"
    done = ledger.today_done(conn, DAY)
    assert any(t.title == "缓存里的任务" for t in done.tasks)


def test_a_phone_undo_takes_the_gain_back(conn, phone_undo) -> None:  # type: ignore[no-untyped-def]
    """手机上撤销完成 → 电脑那边状态回退、`task.uncompleted` 落地、**收益不算**（撤销照扣）。"""
    _seed_cached_task(conn, status="完成")
    syncpack.merge_pack(conn, phone_undo)
    row = _task(conn, CACHED_ID)
    assert row["status"] == "未开始"
    kinds = {r["kind"] for r in conn.execute(
        "SELECT kind FROM facts WHERE subject_id = ?", (CACHED_ID,))}
    assert "task.uncompleted" in kinds
    assert ledger.summary(conn, DAY).gain_count == 0


def test_new_offline_records_all_land(conn, phone) -> None:  # type: ignore[no-untyped-def]
    """手机上新记的东西（任务 / 习惯 / 备忘 / 反馈）一条不落，字段也没走样。"""
    syncpack.merge_pack(conn, phone["pack"])
    m = phone["manifest"]

    task = _task(conn, m["new_task_id"])
    assert task is not None and task["title"] == "手机上记的"
    assert task["due_date"] == "2026-09-30" and task["is_myday"] == 1
    assert task["priority"] == "高" and task["note"] == "离线记的"
    assert task["created_by"] == "me", "你亲手记的，不是 AI 建的"
    assert task["status"] == "未开始" and task["version"] == 1

    habit = conn.execute(
        "SELECT * FROM habit_logs WHERE habit_id = ? AND date = ?", (m["habit_id"], DAY)
    ).fetchone()
    assert habit is not None and habit["done"] == 1

    memo = conn.execute("SELECT * FROM memos WHERE id = ?", (m["memo_id"],)).fetchone()
    assert memo is not None and memo["text"] == "路上想到的一件事"

    fb = conn.execute("SELECT * FROM feedback_logs WHERE date = ?", (DAY,)).fetchone()
    assert fb is not None
    assert fb["plan_note"] == "把第三章看完" and fb["gap_note"] == "卡在第 4 题"
    # 手机上只改了那两句：电脑那边已有的字段（executed / focus_minutes）不能被抹掉
    assert fb["executed"] == "看完了第一节"
    assert fb["focus_minutes"] == 25


def test_attach_from_the_phone_means_the_same_list(conn, phone) -> None:  # type: ignore[no-untyped-def]
    """附件在库里是 JSON 文本、在接口上是列表 —— 手机转过去的那一份必须**读回来还是同一批**。"""
    _seed_cached_task(conn)
    syncpack.merge_pack(conn, phone["pack"])
    row = _task(conn, CACHED_ID)
    got = attach_mod.load_attach(row["attach"])
    assert got == [{"target": "D:/课件/第3章.pdf", "title": "课件"}]


def test_importing_the_phone_pack_twice_changes_nothing(conn, phone) -> None:  # type: ignore[no-untyped-def]
    """重复导入是安全的（导出不清空手机队列，用户可能导两次）——第二次一行都不该动。"""
    _seed_cached_task(conn)
    first = syncpack.merge_pack(conn, phone["pack"])
    assert first.inserted > 0
    second = syncpack.merge_pack(conn, phone["pack"])
    assert second.inserted == 0 and second.updated == 0
    assert second.kept > 0
    assert ledger.summary(conn, DAY).gain_count == 1, "导两次不能算两笔收益"


def test_phone_import_does_not_touch_machine_settings(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """「同步的是你的数据，不同步的是这台机器的事」（T-G8 立的规矩）在手机包上同样成立。"""
    c = db_mod.connect(str(tmp_path / "machine.db"))
    facts_mod.clear()
    try:
        for key, value in (("export.dir", "D:/我的导出目录"), ("ai.enabled", "true")):
            c.execute(
                "INSERT INTO app_settings (key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
        c.commit()
        subprocess.run([str(NODE), str(PHONE_CHECK), str(tmp_path / "p.json")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=120, cwd=str(ROOT), check=True)
        pack = json.loads((tmp_path / "p.json").read_text(encoding="utf-8"))
        syncpack.merge_pack(c, pack)
        got = {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM app_settings")}
        assert got["export.dir"] == "D:/我的导出目录"
        assert got["ai.enabled"] == "true"
    finally:
        c.close()
        facts_mod.clear()


def test_phone_import_never_deletes_local_rows(conn, phone) -> None:  # type: ignore[no-untyped-def]
    """导入不删电脑上的东西（v1 边界）：一条本地任务 + 一条墓碑都还在。"""
    from timeflow.core import tasks as tm

    keep = tm.create_task(conn, "电脑上好好的", is_myday=True)
    conn.execute(
        "INSERT INTO sync_tombstones (entity, entity_id, deleted_at) VALUES (?,?,?)",
        ("tasks", "some-old-thing", "2026-09-20T10:00:00"),
    )
    conn.commit()
    syncpack.merge_pack(conn, phone["pack"])
    assert _task(conn, keep.id) is not None
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM sync_tombstones WHERE entity_id = ?", ("some-old-thing",)
    ).fetchone()["n"] == 1


def test_overwrites_are_logged_not_silent(conn, phone) -> None:  # type: ignore[no-untyped-def]
    """手机覆盖了电脑上的一条任务 → 必须留痕（谁新谁旧、差在哪），不静默。"""
    _seed_cached_task(conn)
    syncpack.merge_pack(conn, phone["pack"])
    logs = conn.execute(
        "SELECT * FROM sync_logs WHERE entity = 'tasks' AND entity_id = ?", (CACHED_ID,)
    ).fetchall()
    assert logs, "覆盖了却没记冲突日志"
    assert any("覆盖" in str(r["result"]) for r in logs)
    assert any("status" in str(r["note"]) for r in logs), "日志要说清差在哪"


def test_phone_device_id_can_never_collide_with_the_desktop(conn, phone) -> None:  # type: ignore[no-untyped-def]
    """设备号不能撞车：自己的包会被电脑拒掉，手机包必须不是"自己导给自己"。"""
    desktop = syncpack.device_id(conn)
    assert desktop != phone["pack"]["device_id"]
    assert len(desktop) == 12 and "ph-" not in desktop
    # 反向验一次：把设备号改成电脑自己的 → 电脑必须拒绝（这条逻辑在合并前就该拦住）
    same = dict(phone["pack"], device_id=desktop)
    with pytest.raises(ValueError, match="自己导给自己"):
        syncpack.plan_merge(conn, same)


def test_status_reports_file_sync_without_pretending_about_network(conn, phone) -> None:  # type: ignore[no-untyped-def]
    """导入之后状态如实：文件同步可用、网络同步还没做（② 未落地），且上次导入来自手机。"""
    syncpack.merge_pack(conn, phone["pack"])
    st = syncpack.status(conn)
    assert st["file_sync"] is True and st["network_sync"] is False
    assert st["last_import"]["from_device"] == phone["pack"]["device_id"]
    # 兼容面（旧接口）也仍然指着同一件事
    old = sync_mod.status(conn)
    assert old["conflict_logs"] == st["conflict_logs"]


def test_offline_engine_is_shipped_where_the_page_can_get_it(conn, phone) -> None:  # type: ignore[no-untyped-def]
    """手机侧的代码要在仓库里、能被页面取到（别只在自检里存在）。"""
    assert OFFLINE_JS.is_file()
    text = OFFLINE_JS.read_text(encoding="utf-8")
    assert "TFOffline" in text and "timeflow-sync" in text
    for marker in ("indexedDB", "putCache", "clearQueue"):
        assert marker in text
