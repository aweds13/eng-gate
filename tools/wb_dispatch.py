r"""派活给 WorkBuddy / CodeBuddy CLI（外包链路的第 ② 步）—— 带四道前置检查。

为什么要有它（2026-09-26，T-G82）：派活是**别人替我改工作区**的动作，手工敲命令有三个坑，
三个都真发生过或真会咬：
  ① 在**脏工作区**里派活 → 工人和我的未提交改动混在一起分不清（"一写一读"当场失效）；
  ② **没登录**就派 → 白等一轮，只拿到一句 `Authentication required`（T-G80 实测）；
  ③ 派活不留痕 / 覆盖上一轮的 log → 之后没人说得清它到底干了什么。

所以这个脚本把四道检查放在**真跑之前**，任何一道不过就**不派活**并说清原因：
  ① `--spec` 指的卡规格文件必须存在（不许凭记忆派活）；
  ② `git status --porcelain -uno` 必须**空**（未跟踪文件不算，那两个是别的窗口放的）；
  ③ 轻量登录自检（真发一条极短请求，认出 `Authentication required`）；
  ④ `gates/diag/wb-<卡号>.jsonl` 不存在（要覆盖得显式 `--force`，证据不许被悄悄盖掉）。

用法（默认 **dry-run**：只打印将要执行的命令，不派活）：
    python -X utf8 tools/wb_dispatch.py --card 001 --spec 复盘/外包卡-001-独立复核T-G79.md
    # 真想派活加 --execute；跑完会自动用 tools/wb_status.py 渲染时间线
    # --model 默认 deepseek-v4.1-flash（用户 2026-09-26 要的那一档；★ CLI 2.158.0 的可用列表里
    # 已经没有 deepseek-v3-2-volc 了 —— 默认模型是 hy4-preview，实测 JSON 里回的是 hy4-preview-f）
    # --cli 覆盖 CLI 入口；--permission-mode 默认 bypassPermissions（见下）
    # --no-preflight 跳过登录自检（省 10 秒，接口不改）

★ 2026-09-26 实测两条（都写进 复盘/外包-卡表与规矩.md §10）：
  · **CLI 入口优先独立安装的那份**（`%APPDATA%` 下 npm 装的 `@tencent-ai/codebuddy-code`）——
    WorkBuddy 自带那份是**无头版**：缺 `dist/codebuddy.js`（TUI），`config`/`doctor`/`install`
    全报 `Cannot find module '../dist/codebuddy'`，也没有 `/login` 可敲；
  · **`-y` 不够**：工人要用 `python …` 跑测试时会被"非交互无法确认"挡回来（它自己提示改用
    `--permission-mode bypassPermissions`）→ 这是默认值；想收紧就显式给别的模式。

★ 边界（如实写）：**`--execute` 现在真跑过两轮了**（卡 001 只读复核、卡 002 写卡修 T-G79 → T-G86），
所以"命令拼装 + 真机派活"不再是纸面推理；但**看门狗那条路（真掐）还没在真工人身上触发过** ——
这里用桩命令真跑一遍，钉住"静默 → 掐掉 + 报现场"这条行为（`tests/test_wb_dispatch.py`）。

★ 反空转三道（T-G88 建 · **T-G89 更正标定**，用户 2026-09-26 点名要的"心跳"）：工人在**别的进程**
里干活，主控看得见的只有它落的 log，所以三道护栏全建在这份 log 上：
  ① **回合上限** —— `--max-turns`（写卡 **240** / 只读卡 **80**）。★ 口径是探针量出来的：它数的是
     **工具调用回合**（卡 002 实测 88~111），**不是** `result` 里的 `num_turns`（那是**另一个**
     计数器，卡 002 = 319 —— 照它定会把上限放到天上）。撞上限时 CLI 给的是
     `subtype = error_during_execution` + **空回话** + **退出码仍是 0** → 所以跑完既数回合（预警）
     也读 `result` 事件（硬证据），别把腰斩当成功。
  ② **看门狗** —— 跑的时候盯着：日志**静默 ≥ 8 分钟**（卡死）或最近 12 次工具调用里
     **同一件事出现 ≥ 5 次**（空转）→ 掐掉整棵进程树，并把现场（最后几步、碰过哪些文件）报出来。
  ③ **心跳** —— 每 2 分钟一行（已跑多久 / 回合 / 工具 / 碰过文件 / 静默多少秒）：
     让"它还在动"从猜测变成看得见的事实。
两个默认值按用户 2026-09-26 的决定：`--autocompact 1m`（CLI 钳位 100k–1M）、
`--effort` **不加**（保持默认 High）；两条都对着 CLI 2.158.0 的 `--help` 核过。
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_status  # noqa: E402 —— 同一个目录，渲染复用状态器（别写第二份）

DEFAULT_MODEL = "deepseek-v4.1-flash"
NODE_REL = r".workbuddy\binaries\node\versions\22.22.2-3\node.exe"
# ★ 优先用**独立安装**的 CodeBuddy CLI（官方 npm 包，带 TUI、能登录）：
#   WorkBuddy 自带那份是**无头版**（缺 dist/codebuddy.js，`config`/`doctor`/`install` 全废、
#   也没有 `/login` 可敲）—— 2026-09-26 实测，见 复盘/外包-卡表与规矩.md §10。
NPM_CLI_PARTS = ("npm", "node_modules", "@tencent-ai", "codebuddy-code", "bin", "codebuddy")
FALLBACK_CLI_REL = r"workbuddy\resources\app.asar.unpacked\cli\bin\codebuddy"
# 工人要跑 pytest / 脚本，`-y` 不够（实测 `python …` 会被"非交互无法确认"挡回来）
DEFAULT_PERMISSION_MODE = "bypassPermissions"
AUTH_NEEDLE = "Authentication required"

# ---------------------------------------------------------------- 反空转三道的默认值
# ★ 标定口径（T-G88 初版 → **T-G89 更正**，两处真机探针量出来的）：
#   `--max-turns` 数的是**工具调用回合**，不是 `result` 事件里的 `num_turns` —— 那是**另一个**
#   计数器（卡 002 实测 `num_turns`=319，而工具回合只有 88~111）。初版差点照 90 定 150，
#   更正后又差点照 319 定 600；两次都是探针拦下的。
#   探针（真机）：给一个要跑 6 条命令的活 + `--max-turns 2` → 只跑了 **2 次**工具调用，
#   `result.subtype = error_during_execution`、**回话是空的**、而**退出码仍是 0**。
DEFAULT_MAX_TURNS_WRITE = 240    # ≈ 2.2 × 卡 002 的 111 次工具调用
DEFAULT_MAX_TURNS_READONLY = 80
DEFAULT_AUTOCOMPACT = "1m"       # 用户 2026-09-26 定的；CLI 钳位 100k–1M
STALL_SECONDS = 480              # 日志静默多久算卡死（8 分钟）
REPEAT_WINDOW = 12               # 空转只看最近多少次工具调用
REPEAT_NEED = 5                  # 同一件事在里面出现几次算空转
HEARTBEAT_SECONDS = 120          # 心跳行间隔
POLL_SECONDS = 5.0               # 看门狗多久醒一次
SCENE_LINES = 6                  # 掐掉时报最后几步

OPENING = (
    "读 复盘/交接-重构进度.md + 复盘/长任务执行协议.md + 复盘/新窗口交接卡.md + "
    "复盘/外包-卡表与规矩.md + {spec}（这一张卡的规格）。你有完整 CLI、工具链与主控相同。"
    "★ **以卡规格为准**：它写了这一轮能改哪些文件、能不能提交、要不要跑全量门禁、禁区是什么；"
    "规格与本句冲突时，按规格执行。干完按规格要求回报。卡号 {card}。"
)


def paths(cli_override: str | None = None) -> tuple[Path, Path]:
    """（内置 node, CLI 入口）—— 默认优先独立安装的那份，找不到才退回 WorkBuddy 自带的。"""
    home = Path(os.environ.get("USERPROFILE", str(Path.home())))
    node = home / NODE_REL
    if cli_override:
        return node, Path(cli_override)
    appdata = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
    npm_cli = appdata.joinpath(*NPM_CLI_PARTS)
    if npm_cli.exists():
        return node, npm_cli
    return node, Path("D:/") / FALLBACK_CLI_REL


def git_dirty() -> list[str]:
    """被跟踪文件里有没有未提交改动（未跟踪文件不算：那两个是别的窗口放的）。"""
    done = subprocess.run(
        ["git", "status", "--porcelain", "-uno"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return [ln for ln in (done.stdout or "").splitlines() if ln.strip()]


def auth_ok(node: Path, cli: Path, timeout: int = 180) -> tuple[bool, str]:
    """真发一条极短请求 —— 登录没通就当场认出来（别把一轮白等当成"工人在想"）。"""
    done = subprocess.run(
        [str(node), str(cli), "-p", "只回复四个字：连接成功", "--output-format", "text",
         "--no-session-persistence", "-y"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout,
    )
    body = f"{done.stdout or ''}\n{done.stderr or ''}"
    if AUTH_NEEDLE in body:
        return False, "登录没通（Authentication required）→ 先在 TUI 里敲 /login（T-G80）"
    if "连接成功" in body:
        return True, "登录自检通过"
    return False, f"自检没拿到预期回话（退出码 {done.returncode}）：{wb_status._clip(body, 200)}"


def build_command(node: Path, cli: Path, card: str, spec: str, model: str,
                  permission_mode: str = DEFAULT_PERMISSION_MODE, *,
                  max_turns: int = DEFAULT_MAX_TURNS_WRITE,
                  autocompact: str = DEFAULT_AUTOCOMPACT) -> list[str]:
    return [
        str(node), str(cli), "-p", OPENING.format(spec=spec, card=card),
        "--model", model, "--output-format", "stream-json",
        "--permission-mode", permission_mode,
        # ① 回合上限：撞到了 CLI 会自己停（退出码仍是 0，所以跑完还要判"没做完"）
        "--max-turns", str(max_turns),
        # 用户 2026-09-26 定：上下文窗口按 1M 自动压缩（`--effort` 不加 = 保持默认 High）
        "--autocompact", autocompact,
        "--no-session-persistence", "-y",
    ]


# ================================================================ 反空转三道（T-G88）


def max_turns_default(read_only: bool) -> int:
    """写卡 240 / 只读卡 80 —— 依据：卡 002 实测 **111 次工具调用**（≈ 88~111 工具回合）才收工。"""
    return DEFAULT_MAX_TURNS_READONLY if read_only else DEFAULT_MAX_TURNS_WRITE


def turns_seen(lines: list[str]) -> int:
    """数"回合"：`assistant` 事件的 `message.id` **去重**。

    卡 002 实测：206 条事件 → 90 个回合，其中 88 条带工具调用。
    这是 `--max-turns` 那个计数的**近似**（它的口径是工具调用回合），用来在心跳/预警里说进度。
    ★ 别拿 `result` 里的 `num_turns` 当这个数：那是**另一个**计数器（卡 002 = 319），
    不是上限比的那一格。对方要是改了格式、没带 `message.id`，就退回"数 assistant 事件" ——
    那会**多算**，所以这个值只用来预警"撞上限了"，不用来卡人（判据宁可保守）。
    """
    ids: set[str] = set()
    seen_events = 0
    for raw in lines:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "assistant":
            continue
        seen_events += 1
        mid = (event.get("message") or {}).get("id")
        if mid:
            ids.add(str(mid))
    return len(ids) if ids else seen_events


def tool_signatures(lines: list[str]) -> list[str]:
    """每次工具调用压成一个签名 `名字|参数` —— 空转判据拿它比"是不是在重复同一件事"。"""
    out: list[str] = []
    for raw in lines:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "assistant":
            continue
        content = (event.get("message") or {}).get("content")
        for item in content if isinstance(content, list) else []:
            if not isinstance(item, dict) or item.get("type") != "tool_use":
                continue
            payload = item.get("input") or {}
            try:
                blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
            except (TypeError, ValueError):
                blob = str(payload)
            out.append(f"{item.get('name')}|{blob}")
    return out


def repeat_signal(signatures: list[str], *, window: int = REPEAT_WINDOW,
                  need: int = REPEAT_NEED) -> tuple[int, str] | None:
    """最近 `window` 次调用里同一个（工具+参数）出现了 ≥ `need` 次 → `(次数, 签名)`。

    连着来 5 次算，A,B,A,B,… 交替 5 次也算（这就是按"窗口内计数"而不是"数末尾连续"的理由）。
    ★ 边界（如实写）：只抓**完全一样**的调用；参数每次差一点点的"原地打转"抓不到 ——
    那一类靠静默超时兜底（两条判据互为补集）。
    """
    tail = signatures[-window:]
    if not tail:
        return None
    sig, count = Counter(tail).most_common(1)[0]
    return (count, sig) if count >= need else None


def watchdog_verdict(*, silent_seconds: float, signatures: list[str],
                     stall_seconds: int = STALL_SECONDS, window: int = REPEAT_WINDOW,
                     need: int = REPEAT_NEED) -> str:
    """**在跑的时候**该不该把它掐了 —— 返回原因（空串 = 健康）。① 卡死 ② 空转。"""
    if silent_seconds >= stall_seconds:
        return (f"卡死：{silent_seconds / 60:.1f} 分钟没有新事件"
                f"（阈值 {stall_seconds / 60:.1f} 分钟）")
    repeat = repeat_signal(signatures, window=window, need=need)
    if repeat:
        count, sig = repeat
        return (f"空转：最近 {window} 次工具调用里同一件事出现了 {count} 次"
                f"（阈值 {need}）—— {wb_status._clip(sig, 120)}")
    return ""


def cap_verdict(turns: int, max_turns: int) -> str:
    """**跑完之后**：回合数撞到上限 = **没做完**（CLI 会自己停，退出码还是 0，别当成功）。"""
    if turns >= max_turns:
        return (f"没做完：回合数 {turns} 撞到上限 {max_turns}"
                f"（`--max-turns` 到了 CLI 会自己停，退出码仍是 0）")
    return ""


def finish_verdict(lines: list[str]) -> str:
    """从 stream 的 `result` 事件判「这一轮**到底跑完了没有**」—— 退出码 0 不等于干完了。

    ★ 真机实测（T-G89 探针）：撞 `--max-turns` 上限时 CLI 给的是
    `result.subtype = error_during_execution`、**回话是空的**，而**进程退出码仍是 0**。
    只看退出码就会把"腰斩"当成成功。所以判据读事件本身：
      ① 整段 log 里没有 `result` 事件 → 没跑完（被打断 / 被杀 / 还在跑）；
      ② `subtype != success` → 中途停下（撞上限、被中断、工具连环失败）；
      ③ 回话是空的 → 没交出东西。
    ★ 两条判据（数回合 vs 读事件）是**互补**的：数回合能提前预警，读事件才是硬证据。
    """
    result: dict | None = None
    for raw in lines:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") == "result":
            result = event
    if result is None:
        return "没跑完：整段 log 里没有 `result` 事件（进程被打断 / 被杀 / 还在跑）"
    subtype = str(result.get("subtype") or "")
    text = str(result.get("result") or "").strip()
    if subtype != "success":
        detail = f"回话：{wb_status._clip(text, 120)}" if text else "回话是空的"
        return (f"没跑完：`result.subtype = {subtype or '（空）'}`"
                f"（撞 `--max-turns` 上限时就是这个，而退出码仍是 0）—— {detail}")
    if not text:
        return "没跑完：`subtype = success` 但回话是空的 —— 没交出东西"
    return ""


def heartbeat_line(*, elapsed: float, turns: int, tool_calls: int, files: int,
                   silent_seconds: float) -> str:
    """心跳一行 —— 让"它还在动"变成看得见的事实（而不是主控干等）。"""
    return (f"[心跳] 已跑 {elapsed / 60:.1f} 分钟 | 回合 {turns} | 工具 {tool_calls} 次 | "
            f"碰过文件 {files} 个 | 日志静默 {silent_seconds:.0f} 秒")


def kill_tree(pid: int) -> str:
    """掐掉**整棵进程树**（按 PID，不按进程名 —— 按名字会误伤同名的别的进程）。

    Windows 走 `taskkill /F /T`；别的平台退回 `os.kill`。掐完返回一句人话（原因照实说）。
    """
    if os.name == "nt":
        done = subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        body = (done.stdout or done.stderr or "").strip().splitlines()
        return body[0] if body else f"taskkill 退出码 {done.returncode}"
    os.kill(pid, signal.SIGKILL)
    return f"已给 {pid} 发 SIGKILL"


def _pump(stream, log: Path, lines: list[str], lock: threading.Lock,
          state: dict[str, float]) -> None:
    """读线程：工人每吐一行就**立刻落盘**并喂给判据（主控不必等它跑完才看得见）。"""
    with log.open("w", encoding="utf-8") as out:
        for raw in stream:
            out.write(raw)
            out.flush()
            with lock:
                lines.append(raw.rstrip("\n"))
                state["last_at"] = time.monotonic()


def run_worker(cmd: list[str], log: Path, errlog: Path, *, timeout: int, max_turns: int,
               watchdog: bool = True, heartbeat_seconds: int = HEARTBEAT_SECONDS,
               stall_seconds: int = STALL_SECONDS, poll_seconds: float = POLL_SECONDS,
               printer: Callable[[str], None] = print) -> tuple[int, str, str]:
    """真跑工人并且**盯着它** —— 返回 `(退出码, 掐掉/超时/撞上限的原因, 现场)`。

    为什么不是一句 `subprocess.run(stdout=file)`（T-G82 的老写法）：那样主控在它跑的那一小时里
    **什么都看不见** —— 卡死了在等、空转烧时间也在等，而这两种"等"都不该发生。
    所以改成 Popen + 读线程（逐行落盘、顺手喂判据）+ 主循环（心跳 / 看门狗 / 超时）。

    ★ 边界（如实写）：判据每轮把已落的 log **整段重解析**（简单、够快：卡 002 那种量级
    300 多条事件，解析一遍是毫秒级）；真跑出几万条事件再谈增量。
    """
    log.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    state: dict[str, float] = {"last_at": time.monotonic()}
    lock = threading.Lock()
    reason = ""

    errlog.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    last_beat = started
    with errlog.open("w", encoding="utf-8") as err:
        proc = subprocess.Popen(          # noqa: S603 —— 命令是本地拼好的 CLI，不是外部输入
            list(cmd), cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=err, text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        pump = threading.Thread(target=_pump, args=(proc.stdout, log, lines, lock, state),
                                daemon=True)
        pump.start()
        try:
            while True:
                try:
                    # 用 wait(timeout=…) 而不是 sleep：工人收工就**立刻**返回，
                    # 不必白等一个轮询周期（否则每一轮派活都要多搭最多 poll_seconds）
                    proc.wait(timeout=poll_seconds)
                    break
                except subprocess.TimeoutExpired:
                    pass
                now = time.monotonic()
                if now - started >= timeout:
                    reason = f"超时：{timeout} 秒到了（`--timeout`）"
                    break
                with lock:
                    snapshot = list(lines)
                    silent = now - state["last_at"]
                if watchdog:
                    verdict = watchdog_verdict(silent_seconds=silent, signatures=snapshot,
                                               stall_seconds=stall_seconds)
                    if verdict:
                        reason = verdict
                        break
                if heartbeat_seconds and now - last_beat >= heartbeat_seconds:
                    last_beat = now
                    sigs = tool_signatures(snapshot)
                    _, hb = wb_status.parse_events(snapshot)
                    printer(heartbeat_line(
                        elapsed=now - started, turns=turns_seen(snapshot),
                        tool_calls=len(sigs), files=hb["files_total"],
                        silent_seconds=silent))
        finally:
            gone = proc.poll() is not None
            killed = "（它已经自己退出了，不用掐）" if gone else ""
            if reason and not gone:
                killed = kill_tree(proc.pid)
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:      # 掐都掐不动：如实说，不假装
                    killed += "（等它退出超时 30 秒）"
            code = proc.wait()
            pump.join(timeout=10)
    with lock:
        snapshot = list(lines)

    if reason:
        return code, f"{reason} → {killed}", _scene(snapshot)
    return code, cap_verdict(turns_seen(snapshot), max_turns) or finish_verdict(snapshot), ""


def _scene(lines: list[str]) -> str:
    """掐掉那一刻的现场：最后几步 + 它碰过哪些文件（主控据此判断"卡在哪一步"）。"""
    timeline, summary = wb_status.parse_events(lines)
    tail = timeline[-SCENE_LINES:]
    files = "、".join(summary["files"]) or "（没碰过文件）"
    return ("\n".join(f"    {ln}" for ln in tail)
            + f"\n    碰过的文件（{summary['files_total']} 个）：{files}"
            + f"\n    工具调用 {summary['tool_calls']} 次；"
            + f"认不出的行 {summary['unknown_events']} 条")


def preflight(card: str, spec: str, *, force: bool, check_auth: bool,
              cli_override: str | None = None) -> tuple[list[str], Path]:
    """四道检查 —— 返回（问题清单, 日志路径）。问题非空就不许派活。"""
    problems: list[str] = []
    node, cli = paths(cli_override)
    log = ROOT / "gates" / "diag" / f"wb-{card}.jsonl"
    if not (ROOT / spec).exists():
        problems.append(f"卡规格文件不存在：{spec}（不许凭记忆派活）")
    if not node.exists():
        problems.append(f"找不到内置 node：{node}")
    if not cli.exists():
        problems.append(f"找不到 CLI：{cli}")
    dirty = git_dirty()
    if dirty:
        problems.append(f"工作区不干净（{len(dirty)} 个被跟踪文件有改动）→ 一写一读："
                        f"先提交或收起它们：{', '.join(dirty[:5])}")
    if log.exists() and not force:
        problems.append(f"这一轮的 log 已存在：{log}（要覆盖请 --force —— 证据不许被悄悄盖掉）")
    if check_auth and not problems:
        ok, why = auth_ok(node, cli)
        if not ok:
            problems.append(why)
    return problems, log


def main() -> int:
    parser = argparse.ArgumentParser(description="派活给 CodeBuddy CLI（默认 dry-run）")
    parser.add_argument("--card", required=True, help="卡号（用来命名 log，如 001）")
    parser.add_argument("--spec", required=True, help="卡规格文件（相对仓库根）")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--cli", default=None,
                        help="CLI 入口覆盖（默认优先用独立安装的那份）")
    parser.add_argument("--permission-mode", default=DEFAULT_PERMISSION_MODE,
                        help="工人的权限模式（默认 bypassPermissions：否则 python 会被挡回来）")
    parser.add_argument("--execute", action="store_true",
                        help="真派活（默认只做前置检查 + 打印命令）")
    parser.add_argument("--force", action="store_true", help="允许覆盖已有 log")
    parser.add_argument("--no-preflight", action="store_true", help="跳过登录自检")
    parser.add_argument("--timeout", type=int, default=3600, help="工人最长跑多久（秒）")
    parser.add_argument("--max-turns", type=int, default=0,
                        help="回合上限（0 = 按卡种取默认：写卡 150 / 只读卡 60）")
    parser.add_argument("--read-only", action="store_true",
                        help="这是一张只读卡 → 回合上限默认取 60（预算，不是安全边界）")
    parser.add_argument("--autocompact", default=DEFAULT_AUTOCOMPACT,
                        help="自动压缩窗口（默认 1m；CLI 钳位 100k-1M）")
    parser.add_argument("--heartbeat-seconds", type=int, default=HEARTBEAT_SECONDS,
                        help="心跳行间隔（秒；0 = 不打）")
    parser.add_argument("--stall-seconds", type=int, default=STALL_SECONDS,
                        help="日志静默多久算卡死（秒）")
    parser.add_argument("--poll-seconds", type=float, default=POLL_SECONDS,
                        help="看门狗多久醒一次（秒）")
    parser.add_argument("--no-watchdog", action="store_true",
                        help="关掉看门狗（卡死/空转不再自动掐；心跳仍在）")
    args = parser.parse_args()

    problems, log = preflight(
        args.card, args.spec, force=args.force, check_auth=not args.no_preflight,
        cli_override=args.cli,
    )
    node, cli = paths(args.cli)
    max_turns = args.max_turns or max_turns_default(args.read_only)
    cmd = build_command(node, cli, args.card, args.spec, args.model, args.permission_mode,
                        max_turns=max_turns, autocompact=args.autocompact)

    if problems:
        print("[FAIL] 不派活 —— 前置检查没过：", file=sys.stderr)
        for item in problems:
            print(f"  · {item}", file=sys.stderr)
        return 2

    done_checks = "规格在 / 工作区干净 / log 未占用"
    if args.no_preflight:
        done_checks += " / **登录没查**（--no-preflight）"
    else:
        done_checks += " / 登录通"
    print(f"[OK ] 前置检查全过（{done_checks}）")
    print(f"[log ] {log}")
    print(f"[cmd ] {' '.join(cmd[:4])} … --model {args.model} --output-format stream-json "
          f"--permission-mode {args.permission_mode} --max-turns {max_turns} "
          f"--autocompact {args.autocompact}")
    guards = ("看门狗**关**（--no-watchdog）" if args.no_watchdog else
              f"看门狗：日志静默 {args.stall_seconds}s 或最近 {REPEAT_WINDOW} 次调用里同一件事"
              f"重复 {REPEAT_NEED} 次 → 掐")
    print(f"[盯 ] {guards}；心跳每 {args.heartbeat_seconds}s；超时 {args.timeout}s")
    if not args.execute:
        print("[dry ] 这是 dry-run；真想派活加 --execute")
        return 0

    errlog = log.with_suffix(".stderr.txt")
    code, reason, scene = run_worker(
        cmd, log, errlog, timeout=args.timeout, max_turns=max_turns,
        watchdog=not args.no_watchdog, heartbeat_seconds=args.heartbeat_seconds,
        stall_seconds=args.stall_seconds, poll_seconds=args.poll_seconds,
    )
    print(f"[done] 工人退出码 {code}；stderr 见 {errlog.name}")
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    timeline, summary = wb_status.parse_events(lines)
    for line in timeline:
        print(line)
    print(f"[摘要] 回合 {turns_seen(lines)} 个（上限 {max_turns}）；"
          f"工具调用 {summary['tool_calls']} 次；碰过的文件 {summary['files_total']} 个；"
          f"认不出的行 {summary['unknown_events']} 条")
    if reason:
        print(f"[掐 ] {reason}", file=sys.stderr)
        print(f"     现场（最后一次动作之后的几步）：\n{scene}", file=sys.stderr)
        print(f"[复核] 先看现场再决定：python -X utf8 tools/wb_status.py {log} --tail 20 --repo",
              file=sys.stderr)
        return 6
    print(f"[复核] 主控现在去看报告与 git status：python -X utf8 tools/wb_status.py {log} --repo")
    return 0 if code == 0 else 4


if __name__ == "__main__":
    raise SystemExit(main())
