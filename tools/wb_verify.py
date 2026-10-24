r"""一屏核实（卡 078 · T-G173）—— 把主控自用的 `gates/diag/verify_i9.py` 参量化。

为什么有它：`verify_i9.py` 是 I-9 集成笔的**一次性**只读核实器（卡号、树名、十七条「活还在」
全写死在文件里）。外包链路的每一张卡其实需要同一套判据 —— 所以把它抽成**给任意树用**的一条命令：
传入 `--tree` 与白名单，它现读那一笔的骨架 / 门禁 / 台账 / 审计 / 越界 / wb_review，全部贴原始读数。

判据（一条一行，前面 `OK`/`FAIL`/`INFO`；**退出码 = FAIL 条数**，0 = 全过）：
    OK   提交骨架：HEAD <短sha> · 父 <短sha> · 脏 0 · trailer Task/Refs/Ledger/Gates = 1/1/1/1
    OK   门禁：ok=True · rev=<短sha>=父提交 · N 门（N 从门表现读，不写死）· exit_code 非零 0 道
         · not_run 0 道 · 复用 N 道
    OK   封存指纹：last.json.tree == 本笔提交【去掉 gates/**】的 tree（旧笔则 INFO 不核，见下）
    OK   台账：sync_counts --check <原文那一行>
    OK   审计：提交后 audit <原文那一行>
    OK   越界：<n> 个文件全在白名单 / FAIL 越界文件：[…]
    OK   wb_review：<末行原文>
    OK   既有文件：<只读，跳过>
    SUMMARY FAIL=<n> OK=<n>

★ 复用记录的读法（主控踩过的坑）：`last.json` 顶层的 `reused` **字典**，不是每道门自己的键。
★ 封存指纹的读法（T-G179）：`last.json.tree` 现在（`tree_scope="worktree-minus-gates"`）是
  "**除 `gates/**` 外**、即将提交的内容"的 tree 哈希 —— 一个**可复现的固定点**。
  复算**共用门禁自己那份实现**（`scripts/run_gates.py` 的 `tree_without_gates`，不在这里另写一套）。
  旧笔没有 `tree_scope` 字段 → 记 `INFO … 按旧口径不核`（那时它是"底座那棵树的哈希"，核不了，
  **不假装 OK**、也不算 FAIL）。
★ 只读：**不许** `git add/commit`、**不许**跑 `run_gates.py`、**不许**动锁。

用法：
    python -X utf8 tools/wb_verify.py --tree .wt/foo --expect-parent d842771 \
        --allow "复盘/*" --allow "tools/*" --allow "gates/*" --allow "docs/*"
    python -X utf8 tools/wb_verify.py --tree .        # 缺 --expect-parent 时用该树 HEAD^
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from pathlib import Path

TRAILER_KEYS = ("Task", "Refs", "Ledger", "Gates")


def _expected_scope(tree: Path) -> str:
    """封存指纹口径自述值的**唯一真源**（T-G179 / 卡 160）：`run_gates.TREE_SCOPE`（现读）。

    原来这里写死一个字面量 `EXPECT_SCOPE = "worktree-minus-gates"` —— 与门数一样，凡是写死的
    口径都是会漂的第二真源；改成按 `--tree` 指向的那棵树现读。读不到 → 回退字面量（此时
    `check_fingerprint` 反正会走"不核/复算失败"那条路，不静默放过）。
    """
    scripts = str(tree / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import run_gates  # noqa: PLC0415 —— 延迟到运行时按 --tree 的树 import
    try:
        return str(run_gates.TREE_SCOPE)
    except Exception:
        return "worktree-minus-gates"


class Screen:
    """收集行 + 计数（FAIL 条数就是退出码）。"""

    def __init__(self) -> None:
        self.fails = 0
        self.oks = 0

    def _emit(self, tag: str, msg: str) -> None:
        print(f"{tag:<5} {msg}", flush=True)

    def ok(self, msg: str) -> None:
        self.oks += 1
        self._emit("OK", msg)

    def bad(self, msg: str) -> None:
        self.fails += 1
        self._emit("FAIL", msg)

    def info(self, msg: str) -> None:
        self._emit("INFO", msg)


def _run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    done = subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def _git(cwd: Path, *args: str) -> str:
    rc, out = _run(["git", "-c", "core.quotepath=false", *args], cwd)
    return out.strip() if rc == 0 else ""


def expected_gate_names(
    tree: Path, profiles: list[str] | tuple[str, ...] | None = None
) -> tuple[list[str], str]:
    """该仓**当前应有**的门清单 —— 从门表现读（卡 160 · T-G260）。

    ★ **门数真源只有一处**：`<tree>/scripts/run_gates.py::build_jobs(quick=False, fast=False)`
      （全量那一趟）。原来这里写死 `EXPECT_GATES = 17`，加了第 18 道门（`invariants`）就得
      两处一起改 —— 凡是写死的数字都是会漂的第二真源（卡 147 已立同一条口径）。现在改成
      **按 `--tree` 指向的那棵树现读**（核的是那棵树的门表，不是本进程所在树的）。
    读不到（import 失败 / 门表坏了）→ `([], 原因)`：调用方据此**判红**（拿不准不放过）。

    ★ **分档门禁**（卡 A327 的 `--profiles auto`，卡 E24）：`gates/last.json` 记着这一趟真跑全了
      哪几档（`profiles_run`）。只跑 `audit+lang` 的那一趟**本来就只有 8 道门**，不是漏跑 ——
      所以传了 `profiles` 就按档派生期望集合；不传 / 传 `all` / 字段缺失（旧笔）仍是全量 19 道。
      未知档名 ⇒ 空集合 ⇒ 调用方判红（fail closed，别把「看不懂」当「都跑过了」）。
    """
    scripts = str(tree / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import run_gates  # noqa: PLC0415 —— 延迟到运行时按 --tree 的树 import
    try:
        names = [str(n) for n, _ in run_gates.build_jobs(False, False)]
    except Exception as exc:  # 读不到就如实说，别猜（"无法判断"优于猜）
        return [], f"读不到门表（{type(exc).__name__}: {exc}）"
    want = [str(p) for p in (profiles or []) if str(p).strip()]
    if not want or "all" in want:
        return names, f"run_gates.build_jobs(False, False)（{len(names)} 道）"
    keep: set[str] = set()
    unknown: list[str] = []
    for one in want:
        got = run_gates.GATE_PROFILES.get(one)
        if got is None:
            unknown.append(one)
            continue
        keep |= set(got)
    if unknown:
        return [], f"profiles_run 里有不认识的档 {unknown}"
    picked = [n for n in names if n in keep]
    return picked, f"last.json 记的是 {'+'.join(want)} 档（{len(picked)} 道）"


def _tree_without_gates(tree: Path, rev: str) -> str:
    """独立复算「封存指纹」：`<rev>` 的树去掉 `gates/**`。

    ★ 算法**共用门禁自己那份实现**（`<tree>/scripts/run_gates.py` 的 `tree_without_gates`），
    不在这里手写第二套切法 —— 手写第二套切法就是 080 那个假护栏的病根（卡 §1.3 点名）。
    按 `--tree` 指向的那棵树去 `import`（这样复算的是**那棵树**的实现，不是本进程所在树的）。
    """
    scripts = str(tree / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import run_gates  # noqa: PLC0415 —— 延迟到运行时按 --tree 的树 import
    return run_gates.tree_without_gates(tree, rev) or ""


def _last_nonempty(text: str) -> str:
    for ln in reversed(text.splitlines()):
        if ln.strip():
            return ln.strip()
    return ""


def _first_nonempty(text: str) -> str:
    for ln in text.splitlines():
        if ln.strip():
            return ln.strip()
    return ""


def check_skeleton(s: Screen, tree: Path, expect_parent: str) -> str:
    sha = _git(tree, "rev-parse", "--short", "HEAD")
    parent = _git(tree, "rev-parse", "--short", "HEAD^")
    if not sha:
        s.bad("提交骨架：取不到 HEAD（--tree 指对了吗）")
        return ""
    dirty = [ln for ln in _git(tree, "status", "--porcelain", "-uno").splitlines() if ln.strip()]
    body = _git(tree, "log", "-1", "--format=%B", sha)
    counts = {k: sum(1 for ln in body.splitlines() if ln.startswith(f"{k}:"))
              for k in TRAILER_KEYS}
    tail = "/".join(str(counts[k]) for k in TRAILER_KEYS)
    wrong = [k for k in TRAILER_KEYS if counts[k] != 1]
    detail = f"HEAD {sha} · 父 {parent} · 脏 {len(dirty)} · trailer Task/Refs/Ledger/Gates = {tail}"
    problems: list[str] = []
    if wrong:
        problems.append(f"trailer 不是各一条：{wrong}")
    if dirty:
        problems.append(f"工作区脏（{len(dirty)} 个未提交改动）")
    if expect_parent and parent != expect_parent:
        detail += f"（≠ --expect-parent {expect_parent}）"
        problems.append("父提交 != --expect-parent")
    if problems:
        s.bad(f"提交骨架：{detail} —— {'；'.join(problems)}")
    else:
        s.ok(f"提交骨架：{detail}")
    return parent


def check_gates(s: Screen, tree: Path, parent: str) -> None:
    raw = _git(tree, "show", "HEAD:gates/last.json")
    if not raw:
        s.bad("门禁：这一笔里没有 gates/last.json（门禁产物没跟着提交）")
        return
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        s.bad("门禁：gates/last.json 不是合法 JSON")
        return
    gates = payload.get("gates", [])
    nonzero = [g.get("name") for g in gates if g.get("exit_code") != 0]
    not_run = payload.get("not_run", [])
    reused = payload.get("reused", {})
    rev = str(payload.get("rev") or "")
    rev_short = rev[:len(parent)] if parent else rev
    rev_ok = bool(rev) and parent.startswith(rev)
    # ★ 门数**从门表现读**（不是写死 17）—— 见 `expected_gate_names()`。
    # ★ 分档（卡 E24）：`profiles_run` 说这一趟只跑了哪几档，期望集合就按那几档算；
    #   字段缺失（旧笔）⇒ 仍按全量 19 道核。
    ran = [str(x) for x in (payload.get("profiles_run") or [])]
    expected, source = expected_gate_names(tree, ran)
    got = [str(g.get("name")) for g in gates if isinstance(g, dict)]
    missing = [n for n in expected if n not in got]
    extra = [n for n in got if n not in expected]
    detail = (f"ok={payload.get('ok')} · rev={rev_short}"
              f"{'=父提交' if rev_ok else '≠' + parent} · {len(gates)} 门"
              f"（应有 {len(expected) if expected else '?'}，{source}）"
              f" · exit_code 非零 {len(nonzero)} 道 · not_run {len(not_run)} 道"
              f" · 复用 {(len(reused) if isinstance(reused, dict) else '?')} 道")
    problems: list[str] = []
    if payload.get("ok") is not True:
        problems.append("ok 不是 True")
    if not rev_ok:
        problems.append("rev != 父提交（一次门禁跑完提交两笔？第二笔没验过）")
    if not expected:
        problems.append(f"读不到应有的门数（{source}）—— 拿不准不放过")
    elif missing or extra:
        problems.append(f"门数/门名对不上（应有 {len(expected)} 道，来自 {source}）："
                        f"少 {missing}；多 {extra}")
    if nonzero:
        problems.append(f"有门没过：{nonzero}")
    if not_run:
        problems.append(f"有门没跑：{not_run}")
    msg = f"门禁：{detail}"
    if problems:
        msg += " —— " + "；".join(problems)
    (s.bad if problems else s.ok)(msg)


def check_fingerprint(s: Screen, tree: Path, short_sha: str) -> None:
    """封存指纹独立复算（T-G179 §1.3）：`last.json.tree` == 本笔提交【去掉 `gates/**`】的 tree。

    旧笔（`last.json` 没有 `tree_scope` 字段）→ 记 `INFO … 按旧口径不核`：口径自述值从门表现读
    （`_expected_scope`）。那时这一列记的是
    "底座那棵树的哈希"（worktree 回退 + 自指两个洞），核不了 —— **既不假装 OK，也不算 FAIL**。
    """
    raw = _git(tree, "show", "HEAD:gates/last.json")
    if not raw:
        s.bad("封存指纹：这一笔里没有 gates/last.json，无从复算")
        return
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        s.bad("封存指纹：gates/last.json 不是合法 JSON")
        return
    recorded = str(payload.get("tree") or "")
    if payload.get("tree_scope") != _expected_scope(tree):
        s.info(f"封存指纹：{short_sha[:12]} 早于本卡，按旧口径不核"
               f"（无 tree_scope，旧值 {recorded[:12] or '?'} 是底座那棵树的哈希）")
        return
    calc = _tree_without_gates(tree, "HEAD")
    if calc and calc == recorded:
        s.ok(f"封存指纹：last.json.tree == 本笔提交【去掉 gates/**】的 tree（{calc[:12]}）")
    else:
        s.bad(f"封存指纹：last.json.tree={recorded[:12] or '?'} ≠ 复算"
              f"{calc[:12] if calc else '(复算失败)'} —— 指纹对不上")


def check_ledger(s: Screen, tree: Path) -> None:
    rc, out = _run([sys.executable, "-X", "utf8", "tools/sync_counts.py", "--check"], tree)
    line = _first_nonempty(out) or "(没有输出)"
    (s.bad if rc != 0 else s.ok)(f"台账：sync_counts --check {line}")


def check_audit(s: Screen, tree: Path) -> None:
    rc, out = _run([sys.executable, "-X", "utf8", "scripts/audit_progress.py"], tree)
    line = _last_nonempty(out) or "(没有输出)"
    (s.bad if rc != 0 else s.ok)(f"审计：提交后 audit {line}")


def check_files(s: Screen, tree: Path, allow: list[str]) -> None:
    files = [f for f in _git(tree, "show", "--name-only", "--format=", "HEAD").splitlines()
             if f.strip()]
    if not allow:
        s.info("越界：未给 --allow 白名单 → 跳过（只读核实，不改文件）")
        return
    outside = [f for f in files if not any(fnmatch.fnmatch(f, pat) for pat in allow)]
    if outside:
        s.bad(f"越界：{len(files)} 文件里 {len(outside)} 个不在白名单：{outside[:8]}")
    else:
        s.ok(f"越界：{len(files)} 个文件全在白名单")


def check_wb_review(s: Screen, tree: Path, allow: list[str]) -> None:
    if not allow:
        s.info("wb_review：未给 --allow 白名单 → 跳过")
        return
    cmd = [sys.executable, "-X", "utf8", "tools/wb_review.py", "--rev", "HEAD"]
    for pat in allow:
        cmd += ["--allow", pat]
    rc, out = _run(cmd, tree)
    line = _last_nonempty(out) or "(没有输出)"
    (s.bad if rc != 0 else s.ok)(f"wb_review：{line}")


def main() -> int:
    ap = argparse.ArgumentParser(description="一屏核实（卡 078 · T-G173）：这一笔算不算数")
    ap.add_argument("--tree", default=".", help="要看的那棵树（默认 .）")
    ap.add_argument("--expect-parent", default="", help="期望的父提交（缺省 = 该树 HEAD^）")
    ap.add_argument("--allow", action="append", default=None, help="白名单 glob（可重复）")
    args = ap.parse_args()

    tree = Path(args.tree).resolve()
    allow = args.allow or []
    s = Screen()
    if not (tree / ".git").exists():
        print(f"FAIL  --tree 不是 git 工作树：{tree}", flush=True)
        print("SUMMARY FAIL=1 OK=0", flush=True)
        return 1

    parent = check_skeleton(s, tree, args.expect_parent)
    if parent:
        check_gates(s, tree, parent)
    check_fingerprint(s, tree, _git(tree, "rev-parse", "--short", "HEAD"))
    check_ledger(s, tree)
    check_audit(s, tree)
    check_files(s, tree, allow)
    check_wb_review(s, tree, allow)
    s.ok("既有文件：只读，跳过")
    print(f"SUMMARY FAIL={s.fails} OK={s.oks}", flush=True)
    return s.fails


if __name__ == "__main__":
    raise SystemExit(main())
