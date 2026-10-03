"""留痕与配额的钉子测试（卡 182 · `T-G282`）。

为什么有这个文件：`tools/wb_retention.py` 把「读数 + 判据 + 归档」接上常规，它最重要的
性质是 **判据正确（无判决的不许被当已判决）+ 归档幂等 + 默认只看不删**。所以这里在
`tmp_path` 里造临时仓库 + 假日志，逐条钉住：

  ① `has_verdict` 逐文件同名配对（不按卡号聚合 → claim 不会蹭正跑的判决）
  ② 读数：jsonl / verdict / 无判决 份数如实
  ③ 反例：有判决的日志归档后**必须还在原位**；无判决的才被移走
  ④ 归档幂等：跑两次，第二次 done=0、文件不重复移
  ⑤ dry-run 不动文件
  ⑥ 配额告警：超阈值印 WARN/CRIT

★ 全在 `tmp_path` 里跑，**绝不碰真 `gates/diag`**。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import wb_retention as rt  # noqa: E402


def _run(cmd: list[str], cwd: Path) -> str:
    import subprocess
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", check=False)
    assert r.returncode == 0, f"{cmd} 失败：{r.stderr.strip()}"
    return r.stdout


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _run(["git", "-c", "init.defaultBranch=main", "init", "-q"], root)
    _run(["git", "config", "user.email", "t@example.com"], root)
    _run(["git", "config", "user.name", "tester"], root)
    (root / "a.txt").write_text("x\n", encoding="utf-8")
    _run(["git", "add", "a.txt"], root)
    _run(["git", "commit", "-q", "-m", "init"], root)
    return root


def _diag(repo: Path) -> Path:
    d = repo / "gates" / "diag"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _touch(p: Path, *, mtime_days_ago: float = 0.0) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x\n", encoding="utf-8")
    if mtime_days_ago:
        t = time.time() - mtime_days_ago * 86400
        import os
        os.utime(p, (t, t))


# ---------------------------------------------------------------- ① has_verdict 逐文件同名配对


def test_has_verdict_pairs_by_exact_name_not_card(tmp_path):
    """`wb-125.claim.jsonl` 找 `wb-125.claim.verdict.txt`，不蹭 `wb-125.verdict.txt`。"""
    d = _diag(tmp_path)
    j = d / "wb-125.claim.jsonl"
    _touch(j)
    (d / "wb-125.verdict.txt").write_text("ok\n", encoding="utf-8")  # 正跑的判决
    assert rt.has_verdict(j) is False, "claim 蹭了正跑的判决（应逐文件配对）"
    (d / "wb-125.claim.verdict.txt").write_text("ok\n", encoding="utf-8")
    assert rt.has_verdict(j) is True


def test_card_of_extracts_number():
    assert rt.card_of("wb-125.claim.jsonl") == "125"
    assert rt.card_of("wb-178.verdict.txt") == "178"
    assert rt.card_of("wb-usage.jsonl") is None
    assert rt.card_of("readme.md") is None


# ---------------------------------------------------------------- ② 读数如实


def test_read_counts_reports_all_categories(repo):
    d = _diag(repo)
    _touch(d / "wb-100.jsonl")
    _touch(d / "wb-100.verdict.txt")
    _touch(d / "wb-101.jsonl")            # 无判决
    _touch(d / "wb-125.claim.jsonl")      # 无判决（claim 变体）
    c = rt.read_counts(repo)
    assert c.n_jsonl == 3, c.n_jsonl
    assert c.n_verdict == 1, c.n_verdict
    assert c.n_no_verdict == 2, c.n_no_verdict
    assert c.no_verdict_cards == ["101", "125"], c.no_verdict_cards
    assert c.worktrees >= 1


# ---------------------------------------------------------------- ③ 反例：有判决的不许被归档


def test_archive_keeps_verdicted_log(repo):
    """反例钉子：有判决的日志归档后**必须还在原位**（不许被当无判决移走）。"""
    d = _diag(repo)
    verdicted = d / "wb-200.jsonl"
    _touch(verdicted, mtime_days_ago=30)
    _touch(d / "wb-200.verdict.txt", mtime_days_ago=30)
    done, skipped, failed = rt.archive_apply(repo, min_age_days=0)
    assert done == 0, f"有判决的日志被归档了：done={done}"
    assert verdicted.exists(), "有判决的日志被移走了！"
    assert not (rt._archive_root(repo) / "wb-200.jsonl").exists()


def test_archive_moves_no_verdict_log(repo):
    """无判决的旧日志归档后移到 archive/ 且留索引。"""
    d = _diag(repo)
    orphan = d / "wb-201.jsonl"
    _touch(orphan, mtime_days_ago=30)
    done, skipped, failed = rt.archive_apply(repo, min_age_days=0)
    assert done == 1 and failed == 0, (done, skipped, failed)
    assert not orphan.exists(), "无判决日志没被移走"
    assert (rt._archive_root(repo) / "wb-201.jsonl").exists(), "没移到 archive/"
    assert "wb-201.jsonl" in rt._index_keys(repo), "没留索引"


# ---------------------------------------------------------------- ④ 归档幂等


def test_archive_is_idempotent(repo):
    """幂等钉子：跑两次，第二次 done=0、文件不重复、索引不重复写。"""
    d = _diag(repo)
    _touch(d / "wb-300.jsonl", mtime_days_ago=30)
    _touch(d / "wb-301.jsonl", mtime_days_ago=30)
    done1, _, _ = rt.archive_apply(repo, min_age_days=0)
    assert done1 == 2
    idx1 = rt._index_path(repo).read_text(encoding="utf-8")
    done2, skipped2, failed2 = rt.archive_apply(repo, min_age_days=0)
    assert done2 == 0 and failed2 == 0, f"第二次不该再归档：done={done2}"
    assert skipped2 == 0, skipped2  # 源已移走，不在 plan 里
    idx2 = rt._index_path(repo).read_text(encoding="utf-8")
    assert idx1 == idx2, "索引被改了（不幂等）"


def test_archive_plan_marks_already_archived(repo):
    """源还在但索引已有 → 标「已归档」跳过（幂等的另一面）。"""
    d = _diag(repo)
    _touch(d / "wb-302.jsonl", mtime_days_ago=30)
    rt._archive_root(repo).mkdir(parents=True, exist_ok=True)
    with rt._index_path(repo).open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"name": "wb-302.jsonl", "age_days": 30}) + "\n")
    plan = rt.archive_plan(repo, min_age_days=0)
    assert plan[0].skipped_reason == "已归档", plan[0].skipped_reason


# ---------------------------------------------------------------- ⑤ dry-run 不动


def test_archive_dry_run_touches_nothing(repo):
    d = _diag(repo)
    orphan = d / "wb-303.jsonl"
    _touch(orphan, mtime_days_ago=30)
    plan = rt.archive_plan(repo, min_age_days=0)
    assert len(plan) == 1 and not plan[0].skipped_reason
    assert orphan.exists(), "plan 不该动文件"
    assert not rt._archive_root(repo).exists(), "dry-run 不该建 archive/"


# ---------------------------------------------------------------- ⑥ 配额告警


def test_quota_warns_on_many_trees(repo):
    """树数超 WARN 阈值 → 告警；用低阈值触发（不真造 100 棵树）。"""
    c = rt.read_counts(repo)
    warns = rt.quota_check(c, tree_warn=0, tree_crit=999, log_warn=999)
    levels = [w.level for w in warns]
    assert "WARN" in levels, levels
    crits = [w for w in warns if w.level == "CRIT"]
    assert not crits, "没到 CRIT 不该报 CRIT"


def test_quota_crit_above_crit_threshold(repo):
    c = rt.read_counts(repo)
    warns = rt.quota_check(c, tree_warn=0, tree_crit=1, log_warn=999)
    assert any(w.level == "CRIT" for w in warns), warns


# ---------------------------------------------------------------- CLI 烟雾


def test_cli_summary_json(repo):
    import subprocess
    r = subprocess.run([sys.executable, "-X", "utf8", str(REPO / "tools" / "wb_retention.py"),
                        "--root", str(repo), "summary", "--json"],
                       capture_output=True, text=True, encoding="utf-8", check=False)
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert "worktrees" in payload and "n_jsonl" in payload


def test_cli_archive_dry_run(repo):
    import subprocess
    d = _diag(repo)
    _touch(d / "wb-400.jsonl", mtime_days_ago=30)
    r = subprocess.run([sys.executable, "-X", "utf8", str(REPO / "tools" / "wb_retention.py"),
                        "--root", str(repo), "archive"],
                       capture_output=True, text=True, encoding="utf-8", check=False)
    assert r.returncode == 0, r.stderr
    assert (d / "wb-400.jsonl").exists(), "dry-run 不该移文件"
    assert "待归档" in r.stdout, r.stdout
