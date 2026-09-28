r"""一屏现状（卡 078 · T-G173）—— 给主控用：一眼看清这棵树现在什么样。

为什么有它：主控接手/派活之前要现查的那几样东西（HEAD、锁、在跑的派活器与门禁、最近提交、
Trae 池余额）散在五六个命令里，每次现敲既慢又容易漏。这一条命令把它们收进 ≤30 行。

一句话：HEAD / 分支 / 脏 / 外来未跟踪 / 锁 / 在跑的派活器 / 在跑的门禁 / 最近 5 条提交 / Trae 余额。

    python -X utf8 harness/wb_state.py

★ 一律**只读**：不许杀进程、不许占端口、不许写任何文件。
★ Trae 余额：从 `%LOCALAPPDATA%` 下读不到就算了，打 `(需 IDE 在跑)` —— **不许为此去起 IDE**。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import manifest

ROOT = manifest.ROOT
NO_WINDOW = {"creationflags": 0x08000000} if os.name == "nt" else {}


def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    done = subprocess.run(
        cmd, cwd=str(cwd or ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", **NO_WINDOW,
    )
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def _git(*args: str) -> str:
    rc, out = _run(["git", "-c", "core.quotepath=false", *args])
    return out.strip() if rc == 0 else ""


def line_head() -> str:
    sha = _git("rev-parse", "--short", "HEAD") or "?"
    branch = _git("rev-parse", "--abbrev-ref", "HEAD") or "?"
    porc = [ln for ln in _git("status", "--porcelain").splitlines() if ln.strip()]
    tracked = [ln for ln in porc if not ln.startswith("??")]
    untracked = [ln for ln in porc if ln.startswith("??")]
    return (f"HEAD {sha} · 分支 {branch} · 脏(tracked) {len(tracked)}"
            f" · 外来未跟踪 {len(untracked)}")


def line_lock() -> str:
    # 锁脚本路径是项目胶水（原件写死 gates/diag/gate_lock.py）—— 从 harness.toml 读；
    # 脚本不在盘上时 rc!=0、out 为空，沿用原件的软兜底文案（占位串就用配置里的路径字面值）。
    lock_script = manifest.get("paths.gate_lock")
    rc, out = _run([sys.executable, "-P", "-X", "utf8",
                    lock_script, "status"])
    text = out.strip().splitlines()
    head = text[0].strip() if text else f"({lock_script} 没有输出)"
    return f"锁：{head}"


def _processes() -> list[tuple[str, str]]:
    """(pid, 命令行) 列表 —— Windows 用 PowerShell 现读，其它平台退回 ps。"""
    if os.name == "nt":
        cmd = ["powershell", "-NoProfile", "-Command",
               "Get-CimInstance Win32_Process | "
               "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"]
        rc, out = _run(cmd)
        if rc != 0 or not out.strip():
            return []
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return []
        if isinstance(data, dict):
            data = [data]
        out2: list[tuple[str, str]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            cl = item.get("CommandLine") or ""
            out2.append((str(item.get("ProcessId", "")), cl))
        return out2
    rc, out = _run(["ps", "-axo", "pid=,args="])
    pairs = []
    for ln in out.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        pid, _, args = ln.partition(" ")
        pairs.append((pid, args))
    return pairs


def lines_procs() -> list[str]:
    procs = _processes()
    if not procs:
        return ["在跑的派活器：无法枚举进程（PowerShell/ps 不可用）",
                "在跑的门禁：无法枚举进程（PowerShell/ps 不可用）"]
    # 认哪两个进程按 harness.toml 的派活器目录 / 门禁脚本文件名走（原件写死这两个字符串）。
    dispatcher_name = (Path(manifest.get("paths.workbench")) / "wb_dispatch.py").name
    gates_name = Path(manifest.get("paths.gates_runner")).name
    dispatch = [(p, c) for p, c in procs if dispatcher_name in c]
    gates = [c for _p, c in procs if gates_name in c]
    out = [f"在跑的派活器：{len(dispatch)} 个（命令行含 {dispatcher_name}）"]
    for pid, cmd in dispatch:
        m = re.search(r"--card\s+(\S+)", cmd)
        out.append(f"  · pid={pid} card={m.group(1) if m else '?'}")
    out.append(f"在跑的门禁：{len(gates)} 个（命令行含 {gates_name}）")
    return out


def lines_commits(n: int = 5) -> list[str]:
    out = _git("log", f"-{n}", "--format=%h %s")
    if not out:
        return ["最近 5 条提交：（取不到）"]
    lines = ["最近 5 条提交："]
    lines += [f"  {ln}" for ln in out.splitlines() if ln.strip()]
    return lines


def line_trae() -> str:
    """Trae 池余额 —— 读不到就打占位（不为此起 IDE）。"""
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return "Trae 池余额：(需 IDE 在跑)"
    home = Path(base)
    for rel in ("Trae/balance.json", "Trae CN/balance.json", "trae_pool/balance.json"):
        cand = home / rel
        if not cand.exists():
            continue
        try:
            data = json.loads(cand.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        val = data.get("balance") if isinstance(data, dict) else data
        return f"Trae 池余额：{val}（读自 {cand}）"
    return "Trae 池余额：(需 IDE 在跑)"


def main() -> int:
    try:
        lines = [line_head(), line_lock(), *lines_procs(), *lines_commits(), line_trae()]
    except manifest.ManifestError as exc:
        # harness.toml 写错（缺键/路径名拼错）必须是**人话**，不许抛栈或静默兜底。
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2
    for ln in lines:
        print(ln, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
