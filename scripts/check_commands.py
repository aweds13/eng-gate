"""命令表的一致性检查（T-G31）—— 让「四个面」共用一张表，并且这张表不许漂。

## 为什么需要它

用户 2026-09-23 说：「**最好就是 4 个面集中到一个点，然后调用同一个点的东西，可以吗？**」
可以 —— 而且本项目**已经**是"一个点 + 薄适配器"：`core/` 是那个点，`api/app.py` 是唯一的边界，
界面通过 HTTP 调它。缺的不是架构，是**一层元数据**：每个操作叫什么、改不改数据、可不可逆、
对应哪条路由、界面上哪个入口、AI 能不能碰。

有了这层元数据，**四个面都变成投影**，不用各写一遍：
    界面按钮 / ⌘K 面板 / CLI / AI·MCP   ←   全部读 `docs/commands.toml`

## 它检查什么

这张表有**三个已有的真源**，所以大部分能机器核对 —— 这才是它不会变成"第二份手抄"的原因：

| 真源 | 从哪读 | 核对什么 |
|---|---|---|
| **契约层操作** | `docs/contracts/**` 的 `## OP-n 标题` | 每条 OP 必须有行；行不许有契约里没有的 |
| **HTTP 路由** | `app.py` 的 `@app.<method>("/path")` | 表里每条路由必须**真的存在** |
| **界面入口** | `index.html` 的 `ACTIONS` / `VIEWS` | `data-action=x` / `view=y` 必须**真注册过** |

**洞是允许的、也是要报的**：现在还有多少行没填出路由/界面入口，脚本会数出来 ——
那就是"这张表还差多少"的进度条，也是下一步的工单（跟两道审美门的登记表一个思路）。

用法
  python -X utf8 scripts/check_commands.py            # 人读
  python -X utf8 scripts/check_commands.py --json     # 机器读
  python -X utf8 scripts/check_commands.py --check    # 门禁用：硬冲突就退 1
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent
COMMANDS = ROOT / "docs" / "commands.toml"
CONTRACTS = ROOT / "docs" / "contracts"
APP = ROOT / "src" / "timeflow" / "api" / "app.py"
INDEX = ROOT / "src" / "web" / "index.html"

OP_HEADING = re.compile(r"^##\s+(OP-\d+[a-z]?)\s+(.+?)\s*$")
ROUTE = re.compile(r'@app\.(get|post|patch|delete|put)\("([^"]+)"')
# `@app.api_route("/api/ai/{rest:path}")` 是**故意不做事**的通配兜底（拒写 403/404），
# 不是命令 —— 所以它不进命令表的合法路由集，只数出来给人看。
WILDCARD = re.compile(r'@app\.api_route\(\s*"([^"]+)"')
ACTION_KEY = re.compile(r"'([a-z0-9-]+)':\s*(?:el\s*=>|\()")
VIEWS = re.compile(r"const VIEWS=\[([^\]]*)\]")

KINDS = {"write", "read", "derive"}
AI_SCOPES = {"read", "create", "none"}


def contract_ops() -> tuple[dict[str, str], list[str]]:
    """`{OP-n: 标题}` + 「同一号有多节」的说明。

    同一个 OP 在**基础篇**与**领域篇**各有一节是**设计如此**（领域篇那节标题带（扩展），
    是在基础契约上再加该域的要求）—— 所以这不是冲突，取**不带（扩展）**的那个当正名，
    另一节记进 `dupes` 当提示。
    """
    ops: dict[str, str] = {}
    seen_in: dict[str, str] = {}
    dupes: list[str] = []
    for path in sorted(CONTRACTS.rglob("*.md")):
        for line in path.read_text(encoding="utf-8").splitlines():
            m = OP_HEADING.match(line)
            if m is None:
                continue
            oid, title = m.group(1), m.group(2)
            if oid not in ops:
                ops[oid] = title
                seen_in[oid] = path.name
                continue
            if title == ops[oid]:
                continue
            plain_is_new = "（扩展）" not in title
            plain = title if plain_is_new else ops[oid]
            extended = ops[oid] if plain_is_new else title
            plain_file = path.name if plain_is_new else seen_in[oid]
            ext_file = seen_in[oid] if plain_is_new else path.name
            ops[oid] = plain
            dupes.append(f"{oid}：基础「{plain}」在 {plain_file}，扩展「{extended}」在 {ext_file}")
    return ops, dupes


def routes() -> set[str]:
    src = APP.read_text(encoding="utf-8")
    return {f"{m.group(1).upper()} {m.group(2)}" for m in ROUTE.finditer(src)}


def wildcard_routes() -> list[str]:
    """`@app.api_route(...)` 通配兜底（故意不做事的那种）—— 只报告，不进合法路由集。"""
    return [m.group(1) for m in WILDCARD.finditer(APP.read_text(encoding="utf-8"))]


def ui_names() -> tuple[set[str], set[str]]:
    """`(ACTIONS 里注册过的动作名, VIEWS 里的视图名)`。

    ⚠️ 解析方式**必须与 `scripts/audit_progress.py::registered_actions()` 一致** ——
    那一条是项目既有的护栏（"模板里用到的每个 `data-action` 都必须注册"），
    两边定义不一样就会出现"审计说注册了、命令表说没注册"这种自相矛盾。
    踩过的坑：第一版用 `split("};")[0]` 截 ACTIONS 段，**遇到函数体里的 `};` 就被截断**，
    于是后十几个动作被判成"没注册"（报出 15 条假冲突）。
    """
    html = INDEX.read_text(encoding="utf-8")
    segment = html.split("const ACTIONS", 1)[1] if "const ACTIONS" in html else ""
    actions = {m.group(1) for m in ACTION_KEY.finditer(segment)}
    m = VIEWS.search(html)
    views = {v.strip().strip("'") for v in m.group(1).split(",") if v.strip()} if m else set()
    return actions, views


def load_commands() -> dict[str, dict[str, object]]:
    if not COMMANDS.exists():
        return {}
    data = tomllib.loads(COMMANDS.read_text(encoding="utf-8"))
    table = data.get("commands", {})
    return dict(table) if isinstance(table, dict) else {}


def as_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if value in ("", None):
        return []
    return [str(value)]


def main() -> int:
    ap = argparse.ArgumentParser(description="命令表一致性检查")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true", help="有硬冲突（对不上真源）就退 1")
    args = ap.parse_args()

    ops, dupes = contract_ops()
    real_routes = routes()
    wildcards = wildcard_routes()
    actions, views = ui_names()
    table = load_commands()

    problems: list[str] = []
    no_route: list[str] = []
    no_ui: list[str] = []

    if not table:
        problems.append(
            "docs/commands.toml 还不存在或没有 [commands] 表 —— 这张表是"
            "「四个面共用一个点」的地基，还没建。"
        )

    for oid, row in sorted(table.items()):
        if oid not in ops:
            problems.append(f"{oid}：契约层里没有这条 OP（表里多了行，或是编号写错）")
            continue
        title = str(row.get("title", ""))
        if title and title != ops[oid]:
            problems.append(f"{oid}：标题与契约不一致（表：{title} / 契约：{ops[oid]}）")
        kind = str(row.get("kind", ""))
        if kind and kind not in KINDS:
            problems.append(f"{oid}：kind={kind!r} 不在 {sorted(KINDS)}")
        # `ai` 是**列表**（一条操作可以既是「可读」又是「可新建」——OP-34 就是），不是单值。
        for scope in as_list(row.get("ai")):
            if scope not in AI_SCOPES:
                problems.append(f"{oid}：ai 里有非法值 {scope!r}，只允许 {sorted(AI_SCOPES)}")
        row_routes = as_list(row.get("routes"))
        for route in row_routes:
            if route not in real_routes:
                problems.append(f"{oid}：路由 {route!r} 在 app.py 里不存在（手抄或过期）")
        for entry in as_list(row.get("ui")):
            if entry.startswith("data-action="):
                name = entry.split("=", 1)[1]
                if name not in actions:
                    problems.append(f"{oid}：界面动作 {name!r} 没在 ACTIONS 注册")
            elif entry.startswith("view="):
                name = entry.split("=", 1)[1]
                if name not in views:
                    problems.append(f"{oid}：视图 {name!r} 不在 VIEWS 里")
            else:
                problems.append(f"{oid}：ui 写法不认识 {entry!r}（应为 data-action=… 或 view=…）")
        if not row_routes:
            no_route.append(oid)
        if not as_list(row.get("ui")):
            no_ui.append(oid)

    missing = sorted(set(ops) - set(table))
    if missing:
        problems.append(f"契约里有 {len(missing)} 条 OP 还没进命令表：{missing}")

    report = {
        "contract_ops": len(ops),
        "rows": len(table),
        "routes_in_app": len(real_routes),
        "wildcard_routes": wildcards,
        "actions_in_registry": len(actions),
        "views": len(views),
        "rows_without_route": no_route,
        "rows_without_ui": no_ui,
        "problems": problems,
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if (args.check and problems) else 0

    print("=== 命令表 ↔ 三个真源 对账 ===")
    print(f"  契约层 OP：{len(ops)} 条   命令表行数：{len(table)}")
    print(
        f"  app.py 路由：{len(real_routes)} 条   "
        f"ACTIONS 注册：{len(actions)} 个   视图：{len(views)} 个"
    )
    if wildcards:
        print(f"  （另有 {len(wildcards)} 条通配兜底，故意不做事、不进命令表：{wildcards}）")
    if dupes:
        print(f"\n  （提示）同一号在基础篇与领域篇各有一节：{len(dupes)} 处")
        for d in dupes:
            print(f"    · {d}")
    if no_route:
        print(f"\n  还没填出路由的：{len(no_route)} 条 → {no_route}")
    if no_ui:
        print(f"\n  还没填出界面入口的：{len(no_ui)} 条 → {no_ui}")
    if problems:
        print(f"\n=== 硬冲突 {len(problems)} 条（必须修）===")
        for p in problems:
            print(f"  [FAIL] {p}")
        return 1 if args.check else 0
    print("\n命令表与三个真源一致 ✅（没有硬冲突）")
    print("说明：洞（没填出的路由/入口）是**进度**不是错误 —— 数量下降就是这张表在长。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
