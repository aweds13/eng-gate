r"""工作台接进会话内：MCP 只读工具 `workbench_board`（卡 213 · T-G325）的钉子。

为什么值当测：用户 2026-10-13 的令是"**不要让我切来切去**"。`workbench_board` 把卡 207 的
`tools/pipeline_view.py`（六块读数）接成 MCP 工具，让我/用户在会话里**直接问**。它一旦出错，
错的不是"报个错"而是**会话里读到一个假板子**：把"没读到读数"读成"板子是空的"、
把 `null + 说明` 洗成空对象。所以四条判据都要机器形态：

| 钉子 | 判什么 |
|---|---|
| ① 在清单且只读 | `workbench_board` 在 `tools/list` 里，`readOnlyHint=True`，**不在**任何写名单里 |
| ② 非零如实报错 | `pipeline_view.py` 非零 ⇒ `is_error=True`、`reading=None`，**不许**给"空板子" |
| ③ null 不洗 | 某块是 `null` + 说明 ⇒ 传出来的也是 `null` + 说明（**原样透传**） |
| ④ 幂等 | 同一份 fixture 连跑两次，机器可读块**逐字相同** |

★ 反例（②③）都走**真子进程**：② 把 `pool_mcp.PIPELINE_VIEW` 换成一个"故意非零"的桩脚本；
③ 用**真** `pipeline_view.py` 指向一个缺来源的临时 root。
★ 导入口径照既有测试：把 `tools/` 挂上 `sys.path` 再 `import pool_mcp`。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pool_mcp  # noqa: E402 —— tools/ 已在 sys.path 上

#: 机器可读块的唯一标记（**写死**，与 `tools/pool_mcp.py::JSON_MARKER` 逐字一致）。
JSON_MARKER = "--- tf-json ---"

#: 一份合法的 backlog（给幂等/正例用；两张卡）。
BACKLOG = """\
[base]
reviewed = "deadbeef"

[[cards]]
id = "213"
task = "T-G325"
title = "工作台接进会话内"
tree = ".wt/wbboard"
spec = "复盘/卡/卡213-工作台接进会话内.md"
files = ["tools/pool_mcp.py"]
depends = []
risk = "mid"
status = "pending"

[[cards]]
id = "207"
task = "T-G316"
title = "一份读数"
tree = ""
spec = "复盘/卡/卡207-一份读数.md"
files = ["tools/pipeline_view.py"]
depends = []
risk = "mid"
status = "done"
"""

#: 桩脚本：**故意非零退出**（反例②用）。
FAKE_FAIL = "import sys\nsys.stderr.write('boom-from-fake\\n')\nsys.exit(3)\n"
#: 桩脚本：**睡很久**（反例②的"超时"分支用）。
FAKE_SLEEP = "import time\ntime.sleep(30)\n"


# ---------------------------------------------------------------- 报文小工具（照既有测试）


def _req(mid: int | None, method: str, params: dict | None = None) -> dict:
    message: dict = {"jsonrpc": "2.0", "method": method}
    if mid is not None:
        message["id"] = mid
    if params is not None:
        message["params"] = params
    return message


def _call(name: str, arguments: dict | None = None) -> dict:
    return _req(1, "tools/call", {"name": name, "arguments": arguments or {}})


def _json_block(text: str) -> dict:
    """取出**唯一标记之后**那一行单行紧凑 JSON（与既有读端同口径）。"""
    assert JSON_MARKER in text, f"回复里没有机器可读块标记 {JSON_MARKER!r}"
    after = text.split(JSON_MARKER, 1)[1]
    line = next((ln for ln in after.splitlines() if ln.lstrip().startswith("{")), None)
    assert line is not None, "唯一标记之后没有机器可读块"
    return json.loads(line)


def _fake_script(tmp_path: Path, body: str) -> Path:
    """把一段源码摊成一个可执行的桩脚本，返回它的路径。"""
    script = tmp_path / "fake_pipeline_view.py"
    script.write_text(body, encoding="utf-8")
    return script


@pytest.fixture()
def board_root(tmp_path: Path) -> Path:
    """一份能读出东西的临时 root（有 backlog、无门禁/租约）。"""
    (tmp_path / "docs").mkdir(parents=True)
    (tmp_path / "docs" / "workbacklog.toml").write_text(BACKLOG, encoding="utf-8")
    return tmp_path


# ================================================================ ① 在清单且只读


def test_workbench_board_is_listed_and_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """`workbench_board` 在清单里、`readOnlyHint=True`、**不在**任何写工具名单里。"""
    monkeypatch.delenv("POOL_MCP_WRITE", raising=False)
    tools = pool_mcp.handle(_req(1, "tools/list"))["result"]["tools"]
    by_name = {t["name"]: t for t in tools}
    assert "workbench_board" in by_name
    assert by_name["workbench_board"]["annotations"]["readOnlyHint"] is True
    assert by_name["workbench_board"]["inputSchema"]["additionalProperties"] is False
    # ★ 它绝不能是写工具
    assert "workbench_board" not in pool_mcp.WRITE_NAMES
    assert "workbench_board" not in pool_mcp.TASK_WRITE_NAMES
    # 即便开了写 env，它仍只读，且排在号池只读那一串里
    monkeypatch.setenv("POOL_MCP_WRITE", "1")
    names = [t["name"] for t in pool_mcp.handle(_req(1, "tools/list"))["result"]["tools"]]
    assert "workbench_board" in names
    assert names.index("workbench_board") < names.index("pool_dispatch")


def test_workbench_board_success_returns_machine_block(board_root: Path) -> None:
    """成功路径：`call_tool` 回一段带唯一标记的机器块，且读数是那六块的结构化读数。"""
    result = pool_mcp.call_tool("workbench_board", {}, root=board_root)
    assert result is not None and result["isError"] is False
    block = _json_block(result["content"][0]["text"])
    assert block["exit_code"] == 0
    assert block["section"] is None
    reading = block["reading"]
    assert isinstance(reading, dict)
    assert [c["id"] for c in reading["cards"]] == ["213", "207"]


# ================================================================ ② 非零 / 超时 ⇒ 如实报错


def test_nonzero_pipeline_view_reports_error_not_empty_board(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 反例②：`pipeline_view.py` 返回非零 ⇒ `workbench_board` **如实报错**。

    ★ 命门：**不许**返回一个"看起来正常"的空板子 —— `is_error=True`、`reading=None`、
    退出码原样带出、stderr 原文带出。
    """
    monkeypatch.setattr(pool_mcp, "PIPELINE_VIEW", _fake_script(tmp_path, FAKE_FAIL))
    text, data, is_error = pool_mcp.tool_workbench_board({}, root=tmp_path)
    assert is_error is True
    assert data["reading"] is None                      # ★ 不是空对象，是 None
    assert data["exit_code"] == 3                       # 退出码原样
    assert "boom-from-fake" in data["stderr"]           # stderr 原文带出
    assert "没能拿到读数" in text
    # 机器块也得如实：reading 是 null（用 call_tool 再验一遍）
    result = pool_mcp.call_tool("workbench_board", {}, root=tmp_path)
    assert result is not None and result["isError"] is True
    block = _json_block(result["content"][0]["text"])
    assert block["reading"] is None and block["exit_code"] == 3


def test_timeout_reports_error_not_empty_board(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 反例②的超时分支：桩脚本睡过 `WORKBENCH_TIMEOUT` ⇒ 如实报"超时"，绝不静默返空。"""
    monkeypatch.setattr(pool_mcp, "PIPELINE_VIEW", _fake_script(tmp_path, FAKE_SLEEP))
    monkeypatch.setattr(pool_mcp, "WORKBENCH_TIMEOUT", 0.5)
    text, data, is_error = pool_mcp.tool_workbench_board({}, root=tmp_path)
    assert is_error is True
    assert data["reading"] is None
    assert data["exit_code"] is None                    # 超时 ⇒ 退出码 None
    assert "超时" in text


def test_bad_section_is_rejected(tmp_path: Path) -> None:
    """不认识的 `section` ⇒ 报错并列出六块（不静默当成"全给"）。"""
    text, data, is_error = pool_mcp.tool_workbench_board({"section": "no-such"}, root=tmp_path)
    assert is_error is True and data["reading"] is None
    for sec in pool_mcp.WORKBENCH_SECTIONS:
        assert sec in text


# ================================================================ ③ null 不洗（原样透传）


def test_null_block_is_passed_through_with_note(tmp_path: Path) -> None:
    """★ 反例③：某块是 `null` + 说明 ⇒ 传出来的**也**是 `null` + 说明（**不许**洗掉）。

    空 root 里没有 `docs/workbacklog.toml` / `gates/last.json` ⇒ `cards` / `gates` 必是
    `null` + `_note`；`workbench_board` 必须**原样**透传（既留 `null`，也留说明）。
    """
    text, data, is_error = pool_mcp.tool_workbench_board({}, root=tmp_path)
    assert is_error is False
    reading = data["reading"]
    assert reading["cards"] is None
    assert "workbacklog" in reading["cards_note"]       # 说明在，且点到了来源
    assert reading["gates"] is None
    assert "last.json" in reading["gates_note"]
    # 人话里也得如实说"没有"
    assert "没有" in text


def test_section_filter_keeps_only_that_block(board_root: Path) -> None:
    """`section` 给了 ⇒ 只有那一块（连它的 `_*` 说明键一起，别的块一个不漏）。"""
    text, data, is_error = pool_mcp.tool_workbench_board({"section": "gates"}, root=board_root)
    assert is_error is False
    reading = data["reading"]
    # 只有 gates 那一族（块 + 它的 `_*` 说明键，如 `gates_note`）
    assert all(k == "gates" or k.startswith("gates_") for k in reading), sorted(reading)
    assert "gates" in reading
    assert data["section"] == "gates"
    # 别的块一个都不许混进来
    for other in ("cards", "verdicts", "leases", "fences", "worktrees"):
        assert other not in reading


# ================================================================ ④ 幂等


def test_same_fixture_twice_is_byte_identical(board_root: Path) -> None:
    """同一份 fixture 连跑两次 ⇒ 机器可读块**逐字相同**（不许写时间戳/随机序）。"""
    first = pool_mcp.call_tool("workbench_board", {}, root=board_root)
    second = pool_mcp.call_tool("workbench_board", {}, root=board_root)
    assert first is not None and second is not None
    assert _json_block(first["content"][0]["text"]) == _json_block(second["content"][0]["text"])
