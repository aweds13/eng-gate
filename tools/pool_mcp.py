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
| `tools/list` | 六个只读工具的清单（**写死在 `TOOL_SPECS` 里**，见下） |
| `tools/call` | 跑一个工具 → 人话文本 + ```json 围栏里的机器可读块 |
| `ping` | `{}` |

不认的方法回 `-32601`，不认的工具名回 `-32602`。**未知工具名明确报错、绝不崩**（先例同款）。

## ★ 零依赖 & 编码（照抄先例的 `_pin_stdio_utf8` / `_emit` / `_read_line`）

本仓不引第三方 MCP SDK，只用标准库。stdio 说明：Windows 上 Python 的 `sys.stdin/stdout`
默认跟**控制台代码页**（这台 cp936）——不钉的话中文出去是 GBK、进来会把服务端**打崩**。
所以协议这一层把三件套钉成 UTF-8，并按**字节**逐行读（一行坏字节只坏那一行，不打死循环）。

## ★★ 六个工具，一个都不许写文件（本卡硬要求）

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

**没有一个是写类工具**（派活 / 取消 / 提交 / 抢锁）—— 那是**期 2**。

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

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

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
    """工具清单（六个只读工具；本卡不列任何写工具）。"""
    return list(TOOL_SPECS)


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


def _fence(data: dict[str, Any]) -> str:
    """把机器可读块拼成 ```json 围栏（卡允许"围栏 或 structuredContent"，这里选围栏）。"""
    return "```json\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n```"


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


# ================================================================ tools/call 调度


_HANDLERS: dict[str, Any] = {
    "pool_plan": tool_pool_plan,
    "job_list": tool_job_list,
    "job_status": tool_job_status,
    "job_result": tool_job_result,
    "lock_status": tool_lock_status,
    "pool_models": tool_pool_models,
}


def call_tool(name: str, arguments: dict[str, Any], *, root: Path = ROOT
              ) -> dict[str, Any] | None:
    """跑一个工具；`None` = **不认识这个名字**（调用方翻成 `-32602`，不崩）。"""
    handler = _HANDLERS.get(name)
    if handler is None:
        return None
    text, _data, is_error = handler(arguments or {}, root)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


# ================================================================ 协议处理


def _initialize(params: dict[str, Any]) -> dict[str, Any]:
    wanted = str(params.get("protocolVersion") or "")
    return {
        "protocolVersion": wanted if wanted in KNOWN_PROTOCOLS else PROTOCOL_VERSION,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        "instructions": (
            "外包号池的**只读**面：pool_plan / job_list / job_status / job_result / "
            "lock_status / pool_models。六个工具都只读 —— 不写文件、不派活、不抢锁。"
            "派活 / 取消 / 提交 / 抢锁是期 2，不在这里。命令失败会带回**原样命令**；"
            "产物缺失会明说'没有'，不假装有。"
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
            listed = "、".join(spec["name"] for spec in TOOL_SPECS)
            return bad(JSONRPC_INVALID_PARAMS,
                       f"没有这个工具：{name!r}；有：{listed}。"
                       f"（本服务只有只读工具 —— 六个都不写文件、不派活、不抢锁。）")
        return ok(result)
    return bad(JSONRPC_METHOD_NOT_FOUND, f"不支持的方法：{method}")


def _usage() -> str:
    return (
        "pool_mcp —— 把外包号池的现状作为 MCP 只读工具提供给 AI 客户端"
        "（stdio，一行一个 JSON-RPC 消息）\n"
        "\n"
        "  python -X utf8 tools/pool_mcp.py          起 stdio 服务\n"
        "  python -X utf8 tools/pool_mcp.py --help\n"
        "\n"
        "工具：pool_plan / job_list / job_status(card) / job_result(card) / "
        "lock_status / pool_models —— 全部只读。\n"
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
