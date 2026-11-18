r"""外包号池的 **MCP 只读面**（stdio · JSON-RPC 2.0）—— 换哪个窗口的 AI 都能问"现在号池在跑什么"。

## 为什么有它（用户原话）

「外包调用能不能做成 MCP，更适合不同窗口 AI 调用」→「我会在 DSH 里不同窗口用」。
派活那一套散在 6 个脚本里、**靠约定**（主树要干净 / 切片里写工作树 / 别并行两池），换个窗口
的 AI 得从头学；而且**谁也不知道别的窗口在跑什么**。这一卡把那套现状**只读地**摊成
十三个工具（十个号池 + 三个任务）。

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

## ★★ 十三个只读工具（一个都不许写文件）

下面六行是**号池面**；任务面那三个在「任务面」一节（同一批只读工具，一处都不许写文件）。

| 工具 | 干什么 | 底层 |
|---|---|---|
| `pool_plan` | 队列与冲突域 | **import** `tools/pool/plan.py`（不再 shell 出去） |
| `job_list` | 扫 `wb-*.jsonl` → 五类态；台账读不到⇒判不了 | **import** `tools/pool/jobs.py` |
| `job_status(card)` | 时间线 + 仓库状态 | **import** `tools/pool/jobs.py`（读 log + 进程内渲染） |
| `job_result(card)` | 判决与摘要的**原文**（截断**明示总长**） | **import** `tools/pool/jobs.py` |
| `lock_status` | 门禁锁：哪把、谁的、租约剩多久 | `gate_lock.py status`（唯一 subprocess，见下） |
| `pool_models` | 批准集 ∩ 快照 + 按池允许集 + **按池判决** | **import** `tools/pool/models.py` |

★ 卡 106（T-G202）：十三个工具的**逻辑**已收敛到 `tools/pool/` 包，CLI 与 MCP **共用同一批函数**。
`subprocess` 只留**一处** —— `lock_status` 跑 `gate_lock.py`：那是 `gates/diag/` 下的**独立脚本**
（`-P` 是铁律 24：那里的同名脚本会被当模块顶掉），且既有测试把"经 `_run` 调它"钉住了。

## ★★ 写面（卡 111 · T-G208）：`pool_dispatch` / `pool_cancel` —— 要 `POOL_MCP_WRITE=1` 才列

两个写工具**默认隐身**（没有那个 env 就只列十三个只读工具）：起工人 / 杀进程不该被"顺手"调到。
每次写调用还必须 `arguments.confirm`（防手滑），但**不是同一个东西**：号池两个写工具 = **卡号**；
任务面三个各有各的 —— `task_register` = TOML 里的 `id`、`task_claim` = `task`、
`usage_report` = **这一批的记录条数**（这一批的规模才是最该先看一眼的）。
十三个只读工具**不需要任何 env**。

**`pool_dispatch(card, tree, spec?, model?, pool?, note?)`** —— 顺序**固定**：
① 干跑（`pool.guards` 三条 + `pool.registry` 的租约判据，**import 调用**）→ 有咬就**不派活**、
把逐条原因原样回给调用方（`isError=true`）；② `pool.registry.reserve(...)` **先占位**（并发安全
的关键：不能"先派活后登记"）；③ 起工人 `wb_dispatch.py … --cwd <树绝对路径> --lean --detach
--execute`（**必须 `--detach`**：MCP 工具调用不能阻塞几十分钟）；④ 起不来就
`pool.registry.release(...)` **回滚**并如实报错。参数**写死、不透传危险项**：不给 `--force` /
`--allow` / `--no-preflight` / `--resume`；`--model` / `--pool` 走**与 CLI 同一份判据**：
允许集 = `wb_dispatch.effective_allowed_models(pool)`（注册表该池条目 + 一次性授权
+ 开关文件里打开的），判定函数 = `wb_dispatch.model_rejected(model, pool)`；
不在就拒（拒单文案原样带回），不给模型用该池默认。

**`pool_cancel(card, reason?)`** —— 只取消**本机登记里那一条租约**的 pid：
★ 先核对身份（`tasklist /FI "PID eq <n>" /FO CSV` 的映像名必须是 `node.exe` / `python.exe`），
不对就**拒绝动手**并把"人工该敲什么"的确切命令印出来；★★ **绝不用 `os.kill(pid, 0)` 探活**
（Windows 上 CPython 的 `os.kill` 走 `TerminateProcess` —— 那不是探活、那是**把人杀了**，
见 `复盘/口径坑.md` 第 27 条）。成功后写 `gates/diag/wb-<卡>.cancel.txt`（谁 / 什么时候 /
为什么）并 `pool.registry.release(card)`。

## ★★ HTTP 传输（卡 A365 · T-AG584）：远程窗口也能接

`--http` 起 **Streamable HTTP**（`tools/pool/mcp_http.py`，零依赖）：请求体里的 JSON-RPC 交给
**同一个 `handle()`**，判据一条不重写。`--host` 只收回环、必须设 `TF_MCP_HTTP_TOKEN`
（Bearer）；Origin 白名单与请求体上限都在那一层；`GET`/`DELETE` 回 405（本服务不提供 SSE、无会话）。
stdio 那条路**一个字节不变**（无参数仍是 stdio）。

### 六条不变量 + 一条执行口径：哪条谁判（★ 不在本模块重写任何判据）

| # | 不变量 | 谁判 |
|---|---|---|
| ① | 一棵树同时一个写者 | `pool.guards.tree_guard` |
| ② | 冲突域不许相交（域从 backlog 读，**查不到就拒**，别猜空域） | `pool.guards.domain_guard` |
| ③ | 门禁还在跑就不动手 | `pool.guards.lock_guard` |
| ④ | 内存闸 | **委托** `wb_dispatch.py` 的前置检查（本模块**不写**内存判据） |
| ⑤ | 日志不许覆盖 | `pool.guards.log_guard` + **不给** `--force`（wb_dispatch 自己挑 r2） |
| ⑥ | 模型白名单 | `wb_dispatch.effective_allowed_models(pool)`（硬闸门）+ `pool.models` |
| ⑦ | `task_claim` 不许冻住 stdio（卡 130） | 本模块：子进程 + 后台线程 |

★ ⑥ 的后半 `pool.models` 是号池快照的「批准 ∩ 可用」；两侧都过才放行（本模块不重写任何一侧）。

★ ⑦ 是**执行口径**（不是外部守卫）：`tool_task_claim` 把 `wb_task.py claim` 跑在**子进程**里，
`serve` 再把它交给一个**后台 FIFO 线程** —— 主循环继续读，只读工具照样即刻答；判据仍只有一份
（`pool.task`，见下节）。

★ 干跑与登记都经 `pool.registry.list_reservations` + `pool.guards`（同一批纯函数）—— 派活的
"能不能占"与 CLI `wb_registry.py check` 是**同一处判据**，不另写一份（本仓最忌两份真源）。

## ★★ 任务面（卡 121 · T-G218）：只读三个 + 写两个

任务栅栏（注册一个跨层的任务 → 每张卡交成送申请 → 集齐才收口）的本体是 `tools/pool/task.py`
（模块 `pool.task`，卡 119 搬进 git）。本段把**它**接到外包面，**判据只有一份**（都跑
`wb_task.py` → `pool.task`，卡 106 的规矩：CLI 与 MCP 共用同一批函数）；★ 卡 130 起
**执行方式分两路**：快的（register）进程内，会跑门禁的（claim）走子进程。

| 工具 | 干什么 |
|---|---|
| `task_list` | 所有任务一行（任务号 / 状态 / 成送申请进度 / 一句话 why） |
| `task_status(task)` | 一个任务的详情（每张卡的**层**与**域**、交没交、history 尾部） |
| `task_pool` | 待办登记表（还没定卡的活，按层） |

三个只读工具全部 **import `pool.task`**（`batch_dir` / `read_json` / `_ok` / `_missing` /
`_load_pool`），**不需要任何 env、永远列出**，且**一个字节都不许写**（卡 105 的机器判据要能过）。

**写两个**（★ 只在服务端 `POOL_MCP_WRITE=1` 时**列出来** —— "存在性即授权"，卡 111 的规矩）：

- **`task_register(manifest_text? | manifest_path?, confirm)`** —— 给**整段预声明 TOML** 或路径，
  `confirm` = TOML 里的 `id`；走 `cmd_register`（`Namespace` + 捕获 stdout、**进程内**，快路径）。
  文本先落到批目录里一个临时源文件、注册完即删，**不留半截**。
- **`task_claim(task, member, claim, evidence, files, why, confirm)`** —— `confirm` = `task`；
  ★ **走子进程** `[python -X utf8 tools/wb_task.py claim …]`（它会跑门禁 5~9 分钟 ⇒ 不许进程内跑、
  不许冻住 stdio；卡 130）。★★ **逐卡域守卫照走**：碰了域外文件 ⇒ 子进程非零退出，
  回话**原样带出**它的输出与退出码、`isError=true`，**绝不静默**（域守卫在 MCP 这条路上也不能绕）。

## ★★ 工作台面（卡 213 · T-G325）：`workbench_board` —— 会话内看全六块

一个**只读**工具，把卡 207 的 `tools/pipeline_view.py` 的一份读数（卡 / 门禁 / 判决 / 租约 /
栅栏 / 卡树**六块**）收成一份端到会话内 —— 用户原话「尽量**不要让我切来切去**」的第 1 个面。

- ★ **判据只有一份**：本工具**只调** `pipeline_view.py --json`（子进程），**不重写**读队列 /
  读门禁的逻辑 —— 这正是卡 207 存在的意义。
- ★ 参数 `section`：不给 = 一次看全六块；给了 = 只要那一块。
- ★ **缺什么说什么**：某块是 `null` + 说明时**原样透传** —— 不许洗成空对象、不许省略。
- ★ 子进程带 `NO_WINDOW` 且**限时**（`WORKBENCH_TIMEOUT`）：非零 / 超时 / 起不来都**如实报错**
  （`isError=true`、`reading=null`），**绝不**返回一个"看起来正常"的空板子。

## ★★ 外部用量上报入口（卡 A364 · T-AG578）：`usage_report` —— 只开入口，不动判据

判据层是卡 A347 的 `tools/pool/usage_ingest.py`（`ingest()` / `parse_batch()`），它的 docstring
逐字写着「**不经过派活器的调用，今天完全不进账。**」—— 本卡补的就是那**一个**入口。

- ★ **判据只有一份**：本工具**只调** `usage_ingest.ingest()` / `usage_ingest.parse_batch()`，
  **不重写**任何一条校验（字段表、条数上限、去重口径全在判据层）。
- ★ `confirm` 是**这一批的记录条数**（不是卡号 —— 这一批的规模就是最该先看一眼的东西）；
  条数由判据层自己数出来，所以"能报几条"与"该确认几"永远是同一个数。
- ★ 顺序固定：**先**解析（全量校验，一条坏就整包拒）→ **再**核 `confirm`（此时一个字节都还没
  写）→ **才** `ingest()`。全有或全无，拒单时目标文件行数与 mtime 都不动。
- ★ 上报行落 `gates/diag/usage-reported.jsonl`，**绝不**混进派活器自己的 `wb-usage.jsonl`
  （那本账认"这一行是谁写的"，混了就永久不可判）。
- ★ 拒单 ⇒ `isError: true` 且回话里**逐条带 faults 原文**；成功 ⇒ 判据层的
  `{"accepted", "skipped", "records"}` **原样**透出（不翻译字段名）。

## 诚实边界（如实写）

- `pool_models` 读的是**快照** `models.live.json`（带 `at` 时间戳），**不是现场拉取**：
  现场拉取（`pool_models.py --check`）既要**联网**又会**写快照文件**，两样都被本卡禁止。
  所以这里只读它已经落盘的输入，并在输出里**明说**"来自快照 at=…"。
- ★ 卡 E107：pool_models 里「交集」那段**不是**派活允许集 —— 它是号池两份静态产物的交集
  （models.whitelist.toml ∩ models.live.json），与派活器判的那份**不是同一件事**，
  连 id 口径都不同（号池 provider/model、派活器裸名）。真名单**按池**现算，
  判据只有一份：wb_dispatch.effective_allowed_models(pool)；注册表坏了只让**这一段**
  说"读不出来"，工具整体照常返回（只读面不许被一个坏 TOML 打成异常）。
- ★ 快照新鲜度（过期 / 没过期 / **没记录**）必须出现在**人话段**：只藏在机器块
  （--- tf-json --- 之后）里等于没说 —— MCP 客户端读的就是人话段。
- ★ 卡 E109（T-AG618）：**按原名过不了闸 ≠ 这条模型今天用不了**。号池批准集写的是号池 id
  （`provider/model`），派活器写裸名；同一个模型在两套体系里名字不同，逐字比必被拒。
  所以判决段同时给「可派别名」—— 那是今天**真能派**的写法（现算，不写死）。
- ★ 注册表指针**现算**（`pool.model_registry.registry_path()`）：它在**本仓** `tools/pool/`
  下，不在仓外号池目录里 —— 老文案指错了地方，照着找是白找。
- 号池目录（`infra/pool/`）**不在本仓**（它在 `jelly_ware/` 下、跨项目复用）。本模块从
  `ROOT` 起**逐级向上**找 `<祖先>/infra/pool/pool_models.py`；找不到就如实说"没有"并列出找过哪些。
- 传给人看/给客户端的东西只有工具；**没有** `resources` / `prompts` / `logging`（先例也一样）。
- 这一卡只做到"另一个实现能读懂报文"这一层；**真在 DSH 里接一次**要人工点（注册写法见卡 §9）。

## 用法

    python -X utf8 tools/pool_mcp.py          # stdio 起服务（一行一个 JSON-RPC）
    python -X utf8 tools/pool_mcp.py --help
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import io
import json
import locale
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

import tomllib
import wb_dispatch  # noqa: PLC0415 —— 模型白名单 / 默认模型的**唯一**真源（卡 111 §2 ⑥）
import wb_plan  # noqa: PLC0415 —— 台账分片（卡 E89）：分片目录 / 分片读法只此一份
from pool import accounts_scope, guards, registry, task, usage_ingest
from pool.jobs import (
    HEARTBEAT_SECONDS,
    REPORT_MAX_CHARS,
    STALL_SECONDS,
    card_artifacts,
    diag_dir,
    in_flight,
    parse_events,
    read_log_lines,
    render_timeline,
    scan_jobs,
)
from pool.locks import is_empty as lock_is_empty
from pool.locks import status_argv as lock_status_argv
from pool.models import find_pool_dir, load_pool_models, probe_command, probe_hint
from pool.no_window import NO_WINDOW  # ★ 卡 148：子进程一律不弹窗（flag 的唯一真源）
from pool.plan import BacklogError, plan_report

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


#: 一行协议消息的**字节上限**（卡 A362 · F7）：照 magpie `internal/gateway/mcp.go:83` 的
#: `readMCPBody(w, r, 32<<20)`（`vision_mcp.go:34` 的 `visionMCPBody` 也是同一个值）。
#: **只定义一次**：报错文案引这个常量，不另写字面量（抄错常量那一位就没有钉子咬了）。
MAX_LINE_BYTES: int = 32 << 20


class LineTooLongError(Exception):
    """一行**长过上限**：带**实际读到的字节数**（文案由 `serve()` 组织，这里不印）。"""

    def __init__(self, size: int) -> None:
        super().__init__(size)
        self.size = size


#: 卡规格里的名字（`except LineTooLong`）。ruff `N818` 要求异常名带 `Error` 后缀 ⇒ 类名带后缀，
#: 再用这个别名把卡规格的名字挂回去。**同一个类**，不是第二个类型（钉子 1 用别名捕获，删了就红）。
LineTooLong = LineTooLongError


def _read_line(limit: int = MAX_LINE_BYTES) -> str | None:
    """读一行协议消息（**按字节读、自己解 UTF-8**）；`None` = EOF。

    不用 `for line in sys.stdin`：TextIOWrapper 一遇坏字节整个流进坏状态，连**它前面**那条
    正常请求的回话都拿不到。按字节逐行读 → 坏行只坏那一行。坏字节**故意抛给调用方**
    （不该 `errors="replace"`：把乱码当合法内容比回一条错误坏得多）。

    ★ 卡 A362（F7）：**一行有字节上限**（`limit`，默认 `MAX_LINE_BYTES`，照 magpie 的 32 MiB）。
    判据不是「读满了就算长」：读满 `limit` 就停，与「这一行被切了一半」在 `readline()` 下
    长得**一模一样** —— magpie #1766 修的就是它。所以读 `limit + 1`：多读的那 1 字节
    **就是在问「到此为止，还是被切了」**。超限**不截断**（截断后再解 JSON 正是 #1766 的 bug），
    而是抛给调用方，由它回一条错误、把这一行剩余字节吃完、再接着服务。
    """
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is None:  # 被换成文本流（测试里 redirect 过）
        text = sys.stdin.readline()
        return None if text == "" else str(text)
    # ★ 卡 A362（F7）：多读这 1 字节 —— 它就是「到此为止」与「被切了」之间唯一的信息。
    raw: bytes = buffer.readline(limit + 1)
    if not raw:
        return None
    body = _content_bytes(raw)
    if len(body) > limit:
        raise LineTooLong(len(body))
    return raw.decode("utf-8")


def _content_bytes(raw: bytes) -> bytes:
    """这一行**去掉行尾换行**的内容：先去掉 `\n`，它前面若有 `\r` 也去掉。

    上限只数**内容**字节：行尾换行是传输分隔符，不是消息的一部分 —— 否则「正好 `limit` 字节」
    的合法消息带一个换行就会被判成超限（两侧各错一位，`>` 与 `>=` 就分不出来了）。
    """
    body = raw[:-1] if raw.endswith(b"\n") else raw
    return body[:-1] if body.endswith(b"\r") else body


#: 吞残余的块大小（一行可以很长：按块读到行尾，不把残余整行读进内存）。
_DRAIN_CHUNK = 1 << 16


def _drain_line() -> int:
    """把**当前这一行剩下的字节**吃到行尾，返回吃掉的**内容**字节数（卡 A362）。

    为什么非吃不可：`_read_line` 判超限时只消费了 `limit + 1` 字节，剩下的还在流里。
    不吃掉，残余就会被当成**下一行** —— 客户端看到的是一条莫名其妙的「不是合法 JSON」，
    明明它只发了一条消息。

    按**字节**读、**不解码**：残余里有没有坏字节，都不改变这条已经判死的行的结论
    （解码了就可能在吞残余时抛 `UnicodeDecodeError`，把「太长」这条回话也搅坏）。
    文本流那一支是**镜像**（测试里 redirect 过才走得到），按字符数。
    """
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is None:
        text = sys.stdin.readline()
        return len(text[:-1]) if text.endswith("\n") else len(text)
    total = 0
    while True:
        chunk = buffer.readline(_DRAIN_CHUNK)
        if not chunk:
            return total
        if chunk.endswith(b"\n"):
            chunk = chunk[:-1]
            return total + len(chunk[:-1] if chunk.endswith(b"\r") else chunk)
        total += len(chunk)


# ================================================================ 工具元数据（照先例：写死在表里）

#: ★ 卡 213：工作台读数的**唯一**来源 —— 调卡 207 的 `tools/pipeline_view.py`（**不重写判据**）。
#: 测试可把 `PIPELINE_VIEW` 换成一个"故意非零"的桩脚本，验 `workbench_board` 会如实报错。
PIPELINE_VIEW = ROOT / "tools" / "pipeline_view.py"

#: `workbench_board` 的六块（顺序即 `pipeline_view` 的块序）。
WORKBENCH_SECTIONS = ("cards", "gates", "verdicts", "leases", "fences", "worktrees")

#: workbench_board 的两档 payload 口径（卡 E125）：默认 summary（瘦），full 才给全明细。
#: ★ 只许这一个开关 —— 不许再加 verbose 之类第二个口径（同一个意思只许一种说法）。
WORKBENCH_VIEWS = ("summary", "full")

#: 子进程**限时**上限（秒）：pipeline_view 要跑 `git worktree list` + 逐树 `git status`，
#: 给足但不许无限等（超时 ⇒ 如实报错，绝不静默返空）。
WORKBENCH_TIMEOUT = 60.0


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
        "description": "扫 gates/diag/wb-*.jsonl：在跑 / 已判决 / 断了 + 历史尝试 / 已被取代 / "
        "台账已完结 / 非派活（看 mtime/大小/有无判决/台账）；每行末尾给在飞。"
        "台账读不到 ⇒ 判不了（这一源不可判，不是「已经结束」）。",
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
        "description": "一张卡现在到哪了：在飞（活租约 / 判决 / 日志是否静默）+ 时间线"
        "（进程内渲染，不起子进程）+ 仓库状态；没有 wb-<卡>.jsonl 时按落地链五类正式证据找。",
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
        "description": (
            "号池可用模型：批准集 ∩ 快照（★ 不是派活允许集）+ 按池的派活允许集；"
            "并逐条给出按池的真判决今天派不派得出去（含可派别名与注册表真路径）。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "quota_status",
        "description": (
            "额度四态（卡 201）：按「记录时间 vs 现实时间」判 —— 限流中 / 已过期，"
            "需重新探测 / 余额耗尽 / 未记录。只读，当场算，不探测。"
            "★ 后三态会给一条 `tools/pool_accounts.py probe` 命令（命令是**输出**，"
            "不是本工具的入参）；`can_dispatch` 只有限流中才是 false，其余是 null（不知道）。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "card": {"type": "string", "description": "卡号，例如 201"},
                "model": {"type": "string", "description": "模型名"},
                "now": {
                    "type": "string",
                    "description": "注入「现在」（ISO-8601；测试用，不许靠真实钟表）",
                },
            },
            "required": ["card", "model"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "account_status",
        "description": (
            "账号账本读数（卡 E45）：有哪些号、哪个平台、额度观测值、凭据位点"
            "（打码）。只读仓外账本，**不探测、不联网、不动凭据**。"
            "账本本体在 D:/repo/infra/pool/accounts.toml。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "description": "只看某个平台（如 codearts）"},
                "id": {"type": "string", "description": "只看某个账号 id"},
            },
            "required": [],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "checkin_status",
        "description": (
            "今日签到读数（卡 E48 / E119）：读当天留档 gates/diag/checkin-<日期>.json，"
            "并只读仓外账本的 health.last_checkin / last_probe —— 结论码可能是旧的，"
            "读数按 last_probe 的日期标明它是哪天的。**永不触发签到、永不联网** —— "
            "真要签得人跑 tools/pool_accounts.py checkin --all。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                    "description": (
                        "看哪一天（YYYY-MM-DD；默认今天，本地时区）。形状或日历不对的串"
                        "一律拒收（isError=true，正文点名 YYYY-MM-DD），不会被拼进留档路径。"
                    ),
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "workbench_board",
        "description": (
            "工作台一份读数（卡 213）：卡 / 门禁 / 判决 / 租约 / 栅栏 / 卡树六块"
            "收成一份（只读，走 pipeline_view.py --json，不重写判据）。"
            "默认瘦（fields=summary）：cards 每行 files/depends 只给计数（files_n/depends_n）、"
            "已完卡（status=done）折叠成只含 id 与 status 的骨架行（行数与顺序都不动）；"
            "verdicts 每行 attempts 只给计数（attempts_n）；worktrees 的 path 相对读数根。"
            "fields=full 才给全明细（与 pipeline_view 逐键相同）。"
            "section 不给=一次看全六块；某块缺来源会如实给 null + 说明。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": "只要哪一块；不给=六块全给",
                    "enum": list(WORKBENCH_SECTIONS),
                },
                "fields": {
                    "type": "string",
                    "description": (
                        "summary（默认）＝瘦：files/depends 只给计数、已完卡折叠成骨架行；"
                        "full＝全明细（与 pipeline_view 逐键相同）"
                    ),
                    "enum": list(WORKBENCH_VIEWS),
                    "default": "summary",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
]

#: 任务面三个**只读**工具（卡 121 §1）—— **不要 env、永远列出**、一个字节都不写。
TASK_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "task_list",
        "description": (
            "任务栅栏现状：所有任务一行（任务号 / 状态 / 成送申请进度 / 一句话 why）；"
            "读不了的状态文件单独点名（不许洗成没有）。只读，不要 env。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "task_status",
        "description": (
            "一个任务的详情：每张卡的层与域、交没交、history 尾部。参数 task。只读，不要 env。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "任务号，例如 T-1"},
            },
            "required": ["task"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "task_pool",
        "description": "待办登记表（还没定卡的活，按层）。只读，不要 env。",
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
    """十三个只读工具（十个号池 + 三个任务）；有 `POOL_MCP_WRITE=1` 时再补五个写工具。"""
    specs = [*TOOL_SPECS, *TASK_TOOL_SPECS]
    if write_enabled():
        specs += [*WRITE_TOOL_SPECS, *TASK_WRITE_TOOL_SPECS]
    return specs


# ================================================================ 写工具元数据（卡 111 §3 / §5）

#: 写工具的授权 env —— **有它才把写工具列进 `tools/list`**（"存在性即授权"）。
WRITE_ENV = "POOL_MCP_WRITE"

WRITE_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "pool_dispatch",
        "description": (
            "派活：干跑守卫 → 先占树 → 起工人（--detach，立刻返回）。"
            "只在服务端 POOL_MCP_WRITE=1 时可见；arguments.confirm 必须等于卡号。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "card": {"type": "string", "description": "卡号，例如 111"},
                "tree": {"type": "string", "description": "工人干活树（相对主树根；'' = 主树）"},
                "spec": {
                    "type": "string",
                    "description": "卡规格文件（仓库相对）；不给就按 backlog 登记的路径",
                },
                "model": {
                    "type": "string",
                    "description": "模型；不给用默认；必须在 wb_dispatch 白名单里",
                },
                "pool": {"type": "string", "description": "号池名（记进租约）"},
                "account": {
                    "type": "string",
                    "description": (
                        "账号 id（accounts.toml 的 id，不是 email）；给了就按"
                        " limits.toml 的 [accounts.<id>].models 收窄模型白名单"
                    ),
                },
                "note": {"type": "string", "description": "备注（记进租约）"},
                "sticky": {
                    "type": "boolean",
                    "description": (
                        "卡粘性（卡 A345）：同一张卡第二次派活时还用它上次答过的那个号。"
                        "只在本轮没给 account 时生效；不给 / false 就不透传 --sticky"
                    ),
                },
                "confirm": {"type": "string", "description": "★ 防手滑：必须等于 card"},
            },
            "required": ["card", "tree"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
    },
    {
        "name": "pool_cancel",
        "description": (
            "取消本机登记里那张卡的工人（先核对 pid 身份再动手）。"
            "只在服务端 POOL_MCP_WRITE=1 时可见；arguments.confirm 必须等于卡号。"
        ),
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
    {
        "name": "usage_report",
        "description": (
            "★ 外部用量上报（不经派活器的那一笔也进账）。"
            "body 给一条 JSON 记录或一组（整段文本，也可直接给对象/数组）；"
            "只在服务端 POOL_MCP_WRITE=1 时可见；arguments.confirm 必须等于**这一批的记录条数**"
            "（防手滑 —— 一屏 300 条和一条，手滑的代价不一样）。"
            "校验一条都不在这里：全在 tools/pool/usage_ingest.py（本工具只开入口）；"
            "上报行落 gates/diag/usage-reported.jsonl，同一个记录号重复上报会被跳过（不写第二行），"
            "**不进**派活器自己的 wb-usage.jsonl。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "body": {
                    "type": "string",
                    "description": (
                        "一条 JSON 记录，或一组记录的 JSON 数组（也可以直接传对象/数组，"
                        "这里只做 JSON 化、不校验字段）"
                    ),
                },
                "confirm": {
                    "type": "string",
                    "description": "★ 防手滑：必须等于这一批的记录条数（十进制串，例如 \"3\"）",
                },
            },
            "required": ["body"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    },
]

#: 号池写工具的名字 —— 授权门用（`confirm` 判据见 `USAGE_WRITE_NAMES`）。
WRITE_NAMES = frozenset(spec["name"] for spec in WRITE_TOOL_SPECS)

#: ★ 卡 A364（T-AG578）：`confirm` **不**等于卡号、而是**等于这一批的记录条数**的写工具。
#:   它**在** `WRITE_NAMES` 里（否则授权门不知道它是写工具、没 env 就会漏列出来 ——
#:   那不是「漏登记」，是**刻意留在**里面）；这里另立一集，只为从 `call_tool` 那条
#:   「`confirm == card`」的**通用门**里排除掉：它的判据是 `confirm == 这一批的记录条数`，
#:   让通用门先咬一口，回话就不再是卡规格要的那一句（收到 N 条 / confirm 给的 M）。
#:   照 `TASK_WRITE_NAMES` 成例单独排除，`confirm` 判据在 handler 里判。
USAGE_WRITE_NAMES = frozenset({"usage_report"})

#: 任务面两个**写**工具（卡 121 §2）—— 同样只在 `POOL_MCP_WRITE=1` 时列出。
#: ★ `confirm` 的判据与号池写工具**不同**：register 要等于 TOML 里的 `id`、claim 要等于 `task`，
#:   所以**不走** `call_tool` 里那条"confirm=卡号"的通用检查，各自在 handler 里判（见下）。
TASK_WRITE_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "task_register",
        "description": (
            "★ 注册一个任务（预声明它需要哪些卡 / 每张卡属于哪层 / 各自域）。给 manifest_text"
            "（整段 TOML）或 manifest_path；只在服务端 POOL_MCP_WRITE=1 时可见；arguments.confirm"
            " 必须等于 TOML 里的 id。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "manifest_text": {"type": "string", "description": "整段预声明 TOML 文本"},
                "manifest_path": {
                    "type": "string",
                    "description": "预声明 TOML 的路径（相对仓库根或绝对）",
                },
                "confirm": {"type": "string", "description": "★ 防手滑：必须等于 TOML 里的 id"},
            },
            "required": ["confirm"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
    },
    {
        "name": "task_claim",
        "description": (
            "★ 一张卡交成送申请（success 必带证据；failed ⇒ 挡住收口）。只在服务端 "
            "POOL_MCP_WRITE=1 时可见；arguments.confirm 必须等于 task；碰了域外文件会被拒并点名。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "任务号，例如 T-1"},
                "member": {"type": "string", "description": "卡号，例如 卡115"},
                "claim": {
                    "type": "string",
                    "enum": ["success", "failed"],
                    "description": "success（成送申请）/ failed（不通过 ⇒ 挡住收口）",
                },
                "evidence": {
                    "type": "string",
                    "description": "★ success 必填：测试读数 / 门禁结论 / 原样输出",
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "碰过的文件（**要过这张卡自己的域检查**）",
                },
                "why": {"type": "string", "description": "这张卡干了什么（会进文书骨架）"},
                "confirm": {"type": "string", "description": "★ 防手滑：必须等于 task"},
            },
            "required": ["task", "member", "confirm"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    },
]

#: 任务面两个写工具的名字 —— 授权门用（`confirm` 判据各自在 handler 里）。
TASK_WRITE_NAMES = frozenset(spec["name"] for spec in TASK_WRITE_TOOL_SPECS)


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
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            **NO_WINDOW,
        )
    except OSError as exc:
        return None, "", f"跑不起来：{type(exc).__name__}: {exc}"
    return done.returncode, done.stdout or "", done.stderr or ""


def _run_bounded(argv: list[str], cwd: Path, timeout: float) -> tuple[int | None, str, str]:
    """跑一条**只读、限时**的命令：返回 `(退出码 | None, stdout, stderr)`。

    ★ 卡 213：`workbench_board` 要起 `pipeline_view.py` —— 与 `_run` 的区别只有一条：
      **有超时上限**（`subprocess.run(timeout=…)`）。起不来 / 超时都 **不抛**，
      退出码给 `None` + stderr 里写清原因（**绝不静默返空**）；子进程一律带 `NO_WINDOW`。
    """
    try:
        done = subprocess.run(  # noqa: S603 —— 命令是本地拼死的，不是外部输入
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            **NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return None, "", f"超时：超过 {timeout:g}s 还没跑完，已掐掉（`{_cmd_text(argv)}`）。"
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
                "id": m.group(1),
                "task": m.group(2),
                "tree": m.group(3),
                "title": m.group(4),
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


def tool_pool_plan(
    arguments: dict[str, Any], root: Path = ROOT
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
    argv = [
        sys.executable,
        "-X",
        "utf8",
        "tools/wb_plan.py",
        "plan",
        "--concurrency",
        str(concurrency),
    ]
    command = _cmd_text(argv)
    try:
        # 卡 E89：台账分片时读分片（总表只是合并产物）；无分片退回同一条老读法。
        backlog = wb_plan.load_sharded_backlog(
            root / "docs" / "workbacklog.toml", root / "docs" / "backlog")
        code, out, err = plan_report(backlog, concurrency, root=root)
    except BacklogError as exc:
        code, out, err = 2, "", f"[FAIL] {exc}\n"
    body = (out + ("\n" + err if err.strip() else "")).strip()
    if code != 0:
        text = (
            f"pool_plan：我没有拿到计划。我是跑 `{command}` 得到这个的（退出码 {code}）：\n{body}"
        )
        return _result(
            text, {"command": command, "exit_code": code, "batches": None}, is_error=True
        )
    text = f"外包队列与冲突域（pool_plan）—— 来自 `{command}`：\n{body}"
    data = {
        "command": command,
        "exit_code": code,
        "concurrency": concurrency,
        "batches": _parse_plan(out),
    }
    return _result(text, data, is_error=False)


# ================================================================ 卡 E116：台账与正式证据（只读）

#: 没有 `wb-<卡>[.rN].jsonl` 时，正式证据按这个顺序找（**顺序写死**，与卡 E116 判据 2 一致）。
EVIDENCE_KINDS: tuple[str, ...] = ("land", "trace_d", "changelog", "review", "trace_entry")


def _backlog_cards(root: Path) -> tuple[dict[str, Any], str | None]:
    """台账 `id -> Card` 与「读不到」的原文 —— `(cards, gap)`。**读不到就回空字典，绝不抛**。

    ★ `wb_plan.load_sharded_backlog` 在总表不存在时直接抛 `BacklogError`（实测原文
    `backlog 文件不存在：…`）—— 号池工具是只读面，台账不在只该让「证据链」少几类，
    不该让整个 `job_status` 变成一行 traceback。

    ★ 卡 E132：**不抛 ≠ 不说**。第二个返回值 `gap` 是那句原文（形如 `BacklogError: <原文>`），
    读得到时是 `None` —— 调用方据此把「这一源不可判」摆到正文与 data 上，而不是洗成「没有台账」。
    """
    try:
        backlog = wb_plan.load_sharded_backlog(
            root / "docs" / "workbacklog.toml", root / "docs" / "backlog"
        )
        return dict(backlog.by_id()), None
    except Exception as exc:  # noqa: BLE001 —— 台账坏了/不在/格式变了，都不许把工具打成 traceback
        gap = f"{type(exc).__name__}: {exc}"
        print(f"[job_list/job_status] 台账读不到（这一源不可判）：{gap}", file=sys.stderr)
        return {}, gap


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:  # pragma: no cover —— root 之外的路径不该出现
        return path.as_posix()


def _trace_entry_exists(root: Path, task: str) -> bool:
    """`docs/traceability.toml` 里有没有 `[entries."<task>"]` 这一节（只读，不解析业务字段）。"""
    path = root / "docs" / "traceability.toml"
    if not path.is_file():
        return False
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (tomllib.TOMLDecodeError, OSError):
        return False
    entries = data.get("entries")
    return isinstance(entries, dict) and task in entries


def formal_evidence(root: Path, card: str, task: str | None) -> list[dict[str, str]]:
    """按写死的顺序找「这张卡真的干过活」的正式证据，**first-hit** 就停（卡 E116 判据 2）。

    ① `gates/diag/land-<卡>[a-z]?.log` —— 只许**一位小写字母**：允许数字会串卡（实测
    `land-E1` 会命中 E10..E19，`land-E4` 会命中 E40..E49）。这一条**不依赖台账**。
    ② `docs/traceability.d/<task>.toml` ③ `docs/changelog.d/<task>.md` ④ `gates/review/<task>.json`
    ⑤ `docs/traceability.toml` 的 `entries[<task>]`。
    卡不在台账（`task is None`）⇒ 只查 ①。
    """
    diag = diag_dir(root)
    if diag.is_dir():
        pat = re.compile(rf"^land-{re.escape(card)}[a-z]?\.log$")
        for path in sorted(diag.iterdir()):
            if pat.match(path.name):
                return [{"kind": "land", "path": _rel(root, path)}]
    if not task:
        return []
    for kind, path in (
        ("trace_d", root / "docs" / "traceability.d" / f"{task}.toml"),
        ("changelog", root / "docs" / "changelog.d" / f"{task}.md"),
        ("review", root / "gates" / "review" / f"{task}.json"),
    ):
        if path.is_file():
            return [{"kind": kind, "path": _rel(root, path)}]
    if _trace_entry_exists(root, task):
        return [{"kind": "trace_entry", "path": "docs/traceability.toml"}]
    return []


# ================================================================ 工具 2：job_list


def tool_job_list(arguments: dict[str, Any], root: Path = ROOT) -> tuple[str, dict[str, Any], bool]:
    """扫 `gates/diag/wb-*.jsonl` —— **判断依据都念出来**。

    ★ 卡 E132：态名**只从 `scan_jobs` 的行里取**，这里一个都不许硬写 ——
    硬写一个名字，等于在工具里又判了一次状态（判据 4）。
    """
    diag = diag_dir(root)
    cards, backlog_gap = _backlog_cards(root)
    statuses = {cid: c.status for cid, c in cards.items()}
    rows = scan_jobs(diag, backlog=statuses, backlog_error=backlog_gap)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    head = f"外包派活台账（job_list）—— 扫 {diag.as_posix()}\n共 {len(rows)} 个日志" + (
        "：" + " · ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        if counts
        else "（一个都没有）"
    )
    if not rows:
        head += "\n（一个 wb-*.jsonl 都没有 —— 我没有假装有）"
    lines = [head]
    if backlog_gap:
        lines.append(
            f"台账读不到（{backlog_gap}）—— 台账那一路不可判：下面每一行的态名只按日志与判决算，"
            "台账那一维没有结论。"
        )
    for row in rows:
        verdict = f"判决 {row['verdict']}" if row["has_verdict"] else "无判决"
        if row["state"] == "非派活":
            fly, fly_why = False, "旁账日志不是派活，没有「在飞」这回事"
        else:
            fly, fly_why = in_flight(diag, row["card"])
        row["in_flight"] = fly
        row["in_flight_why"] = fly_why
        lines.append(
            f"  · 卡 {row['card'] or '?'}  [{row['state']}]  {row['log']}"
            f"  {row['size_bytes']}B  mtime={row['mtime']}（距今 {row['age_seconds']:.0f}s）"
            f"  {verdict}  —— {row['why']}｜在飞：{'是' if fly else '否'}"
        )
    data = {
        "diag_dir": diag.as_posix(),
        "count": len(rows),
        "counts": counts,
        "jobs": rows,
        "backlog_unavailable": backlog_gap,
    }
    return _result("\n".join(lines), data, is_error=False)


# ================================================================ 工具 3：job_status(card)


def tool_job_status(
    arguments: dict[str, Any], root: Path = ROOT
) -> tuple[str, dict[str, Any], bool]:
    """一张卡现在到哪了 —— **import** `tools/pool/jobs.py` 读 log 并在**进程内**渲染。

    ★ 这里**没有**子进程，也**没有**命令：data 里的 `rendered_by` 说的是真话
    （在进程内 import `pool.jobs.render_timeline` 渲染），
    不给 `command` / `exit_code` 那种没跑过的字段。
    """
    card = str(arguments.get("card") or "").strip()
    if not card:
        text = (
            "job_status：得给我一个卡号（card）。我是照 `card` 参数找 "
            "`gates/diag/wb-<卡>*.jsonl` 的。"
        )
        return _result(text, {"card": None, "found": False}, is_error=True)
    diag = diag_dir(root)
    logs = card_artifacts(diag, card, ".jsonl")
    if not logs:
        # ★ 卡 E116 判据 2：没有 wb-<卡>.jsonl **不等于**「还没派过」—— 真树里 200+ 张 done 的卡
        #   是走落地链落的（gates/diag/land-<卡>*.log / docs/traceability.d / gates/review/…）。
        #   五类证据按写死的顺序 first-hit；台账读不到只少几类，不许抛。
        cards, backlog_gap = _backlog_cards(root)
        meta = cards.get(card)
        task = getattr(meta, "task", None)
        evidence = formal_evidence(root, card, task)
        fly, fly_why = in_flight(diag, card)
        head = f"在飞：{'是' if fly else '否'} —— {fly_why}"
        if backlog_gap:
            head += (
                f"\n台账读不到（{backlog_gap}）—— 台账那一路不可判；"
                "下面「没有」只说日志与五类正式证据里都找不到，台账写没写过这张卡我不知道。"
            )
        base = {
            "card": card,
            "found": False,
            "log": None,
            "diag_dir": diag.as_posix(),
            "in_flight": fly,
            "in_flight_why": fly_why,
            "evidence": evidence,
            "task": task,
            "backlog_unavailable": backlog_gap,
        }
        if evidence:
            hit = evidence[0]
            text = (
                head + "\n"
                + f"没有：卡 {card} 在 {diag.as_posix()} 里没有 `wb-{card}.jsonl`（连 r2… 也没有）"
                + "—— 但它**走的是落地链**（没有外包工人日志，卡由落地链直接提交）。"
                + f"\n正式证据：`{hit['path']}`（{hit['kind']}）"
            )
            return _result(text, base, is_error=False)
        if meta is not None and getattr(meta, "status", "") == "done":
            text = (
                head + "\n"
                + f"没有：卡 {card} 在 {diag.as_posix()} 里没有 `wb-{card}.jsonl`，"
                + "台账写 `done`，但仓里查不到五类正式证据中的任何一类"
                + "（落地日志 / traceability.d / changelog.d / 复核 / 汇总表）"
                + "—— 这是台账与仓对不上，不是「没派过」。"
            )
            return _result(text, base, is_error=True)
        text = (
            head + "\n"
            + f"没有：卡 {card} 在 {diag.as_posix()} 里没有 `wb-{card}.jsonl`"
            + "（连 r2… 也没有）—— 还没派过，或日志不在这个树里。"
        )
        return _result(text, base, is_error=True)
    log = logs[-1]
    lines = read_log_lines(log)
    timeline, summary = parse_events(lines)
    body = render_timeline(log.name, timeline, summary, tail=0, repo=True, git_cwd=diag).strip()
    fly, fly_why = in_flight(diag, card)
    rendered_by = "在进程内 import pool.jobs.render_timeline 渲染，没有起子进程"
    text = (
        f"在飞：{'是' if fly else '否'} —— {fly_why}\n"
        f"卡 {card} 的状态（job_status）—— {rendered_by}"
        f"（log={log.name}，cwd={diag.as_posix()}）：\n{body}"
    )
    data = {
        "card": card,
        "found": True,
        "log": log.name,
        "rendered_by": rendered_by,
        "in_flight": fly,
        "in_flight_why": fly_why,
    }
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


def tool_job_result(
    arguments: dict[str, Any], root: Path = ROOT
) -> tuple[str, dict[str, Any], bool]:
    """读 `wb-<卡>.report.md` 与 `wb-<卡>.verdict.txt` 的**原文**（缺就说"没有"）。"""
    card = str(arguments.get("card") or "").strip()
    if not card:
        text = (
            "job_result：得给我一个卡号（card）。我照它找 "
            "`gates/diag/wb-<卡>.report.md` 与 `wb-<卡>.verdict.txt`。"
        )
        return _result(text, {"card": None, "found": False}, is_error=True)
    diag = diag_dir(root)
    verdicts = card_artifacts(diag, card, ".verdict.txt")
    reports = card_artifacts(diag, card, ".report.md")
    if not verdicts and not reports:
        text = (
            f"没有：卡 {card} 在 {diag.as_posix()} 里既没有 `wb-{card}.report.md`，"
            f"也没有 `wb-{card}.verdict.txt`（含 r2…）—— 没跑完 / 没派过 / 不在这个树里。"
        )
        return _result(
            text,
            {
                "card": card,
                "found": False,
                "diag_dir": diag.as_posix(),
                "verdict": {"exists": False},
                "report": {"exists": False},
            },
            is_error=True,
        )
    blocks = [f"卡 {card} 的结果（job_result）—— 读 {diag.as_posix()} 下的原文："]
    vdata: dict[str, Any] = {"exists": False}
    rdata: dict[str, Any] = {"exists": False}
    if verdicts:
        vdata = _read_capped(verdicts[-1], REPORT_MAX_CHARS)
        tail = "（已截断）" if vdata["truncated"] else ""
        blocks.append(
            f"[判决] {vdata['path']}（共 {vdata['total_chars']} 字{tail}）：\n{vdata['text']}"
        )
    else:
        blocks.append("[判决] （没有）")
    if reports:
        rdata = _read_capped(reports[-1], REPORT_MAX_CHARS)
        tail = "（已截断）" if rdata["truncated"] else ""
        blocks.append(
            f"[摘要] {rdata['path']}（共 {rdata['total_chars']} 字{tail}）：\n{rdata['text']}"
        )
    else:
        blocks.append("[摘要] （没有）")
    data = {"card": card, "found": True, "verdict": vdata, "report": rdata}
    return _result("\n".join(blocks), data, is_error=False)


# ================================================================ 工具 5：lock_status


def tool_lock_status(
    arguments: dict[str, Any], root: Path = ROOT
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


def _short_mismatch(why: str) -> str:
    """把跨池串用那句长理由压成一句人话（原文里那句 ``--pool {belongs_to}`` 是**没被填**的模板，

    照抄出来只会让人更糊涂；这里只取「属于哪个池」）。

    ★ 卡 E109（T-AG618）：压短是**读面**的事，判据一个字不动 —— 原文照旧由派活器打给命令行。
    """
    import re  # noqa: PLC0415 —— 只在这一句上用

    hit = re.search(r"属于「([^」]+)」池", why)
    if hit:
        return f"它属于 {hit.group(1)} 池（两套 id 不许串用）"
    return why.splitlines()[0]


def _dispatch_verdict(name: str, pool: str) -> tuple[str, str]:
    """这个名字在这个池今天派不派得出去 —— 判序与 tools/wb_dispatch.py 的 main() 一字不差。

    ★ 卡 E109（T-AG618）：判据只有一份，这里只负责**问**（get_adapter → resolve_model →
      assert_wired → model_rejected → assert_not_disabled）；不另抄名单、不另写判序。
    返回 (结论, 为什么)；「为什么」是给人看的那一句话（未接 ⇒ 适配器自己那句 note）。
    """
    from pool.model_registry import (  # noqa: PLC0415 —— 只在被调用时读，坏注册表不连累模块导入
        ModelRegistryError,
        PoolMismatchError,
        get_adapter,
        resolve_model,
    )

    adapter = get_adapter(pool)
    try:
        resolve_model(name, pool)   # 返回值不看：不在注册表 ⇒ None ⇒ 可能被开关/一次性授权放行
    except PoolMismatchError as exc:
        return "跨池串用", _short_mismatch(str(exc))
    # ★ 卡 E109：这里**不许**把「不在注册表」当结论 —— 派活主闸也不这么判：
    #   resolve_model 只用来拦跨池串用，返回值被丢掉；不在注册表的名字能不能派，
    #   由 model_rejected 看允许集（注册表 + 一次性授权 + 开关文件）说了算。
    if not adapter.wired:
        return "未接", adapter.note
    rejected = wb_dispatch.model_rejected(name, pool)
    if rejected:
        return "未授权", rejected.splitlines()[0]
    try:
        wb_dispatch.assert_not_disabled(pool, name)
    except ModelRegistryError as exc:
        return "判不了", str(exc).splitlines()[0]
    return "可派", ""


def _alias_routes(name: str, pools: list[str]) -> list[str]:
    """同一个模型今天**换个名字**能派出去的（形如 glm-5.2（codebuddy））。

    ★ 两套 id 体系（号池 provider/model、派活器裸名）对不上时，按原名过闸必被拒；
      但同一个模型换个写法今天就能派。判「是不是同一个模型」用别名集合**相交**
      （单向包含不可靠：id_names 只切前缀，注册表同组别名只在一边有）。
    """
    mine = {a.strip().lower() for a in wb_dispatch.model_aliases(name)}
    routes: list[str] = []
    for pool in pools:
        try:
            allowed = wb_dispatch.effective_allowed_models(pool)
        except Exception:  # noqa: BLE001 —— 只读面：一个池读不出来不连累别的池
            continue
        for cand in allowed:
            if cand == name:
                continue
            theirs = {a.strip().lower() for a in wb_dispatch.model_aliases(cand)}
            if not (mine & theirs):
                continue
            if _dispatch_verdict(cand, pool)[0] == "可派":
                routes.append(cand + "（" + pool + "）")
    return routes


#: ★ 卡 E110 判据 3：同一个「过期」在两处态度不同——网关硬拒、派活器只提示。
#: 只写在读面这一处；判据本体在 tools/pool/gateway.py 与 tools/wb_dispatch.py，这里不重写。
_WHO_BLOCKS = (
    "  谁拦谁不拦：号池网关会拒（404，一个字节不出网）；派活器只提示不拦"
    "（tools/wb_dispatch.py 的 snapshot_stale_problem 只往 stderr 打一行）"
)

#: ★ 卡 E111 判据 2：这句注解只写一处 —— 人话段与机器块的 dispatch.note 用同一个常量。
#: 写两处就会各漂各的（E107/E109/E110 三张卡的口径都是这么丢的）。
_DISPATCH_NOTE = (
    "（按原名派不出去 ≠ 这条模型用不了：同一个模型在两套 id 体系里名字不同 —— "
    "号池写 provider/model、派活器写裸名。换别名那一条今天真能派。）"
)

# ================================================================ 工具 6：pool_models


def tool_pool_models(
    arguments: dict[str, Any], root: Path = ROOT
) -> tuple[str, dict[str, Any], bool]:
    """号池可用模型：号池批准集 ∩ 快照 + 按池的派活允许集 —— 只读、不联网、不写快照。

    ★ 卡 E107：前半（交集）**不是**派活允许集；真正那份按池现算，见 wb_dispatch。
    """
    pool = find_pool_dir(root)
    if pool is None:
        searched = " 、 ".join(
            (base / "infra" / "pool").as_posix() for base in (root, *root.parents)
        )
        text = (
            f"没有：从 {root.as_posix()} 向上没找到号池目录"
            f"（找的是各级 `<祖先>/infra/pool/pool_models.py`）。找过：{searched}"
        )
        return _result(text, {"found": False, "pool_dir": None}, is_error=True)
    info = load_pool_models(pool)
    if not info["whitelist_exists"] and not info["snapshot_exists"]:
        text = (
            f"没有：号池目录 {pool.as_posix()} 里既没有 {info['whitelist']}，"
            f"也没有 {info['snapshot']}。"
        )
        return _result(text, {"found": False, **info}, is_error=True)
    # ★ 卡 E111 判据 5：探测命令**现算一次**，人话段两处与机器块 snapshot_probe 都用它；
    #   各拼一句的话，机器块那份迟早和人话段那份说两样（E110 只修了人话段）。
    probe: dict[str, Any] = {"command": probe_command(pool), "hint": probe_hint(pool)}
    # ★ 卡 E131：**坏文件是读数，不是「没有这份文件」**。哪份坏了就点名哪份 + 解析错误首行，
    #   整条工具给 is_error=True（判据 1/2）；形状不对走同一支（判据 2，「结构不对：…」）。
    unreadable = [info["whitelist_error"], info["snapshot_error"]]
    if any(item is not None for item in unreadable):
        bad_lines = [f"号池可用模型（pool_models）—— 读 {pool.as_posix()}（读不懂 ⇒ 不猜）"]
        for item, what in (
            (info["whitelist_error"], "批准集"),
            (info["snapshot_error"], "快照"),
        ):
            if item is None:
                continue
            bad_lines.append(
                f"读不懂：{item['file']} 坏了 —— {item['error']}"
                f" ⇒ 不知道{what}是什么，不猜（★ 坏文件 ≠ 没有这份文件；{probe['hint']}）"
            )
        return _result(
            "\n".join(bad_lines),
            {
                **info,
                "found": True,
                "in_both_is_a_dispatch_allow_list": False,
                "snapshot_probe": probe,
            },
            is_error=True,
        )
    lines = [
        f"号池可用模型（pool_models）—— 读 {pool.as_posix()}（★ 快照，非现场拉取；"
        f"{info['snapshot']} at={info['snapshot_at']}）",
        "批准集（models.whitelist.toml，只有用户能改）："
        + ("、".join(info["approved"]) if info["approved"] else "（没有批准项）"),
    ]
    # ★ 卡 E107：这句话原来写的是「交集（真正允许派活的）」—— 撒谎。
    #   in_both 只是号池两份**静态产物**的交集（whitelist ∩ 快照），派活器判的是
    #   wb_dispatch.effective_allowed_models(pool)（注册表该池条目 + 一次性授权 + 开关文件），
    #   而且两套 id 口径不同（号池 provider/model、派活器裸名）。它谁都冒充不了 ——
    #   最坏时它空，文案却说「拒绝派活」，而派活器那边照样能派。
    lines.append(
        "号池快照里「批准 ∩ 可用」："
        + ("、".join(info["in_both"]) or "（空）")
        + "（★ 这不是派活允许集：它是号池两份静态产物的交集，"
        "与派活器判的那份不是同一件事，见下）"
    )
    # ★ 卡 E107 判据 2：新鲜度必须出现在**人话段**。三态，缺一态就是把「不知道」洗成「新鲜」。
    age = info["snapshot_age_hours"]
    stale_hours = info["snapshot_stale_hours"]
    # ★ 卡 E110（T-AG619）：两个「不新鲜」的态都带上 probe_hint（命令 + 现算路径）；
    #   「谁拦谁不拦」只在 _WHO_BLOCKS 里写一份（两个不新鲜的态都要带出来）。
    if info["snapshot_at"] is None:
        lines.append(
            f"快照新鲜度：不知道它多旧（{info['snapshot']} 里没有 at 时间戳）"
            f" ⇒ 不当成新鲜，也不当成过期；{probe['hint']}"
        )
        lines.append(_WHO_BLOCKS)
    elif info["snapshot_stale"]:
        lines.append(
            f"快照新鲜度：已过期 {age} 小时（上限 {stale_hours}h）⇒ 先重新探测再派活；"
            + probe["hint"]
        )
        lines.append(_WHO_BLOCKS)
    else:
        lines.append(f"快照新鲜度：没过期（{age} 小时前，上限 {stale_hours}h）")
    if info["approved_but_missing"]:
        lines.append("批准了但快照里没有（派它必失败）：" + "、".join(info["approved_but_missing"]))
    if info["live_but_unapproved"]:
        lines.append(
            "服务端有但未批准（只报告，绝不自动启用 → 等你一句「批 X」）："
            + "、".join(info["live_but_unapproved"])
        )
    # ★ 卡 E107 判据 1：真名单**按池**现算（判据只有一份，就在 wb_dispatch 里）。
    #   不写死名单、不另造一份；注册表坏了只让**这一段**没答案（判据 3）。
    lines.append(
        "派活允许集（wb_dispatch.effective_allowed_models(pool)：注册表该池条目"
        " + 一次性授权 + 开关文件里打开的；★ 这里现算，不写死）"
    )
    # ★ 卡 E111（T-AG620）判据 1：这一段先算**一份结构**（dispatch），再用它渲染人话段、
    #   并原样塞进机器块。原来是边算边拼字符串 —— 结构只活在局部变量里，机器块拿不到，
    #   于是人话段判完三张卡的事，机器读者一个字段都读不到（这就是本卡的现场）。
    dispatch: dict[str, Any] = {
        # 判不了 ⇒ None（不是 []、不是 {}：空列表读起来是「判完了，一条都没有」）
        "verdicts": None,
        "counts": None,
        "allow_lists": None,
        "pools_unwired": None,
        "note": _DISPATCH_NOTE,
        "error": None,
    }
    _ordered: list[str] = []
    try:
        from pool.model_registry import (  # noqa: PLC0415
            DEFAULT_POOL,
            KNOWN_POOLS,
            get_adapter,
        )

        ordered = [DEFAULT_POOL] + [n for n in KNOWN_POOLS if n != DEFAULT_POOL]
        _ordered = ordered
        allow_lines: list[str] = []
        allow_lists: dict[str, list[str]] = {}
        pools_unwired: list[str] = []
        for name in ordered:
            allowed = wb_dispatch.effective_allowed_models(name)
            allow_lists[name] = list(allowed)
            wired = get_adapter(name).wired
            if not wired:
                pools_unwired.append(name)
            # ★ 未接的池如实标「未接」：名单照给（那是它的允许集），但派它会被拒。
            #   注记放在**第一个全角冒号之前**、且自身不含全角冒号 —— 机器读这段按第一个「：」切。
            mark = "" if wired else "（未接 ⇒ 派它会被拒）"
            allow_lines.append(f"· {name}{mark}：" + ("、".join(allowed) or "（空 ⇒ 派什么都拒）"))
    except Exception as exc:  # noqa: BLE001 —— 只读面：坏输入不许把整个 tools/call 打成异常
        lines.append(f"派活允许集读不出来：{type(exc).__name__}：{exc}")
        dispatch["error"] = f"{type(exc).__name__}：{exc}"
        try:
            from pool.model_registry import registry_path  # noqa: PLC0415

            _where = registry_path().as_posix()
        except Exception:  # noqa: BLE001 —— 连路径都问不出来就如实说，不编一个
            _where = "（问不出来：pool.model_registry.registry_path() 自己也抛了）"
        # ★ 卡 E109（T-AG618）：这句话原来写死「注册表在 infra/pool/model-registry.toml」——
        #   真路径是**本仓** tools/pool/model-registry.toml（registry_path() 现算），照旧文案
        #   去仓外那个位置翻是找不到的（只读面给错指针 = 让人白找）。
        lines.append(
            f"  指针：注册表在 {_where}（或用 TF_MODEL_REGISTRY 指过去）；"
            " 读不到就不列 —— 不猜、不退回内置名单"
        )
    else:
        lines.extend(allow_lines)
        dispatch["allow_lists"] = allow_lists
        dispatch["pools_unwired"] = pools_unwired
    # ★ 卡 E109（T-AG618）判据 1：批准集**逐条**给按池的真判决 —— 「今天派不派得出去」。
    #   为什么非有不可：批准集用的是号池 id（provider/model），派活器用裸名，按原名逐字过闸
    #   今天**一条都过不去**；只报「允许集」等于让人以为「没模型可用」。判据只有一份，
    #   这里只负责问（_dispatch_verdict 的判序与 tools/wb_dispatch.py 的 main() 一字不差）。
    if _ordered:
        try:
            lines.append("")
            lines.append(
                "按池判决（批准集里每一条今天派不派得出去；判序 = 派活主闸，现算不写死）："
            )
            judged: list[dict[str, Any]] = []
            for name in info["approved"]:
                cells: dict[str, dict[str, str]] = {}
                parts: list[str] = []
                for pool in _ordered:
                    verdict, why = _dispatch_verdict(name, pool)
                    cells[pool] = {"verdict": verdict, "why": why}
                    if verdict == "可派":
                        parts.append(f"{pool} 可派")
                    elif why:
                        parts.append(f"{pool} {verdict}（{why}）")
                    else:
                        parts.append(f"{pool} {verdict}")
                routes = _alias_routes(name, _ordered)
                judged.append(
                    {
                        "name": name,
                        "pools": cells,
                        "aliases": list(routes),
                        "dispatchable": any(c["verdict"] == "可派" for c in cells.values()),
                    }
                )
                route = "、".join(routes) if routes else "（没有）"
                lines.append(f"· {name} —— " + "、".join(parts) + f"｜可派别名：{route}")
            counts = {
                "approved": len(info["approved"]),
                "origin": sum(1 for row in judged if row["dispatchable"]),
                "alias": sum(1 for row in judged if row["aliases"]),
            }
            lines.append(
                f"号池批准集 {counts['approved']} 条 / 按原名今天派得出去 {counts['origin']} 条 / "
                f"换别名能派 {counts['alias']} 条"
            )
            lines.append("  " + _DISPATCH_NOTE)
            dispatch["verdicts"] = judged
            dispatch["counts"] = counts
        except Exception as exc:  # noqa: BLE001 —— 只读面：一段算不出来不许把整个调用打成异常
            lines.append(f"按池判决读不出来：{type(exc).__name__}：{exc}")
            dispatch["error"] = f"{type(exc).__name__}：{exc}"
    # ★ 卡 E111 判据 2/3/5：机器块不是人话段的抄本 —— 它是同一份结构的另一处渲染。
    #   in_both_is_a_dispatch_allow_list 恒 False：E107 的结论是**口径**问题（两套 id 体系
    #   本来就不通用），不是「今天数据恰好空」；数据空了也不许把这个布尔翻成 True。
    return _result(
        "\n".join(lines),
        {
            **info,
            "in_both_is_a_dispatch_allow_list": False,
            "snapshot_probe": probe,
            "dispatch": dispatch,
        },
        is_error=False,
    )


# ================================================================ 工具 7：quota_status（卡 201）


def tool_quota_status(
    arguments: dict[str, Any], root: Path = ROOT
) -> tuple[str, dict[str, Any], bool]:
    """额度四态（卡 201）—— 按「记录时间 vs 现实时间」判，**只读、当场算、不探测**。

    ★ 用户原话：「429 了不要凭记忆确定是否 429，要根据记录时间和现实时间对比」。
      这个工具就是那条判据的 MCP 面 —— 会话里问「现在能不能派活」得到的是**读数**，
      不是人的记忆。四态都不猜：`未记录` 不当可用、`已过期` 不当可用。
    """
    import pool_quota  # noqa: PLC0415 —— 同一个 tools/ 目录

    card = str(arguments.get("card") or "").strip()
    model = str(arguments.get("model") or "").strip()
    now = arguments.get("now") or None
    if not card or not model:
        text = "quota_status：card 和 model 都要给（例如 card=201, model=deepseek-v4.1-flash）。"
        return _result(text, {"state": None, "card": card, "model": model}, is_error=True)
    # ★ 卡 E131 判据 4：now 认不出 ⇒ 点名格式，不许把 ValueError 冒成协议层错误（-32603）。
    try:
        st = pool_quota.status(card=card, model=model, now=now, root=root)
    except pool_quota.BadNowError as exc:
        text = f"quota_status：{exc}"
        return _result(text, {"state": None, "card": card, "model": model}, is_error=True)
    text = pool_quota.render(st)
    # ★ 卡 E131 判据 3：记录文件坏了是读数 —— 与「未记录」不同形，给 is_error=True。
    return _result(text, st, is_error=st.get("state_file_broken") is not None)


# ============================================================ 工具 7.5：account_status（卡 E45）


def tool_account_status(
    arguments: dict[str, Any], root: Path = ROOT
) -> tuple[str, dict[str, Any], bool]:
    """账号账本读数（卡 E45）—— **只读账本，不探测、不联网、不动凭据**。

    ★ 为什么不在这里顺手探一下额度：探测要发网络请求、要用凭据、会被 429 咬；
      「看一眼有哪些号」不该有副作用。真探测是 `tools/pool_accounts.py probe`（人手动跑）。
    """
    import pool_accounts  # noqa: PLC0415 —— 同一个 tools/ 目录

    platform = str(arguments.get("platform") or "").strip() or None
    wanted = str(arguments.get("id") or "").strip() or None

    ledger = None
    try:
        ledger = pool_accounts.find_ledger()
    except pool_accounts.LedgerError:
        for base in (root, *root.parents):
            cand = base / "infra" / "pool" / "accounts.toml"
            if cand.is_file():
                ledger = cand.resolve()
                break
    if ledger is None:
        text = (
            "没有：从当前目录与仓库根向上都没找到 infra/pool/accounts.toml"
            "（账本在仓外，可用 TF_ACCOUNTS_TOML 指定；建账本见卡 E45 的 add 动作）。"
        )
        return _result(text, {"found": False, "ledger": None}, is_error=True)

    try:
        data = pool_accounts.load_ledger(ledger)
    except pool_accounts.LedgerError as exc:
        return _result(f"账本读不了：{exc}", {"found": False, "ledger": str(ledger)}, is_error=True)

    rows = pool_accounts.list_rows(data, platform, False)
    if wanted:
        rows = [r for r in rows if r["id"] == wanted]
        if not rows:
            return _result(
                f"账本 {ledger.as_posix()} 里没有账号 {wanted!r}",
                {"found": True, "ledger": str(ledger), "accounts": []},
                is_error=True,
            )

    lines = [f"账号账本（account_status）—— 读 {ledger.as_posix()}（★ 仓外文件，不进 git）"]
    never: list[str] = []
    tried: list[str] = []
    for row in rows:
        models = "、".join(row["models"]) if row["models"] else "（未批准任何模型 ⇒ 不许派活）"
        lines.append(
            f"- {row['id']} · {row['platform']} · {row['state']}"
            f" · 额度 {row['quota']} · 批准 {models}"
        )
        (tried if row.get("quota_kind") or row.get("quota_at") else never).append(row["id"])
    if not rows:
        lines.append("（这个筛选条件下一个号都没有）")
    if rows:
        # ★ 卡 E118：一行汇总，把「探过没探到」与「从没探过」当面分开 ——
        #   改之前这两件事在读数上是同一个词，而它们在派活决策上不是一回事。
        kinds: dict[str, int] = {}
        for row in rows:
            kind = row.get("quota_kind")
            label = kind if isinstance(kind, str) and kind else "探过但没记结论码"
            if row.get("quota_kind") or row.get("quota_at"):
                kinds[label] = kinds.get(label, 0) + 1
        tally = "、".join(f"{k}×{n}" for k, n in sorted(kinds.items())) or "（无）"
        lines.append(
            f"- 读数补充：探过没探到 {len(tried)} 个（末条结论码 {tally}）；"
            f"账本里从没探过 {len(never)} 个 —— 只有后者才叫「未观测」。"
        )
    lines.append("只读读数，不探测；要真探额度请人手动跑 tools/pool_accounts.py probe。")
    return _result(
        "\n".join(lines), {"found": True, "ledger": str(ledger), "accounts": rows}, is_error=False
    )


# ================================================= 工具 7.6：checkin_status（卡 E48）


_CHECKIN_DIR = Path("gates") / "diag"

# ★ 卡 E130：日期串只能长这样 —— 先看形状（fromisoformat 单独用会放行 20260102 /
#   2026-W01-1，见卡规格问题 1），再用 date.fromisoformat 判日历上有没有这一天。
#   两条缺一不可：只做正则会把 2026-02-30 放过去，只做 fromisoformat 会把 20260102 放过去。
_CHECKIN_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _today_local() -> str:
    """本地时区（UTC+8）的今天 —— 与 `tools/pool_accounts.py checkin` 的留档口径一致。"""
    from datetime import datetime, timedelta, timezone  # noqa: PLC0415

    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def tool_checkin_status(
    arguments: dict[str, Any], root: Path = ROOT
) -> tuple[str, dict[str, Any], bool]:
    """今日签到读数（卡 E48 / 卡 E119）—— **只读留档 + 账本，不联网、永不触发签到**。

    ★ 为什么不在这里顺手签一下：签到是**写动作**（会真领积分、会打上游、会被 429 咬）。
      只读入口给"今天签了没"，签不签由人开口（卡 §1 的拉取式定形）。
    ★ 卡 E119：留档（gates/diag/checkin-<日期>.json）与账本（仓外 accounts.toml 的
      health.last_checkin / health.last_probe）是**两件事**，payload 分开摆
      （found 只指留档；账本另用 ledger_found / ledger_rows / ledger_error）。
      账本里的 last_checkin 是**结论码**、不是"今天的时刻" —— 所以每行都带
      last_probe 的日期并用 is_today 标明它是不是 date 那天的结论；
      拿 22 天前的 uncertain 冒充今天，就是第二次撒谎。
    """
    import json  # noqa: PLC0415

    import pool_accounts  # noqa: PLC0415 —— 同一个 tools/ 目录

    date = str(arguments.get("date") or "").strip() or _today_local()
    # ★ 卡 E130：date 是**用户串**，直接拼进路径等于把它当文件名用 —— 2026-11-17 实测
    #   date="../../../../outside/secret" 真读到了树外 JSON 并渲染进正文。校验必须在拼路径
    #   **之前**：拦下来时连 stat 都不做（payload 里没有 archive 键）。
    #   写法上两条一起：正则管形状（挡 20260102 / 2026-W01-1 / 全角数字 / 带路径），
    #   date.fromisoformat 管日历（挡 2026-02-30 / 2026-13-99）—— 只留一条都会漏。
    if not _CHECKIN_DATE_RE.match(date):
        return _result(
            f"date 不是 YYYY-MM-DD 形状：{date!r} ⇒ 拒收"
            "（只收四位年-两位月-两位日，例如 2026-11-17）",
            {"date": date, "rejected": "format"},
            is_error=True,
        )
    try:
        datetime.date.fromisoformat(date)
    except ValueError:
        return _result(
            f"date 不是日历上的一天：{date!r} ⇒ 拒收（要 YYYY-MM-DD，例如 2026-11-17）",
            {"date": date, "rejected": "calendar"},
            is_error=True,
        )
    # ★ 卡 E114：留档**读端**必须是**写端**那一棵树。写端 pool_accounts.write_checkin_archive()
    #   恒落 pool_accounts.DATA_ROOT（即 pipe_root.data_root()）；从前读端用传进来的 root ——
    #   而 MCP 服务端传的恒是模块级 ROOT（工具根），于是从 profile 目录拉起时两边永不相交。
    #   调用方**显式给了另一棵树**（夹具 root=tmp_path）时仍尊重它：那是「给我哪个根就读哪个根」。
    archive_root = root if root != ROOT else pool_accounts.DATA_ROOT
    archive = archive_root / _CHECKIN_DIR / f"checkin-{date}.json"

    payload: dict[str, Any] = {"date": date, "archive": str(archive), "found": archive.is_file()}
    lines = [f"今日签到（checkin_status）—— {date}"]
    lines.append(
        f"留档路径：{archive.as_posix()}"
        f"（与签到写入端同一个根；换一棵树读的是另一份）"
    )
    if archive.is_file():
        try:
            data = json.loads(archive.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return _result(f"留档读不了：{exc}", {**payload, "found": False}, is_error=True)
        rows = data.get("results") or []
        payload.update({"applied": bool(data.get("applied")), "results": rows})
        for row in rows:
            tail = f"（{row['detail']}）" if row.get("detail") else ""
            credit = f" +{row['credit']}" if row.get("credit") else ""
            lines.append(
                f"- {row.get('id')} · {row.get('platform')} · {row.get('kind')}{credit}{tail}"
            )
        counts: dict[str, int] = {}
        for row in rows:
            counts[str(row.get("kind"))] = counts.get(str(row.get("kind")), 0) + 1
        mode = "已真签" if data.get("applied") else "只探未领"
        lines.append(
            f"小计（{mode}）："
            + (" · ".join(f"{k}={v}" for k, v in counts.items()) or "0 个号")
        )
    else:
        lines.append(f"没有留档：{archive.as_posix()}")
        lines.append(
            "今天还没跑过签到（或那天没跑）——要签就人跑 tools/pool_accounts.py checkin --all。"
        )

    # ---- 账本那一段（只读；卡 E119：照 account_status 的 two-except 形状）----
    led_path = None
    try:
        led_path = pool_accounts.find_ledger()
    except pool_accounts.LedgerError:
        for base in (root, *root.parents):
            cand = base / "infra" / "pool" / "accounts.toml"
            if cand.is_file():
                led_path = cand.resolve()
                break

    led_rows: list[dict[str, Any]] = []
    led_error = ""
    if led_path is None:
        led_error = (
            "没找到账号账本：从当前目录与仓库根向上都没找到 infra/pool/accounts.toml"
            "（账本在仓外，可用 TF_ACCOUNTS_TOML 指定）。"
        )
    else:
        try:
            led_data = pool_accounts.load_ledger(led_path)
        except (pool_accounts.LedgerError, FileNotFoundError) as exc:
            led_error = f"账本读不了：{exc}"
        else:
            for acc in pool_accounts.visible_accounts(led_data, False):
                health = acc.get("health") or {}
                probe = str(health.get("last_probe") or "")
                probe_date = probe[:10] or None
                led_rows.append(
                    {
                        "id": acc.get("id"),
                        "platform": acc.get("platform"),
                        "last_checkin": health.get("last_checkin"),
                        "last_probe": probe,
                        "last_probe_date": probe_date,
                        "is_today": probe_date == date if probe_date else False,
                    }
                )

    payload.update(
        {
            "ledger": str(led_path) if led_path is not None else None,
            "ledger_found": bool(led_path is not None) and not led_error,
            "ledger_rows": led_rows,
            "ledger_error": led_error,
        }
    )

    if led_error:
        lines.append(f"账本（仓外，只读）：{led_error}")
    else:
        _shown = str(led_path).replace(chr(92), "/")
        lines.append(f"账本（仓外，只读）：{_shown}")
        if archive.is_file():
            lines.append("留档是同日的 ⇒ 以留档为准；账本这一行只记最近一次问的结论码。")
        for row in led_rows:
            if row["last_probe_date"] is None:
                lines.append(f"- {row['id']} · {row['platform']} · 没问过（账本里没有 last_probe）")
            elif row["is_today"]:
                lines.append(
                    f"- {row['id']} · {row['platform']} · 最近一次问是 {row['last_probe_date']}"
                    f"（= {date}）· {row['last_checkin']}"
                )
            else:
                lines.append(
                    f"- {row['id']} · {row['platform']} · 最近一次问是 {row['last_probe_date']}"
                    f" · {row['last_checkin']}（不是 {date} 的结论，别当今天的）"
                )
        if not led_rows:
            lines.append("（账本里一个号都没有）")

    lines.append("只读读数：不触发签到、不联网、不写账本。")
    return _result(chr(10).join(lines), payload, is_error=False)


# ================================================================ 工具 8：workbench_board（卡 213）


def _board_subset(reading: dict[str, Any], section: str | None) -> dict[str, Any]:
    """按块名取子集：块本身 + 它的 `<块>_*` 说明键（`cards_note` / `fences_broken` …）。

    ★ **原样**取，不填默认、**不洗 null** —— `pipeline_view` 说"这块是 null + 为什么"，
      这里就把 `null` 与那句说明**一起**端出去（卡 213 的硬约束）。
    """
    if section is None:
        return reading
    return {k: v for k, v in reading.items() if k == section or k.startswith(section + "_")}


def _board_rel(path: Any, root: Path) -> Any:
    """卡树路径改成**相对读数根**的 posix 路径（不是字符串 / 换盘符算不出 ⇒ 原样，不编）。"""
    if not isinstance(path, str) or not path:
        return path
    try:
        rel = os.path.relpath(path, root)
    except ValueError:  # 不同盘符：相对不了，原样给绝对路径，不编一个假的相对路径
        return path
    return Path(rel).as_posix()


def _board_compact(
    reading: dict[str, Any], fields: str, root: Path = ROOT
) -> dict[str, Any]:
    """把一份读数压成默认瘦的投影（卡 E125）—— **只做投影，一个读数都不重算**。

    ★ 只掐三块：
      - cards：每行 files/depends 换成 files_n/depends_n（整数＝数组长；原值不是 list ⇒ None，
        **不许编 0**）；status=done 的行只留 {id, status}（**折叠不是过滤**：行数、id 顺序不动）；
        顶层加 cards_done_n（派生计数一律以 <块名>_ 打头，否则 section 过滤会漏/带错）。
      - verdicts：每行 attempts 换成 attempts_n（整数），其余键原样。
      - worktrees：path 换成相对读数根的 posix 路径，dirty 与其它键原样。
    ★ gates / leases / fences 三块一字不动；块本身是 None 的**原样 None**（不洗成 []/0/{}）；
      <块>_note 一字不改。fields="full" ⇒ 原样返回（与 pipeline_view 逐键相同）。
    """
    if fields != "summary":
        return reading
    out = dict(reading)
    cards = out.get("cards")
    if isinstance(cards, list):
        rows: list[Any] = []
        done_n = 0
        for row in cards:
            if not isinstance(row, dict):
                rows.append(row)
                continue
            if row.get("status") == "done":
                done_n += 1
                rows.append({k: row[k] for k in ("id", "status") if k in row})
                continue
            slim = {k: v for k, v in row.items() if k not in ("files", "depends")}
            for key in ("files", "depends"):
                val = row.get(key)
                slim[key + "_n"] = len(val) if isinstance(val, list) else None
            rows.append(slim)
        out["cards"] = rows
        out["cards_done_n"] = done_n
    verdicts = out.get("verdicts")
    if isinstance(verdicts, list):
        vrows: list[Any] = []
        for row in verdicts:
            if not isinstance(row, dict):
                vrows.append(row)
                continue
            attempts = row.get("attempts")
            slim_v = {k: v for k, v in row.items() if k != "attempts"}
            slim_v["attempts_n"] = len(attempts) if isinstance(attempts, list) else None
            vrows.append(slim_v)
        out["verdicts"] = vrows
    worktrees = out.get("worktrees")
    if isinstance(worktrees, list):
        wrows: list[Any] = []
        for row in worktrees:
            if not isinstance(row, dict):
                wrows.append(row)
                continue
            wrows.append({**row, "path": _board_rel(row.get("path"), root)})
        out["worktrees"] = wrows
    return out


def _board_line(section: str, reading: dict[str, Any]) -> str:
    """一块的**人话**一行（只念数，不重算读数 —— 数都从已解析的 JSON 里取）。"""
    val = reading.get(section)
    note = reading.get(f"{section}_note")
    if val is None:
        return f"  · {section}：**没有** —— {note or '（来源缺失，未给说明）'}"
    if isinstance(val, list):
        extra = ""
        if section == "fences" and reading.get("fences_broken"):
            extra = f"（另有坏文件 {len(reading['fences_broken'])} 个）"
        elif section == "leases":
            # ★ 卡 E128：dead 列就在这份 JSON 里（卡 E115 算好的）—— 这里只念数，不重算 TTL。
            dead = sum(1 for lc in val if isinstance(lc, dict) and lc.get("dead"))
            unknown = sum(1 for lc in val if isinstance(lc, dict) and lc.get("dead") is None)
            bits = ([f"其中 {dead} 条已死"] if dead else []) + (
                [f"{unknown} 条判不出"] if unknown else [])
            if bits:
                extra = "（" + "，".join(bits) + "）"
        tail = f" —— {note}" if note else ""
        return f"  · {section}：{len(val)} 项{extra}{tail}"
    if section == "gates" and isinstance(val, dict):
        items = val.get("items") or []
        return (
            f"  · gates：ok={val.get('ok')} rev={val.get('rev')} 共 {len(items)} 道"
            f"{(' —— ' + note) if note else ''}"
        )
    return f"  · {section}：{json.dumps(val, ensure_ascii=False, sort_keys=True)}"


def tool_workbench_board(
    arguments: dict[str, Any], root: Path = ROOT
) -> tuple[str, dict[str, Any], bool]:
    """工作台一份读数（卡 213）—— **只调** `tools/pipeline_view.py --json`，**不重写判据**。

    ★ 判据只许一份真源（卡 207 的 `pipeline_view` 把六块收成一份）：这里**不**读队列 /
      不读门禁 / 不读租约，只把它的 `--json` **原样**端出来。
    ★ 缺什么说什么：某块是 `null` + 说明时**原样透传** —— 不许洗成空对象、不许省略。
    ★ 子进程带 `NO_WINDOW` 且**限时**（`WORKBENCH_TIMEOUT`）：非零 / 超时 / 起不来都
      **如实报错**（`is_error=True`、`reading=None`），**绝不**返回一个"看起来正常"的空板子。
    """
    section = str(arguments.get("section") or "").strip() or None
    if section is not None and section not in WORKBENCH_SECTIONS:
        text = (
            f"workbench_board：不认识的 section={section!r}；六块是："
            + "、".join(WORKBENCH_SECTIONS)
            + "。不给 section 就一次给全。"
        )
        return _result(text, {"section": section, "reading": None}, is_error=True)
    fields = str(arguments.get("fields") or "").strip() or "summary"
    if fields not in WORKBENCH_VIEWS:
        text2 = (
            f"workbench_board：不认识的 fields={fields!r}；只有 "
            + "、".join(WORKBENCH_VIEWS)
            + "（summary 默认=瘦，full=全明细）。"
        )
        return _result(
            text2, {"section": section, "fields": fields, "reading": None}, is_error=True
        )
    argv = [sys.executable, "-X", "utf8", str(PIPELINE_VIEW), "--json", "--root", str(root)]
    command = _cmd_text(argv)
    code, out, err = _run_bounded(argv, root, WORKBENCH_TIMEOUT)
    if code != 0:
        body = "\n".join(x for x in (out.strip(), err.strip()) if x) or "（子进程没有输出）"
        what = "没跑起来（起不来或超时）" if code is None else f"退出码 {code}（不是 0）"
        text = (
            f"workbench_board：**没能拿到读数** —— 我是跑 `{command}`，它 {what}。\n"
            f"pipeline_view 的原样输出：\n{body}\n"
            f"（★ 我没拿一个空板子糊弄你：非零/超时就是没读到读数。）"
        )
        return _result(
            text,
            {
                "command": command,
                "exit_code": code,
                "section": section,
                "reading": None,
                "stdout": out,
                "stderr": err,
            },
            is_error=True,
        )
    try:
        reading = json.loads(out)
    except json.JSONDecodeError as exc:
        text = (
            f"workbench_board：`{command}` 退 0，但 stdout 不是 JSON（{exc}）。"
            f"原样输出：\n{out.strip()}"
        )
        return _result(
            text,
            {
                "command": command,
                "exit_code": code,
                "section": section,
                "reading": None,
                "stdout": out,
            },
            is_error=True,
        )
    if not isinstance(reading, dict):
        text = f"workbench_board：`{command}` 的 JSON 顶层不是对象（是 {type(reading).__name__}）。"
        return _result(
            text,
            {"command": command, "exit_code": code, "section": section, "reading": None},
            is_error=True,
        )
    reading = _board_compact(reading, fields, root)
    shown = [section] if section is not None else list(WORKBENCH_SECTIONS)
    lines = [f"工作台读数（workbench_board）—— 来自 `{command}`（卡 207 的一份读数，六块）："]
    lines += [_board_line(sec, reading) for sec in shown]
    data = {
        "command": command,
        "exit_code": 0,
        "section": section,
        "fields": fields,
        "reading": _board_subset(reading, section),
    }
    return _result("\n".join(lines), data, is_error=False)


# ================================================================ 任务面（卡 121）：只读三个
#
# ★ 全部 **import `pool.task`**：任务状态住在**主工作树**的 `gates/diag/batch/`（`TF_BATCH_DIR`
#   可覆盖），不是本树 —— 与 `pool.task` 一致，不另算一份根。**一个字节都不写**。


def _task_batch_dir(root: Path | None = None) -> Path:
    """任务目录（可能还不存在）—— 转发 `pool.task.batch_dir(root)`（`TF_BATCH_DIR` 覆盖）。

    ★ 卡 E114：把**调用方给的 root** 传下去。从前这里不收参数，于是三个 `task_*` 面
      不管调用方给哪个根，都只读「工具目录所在那棵树」—— 从 profile 目录拉起时回
      「一个任务都没有」，而真值上百个。`TF_BATCH_DIR` 仍排第一（自证注入点，语义一字未动）。
    """
    return task.batch_dir(root)


def _load_tasks(
    batch_root: Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """把批目录里的任务状态都读（跳过 `pool.json`）。**只读**。

    ★ 卡 E129：返回 `(states, broken)` —— 读不了的**点名交出来**，不许静默丢掉。
    丢掉就等于「盘上没这个文件」，而那正是本卡要修的病（读不懂被洗成不存在）。
    broken 每条是 `{"file": "<名>.json", "error": "<原因>"}`；目录冒充、非 UTF-8、
    坏 JSON、缺 declared 都进 broken。
    """
    root = _task_batch_dir(batch_root)
    if not root.exists():
        return [], []
    out: list[dict[str, Any]] = []
    broken: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        if path.name == "pool.json":
            continue
        try:
            st = task.read_json(path)
        except (task.BatchError, OSError, UnicodeDecodeError) as exc:
            broken.append({"file": path.name, "error": str(exc)})
            continue
        if not isinstance(st.get("declared"), list):
            broken.append(
                {"file": path.name, "error": "结构不对：缺 declared 列表（不猜成空名单）"}
            )
            continue
        out.append(st)
    return out, broken


def tool_task_list(
    arguments: dict[str, Any], root: Path = ROOT
) -> tuple[str, dict[str, Any], bool]:
    """所有任务一行：任务号 / 状态 / 成送申请进度 / 一句话 why（**只读**）。

    ★ 卡 E129：读不了的状态文件**点名念出来**（`broken` 通道），计数与盘上的文件对得上。
    """
    try:
        root_dir = _task_batch_dir(root)
        states, broken = _load_tasks(root)
    except task.BatchError as exc:
        return _result(
            f"task_list：读不了任务目录：{exc}",
            {"count": 0, "tasks": [], "broken": []},
            is_error=True,
        )
    head = f"任务栅栏（task_list）—— 读 {root_dir.as_posix()}"
    if not states and not broken:
        return _result(
            head + "\n（一个任务都没有）",
            {"batch_dir": root_dir.as_posix(), "count": 0, "tasks": [], "broken": []},
            is_error=False,
        )
    tail = f"，另有 {len(broken)} 个状态文件读不了" if broken else ""
    lines = [head + f"（共 {len(states)} 个任务{tail}）"]
    rows: list[dict[str, Any]] = []
    for st in states:
        ok = task._ok(st)
        waived = list(st.get("waived") or [])
        missing = task._missing(st)
        rows.append(
            {
                "id": st.get("id"),
                "state": st.get("state"),
                "need": st.get("need"),
                "success": len(ok),
                "waived": waived,
                "missing": missing,
                "why": st.get("why"),
            }
        )
        extra = f"（豁免 {len(waived)}）" if waived else ""
        lines.append(
            f"  · {st.get('id')}  [{st.get('state')}]  成送申请 {len(ok)}/{st.get('need')}"
            f"{extra}  还缺：{missing or '（齐了）'}  —— {st.get('why')}"
        )
    for item in broken:
        lines.append(f"  ★ 读不了：{item['file']} —— {item['error']}")
    data = {
        "batch_dir": root_dir.as_posix(),
        "count": len(states),
        "tasks": rows,
        "broken": broken,
    }
    return _result("\n".join(lines), data, is_error=False)


def tool_task_status(
    arguments: dict[str, Any], root: Path = ROOT
) -> tuple[str, dict[str, Any], bool]:
    """一个任务的详情：每张卡的**层**与**域**、交没交、history 尾部（**只读**）。"""
    task_id = str(arguments.get("task") or "").strip()
    if not task_id:
        return _result(
            "task_status：得给我一个任务号（task）。我是照 `task` 找 `<批目录>/<任务号>.json` 的。",
            {"task": None, "found": False},
            is_error=True,
        )
    try:
        root_dir = _task_batch_dir(root)
        sp = task.state_path(task_id, root)
    except task.BatchError as exc:
        return _result(
            f"task_status：算不出任务目录：{exc}", {"task": task_id, "found": False}, is_error=True
        )
    if not sp.exists():
        return _result(
            f"没有：{root_dir.as_posix()} 里没有任务 {task_id} 的状态文件（{sp.name}）"
            f"—— 还没注册，或不在这个树里（我不假装有）。",
            {"task": task_id, "found": False, "batch_dir": root_dir.as_posix()},
            is_error=True,
        )
    try:
        st = task.read_json(sp)
        if not isinstance(st.get("declared"), list):
            # ★ 卡 E129：缺名单就**说清读不了**，不猜成空名单（空名单 = 齐了 = 撒谎）。
            raise task.BatchError("结构不对：缺 declared 列表（不猜成空名单）")
        man = task.load_manifest(task_id, root)
    except task.BatchError as exc:
        return _result(
            f"task_status：读不了任务 {task_id}：{exc}",
            {"task": task_id, "found": True},
            is_error=True,
        )
    claims = st.get("claims") or {}
    waived = list(st.get("waived") or [])
    lines = [
        f"任务 {task_id}：{st.get('why')}",
        f"  状态 **{st.get('state')}** · 层 {'、'.join(st.get('layers') or [])}"
        f" · 自动 {st.get('auto')} · 期限 {st.get('deadline') or '（无）'}",
        f"  成送申请 {len(task._ok(st))}/{st.get('need')} · 豁免 {len(waived)}"
        f" · 还缺 {task._missing(st) or '（齐了）'}",
    ]
    members: list[dict[str, Any]] = []
    for mem in man["member"]:
        mid = mem["id"]
        kind = claims.get(mid)
        if mid in waived:
            tag = "★豁免"
        elif kind == "success":
            tag = "✓成功申请"
        elif kind == "failed":
            tag = "✗不通过"
        else:
            tag = "…还缺"
        members.append(
            {
                "id": mid,
                "layer": mem["layer"],
                "what": mem.get("what"),
                "paths": list(mem.get("paths") or []),
                "claim": kind,
                "waived": mid in waived,
            }
        )
        lines.append(
            f"  [{tag:<8}] {mid} · 层 {mem['layer']} · 域 {'、'.join(mem.get('paths') or [])}"
        )
    history = list(st.get("history") or [])
    lines.append("  --- history（尾部）---")
    for row in history[-8:]:
        lines.append(f"  {row.get('at')} {row.get('from')}→{row.get('to')} {row.get('note')}")
    data = {
        "task": task_id,
        "found": True,
        "state": st.get("state"),
        "why": st.get("why"),
        "layers": st.get("layers"),
        "need": st.get("need"),
        "success": len(task._ok(st)),
        "waived": waived,
        "missing": task._missing(st),
        "claims": claims,
        "members": members,
        "history": history,
        "history_total": len(history),
        "batch_dir": root_dir.as_posix(),
    }
    return _result("\n".join(lines), data, is_error=False)


def tool_task_pool(
    arguments: dict[str, Any], root: Path = ROOT
) -> tuple[str, dict[str, Any], bool]:
    """待办登记表：还没定卡的活，**按层**（只读）。"""
    try:
        root_dir = _task_batch_dir(root)
        rows = task._load_pool(root)
    except task.BatchError as exc:
        return _result(
            f"task_pool：读不了待办表：{exc}",
            {"found": False, "count": 0, "pool": []},
            is_error=True,
        )
    if not rows:
        return _result(
            f"待办登记（task_pool）—— {root_dir.as_posix()} 里没有待办（pool.json 不存在或为空）。",
            {"batch_dir": root_dir.as_posix(), "found": True, "count": 0, "layers": {}, "pool": []},
            is_error=False,
        )
    by_layer: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_layer.setdefault(str(row.get("layer") or "（没写层）"), []).append(row)
    lines = [f"待办登记（task_pool）—— 读 {root_dir.as_posix()}（共 {len(rows)} 条，按层）"]
    for layer, items in by_layer.items():
        lines.append(f"  层 {layer}：")
        for row in items:
            domain = "、".join(row.get("files") or []) or "——"
            lines.append(f"    · {row.get('id')}  {row.get('what')}  域 {domain}")
    data = {
        "batch_dir": root_dir.as_posix(),
        "found": True,
        "count": len(rows),
        "layers": {lay: [r.get("id") for r in items] for lay, items in by_layer.items()},
        "pool": rows,
    }
    return _result("\n".join(lines), data, is_error=False)


# ================================================================ 写面：pool_dispatch / pool_cancel


def _backlog_for(root: Path) -> Any:
    """读 **root 下**的 backlog（不像 `pool.plan.load_backlog()` 那样固定到导入时的仓库根）。

    ★ 为什么按 root：MCP 服务端的 root 就是主仓；测试把 root 指到临时目录时读的也是那一份，
      不与别的门共享真 backlog。解析仍是同一个 `load_backlog`（不另写一份 parser）。

    卡 E89：分片在就先读分片（`docs/backlog/*.toml`），口径唯一在
    `wb_plan.load_sharded_backlog`；没有分片就退回总表。
    """
    return wb_plan.load_sharded_backlog(
        root / "docs" / "workbacklog.toml", root / "docs" / "backlog")


def _how_to_pass() -> str:
    """干跑被咬时附给人看的"怎么才能通过"（逐条对得上守卫的措辞）。"""
    return (
        "怎么才能通过：\n"
        "  · 树被占 → 等那张卡的租约释放，或换一棵树（tree）；\n"
        "  · 冲突域相交 → 换一张域不相交的卡，或等对方收工；\n"
        "  · 日志已存在 → 由 wb_dispatch 自己挑 wb-<卡>.r2.jsonl，或先归档旧日志；\n"
        "  · 门禁还在跑 → 等这趟门禁结束（用 lock_status 看进度）。"
    )


def _dispatch_argv(
    card: str,
    spec: str,
    cwd: Path,
    model: str,
    account: str = "",
    sticky: bool = False,
    pool: str = "",
) -> list[str]:
    """给 `wb_dispatch.py` 的 argv —— **写死**，不透传危险项。

    不透传：`--force` / `--allow` / `--resume` / `--no-preflight`。
    ★ 卡 A341（F34）：`--account` **要**透传 —— 工人侧得按同一个账号收窄模型白名单
      （白名单只能收窄不能放宽）；空串就不带这个参数（= 不按账号收窄）。
    ★ 卡 A345（T-AG547）：`--sticky` **要**透传 —— 粘性只在 `wb_dispatch` 那一侧生效
      （它要读 `gates/diag/pool-sticky.json` 并复查账本）；`False` 就不带 ⇒ 既有 argv 逐字不变。
    ★ 卡 E106（T-AG615）：`--pool` **只在非默认池时才带** —— 不给 / 给默认池 ⇒ 既有工人的
      命令行逐字不变（默认池是缺省值，写出来只是多一个 token）；给了别的已接池就必须带，
      否则工人侧按默认池跑，于是「判一个池、登记一个池、跑另一个池」。
    ★ 卡 125：带 `--already-reserved` —— 本函数**上游**（`tool_pool_dispatch`）已经
      `registry.reserve` 过这条树；不带它会撞上 wb_dispatch 新接的 `tree_guard`（自己占的树
      被自己判"被占"）⇒ 派活必被拒。带上它 = wb_dispatch **只跳过**守卫与占/还树，别的前置照走。
    """
    return [
        sys.executable,
        "-X",
        "utf8",
        "tools/wb_dispatch.py",
        "--card",
        card,
        "--spec",
        spec,
        "--cwd",
        str(cwd),
        "--model",
        model,
        "--lean",
        "--detach",
        "--execute",
        "--already-reserved",
        *(("--pool", pool) if pool and pool != wb_dispatch.DEFAULT_POOL else ()),
        *(("--account", account) if account else ()),
        *(("--sticky",) if sticky else ()),
    ]


def _spawn_worker(argv: list[str], root: Path) -> tuple[int | None, str, str]:
    """起工人（带 `--detach`：父进程前置检查完就把自己扔出去，立刻返回）—— 本模块第二处 subprocess。

    返回 `(退出码 | None, stdout, stderr)`；跑不起来**不抛**（调用方据 `OSError` 回滚租约）。
    """
    done = subprocess.run(  # noqa: S603 —— 命令是本地拼死的，不是外部输入
        argv,
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **NO_WINDOW,
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
    return (
        locale.getencoding()
        if hasattr(locale, "getencoding")
        else locale.getpreferredencoding(False)
    ) or "utf-8"


def _image_name(pid: int) -> str | None:
    """`tasklist` 拿这个 pid 的**映像名**；拿不到 → `None`（判不出，**不当作"没在跑"**）。"""
    try:
        done = subprocess.run(  # noqa: S603 —— pid 来自本机登记，不是外部输入
            ["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            encoding=_console_encoding(),
            errors="replace",
            **NO_WINDOW,
        )
    except OSError:
        return None
    line = next((ln for ln in (done.stdout or "").splitlines() if ln.strip()), "")
    if done.returncode != 0 or not line.startswith('"'):
        return None
    return line[1 : line.index('"', 1)]


def _kill(pid: int) -> tuple[bool, str]:
    """`taskkill /F /T /PID <n>` 杀**整棵**（★ 绝不 `os.kill` 探活/杀，见模块头）。"""
    try:
        done = subprocess.run(  # noqa: S603 —— pid 来自本机登记，不是外部输入
            ["taskkill", "/F", "/T", "/PID", str(int(pid))],
            capture_output=True,
            text=True,
            encoding=_console_encoding(),
            errors="replace",
            **NO_WINDOW,
        )
    except OSError as exc:
        return False, f"taskkill 起不来：{type(exc).__name__}: {exc}"
    return done.returncode == 0, ((done.stdout or "") + (done.stderr or "")).strip()


def tool_pool_dispatch(
    arguments: dict[str, Any], root: Path = ROOT
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
            {"card": card, "found": False},
            is_error=True,
        )
    files = list(hit.files)
    spec = str(arguments.get("spec") or "").strip() or hit.spec
    # ★ 卡 E106（T-AG615）：`pool` 一路走到底 —— 判它、登记它、工人也按它跑。
    #   空串 = 不点名 = 默认池（与 `wb_dispatch --pool` 的缺省一致）。
    pool = str(arguments.get("pool") or "").strip() or wb_dispatch.DEFAULT_POOL
    model = str(arguments.get("model") or "").strip()
    # ⑥ 模型白名单（硬闸门）—— **判据只有一份**：调 `wb_dispatch.model_rejected(model, pool)`，
    #   即 CLI 派活主路径过的那一道。★ 不再自己比 `MODEL_WHITELIST`：那只是**轮换链**
    #   （`rotation_chain_for(pool)`），不含一次性授权与外部开关文件里打开的模型 ⇒ 同一个模型
    #   CLI 放得出去、MCP 却被拒（卡 E106 问题 1），而且拒单理由还是个空串（问题 2）。
    #   顺序照 `wb_dispatch.main()` 的模型闸：先答「池认不认 / 接没接 / 注册表读不读得了」，
    #   再答「这个模型批了吗」，最后才轮到「这个账号有没有更窄的白名单」。
    allowed: list[str] = []
    try:
        wb_dispatch.get_adapter(pool)                        # 未知池 ⇒ 拒（不静默降级到别的池）
        wb_dispatch.get_adapter(pool).assert_wired()         # 已知但未接 ⇒ 拒（码道今天就是这条）
        if not model:
            model = wb_dispatch.default_model_for(pool).alias  # 按池取默认（不取注册表首项）
        wb_dispatch.resolve_model(model, pool)               # 跨池串用 ⇒ 拒
        allowed = list(wb_dispatch.effective_allowed_models(pool))
        rejected = wb_dispatch.model_rejected(model, pool)
        # ⑥a′ 卡 E105（T-AG614）：**禁用表** 也要在起工人之前问一句 —— 干跑面会真起进程，
        #   所以禁用的模型必须在这里就拒。判据只有一份：`model_registry.assert_not_disabled`
        #   （与 wb_dispatch 模型闸、gateway `_model_block` 共用同一份），
        #   这里不自己读表、不自己 glob。
        if not rejected:
            wb_dispatch.assert_not_disabled(pool, model)
    except (wb_dispatch.ModelRegistryError, wb_dispatch.PoolMismatchError,
            wb_dispatch.UnknownPoolError, wb_dispatch.PoolNotWiredError,
            wb_dispatch.SwitchFileError) as exc:
        # ★ 卡 E106 问题 4：开关文件坏了必须在这里接住 —— 一个坏 TOML 不许把 `tools/call` 打崩。
        return _result(
            f"模型闸没过，已拒绝派活：{exc}",
            {"card": card, "model": model, "pool": pool, "allowed": allowed},
            is_error=True,
        )
    if rejected:
        # 拒单文案原样带回（它是 `model_rejected` 写的，含允许集与「默认拒绝」口径）。
        return _result(
            rejected,
            {"card": card, "model": model, "pool": pool, "allowed": allowed},
            is_error=True,
        )
    # ⑥b 卡 A341（F34）第 ③ 步：caller（账号）白名单**只收窄** —— 与 wb_dispatch 的派活主路径
    #   调**同一个** `caller_model_rejected()`（判据只有一份）。★ 卡 E106：池名传 `pool`
    #   （不再写死 DEFAULT_POOL）—— 工人侧也按同一个池跑（`_dispatch_argv` 透传 `--pool`），
    #   三处口径才对得上。
    account = str(arguments.get("account") or "").strip()
    # ★ 卡 A344（T-AG546）：先解析再判 —— 判据 5「两处判据只有一份」。`caller_model_rejected()`
    #   的第三参是**账本稳定 id**（仓外 limits.toml 的 `[accounts."<id>"]`），而这里收到的是
    #   profile 名 ⇒ 不解析就永远查不到表（闸等于不生效）。
    #   解析器也只有一份：`wb_dispatch.resolve_account`。
    try:
        account_id, _account_why = wb_dispatch.resolve_account(account)
    except wb_dispatch.AccountMapError as exc:
        return _result(
            f"账号名字判不出是哪个号，已拒绝派活：{exc}",
            {"card": card, "model": model, "account": account},
            is_error=True,
        )
    try:
        caller_rejected = wb_dispatch.caller_model_rejected(
            model, pool, account_id or None)
    except wb_dispatch.ModelRegistryError as exc:
        return _result(
            f"账号白名单读不懂，已拒绝派活：{exc}",
            {"card": card, "model": model, "account": account},
            is_error=True,
        )
    if caller_rejected:
        return _result(
            caller_rejected,
            {"card": card, "model": model, "account": account},
            is_error=True,
        )

    # ② 干跑：三条自家守卫 + 登记里的租约判据（import 调用，不 shell 出去）
    stamp = time.time()
    log_path = diag_dir(root) / f"wb-{card}.jsonl"
    try:
        live = registry.list_reservations(stamp)
        lock_body = registry.read_lock_body()
    except registry.RegistryError as exc:
        return _result(f"pool_dispatch：读登记失败：{exc}", {"card": card}, is_error=True)
    problems = [
        *guards.tree_guard(tree, live, stamp),  # ① 一棵树一个写者
        *guards.domain_guard(files, live, stamp),  # ② 冲突域不相交
        *guards.lock_guard(card, tree, lock_body, root=main_root),  # ③ 门禁还在跑
        *guards.log_guard(log_path),  # ⑤ 日志不许覆盖
    ]
    # ★ 卡 A342：账号白名单（每 caller）—— 调**同一个** `guards.account_guard`，
    #   不另写一份 if（理由见 `tools/pool/__init__.py`：判据只许一份）。
    account = str(arguments.get("account") or "").strip()
    if account:
        try:
            scopes = accounts_scope.load_scopes()
        except accounts_scope.ScopeError as exc:
            problems = [*problems, f"账号白名单读不了（不许当「不收窄」）：{exc}"]
        else:
            problems = [
                *problems,
                *guards.account_guard(
                    account,
                    scopes,
                    card=card,
                    project=str(arguments.get("project") or ""),
                    pool=str(arguments.get("pool") or ""),
                ),
            ]
    if problems:
        text = (
            "pool_dispatch：干跑没过，**不派活**（逐条原因）：\n"
            + "".join(f"  · {item}\n" for item in problems)
            + "\n"
            + _how_to_pass()
        )
        return _result(
            text, {"card": card, "dispatched": False, "problems": problems}, is_error=True
        )

    # ③ 先占位（并发安全的关键：不能"先派活后登记"）
    try:
        lease = registry.reserve(
            card,
            task=hit.task,
            tree=tree,
            files=files,
            pool=str(arguments.get("pool") or ""),
            model=model,
            log=log_path.as_posix(),
            note=str(arguments.get("note") or ""),
            lock_body=lock_body,
        )
    except registry.GuardError as exc:
        text = (
            "pool_dispatch：占位时被守卫拦下，**不派活**：\n"
            + "".join(f"  · {item}\n" for item in exc.problems)
            + "\n"
            + _how_to_pass()
        )
        return _result(
            text, {"card": card, "dispatched": False, "problems": exc.problems}, is_error=True
        )
    except registry.RegistryError as exc:
        return _result(f"pool_dispatch：登记失败（未派活）：{exc}", {"card": card}, is_error=True)

    # ④ 起工人（--detach：立刻返回）；起不来就回滚刚占的租约
    cwd = Path(tree) if Path(tree).is_absolute() else (main_root / tree if tree else main_root)
    argv = _dispatch_argv(card, spec, cwd, model, account,
                          sticky=bool(arguments.get("sticky")), pool=pool)
    try:
        code, out, err = _spawn_worker(argv, root)
    except OSError as exc:
        registry.release(card)
        return _result(
            f"pool_dispatch：工人起不来，已回滚租约：{type(exc).__name__}: {exc}",
            {"card": card, "dispatched": False, "rolled_back": True},
            is_error=True,
        )
    preflight = (out + ("\n" + err if err.strip() else "")).strip()
    pid_hit = _PID_RE.search(preflight)
    if code != 0 or pid_hit is None:
        registry.release(card)
        return _result(
            f"pool_dispatch：wb_dispatch 没把工人扔出去（退出码 {code}），"
            f"已回滚租约：\n{preflight}",
            {
                "card": card,
                "dispatched": False,
                "rolled_back": True,
                "exit_code": code,
                "preflight": preflight,
            },
            is_error=True,
        )
    pid = int(pid_hit.group(1))
    _record_pid(card, pid)

    dispatch_log = log_path.with_name(f"wb-{card}.dispatch.log")
    data = {
        "card": card,
        "tree": tree or "（主树）",
        "cwd": cwd.as_posix(),
        "spec": spec,
        "model": model,
        "log": log_path.as_posix(),
        "dispatch_log": dispatch_log.as_posix(),
        "pid": pid,
        "preflight": preflight,
        "lease": {**lease, "pid": pid},
    }
    text = (
        f"pool_dispatch：卡 {card} 已派（pid {pid}）—— 来自 `{_cmd_text(argv)}`\n"
        f"  log：{log_path.as_posix()}\n"
        f"  dispatch.log：{dispatch_log.as_posix()}\n"
        f"  租约：树 {tree or '（主树）'}｜域 {'、'.join(files)}\n"
        f"  前置检查原文：\n{preflight}\n"
        f"  ★ 用 job_status(card='{card}') 看进度。"
    )
    return _result(text, data, is_error=False)


def tool_pool_cancel(
    arguments: dict[str, Any], root: Path = ROOT
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
        return _result(
            f"pool_cancel：本机登记里没有卡 {card} 的**活租约** —— 不动手。",
            {"card": card, "found": False},
            is_error=True,
        )
    pid = hit.get("pid")
    manual = (
        f"人工怎么做（先看清是不是本卡的活）：\n"
        f'  tasklist /FI "PID eq {pid or "<pid>"}" /FO CSV\n'
        f"  taskkill /F /T /PID {pid or '<pid>'}"
    )
    if not isinstance(pid, int):
        return _result(
            f"pool_cancel：这条租约里没记 pid（不是本 MCP 派的活）→ **拒绝动手**。\n{manual}",
            {"card": card, "found": True, "pid": None},
            is_error=True,
        )
    image = _image_name(pid)
    if image is None or image.lower() not in ("node.exe", "python.exe"):
        return _result(
            f"pool_cancel：**拒绝动手** —— PID {pid} 的映像是 {image or '（查不到，判不出）'}，"
            f"不是 node.exe / python.exe（pid 会被复用，杀错树 = 杀掉别人的东西）。\n{manual}",
            {"card": card, "found": True, "pid": pid, "image": image},
            is_error=True,
        )
    ok, detail = _kill(pid)
    if not ok:
        return _result(
            f"pool_cancel：taskkill 没成功（pid {pid}），租约**没动**：{detail}",
            {"card": card, "pid": pid, "image": image, "killed": False},
            is_error=True,
        )
    note_path = diag_dir(root) / f"wb-{card}.cancel.txt"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        f"card={card} 取消于={datetime.datetime.now().isoformat(timespec='seconds')}\n"
        f"谁：{registry.default_owner()}\n"
        f"pid={pid}（映像 {image}）\n"
        f"为什么：{reason or '（没写理由）'}\n"
        f"结果：taskkill /F /T /PID {pid}\n{detail}\n",
        encoding="utf-8",
    )
    released = registry.release(card)
    data = {
        "card": card,
        "pid": pid,
        "image": image,
        "killed": True,
        "released": released,
        "cancel_txt": note_path.as_posix(),
        "reason": reason,
    }
    text = (
        f"pool_cancel：卡 {card} 的工人已结束（pid {pid}，映像 {image}）\n"
        f"  已写 {note_path.as_posix()}（谁 / 什么时候 / 为什么）\n"
        f"  租约{'已释放' if released else '本来就没有'}。"
    )
    return _result(text, data, is_error=False)


# ================================================================ 任务面（卡 121）：写两个
#
# ★ 判据仍然只有一份（`pool.task`，经 `tools/wb_task.py` 这个壳），但**执行换到子进程**（卡 130）：
#   - `task_register`（快路径，几毫秒）**仍进程内**：复用一个 `pool.task.cmd_register`，
#     `redirect_stdout` 把它的 `print` 收成人话（绝不能漏进协议报文）。
#   - `task_claim` **走子进程** `[python -X utf8 tools/wb_task.py claim …]`：它会跑
#     `on_complete` 里声明的门禁（**5~9 分钟**）—— 进程内跑就是把 MCP 服务进程**冻住 stdio**
#     （连九个只读工具也答不了；服务中途被杀还会把锁与状态一起带走）。子进程里跑 ⇒ **服务进程
#     永远不替别人跑门禁**；`serve()` 再把它交给后台线程（见 `_CLAIM_TOOL`），只读工具照样即刻答。
#   ★ 为什么不是"另写一份判据"：子进程跑的**就是** `wb_task.py` → `pool.task.cmd_claim`，一处判据。

#: `task_claim` 会跑门禁 ⇒ 子进程至少给这么久的超时（卡 130：门禁 6~9 分钟，留足余量）。
CLAIM_TIMEOUT_SECONDS = 1800


def _capture(fn: Any) -> tuple[int, str]:
    """进程内跑一个 `pool.task.cmd_*`（现只给**快路径** register 用），把 `print` 收成字符串。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn()
    return int(rc), buf.getvalue()


def _claim_argv(
    root: Path, task_id: str, member: str, claim: str, evidence: str, files_arg: str, why: str
) -> list[str]:
    """拼 `wb_task.py claim …` 的命令行 —— 与 `pool.task.cmd_claim` 的 CLI 口径**逐字一致**。"""
    argv = [
        sys.executable,
        "-X",
        "utf8",
        str(root / "tools" / "wb_task.py"),
        "claim",
        task_id,
        member,
        "--claim",
        claim,
    ]
    if evidence:
        argv += ["--evidence", evidence]
    if files_arg:
        argv += ["--files", files_arg]
    if why:
        argv += ["--why", why]
    return argv


def _confirm_reject(tool: str, got: str, want: str, what: str) -> tuple[str, dict[str, Any], bool]:
    """`confirm` 与应值不一致 ⇒ **拒**，并把"为什么"说清（防手滑）。`what` 自带引号。"""
    text = (
        f"{tool}：**拒绝** —— arguments.confirm（{got or '空'}）必须等于{what}（{want}）。"
        f"这是防手滑：真要害的是一个任务，就把{what}再写一遍。"
    )
    return _result(text, {"rejected": True, "confirm": got, "expected": want}, is_error=True)


# ================================================================ 卡 136：把 claim 的整棵进程树带走
#
# 卡 130 把 claim 挪进子进程后自己报过一条没治的边界：**超时只带走 `subprocess.run` 的直连子进程**，
# 它再起的 grandchild 门禁进程（Windows）不在它的树下 ⇒ 真正吃 CPU / 占端口的还在跑（"孤儿门禁"）。
# 本段：执行换 `Popen` + `communicate(timeout=…)`；超时 / 失败时复用
# `wb_dispatch.kill_tree`（**按 PID 收子树**，不按进程名 —— 按名字会误伤同名进程）把整棵带走，
# 并把读数**如实**写进回话（杀了哪些 pid / 有没有残留），绝不只说"已清理"。


def _optional_psutil() -> Any:
    """best-effort 取 `psutil`（本仓 dependencies 里没有它）—— 取不到回 `None`（判不了就说判不了）。

    ★ 只用它**点数**（点名 pid / 核残留），**不**用它掐进程 —— 杀树仍走 `wb_dispatch.kill_tree`。
    """
    try:
        import psutil  # type: ignore[import-untyped]  # noqa: PLC0415
    except ImportError:  # pragma: no cover —— 本机有；没有时如实降级
        return None
    return psutil


def _descendant_pids(pid: int) -> list[int]:
    """`pid` 的**后代**（递归子进程）pid —— psutil 不在 / 进程没了 → 空表（判不了 ≠ 没有）。"""
    ps = _optional_psutil()
    if ps is None:
        return []
    try:
        return [child.pid for child in ps.Process(pid).children(recursive=True)]  # type: ignore[no-any-return]
    except Exception:  # noqa: BLE001 —— 进程可能已消失 / 权限不够：判不了就当空
        return []


def _pid_alive(pid: int) -> bool | None:
    """`True` / `False` = 判出来了；`None` = 判不了（psutil 不在）。"""
    ps = _optional_psutil()
    if ps is None:
        return None
    try:
        return bool(ps.pid_exists(pid))
    except Exception:  # noqa: BLE001
        return None


def _reap_claim_tree(proc: subprocess.Popen[str]) -> dict[str, Any]:
    """把 claim 子进程**整棵**带走并给出**如实**读数（卡 136）。

    ★ 复用 `wb_dispatch.kill_tree`（按 PID 收子树）；★ 回话必须点名**杀了哪些 pid / 有没有残留**
    —— 不许只说"已清理"。子进程若已退出（非零退出那条路），如实记"没有活子树可带"。
    """
    alive_before = proc.poll() is None
    pids = [proc.pid, *_descendant_pids(proc.pid)]
    kill_note: str | None = None
    killed = False
    if alive_before:
        try:
            kill_note = wb_dispatch.kill_tree(proc.pid)
            killed = True
        except Exception as exc:  # noqa: BLE001 —— 杀树本身失败也要如实报（钉子③）
            kill_note = f"kill_tree 抛异常：{type(exc).__name__}: {exc}"
        if killed:
            with contextlib.suppress(Exception):
                proc.communicate(timeout=10)  # 排空管道（树已死 → 应立刻返回）
    residual = [pid for pid in pids if _pid_alive(pid) is True]
    return {
        "alive_before": alive_before,
        "killed": killed,
        "pids": pids,
        "kill_note": kill_note,
        "residual": residual,
        "psutil": _optional_psutil() is not None,
    }


def _reap_line(reap: dict[str, Any]) -> str:
    """把 `_reap_claim_tree` 的读数做成人话（★ 有残留就点名"没带走"，绝不吞）。"""
    if not reap.get("alive_before"):
        return "  · 进程树：子进程已退出（没有活子树可带）。"
    pids = "、".join(str(p) for p in reap.get("pids") or []) or "（无）"
    head = (
        f"  · 杀树：wb_dispatch.kill_tree → {reap.get('kill_note')}\n"
        f"  · 目标 pid（直连 + 后代）：{pids}"
    )
    residual = reap.get("residual") or []
    if residual:
        left = "、".join(str(p) for p in residual)
        return f"{head}\n  · 残留：{left} —— **没带走**（这条必须告诉人）"
    if reap.get("psutil"):
        return f"{head}\n  · 残留：无（已核对）"
    return f"{head}\n  · 残留：判不了（psutil 不在，没能核对）"


def tool_task_register(
    arguments: dict[str, Any], root: Path = ROOT
) -> tuple[str, dict[str, Any], bool]:
    """注册一个任务：`manifest_text`（整段 TOML）或 `manifest_path`；`confirm` = TOML 里的 id。"""
    text_arg = arguments.get("manifest_text")
    mpath = str(arguments.get("manifest_path") or "").strip()
    confirm = str(arguments.get("confirm") or "").strip()
    tmp_src: Path | None = None

    if text_arg is not None and str(text_arg).strip():
        raw = str(text_arg)
        try:
            man = tomllib.loads(raw)
        except tomllib.TOMLDecodeError as exc:
            return _result(
                f"task_register：预声明不是合法 TOML：{exc}",
                {"registered": False, "error": "toml"},
                is_error=True,
            )
        task_id = str(man.get("id") or "").strip()
        if not task_id:
            return _result(
                "task_register：预声明里没写 `id`（任务号）。", {"registered": False}, is_error=True
            )
        if confirm != task_id:
            return _confirm_reject("task_register", confirm, task_id, "「TOML 里的 id」")
        try:
            batch = _task_batch_dir()
            batch.mkdir(parents=True, exist_ok=True)
            tmp_src = batch / f".{task_id}.mcp-src.toml"
            tmp_src.write_text(raw, encoding="utf-8", newline="\n")
        except (task.BatchError, OSError) as exc:
            return _result(
                f"task_register：写临时预声明失败：{exc}", {"registered": False}, is_error=True
            )
        src = tmp_src
    elif mpath:
        src = Path(mpath)
        if not src.is_absolute():
            src = root / src
        if not src.exists():
            return _result(
                f"task_register：找不到预声明文件：{src.as_posix()}",
                {"registered": False},
                is_error=True,
            )
        try:
            with src.open("rb") as fh:
                man = tomllib.load(fh)
        except (tomllib.TOMLDecodeError, OSError) as exc:
            return _result(
                f"task_register：读不了预声明：{exc}", {"registered": False}, is_error=True
            )
        task_id = str(man.get("id") or "").strip()
        if not task_id:
            return _result(
                "task_register：预声明里没写 `id`（任务号）。", {"registered": False}, is_error=True
            )
        if confirm != task_id:
            return _confirm_reject("task_register", confirm, task_id, "「TOML 里的 id」")
    else:
        return _result(
            "task_register：得给 `manifest_text`（整段 TOML）或 `manifest_path`。",
            {"registered": False},
            is_error=True,
        )

    try:
        _rc, out = _capture(
            lambda: task.cmd_register(argparse.Namespace(manifest=str(src), force=False))
        )
    except task.RefuseError as exc:
        return _result(
            "task_register：**拒收**：\n" + "\n".join(f"  · {r}" for r in exc.reasons),
            {"registered": False, "task": task_id, "reasons": exc.reasons},
            is_error=True,
        )
    except task.BatchError as exc:
        return _result(
            f"task_register：注册失败（没落成）：{exc}",
            {"registered": False, "task": task_id},
            is_error=True,
        )
    finally:
        if tmp_src is not None:
            with contextlib.suppress(OSError):
                tmp_src.unlink()

    st = task.read_json(task.state_path(task_id))
    manifest = task.manifest_path(task_id)
    data = {
        "registered": True,
        "task": task_id,
        "state": st.get("state"),
        "need": st.get("need"),
        "layers": st.get("layers"),
        "declared": st.get("declared"),
        "manifest": manifest.as_posix(),
        "cli": out.strip(),
    }
    text = (
        f"task_register：任务 {task_id} 注册好了（复用 `pool.task.cmd_register`，进程内）。\n"
        f"  {st.get('need')} 张卡 · 层 {'、'.join(st.get('layers') or [])}\n"
        f"  ★ 放行判据：名单上每一张卡都交了**成功申请**（或缺席者被显式豁免）—— 不看数量。\n"
        f"  预声明：{manifest.as_posix()}"
    )
    return _result(text, data, is_error=False)


def tool_task_claim(
    arguments: dict[str, Any], root: Path = ROOT
) -> tuple[str, dict[str, Any], bool]:
    """一张卡交成送申请：`confirm` = task；★ 逐卡域守卫照走，越界**逐条点名**。"""
    task_id = str(arguments.get("task") or "").strip()
    member = str(arguments.get("member") or "").strip()
    claim = str(arguments.get("claim") or "success").strip()
    confirm = str(arguments.get("confirm") or "").strip()
    evidence = str(arguments.get("evidence") or "")
    why = str(arguments.get("why") or "")
    files = arguments.get("files")
    if isinstance(files, list):
        files_arg = ",".join(str(f).strip() for f in files if str(f).strip())
    else:
        files_arg = str(files or "")
    if not task_id:
        return _result("task_claim：得给我一个任务号（task）。", {"claimed": False}, is_error=True)
    if not member:
        return _result(
            "task_claim：得给我一个卡号（member）。",
            {"task": task_id, "claimed": False},
            is_error=True,
        )
    if claim not in ("success", "failed"):
        return _result(
            f"task_claim：claim 只能是 success / failed（收到 {claim!r}）。",
            {"task": task_id, "member": member, "claimed": False},
            is_error=True,
        )
    if confirm != task_id:
        return _confirm_reject("task_claim", confirm, task_id, "「任务号（task）」")
    argv = _claim_argv(root, task_id, member, claim, evidence, files_arg, why)
    try:
        proc = subprocess.Popen(  # noqa: S603 —— 命令是本地拼死的，不是外部输入
            argv,
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **NO_WINDOW,
        )
    except OSError as exc:
        return _result(
            f"task_claim：子进程起不来：{type(exc).__name__}: {exc}",
            {"task": task_id, "member": member, "claimed": False},
            is_error=True,
        )
    try:
        out, err = proc.communicate(timeout=CLAIM_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        # ★ 卡 136：`subprocess.run` 超时只带走**直连**子进程，它再起的门禁孙进程会成孤儿 ——
        #   所以这里自己按 PID 收整棵子树（复用 wb_dispatch.kill_tree），读数如实写进回话。
        reap = _reap_claim_tree(proc)
        return _result(
            f"task_claim：卡 {member} 的申请**没跑完**（子进程超时 {CLAIM_TIMEOUT_SECONDS}s）。\n"
            f"{_reap_line(reap)}\n"
            f"  ★ 别当成成功 —— 门禁/状态可能没落盘；稍后用 `task_status` 看现状。",
            {"task": task_id, "member": member, "claimed": False, "timeout": True, **reap},
            is_error=True,
        )
    except OSError as exc:
        # 排空/读写出错也是失败路径 —— 同样把树带走（卡 136），别留孤儿。
        reap = _reap_claim_tree(proc)
        return _result(
            f"task_claim：子进程读写出错：{type(exc).__name__}: {exc}\n{_reap_line(reap)}",
            {"task": task_id, "member": member, "claimed": False, **reap},
            is_error=True,
        )
    except Exception as exc:  # noqa: BLE001 —— 执行边界：任何别的失败也把树带走，别留孤儿
        reap = _reap_claim_tree(proc)
        return _result(
            f"task_claim：子进程执行出错：{type(exc).__name__}: {exc}\n{_reap_line(reap)}",
            {"task": task_id, "member": member, "claimed": False, **reap},
            is_error=True,
        )
    rc = int(proc.returncode)
    out = out or ""
    err = err or ""
    if rc != 0:
        # ★ 非零退出 = 没成（域守卫拒收 / 证据缺失 / 门禁红 …）—— **如实带出**输出与退出码，绝不吞。
        #   子进程已退出 ⇒ 正常无活子树；卡 136 仍核一遍（有残留就点名，绝不假装"已清理"）。
        reap = _reap_claim_tree(proc)
        detail = "\n".join(x for x in (out.strip(), err.strip()) if x) or "（子进程没有输出）"
        return _result(
            f"task_claim：卡 {member} 的申请**没跑通**（子进程退出码 {rc}）。\n{detail}\n"
            f"{_reap_line(reap)}",
            {
                "task": task_id,
                "member": member,
                "claimed": False,
                "exit_code": rc,
                "stdout": out,
                "stderr": err,
                **reap,
            },
            is_error=True,
        )
    st = task.read_json(task.state_path(task_id))
    data = {
        "task": task_id,
        "member": member,
        "claim": claim,
        "claimed": True,
        "state": st.get("state"),
        "success": len(task._ok(st)),
        "need": st.get("need"),
        "missing": task._missing(st),
        "exit_code": rc,
        "cli": out.strip(),
    }
    text = (
        f"task_claim：卡 {member} 的申请收了（走 `wb_task.py claim`，子进程）。\n"
        f"  任务 {task_id} 现在：**{st.get('state')}** · 成功申请 "
        f"{len(task._ok(st))}/{st.get('need')} · 还缺 {task._missing(st) or '（齐了）'}"
    )
    return _result(text, data, is_error=False)


# ============================================ 工具 18：usage_report（卡 A364 · T-AG578）


def _usage_faults_reply(faults: list[Any]) -> tuple[str, dict[str, Any], bool]:
    """判据层拒单 ⇒ **逐条**把 faults 原文端出来（吞成"失败了"就等于把原因丢了）。"""
    lines = [f"  · {fault.error_text()}" for fault in faults]
    text = (
        "usage_report：**拒收** —— 判据层（tools/pool/usage_ingest.py）一条都没写盘。\n"
        + "\n".join(lines)
        + "\n（全有或全无：这一批里只要有一条坏，整包都不进账。）"
    )
    data = {
        "accepted": 0,
        "skipped": 0,
        "records": [],
        "faults": [
            {
                "index": fault.index,
                "field": fault.field,
                "msg": fault.msg,
                "text": fault.error_text(),
            }
            for fault in faults
        ],
    }
    return _result(text, data, is_error=True)


def tool_usage_report(
    arguments: dict[str, Any], root: Path = ROOT
) -> tuple[str, dict[str, Any], bool]:
    """外部用量上报（卡 A364）—— **只开入口，不动判据**：校验全在 `pool.usage_ingest`。

    ★ 为什么 `confirm` 是**记录条数**而不是卡号：这一批的规模就是最该先看一眼的东西。
      条数由判据层的 `parse_batch()` 数出来（**不在这里重数字段、重判一遍**），
      所以"能报几条"与"该确认几"永远是同一个数。
    ★ 顺序固定：先解析（判据层全量校验）→ 再核 `confirm`（此时一个字节都还没写）→ 才 `ingest()`。
      判据层是**全有或全无**，所以拒单时目标文件行数与 mtime 都不动。
    """
    body = arguments.get("body")
    if isinstance(body, (list, dict)):  # 直接给对象/数组也认：这里只做 JSON 化，不校验
        raw = json.dumps(body, ensure_ascii=False)
    else:
        raw = "" if body is None else str(body)
    confirm = str(arguments.get("confirm") or "").strip()
    when = datetime.datetime.now(datetime.timezone.utc)

    try:
        rows = usage_ingest.parse_batch(raw, now=when)  # ★ 判据层自己数：一条坏就整包拒
    except usage_ingest.IngestRefused as exc:
        return _usage_faults_reply(list(exc.faults))

    want = str(len(rows))
    if confirm != want:
        given = confirm or "空"
        text = (
            f"usage_report：**拒绝** —— arguments.confirm（{given}）必须等于这一批的记录条数："
            f"收到 {want} 条，confirm 给的 {given}。"
            f"这是防手滑：这一批有 {want} 条，就把 {want} 再写一遍。什么也没写。"
        )
        data = {"rejected": True, "confirm": confirm, "expected": want, "records": []}
        return _result(text, data, is_error=True)

    try:
        payload = usage_ingest.ingest(raw, now=when, root=root)
    except usage_ingest.IngestRefused as exc:  # 两次解析之间文件变了 ⇒ 照实拒，不吞
        return _usage_faults_reply(list(exc.faults))

    accepted = int(payload["accepted"])
    skipped = int(payload["skipped"])
    ledger = usage_ingest.reported_path(root)
    text = (
        f"usage_report：收了 {accepted} 条，跳过 {skipped} 条（同一个记录号已经报过）。\n"
        f"  账本：{ledger.as_posix()}\n"
        f"  ★ 判据全在 tools/pool/usage_ingest.py（本工具只开入口）；这一行**不进**"
        f" wb-usage.jsonl —— 那是派活器自己的账。"
    )
    return _result(text, payload, is_error=False)


# ================================================================ tools/call 调度


_HANDLERS: dict[str, Any] = {
    "pool_plan": tool_pool_plan,
    "job_list": tool_job_list,
    "job_status": tool_job_status,
    "job_result": tool_job_result,
    "lock_status": tool_lock_status,
    "pool_models": tool_pool_models,
    "quota_status": tool_quota_status,
    "account_status": tool_account_status,
    "checkin_status": tool_checkin_status,
    "workbench_board": tool_workbench_board,
    "pool_dispatch": tool_pool_dispatch,
    "pool_cancel": tool_pool_cancel,
    "task_list": tool_task_list,
    "task_status": tool_task_status,
    "task_pool": tool_task_pool,
    "task_register": tool_task_register,
    "task_claim": tool_task_claim,
    "usage_report": tool_usage_report,
}


def call_tool(name: str, arguments: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any] | None:
    """跑一个工具；`None` = **不认识这个名字**（调用方翻成 `-32602`，不崩）。

    ★ 写工具多两道门：① 服务端要有 `POOL_MCP_WRITE=1`（没有就当"没有这个工具"）；
    ② `arguments.confirm` 必须**等于卡号**（防手滑 —— 真要害的一张卡，就把卡号再写一遍）。
    """
    handler = _HANDLERS.get(name)
    if handler is None:
        return None
    args = arguments or {}
    if name in WRITE_NAMES and not write_enabled():
        return None  # 没 env ⇒ 当"没有这个工具"（"存在性即授权"）
    if name in WRITE_NAMES - USAGE_WRITE_NAMES:
        card = str(args.get("card") or "").strip()
        if not card or str(args.get("confirm") or "").strip() != card:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"pool_mcp：写调用被拒 —— arguments.confirm 必须等于卡号"
                        f"（card={card or '?'}）。这是防手滑：真要害的一张卡，就把卡号再写一遍。",
                    }
                ],
                "isError": True,
            }
    if name in TASK_WRITE_NAMES and not write_enabled():
        return None  # 没 env ⇒ 当"没有这个工具"（"存在性即授权"）；confirm 判据在 handler 里
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
            "lock_status / pool_models / quota_status / account_status / checkin_status / "
            "workbench_board，加任务面的 "
            "task_list / task_status / task_pool，"
            "十三个都只读（不写文件、不派活、不抢锁、不要 env）。"
            "quota_status（卡 201）按「记录时间 vs 现实时间」判额度四态 —— "
            "限流中 / 已过期，需重新探测 / 余额耗尽 / 未记录，不猜、不探测。"
            "workbench_board（卡 213）把 pipeline_view 的一份读数（卡 / 门禁 / 判决 / 租约 / "
            "栅栏 / 卡树六块）收成一份端到会话内 —— 不给 section 就一次看全六块，"
            "某块缺来源会如实给 null + 说明（不洗成空对象）。默认瘦（fields=summary）："
            "cards 每行 files/depends 只给计数（files_n/depends_n）、已完卡折叠成只含 id 与 "
            "status 的骨架行（行数与顺序不动），verdicts 每行 attempts 只给计数（attempts_n），"
            "卡树路径相对读数根；fields=full 才给全明细（与 pipeline_view 逐键相同）。"
            "account_status（卡 E45）读仓外账号账本；"
            "checkin_status（卡 E48 / E119）读当天签到留档，"
            "并只读账本的 health.last_checkin / last_probe（按 last_probe 日期标明是哪天的结论）—— "
            "两个都只读、都不联网、都**不触发**任何动作（签到要人跑 pool_accounts.py checkin）。"
            "**写工具**（pool_dispatch 派活 / pool_cancel 取消 / task_register 注册任务 / "
            "task_claim 交成送申请 / usage_report 外部用量上报）只有在**服务端**设了 "
            "POOL_MCP_WRITE=1 时才列出来 —— 那是"
            "「存在性即授权」：没这个 env 就没有写工具。号池写工具每次调用还要 arguments.confirm "
            "**等于卡号**（usage_report 例外：它的 confirm 等于**这一批的记录条数**）；"
            "任务写工具里 task_register 的 confirm 等于 TOML 里的 id、"
            "task_claim 的 confirm 等于 task（防手滑）。"
            "usage_report（卡 A364）是外部用量上报的唯一入口 —— 判据全在 "
            "tools/pool/usage_ingest.py（本工具只开入口、不重写校验），上报行落 "
            "gates/diag/usage-reported.jsonl，**不进**派活器自己的 wb-usage.jsonl。"
            "pool_dispatch 的顺序固定：先干跑守卫（被咬就不派活、逐条给原因）→ 先占树 → 起工人"
            "（--detach，立刻返回）→ 起不来就回滚租约；危险参数一律不透传。"
            "pool_cancel 只取消本机登记里那张卡的工人，**先核对 pid 身份**（映像必须是 node.exe / "
            "python.exe），不对就拒绝动手。"
            "任务面的判据只有一份（都跑 tools/pool/task.py）：task_register 进程内、快；"
            "task_claim 走**子进程**（它会跑门禁，5~9 分钟 ⇒ 不许冻住 stdio），且走**逐卡域"
            "守卫**，碰了域外文件会**点名拒收**、子进程非零退出时回话原样带出它的输出与退出码。"
            "命令失败会带回**原样命令**；产物缺失会明说'没有'。"
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
            extra = (
                ""
                if write_enabled()
                else "（本服务现在只有只读工具 —— 写工具要服务端设 POOL_MCP_WRITE=1 才列出来。）"
            )
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
        "  python -X utf8 tools/pool_mcp.py --http --port 8765 --host 127.0.0.1\n"
        "          起 Streamable HTTP 服务（远程用；先设 TF_MCP_HTTP_TOKEN，没设就退 2）\n"
        "          --host 只收 127.0.0.1 / localhost / ::1（默认只绑回环）\n"
        "\n"
        "只读工具：pool_plan / job_list / job_status(card) / job_result(card) / "
        "lock_status / pool_models / quota_status(card,model) / workbench_board(section?) / "
        "task_list / task_status(task) / task_pool。\n"
        "写工具（要服务端 env POOL_MCP_WRITE=1 才列出来）：pool_dispatch / pool_cancel"
        "（confirm=卡号）、task_register（confirm=TOML 里的 id）、task_claim（confirm=task）、"
        "usage_report（confirm=这一批的记录条数）。\n"
        '客户端配置（示例）：command = python，args = ["-X", "utf8", '
        '"tools/pool_mcp.py"]。stdout 只走协议。\n'
    )


# ================================================================ stdio 主循环


#: 唯一**会被交给后台线程**的工具（卡 130）：它跑门禁、要 5~9 分钟，绝不许冻住主循环。
#: 别的工具（含快路径 `task_register`）都还在主循环里**当场答**。
_CLAIM_TOOL = "task_claim"

#: stdout 只有一处写（`_emit`）—— 主循环与 claim 后台线程都会写，串起来（卡 130）。
_SEND_LOCK = threading.Lock()


def _emit_locked(payload: dict[str, Any]) -> None:
    """`_emit` 的加锁版：主循环与后台线程共用一条 stdout，别让两条报文绞在一起。"""
    with _SEND_LOCK:
        _emit(payload)


def _is_claim_call(message: dict[str, Any]) -> bool:
    """这条消息是不是 `tools/call` → `task_claim`（唯一的慢工具）。"""
    if str(message.get("method") or "") != "tools/call":
        return False
    params = message.get("params")
    if not isinstance(params, dict):
        return False
    return str(params.get("name") or "") == _CLAIM_TOOL


def serve(tail: list[str]) -> int:
    """stdio 主循环：读一行、处理、回一行；EOF 就退 0。

    三道防线（前两条照抄先例，缺一条就真出事）：
    ① `_pin_stdio_utf8()` 钉编码；
    ② 一条坏消息（不是 UTF-8 / 不是 JSON / 处理时异常）只换**一条错误回话**，循环继续 ——
       客户端拿到一条 JSON-RPC 错误还能接着用，拿到 EOF 只会以为"服务坏了"；
    ③ ★ 卡 130：`task_claim` 会跑 5~9 分钟的门禁 ⇒ 把它交给**后台线程**，主循环**继续读**
       （只读工具照样即刻答）。它是**串行**的（一个后台 worker + FIFO），所以回话顺序对
       register/claim 这类连着来的写调用**仍是请求顺序**，不会有两条 claim 抢着写。
    ④ ★ 卡 A362（F7）：一行**有字节上限**（`MAX_LINE_BYTES`）。超限只换**一条错误回话**
       （-32602，文案带上实际字节数与上限）+ 把这一行剩余字节吃完，然后**接着服务**。
    """
    for token in tail:
        if token in ("-h", "--help"):
            print(_usage())
            return 0
        print(f"pool_mcp 不认识的参数 {token!r}（只认 --help）", file=sys.stderr)
        return 2

    _pin_stdio_utf8()

    # 慢工具（task_claim）的 FIFO：一个后台 worker，串行处理，主循环不等它。
    pending: queue.Queue[dict[str, Any] | None] = queue.Queue()

    def _answer(message: dict[str, Any]) -> None:
        """处理一条消息并按需回一条（异常只换一条错误回话，绝不把循环打死）。"""
        try:
            answer = handle(message, root=ROOT)
        except Exception as exc:  # noqa: BLE001 —— 协议边界：任何异常只换一条错误回话
            print(f"[pool_mcp] 处理这条消息时出错：{type(exc).__name__}: {exc}", file=sys.stderr)
            answer = {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {
                    "code": JSONRPC_INTERNAL_ERROR,
                    "message": (f"服务端处理这条消息时出错：{type(exc).__name__}: {exc}"),
                },
            }
        if answer is not None:
            _emit_locked(answer)

    def _slow_worker() -> None:
        while True:
            message = pending.get()
            if message is None:  # 主循环收工（EOF）时会放这个哨兵
                return
            _answer(message)

    worker = threading.Thread(target=_slow_worker, name="pool-mcp-slow", daemon=True)
    worker.start()

    while True:
        try:
            line = _read_line()
        except LineTooLong as exc:
            # ★ 卡 A362（F7）：先**把这一行剩下的字节吃到行尾**，再回话 —— 否则残余会被当成
            #   下一行（回一条「不是合法 JSON」，看上去像客户端发错了，其实是服务端没吃完）。
            #   stdio 是长连接、没有 `Connection: close`（magpie 有，这里没有对应物）：
            #   只回一条错误、**这一行不执行**，然后接着服务下一行。
            total = exc.size + _drain_line()
            _emit_locked(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": JSONRPC_INVALID_PARAMS,
                        "message": (
                            f"这一行太长：{total} 字节，本服务一行最多 {MAX_LINE_BYTES} 字节"
                            f"（{MAX_LINE_BYTES >> 20} MiB）；这一行没有执行，下一行照常处理。"
                        ),
                    },
                }
            )
            continue
        except UnicodeDecodeError as exc:
            _emit_locked(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": JSONRPC_PARSE_ERROR, "message": f"这一行不是 UTF-8：{exc}"},
                }
            )
            continue
        if line is None:  # EOF：客户端走了
            break
        text = line.strip()
        if not text:
            continue
        try:
            message = json.loads(text)
        except ValueError as exc:
            _emit_locked(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": JSONRPC_PARSE_ERROR, "message": f"不是合法 JSON：{exc}"},
                }
            )
            continue
        if not isinstance(message, dict):
            _emit_locked(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": JSONRPC_PARSE_ERROR, "message": "消息必须是对象"},
                }
            )
            continue
        if _is_claim_call(message):
            pending.put(message)  # 慢工具 → 后台串行跑，主循环继续读
            continue
        _answer(message)
    pending.put(None)  # 收工：让 worker 把手上那条跑完、把回话吐完再退
    worker.join()
    return 0


#: `--http` 的默认端口（与 `wb_dash.py` 的 8787 错开）。
HTTP_DEFAULT_PORT = 8765


def _run_http(tail: list[str]) -> int:
    """`--http` 分支：解析 `--host` / `--port` → 读 env → 起 `pool.mcp_http`。

    ★ 判据都在 `pool/mcp_http.py`（Origin / Bearer / 版本头 / 上限 / 202-405）；
    这里只做三件事：**解析参数**、**把 env 读成值**、**把 `handle` 传进去**。
    参数不认 / 主机不在回环集 / 没有 token ⇒ **退 2** 并印理由。
    """
    from pool import mcp_http  # noqa: PLC0415 —— 只有 --http 才需要它

    host = mcp_http.DEFAULT_HOST
    port = HTTP_DEFAULT_PORT
    i = 0
    while i < len(tail):
        item = tail[i]
        if item == "--http":
            i += 1
            continue
        if item in ("--host", "--port"):
            if i + 1 >= len(tail):
                print(f"pool_mcp {item} 缺一个值", file=sys.stderr)
                return 2
            value = tail[i + 1]
            if item == "--host":
                host = value
            else:
                try:
                    port = int(value)
                except ValueError:
                    print(f"pool_mcp --port 要整数，收到 {value!r}", file=sys.stderr)
                    return 2
            i += 2
            continue
        print(f"pool_mcp --http 不认识的参数 {item!r}（只认 --port / --host）", file=sys.stderr)
        return 2
    if not 0 <= port <= 65535:
        print(f"pool_mcp --port 越界：{port}（0~65535）", file=sys.stderr)
        return 2

    token = os.environ.get(mcp_http.TOKEN_ENV, "")
    if not token:
        print(
            "pool_mcp --http 需要鉴权：先设环境变量 TF_MCP_HTTP_TOKEN（一串随机字符）再起服务。\n"
            '  PowerShell：$env:TF_MCP_HTTP_TOKEN = "<随机串>"\n'
            "  cmd：set TF_MCP_HTTP_TOKEN=<随机串>\n"
            "  客户端：Authorization: Bearer <同一个串>\n"
            '  生成随机串：python -c "import secrets;print(secrets.token_urlsafe(32))"',
            file=sys.stderr,
        )
        return 2

    origins = mcp_http.split_origins(os.environ.get(mcp_http.ORIGINS_ENV))
    require_origin = mcp_http.require_origin_from_env(os.environ.get(mcp_http.REQUIRE_ORIGIN_ENV))
    try:
        return mcp_http.serve_http(
            handle,
            host=host,
            port=port,
            token=token,
            origins=origins,
            max_bytes=MAX_LINE_BYTES,
            protocols=KNOWN_PROTOCOLS,
            require_origin=require_origin,
            log=lambda line: print(line, file=sys.stderr, flush=True),
        )
    except mcp_http.ConfigError as exc:
        print(f"pool_mcp --http 起不来：{exc}", file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    """命令入口：`--help` 给人看；其余一个参数都没有（MCP 客户端的 args 就该是空）。"""
    tail = list(sys.argv[1:] if argv is None else argv)
    if not tail:
        return serve(tail)
    if any(token in ("-h", "--help") for token in tail):
        print(_usage())
        return 0
    if "--http" in tail:
        return _run_http(tail)
    print(f"pool_mcp 不认识的参数 {tail!r}（只认 --help 与 --http）", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
