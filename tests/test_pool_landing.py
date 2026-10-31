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


def _mk_repo(tmp_path: Path) -> Path:
    """造一个「够收口链走到 ⑥」且**现算文档自洽**的假仓库。

    与 `tests/test_wb_land.py::_mk_repo` 同体例，只多铺三样（本卡的被测面）：
    `scripts/gen_pool_readme.py`（**真件**）、`docs/subsystems/pool/modules.toml`（按实际文件
    生成）、`docs/subsystems/pool/README.md`（夹具末尾由真生成器写成自洽态）。
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
    _write(repo, MODULES_REL, _manifest_for(repo), crlf=True)
    _write(repo, README_REL, _README_TEMPLATE, crlf=True)
    _write(repo, BACKLOG_REL, _BACKLOG, crlf=True)
    # 夹具末尾真跑一次生成器 ⇒ README 与台账**自洽**（落地前 `--check` 必须是绿的）
    made = _run_gen(repo)
    assert made.returncode == 0, made.stdout + made.stderr
    assert STALE_LINE in (repo / README_REL).read_text(encoding="utf-8")
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
    assert "★ 重算改了它" not in out, out
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
