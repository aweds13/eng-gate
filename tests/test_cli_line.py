"""命令行（T-G64 只读 → T-G65 加写入 + MCP）的测试 —— 「命令行是命令表的投影」这句话的护栏。

三层：
1. **形状层**：自描述（`commands --json`）里有每条命令的 schema 与五个退出码；
2. **行为层**：拿真库跑每一条命令（`--json` 与人读两条路），错误路径给稳定退出码；
3. **投影层**：`CLI 的输出 == 同一条路由的输出`（走真 HTTP 边界）、CLI 不许自己碰
   `core/`·`storage/`·`sqlite3`、也不许出现命令表里没有的命令。

写命令那批的口径（默认关 / 只做界面上已有的那些 / 与界面同一条路）在
`tests/test_cli_writes.py` 与 `tests/test_mcp_line.py` 里判，这个文件管"读"与"分派"。

为什么"CLI 输出 == 接口输出"要单独钉一条：CLI 一旦自己算一遍数字，就变成第二套口径 ——
而这个项目全部口径的价值就在"只有一处"。这条断言是那句话的机器形态。
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_commands as cc  # noqa: E402 —— 需要先用 sys.path 把 scripts/ 挂上

from timeflow.api.app import create_app  # noqa: E402
from timeflow.cli import main as cli_mod  # noqa: E402
from timeflow.cli import registry, table  # noqa: E402

CAPTURE_DAY = "2026-06-15"  # 与渲染/行为流用同一个假日子（T-G62 的时钟缝）
#: 参数默认值与接口默认值必须一致，否则"同源"这条断言会自己变成假红
EXPLICIT = {"trend": ["--days", "14"], "upcoming": ["--days", "14"]}


@pytest.fixture(autouse=True)
def _pinned_day(monkeypatch: pytest.MonkeyPatch) -> None:
    """把「今天」钉住（走产品的时钟缝）—— CLI 与接口必须看到同一个今天。"""
    monkeypatch.setenv("TIMEFLOW_FAKE_TODAY", CAPTURE_DAY)


@pytest.fixture
def seeded(tmp_path: Path) -> tuple[str, TestClient]:
    """一份有内容的真库（走 HTTP 建数据）—— 空库跑不出排版层的错。"""
    path = tmp_path / "cli.db"
    client = TestClient(create_app(str(path)))
    overdue = client.post(
        "/api/tasks", json={"title": "写周报", "due_date": "2026-06-10", "is_myday": True}
    ).json()
    other = client.post(
        "/api/tasks", json={"title": "读论文", "due_date": "2026-06-20", "priority": "高"}
    ).json()
    client.post(f"/api/tasks/{other['id']}/complete")
    habit = client.post("/api/habits", json={"name": "早起"}).json()
    client.post(f"/api/habits/{habit['id']}/toggle")
    client.post("/api/review/items", json={"title": "英语单词"})
    course = client.post("/api/courses", json={"name": "高等数学"}).json()
    client.post(
        "/api/assessments",
        json={"course_id": course["id"], "name": "期中", "due_date": "2026-06-18"},
    )
    client.post("/api/team/assign", json={"task_id": overdue["id"], "assignee": "小李"})
    client.post("/api/focus/start", json={"task_id": other["id"]})
    return str(path), client


def _run(capsys: pytest.CaptureFixture[str], args: list[str]) -> tuple[int, str, str]:
    code = cli_mod.main(args)
    out = capsys.readouterr()
    return code, out.out, out.err


# ------------------------------------------------------------------ 形状层


def test_self_description_lists_every_command_with_schema(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`commands --json` 是"自带 schema + 自描述"那两条性质的落点。"""
    code, out, _ = _run(capsys, ["commands", "--json"])
    assert code == cli_mod.EXIT_OK
    payload = json.loads(out)
    # T-G65：写命令进来了，所以"只读"这个总标记换成了"写操作怎么开"的说明
    assert payload["write_gate"]["flag"] == cli_mod.WRITE_FLAG
    assert "默认关" in payload["write_gate"]["rule"]
    assert set(payload["exit_codes"]) == {"0", "1", "2", "3", "4"}
    assert set(payload["errors"]) == {
        "usage",
        "api_4xx",
        "db_missing",
        "db_unopenable",
        "table_missing",
        "table_broken",
        "write_disabled",
    }
    assert set(payload["errors"].values()) <= {1, 2, 3, 4}
    assert [c["name"] for c in payload["commands"]] == registry.names()
    writes = 0
    for command in payload["commands"]:
        assert command["op"].startswith("OP-")
        assert command["title"]
        if command["write"]:
            writes += 1
            assert not command["route"].startswith("GET "), command["name"]
        else:
            assert command["route"].startswith("GET "), command["name"]
        for param in command["params"]:
            assert param["kind"] in {"int", "str", "bool"}
            assert param["where"] in {"query", "path", "body"}
            assert param["help"]
    assert writes == len(registry.WRITE_COMMANDS) >= 1, "写命令那一批要在自描述里"


def test_table_flag_exposes_the_whole_contract_table(capsys: pytest.CaptureFixture[str]) -> None:
    """`commands --table` 打整张契约命令表（含 kind / 可逆 / AI 边界）—— MCP 那一步的原料。"""
    code, out, _ = _run(capsys, ["commands", "--table", "--json"])
    assert code == cli_mod.EXIT_OK
    payload = json.loads(out)
    rows = payload["rows"]
    assert len(rows) >= 50
    assert payload["table"].endswith("commands.toml")
    for row in rows.values():
        assert row["kind"] in {"read", "write", "derive"}
        assert "reversible" in row


def test_commands_kind_filter_splits_read_and_write(capsys: pytest.CaptureFixture[str]) -> None:
    """`--kind read|write` 各自只留那一批 —— 写命令从"没有"变成了"第一批 6 条"（T-G65）。"""
    code, out, _ = _run(capsys, ["commands", "--kind", "read", "--json"])
    assert code == cli_mod.EXIT_OK
    assert [c["name"] for c in json.loads(out)["commands"]] == [
        c.name for c in registry.COMMANDS
    ]
    code, out, _ = _run(capsys, ["commands", "--kind", "write", "--json"])
    assert code == cli_mod.EXIT_OK
    assert [c["name"] for c in json.loads(out)["commands"]] == [
        c.name for c in registry.WRITE_COMMANDS
    ]


def test_help_lists_every_command(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(capsys, ["--help"])
    assert code == cli_mod.EXIT_OK
    for name in registry.names():
        assert f"timeflow {name}" in out
    code, out, _ = _run(capsys, ["today", "--help"])
    assert code == cli_mod.EXIT_OK
    assert "OP-7" in out and "GET /api/summary" in out


def test_help_for_one_command_accepts_both_word_orders(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`timeflow help today` 与 `timeflow today --help` 是同一件事（T-G66）。"""
    code, out, _ = _run(capsys, ["help", "today"])
    assert code == cli_mod.EXIT_OK
    assert "OP-7" in out and "GET /api/summary" in out
    code, out, _ = _run(capsys, ["help"])
    assert code == cli_mod.EXIT_OK
    assert "timeflow today" in out  # 不带命令名时仍给总目录


# ------------------------------------------------------------------ 投影层


def test_every_command_is_a_projection_of_the_same_route(
    seeded: tuple[str, TestClient], capsys: pytest.CaptureFixture[str]
) -> None:
    """**CLI 的 JSON == 同一条路由的 JSON**（逐条命令、真库、真边界）。

    这条一旦红，说明 CLI 开始自己算数了 —— 那就是"四个面各写一遍"的开始。
    """
    path, client = seeded
    for command in registry.COMMANDS:
        extra = EXPLICIT.get(command.name, [])
        code, out, err = _run(capsys, [command.name, "--json", "--db", path, *extra])
        assert code == cli_mod.EXIT_OK, f"{command.name} 退出码 {code}：{err}"
        query = "?days=14" if extra else ""
        route_path = command.route.partition(" ")[2]
        assert json.loads(out) == client.get(route_path + query).json(), command.name


def test_every_command_has_a_human_face(
    seeded: tuple[str, TestClient], capsys: pytest.CaptureFixture[str]
) -> None:
    """人读那条路每条都要能跑出东西（空库/有数据的排版都不许炸）。"""
    path, _ = seeded
    for command in registry.COMMANDS:
        extra = EXPLICIT.get(command.name, [])
        code, out, err = _run(capsys, [command.name, "--db", path, *extra])
        assert code == cli_mod.EXIT_OK, f"{command.name}：{err}"
        assert out.strip(), command.name
        assert not out.lstrip().startswith("{"), f"{command.name} 的人读输出像是 JSON"


def test_human_output_reports_the_seeded_numbers(
    seeded: tuple[str, TestClient], capsys: pytest.CaptureFixture[str]
) -> None:
    """有数据时人读输出要说得对（不是"能跑就行"）。"""
    path, _ = seeded
    code, out, _ = _run(capsys, ["today", "--db", path])
    assert code == cli_mod.EXIT_OK
    assert out.splitlines()[0].startswith(CAPTURE_DAY), out
    _, plan_out, _ = _run(capsys, ["plan", "--db", path])
    assert "写周报" in plan_out
    _, overdue_out, _ = _run(capsys, ["overdue", "--db", path])
    assert "写周报" in overdue_out
    _, due_out, _ = _run(capsys, ["due", "--db", path])
    assert "英语单词" in due_out
    _, done_out, _ = _run(capsys, ["done", "--db", path])
    assert "读论文" in done_out
    _, habits_out, _ = _run(capsys, ["habits", "--db", path])
    assert "早起" in habits_out
    _, upcoming_out, _ = _run(capsys, ["upcoming", "--db", path])
    assert "期中" in upcoming_out and "高等数学" in upcoming_out
    _, board_out, _ = _run(capsys, ["board", "--db", path])
    assert "小李" in board_out
    _, focus_out, _ = _run(capsys, ["focus", "--db", path])
    assert "进行中" in focus_out


def test_empty_database_still_says_something_plain(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """空库：每条命令都要有一句人话（不是空白、不是报错）。"""
    path = str(tmp_path / "empty.db")
    TestClient(create_app(path)).get("/api/summary")
    for command in registry.COMMANDS:
        code, out, err = _run(capsys, [command.name, "--db", path])
        assert code == cli_mod.EXIT_OK, f"{command.name}：{err}"
        assert out.strip(), command.name


# ------------------------------------------------------------------ 行为层


def test_unknown_command_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _run(capsys, ["nosuch", "--json"])
    assert code == cli_mod.EXIT_USAGE
    assert out == ""  # stdout 只放数据
    assert json.loads(err.strip().splitlines()[-1])["error"]["code"] == "usage"


def test_bad_argument_type_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _run(capsys, ["trend", "--days", "abc"])
    assert code == cli_mod.EXIT_USAGE
    assert "整数" in err


def test_unknown_flag_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = _run(capsys, ["today", "--nope", "1"])
    assert code == cli_mod.EXIT_USAGE
    assert "--nope" in err


def test_http_error_becomes_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`trend --days 999` 越界由**边界**判（400）—— CLI 不自己校验，只翻退出码。"""
    path = str(tmp_path / "bounds.db")
    TestClient(create_app(path)).get("/api/summary")
    code, out, err = _run(capsys, ["trend", "--days", "999", "--db", path, "--json"])
    assert code == cli_mod.EXIT_API
    assert out == ""
    assert json.loads(err.strip().splitlines()[-1])["error"]["code"] == "api_400"


def test_missing_table_refuses_to_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """命令表找不到 → 拒绝工作（退 3），**不**自己发明一份命令清单。"""
    monkeypatch.setenv(table.TABLE_ENV, str(tmp_path / "nope.toml"))
    code, out, err = _run(capsys, ["commands", "--json"])
    assert code == cli_mod.EXIT_ENV
    assert out == ""
    assert json.loads(err.strip().splitlines()[-1])["error"]["code"] == "table_missing"


def test_default_db_is_the_desktop_one() -> None:
    """默认库与桌面端同源（不另开一份数据）。"""
    from timeflow.config import load_settings

    assert cli_mod.default_db() == str(load_settings().database.path)


# ------------------------------------------------- 环境错：翻译成稳定码，不留副作用（T-G66）


def test_missing_database_is_an_environment_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """★ 库不存在 → 退 3，而且**一个文件都不许留下**。

    不查这一下会怎样（T-G66 真踩到）：SQLite 会默默建一个空库，于是打错路径的人
    得到一份"看起来正常"的空数据（0 分钟 / 0 项）—— 一个只读命令还不该有文件副作用。
    """
    missing = tmp_path / "没有这个库.db"
    code, out, err = _run(capsys, ["today", "--json", "--db", str(missing)])
    assert code == cli_mod.EXIT_ENV
    assert out == ""
    assert json.loads(err.strip().splitlines()[-1])["error"]["code"] == "db_missing"
    assert not missing.exists(), "只读命令不该建库"


def test_directory_as_database_is_an_environment_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--db` 指到一个目录 → 同样是环境错（不是栈）。"""
    code, out, _ = _run(capsys, ["today", "--json", "--db", str(tmp_path)])
    assert code == cli_mod.EXIT_ENV
    assert out == ""


def test_broken_database_gives_a_stable_code_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """库文件在、但不是数据库 → `db_unopenable`。

    ★ 这一条是"只兜 create_app 不够"的证据：库是**懒连接**的，这类错在**请求里**才炸出来。
    """
    bad = tmp_path / "坏.db"
    bad.write_text("这不是一个数据库", encoding="utf-8")
    code, out, err = _run(capsys, ["today", "--json", "--db", str(bad)])
    assert code == cli_mod.EXIT_ENV
    assert out == ""
    assert "Traceback" not in err
    assert json.loads(err.strip().splitlines()[-1])["error"]["code"] == "db_unopenable"


def test_broken_table_gives_a_stable_code_with_line_and_column(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """命令表语法坏了 → `table_broken`，并把 `tomllib` 的行列号带给用户。"""
    bad = tmp_path / "bad.toml"
    bad.write_text('[commands."OP-7"\n', encoding="utf-8")
    monkeypatch.setenv(table.TABLE_ENV, str(bad))
    code, out, err = _run(capsys, ["commands", "--json"])
    assert code == cli_mod.EXIT_ENV
    assert out == ""
    error = json.loads(err.strip().splitlines()[-1])["error"]
    assert error["code"] == "table_broken"
    assert "line" in error["detail"], error["detail"]


# ------------------------------------------------------------------ 入口分派


def test_entry_point_sends_cli_words_to_the_command_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """`timeflow today` 走 CLI（不开窗口、不起服务）。"""
    from timeflow.app import main as app_main

    seen: list[list[str]] = []
    monkeypatch.setattr(app_main, "cli_main", lambda argv: seen.append(argv) or 0)
    with pytest.raises(SystemExit) as exc:
        app_main.main(["today", "--json"])
    assert exc.value.code == 0
    assert seen == [["today", "--json"]]


def test_bare_timeflow_still_opens_the_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """不带参数**仍然开窗口**（原行为一个没改）—— 只加不改。"""
    from timeflow.app import main as app_main

    class _BoomError(Exception):
        pass

    class _FakeServer:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise _BoomError

    monkeypatch.setattr(app_main, "cli_main", lambda argv: pytest.fail(f"不该走 CLI：{argv}"))
    monkeypatch.setattr(app_main.backup_mod, "make_backup", lambda path: None)
    monkeypatch.setattr(app_main, "create_app", lambda *a, **k: object())
    monkeypatch.setattr(app_main.uvicorn, "Server", _FakeServer)
    with pytest.raises(_BoomError):
        app_main.main([])


def test_app_start_can_be_silenced_for_scripts(
    seeded: tuple[str, TestClient],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """脚本要干净输出时用 `TF_LOG_PATH=off`（既有的日志开关），stdout 一个字不受影响。"""
    path, _ = seeded
    monkeypatch.setenv("TF_LOG_PATH", "off")
    code, out, _ = _run(capsys, ["today", "--json", "--db", path])
    assert code == cli_mod.EXIT_OK
    assert json.loads(out)["invest_hours"] >= 0


# ------------------------------------------------------------------ 投影层（源码级）


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_cli_and_mcp_do_not_touch_the_database_or_the_domain_layer() -> None:
    """CLI 与 MCP **只当投影**：不 import `core/`、不 import `storage/`、不直接碰 sqlite3。

    真调用的那条路是 `timeflow.api.app`（唯一的边界）—— 少了它，CLI/MCP 就成了第二套口径。
    （T-G65：MCP 也不许自己取数 —— 它连参数解析都走 CLI 那条路。）
    """
    files = sorted((ROOT / "src" / "timeflow" / "cli").glob("*.py")) + sorted(
        (ROOT / "src" / "timeflow" / "mcp").glob("*.py")
    )
    assert len(files) >= 8, f"CLI/MCP 包的文件少了：{files}"
    imported: set[str] = set()
    for path in files:
        imported |= _imports(path)
    assert "timeflow.api.app" in imported, "CLI 必须走 HTTP 边界，而不是自己取数"
    for forbidden in ("sqlite3", "timeflow.core", "timeflow.storage"):
        bad = {name for name in imported if name == forbidden or name.startswith(forbidden + ".")}
        assert not bad, f"CLI/MCP 不许 import {forbidden}（那就成了第二套口径）：{sorted(bad)}"


def test_real_repo_read_commands_are_a_read_only_projection() -> None:
    """真仓库：只读命令 ↔ 命令表双向对得上（这是接进门禁的那条判定的一半）。"""
    rows = cc.load_commands()
    for command in registry.COMMANDS:
        assert not registry.is_write(command), command.name
        assert command.op in rows, command.op
        row = rows[command.op]
        assert row["kind"] in {"read", "derive"}, f"{command.name} 挂在写操作上"
        assert command.route.startswith("GET ")
        assert command.route in cc.as_list(row.get("routes")), command.route
        assert f"timeflow {command.name}" in cc.as_list(row.get("cli"))
    read_ops = {oid for oid, row in rows.items() if row.get("kind") in {"read", "derive"}}
    holes = sorted(oid for oid in read_ops if not cc.as_list(rows[oid].get("cli")))
    # 只读**全覆盖**（T-G30 §4.4 的口径）—— 唯一允许空的是 OP-43（它压根没有路由）
    assert holes == ["OP-43"], f"这些只读操作还没有命令行入口：{holes}"


def test_real_repo_write_commands_only_do_what_the_ui_already_does() -> None:
    """真仓库：写命令的三条口径（用户 2026-09-25 定，T-G65 落地）。

    ① 方法与 `kind` 对得上（非 GET ↔ write）；
    ② **只做界面上已有的那些** —— 那条 OP 的 `ui` 必须非空（这句话的机器形态）；
    ③ 表里的 `cli` / `mcp` 两栏**双向**对得上（表说有这么条命令，代码里就得真有）。
    """
    rows = cc.load_commands()
    assert registry.WRITE_COMMANDS, "写命令第一批不该是空的"
    for command in registry.WRITE_COMMANDS:
        assert registry.is_write(command), command.name
        assert not command.route.startswith("GET "), command.name
        row = rows[command.op]
        assert row["kind"] == "write", f"{command.name} 挂在 {row['kind']} 上"
        assert cc.as_list(row.get("ui")), (
            f"{command.name} 的 {command.op} 在界面上没有入口 —— 写只做「界面上已有的那些」"
        )
        assert command.route in cc.as_list(row.get("routes")), command.route
        assert f"timeflow {command.name}" in cc.as_list(row.get("cli"))
        assert command.name in cc.as_list(row.get("mcp"))
