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
    # core.quotepath=false：否则中文路径会变成八进制转义，凡是"文件名比对"的判断都会失效
    # （run_gates 的文档同步检查实测踩过这个坑）。
    r = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    return r.stdout.strip()


# ---------------------------------------------------------------- 仓库事实
def routes() -> set[str]:
    src = (ROOT / "src" / "timeflow" / "api" / "app.py").read_text(encoding="utf-8")
    return {
        f"{m.group(1).upper()} {m.group(2)}"
        for m in re.finditer(r'@app\.(get|post|patch|delete|put)\("([^"]+)"', src)
    }


# 交接文档里那行分布（`台账进度：done a / partial b / todo c / deferred d（共 N 条）`）
_HANDOFF_NUM = re.compile(
    r"台账进度：\s*done\s*(\d+)\s*/\s*partial\s*(\d+)\s*/\s*todo\s*(\d+)"
    r"\s*/\s*deferred\s*(\d+)\s*（共\s*(\d+)\s*条"
)


def check_handoff_numbers(counts: dict[str, int], total: int) -> list[str]:
    """交接文档里那行「台账进度：done a / partial b / …」必须与台账**算出来的**一致。

    为什么要查：这行数字一直是**手写**的，而手写就会漂 —— 本轮真漂过一次
    （T-G10 那次漏算了 SR-NF17 的 partial→done，写成 124/7/5/4，实际是 126/6/5/4）。
    文档里写错数字属于"文档失真"，机器能查的别靠人眼。
    拿不准就跳过：**找不到那行不算失败**（宁可漏查，也别因为改了措辞就挡提交）。
    """
    fails: list[str] = []
    for name in CHECKPOINTS:
        path = ROOT / name
        if not path.exists():
            continue
        m = _HANDOFF_NUM.search(path.read_text(encoding="utf-8"))
        if not m:
            continue
        want = {
            "done": counts.get("done", 0), "partial": counts.get("partial", 0),
            "todo": counts.get("todo", 0), "deferred": counts.get("deferred", 0),
        }
        keys = ("done", "partial", "todo", "deferred")
        got = dict(zip(keys, (int(x) for x in m.groups()[:4]), strict=True))
        got_total = int(m.group(5))
        if got != want or got_total != total:
            fails.append(
                f"{name} 里写的分布对不上台账：写的是 "
                + " / ".join(f"{k}={v}" for k, v in got.items()) + f"（共 {got_total} 条），"
                + "实际是 " + " / ".join(f"{k}={v}" for k, v in want.items()) + f"（共 {total} 条）"
            )
    return fails


def tables() -> set[str]:
    db = (ROOT / "src" / "timeflow" / "storage" / "db.py").read_text(encoding="utf-8")
    return set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", db))


def columns(table: str) -> set[str]:
    """表里有哪些列 —— 建表语句里的 + **后续迁移 ALTER TABLE 加的**。

    为什么要把 ALTER 也算进来：加列的迁移（v6 的 `note`、v7 的 `priority`、v8 的 `flagged`、
    v9 的 `attach`）不会回写 v1 的历史建表语句，只看 `CREATE TABLE` 会把这些**真实存在的列**
    判成"没有列"，于是 `column:` 断言永远不成立（第一版就只认建表语句）。
    加列有两种写法，两种都要认：
      ① 直接写 `ALTER TABLE <表> ADD COLUMN <列>`；
      ② 用 `_add_column_if_missing(conn, "<表>", "<列>", ...)` 这个幂等小工具（列名在参数里）。
    """
    db = (ROOT / "src" / "timeflow" / "storage" / "db.py").read_text(encoding="utf-8")
    found: set[str] = set()
    parts = db.split(f"CREATE TABLE IF NOT EXISTS {table} (", 1)
    if len(parts) >= 2:
        body = parts[1].split("\n        )", 1)[0]
        col_re = r"^\s*(\w+)\s+TEXT|^\s*(\w+)\s+INTEGER"
        found |= {a or b for a, b in re.findall(col_re, body, re.M)}
    found |= set(re.findall(rf"ALTER TABLE {table} ADD COLUMN (\w+)", db))
    for m in re.finditer(
        r'_add_column_if_missing\(\s*conn,\s*"(\w+)",\s*"(\w+)"', db
    ):
        if m.group(1) == table:
            found.add(m.group(2))
    return found


def web_source() -> str:
    return (ROOT / "src" / "web" / "index.html").read_text(encoding="utf-8")


def declared_actions(attr: str = "data-action") -> set[str]:
    """页面里声明过的动作（三种触发属性**共用一张 ACTIONS 注册表**）：
    `data-action`（点击）/ `data-enter`（回车）/ `data-change`（下拉·开关·日期框）。"""
    return set(re.findall(rf'{attr}="([a-z-]+)"', web_source()))


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
        if key in ("data-action", "data-enter", "data-change"):
            # 三种触发属性共用一张注册表（R2 事件委托）：被引用 + 已注册，缺一不可。
            # 为什么三种都要能断言：界面里"改一下就落库"的控件（下拉/日期框）走 data-change，
            # 只认 data-action 的话，这类交互在台账里**没法如实登记**。
            ok = val in declared_actions(key) and val in registered_actions()
            return ok, f"界面动作 {key}={val}"
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
    # 编号规则 A（2026-09-20）：一条规格被拆成多张卡时加小写后缀（`SR-F1.1a`），
    # 后缀卡算**同一个规格条目** —— 所以覆盖检查按**去掉后缀的基号**比。
    def _base(eid: str) -> str:
        m = re.match(r"^(SR-(?:F\d+(?:\.\d+)?|NF\d+))[a-z]$", eid)
        return m.group(1) if m else eid

    entry_bases = {_base(e) for e in entries}
    missing = sorted(sr_ids - entry_bases - domain_headers)
    if missing:
        errs.append(f"规格里有 {len(missing)} 条 SR 未登记台账：{missing}")
    # 反向：台账里不许出现规格没有的 `SR-*` 编号（自造卡请用 T-*/STEP-*/OP-*）
    unmapped = sorted(e for e in entries if e.startswith("SR-") and _base(e) not in sr_ids)
    if unmapped:
        errs.append(
            f"台账有 {len(unmapped)} 条 SR 卡在规格里找不到同号条目（违反编号规则 A）：{unmapped}"
        )
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


def progress(data: dict, exc: set[str]) -> tuple[list[str], list[str], list[str]]:
    """台账 ↔ git：谁已提交却没更新台账（失败）/ 谁标了 done 却没提交（提示）。

    一个例外（实测踩到）：**有意拆分的任务** —— 比如 T-B5 的"字段+界面"随提交落地、
    "系统通知通道"要等用户选型才能做。这种条目在台账里仍是 `partial`（如实），
    但它的 Task 提交是真的。逐条写进 `[exceptions]` 才豁免（**留痕、修一条删一条**），
    不许默默放过 —— 否则"提交了但忘了改台账"这条最有用的检查就废了。
    """
    log = git("log", "--format=%h%x09%(trailers:key=Task,valueonly)", "HEAD")
    seen: dict[str, list[str]] = {}
    for line in log.splitlines():
        sha, _, task = line.partition("\t")
        if task.strip():
            seen.setdefault(task.strip(), []).append(sha)
    warn: list[str] = []
    fail: list[str] = []
    exempted: list[str] = []
    for eid, e in sorted(data.get("entries", {}).items()):
        status = e.get("status")
        if status == "done" and eid not in seen:
            warn.append(f"{eid}: 台账 done，但 git 里没有挂 Task:{eid} 的提交（多为老账）")
        if status in {"todo", "partial"} and eid in seen:
            shas = ",".join(seen[eid])
            line = f"{eid}: 台账仍是 {status}，但提交 {shas} 挂了 Task:{eid} → 台账漏更新"
            (exempted if eid in exc else fail).append(line)
    return warn, fail, exempted


# ---------------------------------------------------------------- ⑧⑨⑩ 收紧项（T-G22）
# 三条都是"机器本来能查、以前没人查"的东西，2026-09-23 用户点了名才加上。
# 上阻断前都在真实历史上跑过一遍，确认**当前 0 假红**（见 `复盘/门禁收紧三条-T-G22.md`）。
BASELINE_FALLBACK = "593ea6c"  # 强制框架那次提交（此前的历史没有 trailer，不追责）
_CONTRACT_FILES = ROOT / "docs" / "contracts"


def parse_task_trailers(text: str, ids: set[str]) -> list[str]:
    """把 `git log --format=%h%x1f%s%x1f%(trailers:key=Task,valueonly)%x1e` 的输出判一遍。

    单独拆出来是为了能**喂假数据测试**（真仓库里造不出一条错提交来验）。
    判据：`Task:` 必须**恰好一个**台账编号。
    """
    fails: list[str] = []
    for record in text.split("\x1e"):
        if not record.strip():
            continue
        parts = record.strip("\n").split("\x1f")
        if len(parts) < 3:
            continue
        sha, subject, task = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if not task:
            fails.append(f"{sha} 没有 `Task:` trailer（{subject[:44]}）")
            continue
        tokens = [t for t in re.split(r"[\s,/、+]+", task) if t]
        if len(tokens) != 1 or tokens[0] not in ids:
            fails.append(
                f"{sha} 的 `Task:` 不是「恰好一个台账编号」：{task!r}（{subject[:36]}）"
                " —— 多余编号请写进 `Refs:`"
            )
    return fails


def check_commit_trailers(baseline: str, ids: set[str]) -> list[str]:
    """⑧ 逐条提交的 `Task:` 必须**恰好一个台账编号**（T-G17 那类错不再靠人眼）。

    为什么要它：审计原来只在**单条模式**（`--rev`）看当前这条提交，而门禁跑的是 `--all`
    （整段对账）—— 于是 `Task: T-G13 / F6 OP-27 延伸` 这种格式错一路没红。
    老历史（框架落地前）没有 trailer，所以从 `[meta.trailer_baseline]` 往后逐条查。
    """
    out = git("log", "--format=%h%x1f%s%x1f%(trailers:key=Task,valueonly)%x1e", f"{baseline}..HEAD")
    return parse_task_trailers(out, ids)


def collect_contract_ops() -> set[str]:
    """契约层定义成条目的操作（`## OP-nn` / 表格首列 / `- **OP-nn**`）。"""
    ops: set[str] = set()
    for path in sorted(_CONTRACT_FILES.rglob("*.md")):
        for line in path.read_text(encoding="utf-8").splitlines():
            m = (
                re.match(r"^#{2,4}\s*(OP-\d+[a-z]?)\b", line)
                or re.match(r"^\|\s*(OP-\d+[a-z]?)\s*\|", line)
                or re.match(r"^-\s*\*\*(OP-\d+[a-z]?)\*\*", line)
            )
            if m:
                ops.add(m.group(1))
    return ops


def check_contract_ops(data: dict, ops: set[str] | None = None) -> list[str]:
    """⑨ 契约层的每条操作要么挂在某张台账卡上，要么明写"为什么先不挂"。

    为什么：契约层是「怎样才算真的做成」那一层，但台账全文只提到 18/53 条
    （其余功能其实做了，只写在交接文档的**手写行**里）→ 新窗口读契约以为有 53 件事排着。
    落法：`[contract_ops]`（卡 → 操作列表）+ `[acknowledged_ops]`（操作 → 理由）；
    **契约操作自己就是一张台账卡**（`OP-1`…`OP-12` 那些）时算自动覆盖。
    """
    errs: list[str] = []
    if ops is None:
        ops = collect_contract_ops()
    mapping = data.get("contract_ops", {})
    ack = data.get("acknowledged_ops", {})
    entries = data.get("entries", {})
    covered: dict[str, str] = {op: "（自己就是一张卡）" for op in ops if op in entries}
    for eid in sorted(mapping):
        if eid not in entries:
            errs.append(f"[contract_ops] 里的 {eid} 不是台账条目（挂错卡了）")
        for op in mapping[eid]:
            if op not in ops:
                errs.append(f"[contract_ops] {eid} 挂了契约里没有的 {op}")
            if op in covered:
                errs.append(f"{op} 被重复登记：{covered[op]} 与 {eid}（一条操作只该挂一张卡）")
            covered[op] = eid
    for op in sorted(ack):
        if op not in ops:
            errs.append(f"[acknowledged_ops] 里的 {op} 契约里没有")
        covered.setdefault(op, "（acknowledged）")
    missing = sorted(ops - set(covered), key=lambda s: (int(re.search(r"\d+", s).group()), s))
    if missing:
        errs.append(
            f"契约里有 {len(missing)} 条操作既没挂台账卡、也没进 [acknowledged_ops]：{missing}"
        )
    return errs


def spec_n_to_srs(trace: str | None = None) -> dict[str, set[str]]:
    """规格追踪表 → `{N 号: {SR 基号}}`（`docs/specification/traceability.md`）。"""
    if trace is None:
        trace = (ROOT / "docs" / "specification" / "traceability.md").read_text(encoding="utf-8")
    n2sr: dict[str, set[str]] = {}
    for line in trace.splitlines():
        m = re.match(r"\|\s*N(\d+)[^|]*\|([^|]*)\|", line)
        if m:
            n2sr[m.group(1)] = set(re.findall(r"SR-(?:F\d+\.\d+|NF\d+)", m.group(2)))
    return n2sr


def check_spec_child_cards(data: dict, n2sr: dict[str, set[str]] | None = None) -> list[str]:
    """⑩ 规格条目还是 `todo`，但引用同一个 N 的实现卡**全 done** → 母条该收口了。

    为什么：T-G18 抓到的 `SR-F1.7`（子卡 T-F2/T-F3 都 done，母条还挂 todo + 过期 gaps）。
    只查 `todo` 不查 `partial`：partial 可以合法地"卡片都完了、但还剩一句不靠卡片的缺口"
    （`SR-F1.7` 更正后就是这种：关联笔记口径待定）—— 查它必然假红。
    """
    errs: list[str] = []
    if n2sr is None:
        n2sr = spec_n_to_srs()
    entries = data.get("entries", {})
    for eid in sorted(entries):
        if not eid.startswith("SR-") or entries[eid].get("status") != "todo":
            continue
        base = re.match(r"SR-(?:F\d+\.\d+|NF\d+)", eid)
        if not base:
            continue
        ns = {n for n, srs in n2sr.items() if base.group(0) in srs}
        if not ns:
            continue
        cards: list[tuple[str, str]] = []
        for cid, card in entries.items():
            if cid.startswith("SR-"):
                continue
            title = str(card.get("title", ""))
            if any(re.search(rf"N{n}\b", title) for n in ns):
                cards.append((cid, str(card.get("status"))))
        if cards and all(status == "done" for _, status in cards):
            names = "、".join(cid for cid, _ in cards)
            errs.append(
                f"{eid} 仍挂 todo，但引用同一 N 的实现卡全都是 done（{names}）"
                " → 母条该收口，或把缺口写清楚（`partial` + 非目标）"
            )
    return errs


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
    # ⑦ 交接文档里手写的那行分布（能查就查，查不到不失败）
    num_fails = check_handoff_numbers(counts, len(entries))
    print("\n=== ⑦ 交接文档的分布数字 ===")
    for line in num_fails:
        print(f"  {FAIL} {line}")
    if not num_fails:
        print(f"  {OK} 与台账一致（或文档里没写这行）")

    git_fails: list[str] = []
    git_exempt: list[str] = []
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
                    # 为什么不用 rev/tree 校验（三个坑都实测踩过）：
                    #  ① tree 自指：产物自己在那棵树里，写入哈希会让树变化 → 永不相等；
                    #  ② rev 时序：门禁必须**提交前**跑，那时新提交还不存在 → rev 必然落后一次；
                    #  ③ 与"本次提交时间"比较也是反的 —— 门禁必然比提交早。
                    # 正确的尺子是**父提交**：产物必须比上一次提交更新（否则就是沿用了陈旧产物）。
                    if not gate.get("ok"):
                        git_fails.append("gates/last.json 里 ok=false（门禁没过）")
                    else:
                        at_raw = str(gate.get("at", ""))
                        parent_ts = git("log", "-1", "--format=%cI", f"{rev}^") or git(
                            "log", "-1", "--format=%cI", rev
                        )
                        try:
                            at = datetime.fromisoformat(at_raw).replace(tzinfo=None)
                            parent_at = datetime.fromisoformat(parent_ts).replace(tzinfo=None)
                        except ValueError:
                            git_fails.append(f"gates/last.json 的时间戳无法解析：{at_raw!r}")
                        else:
                            if parent_at - at > timedelta(seconds=120):
                                git_fails.append(
                                    f"门禁产物时间 {at_raw} 早于父提交 {parent_ts}"
                                    "（沿用了旧产物，请重跑 scripts/run_gates.py）"
                                )
                if not meta["Gates"]:
                    git_fails.append("提交没有 `Gates:` trailer（没有门禁结果）")
        warn, wrong, exempt_now = progress(data, exc)
        git_exempt.extend(exempt_now)
        print("\n=== ⑥ 进度重建（台账 ↔ git）===")
        for line in exempt_now:
            print(f"  {WARN} 已豁免 {line}（见 [exceptions] 的理由）")
        for line in wrong:
            print(f"  {FAIL} {line}")
            git_fails.append(line)
        if not wrong:
            print(f"  {OK} 没有「已提交但台账未更新」的条目")
        for line in warn:
            print(f"  {WARN} {line}")

    # ⑧⑨⑩ 收紧项（T-G22）：都是"机器本来能查、以前没人查"的
    tighten_fails: list[str] = []
    print("\n=== ⑨ 契约层覆盖（每条 OP 要么挂台账卡，要么写明先不挂）===")
    contract = check_contract_ops(data)
    if contract:
        for line in contract:
            print(f"  {FAIL} {line}")
        tighten_fails.extend(contract)
    else:
        ops = collect_contract_ops()
        ack = data.get("acknowledged_ops", {})
        print(f"  {OK} 契约 {len(ops)} 条操作全部有归属（其中 {len(ack)} 条已写明先不挂）")

    print("\n=== ⑩ 母条/子卡一致性（规格仍 todo 但子卡全 done）===")
    child = check_spec_child_cards(data)
    if child:
        for line in child:
            print(f"  {FAIL} {line}")
        tighten_fails.extend(child)
    else:
        print(f"  {OK} 没有「子卡全 done、母条还挂 todo」的规格条目")

    if not args.no_git:
        baseline = str(data.get("meta", {}).get("trailer_baseline", BASELINE_FALLBACK))
        print(f"\n=== ⑧ 提交信息逐条（{baseline}..HEAD 的 `Task:` 必须恰好一个台账编号）===")
        trailer = check_commit_trailers(baseline, set(entries))
        if trailer:
            for line in trailer:
                print(f"  {FAIL} {line}")
            tighten_fails.extend(trailer)
        else:
            log = git("log", "--format=%h", f"{baseline}..HEAD")
            n = len([ln for ln in log.splitlines() if ln])
            print(f"  {OK} {n} 条提交全部合格（多余编号写进 `Refs:` 的那条规矩，机器也会拦了）")

    all_fails = shape + fails + num_fails + git_fails + tighten_fails
    n_exempt = len(exempted) + len(git_exempt)
    print("\n" + "=" * 72)
    if all_fails:
        print(f"审计不通过：{len(all_fails)} 项失败（{n_exempt} 项已豁免）")
        for line in all_fails:
            print(f"  - {line}")
        print("→ 按用户约定：**审计不通过不许提交**。修完或写进 exceptions 再提交。")
        return 1
    print(f"审计通过 ✅（豁免 {n_exempt} 项已知欠账）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
