r"""租约命令行（卡 195 · T-G295）—— 把"码道池"那条派活路也接进**同一本租约账**。

**防什么**：派活有两个入口，只有**一个**会写租约 ——
- `tools/wb_dispatch.py`（CodeBuddy）✅ 写（经 `pool.registry.reserve`，落到
  `gates/diag/pool-registry.json`）；
- `infra/pool/dispatch.py`（码道）❌ **不写**。
⇒ 守卫（`pool.guards`）看不见码道那一半，「154 与 166 撞同一个文件」一路上没人拦。
★ 这不是"守卫写错了"，是"**有一半的写者不在它看得见的账上**"。

本 CLI 把码道那条路也接进**同一本账**：`claim` 调 `pool.registry.reserve`、`release` 调
`pool.registry.release` —— 字段名 / 位置 / 格式**逐字与 CodeBuddy 那条路一致**（因为走的是
同一个函数、写同一个文件）。**不许另起一本**（两本账 = 守卫照旧瞎）。

    python -X utf8 tools/pool/lease.py claim --card 195 --tree .wt/a --files a.py b.py
    python -X utf8 tools/pool/lease.py release --card 195

- `--tree` 不给 = 主树（`""`）；`--files` **必需**（空域会绕过域守卫，= 放松判据，不许）。
- 退出码：`0` = 登记成功 / `1` = 守卫咬（逐条点名）/ `2` = 用法或环境错。

★ 边界（如实写）：本 CLI **只做登记与释放**，不派活、不跑门禁、不 import `wb_dispatch`
（那是别的卡的域）。`lock_guard` 用的锁原文由 `registry.read_lock_body()` 现跑一次
`gate_lock.py status`（与 `wb_dispatch` 同一处）。
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import TYPE_CHECKING

# ★ 把 tools/ 挂上 path 以便 import pool 包（本文件在 tools/pool/，上两级 = 仓库根）。
#   与 tools/pool/stage_card.py 同一手法（卡 139）。
_TOOLS_DIR = str(pathlib.Path(__file__).resolve().parent.parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from pool import registry  # noqa: E402 —— 作业登记唯一实现（同一本账）

if TYPE_CHECKING:
    from collections.abc import Sequence


# ---------------------------------------------------------------- 子命令


def cmd_claim(card: str, tree: str, files: list[str]) -> int:
    """登记一张卡的租约 —— 经 `registry.reserve`（与 CodeBuddy 同一本账）。"""
    try:
        entry = registry.reserve(card, tree=tree, files=files,
                                 lock_body=registry.read_lock_body())
    except registry.GuardError as exc:
        print("[咬 ] 守卫拦下，未登记：", file=sys.stderr)
        for item in exc.problems:
            print(f"  · {item}", file=sys.stderr)
        return 1
    except registry.RegistryError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2
    print(f"[登 ] 已登记：卡 {entry['card']} 占树 {entry['tree'] or '（主树）'}"
          f"｜owner {entry['owner']}")
    print(f"      域：{'、'.join(entry['files']) or '（空）'}｜at {entry['at']}"
          f"｜TTL {int(entry['ttl_seconds'])}s｜登记文件 {registry.registry_path()}")
    return 0


def cmd_release(card: str) -> int:
    """放掉这张卡的租约 —— 经 `registry.release`（同一本账）。"""
    try:
        done = registry.release(card)
    except registry.RegistryError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2
    if done:
        print(f"[放 ] 已放掉卡 {card} 的租约")
    else:
        print(f"[放 ] 没有卡 {card} 的租约（没动任何东西）")
    return 0


# ---------------------------------------------------------------- 参数


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="租约命令行：把码道池那条派活路接进同一本租约账（卡 195 · T-G295）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_claim = sub.add_parser("claim", help="登记一张卡的租约（与 CodeBuddy 同一本账）")
    p_claim.add_argument("--card", required=True, help="卡号")
    p_claim.add_argument("--tree", default="", help="树（相对主树根；默认 '' = 主树）")
    p_claim.add_argument("--files", nargs="+", required=True,
                         help="冲突域（要改的文件；至少一个 —— 空域会绕过域守卫）")

    p_rel = sub.add_parser("release", help="放掉这张卡的租约")
    p_rel.add_argument("--card", required=True, help="卡号")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "claim":
        return cmd_claim(args.card, args.tree, args.files)
    return cmd_release(args.card)


if __name__ == "__main__":
    raise SystemExit(main())
