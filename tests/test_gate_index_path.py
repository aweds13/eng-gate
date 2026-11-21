"""临时索引必须**每次调用唯一**（卡 E147 · 台账号 T-G385）。

## 为什么有这张测试

`scripts/run_gates.py` 算封存指纹时要建一个临时索引，名字原来是**每棵树固定的**一个文件
（`.git/dsh_gates_index`，linked worktree 里是 `.git/worktrees/<名>/dsh_gates_index`）。
同一棵树里**两个读者同时算**就会撞 git 自己加的 `<名字>.lock`：先到的那步 `read-tree` 失败，
函数打一行警告并**返回 None**。落地链的门禁用 `-n 2 --dist worksteal` 跑全量 pytest，
于是这件事每天都在发生，只是大多数时候没被测到 —— 一旦那条钉子抽到这种顺序，
整趟落地（~19 分钟）白烧。

实测基线（主树 `gates/diag/_race_probe.py 4`，4 进程 × 6 次 = 24 次调用）：**回退(None)=14**。
而且「成功」的那些值里既有真树 `ca3e07b1…` 也有 `git write-tree` 的空树 `4b825dc6…`
—— 并发下连成功的那部分都不是同一棵树。

## 三条判据（卡 §4）

1. **路径唯一**（静态可判）：`_git_index_path(repo)` 连调三次给三个不同路径，
   都在 `git rev-parse --absolute-git-dir` 之下，名字都以 `dsh_gates_index` 开头。
2. **并发不再回退**（钉子本体）：真起 4 个 spawn 进程 × 每人 5 次 `tree_without_gates`，
   20 次全非空、全是同一个十六进制哈希、子进程退出码全 0 且 stderr 里没有 `[警告]`。
3. **不留垃圾**：成功路径 / `read-tree` 失败路径 / `write-tree` 失败路径跑完，
   `git_dir.glob("dsh_gates_index*")` 都必须是空的。

## 边界（如实写，未覆盖）

- 判据 2 钉的是**同一棵真仓**上的并发；它不高频复现 `-n 2` 那种 worker 调度，
  只保证名字唯一这条**必要条件**成立。反向证明见 `gates/diag/_rev_146.py`（M-A）。
- 不测「git 认不出 `rev-parse --git-path` 时的退路是否也唯一」—— 那要伪造一个坏 git，
  成本不值；退路用的是**同一个** `_unique_index_name()`，静态可读，且 M-A/M-B 已钉住前缀与序号。
- 不测 `_discard_index` 在 `unlink` 抛 `PermissionError` 时的行为（Windows 上被杀毒锁文件）：
  那里是 `contextlib.suppress(OSError)`，**故意**不把清理失败升级成结果失败。

★ 全部离线：只在 `tmp_path` 里 `git init` 造真仓，不碰本仓库的工作区、不跑任何门。
"""

from __future__ import annotations

import multiprocessing
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import run_gates as rg  # noqa: E402 —— 需要先用 sys.path 把 scripts/ 挂上

_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
}

#: 封存指纹的合法形状：SHA-1 的 40 位，或 SHA-256 仓库的 64 位（卡 §4 判据 2）。
FINGERPRINT_RE = re.compile(r"[0-9a-f]{40}([0-9a-f]{24})?")


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args], cwd=root, env=_GIT_ENV,
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    assert done.returncode == 0, f"git {args} 失败：{done.stderr}"
    return done.stdout.strip()


def _seed(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _init_repo(root: Path) -> None:
    """一个**真**临时 git 仓库（`tree_without_gates` 要真 git），已有一笔提交。"""
    _git(root, "init", "-q")
    _seed(root, "src/a.txt", "A")
    _seed(root, "gates/last.json", '{"tree":"x"}')
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")


def _git_dir(root: Path) -> Path:
    return Path(_git(root, "rev-parse", "--absolute-git-dir"))


def _index_files(root: Path) -> list[str]:
    """这个 git dir 里所有临时索引残留（含 `.lock`）—— 判据 3 的唯一读法。"""
    return sorted(p.name for p in _git_dir(root).glob("dsh_gates_index*"))


# --------------------------------------------------------------------------- 判据 1：路径唯一


def test_index_path_is_unique_per_call(tmp_path: Path) -> None:
    """★ 连调三次必须是**三个**路径 —— 不是「至少不同」，是三者两两不等。"""
    _init_repo(tmp_path)
    paths = [rg._git_index_path(tmp_path) for _ in range(3)]

    assert all(p is not None for p in paths), f"有调用拿不到索引路径：{paths}"
    names = [p.name for p in paths]
    assert len(set(paths)) == 3, f"三次调用给的路径有重复：{names}（并发下就是同一个 .lock）"

    git_dir = _git_dir(tmp_path)
    for path in paths:
        assert path.parent == git_dir, f"索引跑到 git dir 外面去了：{path} vs {git_dir}"
        assert path.name.startswith(rg.INDEX_NAME), (
            f"文件名没保留可 grep 的前缀 {rg.INDEX_NAME!r}：{path.name}"
            "（清理孤儿索引与排查都靠这个名字）"
        )


def test_index_name_carries_pid_and_a_counter(tmp_path: Path) -> None:
    """后缀必须是 `<pid>.<序号>`：只有 pid 的话同一进程连调两次仍同值（卡 §4 M-B）。"""
    _init_repo(tmp_path)
    a = rg._git_index_path(tmp_path)
    b = rg._git_index_path(tmp_path)
    assert a is not None and b is not None

    pid_part = f".{os.getpid()}."
    assert pid_part in a.name and pid_part in b.name, (a.name, b.name)
    suffix = lambda p: p.name[len(rg.INDEX_NAME) + 1:]  # noqa: E731 —— 只为读法短一点
    assert suffix(a).split(".")[0] == str(os.getpid())
    assert suffix(a).split(".")[1] != suffix(b).split(".")[1], (
        f"两次调用的序号相同：{a.name} / {b.name} —— 进程内序号没生效，同进程并发仍会撞"
    )


# --------------------------------------------------------------------------- 判据 3：不留垃圾


def test_successful_call_leaves_no_index_behind(tmp_path: Path) -> None:
    """成功路径跑完，git dir 里不许剩下任何 `dsh_gates_index*`。"""
    _init_repo(tmp_path)
    fingerprint = rg.tree_without_gates(tmp_path, "HEAD", include_worktree=True)

    assert fingerprint and FINGERPRINT_RE.fullmatch(fingerprint), fingerprint
    assert _index_files(tmp_path) == [], f"成功路径留下了孤儿索引：{_index_files(tmp_path)}"


def test_failed_read_tree_still_cleans_up(tmp_path: Path) -> None:
    """`read-tree` 失败（拿一个不存在的 rev）跑完，同样不许留垃圾，且必须**响**。"""
    _init_repo(tmp_path)
    done = subprocess.run(
        [sys.executable, "-X", "utf8", "-c",
         "import sys; sys.path.insert(0, sys.argv[1]);"
         "from run_gates import tree_without_gates;"
         "from pathlib import Path;"
         "print(repr(tree_without_gates(Path(sys.argv[2]), 'no-such-rev-4e147')))",
         str(ROOT / "scripts"), str(tmp_path)],
        cwd=tmp_path, env=_GIT_ENV, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "None", f"read-tree 失败却没回退成 None：{done.stdout!r}"
    assert "[警告]" in done.stderr, f"失败必须响亮（stderr 要有 [警告]）：{done.stderr!r}"
    assert _index_files(tmp_path) == [], f"失败路径留下了孤儿索引：{_index_files(tmp_path)}"


def test_failed_write_tree_still_cleans_up(tmp_path: Path, monkeypatch) -> None:
    """`write-tree` 失败也要删干净 —— 两条失败出口各钉一次（卡 §4 判据 3 原文）。"""
    _init_repo(tmp_path)
    real_run = subprocess.run

    def _fake_run(cmd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003 —— 只为拦 write-tree
        if isinstance(cmd, list) and "write-tree" in cmd:
            return subprocess.CompletedProcess(cmd, 1, "", "fatal: 假造的 write-tree 失败")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(rg.subprocess, "run", _fake_run)
    assert rg.tree_without_gates(tmp_path, "HEAD") is None, "write-tree 失败却给了指纹"
    monkeypatch.undo()

    left = _index_files(tmp_path)
    assert left == [], f"write-tree 失败路径留下了孤儿索引：{left}"


# --------------------------------------------------------------------------- 判据 2：并发不回退


def _worker(args: tuple[str, int, int]) -> tuple[int, list[str], list[str], str]:
    """子进程：连算 N 次封存指纹，返回 (退出码, 结果列表, 每次用的索引路径的父目录, stderr)。

    ★ 顺手把 `_git_index_path` 给的父目录一起带回来：卡 §3 那条「`GIT_INDEX_FILE` 必须落在
      同一个 git dir 里」得有钉子 —— 挪到仓外临时目录虽然也不撞，但同一棵树的两个读者就不再
      共享同一份索引语义（卡 §4 M-D 要能红）。
    """
    root_text, rounds, _i = args
    import contextlib  # noqa: PLC0415
    import io  # noqa: PLC0415

    root = Path(root_text)
    sys.path.insert(0, str(root / "scripts"))
    import run_gates  # noqa: PLC0415

    buf = io.StringIO()
    out: list[str] = []
    parents: list[str] = []
    with contextlib.redirect_stderr(buf):
        for _ in range(rounds):
            idx = run_gates._git_index_path(root)
            parents.append(str(idx.parent) if idx is not None else "")
            out.append(run_gates.tree_without_gates(root, "HEAD") or "")
    return 0, out, parents, buf.getvalue()


def test_concurrent_readers_all_get_the_same_fingerprint() -> None:
    """★ 本卡的钉子本体：4 个 spawn 进程各连调 5 次，20 次必须全非空、全同值、零警告。

    ★ 必须能红：把 `_unique_index_name` 改回常量名字 ⇒ 立刻出现「回退(None)=N」（N≥1），
      基线实测是 14/24（卡 §1.3）。反向脚本：`gates/diag/_rev_146.py` 的 M-A。
    """
    workers, rounds = 4, 5
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(processes=workers) as pool:
        results = pool.map(_worker, [(str(ROOT), rounds, i) for i in range(workers)])

    codes = [code for code, _outs, _parents, _err in results]
    prints = [fp for _code, outs, _parents, _err in results for fp in outs]
    parents = [p for _code, _outs, ps, _err in results for p in ps]
    stderrs = [err for _code, _outs, _parents, err in results]

    assert codes == [0] * workers, f"子进程退出码不全是 0：{codes}"
    empty = [fp for fp in prints if not fp]
    assert not empty, (
        f"回退(None)={len(empty)}（共 {len(prints)} 次）—— 并发读者仍在共用同一个索引名字，"
        "撞 git 自己的 .lock 后 read-tree 退 1（基线 4 进程 × 6 次实测回退 14/24）"
    )
    bad_shape = [fp for fp in prints if not FINGERPRINT_RE.fullmatch(fp)]
    assert not bad_shape, f"拿到的不是十六进制 tree 哈希：{bad_shape[:3]}"
    assert len(set(prints)) == 1, (
        "并发下拿到的不是同一棵树："
        + ", ".join(sorted({fp[:8] for fp in prints}))
        + "（既有真树也有 write-tree 的空树 4b825dc6 就是这个症状）"
    )
    noisy = [err for err in stderrs if "[警告]" in err]
    assert not noisy, f"成功路径不该带警告：{noisy[0][:300]!r}"

    git_dir = str(_git_dir(ROOT))
    outside = sorted({p for p in parents if p != git_dir})
    assert not outside, (
        f"临时索引跑到 git dir 外面去了：{outside[:3]} —— GIT_INDEX_FILE 必须与对象库同一个 "
        "git dir：挪到仓外临时目录（tempfile.mkdtemp）虽然也不撞，但读者之间不再共享同一份索引语义"
    )


def test_fingerprint_is_a_real_tree_hash() -> None:
    """钉子自身的防假绿：并发拿到的那个值必须真是本仓 HEAD 摘掉 gates 的那棵树。"""
    fingerprint = rg.tree_without_gates(ROOT, "HEAD")
    assert fingerprint and FINGERPRINT_RE.fullmatch(fingerprint), fingerprint

    entries = _git(ROOT, "ls-tree", "-r", "--name-only", fingerprint).splitlines()
    assert entries, "封存指纹是空树？"
    assert not [e for e in entries if e == "gates" or e.startswith("gates/")], (
        "封存指纹里还有 gates/ 条目 —— 口径被换了"
    )
    again = rg.tree_without_gates(ROOT, "HEAD")
    assert fingerprint == again, "同一个 HEAD 两次算出的指纹不同 —— 不是固定点"
