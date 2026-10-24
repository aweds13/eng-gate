"""`scripts/gen_doc_index.py` 的钉子（卡 F2 · T-AG450）—— 索引必须跟文件走。

## 钉什么（对应卡 §判据）

1. 一致退 0 / 手改退 1，并且**点名哪几行**（不是只说「有差异」）；
2. 没有 frontmatter 的文件进「未标注」段，如实计数（不拿 `# 标题` 顶替 `title`）；
3. 删掉首行 generated 标记 ⇒ 红（判据 3：人改了但没跑脚本，必须红）；
4. `复盘/INDEX.md` 的 L0 段表与「历史与被推翻」由机器算（frontmatter + 路径前缀）；
   判不出来（盘上是手写版）⇒ 报 SKIP，且 `--strict` 时 SKIP 也算红。

每条都喂**合成小树**（`tmp_path`），不碰真仓库 —— 真仓库那条由验收命令
`python -X utf8 scripts/gen_doc_index.py --check` 负责，两处不重叠。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import gen_doc_index as gi  # noqa: E402 —— 需要先用 sys.path 把 scripts/ 挂上


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _fm(**fields: str) -> str:
    body = "".join(f"{key}: {value}\n" for key, value in fields.items())
    return f"---\n{body}---\n"


# --------------------------------------------------- 判据 1：一致退 0 / 手改退 1


def test_check_is_green_when_index_matches_files(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    """生成后立刻 `--check` ⇒ 退 0（判据 1 的绿灯半边）。"""
    _write(tmp_path, "docs/a.md", _fm(title="甲", mode="tutorial") + "\n正文\n")
    _write(tmp_path, "docs/sub/b.md", "# 乙\n\n没有 frontmatter\n")

    assert gi.main(["--root", str(tmp_path), "--target", "docs"]) == 0
    capsys.readouterr()
    assert gi.main(["--root", str(tmp_path), "--target", "docs", "--check"]) == 0
    assert "[OK  ] docs/INDEX.md" in capsys.readouterr().out


def test_hand_edit_is_red_and_names_the_lines(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    """手改一行 ⇒ 退 1，且**点名到行号 + 应为/实际**（判据 1 的红灯半边）。"""
    _write(tmp_path, "docs/a.md", "# 甲\n")
    assert gi.main(["--root", str(tmp_path), "--target", "docs"]) == 0
    index = tmp_path / "docs/INDEX.md"
    index.write_text(index.read_text(encoding="utf-8") + "手改的一行\n", encoding="utf-8",
                     newline="\n")
    capsys.readouterr()

    assert gi.main(["--root", str(tmp_path), "--target", "docs", "--check"]) == 1
    out = capsys.readouterr().out
    assert "[FAIL] docs/INDEX.md" in out
    assert "行：应为" in out and "实际" in out
    assert "手改的一行" in out


# --------------------------------------------- 判据 2：没有 frontmatter 进「未标注」


def test_file_without_frontmatter_lands_in_unlabeled_section(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    """无 frontmatter 的进「未标注」段并计数，不进任何 mode 段、也不拿标题冒充 title。"""
    _write(tmp_path, "docs/plain.md", "# 有标题但没 frontmatter\n\n正文\n")
    _write(tmp_path, "docs/fm.md", _fm(title="写了的", mode="reference"))

    assert gi.main(["--root", str(tmp_path), "--target", "docs"]) == 0
    capsys.readouterr()
    text = (tmp_path / "docs/INDEX.md").read_text(encoding="utf-8")

    assert "## 未标注（1 篇）" in text
    assert "## reference（1 篇）" in text
    assert "- `docs/plain.md`\n" in text            # 未标注段里只有路径，没有 title
    assert "- `docs/plain.md` — 有标题但没 frontmatter" not in text  # 不猜标题


# ------------------------------------------- 判据 3：删首行 generated 标记必须红


def test_deleting_generated_header_is_red(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    """首行标识不是「可有可无」的装饰：删了它 = 人改过 ⇒ 判据 3 判红。"""
    _write(tmp_path, "docs/a.md", "# 甲\n")
    assert gi.main(["--root", str(tmp_path), "--target", "docs"]) == 0
    index = tmp_path / "docs/INDEX.md"
    body = index.read_text(encoding="utf-8").splitlines(keepends=True)[1:]
    index.write_text("".join(body), encoding="utf-8", newline="\n")
    capsys.readouterr()

    assert gi.main(["--root", str(tmp_path), "--target", "docs", "--check"]) == 1
    assert "首行不是" in capsys.readouterr().out


def test_write_refuses_to_clobber_a_handwritten_index(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    """盘上是手写版 ⇒ 拒写（不覆盖别人的文件），除非显式 `--adopt`。"""
    _write(tmp_path, "docs/a.md", "# 甲\n")
    handwritten = _write(tmp_path, "docs/INDEX.md", "# 手写索引\n")

    assert gi.main(["--root", str(tmp_path), "--target", "docs"]) == 1
    assert "不覆盖" in capsys.readouterr().out
    assert handwritten.read_text(encoding="utf-8") == "# 手写索引\n"

    assert gi.main(["--root", str(tmp_path), "--target", "docs", "--adopt", "docs/INDEX.md"]) == 0
    assert (tmp_path / "docs/INDEX.md").read_text(encoding="utf-8").startswith(gi.GENERATED)


# ------------------------------------------------- 计数稳定 / 跟得上文件变化


def test_counts_are_stable_and_track_new_files(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    """同一棵树连写两次字节相同；加一篇之后 `--check` 先红、再生成就跟着变（不许抄旧数字）。"""
    _write(tmp_path, "docs/a.md", _fm(title="甲", mode="tutorial"))
    _write(tmp_path, "docs/b.md", _fm(title="乙", mode="howto"))
    assert gi.main(["--root", str(tmp_path), "--target", "docs"]) == 0
    first = (tmp_path / "docs/INDEX.md").read_bytes()

    assert gi.main(["--root", str(tmp_path), "--target", "docs"]) == 0
    assert (tmp_path / "docs/INDEX.md").read_bytes() == first, "连写两次必须字节相同"
    capsys.readouterr()

    _write(tmp_path, "docs/c.md", "# 丙（没有 frontmatter）\n")
    assert gi.main(["--root", str(tmp_path), "--target", "docs", "--check"]) == 1
    capsys.readouterr()

    assert gi.main(["--root", str(tmp_path), "--target", "docs"]) == 0
    text = (tmp_path / "docs/INDEX.md").read_text(encoding="utf-8")
    assert "# docs 索引（3 篇 · 机器生成）" in text
    assert "| **合计** | **3** |" in text
    assert "| 未标注 | 1 |" in text


# ------------------------------------- 判据 4：复盘索引的 L0 段表与「历史与被推翻」


def test_retro_l0_table_and_superseded_are_computed(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    """L0 段表按路径前缀算，「历史与被推翻」按 `status: superseded` 算（含反查 supersedes）。"""
    _write(tmp_path, "复盘/卡/卡A-新.md", _fm(title="新", status="active"))
    _write(tmp_path, "复盘/卡/卡B-旧.md",
           _fm(title="旧", status="superseded", supersedes="复盘/卡/卡A-新.md"))
    _write(tmp_path, "复盘/交接.d/T-1.md", "# 交接\n")
    _write(tmp_path, "复盘/手写.md", "# 根层\n")

    assert gi.main(["--root", str(tmp_path), "--target", "retro",
                    "--adopt", "复盘/INDEX.md"]) == 0
    capsys.readouterr()
    assert gi.main(["--root", str(tmp_path), "--target", "retro",
                    "--adopt", "复盘/INDEX.md", "--check"]) == 0
    text = (tmp_path / "复盘/INDEX.md").read_text(encoding="utf-8")

    # L0 段表：根层 1 / 交接.d 1 / 卡 2（已标注 2）
    assert "| `复盘/` | 1 | 0 | 1 |" in text
    assert "| `复盘/交接.d/` | 1 | 0 | 1 |" in text
    assert "| `复盘/卡/` | 2 | 2 | 0 |" in text
    # 历史与被推翻：1 篇，并给出 supersedes 指向
    assert "- 标了 `status: superseded` 的：**1 篇**" in text
    assert "| `复盘/卡/卡B-旧.md` | `复盘/卡/卡A-新.md` |" in text


def test_pending_retro_is_skip_and_strict_turns_it_red(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    """盘上是手写版 ⇒ SKIP（判不出来不冒充通过）；`--strict` 把 SKIP 也当红（自证会咬）。"""
    _write(tmp_path, "复盘/手写.md", "# 根层\n")
    _write(tmp_path, "复盘/INDEX.md", "# 手写索引\n")

    assert gi.main(["--root", str(tmp_path), "--target", "retro", "--check"]) == 0
    assert "[SKIP] 复盘/INDEX.md" in capsys.readouterr().out

    assert gi.main(["--root", str(tmp_path), "--target", "retro", "--check", "--strict"]) == 1
    capsys.readouterr()


def test_missing_source_dir_is_skip_not_red(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    """源目录不存在（合成小树只放一份）⇒ SKIP；不许因此把 `--check` 弄红。"""
    _write(tmp_path, "docs/a.md", "# 甲\n")
    assert gi.main(["--root", str(tmp_path), "--target", "docs"]) == 0
    capsys.readouterr()

    assert gi.main(["--root", str(tmp_path), "--check"]) == 0
    out = capsys.readouterr().out
    assert "[OK  ] docs/INDEX.md" in out
    assert "[SKIP] 复盘/INDEX.md" in out
