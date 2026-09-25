"""命令行入口（T-G64 只读 → T-G65 加写入 + MCP）—— 命令表的投影。

## 用法

```text
timeflow commands [--kind read|write|derive] [--table] [--json]   自描述
timeflow today|plan|overdue|due|done|week|trend|habits|check|…[--json] [--db PATH]
timeflow add-task --in-title … --allow-write……（写命令，默认关）
timeflow mcp [--allow-write]       把同一批命令当 MCP 工具提供给 AI 客户端
timeflow <命令> --help
```

不带参数仍然是**开窗口**（原行为一个没改）；只有第一个词是已知子命令、或 `-h/--help`
时才走这里。

## 写入：默认关，而且**每次**都要说出口（T-G65）

用户 2026-09-25 定的三条：只做界面上已有的那些（OP 的 `ui` 必须非空，门禁判）、
**默认关**、语义与界面完全一样。这里的"默认关"落在一条**结构**判据上：
写命令必须带 `--allow-write`，否则退 **4** + 机器码 `write_disabled`，
**在发请求之前**就拒绝（库一个字节都不动，有测试钉着）。
MCP 那边同一个开关（`timeflow mcp --allow-write`）：不给就不列出写工具。

为什么是**每次带**而不是一个持久设置：持久开关打开就忘了关，而写操作的风险是一次性的；
每带一次，人和调用方在那一刻都知道自己在写。持久开关要做就得连设置页一起做（属产品面），
所以如实记成"没做"，不在这里偷偷定。

## 「AI 原生」那六条性质，逐条落在哪（T-G31 §2 的表）

| 性质 | 本实现 |
|---|---|
| 输出结构化 | `--json` 打的是**边界原样**的 JSON（不重排、不改名） |
| 自带 schema | `timeflow commands --json` 输出每条命令的**参数 schema**（名字/类型/默认/说明） |
| 非交互 | 永不提问、永不分页（一条命令一次输出） |
| 稳定错误码 | 退出码 0/1/2/3/4 + `--json` 时 stderr 上的 `{"error":{"code":…}}` |
| 幂等/可逆/破坏性 | 都从命令表里读（`commands --table` 带 `kind`/`reversible`/`ai`） |
| 自描述 | `timeflow commands`（读 `docs/commands.toml`，不另立一份） |

只读命令"不留副作用"：库文件不存在时拒绝工作（不替你建一个空库并回一份空数据），
库/表打不开时给稳定错误码而不是栈（T-G66）；**写命令同样过这一关**（T-G65）。

**命令表在运行时只被 `commands` 读**（自描述）。每条数据命令的路由绑定写在
`registry.py` 里，由门禁（`scripts/check_commands.py` 的「命令行投影」「MCP 投影」两节）
逐条核对 —— 与 ⌘K 面板同一个做法（面板也不在运行时读那张表，而是由门禁证明它对得上）。
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

from timeflow.cli import registry, table
from timeflow.cli.call import ApiError, DatabaseError, call_route

if TYPE_CHECKING:  # pragma: no cover —— 只为类型注解
    from timeflow.cli.registry import Command

EXIT_OK = 0
EXIT_USAGE = 1  # 用法错（未知命令 / 未知参数 / 参数类型不对 / 少必填项）
EXIT_API = 2  # 边界回了 4xx/5xx
EXIT_ENV = 3  # 环境错（命令表找不到、库不存在/打不开）
EXIT_REFUSED = 4  # 被策略拒绝：写命令没带 --allow-write

EXIT_CODES: dict[str, str] = {
    "0": "成功",
    "1": "用法错误（未知命令 / 未知参数 / 参数类型不对 / 少必填项）",
    "2": "接口错误（HTTP 4xx/5xx）",
    "3": "环境错误（库或命令表的问题）",
    "4": "被拒绝（写操作默认关：加 --allow-write 明确表示要写）",
}

#: 稳定的机器码（`--json` 时 stderr 上的 `{"error":{"code":…}}`）—— 与退出码分开写，
#: 因为"退 3"下面有好几件不同的事，脚本要能分辨（这也是 AI 原生六条里"稳定错误码"那条）。
ERROR_CODES: dict[str, int] = {
    "usage": EXIT_USAGE,
    "api_4xx": EXIT_API,
    "db_missing": EXIT_ENV,
    "db_unopenable": EXIT_ENV,
    "table_missing": EXIT_ENV,
    "table_broken": EXIT_ENV,
    "write_disabled": EXIT_REFUSED,
}

KINDS = ("read", "write", "derive")

#: 写命令必须显式带上它（默认关；`timeflow mcp` 也认同一个开关）
WRITE_FLAG = "--allow-write"

#: 第一个词是这些之一才走 CLI —— 否则仍然开窗口（原行为不变）
CLI_WORDS = frozenset({"commands", "help", "mcp", *registry.names()})


class UsageError(RuntimeError):
    """用法错（退 1）。"""


def default_db() -> str:
    """默认库 = 桌面端那个库（`config.toml`）—— 同源，不另开一份数据。"""
    from timeflow.config import load_settings

    return str(load_settings().database.path)


def _usage() -> str:
    lines = [
        "timeflow —— 本地优先的时间与学习投入工具",
        "",
        "  timeflow                          开窗口（默认）",
        "  timeflow <命令> [--json]          命令（不起服务、不占端口）",
        "  timeflow mcp [--allow-write]      把同一批命令作为 MCP 工具给 AI 客户端（stdio）",
        "  timeflow commands                 我有哪些命令",
        "  timeflow commands --table         整张契约命令表（含 kind / 可逆 / AI 边界）",
        "",
        "只读命令：",
    ]
    lines += [f"  timeflow {c.name:<12} {c.title}" for c in registry.COMMANDS]
    lines += ["", "写命令（默认关：每条都要加 " + WRITE_FLAG + "）："]
    lines += [f"  timeflow {c.name:<12} {c.title}" for c in registry.WRITE_COMMANDS]
    lines += [
        "",
        "全局：--json（机器读）· --db PATH（换库）· " + WRITE_FLAG + "（写命令的必要开关）· --help",
        "退出码：0=成功 1=用法错 2=接口错 3=环境错 4=写操作没开",
    ]
    return "\n".join(lines)


def _command_help(command: Command) -> str:
    write = registry.is_write(command)
    lines = [
        f"timeflow {command.name} —— {command.title}",
        f"  契约操作：{command.op}    路由：{command.route}",
    ]
    if command.params:
        lines.append("  参数：")
        for param in command.params:
            default = f"（默认 {param.default}）" if param.default is not None else ""
            flag = param.name.replace("_", "-")
            place = {"query": "查询", "path": "路径", "body": "请求体"}
            where = place.get(param.where, param.where)
            need = "必填 · " if param.required else ""
            kind = "开关" if param.kind == "bool" else f"<{param.kind}>"
            lines.append(f"    --{flag} {kind} {need}{param.help}{default} → {where}")
    else:
        lines.append("  参数：无")
    lines += ["  加 --json 打边界原样的 JSON；加 --db PATH 换库。"]
    if write:
        lines.append(f"  ★ 这条会改数据：必须加 {WRITE_FLAG}（写操作默认关）。")
    else:
        lines.append("  这条命令是只读的。")
    return "\n".join(lines)


def _coerce(param: registry.Param, raw: str) -> str:
    if param.kind == "int":
        try:
            return str(int(raw))
        except ValueError:
            raise UsageError(f"--{param.name} 要一个整数，收到 {raw!r}") from None
    return raw


def _typed(value: str, param: registry.Param) -> Any:
    """请求体里的值要**真类型**（JSON 里 `"1500"` 与 `1500` 不是一回事）。"""
    if param.kind == "int":
        try:
            return int(value)
        except ValueError:
            raise UsageError(f"--{param.name} 要一个整数，收到 {value!r}") from None
    if param.kind == "bool":
        lowered = value.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
        raise UsageError(f"--{param.name} 是开关，写 true / false（收到 {value!r}）")
    return value


def _parse(
    command: Command, tail: list[str], db: str
) -> tuple[dict[str, str], dict[str, str], dict[str, Any], str]:
    """解析一条命令的参数（只认它声明过的那些 + `--db`），并按 `where` 分到三处去。"""
    allowed = {param.name: param for param in command.params}
    raw: dict[str, str] = {}
    index = 0
    while index < len(tail):
        token = tail[index]
        flag, _, inline = token.partition("=")
        if not flag.startswith("-"):
            raise UsageError(f"多余的参数 {token!r}（参数一律写成 --名字 值）")
        name = flag.lstrip("-").replace("-", "_")
        param = allowed.get(name)
        if name == "db" or param is not None:
            value, used_next = inline, False
            if param is not None and param.kind == "bool" and not inline:
                raw[name] = "true"  # 开关：出现即为真（要 false 就写 --名字=false）
                index += 1
                continue
            if not value and index + 1 < len(tail):
                value, used_next = tail[index + 1], True
            if not value:
                raise UsageError(f"{flag} 需要一个值")
            if name == "db":
                db = value
            else:
                raw[name] = _coerce(param, value)  # type: ignore[arg-type]
        else:
            known = "、".join(f"--{p.name.replace('_', '-')}" for p in command.params)
            raise UsageError(f"不认识的参数 {token!r}；这条命令的参数：{known or '（无）'}、--db")
        index += 2 if used_next else 1

    path_params: dict[str, str] = {}
    query: dict[str, str] = {}
    body: dict[str, Any] = {}
    for name, param in allowed.items():
        if name not in raw and param.default is not None:
            raw[name] = param.default  # 声明了默认值就真的用它（schema 里写着默认，不能是句空话）
        if name not in raw:
            if param.required:
                raise UsageError(f"缺必填参数 --{name.replace('_', '-')}（{param.help}）")
            continue
        if param.where == "path":
            path_params[name] = raw[name]
        elif param.where == "body":
            body[name] = _typed(raw[name], param)
        else:
            query[name] = raw[name]
    return path_params, query, body, db


def _fail(code: int, kind: str, detail: str, as_json: bool) -> int:
    """错误一律走 **stderr**（stdout 只放数据），`--json` 时给机器读的形状。"""
    if as_json:
        payload = {"error": {"code": kind, "detail": detail}}
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
    else:
        print(f"[{kind}] {detail}", file=sys.stderr)
    return code


def _self_description() -> dict[str, Any]:
    """自描述（AI 原生六条里的"自带 schema"+"自描述"）。"""
    return {
        "write_gate": {
            "flag": WRITE_FLAG,
            "rule": "写命令默认关：每次调用都要显式带上这个开关，否则退 4（write_disabled）",
        },
        "exit_codes": EXIT_CODES,
        "errors": ERROR_CODES,
        "commands": [
            {
                "name": command.name,
                "op": command.op,
                "title": command.title,
                "route": command.route,
                "write": registry.is_write(command),
                "params": [
                    {
                        "name": param.name,
                        "kind": param.kind,
                        "default": param.default,
                        "help": param.help,
                        "where": param.where,
                        "required": param.required,
                    }
                    for param in command.params
                ],
            }
            for command in registry.all_commands()
        ],
    }


def _parse_commands_flags(tail: list[str]) -> tuple[str, bool]:
    """`commands` 自己的两个开关：`--kind X` 与 `--table`。"""
    want_table = "--table" in tail
    rest = [t for t in tail if t != "--table"]
    kind = ""
    if rest:
        if rest[0] == "--kind" and len(rest) == 2:
            kind = rest[1]
        elif rest[0].startswith("--kind=") and len(rest) == 1:
            kind = rest[0].split("=", 1)[1]
        else:
            raise UsageError("commands 只认 --kind read|write|derive 与 --table")
    if kind and kind not in KINDS:
        raise UsageError(f"--kind 只能是 {'/'.join(KINDS)}，收到 {kind!r}")
    return kind, want_table


def _run_commands(tail: list[str], as_json: bool) -> int:
    """自描述：CLI 有哪些命令；`--table` 则打**整张契约命令表**。"""
    try:
        kind, want_table = _parse_commands_flags(tail)
    except UsageError as exc:
        return _fail(EXIT_USAGE, "usage", str(exc), as_json)
    try:
        rows = table.load()
        path = str(table.find_table())
    except table.TableMissingError as exc:
        return _fail(EXIT_ENV, "table_missing", str(exc), as_json)
    except table.TableBrokenError as exc:
        return _fail(EXIT_ENV, "table_broken", str(exc), as_json)

    if want_table:
        chosen = {oid: row for oid, row in rows.items() if not kind or row.get("kind") == kind}
        if as_json:
            print(json.dumps({"table": path, "rows": chosen}, ensure_ascii=False, indent=2))
            return EXIT_OK
        print(f"契约命令表：{len(chosen)} 条（{path}）")
        for oid, row in chosen.items():
            routes = row.get("routes")
            first = routes[0] if isinstance(routes, list) and routes else "（没有路由）"
            print(f"  {oid:<8} {row.get('title', '')}  [{row.get('kind', '')}]  {first}")
        return EXIT_OK

    every = registry.all_commands()
    selected = [c for c in every if not kind or rows.get(c.op, {}).get("kind") == kind]
    if as_json:
        payload = _self_description()
        keep = {c.name for c in selected}
        payload["commands"] = [c for c in payload["commands"] if c["name"] in keep]
        payload["table"] = path
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return EXIT_OK
    reads = [c for c in selected if not registry.is_write(c)]
    writes = [c for c in selected if registry.is_write(c)]
    print(f"命令 {len(selected)} 条（只读 {len(reads)} + 写 {len(writes)}；命令表：{path}）")
    for command in reads:
        print(f"  timeflow {command.name:<12} {command.op}")
        print(f"    {command.title}")
        print(f"    → {command.route}")
    if writes:
        print(f"  写命令（默认关，要加 {WRITE_FLAG}）：")
        for command in writes:
            print(f"  timeflow {command.name:<12} {command.op}")
            print(f"    {command.title}")
            print(f"    → {command.route}")
    print("  加 --json 看参数 schema；加 --table 看整张契约命令表。")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = [str(a) for a in (sys.argv[1:] if argv is None else argv)]
    as_json = "--json" in args
    allow_write = WRITE_FLAG in args
    raw_rest = [a for a in args if a != "--json"]  # 含 --allow-write（mcp 要从自己的 args 里读它）
    rest = [a for a in raw_rest if a != WRITE_FLAG]

    if not rest:
        print(_usage(), file=sys.stderr)
        return EXIT_USAGE
    if rest[0] in ("-h", "--help", "help"):
        # `timeflow help today` 与 `timeflow today --help` 是同一件事：
        # 自描述的命令行不该在"我想知道这条命令怎么用"时只回一份总目录
        wanted = rest[1] if len(rest) > 1 else ""
        target = registry.by_name().get(wanted)
        print(_command_help(target) if target else _usage())
        return EXIT_OK

    name, tail = rest[0], rest[1:]
    if name == "commands":
        return _run_commands(tail, as_json)
    if name == "mcp":
        # MCP 是**同一个开关**的另一个出口：不给 --allow-write 就不列出写工具。
        # 这里传的是**没剥掉开关**的 tail —— MCP 客户端的配置就是
        # `command = timeflow` / `args = ["mcp", "--allow-write"]`，开关必须能从 args 里给。
        from timeflow.mcp import server

        return server.serve(raw_rest[1:], as_json=as_json)
    command = registry.by_name().get(name)
    if command is None:
        known = "、".join(registry.names())
        return _fail(EXIT_USAGE, "usage", f"没有 {name!r} 这条命令；有：{known}", as_json)

    if any(arg in ("-h", "--help") for arg in tail):
        print(_command_help(command))
        return EXIT_OK

    # ★ 默认关（T-G65）：写命令没带开关就**在这里**停住 —— 请求一个字节都没发出去，
    #   库也就一个字节都没动（`tests/test_cli_writes.py` 拿"任务数没变"钉着这条）。
    if registry.is_write(command) and not allow_write:
        return _fail(
            EXIT_REFUSED,
            "write_disabled",
            f"{command.name} 会改数据，默认不执行；确认要写就加 {WRITE_FLAG}。",
            as_json,
        )

    try:
        path_params, query, body, db = _parse(command, tail, default_db())
        data = call_route(
            db,
            command.route,
            query,
            path_params=path_params,
            body=body if registry.is_write(command) else None,
        )
    except UsageError as exc:
        return _fail(EXIT_USAGE, "usage", str(exc), as_json)
    except DatabaseError as exc:
        return _fail(EXIT_ENV, exc.code, exc.detail, as_json)
    except ApiError as exc:
        return _fail(EXIT_API, f"api_{exc.status}", exc.detail, as_json)

    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return EXIT_OK
    for line in command.human(data):
        print(line)
    return EXIT_OK
