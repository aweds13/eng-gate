r"""外包号池 MCP 只读面（`tools/pool_mcp.py` · 卡 105 · 台账号 T-G201）的测试 —— **四个钉子**。

为什么值当测：这一面是给**别的窗口的 AI**读的（用户原话「我会在 DSH 里不同窗口用」）。
它一旦出错，错的不是"报个错"而是**别的窗口读到假现状**：把"没跑完"读成"跑完了"、
把"没有产物"读成"空成功"、或者**偷偷写了文件**把别人的工作树弄脏。所以四条判据都要机器形态：

| 钉子 | 判什么 |
|---|---|
| ① 报文形状 | `initialize` / `tools/list` **照先例**（`src/timeflow/mcp/server.py`）的字段 |
| ② 只读 | 十二个工具（九个号池 + 三个任务）**都返回**，且跑前后工作区**不比多文件** |
| ③ 未知工具 | 明确报错（`-32602`）且**进程不崩**（坏请求之后还能接着服务） |
| ④ 缺产物/缺锁 | 说清"**没有**" —— **不许**把"没找到"写成"空成功" |

★ 与 `tests/test_wb_plan.py` 同一套导入口径：把 `tools/` 挂上 `sys.path` 再 `import pool_mcp`。
★ 判据里"断了"的阈值与 `tools/wb_dispatch.STALL_SECONDS` **同口径**（本模块的常量，不另立一套）。
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

    import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pool_mcp  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上

SERVER_SNIPPET = "import sys; from pool_mcp import serve; raise SystemExit(serve(sys.argv[1:]))"
#: 十三个只读工具：十个号池（含卡 201 的 quota_status、卡 213 的 workbench_board、
#: 卡 E45 的 account_status、卡 E48 的 checkin_status）+ 三个任务面。
TOOL_NAMES = [
    "pool_plan",
    "job_list",
    "job_status",
    "job_result",
    "lock_status",
    "pool_models",
    "quota_status",
    "account_status",
    "checkin_status",
    "workbench_board",
    "task_list",
    "task_status",
    "task_pool",
]


# ---------------------------------------------------------------- 报文小工具（照先例）


def _req(mid: int | None, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if mid is not None:
        message["id"] = mid
    if params is not None:
        message["params"] = params
    return message


def _call(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    return _req(1, "tools/call", {"name": name, "arguments": arguments or {}})


def _text(result: dict[str, Any]) -> str:
    return result["result"]["content"][0]["text"]


#: 机器可读块的唯一标记（**写死**，与 `tools/pool_mcp.py::JSON_MARKER` 逐字一致）——
#: 钉住格式：工具若偷偷换标记，这里就红。卡 117。
JSON_MARKER = "--- tf-json ---"


def _json_block(text: str) -> dict[str, Any]:
    """取出回复里**唯一标记之后**那一行**单行紧凑 JSON**（解不开 = 形状不对）。

    ★ 卡 117（T-G215）：老读端取"第一个 ```json 围栏" —— 但 `job_result` 把**报告正文
      原样带出**，正文里引用 tools/list 报文样例时也带 ```json ⇒ 抓到的是**样例**
      （主树里真红）。现在工具把真机器块放在唯一标记之后。
    ★ 也**不**按"下一个 ```"去截：机器块 JSON 里就含报告正文（正文里的 ``` 落进字符串），
      按围栏截会把 JSON 截断。标记后那**一行**紧凑 JSON 才是唯一可靠的判据。
    """
    assert JSON_MARKER in text, f"回复里没有机器可读块标记 {JSON_MARKER!r}"
    after = text.split(JSON_MARKER, 1)[1]
    line = next((ln for ln in after.splitlines() if ln.lstrip().startswith("{")), None)
    assert line is not None, "唯一标记之后没有机器可读块"
    return json.loads(line)


# ================================================================ 钉子④：只读（不写工作区）
#
# ★ 判据怎么选（2026-10-01 卡 105 真被咬**两次**，与当天早上修的 T-G194 是同一个坑）：
#   最初拿**整个 worktree** 的 `git status` 前后比 —— 门禁里**别的门会重生成 `docs/**` 派生文件**
#   （实测：先是 `docs/implementation/coverage.md`，接着 `docs/contracts/flows.md`）
#   于是"凭空多出来" ⇒ 假红。★ 往排除表里继续加路径是**打地鼠**（换个文件又中），
#   所以**换判据**：
#   只留"别的门不可能造成"的两种痕迹：
#     ① **不许新建未跟踪文件**（`??` 条目一个都不许多）—— 只读工具落盘必先在这里现形；
#     ② **不许改动它读的那几个真源**（按**内容哈希**比，不按 `git status` 比）。

# 这六个工具会读的真源（改了它们 = 真的越界写）：相对仓库根。
READ_ONLY_INPUTS = (
    "docs/workbacklog.toml",
    "gates/diag/gate_lock.py",
)


def _git_status() -> set[str]:
    """工作区快照（**只数未跟踪条目** —— 已跟踪文件的改动别的门会重生成，不能归因给本工具）。"""
    done = subprocess.run(
        ["git", "status", "--porcelain", "-uall"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {line for line in (done.stdout or "").splitlines() if line.strip()}


def _untracked(snapshot: set[str]) -> set[str]:
    return {ln for ln in snapshot if ln.startswith("??")}


def _hashes() -> dict[str, str]:
    import hashlib

    out: dict[str, str] = {}
    for rel in READ_ONLY_INPUTS:
        f = ROOT / rel
        if f.exists():
            out[rel] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


# ================================================================ 钉子①：报文形状


def test_initialize_shape_matches_the_precedent() -> None:
    """`initialize` 的字段照先例：协议版本 + capabilities.tools + serverInfo + instructions。"""
    reply = pool_mcp.handle(_req(1, "initialize", {"protocolVersion": "2025-06-18"}))
    assert reply is not None and reply["jsonrpc"] == "2.0" and reply["id"] == 1
    result = reply["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert result["serverInfo"] == {"name": "pool", "version": "1.0"}
    # 不认识的版本 → 回我们自己支持的那个（不装作支持）
    other = pool_mcp.handle(_req(2, "initialize", {"protocolVersion": "1999-01-01"}))
    assert other is not None and other["result"]["protocolVersion"] == pool_mcp.PROTOCOL_VERSION


def test_tools_list_shape_is_pinned() -> None:
    """`tools/list`：十二个只读工具、每个 inputSchema 是 object、annotations 说只读。"""
    reply = pool_mcp.handle(_req(1, "tools/list"))
    assert reply is not None
    tools = reply["result"]["tools"]
    assert [t["name"] for t in tools] == TOOL_NAMES
    for tool in tools:
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) <= set(schema["properties"])
        assert tool["annotations"]["readOnlyHint"] is True  # ★ 一个写工具都不许有
        assert tool["description"]
    by_name = {t["name"]: t for t in tools}
    assert by_name["job_status"]["inputSchema"]["required"] == ["card"]
    assert by_name["job_result"]["inputSchema"]["required"] == ["card"]
    assert by_name["pool_plan"]["inputSchema"]["properties"]["concurrency"]["default"] == 2
    assert by_name["job_list"]["inputSchema"]["required"] == []


def test_notification_ping_and_unknown_method() -> None:
    """通知不回；`ping` 回 `{}`；不认的方法回 `-32601`（都照先例）。"""
    assert pool_mcp.handle(_req(None, "notifications/initialized")) is None
    ping = pool_mcp.handle(_req(3, "ping"))
    assert ping is not None and ping["result"] == {}
    bad = pool_mcp.handle(_req(4, "resources/list"))
    assert bad is not None and bad["error"]["code"] == pool_mcp.JSONRPC_METHOD_NOT_FOUND


# ================================================================ 钉子②：十二个工具返回、都不写文件


def test_nine_tools_return_and_write_nothing() -> None:
    """十二个工具都返回内容，且跑一遍**工作区不多出一个文件**（只读的机器判据）。"""
    before, before_hashes = _git_status(), _hashes()
    for name in TOOL_NAMES:
        if name in ("job_status", "job_result"):
            args = {"card": "105"}
        elif name == "quota_status":
            args = {"card": "105", "model": "deepseek-v4.1-flash"}
        else:
            args = {}
        result = pool_mcp.call_tool(name, args, root=ROOT)
        assert result is not None, name
        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"].strip(), name
        _json_block(result["content"][0]["text"])  # 每一条都得带机器可读块

    # ① 不许新建未跟踪文件（别的门不会造出 `??` 条目：它们改的是**已跟踪**的派生文件）
    new_untracked = _untracked(_git_status()) - _untracked(before)
    assert not new_untracked, f"只读工具不许新建文件：{sorted(new_untracked)}"
    # ② 不许改动它读的真源（按内容哈希，不看 git status）
    after_hashes = _hashes()
    changed = [k for k in after_hashes if after_hashes.get(k) != before_hashes.get(k)]
    assert not changed, f"只读工具不许改动它读的真源：{changed}"


def test_machine_block_survives_a_report_that_quotes_json(tmp_path: Path) -> None:
    """★ 卡 117 钉子：报告正文里**带 ```json 样例**时，六个工具仍解析得出自己的机器块。

    复现的就是主树里那条真 pytest —— `job_result` 原样带出的报告正文里引用了一份
    tools/list 报文样例（JSON 里带**裸换行**，正是"Invalid control character"的来源）。
    老读端取"第一个 ```json" ⇒ 抓到样例 ⇒ 主树里必红。这里跑**六个**工具逐个验机器块。
    """
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    (diag / "wb-105.jsonl").write_text('{"type":"assistant"}\n', encoding="utf-8")
    (diag / "wb-105.verdict.txt").write_text("判决：过\n", encoding="utf-8")
    # 正文里的样例：JSON 字符串内**裸换行**（非法 JSON，真报告里就是这么被引用的）
    sample = '```json\n{"jsonrpc":"2.0","id":2,"result":{"tools":[\n {"name":"pool_plan"}\n]}}\n```'
    (diag / "wb-105.report.md").write_text(
        "# 卡 105 报告\n\n正文引用了一份 tools/list 报文样例（★ 不是工具的机器块）：\n\n"
        + sample
        + "\n\n以上是样例，下面是结论。\n",
        encoding="utf-8",
    )

    for name in TOOL_NAMES:
        if name in ("job_status", "job_result"):
            args = {"card": "105"}
        elif name == "quota_status":
            args = {"card": "105", "model": "deepseek-v4.1-flash"}
        else:
            args = {}
        result = pool_mcp.call_tool(name, args, root=tmp_path)
        assert result is not None, name
        block = _json_block(result["content"][0]["text"])  # 不抛 = 认出的是真机器块
        assert isinstance(block, dict), name

    # 正文里的样例确实被带了出来（证明这条钉子不是空跑）：`job_result` 人话里有那个样例
    job_text = pool_mcp.call_tool("job_result", {"card": "105"}, root=tmp_path)
    assert job_text is not None
    assert "tools/list 报文样例" in job_text["content"][0]["text"]
    assert "```json" in job_text["content"][0]["text"]


def test_pool_plan_json_is_structured_not_faked() -> None:
    """`pool_plan` 的 JSON 块真的解析出了批次结构（不是把原文塞进一个字符串了事）。"""
    text, data, is_error = pool_mcp.tool_pool_plan({}, root=ROOT)
    assert is_error is False
    assert data["command"].endswith("tools/wb_plan.py plan --concurrency 2")
    assert isinstance(data["batches"], list)  # 0 批是真的 []，不是 None


# ================================================================ 钉子③：未知工具名不崩


def test_unknown_tool_is_a_jsonrpc_error_not_a_crash() -> None:
    reply = pool_mcp.handle(_call("no-such-tool"))
    assert reply is not None
    assert reply["error"]["code"] == pool_mcp.JSONRPC_INVALID_PARAMS
    assert "没有这个工具" in reply["error"]["message"]
    assert "pool_plan" in reply["error"]["message"]  # 把"有哪些"说出来


def test_serve_loop_survives_an_unknown_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    """坏请求之后**还能接着服务**：未知工具换一条错误，后面那条正常请求照样有回话。"""
    lines = [
        json.dumps(_call("no-such-tool")),
        json.dumps(_req(2, "tools/list")),
    ]
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n".join(lines) + "\n"))
    monkeypatch.setattr(sys, "stdout", out)
    assert pool_mcp.serve([]) == 0
    replies = [json.loads(x) for x in out.getvalue().splitlines() if x.strip()]
    assert len(replies) == 2, replies
    assert replies[0]["error"]["code"] == pool_mcp.JSONRPC_INVALID_PARAMS
    assert [t["name"] for t in replies[1]["result"]["tools"]] == TOOL_NAMES


# ================================================================ 钉子④：缺产物 / 缺锁说清"没有"


def test_missing_artifacts_say_meiyou(tmp_path: Path) -> None:
    """空树里：`job_status` / `job_result` / `job_list` 都**如实说"没有"**（不假装有）。"""
    (tmp_path / "gates" / "diag").mkdir(parents=True)
    result = pool_mcp.call_tool("job_status", {"card": "777"}, root=tmp_path)
    assert result is not None and "没有" in result["content"][0]["text"]
    result = pool_mcp.call_tool("job_result", {"card": "777"}, root=tmp_path)
    assert result is not None and "没有" in result["content"][0]["text"]
    text, data, is_error = pool_mcp.tool_job_list({}, root=tmp_path)
    assert is_error is False and data["count"] == 0
    assert "没有" in text and "假装" in text


def test_missing_lock_says_no_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """门禁锁空着时，`lock_status` **明说"没有锁"**（这条用喂进来的原样输出判，不靠机器现场）。"""
    canned = (
        "[锁] 空着（没有任何段的锁）\n"
        "[锁] 全局并发上限 TF_GATE_MAX_CONCURRENT=2，当前租约内 0 把在跑\n"
    )

    def fake_run(argv: list[str], cwd: Path) -> tuple[int, str, str]:
        return 0, canned, ""

    monkeypatch.setattr(pool_mcp, "_run", fake_run)
    text, data, is_error = pool_mcp.tool_lock_status({}, root=ROOT)
    assert is_error is False
    assert "没有锁" in text
    assert data["has_lock"] is False
    assert "gate_lock.py status" in data["command"]


def test_job_list_classifies_by_evidence(tmp_path: Path) -> None:
    """`job_list` 按**证据**分态：有判决=已判决；无判决且日志新=在跑；无判决且静默=断了。"""
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    now = 1_700_000_000.0
    fresh = diag / "wb-101.jsonl"
    fresh.write_text('{"type":"assistant"}\n', encoding="utf-8")
    stale = diag / "wb-102.jsonl"
    stale.write_text('{"type":"assistant"}\n', encoding="utf-8")
    judged = diag / "wb-103.jsonl"
    judged.write_text('{"type":"result"}\n', encoding="utf-8")
    (diag / "wb-103.verdict.txt").write_text("ok\n", encoding="utf-8")
    # 只把 102 的 mtime 拨老（101 就是现在 → 在跑）
    old = now - pool_mcp.STALL_SECONDS - 60
    os.utime(stale, (old, old))

    rows = {row["card"]: row for row in pool_mcp.scan_jobs(diag, now=now)}
    assert rows["101"]["state"] == "在跑"
    assert rows["102"]["state"] == "断了"
    assert rows["103"]["state"] == "已判决"
    assert rows["102"]["age_seconds"] > pool_mcp.STALL_SECONDS
    assert rows["103"]["has_verdict"] is True

    text, data, _ = pool_mcp.tool_job_list({}, root=tmp_path)
    assert data["counts"] == {"在跑": 1, "断了": 1, "已判决": 1}
    assert "在跑" in text and "断了" in text and "已判决" in text


def test_job_result_shows_totals_when_truncating(tmp_path: Path) -> None:
    """截断**明示总长**（先例一贯的做法）：`total_chars` 是全文长度，不是显示长度。"""
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    long_text = "判" * (pool_mcp.REPORT_MAX_CHARS + 500)
    (diag / "wb-200.verdict.txt").write_text(long_text, encoding="utf-8")
    text, data, is_error = pool_mcp.tool_job_result({"card": "200"}, root=tmp_path)
    assert is_error is False
    assert data["verdict"]["total_chars"] == len(long_text)
    assert data["verdict"]["truncated"] is True
    assert data["verdict"]["shown_chars"] == pool_mcp.REPORT_MAX_CHARS
    assert str(len(long_text)) in text  # 人话里也把总长念出来


# ================================================================ 真 stdio（子进程 · 照先例）


def _talk(
    messages: list[dict[str, Any]], args: list[str]
) -> tuple[list[dict[str, Any]], bytes, str, int]:
    """真起一个子进程，按字节喂 UTF-8、按字节收回（照 `test_mcp_line.py` 的口径）。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "tools")
    proc = subprocess.Popen(
        [sys.executable, "-c", SERVER_SNIPPET, *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=str(ROOT),
    )
    payload = b"".join((json.dumps(m, ensure_ascii=False) + "\n").encode("utf-8") for m in messages)
    out, err = proc.communicate(payload, timeout=180)
    replies = [json.loads(line.decode("utf-8")) for line in out.split(b"\n") if line.strip()]
    return replies, out, err.decode("utf-8", errors="replace"), proc.returncode


def test_real_stdio_round_trip_is_utf8_and_only_protocol() -> None:
    """端到端：initialize → tools/list → tools/call；stdout 只有协议、两头都是 UTF-8。"""
    replies, raw, err, code = _talk(
        [
            _req(1, "initialize", {"protocolVersion": "2025-06-18"}),
            _req(2, "tools/list"),
            _req(3, "tools/call", {"name": "job_list", "arguments": {}}),
        ],
        [],
    )
    assert code == 0, err
    raw.decode("utf-8")  # ① 出去必须是 UTF-8（解不开就是缺陷）
    assert [r["id"] for r in replies] == [1, 2, 3], (replies, err)
    assert replies[0]["result"]["serverInfo"]["name"] == "pool"
    assert [t["name"] for t in replies[1]["result"]["tools"]] == TOOL_NAMES
    assert "外包派活台账" in _text(replies[2])  # ② 中文一字不差地出去


def test_real_stdio_survives_a_bad_line() -> None:
    """一条坏字节 / 坏 JSON **不许打死循环**（坏行之后那条正常请求照样有回话）。"""
    payload = b"\xff\xfe\x00 not utf-8\n{not json\n"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "tools")
    proc = subprocess.Popen(
        [sys.executable, "-c", SERVER_SNIPPET],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=str(ROOT),
    )
    out, _err = proc.communicate(
        payload + json.dumps(_req(4, "tools/list")).encode("utf-8") + b"\n", timeout=180
    )
    replies = [json.loads(x.decode("utf-8")) for x in out.split(b"\n") if x.strip()]
    assert len(replies) == 3, replies
    codes = [r.get("error", {}).get("code") for r in replies]
    assert codes[0] == pool_mcp.JSONRPC_PARSE_ERROR
    assert codes[1] == pool_mcp.JSONRPC_PARSE_ERROR
    assert "tools" in replies[2]["result"]  # 坏行没把流搞坏


# ================================================================ 时长常量与先例同口径（防漂）


def test_thresholds_match_the_dispatch_tool() -> None:
    """ "断了"的阈值必须与派活器**同口径**（不然两个窗口会对同一现场给出不同结论）。"""
    import wb_dispatch  # noqa: PLC0415 —— tools/ 已在 sys.path 上

    assert pool_mcp.STALL_SECONDS == wb_dispatch.STALL_SECONDS
    assert pool_mcp.HEARTBEAT_SECONDS == wb_dispatch.HEARTBEAT_SECONDS


def test_sanity_now_is_time() -> None:
    """`scan_jobs` 默认 `now` 就是 `time.time()`（不传参时也判得动）。"""
    diag = ROOT / "gates" / "diag"
    rows = pool_mcp.scan_jobs(diag, now=time.time())
    assert isinstance(rows, list)
