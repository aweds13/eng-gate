r"""一次盯**多张卡**，收工就出结论（卡 215 · T-G328）—— 派活不该靠人记着轮询。

**为什么有它**（主控 2026-10-13 一天**七次**靠人肉轮询等工人）：`wb_dispatch --detach` 派出去的活
**没有回推通道**（派活器自己的提示原话就是「请轮询」），主控只能每批挂一个
`for i in $(seq …); do sleep 60; done` 的后台看守 —— 有一次忘了挂，用户问「没通知你吗」才发现
工人早就收工了。本工具把那句「请轮询」变成**默认动作**：挂一次，收工自动出结论。

    python -X utf8 tools/wb_watch.py --cards 213 214 215
    python -X utf8 tools/wb_watch.py --batch B-20261015
    python -X utf8 tools/wb_watch.py --cards 213 --timeout 600 --interval 30

**行为**：阻塞直到**所有**目标都出现「收工信号」，然后打印每张卡的结论（判决首行 / 退出码 / 时长）。
真轮询（每 `--interval` 秒醒一次、打印一行带「现在到哪了」的心跳）+ **硬超时**（默认 2 小时）。

**收工信号按池分别判**（这是本卡的核心，不写死一条路）：
  · CodeBuddy：`<树>/gates/diag/wb-<卡>.verdict.txt` 出现且**非空**；
  · 码道：`<号池>/logs/card-<卡>-<日期>-<时刻>.meta.json` 里的 `finished == true`。
两条路都**现读**、每轮都查；读不到就如实说「这张卡我看不见信号」——
★ **不许**把「看不见」当成「已完成」（空信号文件同理，也不算完成）。

**判死**（没跑完就断了）：复用在跑的判据、**不另写一份**——
  · CodeBuddy：没有判决 + 日志静默超过 `pool.jobs.STALL_SECONDS` → `classify_job_state` 判「断了」；
  · 码道：`meta.json` 存在但 `finished` 不是 `true`（被看门狗 / 超时掐了，或没见到收工）→ 判死。

**退出码**：全收工 = 0；有卡判死 = 3；超时 = 4。

**只读**：只读状态文件，不派活、不取消、不写仓库里任何文件，**不起任何子进程**
（因此不涉及 NO_WINDOW —— 没有子进程可起）。

★ 边界（如实写）：本工具**不判断内容对不对**（那是主控复核的事），只判断「哪张卡收工了 / 断了」。
多树（`.wt/<树>`）里同一卡号是不同卡 —— 本工具按**单棵树**（`--root`，默认本文件上两级）看，
不给跨树合并（要盯别的树就显式 `--root <那棵树>`）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import tomllib

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

# ★ 判据只有一份真源，都在 `tools/pool/` 包里 —— 这里只 import、只调用，不另抄一份
#   （本仓最忌「两份真源」：判据漂一次就会串卡 / 误判）。
from pool.jobs import card_artifacts, classify_job_state  # noqa: E402 —— 产物定位 + 三态判据
from pool.model_registry import dispatch_log_dirs  # noqa: E402 —— 两边日志目录唯一实现
from pool.plan import batch_manifest_path  # noqa: E402 —— 批次预声明定位唯一实现

# ---------------------------------------------------------------- 状态 / 退出码
FINISHED = "收工"          # 有收工信号
DEAD = "判死"              # 没跑完就断了
RUNNING = "在跑"           # 还活着，继续等
BLIND = "看不见信号"       # 两条路都读不到这张卡（★ 不许当成已完成）

EXIT_FINISHED = 0          # 全部收工
EXIT_DEAD = 3              # 有卡判死（非零）
EXIT_TIMEOUT = 4           # 超时（另一个码）
EXIT_USAGE = 2             # 用法 / 读不到批次预声明

DEFAULT_TIMEOUT = 7200.0   # 默认硬超时：2 小时（长卡给足）
DEFAULT_INTERVAL = 45.0    # 轮询间隔（卡说 30~60s；取中位）

# 码道日志名是 `card-<卡>-<YYYYMMDD>-<HHMMSS>.<后缀>`。★ 用**精确**匹配，别宽 glob：
# `card-215-*` 会串到 `card-2150-…`（`fnmatch("card-2150-…", "card-215-*") == True`，卡 029 §2.9）。
_CB_VERDICT_SUFFIX = ".verdict.txt"
_CA_META_SUFFIX = ".meta.json"
_LOG_SUFFIX = ".jsonl"

_EXIT_CODE_RE = re.compile(r"退出码=(-?\d+)")
_BEGIN_RE = re.compile(r"开始于=(\S+)")
_END_RE = re.compile(r"结束于=(\S+)")


# ---------------------------------------------------------------- 收工信号（按池）
@dataclass
class CardSignal:
    """一张卡此刻的读数 —— 「判决首行 / 退出码 / 时长」都从**真文件**里现读，读不到就留空。"""

    card: str
    kind: str                     # FINISHED / DEAD / RUNNING / BLIND
    pool: str = ""                # codebuddy / codearts（BLIND 时为空）
    verdict_line: str = ""        # 判决首行（码道 = meta 的 verdict 字段）
    exit_code: int | None = None
    duration_s: float | None = None
    detail: str = ""              # 一句人话：为什么这么判


def _first_nonempty(text: str) -> str:
    return next((ln.strip() for ln in text.splitlines() if ln.strip()), "")


def _parse_verdict(text: str) -> tuple[str, int | None, float | None]:
    """从 `wb_dispatch` 的判决文件里取（首行, 退出码, 时长秒）—— 拿不到就 None。"""
    first = _first_nonempty(text)
    hit = _EXIT_CODE_RE.search(text)
    code = int(hit.group(1)) if hit else None
    began, ended = _BEGIN_RE.search(first), _END_RE.search(first)
    duration: float | None = None
    if began and ended:
        try:
            duration = (datetime.fromisoformat(ended.group(1))
                        - datetime.fromisoformat(began.group(1))).total_seconds()
        except ValueError:
            duration = None
    return first, code, duration


def _read_meta(path: Path) -> dict | None:
    """读码道的 `.meta.json`；解不出（空文件 / 坏 JSON / 读不到）→ None（**不当成完成**）。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _codearts_artifacts(logs_dir: Path, card: str, suffix: str) -> list[Path]:
    """码道那张卡的产物（精确匹配 `card-<卡>-<日期>-<时刻><后缀>`，按 mtime 升序）。"""
    if not logs_dir.is_dir():
        return []
    pat = re.compile(rf"^card-{re.escape(card)}-\d{{8}}-\d{{6}}{re.escape(suffix)}$")
    return sorted((p for p in logs_dir.iterdir() if pat.match(p.name)),
                  key=lambda p: p.stat().st_mtime)


def _probe_codebuddy(card: str, root: Path, now: float) -> CardSignal | None:
    """CodeBuddy 池的读数：`gates/diag/wb-<卡>.verdict.txt` 非空 = 收工；否则按日志静默判。

    读不到任何证据（无判决、无日志）→ None（这条池看不见这张卡）。
    """
    diag = root / "gates" / "diag"
    verdicts = card_artifacts(diag, card, _CB_VERDICT_SUFFIX)
    if verdicts:
        verdict = verdicts[-1]
        try:
            text = verdict.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if text.strip():
            line, code, dur = _parse_verdict(text)
            return CardSignal(card, FINISHED, "codebuddy", line, code, dur,
                              detail=f"判决文件 {verdict.name}")
        # ★ 空判决文件：**不许**当成已完成（卡 215 反例）—— 落到日志静默那一路去判。
    logs = card_artifacts(diag, card, _LOG_SUFFIX)
    if not logs:
        return None
    log = logs[-1]
    age = max(0.0, now - log.stat().st_mtime)
    state, why = classify_job_state(age, False)     # ★ 「断了」的唯一实现（pool.jobs）
    kind = DEAD if state == "断了" else RUNNING
    return CardSignal(card, kind, "codebuddy", detail=f"{why}（{log.name}）")


def _probe_codearts(card: str, root: Path, now: float) -> CardSignal | None:
    """码道池的读数：`.meta.json` 的 `finished == true` = 收工；`finished` 非 true = 判死。

    没有 meta（工人还在跑，或派活器还没来得及落 meta）→ 看日志在不在：在 → 在跑，不在 → 看不见。
    """
    logs_dir = dispatch_log_dirs(root)["codearts"]
    metas = _codearts_artifacts(logs_dir, card, _CA_META_SUFFIX)
    if metas:
        meta_path = metas[-1]
        data = _read_meta(meta_path)
        if data is not None and data.get("finished") is True:
            seconds = data.get("seconds")
            return CardSignal(
                card, FINISHED, "codearts",
                verdict_line=str(data.get("verdict") or "正常收工"),
                exit_code=data.get("exit_code") if isinstance(data.get("exit_code"), int) else None,
                duration_s=float(seconds) if isinstance(seconds, (int, float)) else None,
                detail=f"meta.json {meta_path.name}（finished=true）")
        if data is not None:
            # meta 有内容但 finished 不是 true（被看门狗 / 超时掐了，或没见到收工）→ 判死，
            # 把派活器写在 meta 里的那句原话带出来（人一眼看得出是"被掐"还是"失败"）。
            why = data.get("verdict") or "finished 不是 true"
            return CardSignal(card, DEAD, "codearts", detail=f"{meta_path.name}：{why}")
        # ★ meta 解不出（空文件 / 坏 JSON / 半截写）：**既不许**当成完成、**也不许**凭它判死
        #   —— 落到日志那一路如实说「还在跑 / 看不见」（卡 052 的教训：没证据不下结论）。
    logs = _codearts_artifacts(logs_dir, card, _LOG_SUFFIX)
    if not logs:
        return None
    return CardSignal(card, RUNNING, "codearts", detail=f"还没有 meta.json（{logs[-1].name}）")


def probe_card(card: str, root: Path, now: float) -> CardSignal:
    """一张卡的现读读数 —— **两条池的路都查**，按 收工 > 判死 > 在跑 取舍。

    ★ 两条路都看不见 → BLIND（如实说「我看不见信号」，**不许**当成已完成）。
    """
    found = [sig for sig in (_probe_codebuddy(card, root, now),
                             _probe_codearts(card, root, now)) if sig is not None]
    if not found:
        return CardSignal(card, BLIND, detail="两条池里都看不到这张卡的信号")
    for kind in (FINISHED, DEAD, RUNNING):
        for sig in found:
            if sig.kind == kind:
                return sig
    return found[0]


# ---------------------------------------------------------------- 批次 → 卡号
class BatchWatchError(Exception):
    """批次预声明读不到 / 没有成员 —— 带路径，拒绝猜。"""


def resolve_batch(batch: str, manifest_path: Path | None = None) -> list[str]:
    """`--batch B-XXX` → 成员卡号列表：读 `gates/diag/batch/<批号>.toml` 的 `[[member]].id`。

    ★ 定位走 `pool.plan.batch_manifest_path`（预声明住主树、卡树里也找得到它，见那里的说明）；
    `manifest_path` 是给测试注入用的（不给就用真源）。
    """
    path = manifest_path if manifest_path is not None else batch_manifest_path(batch)
    if not path.is_file():
        raise BatchWatchError(f"找不到批次预声明：{path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise BatchWatchError(f"批次预声明读不出来：{path}（{exc}）") from exc
    members = data.get("member") or []
    cards = [str(m.get("id", "")).strip() for m in members if isinstance(m, dict) and m.get("id")]
    if not cards:
        raise BatchWatchError(f"批次 {batch} 的预声明里没有成员卡：{path}")
    return cards


# ---------------------------------------------------------------- 轮询主循环
def _fmt_duration(seconds: float | None) -> str:
    return "读不到" if seconds is None else f"{seconds / 60:.1f} 分钟"


def _conclusion_lines(cards: Sequence[str], signals: dict[str, CardSignal]) -> list[str]:
    """每张卡的结论：判决首行 / 退出码 / 时长 —— 都从 `CardSignal` 现读值来。"""
    out = ["", "=== 收工结论 ==="]
    for card in cards:
        sig = signals[card]
        where = f"（{sig.pool} 池）" if sig.pool else ""
        out.append(f"卡 {card}：{sig.kind}{where}")
        out.append(f"  判决首行：{sig.verdict_line or '读不到'}")
        out.append(f"  退出码：{sig.exit_code if sig.exit_code is not None else '读不到'}")
        out.append(f"  时长：{_fmt_duration(sig.duration_s)}")
        if sig.detail:
            out.append(f"  说明：{sig.detail}")
    return out


def _heartbeat(elapsed: float, cards: Sequence[str], signals: dict[str, CardSignal]) -> str:
    """心跳一行，且**要有「现在到哪了」**（每张卡此刻的读数）—— 卡 215 的硬要求。"""
    where = " · ".join(f"{card}={signals[card].kind}" for card in cards)
    return f"[心跳] 已盯 {elapsed / 60:.1f} 分钟 | {where}"


def watch(cards: Iterable[str], *,
          root: Path | None = None,
          timeout: float = DEFAULT_TIMEOUT,
          interval: float = DEFAULT_INTERVAL,
          clock: Callable[[], float] = time.time,
          sleep: Callable[[float], None] = time.sleep,
          emit: Callable[[str], None] = print) -> int:
    """真轮询直到全部收工 / 有卡判死 / 超时；返回退出码（0 / 3 / 4）。

    `clock` 与 `sleep` 可注入（测试用假时间源，**不真等**）—— 判据本身仍是现读文件。
    """
    root = Path(root) if root is not None else ROOT
    target = list(cards)
    start = clock()
    while True:
        now = clock()
        signals = {card: probe_card(card, root, now) for card in target}
        if all(sig.kind == FINISHED for sig in signals.values()):
            for line in _conclusion_lines(target, signals):
                emit(line)
            emit(f"[OK ] 全部收工（{len(target)} 张）")
            return EXIT_FINISHED
        dead = [card for card in target if signals[card].kind == DEAD]
        if dead:
            for line in _conclusion_lines(target, signals):
                emit(line)
            emit(f"[FAIL] 有卡判死（没跑完就断了）：{'、'.join(dead)}")
            return EXIT_DEAD
        elapsed = now - start
        if elapsed >= timeout:
            unfinished = [card for card in target if signals[card].kind != FINISHED]
            for line in _conclusion_lines(target, signals):
                emit(line)
            emit(f"[超时] 已等 {elapsed / 60:.1f} 分钟（上限 {timeout / 60:.1f} 分钟）—— "
                 f"还没完的卡：{'、'.join(unfinished) or '（无）'}")
            return EXIT_TIMEOUT
        emit(_heartbeat(elapsed, target, signals))
        sleep(min(interval, max(0.0, timeout - elapsed)))


# ---------------------------------------------------------------- CLI
def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="一次盯多张卡，收工就出结论（只读；真轮询 + 心跳 + 硬超时）")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--cards", nargs="+", metavar="卡号", help="要盯的卡号（可多张）")
    group.add_argument("--batch", metavar="B-XXX",
                       help="盯整批：读 gates/diag/batch/<批号>.toml 的成员卡")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                    help=f"硬超时（秒，默认 {DEFAULT_TIMEOUT:.0f} = 2 小时）")
    ap.add_argument("--interval", type=float, default=DEFAULT_INTERVAL,
                    help=f"轮询间隔（秒，默认 {DEFAULT_INTERVAL:.0f}）")
    ap.add_argument("--root", default=str(ROOT),
                    help="仓库根（默认本文件上两级；要盯别的树就显式给）")
    args = ap.parse_args(argv)

    if args.batch:
        try:
            cards = resolve_batch(args.batch)
        except BatchWatchError as exc:
            print(f"[FAIL] {exc}", file=sys.stderr)
            return EXIT_USAGE
    else:
        cards = [c.strip() for c in args.cards if c.strip()]
    print(f"[看 ] 盯 {len(cards)} 张卡：{'、'.join(cards)}"
          f"（超时 {args.timeout / 60:.0f} 分钟 / 每 {args.interval:.0f} 秒查一次）", flush=True)
    return watch(cards, root=Path(args.root), timeout=args.timeout, interval=args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
