r"""一份读数（卡 207 · T-G316）—— 只读，唯一读数器。

为什么有它：主控 2026-10-13 定的方案里，**同一批读数会有多个「面」**（会话内的 MCP、
timeflow 视图、禅道）。按本仓教义（「四个面集中到一个点」），必须先有**一个只读读数器**，
否则同一件事各读各的、口径必漂。现在这些读数散在各处（`landing.py` 读队列与台账、
`wb_state.py` 读 HEAD/锁/进程、`wb_dash.py` 读 `wb-*.jsonl`、`wb_flow.py` 读队列算流量、
`pool_mcp.py` 读队列+判决+租约）—— **没有任何一处把它们收成一份**。本工具就是那一份。

一条命令产出一份结构化读数（`--json` 给机器、`--report` 给人读）。**七块**，每块都写清来源：

1. `cards`     —— 队列全貌（来源 `docs/workbacklog.toml`）
2. `gates`     —— 最近一次门禁（来源 `gates/last.json`）
3. `verdicts`  —— 每张卡的判决 / 摘要（来源 `gates/diag/wb-<卡>.verdict.txt` 与 `.report.md`）
4. `leases`    —— 租约（行内 dead 标死活；来源 `gates/diag/pool-registry.json`）
5. `fences`    —— 任务栅栏（来源 `gates/diag/batch/*.toml`）
6. `worktrees` —— 卡树清单（来源 `git worktree list`）
7. `holds`     —— 整窗用量估算（来源账号账本 `infra/pool/accounts.toml`，经
   `tools/pool/holds_wiring.py`）

★ **只读**：不杀进程、不占端口、不调 git 的写命令；写的只有两样（都在 gitignore 的
  `gates/diag/` 区）：连续块的 last-good 快照（`pipeline-view-lastgood.json`，卡 249）
  与读数缓存（`readcache/<块>.json`，卡 255）。
★ **内容哈希缓存**（卡 255 · T-G376）：文件型块的读数按「来源文件 mtime_ns + size +
  内容 sha256」做键，命中就**不重算**；缓存落 `gates/diag/readcache/<块>.json`。
  键里带内容哈希 ⇒ 内容变一个字节就重算；来源**缺失/坏掉**时**不查缓存**（仍走
  「缺什么说什么」/ STALE-WHILE-ERROR）；命中/重算与峰值内存只进 `--report`，
  **不进 `--json`**（冷跑/热跑逐字节相同）。库调用方只读缓存、不写（`_REMEMBER` 才写）。
★ **git 只调两次**（卡 255）：`git worktree list --porcelain` + 读数根上的
  `git status --porcelain=v1 --branch`；不逐棵 worktree 起 status（其余棵的 dirty 记
  null + 注，缺什么说什么）。调用次数写进 `--report`。★ 卡 E115：`--report` 另外多
  一条 `git rev-list --count` 算「落后几个提交」（墙钟与那条 git 都只进 `--report`，
  `--json` 一个字都不许有）。
★ **BLOCKS 声明表是唯一口径源**（卡 249 · T-G370）：七块的块名 / 来源 / 缺源标注语 /
  字段清单都在模块级 `BLOCKS` 里，`read_*()` 与 `_report_*()` 都从它取（不许各写一份）；
  `--json` 每块带 `<块>_source` 回声、`--report` 每块头带同一句来源 —— 两个出口对得上。
★ **连续块 vs 静态块**：`BLOCKS` 里 `continuous=True` 的只有 `gates` / `leases` ——
  读数失败时若有上一份好读数（STALE-WHILE-ERROR，快照见 `LASTGOOD_REL`），返回
  上一份好值 + `<块>_stale`（`error_code` + `captured_at`）；墙钟算出的 `stale_for_s`
  只进 `--report`、不进 `--json`（保幂等）。静态块保留「缺什么说什么」：
  null + 声明表标注语，不许一刀切改成 last-good。
★ **缺什么说什么**：来源文件缺失/坏掉 ⇒ 那一块**明确标注**（如 `"gates": null` +
  `"gates_note": "没有 gates/last.json"`），**不许**用空对象冒充、**不许**猜。
★ **不 import 业务代码**（`src/timeflow/**`）；只用标准库 + 读文件 + 调 `git`（带 `NO_WINDOW`）。
★ 幂等：同样的输入连跑两次，`--json` 逐字节相同（**不许**写时间戳/随机序）。

用法：
    python -X utf8 tools/pipeline_view.py --report
    python -X utf8 tools/pipeline_view.py --json
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import subprocess
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

import tomllib
import wb_plan  # 台账分片（卡 E89）：分片目录 / 分片读法只此一份

#: ★ 卡 E115：判「这条租约死了没有」的判据只有一份（`tools/pool/registry.py`）——
#: 不许在这儿抄一份；包不在 sys.path 时就如实说「判不了」（`dead=None`），不许猜。
try:
    from pool import registry as _pool_registry
except ImportError:  # pragma: no cover - 工具目录不在 sys.path 的调用方
    _pool_registry = None

#: ★ 卡 A369（T-AG654）：整窗用量估算的**唯一**搬运层（账本 → 窗口 → 判据）。
#:   `tools/pool/holds.py` 是判据层（本文件与它都不许再抄一遍算式）；本文件只负责
#:   把它摆成第七块读数。包不在 sys.path 时如实说「读不了」，不许猜。
try:
    from pool import holds_wiring as _holds_wiring
except ImportError:  # pragma: no cover - 工具目录不在 sys.path 的调用方
    _holds_wiring = None

#: ★ 卡 A392（T-AG683）：上报账的读数**只在这里**调（`usage_ingest.reported_summary`）。
#:   ★ **不许**把这个 import 搬到 `tools/pool/holds_wiring.py` —— 它在派活留痕行上被调用，
#:   上报数字从那里流出去就等于进了派活链。包不在 sys.path 时如实说「不知道」（0 / None）。
try:
    from pool import usage_ingest as _usage_ingest
except ImportError:  # pragma: no cover - 工具目录不在 sys.path 的调用方
    _usage_ingest = None

ROOT = Path(__file__).resolve().parent.parent
#: 这一次读数用的根（`--report` 的 git rev-list 要在这儿跑；`--json` 不受影响）。
_ROOT_USED: Path = ROOT
NO_WINDOW: dict[str, int] = {"creationflags": 0x08000000} if os.name == "nt" else {}

BACKLOG_REL = Path("docs") / "workbacklog.toml"
GATES_LAST_REL = Path("gates") / "last.json"
DIAG_REL = Path("gates") / "diag"
REGISTRY_REL = DIAG_REL / "pool-registry.json"
BATCH_REL = DIAG_REL / "batch"
# 连续块（gates/leases）的 last-good 快照（卡 249）：失败时「坏读数不许抹掉好读数」。
LASTGOOD_REL = DIAG_REL / "pipeline-view-lastgood.json"
# 读数缓存（卡 255）：按「来源文件 mtime_ns + size + 内容 sha256」命中，命中就不重算。
# ★ 只放 gitignore 的 gates/diag/ 区，**不许**放 docs/。
READCACHE_REL = DIAG_REL / "readcache"

#: 缓存文件的格式版本：字段形状变了就抬，旧缓存自然失效（不猜旧格式）。
#: ★ 卡 E115 抬到 2：gates 多了 at/dirty/branch、leases 多了 dead、verdicts 多了
#:   attempts/selected —— 旧缓存里还是老形状，不抬版本号真仓会继续读旧字段。
_CACHE_SCHEMA = 2
#: 算内容哈希的分块大小（流式，不把大文件整块读进内存）。
_HASH_CHUNK = 64 * 1024

#: ★ 卡 A369：账本读不到时第七块的说法。与 `tools/pool/holds_wiring.py` 的
#:   `MISSING_LEDGER_NOTE` **逐字同一句**（`tests/test_pipeline_view_holds.py` 钉这个
#:   等式，免得两处各说各的）。
HOLDS_MISSING_NOTE = "没有账号账本（infra/pool/accounts.toml 或 TF_ACCOUNTS_TOML）"

#: 判决/摘要文件名 → (卡号, 尝试标记)。尝试标记只有三种写法：.r2 / .killed / .attempt1。
#: ★ 卡 E115：旧正则的 (.+?) 会把尝试标记吞进卡号 —— 「120.killed」被当成另一张卡，
#:   同一张卡的第二次尝试（「143.r2」）反而被同一个键覆盖掉。
_ATT_PAT = r"(?:[.](?P<att>r[0-9]+|killed|attempt[0-9]+))?"
_VERDICT_RE = re.compile(rf"^wb-(?P<card>[^./]+?){_ATT_PAT}[.]verdict[.]txt$")
_REPORT_RE = re.compile(rf"^wb-(?P<card>[^./]+?){_ATT_PAT}[.]report[.]md$")
#: 判决首行里的结束时刻（与 `tools/wb_notify.py` 的「结束于=」同一口径）。
_ENDED_AT_RE = re.compile(r"结束于=([^ ]+)")


# ================================================================ BLOCKS：七块声明表
# ★ 唯一口径源（卡 249 · T-G370）：read_*() 与 _report_*() 都从这张表取
#   （块名、来源、缺源标注语、字段清单）—— 不许再各写一份。
#   --json 的 <块>_source 回声与 --report 每块头的「来源 …」都出自这里。
# ★ continuous=True = 连续监测块：读数失败且有上一份好读数时走 STALE-WHILE-ERROR
#   （快照 LASTGOOD_REL）；False = 静态块（一次性读数）：保留「缺什么说什么」
#   （null + missing_note），不许一刀切改成 last-good。
BLOCKS: tuple[dict, ...] = (
    {"id": "cards",
     "source": "docs/workbacklog.toml 与分片 docs/backlog/*.toml",
     "missing_note": "没有 docs/workbacklog.toml（也没有 docs/backlog/*.toml 分片）",
     "continuous": False,
     "fields": ("cards", "cards_reviewed"),
     "row_fields": ("id", "task", "title", "tree", "spec", "files",
                    "depends", "risk", "status")},
    {"id": "gates", "source": "gates/last.json",
     "missing_note": "没有 gates/last.json", "continuous": True,
     "fields": ("gates",),
     # ★ 卡 E115：生产者（scripts/run_gates.py）早写了 at/dirty/branch，读数器一直没搬。
     "row_fields": ("ok", "rev", "at", "dirty", "branch", "items")},
    {"id": "verdicts", "source": "gates/diag/wb-*.verdict.txt / .report.md",
     "missing_note": "没有 gates/diag 目录", "continuous": False,
     "fields": ("verdicts",),
     # ★ 卡 E115：一卡一行 + 每次尝试一行（attempts），同卡的两次尝试不许互相覆盖。
     "row_fields": ("card", "has_verdict", "verdict_first_line", "has_report",
                    "attempts", "selected")},
    {"id": "leases", "source": "gates/diag/pool-registry.json",
     "missing_note": "没有 gates/diag/pool-registry.json", "continuous": True,
     "fields": ("leases",),
     # ★ 卡 E115：死租约不从表里抹掉，只加一列 dead（None = 判不出）。
     "row_fields": ("card", "tree", "files", "owner", "at", "ttl_seconds", "dead")},
    {"id": "fences", "source": "gates/diag/batch/*.toml",
     "missing_note": "没有 gates/diag/batch 目录", "continuous": False,
     "fields": ("fences",),
     "row_fields": ("id", "on_complete", "members")},
    {"id": "worktrees", "source": "git worktree list",
     "missing_note": "git worktree list 没有输出", "continuous": False,
     "fields": ("worktrees",),
     "row_fields": ("path", "head", "branch", "dirty")},
    # ★ 卡 A369（T-AG654）：整窗用量估算。**为什么不进 continuous**：它不是「监测
    #   一块连续的东西」，而是账本每行的一次换算 —— 账本读不到时就得说「没有账本」，
    #   不许拿上一份好读数冒充「现在的整窗」。
    {"id": "holds", "source": "infra/pool/accounts.toml 经 tools/pool/holds_wiring.py",
     "missing_note": HOLDS_MISSING_NOTE, "continuous": False,
     "fields": ("holds",),
     # ★ 卡 A369：why 是判据层的**原串**（"-" / "low" / "log" / "none" / "credits" /
     #   ""），why_text 是人话 —— 两个都要在，否则「估不出来」变成沉默。
     # ★ 卡 A392：reported_tokens / reported_priced 是**另加**的两列（上报账单列）——
     #   tokens / cost / priced 三列的语义一个字不动（tokens 仍不含上报）。
     "row_fields": ("account", "platform", "model", "used_percent", "why",
                    "why_text", "tokens", "cost", "priced", "since",
                    "reported_tokens", "reported_priced")},
)

_SRC: dict[str, dict] = {b["id"]: b for b in BLOCKS}


# ================================================================ last-good 快照（卡 249）


#: ★ 卡 249：last-good 快照只在**监测路径**（CLI `main()`）里写；
#: 库调用方（`build_inbox()` 那种只读路径）默认不写 ⇒ 只读硬判据仍然成立 ✓。
#: ★ 卡 255：读数缓存同规矩 —— 库调用方**只读缓存**，只有 `_REMEMBER` 才写。
_REMEMBER = False

#: 本次 `build_reading()` 的账：git 调了几次 / 缓存命中与重算的块名 / 峰值内存。
#: ★ 只进 `--report`，**不进 `--json`**（否则冷跑与热跑不可能逐字节相同）。
_GIT_CALLS = 0
_CACHE_HITS: list[str] = []
_CACHE_MISSES: list[str] = []
_CACHE_SKIPPED: list[str] = []  # 没有可做键的来源（缺文件/坏目录）⇒ 不查也不写缓存
_PEAK_BYTES = 0


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _load_lastgood(root: Path) -> dict:
    """读 last-good 快照；没有/坏了 ⇒ 空表（STALE-WHILE-ERROR 退化为「缺什么说什么」）。"""
    try:
        data = json.loads((root / LASTGOOD_REL).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    blocks = data.get("blocks") if isinstance(data, dict) else None
    return blocks if isinstance(blocks, dict) else {}


def _save_lastgood_block(root: Path, bid: str, data: object) -> None:
    """把某连续块的好读数落进快照；写不进去就算了（不许因快照失败而红）。"""
    blocks = dict(_load_lastgood(root))
    blocks[bid] = {"captured_at": _now_iso(), "data": data}
    snap = {"schema": 1, "blocks": blocks}
    try:
        path = root / LASTGOOD_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snap, ensure_ascii=False, indent=2, sort_keys=True),
                        encoding="utf-8")
    except OSError:
        pass


def _stale_hit(root: Path, bid: str, error_code: str) -> dict | None:
    """取某连续块的上一份好读数；有 ⇒ {data, stale}，没有 ⇒ None。"""
    hit = _load_lastgood(root).get(bid)
    if not isinstance(hit, dict) or "data" not in hit:
        return None
    return {"data": hit["data"],
            "stale": {"error_code": error_code,
                      "captured_at": str(hit.get("captured_at", ""))}}


def _continuous_out(root: Path, bid: str, payload: object,
                    note: str, error_code: str) -> dict:
    """连续块的统一出口：好读数落快照；坏读数有上一份好值 ⇒ last-good + error_code。"""
    src = _SRC[bid]["source"]
    if payload is not None:
        if _REMEMBER:
            _save_lastgood_block(root, bid, payload)
        return {bid: payload, f"{bid}_source": src}
    hit = _stale_hit(root, bid, error_code)
    if hit is not None:
        return {bid: hit["data"], f"{bid}_stale": hit["stale"], f"{bid}_source": src}
    return {bid: None, f"{bid}_note": note, f"{bid}_source": src}


# ================================================================ 内容哈希缓存（卡 255）


def _sha256_file(path: Path) -> str:
    """流式算内容哈希（64 KiB 一块）—— 大文件也不整块读进内存。"""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(root: Path, paths: list[Path]) -> tuple[str, list] | None:
    """来源文件的键（mtime_ns + size + 内容 sha256）与逐文件明细。

    任何一个文件读不到 ⇒ None（**不查缓存**，仍走「缺什么说什么」/ last-good）。
    """
    rows: list[list] = []
    for path in sorted(paths, key=lambda p: p.as_posix()):
        try:
            st = path.stat()
            rel = path.relative_to(root).as_posix()
            rows.append([rel, st.st_mtime_ns, st.st_size, _sha256_file(path)])
        except (OSError, ValueError):
            return None
    if not rows:
        return None
    raw = json.dumps(rows, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest(), rows


def _cache_path(root: Path, bid: str) -> Path:
    return root / READCACHE_REL / f"{bid}.json"


def _cache_load(root: Path, bid: str) -> dict | None:
    """读某块的缓存；没有 / 坏了 / 版本不对 ⇒ None（缓存不是判据，不许因它红）。"""
    try:
        data = json.loads(_cache_path(root, bid).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != _CACHE_SCHEMA:
        return None
    if not isinstance(data.get("key"), str) or "data" not in data:
        return None
    return data


def _cache_put(root: Path, bid: str, key: str, rows: list, payload: dict) -> None:
    """写回缓存（原子替换）；写不进去就算了 —— 缓存失败不许把一次好读数弄红。"""
    if not _REMEMBER:
        return
    path = _cache_path(root, bid)
    snap = {"schema": _CACHE_SCHEMA, "key": key, "sources": rows, "data": payload}
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(snap, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()


def _cacheable(bid: str, payload: object) -> bool:
    """只有**成功**读数才配进缓存：失败/坏源/stale 一律不缓存（它们必须每次重走原路）。"""
    if not isinstance(payload, dict):
        return False
    if f"{bid}_note" in payload or f"{bid}_stale" in payload:
        return False
    return payload.get(bid) is not None


def _cached(root: Path, bid: str, paths: list[Path],
            compute: Callable[[], dict]) -> dict:
    """文件型块的统一入口：键命中 ⇒ 直接返回缓存读数（不重算）；否则重算并按需写回。"""
    fp = _fingerprint(root, paths)
    key = fp[0] if fp is not None else None
    if key is None:
        # ★ 来源缺失/读不到 ⇒ 不查缓存、不写缓存，直接走既有口径（缺什么说什么 / last-good）。
        _CACHE_SKIPPED.append(bid)
        return compute()
    hit = _cache_load(root, bid)
    if hit is not None and hit["key"] == key:
        _CACHE_HITS.append(bid)
        data = hit["data"]
        # ★ 连续块的 last-good 仍要按「每次成功读数」刷新（不许因为走了缓存就不刷新）。
        if (_REMEMBER and _SRC[bid]["continuous"]
                and isinstance(data, dict) and bid in data):
            _save_lastgood_block(root, bid, data[bid])
        return data
    payload = compute()
    _CACHE_MISSES.append(bid)
    if _cacheable(bid, payload):
        _cache_put(root, bid, key, fp[1], payload)
    return payload


def _first_line(path: Path) -> str:
    """只读**首行**（判决摘要是唯一要的东西）—— 不把整个判决文件读进内存。"""
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            line = fh.readline()
    except OSError:
        return ""
    return line.rstrip("\r\n")


def _parse_stamp(value: object) -> datetime | None:
    """ISO8601 → 带时区的 datetime；认不出 → None（naive 一律按本机时区）。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.astimezone()


def _empty_attempt(att: str) -> dict:
    """一次尝试的产物读数（卡 E115：同一张卡跑过几次就几行，不许互相覆盖）。"""
    return {"att": att, "has_verdict": False, "has_report": False,
            "ended_at": "", "selected": False}


def _select_attempt(attempts: list[dict]) -> str:
    """哪一次是「现行」的：结束时刻最大的那次；认不出时刻就回落无后缀，再回落字典序最小。

    ★ 卡 E115：不许按文件名排序凑合 —— 真仓里 120.killed 比 120 早、143.r2 比 143 晚；
      判决首行的「结束于=」才是唯一能比的读数。
    """
    dated = [row for row in attempts if _parse_stamp(row.get("ended_at")) is not None]
    if dated:
        newest = max(dated, key=lambda row: (_parse_stamp(row["ended_at"]), row["att"]))
        return str(newest["att"])
    if any(row["att"] == "" for row in attempts):
        return ""
    return str(min(row["att"] for row in attempts))


def _lease_dead(row: dict, now: float, root: Path) -> bool | None:
    """这条租约死了没有（判据只有 tools/pool/registry.py 一份）；判不了就说 None。"""
    if _pool_registry is None:
        return None
    try:
        return bool(_pool_registry.is_dead(row, now, log_base=lambda: root))
    except (OSError, ValueError, KeyError):
        return None


def _age_text(at: object) -> str:
    """gates/last.json 的 at（naive 本地时间）距今多久 —— 墙钟只进 --report。"""
    stamp = _parse_stamp(at)
    if stamp is None:
        return "at 缺 / 认不出"
    hours = (datetime.now().astimezone() - stamp).total_seconds() / 3600.0
    if hours < 0:
        return "0.0 小时前（at 在未来？）"
    return f"{hours:.1f} 小时前"


def _behind_text(rev: object) -> str:
    """那趟门禁之后又落了几笔（git rev-list --count <rev>..HEAD）；认不出就如实说。"""
    text = str(rev or "").strip()
    if not text:
        return "rev 缺"
    rc, out = _run_git("rev-list", "--count", f"{text}..HEAD", cwd=_ROOT_USED)
    if rc != 0:
        return f"认不出 rev={text}"
    count = out.strip().splitlines()[0] if out.strip() else "?"
    return f"落后 {count} 个提交"


# ================================================================ 子进程（只读 git）


def _run_git(*args: str, cwd: Path | None = None) -> tuple[int, str]:
    global _GIT_CALLS
    _GIT_CALLS += 1
    done = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=str(cwd or ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", **NO_WINDOW,
    )
    return done.returncode, (done.stdout or "") + (done.stderr or "")


# ================================================================ 1. cards


def _shard_dir(root: Path) -> Path:
    """台账分片目录（`docs/backlog/`）—— 从读数根现算，不用 `wb_plan.ROOT`（它可能是别的树）。"""
    return root.joinpath(*wb_plan.SHARD_DIR_REL)


def _backlog_sources(root: Path) -> list[Path]:
    """队列的**来源文件**：有分片就只算分片（与读法同口径），否则算总表。

    ★ 卡 E89：缓存指纹必须跟着读法走 —— 指纹只算总表时，改分片**不重算**（静默少卡）。
    """
    shards = wb_plan.shard_files(_shard_dir(root))
    return shards if shards else [root / BACKLOG_REL]


def read_cards(root: Path) -> dict:
    """队列全貌（口径见 ``BLOCKS["cards"]``）。静态块：缺什么说什么；内容没变就走缓存。"""
    return _cached(root, "cards", _backlog_sources(root), lambda: _read_cards(root))


def _read_cards(root: Path) -> dict:
    spec = _SRC["cards"]
    shards = wb_plan.shard_files(_shard_dir(root))
    if not shards and not (root / BACKLOG_REL).exists():
        return {"cards": None, "cards_note": spec["missing_note"],
                "cards_source": spec["source"]}
    try:
        backlog = wb_plan.load_sharded_backlog(root / BACKLOG_REL, _shard_dir(root))
    except (OSError, tomllib.TOMLDecodeError, wb_plan.BacklogError) as exc:
        return {"cards": None, "cards_note": f"{spec['source']} 坏了：{exc}",
                "cards_source": spec["source"]}
    cards: list[dict] = [
        {
            "id": card.id,
            "task": card.task,
            "title": card.title,
            "tree": card.tree,
            "spec": card.spec,
            "files": list(card.files),
            "depends": list(card.depends),
            "risk": card.risk,
            "status": card.status,
        }
        for card in backlog.cards
    ]
    return {"cards": cards, "cards_reviewed": backlog.reviewed,
            "cards_source": spec["source"]}


# ================================================================ 2. gates


def read_gates(root: Path) -> dict:
    """最近一次门禁（口径见 ``BLOCKS["gates"]``）。连续块：失败走 STALE-WHILE-ERROR。"""
    return _cached(root, "gates", [root / GATES_LAST_REL], lambda: _read_gates(root))


def _read_gates(root: Path) -> dict:
    spec = _SRC["gates"]
    path = root / GATES_LAST_REL
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return _continuous_out(root, "gates", None,
                                   f"{spec['source']} 坏了：{exc}", "source_broken")
        if not isinstance(data, dict):
            return _continuous_out(root, "gates", None,
                                   f"{spec['source']} 结构不对（顶层应是对象）",
                                   "source_broken")
        items: list[dict] = []
        for g in data.get("gates") or []:
            if not isinstance(g, dict):
                continue
            items.append({
                "name": str(g.get("name", "")),
                "exit_code": g.get("exit_code"),
                "seconds": g.get("seconds"),
            })
        # ★ 卡 E115：生产者（scripts/run_gates.py）早写了这三项，读数器一直没搬 ——
        #   「8 小时前那趟、跑在 card/E116 上、树是脏的」全被抹成一句 rev/ok。
        payload = {
            "ok": data.get("ok"), "rev": data.get("rev"),
            "at": data.get("at"), "dirty": data.get("dirty"),
            "branch": data.get("branch"), "items": items,
        }
        return _continuous_out(root, "gates", payload, "", "")
    return _continuous_out(root, "gates", None, spec["missing_note"], "source_missing")


# ================================================================ 3. verdicts


def read_verdicts(root: Path) -> dict:
    """每张卡有没有判决 / 判决首行 / 有没有 report（口径见 ``BLOCKS["verdicts"]``）。"""
    files = _verdict_files(root)
    return _cached(root, "verdicts", files, lambda: _read_verdicts(root, files))


def _verdict_files(root: Path) -> list[Path]:
    """判决块的全部来源文件（缓存键要逐个文件算 mtime_ns + size + sha256）。"""
    diag = root / DIAG_REL
    if not diag.is_dir():
        return []
    return [p for p in sorted(diag.iterdir())
            if p.is_file() and (_VERDICT_RE.match(p.name) or _REPORT_RE.match(p.name))]


def _read_verdicts(root: Path, files: list[Path]) -> dict:
    spec = _SRC["verdicts"]
    diag = root / DIAG_REL
    if not diag.is_dir():
        return {"verdicts": [], "verdicts_note": spec["missing_note"],
                "verdicts_source": spec["source"]}
    # 卡号 → 尝试标记 → 这一份产物的读数（同卡的多次尝试叠在一起，不许互相覆盖）。
    per_card: dict[str, dict[str, dict]] = {}
    firsts: dict[tuple[str, str], str] = {}
    for entry in files:
        if not entry.is_file():
            continue
        m = _VERDICT_RE.match(entry.name)
        is_verdict = m is not None
        if not is_verdict:
            m = _REPORT_RE.match(entry.name)
        if not m:
            continue
        cid = m.group("card")
        att = m.group("att") or ""
        row = per_card.setdefault(cid, {}).setdefault(att, _empty_attempt(att))
        if is_verdict:
            row["has_verdict"] = True
            # ★ 卡 255：只要首行 ⇒ 只读首行，不把整个判决文件读进内存。
            line = _first_line(entry)
            firsts[(cid, att)] = line
            ended = _ENDED_AT_RE.search(line)
            row["ended_at"] = ended.group(1) if ended else ""
        else:
            row["has_report"] = True
    verdicts: list[dict] = []
    for cid in sorted(per_card):
        attempts = [per_card[cid][att] for att in sorted(per_card[cid])]
        selected = _select_attempt(attempts)
        for row in attempts:
            row["selected"] = row["att"] == selected
        # 四个老字段的口径不变：仍是「这张卡」的读数（selected 那次的判决首行）。
        first = firsts.get((cid, selected), "")
        if not first:
            other = next((row["att"] for row in attempts if row["has_verdict"]), "")
            first = firsts.get((cid, other), "")
        verdicts.append({
            "card": cid,
            "has_verdict": any(row["has_verdict"] for row in attempts),
            "verdict_first_line": first,
            "has_report": any(row["has_report"] for row in attempts),
            "attempts": attempts,
            "selected": selected,
        })
    return {"verdicts": verdicts, "verdicts_source": spec["source"]}



# ================================================================ 4. leases


def read_leases(root: Path) -> dict:
    """租约（口径见 ``BLOCKS["leases"]``）。连续块：失败走 STALE-WHILE-ERROR。

    行内 dead 标死活（True 死 / False 活 / None 判不出）；死租约仍留在表里。
    """
    return _cached(root, "leases", [root / REGISTRY_REL], lambda: _read_leases(root))


def _read_leases(root: Path) -> dict:
    spec = _SRC["leases"]
    path = root / REGISTRY_REL
    if not path.exists():
        # 文件不在 = 还没人租 ⇒ 空表是合法读数（既有口径不动），不是失败。
        return {"leases": [], "leases_source": spec["source"]}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _continuous_out(root, "leases", None,
                               f"{spec['source']} 坏了：{exc}", "source_broken")
    if not isinstance(data, list):
        return _continuous_out(root, "leases", None,
                               f"{spec['source']} 结构不对（顶层应是数组）",
                               "source_broken")
    now = time.time()
    leases: list[dict] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        leases.append({
            "card": str(row.get("card", "")),
            "tree": str(row.get("tree", "")),
            "files": list(row.get("files") or []),
            "owner": str(row.get("owner", "")),
            "at": str(row.get("at", "")),
            "ttl_seconds": row.get("ttl_seconds"),
            # ★ 卡 E115：死租约**不许从表里抹掉**（抹掉就看不见「它一直没被清」），
            #   也不许在读数侧 prune（那是 registry.prune 的职责）—— 只加一列标死活。
            "dead": _lease_dead(row, now, root),
        })
    return _continuous_out(root, "leases", leases, "", "")


# ================================================================ 5. fences


def read_fences(root: Path) -> dict:
    """任务栅栏（口径见 ``BLOCKS["fences"]``）；坏文件 ⇒ 点名不崩。静态块。"""
    files = _fence_files(root)
    return _cached(root, "fences", files, lambda: _read_fences(root, files))


def _fence_files(root: Path) -> list[Path]:
    """栅栏块的全部来源文件（*.toml；缓存键逐个文件算）。"""
    batch = root / BATCH_REL
    if not batch.is_dir():
        return []
    return [p for p in sorted(batch.iterdir()) if p.is_file() and p.suffix == ".toml"]


def _read_fences(root: Path, files: list[Path]) -> dict:
    spec = _SRC["fences"]
    batch = root / BATCH_REL
    if not batch.is_dir():
        return {"fences": [], "fences_note": spec["missing_note"],
                "fences_source": spec["source"]}
    fences: list[dict] = []
    broken: list[dict] = []
    for entry in files:
        if not entry.is_file() or entry.suffix != ".toml":
            continue
        try:
            man = tomllib.loads(entry.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            broken.append({"file": entry.name, "error": str(exc)})
            continue
        members = man.get("member") or []
        fences.append({
            "id": str(man.get("id", "")),
            "on_complete": list(man.get("on_complete") or []),
            "members": len(members) if isinstance(members, list) else 0,
        })
    result: dict = {"fences": fences, "fences_source": spec["source"]}
    if broken:
        result["fences_broken"] = broken
    return result


# ================================================================ 6. worktrees


def read_worktrees(root: Path) -> dict:
    """卡树清单（口径见 ``BLOCKS["worktrees"]``）；路径 + 分支/HEAD + 是否脏。静态块。

    ★ 卡 255：git **固定两次**（`worktree list --porcelain` + 读数根上的
      `status --porcelain=v1 --branch`），不再逐棵树起 `git status`。
      其余树的 dirty 拿不到就记 ``null`` + 块级注（缺什么说什么，不许拿 false 冒充）。
    """
    spec = _SRC["worktrees"]
    rc, out = _run_git("worktree", "list", "--porcelain", cwd=root)
    out = out.strip() if rc == 0 else ""
    if not out:
        return {"worktrees": None, "worktrees_note": spec["missing_note"],
                "worktrees_source": spec["source"]}
    worktrees: list[dict] = []
    current: dict = {}
    for line in out.splitlines():
        if not line.strip():
            if current:
                worktrees.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            current = {"path": line[len("worktree "):]}
        elif line.startswith("HEAD "):
            current["head"] = line[len("HEAD "):]
        elif line.startswith("branch "):
            current["branch"] = line[len("branch "):].removeprefix("refs/heads/")
        elif line.startswith("detached"):
            current["branch"] = "(detached HEAD)"
    if current:
        worktrees.append(current)

    # 第二条（也是最后一条）git 调用：只问读数根这一棵脏不脏，然后分发。
    rc, status_out = _run_git("status", "--porcelain=v1", "--branch", cwd=root)
    root_dirty: bool | None = _status_dirty(status_out) if rc == 0 else None
    root_key = os.path.normcase(str(root.resolve()))
    unknown = 0
    rows: list[dict] = []
    for wt in worktrees:
        path = wt.get("path", "")
        dirty: bool | None = None
        if path and os.path.normcase(str(Path(path).resolve())) == root_key:
            dirty = root_dirty
        if dirty is None:
            unknown += 1
        rows.append({
            "path": path,
            "head": wt.get("head", ""),
            "branch": wt.get("branch", ""),
            "dirty": dirty,
        })
    result: dict = {"worktrees": rows, "worktrees_source": spec["source"]}
    if unknown:
        result["worktrees_dirty_note"] = (
            f"只对读数根起了一次 git status；其余 {unknown} 棵未逐棵起 git ⇒ dirty=null（未知）")
    return result


def _status_dirty(out: str) -> bool:
    """`status --porcelain=v1 --branch` 里除 `## ` 头之外还有行 ⇒ 脏。"""
    return any(line.strip() and not line.startswith("## ") for line in out.splitlines())


# ================================================================ 7. holds


def _reported_columns(row: dict, root: Path) -> dict:
    """这一窗里**上报账**另有多少 token、有没有价（卡 A392）。

    * `reported_tokens`：窗口起点（行里的 `since`）到**此刻**之间、同模型的上报 token 和；
    * `reported_priced`：`True` 全有价 / `False` 至少一行没价 / `None` 这一窗没有上报行。

    ★ **为什么只到「此刻」而不是窗口终点**：行里只有 `since`（窗口起点），没有终点；
      上报行是已经发生的事，`[since, now)` 就是这一窗到今天为止的那一段。窗口终点在
      将来时多算的部分不存在（还没发生）。
    ★ **为什么没有窗口就是 0 / None**：`since` 为空（`why="-"` 那一档，窗口都判不出来）
      ⇒ 这一行没有可归属的窗口，不拿「整本上报账」冒充这一窗。
    ★ 理由（判据 3 要求写进代码注释）：上报账**按账号归不了**（没有 `account` 字段），
      价又是可选的 ⇒ 它不能进限额的 spent / unpriced。能做的是「让读的人看见这里
      有个下界没算进来」，而不是把它折成 0。
    ★ 缺失 / 坏掉 / 调不通 ⇒ `0 / None`，**不抛**（读数面缺什么说什么，不许带崩）。
    """
    blank = {"reported_tokens": 0, "reported_priced": None}
    if _usage_ingest is None:  # pragma: no cover - 工具目录不在 sys.path 的调用方
        return blank
    model = str(row.get("model") or "").strip()
    since = row.get("since")
    if not model or not isinstance(since, str) or not since.strip():
        return blank
    try:
        start = datetime.fromisoformat(since)
    except ValueError:
        return blank
    if start.tzinfo is None:  # 没有偏移量就没法与 aware 的 end 比 —— 不猜
        return blank
    end = datetime.now(timezone.utc)
    if end <= start:
        return blank
    try:
        tokens, priced = _usage_ingest.reported_summary(model, start, end, root=root)
    except Exception:  # 读数面不许被上报账带崩（缺什么说什么）
        return blank
    return {"reported_tokens": int(tokens), "reported_priced": priced}


def read_holds(root: Path) -> dict:
    """整窗用量估算（口径见 ``BLOCKS["holds"]``）。静态块，**不走读数缓存**。

    ★ 卡 A369：算式与五因顺序**一个字都不在这里** —— 全在 `tools/pool/holds.py`；
      账本 → 窗口的搬运只有 `tools/pool/holds_wiring.py` 一份。本函数只做三件事：
      调它、把三种结局分开说（账本读不到 / 一个号都没有 / 账本坏了）、保证**不抛**。
    ★ 坏账本（used_percent 越界 / 重复 id / TOML 坏）**不是**「没有读数」：读数面
      仍要出得来（`--json` / `--report` 不许抛），但必须点出原文 —— 不许静默成 null。
    ★ 卡 A392：每行追加 `reported_tokens` / `reported_priced` 两列（见 `_reported_columns`）。
      上报账的调用**只在这里**；`holds_wiring` 一个字不改。
    """
    spec = _SRC["holds"]
    if _holds_wiring is None:  # pragma: no cover - 工具目录不在 sys.path 的调用方
        return {"holds": None, "holds_note": spec["missing_note"],
                "holds_source": spec["source"]}
    try:
        reading = _holds_wiring.read_holds(root)
    except Exception as exc:  # 缺什么说什么：坏账本也要出得来，不许把读数带崩
        return {"holds": None, "holds_note": f"账号账本读不了：{exc}",
                "holds_source": spec["source"]}
    if reading.rows is None:
        return {"holds": None, "holds_note": reading.note or spec["missing_note"],
                "holds_source": spec["source"]}
    rows = [dict(row, **_reported_columns(row, root)) for row in reading.rows]
    result: dict = {"holds": rows, "holds_source": spec["source"]}
    if reading.note:
        result["holds_note"] = reading.note
    return result


# ================================================================ 汇总


_READERS: dict[str, object] = {
    "cards": read_cards, "gates": read_gates, "verdicts": read_verdicts,
    "leases": read_leases, "fences": read_fences, "worktrees": read_worktrees,
    "holds": read_holds,
}


def build_reading(root: Path | None = None, *, remember: bool = False) -> dict:
    """一份读数：七块（块的顺序与口径都来自 BLOCKS 声明表，不许另立一份）。

    `remember=True` 才把连续块的好读数落 last-good、才写读数缓存（默认不写 ⇒ 只读 ✓）。
    """
    global _REMEMBER, _GIT_CALLS, _CACHE_HITS, _CACHE_MISSES, _CACHE_SKIPPED, _ROOT_USED
    if remember:
        _REMEMBER = True
    # ★ 卡 255：每次读数重开账（--report 报的是**这一次**调了几次 git / 命中几块）。
    _GIT_CALLS = 0
    _CACHE_HITS = []
    _CACHE_MISSES = []
    _CACHE_SKIPPED = []
    root = Path(root) if root is not None else ROOT
    _ROOT_USED = root  # ★ 卡 E115：--report 要在这个根上算「落后几个提交」
    result: dict = {}
    for spec in BLOCKS:
        result.update(_READERS[spec["id"]](root))
    return result


# ================================================================ 人读报告


def _report(reading: dict) -> str:
    lines: list[str] = []
    _report_cards(lines, reading)
    _report_gates(lines, reading)
    _report_verdicts(lines, reading)
    _report_leases(lines, reading)
    _report_fences(lines, reading)
    _report_worktrees(lines, reading)
    _report_holds(lines, reading)
    return "\n".join(lines)


def _report_cards(lines: list[str], r: dict) -> None:
    cards = r.get("cards")
    src = _SRC["cards"]["source"]
    if cards is None:
        lines.append(f"[cards] {r.get('cards_note', '没有')}（来源 {src}）")
        return
    lines.append(f"[cards] 队列共 {len(cards)} 张（来源 {src}，"
                 f"基点 {r.get('cards_reviewed', '?')}）：")
    for c in cards:
        lines.append(f"  · {c['id']}（{c['task']}）{c['title'][:40]}"
                     f"  tree={c['tree'] or '(主树)'}  status={c['status']}  risk={c['risk']}")


def _report_gates(lines: list[str], r: dict) -> None:
    gates = r.get("gates")
    src = _SRC["gates"]["source"]
    if gates is None:
        lines.append(f"[gates] {r.get('gates_note', '没有')}（来源 {src}）")
        return
    items = gates.get("items") or []
    # ★ 卡 E115：一行 rev/ok 看不出「这是不是现在」—— 把 at 距今多久、落后几个提交念出来
    #   （墙钟与 git rev-list 都只进 --report，--json 仍是纯读数）。
    lines.append(f"[gates] 最近一次门禁（来源 {src}）："
                 f"rev={gates.get('rev')} ok={gates.get('ok')}  共 {len(items)} 道"
                 f"（{_age_text(gates.get('at'))}，{_behind_text(gates.get('rev'))}）：")
    for g in items:
        lines.append(f"  · {g['name']}: exit={g['exit_code']}  {g['seconds']}s")
    # ★ 卡 E115：那趟门禁是在哪条分支上、树脏不脏，也念出来（生产者早就写了）。
    if gates.get("branch") is not None or gates.get("dirty") is not None:
        dirty = gates.get("dirty")
        mark = "脏否未知" if dirty is None else ("脏" if dirty else "干净")
        lines.append(f"  · 那趟跑在 branch={gates.get('branch') or '?'} 上，树 {mark}")
    _report_stale(lines, r, "gates")


def _report_stale(lines: list[str], r: dict, bid: str) -> None:
    """连续块的坏读数标注（STALE-WHILE-ERROR）：墙钟只进 --report，不进 --json。"""
    st = r.get(f"{bid}_stale")
    if not st:
        return
    lines.append(f"  ★ 读数失败（error_code={st.get('error_code')}）："
                 f"以上是上一份好读数（captured_at={st.get('captured_at')}，"
                 f"stale_for_s={_stale_for_s(st)}s）")


def _stale_for_s(st: dict) -> str:
    """上一份好读数距今多少秒；解析不了就如实给「?」。"""
    try:
        t = datetime.fromisoformat(str(st.get("captured_at", "")))
        gap = (datetime.now().astimezone() - t).total_seconds()
        return str(max(0, int(gap)))
    except ValueError:
        return "?"


def _report_verdicts(lines: list[str], r: dict) -> None:
    note = r.get("verdicts_note")
    src = _SRC["verdicts"]["source"]
    if note:
        lines.append(f"[verdicts] {note}（来源 {src}）")
        return
    verdicts = r.get("verdicts") or []
    lines.append(f"[verdicts] 判决（来源 {src}）："
                 f"共 {len(verdicts)} 张卡有产物：")
    for v in verdicts:
        tags = []
        if v["has_verdict"]:
            tags.append("有判决")
        if v["has_report"]:
            tags.append("有摘要")
        attempts = v.get("attempts") or []
        if len(attempts) > 1:
            # ★ 卡 E115：同一张卡跑过几次就说几次，「现行」是哪一个也念出来。
            tags.append(f"{len(attempts)} 次尝试，现行={v.get('selected') or '无后缀那次'}")
        first = v["verdict_first_line"][:60] if v["verdict_first_line"] else ""
        suffix = f"  首行：{first}" if first else ""
        lines.append(f"  · {v['card']}: {'、'.join(tags) or '无'}" + suffix)


def _report_leases(lines: list[str], r: dict) -> None:
    leases = r.get("leases")
    src = _SRC["leases"]["source"]
    if leases is None:
        lines.append(f"[leases] {r.get('leases_note', '没有')}（来源 {src}）")
        return
    # ★ 卡 E115：死租约还留在表里 —— 这里必须把「其中几条已死」念出来，否则读者以为都活着。
    dead = sum(1 for lc in leases if lc.get("dead"))
    unknown = sum(1 for lc in leases if lc.get("dead") is None)
    tail = f"，其中 {dead} 条已死" if dead else ""
    if unknown:
        tail += f"，{unknown} 条判不出"
    lines.append(f"[leases] 租约（来源 {src}）：共 {len(leases)} 条{tail}：")
    for lc in leases:
        mark = "  ★ 已死" if lc.get("dead") else ""
        mark += "  （判不出）" if lc.get("dead") is None else ""
        lines.append(f"  · card={lc['card']}  tree={lc['tree']}  owner={lc['owner']}"
                     f"  at={lc['at']}  ttl={lc['ttl_seconds']}s{mark}")
    _report_stale(lines, r, "leases")


def _report_fences(lines: list[str], r: dict) -> None:
    note = r.get("fences_note")
    src = _SRC["fences"]["source"]
    if note:
        lines.append(f"[fences] {note}（来源 {src}）")
    else:
        fences = r.get("fences") or []
        lines.append(f"[fences] 任务栅栏（来源 {src}）："
                     f"共 {len(fences)} 个：")
        for f in fences:
            lines.append(f"  · {f['id']}: on_complete={f['on_complete']}"
                         f"  members={f['members']}")
    for b in r.get("fences_broken") or []:
        lines.append(f"  ★ 坏文件：{b['file']}  错误：{b['error']}")


def _report_worktrees(lines: list[str], r: dict) -> None:
    worktrees = r.get("worktrees")
    src = _SRC["worktrees"]["source"]
    if worktrees is None:
        lines.append(f"[worktrees] {r.get('worktrees_note', '没有')}（来源 {src}）")
        return
    lines.append(f"[worktrees] 卡树清单（来源 {src}）："
                 f"共 {len(worktrees)} 棵：")
    for w in worktrees:
        dirty = "未知" if w["dirty"] is None else ("是" if w["dirty"] else "否")
        lines.append(f"  · {w['path']}  branch={w['branch']}  head={w['head']}"
                     f"  dirty={dirty}")
    note = r.get("worktrees_dirty_note")
    if note:
        lines.append(f"  ★ {note}")


def _reported_text(h: dict) -> str:
    """人话里怎么说「上报账这一窗另有多少」—— 没价就明说没价（卡 A392）。"""
    tokens = h.get("reported_tokens", 0)
    priced = h.get("reported_priced")
    if priced is None:
        return "上报=0（这一窗没有上报行）"
    if priced:
        return f"上报={tokens}（都有价）"
    return f"上报={tokens}（★ 其中有行没价，这笔钱不知道）"


def _report_holds(lines: list[str], r: dict) -> None:
    """第七块：整窗用量估算 —— **估不出来也要把理由念出来**（卡 A369 的核心）。"""
    holds = r.get("holds")
    src = _SRC["holds"]["source"]
    if holds is None:
        lines.append(f"[holds] {r.get('holds_note', '没有')}（来源 {src}）")
        return
    live = sum(1 for h in holds if not h.get("why"))
    lines.append(f"[holds] 整窗用量估算（来源 {src}）：共 {len(holds)} 个号，"
                 f"其中 {live} 个估出来了：")
    for h in holds:
        why = h.get("why") or "(估出来了)"
        lines.append(f"  · {h['account']}（{h['platform']}）"
                     f"model={h['model'] or '(没有批准模型)'}  used={h['used_percent']}"
                     f"  why={why}  tokens={h['tokens']}  cost={h['cost']}"
                     f"  priced={h['priced']}  {_reported_text(h)}")
        if h.get("why_text"):
            lines.append(f"    ★ {h['why_text']}")
    note = r.get("holds_note")
    if note:
        lines.append(f"  ★ {note}")


# ================================================================ 性能账（只进 --report）

#: git 调用形状（按实际次数打印；两次是常态：worktree list + status）。
_GIT_SHAPES = {
    # ★ 卡 E115：--report 为了算「落后几个提交」多调一次 git rev-list ⇒ 三档也登记。
    3: "git worktree list --porcelain + git status --porcelain=v1 --branch"
       " + git rev-list --count（--report 算「落后几个提交」）",
    2: "git worktree list --porcelain + git status --porcelain=v1 --branch",
    1: "git worktree list --porcelain（status 未跑：list 无输出/失败）",
    0: "一次也没调",
}


def _report_perf() -> str:
    """本次读数的账：缓存命中/重算、git 调用次数、Python 侧峰值内存。

    ★ 只进 `--report` —— `--json` 里一个字都不许有（冷跑/热跑必须逐字节相同）。
    """
    hits = "、".join(_CACHE_HITS) or "无"
    misses = "、".join(_CACHE_MISSES) or "无"
    skipped = "、".join(_CACHE_SKIPPED) or "无"
    shape = _GIT_SHAPES.get(_GIT_CALLS, "（未登记的调用形状）")
    peak = _PEAK_BYTES / (1024 * 1024)
    return "\n".join([
        f"[readcache] 命中 {len(_CACHE_HITS)} 块（{hits}）"
        f" / 重算 {len(_CACHE_MISSES)} 块（{misses}）"
        f" / 无源不缓存 {len(_CACHE_SKIPPED)} 块（{skipped}）",
        f"[readcache] 键 = mtime_ns + size + sha256；"
        f"落盘 {READCACHE_REL.as_posix()}/",
        f"[git] 本次调用 {_GIT_CALLS} 次：{shape}",
        f"[mem] Python 侧峰值 {peak:.2f} MB（tracemalloc，仅 --report 采）",
    ])


# ================================================================ CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="一份读数：七块收成一份（只读，缺什么说什么、幂等）")
    parser.add_argument("--json", action="store_true", help="输出 JSON（机器可读）")
    parser.add_argument("--report", action="store_true", help="输出人读报告")
    parser.add_argument("--root", default="", help="仓库根（默认本文件推出来）")
    global _REMEMBER, _PEAK_BYTES
    args = parser.parse_args(argv)
    _REMEMBER = True  # ★ CLI = 监测路径：好读数落 last-good / 写缓存（库调用方不写 ✓）
    root = Path(args.root) if args.root else ROOT
    if args.json:
        reading = build_reading(root)
        print(json.dumps(reading, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    # ★ 峰值内存只在 --report 采：--json 的路径不加任何额外观测（保冷/热逐字节相同）。
    tracemalloc.start()
    try:
        reading = build_reading(root)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    _PEAK_BYTES = peak
    print(_report(reading))
    print(_report_perf())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
