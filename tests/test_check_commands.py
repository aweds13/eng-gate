"""命令表检查器（T-G31）的测试 —— 给"四个面共用的那一个源"上护栏。

两层：
1. **零件层**：喂合成文件（临时目录里放极小的 contracts / app.py / index.html），
   钉住"基础篇 + 领域篇双节怎么取正名""路由怎么解析""ACTIONS/VIEWS 怎么读""命令面板那张表怎么读"；
2. **数据层**：拿**真仓库**跑一遍，断言 0 条硬冲突（表与三个真源同步）+ 表覆盖全部 OP
   + 命令面板那份投影与 ACTIONS / 契约对得上。
"""

from __future__ import annotations

import json
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


def test_ui_commands_reads_the_palette_table(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """命令面板那张表（T-G61）要能读出来，而且**不被嵌套结构或注释带偏**。

    ★ 这一段特意放了三种"会让正则翻车"的东西：注释里成对的 `{` 与单引号、
    每条里嵌套的 `data:{view:'…'}`、以及结尾那个 `];` 后面还有别的代码。
    第一版 `ACTIONS` 就是被"函数体里的 `};`"截断过（报出 15 条假冲突），
    所以这里用**括号配对**读，并把这个失败模式钉成一条测试。
    """
    html = _write(
        tmp_path,
        "index.html",
        "const VIEWS=['today','review'];\n"
        "const COMMANDS = [\n"
        "  // 注释里写 { 和 ' 也要能跳过（不然括号配对会数错）\n"
        "  { id:'new-task', group:'动作', title:'新建任务', keys:'n',"
        " action:'palette-new-task', op:'OP-1' },\n"
        "  { id:'review', group:'视图', title:'复习', keys:'r', action:'view',"
        " data:{view:'review'}, op:'OP-28' },\n"
        "];\n"
        "const ACTIONS = { 'view': el => x, 'palette-new-task': () => y };\n",
    )
    monkeypatch.setattr(cc, "INDEX", html)
    cmds = cc.ui_commands()
    assert [c["id"] for c in cmds] == ["new-task", "review"], cmds
    assert cmds[0]["keys"] == "n" and cmds[0]["op"] == "OP-1"
    assert cmds[0]["action"] == "palette-new-task" and cmds[0]["view"] == ""
    assert cmds[1]["action"] == "view" and cmds[1]["view"] == "review"
    assert [c["group"] for c in cmds] == ["动作", "视图"]
    assert cc.ui_commands.__doc__ is not None


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


def test_real_palette_is_a_projection_not_a_second_system() -> None:
    """T-G61：命令面板那张表必须与 ACTIONS / 契约命令表**逐条对得上**。

    "⌘K 只是同一张表的另一个入口"这句话如果没人判，第三轮就会变成"面板自己有一份命令" ——
    所以逐条钉：动作真注册过、视图在 VIEWS 里、键位不重复、声称对应的 OP 的界面入口里真有它。
    """
    actions, views = cc.ui_names()
    table = cc.load_commands()
    ops, _ = cc.contract_ops()
    cmds = cc.ui_commands()
    assert len(cmds) >= 15, f"命令面板只有 {len(cmds)} 条命令，像是表被删了"
    ids = [c["id"] for c in cmds]
    assert all(ids), f"有命令没写 id：{ids}"
    assert len(set(ids)) == len(ids), f"命令 id 有重复：{ids}"
    keys = [c["keys"] for c in cmds if c["keys"]]
    assert len(set(keys)) == len(keys), f"键位有重复（会抢键）：{keys}"
    assert len(keys) >= 5, f"只有 {len(keys)} 个键位 —— 那就不叫快捷键层了"
    with_op = 0
    for c in cmds:
        assert c["action"] in actions, f"{c['id']} 的动作 {c['action']} 没在 ACTIONS 注册"
        if c["view"]:
            assert c["view"] in views, f"{c['id']} 的视图 {c['view']} 不在 VIEWS 里"
        if not c["op"]:
            continue
        assert c["op"] in ops, f"{c['id']} 挂了契约里没有的 {c['op']}"
        assert c["op"] in table, f"{c['id']} 挂了还没进命令表的 {c['op']}"
        want = f"view={c['view']}" if c["view"] else f"data-action={c['action']}"
        got = cc.as_list(table[c["op"]].get("ui"))
        assert want in got, (
            f"{c['id']} 声称对应 {c['op']}，但那条 OP 的入口里没有 {want}（现在：{got}）"
        )
        with_op += 1
    assert with_op >= 10, f"只有 {with_op} 条对得上契约 OP —— 面板正在与契约脱钩"


def test_checker_main_is_green_on_the_real_repo(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """真仓库跑一遍**门禁那条判定**（`--check --json`）：0 条硬冲突才算过。

    为什么不只测零件：门禁跑的是 `main()`，如果只在测试里重写一遍判定，
    两边可以各自演化 —— 那正是"我测的是我以为的规则"。
    """
    monkeypatch.setattr(sys, "argv", ["check_commands.py", "--check", "--json"])
    assert cc.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["problems"] == []
    assert report["palette_commands"] >= 15
    assert report["palette_with_op"] >= 10
    assert len(report["palette_keys"]) == len(set(report["palette_keys"]))
