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

★ 逻辑层已抽到 `tools/pool/jobs.py`（卡 106 · T-G202）：`parse_events` / 渲染 / 三态判据
  与号池 MCP 的 `job_list` / `job_status` **共用同一批函数**。本文件只留**取参数 / 打印**。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pool.jobs import clip as _clip
from pool.jobs import parse_events, render_json, render_timeline
from pool.jobs import tool_line as _tool_line

#: 逻辑层在 `pool.jobs`；这里原样转发 `parse_events`（wb_dash 用）与 `_clip` / `_tool_line`
#: （wb_dispatch 用）。
__all__ = ["main", "parse_events", "_clip", "_tool_line"]


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
        print(render_json(str(path), summary))
        return 0

    sys.stdout.write(render_timeline(str(path), timeline, summary,
                                     tail=args.tail, repo=args.repo))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
