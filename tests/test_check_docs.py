"""文档门禁（卡 F3 / T-AG451）的钉子 —— 五条判据各一条，外加一条"它真的看得见"。

口径全在 `scripts/check_docs.py` 的文件头；这里只**验它真的会咬**：

1. 死指针报红（`--mode block` 退 1；`--mode report` 不红 —— 第一版先不挂 block）；
2. skip 计数：判不出的东西**必须**出现在输出里，且**不许**给 PASS 结论（block 档退 3）；
3. superseded 报红：**文档自己声明自己过时**（`本文档已废弃` / `本文档不再适用。` /
   `本文档被 docs/new.md 取代` / `# 已废弃：xxx`）而没有 `status: superseded` + `supersedes:`；
   ★ 判据是「主语 + 关键词 + 同句」三件齐备 —— 无主语的 `这条路现已废弃。` 不算；
   补了 frontmatter 就不报（反面钉子：证明它不是"命中就红"）；
   裸词（讨论词表、文件名里带这词、自动生成索引）**不许**报 —— 卡 A308 收窄；
4. baseline ratchet：比基线多一条 ⇒ 连 report 档也红；持平 ⇒ 不红（只许降不许升）；
5. `--doctor` 输出含「我在跑 / 我扫了 N 个文件 / 判出 M 条 / 判不出 K 条」四类读数。

夹具全部在 `tmp_path` 里搭合成小树（**真实仓库一个字节都不写**），
只有最后一条拿真仓库跑（证明它不是空转）。

6. `--file`（卡 E96）：只判点名的几份 —— 收窄只作用于**逐份文档**的两腿（死指针 / superseded），
   drift 腿不吃 docs 列表；坏单文件只报那一份、点不到任何文件 ⇒ 退 1 并明说；
   不给 `--file` 时，行为与输出都逐字节同旧。
   ★ 复核补的一刀：收窄读数**不许**跟全仓基线比（局部小证不了全仓清了）—— 输出里没有
   「降到」/「可以把基线调低」，基线那几行改印「（收窄读数，不比基线）」。
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

# --------------------------------------- 判据 1（卡 F10）：一行判不了别连累同行
def test_unpaired_backtick_does_not_hide_the_paired_ref(tmp_path: Path) -> None:
    """★ 卡 F10 反向钉子：成对引用 + 行尾游离反引号 ⇒ 死指针**照样**要报。

    旧实现（`if line.count("`") % 2: return [], True` + 主循环 `continue`）见到奇数个
    反引号就把整行扔掉，于是同一行里成对的引用一条都不判 ⇒ 这条真断链**报 0 条**。
    判据自己制造盲区，比不判更坏：它诚实地写着「判不了」，却把判得了的一起丢了。
    """
    root = _tree(tmp_path)
    (root / "docs" / "half.md").write_text(
        "见 `docs/ghost.md`，尾还挂着一个没配对的反引号 `\n", encoding="utf-8"
    )
    detail = [item.line() for item in cd.scan(root).dead_refs]
    assert detail == ["docs/half.md:1 → docs/ghost.md"], detail


def test_unpaired_backtick_skip_is_narrowed_to_the_tail(tmp_path: Path) -> None:
    """★ 判不了的那一段仍要如实报，但口径是「这一段」不是「这一行」。"""
    root = _tree(tmp_path)
    (root / "docs" / "tailref.md").write_text(
        "见 `docs/ok.md`，尾巴 `docs/<卡号>.md\n", encoding="utf-8"
    )
    report = cd.scan(root)
    assert report.dead_refs == [], [item.line() for item in report.dead_refs]
    reasons = [item.reason for item in report.skips]
    assert "行尾反引号不成对，这一段判不了" in reasons, reasons
    assert "行内反引号不成对，这一行判不了" not in reasons, reasons


def test_unpaired_backtick_before_plain_code_is_not_a_skip(tmp_path: Path) -> None:
    """★ 尾巴里只是代码原文 / 纯标点 ⇒ 不记 skip（它本来就不含引用，记了是灌噪声）。"""
    root = _tree(tmp_path)
    (root / "docs" / "code.md").write_text(
        "调用 `min(a, b)` 时尾部多一个反引号 ` 以及 get_group / rename_group\n",
        encoding="utf-8",
    )
    report = cd.scan(root)
    backtick = [s for s in report.skips if "反引号" in s.reason]
    assert backtick == [], [s.reason for s in backtick]
    assert report.dead_refs == [], [item.line() for item in report.dead_refs]



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
    (root / "docs" / "old.md").write_text("本文档已废弃。\n", encoding="utf-8")
    (root / "docs" / "gone.md").write_text(
        "---\nstatus: superseded\nsupersedes: docs/old.md\n---\n\n本文档已废弃。\n",
        encoding="utf-8",
    )
    flagged = [item.where for item in cd.scan(root).superseded]
    assert flagged == ["docs/old.md"], flagged


def test_superseded_accepts_every_declaration_shape(tmp_path: Path) -> None:
    """★ 收窄后三种句式**都要认得**（收窄不许窄到真声明也漏）。"""
    root = _tree(tmp_path)
    shapes = {
        "subject.md": "本文档已废弃，内容并进 `docs/ok.md`。\n",   # 主语 + 关键词
        "this.md": "本文件被 `docs/new.md` 取代。\n",              # 「被取代」的另一种说法
        "tail.md": "本文档不再适用。\n",                           # 主语在，关键词落句末
        "heading.md": "# 已废弃：老的通知聚合\n\n只留路标。\n",      # 标题即声明
    }
    for name, text in shapes.items():
        (root / "docs" / name).write_text(text, encoding="utf-8")
    flagged = {item.where for item in cd.scan(root).superseded}
    assert flagged == {f"docs/{name}" for name in shapes}, flagged


def test_superseded_ignores_bare_word(tmp_path: Path) -> None:
    """★ 卡 A308：**裸词不算**。讨论词表、文件名带词、自动生成文件、说别人过时、否定，都不报。"""
    root = _tree(tmp_path)
    # ① 在讨论/定义词表本身（原来卡 F3 就是这样被误报的）
    (root / "docs" / "wordlist.md").write_text(
        "判据 3 的词表是「已废弃 / 被取代 / 不再适用」三个词，命中就报。\n",
        encoding="utf-8",
    )
    # ② 文件名里带这个词，正文只是引用别处（原来 复盘/已废弃-xxx.md 这样被误报）
    (root / "docs" / "已废弃-老平台.md").write_text(
        "归档在 `docs/ok.md`，详见废弃记录。\n", encoding="utf-8",
    )
    # ③ 自动生成文件：首行锚点 ⇒ 不判（原来 复盘/INDEX.md 这样被误报）
    (root / "docs" / "index.md").write_text(
        cd.GENERATED + "\n\n# 索引\n\n- 已废弃：某页\n", encoding="utf-8",
    )
    # ④ 说的是**别的**对象过时，不是自己：`本文档的 A 已被 B 取代`
    (root / "docs" / "object.md").write_text(
        "本文档的旧入口已被 `docs/ok.md` 取代。\n", encoding="utf-8",
    )
    # ⑤ 否定句
    (root / "docs" / "negated.md").write_text(
        "本文档并非不再适用，仍在维护。\n", encoding="utf-8",
    )
    # ⑥ 无主语、只靠关键词落句末：说的是那条路，不是这份文档
    (root / "docs" / "nosubject.md").write_text(
        "旧路由表那条路现已废弃。\n", encoding="utf-8",
    )
    flagged = [item.where for item in cd.scan(root).superseded]
    assert flagged == [], flagged


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


# ------------------------------- 卡 F6：判据顺序换了，钉子跟着换（反向用例 · 每条都得能咬）
def test_ref_with_line_number_list_resolves(tmp_path: Path) -> None:
    """钉子 1：文件真在、引用带**行号列表**（`:23,161`）⇒ 判得出存在，不判死也不 skip。

    行号是**排版**不是路径：`normalize()` 剥掉它之后必须落回 `docs/deep.md`。
    改坏了会怎样：`docs/deep.md:23,161` 的扩展名变成 `.md:23,161` ⇒ 不在 `OWN_EXTS`
    ⇒ 落进「别仓路径」白跳过（旧顺序正是这样白跳过的）。
    """
    root = _tree(tmp_path)
    (root / "docs" / "deep.md").write_text("x\n" * 40, encoding="utf-8")
    (root / "docs" / "refs.md").write_text("看 `docs/deep.md:23,161` 这两行\n", encoding="utf-8")
    assert cd.normalize("docs/deep.md:23,161") == "docs/deep.md"
    assert cd.is_pointer("docs/deep.md:23,161", root), "这条钉子拿的不是指针 ⇒ 等于空转"

    report = cd.scan(root)
    assert [item.line() for item in report.dead_refs] == [], report.dead_refs
    refs_skips = [s.reason for s in report.skips if s.where.startswith("docs/refs.md")]
    assert refs_skips == [], report.skips


def test_trailing_colon_after_line_number_is_not_foreign(tmp_path: Path) -> None:
    """钉子 2：`文件.py:` / `文件.py:68:` 这种**尾冒号**写法不该被判成「别仓类型」。

    三处实测（`复盘/卡/卡E49-云机红单归因与可移植性.md:22`、`复盘/外包-卡表与规矩.md:1298`、
    `复盘/派活器三合一-T-G114.md:171`）都是本仓真文件后面多打了一个冒号。
    改坏了会怎样：扩展名变成 `.py:` ⇒ 不在 `OWN_EXTS` ⇒ 理由写着「别仓路径」，白跳过。
    """
    root = _tree(tmp_path)
    (root / "tests").mkdir()
    (root / "tests" / "test_wb_dispatch.py").write_text("x = 1\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("y = 2\n", encoding="utf-8")
    (root / "docs" / "refs.md").write_text(
        "看 `tests/test_wb_dispatch.py:` 与 `src/main.py:68:`\n", encoding="utf-8"
    )
    assert cd.normalize("tests/test_wb_dispatch.py:") == "tests/test_wb_dispatch.py"
    assert cd.normalize("src/main.py:68:") == "src/main.py"

    report = cd.scan(root)
    assert [item.line() for item in report.dead_refs] == [], report.dead_refs
    mine = [s.reason for s in report.skips if s.where.startswith("docs/refs.md")]
    assert mine == [], mine


def test_absolute_path_that_exists_is_not_skipped(tmp_path: Path) -> None:
    """钉子 3：盘符绝对路径**盘上真有** ⇒ 正常（存在就是存在）；不存在的仍 skip。

    两半都钉：只钉「真在的放过」证明不了它不是「凡是绝对路径都放过」。
    `D:/repo/infra/pool/projects.toml` 实测 120 条这种真存在的仓外绝对路径。
    """
    root = _tree(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    real = outside / "real.toml"
    real.write_text("k = 1\n", encoding="utf-8")
    gone = outside / "gone.toml"
    (root / "docs" / "abs.md").write_text(
        f"真在的：`{real.as_posix()}`\n不存在的：`{gone.as_posix()}`\n", encoding="utf-8"
    )
    assert cd.is_pointer(real.as_posix(), root), "这条钉子拿的不是指针 ⇒ 等于空转"
    assert cd.is_pointer(gone.as_posix(), root), "这条钉子拿的不是指针 ⇒ 等于空转"

    report = cd.scan(root)
    assert [item.line() for item in report.dead_refs] == [], report.dead_refs
    reasons = {s.token: s.reason for s in report.skips}
    assert real.as_posix() not in reasons, reasons
    assert reasons.get(gone.as_posix()) == "仓外/绝对路径，判不了", reasons


def test_gitignored_artifact_reason_is_accurate(tmp_path: Path) -> None:
    """钉子 4：被 `.gitignore` 遮住的产物 ⇒ 理由写「gitignored 产物」，**不是**「别仓路径」。

    旧顺序把扩展名猜测排在 gitignore 之前 ⇒ `logs/gone.jsonl` 会被记成「别仓类型」。
    理由写反不只是文案问题：它把「我知道这是产物」和「我猜这是别人的文件」混成一类。
    """
    root = _committed_repo(tmp_path)
    (root / ".gitignore").write_text("logs/\n", encoding="utf-8")
    (root / "logs").mkdir()
    (root / "docs" / "refs.md").write_text("产物：`logs/gone.jsonl`\n", encoding="utf-8")
    assert _git(root, "add", "-A").returncode == 0
    assert _git(
        root, "-c", "user.name=t", "-c", "user.email=t@e.invalid", "commit", "-q", "-m", "refs"
    ).returncode == 0
    assert cd.is_pointer("logs/gone.jsonl", root), "这条钉子拿的不是指针 ⇒ 等于空转"

    report = cd.scan(root)
    assert [item.line() for item in report.dead_refs] == [], report.dead_refs
    reasons = [s.reason for s in report.skips if s.where.startswith("docs/refs.md")]
    assert reasons == ["gitignored 产物（不随树分发）"], reasons


def test_placeholder_stem_and_angle_bracket_are_skipped(tmp_path: Path) -> None:
    """钉子 5：`docs/<卡号>.md` 与 `src/X.py` 是**占位符**，skip 不判死。

    `X.py` 这种「单字母大写词干」在正文里满地都是；实测本仓跟踪的 1964 个文件里
    末段是这种形状的 **0 个** ⇒ 认它不会吃掉真文件。
    改坏了会怎样：`src/X.py` 不存在、扩展名 `.py` 又在 `OWN_EXTS` 里 ⇒ 直接落成死指针（假红）。
    """
    root = _tree(tmp_path)
    (root / "src").mkdir()
    (root / "docs" / "ph.md").write_text("模板：`docs/<卡号>.md`\n示例：`src/X.py`\n",
                                         encoding="utf-8")
    assert cd.is_pointer("src/X.py", root), "这条钉子拿的不是指针 ⇒ 等于空转"

    report = cd.scan(root)
    assert [item.line() for item in report.dead_refs] == [], report.dead_refs
    reasons = {s.token: s.reason for s in report.skips if s.where.startswith("docs/ph.md")}
    assert reasons.get("docs/<卡号>.md") == "模板占位/通配，判不了", reasons
    assert reasons.get("src/X.py") == "模板占位/通配，判不了", reasons


def test_existing_file_with_unknown_ext_is_not_skipped(tmp_path: Path) -> None:
    """钉子 6：`.jsonl` **真在盘上** ⇒ 正常，既不判死也不算 skip。

    这是卡 F6 的正题：`gates/diag/notifications.jsonl`、`logs/timeflow.jsonl`、
    `data/timeflow.db` 这类文件实测在本仓真实存在（134 条），旧顺序靠扩展名先判
    ⇒ 全被写成「别仓路径」白跳过了。**存在就是存在，扩展名不算数。**
    """
    root = _tree(tmp_path)
    (root / "logs").mkdir()
    (root / "logs" / "timeflow.jsonl").write_text("{}\n", encoding="utf-8")
    (root / "docs" / "refs.md").write_text("日志：`logs/timeflow.jsonl`\n", encoding="utf-8")
    assert cd.ext_of("logs/timeflow.jsonl") == ".jsonl"
    assert ".jsonl" not in cd.OWN_EXTS, "OWN_EXTS 若收了 .jsonl，这条钉子就失去意义"
    assert cd.is_pointer("logs/timeflow.jsonl", root), "这条钉子拿的不是指针 ⇒ 等于空转"

    report = cd.scan(root)
    assert [item.line() for item in report.dead_refs] == [], report.dead_refs
    refs_skips = [s.reason for s in report.skips if s.where.startswith("docs/refs.md")]
    assert refs_skips == [], report.skips


def test_unknown_ext_and_missing_is_skipped_as_foreign(tmp_path: Path) -> None:
    """钉子 7：**不存在 且 类型本仓从不跟踪** ⇒ 才能推定为「别仓路径」。

    与钉子 6 成对：存在性优先不等于取消兜底。两条一起才说明「先查存在、再猜类型」，
    而不是简单的「不再看扩展名」。`src/core/verification.ts` 是 `复盘/DSH插件-*.md`
    里 50 条真实写法（引用的是别人的仓）。
    """
    root = _tree(tmp_path)
    (root / "src" / "core").mkdir(parents=True)
    (root / "docs" / "refs.md").write_text("别仓：`src/core/verification.ts`\n", encoding="utf-8")
    assert cd.ext_of("src/core/verification.ts") == ".ts"
    assert ".ts" not in cd.OWN_EXTS
    assert cd.is_pointer("src/core/verification.ts", root), "这条钉子拿的不是指针 ⇒ 等于空转"

    report = cd.scan(root)
    assert [item.line() for item in report.dead_refs] == [], report.dead_refs
    reasons = {s.token: s.reason for s in report.skips if s.where.startswith("docs/refs.md")}
    assert reasons.get("src/core/verification.ts") == (
        "`.ts` 不是本仓跟踪过的类型 ⇒ 判为别仓路径"
    ), reasons


def test_member_reference_resolves_after_reorder(tmp_path: Path) -> None:
    """钉子 8：`模块.成员()` 这种成员引用在重排后仍要解析，不能被当死指针。

    `tools/evidence_map.assertion_path()` 的扩展名是 `.assertion_path()` —— 不在 `OWN_EXTS`。
    旧顺序在这里直接判「别仓路径」；新顺序靠 `symbol_variants()` 在扩展名兜底**之前**
    把它摊回 `tools/evidence_map.py`。改坏了会怎样：它落进「别仓路径」桶里，
    于是「成员引用」这个边界名存实亡。
    """
    root = _tree(tmp_path)
    (root / "tools").mkdir()
    (root / "tools" / "evidence_map.py").write_text("def assertion_path():\n    return 1\n",
                                                   encoding="utf-8")
    token = "tools/evidence_map.assertion_path()"
    (root / "docs" / "refs.md").write_text(f"成员：`{token}`\n", encoding="utf-8")
    assert cd.ext_of(token) == ".assertion_path()", cd.ext_of(token)
    assert cd.is_pointer(token, root), "这条钉子拿的不是指针 ⇒ 等于空转"
    hits = [c for c in cd.symbol_variants(token)
            if cd.resolve(c, root / "docs" / "refs.md", root, "backtick") is not None]
    assert hits, f"symbol_variants 一个都没命中 ⇒ 这条钉子空转：{cd.symbol_variants(token)}"

    report = cd.scan(root)
    assert [item.line() for item in report.dead_refs] == [], report.dead_refs
    reasons = {s.token: s.reason for s in report.skips if s.where.startswith("docs/refs.md")}
    assert token not in reasons, reasons


# ------------------------ 卡 F6 / OWN_EXTS：手写集合必须能被 `git ls-files` 现证（不是自说自话）
def _tracked_exts() -> set[str]:
    """本仓**真跟踪过**的扩展名（`git ls-files` 实测；空集合就说明这条钉子空转）。"""
    out = _git(ROOT, "-c", "core.quotePath=false", "ls-files", "-z")
    assert out.returncode == 0, out.stderr
    return {cd.ext_of(p) for p in out.stdout.split("\0") if p}


def test_own_exts_covers_every_tracked_extension() -> None:
    """钉子 9：本仓跟踪过的扩展名**一个都不许落在** `OWN_EXTS` 外面。

    `OWN_EXTS` 是手写的（选 (b) 不选现算，理由写在 `scripts/check_docs.py` 里：非 git 树
    现算为空 ⇒ 一切落「别仓」= 放宽；且会随 `git add` 漂 ⇒ 同 HEAD 两树读数不同）。
    手写就得有东西钉住它，否则谁把 `.json` 删了都不会有人发现。
    放宽方向（加成员）这条不拦，收紧方向（删成员）当场红。
    """
    tracked = _tracked_exts()
    assert len(tracked) > 10, f"只读到 {len(tracked)} 种扩展名 ⇒ 这条钉子空转"
    assert "" not in cd.OWN_EXTS
    missing = sorted(tracked - set(cd.OWN_EXTS))
    assert missing == [], f"本仓真跟踪、却不在 OWN_EXTS 里（会全被判别仓）：{missing}"


def test_every_own_ext_is_justified() -> None:
    """钉子 10：`OWN_EXTS` 里每个成员**都要有理由** —— 要么有跟踪样本，要么写明为什么留。

    没有这条，`OWN_EXTS` 会慢慢长成一个「什么都不拒绝」的空集：每加一个成员，
    「别仓路径」这条边界就松一寸，而读数上看不出来。反向：删掉一条理由也红。
    """
    tracked = _tracked_exts()
    reasons = cd.OWN_EXTS_UNTRACKED_REASONS
    # ① 每个成员都得有理由：要么真有跟踪样本，要么在理由表里
    unexplained = sorted(
        ext for ext in cd.OWN_EXTS if ext not in tracked and ext not in reasons
    )
    assert unexplained == [], (
        f"这些成员既没有跟踪样本、也没写理由（说明不了它们为什么在集合里）：{unexplained}"
    )
    # ② 理由非空
    blank = sorted(ext for ext, why in reasons.items() if not why.strip())
    assert blank == [], f"理由表里有空理由：{blank}"
    # ③ 与跟踪样本**不相交**：理由表只放「当前没样本」的成员
    rotten = sorted(ext for ext in reasons if ext in tracked)
    assert rotten == [], (
        f"这些成员已经被本仓跟踪了，理由会腐烂 —— 把它们从理由表里删掉：{rotten}"
    )
    stripped = sorted(set(reasons) - set(cd.OWN_EXTS))
    assert stripped == [], f"理由表里有不在 OWN_EXTS 的成员：{stripped}"


# ------------------------------------------------- 判据 6（卡 E96）：`--file` 只判点名的几份
def _tree_with_baseline(tmp_path: Path) -> Path:
    """合成树 + 一份基线：`docs/ok.md` 自身合法，基线把当前读数钉成地板（ratchet 才判得出来）。"""
    root = _tree(tmp_path)
    (root / "docs" / "doc-debt-baseline.toml").write_text(
        '[baseline]\nupdated = "2026-01-01"\ntask = "T-TEST"\n'
        "dead_refs = 0\ndrift = 0\nsuperseded = 0\n",
        encoding="utf-8",
    )
    assert _run(root, "report")[0] == 0, "地板没钉住 ⇒ 后面的「涨到」是假的"
    return root


def test_file_scope_reports_only_the_named_doc_and_goes_nonzero(tmp_path: Path) -> None:
    """★ `--file`：坏掉的**只**出现在点名文件里 ⇒ 只看那一份时红，全仓也红；反面两棵树各一份坏。

    这条钉的是**收窄**：全仓两处坏、`--file` 只点一处 ⇒ 读数必须是 1 条，且只点出那一份。
    """
    root = _tree_with_baseline(tmp_path)
    (root / "docs" / "bad-a.md").write_text("看 `docs/nope-a.md`\n", encoding="utf-8")
    (root / "docs" / "bad-b.md").write_text("看 `docs/nope-b.md`\n", encoding="utf-8")
    report = cd.scan(root)
    assert sorted(item.line() for item in report.dead_refs) == [
        "docs/bad-a.md:1 → docs/nope-a.md",
        "docs/bad-b.md:1 → docs/nope-b.md",
    ], [item.line() for item in report.dead_refs]

    code, text = _run(root, "report", only=["docs/bad-a.md"])
    assert code == 1, text                      # 涨到 2 ⇒ 1 条（基线 0，只不许升）
    assert "docs/bad-a.md:1 → docs/nope-a.md" in text
    assert "nope-b.md" not in text, text        # 没点名的那一份**不许**出现在读数里
    total = cd.scan(root).scanned["文件"]
    assert f"[note] --file 只看 1 份（全仓 {total} 份）" in text, text

    # 点的是好的那一份 ⇒ report 档退 0（没债、没超基线），且不许把别人的债算进来
    code_ok, text_ok = _run(root, "report", only=["docs/ok.md"])
    assert code_ok == 0, text_ok
    assert "nope-a.md" not in text_ok and "nope-b.md" not in text_ok, text_ok
    # ★ 未点名的那些**仍然是 skip**（本来就没判）—— 收窄不等于替它们背书
    assert f"[note] --file 只看 1 份（全仓 {total} 份）" in text_ok, text_ok


def test_file_scope_accepts_absolute_and_backslash_and_dedupes(tmp_path: Path) -> None:
    """`--file` 的写法兼容：绝对路径、反斜杠、`./` 前缀、同一份点两次 ⇒ 只算一份。"""
    root = _tree_with_baseline(tmp_path)
    (root / "docs" / "bad.md").write_text("看 `docs/nope.md`\n", encoding="utf-8")
    for token in (
        str(root / "docs" / "bad.md"),
        "docs\\bad.md",
        "./docs/bad.md",
    ):
        report = cd.scan(root, only=[token])
        assert [item.line() for item in report.dead_refs] == ["docs/bad.md:1 → docs/nope.md"], (
            token, [item.line() for item in report.dead_refs]
        )
        assert report.scanned["文件"] == 1, (token, report.scanned)
        assert any("只看 1 份（全仓" in note for note in report.notes), report.notes

    twice = cd.scan(root, only=["docs/bad.md", "./docs/bad.md", str(root / "docs" / "bad.md")])
    assert twice.scanned["文件"] == 1, twice.scanned
    total2 = cd.scan(root).scanned["文件"]
    assert [note for note in twice.notes if note.startswith("--file 只看")] == [
        f"--file 只看 1 份（全仓 {total2} 份）"
    ], twice.notes


def test_file_scope_with_no_hits_is_red_not_green(tmp_path: Path) -> None:
    """★ 反向钉子：`--file` 点了一个**不在扫描集里**的文件 ⇒ 退 1 且明说（空集不许当通过）。"""
    root = _tree_with_baseline(tmp_path)
    code, text = _run(root, "report", only=["docs/does-not-exist.md"])
    assert code == 1, text
    assert "给的文件一份都没在扫描集里" in text, text
    assert "[note] --file 只看 0 份（全仓" in text, text
    assert "docs/does-not-exist.md" in text, text     # 点名说清是哪一条没命中

    # 一类"点了但没入库"的也不行
    code2, text2 = _run(root, "report", only=[])
    assert code2 == 1, text2
    assert "给的文件一份都没在扫描集里" in text2, text2


def test_no_file_flag_keeps_old_behaviour_byte_for_byte(tmp_path: Path) -> None:
    """★「不给 `--file` 时行为与今天一致」：两棵一样的树，一次隐式一次显式，输出逐字相同。"""
    left = _tree_with_baseline(tmp_path / "left")
    right = _tree_with_baseline(tmp_path / "right")
    for root in (left, right):
        (root / "docs" / "bad.md").write_text("看 `docs/nope.md`\n", encoding="utf-8")

    lines_old: list[str] = []
    code_old = cd.main(left, "report", out=lines_old.append)
    lines_new: list[str] = []
    code_new = cd.main(right, "report", out=lines_new.append, only=None)
    old_text = "\n".join(lines_old).replace(str(left), "<root>")
    new_text = "\n".join(lines_new).replace(str(right), "<root>")
    assert code_old == code_new == 1, (code_old, code_new)
    assert old_text == new_text, "不给 --file 时输出变了 —— 那是回归，不是新功能"

    # 老签名（不传 only）与旧调用方一致：位置参数 + 关键字参数都不受影响
    assert cd.scan(left).counts() == cd.scan(right, only=None).counts()


def test_file_scope_does_not_narrow_the_drift_leg(tmp_path: Path) -> None:
    """★ drift 腿**不吃** docs 列表：`--file` 点了别的文件，drift 判据面（跳过项）不变。"""
    root = _tree_with_baseline(tmp_path)
    (root / "docs" / "bad.md").write_text("看 `docs/nope.md`\n", encoding="utf-8")
    wide = cd.scan(root)
    narrow = cd.scan(root, only=["docs/ok.md"])
    assert len(narrow.drift) == len(wide.drift), (narrow.drift, wide.drift)
    assert narrow.drift_judged == wide.drift_judged, (narrow.drift_judged, wide.drift_judged)
    # 死指针这一腿确实被收窄了（证明上面那条不是因为"两条腿都没动"）
    assert len(narrow.dead_refs) < len(wide.dead_refs), (narrow.dead_refs, wide.dead_refs)


def _tree_with_slack(tmp_path: Path, was: int) -> Path:
    """合成树 + 一份**比现状宽松**的基线（`was` 条地板）：这样全仓读数才判得出来「降了」。"""
    root = _tree(tmp_path)
    (root / "docs" / "doc-debt-baseline.toml").write_text(
        f'[baseline]\nupdated = "2026-01-01"\ntask = "T-TEST"\n'
        f"dead_refs = {was}\ndrift = 0\nsuperseded = 0\n",
        encoding="utf-8",
    )
    return root


def test_file_scope_never_compares_a_narrowed_reading_to_the_whole_repo_baseline(
    tmp_path: Path,
) -> None:
    """★ 复核钉子：`--file` 只看了 N 份 ⇒ 读数**不许**跟全仓基线比，更不许教人下调基线。

    反面（这就是 bug 的形状）：全仓 1 条死指针、基线记 2 条。收窄到「干净的那一份」时
    读数 0 —— 旧代码会印 `dead_refs 从 2 降到 0（可以把基线调低到 0）`，等于把
    「这次只看了 1 份」说成「欠账全清」，照着调低基线就把这道门拆了。
    """
    root = _tree_with_slack(tmp_path, 2)
    (root / "docs" / "bad.md").write_text("看 `docs/nope.md`\n", encoding="utf-8")

    # 全仓档：ratchet 照旧能判「降了」，且仍允许下调基线（这是全仓读数，说的是实话）
    code_all, text_all = _run(root, "report")
    assert "dead_refs 从 2 降到 1（可以把基线调低到 1）" in text_all, text_all
    assert "CHECK_DOCS: 死指针 1（基线 2，-1）" in text_all, text_all

    # 收窄档：一个字都不许提「降到 / 调低」，且明说这是收窄读数
    code_one, text_one = _run(root, "report", only=["docs/ok.md"])
    assert code_one == 0, text_one
    assert "降到" not in text_one, f"收窄读数不许说「降到」：\n{text_one}"
    assert "可以把基线调低" not in text_one, text_one
    assert "[ratchet] 收窄读数不比基线（--file 只看了 1 份）" in text_one, text_one
    assert "CHECK_DOCS: 死指针 0（收窄读数，不比基线）" in text_one, text_one
    assert "CHECK_DOCS: 死指针 0（基线 2，-2）" not in text_one, text_one


def test_file_scope_still_bites_when_the_narrowed_reading_is_over_the_baseline(
    tmp_path: Path,
) -> None:
    """★ 收窄**不是**关掉 ratchet：局部超地板 ⇒ 全仓必然也超 ⇒ 照旧红、照旧说「涨到」。"""
    root = _tree_with_baseline(tmp_path)          # 地板 0
    (root / "docs" / "bad.md").write_text("看 `docs/nope.md`\n", encoding="utf-8")
    code, text = _run(root, "report", only=["docs/bad.md"])
    assert code == 1, text
    assert "dead_refs 从 0 涨到 1（基线只能降不能升）" in text, text
    assert "降到" not in text, text


def test_json_output_only_grows_a_key_when_narrowed(tmp_path: Path) -> None:
    """`--json`：收窄时多一个 `"narrowed": true`；全仓档的 JSON 一个键都不多（逐字节同旧）。"""
    import json

    root = _tree_with_baseline(tmp_path)
    (root / "docs" / "bad.md").write_text("看 `docs/nope.md`\n", encoding="utf-8")
    wide = cd.as_json(cd.scan(root))
    narrow = cd.as_json(cd.scan(root, only=["docs/ok.md"]))
    assert "narrowed" not in wide, sorted(wide)
    assert narrow.get("narrowed") is True, sorted(narrow)
    assert set(narrow) - set(wide) == {"narrowed"}, (sorted(narrow), sorted(wide))
    assert json.dumps(wide, ensure_ascii=False) == json.dumps(
        cd.as_json(cd.scan(root, only=None)), ensure_ascii=False
    )


def test_file_flag_is_parsed_as_repeatable() -> None:
    """CLI 面：`--file a --file b` 收成两条（append），不给是 None（默认仍全仓）。"""
    assert cd.parse_args([]).file is None
    got = cd.parse_args(["--file", "docs/a.md", "--file", "docs/b.md"]).file
    assert got == ["docs/a.md", "docs/b.md"], got
