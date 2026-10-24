"""文档门禁（卡 F3 / T-AG451）的钉子 —— 五条判据各一条，外加一条"它真的看得见"。

口径全在 `scripts/check_docs.py` 的文件头；这里只**验它真的会咬**：

1. 死指针报红（`--mode block` 退 1；`--mode report` 不红 —— 第一版先不挂 block）；
2. skip 计数：判不出的东西**必须**出现在输出里，且**不许**给 PASS 结论（block 档退 3）；
3. superseded 报红：正文说「已废弃」而没有 `status: superseded` + `supersedes:`；
   补了 frontmatter 就不报（反面钉子：证明它不是"命中就红"）；
4. baseline ratchet：比基线多一条 ⇒ 连 report 档也红；持平 ⇒ 不红（只许降不许升）；
5. `--doctor` 输出含「我在跑 / 我扫了 N 个文件 / 判出 M 条 / 判不出 K 条」四类读数。

夹具全部在 `tmp_path` 里搭合成小树（**真实仓库一个字节都不写**），
只有最后一条拿真仓库跑（证明它不是空转）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_docs as cd  # noqa: E402 —— 需要先把 scripts/ 挂上 sys.path


def _tree(tmp_path: Path) -> Path:
    """一棵最小合成树：`docs/ok.md` 自己指自己（合法引用）。"""
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "ok.md").write_text("见 `docs/ok.md`\n", encoding="utf-8")
    return tmp_path


def _run(root: Path, mode: str, **kwargs) -> tuple[int, str]:
    """跑一遍 `main()` 并把输出收成一段文本。"""
    lines: list[str] = []
    code = cd.main(root, mode, out=lines.append, **kwargs)
    return code, "\n".join(lines)


# --------------------------------------------------------------------- 判据 1
def test_dead_pointer_is_reported(tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """★ 死指针：`docs/bad.md` 指着不存在的 `docs/missing.md` ⇒ 逐条报「文件:行 → 指到哪」。"""
    root = _tree(tmp_path)
    (root / "docs" / "bad.md").write_text("第一行\n看 `docs/missing.md` 这一句\n",
                                          encoding="utf-8")
    report = cd.scan(root)
    detail = [item.line() for item in report.dead_refs]
    assert detail == ["docs/bad.md:2 → docs/missing.md"], detail

    code, text = _run(root, "block")
    assert code == 1, text
    assert "docs/bad.md:2 → docs/missing.md" in text
    # 第一版先 report：有债也不红（卡里写明"不许在第一版就 --mode block"）
    assert _run(root, "report")[0] == 0


def test_existing_and_out_of_scope_refs_are_not_dead(tmp_path: Path) -> None:
    """反面钉子：真存在的不报；外链、子命令这种「不是仓内相对路径」的也不冤枉。"""
    root = _tree(tmp_path)
    (root / "docs" / "fine.md").write_text(
        "真在的：`docs/ok.md`、`../AGENTS.md`\n"
        "不是指针的：`tools/list`、`https://example.com/a.md`、`/api/tasks`\n",
        encoding="utf-8",
    )
    (root / "AGENTS.md").write_text("入口\n", encoding="utf-8")
    assert cd.scan(root).dead_refs == []


# --------------------------------------------------------------------- 判据 4
def test_skip_is_counted_and_never_called_a_pass(tmp_path: Path) -> None:
    """★ skip：模板占位 / `gates/diag` 产物**计数打印**，且输出里不许出现 PASS。"""
    root = _tree(tmp_path)
    (root / "gates").mkdir(exist_ok=True)  # `gates/` 在根上存在，`gates/diag/...` 才算仓内路径
    (root / "docs" / "skip.md").write_text(
        "模板：`docs/<卡号>.md`\n产物：`gates/diag/x.md`\n", encoding="utf-8"
    )
    report = cd.scan(root)
    reasons = {item.reason for item in report.skips}
    assert any("模板占位" in reason for reason in reasons), reasons
    assert any("gates/diag" in reason for reason in reasons), reasons

    code, text = _run(root, "report")
    assert "判不出" in text and "我判不出" in text
    assert "CHECK_DOCS: PASS" not in text, text
    assert code == 0  # report 档不因 skip 而红（但结论里写明没判完）
    # block 档：判不出**不算通过** ⇒ 单独一个退出码 3（不是 0）
    assert _run(root, "block")[0] == 3


# --------------------------------------------------------------------- 判据 3
def test_superseded_needs_frontmatter(tmp_path: Path) -> None:
    """★ superseded：正文说「已废弃」却没标注 ⇒ 报；补了 `status` + `supersedes` ⇒ 不报。"""
    root = _tree(tmp_path)
    (root / "docs" / "old.md").write_text("这条路已废弃。\n", encoding="utf-8")
    (root / "docs" / "gone.md").write_text(
        "---\nstatus: superseded\nsupersedes: docs/old.md\n---\n\n这条路已废弃。\n",
        encoding="utf-8",
    )
    flagged = [item.where for item in cd.scan(root).superseded]
    assert flagged == ["docs/old.md"], flagged


# ----------------------------------------------------------- 基线 ratchet
def test_baseline_ratchet_only_goes_down(tmp_path: Path) -> None:
    """★ ratchet：欠账比基线多一条 ⇒ 连 report 档也红；持平 ⇒ 不红。"""
    root = _tree(tmp_path)
    (root / "docs" / "bad.md").write_text("`docs/missing.md`\n", encoding="utf-8")
    baseline = root / "docs" / "doc-debt-baseline.toml"

    baseline.write_text("[baseline]\ndead_refs = 0\nsuperseded = 0\n", encoding="utf-8")
    report = cd.scan(root)
    assert any("涨到" in line for line in report.ratchet), report.ratchet
    assert _run(root, "report")[0] == 1, "基线被顶破 ⇒ report 档也该红"

    baseline.write_text("[baseline]\ndead_refs = 1\nsuperseded = 0\n", encoding="utf-8")
    assert _run(root, "report")[0] == 0
    # 基线不存在 ⇒ 记 skip（判不了），不是"通过"
    baseline.unlink()
    report = cd.scan(root)
    assert any("没有基线" in item.reason for item in report.skips)


# --------------------------------------------------------------------- 判据 5
def test_doctor_prints_all_three_counts(tmp_path: Path) -> None:
    """★ `--doctor`：四类读数都要打出来（我在跑 / 扫了 N 个 / 判出 M 条 / 判不出 K 条）。"""
    root = _tree(tmp_path)
    (root / "docs" / "bad.md").write_text("`docs/missing.md`\n模板：`docs/<x>.md`\n",
                                          encoding="utf-8")
    # 台账 + 基线都在 ⇒ "判不出"只剩那条模板占位（数字才是确定的）
    (root / "docs" / "traceability.toml").write_text("[entries]\n", encoding="utf-8")
    (root / "docs" / "doc-debt-baseline.toml").write_text(
        "[baseline]\ndead_refs = 1\nsuperseded = 0\n", encoding="utf-8"
    )
    _, text = _run(root, "report", doctor=True)
    for phrase in ("我在跑", "我扫了", "个文件", "判出", "判不出"):
        assert phrase in text, f"doctor 输出缺「{phrase}」：\n{text}"
    assert "判出 1 条" in text, text
    # 判不出 2 条 = 模板占位 1 + 「不是 git 仓库 ⇒ drift 判不了」1（合成树里没有 git）
    assert "判不出 2 条" in text, text
    assert "模板占位" in text and "drift 判不了" in text, text


# --------------------------------------------------------- 真仓库（反空转）
def test_real_repo_is_actually_scanned() -> None:
    """真仓库上它得**看得见东西**：三个目录都扫到了，基线也在、能读。

    ★ 只钉"看得见 + 基线可读"，**不**钉欠账条数 —— 那个数由基线 ratchet 管，
      写进钉子只会让还债的人莫名撞红。
    """
    report = cd.scan(ROOT)
    assert report.scanned.get("文件", 0) > 500, report.scanned
    assert report.scanned.get("docs", 0) > 0, report.scanned
    assert report.scanned.get("复盘", 0) > 0, report.scanned
    counts, why = cd.load_baseline(ROOT / "docs" / "doc-debt-baseline.toml")
    assert why == "", why
    assert "dead_refs" in counts and "superseded" in counts, counts
