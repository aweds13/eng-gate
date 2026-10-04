"""文档地图生成器（`tools/wb_docmap.py`，卡 183 · T-G283）的反例钉子。

这个工具的价值在「把人读变成机器读数」，且要能区分「被台账钉住」与「只被人读过」。
按卡 §③ 钉四条，**全部跑在临时夹具上**（不许拿真树当夹具 ——
那会让每加一份文档就红一次）：

| # | 钉子 | 坏掉会红在哪 |
|---|---|---|
| ① | 完整性：夹具 N 份 `.md` ⇒ 索引正好 N 条 | 漏扫 / 重复扫 |
| ② | 幂等：连生成两次 ⇒ 逐字节相同 | 输出里混进了时间戳 / 顺序不稳 |
| ③ | ★ 「被钉住」要认得出来：造 `file:<文档>` 断言 ⇒ `pinned=true` | 钉子与普通引用没分开 |
| ④ | 坏输入不静默：不存在的目录 ⇒ 明确报错（非零退出） | 静默出空表把坏树当成空树 |

★ 只读真树：这里不写仓库里的真索引（临时索引都落在 `tmp_path`）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_docmap as wb  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上


def _make_fixture(tmp_path: Path, *, with_ledger: bool = False) -> Path:
    """搭一棵最小夹具树：复盘/ 两份 + docs/ 一份；可选带台账钉一条 file: 断言。"""
    (tmp_path / "复盘").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "复盘" / "a.md").write_text("# a\n", encoding="utf-8")
    (tmp_path / "复盘" / "b.md").write_text("# b\n", encoding="utf-8")
    (tmp_path / "docs" / "c.md").write_text("# c\n", encoding="utf-8")
    if with_ledger:
        (tmp_path / "docs" / "traceability.toml").write_text(
            '[entries."T-TEST"]\n'
            'evidence = ["file:复盘/a.md"]\n',
            encoding="utf-8",
        )
    return tmp_path


# ------------------------------------------------------------------ ① 完整性


def test_index_has_exactly_n_entries(tmp_path: Path) -> None:
    """夹具里放 3 份 `.md` ⇒ 索引里正好 3 条，不多不少。"""
    root = _make_fixture(tmp_path)
    out = tmp_path / "idx.toml"
    rc = wb.main(["--root", str(root), "--out", str(out)])
    assert rc == 0, f"生成应成功，rc={rc}"
    entries = wb.load_index_toml(out)
    assert len(entries) == 3, f"该有 3 条，实得 {len(entries)}：{entries}"
    paths = {str(e["path"]) for e in entries}
    assert paths == {"复盘/a.md", "复盘/b.md", "docs/c.md"}


# ------------------------------------------------------------------ ② 幂等


def test_idempotent_two_runs_byte_identical(tmp_path: Path) -> None:
    """连生成两次 ⇒ 两次写出的文件逐字节相同（不混时间戳 / 顺序稳）。"""
    root = _make_fixture(tmp_path, with_ledger=True)
    out1 = tmp_path / "idx1.toml"
    out2 = tmp_path / "idx2.toml"
    assert wb.main(["--root", str(root), "--out", str(out1)]) == 0
    assert wb.main(["--root", str(root), "--out", str(out2)]) == 0
    assert out1.read_bytes() == out2.read_bytes(), "两次生成不一致 —— 输出里混了非确定因素"


# ------------------------------------------------------------------ ③ 被钉住要认得出来


def test_pinned_is_detected_from_ledger_assertion(tmp_path: Path) -> None:
    """夹具里造一条 `file:复盘/a.md` 断言 ⇒ `复盘/a.md` 的 `pinned=true`、`pinned_by` 含台账号。

    ★ 这是本卡最值钱的钉子：「被台账钉住」与「只被人读过」必须在字段上分开 ——
    前者动了会碎台账，后者只是文档间互引。混了 = 危险批漏判。
    """
    root = _make_fixture(tmp_path, with_ledger=True)
    out = tmp_path / "idx.toml"
    assert wb.main(["--root", str(root), "--out", str(out)]) == 0
    entries = wb.load_index_toml(out)
    by_path = {str(e["path"]): e for e in entries}
    a = by_path["复盘/a.md"]
    assert a["pinned"] is True, f"复盘/a.md 被 file: 钉住，pinned 该 true，实得 {a['pinned']}"
    assert "T-TEST" in list(a["pinned_by"]), f"pinned_by 该含 T-TEST，实得 {a['pinned_by']}"
    b = by_path["复盘/b.md"]
    assert b["pinned"] is False, f"复盘/b.md 没被钉，pinned 该 false，实得 {b['pinned']}"


# ------------------------------------------------------------------ ④ 坏输入不静默


def test_missing_root_raises_not_silent(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """给一个不存在的目录 ⇒ 明确报错（非零退出 + stderr 有字），不许静默出空表。"""
    bogus = tmp_path / "不存在"
    out = tmp_path / "idx.toml"
    rc = wb.main(["--root", str(bogus), "--out", str(out)])
    err = capsys.readouterr().err
    assert rc != 0, "不存在的根目录该报错，不该退 0"
    assert err.strip(), "报错时 stderr 必须有字（不许静默）"
    assert not out.exists(), "坏输入不该写出索引文件"
