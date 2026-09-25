"""MCP 服务端（T-G65）的测试 —— 「工具清单由命令表生成」与「写默认关」这两句话的机器形态。

判据分四层：

| 层 | 判什么 |
|---|---|
| 形状 | `tools/list` 的每一条都由 `registry` 现算：名字/描述/`inputSchema`/必填/`annotations` |
| 默认关 | 不开 `--allow-write` → 清单里没有写工具，**硬调也拒绝**，而且库没动 |
| 协议 | `initialize` / `ping` / 通知不回 / 不认的方法 `-32601` / 不认的工具 `-32602` /
  坏 JSON `-32700` |
| 真 stdio | 真起一个子进程、真走一行一个 JSON-RPC：stdout 上**只有**协议消息，写操作真的落库 |

★ 诚实边界（写进 `复盘/MCP与写操作-T-G65.md`）：我们**没有**第三方 MCP SDK（本项目零依赖），
所以上面这条"真 stdio"验的是**我们自己的客户端脚本 ↔ 我们的服务端**；
第三方客户端（Claude Desktop / DSH 之类）里能不能直接用，要**人工接一次**才算验过。
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent

from timeflow.api.app import create_app  # noqa: E402
from timeflow.cli import main as cli_mod  # noqa: E402
from timeflow.cli import registry  # noqa: E402
from timeflow.mcp import server  # noqa: E402

CAPTURE_DAY = "2026-06-15"
SERVER_SNIPPET = (
    "import sys; from timeflow.mcp.server import serve; raise SystemExit(serve(sys.argv[1:]))"
)
JSON_TYPES = {"int": "integer", "bool": "boolean", "str": "string"}


def _req(mid: int | None, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """一条 JSON-RPC 请求（`mid=None` 就是通知）。"""
    message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if mid is not None:
        message["id"] = mid
    if params is not None:
        message["params"] = params
    return message


def _call(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    return _req(1, "tools/call", {"name": name, "arguments": arguments or {}})


@pytest.fixture(autouse=True)
def _pinned_day(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIMEFLOW_FAKE_TODAY", CAPTURE_DAY)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "mcp.db"
    TestClient(create_app(str(path))).get("/api/tasks")  # 建库（走真边界）
    return path


# ------------------------------------------------------------------ 形状层


def test_tool_list_is_generated_from_the_registry() -> None:
    """工具清单 = registry 的两批命令（不是手抄的第二份）。"""
    assert [t["name"] for t in server.tool_list(False)] == [c.name for c in registry.COMMANDS]
    assert [t["name"] for t in server.tool_list(True)] == [c.name for c in registry.all_commands()]


def test_every_tool_schema_is_a_projection_of_the_param_table() -> None:
    """`inputSchema` 就是参数表的投影：名字/类型/默认/必填/说明都要对得上。"""
    by_name = {t["name"]: t for t in server.tool_list(True)}
    for command in registry.all_commands():
        tool = by_name[command.name]
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        assert set(schema["properties"]) == {p.name for p in command.params}
        assert schema["required"] == [p.name for p in command.params if p.required]
        assert tool["annotations"]["readOnlyHint"] is (not registry.is_write(command))
        assert command.op in tool["description"]  # 工具与契约 OP 的对应写在描述里
        for param in command.params:
            entry = schema["properties"][param.name]
            assert entry["description"] == param.help
            assert entry["type"] == JSON_TYPES[param.kind]
            if param.default is not None:
                assert entry["default"] == server._default_value(param)  # noqa: SLF001
            else:
                assert "default" not in entry


def test_boolean_defaults_are_real_booleans_not_strings() -> None:
    """`"false"` 必须变成 `false` —— MCP 客户端会照着 schema 造参数。"""
    add_task = {t["name"]: t for t in server.tool_list(True)}["add-task"]
    props = add_task["inputSchema"]["properties"]
    assert props["is_myday"]["default"] is False
    assert props["priority"]["default"] == "中"


# ------------------------------------------------------------------ 默认关


def test_write_tools_are_hidden_and_refused_without_the_switch(db_path: Path) -> None:
    """★ 不开写：清单里没有写工具；**硬调也拒绝**，而且库一个字节没动。

    拒绝的形状是"这个会话里没有这个工具"（`-32602`）+ 一句"怎么开" ——
    与 `tools/list` 不列它是**同一个判断**（MCP 的规矩：只能调清单里出现过的工具）。
    """
    listed = {t["name"] for t in server.tool_list(False)}
    assert not (listed & {c.name for c in registry.WRITE_COMMANDS})
    hidden = server.call_tool("memo", {"text": "不该落库"}, db=str(db_path), allow_write=False)
    assert hidden is None

    reply = server.handle(_call("memo"), db=str(db_path), allow_write=False)
    assert reply is not None and reply["error"]["code"] == server.JSONRPC_INVALID_PARAMS
    assert cli_mod.WRITE_FLAG in reply["error"]["message"]
    assert "写操作" in reply["error"]["message"]
    memos = TestClient(create_app(str(db_path))).get("/api/memos").json()
    assert memos == [], "没开写就不许留下东西"


def test_write_tools_really_write_when_the_switch_is_on(db_path: Path) -> None:
    """开了写：同一个工具真的落库（不是"列出来了但调不动"）。"""
    result = server.call_tool("memo", {"text": "开了写"}, db=str(db_path), allow_write=True)
    assert result is not None and result["isError"] is False
    memos = TestClient(create_app(str(db_path))).get("/api/memos").json()
    assert [m["text"] for m in memos] == ["开了写"]


def test_the_gate_is_the_same_constant_as_the_cli() -> None:
    """同一个开关名、同一条说法 —— CLI 与 MCP 不许各有一个"开写"的概念。"""
    assert cli_mod.WRITE_FLAG == "--allow-write"
    assert cli_mod.WRITE_FLAG in server._mcp_usage()  # noqa: SLF001


# ------------------------------------------------------------------ 协议层


def test_initialize_ping_and_notifications(db_path: Path) -> None:
    reply = server.handle(
        _req(1, "initialize", {"protocolVersion": "2025-06-18"}),
        db=str(db_path),
        allow_write=False,
    )
    assert reply is not None
    result = reply["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["capabilities"]["tools"] == {"listChanged": False}
    assert result["serverInfo"]["name"] == "timeflow"
    assert cli_mod.WRITE_FLAG in result["instructions"]
    # 不认识的版本 → 回我们自己支持的那个（不装作支持）
    other = server.handle(
        _req(2, "initialize", {"protocolVersion": "1999-01-01"}),
        db=str(db_path),
        allow_write=False,
    )
    assert other is not None and other["result"]["protocolVersion"] == server.PROTOCOL_VERSION
    # 通知（没有 id）不回
    assert (
        server.handle(_req(None, "notifications/initialized"), db=str(db_path), allow_write=False)
        is None
    )
    ping = server.handle(_req(3, "ping"), db=str(db_path), allow_write=False)
    assert ping is not None and ping["result"] == {}


def test_unknown_method_and_unknown_tool_are_jsonrpc_errors(db_path: Path) -> None:
    bad_method = server.handle(_req(1, "resources/list"), db=str(db_path), allow_write=False)
    assert bad_method is not None and bad_method["error"]["code"] == server.JSONRPC_METHOD_NOT_FOUND
    # 写工具在没开开关时"不存在" —— 客户端凭记忆硬调会拿到 -32602（而不是悄悄执行）
    bad_tool = server.handle(_call("memo"), db=str(db_path), allow_write=False)
    assert bad_tool is not None and bad_tool["error"]["code"] == server.JSONRPC_INVALID_PARAMS
    assert "--allow-write" in bad_tool["error"]["message"]


def test_serve_loop_reads_one_message_per_line(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """stdio 主循环：一行一个消息、一行一个回复；通知不占行；坏 JSON 回 -32700。"""
    lines = [
        json.dumps(_req(1, "initialize", {})),
        json.dumps(_req(None, "notifications/initialized")),  # 通知：不回
        "{这不是 JSON",  # 解析错：回 -32700
        json.dumps(_req(2, "tools/list")),
        "",  # 空行：跳过
    ]
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n".join(lines) + "\n"))
    monkeypatch.setattr(sys, "stdout", out)
    code = server.serve(["--db", str(db_path)])
    assert code == cli_mod.EXIT_OK
    replies = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
    assert len(replies) == 3, replies
    assert replies[0]["result"]["serverInfo"]["name"] == "timeflow"
    assert replies[1]["error"]["code"] == server.JSONRPC_PARSE_ERROR
    assert [t["name"] for t in replies[2]["result"]["tools"]] == [c.name for c in registry.COMMANDS]


def test_serve_rejects_unknown_arguments(db_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert server.serve(["--nope"]) == cli_mod.EXIT_USAGE
    assert "--nope" in capsys.readouterr().err
    assert server.serve(["--db"]) == cli_mod.EXIT_USAGE
    assert server.serve(["--help"]) == cli_mod.EXIT_OK
    assert "timeflow mcp" in capsys.readouterr().out


# ------------------------------------------------------------------ 真 stdio（子进程）


def _talk(messages: list[dict[str, Any]], args: list[str]) -> tuple[list[dict[str, Any]], str, int]:
    """真起一个子进程，把消息一行一行喂进去，把回复一行一行读回来。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["TF_LOG_PATH"] = "off"
    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-c", SERVER_SNIPPET, *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=str(ROOT),
    )
    payload = "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in messages)
    out, err = proc.communicate(payload, timeout=180)
    replies = [json.loads(line) for line in out.splitlines() if line.strip()]
    return replies, err, proc.returncode


def test_real_stdio_round_trip_lists_tools_and_writes_a_memo(db_path: Path) -> None:
    """★ 端到端：真子进程 + 真 stdio。

    三件事一起验：① stdout 上**只有** JSON-RPC（日志在 stderr）；
    ② `--allow-write` 从 args 里给（MCP 客户端的配置就是这样）；
    ③ `tools/call` 真把备忘录写进了库（读回来对上）。
    """
    hello = _req(1, "initialize", {"protocolVersion": "2025-06-18"})
    listing = _req(2, "tools/list")
    call = _call("memo", {"text": "MCP 写的一条"})
    call["id"] = 3
    replies, err, code = _talk([hello, listing, call], ["--db", str(db_path), "--allow-write"])
    assert code == cli_mod.EXIT_OK, err
    assert [r["id"] for r in replies] == [1, 2, 3], replies
    names = [t["name"] for t in replies[1]["result"]["tools"]]
    assert "memo" in names and "today" in names
    result = replies[2]["result"]
    assert result["isError"] is False
    assert "id" in json.loads(result["content"][0]["text"])

    memos = TestClient(create_app(str(db_path))).get("/api/memos").json()
    assert [m["text"] for m in memos] == ["MCP 写的一条"]


def test_real_stdio_without_the_switch_has_no_write_tools_and_writes_nothing(
    db_path: Path,
) -> None:
    """同一个子进程，不给开关：清单里没有 `memo`，硬调它得到 `isError`，库里也没有它。"""
    replies, err, code = _talk(
        [
            _req(1, "tools/list"),
            _call("memo", {"text": "不该出现"}),
        ],
        ["--db", str(db_path)],
    )
    assert code == cli_mod.EXIT_OK, err
    names = [t["name"] for t in replies[0]["result"]["tools"]]
    assert "memo" not in names and "today" in names
    assert replies[1]["error"]["code"] == server.JSONRPC_INVALID_PARAMS
    assert TestClient(create_app(str(db_path))).get("/api/memos").json() == []
