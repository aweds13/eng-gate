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

★ 台账号 T-G113（卡 025，口径 B）：续跑日志**一行一轮、同卡各轮相邻** —— 不拿 ctime 当
「第几轮」（Windows 上 ctime 是创建时间、复制/覆盖会重置），轮次看文件名里的后缀（`r2`/`r3`），
行里带 `round` 字段给「第 N 轮」标识用。行模型不变（不跨轮合并/累加）。

★ 台账号 T-G123（卡 030）：整体行序**最新在前** —— 组（同树 + 同卡）按组内最后一次活动的
mtime **降序**（刚动过的卡在最上面，用户不用往下翻）；同卡各轮**轮次新的在前**（r2 在第 1 轮
上面，与整体同一个「新在前」方向）；等值行再按（树名, 卡号）定稳定次序。

★ 台账号 T-G144（卡 052）：**状态口径 —— 没有判决的日志不许说「可能卡死」**。直连 CLI 跑的
日志（如 022.r2）既无判决文件也无派活器心跳，旧口径把「日志很久没动」渲染成
「静默 N 分钟（可能卡死）」并永久挂着 —— 把"我不知道它怎么了"说成了"它卡死了"。
新终态 **「已停（无判决）」**：没有判决 + 没有**在更新**的心跳 + 静默超过阈值 → 如实说
"我看不到它的判决"，不下"卡死"的结论；「可能卡死」只允许在有**在更新**的心跳
（= 本该在跑）时用。★ 046 的成果（账本排除 / 非 UTF-8 容错 / 行序）一条不许弄回去。

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


def test_stopped_no_verdict_no_heartbeat(tmp_path: Path) -> None:
    """★ T-G144 钉子①：没有判决 + 没有在更新的心跳 + 静默超过阈值 → 「已停（无判决）」。

    直连 CLI 跑的日志（真数据 022.r2：静默 242.6 分钟、无心跳、无判决）旧口径渲染成
    「静默 N 分钟（可能卡死）」并永久挂着。★ 状态字符串里不许出现「可能卡死」，
    副文案要能让人看懂"这不是失败，是我看不到它的判决"。
    """
    _card(tmp_path, "022.r2", age=600)
    row = wb_dash.card_state(tmp_path)[0]
    assert row["state"] == "已停（无判决）"
    assert "可能卡死" not in row["state"]
    assert row["color"] == "quiet"                       # 不是失败，不下结论
    assert "没有判决文件" in row["note"]


def test_fresh_heartbeat_still_running_never_stopped(tmp_path: Path) -> None:
    """★ T-G144 钉子②：有心跳且**在更新** → 不许判「已停」（防一刀切把旧的都判成已停）。

    - 日志也新 → 「在跑」（原口径不变）；
    - 日志静默 600 秒但心跳 mtime 是现在 → 派活器活着在盯 = 本该在跑 →
      「静默…（可能卡死）」—— **不是**「已停（无判决）」；
    - 心跳文件存在但早停了（mtime 600 秒前）→ 没有「在更新」的证据 → 「已停（无判决）」。
    """
    log1 = _card(tmp_path, "049", age=5)
    hb1 = log1.with_suffix(".heartbeat.txt")
    hb1.write_text("[心跳] 每 2 分钟一行", encoding="utf-8")
    log2 = _card(tmp_path, "050", age=600)
    hb2 = log2.with_suffix(".heartbeat.txt")
    hb2.write_text("[心跳] 每 2 分钟一行", encoding="utf-8")     # mtime = 现在 = 在更新
    log3 = _card(tmp_path, "051", age=600)
    hb3 = log3.with_suffix(".heartbeat.txt")
    hb3.write_text("[心跳] 早就停了", encoding="utf-8")
    then = time.time() - 600
    os.utime(hb3, (then, then))
    rows = {r["card"]: r for r in wb_dash.card_state(tmp_path)}
    assert rows["049"]["state"] == "在跑"
    assert "已停" not in rows["050"]["state"]
    assert "可能卡死" in rows["050"]["state"]
    assert rows["051"]["state"] == "已停（无判决）"


def test_state_finished_by_verdict_file(tmp_path: Path) -> None:
    """有判决文件 → 收工·结束（哪怕日志刚动过、哪怕静默很久）。"""
    log = _card(tmp_path, "004", age=600)
    log.with_suffix(".verdict.txt").write_text("收工\n理由：门禁全绿", encoding="utf-8")
    row = wb_dash.card_state(tmp_path)[0]
    assert row["state"] == "收工·结束"
    assert row["color"] == "done"
    assert row["note"] == ""                             # ★ T-G144：收工行没有副文案


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
    """60 是"安静"边界；超阈值后按**心跳**分：没有在更新的心跳 → 已停（无判决）（T-G144）。"""
    assert wb_dash._state(59.9, False)[0] == "在跑"
    assert wb_dash._state(60.0, False)[0] == "安静"
    assert wb_dash._state(479.9, False)[0] == "安静"
    assert wb_dash._state(480.0, False)[0] == "已停（无判决）"
    # 本次阈值可注入（有在飞时就上抬到 1800）—— 边界跟着它走
    assert wb_dash._state(1799.0, False, threshold=1800.0)[0] == "安静"
    assert wb_dash._state(1800.0, False, threshold=1800.0)[0] == "已停（无判决）"
    # ★ T-G144：有「在更新」的心跳 = 本该在跑 → 才允许说「可能卡死」
    assert wb_dash._state(1800.0, False, threshold=1800.0,
                          heartbeat=True)[0].startswith("静默")


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
    """★ 保守口径：调用没带 `__timestamp` → 算不出耗时 → 阈值就是底线 480 秒（不放大）；
    没有心跳 → 超阈值就是「已停（无判决）」（T-G144），不再说「可能卡死」。"""
    _card(tmp_path, "008", age=600, lines=[
        _event(type="assistant", message={"id": "m1", "content": [
            {"type": "tool_use", "id": "t1", "name": "Bash",
             "input": {"command": "python -X utf8 scripts/run_gates.py"}}]}),
    ])
    row = wb_dash.card_state(tmp_path)[0]
    assert row["state"] == "已停（无判决）"
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
                  "inflight", "threshold_min",      # ★ T-G97 新增两字段（只加不改）
                  "round",                          # ★ T-G113 新增（只加不改）：续跑第几轮
                  "note"):                          # ★ T-G144 新增（只加不改）：已停副文案
        assert field in card


def test_no_cards_gives_empty_table_not_crash(tmp_path: Path) -> None:
    """一条 wb-*.jsonl 都没有（比如刚开工）→ 空表，不许崩。"""
    assert wb_dash.card_state(tmp_path) == []
    assert wb_dash.api_state(tmp_path)["cards"] == []


# -------------------------------------- 续跑分组排序 + 第 N 轮（T-G113，口径 B）


def test_newest_activity_group_first_and_rounds_new_on_top(tmp_path: Path) -> None:
    """★ 本卡要点（T-G123）：整体行序 = **最新活动在前**，同卡各轮相邻、轮次新的在前。

    故意按 005 → 004.r3 → 004 → 004.r2 的顺序**创建**文件（与创建序无关，mtime 用
    `os.utime` 钉死）：004 组的最新活动（r3，5 秒前）比 005（600 秒前）新 → 004 整组
    在上面，组内 r3/r2/第 1 轮；旧的 (卡号, 轮次) 升序口径会排成 004/004.r2/004.r3/005 → 红。
    """
    _card(tmp_path, "005", age=600)
    _card(tmp_path, "004.r3", age=5)
    _card(tmp_path, "004", age=60)
    _card(tmp_path, "004.r2", age=30)
    rows = wb_dash.card_state(tmp_path)
    assert [r["card"] for r in rows] == ["004.r3", "004.r2", "004", "005"]
    assert [r["round"] for r in rows] == [3, 2, 1, 1]


def test_newest_card_on_top_overall(tmp_path: Path) -> None:
    """用户要的那条：刚跑完的卡在最上面，不用往下翻。旧口径（按卡号升序）001 在前 → 红。"""
    _card(tmp_path, "001", age=900)
    _card(tmp_path, "024", age=10)
    rows = wb_dash.card_state(tmp_path)
    assert [r["card"] for r in rows] == ["024", "001"]


def test_equal_mtime_is_stable_by_tree_then_card(tmp_path: Path) -> None:
    """★ 排序要稳：mtime 真正相等（这里用 `os.utime` 钉成同一秒）→ 按（树名, 卡号）定次序，
    连续两次求值结果一致，刷新不许跳。"""
    log_b = _card(tmp_path, "010", age=30)
    log_a = _card(tmp_path, "002", age=30)
    same = time.time() - 30
    for log in (log_a, log_b):
        os.utime(log, (same, same))
    first = [r["card"] for r in wb_dash.card_state(tmp_path)]
    second = [r["card"] for r in wb_dash.card_state(tmp_path)]
    assert first == second == ["002", "010"]


def test_round_suffix_sorted_numerically_not_lexically(tmp_path: Path) -> None:
    """同卡各轮按**数字**降序（轮次新的在前）：r10 要在 r2 上面 ——
    按字符串排 'r2' > 'r10' → 那种写法这条红。"""
    _card(tmp_path, "007.r10")
    _card(tmp_path, "007.r2")
    rows = wb_dash.card_state(tmp_path)
    assert [r["card"] for r in rows] == ["007.r10", "007.r2"]
    assert [r["round"] for r in rows] == [10, 2]


def test_round_defaults_to_one_and_unparsed_suffix_is_first_round(tmp_path: Path) -> None:
    """无后缀 = 第 1 轮；形如 `.rx` 的怪后缀**不**当轮次解析（保守：整个当卡号、第 1 轮）。"""
    _card(tmp_path, "008")
    _card(tmp_path, "009.rx")
    rows = {r["card"]: r for r in wb_dash.card_state(tmp_path)}
    assert rows["008"]["round"] == 1
    assert rows["009.rx"]["round"] == 1


def test_same_card_number_in_different_trees_stays_separate(tmp_path: Path) -> None:
    """★ 跨树的**同号卡不是同一张卡**（T-G93 立标识的原因）：分组只在**同一棵树内**发生。

    主树 004 有两轮（r2 刚动过、第 1 轮较旧）、`.wt/004` 里另有一张 004（更早没动）——
    主树的两轮挨着在最上面（轮次新的在前），worktree 那张带 `@.wt/004` 标识、自己一轮，
    绝不与主树的合并/插进去。
    """
    _card(tmp_path, "004.r2", age=5)
    _card(tmp_path, "004", age=60)
    _card(tmp_path, "004", tree=".wt/004", age=300)
    rows = wb_dash.card_state(tmp_path)
    assert [r["card"] for r in rows] == ["004.r2", "004", "004@.wt/004"]
    assert [r["round"] for r in rows] == [2, 1, 1]
    assert [r["tree"] for r in rows] == ["", "", ".wt/004"]


# --------------------------- 用量账本不是卡 + 日志非 UTF-8/NUL 容错（T-G137，卡 046）


def test_usage_ledger_is_not_a_card(tmp_path: Path) -> None:
    """★ 用量账本 `wb-usage.jsonl` 不是卡 —— discover_logs 只许有真卡的两轮，一条 usage 都不许有。

    派活器（T-G114）每棵树落一份 gates/diag/wb-usage.jsonl（只有 token 计数、没有事件流），
    `wb-*.jsonl` 通配把它当一张叫 usage 的卡 → 永远「静默/可能卡死」（9 棵树 9 行幻影，
    用户 2026-09-26 就是这么被吓到的）。★ 账本不改名，面板适配账本。
    """
    _card(tmp_path, "042")
    _card(tmp_path, "042.r2")
    usage = tmp_path / "gates" / "diag" / "wb-usage.jsonl"
    usage.write_text('{"tokens_in": 1, "tokens_out": 2}\n', encoding="utf-8")
    then = time.time() - 600
    os.utime(usage, (then, then))
    cards = [card for _t, card, _p in wb_dash.discover_logs(tmp_path)]
    assert cards == ["042.r2", "042"]          # 轮次新的在前（030 口径照旧）
    assert not any(c.startswith("usage") for c in cards)
    assert wb_dash.is_card_log("wb-042.jsonl")
    assert wb_dash.is_card_log("wb-042.r2.jsonl")
    assert not wb_dash.is_card_log("wb-usage.jsonl")


def test_utf16_log_is_unparseable_never_stalled(tmp_path: Path) -> None:
    """★ UTF-16LE（PowerShell `*>` 重定向写出的那种）→ 不抛异常；整份解不出 →
    如实标「日志不可解析」，**不许**显示成「? 非 JSON 行：\\x00」、也**不许**判成「可能卡死」。
    """
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    log = diag / "wb-901.jsonl"
    log.write_bytes('{"type":"system","subtype":"init"}\n'.encode("utf-16-le"))
    then = time.time() - 600
    os.utime(log, (then, then))
    row = wb_dash.card_state(tmp_path)[0]
    assert row["state"] == "日志不可解析"
    assert "卡死" not in row["state"]
    assert "\\x00" not in row["last"]


def test_bad_line_is_skipped_good_lines_still_parsed(tmp_path: Path) -> None:
    """★ 混进一条坏行（NUL / 非 UTF-8 字节）→ **跳过那一条**，好行照常解析 ——
    不能因为一行垃圾把整张卡说成「说不清」。
    """
    good1 = _line({"type": "assistant", "message": {"id": "m1", "content": []}})
    good2 = _line({"type": "system", "subtype": "init", "model": "glm-5.3-flash"})
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    log = diag / "wb-902.jsonl"
    log.write_bytes(
        good1.encode("utf-8") + b"\n"
        + b'\x00\xff\xfe garbage \x00\n'
        + good2.encode("utf-8") + b"\n")
    row = wb_dash.card_state(tmp_path)[0]
    assert row["turns"] == 1                              # 好行的回合还在
    assert row["model"] == "glm-5.3-flash"                # 好行的 init 还在
    assert "\\x00" not in row["last"]                     # 坏行不进时间线
    assert "非 JSON 行" not in row["last"]


def test_utf8_log_parsing_unchanged(tmp_path: Path) -> None:
    """★ 既有行为不许变：真 UTF-8 log（哪怕带空行）的解析、状态判定与从前完全一致。"""
    _card(tmp_path, "043", age=600, lines=[
        _event(type="system", subtype="init", model="deepseek-v4.1-flash"),
        "",
        _event(type="result", subtype="success", result="做完了"),
    ])
    row = wb_dash.card_state(tmp_path)[0]
    assert row["state"] == "收工·结束"
    assert row["final"] == "做完了"
    assert row["model"] == "deepseek-v4.1-flash"
