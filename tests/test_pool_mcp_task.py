r"""任务栅栏接到外包面（MCP 的任务类工具）的钉子 —— 卡 121 · T-G218。

为什么值当测：这一段把**任务栅栏**（注册一个跨层的任务 → 每张卡交成送申请 → 集齐才收口）
接到别的窗口的 AI 能敲的 MCP 工具上。错的方式有几种，全是**别的窗口读到假现状**或**静默绕守卫**：

| 钉子 | 判什么 |
|---|---|
| ① 只读三个 | 三个任务只读工具都返回、都带机器可读块、且**不写一个文件** |
| ② 授权（`tools/list`） | 不设 env = **11 个**只读；设 `POOL_MCP_WRITE=1` 才多出两个写工具 |
| ③ 写门 `confirm` | `task_register` 的 `confirm` = TOML 的 `id`；`task_claim` = `task`；不符 ⇒ 拒 |
| ④ 没 env = 没这个工具 | 没设 env 时写调用回 `-32602`（"没有这个工具"），**不假装有** |
| ⑤ 域守卫不许绕 | `task_claim` 带**域外文件** ⇒ **拒并点名**（★ 任务＝绕冲突域后门，这条最重要） |
| ⑥ 未知任务说清 | `task_status` 传不存在的任务 ⇒ 明说"没有"，**不崩、不带假数据** |

★ 卡 130（`task_claim` 改**子进程**跑，治 GLM-2.3 的放大器）另加四条：

| 钉子 | 判什么 |
|---|---|
| ⑦ 真走子进程 | `task_claim` 起 `wb_task.py claim` 子进程，**不许**进程内调 `task.cmd_claim` |
| ⑧ stdio 不被冻住 | 慢门禁（8 秒）的 claim 在跑时，只读工具**5 秒内**答（★ 本案命门；先红后绿） |
| ⑨ 失败如实带出 | 子进程非零退出 ⇒ 回话里**既有退出码又有原文**（不许吞、不许假装成功） |
| ⑩ 超时不当成功 | 子进程超时 ⇒ 回话写"没跑完"，**不许**当成成功 |

★ 卡 A364（`usage_report` 开外部用量上报的入口）另加七条：

| 钉子 | 判什么 |
|---|---|
| ⑪ 只开入口 | 没 `POOL_MCP_WRITE=1` 不列出来；有 env 才列，且 `readOnlyHint` 必须是 false |
| ⑫ `confirm` = 条数 | `confirm` 必须等于**这一批的记录条数**；不符 ⇒ 拒且点名「收到 N 条」 |
| ⑬ 判据只有一份 | `pool_mcp.py` 里**没有**第二份字段表/上限/`rid` 判据；写盘的是
  `usage_ingest.ingest()` |
| ⑭ faults 原文 | 判据层拒单 ⇒ 回话带**逐条** `faults` 原文，一条都不写盘 |
| ⑮ 回执原样 | 成功回 `{"accepted","skipped","records"}` —— 字段名一个都不翻译 |
| ⑯ `isError` 跟判决 | 拒单 `true` / 成功 `false` —— 四条拒单路径逐条过 |
| ⑰ 不碰派活器的账 | `gates/diag/wb-usage.jsonl` **一个字节不变**（sha256 前后比） |

★ 一律把 `TF_BATCH_DIR` 指到临时目录 —— 一个字节都不写进真的 `gates/diag/batch/`。
★ 导入口径照既有测试：把 `tools/` 挂上 `sys.path` 再 `import pool_mcp` / `pool.task`。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pool_accounts as pa  # noqa: E402
import pool_mcp  # noqa: E402 —— tools/ 已在 sys.path 上
from pool import task  # noqa: E402

READ_POOL_NAMES = [
    "pool_plan",
    "job_list",
    "job_status",
    "job_result",
    "lock_status",
    "pool_models",
    # ★ 卡 201（T-G303）：第 10 个只读工具 —— 额度状态按钟表算
    "quota_status",
    "account_status",  # ★ 卡 E45（T-AG496）：账号账本，不探测、不联网
    # ★ 卡 E48（T-AG497）：今日签到读数（读留档，永不触发签到）
    "checkin_status",
    # ★ 卡 213（T-G325）：第 11 个只读工具 —— 工作台读数（调 pipeline_view）
    "workbench_board",
]
READ_TASK_NAMES = ["task_list", "task_status", "task_pool"]
READ_TOOL_NAMES = [*READ_POOL_NAMES, *READ_TASK_NAMES]
WRITE_TOOL_NAMES = [
    "pool_dispatch",
    "pool_cancel",
    # ★ 卡 A364（T-AG578）：第 5 个写工具 —— 外部用量上报（confirm = 这一批的条数）
    "usage_report",
    "task_register",
    "task_claim",
]

SERVER_SNIPPET = "import sys; from pool_mcp import serve; raise SystemExit(serve(sys.argv[1:]))"

#: 一份合法的预声明：审美层 + 后端各一张卡，域互不相交。
MANIFEST = """\
id = "T-1"
why = "审美层 + 后端一次收口"
gate_cmd = "python -X utf8 tools/wb_task.py list"
on_complete = ["gate", "draft"]

[[member]]
id = "卡A"
layer = "后端"
what = "甲"
paths = ["tools/a/*"]

[[member]]
id = "卡B"
layer = "审美层"
what = "乙"
paths = ["ui/*"]
"""

JSON_MARKER = "--- tf-json ---"  # 与 tools/pool_mcp.py::JSON_MARKER 逐字一致


# ---------------------------------------------------------------- 报文小工具（照 test_pool_mcp.py）


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
    return result["content"][0]["text"]


def _json_block(text: str) -> dict[str, Any]:
    """取唯一标记之后那一行单行紧凑 JSON（解不开 = 形状不对）。"""
    assert JSON_MARKER in text, f"回复里没有机器可读块标记 {JSON_MARKER!r}"
    after = text.split(JSON_MARKER, 1)[1]
    line = next((ln for ln in after.splitlines() if ln.lstrip().startswith("{")), None)
    assert line is not None, "唯一标记之后没有机器可读块"
    return json.loads(line)


# ---------------------------------------------------------------- 夹具


@pytest.fixture()
def batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把任务目录（`TF_BATCH_DIR`）指到临时目录 —— 绝不动真的 `gates/diag/batch/`。"""
    d = tmp_path / "batch"
    monkeypatch.setenv("TF_BATCH_DIR", str(d))
    return d


@pytest.fixture()
def write_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POOL_MCP_WRITE", "1")


def _seed(d: Path, manifest: str = MANIFEST) -> None:
    """用 `pool.task` 本体注册一个任务（测试侧不碰 MCP 的注册路，好单独验注册）。"""
    src = d.parent / "src"
    src.mkdir(parents=True, exist_ok=True)
    man = src / "T-1.toml"
    man.write_text(manifest, encoding="utf-8", newline="\n")
    assert task.main(["register", str(man)]) == 0


def _files_under(d: Path) -> set[str]:
    return {p.relative_to(d).as_posix() for p in d.rglob("*")} if d.exists() else set()


def _untracked() -> set[str]:
    done = subprocess.run(
        ["git", "status", "--porcelain", "-uall"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {ln for ln in (done.stdout or "").splitlines() if ln.startswith("??")}


# ================================================================ ① 只读三个


def test_read_tools_return_machine_block(batch: Path) -> None:
    """三个只读工具都返回内容 + 机器可读块；`task_status` 把层/域都摊出来。"""
    _seed(batch)
    for name, args in (("task_list", {}), ("task_status", {"task": "T-1"}), ("task_pool", {})):
        result = pool_mcp.call_tool(name, args)
        assert result is not None, name
        assert result["content"][0]["type"] == "text", name
        text = _text(result)
        assert text.strip(), name
        block = _json_block(text)  # 解不开 = 形状不对
        assert isinstance(block, dict), name

    _, data, _ = pool_mcp.tool_task_list({})
    assert data["count"] == 1 and data["tasks"][0]["id"] == "T-1"

    _, st, _ = pool_mcp.tool_task_status({"task": "T-1"})
    assert st["layers"] == ["后端", "审美层"]
    assert {m["id"] for m in st["members"]} == {"卡A", "卡B"}
    assert st["members"][0]["paths"] == ["tools/a/*"]
    assert st["history_total"] >= 1


def test_read_tools_write_nothing(batch: Path) -> None:
    """跑一遍三个只读工具：**任务目录不多一个文件**、**工作区不多一个未跟踪文件**（卡 105）。"""
    _seed(batch)
    before_files, before_untracked = _files_under(batch), _untracked()
    for name, args in (("task_list", {}), ("task_status", {"task": "T-1"}), ("task_pool", {})):
        pool_mcp.call_tool(name, args)
    assert _files_under(batch) == before_files, "只读工具不许在任务目录里新建/删除文件"
    assert _untracked() == before_untracked, "只读工具不许在工作区多出未跟踪文件"


def test_task_status_unknown_task_says_clearly(batch: Path) -> None:
    """⑥ 不存在的任务 ⇒ 明说"没有"、`found=false`、**不崩、不带假数据**。"""
    result = pool_mcp.call_tool("task_status", {"task": "NOPE"})
    assert result is not None and result["isError"] is True
    text = _text(result)
    assert "没有" in text and "NOPE" in text
    block = _json_block(text)
    assert block["found"] is False and "members" not in block


# ================================================================ ② 授权（tools/list）


def test_tools_list_without_env_is_nine_read(batch: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """没 env ⇒ **11 个只读**；两个任务写工具当"没有这个工具"（`-32602`）。"""
    monkeypatch.delenv("POOL_MCP_WRITE", raising=False)
    names = [t["name"] for t in pool_mcp.handle(_req(1, "tools/list"))["result"]["tools"]]
    assert names == READ_TOOL_NAMES

    assert pool_mcp.call_tool("task_register", {"confirm": "T-1"}) is None
    assert pool_mcp.call_tool("task_claim", {"task": "T-1", "confirm": "T-1"}) is None
    reply = pool_mcp.handle(_call("task_register", {"confirm": "T-1"}))
    assert reply is not None and reply["error"]["code"] == pool_mcp.JSONRPC_INVALID_PARAMS
    assert "没有这个工具" in reply["error"]["message"]


def test_tools_list_with_env_adds_two_task_writes(batch: Path, write_on: None) -> None:
    """有 env ⇒ 11 只读 + 4 写；只读的 `readOnlyHint` 仍 true；任务写工具的 annotations 逐字。"""
    tools = pool_mcp.handle(_req(1, "tools/list"))["result"]["tools"]
    assert [t["name"] for t in tools] == [*READ_TOOL_NAMES, *WRITE_TOOL_NAMES]
    by_name = {t["name"]: t for t in tools}
    for name in READ_TOOL_NAMES:
        assert by_name[name]["annotations"]["readOnlyHint"] is True, name
    reg = by_name["task_register"]["annotations"]
    claim = by_name["task_claim"]["annotations"]
    assert (reg["readOnlyHint"], reg["destructiveHint"], reg["idempotentHint"]) == (
        False,
        False,
        False,
    )
    assert (claim["readOnlyHint"], claim["destructiveHint"], claim["idempotentHint"]) == (
        False,
        False,
        True,
    )
    assert by_name["task_status"]["inputSchema"]["required"] == ["task"]
    assert by_name["task_register"]["inputSchema"]["required"] == ["confirm"]
    assert by_name["task_claim"]["inputSchema"]["required"] == ["task", "member", "confirm"]


# ================================================================ ③ 写门 confirm


def test_register_confirm_must_equal_manifest_id(batch: Path, write_on: None) -> None:
    """★ `task_register` 的 `confirm` 不等于 TOML 里的 `id` ⇒ **拒**，且**不落盘**。"""
    result = pool_mcp.call_tool("task_register", {"manifest_text": MANIFEST, "confirm": "T-9"})
    assert result is not None and result["isError"] is True
    text = _text(result)
    assert "confirm" in text and "T-1" in text
    assert not (batch / "T-1.json").exists() and not (batch / "T-1.toml").exists()


def test_claim_confirm_must_equal_task(batch: Path, write_on: None) -> None:
    """★ `task_claim` 的 `confirm` 不等于任务号 ⇒ **拒**，且没留下任何申请。"""
    _seed(batch)
    result = pool_mcp.call_tool(
        "task_claim",
        {
            "task": "T-1",
            "member": "卡A",
            "claim": "success",
            "evidence": "pytest",
            "files": ["tools/a/x.py"],
            "confirm": "T-2",
        },
    )
    assert result is not None and result["isError"] is True
    assert "confirm" in _text(result)
    assert not (batch / "T-1.d" / "卡A.json").exists()
    st = task.read_json(batch / "T-1.json")
    assert st["claims"] == {} and st["state"] == "collecting"


# ================================================================ ⑤ 域守卫不许绕


def test_claim_out_of_domain_is_refused_and_named(batch: Path, write_on: None) -> None:
    """★★ `task_claim` 带域外文件 ⇒ **拒并点名**（守卫在 MCP 这条路上也不能绕）。"""
    _seed(batch)
    result = pool_mcp.call_tool(
        "task_claim",
        {
            "task": "T-1",
            "member": "卡A",
            "claim": "success",
            "evidence": "pytest 3 passed",
            "files": ["docs/别的.md"],
            "why": "越界",
            "confirm": "T-1",
        },
    )
    assert result is not None and result["isError"] is True
    text = _text(result)
    assert "自己域外" in text and "docs/别的.md" in text  # 点名到文件
    assert "tools/a/*" in text  # 并指出这张卡的域
    # 越界那次**没留下**申请、状态没动
    assert not (batch / "T-1.d" / "卡A.json").exists()
    assert task.read_json(batch / "T-1.json")["claims"] == {}


def test_claim_and_register_happy_path(batch: Path, write_on: None) -> None:
    """正路：MCP 注册 → 两张卡都交成功申请 → 集齐放行（停在 awaiting-commit）。"""
    reg = pool_mcp.call_tool("task_register", {"manifest_text": MANIFEST, "confirm": "T-1"})
    assert reg is not None and reg["isError"] is False
    assert (batch / "T-1.json").exists() and (batch / "T-1.toml").exists()
    assert _json_block(_text(reg))["declared"] == ["卡A", "卡B"]

    a = pool_mcp.call_tool(
        "task_claim",
        {
            "task": "T-1",
            "member": "卡A",
            "claim": "success",
            "evidence": "pytest 3 passed",
            "files": ["tools/a/x.py"],
            "confirm": "T-1",
        },
    )
    assert a is not None and a["isError"] is False
    assert _json_block(_text(a))["success"] == 1

    b = pool_mcp.call_tool(
        "task_claim",
        {
            "task": "T-1",
            "member": "卡B",
            "claim": "success",
            "evidence": "ui 三张图都过",
            "files": ["ui/c.png"],
            "confirm": "T-1",
        },
    )
    assert b is not None and b["isError"] is False
    st = task.read_json(batch / "T-1.json")
    assert st["state"] == "awaiting-commit" and len(task._ok(st)) == 2


# ================================================================ 注册的来源 / 坏输入


def test_register_needs_manifest_source(batch: Path, write_on: None) -> None:
    """既没 `manifest_text` 也没 `manifest_path` ⇒ 说清（不崩）。"""
    result = pool_mcp.call_tool("task_register", {"confirm": "T-1"})
    assert result is not None and result["isError"] is True
    assert "manifest_text" in _text(result) and "manifest_path" in _text(result)


def test_register_from_path(batch: Path, write_on: None, tmp_path: Path) -> None:
    """`manifest_path` 走文件（相对仓库根或绝对都行）。"""
    man = tmp_path / "T-1.toml"
    man.write_text(MANIFEST, encoding="utf-8", newline="\n")
    result = pool_mcp.call_tool("task_register", {"manifest_path": str(man), "confirm": "T-1"})
    assert result is not None and result["isError"] is False
    assert (batch / "T-1.json").exists()


def test_register_bad_toml_is_refused(batch: Path, write_on: None) -> None:
    """预声明不是合法 TOML ⇒ 拒（不落盘）。"""
    result = pool_mcp.call_tool(
        "task_register", {"manifest_text": "id = , not toml {", "confirm": "T-1"}
    )
    assert result is not None and result["isError"] is True
    assert "TOML" in _text(result)


# ================================================================ 真 stdio 端到端


def _talk(
    messages: list[dict[str, Any]], env_extra: dict[str, str | None]
) -> tuple[list[dict[str, Any]], bytes, str, int]:
    env: dict[str, str] = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "tools")
    env.update({k: v for k, v in env_extra.items() if v is not None})
    for key, value in env_extra.items():
        if value is None:
            env.pop(key, None)  # `None` = 显式把它从环境里拿掉（"不设 env"）
    proc = subprocess.Popen(
        [sys.executable, "-c", SERVER_SNIPPET],
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


def test_real_stdio_task_tools_round_trip(batch: Path) -> None:
    """端到端（子进程，`POOL_MCP_WRITE=1`）：`tools/list` + 注册 + 成功申请 + 越界申请。"""
    replies, _raw, err, code = _talk(
        [
            _req(1, "tools/list"),
            _req(
                2,
                "tools/call",
                {
                    "name": "task_register",
                    "arguments": {"manifest_text": MANIFEST, "confirm": "T-1"},
                },
            ),
            _req(
                3,
                "tools/call",
                {
                    "name": "task_claim",
                    "arguments": {
                        "task": "T-1",
                        "member": "卡A",
                        "claim": "success",
                        "evidence": "pytest 3 passed",
                        "files": ["tools/a/x.py"],
                        "confirm": "T-1",
                    },
                },
            ),
            _req(
                4,
                "tools/call",
                {
                    "name": "task_claim",
                    "arguments": {
                        "task": "T-1",
                        "member": "卡B",
                        "claim": "success",
                        "evidence": "x",
                        "files": ["docs/别的.md"],
                        "confirm": "T-1",
                    },
                },
            ),
        ],
        {"TF_BATCH_DIR": str(batch), "POOL_MCP_WRITE": "1"},
    )
    assert code == 0, err
    assert [r["id"] for r in replies] == [1, 2, 3, 4], (replies, err)
    assert [t["name"] for t in replies[0]["result"]["tools"]] == [
        *READ_TOOL_NAMES,
        *WRITE_TOOL_NAMES,
    ]
    assert _json_block(replies[1]["result"]["content"][0]["text"])["registered"] is True
    assert _json_block(replies[2]["result"]["content"][0]["text"])["success"] == 1
    oob = replies[3]["result"]
    assert oob["isError"] is True
    assert "自己域外" in oob["content"][0]["text"]


def test_real_stdio_without_env_hides_task_writes(batch: Path) -> None:
    """端到端（不设 env）：`tools/list` 里**没有**那两个任务写工具。"""
    replies, _raw, err, code = _talk(
        [_req(1, "tools/list")], {"TF_BATCH_DIR": str(batch), "POOL_MCP_WRITE": None}
    )
    assert code == 0, err
    names = [t["name"] for t in replies[0]["result"]["tools"]]
    assert names == READ_TOOL_NAMES
    assert "task_register" not in names and "task_claim" not in names


# ================================================================ 卡 130：claim 走子进程
#
# GLM-5.3 的 2.3「放大器」：`task_claim` 进程内跑 ⇒ 最后一名 claimant 走 MCP 时，
# **MCP 服务进程**同步跑完整个门禁（stdio 全程冻结）。改法：claim 走**子进程**、
# `serve` 再把它交给**后台线程**。四条钉子各钉一处，缺一条这段就没牙。


def _claim_args(**over: Any) -> dict[str, Any]:
    """一份能过写门/域守卫的 `task_claim` 参数（要挪就覆盖个别键）。"""
    args: dict[str, Any] = {
        "task": "T-1",
        "member": "卡A",
        "claim": "success",
        "evidence": "pytest 3 passed",
        "files": ["tools/a/x.py"],
        "why": "自证",
        "confirm": "T-1",
    }
    args.update(over)
    return args


def test_claim_runs_in_a_subprocess_not_inprocess(
    batch: Path, write_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⑦ 真走子进程：`task_claim` 起 `wb_task.py claim …`，**不许**进程内调 `task.cmd_claim`。

    ★ 卡 136 起执行改走 `Popen` + `communicate(timeout=…)` —— 原因：`subprocess.run` 超时只杀
      **直连子进程**，真正吃 CPU / 占端口的门禁孙进程留成孤儿（本卡要治的正是这个）。本条判据
      **不变**（真起子进程 / 超时给足 / utf-8），只把钉的接缝从 `run` 挪到 `Popen`。
    """
    _seed(batch)
    calls: list[dict[str, Any]] = []

    class _Proc:
        pid = 4242
        returncode = 0

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            calls.append({"communicate_timeout": timeout})
            return "子进程说：收了\n", ""

        def poll(self) -> int:
            return 0

    def fake_popen(argv: list[str], **kwargs: Any) -> _Proc:
        calls.append({"argv": list(argv), **kwargs})
        return _Proc()

    def boom(*_a: Any, **_k: Any) -> int:
        raise AssertionError("task_claim 不许在进程内调 task.cmd_claim（必须走子进程）")

    monkeypatch.setattr(pool_mcp.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(task, "cmd_claim", boom)  # 进程内那条路一旦被走到就当场炸

    _t, _data, is_error = pool_mcp.tool_task_claim(_claim_args())

    assert is_error is False
    spawn = calls[0]
    argv = spawn["argv"]
    assert argv[0] == sys.executable, argv
    assert any(a.endswith("wb_task.py") for a in argv), argv
    assert "claim" in argv and "T-1" in argv and "卡A" in argv, argv
    assert spawn["encoding"] == "utf-8" and spawn["errors"] == "replace", spawn
    assert spawn["stdout"] == subprocess.PIPE and spawn["stderr"] == subprocess.PIPE, spawn
    timeouts = [c["communicate_timeout"] for c in calls if "communicate_timeout" in c]
    assert timeouts and min(timeouts) >= 1800, calls


def test_claim_subprocess_nonzero_exit_is_surfaced(
    batch: Path, write_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⑨ 子进程非零退出 ⇒ 回话里**既有退出码又有原文**（不许吞、不许假装成功）。"""
    _seed(batch)

    class _Proc:
        pid = 4243
        returncode = 2

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            return "部分输出：域守卫拒收\n", "错误原文：卡 卡A 碰了**自己域外**的文件\n"

        def poll(self) -> int:
            return 2  # 已退出 ⇒ 没有活子树可带（卡 136 也只如实记一句）

    monkeypatch.setattr(pool_mcp.subprocess, "Popen", lambda argv, **k: _Proc())
    text, data, is_error = pool_mcp.tool_task_claim(_claim_args())

    assert is_error is True
    assert "退出码 2" in text, text
    assert "部分输出" in text and "错误原文" in text, text
    assert data["claimed"] is False and data["exit_code"] == 2, data


def test_claim_subprocess_timeout_is_not_success(
    batch: Path, write_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⑩ 子进程超时 ⇒ 回话写"没跑完/超时"，**不许**当成成功（卡 136 起还会带走整棵树）。"""
    _seed(batch)

    class _Proc:
        pid = 4244
        returncode = None

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            raise subprocess.TimeoutExpired(cmd="wb_task.py", timeout=timeout)

        def poll(self) -> None:
            return None  # 还活着 ⇒ 走"带走整棵树"那条路

    monkeypatch.setattr(pool_mcp.subprocess, "Popen", lambda argv, **k: _Proc())
    # 杀树用桩（pid 4244 不存在，真 kill_tree 只会白跑）—— 钉子⑩只钉"超时不当成功"。
    monkeypatch.setattr(pool_mcp.wb_dispatch, "kill_tree", lambda pid: f"桩：已处理 {pid}")

    text, data, is_error = pool_mcp.tool_task_claim(_claim_args())

    assert is_error is True
    assert "没跑完" in text and "超时" in text, text
    assert data.get("timeout") is True and data.get("claimed") is False, data


#: 慢门禁：仓库内慢门禁桩睡 8 秒（claim 是最后一名投递者 ⇒ 当场跑它）。
SLOW_GATE_SECONDS = 8


def _slow_manifest(seconds: int = SLOW_GATE_SECONDS) -> str:
    """一个单成员任务，`gate_cmd` 睡 `seconds` 秒 —— 用来把"最后一名 claimant 跑门禁"演出来。

    ★ 2026-10-02 主控改的接缝：`gate_cmd` 从卡 128（`T-G226`）起**白名单化**（只认
      `python -X utf8 scripts/…` 或 `tools/…`，**不许** `python -c`）⇒ 原来的
      `"{sys.executable}" -X utf8 -c "…sleep…"` 会被 `register` 拒。改用仓库内的
      **慢门禁桩** `tools/_slow_gate_stub.py`（合法形态 + 真的会慢）。
    """
    gate = json.dumps(f"python -X utf8 tools/_slow_gate_stub.py {seconds}")
    return (
        'id = "T-SLOW"\nwhy = "慢门禁自证"\n'
        f'gate_cmd = {gate}\non_complete = ["gate", "draft"]\n\n'
        '[[member]]\nid = "卡A"\nlayer = "门禁层"\nwhat = "慢门禁"\n'
        'paths = ["tools/a/*"]\n'
    )


def test_stdio_not_frozen_while_claim_runs(batch: Path) -> None:
    """⑧ ★ 本案命门：慢门禁的 `task_claim` 在跑时，只读工具必须 **5 秒内**答。

    先红后绿：改前 claim **进程内**跑门禁 ⇒ 主循环被冻住，只读要等门禁跑完（≈8~10s）⇒ 红；
    改后 claim 走**子进程 + 后台线程** ⇒ 主循环继续读，只读即刻答 ⇒ 绿。
    """
    _seed(batch, _slow_manifest())
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "tools")
    env["TF_BATCH_DIR"] = str(batch)
    env["POOL_MCP_WRITE"] = "1"
    proc = subprocess.Popen(
        [sys.executable, "-c", SERVER_SNIPPET],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=str(ROOT),
    )
    got: dict[int, float] = {}

    def _read() -> None:
        for raw in proc.stdout:  # type: ignore[union-attr]
            if raw.strip():
                got[json.loads(raw.decode("utf-8"))["id"]] = time.monotonic()

    threading.Thread(target=_read, daemon=True).start()

    def _send(msg: dict[str, Any]) -> None:
        proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))  # type: ignore[union-attr]
        proc.stdin.flush()  # type: ignore[union-attr]

    try:
        _send(
            _req(
                1,
                "tools/call",
                {
                    "name": "task_claim",
                    "arguments": {
                        "task": "T-SLOW",
                        "member": "卡A",
                        "claim": "success",
                        "evidence": "自证",
                        "files": ["tools/a/x.py"],
                        "confirm": "T-SLOW",
                    },
                },
            )
        )
        time.sleep(1.0)
        t_status = time.monotonic()
        _send(_req(2, "tools/call", {"name": "task_status", "arguments": {"task": "T-SLOW"}}))

        deadline = t_status + 12.0
        while 2 not in got and time.monotonic() < deadline:
            time.sleep(0.05)
        assert 2 in got, f"只读工具没回话（收到的 id：{sorted(got)}）"
        latency = got[2] - t_status
        print(f"\n[钉子⑧] 慢门禁 running 时，只读 task_status 回话耗时 = {latency:.2f}s（阈值 5s）")
        # 贴两次读数（先红后绿）：改前这里会是 ≈7~10s（红），改后 < 0.5s（绿）。
        assert latency < 5.0, f"stdio 被 claim 冻住了：只读回话等了 {latency:.2f}s"
    finally:
        with contextlib.suppress(OSError):
            proc.stdin.close()  # type: ignore[union-attr]
        proc.wait(timeout=60)

    assert 1 in got, f"claim 的回话没到（收到的 id：{sorted(got)}）"


# ================================================================ 卡 136：超时/失败把整棵进程树带走
#
# 卡 130 把 claim 挪进子进程后自己报过一条没治的边界：**超时只杀 `subprocess.run` 的直连子进程**，
# 它再起的 grandchild 门禁进程（Windows）不在它的树下 ⇒ 真正吃 CPU / 占端口的还在跑（"孤儿门禁"）。
# 卡 136 把执行改走 `Popen` + `communicate(timeout=…)`，超时/失败时复用
# `wb_dispatch.kill_tree`（按 PID 收子树）把**整棵**带走。四条钉子各钉一处：


def _wait_until(pred: Any, timeout: float = 15.0) -> bool:
    """等 `pred()` 变真（最多 `timeout` 秒）—— 给"掐进程后等它真的消失"用。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.1)
    return bool(pred())


def test_claim_timeout_carries_away_the_grandchild(
    batch: Path, write_on: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """① ★★ 孙进程也死了：门禁桩**真起一个孙进程**，claim 超时 ⇒ 用 `psutil` 核它已不在。

    先红后绿：改前 `subprocess.run` 超时只杀直连子进程（桩），孙进程被留成孤儿 ⇒ **红**；
    改后 `Popen` + `kill_tree` 把整棵带走 ⇒ **绿**。

    ★ 桩给孙进程的 stdio 钉 `DEVNULL`：否则它继承 claim 子进程的捕获管道 → 直连子进程被杀后
      管道仍被孙进程握着（`subprocess.run` 的收尾 `communicate()` 会一直阻塞到它自己退出）——
      那会先把**测试自己**卡住，红是"卡住"而不是"断言失败"。
    """
    _seed(batch)
    pidfile = tmp_path / "grandchild.pid"
    stub = tmp_path / "spawn_gate_stub.py"
    stub.write_text(
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'],\n"
        "                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,\n"
        "                         stderr=subprocess.DEVNULL)\n"
        "open(sys.argv[1], 'w').write(str(child.pid))\n"
        "time.sleep(120)\n",
        encoding="utf-8",
        newline="\n",
    )
    monkeypatch.setattr(
        pool_mcp, "_claim_argv", lambda *a, **k: [sys.executable, str(stub), str(pidfile)]
    )
    monkeypatch.setattr(pool_mcp, "CLAIM_TIMEOUT_SECONDS", 3)

    psutil = pytest.importorskip("psutil")
    text, data, is_error = pool_mcp.tool_task_claim(_claim_args())
    grandchild = int(pidfile.read_text(encoding="utf-8").strip())
    try:
        assert is_error is True and "超时" in text, text
        gone = _wait_until(lambda: not psutil.pid_exists(grandchild), timeout=15.0)
        assert gone, f"孙进程 pid {grandchild} 仍在 —— 整棵没被带走（本卡要治的孤儿门禁）\n{text}"
    finally:
        with contextlib.suppress(Exception):  # 红的时候自己收尸，别留睡眠子进程
            psutil.Process(grandchild).kill()


def test_claim_normal_path_unchanged(batch: Path, write_on: None) -> None:
    """② 正常路径不受影响：不超时的 claim 照旧成功、回话形态不变（仍带机器可读块）。"""
    _seed(batch)
    text, data, is_error = pool_mcp.tool_task_claim(_claim_args())

    assert is_error is False, text
    assert data["claimed"] is True and data["claim"] == "success", data
    block = _json_block(text)  # 回话形态不变：正文 + 唯一标记后的机器块
    assert block["claimed"] is True and block["task"] == "T-1", block
    assert "没跑完" not in text and "超时" not in text, text


def test_claim_kill_failure_is_reported_not_swallowed(
    batch: Path, write_on: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """③ 杀不掉要如实说：`kill_tree` 抛异常 ⇒ 回话**点名"没带走 / 残留 pid"**，不许吞。"""
    pytest.importorskip("psutil")  # 残留判定要 psutil 才判得了
    _seed(batch)
    stub = tmp_path / "sleep_gate_stub.py"
    stub.write_text("import time\ntime.sleep(300)\n", encoding="utf-8", newline="\n")
    monkeypatch.setattr(pool_mcp, "_claim_argv", lambda *a, **k: [sys.executable, str(stub)])
    monkeypatch.setattr(pool_mcp, "CLAIM_TIMEOUT_SECONDS", 3)

    real_kill = pool_mcp.wb_dispatch.kill_tree

    def boom(pid: int) -> str:
        raise RuntimeError(f"桩：杀不掉 {pid}")

    monkeypatch.setattr(pool_mcp.wb_dispatch, "kill_tree", boom)

    text, data, is_error = pool_mcp.tool_task_claim(_claim_args())
    try:
        assert is_error is True and "超时" in text, text
        assert "没带走" in text and "残留" in text, text
        assert data["killed"] is False and data["residual"], data
        assert str(data["pids"][0]) in text, text
    finally:
        # 收尸：kill 被桩掉了，真起来的桩子树得由测试自己清掉（别留睡眠子进程）。
        with contextlib.suppress(Exception):
            real_kill(data["pids"][0])


def test_tools_list_counts_unchanged(batch: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """④ 工具清单没变：没 env = **13**（全只读）；`POOL_MCP_WRITE=1` = **18**。

    ★ 卡 201（T-G303）：加了第 10 个只读工具 `quota_status`（额度按钟表算，只读）⇒
      9/13 → 10/14。★ 卡 213（T-G325）：加了第 11 个只读工具 `workbench_board`
      ★ 卡 E45（T-AG496）：加第 12 个只读工具 `account_status` ⇒ 11/15 → 12/16。
      ★ 卡 A364（T-AG578）：加第 5 个写工具 `usage_report`（外部用量上报的入口）⇒ 13/17 → 13/18。
      **没人放松判据** ——
      只是把新工具如实记进来。
    """
    monkeypatch.delenv("POOL_MCP_WRITE", raising=False)
    thirteen = pool_mcp.handle(_req(1, "tools/list"))["result"]["tools"]
    assert len(thirteen) == 13, [t["name"] for t in thirteen]
    assert all(t["annotations"]["readOnlyHint"] is True for t in thirteen), thirteen

    monkeypatch.setenv("POOL_MCP_WRITE", "1")
    eighteen = pool_mcp.handle(_req(1, "tools/list"))["result"]["tools"]
    assert len(eighteen) == 18, [t["name"] for t in eighteen]


# --------------------------------------- 卡 E48：checkin_status（只读留档，永不触发签到）


def test_checkin_status_says_missing_when_no_archive(tmp_path) -> None:
    """没有留档 ⇒ found=False + 明说「今天还没跑过」，并指出真签要人跑哪条命令。"""
    text, payload, is_error = pool_mcp.tool_checkin_status({"date": "2026-01-02"}, root=tmp_path)
    assert is_error is False
    assert payload["found"] is False
    assert payload["date"] == "2026-01-02"
    assert "没有留档" in text
    assert "pool_accounts.py checkin" in text


def test_checkin_status_reads_archive(tmp_path) -> None:
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    (diag / "checkin-2026-01-02.json").write_text(
        json.dumps(
            {
                "date": "2026-01-02",
                "applied": False,
                "results": [
                    {"id": "x", "platform": "trae", "kind": "uncertain", "detail": "缺 token"},
                    {"id": "y", "platform": "codebuddy", "kind": "not-supported"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    text, payload, is_error = pool_mcp.tool_checkin_status({"date": "2026-01-02"}, root=tmp_path)
    assert is_error is False
    assert payload["found"] is True
    assert payload["applied"] is False
    assert payload["results"][0]["id"] == "x"
    assert "只探未领" in text
    assert "not-supported=1" in text and "uncertain=1" in text


def test_checkin_status_is_offline_and_never_writes(tmp_path, monkeypatch) -> None:
    """★ 判据本体：这个工具只读 —— 断网照常出读数，且源码里没有领取端点。"""

    def _boom(*a, **k):  # pragma: no cover —— 被调用就说明它联网了
        raise AssertionError("checkin_status 不许联网")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    (diag / "checkin-2026-01-02.json").write_text(
        json.dumps({"date": "2026-01-02", "applied": True, "results": []}), encoding="utf-8"
    )
    text, payload, is_error = pool_mcp.tool_checkin_status({"date": "2026-01-02"}, root=tmp_path)
    assert is_error is False
    assert payload["found"] is True

    src = Path(pool_mcp.__file__).read_text(encoding="utf-8")
    for needle in ("/v1/ops/claim", "/daily-checkin", "checkin_credits/claim", "/signin/claim"):
        assert needle not in src, f"MCP 只读面里不许出现写端点：{needle}"
# --------------------------------------- 卡 E119：checkin_status 真读账本（不再只说留档）


def _checkin_ledger(tmp_path: Path, *, probe: str, checkin: str) -> Path:
    body = [
        "[[account]]",
        'id = "trae-1"',
        'label = "Trae 主号"',
        'platform = "trae"',
        'state = "active"',
        'added_at = "2026-10-20"',
        "approved_models = []",
        "",
        "[account.credential]",
        'kind = "none"',
        "",
        "[account.health]",
        'state = "unknown"',
        f'last_probe = "{probe}"',
        f'last_checkin = "{checkin}"',
        "",
    ]
    p = tmp_path / "infra" / "pool" / "accounts.toml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(chr(10).join(body), encoding="utf-8")
    return p


def _inject_ledger(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.delenv("TF_ACCOUNTS_TOML", raising=False)
    monkeypatch.setattr(pa, "find_ledger", lambda explicit=None: path)


def _checkin_archive(tmp_path: Path, date: str, *, applied: bool = False) -> Path:
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True, exist_ok=True)
    p = diag / f"checkin-{date}.json"
    p.write_text(json.dumps({"date": date, "applied": applied, "results": []}), encoding="utf-8")
    return p


_LEDGER_KEYS = {"ledger", "ledger_found", "ledger_rows", "ledger_error"}
_ROW_KEYS = {"id", "platform", "last_checkin", "last_probe", "last_probe_date", "is_today"}


def test_checkin_status_payload_separates_archive_from_ledger(tmp_path, monkeypatch) -> None:
    """判据 1：found 只指留档；账本另用四格。两件事在 payload 里永远分得开。"""
    _inject_ledger(
        monkeypatch,
        _checkin_ledger(tmp_path, probe="2026-10-25T18:30:46+08:00", checkin="uncertain"),
    )
    _text, payload, is_error = pool_mcp.tool_checkin_status({"date": "2026-11-16"}, root=tmp_path)
    assert is_error is False
    assert set(payload) == {"date", "archive", "found"} | _LEDGER_KEYS, sorted(payload)
    assert payload["found"] is False
    assert payload["ledger_found"] is True
    assert len(payload["ledger_rows"]) == 1
    assert set(payload["ledger_rows"][0]) == _ROW_KEYS
    assert payload["ledger_error"] == ""

    _checkin_archive(tmp_path, "2026-11-16")
    _text2, payload2, is_error2 = pool_mcp.tool_checkin_status(
        {"date": "2026-11-16"}, root=tmp_path
    )
    assert is_error2 is False
    assert set(payload2) == {"date", "archive", "found", "applied", "results"} | _LEDGER_KEYS
    assert payload2["found"] is True and payload2["ledger_found"] is True


def test_checkin_status_never_claims_today_from_a_stale_probe(tmp_path, monkeypatch) -> None:
    """判据 2：结论码必须与 last_probe 的日期一起说；旧日期不许写成今天的结论。"""
    _inject_ledger(
        monkeypatch,
        _checkin_ledger(tmp_path, probe="2026-10-25T18:30:46+08:00", checkin="uncertain"),
    )
    text, payload, _ = pool_mcp.tool_checkin_status({"date": "2026-11-16"}, root=tmp_path)
    row = payload["ledger_rows"][0]
    assert row["is_today"] is False
    assert row["last_probe_date"] == "2026-10-25"
    assert "2026-10-25" in text
    assert "今天签到" not in text

    _inject_ledger(
        monkeypatch, _checkin_ledger(tmp_path, probe="2026-11-16T09:00:00+08:00", checkin="claimed")
    )
    _text2, payload2, _ = pool_mcp.tool_checkin_status({"date": "2026-11-16"}, root=tmp_path)
    assert payload2["ledger_rows"][0]["is_today"] is True

    _inject_ledger(monkeypatch, _checkin_ledger(tmp_path, probe="", checkin="not-supported"))
    text3, payload3, _ = pool_mcp.tool_checkin_status({"date": "2026-11-16"}, root=tmp_path)
    assert payload3["ledger_rows"][0]["last_probe_date"] is None
    assert payload3["ledger_rows"][0]["is_today"] is False
    assert "没问过" in text3


def test_checkin_status_three_states_are_distinguishable(tmp_path, monkeypatch) -> None:
    """判据 3：留档没有 / 账本说 X / 账本读不了，三态互不覆盖，且都不翻 is_error。"""

    def _broken(explicit=None):
        raise pa.LedgerError("没找到账号账本。三种修法任一：设 TF_ACCOUNTS_TOML=<绝对路径>")

    monkeypatch.delenv("TF_ACCOUNTS_TOML", raising=False)
    monkeypatch.setattr(pa, "find_ledger", _broken)

    text, payload, is_error = pool_mcp.tool_checkin_status({"date": "2026-11-16"}, root=tmp_path)
    assert is_error is False
    assert payload["found"] is False and payload["ledger_found"] is False
    assert payload["ledger_error"]
    assert "没找到账号账本" in text

    _checkin_archive(tmp_path, "2026-11-16", applied=True)
    text2, payload2, is_error2 = pool_mcp.tool_checkin_status({"date": "2026-11-16"}, root=tmp_path)
    assert is_error2 is False
    assert payload2["found"] is True and payload2["ledger_found"] is False
    assert payload2["ledger_error"]

    _inject_ledger(
        monkeypatch, _checkin_ledger(tmp_path, probe="2026-11-16T09:00:00+08:00", checkin="claimed")
    )
    text3, payload3, is_error3 = pool_mcp.tool_checkin_status({"date": "2026-11-16"}, root=tmp_path)
    assert is_error3 is False
    assert payload3["found"] is True and payload3["ledger_found"] is True
    assert payload3["ledger_error"] == ""


def test_checkin_status_ledger_is_injectable_and_untouched(tmp_path, monkeypatch) -> None:
    """判据 4：账本可注入；跑完字节不变、目录无新文件；断网照常出读数。"""
    led = _checkin_ledger(tmp_path, probe="2026-10-25T18:30:46+08:00", checkin="uncertain")
    before = hashlib.sha256(led.read_bytes()).hexdigest()
    names_before = sorted(p.name for p in led.parent.iterdir())

    def _boom(*a, **k):  # pragma: no cover —— 被调用就说明它联网了
        raise AssertionError("checkin_status 不许联网")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    _inject_ledger(monkeypatch, led)
    _text, payload, is_error = pool_mcp.tool_checkin_status({"date": "2026-11-16"}, root=tmp_path)
    assert is_error is False
    assert payload["ledger_found"] is True
    assert hashlib.sha256(led.read_bytes()).hexdigest() == before, "账本被写了"
    assert sorted(p.name for p in led.parent.iterdir()) == names_before, "账本目录多了文件"


def test_checkin_status_prose_agrees_with_what_it_reads() -> None:
    """判据 5：description / docstring / README 表行三处同口径，都点明结论码不等于今天。"""
    desc = next(s for s in pool_mcp.TOOL_SPECS if s["name"] == "checkin_status")["description"]
    doc = pool_mcp.tool_checkin_status.__doc__ or ""
    readme = (ROOT / "docs" / "subsystems" / "pool" / "README.md").read_text(encoding="utf-8")
    rows = [ln for ln in readme.splitlines() if "checkin_status" in ln]
    assert len(rows) == 1, rows
    for where, blob in (("description", desc), ("docstring", doc), ("README", rows[0])):
        assert "留档" in blob, where
        assert "health.last_checkin" in blob, where
        assert "last_probe" in blob, where

# --------------------------------------- 卡 E130：非法日期串不许当今日、不许拼进路径

_MALFORMED_DATES = [
    "2026-1-2",
    "today",
    "20260102",
    "2026-W01-1",
    "2026-01-02T00:00:00",
    "２０２６-01-02",
]
_NON_CALENDAR_DATES = ["2026-02-30", "2026-13-99", "2026-02-29", "0000-01-01"]
_PATH_LIKE_DATES = ["../x", "../../../../outside/secret", "C:/tmp/x", "a\\b"]


def test_checkin_status_rejects_malformed_date(tmp_path) -> None:
    """判据 1 第一批：形状不对 ⇒ isError=True + 正文点名 YYYY-MM-DD，且不往下走。"""
    for bad in _MALFORMED_DATES:
        text, payload, is_error = pool_mcp.tool_checkin_status({"date": bad}, root=tmp_path)
        assert is_error is True, bad
        assert "YYYY-MM-DD" in text, bad
        assert "留档路径" not in text, bad
        assert "archive" not in payload, bad


def test_checkin_status_rejects_non_calendar_date(tmp_path) -> None:
    """判据 1 第二批：正则全过、日历上不存在 ⇒ 只能靠 date.fromisoformat 挡。"""
    for bad in _NON_CALENDAR_DATES:
        text, payload, is_error = pool_mcp.tool_checkin_status({"date": bad}, root=tmp_path)
        assert is_error is True, bad
        assert "YYYY-MM-DD" in text, bad
        assert "留档路径" not in text, bad
        assert "archive" not in payload, bad


def test_checkin_status_rejects_path_like_date(tmp_path) -> None:
    """判据 1 第三批：带 .. / 分隔符 ⇒ 拒收，且不许 stat 到树外去。"""
    diag = (tmp_path / "gates" / "diag").resolve()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.json").write_text(
        json.dumps({"results": [{"id": "leak", "platform": "outside-tree"}]}),
        encoding="utf-8",
    )
    for bad in _PATH_LIKE_DATES:
        text, payload, is_error = pool_mcp.tool_checkin_status({"date": bad}, root=tmp_path)
        assert is_error is True, bad
        assert "YYYY-MM-DD" in text, bad
        assert "留档路径" not in text, bad
        assert "leak" not in text, bad
        raw = payload.get("archive")
        if raw is not None:
            assert Path(raw).resolve().is_relative_to(diag), bad


def test_checkin_status_archive_stays_inside_diag_dir(tmp_path) -> None:
    """判据 2：合法日期才拼路径，resolve() 之后父目录恰好是 gates/diag。"""
    diag = (tmp_path / "gates" / "diag").resolve()
    for good in ("2026-01-02", "2024-02-29", "2026-12-31"):
        text, payload, is_error = pool_mcp.tool_checkin_status({"date": good}, root=tmp_path)
        assert is_error is False, good
        archive = Path(payload["archive"]).resolve()
        assert archive.parent == diag, good
        assert archive.name == f"checkin-{good}.json", good
    for bad in (*_MALFORMED_DATES, *_NON_CALENDAR_DATES, *_PATH_LIKE_DATES):
        assert pool_mcp.tool_checkin_status({"date": bad}, root=tmp_path)[2] is True, bad


def test_checkin_status_defaults_to_utc8_today(tmp_path) -> None:
    """判据 3：不给 date（四种空）⇒ 仍是今天；时区口径 UTC+8 一个字都不许改。"""
    from datetime import datetime as _dt  # noqa: PLC0415
    from datetime import timedelta as _td  # noqa: PLC0415
    from datetime import timezone as _tz  # noqa: PLC0415

    today = pool_mcp._today_local()
    for empty_args in ({}, {"date": ""}, {"date": "   "}, {"date": None}):
        text, payload, is_error = pool_mcp.tool_checkin_status(empty_args, root=tmp_path)
        assert is_error is False, empty_args
        assert payload["date"] == today, empty_args
    assert today == _dt.now(_tz(_td(hours=8))).strftime("%Y-%m-%d")
    src = Path(pool_mcp.__file__).read_text(encoding="utf-8")
    start = src.index("def _today_local")
    body = src[start:src.index("\n\n\ndef ", start)]
    assert "hours=8" in body
    assert "date.today()" not in body
# --------------------------------------- 卡 A364：usage_report（外部用量上报的入口）

USAGE_REPORTED_REL = ("gates", "diag", "usage-reported.jsonl")


def _usage_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把上报账本钉到临时 root —— 一个字节都不写进真的 `gates/diag/`。"""
    monkeypatch.delenv("TF_POOL_REPORTED", raising=False)
    return tmp_path / "root"


def _usage_record(rid: str, **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "rid": rid,
        "agent": "a",
        "provider": "p",
        "model": "m",
        "status": 200,
        "t": "2026-10-13T08:00:00Z",
    }
    row.update(over)
    return row


def _usage_body(*rows: dict[str, Any]) -> str:
    return json.dumps(list(rows), ensure_ascii=False)


def _usage_ledger(root: Path) -> Path:
    return root.joinpath(*USAGE_REPORTED_REL)


def test_usage_report_is_hidden_without_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⑪ 判据①：没 `POOL_MCP_WRITE=1` ⇒ **不列出来**，调用回 `-32602`（"没有这个工具"）。"""
    root = _usage_root(tmp_path, monkeypatch)
    monkeypatch.delenv("POOL_MCP_WRITE", raising=False)

    names = [t["name"] for t in pool_mcp.handle(_req(1, "tools/list"))["result"]["tools"]]
    assert "usage_report" not in names
    assert pool_mcp.call_tool("usage_report", {"body": "{}", "confirm": "1"}, root=root) is None

    reply = pool_mcp.handle(_call("usage_report", {"body": "{}", "confirm": "1"}), root=root)
    assert reply["error"]["code"] == pool_mcp.JSONRPC_INVALID_PARAMS
    assert "没有这个工具" in reply["error"]["message"]
    assert not _usage_ledger(root).exists()


def test_usage_report_is_a_write_tool_with_env(
    write_on: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⑪ 判据①：有 env ⇒ 列出来，且是**写**工具 —— `readOnlyHint` 必须是 false。"""
    _usage_root(tmp_path, monkeypatch)

    tools = pool_mcp.handle(_req(1, "tools/list"))["result"]["tools"]
    by_name = {t["name"]: t for t in tools}
    assert "usage_report" in by_name
    assert "usage_report" in pool_mcp.WRITE_NAMES
    assert "usage_report" not in pool_mcp.TASK_WRITE_NAMES
    assert "usage_report" not in [t["name"] for t in tools if t["annotations"]["readOnlyHint"]]

    ann = by_name["usage_report"]["annotations"]
    assert ann["readOnlyHint"] is False
    assert ann["destructiveHint"] is False
    assert ann["idempotentHint"] is True

    schema = by_name["usage_report"]["inputSchema"]
    assert schema["required"] == ["body"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"body", "confirm"}


def test_usage_confirm_must_equal_record_count(
    write_on: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⑫ 判据②：`confirm` 必须等于**记录条数**的十进制串；不符 ⇒ 拒且点名「收到 N 条」。"""
    root = _usage_root(tmp_path, monkeypatch)
    body = _usage_body(_usage_record("u1"), _usage_record("u2"))

    missing = pool_mcp.call_tool("usage_report", {"body": body}, root=root)
    assert missing is not None
    assert missing["isError"] is True
    assert "收到 2 条" in _text(missing)
    assert "confirm 给的 空" in _text(missing)
    assert not _usage_ledger(root).exists()

    wrong = pool_mcp.call_tool("usage_report", {"body": body, "confirm": "3"}, root=root)
    assert wrong is not None
    assert wrong["isError"] is True
    assert "收到 2 条" in _text(wrong)
    assert "confirm 给的 3" in _text(wrong)
    assert not _usage_ledger(root).exists()

    good = pool_mcp.call_tool("usage_report", {"body": body, "confirm": "2"}, root=root)
    assert good is not None
    assert good["isError"] is False
    assert len(_usage_ledger(root).read_text(encoding="utf-8").splitlines()) == 2


def test_usage_report_keeps_the_only_criteria_in_usage_ingest(
    write_on: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⑬ 判据③：正文里**只有一份判据** —— 入口不许再抄一遍字段表 / 上限 / `rid` 判据。"""
    _usage_root(tmp_path, monkeypatch)
    src = Path(pool_mcp.__file__).read_text(encoding="utf-8")
    for needle in (
        "FIELDS",
        "MAX_RECORDS",
        "MAX_TOKENS",
        "MAX_MILLIS",
        "MAX_TEXT",
        "MAX_BODY",
        "REQUIRED_TEXT",
        "_parse_one",
        "_known_rids",
        "_append_rows",
        "SOURCE_REPORTED",
        "REPORTED_REL",
        "EARLIEST",
    ):
        assert needle not in src, f"入口里冒出了第二份判据：{needle}"
    assert "usage_ingest.ingest(" in src


def test_usage_report_hands_the_body_to_the_criteria_layer(
    write_on: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⑬ 判据③：入口**只开入口** —— 真写盘的是 `usage_ingest.ingest()`（换成桩就看得见）。"""
    _usage_root(tmp_path, monkeypatch)
    seen: dict[str, Any] = {}
    stub = {
        "accepted": 7,
        "skipped": 1,
        "records": [{"index": 0, "rid": "spy", "status": "accepted"}],
    }

    def _spy(text: str, *, now: Any = None, root: Any = None) -> dict[str, Any]:
        seen["text"] = text
        seen["root"] = root
        return stub

    monkeypatch.setattr(pool_mcp.usage_ingest, "ingest", _spy)
    body = _usage_body(_usage_record("u9"))
    result = pool_mcp.call_tool(
        "usage_report", {"body": body, "confirm": "1"}, root=tmp_path / "root"
    )
    assert result is not None
    assert result["isError"] is False
    assert seen["text"] == body
    assert seen["root"] == tmp_path / "root"
    assert _json_block(_text(result)) == stub
    assert not _usage_ledger(tmp_path / "root").exists()


def test_usage_report_surfaces_every_fault_verbatim(
    write_on: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⑭ 判据④：判据层拒单 ⇒ 回话带**逐条** faults 原文；一个字节都不写盘。"""
    root = _usage_root(tmp_path, monkeypatch)
    body = _usage_body(
        _usage_record("v1"),
        _usage_record("v2", **{"in": -1}),
        _usage_record("v3", zzz=1),
    )

    result = pool_mcp.call_tool("usage_report", {"body": body, "confirm": "3"}, root=root)
    assert result is not None
    assert result["isError"] is True
    text = _text(result)
    # ★ 人读的那一半必须自己带原因：只把原文塞进机器块里不算 —— 报错信息没人看得见
    human = text.split(JSON_MARKER, 1)[0]
    assert "record 1: in: must not be negative" in human
    assert "record 2: zzz: is not a field a call has" in human

    payload = _json_block(text)
    assert [f["text"] for f in payload["faults"]] == [
        "record 1: in: must not be negative",
        "record 2: zzz: is not a field a call has",
    ]
    assert payload["accepted"] == 0
    assert payload["skipped"] == 0
    assert payload["records"] == []
    assert not _usage_ledger(root).exists()


def test_usage_report_success_payload_is_verbatim(
    write_on: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⑮ 判据⑤：成功回 `{"accepted","skipped","records"}` —— 字段名**一个都不翻译**。"""
    root = _usage_root(tmp_path, monkeypatch)
    body = _usage_body(_usage_record("w1"), _usage_record("w2"))

    first = pool_mcp.call_tool("usage_report", {"body": body, "confirm": "2"}, root=root)
    assert first is not None
    assert first["isError"] is False
    payload = _json_block(_text(first))
    assert set(payload) == {"accepted", "skipped", "records"}
    assert payload["accepted"] == 2
    assert payload["skipped"] == 0
    assert payload["records"] == [
        {"index": 0, "rid": "w1", "status": "accepted"},
        {"index": 1, "rid": "w2", "status": "accepted"},
    ]

    lines = _usage_ledger(root).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert all(json.loads(line)["source"] == "reported" for line in lines)

    again = pool_mcp.call_tool("usage_report", {"body": body, "confirm": "2"}, root=root)
    assert again is not None
    assert again["isError"] is False
    second = _json_block(_text(again))
    assert second["accepted"] == 0
    assert second["skipped"] == 2
    assert {r["status"] for r in second["records"]} == {"skipped"}
    assert len(_usage_ledger(root).read_text(encoding="utf-8").splitlines()) == 2


def test_usage_report_is_error_flag_follows_the_verdict(
    write_on: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⑯ 判据⑥：拒单 `isError=true`、成功 `false` —— 四条拒单路径逐条过。"""
    root = _usage_root(tmp_path, monkeypatch)
    cases: list[tuple[str, dict[str, Any]]] = [
        ("空 body", {"body": "", "confirm": "1"}),
        ("不是 JSON", {"body": "not json", "confirm": "1"}),
        ("条数不符", {"body": _usage_body(_usage_record("x1")), "confirm": "9"}),
        ("一条坏", {"body": _usage_body(_usage_record("x2", status=99)), "confirm": "1"}),
    ]
    for label, args in cases:
        result = pool_mcp.call_tool("usage_report", args, root=root)
        assert result is not None, label
        assert result["isError"] is True, label
    assert not _usage_ledger(root).exists()

    good = pool_mcp.call_tool(
        "usage_report", {"body": _usage_body(_usage_record("x3")), "confirm": "1"}, root=root
    )
    assert good is not None
    assert good["isError"] is False


def test_usage_report_never_touches_wb_usage_jsonl(
    write_on: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⑰ 判据⑦：`gates/diag/wb-usage.jsonl` **一个字节都不变**（混进去就永久不可判）。"""
    root = _usage_root(tmp_path, monkeypatch)
    diag = root / "gates" / "diag"
    diag.mkdir(parents=True)
    own = diag / "wb-usage.jsonl"
    original = (
        b'{"source": "dispatch", "card": "111", "model": "m", "in": 10, "out": 5}\n'
        b'{"source": "dispatch", "card": "112", "model": "m", "in": 1, "out": 2}\n'
    )
    own.write_bytes(original)
    before = hashlib.sha256(own.read_bytes()).hexdigest()
    before_stat = own.stat()

    # ① 成功一单 ② 判据层拒单 ③ confirm 不符 —— 三条路径都不许碰这本账
    pool_mcp.call_tool(
        "usage_report", {"body": _usage_body(_usage_record("y1")), "confirm": "1"}, root=root
    )
    pool_mcp.call_tool(
        "usage_report", {"body": _usage_body(_usage_record("y2", **{"in": -1})), "confirm": "1"},
        root=root,
    )
    pool_mcp.call_tool(
        "usage_report", {"body": _usage_body(_usage_record("y3")), "confirm": "9"}, root=root
    )

    after_stat = own.stat()
    assert hashlib.sha256(own.read_bytes()).hexdigest() == before
    assert own.read_bytes() == original
    assert (after_stat.st_size, after_stat.st_mtime_ns) == (
        before_stat.st_size,
        before_stat.st_mtime_ns,
    )
    assert _usage_ledger(root).exists()
    assert sorted(p.name for p in diag.iterdir()) == ["usage-reported.jsonl", "wb-usage.jsonl"]


# --------------------------------------- 卡 E114：五个只读面读的是**给我的那个根**


def _resolved(p) -> str:
    """路径比较先规范化（mcp 回 D:/、task 回 D:\\，直接比字符串会假红）。"""
    return Path(p).resolve().as_posix()


def test_task_faces_follow_the_root_they_are_given(tmp_path: Path, monkeypatch) -> None:
    """★ 判据 2-2：`root=R` ⇒ 三个任务面都读 `R/gates/diag/batch`；`TF_BATCH_DIR` 仍赢。

    病：签名里有 root，函数体里 `root_dir = _task_batch_dir()` 一次都不用 ——
    MCP 从 profile 目录被拉起时三条 task_* 面说「一个任务都没有」（真值 153 个）。
    """
    monkeypatch.delenv("TF_BATCH_DIR", raising=False)
    first = tmp_path / "one"
    second = tmp_path / "two"
    want_first = (first / "gates" / "diag" / "batch").as_posix()
    want_second = (second / "gates" / "diag" / "batch").as_posix()

    _text, data, _err = pool_mcp.tool_task_list({}, root=first)
    assert _resolved(data["batch_dir"]) == _resolved(want_first), data["batch_dir"]
    _text, data, _err = pool_mcp.tool_task_list({}, root=second)
    assert _resolved(data["batch_dir"]) == _resolved(want_second), data["batch_dir"]
    assert _resolved(want_first) != _resolved(want_second), (
        "两次不同 root 回同一个批目录 ⇒ root 被忽略"
    )
    _text, data, _err = pool_mcp.tool_task_pool({}, root=second)
    assert _resolved(data["batch_dir"]) == _resolved(want_second), data["batch_dir"]
    _text, data, _err = pool_mcp.tool_task_status({"task": "nope"}, root=second)
    assert _resolved(data["batch_dir"]) == _resolved(want_second), data.get("batch_dir")

    # 自证注入点（TF_BATCH_DIR）不许坏：设了就仍回它，哪怕 root 给了别的树
    injected = tmp_path / "injected"
    monkeypatch.setenv("TF_BATCH_DIR", str(injected))
    _text, data, _err = pool_mcp.tool_task_list({}, root=first)
    assert _resolved(data["batch_dir"]) == _resolved(injected), data["batch_dir"]


def test_pool_plan_judges_with_the_root_it_was_given(tmp_path: Path, monkeypatch) -> None:
    """★ 判据 2-3：`pool_plan` 的判据根是 `root`，不是进程 cwd。

    病：账本按 root 读（对），判据走 `plan.ROOT`（导入时由 cwd 派生）⇒ 从 profile 里
    调用回「361 行读不到规格」。这里 cwd 故意造一棵「只有 gates/diag、没有账本」的树。
    """
    cwd_tree = tmp_path / "profile"
    (cwd_tree / "gates" / "diag").mkdir(parents=True)
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "复盘" / "卡").mkdir(parents=True)
    (repo / "复盘" / "卡" / "卡DEMO.md").write_text("# demo\n", encoding="utf-8")
    (repo / "docs" / "workbacklog.toml").write_text(
        '[base]\nreviewed = "38522420"\n'
        '[[cards]]\nid = "DEMO"\ntask = "T-DEMO"\ntitle = "demo"\n'
        'tree = ".wt/DEMO"\nspec = "复盘/卡/卡DEMO.md"\nfiles = ["code/a.py"]\n'
        'risk = "low"\nstatus = "pending"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(cwd_tree)
    assert not (cwd_tree / "docs" / "workbacklog.toml").exists()
    text, data, _is_error = pool_mcp.tool_pool_plan({}, root=repo)
    assert data["exit_code"] == 0, text[-1200:]


def test_checkin_read_side_lands_on_the_write_side(tmp_path: Path) -> None:
    """★ 判据 3：读端与写端指向**同一个文件**（两格 cwd，子进程 —— `pa.DATA_ROOT` 导入时求值）。

    ① cwd = 真数据根（有 docs/workbacklog.toml）⇒ 两边都落在那棵树；
    ② cwd = 只有 gates/diag 的目录（profile 的迷你复刻）⇒ 两边都落回工具根，都不许落在它里面。
    """
    real = tmp_path / "data"
    (real / "docs").mkdir(parents=True)
    (real / "docs" / "workbacklog.toml").write_text(
        '[base]\nreviewed = "38522420"\n[[cards]]\nid = "D"\ntask = "T-D"\n'
        'title = "d"\ntree = ".wt/D"\nspec = "复盘/卡/卡D.md"\nfiles = []\n',
        encoding="utf-8",
    )
    profile = tmp_path / "profile"
    (profile / "gates" / "diag").mkdir(parents=True)
    probe = "\n".join([
        "import sys, json",
        "sys.path.insert(0, sys.argv[1])",
        "import pool_mcp, pool_accounts as pa",
        'text, data, _err = pool_mcp.tool_checkin_status({"date": "2026-01-02"})',
        "print(json.dumps({\"archive\": str(data[\"archive\"]),",
        "                  \"write\": str(pa._checkin_archive(\"2026-01-02\")),",
        "                  \"data_root\": str(pa.DATA_ROOT)}))",
    ]) + "\n"
    script = tmp_path / "probe.py"
    script.write_text(probe, encoding="utf-8", newline="\n")
    env = dict(os.environ)
    for key in ("PIPE_DATA", "PIPE_HOME", "TF_ACCOUNTS_TOML"):
        env.pop(key, None)
    tool_root = Path(pool_mcp.__file__).resolve().parent.parent
    seen: dict[str, dict[str, str]] = {}
    for label, cwd, must_be in (
        ("real", real, real.resolve()),
        ("profile", profile, tool_root.resolve()),
    ):
        run = subprocess.run(
            [sys.executable, "-X", "utf8", str(script), str(tool_root / "tools")],
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8", errors="replace",
            timeout=180,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        assert run.returncode == 0, run.stdout[-800:] + run.stderr[-800:]
        got = json.loads(run.stdout.strip().splitlines()[-1])
        seen[label] = got
        read = Path(got["archive"]).resolve()
        write = Path(got["write"]).resolve()
        assert read == write, f"{label}：读端 {read} ≠ 写端 {write}"
        assert read.parent.parent.parent.resolve() == must_be, (
            f"{label}：落在 {read} 而不是 {must_be}"
        )
    assert Path(seen["real"]["data_root"]).resolve() == real.resolve()
    assert Path(seen["profile"]["data_root"]).resolve() == tool_root.resolve()

# ============================================ 卡 E129：读不懂的状态文件要点名，不许洗成没有

# ★ 这一段的病：工具读**任务面**（task_list / task_status / wb_task list）时，
#   一个读不懂的状态文件被 except BatchError: continue 静默丢掉 ⇒ 盘上明明有个
#   文件，回话却说「一个任务都没有」。读不懂被洗成不存在，是**撒谎**。
#
#   判据 1：坏文件进 broken 通道并点名（不许当没有、不许当 isError）；
#   判据 2：老状态缺 waived / declared 一律按缺省处理，不许 KeyError；
#   判据 3：缺 declared 不猜成空名单（空名单 = 齐了）；
#   判据 4：count == len(tasks)，tasks + broken == 盘上文件数；
#   判据 5：wb_task list 也逐条念「读不了」，不冒充「还没有任务」。


def _write_bad_state(d: Path, name: str, body: str | bytes) -> Path:
    """往批目录里塞一个坏状态文件（d 是任务目录本身）。"""
    d.mkdir(parents=True, exist_ok=True)
    path = d / name
    if isinstance(body, bytes):
        path.write_bytes(body)
    else:
        path.write_text(body, encoding="utf-8", newline="\n")
    return path


def _state_without(state_path: Path, *keys: str) -> dict[str, Any]:
    """把注册好的状态文件里若干键**删掉**，模拟老形状（判据 2/3）。"""
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    for key in keys:
        raw.pop(key, None)
    state_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return raw


def test_task_list_names_broken_state_file(batch: Path) -> None:
    """判据 1：一个坏 JSON 不许被洗成「一个任务都没有」—— 要点名、要能数出来。"""
    _seed(batch)
    _write_bad_state(batch, "T-9.json", "{断掉的 json")
    text, data, is_error = pool_mcp.tool_task_list({})
    assert is_error is False, text
    assert [b["file"] for b in data["broken"]] == ["T-9.json"], data["broken"]
    assert data["broken"][0]["error"], "点了名却没给原因"
    assert "★ 读不了：T-9.json" in text, text
    assert "一个任务都没有" not in text, "有文件在盘上还说没有任务"
    assert "另有 1 个状态文件读不了" in text, text
    assert data["count"] == 1 and data["tasks"][0]["id"] == "T-1"


def test_task_list_broken_is_not_batch_error_only(batch: Path) -> None:
    """判据 1：坏文件是**读数**不是报错 —— 好任务照样列出来（不许整份失败）。"""
    _seed(batch)
    _write_bad_state(batch, "T-8.json", "[]")
    _write_bad_state(batch, "T-7.json", b"\xff\xfe")
    text, data, is_error = pool_mcp.tool_task_list({})
    assert is_error is False, text
    names = sorted(b["file"] for b in data["broken"])
    assert names == ["T-7.json", "T-8.json"], names
    assert data["tasks"][0]["id"] == "T-1"
    for item in data["broken"]:
        assert "★ 读不了：" + item["file"] in text


def test_task_list_broken_differs_from_no_files(batch: Path) -> None:
    """判据 1/4：零文件与坏文件是**两种读数**（不许同一句话打发）。"""
    empty, _, _ = pool_mcp.tool_task_list({})
    assert "一个任务都没有" in empty

    _write_bad_state(batch, "T-5.json", "not json at all")
    text, data, _ = pool_mcp.tool_task_list({})
    assert "一个任务都没有" not in text, text
    assert data["count"] == 0 and len(data["broken"]) == 1
    assert "（共 0 个任务，另有 1 个状态文件读不了）" in text, text


def test_task_list_description_mentions_unreadable() -> None:
    """判据 1：工具说明书也得说它会点名读不了的文件（否则别的窗口不知道有这个读数）。"""
    spec = next(s for s in pool_mcp.TASK_TOOL_SPECS if s["name"] == "task_list")
    desc = spec["description"]
    assert "读不了" in desc, desc
    assert "点名" in desc, desc


def test_task_list_count_reconciles_with_broken(batch: Path) -> None:
    """判据 4：count 只数读得懂的那些；tasks + broken 必须等于盘上的 .json 数。"""
    _seed(batch)
    _write_bad_state(batch, "T-4.json", "{}")
    _write_bad_state(batch, "T-3.json", "{\"id\": \"T-3\"}")
    _write_bad_state(batch, "pool.json", "{\"pool\": []}")
    _, data, _ = pool_mcp.tool_task_list({})
    on_disk = [p.name for p in batch.glob("*.json") if p.name != "pool.json"]
    assert len(data["tasks"]) == data["count"], data
    assert data["count"] + len(data["broken"]) == len(on_disk), (data, on_disk)
    assert sorted(b["file"] for b in data["broken"]) == ["T-3.json", "T-4.json"]


def test_task_list_missing_declared_is_named_not_dropped(batch: Path) -> None:
    """判据 3：缺 declared 报「结构不对」，**不许**当成空名单 / 当成不存在。"""
    _seed(batch)
    _write_bad_state(batch, "T-2.json", "{\"id\": \"T-2\", \"state\": \"collecting\"}")
    text, data, _ = pool_mcp.tool_task_list({})
    item = next(b for b in data["broken"] if b["file"] == "T-2.json")
    assert "结构不对" in item["error"] and "declared" in item["error"], item
    assert "★ 读不了：T-2.json" in text


def test_task_list_tolerates_state_without_waived(batch: Path) -> None:
    """判据 2：老状态没有 waived 键 ⇒ 当空列表，不许 KeyError。"""
    _seed(batch)
    _state_without(task.state_path("T-1"), "waived")
    text, data, is_error = pool_mcp.tool_task_list({})
    assert is_error is False, text
    assert data["tasks"][0]["waived"] == []
    assert data["tasks"][0]["missing"], "名单没交齐 ⇒ 还缺不算空"


def test_task_status_tolerates_state_without_waived(batch: Path) -> None:
    """判据 2：task_status 也读同一个老状态 —— 缺 waived 不许崩。"""
    _seed(batch)
    _state_without(task.state_path("T-1"), "waived")
    text, data, is_error = pool_mcp.tool_task_status({"task": "T-1"})
    assert is_error is False, text
    assert data["waived"] == []
    assert data["members"] and data["members"][0]["waived"] is False


def test_helpers_tolerate_state_without_waived() -> None:
    """判据 2：帮手函数自己也扛得住（_missing / _bad / _report 的裸下标已收掉）。"""
    state = {
        "id": "T-old", "declared": ["卡A", "卡B"], "need": 2, "read_only": [],
        "state": "collecting", "claims": {"卡A": "failed"}, "auto": [], "gate": None,
    }
    assert task._missing(state) == "卡A、卡B"
    assert task._bad(state) == ["卡A"]
    state["waived"] = None
    assert task._missing(state) == "卡A、卡B"
    assert task._bad(state) == ["卡A"]
    task._report(state)


def test_task_helpers_refuse_state_without_declared() -> None:
    """判据 3：_required 缺 declared ⇒ 抛 BatchError，**不许**回空列表。"""
    for broken_state in ({"id": "T", "need": 0}, {"id": "T", "declared": None}):
        with pytest.raises(task.BatchError) as caught:
            task._required(broken_state)
        assert "declared" in str(caught.value), str(caught.value)


def test_task_status_refuses_state_without_declared(batch: Path) -> None:
    """判据 3：task_status 遇到缺名单的状态 ⇒ 明说读不了（不造假详情）。"""
    _seed(batch)
    _state_without(task.state_path("T-1"), "declared")
    text, data, is_error = pool_mcp.tool_task_status({"task": "T-1"})
    assert is_error is True, text
    assert "declared" in text, text
    assert "members" not in data, data


def test_wb_task_list_says_unreadable_not_missing(
    batch: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """判据 5：wb_task list（CLI 人话）也逐条念「读不了」。"""
    assert task.main(["list"]) == 0
    assert "（还没有任务" in capsys.readouterr().out

    _write_bad_state(batch, "T-1.json", "{坏的")
    assert task.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "★ 读不了：T-1.json" in out, out
    assert "（还没有任务" not in out, out


def test_broken_reading_keeps_stdout_json_block(batch: Path) -> None:
    """判据 7：有坏文件时，走 MCP 那条路也解得开机器块，且 broken 在里面。"""
    _seed(batch)
    _write_bad_state(batch, "T-9.json", "{断掉的 json")
    result = pool_mcp.call_tool("task_list", {})
    assert result is not None
    block = _json_block(_text(result))
    assert block["count"] == 1 and block["tasks"][0]["id"] == "T-1"
    assert [b["file"] for b in block["broken"]] == ["T-9.json"]
