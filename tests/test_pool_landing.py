r"""钉「落地链自己改的东西，自己验证」：翻账之后必须重算现算文档（卡 E76 · `T-AG579`）。

## 为什么这张测试

`docs/subsystems/pool/README.md` 的「队列卡数 | N 张（X done / Y pending）」是
`scripts/gen_pool_readme.py` 从 `docs/workbacklog.toml` **现算**的。而落地链的 ⑤′ 会
`flip_card_status()` 把卡从 `pending` 翻成 `done` —— **台账分布当场变了**，README 却没人
重算。⇒ **每落一张卡，主树的 README 就错一次**，而判据（`tests/test_pool_readme_counts.py`）
只在**下一次**有人跑门禁时才说话。

这不是「忘了一次」：是**顺序缺陷** —— 翻账（⑤′）在门禁（④）之后，README 的现算判据在门禁里。
所以 `landing.py` 现在在**翻账之后、暂存之前**多了一步 ⑤′.5 `recount_derived()`：真写盘重算，
改了就把那份 README 补进 `allow` 随这一笔提交。

## 六条钉子（对应卡 E76 §判据 1–6）

| # | 钉子 | 坏掉会红在哪 |
|---|---|---|
| 1 | 翻账让 README 过期 ⇒ 落地链**自己修**（真写盘，不是只跑 `--check`） | 提交里那句仍是旧分布 |
| 2 | 重算在**翻账之后**（顺序钉子） | 提交里 README 记的是翻账**前**的分布 |
| 3 | `--check` 仍能抓到过期（本卡**不许**削弱它） | 生成器对错行不吭声 / 退 0 |
| 4 | 重算只带 README，不许夹带别的文件（暂存清单无「计划外」） | `extra` 非空 / 多出无关文件 |
| 5 | `--commit-only` 也要重算（那条路同样翻账） | 那条路下 README 仍是旧的 |
| 6 | 不许把 README 从门禁判据里摘掉 | 钉子被删 / 只剩正向、没有反向 |

## 怎么跑（★ 不碰真仓库、不跑真门禁）

- 每条钉子都在 `tmp_path` 里 `git init` 一个**假仓库**（`ROOT` 自推 = 假仓库），把
  `tools/pool/landing.py` 等真工具拷进去跑；
- **生成器用真件**（`scripts/gen_pool_readme.py` 原字节拷进假仓库）—— 本卡治的正是
  「落地链与生成器之间那条接缝」，用桩会把接缝测没；
- 外部命令（`sync_counts` / `sync_docs` / `check_toml` / `audit_progress` / `gate_lock` /
  `run_gates`）仍是桩（与 `tests/test_wb_land.py` 同一套体例）；
- 假仓库里**现算文档是自洽的**（夹具末尾真跑一次生成器），所以「落地前 `--check` 绿」是前提，
  「落地后 `--check` 还能绿」才是本卡的结论。

## 边界（如实写，未覆盖）

- 不跑真全量门禁（贵且与本卡无关）；门禁整段用 `--no-gate` 跳过。
- **腿②（卡 E77）**：`tools/wb_land.py` 壳层那一条只在 `pool.landing.main()` 返回 **0**
  （= 已经提交）之后才跑，所以它抓的是「提交之后发现自己过期了」。它抓不住提交之前 ——
  那是腿①的职责。两条腿各有一条 e2e 钉子；`--commit-only` 上腿①哑掉时的现场由
  `test_shell_leg_catches_what_the_landing_leg_missed` 复现（删掉假仓库里的 ⑤′.5）。
- 批模式（`--batch`）的重算走的是**同一行**（两分支汇合之后），本文件只钉单卡与
  `--commit-only` 两条路；批路径由 `tests/test_wb_land.py` 的批 e2e 与变异脚本覆盖。
- 只在 Windows（本仓主力）跑过。
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"

README_REL = "docs/subsystems/pool/README.md"
MODULES_REL = "docs/subsystems/pool/modules.toml"
BACKLOG_REL = "docs/workbacklog.toml"
GEN_REL = "scripts/gen_pool_readme.py"
#: ★ 卡 E77：两条腿共同调用的**独立检查器**（生成器的调用方，不含现算口径）。
CHECKER_REL = "scripts/check_derived_docs.py"
#: ★ 卡 E78：同一个病的**第二个面** —— 落地链每笔自动补 `docs/changelog.d/{task}.md`，
#: 而 `docs/INDEX.md` 是按目录数篇数 + 算总字数的投影 ⇒ 每落一张卡它也过期一次。
INDEX_REL = "docs/INDEX.md"
INDEX_GEN_REL = "scripts/gen_doc_index.py"
BEGIN = "<!-- pool-margin:begin -->"
END = "<!-- pool-margin:end -->"

#: 拷进假仓库的真工具（相对仓库根）—— 与 `tests/test_wb_land.py` 的 `_NEW_TOOLS` 同批；
#: 这里少了几份用不到的（`wb_task.py` / `pytest_select.py` 等只被别的子命令用到）。
_NEW_TOOLS = (
    "tools/wb_land.py",
    "tools/pool/__init__.py",
    "tools/pool/landing.py",
    "tools/pool/review.py",
    "tools/wb_stage_card.py",
    "tools/pool/stage_card.py",
    "tools/card_doc_budget.py",
    "tools/pool/snapshot.py",
    "tools/pool/task.py",
    "tools/pool/plan.py",
    "tools/pool/projects.py",
    "tools/pool/lastgood.py",
    "tools/pool/queue.py",
    "tools/gate_verdict.py",
    # ★ 生成器 `_is_card_log()` 会 `from pool.jobs import is_card_log`（判据一份，卡 E74）
    "tools/pool/jobs.py",
)

_TEXT = """=== gaps ===
**边界**：合成卡，仅供钉子用，不作数（指针 `code/a.py`）。
=== changelog ===
## 2026-10-02 · 钉子用
- 为什么：证明翻账之后会自己重算现算文档
- 改了什么：无（合成）
=== checkpoint ===
> **2026-10-02 · CHECKPOINT（合成）**：钉子用。
"""

#: 桩：import 块与正文之间空一行（否则 ruff 的 I001 会让 `--preflight` 的 ruff 快检红在夹具上）。
_MAYBE = "import sys\n\nprint('stub')\nsys.exit(0)\n"

_GATE_LOCK = """import pathlib, sys
mk = pathlib.Path("lock.marker")
if "acquire" in sys.argv:
    mk.write_text("locked", encoding="utf-8")
elif "release" in sys.argv and mk.exists():
    mk.unlink()
print("stub-gate_lock", " ".join(sys.argv[1:]))
sys.exit(0)
"""

_RUN_GATES = """import pathlib
import sys

pathlib.Path("gate_ran.marker").write_text("ran", encoding="utf-8")
print("stub-run_gates")
sys.exit(0)
"""

#: 合成项目书的骨架：标记之间先放占位（夹具末尾由**真生成器**整块替换成现算内容）。
_README_TEMPLATE = f"""# 合成树里的 pool 项目书

> 文件头在标记外。

## 1. 它现在是什么（代码边际）

{BEGIN}
占位：夹具末尾由真生成器整块重写。
{END}

## 2. 度量

口径句在标记外。
"""

#: 假仓库的队列：2 done + 1 pending ⇒ 落地把 T-G999 翻成 done 之后分布变 3 / 0，
#: 「队列卡数」那行**必然**从 `3 张（2 done / 1 pending）` 变成 `3 张（3 done / 0 pending）`。
_BACKLOG = """[base]
reviewed = "abc1234"

[[cards]]
id = "T-G999"
task = "T-G999"
title = "钉子卡"
tree = ""
spec = ""
files = ["code/a.py"]
depends = []
risk = "low"
status = "pending"

[[cards]]
id = "A001"
task = "T-G900"
title = "已完成的邻居"
tree = ""
spec = ""
files = ["code/a.py"]
depends = []
risk = "low"
status = "done"

[[cards]]
id = "A002"
task = "T-G901"
title = "另一个已完成的邻居"
tree = ""
spec = ""
files = ["code/a.py"]
depends = []
risk = "low"
status = "done"
"""

STALE_LINE = "3 张（2 done / 1 pending）"
FRESH_LINE = "3 张（3 done / 0 pending）"

_ENV = {k: v for k, v in os.environ.items()
        if k not in ("PYTHONPATH", "TF_PYTEST_WORKERS", "TF_GATE_MIN_FREE_GB")}

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ================================================================ 假仓库
def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    # `core.quotepath=false`：不然中文路径会被 git 转义成 `"\345\244\215..."`，
    # 拿它去和白名单比对永远不相等（`landing.git()` 用的是同一口径）。
    return subprocess.run(["git", "-c", "commit.gpgsign=false",
                           "-c", "core.quotepath=false", *args], cwd=str(repo),
                          env=_ENV, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)


def _write(root: Path, rel: str, text: str, crlf: bool = False) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    data = text.replace("\n", "\r\n") if crlf else text
    p.write_bytes(data.encode("utf-8"))


def _stage_tools(repo: Path) -> None:
    for rel in _NEW_TOOLS:
        src = ROOT / rel
        dst = repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())


def _manifest_for(repo: Path) -> str:
    """按假仓库里**实际存在**的 `tools/pool/*.py|toml` 生成清单（漏一个模块生成器就退 1）。"""
    lines = ["# 合成清单：夹具按实际文件生成（真实仓那份是人写的）"]
    pool = repo / "tools" / "pool"
    for path in sorted(pool.glob("*")) + sorted(pool.glob("*.toml")):
        if not path.is_file() or path.suffix not in (".py", ".toml"):
            continue
        lines.append("")
        lines.append("[[module]]")
        lines.append(f'name = "{path.name}"')
        lines.append(f'duty = "{path.name} 的合成职责（夹具）"')
        lines.append('cli = "无"')
    return "\n".join(lines) + "\n"


def _run_gen(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """在假仓库里跑**真生成器**（子进程、真落盘/真退出码，不 import 它 —— 防止「测自己」）。"""
    return subprocess.run(
        [sys.executable, "-X", "utf8", GEN_REL, *args],
        cwd=str(repo), env=_ENV, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False, creationflags=_NO_WINDOW,
    )


def _run_index_gen(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """在树里跑**真** `scripts/gen_doc_index.py`（`--target docs`：不碰 `复盘/INDEX.md`）。"""
    return subprocess.run(
        [sys.executable, "-X", "utf8", INDEX_GEN_REL, "--target", "docs", *args],
        cwd=str(repo), env=_ENV, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False, creationflags=_NO_WINDOW,
    )


def _mk_repo(tmp_path: Path) -> Path:
    """造一个「够收口链走到 ⑥」且**现算文档自洽**的假仓库。

    与 `tests/test_wb_land.py::_mk_repo` 同体例，多铺这几样（本卡的被测面）：
    `scripts/gen_pool_readme.py`（**真件**）、`docs/subsystems/pool/modules.toml`（按实际文件
    生成）、`docs/subsystems/pool/README.md`（夹具末尾由真生成器写成自洽态）；
    ★ 卡 E78：`scripts/gen_doc_index.py`（**真件**）+ `docs/INDEX.md`（同样由真生成器写成
    自洽态）—— 少了这两样，多目标检查器会走「这棵树里没有它」那一支，第二个面就测不到。
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "nail@example.invalid")
    _git(repo, "config", "user.name", "nail")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "config", "commit.gpgsign", "false")
    _write(repo, ".gitignore",
           "__pycache__/\n*.pyc\n"
           "gate_lock_calls.log\ngate_ran.marker\nlock.marker\n")
    _write(repo, "README.md", "hello\n")
    _write(repo, "code/a.py", "X = 1\n")
    _write(repo, "docs/traceability.toml", "[entries]\n", crlf=True)
    _write(repo, "docs/changelog.md", "## 2026-10-02 · 现有\n\n- 旧条目\n", crlf=True)
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
    _write(repo, "tests/test_card_specs_tracked.py", "def test_ok():\n    assert True\n")
    _stage_tools(repo)
    # ---- 本卡的被测面：真生成器 + 清单 + 项目书 + 队列 ----
    _write(repo, GEN_REL, (ROOT / GEN_REL).read_bytes().decode("utf-8"))
    # ★ 卡 E77：腿① 只调独立检查器（不再直跑生成器）⇒ 假仓库里必须有它，
    #   否则 `recount_derived()` 会走「没有检查器 ⇒ 停手」那一支（退 2）。
    _write(repo, CHECKER_REL, (ROOT / CHECKER_REL).read_bytes().decode("utf-8"))
    _write(repo, MODULES_REL, _manifest_for(repo), crlf=True)
    _write(repo, README_REL, _README_TEMPLATE, crlf=True)
    _write(repo, BACKLOG_REL, _BACKLOG, crlf=True)
    # 夹具末尾真跑一次生成器 ⇒ README 与台账**自洽**（落地前 `--check` 必须是绿的）
    made = _run_gen(repo)
    assert made.returncode == 0, made.stdout + made.stderr
    assert STALE_LINE in (repo / README_REL).read_text(encoding="utf-8")
    # ★ 卡 E78：第二个面（`docs/INDEX.md` ← `scripts/gen_doc_index.py`）。
    #   必须在真生成器写完 README 之后跑 —— 否则 INDEX 里那一篇项目的路径还没出现。
    _write(repo, INDEX_GEN_REL, (ROOT / INDEX_GEN_REL).read_bytes().decode("utf-8"))
    indexed = _run_index_gen(repo)
    assert indexed.returncode == 0, indexed.stdout + indexed.stderr
    assert (repo / INDEX_REL).is_file(), "夹具：INDEX 没生成出来"
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _wand(repo: Path, *extra: str, card: str = "T-G999", task: str = "T-G999",
          allow: tuple[str, ...] = ("code",)) -> subprocess.CompletedProcess:
    """跑一次 wb_land（`--tree .`：产物就在假仓库里，省掉 worktree 那层）。"""
    cmd = [sys.executable, "-X", "utf8", str(repo / "tools" / "wb_land.py"),
           "--card", card, "--tree", ".", "--task", task, "--title", "钉子",
           "--type", "feat", "--group", "ENGINEERING", "--evidence", "code/a.py",
           "--allow", *allow, *extra]
    return subprocess.run(cmd, cwd=str(repo), env=_ENV, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False,
                          creationflags=_NO_WINDOW)


def _out(done: subprocess.CompletedProcess) -> str:
    return (done.stdout or "") + (done.stderr or "")


def _head_text(repo: Path, rel: str) -> str:
    """HEAD 里那份文件的内容（提交之后的真读数，不看工作区）。"""
    got = _git(repo, "show", f"HEAD:{rel}")
    assert got.returncode == 0, got.stderr
    return got.stdout


def _head_files(repo: Path) -> list[str]:
    """这一笔提交改了哪些文件（相对仓库根，`/` 分隔）。"""
    got = _git(repo, "show", "--name-only", "--format=", "HEAD")
    assert got.returncode == 0, got.stderr
    return [x.strip() for x in got.stdout.splitlines() if x.strip()]


# ================================================================ 判据 1
def test_landing_recomputes_the_derived_readme(tmp_path: Path) -> None:
    """判据 1：翻账让 README 过期 ⇒ 落地链**自己修**（真写盘），提交里那句是新的。

    坏掉的写法：⑤′.5 整段不存在（本卡开工前就是这样）⇒ 提交里仍是 `2 done / 1 pending`。
    ★ 这一条同时钉住「不许只跑 `--check` 然后失败」：只跑 check 的话，落地链会停在
      ⑤′ 前面或退 2，`returncode == 0` 就过不去。
    """
    repo = _mk_repo(tmp_path)
    assert _run_gen(repo, "--check").returncode == 0, "前提：落地前 README 与台账自洽"
    _write(repo, "code/a.py", "X = 2\n")

    done = _wand(repo, "--no-gate", "--no-review")
    out = _out(done)

    assert done.returncode == 0, out
    # 翻账真的发生了（否则这条钉子测的是别的东西）
    assert "[队列] 卡 T-G999：pending → done" in out, out
    # 生成器是**不带 --check** 跑的 ⇒ 它真写盘了（安静/写盘两种体例都在允许集里，
    # 这里是「变了」那一支 ⇒ 必须是「写了」）
    assert "[OK  ] 写了 " + README_REL in out, out
    assert "--check" not in out.split("=== ⑤′")[1].split("=== ⑥")[0], out
    # 提交里那句是**翻账之后**的分布
    head = _head_text(repo, README_REL)
    assert FRESH_LINE in head, head
    assert STALE_LINE not in head, head
    # 交完之后假仓库自己也是自洽的（这一笔真的把它修好了）
    checked = _run_gen(repo, "--check")
    assert checked.returncode == 0, checked.stdout


def test_recount_is_quiet_when_nothing_changed(tmp_path: Path) -> None:
    """判据 1 的另一半：**没变就安静**（照既有体例 `[OK  ] … 已是最新，未写盘`）。

    ★ 为什么要这一条：重算写成「每次都覆盖」也能让上一条绿，但那会把 README 的行尾/日期
      动一遍（无谓改动）。这里用「登记型提交」（`--task` ≠ 卡.task ⇒ 不翻账）造出
      「台账分布不变」的场景。
    """
    repo = _mk_repo(tmp_path)
    _write(repo, "code/a.py", "X = 2\n")
    # 登记型提交的文书文件按 `_text_{task}.md` 找 ⇒ 换 task 就得补一份
    _write(repo, "gates/diag/_text_TG888.md", _TEXT)

    done = _wand(repo, "--no-gate", "--no-review", task="T-G888")
    out = _out(done)

    assert done.returncode == 0, out
    assert "[OK  ] " + README_REL + " 已是最新，未写盘" in out, out
    # ★ 卡 E78：`docs/` 不再「全都不变」了 —— ⑤′ 自动补的 `docs/changelog.d/T-G888.md`
    #   是这一笔自己带进来的新文件，INDEX 依约要跟着变。所以这条钉子的口径收窄到
    #   **README 安静**（它原本要测的就是这个），INDEX 的安静另有一条钉子。
    assert "★ 重算改了它 ⇒ 随这一笔提交：" + README_REL not in out, out
    assert README_REL not in _head_files(repo), _head_files(repo)


# ================================================================ 判据 2
def test_recount_happens_after_the_flip(tmp_path: Path) -> None:
    """判据 2（**顺序钉子**）：翻账 → 重算 → 暂存 → 提交。

    两条独立的证据：
      ① stdout 里「翻账那行」在「重算那行」**之前**；
      ② 提交里 README 记的是**翻账之后**的分布（`3 done / 0 pending`）—— 若重算被挪到
         翻账之前，它写下去的是 `2 done / 1 pending`，随后翻账又把它变旧 ⇒ 这里必红。
    """
    repo = _mk_repo(tmp_path)
    _write(repo, "code/a.py", "X = 2\n")

    done = _wand(repo, "--no-gate", "--no-review")
    out = _out(done)

    assert done.returncode == 0, out
    flip_at = out.find("[队列] 卡 T-G999：pending → done")
    recount_at = out.find("[OK  ] 写了 " + README_REL)
    assert flip_at >= 0, out
    assert recount_at >= 0, out
    why = f"重算跑在翻账之前（flip@{flip_at} / recount@{recount_at}）：\n{out}"
    assert flip_at < recount_at, why
    assert FRESH_LINE in _head_text(repo, README_REL)


# ================================================================ 判据 3
def test_check_still_catches_a_stale_readme(tmp_path: Path) -> None:
    """判据 3：`--check` 仍能抓到过期（本卡**不许**削弱它），并点名第几行。"""
    repo = _mk_repo(tmp_path)
    assert _run_gen(repo, "--check").returncode == 0, "前提：自洽"

    raw = (repo / README_REL).read_bytes().decode("utf-8")
    lines = raw.replace("\r\n", "\n").split("\n")
    target = next(i for i, line in enumerate(lines) if STALE_LINE in line)
    lines[target] = lines[target].replace("2 done / 1 pending", "9 done / 9 pending")
    (repo / README_REL).write_bytes("\n".join(lines).replace("\n", "\r\n").encode("utf-8"))

    done = _run_gen(repo, "--check")

    assert done.returncode == 1, done.stdout
    assert f"第 {target + 1} 行" in done.stdout, done.stdout
    assert "9 done / 9 pending" in done.stdout, done.stdout


# ================================================================ 判据 4
def test_recount_brings_in_no_unexpected_files(tmp_path: Path) -> None:
    """判据 4：旧链不进提交的东西不许被顺手带进来。

    重算只写 `RECOUNT_DOCS` 那一项 ⇒ 暂存清单里**没有**「计划外」文件；
    这一笔的文件集合必须落在「本卡的产物 + 派生物」这个白名单里。
    """
    repo = _mk_repo(tmp_path)
    _write(repo, "code/a.py", "X = 2\n")

    done = _wand(repo, "--no-gate", "--no-review")
    out = _out(done)

    assert done.returncode == 0, out
    assert "  extra  = []" in out, out
    assert "★ 计划外或空暂存区 ⇒ 停手" not in out, out
    files = set(_head_files(repo))
    allowed = {
        "code/a.py",
        README_REL,
        BACKLOG_REL,
        "docs/traceability.toml",
        "docs/changelog.md",
        "复盘/交接-重构进度.md",
        "gates/last.json",
        "gates/reuse.json",
        "docs/changelog.d/T-G999.md",
        "docs/traceability.d/T-G999.toml",
        "复盘/交接.d/T-G999.md",
        INDEX_REL,          # ★ 卡 E78：第二个面（篇数表跟着新片段一起变）
    }
    surprise = files - allowed
    assert not surprise, f"这一笔多带了计划外的文件：{sorted(surprise)}"
    assert README_REL in files, files


# ================================================================ 判据 5
def test_commit_only_path_also_recomputes(tmp_path: Path) -> None:
    """判据 5：`--commit-only` 从 ⑤′ 起跑、跳过门禁 —— 它**同样**会翻账，所以也**必须**重算。

    坏掉的写法：把 ⑤′.5 放进 `if not a.commit_only:` 里 ⇒ 这条路下 README 仍是旧的。
    """
    repo = _mk_repo(tmp_path)
    _write(repo, "code/a.py", "X = 2\n")

    done = _wand(repo, "--no-gate", "--commit-only", "--no-reset", "--no-review")
    out = _out(done)

    assert done.returncode == 0, out
    assert "①~⑤ 跳过" in out, out                      # 确认真走的是这条路
    assert "[队列] 卡 T-G999：pending → done" in out, out
    assert "[OK  ] 写了 " + README_REL in out, out
    head = _head_text(repo, README_REL)
    assert FRESH_LINE in head, head
    assert README_REL in _head_files(repo)


# ================================================================ 判据 6
def test_readme_pins_are_not_removed_from_the_gate(tmp_path: Path) -> None:
    """判据 6：不许把 README 从门禁判据里摘掉 —— 那两条钉子（正/反）必须还在。

    ★ 只钉「结构还在」不够，还钉它们**各自断言了什么**：正向那条要 `--check` 退 0，
      反向那条要退非零。删掉任一半，本卡判据 3 就没有判据来源了。
    """
    pins = ROOT / "tests" / "test_pool_readme_counts.py"
    source = pins.read_text(encoding="utf-8")
    tree = ast.parse(source)
    funcs = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert "test_real_readme_matches_recount" in funcs, sorted(funcs)
    assert "test_hand_edited_count_reports_line" in funcs, sorted(funcs)

    # 正向那条：真跑 `--check` 并断言退出码 0（没有它，「README 是现算的」就没人钉了）
    positive = ast.dump(funcs["test_real_readme_matches_recount"])
    assert "'--check'" in positive, "正向钉子不再跑 --check"
    assert "returncode" in positive, "正向钉子不再断言退出码"
    # 反向那条：要断言非零退码 **并点名行号**（本卡判据 3 的判据来源）
    negative_src = ast.get_source_segment(source, funcs["test_hand_edited_count_reports_line"])
    assert negative_src is not None
    assert "returncode" in negative_src, "反向钉子不再断言退出码"
    assert "第 " in negative_src, "反向钉子不再点名第几行"

    # 门禁那两条钉子里还有一条在别的文件（判据 1 曾经红在它上面）：同一条口径，钉住它在
    jobs_source = (ROOT / "tests" / "test_pool_jobs.py").read_text(encoding="utf-8")
    assert "test_gen_pool_readme_check_is_green" in jobs_source, "那条钉子在门禁里被删了"
    assert "与现算一致" in jobs_source, "那条钉子不再断言「与现算一致」"


# ================================================================ 卡 E77：第二条腿
#: 卡 E77（`T-AG580`）的五条钉子：判据 1（真树一致性）/ 判据 2（腿①只调检查器、检查器里
#: 不长第二份现算口径）/ 判据 3（第二条腿不是摆设）/ 判据 4（`--commit-only` 也覆盖）/
#: 判据 5（既有判据一条都不许削弱）。
#: ★ 「删掉修复 ⇒ 判据 4 的钉子红」由 `gates/diag/_rev_E77.py` 的变异 #1 当场证明。


def _run_checker(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """在树里跑**真检查器**（子进程 —— 走磁盘上的当前代码，正是卡 E76 教的那条）。"""
    return subprocess.run(
        [sys.executable, "-X", "utf8", CHECKER_REL, *args],
        cwd=str(repo), env=_ENV, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False, creationflags=_NO_WINDOW,
    )


def _drop_landing_leg(repo: Path) -> None:
    """把假仓库里 `landing.py` 的 ⑤′.5 **整段删掉** —— 复现卡 E76 的现场。

    E76 落地那一笔改的正是 `tools/pool/landing.py`：运行时加载的是**改动前**的代码，
    ⑤′.5 根本不存在（`gates/diag/land-E76.log` 里翻账之后直接 `staged`）。
    删掉之后只剩壳层的腿②站着 —— 那正是本卡要补的那条腿。
    """
    path = repo / "tools" / "pool" / "landing.py"
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    old = (
        "    for _rel in recount_derived(wt):\n"
        "        if _rel not in allow:\n"
        "            allow.append(_rel)\n"
        '        print(f"  ★ 重算改了它 ⇒ 随这一笔提交：{_rel}")\n'
    )
    assert text.count(old) == 1, "⑤′.5 的调用点变了 ⇒ 这条钉子得跟着改"
    path.write_bytes(text.replace(old, "    # 卡 E76 现场：⑤′.5 整段不存在。\n").encode("utf-8"))
    # ★ 删完必须**重算**：假仓的 README 是从 `tools/pool/*.py` 现算的，少了四行就当场
    #   过期，而新的前置腿会在开跑前把这一笔拦住（那是对的 —— 但它会挡住本用例）。
    made = _run_gen(repo)
    assert made.returncode == 0, _out(made)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "卡 E76 现场：⑤′.5 不见了")


# ---------------------------------------------------------------- 判据 1
def test_real_tree_derived_docs_are_consistent() -> None:
    """判据 1：真树里 README 与现算一致 —— 独立检查器也要绿（不只生成器自己说绿）。"""
    done = _run_checker(ROOT, "--check")
    out = (done.stdout or "") + (done.stderr or "")
    assert done.returncode == 0, out
    assert "[OK  ] " + README_REL + " 与现算一致" in out, out


# ---------------------------------------------------------------- 判据 2
def test_landing_leg_delegates_to_the_independent_checker() -> None:
    """判据 2：腿① **不许自己算**，也不许直跑生成器 —— 它只以子进程调独立检查器。"""
    src = (TOOLS / "pool" / "landing.py").read_text(encoding="utf-8")
    func = next(node for node in ast.parse(src).body
                if isinstance(node, ast.FunctionDef) and node.name == "recount_derived")
    body = ast.get_source_segment(src, func) or ""
    assert "DERIVED_CHECKER" in body, "腿① 不再调独立检查器"
    assert "POOL_README_GEN], cwd=wt" not in body, "腿① 又改回直跑生成器（卡 E76 的病）"

    checker = (ROOT / CHECKER_REL).read_text(encoding="utf-8")
    # 不许变成第二份判据：现算口径（数行 / 读台账 / 渲染 / 差异）一份都不许长在这里
    for token in ("def count_lines", "def scan_pool", "def backlog_metrics",
                  "def render_block", "DIFF_LIMIT"):
        assert token not in checker, f"检查器里长出了第二份现算口径：{token}"
    # 必须是**子进程**跑生成器（跑磁盘上的当前代码），不是 import 之后调函数
    assert "subprocess.run(" in checker, "检查器不再以子进程跑生成器"
    assert "import gen_pool_readme" not in checker, "检查器 import 了生成器（那就又回到 E76 的病）"


# ---------------------------------------------------------------- 判据 3
def test_shell_leg_runs_even_when_the_landing_leg_succeeded(tmp_path: Path) -> None:
    """判据 3：腿① 绿了腿② 也照样跑 —— 输出里要能看到**腿② 自己那行**。

    ★ 区分度：腿① 的写模式**不复核成功时**（只在复核失败时才 echo），所以
      `[OK  ] … 与现算一致` 那一行只可能来自腿② 的 `--check`。
    """
    repo = _mk_repo(tmp_path)
    _write(repo, "code/a.py", "X = 2\n")

    done = _wand(repo, "--no-gate", "--no-review")
    out = _out(done)

    assert done.returncode == 0, out
    tail = out.split("  提交：")[-1]
    assert "[OK  ] " + README_REL + " 与现算一致" in tail, tail


# ---------------------------------------------------------------- 判据 4
def test_shell_leg_catches_what_the_landing_leg_missed(tmp_path: Path) -> None:
    """判据 4（**E76 现场复现**）：腿① 哑掉时，`--commit-only` 上腿② 必须响亮失败并就地修回。

    坏掉的写法（本卡开工前就是这样）：仓里没有第二条腿 ⇒ 这笔提交带着过期一行的 README
    落地，退出码还是 0，下一趟门禁才红。
    """
    repo = _mk_repo(tmp_path)
    _drop_landing_leg(repo)
    _write(repo, "code/a.py", "X = 2\n")

    done = _wand(repo, "--no-gate", "--commit-only", "--no-reset", "--no-review")
    out = _out(done)

    assert "①~⑤ 跳过" in out, out                        # 确认真走的是这条路
    assert "[队列] 卡 T-G999：pending → done" in out, out
    assert "★ 重算改了它" not in out, out                 # 腿① 真的哑了（这就是 E76）
    assert done.returncode == 4, out                     # 腿② 抓住 ⇒ 这一轮不算数
    assert "派生文档检查失败（腿②/壳层）" in out, out
    assert "✓ 已就地把它修回一致" in out, out
    # 提交里是错的（E76 那一笔），工作区里已经被腿② 修回一致（重落一条命令即可）
    assert STALE_LINE in _head_text(repo, README_REL)
    assert FRESH_LINE in (repo / README_REL).read_text(encoding="utf-8")
    assert _run_gen(repo, "--check").returncode == 0


# ---------------------------------------------------------------- 判据 3 的另一半
def test_shell_leg_is_quiet_when_the_tree_has_no_derived_docs(tmp_path: Path) -> None:
    """假仓容忍（E76 踩过）：两样都不在 ⇒ 安静跳过；**只缺生成器** ⇒ 响亮停手。

    E76 第一版没容忍「两样都不在」，让 `tests/test_wb_land.py` 的 86 条落地钉子全红。
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    quiet = subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / CHECKER_REL), "--check", "--root", str(empty)],
        cwd=str(ROOT), env=_ENV, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False, creationflags=_NO_WINDOW,
    )
    quiet_out = (quiet.stdout or "") + (quiet.stderr or "")
    assert quiet.returncode == 0, quiet_out
    assert "既没有" in quiet_out and "跳过" in quiet_out, quiet_out

    # 只缺生成器 ⇒ 证明不了 ⇒ 不许静默跳过（卡规格：重算失败不许静默）
    half = tmp_path / "half"
    (half / "docs" / "subsystems" / "pool").mkdir(parents=True)
    (half / README_REL).write_text("x\n", encoding="utf-8")
    loud = subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / CHECKER_REL), "--check", "--root", str(half)],
        cwd=str(ROOT), env=_ENV, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False, creationflags=_NO_WINDOW,
    )
    loud_out = (loud.stdout or "") + (loud.stderr or "")
    assert loud.returncode == 2, loud_out
    assert "停手" in loud_out, loud_out


# ---------------------------------------------------------------- 判据 5
def test_the_old_pins_and_the_generator_are_not_weakened() -> None:
    """判据 5：既有判据一条都不许削弱 —— 生成器的现算口径与那两条钉子必须原样在。"""
    gen = (ROOT / GEN_REL).read_text(encoding="utf-8")
    for token in ("def count_lines", "def scan_pool", "def backlog_metrics",
                  "def render_block", "DIFF_LIMIT = 8", "与现算一致",
                  "与现算不一致", "没有可写的区域"):
        assert token in gen, f"生成器的现算口径被动了：{token}"
    pins = (ROOT / "tests" / "test_pool_readme_counts.py").read_text(encoding="utf-8")
    for name in ("test_real_readme_matches_recount", "test_hand_edited_count_reports_line"):
        assert name in pins, f"既有钉子被删了：{name}"



# ---------------------------------------------------------------- 前置腿（卡 E77）
def test_pre_leg_refuses_to_start_on_a_dirty_tree(tmp_path: Path) -> None:
    r"""★ 卡 E77：前置腿 —— 树上已经不一致 ⇒ **拒绝开跑**（退 3），一步都不动、也不写盘。

    这是「别在脏树上开跑」那一条：E76 的脏（提交后才发现过期）会拦在**下一笔**开跑时。
    ★ 坏掉写法：没有这条前置腿 ⇒ 本测试退 0 ⇒ 红。
    """
    repo = _mk_repo(tmp_path)
    readme = repo / README_REL
    dirty = readme.read_bytes().replace(
        STALE_LINE.encode("utf-8"), "99 张（0 done / 99 pending）".encode())
    assert dirty != readme.read_bytes(), "夹具没改到那一行"
    readme.write_bytes(dirty)
    _git(repo, "add", "--", README_REL)
    _git(repo, "commit", "-q", "-m", "手改成过期")
    head_before = _git(repo, "rev-parse", "HEAD").stdout.strip()

    done = _wand(repo, "--no-gate", "--no-review")
    out = _out(done)

    assert done.returncode == 3, out
    assert "落地链开跑前" in out
    assert "先修好再落" in out
    assert "python -X utf8 scripts/check_derived_docs.py" in out
    assert "[队列] 卡 T-G999：pending → done" not in out
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == head_before, "前置腿红了还往前走了"
    assert readme.read_bytes() == dirty, "★ 前置腿写盘了 —— 它必须只读"


# ================================================================ 卡 E78：第二个面
#
# 病：落地链每笔都会 ⑤′ 自动补 `docs/changelog.d/{task}.md`、② 重写 `docs/changelog.md`，
# 而 `docs/INDEX.md` 是 `docs/**` 的**投影**（按目录数篇数 + 算总字数）⇒ 每落一张卡它也
# 过期一次。修法与 E76/E77 同一个：复用**三条腿**（前置腿只读 / 腿① ⑤′.5 写盘 / 腿② 壳层
# 写盘），判决权只在 `scripts/gen_doc_index.py`，`scripts/check_derived_docs.py` 只管调它。
#
# 五条判据各至少一枚钉子：
#   1. 落地链必须重算 `docs/INDEX.md`           → test_landing_recomputes_the_derived_index
#                                                 test_recount_leaves_the_index_quiet_when_unchanged
#   2. checker 扩成多目标、仍不含现算口径        → test_checker_declares_both_targets
#                                                 test_checker_still_has_no_recount_logic
#   3. `gen_doc_index.py --check` 仍逐行点名     → test_index_check_still_names_the_line
#   3b. 只缺 INDEX 生成器也要响亮停手
#       → test_checker_is_loud_when_only_the_index_gen_is_missing
#   4. `--commit-only` 那条路也被覆盖
#       → test_commit_only_path_also_recomputes_the_index
#   5. 生成器与既有钉子一字节不动
#       → test_index_generator_and_its_pins_are_not_weakened


# ---------------------------------------------------------------- 判据 1
def test_landing_recomputes_the_derived_index(tmp_path: Path) -> None:
    r"""判据 1：翻账 + 自动补片段之后，`docs/INDEX.md` 必须**真写盘**并随这一笔提交。

    ★ 坏掉的写法（本卡开工前就是这样）：`RECOUNT_DOCS` 只有 README 一项 ⇒ 这一笔把
      `docs/changelog.d/T-G999.md` 带进库，而 INDEX 的篇数表还是旧的 ⇒ 每落一张卡过期一次。
    """
    repo = _mk_repo(tmp_path)
    assert _run_index_gen(repo, "--check").returncode == 0, "前提：夹具里 INDEX 自洽"
    before = (repo / INDEX_REL).read_text(encoding="utf-8")
    assert "docs/changelog.d/T-G999.md" not in before, "前提：落地前片段还不存在"
    _write(repo, "code/a.py", "X = 2\n")

    done = _wand(repo, "--no-gate", "--no-review")
    out = _out(done)

    assert done.returncode == 0, out
    assert "[队列] 卡 T-G999：pending → done" in out, out
    # 落地链自己把 INDEX 补进了这一笔（`★ 重算改了它 ⇒ 随这一笔提交：`）
    assert "★ 重算改了它 ⇒ 随这一笔提交：" + INDEX_REL in out, out
    assert INDEX_REL in _head_files(repo), _head_files(repo)
    # 提交里那份 INDEX 已经**看见**这一笔新增的片段（这才是「重算」的证据）
    assert "docs/changelog.d/T-G999.md" in _head_text(repo, INDEX_REL)
    # 交完之后假仓库自己也是自洽的
    assert _run_index_gen(repo, "--check").returncode == 0


def test_recount_leaves_the_index_quiet_when_unchanged(tmp_path: Path) -> None:
    """判据 1 的另一半：`docs/` 真的没变时 INDEX **不许被拖进这一笔**（不制造空改动）。

    ★ 为什么用 `--commit-only` 造这个现场：这条路的 ①~⑤ 全跳过 ⇒ 不会自动补
      `docs/changelog.d/{task}.md`（那是 ② 的产物）⇒ 整棵树里 `docs/` 一字节不变。
      普通单卡落地永远会补片段，所以造不出「docs 不变」的现场。
    """
    repo = _mk_repo(tmp_path)
    _write(repo, "code/a.py", "X = 2\n")
    before = (repo / INDEX_REL).read_bytes()

    done = _wand(repo, "--no-gate", "--commit-only", "--no-reset", "--no-review")
    out = _out(done)

    assert done.returncode == 0, out
    assert "①~⑤ 跳过" in out, out
    # 检查器照旧点名 INDEX（腿② 仍在看第二个面）……
    assert "[OK  ] " + INDEX_REL + "（" in out, out
    # ……但 INDEX 没进这一笔（`recount_derived` 只收**真被改**的）
    assert INDEX_REL not in _head_files(repo), _head_files(repo)
    assert (repo / INDEX_REL).read_bytes() == before, "INDEX 被无谓改写了"


# ---------------------------------------------------------------- 判据 2
def test_checker_declares_both_targets() -> None:
    """判据 2：检查器的目标表必须**同时**声明两个面（README + INDEX），各带自己的生成器。

    ★ 这条是「删掉 INDEX 那一支」的钉子：目标表里少了 INDEX ⇒ 判据 1 的三条腿一起哑掉。
    """
    src = (ROOT / CHECKER_REL).read_text(encoding="utf-8")
    tree = ast.parse(src)
    targets = next(
        node for node in tree.body
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "TARGETS"
    )
    pairs: list[tuple[str, str]] = []
    for call in targets.value.elts:                          # type: ignore[union-attr]
        got = {
            kw.arg: kw.value.value                             # type: ignore[attr-defined]
            for kw in call.keywords
            if isinstance(kw.value, ast.Constant)             # `gen_args` 是 Tuple，跳过
        }
        pairs.append((got.get("doc", ""), got.get("gen", "")))
    assert (README_REL, GEN_REL) in pairs, pairs
    assert (INDEX_REL, INDEX_GEN_REL) in pairs, pairs
    # INDEX 必须限定 `--target docs`：`复盘/INDEX.md` 归 `scripts/retro/retro_index.py`，不接管
    index_call = next(
        call for call in targets.value.elts                     # type: ignore[union-attr]
        if any(kw.arg == "doc" and kw.value.value == INDEX_REL for kw in call.keywords)
    )
    args = next(
        kw.value for kw in index_call.keywords if kw.arg == "gen_args"
    )
    assert [e.value for e in args.elts] == ["--target", "docs"], ast.dump(args)


def test_checker_still_has_no_recount_logic() -> None:
    """判据 2：检查器**仍不含任何现算口径** —— 数行数、扫目录、数篇数、渲染都不许长在这里。"""
    checker = (ROOT / CHECKER_REL).read_text(encoding="utf-8")
    for token in ("rglob", "render_docs", "def count", "collect(",
                  "import gen_pool_readme", "import gen_doc_index",
                  "def scan_pool", "def backlog_metrics", "def render_block", "DIFF_LIMIT"):
        assert token not in checker, f"检查器里长出了第二份现算口径：{token}"
    assert "subprocess.run(" in checker, "检查器不再以子进程跑生成器"


# ---------------------------------------------------------------- 判据 3
def test_index_check_still_names_the_line(tmp_path: Path) -> None:
    """判据 3：`gen_doc_index.py --check` 遇过期仍退非零并**逐行点名**（本卡不许削弱它）。"""
    repo = _mk_repo(tmp_path)
    assert _run_index_gen(repo, "--check").returncode == 0, "前提：自洽"

    raw = (repo / INDEX_REL).read_bytes().decode("utf-8")
    lines = raw.replace("\r\n", "\n").split("\n")
    target = next(i for i, line in enumerate(lines) if "docs/changelog.md" in line)
    lines[target] = "- `docs/不该存在.md`"
    (repo / INDEX_REL).write_bytes("\n".join(lines).replace("\n", "\r\n").encode("utf-8"))

    done = _run_index_gen(repo, "--check")

    assert done.returncode == 1, done.stdout
    assert f"第 {target + 1} 行" in done.stdout, done.stdout
    assert "docs/不该存在.md" in done.stdout, done.stdout


def test_checker_is_loud_when_only_the_index_gen_is_missing(tmp_path: Path) -> None:
    """判据 3：**只缺 INDEX 的生成器**也要响亮停手（退 2），不许静默跳过。"""
    half = tmp_path / "half"
    (half / "docs").mkdir(parents=True)
    (half / INDEX_REL).write_text("x\n", encoding="utf-8")
    loud = subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / CHECKER_REL), "--check", "--root", str(half)],
        cwd=str(ROOT), env=_ENV, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False, creationflags=_NO_WINDOW,
    )
    loud_out = (loud.stdout or "") + (loud.stderr or "")

    assert loud.returncode == 2, loud_out
    assert INDEX_REL in loud_out and "停手" in loud_out, loud_out


# ---------------------------------------------------------------- 判据 4
def test_commit_only_path_also_covers_the_index(tmp_path: Path) -> None:
    r"""判据 4：`--commit-only` 那条路**同样**被覆盖 —— 两半都测，不许静默。

    ★ 为什么两半都得测：这条路 ①~⑤ 全跳过 ⇒ 不会自动补 `docs/changelog.d/{task}.md`，
      也不会重写 `docs/changelog.md`。所以 `docs/` 在**这条路自己手里**永远不变，
      「重算写盘」那一半造不出正面现场。可达的现实只有两种，两种都钉：
        ① 树是干净的 ⇒ 检查器**照样点名 INDEX**（证明这道腿没被这条路绕开，且不制造空改动）；
        ② 树已经过期 ⇒ **响亮停手**（rc=3、点名、一个字节都不提交）——
           卡里写的「或 loud failure，不许静默」就是这一半。
      ★ 顺带钉住一件真会踩的事：过期的 INDEX 若能被 `--commit-only` 静默带过，
        那它就是又一条「落地即过期」的路。
    """
    # ---- ① 干净树：这条路照旧把两个面都过一遍（安静，且不制造空改动）
    (tmp_path / "clean").mkdir()
    clean = _mk_repo(tmp_path / "clean")
    assert _run_index_gen(clean, "--check").returncode == 0, "前提：夹具里 INDEX 自洽"
    _write(clean, "code/a.py", "X = 2\n")
    before = (clean / INDEX_REL).read_bytes()

    ok = _wand(clean, "--no-gate", "--commit-only", "--no-reset", "--no-review")
    ok_out = _out(ok)

    assert ok.returncode == 0, ok_out
    assert "①~⑤ 跳过" in ok_out, ok_out                      # 确认真走的是这条路
    assert "[OK  ] " + INDEX_REL + "（" in ok_out, ok_out     # 这条路也看了第二个面
    assert (clean / INDEX_REL).read_bytes() == before, "INDEX 被无谓改写了"

    # ---- ② 过期树：这条路必须响亮停手（rc=3），不许把过期悄悄带进提交
    (tmp_path / "stale").mkdir()
    stale = _mk_repo(tmp_path / "stale")
    _write(stale, "code/a.py", "X = 2\n")
    # 新增一篇笔记 ⇒ INDEX 的篇数表过期（不重算：模拟「有人手改文档又忘了重算」）
    _write(stale, "docs/extra_note.md", "# 忘了重算的一篇\n")
    head_before = _git(stale, "rev-parse", "HEAD").stdout.strip()

    # 先拿检查器的**完整**输出（`_run_step` 只留末尾 8 行，`[FAIL]` 那行会被截掉，
    # 所以「点名了哪个面」要直接问检查器，别从腿的尾巴里猜）。
    seen = _run_checker(stale, "--check")
    assert seen.returncode == 1, _out(seen)
    assert "[FAIL] " + INDEX_REL in seen.stdout, _out(seen)   # 点名的是第二个面
    assert "[OK  ] " + README_REL in seen.stdout, _out(seen)  # 第一个面本来是好的

    refused = _wand(stale, "--no-gate", "--commit-only", "--no-reset", "--no-review")
    bad_out = _out(refused)

    assert refused.returncode == 3, bad_out
    assert "落地链开跑前" in bad_out, bad_out
    assert _git(stale, "rev-parse", "HEAD").stdout.strip() == head_before, "过期的树竟被提交了"


# ---------------------------------------------------------------- 判据 5
def test_index_generator_and_its_pins_are_not_weakened() -> None:
    """判据 5：`scripts/gen_doc_index.py` 的现算口径与既有钉子一条都不许削弱。"""
    gen = (ROOT / INDEX_GEN_REL).read_text(encoding="utf-8")
    for token in ("def collect(", "rglob", "def render_docs", "def check_target",
                  "def write_target", "第 {index + 1} 行", "[OK  ]", "[FAIL]",
                  "--target"):
        assert token in gen, f"索引生成器的现算口径被动了：{token}"
    pins = (ROOT / "tests" / "test_gen_doc_index_fresh.py").read_text(encoding="utf-8")
    for name in ("test_the_real_index_matches_the_real_tree",
                 "test_hand_edit_is_red_and_names_the_line"):
        assert name in pins, f"既有钉子被删了：{name}"


# ---------------------------------------------------------------- 三条腿都覆盖 INDEX
def test_every_leg_checks_the_index(tmp_path: Path) -> None:
    """三条腿都要点名 INDEX：前置腿/腿② 走真树 `--check`，腿① 由上面判据 1 的 e2e 覆盖。"""
    real = _run_checker(ROOT, "--check")
    real_out = (real.stdout or "") + (real.stderr or "")
    assert real.returncode == 0, real_out
    assert "[OK  ] " + INDEX_REL + "（" in real_out, real_out

    repo = _mk_repo(tmp_path)
    _write(repo, "code/a.py", "X = 2\n")
    _drop_landing_leg(repo)
    stale = _wand(repo, "--no-gate", "--commit-only", "--no-reset", "--no-review")
    out = _out(stale)
    assert stale.returncode == 4, out
    assert INDEX_REL in out, out                            # 腿② 的不一致里点了 INDEX 的名
