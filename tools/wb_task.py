r"""任务栅栏 CLI `tools/wb_task.py`（卡 119 · T-G217）—— 只标准库。

为什么有它：任务栅栏（注册一个跨层的任务 → 每张卡交成送申请 → 集齐才收口）原先住在
`gates/diag/tf_batch.py` —— 那是 **gitignore 的 scratch**，别的窗口 / 别的机器拿不到
（「只有主控一个人能用」的根因）。卡 119 把它搬进 git：**权威副本**＝ `tools/pool/task.py`
（模块 `pool.task`）。本文件是**命令行壳**，与 `tools/wb_plan.py` / `tools/wb_status.py` 同款，
只做「取参数 / 打印 → 转发给逻辑层」这一件事。

子命令（实现全在 `pool.task`，本壳**原样转发**，名字一个不少）：
    register / claim / deposit / waive / extend / expire / advance / landed / status / list / pool
    --selftest   反例钉子（33 条），转发到 `pool.task.selftest`

用法：
    python -X utf8 tools/wb_task.py register <预声明.toml>
    python -X utf8 tools/wb_task.py claim <任务> <卡> --evidence "pytest 3 passed" --files a.py
    python -X utf8 tools/wb_task.py status <任务>
    python -X utf8 tools/wb_task.py --selftest

★ 旧的 `gates/diag/tf_batch.py` 保留成临时转发壳（打印一行后转发到本文件），免得旧调用点断掉。
"""

from __future__ import annotations

import sys

from pool import task as _task

__all__ = ["main", "selftest"]


def selftest() -> int:
    """反例钉子（33 条）—— 原样转发到 `pool.task.selftest`。"""
    return _task.selftest()


def main(argv: list[str] | None = None) -> int:
    """把 argv 交给 `pool.task.main`；`--selftest` 先截住转发到 `selftest()`。

    ★ `--selftest` 要在交给 argparse 前截住：子命令是 required，直接交给它只会先报「缺子命令」。
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        return selftest()
    return _task.main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
