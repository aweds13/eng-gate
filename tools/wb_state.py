r"""一屏现状（卡 078 · T-G173）—— 给主控用：一眼看清这棵树现在什么样。

为什么有它：主控接手/派活之前要现查的那几样东西（HEAD、锁、在跑的派活器与门禁、最近提交、
Trae 池余额）散在五六个命令里，每次现敲既慢又容易漏。这一条命令把它们收进 ≤30 行。

一句话：HEAD / 分支 / 脏 / 外来未跟踪 / **白名单对账** / 锁 / 在跑的派活器 / 在跑的门禁 /
最近 5 条提交 / Trae 余额。

    python -X utf8 tools/wb_state.py

★ 一律**只读**：不许杀进程、不许占端口、不许写任何文件。
★ 白名单对账（卡 132 · T-G229）：把本仓那份名单（`wb_dispatch` 的裸名）与号池那份
  （`pool.models` 的 `provider/model`）**并排**列出，漂了就 `⚠`、一致就 `✓`。**只报告、不改名单**。
★ Trae 余额：从 `%LOCALAPPDATA%` 下读不到就算了，打 `(需 IDE 在跑)` —— **不许为此去起 IDE**。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

ROOT = Path(__file__).resolve().parent.parent
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


def _local_whitelist() -> list[str]:
    """本仓那份名单（CLI 层的硬闸门常量 `MODEL_WHITELIST` ∪ `ONE_OFF_MODELS`）。

    ★ 惰性 import：`wb_dispatch` 是 CLI 层，只在真要读名单时才引；且**不在 `pool.models`
      里反向 import 它**（那是分层倒置）—— 名字由这里读出来、**传**给对账函数。
    """
    import wb_dispatch  # tools/ 已在 sys.path 上（脚本入口 / 测试都会挂）

    return list(wb_dispatch.MODEL_WHITELIST) + list(wb_dispatch.ONE_OFF_MODELS)


def _pool_roster() -> dict[str, Any]:
    """仓外那份批准集（`load_pool_models()` 的返回值）；号池目录找不到时回空批准集。"""
    from pool import models as pool_models

    pool = pool_models.find_pool_dir(ROOT)
    if pool is None:
        return {"approved": [], "pool_dir": ""}
    return pool_models.load_pool_models(pool)


def roster_line(local_names: Iterable[str], pool_models: dict[str, Any]) -> str:
    """对账那一行的**纯格式**：吃两份数据 → 一行字（漂 / 一致都行）。"""
    from pool import models as pool_models_mod

    local = "、".join(local_names) or "(空)"
    pool = "、".join(pool_models.get("approved") or []) or "(空)"
    seen = f"本仓[{local}] ｜ 池[{pool}]"
    problems = pool_models_mod.compare_rosters(local_names, pool_models)
    if not problems:
        return f"✓ 白名单对账：一致（{seen}）"
    return f"⚠ 白名单对账：{'；'.join(problems)}（{seen}）"


def line_roster() -> str:
    """白名单对账行 —— 现读两份名单再对账。★ 面板不许因为这一行整个崩，故兜底成「无法判断」。"""
    try:
        return roster_line(_local_whitelist(), _pool_roster())
    except Exception as exc:  # 只读面板：读不到就如实说读不到，别整个崩
        return f"白名单对账：无法判断（{exc}）"


def line_lock() -> str:
    rc, out = _run([sys.executable, "-P", "-X", "utf8",
                    "gates/diag/gate_lock.py", "status"])
    text = out.strip().splitlines()
    head = text[0].strip() if text else "(gates/diag/gate_lock.py 没有输出)"
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
    dispatch = [(p, c) for p, c in procs if "wb_dispatch.py" in c]
    gates = [c for _p, c in procs if "run_gates.py" in c]
    out = [f"在跑的派活器：{len(dispatch)} 个（命令行含 wb_dispatch.py）"]
    for pid, cmd in dispatch:
        m = re.search(r"--card\s+(\S+)", cmd)
        out.append(f"  · pid={pid} card={m.group(1) if m else '?'}")
    out.append(f"在跑的门禁：{len(gates)} 个（命令行含 run_gates.py）")
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
    lines = [line_head(), line_roster(), line_lock(), *lines_procs(), *lines_commits(), line_trae()]
    for ln in lines:
        print(ln, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
