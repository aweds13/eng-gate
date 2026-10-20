r"""接管旧项目的**端到端**验证（卡 A301 · `T-AG415`）：
勘察 → 映射 → 限制 → 最小骨架 → 第一步验收。

为什么另起一份、不塞进 `tests/test_wb_takeover.py`：那一份钉的是**分类判据**
（A/B/C/D 各一条 case）；这一份钉的是**整条路径走得通**：

1. 四类样例目录（A 完整 / B 有卡无门 / C 只有代码 / D 空）逐类给出
   `kind` + `mapping_hints`（照 `复盘/接手能力-方案.md` §1–§2）；
2. 对 **C 类**真走一遍「铺最小骨架 → 第一步验收」（方案 §5 第 3–4 步）：
   骨架铺完 ⇒ 勘察器认得出是 A；那道门**真会跑**（退 0）且**真会红**（塞坏数据退 1）；
   台账证据在骨架里**可求值**（`file:` 换成真文件 / 假文件两半）。

★ 全程只在 `tmp_path` 里落文件，**一个字节都不写真实仓库**；勘察器本身只读（跑完比一次目录指纹）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "scripts"))

import audit_progress as ap  # noqa: E402 —— 证据求值器的唯一真源（不另写一份）
import wb_takeover as wt  # noqa: E402
from pool.no_window import NO_WINDOW  # noqa: E402 —— 起子进程必须不弹窗（卡 148）

#: 一道真门的源码（骨架里的「第一步验收」用它）：> 3 行数据就退 1。
GATE_SRC = """import pathlib
import sys

data = pathlib.Path("data.txt")
lines = data.read_text(encoding="utf-8").splitlines() if data.is_file() else []
print(f"[check_size] data.txt {len(lines)} 行")
sys.exit(0 if len(lines) <= 3 else 1)
"""


def _fingerprint(root: Path) -> set[tuple[str, int]]:
    """目录指纹（相对路径 + 字节数）—— 「勘察器零写盘」用它对账。"""
    return {
        (p.relative_to(root).as_posix(), p.stat().st_size)
        for p in root.rglob("*") if p.is_file()
    }


def _mk_a(tmp_path: Path) -> Path:
    """A 完整：骨架配置 + 三件套（本仓形态：没有根级 pipeline.toml 也算 A）。"""
    d = tmp_path / "proj-a"
    for sub in ("docs", "gates", "tools", "src"):
        (d / sub).mkdir(parents=True)
    (d / "harness.toml").write_text("[harness]\n", encoding="utf-8")
    (d / "docs" / "workbacklog.toml").write_text('[[cards]]\nid = "A1"\n', encoding="utf-8")
    (d / "gates" / "last.json").write_text('{"ok": true}', encoding="utf-8")
    (d / "tools" / "wb_demo.py").write_text("# demo\n", encoding="utf-8")
    (d / "src" / "main.py").write_text("print(1)\n", encoding="utf-8")
    return d


def _mk_b(tmp_path: Path) -> Path:
    """B 有卡无门：有测试 / CI，没有管线配置与三件套。"""
    d = tmp_path / "proj-b"
    (d / "tests").mkdir(parents=True)
    (d / ".github" / "workflows").mkdir(parents=True)
    (d / "pyproject.toml").write_text("[project]\nname='b'\n", encoding="utf-8")
    (d / ".github" / "workflows" / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    (d / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    return d


def _mk_c(tmp_path: Path) -> Path:
    """C 只有代码：无测试、无 CI、无管线 ⇒ 兜底类，要铺骨架。"""
    d = tmp_path / "proj-c"
    (d / "src").mkdir(parents=True)
    (d / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    return d


def _mk_d(tmp_path: Path) -> Path:
    """D 空（别人的框架）：只检出别家 agent 框架标记，别的信号一概没有。"""
    d = tmp_path / "proj-d"
    (d / ".claude").mkdir(parents=True)
    (d / "CLAUDE.md").write_text("# claude\n", encoding="utf-8")
    return d


def _lay_skeleton(root: Path) -> Path:
    """铺最小骨架（方案 §5 第 3–4 步）：骨架配置 + 队列壳 + 台账壳 + **一道真门**。

    ★「只加文件」：不动对方任何既有文件（本函数只写新路径）。
    ★ 门必须是**能红**的（永远绿的门等于没有门）—— 判据在 `GATE_SRC`。
    """
    (root / "docs").mkdir(exist_ok=True)
    (root / "gates").mkdir(exist_ok=True)
    (root / "tools").mkdir(exist_ok=True)
    (root / "pipeline.toml").write_text(
        "[pipeline]\nname = 'demo'\n", encoding="utf-8")
    (root / "docs" / "workbacklog.toml").write_text(
        '[[cards]]\nid = "C1"\ntitle = "第一张卡"\nstatus = "pending"\n', encoding="utf-8")
    (root / "docs" / "traceability.toml").write_text(
        '[meta]\nversion = 1\n\n[entries]\n', encoding="utf-8")
    (root / "gates" / "last.json").write_text('{"ok": true}', encoding="utf-8")
    (root / "tools" / "wb_demo.py").write_text("# 骨架里的第一个工具\n", encoding="utf-8")
    (root / "data.txt").write_text("1\n2\n", encoding="utf-8")
    gate = root / "gates" / "check_size.py"
    gate.write_text(GATE_SRC, encoding="utf-8")
    return gate


def _run_gate(root: Path, gate: Path) -> int:
    """跑一次那道门（★ 子进程一律不弹窗）。"""
    done = subprocess.run(
        [sys.executable, "-X", "utf8", str(gate)], cwd=str(root),
        capture_output=True, text=True, encoding="utf-8", errors="replace", **NO_WINDOW,
    )
    return done.returncode


# ================================================================ ① 四类逐类：kind + 映射
@pytest.mark.parametrize("maker,kind", [
    (_mk_a, "A"), (_mk_b, "B"), (_mk_c, "C"), (_mk_d, "D"),
])
def test_four_kinds_and_hints(tmp_path: Path, maker, kind: str) -> None:
    """四类各一条：`kind` 判对，`mapping_hints` 就是该类那一份（不是空话、不是别人的）。"""
    d = maker(tmp_path)
    r = wt.probe(d)
    assert r["ok"] is True
    assert r["kind"] == kind, r
    assert r["mapping_hints"] == wt.MAPPING_HINTS[kind]
    assert r["mapping_hints"], "每类至少一条映射提示"
    assert all(isinstance(h, str) and h.strip() for h in r["mapping_hints"])


def test_probe_is_read_only(tmp_path: Path) -> None:
    """勘察器零写盘 —— 四类都过一遍，目录指纹一字不变（骨架铺完的 A 类也一样）。"""
    for maker in (_mk_a, _mk_b, _mk_c, _mk_d):
        d = maker(tmp_path)
        before = _fingerprint(d)
        wt.probe(d)
        assert _fingerprint(d) == before, f"{d.name} 被写过了"


def test_hints_are_kind_specific(tmp_path: Path) -> None:
    """四类的提示**互不相同** —— 否则「映射」这层等于没分（把 A 的提示给 C 就是假接上）。"""
    seen = {}
    for maker in (_mk_a, _mk_b, _mk_c, _mk_d):
        r = wt.probe(maker(tmp_path))
        seen[r["kind"]] = tuple(r["mapping_hints"])
    assert len(set(seen.values())) == 4, seen
    assert any("骨架" in h for h in seen["C"]), seen["C"]
    assert any("不落" in h or "只勘察" in h for h in seen["D"]), seen["D"]


# ================================================================ ② C 类：铺骨架 → 第一步验收
def test_c_class_skeleton_reclassifies_as_a(tmp_path: Path) -> None:
    """C 类铺完最小骨架 ⇒ 勘察器**认得出**（再判一次就是 A，不是还停在 C）。"""
    d = _mk_c(tmp_path)
    assert wt.probe(d)["kind"] == "C"
    _lay_skeleton(d)
    r = wt.probe(d)
    assert r["kind"] == "A", r


def test_c_class_first_acceptance_gate_really_runs_and_bites(tmp_path: Path) -> None:
    """第一步验收：那道门**退 0**，塞进坏数据后**退 1** —— 证明它真跑、真会咬。"""
    d = _mk_c(tmp_path)
    gate = _lay_skeleton(d)
    assert _run_gate(d, gate) == 0, "干净数据上门必须是绿（否则门本身坏了）"
    (d / "data.txt").write_text("1\n2\n3\n4\n", encoding="utf-8")
    assert _run_gate(d, gate) == 1, "坏数据上门必须红（永远绿的门 = 没门）"


def test_c_class_evidence_is_machine_checkable_in_skeleton(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """第一步验收的证据面：`file:` 在骨架里**换棵树也能求值**（真文件 True / 假路径 False）。"""
    d = _mk_c(tmp_path)
    _lay_skeleton(d)
    monkeypatch.setattr(ap, "ROOT", d)
    assert ap.eval_assertion("file:demo/wb_demo.py")[0] is False   # 注入：路径不存在
    assert ap.eval_assertion("file:tools/wb_demo.py")[0] is True
    assert ap.eval_assertion("file:data.txt")[0] is True


def test_skeleton_never_touches_the_real_repo(tmp_path: Path) -> None:
    """★ 边界：骨架只落在 `tmp_path` 里 —— 真实仓库根不是它、也不在它下面。"""
    d = _mk_c(tmp_path)
    _lay_skeleton(d)
    assert d.is_relative_to(tmp_path)
    assert not ROOT.resolve().is_relative_to(d.resolve())
    assert (d / "pipeline.toml").is_file()
