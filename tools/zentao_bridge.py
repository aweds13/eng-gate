r"""禅道桥（只读那一半）`tools/zentao_bridge.py`（卡 211 · T-G321）—— 只标准库。

只做一件事：把禅道 22.6 REST v1 的 **项目 / 迭代 / 任务** 拉成一份本仓能读的读数。
`--json` 给机器、`--report` 给人读。字段名与映射的真源是 `docs/zentao-bridge.toml`。

★ 只读：本工具**只发 GET**，对禅道一个字节都不写。
  · 登录（`POST /api.php/v1/tokens` 会建会话 = 写）**不在本工具里做** —— token 走环境变量
    `ZENTAO_TOKEN`（在桥外先取好；取法见 `docs/zentao-bridge.toml` 的 `[api]`）。
  · 「起子进程要带 NO_WINDOW」那条铁律与本工具无关：本工具只用标准库 urllib，不起子进程。

★ 离线可用：禅道没开 / 连不上 / 鉴权失败 / 响应坏 / 缺字段 —— 每一样**分开报**，
  报清是哪一步、哪种错（见退出码），**绝不用空对象冒充「拉到了、是空的」**。

用法：
    python -X utf8 tools/zentao_bridge.py --report     # 给人读
    python -X utf8 tools/zentao_bridge.py --json       # 给机器（同输入 ⇒ 逐字节相同）

环境变量：`ZENTAO_URL`（如 http://127.0.0.1）、`ZENTAO_TOKEN`。
退出码：0 成功 / 2 配置或鉴权缺失 / 3 连不上 / 4 HTTP 4xx（401/403…）/
        5 响应不是 JSON / 6 响应结构缺必需字段。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

#: 端点表（读数分段名, REST v1 路径, 响应里那一层的键）。
#: 证据：app/zentao/api/v1/entries/{projects,executions,tasks}.php（见 docs/zentao-bridge.toml）。
ENDPOINTS: tuple[tuple[str, str, str], ...] = (
    ("projects", "/api.php/v1/projects", "projects"),
    ("executions", "/api.php/v1/executions", "executions"),
    ("tasks", "/api.php/v1/tasks", "tasks"),
)

#: 每个读数条目**必须**有的字段；缺任一 ⇒ `badshape`（卡 211 §3，不许静默给空）。
REQUIRED_ITEM_FIELDS: tuple[str, ...] = ("id", "name")

#: 规范字段白名单：只留跨版本稳的标量（用户对象取 account）。真源见 TOML 的 [[mapping]]。
FIELD_LIST: dict[str, tuple[str, ...]] = {
    "projects": ("id", "name", "code", "model", "type", "status", "PM",
                 "begin", "end", "progress"),
    "executions": ("id", "name", "project", "code", "type", "parent",
                   "begin", "end", "status", "progress", "isParent"),
    "tasks": ("id", "name", "execution", "project", "status", "pri", "assignedTo",
              "estimate", "consumed", "left", "deadline"),
}

#: 错误种类 → 退出码。
EXIT_CODES: dict[str, int] = {
    "config": 2,
    "connect": 3,
    "http": 4,
    "badjson": 5,
    "badshape": 6,
}


class BridgeError(Exception):
    """按「哪一步 + 哪种错」报出的桥错（kind 决定退出码）。"""

    def __init__(self, kind: str, step: str, detail: str) -> None:
        super().__init__(f"{kind}: {step}: {detail}")
        self.kind = kind
        self.step = step
        self.detail = detail

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.kind]


def resolve_config(url: str | None, token: str | None) -> tuple[str, str]:
    """取地址与 token（命令行优先，其次环境变量）。缺哪个报哪个，别混。"""
    base = (url or os.environ.get("ZENTAO_URL") or "").strip()
    tok = (token or os.environ.get("ZENTAO_TOKEN") or "").strip()
    if not base:
        raise BridgeError("config", "url", "没有禅道地址（--url 或环境变量 ZENTAO_URL）")
    if not base.startswith(("http://", "https://")):
        raise BridgeError("config", "url", f"地址得带 http:// 或 https:// 前缀：{base!r}")
    if not tok:
        raise BridgeError(
            "config", "token",
            "没有 token（--token 或环境变量 ZENTAO_TOKEN）；"
            "禅道 REST v1 要先在桥外 POST /api.php/v1/tokens 取一个（见 docs/zentao-bridge.toml）",
        )
    return base.rstrip("/"), tok


def _http_get(url: str, token: str, timeout: float, step: str) -> str:
    """发一个只读 GET，失败按种类抛 BridgeError。**只 GET，永不写。**"""
    req = urllib.request.Request(url, method="GET")
    req.add_header("Token", token)
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 —— 固定 http(s)
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise BridgeError("http", step, f"HTTP {exc.code}：{url}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        raise BridgeError("connect", step, f"连不上 {url}：{reason}") from exc


def _norm(value: object) -> object:
    """用户对象 {account,avatar,realname} → account；其余原样。"""
    if isinstance(value, dict):
        return value.get("account", value)
    return value


def parse_section(section: str, raw: str, step: str) -> list[dict[str, object]]:
    """把一段响应正文解析成规范条目表；坏 JSON / 缺字段各自报清。"""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BridgeError("badjson", step, f"响应不是 JSON：{exc}") from exc

    items = data.get(section) if isinstance(data, dict) else None
    if not isinstance(items, list):
        got = type(items).__name__
        raise BridgeError("badshape", step, f"响应顶层没有数组 {section!r}，实为 {got}")

    normalized: list[dict[str, object]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise BridgeError("badshape", step, f"{section}[{index}] 不是对象")
        for field in REQUIRED_ITEM_FIELDS:
            if field not in item:
                raise BridgeError("badshape", step, f"{section}[{index}] 缺必需字段 {field!r}")
        normalized.append({name: _norm(item.get(name)) for name in FIELD_LIST[section]})
    return normalized


def fetch_bundle(base: str, token: str, timeout: float) -> dict[str, object]:
    """依次拉三段读数；任一段出错即抛（保持「哪一步」清晰）。"""
    bundle: dict[str, object] = {"ok": True, "source": base}
    for name, path, section in ENDPOINTS:
        raw = _http_get(base + path, token, timeout, name)
        bundle[section] = parse_section(section, raw, name)
    return bundle


def render_report(bundle: dict[str, object]) -> str:
    """给人读的那份。"""
    lines = [f"禅道桥（只读）读数 —— {bundle['source']}"]
    titles = {"projects": "项目", "executions": "迭代", "tasks": "任务"}
    for section, title in titles.items():
        rows = bundle[section]
        lines.append(f"{title} {len(rows)} 个：")
        for row in rows:
            detail = "  ".join(f"{k}={row.get(k)}" for k in FIELD_LIST[section] if k != "name")
            lines.append(f"  #{row.get('id')} {row.get('name')}  {detail}")
    return "\n".join(lines)


def render_error_json(exc: BridgeError) -> str:
    payload = {"ok": False, "error": {"kind": exc.kind, "step": exc.step, "detail": exc.detail}}
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def render_error_report(exc: BridgeError) -> str:
    labels = {"config": "配置/鉴权缺失", "connect": "连不上", "http": "HTTP 4xx",
              "badjson": "响应不是 JSON", "badshape": "响应结构缺字段"}
    hint = ""
    if exc.kind == "connect":
        hint = "\n  提示：禅道没开？先确认这个地址上真有禅道在跑。"
    elif exc.kind == "http":
        hint = "\n  提示：401=没登录/token 失效；403=没权限。核实 token 与账号权限。"
    return f"[{labels[exc.kind]}] 步骤：{exc.step}\n  详情：{exc.detail}{hint}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zentao_bridge.py",
        description="禅道桥（只读）：把项目/迭代/任务拉成一份读数。",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="输出机器可读 JSON（确定性）")
    mode.add_argument("--report", action="store_true", help="输出人类可读报告（默认）")
    parser.add_argument("--url", default=None, help="禅道地址（默认环境变量 ZENTAO_URL）")
    parser.add_argument("--token", default=None, help="会话 token（默认环境变量 ZENTAO_TOKEN）")
    parser.add_argument("--timeout", type=float, default=5.0, help="每个请求超时秒数（默认 5）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    as_json = args.json
    try:
        base, token = resolve_config(args.url, args.token)
        bundle = fetch_bundle(base, token, args.timeout)
    except BridgeError as exc:
        out = render_error_json(exc) if as_json else render_error_report(exc)
        print(out, file=sys.stdout if as_json else sys.stderr)
        return exc.exit_code

    if as_json:
        print(json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_report(bundle))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
