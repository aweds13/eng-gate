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


# ------------------------------------------------------------------ 数据层：真仓库


def test_current_head_passes_the_gate_evidence_check() -> None:
    """本项目的提交流程应当让 HEAD 通过第 ③ 条 —— 拿真仓库验一次（假的会被这里抓到）。"""
    sha = wr.git("rev-parse", "--short", "HEAD")
    parent = wr.git("rev-parse", "--short", f"{sha}^")
    payload = json.loads(wr.git("show", f"{sha}:gates/last.json"))
    assert payload.get("ok") is True
    assert payload.get("rev") == parent, "gates/last.json 的 rev 应当等于这一笔的父提交"
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
