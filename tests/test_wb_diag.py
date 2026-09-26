"""`tools/wb_diag.py`（日志失败定位器，T-G108）的测试 —— 把 1 MB 的 log 压成"错在哪"。

为什么要有测试：工人跑完的 log 是 100 KB ~ 1.2 MB 的 stream-json，主控真正要的只有几行
（**哪条红了 / 断言原文 / 项目内的栈帧 / 它最后在干什么**）。这个工具的价值全在"**它有没有替主控
把噪音丢掉、把信号留下**"：

- 抓不红 → 主控还得整份读（工具白做）；
- 抓一堆**外部库的栈帧** → 比不抓更坏（噪音淹掉信号）；
- 日志半截（正在写）/ 一条坏行 → **不许炸**（跑长任务时日志永远可能不完整）。

★ 单测一律用**合成事件流**（`tmp_path`），**不读真日志** —— 真 log 只在卡 §5 的"真东西验证"里
手工跑一次（见 `复盘/少读工具-T-G108.md`）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_diag as wd  # noqa: E402


def _event(**kwargs: object) -> str:
    return json.dumps(kwargs, ensure_ascii=False)


def _assistant(*items: dict) -> str:
    return _event(type="assistant", message={"content": list(items)})


def _tool_result(text: str, is_error: bool = False) -> str:
    return _event(type="user", message={"content": [
        {"type": "tool_result", "content": text, "is_error": is_error}]})


PYTEST_OUT = "\n".join([
    "=========================== short test summary info ===========================",
    "FAILED tests/test_a.py::test_x - assert 1 == 2",
    "FAILED tests/test_b.py::test_y - AssertionError: nope",
    "ERROR tests/test_c.py::test_z",
    "FAILED tests/test_a.py::test_x - assert 1 == 2",   # 重复的一行（去重）
    "",
    "tests/test_a.py:12: in test_x",
    "    assert 1 == 2",
    "E   assert 1 == 2",
    "E    +  where 1 = thing()",
    "ValueError: boom",
])


def _frame(root: Path, rel: str, line: int) -> str:
    return f'  File "{root / rel}", line {line}, in test_x'


def _log(root: Path) -> list[str]:
    return [
        _event(type="system", subtype="init", model="deepseek-v4.1-flash",
               tools=["Bash", "Read"]),
        _assistant({"type": "text", "text": "先跑目标用例。"}),
        _assistant({"type": "tool_use", "name": "Bash", "input": {"command": "pytest -k a"}}),
        _tool_result(PYTEST_OUT),
        _assistant({"type": "tool_use", "name": "Read", "input": {"file_path": "tests/test_a.py"}}),
        _tool_result("Traceback (most recent call last):\n"
                     + _frame(root, "tests/test_a.py", 12) + "\n"
                     + '  File "C:\\py\\Lib\\json\\__init__.py", line 5, in loads\n'
                     + '  File "<string>", line 1, in <module>\n'
                     + "ValueError: boom"),
        _assistant({"type": "tool_use", "name": "Edit",
                    "input": {"file_path": "tests/test_a.py", "old_string": "1 == 2"}}),
        _event(type="result", subtype="success", result="改完了，门禁全绿"),
    ]


# ------------------------------------------------------------------ 零件层


def test_finds_failed_and_error_test_ids_and_dedups() -> None:
    """抓 `FAILED <path>::<test>` / `ERROR <path>::<test>` 行，并去重。"""
    got = wd.find_failed_tests([PYTEST_OUT])
    assert "FAILED tests/test_a.py::test_x" in got
    assert "FAILED tests/test_b.py::test_y" in got
    assert "ERROR tests/test_c.py::test_z" in got
    assert got.count("FAILED tests/test_a.py::test_x") == 1, f"没去重：{got}"


def test_project_frames_kept_and_external_dropped(tmp_path: Path) -> None:
    """★ 项目内栈帧留下（且只留仓库相对路径），外部库 / `<string>` 的帧一律丢。"""
    text = ("Traceback (most recent call last):\n"
            + _frame(tmp_path, "tests/test_a.py", 12) + "\n"
            + _frame(tmp_path, "src/timeflow/cli/main.py", 88) + "\n"
            + '  File "C:\\py\\Lib\\json\\__init__.py", line 5, in loads\n'
            + '  File "<string>", line 1, in <module>\n')
    got = wd.find_project_frames([text], tmp_path)
    assert got == ["tests/test_a.py:12", "src/timeflow/cli/main.py:88"], got


def test_assertion_lines_split_into_three_buckets() -> None:
    """三类各抓各的：`assert ...` / `AssertionError` / 其它 `Error:`。"""
    buckets = wd.find_assertion_lines([PYTEST_OUT])
    assert any("assert 1 == 2" in ln for ln in buckets["assert"])
    assert any("AssertionError" in ln for ln in buckets["AssertionError"])
    assert any("ValueError: boom" in ln for ln in buckets["Error:"])
    # 每类最多 10 行
    many = "\n".join(f"    assert {i} == {i + 1}" for i in range(50))
    assert len(wd.find_assertion_lines([many])["assert"]) == 10


def test_no_failures_and_bad_lines_do_not_crash() -> None:
    """没有红用例 / 半截 log / 坏行 → 空结果 + 不抛异常（长任务里日志永远可能不完整）。"""
    lines = ["不是 JSON 的一行", "", "{坏 JSON", _tool_result("一切正常，0 failed").rstrip()]
    diag = wd.diagnose(lines)
    assert diag["failed"] == []
    assert diag["frames"] == []
    assert diag["has_result"] is False
    assert diag["subtype"] == ""


def test_error_bucket_ignores_source_code_lines() -> None:
    """`Error:` 只认**行首**的异常名（可选 pytest 的 `E ` / grep 的 `NN→` 前缀）。

    为什么：工具回话里常夹着工人 grep 出来的**源码**（`except json.JSONDecodeError:` 之类），
    它们在字面上也符合 "Error:" —— 不挡住，10 行的额度会被噪音占满，真正那行反而被挤掉
    （这正是"少读"最怕的结果）。grep 前缀要剥掉再判，否则 `86→E IndexError: …` 这种真行会被误杀。
    """
    text = "\n".join([
        "    except json.JSONDecodeError:",
        "238→ except json.JSONDecodeError:",
        "IndexError: list index out of range",
        "86→E IndexError: list index out of range test_x.py:681",
    ])
    got = wd.find_assertion_lines([text])["Error:"]
    assert "except json.JSONDecodeError:" not in "\n".join(got), got
    assert sum("list index out of range" in ln for ln in got) == 2, got


# ------------------------------------------------------------------ 整机层


def test_diagnose_extracts_all_five_sections(tmp_path: Path) -> None:
    diag = wd.diagnose(_log(tmp_path), root=tmp_path)
    assert diag["failed"] == [
        "FAILED tests/test_a.py::test_x",
        "FAILED tests/test_b.py::test_y",
        "ERROR tests/test_c.py::test_z",
    ]
    assert diag["frames"] == ["tests/test_a.py:12"]
    assert diag["has_result"] is True and diag["subtype"] == "success"
    assert diag["log_lines"] == len(_log(tmp_path))
    assert len(diag["calls"]) == 3 and "Edit" in diag["calls"][-1]


def test_report_prints_the_five_sections_even_when_empty(tmp_path: Path) -> None:
    """五段标题永远在（空就写「（没有）」）—— 主控不看全也知道"哪段是空的"。"""
    report = wd.render(wd.diagnose([_event(type="system", subtype="init")], root=tmp_path))
    for head in ("红的用例", "断言原文", "项目内栈帧", "它最后在干什么", "一行汇总"):
        assert head in report, f"缺了 {head} 这一段"
    assert "（没有）" in report


def test_cli_writes_nothing_and_handles_missing_file(tmp_path: Path) -> None:
    """CLI：真 log 落盘 → 退 0；文件不存在 → 退 2（不炸）。"""
    log = tmp_path / "wb-999.jsonl"
    log.write_text("\n".join(_log(tmp_path)), encoding="utf-8")
    assert wd.main([str(log)]) == 0
    assert wd.main([str(tmp_path / "nope.jsonl")]) == 2
