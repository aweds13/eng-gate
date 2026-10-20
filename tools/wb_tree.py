r"""卡谱系树：从 git 历史重建「谁接着谁」，按功能区切（卡 A302 · T-AG416）。

## 一句话

每张卡收口是一笔提交，**父提交就是上一张卡** —— 推进顺序本来就记在提交链里，
不需要再往台账里补猜 `depends`。本工具**只读** `git log` 与 `docs/workbacklog.toml`：
不写台账、不写 `gates/`、不起工人。

## 节点（= 一笔提交）

- `sha`     缩写提交号（`%h`）；
- `task`    subject 里第一个 `T-[A-Z]+\d+`（查不到 ⇒ `null`，**不推断**）；
- `card`    用 task 去卡池 `[[cards]].task` 对出来的卡号（对不到 ⇒ `null`，如实空着）；
- `title`   subject 原文；`date` 提交日（`--date=short`）；
- `area`    见下面的区映射表；`files` 该提交改了几个文件（`git show --name-only` 口径）；
- `parents` 真实 git 父链（`%p`）；`children` 反链。

★ `card = null` 不等于是「没卡」—— 只是**卡池里查不到**（老账没登记成卡）。
  文本模式把它标成「未登记」并显示 task 号 / subject 摘要，**绝不猜成某张卡**。

## 边

- `parent`：真实 git 父链（先后只在这里表达 —— **不把「提交时间相邻」猜成 `depends`**）；
- `depends`：卡池里的**显式前置**（`[[cards]].depends`，跨链），每个节点带
  `depends: [{card, sha, kind: "explicit"}]`；`sha` = 该前置卡在窗口内最后一笔提交，
  窗口里没有就是 `null`（**不拿别的提交顶上**）。

## 区映射表（`area` 的唯一真源）

按该提交**改动文件的前缀**归类（`git show --name-only` 同口径；本工具用
`git log --name-only` 一次批量取，两者对同一笔提交输出一致）。规则：

1. 先看**代码区**（面板 / 号池 / 技能 / 门禁 / 服务）：碰了就算，取改动文件数最多的那个，
   打平按本表顺序；`tests/` 下与某区同名的测试算那一区（其余 `tests/` 算服务）。
2. 只有**纯文档**提交才落到 复盘 / 台账（两区并存时复盘优先 —— 复盘是正文，changelog /
   traceability / workbacklog 是登记噪声）。
3. `gates/last.json` 与 `gates/diag/…` 是**每笔都可能被重写的运行产物**，不参与投票
   （否则「门禁」会把大半提交吸走）。
4. 一个前缀都不命中 ⇒ `其它`。

★ 为什么不是全表多数票：每张卡收口都顺带改 `docs/changelog*` / `docs/traceability*` /
  `docs/workbacklog.toml` / `复盘/…`，多数票会把「改面板的那一笔」判成台账（真踩过）。

各区的**前缀表**（真源是下面的 `AREA_MAP`，这里只列给人看）：

- **面板**：`tools/dsh_panel.py` · `tools/pipeline_view.py` · `tools/wb_dash.py` ·
  `tools/dsh_skills_link.py` · `tools/tf_cardgen.py` · `tools/ui_` · `tools/contrast` ·
  `tools/style_` · `tools/candidate_` · `tools/render_check` · `tools/dark_probe` ·
  `tools/phone_check` · `tools/route_ui_gap.py` · `tools/notmodel_audit.py` ·
  `tests/test_dsh_panel.py` · `tests/test_pipeline_view` · `tests/test_wb_dash`
- **号池**：`tools/pool/` · `tools/pool_` · `tools/wb_plan.py` · `tools/wb_dispatch.py` ·
  `tools/wb_status.py` · `tools/wb_notify.py` · `tools/wb_reconcile.py` ·
  `tools/wb_tree.py` · `tools/wt_prune.py` · `tools/auto_land.py` ·
  `tools/trae_pool.mjs` · `tools/tf_commit.py` · `tools/tf_stage_guard.py` ·
  `tests/test_wb_` · `tests/test_pool`
- **技能**：`skills/` · `tools/check_skills.py` · `tests/test_check_skills`
- **台账**：`docs/traceability` · `docs/workbacklog.toml` · `docs/changelog` ·
  `tools/sync_counts.py` · `tools/sync_docs.py` · `tools/evidence_map.py` ·
  `scripts/audit_progress.py` · `scripts/audit_titles.py` · `tests/test_ledger` ·
  `tests/test_evidence_map` · `tests/test_sync_`
- **复盘**：`复盘/`
- **门禁**：`gates/` · `harness/` · `harness.toml` · `scripts/run_gates.py` ·
  `scripts/check_` · `tools/check_commands.py` · `tools/card_doc_budget.py` ·
  `tools/domain_symbols.py` · `tools/contract_audit.py` · `tools/seam_check.py` ·
  `tools/lf1_live_check.py` · `tests/test_gate` · `tests/test_check_` ·
  `tests/test_no_window` · `tests/test_contract_audit` · `tests/test_seam_check` ·
  `tests/test_domain_symbols` · `tests/test_audit_` · `tests/test_card_doc_budget`
- **服务**：`src/` · `tools/serve.py` · `tools/stack.py` · `tools/launch_timeflow.pyw` ·
  `tools/mcp_client.py` · `tools/bench.py` · `tools/snapshot.py` · `tools/relocate.py` ·
  `tools/sandbox_shim/` · `tests/`（其余测试）
- **其它**：兜底（一个前缀都不命中）

## 窗口 / 断链

`--since` 把窗口切短时，父提交可能落在窗口外 ⇒ 记一条 `orphans` 条目
（`why` 写明是哪个父提交不在窗口），**不递归、不爆栈**；文本模式尾部报
「窗口截断 N 处」。环同理：遍历带 `seen` 集合，重复访问不再展开。

## 用法

    python -X utf8 tools/wb_tree.py --area 面板 --limit 20
    python -X utf8 tools/wb_tree.py --json
    python -X utf8 tools/wb_tree.py --since 2026-10-01 --limit 100
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import tomllib
from pool.no_window import NO_WINDOW  # noqa: E402  ★ 卡 148：子进程一律不弹窗（唯一真源）

ROOT = Path(__file__).resolve().parent.parent

#: task 号口径（卡规格点名）：`T-AG414` / `T-G99` / `T-A302` 都吃。
TASK_RE = re.compile(r"T-[A-Z]+\d+")

#: 区的固定顺序（`areas[]` 与打平时的次序都按它）。
AREA_OTHER = "其它"
AREA_MAP: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "面板",
        (
            "tools/dsh_panel.py",
            "tools/pipeline_view.py",
            "tools/wb_dash.py",
            "tools/dsh_skills_link.py",
            "tools/tf_cardgen.py",
            "tools/ui_",
            "tools/contrast",
            "tools/style_",
            "tools/candidate_",
            "tools/render_check",
            "tools/dark_probe",
            "tools/phone_check",
            "tools/route_ui_gap.py",
            "tools/notmodel_audit.py",
            "tests/test_dsh_panel.py",
            "tests/test_pipeline_view",
            "tests/test_wb_dash",
        ),
    ),
    (
        "号池",
        (
            "tools/pool/",
            "tools/pool_",
            "tools/wb_plan.py",
            "tools/wb_dispatch.py",
            "tools/wb_status.py",
            "tools/wb_notify.py",
            "tools/wb_reconcile.py",
            "tools/wb_tree.py",
            "tools/wt_prune.py",
            "tools/auto_land.py",
            "tools/trae_pool.mjs",
            "tools/tf_commit.py",
            "tools/tf_stage_guard.py",
            "tests/test_wb_",
            "tests/test_pool",
        ),
    ),
    ("技能", ("skills/", "tools/check_skills.py", "tests/test_check_skills")),
    (
        "台账",
        (
            "docs/traceability",
            "docs/workbacklog.toml",
            "docs/changelog",
            "tools/sync_counts.py",
            "tools/sync_docs.py",
            "tools/evidence_map.py",
            "scripts/audit_progress.py",
            "scripts/audit_titles.py",
            "tests/test_ledger",
            "tests/test_evidence_map",
            "tests/test_sync_",
        ),
    ),
    ("复盘", ("复盘/",)),
    (
        "门禁",
        (
            "gates/",
            "harness/",
            "harness.toml",
            "scripts/run_gates.py",
            "scripts/check_",
            "tools/check_commands.py",
            "tools/card_doc_budget.py",
            "tools/domain_symbols.py",
            "tools/contract_audit.py",
            "tools/seam_check.py",
            "tools/lf1_live_check.py",
            "tests/test_gate",
            "tests/test_check_",
            "tests/test_no_window",
            "tests/test_contract_audit",
            "tests/test_seam_check",
            "tests/test_domain_symbols",
            "tests/test_audit_",
            "tests/test_card_doc_budget",
        ),
    ),
    (
        "服务",
        (
            "src/",
            "tools/serve.py",
            "tools/stack.py",
            "tools/launch_timeflow.pyw",
            "tools/mcp_client.py",
            "tools/bench.py",
            "tools/snapshot.py",
            "tools/relocate.py",
            "tools/sandbox_shim/",
            "tests/",
        ),
    ),
    (AREA_OTHER, ()),
)
AREA_NAMES: tuple[str, ...] = tuple(name for name, _ in AREA_MAP)

#: 「代码区」—— 一笔提交只要碰了其中任何一个，就按它归类（文档/台账是每笔都带的噪声）。
CODE_AREAS: tuple[str, ...] = ("面板", "号池", "技能", "门禁", "服务")
#: 「文档区」—— 只改了文档的提交才落到这里；两区并存时 **复盘优先**（那份复盘才是正文，
#: changelog / traceability / workbacklog 是登记噪声）。
DOC_AREAS: tuple[str, ...] = ("复盘", "台账")

#: 每笔提交都会被改的**运行产物**：它们不参与区投票（否则「门禁」会把大半提交吸走）。
#: `gates/last.json` 是每次门禁都重写的；`gates/diag/` 是判决/日志/通知的落点。
NOISE_PREFIXES: tuple[str, ...] = ("gates/last.json", "gates/diag/")

#: 文本模式的缩进上限：深度 > 6 就打 `…`（规格点名）。
MAX_DEPTH = 6
#: git 子进程超时（秒）—— 真仓 473 笔实测 1~2s，留足余量。
GIT_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class Commit:
    """一笔提交的裸读数（`git log --format=%h%x09%p%x09%ad%x09%s --date=short`）。"""

    sha: str
    parents: tuple[str, ...]
    date: str
    subject: str


@dataclass(frozen=True)
class CardRec:
    """卡池里一条 `[[cards]]`（只取本工具要用的三列）。"""

    id: str
    task: str
    depends: tuple[str, ...]


def area_of(path: str) -> str:
    """一个改动文件属于哪个区：按前缀表**第一个命中**的算（表序 = 优先级）。"""
    norm = path.replace("\\", "/").strip()
    for name, prefixes in AREA_MAP:
        if any(norm.startswith(prefix) for prefix in prefixes):
            return name
    return AREA_OTHER


def classify(paths: list[str] | tuple[str, ...]) -> str:
    """一笔提交的区：先看**代码区**（碰了就算，按改动文件数最多 / 表序靠前），
    只有**纯文档**提交才落到 复盘/台账（复盘优先），一个都不命中 ⇒ `其它`。

    ★ 为什么不是全表多数票：每张卡收口都会顺带改 `docs/changelog*` /
      `docs/traceability*` / `docs/workbacklog.toml` / `复盘/…`，多数票会把
      「改面板的那一笔」判成台账（真踩过：面板区一度只剩 5 笔）。
    没有改动文件（合并提交的 `--name-only` 是空的）⇒ `其它`。
    """
    counts: dict[str, int] = {}
    for path in paths:
        if _is_noise(path):
            continue
        area = area_of(path)
        counts[area] = counts.get(area, 0) + 1
    if not counts:
        return AREA_OTHER
    code = {name: hit for name, hit in counts.items() if name in CODE_AREAS}
    if code:
        return _pick(code, AREA_NAMES)
    doc = {name: hit for name, hit in counts.items() if name in DOC_AREAS}
    if doc:
        return _pick(doc, DOC_AREAS)
    return AREA_OTHER


def _is_noise(path: str) -> bool:
    """运行产物路径（`gates/last.json` / `gates/diag/…`）：不参与区投票。

    `gates/` 里既有产物也有真门禁代码，所以判据核**文件**、不整区丢。
    """
    norm = path.replace("\\", "/").strip()
    return any(norm.startswith(prefix) for prefix in NOISE_PREFIXES)


def _pick(counts: dict[str, int], order: tuple[str, ...]) -> str:
    """改动文件数最多者；打平按 `order` 里的先后。"""
    return min(counts, key=lambda name: (-counts[name], order.index(name)))


def match_task(subject: str) -> str | None:
    """subject 里第一个任务号；没有 ⇒ `None`（**不推断**）。"""
    found = TASK_RE.search(subject or "")
    return found.group(0) if found else None


def _git(root: Path, *args: str) -> str:
    """跑一条只读 git 命令；非零退出**如实抛出**（不拿空输出冒充成功）。

    ★ `core.quotepath=false`：不加它，非 ASCII 路径会被 git 写成 `"\\345\\244..."` 八进制，
      区映射就全落到「其它」里（真踩过：面板区一度 0 笔）。
    """
    done = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=GIT_TIMEOUT_SECONDS,
        cwd=str(root),
        **NO_WINDOW,
    )
    if done.returncode != 0:
        tail = (done.stderr or "").strip()[:400]
        raise RuntimeError(f"git {' '.join(args)} 非零退出（{done.returncode}）：{tail}")
    return done.stdout


def git_log(root: Path, since: str = "") -> list[Commit]:
    """窗口内的提交（`%p` 是缩写父链，与 `%h` 同一缩写长度）。"""
    args = ["log", "--format=%h%x09%p%x09%ad%x09%s", "--date=short"]
    if since:
        args.append(f"--since={since}")
    commits: list[Commit] = []
    for line in _git(root, *args).splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 3)
        if len(parts) < 4:
            continue
        sha, parents, date, subject = parts
        commits.append(Commit(sha, tuple(parents.split()), date, subject))
    return commits


def changed_files(root: Path, since: str = "") -> dict[str, list[str]]:
    """每笔提交改了哪些文件（`git show --name-only` 同口径，批量一次取完）。

    ★ 合并提交按 git 默认**不列文件**（`git show` 同样为空）⇒ 空表，如实记。
    """
    args = ["log", "--format=%x01%h", "--name-only"]
    if since:
        args.append(f"--since={since}")
    files: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in _git(root, *args).splitlines():
        if line.startswith("\x01"):
            sha = line[1:].strip()
            current = files.setdefault(sha, [])
        elif line.strip() and current is not None:
            current.append(line.strip())
    return files


def load_cards(root: Path) -> tuple[dict[str, str], dict[str, CardRec]]:
    """读卡池：`task -> 卡号` 与 `卡号 -> 记录`。文件不在 ⇒ 两个空表（如实空着）。"""
    path = root / "docs" / "workbacklog.toml"
    if not path.is_file():
        return {}, {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    by_task: dict[str, str] = {}
    by_id: dict[str, CardRec] = {}
    for row in data.get("cards") or []:
        card_id = str(row.get("id") or "").strip()
        if not card_id:
            continue
        task = str(row.get("task") or "").strip()
        depends = tuple(str(item).strip() for item in row.get("depends") or () if str(item).strip())
        by_id[card_id] = CardRec(card_id, task, depends)
        if task:
            by_task[task] = card_id
    return by_task, by_id


def build(root: Path | None = None, since: str = "") -> dict:
    """整棵树：`{nodes, areas, orphans}`（规格点名的三个顶层键）。"""
    root = Path(root) if root is not None else ROOT
    commits = git_log(root, since)
    file_map = changed_files(root, since)
    by_task, by_id = load_cards(root)

    nodes: list[dict] = []
    index: dict[str, dict] = {}
    #: 卡号 -> 窗口内**最后一笔**提交（`depends` 边的落点）。
    last_sha_of_card: dict[str, str] = {}
    for commit in commits:
        task = match_task(commit.subject)
        card = by_task.get(task) if task else None
        paths = file_map.get(commit.sha, [])
        node = {
            "sha": commit.sha,
            "card": card,
            "task": task,
            "title": commit.subject,
            "date": commit.date,
            "area": classify(paths),
            "parents": list(commit.parents),
            "children": [],
            "files": len(paths),
            "depends": [],
        }
        nodes.append(node)
        index[commit.sha] = node
        if card and card not in last_sha_of_card:
            # `git log` 是倒序：第一次遇到就是这张卡最新的一笔。
            last_sha_of_card[card] = commit.sha

    for node in nodes:
        for parent in node["parents"]:
            if parent in index:
                index[parent]["children"].append(node["sha"])

    for node in nodes:
        record = by_id.get(node["card"]) if node["card"] else None
        if record is None:
            continue
        for dep in record.depends:
            node["depends"].append(
                {"card": dep, "sha": last_sha_of_card.get(dep), "kind": "explicit"}
            )

    areas = _areas(nodes, index)
    orphans = [
        {
            "sha": node["sha"],
            "task": node["task"],
            "why": f"父提交 {parent} 不在窗口内（窗口截断）",
        }
        for node in nodes
        for parent in node["parents"]
        if parent not in index
    ]
    return {"nodes": nodes, "areas": areas, "orphans": orphans}


def _areas(nodes: list[dict], index: dict[str, dict]) -> list[dict]:
    """按固定区序汇总：`count` = 该区节点数，`roots` = 该区可见子树的起点数。

    `roots` 的口径 = **父节点不在同区**（含父提交在窗口外）的节点数 ——
    它与 `--area <名>` 展开后看到的顶层行数一致。
    """
    rows: list[dict] = []
    for name in AREA_NAMES:
        picked = [node for node in nodes if node["area"] == name]
        if not picked:
            continue
        roots = sum(
            1
            for node in picked
            if not any(
                parent in index and index[parent]["area"] == name for parent in node["parents"]
            )
        )
        rows.append({"name": name, "count": len(picked), "roots": roots})
    return rows


# ---------------------------------------------------------------- 文本模式


def _node_label(node: dict) -> str:
    """节点左侧的「卡号 / 未登记」标签。"""
    if node["card"]:
        return str(node["card"])
    if node["task"]:
        return f"未登记({node['task']})"
    return "未登记(无任务号)"


def _line(node: dict, depth: int, *, with_area: bool) -> str:
    parts = [f"{'  ' * depth}{node['sha']}  {_node_label(node):<18}  {node['title']}"]
    if with_area:
        parts.append(f"  [{node['area']}]")
    for dep in node["depends"]:
        parts.append(f"  ←{dep['card']}(explicit)")
    return "".join(parts)


def render_text(tree: dict, *, area: str = "", limit: int = 50) -> list[str]:
    """缩进树（深度 > 6 打 `…`）+ 头部汇总 + 尾部窗口截断计数。"""
    nodes = tree["nodes"]
    by_sha = {node["sha"]: node for node in nodes}
    picked = [node for node in nodes if not area or node["area"] == area]
    picked_sha = {node["sha"] for node in picked}
    roots = [node for node in picked if not any(p in picked_sha for p in node["parents"])]
    roots.sort(key=lambda node: (node["date"], node["sha"]), reverse=True)

    mapped = sum(1 for node in nodes if node["card"])
    head = [
        f"谱系窗口 {len(nodes)} 笔 · 对上卡池 {mapped} 笔 · 未登记 {len(nodes) - mapped} 笔"
        + (f" · 只看「{area}」（{len(picked)} 笔）" if area else "")
    ]

    lines: list[str] = []
    printed = 0
    seen: set[str] = set()

    def walk(node: dict, depth: int) -> None:
        nonlocal printed
        if printed >= limit or node["sha"] in seen:
            return
        if depth > MAX_DEPTH:
            lines.append("  " * depth + "…")
            printed += 1
            return
        seen.add(node["sha"])
        lines.append(_line(node, depth, with_area=not area))
        printed += 1
        kids = [
            by_sha[child]
            for child in node["children"]
            if child in picked_sha and child not in seen
        ]
        kids.sort(key=lambda kid: (kid["date"], kid["sha"]))
        for kid in kids:
            walk(kid, depth + 1)

    for root in roots:
        if printed >= limit:
            break
        walk(root, 0)

    rest = len(picked) - printed
    tail = [f"窗口截断 {len(tree['orphans'])} 处（父提交不在窗口内；明细见 --json 的 orphans）"]
    if rest > 0:
        tail.insert(0, f"… 还有 {rest} 笔未显示（--limit {limit}）")
    return head + lines + tail


def _write(text: str) -> None:
    """写 stdout；下游提前关管道（`| head -20`）不算错 —— 静默收工，不吐 traceback。"""
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except BrokenPipeError:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="卡谱系树：从 git 历史重建前置关系，按功能区切（卡 A302，只读）",
    )
    parser.add_argument("--json", action="store_true", help="输出 {nodes, areas, orphans}")
    parser.add_argument("--area", default="", help=f"只看一个区：{' / '.join(AREA_NAMES)}")
    parser.add_argument("--limit", type=int, default=50, help="文本模式最多显示多少笔（默认 50）")
    parser.add_argument("--since", default="", help="窗口起点（git --since 口径，如 2026-10-01）")
    parser.add_argument("--root", default="", help="仓库根（默认本文件推出来）")
    args = parser.parse_args(argv)

    if args.area and args.area not in AREA_NAMES:
        print(
            f"[FAIL] 不认识的区：{args.area}（只有 {' / '.join(AREA_NAMES)}）",
            file=sys.stderr,
        )
        return 2

    root = Path(args.root) if args.root else ROOT
    tree = build(root, args.since)
    if args.json:
        _write(json.dumps(tree, ensure_ascii=False, indent=2) + "\n")
        return 0
    _write("\n".join(render_text(tree, area=args.area, limit=max(1, args.limit))) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
