"""端口段体检（`tools/tf_portcheck.py`，卡 095 · 机器替代①）的测试。

判据是**纯机械**的：段内被占 → 退 1 且**点名**到「端口 ← pid 进程名」；全空闲 → 退 0。
这里用**假的端口表**（monkeypatch `busy_ports`）—— 不需要真端口，也不碰本机监听。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import tf_portcheck as tp  # noqa: E402 —— 需要先挂 tools/


def test_default_span_is_17() -> None:
    """铁律 37：㉒ 的对端用 BASE+16，所以一段是 17 个端口 —— 不许写死成别的。"""
    assert tp.DEFAULT_SPAN == 17


def test_segment_hits_covers_base_plus_16() -> None:
    """判据覆盖到段尾：`BASE+16`（对端那个口）被占也必须算命中。"""
    busy = {9191 + 16: "pid=1 vivoesService_x64.exe"}
    hits = tp.segment_hits(9191, tp.DEFAULT_SPAN, busy)
    assert hits == [(9207, "pid=1 vivoesService_x64.exe")]


def test_all_free_exits_0(monkeypatch, capsys) -> None:
    """全空闲 → 退 0，并说清哪一段到哪一段是全空闲的。"""
    monkeypatch.setattr(tp, "busy_ports", lambda: {})
    rc = tp.main(["--base", "9191"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "9191..9207 全空闲" in out


def test_busy_segment_exits_1_and_names(monkeypatch, capsys) -> None:
    """★ 反例：段内被占 → 退 1，且**点名**端口与进程（不许只说"忙"）。"""
    monkeypatch.setattr(tp, "busy_ports",
                        lambda: {9197: "pid=4321 vivoesService_x64.exe"})
    rc = tp.main(["--base", "9191"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "9197" in out
    assert "vivoesService_x64.exe" in out
    assert "✗" in out


def test_multiple_bases_any_busy_exits_1(monkeypatch, capsys) -> None:
    """`--base` 可重复：任何一段有占用，整次体检就退 1。"""
    monkeypatch.setattr(tp, "busy_ports", lambda: {9227: "pid=9 other.exe"})
    rc = tp.main(["--base", "9191", "--base", "9221"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "9191..9207 全空闲" in out          # 第一段空闲
    assert "9227" in out and "other.exe" in out  # 第二段点名


def test_positional_bases_still_work(monkeypatch, capsys) -> None:
    """位置参数（老入口 `_portcheck.py 9191 …` 的调用方式）继续可用。"""
    monkeypatch.setattr(tp, "busy_ports", lambda: {})
    assert tp.main(["9191", "9211"]) == 0
    out = capsys.readouterr().out
    assert "9191..9207 全空闲" in out and "9211..9227 全空闲" in out


def test_custom_span(monkeypatch, capsys) -> None:
    """`--span` 可调：span=1 时只看起点那一个端口。"""
    monkeypatch.setattr(tp, "busy_ports", lambda: {9192: "pid=1 x.exe"})
    assert tp.main(["--base", "9191", "--span", "1"]) == 0   # 只看 9191 → 空
    assert tp.main(["--base", "9191", "--span", "3"]) == 1   # 9191..9193 含 9192


def test_json_is_machine_readable(monkeypatch, capsys) -> None:
    """`--json`：给派活器调 —— 结构化、含 span 与每段的命中明细。"""
    monkeypatch.setattr(tp, "busy_ports", lambda: {9197: "pid=4321 vivoesService_x64.exe"})
    rc = tp.main(["--base", "9191", "--json"])
    assert rc == 1
    data = json.loads(capsys.readouterr().out)
    assert data["span"] == 17
    assert data["busy"] is True
    seg = data["segments"][0]
    assert (seg["base"], seg["start"], seg["end"]) == (9191, 9191, 9207)
    assert seg["busy"] == [{"port": 9197, "who": "pid=4321 vivoesService_x64.exe"}]


def test_json_all_free(monkeypatch, capsys) -> None:
    """`--json` 全空闲：退 0，`busy` 为 false、命中为空。"""
    monkeypatch.setattr(tp, "busy_ports", lambda: {})
    assert tp.main(["--base", "9191", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["busy"] is False
    assert data["segments"][0]["busy"] == []


def test_check_segments_accepts_injected_table() -> None:
    """`check_segments` 可注入端口表（不依赖本机、不依赖 monkeypatch 也能测）。"""
    segs = tp.check_segments([9191], span=17, busy={9200: "pid=7 svc.exe"})
    assert segs[0]["busy"] == [{"port": 9200, "who": "pid=7 svc.exe"}]


def test_bad_span_is_rejected(capsys) -> None:
    """`--span 0` 是坏输入：退 2 并说清（不是"全空闲"）。"""
    assert tp.main(["--base", "9191", "--span", "0"]) == 2
    assert "span" in capsys.readouterr().err
