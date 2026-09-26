r"""WorkBuddy 日志失败定位器 —— "少读"的第二件：把 1 MB 的 log 压成"错在哪"（T-G108）。

工人跑完留下的 log 是 **100 KB ~ 1.2 MB** 的 stream-json（真 log 实测 `wb-007.jsonl`
= **435 行 / 1133 KB**），而主控真正要的只有几行：**哪条用例红了 / 断言原文 / 项目内的栈帧 /
它最后在干什么**。整份读一次上万 token，纯浪费 —— 这个工具就砍这一笔。

它抓哪五段（每段都可能为空，空就写「（没有）」）：
  1. 红的用例 —— `FAILED <path>::<test>` / `ERROR <path>::<test>`（去重）；
  2. 断言原文 —— `assert …` / `AssertionError` / 其它 `Error:`（每类最多 10 行）；
  3. ★ 项目内栈帧 —— traceback 里指向**本仓库**的 `File "<路径>", line N`；
     **外部库的帧一律丢掉**（那是噪音），路径只留**仓库相对路径**；
  4. 它最后在干什么 —— 最后 3 次工具调用（名字 + 参数前 80 字符）；
  5. 一行汇总 —— 退出码 / 有没有 `result` 事件 / `result.subtype` / log 行数 / 红用例条数。

★ **口径复用**：时间线 / 摘要 / 工具数一律走状态器 `tools/wb_status.py` 的 `parse_events`
（本文件只补它**故意裁掉**的那部分 —— 它把 tool_result 压到 120~200 字，抓 FAILED 行不够用）。
★ **只读**：不跑 CLI、不改任何文件。日志是流式的、可能半截 → 坏行一律容忍，**不许炸**。

用法：
    python -X utf8 tools/wb_diag.py gates/diag/wb-007.jsonl          # 默认：只印"错在哪"五段
    python -X utf8 tools/wb_diag.py gates/diag/wb-007.jsonl --full    # 想看全时再给全文时间线
    （附加：--exit-code N 把派活器知道的进程退出码补进来 —— 日志里没有这一项）
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 事件解析复用状态器（口径不写第二份，见文件头）。
sys.path.insert(0, str(ROOT / "tools"))
import wb_status  # noqa: E402

MAX_LINES = 10      # 断言原文每类最多几行
LAST_CALLS = 3      # "它最后在干什么"显示几次工具调用
CALL_CLIP = 80      # 工具调用参数显示多少字符
LINE_CLIP = 240     # 每行原文最多多少字符

_FAILED_RE = re.compile(r"(?:^|\s)(FAILED|ERROR)\s+([\w./\\-]*\.py::\S+)", re.M)
_ASSERT_RE = re.compile(r"^\s*(?:E\s+)?assert\b")
_ERROR_RE = re.compile(r"^\s*(?:E\s+)?(?:[A-Za-z_][\w.]*)?Error:")
_GREP_PREFIX_RE = re.compile(r"^\s*\d+→")   # 工人 grep 输出会把行号前缀成 `NN→`
_FRAME_RE = re.compile(r'File "([^"]+)", line (\d+)')
_CALL_RE = re.compile(r"\s+做\s+(.*)$")


def repo_root() -> Path:
    """本仓库的根 —— 在 worktree 里跑时也要认得出**主树里**的帧（那才是真 log 的来源）。

    `git rev-parse --git-common-dir` 指向共享的 `.git`（worktree 里不是 `<树>/.git`），
    它的父目录就是主仓库根。git 不可用 / 不在这仓库里 → 退回本工具所在的树（保守）。
    """
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except OSError:
        return ROOT
    common = (done.stdout or "").strip()
    if done.returncode != 0 or not common:
        return ROOT
    path = Path(common)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve().parent


def iter_events(lines: list[str]) -> list[dict]:
    """容忍坏行的事件遍历（半截 JSONL / 非 JSON / 非对象一律跳过）。"""
    events: list[dict] = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def tool_result_texts(events: list[dict]) -> list[str]:
    """所有 `tool_result` 的**原文**（`parse_events` 会把它裁到 120~200 字，这里要全文）。"""
    texts: list[str] = []
    for event in events:
        if str(event.get("type")) != "user":
            continue
        content = (event.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if not (isinstance(item, dict) and item.get("type") == "tool_result"):
                continue
            body = item.get("content")
            if isinstance(body, str):
                texts.append(body)
            elif isinstance(body, list):      # 有的客户端把结果拆成 content block
                for block in body:
                    if isinstance(block, dict) and block.get("type") == "text":
                        texts.append(str(block.get("text") or ""))
    return texts


def find_failed_tests(texts: list[str]) -> list[str]:
    """抓 `FAILED <path>::<test>` / `ERROR <path>::<test>` 行，按出现顺序去重。

    只认**像路径**的（`.py` 结尾），免得把日志里 "FAILED ...::x" 这种省略写法也算进来。
    """
    seen: set[str] = set()
    out: list[str] = []
    for text in texts:
        for kind, target in _FAILED_RE.findall(text):
            item = f"{kind} {target}"
            if item not in seen:
                seen.add(item)
                out.append(item)
    return out


def find_assertion_lines(texts: list[str]) -> dict[str, list[str]]:
    """三类断言原文：`assert …` / `AssertionError` / 其它 `Error:`（每类最多 10 行）。

    ★ `Error:` 只认**行首**的异常名（可选 pytest 的 `E ` / grep 的 `NN→` 前缀）——
    工具回话里常夹着工人 grep 出来的**源码**（`except json.JSONDecodeError:` 之类），
    字面上也符合 "Error: "，不挡住的话 10 行额度会被噪音占满，真正那行反而被挤掉。
    """
    buckets: dict[str, list[str]] = {"assert": [], "AssertionError": [], "Error:": []}
    for text in texts:
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            probe = _GREP_PREFIX_RE.sub("", line)   # 剥掉 grep 的行号前缀再判
            if _ASSERT_RE.match(probe):
                key = "assert"
            elif "AssertionError" in probe:
                key = "AssertionError"
            elif _ERROR_RE.match(probe):
                key = "Error:"
            else:
                continue
            if len(buckets[key]) < MAX_LINES:
                buckets[key].append(wb_status._clip(stripped, LINE_CLIP))
    return buckets


def find_project_frames(texts: list[str], root: Path | None = None) -> list[str]:
    """★ traceback 里的**项目内**栈帧（`文件:行号`，仓库相对路径）；外部库的帧丢掉。"""
    base = (root or repo_root()).resolve()
    seen: set[str] = set()
    out: list[str] = []
    for text in texts:
        for raw_path, lineno in _FRAME_RE.findall(text):
            if "<" in raw_path:               # <string> / <frozen …> 不是文件
                continue
            try:
                rel = Path(raw_path).resolve().relative_to(base)
            except (ValueError, OSError):
                continue                      # 仓库外（stdlib / site-packages）一律丢
            item = f"{rel.as_posix()}:{lineno}"
            if item not in seen:
                seen.add(item)
                out.append(item)
    return out


def last_tool_calls(timeline: list[str], n: int = LAST_CALLS) -> list[str]:
    """最后 n 次工具调用（从状态器的时间线里取，名字 + 参数前 80 字符）。"""
    calls = [wb_status._clip(m.group(1), CALL_CLIP)
             for line in timeline if (m := _CALL_RE.match(line))]
    return calls[-n:]


def diagnose(lines: list[str], root: Path | None = None) -> dict:
    """一次算清五段 + 汇总（全部只读）。"""
    timeline, summary = wb_status.parse_events(lines)
    events = iter_events(lines)
    texts = tool_result_texts(events)
    result: dict | None = None
    for event in events:
        if str(event.get("type")) == "result":
            result = event
    failed = find_failed_tests(texts)
    return {
        "log_lines": len([ln for ln in lines if ln.strip()]),
        "events": summary["events"],
        "tool_calls": summary["tool_calls"],
        "has_result": result is not None,
        "subtype": str(result.get("subtype") or "") if result else "",
        "is_error": bool(result.get("is_error")) if result else False,
        "final": summary["final"],
        "failed": failed,
        "asserts": find_assertion_lines(texts),
        "frames": find_project_frames(texts, root),
        "calls": last_tool_calls(timeline),
        "timeline": timeline,
        "exit_code": None,
    }


def _assert_rows(buckets: dict[str, list[str]]) -> list[str]:
    rows: list[str] = []
    for key in ("assert", "AssertionError", "Error:"):
        for line in buckets.get(key, []):
            # 行里已经带了这个标签就别再加一层（读自己的 log 时会递归，别显示成 `[X] [X] …`）
            rows.append(line if line.startswith(f"[{key}]") else f"[{key}] {line}")
    return rows


def _section(title: str, rows: list[str]) -> str:
    body = "\n".join(f"  {row}" for row in rows) if rows else "  （没有）"
    return f"【{title}】\n{body}"


def render(diag: dict, full: bool = False) -> str:
    """把诊断结果印成人能读的五段（空段写「（没有）」）。"""
    exit_code = diag.get("exit_code")
    shown_code = exit_code if exit_code is not None else "未提供（用 --exit-code 传）"
    parts = [
        f"=== 失败定位器：{diag.get('log', '')} ===",
        _section("1 红的用例", diag["failed"]),
        _section("2 断言原文（每类最多 10 行）", _assert_rows(diag["asserts"])),
        _section("3 项目内栈帧（外部库已丢）", diag["frames"]),
        _section("4 它最后在干什么（最后 3 次工具调用）", diag["calls"]),
        _section("5 一行汇总", [
            f"退出码={shown_code}；"
            f"有 result 事件={'有' if diag['has_result'] else '没有'}；"
            f"result.subtype={diag['subtype'] or '（无）'}；"
            f"log 行数={diag['log_lines']}；红用例={len(diag['failed'])} 条"
        ]),
    ]
    if full:
        parts.append("【全文时间线（wb_status.parse_events）】")
        parts.append("\n".join(diag["timeline"]) or "  （没有）")
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WorkBuddy 日志失败定位器（只读）")
    parser.add_argument("log", help="stream-json 输出文件（.jsonl）")
    parser.add_argument("--full", action="store_true", help="还要打印全文时间线")
    parser.add_argument("--exit-code", type=int, default=None,
                        help="派活器知道的进程退出码（日志里没有这一项）")
    args = parser.parse_args(argv)

    path = Path(args.log)
    if not path.exists():
        print(f"[FAIL] 找不到 log：{path}", file=sys.stderr)
        return 2
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    diag = diagnose(lines)
    diag["log"] = str(path)
    diag["exit_code"] = args.exit_code
    print(render(diag, full=args.full))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
