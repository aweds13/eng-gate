r"""号池写面地基①：作业登记 CLI `tools/wb_registry.py`（卡 108 · T-G205）—— 只标准库。

**防什么**：写面（派活 / 取消）动手前得先问「谁占了哪棵树 / 哪个冲突域」。本 CLI 就三个动作，
**只做登记与干跑**，不派活、不碰 MCP（写面工具是卡 110）：

    python -X utf8 tools/wb_registry.py list [--json]                    列活租约（空就说"空着"）
    python -X utf8 tools/wb_registry.py check --card 108 [--tree T] [--files A B …]
    python -X utf8 tools/wb_registry.py reserve --card 108 [--tree T] [--files A B …] \
        [--project P] [--model M] [--log L] [--ttl 21600]
    python -X utf8 tools/wb_registry.py release --card 108

- `check` = **只跑守卫、不登记**（写面的"干跑"）。
- `--files` 不给 → 按卡号从 `docs/workbacklog.toml` 查（`pool.plan.load_backlog`）；
  ★ **查不到就拒**（"没有冲突域 ⇒ 不许派活"）—— **别猜成空域**（空域会绕过域守卫）。
- `--tree` 不给 = 主树（`""`）。

**退出码**：`0` = 没问题 / `1` = 有守卫咬（**逐条点名**）/ `2` = 用法或环境错。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import TYPE_CHECKING

from pool import guards, registry
from pool.plan import BacklogError, load_backlog

if TYPE_CHECKING:
    from collections.abc import Sequence


class UsageError(Exception):
    """用法 / 数据不对 —— 退 2（与"守卫咬"的退 1 分开）。"""


# ---------------------------------------------------------------- 取冲突域


def files_from_backlog(card: str) -> list[str]:
    """按卡号从 backlog 查冲突域；**查不到就拒** —— 不猜成空域（空域会绕过域守卫）。"""
    try:
        backlog = load_backlog()
    except BacklogError as exc:
        raise UsageError(f"读不了 backlog：{exc}") from exc
    hit = backlog.by_id().get(str(card))
    if hit is None:
        raise UsageError(
            f"backlog 里没有卡 {card} ⇒ 没有冲突域 ⇒ 不许派活"
            f"（要用就显式 --files 给域）")
    return list(hit.files)


def _files_or_backlog(card: str, files: list[str] | None) -> list[str]:
    return list(files) if files else files_from_backlog(card)


# ---------------------------------------------------------------- 渲染


def _render_human(rows: list[dict]) -> str:
    if not rows:
        return "[池 ] 空着（没有任何活租约）\n"
    lines = [f"[池 ] {len(rows)} 条活租约："]
    for row in rows:
        lines.append(
            f"  · 卡 {row.get('card')}（{row.get('task') or '—'}）｜树 "
            f"{row.get('tree') or '（主树）'}｜项目 {row.get('project') or '（未定）'}"
            f"｜owner {row.get('owner')}")
        lines.append(
            f"      域：{'、'.join(row.get('files') or []) or '（空）'}"
            f"｜起于 {row.get('at')}｜TTL {row.get('ttl_seconds')}s")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 子命令


def cmd_list(*, as_json: bool, now: float | None = None) -> int:
    stamp = time.time() if now is None else now
    try:
        rows = registry.list_reservations(stamp)
    except registry.RegistryError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(_render_human(rows))
    return 0


def _repo_root() -> object:
    """门禁锁的 `cwd` 按主树根归一（算不出 → `None`，`lock_guard` 退化成后缀匹配）。"""
    try:
        return registry.main_tree_root()
    except registry.RegistryError:
        return None


def _guard_problems(card: str, tree: str, files: list[str], now: float) -> list[str]:
    live = registry.list_reservations(now)
    body = registry.read_lock_body()
    return [
        *guards.tree_guard(tree, live, now),
        *guards.domain_guard(files, live, now),
        *guards.lock_guard(card, tree, body, root=_repo_root()),
    ]


def cmd_check(card: str, tree: str, files: list[str] | None, now: float | None = None) -> int:
    """只跑守卫、**不登记**（写面的"干跑"）。"""
    stamp = time.time() if now is None else now
    try:
        domain = _files_or_backlog(card, files)
        problems = _guard_problems(card, tree, domain, stamp)
    except registry.RegistryError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2
    except UsageError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2
    if problems:
        print("[咬 ] 守卫拦下：", file=sys.stderr)
        for item in problems:
            print(f"  · {item}", file=sys.stderr)
        return 1
    print(f"[OK ] 守卫全过：卡 {card} 可占树 {tree or '（主树）'}｜域 {'、'.join(domain)}")
    return 0


def cmd_reserve(card: str, tree: str, files: list[str] | None, *,
                project: str = "", model: str = "", log: str = "",
                ttl: int = registry.DEFAULT_TTL, now: float | None = None) -> int:
    stamp = time.time() if now is None else now
    try:
        domain = _files_or_backlog(card, files)
        entry = registry.reserve(card, tree=tree, files=domain, project=project,
                                 model=model, log=log, ttl_seconds=ttl, now=stamp)
    except registry.GuardError as exc:
        print("[咬 ] 守卫拦下，未登记：", file=sys.stderr)
        for item in exc.problems:
            print(f"  · {item}", file=sys.stderr)
        return 1
    except (registry.RegistryError, UsageError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2
    print(f"[登 ] 已登记：卡 {entry['card']}（{entry['task'] or '—'}）占树 "
          f"{entry['tree'] or '（主树）'}｜项目 {entry['project'] or '（未定）'}"
          f"｜owner {entry['owner']}")
    print(f"      域：{'、'.join(entry['files']) or '（空）'}｜at {entry['at']}"
          f"｜TTL {int(entry['ttl_seconds'])}s｜登记文件 {registry.registry_path()}")
    return 0


def cmd_release(card: str) -> int:
    try:
        done = registry.release(card)
    except registry.RegistryError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2
    if done:
        print(f"[放 ] 已放掉卡 {card} 的租约")
        return 0
    print(f"[放 ] 没有卡 {card} 的租约（没动任何东西）")
    return 0


# ---------------------------------------------------------------- 参数


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="号池写面地基①：作业登记（谁占了哪棵树 / 哪个冲突域）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="列活租约")
    p_list.add_argument("--json", action="store_true", help="给机器看")

    p_check = sub.add_parser("check", help="只跑守卫、不登记（干跑）")
    p_check.add_argument("--card", required=True, help="卡号")
    p_check.add_argument("--tree", default="", help="树（相对主树根；默认 '' = 主树）")
    p_check.add_argument("--files", nargs="+", default=None,
                         help="冲突域；不给就按卡号从 backlog 查")

    p_res = sub.add_parser("reserve", help="登记一条租约")
    p_res.add_argument("--card", required=True, help="卡号")
    p_res.add_argument("--tree", default="", help="树（相对主树根；默认 '' = 主树）")
    p_res.add_argument("--files", nargs="+", default=None,
                       help="冲突域；不给就按卡号从 backlog 查")
    p_res.add_argument("--project", default="",
                       help="项目名（卡 120）；不给就按树从项目索引反查")
    p_res.add_argument("--model", default="", help="模型")
    p_res.add_argument("--log", default="", help="作业日志（相对路径）")
    p_res.add_argument("--ttl", type=int, default=registry.DEFAULT_TTL,
                       help=f"租约秒数（默认 {registry.DEFAULT_TTL}）")

    p_rel = sub.add_parser("release", help="放掉这张卡的租约")
    p_rel.add_argument("--card", required=True, help="卡号")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "list":
        return cmd_list(as_json=args.json)
    if args.command == "check":
        return cmd_check(args.card, args.tree, args.files)
    if args.command == "reserve":
        return cmd_reserve(args.card, args.tree, args.files,
                           project=args.project, model=args.model, log=args.log, ttl=args.ttl)
    return cmd_release(args.card)


if __name__ == "__main__":
    raise SystemExit(main())
