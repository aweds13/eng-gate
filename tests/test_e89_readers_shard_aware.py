"""钉子：台账分片（卡 E89 · `T-AG596`）的**拒单型 + 按路径取历史**读者 —— 六处要害。

## 为什么这些用例存在

A 组的钉子（`tests/test_e89_readers_a.py`）钉的是「静默少卡」那一半；这份钉另一半：
**分片里有卡，读者却报「队列里没有这张卡」** —— 正常活被拒掉（派活被咬退 2、复核落到
「权威域查不到」、自动落地判「卡不在队列」）。另两处**按路径**取历史：路径不覆盖
`docs/backlog` ⇒ 分片里登记的号全成孤儿（天天假红）。

夹具与 A 组同型：仓外 `tempfile.mkdtemp()`（仓内临时文件会被 `git status` 抓到），
复制真的 `docs/partitions.toml`，**总表故意只有 `C2`**、`docs/backlog/C.toml` 里有
`C1` + `C2`（分片盖住总表 ⇒ `load_sharded_backlog` 的覆盖比对不会炸）。
读者若只读总表 ⇒ 看不见 `C1` ⇒ 这条红。

`shard_only_repo` 是更狠的那一面：**总表根本还没合出来**，只有分片。
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import auto_land  # noqa: E402  —— 需要先把 tools/ 挂上
import pool_mcp  # noqa: E402
import wb_impact  # noqa: E402
import wb_queue_audit  # noqa: E402
import wb_registry  # noqa: E402
import wb_review  # noqa: E402
from pool.plan import BacklogError  # noqa: E402

BASE = '[base]\nreviewed = "0000000"\n\n'

#: 总表里那唯一一张卡（**故意**与分片差一张）。
C2 = ('[[cards]]\nid = "C2"\ntask = "T-AG902"\ntitle = "已完"\n'
      'tree = ".wt/C2"\nspec = "s.md"\nfiles = ["tools/x_c2.py"]\ndepends = []\n'
      'risk = "low"\nstatus = "done"\n')

#: 只在分片里的那张卡：pending、占着 `.wt/C1`。
C1 = ('[[cards]]\nid = "C1"\ntask = "T-AG901"\ntitle = "没完"\n'
      'tree = ".wt/C1"\nspec = "s.md"\nfiles = ["tools/x_c1.py"]\ndepends = []\n'
      'risk = "low"\nstatus = "pending"\n')

MASTER = BASE + C2
SHARD_C = BASE + C1 + C2


def _sandbox(prefix: str, *, master: bool) -> Path:
    """仓外临时树：`docs/backlog/C.toml` 必有；`docs/workbacklog.toml` 按需。"""
    root = Path(tempfile.mkdtemp(prefix=prefix))
    docs = root / "docs"
    (docs / "backlog").mkdir(parents=True)
    if master:
        (docs / "workbacklog.toml").write_text(MASTER, encoding="utf-8", newline="\n")
    (docs / "backlog" / "C.toml").write_text(SHARD_C, encoding="utf-8", newline="\n")
    shutil.copy2(ROOT / "docs" / "partitions.toml", docs / "partitions.toml")
    return root


@pytest.fixture()
def shard_repo() -> Path:
    """总表只有 C2、分片 C.toml 有 C1+C2（真 `docs/partitions.toml` 也带上）。"""
    root = _sandbox("e89-readers-bc-", master=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture()
def shard_only_repo() -> Path:
    """**总表还没合出来**，只有分片 —— 这棵树里 `docs/workbacklog.toml` 不存在。"""
    root = _sandbox("e89-readers-bc-nomaster-", master=False)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _shard_commit(repo: Path, mark: str) -> None:
    """在 `repo` 里造一笔「只改了分片文件」的提交（带 `Task:` trailer）。"""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    for cmd in (["git", "init", "-q"],
                ["git", "config", "user.email", "nail@example.invalid"],
                ["git", "config", "user.name", "nail"],
                ["git", "config", "commit.gpgsign", "false"]):
        # text=True 必给 encoding：云机 cp936 解码中文会崩，本机 utf-8 看不出来。
        subprocess.run(cmd, cwd=str(repo), env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    for cmd in (["git", "add", "docs/backlog/C.toml"],
                ["git", "commit", "-q", "-m", f"feat(队列): 分片登记 C1\n\nTask: {mark}\n"]):
        subprocess.run(cmd, cwd=str(repo), env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")


# ============================================================ 1. wb_registry（派活拒单）


def test_registry_files_from_backlog_sees_shard_card(shard_repo: Path) -> None:
    """`files_from_backlog("C1")` 拿得到域 —— 不是「没有这张卡 ⇒ 不许派活」。

    反向：把它换回零参 `load_backlog()`（`pool.plan` 那份固定到导入时的仓库根）⇒ 这条红（拒单）。
    """
    assert wb_registry.files_from_backlog("C1", root=shard_repo) == ["tools/x_c1.py"]


def test_registry_still_refuses_unknown_card(shard_repo: Path) -> None:
    """反向保护：真没有这张卡时**照样拒**（不许为了放行改成猜空域）。"""
    with pytest.raises(wb_registry.UsageError) as caught:
        wb_registry.files_from_backlog("C999", root=shard_repo)
    assert "backlog 里没有卡 C999" in str(caught.value)


# ============================================================ 2. wb_review（复核权威域）


def test_review_domain_comes_from_shard(shard_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`resolve_domain("C1", None)` 从分片拿到域 —— 不许落到「权威域查不到」。

    反向：把 `resolve_domain` 换回 `if bpath.exists(): load_backlog(bpath)` ⇒ 这条红。
    """
    monkeypatch.setattr(wb_review, "ROOT", shard_repo)
    domain, why = wb_review.resolve_domain("C1", None)
    assert domain == ["tools/x_c1.py"], why
    assert "查不到" not in why, why


def test_review_domain_comes_from_shard_when_master_absent(
    shard_only_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """总表还没合出来（只有分片）时也不许落「查不到」—— 判据只看 `bpath.exists()` 就会漏。

    反向：把条件改回 `if bpath.exists():` ⇒ 这条红（`shard_only_repo` 里没有总表）。
    """
    monkeypatch.setattr(wb_review, "ROOT", shard_only_repo)
    domain, why = wb_review.resolve_domain("C1", None)
    assert domain == ["tools/x_c1.py"], why
    assert "查不到" not in why, why


def test_review_still_refuses_card_in_no_queue(
    shard_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """反向保护：分片里也没有的卡，仍然拒（兜底那句话与判据都不许放宽）。"""
    monkeypatch.setattr(wb_review, "ROOT", shard_repo)
    domain, why = wb_review.resolve_domain("C999", None)
    assert domain is None
    assert "查不到" in why, why


# ============================================================ 3. wb_impact（影响面取域）


def test_impact_files_from_backlog_sees_shard_card(shard_repo: Path) -> None:
    """`--card C1` 的影响面从分片取到（老读法直读 `ROOT/docs/workbacklog.toml` ⇒ 这条红）。"""
    assert wb_impact.files_from_backlog("C1", root=shard_repo) == ["tools/x_c1.py"]


def test_impact_files_from_backlog_sees_shard_card_when_master_absent(
    shard_only_repo: Path,
) -> None:
    """总表不存在时也照样能取（分片就是队列的现在时）。"""
    assert wb_impact.files_from_backlog("C1", root=shard_only_repo) == ["tools/x_c1.py"]


def test_impact_still_refuses_unknown_card(shard_repo: Path) -> None:
    """反向保护：真没有这张卡 ⇒ 仍然 `UsageError`（文案里点名 `docs/workbacklog.toml`）。"""
    with pytest.raises(wb_impact.UsageError) as caught:
        wb_impact.files_from_backlog("C999", root=shard_repo)
    assert "没有卡 C999" in str(caught.value)


# ============================================================ 4. auto_land（判卡落在哪棵树）


def test_auto_land_load_backlog_sees_shard_card(shard_repo: Path) -> None:
    """`load_backlog()` 里要有只在分片里的卡（否则「卡 C1 不在队列里」⇒ 不收口）。

    反向：把它换回直读 `root/docs/workbacklog.toml` ⇒ 这条红（`out` 里没有键 `1`）。
    """
    rows = auto_land.load_backlog(root=shard_repo)
    assert set(rows) == {"1", "2"}, sorted(rows)
    assert rows["1"]["tree"] == ".wt/C1", rows["1"]


def test_auto_land_load_backlog_is_still_callable_without_args() -> None:
    """零参兼容：既有测试（`tests/test_auto_land.py`）把它当零参桩用，签名不许变成必填。"""
    import inspect

    params = inspect.signature(auto_land.load_backlog).parameters
    assert all(p.default is not inspect.Parameter.empty for p in params.values()), params


# ============================================================ 5. pool_mcp（派活器那一侧）


def test_pool_mcp_backlog_for_sees_shard_card(shard_repo: Path) -> None:
    """`_backlog_for(root)` 读的是 root 的分片（不是导入时的那棵树，也不只是总表）。

    反向：把 `_backlog_for` 换回 `load_backlog(root/"docs"/"workbacklog.toml")` ⇒ 这条红。
    """
    pool_mcp = importlib.import_module("pool_mcp")
    backlog = pool_mcp._backlog_for(shard_repo)
    assert sorted(backlog.by_id()) == ["C1", "C2"], sorted(backlog.by_id())


# ============================================================ 6. wb_queue_audit（按路径取历史）


def test_queue_audit_shard_relpath_sits_beside_queue() -> None:
    """分片目录从队列路径**现算**：`docs/workbacklog.toml` ⇒ `docs/backlog`（不写死）。"""
    assert wb_queue_audit.shard_relpath() == "docs/backlog"
    assert wb_queue_audit.shard_relpath("a/b/queue.toml") == "a/b/backlog"
    assert wb_queue_audit.shard_relpath("queue.toml") == "backlog"


def test_queue_audit_protects_mark_that_only_touched_shard(shard_repo: Path) -> None:
    """只改了 `docs/backlog/C.toml` 的号是**簿记号**，不许报成孤儿。

    反向：把 `queue_touch_marks` 的 pathspec 改回只有 `queue_relpath` ⇒ 这条红（假红）。
    """
    _shard_commit(shard_repo, "T-AG901")
    marks = wb_queue_audit.read_task_commits(shard_repo)
    assert "T-AG901" in marks, sorted(marks)
    protected = wb_queue_audit.queue_touch_marks(shard_repo, marks)
    assert "T-AG901" in protected, sorted(protected)


def test_queue_audit_still_reports_mark_that_touched_nothing(
    shard_repo: Path
) -> None:
    """反向保护：没碰队列也没碰分片的号，照样是孤儿（保护集不许放大成「全部」）。"""
    _shard_commit(shard_repo, "T-AG901")
    marks = wb_queue_audit.read_task_commits(shard_repo)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    (shard_repo / "plain.txt").write_text("x\n", encoding="utf-8", newline="\n")
    for cmd in (["git", "add", "plain.txt"],
                ["git", "commit", "-q", "-m", "chore: 无关一笔\n\nTask: T-AG903\n"]):
        subprocess.run(cmd, cwd=str(shard_repo), env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    marks = wb_queue_audit.read_task_commits(shard_repo)
    protected = wb_queue_audit.queue_touch_marks(shard_repo, marks)
    assert "T-AG901" in protected
    assert "T-AG903" not in protected, sorted(protected)


def test_queue_audit_cli_counts_cards_from_shard(
    shard_repo: Path, capsys: pytest.CaptureFixture
) -> None:
    """CLI 读的也是分片：总表 1 张、分片 2 张 ⇒ `cards` 要报 2。

    反向：把 `main` 换回 `load_backlog(Path(args.backlog))` ⇒ 这条红（报 1）。
    """
    code = wb_queue_audit.main(["--backlog", str(shard_repo / "docs" / "workbacklog.toml"),
                                "--repo", str(shard_repo), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["cards"] == 2, payload
    assert code in (wb_queue_audit.EXIT_CLEAN, wb_queue_audit.EXIT_SKIPPED), code


def test_queue_audit_cli_refuses_broken_shard(
    shard_repo: Path, capsys: pytest.CaptureFixture
) -> None:
    """反向保护：分片坏掉时仍然是 `[FAIL] 队列读不了` + 退出码 1（不许静默当成空队列）。"""
    (shard_repo / "docs" / "backlog" / "C.toml").write_text(
        "这不是 TOML [[[\n", encoding="utf-8", newline="\n")
    code = wb_queue_audit.main(["--backlog", str(shard_repo / "docs" / "workbacklog.toml"),
                                "--repo", str(shard_repo)])
    captured = capsys.readouterr()
    assert code == wb_queue_audit.EXIT_FINDINGS, code
    assert "队列读不了" in captured.err, captured.err
    assert BacklogError is not None  # 判据类来自 pool.plan（口径只此一份）


# ============================================= 7. 无分片时退回总表（向后兼容）

#: 只有总表、**没有** `docs/backlog/` 的旧形状 —— 今天真仓就是这一态。
MASTER_ONLY_C2 = ('[[cards]]\nid = "C2"\ntask = "T-AG902"\ntitle = "已完"\n'
                  'tree = ".wt/C2"\nspec = "s.md"\nfiles = ["x.txt"]\ndepends = []\n'
                  'risk = "low"\nstatus = "done"\n')


@pytest.fixture()
def master_only_repo() -> Path:
    """没有分片目录的旧形状 —— 读者必须一字不变地退回总表（真仓现在就是这一态）。"""
    root = Path(tempfile.mkdtemp(prefix="e89-readers-bc-master-"))
    try:
        docs = root / "docs"
        docs.mkdir(parents=True)
        (docs / "workbacklog.toml").write_text(
            BASE + MASTER_ONLY_C2, encoding="utf-8", newline="\n"
        )
        shutil.copy2(ROOT / "docs" / "partitions.toml", docs / "partitions.toml")
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_registry_without_shards_still_reads_master(master_only_repo: Path) -> None:
    """没有分片目录时行为一字不变：总表里的卡照旧读得到，查不到照旧拒。

    反向：把读法改成「只认分片、没有分片就抛」⇒ 这条红（真仓现在是无分片）。
    """
    assert wb_registry.files_from_backlog("C2", root=master_only_repo) == ["x.txt"]
    with pytest.raises(wb_registry.UsageError):
        wb_registry.files_from_backlog("C1", root=master_only_repo)


def test_impact_without_shards_falls_back_to_master(master_only_repo: Path) -> None:
    """无分片时退回总表（向后兼容）。

    反向：只认分片、没有分片就抛 ⇒ 这条红。
    """
    assert wb_impact.files_from_backlog("C2", root=master_only_repo) == ["x.txt"]


def test_auto_land_without_shards_reads_master(master_only_repo: Path) -> None:
    """无分片时退回总表（`tests/test_auto_land.py` 的 lambda 也走这条签名）。

    反向：给 `load_backlog` 加必填参数 / 只认分片 ⇒ 这条红。
    """
    rows = auto_land.load_backlog(master_only_repo)
    assert set(rows) == {"2"}, sorted(rows)
    assert rows["2"]["task"] == "T-AG902"


def test_pool_mcp_without_shards_reads_master(master_only_repo: Path) -> None:
    """无分片时退回总表（向后兼容）。

    反向：只认分片、没有分片就抛 ⇒ 这条红。
    """
    backlog = pool_mcp._backlog_for(master_only_repo)
    assert [card.id for card in backlog.cards] == ["C2"]
