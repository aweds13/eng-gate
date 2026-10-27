"""文档门（`docs`，卡 F3 / T-AG451）接进门禁表的钉子。

这道门跑的是 `scripts/check_docs.py --mode report`：

* **有债不红**（report 档）—— 债还没还完，第一版不挂 block；
* **基线被顶破才红**（ratchet 只许降不许升，与档位无关）；
* **退出码非 0 一律不算通过** —— `gates_ok()` 只认 `exit_code == 0`，
  退 3（没判完）与退 1（超基线）都落进非 0。

★ 已知取舍（`test_skip_count_is_loud_but_does_not_red_report_mode` 钉住它）：
`--mode report` 按 `check_docs.exit_code()`
的语义**永远不会**返 3 —— 只有 block 档才会。所以「skip 计数」目前在门禁层**不判红**，
只出现在这道门的输出与 summary 里。要把它变成硬红，得改成 block 档或加一层包装，
那是另一张卡的事。
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 只用在注解上（ruff TC002）：真跑时 pytest 由插件自己加载
    import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_run_gates():
    """照 `tests/test_run_gates_profiles.py` 的方式加载 runner（不 import 真进程）。"""
    target = ROOT / "scripts" / "run_gates.py"
    spec = importlib.util.spec_from_file_location("run_gates_for_docs_gate", target)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_gates_for_docs_gate"] = mod
    spec.loader.exec_module(mod)
    return mod


rg = _load_run_gates()


# --------------------------------------------------------------------- 夹具
def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def _baseline(root: Path, *, dead_refs: int, superseded: int = 0) -> None:
    """写一份合成基线（`load_baseline()` 要求 dead_refs 与 superseded 两项都在）。"""
    (root / "docs" / "doc-debt-baseline.toml").write_text(
        f'[baseline]\nupdated = "2026-10-27"\ndead_refs = {dead_refs}\n'
        f"superseded = {superseded}\n",
        encoding="utf-8",
    )


def _seed_git(root: Path) -> None:
    assert _git(root, "init", "-q").returncode == 0
    assert _git(root, "add", "-A").returncode == 0
    commit = _git(
        root, "-c", "user.name=test", "-c", "user.email=test@example.invalid",
        "commit", "-q", "-m", "seed",
    )
    assert commit.returncode == 0, commit.stderr


def _tree(tmp_path: Path, *, dead_refs: int) -> Path:
    """一棵合成小树：`dead_refs` 条死指针（`docs/bad.md` → 不存在的文件）。"""
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "ok.md").write_text("见 `docs/ok.md`\n", encoding="utf-8")
    if dead_refs:
        (docs / "bad.md").write_text(
            "第一行\n看 `docs/missing.md` 这一句\n", encoding="utf-8"
        )
    _baseline(tmp_path, dead_refs=dead_refs)
    _seed_git(tmp_path)
    return tmp_path


def _gate_argv() -> list[str]:
    """注册表里这道门的**真命令**（门跑的就是它）。"""
    cmds = dict(rg.COMMON)
    assert "docs" in cmds, f"门表里没有 docs：{[n for n, _ in rg.COMMON]}"
    return list(cmds["docs"])


def _run_gate(tree: Path, *extra: str) -> subprocess.CompletedProcess:
    """按门表里那条命令跑一遍，只把 `--root` 指到合成树。"""
    return subprocess.run(
        [*_gate_argv(), "--root", str(tree), *extra],
        cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False,
    )


def _ok(exit_code: int) -> bool:
    """门禁层判绿的口径（与 `run_gates.gates_ok` 同一条）。"""
    return rg.gates_ok([{"name": "docs", "exit_code": exit_code}])


# ------------------------------------------------------- (a) 门在注册表里
def test_docs_gate_is_registered_and_runs_report_mode() -> None:
    """★ 门表里有这道门、命令逐字是 report 档、归 audit 档、不在 --fast 内循环里。"""
    names = [n for n, _ in rg.COMMON]
    assert names.count("docs") == 1, f"docs 在门表里出现 {names.count('docs')} 次：{names}"
    assert _gate_argv()[1:] == [
        "-X", "utf8", "scripts/check_docs.py", "--mode", "report",
    ], _gate_argv()
    # 命令里的解释器就是当前解释器（门从门表起子进程，不能写死别的 python）
    assert _gate_argv()[0] == sys.executable
    # 档位：audit（契约/台账类），且三档钉子照旧成立
    assert "docs" in rg.GATE_PROFILES["audit"]
    assert "docs" not in rg.GATE_PROFILES["lang"]
    assert "docs" not in rg.GATE_PROFILES["product"]
    # 全量门表（即 --list 的等价读数）含它；--fast 里没有它（文档门不进开发内循环）
    assert "docs" in [n for n, _ in rg.build_jobs(quick=False, fast=False)]
    assert "docs" not in rg.FAST


# ------------------------------------- (b) 有债（= 基线）在 report 档不判红
def test_debt_at_baseline_is_green_in_report_mode(tmp_path: Path) -> None:
    """★ 1 条死指针、基线也是 1 ⇒ 退 0，且**数字要看得见**（不是静默通过）。"""
    tree = _tree(tmp_path, dead_refs=1)
    proc = _run_gate(tree)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _ok(proc.returncode) is True
    text = proc.stdout
    assert "死指针 1 条" in text, text  # counts 进门输出
    assert "CHECK_DOCS: 死指针 1（基线 1，+0）" in text, text


# ------------------------------------------- (b') 债涨破基线：report 档也红
def test_debt_over_baseline_is_red_even_in_report_mode(tmp_path: Path) -> None:
    """★ ratchet 与档位无关：基线 0、实际 1 ⇒ 退 1 ⇒ 门禁判红。"""
    tree = _tree(tmp_path, dead_refs=1)
    _baseline(tree, dead_refs=0)
    # 基线是已提交文件的一部分，改它要重新提交（否则只算工作区脏，ratchet 照读）
    assert _git(tree, "add", "-A").returncode == 0
    assert _git(
        tree, "-c", "user.name=test", "-c", "user.email=test@example.invalid",
        "commit", "-q", "-m", "tighten",
    ).returncode == 0
    proc = _run_gate(tree)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert _ok(proc.returncode) is False
    assert "涨到" in proc.stdout and "超基线" in proc.stdout, proc.stdout


# ---------------------------------------- (c) 非 0（含退出码 3）一律不算通过
def test_any_nonzero_exit_code_is_not_a_pass() -> None:
    """★ 退 3（没判完）与退 1（有债）都不许当 PASS —— 只有 0 才算绿。"""
    assert _ok(0) is True
    for code in (1, 2, 3, 124):
        assert _ok(code) is False, f"exit_code={code} 被当成了通过"
    # 门禁层不许把 3 当「跳过」：blocking 缺省为真 ⇒ 参与判定
    assert rg.gates_ok([{"name": "docs", "exit_code": 3}]) is False
    # 真正被标成 blocking=False 的（例如没起浏览器）才不参与判定
    assert rg.gates_ok([{"name": "docs", "exit_code": 3, "blocking": False}]) is True


def test_skip_count_is_loud_but_does_not_red_report_mode(tmp_path: Path) -> None:
    """★ 判不出的东西必须**喊出来**；report 档它不判红（已知取舍，见文件头）。"""
    tree = _tree(tmp_path, dead_refs=0)
    (tree / "gates").mkdir(exist_ok=True)  # gates/ 在根上存在，gates/diag/... 才算仓内路径
    (tree / "docs" / "skip.md").write_text(
        "模板：`docs/<卡号>.md`\n产物：`gates/diag/x.md`\n", encoding="utf-8"
    )
    assert _git(tree, "add", "-A").returncode == 0
    assert _git(
        tree, "-c", "user.name=test", "-c", "user.email=test@example.invalid",
        "commit", "-q", "-m", "skips",
    ).returncode == 0

    report = _run_gate(tree)
    assert report.returncode == 0, report.stdout + report.stderr
    assert "判不出" in report.stdout and "不是 PASS" in report.stdout
    assert "CHECK_DOCS: PASS" not in report.stdout
    # 同一棵树切 block 档 ⇒ 退 3（这才是「skip 不许当 PASS」的机器口径）
    blocked = _run_gate(tree, "--mode", "block")
    assert blocked.returncode == 3, blocked.stdout + blocked.stderr
    assert _ok(blocked.returncode) is False


# ------------------------------------------------ (d) --only 只跑这一道门
def test_only_docs_runs_only_that_door(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """★ `--only docs` 只起这一道门，且产物里只记这一道（不写真实 gates/last.json）。"""
    started: list[str] = []

    def fake_start_gate(name: str, cmd: list[str]):
        started.append(name)
        assert cmd and cmd[0] == sys.executable, cmd
        return object(), 0.0, ""

    def fake_finish_gate(name: str, proc: object, t0: float, timeout=None):
        return {"name": name, "exit_code": 0, "seconds": 0.0, "summary": "假门：绿"}

    last = tmp_path / "last.json"
    monkeypatch.setattr(rg, "GATES", last)
    monkeypatch.setattr(rg, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(rg, "REUSE", tmp_path / "reuse.json")
    monkeypatch.setattr(rg, "start_gate", fake_start_gate)
    monkeypatch.setattr(rg, "finish_gate", fake_finish_gate)
    monkeypatch.setenv("TF_GATE_MIN_FREE_GB", "0")  # 内存闸与本卡无关，关掉免得看机器脸色
    monkeypatch.setattr(sys, "argv", ["run_gates.py", "--only", "docs", "--serial"])

    assert rg.main() == 0
    assert started == ["docs"], started  # 只起了这一道

    payload = json.loads(last.read_text(encoding="utf-8"))
    total = len(rg.build_jobs(quick=False, fast=False))
    assert payload["only"] == ["docs"]
    assert payload["only_counts"] == f"1/{total}"
    assert [g["name"] for g in payload["gates"]] == ["docs"]
    assert "docs" not in payload["not_run"]
    assert any("未跑全量" in part for part in payload["trailer"].split("；")), payload["trailer"]
