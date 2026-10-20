"""命令写法检查器：拦住「管道截断」和「拿 sleep 硬等」这两类偷懒写法。

背景：落地要跑全量门 8–12 分钟，如果写成 `wb_land.py … | tail -3`，管道会把
所有输出攒到进程结束才吐一次，后台作业中途读不到任何输出，看着像卡死；
`sleep 120` 去硬等同样是拿时间换信息，应该用后台作业的完成通知。

用法（长命令跑之前先过一遍）：
    python -X utf8 tools/cmd_guard.py --cmd 'python -X utf8 tools/wb_land.py … | tail -3'

退出码：0 = 写法可以；1 = 拦下（打印该改成什么）。
"""

from __future__ import annotations

import argparse
import re
import sys

# (正则, 说明, 建议)
RULES = [
    (
        re.compile(r"\|\s*(?:tail|head|cut)\b"),
        "管道截断：`| tail/head/cut` 要等前一个进程结束才吐输出，后台作业中途读不到东西",
        "改成落日志：python -X utf8 tools/run_logged.py --log gates/diag/<名>.log -- <原命令>",
    ),
    (
        re.compile(r"\bsleep\s+\d+"),
        "硬等：`sleep N` 拿时间换信息，长任务应该起后台作业等完成通知",
        "用 run_in_background 起作业；要看进度就 tail 日志或读 job_output",
    ),
    (
        re.compile(r"\bwb_land\.py\b(?![^|]*run_logged)[^\n]*\bsleep\b"),
        "落地里混 sleep 轮询",
        "落地直接用 run_logged.py 套起来跑",
    ),
]


def check(cmd: str) -> list[str]:
    """返回命中的问题说明（空列表 = 写法可以）。"""
    hits: list[str] = []
    for pattern, why, fix in RULES:
        if pattern.search(cmd or ""):
            hits.append(f"{why}\n  ⇒ {fix}")
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="拦住管道截断与 sleep 硬等")
    parser.add_argument("--cmd", required=True, help="要检查的命令原文")
    args = parser.parse_args(argv)

    hits = check(args.cmd)
    if not hits:
        print("[OK ] 写法可以：长命令请配 tools/run_logged.py + 后台作业")
        return 0
    print("[拦 ] 这条命令写法被禁止：")
    for hit in hits:
        print(f"  - {hit}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
