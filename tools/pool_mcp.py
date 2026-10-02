r"""外包号池的 **MCP 只读面**（stdio · JSON-RPC 2.0）—— 换哪个窗口的 AI 都能问"现在号池在跑什么"。

## 为什么有它（用户原话）

「外包调用能不能做成 MCP，更适合不同窗口 AI 调用」→「我会在 DSH 里不同窗口用」。
派活那一套散在 6 个脚本里、**靠约定**（主树要干净 / 切片里写工作树 / 别并行两池），换个窗口
的 AI 得从头学；而且**谁也不知道别的窗口在跑什么**。这一卡把那套现状**只读地**摊成六个工具。

## 协议这一半：**照抄先例** `src/timeflow/mcp/server.py`（185 行、手写零依赖、被真客户端用过）

一行一个 JSON-RPC 消息（MCP 的 stdio 传输就是这个 framing）。支持五个方法：

| 方法 | 回什么 |
|---|---|
| `initialize` | 协议版本 + `capabilities.tools` + `serverInfo`（+ 一段 `instructions` 说明边界） |
| `notifications/initialized` | 不回（通知没有 `id` —— JSON-RPC 的规矩，也是客户端不卡住的前提） |
| `tools/list` | 工具清单（**写死在 `TOOL_SPECS` / `WRITE_TOOL_SPECS`**；写工具按 env 列不列） |
| `tools/call` | 跑一个工具 → 人话文本 + **唯一标记**之后的机器可读块（见 `_fence`） |
| `ping` | `{}` |

不认的方法回 `-32601`，不认的工具名回 `-32602`。**未知工具名明确报错、绝不崩**（先例同款）。

## ★ 零依赖 & 编码（照抄先例的 `_pin_stdio_utf8` / `_emit` / `_read_line`）

本仓不引第三方 MCP SDK，只用标准库。stdio 说明：Windows 上 Python 的 `sys.stdin/stdout`
默认跟**控制台代码页**（这台 cp936）——不钉的话中文出去是 GBK、进来会把服务端**打崩**。
所以协议这一层把三件套钉成 UTF-8，并按**字节**逐行读（一行坏字节只坏那一行，不打死循环）。

## ★★ 六个只读工具（一个都不许写文件）

| 工具 | 干什么 | 底层 |
|---|---|---|
| `pool_plan` | 队列与冲突域 | **import** `tools/pool/plan.py`（不再 shell 出去） |
| `job_list` | 扫 `wb-*.jsonl` → 在跑/已判决/断了（看证据不猜） | **import** `tools/pool/jobs.py` |
| `job_status(card)` | 时间线 + 仓库状态 | **import** `tools/pool/jobs.py`（读 log + 渲染） |
| `job_result(card)` | 判决与摘要的**原文**（截断**明示总长**） | **import** `tools/pool/jobs.py` |
| `lock_status` | 门禁锁：哪把、谁的、租约剩多久 | `gate_lock.py status`（唯一 subprocess，见下） |
| `pool_models` | 号池可用模型（批准 ∩ 可用） | **import** `tools/pool/models.py`（只读快照） |

★ 卡 106（T-G202）：六个工具的**逻辑**已全部收敛到 `tools/pool/` 包，CLI 与 MCP **共用同一批函数**。
`subprocess` 只留**一处** —— `lock_status` 跑 `gate_lock.py`：那是 `gates/diag/` 下的**独立脚本**
（`-P` 是铁律 24：那里的同名脚本会被当模块顶掉），且既有测试把"经 `_run` 调它"钉住了。

## ★★ 写面（卡 111 · T-G208）：`pool_dispatch` / `pool_cancel` —— 要 `POOL_MCP_WRITE=1` 才列

两个写工具**默认隐身**（没有那个 env 就只列六个只读工具）：起工人 / 杀进程不该被"顺手"调到。
每次写调用还必须 `arguments.confirm` **等于卡号**（防手滑）。六个只读工具**不需要任何 env**。

**`pool_dispatch(card, tree, spec?, model?, pool?, note?)`** —— 顺序**固定**：
① 干跑（`pool.guards` 三条 + `pool.registry` 的租约判据，**import 调用**）→ 有咬就**不派活**、
把逐条原因原样回给调用方（`isError=true`）；② `pool.registry.reserve(...)` **先占位**（并发安全
的关键：不能"先派活后登记"）；③ 起工人 `wb_dispatch.py … --cwd <树绝对路径> --lean --detach
--execute`（**必须 `--detach`**：MCP 工具调用不能阻塞几十分钟）；④ 起不来就
`pool.registry.release(...)` **回滚**并如实报错。参数**写死、不透传危险项**：不给 `--force` /
`--allow` / `--no-preflight` / `--resume`；`--model` 只许取 `wb_dispatch.MODEL_WHITELIST` 里的值
（不在就拒），不给用默认。

**`pool_cancel(card, reason?)`** —— 只取消**本机登记里那一条租约**的 pid：
★ 先核对身份（`tasklist /FI "PID eq <n>" /FO CSV` 的映像名必须是 `node.exe` / `python.exe`），
不对就**拒绝动手**并把"人工该敲什么"的确切命令印出来；★★ **绝不用 `os.kill(pid, 0)` 探活**
（Windows 上 CPython 的 `os.kill` 走 `TerminateProcess` —— 那不是探活、那是**把人杀了**，
见 `复盘/口径坑.md` 第 27 条）。成功后写 `gates/diag/wb-<卡>.cancel.txt`（谁 / 什么时候 /
为什么）并 `pool.registry.release(card)`。

### 六条不变量：哪条谁判（★ 不在本模块重写任何判据）

| # | 不变量 | 谁判 |
|---|---|---|
| ① | 一棵树同时一个写者 | `pool.guards.tree_guard` |
| ② | 冲突域不许相交（域从 backlog 读，**查不到就拒**，别猜空域） | `pool.guards.domain_guard` |
| ③ | 门禁还在跑就不动手 | `pool.guards.lock_guard` |
| ④ | 内存闸 | **委托** `wb_dispatch.py` 的前置检查（本模块**不写**内存判据） |
| ⑤ | 日志不许覆盖 | `pool.guards.log_guard` + **不给** `--force`（wb_dispatch 自己挑 r2） |
| ⑥ | 模型白名单 | `wb_dispatch.MODEL_WHITELIST`（硬闸门）+ `pool.models`（批准 ∩ 可用） |

★ 干跑与登记都经 `pool.registry.list_reservations` + `pool.guards`（同一批纯函数）—— 派活的
"能不能占"与 CLI `wb_registry.py check` 是**同一处判据**，不另写一份（本仓最忌两份真源）。

## 诚实边界（如实写）

- `pool_models` 读的是**快照** `models.live.json`（带 `at` 时间戳），**不是现场拉取**：
  现场拉取（`pool_models.py --check`）既要**联网**又会**写快照文件**，两样都被本卡禁止。
  所以这里只读它已经落盘的输入，并在输出里**明说**"来自快照 at=…"。
- 号池目录（`infra/pool/`）**不在本仓**（它在 `jelly_ware/` 下、跨项目复用）。本模块从
  `ROOT` 起**逐级向上**找 `<祖先>/infra/pool/pool_models.py`；找不到就如实说"没有"并列出找过哪些。
- 传给人看/给客户端的东西只有工具；**没有** `resources` / `prompts` / `logging`（先例也一样）。
- 这一卡只做到"另一个实现能读懂报文"这一层；**真在 DSH 里接一次**要人工点（注册写法见卡 §9）。

## 用法

    python -X utf8 tools/pool_mcp.py          # stdio 起服务（一行一个 JSON-RPC）
    python -X utf8 tools/pool_mcp.py --help
"""

from __future__ import annotations

import datetime
import json
import locale
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import wb_dispatch  # noqa: PLC0415 —— 模型白名单 / 默认模型的**唯一**真源（卡 111 §2 ⑥）
from pool import guards, registry
from pool.jobs import (
    HEARTBEAT_SECONDS,
    REPORT_MAX_CHARS,
    STALL_SECONDS,
    card_artifacts,
    diag_dir,
    parse_events,
    render_timeline,
    scan_jobs,
)
from pool.locks import is_empty as lock_is_empty
from pool.locks import status_argv as lock_status_argv
from pool.models import find_pool_dir, load_pool_models
from pool.plan import BacklogError, load_backlog, plan_report

if TYPE_CHECKING:  # pragma: no cover —— 只为类型注解（ruff TCH）
    from typing import Any

#: 阈值从 `pool.jobs` 转发（与 `tools/wb_dispatch.py` **同一口径**）—— 供既有测试读。
__all__ = ["HEARTBEAT_SECONDS", "STALL_SECONDS"]

#: 我们支持的协议版本（`initialize` 时优先回客户端那个"我们认识"的版本）。
PROTOCOL_VERSION = "2025-06-18"
KNOWN_PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18")
SERVER_NAME = "pool"
SERVER_VERSION = "1.0"

JSONRPC_PARSE_ERROR = -32700
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603

ROOT = Path(__file__).resolve().parent.parent


# ================================================================ 协议边界：UTF-8 stdio（照抄先例）


def _pin_stdio_utf8() -> None:
    """把 stdio 三件套钉成 **UTF-8**（先例 T-G74 同款）。

    不钉的实测后果（先例里写死过）：**出去**中文按 GBK 写 → 规范客户端看到乱码；
    **进来**的 UTF-8 被按 cp936 解 → 孤立代理 → `json.dumps(...).encode("utf-8")` 抛
    `UnicodeEncodeError` → **整个服务端当场崩**。

    被换成 `StringIO`（测试 redirect 过）时**不猜、不报错**：没有 `reconfigure` 就跳过。
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="strict", newline="\n")
        except (ValueError, OSError):  # pragma: no cover —— 平台/流类型不给改时不至于炸
            continue


def _emit(payload: dict[str, Any]) -> None:
    """把一条协议消息写出去（**一行一个 JSON-RPC**，只有这一处写 stdout）。

    走**字节**：JSON 按 UTF-8 编码后直接写 `sys.stdout.buffer`。测试里 `sys.stdout`
    是 `StringIO`（没有 `.buffer`）→ 退回文本写。
    """
    data = json.dumps(payload, ensure_ascii=False) + "\n"
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(data)
        sys.stdout.flush()
        return
    buffer.write(data.encode("utf-8"))
    buffer.flush()


def _read_line() -> str | None:
    """读一行协议消息（**按字节读、自己解 UTF-8**）；`None` = EOF。

    不用 `for line in sys.stdin`：TextIOWrapper 一遇坏字节整个流进坏状态，连**它前面**那条
    正常请求的回话都拿不到。按字节逐行读 → 坏行只坏那一行。坏字节**故意抛给调用方**
    （不该 `errors="replace"`：把乱码当合法内容比回一条错误坏得多）。
    """
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is None:  # 被换成文本流（测试里 redirect 过）
        text = sys.stdin.readline()
        return None if text == "" else str(text)
    raw: bytes = buffer.readline()
    if not raw:
        return None
    return raw.decode("utf-8")


# ================================================================ 工具元数据（照先例：写死在表里）


TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "pool_plan",
        "description": "外包队列与冲突域：哪些卡能同批跑（只读，走 wb_plan.py plan）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "concurrency": {
                    "type": "integer",
                    "description": "并发上限（默认 2；要改就显式给）",
                    "default": 2,
                }
            },
            "required": [],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "job_list",
        "description": "扫 gates/diag/wb-*.jsonl：在跑 / 已判决 / 断了（看 mtime/大小/有无判决）。",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "job_status",
        "description": "一张卡现在到哪了：时间线 + 仓库状态（只读，走 wb_status.py --repo）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "card": {"type": "string", "description": "卡号，例如 105"},
            },
            "required": ["card"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "job_result",
        "description": "一张卡的判决与摘要**原文**（缺产物就说'没有'，截断会明示总长）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "card": {"type": "string", "description": "卡号，例如 105"},
            },
            "required": ["card"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "lock_status",
        "description": "门禁锁：哪把、谁的、租约剩多久（只列不拿，走 gate_lock.py status）。",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "pool_models",
        "description": "号池可用模型：批准集 ∩ 可用集（读号池快照，只读、不联网）。",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
]


def tool_list() -> list[dict[str, Any]]:
    """工具清单：六个只读工具；服务端有 `POOL_MCP_WRITE=1` 时再补两个写工具（"存在性即授权"）。"""
    specs = list(TOOL_SPECS)
    if write_enabled():
        specs += WRITE_TOOL_SPECS
    return specs


# ================================================================ 写工具元数据（卡 111 §3 / §5）

#: 写工具的授权 env —— **有它才把写工具列进 `tools/list`**（"存在性即授权"）。
WRITE_ENV = "POOL_MCP_WRITE"

WRITE_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "pool_dispatch",
        "description": ("派活：干跑守卫 → 先占树 → 起工人（--detach，立刻返回）。"
                        "只在服务端 POOL_MCP_WRITE=1 时可见；arguments.confirm 必须等于卡号。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "card": {"type": "string", "description": "卡号，例如 111"},
                "tree": {"type": "string", "description": "工人干活树（相对主树根；'' = 主树）"},
                "spec": {"type": "string",
                         "description": "卡规格文件（仓库相对）；不给就按 backlog 登记的路径"},
                "model": {"type": "string",
                          "description": "模型；不给用默认；必须在 wb_dispatch 白名单里"},
                "pool": {"type": "string", "description": "号池名（记进租约）"},
                "note": {"type": "string", "description": "备注（记进租约）"},
                "confirm": {"type": "string", "description": "★ 防手滑：必须等于 card"},
            },
            "required": ["card", "tree"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
    },
    {
        "name": "pool_cancel",
        "description": ("取消本机登记里那张卡的工人（先核对 pid 身份再动手）。"
                        "只在服务端 POOL_MCP_WRITE=1 时可见；arguments.confirm 必须等于卡号。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "card": {"type": "string", "description": "卡号"},
                "reason": {"type": "string", "description": "为什么取消（写进 cancel.txt）"},
                "confirm": {"type": "string", "description": "★ 防手滑：必须等于 card"},
            },
            "required": ["card"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True},
    },
]

#: 两个写工具的名字 —— 授权门 / `confirm` 校验用。
WRITE_NAMES = frozenset(spec["name"] for spec in WRITE_TOOL_SPECS)


def write_enabled() -> bool:
    """服务端授权：env `POOL_MCP_WRITE=1` 才把写工具列出来（"存在性即授权"）。"""
    return os.environ.get(WRITE_ENV, "").strip() == "1"


# ================================================================ 小工具：命令 / 子进程 / 产物


def _cmd_text(argv: list[str]) -> str:
    """人能照抄的**原样命令**（只在含空格时加双引号 —— 在 bash 与 cmd 里都好粘）。"""
    return " ".join(f'"{a}"' if " " in str(a) else str(a) for a in argv)


def _run(argv: list[str], cwd: Path) -> tuple[int | None, str, str]:
    """跑一条**只读**命令：返回 `(退出码 | None, stdout, stderr)`；起不来不抛、如实回报。

    ★ 卡 106 后**只剩一处调用方**（`lock_status` 跑 `gate_lock.py`，见模块头）—— 别的工具
    已改成 import `tools/pool/` 的函数，不再 shell 出去。
    """
    try:
        done = subprocess.run(  # noqa: S603 —— 命令是本地拼死的，不是外部输入
            argv, cwd=str(cwd), capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
    except OSError as exc:
        return None, "", f"跑不起来：{type(exc).__name__}: {exc}"
    return done.returncode, done.stdout or "", done.stderr or ""


#: 机器可读块的**唯一标记**（独占一行）—— 卡 117。
#: `job_result` 会把**报告正文原样带出**，正文里引用 tools/list 报文样例时也带 ```json；
#: 读端只认这个标记**之后**那一段，才不会把正文里的样例当成工具自己的机器块（主树实测坑）。
JSON_MARKER = "--- tf-json ---"


def _fence(data: dict[str, Any]) -> str:
    """把机器可读块放在**唯一标记**之后（标记后紧跟单行紧凑 JSON）。

    ★ 卡 117（T-G215）：老写法只靠 ```json 围栏 —— 而 `job_result` 原样带出的**报告正文**
      里正好引用了一份 tools/list 报文样例（也是 ```json）⇒ 读端取"第一个围栏"抓到的是
      **样例**（主树里必红、卡树里没报告所以必绿）。现在标记在前（正文里不会有的唯一行）、
      JSON 用**单行紧凑**（不含裸换行），唯一性不再依赖"围栏是不是第一个"。
    ★ 仍**保留** ```json 围栏：白名单外的既有读端 `tests/test_pool_mcp_write.py::_json_block`
      按第一个 ```json 取块（它读的 dispatch/cancel 正文里没有围栏，首块即真块），删围栏会
      波及那张卡；标记才是新的唯一判据，围栏只为兼容那个读端（本卡白名单不含它）。
    """
    compact = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"{JSON_MARKER}\n```json\n{compact}\n```"


def _result(text: str, data: dict[str, Any], *, is_error: bool) -> tuple[str, dict[str, Any], bool]:
    return f"{text.rstrip()}\n\n{_fence(data)}", data, is_error


# ================================================================ 工具 1：pool_plan


_PLAN_BATCH_RE = re.compile(r"^第 (\d+) 批（(\d+) 张，可同时跑）$")
_PLAN_CARD_RE = re.compile(r"^  · 卡 (.+?)（(.+?)）｜树 (.+?)｜(.*)$")
_PLAN_FILES_RE = re.compile(r"^      (?:域)：(.*)$")


def _parse_plan(text: str) -> list[dict[str, Any]] | None:
    """把 `wb_plan.py plan` 的人话输出解析成结构化批次。

    ★ 三态，别混：有批次 → 那个列表；**只有 `[计划]` 头、没有批次行** → `[]`（真的是 0 批）；
    连 `[计划]` 头都没有 → `None`（没解析出来，不假装）。
    """
    batches: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    card: dict[str, Any] | None = None
    for line in text.splitlines():
        if (m := _PLAN_BATCH_RE.match(line)) is not None:
            current = {"index": int(m.group(1)), "size": int(m.group(2)), "cards": []}
            batches.append(current)
            card = None
            continue
        if current is not None and (m := _PLAN_CARD_RE.match(line)) is not None:
            card = {
                "id": m.group(1), "task": m.group(2), "tree": m.group(3), "title": m.group(4),
                "files": [],
            }
            current["cards"].append(card)
            continue
        if card is not None and (m := _PLAN_FILES_RE.match(line)) is not None:
            raw = m.group(1).strip()
            card["files"] = [] if raw in ("", "（空）") else raw.split("、")
    if batches:
        return batches
    return [] if "[计划]" in text else None


def tool_pool_plan(arguments: dict[str, Any], root: Path = ROOT
                   ) -> tuple[str, dict[str, Any], bool]:
    """队列与冲突域 —— **import** `tools/pool/plan.py`（只读、不建树、不派活，不 shell 出去）。

    ★ `command` 字段仍给**人能照抄的 CLI 命令**（那是同一份逻辑的 CLI 说法）。
    """
    try:
        concurrency = int(arguments.get("concurrency", 2))
    except (TypeError, ValueError):
        concurrency = 2
    if concurrency < 1:
        concurrency = 2
    argv = [sys.executable, "-X", "utf8", "tools/wb_plan.py",
            "plan", "--concurrency", str(concurrency)]
    command = _cmd_text(argv)
    try:
        backlog = load_backlog(root / "docs" / "workbacklog.toml")
        code, out, err = plan_report(backlog, concurrency)
    except BacklogError as exc:
        code, out, err = 2, "", f"[FAIL] {exc}\n"
    body = (out + ("\n" + err if err.strip() else "")).strip()
    if code != 0:
        text = (f"pool_plan：我没有拿到计划。我是跑 `{command}` 得到这个的"
                f"（退出码 {code}）：\n{body}")
        return _result(text, {"command": command, "exit_code": code, "batches": None},
                       is_error=True)
    text = f"外包队列与冲突域（pool_plan）—— 来自 `{command}`：\n{body}"
    data = {"command": command, "exit_code": code, "concurrency": concurrency,
            "batches": _parse_plan(out)}
    return _result(text, data, is_error=False)


# ================================================================ 工具 2：job_list


def tool_job_list(arguments: dict[str, Any], root: Path = ROOT) -> tuple[str, dict[str, Any], bool]:
    """扫 `gates/diag/wb-*.jsonl` —— 在跑 / 已判决 / 断了（**判断依据都念出来**）。"""
    diag = diag_dir(root)
    rows = scan_jobs(diag)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    head = (f"外包派活台账（job_list）—— 扫 {diag.as_posix()}\n"
            f"共 {len(rows)} 个日志"
            + ("：" + " · ".join(f"{k} {v}" for k, v in sorted(counts.items()))
               if counts else "（一个都没有）"))
    if not rows:
        head += "\n（一个 wb-*.jsonl 都没有 —— 我没有假装有）"
    lines = [head]
    for row in rows:
        verdict = f"判决 {row['verdict']}" if row["has_verdict"] else "无判决"
        lines.append(
            f"  · 卡 {row['card'] or '?'}  [{row['state']}]  {row['log']}"
            f"  {row['size_bytes']}B  mtime={row['mtime']}（距今 {row['age_seconds']:.0f}s）"
            f"  {verdict}  —— {row['why']}"
        )
    data = {"diag_dir": diag.as_posix(), "count": len(rows), "counts": counts, "jobs": rows}
    return _result("\n".join(lines), data, is_error=False)


# ================================================================ 工具 3：job_status(card)


def tool_job_status(arguments: dict[str, Any], root: Path = ROOT
                    ) -> tuple[str, dict[str, Any], bool]:
    """一张卡现在到哪了 —— **import** `tools/pool/jobs.py` 读 log 并渲染（不再起进程）。

    ★ `command` 字段仍给 CLI 说法；输出形状与 `wb_status.py <log> --repo` **逐字一致**。
    """
    card = str(arguments.get("card") or "").strip()
    if not card:
        text = ("job_status：得给我一个卡号（card）。我是照 `card` 参数找 "
                "`gates/diag/wb-<卡>*.jsonl` 的。")
        return _result(text, {"card": None, "found": False}, is_error=True)
    diag = diag_dir(root)
    logs = card_artifacts(diag, card, ".jsonl")
    if not logs:
        text = (f"没有：卡 {card} 在 {diag.as_posix()} 里没有 `wb-{card}.jsonl`"
                f"（连 r2… 也没有）—— 还没派过，或日志不在这个树里。")
        return _result(text, {"card": card, "found": False, "log": None,
                              "diag_dir": diag.as_posix()}, is_error=True)
    log = logs[-1]
    argv = [sys.executable, "-X", "utf8", "tools/wb_status.py", log.name, "--repo"]
    command = _cmd_text(argv)
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    timeline, summary = parse_events(lines)
    body = render_timeline(log.name, timeline, summary, tail=0, repo=True, git_cwd=diag).strip()
    text = f"卡 {card} 的状态（job_status）—— 来自 `{command}`（cwd={diag.as_posix()}）：\n{body}"
    data = {"card": card, "found": True, "log": log.name, "command": command, "exit_code": 0}
    return _result(text, data, is_error=False)


# ================================================================ 工具 4：job_result(card)


def _read_capped(path: Path, cap: int) -> dict[str, Any]:
    """读一份原文；**截断要明示总长**（先例一貫的做法）。"""
    raw = path.read_text(encoding="utf-8", errors="replace")
    shown = raw if len(raw) <= cap else raw[:cap]
    return {
        "path": path.name,
        "exists": True,
        "total_chars": len(raw),
        "shown_chars": len(shown),
        "truncated": len(shown) < len(raw),
        "text": shown,
    }


def tool_job_result(arguments: dict[str, Any], root: Path = ROOT
                    ) -> tuple[str, dict[str, Any], bool]:
    """读 `wb-<卡>.report.md` 与 `wb-<卡>.verdict.txt` 的**原文**（缺就说"没有"）。"""
    card = str(arguments.get("card") or "").strip()
    if not card:
        text = ("job_result：得给我一个卡号（card）。我照它找 "
                "`gates/diag/wb-<卡>.report.md` 与 `wb-<卡>.verdict.txt`。")
        return _result(text, {"card": None, "found": False}, is_error=True)
    diag = diag_dir(root)
    verdicts = card_artifacts(diag, card, ".verdict.txt")
    reports = card_artifacts(diag, card, ".report.md")
    if not verdicts and not reports:
        text = (f"没有：卡 {card} 在 {diag.as_posix()} 里既没有 `wb-{card}.report.md`，"
                f"也没有 `wb-{card}.verdict.txt`（含 r2…）—— 没跑完 / 没派过 / 不在这个树里。")
        return _result(text, {"card": card, "found": False, "diag_dir": diag.as_posix(),
                              "verdict": {"exists": False}, "report": {"exists": False}},
                       is_error=True)
    blocks = [f"卡 {card} 的结果（job_result）—— 读 {diag.as_posix()} 下的原文："]
    vdata: dict[str, Any] = {"exists": False}
    rdata: dict[str, Any] = {"exists": False}
    if verdicts:
        vdata = _read_capped(verdicts[-1], REPORT_MAX_CHARS)
        tail = "（已截断）" if vdata["truncated"] else ""
        blocks.append(f"[判决] {vdata['path']}（共 {vdata['total_chars']} 字{tail}）："
                      f"\n{vdata['text']}")
    else:
        blocks.append("[判决] （没有）")
    if reports:
        rdata = _read_capped(reports[-1], REPORT_MAX_CHARS)
        tail = "（已截断）" if rdata["truncated"] else ""
        blocks.append(f"[摘要] {rdata['path']}（共 {rdata['total_chars']} 字{tail}）："
                      f"\n{rdata['text']}")
    else:
        blocks.append("[摘要] （没有）")
    data = {"card": card, "found": True, "verdict": vdata, "report": rdata}
    return _result("\n".join(blocks), data, is_error=False)


# ================================================================ 工具 5：lock_status


def tool_lock_status(arguments: dict[str, Any], root: Path = ROOT
                     ) -> tuple[str, dict[str, Any], bool]:
    """门禁锁现状 —— 跑 `gates/diag/gate_lock.py status`（只列不拿，不抢锁）。

    ★ 卡 106：命令与"空着"判据走 `pool.locks`；**这一处 subprocess 是本模块唯一保留的** ——
    `gate_lock.py` 是 `gates/diag/` 下的独立 `-P` 脚本（铁律 24：同名脚本会被当模块顶掉），
    且既有测试把"经 `_run` 调它"钉住了。
    """
    argv = lock_status_argv()
    code, out, err = _run(argv, root)
    command = _cmd_text(argv)
    body = (out + ("\n" + err if err.strip() else "")).strip()
    empty = lock_is_empty(body)
    if code != 0:
        text = f"lock_status：我是跑 `{command}` 得到这个的（退出码 {code}）：\n{body}"
        return _result(text, {"command": command, "exit_code": code}, is_error=True)
    lead = "现在没有锁（空着）。" if empty else "现在有锁在。"
    text = f"门禁锁现状（lock_status）—— {lead} 来自 `{command}`：\n{body}"
    data = {"command": command, "exit_code": code, "has_lock": not empty}
    return _result(text, data, is_error=False)


# ================================================================ 工具 6：pool_models


def tool_pool_models(arguments: dict[str, Any], root: Path = ROOT
                     ) -> tuple[str, dict[str, Any], bool]:
    """号池可用模型：批准集 ∩ 可用集 —— 读快照，**只读、不联网、不写快照**。"""
    pool = find_pool_dir(root)
    if pool is None:
        searched = " 、 ".join(
            (base / "infra" / "pool").as_posix() for base in (root, *root.parents))
        text = (f"没有：从 {root.as_posix()} 向上没找到号池目录"
                f"（找的是各级 `<祖先>/infra/pool/pool_models.py`）。找过：{searched}")
        return _result(text, {"found": False, "pool_dir": None}, is_error=True)
    info = load_pool_models(pool)
    if not info["whitelist_exists"] and not info["snapshot_exists"]:
        text = (f"没有：号池目录 {pool.as_posix()} 里既没有 {info['whitelist']}，"
                f"也没有 {info['snapshot']}。")
        return _result(text, {"found": False, **info}, is_error=True)
    lines = [
        f"号池可用模型（pool_models）—— 读 {pool.as_posix()}（★ 快照，非现场拉取；"
        f"{info['snapshot']} at={info['snapshot_at']}）",
        "批准集（models.whitelist.toml，只有用户能改）："
        + ("、".join(info["approved"]) if info["approved"] else "（没有批准项）"),
    ]
    lines.append("交集（真正允许派活的）：" + ("、".join(info["in_both"]) or "（空 —— 拒绝派活）"))
    if info["approved_but_missing"]:
        lines.append("批准了但快照里没有（派它必失败）：" + "、".join(info["approved_but_missing"]))
    if info["live_but_unapproved"]:
        lines.append("服务端有但未批准（只报告，绝不自动启用 → 等你一句「批 X」）："
                     + "、".join(info["live_but_unapproved"]))
    return _result("\n".join(lines), info, is_error=False)


# ================================================================ 写面：pool_dispatch / pool_cancel


def _backlog_for(root: Path) -> Any:
    """读 **root 下**的 backlog（不像 `pool.plan.load_backlog()` 那样固定到导入时的仓库根）。

    ★ 为什么按 root：MCP 服务端的 root 就是主仓；测试把 root 指到临时目录时读的也是那一份，
      不与别的门共享真 backlog。解析仍是同一个 `load_backlog`（不另写一份 parser）。
    """
    return load_backlog(root / "docs" / "workbacklog.toml")


def _how_to_pass() -> str:
    """干跑被咬时附给人看的"怎么才能通过"（逐条对得上守卫的措辞）。"""
    return ("怎么才能通过：\n"
            "  · 树被占 → 等那张卡的租约释放，或换一棵树（tree）；\n"
            "  · 冲突域相交 → 换一张域不相交的卡，或等对方收工；\n"
            "  · 日志已存在 → 由 wb_dispatch 自己挑 wb-<卡>.r2.jsonl，或先归档旧日志；\n"
            "  · 门禁还在跑 → 等这趟门禁结束（用 lock_status 看进度）。")


def _dispatch_argv(card: str, spec: str, cwd: Path, model: str) -> list[str]:
    """给 `wb_dispatch.py` 的 argv —— **写死**，不透传危险项。

    不透传：`--force` / `--allow` / `--resume` / `--no-preflight`。
    """
    return [
        sys.executable, "-X", "utf8", "tools/wb_dispatch.py",
        "--card", card, "--spec", spec, "--cwd", str(cwd), "--model", model,
        "--lean", "--detach", "--execute",
    ]


def _spawn_worker(argv: list[str], root: Path) -> tuple[int | None, str, str]:
    """起工人（带 `--detach`：父进程前置检查完就把自己扔出去，立刻返回）—— 本模块第二处 subprocess。

    返回 `(退出码 | None, stdout, stderr)`；跑不起来**不抛**（调用方据 `OSError` 回滚租约）。
    """
    done = subprocess.run(  # noqa: S603 —— 命令是本地拼死的，不是外部输入
        argv, cwd=str(root), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return done.returncode, done.stdout or "", done.stderr or ""


#: 从 `wb_dispatch --detach` 的那行「…（pid 4242）…」里取 pid（★ 收紧到括号，避免误抓别的数字）。
_PID_RE = re.compile(r"（pid\s+(\d+)）")


def _record_pid(card: str, pid: int) -> None:
    """把刚起的工人 pid 补进**已经占好的那条租约** —— `pool_cancel` 靠它认身份。

    ★ 卡 108 明确 `registry.reserve` **不登记 pid**（判活只按租约 + 日志）—— 这里不碰那条规矩：
      只在既有租约上补一个"我派的是哪个进程"，用的还是 `registry.load` / `registry.save`。
    """
    rows = registry.load()
    for row in rows:
        if str(row.get("card")) == str(card):
            row["pid"] = int(pid)
    registry.save(rows)


def _console_encoding() -> str:
    """`tasklist` / `taskkill` 输出要按**系统区域编码**解（这台 cp936）。

    ★ 照抄 `tools/wb_dispatch.py::kill_tree`（T-G96 的老坑，新代码重犯）：这两个命令吐的是
    **系统区域编码**，原来按 `utf-8` 解 → 掐进程的回话成乱码（"证据读不出来，等于没留证据"）。
    ★ 为什么**不用** `locale.getpreferredencoding(False)`：本仓一律 `python -X utf8`，
    那会让它回 `utf-8`（UTF-8 模式）→ 等于没修；`locale.getencoding()` 仍回系统区域编码（cp936）。
    ★ 解不开的字节仍走 `errors="replace"`，绝不让解码把掐进程这条路带崩。
    """
    return (locale.getencoding() if hasattr(locale, "getencoding")
            else locale.getpreferredencoding(False)) or "utf-8"


def _image_name(pid: int) -> str | None:
    """`tasklist` 拿这个 pid 的**映像名**；拿不到 → `None`（判不出，**不当作"没在跑"**）。"""
    try:
        done = subprocess.run(  # noqa: S603 —— pid 来自本机登记，不是外部输入
            ["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, encoding=_console_encoding(), errors="replace",
        )
    except OSError:
        return None
    line = next((ln for ln in (done.stdout or "").splitlines() if ln.strip()), "")
    if done.returncode != 0 or not line.startswith('"'):
        return None
    return line[1:line.index('"', 1)]


def _kill(pid: int) -> tuple[bool, str]:
    """`taskkill /F /T /PID <n>` 杀**整棵**（★ 绝不 `os.kill` 探活/杀，见模块头）。"""
    try:
        done = subprocess.run(  # noqa: S603 —— pid 来自本机登记，不是外部输入
            ["taskkill", "/F", "/T", "/PID", str(int(pid))],
            capture_output=True, text=True, encoding=_console_encoding(), errors="replace",
        )
    except OSError as exc:
        return False, f"taskkill 起不来：{type(exc).__name__}: {exc}"
    return done.returncode == 0, ((done.stdout or "") + (done.stderr or "")).strip()


def tool_pool_dispatch(arguments: dict[str, Any], root: Path = ROOT
                       ) -> tuple[str, dict[str, Any], bool]:
    """派活：干跑守卫 → `registry.reserve` 先占位 → 起工人（`--detach`）→ 起不来就回滚。"""
    card = str(arguments.get("card") or "").strip()
    tree = str(arguments.get("tree") or "").strip()
    if not card:
        return _result("pool_dispatch：得给我一个卡号（card）。", {"card": None}, is_error=True)

    # ① 定位：主树 / 域 / 规格 —— 域**查不到就拒**（别猜空域），规格按 backlog 登记的路径
    try:
        main_root = registry.main_tree_root()
    except registry.RegistryError as exc:
        return _result(f"pool_dispatch：算不出主工作树：{exc}", {"card": card}, is_error=True)
    try:
        hit = _backlog_for(root).by_id().get(card)
    except BacklogError as exc:
        return _result(f"pool_dispatch：读不了 backlog：{exc}", {"card": card}, is_error=True)
    if hit is None or not hit.files:
        return _result(
            f"pool_dispatch：backlog 里没有卡 {card} 的冲突域 ⇒ 不许派活（别猜空域）。",
            {"card": card, "found": False}, is_error=True)
    files = list(hit.files)
    spec = str(arguments.get("spec") or "").strip() or hit.spec
    model = str(arguments.get("model") or "").strip() or wb_dispatch.DEFAULT_MODEL
    if model not in wb_dispatch.MODEL_WHITELIST:      # ⑥ 模型白名单（硬闸门）
        return _result(wb_dispatch.model_rejected(model),
                       {"card": card, "model": model,
                        "allowed": list(wb_dispatch.MODEL_WHITELIST)}, is_error=True)

    # ② 干跑：三条自家守卫 + 登记里的租约判据（import 调用，不 shell 出去）
    stamp = time.time()
    log_path = diag_dir(root) / f"wb-{card}.jsonl"
    try:
        live = registry.list_reservations(stamp)
        lock_body = registry.read_lock_body()
    except registry.RegistryError as exc:
        return _result(f"pool_dispatch：读登记失败：{exc}", {"card": card}, is_error=True)
    problems = [
        *guards.tree_guard(tree, live, stamp),                          # ① 一棵树一个写者
        *guards.domain_guard(files, live, stamp),                       # ② 冲突域不相交
        *guards.lock_guard(card, tree, lock_body, root=main_root),      # ③ 门禁还在跑
        *guards.log_guard(log_path),                                    # ⑤ 日志不许覆盖
    ]
    if problems:
        text = ("pool_dispatch：干跑没过，**不派活**（逐条原因）：\n"
                + "".join(f"  · {item}\n" for item in problems) + "\n" + _how_to_pass())
        return _result(text, {"card": card, "dispatched": False, "problems": problems},
                       is_error=True)

    # ③ 先占位（并发安全的关键：不能"先派活后登记"）
    try:
        lease = registry.reserve(card, task=hit.task, tree=tree, files=files,
                                 pool=str(arguments.get("pool") or ""), model=model,
                                 log=log_path.as_posix(), note=str(arguments.get("note") or ""),
                                 lock_body=lock_body)
    except registry.GuardError as exc:
        text = ("pool_dispatch：占位时被守卫拦下，**不派活**：\n"
                + "".join(f"  · {item}\n" for item in exc.problems) + "\n" + _how_to_pass())
        return _result(text, {"card": card, "dispatched": False, "problems": exc.problems},
                       is_error=True)
    except registry.RegistryError as exc:
        return _result(f"pool_dispatch：登记失败（未派活）：{exc}", {"card": card},
                       is_error=True)

    # ④ 起工人（--detach：立刻返回）；起不来就回滚刚占的租约
    cwd = Path(tree) if Path(tree).is_absolute() else (main_root / tree if tree else main_root)
    argv = _dispatch_argv(card, spec, cwd, model)
    try:
        code, out, err = _spawn_worker(argv, root)
    except OSError as exc:
        registry.release(card)
        return _result(f"pool_dispatch：工人起不来，已回滚租约：{type(exc).__name__}: {exc}",
                       {"card": card, "dispatched": False, "rolled_back": True}, is_error=True)
    preflight = (out + ("\n" + err if err.strip() else "")).strip()
    pid_hit = _PID_RE.search(preflight)
    if code != 0 or pid_hit is None:
        registry.release(card)
        return _result(
            f"pool_dispatch：wb_dispatch 没把工人扔出去（退出码 {code}），"
            f"已回滚租约：\n{preflight}",
            {"card": card, "dispatched": False, "rolled_back": True, "exit_code": code,
             "preflight": preflight}, is_error=True)
    pid = int(pid_hit.group(1))
    _record_pid(card, pid)

    dispatch_log = log_path.with_name(f"wb-{card}.dispatch.log")
    data = {"card": card, "tree": tree or "（主树）", "cwd": cwd.as_posix(), "spec": spec,
            "model": model, "log": log_path.as_posix(),
            "dispatch_log": dispatch_log.as_posix(), "pid": pid, "preflight": preflight,
            "lease": {**lease, "pid": pid}}
    text = (f"pool_dispatch：卡 {card} 已派（pid {pid}）—— 来自 `{_cmd_text(argv)}`\n"
            f"  log：{log_path.as_posix()}\n"
            f"  dispatch.log：{dispatch_log.as_posix()}\n"
            f"  租约：树 {tree or '（主树）'}｜域 {'、'.join(files)}\n"
            f"  前置检查原文：\n{preflight}\n"
            f"  ★ 用 job_status(card='{card}') 看进度。")
    return _result(text, data, is_error=False)


def tool_pool_cancel(arguments: dict[str, Any], root: Path = ROOT
                     ) -> tuple[str, dict[str, Any], bool]:
    """取消本机登记里那张卡的工人 —— **先核对 pid 身份**，不对就拒绝动手。"""
    card = str(arguments.get("card") or "").strip()
    reason = str(arguments.get("reason") or "").strip()
    if not card:
        return _result("pool_cancel：得给我一个卡号（card）。", {"card": None}, is_error=True)
    try:
        live = registry.list_reservations()
    except registry.RegistryError as exc:
        return _result(f"pool_cancel：读登记失败：{exc}", {"card": card}, is_error=True)
    hit = next((row for row in live if str(row.get("card")) == card), None)
    if hit is None:
        return _result(f"pool_cancel：本机登记里没有卡 {card} 的**活租约** —— 不动手。",
                       {"card": card, "found": False}, is_error=True)
    pid = hit.get("pid")
    manual = (f"人工怎么做（先看清是不是本卡的活）：\n"
              f"  tasklist /FI \"PID eq {pid or '<pid>'}\" /FO CSV\n"
              f"  taskkill /F /T /PID {pid or '<pid>'}")
    if not isinstance(pid, int):
        return _result(
            f"pool_cancel：这条租约里没记 pid（不是本 MCP 派的活）→ **拒绝动手**。\n{manual}",
            {"card": card, "found": True, "pid": None}, is_error=True)
    image = _image_name(pid)
    if image is None or image.lower() not in ("node.exe", "python.exe"):
        return _result(
            f"pool_cancel：**拒绝动手** —— PID {pid} 的映像是 {image or '（查不到，判不出）'}，"
            f"不是 node.exe / python.exe（pid 会被复用，杀错树 = 杀掉别人的东西）。\n{manual}",
            {"card": card, "found": True, "pid": pid, "image": image}, is_error=True)
    ok, detail = _kill(pid)
    if not ok:
        return _result(f"pool_cancel：taskkill 没成功（pid {pid}），租约**没动**：{detail}",
                       {"card": card, "pid": pid, "image": image, "killed": False},
                       is_error=True)
    note_path = diag_dir(root) / f"wb-{card}.cancel.txt"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        f"card={card} 取消于={datetime.datetime.now().isoformat(timespec='seconds')}\n"
        f"谁：{registry.default_owner()}\n"
        f"pid={pid}（映像 {image}）\n"
        f"为什么：{reason or '（没写理由）'}\n"
        f"结果：taskkill /F /T /PID {pid}\n{detail}\n",
        encoding="utf-8")
    released = registry.release(card)
    data = {"card": card, "pid": pid, "image": image, "killed": True, "released": released,
            "cancel_txt": note_path.as_posix(), "reason": reason}
    text = (f"pool_cancel：卡 {card} 的工人已结束（pid {pid}，映像 {image}）\n"
            f"  已写 {note_path.as_posix()}（谁 / 什么时候 / 为什么）\n"
            f"  租约{'已释放' if released else '本来就没有'}。")
    return _result(text, data, is_error=False)


# ================================================================ tools/call 调度


_HANDLERS: dict[str, Any] = {
    "pool_plan": tool_pool_plan,
    "job_list": tool_job_list,
    "job_status": tool_job_status,
    "job_result": tool_job_result,
    "lock_status": tool_lock_status,
    "pool_models": tool_pool_models,
    "pool_dispatch": tool_pool_dispatch,
    "pool_cancel": tool_pool_cancel,
}


def call_tool(name: str, arguments: dict[str, Any], *, root: Path = ROOT
              ) -> dict[str, Any] | None:
    """跑一个工具；`None` = **不认识这个名字**（调用方翻成 `-32602`，不崩）。

    ★ 写工具多两道门：① 服务端要有 `POOL_MCP_WRITE=1`（没有就当"没有这个工具"）；
    ② `arguments.confirm` 必须**等于卡号**（防手滑 —— 真要害的一张卡，就把卡号再写一遍）。
    """
    handler = _HANDLERS.get(name)
    if handler is None:
        return None
    args = arguments or {}
    if name in WRITE_NAMES:
        if not write_enabled():
            return None
        card = str(args.get("card") or "").strip()
        if not card or str(args.get("confirm") or "").strip() != card:
            return {"content": [{"type": "text", "text":
                    f"pool_mcp：写调用被拒 —— arguments.confirm 必须等于卡号"
                    f"（card={card or '?'}）。这是防手滑：真要害的一张卡，就把卡号再写一遍。"}],
                    "isError": True}
    text, _data, is_error = handler(args, root)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


# ================================================================ 协议处理


def _initialize(params: dict[str, Any]) -> dict[str, Any]:
    wanted = str(params.get("protocolVersion") or "")
    return {
        "protocolVersion": wanted if wanted in KNOWN_PROTOCOLS else PROTOCOL_VERSION,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        "instructions": (
            "外包号池：默认是**只读**面 —— pool_plan / job_list / job_status / job_result / "
            "lock_status / pool_models，六个都只读（不写文件、不派活、不抢锁、不要 env）。"
            "**写工具**（pool_dispatch 派活 / pool_cancel 取消）只有在**服务端**设了 "
            "POOL_MCP_WRITE=1 时才列出来 —— 那是「存在性即授权」：没这个 env 就没有写工具。"
            "而且每次写调用还要 arguments.confirm **等于卡号**（防手滑）。"
            "pool_dispatch 的顺序固定：先干跑守卫（被咬就不派活、逐条给原因）→ 先占树 → 起工人"
            "（--detach，立刻返回）→ 起不来就回滚租约；危险参数一律不透传。"
            "pool_cancel 只取消本机登记里那张卡的工人，**先核对 pid 身份**（映像必须是 node.exe / "
            "python.exe），不对就拒绝动手。命令失败会带回**原样命令**；产物缺失会明说'没有'。"
        ),
    }


def handle(message: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any] | None:
    """处理一条消息 → 回一条（或 None = 通知，不回）。"""
    method = str(message.get("method") or "")
    has_id = "id" in message
    mid = message.get("id")

    if not has_id:  # 通知（initialized / cancelled / …）：不回，也不报错
        return None

    def ok(result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def bad(code: int, text: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": text}}

    if method == "initialize":
        params = message.get("params")
        return ok(_initialize(params if isinstance(params, dict) else {}))
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": tool_list()})
    if method == "tools/call":
        params = message.get("params")
        params = params if isinstance(params, dict) else {}
        name = str(params.get("name") or "")
        arguments = params.get("arguments")
        result = call_tool(name, arguments if isinstance(arguments, dict) else {}, root=root)
        if result is None:
            listed = "、".join(spec["name"] for spec in tool_list())
            extra = ("" if write_enabled() else
                     "（本服务现在只有只读工具 —— 写工具要服务端设 POOL_MCP_WRITE=1 才列出来。）")
            return bad(JSONRPC_INVALID_PARAMS, f"没有这个工具：{name!r}；有：{listed}。{extra}")
        return ok(result)
    return bad(JSONRPC_METHOD_NOT_FOUND, f"不支持的方法：{method}")


def _usage() -> str:
    return (
        "pool_mcp —— 把外包号池的现状与派活作为 MCP 工具提供给 AI 客户端"
        "（stdio，一行一个 JSON-RPC 消息）\n"
        "\n"
        "  python -X utf8 tools/pool_mcp.py          起 stdio 服务\n"
        "  python -X utf8 tools/pool_mcp.py --help\n"
        "\n"
        "只读工具：pool_plan / job_list / job_status(card) / job_result(card) / "
        "lock_status / pool_models。\n"
        "写工具（要服务端 env POOL_MCP_WRITE=1 才列出来；每次调用还要 confirm=卡号）："
        "pool_dispatch / pool_cancel。\n"
        "客户端配置（示例）：command = python，args = [\"-X\", \"utf8\", "
        "\"tools/pool_mcp.py\"]。stdout 只走协议。\n"
    )


def serve(tail: list[str]) -> int:
    """stdio 主循环：读一行、处理、回一行；EOF 就退 0。

    两道防线（照抄先例，缺一条就真出事）：① `_pin_stdio_utf8()` 钉编码；
    ② 一条坏消息（不是 UTF-8 / 不是 JSON / 处理时异常）只换**一条错误回话**，循环继续 ——
    客户端拿到一条 JSON-RPC 错误还能接着用，拿到 EOF 只会以为"服务坏了"。
    """
    for token in tail:
        if token in ("-h", "--help"):
            print(_usage())
            return 0
        print(f"pool_mcp 不认识的参数 {token!r}（只认 --help）", file=sys.stderr)
        return 2

    _pin_stdio_utf8()

    while True:
        try:
            line = _read_line()
        except UnicodeDecodeError as exc:
            _emit({"jsonrpc": "2.0", "id": None,
                   "error": {"code": JSONRPC_PARSE_ERROR, "message": f"这一行不是 UTF-8：{exc}"}})
            continue
        if line is None:  # EOF：客户端走了
            break
        text = line.strip()
        if not text:
            continue
        try:
            message = json.loads(text)
        except ValueError as exc:
            _emit({"jsonrpc": "2.0", "id": None,
                   "error": {"code": JSONRPC_PARSE_ERROR, "message": f"不是合法 JSON：{exc}"}})
            continue
        if not isinstance(message, dict):
            _emit({"jsonrpc": "2.0", "id": None,
                   "error": {"code": JSONRPC_PARSE_ERROR, "message": "消息必须是对象"}})
            continue
        try:
            answer = handle(message, root=ROOT)
        except Exception as exc:  # noqa: BLE001 —— 协议边界：任何异常只换一条错误回话
            print(f"[pool_mcp] 处理这条消息时出错：{type(exc).__name__}: {exc}", file=sys.stderr)
            answer = {"jsonrpc": "2.0", "id": message.get("id"),
                      "error": {"code": JSONRPC_INTERNAL_ERROR,
                                "message": (f"服务端处理这条消息时出错："
                                            f"{type(exc).__name__}: {exc}")}}
        if answer is None:
            continue
        _emit(answer)
    return 0


def main(argv: list[str] | None = None) -> int:
    """命令入口：`--help` 给人看；其余一个参数都没有（MCP 客户端的 args 就该是空）。"""
    tail = list(sys.argv[1:] if argv is None else argv)
    if not tail:
        return serve(tail)
    if any(token in ("-h", "--help") for token in tail):
        print(_usage())
        return 0
    print(f"pool_mcp 不认识的参数 {tail!r}（MCP 客户端不该传参；只有 --help）", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
