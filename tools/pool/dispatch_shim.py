r"""dispatch_shim —— 号池真派活的那一层中间壳（卡 A366 · T-AG588）。

为什么要有它：面板宿主半的禁词表（`tools/dsh_panel.py:133-145`）里有真派活器的名字，
面板源码里一旦出现它，`python -X utf8 tools/dsh_panel.py --check` 立刻判红。所以面板
只调本文件，由这里转发到真派活器。

★ **本壳不复制任何判据**：卡号 / 卡规格 / 冲突域 / 树 / 干跑一律由真派活器自己判。
  本壳只做四件事 ——
  ① 卡号 → 卡规格（**服务端按卡号查**，绝不让客户端传路径）；
  ② 组 argv（写死，不拼字符串、不过 shell）；
  ③ 真跑一次（默认 `--execute --detach`，与面板「派活」的语义一致：起后台就返回）；
  ④ 往 `gates/diag/pool-actions.log` 追加一行痕（宿主半不许写文件，留痕只能在这一层）。

用法：

    python -X utf8 tools/pool/dispatch_shim.py --card D1 [--tree .wt/D1] [--dry-run]

退出码：0 已发起；2 用法 / 台账不对（**没跑真派活器**）；其它 = 真派活器的退出码，原样转发。
"""

from __future__ import annotations

import argparse
import datetime
import os
import pathlib
import re
import subprocess
import sys

# ★ 把 tools/ 挂上 path 以便 import pool 包（本文件在 tools/pool/，上两级 = 仓库根）。
_TOOLS_DIR = str(pathlib.Path(__file__).resolve().parent.parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from pool import plan  # noqa: E402 —— 卡规格查找的唯一实现（backlog 口径）
from pool.no_window import NO_WINDOW  # noqa: E402 —— 子进程不弹窗（卡 159 的真仓扫描）

ROOT = pathlib.Path(__file__).resolve().parents[2]
CARD_RE = re.compile(r"^[A-Za-z]{0,3}-?\d{1,4}$")
TREE_RE = re.compile(r"^\.wt/[A-Za-z0-9_.-]{1,40}$")
LOG_REL = ("gates", "diag", "pool-actions.log")
DISPATCHER = ("tools", "wb_dispatch.py")


def _fail(msg: str) -> int:
    print(f"[FAIL] {msg}", flush=True)
    return 2


def _refuse(card: str, tree: str, msg: str) -> int:
    """拒收同样是「一次点击」——先留痕再拒，面板的留痕才可信。"""
    _audit(card, tree, "FAIL", 2, f"拒收：{msg}")
    return _fail(msg)


def _audit(card: str, tree: str, verdict: str, rc: int, detail: str = "") -> None:
    """追一行痕（`tools/stack.py log_action` 同款字段次序）；写不进只告警，不打断派活。"""
    stamp = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    line = (f"{stamp}  panel  dispatch {card}  {verdict}"
            f"  tree={tree or '(主树)'}  pid={os.getpid()}  rc={rc}  {detail}")
    try:
        path = ROOT.joinpath(*LOG_REL)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(line.rstrip() + "\n")
    except OSError as exc:  # 留痕失败不改变派活结果
        print(f"[WARN] 留痕失败（派活结果不受影响）：{exc}", flush=True)


def _resolve_spec(card: str) -> str:
    """按卡号查卡规格（仓库相对路径）；查不到 / 读不了 ⇒ 空串。"""
    try:
        return plan.find_spec(card)
    except Exception as exc:  # 只读降级：查不到就当没有，后面会明确拒
        print(f"[WARN] 查卡规格失败：{exc}", flush=True)
        return ""


def _spec_file(spec: str) -> pathlib.Path | None:
    """把仓库相对规格解析成本文件的绝对路径；两处 ROOT 都试（主树 / 本树）。"""
    for base in (ROOT, pathlib.Path(getattr(plan, "ROOT", ROOT))):
        cand = base / spec
        if cand.is_file():
            return cand
    return None


def build_command(card: str, spec: str, tree: str) -> list[str]:
    """组真派活器的 argv —— 参数写死，不接收客户端传来的任何其它东西。"""
    cmd = [sys.executable, "-X", "utf8", str(ROOT.joinpath(*DISPATCHER)),
           "--card", card, "--spec", spec, "--execute", "--detach"]
    if tree:
        cmd.extend(["--cwd", str(ROOT / tree)])
    return cmd


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="号池真派活转发（面板唯一合法入口；卡 A366）")
    ap.add_argument("--card", required=True, help="卡号，如 142 / D1 / E81")
    ap.add_argument("--tree", default="", help="工人树（相对仓库根），如 .wt/D1")
    ap.add_argument("--spec", default="",
                    help="卡规格（仓库相对）；只在手工排障时给 —— 面板不收这个参数")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要执行的 argv，不派活")
    args = ap.parse_args(argv)

    card = str(args.card).strip()
    if not CARD_RE.match(card):
        return _refuse(card, "", f"卡号不合法：{card}（要形如 142 / D1 / E81）")

    tree = str(args.tree or "").strip()
    if tree and not TREE_RE.match(tree):
        return _refuse(card, tree, f"树不合法：{tree}（要形如 .wt/D1）")
    if tree and not (ROOT / tree).is_dir():
        return _refuse(card, tree, f"树不存在：{tree}")

    spec = str(args.spec or "").strip() or _resolve_spec(card)
    if not spec:
        return _refuse(card, tree, f"backlog 里没有卡 {card} ⇒ 没有卡规格 ⇒ 不许派活")
    spec_file = _spec_file(spec)
    if spec_file is None:
        return _refuse(card, tree, f"卡规格文件不存在：{spec}")

    cmd = build_command(card, str(spec_file), tree)
    if args.dry_run:
        print("[干跑] " + " ".join(cmd), flush=True)
        return 0

    print(f"[派活] card={card} spec={spec} tree={tree or '(主树)'} —— 转发真派活器", flush=True)
    try:
        rc = subprocess.run(cmd, cwd=str(ROOT), check=False, **NO_WINDOW).returncode
    except OSError as exc:
        _audit(card, tree, "FAIL", 2, f"起不来：{exc}")
        return _fail(f"真派活器起不来：{exc}")
    _audit(card, tree, "OK" if rc == 0 else "FAIL", rc)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
