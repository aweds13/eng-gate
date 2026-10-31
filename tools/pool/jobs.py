r"""作业状态 / 扫日志（从 `tools/wb_status.py` 与 `tools/pool_mcp.py` 抽，卡 106 · T-G202）。

**防什么**：外包模式下工人 agent 在**别的进程**里干活，主控与用户看不见它做了什么 —— 只能读它
留下的 log。这里把两件事做成**只读、无副作用**的纯函数，让 CLI（`wb_status.py`）与号池 MCP
（`job_list` / `job_status`）**共用同一批实现**，不再各写一份（本仓最忌的"两份真源"）。

| 组 | 函数 | 干什么 |
|---|---|---|
| 读日志 | `parse_events`/`clip`/`tool_line`/`message_of` | 把 stream-json 渲成时间线 + 摘要 |
| 三态判据 | `classify_job_state`/`scan_jobs` | 在跑 / 已判决 / 断了（不猜） |
| 产物定位 | `diag_dir`/`card_artifacts`/`card_of` | 精确匹配文件名（宽 glob 会串卡） |
| 口径 | `is_card_log`/`non_card_reason` | 哪几个 `wb-*.jsonl` **不是卡**（全仓唯一定义，卡 E74） |
| 渲染 | `render_timeline`/`render_json`/`repo_state` | 拼成 `wb_status.py` 的那段人话 |

★ 阈值 (`STALL_SECONDS` / `HEARTBEAT_SECONDS`) 与 `tools/wb_dispatch.py` **同一口径**，由
`tests/test_pool_mcp.py::test_thresholds_match_the_dispatch_tool` 钉住（不另立一套）。
★ 只读：本模块不写任何文件；`repo_state()` 只跑 `git status/log` 两条**只读**命令。
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

MAX_TEXT = 240          # 一句话最多显示多少字（长输出不许刷屏）
MAX_FILE = 12           # 摘要里最多列几个文件

#: 与 `tools/wb_dispatch.py` **同一口径**（不另立一套阈值）。
STALL_SECONDS = 480         # 日志静默多久算"断了"（wb_dispatch.STALL_SECONDS）
HEARTBEAT_SECONDS = 120     # 心跳行间隔（只在说明里引用）
REPORT_MAX_CHARS = 4000     # `job_result` 单份原文最多显示多少字（截断要明示总长）

#: `gates/diag/wb-*.jsonl` 里**不是卡**的那一族 —— **全仓唯一一份定义**（卡 E74 · T-AG576）。
#: 写成正则而不是枚举：带轮次的变体（`wb-usage.r2.jsonl`）同办，新增一本旁账**只改这一行**。
#: 今天两条真值：`wb-usage[.r<N>].jsonl`（派活器追加的 token 用量账，T-G137）与
#: `wb-route.jsonl`（F39 路由回放，一行一轮，卡 A363）。
NON_CARD_LOG_RE = re.compile(r"^wb-(?P<kind>usage|route)(?:\.r\d+)?\.jsonl$")

#: 非卡日志各是哪一本账（`scan_jobs` 把这句话念出来）。★ 认不出的 kind 走通用那句 ——
#: 所以给上面那个正则加新名字，**这里不用跟着改**（判据 6：一处加、三处生效）。
NON_CARD_REASONS = {
    "usage": "用量账（wb_dispatch 追加的 token 账），不是派活日志",
    "route": "路由回放（F39 换号记录，一行一轮），不是派活日志",
}


def is_card_log(name: str) -> bool:
    """`gates/diag/` 里这个文件名算不算**一张卡的派活日志** —— 判据只许一份，三处读者都问它。

    `wb-001.jsonl` / `wb-B1.jsonl` / `wb-B-20261052.jsonl` / `wb-105.r2.jsonl` ⇒ True；
    `wb-usage.jsonl` / `wb-usage.r2.jsonl` / `wb-route.jsonl` ⇒ False。
    """
    return NON_CARD_LOG_RE.match(name) is None


def non_card_reason(name: str) -> str:
    """这个名字不是卡的理由；是卡 ⇒ `""`（`scan_jobs` 用它写「非派活」那一行的 why）。"""
    hit = NON_CARD_LOG_RE.match(name)
    if hit is None:
        return ""
    return NON_CARD_REASONS.get(hit.group("kind"), f"{name} 是旁账日志，不是派活日志")


# ================================================================ 读日志：渲染时间线 / 摘要


def clip(text: object, limit: int = MAX_TEXT) -> str:
    """压成一行、按字数截断 —— 日志里的东西可能是几万字的文件内容。"""
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def tool_line(name: str, payload: dict) -> str:
    """把一次工具调用压成一行 —— 优先显示"它动了哪儿"（路径/命令/查询）。"""
    if not isinstance(payload, dict):
        return f"{name} {clip(payload, 120)}"
    keys = (
        "file_path", "command", "pattern", "path", "notebook_path",
        "url", "query", "description", "prompt", "old_string",
    )
    for key in keys:
        if key in payload and payload[key]:
            return f"{name}({key}={clip(payload[key], 160)})"
    if payload:
        return f"{name}({clip(json.dumps(payload, ensure_ascii=False), 160)})"
    return f"{name}()"


def message_of(event: dict) -> tuple[dict, str | None]:
    """取 `message`；畸形 log（不是 dict）不许炸（T-G96 边界① / T-G125）。

    返回 `(message, 坏行)`：`message` 缺失或为 None → 空对象（老口径，当没有）；
    是字符串 / 列表等 → 给出可渲染的坏行（认不出来的一行也不丢），`message` 位返回空对象。
    """
    message = event.get("message")
    if message is None:
        return {}, None
    if isinstance(message, dict):
        return message, None
    return {}, f"  ?  message 不是对象（{type(message).__name__}）：{clip(message, 160)}"


#: 工人日志的编码**按 BOM 判**（卡 E75）—— 顺序有意义：先 utf-16 的两个，再 utf-8 的。
_BOM_CODECS: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
)


class UnknownLogEncodingError(ValueError):
    """没有 BOM、又不像 UTF-8 的日志 —— **不猜**，让调用方看见（卡 E75 判据 4）。

    今天的病是反过来的：`errors="replace"` 让解码**永不失败**，于是读错编码也没人知道，
    2096 行乱码一路走到时间线上、`tool_calls` 静默变成 0。宁可抛，也不要静默当空。
    ★ 要不要吞掉它由调用方决定：`usage_in()` / `usage_summary()` / `_verdict_log_lines()`
      的契约是"读不出来就跳过、不抛"（它们的 docstring 写着），那三处显式捕获；
      `wb_status` / `wb_diag` / `pool_mcp` / 派活器那几处**不捕获** —— 让人看见才是判据 4。
    """


def log_codec(data: bytes) -> str:
    """按 **BOM** 判这份日志该用什么编码解 —— 看字节再决定，**不试**（卡 E75）。

    `ff fe` ⇒ `utf-16-le`、`fe ff` ⇒ `utf-16-be`、`ef bb bf` ⇒ `utf-8-sig`、无 BOM ⇒ `utf-8`。

    ★ 为什么不"先按 utf-8 读，失败再退回 utf-16"：那种写法把"这份文件到底是什么"交给运气 ——
      带 BOM 的 UTF-16 用 `errors="replace"` 读**永远不会失败**（它只是变成一堆带 NUL 的乱码），
      于是退回那一步永远走不到。判据 4 的"认不出时不许猜"就是这么丢的。
    """
    for bom, codec in _BOM_CODECS:
        if data.startswith(bom):
            return codec
    if b"\x00" in data:
        raise UnknownLogEncodingError(
            "没有 BOM，但字节里带 NUL —— 像 UTF-16/32 又没 BOM，不猜编码"
            f"（{len(data)} 字节）")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UnknownLogEncodingError(
            f"没有 BOM，也不是合法的 UTF-8（{exc.reason} @ 第 {exc.start} 字节）—— "
            "不猜编码：要么在源头写对，要么给这份日志补 BOM") from exc
    return "utf-8"


def read_log_lines(path: Path) -> list[str]:
    """把一份工人日志读成 `lines` —— 全仓**唯一**的读法（卡 E75 判据 5）。

    先读**字节**、按 BOM 判编码（见 `log_codec`），再 `splitlines()`。`parse_events()` 吃的是
    `lines`，所以编码判错 = **整条时间线静默消失**：`gates/diag/wb-045.jsonl`（UTF-16LE 带 BOM）
    按 UTF-8 读出来 2096 行乱码、`tool_calls` 0、`models` 空；按 BOM 读出来 122 行事件、
    `tool_calls` 35、`models == ["glm-5.3-flash"]`。

    ★ `errors="replace"` **留着**：它治的是"坏几个字节就读不下去"，不是治编码（编码由
      `log_codec` 判）。删掉它本卡所有钉子都不变红 —— 这条实测记在卡 E75 的缺口里，
      别以为它是本卡的判据。
    ★ 不归并的四处（都不是工人日志，各有各的读法）：`pool/landing.py`（按 `=== … ===` 分节读
      文档件）、`run_logged.py`（读自己刚写的 tail）、`stack.py`（读 `stack-actions.log`）、
      `wb_brief.py`（读 markdown 规矩件）。
    ★ `wb_dash.py::_read_log_lines` 是**另一套语义**（无 BOM 含 NUL 时逐行救、救不出就当
      "日志不可解析"），本卡不裁决哪个对 —— 见卡 E75 缺口：同一份坏日志，`wb_dash` 会救、
      `wb_status` 会抛 `UnknownLogEncodingError`，两个入口结论不同。
    """
    data = path.read_bytes()
    codec = log_codec(data)
    for bom, _ in _BOM_CODECS:
        if data.startswith(bom):    # BOM 是"声明的编码"，不是正文 —— 剥掉再解，别留成 \ufeff
            data = data[len(bom):]
            break
    return data.decode(codec, errors="replace").splitlines()


def parse_events(lines: list[str]) -> tuple[list[str], dict]:
    """把 JSONL 渲染成 `(时间线, 摘要)`。认不出的行原样留着 —— 不静默丢东西。"""
    timeline: list[str] = []
    tools: Counter[str] = Counter()
    files: list[str] = []
    models: list[str] = []
    texts = 0
    errors = 0
    final: str | None = None
    unknown = 0

    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            unknown += 1
            timeline.append(f"  ?  非 JSON 行：{clip(raw, 160)}")
            continue
        if not isinstance(event, dict):
            unknown += 1
            timeline.append(f"  ?  非对象事件：{clip(raw, 160)}")
            continue

        kind = str(event.get("type") or event.get("event") or "")
        subtype = str(event.get("subtype") or "")

        # ① 开场：把它的模型与工具清单说出来（"它到底有没有 grep"这种问题看这里）
        if kind == "system" and subtype == "init":
            model = event.get("model")
            if model:
                models.append(str(model))
            tools_now = event.get("tools") or []
            if isinstance(tools_now, list) and tools_now:
                timeline.append(f"  开  init  model={model}  tools={len(tools_now)}："
                                + clip(", ".join(str(t) for t in tools_now), 300))
            else:
                timeline.append(f"  开  init  model={model}")

        # ② 助手说话 / 调工具
        elif kind == "assistant":
            message, bad_message = message_of(event)
            if bad_message:
                unknown += 1
                timeline.append(bad_message)
                continue
            content = message.get("content")
            if isinstance(content, str):
                texts += 1
                timeline.append(f"  说  {clip(content)}")
                continue
            for item in content or []:
                if not isinstance(item, dict):
                    timeline.append(f"  说  {clip(item)}")
                    continue
                if item.get("type") == "text" and item.get("text"):
                    texts += 1
                    timeline.append(f"  说  {clip(item['text'])}")
                elif item.get("type") == "tool_use":
                    name = str(item.get("name") or "?")
                    tools[name] += 1
                    payload = item.get("input") or {}
                    if isinstance(payload, dict):
                        for key in ("file_path", "path", "notebook_path"):
                            got = payload.get(key)
                            if got and str(got) not in files:
                                files.append(str(got))
                    timeline.append(f"  做  {tool_line(name, payload)}")

        # ③ 工具回话（成功/失败）
        elif kind == "user":
            message, bad_message = message_of(event)
            if bad_message:
                unknown += 1
                timeline.append(bad_message)
                continue
            content = message.get("content")
            items = content if isinstance(content, list) else []
            for item in items:
                if not isinstance(item, dict) or item.get("type") != "tool_result":
                    continue
                if item.get("is_error"):
                    errors += 1
                    timeline.append(f"  错  {clip(item.get('content'), 200)}")
                else:
                    timeline.append(f"  回  {clip(item.get('content'), 120)}")

        # ④ 收尾
        elif kind == "result":
            final = clip(event.get("result") or subtype, 400)
            timeline.append(f"  完  {subtype or 'result'}：{final}")

        else:
            unknown += 1
            raw_line = clip(json.dumps(event, ensure_ascii=False), 160)
            timeline.append(f"  ?  {kind or '未知'} {raw_line}")

    summary = {
        "events": len([ln for ln in lines if ln.strip()]),
        "texts": texts,
        "tools": dict(tools),
        "tool_calls": sum(tools.values()),
        "files": files[:MAX_FILE],
        "files_total": len(files),
        "models": models[:3],
        "tool_errors": errors,
        "unknown_events": unknown,
        "final": final,
    }
    return timeline, summary


# ================================================================ 产物定位：gates/diag/wb-*


def diag_dir(root: Path) -> Path:
    """`<root>/gates/diag` —— 派活日志、判决、心跳都落在这里。"""
    return root / "gates" / "diag"


def card_artifacts(diag: Path, card: str, suffix: str) -> list[Path]:
    """这一张卡自己的产物文件（精确匹配，按 mtime 升序）—— 口径照抄 `wb_dispatch.card_artifacts`。

    ★ 为什么不能宽 glob：`wb-42*` 会**串卡**（`fnmatch("wb-421.jsonl", "wb-42*.jsonl") == True`，
    卡 029 §2.9 实测挖出的既有 bug）。改成精确匹配：卡号后面**只能是**后缀本身或 `.r<N>`+后缀。
    """
    if not diag.exists():
        return []
    pat = re.compile(rf"^wb-{re.escape(card)}(\.r\d+)?{re.escape(suffix)}$")
    return sorted((p for p in diag.iterdir() if pat.match(p.name)),
                  key=lambda p: p.stat().st_mtime)


def card_of(log: Path) -> str:
    """从 log 文件名取卡号（`wb-105.jsonl` / `wb-105.r2.jsonl` → `105`）；取不到 → `""`。"""
    hit = re.match(r"^wb-(.+?)(?:\.r\d+)?\.jsonl$", log.name)
    return hit.group(1) if hit else ""


# ================================================================ 三态判据 + 扫全部日志


def classify_job_state(age: float, has_verdict: bool) -> tuple[str, str]:
    """按**证据**给出一态（不猜）：判决文件 / 日志 mtime 距今多久。"""
    if has_verdict:
        return "已判决", "有判决文件"
    if age <= STALL_SECONDS:
        return "在跑", f"无判决，且日志 mtime 距今 {age:.0f}s ≤ {STALL_SECONDS}s"
    return "断了", f"无判决，且日志已静默 {age:.0f}s > {STALL_SECONDS}s"


def scan_jobs(diag: Path, now: float | None = None) -> list[dict]:
    """扫 `gates/diag/wb-*.jsonl`，每条给出 mtime / 大小 / 有无判决 + 一态判断。"""
    if not diag.exists():
        return []
    now = time.time() if now is None else now
    rows: list[dict] = []
    for log in sorted(diag.glob("wb-*.jsonl")):
        try:
            stat = log.stat()
        except OSError:  # pragma: no cover —— 边扫边被删就跳过这一条
            continue
        age = max(0.0, now - stat.st_mtime)
        verdict = log.with_suffix(".verdict.txt")
        report = log.with_suffix(".report.md")
        has_verdict = verdict.exists()
        reason = non_card_reason(log.name)
        if reason:
            state, why = "非派活", reason       # 旁账（用量 / 路由回放）不是派活
        else:
            state, why = classify_job_state(age, has_verdict)
        rows.append({
            "card": card_of(log),
            "log": log.name,
            "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
            "age_seconds": round(age, 1),
            "size_bytes": stat.st_size,
            "has_verdict": has_verdict,
            "verdict": verdict.name if has_verdict else None,
            "has_report": report.exists(),
            "state": state,
            "why": why,
        })
    return rows


# ================================================================ 渲染：`wb_status.py` 的那段输出


def repo_state(git_cwd: Path | None = None) -> list[str]:
    """它对仓库做了什么 —— 只看两条最实在的（工作区状态 + 最新提交）。

    ★ `git_cwd` 是给号池 MCP 用的：`job_status` 原先在 `gates/diag/` 里跑 `wb_status.py`，
    git 的相对路径口径就按那个 cwd 来；不传 = 继承当前进程 cwd（CLI 的默认行为）。
    """
    out: list[str] = []
    for args in (["status", "--short"], ["log", "-1", "--format=%h %s"]):
        try:
            done = subprocess.run(
                ["git", *args], capture_output=True, text=True, encoding="utf-8",
                errors="replace", cwd=str(git_cwd) if git_cwd else None,
            )
            body = (done.stdout or "").strip() or "(空)"
        except OSError as exc:                      # git 不在也不许崩
            body = f"（跑不了 git：{exc}）"
        indented = "\n".join("    " + ln for ln in body.splitlines())
        out.append(f"  git {' '.join(args)}：\n" + indented)
    return out


def render_timeline(path_display: str, timeline: list[str], summary: dict, *,
                    tail: int = 0, repo: bool = False,
                    git_cwd: Path | None = None) -> str:
    """把时间线 + 摘要拼成 `wb_status.py` 的**那段人话**（逐字口径，CLI 与 MCP 共用）。

    ★ 为什么抽成函数：`wb_status.py` 打的就是这段文本，号池 MCP 的 `job_status` 也承诺给
    同一段（措辞逐字不变）—— 只有一处打印才不会有第二份口径。
    """
    shown = timeline[-tail:] if tail and tail > 0 else timeline
    only = f"，只显示最后 {tail} 条" if tail and tail > 0 else ""
    lines: list[str] = [f"=== WorkBuddy 状态器：{path_display}"
                        f"（事件 {summary['events']} 条{only}）==="]
    lines += shown
    lines.append("--- 摘要 ---")
    model_line = ", ".join(summary["models"]) or "（没见到 init 事件）"
    lines.append(f"  模型：{model_line}")
    tools_line = "、".join(f"{k}×{v}" for k, v in sorted(summary["tools"].items()))
    lines.append(f"  工具调用 {summary['tool_calls']} 次：{tools_line or '（一次都没调）'}")
    lines.append(f"  助手发言 {summary['texts']} 次；工具报错 {summary['tool_errors']} 次")
    lines.append(f"  认不出的行 {summary['unknown_events']} 条")
    if summary["files"]:
        shown_files = len(summary["files"])
        more = f"（共 {summary['files_total']} 个）" if summary["files_total"] > shown_files else ""
        lines.append(f"  碰过的文件{more}：" + "、".join(summary["files"]))
    lines.append(f"  最后一条结果：{summary['final'] or '（还没见到 result —— 可能还在跑）'}")
    if repo:
        lines += repo_state(git_cwd)
    return "\n".join(lines) + "\n"


def render_json(path_display: str, summary: dict) -> str:
    """`wb_status.py --json` 的那段机器可读摘要（`log` + 摘要字段）。"""
    return json.dumps({"log": path_display, **summary}, ensure_ascii=False, indent=2)
