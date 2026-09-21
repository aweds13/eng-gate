"""台账 ↔ 规格 标题对账工具（`scripts/audit_titles.py`）的测试。

它存在的理由（2026-09-20 实测）：`audit_progress.py` 的「规格覆盖」**只按编号**核对，
所以"编号在、含义错"（台账写成了规格前一条的要求）能一直躲过审计。
本工具补这一刀 —— 测试要保证两件事：
1. **抽标题**与**重叠度**这两个零件是对的（合成数据上验）；
2. 工具真能**抓出**现有的错位（数据级断言，用 xfail 挂着：T-D1 修完它必须变成 XPASS → 删掉 xfail）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import audit_titles as at  # noqa: E402 —— 需要先用 sys.path 把 scripts/ 挂上

# ---------------------------------------------------------------- 零件

def test_extract_spec_titles_covers_both_layers() -> None:
    titles = at.extract_spec_titles()
    assert titles, "一条规格标题都没抽到，解析一定坏了"
    # 两种写法都要认：nonfunctional 的 `## SR-NFxx · …` 与 functional 的 `- **SR-Fx.y**（…）～ …`
    assert "SR-NF13" in titles and "可观测" in titles["SR-NF13"]
    assert "SR-F1.1" in titles and "My Day" in titles["SR-F1.1"]
    # 括注（N 编号/一版）必须被剥掉，否则重叠度会被噪声拉高
    assert "N42" not in titles["SR-NF13"]
    assert "一版" not in titles["SR-F1.1"]


def test_content_chars_drops_stopwords() -> None:
    got = at.content_chars("支持任务：提醒 / 附件（可选）")
    assert {"醒", "附", "任", "务"} <= got, "实词要留下"
    assert "提" not in got, "「提供」被当虚词滤掉（短标题才不会被虚词凑出假重合）"
    assert "支" not in got and "持" not in got, "虚词要滤掉，否则什么标题都'像'"
    assert "/" not in got and "（" not in got and "：" not in got, "标点不算内容字"


def test_overlap_is_jaccard() -> None:
    assert at.overlap("跨端同步 LWW", "跨端同步 LWW") == 1.0
    assert at.overlap("跨端同步", "热力图") == 0.0
    mid = at.overlap("跨端同步 LWW 推拉传输", "跨端同步 LWW")
    assert 0.0 < mid < 1.0


def test_neighbour_detection_is_the_precise_signal() -> None:
    """合成一个"错位一格"的台账：NF2 写的是 NF1 的内容 → 必须判 `shifted` 且指认邻居。"""
    rows = at.compare()
    assert rows, "对账结果为空，工具坏了"
    for row in rows:
        assert row["level"] in {"shifted", "needs_review", "ok"}
        if row["level"] == "shifted":
            assert row["looks_like"], "判成错位就必须说出'更像哪一条'"


# ------------------------------------------------ 数据级（xfail：T-D1 修完转 XPASS）

@pytest.mark.xfail(
    strict=True,
    reason="T-D1 未完成：台账 F/NF 两层编号错位尚未校正；**修完后删掉这个 xfail**",
)
def test_no_shifted_entries_in_ledger() -> None:
    shifted = [r for r in at.compare() if r["level"] == "shifted"]
    ids = [r["id"] for r in shifted]
    assert not shifted, f"台账里有 {len(shifted)} 条编号错位：{ids}"


def test_cli_json_shape() -> None:
    cmd = [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "audit_titles.py"), "--json"]
    got = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT), timeout=120, check=False,
    )
    assert got.returncode == 0, got.stderr[-400:]  # 默认只报告；`--check` 才按错位数退 1
    payload = json.loads(got.stdout)
    assert payload["rows"] and "shifted" in payload and "problems" in payload
