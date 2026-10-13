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

import datetime
import importlib.util
import json
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
#: ★ 卡 184：加 `tools/pool/review.py` —— landing.py 的 _touched_paths / _touched_judge_body
#:   会 `from pool.review import changed_paths / outside_allow`，假仓库里没有它就 ImportError。
_NEW_TOOLS = (
    "tools/wb_land.py",
    "tools/pool/__init__.py",
    "tools/pool/landing.py",
    "tools/pool/review.py",
    "tools/wb_stage_card.py",
    "tools/pool/stage_card.py",
    # ★ 卡 193（T-G293）：`stage_card._selfcheck` 起要 `import card_doc_budget`
    #   ⇒ 沙箱少这一份，脚本**一 import 就崩**（当晚实测）⇒ 清单必须跟着真依赖走。
    "tools/card_doc_budget.py",
    # ★ 卡 192（T-G292）：`landing.py` 起要 `import pool.snapshot` ⇒ 沙箱少一份就崩。
    "tools/pool/snapshot.py",
    # ★ 卡 212（T-G323）：`landing.py` 的 _warn_if_card_in_batch / _advance_*_gate
    #   会 `from pool.task import ...` ⇒ 沙箱少 task.py / plan.py / projects.py 就崩。
    "tools/pool/task.py",
    "tools/pool/plan.py",
    "tools/pool/projects.py",
    "tools/wb_task.py",
)

_TEXT = """=== gaps ===
**边界**：合成卡，仅供钉子用，不作数（指针 `code/a.py`）。
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

#: ★ 卡 184 钉子用的「增量门禁」桩（比 _RUN_GATES 多三件事）：
#:   ① 记下 argv（断言 --affected 有没有传到 run_gates 这一层）；
#:   ② 写一份真模样的 gates/last.json —— 跑过 --affected ⇒ 加 affected 块（卡 147 护栏读的就是它）；
#:   ③ 提供 build_jobs / plan_affected 让 landing.py 的 _affected_plan 能 import（不 exit）。
#:   ★ plan_affected 的匹配口径（够测试用，不复制 run_gates 的正则）：
#:     pat='code/**' ⇒ path 以 'code/' 开头算命中；其它不命中。
#:     「code/」命中 ⇒ 跑 pytest 一道；其它路径 ⇒ full_fallback（空计划）。
_RUN_GATES_AFFECTED = '''import json, pathlib, sys

DOOR_INPUTS = {"pytest": ("code/**",), "ruff": ("src/**",), "render": ("src/web/**",)}


class AffectedPlan:
    def __init__(self, ran, matched, skipped, full_fallback, note, inputs=()):
        self.ran = tuple(ran)
        self.matched = tuple(matched)
        self.skipped = tuple(skipped)
        self.full_fallback = full_fallback
        self.note = note
        self.inputs = tuple(inputs)

    def to_payload(self):
        return {"ran": list(self.ran), "matched": list(self.matched),
                "skipped": [{"name": n, "why": w} for n, w in self.skipped],
                "full_fallback": self.full_fallback, "note": self.note,
                "inputs": list(self.inputs)}


def build_jobs(quick, fast):
    return [("pytest", []), ("ruff", []), ("render", [])]


def _norm(p):
    p = p.strip()
    while p.startswith("./"):
        p = p[2:]
    return p.rstrip("/")


def _match(path, pat):
    prefix = pat.rstrip("/*")
    n = _norm(path)
    return n == prefix or n.startswith(prefix + "/")


def plan_affected(paths, doors, door_inputs=None):
    norm = [p for p in (_norm(p) for p in paths) if p]
    always = [d for d in doors if d not in DOOR_INPUTS]
    matched = [d for d in doors if DOOR_INPUTS.get(d) and
               any(_match(p, pat) for p in norm for pat in DOOR_INPUTS[d])]
    if not matched:
        note = "no match -> full" if norm else "empty -> full"
        return AffectedPlan(doors, (), (), True, note, norm)
    keep = set(always) | set(matched)
    ran = [d for d in doors if d in keep]
    skipped = [(d, "no match") for d in doors if d not in keep]
    return AffectedPlan(ran, matched, skipped, False, "matched " + str(matched), norm)


def _main():
    args = sys.argv[1:]
    pathlib.Path("gate_ran.marker").write_text("ran", encoding="utf-8")
    # ★ 追加（不覆盖）：④ 门禁 + ⑤ seal 都会调本桩，覆盖了就只剩 ⑤ 的 --seal
    with pathlib.Path("gate_args.txt").open("a", encoding="utf-8") as fh:
        fh.write(" ".join(args) + "\\n")
    last_path = pathlib.Path("gates") / "last.json"
    last_path.parent.mkdir(exist_ok=True)
    # ★ --seal：真 run_gates 只改 tree/tree_scope/untracked，保留其它字段（含 affected 块）。
    #   桩照这个口径 —— 读旧 last.json + 改 tree，不覆盖 ④ 写的 affected 块。
    if "--seal" in args:
        payload = {}
        if last_path.exists():
            try:
                payload = json.loads(last_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
        payload["tree"] = "stub-tree"
        payload["tree_scope"] = "worktree-minus-gates"
        last_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print("stub-run_gates-seal")
        sys.exit(0)
    doors = [n for n, _ in build_jobs(False, False)]
    aff = None
    ran_doors = list(doors)
    if "--affected" in args:
        idx = args.index("--affected")
        aff = plan_affected(args[idx + 1:], doors)
        ran_doors = list(aff.ran)
    elif "--changed-from" in args:
        idx = args.index("--changed-from")
        aff = plan_affected([args[idx + 1]], doors)
        ran_doors = list(aff.ran)
    gates = [{"name": d, "exit_code": 0} for d in ran_doors]
    payload = {"ok": True, "rev": "", "gates": gates,
               "tree_scope": "worktree-minus-gates"}
    if aff is not None:
        payload["affected"] = aff.to_payload()
    last_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("stub-run_gates-affected")
    sys.exit(0)


if __name__ == "__main__":
    _main()
'''

#: ★ 卡 184 ⑧ 复核桩：输出一份「复核通过」的 JSON（让 landing.py 落盘 gates/review/<task>.json）。
#:   ★ 不真跑 wb_review（那会 import scripts/run_gates）；这里只测「收口链有没有把结论落盘」。
_WB_REVIEW = """import json, sys
print(json.dumps({"rev": "HEAD", "problems": []}, ensure_ascii=False, indent=2))
sys.exit(0)
"""

#: ★ 卡 198 ①钉子桩：把收到的 argv 原样记到 `review_args.txt`（假仓库根 = ⑧ 的 cwd），
#:   证明 `--allow` 真传到了、且就是收口链那一份；随后输出「复核通过」JSON。
_WB_REVIEW_ARGS = """import json, pathlib, sys
pathlib.Path("review_args.txt").write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
print(json.dumps({"rev": "HEAD", "problems": []}, ensure_ascii=False, indent=2))
sys.exit(0)
"""

#: ★ 卡 198 ②钉子桩：明明收到了 `--allow` 却**仍**报「没有给白名单」—— 复核侧为什么
#:   还报不归本卡管（`wb_review.py` 是别的域），但收口链必须把它当成问题喊出来。
_WB_REVIEW_STUBBORN = """import json, sys
print(json.dumps({"rev": "HEAD", "problems": [
    "没有给白名单：复核改动范围请加 `--allow <glob>`（或声明 `--read-only`）"]},
    ensure_ascii=False, indent=2))
sys.exit(1)
"""

#: ★ 卡 198 ③钉子桩：复核报一条**真问题**（白名单外有改动）—— 传 `--allow` 不许顺手
#:   把真问题也压掉；problems 必须照旧 != 0。
_WB_REVIEW_REAL = """import json, sys
print(json.dumps({"rev": "HEAD", "problems": [
    "有 1 个改动不在白名单里：['code/rogue.py']"]}, ensure_ascii=False, indent=2))
sys.exit(1)
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
             stage_card_body: str | None = None, run_gates_body: str | None = None,
             wb_review_body: str | None = None) -> Path:
    """造一个「够收口链走到 ⑥」的最小假仓库：共享文档 + 桩 + 新工具 + 文书模板。

    `sync_docs_body` / `stage_card_body`：给真桩换**行为桩**（卡 150 的幂等钉子用）——
    在 `_stage_tools` 拷完真工具**之后**覆写，只影响用到它们的测试。
    `run_gates_body` / `wb_review_body`（卡 184）：换门禁桩 / 复核桩 —— 在初始提交里就位，
    免得 stub swap 本身变成卡树改动（会撞 ②.1 判据本体 ⇒ 强制全量）。
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
    _write(repo, "scripts/run_gates.py", run_gates_body or _RUN_GATES)
    if wb_review_body is not None:
        _write(repo, "tools/wb_review.py", wb_review_body)
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
    repo: Path, *extra: str, allow: tuple[str, ...] = ("code",), tree: str = ".",
    card: str = "T-G999", task: str = "T-G999"
) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-X", "utf8", str(repo / "tools" / "wb_land.py"),
           "--card", card, "--tree", tree, "--task", task, "--title", "钉子",
           "--type", "feat", "--group", "ENGINEERING", "--evidence", "code/a.py",
           "--allow", *allow, *extra]
    return subprocess.run(cmd, cwd=str(repo), env=_ENV, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _mk_pen(repo: Path) -> Path:
    """给沙箱建一个**卡树**（worktree，`--tree .pen`）。

    ★ 卡 192（T-G292）起：`wb_land` 有「主干保护」——主树里出现白名单外的**跟踪文件**改动就退 5。
    这些钉子的场景本意是「**计划外暂存**发生在卡树里」（真流程就是 `.wt/<卡树>`）⇒ 只有把脏东西
    放进卡树，⑤/⑥ 才测得到、主树也才是干净的（否则守卫先咬，测的就不是原来那条路了）。
    """
    pen = repo / ".pen"
    subprocess.run(["git", "worktree", "add", "--detach", str(pen), "HEAD"],
                   cwd=str(repo), env=_ENV, capture_output=True, text=True, check=False,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return pen


def _out(done: subprocess.CompletedProcess) -> str:
    return (done.stdout or "") + (done.stderr or "")


# ================================================================ 卡 184 钉子用的辅助
def _write_daily_full(repo: Path, *, today: bool = True, date: str | None = None) -> Path:
    """写 `gates/diag/_daily_full.json`：today=True ⇒ 今天（让 landing.py 认「今天跑过」）；
    today=False ⇒ 给一个历史日期（让 landing.py 认「今天还没跑」）。"""
    d = date or (datetime.date.today().isoformat() if today else "2020-01-01")
    p = repo / "gates" / "diag" / "_daily_full.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"date": d, "rev": "stub0001", "time": "stub"},
                            ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


# ================================================================ ① --help
def test_help_lists_every_argument() -> None:
    """`--help` 要列出全部参数（少一个 = 旧调用点找不到入口）。"""
    done = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "wb_land.py"), "--help"],
                          env=_ENV, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    assert done.returncode == 0, _out(done)
    for flag in ("--card", "--batch", "--tree", "--task", "--title", "--type", "--scope",
                 "--group", "--evidence", "--allow", "--port-base", "--refs",
                 "--no-gate", "--commit-only", "--no-reset",
                 # ★ 卡 184：增量门禁开关 + ⑧ 复核跳过
                 "--affected", "--changed-from", "--no-review"):
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
    pen = _mk_pen(repo)   # ★ 192：脏东西落在卡树里（真流程如此）
    _write(pen, "rogue.txt", "偷渡\n")
    _git(pen, "add", "--", "rogue.txt")               # 先偷偷 stage 一个白名单外的

    done = _wand(repo, "--no-gate", tree=".pen")

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
    pen = _mk_pen(repo)   # ★ 192：脏东西落在卡树里（真流程如此）
    _make_rerun_dirt(pen)
    src = pen / "tools" / "wb_land.py"
    before = src.read_bytes() + "# 白名单源文件，不许被回退碰掉\n".encode()
    src.write_bytes(before)

    done = _wand(repo, "--no-gate", tree=".pen")

    out = _out(done)
    assert src.read_bytes() == before, "★ 回退动了白名单源文件！"
    st = _git(pen, "status", "--porcelain", "--", "tools/wb_land.py").stdout
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
    pen = _mk_pen(repo)   # ★ 192：脏东西落在卡树里（真流程如此）
    _write(pen, "rogue.txt", "偷渡\n")
    _git(pen, "add", "--", "rogue.txt")

    first = _wand(repo, "--no-gate", tree=".pen")
    assert first.returncode == 2, _out(first)             # ⑥ 计划外 ⇒ 停（残留下派生物）
    ledger = (pen / "docs" / "traceability.toml").read_bytes()
    assert b'[entries."T-G999"]' in ledger, "第一趟应当残留下脏台账"

    second = _wand(repo, "--no-gate", tree=".pen")

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


# ================================================================ 卡 184（T-G284）增量门禁
# ★ 四条反例钉子（卡 §三条硬要求 ②）：① 空计划 ⇒ 真退全量；② 增量那一趟 trailer 含「非全量」；
#   ③ 碰 tools/** ⇒ 强制全量；④ 卡 147 护栏仍咬（增量产物有 affected 块）。
#   另加：每日全量兜底、⑧ 复核落盘、全量后落盘每日记录。


# ----------------------------------------------- ⓭ --help 列新参数（已在 ① 里加了，这里单钉一遍）
def test_help_lists_incremental_flags() -> None:
    """`--affected` / `--changed-from` / `--no-review` 三个新参数都要在 `--help` 里。"""
    done = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "wb_land.py"), "--help"],
                          env=_ENV, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    assert done.returncode == 0, _out(done)
    for flag in ("--affected", "--changed-from", "--no-review"):
        assert flag in done.stdout, f"`--help` 少了卡 184 的新参数 {flag}"


# ----------------------------------------------- ⓱ --affected 透传（无强制条件）
def test_affected_passes_through_when_no_force_full(tmp_path: Path) -> None:
    """没碰判据本体 + 非空计划 + 今天已跑过全量 ⇒ `--affected` 透传给 run_gates.py。

    ★ 坏掉写法（不透传 / 把 --affected 吞了）：gate_args.txt 里没有 `--affected` ⇒ 钉子红。
    """
    repo = _mk_repo(tmp_path, run_gates_body=_RUN_GATES_AFFECTED,
                    wb_review_body=_WB_REVIEW)
    _write_daily_full(repo, today=True)
    _write(repo, "code/a.py", "X = 2\n")           # 卡树改动：只动 code/（非判据本体）

    done = _wand(repo, "--affected", "code/a.py")

    out = _out(done)
    assert done.returncode == 0, out
    args = (repo / "gate_args.txt").read_text(encoding="utf-8")
    assert "--affected" in args and "code/a.py" in args, \
        f"--affected 没透传到 run_gates：{args!r}"
    last = json.loads((repo / "gates/last.json").read_text(encoding="utf-8"))
    assert "affected" in last, "增量那一趟必须写 affected 块（卡 147 护栏读它）"
    assert "增量" in out and "非全量" not in out.split("=== ⑤")[0]  # 文书那行在 ⑥ 之后才出现


# ----------------------------------------------- ⓲ 碰 tools/** ⇒ 强制全量
def test_touching_tools_forces_full(tmp_path: Path) -> None:
    """卡树改动里有 `tools/**` 文件 ⇒ 强制全量（不传 --affected）。

    ★ 判据本体改了 = 碰 scripts/** / tools/** / gates/** 里任何文件（卡 184 §②.1）。
    ★ 坏掉写法（把 --affected 传过去）：gate_args.txt 里有 `--affected` ⇒ 钉子红。
    """
    repo = _mk_repo(tmp_path, run_gates_body=_RUN_GATES_AFFECTED,
                    wb_review_body=_WB_REVIEW)
    _write_daily_full(repo, today=True)
    _write(repo, "code/a.py", "X = 2\n")               # 卡树改动：code/（非判据本体）
    _write(repo, "tools/extra_notes.md", "notes\n")    # 卡树改动：tools/**（判据本体）

    done = _wand(repo, "--affected", "code/a.py",
                allow=("code", "tools/extra_notes.md"))

    out = _out(done)
    assert done.returncode == 0, out
    args = (repo / "gate_args.txt").read_text(encoding="utf-8")
    assert "--affected" not in args, \
        f"碰了 tools/** 就该强制全量（不传 --affected），却传了：{args!r}"
    assert "强制全量" in out and "判据本体" in out, \
        "stdout 应当点名「强制全量」+「判据本体」"
    last = json.loads((repo / "gates/last.json").read_text(encoding="utf-8"))
    assert "affected" not in last, "全量那一趟不许有 affected 块"


# ----------------------------------------------- ⓳ 空计划 ⇒ 强制全量
def test_empty_plan_forces_full(tmp_path: Path) -> None:
    """`--affected` 给的路径一条都命不中任何门 ⇒ 空计划 ⇒ 退全量（绝不许空集绿灯）。

    ★ 这是 `Silent Success` 那个「空集绿灯」的同族 —— 本仓已经栽过。
    ★ 坏掉写法（把 --affected 传过去跑空集）：gate_args.txt 里有 `--affected` ⇒ 钉子红。
    """
    repo = _mk_repo(tmp_path, run_gates_body=_RUN_GATES_AFFECTED,
                    wb_review_body=_WB_REVIEW)
    _write_daily_full(repo, today=True)
    _write(repo, "code/a.py", "X = 2\n")           # 卡树改动只在 code/
    # --affected 给一个不命中任何门的路径（stub 的门表只认 code/、src/、src/web/）
    _write(repo, "docs/foo.md", "doc\n")
    _git(repo, "add", "--", "docs/foo.md")

    done = _wand(repo, "--affected", "docs/foo.md", allow=("code", "docs/foo.md"))

    out = _out(done)
    assert done.returncode == 0, out
    args = (repo / "gate_args.txt").read_text(encoding="utf-8")
    assert "--affected" not in args, \
        f"空计划该退全量（不传 --affected），却传了：{args!r}"
    assert "空计划" in out or "强制全量" in out, "stdout 应当点名「空计划」或「强制全量」"


# ----------------------------------------------- ⓴ 今天没跑过全量 ⇒ 强制全量
def test_no_daily_full_forces_full(tmp_path: Path) -> None:
    """今天还没跑过全量（无每日记录 / 记录是昨天的）⇒ 强制全量（每日一次兜底）。

    ★ 「今天跑过全量没有」必须机器可判，不许靠人记（卡 184 §②.3）。
    ★ 坏掉写法（让 --affected 透传）：gate_args.txt 里有 `--affected` ⇒ 钉子红。
    """
    repo = _mk_repo(tmp_path, run_gates_body=_RUN_GATES_AFFECTED,
                    wb_review_body=_WB_REVIEW)
    _write_daily_full(repo, today=False)            # 历史日期 ⇒ 今天还没跑
    _write(repo, "code/a.py", "X = 2\n")

    done = _wand(repo, "--affected", "code/a.py")

    out = _out(done)
    assert done.returncode == 0, out
    args = (repo / "gate_args.txt").read_text(encoding="utf-8")
    assert "--affected" not in args, \
        f"今天没跑过全量就该强制全量，却传了 --affected：{args!r}"
    assert "每日一次兜底" in out or "强制全量" in out, "stdout 应当点名「每日一次兜底」"


# ----------------------------------------------- ⓵ 增量 trailer 含「非全量」
def test_incremental_trailer_says_not_full(tmp_path: Path) -> None:
    """增量那一趟的提交信息 trailer 必须含「非全量」字样（卡 184 §③ 如实披露）。

    ★ 复用卡 147 的判据与措辞（affected 块照写），不许另写一份「看起来像全量」的话。
    ★ 全量分支字面「全量门禁绿 + seal」一字不动（卡 133 的 6 个钉子钉着它）。
    ★ 坏掉写法（增量 trailer 写「全量门禁绿」）：会撞卡 133 钉子 + 这条钉子也红。
    """
    repo = _mk_repo(tmp_path, run_gates_body=_RUN_GATES_AFFECTED,
                    wb_review_body=_WB_REVIEW)
    _write_daily_full(repo, today=True)
    _write(repo, "code/a.py", "X = 2\n")

    done = _wand(repo, "--affected", "code/a.py")

    out = _out(done)
    assert done.returncode == 0, out
    msg = _git(repo, "log", "-1", "--format=%B").stdout
    assert "非全量" in msg, f"增量 trailer 必须含「非全量」：{msg!r}"
    assert "全量门禁绿 + seal" not in msg, \
        "增量 trailer 不许写「全量门禁绿 + seal」（那是全量分支的字面，卡 133 钉着）"


# ----------------------------------------------- ⓶ 全量那一趟落盘每日记录
def test_full_run_marks_daily_full(tmp_path: Path) -> None:
    """全量那一趟（没给 --affected）跑完 ⇒ 落盘 gates/diag/_daily_full.json（今天跑过了）。

    ★ 「今天跑过全量没有」必须机器可判 —— 落盘是机器判据，不是人记。
    ★ 坏掉写法（不落盘）：第二趟给 --affected 时 _today_full_done() 仍返回 False ⇒ 强制全量
      （下一趟该跑增量却跑了全量）。
    """
    repo = _mk_repo(tmp_path, run_gates_body=_RUN_GATES_AFFECTED,
                    wb_review_body=_WB_REVIEW)
    assert not (repo / "gates" / "diag" / "_daily_full.json").exists(), \
        "初始状态：不该有每日全量记录"
    _write(repo, "code/a.py", "X = 2\n")

    done = _wand(repo)                              # 不给 --affected ⇒ 全量

    out = _out(done)
    assert done.returncode == 0, out
    daily = repo / "gates" / "diag" / "_daily_full.json"
    assert daily.is_file(), "全量那一趟必须落盘每日记录"
    data = json.loads(daily.read_text(encoding="utf-8"))
    assert data.get("date") == datetime.date.today().isoformat(), \
        f"每日记录的 date 应当是今天：{data!r}"
    assert data.get("rev"), "每日记录的 rev 不该空"


# ----------------------------------------------- ⓷ ⑧ 复核落盘 gates/review/<task>.json
def test_review_step_writes_to_gates_review(tmp_path: Path) -> None:
    """⑧ 跑 wb_review.py --rev <新提交> --json ⇒ 落盘 gates/review/<task>.json（追加三）。

    ★ 口径照卡 143：「提交之后 · 异步 · 不挡提交」—— 复核失败不回滚已提交的那笔；
      但 wb_task.py landed 之前必须存在一条复核记录（机器判据）。
    ★ 坏掉写法（不落盘）：gates/review/<task>.json 不存在 ⇒ 钉子红。
    """
    repo = _mk_repo(tmp_path, run_gates_body=_RUN_GATES_AFFECTED,
                    wb_review_body=_WB_REVIEW)
    _write_daily_full(repo, today=True)
    _write(repo, "code/a.py", "X = 2\n")

    done = _wand(repo)                              # 全量那一趟（含 ⑧ 复核）

    out = _out(done)
    assert done.returncode == 0, out
    review = repo / "gates" / "review" / "T-G999.json"
    assert review.is_file(), f"⑧ 复核必须落盘：{review}"
    verdict = json.loads(review.read_text(encoding="utf-8"))
    assert "problems" in verdict, f"复核产物应当有 problems 字段：{verdict!r}"
    assert "复核落盘" in out, "stdout 应当点名「复核落盘」"


# ------------------- ⓷′ 卡 198：⑧ 复核必须带上收口链自己那份 --allow（三条钉子）
def test_review_cmd_gets_landing_allow(tmp_path: Path) -> None:
    """① 卡 198：⑧ 调复核的命令行确实带 `--allow`，且与收口链那份**同一次运行一致**。

    ★ 坏掉写法 A（不传）：复核 argv 里没有 `--allow` ⇒ 每笔报「没有给白名单」。
    ★ 坏掉写法 B（另造一份 / 传展开后的提交白名单）：收到的与 wb_land 收到的不一致。
    ★ 坏掉写法 C（改成 --read-only 消红字）：有 `--read-only` 没有 `--allow`。
    """
    repo = _mk_repo(tmp_path, run_gates_body=_RUN_GATES_AFFECTED,
                    wb_review_body=_WB_REVIEW_ARGS)
    _write_daily_full(repo, today=True)
    _write(repo, "code/a.py", "X = 2\n")

    done = _wand(repo, allow=("code", "README.md"))

    out = _out(done)
    assert done.returncode == 0, out
    args = json.loads((repo / "review_args.txt").read_text(encoding="utf-8"))
    assert "--allow" in args, f"⑧ 复核命令行必须带 --allow：{args!r}"
    assert "--read-only" not in args, f"不许改成 --read-only 消红字：{args!r}"
    vals = [a for i, a in enumerate(args) if i and args[i - 1] == "--allow"]
    assert vals == ["code", "README.md"], \
        f"复核收到的 --allow 必须就是收口链那一份（不许另造）：{args!r}"
    assert "--rev" in args, f"--rev 原有行为不动：{args!r}"
    cmd_line = [ln for ln in out.splitlines() if "复核命令" in ln]
    assert cmd_line and "--allow" in cmd_line[0], \
        f"⑧ 打印的复核命令行原文必须看得见 --allow：{out!r}"


def test_review_whitelist_complaint_is_not_silenced(tmp_path: Path) -> None:
    """② 卡 198：复核**仍**报「没有给白名单」⇒ 必须当成问题（不许静默）。

    ★ 坏掉写法：landing 特判这条消息把它吞掉（problems 记 0 / 不喊 ★ 行）⇒ 红。
    """
    repo = _mk_repo(tmp_path, run_gates_body=_RUN_GATES_AFFECTED,
                    wb_review_body=_WB_REVIEW_STUBBORN)
    _write_daily_full(repo, today=True)
    _write(repo, "code/a.py", "X = 2\n")

    done = _wand(repo)

    out = _out(done)
    assert done.returncode == 0, out      # 异步、不挡提交
    assert "复核有问题" in out, "复核仍报「没有给白名单」必须当成问题喊出来"
    assert "problems=1" in out, out
    verdict = json.loads((repo / "gates/review/T-G999.json").read_text(
        encoding="utf-8"))
    assert any("没有给白名单" in p for p in verdict["problems"]), \
        f"那条消息不许在落盘前被滤掉：{verdict!r}"


def test_review_real_problems_still_count(tmp_path: Path) -> None:
    """③ 卡 198：复核的**真问题**照旧让 problems != 0（别顺手压掉）。

    ★ 坏掉写法：为了让红字消失而把复核结论吞掉 / 强行记 0 ⇒ 红。
    """
    repo = _mk_repo(tmp_path, run_gates_body=_RUN_GATES_AFFECTED,
                    wb_review_body=_WB_REVIEW_REAL)
    _write_daily_full(repo, today=True)
    _write(repo, "code/a.py", "X = 2\n")

    done = _wand(repo)

    out = _out(done)
    assert done.returncode == 0, out      # 异步、不挡提交
    assert "复核有问题" in out, "复核的真问题必须当成问题喊出来"
    assert "problems=1" in out, out
    verdict = json.loads((repo / "gates/review/T-G999.json").read_text(
        encoding="utf-8"))
    assert any("rogue.py" in p for p in verdict["problems"]), \
        f"真问题不许在落盘前被滤掉：{verdict!r}"


# ----------------------------------------------- ⓸ 增量产物有 affected 块（卡 147 护栏可读）
def test_incremental_writes_affected_block_for_card147_fence(tmp_path: Path) -> None:
    """增量那一趟的 gates/last.json 必须有 affected 块 —— 卡 147 护栏读的就是它。

    ★ 卡 147 的 `wb_review._affected_marks_partial_run`：last.json 有 affected 块 ⇒ 判红
      （把增量产物当全量交 ⇒ 红）。本卡**不动**这个护栏，只确保 landing.py 不许静默吞掉它。
    ★ 坏掉写法（landing.py 把 affected 块吞了）：卡 147 护栏咬不住 ⇒ 这条钉子红。
    """
    repo = _mk_repo(tmp_path, run_gates_body=_RUN_GATES_AFFECTED,
                    wb_review_body=_WB_REVIEW)
    _write_daily_full(repo, today=True)
    _write(repo, "code/a.py", "X = 2\n")

    done = _wand(repo, "--affected", "code/a.py")

    assert done.returncode == 0, _out(done)
    last = json.loads((repo / "gates/last.json").read_text(encoding="utf-8"))
    assert "affected" in last, \
        "增量那一趟必须有 affected 块（卡 147 护栏读它来咬「把增量当全量交」）"
    aff = last["affected"]
    assert isinstance(aff, dict) and "ran" in aff and "skipped" in aff, \
        f"affected 块形状不对：{aff!r}"


# ----------------------------------------------- ⓹ --no-review 跳过 ⑧
def test_no_review_skips_step8(tmp_path: Path) -> None:
    """`--no-review` ⇒ ⑧ 不跑、gates/review/<task>.json 不存在（默认会跑）。"""
    repo = _mk_repo(tmp_path, run_gates_body=_RUN_GATES_AFFECTED,
                    wb_review_body=_WB_REVIEW)
    _write_daily_full(repo, today=True)
    _write(repo, "code/a.py", "X = 2\n")

    done = _wand(repo, "--no-review")

    out = _out(done)
    assert done.returncode == 0, out
    assert "⑧ 复核落盘" not in out, "--no-review 应当跳过 ⑧"
    assert not (repo / "gates" / "review" / "T-G999.json").exists(), \
        "--no-review 不该有复核产物"


# ----------------------------------------------- ⓺ 降级跑法 trailer 留痕（边界纪律）
def test_degraded_run_trailer(tmp_path: Path) -> None:
    """设了 TF_PYTEST_WORKERS / TF_GATE_MIN_FREE_GB ⇒ 提交 trailer 必须点名（边界纪律）。

    ★ 判据：跑法字段缺失、或与默认不同却没有 trailer 声明 ⇒ 红（wb_review.py 那半属卡 161）。
    ★ 坏掉写法（不声明）：提交信息里没有 Run: 行 ⇒ 钉子红。
    ★ 不设环境变量 ⇒ 不该有 Run: 行（默认跑法不声明，宁多勿漏但不噪音）。
    """
    repo = _mk_repo(tmp_path, run_gates_body=_RUN_GATES_AFFECTED,
                    wb_review_body=_WB_REVIEW)
    _write_daily_full(repo, today=True)
    _write(repo, "code/a.py", "X = 2\n")

    env = {**_ENV, "TF_PYTEST_WORKERS": "1", "TF_GATE_MIN_FREE_GB": "1.5"}
    cmd = [sys.executable, "-X", "utf8", str(repo / "tools" / "wb_land.py"),
           "--card", "T-G999", "--tree", ".", "--task", "T-G999", "--title", "钉子",
           "--type", "feat", "--group", "ENGINEERING", "--evidence", "code/a.py",
           "--allow", "code"]
    done = subprocess.run(cmd, cwd=str(repo), env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")

    out = _out(done)
    assert done.returncode == 0, out
    msg = _git(repo, "log", "-1", "--format=%B").stdout
    assert "Run:" in msg, f"降级跑法必须在 trailer 里声明：{msg!r}"
    assert "TF_PYTEST_WORKERS=1" in msg, f"trailer 必须含 TF_PYTEST_WORKERS=1：{msg!r}"
    assert "TF_GATE_MIN_FREE_GB=1.5" in msg, f"trailer 必须含 TF_GATE_MIN_FREE_GB=1.5：{msg!r}"

    # 反向：不设环境变量 ⇒ 不该有 Run: 行
    (tmp_path / "b").mkdir(parents=True)
    repo2 = _mk_repo(tmp_path / "b", run_gates_body=_RUN_GATES_AFFECTED,
                     wb_review_body=_WB_REVIEW)
    _write_daily_full(repo2, today=True)
    _write(repo2, "code/a.py", "X = 2\n")
    done2 = _wand(repo2)
    assert done2.returncode == 0, _out(done2)
    msg2 = _git(repo2, "log", "-1", "--format=%B").stdout
    assert "Run:" not in msg2, f"默认跑法不该有 Run: trailer：{msg2!r}"

# ================================================ 卡 163 INV-28：收口链续租接线
_GATE_LOCK_RENEW = """import pathlib, sys
with pathlib.Path("gate_lock_calls.log").open("a", encoding="utf-8") as fh:
    fh.write(" ".join(sys.argv[1:]) + "\\n")
mk = pathlib.Path("lock.marker")
if "acquire" in sys.argv:
    mk.write_text("locked", encoding="utf-8")
elif "release" in sys.argv and mk.exists():
    mk.unlink()
elif "renew" in sys.argv:
    pathlib.Path("renew.marker").touch()
print("stub-gate_lock", " ".join(sys.argv[1:]))
sys.exit(0)
"""

_RUN_GATES_SLOW = """import pathlib, sys, time
pathlib.Path("gate_ran.marker").write_text("ran", encoding="utf-8")
time.sleep(0.5)
print("stub-run_gates")
sys.exit(0)
"""


def test_landing_renews_lock_during_gate(tmp_path: Path) -> None:
    """★ 卡 163 INV-28：收口链跑门禁期间自动续租 —— renew 真的被调过（不只是 cmd_renew 存在）。"""
    repo = _mk_repo(tmp_path)
    _write(repo, "gates/diag/gate_lock.py", _GATE_LOCK_RENEW)
    _write(repo, "scripts/run_gates.py", _RUN_GATES_SLOW)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "stubs with renew")

    env = {**_ENV, "TF_GATE_RENEW_INTERVAL": "0.05"}
    cmd = [sys.executable, "-X", "utf8", str(repo / "tools" / "wb_land.py"),
           "--card", "T-G999", "--tree", ".", "--task", "T-G999", "--title", "钉子",
           "--type", "feat", "--group", "ENGINEERING", "--evidence", "code/a.py",
           "--allow", "code"]
    subprocess.run(cmd, cwd=str(repo), env=env, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")

    calls = (repo / "gate_lock_calls.log").read_text(encoding="utf-8") \
        if (repo / "gate_lock_calls.log").exists() else ""
    assert "renew" in calls, f"续租必须真的发生（renew 被调过）：{calls!r}"


# ================================================ 卡 163 INV-10：第⑦步 ff 合流失败反例
def test_ff_merge_failure_does_not_print_complete(tmp_path: Path) -> None:
    r"""★ 卡 163 INV-10：ff 合流失败时不许打印「合流完成」—— 要打 stdout/stderr、退 2。

    卡明说「不覆盖⑦之后」，本卡**必须覆盖它**。造法：子 worktree 提交一笔 + 主树对同一文件
    造本地改动 ⇒ `git merge --ff-only` 拒绝覆盖本地改动 ⇒ HEAD 不变 ⇒ 不许打印「合流完成」。
    """
    repo = _mk_repo(tmp_path)
    sub = repo / ".wt" / "sub"
    _git(repo, "worktree", "add", str(sub), "HEAD")
    (sub / "code" / "a.py").write_text("X = 2\n", encoding="utf-8")
    (repo / "code" / "a.py").write_text("X = 3\n", encoding="utf-8")

    done = _wand(repo, "--no-gate", tree=".wt/sub", allow=("code",))

    out = _out(done)
    assert done.returncode == 2, out
    assert "ff 合流完成" not in out, "★ ff 没成功时不许打印「合流完成」"
    assert "没成功" in out, out
    assert "stdout:" in out, "要打 merge 的 stdout"
    assert "stderr:" in out, "要打 merge 的 stderr"


# ================================================ 卡 163 INV-23：stage_card 引号/反斜杠钉子
def _load_stage_card() -> ModuleType:
    """按文件路径加载 `tools/pool/stage_card.py`（钉**这一份**，不是 task.py 那份副本）。"""
    path = TOOLS / "pool" / "stage_card.py"
    spec = importlib.util.spec_from_file_location("stage_card_under_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_stage_card_quote_safe_escapes_windows_backslashes() -> None:
    r"""★ 含反斜杠的 Windows 路径 —— 反斜杠必须加倍（TOML 基本串里 \U 是 8 位十六进制转义）。"""
    import tomllib
    sc = _load_stage_card()
    out = sc.quote_safe(r"C:/Users/example\test")
    tomllib.loads(f'x = "{out}"')
    assert "\\\\" in out, "反斜杠必须加倍"


def test_stage_card_quote_safe_replaces_ascii_quotes_with_corners() -> None:
    """★ 含 ASCII 双引号的中文正文 —— 双引号换成「」。"""
    sc = _load_stage_card()
    out = sc.quote_safe('他说"你好"然后"再见"')
    assert '"' not in out, "ASCII 双引号不许留"
    assert "「" in out and "」" in out


def test_stage_card_unescape_git_quoted_octal() -> None:
    r"""★ 含八进制转义的 git 输出 —— 还原成人能用的路径。

    git 对非 ASCII 路径输出八进制转义：中文.txt 的 UTF-8 字节
    E4 B8 AD E6 96 87 → \344\270\255\346\226\207。
    """
    sc = _load_stage_card()
    escaped = '"\\344\\270\\255\\346\\226\\207.txt"'
    out = sc._unescape_git_quoted(escaped)
    assert out == "中文.txt", f"还原失败：{out!r}"


def test_stage_card_toml_str_produces_valid_toml() -> None:
    """★ _toml_str 对各种特殊字符都产出合法 TOML（钉 stage_card 这一份，不是 task.py 那份）。"""
    import tomllib
    sc = _load_stage_card()
    for s in (r"C:\Users\test", '含"引号"的', "含\\反斜杠的", "中文正文"):
        out = sc._toml_str(s)
        tomllib.loads(f"x = {out}")


# ================================================ 卡 204（T-G311）：落地即翻 status
#
# ★ 收口链在第⑥步把队列里那张卡的 status 翻成 done（当且仅当 --task == 卡.task）。
#   三条钉子：① 正向（自己的落地）⇒ 翻；② 反例（登记型 --task != 卡.task）⇒ 不翻；
#   ③ 跳过路径（找不到卡 / 已是 done）⇒ 打印并跳过。
#   ★ CRLF 感知：workbacklog.toml 是纯 CRLF，flip_card_status 按字节读写。

def _write_backlog(repo: Path, *, cid: str = "T-G999", task: str = "T-G999",
                   status: str = "pending") -> None:
    """往假仓库写一份只含一张卡的 workbacklog.toml（纯 CRLF，与真文件一致）。"""
    body = (
        f'[base]\nreviewed = "abc1234"\n\n'
        f'[[cards]]\n'
        f'id = "{cid}"\n'
        f'task = "{task}"\n'
        f'title = "测试卡"\n'
        f'tree = ""\n'
        f'spec = ""\n'
        f'files = ["code/a.py"]\n'
        f'depends = []\n'
        f'risk = "low"\n'
        f'status = "{status}"\n')
    _write(repo, "docs/workbacklog.toml", body, crlf=True)


def _backlog_card_status(repo: Path, cid: str) -> str:
    """读 HEAD 里 workbacklog.toml 那张卡的 status（提交之后的真读数）。"""
    import tomllib
    blob = _git(repo, "show", "HEAD:docs/workbacklog.toml").stdout
    data = tomllib.loads(blob)
    cards = [c for c in data["cards"] if c["id"] == cid]
    assert cards, f"提交里找不到卡 {cid}"
    return cards[0]["status"]


def test_landing_flips_status_when_task_matches(tmp_path: Path) -> None:
    """① 正向：--task == 卡.task ⇒ 提交里那张卡的 status = done（端到端）。"""
    repo = _mk_repo(tmp_path)
    _write_backlog(repo, cid="T-G999", task="T-G999", status="pending")
    _git(repo, "add", "--", "docs/workbacklog.toml")
    _git(repo, "commit", "-q", "-m", "add backlog")
    pen = _mk_pen(repo)
    _write(pen, "code/a.py", "X = 2\n")

    done = _wand(repo, "--no-gate", tree=".pen")

    out = _out(done)
    assert done.returncode == 0, out
    assert "[队列] 卡 T-G999：pending → done" in out, out
    assert _backlog_card_status(repo, "T-G999") == "done"


def test_landing_does_not_flip_status_on_registration(tmp_path: Path) -> None:
    """★★ 反例（最重要）：--task != 卡.task（登记型）⇒ 那张卡的 status 一字不动。"""
    repo = _mk_repo(tmp_path)
    _write_backlog(repo, cid="T-G999", task="T-G888", status="pending")
    _git(repo, "add", "--", "docs/workbacklog.toml")
    _git(repo, "commit", "-q", "-m", "add backlog")
    pen = _mk_pen(repo)
    _write(pen, "code/a.py", "X = 2\n")

    done = _wand(repo, "--no-gate", tree=".pen")

    out = _out(done)
    assert done.returncode == 0, out
    assert "登记型" in out, out
    assert _backlog_card_status(repo, "T-G999") == "pending"


def test_landing_skip_when_card_not_found(tmp_path: Path) -> None:
    """跳过路径：找不到卡 ⇒ 打印并跳过（不崩、不翻）。"""
    repo = _mk_repo(tmp_path)
    _write_backlog(repo, cid="203", task="T-G308", status="pending")
    _git(repo, "add", "--", "docs/workbacklog.toml")
    _git(repo, "commit", "-q", "-m", "add backlog")
    pen = _mk_pen(repo)
    _write(pen, "code/a.py", "X = 2\n")

    done = _wand(repo, "--no-gate", tree=".pen", card="999")

    out = _out(done)
    assert done.returncode == 0, out
    assert "找不到卡 999" in out, out
    assert _backlog_card_status(repo, "203") == "pending"


def test_landing_skip_when_already_done(tmp_path: Path) -> None:
    """跳过路径：已是 done ⇒ 打印并跳过（不崩、不重复翻）。"""
    repo = _mk_repo(tmp_path)
    _write_backlog(repo, cid="T-G999", task="T-G999", status="done")
    _git(repo, "add", "--", "docs/workbacklog.toml")
    _git(repo, "commit", "-q", "-m", "add backlog")
    pen = _mk_pen(repo)
    _write(pen, "code/a.py", "X = 2\n")

    done = _wand(repo, "--no-gate", tree=".pen")

    out = _out(done)
    assert done.returncode == 0, out
    assert "已是 done" in out, out
    assert _backlog_card_status(repo, "T-G999") == "done"


# -------------------------------------------------- 卡 212（T-G323）：攒批收口固定进工作流

sys.path.insert(0, str(TOOLS))
import json as _json212  # noqa: E402

from pool import landing as _landing  # noqa: E402
from pool import task as _task  # noqa: E402


def _mk_gate212(bd: Path, gate_id: str, state: str,
                members: list[dict[str, object]]) -> None:
    """在 `bd` 下造一个栅栏（toml + json），供卡 212 测试。"""
    bd.mkdir(parents=True, exist_ok=True)
    member_text = "".join(
        f'\n[[member]]\nid = "{m["id"]}"\nlayer = "{m.get("layer", "test")}"\n'
        + ('read_only = true\n' if m.get("read_only") else "")
        + f'paths = {_json212.dumps(m.get("paths", []))}\n'
        for m in members)
    (bd / f"{gate_id}.toml").write_text(
        f'id = "{gate_id}"\nwhy = "test"\non_complete = ["draft"]\n{member_text}',
        encoding="utf-8")
    declared = [str(m["id"]) for m in members]
    read_only = [str(m["id"]) for m in members if m.get("read_only")]
    st = {
        "id": gate_id, "why": "test", "layers": ["test"], "declared": declared,
        "read_only": read_only, "need": len(declared) - len(read_only),
        "claims": {}, "waived": [], "state": state, "auto": ["draft"],
        "gate_cmd": None, "deadline": None, "gate": None, "draft": None,
        "landed": None, "history": [],
    }
    (bd / f"{gate_id}.json").write_text(
        _json212.dumps(st, ensure_ascii=False) + "\n", encoding="utf-8")


def test_find_gates_for_member_by_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """成员号 == declared 里的成员 ⇒ 匹配。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path))
    _mk_gate212(tmp_path, "B-X", "collecting",
                [{"id": "203", "layer": "工具层", "paths": ["tools/x.py"]}])
    hits = _task.find_gates_for_member("203", ["tools/x.py"])
    assert hits == [("B-X", "203")], hits


def test_find_gates_for_member_by_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """成员号不等于卡号，但 paths 相交 ⇒ 匹配（B-DTREE 的 M-1 → 卡 203）。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path))
    _mk_gate212(tmp_path, "B-X", "collecting",
                [{"id": "M-1", "layer": "工具层",
                  "paths": ["tools/wb_plan.py", "tools/wb_dispatch.py"]}])
    hits = _task.find_gates_for_member("203",
                                       ["tools/wb_plan.py", "tools/wb_dispatch.py"])
    assert hits == [("B-X", "M-1")], hits


def test_find_gates_for_member_no_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """成员号不匹配且 paths 不相交 ⇒ 空列表。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path))
    _mk_gate212(tmp_path, "B-X", "collecting",
                [{"id": "M-1", "layer": "工具层", "paths": ["tools/x.py"]}])
    assert _task.find_gates_for_member("203", ["tools/z.py"]) == []


def test_other_members_in_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """栅栏里除了指定成员还有哪些非只读成员。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path))
    _mk_gate212(tmp_path, "B-X", "collecting", [
        {"id": "M-1", "layer": "工具层", "paths": ["a.py"]},
        {"id": "M-2", "layer": "工具层", "paths": ["b.py"]},
        {"id": "M-3", "layer": "审计层", "paths": [], "read_only": True},
    ])
    others = _task.other_members_in_gate("B-X", "M-1")
    assert others == ["M-2"], others  # M-3 是只读，不算


def test_warn_if_card_in_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """单张落地警告：卡属于批且批还有别的成员 ⇒ 打印警告。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path))
    _mk_gate212(tmp_path, "B-X", "collecting", [
        {"id": "M-1", "layer": "工具层", "paths": ["tools/x.py"]},
        {"id": "M-2", "layer": "工具层", "paths": ["tools/y.py"]},
    ])
    _landing._warn_if_card_in_batch("203", ["tools/x.py"])
    out = capsys.readouterr().out
    assert "警告" in out and "B-X" in out and "M-2" in out, out


def test_warn_if_card_in_batch_no_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """卡属于批但批没有别的成员 ⇒ 不警告（need=1 的批）。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path))
    _mk_gate212(tmp_path, "B-X", "collecting",
                [{"id": "M-1", "layer": "工具层", "paths": ["tools/x.py"]}])
    _landing._warn_if_card_in_batch("203", ["tools/x.py"])
    out = capsys.readouterr().out
    assert "警告" not in out, out


def test_integrate_multi_tree_single_tree_returns_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """只有一棵树（或读不到栅栏）⇒ 不做集成，返回 True。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path / "batch"))
    # 没有栅栏文件 ⇒ load_manifest 失败 ⇒ 返回 True
    assert _landing._integrate_multi_tree(tmp_path, "B-NOSUCH", "T-G999") is True


def test_integrate_multi_tree_no_gate_returns_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """读不到栅栏 ⇒ 不做集成，返回 True（现有逻辑不变）。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path / "empty"))
    (tmp_path / "empty").mkdir()
    assert _landing._integrate_multi_tree(tmp_path, "B-NOSUCH", "T-G999") is True


def test_integrate_multi_tree_ignores_cards_outside_the_fence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """★ 卡 212 跟进：批外的陈旧卡树**不许**被当成批成员（回归用例）。

    先红后绿：原条件 `cfiles and set(cfiles) & set(card_files_map.get(mid, ()))`
    是自己跟自己求交（恒真）⇒ backlog 里**每一条**带 `tree` 的卡都被认成
    "第一个成员"（这里恒为 215），于是批外的陈旧卡树也进了集成名单，
    报出 `X 和 X 都改了 <同一个文件>` 的**假冲突**，把 `--batch` 收口全挡住。

    钉住的是"映射对不对"，不是"集成了几棵树"：真成员 216 必须出现在
    成员名单里（恒真条件下它永远不会出现），批外卡 999 的树必须不出现。
    """
    bd = tmp_path / "batch"
    monkeypatch.setenv("TF_BATCH_DIR", str(bd))
    _mk_gate212(bd, "B-MAP", "awaiting-commit", [
        {"id": "215", "layer": "工具层", "paths": ["tools/a.py"]},
        {"id": "216", "layer": "工具层", "paths": ["tools/b.py"]},
    ])
    wt = tmp_path / "wt"
    (wt / "docs").mkdir(parents=True)
    (wt / "docs" / "workbacklog.toml").write_text(
        '[[cards]]\nid = "215"\ntree = ".wt/t215"\n\n'
        '[[cards]]\nid = "216"\ntree = ".wt/t216"\n\n'
        '[[cards]]\nid = "999"\ntree = ".wt/stale-tree"\n',
        encoding="utf-8")
    monkeypatch.setattr(_landing, "ROOT", tmp_path)
    # ★ 故意**不造**树目录：函数会走「树不存在 ⇒ 跳过」这一支，
    #   而那一支会把**成员号**打出来 —— 正好用来判映射对不对（不依赖 git）。
    _landing._integrate_multi_tree(wt, "B-MAP", "T-G999")
    out = capsys.readouterr().out
    assert "2 棵" in out, out
    assert "216" in out, out              # 真成员必须被认出来（恒真条件下恒不出现）
    assert "stale-tree" not in out, out   # 批外卡 999 的树不许进集成名单


def test_advance_card_gate_no_gate_skips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """卡不属于任何栅栏 ⇒ 打印跳过（不崩、不猜、不新建栅栏）。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path))
    _landing._advance_card_gate("999", "abc123", "T-G999", ["tools/z.py"])
    out = capsys.readouterr().out
    assert "不属于任何栅栏" in out, out
