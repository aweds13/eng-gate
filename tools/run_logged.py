"""长命令跑法：边跑边落日志、边报心跳。

为什么有这个工具：后台跑长命令时如果写成 `python x.py | tail -3`，
管道会把所有输出攒到进程结束才吐一次，中途看作业输出永远是空的，
看起来像「卡死」。本工具把子进程输出逐行写进日志文件，并且每隔
`--every` 秒在**自己的 stdout** 打一行心跳（含最后一行输出），
所以后台作业的输出是**增量可读**的。

用法：
    python -X utf8 tools/run_logged.py --log gates/diag/land-A302.log -- \
        python -X utf8 tools/wb_land.py --card A302 ...

退出码 = 子进程退出码（原样透传，不吞）。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time
from pathlib import Path

TAIL_LINES = 6


def _reader(stream, log_path: Path, state: dict) -> None:
    """把子进程输出逐行落盘，并把最后一行留在 state 里给心跳用。"""
    with log_path.open("a", encoding="utf-8", errors="replace") as fh:
        for line in stream:
            fh.write(line)
            fh.flush()
            text = line.rstrip("\n")
            if text:
                state["last"] = text
        state["eof"] = True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="跑长命令：日志逐行落盘 + 定时心跳")
    parser.add_argument("--log", required=True, help="日志文件路径（追加写）")
    parser.add_argument("--every", type=float, default=15.0, help="心跳间隔秒数，默认 15")
    parser.add_argument("--tail", type=int, default=TAIL_LINES, help="结束时回放最后几行，默认 6")
    parser.add_argument("cmd", nargs=argparse.REMAINDER, help="`--` 之后是要跑的命令")
    args = parser.parse_args(argv)

    cmd = [part for part in args.cmd if part != "--"]
    if not cmd:
        print("[用法] 缺命令：python tools/run_logged.py --log <文件> -- <命令...>", flush=True)
        return 2

    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    state: dict = {"last": "", "eof": False}

    with log_path.open("a", encoding="utf-8", errors="replace") as head:
        head.write(f"\n=== {time.strftime('%Y-%m-%dT%H:%M:%S')} 起跑：{' '.join(cmd)} ===\n")
        head.flush()

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert proc.stdout is not None
    reader = threading.Thread(target=_reader, args=(proc.stdout, log_path, state), daemon=True)
    reader.start()

    print(f"[跑] {log_path} | 心跳 {args.every:g}s | pid={proc.pid}", flush=True)
    while proc.poll() is None:
        time.sleep(args.every)
        elapsed = int(time.time() - started)
        last = state.get("last", "")
        print(f"[心跳] {elapsed}s | {last[:120]}", flush=True)

    reader.join(timeout=5)
    code = proc.returncode or 0
    elapsed = int(time.time() - started)
    print(f"[完] 退出码={code} 用时={elapsed}s 日志={log_path}", flush=True)
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[-args.tail :]:
        print(f"  {line}", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
