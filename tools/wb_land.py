r"""主控的通用集成器 CLI `tools/wb_land.py`（卡 139 · `T-G237`）—— 只标准库。

为什么有它：本仓记的**最大缺口**（`复盘/外包工具-需求与架构.md` §5 第 1 条 / 外部审查 §四）
就是「**收口工具还在 scratch**」—— `gates/diag/_integrate.py` 是 **gitignore 的 scratch**，
别的窗口 / 别的机器拿得到队列、**拿不到把一笔卡收成提交的那条链**（错配③：权威与工具位置错配）。
卡 139 把它搬进 git：**权威副本**＝ `tools/pool/landing.py`（模块 `pool.landing`）。
本文件是**命令行壳**，与 `tools/wb_task.py` / `tools/wb_stage_card.py` 同款，
只做「取参数 → 转发给逻辑层」这一件事。

八步链（顺序固定，任一步失败就停，绝不带着红门禁提交）：
    ⓪ 回退派生物（卡 150：幂等重跑；`--no-reset` 可关，`--commit-only` 不回退）
    ① 卡树迁到主树 HEAD  ② 文档件  ③ sync_counts  ④ 门禁锁 + 门禁  ⑤ seal
    ⑥ 白名单 → add → commit  ⑦ audit → release → ff 合流
    ⑧ 复核落盘（卡 184 · 追加三）：wb_review.py --rev <新提交> --json → gates/review/<task>.json

用法：
    python -X utf8 tools/wb_land.py --card 139 --tree .wt/landing --task T-G237 \
        --title "…" --group ENGINEERING --evidence a.py b.py --allow a.py b.py \
        --port-base 9034

★ `--card` 与 `--batch` **必须恰好给一个**（批号也能当门禁锁的标签）；
  `--no-gate`（只在文档件/白名单上试跑）与 `--commit-only`（门禁已绿、封存没变）两个模式
  会在 trailer 里**如实写**「这一笔没跑门禁」/「复用已绿的那一趟」—— 不许借这行冒充跑过。
★ 卡 184（T-G284）：`--affected <路径…>` / `--changed-from <REV>` —— 增量门禁开关（**默认关**，
  给了才少跑）。三条强制全量照咬：① 碰 scripts/**/tools/**/gates/** ⇒ 全量；② 空计划 ⇒ 全量；
  ③ 今天没跑过全量 ⇒ 全量（每日一次兜底，不按笔数）。增量那一趟 trailer 写「非全量」字样，
  gates/last.json 的 affected 块照写 —— 卡 147 护栏会咬（把增量产物当全量交 ⇒ 红）。
  `--no-review` 跳过 ⑧ 复核落盘（默认会跑）。
★ 旧的 `gates/diag/_integrate.py` 保留成**临时转发壳**（打印一行后转发到本文件）。
"""

from __future__ import annotations

import sys

from pool import landing as _landing

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    """把 argv 交给 `pool.landing.main`（逻辑全在那边，本壳原样转发）。"""
    argv = list(sys.argv[1:] if argv is None else argv)
    return _landing.main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
