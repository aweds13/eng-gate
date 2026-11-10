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
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
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


# coverage 自己的数据文件（不是工具写的）：.coverage 与 .coverage.<suffix>。
# 出处 coverage/sqldata.py::filename_suffix(True) 造的是 host.pid<pid>.X<rolls>x，
# pytest-cov engine.py 的 data_suffix=True（中央/分布式两条路）都会落这种中间文件；
# 合并后通常删掉，失败/中断时会残留 —— 它与「只读工具写了文件」无关
# （卡 E109 现场：land-E109.log:160）。
_COVERAGE_DATA = re.compile(r"^\.coverage(\..*)?$")


def _untracked(snapshot: set[str]) -> set[str]:
    """未跟踪条目，**剔除 coverage 自己的数据文件**（.coverage / .coverage.<suffix>）。

    剔除面必须窄到只剩这一族 —— 别的名字照样算，见
    test_the_readonly_snapshot_only_ignores_coverage_data_files。
    """
    out: set[str] = set()
    for line in snapshot:
        if not line.startswith("??"):
            continue
        rel = line[3:].strip().strip(chr(34))
        if _COVERAGE_DATA.match(rel.rsplit("/", 1)[-1]):
            continue
        out.add(line)
    return out


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


def test_the_readonly_snapshot_only_ignores_coverage_data_files() -> None:
    """反空转：钉子② 的剔除面必须窄到 coverage 数据文件那一族。

    没有这条钉子，_untracked 可以被悄悄改成「什么都不要」，钉子② 就变成空气；
    反过来，这一族以外的名字（含长得像的 .coverageish）必须照样算。
    """
    snap = {
        "?? .coverage",
        "?? .coverage.DEV-HOST.pid30684.XR6s7lZx.H99bHMpKZUMh",
        "?? .coverageish",
        "?? code/rogue.py",
        " M tools/pool_mcp.py",
    }
    assert _untracked(snap) == {"?? .coverageish", "?? code/rogue.py"}


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

# ================================================ 卡 E107（T-AG616）：pool_models 的人话段
#
# 三条判据各钉一位：
#   ① 「交集」不是派活允许集 —— 不许再冒充（真名单按池报，且现算比对，不写死）；
#   ② 快照新鲜度必须出现在**人话**里（三态：过期 / 新鲜 / 没记录，不许把「没记录」说成「新鲜」）；
#   ③ 注册表坏了，这个只读工具也不许崩（号池那几段照常给，只这一段说「读不出来」）。


def _fake_pool_root(
    tmp_path: Path, *, at: object = "__omit__", live: list[str] | None = None
) -> Path:
    """造一个够 `find_pool_dir` / `load_pool_models` 用的假号池目录。

    ★ 照 tests/test_pool_lib.py 的范式：`pool_models.py` 只要存在即可。
      `at` 传 `None` = 快照里**没有** `at` 键（没记录）；传字符串 = 写进去。
    """
    pool = tmp_path / "infra" / "pool"
    pool.mkdir(parents=True, exist_ok=True)
    (pool / "pool_models.py").write_text("", encoding="utf-8")
    (pool / "models.whitelist.toml").write_text(
        "[[approved]]\npool = \"codebuddy\"\nmodel = \"p/GLM-5.2\"\n",
        encoding="utf-8",
    )
    snap: dict[str, Any] = {"live": live if live is not None else ["p/GLM-5.2"]}
    if at != "__omit__" and at is not None:
        snap["at"] = at
    (pool / "models.live.json").write_text(json.dumps(snap), encoding="utf-8")
    return tmp_path


def _human(text: str) -> str:
    """只取**人话段**（机器块之前）。拿整段判文案 = 自己骗自己：JSON 里本来就有那些字段。"""
    return text.split(JSON_MARKER, 1)[0]


def test_pool_models_does_not_call_the_intersection_a_dispatch_allow_list() -> None:
    """★ 卡 E107 的现场：人话段写着「交集（真正允许派活的）」，而那句话是假的。

    `in_both` 只是号池两份**静态产物**的交集；派活器判的是
    `wb_dispatch.effective_allowed_models(pool)`（注册表该池条目 + 一次性授权 + 开关文件）。
    两套 id 口径还不同（号池 provider/model、派活器裸名），谁也冒充不了谁。
    """
    text, data, is_error = pool_mcp.tool_pool_models({}, root=ROOT)
    assert is_error is False
    assert "交集（真正允许派活的）" not in text, "这句话是假的：交集不是派活允许集"
    assert "不是派活允许集" in _human(text), text
    assert "effective_allowed_models" in text, "得点名真名单从哪来（判据只有一份）"
    assert data["in_both"], "真仓今天有两个（号池批准 ∩ 号池快照）—— 一条都没有说明夹具坏了"


def test_pool_models_reports_the_dispatch_allow_list_per_pool() -> None:
    """派活允许集必须**按池**报，且与 wb_dispatch 现算的逐项相等（不许写死名单）。"""
    import wb_dispatch  # noqa: PLC0415 —— tools/ 已在 sys.path 上
    from pool.model_registry import KNOWN_POOLS  # noqa: PLC0415

    text, _data, is_error = pool_mcp.tool_pool_models({}, root=ROOT)
    assert is_error is False
    lines = text.splitlines()
    for pool in KNOWN_POOLS:
        allowed = set(wb_dispatch.effective_allowed_models(pool))
        line = next((ln for ln in lines if ln.strip().startswith("· " + pool)), None)
        assert line is not None, "人话段里没有这个池的行：" + pool + "\n" + text
        listed = {part.strip() for part in line.split("：", 1)[1].split("、") if part.strip()}
        assert listed == allowed, pool + " 名单不一致：" + repr(listed) + " != " + repr(allowed)
        assert ("未接" in line) is (not wb_dispatch.get_adapter(pool).wired), line


def test_pool_models_says_the_snapshot_is_stale_in_the_human_text(tmp_path: Path) -> None:
    """★ 过期 373.8 小时这件事，原来只有 JSON 块里有；人话段必须说。"""
    stamp = (datetime.now() - timedelta(hours=72)).strftime("%Y-%m-%d %H:%M:%S")
    root = _fake_pool_root(tmp_path, at=stamp)
    text, data, is_error = pool_mcp.tool_pool_models({}, root=root)
    assert is_error is False
    assert data["snapshot_stale"] is True
    human = _human(text)  # 只准人话段有：机器块里本来就有 snapshot_note，拿整段判等于没判
    assert "已过期" in human, human
    assert "72" in human, human
    assert "24" in human, human


def test_pool_models_says_fresh_without_crying_wolf(tmp_path: Path) -> None:
    """新鲜快照要说「没过期」，且**不许**出现「已过期」（不许嚷）。"""
    root = _fake_pool_root(tmp_path, at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    text, data, is_error = pool_mcp.tool_pool_models({}, root=root)
    assert is_error is False
    assert data["snapshot_stale"] is False
    human = _human(text)
    assert "没过期" in human, human
    assert "已过期" not in human, human


def test_pool_models_says_unknown_when_the_stamp_is_missing(tmp_path: Path) -> None:
    """★ 「没记录」不是「新鲜」：at 没有 ⇒ 说「不知道它多旧」（与卡 320 的口径一致）。"""
    root = _fake_pool_root(tmp_path, at=None)
    text, data, is_error = pool_mcp.tool_pool_models({}, root=root)
    assert is_error is False
    assert data["snapshot_at"] is None
    assert data["snapshot_stale"] is False, "没记录 ≠ 过期（卡 320 已定）"
    human = _human(text)
    assert "不知道" in human, human
    assert "没过期" not in human, "没记录不许洗成新鲜"


def test_pool_models_survives_a_broken_registry(tmp_path: Path, monkeypatch: Any) -> None:
    """★ 注册表坏了：只这一段说「读不出来」，号池那几段照常给，工具**不抛**。

    `effective_allowed_models` **不 fail-open**（注册表缺失即 `ModelRegistryError`）；
    这个工具是只读面，一个坏 TOML 不许把整个 tools/call 打成异常。
    """
    root = _fake_pool_root(tmp_path, at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    monkeypatch.setenv("TF_MODEL_REGISTRY", str(tmp_path / "nope.toml"))
    text, _data, is_error = pool_mcp.tool_pool_models({}, root=root)
    assert is_error is False, "坏注册表是这一段没答案，不是整个工具失败"
    assert text.strip(), "只读工具必须回非空文本"
    assert "读不出来" in text, text
    assert "ModelRegistryError" in text, "得点名异常（不然人只看到「读不出来」）"
    assert "批准集" in text, "号池那几段必须照常给"


def test_pool_models_still_writes_nothing(tmp_path: Path) -> None:
    """★ 只读：不写快照、不联网。跑前跑后两份输入的字节与 mtime 都不许变。"""
    root = _fake_pool_root(tmp_path, at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    pool = root / "infra" / "pool"
    watched = (pool / "models.live.json", pool / "models.whitelist.toml")
    before = [(f.read_bytes(), f.stat().st_mtime_ns) for f in watched]
    pool_mcp.tool_pool_models({}, root=root)
    after = [(f.read_bytes(), f.stat().st_mtime_ns) for f in watched]
    assert before == after, "只读工具改了它的输入（或碰了 mtime）"


def test_pool_models_module_duty_does_not_claim_the_intersection_is_the_allow_list() -> None:
    """同一条口径在模块表里还有一份投影（docs/subsystems/pool/modules.toml）—— 一起改。"""
    import tomllib  # noqa: PLC0415 —— 3.11+ 标准库

    raw = (ROOT / "docs" / "subsystems" / "pool" / "modules.toml").read_bytes()
    data = tomllib.loads(raw.decode("utf-8"))
    by_name = {m["name"]: m for m in data["module"]}
    duty = by_name["models.py"]["duty"]
    assert "批准集 ∩ 可用集" not in duty, duty
    assert "不是派活允许集" in duty, duty
    gw_duty = by_name["gateway.py"]["duty"]
    assert "UNKNOWN_TIER" in gw_duty, gw_duty


# ============================ 卡 E109（T-AG618）：pool_models 说清「今天派不派得出去」
#
# 四条判据各钉一位：
#   ① 按批准集**逐条**给按池的真判决（判序照抄派活主闸；测试用真判据现算后比对，不另抄名单）；
#   ② 说清「按原名派不出去 ≠ 这条模型用不了」—— 给出今天真能派的别名；
#   ③ 结论行数出来（批准 N 条 / 按原名派得出去 M 条），N 与 M 都由数据现算，不许写死；
#   ④ 注册表坏了时给的指针必须是**真**路径（registry_path() 现算，不是仓外那个不存在的）。


def _verdict_line(human: str, name: str) -> str | None:
    """判决段里这一条模型的那一行（以「· <模型> —— 」开头）。"""
    prefix = "· " + name + " —— "
    return next((ln for ln in human.splitlines() if ln.startswith(prefix)), None)


def _real_verdict(name: str, pool: str) -> str:
    """用**派活主闸那几份真判据**现算这个名字在这个池今天派不派得出去。

    判据只有一份（get_adapter / resolve_model / model_rejected / assert_not_disabled 都在
    tools/pool/ 里）—— 测试只负责**问**，不另写判序、不另抄名单。
    """
    import wb_dispatch  # noqa: PLC0415 —— tools/ 已在 sys.path 上

    adapter = wb_dispatch.get_adapter(pool)
    try:
        wb_dispatch.resolve_model(name, pool)   # 返回值不看，与 main() 一致
    except wb_dispatch.PoolMismatchError:
        return "跨池串用"
    if not adapter.wired:
        return "未接"
    if wb_dispatch.model_rejected(name, pool):
        return "未授权"
    try:
        wb_dispatch.assert_not_disabled(pool, name)
    except wb_dispatch.ModelRegistryError:
        return "判不了"
    return "可派"


def _alias_paths(name: str, pools: tuple[str, ...]) -> list[str]:
    """这条批准模型今天**换个名字**能派的去处（形如 glm-5.2（codebuddy））。"""
    import wb_dispatch  # noqa: PLC0415

    mine = {a.strip().lower() for a in wb_dispatch.model_aliases(name)}
    out: list[str] = []
    for pool in pools:
        for cand in wb_dispatch.effective_allowed_models(pool):
            if cand == name:
                continue
            theirs = {a.strip().lower() for a in wb_dispatch.model_aliases(cand)}
            if not (mine & theirs):
                continue
            if _real_verdict(cand, pool) == "可派":
                out.append(cand + "（" + pool + "）")
    return out


def test_pool_models_judges_every_approved_model_with_the_real_gate() -> None:
    """★ 卡 E109 判据 1：批准集里每一条都要有一行**按池的真判决**，且与真判据现算一致。"""
    from pool.model_registry import KNOWN_POOLS  # noqa: PLC0415

    text, data, is_error = pool_mcp.tool_pool_models({}, root=ROOT)
    assert is_error is False
    human = _human(text)
    assert data["approved"], "真仓今天有批准项；一条都没有说明号池坏了（不是这条钉子的意思）"
    for name in data["approved"]:
        line = _verdict_line(human, name)
        assert line is not None, "判决段里没有这一条：" + name + "\n" + human
        for pool in KNOWN_POOLS:
            want = pool + " " + _real_verdict(name, pool)
            assert want in line, "「" + name + "」在 " + pool + " 池的判决与真判据不一致：" + line


def test_pool_models_names_the_gate_that_blocks() -> None:
    """★ 卡 E109 判据 1 后半：被哪道闸拦住就点哪道 —— 未接的池要把适配器自己那句话带出来。"""
    import wb_dispatch  # noqa: PLC0415
    from pool.model_registry import KNOWN_POOLS  # noqa: PLC0415

    text, data, is_error = pool_mcp.tool_pool_models({}, root=ROOT)
    assert is_error is False
    human = _human(text)
    blocked = 0
    for name in data["approved"]:
        line = _verdict_line(human, name)
        assert line is not None, human
        for pool in KNOWN_POOLS:
            verdict = _real_verdict(name, pool)
            if verdict != "未接":
                continue
            blocked += 1
            note = wb_dispatch.get_adapter(pool).note
            assert note in line, "未接的那一池必须把 note 原文带出来（不然只看到「未接」）：" + line
    assert blocked >= 1, "真仓今天 codearts 未接（卡 166）；一个都没算到说明探针坏了"


def test_pool_models_offers_the_alias_that_actually_dispatches() -> None:
    """★ 卡 E109 判据 2：按原名派不出去 ≠ 这条模型用不了 —— 换个名字今天就能派，必须点名。"""
    from pool.model_registry import KNOWN_POOLS  # noqa: PLC0415

    text, data, is_error = pool_mcp.tool_pool_models({}, root=ROOT)
    assert is_error is False
    human = _human(text)
    offered = 0
    for name in data["approved"]:
        line = _verdict_line(human, name)
        assert line is not None, human
        for path in _alias_paths(name, KNOWN_POOLS):
            offered += 1
            cand = path.split("（", 1)[0]
            assert cand in line, "别名生路没点名：" + path + "\n" + line
            assert "可派别名" in line, line
        if not _alias_paths(name, KNOWN_POOLS):
            assert "可派别名：（没有）" in line, "没有生路就要明说「没有」，不许留白：" + line
    assert offered >= 1, (
        "真仓今天至少有一条别名生路（GLM-5.2 与 glm-5.2 是同一条）；算不出来说明探针坏了"
    )


def test_pool_models_counts_follow_the_ledger_not_a_constant(tmp_path: Path) -> None:
    """★ 卡 E109 判据 2 后半：判决条数跟着号池数据走 —— 换成一条批准的假号池，数就要变。"""
    root = _fake_pool_root(tmp_path, at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    text, data, is_error = pool_mcp.tool_pool_models({}, root=root)
    assert is_error is False
    human = _human(text)
    assert len(data["approved"]) == 1, data["approved"]
    assert "批准集 1 条" in human, human
    assert "批准集 2 条" not in human, "数写死了（真仓今天是 2 条）：" + human
    bullets = [ln for ln in human.splitlines() if ln.startswith("· ") and " —— " in ln]
    assert len(bullets) == len(data["approved"]), bullets


def test_pool_models_says_how_many_approved_names_dispatch_today() -> None:
    """★ 卡 E109 判据 3：结论行要把数出来 —— 两个数都必须与真判据现算的结果一致。"""
    from pool.model_registry import KNOWN_POOLS  # noqa: PLC0415

    text, data, is_error = pool_mcp.tool_pool_models({}, root=ROOT)
    assert is_error is False
    human = _human(text)
    origin = sum(
        1 for name in data["approved"]
        if any(_real_verdict(name, pool) == "可派" for pool in KNOWN_POOLS)
    )
    alias = sum(1 for name in data["approved"] if _alias_paths(name, KNOWN_POOLS))
    assert "按原名今天派得出去 " + str(origin) + " 条" in human, human
    assert "换别名能派 " + str(alias) + " 条" in human, human


def test_pool_models_pointer_names_the_real_registry_path(tmp_path: Path, monkeypatch: Any) -> None:
    """★ 卡 E109 判据 4：注册表坏了给的指针必须是真路径（仓外 infra/pool/ 下没有这份文件）。"""
    from pool.model_registry import registry_path  # noqa: PLC0415

    root = _fake_pool_root(tmp_path, at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    monkeypatch.setenv("TF_MODEL_REGISTRY", str(tmp_path / "nope.toml"))
    text, _data, is_error = pool_mcp.tool_pool_models({}, root=root)
    assert is_error is False, "坏注册表是某几段没答案，不是整个只读工具失败"
    assert "读不出来" in text, text
    assert registry_path().as_posix() in text, "指针要现算（registry_path()），不是写死的：" + text
    assert "infra/pool/model-registry.toml" not in text, "指针又指回仓外那个不存在的路径了：" + text


def test_pool_models_schema_and_prose_agree_on_what_it_answers() -> None:
    """★ 卡 E109 判据 5：同一条口径在 schema 与两份文档里都跟着改（一处都不许留旧说法）。"""
    spec = next(s for s in pool_mcp.TOOL_SPECS if s["name"] == "pool_models")
    desc = str(spec["description"])
    assert "按池" in desc, desc
    assert "不是派活允许集" in desc, desc
    assert "派不派得出去" in desc, desc

    asset = (ROOT / "skills" / "softeng-manage" / "references" / "asset-layers.md").read_text(
        encoding="utf-8"
    )
    assert "返回的「批准集 ∩ 可用集」" not in asset, "skill 里还在拿交集当答案"
    assert "按池现算" in asset, "skill 里得说清去看按池现算的真判决"

    design = (ROOT / "复盘" / "号池MCP-使用与设计.md").read_text(encoding="utf-8")
    row = next(
        (ln for ln in design.splitlines() if ln.startswith("| ") and "pool_models" in ln), None
    )
    assert row is not None, "工具表里没有 pool_models 那一行"
    assert "按池" in row and "真判决" in row, row
    assert "（批准 ∩ 可用" not in row, row


# ======================================== 卡 E110（T-AG619）：过期时人话段要说清怎么探、谁拒谁拦


def test_pool_models_stale_line_says_how_to_probe(tmp_path: Path) -> None:
    """★ 判据 2：人话段（_human）过期那一屏要带命令与现算路径。

    改前：只说「已过期 72 小时 ⇒ 先重新探测再派活」，读者拿不到那条命令。
    """
    stamp = (datetime.now() - timedelta(hours=72)).strftime("%Y-%m-%d %H:%M:%S")
    root = _fake_pool_root(tmp_path, at=stamp)
    text, data, is_error = pool_mcp.tool_pool_models({}, root=root)
    assert is_error is False
    assert data["snapshot_stale"] is True
    human = _human(text)
    assert "已过期" in human, human
    assert "--check" in human, "过期了却不说怎么探：" + human
    assert (root / "infra" / "pool" / "pool_models.py").as_posix() in human, human


def test_pool_models_missing_stamp_also_says_how_to_probe(tmp_path: Path) -> None:
    """★ 判据 2：「没记录」那一态同样要给出探测命令（不许只说过期那半）。"""
    root = _fake_pool_root(tmp_path, at=None)
    text, _data, is_error = pool_mcp.tool_pool_models({}, root=root)
    assert is_error is False
    human = _human(text)
    assert "不知道" in human, human
    assert "--check" in human, human
    assert (root / "infra" / "pool" / "pool_models.py").as_posix() in human, human


def test_pool_models_says_who_blocks_and_who_only_warns(tmp_path: Path) -> None:
    """★ 判据 3：说清「同一个过期，网关拒、派活器只提示」—— 一句，写在一处。"""
    stamp = (datetime.now() - timedelta(hours=72)).strftime("%Y-%m-%d %H:%M:%S")
    root = _fake_pool_root(tmp_path, at=stamp)
    text, _data, _is_error = pool_mcp.tool_pool_models({}, root=root)
    human = _human(text)
    assert "网关" in human, human
    assert "派活器" in human, human
    assert "不拦" in human, human

# ============================ 卡 E111（T-AG620）：机器块还停在三张卡之前
#
# 人话段在 E107 / E109 / E110 三张卡里长出了判决、计数、允许集、探测命令；
# 机器块一直只是 load_pool_models() 的 16 个键 —— 而机器读者只读机器块，
# 拿到的仍是那张被 E107 点名「不是派活允许集」的 in_both。
# 这里钉的是「一份结构两处渲染」：
#   ① 判决 / 计数 / 允许集 / 探测命令都进机器块，且与人话段同源；
#   ② 机器块里有一句布尔否掉「in_both 是允许集」；
#   ③ 判不了的时候三键 None（不是 []、不是 {}）—— 不许给一个看起来正常的空判决。


def _dispatch_block(text: str) -> dict[str, Any]:
    """机器块里的 dispatch 段（判不了时里面几个键是 None，也得取得出来）。"""
    return _json_block(text)["dispatch"]


def test_payload_carries_every_verdict_the_human_text_shows() -> None:
    """★ 判据 1：机器块每条判决都要能在人话段那一行里逐字对上（池、结论、why）。"""
    from pool.model_registry import KNOWN_POOLS  # noqa: PLC0415

    text, data, is_error = pool_mcp.tool_pool_models({}, root=ROOT)
    assert is_error is False
    judged = _dispatch_block(text)["verdicts"]
    assert isinstance(judged, list) and judged, "机器块里没有判决，而人话段有"
    human = _human(text)
    assert len(judged) == len(data["approved"]), (len(judged), data["approved"])
    for row in judged:
        line = _verdict_line(human, row["name"])
        assert line is not None, "人话段没有这一条：" + str(row["name"])
        assert set(row["pools"]) == set(KNOWN_POOLS), row["pools"]
        for pool in KNOWN_POOLS:
            cell = row["pools"][pool]
            assert pool + " " + cell["verdict"] in line, (
                "机器块与文本对不上：" + pool + " " + cell["verdict"] + "\n" + line
            )
            if cell["why"]:
                assert cell["why"] in line, "why 没跟在判决后面：" + cell["why"] + "\n" + line
        assert row["dispatchable"] is any(
            c["verdict"] == "可派" for c in row["pools"].values()
        ), row


def test_payload_counts_equal_the_human_counts() -> None:
    """★ 判据 1 后半：两个计数在机器块与文本里必须是同一对数（同源，不是各算一遍）。"""
    from pool.model_registry import KNOWN_POOLS  # noqa: PLC0415

    text, data, is_error = pool_mcp.tool_pool_models({}, root=ROOT)
    assert is_error is False
    counts = _dispatch_block(text)["counts"]
    human = _human(text)
    origin = sum(
        1
        for name in data["approved"]
        if any(_real_verdict(name, pool) == "可派" for pool in KNOWN_POOLS)
    )
    alias = sum(1 for name in data["approved"] if _alias_paths(name, KNOWN_POOLS))
    assert counts == {
        "approved": len(data["approved"]),
        "origin": origin,
        "alias": alias,
    }, counts
    assert "按原名今天派得出去 " + str(origin) + " 条" in human, human
    assert "换别名能派 " + str(alias) + " 条" in human, human


def test_payload_never_claims_in_both_is_the_allow_list() -> None:
    """★ 判据 2：布尔恒 False —— 它是口径问题，不是数据问题（数据空了也不许翻成 True）。"""
    text, data, is_error = pool_mcp.tool_pool_models({}, root=ROOT)
    assert is_error is False
    flag = data["in_both_is_a_dispatch_allow_list"]
    assert isinstance(flag, bool) and flag is False, flag
    allow = _dispatch_block(text)["allow_lists"]
    assert allow, "允许集一个池都没有 —— 那不是「不是交集」，是没算"
    assert allow is not data["in_both"], "允许集不许就是那份交集"


def test_payload_note_matches_the_human_text() -> None:
    """★ 判据 2 后半：那句注解只写一处 —— 机器块里那串必须原样出现在人话段。"""
    text, _data, is_error = pool_mcp.tool_pool_models({}, root=ROOT)
    assert is_error is False
    note = _dispatch_block(text)["note"]
    assert isinstance(note, str) and note.strip(), note
    assert note in _human(text), "机器块那句注解在人话段里找不到（两处各写一份）：" + note


def test_payload_lists_the_allow_set_per_pool() -> None:
    """★ 判据 3：按池允许集进机器块，且与 wb_dispatch 现算的逐池相等（顺序也照它）。"""
    import wb_dispatch  # noqa: PLC0415
    from pool.model_registry import KNOWN_POOLS  # noqa: PLC0415

    text, _data, is_error = pool_mcp.tool_pool_models({}, root=ROOT)
    assert is_error is False
    block = _dispatch_block(text)
    assert set(block["allow_lists"]) == set(KNOWN_POOLS), block["allow_lists"]
    for pool in KNOWN_POOLS:
        want = list(wb_dispatch.effective_allowed_models(pool))
        assert block["allow_lists"][pool] == want, (pool, block["allow_lists"][pool], want)
    unwired = sorted(p for p in KNOWN_POOLS if not wb_dispatch.get_adapter(p).wired)
    assert sorted(block["pools_unwired"]) == unwired, (
        block["pools_unwired"],
        unwired,
    )


def test_payload_allow_lists_are_not_the_intersection(tmp_path: Path) -> None:
    """★ 判据 3 后半：假号池批准一条 p/GLM-5.2 —— 允许集是派活器现算的，两套 id 口径不同。"""
    root = _fake_pool_root(tmp_path, at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    text, data, is_error = pool_mcp.tool_pool_models({}, root=root)
    assert is_error is False
    block = _dispatch_block(text)
    flat = {name for names in block["allow_lists"].values() for name in names}
    assert flat, "允许集空着 —— 那不是「不是交集」，是没算"
    assert flat != set(data["in_both"]), "两套 id 口径不同，允许集不可能等于交集：" + str(flat)


def test_payload_says_unknown_when_the_registry_is_broken(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """★ 判据 4：判不了就说判不了 —— 三个键 None，另带一句 error；工具本身不失败。"""
    root = _fake_pool_root(tmp_path, at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    monkeypatch.setenv("TF_MODEL_REGISTRY", str(tmp_path / "nope.toml"))
    text, data, is_error = pool_mcp.tool_pool_models({}, root=root)
    assert is_error is False, "坏注册表是这几段没答案，不是整个只读工具失败"
    block = _dispatch_block(text)
    assert block["verdicts"] is None, block["verdicts"]
    assert block["counts"] is None, block["counts"]
    assert block["allow_lists"] is None, block["allow_lists"]
    assert block["pools_unwired"] is None, block["pools_unwired"]
    assert isinstance(block["error"], str) and block["error"].strip(), block["error"]
    assert data["in_both_is_a_dispatch_allow_list"] is False
    assert "读不出来" in text, "人话段那两行照旧要给"


def test_payload_verdicts_is_never_a_fake_empty_list(tmp_path: Path, monkeypatch: Any) -> None:
    """★ 判据 4 后半：None 不等于 [] —— 空列表读起来是「判完了，一条都没有」。"""
    root = _fake_pool_root(tmp_path, at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    monkeypatch.setenv("TF_MODEL_REGISTRY", str(tmp_path / "nope.toml"))
    text, _data, is_error = pool_mcp.tool_pool_models({}, root=root)
    assert is_error is False
    block = _dispatch_block(text)
    assert not isinstance(block["verdicts"], list), "给空列表就是把判不了洗成判完了"
    assert not isinstance(block["counts"], dict), "给空字典同上"
    assert block["verdicts"] is None and block["counts"] is None


def test_payload_carries_the_same_probe_command_as_the_text(tmp_path: Path) -> None:
    """★ 判据 5：探测命令也进机器块，且与文本里那一串是**同一个值**（E110 只改了人话段）。"""
    stamp = (datetime.now() - timedelta(hours=72)).strftime("%Y-%m-%d %H:%M:%S")
    root = _fake_pool_root(tmp_path, at=stamp)
    text, data, is_error = pool_mcp.tool_pool_models({}, root=root)
    assert is_error is False
    probe = data["snapshot_probe"]
    script = (root / "infra" / "pool" / "pool_models.py").as_posix()
    assert probe["command"] == "python -X utf8 " + script + " --check", probe
    assert probe["hint"] == "重新探测：" + str(probe["command"]), probe
    assert probe["command"] in _human(text), "人话段那串命令与机器块不是同一个值"


def test_payload_probe_is_null_when_the_script_is_missing(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """★ 判据 5 后半：脚本不在 ⇒ command 是 None，hint 仍非空且不编命令。"""
    from pool.models import find_pool_dir  # noqa: PLC0415

    stamp = (datetime.now() - timedelta(hours=72)).strftime("%Y-%m-%d %H:%M:%S")
    root = _fake_pool_root(tmp_path, at=stamp)
    pool = find_pool_dir(root)
    assert pool is not None, "夹具坏了：假号池目录都没找到"
    (pool / "pool_models.py").unlink()
    monkeypatch.setattr(pool_mcp, "find_pool_dir", lambda _root: pool)
    text, data, is_error = pool_mcp.tool_pool_models({}, root=root)
    assert is_error is False
    probe = data["snapshot_probe"]
    assert probe["command"] is None, probe
    assert probe["hint"].strip(), "没有命令也要说一句（不许留白）"
    assert "--check" not in probe["hint"], "脚本都没有，别编一条假命令：" + probe["hint"]
    assert "--check" not in _human(text), "人话段也不许出现假命令"


def test_the_doc_projections_stop_calling_the_intersection_dispatchable() -> None:
    """★ 判据 6：两处投影改法不同 —— 一处就地改，一处只许加补注（逐字输出是历史）。"""
    doc = (ROOT / "docs" / "subsystems" / "pool" / "模型与号池.md").read_bytes().decode("utf-8")
    row = next((ln for ln in doc.splitlines() if ln.startswith("| `in_both` |")), None)
    assert row is not None, "模型与号池.md 里没有 in_both 那一行（表被改了？）"
    assert "真正可派" not in row, "这一行还在说交集是真正可派：" + row
    trae = (ROOT / "复盘" / "Trae-接入结论.md").read_bytes().decode("utf-8")
    verbatim = (
        "pool_models    只读   号池可用模型：批准集 ∩ 可用集（读号池快照，只读、不联网）。"
    )
    assert verbatim in trae, "逐字输出被改了 —— 那是伪造历史，只许在它后面加补注"
    tail = "\n".join(trae[trae.index(verbatim):].splitlines()[:40])
    assert "E111" in tail, "逐字输出之后 40 行内要有 E111 的补注：" + tail
    assert "2026-11-10" in tail, "补注必须带日期：" + tail
