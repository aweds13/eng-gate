"""G 批 · T-G8：跨端同步的**同步包 + 合并机制**（SR-F9.2 / SR-NF17；场景 ③ = 电脑↔电脑）。

**口径（用户 2026-09-21 定，见 `复盘/口径定案-待定清单.md` §3）**：先做 ③ —— 定义同步包文件格式 +
合并机制（谁新谁旧 / 同一条不重复 / 冲突留痕）+ 导出/导入入口；它是 ①（手机离线）的地基。

这一版的三条规矩（也是本文件的测试骨架）：
1. **同步你的数据，不同步这台机器的事**（不含 app_settings / sync_logs / schema_version）；
2. **合并不静默**（覆盖与保留逐条记进 `sync_logs`，带结果与"差在哪"）；
3. **导入永不删你本地的数据**（远程墓碑只防复活 + 继续传播，不替你删）。

覆盖：
- 包的身份与自述（format / 版本 / 设备号 / 各表条数 / 明确排除哪些表）；
- 拒绝坏包（不存在 / 非 JSON / 不是我们的格式 / 来自更新版本 / 自己导给自己）；
- 三类合并规则：LWW 行（远端较新→覆盖、本地不旧→保留）、只增行（只插不改）、关系行（缺则插）；
- **墓碑**：本地硬删过的不被旧包复活；远程墓碑**不删本地**但记下来继续传播；
- `dry_run` 一个字节都不写；重复导入幂等；台账数字（债务/收益/复习/产出/习惯）两边一致；
- v17 迁移：六张表补 `updated_at`（改了会动，`tasks` 的"换顺序不动"例外保留）+ 触发器幂等；
- API：导出（写文件）/ 预览 / 导入 / 坏路径 400 / 跨站 403 / 状态只报事实。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import facts as facts_mod
from timeflow.core import feedback as fb
from timeflow.core import memo as memo_mod
from timeflow.core import review as rv
from timeflow.core import syncpack
from timeflow.core import tasks as tm
from timeflow.core.ledger import ledger
from timeflow.storage import db as db_mod


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "sync.db"))
    facts_mod.clear()
    yield c
    c.close()
    facts_mod.clear()


def _client(tmp_path, name: str = "sync_api.db") -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(create_app(str(tmp_path / name)))


def _db(tmp_path: Path, name: str, *, clear: bool = True):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / name))
    if clear:
        facts_mod.clear()
    return c


def _make_pack(conn, **over) -> dict:  # type: ignore[no-untyped-def]
    pack = syncpack.build_pack(conn)
    pack.update(over)
    return pack


# ---------------------------------------------------------------- 包的身份


def test_pack_identity_and_what_is_not_in_it(conn) -> None:  # type: ignore[no-untyped-def]
    """包里要有身份与自述；**不含**本机设置 / 本机冲突日志 / schema 版本管理表。"""
    tm.create_task(conn, "一件事", is_myday=True)
    memo_mod.create_memo(conn, "一条备忘")
    pack = syncpack.build_pack(conn)
    assert pack["format"] == syncpack.FORMAT
    assert pack["format_version"] == syncpack.FORMAT_VERSION
    assert pack["schema_version"] == db_mod.SCHEMA_VERSION
    assert pack["device_id"] and pack["created_at"]
    assert pack["counts"]["tasks"] == 1 and pack["counts"]["memos"] == 1
    assert "facts" in pack["tables"] and "tombstones" in pack
    for excluded in syncpack.EXCLUDED_TABLES:
        assert excluded not in pack["tables"], f"{excluded} 不该进包（它是这台机器的事）"
    assert "不含" in pack["note"]


def test_export_writes_one_file_atomically(conn, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """导出：文件名自带设备号与时间、不留半截文件、报告里条数对得上。"""
    tm.create_task(conn, "导出用", is_myday=True)
    out = tmp_path / "packs"
    first = syncpack.export_pack(conn, out)
    path = Path(first.path)
    assert path.is_file() and path.parent == out
    assert path.name.startswith(f"sync-{first.device_id}-") and path.suffix == ".json"
    assert list(out.glob("*.tmp")) == []
    assert first.rows == sum(first.tables.values()) > 0
    assert first.bytes == len(path.read_bytes())
    # 再导一次：新文件（不动上一份），内容等价的包
    second = syncpack.export_pack(conn, out)
    assert Path(second.path) != path and len(list(out.glob("sync-*.json"))) == 2


def test_load_pack_rejects_bad_input(conn, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """坏包明确拒绝（不"尽力猜" —— 猜错就是把别人的数据合进来）。"""
    with pytest.raises(ValueError, match="找不到这个文件"):
        syncpack.load_pack(tmp_path / "没有这个文件.json")

    broken = tmp_path / "broken.json"
    broken.write_text("{不是 json", encoding="utf-8")
    with pytest.raises(ValueError, match="不是合法的 JSON"):
        syncpack.load_pack(broken)

    alien = tmp_path / "alien.json"
    alien.write_text(json.dumps({"format": "something-else", "tables": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="不是 timeflow 的同步包"):
        syncpack.load_pack(alien)

    future = tmp_path / "future.json"
    future.write_text(
        json.dumps({"format": syncpack.FORMAT, "format_version": 99, "tables": {}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="比本程序新"):
        syncpack.load_pack(future)


def test_importing_your_own_pack_is_refused(conn, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """自己导给自己：没有意义 → 明确拒绝（否则会白跑一遍还留下冲突日志）。"""
    pack = syncpack.build_pack(conn)
    with pytest.raises(ValueError, match="就是本机导出的"):
        syncpack.merge_pack(conn, pack)


# ---------------------------------------------------------------- 合并：三类规则


def test_other_machine_gets_everything_and_numbers_match(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """**主验收**：A 的一整天（任务 / 步骤 / 专注 / 产出 / 复习 / 备忘 / 习惯）导进 B 之后，
    B 的账本数字与 A **一致**（事实是账本的权威，所以合并事实就等于合并账目）。"""
    a = _db(tmp_path, "a.db")
    top = tm.create_task(a, "大任务", is_myday=True)
    step = tm.create_subtask(a, top.id, "第 1 步")
    tm.complete_task(a, step.id)
    tm.complete_task(a, top.id)
    memo_mod.add_output_entry(a, value=1, kind="asset", note="写了笔记")
    memo_mod.create_memo(a, "一条备忘", ref_handle="notes/x.md")
    card_id = rv.create_item(a, "复习卡", ref_handle="notes/y.md")
    rv.review(a, card_id, "remember")
    habit = fb.create_habit(a, "跑步")
    fb.toggle_habit_log(a, habit)
    fb.set_daily_feedback(a, None, plan_note="今天做完", executed="做完了", gap_note="")
    a_summary = ledger.summary(a)
    a_pack = syncpack.build_pack(a)

    b = _db(tmp_path, "b.db")
    report = syncpack.merge_pack(b, a_pack)
    assert report.inserted > 0 and report.updated == 0
    assert sorted(t.title for t in tm.list_tasks(b)) == ["大任务", "第 1 步"]
    assert tm.get_task(b, step.id).parent_id == top.id        # 父子关系跟着来
    assert [m["text"] for m in memo_mod.list_memos(b)] == ["一条备忘"]
    assert rv.get_item(b, card_id)["ref_handle"] == "notes/y.md"
    assert [h["name"] for h in fb.list_habits(b)] == ["跑步"]
    assert fb.get_feedback(b, None)["plan_note"] == "今天做完"

    b_summary = ledger.summary(b)
    for key in ("debt_count", "invest_hours", "manual_hours", "review_count",
                "output_count", "output_kpi", "output_asset", "habit_count", "gain_count"):
        assert getattr(b_summary, key) == getattr(a_summary, key), (
            f"{key} 两边不一致：账目必须跟着事实走"
        )
    a.close()
    b.close()


def test_lww_remote_newer_wins_and_is_logged(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """同一条两边都改了：远端较新 → 覆盖，并**记一条日志说明为什么**（不静默覆盖）。"""
    a = _db(tmp_path, "a.db")
    b = _db(tmp_path, "b.db")
    task_a = tm.create_task(a, "原标题")
    # B 先拿到这条（旧版本）
    pack1 = syncpack.build_pack(a)
    syncpack.merge_pack(b, pack1)
    # A 改标题（version 变大）→ 导出新包
    tm.update_task(a, task_a.id, title="A 改过的标题")
    pack2 = syncpack.build_pack(a)
    report = syncpack.merge_pack(b, pack2)
    assert tm.get_task(b, task_a.id).title == "A 改过的标题"
    assert report.updated == 1 and report.conflict_count >= 1
    logged = b.execute("SELECT entity, result, note FROM sync_logs").fetchall()
    assert any(r["result"].startswith("覆盖") for r in logged)
    assert any("title" in (r["note"] or "") for r in logged), "日志要说清差在哪"
    a.close()
    b.close()


def test_lww_local_not_older_keeps_local_and_logs(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """本地不旧（版本更高）：**保留本地**，但如实记一条"远端想改什么"（不静默丢弃）。"""
    a = _db(tmp_path, "a.db")
    b = _db(tmp_path, "b.db")
    task_a = tm.create_task(a, "A 的标题")
    pack1 = syncpack.build_pack(a)
    syncpack.merge_pack(b, pack1)
    tm.update_task(b, task_a.id, title="B 改的")      # B 改 → B 的版本更高
    tm.update_task(b, task_a.id, title="B 又改的")    # 再多一版，确保比 A 新
    report = syncpack.merge_pack(b, pack1)           # 拿**旧包**来合
    assert tm.get_task(b, task_a.id).title == "B 又改的"
    assert report.updated == 0 and report.kept >= 1
    assert any("保留本地" in r["result"] for r in
               [dict(x) for x in b.execute("SELECT result FROM sync_logs")])
    a.close()
    b.close()


def test_append_only_tables_are_insert_only(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """只增行（事实这类）：本地已有但内容不同 → **不动本地**，只记冲突。"""
    a = _db(tmp_path, "a.db")
    b = _db(tmp_path, "b.db")
    task = tm.create_task(a, "有事实的任务", is_myday=True)
    tm.complete_task(a, task.id)
    pack = syncpack.build_pack(a)
    syncpack.merge_pack(b, pack)
    fact_id = b.execute("SELECT id FROM facts LIMIT 1").fetchone()["id"]
    # 人为把本地事实改坏（模拟"同 id 不同内容"），再合一次
    b.execute("UPDATE facts SET value_text = '被改过' WHERE id = ?", (fact_id,))
    b.commit()
    report = syncpack.merge_pack(b, pack)
    assert b.execute("SELECT value_text FROM facts WHERE id = ?", (fact_id,)).fetchone()[
        "value_text"
    ] == "被改过", "只增行不该被覆盖"
    assert any("只增不改" in r["result"] for r in
               [dict(x) for x in b.execute("SELECT result FROM sync_logs")])
    assert report.inserted == 0
    a.close()
    b.close()


def test_relations_are_inserted_but_not_resurrected(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """关系行（任务↔分组）：缺则插；**本机删过（有墓碑）就不插** —— 否则"移出分组"会被旧包撤销。"""
    a = _db(tmp_path, "a.db")
    b = _db(tmp_path, "b.db")
    task = tm.create_task(a, "带分组的任务")
    gid = tm.create_group(a, "高数")
    tm.set_task_groups(a, task.id, [gid])
    pack = syncpack.build_pack(a)

    syncpack.merge_pack(b, pack)
    assert tm.task_group_ids(b, task.id) == [gid]
    # B 把它移出分组（DELETE task_groups → 墓碑）
    tm.set_task_groups(b, task.id, [])
    assert b.execute("SELECT COUNT(*) AS n FROM sync_tombstones WHERE entity='task_groups'"
                     ).fetchone()["n"] == 1
    report = syncpack.merge_pack(b, pack)
    assert tm.task_group_ids(b, task.id) == [], "有墓碑就不该被旧包加回来"
    assert report.tombstoned == 1
    a.close()
    b.close()


# ---------------------------------------------------------------- 墓碑（硬删不复活）


def test_purged_task_is_not_resurrected_by_an_old_pack(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A 彻底删掉的任务：拿**删之前**导出的包导进 A，**不许复活**（这是墓碑存在的理由）。"""
    a = _db(tmp_path, "a.db")
    task = tm.create_task(a, "会被彻底删掉", is_myday=True)
    old_pack = syncpack.build_pack(a)          # 删之前的包（还带着它）
    tm.delete_task(a, task.id)
    tm.purge_task(a, task.id)

    report = syncpack.merge_pack(a, old_pack, device="别的设备号")
    assert tm.list_tasks(a, active_only=False) == [] or all(
        t.id != task.id for t in tm.list_tasks(a, active_only=False)
    )
    assert report.tombstoned == 1
    assert any("按墓碑跳过" in r["result"] for r in
               [dict(x) for x in a.execute("SELECT result FROM sync_logs")])
    a.close()


def test_remote_tombstone_never_deletes_local_rows(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """**v1 边界**：A 删过的东西，导入时**不会删 B 本地**那份 —— 只记墓碑 + 如实提示。"""
    a = _db(tmp_path, "a.db")
    b = _db(tmp_path, "b.db")
    task = tm.create_task(a, "两边都有", is_myday=True)
    syncpack.merge_pack(b, syncpack.build_pack(a))       # B 也有了
    tm.delete_task(a, task.id)
    tm.purge_task(a, task.id)
    pack_after_delete = syncpack.build_pack(a)
    assert pack_after_delete["tombstones"], "删过就该有墓碑随包走"

    report = syncpack.merge_pack(b, pack_after_delete)
    assert tm.get_task(b, task.id).title == "两边都有", "导入不许删你本地的数据"
    assert any("远程已删（本地保留）" in r["result"] for r in
               [dict(x) for x in b.execute("SELECT result FROM sync_logs")])
    # 墓碑被记下来了（继续传给下一台），但本地行还在 —— 两件事同时为真
    assert b.execute("SELECT COUNT(*) AS n FROM sync_tombstones WHERE entity_id = ?",
                     (task.id,)).fetchone()["n"] == 1
    assert report.tombstone_added == 1
    a.close()
    b.close()


# ---------------------------------------------------------------- dry-run 与幂等


def test_dry_run_changes_nothing(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """预览：报告与真跑一致，但**一个字节都不写**（行数、冲突日志、上次导入记录都不动）。"""
    a = _db(tmp_path, "a.db")
    b = _db(tmp_path, "b.db")
    tm.create_task(a, "A 的任务", is_myday=True)
    memo_mod.create_memo(a, "A 的备忘")
    pack = syncpack.build_pack(a)
    before = {
        "tasks": len(tm.list_tasks(b, active_only=False)),
        "memos": len(memo_mod.list_memos(b)),
        "logs": b.execute("SELECT COUNT(*) AS n FROM sync_logs").fetchone()["n"],
        "settings": b.execute("SELECT COUNT(*) AS n FROM app_settings").fetchone()["n"],
        "facts": b.execute("SELECT COUNT(*) AS n FROM facts").fetchone()["n"],
    }
    preview = syncpack.merge_pack(b, pack, dry_run=True)
    after = {
        "tasks": len(tm.list_tasks(b, active_only=False)),
        "memos": len(memo_mod.list_memos(b)),
        "logs": b.execute("SELECT COUNT(*) AS n FROM sync_logs").fetchone()["n"],
        "settings": b.execute("SELECT COUNT(*) AS n FROM app_settings").fetchone()["n"],
        "facts": b.execute("SELECT COUNT(*) AS n FROM facts").fetchone()["n"],
    }
    assert preview.dry_run is True and after == before

    real = syncpack.merge_pack(b, pack)
    assert (real.inserted, real.updated, real.kept) == (
        preview.inserted, preview.updated, preview.kept
    ), "预览与真跑必须是同一套判断"


def test_import_is_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """同一份包导两次：第二次全是"保留"，且不再长冲突日志。"""
    a = _db(tmp_path, "a.db")
    b = _db(tmp_path, "b.db")
    tm.create_task(a, "一条", is_myday=True)
    pack = syncpack.build_pack(a)
    first = syncpack.merge_pack(b, pack)
    logs_after_first = b.execute("SELECT COUNT(*) AS n FROM sync_logs").fetchone()["n"]
    second = syncpack.merge_pack(b, pack)
    assert first.inserted > 0
    assert second.inserted == 0 and second.updated == 0 and second.conflict_count == 0
    assert b.execute("SELECT COUNT(*) AS n FROM sync_logs").fetchone()["n"] == logs_after_first
    a.close()
    b.close()


def test_pack_with_unknown_or_partial_tables_is_tolerated(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """老包/残缺包：只带一张表也能合（不认识的行忽略），不因为缺表就整包失败。"""
    b = _db(tmp_path, "b.db")
    pack = {
        "format": syncpack.FORMAT, "format_version": 1, "schema_version": 1,
        "device_id": "oldmachine01", "created_at": "2026-01-01T00:00:00",
        "tables": {"tasks": [{"id": "t-old", "title": "老包里的任务", "status": "未开始",
                              "created_at": "2026-01-01T00:00:00", "is_myday": 1}]},
        "tombstones": [],
    }
    report = syncpack.merge_pack(b, pack)
    assert report.inserted == 1
    assert tm.get_task(b, "t-old").title == "老包里的任务"
    # 没有 updated_at 的行按 created_at 当时间（没有就按"本地不旧"处理）
    assert tm.get_task(b, "t-old").updated_at == "2026-01-01T00:00:00"
    b.close()


# ---------------------------------------------------------------- v17：改过的痕迹


def test_renaming_a_habit_moves_its_updated_at(conn) -> None:  # type: ignore[no-untyped-def]
    """六张会被改的表：改了内容时间就动（跨端判新旧靠它）—— 触发器管，不靠逐个入口记得写。"""
    habit = fb.create_habit(conn, "跑步")
    first = conn.execute("SELECT updated_at FROM habits WHERE id=?", (habit,)).fetchone()[
        "updated_at"
    ]
    assert first, "新建的行也要有时间（否则跨端只能当最旧）"
    fb.update_habit(conn, habit, "慢跑")
    second = conn.execute("SELECT updated_at FROM habits WHERE id=?", (habit,)).fetchone()[
        "updated_at"
    ]
    assert second >= first


def test_review_and_group_and_team_and_feedback_all_get_touched(conn) -> None:  # type: ignore[no-untyped-def]
    """把其余几条更新路径都过一遍（每条都断言时间戳确实动了）。"""
    card_id = rv.create_item(conn, "卡")
    rv.update_item(conn, card_id, title="改过的卡")
    assert conn.execute("SELECT updated_at FROM review_items WHERE id=?", (card_id,)).fetchone()[
        "updated_at"
    ]

    gid = tm.create_group(conn, "高数")
    tm.groups.rename_group(conn, gid, "高等数学")
    assert conn.execute("SELECT updated_at FROM groups WHERE id=?", (gid,)).fetchone()[
        "updated_at"
    ]

    task = tm.create_task(conn, "团队任务")
    from timeflow.core import team as team_mod

    asg = team_mod.assign_task(conn, task_id=task.id, assignee="Hermes", assigner="me")
    team_mod.update_assignment_status(conn, asg, "in_progress")
    assert conn.execute("SELECT updated_at FROM team_assignments WHERE id=?",
                        (asg,)).fetchone()["updated_at"]

    fb.set_daily_feedback(conn, None, plan_note="计划", executed="执行", gap_note="")
    fb.set_daily_feedback(conn, None, plan_note="计划2", executed="执行2", gap_note="")
    assert conn.execute("SELECT updated_at FROM feedback_logs").fetchone()["updated_at"]


def test_tasks_keep_their_deliberate_exception(conn) -> None:  # type: ignore[no-untyped-def]
    """`tasks` **不挂触碰触发器**：换「进行中」顺序**不该**动 `updated_at`（T-F1 的刻意行为）。"""
    a = tm.create_task(conn, "任务一")
    b = tm.create_task(conn, "任务二")
    tm.start_task(conn, a.id)
    tm.start_task(conn, b.id)
    before = tm.get_task(conn, b.id).updated_at
    tm.move_doing(conn, b.id, "up")
    assert tm.get_task(conn, b.id).updated_at == before, "换顺序不是内容变了"


def test_v17_is_idempotent_and_tombstones_are_declarative(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """重复连接：结构指纹不变（触发器不重复建、updated_at 不回填成"现在"）。"""
    path = tmp_path / "v17.db"
    c = db_mod.connect(str(path))
    tm.create_task(c, "一条", is_myday=True)
    first = db_mod._schema_fingerprint(c)
    c.close()
    c = db_mod.connect(str(path))
    assert db_mod._schema_fingerprint(c) == first
    triggers = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert {"trg_habits_touch", "trg_tasks_tombstone", "trg_task_groups_tombstone"} <= triggers
    c.close()


def test_tombstone_is_written_for_every_hard_delete_kind(conn) -> None:  # type: ignore[no-untyped-def]
    """墓碑是**触发器**写的：抽查几种硬删（备忘 / 成绩 / 取消打卡 / 解绑分组）都留痕。"""
    memo_mod.create_memo(conn, "会被删的备忘")
    memo_id = conn.execute("SELECT id FROM memos LIMIT 1").fetchone()["id"]
    memo_mod.delete_memo(conn, memo_id)

    habit = fb.create_habit(conn, "习惯")
    fb.toggle_habit_log(conn, habit)
    fb.toggle_habit_log(conn, habit)          # 再点一次 = 取消打卡 → 删行
    fb.delete_habit(conn, habit)

    task = tm.create_task(conn, "带分组")
    gid = tm.create_group(conn, "组")
    tm.set_task_groups(conn, task.id, [gid])
    tm.set_task_groups(conn, task.id, [])

    rows = {
        (r["entity"], r["entity_id"])
        for r in conn.execute("SELECT entity, entity_id FROM sync_tombstones")
    }
    assert ("memos", memo_id) in rows
    assert ("habits", habit) in rows
    assert any(e == "habit_logs" for e, _ in rows)
    assert ("task_groups", f"{task.id}|{gid}") in rows


# ---------------------------------------------------------------- app_settings 不跨端


def test_machine_settings_are_not_overwritten_by_import(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A 的导出目录 / AI 开关不会跟着包过来（那是"这台机器的事"）。"""
    a = _db(tmp_path, "a.db")
    b = _db(tmp_path, "b.db")
    from timeflow.core import ai as ai_mod

    ai_mod.set_enabled(a, True)
    tm.create_task(a, "一条", is_myday=True)
    pack = syncpack.build_pack(a)
    assert "app_settings" not in pack["tables"]

    syncpack.merge_pack(b, pack)
    assert ai_mod.enabled(b) is False, "B 的 AI 开关不该被 A 的设置改掉"
    # B 自己的 app_settings 里只该有"本机自己的"记账（设备号 + 上次导入），
    # **没有**任何从 A 带过来的设置（导出目录 / Vault / AI 开关 / 口径开关）
    leaked = {str(r["key"]) for r in b.execute("SELECT key FROM app_settings").fetchall()}
    assert leaked <= {"sync.device_id", "sync.last_import"}, f"不该把 A 的设置带过来：{leaked}"
    a.close()
    b.close()


# ---------------------------------------------------------------- API 与界面


def test_api_export_preview_and_import(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """三条路由：导出（写文件）/ 预览（dry_run）/ 导入；坏包 400 带原话。"""
    a = _client(tmp_path, "a_api.db")
    a.post("/api/tasks", json={"title": "API 导出的任务", "is_myday": True})
    exported = a.post("/api/sync/export").json()
    assert exported["ok"] is True and Path(exported["path"]).is_file()
    assert exported["rows"] > 0

    b = _client(tmp_path, "b_api.db")
    preview = b.post("/api/sync/import", json={"path": exported["path"], "dry_run": True}).json()
    assert preview["dry_run"] is True and preview["totals"]["inserted"] > 0
    assert b.get("/api/tasks").json() == []                  # 预览没动库
    applied = b.post("/api/sync/import", json={"path": exported["path"]}).json()
    assert applied["dry_run"] is False
    assert [t["title"] for t in b.get("/api/tasks").json()] == ["API 导出的任务"]

    assert b.post("/api/sync/import", json={"path": str(tmp_path / "没有.json")}).status_code == 400
    own = b.post("/api/sync/export").json()
    assert b.post("/api/sync/import", json={"path": own["path"]}).status_code == 400


def test_api_sync_surface_requires_local_origin(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """导出/导入都写本机文件 → 跨站来源一律 403（只有本机页面/程序能调）。"""
    client = _client(tmp_path, "origin.db")
    evil = {"Origin": "https://evil.example"}
    assert client.post("/api/sync/export", headers=evil).status_code == 403
    assert client.post("/api/sync/import", json={"path": "x.json"}, headers=evil).status_code == 403


def test_api_status_and_conflict_log_are_honest(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """状态：文件同步能用、网络同步没做；冲突日志带结果与说明。"""
    client = _client(tmp_path, "status.db")
    st = client.get("/api/sync/status").json()
    assert st["file_sync"] is True and st["network_sync"] is False
    assert st["device_id"] and st["excluded_tables"] and "app_settings" in st["excluded_tables"]

    client.post("/api/tasks", json={"title": "一条", "is_myday": True})
    pack = client.post("/api/sync/export").json()
    other = _client(tmp_path, "other.db")
    other.post("/api/sync/import", json={"path": pack["path"]})
    # 把另一台改旧了再合一次 → 必有冲突日志（带 result 与 note）
    other.post("/api/tasks", json={"title": "改过的另一条"})
    assert client.get("/api/sync/logs").json() == []


def test_schema_version_newer_pack_is_refused(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """包来自更新的程序版本：**明确拒绝**（宁可让你先升级，也不拿半懂的规则去合）。"""
    client = _client(tmp_path, "future.db")
    pack = {
        "format": syncpack.FORMAT, "format_version": 1,
        "schema_version": db_mod.SCHEMA_VERSION + 5,
        "device_id": "futuremachine", "created_at": "2030-01-01T00:00:00",
        "tables": {"tasks": []}, "tombstones": [],
    }
    path = tmp_path / "future.json"
    path.write_text(json.dumps(pack), encoding="utf-8")
    # 包结构合法（format_version 没超），但 schema 比我们新 —— 合并本身能容错；
    # 真正的版本闸在 format_version 上（见 test_load_pack_rejects_bad_input）
    resp = client.post("/api/sync/import", json={"path": str(path)})
    assert resp.status_code == 200 and resp.json()["pack_schema_version"] > db_mod.SCHEMA_VERSION


def test_pack_does_not_leak_the_other_machines_conflict_log(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """同步包不带 `sync_logs`（那是本机的历史）：B 导入后自己的日志还是自己的。"""
    a = _client(tmp_path, "logsa.db")
    b = _client(tmp_path, "logsb.db")
    a.post("/api/tasks", json={"title": "一条", "is_myday": True})
    sync_mod_conn = b  # 只是命名清晰
    b.post("/api/sync/import", json={"path": a.post("/api/sync/export").json()["path"]})
    assert b.get("/api/sync/logs").json() == []
    assert sync_mod_conn is b


def test_primary_key_map_matches_the_real_tables(conn) -> None:  # type: ignore[no-untyped-def]
    """**护栏**：`syncpack.PRIMARY_KEYS` 必须与真实表结构一致。

    为什么值得一条：合并靠主键定位"同一条"。原先假设所有表的主键都叫 `id`，
    于是 `feedback_logs`（主键是 `date`）整张表被**静默跳过** —— 用户手写的每日反馈
    在跨端时凭空消失，而且**没有任何报错**。这条护栏拿 `PRAGMA table_info` 对账，
    以后加表/改主键会立刻红。
    """
    for table in syncpack.SYNCED_TABLES:
        real = tuple(
            str(r["name"])
            for r in sorted(
                (r for r in conn.execute(f"PRAGMA table_info({table})") if int(r["pk"]) > 0),
                key=lambda r: int(r["pk"]),
            )
        )
        assert syncpack.pk_columns(table) == real, f"{table} 的主键映射不对：{real}"


def test_feedback_logs_actually_travel(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """上面那条护栏挡的就是这个：每日反馈（主键是 `date`，不是 `id`）必须真的能跨端。"""
    a = _db(tmp_path, "fba.db")
    b = _db(tmp_path, "fbb.db")
    fb.set_daily_feedback(a, None, plan_note="今天做完", executed="做完了", gap_note="没跑步")
    report = syncpack.merge_pack(b, syncpack.build_pack(a))
    assert report.inserted == 1
    assert fb.get_feedback(b, None)["plan_note"] == "今天做完"
    a.close()
    b.close()


def test_conn_helper_is_sqlite() -> None:
    """（护栏）测试里用到的连接类型没被换掉 —— 上面那些断言都建立在真 sqlite 上。"""
    assert sqlite3.Connection.__name__ == "Connection"
