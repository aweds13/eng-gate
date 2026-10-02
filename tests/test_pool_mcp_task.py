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

★ 一律把 `TF_BATCH_DIR` 指到临时目录 —— 一个字节都不写进真的 `gates/diag/batch/`。
★ 导入口径照既有测试：把 `tools/` 挂上 `sys.path` 再 `import pool_mcp` / `pool.task`。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
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
                   "pool_models"]
READ_TASK_NAMES = ["task_list", "task_status", "task_pool"]
READ_TOOL_NAMES = [*READ_POOL_NAMES, *READ_TASK_NAMES]
WRITE_TOOL_NAMES = ["pool_dispatch", "pool_cancel", "task_register", "task_claim"]

SERVER_SNIPPET = "import sys; from pool_mcp import serve; raise SystemExit(serve(sys.argv[1:]))"

#: 一份合法的预声明：审美层 + 后端各一张卡，域互不相交。
MANIFEST = """\
id = "T-1"
why = "审美层 + 后端一次收口"
gate_cmd = "exit 0"
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
    """有 env ⇒ 9 只读 + 4 写；只读的 `readOnlyHint` 仍 true；任务写工具的 annotations 逐字。"""
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
