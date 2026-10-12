r"""任务栅栏接到外包面（MCP 的任务类工具）的钉子 —— 卡 121 · T-G218。

为什么值当测：这一段把**任务栅栏**（注册一个跨层的任务 → 每张卡交成送申请 → 集齐才收口）
接到别的窗口的 AI 能敲的 MCP 工具上。错的方式有几种，全是**别的窗口读到假现状**或**静默绕守卫**：

| 钉子 | 判什么 |
|---|---|
| ① 只读三个 | 三个任务只读工具都返回、都带机器可读块、且**不写一个文件** |
| ② 授权（`tools/list`） | 不设 env = **9 个**只读；设 `POOL_MCP_WRITE=1` 才多出两个写工具 |
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

★ 一律把 `TF_BATCH_DIR` 指到临时目录 —— 一个字节都不写进真的 `gates/diag/batch/`。
★ 导入口径照既有测试：把 `tools/` 挂上 `sys.path` 再 `import pool_mcp` / `pool.task`。
"""

from __future__ import annotations

import contextlib
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

import pool_mcp  # noqa: E402 —— tools/ 已在 sys.path 上
from pool import task  # noqa: E402

READ_POOL_NAMES = ["pool_plan", "job_list", "job_status", "job_result", "lock_status",
                   "pool_models",
                   # ★ 卡 201（T-G303）：第 10 个只读工具 —— 额度状态按钟表算
                   "quota_status"]
READ_TASK_NAMES = ["task_list", "task_status", "task_pool"]
READ_TOOL_NAMES = [*READ_POOL_NAMES, *READ_TASK_NAMES]
WRITE_TOOL_NAMES = ["pool_dispatch", "pool_cancel", "task_register", "task_claim"]

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
    done = subprocess.run(["git", "status", "--porcelain", "-uall"], cwd=str(ROOT),
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
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


def test_tools_list_without_env_is_nine_read(batch: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """没 env ⇒ **9 个只读**；两个任务写工具当"没有这个工具"（`-32602`）。"""
    monkeypatch.delenv("POOL_MCP_WRITE", raising=False)
    names = [t["name"] for t in pool_mcp.handle(_req(1, "tools/list"))["result"]["tools"]]
    assert names == READ_TOOL_NAMES

    assert pool_mcp.call_tool("task_register", {"confirm": "T-1"}) is None
    assert pool_mcp.call_tool("task_claim", {"task": "T-1", "confirm": "T-1"}) is None
    reply = pool_mcp.handle(_call("task_register", {"confirm": "T-1"}))
    assert reply is not None and reply["error"]["code"] == pool_mcp.JSONRPC_INVALID_PARAMS
    assert "没有这个工具" in reply["error"]["message"]


def test_tools_list_with_env_adds_two_task_writes(batch: Path, write_on: None) -> None:
    """有 env ⇒ 10 只读 + 4 写；只读的 `readOnlyHint` 仍 true；任务写工具的 annotations 逐字。"""
    tools = pool_mcp.handle(_req(1, "tools/list"))["result"]["tools"]
    assert [t["name"] for t in tools] == [*READ_TOOL_NAMES, *WRITE_TOOL_NAMES]
    by_name = {t["name"]: t for t in tools}
    for name in READ_TOOL_NAMES:
        assert by_name[name]["annotations"]["readOnlyHint"] is True, name
    reg = by_name["task_register"]["annotations"]
    claim = by_name["task_claim"]["annotations"]
    assert (reg["readOnlyHint"], reg["destructiveHint"], reg["idempotentHint"]) == (
        False, False, False)
    assert (claim["readOnlyHint"], claim["destructiveHint"], claim["idempotentHint"]) == (
        False, False, True)
    assert by_name["task_status"]["inputSchema"]["required"] == ["task"]
    assert by_name["task_register"]["inputSchema"]["required"] == ["confirm"]
    assert by_name["task_claim"]["inputSchema"]["required"] == ["task", "member", "confirm"]


# ================================================================ ③ 写门 confirm


def test_register_confirm_must_equal_manifest_id(batch: Path, write_on: None) -> None:
    """★ `task_register` 的 `confirm` 不等于 TOML 里的 `id` ⇒ **拒**，且**不落盘**。"""
    result = pool_mcp.call_tool(
        "task_register", {"manifest_text": MANIFEST, "confirm": "T-9"})
    assert result is not None and result["isError"] is True
    text = _text(result)
    assert "confirm" in text and "T-1" in text
    assert not (batch / "T-1.json").exists() and not (batch / "T-1.toml").exists()


def test_claim_confirm_must_equal_task(batch: Path, write_on: None) -> None:
    """★ `task_claim` 的 `confirm` 不等于任务号 ⇒ **拒**，且没留下任何申请。"""
    _seed(batch)
    result = pool_mcp.call_tool(
        "task_claim", {"task": "T-1", "member": "卡A", "claim": "success",
                       "evidence": "pytest", "files": ["tools/a/x.py"], "confirm": "T-2"})
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
        "task_claim", {"task": "T-1", "member": "卡A", "claim": "success",
                       "evidence": "pytest 3 passed", "files": ["docs/别的.md"],
                       "why": "越界", "confirm": "T-1"})
    assert result is not None and result["isError"] is True
    text = _text(result)
    assert "自己域外" in text and "docs/别的.md" in text      # 点名到文件
    assert "tools/a/*" in text                                # 并指出这张卡的域
    # 越界那次**没留下**申请、状态没动
    assert not (batch / "T-1.d" / "卡A.json").exists()
    assert task.read_json(batch / "T-1.json")["claims"] == {}


def test_claim_and_register_happy_path(batch: Path, write_on: None) -> None:
    """正路：MCP 注册 → 两张卡都交成功申请 → 集齐放行（停在 awaiting-commit）。"""
    reg = pool_mcp.call_tool("task_register", {"manifest_text": MANIFEST, "confirm": "T-1"})
    assert reg is not None and reg["isError"] is False
    assert (batch / "T-1.json").exists() and (batch / "T-1.toml").exists()
    assert _json_block(_text(reg))["declared"] == ["卡A", "卡B"]

    a = pool_mcp.call_tool("task_claim", {"task": "T-1", "member": "卡A", "claim": "success",
                                          "evidence": "pytest 3 passed",
                                          "files": ["tools/a/x.py"], "confirm": "T-1"})
    assert a is not None and a["isError"] is False
    assert _json_block(_text(a))["success"] == 1

    b = pool_mcp.call_tool("task_claim", {"task": "T-1", "member": "卡B", "claim": "success",
                                          "evidence": "ui 三张图都过",
                                          "files": ["ui/c.png"], "confirm": "T-1"})
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
    result = pool_mcp.call_tool(
        "task_register", {"manifest_path": str(man), "confirm": "T-1"})
    assert result is not None and result["isError"] is False
    assert (batch / "T-1.json").exists()


def test_register_bad_toml_is_refused(batch: Path, write_on: None) -> None:
    """预声明不是合法 TOML ⇒ 拒（不落盘）。"""
    result = pool_mcp.call_tool(
        "task_register", {"manifest_text": "id = , not toml {", "confirm": "T-1"})
    assert result is not None and result["isError"] is True
    assert "TOML" in _text(result)


# ================================================================ 真 stdio 端到端


def _talk(messages: list[dict[str, Any]], env_extra: dict[str, str | None]
          ) -> tuple[list[dict[str, Any]], bytes, str, int]:
    env: dict[str, str] = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "tools")
    env.update({k: v for k, v in env_extra.items() if v is not None})
    for key, value in env_extra.items():
        if value is None:
            env.pop(key, None)  # `None` = 显式把它从环境里拿掉（"不设 env"）
    proc = subprocess.Popen([sys.executable, "-c", SERVER_SNIPPET],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=env, cwd=str(ROOT))
    payload = b"".join((json.dumps(m, ensure_ascii=False) + "\n").encode("utf-8") for m in messages)
    out, err = proc.communicate(payload, timeout=180)
    replies = [json.loads(line.decode("utf-8")) for line in out.split(b"\n") if line.strip()]
    return replies, out, err.decode("utf-8", errors="replace"), proc.returncode


def test_real_stdio_task_tools_round_trip(batch: Path) -> None:
    """端到端（子进程，`POOL_MCP_WRITE=1`）：`tools/list` + 注册 + 成功申请 + 越界申请。"""
    replies, _raw, err, code = _talk(
        [
            _req(1, "tools/list"),
            _req(2, "tools/call", {"name": "task_register",
                                   "arguments": {"manifest_text": MANIFEST, "confirm": "T-1"}}),
            _req(3, "tools/call",
                 {"name": "task_claim",
                  "arguments": {"task": "T-1", "member": "卡A", "claim": "success",
                                "evidence": "pytest 3 passed", "files": ["tools/a/x.py"],
                                "confirm": "T-1"}}),
            _req(4, "tools/call",
                 {"name": "task_claim",
                  "arguments": {"task": "T-1", "member": "卡B", "claim": "success",
                                "evidence": "x", "files": ["docs/别的.md"], "confirm": "T-1"}}),
        ],
        {"TF_BATCH_DIR": str(batch), "POOL_MCP_WRITE": "1"},
    )
    assert code == 0, err
    assert [r["id"] for r in replies] == [1, 2, 3, 4], (replies, err)
    assert [t["name"] for t in replies[0]["result"]["tools"]] == [*READ_TOOL_NAMES,
                                                                  *WRITE_TOOL_NAMES]
    assert _json_block(replies[1]["result"]["content"][0]["text"])["registered"] is True
    assert _json_block(replies[2]["result"]["content"][0]["text"])["success"] == 1
    oob = replies[3]["result"]
    assert oob["isError"] is True
    assert "自己域外" in oob["content"][0]["text"]


def test_real_stdio_without_env_hides_task_writes(batch: Path) -> None:
    """端到端（不设 env）：`tools/list` 里**没有**那两个任务写工具。"""
    replies, _raw, err, code = _talk([_req(1, "tools/list")],
                                     {"TF_BATCH_DIR": str(batch), "POOL_MCP_WRITE": None})
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
    args: dict[str, Any] = {"task": "T-1", "member": "卡A", "claim": "success",
                            "evidence": "pytest 3 passed", "files": ["tools/a/x.py"],
                            "why": "自证", "confirm": "T-1"}
    args.update(over)
    return args


def test_claim_runs_in_a_subprocess_not_inprocess(batch: Path, write_on: None,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_claim_subprocess_nonzero_exit_is_surfaced(batch: Path, write_on: None,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_claim_subprocess_timeout_is_not_success(batch: Path, write_on: None,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
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
    return ("id = \"T-SLOW\"\nwhy = \"慢门禁自证\"\n"
            f"gate_cmd = {gate}\non_complete = [\"gate\", \"draft\"]\n\n"
            "[[member]]\nid = \"卡A\"\nlayer = \"门禁层\"\nwhat = \"慢门禁\"\n"
            "paths = [\"tools/a/*\"]\n")


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
    proc = subprocess.Popen([sys.executable, "-c", SERVER_SNIPPET],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=env, cwd=str(ROOT))
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
        _send(_req(1, "tools/call", {"name": "task_claim",
                                     "arguments": {"task": "T-SLOW", "member": "卡A",
                                                   "claim": "success", "evidence": "自证",
                                                   "files": ["tools/a/x.py"],
                                                   "confirm": "T-SLOW"}}))
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


def test_claim_timeout_carries_away_the_grandchild(batch: Path, write_on: None,
                                                   monkeypatch: pytest.MonkeyPatch,
                                                   tmp_path: Path) -> None:
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
        encoding="utf-8", newline="\n")
    monkeypatch.setattr(pool_mcp, "_claim_argv",
                        lambda *a, **k: [sys.executable, str(stub), str(pidfile)])
    monkeypatch.setattr(pool_mcp, "CLAIM_TIMEOUT_SECONDS", 3)

    psutil = pytest.importorskip("psutil")
    text, data, is_error = pool_mcp.tool_task_claim(_claim_args())
    grandchild = int(pidfile.read_text(encoding="utf-8").strip())
    try:
        assert is_error is True and "超时" in text, text
        gone = _wait_until(lambda: not psutil.pid_exists(grandchild), timeout=15.0)
        assert gone, f"孙进程 pid {grandchild} 仍在 —— 整棵没被带走（本卡要治的孤儿门禁）\n{text}"
    finally:
        with contextlib.suppress(Exception):      # 红的时候自己收尸，别留睡眠子进程
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


def test_claim_kill_failure_is_reported_not_swallowed(batch: Path, write_on: None,
                                                      monkeypatch: pytest.MonkeyPatch,
                                                      tmp_path: Path) -> None:
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
    """④ 工具清单没变：没 env = **10**（全只读）；`POOL_MCP_WRITE=1` = **14**。

    ★ 卡 201（T-G303）：加了第 10 个只读工具 `quota_status`（额度按钟表算，只读）⇒
      9/13 → 10/14。**没人放松判据** —— 只是把新工具如实计进来。
    """
    monkeypatch.delenv("POOL_MCP_WRITE", raising=False)
    ten = pool_mcp.handle(_req(1, "tools/list"))["result"]["tools"]
    assert len(ten) == 10, [t["name"] for t in ten]
    assert all(t["annotations"]["readOnlyHint"] is True for t in ten), ten

    monkeypatch.setenv("POOL_MCP_WRITE", "1")
    fourteen = pool_mcp.handle(_req(1, "tools/list"))["result"]["tools"]
    assert len(fourteen) == 14, [t["name"] for t in fourteen]
