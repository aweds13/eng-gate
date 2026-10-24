r"""TIA（测试影响分析）钉子 —— 映射格式 / pinned 兜底 / 过期失效 / fail-closed。

卡 E2（T-AG444）。判据方向与 `run_gates.select_tests` 同一条：**宁可多跑不许漏跑** ——
凡是「判不出」的分支一律退回全量，绝不用"少跑几个"换一句好看的数字。

这里只测**纯逻辑**（映射解析 / 选测 / 兜底 / 失效判定），不跑真 pytest、不读真 `gates/tia.json`：
真实读数由 `python -X utf8 scripts/tia_map.py --build` 单独产出，测试用 `tmp_path` 造映射。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, relpath: str):
    target = ROOT / relpath
    spec = importlib.util.spec_from_file_location(name, target)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_tree(tmp_path: Path, *relpaths: str) -> Path:
    """在临时根里造出这些（空）文件 —— 选测只判"文件真存在吗"。"""
    for rel in relpaths:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")
    return tmp_path


def test_payload_shape_and_roundtrip() -> None:
    """映射格式：`{nodeid: [被覆盖的源文件…], generated_at, rev}`，能被原样读回。"""
    tia = _load("tia_map_shape", "scripts/tia_map.py")
    payload = tia.make_payload(
        {"tests/test_a.py::test_one": ["src/timeflow/a.py"]},
        rev="abc1234",
        generated_at="2026-10-24T00:00:00",
    )
    assert payload["rev"] == "abc1234"
    assert payload["generated_at"] == "2026-10-24T00:00:00"
    assert payload["tests/test_a.py::test_one"] == ["src/timeflow/a.py"]
    assert tia.mapping_from_payload(payload) == {
        "tests/test_a.py::test_one": ["src/timeflow/a.py"]
    }
    assert tia.test_count(payload) == 1


def test_bad_payload_is_rejected() -> None:
    """坏映射不许静默当"没有映射"—— 缺 rev / 值不是字符串列表都得响。"""
    tia = _load("tia_map_bad", "scripts/tia_map.py")
    with pytest.raises(ValueError):
        tia.mapping_from_payload({"tests/test_a.py::test_one": ["src/a.py"]})  # 缺 rev
    with pytest.raises(ValueError):
        tia.mapping_from_payload({"rev": "abc", "generated_at": "x", "t::x": "src/a.py"})
    with pytest.raises(ValueError):
        tia.mapping_from_payload({"rev": "abc", "generated_at": "x", "t::x": [1, 2]})


def test_select_picks_only_covering_tests(tmp_path: Path) -> None:
    """按覆盖映射选：只有覆盖了被改文件的用例进清单（不按目录猜）。"""
    tia = _load("tia_map_select", "scripts/tia_map.py")
    root = _make_tree(tmp_path, "src/timeflow/a.py", "src/timeflow/b.py")
    mapping = {
        "tests/test_a.py::test_one": ["src/timeflow/a.py"],
        "tests/test_b.py::test_two": ["src/timeflow/b.py"],
    }
    plan = tia.select(["src/timeflow/a.py"], mapping, root=root, pinned=())
    assert not plan.full
    assert "tests/test_a.py::test_one" in plan.tests
    assert "tests/test_b.py::test_two" not in plan.tests


def test_pinned_always_present(tmp_path: Path) -> None:
    """pinned 兜底：判据钉子每次都跑（本卡不许为了让数字好看缩小这一集）。"""
    tia = _load("tia_map_pinned", "scripts/tia_map.py")
    root = _make_tree(
        tmp_path,
        "src/timeflow/a.py",
        "tests/test_a.py",
        "tests/test_wb_review.py",
        "tests/test_card_specs_tracked.py",
        "tests/test_check_skills.py",
        "tests/test_run_gates_profiles.py",
        "scripts/test_check_layers.py",
    )
    mapping = {"tests/test_a.py::test_one": ["src/timeflow/a.py"]}
    plan = tia.select(["src/timeflow/a.py"], mapping, root=root)
    # 卡的钉子清单逐字保留 5 条（不许删条目来缩小这一集）；`tests/test_check_layers.py`
    # 在本仓落在 `scripts/test_check_layers.py`，用别名换真文件（不是删掉）。
    assert len(tia.PINNED_TESTS) == 5
    assert "tests/test_check_layers.py" in tia.PINNED_TESTS
    assert "scripts/test_check_layers.py" in plan.tests
    for pinned in tia.resolved_pinned(root):
        assert pinned in plan.tests, pinned
    # 该文件里唯一的用例被选中 ⇒ 收成文件名（两种写法都表示"这条用例会跑"）
    assert "tests/test_a.py" in plan.tests or "tests/test_a.py::test_one" in plan.tests


def test_uncovered_file_falls_back_to_full(tmp_path: Path) -> None:
    """判不出 ⇒ 全量：没人覆盖的文件不许"当成没影响"。"""
    tia = _load("tia_map_full", "scripts/tia_map.py")
    root = _make_tree(tmp_path, "src/timeflow/a.py", "src/timeflow/nobody.py")
    mapping = {"tests/test_a.py::test_one": ["src/timeflow/a.py"]}
    plan = tia.select(["src/timeflow/a.py", "src/timeflow/nobody.py"], mapping, root=root)
    assert plan.full
    assert "全量" in plan.note


def test_changed_test_file_runs_itself(tmp_path: Path) -> None:
    """改过的测试文件自己必定在清单里（本卡新增/改过的测试文件也算 pinned）。"""
    tia = _load("tia_map_selftest", "scripts/tia_map.py")
    root = _make_tree(tmp_path, "tests/test_new.py")
    plan = tia.select(["tests/test_new.py"], {}, root=root, pinned=())
    assert plan.tests == ("tests/test_new.py",)
    assert not plan.full


def test_last_failed_is_pinned(tmp_path: Path) -> None:
    """上次失败过的用例当 pinned 兜底（缓存里有就带上，不猜）。"""
    tia = _load("tia_map_lastfail", "scripts/tia_map.py")
    root = _make_tree(tmp_path, "src/timeflow/a.py", "tests/test_a.py",
                      "tests/test_flaky.py")
    mapping = {"tests/test_a.py::test_one": ["src/timeflow/a.py"]}
    plan = tia.select(
        ["src/timeflow/a.py"], mapping, root=root, pinned=(),
        last_failed=("tests/test_flaky.py::test_bad",),
    )
    assert "tests/test_flaky.py::test_bad" in plan.tests


def test_collapses_to_file_when_all_its_tests_selected(tmp_path: Path) -> None:
    """一个文件里的用例全被选中 ⇒ 收成文件名（命令行更短，语义等价）。"""
    tia = _load("tia_map_collapse", "scripts/tia_map.py")
    root = _make_tree(tmp_path, "src/timeflow/a.py", "tests/test_a.py")
    mapping = {
        "tests/test_a.py::test_one": ["src/timeflow/a.py"],
        "tests/test_a.py::test_two": ["src/timeflow/a.py"],
    }
    plan = tia.select(["src/timeflow/a.py"], mapping, root=root, pinned=())
    assert plan.tests == ("tests/test_a.py",)


def test_docs_only_change_falls_back_to_full(tmp_path: Path) -> None:
    """只有文档/记账改动 ⇒ 判不出（用例也读文档）⇒ 全量，不许裁成空集。"""
    tia = _load("tia_map_docs", "scripts/tia_map.py")
    root = _make_tree(tmp_path, "src/timeflow/a.py")
    plan = tia.select(["docs/changelog.md", "复盘/x.md"], {}, root=root, pinned=())
    assert plan.full
    assert "全量" in plan.note


def test_stale_mapping_falls_back_to_full(tmp_path: Path) -> None:
    """映射过期 ⇒「映射过期，退回全量」并真回退（fail closed）。"""
    tia = _load("tia_map_stale", "scripts/tia_map.py")
    root = _make_tree(tmp_path, "src/timeflow/a.py")
    mapping = {"tests/test_a.py::test_one": ["src/timeflow/a.py"]}
    plan = tia.plan(
        ["src/timeflow/a.py"], root=root, payload=tia.make_payload(mapping),
        fresh=lambda _rev, _root: False,
    )
    assert plan.full
    assert "映射过期" in plan.note


def test_missing_mapping_falls_back_to_full(tmp_path: Path) -> None:
    """没有映射文件 ⇒ 全量（不是"没影响"）。"""
    tia = _load("tia_map_missing", "scripts/tia_map.py")
    root = _make_tree(tmp_path, "src/timeflow/a.py")
    plan = tia.plan(["src/timeflow/a.py"], root=root, payload=None,
                    fresh=lambda _rev, _root: True)
    assert plan.full
    assert "全量" in plan.note


def test_no_changes_falls_back_to_full(tmp_path: Path) -> None:
    """空改动也退回全量 —— 空集绝不能伪装成"这一层跑过了"。"""
    tia = _load("tia_map_empty", "scripts/tia_map.py")
    root = _make_tree(tmp_path, "src/timeflow/a.py")
    plan = tia.plan([], root=root, payload=tia.make_payload({}),
                    fresh=lambda _rev, _root: True)
    assert plan.full


def test_load_mapping_reads_file(tmp_path: Path) -> None:
    """`--select` 用的就是 `gates/tia.json` 这一份（路径可注入，测试不碰真文件）。"""
    tia = _load("tia_map_io", "scripts/tia_map.py")
    path = tmp_path / "tia.json"
    payload = tia.make_payload({"tests/test_a.py::test_one": ["src/timeflow/a.py"]},
                               rev="deadbee")
    tia.save_mapping(payload, path)
    assert json.loads(path.read_text(encoding="utf-8"))["rev"] == "deadbee"
    assert tia.load_mapping(path)["tests/test_a.py::test_one"] == ["src/timeflow/a.py"]
    assert tia.load_mapping(tmp_path / "nope.json") is None


def test_run_gates_pytest_gate_honours_tf_tia(monkeypatch, tmp_path: Path) -> None:
    """`scripts/run_gates.py` 的 pytest 门：给了选集就接在 pytest 命令后面。"""
    run_gates = _load("run_gates_tia_under_test", "scripts/run_gates.py")
    monkeypatch.setattr(run_gates, "xdist_available", lambda: False)
    plain = run_gates.resolve_cmd("pytest", {}, serial=True)
    assert plain == [run_gates.PY, "-X", "utf8", "-m", "pytest"]
    picked = run_gates.resolve_cmd(
        "pytest", {}, serial=True, pytest_args=["tests/test_a.py"]
    )
    assert picked == [*plain, "tests/test_a.py"]
    assert run_gates.tia_payload_fields(plan=_FakePlan(), enabled=False) == {}
    fields = run_gates.tia_payload_fields(plan=_FakePlan(), enabled=True)
    assert fields["tests_run"] == 2
    assert fields["tests_total"] == 10


class _FakePlan:
    """最小的 TiaPlan 替身（不 import tia_map 就能测 run_gates 那半边）。"""

    tests = ("tests/test_a.py", "tests/test_b.py")
    full = False
    total = 10
    note = "选中 2 个用例"

    @property
    def run_count(self) -> int:
        return self.total if self.full else len(self.tests)
