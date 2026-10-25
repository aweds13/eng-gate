r"""Trae 完工看守（卡 E29 · T-AG483）—— 把「Trae 停了」变成**可发现**的。

**为什么有它**（2026-10-25 三次真现场，都是人发现的）：

Trae 是「一轮一交还」的模型 —— **没有常驻进程**，一轮干完就停在那里等下一句。于是「它停了」
这件事没有任何事实来源：只能靠人眼看面板，或人来问一句「怎么停了」。

1. **被手动终止**：发送键在运行中**兼作停止键**（`span[data-testid]` 由 `chat-icon-arrow-up`
   变成 `chat-icon-stop`）。10:39 误点一下，E10 会话里出现「手动终止输出」，卡树随后一小时
   零改动 —— 当时没有任何通知。
2. **一轮跑完交还**（E27）：面板里交了一份很像样的收工报告，但没有任何落盘事件，
   `gates/diag/wb-<卡>.done` 不出现 —— 看守（`wb_watch`）只认号池工人的日志，**不认 Trae**。
3. **看起来在跑、其实空转**：图标还不是空闲、树里一小时没动 —— 比停了更贵（一直占并发位）。

    python -X utf8 tools/trae_watch.py --task "E28" --card E28 --tree .wt/E28 \
        --interval 30 --timeout 5400 [--stale-min 10] [--write-done] [--json]

**每拍采样一次**（`node tools/trae_pool.mjs sample --task … --json`，**只读 DOM**），
判四态并落事件：

==============  ===========================================  ===========================
态              判据                                         落盘（通知流 state）
==============  ===========================================  ===========================
`finished`      icon 由 stop → `chat-icon-arrow-up`          `wb-<卡>.done` / `done`
`terminated`    正文出现「手动终止输出」                       `.stopped` / `trae-stopped`，退 5
`stalled`       icon 仍 stop 且 bodyHash 不变 ≥ 门槛         `.stopped` / `trae-stalled`，退 5
                （给了 `--tree` 时树 mtime 也要不动）
`running`       其余                                         只写通知流（含 bodyLen）
==============  ===========================================  ===========================

（`.stopped` 的完整名是 `gates/diag/trae-<卡>.stopped`。）

★ **事件面复用 `wb_watch`，不另造一份**：`diag_dir()` / `done_path()` / `append_notification()`
  直接调它那三个函数（判决 / 通知 / `.done` 与号池工人**同一处、同一种行**）。
★ **不给 `--write-done` 就是只读**：一个字节都不写，只把采样打出来（与 `wb_watch` 同口径）。
★ **`.done` 只在真收工时写**：Trae 的失败不是号池工人的失败 —— 没跑完就没有完工事件。
★ **幂等**：`.done` / `.stopped` 已在 ⇒ 原样返回，**不再**追加第二行通知（看守重启不重复写）。
★ **判据与 `trae_pool.mjs:judgeTraeSample` 同口径**（四态、锚点、`stale_min <= 0` = 关掉空转判定）；
  两边各由 pytest / `selftest` 钉住 —— 改一边就要改另一边。

**退出码**：`0` 真收工 · `5` 被终止 / 空转（卡的硬要求）· `4` 超时（没判决不算成功）·
`3` 采样就没成（node / CDP / 页面读不到）· `2` 用法。

★ 边界（如实写）：本工具**不判断内容对不对**（那是主控复核的事），只判断「这一轮完了 / 被掐了 /
  空转了」。`bodyHash` 是采样侧算的 32 位 FNV-1a，只用来判「变没变」。真机那一步要有带调试口的
  Trae，本卡机器上跑的是注入式假采样 + 纯函数判据。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

TOOL_ROOT = Path(__file__).resolve().parent.parent  # 工具住哪：本树的 tools/trae_pool.mjs
sys.path.insert(0, str(TOOL_ROOT / "tools"))

try:  # 事件/日志住哪（卡 A326）：按文件位置算根 ⇒ 在卡树里跑会把事件写进卡树
    import pipe_root
except ImportError:  # pragma: no cover —— 落地桩/独立拷贝的树里没有 pipe_root
    try:
        from tools import pipe_root  # type: ignore[no-redef]
    except ImportError:
        pipe_root = None  # type: ignore[assignment]

ROOT = pipe_root.data_root() if pipe_root is not None else TOOL_ROOT

# ★ 事件面**只有一份真源**：判决目录 / `.done` / 通知流都在 `wb_watch` 里 —— 这里只 import、只调用。
import wb_watch  # noqa: E402
from pool.no_window import NO_WINDOW  # noqa: E402 —— 起 node 子进程不弹窗（卡 148）

# ---------------------------------------------------------------- 四态 / 退出码
STATE_FINISHED = "finished"
STATE_TERMINATED = "terminated"
STATE_STALLED = "stalled"
STATE_RUNNING = "running"

#: 通知流里的 `state` 值（卡 E29 逐字钉着这四个；`done` 与 `wb_watch` 同一个值）。
NOTIFY_DONE = "done"
NOTIFY_STOPPED = "trae-stopped"
NOTIFY_STALLED = "trae-stalled"
NOTIFY_RUNNING = "trae-running"
NOTIFY_TIMEOUT = "timeout"

EXIT_FINISHED = 0          # 真收工（图标 stop → arrow-up）
EXIT_USAGE = 2             # 用法错
EXIT_SAMPLE = 3            # 采样就没成（node / CDP / 页面读不到）
EXIT_TIMEOUT = 4           # 超时（★ 没判决不算成功）
EXIT_STOPPED = 5           # 被手动终止 / 空转塌陷（卡 E29 指定的退出码）

DEFAULT_INTERVAL = 30.0    # 每 30 秒采一拍（卡给的默认）
DEFAULT_TIMEOUT = 5400.0   # 硬超时 90 分钟（卡给的默认）
DEFAULT_STALE_MIN = 10.0   # 空转门槛：同一段正文 ≥10 分钟没变

ICON_STOP = "chat-icon-stop"
ICON_ARROW_UP = "chat-icon-arrow-up"
TERMINATED_HINT = "手动终止输出"

#: 采样日志（每拍一行）—— 卡的证据清单要读它的尾部。
WATCH_LOG_NAME = "trae-watch.jsonl"


class SampleError(Exception):
    """采样不成（node 不在 / CDP 连不上 / 页面读不到 / 吐的不是 JSON）—— 带原话，不猜。"""


# ---------------------------------------------------------------- 采样（只读）
def watch_log_path(root: Path) -> Path:
    """每拍一行的采样日志：`<root>/gates/diag/trae-watch.jsonl`（卡的证据指向它）。"""
    return wb_watch.diag_dir(root) / WATCH_LOG_NAME


def stopped_path(root: Path, card: str) -> Path:
    """被终止 / 空转的落点：`gates/diag/trae-<卡>.stopped`（一行 JSON）。"""
    return wb_watch.diag_dir(root) / f"trae-{card}.stopped"


def _rel(root: Path, path: Path) -> str:
    """仓库相对路径；不在树里（独立拷贝）⇒ 绝对 posix 路径（不编一个假的相对路径）。"""
    try:
        return Path(path).relative_to(root).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _node_exe() -> str:
    node = shutil.which("node")
    if not node:
        raise SampleError("找不到 node —— 采样要靠 `node tools/trae_pool.mjs sample`")
    return node


def sample_trae(task: str, *, root: Path = TOOL_ROOT, port: int | None = None,
                timeout: float = 60.0) -> dict:
    """采一拍：跑 `node tools/trae_pool.mjs sample --task <task> --json`，回那条 JSON。

    ★ **只读**：子命令自己只读 DOM（不点发送键 / 不点任务项），这里也不写任何文件。
    ★ 起子进程带 `NO_WINDOW`（卡 148 铁律：不弹命令行窗口）。
    """
    cmd = [_node_exe(), str(Path(root) / "tools" / "trae_pool.mjs"), "sample",
           "--task", str(task), "--json"]
    if port is not None:
        cmd += ["--port", str(port)]
    try:
        proc = subprocess.run(
            cmd, cwd=str(root), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, **NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SampleError(f"起 `trae_pool.mjs sample` 失败：{exc}") from exc
    line = next((ln for ln in reversed(proc.stdout.splitlines()) if ln.strip()), "")
    if not line:
        tail = (proc.stderr or "").strip().splitlines()
        raise SampleError(f"sample 没有输出（退出码 {proc.returncode}）："
                          f"{tail[-1] if tail else '（stderr 也是空的）'}")
    try:
        data = json.loads(line)
    except json.JSONDecodeError as exc:
        raise SampleError(
            f"sample 吐的不是 JSON（退出码 {proc.returncode}）：{line[:200]}") from exc
    if not isinstance(data, dict) or data.get("ok") is not True:
        raise SampleError(f"sample 报错：{line[:300]}")
    return data


# ---------------------------------------------------------------- 判据（四态）
def judge_sample(prev: dict | None, cur: dict, *, stale_min: float = DEFAULT_STALE_MIN,
                 tree_idle: bool | None = None) -> tuple[str, str]:
    """两拍采样 → （态, 一句人话）。与 `trae_pool.mjs:judgeTraeSample` **同口径**。

    · `prev` 是**锚点**：正文上一次变样的那一拍（一直不变 ⇒ 锚点不动 ⇒ 量得出「多久没动」）；
    · `terminated` 优先于一切：正文出现「手动终止输出」⇒ 这一轮被掐了，跟图标无关；
    · `finished`：图标由 `stop` → `arrow-up`（★ 一次采样说不了「收工」，必须有锚点）；
    · `stalled`：图标仍 `stop`、`bodyHash` 与锚点相同、已过 ≥ `stale_min` 分钟，
      且（给了 `--tree` 时）树 mtime 也没动（`tree_idle is not False`）；
    · 其余 = `running`。

    ★ `stale_min <= 0` ⇒ **关掉空转判定**（「0 分钟没动」不是读数，是「别判空转」的开关写法）。
    """
    if cur.get("terminated"):
        return STATE_TERMINATED, f"正文出现「{TERMINATED_HINT}」—— 这一轮是被手动掐掉的"
    icon = str(cur.get("icon") or "unknown")
    prev_icon = str((prev or {}).get("icon") or "")
    if prev_icon == ICON_STOP and icon == ICON_ARROW_UP:
        return STATE_FINISHED, "图标由 chat-icon-stop → chat-icon-arrow-up（真收工）"
    if (prev is not None and icon == ICON_STOP
            and prev.get("bodyHash") == cur.get("bodyHash")
            and stale_min > 0 and tree_idle is not False):
        minutes = (float(cur.get("at") or 0.0) - float(prev.get("at") or 0.0)) / 60.0
        if minutes >= stale_min:
            return STATE_STALLED, (f"图标仍 stop，正文已有 {minutes:.1f} 分钟一字未变"
                                   f"（门槛 {stale_min:g} 分钟）")
    return STATE_RUNNING, f"icon={icon} bodyLen={int(cur.get('bodyLen') or 0)}"


# ---------------------------------------------------------------- 落盘（复用 wb_watch）
def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def append_sample(root: Path, row: dict) -> Path:
    """往 `gates/diag/trae-watch.jsonl` 追加**一行**（每拍一行，卡的证据读它的尾部）。"""
    path = watch_log_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as out:
        out.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def write_done_event(root: Path, card: str, *, task: str = "", sample: dict | None = None,
                     now: float | None = None) -> dict | None:
    """真收工 ⇒ 落 `gates/diag/wb-<卡>.done`（**与 `wb_watch` 逐字段同构**）
    + 通知流 `state:"done"`。

    ★ 行里六个键与 `wb_watch.write_done_event` 一模一样：`card` / `task` / `exit_code` / `at` /
      `log` / `report` —— 号池工人与 Trae 的完工事件在下游看来是**同一种**行。
    ★ 幂等：`.done` 已在 ⇒ 原样返回，**不再**追加第二行通知。
    """
    root = Path(root)
    now = time.time() if now is None else now
    path = wb_watch.done_path(root, card)
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return existing if isinstance(existing, dict) else None
    s = sample or {}
    done = {
        "card": card,
        "task": task or str(s.get("task") or ""),
        "exit_code": 0,
        "at": _iso(now),
        "log": _rel(root, watch_log_path(root)),
        "report": wb_watch._report_pointer(root, card),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(done, ensure_ascii=False) + "\n", encoding="utf-8")
    wb_watch.append_notification(root, {**done, "state": NOTIFY_DONE,
                                        "verdict": "Trae 收工（图标 stop → arrow-up）"})
    return done


def write_stopped_event(root: Path, card: str, state: str, *, why: str = "",
                        sample: dict | None = None, now: float | None = None) -> dict | None:
    """被终止 / 空转 ⇒ 落 `trae-<卡>.stopped` + 通知流
    `trae-stopped` / `trae-stalled`。

    ★ **不写** `.done`：没跑完就没有完工事件（Trae 的失败不许冒充号池工人的成功）。
    ★ 幂等：`.stopped` 已在 ⇒ 原样返回，**不再**追加第二行通知。
    """
    root = Path(root)
    now = time.time() if now is None else now
    path = stopped_path(root, card)
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return existing if isinstance(existing, dict) else None
    s = sample or {}
    row = {
        "card": card,
        "task": str(s.get("task") or ""),
        "state": state,
        "at": _iso(now),
        "why": why,
        "icon": str(s.get("icon") or ""),
        "bodyLen": int(s.get("bodyLen") or 0),
        "bodyHash": str(s.get("bodyHash") or ""),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    notify_state = NOTIFY_STOPPED if state == STATE_TERMINATED else NOTIFY_STALLED
    wb_watch.append_notification(root, {
        "at": row["at"], "card": card, "state": notify_state,
        "log": _rel(root, watch_log_path(root)),
        "report": wb_watch._report_pointer(root, card),
        "which": state, "why": why, "icon": row["icon"],
        "bodyLen": row["bodyLen"], "bodyHash": row["bodyHash"],
    })
    return row


def write_running_event(root: Path, card: str, *, sample: dict, why: str = "",
                        now: float | None = None) -> dict:
    """`running` ⇒ **只写通知流**（含 `bodyLen`），不落任何 mark（卡 E29 的表格要求）。"""
    now = time.time() if now is None else now
    row = {
        "at": _iso(now), "card": card, "state": NOTIFY_RUNNING,
        "log": _rel(root, watch_log_path(root)),
        "report": wb_watch._report_pointer(root, card),
        "icon": str(sample.get("icon") or ""),
        "bodyLen": int(sample.get("bodyLen") or 0),
        "bodyHash": str(sample.get("bodyHash") or ""),
        "why": why,
    }
    wb_watch.append_notification(root, row)
    return row


def write_timeout_event(root: Path, card: str, *, now: float | None = None) -> dict:
    """超时**没结论** ⇒ 通知流 `state:"timeout"`（与 `wb_watch` 同一个值；不写 `.done`）。"""
    return wb_watch.write_card_event(root, card, NOTIFY_TIMEOUT, now=now)


# ---------------------------------------------------------------- 树 mtime
#: 树 mtime 只看「工人真会写的那些文件」—— `.git` / `gates` / 缓存目录不算（它们随时在动）。
_SKIP_DIRS = frozenset({".git", "gates", "node_modules", "__pycache__", ".pytest_cache",
                        ".mypy_cache", ".ruff_cache"})


def tree_latest_mtime(tree: Path | str) -> float | None:
    """这棵树里**最新的文件 mtime**；目录不存在 / 一个文件都没有 ⇒ None（不猜）。"""
    base = Path(tree)
    if not base.is_dir():
        return None
    latest: float | None = None
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            try:
                mtime = (Path(dirpath) / name).stat().st_mtime
            except OSError:                       # 边读边被删 ⇒ 这一份不算
                continue
            if latest is None or mtime > latest:
                latest = mtime
    return latest


# ---------------------------------------------------------------- 主循环
def _state_row(now: float, card: str, state: str, sample: dict, why: str) -> dict:
    """`--json` 每拍那一行 —— 键名**固定**（卡 E29 判据 1 的第五条钉子）。"""
    return {
        "at": _iso(now),
        "card": card,
        "state": state,
        "icon": str(sample.get("icon") or ""),
        "bodyLen": int(sample.get("bodyLen") or 0),
        "bodyHash": str(sample.get("bodyHash") or ""),
        "why": why,
    }


def watch(*, task: str, card: str, root: Path | None = None, tree: Path | None = None,
          interval: float = DEFAULT_INTERVAL, timeout: float = DEFAULT_TIMEOUT,
          stale_min: float = DEFAULT_STALE_MIN, write_done: bool = False,
          port: int | None = None,
          sample: Callable[[], dict] | None = None,
          clock: Callable[[], float] = time.time,
          sleep: Callable[[float], None] = time.sleep,
          emit: Callable[[str], None] = print,
          as_json: bool = False) -> int:
    """真轮询直到 收工 / 被终止 / 空转 / 超时；返回退出码（0 / 5 / 4 / 3）。

    `sample` / `clock` / `sleep` 可注入（测试用假采样 + 假时间源，**不真等、不碰 Trae**）——
    判据本身仍是现读采样 + 现读树 mtime。
    ★ `write_done=False`（CLI 不给 `--write-done`）⇒ **一个字节都不写**，只把采样打出来。
    """
    root = Path(root) if root is not None else ROOT
    # ★ 工具根 ≠ 数据根（卡 A326）：mjs 住工具树，事件落数据根 —— 卡树里跑也不会写错树。
    do_sample = (sample if sample is not None
                 else (lambda: sample_trae(task, root=TOOL_ROOT, port=port)))
    # ★ `--json` 时 stdout 只许出现 JSON 行（`jq` 才用得上）——人话改走 stderr。
    note: Callable[[str], None] = emit if not as_json else (
        lambda line: print(line, file=sys.stderr, flush=True))
    start = clock()
    anchor: dict | None = None
    first = True
    while True:
        now = clock()
        try:
            cur = dict(do_sample())
        except SampleError as exc:
            if first:
                note(f"[FAIL] 采样就没成：{exc}")
                return EXIT_SAMPLE
            cur = None
            note(f"[看 ] 这一拍读不到：{exc}（继续等）")
        first_tick, first = first, False
        if cur is not None:
            cur["at"] = now
            if first_tick and cur.get("icon") == ICON_ARROW_UP:
                # ★ 诚实写边界：上来就是空闲 ⇒ 无法确认「这一轮刚收工」
                #   （收工只认 stop → arrow-up 的转变）—— 不写 .done，只把这句话说出来。
                note("[看 ] 第一拍就是 chat-icon-arrow-up（空闲）—— 这一轮可能早就收工了；"
                     "「收工」只认 stop → arrow-up 的转变，所以不写 .done")
            tree_idle: bool | None = None
            if tree is not None:
                latest = tree_latest_mtime(tree)
                if latest is not None:
                    tree_idle = (now - latest) >= max(stale_min, 0.0) * 60.0
            state, why = judge_sample(anchor, cur, stale_min=stale_min, tree_idle=tree_idle)
            if as_json:
                emit(json.dumps(_state_row(now, card, state, cur, why), ensure_ascii=False))
            if write_done:
                append_sample(root, _state_row(now, card, state, cur, why))
            if state == STATE_FINISHED:
                if write_done:
                    done = write_done_event(root, card, task=str(cur.get("task") or task),
                                            sample=cur, now=now)
                    where = (wb_watch.done_path(root, card).name
                             if done is not None else "（没写出来）")
                    note(f"[完 ] 卡 {card} 收工 → 写 {where} + 通知流一行")
                else:
                    note(f"[完 ] 卡 {card} 收工（没给 --write-done：只读，未落盘）")
                return EXIT_FINISHED
            if state in (STATE_TERMINATED, STATE_STALLED):
                if write_done:
                    write_stopped_event(root, card, state, why=why, sample=cur, now=now)
                    note(f"[断 ] 卡 {card} {why} → 写 {stopped_path(root, card).name} + 通知流一行")
                else:
                    note(f"[断 ] 卡 {card} {why}（没给 --write-done：只读，未落盘）")
                return EXIT_STOPPED
            # running：只写通知流，不落 mark
            if write_done:
                write_running_event(root, card, sample=cur, why=why, now=now)
            elapsed = now - start
            if elapsed >= timeout:
                if write_done:
                    write_timeout_event(root, card, now=now)
                note(f"[超时] 已盯 {elapsed / 60:.1f} 分钟（上限 {timeout / 60:.1f} 分钟）"
                     f"—— 仍 icon={cur.get('icon')}（**没结论不算有结果**）")
                return EXIT_TIMEOUT
            note(f"[心跳] 已盯 {elapsed / 60:.1f} 分钟 | 卡 {card}={state} | "
                 f"icon={cur.get('icon')} bodyLen={int(cur.get('bodyLen') or 0)}")
            # ★ 锚点：正文变样才前移（一直不变 ⇒ 停在上一次变样那一拍，才量得出「多久没动」）
            if anchor is None or anchor.get("bodyHash") != cur.get("bodyHash"):
                anchor = cur
        else:
            elapsed = now - start
            if elapsed >= timeout:
                note(f"[超时] 已盯 {elapsed / 60:.1f} 分钟，仍然读不到采样（**不猜结果**）")
                return EXIT_SAMPLE
            note(f"[心跳] 已盯 {elapsed / 60:.1f} 分钟 | 卡 {card}=看不见信号（采样读不到）")
        sleep(min(interval, max(0.0, timeout - (clock() - start))))


# ---------------------------------------------------------------- CLI
def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Trae 完工看守：每拍采样一次，判 收工 / 被终止 / 空转 / 在跑（默认只读）")
    ap.add_argument("--task", required=True, help='面板里那张任务的**标题子串**（如 "E28"）')
    ap.add_argument("--card", required=True,
                    help="卡号（落盘用：wb-<卡>.done / trae-<卡>.stopped）")
    ap.add_argument("--tree", default=None,
                    help="卡树（如 .wt/E28）：给了就问「树 mtime 也不动」才算空转")
    ap.add_argument("--root", default=str(ROOT), help="仓库根（事件落 <root>/gates/diag）")
    ap.add_argument("--interval", type=float, default=DEFAULT_INTERVAL,
                    help=f"采样间隔（秒，默认 {DEFAULT_INTERVAL:.0f}）")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                    help=f"硬超时（秒，默认 {DEFAULT_TIMEOUT:.0f} = 90 分钟）")
    ap.add_argument("--stale-min", type=float, default=DEFAULT_STALE_MIN, dest="stale_min",
                    help=f"空转门槛（分钟，默认 {DEFAULT_STALE_MIN:g}；设 0 = 关掉空转判定）")
    ap.add_argument("--port", type=int, default=None, help="CDP 端口（默认交给 trae_pool）")
    ap.add_argument("--write-done", action="store_true",
                    help="落事件（wb-<卡>.done / trae-<卡>.stopped / 通知流 / trae-watch.jsonl）；"
                         "不给 = 只读，一个字节不写")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="每拍打一行 JSON（键名固定：at/card/state/icon/bodyLen/bodyHash/why）")
    args = ap.parse_args(argv)

    task, card = args.task.strip(), args.card.strip()
    if not task or not card:
        print("[FAIL] --task / --card 不能为空", file=sys.stderr)
        return EXIT_USAGE
    root = Path(args.root)
    tree = Path(args.tree) if args.tree else None
    if not args.as_json:
        print(f"[看 ] Trae 看守：task={task!r} card={card} "
              f"树={tree.as_posix() if tree else '（没给，只看正文）'} "
              f"门槛 {args.stale_min:g} 分钟 / 每 {args.interval:.0f} 秒采一次 / "
              f"超时 {args.timeout / 60:.0f} 分钟 / write_done={args.write_done}", flush=True)
    return watch(task=task, card=card, root=root, tree=tree, interval=args.interval,
                 timeout=args.timeout, stale_min=args.stale_min, write_done=args.write_done,
                 port=args.port, emit=lambda line: print(line, flush=True), as_json=args.as_json)


if __name__ == "__main__":
    raise SystemExit(main())
