"""卡 126（`T-G224`）：changelog 合并改成「**按日期插入**」的钉子。

被测：`tools/sync_docs.py` 的 `_merge_changelog`（旧口径「新片段一律接文件头」）
与 `--check` 的次序判据。四类钉子：

1. ★ **老片段插进新文档**（坑 32 现场）：目标已有 `## 2026-10-03`，待合并片段是 `## 2026-10-01`
   ⇒ 结果里 **10-03 在 10-01 上面**（旧实现把它插到文件头 ⇒ 这条**必红**）；
2. **同日期稳定**：两个同日片段，合并后相对次序 = 传入次序；
3. **幂等**：连跑两次，输出**逐字节相同**；
4. **`--check` 报次序错**：人工放一个「旧在上、新在下」的文件 ⇒ 报 **WARN** 并**点名两节的日期**。

★ 第 4 条只报 WARN、**不改退出码**：真仓 `docs/changelog.md` **可能**有历史倒置（坑 32 的残留），
硬失败会打穿既有断言
（`tests/test_docs_fragments.py::test_real_repo_is_in_sync_and_merge_is_noop`，本卡无权改）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import sync_docs as sd  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上

NEWER = "## 2026-10-03 —— 新节（T-G901）\n\n- 新内容。\n"
OLDER = "## 2026-10-01 —— 旧节（T-G900）\n\n- 老内容。\n"


def _mkroot(tmp_path: Path, changelog: str = NEWER) -> Path:
    """最小骨架：只有一个 `docs/changelog.md` 与其片段目录（其余通道空跑）。"""
    (tmp_path / "docs" / "changelog.d").mkdir(parents=True)
    (tmp_path / "docs" / "changelog.md").write_text(changelog, encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------- 1. 按日期插入（坑 32）

def test_older_fragment_inserted_below_newer_section() -> None:
    """★ 坑 32 现场：目标 `## 2026-10-03`，待合并 `## 2026-10-01` ⇒ 10-03 在上面。"""
    target = NEWER
    merged = sd._merge_changelog(target, [("docs/changelog.d/T-G900.md", OLDER)])
    assert merged.index("## 2026-10-03") < merged.index("## 2026-10-01")
    assert merged.startswith("## 2026-10-03")  # 首行仍是更新的那节
    assert merged.endswith(OLDER)  # 待合并节整段落在后面（只插入、不改写）


def test_newer_fragment_inserted_above_older_section() -> None:
    """反向：待合并片段更新 ⇒ 插到已有序文件的最上面。"""
    target = OLDER
    merged = sd._merge_changelog(target, [("docs/changelog.d/T-G901.md", NEWER)])
    assert merged.index("## 2026-10-03") < merged.index("## 2026-10-01")


def test_fragment_inserted_between_sections() -> None:
    """夹缝：目标 [10-03, 10-01]，待合并 10-02 ⇒ 落在这两节中间。"""
    target = NEWER + OLDER
    mid = "## 2026-10-02 —— 中间节（T-G902）\n\n- 中间。\n"
    merged = sd._merge_changelog(target, [("x", mid)])
    assert merged.index("## 2026-10-03") < merged.index("## 2026-10-02")
    assert merged.index("## 2026-10-02") < merged.index("## 2026-10-01")


# ---------------------------------------------------------------- 2. 同日期稳定

def test_same_day_fragments_keep_input_order() -> None:
    """两个同日片段：合并后相对次序**就是传入次序**（不搅乱）。"""
    a = "## 2026-10-02 —— 先（T-G911）\n\n- 先。\n"
    b = "## 2026-10-02 —— 后（T-G912）\n\n- 后。\n"
    m1 = sd._merge_changelog("", [("a", a), ("b", b)])
    assert m1.index("先（T-G911）") < m1.index("后（T-G912）")
    m2 = sd._merge_changelog("", [("b", b), ("a", a)])
    assert m2.index("后（T-G912）") < m2.index("先（T-G911）")


def test_same_day_fragment_not_hoisted_above_existing_same_day() -> None:
    """同日不插到既有同日节之上（`<` 而非 `<=`）⇒ 既有同日次序不被搅乱。"""
    existing = "## 2026-10-02 —— 既有（T-G910）\n\n- 既有。\n"
    incoming = "## 2026-10-02 —— 新增（T-G911）\n\n- 新增。\n"
    merged = sd._merge_changelog(existing, [("x", incoming)])
    assert merged.index("既有（T-G910）") < merged.index("新增（T-G911）")


# ---------------------------------------------------------------- 3. 幂等（逐字节）

def test_merge_is_idempotent_byte_identical(tmp_path: Path) -> None:
    root = _mkroot(tmp_path)
    (root / "docs" / "changelog.d" / "T-G900.md").write_text(OLDER, encoding="utf-8")

    assert sd.run(root, check=False) == 0
    first = (root / "docs" / "changelog.md").read_bytes()
    assert first.find(b"2026-10-03") < first.find(b"2026-10-01")  # 插入位置正确

    assert sd.run(root, check=False) == 0  # 第二次：零 diff
    assert (root / "docs" / "changelog.md").read_bytes() == first


# ---------------------------------------------------------------- 4. --check 次序判据（WARN）

def test_check_warns_on_out_of_order_changelog(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """旧在上、新在下 ⇒ 报 WARN 并**点名两节的日期**（★ 只 WARN，退出码不变）。"""
    root = _mkroot(tmp_path, changelog=OLDER + NEWER)  # 10-01 排在 10-03 上面 = 倒置
    rc = sd.run(root, check=True)
    out = capsys.readouterr().out
    assert rc == 0  # ★ 不阻断（真仓有历史倒置，硬失败会打穿既有断言）
    assert "[WARN]" in out
    assert "2026-10-01" in out  # 点名倒置那两节
    assert "2026-10-03" in out


def test_check_quiet_on_ordered_changelog(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """有序 ⇒ **不报** WARN（上面那条的正对照，证明判据真会咬）。"""
    root = _mkroot(tmp_path, changelog=NEWER + OLDER)
    rc = sd.run(root, check=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "[WARN]" not in out
    assert "[OK ]" in out


# ---------------------------------------------------------------- 5. 另两个通道口径未动

def test_traceability_and_handoff_channels_unchanged(tmp_path: Path) -> None:
    """本卡只动 changelog：traceability 仍接**文件尾**、交接仍按锚点插在旧 CHECKPOINT 之前。"""
    (tmp_path / "docs" / "traceability.d").mkdir(parents=True)
    (tmp_path / "复盘" / "交接.d").mkdir(parents=True)
    (tmp_path / "docs" / "changelog.md").write_text(NEWER, encoding="utf-8")
    (tmp_path / "docs" / "traceability.toml").write_text(
        '# 头注释\n\n[entries."T-G001"]\nid = "T-G001"\nstatus = "done"\ngaps = ""\n',
        encoding="utf-8",
    )
    (tmp_path / "复盘" / "交接-重构进度.md").write_text(
        "# 交接\n\n> **2026-10-01 · CHECKPOINT（卡 1 · `T-G001`）—— 旧**：\n> 旧一行。\n",
        encoding="utf-8",
    )
    trace = '[entries."T-G900"]\nid = "T-G900"\nstatus = "done"\ngaps = ""\n'
    handoff = "> **2026-10-02 · CHECKPOINT（卡 126 · `T-G900`）—— 新**：\n> 一行。\n"
    (tmp_path / "docs" / "traceability.d" / "T-G900.toml").write_text(trace, encoding="utf-8")
    (tmp_path / "复盘" / "交接.d" / "T-G900.md").write_text(handoff, encoding="utf-8")

    assert sd.run(tmp_path, check=False) == 0
    assert (tmp_path / "docs" / "traceability.toml").read_text(encoding="utf-8").endswith(trace)
    hand = (tmp_path / "复盘" / "交接-重构进度.md").read_text(encoding="utf-8")
    assert hand.index("T-G900") < hand.index("T-G001")  # 新 CHECKPOINT 插在旧的之前


# ---------------------------------------------------------------- 6. 真仓读数（卡验收）

def test_real_repo_check_still_passes(capsys: pytest.CaptureFixture[str]) -> None:
    """★ 卡验收：拿**真仓库**跑 `--check` 应当仍然通过（片段 ↔ 汇总一致）。"""
    rc = sd.run(ROOT, check=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "[OK ]" in out
