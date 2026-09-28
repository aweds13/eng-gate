"""`.wt` 工作树清理器的钉子测试（卡 081 · `T-G176`）。

为什么有这个文件：清理器是一台"会动世界"的机器（`--apply` 真删树），它最重要的性质是
**默认只看不删 + 七条判据缺一不可**。所以这个测试**在 `tmp_path` 里造一棵临时 git 仓库**
（`git init` + 一次提交 + 几棵 worktree），逐条钉住判据，**绝不碰真 `.wt`**：

  ① 已集成 + 干净                → **可删**
  ② 已集成 + 脏（改了已跟踪文件）→ **保留**
  ③ 未集成 + 干净                → **保留**
  ④ `locked`                     → **保留**
  ⑤ 当前工作树                   → **保留**（判据 1）
  ⑥ 未完工卡（backlog `status != done`）占的树 → **保留**（判据 7）
  ⑦ 未跟踪文件**不算阻塞**（判据 3），但 `--apply` 时 `git worktree remove` 会失败 → 保留

★ 测试自己建的 worktree 用完由 `tmp_path` 连同仓库一起回收；本文件**不需要真仓库里有 `.wt`**。
★ `tools/` 不是包（没有 `__init__.py`）→ 按路径用 `importlib` 加载被测模块。
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
# ★ 允许用环境变量 `WT_PRUNE_UNDER_TEST` 换一份实现来跑（"先红后绿"：不改工作区文件，
#   把一个**变异副本**指给本测试，看它红 —— 同 `tests/test_gate_lock_multi.py` 的手法）。
WT_SRC = Path(os.environ.get("WT_PRUNE_UNDER_TEST", str(REPO / "tools" / "wt_prune.py")))


def _load():
    spec = importlib.util.spec_from_file_location("wt_prune_under_test", WT_SRC)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclass 求值要靠 sys.modules（同 wt_prune._load_wb_plan）
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def wt():
    return _load()


def _run(cmd: list[str], cwd: Path) -> str:
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", check=False)
    assert r.returncode == 0, f"{cmd} 失败（rc={r.returncode}）：{r.stderr.strip()}"
    return r.stdout


@pytest.fixture()
def repo(tmp_path, wt):
    """临时 git 仓库：`git init` + 一次提交（=`main` 的 tip）。"""
    root = tmp_path / "repo"
    root.mkdir()
    _run(["git", "-c", "init.defaultBranch=main", "init", "-q"], root)
    _run(["git", "config", "user.email", "t@example.com"], root)
    _run(["git", "config", "user.name", "tester"], root)
    _run(["git", "config", "commit.gpgsign", "false"], root)
    (root / "a.txt").write_text("hello\n", encoding="utf-8")
    _run(["git", "add", "a.txt"], root)
    _run(["git", "commit", "-q", "-m", "init"], root)
    return root


def _add(root: Path, name: str, *, commit: bool = False, lock: bool = False) -> Path:
    """在 `<root>/.wt/<name>` 建一棵 worktree（默认挂在 main 的 tip = 已集成）。"""
    path = root / ".wt" / name
    _run(["git", "worktree", "add", "--detach", str(path), "HEAD"], root)
    if commit:  # 在树里再提交一笔 → 它的 tip 不再是 main HEAD 的祖先 = 未集成
        (path / "b.txt").write_text("x\n", encoding="utf-8")
        _run(["git", "add", "b.txt"], path)
        _run(["git", "commit", "-q", "-m", "extra"], path)
    if lock:
        _run(["git", "worktree", "lock", str(path)], root)
    return path


def _judge_all(wt, root: Path, current: Path | None = None) -> dict[str, object]:
    ctx = wt.make_context(root, current)
    return {t.path.name: wt.judge(t, ctx) for t in wt.list_worktrees(root)}


def _cli(wt, args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-X", "utf8", str(WT_SRC), *args],
                          cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)


# ---------------------------------------------------------------- 七条判据


def test_integrated_clean_is_deletable(repo, wt):
    """① 已集成 + 干净 → 可删；顺手钉「未跟踪文件不算阻塞」（判据 3）。"""
    _add(repo, "clean")
    vs = _judge_all(wt, repo)
    v = vs["clean"]
    assert v.deletable is True, v.reason
    assert v.integrated is True and v.tracked_dirty == 0 and v.untracked == 0
    # 未跟踪的临时文件：判据 3 不阻塞（仍可删），但计数要如实
    (repo / ".wt" / "clean" / "tmp.txt").write_text("tmp\n", encoding="utf-8")
    v2 = _judge_all(wt, repo)["clean"]
    assert v2.untracked == 1 and v2.deletable is True, v2.reason


def test_integrated_dirty_is_kept(repo, wt):
    """② 已集成 + 脏（改了已跟踪文件）→ 保留，理由是判据 3。"""
    p = _add(repo, "dirty")
    (p / "a.txt").write_text("changed\n", encoding="utf-8")
    v = _judge_all(wt, repo)["dirty"]
    assert v.integrated is True and v.tracked_dirty == 1
    assert v.deletable is False and "判据3" in v.reason, v.reason


def test_unintegrated_clean_is_kept(repo, wt):
    """③ 未集成 + 干净 → 保留，理由是判据 2。"""
    _add(repo, "ahead", commit=True)
    v = _judge_all(wt, repo)["ahead"]
    assert v.integrated is False and v.tracked_dirty == 0
    assert v.deletable is False and "判据2" in v.reason, v.reason


def test_locked_is_kept(repo, wt):
    """④ `locked` → 保留，理由是判据 6。"""
    _add(repo, "locked", lock=True)
    v = _judge_all(wt, repo)["locked"]
    assert v.locked is True and v.integrated is True and v.tracked_dirty == 0
    assert v.deletable is False and "判据6" in v.reason, v.reason


def test_current_worktree_is_kept(repo, wt):
    """⑤ 当前工作树 → 保留（判据 1）。"""
    p = _add(repo, "cur")
    ctx = wt.make_context(repo, p)  # 把 cur 当"当前工作树"
    v = wt.judge({t.path.name: t for t in wt.list_worktrees(repo)}["cur"], ctx)
    assert v.deletable is False and "判据1" in v.reason, v.reason


def test_pending_card_tree_is_kept(repo, wt):
    """⑥ 未完工卡占的树 → 保留（判据 7）；卡号**从 backlog 现读**，不硬编码。"""
    _add(repo, "claimed")
    docs = repo / "docs"
    docs.mkdir()
    (docs / "workbacklog.toml").write_text(
        '[base]\nreviewed = "0000000"\n\n'
        '[[cards]]\nid = "900"\ntask = "T-G900"\ntitle = "临时"\n'
        'tree = ".wt/claimed"\nspec = "s.md"\nfiles = ["x.txt"]\n'
        'depends = []\nrisk = "low"\nstatus = "pending"\n',
        encoding="utf-8",
    )
    v = _judge_all(wt, repo)["claimed"]
    assert v.deletable is False and "判据7" in v.reason, v.reason


# ---------------------------------------------------------------- 默认只看不删 / --apply


def test_cli_dry_run_touches_nothing(repo, wt):
    """默认（dry-run）**一棵都不删**：跑前跑后 worktree 计数相等、目录都还在。"""
    _add(repo, "clean")
    dusty = _add(repo, "dirty")
    (dusty / "a.txt").write_text("changed\n", encoding="utf-8")
    before = wt.list_worktrees(repo)
    before_n = len(before)
    r = _cli(wt, ["--root", str(repo)], repo)
    assert r.returncode == 0, r.stderr
    after = wt.list_worktrees(repo)
    assert len(after) == before_n, f"dry-run 不该动树：{before_n} → {len(after)}"
    assert all(t.path.exists() for t in after)
    assert "汇总：可删 1 棵 / 保留" in r.stdout, r.stdout


def test_cli_apply_removes_only_deletable(repo, wt):
    """`--apply`：删掉 1 棵该删的、保住 3 棵该留的；退出码 0。"""
    a = _add(repo, "clean")             # 该删
    b = _add(repo, "dirty")             # 保留（脏）
    (b / "a.txt").write_text("changed\n", encoding="utf-8")
    c = _add(repo, "ahead", commit=True)  # 保留（未集成）
    d = _add(repo, "locked", lock=True)   # 保留（locked）
    r = _cli(wt, ["--root", str(repo), "--apply"], repo)
    assert r.returncode == 0, r.stderr
    assert not a.exists(), "该删的那棵没删掉"
    assert b.exists() and c.exists() and d.exists(), "该留的被删了"
    assert "删了 1 棵" in r.stdout, r.stdout


def test_cli_apply_keeps_when_remove_fails(repo, wt):
    """`--apply` 删不掉就保留：未跟踪文件让 `git worktree remove` 失败 → 保留 + 退 1。"""
    p = _add(repo, "loose")
    (p / "loose.txt").write_text("loose\n", encoding="utf-8")  # 未跟踪 → remove 会拒
    r = _cli(wt, ["--root", str(repo), "--apply"], repo)
    assert p.exists(), "remove 失败时不该把树删掉"
    assert r.returncode == 1, r.stdout + r.stderr
    assert "删失败" in r.stdout or "1 棵本应删掉的树删失败" in r.stdout, r.stdout


def test_cli_json_is_machine_readable(repo, wt):
    """`--json` 给主控读：结构里有 trees + summary。"""
    import json
    _add(repo, "clean")
    r = _cli(wt, ["--root", str(repo), "--json"], repo)
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["mode"] == "dry-run"
    assert payload["summary"]["deletable"] == 1
    assert any(t["name"] == ".wt/clean" and t["deletable"] for t in payload["trees"])


def test_dir_size_sums_and_survives_bad_paths(tmp_path, wt):
    """大小用 `os.scandir` 递归求和（不经 `du`）；读不动的路径跳过并计数。"""
    d = tmp_path / "d"
    (d / "sub").mkdir(parents=True)
    (d / "x.bin").write_bytes(b"a" * 1000)
    (d / "sub" / "y.bin").write_bytes(b"b" * 500)
    total, skipped = wt.dir_size(d)
    assert total == 1500 and skipped == 0
    missing_total, missing_skipped = wt.dir_size(tmp_path / "不存在")
    assert missing_total == 0 and missing_skipped >= 1
