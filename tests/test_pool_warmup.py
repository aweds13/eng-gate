"""A370 —— 窗口登记（判据 1 / 3 / 4 / 6）。

钉的是四件事：
  ① `window_of_row()` **两键缺一不可**，缺任一就 `None`（不许兜底 5 小时）；
  ② `register()` 是**唯一**写 `warm-window.json` 的地方，写盘走 tempfile + `os.replace`；
  ③ `window_running()` 三支顺序固定，判不出时**不许**默认「没在跑」；
  ④ 本模块的 import 面**零网络、零定时器**（扫 AST，不扫字符串）。

★ 导入口径：一律走包路径（`from tools.pool import warmup`），不往 `sys.path` 里塞东西。
"""

from __future__ import annotations

import ast
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tools.pool import warmup
from tools.pool.holds import Window

ROOT = Path(__file__).resolve().parent.parent
TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 11, 19, 12, 0, 0, tzinfo=TZ)


def _row(**extra) -> dict:
    """一条「像探测行 / 像账本 [account.quota]」的读数。"""
    row = {"resets_at": "2026-11-19T17:00:00+08:00", "span_s": 5 * 3600}
    row.update(extra)
    return row

# ---------------------------------------------------------------- 判据 1

def test_window_of_row_requires_both_keys():
    """只给 resets_at ⇒ None；只给 span_s ⇒ None；两个都给 ⇒ Window 字段逐一相等。"""
    only_reset = {"resets_at": "2026-11-19T17:00:00+08:00"}
    only_span = {"span_s": 5 * 3600}
    assert warmup.window_of_row(only_reset) is None
    assert warmup.window_of_row(only_span) is None

    both = warmup.window_of_row(_row(model="m1", used_percent=12.5, pool="p", family="f"))
    assert isinstance(both, Window)
    assert both.model == "m1"
    assert both.span_s == 5 * 3600
    assert both.used == 12.5
    assert both.resets_at == datetime(2026, 11, 19, 17, 0, 0, tzinfo=TZ)
    assert both.pool == "p"
    assert both.family == "f"


def test_window_of_row_never_defaults_the_span():
    """★ 硬边界：跨度只许来自读数（平台表 window_hours 折算），缺了就 None —— 不许 5 小时兜底。"""
    for bad in (0, -1, "18000", True, float("nan"), float("inf")):
        row = {"resets_at": "2026-11-19T17:00:00+08:00", "span_s": bad}
        assert warmup.window_of_row(row) is None
    for bad in ("", "not-a-time", None, 12):
        assert warmup.window_of_row({"resets_at": bad, "span_s": 3600}) is None


def test_window_of_row_ignores_non_numeric_used():
    """used_percent 不是数就当「没有读数」（不是 0，也不抛）——判据 3 靠它分三支。"""
    row = _row(used_percent="12.5")
    win = warmup.window_of_row(row)
    assert win is not None and win.used is None


def test_register_is_the_only_writer():
    """ast 扫 warmup.py（判据 1）：状态文件名字面量只许一处、os.replace 只许在 register() 里。"""
    src = Path(warmup.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    literal_hits = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value == "warm-window.json"
    ]
    assert len(literal_hits) == 1, "warm-window.json 的字面量只许有一处（STATE_REL 那一处）"

    replace_funcs = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Attribute)
                and inner.attr == "replace"
                and isinstance(inner.value, ast.Name)
                and inner.value.id == "os"
            ):
                replace_funcs.append(node.name)
    assert replace_funcs == ["register"], replace_funcs

# ---------------------------------------------------------------- 判据 3

def _window(**extra) -> Window:
    """未来的重置时刻 + 5 小时跨度 —— 判据 3 的底板（用上一面推不动再改）。"""
    base = dict(
        span_s=5 * 3600,
        resets_at=datetime(2026, 11, 19, 17, 0, 0, tzinfo=TZ),
    )
    base.update(extra)
    return Window(**base)


def test_window_running_false_when_reset_passed():
    """① 重置时刻已经过去 ⇒ (False, "reset")：窗口结束了。"""
    w = _window(resets_at=datetime(2026, 11, 19, 11, 0, 0, tzinfo=TZ))
    assert warmup.window_running(w, NOW) == (False, "reset")


def test_window_running_true_when_used_drops():
    """② 有 used 且比上次登记的回落 ⇒ (True, "usage")：回落 = 窗口重开。"""
    w = _window(used=10.0)
    assert warmup.window_running(w, NOW, prev_used=40.0) == (True, "usage")


def test_window_running_unknown_without_used():
    """③ 没有 used、也没有可比的登记时刻 ⇒ (None, "unknown") —— 不许默认「没在跑」。"""
    w = _window()
    assert warmup.window_running(w, NOW) == (None, "unknown")


def test_window_running_idle_when_nobody_used_it():
    """③ 的正面：没有 used，但 resets_at 晚于「上次跑到的时间」且此后无人用过 ⇒ (False, "idle")。"""
    w = _window()
    seen = datetime(2026, 11, 19, 9, 0, 0, tzinfo=TZ)
    assert warmup.window_running(w, NOW, last_seen=seen) == (False, "idle")


def test_reset_beats_usage_when_both_apply():
    """顺序钉：① 与 ② 同时成立时 **① 先赢**（重置时刻已过就轮不到「用量回落」说话）。"""
    w = _window(
        used=10.0,
        resets_at=datetime(2026, 11, 19, 11, 0, 0, tzinfo=TZ),
    )
    assert warmup.window_running(w, NOW, prev_used=40.0) == (False, "reset")


def test_window_running_never_returns_bare_true_without_used():
    """没有 used 时只有「有可比时刻」这一条能判；判不出必须是 None，不许凑一个 True/False。"""
    w = _window()
    running, reason = warmup.window_running(w, NOW)
    assert running is None
    assert reason == "unknown"

# ---------------------------------------------------------------- 判据 4

def test_same_epoch_same_day_is_idempotent(tmp_path):
    """同 (账号, 日期, 时刻) 调两次：列表长度仍 1、文件 mtime 不变（连 replace 都不调）。"""
    rows = [{"account": "a-1", "at": "09:00"}]
    path = warmup.register(rows, now=NOW, root=tmp_path)
    body1 = json.loads(path.read_text(encoding="utf-8"))
    assert body1 == {"a-1": {"2026-11-19": ["09:00"]}}

    # 把 mtime 打成一个好认的哨兵：真写过盘就必然变（比「两次 stat 恰好相等」硬 ——
    # Windows 上 os.utime 的浮点秒会掉精度，拿它回写会自己把自己比挂）。
    os.utime(path, ns=(1_000_000_000, 1_234_567_890))
    # 记「回写之后文件系统报的 mtime」而不是我们想设的那个数：NTFS 会把 ns 量化，
    # 拿预期值直接比是比文件系统，不是比「有没有写盘」。哨兵值在 1970 年，真写一次必变。
    sentinel = path.stat().st_mtime_ns
    again = warmup.register(rows, now=NOW, root=tmp_path)
    assert again == path
    body2 = json.loads(path.read_text(encoding="utf-8"))
    assert body2 == body1
    assert len(body2["a-1"]["2026-11-19"]) == 1
    assert path.stat().st_mtime_ns == sentinel


def test_next_day_same_epoch_is_due_again(tmp_path):
    """跨日重新可用：同一条 09:00 在第二天仍会被登记（不是「这账号今天已经 warm 过」）。"""
    rows = [{"account": "a-1", "at": "09:00"}]
    warmup.register(rows, now=NOW, root=tmp_path)
    tomorrow = NOW + timedelta(days=1)
    warmup.register(rows, now=tomorrow, root=tmp_path)
    body = json.loads((tmp_path / "gates/diag/warm-window.json").read_text(encoding="utf-8"))
    assert body == {
        "a-1": {"2026-11-19": ["09:00"], "2026-11-20": ["09:00"]},
    }


def test_register_keeps_times_sorted(tmp_path):
    """只记时刻：同一天登记 17:00 再 09:00 ⇒ 表里排好序（due() 的「下一个」靠它）。"""
    warmup.register([{"account": "a-1", "at": "17:00"}], now=NOW, root=tmp_path)
    warmup.register([{"account": "a-1", "at": "09:00"}], now=NOW, root=tmp_path)
    body = json.loads((tmp_path / "gates/diag/warm-window.json").read_text(encoding="utf-8"))
    assert body["a-1"]["2026-11-19"] == ["09:00", "17:00"]


def test_register_rejects_bad_at(tmp_path):
    """登记表里只许 HH:MM；写成别的东西当场抛，不写盘。"""
    with pytest.raises(warmup.WarmError):
        warmup.register([{"account": "a-1", "at": "9:00"}], now=NOW, root=tmp_path)
    assert not (tmp_path / "gates/diag/warm-window.json").exists()

# ---------------------------------------------------------------- due() 判词

def _acc(account="a-1", **quota) -> dict:
    """一个「像账本 [[account]]」的条目：窗口两键放 [account.quota]。"""
    return {"id": account, "quota": dict(quota)}


def test_due_unknown_without_window_keys(tmp_path):
    """账本里没有 resets_at / span_s ⇒ unknown，且 why 里点名「先跑 probe」。"""
    rows = warmup.due([_acc(unit="点")], ["12:00"], now=NOW, root=tmp_path)
    assert len(rows) == 1
    assert rows[0]["account"] == "a-1"
    assert rows[0]["ats"] == ["12:00"]
    assert rows[0]["verdict"] == "unknown"
    assert "probe" in rows[0]["why"]


def test_due_unknown_with_half_the_pair(tmp_path):
    """只带两键中的**一个** ⇒ 仍判不出（unknown）：不许给缺的那一半兜个默认值凑出判词。"""
    rows = warmup.due(
        [_acc(resets_at="2026-11-19T17:00:00+08:00")], ["12:00"], now=NOW, root=tmp_path
    )
    assert rows[0]["verdict"] == "unknown"
    assert rows[0]["why"]


def test_due_when_reset_passed(tmp_path):
    """重置时刻已过 ⇒ 窗口没在跑 ⇒ due，且 why 写出理由码 reset。"""
    acc = _acc(
        resets_at="2026-11-19T11:00:00+08:00",
        span_s=5 * 3600,
    )
    rows = warmup.due([acc], ["12:00"], now=NOW, root=tmp_path)
    assert rows[0]["verdict"] == "due"
    assert rows[0]["why"]
    assert "reset" in rows[0]["why"]


def test_due_unknown_when_window_cannot_be_judged(tmp_path):
    """有窗口两键但判不出在不在跑（没有 used、也没有登记时刻）⇒ 仍是 unknown，不是 due。"""
    acc = _acc(
        resets_at="2026-11-19T17:00:00+08:00",
        span_s=5 * 3600,
    )
    rows = warmup.due([acc], ["12:00"], now=NOW, root=tmp_path)
    assert rows[0]["verdict"] == "unknown"
    assert rows[0]["why"]


def test_due_not_due_before_the_slot(tmp_path):
    """还没到点 ⇒ not-due（不是 unknown、也不是 due）。"""
    acc = _acc(resets_at="2026-11-19T11:00:00+08:00", span_s=5 * 3600)
    rows = warmup.due([acc], ["18:00"], now=NOW, root=tmp_path)
    assert rows[0]["verdict"] == "not-due"
    assert "18:00" in rows[0]["why"]


def test_due_not_due_after_register(tmp_path):
    """同 (账号, 日期, 时刻) 登记过 ⇒ due() 不再列它（判据 4 的另一半）。"""
    acc = _acc(resets_at="2026-11-19T11:00:00+08:00", span_s=5 * 3600)
    warmup.register([{"account": "a-1", "at": "12:00"}], now=NOW, root=tmp_path)
    rows = warmup.due([acc], ["12:00"], now=NOW, root=tmp_path)
    assert rows[0]["verdict"] == "not-due"


def test_due_unknown_without_slots(tmp_path):
    """没给 --at ⇒ 不知道按哪个点判 ⇒ unknown（不许自己编一个点）。"""
    acc = _acc(resets_at="2026-11-19T11:00:00+08:00", span_s=5 * 3600)
    rows = warmup.due([acc], [], now=NOW, root=tmp_path)
    assert rows[0]["verdict"] == "unknown"


def test_due_verdicts_are_only_the_three(tmp_path):
    """判词只许三个值；due 必带 why（卡规格第三条验收的硬要求）。"""
    accs = [
        _acc("a-1"),
        _acc("a-2", resets_at="2026-11-19T11:00:00+08:00", span_s=5 * 3600),
    ]
    rows = warmup.due(accs, ["12:00"], now=NOW, root=tmp_path)
    for row in rows:
        assert row["verdict"] in ("due", "not-due", "unknown")
        assert row["why"]
        assert set(row) == {"account", "ats", "verdict", "why"}

def test_cli_due_prints_json_and_exits_3_when_all_unknown(tmp_path, capsys, monkeypatch):
    """due 子命令：回 JSON（每号一条 {account, ats, verdict, why}）、只读、判不出退 3。"""
    acc = _acc("a-1", unit="点")
    monkeypatch.setattr(warmup, "_read_accounts", lambda root: ([acc], warmup.EXIT_OK))
    code = warmup.main([
        "due",
        "--json",
        "--now", "2026-11-19T12:00:00+08:00",
        "--root", str(tmp_path),
    ])
    assert code == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["now"] == "2026-11-19T12:00:00+08:00"
    assert payload["ats"] == ["12:00"]
    assert payload["rows"] == [
        {
            "account": "a-1",
            "ats": ["12:00"],
            "verdict": "unknown",
            "why": (
                "账本里没有 resets_at / span_s 这对键 ⇒ 判不出窗口在不在跑"
                "（先跑 python -X utf8 tools/pool_accounts.py probe）"
            ),
        }
    ]
    assert not (tmp_path / "gates/diag/warm-window.json").exists()


def test_cli_due_exits_2_when_ledger_unreadable(tmp_path, capsys, monkeypatch):
    """账本读不到 ⇒ 退 2（环境问题，不是「没有该 warm 的」）。"""
    monkeypatch.setenv("TF_ACCOUNTS_TOML", str(tmp_path / "nope" / "accounts.toml"))
    code = warmup.main(["due", "--json", "--root", str(tmp_path)])
    assert code == 2
    assert "账本读不到" in capsys.readouterr().err


def test_cli_register_writes_only_the_state_file(tmp_path, capsys, monkeypatch):
    """register 子命令是唯一的写动作；写的就是 gates/diag/warm-window.json。"""
    monkeypatch.setattr(warmup, "_read_accounts", lambda root: ([_acc("a-1")], warmup.EXIT_OK))
    code = warmup.main([
        "register",
        "--now", "2026-11-19T12:00:00+08:00",
        "--at", "09:00",
        "--root", str(tmp_path),
    ])
    assert code == 0
    body = json.loads((tmp_path / "gates/diag/warm-window.json").read_text(encoding="utf-8"))
    assert body == {"a-1": {"2026-11-19": ["09:00"]}}


def test_cli_status_is_read_only(tmp_path, capsys):
    """status 只打印登记表，一个字节都不写。"""
    code = warmup.main(["status", "--json", "--root", str(tmp_path)])
    assert code == 0
    assert json.loads(capsys.readouterr().out) == {}
    assert not (tmp_path / "gates/diag/warm-window.json").exists()


def test_cli_rejects_bad_now(tmp_path, capsys):
    """--now 认不出 ⇒ 退 2 并点名要求的形状（不许拿真实钟表糊过去）。"""
    code = warmup.main(["due", "--now", "昨天", "--root", str(tmp_path)])
    assert code == 2
    assert "ISO-8601" in capsys.readouterr().err


def test_warm_prints_suggestion_and_never_sends(tmp_path, capsys, monkeypatch):
    """warm 子命令只打印**建议命令**与理由 —— 本模块不发请求（硬边界）。"""
    acc = _acc(
        "a-1",
        resets_at="2026-11-19T11:00:00+08:00",
        span_s=5 * 3600,
    )
    monkeypatch.setattr(warmup, "_read_accounts", lambda root: ([acc], warmup.EXIT_OK))
    code = warmup.main([
        "warm",
        "--now", "2026-11-19T12:00:00+08:00",
        "--root", str(tmp_path),
    ])
    assert code == 0
    out = capsys.readouterr().out
    assert "建议命令" in out
    assert "tools/pool_accounts.py probe" in out
    assert not (tmp_path / "gates/diag/warm-window.json").exists()
