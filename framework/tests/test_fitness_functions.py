"""G1 / G3 / G5 的用例 —— 架构级 fitness + 多样性不可削减 + 可转换性分类。

★ 反例钉子：G1（分层倒流）/ G3（砍门无论证）/ G5（缺回滚）各一，造错必红。
"""

from __future__ import annotations

from pathlib import Path

from framework.fitness import (
    ArchitectureFitnessInput,
    ControlSurface,
    DirectoryDiscipline,
    DiversityChange,
    ImportEdge,
    LayerSpec,
    architecture_fitness,
    dangling_references,
    directory_discipline,
    diversity_not_reduced,
    layered_dependencies_no_backflow,
    no_project_specific_imports,
)
from framework.migration import (
    Convertibility,
    FRAMEWORK_MIGRATION,
    MigrationItem,
    checklist_to_dict,
    framework_migration_report,
    validate_checklist,
)


# ===========================================================================
# G1 · 架构级 fitness function 成体系（四条，每条一条钉子）
# ===========================================================================

def test_g1_layered_no_backflow_green():
    layers = (
        LayerSpec("core", frozenset({"framework"})),
        LayerSpec("cli", frozenset({"cli"})),
    )
    edges = [ImportEdge("framework", "json", "framework/x.py::json")]
    assert layered_dependencies_no_backflow(layers, edges) == []


def test_g1_layered_backflow_is_red():
    """★ 反例钉子：core import cli ⇒ 倒流 ⇒ 红。"""
    layers = (
        LayerSpec("core", frozenset({"framework"})),
        LayerSpec("cli", frozenset({"cli"})),
    )
    edges = [ImportEdge("framework", "cli", "framework/x.py::import cli")]
    out = layered_dependencies_no_backflow(layers, edges)
    assert len(out) == 1
    assert out[0].constraint == "G1·分层倒流"


def test_g1_no_project_imports_green(tmp_path: Path):
    (tmp_path / "ok.py").write_text("import json\n", encoding="utf-8")
    assert no_project_specific_imports(tmp_path, ("evil_project",)) == []


def test_g1_project_import_is_red(tmp_path: Path):
    """★ 反例钉子：框架 import 项目专有包 ⇒ 红。"""
    (tmp_path / "bad.py").write_text("import evil_project\n", encoding="utf-8")
    out = no_project_specific_imports(tmp_path, ("evil_project",))
    assert len(out) == 1
    assert "evil_project" in out[0].detail


def test_g1_from_import_is_red(tmp_path: Path):
    (tmp_path / "bad2.py").write_text("from evil_project import thing\n", encoding="utf-8")
    assert len(no_project_specific_imports(tmp_path, ("evil_project",))) == 1


def test_g1_dangling_references_green(tmp_path: Path):
    f = tmp_path / "ledger.toml"
    f.write_text("x = 1\n", encoding="utf-8")
    assert dangling_references([("ledger::e[0]", f)]) == []


def test_g1_dangling_references_is_red(tmp_path: Path):
    """★ 反例钉子：指向不存在的路径 ⇒ 红。"""
    out = dangling_references([("ledger::e[3]", tmp_path / "nope.toml")])
    assert len(out) == 1
    assert out[0].constraint == "G1·悬空引用"


def test_g1_directory_discipline_green(tmp_path: Path):
    (tmp_path / "PIPELINE.md").write_text("x\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    assert directory_discipline(tmp_path, DirectoryDiscipline(must_exist=("PIPELINE.md", "src"))) == []


def test_g1_directory_discipline_is_red(tmp_path: Path):
    """★ 反例钉子：期望缺失 / 不许存在的出现 ⇒ 红。"""
    (tmp_path / "junk").mkdir()
    out = directory_discipline(tmp_path, DirectoryDiscipline(must_exist=("PIPELINE.md",), must_not_exist=("junk",)))
    assert len(out) == 2


def test_g1_architecture_fitness_combines(tmp_path: Path):
    layers = (LayerSpec("core", frozenset({"framework"})), LayerSpec("cli", frozenset({"cli"})))
    inp = ArchitectureFitnessInput(
        layers=layers, import_edges=[ImportEdge("framework", "cli", "x::cli")],
        framework_dir=tmp_path, forbidden_top_levels=("evil",),
        evidence_references=[("ledger::e[0]", tmp_path / "nope.toml")],
        discipline_root=tmp_path, discipline=DirectoryDiscipline(must_exist=("PIPELINE.md",)),
    )
    out = architecture_fitness(inp)
    assert {"G1·分层倒流", "G1·悬空引用", "G1·目录纪律"} <= {v.constraint for v in out}


# ===========================================================================
# G3 · 多样性不许被削减
# ===========================================================================

def test_g3_no_reduction_is_green():
    b = ControlSurface(5, 3, 4)
    assert diversity_not_reduced(DiversityChange(b, ControlSurface(5, 3, 4), justification=None)) == []


def test_g3_increase_is_green():
    assert diversity_not_reduced(DiversityChange(ControlSurface(5, 3, 4), ControlSurface(6, 3, 4), justification=None)) == []


def test_g3_reduction_without_justification_is_red():
    """★ 反例钉子：砍门且无显式论证 ⇒ 红（依据 [2510.20041]）。"""
    out = diversity_not_reduced(DiversityChange(ControlSurface(5, 3, 4), ControlSurface(4, 3, 4), justification=None))
    assert len(out) == 1
    assert out[0].constraint == "G3·多样性削减"
    assert "2510.20041" in out[0].detail


def test_g3_reduction_with_justification_is_green():
    out = diversity_not_reduced(DiversityChange(
        ControlSurface(5, 3, 4), ControlSurface(4, 3, 4),
        justification="并行度提到 8，这道门被合并（主控 2026-10-03 批）",
    ))
    assert out == []


def test_g3_fallback_reduction_is_red():
    out = diversity_not_reduced(DiversityChange(ControlSurface(5, 3, 4), ControlSurface(5, 2, 4), justification=None))
    assert len(out) == 1 and "兜底" in out[0].detail


# ===========================================================================
# G5 · 可转换性分类 + 回滚手段
# ===========================================================================

def test_g5_framework_migration_is_valid():
    report = framework_migration_report()
    assert report["ok"] is True, f"框架迁移清单有违规：{report['violations']}"
    assert len(report["items"]) == len(FRAMEWORK_MIGRATION)


def test_g5_reversible_without_rollback_is_red():
    """★ 反例钉子：可逆项缺回滚手段 ⇒ 红。"""
    out = validate_checklist([MigrationItem("搬目录", Convertibility.REVERSIBLE, rollback="")])
    assert len(out) == 1 and "缺回滚手段" in out[0].detail


def test_g5_one_shot_without_rollback_is_red():
    assert len(validate_checklist([MigrationItem("抽空", Convertibility.ONE_SHOT, rollback="  ")])) == 1


def test_g5_irreversible_empty_rollback_is_red():
    """★ 反例钉子：不可逆项回滚空着（没想过）⇒ 红。"""
    out = validate_checklist([MigrationItem("删原件", Convertibility.IRREVERSIBLE, rollback="")])
    assert len(out) == 1 and "显式写「无」" in out[0].detail


def test_g5_irreversible_with_other_rollback_is_red():
    """★ 反例钉子：不可逆项写了别的回滚（分类标错）⇒ 红。"""
    out = validate_checklist([MigrationItem("删原件", Convertibility.IRREVERSIBLE, rollback="git revert")])
    assert len(out) == 1 and "分类标错" in out[0].detail


def test_g5_irreversible_with_explicit_none_is_green():
    assert validate_checklist([MigrationItem("删原件", Convertibility.IRREVERSIBLE, rollback="无")]) == []


def test_g5_unnamed_item_is_red():
    assert len(validate_checklist([MigrationItem("  ", Convertibility.REVERSIBLE, rollback="搬回")])) == 1


def test_g5_checklist_to_dict_shape():
    d = checklist_to_dict([MigrationItem("x", Convertibility.REVERSIBLE, rollback="搬回", notes="n")])
    assert set(d) == {"items", "violations", "ok"} and d["ok"] is True
