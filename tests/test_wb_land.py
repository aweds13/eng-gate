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

import contextlib
import datetime
import importlib.util
import io
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
    # ★ 卡 E51：`wb_land.select_env()` 会 `import pytest_select`（选测口径的唯一真源）
    "tools/pytest_select.py",
    "tools/pool/__init__.py",
    "tools/pool/landing.py",
    # ★ 卡 E81（T-AG586）：`landing.py` 的翻账改走 `pool.ledger`（锁 + 原子写）
    #   ⇒ 沙箱少这一份，子进程一 import landing 就 ImportError（实测 13 条红）。
    "tools/pool/ledger.py",
    # ★ 卡 E81：`pool/ledger.py` 起要 `from pool.no_window import NO_WINDOW`
    #   ⇒ 沙箱少这一份，`import landing` 就 `ModuleNotFoundError: No module named
    #   'pool.no_window'`（实测 test_mixed_endings 那条「点名 C9」的用例红）。
    "tools/pool/no_window.py",
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
    # ★ 卡 A330（T-AG532）：task.py / queue.py / registry.py / pool_accounts.py 起都
    #   `import lastgood`（原子写 + `.bak` 落后一次写 + fail-closed 读）
    #   ⇒ 沙箱少这一份，收口链一 import 就 ModuleNotFoundError（实测 40 条红）。
    "tools/pool/lastgood.py",
    "tools/wb_task.py",
    # ★ 卡 E5（T-AG447）：`landing.py` 的 ④′ 合并队列要 `from pool import queue`
    #   ⇒ 沙箱少这一份，落地一进 ④′ 就 ImportError。
    "tools/pool/queue.py",
    # ★ 卡 E63（T-AG521）：`landing.py` 起把门禁产物再判一遍（`import gate_verdict`）
    #   ⇒ 沙箱少这一份，`--preflight` 一 import 就 ModuleNotFoundError（实测）。
    "tools/gate_verdict.py",
    # ★ 卡 E123（T-AG632）：`landing.py` / `gate_pool.py` 都要 `import gate_base`
    #   （门禁基点漂移分类器，全仓只此一份）⇒ 沙箱少这一份就 ModuleNotFoundError。
    "tools/gate_base.py",
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

#: ★ 卡 E1：桩也要 ruff 干净（`--preflight` 的 ruff 快检会扫 `scripts/`、`tools/`）——
#:   import 块与正文之间空一行（否则 `I001` 让体检红在**夹具**上，不是在代码上）。
_MAYBE = "import sys\n\nprint('stub')\nsys.exit(0)\n"

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
_RUN_GATES = """import pathlib
import sys

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
               # ★ 卡 E63：真产物一定带 `host`；桩也得带（落地链 check_host=True）。
               "host": __import__("socket").gethostname(),
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

#: ★ 卡 228 e2e 门禁桩：④ 假跑门禁（写**真模样**的 last.json：ok/rev=HEAD/docs_sync_ok/
#:   gates 与本桩 build_jobs 一致 —— wb_review ③′ 现读的就是这份），`--seal` 时用
#:   **真 run_gates 的算法**（`tree_without_gates` / `TREE_SCOPE`，importlib 按路径加载，
#:   ★ 不造第二份指纹实现）在 cwd（=.pen 卡树）上重算封存指纹。
#:   不能直接转发 `python <真卡树>/scripts/run_gates.py --seal`：真模块的 ROOT 绑定
#:   `__file__` 所在树，会把指纹算到卡树自己头上。
_RUN_GATES_E2E = '''import importlib.util, json, pathlib, subprocess, sys

REAL = r"{real}"
_spec = importlib.util.spec_from_file_location("_real_run_gates", REAL)
_real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _real  # ★ 先注册再 exec：真模块里有 dataclass，解析时要查 sys.modules
_spec.loader.exec_module(_real)


def build_jobs(quick, fast):
    return [("pytest", [])]


# ★ wb_review ③″ 复算「提交树去 gates/**」现读的就是本桩的这两个名字 —— re-export
#   真实现（不造第二份）：复核与封存用同一套切法，判据才对得上。
tree_without_gates = _real.tree_without_gates
TREE_SCOPE = _real.TREE_SCOPE


def _seal():
    last = pathlib.Path("gates") / "last.json"
    payload = json.loads(last.read_text(encoding="utf-8"))
    payload["tree"] = _real.tree_without_gates(
        pathlib.Path.cwd(), "HEAD", include_worktree=True)
    payload["tree_scope"] = _real.TREE_SCOPE
    payload["sealed_at"] = "stub"
    last.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[seal-stub] tree =", (payload["tree"] or "?")[:12])


def _main():
    args = sys.argv[1:]
    pathlib.Path("gate_ran.marker").write_text("ran", encoding="utf-8")
    if "--seal" in args:
        _seal()
        sys.exit(0)
    rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    payload = {{"ok": True, "rev": rev, "docs_sync_ok": True, "docs_sync_missing": [],
               "gates": [{{"name": n, "exit_code": 0}}
                         for n, _ in build_jobs(False, False)],
               "host": __import__("socket").gethostname(),
               "tree_scope": _real.TREE_SCOPE}}
    last = pathlib.Path("gates") / "last.json"
    last.parent.mkdir(exist_ok=True)
    last.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("stub-run_gates-e2e")
    sys.exit(0)


if __name__ == "__main__":
    _main()
'''

#: ★ 卡 228 先红钉：同上，但**第二次 `--seal` 之后**模拟「封存之后还有人改被跟踪文件」
#:   （卡 218 现场：⑤ 封存先算指纹、⑥ 提交前翻 status）—— 翻完还 `git add` 进提交
#:   ⇒ 提交树 ≠ 封存树 ⇒ 复核**必须**报「封存树 vs 提交树」（判据不许删/不许降级）。
_RUN_GATES_E2E_TAMPER = '''import importlib.util, json, pathlib, subprocess, sys

REAL = r"{real}"
_spec = importlib.util.spec_from_file_location("_real_run_gates", REAL)
_real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _real  # ★ 先注册再 exec：真模块里有 dataclass，解析时要查 sys.modules
_spec.loader.exec_module(_real)


def build_jobs(quick, fast):
    return [("pytest", [])]


# ★ 同 E2E 桩：wb_review ③″ 复算读的是本桩模块级这两个名字 —— re-export 真实现，
#   红钉才是「真比对出来的不等」，不是「复算失败拿不准不放过」那种假红。
tree_without_gates = _real.tree_without_gates
TREE_SCOPE = _real.TREE_SCOPE


def _seal():
    last = pathlib.Path("gates") / "last.json"
    payload = json.loads(last.read_text(encoding="utf-8"))
    payload["tree"] = _real.tree_without_gates(
        pathlib.Path.cwd(), "HEAD", include_worktree=True)
    payload["tree_scope"] = _real.TREE_SCOPE
    payload["sealed_at"] = "stub"
    last.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    n = 0
    if pathlib.Path("seal_count.txt").exists():
        n = int(pathlib.Path("seal_count.txt").read_text(encoding="utf-8"))
    pathlib.Path("seal_count.txt").write_text(str(n + 1), encoding="utf-8")
    if n >= 1:  # 第二次封存**之后**：模拟「封存之后才翻 status」（卡 218 病根原样）
        wb = pathlib.Path("docs") / "workbacklog.toml"
        wb.write_bytes(wb.read_bytes().replace(b"pending", b"done"))
        subprocess.run(["git", "add", "--", "docs/workbacklog.toml"],
                       capture_output=True, text=True)
    print("[seal-stub-tamper] tree =", (payload["tree"] or "?")[:12])


def _main():
    args = sys.argv[1:]
    pathlib.Path("gate_ran.marker").write_text("ran", encoding="utf-8")
    if "--seal" in args:
        _seal()
        sys.exit(0)
    rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    payload = {{"ok": True, "rev": rev, "docs_sync_ok": True, "docs_sync_missing": [],
               "gates": [{{"name": n, "exit_code": 0}}
                         for n, _ in build_jobs(False, False)],
               "host": __import__("socket").gethostname(),
               "tree_scope": _real.TREE_SCOPE}}
    last = pathlib.Path("gates") / "last.json"
    last.parent.mkdir(exist_ok=True)
    last.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("stub-run_gates-e2e-tamper")
    sys.exit(0)


if __name__ == "__main__":
    _main()
'''

#: ★ 卡 228 e2e 审计桩：wb_review ① 判据要「退出 0 + 审计通过 + 豁免 0 项已知欠账」。
_AUDIT_E2E = """import sys
print("审计通过：豁免 0 项已知欠账（桩）")
sys.exit(0)
"""

#: ★ 卡 A266：`_ENV` 改成**显式环境** —— 摘掉门禁自己的跑法变量
#: （`TF_PYTEST_WORKERS` / `TF_GATE_MIN_FREE_GB`），别让跑门禁时的环境渗进子进程：
#: 否则「**不设**变量 ⇒ 提交 trailer 不写 `Run:` 行」那条反例物理上不可能成立（必红）。
#: 用例自己要测就在用例里自己设（`{**_ENV, "TF_PYTEST_WORKERS": "1"}` 那种写法保持能跑）。
_ENV = {k: v for k, v in os.environ.items()
        if k not in ("PYTHONPATH", "TF_PYTEST_WORKERS", "TF_GATE_MIN_FREE_GB")}


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
             wb_review_body: str | None = None,
             audit_body: str | None = None) -> Path:
    """造一个「够收口链走到 ⑥」的最小假仓库：共享文档 + 桩 + 新工具 + 文书模板。

    `sync_docs_body` / `stage_card_body`：给真桩换**行为桩**（卡 150 的幂等钉子用）——
    在 `_stage_tools` 拷完真工具**之后**覆写，只影响用到它们的测试。
    `run_gates_body` / `wb_review_body`（卡 184）：换门禁桩 / 复核桩 —— 在初始提交里就位，
    免得 stub swap 本身变成卡树改动（会撞 ②.1 判据本体 ⇒ 强制全量）。
    `audit_body`（卡 228 e2e）：换审计桩 —— 复核 ① 判据要「审计通过 + 豁免 0」。
    """
    repo = tmp / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "nail@example.invalid")
    _git(repo, "config", "user.name", "nail")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "config", "commit.gpgsign", "false")
    # ★ 卡 239（T-G357）：门禁桩的产物按**真仓口径**排除出封存指纹 —— 它们是**跑门禁时
    #   生成的**（真链落在 gitignored 的 `gates/**` 下；桩写在树根，是夹具的简化落点），
    #   **提交装不下** ⇒ 不排除则封存树与提交树**不可比**，复核必报「封存树 vs 提交树」
    #   （卡 237 实测原话：差在 ['gate_lock_calls.log','gate_ran.marker','lock.marker']）。
    #   这不是放松判据：`check_seal_tree` 一字不动；「封存后真改了**被跟踪**文件」
    #   照样红（见 test_tamper_after_seal_review_red_e2e）。
    _write(repo, ".gitignore",
           "__pycache__/\n*.pyc\n"
           "gate_lock_calls.log\ngate_ran.marker\nlock.marker\nseal_count.txt\n")
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
    for rel in ("tools/sync_counts.py", "tools/sync_docs.py", "scripts/check_toml.py"):
        _write(repo, rel, _MAYBE)
    _write(repo, "scripts/audit_progress.py", audit_body or _MAYBE)
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
    card: str = "T-G999", task: str = "T-G999", batch: str | None = None,
    env: dict[str, str] | None = None,
    allow_flags: tuple[str, ...] | None = None,
) -> subprocess.CompletedProcess:
    """跑一次 wb_land。★ 卡 228：batch 给了走 --batch（恰好给一个）；env 覆写
    子进程环境（批 e2e 要传 TF_BATCH_DIR —— _ENV 是 import 时的快照，
    monkeypatch.setenv 影响不到它）。

    ★ 卡 E155（T-AG690）：allow_flags 用**重复开关**的写法给卡域
      （--allow a --allow b），而不是默认的「一条开关带多值」。两种写法都必须全部生效 ——
      默认 action 下前者只有最后一条活下来，而这条静默行为骗过了门禁、审计、封存、复核
      （卡 E154 那趟的真实现场）⇒ 必须有一条钉子一直走这条路。
    """
    cmd = [sys.executable, "-X", "utf8", str(repo / "tools" / "wb_land.py")]
    if batch is not None:
        cmd += ["--batch", batch]
    else:
        cmd += ["--card", card]
    cmd += ["--tree", tree, "--task", task, "--title", "钉子",
            "--type", "feat", "--group", "ENGINEERING", "--evidence", "code/a.py"]
    if allow_flags is None:
        cmd += ["--allow", *allow, *extra]
    else:
        cmd += [*allow_flags, *extra]
    return subprocess.run(cmd, cwd=str(repo), env=env or _ENV, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _mk_pen(repo: Path) -> Path:
    """给沙箱建一个**卡树**（worktree，`--tree .pen`）。

    ★ 卡 192（T-G292）起：`wb_land` 有「主干保护」——主树里出现白名单外的**跟踪文件**改动就退 5。
    这些钉子的场景本意是「**计划外暂存**发生在卡树里」（真流程就是 `.wt/<卡树>`）⇒ 只有把脏东西
    放进卡树，⑤/⑥ 才测得到、主树也才是干净的（否则守卫先咬，测的就不是原来那条路了）。
    """
    pen = repo / ".pen"
    # text=True 必给 encoding：云机 cp936 解码中文会崩，本机 utf-8 看不出来。
    # errors="replace"：宁可拿到带替换符的中文，也不要整条炸掉。
    subprocess.run(["git", "worktree", "add", "--detach", str(pen), "HEAD"],
                   cwd=str(repo), env=_ENV, capture_output=True, text=True, check=False,
                   encoding="utf-8", errors="replace",
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


# ======================================== ④″ 卡 E155：重复开关全部生效
def test_repeated_allow_flags_all_take_effect(tmp_path: Path) -> None:
    r"""卡 E155（T-AG690）：`--allow a --allow b c` 三条**都要生效**（端到端）。

    ★ 为什么这条钉子必须存在：argparse 的默认 action 下**重复给同一个开关只有最后一条生效**，
      不报错、不警告。卡 E154 第一趟（`gates/diag/land-E154.log`，2026-11-22 02:28）就这么
      丢掉 9 条 `--allow` 里的 8 条 ⇒ 提交 `c05b9b51` 只含派生物，本卡唯一的内容改动
      `复盘/收口后待用户清单.md` 一个字都没进。**每一道闸都说好**：`extra=[]`（暂存全是
      allow 内的派生物）+ `staged` 非空 ⇒「计划外或空暂存区 ⇒ 停手」不触发；门禁全绿、
      审计「926 条提交全部合格」、封存一致、⑧ 复核 problems=0，最后只在 rebase 报
      `error: cannot rebase: You have unstaged changes.` 这种指错方向的话。

    ★ 本仓既有钉子全是「一条开关 + 空格分隔多值」的写法（`_wand` 的默认路径），所以这条
      静默行为一次都没被咬过 —— 本钉子走 `allow_flags` 那条路，把「重复给」钉死。

    ★ 反向验证（必须做过的）：把 `tools/pool/landing.py` 的 `--allow` 改回默认 action，
      这条钉子**必红** —— 现场是 `code/a.py` 留在工作区没进暂存，且输出里有
      「卡域里有 N 条没进暂存区」那行。
    """
    repo = _mk_repo(tmp_path)
    pen = _mk_pen(repo)
    _write(pen, "code/a.py", "X = 2\n")
    _write(pen, "code/b.py", "Y = 2\n")

    done = _wand(repo, "--no-gate", tree=".pen",
                 allow_flags=("--allow", "code/a.py", "--allow", "code/b.py",
                              "--allow", "README.md"))

    out = _out(done)
    assert done.returncode == 0, out
    # ★ 断言看**提交**而不是暂存区：落地链会当场 commit，暂存区那时已经空了 ——
    #   断言暂存区等于什么都没测（第一版就这么写，恒为空）。
    committed = _git(repo, "show", "--name-only", "--format=", "HEAD").stdout.split()
    assert "code/a.py" in committed, f"重复给的 --allow 被吞了（只留最后一条）：{committed!r}"
    assert "code/b.py" in committed, f"重复给的 --allow 被吞了（只留最后一条）：{committed!r}"
    assert "卡域**一条都没生效**" not in out, out


def test_dead_allow_names_the_failure_without_changing_the_exit_code() -> None:
    """卡 E155：卡域**整个没生效**要留一行字，但**不许**改退出码（判据 4 的两面）。

    ★ 为什么只点名不改码：`--allow` 里带一个「这次没改、只是顺带声明」的文件是**合法**用法
      （只改文档却声明同域的一个代码文件）；判死会把正常落地拦下来。真正该拦的「计划外暂存」
      由 `extra` 管。
    """
    mod = _load_landing()
    assert mod.dead_allow(["a.py", "b.py"], ["a.py", "docs/x.md"]) == ["b.py"]
    assert mod.dead_allow(["a.py"], ["a.py"]) == []
    # 空 allow ⇒ 空（不是「全都没生效」）
    assert mod.dead_allow([], ["x"]) == []



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
    """① 卡 198 + 卡 E98（T-AG607）缺口 C：⑧ 调复核的 `--allow` 必须就是 ⑤′
    **真正拿去提交的那一份**（`expand_allow` 展开 + 三片段 + `DOCS` + `GATES`）。

    ★ 坏掉写法 A（不传）：复核 argv 里没有 `--allow` ⇒ 每笔报「没有给白名单」。
    ★ 坏掉写法 B（传原始 `a.allow`）：与 ⑤′ 那份不一致 ⇒ 每张翻账卡都报
      「有 1 个改动不在白名单里：['docs/workbacklog.toml']」（卡 E98 缺口 C 的现场）。
    ★ 坏掉写法 C（改成 --read-only 消红字）：有 `--read-only` 没有 `--allow`。

    ★ 为什么这条钉子的字面值在卡 E98 变了：旧断言写的是 `["code", "README.md"]`，
      即「原样传 `a.allow`」—— 那正是缺口 C 本身。现在标准改成「与提交那份一致」，
      所以字面值跟着变成展开后的那一份；坏掉写法 B 仍然咬得住 `a.allow`。
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
    # ⑤′ 真正拿去提交的那一份 = expand_allow(a.allow) + 三片段 + DOCS + GATES
    # （本假仓没有 docs/workbacklog.toml ⇒ 翻账后不会追加队列文件）。
    want = {
        "code/a.py",                          # 目录被 expand_allow 展开
        "README.md",                          # 用户给的白名单文件
        "docs/changelog.d/T-G999.md",         # 本台三片段
        "docs/traceability.d/T-G999.toml",
        "复盘/交接.d/T-G999.md",
        "docs/traceability.toml",             # DOCS
        "docs/changelog.md",
        "复盘/交接-重构进度.md",
        "gates/last.json",                    # GATES
        "gates/reuse.json",
    }
    assert "code" not in vals, \
        f"目录必须展开成文件清单（否则复核按目录名对不上任何改动）：{args!r}"
    assert set(vals) == want, \
        f"复核收到的 --allow 必须就是 ⑤′ 拿去提交的那一份（不许另造）：{args!r}"
    assert len(vals) == len(set(vals)), f"--allow 不许重复：{args!r}"
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
                   status: str = "pending", extra_pending: str | None = None,
                   spec: str = "", omit_status: bool = False,
                   extra_missing_status: str | None = None) -> None:
    """往假仓库写一份 workbacklog.toml（纯 CRLF，与真文件一致）。

    `extra_pending`：再附一张**永远 pending** 的卡（卡 228 红钉用）—— 主卡翻 done 之后
    账里仍有 `pending` 字样，封存后的翻账动作才有真内容可改。
    `spec`（卡 E1）：这张卡的规格路径；`--preflight` 要核「存在且已进 git」，默认空串
    保持老用例一字不变（它们不关心 spec）。
    `omit_status`（卡 E9）：主卡块**不写** status 行（注入「目标卡自己缺 status」）。
    `extra_missing_status`（卡 E9）：再附一块缺 status 的卡 —— 用来钉「目标卡**之外**的
    那块缺 status 也要被判出来」（半瞎 → 全判）。
    """
    body = (
        f'[base]\nreviewed = "abc1234"\n\n'
        f'[[cards]]\n'
        f'id = "{cid}"\n'
        f'task = "{task}"\n'
        f'title = "测试卡"\n'
        f'tree = ""\n'
        f'spec = "{spec}"\n'
        f'files = ["code/a.py"]\n'
        f'depends = []\n'
        f'risk = "low"\n')
    if not omit_status:
        body += f'status = "{status}"\n'
    if extra_pending:
        body += (
            f'\n[[cards]]\n'
            f'id = "{extra_pending}"\n'
            f'task = "T-G{extra_pending}"\n'
            f'title = "陪绑卡"\n'
            f'tree = ""\n'
            f'spec = ""\n'
            f'files = ["code/a.py"]\n'
            f'depends = []\n'
            f'risk = "low"\n'
            f'status = "pending"\n')
    if extra_missing_status:
        body += (
            f'\n[[cards]]\n'
            f'id = "{extra_missing_status}"\n'
            f'task = "T-G{extra_missing_status}"\n'
            f'title = "缺 status 的卡"\n'
            f'tree = ""\n'
            f'spec = "{spec}"\n'          # ⑤ 要 spec 存在且已跟踪 —— 借主卡那一份
            f'files = ["code/a.py"]\n'
            f'depends = []\n'
            f'risk = "low"\n')
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


def test_landing_refuses_when_card_not_registered(tmp_path: Path) -> None:
    """A318 钉子：卡不在卡树台账里 ⇒ **拒落退 2**（不再「跳过翻 status」）。"""
    repo = _mk_repo(tmp_path)
    _write_backlog(repo, cid="203", task="T-G308", status="pending")
    _git(repo, "add", "--", "docs/workbacklog.toml")
    _git(repo, "commit", "-q", "-m", "add backlog")
    pen = _mk_pen(repo)
    _write(pen, "code/a.py", "X = 2" + chr(10))

    done = _wand(repo, "--no-gate", tree=".pen", card="999")

    out = _out(done)
    assert done.returncode == 2, out
    assert "没有卡 999 的条目" in out, out
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


# -------------------------------------------------- 卡 E6（T-AG448）：卡树 HEAD 非主树祖先
def test_card_tree_head_not_ancestor_says_cherry_pick(tmp_path: Path) -> None:
    """卡树 HEAD 不是主树 HEAD 的祖先 ⇒ ① 停手退 3，且**报错文本含 `cherry-pick -n`**。

    这一条钉的是「先 commit 再落地」那条返工姿势的出口：守卫本来就会停手（`return 3`），
    但停手话术里没有把「已提交」的还原姿势写出来 ⇒ 人会去猜。
    坏掉的写法（删掉那句 print）：`returncode == 3` 照样成立，只有 `cherry-pick -n` 那条会红。
    """
    repo = _mk_repo(tmp_path)
    pen = _mk_pen(repo)
    _write(pen, "code/a.py", "X = 2\n")
    _git(pen, "add", "--", "code/a.py")
    _git(pen, "commit", "-q", "-m", "卡树里先 commit（就是要被挡的那种活）")

    done = _wand(repo, "--no-gate", tree=".pen")

    out = _out(done)
    assert done.returncode == 3, out
    assert "祖先" in out, out
    assert "cherry-pick -n" in out, out


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
        '[[cards]]\nid = "215"\ntree = ".wt/215"\n\n'
        '[[cards]]\nid = "216"\ntree = ".wt/216"\n\n'
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


# -------------------------------------------------- 卡 E13（T-AG464）：匹配**不许猜**
def _mk_src_tree(root: Path, name: str, changed: dict[str, str]) -> Path:
    """在 `<root>/.wt/<name>` 造一棵**真 git 树**：提交一个基点，再把 `changed` 写成工作区改动。

    `_integrate_multi_tree` 靠 `git diff --name-only HEAD` + `git ls-files -o` 认「这棵树
    改了什么」，所以夹具必须是真仓库（不是空目录）。
    """
    d = root / ".wt" / name
    d.mkdir(parents=True, exist_ok=True)
    _git(d, "init", "-q")
    _git(d, "config", "user.email", "nail@example.invalid")
    _git(d, "config", "user.name", "nail")
    _git(d, "config", "commit.gpgsign", "false")
    (d / "base.txt").write_text("base\n", encoding="utf-8")
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", "base")
    for rel, body in changed.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return d


def _mk_backlog(wt: Path, blocks: list[tuple[str, str]]) -> None:
    """`wt/docs/workbacklog.toml` 里写若干 `[[cards]]`（只带 id / tree）。"""
    (wt / "docs").mkdir(parents=True, exist_ok=True)
    (wt / "docs" / "workbacklog.toml").write_text(
        "".join(f'[[cards]]\nid = "{cid}"\ntree = "{tree}"\n\n' for cid, tree in blocks),
        encoding="utf-8")


def test_batch_member_matches_exact_id_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """★ 卡 E13 钉子 1：批里只有 `G1`（+`H2`）时，`.wt/F1` 的改动**一个都不许**进批树。

    旧码（数字键相等即认）在 `F1` 上必红：`F1` 的数字键是 `1`，与成员 `G1` 相同 ⇒
    旧码把 `(G1, .wt/F1)` 收进集成名单 ⇒ 批树里冒出 `f1_only.py`（正是第五处机制那次事故）。
    """
    bd = tmp_path / "batch"
    monkeypatch.setenv("TF_BATCH_DIR", str(bd))
    _mk_gate212(bd, "B-EXACT", "awaiting-commit", [
        {"id": "G1", "layer": "工具层", "paths": ["g1.py"]},
        {"id": "H2", "layer": "工具层", "paths": ["h2.py"]},
    ])
    _mk_src_tree(tmp_path, "G1", {"g1.py": "G1 = 1\n"})
    _mk_src_tree(tmp_path, "H2", {"h2.py": "H2 = 2\n"})
    _mk_src_tree(tmp_path, "F1", {"f1_only.py": "F1 = 3\n"})   # 批外，数字键撞 G1
    wt = tmp_path / "wt"
    wt.mkdir()
    _mk_backlog(wt, [("G1", ".wt/G1"), ("H2", ".wt/H2"), ("F1", ".wt/F1")])
    monkeypatch.setattr(_landing, "ROOT", tmp_path)

    assert _landing._integrate_multi_tree(wt, "B-EXACT", "T-G999") is True, \
        capsys.readouterr().out
    assert (wt / "g1.py").is_file(), "成员 G1 的改动必须合进来"
    assert (wt / "h2.py").is_file(), "成员 H2 的改动必须合进来"
    assert not (wt / "f1_only.py").exists(), \
        "★ .wt/F1 不是成员（数字键撞车不许冒充）—— 它的文件进了批树 = 别人的活被夹带"


def test_numeric_fallback_must_be_unique(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """★ 卡 E13 钉子 2：数字键撞车且**没有精确 id 可判** ⇒ 点名两个卡号并停手（返回 False）。

    栅栏成员是 `E1` / `G1`（数字键都是 `1`），backlog 里只有一张 `F1`（同样键 `1`，
    且没有精确命中）⇒ 谁都不许猜 ⇒ `_integrate_multi_tree` 必须返回 False（调用方退 3）。
    """
    bd = tmp_path / "batch"
    monkeypatch.setenv("TF_BATCH_DIR", str(bd))
    _mk_gate212(bd, "B-CLASH", "awaiting-commit", [
        {"id": "E1", "layer": "工具层", "paths": ["e1.py"]},
        {"id": "G1", "layer": "工具层", "paths": ["g1.py"]},
    ])
    _mk_src_tree(tmp_path, "E1", {"e1.py": "E1 = 1\n"})
    _mk_src_tree(tmp_path, "G1", {"g1.py": "G1 = 1\n"})
    wt = tmp_path / "wt"
    wt.mkdir()
    _mk_backlog(wt, [("F1", ".wt/F1")])
    monkeypatch.setattr(_landing, "ROOT", tmp_path)

    assert _landing._integrate_multi_tree(wt, "B-CLASH", "T-G999") is False
    out = capsys.readouterr().out
    assert "数字键撞车" in out, out
    assert "E1" in out and "G1" in out, out      # 点名两个候选成员（不猜）
    assert not (wt / "g1.py").exists(), "停手之后不许把任何一棵树合进来"


def test_member_tree_must_be_dot_wt_card(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """★ 卡 E13 钉子 3：成员声明的树不是它自己的树 ⇒ 点名并停手（防呆）。

    精确命中的 `G1` 在 backlog 里写的却是 `.wt/somebody-else` —— 那说明这条 backlog
    块其实不是它的（同名不同树）⇒ 匹配错了，必须停手，不许照样合。
    """
    bd = tmp_path / "batch"
    monkeypatch.setenv("TF_BATCH_DIR", str(bd))
    _mk_gate212(bd, "B-TREE", "awaiting-commit", [
        {"id": "G1", "layer": "工具层", "paths": ["g1.py"]},
        {"id": "H2", "layer": "工具层", "paths": ["h2.py"]},
    ])
    _mk_src_tree(tmp_path, "G1", {"g1.py": "G1 = 1\n"})
    _mk_src_tree(tmp_path, "H2", {"h2.py": "H2 = 2\n"})
    wt = tmp_path / "wt"
    wt.mkdir()
    _mk_backlog(wt, [("G1", ".wt/somebody-else"), ("H2", ".wt/H2")])
    monkeypatch.setattr(_landing, "ROOT", tmp_path)

    assert _landing._integrate_multi_tree(wt, "B-TREE", "T-G999") is False
    out = capsys.readouterr().out
    assert "声明的树是 .wt/somebody-else" in out, out
    assert "停手" in out, out
    assert not (wt / "h2.py").exists(), "停手之后一棵树都不许合"


def test_advance_card_gate_no_gate_skips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """卡不属于任何栅栏 ⇒ 打印跳过（不崩、不猜、不新建栅栏）。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path))
    _landing._advance_card_gate("999", "abc123", "T-G999", ["tools/z.py"])
    out = capsys.readouterr().out
    assert "不属于任何栅栏" in out, out


# ================================================ 卡 236（T-G354）：③″ 快预检的次序
# ★ ③″ 快门禁预检（卡 226 的 ③″；`run_gates.py --fast`，不落盘）的**次序**钉死：
#   「--card/--batch 恰好给一个」的参数合法性检查（退 6）**必须最先** —— 参数非法 ⇒
#   立刻退 6，**不碰门禁、不碰预检**；预检落在参数检查之后、全量门禁 ④ 之前。
#   三条钉子都要有先红后绿读数（旧码在反向那条上必红）。

#: ★ 快预检感知的门禁桩 = --fast 前缀 + _RUN_GATES_AFFECTED 本体：
#:   ① 每次被调都把 argv 追加记到 `fast_args.txt`（断言 --fast 跑没跑、跑了几次）；
#:   ② `--fast` 那一趟**不落盘**（不写 gate_ran.marker / last.json / gate_args.txt，
#:     与真 run_gates 的 --fast 同口径）；卡树里有 `fast_red.marker` ⇒ 退 1 并带出
#:     一句内存闸原话（模拟预检红）；否则退 0（预检绿）；
#:   ③ 非 --fast 的调用照走 _RUN_GATES_AFFECTED 的全量/seal 行为。
_RUN_GATES_FAST_PREFIX = '''import pathlib, sys

with pathlib.Path("fast_args.txt").open("a", encoding="utf-8") as fh:
    fh.write(" ".join(sys.argv[1:]) + "\\n")

if "--fast" in sys.argv:
    if pathlib.Path("fast_red.marker").exists():
        print("[FAIL] 内存闸拒跑：可用内存 2.0 GB < 阈值 2.0 GB")
        sys.exit(1)
    print("--fast 全过（stub）")
    sys.exit(0)
'''

_RUN_GATES_FAST = _RUN_GATES_FAST_PREFIX + _RUN_GATES_AFFECTED


def test_invalid_params_run_fast_preflight_zero_times(tmp_path: Path) -> None:
    """★★ 反向（本卡核心）：参数互斥非法 ⇒ 退 6，且 ③″ 预检被调用 **0 次**。

    旧码必红：旧码这条非法路径退 2（≠ 6）。③″ 若跑到参数检查**之前**，
    预检的输出（如内存闸那句话）会顶掉「恰好给一个」⇒ 既有判据红（主控 2026-10-14 实测）。
    """
    repo = _mk_repo(tmp_path, run_gates_body=_RUN_GATES_FAST,
                    wb_review_body=_WB_REVIEW)
    cmd = [sys.executable, "-X", "utf8", str(repo / "tools" / "wb_land.py"),
           "--card", "T-G999", "--batch", "B1", "--tree", ".", "--task", "T-G999",
           "--title", "钉子", "--type", "feat", "--group", "ENGINEERING",
           "--evidence", "code/a.py", "--allow", "code"]
    done = subprocess.run(cmd, cwd=str(repo), env=_ENV, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")

    out = _out(done)
    assert done.returncode == 6, out
    assert "恰好给一个" in out, out
    fast = (repo / "fast_args.txt").read_text(encoding="utf-8") \
        if (repo / "fast_args.txt").exists() else ""
    assert "--fast" not in fast, f"参数非法不许碰预检：{fast!r}"
    assert not (repo / "gate_ran.marker").exists(), "参数非法也不许碰全量门禁"


def test_preflight_red_stops_before_full_gates(tmp_path: Path) -> None:
    """参数合法 + ③″ 预检红 ⇒ 停手（退 7）且全量门禁 **0 次**（卡 226 判据，不许破）。"""
    repo = _mk_repo(tmp_path, run_gates_body=_RUN_GATES_FAST,
                    wb_review_body=_WB_REVIEW)
    _write(repo, "fast_red.marker", "red")

    done = _wand(repo)

    out = _out(done)
    assert done.returncode == 7, out
    assert "还没跑全量" in out, out
    assert "内存闸拒跑" in out, out
    assert not (repo / "gate_ran.marker").exists(), "预检红了不许再跑全量门禁"
    calls = (repo / "gate_lock_calls.log").read_text(encoding="utf-8") \
        if (repo / "gate_lock_calls.log").exists() else ""
    assert "acquire" not in calls, f"预检红了不许拿门禁锁：{calls!r}"


def test_preflight_green_continues_to_full_gates(tmp_path: Path) -> None:
    """参数合法 + ③″ 预检绿 ⇒ 继续走全量门禁（预检恰好 1 次）（卡 226 判据，不许破）。"""
    repo = _mk_repo(tmp_path, run_gates_body=_RUN_GATES_FAST,
                    wb_review_body=_WB_REVIEW)

    done = _wand(repo)

    out = _out(done)
    assert done.returncode == 0, out
    assert "快门禁全过" in out, out
    fast = (repo / "fast_args.txt").read_text(encoding="utf-8") \
        if (repo / "fast_args.txt").exists() else ""
    assert fast.count("--fast") == 1, f"预检应当恰好跑一次：{fast!r}"
    assert "门禁退出码 = 0" in out, out


# ================================================ 卡 238（T-G356）：⑨ 盖章前核验产物在提交里
# ★ 现象（机制自己制造的假账）：B-20261017/18/26 全被 ⑨ 标 landed，而 225 的活不在主仓 ——
#   ⑨ 按「成员都交了申请」就盖章、没验产物真在那笔提交里（推栅栏原话引的还是 236 的提交号）。
#   三条钉子：反向（不带产物 ⇒ 盖章函数被调用 0 次，先红后绿）/ 正向（产物真在 ⇒ 照旧盖章）/
#   边界（paths 为空 ⇒ 如实说「无法核验」，不盖章）；另加卡模式 landed 同款反例。
#   「盖章函数」= `_run_task_sub`（⑨ 推 claim / landed 全走它）—— 用记录桩数它被调几次。


def _mk_repo_238(tmp_path: Path) -> tuple[Path, str]:
    """造一个带**一笔真提交**的假仓（提交只改 code/a.py + tools/a.py），返回 (repo, sha)。"""
    repo = tmp_path / "repo238"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "nail@example.invalid")
    _git(repo, "config", "user.name", "nail")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "config", "commit.gpgsign", "false")
    _write(repo, "code/a.py", "X = 1\n")
    _write(repo, "tools/a.py", "A = 1\n")     # 这笔只带「tools/a.py 成员」的产物
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init for 238")
    sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    return repo, sha


def test_batch_gate_refuses_stamp_when_member_artifacts_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    """★★ 反向（本卡核心）：提交里没有成员 302 的产物 ⇒ ⑨ **不盖章** ——
    盖章函数（`_run_task_sub`）被调用 **0 次**，且点名里有 302。
    先红后绿：旧码按「成员都在名单」就推 2 个申请 + landed（调用 3 次）⇒ 旧码必红。"""
    bd = tmp_path / "batch"
    monkeypatch.setenv("TF_BATCH_DIR", str(bd))
    _mk_gate212(bd, "B-238", "awaiting-commit", [
        {"id": "301", "layer": "工具层", "paths": ["tools/a.py"]},
        {"id": "302", "layer": "工具层", "paths": ["tools/b.py"]},
    ])
    repo, sha = _mk_repo_238(tmp_path)              # 这笔提交只改 tools/a.py
    monkeypatch.setattr(_landing, "ROOT", repo)     # `git show` 在假仓里查
    calls: list[list[str]] = []
    monkeypatch.setattr(_landing, "_run_task_sub", lambda cmd: calls.append(cmd) or 0)

    _landing._advance_batch_gate("B-238", sha, "T-G999")

    out = capsys.readouterr().out
    assert calls == [], f"★ 盖章函数被调用了 {len(calls)} 次：{calls!r}"
    assert "拒盖章" in out, out
    assert "302 的产物不在这笔提交里" in out, out
    assert "paths=['tools/b.py']" in out, out       # 点名要带它的声明域


def test_batch_gate_stamps_when_artifacts_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    """正向：两个成员的产物**真在**这笔提交里 ⇒ 照旧盖章：2 个申请 + 1 个 landed
    （既有行为不变，不许因新核验多拒或少推）。"""
    bd = tmp_path / "batch"
    monkeypatch.setenv("TF_BATCH_DIR", str(bd))
    _mk_gate212(bd, "B-238P", "awaiting-commit", [
        {"id": "301", "layer": "工具层", "paths": ["tools/a.py"]},
        {"id": "302", "layer": "工具层", "paths": ["tools/b.py"]},
    ])
    repo, _ = _mk_repo_238(tmp_path)
    _write(repo, "tools/a.py", "A = 2\n")           # 第二笔同时带两个成员的产物
    _write(repo, "tools/b.py", "B = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "both artifacts")
    sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    monkeypatch.setattr(_landing, "ROOT", repo)
    calls: list[list[str]] = []
    monkeypatch.setattr(_landing, "_run_task_sub", lambda cmd: calls.append(cmd) or 0)

    _landing._advance_batch_gate("B-238P", sha, "T-G999")

    out = capsys.readouterr().out
    # ★ 按 argv 元素判（不 join 成串）—— pytest 的 tmp 目录名里可能有「landed」字样，
    #   子串匹配会假阳（本卡自证时当场咬过一次）。
    claim_calls = [c for c in calls if "claim" in c]
    landed_calls = [c for c in calls if "landed" in c]
    assert len(claim_calls) == 2 and all("B-238P" in c for c in claim_calls), calls
    assert len(landed_calls) == 1 and "B-238P" in landed_calls[0], calls
    assert "拒盖章" not in out, out


def test_batch_gate_empty_paths_says_cannot_verify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    """边界：成员声明的 paths 为空 ⇒ 如实说「无法核验」、**不盖章**（宁可漏盖不可假盖）。

    ★ `load_manifest` 的校验正常会拒「非只读成员 paths 为空」；这条钉的是核验自己的
      防御分支（别的入口绕过校验时也不许瞎盖）⇒ 用桩 manifest 直达 ⑨。
    """
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path / "batch"))
    repo, sha = _mk_repo_238(tmp_path)
    monkeypatch.setattr(_landing, "ROOT", repo)
    calls: list[list[str]] = []
    monkeypatch.setattr(_landing, "_run_task_sub", lambda cmd: calls.append(cmd) or 0)
    fake = {"id": "B-238E", "member": [{"id": "303", "layer": "工具层", "paths": []}]}
    monkeypatch.setattr(_task, "load_manifest", lambda tid: fake)

    _landing._advance_batch_gate("B-238E", sha, "T-G999")

    out = capsys.readouterr().out
    assert calls == [], f"★ 无法核验时不许盖章：{calls!r}"
    assert "无法核验" in out, out
    assert "303" in out, out


def test_card_gate_refuses_landed_when_other_member_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    """卡模式同款核验（现象原样）：本卡（236）产物在、栅栏也齐，但**别的成员**（225）
    的产物不在这笔提交里 ⇒ 本卡的申请照推（那是真的）、**landed 不许标**。
    旧码会拿本卡的提交号把整个批盖成 landed（f4d4626 假账）⇒ 旧码必红。"""
    bd = tmp_path / "batch"
    monkeypatch.setenv("TF_BATCH_DIR", str(bd))
    _mk_gate212(bd, "B-238C", "awaiting-commit", [
        {"id": "236", "layer": "工具层", "paths": ["tools/a.py"]},
        {"id": "225", "layer": "工具层", "paths": ["tools/b.py"]},
    ])
    repo, sha = _mk_repo_238(tmp_path)              # 这笔提交只带 236 的产物
    monkeypatch.setattr(_landing, "ROOT", repo)
    calls: list[list[str]] = []
    monkeypatch.setattr(_landing, "_run_task_sub", lambda cmd: calls.append(cmd) or 0)

    _landing._advance_card_gate("236", sha, "T-G999", ["tools/a.py"])

    out = capsys.readouterr().out
    # ★ 按 argv 元素判（不 join 成串）—— tmp 目录名 test_card_gate_refuses_landed_0
    #   自带「landed」字样，子串匹配会假阳（本卡自证时当场咬过一次）。
    claim_calls = [c for c in calls if "claim" in c]
    landed_calls = [c for c in calls if "landed" in c]
    assert len(claim_calls) == 1 and "B-238C" in claim_calls[0], calls
    assert landed_calls == [], f"★ landed 不许盖：{calls!r}"
    assert "不标 landed" in out, out
    assert "225 的产物不在这笔提交里" in out, out


# ================================================================ 卡 228（T-G344）：完整链判据
# ★ 判据本体：临时小树跑**完整链**（假门禁 + 真封存算法 + 假提交），断言真复核
#   `problems == []`；配两条先红后绿反例。真复核 = **真 wb_review.py**（不是桩）——
#   只有真判据才能钉住「链子顺序改对了」。

def _real_run_gates_path() -> Path:
    """真 run_gates.py（卡树 scripts/ 下）—— e2e 桩 import 它的指纹算法，不造第二份。"""
    return ROOT / "scripts" / "run_gates.py"


def test_full_chain_review_green_e2e(tmp_path: Path) -> None:
    """★ 卡 228 判据：完整链跑完（翻账 → 封存 → 兜底重封存 → 提交 → 复核），
    真复核 `problems == []` —— 卡 218 那笔「封存树 vs 提交树必然红」的病根已修。

    ★ 先红后绿：老链（⑤ 封存在 ⑤′ 翻账之前 + `add -A` 指纹）下本测试必红
      （workbacklog.toml 翻账后提交树 ≠ 封存树）。
    """
    repo = _mk_repo(
        tmp_path,
        run_gates_body=_RUN_GATES_E2E.format(real=str(_real_run_gates_path())),
        wb_review_body=(TOOLS / "wb_review.py").read_text(encoding="utf-8"),
        audit_body=_AUDIT_E2E)
    _write_backlog(repo, cid="T-G999", task="T-G999", status="pending")
    _git(repo, "add", "--", "docs/workbacklog.toml")
    _git(repo, "commit", "-q", "-m", "add backlog")
    _git(repo, "branch", "-m", "line/impl-v1")  # 复核分支判据认这个名字
    pen = _mk_pen(repo)
    _write(pen, "code/a.py", "X = 2\n")

    done = _wand(repo, tree=".pen", allow=("code/a.py", "docs/workbacklog.toml"))

    out = _out(done)
    assert done.returncode == 0, out
    assert "[队列] 卡 T-G999：pending → done" in out, out
    assert _backlog_card_status(repo, "T-G999") == "done"
    review = json.loads(
        (repo / "gates" / "review" / "T-G999.json").read_text(encoding="utf-8"))
    assert review.get("problems") == [], review


def test_gate_artifacts_present_or_changed_keep_review_green_e2e(
    tmp_path: Path,
) -> None:
    """★★ 卡 239 正向判据：门禁产物**存在/变化** ⇒ **不许**影响那条 e2e
    （真复核 `problems == []`）。

    ★ 场景 = 卡 237 实测现场：门禁桩在树根落产物（真链落在 gitignored 的 `gates/**`
      下，提交装不下），且链子开跑**之前**就有「上一趟」的残留（存在）、④~⑤ 之间还会
      被桩**重写**（变化）—— 存在 + 变化都真发生了，测试不许空转。
    ★ 先红后绿：旧夹具（产物未被排除 ⇒ 进了封存指纹、提交装不下）下本测试必红 ——
      原话 `差在这些路径：['gate_lock_calls.log','gate_ran.marker','lock.marker']`
      （卡 237 判 228 没改完的那条读数）。
    """
    repo = _mk_repo(
        tmp_path,
        run_gates_body=_RUN_GATES_E2E.format(real=str(_real_run_gates_path())),
        wb_review_body=(TOOLS / "wb_review.py").read_text(encoding="utf-8"),
        audit_body=_AUDIT_E2E)
    _write_backlog(repo, cid="T-G999", task="T-G999", status="pending")
    _git(repo, "add", "--", "docs/workbacklog.toml")
    _git(repo, "commit", "-q", "-m", "add backlog")
    _git(repo, "branch", "-m", "line/impl-v1")  # 复核分支判据认这个名字
    pen = _mk_pen(repo)
    _write(pen, "code/a.py", "X = 2\n")
    # 「上一趟门禁」的残留产物：链子开跑之前就在（存在）——
    # 放在卡树里（门禁桩的 cwd），与卡 237 失败读数里的裸路径同位。
    (pen / "gate_ran.marker").write_text("stale-from-last-run", encoding="utf-8")
    (pen / "gate_lock_calls.log").write_text("release --card last-run\n",
                                             encoding="utf-8")

    done = _wand(repo, tree=".pen", allow=("code/a.py", "docs/workbacklog.toml"))

    out = _out(done)
    assert done.returncode == 0, out
    # 存在 + 变化都真发生了：④ 桩把残留重写成 "ran"；锁账里多了本趟的 acquire
    assert (pen / "gate_ran.marker").read_text(encoding="utf-8") == "ran", out
    assert "acquire" in (pen / "gate_lock_calls.log").read_text(encoding="utf-8"), out
    review = json.loads(
        (repo / "gates" / "review" / "T-G999.json").read_text(encoding="utf-8"))
    assert review.get("problems") == [], review


def test_tamper_after_seal_review_red_e2e(tmp_path: Path) -> None:
    """★★ 卡 228 反例（先红钉，判据不放松）：封存之后仍改被跟踪文件并暂存进提交
    ⇒ 真复核**必须**报「封存树 vs 提交树」。

    ★ 这条钉住 `wb_review.check_seal_tree` 本体：删掉它 / 降级成警告 = 本测试红。
      桩在**第二次** `--seal`（= ⑤″ 兜底之后没有第三道封存）之后翻账 + `git add`，
      原样复刻卡 218 现场。
    """
    repo = _mk_repo(
        tmp_path,
        run_gates_body=_RUN_GATES_E2E_TAMPER.format(real=str(_real_run_gates_path())),
        wb_review_body=(TOOLS / "wb_review.py").read_text(encoding="utf-8"),
        audit_body=_AUDIT_E2E)
    # ★ 陪绑卡 998 留在 pending：主卡在 ⑤′（封存**前**）已被新链翻成 done，
    #   桩在**封存之后**把账里剩的 pending 翻 done —— 那一刻改的才是**真内容**
    #   （等价卡 218 现场：封存先算树、翻账在提交前 ⇒ 提交树 ≠ 封存树）。
    _write_backlog(repo, cid="T-G999", task="T-G999", status="pending", extra_pending="998")
    _git(repo, "add", "--", "docs/workbacklog.toml")
    _git(repo, "commit", "-q", "-m", "add backlog")
    _git(repo, "branch", "-m", "line/impl-v1")
    pen = _mk_pen(repo)
    _write(pen, "code/a.py", "X = 2\n")

    done = _wand(repo, tree=".pen", allow=("code/a.py", "docs/workbacklog.toml"))

    out = _out(done)
    assert done.returncode == 0, out  # ⑧ 复核不挡提交；问题在复核记录里
    review = json.loads(
        (repo / "gates" / "review" / "T-G999.json").read_text(encoding="utf-8"))
    problems = [str(p) for p in review.get("problems", [])]
    assert any("封存树 vs 提交树" in p for p in problems), problems


def test_batch_landing_flips_member_status_e2e(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """★★ 卡 228 批 e2e（先红后绿钉）：`--batch` 收口、`--task` 给**批台账号**（T-G340，
    不在队列）⇒ 成员卡 301 的 status 仍**必须**翻成 done。

    ★ 老码必红：老链拿批台账号去比每张卡自己的 `task`（T-G333）⇒ 永远比不中 ⇒
      「一张都翻不了」。新码按批清单 `[[member]]` + 「产物 ∩ 暂存」判 ⇒ 翻中。
    """
    bd = tmp_path / "batch"
    monkeypatch.setenv("TF_BATCH_DIR", str(bd))  # 进程内辅助（_integrate 等）
    _mk_gate212(bd, "B-TEST1", "collecting", [
        {"id": "301", "layer": "工具层", "paths": ["code/a.py"]}])
    repo = _mk_repo(tmp_path)
    _write(repo, "gates/diag/_text_TG340.md", _TEXT)  # 批台账号 T-G340 的文书模板
    _write_backlog(repo, cid="301", task="T-G333", status="pending")
    _git(repo, "add", "--", "docs/workbacklog.toml")
    _git(repo, "commit", "-q", "-m", "add backlog")
    pen = _mk_pen(repo)
    _write(pen, "code/a.py", "X = 2\n")

    done = _wand(repo, batch="B-TEST1", task="T-G340", tree=".pen",
                 allow=("code/a.py", "docs/workbacklog.toml"),
                 env={**_ENV, "TF_BATCH_DIR": str(bd)})

    out = _out(done)
    assert done.returncode == 0, out
    assert "卡 301：pending → done" in out, out
    assert _backlog_card_status(repo, "301") == "done"


def test_flip_card_status_require_task_match_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture,
) -> None:
    """卡 228 单元钉：`require_task_match=False` 跳过 task 比对（批成员翻账专用）；
    默认 `True` 时 task 不匹配仍拒绝 —— 登记型保护**不放松**（单卡路径一字不变）。"""
    repo = _mk_repo(tmp_path)
    _write_backlog(repo, cid="301", task="T-G333", status="pending")

    flipped = _landing.flip_card_status(repo, "301", "", require_task_match=False)
    # 卡 E61（T-AG519）：返回值改成三态（"flipped" / "not-needed" / "unflippable"），
    # 「不用翻」与「该翻却翻不动」不许再共用一个布尔值。
    assert flipped == "flipped"
    _git(repo, "add", "--", "docs/workbacklog.toml")
    _git(repo, "commit", "-q", "-m", "flip 301")
    assert _backlog_card_status(repo, "301") == "done"

    _write_backlog(repo, cid="302", task="T-G334", status="pending")
    _git(repo, "add", "--", "docs/workbacklog.toml")
    _git(repo, "commit", "-q", "-m", "add 302")
    flipped2 = _landing.flip_card_status(repo, "302", "T-G999")  # 默认：task 不匹配 ⇒ 拒
    assert flipped2 == "not-needed"
    assert _backlog_card_status(repo, "302") == "pending"
    assert "登记型" in capsys.readouterr().out


# ================================================ 卡 E1（T-AG443）：--preflight 判据前置
#
# 定义：落地**前**一次零副作用的只读体检，11 条判据一次说全（不 fail-fast）。
# 三条钉子（照卡 §交付）：全绿退 0 / 缺文书退 1 且报出路径 / 有 offender 退 1 且清单一致；
# 外加两条同族：只读（前后 git status 逐字相同）、与 --card 同给时体检完继续落地。


def _preflight(repo: Path, *extra: str,
               env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """在假仓库里跑一次 `wb_land.py --preflight ...`（走壳层入口，不另造第二套）。

    `env` 覆写子进程环境（卡 E16 的锁读数要指定端口段 —— `_ENV` 是 import 时的快照）。
    """
    cmd = [sys.executable, "-X", "utf8", str(repo / "tools" / "wb_land.py"),
           "--preflight", *extra]
    return subprocess.run(cmd, cwd=str(repo), env=env or _ENV, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _mk_preflight_repo(tmp: Path) -> Path:
    """绿色体检的最小真仓：队列里的卡 `C1`（task T-G999）+ 它那份已进 git 的规格。"""
    repo = _mk_repo(tmp)
    # ★ 卡 E1：ruff 的判据要带**真仓同一份**规则表 —— 没有 pyproject 时 ruff 会退回默认
    #   规则集（多出 RUF/PLW…），体检就在**夹具**上红，跟代码没关系。
    _write(repo, "pyproject.toml",
           "[tool.ruff]\nline-length = 100\n\n[tool.ruff.lint]\n"
           "select = [\"E\", \"W\", \"F\", \"I\", \"N\", \"UP\", \"B\", \"SIM\", \"TCH\"]\n")
    _write(repo, "复盘/卡/卡C1-合成.md", "# 合成卡规格\n")
    _write_backlog(repo, cid="C1", task="T-G999", status="pending",
                   spec="复盘/卡/卡C1-合成.md")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "queue")
    return repo


def _guard_offenders(repo: Path, allow: list[str]) -> list[str]:
    """用**假仓库里那份** landing 现算 offender 清单（体检的清单一字不差地对它）。"""
    code = (
        "import pathlib, sys\n"
        "sys.path.insert(0, 'tools')\n"
        "from pool import landing\n"
        f"print(chr(10).join(landing.main_tree_offenders({allow!r},"
        " pathlib.Path('.pen'))))\n"
    )
    done = subprocess.run([sys.executable, "-X", "utf8", "-c", code], cwd=str(repo),
                          env=_ENV, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return [ln for ln in (done.stdout or "").splitlines() if ln.strip()]


def test_preflight_all_green_exits_zero_and_is_read_only(tmp_path: Path) -> None:
    """全绿 ⇒ 退 0 + 「可以直接落地」；且 `--preflight` **只读**（前后 status 逐字相同）。"""
    repo = _mk_preflight_repo(tmp_path)
    _write(repo, "code/a.py", "X = 2\n")      # 卡域里真有产物（否则第 ⑥ 条该红）
    before = _git(repo, "status", "--porcelain").stdout

    # ★ 只给 --task（不给 --card）= 纯体检、体检完早退（判据 4：全绿退 0）
    done = _preflight(repo, "--task", "T-G999", "--tree", ".", "--allow", "code")

    out = _out(done)
    assert done.returncode == 0, out
    assert "可以直接落地" in out, out
    assert "❌" not in out, out
    after = _git(repo, "status", "--porcelain").stdout
    assert after == before, "preflight 改了工作区/索引 —— 判据 2 要求前后 status 逐字相同"


def test_preflight_missing_text_exits_one_and_names_the_path(tmp_path: Path) -> None:
    """缺 `_text_<台账号>.md` ⇒ 退 1、**报出路径**，且 11 条判据照跑（不 fail-fast）。"""
    repo = _mk_preflight_repo(tmp_path)
    _write(repo, "code/a.py", "X = 2\n")
    (repo / "gates" / "diag" / "_text_TG999.md").unlink()

    done = _preflight(repo, "--task", "T-G999", "--tree", ".", "--allow", "code")

    out = _out(done)
    assert done.returncode == 1, out
    assert "缺文档件" in out and "_text_TG999.md" in out, out
    marks = [ln for ln in out.splitlines() if ln.startswith(("  ✅", "  ❌"))]
    assert len(marks) == 12, f"判据没跑全（fail-fast 了？）：{len(marks)} 条\n{out}"
    assert "修完重跑" in out, out


def test_missing_text_message_survives_the_display_budget(tmp_path: Path) -> None:
    """缺件话术必须报**仓库相对**路径 —— 绝对路径会被 150 字预算连 `.md` 一起切掉。

    ★ 卡 E49（T-AG499）实测：云机的基础临时目录长（`…\\pytest-of-Administrator\\
      pytest-70\\popen-gw2\\test_preflight_missing_text_ex0\\repo\\…`），绝对路径超过
      `--preflight` 打印时的 `detail[:150]` ⇒ 日志上只剩 `_text_TG999`，看着像「工具要的
      是没有后缀的文件」；本机短路径不复现，单人单跑也不复现。判据不能靠「路径刚好够短」。
    """
    repo = _mk_preflight_repo(tmp_path)
    _write(repo, "code/a.py", "X = 2\n")
    (repo / "gates" / "diag" / "_text_TG999.md").unlink()

    out = _out(_preflight(repo, "--task", "T-G999", "--tree", ".", "--allow", "code"))

    assert "缺文档件：gates/diag/_text_TG999.md" in out, out
    assert str(tmp_path) not in out, f"缺件话术里带了绝对路径 ⇒ 长路径下会被截断\n{out}"


def test_preflight_offender_list_matches_the_guard(tmp_path: Path) -> None:
    """主树有白名单外的跟踪改动 ⇒ 退 1，且**列出来的就是守卫那一份**（不另算一套）。"""
    repo = _mk_preflight_repo(tmp_path)
    pen = _mk_pen(repo)
    _write(pen, "code/a.py", "X = 2\n")
    _write(repo, "README.md", "hand edited in the main tree\n")

    expected = _guard_offenders(repo, ["code"])
    assert expected, "夹具没造出 offender ⇒ 下面的断言没有意义"

    done = _preflight(repo, "--task", "T-G999", "--tree", ".pen", "--allow", "code")

    out = _out(done)
    assert done.returncode == 1, out
    for line in expected:
        assert line.strip() in out, f"清单不一致：体检漏了 {line!r}\n{out}"


def test_preflight_with_card_continues_into_landing(tmp_path: Path) -> None:
    """`--preflight` 与 `--card` 同给：体检绿后**接着落地**（缺必填参数 ⇒ 落地链退 2）。"""
    repo = _mk_preflight_repo(tmp_path)
    _write(repo, "code/a.py", "X = 2\n")

    done = _preflight(repo, "--card", "C1", "--tree", ".", "--allow", "code")

    out = _out(done)
    assert "可以直接落地" in out, out      # 体检这一趟真跑了且全绿
    assert done.returncode == 2, out      # 然后进落地链：缺 --task/--title ⇒ argparse 退 2
    assert "required" in out.lower(), out


# ------------------------------------------------ 卡 E9（T-AG455）：⑧ 从「只看目标卡」改成**全判**
#
# 为什么（卡 E9 §现在疼在哪）：卡 E1 把第 ⑧ 条收窄成只判「这一趟要落的这张卡」，因为队列里
# 11 块没有 status 行；数据已补齐（本轮），判据恢复全判 —— 判据不该为了迁就数据而降级。
# 三条钉子：全队列干净 ⇒ ✅ / 目标卡自己缺 ⇒ ❌ 点名 / **目标卡之外**那块缺 ⇒ ❌ 点名（半瞎→全判）。


def _item_line(out: str, name: str) -> str:
    """取体检里某一条判据的那一行（✅/❌ 都算）。"""
    hits = [ln for ln in out.splitlines()
            if ln.strip().startswith(("✅", "❌")) and name in ln]
    assert hits, f"体检没输出「{name}」这一条：\n{out}"
    return hits[0]


def test_preflight_status_check_is_green_on_clean_queue(tmp_path: Path) -> None:
    """全队列都有 status ⇒ 第 ⑧ 条 ✅（整队列一块不缺时不许报 ❌）。"""
    repo = _mk_preflight_repo(tmp_path)
    _write(repo, "code/a.py", "X = 2\n")

    done = _preflight(repo, "--task", "T-G999", "--tree", ".", "--allow", "code")

    out = _out(done)
    assert done.returncode == 0, out
    line = _item_line(out, "队列卡块有 status 行")
    assert line.lstrip().startswith("✅"), line


def test_preflight_status_check_red_when_target_card_lacks_status(tmp_path: Path) -> None:
    """目标卡自己的块缺 status ⇒ 第 ⑧ 条 ❌ 且点名这张卡（老行为不许丢）。"""
    repo = _mk_preflight_repo(tmp_path)
    _write(repo, "code/a.py", "X = 2\n")
    _write_backlog(repo, cid="C1", task="T-G999",
                   spec="复盘/卡/卡C1-合成.md", omit_status=True)

    done = _preflight(repo, "--task", "T-G999", "--tree", ".", "--allow", "code")

    out = _out(done)
    assert done.returncode == 1, out
    line = _item_line(out, "队列卡块有 status 行")
    assert line.lstrip().startswith("❌"), line
    assert "卡 C1" in line, line


def test_preflight_status_check_red_on_other_card_missing_status(tmp_path: Path) -> None:
    """★★ 本卡核心：缺 status 的是**目标卡之外**那一块 ⇒ 照样 ❌ 且点名它。

    改前（只判目标卡）这一段必定红：目标卡 C1 的 status 齐 ⇒ 第 ⑧ 条报 ✅，D9 被静默放过
    —— 这正是「半瞎」。
    """
    repo = _mk_preflight_repo(tmp_path)
    _write(repo, "code/a.py", "X = 2\n")
    _write_backlog(repo, cid="C1", task="T-G999", spec="复盘/卡/卡C1-合成.md",
                   extra_missing_status="D9")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "queue with a status-less block")

    done = _preflight(repo, "--task", "T-G999", "--tree", ".", "--allow", "code")

    out = _out(done)
    assert done.returncode == 1, out
    line = _item_line(out, "队列卡块有 status 行")
    assert line.lstrip().startswith("❌"), line
    assert "卡 D9" in line, line
    assert "卡 C1" not in line, f"目标卡 C1 有 status，不该被点名：{line}"


# ============================================ 卡 G3（T-AG458）：preflight 两层次分层命名
def test_preflight_flags_live_on_two_layers(capsys) -> None:
    """★ 卡 G3：`--preflight`（壳层只读体检）与 `--skip-preflight`（内层跳过快门禁预检）分层。

    反例：两个旗标同义、或落地链里又叫 `--no-preflight` 又叫 `--preflight` ⇒ 本钉子红。
    """
    from tools.pool import landing

    buf = io.StringIO()
    with contextlib.suppress(SystemExit), contextlib.redirect_stdout(buf):
        landing.main(["--help"])
    help_text = buf.getvalue()
    assert "--skip-preflight" in help_text, (
        f"落地链帮助里没有 `--skip-preflight`：{help_text[:400]}")
    assert "--no-preflight" in help_text, "旧写法 `--no-preflight` 要留着（已发布过）"
    assert "  --preflight" not in help_text, (
        "落地链**不该**自己收 `--preflight` —— 那是壳层的只读体检（卡 E1），两层不许同名")


def test_legacy_no_preflight_still_works_and_says_it_was_renamed(capsys) -> None:
    """旧写法照旧生效，但必须当场说「已改名」——静默改名比报错更难查。"""
    from tools.pool import landing

    rc = landing.main(["--tree", ".wt/x", "--task", "T-1", "--title", "t",
                       "--evidence", "e", "--allow", "a", "--no-preflight"])
    out = capsys.readouterr().out
    assert rc == 6, "缺 --card/--batch 应在解析后退 6（参数检查最先）"
    assert "已改名" in out and "--skip-preflight" in out, out


# ============================================ 卡 E15（T-AG466）：文书引用体检（第 12 条）
#
# 痛点（实测）：`check_layers` 的「引用完整性」只扫 `docs/**/*.md`，一条写错的短路径要等
# **全量门禁**（≈15 分钟）才红，而且同时打红 `check_layers` 与 `check_layers_selftest` 两道门。
# 这条判据把它提前到体检（10 秒内说），且**只扫本次要提交的三份文书**（不跑全量 check_layers）。

#: 合成文书：changelog 段里**故意**写一条解析不到的短路径。
_TEXT_BAD_REF = """=== gaps ===
**边界**：合成卡，仅供钉子用（指针 `code/a.py`）。
=== changelog ===
## 2026-10-02 · 钉子用
- 照抄的短路径 `pipe-land/SKILL.md`（解析不到）
=== checkpoint ===
> **2026-10-02 · CHECKPOINT（合成）**：钉子用。
"""


def test_preflight_doc_ref_red_names_section_token_and_fix(tmp_path: Path) -> None:
    """★ 钉子 1：文书里 `pipe-land/SKILL.md` 解析不到 ⇒ 退 1，报行点名 **changelog 段** +
    token + **可照抄的修法**（`skills/` 前缀）。"""
    repo = _mk_preflight_repo(tmp_path)
    _write(repo, "code/a.py", "X = 2\n")
    # 技能**真的在** `skills/pipe-land/SKILL.md`，文书只是写成了短路径 ⇒ 修法才有的可照抄
    _write(repo, "skills/pipe-land/SKILL.md", "# 技能\n")
    _write(repo, "gates/diag/_text_TG999.md", _TEXT_BAD_REF)

    done = _preflight(repo, "--task", "T-G999", "--tree", ".", "--allow", "code")

    out = _out(done)
    assert done.returncode == 1, out
    line = _item_line(out, "文书引用解析得到")
    assert line.lstrip().startswith("❌"), line
    assert "文书引用解析不到" in line, line
    assert "changelog 段" in line, line
    assert "pipe-land/SKILL.md" in line, line
    assert "skills/pipe-land/SKILL.md 才对" in line, line   # 判据 2：修法可照抄


def test_preflight_doc_ref_green_when_prefix_fixed(tmp_path: Path) -> None:
    """★ 钉子 2：同一个 token 改成 `skills/pipe-land/SKILL.md` ⇒ 该条转绿（其余照样绿）。"""
    repo = _mk_preflight_repo(tmp_path)
    _write(repo, "code/a.py", "X = 2\n")
    _write(repo, "skills/pipe-land/SKILL.md", "# 技能\n")
    _write(repo, "gates/diag/_text_TG999.md",
           _TEXT_BAD_REF.replace("`pipe-land/SKILL.md`", "`skills/pipe-land/SKILL.md`"))

    done = _preflight(repo, "--task", "T-G999", "--tree", ".", "--allow", "code")

    out = _out(done)
    assert done.returncode == 0, out
    line = _item_line(out, "文书引用解析得到")
    assert line.lstrip().startswith("✅"), line
    assert "1 条 .md 引用" in line, line


def test_preflight_doc_ref_skip_when_no_md(tmp_path: Path) -> None:
    """★ 钉子 3：文书里没有 `.md` 引用 ⇒ `[skip]`，**不拖红**（整趟仍退 0）。"""
    repo = _mk_preflight_repo(tmp_path)
    _write(repo, "code/a.py", "X = 2\n")

    done = _preflight(repo, "--task", "T-G999", "--tree", ".", "--allow", "code")

    out = _out(done)
    assert done.returncode == 0, out
    line = _item_line(out, "文书引用解析得到")
    assert "[skip]" in line and "没有 .md 引用" in line, line


def test_preflight_doc_ref_runs_without_card_or_task(tmp_path: Path) -> None:
    """★ 钉子 4：**不给 `--card` / `--task`** 也照跑（判据 5：这条不依赖卡号）——
    扫 `docs/changelog.d/*.md` 的片段，坏 token 照样被点名。"""
    repo = _mk_preflight_repo(tmp_path)
    _write(repo, "code/a.py", "X = 2\n")
    _write(repo, "docs/changelog.d/T-G999.md",
           "## 2026-10-02 · 片段\n\n- 短路径 `pipe-card/references/dispatch.md`\n")

    done = _preflight(repo, "--tree", ".", "--allow", "code")

    out = _out(done)
    line = _item_line(out, "文书引用解析得到")
    assert line.lstrip().startswith("❌"), f"没给 --task 就不跑这条了？\n{out}"
    assert "pipe-card/references/dispatch.md" in line, line


def test_md_ref_resolution_matches_check_layers(tmp_path: Path) -> None:
    """★ 交叉钉子：本条的三基准解析与**真** `scripts/check_layers.check_link_integrity` 同口径。

    同一棵合成树，两边对同一批 token 的判断必须**逐条一致**（相/不相都算数）——
    否则「复用判据」就成了一句空话（两边一漂，体检绿了门禁还红）。
    """
    spec = importlib.util.spec_from_file_location(
        "check_layers_under_test", ROOT / "scripts" / "check_layers.py")
    assert spec and spec.loader
    cl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cl)

    landing = _load_landing()
    tree = tmp_path / "tree"
    docs = tree / "docs"
    docs.mkdir(parents=True)
    (docs / "ok.md").write_text("# ok\n", encoding="utf-8")
    (tree / "skills" / "pipe-land").mkdir(parents=True)
    (tree / "skills" / "pipe-land" / "SKILL.md").write_text("# s\n", encoding="utf-8")
    tokens = ["ok.md", "skills/pipe-land/SKILL.md", "nope/missing.md",
              "pipe-land/SKILL.md", "own.md"]
    (docs / "own.md").write_text("# own\n", encoding="utf-8")
    (docs / "x.md").write_text(
        "".join(f"- `{t}`\n" for t in tokens), encoding="utf-8")

    problems, _notes, _checked = cl.check_link_integrity(root=tree)
    bad = {p.rsplit(" ", 1)[-1] for p in problems}
    assert "nope/missing.md" in bad and "pipe-land/SKILL.md" in bad, \
        f"合成树没造出断链，这条钉子没有意义：{problems}"
    for tok in tokens:
        mine = not landing.md_ref_resolves(tree, docs / "x.md", tok)
        assert mine == (tok in bad), (
            f"{tok!r}：体检判 {'断链' if mine else '解析得到'}，"
            f"check_layers 判 {'断链' if tok in bad else '解析得到'} —— 两边口径漂了")


# ======================================== 卡 E16（T-AG467）：门禁锁的三处静默，落地链这两处
#
# ① 等锁**有进度**：`gate_lock.py` 每 60s 打的 `[锁] 等门禁锁 Ns…` 必须出现在落地日志里
#    （原来 `capture_output` + `print(stdout[-400:])` 把它们全吞了，日志空白 28 分钟）。
# ② 体检**先说锁**：第一屏就把「本段锁 card / pid / 已持有秒数 / 持有者还活着吗 / 剩余租约」
#    说出来；判不了就明说 `not verified`。

#: 会「啰嗦」的锁桩：acquire 时打 40 行等锁进度（判据 = 每一行都要进落地日志）。
_GATE_LOCK_CHATTY = """import pathlib, sys

with pathlib.Path("gate_lock_calls.log").open("a", encoding="utf-8") as fh:
    fh.write(" ".join(sys.argv[1:]) + chr(10))
mk = pathlib.Path("lock.marker")
if "acquire" in sys.argv:
    for i in range(1, 41):
        print(f"[锁] 等门禁锁 {i}s… 本段锁被占：card=OTHER pid=1（合成）", flush=True)
    mk.write_text("locked", encoding="utf-8")
elif "release" in sys.argv and mk.exists():
    mk.unlink()
sys.exit(0)
"""


def test_lock_progress_is_streamed_into_the_landing_log(tmp_path: Path) -> None:
    """★ E16 钉子 6：拿锁那一步改成**流式** ⇒ 锁桩打的第一行也必须出现在落地输出里。

    旧码（`capture_output` + 只打尾部 400 字符）在 40 行 × ≈40 字符面前必红：
    第 1 行早就被截掉了 —— 那正是「日志空白 28 分钟」的机制。
    """
    repo = _mk_repo(tmp_path)
    _write(repo, "gates/diag/gate_lock.py", _GATE_LOCK_CHATTY)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "chatty gate_lock stub")

    done = _wand(repo)
    out = _out(done)

    assert "[锁] 等门禁锁 1s…" in out, f"等锁进度被吞了（没流式）：\n{out[-1500:]}"
    assert "[锁] 等门禁锁 40s…" in out, f"最后一行也没了：\n{out[-1500:]}"


def test_preflight_says_lock_first_with_liveness(tmp_path: Path) -> None:
    """★ E16 判据 3：体检**先说锁** —— 第一屏打出 card / pid / 已持有秒数 / 活着吗 / 剩余租约。

    造法：假仓库里放**真** `gate_lock.py`（读数就是它），再放一把「持有者 pid 不存在」的锁。
    断言 ① 锁那几行出现在「落地前置体检」标题**之前**；② 报出 `已不存在`（不是猜的）。
    """
    repo = _mk_preflight_repo(tmp_path)
    _write(repo, "code/a.py", "X = 2\n")
    gate_lock_src = ROOT / "gates" / "diag" / "gate_lock.py"
    _write(repo, "gates/diag/gate_lock.py", gate_lock_src.read_text(encoding="utf-8"))
    _write(repo, "tools/pool/no_window.py",
           (TOOLS / "pool" / "no_window.py").read_text(encoding="utf-8"))
    dead_pid = 4_000_004
    (repo / "gates" / "diag" / "gates-9477.lock").write_text(
        json.dumps({"card": "LOCKHOLDER", "pid": dead_pid, "base": 9477,
                    "lease": 10800, "at": "2026-10-25T00:00:00"}, ensure_ascii=False),
        encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "real gate_lock + a stale-by-pid lock")

    done = _preflight(repo, "--task", "T-G999", "--tree", ".", "--allow", "code",
                      env={**_ENV, "TF_GATE_PORT_BASE": "9477"})

    out = _out(done)
    lines = out.splitlines()
    head = next(i for i, ln in enumerate(lines) if "落地前置体检" in ln)
    lock_lines = [ln for ln in lines[:head] if ln.startswith("[锁]")]
    assert lock_lines, f"体检没有「先说锁」：\n{out}"
    blob = "\n".join(lock_lines)
    assert "LOCKHOLDER" in blob, blob
    assert str(dead_pid) in blob, blob
    assert "已持有" in blob and "剩余租约" in blob, blob
    assert "已不存在" in blob, f"持有者进程的读数不对（应是「已不存在」）：{blob}"
    assert "★ 本段" in blob, f"没标出哪把是本次要用的段：{blob}"


# ============================================ 卡 E3（T-AG445）：提交面算档 + 残留只 ignore
#
# ★ 域内/域外界线（如实）：E3 的 `required_profiles(..., source=)` 与 `.gitignore` 收残留
#   在本卡域内，两条钉子钉在这里；**payload 落进 `gates/last.json`** 那一半在
#   `scripts/run_gates.py`（不在 E28 的 8 文件域内）⇒ 这里钉的是**它的形状**
#   （`profiles_payload`），落地链接管时直接 `payload.update(...)` 即可。

def _load_domains() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "domains_under_test", ROOT / "gates" / "defs" / "domains.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_domains_profiles_payload_marks_committed_face() -> None:
    """★ E3 判据 1/5：`source="committed"` ⇒ payload 里 `profiles_source` **如实**写 committed。

    提交面 vs 工作区是**两个来源**（判据 5 要求各一条钉子）；这条钉提交面。
    """
    domains = _load_domains()
    payload = domains.profiles_payload(["tools/pool/landing.py", "docs/changelog.md"],
                                       source="committed")
    assert payload["profiles_source"] == "committed", payload
    assert payload["required_profiles"] == ["audit", "lang"], payload


def test_domains_profiles_payload_defaults_to_worktree() -> None:
    """★ E3 判据 1/5：不给 `source` ⇒ 老口径（工作区），且 payload 里写明 `worktree`。

    这条钉住「手工跑门禁行为不变」那一半：默认值一漂，所有老调用点的含义都会变。
    """
    domains = _load_domains()
    assert domains.required_profiles(["tools/x.py"]) == frozenset({"lang", "audit"})
    payload = domains.profiles_payload(["tools/x.py"])
    assert payload["profiles_source"] == "worktree", payload
    with pytest.raises(ValueError):
        domains.required_profiles(["tools/x.py"], source="guess")   # 来源不许猜


def test_gitignore_covers_worktree_residue(tmp_path: Path) -> None:
    """★ E3 判据 3：`blobs/`、`.dsh-probe/`、`.dsh-probedump-*.txt`、`gates/tia.json` 被忽略。

    判据问的是 **git 自己**（`git check-ignore`），不是读一遍 .gitignore 的文本 ——
    文本对不等于行为对（顺序 / `!` 例外都会改结果）。
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / ".gitignore").write_bytes((ROOT / ".gitignore").read_bytes())
    for rel in ("blobs/x.bin", ".dsh-probe/p.txt", ".dsh-probedump-1.txt",
                "gates/tia.json"):
        done = _git(repo, "check-ignore", "-q", "--", rel)
        assert done.returncode == 0, f"{rel} 没被忽略 ⇒ 又会被算进改动面：{_out(done)}"
    # 反例：真正的源文件不许被这条连坐（只 ignore 残留，不 ignore 代码）
    assert _git(repo, "check-ignore", "-q", "--", "tools/pool/landing.py").returncode == 1


def test_domains_derived_residue_does_not_force_full_profiles() -> None:
    """★ E3：被 `.gitignore` 收掉的**派生 / 残留**不算改动面 —— 不许把算档拖成三档全量；
    派生目录**之外**的改动照常算（`tools/` ⇒ lang+audit）。

    反例那一半同样要钉：判不出档、又**没被 ignore** 的路径 ⇒ 仍然 fail closed 到全量
    （宁可多跑，不许漏跑 —— 这不是「为了变绿放松判据」）。
    """
    domains = _load_domains()
    got = domains.required_profiles(
        ["blobs/x.bin", "export/old.md", ".dsh-probe/p.txt", ".dsh/skills/x",
         "tools/pool/landing.py"])
    assert got == frozenset({"lang", "audit"}), got
    # 反例：`weird/blob.bin` 不在 .gitignore 里 ⇒ 判不出档 ⇒ 全量（fail closed 不动）
    assert domains.required_profiles(["blobs/x.bin", "weird/blob.bin"]) \
        == domains.ALL_PROFILES


# ============================================ 卡 E5（T-AG447）：落地链接入合并队列
#
# 单写者段 = ④–⑦。钉子只钉**接入点**（纯状态机在 tests/test_pool_queue.py 里逐条钉）：
# ① 单笔落地 ⇒ 进队、位置 1/1、落地完出队（队列不许留残渣）；
# ② 前面有人 ⇒ **不许抢**（位置 2、等超时退 8、自己从队列摘掉）；
# ③ 排队期间主树前进 ⇒ 投机预检作废 ⇒ **重跑 ③″**（结果不许复用）。

def _queue_state(repo: Path) -> dict:
    p = repo / "gates" / "diag" / "merge-queue.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def test_landing_joins_queue_and_leaves_it_empty(tmp_path: Path) -> None:
    """★ 判据 1/3：单笔落地要进队（位置 1/1），ff 合流后**出队**（队列不许留残渣）。"""
    repo = _mk_repo(tmp_path)

    done = _wand(repo)
    out = _out(done)

    assert "=== ④′ 合并队列" in out, out[-1500:]
    assert "位置 1/1" in out, out[-1500:]
    st = _queue_state(repo)
    assert st.get("head") is None and st.get("waiting") == [], \
        f"落地完队列还有残渣（会堵死下一笔）：{st}"


def test_landing_refuses_to_cut_in_line(tmp_path: Path) -> None:
    """★ 判据 2（单写者）：前面已经有人 ⇒ 位置 2、等超时退 8，且**自己摘掉**不占位。"""
    repo = _mk_repo(tmp_path)
    (repo / "gates" / "diag" / "merge-queue.json").write_text(
        json.dumps({"head": {"task": "OTHER", "tree": ".wt/other", "base": "abc"},
                    "waiting": []}, ensure_ascii=False), encoding="utf-8")

    done = _wand(repo, "--queue-wait", "0.3")
    out = _out(done)

    assert done.returncode == 8, out[-1500:]
    assert "位置 2" in out, out[-1500:]
    assert "等队首超时" in out, out[-1500:]
    st = _queue_state(repo)
    assert st["head"]["task"] == "OTHER", f"别人的队首被抢了：{st}"
    assert not [e for e in st["waiting"] if e.get("task") == "T-G999"], \
        f"等超时的这一笔要自己摘掉：{st}"


def test_join_queue_reruns_speculative_preflight_when_main_moved(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture) -> None:
    """★ 判据 3：排队期间主树前进 ⇒ **投机预检作废**，③″ 必须重跑一次（不许复用）。"""
    repo = _mk_repo(tmp_path)
    monkeypatch.setenv("TF_MERGE_QUEUE", str(repo / "gates" / "diag" / "merge-queue.json"))

    calls: list[int] = []

    def _fake_fast(wt, env):          # noqa: ANN001 —— 只记「重跑了几次」
        calls.append(1)
        return True

    # 入队时读到 sha-old；轮到队首时主树已前进到 sha-new（= 前一笔刚 ff 合流）
    _heads = iter(["sha-old", "sha-new"])
    monkeypatch.setattr(_landing, "ROOT", repo)
    monkeypatch.setattr(_landing, "git", lambda *a, **k: next(_heads, "sha-new"))
    monkeypatch.setattr(_landing, "fast_preflight", _fake_fast)

    class _Args:
        tree = "."
        task = "T-G999"
        queue_wait = 1.0

    rc = _landing._join_merge_queue(_Args(), repo, {})
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "投机预检作废" in out, out
    assert len(calls) == 1, f"投机预检没重跑（结果被复用了）：{calls}"


def test_landing_records_base_drift_after_rebase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """★ 卡 E123 判据 6：⑦ rebase 之后**落门禁基点读数**（只补账，不重跑门禁）。

    造一次「主树前进两笔」：门禁在 G 上跑（卡树里的 `gates/last.json` 记着 `rev=G`），
    之后主树又落下两笔（一笔台账、一笔源码），卡树 rebase 上来 ⇒ 这一笔的父提交 = 主树新
    HEAD。读数要落在 `gates/diag/base_drift/<task>.json`，五个字段齐，`diff_paths` 由
    `git diff --name-only <gates_rev> <新 HEAD>^` **现算**。

    ★ 不断言「门禁重跑」—— 判据明写不许插重跑；也不断言这笔记账会不会把复核判红（那是
      复核器的判据，另有钉子）。
    """
    repo = _mk_repo(tmp_path)
    pen = _mk_pen(repo)
    base = _git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
    # 门禁是在 `base` 上跑的（卡树里那份产物这么写着）
    _write(pen, "gates/last.json", json.dumps({"rev": base, "ok": True}) + "\n")
    # 主树前进两笔：一笔只动台账，一笔动源码
    _write(repo, "docs/workbacklog.toml", "[cards]\n")
    _git(repo, "add", "--", "docs/workbacklog.toml")
    _git(repo, "commit", "-q", "-m", "docs(ledger): 台账前进一笔")
    _write(repo, "code/b.py", "Y = 2\n")
    _git(repo, "add", "--", "code/b.py")
    _git(repo, "commit", "-q", "-m", "feat: 源码前进一笔")
    main_tip = _git(repo, "rev-parse", "HEAD").stdout.strip()
    # 卡树提交 → rebase 到主树新 HEAD（= 收口链 ⑦ 那一步）
    _git(pen, "add", "-A")
    _git(pen, "commit", "-q", "-m", "feat: 这一笔")
    rebased = _git(pen, "rebase", main_tip)
    assert rebased.returncode == 0, rebased.stderr
    parent = _git(pen, "rev-parse", "HEAD^").stdout.strip()
    assert parent == main_tip

    mod = _load_landing()
    monkeypatch.setattr(mod, "ROOT", repo)
    out = mod.record_base_drift("T-G999", wt=pen, rebase_before_main=main_tip)

    assert out is not None, "门禁基点读数没落下"
    path = repo / "gates" / "diag" / "base_drift" / "T-G999.json"
    assert path.is_file(), f"读数没落在约定位置：{path}"
    body = json.loads(path.read_text(encoding="utf-8"))
    assert set(body) == {
        "gates_rev", "rebase_before_main", "rebase_after_head",
        "rebase_after_parent", "diff_paths",
    }, body
    assert body["gates_rev"] == base
    assert body["rebase_before_main"] == main_tip
    assert body["rebase_after_head"] == _git(pen, "rev-parse", "HEAD").stdout.strip()
    assert body["rebase_after_parent"] == parent
    assert sorted(body["diff_paths"]) == ["code/b.py", "docs/workbacklog.toml"], body


def test_record_base_drift_is_called_after_rebase_and_before_ff() -> None:
    """★ 判据 6 的顺序钉（源级）：落读数在「rebase 后 HEAD」之后、「merge --ff-only」之前。"""
    text = (TOOLS / "pool" / "landing.py").read_text(encoding="utf-8").replace("\r\n", "\n")
    call = text.find("record_base_drift(a.task, wt=wt, rebase_before_main=main_now)")
    rebase = text.find('print("  rebase 后 HEAD ="')
    ff = text.find('"merge", "--ff-only"')
    assert call > 0 and rebase > 0 and ff > 0, (call, rebase, ff)
    assert rebase < call < ff, f"落读数的位置不对：rebase={rebase} call={call} ff={ff}"
