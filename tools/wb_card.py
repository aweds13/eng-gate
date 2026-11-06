r"""立卡（往 `docs/workbacklog.toml` 尾部追加一张卡）与锁状态查看的命令行壳（卡 E81 · T-AG586）。

为什么有它：立卡原先靠 `gates/diag/_add_card.py` —— 硬编码绝对路径、**子串判幂等**（加
`A1` 时 `A11` 已存在就被判成「已在」，卡凭空丢了）、而且住在 gitignore 的 scratch 里
（别的窗口拿不到）。两个会话同时立卡还会静默丢卡（实测 8 进程并发丢 3–4 张）。

这个壳把立卡收敛到 `tools/pool/ledger.py` 的短事务：
「拿锁 → 读字节 → 切块查重 → 尾部追加 → 原子写（带重试）→ 放锁」。
**逻辑全在那边，本文件只解析参数、打印人话** —— 照 `tools/wb_stage_card.py` 的薄壳模式，
不许在这里再写一份判据。

## 三条纪律（写在这里，免得有人绕过去）

1. **立卡只走这条命令**，不要再写一次性脚本往台账里拼字节。
2. **主树禁止 `git reset --hard`** —— 它会抹掉别人未提交的台账条目
   （2026-11-02 20:36 真发作过：另一会话落地失败回滚，把主控刚写进台账的一起扫掉）。
3. 等不到锁就**失败关闭**（退 2）。没有 `--no-lock` 这种口子 —— 别加。

## 例

```bash
python -X utf8 tools/wb_card.py add --id E82 --task T-AG587 \
    --title "…" --tree .wt/E82 --spec "复盘/卡/卡E82-….md" \
    --file tools/pool/x.py --file tools/wb_x.py
python -X utf8 tools/wb_card.py lock-status
```

## 边界（如实写）

锁在 `gates/diag/ledger.lock` ⇒ **跨机器不互斥**（本仓是单机多会话，够用）；
写完提交之后仍可能被人 `git reset --hard` 抹掉 —— 那是 git 语义，属纪律问题。
"""

from __future__ import annotations

import argparse
import sys
import time

from pool import ledger

__all__ = ["main"]

EXIT_OK = 0
EXIT_BAD = 1
EXIT_BUSY = 2


def _build_add(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "add",
        help="在台账尾部追加一张卡（幂等；只加字节，不动已有块）",
        description=(
            "在锁里读台账 → 块级查重 → 尾部追加 → 原子写。"
            "已有同号卡 ⇒ 打「已在」退 0（不重复加）；"
            "台账不是纯 CRLF ⇒ 退 1 且不写盘；等不到锁 ⇒ 退 2。"
        ),
    )
    p.add_argument("--id", required=True, help="卡号（如 E82）")
    p.add_argument("--task", required=True, help="台账号（如 T-AG587）")
    p.add_argument("--title", required=True, help="卡标题")
    p.add_argument("--tree", default="", help="卡树目录（如 .wt/E82；空串表示没有树）")
    p.add_argument("--spec", required=True, help="卡规格路径（如 复盘/卡/卡E82-….md）")
    p.add_argument("--file", action="append", default=[],
                   help="这张卡会碰的文件（可重复；域不会自动推断）")
    p.add_argument("--depends", action="append", default=[],
                   help="依赖的卡号（可重复）")
    p.add_argument("--risk", default="mid", choices=("low", "mid", "high"),
                   help="风险档（默认 mid，与既有块一致）")
    p.add_argument("--status", default="pending",
                   choices=("pending", "running", "done", "failed"),
                   help="初始状态（默认 pending）")
    p.add_argument("--wait", type=float, default=ledger.LOCK_WAIT_S,
                   help=f"等锁秒数（默认 {ledger.LOCK_WAIT_S:.0f}；等不到就失败关闭）")
    p.add_argument("--commit", action="store_true",
                   help="写完顺手只提交台账那一份文件（提交在锁里做）")
    p.add_argument("--root", default=None,
                   help="主仓根（默认按 git 现算；在卡树里跑也指回主树）")


def _cmd_add(args: argparse.Namespace) -> int:
    try:
        result = ledger.add_card(
            args.root, id=args.id, task=args.task, title=args.title,
            tree=args.tree, spec=args.spec, files=args.file,
            depends=args.depends, risk=args.risk, status=args.status,
            wait=args.wait, commit=args.commit,
        )
    except ledger.LedgerBusyError as exc:
        print(f"[忙] {exc}", file=sys.stderr)
        return EXIT_BUSY
    except ledger.LedgerError as exc:
        print(f"[停手] {exc}", file=sys.stderr)
        return EXIT_BAD
    if result == "already":
        print(f"[已在] 卡 {args.id} 本来就在台账里 ⇒ 没动文件")
    else:
        # ★ 卡 E89：台账启用分片后，新卡落 `docs/backlog/<分区>.toml` 而不是总表尾部
        #   —— 打印必须说实话（否则「已追加到台账尾部」会把人引到错的文件）。
        try:
            target = ledger.target_path(args.root, args.id)
            where = target.relative_to(ledger.main_root(args.root)).as_posix()
        except Exception:
            where = "docs/workbacklog.toml"
        print(f"[加卡] 卡 {args.id}（{args.task}）已写进 {where}"
              f"{'，并已提交' if args.commit else ''}")
    return EXIT_OK


def _cmd_lock_status(_args: argparse.Namespace) -> int:
    root = ledger.main_root()
    lock = ledger.lock_path(root)
    print(f"主根：{root}")
    print(f"台账：{ledger.backlog_path(root)}")
    print(f"锁：  {lock}")
    if not lock.is_file():
        print("状态：空着（没有人在写台账）")
        return EXIT_OK
    age = time.time() - lock.stat().st_mtime
    leased = "已过期（可接管）" if age > ledger.LOCK_TTL_S else "租约内"
    print(f"状态：被占着 · {leased} · 已 {age:.1f}s（租约 {ledger.LOCK_TTL_S:.0f}s）")
    print("      ★ 只按 mtime 判租约，不读锁文件内容 —— 这是故意的，见 pool/ledger.py")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="wb_card.py",
        description="台账（docs/workbacklog.toml）的写入口：立卡 + 锁状态。",
        epilog=(
            "边界：锁在 gates/diag/ledger.lock ⇒ 跨机器不互斥（本仓单机多会话够用）；"
            "提交后仍可能被人 git reset --hard 抹掉 —— 主树禁止 git reset --hard。"
        ),
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    _build_add(sub)
    ls = sub.add_parser("lock-status", help="看台账锁现在被占着没有（只读）")
    ls.set_defaults(func=_cmd_lock_status)
    args = ap.parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.cmd == "add":
        return _cmd_add(args)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
