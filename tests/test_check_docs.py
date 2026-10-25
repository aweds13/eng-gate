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

import subprocess
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


def _seed_git(root: Path) -> None:
    """把合成树变成一个**提交过一次**的 git 仓（drift 才判得出来）。"""
    assert _git(root, "init", "-q").returncode == 0
    assert _git(root, "add", "-A").returncode == 0
    commit = _git(
        root, "-c", "user.name=test", "-c", "user.email=test@example.invalid",
        "commit", "-q", "-m", "seed",
    )
    assert commit.returncode == 0, commit.stderr


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


# ----------------------------------------------------------- 卡 E39：基线重刷
def test_write_baseline_file_format(tmp_path: Path) -> None:
    """★ 判据 1 的格式面：文件头写重刷命令 + 生成时间，三项读数都落盘。"""
    root = _tree(tmp_path)
    (root / "docs" / "bad.md").write_text("`docs/missing.md`\n", encoding="utf-8")
    (root / "docs" / "traceability.toml").write_text("[entries]\n", encoding="utf-8")
    _seed_git(root)

    assert cd.main(root, out=lambda _line: None, write_baseline=True) == 0
    path = root / "docs" / "doc-debt-baseline.toml"
    text = path.read_text(encoding="utf-8")
    assert "重刷命令" in text and "--write-baseline" in text, text
    assert "生成时间" in text, text

    counts, why = cd.load_baseline(path)
    assert why == "", why
    assert counts["dead_refs"] == 1, counts
    assert counts["superseded"] == 0, counts
    assert counts["drift"] == 0, counts


def test_write_baseline_is_idempotent(tmp_path: Path) -> None:
    """★ 判据 1：`--write-baseline` 连跑两次，基线文件**字节不变**（第二次不重写）。"""
    root = _tree(tmp_path)
    (root / "docs" / "bad.md").write_text("`docs/missing.md`\n", encoding="utf-8")
    path = root / "docs" / "doc-debt-baseline.toml"

    assert cd.main(root, out=lambda _line: None, write_baseline=True) == 0
    first = path.read_bytes()
    assert cd.main(root, out=lambda _line: None, write_baseline=True) == 0
    assert path.read_bytes() == first


def test_default_output_separates_debt_and_skip(tmp_path: Path) -> None:
    """★ 判据 2/3：欠账一行、判不出一行；基线内不报红，超基线报红。"""
    root = _tree(tmp_path)
    (root / "docs" / "bad.md").write_text("`docs/missing.md`\n", encoding="utf-8")
    baseline = root / "docs" / "doc-debt-baseline.toml"

    baseline.write_text("[baseline]\ndead_refs = 1\nsuperseded = 0\n", encoding="utf-8")
    code, text = _run(root, "report")
    lines = text.splitlines()
    assert "CHECK_DOCS: 死指针 1（基线 1，+0）" in lines, text
    assert any(
        line.startswith("CHECK_DOCS: 判不出 ") and line.endswith("这不是 PASS")
        for line in lines
    ), text
    assert "基线被顶破" not in text, text
    assert code == 0, text

    baseline.write_text("[baseline]\ndead_refs = 0\nsuperseded = 0\n", encoding="utf-8")
    code, text = _run(root, "report")
    assert code == 1, text
    assert "CHECK_DOCS: FAIL" in text, text


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

# ------------------------------------------------------------ 卡 F4：决策记录（--decisions）
def _record(
    number: str = "0001",
    *,
    status: str = "Accepted",
    supersedes: str = "",
    superseded_by: str = "",
    source: str = "台账 T-AG452",
) -> str:
    """一条结构完整的记录（默认 Accepted）。"""
    return (
        f"# {number} 演示决策\n"
        "\n"
        f"Status: {status}\n"
        f"Supersedes: {supersedes}\n"
        f"Superseded-by: {superseded_by}\n"
        f"来源: {source}\n"
        "\n"
        "## 背景与问题\n"
        "\n"
        "当时没有决策记录，改主意没人知道原委。\n"
        "\n"
        "## 候选方案\n"
        "\n"
        "A 继续散在复盘里；B 单独成篇。\n"
        "\n"
        "## 决定\n"
        "\n"
        "选 B，代价是多一份文档要维护。\n"
        "\n"
        "## 把握程度\n"
        "\n"
        "high —— 微软 Well-Architected 也是这么做的。\n"
    )


def _adr_tree(tmp_path: Path, files: dict[str, str]) -> Path:
    """在临时目录里铺一棵 docs/decisions 树。"""
    directory = tmp_path / "docs" / "decisions"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "README.md").write_text("# 决策记录\n", encoding="utf-8")
    for name, text in files.items():
        (directory / name).write_text(text, encoding="utf-8")
    return tmp_path


def _problems(tmp_path: Path) -> list[str]:
    return cd.check(tmp_path, head=cd.NO_HEAD).problems


# ------------------------------------------------------------------ 零件层：绿
def test_complete_record_passes(tmp_path):
    tree = _adr_tree(tmp_path, {"0001-first.md": _record()})
    result = cd.check(tree, head=cd.NO_HEAD)
    assert result.problems == [], result.problems
    assert result.count == 1 and result.span == "0001..0001"


def test_readme_is_not_a_record(tmp_path):
    """README 不参与编号与模板检查（它是说明，不是决策）。"""
    result = cd.check(_adr_tree(tmp_path, {"0001-first.md": _record()}), head=cd.NO_HEAD)
    assert result.count == 1


# ------------------------------------------------------------------ 零件层：红
def test_numbering_gap_bites(tmp_path):
    tree = _adr_tree(tmp_path, {"0001-a.md": _record("0001"), "0003-c.md": _record("0003")})
    problems = _problems(tree)
    assert any("连续" in p and "0002" in p for p in problems), problems


def test_duplicate_number_bites(tmp_path):
    tree = _adr_tree(tmp_path, {"0001-a.md": _record("0001"), "0001-b.md": _record("0001")})
    assert any("重号" in p for p in _problems(tree)), _problems(tree)


def test_filename_must_be_lowercase_slug(tmp_path):
    tree = _adr_tree(tmp_path, {"0001-Bad_Slug.md": _record()})
    assert any("文件名不合规" in p for p in _problems(tree)), _problems(tree)


def test_illegal_status_bites(tmp_path):
    tree = _adr_tree(tmp_path, {"0001-a.md": _record(status="Done")})
    assert any("status 不合法" in p for p in _problems(tree)), _problems(tree)


def test_missing_section_bites(tmp_path):
    text = _record().replace("## 候选方案", "## 别的标题")
    tree = _adr_tree(tmp_path, {"0001-a.md": text})
    problems = _problems(tree)
    assert any("缺段落 `## 候选方案`" in p for p in problems), problems


def test_extra_section_bites(tmp_path):
    tree = _adr_tree(tmp_path, {"0001-a.md": _record() + "\n## 后果\n\n多出来的一段。\n"})
    assert any("多出段落" in p for p in _problems(tree)), _problems(tree)


def test_empty_section_bites(tmp_path):
    text = _record().replace("当时没有决策记录，改主意没人知道原委。", "")
    tree = _adr_tree(tmp_path, {"0001-a.md": text})
    assert any("`## 背景与问题` 是空的" in p for p in _problems(tree)), _problems(tree)


def test_section_order_bites(tmp_path):
    text = _record()
    swapped = text.replace("## 背景与问题", "@@A@@").replace("## 候选方案", "## 背景与问题")
    swapped = swapped.replace("@@A@@", "## 候选方案")
    tree = _adr_tree(tmp_path, {"0001-a.md": swapped})
    assert any("段落顺序不对" in p for p in _problems(tree)), _problems(tree)


def test_confidence_needs_level_and_reason(tmp_path):
    text = _record().replace("high —— 微软 Well-Architected 也是这么做的。", "挺有把握的。")
    tree = _adr_tree(tmp_path, {"0001-a.md": text})
    assert any("把握程度" in p and "high" in p for p in _problems(tree)), _problems(tree)


def test_confidence_reason_too_short_bites(tmp_path):
    text = _record().replace("high —— 微软 Well-Architected 也是这么做的。", "high —— 行。")
    tree = _adr_tree(tmp_path, {"0001-a.md": text})
    assert any("为什么" in p and "太短" in p for p in _problems(tree)), _problems(tree)


def test_supersedes_must_be_reciprocal(tmp_path):
    """A 说取代 0002，而 0002 没写 Superseded-by / 没改状态 ⇒ 两条红。"""
    tree = _adr_tree(
        tmp_path,
        {"0002-old.md": _record("0002"), "0003-new.md": _record("0003", supersedes="0002")},
    )
    problems = _problems(tree)
    assert any("`Superseded-by`" in p and "不是 0003" in p for p in problems), problems
    assert any("status 还是 Accepted" in p for p in problems), problems


def test_superseded_without_link_bites(tmp_path):
    tree = _adr_tree(tmp_path, {"0001-a.md": _record(status="Superseded")})
    assert any("却没写 `Superseded-by:`" in p for p in _problems(tree)), _problems(tree)


def test_self_reference_bites(tmp_path):
    tree = _adr_tree(tmp_path, {"0001-a.md": _record(supersedes="0001")})
    assert any("指向自己" in p for p in _problems(tree)), _problems(tree)


def test_accepted_body_must_be_frozen(tmp_path):
    before = _record()
    after = before.replace("选 B，代价是多一份文档要维护。", "选 A 了，改主意。")
    tree = _adr_tree(tmp_path, {"0001-a.md": after})
    head = {"docs/decisions/0001-a.md": before}
    problems = cd.check(tree, head=head).problems
    assert any("正文被改过" in p for p in problems), problems


def test_header_beyond_two_allowed_lines_is_frozen(tmp_path):
    before = _record()
    after = before.replace("台账 T-AG452", "台账 T-AG999")
    tree = _adr_tree(tmp_path, {"0001-a.md": after})
    problems = cd.check(tree, head={"docs/decisions/0001-a.md": before}).problems
    assert any("头信息被改过" in p for p in problems), problems


def test_metadata_only_change_is_allowed(tmp_path):
    """Accepted → Superseded + 双链：正文不动、头信息只动两行 ⇒ 绿。"""
    old = _record("0001")
    new = _record("0002", supersedes="0001")
    flipped = _record("0001", status="Superseded", superseded_by="0002")
    tree = _adr_tree(tmp_path, {"0001-a.md": flipped, "0002-b.md": new})
    result = cd.check(tree, head={"docs/decisions/0001-a.md": old})
    assert result.problems == [], result.problems
    assert result.links == 1


def test_status_downgrade_bites(tmp_path):
    before = _record(status="Superseded", superseded_by="0002")
    after = _record(status="Accepted")
    tree = _adr_tree(
        tmp_path, {"0001-a.md": after, "0002-b.md": _record("0002", supersedes="0001")}
    )
    problems = cd.check(tree, head={"docs/decisions/0001-a.md": before}).problems
    assert any("status 倒退" in p for p in problems), problems


def test_deleted_record_bites(tmp_path):
    tree = _adr_tree(tmp_path, {})
    problems = cd.check(tree, head={"docs/decisions/0001-a.md": _record()}).problems
    assert any("不许删" in p for p in problems), problems


def test_missing_directory_bites(tmp_path):
    assert any("不存在" in p for p in cd.check(tmp_path).problems)


# ------------------------------------------------------------------ 真东西：git
def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        **cd.NO_WINDOW,
    )


def _git_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    """真起一个仓库并提交；不碰真仓库。"""
    tree = _adr_tree(tmp_path, files)
    assert _git(tree, "init", "-q").returncode == 0
    assert _git(tree, "add", "-A").returncode == 0
    commit = _git(
        tree, "-c", "user.name=test", "-c", "user.email=test@example.invalid",
        "commit", "-q", "-m", "seed",
    )
    assert commit.returncode == 0, commit.stderr
    return tree


def test_default_loader_reads_real_head(tmp_path):
    """★ 命门：默认路径（不问 stub）真能读到 HEAD 里的那一版，改正文就红。"""
    tree = _git_repo(tmp_path, {"0001-a.md": _record()})
    assert cd.check(tree).problems == []

    path = tree / "docs" / "decisions" / "0001-a.md"
    path.write_text(_record().replace("选 B，代价是", "选 A，代价是"), encoding="utf-8")
    problems = cd.check(tree).problems
    assert any("正文被改过" in p for p in problems), problems


def test_cli_exit_codes(tmp_path, capsys):
    good = _git_repo(tmp_path / "repo", {"0001-a.md": _record()})
    assert cd.main_decisions(["--decisions", "--root", str(good)]) == 0
    assert "[OK ]" in capsys.readouterr().out

    plain = _adr_tree(tmp_path / "plain", {"0001-a.md": _record()})
    assert cd.main_decisions(["--decisions", "--root", str(plain)]) == 3
    assert "[skip]" in capsys.readouterr().out


def test_real_tree_passes():
    """真仓库（本树）必须先过：docs/decisions 里的记录没有一条是坏的。"""
    assert cd.check(ROOT).problems == []



# ------------------------------------------- 卡 E53：未入库的源文档不进判据（双侧对称）
def _committed_repo(tmp_path: Path) -> Path:
    """一棵**提交过一次**的合成树：`docs/ok.md` 自指合法。"""
    root = _tree(tmp_path)
    _seed_git(root)
    return root


def test_untracked_source_doc_is_skipped_not_judged(tmp_path):
    """★ 未跟踪的 `.md` 不是判据的输入：它照扫不误就会让「同一 HEAD 两棵树读数不同」。

    主树盘上躺着的私有速查、别的窗口的半成品都属这一类（`git check-ignore` 对它们退 1，
    所以只问 ignored 是**问错了问题**）。判据要求：这条断链不进 `dead_refs`，
    而是出现在 skip 明细里，并点名理由。
    """
    root = _committed_repo(tmp_path)
    private = root / "复盘"
    private.mkdir()
    (private / "mine.md").write_text("看 `复盘/missing.md` 这一句\n", encoding="utf-8")

    report = cd.scan(root)
    assert [i.line() for i in report.dead_refs] == [], report.dead_refs
    reasons = {s.where: s.reason for s in report.skips if s.where == "复盘/mine.md"}
    assert reasons.get("复盘/mine.md") == "未入库文档（未跟踪，不随树分发）", report.skips

    # 反面：把它提交进库，它立刻回到判据里（证明不是「凡 notes/ 下都放过」）
    assert _git(root, "add", "-A").returncode == 0
    assert _git(root, "-c", "user.name=t", "-c", "user.email=t@e.invalid",
                "commit", "-q", "-m", "track").returncode == 0
    assert [i.line() for i in cd.scan(root).dead_refs] == ["复盘/mine.md:1 → 复盘/missing.md"]


def test_gitignored_source_doc_is_skipped_not_judged(tmp_path):
    """★ gitignored 的源文档同样不进判据，理由与「未跟踪」分开记（产物 vs 私有）。"""
    root = _committed_repo(tmp_path)
    (root / ".gitignore").write_text("scratch/\n", encoding="utf-8")
    scratch = root / "复盘" / "scratch"
    scratch.mkdir(parents=True)
    (scratch / "tmp.md").write_text("看 `复盘/scratch/gone.md` 这一句\n", encoding="utf-8")

    report = cd.scan(root)
    assert report.dead_refs == [], report.dead_refs
    reasons = {s.where: s.reason for s in report.skips}
    assert reasons.get("复盘/scratch/tmp.md") == "gitignored 文档（本机产物，不随树分发）", reasons


def test_real_tree_judges_only_tracked_docs():
    """真仓库：判出问题的源文件必须都在库内（否则就是又被本地文件带偏了）。"""
    tracked = cd.tracked_docs(ROOT)
    assert tracked, "git ls-files 一条都没读到 —— 这条钉子等于空转"
    report = cd.scan(ROOT)
    sources = {item.where.split(":")[0] for item in report.dead_refs}
    assert sources <= tracked, sorted(sources - tracked)[:5]
    for skip in report.skips:
        if skip.where.endswith(".md") and "/" in skip.where:
            assert skip.reason in {
                "未入库文档（未跟踪，不随树分发）",
                "gitignored 文档（本机产物，不随树分发）",
                "文件不存在",
                "路径在仓外，判不了",
                "模板占位符，判不了",
            } or skip.reason, skip
