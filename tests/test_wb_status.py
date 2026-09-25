"""WorkBuddy 状态器（`tools/wb_status.py`，T-G81）的测试 —— 给"看工人的窗"上护栏。

为什么要有测试：这个工具的**输入是别的进程吐出来的 JSONL**，而那个进程会升级、会换事件形状。
它最容易得的病有两种，两种都已经被钉住：
  · **认不出来就静默丢掉** → 状态器说"什么也没干"，而工人其实干了一堆（比没有窗更坏）；
  · **长输出原样刷屏**（工具回话里可能是几万字的文件内容）→ 真正的动作被淹掉。

零件层喂合成事件；CLI 层验 `--tail` / `--json` / 文件不存在这三条路。
★ 形状目前按 CodeBuddy/Claude-Code 那一族写 —— **第一次真派活之后要用真 log 复钉**（本文件头一句
就是记这件事，别让它漂）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_status as ws  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上


def _event(**kwargs: object) -> str:
    return json.dumps(kwargs, ensure_ascii=False)


def _assistant(*items: dict) -> str:
    return _event(type="assistant", message={"content": list(items)})


def _lines() -> list[str]:
    return [
        _event(type="system", subtype="init", model="deepseek-v3-2-volc",
               tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"]),
        _assistant({"type": "text", "text": "我先读一遍交接文档，再决定动哪里。"}),
        _assistant({"type": "tool_use", "name": "Bash",
                    "input": {"command": "git status --short"}}),
        _event(type="user", message={"content": [
            {"type": "tool_result", "content": "M src/timeflow/api/app.py"}]}),
        _assistant({"type": "tool_use", "name": "Edit",
                    "input": {"file_path": "src/timeflow/core/tasks/manager.py",
                              "old_string": "a"}}),
        _event(type="user", message={"content": [
            {"type": "tool_result", "content": "编辑失败：找不到那段", "is_error": True}]}),
        _event(type="result", subtype="success", result="改完了，门禁全绿"),
    ]


# ------------------------------------------------------------------ 零件层


def test_timeline_shows_model_tools_and_what_it_touched() -> None:
    """一行事件 → 一行人话：模型、工具清单、每个动作动了哪个文件/跑了什么命令。"""
    timeline, summary = ws.parse_events(_lines())
    body = "\n".join(timeline)

    assert "deepseek-v3-2-volc" in body          # 用的是哪个模型
    assert "Grep" in body                        # ★ 它到底有没有 grep，看这一行
    assert "Bash(command=git status --short)" in body
    assert "src/timeflow/core/tasks/manager.py" in body
    assert summary["tool_calls"] == 2
    assert summary["tools"] == {"Bash": 1, "Edit": 1}
    assert summary["texts"] == 1
    assert summary["files"] == ["src/timeflow/core/tasks/manager.py"]
    assert summary["tool_errors"] == 1
    assert summary["final"] == "改完了，门禁全绿"


def test_unknown_event_shapes_are_shown_not_swallowed() -> None:
    """对方升级换了形状 → **原样留一行**，不许静默什么都不说（比没有窗更坏）。"""
    timeline, summary = ws.parse_events([_event(type="brand_new_thing", foo=1)])
    assert "brand_new_thing" in timeline[0]
    assert summary["unknown_events"] == 1


def test_broken_json_line_does_not_crash() -> None:
    """半行 / 非 JSON（进程被 kill 时很常见）→ 记一句，继续读完整个文件。"""
    ok = _event(type="result", subtype="success", result="ok")
    timeline, summary = ws.parse_events(["这不是 JSON", ok])
    assert "非 JSON 行" in timeline[0]
    assert summary["unknown_events"] == 1
    assert summary["final"] == "ok"


def test_long_output_is_clipped() -> None:
    """工具回话里可能塞着整个文件 —— 状态器一行最多 240 字，不许刷屏。"""
    big = "x" * 5000
    timeline, _ = ws.parse_events([
        _event(type="user", message={"content": [{"type": "tool_result", "content": big}]}),
    ])
    assert len(timeline[0]) < 400
    assert big not in timeline[0]


def test_non_dict_event_does_not_crash() -> None:
    """一行合法 JSON 但不是对象（比如一个数组）也不许崩。"""
    timeline, summary = ws.parse_events(["[1,2,3]"])
    assert "非对象事件" in timeline[0]
    assert summary["unknown_events"] == 1


# ------------------------------------------------------------------ CLI 层


def _write(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "wb.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_tail_shows_only_the_last_events(tmp_path: Path, monkeypatch, capsys) -> None:
    """跑长任务时看进度：`--tail` 只印最后几条（第一条发言不该出现）。"""
    path = _write(tmp_path, _lines())
    monkeypatch.setattr(sys, "argv", ["wb_status.py", str(path), "--tail", "2"])
    assert ws.main() == 0
    out = capsys.readouterr().out
    assert "改完了，门禁全绿" in out
    assert "我先读一遍交接文档" not in out


def test_json_summary_is_machine_readable(tmp_path: Path, monkeypatch, capsys) -> None:
    """主控要拿它做判断 → `--json` 必须是能解析的摘要。"""
    path = _write(tmp_path, _lines())
    monkeypatch.setattr(sys, "argv", ["wb_status.py", str(path), "--json"])
    assert ws.main() == 0
    data = json.loads(capsys.readouterr().out)
    assert data["tool_calls"] == 2
    assert data["final"] == "改完了，门禁全绿"


def test_missing_log_is_a_clean_error(tmp_path: Path, monkeypatch, capsys) -> None:
    """文件不存在 → 退出码 2 + 一句人话，不许抛栈（它常被主控在循环里调）。"""
    monkeypatch.setattr(sys, "argv", ["wb_status.py", str(tmp_path / "没有这个.jsonl")])
    assert ws.main() == 2
    assert "找不到 log" in capsys.readouterr().err
