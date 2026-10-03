"""pin_check（tools/pin_check.py，T-G145）的测试 —— 给「钉子判据」上牙。

钉住三条真历史（卡 053 §2.4，全用真数据；集成注：字面随主树现状换向钉住，
**行号一律不钉** —— 行号是会变的内容，见卡表 §22）：
  ① `DEFAULT_MODEL = MODEL_WHITELIST[0]` 必须点名台账 T-G85（台账证据 + ★ 钉子）；
  ② `const TASK_TYPES=[...]`（七档）必须报出 tests/test_web_frontend.py 且标 ★ 钉子；
  ③ 仓里不存在的字面 → 零命中 + 退出码 0（零误报）。
外加**反证**（卡 053 §2.4 三贴）：把「钉子语境」判据改坏（去掉 text:）→
钉子①不再被标钉子 —— 证明判据真在起作用，不是恒真。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pin_check as pc  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上

TOOL = [sys.executable, "-X", "utf8", str(ROOT / "tools" / "pin_check.py")]

LITERAL_TG85 = "DEFAULT_MODEL = MODEL_WHITELIST[0]"
LITERAL_TASK_TYPES = "const TASK_TYPES=['普通','作业','考试','论文','小测','竞赛','活动']"
LITERAL_ABSENT = "这个词本仓绝对不存在zzz"


def run_tool(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*TOOL, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )


def test_pin1_tg85_is_named_as_ledger_pin() -> None:
    r = run_tool("--literal", LITERAL_TG85)
    assert r.returncode == 1, f"有钉子命中应退 1，实际 {r.returncode}\n{r.stdout}"
    hit_line = next(ln for ln in r.stdout.splitlines() if "T-G85" in ln and "traceability" in ln)
    assert "台账证据" in hit_line, hit_line
    assert "★ 钉子" in hit_line, hit_line


def test_pin2_task_types_hits_test_file() -> None:
    r = run_tool("--literal", LITERAL_TASK_TYPES)
    assert r.returncode == 1, f"有钉子命中应退 1，实际 {r.returncode}\n{r.stdout}"
    hit_line = next(ln for ln in r.stdout.splitlines() if "tests/test_web_frontend.py" in ln)
    assert "★ 钉子" in hit_line, hit_line


def test_zero_hit_is_green() -> None:
    r = run_tool("--literal", LITERAL_ABSENT)
    assert r.returncode == 0, f"零命中应退 0，实际 {r.returncode}\n{r.stdout}"
    assert "零命中" in r.stdout, r.stdout


def test_narrative_hits_are_not_pins() -> None:
    r = run_tool("--literal", LITERAL_TG85)
    assert r.returncode == 1
    hit_line = next(
        ln for ln in r.stdout.splitlines()
        if ln.strip().startswith("叙述") and "tools/wb_dispatch.py" in ln
    )
    assert "叙述" in hit_line, hit_line
    assert "★ 钉子" not in hit_line, hit_line


def test_ledger_only_restricts_to_text_evidence() -> None:
    r = run_tool("--literal", LITERAL_TG85, "--ledger-only")
    assert r.returncode == 1
    assert "T-G85" in r.stdout, r.stdout
    assert "traceability.toml" in r.stdout, r.stdout
    assert "叙述 [" not in r.stdout, r.stdout


def test_multiple_literals_in_one_run() -> None:
    r = run_tool("--literal", LITERAL_TG85, "--literal", LITERAL_TASK_TYPES)
    assert r.returncode == 1
    assert "字面 1/2" in r.stdout and "字面 2/2" in r.stdout, r.stdout
    assert "T-G85" in r.stdout and "tests/test_web_frontend.py" in r.stdout, r.stdout


def test_empty_literal_is_usage_error() -> None:
    r = run_tool("--literal", "")
    assert r.returncode == 2, f"空字面应退 2，实际 {r.returncode}\n{r.stdout}"


def test_mutation_dropping_text_marker_kills_pin1(monkeypatch) -> None:
    """反证：判据改坏（去掉 text:）→ 钉子①必须失效（命中还在、钉子标没了）。"""
    broken = tuple(m for m in pc.PIN_MARKERS if m != "text:")
    monkeypatch.setattr(pc, "PIN_MARKERS", broken)
    hits = pc.scan_literal(LITERAL_TG85, pc.collect_files())
    ledger_hits = [h for h in hits if h.category == "台账证据" and h.entry == "T-G85"]
    assert ledger_hits, "命中本身不该消失（消失 = 匹配坏了，不是判据坏了）"
    assert all(not h.is_pin for h in ledger_hits), "去掉 text: 判据后 T-G85 不应再被标钉子"


# ---------------------------------------------------------------- 接上派活链路（卡 159 · T-G259）


def _opening_blocks() -> dict[str, str]:
    """派活器里的开场白常量原文（OPENING / LEAN_OPENING 两块都要有那条规矩）。"""
    import re

    src = (ROOT / "tools" / "wb_dispatch.py").read_text(encoding="utf-8")
    blocks = {}
    for name in ("OPENING", "LEAN_OPENING"):
        m = re.search(rf"^{name} = \((.*?)^\)", src, re.S | re.M)
        assert m, f"wb_dispatch.py 里找不到 {name}"
        blocks[name] = m.group(1)
    return blocks


def test_opening_rules_tell_copy_edit_cards_to_run_pin_check() -> None:
    """★ 卡 159（INV-47 的钉子）：改文案/字面/常量类卡**开工前必须跑 pin_check** ——
    这条规矩要钉进派活的开场白（普通 OPENING 与 --lean 的 LEAN_OPENING 都要），
    少任何一块 = 规矩悄悄退化回「撞上了才知道」。
    """
    for name, block in _opening_blocks().items():
        assert "pin_check" in block, f"{name} 里没有 pin_check 规矩（卡 159）"
        assert "--literal" in block, f"{name} 里没写怎么跑（--literal）"


def test_text_pointer_rule_prefers_semantic_anchors() -> None:
    """★ 卡 159（INV-77 的钉子）：`text:` 指针改指**语义锚点**的口径必须写进
    `复盘/外包-卡表与规矩.md` §22（证据指针语法表）—— 口径没立 = 下一个工人照旧钉整句。
    """
    doc = (ROOT / "复盘" / "外包-卡表与规矩.md").read_text(encoding="utf-8")
    sec22 = doc.split("## §22", 1)[1].split("## §23", 1)[0]
    assert "语义锚点" in sec22, "§22 里没有「语义锚点」口径"
    assert "pin_check" in sec22, "§22 里没有「改前先跑 pin_check」"
