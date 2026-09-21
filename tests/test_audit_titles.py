"""台账 ↔ 规格 标题对账工具（`scripts/audit_titles.py`）的测试。

它存在的理由（2026-09-20 实测）：`audit_progress.py` 的「规格覆盖」**只按编号**核对，
所以"编号在、含义错"（台账写成了规格前一条的要求）能一直躲过审计。
本工具补这一刀 —— 测试要保证两件事：
1. **抽标题**与**重叠度**这两个零件是对的（合成数据上验）；
2. 工具真能**抓出**现有的错位（数据级断言）。

2026-09-20：编号已按规则 A 校正完（`复盘/台账编号校正-方案A落地.md`），
所以原来那个 `xfail(strict=True)` 的闹钟**按约定删掉**，换成真断言（错位必须为 0）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

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


def test_base_id_strips_split_suffix() -> None:
    """规则 A 的拆卡后缀：`SR-F1.1a` 属于规格条目 `SR-F1.1`。"""
    assert at.base_id("SR-F1.1a") == "SR-F1.1"
    assert at.base_id("SR-NF4b") == "SR-NF4"
    assert at.base_id("SR-F1.1") == "SR-F1.1"
    assert at.base_id("SR-NF13") == "SR-NF13"


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


def test_rows_carry_the_shape_the_audit_needs() -> None:
    rows = at.compare()
    assert rows, "对账结果为空，工具坏了"
    for row in rows:
        assert row["level"] in {"shifted", "unmapped", "needs_review", "ok"}
        if row["level"] == "shifted":
            assert row["looks_like"], "判成错位就必须说出'更像哪一条'"


# ------------------------------------------------- 数据级：规则 A 必须为真

def test_no_shifted_or_unmapped_entries_in_ledger() -> None:
    """★ 核心断言：台账里的每张 `SR-*` 卡都与**同号规格条目**同义，且没有规格里不存在的编号。

    这条原来是 `xfail(strict=True)` 的闹钟（校正前必须失败、修好后 XPASS 报错逼人删掉 xfail）。
    T-D1 校正完成 → 按约定删掉 xfail，换成真断言。
    """
    rows = at.compare()
    shifted = [r["id"] for r in rows if r["level"] == "shifted"]
    unmapped = [r["id"] for r in rows if r["level"] == "unmapped"]
    assert not shifted, f"台账里有 {len(shifted)} 条编号错位：{shifted}"
    assert not unmapped, f"台账里有 {len(unmapped)} 条 SR 卡在规格里找不到同号条目：{unmapped}"


def test_cli_check_fails_loudly_only_on_shifted_or_unmapped() -> None:
    """`--check` 现在必须退 0（已校正）；默认模式与 `--json` 的字段名要稳定（门禁与测试都读它）。"""
    cmd = [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "audit_titles.py"), "--json"]
    got = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT), timeout=120, check=False,
    )
    assert got.returncode == 0, got.stderr[-400:]
    payload = json.loads(got.stdout)
    assert payload["rows"] and "shifted" in payload and "problems" in payload
    assert payload["shifted"] == 0 and payload["unmapped"] == 0
    check = subprocess.run(
        [*cmd[:-1], "--check"], capture_output=True, text=True, encoding="utf-8",
        errors="replace", cwd=str(ROOT), timeout=120, check=False,
    )
    assert check.returncode == 0, check.stdout[-600:]

