r"""`tools/zentao_gantt.py`（卡 223 · T-G337）的测试 —— **不连真禅道**。

## 测什么

在卡 211 的只读读数之上自写的迭代甘特：样例读数 ⇒ 能出 HTML/JSON（且自包含、确定性）；
字段缺失 ⇒ 如实报；坏输入 ⇒ 不许崩；★ 反例：把迭代起止改坏 ⇒ 必须红并点名。

## ★ 诚实边界（不假装）

本机**没有在跑的禅道**（见 `docs/zentao-bridge.toml` 的 `[runtime]`）。所以这里用的
`zentao_gantt.SAMPLE_BUNDLE`（及从它派生的坏样本）**不是**「真拉到的响应」—— 它是照
卡 211 测试 fixture 的字段形状编的。真禅道数据下甘特长什么样，**本卡验不了**（回报里如实写）。
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import zentao_gantt  # noqa: E402,I001 —— 需要先把 tools/ 挂上
from pool.no_window import NO_WINDOW  # noqa: E402

TOOL = [sys.executable, "-X", "utf8", str(ROOT / "tools" / "zentao_gantt.py")]


def run_tool(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*TOOL, *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT), timeout=60, **NO_WINDOW,
    )


def _write_bundle(tmp_path: Path, bundle: object, name: str = "读数.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    return path


def _mutate(mutator) -> dict:
    """从内置样例复制一份再改 —— 保证「只有那一处坏」（反例只咬一处）。"""
    bundle = copy.deepcopy(zentao_gantt.SAMPLE_BUNDLE)
    mutator(bundle)
    return bundle


# ── 1. 口径钉子：样例的字段名就是卡 211 定的那套（不另立字段）─────────────────
def test_sample_fields_match_bridge_canonical_set() -> None:
    sample = zentao_gantt.SAMPLE_BUNDLE
    assert set(sample["executions"][0]) == set(zentao_gantt.EXECUTION_FIELDS)
    assert set(sample["tasks"][0]) == set(zentao_gantt.TASK_FIELDS)
    assert zentao_gantt.REQUIRED_ITEM_FIELDS == ("id", "name")


# ── 2. 样例读数 ⇒ 能出 JSON（机器可读）──────────────────────────────────────
def test_sample_produces_json_model() -> None:
    got = run_tool(["--json"])
    assert got.returncode == 0, got.stderr
    model = json.loads(got.stdout)
    assert model["ok"] is True
    assert model["executions"] == 3 and model["tasks"] == 6
    assert model["range"] == {"begin": "2026-01-01", "end": "2026-03-11", "days": 70}
    rows = {row["id"]: row for row in model["rows"]}
    assert rows[11]["days"] == 14 and rows[11]["begin"] == "2026-01-01"
    assert len(rows[12]["tasks"]) == 3, "迭代二下挂三个任务"
    # 「联调」没有 deadline ⇒ 如实报，不当成没有这个任务
    assert any("105" in w and "deadline" in w for w in model["warnings"]), model["warnings"]


# ── 3. 样例读数 ⇒ 能出 HTML，且**自包含**（无外链 / 无脚本）──────────────────
def test_sample_produces_self_contained_html(tmp_path: Path) -> None:
    out = tmp_path / "gantt.html"
    got = run_tool(["--html", str(out)])
    assert got.returncode == 0, got.stderr
    assert out.exists(), "HTML 没落盘"
    text = out.read_text(encoding="utf-8")
    assert text.startswith("<!DOCTYPE html>")
    for needle in ("禅道迭代甘特", "迭代一", "迭代三", 'class="bar"', "任务截止", "如实报"):
        assert needle in text, f"HTML 里少了 {needle!r}"
    assert "<script" not in text, "自包含：不该有脚本"
    assert 'src="http' not in text and 'href="http' not in text, "自包含：不该有外链"


# ── 4. 确定性：同一输入两次 --json / --html 逐字节相同 ───────────────────────
def test_output_is_deterministic(tmp_path: Path) -> None:
    first_json = run_tool(["--json"])
    second_json = run_tool(["--json"])
    assert first_json.returncode == second_json.returncode == 0
    assert first_json.stdout == second_json.stdout, "同一输入两次 --json 必须逐字节相同"

    a, b = tmp_path / "a.html", tmp_path / "b.html"
    run_tool(["--html", str(a)])
    run_tool(["--html", str(b)])
    assert a.read_bytes() == b.read_bytes(), "同一输入两次 --html 必须逐字节相同"


# ── 5. 字段缺失 ⇒ 如实报并点名（起止没了）────────────────────────────────────
def test_missing_end_is_reported_and_named(tmp_path: Path) -> None:
    bundle = _mutate(lambda b: b["executions"][0].pop("end"))
    path = _write_bundle(tmp_path, bundle)
    got = run_tool(["--input", str(path), "--json"])
    assert got.returncode == 6, f"缺字段应退 6，实为 {got.returncode}\n{got.stdout}{got.stderr}"
    err = json.loads(got.stdout)["error"]
    assert err["kind"] == "badshape" and "end" in err["detail"]
    assert "#11 迭代一" in err["detail"], f"必须点名那条迭代：{err['detail']}"


# ── 6. 坏输入（不是 JSON）⇒ 不许崩，报清是哪一步 ─────────────────────────────
def test_bad_json_does_not_crash(tmp_path: Path) -> None:
    path = tmp_path / "读数.txt"
    path.write_text("<html>这不是 JSON</html>", encoding="utf-8")
    got = run_tool(["--input", str(path), "--json"])
    assert got.returncode == 5, f"坏 JSON 应退 5，实为 {got.returncode}\n{got.stdout}{got.stderr}"
    err = json.loads(got.stdout)["error"]
    assert err["kind"] == "badjson"
    assert "Traceback" not in got.stderr and "Traceback" not in got.stdout, "不许崩"


# ── 7. 顶层不是对象 / 没有 executions 数组 ⇒ 如实报 ─────────────────────────
def test_missing_executions_section_is_reported(tmp_path: Path) -> None:
    path = _write_bundle(tmp_path, {"ok": True, "projects": []})
    got = run_tool(["--input", str(path), "--json"])
    assert got.returncode == 6, got.stdout
    assert "executions" in json.loads(got.stdout)["error"]["detail"]


# ── 8. 迭代为空 / 没有 tasks 段 ⇒ 退 0，但**在输出里如实报** ─────────────────
def test_empty_executions_is_reported_not_faked(tmp_path: Path) -> None:
    bundle = {"ok": True, "source": "空读数", "executions": [], "tasks": []}
    path = _write_bundle(tmp_path, bundle, "empty.json")
    got = run_tool(["--input", str(path), "--json"])
    assert got.returncode == 0, got.stderr
    model = json.loads(got.stdout)
    assert model["executions"] == 0
    assert any("没有可画的迭代" in w for w in model["warnings"]), model["warnings"]


def test_missing_tasks_section_is_warned(tmp_path: Path) -> None:
    bundle = _mutate(lambda b: b.pop("tasks"))
    path = _write_bundle(tmp_path, bundle)
    got = run_tool(["--input", str(path), "--json"])
    assert got.returncode == 0, got.stderr
    model = json.loads(got.stdout)
    assert any("没有 'tasks' 段" in w for w in model["warnings"]), model["warnings"]
    assert model["tasks"] == 0


# ── ★ 9. 反例：把样例里的迭代起止**改坏** ⇒ 必须红并点名 ──────────────────────
def test_corrupted_iteration_start_end_is_red_and_named(tmp_path: Path) -> None:
    """起止倒挂（end 早于 begin）—— 这是最典型的「起止改坏」。"""
    bundle = _mutate(
        lambda b: b["executions"][1].update({"begin": "2026-02-11", "end": "2026-01-15"}))
    path = _write_bundle(tmp_path, bundle, "倒挂.json")
    got = run_tool(["--input", str(path)])
    assert got.returncode == 7, f"起止倒挂应退 7，实为 {got.returncode}\n{got.stdout}{got.stderr}"
    assert "迭代二" in got.stderr or "迭代二" in got.stdout, "必须点名那条迭代"
    assert "起止倒挂" in got.stderr or "起止倒挂" in got.stdout


def test_corrupted_date_format_is_red_and_named(tmp_path: Path) -> None:
    """起止写成非 ISO 日期 —— 也必须红并点名，不许当成「没数据」。"""
    bundle = _mutate(lambda b: b["executions"][0].update({"end": "2026-13-40"}))
    path = _write_bundle(tmp_path, bundle, "坏格式.json")
    got = run_tool(["--input", str(path), "--json"])
    assert got.returncode == 7, f"坏日期应退 7，实为 {got.returncode}\n{got.stdout}{got.stderr}"
    err = json.loads(got.stdout)["error"]
    assert err["kind"] == "baddate" and "#11 迭代一" in err["detail"], err["detail"]
