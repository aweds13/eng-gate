"""MCP 服务端（stdio · JSON-RPC 2.0）—— **工具清单由命令表生成，调用直接走 CLI**。

## 协议这一半（自己实现，零依赖）

一行一个 JSON-RPC 消息（MCP 的 stdio 传输就是这个framing）。实现了三个方法：

| 方法 | 回什么 |
|---|---|
| `initialize` | 协议版本 + `capabilities.tools` + `serverInfo`（+ 一段 `instructions` 说明边界） |
| `tools/list` | 由 `timeflow.cli.registry` 现算的工具清单（**只读工具 + 开了开关才有的写工具**） |
| `tools/call` | 把参数翻成 argv → 调 `timeflow.cli.main.main()` → 把它的 JSON 原样当结果 |

不认的方法回 `-32601`，不认的工具名回 `-32602`（写工具在没开开关时就走这一条）。
通知（没有 `id` 的消息）一律不回 —— 这是 JSON-RPC 的规矩，也是 MCP 客户端不会卡住的前提。

## "语义与界面完全一样"是怎么保证的

`tools/call` **不重新实现参数解析**：它把 MCP 的参数翻成命令行 argv，调 `timeflow.cli.main.main()`，
再把命令打出来的 JSON 原样当 tool result 回去。所以

  · 写操作的落库效果、校验、错误码 = 人在终端里敲那一条命令；
  · 参数 schema 来自同一个 `registry`（MCP 的 `inputSchema` 就是它的投影）；
  · 工具清单也来自同一个 `registry` —— 而 `scripts/check_commands.py` 的「MCP 投影」一节
    逐条证明它与 `docs/commands.toml` 双向对得上。

## 默认关（用户 2026-09-25 的口径）

`timeflow mcp` 不给 `--allow-write` → **写工具不列出**；就算客户端凭记忆硬调，
`tools/call` 也会回一条 JSON-RPC 错误说清楚"写工具要先开开关"。
开关与 CLI 是**同一个常量**（`timeflow.cli.main.WRITE_FLAG`），不另立一个说法。

## 诚实边界（别把它当已经验过的 MCP 兼容性）

- 我们**没有**第三方 MCP SDK（本项目零依赖），所以握手是按规范手写的：
  验的是"我们的客户端脚本 ↔ 我们的服务端"（`tests/test_mcp_line.py` 里真起了子进程走 stdio）。
  第三方客户端（Claude Desktop / DSH 之类）里能不能直接用，**要人工接一次**才算验过 ——
  这一条写进了盘点清单，不在这里声称"兼容"。
- 传输只做 **stdio**（没做 HTTP/SSE 那种）：本地工具，够用且最省事。
- `tools/list` 里**没有** `resources` / `prompts` / `logging`：只有工具。
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from typing import TYPE_CHECKING, Any

from timeflow.cli import main as cli_main
from timeflow.cli import registry

if TYPE_CHECKING:  # pragma: no cover —— 只为类型注解
    from timeflow.cli.registry import Command

#: 我们支持的协议版本（`initialize` 时优先回客户端那个"我们认识"的版本）
PROTOCOL_VERSION = "2025-06-18"
KNOWN_PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18")
SERVER_NAME = "timeflow"

JSONRPC_PARSE_ERROR = -32700
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602

_MODESTR = {"int": "integer", "bool": "boolean", "str": "string"}


def _default_value(param: registry.Param) -> Any:
    """把声明的默认值翻成 JSON 里的真类型（`"false"` → `false`、`"14"` → `14`）。"""
    raw = param.default
    if raw is None:
        return None
    if param.kind == "int":
        return int(raw)
    if param.kind == "bool":
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return raw


def tool_schema(command: Command) -> dict[str, Any]:
    """一条命令 → 一个 MCP 工具（`inputSchema` 就是参数表的投影，不另写一份）。"""
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param in command.params:
        entry: dict[str, Any] = {"type": _MODESTR.get(param.kind, "string")}
        entry["description"] = param.help
        default = _default_value(param)
        if default is not None:
            entry["default"] = default
        elif param.required:
            required.append(param.name)
        properties[param.name] = entry
    write = registry.is_write(command)
    kind_note = "写操作，会改数据" if write else "只读"
    tool: dict[str, Any] = {
        "name": command.name,
        "description": f"{command.title}（契约 {command.op}；{kind_note}）",
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
        # MCP 的 tool annotations：让客户端自己决定要不要警告/确认（我们额外用 --allow-write 兜底）
        "annotations": {"readOnlyHint": not write, "openWorldHint": False},
    }
    return tool


def tool_list(allow_write: bool) -> list[dict[str, Any]]:
    """工具清单 —— **由 registry 现算**（写工具只在开了开关时出现）。"""
    return [
        tool_schema(command)
        for command in registry.all_commands()
        if allow_write or not registry.is_write(command)
    ]


def _tool_argv(
    command: Command, arguments: dict[str, Any], db: str, allow_write: bool
) -> list[str]:
    """MCP 的参数 → 那条命令的 argv（参数名字/类型都来自同一张参数表）。"""
    argv = [command.name]
    for param in command.params:
        if param.name not in arguments or arguments[param.name] is None:
            continue
        flag = "--" + param.name.replace("_", "-")
        value = arguments[param.name]
        if param.kind == "bool":
            argv.append(f"{flag}={'true' if value else 'false'}")
        else:
            argv += [flag, str(value)]
    argv += ["--db", db, "--json"]
    if registry.is_write(command) and allow_write:
        argv.append(cli_main.WRITE_FLAG)
    return argv


def _result(text: str, *, is_error: bool) -> dict[str, Any]:
    """MCP 的 tool result：文本内容 + `isError`（工具执行失败走这里，不是 JSON-RPC 错误）。"""
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def call_tool(
    name: str, arguments: dict[str, Any], *, db: str, allow_write: bool
) -> dict[str, Any] | None:
    """跑一个工具：**走 CLI 那条路**（同一个解析、同一个边界、同一套退出码）。

    返回 `None` = **这个会话里没有这个工具**（不认识的名字，或者没开写时的写工具）——
    调用方把它翻成 JSON-RPC 的 `-32602` 并带上"怎么开"。
    为什么隐藏的写工具也走"没有这个工具"而不是"执行了但失败"：MCP 的规矩是
    「只能调用 `tools/list` 里出现过的工具」，而没开写时我们**就是不列它** ——
    两者必须是同一个判断，否则客户端会以为"这个工具在，只是这次失败了"。
    """
    command = registry.by_name().get(name)
    if command is None:
        return None
    if registry.is_write(command) and not allow_write:
        return None
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli_main.main(_tool_argv(command, arguments or {}, db, allow_write))
    if code == cli_main.EXIT_OK:
        return _result(out.getvalue().strip(), is_error=False)
    detail = err.getvalue().strip() or out.getvalue().strip() or f"退出码 {code}"
    return _result(f"{detail}（退出码 {code}）", is_error=True)


def _initialize(params: dict[str, Any]) -> dict[str, Any]:
    wanted = str(params.get("protocolVersion") or "")
    return {
        "protocolVersion": wanted if wanted in KNOWN_PROTOCOLS else PROTOCOL_VERSION,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": SERVER_NAME, "version": "1.0"},
        "instructions": (
            "timeflow 是本地优先的时间/学习工具，数据在这台机器的一个 SQLite 库里。"
            "只读工具随时可用；写工具（add-task / complete / myday / focus-start / "
            "focus-finish / memo）只在服务端带 --allow-write 启动时才列出。"
            "写入走的是与界面完全相同的那套语义（同一个 HTTP 边界），不新增口径。"
        ),
    }


def handle(message: dict[str, Any], *, db: str, allow_write: bool) -> dict[str, Any] | None:
    """处理一条消息 → 回一条（或 None = 通知，不回）。"""
    method = str(message.get("method") or "")
    has_id = "id" in message
    mid = message.get("id")

    if not has_id:  # 通知（initialized / cancelled / …）：不回，也不报错
        return None

    def ok(result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def bad(code: int, text: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": text}}

    if method == "initialize":
        params = message.get("params")
        return ok(_initialize(params if isinstance(params, dict) else {}))
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": tool_list(allow_write)})
    if method == "tools/call":
        params = message.get("params")
        params = params if isinstance(params, dict) else {}
        name = str(params.get("name") or "")
        arguments = params.get("arguments")
        result = call_tool(
            name,
            arguments if isinstance(arguments, dict) else {},
            db=db,
            allow_write=allow_write,
        )
        if result is None:
            listed = [
                c.name
                for c in registry.all_commands()
                if allow_write or not registry.is_write(c)
            ]
            command = registry.by_name().get(name)
            hint = ""
            if command is not None and registry.is_write(command):
                hint = (
                    f"（{name} 是写操作：这个会话没开写 —— 用"
                    f" `timeflow mcp {cli_main.WRITE_FLAG}` 起它才会出现）"
                )
            return bad(
                JSONRPC_INVALID_PARAMS,
                f"没有这个工具：{name!r}；有：{'、'.join(listed)}{hint}",
            )
        return ok(result)
    return bad(JSONRPC_METHOD_NOT_FOUND, f"不支持的方法：{method}")


def _mcp_usage() -> str:
    return (
        "timeflow mcp —— 把命令作为 MCP 工具提供给 AI 客户端（stdio，一行一个 JSON-RPC 消息）\n"
        "\n"
        "  timeflow mcp                 只读工具\n"
        f"  timeflow mcp {cli_main.WRITE_FLAG}   连写工具一起（默认关）\n"
        "  timeflow mcp --db PATH       换一个库（默认 = 桌面端那个）\n"
        "\n"
        "客户端配置（示例）：command = timeflow，args = [\"mcp\"]\n"
        "stdout 只走协议；日志在 stderr（`TF_LOG_PATH=off` 可关）。\n"
    )


def serve(tail: list[str], *, as_json: bool = False) -> int:
    """stdio 主循环：读一行、处理、回一行。EOF 就退 0。

    `--allow-write` 从 `tail` 里读 —— MCP 客户端的配置就是
    `command = timeflow` / `args = ["mcp", "--allow-write"]`，开关必须能从 args 里给。
    """
    db = cli_main.default_db()  # 与 CLI 同一个默认库（同源，不另开一份数据）
    allow_write = cli_main.WRITE_FLAG in tail
    rest = [arg for arg in tail if arg != cli_main.WRITE_FLAG]
    index = 0
    while index < len(rest):
        token = rest[index]
        if token in ("-h", "--help"):
            print(_mcp_usage())
            return cli_main.EXIT_OK
        if token == "--db":
            if index + 1 >= len(rest):
                print("--db 需要一个值", file=sys.stderr)
                return cli_main.EXIT_USAGE
            db = rest[index + 1]
            index += 2
            continue
        print(
            f"mcp 不认识的参数 {token!r}（只认 --db PATH 与 {cli_main.WRITE_FLAG}）",
            file=sys.stderr,
        )
        return cli_main.EXIT_USAGE

    for line in sys.stdin:
        text = line.strip()
        if not text:
            continue
        try:
            message = json.loads(text)
        except ValueError as exc:
            response: dict[str, Any] = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": JSONRPC_PARSE_ERROR, "message": f"不是合法 JSON：{exc}"},
            }
        else:
            if not isinstance(message, dict):
                response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": JSONRPC_PARSE_ERROR, "message": "消息必须是对象"},
                }
            else:
                answer = handle(message, db=db, allow_write=allow_write)
                if answer is None:
                    continue
                response = answer
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return cli_main.EXIT_OK
