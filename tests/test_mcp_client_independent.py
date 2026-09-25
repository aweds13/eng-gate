"""T-G78：**独立实现的最小 MCP 客户端**（`tools/mcp_client.py`）—— 用它去读我们的服务端。

## 这一层补的是哪个盲区

服务端是 T-G65 手写的，`tests/test_mcp_line.py` 也真起子进程走过 stdio —— 但那两边的作者、
假设、读法**是同一套**：服务端把"我们理解的消息"当"规范的消息"，测试再把服务端的回话当成对的。
T-G74 就是这一族发作的现场（stdout 中文是 GBK，而当时的"真 stdio"测试带着 `-X utf8`
—— 正好把要验的那件事关掉了，一路全绿）。T-G69/T-G71 那族写着同一句话：
**判据自己会在错的地方替被测者兜底**。

所以这一份客户端是**另写一遍**的，而且**不 import 这个项目的任何东西**（有源码级护栏），
并**故意按最挑的读法**读：`id` 必须原样（含类型）回来、`required` 里每一项都得真在 `properties` 里、
回话必须是 UTF-8 字节、`tools/call` 必须有 `content[0].text`。

## 这些用例在问什么

- 握手：另一个实现能不能读懂（协议版本 / 能力 / 身份），而不是"我们自己的测试说通了"；
- 清单：**客户端的自检真的会咬**（用两个"坏服务端"证明它不是恒真判据）；
- 错误码：不认的方法 `-32601`、隐藏的写工具 `-32602`（并且说清怎么开）；
- 写入：开了开关之后，**中文标题一字不差**（T-G74 那条缺陷的独立复核）；
- 工具失败：服务端如实回 `isError`，客户端按退出码 4 报出来（不是假装成功）。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app

ROOT = Path(__file__).resolve().parent.parent
CLIENT = ROOT / "tools" / "mcp_client.py"
SERVER = ROOT / "src" / "timeflow" / "mcp" / "server.py"


def make_db(path: Path) -> Path:
    """建一个空的真库（走**真 HTTP 边界**，与 `tests/test_mcp_line.py` 同一条路）。

    为什么要建：CLI/MCP 对"库不存在"是**拒绝**的（T-G66：只读命令不许静默建库，
    写命令也不替人开库）—— 所以想验写入，得先有一个库。
    ★ 注意"独立"说的是**客户端**（`tools/mcp_client.py` 不 import 本项目，有护栏钉着），
    pytest 这一层当然可以用产品自己建库。
    """
    TestClient(create_app(str(path))).get("/api/tasks")
    return path


EXIT_OK, EXIT_PROTOCOL, EXIT_TOOL, EXIT_RPC = 0, 2, 4, 5

#: 服务端怎么起：**跟 DSH / Claude Desktop 那种配法同一条路**（真子进程、真 stdio）。
SERVER_SNIPPET = "import sys; from timeflow.cli.main import main; sys.exit(main())"

#: 故意坏掉的"服务端"（证明客户端那些判据不是恒真的）。
#: ① 把客户端发来的**字符串 id 变成整数** —— 规范要求原样回来，客户端必须当场判它不合格。
FAKE_BAD_ID = """
import json, sys
for line in sys.stdin:
    msg = json.loads(line)
    if 'id' not in msg:
        continue
    n = int(str(msg['id']).split('-')[-1])
    out = {'jsonrpc': '2.0', 'id': n,
           'result': {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}},
                      'serverInfo': {'name': 'fake', 'version': '1'}}}
    sys.stdout.write(json.dumps(out) + chr(10)); sys.stdout.flush()
"""

#: ② `tools/list` 里 `required` 写了一个 properties 里根本没有的参数 —— 客户端必须拦下。
FAKE_BAD_SCHEMA = """
import json, sys
for line in sys.stdin:
    msg = json.loads(line)
    if 'id' not in msg:
        continue
    if msg.get('method') == 'initialize':
        result = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}},
                  'serverInfo': {'name': 'fake', 'version': '1'}}
    else:
        result = {'tools': [{'name': 'x', 'description': 'd',
                             'inputSchema': {'type': 'object', 'properties': {},
                                             'required': ['nope'], 'additionalProperties': False}}]}
    sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': result})
                     + chr(10)); sys.stdout.flush()
"""


def _server_argv(*extra: str) -> str:
    """把服务端命令塞进 `TIMEFLOW_MCP_SERVER`（JSON 数组，省得跟 Windows 的引号打架）。"""
    return json.dumps([sys.executable, "-X", "utf8", "-c", SERVER_SNIPPET, "mcp", *extra],
                      ensure_ascii=False)


def run_client(*args: str, server: str | None = None, timeout: float = 60.0
               ) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "TIMEFLOW_MCP_SERVER": server if server is not None else _server_argv()}
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(CLIENT), *args],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, check=False,
    )


# ------------------------------------------------------------------ 它真的独立吗
def test_client_does_not_import_the_product() -> None:
    """★ 这一条是整张卡的前提：客户端**不许** import 这个项目的任何东西。

    它要是 import 了 `timeflow.mcp`（哪怕只是借一个常量），"另一个实现读懂了协议"这句话
    就变成"同一套假设自己点了点头" —— 那正是 T-G74 全绿的原因。
    """
    source = CLIENT.read_text(encoding="utf-8")
    imports = [ln.strip() for ln in source.splitlines()
               if re.match(r"^\s*(import|from)\s+", ln)]
    assert imports, "客户端里一条 import 都没有？那这份源码多半没读到"
    offenders = [ln for ln in imports if "timeflow" in ln.lower()]
    assert not offenders, f"客户端不许 import 本项目的东西：{offenders}"
    # 也别用"路径拼接去读服务端源码"这种绕法
    for needle in ("src/timeflow", "src\\timeflow", "mcp/server.py"):
        assert needle not in source, f"客户端里出现了服务端路径：{needle}"
    # 两份文件必须是各自独立的实现（同一个文件被复制过去不算"另一个实现"）
    assert CLIENT.read_text(encoding="utf-8") != SERVER.read_text(encoding="utf-8")


def test_handshake_is_read_by_another_implementation() -> None:
    """握手：协议版本 / 能力 / 身份 —— 由**客户端那一侧**的判据验收。"""
    proc = run_client("handshake", "--json")
    assert proc.returncode == EXIT_OK, proc.stderr + proc.stdout
    info = json.loads(proc.stdout)
    assert info["protocolVersion"] == "2025-06-18"
    assert "tools" in info["capabilities"]
    assert info["serverInfo"]["name"] == "timeflow"
    assert proc.stderr.strip() == "", f"握手不该往 stderr 写东西：{proc.stderr!r}"


def test_tool_list_passes_an_independent_schema_check() -> None:
    """工具清单：客户端逐条查 `inputSchema`（`required` 必须在 `properties` 里）。"""
    proc = run_client("list", "--json")
    assert proc.returncode == EXIT_OK, proc.stderr + proc.stdout
    tools = json.loads(proc.stdout)
    assert len(tools) >= 14, f"只读工具应有 14 个，实际 {len(tools)}"
    names = {t["name"] for t in tools}
    for known in ("today", "tasks", "week", "board", "sync"):
        assert known in names
    # 默认关：写工具**一个都不列**（这是用户 2026-09-25 定的口径）
    for hidden in ("add-task", "complete", "myday", "focus-start", "focus-finish", "memo"):
        assert hidden not in names, f"没开写就把写工具列出来了：{hidden}"
    assert all(t["annotations"]["readOnlyHint"] is True for t in tools)


def test_string_ids_are_echoed_and_unknown_methods_are_rejected() -> None:
    """`id` 用**字符串**（规范允许）—— 回话必须原样带类型回来；不认的方法回 `-32601`。"""
    proc = run_client("raw", '{"jsonrpc":"2.0","id":"t-7","method":"没有这个方法"}')
    assert proc.returncode == EXIT_RPC, proc.stderr + proc.stdout
    reply = json.loads(proc.stdout)
    assert reply["id"] == "t-7" and isinstance(reply["id"], str), reply
    assert reply["error"]["code"] == -32601, reply
    assert "没有这个方法" in reply["error"]["message"]


@pytest.mark.parametrize(
    "fake, needle",
    [
        (FAKE_BAD_ID, "id 没有原样回来"),
        (FAKE_BAD_SCHEMA, "required 里有 properties 里没有的参数"),
    ],
)
def test_the_clients_judgements_actually_bite(fake: str, needle: str) -> None:
    """★ 反空转：拿两个**故意坏掉的服务端**证明客户端真的会判它不合格。

    没有这一条，"通过了客户端的自检"就可能只是"客户端什么都没查"（恒真判据）。
    两个坏法各挑一条规范：`id` 的类型、`required` 与 `properties` 的一致性。
    """
    server = json.dumps([sys.executable, "-X", "utf8", "-c", fake], ensure_ascii=False)
    args = ("handshake",) if fake is FAKE_BAD_ID else ("list",)
    proc = run_client(*args, server=server)
    assert proc.returncode == EXIT_PROTOCOL, proc.stderr + proc.stdout
    assert needle in proc.stderr, f"判据没说清哪儿不对：{proc.stderr!r}"


def test_write_tools_need_the_flag_and_chinese_survives(tmp_path: Path) -> None:
    """开了 `--allow-write` 之后：写工具出现、调用成功、**中文一字不差**（T-G74 独立复核）。"""
    db = str(tmp_path / "mcp-client.db")
    readonly = run_client("list", "--json")
    assert "add-task" not in {t["name"] for t in json.loads(readonly.stdout)}

    allowing = _server_argv("--allow-write", "--db", db)
    # ① 没开写时调写工具：服务端说"没有这个工具"，并把怎么开写写在里面
    refused = run_client("call", "add-task", "--arg", "title=不该写进去",
                         server=_server_argv("--db", db))
    assert refused.returncode == EXIT_RPC, refused.stderr + refused.stdout
    assert "写操作" in refused.stderr and "--allow-write" in refused.stderr, refused.stderr
    assert not Path(db).exists(), "被拒的写操作不许留下库文件"

    # ② 建一个空库（CLI/MCP 不替人开库）→ 开了写：工具列出来、调用成功
    make_db(Path(db))
    listed = run_client("list", "--json", server=allowing)
    tools = {t["name"]: t for t in json.loads(listed.stdout)}
    assert "add-task" in tools and tools["add-task"]["annotations"]["readOnlyHint"] is False
    title = "中文标题：一个字都不许变（·、（）也算）"
    made = run_client("call", "add-task", "--arg", f"title={title}", server=allowing)
    assert made.returncode == EXIT_OK, made.stderr + made.stdout

    # ③ 从另一个只读工具读回来（同一个库）—— 中文一字不差
    back = run_client("call", "tasks", server=_server_argv("--db", db))
    assert back.returncode == EXIT_OK, back.stderr + back.stdout
    assert title in back.stdout, f"中文没原样回来：{back.stdout[:200]}"


def test_tool_failure_is_reported_by_the_client_not_swallowed(tmp_path: Path) -> None:
    """工具执行失败：服务端如实回 `isError`（不是 JSON-RPC 错误），客户端按退出码 4 报出来。"""
    missing = str(tmp_path / "没有这个库" / "x.db")
    proc = run_client("call", "today", server=_server_argv("--db", missing))
    assert proc.returncode == EXIT_TOOL, proc.stderr + proc.stdout
    assert "db_missing" in proc.stdout, proc.stdout
    assert not Path(missing).exists(), "只读命令不许把库建出来"
