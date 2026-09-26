"""`tools/wb_dash.py`（工人状态面板，台账号 T-G93）的测试 —— 给这块表上护栏。

为什么要有：这块表的唯一任务是把"工人到底在不在动"判对。四档判错的代价很实在 ——
半夜以为工人在跑（其实早收工了），或反过来把早已收工的卡误报成"可能卡死"
（第一版就误报了卡 002）。所以**四档各钉一条**，外加最容易漏的那条：
**没有判决文件、但日志里有 `result` 事件，也算收工**。

★ 台账号 T-G97（卡 008）：判卡死的阈值**不再是硬写的 480 秒** —— 有工具在飞时静默是**预期**的
（全量门禁 ~4 分钟、冷缓存 worktree 里 `ui_flow` 十几分钟），旧写法会把这种正常的长调用误标成
「静默 N 分钟（可能卡死）」。面板现在**复用派活器**（`wb_dispatch`）的
`inflight_tool()` / `tool_durations()` / `stall_threshold_seconds()` —— 本节后四条就是钉这个，
**不许在面板里写第二份口径**（判据必须是派活器的：换掉它，面板结果要跟着变）。

★ 只造假状态文件（`tmp_path`），**不起服务、不连网** —— 真机那一步是手工证据（卡 §5），不进测试。
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_dash  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上


def _event(**kwargs: object) -> str:
    return json.dumps(kwargs, ensure_ascii=False)


def _line(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _stamp(seconds_ago: float) -> str:
    """派活器看门狗认的那个 `__timestamp`（ISO-8601 UTC）—— `seconds_ago` 秒之前。"""
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


def _tool_use(tid: str, *, seconds_ago: float, name: str = "Bash",
              command: str = "python -X utf8 scripts/run_gates.py") -> str:
    """一次 `tool_use`（带时间戳）—— 没配对应的 `tool_result` 时就是"在飞"。"""
    return _line({"type": "assistant", "__timestamp": _stamp(seconds_ago),
                  "message": {"id": f"m-{tid}", "content": [
                      {"type": "tool_use", "id": tid, "name": name,
                       "input": {"command": command}}]}})


def _tool_result(tid: str, *, seconds_ago: float) -> str:
    """一次 `tool_result`（带时间戳）—— 与同名 `tool_use` 配对后就不算在飞。"""
    return _line({"type": "user", "__timestamp": _stamp(seconds_ago),
                  "message": {"content": [
                      {"type": "tool_result", "tool_use_id": tid, "content": "ok"}]}})


def _card(root: Path, card: str = "004", *, age: float = 5.0, tree: str = "",
          lines: list[str] | None = None) -> Path:
    """造一张卡的状态文件。`age` = 日志"静默"了几秒（决定哪一档）。"""
    diag = (root / tree / "gates" / "diag") if tree else (root / "gates" / "diag")
    diag.mkdir(parents=True, exist_ok=True)
    body = lines if lines is not None else [_event(
        type="system", subtype="init", model="deepseek-v4.1-flash")]
    log = diag / f"wb-{card}.jsonl"
    log.write_text("\n".join(body) + "\n", encoding="utf-8")
    then = time.time() - age
    os.utime(log, (then, then))
    return log


# ------------------------------------------------------------------ 四档判定


def test_state_running(tmp_path: Path) -> None:
    """静默 < 60 秒 → 在跑。"""
    _card(tmp_path, "004", age=5)
    row = wb_dash.card_state(tmp_path)[0]
    assert row["state"] == "在跑"
    assert row["color"] == "run"


def test_state_quiet(tmp_path: Path) -> None:
    """60 ≤ 静默 < 本次阈值 → 安静（可能在长思考，也可能要出事）。"""
    _card(tmp_path, "004", age=120)
    row = wb_dash.card_state(tmp_path)[0]
    assert row["state"] == "安静"
    assert row["color"] == "quiet"


def test_state_stalled(tmp_path: Path) -> None:
    """静默 ≥ 本次阈值（这里没有在飞、没有历史耗时 → 底线 480 秒）→ 可能卡死。"""
    _card(tmp_path, "004", age=600)
    row = wb_dash.card_state(tmp_path)[0]
    assert row["state"] == "静默 10.0 分钟（可能卡死）"
    assert row["color"] == "stall"


def test_state_finished_by_verdict_file(tmp_path: Path) -> None:
    """有判决文件 → 收工·结束（哪怕日志刚动过、哪怕静默很久）。"""
    log = _card(tmp_path, "004", age=600)
    log.with_suffix(".verdict.txt").write_text("收工\n理由：门禁全绿", encoding="utf-8")
    row = wb_dash.card_state(tmp_path)[0]
    assert row["state"] == "收工·结束"
    assert row["color"] == "done"


def test_result_event_means_finished_without_verdict(tmp_path: Path) -> None:
    """★ 老卡没有判决文件 —— 日志里出现 `result` 事件也要算收工。

    少了这一条，早已收工的卡会被误报成"静默 N 分钟（可能卡死）"（第一版就误报了卡 002）。
    """
    _card(tmp_path, "002", age=600,
          lines=[_event(type="result", subtype="success", result="做完了")])
    row = wb_dash.card_state(tmp_path)[0]
    assert row["state"] == "收工·结束"
    assert row["color"] == "done"
    assert row["final"] == "做完了"


def test_state_boundaries() -> None:
    """60 是"安静"边界；卡死边界 = **本次阈值**（默认 = 派活器底线 480）。"""
    assert wb_dash._state(59.9, False)[0] == "在跑"
    assert wb_dash._state(60.0, False)[0] == "安静"
    assert wb_dash._state(479.9, False)[0] == "安静"
    assert wb_dash._state(480.0, False)[0].startswith("静默")
    # 本次阈值可注入（有在飞时就上抬到 1800）—— 边界跟着它走
    assert wb_dash._state(1799.0, False, threshold=1800.0)[0] == "安静"
    assert wb_dash._state(1800.0, False, threshold=1800.0)[0].startswith("静默")


# ------------------------------------------------- 卡死阈值复用派活器（T-G97）


def test_inflight_tool_raises_threshold_instead_of_reporting_stall(tmp_path: Path) -> None:
    """★ 本卡的整个要点：**有工具在飞时静默是预期的**，不许再把长命令误标成"可能卡死"。

    600 秒静默 + 一个 600 秒前发出、还没回话的 `Bash`（跑门禁那种）：
    旧实现（硬写 480）→「静默 10.0 分钟（可能卡死）」；新实现 → 底线上抬到 30 分钟 →「安静」。
    """
    _card(tmp_path, "008", age=600, lines=[
        _event(type="system", subtype="init", model="deepseek-v4.1-flash"),
        _tool_use("t1", seconds_ago=600),
    ])
    row = wb_dash.card_state(tmp_path)[0]
    assert row["state"] == "安静"
    assert row["color"] == "quiet"
    assert row["threshold_min"] == 30.0
    assert row["inflight"].startswith("在跑：")
    assert "已跑" in row["inflight"]


def test_threshold_adapts_to_longest_completed_call(tmp_path: Path) -> None:
    """没有在飞，但历史最长一次已完成调用 400 秒 → 阈值 = max(480, 2.5×400)=1000 秒。

    600 秒静默 < 1000 →「安静」，而不是「可能卡死」（旧实现硬写 480 会误报）。
    """
    _card(tmp_path, "008", age=600, lines=[
        _event(type="system", subtype="init", model="deepseek-v4.1-flash"),
        _tool_use("t1", seconds_ago=800),
        _tool_result("t1", seconds_ago=400),        # 这一段跑了 400 秒
    ])
    row = wb_dash.card_state(tmp_path)[0]
    assert row["state"] == "安静"
    assert row["threshold_min"] == round(1000 / 60, 1)          # 16.7 分
    assert row["inflight"] == ""                                # 配过对了 → 没有在飞


def test_no_timestamp_falls_back_to_baseline(tmp_path: Path) -> None:
    """★ 保守口径：调用没带 `__timestamp` → 算不出耗时 → 阈值就是底线 480 秒（不放大）。"""
    _card(tmp_path, "008", age=600, lines=[
        _event(type="assistant", message={"id": "m1", "content": [
            {"type": "tool_use", "id": "t1", "name": "Bash",
             "input": {"command": "python -X utf8 scripts/run_gates.py"}}]}),
    ])
    row = wb_dash.card_state(tmp_path)[0]
    assert row["state"] == "静默 10.0 分钟（可能卡死）"
    assert row["threshold_min"] == 8.0                          # 480 / 60
    assert row["inflight"] == ""


def test_threshold_comes_from_dispatch_not_a_second_copy(
        tmp_path: Path, monkeypatch: object) -> None:
    """★ 口径必须是**派活器的**：把派活器那个函数换掉，面板结果要跟着变。

    否则说明面板自己抄了第二份公式（本项目一路在消的东西）—— 忘了 480 之外还有个 1800 就会漂。
    """
    _card(tmp_path, "008", age=600)
    monkeypatch.setattr(wb_dash.wb_dispatch, "stall_threshold_seconds",    # type: ignore[attr-defined]
                        lambda **kwargs: 9999.0)
    row = wb_dash.card_state(tmp_path)[0]
    assert row["threshold_min"] == round(9999.0 / 60, 1)
    assert row["state"] == "安静"


def test_dash_reuses_dispatch_functions_by_source() -> None:
    """源码级：面板必须真的**调**派活器那三个判据（不是抄一份常数/公式过来）。"""
    src = (ROOT / "tools" / "wb_dash.py").read_text(encoding="utf-8")
    assert "wb_dispatch.inflight_tool" in src
    assert "wb_dispatch.tool_durations" in src
    assert "wb_dispatch.stall_threshold_seconds" in src


# ------------------------------------------------------------------ 多卡 + 多树


def test_multi_card_multi_tree_are_discovered(tmp_path: Path) -> None:
    """主树的卡 + worktree 里的卡都要被发现，且标出各自来自哪棵树。"""
    _card(tmp_path, "001")
    _card(tmp_path, "004", tree=".wt/004")
    by = {r["card"]: r for r in wb_dash.card_state(tmp_path)}
    assert set(by) == {"001", "004@.wt/004"}
    assert by["001"]["tree"] == ""
    assert by["004@.wt/004"]["tree"] == ".wt/004"


def test_turns_dedupe_by_assistant_message_id(tmp_path: Path) -> None:
    """回合数按 `assistant` 事件的 `message.id` 去重（与派活器同一口径）。"""
    _card(tmp_path, "004", lines=[
        _event(type="assistant", message={"id": "m1", "content": []}),
        _event(type="assistant", message={"id": "m1", "content": []}),   # 同一条 → 不算两回合
        _event(type="assistant", message={"id": "m2", "content": []}),
    ])
    assert wb_dash.card_state(tmp_path)[0]["turns"] == 2


def test_summary_reuses_shared_parser(tmp_path: Path) -> None:
    """时间线/摘要走 `wb_status.parse_events` —— 工具调用次数不能是第二套口径。"""
    _card(tmp_path, "004", lines=[
        _event(type="assistant", message={"id": "m1", "content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "git status"}}]}),
    ])
    row = wb_dash.card_state(tmp_path)[0]
    assert row["tool_calls"] == 1
    assert row["tools"] == {"Bash": 1}


# ------------------------------------------------------------------ /api/state


def test_api_state_json_shape(tmp_path: Path) -> None:
    """`/api/state` 的正文结构（不起服务，直接调那个抽出来的函数）。"""
    _card(tmp_path, "004")
    data = wb_dash.api_state(tmp_path)
    assert set(data) == {"now", "cards"}
    assert isinstance(data["now"], str)
    card = data["cards"][0]
    for field in ("card", "tree", "log", "state", "color", "elapsed_min", "silent_s",
                  "events", "turns", "tool_calls", "tools", "errors", "files_total",
                  "model", "session", "heartbeat", "verdict", "last", "final", "size_kb",
                  "inflight", "threshold_min"):     # ★ T-G97 新增两字段（只加不改）
        assert field in card


def test_no_cards_gives_empty_table_not_crash(tmp_path: Path) -> None:
    """一条 wb-*.jsonl 都没有（比如刚开工）→ 空表，不许崩。"""
    assert wb_dash.card_state(tmp_path) == []
    assert wb_dash.api_state(tmp_path)["cards"] == []
