"""卡 A327 · T-AG442：改动面 → **必需档** 的映射表钉子。

这张表是提交闸与门禁**共用的唯一一份**（`gates/defs/domains.py`）。这里钉三类语义：

1. 每一行前缀都按要求映射（改 `src/` 要 product、改 `skills/` 只要 audit …）；
2. 多文件取**并集**；
3. 判不出 / 空清单 ⇒ **全量**（fail closed，宁可多跑）。
"""

from __future__ import annotations

import pytest

from gates.defs import domains


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/jelly_ware/app.py", {"lang", "product"}),
        ("examples/demo.py", {"lang", "product"}),
        ("harness/run.sh", {"lang", "product"}),
        ("tools/wb_land.py", {"lang", "audit"}),
        ("scripts/run_gates.py", {"lang", "audit"}),
        ("tests/test_x.py", {"lang", "audit"}),
        ("gates/defs/domains.py", {"lang", "audit"}),
        ("docs/changelog.md", {"audit"}),
        ("复盘/卡/卡A327-按域跑必需门.md", {"audit"}),
        ("skills/pipe-gate/SKILL.md", {"audit"}),
        ("README.md", {"audit"}),
    ],
)
def test_each_row_maps_as_declared(path: str, expected: set[str]) -> None:
    assert domains.required_profiles([path]) == frozenset(expected)


def test_union_of_several_paths() -> None:
    need = domains.required_profiles(["src/a.py", "docs/b.md", "tools/c.py"])
    assert need == domains.ALL_PROFILES


def test_unknown_path_falls_back_to_full() -> None:
    """判不出档 ⇒ 全量（不许猜「大概不用跑 product」）。"""
    assert domains.required_profiles(["weird/blob.bin"]) == domains.ALL_PROFILES


def test_empty_change_set_is_full() -> None:
    """没有任何改动证据 ⇒ 全量（空计划不许绿灯）。"""
    assert domains.required_profiles([]) == domains.ALL_PROFILES


def test_windows_separators_and_leading_dot_slash_are_normalised() -> None:
    assert domains.required_profiles(["./tools\\x.py"]) == frozenset({"lang", "audit"})


def test_explain_says_what_is_needed() -> None:
    assert "audit" in domains.explain(["skills/pipe-gate/SKILL.md"])
    assert "全量" in domains.explain(["weird/blob.bin"])
