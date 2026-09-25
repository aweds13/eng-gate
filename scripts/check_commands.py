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
| **命令面板**（T-G61） | `index.html` 的 `COMMANDS` | 动作注册、键位不重复、挂的 OP 入口里真有它 |
| **命令行**（T-G64） | `timeflow.cli.registry.COMMANDS` | 只读（GET）、路由是该 OP 的、`kind` 是
  read/derive、`cli` 字段**双向**对得上 |

**洞是允许的、也是要报的**：现在还有多少行没填出路由/界面入口/命令行入口，脚本会数出来 ——
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

from timeflow.cli import registry as cli_registry
from timeflow.cli import table as cli_table

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
#: 只读命令只该挂在这两类操作上（`derive` 是纯计算，也没有写入）
READ_KINDS = {"read", "derive"}
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
    """读命令表 —— **与 CLI 共用同一个读法**（`timeflow.cli.table`）。

    为什么要共用：门禁读得出来、CLI 读不出来（或反之）这种自相矛盾，
    比"少读一个字段"严重得多 —— T-G52 那次把两处口径并成一处就是为这类事。
    """
    return cli_table.load_file(COMMANDS)


def _skip_literal(text: str, i: int) -> int:
    """如果 `text[i]` 是字符串或注释的开头，返回它**之后**的下标；否则原样返回 `i`。

    这三样必须跳：字符串里的括号/引号、注释里的 `{` 与 `'`。
    不跳会怎样（真踩到过）：注释里那个 `{` 被当成"一条命令的开头"，
    接着配对到**别处**的 `}`，于是从中间开始错位，最后报"括号没配对"。
    """
    ch = text[i]
    n = len(text)
    if ch in "'\"`":
        i += 1
        while i < n and text[i] != ch:
            i += 2 if text[i] == "\\" else 1
        return i + 1
    if ch == "/" and i + 1 < n and text[i + 1] == "/":
        while i < n and text[i] != "\n":
            i += 1
        return i
    if ch == "/" and i + 1 < n and text[i + 1] == "*":
        end = text.find("*/", i)
        return n if end < 0 else end + 2
    return i


def _balanced(text: str, start: int) -> str:
    """从 `text[start]` 那个 `[`（或 `{`）开始，返回**配对括号里面**的那段文本。

    为什么要手写配对而不是正则：命令面板那张表里每条都带嵌套的 `data:{view:'today'}`
    —— 正则很容易把"下一条的开头"一起吃进来。这**正是 `ACTIONS` 第一版踩过的坑**
    （用 `split("};")` 截段，遇到函数体里的 `};` 就断，报出 15 条假冲突，见 `ui_names` 的注释）。
    """
    close = {"[": "]", "{": "}"}[text[start]]
    depth = 0
    i = start
    while i < len(text):
        nxt = _skip_literal(text, i)
        if nxt != i:
            i = nxt
            continue
        if text[i] == text[start]:
            depth += 1
        elif text[i] == close:
            depth -= 1
            if depth == 0:
                return text[start + 1 : i]
        i += 1
    raise ValueError("命令面板那张表的括号没配对（`const COMMANDS = [` 之后找不到收尾的 `]`）")


def _split_entries(body: str) -> list[str]:
    """把 `[ … ]` 里面切成一条条 `{ … }`（同一个扫描器负责跳字符串/注释与配对）。

    为什么不"找第一个 `{` 再配对"：注释或字符串里的 `{` 会被当成条目开头（见 `_skip_literal`）。
    """
    out: list[str] = []
    depth = 0
    start = -1
    i = 0
    while i < len(body):
        nxt = _skip_literal(body, i)
        if nxt != i:
            i = nxt
            continue
        ch = body[i]
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                out.append(body[start + 1 : i])
                start = -1
        i += 1
    return out


def _field(text: str, name: str) -> str:
    m = re.search(rf"\b{name}\s*:\s*'([^']*)'", text)
    return m.group(1) if m else ""


def ui_commands() -> list[dict[str, str]]:
    """从 `index.html` 的 `const COMMANDS = [ … ]` 读**命令面板那张表**（T-G61）。

    它是「⌘K 面板」这份投影的真源：每条命令写了标题 / 分组 / 键位 / 跑哪个已注册动作 /
    对应哪条契约 OP。这里只负责**读出来**，判定在 `main()` 里 —— 读法必须稳（见 `_balanced`）。
    """
    html = INDEX.read_text(encoding="utf-8")
    if "const COMMANDS" not in html:
        return []
    head = html.index("const COMMANDS")
    start = html.index("[", head)
    rows: list[dict[str, str]] = []
    for chunk in _split_entries(_balanced(html, start)):
        view = re.search(r"data\s*:\s*\{\s*view\s*:\s*'([^']*)'", chunk)
        rows.append(
            {
                "id": _field(chunk, "id"),
                "title": _field(chunk, "title"),
                "group": _field(chunk, "group"),
                "keys": _field(chunk, "keys"),
                "action": _field(chunk, "action"),
                "op": _field(chunk, "op"),
                "view": view.group(1) if view else "",
            }
        )
    return rows


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

    problems: list[str] = []
    no_route: list[str] = []
    no_ui: list[str] = []
    # 表语法坏了：报**一句带行列的硬冲突**，而不是把 tomllib 的栈丢给跑门的人
    # （这张表在本项目里写坏过 9 次，每次都要几秒钟才看明白是哪儿）
    try:
        table = load_commands()
    except cli_table.TableBrokenError as exc:
        table = {}
        problems.append(f"命令表语法坏了（先修它，下面的对账才有意义）：{exc}")

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

    # ---- 命令面板（T-G61）：⌘K 那份投影必须与前三者一致 ----
    # 这一节是"四个面共用一个点"从口号变成判定的地方：面板里的每条命令都要
    #   ① 跑一个**真注册过**的动作（否则点了没反应，是空壳）；
    #   ② 键位不重复（抢键是键盘层最常见的隐性缺陷）；
    #   ③ 声称对应某条 OP 时，那条 OP 的界面入口里**真的有**这个动作/视图。
    palette = ui_commands()
    seen_ids: dict[str, str] = {}
    seen_keys: dict[str, str] = {}
    palette_with_op = 0
    palette_ops: set[str] = set()
    for cmd in palette:
        cid = cmd["id"] or "（没写 id）"
        if cmd["id"]:
            if cmd["id"] in seen_ids:
                problems.append(f"命令面板 {cid}：id 与 {seen_ids[cmd['id']]} 重复")
            seen_ids[cmd["id"]] = cid
        action = cmd["action"]
        if not action:
            problems.append(f"命令面板 {cid}：没写 action（面板只能跑已注册的动作）")
        elif action not in actions:
            problems.append(f"命令面板 {cid}：动作 {action!r} 没在 ACTIONS 注册")
        key = cmd["keys"]
        if key:
            if len(key) != 1:
                problems.append(f"命令面板 {cid}：键位 {key!r} 不是单个字符")
            if key in seen_keys:
                problems.append(f"命令面板：键位 {key!r} 被 {seen_keys[key]} 与 {cid} 抢了")
            seen_keys[key] = cid
        view = cmd["view"]
        if view and view not in views:
            problems.append(f"命令面板 {cid}：视图 {view!r} 不在 VIEWS 里")
        op = cmd["op"]
        if not op:
            continue
        if op not in ops:
            problems.append(f"命令面板 {cid}：契约层里没有 {op}")
            continue
        if op not in table:
            problems.append(f"命令面板 {cid}：{op} 还没进命令表")
            continue
        row_ui = as_list(table[op].get("ui"))
        want = f"view={view}" if view else f"data-action={action}"
        if want not in row_ui:
            problems.append(
                f"命令面板 {cid}：声称对应 {op}，但 {op} 的界面入口里没有 {want}"
                "（要么补进命令表的 ui，要么这条命令不该挂这条 OP）"
            )
        else:
            palette_with_op += 1
            palette_ops.add(op)

    # ---- 命令行（T-G64）：这份投影必须与命令表**双向**对得上 ----
    # 这一节回答的是用户 2026-09-23 那个担心：「直接加一个 CLI 会不会让维护变差？」
    # 不会 —— 前提是 CLI **不许自己有一套命令清单**。所以逐条钉：
    #   ① 只读：每条命令的路由必须是 GET，且挂在 kind=read/derive 的操作上
    #      （写操作 CLI 是另一张卡，要等 AI 边界口径）；
    #   ② 那条路由必须**真是**那条 OP 的路由（不是"我记得是这个路径"）；
    #   ③ 表里的 `cli` 字段与代码里的命令**双向**一致 —— 表里写了命令名，代码里就得有；
    #      代码里有这条命令，表里那条 OP 就得写上它。任一边漏了都是硬冲突。
    cli_names: dict[str, cli_registry.Command] = {}
    cli_ops: set[str] = set()
    for command in cli_registry.COMMANDS:
        method, _, route_path = command.route.partition(" ")
        cid = f"timeflow {command.name}"
        if method != cli_registry.READ_METHOD:
            problems.append(
                f"CLI {cid}：只读 CLI 只许挂 {cli_registry.READ_METHOD}，这里写的是 {method}"
            )
        if command.name in cli_names:
            problems.append(f"CLI：命令名 {command.name!r} 重复")
        cli_names[command.name] = command
        if command.op not in ops:
            problems.append(f"CLI {cid}：契约层里没有 {command.op}")
            continue
        if command.op not in table:
            problems.append(f"CLI {cid}：{command.op} 还没进命令表")
            continue
        row_kind = str(table[command.op].get("kind", ""))
        if row_kind not in READ_KINDS:
            problems.append(
                f"CLI {cid}：挂在 {command.op}（kind={row_kind}）上 —— 只读 CLI 只许挂 "
                f"{sorted(READ_KINDS)}，写操作要单独一张卡"
            )
        row_routes = as_list(table[command.op].get("routes"))
        if command.route not in row_routes:
            problems.append(
                f"CLI {cid}：路由 {command.route!r} 不是 {command.op} 的路由（那条 OP 现在有"
                f" {row_routes}）"
            )
        if cid not in as_list(table[command.op].get("cli")):
            problems.append(
                f"CLI {cid}：代码里有这条命令，但 {command.op} 的 cli 字段里没写它"
                "（表是唯一真源，两边要互相指认）"
            )
        cli_ops.add(command.op)
    for oid, row in sorted(table.items()):
        for entry in as_list(row.get("cli")):
            name = entry.removeprefix("timeflow ").strip()
            if not entry.startswith("timeflow "):
                problems.append(f"{oid}：cli 写法不认识 {entry!r}（应为 timeflow <子命令>）")
            elif name not in cli_names:
                problems.append(f"{oid}：cli 写了 {name!r}，但 CLI 里没有这条命令")
            elif cli_names[name].op != oid:
                problems.append(
                    f"{oid}：cli 写了 {name!r}，但那条命令挂的是 {cli_names[name].op}"
                )
    read_ops = {
        oid for oid, row in table.items() if str(row.get("kind", "")) in READ_KINDS
    }
    no_cli = sorted(oid for oid in read_ops if not as_list(table[oid].get("cli")))

    report = {
        "contract_ops": len(ops),
        "rows": len(table),
        "routes_in_app": len(real_routes),
        "wildcard_routes": wildcards,
        "actions_in_registry": len(actions),
        "views": len(views),
        "rows_without_route": no_route,
        "rows_without_ui": no_ui,
        "palette_commands": len(palette),
        "palette_with_op": palette_with_op,
        "palette_keys": sorted(seen_keys),
        "ops_with_palette_entry": sorted(palette_ops),
        "cli_commands": len(cli_names),
        "ops_with_cli_entry": sorted(cli_ops),
        "rows_without_cli": no_cli,
        "cli_read_ops": sorted(read_ops),
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
    print(
        f"\n  命令行（只读）：{len(cli_names)} 条命令"
        f" · 覆盖 {len(cli_ops)}/{len(read_ops)} 条只读操作"
    )
    if no_cli:
        print(f"  还没填出命令行入口的：{len(no_cli)} 条 → {no_cli}")
    print(
        f"\n  命令面板（⌘K）：{len(palette)} 条命令 · {len(seen_keys)} 个键位"
        f" · 其中 {palette_with_op} 条对得上契约 OP（{len(palette_ops)} 条 OP 有面板入口）"
    )
    if problems:
        print(f"\n=== 硬冲突 {len(problems)} 条（必须修）===")
        for p in problems:
            print(f"  [FAIL] {p}")
        return 1 if args.check else 0
    print("\n命令表与三个真源一致 ✅（没有硬冲突）")
    print("说明：洞（没填出的路由/入口/命令行）是**进度**不是错误 —— 数量下降就是这张表在长。")
    print("说明：命令面板那一节证明「⌘K 不是第二套命令系统」—— 它只是这张表的又一份投影。")
    print("说明：命令行那一节证明「CLI 也不是第二套」—— 每条命令都挂在一条只读操作上。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
