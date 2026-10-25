r"""号池 MCP **写面**（`tools/pool_mcp.py` 的 `pool_dispatch` / `pool_cancel` · 卡 111 · T-G208）。

为什么值当测：这两个工具**真会动手** —— 一个起工人、一个杀进程。错的不是"报个错"，
而是**派到别人的树上** / **杀错别人的 pid** / **租约占着不放**。所以每条判据都要机器形态：

| 判据 | 判什么 |
|---|---|
| ① 授权 | 没 `POOL_MCP_WRITE=1` 只列 11 个；写调用还要 `arguments.confirm == 卡号` |
| ② 清单形状 | 有 env 时 16 个；十二个 `readOnlyHint` 仍 true；写工具的 `annotations` |
| ③ 干跑四咬 | 树冲突 / 域相交 / 日志已存在 / 锁在跑 → **不派活** + 逐条原因 |
| ④ 真派活用桩 | argv 逐字（有 `--detach --execute --cwd`；无 `--force/--allow` 等）+ 先占后起 |
| ⑤ 回滚 | 起不来 ⇒ 租约被释放（`list_reservations` 验） |
| ⑥ cancel 身份 | 映像名不对 ⇒ **拒绝动手**，且**没有**调 taskkill |

★ 一律用 `TF_POOL_REGISTRY` 指临时目录、backlog 也从临时 root 读 —— **一个字节都不写进真的
`gates/diag/`**（`cancel.txt` 也落在临时 root 下）。
"""

from __future__ import annotations

import io
import json
import locale
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pool_mcp  # noqa: E402 —— tools/ 已在 sys.path 上
import wb_dispatch  # noqa: E402
from pool import registry  # noqa: E402

READ_TOOL_NAMES = [
    "pool_plan", "job_list", "job_status", "job_result", "lock_status", "pool_models",
    # ★ 卡 201（T-G303）：第 10 个只读工具 —— 额度状态按钟表算
    "quota_status",
    "account_status",  # ★ 卡 E45（T-AG496）：账号账本，不探测、不联网
    # ★ 卡 213（T-G325）：第 11 个只读工具 —— 工作台读数（调 pipeline_view）
    "workbench_board",
    "task_list", "task_status", "task_pool",
]
WRITE_TOOL_NAMES = ["pool_dispatch", "pool_cancel", "task_register", "task_claim"]

BACKLOG = """\
[base]
reviewed = "deadbeef"

[[cards]]
id = "111"
task = "T-G208"
title = "号池写面②"
tree = ".wt/poolmcp2"
spec = "gates/diag/卡111-号池写面②MCP写工具.md"
files = [
  "tools/pool_mcp.py",
  "tests/test_pool_mcp_write.py",
]
depends = []
risk = "high"
status = "pending"
"""


# ---------------------------------------------------------------- 夹具 / 小工具


@pytest.fixture()
def reg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """登记文件指到临时目录（绝不动真的 `gates/diag/pool-registry.json`）。"""
    path = tmp_path / "pool-registry.json"
    monkeypatch.setenv("TF_POOL_REGISTRY", str(path))
    return path


@pytest.fixture()
def worktree(tmp_path: Path) -> Path:
    """临时 root：写一份只含卡 111 的 backlog + 空 `gates/diag/`。"""
    (tmp_path / "docs").mkdir(parents=True)
    (tmp_path / "docs" / "workbacklog.toml").write_text(BACKLOG, encoding="utf-8")
    (tmp_path / "gates" / "diag").mkdir(parents=True)
    return tmp_path


@pytest.fixture()
def write_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POOL_MCP_WRITE", "1")


@pytest.fixture()
def quiet_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "read_lock_body", lambda *a, **k: "")


@pytest.fixture()
def no_spawn(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """起工人那一步换桩：**记录**并返回一个拿不到 pid 的结果（证明"不派活"）。"""
    calls: list[list[str]] = []

    def fake(argv: list[str], root: Path) -> tuple[int, str, str]:
        calls.append(list(argv))
        raise AssertionError("这四种情况都不许派活 —— 起工人不该被调用")

    monkeypatch.setattr(pool_mcp, "_spawn_worker", fake)
    return calls


def _text(result: dict[str, Any]) -> str:
    return result["content"][0]["text"]


def _json_block(text: str) -> dict[str, Any]:
    body = text.split("```json", 1)[1].split("```", 1)[0]
    return json.loads(body)


def _dispatch_args(**over: Any) -> dict[str, Any]:
    args: dict[str, Any] = {"card": "111", "tree": ".wt/poolmcp2", "confirm": "111"}
    args.update(over)
    return args


# ================================================================ ① 授权门


def test_write_tools_are_hidden_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """没 `POOL_MCP_WRITE=1` → 只列十二个只读工具，写工具当"没有这个工具"。"""
    monkeypatch.delenv("POOL_MCP_WRITE", raising=False)
    names = [t["name"] for t in pool_mcp.handle(_req(1, "tools/list"))["result"]["tools"]]
    assert names == READ_TOOL_NAMES
    reply = pool_mcp.handle(_call("pool_dispatch", {}))
    assert reply["error"]["code"] == pool_mcp.JSONRPC_INVALID_PARAMS


def test_write_tools_listed_and_shaped_with_env(write_on: None) -> None:
    """有 env → 16 个；十二个 `readOnlyHint: true`；两个号池写工具的 annotations 逐字。"""
    tools = pool_mcp.handle(_req(1, "tools/list"))["result"]["tools"]
    assert [t["name"] for t in tools] == [*READ_TOOL_NAMES, *WRITE_TOOL_NAMES]
    by_name = {t["name"]: t for t in tools}
    for name in READ_TOOL_NAMES:
        assert by_name[name]["annotations"]["readOnlyHint"] is True, name
    dispatch = by_name["pool_dispatch"]["annotations"]
    cancel = by_name["pool_cancel"]["annotations"]
    assert dispatch["readOnlyHint"] is False
    assert dispatch["destructiveHint"] is False
    assert dispatch["idempotentHint"] is False
    assert cancel["readOnlyHint"] is False
    assert cancel["destructiveHint"] is True
    assert cancel["idempotentHint"] is True
    assert by_name["pool_dispatch"]["inputSchema"]["required"] == ["card", "tree"]
    assert by_name["pool_cancel"]["inputSchema"]["required"] == ["card"]


def test_confirm_must_equal_card(write_on: None, reg: Path, worktree: Path,
                                 no_spawn: list[list[str]]) -> None:
    """`arguments.confirm` 不等于卡号 → 拒绝（防手滑），且**不派活**。"""
    result = pool_mcp.call_tool("pool_dispatch", _dispatch_args(confirm="999"), root=worktree)
    assert result is not None and result["isError"] is True
    assert "confirm" in _text(result)
    assert no_spawn == []


def test_initialize_instructions_describe_write_authorization(write_on: None) -> None:
    """两条授权规矩都要写进 `initialize` 的 instructions（人话）。"""
    text = pool_mcp.handle(_req(1, "initialize", {}))["result"]["instructions"]
    assert "POOL_MCP_WRITE" in text
    assert "confirm" in text


# ================================================================ ③ 干跑四咬


def test_dry_run_bites_on_tree_conflict(write_on: None, reg: Path, worktree: Path,
                                        quiet_lock: None, no_spawn: list[list[str]]) -> None:
    registry.reserve("900", tree=".wt/poolmcp2", files=["docs/other.md"])
    result = pool_mcp.call_tool("pool_dispatch", _dispatch_args(), root=worktree)
    assert result is not None and result["isError"] is True
    assert "树被占" in _text(result)
    assert no_spawn == []


def test_dry_run_bites_on_domain_intersection(write_on: None, reg: Path, worktree: Path,
                                              quiet_lock: None,
                                              no_spawn: list[list[str]]) -> None:
    registry.reserve("900", tree=".wt/other", files=["tools/pool_mcp.py"])
    result = pool_mcp.call_tool("pool_dispatch", _dispatch_args(), root=worktree)
    assert result is not None and result["isError"] is True
    assert "冲突域相交" in _text(result)
    assert no_spawn == []


def test_dry_run_bites_on_existing_log(write_on: None, reg: Path, worktree: Path,
                                       quiet_lock: None, no_spawn: list[list[str]]) -> None:
    (worktree / "gates" / "diag" / "wb-111.jsonl").write_text("{}\n", encoding="utf-8")
    result = pool_mcp.call_tool("pool_dispatch", _dispatch_args(), root=worktree)
    assert result is not None and result["isError"] is True
    assert "不许覆盖" in _text(result)
    assert no_spawn == []


def test_dry_run_bites_on_running_gate_lock(write_on: None, reg: Path, worktree: Path,
                                            monkeypatch: pytest.MonkeyPatch,
                                            no_spawn: list[list[str]]) -> None:
    body = ("[锁] 段 base=9034 文件=gate.lock: card=111 pid=999 "
            "起于 2026-10-01 23:37:00（已 12s / 租约剩 10788s；租约内） cwd=D:/eng")
    monkeypatch.setattr(registry, "read_lock_body", lambda *a, **k: body)
    result = pool_mcp.call_tool("pool_dispatch", _dispatch_args(), root=worktree)
    assert result is not None and result["isError"] is True
    assert "门禁还在跑" in _text(result)
    assert no_spawn == []


def test_unknown_card_in_backlog_is_refused(write_on: None, reg: Path, worktree: Path,
                                            quiet_lock: None,
                                            no_spawn: list[list[str]]) -> None:
    """backlog 里没有这张卡 ⇒ 没有冲突域 ⇒ 拒（**别猜空域**）。"""
    result = pool_mcp.call_tool("pool_dispatch", _dispatch_args(card="999", confirm="999"),
                                root=worktree)
    assert result is not None and result["isError"] is True
    assert "冲突域" in _text(result)
    assert no_spawn == []


# ================================================================ ④⑤ 真派活（桩）/ 回滚


def test_dispatch_argv_is_pinned_and_reserves_first(
        write_on: None, reg: Path, worktree: Path, quiet_lock: None,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """桩验 argv 逐字 + 租约**先占后起**。"""
    seen: dict[str, Any] = {}

    def fake(argv: list[str], root: Path) -> tuple[int, str, str]:
        seen["argv"] = list(argv)
        seen["live_before_spawn"] = [r["card"] for r in registry.list_reservations()]
        return 0, "[OK ] 前置检查全过 → 扔出去单独跑（pid 4242），我的窗口关了它照样跑\n", ""

    monkeypatch.setattr(pool_mcp, "_spawn_worker", fake)
    result = pool_mcp.call_tool("pool_dispatch", _dispatch_args(), root=worktree)
    assert result is not None and result["isError"] is False
    argv = seen["argv"]
    joined = " ".join(argv)
    assert "--detach" in argv and "--execute" in argv and "--lean" in argv
    # ★ 卡 125：MCP 已先 reserve ⇒ 必须带 --already-reserved（否则撞 wb_dispatch 的 tree_guard）
    assert "--already-reserved" in argv
    assert "--cwd" in argv
    cwd = argv[argv.index("--cwd") + 1]
    assert Path(cwd).is_absolute()
    assert cwd == str(registry.main_tree_root() / ".wt" / "poolmcp2")
    assert argv[argv.index("--spec") + 1] == "gates/diag/卡111-号池写面②MCP写工具.md"
    assert argv[argv.index("--model") + 1] == wb_dispatch.DEFAULT_MODEL
    for danger in ("--force", "--allow", "--resume", "--no-preflight"):
        assert danger not in argv, f"不许透传 {danger}：{joined}"
    # 先占后起：起工人那一刻，本卡租约已在登记里
    assert seen["live_before_spawn"] == ["111"]
    data = _json_block(_text(result))
    assert data["pid"] == 4242
    assert data["log"].endswith("wb-111.jsonl")
    # pid 落进登记，供 pool_cancel 认身份
    entry = [r for r in registry.load() if r["card"] == "111"][0]
    assert entry["pid"] == 4242


def test_dispatch_rolls_back_when_worker_fails(
        write_on: None, reg: Path, worktree: Path, quiet_lock: None,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """起不来 ⇒ 释放刚占的租约，如实报错。"""
    def boom(argv: list[str], root: Path) -> tuple[int, str, str]:
        raise OSError("起不来：模拟失败")

    monkeypatch.setattr(pool_mcp, "_spawn_worker", boom)
    result = pool_mcp.call_tool("pool_dispatch", _dispatch_args(), root=worktree)
    assert result is not None and result["isError"] is True
    assert registry.list_reservations() == []           # 租约被释放


def test_dispatch_rolls_back_when_preflight_fails(
        write_on: None, reg: Path, worktree: Path, quiet_lock: None,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """wb_dispatch 前置检查没过（退 2、无 pid）⇒ 回滚 + 把原文带回来。"""
    def fake(argv: list[str], root: Path) -> tuple[int, str, str]:
        return 2, "", "[FAIL] 不派活 —— 前置检查没过：\n  · 内存不够\n"

    monkeypatch.setattr(pool_mcp, "_spawn_worker", fake)
    result = pool_mcp.call_tool("pool_dispatch", _dispatch_args(), root=worktree)
    assert result is not None and result["isError"] is True
    assert "内存不够" in _text(result)
    assert registry.list_reservations() == []


def test_invalid_model_is_refused(write_on: None, reg: Path, worktree: Path,
                                  no_spawn: list[list[str]]) -> None:
    result = pool_mcp.call_tool("pool_dispatch", _dispatch_args(model="gpt-99"),
                                root=worktree)
    assert result is not None and result["isError"] is True
    assert "未授权模型" in _text(result)
    assert no_spawn == []


# ================================================================ ⑥ cancel 身份核对


def _seed_lease(card: str, pid: int, worktree: Path) -> None:
    registry.reserve(card, tree=".wt/poolmcp2", files=[])
    pool_mcp._record_pid(card, pid)


def test_cancel_refuses_when_image_is_not_a_worker(
        write_on: None, reg: Path, worktree: Path, quiet_lock: None,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """映像名不是 node.exe/python.exe ⇒ **拒绝动手**，且**没有**调用 taskkill。"""
    _seed_lease("111", 4242, worktree)
    kills: list[int] = []
    monkeypatch.setattr(pool_mcp, "_image_name", lambda pid: "chrome.exe")
    monkeypatch.setattr(pool_mcp, "_kill", lambda pid: (kills.append(pid), (True, ""))[1])
    result = pool_mcp.call_tool("pool_cancel", {"card": "111", "confirm": "111",
                                                "reason": "手滑取消"}, root=worktree)
    assert result is not None and result["isError"] is True
    assert "拒绝动手" in _text(result)
    assert kills == []
    assert "tasklist" in _text(result) and "taskkill" in _text(result)   # 人工怎么做
    # 拒绝后租约还在（没动任何东西）
    assert [r["card"] for r in registry.list_reservations()] == ["111"]


def test_cancel_refuses_when_no_lease(write_on: None, reg: Path, worktree: Path,
                                      quiet_lock: None) -> None:
    result = pool_mcp.call_tool("pool_cancel", {"card": "111", "confirm": "111"},
                                root=worktree)
    assert result is not None and result["isError"] is True
    assert "租约" in _text(result)


def test_cancel_kills_and_releases_and_writes_note(
        write_on: None, reg: Path, worktree: Path, quiet_lock: None,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """身份对 → 杀、写 `wb-111.cancel.txt`、释放租约。"""
    _seed_lease("111", 4242, worktree)
    killed: list[int] = []
    monkeypatch.setattr(pool_mcp, "_image_name", lambda pid: "node.exe")
    monkeypatch.setattr(pool_mcp, "_kill", lambda pid: (killed.append(pid), (True, "已结束"))[1])
    result = pool_mcp.call_tool("pool_cancel", {"card": "111", "confirm": "111",
                                                "reason": "用户叫停"}, root=worktree)
    assert result is not None and result["isError"] is False
    assert killed == [4242]
    assert registry.list_reservations() == []
    note = worktree / "gates" / "diag" / "wb-111.cancel.txt"
    assert note.exists()
    body = note.read_text(encoding="utf-8")
    assert "111" in body and "4242" in body and "用户叫停" in body


# ---------------------------------------------------------------- 协议小工具


def _req(mid: int | None, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if mid is not None:
        message["id"] = mid
    if params is not None:
        message["params"] = params
    return message


def _call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return _req(1, "tools/call", {"name": name, "arguments": arguments})


def test_serve_without_env_still_lists_six(monkeypatch: pytest.MonkeyPatch) -> None:
    """真 stdio 循环：没 env 时 tools/list 仍是 6 个（只读面行为不变）。"""
    monkeypatch.delenv("POOL_MCP_WRITE", raising=False)
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_req(1, "tools/list")) + "\n"))
    monkeypatch.setattr(sys, "stdout", out)
    assert pool_mcp.serve([]) == 0
    reply = json.loads(out.getvalue().splitlines()[0])
    assert [t["name"] for t in reply["result"]["tools"]] == READ_TOOL_NAMES


# ================================================================ ⑦ 证据编码（卡 113 · T-G210）


def _expected_console_encoding() -> str:
    """测试侧独立算一遍"该用哪个编码"——**不**调 `pool_mcp` 的那个函数（否则是循环自证）。"""
    return (locale.getencoding() if hasattr(locale, "getencoding")
            else locale.getpreferredencoding(False)) or "utf-8"


def test_kill_and_image_decode_with_console_encoding(monkeypatch: pytest.MonkeyPatch) -> None:
    """结构性：`_kill` / `_image_name` 给 `subprocess` 的 `encoding` 是**系统区域编码**
    （★ 动态比，换台机器也成立，不是写死 cp936），且 `errors` 仍是 `"replace"`。"""
    seen: list[dict[str, Any]] = []

    class _Done:
        returncode = 0
        stdout = '"x.exe","4242","Console","1","1 K"\n'
        stderr = ""

    def fake_run(argv: list[str], **kwargs: Any) -> _Done:
        seen.append({"argv": list(argv), **kwargs})
        return _Done()

    monkeypatch.setattr(pool_mcp.subprocess, "run", fake_run)
    pool_mcp._image_name(4242)
    pool_mcp._kill(4242)

    assert [call["argv"][0] for call in seen] == ["tasklist", "taskkill"]
    expected = _expected_console_encoding()
    for call in seen:
        assert call["encoding"] == expected, call["argv"]
        assert call["errors"] == "replace", call["argv"]


def test_kill_reads_system_encoded_output_as_human_text(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """行为性：`taskkill` 吐的**系统编码**回话要能读成人话（不出替换字符 `\\ufffd`）；
    坏字节只许被 `replace` 掉，**绝不许抛**（掐进程这条路不能被解码带崩）。"""
    system_enc = _expected_console_encoding()
    human = "成功: 已终止 PID 1（映像 python.exe）"
    good_bytes = human.encode(system_enc)

    class _Done:
        returncode = 0
        stderr = ""

        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    def fake_run(argv: list[str], **kwargs: Any) -> _Done:
        # 模拟真子进程：按**调用方给的 encoding/errors** 去解系统编码的原始字节。
        return _Done(good_bytes.decode(kwargs["encoding"], errors=kwargs["errors"]))

    monkeypatch.setattr(pool_mcp.subprocess, "run", fake_run)
    ok, detail = pool_mcp._kill(4242)
    assert ok is True
    assert "\ufffd" not in detail          # 编码对 → 没有人话被替换成 U+FFFD（utf-8 老写法会中招）
    assert "成功" in detail and "已终止" in detail

    def fake_bad(argv: list[str], **kwargs: Any) -> _Done:
        # 连系统编码都解不开的坏字节 → 只能 replace 掉，不许抛。
        return _Done(b"\xff\xfe\xff".decode(kwargs["encoding"], errors=kwargs["errors"]))

    monkeypatch.setattr(pool_mcp.subprocess, "run", fake_bad)
    ok2, detail2 = pool_mcp._kill(4242)    # 没抛出来 = 过
    assert isinstance(detail2, str)
    assert "\ufffd" in detail2             # 坏字节被 replace 掉
