r"""通用文档件生成器 CLI `tools/wb_stage_card.py`（卡 139 · `T-G237`）—— 只标准库。

为什么有它：收口链的**第二半**（给一张卡的提交补 台账条目 + changelog + 交接 CHECKPOINT）
原先住在 `gates/diag/_stage_card.py` —— 那是 **gitignore 的 scratch**，别的窗口 / 别的机器
拿不到（「只有主控一个人能用」的根因）。卡 139 把它搬进 git：**权威副本**＝
`tools/pool/stage_card.py`（模块 `pool.stage_card`）。本文件是**命令行壳**，与
`tools/wb_task.py` / `tools/wb_plan.py` 同款，只做「取参数 → 转发给逻辑层」这一件事。

用法：
    python -X utf8 tools/wb_stage_card.py --tree .wt/<名> --id T-G237 --title "…" \
        --group ENGINEERING --evidence a.py b.py --text-file gates/diag/_text_TG237.md

★ 三段文书模板文件（`gates/diag/_text_<台账号>.md`）**仍在 scratch**（那本来就是临时件）；
  本工具按 `ROOT / "gates" / "diag" / "_text_<号>.md"` 找它 —— 与旧脚本同一个口径。
★ 旧的 `gates/diag/_stage_card.py` 保留成**临时转发壳**（打印一行后转发到本文件）。
"""

from __future__ import annotations

import sys

from pool import stage_card as _stage_card

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    """把 argv 交给 `pool.stage_card.main`（逻辑全在那边，本壳原样转发）。"""
    argv = list(sys.argv[1:] if argv is None else argv)
    return _stage_card.main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
