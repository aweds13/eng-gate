"""五层对账审计：把 **git 提交 + 机器可读台账 + 门禁产物** 三者对起来。

用户要求（2026-09-18）：「每次干完上传 git，然后借 git 和文档一起去审计、同步进度」+
「**审计不通过就别提交**」。本脚本就是那道闸门（由 `scripts/run_gates.py` 调用）。

六项检查
  ① 提交挂了任务号    —— 读 `Task:` trailer（无卡开工即失败）
  ② 任务号已登记      —— 台账里必须有该条目
  ③ 声称 = 证据       —— `status=done` 的每条断言逐条实跑
  ④ 文档与代码同提交  —— 改了 `src/`，本提交必须同时改台账 + changelog + 交接/协议
  ⑤ 门禁有落盘产物    —— `Task:` 提交必须带与该提交一致的 `gates/last.json`
  ⑥ 进度可从 git 重建 —— 台账状态与 git 历史对账（漏登记 / 虚报）

豁免：台账 `[exceptions]` 逐条列出已知欠账，**每修一条删一条**，且会被打印出来，不许静默豁免。

用法
  python -X utf8 scripts/audit_progress.py              # 审计最后一次提交（提交前用）
  python -X utf8 scripts/audit_progress.py --all        # 只对账台账 + 重建进度（跳过单提交检查）
  python -X utf8 scripts/audit_progress.py --rev <sha>  # 审计指定提交
  python -X utf8 scripts/audit_progress.py --no-git     # 只查台账与断言（无 git 场景）
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs" / "traceability.toml"
GATES = ROOT / "gates" / "last.json"
DOCS_TOUCH = ("docs/traceability.toml", "docs/changelog.md")
CHECKPOINTS = ("复盘/长任务执行协议.md", "复盘/交接-重构进度.md")
SRC_PREFIXES = ("src/timeflow/", "src/web/")
VALID_STATUS = {"done", "partial", "todo", "deferred", "broken"}
OK, FAIL, WARN = "[OK ]", "[FAIL]", "[WARN]"


def git(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    return r.stdout.strip()


# ---------------------------------------------------------------- 仓库事实
def routes() -> set[str]:
    src = (ROOT / "src" / "timeflow" / "api" / "app.py").read_text(encoding="utf-8")
    return {
        f"{m.group(1).upper()} {m.group(2)}"
        for m in re.finditer(r'@app\.(get|post|patch|delete)\("([^"]+)"', src)
    }


def tables() -> set[str]:
    db = (ROOT / "src" / "timeflow" / "storage" / "db.py").read_text(encoding="utf-8")
    return set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", db))


def columns(table: str) -> set[str]:
    db = (ROOT / "src" / "timeflow" / "storage" / "db.py").read_text(encoding="utf-8")
    parts = db.split(f"CREATE TABLE IF NOT EXISTS {table} (", 1)
    if len(parts) < 2:
        return set()
    body = parts[1].split("\n        )", 1)[0]
    found = re.findall(r"^\s*(\w+)\s+TEXT|^\s*(\w+)\s+INTEGER", body, re.M)
    return {a or b for a, b in found}


def web_source() -> str:
    return (ROOT / "src" / "web" / "index.html").read_text(encoding="utf-8")


def declared_actions() -> set[str]:
    return set(re.findall(r'data-action="([a-z-]+)"', web_source()))


def registered_actions() -> set[str]:
    return set(re.findall(r"'([a-z-]+)':\s*(?:el\s*=>|\()", web_source().split("const ACTIONS")[1]))


def views() -> set[str]:
    m = re.search(r"const VIEWS=\[([^\]]*)\]", web_source())
    return {v.strip().strip("'") for v in m.group(1).split(",") if v.strip()} if m else set()


# ---------------------------------------------------------------- 断言求值
def eval_assertion(assertion: str) -> tuple[bool, str]:
    kind, _, rest = assertion.partition(":")
    if kind == "file":
        return (ROOT / rest).exists(), f"文件 {rest}"
    if kind == "text":
        path, _, pattern = rest.partition("::")
        p = ROOT / path
        if not p.exists():
            return False, f"文件不存在 {path}"
        body = p.read_text(encoding="utf-8")
        # 默认**字面包含**（断言里的 ( ) 等不该被当正则 —— 第一版就在这里崩过）；
        # 需要正则时显式写 text:路径::re:图案
        if pattern.startswith("re:"):
            return re.search(pattern[3:], body) is not None, f"{path} 正则 /{pattern[3:]}/"
        return pattern in body, f"{path} 含 {pattern!r}"
    if kind == "route":
        return rest in routes(), f"路由 {rest}"
    if kind == "table":
        return rest in tables(), f"表 {rest}"
    if kind == "column":
        table, _, col = rest.partition(".")
        return col in columns(table), f"列 {table}.{col}"
    if kind == "ui":
        key, _, val = rest.partition("=")
        if key == "data-action":
            ok = val in declared_actions() and val in registered_actions()
            return ok, f"界面动作 {val}"
        if key == "view":
            return val in views(), f"视图 {val}"
        return False, f"未知 ui 断言 {rest}"
    if kind == "test":
        return (ROOT / "tests" / rest).exists(), f"测试文件 {rest}"
    return False, f"未知断言类型 {kind}"


# ---------------------------------------------------------------- 台账检查
def check_shape(data: dict) -> list[str]:
    """台账自洽性 + 反向覆盖（规格条目 / 后端路由都不能漏登记）。"""
    errs: list[str] = []
    entries = data.get("entries", {})
    for eid, e in entries.items():
        status = e.get("status")
        if status not in VALID_STATUS:
            errs.append(f"{eid}: 非法状态 {status!r}")
        evidence = e.get("evidence", [])
        if status == "done" and not evidence:
            errs.append(f"{eid}: status=done 但没有任何证据断言")
        if status in {"partial", "todo", "deferred", "broken"} and not e.get("gaps"):
            errs.append(f"{eid}: status={status} 但没写 gaps（必须说明缺什么）")
        for item in evidence:
            if ":" not in item:
                errs.append(f"{eid}: 证据格式不对 {item!r}")
    sr_ids: set[str] = set()
    spec_files = list((ROOT / "docs" / "specification").rglob("*.md"))
    spec_files.append(ROOT / "docs" / "ACCEPTANCE.md")
    for path in spec_files:
        sr_ids |= set(re.findall(r"SR-(?:F\d+(?:\.\d+)?|NF\d+)", path.read_text(encoding="utf-8")))
    domain_headers = {f"SR-F{i}" for i in range(1, 11)}
    missing = sorted(sr_ids - set(entries) - domain_headers)
    if missing:
        errs.append(f"规格里有 {len(missing)} 条 SR 未登记台账：{missing}")
    cited = set()
    for e in entries.values():
        for item in e.get("evidence", []):
            m = re.match(r"route:(\S+ \S+)", item)
            if m:
                cited.add(m.group(1))
    acked = set(data.get("meta", {}).get("acknowledged_routes", []))
    exc = set(data.get("exceptions", {}))
    orphan = sorted(r for r in routes() if r not in cited and r not in acked and r not in exc)
    if orphan:
        errs.append(f"有 {len(orphan)} 条路由既没被台账引用、也没进 acknowledged：{orphan[:6]}")
    return errs


def audit_evidence(data: dict, exc: set[str]) -> tuple[list[str], list[str], dict[str, int]]:
    fails: list[str] = []
    exempted: list[str] = []
    counts: dict[str, int] = {}
    for eid, e in sorted(data.get("entries", {}).items()):
        status = str(e.get("status"))
        counts[status] = counts.get(status, 0) + 1
        if status != "done":
            continue
        for assertion in e.get("evidence", []):
            passed, desc = eval_assertion(assertion)
            if passed:
                continue
            line = f"{eid}（{e.get('title', '')}）断言不成立 → {desc} [{assertion}]"
            (exempted if eid in exc else fails).append(line)
    return fails, exempted, counts


# ---------------------------------------------------------------- git 检查
def commit_meta(rev: str) -> dict[str, str]:
    def trailer(key: str) -> str:
        out = git("log", "-1", f"--format=%(trailers:key={key},valueonly)", rev)
        return out.strip()

    return {"Task": trailer("Task"), "Refs": trailer("Refs"), "Gates": trailer("Gates")}


def changed_files(rev: str) -> list[str]:
    return [p for p in git("show", "--name-only", "--format=", rev).splitlines() if p.strip()]


def progress(data: dict) -> tuple[list[str], list[str]]:
    """台账 ↔ git：谁已提交却没更新台账（失败）/ 谁标了 done 却没提交（提示）。"""
    log = git("log", "--format=%h%x09%(trailers:key=Task,valueonly)", "HEAD")
    seen: dict[str, list[str]] = {}
    for line in log.splitlines():
        sha, _, task = line.partition("\t")
        if task.strip():
            seen.setdefault(task.strip(), []).append(sha)
    warn: list[str] = []
    fail: list[str] = []
    for eid, e in sorted(data.get("entries", {}).items()):
        status = e.get("status")
        if status == "done" and eid not in seen:
            warn.append(f"{eid}: 台账 done，但 git 里没有挂 Task:{eid} 的提交（多为老账）")
        if status in {"todo", "partial"} and eid in seen:
            shas = ",".join(seen[eid])
            fail.append(f"{eid}: 台账仍是 {status}，但提交 {shas} 挂了 Task:{eid} → 台账漏更新")
    return warn, fail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rev", default="HEAD")
    ap.add_argument("--all", action="store_true", help="只对账台账 + 重建进度")
    ap.add_argument("--no-git", action="store_true")
    args = ap.parse_args()

    with LEDGER.open("rb") as fh:
        data = tomllib.load(fh)
    entries = data.get("entries", {})
    exc_raw = data.get("exceptions", {})
    exc = set(exc_raw) if isinstance(exc_raw, dict) else set()
    print(f"=== 台账：{len(entries)} 条 / 豁免（已知欠账）：{len(exc)} 条 ===")
    for eid in sorted(exc):
        print(f"  {WARN} 豁免 {eid}: {entries.get(eid, {}).get('gaps', '（未写 gaps）')}")

    shape = check_shape(data)
    print("\n=== 台账结构自检 ===")
    if shape:
        for err in shape:
            print(f"  {FAIL} {err}")
    else:
        print(f"  {OK} 状态词表/证据格式/gaps/规格覆盖/路由覆盖 全部通过")

    fails, exempted, counts = audit_evidence(data, exc)
    print("\n=== ③ 声称 = 证据 ===")
    print("  状态分布：" + " / ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    for line in exempted:
        print(f"  {WARN} 已豁免 {line}")
    for line in fails:
        print(f"  {FAIL} {line}")
    if not fails:
        print(f"  {OK} 所有 status=done 的断言都成立（{counts.get('done', 0)} 条）")

    git_fails: list[str] = []
    if not args.no_git:
        rev = args.rev
        sha = git("rev-parse", "--short", rev)
        meta = commit_meta(rev)
        files = changed_files(rev)
        print(f"\n=== git 对账（{sha}）===")
        print(f"  Task:  {meta['Task'] or '（无）'}")
        print(f"  Refs:  {meta['Refs'] or '（无）'}")
        print(f"  Gates: {meta['Gates'] or '（无）'}")
        if not args.all:
            if not meta["Task"]:
                git_fails.append("提交没有 `Task:` trailer（无任务卡开工）")
            elif meta["Task"] not in entries:
                git_fails.append(f"`Task: {meta['Task']}` 不在台账里（做了没登记 / 编号写错）")
            if any(f.startswith(SRC_PREFIXES) for f in files):
                for need in DOCS_TOUCH:
                    if need not in files:
                        git_fails.append(f"改了源码但本提交没同步 {need}")
                if not any(f in files for f in CHECKPOINTS):
                    git_fails.append("改了源码但本提交没写 CHECKPOINT（协议或交接文档）")
            if meta["Task"]:
                if not GATES.exists():
                    git_fails.append("没有 gates/last.json（门禁未落盘）")
                else:
                    gate = json.loads(GATES.read_text(encoding="utf-8"))
                    # 为什么不用 rev/tree 校验（两个坑都实测踩过）：
                    #  ① tree 自指：产物自己在那棵树里，写入哈希会让树变化 → 永不相等；
                    #  ② rev 时序：门禁必须**提交前**跑，那时新提交还不存在 → rev 必然落后一次。
                    # 所以改成"时效"校验：产物必须由本轮（最近一次提交之后）跑出来。
                    if not gate.get("ok"):
                        git_fails.append("gates/last.json 里 ok=false（门禁没过）")
                    else:
                        at_raw = str(gate.get("at", ""))
                        last_commit_ts = git("log", "-1", "--format=%cI", rev)
                        try:
                            at = datetime.fromisoformat(at_raw).replace(tzinfo=None)
                            commit_at = datetime.fromisoformat(last_commit_ts).replace(tzinfo=None)
                        except ValueError:
                            git_fails.append(f"gates/last.json 的时间戳无法解析：{at_raw!r}")
                        else:
                            if at < commit_at - timedelta(seconds=5):
                                git_fails.append(
                                    f"门禁产物时间 {at_raw} 早于本次提交 {last_commit_ts}"
                                    "（不是这一版跑的，请重跑 scripts/run_gates.py 再提交）"
                                )
                if not meta["Gates"]:
                    git_fails.append("提交没有 `Gates:` trailer（没有门禁结果）")
        warn, wrong = progress(data)
        print("\n=== ⑥ 进度重建（台账 ↔ git）===")
        for line in wrong:
            print(f"  {FAIL} {line}")
            git_fails.append(line)
        if not wrong:
            print(f"  {OK} 没有「已提交但台账未更新」的条目")
        for line in warn:
            print(f"  {WARN} {line}")

    all_fails = shape + fails + git_fails
    print("\n" + "=" * 72)
    if all_fails:
        print(f"审计不通过：{len(all_fails)} 项失败（{len(exempted)} 项已豁免）")
        for line in all_fails:
            print(f"  - {line}")
        print("→ 按用户约定：**审计不通过不许提交**。修完或写进 exceptions 再提交。")
        return 1
    print(f"审计通过 ✅（豁免 {len(exempted)} 项已知欠账）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
