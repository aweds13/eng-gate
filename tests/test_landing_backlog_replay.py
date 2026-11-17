from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANDING = ROOT / "tools" / "pool" / "landing.py"

BACKLOG_REL = "docs/workbacklog.toml"
CODE_REL = "tools/pool/landing.py"

_ENV = {k: v for k, v in os.environ.items()
        if k not in ("PYTHONPATH", "TF_PYTEST_WORKERS", "TF_GATE_MIN_FREE_GB")}

#: 桩：只记「跑过」，不真重汇（判据在真件里）。
_SYNC_DOCS_OK = """import pathlib
import sys

_text = " ".join(sys.argv[1:])
pathlib.Path("sync_docs_calls.log").open("a", encoding="utf-8").write(_text + "\\n")
sys.exit(0)
"""

_CHECKER_OK = """import pathlib
import sys

pathlib.Path("checker_calls.log").open("a", encoding="utf-8").write(" ".join(sys.argv[1:]) + "\\n")
sys.exit(0)
"""


def _load_landing():
    """按路径装 `tools/pool/landing.py`（不 import `pool` 包，免得与真仓 ROOT 打架）。"""
    spec = importlib.util.spec_from_file_location("landing_for_e122", LANDING)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(ROOT / "tools"))
    return mod


landing = _load_landing()


# ================================================================ 真仓库夹具
def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.quotepath=false",
                           *args], cwd=str(repo), env=_ENV, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)


def _write_bytes(root: Path, rel: str, data: bytes) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


_BASE = (
    b'[[cards]]\r\n'
    b'id = "007"\r\n'
    b'task = "T-007"\r\n'
    b'spec = "s7.md"\r\n'
    b'status = "pending"\r\n'
    b'risk = "mid"\r\n'
    b'\r\n'
    b'[[cards]]\r\n'
    b'id = "008"\r\n'
    b'task = "T-008"\r\n'
    b'spec = "s8.md"\r\n'
    b'status = "pending"\r\n'
    b'risk = "mid"\r\n'
)

#: 主树那一笔：把 008 翻成 blocked（别的卡）、把 007 的 risk 改成 high（与 status 相邻 ⇒ 真冲突）、
#: 再在末尾追加一张新卡（并发插队那笔的典型形状）。
_TRUNK_ADDED = (b'\r\n[[cards]]\r\nid = "009"\r\ntask = "T-009"\r\nspec = "s9.md"\r\n'
                b'status = "pending"\r\nrisk = "mid"\r\n')


def _trunk_bytes(base: bytes) -> bytes:
    text = base.decode("utf-8")
    text = text.replace('id = "008"\r\ntask = "T-008"\r\nspec = "s8.md"\r\nstatus = "pending"',
                        'id = "008"\r\ntask = "T-008"\r\nspec = "s8.md"\r\nstatus = "blocked"')
    text = text.replace('status = "pending"\r\nrisk = "mid"\r\n\r\n[[cards]]\r\nid = "008"',
                        'status = "pending"\r\nrisk = "high"\r\n\r\n[[cards]]\r\nid = "008"')
    return text.encode("utf-8") + _TRUNK_ADDED


def _card_bytes(base: bytes, *, also_spec: bool = False) -> bytes:
    text = base.decode("utf-8")
    text = text.replace('status = "pending"\r\nrisk = "mid"\r\n\r\n[[cards]]\r\nid = "008"',
                        'status = "done"\r\nrisk = "mid"\r\n\r\n[[cards]]\r\nid = "008"')
    if also_spec:
        text = text.replace('spec = "s7.md"', 'spec = "s7-v2.md"')
    return text.encode("utf-8")


def _conflicted_repo(tmp_path: Path, *, also_spec: bool = False,
                     trunk_bytes: bytes | None = None,
                     code_conflict: bool = False,
                     autocrlf: str = "false") -> Path:
    """造一个**台账真冲突**的 rebase 现场（卡 E122 的病：插队那笔也动了 queue）。

    `autocrlf="true"` 造的是真仓的几何：库里存 LF、工作区取出来是 CRLF。
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "nail@example.invalid")
    _git(repo, "config", "user.name", "nail")
    _git(repo, "config", "core.autocrlf", autocrlf)
    _write_bytes(repo, ".gitignore", b"sync_docs_calls.log\nchecker_calls.log\n")
    _write_bytes(repo, BACKLOG_REL, _BASE)
    _write_bytes(repo, CODE_REL, b"X = 0\n")
    _write_bytes(repo, "tools/sync_docs.py", _SYNC_DOCS_OK.encode("utf-8"))
    _write_bytes(repo, "scripts/check_derived_docs.py", _CHECKER_OK.encode("utf-8"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()

    _git(repo, "checkout", "-q", "-b", "trunk", base)
    _write_bytes(repo, BACKLOG_REL, trunk_bytes if trunk_bytes is not None else _trunk_bytes(_BASE))
    if code_conflict:
        _write_bytes(repo, CODE_REL, b"X = 1\n")
    _git(repo, "commit", "-q", "-am", "trunk move")

    _git(repo, "checkout", "-q", "-b", "card", base)
    _write_bytes(repo, BACKLOG_REL, _card_bytes(_BASE, also_spec=also_spec))
    if code_conflict:
        _write_bytes(repo, CODE_REL, b"X = 2\n")
    _git(repo, "commit", "-q", "-am", "card move")

    done = _git(repo, "rebase", "trunk")
    assert done.returncode != 0, "夹具：本来该冲突的 rebase 居然成功了"
    return repo


def _unmerged(repo: Path) -> list[str]:
    got = _git(repo, "diff", "--name-only", "--diff-filter=U")
    assert got.returncode == 0, got.stderr
    return [x.strip() for x in got.stdout.splitlines() if x.strip()]


def _stage2(repo: Path) -> bytes:
    """冲突里 `:2:` = 主树那一侧（`--ours`）。"""
    return subprocess.run(["git", "show", f":2:{BACKLOG_REL}"], cwd=str(repo), env=_ENV,
                          capture_output=True, check=True).stdout


def _blob(repo: Path) -> bytes:
    return (repo / BACKLOG_REL).read_bytes()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _status_of(data: bytes, card: str) -> str | None:
    for _s, _e, f in landing._scan_blocks(landing._split_blocks(data)):
        if f["id"] == card:
            return f["status"]  # type: ignore[return-value]
    return None


def _block_bytes(data: bytes, card: str) -> bytes:
    lines = landing._split_blocks(data)
    for start, end, f in landing._scan_blocks(lines):
        if f["id"] == card:
            return b"".join(lines[start:end])
    raise AssertionError(f"块 {card} 不在")


def _expected(trunk: bytes, card: str) -> bytes:
    """期望字节 = 主树那版**只**把目标块 status 行换成 done（其余一字不动）。"""
    lines = landing._split_blocks(trunk)
    for _s, _e, f in landing._scan_blocks(lines):
        if f["id"] == card:
            idx = f["status_idx"]
            assert idx is not None
            lines[idx] = lines[idx].replace(b'"pending"', b'"done"')
    return b"".join(lines)


# ================================================================ 判据 1：签名与旧调用点
def test_the_new_arguments_are_keyword_only_with_safe_defaults() -> None:
    """判据 1：`card` / `task` 是关键字参数、缺省不改变任何旧行为的入口。"""
    import inspect

    sig = inspect.signature(landing.resolve_derived_conflicts)
    params = list(sig.parameters.values())
    assert [p.name for p in params][:1] == ["wt"]
    extra = params[1:]
    assert [p.name for p in extra] == ["card", "task"], extra
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in extra)
    assert extra[0].default is None and extra[1].default == ""


def test_without_a_card_the_backlog_is_still_a_human_call(tmp_path: Path) -> None:
    """不给卡号（批模式 / 老调用点）⇒ 台账仍算「非派生物」，一字不改地停手。"""
    repo = _conflicted_repo(tmp_path)
    before = _blob(repo)
    ok, detail = landing.resolve_derived_conflicts(repo)
    assert ok is False, detail
    assert any("非派生物" in x and BACKLOG_REL in x for x in detail), detail
    assert _blob(repo) == before, "说不清就不许动冲突现场"
    assert _unmerged(repo) == [BACKLOG_REL]


# ================================================================ 判据 2–4：真重放
def test_a_backlog_status_conflict_is_replayed_from_the_landed_hunk(tmp_path: Path) -> None:
    """判据 2/3/4：认领本笔那一行 → 取主树版 → 翻账 → 逐字节等于预期。"""
    repo = _conflicted_repo(tmp_path)
    trunk = _stage2(repo)
    expect = _expected(trunk, "007")

    ok, detail = landing.resolve_derived_conflicts(repo, card="007", task="T-007")

    assert ok is True, detail
    assert BACKLOG_REL in detail
    assert _unmerged(repo) == [], "重放之后没 git add ⇒ 索引里仍是 UU"
    data = _blob(repo)
    assert _sha(data) == _sha(expect), "重放结果必须逐字节等于「主树版只换那一行」"
    assert data.count(b"\r\n") == expect.count(b"\r\n")
    assert len(data.splitlines(keepends=True)) == len(expect.splitlines(keepends=True))
    for marker in (b"<<<<<<<", b"=======", b">>>>>>>"):
        assert marker not in data
    assert _status_of(data, "007") == "done"
    assert _status_of(data, "008") == "blocked", "主树插队那笔翻的别的卡不许被顶掉"
    assert _status_of(data, "009") == "pending", "插队那笔新加的卡块不许丢"
    assert _block_bytes(data, "008") == _block_bytes(trunk, "008")
    assert _block_bytes(data, "009") == _block_bytes(trunk, "009")


def test_the_trunk_side_already_flipping_the_same_card_counts_as_success(tmp_path: Path) -> None:
    """反例 ①：主树那侧也把同一张卡翻成 done ⇒ `not-needed` 也算成功，且不重复长行。"""
    trunk_text = _trunk_bytes(_BASE).decode("utf-8").replace(
        'status = "pending"\r\nrisk = "high"', 'status = "done"  # 主树那侧先翻了\r\nrisk = "high"')
    repo = _conflicted_repo(tmp_path, trunk_bytes=trunk_text.encode("utf-8"))
    trunk = _stage2(repo)
    ok, detail = landing.resolve_derived_conflicts(repo, card="007", task="T-007")
    assert ok is True, detail
    assert _unmerged(repo) == []
    assert _blob(repo) == trunk, "主树那侧已经 done ⇒ 一个字节都不该改"


def test_a_hunk_that_is_more_than_the_status_line_still_stops(tmp_path: Path) -> None:
    """判据 2 的边界：本笔改了不止 status 一行 ⇒ 认不清该重放哪一处 ⇒ 停手并还原现场。"""
    repo = _conflicted_repo(tmp_path, also_spec=True)
    before = _blob(repo)
    ok, detail = landing.resolve_derived_conflicts(repo, card="007", task="T-007")
    assert ok is False, detail
    assert any(BACKLOG_REL in x for x in detail), detail
    assert _unmerged(repo) == [BACKLOG_REL], "停手时不许留半解决树"
    assert _blob(repo) == before, "守卫失败要还原成带标记的冲突现场"


def test_a_source_code_conflict_is_still_named_and_stops(tmp_path: Path) -> None:
    """判据 6：源码进冲突照旧点名停手（重放不许把范围放宽到非派生物）。"""
    repo = _conflicted_repo(tmp_path, code_conflict=True)
    ok, detail = landing.resolve_derived_conflicts(repo, card="007", task="T-007")
    assert ok is False, detail
    assert any(CODE_REL in x for x in detail), detail


def _conflict_body(blob: bytes) -> list[bytes]:
    """去掉冲突标记行（标签不算内容），只留两侧的真字节。"""
    marks = (b"<<<<<<<", b"=======", b">>>>>>>")
    return [ln for ln in blob.split(b"\n") if not ln.startswith(marks)]


def test_a_half_solved_scene_can_be_restored_to_the_marked_conflict(tmp_path: Path) -> None:
    """判据 5：停手时要能把「已取主树版」的半解决树还原成带冲突标记的现场。

    ★ git checkout --merge 重建的标签是 ours/theirs，rebase 原场的标签是
    HEAD/<sha> (msg)：标签不是内容，所以只比两侧真字节。
    """
    repo = _conflicted_repo(tmp_path)
    marked = _blob(repo)
    _git(repo, "checkout", "--ours", "--", BACKLOG_REL)
    assert b"<<<<<<<" not in _blob(repo), "前提：--ours 之后冲突标记没了"
    landing._restore_conflict(repo, BACKLOG_REL)
    assert _unmerged(repo) == [BACKLOG_REL], "还原之后下标又应该是未合并"
    blob = _blob(repo)
    assert b"<<<<<<<" in blob and b">>>>>>>" in blob, "还原要回到带冲突标记的现场"
    assert _conflict_body(blob) == _conflict_body(marked), "两侧真字节要一模一样"


# ================================================================ 判据 5：幂等
def test_replaying_twice_is_a_no_op(tmp_path: Path) -> None:
    """重放是幂等的：对**已经翻好**的字节再来一次 ⇒ 不报错、不改字节。"""
    repo = _conflicted_repo(tmp_path)
    ok, _detail = landing.resolve_derived_conflicts(repo, card="007", task="T-007")
    assert ok is True
    once = _blob(repo)
    verdict = landing.flip_card_status(repo, "007", "T-007")
    assert verdict == "not-needed"
    assert _blob(repo) == once


def test_a_replay_on_a_card_the_task_does_not_own_restores(tmp_path: Path) -> None:
    """判据 5：拿不到「本笔翻的卡」（task 对不上）⇒ 停手，且现场要还原成带标记的冲突。"""
    repo = _conflicted_repo(tmp_path)
    marked = _blob(repo)
    ok, detail = landing.resolve_derived_conflicts(repo, card="007", task="T-999")
    assert ok is False, detail
    assert any(BACKLOG_REL in x for x in detail), detail
    assert _unmerged(repo) == [BACKLOG_REL], "停手时不许留半解决树"
    blob = _blob(repo)
    assert b"<<<<<<<" in blob and b">>>>>>>" in blob, "要还原成带冲突标记的现场"
    assert _conflict_body(blob) == _conflict_body(marked), "两侧真字节要一模一样"



# ================================================================ 判据 3：真仓几何（autocrlf）
def _index_blob_sha(repo: Path) -> str:
    """索引里台账那一份的 blob sha（= 将来进库的那一版）。"""
    out = _git(repo, "ls-files", "-s", "--", BACKLOG_REL).stdout.split()
    assert len(out) >= 2, out
    return out[1]


def test_the_replay_survives_a_worktree_that_is_crlf_while_the_index_is_lf(tmp_path: Path) -> None:
    """★ 卡 E122 真仓现场：core.autocrlf=true ⇒ 库里 LF、工作区 CRLF。

    这时「逐字节等于预期」必须比**进库那一版**（blob sha），不是工作区字节 ——
    否则真仓必判「重放之后不一致」而停手，而假仓（autocrlf=false）看不出来。
    """
    repo = _conflicted_repo(tmp_path, autocrlf="true")
    trunk = _stage2(repo)
    assert trunk.count(b"\r\n") == 0, "前提：索引里那一版是 LF"
    assert (repo / BACKLOG_REL).read_bytes().count(b"\r\n") > 0, "前提：工作区取出来是 CRLF"

    ok, detail = landing.resolve_derived_conflicts(repo, card="007", task="T-007")

    assert ok is True, detail
    assert _unmerged(repo) == [], "重放之后没 git add ⇒ 索引里仍是 UU"
    want = landing._blob_sha(repo, _expected(trunk, "007"))
    assert want, "算不出预期那一版的 blob sha"
    assert _index_blob_sha(repo) == want, "进库那一版必须逐字节等于「主树版只换那一行」"
    staged = subprocess.run(["git", "show", f":{BACKLOG_REL}"], cwd=str(repo), env=_ENV,
                            capture_output=True, check=True).stdout
    assert staged.count(b"\r\n") == 0, "库里不许被换成 CRLF"
    assert _status_of(staged, "007") == "done"
