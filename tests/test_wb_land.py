r"""钉 `tools/wb_land.py`（收口链搬进 git；卡 139 · `T-G237`）。

## 为什么有这张测试

收口链（把一张外包卡收成一笔提交的七步：迁树 → 文书 → sync_counts → 门禁 → seal →
白名单提交 → 审计合流）此前住在 **gitignore 的 scratch** `gates/diag/_integrate.py` ——
别的窗口 / 别的机器拿不到它（本仓记的「最大缺口」）。卡 139 把它搬进 git
（权威副本 `tools/pool/landing.py` + 命令行壳 `tools/wb_land.py`；文书生成器同批搬成
`tools/pool/stage_card.py` + `tools/wb_stage_card.py`）。

搬活必须钉住两件事：① **行为一字不变**（另有「新旧两条命令跑同一真场景、归一化 diff 为空」
的自证，见卡 139 复盘）；② 每条守卫**故意坏掉会红**。这张测试钉后者，**七条钉子**：

| # | 钉子 | 坏掉会红在哪 |
|---|---|---|
| ① | `--help` 列全参数 | 少一个参数 = 旧调用点断 |
| ② | `--card`/`--batch` 必须**恰好给一个** | 两个都给（或都不给）不许静默跑 |
| ③ | 缺 `gates/diag/_text_<号>.md` ⇒ 停手并点名 | 没文书还往下跑 = 生成半截提交 |
| ④ | `--allow` 给目录 ⇒ `git ls-files` 展开、`__pycache__` 不进 | 防 `.pyc` 混进提交 |
| ⑤ | 暂存区有计划外文件 ⇒ 停手 + 清暂存区 | 否则会把别人的东西夹带进提交 |
| ⑥ | fail-fast：卡规格钉子红 ⇒ 退 4、**门禁一步没跑** | 不先跑钉子 = 白烧 9 分钟全量门禁 |
| ⑦ | 拿了锁之后异常退出 ⇒ `atexit` **把锁还掉** | 锁泄漏 = 后面的卡全卡死 |

## 怎么跑（★ 不碰真仓库、不跑真门禁）

- 每条 git 相关的钉子都在 `tmp_path` 里 `git init` 一个**假仓库**，把新工具拷进去再跑
  （于是 `ROOT` 自推 = 假仓库，**绝不写主树**）；
- 外部命令（`sync_counts` / `sync_docs` / `check_toml` / `audit_progress` / `gate_lock` /
  `run_gates`）全用**桩脚本**替掉 —— `run_gates` 桩只写一个 `gate_ran.marker`，
  `gate_lock` 桩只写/删 `lock.marker`（用来判「门禁跑没跑」「锁还没还」）。
- 两条**不建仓库**的钉子：① `--help`（纯读）、② 参数互斥（在任何文件被碰之前就 `return 2`）。

## 边界（如实写，未覆盖）

- 不跑真全量门禁（卡明说贵）；门禁那两截（③′ fail-fast、④⑤ 拿锁/seal）用桩替。
- 不覆盖 ⑦ 之后（ff 合流 / rebase 自动解决）—— 那些要两棵真树并发，属卡 113/115 的范围。
- 只在 Windows（本仓主力）跑过；路径分隔符交给 git（`git ls-files` 输出 `/`）。
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"

#: 拷进假仓库的新工具（相对仓库根）—— 权威副本 + 命令行壳，一个不少。
_NEW_TOOLS = (
    "tools/wb_land.py",
    "tools/pool/__init__.py",
    "tools/pool/landing.py",
    "tools/wb_stage_card.py",
    "tools/pool/stage_card.py",
)

_TEXT = """=== gaps ===
**边界**：合成卡，仅供钉子用，不作数。
=== changelog ===
## 2026-10-02 · 钉子用
- 为什么：证明收口链搬进 git 后行为还在
- 改了什么：无（合成）
=== checkpoint ===
> **2026-10-02 · CHECKPOINT（合成）**：钉子用。
"""

_MAYBE = "import sys\nprint('stub')\nsys.exit(0)\n"

#: 门禁锁桩：每次调用都落一行 `gate_lock_calls.log`；`acquire` 建 `lock.marker`、`release` 删它。
#: ★ 为什么要那本账：`atexit` 在**任何**退出路径都会 `release`（连 fail-fast 那条也还一次），
#:   所以"退出后没有 `lock.marker`"**不能**证明"从没拿过锁"—— 只能看这本账。
_GATE_LOCK = """import pathlib, sys
with pathlib.Path("gate_lock_calls.log").open("a", encoding="utf-8") as fh:
    fh.write(" ".join(sys.argv[1:]) + "\\n")
mk = pathlib.Path("lock.marker")
if "acquire" in sys.argv:
    mk.write_text("locked", encoding="utf-8")
elif "release" in sys.argv and mk.exists():
    mk.unlink()
print("stub-gate_lock", " ".join(sys.argv[1:]))
sys.exit(0)
"""

#: 全量门禁桩：只留一个「门禁跑过」的印记（永不真起服务）。
_RUN_GATES = """import pathlib, sys
pathlib.Path("gate_ran.marker").write_text("ran", encoding="utf-8")
print("stub-run_gates")
sys.exit(0)
"""

_ENV = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}


# ================================================================ 加载实现模块
def _load_landing() -> ModuleType:
    """按文件路径加载 `tools/pool/landing.py`（不 import 包、不动 `sys.path`）。"""
    path = TOOLS / "pool" / "landing.py"
    spec = importlib.util.spec_from_file_location("wb_landing_under_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ================================================================ 假仓库
def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=str(repo),
                          env=_ENV, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)


def _write(root: Path, rel: str, text: str, crlf: bool = False) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    data = text.replace("\n", "\r\n") if crlf else text
    p.write_bytes(data.encode("utf-8"))


def _stage_tools(repo: Path) -> None:
    for rel in _NEW_TOOLS:
        src = TOOLS / rel[len("tools/"):]
        dst = repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())


def _mk_repo(tmp: Path, card_specs_pass: bool = True) -> Path:
    """造一个「够收口链走到 ⑥」的最小假仓库：共享文档 + 桩 + 新工具 + 文书模板。"""
    repo = tmp / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "nail@example.invalid")
    _git(repo, "config", "user.name", "nail")
    _git(repo, "config", "core.autocrlf", "false")
    _write(repo, ".gitignore", "__pycache__/\n*.pyc\n")
    _write(repo, "README.md", "hello\n")
    _write(repo, "code/a.py", "X = 1\n")
    changelog_head = "## 2026-10-02 · 现有\n\n- 旧条目\n"
    _write(repo, "docs/traceability.toml", "[entries]\n", crlf=True)
    _write(repo, "docs/changelog.md", changelog_head, crlf=True)
    _write(repo, "复盘/交接-重构进度.md", "# 交接\n", crlf=True)
    _write(repo, "gates/last.json", "{}\n")
    _write(repo, "gates/reuse.json", "{}\n")
    _write(repo, "docs/changelog.d/.keep", "")
    _write(repo, "gates/diag/_text_TG999.md", _TEXT)
    for rel in ("tools/sync_counts.py", "tools/sync_docs.py", "scripts/check_toml.py",
                "scripts/audit_progress.py"):
        _write(repo, rel, _MAYBE)
    _write(repo, "gates/diag/gate_lock.py", _GATE_LOCK)
    _write(repo, "scripts/run_gates.py", _RUN_GATES)
    body = "def test_ok():\n    assert True\n" if card_specs_pass \
        else "def test_red():\n    assert False\n"
    _write(repo, "tests/test_card_specs_tracked.py", body)
    _stage_tools(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _wand(
    repo: Path, *extra: str, allow: tuple[str, ...] = ("code",)
) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-X", "utf8", str(repo / "tools" / "wb_land.py"),
           "--card", "T-G999", "--tree", ".", "--task", "T-G999", "--title", "钉子",
           "--type", "feat", "--group", "ENGINEERING", "--evidence", "code/a.py",
           "--allow", *allow, *extra]
    return subprocess.run(cmd, cwd=str(repo), env=_ENV, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _out(done: subprocess.CompletedProcess) -> str:
    return (done.stdout or "") + (done.stderr or "")


# ================================================================ ① --help
def test_help_lists_every_argument() -> None:
    """`--help` 要列出全部参数（少一个 = 旧调用点找不到入口）。"""
    done = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "wb_land.py"), "--help"],
                          env=_ENV, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    assert done.returncode == 0, _out(done)
    for flag in ("--card", "--batch", "--tree", "--task", "--title", "--type", "--scope",
                 "--group", "--evidence", "--allow", "--port-base", "--refs",
                 "--no-gate", "--commit-only"):
        assert flag in done.stdout, f"`--help` 少了 {flag}"
    # 文书生成器那一半（同一批搬进来）也照钉
    done2 = subprocess.run(
        [sys.executable, "-X", "utf8", str(TOOLS / "wb_stage_card.py"), "--help"],
        env=_ENV, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert done2.returncode == 0, _out(done2)
    for flag in ("--tree", "--id", "--title", "--group", "--evidence",
                 "--gaps-file", "--changelog-file", "--checkpoint-file", "--text-file"):
        assert flag in done2.stdout, f"stage_card `--help` 少了 {flag}"


# ================================================================ ② 参数互斥
def test_card_and_batch_is_exactly_one() -> None:
    """`--card` 与 `--batch` **恰好给一个**：都给 / 都不给都退非 0 并说清。"""
    base = [sys.executable, "-X", "utf8", str(TOOLS / "wb_land.py"),
            "--tree", ".", "--task", "T-G999", "--title", "t", "--evidence", "e", "--allow", "a"]
    both = subprocess.run([*base, "--card", "T-G999", "--batch", "B1"], env=_ENV,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    neither = subprocess.run(base, env=_ENV, capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
    assert both.returncode != 0 and "恰好给一个" in _out(both), _out(both)
    assert neither.returncode != 0 and "恰好给一个" in _out(neither), _out(neither)


# ================================================================ ③ 缺文书模板
def test_missing_text_file_stops_and_names_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """缺 `gates/diag/_text_<号>.md` ⇒ 停手并印出**缺哪一个**（退非 0）。

    ★ 用 `tmp_path`（里面没有 `gates/diag/`）+ 改 `ROOT`/`TEXT` ⇒ 与真仓状态无关。
    """
    mod = _load_landing()
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "TEXT", tmp_path / "gates" / "diag" / "_text_{task}.md")
    with pytest.raises(AssertionError) as ei:
        mod.main(["--card", "T-G000", "--tree", ".", "--task", "T-G000", "--title", "t",
                  "--evidence", "e", "--allow", "a"])
    assert "缺文档件" in str(ei.value)
    assert "_text_TG000.md" in str(ei.value)


# ================================================================ ④ --allow 目录展开
def test_allow_dir_expands_via_git_ls_files_and_drops_pycache(tmp_path: Path) -> None:
    """目录用 `git ls-files -c -o --exclude-standard` 展开；`__pycache__` **不进**。

    ★ 「会咬」对照：同目录里另放一个**未被忽略**的未跟踪文件 ⇒ 它**要**被列进来
      （证明被排除是 `.gitignore` 起了作用，不是"反正没列"）。
    """
    mod = _load_landing()
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _write(repo, ".gitignore", "__pycache__/\n")
    _write(repo, "code/keep.py", "K = 1\n")
    _write(repo, "code/fresh.py", "F = 1\n")            # 未跟踪、未被忽略 ⇒ 应被列出
    _write(repo, "code/__pycache__/x.pyc", "b\n")       # 未跟踪、被忽略 ⇒ 不许列出
    _git(repo, "add", "--", ".gitignore", "code/keep.py")

    allow = mod.expand_allow(repo, ["code"])

    assert "code/keep.py" in allow, allow
    assert "code/fresh.py" in allow, allow
    assert not any("__pycache__" in a for a in allow), allow
    # 文件参数原样透传（不走目录展开）
    assert mod.expand_allow(repo, ["code/keep.py"]) == ["code/keep.py"]


# ================================================================ ⑤ 计划外暂存
def test_unexpected_staged_file_stops_and_resets(tmp_path: Path) -> None:
    """暂存区里出现**计划外**文件 ⇒ 停手（退 2）+ 清暂存区（不许夹带别人的东西）。"""
    repo = _mk_repo(tmp_path)
    _write(repo, "rogue.txt", "偷渡\n")
    _git(repo, "add", "--", "rogue.txt")               # 先偷偷 stage 一个白名单外的

    done = _wand(repo, "--no-gate")

    assert done.returncode == 2, _out(done)
    assert "计划外" in _out(done), _out(done)
    staged = _git(repo, "diff", "--cached", "--name-only").stdout.strip()
    assert staged == "", f"停手之后不许留暂存：{staged!r}"


# ================================================================ ⑥ fail-fast
def test_fail_fast_stops_before_gate_and_takes_no_lock(tmp_path: Path) -> None:
    """卡规格钉子红 ⇒ 退 4，**且门禁一步都没跑**（没拿锁、没起门禁）。

    ★ 「没拿锁」看的是门禁锁桩自己那本账（`gate_lock_calls.log`）里**没有 `acquire`** ——
      不能看"退出后 `lock.marker` 在不在"：`atexit` 会把锁还掉（连这条路也还一次），
      于是"没 marker"对**拿过锁**与**没拿过锁**是一样长的（突变检验当场咬出这个假判据）。
    坏掉的写法（把 fail-fast 挪到拿锁/跑门禁之后）：账里会出现 `acquire`、或 `gate_ran.marker`
    会出现 —— 两条断言任一条就会红。
    """
    repo = _mk_repo(tmp_path, card_specs_pass=False)

    done = _wand(repo)                                  # 不给 --no-gate ⇒ 走 ③′ 与 ④⑤

    assert done.returncode == 4, _out(done)
    assert "省下 9 分钟" in _out(done), _out(done)
    calls = (repo / "gate_lock_calls.log").read_text(encoding="utf-8") \
        if (repo / "gate_lock_calls.log").exists() else ""
    assert "acquire" not in calls, f"fail-fast 之前不许拿门禁锁，账里却有：{calls!r}"
    assert not (repo / "gate_ran.marker").exists(), "fail-fast 红了不许再跑门禁"


# ================================================================ ⑦ atexit 还锁
def test_atexit_releases_lock_on_abnormal_exit(tmp_path: Path) -> None:
    """拿了门禁锁之后**异常退出**（⑥ 的 `git add` 失败 ⇒ `sys.exit(2)`）⇒ 锁被 `atexit` 还掉。

    坏掉的写法（去掉 `atexit.register`）：`lock.marker` 会留在那里 —— 那条断言就会红。
    ★ 这条路径**不是**任何一条"显式 release"（不是门禁红、不是计划外早退）—— 所以
      还要顺带断言 stdout 里**没有**那句「已顺手释放门禁锁」，证明还锁的确实是 `atexit`。
    """
    repo = _mk_repo(tmp_path)

    done = _wand(repo, allow=("does_not_exist.py",))  # ⑥ `git add` 找不到路径 ⇒ 退 2（异常退出）

    assert (repo / "gate_ran.marker").exists(), "应当已经走过 ④ 的门禁（桩）"
    assert done.returncode != 0, _out(done)
    assert "★ 命令失败" in _out(done), _out(done)
    assert "已顺手释放门禁锁" not in _out(done), "这条不是显式 release 路径"
    calls = (repo / "gate_lock_calls.log").read_text(encoding="utf-8") \
        if (repo / "gate_lock_calls.log").exists() else ""
    assert "acquire" in calls, f"应当拿过锁：{calls!r}"
    assert "release" in calls, f"异常退出后应当还过锁：{calls!r}"
    assert not (repo / "lock.marker").exists(), "★ 异常退出后锁必须被 atexit 还掉"
