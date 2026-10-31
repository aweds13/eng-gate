r"""Trae 道**进账**（卡 218 · T-G331）—— 让 CDP 驱动的那条面板道被**现有账**认出来。

## 它补的是哪个洞

卡 077 起这条道（`tools/trae_pool.mjs`，CDP 驱动 Trae 面板）一直是**零接线**：
`gates/diag/` 里连一个 `trae-*.jsonl` 都没有，主控要盯它只能自己挂 `sleep`。
它的运行日志叫 `trae-<卡>.jsonl` —— 而**整个号池的账**（`pool.registry` 的租约、
`pool.jobs` 的三态判据、卡 215 的 `wb_watch`）认的是**另一套名字**：

- 作业登记 `gates/diag/pool-registry.json`（`pool.registry`）—— 记「谁占了哪棵树 / 哪个域」；
- 工人日志 `gates/diag/wb-<卡>.jsonl`（`pool.jobs.scan_jobs` 的 `wb-*.jsonl` 口径）；
- 判决 `gates/diag/wb-<卡>.verdict.txt`（`scan_jobs` 用它判「已判决」；`wb_watch` 等它收工）。

本模块就是那**一处**转写：把 Trae 道的一次跑，落成上面三样。
★ 判据**只有一份** —— 租约走 `pool.registry.reserve`（树 / 域 / 门禁锁守卫都在里面，本模块
**不重写**任何判据）；判决文件名走 `wb_dispatch.verdict_file_for` 同源的 `log.with_suffix(...)`
口径（`wb-<卡>.jsonl` → `wb-<卡>.verdict.txt`，重试轮各自成对、互不覆盖）。

## 三个子命令（对着这条道的真实生命周期）

| 子命令 | 什么时候 | 落什么 |
|---|---|---|
| `start` | 开跑**之前** | `registry.reserve`（先占树）+ 工人日志 `init` 开场 |
| `finish` | 收工**之后** | 日志 `assistant` + `result`；**判决文件**；`--release` 放租约 |
| `status` | 随时 | 只读：活租约 + 日志 / 判决在不在 |

## 诚实边界（如实写）

- ★ **不 import / 不改 `tools/wb_dispatch.py`**（那是卡 215 的域）—— 本模块只**读**它的命名口径。
- ★ **不重占**：本卡**已有活租约**时 `start` 只**沿用**（报出来），不第二次 `reserve`
  —— 否则会撞上 `tree_guard` 判「自己占的树被自己占」。
- ★ **日志不许覆盖**：目标日志已存在 ⇒ 拒（与 `pool.guards.log_guard` 同一口径）；
  要跑第二轮，就把 `--log` 给成 `wb-<卡>.r2.jsonl` 这种**新名字**。
- ★ 本模块**不起任何子进程**（所以不涉及 NO_WINDOW）；它只写三个文件 + 登记。

## 用法

    python -X utf8 tools/pool/trae_dispatch.py start --card 218 --tree .wt/traecli \
        --files .trae/mcp.json --task T-G331 --pool trae --model "DeepSeek-V4.1-Flash Max"
    python -X utf8 tools/pool/trae_dispatch.py finish --card 218 --exit-code 0 \
        --answer-file gates/diag/trae-218.r2.out.md --session-id 6ace3b8e... --release
    python -X utf8 tools/pool/trae_dispatch.py status --card 218
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

# tools/ 上 sys.path（本文件在 tools/pool/ 下，直接 `python tools/pool/trae_dispatch.py` 跑时
# 只有 tools/pool/ 被加进去，`from pool import …` 会 ImportError）。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pool import jobs, registry, route_log  # noqa: E402 —— tools/ 已在 sys.path 上

if TYPE_CHECKING:  # pragma: no cover —— 只为类型注解（ruff TCH）
    from collections.abc import Sequence

#: Trae 道这一轮的"工具"清单 —— 面板是 CDP 驱动的 DOM 自动化，这是它真实走的步骤。
LANE_STEPS = (
    "cdp.attach(solo-lite)", "focusInput", "Input.insertText", "dispatchKeyEvent(Enter)",
    "clickApproval", ".core-finish-card(readAgents)", "writeFile(--out)",
)

#: 固定事件名 —— `pool.jobs.parse_events` 认的就是这三类（Claude-CLI 口径）。
KIND_INIT = "system"


# ================================================================ 路径口径


def worker_log_for(diag: Path, card: str) -> Path:
    """这一轮的工人日志 —— `gates/diag/wb-<卡>.jsonl`（`scan_jobs` 只扫这个口径）。"""
    return diag / f"wb-{card}.jsonl"


def verdict_for(log: Path) -> Path:
    """判决文件 = 日志名换后缀（与 `wb_dispatch.verdict_file_for` **同一口径**）。"""
    return log.with_suffix(".verdict.txt")


# ================================================================ 事件（JSONL）


def init_event(model: str, note: str) -> dict:
    """开场事件：把"这一轮是什么道、用什么模型、走哪些步骤"说清楚。"""
    return {
        "type": KIND_INIT,
        "subtype": "init",
        "model": model or "（没写）",
        "tools": list(LANE_STEPS),
        "lane": "trae-panel-cdp",
        "note": note,
    }


def answer_event(text: str) -> dict:
    """面板取回的**回答原文** —— 形状与 Claude-CLI 的 `assistant` 一样，好让 `job_status` 渲染。"""
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def result_event(subtype: str, summary: str) -> dict:
    """收尾事件 —— `parse_events` 的 `summary["final"]` 靠它非空（`--status` 也看它）。"""
    return {"type": "result", "subtype": subtype, "result": summary}


def _append(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


# ================================================================ start


def start(*, card: str, tree: str, files: Sequence[str], task: str = "", pool: str = "",
          model: str = "", log: Path | None = None, note: str = "", root: Path,
          now: float | None = None) -> tuple[int, str]:
    """占租约（**已有本卡活租约就沿用**）+ 写工人日志的 `init` 开场。返回 `(退出码, 人话)`。"""
    diag = jobs.diag_dir(root)
    log_path = Path(log) if log is not None else worker_log_for(diag, card)
    if log_path.exists():
        return 2, (f"日志不许覆盖：{log_path.as_posix()} 已存在 —— 换一个新名字"
                   f"（例如 wb-{card}.r2.jsonl）；本工具不给 --force。")
    mine = [row for row in registry.list_reservations(now) if str(row.get("card")) == str(card)]
    if mine:
        lease, reused = mine[-1], True
    else:
        try:
            lease = registry.reserve(card, task=task, tree=tree, files=files, pool=pool,
                                     model=model, log=log_path.as_posix(), note=note, now=now)
            reused = False
        except registry.GuardError as exc:
            return 2, "守卫拦下了，**没占树、也没写日志**：\n" + "".join(
                f"  · {item}\n" for item in exc.problems)
        except registry.RegistryError as exc:
            return 3, f"登记读不了 / 写不了：{exc}"
    _append(log_path, init_event(model or str(lease.get("model") or ""), note))
    head = "沿用已有活租约" if reused else "已占租约"
    text = (f"卡 {card}：{head}（树 {tree or '（主树）'}｜域 {'、'.join(files) or '（空）'}｜"
            f"owner={lease.get('owner') or '?'}｜pool={lease.get('pool') or '（没写）'}）\n"
            f"  工人日志：{log_path.as_posix()}（已写 init 开场）\n"
            f"  收工请跑：python -X utf8 tools/pool/trae_dispatch.py finish --card {card} "
            f"--log {log_path.as_posix()} --exit-code <码> [--answer-file <out.md>] [--release]")
    return 0, text


# ================================================================ finish


def _verdict_text(card: str, log: Path, *, exit_code: int, lines: int, has_result: bool,
                  disconnects: int, reconnects: int, answer_file: Path | None,
                  answer_chars: int, started_at: str, finished_at: str, session_id: str) -> str:
    """判决正文 —— 形状照 `wb-215.verdict.txt`（人能一眼看懂断在哪），**不另发明格式**。"""
    ok = exit_code == 0
    head = (f"card={card} 第=1 次 退出码={exit_code} 会话={session_id or '（没给）'} "
            f"开始于={started_at or '（不在登记里）'} 结束于={finished_at}")
    verdict = ("正常收工（Trae 面板道：--out 取回了回答）" if ok
               else f"没正常收工（退出码 {exit_code}）—— 面板道没跑通")
    tail = (f"看细节：python -X utf8 tools/wb_status.py {log.as_posix()} --tail 20 --repo")
    src = (answer_file.as_posix() if answer_file is not None else "（没给 --answer-file）")
    return "\n".join([
        head,
        f"判决：{verdict}",
        "诊断（这一轮断在哪）：",
        f"  退出码={exit_code}；有 result 事件={'有' if has_result else '没有'}；"
        f"末事件类型={'result' if has_result else '（还没收尾）'}；log 行数={lines}",
        f"  面板断线 {disconnects} 次 / 重连 {reconnects} 次"
        + ("（★ 面板重载过 —— 驱动靠重连活下来）" if disconnects else "（没断过线）"),
        f"  回答来源：{src}（{answer_chars} 字）",
        tail,
    ]) + "\n"


def finish(*, card: str, log: Path | None, exit_code: int, root: Path,
           answer_file: Path | None = None, session_id: str = "", disconnects: int = 0,
           reconnects: int = 0, release: bool = False, now: float | None = None,
           asked: str = "", tried: Sequence[dict] = (), served: str = "",
           route_status: str = "") -> tuple[int, str]:
    """写工人日志的 `assistant` + `result`，落**判决文件**；`--release` 顺手放租约。

    ★ 卡 A363（F39）在这里顺便落一条**路由回放**（`pool.route_log`）：谁被试过、谁真答了。
      `asked` / `tried` / `served` 三个参数**带默认值**，老调用点一个字节不用改（`tried` 为
      空 ⇒ 不落记录，理由见下）。`route_status` 不给就按退出码推（见 `_route_status`）。
    """
    diag = jobs.diag_dir(root)
    log_path = Path(log) if log is not None else worker_log_for(diag, card)
    if not log_path.exists():
        return 2, (f"没这个工人日志：{log_path.as_posix()} —— 先跑 start（它才写 init 开场）。")
    answer = ""
    if answer_file is not None:
        if not answer_file.exists():
            return 2, f"找不到回答文件：{answer_file.as_posix()}（面板的 --out 落哪了？）"
        answer = answer_file.read_text(encoding="utf-8", errors="replace")
        _append(log_path, answer_event(answer))
    subtype = "done" if exit_code == 0 else "timeout"
    src = answer_file.as_posix() if answer_file is not None else "（没给）"
    summary = (f"面板道退出码 {exit_code}；--out {src}；断线 {disconnects}/重连 {reconnects}")
    _append(log_path, result_event(subtype, summary))

    lines = jobs.read_log_lines(log_path)
    _timeline, parsed = jobs.parse_events(lines)
    mine = [row for row in registry.load() if str(row.get("card")) == str(card)]
    started_at = str(mine[-1].get("at")) if mine else ""
    path = verdict_for(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _verdict_text(card, log_path, exit_code=exit_code, lines=len(lines),
                      has_result=bool(parsed.get("final")), disconnects=disconnects,
                      reconnects=reconnects, answer_file=answer_file, answer_chars=len(answer),
                      started_at=started_at,
                      finished_at=datetime.datetime.fromtimestamp(
                          now if now is not None else datetime.datetime.now().timestamp()
                      ).isoformat(timespec="seconds"),
                      session_id=session_id),
        encoding="utf-8", newline="\n")
    _record_route(card=card, log_path=log_path, exit_code=exit_code, root=root,
                  asked=asked, tried=tried, served=served,
                  route_status=route_status, started_at=started_at)
    released = registry.release(card) if release else False
    text = (f"卡 {card} 收工入账：\n"
            f"  工人日志：{log_path.as_posix()}（{len(lines)} 行）\n"
            f"  判决：{path.as_posix()}（★ scan_jobs / wb_watch 认它）\n"
            f"  租约：{'已释放' if released else '还留着（要放就给 --release）'}")
    return 0, text


# ================================================================ 路由回放（F39 · 卡 A363）


def _attempt_of(log_path: Path) -> int:
    """这一轮是第几轮 —— 从日志名取（`wb-A363.r2.jsonl` → 2；没后缀 → 1）。

    ★ 与 `wb_dash._split_card` / `jobs.card_of` **同一口径**（轮次只认文件名后缀，
      不拿 `st_ctime` 当"第几轮"：Windows 上 ctime 是创建时间、复制/覆盖会重置）。
    """
    hit = re.search(r"\.r(\d+)$", log_path.stem)
    return int(hit.group(1)) if hit else 1


def _route_status(exit_code: int, served: str) -> str:
    """按**已有的事实**推这一轮的终态（不猜：猜不出来的那种留给调用方显式给）。

    `exit_code == 7` 是 `wb_dispatch.py` 的既有口径（额度 / 白名单耗尽，界外退出）；
    `quota_blocked`（额度挡住，压根没开工）在 `finish` 的入参里**没有对应物** ——
    那种情况由调用方经 `route_status=` 明说，本函数不替它编。
    """
    if exit_code == 7:
        return route_log.STATUS_STOPPED
    if exit_code == 0 and served:
        return route_log.STATUS_SERVED
    return route_log.STATUS_ALL_FAILED


def _record_route(*, card: str, log_path: Path, exit_code: int, root: Path, asked: str,
                  tried: Sequence[dict], served: str, route_status: str,
                  started_at: str) -> None:
    """落一条路由回放 —— **在做决定的地方、用做决定时的那些值**（照 `trace.go` 包注释）。

    ★ `tried` 为空 ⇒ **不落记录**：那说明这一轮没有真实的尝试顺序可记（老调用点不传）。
      落一条空记录只是把「不知道」写成「知道」。
    ★ 这里**不读** `gates/diag/wb-usage.jsonl` 去"补"或"对账"：那份账是每轮一行，
      同一轮里 `m1` 挂了换 `m2` 这件事它根本记不出来 —— 照它重算就是编数（判据 5）。
    ★ `asked` / `tried` / `served` 里**只有模型名与失败原因**，没有 prompt、回复正文或凭据
      （判据 2）。
    """
    if not tried:
        return
    epoch: float | None = None
    if started_at:
        try:
            epoch = datetime.datetime.fromisoformat(started_at).timestamp()
        except ValueError:
            epoch = None
    route_log.append_route(
        card=card, attempt=_attempt_of(log_path), asked=asked, tried=tried, served=served,
        status=route_status or _route_status(exit_code, served), started_at=epoch, root=root)



# ================================================================ status


def status(*, card: str, root: Path) -> tuple[int, str]:
    """只读：本卡活租约 + 工人日志 / 判决在不在（**不写一个字节**）。"""
    diag = jobs.diag_dir(root)
    live = [row for row in registry.list_reservations() if str(row.get("card")) == str(card)]
    logs = jobs.card_artifacts(diag, card, ".jsonl")
    out = [f"卡 {card} 的 Trae 道现状 —— 读 {diag.as_posix()}：",
           f"  活租约：{len(live)} 条"]
    for row in live:
        out.append(f"    · 树 {row.get('tree') or '（主树）'}｜pool={row.get('pool') or '（没写）'}"
                   f"｜owner={row.get('owner') or '?'}｜at={row.get('at')}｜log={row.get('log')}")
    if not logs:
        out.append("  工人日志：没有（还没跑 start）")
        return 0, "\n".join(out)
    for log in logs:
        verdict = verdict_for(log)
        rows = [r for r in jobs.scan_jobs(diag) if r["log"] == log.name]
        state = rows[0]["state"] if rows else "（扫不出来）"
        out.append(f"    · {log.name}  {log.stat().st_size}B  判决={verdict.name}"
                   f"{'（在）' if verdict.exists() else '（没有）'}  态={state}")
    return 0, "\n".join(out)


# ================================================================ 命令行


def _path(value: str | None) -> Path | None:
    return Path(value) if value else None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trae_dispatch.py",
        description="把 Trae 面板道（CDP）的一次跑，记成现有账认得的：租约 + 工人日志 + 判决。")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("start", "finish", "status"):
        p = sub.add_parser(name)
        p.add_argument("--card", required=True, help="卡号，例如 218")
        p.add_argument("--root", default=None,
                       help="树根（默认主工作树；测试用临时目录指）")
        if name != "status":
            p.add_argument("--log", default=None,
                           help="工人日志（默认 gates/diag/wb-<卡>.jsonl）")
        if name == "start":
            p.add_argument("--tree", default="", help="占哪棵树（相对主树根；'' = 主树）")
            p.add_argument("--files", default="", help="冲突域，逗号分隔")
            p.add_argument("--task", default="", help="任务号，例如 T-G331")
            p.add_argument("--pool", default="trae", help="号池名（记进租约）")
            p.add_argument("--model", default="", help="模型名（记进租约与 init 开场）")
            p.add_argument("--note", default="", help="备注（记进租约）")
        if name == "finish":
            p.add_argument("--exit-code", type=int, default=0, help="面板道的退出码（0=正常收工）")
            p.add_argument("--answer-file", default=None, help="面板 --out 落的那份回答")
            p.add_argument("--session-id", default="", help="面板会话号（写进判决）")
            p.add_argument("--disconnects", type=int, default=0, help="面板断线几次")
            p.add_argument("--reconnects", type=int, default=0, help="重连成功几次")
            p.add_argument("--release", action="store_true", help="收工顺手放掉租约")
    return parser


def _root_of(value: str | None) -> Path:
    return Path(value) if value else registry.main_tree_root()


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        root = _root_of(args.root)
    except registry.RegistryError as exc:
        print(f"算不出主工作树：{exc}", file=sys.stderr)
        return 3
    diag = jobs.diag_dir(root)
    if args.cmd == "start":
        code, text = start(card=args.card, tree=args.tree,
                           files=[f.strip() for f in args.files.split(",") if f.strip()],
                           task=args.task, pool=args.pool, model=args.model,
                           log=_path(args.log), note=args.note, root=root)
    elif args.cmd == "finish":
        code, text = finish(card=args.card, log=_path(args.log), exit_code=args.exit_code,
                            root=root, answer_file=_path(args.answer_file),
                            session_id=args.session_id, disconnects=args.disconnects,
                            reconnects=args.reconnects, release=args.release)
    else:
        code, text = status(card=args.card, root=root)
    stream = sys.stdout if code == 0 else sys.stderr
    print(text, file=stream)
    if args.cmd == "status":
        print(f"（diag 目录：{diag.as_posix()}）", file=sys.stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
