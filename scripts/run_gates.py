"""跑质量门并**落盘结果**（`gates/last.json`），供 `scripts/audit_progress.py` 核对。

为什么要落盘：以前"pytest 284 passed"只是我在报告里打的一行字，**没人能验证**。
现在门禁由脚本执行、结果结构化写到 `gates/last.json` 并随代码提交 ——
提交里的 `Gates:` trailer 就有产物支撑，换个人/换个窗口复跑也能得到同样判断。

用法（**三层速度，按需要挑**）
    python -X utf8 scripts/run_gates.py --fast   # ① 十几秒：ruff/护栏/审计（内循环，不落盘）
                                                 #    ＋ 受影响的测试选集（卡 254，能查到改动时）
    python -X utf8 scripts/run_gates.py --quick  # ② ~90 秒：跳过真机层（提交前够用）
    python -X utf8 scripts/run_gates.py          # ③ 全量（三层一起，~3 分钟；验收/封版前用它）
    python -X utf8 scripts/run_gates.py --no-reuse   # 不信复用记录，全部真跑一遍
    python -X utf8 scripts/run_gates.py --serial     # 全串行（对照"并行下偶发失败"用）

★ T-G156 三项加固（**不设新环境变量时，端口/门数/复用键/黄金/last.json 形状逐字不变**）
  1. `TF_GATE_PORT_BASE`（**可选旁路**）：不设 = 历史的 8531/8541 段；设了则整段平移
     （render BASE/BASE+1、ui_flow BASE+10..+13），于是同机多棵树各自一段、不再排队等端口。
     黄金与端口无关（`gates/render/**` 里出现 8531/8541 的份数 = 0）→ 换端口不该让黄金变。
  2. 开场清遗留：**端口段 ∩ cwd=本树根** 双判据（只掐本树端口段上的 LISTENING 进程 +
     绑这些端口的无头浏览器）；旧清法按进程名/特征（`serve.py --fresh` / `tf-flow-profile-`）
     会跨树误杀（铁律 27）。★ 双判据缺一不可：默认端口段是**多棵树共用**的，只按端口会在
     默认模式下跨树误杀（2026-09-27 真事故，见复盘）。
  3. `TF_PYTEST_WORKERS`：不设 = 按**可用内存自适应**（★ 卡 A266：可用 < 2.5 GB ⇒ 1、
     < 4 GB ⇒ 2、否则 `min(4, cpu)`；机器 32 核但只有 15.2 GB 内存，`-n auto` 会
     拉 32 个 worker → 换页）；装了 xdist 才并行，没装就串行（既有口径不动）。

★ T-G157（修 worktree 假绿）：子进程 `PYTHONPATH` 首位补上**本树 `ROOT/src`** —— 本仓是
  可编辑安装指向**主树**的 `src`，原来只塞 `sandbox_shim`，于是 worktree 里 `render` / `ui_flow` /
  `ui_dom_probe` / `web_live` / `lf1_live` 验的是**主树的页面**（同源黄金一比必绿）→ 假绿。
  见 `tree_pythonpath()` 与 `复盘/门禁假绿-PYTHONPATH-T-G157.md`。

★ T-G47 提速（判定不变，只是不再"一个速度用到底"）
  1. **三层**：`--fast`（十几秒）→ `--quick`（~90 秒）→ 全量（~3 分钟）。
     `--fast` **不写 `gates/last.json`** —— 它不是提交闸，写了就会让"门禁产物与提交一致"
     这条审计失效（那才是最坏的：用半轮结果冒充一轮）。
  2. **两条泳道并行**：轻门（pytest / ruff / mypy / 三道护栏 / 两道审计 / 两个真机 HTTP 检查）
     与浏览器层（render / ui_flow）**同时跑**。这两层互不依赖：
     各自 `serve.py --fresh`（临时库）、各自浏览器 profile（按端口分目录）、端口互不相同
     （render 8531/8532、ui_flow 8541~8544，`web_live` 的局域网自检改成自动挑空闲端口）。
     实测 412s → **~185s**（受最长的那条 ui_flow 决定，32 核机器上不构成 CPU 争用）。
  3. **输入没变就复用上次判定**（`gates/reuse.json`，**带输入哈希留痕**）：
     render / ui_flow 这类真机层的**输入是"网页资源 + 服务端 + 门上自己的脚本 + 黄金"** ——
     这些都没动时，判定**不可能**变（不是"懒得跑"，是"跑的是同一件事"）。
     ★ **pytest 永不复用**：它是唯一"从行为上证明功能还在"的那层，也是唯一能发现
       "谁动了 `src/` 却以为无关"的那层。跳过它省 66 秒，代价是把整条安全网摘掉。

pytest 会**并行**跑（装了 `pytest-xdist`；worker 数见 `TF_PYTEST_WORKERS`，不设 = 按可用内存
自适应 —— ★ 卡 A266：可用 < 2.5 GB ⇒ 1、< 4 GB ⇒ 2、否则 `min(4, cpu)`）：
用例之间没有共享状态（各自 tmp 库 + 各自进程内的事实总线），而每个用例都要起真 app + 真库 ——
串行是这里唯一的瓶颈。覆盖率照旧判 70% 那道门（pytest-cov 会合并各 worker 的数据）。

约定（与用户确认）：**门禁或审计任一不通过 → 退出码非零 → 不许提交**。

★ T-G196（卡 100，每道门加硬超时）：门禁历史病灶是**一道门卡死 = 整趟永久挂死** ——
  2026-10-01 落卡 092 时 `ui_flow` 真卡死 56 分钟（正常 386 秒），`run_gates.py` 一直等它。
  现在每道门有硬超时（`DEFAULT_DOOR_TIMEOUT` = 1800 秒；`TF_GATE_DOOR_TIMEOUT` 可覆盖，
  `0` = 关掉）：到点 → **掐掉整棵进程树**（Windows `taskkill /PID <pid> /T /F`，★ 只杀父的
  会留一堆孤儿占端口）→ 这道门记 **`exit_code = 124`** + `timeout=True`、summary 写清
  「超时 N 秒被掐」并报出门名/pid/掐了几个子进程 → **判红**（124 ≠ 0 → 整趟非 0，
  绝不当"跳过/没跑"糊过去 = 假绿）。其余门的结论照常收完（超时只掐那一棵，不吞别人的读数）。
  ★ 这一层**只加"到点就掐"**：门判据、门清单、泳道/串行结构、`input_hash()` / `REUSE_INPUTS`
  / 封存指纹**一个字不动**。测试见 `tests/test_run_gates_timeout.py`（假门 `sleep`）。

★ T-G239（卡 140）`--affected`：**自查提速** —— 只跑"被给定路径影响"的那几道门。
  来路：`复盘/架构审议-外包与门禁.md` §二 错配① + §五「A 分档」原话 —— 现在门禁只有"全量"、
  没有"哪个文件影响哪道门"的依赖图，且**判据方向是反的**（不是"多跑安全"，是"**漏跑危险**"）
  ⇒ 先立一张「**门 × 输入**」表（`DOOR_INPUTS`，见下），再据它裁。
  **判据（宁多勿漏，写进 `--help` 原文）**：
    ① 路径匹配不上任何门 ⇒ **跑全量**；② 某道门在表里**缺输入** ⇒ **那道门照跑**；③ 拿不准就多跑。
  **不许静默跳过**：`--affected` 那一趟会**明说**跑了哪几道、跳了哪几道、为什么跳，并把这份
  记账写进 `gates/last.json` 的 `affected` 块（`ok` 的语义**不动**）。
  ★★ **分工（本卡的硬要求，别越界）**：`--affected` **只给"改完一小块自查"**用（像工人跑目标
  用例那样）。一切**真的判提交**的路径 —— 收口链（`tools/wb_land.py` / `tools/pool/landing.py`）
  与"**提交前必须全量**"的约定 —— **仍然跑全量**；本卡**不改**它们，本开关也**不许**被当提交闸。
  ★ **不给 `--affected` 时**：门清单、输出结构、`last.json` 形状**逐字不变**。
"""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import dataclasses
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

# ------------------------------------------------------- 工具根 vs 数据根（卡 A326 · T-AG441）
# 以前只有一个根（`Path(__file__)…parent.parent`），于是「工具住在哪个仓」与「台账/门禁产物住在
# 哪个仓」被绑死：同一份 `tools/` 想服务别的仓，读的仍是工具自己那棵树的账。
# 现在切两刀 —— **门表跟工具走**（`gates/defs/` 是判据，属于框架），
# **产物跟数据走**（`gates/last.json`、`gates/logs/`、门命令的 cwd 与 `src/` 都是被判那个仓的）。
TOOL_ROOT = Path(__file__).resolve().parent.parent
"""工具根：门表（`gates/defs/`）、技能、脚本住的地方 —— **只用来 import 判据，不读账本**。"""

if str(TOOL_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT / "tools"))
from pipe_root import data_root  # noqa: E402 —— 数据根解析的唯一实现（卡 A326）

ROOT = data_root()
# 数据根：台账、门禁产物、`src/` 住的地方。★ 没设 `PIPE_DATA` 且当前目录不像数据根
# ⇒ 等于工具根（老行为逐字不变）。

GATES = ROOT / "gates" / "last.json"
REUSE = ROOT / "gates" / "reuse.json"
LOG_DIR = ROOT / "gates" / "logs"   # 每道门的全量输出（T-G58；不进仓库）
PY = sys.executable

# 门禁的**定义层**在 `gates/defs/`（卡 A321）：换语言换产品只动那份模块 —— 这份**跟工具根走**。
if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))
from gates.defs import contract, lang_python, product_timeflow  # noqa: E402

COMMON: list[tuple[str, list[str]]] = [
    *lang_python.GATES,
    *contract.GATES,
    *product_timeflow.GATES,
]

# 真机层：起真服务 / 真浏览器。轻的那两个（HTTP 层）跟轻门同一泳道，重的两个自己一条泳道。
REAL_PY: list[tuple[str, list[str]]] = list(product_timeflow.REAL)

# 渲染验证层（T-G32）：真浏览器把 3 档宽度 × 14 个视图各渲染一遍，采成"几何清单"与黄金逐字节比。
# 那一层里**每次采两遍**做确定性自检：不一致 = 工具自己不可信（退出码 4），不当成"界面变了"。
# 退出码 3 = 起不了真浏览器 → 记 `not_run`：**NOT RUN 不是 PASS**（last.json 单列一栏 +
# trailer 里写 NOT RUN）。
# 行为流层（T-G34）：真浏览器 + 真点击 + 真按键，把「待人工确认」里功能性的那些搬给机器。
# 每轮默认**跑两遍**（各自新库 + 新浏览器）比对断言指纹，不一致同样退 4。
BROWSER = product_timeflow.BROWSER

# ---------------------------------------------------------------- 门禁分层（卡 A321 · T-AG434）
# 19 道门不是一类东西：一半是**通用工程门**（任何改动都该过），另一半是 **timeflow 产品门**
# （五层文档 / 对比度 / 风格 / 界面文案 / 命令表 / DOM 探针 / 代理指标 / 台账标题 / 真机）。
# 分三档只是为了**内循环**少等十几分钟；`all` 仍是默认，收口链照旧跑全量。
#
# ★ 每道门**恰好属于一档**（钉子 `tests/test_run_gates_profiles.py` 会核）：
#   漏一个 ⇒ 谁都不知道它归谁管；重叠 ⇒ 「按档跑」和「全量跑」会给出不同结论。
GATE_PROFILES: dict[str, tuple[str, ...]] = {
    # 语言门：Python 仓就是这五道。换语言 ⇒ 换 `gates/defs/lang_python.py`
    "lang": tuple(n for n, _ in lang_python.GATES),
    # 契约门：判的是本仓的账（证据 / 不变量 / 标题对账）
    "audit": tuple(n for n, _ in contract.GATES),
    # 产品门：timeflow 专属，删掉整份模块框架也照样跑
    "product": (
        *(n for n, _ in product_timeflow.GATES),
        *(n for n, _ in product_timeflow.REAL),
        *product_timeflow.BROWSER,
    ),
}

# ① --fast：开发内循环用。挑的是"**改一行就能犯、且十几秒内查得出来**"的那几道 ——
# 尤其 audit（TOML/台账语法，实测犯过 5 次）与 contrast/style（照抄包时最容易抄错的令牌层）。
# ★ 卡 208：`proxy`（代理指标过期对账）也属这一类 —— 改一条 `docs/proxy-map.toml` 的
#   `last_verified` 就能犯，`proxy_audit.py --check` 十几秒查得出来。
FAST = ("ruff", "contrast", "style", "ui_text", "commands", "audit", "audit_titles", "proxy")
# 这些门是 **node 脚本**：环境里没有 node 时就跑不了 —— 统一记 `not_run`（不许静默跳过当通过）。
NODE_TOOLS = ("ui_dom_probe", "render", "ui_flow")
# 信息性检查（只报告、不阻断）—— 当前为空：`audit_titles` 已转正为阻断项（T-D2 收口）。
INFO_GATES: list[tuple[str, list[str]]] = []
SUCCESS_HINTS = ("passed", "failed", "error", "PASS", "Success", "checks passed", "OK")

# ---------------------------------------------------------------- 每道门硬超时（T-G196 / 卡 100）
# 病灶：一道门卡死 = **整趟门禁永久挂死**。2026-10-01 落卡 092 时，`ui_flow` 那道门真卡死
#   56 分钟（正常 386 秒）——`run_gates.py` 一直 `communicate()` 等它，锁租约到了也不杀，
#   只能人工按 PID 逐个核命令行再掐。这一层**只加"到点就掐"**：门判据、门清单、泳道结构、
#   输入哈希与封存指纹一个字不动。
# 默认 1800 秒；`TF_GATE_DOOR_TIMEOUT` 可覆盖（`0` = 关掉，给将来留口子）。
DEFAULT_DOOR_TIMEOUT = 1800.0

# ---------------------------------------------------------------- 内存闸（T-G198 / 卡 102）
# 病灶：跑门禁/派活**只看"我该不该跑"，不看"这台机器扛不扛得住"**。2026-10-01 晚，16.3 GB 机器上
#   并行跑两趟门禁 + 4 个 CodeBuddy 工人 + 每趟门禁的无头 Edge + serve.py，同时用户在玩游戏
#   （≈2 GB）→ 可用内存掉到 ~3 GB、MemCompression 起了 310 MB、整机慢 6 倍（pytest 884s vs 146s），
#   **用户的游戏被挤崩了一次**。
# 口径：读 **available**（可用，含可回收文件缓存），**不是 free** —— free 会把缓存算成"没内存"，
#   误拦严重（卡 102 §干活前自问）。阈值 `TF_GATE_MIN_FREE_GB`（默认 4.0；`0` = 关掉这道闸）。
# ★★ 2026-10-03 18:2x —— **用户令：默认阈值 4.0 → 2.0**（原话「把内存限制降到2G」）。
#   ★ 为什么改：这台机器上 4.0 **长期过不去**（Edge ~1.9 GB + Memory Compression ~0.9 GB +
#     Defender ~0.5 GB + 多个 DSH 实例 ~0.9 GB）⇒ 落地几乎每趟都要主控手打 `TF_GATE_MIN_FREE_GB=2.5`
#     才能开跑；那个数字反复出现在交接文档里，已经成了**靠人记**的东西。
#   ★★ **如实留痕（这是本仓自己的规矩：改阈值必须写清代价）**：这条闸当初就是为了护这台机器 ——
#     上面那段病灶记的正是「可用掉到 ~3 GB 时整机慢 6 倍、用户的游戏被挤崩过一次」。
#     ⇒ 默认降到 2.0 意味着**门禁能在只剩 2 GB 时开跑**，那是**用户本人拍板**接受的代价。
#     ★ 缓解手段（内存紧时请一并加）：`TF_PYTEST_WORKERS=1` —— 1 worker 的实际占用只几百 MB
#       （照 `_text_TG250.md` 先例）。`0` 仍可完全关掉这道闸。
DEFAULT_GATE_MIN_FREE_GB = 2.0


def available_memory_gb() -> float | None:
    """读**可用**内存（available，GB）；读不到 → None（调用方跳过这道闸，不静默当通过、也不拒跑）。

    ★ **不许依赖 `psutil`**（本仓 `pyproject.toml` 的 `dependencies` 里没有它，卡 095 已如实报过）。
    用标准库：
      - Windows：`ctypes` 的 `GlobalMemoryStatusEx` 取 `ullAvailPhys`（可用，不是空闲）；
      - 其它平台：`os.sysconf("SC_AVPHYS_PAGES") * SC_PAGE_SIZE`。
    """
    try:
        if os.name == "nt":
            import ctypes

            class _MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = _MemoryStatusEx()
            stat.dwLength = ctypes.sizeof(_MemoryStatusEx)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return None
            avail = int(stat.ullAvailPhys)
        else:
            pages = int(os.sysconf("SC_AVPHYS_PAGES"))
            size = int(os.sysconf("SC_PAGE_SIZE"))
            if pages <= 0 or size <= 0:
                return None
            avail = pages * size
    except Exception:
        return None
    return avail / (1024 ** 3) if avail > 0 else None


def gate_min_free_gb() -> float:
    """内存闸阈值（GB）：`TF_GATE_MIN_FREE_GB`（默认 2.0；`0` = 关掉这道闸）。坏值 → 退回默认。"""
    raw = os.environ.get("TF_GATE_MIN_FREE_GB", "").strip()
    if not raw:
        return DEFAULT_GATE_MIN_FREE_GB
    try:
        return float(raw)
    except ValueError:
        print(f"[WARN] TF_GATE_MIN_FREE_GB={raw!r} 不是数字 → 退回默认 "
              f"{DEFAULT_GATE_MIN_FREE_GB:g} GB", file=sys.stderr, flush=True)
        return DEFAULT_GATE_MIN_FREE_GB


def memory_gate_problem() -> str | None:
    """内存闸判据（卡 102）：可用内存 < 阈值 → 返回一句人话（调用方**拒跑**）；否则 None（放行）。

    - 阈值 `0` → 打一行"闸已关"并放行（**不静默**）；
    - 读不到内存（`available_memory_gb()` 返回 None **或抛异常**）→ 打印"读不到，闸跳过"并放行
      （★ **不静默当通过**、也**不**因此拒跑）；
    - 正常 → 打印一行读数（两个数）并放行。
    """
    threshold = gate_min_free_gb()
    if threshold <= 0:
        print("=== 内存闸：已关（TF_GATE_MIN_FREE_GB=0）—— 不静默 ===", flush=True)
        return None
    try:
        avail = available_memory_gb()
    except Exception:
        avail = None
    if avail is None:
        print(f"=== 内存闸：读不到可用内存（阈值 {threshold:.1f} GB）→ 跳过这道闸"
              "（读不到不当通过、也不拒跑）===", flush=True)
        return None
    if avail < threshold:
        return (f"可用内存 {avail:.1f} GB < 阈值 {threshold:.1f} GB → 内存不够："
                "可能压死你正在用的程序 —— 今天真把用户的游戏挤崩过。"
                "放行：TF_GATE_MIN_FREE_GB=0 关掉这道闸，或先腾出内存。")
    print(f"=== 内存闸：可用 {avail:.1f} GB ≥ 阈值 {threshold:.1f} GB，放行 ===", flush=True)
    return None


# ---------------------------------------------------------------- 端口段（T-G156 §2.1）
# 浏览器层的端口段。**默认与历史逐字一致**（render 8531/8532、ui_flow 8541~8544）；
# 设了 `TF_GATE_PORT_BASE` 才整体平移 —— 于是同一台机器上多棵树各自一段、不再排队等端口：
#     render   = BASE   / BASE+1
#     ui_flow  = BASE+10 / +11（第一遍 server/cdp）、BASE+12 / +13（第二遍）
#     流内自起的"另一台设备"：server+4 / server+6（见 ui_flow_check.mjs ㉒㉘）
#       → 落在 BASE+10..BASE+18（清遗留时一并认领）
# ★ 黄金与端口无关（实测 `git grep -l '8531' -- gates/render/` = 0）→ 换端口不该让黄金变。
DEFAULT_PORT_BASE = 8531


def port_base() -> int:
    """门禁端口段的基准。**不设 `TF_GATE_PORT_BASE` = 8531**（历史默认，逐字不变）。"""
    raw = os.environ.get("TF_GATE_PORT_BASE", "").strip()
    if not raw:
        return DEFAULT_PORT_BASE
    try:
        base = int(raw)
    except ValueError:
        print(f"[WARN] TF_GATE_PORT_BASE={raw!r} 不是整数 → 退回默认 {DEFAULT_PORT_BASE}",
              file=sys.stderr, flush=True)
        return DEFAULT_PORT_BASE
    if not (1024 <= base <= 65500):
        print(f"[WARN] TF_GATE_PORT_BASE={base} 越界（要求 1024..65500）→ 退回默认 "
              f"{DEFAULT_PORT_BASE}", file=sys.stderr, flush=True)
        return DEFAULT_PORT_BASE
    return base


def gate_port_set(base: int | None = None) -> list[int]:
    """本树这一段用到的**全部**端口（给"按端口认领"的清理用）：
    BASE / BASE+1（render）+ BASE+10..BASE+18（ui_flow 两遍 + 流内的对端）。"""
    b = port_base() if base is None else base
    return [b, b + 1, *range(b + 10, b + 19)]


# ---------------------------------------------------------------- pytest 并发（T-G156 §2.3）
# 机器 32 逻辑核、总内存只有 15.2 GB —— `-n auto` 会拉起最多 32 个 worker → 换页风险。
# 读 `TF_PYTEST_WORKERS`；不设时**按可用内存自适应**（★ 卡 A266）：可用 < 2.5 GB ⇒ 1、
# < 4 GB ⇒ 2、否则 `min(4, cpu)`。★ 显式环境变量仍然优先（给了就照给）。
# ★「没装 xdist 就串行」的既有逻辑（`xdist_available()`）一个字不动。
#
# ★★ 快与稳的账（卡 164 第 8 条 / T-G264 · 2026-10-03 实测留痕）：
#   4 worker = 126~158 秒 · 1 worker = 620~700 秒（差 ~5 倍）；4 worker 实测峰值 865 MB
#   （334+275+139+117，见卡 A266 §1.2）。
#   代价 = 第 7 条那类计时 flake（真起 `Popen` 的测试在满载下 stub 落地慢 → 看门狗误判）。
#   ★★ 卡 A266：内存紧时**不再靠人**在命令行写 `TF_PYTEST_WORKERS=1`（写了就踩"环境渗进
#      子进程"那条雷）—— 默认自己按可用内存降档（见 `pytest_workers`），不会自己选满档。
#   若 flake 复发 → `TF_PYTEST_WORKERS=1` 串行（稳但慢 5 倍），别反复重跑到绿（第 9 条）。
DEFAULT_PYTEST_WORKERS = 4


def pytest_workers() -> int:
    """pytest 并行 worker 数：`TF_PYTEST_WORKERS` 优先；不设 → 按可用内存自适应。

    ★ 卡 A266：显式环境变量**仍然优先**（给了就照给，自适应不许覆盖人的显式选择）。
    不设时按可用内存（`available_memory_gb()`）选：
      - 可用 < 2.5 GB ⇒ 1（内存紧，串行最稳 —— 不再要人手工写那个变量）
      - 可用 < 4 GB   ⇒ 2
      - 否则 `min(4, cpu)`
    读不到内存（返回 None）⇒ 退回 `min(4, cpu)`（不静默当"内存够"，也不因读不到而过度保守）。
    """
    raw = os.environ.get("TF_PYTEST_WORKERS", "").strip()
    if raw:
        try:
            n = int(raw)
        except ValueError:
            n = 0
        if n >= 1:
            return n
        print(f"[WARN] TF_PYTEST_WORKERS={raw!r} 不合法 → 按可用内存自适应",
              file=sys.stderr, flush=True)
    cap = max(1, min(DEFAULT_PYTEST_WORKERS, os.cpu_count() or 1))
    try:
        avail = available_memory_gb()
    except Exception:
        avail = None
    if avail is None:          # 读不到内存 ⇒ 退回满档（不静默当"内存够"，也不过度保守）
        return cap
    if avail < 2.5:            # ★ 卡 A266：可用 < 2.5 GB ⇒ 串行
        return 1
    if avail < 4.0:            # ★ 卡 A266：可用 < 4 GB ⇒ 2 个 worker
        return 2
    return cap


# ---------------------------------------------------------------- 门 × 输入表（T-G239）
# 这张表回答**两件事**（共用同一份 glob，但用途不同，别混）：
#   ① `REUSE_INPUTS`（T-G47）：某道真机门的"输入一个字节都没变 → 可以复用上次判定"；
#   ② `--affected`（T-G239）：改了**这些**路径才需要重跑这道门。
# ★ 判据方向 = **宁多勿漏**（漏跑的代价比多跑高）：
#   - 一道门**在这张表里没有条目** ⇒ 视为"任何改动都可能影响它" ⇒ **永远跑**（见表后面的清单）；
#   - 表里每一条都要能在代码里找到出处 —— 下面逐条注明了出处的命令/常量。
# 刻意写宽一点（宁可多跑一次，也不要"以为无关"）：`src/**` 一律算输入。
DOOR_INPUTS: dict[str, tuple[str, ...]] = {
    # —— 真机层（起真服务 / 真浏览器）：输入 = 网页资源 + 服务端 + 门上自己的脚本（+ 黄金）——
    #    出处：命令见 `NODE_CMD`（render/ui_flow/ui_dom_probe）与 `REAL_PY`（两个 live 门）；
    #    输入与 T-G47 的 `REUSE_INPUTS` 同源（`REUSE_INPUTS` 就是从这里取的那 5 道）。
    "render": ("src/**", "tools/render_check.mjs", "tools/tf_browser.mjs", "tools/serve.py",
               "tools/render_signatures.json", "gates/render/*.txt"),
    "ui_flow": ("src/**", "tools/ui_flow_check.mjs", "tools/tf_browser.mjs", "tools/serve.py"),
    "lf1_live": ("src/**", "tools/lf1_live_check.py", "tools/serve.py"),
    "web_live": ("src/**", "tools/web_live_check.py", "tools/phone_check.mjs", "tools/serve.py"),
    "ui_dom_probe": ("src/web/**", "tools/ui_dom_probe.mjs"),
    # —— 静态审美/文案门（见 `COMMON`）：只读 `src/web` 的令牌与文案 ——
    #    出处：`tools/contrast_audit.py` 的 CSS/BASELINE 常量（CSS=src/web/app.css）、
    #    `tools/style_audit.py` 的 CSS/BASELINE、`tools/ui_text_audit.py` 的 BASELINE +
    #    它 import 的 `tools/ui_text_scan.py`（扫 src/web/index.html）。
    "contrast": ("src/web/**", "tools/contrast_audit.py", "tools/contrast_baseline.toml"),
    "style": ("src/web/**", "tools/style_audit.py", "tools/style_baseline.toml"),
    "ui_text": ("src/web/**", "tools/ui_text_audit.py", "tools/ui_text_scan.py",
                "tools/ui_text_baseline.toml"),
    # —— 命令表一致性（命令见 `COMMON` 的 commands）：读 src（app.py / index.html / registry / mcp）
    #    + 契约层 + `docs/commands.toml` ——
    #    出处：`scripts/check_commands.py` 的 COMMANDS/CONTRACTS/APP/INDEX 常量。
    "commands": ("src/**", "docs/contracts/**", "docs/commands.toml", "scripts/check_commands.py"),
    # —— 台账↔规格 标题对账（命令见 `COMMON` 的 audit_titles）：只读台账 + 两份规格 + 自己 ——
    #    出处：`scripts/audit_titles.py` 的 LEDGER/FUNCTIONAL/NONFUNCTIONAL 常量。
    "audit_titles": ("docs/traceability.toml", "docs/specification/**",
                     "scripts/audit_titles.py"),
}
# 表里**没有**条目的门 = 「任何改动都可能影响它」⇒ **永远跑**（逐门核过；出处写在各行）：
#   - pytest / acceptance：测试会读**整棵仓库**（docs/ · 复盘/ · traceability · harness …，
#     实测 tests/ 里到处在读）→ 任何改动都可能让它变红；与 T-G47「pytest 永不复用」同一精神。
#   - ruff：命令扫 `src/ tests/ scripts/ tools/ examples/ harness/`（见 `COMMON`），面宽。
#   - mypy：型检查整份 `src/`（见 `COMMON` 的 mypy），且对"别的模块改了"敏感（跨模块类型）。
#   - check_layers / check_layers_selftest：读 `docs/` 整棵文档体系并做跨层引用完整性
#     （出处：`scripts/check_layers.py` 的 docstring 与 `scripts/test_check_layers.py`）。
#   - audit：`audit_progress.py --all` 逐条求值台账 evidence，指针可指向仓库里**任何**地方。
#     （卡 140 §2 点名的例子之一。）
# ★ 读法等价的旧名字：`REUSE_INPUTS` = 从 `DOOR_INPUTS` 取那 5 道真机门（**避免两处漂**）。
REUSABLE: tuple[str, ...] = ("render", "ui_flow", "lf1_live", "web_live", "ui_dom_probe")
REUSE_INPUTS: dict[str, tuple[str, ...]] = {k: DOOR_INPUTS[k] for k in REUSABLE}

# ★ T-G181：glob 是按【工作区】匹配的 —— 上面 `src/**` 这类宽度会把**未跟踪的生成物**
# 也捞进输入哈希。它们是「这棵树有没有被 pip 装过 / 跑过测试」的函数，不是提交内容的一部分：
# 同一个提交在装过的树与干净的树里会算出不同哈希，还可能让"复用通过"基于提交里没有的文件。
# 下面这两个常量就是**要排掉的那几类**（按路径判；门清单与 `src/**` 宽度一个字不动）。
GENERATED_DIR_NAMES: frozenset[str] = frozenset({"__pycache__", ".pytest_cache"})
GENERATED_SUFFIXES: tuple[str, ...] = (".pyc", ".pyo")


def is_generated(path: Path) -> bool:
    """命中的文件是**生成物**吗（T-G181）：`__pycache__/` · `.pytest_cache/` ·
    `*.egg-info/` 目录下的任何文件，以及 `*.pyc` / `*.pyo`。只看路径，与内容无关。"""
    if path.suffix in GENERATED_SUFFIXES:
        return True
    return any(
        part in GENERATED_DIR_NAMES or part.endswith(".egg-info") for part in path.parts[:-1]
    )


def input_hash(patterns: tuple[str, ...]) -> str:
    """把一组 glob 命中的**文件内容**哈希起来（路径 + 内容，稳定排序）。

    ★ T-G181：命中结果里按**路径**排掉生成物（`__pycache__/` · `*.pyc`/`*.pyo` ·
    `*.egg-info/` · `.pytest_cache/`，见上面的 `GENERATED_DIR_NAMES`/`GENERATED_SUFFIXES`）。
    为什么排：glob 按工作区匹配，这些是**未跟踪的生成物**，随"这棵树装没装过 / 跑没跑过
    测试"变 —— 算进去会让**同一个提交**在两棵树里判出不同的复用结论（主控实测：同一提交
    render 主树 171 个输入 vs 工作树 164 个，差的就是 `src/timeflow.egg-info/*`），
    且一条"复用通过"可能是基于提交里根本不存在的文件下的。
    ★ 排掉之后哈希口径变了 → `gates/reuse.json` 里既有那几条记录会**失效一次**（下一轮这
    几道门真跑一遍），这是自愈，不是 bug。

    ★ 换行归一：哈希前把读到的字节里的 `\r\n`（两字节序列）替换成 `\n`，再喂给 sha256。
    为什么归一：本仓库 `core.autocrlf=true`，而 `.gitattributes` 只给 `gates/render/*.txt`
    钉了 `eol=lf`，其余已跟踪文件在工作区里 CRLF / LF / 混合都有（主控实测）。门禁的输入
    正是这种混合的（例如 `src/web/app.css`、`tools/ui_flow_check.mjs` 是 CRLF，
    `tools/serve.py` 是 LF）→ **同一份提交内容**在"CRLF 签出"和"LF 签出"的树里会算出不同
    哈希，复用结论随存放形式漂移。归一后哈希只看内容，不看换行存放形式。
    只动 `\r\n` 这一个两字节序列，**不**动孤立的 `\r`（那会改内容语义，超出本卡）。
    ★ 代价（接受的取舍，不是遗漏）：只改换行不改内容时，复用哈希**不会**失效 —— 但本仓库
    已给 `gates/render/*.txt` 钉了 `eol=lf`，"只改换行"本就是违规改动（动了逐字节比对的
    黄金文件），所以这条"失效不了"的路径在合规改动下根本走不到。哈希口径变了 → 既有
    `gates/reuse.json` 记录会**失效一次**（下一轮真跑），是自愈，不是 bug。
    """
    digest = hashlib.sha256()
    files: list[Path] = []
    for pattern in patterns:
        files.extend(p for p in ROOT.glob(pattern) if p.is_file() and not is_generated(p))
    for path in sorted(set(files), key=lambda p: p.as_posix()):
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).digest())
    return digest.hexdigest()[:16]


# ---- 门输入字面路径必须 git 跟踪（卡 161 §4 / INV-73）----
# gitignored / 没 pin 的输入（`.uiux-skill-probe/` 那类）换个机器就变成
# 「在别人机器上不存在」的检查 ⇒ 门禁结果依赖机器状态、不可复现。门表里出现的
# 字面路径（非 glob）一律要求 git 跟踪；glob 由 `--affected` 与复用哈希各自把关。

def _is_literal_path(pattern: str) -> bool:
    """这条门输入是字面路径（不是 glob）吗？出现 `*` `?` `[` 即视为 glob。"""
    return not any(c in pattern for c in "*?[")


def door_input_violations(
    door_inputs: Mapping[str, tuple[str, ...]] | None = None,
) -> list[str]:
    """门输入表里的**字面路径**必须是 git 跟踪的。

    返回违规字面路径（仓库相对、POSIX 斜杠）；空 = 全部合规。
    ★ 只读 `DOOR_INPUTS`（默认）或传入的表 —— 不写第二份门表（钉子⑤钉死这条）。
    """
    table = DOOR_INPUTS if door_inputs is None else door_inputs
    literals = sorted({p for pats in table.values() for p in pats if _is_literal_path(p)})
    if not literals:
        return []
    proc = subprocess.run(  # noqa: S603 —— 参数写死，无 shell
        ["git", "-c", "core.quotepath=false", "ls-files", "--", *literals],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        # ★ 防窗旗：Windows 上别让这条 git 弹控制台窗口（POSIX 上 `getattr` 落到 0 = 无操作）。
        #   ★ 为什么不登记进 `tests/test_no_window.py` 的 EXEMPT：那表是**白名单外改不了**的欠账，
        #   而本文件在卡 161 自己的域里 ⇒ 能加旗就加旗，别把债留给下一张卡。
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    tracked = {ln.strip() for ln in proc.stdout.splitlines() if ln.strip()}
    return [p for p in literals if p not in tracked]


def load_reuse() -> dict[str, dict[str, str]]:
    if not REUSE.exists():
        return {}
    try:
        data = json.loads(REUSE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_reuse(records: dict[str, dict[str, str]]) -> None:
    REUSE.parent.mkdir(parents=True, exist_ok=True)
    REUSE.write_text(
        json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )


def dom_probe_cmd() -> list[str] | None:
    """假 DOM 渲染探针：真跑 9 个视图。node 不在就跳过（不谎报通过）。"""
    node = shutil.which("node")
    return [node, str(ROOT / "tools" / "ui_dom_probe.mjs")] if node else None


def render_cmd() -> list[str] | None:
    """渲染验证层：真浏览器采几何清单与黄金比。node 不在就跳过（不谎报通过）。

    ★ T-G156：把本树端口段的 BASE 透传给 `render_check.mjs --port`（该工具已支持；
    不设 `TF_GATE_PORT_BASE` 时传的就是历史默认 8531，行为逐字不变）。"""
    node = shutil.which("node")
    if not node:
        return None
    return [node, str(ROOT / "tools" / "render_check.mjs"), "--port", str(port_base())]


def ui_flow_cmd() -> list[str] | None:
    """行为流层（T-G34）：真浏览器真点真按，验功能性的验收项。node 不在就跳过。

    ★ T-G156：透传 `--port BASE+10`（不设变量时 = 8541，历史默认，逐字不变）。"""
    node = shutil.which("node")
    if not node:
        return None
    return [node, str(ROOT / "tools" / "ui_flow_check.mjs"), "--port", str(port_base() + 10)]


# 这三门都是 **node 脚本**：环境里没有 node 就跑不了 —— 统一记 `not_run`（不许静默跳过当通过）。
NODE_CMD = {
    "ui_dom_probe": dom_probe_cmd,
    "render": render_cmd,
    "ui_flow": ui_flow_cmd,
}


def xdist_available() -> bool:
    """装了 `pytest-xdist` 吗？没装就串行跑 —— **不谎报**，也不因为缺插件把门禁弄红。"""
    probe = subprocess.run(
        [PY, "-c", "import xdist"], capture_output=True, text=True, check=False
    )
    return probe.returncode == 0


def pytest_cmd(serial: bool = False) -> list[str]:
    """pytest 那条命令：装了 xdist 就并行，否则串行。

    为什么可以并行（T-G7 实测的结论）：每个用例都起**真 app + 真库**（单次 `create_app()` ≈ 190ms、
    `connect + 迁移` ≈ 26ms），757 个用例串行要 3~4 分钟，而**用例之间没有共享状态** ——
    各自 `tmp_path` 一个库、各自进程内的 facts 总线，所以这是"安全的那一类提速"。
    覆盖率不受影响：pytest-cov 会把各 worker 的数据合并后，再判 `--cov-fail-under=70`。
    `--serial` 是给"并行下偶发失败"用的对照跑法（同一条命令、单进程）。

    ★ T-G156：worker 数**不再 `-n auto`**（32 核会拉 32 个 worker，而机器只有 15.2 GB 内存 →
    换页）。改成读 `TF_PYTEST_WORKERS`，不设时**按可用内存自适应**（★ 卡 A266，见
    `pytest_workers`）。
    `--serial` / 「没装 xdist 就串行」这两条既有口径一个字不动。
    """
    # ★ T-G190：**必须带 `-X utf8`**（本仓铁律：「python 一律 `python -X utf8 …`」）。
    #   不带它时子进程按**本机区域编码**解自己 subprocess 的输出（这台机器 GBK）→ 中文路径当场炸
    #   （`scripts/check_toml.py` 的 `toml_files()` 就是这么把 pytest 门弄红的）。
    #   本文件里其余十几条命令本来就带，漏的就是 acceptance / pytest 这两条。
    cmd = [PY, "-X", "utf8", "-m", "pytest"]
    if not serial and xdist_available():
        workers = pytest_workers()
        if workers > 1:
            cmd += ["-n", str(workers)]
    return cmd


def tree_pythonpath(e: dict[str, str]) -> dict[str, str]:
    """把**本树 `ROOT/src`** 放到子进程 `PYTHONPATH` 的**首位**（在原地改 `e` 并返回）。

    ★ 为什么（T-G157，真机门验错树的假绿）：本仓是**可编辑安装**（`pip install -e .`）指向
    **主树**的 `src` —— 在 worktree 里跑门禁时，node 门（`render` / `ui_flow` / `ui_dom_probe`）
    起的 `serve.py` 与两个 live 检查 `import timeflow` 会解析到**主树的 src**，于是这几道真机门
    验的是**主树的页面**；黄金又是在这同一个错页面上采的 → **两边一致 → 假绿**，你以为在验自己
    那棵树。把本树 `src` 塞进 `PYTHONPATH` 首位，子进程（含 node 再 spawn 的 `serve.py`，
    它继承 `process.env`）就解析到**本树**。

    顺序（**前者优先**）：`<ROOT>/src` → `tools/sandbox_shim` → 原有的 `PYTHONPATH`。
    `shim` 目录里只有 `sitecustomize.py`（无 `timeflow`），`<ROOT>/src` 里没有 `sitecustomize.py`
    → 两者互不遮蔽，`site` 仍能扫描到 `shim` 的 `sitecustomize`。
    ★ 主树里 `ROOT/src` 就是可编辑安装指向的那份 → **行为等价**（前后门数与结论不变）。
    """
    parts = [str(ROOT / "src"), str(ROOT / "tools" / "sandbox_shim")]
    if e.get("PYTHONPATH"):
        parts.append(e["PYTHONPATH"])
    e["PYTHONPATH"] = os.pathsep.join(parts)
    return e


def env() -> dict[str, str]:
    return tree_pythonpath(dict(os.environ))


def summarize(out: str) -> str:
    """抓一行结论（供 trailer 用）。

    注意：Windows 命令输出里常有中文警告，直接取"最后一行含关键词"会抓到 ResourceWarning
    （第一版就抓错了）。所以优先匹配测试框架的**汇总行**，并跳过各类 warning。
    """
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    summary_re = re.compile(r"\d+\s+(passed|failed|error|deselected)|no issues found|checks passed|"
                            r"LAYER CHECKS|SELF-TEST|PASS（|审计通过|OK \]")
    for line in reversed(lines):
        if "Warning" in line or line.startswith("ResourceWarning"):
            continue
        if summary_re.search(line):
            return line[:160]
    for line in reversed(lines):
        if "Warning" in line:
            continue
        if any(k in line for k in SUCCESS_HINTS):
            return line[:160]
    return lines[-1][:160] if lines else ""


# ---------------------------------------------------------------- 封存指纹（T-G179）
# 临时索引文件名（在 git-dir 里，不动用户真正的索引）。
INDEX_NAME = "dsh_gates_index"
# 封存指纹的口径自述（写进 last.json 的 tree_scope）：见 tree_without_gates。
TREE_SCOPE = "worktree-minus-gates"


def _git_index_path(repo: Path) -> Path | None:
    """临时索引文件路径 —— **由 git 自己给**，不再手拼 `ROOT / ".git"`。

    病灶（T-G179 实测钉死）：linked worktree 里 `ROOT/.git` 是**文件**（git-dir =
    `<主树>/.git/worktrees/<名>`），而旧代码把它当**目录**拼出 `ROOT/.git/dsh_gates_index`
    → `GIT_INDEX_FILE` 指向"一个文件底下"的路径 → `git read-tree HEAD` 失败 →
    回退成 `HEAD^{tree}`（= 底座那棵树，不是"即将提交的那棵树"）。
    改用 `git rev-parse --git-path`（拿到的可能是相对路径，按 repo 拼成绝对）。
    两个办法都拿不到 → None（调用方打印警告并回退，**不许静默**）。
    """
    probe = subprocess.run(
        ["git", "rev-parse", "--git-path", INDEX_NAME], cwd=repo,
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    out = (probe.stdout or "").strip()
    if probe.returncode == 0 and out:
        path = Path(out)
        return path if path.is_absolute() else (repo / path)
    probe2 = subprocess.run(
        ["git", "rev-parse", "--absolute-git-dir"], cwd=repo,
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    out2 = (probe2.stdout or "").strip()
    if probe2.returncode == 0 and out2:
        return Path(out2) / INDEX_NAME
    return None


def tree_without_gates(
    repo: Path, rev: str = "HEAD", *, include_worktree: bool = False, exclude_gates: bool = True
) -> str | None:
    """「封存指纹」的**唯一实现**：把 `<rev>`（可叠加工作区改动）写成临时 tree，返回它的哈希。

    ── 这个字段**是什么** ──
    除 `gates/**` 之外、即将提交的那份内容的 tree 哈希
    （`exclude_gates=False` 时就是完整 tree）。
    它是**可复现的固定点**：只要"除 gates 外的内容"不动，重算多少次都一样。
    ── 它**不是什么** ──
    ① **不是**完整提交的 tree（完整 tree 含 `gates/`）；② **不含门禁产物**。
    为什么必须不含门禁产物：`gates/last.json` **自己就在那棵树里** —— 把"含它自己的树"的哈希
    写进它自己，写完哈希又变 → **永远追不上**（自指悖论）。本卡 §0 实测：5 棵树的
    `last.json.tree` 全等于底座那棵树（worktree 回退 + 自指，两个洞叠加），是一整列
    "没人查、且每笔都错"的凭证；RI10「无法脱离凭证独立证明门禁跑在脏树上」正是这个洞的后遗症。
    ⇒ 定义成"摘掉 `gates/**` 的固定点"后，`run_gates` 写它、`wb_verify` 能**独立复算**它
    （见 §1.3；两处共用**本函数**这一份实现，不各写一套）。
    ── 为什么之前会骗人 ──
    见 `_git_index_path` 的病灶说明：回退路径把"即将提交的树"错记成"底座提交的树"。

    做法：临时索引（路径由 git 给）→ `read-tree <rev>`（`include_worktree=True` 时再
    `git add -A` 叠上工作区）→ `git rm -r --cached --ignore-unmatch gates`（`exclude_gates`）
    → `git write-tree`。任何一步拿不到结果 → None（调用方决定回退 + 打警告，**不许静默**）。
    """
    index_path = _git_index_path(repo)
    if index_path is None:
        print("[警告] 取不到临时索引路径（git rev-parse --git-path 失败）→ 封存指纹回退",
              file=sys.stderr, flush=True)
        return None
    with contextlib.suppress(OSError):
        if index_path.exists():
            index_path.unlink()
    env_index = dict(os.environ)
    env_index["GIT_INDEX_FILE"] = str(index_path)

    def _git_i(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=repo, env=env_index,
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        )

    read = _git_i("read-tree", rev)
    if read.returncode != 0:
        print(f"[警告] read-tree {rev} 失败（{(read.stderr or '').strip()[:120]}）→ 封存指纹回退",
              file=sys.stderr, flush=True)
        with contextlib.suppress(OSError):
            if index_path.exists():
                index_path.unlink()
        return None
    if include_worktree:
        _git_i("add", "-A")
    if exclude_gates:
        _git_i("rm", "-r", "--cached", "--ignore-unmatch", "--quiet", "gates")
    written = _git_i("write-tree")
    with contextlib.suppress(OSError):
        if index_path.exists():
            index_path.unlink()
    tree = (written.stdout or "").strip()
    if written.returncode != 0 or not tree:
        print(f"[警告] write-tree 失败（{(written.stderr or '').strip()[:120]}）→ 封存指纹回退",
              file=sys.stderr, flush=True)
        return None
    return tree


def staged_tree() -> str:
    """把"即将提交的内容"（索引 + 工作区）写成一个**封存指纹** tree，返回它的哈希。

    为什么不能用 HEAD 的 tree：门禁在**提交前**跑，那时 HEAD 还是上一次提交。
    工作树在提交前后一致，但工作区可能还有未 add 的改动，所以用 `git add -A` 到临时索引后
    `git write-tree` 得到"这次要提交的那棵树"。
    ★ T-G179：这个值**摘掉 `gates/**`**（`tree_without_gates` 的固定点口径）——
    否则 `gates/last.json` 写进它自己的哈希会自指、永远对不上（见 `tree_without_gates`）。
    任何一步失败 → 打一行警告并回退到 `HEAD^{tree}`（回退值**不是**固定点，可能骗人）。
    """
    tree = tree_without_gates(ROOT, "HEAD", include_worktree=True)
    if tree:
        return tree
    print("[警告] 封存指纹临时索引法失败 → 回退 HEAD^{tree}（这个值不是固定点，可能骗人）",
          file=sys.stderr, flush=True)
    return git("rev-parse", "HEAD^{tree}")


def git(*args: str) -> str:
    # core.quotepath=false：否则 git 把中文路径输出成八进制转义（\345\244\215 这种），
    # 于是"复盘/xxx.md 有没有一起改"这类判断会永远为假（实测踩到，等于中文文档的同步检查失效）。
    r = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    return r.stdout.strip()


def untracked_files() -> list[str]:
    """此刻**未跟踪**的文件清单（= 会进 `git add -A`、但还没进索引的），不含 `gates/**`。

    ★ T-G212 / 卡 115：门禁算的"封存树"是**工作树减 `gates/**`**（临时索引 `git add -A`），
    **包含**未跟踪的生成物（例如 `_stage_card.py` 落的 `docs/changelog.d/<台账号>.md` 片段）——
    可是**没人**拿它跟"提交树"比：2026-10-02 三笔提交（`T-G205`/`T-G206`/`T-G208`）的片段文件
    **根本没进提交**（集成时 `--allow` 只给了代码文件），而 `sync_docs.py --check` 只查
    "现有片段在不在汇总里"、**少文件照样 PASS** ⇒ 这个缺口零判据。

    本函数把"封存那一刻未跟踪的文件"记进 `gates/last.json.untracked`，好让
    `scripts/audit_progress.py` 事后逐条 `git ls-files --error-unmatch` —— 谁"生成了却没进提交"
    当场点名。口径：

    - 用 `--others --exclude-standard`：只列**未跟踪且未被 `.gitignore` 忽略**的（= `git add -A`
      会带上的那批，与"封存树"口径一致）；
    - **已跟踪的不列**：它们本来就在提交里，列出来只会是噪音；
    - **`gates/**` 照旧不列**：与封存指纹（`tree_without_gates`）同一口径 —— 门禁产物不进清单，
      否则 `gates/logs/**` 这类未跟踪产物会天天误报。
    """
    out = git("ls-files", "--others", "--exclude-standard")
    return [
        p for p in out.splitlines()
        if p.strip() and p != "gates" and not p.startswith("gates/")
    ]


def docs_fragments_problems() -> list[str]:
    """片段 ↔ 汇总一致性（卡 107 / T-G203）：跑 `tools/sync_docs.py --check`。

    非零退出 = 三个共享文档与它们各自的片段目录**对不上**。说人话：
    「**有人手改了汇总文件却没改片段，或反之**」—— 并发要零冲突，靠的就是两边一致。
    工具不在（旧树）→ 不误报（返回空）。
    """
    tool = ROOT / "tools" / "sync_docs.py"
    if not tool.exists():
        return []
    proc = subprocess.run(
        [PY, "-X", "utf8", str(tool), "--check"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if proc.returncode == 0:
        return []
    out = (proc.stdout or "") + (proc.stderr or "")
    dash = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("-")]
    if dash:
        return [f"片段与汇总不一致：{ln.lstrip('- ').strip()}" for ln in dash]
    return ["片段与汇总不一致：有人手改了汇总却没改片段，或反之（跑 `tools/sync_docs.py` 汇总）"]


def _changed_or_frag(changed: set[str], whole: str, frag_dir: str, suffix: str) -> bool:
    """整份共享文档改了，**或**它对应的片段目录下落了片段 —— 都算"已同步"。"""
    if whole in changed:
        return True
    return any(p.startswith(frag_dir) and p.endswith(suffix) for p in changed)


def docs_sync_precheck() -> tuple[bool, list[str]]:
    """④ 的前置检查：改了源码就必须同时改台账/changelog/CHECKPOINT（**提交前**就发现）。

    ★ 卡 107（T-G203）：认**片段文件** —— 作者不再直接改三个共享文档，而是落
    `docs/traceability.d/<台账号>.toml` / `docs/changelog.d/<台账号>.md` /
    `复盘/交接.d/<台账号>.md`，由集成者用 `tools/sync_docs.py` **串行汇总**。
    所以"改了源码却只落了片段"**也算已同步**。
    另加一条新判据：**片段 ↔ 汇总必须一致**（`sync_docs.py --check`），不一致判红。
    """
    problems = list(docs_fragments_problems())
    changed = set(git("status", "--porcelain").split())
    changed |= set(git("diff", "--cached", "--name-only").split())
    if not any(p.startswith(("src/timeflow/", "src/web/")) for p in changed):
        return (not problems), problems
    missing: list[str] = []
    if not _changed_or_frag(changed, "docs/traceability.toml", "docs/traceability.d/", ".toml"):
        missing.append("docs/traceability.toml（或 docs/traceability.d/<台账号>.toml）")
    if not _changed_or_frag(changed, "docs/changelog.md", "docs/changelog.d/", ".md"):
        missing.append("docs/changelog.md（或 docs/changelog.d/<台账号>.md）")
    if not (any(p in changed for p in ("复盘/长任务执行协议.md", "复盘/交接-重构进度.md"))
            or any(p.startswith("复盘/交接.d/") for p in changed)):
        missing.append("复盘/长任务执行协议.md（或 交接-重构进度.md，或 复盘/交接.d/<台账号>.md）")
    return (not missing and not problems), problems + missing


def seal() -> int:
    """封存：只把 `gates/last.json` 里的**封存指纹**（`tree`）重算一次，并写上口径自述。

    ★ T-G179 改口径：`tree` 现在是"**除 `gates/**` 外**、即将提交的那份内容"的 tree 哈希
    （见 `tree_without_gates`）—— **不含**门禁产物，所以是个**固定点**：写完它自己也不变。
    旧口径把"含 `gates/last.json` 自己"的树哈希写进去 → 写完哈希又变 → 永远追不上（自指）。
    本步骤在正式提交前重算一次，让 `last.json.tree` 与最终提交【去掉 `gates/**`】的 tree 一致。
    """
    if not GATES.exists():
        print("[FAIL] 还没有 gates/last.json，先跑一次门禁")
        return 1
    payload = json.loads(GATES.read_text(encoding="utf-8"))
    if not payload.get("ok"):
        print("[FAIL] gates/last.json 里 ok=false，封存没有意义（先让门禁通过）")
        return 1
    old = payload.get("tree", "")
    payload["tree"] = staged_tree()
    payload["tree_scope"] = TREE_SCOPE   # 口径自述：旧笔没这个字段 → wb_verify 据它判"不核"
    # ★ T-G212 / 卡 115：封存**这一刻**的未跟踪清单 —— 提交前最后一眼，比门禁跑时那份更贴近提交。
    #   提交之后 `scripts/audit_progress.py` 逐条查它们有没有被跟踪：漏了 = 生成了却没进提交。
    payload["untracked"] = untracked_files()
    payload["sealed_at"] = datetime.now().isoformat(timespec="seconds")
    GATES.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"[封存] gates/last.json tree: {old[:12]} → {payload['tree'][:12]}（{TREE_SCOPE}）")
    print("[提示] `git add gates/last.json && git commit` 后，"
          "产物与提交【去掉 gates/**】的树会一致")
    return 0


# ---------------------------------------------------------------- 开场清遗留（T-G156 §2.2）
# 病灶③：全量门禁常超工人 CLI 的 10 分钟单次调用上限 → 调用被掐 → 测试服务/无头 Edge 变孤儿
# → 下一轮撞端口 → 又清又撞。旧清法是**按进程名/特征乱杀**（`serve.py --fresh` 等，不认哪棵树）
# —— 058 清端口时把 059 正在跑的 render_check 一起杀了（铁律 27）。
# 现在改成**按端口认领**：只看「本树这一段端口」上的 LISTENING 进程，只掐它们的 PID。
def _is_listening(port: int) -> bool:
    """127.0.0.1:<port> 有人在听吗（与 `gate_lock.py` 同一套探法）。"""
    try:
        s = socket.socket()
        s.settimeout(0.2)
        busy = s.connect_ex(("127.0.0.1", port)) == 0
        s.close()
        return busy
    except OSError:
        return False


def _psutil():
    """psutil 在就用它（跨平台、能拿命令行）；不在就回退。"""
    try:
        import psutil  # type: ignore[import-untyped]
        return psutil
    except Exception:
        return None


def _listening_pids(port: int) -> list[int] | None:
    """监听 <port> 的进程 PID 列表；**查不到 → None**（调用方据此"不动并报原因"，不许瞎杀）。"""
    ps = _psutil()
    if ps is not None:
        pids: set[int] = set()
        try:
            for conn in ps.net_connections(kind="tcp"):
                if (conn.status == ps.CONN_LISTEN and conn.laddr
                        and int(conn.laddr.port) == port and conn.pid):
                    pids.add(int(conn.pid))
            if pids:
                return sorted(pids)
        except Exception:
            pass
    # 兜底：netstat -ano（Windows 自带）
    try:
        proc = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", check=False)
    except OSError:
        return None
    pids = set()
    for line in (proc.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING":
            tail = parts[1].rsplit(":", 1)[-1]
            if tail.isdigit() and int(tail) == port:
                with contextlib.suppress(ValueError):
                    pids.add(int(parts[4]))
    return sorted(pids) if pids else None


def _pid_cwd(pid: int) -> str | None:
    """进程工作目录（规范化）；拿不到 → None。**这是"是不是本树"的硬判据**：
    本树起的 `serve.py` / node / 无头浏览器，cwd 都是本仓库根（`start_gate` 用 `cwd=ROOT`
    起 node，node 再 `spawn` 子进程时继承）。★ 拿不到就**不杀**（拒绝优于跨树误杀）。"""
    ps = _psutil()
    if ps is None:
        return None
    try:
        cwd = ps.Process(pid).cwd()
    except Exception:
        return None
    if not cwd:
        return None
    try:
        return os.path.normcase(str(Path(cwd).resolve()))
    except OSError:
        return None


def _is_our_tree(pid: int, depth: int = 4) -> bool:
    """本进程（或其至多 `depth` 代祖先）的 cwd 是不是**本仓库根**。

    ★ 这一条是本卡的关键加固，来由是一次**真事故**（2026-09-27，见复盘）：默认端口段是
    **多棵树共用**的，只按端口认领会在默认模式下**跨树误杀**（把另一棵树正在跑的
    render/ui_flow 一起掐了，日志是 node 的「unsettled top-level await」+ 退 13）。
    加上"cwd = 本树根"这条树判据后：别人的树 cwd 不同 → **天然不碰**。"""
    ps = _psutil()
    if ps is None:
        return False
    target = os.path.normcase(str(ROOT.resolve()))
    cur = pid
    seen: set[int] = set()
    for _ in range(depth + 1):
        if cur in seen or cur <= 0:
            break
        seen.add(cur)
        if _pid_cwd(cur) == target:
            return True
        try:
            cur = ps.Process(cur).ppid()
        except Exception:
            break
    return False


def _cmdline_of(pid: int) -> str:
    """进程命令行（拿不到 → 空串）。只用于**打印留痕**，不做杀/不杀判据。"""
    ps = _psutil()
    if ps is not None:
        try:
            return " ".join(ps.Process(pid).cmdline())
        except Exception:
            return ""
    return ""


def _kill_pid(pid: int) -> tuple[bool, str]:
    """**按 PID 单掐**（绝不用 `/T` 整树、绝不按进程名）。返回 (成功?, 说明)。"""
    ps = _psutil()
    if ps is not None:
        try:
            ps.Process(pid).kill()
            return True, "psutil.kill"
        except Exception as exc:
            return False, f"psutil:{type(exc).__name__}"
    try:
        r = subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, text=True, check=False)
        return r.returncode == 0, f"taskkill rc={r.returncode}"
    except OSError as exc:
        return False, f"{type(exc).__name__}"


# 浏览器可执行名（只作**正向身份过滤**，好把"命令行里恰好含端口字样的外壳进程"排掉；
# 杀/不杀的判据仍是端口认领，**不是**按名字乱杀 —— 见卡 §2.2 与铁律 27）。
_BROWSER_IMAGE_HINTS = (
    "msedge", "microsoft-edge", "chrome", "chromium", "headless_shell", "headless-shell",
)


def _is_orphan_browser(image_name: str, cmdline: str, ports: list[int]) -> str | None:
    """纯判据（便于单测）：是"绑在本段端口上的无头浏览器"就返回原因，否则 None。

    条件 = ①镜像名像浏览器（正向身份过滤）**且** ②命令行里带本段端口的两种令牌之一：
    `--remote-debugging-port=<本段端口>` 或 profile 目录名 `tf-flow-profile-<端口>` /
    `tf-render-profile-<端口>`。★ 两条都必须挂在**本段端口**上 —— 别的 BASE 段天然不匹配。"""
    name = (image_name or "").lower()
    if not any(hint in name for hint in _BROWSER_IMAGE_HINTS):
        return None
    if not cmdline:
        return None
    for p in ports:
        if f"--remote-debugging-port={p}" in cmdline:
            return f"命令行含 --remote-debugging-port={p}"
    for p in ports:
        for pat in (f"tf-flow-profile-{p}", f"tf-render-profile-{p}"):
            if pat in cmdline:
                return f"命令行含 {pat}"
    return None


def _orphan_browser_pids(ports: list[int], exclude: set[int]) -> dict[int, str]:
    """**按端口/profile 目录认领**的无头浏览器（那正是"属于这段端口"的判据）。
    ★ 绝不用"名字带 tf-flow-profile 就杀"（会跨树误杀）。判据见 `_is_orphan_browser`。"""
    ps = _psutil()
    if ps is None:
        return {}
    hits: dict[int, str] = {}
    for proc in ps.process_iter(["pid", "name", "cmdline"]):
        try:
            pid = int(proc.info["pid"])
            if pid in exclude:
                continue
            why = _is_orphan_browser(
                str(proc.info.get("name") or ""),
                " ".join(proc.info.get("cmdline") or []),
                ports,
            )
            if why:
                hits[pid] = why
        except Exception:
            continue
    return hits


def cleanup_leftovers() -> None:
    """开场清**本树端口段**上的遗留（幂等 + 有读数，清不掉打印原因，不许静默）。

    ★ 两条判据**同时**成立才掐：① 端口落在本树段 `gate_port_set()`（默认 = 8531..8549）；
    ② 该进程（或近祖先）的 cwd = **本仓库根**（`_is_our_tree`）。别的 BASE 段在别的端口、
    别的树的 cwd 也不同 → 两条都天然不碰（这才是"非本树的服务不许动"的真判据）。
    ★ 本卡实现里**没有**任何"按 `serve.py --fresh` 匹配就杀"的写法（铁律 27）。"""
    base = port_base()
    ports = gate_port_set(base)
    print(f"=== ⑨ 开场清遗留（端口段 + 本树 cwd 双判据；BASE={base}：{ports[0]}..{ports[-1]}）===",
          flush=True)
    busy = {p: _listening_pids(p) for p in ports if _is_listening(p)}
    if not busy:
        print(f"  [清遗留] 本树端口段本来就空着（{len(ports)} 个端口都没人听）", flush=True)
    killed: list[str] = []
    untouched: list[str] = []
    for port in sorted(busy):
        pids = busy[port]
        if not pids:
            untouched.append(f"{port} 在听但查不到持有进程（psutil/netstat 都没给出 PID）")
            continue
        for pid in pids:
            cmd = _cmdline_of(pid)
            note = f"pid={pid}@{port} cmd={cmd[:100]!r}"
            if not _is_our_tree(pid):
                untouched.append(note + " [不是本树（cwd 不符/查不到）→ 不动]")
                continue
            ok, why = _kill_pid(pid)
            if ok:
                killed.append(note + " [已掐]")
            else:
                untouched.append(note + f" [掐不掉:{why}]")
    # 无头 Edge：按端口/profile 认领（排除刚掐掉的 serve PID）+ 本树 cwd 双判据
    exclude = {pid for pids in busy.values() if pids for pid in pids}
    edge_hits = _orphan_browser_pids(ports, exclude)
    edge_killed: list[str] = []
    for pid, why in edge_hits.items():
        if not _is_our_tree(pid):
            untouched.append(f"pid={pid}（{why}）[不是本树 → 不动]")
            continue
        ok, kwhy = _kill_pid(pid)
        if ok:
            edge_killed.append(f"pid={pid}（{why}）")
        else:
            untouched.append(f"pid={pid}（{why}）掐不掉:{kwhy}")
    print(f"  [清遗留] 本树 serve/进程：掐了 {len(killed)} 个"
          + ("：" + "；".join(killed) if killed else ""), flush=True)
    print(f"  [清遗留] 本树无头浏览器：掐了 {len(edge_killed)} 个"
          + ("：" + "；".join(edge_killed) if edge_killed else ""), flush=True)
    if untouched:
        print("  [清遗留] ★ 没动的（不静默）：" + "；".join(untouched), flush=True)
    print("  [清遗留] 判据：端口段 ∩ cwd=本树根 —— 别的树/别的 BASE 段两条都不同，天然不碰。",
          flush=True)


# ---------------------------------------------------------------- 跑一道门
PRINT_LOCK = threading.Lock()


def door_timeout() -> float | None:
    """每道门的硬超时（秒）；`None` = **不设超时**（一直等）。

    - 不设 `TF_GATE_DOOR_TIMEOUT` → 默认 `DEFAULT_DOOR_TIMEOUT`（1800 秒）；
    - 设了且 > 0 → 用该值；`0`（或任何 ≤ 0 的值）→ `None` = 关掉这条路；
    - 设了但不是数字 → 打警告并退回默认（**不许静默**：静默退回和"没设"分不出来，
      而"没设"与"设错了"对一道卡死的门后果完全不同）。

    ★ 这一层不碰任何门的判据 —— 它只决定"等多久后掐"，掐完仍由 `finish_gate` 判红。
    """
    raw = os.environ.get("TF_GATE_DOOR_TIMEOUT", "").strip()
    if not raw:
        return DEFAULT_DOOR_TIMEOUT
    try:
        val = float(raw)
    except ValueError:
        print(f"[WARN] TF_GATE_DOOR_TIMEOUT={raw!r} 不是数字 → 退回默认 "
              f"{DEFAULT_DOOR_TIMEOUT:g} 秒", file=sys.stderr, flush=True)
        return DEFAULT_DOOR_TIMEOUT
    if val <= 0:
        return None
    return val


# 卡 161 §2：慢门软预算（**告警**，不阻断——硬超时仍由 `door_timeout()` 掐）。
# 默认 600 秒：一道门跑过 10 分钟就该被点名（pytest 1 worker 实测 612s 会踩这条），
# 让"我手打 1 个 worker"从静默变成会被发现的事。`=0` 关掉告警。
DEFAULT_DOOR_BUDGET = 600.0


def door_budget() -> float | None:
    """单门慢告警阈值（秒）；`None` = 不告警。

    - 不设 `TF_GATE_DOOR_BUDGET` → 默认 `DEFAULT_DOOR_BUDGET`（600 秒）；
    - 设了且 > 0 → 用该值；`0` → `None` = 关掉告警；
    - 设了但不是数字 → 打警告并退回默认（**不许静默**）。
    ★ 与 `door_timeout()` 是两件事：硬超时掐门、软预算只点名。
    """
    raw = os.environ.get("TF_GATE_DOOR_BUDGET", "").strip()
    if not raw:
        return DEFAULT_DOOR_BUDGET
    try:
        val = float(raw)
    except ValueError:
        print(f"[WARN] TF_GATE_DOOR_BUDGET={raw!r} 不是数字 → 退回默认 "
              f"{DEFAULT_DOOR_BUDGET:g} 秒", file=sys.stderr, flush=True)
        return DEFAULT_DOOR_BUDGET
    if val <= 0:
        return None
    return val


def _fmt_secs(value: float) -> str:
    """秒数的**人话**写法：整数就不带小数点（3 而不是 3.0）；否则留有效位。"""
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _descendant_pids(pid: int) -> list[int]:
    """`pid` 的所有后代 PID（psutil 在才给得出；拿不到 → 空表 = "只掐得掉它自己"）。

    ★ 只用来**数**要掐几个子进程并留痕，不参与"掐/不掐"的判据（那个判据是"超时了"）。
    """
    ps = _psutil()
    if ps is None:
        return []
    try:
        return [int(c.pid) for c in ps.Process(pid).children(recursive=True)]
    except Exception:
        return []


def kill_gate_tree(pid: int) -> tuple[bool, int, str]:
    """**掐掉整棵进程树**（不是只杀父进程）。返回 `(掐成功?, 子进程数, 说明)`。

    ★ 为什么必须整树（本卡的病根）：2026-10-01 卡死的那串是
      `node ui_flow_check.mjs` → `serve.py` + 无头 `msedge` —— 只 `kill` 父的会留下一堆
      孤儿继续占端口，下一轮又撞端口。Windows 上用 `taskkill /PID <pid> /T /F`（`/T` = 连
      子孙一起），先数一下后代个数（`_descendant_pids`）好在 report 里说清"掐了几个"。
    ★ 与开场清遗留（`cleanup_leftovers`，按端口 + 本树 cwd 双判据、`/T` 绝不用的**单掐**）
      刻意分开：那一条怕跨树误杀，这一条掐的是**本进程刚起的门**，杀整树才对。
    """
    children = _descendant_pids(pid)
    n_children = len(children)
    if os.name == "nt":
        try:
            r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],  # noqa: S603
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace", check=False)
        except OSError as exc:
            return False, n_children, f"{type(exc).__name__}: {exc}"
        ok = r.returncode == 0
        return ok, n_children, f"taskkill /PID {pid} /T /F rc={r.returncode}"
    # POSIX（本仓主力在 Windows，这条是防"换台机器跑不了"）：
    ps = _psutil()
    if ps is not None:
        try:
            victims = ps.Process(pid).children(recursive=True) + [ps.Process(pid)]
            for victim in victims:
                with contextlib.suppress(Exception):
                    victim.kill()
            gone, _ = ps.wait_procs(victims, timeout=5)
            return len(gone) > 0, n_children, f"psutil 递归掐（{len(gone)} 个）"
        except Exception as exc:
            return False, n_children, f"{type(exc).__name__}: {exc}"
    try:
        os.kill(pid, 9)
        return True, n_children, f"os.kill({pid}, 9)"
    except OSError as exc:
        return False, n_children, f"{type(exc).__name__}: {exc}"


def resolve_cmd(name: str, cmds: dict[str, list[str]], serial: bool) -> list[str] | None:
    """把占位命令填实（node 不在 → None = 这一门没跑，记 `not_run`，不算通过）。

    ★ 顺序有讲究（T-G47 实测踩到）：**先**看"是不是占位门"，**再**从 `cmds` 取字面命令。
    反过来写的话（第一版就是），`jobs` 里 `("pytest", [])` / `("render", [])` 这些**空占位**
    会先被 `name in cmds` 命中 → 返回 `[]` → `Popen([])` 在 Windows 上抛
    `OSError: [WinError 87]`（"参数错误"，看不出跟命令有关）→ 那 4 道门全记成"起不来"。
    """
    if name in NODE_CMD:
        return NODE_CMD[name]()
    if name == "pytest":
        return pytest_cmd(serial=serial)
    loaded = cmds.get(name)
    return loaded if loaded else None


def start_gate(name: str, cmd: list[str]) -> tuple[subprocess.Popen[str] | None, float, str]:
    """**在主线程里**把门起起来（返回进程 + 起始时刻 + 错误文本）。

    ★ 为什么"起进程"必须串行、不能放在线程池里（T-G47 实测踩到）：
    多个线程**同时** `subprocess.Popen` 在 Windows 上会随机抛
    `OSError: [WinError 87] 参数错误`（CPython 在 Windows 上创建子进程不是线程安全的：
    句柄继承与 startupinfo 会互相踩）。而"并行"真正需要的是**等输出**那一段 ——
    进程起完就各自在跑了，等待完全可以在线程里做。于是拆成 start / finish 两步。

    一道门**起不来**（解释器不在、命令写错）也如实记成一条 FAIL，而不是让整个门禁脚本崩掉
    —— 崩掉会丢掉其余门的结论，"失败要留下证据"这条先于"这次跑得顺"。
    """
    t0 = time.time()
    try:
        proc = subprocess.Popen(  # noqa: S603
            cmd, cwd=ROOT, env=env(),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
    except OSError as exc:  # 起不来：记 FAIL，别把整轮门禁带走
        return None, t0, f"{type(exc).__name__}: {exc}"
    return proc, t0, ""


def finish_gate(
    name: str, proc: subprocess.Popen[str], t0: float, timeout: float | None = None
) -> dict[str, object]:
    """等一道门跑完，汇成它的结果条目（这一半可以放心并行）。

    ★ 本卡 T-G196：`timeout` 是这道门的**硬超时**（秒；`None` = 一直等）。到点 → **掐整棵树**
    （`kill_gate_tree`）→ 记 **`exit_code = 124`**（`timeout(1)` 的约定俗成）并在 summary 里
    写清「**超时 N 秒被掐**」+ 门名 + pid + 掐了几个子进程；`timeout=True` 这个字段让它
    **机器可读**。★ 判红：124 ≠ 0 → 整趟非 0，**绝不当"跳过/没跑"糊过去**（那是最坏的一种假绿）。
    """
    timed_out = False
    killed_children = 0
    kill_note = ""
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        # kill_gate_tree 自己在掐之前数后代（杀完就查不到了）——这个数进 summary 与 last.json。
        ok_kill, killed_children, kill_note = kill_gate_tree(proc.pid)
        # 树掐完后把 shell 与管道收干净（拿回剩余输出；万一父进程没死透，兜底硬 kill）。
        try:
            out, _ = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(OSError):
                proc.kill()
            out, _ = proc.communicate()
        if not ok_kill:
            kill_note = f"★ 整树没掐干净（{kill_note}）"

    exit_code = 124 if timed_out else int(proc.returncode)
    item: dict[str, object] = {
        "name": name,
        "exit_code": exit_code,
        "seconds": round(time.time() - t0, 2),
        "summary": summarize(out or ""),
    }
    if timed_out:
        item["summary"] = (
            f"超时 {_fmt_secs(timeout)} 秒被掐：{name} pid={proc.pid}，"
            f"掐了 {killed_children} 个子进程（{kill_note}）"
        )
        # 机器可读：哪道门被超时掐的、限时多少、掐了几个子进程。
        item["timeout"] = True
        item["timeout_seconds"] = timeout
        item["killed_pid"] = proc.pid
        item["killed_children"] = killed_children
    if name in NODE_CMD and exit_code == 3:
        item["blocking"] = False
        item["status"] = "NOT RUN"
        item["note"] = "起不了真浏览器：这一层**没有验证**，不算通过"
    # ★ T-G58：**失败时把这道门的输出留下**。原来只印一行摘要、输出直接丢掉 —— 于是
    # 「全量跑红了」之后唯一的办法是**把这道门单独再跑一遍**（render 110 秒、ui_flow 176 秒），
    # 而它往往是随机的，重跑还未必复现（T-G51 就在这上面白花了两轮）。现在：全量输出落
    # `gates/logs/<门名>.log`（不进仓库），**并且**当场印尾部若干行 —— 红的时候立刻能看到原因。
    failed = exit_code not in (0, 3)
    if out:
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            (LOG_DIR / f"{name}.log").write_text(out, encoding="utf-8")
        except OSError:  # 写不了日志不该把门禁也带走
            pass
    with PRINT_LOCK:
        tag = f"{name:<22} exit={exit_code}  {item['seconds']}s"
        if item.get("status") == "NOT RUN":
            print(f"[SKIP] {tag}  （起不了真浏览器）")
        elif timed_out:
            print(f"[FAIL] {tag}  ★ {item['summary']}")
        else:
            mark = "[OK ]" if exit_code == 0 else "[FAIL]"
            print(f"{mark} {tag}  {item['summary']}")
        if failed and out:
            tail = [ln.rstrip() for ln in out.splitlines() if ln.strip()][-12:]
            print(f"       ↳ 这道门的输出尾部（全量在 gates/logs/{name}.log）：")
            for ln in tail:
                print(f"         {ln[:160]}")
    return item


def dead_gate(name: str, t0: float, why: str) -> dict[str, object]:
    """起不来的门：记一条 FAIL（宁可红，也不要"看起来没这回事"）。"""
    with PRINT_LOCK:
        print(f"[FAIL] {name:<22} 起不来：{why}")
    return {
        "name": name,
        "exit_code": -1,
        "seconds": round(time.time() - t0, 2),
        "summary": f"起不来：{why}",
    }


def skip_reused(name: str, records: dict[str, dict[str, str]], no_reuse: bool) -> str | None:
    """输入没变且上次是通过 → 返回那条记录里的哈希（调用方据此记 `reused`）；否则 None。

    ★ 这个判据**本身会不会咬**由 `tests/test_gates_reuse_line.py` 钉住（T-G106）：输入改一个
      字节 / 新增文件 → 不复用；`--no-reuse` / `pytest`（不在 `REUSE_INPUTS`）/ 上次没过 /
      没有记录 → 一律不复用。一条永远回「复用」的判据等于注释。
    """
    if no_reuse or name not in REUSE_INPUTS:
        return None
    record = records.get(name)
    if not record or record.get("verdict") != "pass":
        return None
    current = input_hash(REUSE_INPUTS[name])
    return current if record.get("hash") == current else None


def gates_ok(results: list[dict[str, object]]) -> bool:
    """整趟是否通过：**所有阻断门**都 `exit_code == 0`。

    单独抽出来（T-G196）是为了让"一道门被超时掐 → 整趟退非 0"这条**有机器钉子**：
    `exit_code = 124` 一样落进 `!= 0` → 整趟非 0，超时**不会被别的门的通过吞掉**。
    `blocking=False` 的（NOT RUN 渲染层、信息性门）照旧不计。
    """
    blocking = [r for r in results if r.get("blocking", True)]
    return all(int(str(r["exit_code"])) == 0 for r in blocking)


# ---------------------------------------------------------------- --affected（T-G239 / 卡 140）
# 只裁"该跑哪几道门"，**不碰任何门的判据**。判据方向 = 宁多勿漏（见模块头与 `--help`）。
_GLOB_RE_CACHE: dict[str, re.Pattern[str]] = {}


def _glob_re(pattern: str) -> re.Pattern[str]:
    """把 glob 翻成正则（与 `ROOT.glob` 同语义：`**` 跨目录、`*`/`?` 不跨；结果缓存）。"""
    cached = _GLOB_RE_CACHE.get(pattern)
    if cached is not None:
        return cached
    out: list[str] = []
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                j = i + 2
                if j < n and pattern[j] == "/":
                    # `**/` → 跨目录且**含零层**（`src/**` 要能命中 `src/foo.py`）
                    j += 1
                    out.append("(?:.*/)?")
                else:
                    out.append(".*")
                i = j
                continue
            out.append("[^/]*")
            i += 1
            continue
        if c == "?":
            out.append("[^/]")
            i += 1
            continue
        out.append(re.escape(c))
        i += 1
    compiled = re.compile("^" + "".join(out) + "$")
    _GLOB_RE_CACHE[pattern] = compiled
    return compiled


def _norm_path(raw: str) -> str:
    """把路径规范成**仓库相对、POSIX 斜杠**（去 `./` 前缀与尾部 `/`）。"""
    p = raw.strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.rstrip("/")


def path_matches_glob(path: str, pattern: str) -> bool:
    """`path`（仓库相对）命中 glob `pattern` 吗。

    ★ 宁多勿漏的第二道：`path` 是 `pattern` 的**祖先目录**（如 path=`src`、pattern=`src/**`）
      也算命中 —— 少跑一道门的代价比多跑一道高。
    """
    path = _norm_path(path)
    if not path or not pattern:
        return False
    if path == pattern:
        return True
    if pattern.startswith(path + "/"):
        return True
    return _glob_re(pattern).match(path) is not None


@dataclasses.dataclass(frozen=True)
class AffectedPlan:
    """`--affected` 这一趟的**记账**（哪些门跑、哪些跳、为什么跳）。

    ★ 它是**纯数据**：`to_payload()` 直接进 `gates/last.json` 的 `affected` 块，
      好让"这趟是部分跑、跳了哪几道、为什么"事后**能从产物里看出来**（不许静默跳过）。
    """

    inputs: tuple[str, ...]
    ran: tuple[str, ...]
    matched: tuple[str, ...]
    skipped: tuple[tuple[str, str], ...]
    full_fallback: bool
    note: str

    def to_payload(self) -> dict[str, object]:
        return {
            "inputs": list(self.inputs),
            "ran": list(self.ran),
            "matched": list(self.matched),
            "skipped": [{"name": n, "why": w} for n, w in self.skipped],
            "full_fallback": self.full_fallback,
            "note": self.note,
        }


def plan_affected(
    paths: Iterable[str],
    all_doors: Sequence[str],
    door_inputs: Mapping[str, tuple[str, ...]] | None = None,
) -> AffectedPlan:
    """按「门 × 输入」表算出 `--affected` 该跑哪几道（**宁多勿漏**）。

    判据（与卡 140 §2 逐条对应）：
      ① `paths` 一条都命不中任何门的输入 ⇒ **跑全量**（`full_fallback=True`）；
      ② 某道门在表里**缺输入** ⇒ 那道门**永远跑**（`all_doors` 里不在表内的门）；
      ③ 命中就多跑：要跑 = 永远跑的门 ∪ 被命中的门；其余进 `skipped`（带原因）。
    ★ 只裁"名单"，**不碰任何门的判据**：`all_doors` 之外的语义（复用/超时/落盘）一个字不动。
    """
    table = DOOR_INPUTS if door_inputs is None else door_inputs
    norm = [p for p in (_norm_path(p) for p in paths) if p]
    doors = list(all_doors)
    always = [d for d in doors if d not in table]
    matched = [
        d for d in doors
        if table.get(d) and any(path_matches_glob(p, pat) for p in norm for pat in table[d])
    ]
    if not matched:
        note = ("没有任何路径命中门的输入表 ⇒ 宁多勿漏：**跑全量**"
                if norm else "没给路径（空）⇒ 宁多勿漏：**跑全量**")
        return AffectedPlan(inputs=tuple(norm), ran=tuple(doors), matched=(),
                            skipped=(), full_fallback=True, note=note)
    keep = set(always) | set(matched)
    ran = [d for d in doors if d in keep]
    skipped = [
        (d, f"输入未命中（该门登记的输入：{'、'.join(table[d])}）")
        for d in doors if d not in keep
    ]
    note = (f"命中 {len(matched)} 道门（{', '.join(matched)}）；"
            f"无输入映射永远跑 {len(always)} 道；跳过 {len(skipped)} 道")
    return AffectedPlan(inputs=tuple(norm), ran=tuple(ran), matched=tuple(matched),
                        skipped=tuple(skipped), full_fallback=False, note=note)


def changed_paths_from(rev: str) -> list[str]:
    """`--changed-from <REV>`：让 git 现算"改了哪些路径"。

    = `git diff --name-only <REV>`（含已提交与未提交的**已跟踪**改动）
      ∪ 未跟踪且未被 `.gitignore` 忽略的文件（排除 `gates/**` 与生成物，与封存指纹同口径）。
    ★ 生成物（`__pycache__/` · `*.pyc` · `*.egg-info/`）按 `is_generated` 排掉 ——
      否则在"装过 / 跑过测试"的树里它们会顶替成 `src/**` 的输入，把真机门白白全拉起来。
    """
    paths = [p for p in git("diff", "--name-only", rev).splitlines() if p.strip()]
    for line in git("ls-files", "--others", "--exclude-standard").splitlines():
        sp = line.strip()
        if sp and sp != "gates" and not sp.startswith("gates/") and not is_generated(Path(sp)):
            paths.append(sp)
    return paths


# ---------------------------------------------------------------- 受影响测试选择（卡 254 / T-G375）
# 病灶（卡 254 §为什么）：一次全量门禁 = `pytest -n 4`（4 个 worker 实测 334+275+139+117 =
#   865 MB）＋ mypy / ruff / 审计脚本 ⇒ **~1 GB 峰** —— 2026-10-15 两次被内存闸挡下。
# 本卡只做用户点的那一条（1②）：**改动文件 → 该跑哪些测试**的显式映射，接进落地链的
#   快门禁 ③″（`run_gates.py --fast`）。★ `-n` 自适应与全量串行化**本卡不做**（用户没点）。
#
# ★ 判据方向 = **宁多勿漏**（与 `--affected` 同一精神）：
#   ① 映射只认**命名对应**（`tools/<x>.py` ↔ `tests/test_<x>.py`，文件真存在才算）＋ 下面这张
#      **显式例外表** —— 不用"猜"、不用模型判断，任何人都能 `ls` / `grep` 复核；
#   ② 映射不到、或改动落在**公共模块**（`tools/pool/**` · `scripts/**` · `pyproject.toml` 等）
#      ⇒ **回退全量**（③″ 不裁选集；全量仍在收口链 **④** 跑，绝不在这里冒充跑过）；
#   ③ ★ 选集**从不替代 ④ 全量**：它只是"早点发现"的一层，判提交的仍是 ④。
#
# ★ 记账/文档不参与选集（`docs/` · `复盘/` · `gates/` · `.wt/`）：落地链**每一笔**都会写它们，
#   算进去 ⇒ 选集永远用不上。它们影响的用例（docs_fragments / card_doc_budget / ledger_summary…）
#   在 ④ 全量照跑 —— 这条写在这里，免得后来人以为漏了。
TEST_SELECTION_IGNORE_PREFIXES: tuple[str, ...] = ("docs/", "复盘/", "gates/", ".wt/")
#: 碰这些 ⇒ 回退全量（公共模块 / 测试基础设施）。
TEST_SELECTION_COMMON_PREFIXES: tuple[str, ...] = ("scripts/", "tools/pool/")
TEST_SELECTION_COMMON_FILES: tuple[str, ...] = (
    "pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini", "conftest.py",
)
#: ★ **显式例外表**：`tools/<x>.py` 没有**同名**测试、但有明确归属的用例。
#: 每一条都是 `tests/` 里**真的 import 该模块**的用例（`grep -n "^import <x>\|^from <x>" tests/`
#: 可复核）；宁缺勿滥 —— 拿不准就不写，走"映射不到 ⇒ 回退全量"。
TEST_SELECTION_EXCEPTIONS: dict[str, tuple[str, ...]] = {
    "tools/serve.py": ("tests/test_serve_port.py", "tests/test_lan_pairing_line.py"),
    "tools/sync_counts.py": ("tests/test_process_tools.py",),
    "tools/wb_verify.py": ("tests/test_wb_review.py",),
    "tools/wb_project.py": ("tests/test_pool_projects.py",),
    "tools/wb_registry.py": ("tests/test_pool_registry.py",),
    "tools/pool_quota.py": ("tests/test_quota_clock.py",),
    "tools/ui_text_audit.py": ("tests/test_ui_text_line.py",),
    "tools/ui_hotmap.py": ("tests/test_process_tools.py",),
    "tools/bench.py": ("tests/test_bench_tool.py",),
    "tools/mcp_client.py": ("tests/test_mcp_client_independent.py",),
    "tools/web_live_check.py": ("tests/test_dark_teeth.py", "tests/test_web_frontend.py"),
}


@dataclasses.dataclass(frozen=True)
class TestSelectionPlan:
    """`--fast` 这一趟的**选集记账**（选了哪几个用例 / 为什么退全量 / 哪些不算代码）。

    ★ 纯数据：`note` 会原样打给操作者看，退全量时**必须**说清原因（不许静默少跑）。
    """

    inputs: tuple[str, ...]
    tests: tuple[str, ...]
    ignored: tuple[str, ...]
    full_fallback: bool
    note: str


def select_tests(paths: Iterable[str], root: Path | None = None) -> TestSelectionPlan:
    """按「改动文件 → 测试」的**显式映射**算出该跑哪些用例（**宁多勿漏**）。

    - `tools/<x>.py` ⇒ `tests/test_<x>.py`（存在才映射）∪ `TEST_SELECTION_EXCEPTIONS[x]`；
    - `tests/test_<x>.py` ⇒ 它自己；
    - 公共模块 / 映射不到 / 文件不存在 ⇒ `full_fallback=True`、`tests=()`（回退全量）；
    - 记账/文档（`docs/` · `复盘/` · `gates/` · `.wt/`）⇒ 不算代码，记进 `ignored`；
    - 没有任何代码改动 ⇒ 空选集（不是"全量"，也没有该跑的东西）。
    ★ 只裁"跑哪几个用例"，**不碰任何判据**；全量门禁（④）一个字不动。
    """
    base = ROOT if root is None else root
    seen: set[str] = set()
    norm = [p for p in (_norm_path(p) for p in paths) if p and not (p in seen or seen.add(p))]

    ignored = tuple(p for p in norm if p.startswith(TEST_SELECTION_IGNORE_PREFIXES))
    code = [p for p in norm if not p.startswith(TEST_SELECTION_IGNORE_PREFIXES)]
    if not code:
        note = ("没有代码改动（只有记账/文档）⇒ 不选集（全量仍在 ④）"
                if norm else "没有改动 ⇒ 不选集（全量仍在 ④）")
        return TestSelectionPlan(inputs=tuple(norm), tests=(), ignored=ignored,
                                 full_fallback=False, note=note)

    chosen: list[str] = []
    why_full: list[str] = []

    def _add(test: str) -> None:
        if test not in chosen:
            chosen.append(test)

    for p in code:
        if p in TEST_SELECTION_COMMON_FILES or Path(p).name in TEST_SELECTION_COMMON_FILES:
            why_full.append(f"{p}（公共模块/测试基础设施）")
            continue
        if p.startswith(TEST_SELECTION_COMMON_PREFIXES):
            why_full.append(f"{p}（公共模块）")
            continue
        if re.fullmatch(r"tests/test_[^/]+\.py", p):
            if (base / p).is_file():
                _add(p)
            else:
                why_full.append(f"{p}（用例文件不存在/已删）")
            continue
        if p.startswith("tools/"):
            rest = p[len("tools/"):]
            if "/" in rest or not rest.endswith(".py"):
                why_full.append(f"{p}（映射不到：只认 tools/<x>.py）")
                continue
            same = f"tests/test_{rest[:-3]}.py"
            if (base / same).is_file():
                _add(same)
                for extra in TEST_SELECTION_EXCEPTIONS.get(p, ()):
                    _add(extra)
                continue
            extras = TEST_SELECTION_EXCEPTIONS.get(p, ())
            if extras and all((base / t).is_file() for t in extras):
                for t in extras:
                    _add(t)
                continue
            why_full.append(f"{p}（映射不到：{same} 不存在，也不在例外表里）")
            continue
        why_full.append(f"{p}（映射不到）")

    if why_full:
        return TestSelectionPlan(inputs=tuple(norm), tests=(), ignored=ignored,
                                 full_fallback=True,
                                 note="回退全量（宁多勿漏）：" + "；".join(why_full))
    tests = tuple(sorted(chosen))
    return TestSelectionPlan(inputs=tuple(norm), tests=tests, ignored=ignored,
                             full_fallback=False,
                             note=f"选中 {len(tests)} 个用例（串行 + --no-cov）")


def parse_status_paths(out: str) -> list[str]:
    """`git status --porcelain` 的路径列（`-uall --no-renames` 形态）→ 仓库相对路径列表。

    ★ 为什么单独成函数：`git()` 会 `.strip()` 整段输出，**第一行的状态前缀会被吃掉一个
      字符**（实测 `" M scripts/run_gates.py"` → `"cripts/run_gates.py"`），映射就永远失败。
      这里按"每行前 3 个字符是 XY+空格"切，空行跳过。
    """
    paths: list[str] = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        p = line[3:]
        if " -> " in p:
            p = p.split(" -> ", 1)[1]
        p = p.strip().strip('"')
        if p:
            paths.append(p)
    return paths


def worktree_changed_paths() -> list[str] | None:
    """此刻卡树里**已跟踪改动 + 未跟踪文件**（不含 ignored 生成物）；读不到 git ⇒ None。

    ★ 复用同一套 git 口径（`core.quotepath=false` · `-uall` · `--no-renames`），但**不借
      `git()`**：它会把整段输出 `.strip()`，第一行的 `" M "` 前缀会被吃掉一个字符
      （实测把 `scripts/run_gates.py` 读成 `cripts/run_gates.py`）。
    """
    probe = subprocess.run(  # noqa: S603 —— 参数写死，无 shell
        ["git", "-c", "core.quotepath=false", "rev-parse", "--git-dir"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if probe.returncode != 0:
        return None
    r = subprocess.run(  # noqa: S603 —— 参数写死，无 shell
        ["git", "-c", "core.quotepath=false", "status", "--porcelain", "-uall",
         "--no-renames"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if r.returncode != 0:
        return None
    return parse_status_paths((r.stdout or "").rstrip("\r\n"))


def quick_test_job(plan: TestSelectionPlan) -> tuple[str, list[str]] | None:
    """把选集翻成一条 pytest 命令（**串行 + `--no-cov`**）；回退/空集 ⇒ None（不跑）。

    ★ 为什么串行：本卡治的是**峰值内存** —— 一个 worker 只几百 MB，`-n 4` 实测 865 MB。
    ★ 为什么 `--no-cov`：`pyproject.toml` 的 `addopts` 带 `--cov-fail-under=70`，只跑几个
      用例时覆盖率必然不达标（假红）；验收命令（卡 254 第 3 条）同样是 `--no-cov`。
    """
    if plan.full_fallback or not plan.tests:
        return None
    return ("pytest_sel", [PY, "-X", "utf8", "-m", "pytest", *plan.tests,
                           "-q", "--no-cov", "-p", "no:cacheprovider"])


def _profile_filter(jobs: list[tuple[str, list[str]]], profile: str) -> list:
    """按档裁门；`all` 原样返回（默认路径逐字不变）。认不出的档直接抛 ValueError。"""
    if profile == "all":
        return jobs
    if profile not in GATE_PROFILES:
        raise ValueError(f"未知档：{profile}")
    keep = set(GATE_PROFILES[profile])
    return [j for j in jobs if j[0] in keep]


def build_jobs(quick: bool, fast: bool, profile: str = "all") -> list[tuple[str, list[str]]]:
    """门清单（**默认逐字不变**）：`--fast` 只留十几秒那几道；否则除 `--quick` 外加真机浏览器层。"""
    jobs: list[tuple[str, list[str]]] = [*COMMON, *REAL_PY]
    if fast:
        jobs = [j for j in jobs if j[0] in FAST]
    elif not quick:
        jobs += [(n, []) for n in BROWSER]
    return _profile_filter(jobs, profile)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="跳过真机层（提交前够用）")
    ap.add_argument(
        "--profile", default="all", choices=("all", *GATE_PROFILES),
        help=("只跑某一档（**内循环用**）：core=通用工程门；audit=台账/证据门；"
              "product=timeflow 产品门。默认 all，**收口链仍跑全量**"),
    )
    ap.add_argument("--fast", action="store_true",
                    help="只跑十几秒那几道（内循环；不落盘）＋ 受影响的测试选集（卡 254；"
                         "映射不到/公共模块 ⇒ 回退全量，全量仍在 ④ 跑）")
    ap.add_argument("--serial", action="store_true", help="全串行（对照并行下的偶发失败）")
    ap.add_argument("--no-reuse", action="store_true", help="不信复用记录，真机层全部重跑")
    ap.add_argument("--seal", action="store_true", help="提交前封存：只更新 tree 字段")
    ap.add_argument(
        "--affected", nargs="+", metavar="路径",
        help=("只跑「被这些路径影响」的门（**自查用，不是提交闸**）。判据方向 = 宁多勿漏："
              "① 路径匹配不上任何门 ⇒ 跑全量；② 某道门没登记输入 ⇒ 那道门照跑；③ 拿不准就多跑。"
              "★ 一切真的判提交的路径（收口链 tools/wb_land.py 与「提交前必须全量」的约定）"
              "仍然跑全量；本开关不会、也不许被当成提交闸。跑/跳的道与原因记进 gates/last.json。"),
    )
    ap.add_argument(
        "--changed-from", metavar="REV",
        help=("同 --affected，但路径由 git 现算：git diff --name-only <REV> + 未跟踪文件"
              "（排生成物与 gates/**）。同样只是「改完一小块自查」，不替代全量。"),
    )
    return ap


def main() -> int:
    ap = build_parser()
    args = ap.parse_args()
    if args.seal:
        return seal()

    # ★ 卡 102（T-G198）：开跑前先过**内存闸** —— 可用内存不够就拒跑（退出码 **3**；
    #   124 是"门超时"、2 是 TOML 预检失败、1 是门禁不过，都不与 3 冲突）。
    #   放在**一切之前**：走到这里时还没有任何门被启动（也没有清遗留 / TOML 预检的副作用）。
    mem_problem = memory_gate_problem()
    if mem_problem is not None:
        print(f"[FAIL] 内存闸拒跑：{mem_problem}", flush=True)
        return 3

    # ★ 卡 161 §4（INV-73）：门输入表里的**字面路径**必须 git 跟踪 ——
    # gitignored / 没 pin 的输入换个机器就变「在别人机器上不存在」的检查 ⇒ 不可复现。
    # 违规就拒跑（退出码 1），不静默。glob（`src/**`）不在此列。
    input_violations = door_input_violations()
    if input_violations:
        print(f"[FAIL] 门输入表里有 {len(input_violations)} 个字面路径未被 git 跟踪：",
              flush=True)
        for p in input_violations:
            print(f"  - {p}", flush=True)
        print("  （gitignored 的输入要么删掉、要么显式豁免并写理由）", flush=True)
        return 1

    jobs = build_jobs(args.quick, args.fast, args.profile)

    # ★ T-G239（卡 140）：`--affected` / `--changed-from` —— **只裁门名单**，不碰别处。
    affected_plan: AffectedPlan | None = None
    if args.affected is not None or args.changed_from:
        paths: list[str] = list(args.affected or [])
        if args.changed_from:
            paths += changed_paths_from(args.changed_from)
        seen: set[str] = set()
        uniq = [p for p in paths if not (p in seen or seen.add(p))]
        affected_plan = plan_affected(uniq, [n for n, _ in jobs])
        jobs = [j for j in jobs if j[0] in set(affected_plan.ran)]
        print(f"=== --affected：只跑受影响的 {len(jobs)} 道门"
              "（**自查用**；★ 提交前仍要全量）===", flush=True)
        print(f"  [affected] 输入 {len(uniq)} 条：{uniq if uniq else '（空）'}", flush=True)
        print(f"  [affected] {affected_plan.note}", flush=True)
        for _n, _why in affected_plan.skipped:
            print(f"  [affected] 跳 {_n:<22} {_why}", flush=True)

    # ★ 卡 254（T-G375）：`--fast`（落地链 ③″ 快门禁）再补一道「受影响的测试」门 ——
    #   只跑与**本次改动**有显式映射的那几个用例（串行 + --no-cov）。★ 它**不替代** ④ 全量：
    #   映射不到 / 公共模块 ⇒ 回退全量（这一趟不裁选集），判提交的仍是收口链 ④。
    if args.fast:
        changed = worktree_changed_paths()
        print("=== 受影响测试选择（卡 254；★ 提交前仍要 ④ 全量）===", flush=True)
        if changed is None:
            print("  [select] 读不到 git 改动 ⇒ 不裁选集（全量仍在 ④）", flush=True)
        else:
            sel = select_tests(changed)
            print(f"  [select] 改动 {len(changed)} 条：{changed if changed else '（空）'}",
                  flush=True)
            print(f"  [select] {sel.note}", flush=True)
            for _p in sel.ignored:
                print(f"  [select] 记账/文档不参与选集（其用例在 ④ 照跑）：{_p}", flush=True)
            quick_job = quick_test_job(sel)
            if quick_job is not None:
                print(f"  [select] 选集 {len(sel.tests)} 个用例（串行 + --no-cov）："
                      f"{', '.join(sel.tests)}", flush=True)
                jobs.append(quick_job)

    cmds = dict(jobs)

    ok_docs: bool = True                     # --fast 不判"文档同提交"（那是提交闸的事）
    missing: list[str] = []
    if args.fast:
        # ★ 这一档**不写 gates/last.json**：它不是提交闸。写了就会让
        # "门禁产物与提交一致"（审计第 ⑤ 条）失效 —— 那是拿半轮结果冒充一轮。
        print("=== --fast：开发内循环（ruff / 护栏 / 审计；**不是提交闸，不落盘**）===")
    else:
        ok_docs, missing = docs_sync_precheck()
        print("=== ④ 文档与代码同提交（提交前检查）===")
        if ok_docs:
            print("  [OK ] 台账/changelog/CHECKPOINT 都在改动清单里（或其片段在），"
                  "且**片段 ↔ 汇总一致**（或本轮没改源码）")
        else:
            print(f"  [FAIL] 文档同步未过（改了源码没同步 / 片段与汇总对不上）：{missing}")

    # ★ ⓪ TOML 语法预检（T-G52）：台账是唯一真源，而「正文里写了 ASCII 双引号」这条坑
    #   已经在同一个会话里踩了 8 次 —— 一踩就是整份台账解析不了、`audit` 与 `audit_titles` 双红，
    #   而报的是 tomllib 的原始错误（还得自己去数第几行第几列）。这里先花 0.1 秒说清楚，
    #   既不让两道门白跑一趟，也不用我去数列号。
    pre = subprocess.run(
        [PY, "-X", "utf8", str(ROOT / "scripts" / "check_toml.py")],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if pre.returncode != 0:
        print("=== ⓪ TOML 语法预检（门禁开跑之前）===")
        print((pre.stdout or pre.stderr).rstrip())
        print("\nTOML 有问题，门禁**没有跑** —— 先修上面那一行，再跑一次。")
        return 2

    # ★ T-G157：开跑先印出**验的是哪棵树** —— 本树 `src` 是子进程 PYTHONPATH 的首位。
    print(f"=== 本树 src = {ROOT / 'src'}（子进程 PYTHONPATH 首位，T-G157）===", flush=True)

    # ★ ⑨ T-G156：全量门禁开场先清**本树端口段**上的遗留（孤儿服务/无头 Edge）。
    #   只在**会用到端口**的档位跑（全量 = 含浏览器层）；`--quick` / `--fast` 不起真机服务，
    #   清了没意义还可能误伤，所以那两档不碰（`--fast` 更不写盘）。
    #   ★ T-G239：`--affected` 若把浏览器层裁掉了，就不清 —— 这趟不起真机服务，没有端口可清。
    if not args.fast and not args.quick and any(n in BROWSER for n, _ in jobs):
        cleanup_leftovers()

    if args.serial:
        mode = "串行（--serial）"
    elif xdist_available():
        w = pytest_workers()
        # ★ 卡 A266：默认值可能因**内存紧**降到 1（不一定是人设了 `TF_PYTEST_WORKERS=1`）——
        #   文案别写死成因，免得默认降档时印出一句假话。
        mode = f"并行（pytest-xdist，-n {w}）" if w > 1 else "串行（worker=1）"
    else:
        mode = "串行（环境里没装 pytest-xdist）"
    if not args.fast:
        print(f"=== pytest 跑法：{mode} ===")

    # ★ T-G196 每道门硬超时：整轮只解析一次（到点就掐整棵树，掐完记 124 判红）。
    timeout = door_timeout()
    if not args.fast:
        if timeout is None:
            print("=== 每道门硬超时：**已关**（TF_GATE_DOOR_TIMEOUT=0）—— 一道卡死会挂死整趟 ===")
        else:
            print(f"=== 每道门硬超时：{_fmt_secs(timeout)} 秒（到点掐整棵进程树，记 exit=124）===")

    # 复用判定：只对"输入确实是那几样"的真机门做（--quick 里本来就没有真机层，--fast 更不碰）。
    records = load_reuse()
    reused: dict[str, str] = {}
    todo: list[tuple[str, list[str]]] = []
    not_run: list[str] = []
    for name, _ in jobs:
        mark = None if args.fast else skip_reused(name, records, args.no_reuse)
        if mark is not None:
            reused[name] = mark
            print(f"[REUSE] {name:<22} 输入未变（{mark}）→ 复用上次通过判定")
            continue
        cmd = resolve_cmd(name, cmds, args.serial)
        if cmd is None:
            print(f"[WARN] {name:<22} 跳过：环境里没有 node（未验证，不算通过）")
            not_run.append(name)
            continue
        todo.append((name, cmd))

    order = {name: i for i, (name, _) in enumerate(jobs)}
    results: list[dict[str, object]] = []

    if args.serial:
        # 全串行：给"并行下的偶发失败"当对照跑法（本文件自己的老路径）
        for name, cmd in todo:
            proc, t0, why = start_gate(name, cmd)
            results.append(dead_gate(name, t0, why) if proc is None
                           else finish_gate(name, proc, t0, timeout))
    else:
        # **两条泳道并行**：轻门一路、真机浏览器一路。
        # ★ 起进程一律在**主线程依次**做（见 start_gate 的注释：多线程同时 Popen 在 Windows 上
        #   会 WinError 87）；并行只发生在"等输出"这一半 —— 而墙钟时间恰恰由等待决定。
        # ★ 卡 091：浏览器层（render / ui_flow）改成**内部串行**。原来两个真浏览器实例同时跑，
        #   满载下争磁盘 IO / 内存 / 浏览器内部资源，ui_flow 的"等元素就绪"抢不到时间片而误判
        #   稳定（症状：元素 0×0 / 匹配 0 个 / 可见 0 个），且每趟挂的是不同行为流（竞态签名，
        #   非确定性缺陷）。串行后 ui_flow 跑时 render 已结束，不再争浏览器资源；轻门泳道仍与
        #   浏览器层并行（那是 CPU vs 浏览器，争用小）。代价：总时长 ≈ render+ui_flow 而非 max，
        #   在 gate_lock 90 分钟预算内。
        light = [(n, c) for n, c in todo if n not in BROWSER]
        heavy = [(n, c) for n, c in todo if n in BROWSER]
        print(f"=== 泳道：轻门 {len(light)} 道 ∥ 真机浏览器 {len(heavy)} 道（浏览器层内部串行）===")
        # 轻门先在主线程依次起进程（Popen 不并发，见 start_gate 注释）
        started_light: list[tuple[str, subprocess.Popen[str] | None, float, str]] = []
        for name, cmd in light:
            proc, t0, why = start_gate(name, cmd)
            started_light.append((name, proc, t0, why))

        def run_heavy_serial() -> list[dict[str, object]]:
            out: list[dict[str, object]] = []
            for name, cmd in heavy:           # 浏览器层串行：render 完了再 ui_flow
                proc, t0, why = start_gate(name, cmd)
                out.append(dead_gate(name, t0, why) if proc is None
                           else finish_gate(name, proc, t0, timeout))
            return out

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            heavy_future = pool.submit(run_heavy_serial)
            light_futures = [
                pool.submit(dead_gate, n, t0, why) if proc is None
                else pool.submit(finish_gate, n, proc, t0, timeout)
                for n, proc, t0, why in started_light
            ]
            results = heavy_future.result() + [f.result() for f in light_futures]

    for name, mark in reused.items():
        results.append({
            "name": name,
            "exit_code": 0,
            "seconds": 0,
            "summary": f"复用上次通过判定（输入未变 {mark}）",
            "reused": True,
            "inputs_hash": mark,
        })
    for name in not_run:
        results.append({
            "name": name, "exit_code": 3, "seconds": 0,
            "summary": "环境里没有 node：未验证，不算通过",
            "blocking": False, "status": "NOT RUN",
        })
    # 结果按**固定顺序**排（而不是完成顺序）：last.json 要能逐字节比较，trailer 也要稳定
    results.sort(key=lambda r: order.get(str(r["name"]), 99))

    # 信息性检查：只报告、不阻断（blocking=False，不计进 ok）
    for name, cmd in ([] if (args.quick or args.fast) else INFO_GATES):
        t0 = time.time()
        info_proc = subprocess.run(
            cmd, cwd=ROOT, env=env(), capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False,
        )
        out = (info_proc.stdout or "") + (info_proc.stderr or "")
        tail = [ln.strip() for ln in out.splitlines() if ln.strip()]
        summary = next(
            (ln[:160] for ln in reversed(tail) if ln.startswith("共 ") or "全部对得上" in ln), ""
        )
        summary = summary or (tail[-1][:160] if tail else "")
        item = {
            "name": name,
            "exit_code": info_proc.returncode,
            "seconds": round(time.time() - t0, 2),
            "summary": summary,
            "blocking": False,
            "note": "信息性：台账↔规格 标题对账；T-D1 完成后改成阻断项（audit_titles.py --check）",
        }
        results.append(item)
        mark = "[OK ]" if info_proc.returncode == 0 else "[WARN]"
        print(f"{mark} {name:<22} exit={info_proc.returncode}  {item['seconds']}s  "
              f"{summary}（不阻断）")

    blocking = [r for r in results if r.get("blocking", True)]
    ok = gates_ok(results)
    if not args.fast:
        ok = ok and ok_docs
    passed = [r for r in blocking if int(str(r["exit_code"])) == 0]

    if args.fast:
        bad = [r for r in blocking if int(str(r["exit_code"])) != 0]
        if bad:
            print(f"\n[FAIL] --fast 里 {len(bad)} 道不通过：{[r['name'] for r in bad]}")
            return 1
        print("\n--fast 全过 ✅（只覆盖「改一行就能犯」那几类；提交前仍要 --quick 或全量）")
        return 0

    payload = {
        "rev": git("rev-parse", "--short", "HEAD"),
        # ★ T-G179 封存指纹：除 gates/** 外即将提交内容的 tree 哈希（可复现固定点）。
        # 为什么摘掉 gates/：gates/last.json 自己在那棵树里，写进它自己的哈希会让树变化 →
        # 永远追不上（自指悖论）。它不是"完整提交的 tree"，也**不含门禁产物**。
        # 口径自述见 tree_scope（旧笔没这个字段 → wb_verify 按旧口径标 INFO 不核）。
        "tree": staged_tree(),
        "tree_scope": TREE_SCOPE,
        "parent": git("rev-parse", "--short", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(git("status", "--porcelain")),
        "at": datetime.now().isoformat(timespec="seconds"),
        "quick": args.quick,
        "docs_sync_ok": ok_docs,
        "docs_sync_missing": missing,
        "ok": ok,
        # ★ 卡 161 §2（INV-24）：跑法落盘 —— worker 数与跑法一目了然，
        #   让"我手打 1 个 worker（pytest 612s 占全趟 86%）"从静默变成会被发现的事。
        #   ★ worker 数只读 `pytest_workers()` 一处（不写第二份口径）。
        "workers": pytest_workers(),
        "pytest_mode": mode,
        # 慢门清单（卡 161 §2 验收）：把「哪道门多少秒」打出来——"盯着慢"的第一份真读数。
        #   阈值 `TF_GATE_DOOR_BUDGET`（默认 600s，`=0` 关）；告警不阻断
        #   （硬超时仍由 door_timeout 掐）。
        "slow_doors": sorted(
            [{"name": r["name"], "seconds": r.get("seconds", 0)}
             for r in results
             if r.get("seconds") and (door_budget() is None or r["seconds"] >= door_budget())],
            key=lambda x: x["seconds"], reverse=True,
        ),
        "gates": results,
        # 没验证成的门（当前只有渲染层会遇到：起不了真浏览器）。**不是"通过"**，
        # 单列一栏 + 写进 trailer，让"这次提交哪些东西没被验证过"有据可查。
        "not_run": not_run,
        # 复用了上次判定的门（T-G47）：单列一栏 + 带上输入哈希。**不是"通过"的同义词** ——
        # 它是"这一层的输入一个字节都没变，所以上次那个判定仍然成立"，写出来才禁得住问。
        "reused": {k: v for k, v in reused.items()},
        # ★ T-G212 / 卡 115：门禁跑时**未跟踪**的文件清单（不含 `gates/**`）。
        #   这是"生成了却没进提交"那条判据的凭证：审计逐条查它们提交后有没有被 git 跟踪。
        #   既有字段语义一个字不动，这里只**追加**一个新键。
        "untracked": untracked_files(),
        "trailer": "; ".join(
            [f"{r['name']} {r['summary']}" for r in passed]
            + [f"{n} NOT RUN" for n in not_run]
        ) or "（无通过项）",
    }
    # ★ T-G239（卡 140）：`--affected` 是**部分跑** —— 把"跑了/跳了/为什么跳"记进 `affected` 块。
    #   ★ `ok` 的语义一个字不动（仍 = "这一趟**真跑的**阻断门全过"）；本块只**披露范围**，
    #   让事后能从产物里看出"这不是一轮全量门禁"。默认（不给 `--affected`）**不加这个键**
    #   → `last.json` 形状逐字不变（卡 §4 硬要求）。
    if affected_plan is not None:
        payload["affected"] = affected_plan.to_payload()
        payload["trailer"] = ("【--affected：只跑了受影响的 "
                              f"{len(jobs)} 道门，未跑全量】" + str(payload["trailer"]))
    # ★ A324：**只跑一档**时把档名写进封存 —— 让「挑一档冒充全量」在产物上可见；
    #   默认 `all` 不写这个键，`last.json` 形状逐字不变（A321 §4 硬要求）。
    if args.profile != "all":
        payload["profile"] = args.profile
        payload["trailer"] = (
            f"【--profile {args.profile}：只跑了这一档，未跑全量】" + str(payload["trailer"])
        )
    GATES.parent.mkdir(parents=True, exist_ok=True)
    GATES.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    # 复用记录只在**这一轮真跑且通过**时更新（复用过的门保持原记录：哈希本来就一样）
    for name in REUSABLE:
        if name in reused:
            continue
        entry = next((r for r in results if r["name"] == name), None)
        if entry is None or int(str(entry["exit_code"])) != 0:
            continue
        if name in REUSE_INPUTS:
            records[name] = {
                "hash": input_hash(REUSE_INPUTS[name]),
                "verdict": "pass",
                "at": datetime.now().isoformat(timespec="seconds"),
                "what": "输入哈希一致时可复用这条判定（T-G47）",
            }
    save_reuse(records)
    print(f"\n[落盘] gates/last.json  ok={ok}  rev={payload['rev']}")
    used = ", ".join(f"{k}({v})" for k, v in reused.items()) or "无"
    print(f"[复用] {used}")
    print(f"[建议 trailer] Gates: {str(payload['trailer'])[:200]}")
    if not ok:
        print("\n质量门或文档同步未通过 —— **不许提交**（用户约定）。")
        return 1
    print("\n质量门 + 文档同步通过 ✅（下一步：commit 并带上 Task:/Refs:/Gates: trailer）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
