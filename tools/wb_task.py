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

★ 卡 262（T-G383）·分区前缀：卡号可以是带**分区前缀**的新形态（`A261`），本壳原样透传
  —— 成员号 / 任务号都是不透明字符串，`pool.task` 不做数字假设 ⇒ **登记、成送都通**。
  另加一条**只报不拒**的提醒：一张栅栏的成员若跨了多个分区（如同时有 `A1` 与 `B1`），
  打一句 stderr 提示（多数是笔误或该拆成两张栅栏）—— **不改退出码、不改 stdout**，
  既有行为一字不变（旧号全归 A，永不触发）。
"""

from __future__ import annotations

import sys
from pathlib import Path

from pool import task as _task

__all__ = ["main", "selftest"]


def selftest() -> int:
    """反例钉子（33 条）—— 原样转发到 `pool.task.selftest`。"""
    return _task.selftest()


def _partition_warning(argv: list[str]) -> str:
    """★ 卡 262：`register` 的成员若跨多个分区 ⇒ 一句提醒（**只报不拒**，认不出就返回空串）。

    「分区前缀」是**新卡才用**的命名约定（`A261` / `B1` …）。一张栅栏的成员分属不同分区，
    多数是笔误或该拆成两张栅栏 —— 但这是**命名提醒**，不是拒单理由，所以只打 stderr。
    读不了预声明 / 登记表 / 任何异常 ⇒ 返回空串（**不因这条提醒把登记弄坏**）。
    """
    if not argv or argv[0] != "register":
        return ""
    man_file = next((arg for arg in argv[1:] if not arg.startswith("-")), "")
    if not man_file:
        return ""
    path = Path(man_file)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.is_file():
        return ""
    try:
        import tomllib
        from wb_plan import card_prefix
        man = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 —— 提醒不参与正确性，任何异常都静默跳过
        return ""
    prefixes = {card_prefix(str(m.get("id", ""))) for m in man.get("member") or []}
    prefixes.discard("")
    if len(prefixes) > 1:
        return (f"这张栅栏的成员跨了多个分区：{'、'.join(sorted(prefixes))}"
                "（分区前缀是「新卡才用」的命名约定；多数是笔误或该拆成两张栅栏）")
    return ""


def main(argv: list[str] | None = None) -> int:
    """把 argv 交给 `pool.task.main`；`--selftest` 先截住转发到 `selftest()`。

    ★ `--selftest` 要在交给 argparse 前截住：子命令是 required，直接交给它只会先报「缺子命令」。
    ★ 卡 262：`register` 前打一句**只报不拒**的分区提醒（见 `_partition_warning`）。
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        return selftest()
    warning = _partition_warning(argv)
    if warning:
        print(f"[提醒] {warning}", file=sys.stderr)
    return _task.main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
