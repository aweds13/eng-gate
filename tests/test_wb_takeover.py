"""`tools/wb_takeover.py`（只读勘察器，卡 A300）的测试 —— A/B/C/D 四类逐类断言。

为什么要有测试：勘察器的全部价值在「**类别判对**」——判错类，后面的映射表与限制清单
就全套错对象。这里用 `tmp_path` 造四种形态，逐类断言 `kind`；再钉两条边界：

- 目录不存在 ⇒ `ok: false` 且退出码非 0（唯一允许非零的情形）；
- 勘察是**只读**的：跑完目录里一个多余字节都不许有（含 `__pycache__` 也不许生在
  被勘察目录里 —— 勘察器只用 pathlib 读，不 import 目标目录的任何东西）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_takeover as wt  # noqa: E402


def _tree(root: Path) -> set[str]:
    """目录里所有相对路径（文件 + 目录），用于「只读」断言。"""
    return {str(p.relative_to(root)) for p in root.rglob("*")}


def _mk_a(tmp_path: Path) -> Path:
    """A 类：已有完整管线 —— 骨架配置 harness.toml + 本仓三件套。"""
    d = tmp_path / "proj-a"
    (d / "docs").mkdir(parents=True)
    (d / "gates").mkdir()
    (d / "tools").mkdir()
    (d / "harness.toml").write_text("[harness]\n", encoding="utf-8")
    (d / "docs" / "workbacklog.toml").write_text("[cards]\n", encoding="utf-8")
    (d / "gates" / "last.json").write_text("{}", encoding="utf-8")
    (d / "tools" / "wb_demo.py").write_text("# demo\n", encoding="utf-8")
    return d


def _mk_b(tmp_path: Path) -> Path:
    """B 类：有测试无门禁 —— tests/ + pyproject.toml + CI，无管线配置。"""
    d = tmp_path / "proj-b"
    (d / "tests").mkdir(parents=True)
    (d / ".github" / "workflows").mkdir(parents=True)
    (d / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (d / ".github" / "workflows" / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    return d


def _mk_c(tmp_path: Path) -> Path:
    """C 类：裸仓 —— 只有 src/，无测试、无 CI、无管线。"""
    d = tmp_path / "proj-c"
    (d / "src").mkdir(parents=True)
    (d / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    return d


def _mk_d(tmp_path: Path) -> Path:
    """D 类：别人的框架 —— 有 CLAUDE.md + .claude/，别的信号也压不过它。"""
    d = tmp_path / "proj-d"
    (d / ".claude").mkdir(parents=True)
    (d / "tests").mkdir()
    (d / "CLAUDE.md").write_text("# claude\n", encoding="utf-8")
    (d / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    return d


def test_classify_a(tmp_path: Path) -> None:
    d = _mk_a(tmp_path)
    before = _tree(d)
    r = wt.probe(d)
    assert r["ok"] is True
    assert r["kind"] == "A"
    assert _tree(d) == before, "勘察器不许写盘"


def test_classify_a_by_trio_only(tmp_path: Path) -> None:
    """没有 pipeline.toml/harness.toml，但三件套齐 ⇒ 仍是 A（本仓形态）。"""
    d = tmp_path / "proj-a2"
    (d / "docs").mkdir(parents=True)
    (d / "gates").mkdir()
    (d / "tools").mkdir()
    (d / "docs" / "workbacklog.toml").write_text("[cards]\n", encoding="utf-8")
    (d / "gates" / "last.json").write_text("{}", encoding="utf-8")
    (d / "tools" / "wb_x.py").write_text("# x\n", encoding="utf-8")
    assert wt.probe(d)["kind"] == "A"


def test_classify_b(tmp_path: Path) -> None:
    r = wt.probe(_mk_b(tmp_path))
    assert r["kind"] == "B"


def test_classify_c(tmp_path: Path) -> None:
    r = wt.probe(_mk_c(tmp_path))
    assert r["kind"] == "C"


def test_classify_c_empty_dir(tmp_path: Path) -> None:
    """空目录也是裸仓：什么都没有 ⇒ 要铺骨架。"""
    d = tmp_path / "proj-empty"
    d.mkdir()
    assert wt.probe(d)["kind"] == "C"


def test_classify_d(tmp_path: Path) -> None:
    """别人的框架压过测试信号：有 tests/ 也判 D（先认框架，再谈借测试）。"""
    r = wt.probe(_mk_d(tmp_path))
    assert r["kind"] == "D"
    foreign = [x for x in r["readings"] if x["name"] == "foreign_framework"]
    assert foreign and foreign[0]["ok"] is True


def test_a_beats_d(tmp_path: Path) -> None:
    """自己的管线最优先：既有 harness.toml 又有 CLAUDE.md ⇒ A。"""
    d = _mk_d(tmp_path)
    (d / "harness.toml").write_text("[harness]\n", encoding="utf-8")
    assert wt.probe(d)["kind"] == "A"


def test_mapping_hints_match_kind(tmp_path: Path) -> None:
    for mk, kind in [(_mk_a, "A"), (_mk_b, "B"), (_mk_c, "C"), (_mk_d, "D")]:
        r = wt.probe(mk(tmp_path))
        assert r["mapping_hints"] == wt.MAPPING_HINTS[kind]
        assert r["mapping_hints"], "每类至少一条映射提示"


def test_missing_dir_json_and_exit_code(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "no-such-dir"
    rc = wt.main(["--root", str(missing), "--json"])
    assert rc != 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False


def test_existing_dir_exit_zero(tmp_path: Path, capsys) -> None:
    """判哪类都退 0 —— 非零只留给「目录不存在」。"""
    for mk in (_mk_a, _mk_b, _mk_c, _mk_d):
        rc = wt.main(["--root", str(mk(tmp_path)), "--json"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is True
        assert out["kind"] in ("A", "B", "C", "D")


def test_strict_refuses_empty_dir(tmp_path: Path) -> None:
    """★ A311：空目录判成 C 不算「判出来了」⇒ --strict 退 2 并点名缺什么。"""
    assert wt.main(["--root", str(tmp_path), "--strict"]) == 2


def test_strict_accepts_repo_with_tests(tmp_path: Path) -> None:
    """★ A311：有 tests/ 就算有正证据（B 类），strict 不该误伤。"""
    (tmp_path / "tests").mkdir()
    assert wt.main(["--root", str(tmp_path), "--strict"]) == 0


def test_strict_json_reports_problems(tmp_path: Path, capsys) -> None:
    """★ A311：JSON 模式下也要带 strict_ok / strict_problems，脚本才判得出来。"""
    assert wt.main(["--root", str(tmp_path), "--strict", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["strict_ok"] is False
    assert payload["strict_problems"]
