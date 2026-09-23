"""命令表检查器（T-G31）的测试 —— 给"四个面共用的那一个源"上护栏。

两层：
1. **零件层**：喂合成文件（临时目录里放极小的 contracts / app.py / index.html），
   钉住"基础篇 + 领域篇双节怎么取正名""路由怎么解析""ACTIONS/VIEWS 怎么读"；
2. **数据层**：拿**真仓库**跑一遍，断言 0 条硬冲突（表与三个真源同步）+ 表覆盖全部 OP。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_commands as cc  # noqa: E402 —— 需要先用 sys.path 把 scripts/ 挂上

# ------------------------------------------------------------------ 零件层


def _write(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_base_and_domain_sections_take_the_plain_title(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """同一个 OP 在基础篇与领域篇各有一节：取**不带（扩展）**的当正名，另一节记成提示。"""
    _write(tmp_path, "contracts/interactions.md", "## OP-1 新建任务\n\n正文\n")
    _write(tmp_path, "contracts/domains/F1-tasks.md", "## OP-1 新建任务（扩展）\n\n正文\n")
    monkeypatch.setattr(cc, "CONTRACTS", tmp_path / "contracts")

    ops, dupes = cc.contract_ops()
    assert ops == {"OP-1": "新建任务"}
    assert len(dupes) == 1
    assert "基础「新建任务」在 interactions.md" in dupes[0]
    assert "扩展「新建任务（扩展）」在 F1-tasks.md" in dupes[0]


def test_identical_duplicate_is_not_reported(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """标题完全一样的两节不算"基础+扩展"，不报提示。"""
    _write(tmp_path, "contracts/a.md", "## OP-9 同一个标题\n")
    _write(tmp_path, "contracts/b.md", "## OP-9 同一个标题\n")
    monkeypatch.setattr(cc, "CONTRACTS", tmp_path / "contracts")
    ops, dupes = cc.contract_ops()
    assert ops == {"OP-9": "同一个标题"}
    assert dupes == []


def test_routes_parses_method_and_path(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    app = _write(
        tmp_path,
        "app.py",
        '@app.get("/api/tasks")\ndef a(): ...\n'
        '@app.post("/api/tasks/{task_id}/complete")\ndef b(): ...\n',
    )
    monkeypatch.setattr(cc, "APP", app)
    assert cc.routes() == {"GET /api/tasks", "POST /api/tasks/{task_id}/complete"}


def test_ui_names_reads_actions_and_views(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    html = _write(
        tmp_path,
        "index.html",
        "const VIEWS=['today','tasks'];\n"
        "const ACTIONS = {\n  'add-task': el => x,\n  'view': el => y,\n};\n",
    )
    monkeypatch.setattr(cc, "INDEX", html)
    actions, views = cc.ui_names()
    assert actions == {"add-task", "view"}
    assert views == {"today", "tasks"}


# ------------------------------------------------------------------ 数据层（真仓库）


def test_real_repo_has_no_hard_conflict() -> None:
    """真仓库：命令表 ↔ 三个真源 **0 条硬冲突**（这是接进门禁的那条判定）。"""
    ops, _ = cc.contract_ops()
    table = cc.load_commands()
    real_routes = cc.routes()
    actions, views = cc.ui_names()

    assert table, "docs/commands.toml 还没有 [commands] 表"
    for oid, row in table.items():
        assert oid in ops, f"{oid} 不在契约层里"
        for route in cc.as_list(row.get("routes", [])):
            assert route in real_routes, f"{oid} 写了不存在的路由 {route}"
        for entry in cc.as_list(row.get("ui", [])):
            kind, _, name = entry.partition("=")
            if kind == "data-action":
                assert name in actions, f"{oid} 写了没注册的动作 {name}"
            elif kind == "view":
                assert name in views, f"{oid} 写了不存在的视图 {name}"
            else:
                raise AssertionError(f"{oid} 的 ui 写法不认识：{entry}")


def test_real_table_covers_every_contract_op() -> None:
    """契约里 54 条 OP，一条都不许漏在命令表外。"""
    ops, _ = cc.contract_ops()
    missing = sorted(set(ops) - set(cc.load_commands()))
    assert missing == [], f"这些 OP 还没进命令表：{missing}"


def test_real_table_columns_are_valid_enums() -> None:
    """`kind` / `ai` 只能是约定好的几种值 —— 免得以后随手写个新词（`ai` 是**列表**）。"""
    for oid, row in cc.load_commands().items():
        kind = str(row.get("kind", ""))
        assert kind in cc.KINDS or kind == "", f"{oid} 的 kind 非法：{kind!r}"
        for scope in cc.as_list(row.get("ai", [])):
            assert scope in cc.AI_SCOPES, f"{oid} 的 ai 非法：{scope!r}"
