"""动线自查表的机器闸（T-G39；用户 2026-09-23 点头"加"）。

`docs/contracts/flows.md` 里那张「4 条动线 × 4 条贯通验收」的表，是**文档层**的"哪些真跑过"。
T-G23 逐条回填过（每条都带证据指针），但它是文档：以后有人把某格改回空框、或加一行只写 ✅
却不说拿什么验的，**没人拦**。这一条就是那道闸 —— 几百毫秒，读一个文件。

口径（宽严都写清楚，免得以后有人觉得太紧就把它删了）：
- 表里每个格子只能是 `✅` 或 `—`：**空框 / `☐` / 其它符号一律红**（"没验"不许混在"验过"里）；
- 每一行有几个 ✅，下面「逐条证据」表里就得有**同样多条**同编号的证据行；
- 每条证据得**指得着东西**（含 `tests/` / `tools/` / `复盘/` 这类指针）—— 光写"已验"不算证据；
- 表外那段「仍然没做到的」是**故意留的**（FLOW-4 执行侧不自动填，属产品判断）→ 不拦它。

★ 按"上了闸就得证明它咬得住"的规矩：`test_synthetic_holes_are_caught` 用**合成表**验三条判定
（空框 / ✅ 没证据 / 证据指不着东西），真仓库那份用 `test_real_repo_is_clean`。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FLOWS = ROOT / "docs" / "contracts" / "flows.md"

_MARK = {"✅", "—"}
_FLOW = re.compile(r"^FLOW-\d+")
_POINTERS = ("tests/", "tools/", "复盘/", "render", "DOM")


def _scan(text: str) -> tuple[list[list[str]], list[list[str]], list[str]]:
    """纯函数：喂一段 markdown，返回（动线表、证据表、问题清单）。"""
    claims: list[list[str]] = []
    evidence: list[list[str]] = []
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells or not _FLOW.match(cells[0]):
            continue
        if len(cells) == 5:
            claims.append(cells)
        elif len(cells) == 2:
            evidence.append(cells)

    problems: list[str] = []
    per_flow: dict[str, int] = {}
    for cells in evidence:
        flow = _FLOW.match(cells[0])
        assert flow is not None
        per_flow[flow.group(0)] = per_flow.get(flow.group(0), 0) + 1
        if not any(k in cells[1] for k in _POINTERS):
            problems.append(f"证据指不着东西：{cells[0]} → {cells[1][:60]}")
    for cells in claims:
        flow = _FLOW.match(cells[0])
        assert flow is not None
        marks = cells[1:]
        for i, mark in enumerate(marks, start=1):
            if mark not in _MARK:
                problems.append(f"{cells[0]} 第 {i} 格是 {mark!r}（只允许 ✅ 或 —，不许空框）")
        claimed = sum(1 for m in marks if m == "✅")
        got = per_flow.get(flow.group(0), 0)
        if claimed != got:
            problems.append(f"{flow.group(0)}：表里写了 {claimed} 个 ✅，证据表只有 {got} 条")
    return claims, evidence, problems


def test_synthetic_holes_are_caught() -> None:
    """★ 证明这道闸咬得住（零件层）：空框 / ✅ 没证据 / 证据指不着东西，三条都要被抓出来。"""
    text = """
| 动线 | 第1条 | 第2条 | 第3条 | 第4条 |
|---|---|---|---|---|
| FLOW-1 干一件事 | ✅ | ☐ | ✅ | — |
| FLOW-2 逾期 | ✅ | — | — | — |

| 动线·第几条 | 实测方式 |
|---|---|
| FLOW-1 ① 开工 | `tests/test_a.py` |
| FLOW-1 ② 收工 | 已验过（没有指针，应当被抓） |
| FLOW-2 ① 逾期 | `tools/live.py` |
"""
    _claims, _evidence, problems = _scan(text)
    joined = "\n".join(problems)
    assert "第 2 格是 '☐'" in joined, joined
    # FLOW-1 表里 2 个 ✅、证据 2 条 → 数量对上，但其中一条没有指针 → 必须被抓
    assert "证据指不着东西" in joined, joined
    # 反证：合成数据里 FLOW-2 的 ✅ 与证据条数是对上的（不该报数量问题）
    assert "FLOW-2：表里写了" not in joined, joined


def test_synthetic_missing_evidence_is_counted() -> None:
    """再补一个：✅ 比证据多 → 报出来（这是最常见的"嘴上验过"）。"""
    text = """
| FLOW-1 干一件事 | ✅ | ✅ | — | — |

| FLOW-1 ① 开工 | `tests/test_a.py` |
"""
    _claims, _evidence, problems = _scan(text)
    assert any("FLOW-1：表里写了 2 个 ✅，证据表只有 1 条" in p for p in problems), problems


def test_real_tables_are_parsable() -> None:
    """真仓库那份：表还在、还长得像表（换写法时这里先红，而不是让上面那条莫名红）。"""
    claims, evidence, _ = _scan(FLOWS.read_text(encoding="utf-8"))
    assert len(claims) == 4, f"动线表应有 4 条动线，实际 {len(claims)} 条（表被改坏了？）"
    assert len(evidence) >= 8, f"证据表太短（{len(evidence)} 行），像是被删过"


def test_real_repo_is_clean() -> None:
    """★ 这一条就是门禁里的那道闸：真仓库现在没有洞（空框 / ✅ 没证据 / 证据没指针）。"""
    _, _, problems = _scan(FLOWS.read_text(encoding="utf-8"))
    assert not problems, "动线自查表有洞：\n  - " + "\n  - ".join(problems)


@pytest.mark.parametrize("flow", ["FLOW-1", "FLOW-2", "FLOW-3", "FLOW-4"])
def test_each_flow_evidence_is_numbered_continuously(flow: str) -> None:
    """证据行的编号要从 ① 连续排下去（防"抄一条改个字"这种复制粘贴留痕）。"""
    _, evidence, _ = _scan(FLOWS.read_text(encoding="utf-8"))
    rows = [c[0] for c in evidence if c[0].startswith(flow)]
    want = "①②③④⑤⑥"
    for i, row in enumerate(rows):
        assert want[i] in row, f"{row[:40]} 缺少编号 {want[i]}（第 {i + 1} 条）"
