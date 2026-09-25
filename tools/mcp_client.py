"""独立实现的最小 MCP 客户端（T-G78）—— 一行一个 JSON-RPC 消息，走 stdio。

## 为什么要有它（它补的是哪个盲区）

T-G65 手写了 MCP 服务端，`tests/test_mcp_line.py` 也真起子进程走过 stdio —— 但那两边的**作者、
假设、读法**是同一套：服务端把"我们理解的消息"当成"规范的消息"，测试再把服务端的回话当成对的。
T-G74 就是这一族病发作的现场：**stdout 中文是 GBK**，而当时的"真 stdio"测试带着 `-X utf8`
（正好把要验的那件事关掉了），一路全绿。
T-G69/T-G71 那族也写着同一句话：**判据自己会在错的地方替被测者兜底**。

所以这一份客户端是**另写一遍**的，而且是**故意按最挑的读法**写：

- **不 import 这个项目的任何东西**（连 `timeflow` 三个字都不 import，有源码级护栏钉着）——
  它只认命令行、字节和 JSON。客户端里没有一个从服务端借来的常量。
- **协议这一层自己判**：`jsonrpc` 必须是 `"2.0"`；`id` 必须**原样（含类型）**回来；
  `result` 与 `error` 不许同时出现、也不许都不出现；`tools/list` 里每个工具的
  `inputSchema` 必须是对象、`required` 里每一项都得**真的在 properties 里**；
  `tools/call` 的结果必须有 `content[0].text`。任何一条不成立就**判协议违规**（退出码 2）——
  而不是"看着像就算了"。
- **id 用字符串**（`tf-1`、`tf-2`…）：规范允许字符串 id，而"整数 id 才管用"这种假设，
  自家测试里是看不出来的。
- **读的是原始字节**：回话先按 **UTF-8** 解，解不开就是协议违规（不是"换个编码再试试"）。

## 用法（也当"第三方客户端"的手动替身）

    python -X utf8 tools/mcp_client.py handshake          # 握手：协议版本 / 能力 / 服务端身份
    python -X utf8 tools/mcp_client.py list               # 工具清单（逐条自检 schema）
    python -X utf8 tools/mcp_client.py call today         # 调一个只读工具，打印它的 JSON
    python -X utf8 tools/mcp_client.py call add-task --arg title=写点什么 --allow-write
    python -X utf8 tools/mcp_client.py raw '{"jsonrpc":"2.0","id":"x","method":"nope"}'

服务端命令怎么给（三选一，优先上面的）：

    1. `--server-json '["timeflow","mcp"]'`
    2. 环境变量 `TIMEFLOW_MCP_SERVER`（**JSON 数组**，省得在 Windows 上跟引号打架）
    3. 默认 `timeflow mcp`（就是 DSH / Claude Desktop 那种配法）

## 退出码（机器可读的那半）

    0 一切正常 / 2 **协议违规**（回话不符合规范，客户端当场判它不合格）/ 3 服务端起不来
    4 工具执行失败（服务端如实回了 `isError:true`）/ 5 服务端回了 JSON-RPC 错误 / 6 超时

★ 边界（不假装）：这只是**最小**客户端 —— 没有 resources / prompts / sampling / 进度通知，
不做 SSE；它证明的是"stdio + JSON-RPC 这一层按规范能不能被另一个实现读懂"。
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading

#: 客户端自己认识的那几个协议版本（**在客户端这一侧**写死，不从服务端抄）
KNOWN_PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18")
WANT_PROTOCOL = "2025-06-18"

DEFAULT_SERVER = ("timeflow", "mcp")
DEFAULT_TIMEOUT = 30.0

EXIT_OK = 0
EXIT_PROTOCOL = 2
EXIT_SPAWN = 3
EXIT_TOOL = 4
EXIT_RPC = 5
EXIT_TIMEOUT = 6


class ProtocolError(Exception):
    """回话不符合 MCP/JSON-RPC 规范 —— 这是**客户端这一侧的判决**，不是"服务端报错了"。"""


class RpcError(Exception):
    """服务端回了一条 JSON-RPC 错误（合法，但这次调用失败了）。"""

    def __init__(self, code: object, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


# ------------------------------------------------------------------ 自检（客户端自己的判据）
def check_envelope(message: object, want_id: object) -> dict:
    """一条回话的**信封**：这三条不成立就没法继续谈了。"""
    if not isinstance(message, dict):
        raise ProtocolError("回话不是 JSON 对象")
    if message.get("jsonrpc") != "2.0":
        raise ProtocolError(f"jsonrpc 不是 '2.0'：{message.get('jsonrpc')!r}")
    if "id" not in message:
        raise ProtocolError("回话里没有 id（请求带了 id，服务端必须原样回）")
    got = message["id"]
    if got != want_id or type(got) is not type(want_id):
        raise ProtocolError(f"id 没有原样回来：发的是 {want_id!r}（{type(want_id).__name__}），"
                                f"回的是 {got!r}（{type(got).__name__}）")
    has_result, has_error = "result" in message, "error" in message
    if has_result and has_error:
        raise ProtocolError("result 与 error 同时出现")
    if not has_result and not has_error:
        raise ProtocolError("既没有 result 也没有 error")
    if has_error:
        err = message["error"]
        if not isinstance(err, dict) or "code" not in err or "message" not in err:
            raise ProtocolError(f"error 不是 {{code, message}} 形状：{err!r}")
        raise RpcError(err["code"], str(err["message"]))
    return message


def check_initialize(result: object) -> dict:
    """握手结果：版本要在**客户端认识的**那几个里、能力与身份都得说清楚。"""
    if not isinstance(result, dict):
        raise ProtocolError("initialize 的 result 不是对象")
    version = result.get("protocolVersion")
    if version not in KNOWN_PROTOCOLS:
        raise ProtocolError(f"protocolVersion 不在客户端认识的版本里：{version!r}"
                                f"（认识：{'、'.join(KNOWN_PROTOCOLS)}）")
    caps = result.get("capabilities")
    if not isinstance(caps, dict) or not isinstance(caps.get("tools"), dict):
        raise ProtocolError(f"capabilities.tools 缺失或不是对象：{caps!r}")
    info = result.get("serverInfo")
    if not isinstance(info, dict) or not isinstance(info.get("name"), str) or not info["name"]:
        raise ProtocolError(f"serverInfo.name 缺失：{info!r}")
    if not isinstance(info.get("version"), str) or not info["version"]:
        raise ProtocolError(f"serverInfo.version 缺失：{info!r}")
    return result


def check_tools(tools: object) -> list[dict]:
    """工具清单：名字唯一、schema 是对象、**required 里每一项都真的在 properties 里**。"""
    if not isinstance(tools, list) or not tools:
        raise ProtocolError(f"tools 不是非空数组：{type(tools).__name__}")
    seen: set[str] = set()
    for tool in tools:
        if not isinstance(tool, dict):
            raise ProtocolError(f"工具不是对象：{tool!r}")
        name = tool.get("name")
        if not isinstance(name, str) or not name:
            raise ProtocolError(f"工具有个空名字：{tool!r}")
        if name in seen:
            raise ProtocolError(f"工具名重复：{name}")
        seen.add(name)
        if not isinstance(tool.get("description"), str) or not tool["description"]:
            raise ProtocolError(f"{name} 没有 description")
        schema = tool.get("inputSchema")
        if not isinstance(schema, dict):
            raise ProtocolError(f"{name} 的 inputSchema 不是对象")
        if schema.get("type") != "object":
            raise ProtocolError(f"{name} 的 inputSchema.type 不是 'object'：{schema.get('type')!r}")
        props = schema.get("properties", {})
        if not isinstance(props, dict):
            raise ProtocolError(f"{name} 的 properties 不是对象")
        required = schema.get("required", [])
        if not isinstance(required, list) or not all(isinstance(x, str) for x in required):
            raise ProtocolError(f"{name} 的 required 不是字符串数组：{required!r}")
        missing = [x for x in required if x not in props]
        if missing:
            raise ProtocolError(f"{name} 的 required 里有 properties 里没有的参数：{missing}")
        if schema.get("additionalProperties") is not False:
            raise ProtocolError(
                f"{name} 的 additionalProperties 不是 false（客户端无从判断多余参数）"
            )
    return tools


def check_tool_result(result: object) -> dict:
    """`tools/call` 的结果：MCP 规定至少一段 text 内容 + 一个 isError 布尔。"""
    if not isinstance(result, dict):
        raise ProtocolError("tools/call 的 result 不是对象")
    content = result.get("content")
    if not isinstance(content, list) or not content:
        raise ProtocolError(f"content 不是非空数组：{content!r}")
    first = content[0]
    has_text = isinstance(first, dict) and first.get("type") == "text"
    if not has_text or not isinstance(first.get("text"), str):
        raise ProtocolError(f"content[0] 不是 {{type:'text', text:…}}：{first!r}")
    if not isinstance(result.get("isError"), bool):
        raise ProtocolError(f"isError 不是布尔：{result.get('isError')!r}")
    return result


# ------------------------------------------------------------------ 传输（字节 + 一行一条）
class Client:
    """最小 stdio 客户端：写一行 UTF-8 字节、读一行 UTF-8 字节。

    读用**后台线程 + 队列**：管道上的 `readline()` 在 Windows 上没法 select，
    没有超时的话"服务端不回话"会让这个工具**永远挂着** —— 一个验证工具自己卡死是最糟的形态。
    stderr 也单独收（不排空管道会让子进程写满缓冲后自己卡住）。
    """

    def __init__(self, argv: list[str], timeout: float = DEFAULT_TIMEOUT) -> None:
        self.argv = argv
        self.timeout = timeout
        try:
            self.proc = subprocess.Popen(
                argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
        except OSError as exc:
            raise ProtocolError(f"起不了服务端 {argv!r}：{exc}") from exc
        self._lines: queue.Queue[bytes | None] = queue.Queue()
        self._err: list[str] = []
        self._n = 0
        threading.Thread(target=self._pump_stdout, daemon=True).start()
        threading.Thread(target=self._pump_stderr, daemon=True).start()

    def _pump_stdout(self) -> None:
        assert self.proc.stdout is not None
        for raw in self.proc.stdout:
            self._lines.put(raw)
        self._lines.put(None)  # EOF

    def _pump_stderr(self) -> None:
        assert self.proc.stderr is not None
        for raw in self.proc.stderr:
            self._err.append(raw.decode("utf-8", errors="replace"))

    @property
    def stderr_text(self) -> str:
        return "".join(self._err).strip()

    def send_raw(self, line: str) -> None:
        """发一行**原文**（用来发坏 JSON / 坏字节那种协议用例）。"""
        self.send_bytes(line.encode("utf-8"))

    def send_bytes(self, data: bytes) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def read_message(self) -> dict:
        """读一条回话（原始字节 → UTF-8 → JSON），顺手把信封判了。"""
        try:
            raw = self._lines.get(timeout=self.timeout)
        except queue.Empty as exc:
            raise ProtocolError(f"服务端 {self.timeout:.0f} 秒没有回话") from exc
        if raw is None:
            raise ProtocolError("服务端没有回话就关掉了 stdout（EOF）"
                                    + (f"；它的 stderr：{self.stderr_text[:200]}"
                                       if self.stderr_text else ""))
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError(
                f"回话不是 UTF-8（规范要求 stdio 上的消息是 UTF-8）：{exc}；原始字节开头 "
                f"{raw[:24]!r}"
            ) from exc
        if not text.endswith("\n"):
            raise ProtocolError("一条消息没有以换行结束（framing 应当是「一行一条」）")
        try:
            message = json.loads(text)
        except ValueError as exc:
            raise ProtocolError(f"回话不是合法 JSON：{exc}；原文 {text[:120]!r}") from exc
        return message

    def notify(self, method: str, params: dict | None = None) -> None:
        """发一条**通知**（没有 id）：按规范服务端**不许回**，所以这里也不读。"""
        self.send_raw(json.dumps(
            {"jsonrpc": "2.0", "method": method, "params": params or {}},
            ensure_ascii=False) + "\n")

    def request(self, method: str, params: dict | None = None) -> dict:
        """发一条请求并读回话（id 用**字符串** —— 规范允许，而"只有整数 id 才管用"这种假设
        在自家测试里看不出来）。返回 `result`；服务端回错误则抛 `RpcError`。"""
        self._n += 1
        want_id = f"tf-{self._n}"
        self.send_raw(json.dumps(
            {"jsonrpc": "2.0", "id": want_id, "method": method, "params": params or {}},
            ensure_ascii=False) + "\n")
        return check_envelope(self.read_message(), want_id)["result"]

    def handshake(self) -> dict:
        result = check_initialize(self.request("initialize", {
            "protocolVersion": WANT_PROTOCOL,
            "capabilities": {},
            "clientInfo": {"name": "timeflow-minimal-client", "version": "1.0"},
        }))
        self.notify("notifications/initialized")
        return result

    def close(self) -> int:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover —— 服务端不理 EOF 才会到这儿
            self.proc.kill()
        return int(self.proc.returncode or 0)


# ------------------------------------------------------------------ 命令行
def _server_argv(args: argparse.Namespace) -> list[str]:
    if args.server_json:
        raw = args.server_json
    elif os.environ.get("TIMEFLOW_MCP_SERVER"):
        raw = os.environ["TIMEFLOW_MCP_SERVER"]
    else:
        return list(DEFAULT_SERVER) + list(args.server_arg)
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise SystemExit(f"--server-json / TIMEFLOW_MCP_SERVER 不是合法 JSON：{exc}") from exc
    if not isinstance(parsed, list) or not parsed or not all(isinstance(x, str) for x in parsed):
        raise SystemExit("服务端命令必须是非空的字符串数组，例如 '[\"timeflow\",\"mcp\"]'")
    return list(parsed) + list(args.server_arg)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    # 全局选项在**子命令前后都能写**（`--json handshake` 与 `handshake --json` 都认）：
    # 用 `parents=[common]` 让两边都认识它们 —— 客户端是给人敲的，位置不该成为坑。
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--server-json", help='服务端命令（JSON 数组），如 \'["timeflow","mcp"]\'')
    common.add_argument("--server-arg", action="append", default=[],
                        help="追加到服务端命令后面的参数（可重复），如 --server-arg --allow-write")
    common.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    common.add_argument("--json", action="store_true", help="连原始回话一起打出来")
    ap = argparse.ArgumentParser(
        prog="mcp_client.py", parents=[common],
        description="独立实现的最小 MCP 客户端（stdio，一行一个 JSON-RPC 消息）",
    )
    sub = ap.add_subparsers(dest="action", required=True)
    sub.add_parser("handshake", parents=[common], help="握手：协议版本 / 能力 / 服务端身份")
    sub.add_parser("list", parents=[common], help="列出工具（逐条自检 inputSchema）")
    call = sub.add_parser("call", parents=[common], help="调一个工具")
    call.add_argument("name")
    call.add_argument("--arg", action="append", default=[],
                      help="参数（可重复）：--arg title=写点什么；值一律当字符串，"
                           "`true`/`false`/纯数字会按 JSON 解析")
    sub.add_parser("raw", parents=[common],
                   help="发一条原文消息（协议用例用）").add_argument("message")
    return ap.parse_args(argv)


def _arg_value(raw: str) -> object:
    """`--arg k=v` 的值：先按 JSON 解（true/false/数字），解不开就当字符串。"""
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _run(args: argparse.Namespace) -> int:
    argv = _server_argv(args)
    if args.action == "raw":
        client = Client(argv, timeout=args.timeout)
        try:
            client.send_raw(args.message if args.message.endswith("\n") else args.message + "\n")
            message = client.read_message()
            print(json.dumps(message, ensure_ascii=False, indent=2) if args.json
                  else json.dumps(message, ensure_ascii=False))
            return EXIT_RPC if "error" in message else EXIT_OK
        finally:
            client.close()

    client = Client(argv, timeout=args.timeout)
    try:
        info = client.handshake()
        if args.action == "handshake":
            if args.json:
                print(json.dumps(info, ensure_ascii=False, indent=2))
                return EXIT_OK
            print(f"协议版本 {info['protocolVersion']} · 服务端 {info['serverInfo']['name']} "
                  f"{info['serverInfo']['version']} · 能力 {sorted(info['capabilities'])}")
            if info.get("instructions"):
                print(f"说明：{info['instructions']}")
            return EXIT_OK
        listed = client.request("tools/list")
        if not isinstance(listed, dict) or "tools" not in listed:
            raise ProtocolError(f"tools/list 的 result 不是 {{tools: [...]}}：{listed!r}")
        tools = check_tools(listed["tools"])
        if args.action == "list":
            if args.json:
                print(json.dumps(tools, ensure_ascii=False, indent=2))
            else:
                for tool in tools:
                    ann = tool.get("annotations") or {}
                    write = "写" if ann.get("readOnlyHint") is False else "只读"
                    print(f"  {tool['name']:<14} {write:<4} {tool['description']}")
                print(f"共 {len(tools)} 个工具（每条的 inputSchema 都已自检通过）")
            return EXIT_OK
        arguments: dict[str, object] = {}
        for pair in args.arg:
            key, _, value = pair.partition("=")
            if not key or not _:
                raise SystemExit(f"--arg 要写成 k=v 的样子：{pair!r}")
            arguments[key] = _arg_value(value)
        asked = {"name": args.name, "arguments": arguments}
        result = check_tool_result(client.request("tools/call", asked))
        text = result["content"][0]["text"]
        print(text)
        return EXIT_TOOL if result["isError"] else EXIT_OK
    finally:
        client.close()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return _run(args)
    except RpcError as exc:
        print(f"服务端回了 JSON-RPC 错误：{exc}", file=sys.stderr)
        return EXIT_RPC
    except ProtocolError as exc:
        print(f"❌ 协议违规：{exc}", file=sys.stderr)
        return EXIT_PROTOCOL
    except KeyboardInterrupt:  # pragma: no cover
        return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
