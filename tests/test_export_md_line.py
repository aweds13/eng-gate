"""G 批 · T-G4：沉淀型内容写 Markdown（SR-F8 / 约定层第 9~11 行）。

**口径（2026-09-21 用户定，见 `复盘/口径定案-待定清单.md` §7）**：
- **数据库是权威，md 是产物** —— md 里手改的内容不会被读回，下次导出会覆盖；
- **每天一个 md**（`2026-09-21.md`）；
- **目录可配置**（默认项目下 `export/`，可指到任意路径）；
- **不写进 Obsidian 笔记目录**（红线 `SR-F8.2`：不直接写外部知识资产库）。

覆盖：
- 目录解析（相对项目根 / 本机设置优先于配置 / 空与 NUL 拒绝 / 建不了就回滚配置）；
- 渲染（frontmatter 带 type+命名空间、完成与步骤（含父任务进度）、投入/产出/备忘/反馈、
  空的一天也要有文件）；
- **数据库权威**：完成→导出→撤销→再导出，那条就没了；手改 md 会被覆盖；
- 原子写（不留 `.tmp`）、幂等（除 `generated_at` 外逐字一致）、文件名 = 日期；
- **失败不挡主流程**：自动导出失败只记 `last_error`，完成任务的请求照样 200；
- API：`GET/PUT /api/settings/export`、`POST /api/export/day`（非法 400）；
- 自动导出挂点：完成任务 / 撤销 / 记备忘 / 记产出 / 撤销产出 都各写一次。
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import facts as facts_mod
from timeflow.core import tasks as tm
from timeflow.core import vault
from timeflow.storage import db as db_mod

DAY = "2026-09-21"                      # 固定的一天：给"文件名/空的一天"这类与内容无关的用例
TODAY = date.today().isoformat()        # 内容类用例：完成/产出/备忘都发生在**现在**，就写今天


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "vault.db"))
    facts_mod.clear()
    yield c
    c.close()
    facts_mod.clear()


def _client(tmp_path, name: str = "vault_api.db") -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(create_app(str(tmp_path / name)))


def _export(conn, tmp_path, day: str = DAY):  # type: ignore[no-untyped-def]
    return vault.export_day(conn, day, str(tmp_path / "out"))


def _body(path) -> str:  # type: ignore[no-untyped-def]
    return path.read_text(encoding="utf-8")


def _stable(text: str) -> str:
    """去掉 `generated_at`（每次导出都会变，不算"内容不同"）。"""
    return re.sub(r"^generated_at: .*$", "generated_at: <ts>", text, flags=re.M)


# ---------------------------------------------------------------- 目录


def test_resolve_dir_default_and_priority(conn, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """相对路径相对**项目根**；本机设置优先于 config；没设置就用传入的默认。"""
    assert vault.resolve_dir(conn, "export") == vault.ROOT / "export"
    assert vault.resolve_dir(conn, "custom") == vault.ROOT / "custom"

    absolute = tmp_path / "abs"
    vault.set_dir(conn, str(absolute), "export")
    assert vault.resolve_dir(conn, "export") == absolute       # 本机设置优先
    assert vault.describe(conn, "export")["configured"] is True


def test_set_dir_validates_and_rolls_back(conn, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """空目录名 / 非法字符 → 拒绝；**建不出来就把配置回滚**（不静默留一个写不进去的目录）。"""
    with pytest.raises(ValueError, match="不能为空"):
        vault.set_dir(conn, "   ", "export")
    with pytest.raises(ValueError, match="非法字符"):
        vault.set_dir(conn, "a\x00b", "export")
    assert vault.describe(conn, "export")["configured"] is False

    blocker = tmp_path / "blocker"
    blocker.write_text("我是一个文件", encoding="utf-8")
    with pytest.raises(ValueError, match="同名文件占着|建不了导出目录"):
        vault.set_dir(conn, str(blocker / "sub"), "export")
    assert vault.describe(conn, "export")["configured"] is False   # 回滚了


def test_ensure_dir_creates_nested(conn, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """目录不存在就建（含多级），已存在也不报错。"""
    target = tmp_path / "a" / "b" / "c"
    vault.ensure_dir(target)
    assert target.is_dir()
    vault.ensure_dir(target)


# ---------------------------------------------------------------- 渲染


def test_render_day_has_frontmatter_and_sections(conn) -> None:  # type: ignore[no-untyped-def]
    """frontmatter 带 type + 命名空间（约定层要求）；完成/步骤/投入/产出/备忘/反馈都写进去。"""
    top = tm.create_task(conn, "高数作业", is_myday=True)
    step = tm.create_subtask(conn, top.id, "第 2 题")
    tm.complete_task(conn, step.id)
    tm.complete_task(conn, top.id)
    done_task = tm.create_task(conn, "背单词", is_myday=True)
    tm.complete_task(conn, done_task.id)
    from timeflow.core import memo as memo_mod

    memo_mod.add_output_entry(conn, value=1, kind="kpi", note="数学卷子")
    memo_mod.create_memo(conn, "别忘了交作业", ref_handle="notes/高数.md")
    from timeflow.core import feedback as fb

    fb.set_daily_feedback(
        conn, TODAY, plan_note="今天做完高数", executed="做完了", gap_note="没跑步"
    )

    text = vault.render_day(conn, TODAY)
    assert text.startswith("---\ntype: timeflow-daily\nnamespace: timeflow\n")
    assert f"date: {TODAY}" in text
    assert "generated_at: " in text
    assert f"# {TODAY} " in text                    # 标题带星期
    assert "数据库是权威" in text                    # 产物声明（也写进文件头）
    assert "## 完成" in text and "- [x] 背单词" in text
    assert "高数作业 · 第 2 题" in text              # 步骤挂在父任务后面
    assert "## 投入" in text and "复习 0 张 · 产出 1 条" in text
    assert "## 产出" in text and "KPI ×1：数学卷子" in text
    assert "## 备忘" in text and "别忘了交作业（引用：notes/高数.md）" in text
    assert "## 每日反馈" in text and "**计划**：今天做完高数" in text


def test_render_day_without_records_is_still_a_file(conn) -> None:  # type: ignore[no-untyped-def]
    """啥都没发生的一天也要有一份（空手而归不该没有记录）。"""
    text = vault.render_day(conn, "2020-01-01")
    assert "（这一天还没有记录。）" in text
    assert "## 完成" not in text


def test_render_ignores_retracted_outputs(conn) -> None:  # type: ignore[no-untyped-def]
    """撤销的产出如实列出但标明不计入（与账本同一口径，不自己算一套）。"""
    from timeflow.core import memo as memo_mod

    entry = memo_mod.add_output_entry(conn, value=2, kind="asset", note="笔记#3")
    memo_mod.retract_output_entry(conn, entry)
    text = vault.render_day(conn, TODAY)
    assert "资产 ×2：笔记#3（已撤销，不计入）" in text


# ---------------------------------------------------------------- 写出


def test_export_writes_one_file_per_day(conn, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """文件名 = 日期；写完不留 `.tmp`；旧的一天也写得出来。"""
    result = _export(conn, tmp_path)
    assert result.day == DAY
    note = tmp_path / "out" / f"{DAY}.md"
    assert note.is_file()
    assert result.path == str(note)
    assert result.bytes == len(note.read_bytes())
    assert list((tmp_path / "out").glob("*.tmp")) == []

    older = vault.export_day(conn, "2020-01-01", str(tmp_path / "out"))
    assert (tmp_path / "out" / "2020-01-01.md").is_file()
    assert older.day == "2020-01-01"


def test_export_is_idempotent(conn, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """同一天导出两次：内容逐字一致（除 `generated_at`）。"""
    _export(conn, tmp_path)
    first = _body(tmp_path / "out" / f"{DAY}.md")
    _export(conn, tmp_path)
    second = _body(tmp_path / "out" / f"{DAY}.md")
    assert _stable(first) == _stable(second)


def test_database_is_the_authority(conn, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """**数据库权威**：完成任务 → 导出里有它；撤销 → 再导出就没了；手改 md 会被覆盖。"""
    task = tm.create_task(conn, "会被撤销的任务", is_myday=True)
    tm.complete_task(conn, task.id)
    _export(conn, tmp_path, TODAY)
    note = tmp_path / "out" / f"{TODAY}.md"
    assert "会被撤销的任务" in _body(note)

    tm.uncomplete_task(conn, task.id)
    _export(conn, tmp_path, TODAY)
    assert "会被撤销的任务" not in _body(note)

    # 手改 md：不会被读回，下次导出直接覆盖（这句话写在文件头里）
    note.write_text("我手写的笔记，希望被保留\n", encoding="utf-8")
    _export(conn, tmp_path, TODAY)
    assert "我手写的笔记，希望被保留" not in _body(note)


def test_export_rejects_bad_day(conn, tmp_path) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError, match="日期得写成"):
        vault.export_day(conn, "9月21日", str(tmp_path / "out"))


def test_try_export_records_error_without_raising(conn, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """自动导出失败**只记错**（不抛）—— md 是产物，不许把主流程带崩。"""
    blocker = tmp_path / "blocker"
    blocker.write_text("我是个文件", encoding="utf-8")
    result = vault.try_export(conn, DAY, str(blocker / "sub"))
    assert result is None
    status = vault.status(conn, str(blocker / "sub"))
    assert status["last_error"], status          # 错误不许静默消失
    assert vault.describe(conn, "export")["note"].startswith("**数据库是权威")


def test_describe_states_the_red_line(conn) -> None:  # type: ignore[no-untyped-def]
    """红线写在**界面数据**里（不只是代码注释）：不写进 Obsidian 笔记目录。"""
    body = vault.describe(conn, "export")
    assert "不写进 Obsidian 的笔记目录" in str(body["where"])
    assert "手改的内容**不会被读回**" in str(body["note"])
    assert body["default_dir"] == "export"


# ---------------------------------------------------------------- API


def test_api_settings_and_manual_export(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """三条路由：读现状 / 改目录（非法 400）/ 手动导出（字段齐、文件真的在）。"""
    client = _client(tmp_path)
    body = client.get("/api/settings/export").json()
    # `default_dir` = **当前配置里的默认**（测试进程里被 conftest 指到临时目录，免得写进仓库），
    # 所以这里只断言"有默认、有说明、有解析出来的绝对路径"。
    assert body["default_dir"] and body["note"] and Path(body["dir"]).is_absolute()

    ok = client.put("/api/settings/export", json={"dir": str(tmp_path / "out")})
    assert ok.status_code == 200 and ok.json()["configured"] is True
    assert (tmp_path / "out").is_dir()
    assert client.put("/api/settings/export", json={"dir": "  "}).status_code == 400

    task = client.post("/api/tasks", json={"title": "外部脚本建的任务", "is_myday": True}).json()
    client.post(f"/api/tasks/{task['id']}/complete")
    exported = client.post("/api/export/day", json={}).json()
    assert exported["ok"] is True and exported["tasks"] == 1
    assert (tmp_path / "out" / f"{date.today().isoformat()}.md").is_file()
    assert client.post("/api/export/day", json={"day": "9月21日"}).status_code == 400


def test_api_auto_export_on_writes(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """**自动导出**挂点：完成任务 / 记备忘 / 记产出 都各写一次（用户不用手动点）。"""
    client = _client(tmp_path, "auto.db")
    client.put("/api/settings/export", json={"dir": str(tmp_path / "out")})
    note = tmp_path / "out" / f"{date.today().isoformat()}.md"

    task = client.post("/api/tasks", json={"title": "做完就有记录", "is_myday": True}).json()
    assert not note.exists()                       # 建任务本身不导出（还没"做成了什么"）
    client.post(f"/api/tasks/{task['id']}/complete")
    assert note.is_file() and "做完就有记录" in _body(note)

    client.post("/api/memos", json={"text": "记一条备忘"})
    assert "记一条备忘" in _body(note)

    client.post("/api/ledger/output", json={"value": 1, "kind": "asset", "note": "写了个脚本"})
    assert "资产 ×1：写了个脚本" in _body(note)


def test_auto_export_failure_does_not_block_the_action(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """**md 是产物**：目录写不进去时，"完成任务"照样 200，只把错误记下来给界面看。"""
    client = _client(tmp_path, "fail.db")
    blocker = tmp_path / "blocker"
    blocker.write_text("我是文件", encoding="utf-8")
    # 绕过 set_dir 的校验（模拟"后来目录被删/被占"这种情况）直接写设置
    raw = db_mod.connect(str(tmp_path / "fail.db"))
    raw.execute(
        "INSERT INTO app_settings (key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (vault.KEY_DIR, str(blocker / "sub")),
    )
    raw.commit()
    raw.close()

    task = client.post("/api/tasks", json={"title": "照样能完成", "is_myday": True}).json()
    resp = client.post(f"/api/tasks/{task['id']}/complete")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "完成"
    assert client.get("/api/settings/export").json()["last_error"]     # 错误被记下来
    assert client.get("/api/tasks").json()               # 库仍然可用（导出失败没把数据弄坏）


def test_export_only_touches_its_own_directory(conn, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """**只写自己那个目录**（红线 SR-F8.2：不碰知识资产库/别处）：目录里就这一个文件。"""
    _export(conn, tmp_path)
    assert [p.name for p in (tmp_path / "out").iterdir()] == [f"{DAY}.md"]
