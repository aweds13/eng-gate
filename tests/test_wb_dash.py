"""`tools/wb_dash.py`（工人状态面板，台账号 T-G93）的测试 —— 给这块表上护栏。

为什么要有：这块表的唯一任务是把"工人到底在不在动"判对。四档判错的代价很实在 ——
半夜以为工人在跑（其实早收工了），或反过来把早已收工的卡误报成"可能卡死"
（第一版就误报了卡 002）。所以**四档各钉一条**，外加最容易漏的那条：
**没有判决文件、但日志里有 `result` 事件，也算收工**。

★ 只造假状态文件（`tmp_path`），**不起服务、不连网** —— 真机那一步是手工证据（卡 §5），不进测试。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_dash  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上


def _event(**kwargs: object) -> str:
    return json.dumps(kwargs, ensure_ascii=False)


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
    """60 ≤ 静默 < 480 秒 → 安静（可能在长思考，也可能要出事）。"""
    _card(tmp_path, "004", age=120)
    row = wb_dash.card_state(tmp_path)[0]
    assert row["state"] == "安静"
    assert row["color"] == "quiet"


def test_state_stalled(tmp_path: Path) -> None:
    """静默 ≥ 480 秒 → 静默 N 分钟（可能卡死）。"""
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
    """60 / 480 是硬边界（与派活器看门狗同一口径），两边都要留在正确的档里。"""
    assert wb_dash._state(59.9, False)[0] == "在跑"
    assert wb_dash._state(60.0, False)[0] == "安静"
    assert wb_dash._state(479.9, False)[0] == "安静"
    assert wb_dash._state(480.0, False)[0].startswith("静默")


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
                  "model", "session", "heartbeat", "verdict", "last", "final", "size_kb"):
        assert field in card


def test_no_cards_gives_empty_table_not_crash(tmp_path: Path) -> None:
    """一条 wb-*.jsonl 都没有（比如刚开工）→ 空表，不许崩。"""
    assert wb_dash.card_state(tmp_path) == []
    assert wb_dash.api_state(tmp_path)["cards"] == []
