"""钉子测试：`tools/wb_flow.py`（卡 164 / T-G264）。

判据：
- 合成一份带新增卡与 done 卡的夹具 ⇒ 四个数必须对（证明它看得到东西）；
- `why` 字段缺 ⇒ 标 `未标`（不猜来源）；
- 只读：不改 workbacklog。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_flow  # noqa: E402


def test_flow_snapshot_reads_the_four_numbers(tmp_path: Path, monkeypatch) -> None:
    """★★ 合成夹具：新增 2 卡（1 个带 why、1 个不带）+ 1 卡 done ⇒ 四个数必须对。"""
    backlog = tmp_path / "docs" / "workbacklog.toml"
    backlog.parent.mkdir(parents=True)
    backlog.write_text(
        '[base]\nreviewed = "x"\n'
        '[[cards]]\nid = "200"\ntask = "T-G300"\ntitle = "x"\ntree = ""\nspec = "s.md"\n'
        'files = []\ndepends = []\nrisk = "low"\nstatus = "pending"\n'
        'why = "坑（现场咬出来的）"\n'
        '[[cards]]\nid = "201"\ntask = "T-G301"\ntitle = "y"\ntree = ""\nspec = "s.md"\n'
        'files = []\ndepends = []\nrisk = "low"\nstatus = "pending"\n'
        '[[cards]]\nid = "199"\ntask = "T-G299"\ntitle = "z"\ntree = ""\nspec = "s.md"\n'
        'files = []\ndepends = []\nrisk = "low"\nstatus = "done"\n',
        encoding="utf-8")
    monkeypatch.setattr(wb_flow, "BACKLOG", backlog)
    # 桩 git diff：200/201 是新增，199 标成 done
    monkeypatch.setattr(wb_flow, "_git_diff_ids",
                        lambda since: ({"200", "201"}, {"199"}))
    snap = wb_flow.flow_snapshot()
    assert snap["arrived"] == 2
    assert snap["left"] == 1
    assert snap["wip"] == 2                     # 200/201 pending
    assert snap["by_source"]["坑（现场咬出来的）"] == 1
    assert snap["by_source"]["未标"] == 1       # 201 没 why
    # 到达 2、离开 1 ⇒ abs(2-1)=1 <= max(1, 1//10)=1 ⇒ 平台
    assert snap["verdict"] == "平台"


def test_missing_why_is_untagged_not_guessed(tmp_path: Path, monkeypatch) -> None:
    """★ `why` 缺 ⇒ `未标`，不猜来源。"""
    backlog = tmp_path / "docs" / "workbacklog.toml"
    backlog.parent.mkdir(parents=True)
    backlog.write_text(
        '[base]\nreviewed = "x"\n'
        '[[cards]]\nid = "300"\ntask = "T-G400"\ntitle = "x"\ntree = ""\nspec = "s.md"\n'
        'files = []\ndepends = []\nrisk = "low"\nstatus = "pending"\n',
        encoding="utf-8")
    monkeypatch.setattr(wb_flow, "BACKLOG", backlog)
    monkeypatch.setattr(wb_flow, "_git_diff_ids", lambda since: ({"300"}, set()))
    snap = wb_flow.flow_snapshot()
    assert snap["by_source"]["未标"] == 1
    for src in wb_flow.SOURCES:
        assert snap["by_source"][src] == 0


def test_convergence_verdict_when_arrived_below_left(monkeypatch, tmp_path: Path) -> None:
    """★ 到达 < 离开 ⇒ 收敛中（这是「会收敛」的机器证据）。"""
    backlog = tmp_path / "docs" / "workbacklog.toml"
    backlog.parent.mkdir(parents=True)
    backlog.write_text("[base]\nreviewed = \"x\"\n", encoding="utf-8")
    monkeypatch.setattr(wb_flow, "BACKLOG", backlog)
    monkeypatch.setattr(wb_flow, "_git_diff_ids", lambda since: ({"1"}, {"1", "2", "3"}))
    snap = wb_flow.flow_snapshot()
    assert snap["verdict"] == "收敛中"
