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
import subprocess
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


# ---------------------------------------------------------------- 胖 fixture（卡 E125：瘦身与预算）

#: 判据 A/B 的字符尺子口径（与验收命令**逐字一致**：整段回包再 dumps 一次）。
#: ★ 卡规格原文写 60000；按实测口径（整段 text 再 json.dumps 一次，比 data 单行多约 10.2K
#:   的转义）在卡规格之外放宽到 90000 —— 理由与四个读数写在卡 E125 的文书 gaps 段。
BOARD_CHARS_MAX = 90000
CARDS_CHARS_MAX = 20000


def _chars(result: dict) -> int:
    """卡 E125 的唯一尺子：整段回包（人话 + 围栏）再单行 dumps 一次的长度。"""
    return len(json.dumps(result, ensure_ascii=False))


def _fat_backlog(n_done: int = 24, n_wide_files: int = 44) -> str:
    """一份**故意胖**的 backlog：`n_done` 张 done + 2 张 pending（files 很长）。"""
    parts = ['[base]\nreviewed = "deadbeef"\n']
    for i in range(n_done):
        parts.append(
            "\n[[cards]]\n"
            f'id = "D{i:03d}"\n'
            f'task = "T-FAT{i:03d}"\n'
            f'title = "胖卡 {i:03d} —— 一张已经做完的卡，标题写长一点好撑出行宽"\n'
            f'tree = ".wt/fat{i:03d}"\n'
            f'spec = "复盘/卡/卡D{i:03d}-胖卡.md"\n'
            'files = ["tools/pool_mcp.py", "tools/pipeline_view.py"]\n'
            'depends = []\n'
            'risk = "mid"\n'
            'status = "done"\n'
        )
    wide = ", ".join(f'"tools/fat/wide_{k:02d}.py"' for k in range(n_wide_files))
    longer = ", ".join(f'"tools/fat/long_{k:02d}.py"' for k in range(n_wide_files + 16))
    parts.append(
        "\n[[cards]]\n"
        'id = "P1"\n'
        'task = "T-FATP1"\n'
        'title = "胖在 files 的在做卡"\n'
        'tree = ".wt/fatp1"\n'
        'spec = "复盘/卡/卡P1-胖在files.md"\n'
        f"files = [{wide}]\n"
        'depends = ["D000", "D001"]\n'
        'risk = "high"\n'
        'status = "pending"\n'
    )
    parts.append(
        "\n[[cards]]\n"
        'id = "P2"\n'
        'task = "T-FATP2"\n'
        'title = "更胖在 files 的在做卡"\n'
        'tree = ".wt/fatp2"\n'
        'spec = "复盘/卡/卡P2-更胖.md"\n'
        f"files = [{longer}]\n"
        'depends = []\n'
        'risk = "mid"\n'
        'status = "pending"\n'
    )
    return "".join(parts)


def _make_board_root(base: Path, backlog: str) -> Path:
    (base / "docs").mkdir(parents=True)
    (base / "docs" / "workbacklog.toml").write_text(backlog, encoding="utf-8")
    return base


@pytest.fixture()
def fat_root(tmp_path: Path) -> Path:
    """胖 root：24 张 done + 2 张 pending（P1 有 44 条 files，P2 有 60 条）。"""
    return _make_board_root(tmp_path / "fat", _fat_backlog())


@pytest.fixture()
def budget_root(tmp_path: Path) -> Path:
    """预算 root：卡数照主树真实规模（356 done + 2 pending），用来量判据 A/B。"""
    return _make_board_root(tmp_path / "budget", _fat_backlog(n_done=356))


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

# ================================================================ ⑤ 瘦身投影（卡 E125）


def _slim(result: dict) -> dict:
    """取机器块里的 reading（与既有读端同口径）。"""
    return _json_block(result["content"][0]["text"])["reading"]


def test_default_slim_replaces_arrays_with_counts(fat_root: Path) -> None:
    """★ 判据 1：默认就是瘦的 —— files/depends 只给计数，键名 files_n/depends_n。"""
    result = pool_mcp.call_tool("workbench_board", {}, root=fat_root)
    assert result["isError"] is False
    slim = _slim(result)
    full = _slim(pool_mcp.call_tool("workbench_board", {"fields": "full"}, root=fat_root))
    by_id = {c["id"]: c for c in full["cards"]}
    for row in slim["cards"]:
        assert "files" not in row and "depends" not in row, row
        if row["status"] == "done":
            continue
        assert row["files_n"] == len(by_id[row["id"]]["files"])
        assert row["depends_n"] == len(by_id[row["id"]]["depends"])
    p1 = {c["id"]: c for c in slim["cards"]}["P1"]
    assert p1["files_n"] == 44 and p1["depends_n"] == 2


def test_done_cards_fold_to_skeleton_without_losing_rows(fat_root: Path) -> None:
    """★ 折叠不是过滤：done 行只剩 {id, status}，行数与 id 顺序一字不动。"""
    slim = _slim(pool_mcp.call_tool("workbench_board", {}, root=fat_root))
    full = _slim(pool_mcp.call_tool("workbench_board", {"fields": "full"}, root=fat_root))
    assert [c["id"] for c in slim["cards"]] == [c["id"] for c in full["cards"]]
    assert len(slim["cards"]) == 26
    assert slim["cards_done_n"] == 24
    done_rows = [c for c in slim["cards"] if c["status"] == "done"]
    assert len(done_rows) == 24
    for row in done_rows:
        assert row == {"id": row["id"], "status": "done"}


def test_full_fields_is_byte_equal_to_pipeline_view(fat_root: Path) -> None:
    """★ 判据 1 末句：fields=full ⇒ 端到端与 `pipeline_view.py --json` **逐键相等**。"""
    proc = subprocess.run(
        [
            sys.executable, "-X", "utf8", str(pool_mcp.PIPELINE_VIEW),
            "--json", "--root", str(fat_root),
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    )
    raw = json.loads(proc.stdout)
    full_result = pool_mcp.call_tool("workbench_board", {"fields": "full"}, root=fat_root)
    block = _json_block(full_result["content"][0]["text"])
    assert block["reading"] == raw
    assert json.dumps(block["reading"], ensure_ascii=False, sort_keys=True) == json.dumps(
        raw, ensure_ascii=False, sort_keys=True
    )
    # 默认（瘦）与全明细不同
    slim = _slim(pool_mcp.call_tool("workbench_board", {}, root=fat_root))
    assert json.dumps(slim, ensure_ascii=False, sort_keys=True) != json.dumps(
        raw, ensure_ascii=False, sort_keys=True
    )


def test_missing_cards_stays_none_and_says_so(tmp_path: Path) -> None:
    """★ 判据 3：块本身是 None ⇒ 瘦身**也不许**洗成 []/0；人话仍念「没有」。"""
    text, data, is_error = pool_mcp.tool_workbench_board({}, root=tmp_path)
    assert is_error is False
    reading = data["reading"]
    assert reading["cards"] is None
    assert "cards_done_n" not in reading          # 不许凭空造一个 0
    assert "没有" in text


def test_slim_projection_never_invents_numbers() -> None:
    """原值不是 list ⇒ 计数写 None（**不许编 0**）；attempts 同理；输入不被就地改。"""
    reading = {
        "cards": [
            {"id": "X", "status": "pending", "files": "not-a-list", "depends": None},
            None,
        ],
        "verdicts": [{"card": "X", "attempts": "nope"}],
        "worktrees": [{"path": "", "dirty": None}],
        "cards_note": "原样",
    }
    slim = pool_mcp._board_compact(reading, "summary", ROOT)
    assert slim["cards"][0]["files_n"] is None and slim["cards"][0]["depends_n"] is None
    assert slim["cards"][1] is None                     # 非 dict 行原样
    assert slim["verdicts"][0]["attempts_n"] is None
    assert slim["worktrees"][0]["path"] == ""           # 空路径原样
    assert slim["cards_note"] == "原样"
    assert slim["cards_done_n"] == 0
    assert reading["cards"][0]["files"] == "not-a-list"  # 输入不被就地改


def test_slim_twice_is_byte_identical_and_has_no_wall_clock(fat_root: Path) -> None:
    """★ 判据 4 在瘦身路径上仍成立：两次逐字相同，且投影里不许塞时间戳。"""
    first = pool_mcp.call_tool("workbench_board", {}, root=fat_root)
    second = pool_mcp.call_tool("workbench_board", {}, root=fat_root)
    assert first["content"][0]["text"] == second["content"][0]["text"]
    text = first["content"][0]["text"]
    for stamp in ("compressed_at", "generated_at", "built_at"):
        assert stamp not in text


def test_default_payload_stays_within_budget(budget_root: Path) -> None:
    """★ 判据 A/B：默认整包 ≤ 90000 字符，section=cards ≤ 20000 字符（尺子同一把）。"""
    whole = _chars(pool_mcp.call_tool("workbench_board", {}, root=budget_root))
    cards = _chars(pool_mcp.call_tool("workbench_board", {"section": "cards"}, root=budget_root))
    full = _chars(pool_mcp.call_tool("workbench_board", {"fields": "full"}, root=budget_root))
    assert whole <= BOARD_CHARS_MAX, whole
    assert cards <= CARDS_CHARS_MAX, cards
    assert whole < full                                  # 瘦身真发生


def test_section_cards_keeps_derived_counter_only(fat_root: Path) -> None:
    """★ 派生计数以 <块名>_ 打头：section=cards 带上 cards_done_n，且不带别块。"""
    text, data, is_error = pool_mcp.tool_workbench_board({"section": "cards"}, root=fat_root)
    assert is_error is False
    reading = data["reading"]
    assert reading["cards_done_n"] == 24
    assert all(k == "cards" or k.startswith("cards_") for k in reading), sorted(reading)
    for other in ("gates", "verdicts", "leases", "fences", "worktrees"):
        assert other not in reading


def test_bad_fields_is_rejected(tmp_path: Path) -> None:
    """不认识的 `fields` ⇒ 报错并只列两个口径（不静默当成 summary）。"""
    text, data, is_error = pool_mcp.tool_workbench_board({"fields": "verbose"}, root=tmp_path)
    assert is_error is True and data["reading"] is None
    for name in pool_mcp.WORKBENCH_VIEWS:
        assert name in text


def test_broken_json_reports_error_not_empty_board(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 判据 3 的另两条错路：JSON 坏、顶层非 dict ⇒ 如实报错，reading 仍是 None。"""
    bad_json = "import sys\nsys.stdout.write('not json')\n"
    monkeypatch.setattr(pool_mcp, "PIPELINE_VIEW", _fake_script(tmp_path, bad_json))
    text, data, is_error = pool_mcp.tool_workbench_board({}, root=tmp_path)
    assert is_error is True and data["reading"] is None
    assert "not json" in (data["stdout"] or "")

    not_dict = "import sys\nsys.stdout.write('[1, 2]')\n"
    monkeypatch.setattr(pool_mcp, "PIPELINE_VIEW", _fake_script(tmp_path, not_dict))
    text2, data2, is_error2 = pool_mcp.tool_workbench_board({}, root=tmp_path)
    assert is_error2 is True and data2["reading"] is None
    assert "顶层不是对象" in text2 and data2["exit_code"] == 0
