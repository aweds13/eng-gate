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
  · CodeBuddy：`<树>/gates/diag/wb-<卡>.verdict.txt` 出现后**按三态判**（卡 E41）——
    没有额度痕迹 ⇒ 收工；命中额度类 ⇒ 判死（`detail` 带「额度：…」，通知流写 `state:"quota"`）；
    判不出 ⇒ 交给日志静默那一路（**不许**判收工）；
  · 码道：`<号池>/logs/card-<卡>-<日期>-<时刻>.meta.json` 里的 `finished == true`，
    但 meta 的 `errors` / `verdict` 命中额度类 ⇒ 判死（**不是**收工）。
两条路都**现读**、每轮都查；读不到就如实说「这张卡我看不见信号」——
★ **不许**把「看不见」当成「已完成」（空信号文件同理，也不算完成）。
★ **额度判据只有一份真源**：一律调 `wb_dispatch.quota_error`（卡 029 / 045 / 201）——
  本模块**不写** needle 列表，也**不看退出码**（额度错误长得像成功：退出码 0 + 空回话，
  旧写法「文件非空即收工」就是这么把额度失败读成正常收工的，卡 E41）。

**判死**（没跑完就断了）：复用在跑的判据、**不另写一份**——
  · CodeBuddy：没有判决 + 日志静默超过 `pool.jobs.STALL_SECONDS` → `classify_job_state` 判「断了」；
  · 码道：`meta.json` 存在但 `finished` 不是 `true`（被看门狗 / 超时掐了，或没见到收工）→ 判死。

**退出码**：全收工 = 0；有卡判死 = 3；超时 = 4；合用看守发现「上一个看守死了」= 5。

★ 卡 E7（T-AG453）起它多了两件事（`one` 形态要 `--write-done` 才落盘，默认仍**只读**；
  `shared` 形态天然要落盘 —— 计数与中间态就是它的产出）：

  · **完工事件落盘**：判决出现时写 `gates/diag/wb-<卡>.done`（一行 JSON：
    `{"card","task","exit_code","at","log","report"}`），并往 `gates/diag/notifications.jsonl`
    追加一行（行里带 `card` + `verdict`，正好是 `wb_notify` 的幂等键 —— 复用它的机制）。
  · **两种看守形态**（`--mode`）：`one` = 专盯这几张卡，出判决就退（派活器默认）；
    `shared` = 全局一份**合用**看守，引用计数落 `gates/diag/watch-registry.json`
    （`+1` 每派一张 / `-1` 每出一张判决 / 归 0 写一条 `batch-done` 并退出）。

★ **计数抗崩溃**：`refcount` 不靠内存变量 —— 每拍都从磁盘事实重算（已出判决的卡不算未完成），
  看守重启也一样（`rebuild_registry`）。看守每拍把**心跳**写进登记表；心跳超过 `--timeout`
  且还有卡没判决 ⇒ 写 `state:"watcher-stale"` 事件并退 **5**，**不许**留一个「看起来还在盯」的假象。
★ **看守不猜成功**：只读磁盘上的判决（`probe_card`）—— 超时没判决就写 `state:"timeout"`，
  **绝不**把「没判决」当成功。
★ **旧证据不许冒充这一轮**（`--since`）：派活器会把「这一轮开跑的时刻」传过来，
  比它旧的判决 / 日志一律不认 —— 否则 `--force` 重派时上一轮那份静默日志会被读成「判死」。

★ 边界（如实写）：本工具**不判断内容对不对**（那是主控复核的事），只判断「哪张卡收工了 / 断了」。
多树（`.wt/<树>`）里同一卡号是不同卡 —— 本工具按**单棵树**（`--root`，默认本文件上两级）看，
不给跨树合并（要盯别的树就显式 `--root <那棵树>`）。
"""

from __future__ import annotations

import argparse
import json
import os
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
# ★ 卡 E7：判决解析 / 摘要指针 / 队列 task 字段都**复用**既有实现（别抄第二份）。
import wb_notify  # noqa: E402 —— 判决文本 + 结束时刻 + 摘要指针的唯一实现
from pool.jobs import (  # noqa: E402 —— 产物定位 + 三态判据 + 日志读法
    UnknownLogEncodingError,
    card_artifacts,
    classify_job_state,
    read_log_lines,
)
from pool.model_registry import dispatch_log_dirs  # noqa: E402 —— 两边日志目录唯一实现
from pool.plan import batch_manifest_path  # noqa: E402 —— 批次预声明定位唯一实现
from wb_plan import load_sharded_backlog  # noqa: E402 —— 队列读取唯一实现

# ---------------------------------------------------------------- 状态 / 退出码
FINISHED = "收工"          # 有收工信号
DEAD = "判死"              # 没跑完就断了
RUNNING = "在跑"           # 还活着，继续等
BLIND = "看不见信号"       # 两条路都读不到这张卡（★ 不许当成已完成）

EXIT_FINISHED = 0          # 全部收工
EXIT_DEAD = 3              # 有卡判死（非零）
EXIT_TIMEOUT = 4           # 超时（另一个码）
EXIT_STALE = 5             # 合用看守自己死了（心跳过期 + 还有卡没判决）
EXIT_USAGE = 2             # 用法 / 读不到批次预声明

DEFAULT_TIMEOUT = 7200.0   # 默认硬超时：2 小时（长卡给足）
DEFAULT_INTERVAL = 45.0    # 轮询间隔（卡说 30~60s；取中位）

#: 「看守还活着吗」的窗口：看守每 `--interval` 落一次心跳，**几分钟没动 = 多半死了**。
#: ★ 与看守自己的硬超时是两回事：硬超时要盖过工人的全部续跑轮（可能好几小时），
#:   用它判「还活着没」会让死了三小时的看守继续被当成在盯（卡 E7 判据 8 要防的就是这个）。
ALIVE_WINDOW = 180.0

#: 登记表里一张卡的三种状态（`watching` 才是「没判决、还在盯」）。
STATE_WATCHING = "watching"
STATE_DONE = "done"
STATE_DEAD = "dead"

#: 事件里的 `state` 值（卡 E7 逐字钉着 `batch-done` / `watcher-stale` / `timeout`）。
STATE_STALE = "watcher-stale"
STATE_TIMEOUT = "timeout"
STATE_BATCH_DONE = "batch-done"
#: 卡 E41：额度类判死单独一个 state —— 「这趟没跑」与「卡做错了」处置不同（别混成 dead）。
STATE_QUOTA = "quota"

_KEEP = object()           # 哨兵：`rebuild_registry()` 里「这一项保持原样」


# 码道日志名是 `card-<卡>-<YYYYMMDD>-<HHMMSS>.<后缀>`。★ 用**精确**匹配，别宽 glob：
# `card-215-*` 会串到 `card-2150-…`（`fnmatch("card-2150-…", "card-215-*") == True`，卡 029 §2.9）。
_CB_VERDICT_SUFFIX = ".verdict.txt"
_CA_META_SUFFIX = ".meta.json"
_LOG_SUFFIX = ".jsonl"

_EXIT_CODE_RE = re.compile(r"退出码=(-?\d+)")
_BEGIN_RE = re.compile(r"开始于=(\S+)")
_END_RE = re.compile(r"结束于=(\S+)")
#: 判决文件里那句「判决：…」（`wb_dispatch.write_verdict` / `pool.trae_dispatch` 同一形状）。
#: 没有这一句 = 只有退出码之类的半截货 ⇒ **判不出**，不许当收工（卡 E41 §2.2 第三类）。
_REASON_RE = re.compile(r"^判决：(.*)$", re.M)


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
    quota: str = ""               # 非空 = 额度类判死（`quota_error` 的 `why`，卡 E41）


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


def _verdict_reason(text: str) -> str:
    """判决文件里「判决：」那句话；没有 / 是空的 ⇒ 空串（半截写 / 只有退出码）。"""
    hit = _REASON_RE.search(text)
    return hit.group(1).strip() if hit else ""


def _quota_error(lines: list[str]) -> dict | None:
    """调**唯一那份**额度判据：`wb_dispatch.quota_error`（卡 029 / 045 / 201）。

    ★ 函数内 import：`wb_dispatch` 反过来在模块级 import 本模块（派活即看守），
      模块级互引会把两个模块的初始化绕成一团 —— 这里只在真要判的时候取一下。
    ★ 本模块**不抄** needle 列表、不抄两道闸门：判据漂了只会漂一处。
    """
    import wb_dispatch  # noqa: PLC0415 —— 见上：避免与 wb_dispatch 模块级互引

    return wb_dispatch.quota_error(lines)


def _quota_of_text(text: str) -> dict | None:
    """把一段**判决文案**喂给同一份判据（码道 meta 的 `verdict` / 判决文件的正文）。

    ★ 判决文案不是事件流 ⇒ 包成一条 `is_error` 的 `result` 事件，让那两道闸门照常说话
      （候选闸门 + 结构化字段优先）；本模块仍然**一个 needle 都不写**。
    """
    if not text.strip():
        return None
    event = json.dumps({"type": "result", "subtype": "error_during_execution",
                        "is_error": True, "result": "", "errors": text},
                       ensure_ascii=False)
    return _quota_error([event])


def _verdict_log_lines(verdict: Path, diag: Path, card: str,
                       since: float | None) -> list[str]:
    """这一轮判决**对应的**日志行（`wb-<卡>[.rN].jsonl`）；同一份都读不到 ⇒ 空列表。

    ★ 先认**同轮**那份（判决名换后缀，与 `wb_dispatch.verdict_file_for` 同一口径）——
      多轮时别拿第 2 轮的判决去读第 1 轮的日志；换不出来再退回这一轮最新那份日志。
    """
    sibling = verdict.with_name(verdict.name[: -len(_CB_VERDICT_SUFFIX)] + _LOG_SUFFIX)
    paths = [sibling] if sibling.is_file() else _fresh(
        card_artifacts(diag, card, _LOG_SUFFIX), since)[-1:]
    for path in reversed(paths):
        try:
            return read_log_lines(path)
        except (OSError, UnknownLogEncodingError):
            continue
    return []


def _quota_signal(card: str, pool: str, quota: dict, *, verdict: str = "",
                  code: int | None = None, dur: float | None = None,
                  where: str = "") -> CardSignal:
    """额度类 ⇒ 一律 `DEAD`（**不是** `FAILED`：卡没做错，是这趟没跑）+ 「额度：<why>」。"""
    tail = f"（{where}）" if where else ""
    return CardSignal(card, DEAD, pool, verdict, code, dur,
                      detail=f"额度：{quota['why']}{tail}", quota=quota["why"])


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


#: 文件时间戳粒度容差（秒）—— Windows 上 mtime 可落后墙钟数毫秒（卡 E22 实测 1.4 ms，
#: NTFS 更新周期约 15.6 ms）。判「这一轮的产物」时留这么多余量，见 `_fresh`。
_MTIME_GRANULARITY_SLACK = 1.0


def _fresh(paths: list[Path], since: float | None) -> list[Path]:
    """只留**这一轮**的产物（mtime ≥ `since`）—— 上一轮的旧判决 / 旧日志不许冒充当前状态。

    ★ 卡 E7 的真现场：`--force` 重派同一张卡时，旧 `wb-<卡>.jsonl` 还在、也早就静默
      ⇒ 新起的看守一上来就会把它读成「判死」并退 3（假死，比不挂看守更误导）。
      派活器用 `--since`（这一轮开跑的时刻）把旧证据切掉。`since=None`（手动跑）照旧全认。

    ★ 卡 E22：**文件时间戳比墙钟粗**（Windows 实测同一次写入的 mtime 比 `time.time()`
      早 1.4 ms；NTFS 更新周期 ~15.6 ms）⇒ 刚写的判决会被 `mtime >= since` 判成「上一轮」，
      表现为 `rebuild_registry` 把已收工的卡算进未完成（多进程下偶发红）。留 1 秒容差：
      派活到工人出判决隔着秒级以上，1 秒不会把真·上一轮的判决混进这一轮。
    """
    if since is None:
        return paths
    cutoff = since - _MTIME_GRANULARITY_SLACK
    kept: list[Path] = []
    for path in paths:
        try:
            if path.stat().st_mtime >= cutoff:
                kept.append(path)
        except OSError:                              # 边读边被删 ⇒ 这一份不认
            continue
    return kept


def _probe_codebuddy(card: str, root: Path, now: float,
                     since: float | None = None) -> CardSignal | None:
    """CodeBuddy 池的读数：判决文件**按三态判**（卡 E41）；没有判决按日志静默判。

    ★ 三态：无额度痕迹 ⇒ 收工；命中额度类 ⇒ 判死（`detail` 带「额度：…」）；
      空判决 / 判不出 ⇒ **不许**收工，交给日志静默那一路（`classify_job_state`）。
    ★ 额度判据**只有一份**（`wb_dispatch.quota_error`）：先喂这一轮的**日志事件**，
      再喂判决文案本体 —— 两样都过同一道闸门，本模块不写 needle。
    ★ 退出码**不参与判定**（额度错误就是退出码 0 + 空回话），只写进 detail 给人看。
    读不到任何证据（无判决、无日志）→ None（这条池看不见这张卡）。
    ★ 给了 `since` ⇒ 只认这一轮之后的判决 / 日志（旧件不许冒充）。
    """
    diag = root / "gates" / "diag"
    verdicts = _fresh(card_artifacts(diag, card, _CB_VERDICT_SUFFIX), since)
    if verdicts:
        verdict = verdicts[-1]
        try:
            text = verdict.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if text.strip() and _verdict_reason(text):
            line, code, dur = _parse_verdict(text)
            quota = (_quota_error(_verdict_log_lines(verdict, diag, card, since))
                     or _quota_of_text(text))
            if quota is not None:
                return _quota_signal(card, "codebuddy", quota, verdict=line,
                                     code=code, dur=dur, where=verdict.name)
            return CardSignal(card, FINISHED, "codebuddy", line, code, dur,
                              detail=f"判决文件 {verdict.name}")
        # ★ 空判决 / 只有退出码（没写「判决：」那句）= **判不出** ⇒ 不许收工（卡 215 反例 /
        #   卡 E41 §2.2 第三类），落到日志静默那一路去判。
    logs = _fresh(card_artifacts(diag, card, _LOG_SUFFIX), since)
    if not logs:
        return None
    log = logs[-1]
    age = max(0.0, now - log.stat().st_mtime)
    state, why = classify_job_state(age, False)     # ★ 「断了」的唯一实现（pool.jobs）
    kind = DEAD if state == "断了" else RUNNING
    return CardSignal(card, kind, "codebuddy", detail=f"{why}（{log.name}）")


def _probe_codearts(card: str, root: Path, now: float,
                    since: float | None = None) -> CardSignal | None:
    """码道池的读数：`.meta.json` 的 `finished == true` = 收工；`finished` 非 true = 判死。

    ★ 卡 E41：`finished=true` 也要过**同一道额度判据** —— meta 的 `errors` / `verdict`
      命中额度类 ⇒ `DEAD`（detail 带「额度：…」），不是收工；判据仍然只有 `wb_dispatch` 那一份。
    没有 meta（工人还在跑，或派活器还没来得及落 meta）→ 看日志在不在：在 → 在跑，不在 → 看不见。
    ★ 给了 `since` ⇒ 上一轮的 meta / 日志一律不认（同 `_probe_codebuddy` 的理由）。
    """
    logs_dir = dispatch_log_dirs(root)["codearts"]
    metas = _fresh(_codearts_artifacts(logs_dir, card, _CA_META_SUFFIX), since)
    if metas:
        meta_path = metas[-1]
        data = _read_meta(meta_path)
        if data is not None:
            seconds = data.get("seconds")
            code = data.get("exit_code") if isinstance(data.get("exit_code"), int) else None
            dur = float(seconds) if isinstance(seconds, (int, float)) else None
            words = " ".join(str(data.get(key) or "")
                              for key in ("verdict", "errors", "errors_info"))
            quota = _quota_of_text(words)
            if quota is not None:
                return _quota_signal(card, "codearts", quota,
                                     verdict=str(data.get("verdict") or ""),
                                     code=code, dur=dur, where=meta_path.name)
        if data is not None and data.get("finished") is True:
            return CardSignal(
                card, FINISHED, "codearts",
                verdict_line=str(data.get("verdict") or "正常收工"),
                exit_code=code, duration_s=dur,
                detail=f"meta.json {meta_path.name}（finished=true）")
        if data is not None:
            # meta 有内容但 finished 不是 true（被看门狗 / 超时掐了，或没见到收工）→ 判死，
            # 把派活器写在 meta 里的那句原话带出来（人一眼看得出是"被掐"还是"失败"）。
            why = data.get("verdict") or "finished 不是 true"
            return CardSignal(card, DEAD, "codearts", detail=f"{meta_path.name}：{why}")
        # ★ meta 解不出（空文件 / 坏 JSON / 半截写）：**既不许**当成完成、**也不许**凭它判死
        #   —— 落到日志那一路如实说「还在跑 / 看不见」（卡 052 的教训：没证据不下结论）。
    logs = _fresh(_codearts_artifacts(logs_dir, card, _LOG_SUFFIX), since)
    if not logs:
        return None
    return CardSignal(card, RUNNING, "codearts", detail=f"还没有 meta.json（{logs[-1].name}）")


def probe_card(card: str, root: Path, now: float,
               since: float | None = None) -> CardSignal:
    """一张卡的现读读数 —— **两条池的路都查**，按 收工 > 判死 > 在跑 取舍。

    ★ 两条路都看不见 → BLIND（如实说「我看不见信号」，**不许**当成已完成）。
    ★ `since`（可选）= 这一轮开跑的时刻：比它旧的判决 / 日志一律不认（见 `_fresh`）。
    """
    found = [sig for sig in (_probe_codebuddy(card, root, now, since),
                             _probe_codearts(card, root, now, since)) if sig is not None]
    if not found:
        return CardSignal(card, BLIND, detail="两条池里都看不到这张卡的信号")
    for kind in (FINISHED, DEAD, RUNNING):
        for sig in found:
            if sig.kind == kind:
                return sig
    return found[0]


# ---------------------------------------------------------------- 完工事件（卡 E7）
def diag_dir(root: Path) -> Path:
    """判决 / 通知 / 登记表住哪：`<root>/gates/diag`（与 `wb_dispatch` / `wb_notify` 同一处）。"""
    return Path(root) / "gates" / "diag"


def notifications_path(root: Path) -> Path:
    return diag_dir(root) / "notifications.jsonl"


def registry_path(root: Path) -> Path:
    """合用看守的登记表（`refcount` / `cards` / pid / 心跳）—— 抗崩溃的唯一落点。"""
    return diag_dir(root) / "watch-registry.json"


def done_path(root: Path, card: str) -> Path:
    """一张卡的完工事件（一行 JSON）。★ 名字是卡 E7 钉的：`wb-<卡>.done`。"""
    return diag_dir(root) / f"wb-{card}.done"


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def _parse_iso(value: object) -> float | None:
    """ISO8601 串 → 秒；空串 / 不是串 / 解不出 ⇒ None（**不许**当「刚发过心跳」）。"""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip()).timestamp()
    except ValueError:
        return None


def append_notification(root: Path, row: dict) -> Path:
    """往 `gates/diag/notifications.jsonl` 追加**一行**（与 `wb_notify` 同一份文件、同一种行）。

    ★ 行里带 `card` + `verdict` 时，`wb_notify._load_existing()` 的幂等键正好认得它 ⇒
      守护进程不会为同一张卡再写第二行（复用既有机制，不另造一套）。
    """
    path = notifications_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as out:
        out.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def _latest_rel(root: Path, card: str, suffix: str) -> str:
    """这张卡最新一份产物的**仓库相对路径**；没有 ⇒ 空串（不编一个不存在的路径）。"""
    arts = card_artifacts(diag_dir(root), card, suffix)
    if not arts:
        return ""
    try:
        return arts[-1].relative_to(root).as_posix()
    except ValueError:                       # root 不是它的祖先（独立拷贝的树）⇒ 给绝对路径
        return arts[-1].as_posix()


def _report_pointer(root: Path, card: str) -> str:
    """判决对应的摘要**位置**（可能还没落盘 —— 通知只指向它，不假装它在）。"""
    verdicts = card_artifacts(diag_dir(root), card, _CB_VERDICT_SUFFIX)
    if verdicts:
        return wb_notify._report_rel(verdicts[-1])
    return f"gates/diag/wb-{card}.report.md"


def _task_of(root: Path, card: str) -> str:
    """卡号 → 台账号（`T-AG…`）。读不到队列就留空 —— ★ 不猜。"""
    try:
        backlog = load_sharded_backlog(
            path=Path(root) / "docs" / "workbacklog.toml",
            shard_directory=Path(root) / "docs" / "backlog",
        )
    except Exception:  # noqa: BLE001 —— 队列坏了不该让看守崩（task 只是留痕字段）
        return ""
    for item in backlog.cards:
        if item.id == card:
            return item.task
    return ""


def _verdict_text(root: Path, card: str, *, fallback: str, now: float,
                  since: float | None = None) -> tuple[str, str]:
    """（判决文本, 结束时刻）：从判决文件现读；读不到用 `fallback` + 当下时刻。"""
    for path in reversed(_fresh(card_artifacts(diag_dir(root), card, _CB_VERDICT_SUFFIX), since)):
        parsed = wb_notify._parse_verdict(path)
        if parsed is not None:
            return parsed
    return fallback, _iso(now)


def write_card_event(root: Path, card: str, state: str, *,
                     verdict: str = "", exit_code: int | None = None,
                     now: float | None = None) -> dict:
    """往通知流里追加一张卡的事件（`done` / `dead` / `timeout`）—— 不带 `.done` 文件。"""
    now = time.time() if now is None else now
    row: dict = {"at": _iso(now), "card": card, "state": state,
                 "log": _latest_rel(root, card, _LOG_SUFFIX),
                 "report": _report_pointer(root, card)}
    if verdict:
        row["verdict"] = verdict
    if exit_code is not None:
        row["exit_code"] = exit_code
    append_notification(root, row)
    return row


def write_done_event(root: Path, card: str, *, task: str = "",
                     now: float | None = None, since: float | None = None) -> dict | None:
    """判决出现时落**完工事件**：`wb-<卡>.done`（一行 JSON）+ 通知流一行。

    ★ 只认磁盘判决：`probe_card()` 不是「收工」⇒ 返回 None（**看守不猜成功**）。
    ★ `since` = 这一轮开跑的时刻：比它旧的判决不算这一轮的（旧件不许冒充，见 `_fresh`）。
    ★ 幂等：`.done` 已在 ⇒ 原样返回，**不再**追加第二行通知（看守重启 / 两形态并发都不重复写）。
    """
    root = Path(root)
    now = time.time() if now is None else now
    path = done_path(root, card)
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return existing if isinstance(existing, dict) else None
    sig = probe_card(card, root, now, since)
    if sig.kind != FINISHED:
        return None
    verdict, at = _verdict_text(root, card, fallback=sig.verdict_line or "正常收工",
                                now=now, since=since)
    done = {
        "card": card,
        "task": task or _task_of(root, card),
        "exit_code": sig.exit_code,
        "at": at,
        "log": _latest_rel(root, card, _LOG_SUFFIX),
        "report": _report_pointer(root, card),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(done, ensure_ascii=False) + "\n", encoding="utf-8")
    append_notification(root, {**done, "state": STATE_DONE, "verdict": verdict})
    return done


def write_timeout_event(root: Path, card: str, *, now: float | None = None) -> dict:
    """超时**没判决** ⇒ 写 `state:"timeout"`（**不写** `.done`：没做完就没有完工事件）。"""
    return write_card_event(root, card, STATE_TIMEOUT, now=now)


def write_batch_done(root: Path, cards: Iterable[str], *, now: float | None = None) -> dict:
    """合用看守计数归 0 ⇒ 一条「这一批做完了」（整批一次通知）。"""
    row = {"at": _iso(time.time() if now is None else now), "state": STATE_BATCH_DONE,
           "cards": sorted(str(c) for c in cards)}
    append_notification(root, row)
    return row


def write_stale_event(root: Path, event: dict) -> dict:
    """把 `registry_stale()` 给出的那条 `watcher-stale` 落下（它自己不带落盘副作用）。"""
    append_notification(root, event)
    return event


# ---------------------------------------------------------------- 登记表（引用计数）
def read_registry(root: Path) -> dict:
    """读登记表；没有 / 坏了 ⇒ 空 dict（**不许**把「读不到」当成「没有卡在盯」去清账）。"""
    path = registry_path(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_registry(root: Path, data: dict) -> Path:
    path = registry_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _card_state(reg: dict) -> dict[str, str]:
    cards = reg.get("cards")
    if not isinstance(cards, dict):
        return {}
    return {str(k): str(v) for k, v in cards.items()}


def _card_since(reg: dict) -> dict[str, float]:
    """每张卡**这一轮**的开跑时刻（`since`）—— 旧证据的切割线，按卡存（抗重启）。"""
    raw = reg.get("since")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in raw.items():
        try:
            out[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def _refcount(states: dict[str, str]) -> int:
    """引用计数 = **还没出判决**的卡数（现算，不存内存变量）。"""
    return sum(1 for value in states.values() if value == STATE_WATCHING)


def _resolution(card: str, root: Path, now: float,
                *, since: float | None = None) -> tuple[str, str]:
    """这张卡出结论了吗：`(登记态, 额度原因)`；没结论 ⇒ `(watching, "")`。

    ★ 额度原因非空 ⇒ 判死的原因是额度（事件写 `state:"quota"`，处置与「卡做错了」不同）。
    """
    sig = probe_card(card, root, now, since)
    if sig.kind == FINISHED:
        return STATE_DONE, ""
    if sig.kind == DEAD:
        return STATE_DEAD, sig.quota
    return STATE_WATCHING, ""


def _resolved(card: str, root: Path, now: float, *, since: float | None = None) -> str | None:
    """这张卡出结论了吗：`done` / `dead` / None（没有判决 = 还没完）。"""
    got = _resolution(card, root, now, since=since)[0]
    return None if got == STATE_WATCHING else got


def _dead_event(root: Path, card: str, quota: str, *, now: float) -> None:
    """判死落一行通知：额度类写 `state:"quota"`（带「额度：…」），别的仍是 `state:"dead"`。"""
    if quota:
        write_card_event(root, card, STATE_QUOTA, verdict=f"额度：{quota}", now=now)
    else:
        write_card_event(root, card, STATE_DEAD, now=now)


def register_cards(root: Path, cards: Iterable[str], *, now: float | None = None,
                   since: float | None = None) -> dict:
    """派活时登记：每派一张卡引用计数 +1（已出判决的卡不算未完成）。

    ★ 只动 `cards` / `since` / `refcount`：**心跳与 pid 归看守写** ——
      派活器写心跳等于冒充「看守还活着」。
    ★ `since`（可选）= 这一轮开跑的时刻，比它旧的判决 / 日志不算数；默认取 `now`。
      已登记过的卡保留**最早**那个切点（重复登记不许把切点往后挪）。
    """
    root = Path(root)
    now = time.time() if now is None else now
    cutoff = now if since is None else float(since)
    reg = read_registry(root)
    states = _card_state(reg)
    cutoffs = _card_since(reg)
    for raw in cards:
        card = str(raw).strip()
        if not card:
            continue
        if card not in cutoffs:
            cutoffs[card] = cutoff
        states[card] = _resolved(card, root, now, since=cutoffs[card]) or STATE_WATCHING
    reg.update({"cards": states, "since": cutoffs, "refcount": _refcount(states)})
    reg.setdefault("pid", None)
    reg.setdefault("heartbeat", "")
    write_registry(root, reg)
    return reg


def rebuild_registry(root: Path, *, now: float | None = None,
                     pid: object = _KEEP, heartbeat: object = _KEEP) -> dict:
    """看守重启：**从磁盘重建**计数（已出判决的卡不算未完成），不靠内存变量。

    `pid` / `heartbeat` 传值就覆盖，不传（默认哨兵）就保持原样 —— 派活器恢复死看守时
    要显式清心跳（`heartbeat=""`），让「待启动」和「还活着」分得开。
    """
    root = Path(root)
    now = time.time() if now is None else now
    reg = read_registry(root)
    states = _card_state(reg)
    since = _card_since(reg)
    for card in list(states):
        states[card] = _resolved(card, root, now, since=since.get(card)) or STATE_WATCHING
    reg["cards"] = states
    reg["since"] = since
    reg["refcount"] = _refcount(states)
    if pid is not _KEEP:
        reg["pid"] = pid
    else:
        reg.setdefault("pid", None)
    if heartbeat is not _KEEP:
        reg["heartbeat"] = heartbeat
    else:
        reg.setdefault("heartbeat", "")
    write_registry(root, reg)
    return reg


def watcher_alive(root: Path, *, timeout: float = DEFAULT_TIMEOUT,
                  now: float | None = None) -> bool:
    """合用看守还活着吗：还有卡在盯 + **心跳没过期**。

    ★ 不探 PID：Windows 上没有安全的「探活」（`os.kill(pid, 0)` 会真把进程杀掉，坑 27）——
      判据只用**心跳**（看守每拍都落一次）。
    """
    now = time.time() if now is None else now
    reg = read_registry(root)
    if _refcount(_card_state(reg)) <= 0:
        return False
    beat = _parse_iso(reg.get("heartbeat"))
    return beat is not None and (now - beat) <= timeout


def registry_stale(root: Path, *, timeout: float,
                   now: float | None = None) -> dict | None:
    """看守自己死了吗：心跳超过 `timeout` 且**还有卡没判决** ⇒ 一条 `watcher-stale` 事件。

    ★ 心跳为空 = 刚登记、看守还没起来 ⇒ **不算** stale（那是「待启动」，不是「死了」）。
    ★ 全都有判决 ⇒ 也不算（批已经完了，只是没人来收尾）。
    """
    now = time.time() if now is None else now
    reg = read_registry(root)
    states = _card_state(reg)
    pending = sorted(card for card, value in states.items() if value == STATE_WATCHING)
    if not pending:
        return None
    beat = _parse_iso(reg.get("heartbeat"))
    if beat is None or (now - beat) <= timeout:
        return None
    return {"at": _iso(now), "state": STATE_STALE,
            "heartbeat": str(reg.get("heartbeat") or ""), "pid": reg.get("pid"),
            "cards": pending}


def shared_tick(root: Path, *, now: float | None = None,
                emit: Callable[[str], None] = print) -> tuple[list[str], int]:
    """合用看守走**一拍**：把已出判决的卡从计数里减掉；归 0 时写 `batch-done`。

    返回（这一拍新出结论的卡, 剩余的引用计数）。★ 中间态**逐张落盘** —— 主控随时能查。
    """
    root = Path(root)
    now = time.time() if now is None else now
    reg = read_registry(root)
    states = _card_state(reg)
    since = _card_since(reg)
    before = _refcount(states)
    resolved: list[str] = []
    for card in sorted(states):
        if states[card] != STATE_WATCHING:
            continue
        got, quota = _resolution(card, root, now, since=since.get(card))
        if got == STATE_WATCHING:
            continue
        states[card] = got
        resolved.append(card)
        if got == STATE_DONE:
            done = write_done_event(root, card, now=now, since=since.get(card))
            where = done_path(root, card).name if done is not None else "（判决读不出详情）"
            emit(f"[完 ] 卡 {card} 出判决 → 写 {where} + 通知流一行")
        else:
            _dead_event(root, card, quota, now=now)
            why = f"额度：{quota}" if quota else "没跑完就断了"
            emit(f"[断 ] 卡 {card} 判死（{why}）→ 通知流一行（**不算成功**）")
    refcount = _refcount(states)
    reg.update({"cards": states, "since": since, "refcount": refcount,
                "heartbeat": _iso(now)})
    reg.setdefault("pid", None)
    write_registry(root, reg)
    if before > 0 and refcount == 0:
        write_batch_done(root, states, now=now)
        emit(f"[OK ] 计数归 0 —— 这一批做完了（{len(states)} 张）")
    return resolved, refcount


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


def _heartbeat_shared(elapsed: float, states: dict[str, str]) -> str:
    """合用看守的心跳：还要盯几张 + 每张卡此刻的登记状态。"""
    where = " · ".join(f"{card}={states[card]}" for card in sorted(states))
    return f"[心跳] 已盯 {elapsed / 60:.1f} 分钟 | 还差 {_refcount(states)} 张 | {where}"


def watch(cards: Iterable[str], *,
          root: Path | None = None,
          timeout: float = DEFAULT_TIMEOUT,
          interval: float = DEFAULT_INTERVAL,
          clock: Callable[[], float] = time.time,
          sleep: Callable[[float], None] = time.sleep,
          emit: Callable[[str], None] = print,
          write_done: bool = False,
          since: float | None = None) -> int:
    """真轮询直到全部收工 / 有卡判死 / 超时；返回退出码（0 / 3 / 4）。

    `clock` 与 `sleep` 可注入（测试用假时间源，**不真等**）—— 判据本身仍是现读文件。
    ★ `write_done=True`（CLI 的 `--write-done`）才落 `.done` / 通知流；默认**只读**。
    ★ `since`（CLI 的 `--since`）= 这一轮开跑的时刻：旧判决 / 旧日志不认（见 `_fresh`）。
    """
    root = Path(root) if root is not None else ROOT
    target = list(cards)
    written: set[str] = set()
    start = clock()
    while True:
        now = clock()
        signals = {card: probe_card(card, root, now, since) for card in target}
        if all(sig.kind == FINISHED for sig in signals.values()):
            if write_done:
                for card in target:
                    if card not in written:
                        write_done_event(root, card, now=now, since=since)
                        written.add(card)
            for line in _conclusion_lines(target, signals):
                emit(line)
            emit(f"[OK ] 全部收工（{len(target)} 张）")
            return EXIT_FINISHED
        dead = [card for card in target if signals[card].kind == DEAD]
        if dead:
            if write_done:
                for card in dead:
                    _dead_event(root, card, signals[card].quota, now=now)
            for line in _conclusion_lines(target, signals):
                emit(line)
            said = "、".join(f"{card}（额度：{signals[card].quota}）" if signals[card].quota
                            else card for card in dead)
            emit(f"[FAIL] 有卡判死（没跑完就断了）：{said}")
            return EXIT_DEAD
        elapsed = now - start
        if elapsed >= timeout:
            unfinished = [card for card in target if signals[card].kind != FINISHED]
            if write_done:
                for card in unfinished:
                    write_timeout_event(root, card, now=now)
            for line in _conclusion_lines(target, signals):
                emit(line)
            emit(f"[超时] 已等 {elapsed / 60:.1f} 分钟（上限 {timeout / 60:.1f} 分钟）—— "
                 f"还没完的卡：{'、'.join(unfinished) or '（无）'}（没判决 **不算** 成功）")
            return EXIT_TIMEOUT
        emit(_heartbeat(elapsed, target, signals))
        sleep(min(interval, max(0.0, timeout - elapsed)))


def watch_shared(*, root: Path | None = None,
                 timeout: float = DEFAULT_TIMEOUT,
                 interval: float = DEFAULT_INTERVAL,
                 clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep,
                 emit: Callable[[str], None] = print,
                 pid: int | None = None) -> int:
    """**合用看守**：全局一份，引用计数归 0 就退（不是常驻守护 —— 一次派活一份，工人收工它退）。

    ★ 启动时**从磁盘重建**计数（`rebuild_registry`）：已出判决的卡不算未完成 ⇒
      看守重启两次也不会把同一张卡再算一遍。
    ★ 每拍心跳落 `gates/diag/watch-registry.json`；超时没判决只写 `state:"timeout"`。
    """
    root = Path(root) if root is not None else ROOT
    started = clock()
    reg = rebuild_registry(root, now=started,
                           pid=os.getpid() if pid is None else pid,
                           heartbeat=_iso(started))
    if not _card_state(reg):
        emit("[看 ] 登记表里没有要盯的卡 —— 没东西可盯（先让派活器登记）")
        return EXIT_USAGE
    while True:
        now = clock()
        _, refcount = shared_tick(root, now=now, emit=emit)
        states = _card_state(read_registry(root))
        if refcount == 0:
            return EXIT_FINISHED
        elapsed = now - started
        if elapsed >= timeout:
            unfinished = sorted(c for c, v in states.items() if v == STATE_WATCHING)
            for card in unfinished:
                write_timeout_event(root, card, now=now)
            emit(f"[超时] 已等 {elapsed / 60:.1f} 分钟（上限 {timeout / 60:.1f} 分钟）—— "
                 f"还没判决的卡：{'、'.join(unfinished) or '（无）'}（没判决 **不算** 成功）")
            return EXIT_TIMEOUT
        emit(_heartbeat_shared(elapsed, states))
        sleep(min(interval, max(0.0, timeout - elapsed)))


# ---------------------------------------------------------------- CLI
def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="一次盯多张卡，收工就出结论（真轮询 + 心跳 + 硬超时；"
                    "one 形态默认只读，shared 形态要落登记表）")
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
    # ★ 卡 E7：看守形态与完工事件。默认 `one`（推送粒度最细：一张卡一次通知）。
    ap.add_argument("--mode", choices=("one", "shared"), default="one",
                    help="看守形态：one=专属（每张卡一个看守，出判决就退；默认）；"
                         "shared=全局一份合用看守（引用计数 +1 / 出判决 -1 / 归 0 写 batch-done）")
    ap.add_argument("--write-done", action="store_true",
                    help="判决出现时写 gates/diag/wb-<卡>.done 并追加 notifications.jsonl"
                         "（不给 = 只读，一个字不写）")
    ap.add_argument("--since", type=float, default=None,
                    help="这一轮开跑的时刻（epoch 秒）：比它旧的判决 / 日志一律不认"
                         "（派活器会给 —— 旧件不许冒充当前状态）")
    args = ap.parse_args(argv)

    root = Path(args.root)
    if args.batch:
        try:
            cards = resolve_batch(args.batch)
        except BatchWatchError as exc:
            print(f"[FAIL] {exc}", file=sys.stderr)
            return EXIT_USAGE
    else:
        cards = [c.strip() for c in args.cards if c.strip()]
    print(f"[看 ] 盯 {len(cards)} 张卡：{'、'.join(cards)}（{args.mode} 形态"
          f"；超时 {args.timeout / 60:.0f} 分钟 / 每 {args.interval:.0f} 秒查一次）", flush=True)
    if args.mode == "shared":
        # ★ 判据 8：看守自己死了不算完 —— 心跳过期且还有卡没判决 ⇒ 写事件并**退非零**，
        #   绝不装作还在盯（主控看到退出码就知道「这批没人守了」）。
        stale = registry_stale(root, timeout=args.timeout)
        if stale is not None:
            write_stale_event(root, stale)
            print(f"[FAIL] 上一个合用看守心跳停在 {stale['heartbeat'] or '（空）'}"
                  f"（超过 {args.timeout:.0f}s），这些卡还没判决："
                  f"{'、'.join(stale['cards'])} —— 已写 watcher-stale 事件。"
                  "★ 别把「没人盯」当成「还在盯」：要么重派一张卡让派活器重建看守，"
                  "要么确认这些卡已收工。", file=sys.stderr, flush=True)
            return EXIT_STALE
        register_cards(root, cards, since=args.since)
        return watch_shared(root=root, timeout=args.timeout, interval=args.interval)
    return watch(cards, root=root, timeout=args.timeout, interval=args.interval,
                 write_done=args.write_done, since=args.since)


if __name__ == "__main__":
    raise SystemExit(main())
