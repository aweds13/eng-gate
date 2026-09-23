"""跑质量门并**落盘结果**（`gates/last.json`），供 `scripts/audit_progress.py` 核对。

为什么要落盘：以前"pytest 284 passed"只是我在报告里打的一行字，**没人能验证**。
现在门禁由脚本执行、结果结构化写到 `gates/last.json` 并随代码提交 ——
提交里的 `Gates:` trailer 就有产物支撑，换个人/换个窗口复跑也能得到同样判断。

用法
    python -X utf8 scripts/run_gates.py            # 全套（含真机脚本）
    python -X utf8 scripts/run_gates.py --quick    # 跳过真机脚本（只跑 pytest/ruff/mypy/护栏/审计）
    python -X utf8 scripts/run_gates.py --serial   # pytest 单进程（对照并行下的偶发失败）

pytest 会**并行**跑（装了 `pytest-xdist` 时 `-n auto`）：用例之间没有共享状态（各自 tmp 库 +
各自进程内的事实总线），而每个用例都要起真 app + 真库 —— 串行是这里唯一的瓶颈。
覆盖率照旧判 70% 那道门（pytest-cov 会合并各 worker 的数据）。

约定（与用户确认）：**门禁或审计任一不通过 → 退出码非零 → 不许提交**。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATES = ROOT / "gates" / "last.json"
PY = sys.executable

COMMON = [
    ("pytest", []),                # 占位：按有没有 pytest-xdist 决定并行/串行（见 pytest_cmd）
    # 验收层只跑 2 个用例，必须关掉全局 addopts 里的覆盖率门，否则"覆盖率不达标"会误判验收失败
    ("acceptance", [PY, "-m", "pytest", "-m", "acceptance", "--no-cov"]),
    ("ruff", [PY, "-m", "ruff", "check", "src/", "tests/", "scripts/", "tools/", "examples/"]),
    ("mypy", [PY, "-m", "mypy", "src/"]),
    ("check_layers", [PY, "-X", "utf8", "scripts/check_layers.py"]),
    ("check_layers_selftest", [PY, "-X", "utf8", "scripts/test_check_layers.py"]),
    # 对比度审美门（T-G27）：令牌层的 WCAG 对比度**棘轮** —— 已登记的 18 条欠账不算通过，
    # 但"没登记过的新欠账"和"比登记值更差"会 FAIL。为什么是棘轮而不是硬门、怎么收紧成硬门，
    # 见 `tools/contrast_audit.py` 的模块 docstring 与 `复盘/审美门-对比度-T-G27.md`。
    ("contrast", [PY, "-X", "utf8", "tools/contrast_audit.py", "--check"]),
    # 风格一致性体检（T-G29）：「融洽」里**能机器判**的那一半 —— 同形状重复 / 一次性裸值 /
    # 缺 :hover·:focus-visible / 动效越界。它只证明「体系里没有新的破例」，**不证明好看**。
    ("style", [PY, "-X", "utf8", "tools/style_audit.py", "--check"]),
    ("ui_dom_probe", []),          # 占位：下面按 node 是否可用来填
    ("audit", [PY, "-X", "utf8", "scripts/audit_progress.py", "--all"]),
    # 台账↔规格 标题对账（T-D2）：`--check` 一发现「确定错位」或「无规格对应的 SR 卡」就退 1。
    # 2026-09-20 校正前它挂的是"信息性"（blocking=false）—— 因为台账里 F/NF 两层编号错位还没修，
    # 一接进来就会 FAIL。T-D1 校正完（见 `复盘/台账编号校正-方案A落地.md`）后转正为阻断项。
    ("audit_titles", [PY, "-X", "utf8", "scripts/audit_titles.py", "--check"]),
]
REAL = [
    ("lf1_live", [PY, "-X", "utf8", "tools/lf1_live_check.py"]),
    ("web_live", [PY, "-X", "utf8", "tools/web_live_check.py"]),
]
# 信息性检查（只报告、不阻断）—— 当前为空：`audit_titles` 已转正为阻断项（T-D2 收口）。
INFO_GATES: list[tuple[str, list[str]]] = []
SUCCESS_HINTS = ("passed", "failed", "error", "PASS", "Success", "checks passed", "OK")


def dom_probe_cmd() -> list[str] | None:
    """假 DOM 渲染探针：真跑 9 个视图。node 不在就跳过（不谎报通过）。"""
    node = shutil.which("node")
    return [node, str(ROOT / "tools" / "ui_dom_probe.mjs")] if node else None


def xdist_available() -> bool:
    """装了 `pytest-xdist` 吗？没装就串行跑 —— **不谎报**，也不因为缺插件把门禁弄红。"""
    probe = subprocess.run(
        [PY, "-c", "import xdist"], capture_output=True, text=True, check=False
    )
    return probe.returncode == 0


def pytest_cmd(serial: bool = False) -> list[str]:
    """pytest 那条命令：装了 xdist 就 `-n auto` 并行，否则串行。

    为什么可以并行（T-G7 实测的结论）：每个用例都起**真 app + 真库**（单次 `create_app()` ≈ 190ms、
    `connect + 迁移` ≈ 26ms），757 个用例串行要 3~4 分钟，而**用例之间没有共享状态** ——
    各自 `tmp_path` 一个库、各自进程内的 facts 总线，所以这是"安全的那一类提速"。
    覆盖率不受影响：pytest-cov 会把各 worker 的数据合并后，再判 `--cov-fail-under=70`。
    `--serial` 是给"并行下偶发失败"用的对照跑法（同一条命令、单进程）。
    """
    cmd = [PY, "-m", "pytest"]
    if not serial and xdist_available():
        cmd += ["-n", "auto"]
    return cmd


def env() -> dict[str, str]:
    e = dict(os.environ)
    shim = str(ROOT / "tools" / "sandbox_shim")
    e["PYTHONPATH"] = shim + (os.pathsep + e["PYTHONPATH"] if e.get("PYTHONPATH") else "")
    return e


def summarize(out: str) -> str:
    """抓一行结论（供 trailer 用）。

    注意：Windows 命令输出里常有中文警告，直接取"最后一行含关键词"会抓到 ResourceWarning
    （第一版就抓错了）。所以优先匹配测试框架的**汇总行**，并跳过各类 warning。
    """
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    summary_re = re.compile(r"\d+\s+(passed|failed|error|deselected)|no issues found|checks passed|"
                            r"LAYER CHECKS|SELF-TEST|PASS（|审计通过|OK \]")
    for line in reversed(lines):
        if "Warning" in line or line.startswith("ResourceWarning"):
            continue
        if summary_re.search(line):
            return line[:160]
    for line in reversed(lines):
        if "Warning" in line:
            continue
        if any(k in line for k in SUCCESS_HINTS):
            return line[:160]
    return lines[-1][:160] if lines else ""


def staged_tree() -> str:
    """把"即将提交的内容"（索引 + 工作区）写成一个临时 tree，返回它的哈希。

    为什么不能用 HEAD 的 tree：门禁在**提交前**跑，那时 HEAD 还是上一次提交。
    工作树在提交前后一致，但工作区可能还有未 add 的改动，所以用 `git add -A` 到临时索引后
    `git write-tree` 得到"这次要提交的那棵树"——它与最终提交的 tree 必然相同。
    临时索引放在 `.git/` 下的独立文件里，不动用户真正的索引。
    """
    tmp_index = ROOT / ".git" / "dsh_gates_index"
    if tmp_index.exists():
        tmp_index.unlink()
    env_with_index = dict(os.environ)
    env_with_index["GIT_INDEX_FILE"] = str(tmp_index)
    read = subprocess.run(
        ["git", "read-tree", "HEAD"], cwd=ROOT, env=env_with_index,
        capture_output=True, text=True, check=False,
    )
    if read.returncode != 0:
        return git("rev-parse", "HEAD^{tree}")
    subprocess.run(
        ["git", "add", "-A"], cwd=ROOT, env=env_with_index,
        capture_output=True, text=True, check=False,
    )
    written = subprocess.run(
        ["git", "write-tree"], cwd=ROOT, env=env_with_index,
        capture_output=True, text=True, check=False,
    )
    if tmp_index.exists():
        tmp_index.unlink()
    tree = written.stdout.strip()
    return tree or git("rev-parse", "HEAD^{tree}")


def git(*args: str) -> str:
    # core.quotepath=false：否则 git 把中文路径输出成八进制转义（\345\244\215 这种），
    # 于是"复盘/xxx.md 有没有一起改"这类判断会永远为假（实测踩到，等于中文文档的同步检查失效）。
    r = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    return r.stdout.strip()


def docs_sync_precheck() -> tuple[bool, list[str]]:
    """④ 的前置检查：改了源码就必须同时改台账/changelog/CHECKPOINT（**提交前**就发现）。"""
    changed = set(git("status", "--porcelain").split())
    changed |= set(git("diff", "--cached", "--name-only").split())
    if not any(p.startswith(("src/timeflow/", "src/web/")) for p in changed):
        return True, []
    missing = [n for n in ("docs/traceability.toml", "docs/changelog.md") if n not in changed]
    if not any(p in changed for p in ("复盘/长任务执行协议.md", "复盘/交接-重构进度.md")):
        missing.append("复盘/长任务执行协议.md（或 交接-重构进度.md）")
    return not missing, missing


def seal() -> int:
    """封存：只把 `gates/last.json` 里的 tree 更新为"含本文件自身的最新工作树"。

    为什么需要（自指问题，实测踩到）：`gates/last.json` **本身也是被提交的文件**。
    第一次跑门禁时它被写进工作区，工作树随之改变 → 与刚算出的 tree 不再相等 →
    提交后审计发现"门禁产物与提交不一致"。本步骤在正式提交前把 tree 重算一次即可收敛
    （只改一个字段，不重跑测试）。
    """
    if not GATES.exists():
        print("[FAIL] 还没有 gates/last.json，先跑一次门禁")
        return 1
    payload = json.loads(GATES.read_text(encoding="utf-8"))
    if not payload.get("ok"):
        print("[FAIL] gates/last.json 里 ok=false，封存没有意义（先让门禁通过）")
        return 1
    old = payload.get("tree", "")
    payload["tree"] = staged_tree()
    payload["sealed_at"] = datetime.now().isoformat(timespec="seconds")
    GATES.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"[封存] gates/last.json tree: {old[:12]} → {payload['tree'][:12]}")
    print("[提示] 现在 `git add gates/last.json && git commit` 后，产物与提交的 tree 会一致")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--serial", action="store_true", help="pytest 单进程跑（对照并行下的偶发失败）")
    ap.add_argument("--seal", action="store_true", help="提交前封存：只更新 tree 字段")
    args = ap.parse_args()
    if args.seal:
        return seal()

    ok_docs, missing = docs_sync_precheck()
    print("=== ④ 文档与代码同提交（提交前检查）===")
    if ok_docs:
        print("  [OK ] 源码有改动时，台账/changelog/CHECKPOINT 都在改动清单里（或本轮没改源码）")
    else:
        print(f"  [FAIL] 改了源码但还没同步：{missing}")

    if args.serial:
        mode = "串行（--serial）"
    elif xdist_available():
        mode = "并行（pytest-xdist，-n auto）"
    else:
        mode = "串行（环境里没装 pytest-xdist）"
    print(f"=== pytest 跑法：{mode} ===")

    results: list[dict[str, object]] = []
    jobs = COMMON + ([] if args.quick else REAL)
    for name, cmd in jobs:
        if name == "ui_dom_probe":
            filled = dom_probe_cmd()
            if filled is None:
                print("[WARN] ui_dom_probe        跳过：环境里没有 node（未验证，不算通过）")
                continue
            cmd = filled
        elif name == "pytest":
            cmd = pytest_cmd(serial=args.serial)
        t0 = time.time()
        # errors="replace"：Windows 下子进程输出可能是 GBK/混合编码，不能让门禁脚本自己因解码崩掉
        proc = subprocess.run(
            cmd, cwd=ROOT, env=env(), capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        item: dict[str, object] = {
            "name": name,
            "exit_code": proc.returncode,
            "seconds": round(time.time() - t0, 2),
            "summary": summarize(out),
        }
        results.append(item)
        mark = "[OK ]" if proc.returncode == 0 else "[FAIL]"
        print(f"{mark} {name:<22} exit={proc.returncode}  {item['seconds']}s  {item['summary']}")

    # 信息性检查：只报告、不阻断（blocking=False，不计进 ok）
    for name, cmd in ([] if args.quick else INFO_GATES):
        t0 = time.time()
        proc = subprocess.run(
            cmd, cwd=ROOT, env=env(), capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        tail = [ln.strip() for ln in out.splitlines() if ln.strip()]
        summary = next(
            (ln[:160] for ln in reversed(tail) if ln.startswith("共 ") or "全部对得上" in ln), ""
        )
        summary = summary or (tail[-1][:160] if tail else "")
        item = {
            "name": name,
            "exit_code": proc.returncode,
            "seconds": round(time.time() - t0, 2),
            "summary": summary,
            "blocking": False,
            "note": "信息性：台账↔规格 标题对账；T-D1 完成后改成阻断项（audit_titles.py --check）",
        }
        results.append(item)
        mark = "[OK ]" if proc.returncode == 0 else "[WARN]"
        print(f"{mark} {name:<22} exit={proc.returncode}  {item['seconds']}s  {summary}（不阻断）")

    blocking = [r for r in results if r.get("blocking", True)]
    ok = ok_docs and all(int(str(r["exit_code"])) == 0 for r in blocking)
    passed = [r for r in blocking if int(str(r["exit_code"])) == 0]
    payload = {
        "rev": git("rev-parse", "--short", "HEAD"),
        # 注意：**不要**把 tree 当"这一版代码"的凭据 —— gates/last.json 自己也在那棵树里，
        # 写入哈希会让树变化（自指悖论，实测踩到）。这里留着 tree 只作参考，审计不看它。
        "tree": staged_tree(),
        "parent": git("rev-parse", "--short", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(git("status", "--porcelain")),
        "at": datetime.now().isoformat(timespec="seconds"),
        "quick": args.quick,
        "docs_sync_ok": ok_docs,
        "docs_sync_missing": missing,
        "ok": ok,
        "gates": results,
        "trailer": "; ".join(f"{r['name']} {r['summary']}" for r in passed) or "（无通过项）",
    }
    GATES.parent.mkdir(parents=True, exist_ok=True)
    GATES.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"\n[落盘] gates/last.json  ok={ok}  rev={payload['rev']}")
    print(f"[建议 trailer] Gates: {str(payload['trailer'])[:200]}")
    if not ok:
        print("\n质量门或文档同步未通过 —— **不许提交**（用户约定）。")
        return 1
    print("\n质量门 + 文档同步通过 ✅（下一步：commit 并带上 Task:/Refs:/Gates: trailer）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
