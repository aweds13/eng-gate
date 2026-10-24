"""主控复核器（`tools/wb_review.py`，T-G84）的测试 —— 给"这一笔算不算数"的判据上护栏。

这个工具的价值全在**判据**上：漏一条的代价是把没验过的东西当验过了。
所以零件层逐条喂**该失败的输入**（缺 trailer / 门禁 rev 对不上 / 越界改动 / 只读卡改了文件），
数据层拿**真仓库的 HEAD** 验一次（本项目的提交流程应当让它通过）。

真跑的 audit 那一步很慢（~4 秒），所以零件层不碰它；CLI 层用 `--json` 走一遍读真实结果。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.append(str(ROOT / "scripts"))

import run_gates as rg  # noqa: E402 —— 第 ③′ 档的门表真源（卡 147）
import wb_review as wr  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上


def _body(**trailers: str) -> str:
    lines = ["feat(x): 干了一件事（T-999）", "", "正文随便写点。", ""]
    order = ["Task", "Refs", "Ledger", "Gates"]
    for key in order:
        if key in trailers:
            lines.append(f"{key}: {trailers[key]}")
    return "\n".join(lines) + "\n"


GOOD_TRAILERS = {"Task": "T-999", "Ledger": "215 条", "Gates": "pytest 全绿"}


# ------------------------------------------------------------------ ② trailer


def test_trailers_pass_on_a_well_formed_message() -> None:
    problems, found = wr.check_trailers(_body(**GOOD_TRAILERS))
    assert problems == []
    assert found["Task"] == "T-999"


def test_trailers_catch_two_task_ids() -> None:
    """`Task:` 只能有一个台账编号（多出来的写 `Refs:`）—— 这是门禁⑧的同一件事。"""
    body = _body(**GOOD_TRAILERS) + "Task: T-998\n"
    problems, _ = wr.check_trailers(body)
    assert any("恰好一个" in p for p in problems)


def test_trailers_catch_a_missing_gates_line() -> None:
    problems, _ = wr.check_trailers(_body(Task="T-999", Ledger="215 条"))
    assert any("缺 `Gates:`" in p for p in problems)


# ------------------------------------------------------------------ ③ 门禁为谁而跑


def _payload(**over: object) -> dict:
    base: dict = {
        "rev": "abc1234", "ok": True, "docs_sync_ok": True, "docs_sync_missing": [],
        "gates": [{"name": "pytest", "exit_code": 0}, {"name": "audit", "exit_code": 0}],
    }
    base.update(over)
    return base


def test_gate_evidence_passes_when_run_for_this_commit() -> None:
    assert wr.check_gate_evidence(_payload(), "abc1234") == []


def test_gate_evidence_catches_a_stale_run() -> None:
    """★ 最要紧的一条：一次门禁跑完提交**两笔**，第二笔就是"没验过"。"""
    problems = wr.check_gate_evidence(_payload(rev="oldc0de"), "abc1234")
    assert any("不是为这一笔跑的" in p for p in problems)


def test_gate_evidence_catches_a_failed_gate_or_unsynced_docs() -> None:
    gates = [{"name": "pytest", "exit_code": 0}, {"name": "audit", "exit_code": 1}]
    problems = wr.check_gate_evidence(_payload(gates=gates, docs_sync_ok=False), "abc1234")
    assert any("有门没过" in p and "audit" in p for p in problems)
    assert any("没同步" in p for p in problems)


def test_gate_evidence_catches_an_empty_or_failed_artifact() -> None:
    assert any("没有任何门" in p for p in wr.check_gate_evidence(_payload(gates=[]), "abc1234"))
    assert any("ok 不是 true" in p for p in wr.check_gate_evidence(_payload(ok=False), "abc1234"))


# ------------------------------------------------------------------ ④ 改动范围


def test_read_only_card_may_not_touch_any_tracked_file() -> None:
    problems = wr.check_files(["src/a.py"], read_only=True, allow=[])
    assert any("只读卡不许改" in p for p in problems)
    assert wr.check_files([], read_only=True, allow=[]) == []


def test_allowlist_flags_files_outside_it() -> None:
    problems = wr.check_files(["src/a.py", "docs/x.md"], read_only=False, allow=["src/**"])
    assert any("不在白名单里" in p and "docs/x.md" in p for p in problems)
    assert wr.check_files(["src/a.py"], read_only=False, allow=["src/**"]) == []


def test_missing_allowlist_is_refused_not_silently_passed() -> None:
    """不给白名单又不说只读 → **拒绝**，别默认放行（默认放行等于没查）。"""
    problems = wr.check_files(["src/a.py"], read_only=False, allow=[])
    assert any("没有给白名单" in p for p in problems)


# ------------------------------------- ④′ 派生物噪声（卡 210 · T-G320）
#
# 收口链第 ⑥ 步（`tools/pool/landing.py`）**无条件**把「三份本台片段 + 三份共享文档 +
# 两个门禁产物」并进 `allow` 才提交；而复核只拿到调用方给的 `--allow`（不含它们）⇒ 连着
# 6 笔都被**自己的派生物**判成"越界"（噪声，`gates/review/*.json` 里同一条）。本档钉：
# 那批派生物是**预期内**，**只有**「`allow` ∪ 派生物清单」**之外**的改动才报、才红。
# ★★ 这条不许放松成"什么都不报"（见下面的反例）。

#: 一份典型派生物（照 `e0a6dc8` / `T-G313` 那 7 条的样子）—— 判据与钉子都拿它当样例。
DERIVED_SAMPLE = (
    "docs/changelog.d/T-G999.md",
    "docs/traceability.d/T-G999.toml",
    "复盘/交接.d/T-G999.md",
    "docs/changelog.md",
    "docs/traceability.toml",
    "复盘/交接-重构进度.md",
    "gates/last.json",
    "gates/reuse.json",
)


def test_derived_artifacts_are_expected_not_outside() -> None:
    """① **绿**：一笔只含「本卡 allow + 派生物清单」的改动 ⇒ **problems 为空**（噪声归零）。"""
    files = ["src/a.py", *DERIVED_SAMPLE]
    assert wr.check_files(files, read_only=False, allow=["src/**"]) == []


def test_rogue_file_alongside_derived_is_still_refused() -> None:
    """② ★★ **红（反例，最重要）**：同一堆改动里**多塞一个两边都不在的文件** ⇒
    **必须报出来并点名它**；再把它删掉 ⇒ **回到绿**（判据没被放松成"什么都不报"）。"""
    files = ["src/a.py", *DERIVED_SAMPLE, "docs/rogue.md"]
    problems = wr.check_files(files, read_only=False, allow=["src/**"])
    assert len(problems) == 1, problems
    assert "docs/rogue.md" in problems[0], "越界文件没被点名"
    assert "docs/changelog.md" not in problems[0], "派生物被误当成越界点名了"
    # 把那个越界文件删掉 ⇒ 回到绿
    assert wr.check_files(["src/a.py", *DERIVED_SAMPLE], read_only=False, allow=["src/**"]) == []


def test_classify_changes_separates_the_two_columns() -> None:
    """③ 报告两栏分开：`classify_changes()` 把「派生物（预期）」与「越界」各归各（互斥）。"""
    derived_hits, outside = wr.classify_changes(
        ["src/a.py", "gates/last.json", "docs/rogue.md"], ["src/**"])
    assert derived_hits == ["gates/last.json"]
    assert outside == ["docs/rogue.md"]


def test_derived_globs_are_pinned_and_match_landing() -> None:
    """④ ★ **清单钉子**：派生物清单逐字钉住（改了它 ⇒ 这里红），且与真源
    `tools/pool/landing.py` 的 `DOCS` / `GATES` **对齐**（那边漂了 ⇒ 这里也红）。"""
    assert wr.DERIVED_GLOBS == (
        "docs/changelog.d/*.md",
        "docs/traceability.d/*.toml",
        "复盘/交接.d/*.md",
        "docs/changelog.md",
        "docs/traceability.toml",
        "复盘/交接-重构进度.md",
        "gates/last.json",
        "gates/reuse.json",
    )
    from pool import landing  # noqa: PLC0415 —— tools/ 已在 sys.path 里；landing 是清单真源
    for path in (*landing.DOCS, *landing.GATES):
        assert path in wr.DERIVED_GLOBS, f"派生物清单漏了 landing 的 {path}"


def _derived_repo(tmp_path: Path) -> Path:
    """造一棵能走 `--rev` 的仓库：seed 一笔 → 带着「本卡 allow + 派生物清单」的第二笔。"""
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    for rel in ("docs/changelog.d", "docs/traceability.d", "复盘/交接.d", "gates"):
        (repo / rel).mkdir(parents=True)
    (repo / "src" / "a.py").write_text("a\n", encoding="utf-8")
    _run_git(repo, "init", "-q", "-b", "main")
    _run_git(repo, "config", "user.email", "t@local")
    _run_git(repo, "config", "user.name", "t")
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-q", "-m", "seed")
    parent = _run_git(repo, "rev-parse", "--short", "HEAD").strip()
    payload = {"rev": parent, "ok": True, "docs_sync_ok": True, "docs_sync_missing": [],
               "gates": [{"name": "pytest", "exit_code": 0}]}
    files = ("docs/changelog.d/T-G999.md", "docs/traceability.d/T-G999.toml",
             "复盘/交接.d/T-G999.md", "docs/changelog.md", "docs/traceability.toml",
             "复盘/交接-重构进度.md")
    for rel in files:
        (repo / rel).write_text("x\n", encoding="utf-8")
    (repo / "gates" / "last.json").write_text(json.dumps(payload), encoding="utf-8")
    (repo / "src" / "a.py").write_text("b\n", encoding="utf-8")
    msg = "feat: 一笔\n\nTask: T-G999\nLedger: 1 条\nGates: 全量门禁绿\n"
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-q", "-m", msg)
    return repo


def test_cli_commit_with_only_allow_and_derived_passes(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """⑤（CLI 层）一笔只含「本卡 allow + 派生物清单」的提交 ⇒ 复核**退 0** ——
    证明这条判据在整条 `--rev` 流程里也认（不止零件层），且输出里有「派生物（预期）」那一栏。"""
    repo = _derived_repo(tmp_path)
    monkeypatch.setattr(wr, "ROOT", repo)
    monkeypatch.setattr(wr, "audit_verdict", lambda: ([], "审计通过 ✅"))
    code = wr.main(["--rev", "HEAD", "--branch", "main", "--allow", "src/**", "--dirty-ok"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "派生物（预期）" in out


# ------------------------------------------------------------------ 数据层：真 git（自建仓）


def test_a_seal_commit_passes_the_gate_evidence_check(tmp_path: Path, monkeypatch) -> None:
    """拿**真 git** 验第 ③ 条：封存笔里 `gates/last.json` 的 `rev` 指**这一笔的父提交**。

    ★ 老版本断言的是**本仓 HEAD 这一笔**（「本项目的提交流程应当让 HEAD 通过」）—— 那是时序错位：
    门禁在**提交前**跑，HEAD 那时还是父提交，它带的 `last.json` 是**上一笔**封的。只要中间夹一笔
    文档提交（台账 / 卡规格 / 决策记录），`rev` 就再也追不上 `parent`，这条**从此永远红**；而
    `seal()` 又不许在 `ok=false` 时写封存（`scripts/run_gates.py` 里先判 `ok`）⇒ 死锁，谁也没法再
    封一次。同一棵树「提交前绿、提交后红」是判据自己的毛病，不是被查对象变了（同 `T-G87` 那颗
    定时炸弹的族，本文件下半段已有先例）。

    现在自己搭仓：`_derived_repo` 造出来的正是「**父提交封的，这一笔把它带上**」的形态；
    `monkeypatch` 只换 `wb_review.ROOT`，`tools/` 一行不动，判据不再依赖真实历史的运气。
    """
    repo = _derived_repo(tmp_path)
    monkeypatch.setattr(wr, "ROOT", repo)
    sha = wr.git("rev-parse", "--short", "HEAD")
    parent = wr.git("rev-parse", "--short", f"{sha}^")
    payload = json.loads(wr.git("show", f"{sha}:gates/last.json"))
    assert payload.get("ok") is True
    assert wr._resolve_commit(str(payload.get("rev"))) == wr._resolve_commit(parent), (
        "gates/last.json 的 rev 应当指向这一笔的父提交（比提交，不比字符串长度）"
    )
    assert wr.check_gate_evidence(payload, parent) == []


def test_chinese_paths_are_not_escaped(tmp_path: Path, monkeypatch) -> None:
    """★ 中文路径必须原样出来：被转义成 `\\345\\244...` 会让白名单把中文路径全判成越界。

    ★ T-G87 修的是一条**定时炸弹**：老判据断言的是**真仓库 HEAD 这一笔**里必须出现
    `复盘/…`。可门禁是在**提交前**跑的 —— 那时 HEAD 还是**父提交**（恰好带中文路径）。
    提交一落，HEAD 变成自己那一笔，只要它全是 ASCII 路径，**这条测试从此永远红**：
    同一棵树「提交前绿、提交后红」是判据自己的毛病，不是被查对象变了（实测踩到）。
    现在**自己搭一个临时仓库**：`monkeypatch` 只换掉 `wb_review.ROOT`，`tools/` 一行不动，
    判据不再依赖真实历史的运气。★ 还先证明**普通 git 确实会转义** —— 少了这一半，
    夹具就看不见这个现象（同族规矩：**判据自己要能证明它看得到东西**）。
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    def plain(*args: str) -> str:
        """不带 `core.quotepath=false` 的 git —— 用来证明这个夹具真看得见转义。"""
        done = subprocess.run(
            ["git", *args], cwd=str(repo), capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        assert done.returncode == 0, done.stderr
        return done.stdout

    plain("init", "-q", "-b", "main")
    plain("config", "user.email", "test@local")
    plain("config", "user.name", "test")
    (repo / "复盘").mkdir()
    (repo / "复盘" / "中文.md").write_text("x", encoding="utf-8")
    plain("add", "复盘/中文.md")
    plain("commit", "-q", "-m", "中文路径")

    escaped = plain("show", "--name-only", "--format=", "HEAD").splitlines()
    assert any(n.startswith('"') for n in escaped), f"普通 git 应当转义：{escaped}"

    monkeypatch.setattr(wr, "ROOT", repo)
    names = wr.git("show", "--name-only", "--format=", "HEAD").splitlines()
    assert "复盘/中文.md" in names, f"wr.git() 应当原样给出中文路径：{names}"
    assert not [n for n in names if n.startswith('"')], f"有被转义的路径：{names}"


# ------------------------------------------------------------------ ⑥ 实际改动 vs 权威域
#
# 治 GLM 审查「三.1」（卡 131 · T-G228）：栅栏的域检查吃的是"交申请一方自己填的清单"，
# 卡树里**真的改了什么**从不参与判断 ⇒ 越界只要不自报就全绿。本档拿"卡树实际改动"
# （`git status --porcelain -uall --no-renames`，含未跟踪）与"权威域"（栅栏预声明优先、
# 队列次之；两个都查不到就拒）比对，域外即拒、逐个点名。


def _run_git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def _card_repo(tmp_path: Path, paths: list[str] | None = None) -> Path:
    """造一棵卡树：一个真 git 仓库 + 一份栅栏预声明（域默认 `src/**`）。

    ★ 预声明目录按本仓口径忽略（`.gitignore` 里 `gates/diag/*`），否则它自己会进 `git status`
      被当成"域外改动"，把每条钉子污染成假红（夹具自己踩过一次）。
    """
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / "src" / "a.py").write_text("a\n", encoding="utf-8")
    (repo / "docs" / "x.md").write_text("x\n", encoding="utf-8")
    _run_git(repo, "init", "-q", "-b", "main")
    _run_git(repo, "config", "user.email", "t@local")
    _run_git(repo, "config", "user.name", "t")
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-q", "-m", "seed")
    (repo / ".git" / "info" / "exclude").write_text("gates/diag/\n", encoding="utf-8")
    batch = repo / "gates" / "diag" / "batch"
    batch.mkdir(parents=True)
    dom = json.dumps(paths or ["src/**"])
    (batch / "B-X.toml").write_text(
        f'id = "B-X"\nwhy = "夹具"\n\n[[member]]\nid = "M-1"\nlayer = "门禁层"\n'
        f'what = "x"\npaths = {dom}\n',
        encoding="utf-8",
    )
    return repo


def test_changed_paths_reads_porcelain_including_untracked() -> None:
    """零件层：porcelain 原文 → 路径集合（含 `??` 未跟踪，`-z` 不用、箭头也认）。"""
    text = " M docs/x.md\n?? docs/new.md\nD  src/gone.py\n"
    assert wr.changed_paths(text) == ["docs/x.md", "docs/new.md", "src/gone.py"]


def test_domain_of_manifest_text_reads_member_paths() -> None:
    """零件层：从预声明 TOML 原文取某成员的 `paths`；没有这个成员 → `None`（不是空域）。"""
    text = 'id = "B"\n[[member]]\nid = "M-1"\npaths = ["a/**", "b.py"]\n'
    assert wr.domain_of_manifest_text(text, "M-1") == ["a/**", "b.py"]
    assert wr.domain_of_manifest_text(text, "M-2") is None


def test_actual_change_outside_domain_is_refused(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """① ★★ 自报清单里没有、但树里真改了 ⇒ 必须拒并点名（域 `src/**`，真改的是 `docs/x.md`）。"""
    repo = _card_repo(tmp_path)
    (repo / "docs" / "x.md").write_text("改了\n", encoding="utf-8")
    monkeypatch.setattr(wr, "ROOT", repo)
    rc = wr.main(["--card", "M-1", "--task", "B-X", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert data["outside"] == ["docs/x.md"]
    assert any("docs/x.md" in p for p in data["problems"])


def test_actual_change_inside_domain_passes(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """② 域内改动 ⇒ 过（别误伤）。"""
    repo = _card_repo(tmp_path)
    (repo / "src" / "a.py").write_text("改了\n", encoding="utf-8")
    monkeypatch.setattr(wr, "ROOT", repo)
    rc = wr.main(["--card", "M-1", "--task", "B-X"])
    assert rc == 0, capsys.readouterr().out


def test_untracked_new_file_counts(tmp_path: Path, monkeypatch, capsys) -> None:
    """③ 未跟踪的新文件（`??`）**也要算**：域外新建 ⇒ 拒；域内新建 ⇒ 过。"""
    repo = _card_repo(tmp_path)
    (repo / "docs" / "new.md").write_text("新\n", encoding="utf-8")
    monkeypatch.setattr(wr, "ROOT", repo)
    rc = wr.main(["--card", "M-1", "--task", "B-X", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert "docs/new.md" in data["outside"]

    (repo / "docs" / "new.md").unlink()
    (repo / "src" / "new.py").write_text("新\n", encoding="utf-8")
    rc2 = wr.main(["--card", "M-1", "--task", "B-X"])
    assert rc2 == 0, capsys.readouterr().out


def test_waive_exempts_and_records(tmp_path: Path, monkeypatch, capsys) -> None:
    """④ 豁免留痕：`--waive <域外文件>` ⇒ 放行，输出有"豁免"行、`--json` 有字段。"""
    repo = _card_repo(tmp_path)
    (repo / "docs" / "x.md").write_text("改了\n", encoding="utf-8")
    monkeypatch.setattr(wr, "ROOT", repo)
    rc = wr.main(["--card", "M-1", "--task", "B-X", "--waive", "docs/x.md"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "豁免" in out
    rc2 = wr.main(["--card", "M-1", "--task", "B-X", "--waive", "docs/x.md", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert rc2 == 0
    assert data["waived"] == ["docs/x.md"] and data["outside"] == []


def test_missing_authoritative_domain_is_refused(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """⑤ 权威域查不到（既不在预声明、也不在队列）⇒ 拒 —— 别猜空域（空域骗过一切守卫）。"""
    repo = _card_repo(tmp_path)
    (repo / "src" / "a.py").write_text("改了\n", encoding="utf-8")
    monkeypatch.setattr(wr, "ROOT", repo)
    rc = wr.main(["--card", "卡不存在", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert any("查不到" in p for p in data["problems"])


def test_hand_typed_allow_is_disclosed(tmp_path: Path, monkeypatch, capsys) -> None:
    """⑥ 没有权威域而给了 `--allow` ⇒ 输出里必须有"手打白名单"那一行（降级要说出来）。"""
    repo = _card_repo(tmp_path)
    (repo / "src" / "a.py").write_text("改了\n", encoding="utf-8")
    monkeypatch.setattr(wr, "ROOT", repo)
    rc = wr.main(["--card", "卡不存在", "--allow", "src/**"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "手打白名单" in out


def test_authoritative_domain_beats_hand_typed_allow(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """权威域在时，手打 `--allow` **不再能接管** —— 否则就是被审查点名的"手打接力"。"""
    repo = _card_repo(tmp_path)
    (repo / "docs" / "x.md").write_text("改了\n", encoding="utf-8")
    monkeypatch.setattr(wr, "ROOT", repo)
    rc = wr.main(["--card", "M-1", "--task", "B-X", "--allow", "docs/**"])
    assert rc == 1, capsys.readouterr().out


# ------------------------------------------------------------------ ⓖ Gates trailer 真伪
#
# 治外部审查 GLM-5.3「三.2」：`audit_progress` 只查 `Gates:` trailer **在不在**，不查**真伪**；
# 而同一条链路的生成端有 `--no-gate` / `--commit-only` 两个模式（会写死一句"全量门禁绿 + seal"）。
# 本档拿 trailer 的内容与 `gates/last.json` 的 ok/rev **对账**（分工：存在性归 audit，真伪归这里）。


def test_gates_trailer_truth_forged_green_is_refused() -> None:
    """① ★ 伪造"门禁绿"：`ok=false`（或 `rev` 对不上）而 trailer 说绿 ⇒ **拒**，
    且报错里**同时**出现 trailer 原文与 `last.json` 的读数（"为什么说你假"）。"""
    p1, note = wr.check_gates_trailer_truth(
        "全量门禁绿 + seal", _payload(ok=False), "abc1234")
    assert note == ""
    assert len(p1) == 1
    assert "全量门禁绿 + seal" in p1[0] and "ok=False" in p1[0]
    p2, _ = wr.check_gates_trailer_truth(
        "门禁绿 + seal", _payload(rev="oldc0de"), "abc1234")
    assert any("伪造门禁结论" in p for p in p2)


def test_gates_trailer_truth_real_green_passes() -> None:
    """② 真绿：`ok=true` + `rev` = 父提交 + trailer 说绿 ⇒ **过**。"""
    assert wr.check_gates_trailer_truth("全量门禁绿 + seal", _payload(), "abc1234") == ([], "")


def test_gates_trailer_truth_real_green_that_denies_it_is_refused() -> None:
    """②' 真绿那一笔 trailer 若写"没跑门禁"：声称与事实不符 ⇒ 也拒（判据 (a) 的另一半）。"""
    problems, _ = wr.check_gates_trailer_truth("没跑门禁", _payload(), "abc1234")
    assert any("真跑过全量门禁" in p and "没声称" in p for p in problems)


def test_gates_trailer_truth_no_gate_form_is_disclosed() -> None:
    """③ `--no-gate` 形态：没跑门禁而 trailer 主动披露 ⇒ **放行** + 标"没有本轮门禁结论"。"""
    problems, note = wr.check_gates_trailer_truth(
        "未跑门禁（--no-gate）", _payload(ok=False), "abc1234")
    assert problems == []
    assert "没有" in note and "本轮门禁结论" in note


def test_gates_trailer_truth_commit_only_form_is_disclosed() -> None:
    """④ `--commit-only` 形态：trailer 写"复用已绿的那一趟" ⇒ **放行**并标注。"""
    problems, note = wr.check_gates_trailer_truth(
        "复用已绿的那一趟", _payload(rev="oldc0de"), "abc1234")
    assert problems == []
    assert "本轮门禁结论" in note


def test_task_single_still_enforced_alongside_the_truth_check() -> None:
    """⑤ 加了这一档之后 `Task:` 仍**恰好一个** —— 新判据不替换旧 trailer 判据。"""
    problems, found = wr.check_trailers(_body(**GOOD_TRAILERS) + "Task: T-998\n")
    assert any("恰好一个" in p for p in problems)
    assert found["Gates"] == GOOD_TRAILERS["Gates"]


def _rev_repo(
    tmp_path: Path, *, last_ok: bool, gates_line: str,
    gates: list[dict] | None = None, tree_scope: bool = False,
) -> Path:
    """造一棵能走 `--rev` 流程的小仓库：seed 提交 → 带 `gates/last.json` 的第二笔提交。"""
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "gates").mkdir()
    (repo / "src" / "a.py").write_text("a\n", encoding="utf-8")
    _run_git(repo, "init", "-q", "-b", "main")
    _run_git(repo, "config", "user.email", "t@local")
    _run_git(repo, "config", "user.name", "t")
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-q", "-m", "seed")
    parent = _run_git(repo, "rev-parse", "--short", "HEAD").strip()
    payload = {"rev": parent, "ok": last_ok, "docs_sync_ok": True,
               "docs_sync_missing": [],
               "gates": gates if gates is not None else [{"name": "pytest", "exit_code": 0}]}
    if tree_scope:  # 让夹具像"门禁自己写出来的产物"（第 ③′ 档只对真产物判红）
        payload["tree_scope"] = "worktree-minus-gates"
    (repo / "gates" / "last.json").write_text(json.dumps(payload), encoding="utf-8")
    msg = f"feat: 一笔\n\nTask: T-999\nLedger: 1 条\nGates: {gates_line}\n"
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-q", "-m", msg)
    return repo


def test_no_gate_form_is_surfaced_in_output_and_json(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """③（CLI 层）`ok=false` 且 trailer 披露"没跑门禁" ⇒ 真伪那一档**不报伪造**，
    且**输出与 `--json` 都给**"没有本轮门禁结论"（不许把它当"门禁绿"混过去）。"""
    repo = _rev_repo(tmp_path, last_ok=False, gates_line="未跑门禁（--no-gate）")
    monkeypatch.setattr(wr, "ROOT", repo)
    monkeypatch.setattr(wr, "audit_verdict", lambda: ([], "审计通过 ✅"))
    wr.main(["--rev", "HEAD", "--branch", "main", "--allow", "**", "--dirty-ok", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["no_round_gate_verdict"] is True
    assert "本轮门禁结论" in data["gates_trailer_note"]
    assert not any("伪造门禁结论" in p for p in data["problems"])
    wr.main(["--rev", "HEAD", "--branch", "main", "--allow", "**", "--dirty-ok"])
    out = capsys.readouterr().out
    assert "本轮门禁结论" in out


# ------------------------------------------ ③′ 全量门禁（门数 / affected 标记）
#
# 卡 147 · T-G247 —— 来路：卡 140 自己发现的后门。`tools/wb_verify.py` 查 `EXPECT_GATES`
# 会拦"部分跑的 `last.json`"，但 `wb_review.py` 原来只查 `ok`/`rev`/每门 `exit_code`，
# **不查门数** ⇒ 若有人把 `--affected` 那一趟的 `last.json` 提交上去，复核主链可能不拦。
# 本档：门数必须 = 该仓**当前应有**的门数（从 `rg.build_jobs` **现读**，不写死 17），
# 且不许带 `affected` 块。判据只对**真产物**（带 `run_gates.py` 必写的 `tree_scope`）判红；
# 合成夹具（无 `tree_scope`）只标注不判红（否则会误伤 `tests/test_wb_review_branch.py`
# 的 1 道门夹具，而它不在本卡白名单里）。每条判据都配"故意坏掉会红"的反例。


def _gates_payload(names: list[str], *, real: bool = True, **over: object) -> dict:
    base: dict = {"gates": [{"name": n, "exit_code": 0} for n in names]}
    if real:
        base["tree_scope"] = "worktree-minus-gates"   # 真产物才有的字段（run_gates.py:1664）
    base.update(over)
    return base


def _real_gate_names() -> list[str]:
    return [n for n, _ in rg.build_jobs(False, False)]


def test_full_run_last_json_still_passes() -> None:
    """① 真·全量的 `last.json`（门数齐、无 affected 块）⇒ **照旧通过**（不许把正常路径判死）。"""
    names = _real_gate_names()
    problems, note, reading = wr.check_full_gate_run(_gates_payload(names))
    assert problems == [], problems
    assert note == "", "真全量不该留标注"
    assert f"门数={len(names)}" in reading and f"应有={len(names)}" in reading
    assert "affected 块=无" in reading


def test_partial_run_last_json_is_flagged_and_points_at_the_shortfall() -> None:
    """② 部分跑的 `last.json`（门数少几道）⇒ **判红**并**点名差在哪**（少的是哪几道）。"""
    names = _real_gate_names()
    short = names[:-2]
    problems, _, reading = wr.check_full_gate_run(_gates_payload(short))
    assert problems, "少了两道门却没报"
    assert any(("少 2 道" in p) and all(n in p for n in names[-2:]) for p in problems), problems
    assert f"门数={len(short)}" in reading and f"应有={len(names)}" in reading


def test_affected_block_marks_a_partial_run() -> None:
    """③ `last.json` 带 `affected` 块（`--affected` 部分跑的记账）⇒ **判红**并**贴原文**。"""
    names = _real_gate_names()
    block = {"inputs": ["src/a.py"], "ran": ["ruff"], "matched": ["ruff"],
             "skipped": [{"name": "pytest", "why": "输入未命中"}],
             "full_fallback": False, "note": "命中 1 道门"}
    problems, _, reading = wr.check_full_gate_run(_gates_payload(names, affected=block))
    assert any("affected 块" in p for p in problems), problems
    assert any("pytest" in p for p in problems), "affected 原文片段没被贴出来"
    assert "affected 块=有" in reading


def test_expected_count_is_read_from_the_run_gates_table(monkeypatch) -> None:
    """④ ★ **门数是现读的、不是硬编码**：桩掉 `scripts/run_gates.py` 的门表（少一道）⇒
    复核器跟着认为"应有 N-1"（这一条防"第二份真源"）。"""
    names = _real_gate_names()
    assert len(names) >= 2
    # 真表：全在 ⇒ 过；少一道 ⇒ 判"少 1 道"（证明它真拿真表当基准）
    assert wr.check_full_gate_run(_gates_payload(names))[0] == []
    assert any("少 1 道" in p for p in wr.check_full_gate_run(_gates_payload(names[:-1]))[0])
    # 桩掉门表（少一道）⇒ 基准跟着变：喂 N-1 道就过，喂 N 道反而被点名"多 1 道"
    monkeypatch.setattr(rg, "build_jobs", lambda q, f: [(n, []) for n in names[:-1]])
    assert wr.check_full_gate_run(_gates_payload(names[:-1]))[0] == []
    assert any("多 1 道" in p for p in wr.check_full_gate_run(_gates_payload(names))[0])


def test_synthetic_payload_without_tree_scope_is_only_annotated() -> None:
    """⑤ ★ 红线：**没有 `tree_scope`** 的 `last.json`（合成夹具 / 旧笔）**只标注、不判红**。

    为什么：`tests/test_wb_review_branch.py` 用的是一个 1 道门的合成 `last.json`，且断言 CLI 退 0；
    若新判据不留这条红线，那张**不在本卡白名单里**的测试会当场红（= 越界才能修）。真·`--affected`
    产物带 `tree_scope`，照判红（见 ②③）。
    """
    problems, note, reading = wr.check_full_gate_run(_gates_payload(["pytest"], real=False))
    assert problems == [], "合成夹具不该被判红（那是越界改动才救得回来的假红）"
    assert "tree_scope" in note and "标注" in note
    assert "门数=1" in reading


def test_partial_real_artifact_cli_is_rejected_end_to_end(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """②（CLI 层）**真产物**（带 `tree_scope`）门数少一道 ⇒ `wb_review` **判红退 1** ——
    证明这条判据在整条 `--rev` 流程里真会咬（不止零件层）。"""
    names = _real_gate_names()
    short = [{"name": n, "exit_code": 0} for n in names[:-1]]
    repo = _rev_repo(tmp_path, last_ok=True, gates_line="全量门禁绿", gates=short, tree_scope=True)
    monkeypatch.setattr(wr, "ROOT", repo)
    monkeypatch.setattr(wr, "audit_verdict", lambda: ([], "审计通过 ✅"))
    code = wr.main(["--rev", "HEAD", "--branch", "main", "--allow", "**", "--dirty-ok"])
    out = capsys.readouterr().out
    assert code == 1, out
    assert "少 1 道" in out and names[-1] in out, out


# ------------------------------------------ ③″ 封存树 vs 提交树（卡 160 · T-G260）
#
# 来路：INV-26 / INV-29 / INV-34 —— 封存指纹**生成了、没人查**（谁在提交前拿它比对，没有判据）。
# `check_seal_tree()` 把「`last.json.tree`（封存那刻去 gates/**、即将提交的 tree）== 本笔提交
# 去掉 gates/** 的 tree」这条对账接进**复核主链**；不等就点名差在哪几个路径。只对真产物
# （带 `tree_scope`）判红，旧笔（无 `tree_scope`）只标注。每条都配"故意坏掉会红"的反例。


def test_seal_tree_matches_commit_tree(monkeypatch) -> None:
    """① 封存指纹与本笔提交（去 gates/**）的 tree **一致** ⇒ 不报、不留标注。"""
    monkeypatch.setattr(wr, "_tree_without_gates", lambda rev: "deadbeefcafe")
    problems, note, reading = wr.check_seal_tree(
        {"tree": "deadbeefcafe", "tree_scope": rg.TREE_SCOPE}, "HEAD")
    assert problems == [], problems
    assert note == "", "真对上不该留标注"
    assert "相同" in reading and "deadbeefcafe" in reading


def test_seal_tree_mismatch_names_the_paths(monkeypatch) -> None:
    """② ★ 提交树 ≠ 封存树（封存之后又动了文件）⇒ **判红**并**点名差在哪几个路径**。"""
    monkeypatch.setattr(wr, "_tree_without_gates", lambda rev: "bbbbbbbbbbbb")
    monkeypatch.setattr(wr, "_diff_tree_paths",
                        lambda old, new: ["docs/changelog.md", "复盘/x.md"])
    problems, note, reading = wr.check_seal_tree(
        {"tree": "aaaaaaaaaaaa", "tree_scope": rg.TREE_SCOPE}, "HEAD")
    assert problems, "提交树 ≠ 封存树却没报"
    assert note == ""
    assert any("docs/changelog.md" in p and "复盘/x.md" in p for p in problems), problems
    assert "不同" in reading


def test_seal_tree_recompute_failure_is_red(monkeypatch) -> None:
    """③ 复算封存指纹失败（拿不到 tree）⇒ **判红**（拿不准不放过），不静默当对上。"""
    monkeypatch.setattr(wr, "_tree_without_gates", lambda rev: "")
    problems, _, reading = wr.check_seal_tree(
        {"tree": "a" * 12, "tree_scope": rg.TREE_SCOPE}, "HEAD")
    assert problems and "复算" in problems[0], problems
    assert "复算失败" in reading


def test_seal_tree_old_artifact_is_only_annotated() -> None:
    """④ ★ 红线：**没有 `tree_scope`** 的旧笔（那一列是底座那棵树的哈希）**只标注、不判红**。"""
    problems, note, reading = wr.check_seal_tree({"tree": "abc"}, "HEAD")
    assert problems == [], "旧笔不该被判红（核不了就别假装核过）"
    assert "不核" in note and "标注" in note
    assert "不核" in reading


# ------------------------------------------ wb_verify 门数也从门表现读（卡 160 · T-G260）
#
# 卡 147 治的是 `wb_review` 那一侧；`tools/wb_verify.py` 当时还写死 `EXPECT_GATES = 17`
# （加了第 18 道门就得两处一起改 = 第二份会漂的真源）。本档钉「它跟着门表算」。


def test_wb_verify_gate_count_is_read_from_the_table(monkeypatch) -> None:
    """★ `wb_verify.expected_gate_names()` 从门表现读（不是写死 17/18）——门表改了它跟着算。

    真表：与 `rg.build_jobs(False, False)` 一致，且含卡 160 接进来的那道 `invariants`。
    桩掉门表（只留一道）⇒ 现读出的清单**跟着变**（证明没有第二份真源）。
    """
    import wb_verify as wv  # noqa: PLC0415 —— tools/ 已在 sys.path 里

    names, source = wv.expected_gate_names(ROOT)
    assert names == _real_gate_names()
    assert "invariants" in names, "卡 160 的 invariants 门没进门表"
    assert "build_jobs" in source

    monkeypatch.setattr(rg, "build_jobs", lambda q, f: [("only_one", [])])
    short, source2 = wv.expected_gate_names(ROOT)
    assert short == ["only_one"] and "1 道" in source2


# ------------------------------------------------------------------ ① 豁免钉子（卡 159 · T-G259）

def test_ledger_with_exemption_makes_review_red() -> None:
    """★ 卡 159（INV-12 的钉子）：**台账带豁免 ⇒ 复核必须红**。

    红读数（实现前）：判据内联在 `audit_verdict` 里、没法喂数据 ⇒ 本用例 AttributeError 红。
    绿读数（实现后）：audit 退出码 0、但输出里是「豁免 1 项已知欠账」⇒ 复核**红**并点名豁免；
    「豁免 0 项已知欠账」⇒ 绿。判据单独拆出来喂假数据（同 `parse_task_trailers` 的做法）。
    """
    # 退出码 0 + 有豁免 ⇒ 仍必须红（豁免不许当通过）
    body_exempt = (
        "=== 台账：364 条 / 豁免（已知欠账）：1 条 ===\n"
        "审计通过 ✅（豁免 1 项已知欠账）\n"
    )
    problems = wr.audit_verdict_from_output(0, body_exempt)
    assert problems, "台账带豁免时复核不许绿"
    assert any("豁免" in p for p in problems), problems
    # 豁免 0 + 退出码 0 ⇒ 绿
    assert wr.audit_verdict_from_output(0, "审计通过 ✅（豁免 0 项已知欠账）") == []
    # 退出码非 0 ⇒ 红（audit 没过）
    assert wr.audit_verdict_from_output(1, "审计不通过：2 项失败（0 项已豁免）")


def test_short_sha_length_does_not_break_the_evidence_check() -> None:
    """同一笔提交的 7 位与 8 位短 sha 必须都认；换成别的提交必须拒。

    ★ 实测事故：门禁封存写的是 7 位（`94d343c`），`git rev-parse --short` 却给 8 位
    （`94d343cc`），判据按字面量比就把「同一笔」判成两笔，整条落地链卡死。比的是提交，
    不是字符串长度。
    """
    sha = wr.git("rev-parse", "--short", "HEAD")
    parent = wr.git("rev-parse", "--short", f"{sha}^")
    base = {"ok": True, "docs_sync_ok": True, "docs_sync_missing": []}

    same = wr.check_gate_evidence({**base, "rev": parent[:7]}, parent)
    assert [p for p in same if "门禁不是为这一笔跑的" in p] == []

    other = wr.git("rev-parse", "--short", f"{sha}~2")
    mismatch = wr.check_gate_evidence({**base, "rev": other}, parent)
    assert [p for p in mismatch if "门禁不是为这一笔跑的" in p]


def test_partial_profile_seal_is_rejected(tmp_path):
    """只跑了一档（last.json 里有 profile）的封存，不能当提交闸用。"""
    from tools import wb_review

    payload = {
        "ok": True,
        "rev": "abcdef1",
        "docs_sync_ok": True,
        "docs_sync_missing": [],
        "gates": [{"name": "pytest", "exit_code": 0}],
        "profile": "lang",
    }
    problems = wb_review.check_gate_evidence(payload, "abcdef1")
    assert any("只跑了 --profile lang" in p for p in problems), problems


def test_profiles_covering_required_profiles_pass(tmp_path):
    """卡 A327：产物记了 profiles_run 且覆盖 required_profiles ⇒ 放行（不再要求 19 道全量）。"""
    from tools import wb_review

    payload = {
        "ok": True,
        "rev": "abcdef1",
        "docs_sync_ok": True,
        "docs_sync_missing": [],
        "gates": [{"name": "pytest", "exit_code": 0}],
        "profiles_run": ["lang", "audit"],
        "required_profiles": ["lang", "audit"],
    }
    assert wb_review.check_gate_evidence(payload, "abcdef1") == []


def test_profiles_missing_a_required_one_are_rejected(tmp_path):
    """卡 A327：缺一档就点名拒 —— 「改 src 只跑 audit」不许当提交证据。"""
    from tools import wb_review

    payload = {
        "ok": True,
        "rev": "abcdef1",
        "docs_sync_ok": True,
        "docs_sync_missing": [],
        "gates": [{"name": "pytest", "exit_code": 0}],
        "profiles_run": ["audit"],
        "required_profiles": ["lang", "audit"],
    }
    problems = wb_review.check_gate_evidence(payload, "abcdef1")
    assert any("缺 lang" in p for p in problems), problems


def test_partial_profiles_without_required_are_rejected(tmp_path):
    """卡 A327：只记了 profiles_run、没有 required_profiles ⇒ 证明不了够用，判红。"""
    from tools import wb_review

    payload = {
        "ok": True,
        "rev": "abcdef1",
        "docs_sync_ok": True,
        "docs_sync_missing": [],
        "gates": [{"name": "pytest", "exit_code": 0}],
        "profiles_run": ["lang"],
    }
    problems = wb_review.check_gate_evidence(payload, "abcdef1")
    assert any("没有 required_profiles" in p for p in problems), problems
