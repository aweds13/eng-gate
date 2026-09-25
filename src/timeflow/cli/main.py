"""命令行入口（T-G64）—— 只读 CLI，命令表的第四份投影。

## 用法

```text
timeflow commands [--kind read|write|derive] [--table] [--json]   自描述
timeflow today|plan|overdue|due|done|week|trend|habits|check [--json] [--db PATH]
timeflow <命令> --help
```

不带参数仍然是**开窗口**（原行为一个没改）；只有第一个词是已知子命令、或 `-h/--help`
时才走这里。

## 「AI 原生」那六条性质，逐条落在哪（T-G31 §2 的表）

| 性质 | 本实现 |
|---|---|
| 输出结构化 | `--json` 打的是**边界原样**的 JSON（不重排、不改名） |
| 自带 schema | `timeflow commands --json` 输出每条命令的**参数 schema**（名字/类型/默认/说明） |
| 非交互 | 永不提问、永不分页（一条命令一次输出） |
| 稳定错误码 | 退出码 0/1/2/3 + `--json` 时 stderr 上的 `{"error":{"code":…}}` |
| 幂等/可逆/破坏性 | 都从命令表里读（`commands --table` 带 `kind`/`reversible`/`ai`） |
| 自描述 | `timeflow commands`（读 `docs/commands.toml`，不另立一份） |

**只读**是这一版的硬口径：每条命令都挂 `GET`，MCP 与写操作排后面（T-G30 §4.3）。

**命令表在运行时只被 `commands` 读**（自描述）。每条数据命令的路由绑定写在
`registry.py` 里，由门禁（`scripts/check_commands.py` 的「CLI 投影」一节）逐条核对 ——
与 ⌘K 面板同一个做法（面板也不在运行时读那张表，而是由门禁证明它对得上）。
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

from timeflow.cli import registry, table
from timeflow.cli.call import ApiError, call_route

if TYPE_CHECKING:  # pragma: no cover —— 只为类型注解
    from timeflow.cli.registry import Command

EXIT_OK = 0
EXIT_USAGE = 1  # 用法错（未知命令 / 未知参数 / 参数类型不对）
EXIT_API = 2  # 边界回了 4xx/5xx
EXIT_ENV = 3  # 环境错（命令表找不到）

EXIT_CODES: dict[str, str] = {
    "0": "成功",
    "1": "用法错误（未知命令 / 未知参数 / 参数类型不对）",
    "2": "接口错误（HTTP 4xx/5xx）",
    "3": "环境错误（找不到 docs/commands.toml）",
}

KINDS = ("read", "write", "derive")

#: 第一个词是这些之一才走 CLI —— 否则仍然开窗口（原行为不变）
CLI_WORDS = frozenset({"commands", "help", *registry.names()})


class UsageError(RuntimeError):
    """用法错（退 1）。"""


def _default_db() -> str:
    """默认库 = 桌面端那个库（`config.toml`）—— 同源，不另开一份数据。"""
    from timeflow.config import load_settings

    return str(load_settings().database.path)


def _usage() -> str:
    lines = [
        "timeflow —— 本地优先的时间与学习投入工具",
        "",
        "  timeflow                     开窗口（默认）",
        "  timeflow <命令> [--json]     只读命令（不起服务、不占端口）",
        "  timeflow commands            我有哪些命令",
        "  timeflow commands --table    整张契约命令表（含 kind / 可逆 / AI 边界）",
        "",
        "命令：",
    ]
    lines += [f"  timeflow {c.name:<9} {c.title}" for c in registry.COMMANDS]
    lines += [
        "",
        "全局：--json（机器读）· --db PATH（换一个库）· --help",
        "退出码：0=成功 1=用法错 2=接口错 3=找不到命令表",
    ]
    return "\n".join(lines)


def _command_help(command: Command) -> str:
    lines = [
        f"timeflow {command.name} —— {command.title}",
        f"  契约操作：{command.op}    路由：{command.route}",
    ]
    if command.params:
        lines.append("  参数：")
        for param in command.params:
            default = f"（默认 {param.default}）" if param.default is not None else ""
            flag = param.name.replace("_", "-")
            lines.append(f"    --{flag} <{param.kind}> {param.help}{default}")
    else:
        lines.append("  参数：无")
    lines += ["  加 --json 打边界原样的 JSON；加 --db PATH 换库。", "  这条命令是只读的。"]
    return "\n".join(lines)


def _coerce(param: registry.Param, raw: str) -> str:
    if param.kind == "int":
        try:
            return str(int(raw))
        except ValueError:
            raise UsageError(f"--{param.name} 要一个整数，收到 {raw!r}") from None
    return raw


def _parse(command: Command, tail: list[str], db: str) -> tuple[dict[str, str], str]:
    """解析一条命令的参数（只认它声明过的那些 + `--db`）。"""
    allowed = {param.name: param for param in command.params}
    params: dict[str, str] = {}
    index = 0
    while index < len(tail):
        token = tail[index]
        flag, _, inline = token.partition("=")
        if not flag.startswith("-"):
            raise UsageError(f"多余的参数 {token!r}（参数一律写成 --名字 值）")
        value = inline
        used_next = False
        name = flag.lstrip("-").replace("-", "_")
        if name == "db" or name in allowed:
            if not value and index + 1 < len(tail):
                value, used_next = tail[index + 1], True
            if not value:
                raise UsageError(f"{flag} 需要一个值")
        if name == "db":
            db = value
        elif name in allowed:
            params[allowed[name].name] = _coerce(allowed[name], value)
        else:
            known = "、".join(f"--{p.name.replace('_', '-')}" for p in command.params)
            raise UsageError(f"不认识的参数 {token!r}；这条命令的参数：{known or '（无）'}、--db")
        index += 2 if used_next else 1
    return params, db


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
        "read_only": True,
        "exit_codes": EXIT_CODES,
        "commands": [
            {
                "name": command.name,
                "op": command.op,
                "title": command.title,
                "route": command.route,
                "params": [
                    {
                        "name": param.name,
                        "kind": param.kind,
                        "default": param.default,
                        "help": param.help,
                    }
                    for param in command.params
                ],
            }
            for command in registry.COMMANDS
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

    selected = [c for c in registry.COMMANDS if not kind or rows.get(c.op, {}).get("kind") == kind]
    if as_json:
        payload = _self_description()
        keep = {c.name for c in selected}
        payload["commands"] = [c for c in payload["commands"] if c["name"] in keep]
        payload["table"] = path
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return EXIT_OK
    print(f"只读命令 {len(selected)} 条（命令表：{path}）")
    for command in selected:
        print(f"  timeflow {command.name:<9} {command.op}")
        print(f"    {command.title}")
        print(f"    → {command.route}")
    print("  加 --json 看参数 schema；加 --table 看整张契约命令表。")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = [str(a) for a in (sys.argv[1:] if argv is None else argv)]
    as_json = "--json" in args
    rest = [a for a in args if a != "--json"]

    if not rest:
        print(_usage(), file=sys.stderr)
        return EXIT_USAGE
    if rest[0] in ("-h", "--help", "help"):
        print(_usage())
        return EXIT_OK

    name, tail = rest[0], rest[1:]
    if name == "commands":
        return _run_commands(tail, as_json)
    command = registry.by_name().get(name)
    if command is None:
        known = "、".join(registry.names())
        return _fail(EXIT_USAGE, "usage", f"没有 {name!r} 这条命令；有：{known}", as_json)

    if any(arg in ("-h", "--help") for arg in tail):
        print(_command_help(command))
        return EXIT_OK

    try:
        params, db = _parse(command, tail, _default_db())
        data = call_route(db, command.route, params)
    except UsageError as exc:
        return _fail(EXIT_USAGE, "usage", str(exc), as_json)
    except ApiError as exc:
        return _fail(EXIT_API, f"api_{exc.status}", exc.detail, as_json)

    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return EXIT_OK
    for line in command.human(data):
        print(line)
    return EXIT_OK
