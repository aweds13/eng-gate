r"""钉「rebase 冲突里，机器能自己重算的投影不该让人来判」（卡 E86 · `T-AG593`）。

## 为什么这张测试

卡 E85 第二次落地（`gates/diag/land-E85b.log:34-35`）在 ff 合流前 rebase 冲突、**退 3**：

```
rebase 冲突（并发两笔都动了共享文档 / 门禁产物）： docs/INDEX.md · docs/changelog.md ·
docs/subsystems/pool/README.md · docs/traceability.toml · gates/last.json · 复盘/交接-重构进度.md
★★ 自动解决不了 ⇒ 停手：["冲突里有**非派生物**（必须人来判）：
                      ['docs/INDEX.md', 'docs/subsystems/pool/README.md']"]
```

可这两份同样是**落地链自己会重算的投影**（`RECOUNT_DOCS` ← `scripts/check_derived_docs.py`
写模式），只是不在 `DERIVED` 那张表里 ⇒ 判据把「机器能重算的」当成了「必须人来判的」。
代价：那次我手工做了 `checkout --ours` × 5 + `--theirs` × 1 + `git add` + 三个生成器 +
`rebase --continue` 才走完，每一步都是判据已经知道答案的事。

## 六条钉子（对应卡 E86 §判据 1–6）

| # | 钉子 |
|---|---|
| 1 | `RESOLVABLE = (*DERIVED, *RECOUNT_DOCS)`；`docs/INDEX.md` 进冲突集合时 `extra` 为空 |
| 2 | 两份现算文档先 `--ours` 取基线，再**真跑** `check_derived_docs.py`（写模式、cwd=卡树） |
| 3 | 重算后必须跑 `--check` 复核；非零 ⇒ 停手并点名，不许吞成成功 |
| 4 | `git add` 名单必须含这两份（实测：`checkout` 之后不加 `git add`，`git status` 照样 `UU`） |
| 5 | 冲突里有源码 ⇒ 仍 `return False` 并点名（放宽只到投影，不外溢） |
| 6 | 既有行为一字不变：`DOCS` 取 ours + `sync_docs`、`GATES` 取 theirs、空冲突表照旧拒 |

## 怎么跑

- 钉子 2–6 在 `tmp_path` 里 `git init` 一个**真仓库**：真造一次 rebase 冲突（两条分支各改
  同两份投影），真跑 `resolve_derived_conflicts()`；只有 `tools/sync_docs.py` 与
  `scripts/check_derived_docs.py` 是**桩**（本卡治的是「谁该自动解决」，不是它们内部）。
- 钉子 1 是纯读判据：断言 `RESOLVABLE` 恰好是两张表的并集，且 `extra` 的过滤改用新表。
- 钉子 6 另用录制式桩（`landing.run` / `landing.git` 被替换）钉**调用序列**：
  `checkout --ours` × 3 → `sync_docs` → `sync_docs --check` → `git add`。
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:                       # 只在注解里用到（ruff TC002）
    import pytest

ROOT = Path(__file__).resolve().parents[1]
LANDING = ROOT / "tools" / "pool" / "landing.py"

INDEX_REL = "docs/INDEX.md"
README_REL = "docs/subsystems/pool/README.md"
CHANGELOG_REL = "docs/changelog.md"
TRACE_REL = "docs/traceability.toml"
HANDOFF_REL = "复盘/交接-重构进度.md"
LAST_REL = "gates/last.json"
CODE_REL = "tools/pool/landing.py"

_ENV = {k: v for k, v in __import__("os").environ.items()
        if k not in ("PYTHONPATH", "TF_PYTEST_WORKERS", "TF_GATE_MIN_FREE_GB")}

#: 桩：写模式退 0 并留下痕迹；`--check` 退 0。判据在真件里，这里只钉「有没有跑它」。
#: ★ 写模式那趟 `sys.argv[1:]` 是**空的**，直接拼会写出一行空串、被 `_log()` 滤掉 ——
#: 所以没有参数时写 `WRITE` 标记（实测踩过：断言 `calls[0] == ""` 收到的是 `--check`）。
_CHECKER_OK = """import pathlib
import sys

args = sys.argv[1:]
mark = " ".join(args) if args else "WRITE"
pathlib.Path("checker_calls.log").open("a", encoding="utf-8").write(mark + "\\n")
sys.exit(0)
"""

#: 桩：写模式退 0；`--check` 退 1（模拟「重算之后仍不一致」）。
_CHECKER_BAD_CHECK = """import pathlib
import sys

args = sys.argv[1:]
mark = " ".join(args) if args else "WRITE"
pathlib.Path("checker_calls.log").open("a", encoding="utf-8").write(mark + "\\n")
sys.exit(1 if "--check" in sys.argv else 0)
"""

_SYNC_DOCS_OK = """import pathlib
import sys

args = sys.argv[1:]
pathlib.Path("sync_docs_calls.log").open("a", encoding="utf-8").write(" ".join(args) + "\\n")
sys.exit(0)
"""


def _load_landing():
    """按路径装 `tools/pool/landing.py`（不 import `pool` 包，免得与真仓 ROOT 打架）。"""
    spec = importlib.util.spec_from_file_location("landing_for_e86", LANDING)
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


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("utf-8"))


def _conflicted_repo(tmp_path: Path, *, also_code: bool = False,
                     checker: str = _CHECKER_OK) -> Path:
    """造一个**真有 rebase 冲突**的仓库：两条分支各改同几份投影。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "nail@example.invalid")
    _git(repo, "config", "user.name", "nail")
    _git(repo, "config", "core.autocrlf", "false")
    _write(repo, ".gitignore", "checker_calls.log\nsync_docs_calls.log\n")
    _write(repo, INDEX_REL, "base index\n")
    _write(repo, README_REL, "base readme\n")
    _write(repo, CHANGELOG_REL, "base changelog\n")
    _write(repo, TRACE_REL, "base trace\n")
    _write(repo, HANDOFF_REL, "base handoff\n")
    _write(repo, LAST_REL, '{"ok": false}\n')
    _write(repo, CODE_REL, "X = 0\n")
    _write(repo, "tools/sync_docs.py", _SYNC_DOCS_OK)
    _write(repo, "scripts/check_derived_docs.py", checker)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()

    # 主树那一笔：改了全部投影（模拟「并发另一笔动了同样的文件」）
    _git(repo, "checkout", "-q", "-b", "trunk", base)
    for rel in (INDEX_REL, README_REL, CHANGELOG_REL, TRACE_REL, HANDOFF_REL):
        _write(repo, rel, f"trunk {rel}\n")
    _write(repo, LAST_REL, '{"ok": true, "from": "trunk"}\n')
    if also_code:
        _write(repo, CODE_REL, "X = 1  # trunk\n")
    _git(repo, "commit", "-q", "-am", "trunk move")

    # 卡树那一笔：从 base 出发改同样的投影
    _git(repo, "checkout", "-q", "-b", "card", base)
    for rel in (INDEX_REL, README_REL, CHANGELOG_REL, TRACE_REL, HANDOFF_REL):
        _write(repo, rel, f"card {rel}\n")
    _write(repo, LAST_REL, '{"ok": true, "from": "card"}\n')
    if also_code:
        _write(repo, CODE_REL, "X = 2  # card\n")
    _git(repo, "commit", "-q", "-am", "card move")

    done = _git(repo, "rebase", "trunk")
    assert done.returncode != 0, "夹具：本来该冲突的 rebase 居然成功了"
    return repo


def _unmerged(repo: Path) -> list[str]:
    got = _git(repo, "diff", "--name-only", "--diff-filter=U")
    assert got.returncode == 0, got.stderr
    return [x.strip() for x in got.stdout.splitlines() if x.strip()]


def _porcelain(repo: Path) -> str:
    return _git(repo, "status", "--porcelain").stdout


def _read(repo: Path, rel: str) -> str:
    return (repo / rel).read_text(encoding="utf-8")


def _log(repo: Path, name: str) -> list[str]:
    p = repo / name
    if not p.is_file():
        return []
    return [x for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


# ================================================================ 判据 1
def test_resolvable_is_both_tables_and_the_extra_filter_uses_it() -> None:
    """`RESOLVABLE` = 派生三份 + 现算两份；`extra` 的过滤改用新表（不再只看 `DERIVED`）。"""
    assert (*landing.DERIVED, *landing.RECOUNT_DOCS) == landing.RESOLVABLE
    for rel in landing.RECOUNT_DOCS:
        assert rel in landing.RESOLVABLE
        assert rel not in landing.DERIVED, "两张表的语义不同，不许悄悄并进 DERIVED"
    src = LANDING.read_text(encoding="utf-8")
    assert "x not in RESOLVABLE and x not in GATE_ARTIFACTS" in src
    assert "x not in DERIVED and x not in GATE_ARTIFACTS" not in src


# ================================================================ 判据 2 + 4
def test_a_conflict_on_the_two_recount_docs_is_resolved(tmp_path: Path) -> None:
    """E85 现场的重演：`docs/INDEX.md` + README 进冲突 ⇒ 自动解决，不再是「非派生物」。"""
    repo = _conflicted_repo(tmp_path)
    assert set(_unmerged(repo)) >= {INDEX_REL, README_REL}

    ok, detail = landing.resolve_derived_conflicts(repo)

    assert ok is True, detail
    assert INDEX_REL in detail and README_REL in detail
    assert _unmerged(repo) == [], "checkout 之后没 git add ⇒ 索引里仍是 UU（本卡实测）"


def test_recount_runs_the_checker_in_write_mode_then_checks(tmp_path: Path) -> None:
    """判据 2：真跑重算器（写模式，cwd=卡树），再 `--check` 复核 —— 顺序不许颠倒。"""
    repo = _conflicted_repo(tmp_path)
    ok, _detail = landing.resolve_derived_conflicts(repo)
    assert ok is True

    calls = _log(repo, "checker_calls.log")
    assert calls[0] == "WRITE", f"第一趟必须是写模式（不带 --check），实得 {calls[0]!r}"
    assert any("--check" in c for c in calls), f"少了一次复核：{calls}"
    assert "--target" not in " ".join(calls)


def test_the_two_recount_docs_take_the_baseline_not_the_card_tree(tmp_path: Path) -> None:
    """判据 2 前半句：先取 `--ours`（rebase 里 = 被 rebase 到的trunk版），不是卡树那版。"""
    repo = _conflicted_repo(tmp_path)
    ok, _detail = landing.resolve_derived_conflicts(repo)
    assert ok is True
    for rel in (INDEX_REL, README_REL):
        assert _read(repo, rel).startswith("trunk "), f"{rel} 没取基线：{_read(repo, rel)!r}"


def test_the_gate_artifacts_still_take_ours_own(tmp_path: Path) -> None:
    """判据 6：`gates/last.json` 仍取**本笔的**（`--theirs`），本卡不改这条。"""
    repo = _conflicted_repo(tmp_path)
    ok, _detail = landing.resolve_derived_conflicts(repo)
    assert ok is True
    assert '"card"' in _read(repo, LAST_REL), _read(repo, LAST_REL)


# ================================================================ 判据 3
def test_a_still_inconsistent_recount_stops_the_landing(tmp_path: Path) -> None:
    """判据 3：重算之后 `--check` 仍非零 ⇒ 停手并点名，不许吞成成功。"""
    repo = _conflicted_repo(tmp_path, checker=_CHECKER_BAD_CHECK)
    ok, detail = landing.resolve_derived_conflicts(repo)

    assert ok is False
    assert any("--check" in x or "仍不通过" in x for x in detail), detail
    assert any(x.strip() for x in detail)


# ================================================================ 判据 5
def test_a_real_code_conflict_still_stops_and_is_named(tmp_path: Path) -> None:
    """判据 5：源码进冲突集合 ⇒ 仍停手，且原因串里点名该文件（放宽不外溢）。"""
    repo = _conflicted_repo(tmp_path, also_code=True)
    assert CODE_REL in _unmerged(repo), "夹具：源码冲突没造出来"

    ok, detail = landing.resolve_derived_conflicts(repo)

    assert ok is False
    assert any(CODE_REL in x for x in detail), detail
    assert _unmerged(repo), "停手时不许动冲突现场"


# ================================================================ 判据 6
def test_the_existing_paths_are_untouched_when_only_derived_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """判据 6：只有派生三份冲突时，调用序列与卡 E86 之前**逐字相同**（不多跑重算）。"""
    calls: list[list[str]] = []
    wt = tmp_path / "wt"
    wt.mkdir()

    class _Done:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_git(*args: str, cwd: Path | None = None, check: bool = True) -> str:
        assert args[0] == "diff"
        # ★ 冲突表里必须有那两份门禁产物，否则 `add` 名单只剩派生三份，
        # `detail` 就对不上 `DERIVED + GATE_ARTIFACTS`（夹具踩过）。
        return "\n".join((*landing.DERIVED, *landing.GATE_ARTIFACTS))

    def fake_run(cmd: list[str], cwd: Path, check: bool = True) -> _Done:
        calls.append(list(cmd))
        return _Done()

    monkeypatch.setattr(landing, "git", fake_git)
    monkeypatch.setattr(landing, "run", fake_run)

    ok, detail = landing.resolve_derived_conflicts(wt)

    assert ok is True, detail
    assert detail == list(landing.DERIVED) + list(landing.GATE_ARTIFACTS)
    assert not any(landing.DERIVED_CHECKER in " ".join(c) for c in calls), \
        f"只有派生物冲突时不许白跑重算器：{calls}"
    git_add = [c for c in calls if c[:2] == ["git", "add"]]
    assert len(git_add) == 1 and git_add[0][2] == "--"
    # 这两份现算文档**不在冲突表里** ⇒ 不许多加（`add` 只取交集，不是整张 RESOLVABLE）
    assert list(git_add[0][3:]) == [*landing.DERIVED, *landing.GATE_ARTIFACTS]
# ================================================================ 卡 E138（T-AG647）判据 2
def test_a_dirty_recount_doc_is_added_and_the_continue_retried(tmp_path: Path) -> None:
    """E138 现场：冲突都解完、只脏一份白名单里的派生文档 ⇒ 补 add 之后 rebase 走完。

    坏掉的写法（本卡开工前就是这样）：`git rebase --continue` 一次非零就出队 —— 可它
    只是拒跑（原文 `You must edit all merge conflicts and then mark them as resolved
    using git add`），把那一份派生文档 `git add` 掉它就走完了。
    """
    repo = _conflicted_repo(tmp_path)
    ok, detail = landing.resolve_derived_conflicts(repo)
    assert ok is True, detail
    assert _unmerged(repo) == [], "夹具：冲突没解完"
    # 门禁之后重算又把这份现算文档写脏了一次（卡 115 的有意宽松：它本来就晚于门禁）
    _write(repo, README_REL, _read(repo, README_REL) + "重算又写了一遍\n")
    assert " M " + README_REL in _porcelain(repo).replace("MM", " M"), _porcelain(repo)

    rc, added = landing._continue_rebase_after_resolve(repo, task="T-AG647")

    assert rc == 0, f"补 add 之后 rebase 应该走完，rc={rc}\n{_porcelain(repo)}"
    assert added == [README_REL], added
    assert _git(repo, "status", "--porcelain").stdout.strip() == "", _porcelain(repo)


def test_a_dirty_file_outside_the_whitelist_is_not_added(tmp_path: Path, capsys) -> None:
    """白名单外的脏文件一个都不 add：点名、不吞、仍停手（return 3）。

    ★ 夹具用**已跟踪**的文件（`tools/pool/landing.py`）：未跟踪的那份实测不挡
      `rebase --continue`，拿它当现场是假现场。
    """
    repo = _conflicted_repo(tmp_path)
    ok, detail = landing.resolve_derived_conflicts(repo)
    assert ok is True, detail
    _write(repo, CODE_REL, _read(repo, CODE_REL) + "Y = 1  # 人手里的改动\n")
    before = _porcelain(repo)
    assert CODE_REL in before, before

    rc, added = landing._continue_rebase_after_resolve(repo, task="T-AG647")

    assert rc == 3, f"白名单外的脏文件必须仍停手，实得 rc={rc}\n{capsys.readouterr().out}"
    assert added == [], added
    after = _porcelain(repo)
    assert "M  " + CODE_REL not in after, f"白名单外的文件被 add 了：{after}"
    printed = capsys.readouterr().out
    assert CODE_REL in printed, "没点名那个白名单外的脏文件：" + printed
    assert "不 add" in printed, printed


def test_the_continue_is_retried_exactly_once_then_stops(tmp_path: Path, capsys) -> None:
    """两次 `--continue` 都失败 ⇒ 恰好重试一次、返 3、三行留痕都在。

    ★ 现场：冲突表里还有源码（`also_code=True` 解不了）—— 补 add 也救不了，
      这时**只许重试一次**，第二次失败就停手（死循环比停手更糟）。
    """
    repo = _conflicted_repo(tmp_path, also_code=True)
    ok, _detail = landing.resolve_derived_conflicts(repo)
    assert ok is False, "夹具：源码冲突不该被自动解决"

    rc, added = landing._continue_rebase_after_resolve(repo, task="T-AG647")

    assert rc == 3, rc
    assert added == [], added
    printed = capsys.readouterr().out
    assert printed.count("↳ 重试退出码 = ") == 1, "重试次数不是一次：" + printed
    assert "★ rebase --continue 失败 ⇒ 先补 add 再重试一次：" in printed, printed
    assert "↳ 补 add：" in printed, printed
    assert _unmerged(repo), "停手时不许把冲突现场抹掉"


def test_only_the_whitelisted_one_is_added_when_both_kinds_are_dirty(
        tmp_path: Path, capsys) -> None:
    """白名单内 + 白名单外**同时**脏 ⇒ 只 add 白名单里那份（M-D 打的就是这里）。

    ★ 为什么还差这一条（实测）：只脏**一份**白名单外的文件时，`hit` 是空的，
      补 add 那行**根本不会执行** —— 于是 `git add -A` 那种改法照样绿，反向变异
      M-D 咬不住。把两份放一起，「加错了就多 stage 一份」才是可观察的。
    """
    repo = _conflicted_repo(tmp_path)
    ok, detail = landing.resolve_derived_conflicts(repo)
    assert ok is True, detail
    _write(repo, README_REL, _read(repo, README_REL) + "重算又写了一遍\n")
    _write(repo, CODE_REL, _read(repo, CODE_REL) + "Y = 1  # 人手里的改动\n")
    assert CODE_REL in _porcelain(repo), _porcelain(repo)

    rc, added = landing._continue_rebase_after_resolve(repo, task="T-AG647")

    assert added == [README_REL], added
    after = _porcelain(repo)
    assert "M  " + CODE_REL not in after, "白名单外的文件被 add 了（git add -A 那种顺手）：" + after
    assert CODE_REL in capsys.readouterr().out, "白名单外的脏文件没被点名"
    assert rc == 3, f"白名单外的脏文件仍在，rebase 不该走完，实得 rc={rc}\n{after}"
