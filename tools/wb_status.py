r"""WorkBuddy / CodeBuddy CLI 状态器：把 stream-json 事件读成人看的时间线。

为什么有这个工具（2026-09-26，T-G81）：外包模式下**工人 agent 在别的进程里干活**
（`D:\workbuddy\...\cli\bin\codebuddy`），主控与用户都看不见它做了什么 —— 只能事后读它
留下的 log。这个脚本就是那扇窗：把原始 JSONL 事件渲染成

    时间 | 它在说什么 / 它调了哪个工具、动了哪个文件 | 结果

**边界（如实写）**：
  · 它只**读** log，不跑 CLI、不改任何东西（派活是 `tools/workbuddy.ps1` 或主控的直接调用）；
  · 事件形状按 CodeBuddy/Claude-Code 那一族写（`system` / `assistant` / `user` / `result`），
    认得出来的都渲染；**认不出来的一行也不丢**（原样截断打印）—— 所以它不会因为对方升级而
    静默什么都不说；
  · ★ 第一次真派活之后，要用**真 log** 把形状钉成测试（现在只有合成用例，见
    `tests/test_wb_status.py`）。

用法：
    python -X utf8 tools/wb_status.py <log.jsonl> [--tail N] [--repo] [--json]
    # --tail N  只看最后 N 条事件（跑长任务时看进度用）
    # --repo    末尾附一段 `git status --short` + `git log -1`（"它对仓库做了什么"）
    # --json    机器可读的摘要（给主控解析用）
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

MAX_TEXT = 240          # 一句话最多显示多少字（长输出不许刷屏）
MAX_FILE = 12           # 摘要里最多列几个文件


def _clip(text: object, limit: int = MAX_TEXT) -> str:
    """压成一行、按字数截断 —— 日志里的东西可能是几万字的文件内容。"""
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _tool_line(name: str, payload: dict) -> str:
    """把一次工具调用压成一行 —— 优先显示"它动了哪儿"（路径/命令/查询）。"""
    if not isinstance(payload, dict):
        return f"{name} {_clip(payload, 120)}"
    keys = (
        "file_path", "command", "pattern", "path", "notebook_path",
        "url", "query", "description", "prompt", "old_string",
    )
    for key in keys:
        if key in payload and payload[key]:
            return f"{name}({key}={_clip(payload[key], 160)})"
    if payload:
        return f"{name}({_clip(json.dumps(payload, ensure_ascii=False), 160)})"
    return f"{name}()"


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
            timeline.append(f"  ?  非 JSON 行：{_clip(raw, 160)}")
            continue
        if not isinstance(event, dict):
            unknown += 1
            timeline.append(f"  ?  非对象事件：{_clip(raw, 160)}")
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
                                + _clip(", ".join(str(t) for t in tools_now), 300))
            else:
                timeline.append(f"  开  init  model={model}")

        # ② 助手说话 / 调工具
        elif kind == "assistant":
            content = (event.get("message") or {}).get("content")
            if isinstance(content, str):
                texts += 1
                timeline.append(f"  说  {_clip(content)}")
                continue
            for item in content or []:
                if not isinstance(item, dict):
                    timeline.append(f"  说  {_clip(item)}")
                    continue
                if item.get("type") == "text" and item.get("text"):
                    texts += 1
                    timeline.append(f"  说  {_clip(item['text'])}")
                elif item.get("type") == "tool_use":
                    name = str(item.get("name") or "?")
                    tools[name] += 1
                    payload = item.get("input") or {}
                    if isinstance(payload, dict):
                        for key in ("file_path", "path", "notebook_path"):
                            got = payload.get(key)
                            if got and str(got) not in files:
                                files.append(str(got))
                    timeline.append(f"  做  {_tool_line(name, payload)}")

        # ③ 工具回话（成功/失败）
        elif kind == "user":
            content = (event.get("message") or {}).get("content")
            items = content if isinstance(content, list) else []
            for item in items:
                if not isinstance(item, dict) or item.get("type") != "tool_result":
                    continue
                if item.get("is_error"):
                    errors += 1
                    timeline.append(f"  错  {_clip(item.get('content'), 200)}")
                else:
                    timeline.append(f"  回  {_clip(item.get('content'), 120)}")

        # ④ 收尾
        elif kind == "result":
            final = _clip(event.get("result") or subtype, 400)
            timeline.append(f"  完  {subtype or 'result'}：{final}")

        else:
            unknown += 1
            raw_line = _clip(json.dumps(event, ensure_ascii=False), 160)
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


def repo_state() -> list[str]:
    """它对仓库做了什么 —— 只看两条最实在的（工作区状态 + 最新提交）。"""
    out: list[str] = []
    for args in (["status", "--short"], ["log", "-1", "--format=%h %s"]):
        try:
            done = subprocess.run(
                ["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            body = (done.stdout or "").strip() or "(空)"
        except OSError as exc:                      # git 不在也不许崩
            body = f"（跑不了 git：{exc}）"
        indented = "\n".join("    " + ln for ln in body.splitlines())
        out.append(f"  git {' '.join(args)}：\n" + indented)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="WorkBuddy/CodeBuddy stream-json 状态器")
    parser.add_argument("log", help="stream-json 输出文件（.jsonl）")
    parser.add_argument("--tail", type=int, default=0, help="只看最后 N 条事件")
    parser.add_argument("--repo", action="store_true", help="末尾附 git 状态与最新提交")
    parser.add_argument("--json", action="store_true", help="只打印机器可读摘要")
    args = parser.parse_args()

    path = Path(args.log)
    if not path.exists():
        print(f"[FAIL] 找不到 log：{path}", file=sys.stderr)
        return 2
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    timeline, summary = parse_events(lines)

    if args.json:
        print(json.dumps({"log": str(path), **summary}, ensure_ascii=False, indent=2))
        return 0

    shown = timeline[-args.tail:] if args.tail and args.tail > 0 else timeline
    only = f"，只显示最后 {args.tail} 条" if args.tail and args.tail > 0 else ""
    print(f"=== WorkBuddy 状态器：{path}（事件 {summary['events']} 条{only}）===")
    for line in shown:
        print(line)
    print("--- 摘要 ---")
    model_line = ", ".join(summary["models"]) or "（没见到 init 事件）"
    print(f"  模型：{model_line}")
    tools_line = "、".join(f"{k}×{v}" for k, v in sorted(summary["tools"].items()))
    print(f"  工具调用 {summary['tool_calls']} 次：{tools_line or '（一次都没调）'}")
    print(f"  助手发言 {summary['texts']} 次；工具报错 {summary['tool_errors']} 次")
    print(f"  认不出的行 {summary['unknown_events']} 条")
    if summary["files"]:
        shown_files = len(summary["files"])
        more = f"（共 {summary['files_total']} 个）" if summary["files_total"] > shown_files else ""
        print(f"  碰过的文件{more}：" + "、".join(summary["files"]))
    print(f"  最后一条结果：{summary['final'] or '（还没见到 result —— 可能还在跑）'}")
    if args.repo:
        for block in repo_state():
            print(block)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
