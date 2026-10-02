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

卡 150（`T-G250`）增补的**五条钉子**（开跑先回退派生物 ⇒ 幂等重跑；`--no-reset` 可关）：

| # | 钉子 | 坏掉会红在哪 |
|---|---|---|
| ⑧ | 脏派生物+残留片段 ⇒ 回到干净态，且**打印**回退了什么 | 不回退 ⇒ 脏台账/残留片段还在 |
| ⑨ | **不碰源文件**：白名单源文件内容不变、改动原样保留 | 名单混进源文件 ⇒ 被 checkout 抹掉 |
| ⑩ | **幂等**：同一笔连跑两次，第二次不报「重复条目」 | 无回退 ⇒ 第二趟撞 `…twice` |
| ⑪ | `--no-reset` 真的关掉（脏派生物原样保留） | 形同虚设 ⇒ 关了也回退、照样绿 |
| ⑫ | 拿不到 HEAD（空 git 仓）⇒ **警告+继续**，不崩 | 把回退写成新闸 ⇒ 直接栈回溯 |

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

#: stage_card 桩（**故意失败**）：把链冻在「⓪ 回退派生物」之后、② 真改文档之前，
#: 好断言「回退真的发生、且只发生在派生物上」（⑧⑨ 用）。
_STUB_STAGE_CARD_FAIL = """import sys


def main(argv=None):
    print("stub-stage_card: 故意失败")
    return 3
"""

#: sync_docs 桩（带**真合并语义**，⑩⑪ 用）：把 `docs/traceability.d/*.toml` 的条目
#: 合进台账（LF→CRLF，与真台账一致）；条目已在台账里 ⇒ 打印真现场那句
#: `Cannot declare ('entries', '<id>') twice` 并退 1。`--check` 只验台账可解析
#: （与 stage_card 写后自检的调用方式对齐）。
_SYNC_DOCS_MERGE = '''import pathlib, sys, tomllib

frag_d = pathlib.Path("docs") / "traceability.d"
ledger = pathlib.Path("docs") / "traceability.toml"
ids = []
for f in sorted(frag_d.glob("*.toml")):
    for line in f.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith('[entries."') and s.endswith('"]'):
            ids.append(s.split('"')[1])
if "--check" in sys.argv:
    tomllib.loads(ledger.read_text(encoding="utf-8"))
    print("stub-sync_docs --check OK")
    sys.exit(0)
raw = ledger.read_bytes()
for tid in ids:
    if f'[entries."{tid}"]'.encode("utf-8") in raw:
        print(f"Cannot declare ('entries', '{tid}') twice")
        sys.exit(1)
for tid in ids:
    frag = (frag_d / (tid + ".toml")).read_bytes()
    raw += frag.replace(b"\\n", b"\\r\\n")
ledger.write_bytes(raw)
print("stub-sync_docs merged:", ids)
'''

#: 模拟「上一趟收口合入过本条目」的台账残留（纯 CRLF —— 与真台账一致）。
_DIRTY_ENTRY = ('[entries."T-G999"]\r\nid = "T-G999"\r\ntitle = "上一趟残留"\r\n'
                'group = "ENGINEERING"\r\nstatus = "done"\r\n'
                'evidence = ["file:code/a.py"]\r\ngaps = "合成残留"\r\n\r\n')

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


def _mk_repo(tmp: Path, card_specs_pass: bool = True, sync_docs_body: str | None = None,
             stage_card_body: str | None = None) -> Path:
    """造一个「够收口链走到 ⑥」的最小假仓库：共享文档 + 桩 + 新工具 + 文书模板。

    `sync_docs_body` / `stage_card_body`：给真桩换**行为桩**（卡 150 的幂等钉子用）——
    在 `_stage_tools` 拷完真工具**之后**覆写，只影响用到它们的测试。
    """
    repo = tmp / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "nail@example.invalid")
    _git(repo, "config", "user.name", "nail")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "config", "commit.gpgsign", "false")
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
    if stage_card_body is not None:
        _write(repo, "tools/pool/stage_card.py", stage_card_body)
    if sync_docs_body is not None:
        _write(repo, "tools/sync_docs.py", sync_docs_body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _make_rerun_dirt(repo: Path) -> None:
    """模拟「上一趟收口跑到一半」的派生物残留：脏台账 + 三个未跟踪片段（卡 150）。"""
    ledger = repo / "docs" / "traceability.toml"
    ledger.write_bytes(ledger.read_bytes() + _DIRTY_ENTRY.encode("utf-8"))
    _write(repo, "docs/changelog.d/T-G999.md", "## 上一趟残留\n\n- 合成\n")
    _write(repo, "docs/traceability.d/T-G999.toml", '[entries."T-G999"]\nid = "T-G999"\n')
    _write(repo, "复盘/交接.d/T-G999.md", "> 上一趟残留\n")


def _wand(
    repo: Path, *extra: str, allow: tuple[str, ...] = ("code",), tree: str = "."
) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-X", "utf8", str(repo / "tools" / "wb_land.py"),
           "--card", "T-G999", "--tree", tree, "--task", "T-G999", "--title", "钉子",
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
                 "--no-gate", "--commit-only", "--no-reset"):
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


# ================================================ ⑧ 自动回退派生物 + 打印（卡 150）
def test_reset_derived_restores_head_state_and_prints(tmp_path: Path) -> None:
    """脏派生物 + 残留片段 ⇒ 开跑回到干净态，且**打印**了回退了什么（不许静默）。

    ★ 用「故意失败的 stage_card 桩」把链冻在 ⓪ 之后、② 真改文档之前 —— 现场不被动过，
      才能直接断言「回退到的是 HEAD 的字节」。
    """
    repo = _mk_repo(tmp_path, stage_card_body=_STUB_STAGE_CARD_FAIL)
    _make_rerun_dirt(repo)

    done = _wand(repo, "--no-gate")

    out = _out(done)
    assert done.returncode == 2, out                      # ② 的桩故意失败 ⇒ 停在这
    assert "stub-stage_card: 故意失败" in out, out        # 确实走到了 ②（回退在它之前）
    assert (repo / "docs" / "traceability.toml").read_bytes() == b"[entries]\r\n"
    for frag in ("docs/changelog.d/T-G999.md", "docs/traceability.d/T-G999.toml",
                 "复盘/交接.d/T-G999.md"):
        assert not (repo / frag).exists(), f"残留片段没被删：{frag}"
    assert "docs/traceability.toml —— 有改动" in out      # 打印：回退了什么 + 是否真变
    assert "复盘/交接.d/T-G999.md —— HEAD 里没有" in out  # 打印：新文件残留是删掉的
    assert "本来就干净" in out                            # 打印：没变的也如实说


# ================================================ ⑨ 不碰白名单源文件
def test_reset_derived_never_touches_whitelist_sources(tmp_path: Path) -> None:
    """白名单里的源文件（`tools/wb_land.py` 自己）在回退前后**内容不变**、改动原样保留。"""
    repo = _mk_repo(tmp_path, stage_card_body=_STUB_STAGE_CARD_FAIL)
    _make_rerun_dirt(repo)
    src = repo / "tools" / "wb_land.py"
    before = src.read_bytes() + "# 白名单源文件，不许被回退碰掉\n".encode()
    src.write_bytes(before)

    done = _wand(repo, "--no-gate")

    out = _out(done)
    assert src.read_bytes() == before, "★ 回退动了白名单源文件！"
    st = _git(repo, "status", "--porcelain", "--", "tools/wb_land.py").stdout
    assert " M" in st, "源文件的改动应当原样保留（回退不许把它退回 HEAD）"
    assert "· tools/wb_land.py" not in out, "回退清单里不许出现源文件"
    assert (repo / "docs" / "traceability.toml").read_bytes() == b"[entries]\r\n", \
        "（对照）同一次开跑里派生物应当被回退——证明不是整场没跑"


# ================================================ ⑩ 幂等：同一笔连跑两次
def test_second_run_of_same_landing_hits_no_duplicate(tmp_path: Path) -> None:
    """同一笔连跑两次：第一趟半路停手留下派生物残留 ⇒ 第二趟不再报「重复条目」。

    ★ 第一趟用「计划外暂存」停手（同 2026-10-02 今晚第 1 趟的死法）：
      ② 的文书已经写好（台账已合入 T-G999、片段已生成），但没提交。
    """
    repo = _mk_repo(tmp_path, sync_docs_body=_SYNC_DOCS_MERGE)
    _write(repo, "rogue.txt", "偷渡\n")
    _git(repo, "add", "--", "rogue.txt")

    first = _wand(repo, "--no-gate")
    assert first.returncode == 2, _out(first)             # ⑥ 计划外 ⇒ 停（残留下派生物）
    ledger = (repo / "docs" / "traceability.toml").read_bytes()
    assert b'[entries."T-G999"]' in ledger, "第一趟应当残留下脏台账"

    second = _wand(repo, "--no-gate")

    out = _out(second)
    assert second.returncode == 0, out
    assert "twice" not in out and "解析不了" not in out, "★ 第二趟又撞重复条目"
    assert "已回到 HEAD 干净态" in out and "已删除" in out, out
    shown = _git(repo, "show", "HEAD:docs/traceability.toml").stdout
    assert shown.count('[entries."T-G999"]') == 1, "提交里的台账应当恰好一条，没有重复"


# ================================================ ⑪ --no-reset 真的关掉
def test_no_reset_really_disables(tmp_path: Path) -> None:
    """`--no-reset`：脏派生物**原样保留**、重复条目照样炸（与 ⑩ 的第二趟成对照）。"""
    repo = _mk_repo(tmp_path, sync_docs_body=_SYNC_DOCS_MERGE)
    _make_rerun_dirt(repo)

    with_reset = _wand(repo, "--no-gate")
    assert with_reset.returncode == 0, _out(with_reset)   # 默认（回退开着）：救回来跑绿

    ledger = repo / "docs" / "traceability.toml"
    ledger.write_bytes(ledger.read_bytes() + _DIRTY_ENTRY.encode("utf-8"))
    without = _wand(repo, "--no-gate", "--no-reset")

    out = _out(without)
    assert "回退派生物：**跳过**" in out and "--no-reset" in out, out
    assert "Cannot declare" in out and "twice" in out, "关了回退就该撞重复条目"
    assert without.returncode != 0
    wb = ledger.read_bytes()
    assert wb.count(b'[entries."T-G999"]') == 2, "关了回退：脏台账应当原样保留"
    assert (repo / "docs" / "traceability.d" / "T-G999.toml").exists(), "关了就不许删片段"


# ================================================ ⑫ 拿不到 HEAD ⇒ 警告 + 继续
def test_reset_warns_and_continues_when_head_unavailable(tmp_path: Path) -> None:
    """卡树是**没有任何提交**的空 git 仓 ⇒ 回退警告并跳过，链条继续往下走（不崩）。"""
    repo = _mk_repo(tmp_path)
    sub = repo / "sub"
    sub.mkdir()
    _git(sub, "init", "-q")                               # 空仓：没有提交 ⇒ 拿不到 HEAD

    done = _wand(repo, "--no-gate", tree="sub")

    out = _out(done)
    assert done.returncode == 2, out                      # ① 死在同一个空仓上，正常
    assert "拿不到 HEAD" in out, "回退步骤应当警告并跳过"
    assert "=== ①" in out, "警告之后应当继续，不许停在回退这一步"
    assert "Traceback" not in out
