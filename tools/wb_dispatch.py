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
  ⑤ ★ 卡 095：**端口段体检**（铁律 37）—— 给了端口段（`--port-base` 或 `TF_DISPATCH_PORT_BASE`）
     且段内有占用 → 拒派并点名占用者；**没给段 → 跳过**（不检查也不假装检查，不许自动换段）。
  ⑥ ★ 卡 125（T-G223）：**四条守卫干跑**（树 `tree_guard` / 冲突域 `domain_guard` / 门禁锁
     `lock_guard`）—— 判据全在 `pool.guards`；冲突域从队列**真读**（查不到就拒，别猜空域）。
     真派活（`--execute`）前先 `pool.registry.reserve` 占树，**任何退出路径都 release**
     （`atexit` 兜底）；dry-run **不占树**。
     ★ `--already-reserved`：调用方（MCP 写面 `pool_cancel`/`pool_dispatch`）**已经占过树**时用 ——
     **只跳过**守卫与占/还树，别的检查（内存 / 登录 / 白名单 / 日志）**照走**；不带它就一字不变。
  ⑦ ★ 卡 135（T-G233）：**卡树基点过期** —— 卡树的基点（`A`）之后主树（`B`）若改过**这张卡
     要碰的文件**（域从队列真读）⇒ 拒派并点名文件 / 提交 / 修法（收口时会把卡树那份旧文件
     拷回主树 = 静默覆盖新改动，真咬过）；只改了域外文件 ⇒ 放行（别误伤多批并行）；
     算不出 `A`/`B` ⇒ 如实说"算不出基点，跳过"并继续 —— **只拒不猜**。

用法（默认 **dry-run**：只打印将要执行的命令，不派活）：
    python -X utf8 tools/wb_dispatch.py --card 001 --spec 复盘/外包卡-001-独立复核T-G79.md
    # 真想派活加 --execute；跑完会自动用 tools/wb_status.py 渲染时间线
    # --model 默认 deepseek-v4.1-flash（用户 2026-09-26 要的那一档；★ CLI 2.158.0 的可用列表里
    # 已经没有 deepseek-v3-2-volc 了 —— 默认模型是 hy4-preview，实测 JSON 里回的是 hy4-preview-f）
    # --cli 覆盖 CLI 入口；--permission-mode 默认 bypassPermissions（见下）
    # --no-preflight 跳过登录自检（省 10 秒，接口不改）
    # ★ T-G173（卡 078）：--lean 改读 ≤6KB 开工切片 brief-<卡>.md（默认关，行为不变）

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
  ② **看门狗** —— 跑的时候盯着：日志**静默**过久（卡死）或最近 12 次工具调用里
     **同一件事出现 ≥ 5 次**（空转）→ 掐掉整棵进程树，并把现场（最后几步、碰过哪些文件）报出来。
     ★ **静默阈值不是常数（T-G94）**：一次工具调用期间**本来就静默**（全量门禁 ~4 分钟、
     冷缓存 worktree 里十几分钟），旧写法会把这种正常的长调用误判成卡死 → 现在：
     **有工具在飞**（`tool_use` 没配上 `tool_result`）时静默是预期的 → 底线上抬到 30 分钟；
     再按 **2.5 × 历史最长一次已完成调用**自适应。判卡死时报告**带现场**（在跑什么 / 跑了多久 /
     历史最长 / 这一次的阈值）—— 不再让主控自己去翻 log 猜。
  ③ **心跳** —— 每 2 分钟一行（已跑多久 / 回合 / 工具 / 碰过文件 / 静默多少秒）：
     让"它还在动"从猜测变成看得见的事实。
两个默认值按用户 2026-09-26 的决定：`--autocompact 1m`（CLI 钳位 100k–1M）、
`--effort` **不加**（保持默认 High）；两条都对着 CLI 2.158.0 的 `--help` 核过。

★ 稳定化（T-G90，用户点名「尽量把活给 WorkBuddy，增强稳定性」）：外包最大的风险不是"干得慢"，
而是**干到一半断了、然后从头再来**（卡 002 那轮花了 14.2M input tokens）。所以这里补三件：
  ① **续跑**：不再传 `--no-session-persistence`，跑完把 `session_id` 落到
     `gates/diag/wb-<卡>.session.txt`；`--resume <id>`（或 `--resume auto` 读那个文件）带着**同一个
     会话**接着干 —— 实测首轮"记住 42"、`--resume` 后问它 → 回 `42`，`session_id` 不变；
  ② **自动续跑**：`--retry N`（默认 1）—— 卡死 / 超时 / 没跑完时**自动**带同一会话再来一轮，
     每轮一个 log（`wb-<卡>.r2.jsonl`…，证据不互相盖）；
     ★ **只对"被打断"续，不对"空转"续**：空转是原地打转，续跑只会让它接着转（那正是看门狗要掐的）；
  ③ **铁律进系统提示**：`--append-system-prompt` 把八条铁律钉进**系统提示**（不再只靠开场白那句 ——
     开场白会随着上下文压缩越来越远，系统提示还在）；规矩与卡规格冲突时**以卡规格为准**。
边界（如实写）：会话会落在 `~/.codebuddy/projects/` 下**慢慢堆积**（换来的是能续跑）；续跑时
工人会重新看到之前的上下文（token 照花）—— 所以它省的是"重做一遍的活"，不是"重读一遍的钱"。
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import locale
import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_status  # noqa: E402 —— 同一个目录，渲染复用状态器（别写第二份）

# ★ 卡 109（T-G206）/ 卡 125（T-G223）：这些判据**只有一份真源**，都在 `tools/pool/` 包里
#   —— 这里只 import、只调用，不另写一份（本地副本各删一处；判据漂一次就会越界 / 串卡）。
#   ★ 卡 125 的来路（GLM-5.3 审查 2.1）：从前只有 MCP 写面与手工 CLI 接守卫，走**默认派活器**
#   `wb_dispatch --execute` 时不变量 ①②③⑤ 全部失效、且对其他窗口不可见（一树两写者不会被咬）。
from pool import guards as pool_guards  # noqa: E402 —— 守卫唯一实现（pool.guards）
from pool import registry as pool_registry  # noqa: E402 —— 作业登记唯一实现（pool.registry）
from pool.jobs import card_artifacts  # noqa: E402 —— 产物定位唯一实现（pool.jobs）
from pool.models import SwitchFileError, load_switches  # noqa: E402 —— 外部模型开关（卡 138）
from pool.plan import BacklogError, load_backlog  # noqa: E402 —— 队列/冲突域唯一实现（pool.plan）
from pool.review import outside_allow  # noqa: E402 —— 白名单越界唯一实现（pool.review）

# ★ T-G96：Windows 上派活器自己发起的那些 `subprocess` 不加这个，Windows 11 会把控制台程序
#   转交给**默认终端宿主**（WindowsTerminal.exe -Embedding）→ 任务栏里留下一个**空窗口**、
#   标题还是那个 node.exe 的名字，让人以为「它还在跑」。用户 2026-09-26 实际被它迷惑过。
#   非 Windows 平台这个 kwargs 是空字典（别的平台没有这个概念）。
NO_WINDOW: dict = ({"creationflags": subprocess.CREATE_NO_WINDOW}     # type: ignore[attr-defined]
                   if os.name == "nt" else {})

# ★★ 模型白名单（用户 2026-09-26 明令：「黑名单锁死吧，就是只有白名单里面的模型，名字，
#   带模型的名字，你才能调用」→ **默认拒绝**：不在名单里的模型一律调不动，这是代码里的
#   硬闸门，不是一句叮嘱）。
# ★★ 改这份名单必须先问用户（加名字 / 换顺序 / 改默认 → 只有用户能改；主控不许自作主张）。
# ★ 顺序就是「默认优先」：① 默认；② ① 被限流/额度耗尽时的替补（轮换口径：
#   换 ② 让它干一两张卡，然后再探 ①，恢复了换回来）。换模型只影响新派的卡，
#   已经在某模型上跑的卡不许中途换。★ 不许做成读环境变量 / 读配置文件 / 命令行传一串的宽松形式。
MODEL_WHITELIST: tuple[str, ...] = ("deepseek-v4.1-flash", "glm-5.3-flash")
DEFAULT_MODEL = MODEL_WHITELIST[0]

# ★★ 2026-10-02 **一次性**模型的入口（**故意不进轮换链**）—— ★ **当天已按用户令清空**。
#   用户原话两句，第二句是**撤回**：
#   ① 「把这些东西再喂给 GLM5.3，注意，我这次要求的是 GLM5.3 不是 Flash …
#      你可以把它列到白名单，但是**我希望是一次性的调用**」；
#   ② ★ **「GLM5.3 用完就撤。」**
#   ⇒ 处置：**机制留着、名额清空** —— 本常量是"一次性放行"的**唯一入口**，
#     要再放行谁就填进来（**仍然不进 429 轮换链**：轮换只走 `MODEL_WHITELIST`）。
#   ★ 当时现场核过的读数（留档）：`--model glm-5.3 -p "只回 OK"` ⇒ `subtype=success`，
#     且 init 事件的 `model` 就是 `glm-5.3`（**没被静默降级**）；那次外部审查已落档
#     （批 `B-ARCH1` / `T-G220`）。
#   ★ **撤掉之后的行为**：`glm-5.3` 回到「默认拒绝」，与任何表外模型**一视同仁**
#     （要再派会被拒，并列出允许集）。
ONE_OFF_MODELS: tuple[str, ...] = ()
#: 名单常量 = 轮换名单 ∪ 一次性授权（★ **下限**）。闸门查的是「本常量 ∪ 外部开关文件里打开的」——
#: 见 `effective_allowed_models()`；轮换只走 `MODEL_WHITELIST`（开关**不进轮换链**）。
ALLOWED_MODELS: tuple[str, ...] = MODEL_WHITELIST + ONE_OFF_MODELS
# ★ 卡 138：外部开关文件里 `true` 的模型**额外放行**。
#   文件 = `infra/pool/model-switches.toml`（只有用户能改）。
#   **只做加法**（名单是下限、开关不许把名单里的关掉），**不进 429 轮换链**。

# ---------------------------------------------------------------- 429 / 额度（卡 029 §2.5）
# ★ 429 长得像成功：CLI 给 `result.subtype = error_during_execution` + 空回话 + 退出码 0 ——
#   只看退出码会把「额度烧干」读成「正常收工」（2026-09-26 真撞过）。所以判据读事件本身：
#   `result.errors` / `errors_info` 里的 `status 429` / `code 6004` / `category quota`，
#   或正文里的「额度已用尽」「使用量已超出频率限制」。两种分开记：
#   限流（带「将在 <时间> 重置」）vs 余额耗尽（没有重置时间）。
QUOTA_STATUS_NEEDLES = ("429", "6004", "quota")
QUOTA_TEXT_NEEDLES = ("额度已用尽", "使用量已超出频率限制")
DEFAULT_QUOTA_WAIT = 300         # 撞 429 → 先等 300 秒再探（用户 2026-09-26：「你先等一下」）
DEFAULT_INPUT_BUDGET = 25_000_000  # 防空烧：单卡 input tokens 预算（实测单卡最高 18,400,724）


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
# ★ T-G94：静默 480 秒这个常数**会误杀正常的长工具调用** —— 一次工具调用本来就会静默很久
#   （主树全量 run_gates.py ~4 分钟、冷缓存 worktree 里 ui_flow 十几分钟）。所以判卡死改成
#   "先看现场再判"：有工具在飞 → 底线上抬到 BUSY_STALL_SECONDS；再按"历史最长一次调用 × 2.5"自适应。
BUSY_STALL_SECONDS = 1800        # 有工具在飞时的静默上限（30 分钟）—— 在飞 ≠ 卡死
TOOL_DURATION_FACTOR = 2.5       # 阈值 = max(底线, 2.5 × 历史最长一次已完成调用)；留余量，宁可晚掐
# ★ T-G96：`2.5 × 历史最长`**必须有绝对上界**（复核 1969b46 §3 挑出来的「漏杀」风险）——
#   没有上界时，一次 60 分钟的调用会把阈值抬到 150 分钟（2.5 × 3600），而它一轮内不衰减。
#   实测三份真 log 里最长一次调用是 **389.3s / 81.2s / 69.1s** —— 60 分钟已是本项目最长门禁的
#   约 5 倍，所以封顶取 3600（★ 这是主控定的口径，可被质疑）。
ADAPTIVE_MAX_SECONDS = 3600
REPEAT_WINDOW = 12               # 空转只看最近多少次工具调用
REPEAT_NEED = 5                  # 同一件事在里面出现几次算空转
HEARTBEAT_SECONDS = 120          # 心跳行间隔
POLL_SECONDS = 5.0               # 看门狗多久醒一次
SCENE_LINES = 6                  # 掐掉时报最后几步
DEFAULT_RETRIES = 1              # 被中断后自动带同一会话续跑几次
DEFAULT_TIMEOUT = 7200           # 默认超时（秒）：卡 002 用了 44 分钟，长卡给到 2 小时
                                 # ★ 超时**不是失败**，是"掐掉再续跑"的信号（见 §长跑那节）

# ---------------------------------------------------------------- 八条铁律（进**系统提示**，T-G90）
# 为什么进系统提示而不是只写在开场白里：工人换轮次 / 上下文被自动压缩之后，开场白会越来越远，
# 系统提示还在。★ 它与卡规格冲突时**以卡规格为准** —— 卡才是"这一轮的口径"。
IRON_RULES = (
    "你是这个仓库的外包工人：主控写卡、你干活、主控复核。八条铁律："
    "① 以卡规格为准：能改哪些文件、要不要跑门禁、能不能提交，卡里写了就照卡办；"
    "② 只在卡的白名单内改文件 —— 越界 = 这一轮作废；"
    "③ 不许假完成：说「做完了」必须给出可复现的命令与输出（先跑红、再跑绿）；"
    "④ 门禁不过不许提交；卡要求提交时，提交信息末尾四行 trailer 一行不许少"
    "（Task/Refs/Ledger/Gates）；"
    "⑤ 一写一读：工作区归你，别人的未提交改动一个字都不许碰；"
    "⑥ 禁区：真实数据库、备份目录、别人的未跟踪文件；"
    "⑦ 拿不准口径就停下、在回报里说明，别自己定产品决策；"
    "⑧ 按卡的回报格式回报，边界（没做到的部分）如实写、不假装。"
)

OPENING = (
    "读 复盘/交接-重构进度.md + 复盘/长任务执行协议.md + 复盘/新窗口交接卡.md + "
    "复盘/外包-卡表与规矩.md + {spec}（这一张卡的规格）。你有完整 CLI、工具链与主控相同。"
    "★ **以卡规格为准**：它写了这一轮能改哪些文件、能不能提交、要不要跑全量门禁、禁区是什么；"
    "规格与本句冲突时，按规格执行。干完按规格要求回报。卡号 {card}。"
    "★ 改文案/措辞/字面/常量类的卡，**开工前**先跑 "
    "`python -X utf8 tools/pin_check.py --literal \"<要改的字面>\"` 查谁逐字钉着它"
    "（有 ★ 钉子命中就先在回报里列出来，别撞上了才知道 —— 卡 159）。"
)

# ★ T-G173（卡 078）：--lean 的开场白 —— 不拼那四份文档，改读 ≤6KB 开工切片（wb_brief 生成）。
LEAN_OPENING = (
    "读 {brief}（开工切片：现状现算 + 最新 CHECKPOINT + 本卡引用到的规矩 + 白名单/禁区 + 固定坑页）"
    " + {spec}（这一张卡的规格）。你有完整 CLI、工具链与主控相同。"
    "★ **以卡规格为准**：它写了这一轮能改哪些文件、能不能提交、要不要跑全量门禁、禁区是什么；"
    "规格与本句冲突时，按规格执行。干完按规格要求回报。卡号 {card}。"
    "★ 改文案/措辞/字面/常量类的卡，**开工前**先跑 "
    "`python -X utf8 tools/pin_check.py --literal \"<要改的字面>\"` 查谁逐字钉着它"
    "（有 ★ 钉子命中就先在回报里列出来，别撞上了才知道 —— 卡 159）。"
)


def ensure_lean_brief(card: str, worker_cwd: Path | None = None) -> str:
    """--lean：切片缺了就**现生成**（tools/wb_brief.py --card <卡>）；返回仓库根相对路径。

    ★ 卡 103：把 `--cwd`（工人干活树）透传给 `wb_brief.py` —— 切片第一行才写得出那句硬话
    （"你必须 cd <绝对路径> 再干活"）。
    """
    rel = f"gates/diag/brief-{card}.md"
    if not (ROOT / rel).exists():
        cmd = [sys.executable, "-X", "utf8", "tools/wb_brief.py", "--card", card]
        if worker_cwd is not None:
            cmd += ["--cwd", str(worker_cwd)]
        subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", **NO_WINDOW)
    return rel


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


def switch_open_models() -> tuple[str, ...]:
    """外部开关文件里**打开**（值为 `true`）的模型 —— **只做加法**、不进 429 轮换链。

    ★ 文件不存在 ⇒ 空（不报错）；文件坏 ⇒ `SwitchFileError` 冒泡（**不许静默当空**）。
    """
    return tuple(name for name, on in load_switches().items() if on)


def effective_allowed_models() -> tuple[str, ...]:
    """允许集 = 名单常量 `ALLOWED_MODELS` ∪ 开关文件里打开的模型。

    ★ 名单是**下限**、开关只做**加法**。
    ★ 现算（每次读开关文件），**不**拼进模块常量：开关是**数据**、用户随时能改；拼进常量
      就变成「改源码才生效」，正是卡 138 要消灭的东西。轮换链仍只走 `MODEL_WHITELIST`。
    """
    out = list(ALLOWED_MODELS)
    for name in switch_open_models():
        if name not in out:
            out.append(name)
    return tuple(out)


def model_rejected(model: str) -> str:
    """模型白名单硬闸门 —— 不在**允许集**里 → 返回拒单理由（在集合里 → 空串）。

    ★ 逐字比较（连大小写 / 连字符都不许含糊）；拒绝必须**零副作用**：不起进程、不建 log、
    不改树。★ `--resume` / `--retry` / `--detach` 全都从 `main()` 过这道闸；续跑必须沿用
    原来那个模型，不许因为「原模型挂了」就换成表外的。
    ★ 允许集 = `effective_allowed_models()`（名单常量 `ALLOWED_MODELS` ∪ 外部开关文件里打开的）
    —— **但不是轮换链**：`next_whitelist_model()` 只看 `MODEL_WHITELIST`。
    """
    allowed = effective_allowed_models()
    if model in allowed:
        return ""
    return (f"未授权模型，已拒绝派活：{model}\n"
            f"  允许集（名单常量 MODEL_WHITELIST / ONE_OFF_MODELS + 外部开关文件"
            f"(infra/pool/model-switches.toml) 里打开的；只有用户能改）：{'、'.join(allowed)}\n"
            "  默认拒绝：既不在名单、也没在开关文件里打开的模型一律调不动"
            "（用户 2026-09-26 令：黑名单锁死）。")


def next_whitelist_model(model: str) -> str | None:
    """按清单顺序取下一个（429 三拍「按序换」用）；已经是最后一个 → None（全挂就停）。"""
    try:
        idx = MODEL_WHITELIST.index(model)
    except ValueError:
        return None
    return MODEL_WHITELIST[idx + 1] if idx + 1 < len(MODEL_WHITELIST) else None


def git_dirty(cwd: Path | None = None) -> list[str]:
    """被跟踪文件里有没有未提交改动（未跟踪文件不算：那两个是别的窗口放的）。

    ★ 卡 103（T-G199）：多了 `cwd` —— 脏检查要看**工人要干活的那棵树**，不是永远看主仓。
    不给（默认 `None` = 主仓）时行为逐字不变（既有调用与用例一条不动地全过）。
    """
    done = subprocess.run(
        ["git", "status", "--porcelain", "-uno"],
        cwd=str(cwd or ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
        **NO_WINDOW,
    )
    return [ln for ln in (done.stdout or "").splitlines() if ln.strip()]


def is_git_worktree(path: Path) -> bool:
    """`path` 是不是一个 git 工作树（卡 103）—— 不是就**当场说**，不许静默当干净。

    判据用 `git -C <path> rev-parse --is-inside-work-tree`（比看 `.git` 是文件还是目录稳：
    链接工作树（`git worktree add`）里 `.git` 只是**文件**，不是目录）。路径不存在 / 跑不了
    git / 回话不是 `true` → 一律 False。
    """
    if not path.is_dir():
        return False
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(path), capture_output=True, text=True, encoding="utf-8",
            errors="replace", **NO_WINDOW,
        )
    except OSError:
        return False
    return done.returncode == 0 and (done.stdout or "").strip() == "true"


def auth_ok(node: Path, cli: Path, timeout: int = 180) -> tuple[bool, str]:
    """真发一条极短请求 —— 登录没通就当场认出来（别把一轮白等当成"工人在想"）。"""
    done = subprocess.run(
        [str(node), str(cli), "-p", "只回复四个字：连接成功", "--output-format", "text",
         "--no-session-persistence", "-y"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout, **NO_WINDOW,
    )
    body = f"{done.stdout or ''}\n{done.stderr or ''}"
    if AUTH_NEEDLE in body:
        return False, "登录没通（Authentication required）→ 先在 TUI 里敲 /login（T-G80）"
    if "连接成功" in body:
        return True, "登录自检通过"
    return False, f"自检没拿到预期回话（退出码 {done.returncode}）：{wb_status._clip(body, 200)}"


def prompt_path(p: str, worker_cwd: Path | None) -> str:
    """★ T-G204：给了 `--cwd` 就把路径转成**绝对**（不给时**逐字不变**）。

    为什么：`--cwd` 让**工人进程的 cwd** 变成卡树，而切片与规格是**仓库相对**路径
    （`gates/diag/…` 只存在于主仓）⇒ 相对写法会把工人指到一个**不存在的路径**上，
    它只能自己满盘找（卡 106 的工人就是这么找到的 —— 那是运气，不是设计）。
    """
    if not p or worker_cwd is None:
        return p
    q = Path(p)
    return str(q if q.is_absolute() else (ROOT / q).resolve())


def build_command(node: Path, cli: Path, card: str, spec: str, model: str,
                  permission_mode: str = DEFAULT_PERMISSION_MODE, *,
                  max_turns: int = DEFAULT_MAX_TURNS_WRITE,
                  autocompact: str = DEFAULT_AUTOCOMPACT,
                  lean: bool = False, brief: str = "") -> list[str]:
    prompt = (LEAN_OPENING.format(brief=brief, spec=spec, card=card) if lean
              else OPENING.format(spec=spec, card=card))
    return [
        str(node), str(cli), "-p", prompt,
        "--model", model, "--output-format", "stream-json",
        "--permission-mode", permission_mode,
        # ① 回合上限：撞到了 CLI 会自己停（退出码仍是 0，所以跑完还要判"没做完"）
        "--max-turns", str(max_turns),
        # 用户 2026-09-26 定：上下文窗口按 1M 自动压缩（`--effort` 不加 = 保持默认 High）
        "--autocompact", autocompact,
        # ★ 八条铁律进**系统提示**（T-G90）：不再只靠开场白那句（压缩之后它就很远了）
        "--append-system-prompt", IRON_RULES,
        # ★ 不再传 `--no-session-persistence`（T-G90）：会话要留着，才能 `--resume` 续跑
        "-y",
    ]


def resume_command(node: Path, cli: Path, session_id: str, prompt: str, model: str,
                   permission_mode: str = DEFAULT_PERMISSION_MODE, *,
                   max_turns: int = DEFAULT_MAX_TURNS_WRITE,
                   autocompact: str = DEFAULT_AUTOCOMPACT) -> list[str]:
    """带着**同一个会话**接着跑（`--resume <sessionId>`）—— 中断不等于白干。

    实测（T-G90 探针）：首轮 `-p 「请记住一个数字：42」` → 回「记下了」；
    `--resume <同一个 id>` 再问「我刚才让你记的数字是多少」→ 回 **42**，且 session_id 没变。
    """
    return [
        str(node), str(cli), "--resume", session_id, "-p", prompt,
        "--model", model, "--output-format", "stream-json",
        "--permission-mode", permission_mode,
        "--max-turns", str(max_turns),
        "--autocompact", autocompact,
        "--append-system-prompt", IRON_RULES,
        "-y",
    ]


def session_file_for(log: Path) -> Path:
    """会话 id 落在哪里 —— 中断之后 `--resume auto` 就从这儿读。"""
    return log.with_suffix(".session.txt")


def spec_file_for(log: Path) -> Path:
    """规格指纹落哪里（卡 029 §2.7）：`wb-<卡>.jsonl` → `wb-<卡>.spec.txt`。"""
    return log.with_suffix(".spec.txt")


def spec_fingerprint(spec: str) -> str:
    """卡规格的 sha256 —— 每次真开跑记一份；续跑时指纹变了 = 规格改过，必须硬塞「先读规格」。"""
    return hashlib.sha256((ROOT / spec).read_bytes()).hexdigest()


def read_spec_note(log: Path) -> str:
    """读已落的规格指纹（没有 → 空串）。"""
    note = spec_file_for(log)
    try:
        return note.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def spec_changed_notice(spec: str, log: Path) -> str:
    """续跑前核对规格指纹（卡 029 §2.7）—— 返回要**塞进续跑提示词最前面**的那段话（没变 → 空串）。

    ★ 边界：没有 `wb-<卡>.spec.txt` 的老卡**放行**并提示「无指纹，按老规矩」（不拒单）；
    ★ 不许自动新开会话（那会偷偷烧钱）—— 只加告警 + 提示词硬要求。
    ★ 为什么这么较真（§20.3 真撞过）：工人收到了新指令却没读新规格，白跑两轮 —— 而
    「提示词原文不写进日志」，核对它读没读只能靠这个指纹 + 让它在回报里写出新小节标题。
    """
    digest = spec_fingerprint(spec)
    stored = read_spec_note(log)
    if stored and digest in stored:
        return ""
    if not stored:
        print("[指纹] 无规格指纹记录（老卡）→ 按老规矩放行；本轮开跑补记", flush=True)
        return ""
    old_tail = stored.splitlines()[-1][:24]
    print(f"[指纹] ★★ 规格已变（{spec}）→ 本轮续跑必须重读规格"
          f"（旧指纹 {old_tail}… → 现在 {digest[:24]}…）", flush=True)
    return (f"★★ 规格文件已更新：先用 Read 打开 `{spec}`，"
            "在回报里写出新小节（如 §2.10）的标题，再动手。\n")


def session_id_seen(lines: list[str]) -> str:
    """从事件里取 `session_id`（取最后一个）—— 存下来，中断了才续得上。"""
    sid = ""
    for raw in lines:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("session_id"):
            sid = str(event["session_id"])
    return sid


def continuation_prompt(*, reason: str, scene: str, card: str) -> str:
    """续跑时对工人说的话：说明为什么断的 + **别重做** + 把中断现场给它。"""
    return (
        f"上一轮你被中断了（{reason}）。现在接着干**同一张卡**（卡号 {card}）："
        "先看 git status 与工作区里已有的改动，判断哪些**已经做完** —— ★ 不要重做已完成的部分；"
        "卡规格与八条铁律都不变。干完按卡的回报格式回报。"
        f"\n上一次中断时的现场（最后几步）：\n{scene}"
    )


def should_resume(reason: str, attempts_done: int, retries: int) -> bool:
    """该不该带着同一会话续跑。

    ★ 只对「被打断」续跑（卡死 / 超时 / 没跑完），**不对「空转」续跑**：空转是在原地打转，
    续跑只会让它接着转 —— 那正是看门狗要掐掉的东西。没拿到会话 id 时也续不了（调用方判）。
    """
    if not reason or attempts_done > retries:
        return False
    return not reason.startswith("空转")


# ================================================================ 长跑：活过我的窗口（T-G91）


def heartbeat_file_for(log: Path) -> Path:
    """心跳落成**文件**（不只打在 stdout 上）—— 过夜跑时"它还在不在动"读一个文件就知道。"""
    return log.with_suffix(".heartbeat.txt")


def verdict_file_for(log: Path) -> Path:
    """这一轮的判决落盘（退出码 / 原因 / 会话 / 几次尝试）—— 新窗口先读它，别的都不用猜。"""
    return log.with_suffix(".verdict.txt")


def report_file_for(log: Path) -> Path:
    """这一轮的**交接摘要**落哪 —— 按 log 名派生，重试轮各落一份、互不覆盖（T-G95）。

    `wb-005.jsonl` → `wb-005.report.md`；`wb-005.r2.jsonl` → `wb-005.r2.report.md`。
    """
    return log.with_suffix(".report.md")


def write_heartbeat(log: Path, line: str) -> None:
    """心跳落盘（带时间戳，一行覆盖一行）：读的人只关心"它最后一次动是什么时候"。"""
    heartbeat_file_for(log).write_text(
        f"{datetime.now().isoformat(timespec='seconds')} {line}\n", encoding="utf-8")


def detached_argv(argv: list[str]) -> list[str]:
    """给"脱离窗口"的子进程用：`python -X utf8 <脚本> <原参数> --no-preflight --detach-done`。

    为什么要这个标记：子进程再 detach 一次就会无限生小进程 —— 它是**内部**开关，不该给人用。
    ★ 为什么补 `--no-preflight`（T-G92）：父进程**已经**做过四道前置检查了（其中登录自检是真发一条
    CLI 请求，十几秒），子进程再查一遍纯属浪费；输入里已有的也要去掉，只留**恰好一个**。
    ★ 为什么必须带**脚本自己**（T-G92 真机证据 (b) 逮到的第二个洞）：旧写法是
    `[python, -X, utf8, *args]` —— 少了脚本路径，子进程其实是 `python --card 900 …`，
    python 把 `--card` 当成**自己的**选项 → `Unknown option: --card`，**从来没真扔出去过**。
    ★ 为什么带 `-u`（T-G95）：`print` 在**非 TTY**（后台 job / `--detach`）下是**块缓冲**的 ——
    实测 `--detach` 之后 `wb-005.dispatch.log` 是 **0 字节**，主控看日志以为它没起来（同一个坑
    撞了三次）。给解释器加 `-u` 让子进程无缓冲；输入里已有的 `-u` 也去掉，只留**恰好一个**。
    """
    return [sys.executable, "-X", "utf8", "-u", str(Path(__file__).resolve()),
            *[a for a in argv if a not in ("--detach", "--no-preflight", "-u")],
            "--no-preflight", "--detach-done"]


def spawn_detached(argv: list[str], log_path: Path) -> int:
    """把派活**扔出去单独跑**（我的窗口关了它照样跑）：返回子进程 pid，输出落到 `log_path`。

    Windows 用 `DETACHED_PROCESS`（没有控制台，不随父进程退出）；别的平台用 `start_new_session`。
    ★ T-G96：Windows 上再叠一个 `CREATE_NO_WINDOW` —— 用户 2026-09-26 看到任务栏里留着一个
    **空窗口**（标题是那个 node.exe），Windows 11 把控制台程序转交给默认终端宿主就会这样。
    ★ 边界：这两个 flag **不冲突**（`DETACHED_PROCESS` 已经不要控制台；`CREATE_NO_WINDOW` 让
    宿主别再弹）—— 但「脱离窗口后照样活过父进程」是 `--detach` 的命根子，改完必须**真机验一次**。
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict = ({"creationflags": subprocess.DETACHED_PROCESS
                     | subprocess.CREATE_NEW_PROCESS_GROUP
                     | subprocess.CREATE_NO_WINDOW} if os.name == "nt"
                    else {"start_new_session": True})
    with log_path.open("w", encoding="utf-8") as out:
        proc = subprocess.Popen(                      # noqa: S603 —— 命令是本地拼好的，不是外部输入
            list(argv), cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=out,
            stderr=subprocess.STDOUT, **kwargs,
        )
    return proc.pid


# ★ 卡 109（T-G206）：`card_artifacts()` 的**唯一实现**在 `pool.jobs`（见顶部 import）——
#   原先这里的副本已删。别在本地重新长一份：宽 glob `wb-<卡>*` 会**串卡**
#   （`fnmatch("wb-421.jsonl", "wb-42*.jsonl")`），卡 029 §2.9 实测挖出过。


def status_report(card: str) -> str:
    """一张卡现在到哪了 —— **只读文件**（心跳 / 判决 / 会话 / log 尾巴），不碰工人。

    长任务（尤其过夜跑）需要这条：新窗口、或者我半夜里，一条命令就知道"它还在跑吗 / 跑完没有"。
    ★ T-G112（架构 C，主控裁定）：心跳停滞超过阈值且没有判决 → 打**醒目告警**
    （见 `heartbeat_stall_alert`）—— 派活进程被系统杀掉后"没人盯"至少要**看得见**。
    ★ 卡 029 §2.1（C 兜底）：「log 比最新判决新」→ 那份判决描述的不是当前这一轮，打醒目告警。
    ★ 卡 029 §2.6：打出这张卡的 token 用量 + 全部卡的累计用量（只数 token，不做金额换算）。
    """
    diag = ROOT / "gates" / "diag"
    head = diag / f"wb-{card}"
    # 先把 log 读出来：告警判据（`heartbeat_stall_alert`）吃最新一轮的 log 与它的收工证据。
    logs = card_artifacts(diag, card, ".jsonl")
    newest = logs[-1] if logs else None
    lines: list[str] = []
    summary: dict = {}
    alert: list[str] = []
    if newest is not None:
        lines = newest.read_text(encoding="utf-8", errors="replace").splitlines()
        _, summary = wb_status.parse_events(lines)
        # ★ "收工"与面板同一口径：这张 log **自己**的判决文件，或 log 里已有 result 事件。
        #   （判决按轮落，第 1 轮的判决不代表第 2 轮也结束了。）
        finished = (verdict_file_for(newest).exists() or bool(summary["final"]))
        alert = heartbeat_stall_alert(log=newest, finished=finished)
    out: list[str] = [f"=== 卡 {card} 的状态（{head}.*）==="]
    # ★ T-G95：有摘要就先把它指出来 —— 主控**先看它**，不必再翻原始 jsonl。
    reports = card_artifacts(diag, card, ".report.md")
    if reports:
        out.append(f"  [摘要] {reports[-1].relative_to(ROOT).as_posix()}（先看它）")
    # ★ T-G112：心跳**按轮落**（第 2 轮写 `wb-<卡>.r2.heartbeat.txt`）—— 取**最新**一份展示；
    #   旧写法只认第 1 轮那份，续跑时会把"还在跑"读成"心跳停在几点"。
    hbs = card_artifacts(diag, card, ".heartbeat.txt")
    if hbs:
        out.append(f"  [心跳] {hbs[-1].read_text(encoding='utf-8').strip() or '（空）'}")
    elif newest is None:
        # 一个 log 都没有 = 真没派过；有 log 而无心跳时，刚起/真断了由 alert 有证据地判（卡 093）
        out.append("  [心跳] （还没有 —— 要么没派过，要么刚起）")
    out.extend(alert)                        # 醒目告警紧跟心跳 —— 没人盯这事要一眼看见
    # ★ T-G96：判决**按轮落**（`wb-<卡>.verdict.txt` / `wb-<卡>.r2.verdict.txt`…）—— 这里取
    #   **最后一轮**的那一份（按 mtime），别因为按轮落就变成主控读不到。
    verdicts = card_artifacts(diag, card, ".verdict.txt")
    if verdicts:
        newest_verdict = verdicts[-1]
        body = newest_verdict.read_text(encoding="utf-8").strip()
        out.append(f"  [判决] {newest_verdict.name}：{body}")
        # ★ 卡 029 §2.1（C 兜底）：log 比最新判决新 = 判决说的不是当前这一轮（A 的归档是根因修法，
        #   这条防"归档没跑成 / 派活进程半路死了"那类漏网）。
        if newest is not None and newest.stat().st_mtime > newest_verdict.stat().st_mtime:
            out.append("  [★告警] 判决比日志旧 —— 它描述的不是当前这一轮")
    else:
        out.append("  [判决] （还没有 —— 还在跑，或没跑完就断了）")
        # ★ 卡 093：`--detach` 之后主控**收不到完工通知**（今天真发生过：worker 12:36 收工，
        #   主控被用户问才发现）—— 没判决时把"没有回推通道 + 该多久轮询一次"明说出来。
        out.append(f"  [提示] --detach 派活**没有回推通道**（完工不会自动通知主控）—— 请轮询："
                   f"python -X utf8 tools/wb_dispatch.py --card {card} --status"
                   f"（建议每 ~{HEARTBEAT_SECONDS / 60:.0f} 分钟一次；跑挂了再 --resume auto）。")
    sd = session_file_for(head.with_suffix(".jsonl"))
    if sd.exists():
        sid = sd.read_text(encoding="utf-8").strip()
        out.append(f"  [会话] {sid}（续跑：--resume {sid}）")
    usage = usage_summary(card)
    if usage:
        out.append(f"  [用量] {usage}")
    if newest is None:
        out.append("  [log ] （一个都没有）")
        return "\n".join(out)
    out.append(f"  [log ] {newest.name}（{len(lines)} 行 / 共 {len(logs)} 个 log）；"
               f"工具调用 {summary['tool_calls']} 次；碰过文件 {summary['files_total']} 个；"
               f"工具报错 {summary['tool_errors']} 次")
    out.append(f"  [最后] {summary['final'] or '（还没见到 result —— 可能还在跑）'}")
    return "\n".join(out)


# ---------------------------------------------------------------- 进程存活判据（卡 093 · T-G187）
# 为什么按**命令行**查：`node.exe` 满机都是，只按名字下结论 = 铁律 23–28 明令禁止的那件事
# （会把别的 node 当成本卡工人，也会把本卡工人当成"没在跑"）。CodeBuddy worker 的判据是
# **node.exe 且命令行含 codebuddy**（当年主控就是按命令行精确查到 pid 34168 的）。
# ★ 本函数**只查不杀** —— `--status` 是不碰工人的只读通道。


def codebuddy_worker_pids() -> list[tuple[int, str]]:
    """按命令行**精确**列 CodeBuddy worker：`(pid, 命令行)` 列表 —— 只查，不杀。

    枚举不到（非 Windows / PowerShell 不可用 / 读不出）→ 返回 `[]`（意思是"判不出"，
    **不是**"没有进程"）；调用方据此如实措辞，绝不把它读成"工人已死"。
    """
    if os.name != "nt":
        return []
    cmd = ["powershell", "-NoProfile", "-Command",
           "Get-CimInstance Win32_Process | Select-Object ProcessId,CommandLine | "
           "ConvertTo-Json -Compress"]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=20, **NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return []
    if done.returncode != 0 or not (done.stdout or "").strip():
        return []
    try:
        data = json.loads(done.stdout)
    except json.JSONDecodeError:
        return []
    rows = data if isinstance(data, list) else [data]
    found: list[tuple[int, str]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        cl = str(item.get("CommandLine") or "")
        exe = cl.strip().split(" ", 1)[0].strip('"').replace("\\", "/").rsplit("/", 1)[-1].lower()
        if exe != "node.exe" or "codebuddy" not in cl.lower():
            continue                     # ★ 名字 + 命令行**两条都要**，缺一不认（不许只按名字）
        try:
            found.append((int(item.get("ProcessId")), cl))
        except (TypeError, ValueError):
            continue
    return found


def _card_of(log: Path) -> str:
    """从 `wb-<卡>.jsonl` / `wb-<卡>.r2.jsonl` 里取出卡号（取不到 → 空串）。"""
    hit = re.match(r"^wb-(.+?)(?:\.r\d+)?\.jsonl$", log.name)
    return hit.group(1) if hit else ""


def _clock(ts: float) -> str:
    """mtime → `HH:MM:SS`（把判据念给人听用）。"""
    return time.strftime("%H:%M:%S", time.localtime(ts))


def heartbeat_stall_alert(*, log: Path, finished: bool,
                          now: float | None = None) -> list[str]:
    """这张 log 的**心跳/存活**叙述 —— 返回要打进 `--status` 的行（空 = 没话要说）。

    为什么改成"有证据的判断"（卡 093 · T-G187，主控今天亲历）：旧口径只看「心跳文件在不在」，
    于是把**刚起不到一个心跳周期**的正常现场读成了「多半已被杀」的假警报（会让人误判、甚至误重派，
    重派会撞上正在跑的活）。现在每一态都要有证据：

      ① **刚起（正常，不告警）**：还没有心跳文件，且日志 mtime 就在**一个心跳周期内**
         → 说"刚起 N 分钟、心跳每 120s 一行、正常"；
      ② **日志还在长（暂不告警）**：心跳缺失/陈旧，但日志**刚刚还在写** → 派活器可能还在；
      ③ **真断了（★必须告警）**：心跳陈旧（或无心跳文件）**且**日志也不再长（静默 ≥ 阈值）
         → 报出来，并把判据**全部念出来**（心跳最后时间 / 日志最后写时间 / 阈值 / 进程判据）。

    ★ 阈值与看门狗**同一口径**：`STALL_SECONDS` 底线（480 秒 ≈ 心跳间隔 120 秒的 4 个周期）。
    ★ 进程判据按命令行精确查（`codebuddy_worker_pids`），把"多半已被杀"那种**无证据的措辞**
      换成有证据的陈述 —— 不许按进程名判断。
    已收工（这张 log 自己有判决 / 里有 result 事件）→ 不告警：收工后心跳停止是**正常**的。
    ★ 宁可少告警也不让 `--status` 崩：mtime 读不到就退回"不告警"。
    """
    if finished:
        return []
    reference = time.time() if now is None else now
    try:
        hb = heartbeat_file_for(log)
        hb_age: float | None = (max(reference - hb.stat().st_mtime, 0.0)
                                if hb.exists() else None)
        log_mtime = log.stat().st_mtime
        log_age = max(reference - log_mtime, 0.0)
    except OSError:
        return []
    base = float(STALL_SECONDS)          # 告警阈值（与看门狗底线同一口径）
    period = float(HEARTBEAT_SECONDS)    # 一个心跳周期
    if hb_age is not None and hb_age < base:
        return []                        # 心跳还新鲜 = 派活进程活着，没话要说
    hb_said = (f"心跳停滞 {hb_age / 60:.1f} 分钟（最后 {_clock(hb.stat().st_mtime)}）"
               if hb_age is not None
               else "没有心跳文件（--heartbeat-seconds 0，或派活器刚起就死了）")
    # ① 刚起：还没有心跳文件，而日志是在**一个周期内**写的 —— 正常，不告警
    if hb_age is None and log_age < period:
        return [f"  [心跳] 刚起 {log_age / 60:.1f} 分钟（日志最后写 {_clock(log_mtime)}；"
                f"心跳每 {period / 60:.0f} 分钟一行）：还没到第一个心跳周期 —— 正常，不告警"]
    # ② 心跳缺失/陈旧但**日志仍在长** → 派活器可能还在（长任务里心跳偶尔慢一拍），暂不告警
    if log_age < base:
        return [f"  [心跳] {hb_said}、但日志 {log_age / 60:.1f} 分钟前还在写（{_clock(log_mtime)}）"
                " —— 派活器可能还在：暂不告警（继续观察）"]
    # ③ 心跳缺失/陈旧 **且** 日志也不再长 = 真断了 —— 这一态才告警，并把所有判据念出来
    card = _card_of(log)
    procs = codebuddy_worker_pids()
    mine = [pid for pid, cl in procs if f"brief-{card}.md" in cl]
    if mine:
        proof = (f"命令行里查到**本卡** worker 仍在（pid {'/'.join(map(str, mine))}，"
                 "node.exe 且含 codebuddy）→ 别急着重派")
    elif procs:
        proof = (f"命令行里有 {len(procs)} 个 codebuddy worker，但没有本卡的"
                 f"（命令行不含 brief-{card}.md）")
    else:
        proof = "命令行里查不到 codebuddy worker（node.exe 且含 codebuddy）"
    return [
        f"  [★告警] {hb_said}、日志最后写 {_clock(log_mtime)}（静默 {log_age / 60:.1f} 分钟）"
        f"（阈值 {base / 60:.1f} 分钟，与看门狗底线同一口径）且没有判决"
        f" —— {proof}：没人盯了。",
        "  [★告警] 兜底：先 tools/wb_status.py <log> --tail 20 看现场，"
        "再 --resume auto 续跑或重派。",
    ]


# ============================================ 过期判决的根因修法（卡 029 §2.1，原卡 028 裁定 A）

def archive_stale_artifacts(card: str) -> list[str]:
    """**真开跑那一刻**，把这张卡的旧判决 / 摘要**改名归档**（加 `.stale` 后缀）—— 只归档、不删。

    为什么（主控 2026-09-26 真撞到）：一次被前置检查拒绝的派活会留下「前置检查没过 → 没派活」
    的判决；同一张卡随后真跑时它不清掉 → `--status` 半小时里一直显示「没派活」，而工人其实在跑。
    ★ 归档不删：`--force` 才让覆盖那条规矩的精神是**留证据**，归档兼容它、删除不兼容。
    ★ dry-run 不许归档（没真跑）—— 调用点在 `main()` 的 dry-run 返回**之后**。
    ★ 用 `card_artifacts`（精确匹配）—— 别把卡 421 的判决归档到卡 42 头上（§2.9 同源）。
    """
    diag = ROOT / "gates" / "diag"
    moved: list[str] = []
    for suffix in (".verdict.txt", ".report.md"):
        for p in card_artifacts(diag, card, suffix):
            target = p.with_name(p.name + ".stale")
            try:
                p.rename(target)
                moved.append(target.name)
            except OSError:
                continue        # 归档失败不许挡住真跑 —— 如实留在返回里（少了就是没归成）
    return moved


# ============================================ token 用量落账（卡 029 §2.6）

USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_read")


def result_usage(lines: list[str]) -> dict[str, int]:
    """最后一条 `result` 事件里的 `usage` —— 数从 **CLI 自己报的**拿，别自己估；读不到 → 全 0。"""
    usage: dict = {}
    for raw in lines:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") == "result":
            candidate = event.get("usage")
            usage = candidate if isinstance(candidate, dict) else {}
    def num(*keys: str) -> int:
        for key in keys:
            value = usage.get(key)
            if isinstance(value, (int, float)):
                return int(value)
        return 0
    return {field: num(field, *alias) for field, alias in (
        ("input_tokens", ("input_tokens",)),
        ("output_tokens", ("output_tokens",)),
        ("cache_read", ("cache_read_input_tokens", "cache_read")),
    )}


def append_usage_line(*, card: str, model: str, attempt: int, started_at: float | None,
                      usage: dict[str, int], code: int, reason: str) -> Path:
    """每张卡每轮跑完（无论成败）往 `gates/diag/wb-usage.jsonl` 追加一行用量（只数 token，
    **不做金额换算**——用户明说「不用太担心怎么计价」）。该文件在 gitignore 里，不脏树。"""
    path = ROOT / "gates" / "diag" / "wb-usage.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    end = time.time()
    began = end if started_at is None else started_at
    row = {
        "卡": card, "模型": model, "轮次": attempt,
        "开始": _iso_local(began), "结束": _iso_local(end),
        "用时分钟": round(max(end - began, 0.0) / 60, 1),
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "cache_read": usage["cache_read"],
        "退出码": code, "判决": reason or "正常收工",
    }
    with path.open("a", encoding="utf-8") as out:
        out.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def usage_summary(card: str) -> str:
    """`--status` 的用量一行：这张卡的 + 全部卡的累计（读不出来 / 没记录 → 空串，不显示）。"""
    path = ROOT / "gates" / "diag" / "wb-usage.jsonl"
    try:
        rows = [json.loads(ln) for ln in
                path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    except (OSError, json.JSONDecodeError):
        return ""
    rows = [r for r in rows if isinstance(r, dict)]
    mine = [r for r in rows if r.get("卡") == card]
    if not mine:
        return ""
    def total(items: list[dict], field: str) -> int:
        return sum(int(r.get(field) or 0) for r in items)
    parts = [f"本卡 {len(mine)} 轮：input {total(mine, 'input_tokens'):,} / "
             f"output {total(mine, 'output_tokens'):,} / cache_read {total(mine, 'cache_read'):,}",
             f"累计（所有卡）：input {total(rows, 'input_tokens'):,} / "
             f"output {total(rows, 'output_tokens'):,} / cache_read {total(rows, 'cache_read'):,}"]
    return " ｜ ".join(parts)


# ============================================ 429 / 额度三拍（卡 029 §2.5）：等 → 按序换 → 全挂就停

def quota_error(lines: list[str]) -> dict | None:
    """从 `result` 事件认 429 / 额度错误 —— 返回 `{kind, reset, why}`；不是额度问题 → None。

    ★ 429 长得像成功（`subtype=error_during_execution` + 空回话 + **退出码 0**）—— 不许只看
    退出码。★ 卡 045（T-G136）加两道闸（R029 成功收工却被回话里的「429」续跑 3 轮，真撞过）：
    ① **候选闸门**：只有 `subtype == "error_during_execution"` / `is_error` 为真 /
       回话是空的，这三种 `result` 事件才允许进入额度判定 —— **正常成功（有非空回话）
       的一律不算额度错**，这是硬闸门；
    ② **结构化字段优先**：`errors` / `errors_info` 用状态 needle（429/6004/quota）与完整
       中文短语匹配；**回话正文只允许完整中文短语**（「额度已用尽」等）—— 裸「429」/
       「quota」/「6004」不许再扫正文（卡 029 自己的提交信息就写着「429 三拍」，
       任何 `git log` 都会中招 → 自毒）。
    ★ 两种**分开记**：限流（带「将在 <时间> 重置」）vs 余额耗尽（没有重置时间）。
    ★ `why`：命中了哪个 needle、在哪个字段里 —— 下次再误判，一眼看出是谁骗了它。
    """
    for raw in lines:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not (isinstance(event, dict) and event.get("type") == "result"):
            continue
        words = event.get("result")
        words = words if isinstance(words, str) else ""
        # ★★ 候选闸门（卡 045 §2.1）：正常成功 + 非空回话 → 一律不算额度错。
        candidate = (event.get("subtype") == "error_during_execution"
                     or bool(event.get("is_error"))
                     or not words.strip())
        if not candidate:
            continue
        structured = json.dumps({key: event.get(key) for key in ("errors", "errors_info")},
                                ensure_ascii=False, default=str)
        hit_field, hit_needle = "", ""
        for field, blob, needles in (
                ("errors", structured, QUOTA_STATUS_NEEDLES + QUOTA_TEXT_NEEDLES),
                ("result", words, QUOTA_TEXT_NEEDLES)):
            for needle in needles:
                if needle in blob:
                    hit_field, hit_needle = field, needle
                    break
            if hit_field:
                break
        if not hit_field:
            continue
        hit = re.search(r"将在\s*([^\n」\"']+?)\s*重置", structured + "\n" + words)
        return {"kind": "限流" if hit else "余额耗尽", "reset": hit.group(1) if hit else "",
                "why": f"字段 {hit_field} 命中「{hit_needle}」"}
    return None


def round_is_normal_success(lines: list[str]) -> bool:
    """这一轮的 `result` 是不是「正常成功且有非空回话」（卡 045 §2.4 探针优先的判据）。"""
    for raw in reversed(lines):
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not (isinstance(event, dict) and event.get("type") == "result"):
            continue
        words = event.get("result")
        return (event.get("subtype") != "error_during_execution"
                and not event.get("is_error")
                and isinstance(words, str) and words.strip() != "")
    return False


def quota_probe_ok(node: Path, cli: Path, model: str, timeout: int = 120) -> tuple[bool, str]:
    """极小代价的可用性探测（429 三拍的第 ② 拍）—— ★ 别把整卡重跑当探测。"""
    try:
        done = subprocess.run(
            [str(node), str(cli), "-p", "只回复四个字：连接成功", "--model", model,
             "--output-format", "text", "--no-session-persistence", "-y"],
            cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, **NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"探测跑不起来：{exc}"
    body = f"{done.stdout or ''}\n{done.stderr or ''}"
    if AUTH_NEEDLE in body:
        return False, "登录没通（Authentication required）"
    for needle in QUOTA_TEXT_NEEDLES:
        if needle in body:
            return False, f"额度仍挂（{needle}）"
    if "连接成功" in body:
        return True, "探测通过"
    return False, f"探测没拿到预期回话（退出码 {done.returncode}）：{wb_status._clip(body, 120)}"


# ============================================ 交接摘要（T-G95 = 外包卡 006）
#
# 为什么有它（主控写的背景）：主控每收一张卡，最贵的开销不是复核（`wb_review.py` 5 秒的事），
# 而是**读工人那一轮的原始事件流**（卡 005 那轮是 264 行 / 316 KB），而他要的东西（六项回报 /
# 判决 / 计数）只压在末尾。所以派活器**自己**在收工时落一份 1~2 KB 的摘要 —— 主控只读它。
# ★ 口径复用现成的，**不写第二份**：回合走 `turns_seen()`、工具签名走 `tool_signatures()`、
# log 摘要走 `wb_status.parse_events()`（它已经算了工具调用 / 文件 / 报错）。


def result_event_text(lines: list[str]) -> str | None:
    """`result` 事件里 `result` 字段的**原文**（整段 log 里没有 `result` 事件 → `None`）。

    ★ 与 `finish_verdict()` 分工不同：那条判「跑完没有」；这条要**原样搬运**工人的回话（主控读的
    就是它），所以不能借用 `parse_events()` 里那份**截断过**的 `final`。
    """
    found: str | None = None
    for raw in lines:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") == "result":
            found = str(event.get("result") or "")
    return found


def _iso_local(ts: float | None) -> str:
    """epoch 秒 → 本地 ISO（秒级）；没有 / 解不开 → 用"现在"（报告不许因为时间戳炸）。"""
    if ts is None:
        return datetime.now().isoformat(timespec="seconds")
    try:
        return datetime.fromtimestamp(ts).isoformat(timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return datetime.now().isoformat(timespec="seconds")


def _last_tool_lines(lines: list[str], limit: int = 10) -> list[str]:
    """最后 `limit` 次工具调用压成 `序号. 工具名 参数前 120 字符`（复用 `tool_signatures()`）。"""
    out: list[str] = []
    for idx, sig in enumerate(tool_signatures(lines)[-limit:], 1):
        name, _, blob = sig.partition("|")
        out.append(f"{idx}. {name} {wb_status._clip(blob, 120)}")
    return out


def _uncommitted_count() -> str:
    """`git status --porcelain` 的未提交文件数（机械读数 —— 让主控一眼看出工人动没动工作区）。"""
    try:
        done = subprocess.run(["git", "-c", "core.quotepath=false", "status", "--porcelain"],
                              cwd=str(ROOT), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", **NO_WINDOW)
    except OSError as exc:
        return f"（跑不了 git：{exc}）"
    return str(len([ln for ln in (done.stdout or "").splitlines() if ln.strip()]))


def _gates_summary() -> str:
    """`gates/last.json` 的 `ok` / `rev`（读不出来就如实说）。"""
    try:
        data = json.loads((ROOT / "gates" / "last.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "（没有 gates/last.json 或读不出来）"
    return f"ok={data.get('ok')} rev={data.get('rev')}"


def write_report(log: Path, *, card: str, code: int, reason: str, scene: str, sid: str,
                 attempts: int, lines: list[str], started_at: float | None) -> Path:
    """把这一轮压成一份 1~2 KB 的**交接摘要** → `gates/diag/wb-<卡>.report.md`（T-G95）。

    ★ **每一条退出路径都调它**（收工 / 被掐 / 超时 / 撞上限 / 重试的每一轮）；文件按 log 名派生，
    所以重试轮是 `wb-<卡>.r2.report.md`（**不覆写**上一轮 —— 证据不互相盖）。
    ★ 半截 log / 缺字段一律退回「没有数据」，**绝不抛异常** —— 报告是"事故现场"，它自己炸了就最坏。
    """
    _, summary = wb_status.parse_events(lines)
    text = result_event_text(lines)
    if text is None:
        said = "整段 log 里没有 result 事件（被打断 / 被杀 / 还在跑）"
    else:
        said = text or "（`result` 事件里的回话是空的）"
    tools = _last_tool_lines(lines) or ["（一次工具调用都没有）"]
    try:
        size_kb = log.stat().st_size / 1024
    except OSError:
        size_kb = 0.0
    end = time.time()
    began = end if started_at is None else started_at
    minutes = max(end - began, 0.0) / 60
    detail = [ln for ln in scene.splitlines() if ln.strip()] if scene else []
    parts = [
        f"# 卡 {card} 的交接摘要",
        f"- 尝试：第 {attempts} 次   退出码：{code}   判决：{reason or '正常收工'}",
        (f"- 会话：{sid}（续跑：--resume {sid}）" if sid else "- 会话：（还没拿到 session id）"),
        f"- 开始 / 结束：{_iso_local(began)} / {_iso_local(end)}   用时：{minutes:.1f} 分钟",
        (f"- 回合 {turns_seen(lines)} | 工具调用 {summary['tool_calls']} 次 | "
         f"碰过文件 {summary['files_total']} 个 | 工具报错 {summary['tool_errors']} 次"),
        f"- log：{log.name}（{len([ln for ln in lines if ln.strip()])} 行 / {size_kb:.1f} KB）",
    ]
    if detail:                                   # 被掐 / 超时时才有现场，别让收工的报告白占地方
        parts += ["", "## 现场（被掐 / 超时 / 撞上限时的最后几步）", *detail]
    parts += [
        "",
        "## 工人的回话（`result` 事件原文）",
        said,
        "",
        "## 最后 10 次工具调用",
        *tools,
        "",
        "## 主控下一步（机械读数，不是判断）",
        ("- `git -c core.quotepath=false status --porcelain` 的未提交文件数："
         f"{_uncommitted_count()}"),
        f"- `gates/last.json`：{_gates_summary()}",
        "- 建议复核命令（把 `<白名单>` 换成卡 §3 列的那些）："
        "python -X utf8 tools/wb_review.py --rev HEAD --allow \"<白名单>\"",
    ]
    out = report_file_for(log)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return out


# ============================================ 每轮判决（T-G96 = 外包卡 007）
#
# 为什么有它：复核卡 `R-1969b46` 跑了**两轮** —— 第 1 轮 CLI 中途死了（221 行、没有 `result`
# 事件），第 2 轮才正常收工。安全网生效了，但**事后查不出第 1 轮为什么断**：判决文件只有一份、
# 写的是第 2 轮的，第 1 轮的判决被覆写；`.stderr.txt` 是 0 字节；log 里也没留退出码 / 末事件类型。
# 所以：判决**按轮落、不互相覆写**（与每轮一个 log / 一份摘要同一口径），并且每轮记下断流线索。


def _last_event_type(lines: list[str]) -> str:
    """整段 log 里**最后一个能解析成 dict 的事件**的 `type`（读不出 → 一句人话）。"""
    found = ""
    for raw in lines:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            found = str(event.get("type") or "（没有 type）")
    return found or "（没有可解析的事件）"


def _stderr_tail(errlog: Path, limit: int = 5) -> list[str]:
    """`stderr` 的最后 `limit` 行（断流时最要紧的线索之一）；读不出来 / 空 → 一句人话。"""
    try:
        text = errlog.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ["（读不到 stderr）"]
    tail = [ln for ln in text.splitlines() if ln.strip()][-limit:]
    return tail or ["（stderr 是空的）"]


def write_verdict(log: Path, *, card: str, attempts: int, code: int, reason: str, sid: str,
                  lines: list[str], errlog: Path) -> Path:
    """这一轮的判决落盘 —— **按轮落、不互相覆写**（T-G96）。

    `wb-<卡>.jsonl` → `wb-<卡>.verdict.txt`；`wb-<卡>.r2.jsonl` → `wb-<卡>.r2.verdict.txt`。
    ★ 每轮要能查到**断在哪**：退出码 / 有没有 `result` 事件 / 末事件类型 / log 行数 / stderr 5 行。
    """
    has_result = "有" if result_event_text(lines) is not None else "没有"
    diag = [
        f"  退出码={code}；有 result 事件={has_result}；"
        f"末事件类型={_last_event_type(lines)}；"
        f"log 行数={len([ln for ln in lines if ln.strip()])}",
        "  stderr 末 5 行：",
        *[f"    {ln}" for ln in _stderr_tail(errlog)],
    ]
    out = verdict_file_for(log)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        f"card={card} 第={attempts} 次 退出码={code} "
        f"会话={sid or '（无）'} 结束于={datetime.now().isoformat(timespec='seconds')}\n"
        f"判决：{reason or '正常收工（工人退出码 0）'}\n"
        "诊断（这一轮断在哪）：\n" + "\n".join(diag) + "\n"
        f"看细节：python -X utf8 tools/wb_status.py {log} --tail 20 --repo\n",
        encoding="utf-8")
    return out


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


def stall_threshold_seconds(*, stall_seconds: int, inflight: tuple[str, float] | None,
                            durations: list[float]) -> float:
    """这一次判卡死用哪个阈值 —— 两种放宽**只叠加放宽、不收紧**（T-G94）。

    ① **有工具在飞** → 静默是**预期**的 → 底线上抬到 `BUSY_STALL_SECONDS`（30 分钟）；
    ② **按实测自适应** → `TOOL_DURATION_FACTOR × 最近 REPEAT_WINDOW 次**已完成**调用里的最长`
       （取**最长**而不是平均、乘 2.5 是留余量：口径是宁可晚掐、不要误杀）。
    ★ **滑动窗口**（T-G128，裁定 V2）：只看最近 `REPEAT_WINDOW`(12) 次已完成调用 ——
      长调用**掉出窗口就衰减**，修掉「一轮内不衰减」的漏杀（规矩 §15）；
      窗口内最长 ≠ 全量历史最长，别把两者混回来（突变检验钉着）。
    两样都没有 → 就是 `stall_seconds`（老口径，一个字没变）。
    ★ 自适应的那一项**封顶** `ADAPTIVE_MAX_SECONDS`（T-G96）：`min(max(base, 2.5 × longest), 3600)`
    —— 不然一次 60 分钟的调用会把阈值抬到 150 分钟（复核 1969b46 §3 的「漏杀」风险）。
    封顶 3600 > `BUSY_STALL_SECONDS` 1800，所以在飞那条**不会被压下去**。
    """
    base = float(stall_seconds)
    if inflight:
        base = max(base, float(BUSY_STALL_SECONDS))
    window_durations = durations[-REPEAT_WINDOW:]   # ★ T-G128 滑窗：长调用掉出窗口就衰减
    longest = max(window_durations) if window_durations else 0.0
    return min(max(base, TOOL_DURATION_FACTOR * longest), float(ADAPTIVE_MAX_SECONDS))


def _stall_report(*, silent_seconds: float, threshold: float,
                  inflight: tuple[str, float] | None, durations: list[float]) -> str:
    """卡死报告 —— ★ **必须带现场**（T-G94）：最后一次调用是什么 / 已跑多久 / 历史最长一次 /
    这一次用的阈值。旧报告只说「X 分钟没有新事件」，主控拿到现场还得自己翻 log 去猜它当时在跑什么。
    """
    longest = max(durations) if durations else 0.0
    if inflight:
        sig, ran = inflight
        what = f"在跑 {wb_status._clip(sig, 100)}（已跑 {ran / 60:.1f} 分钟）"
    else:
        what = "没有在飞的调用"
    seen = f"历史最长一次调用 {longest / 60:.1f} 分钟" if longest else "历史最长一次调用：没有记录"
    return (f"卡死：{silent_seconds / 60:.1f} 分钟没有新事件"
            f"（这一次的阈值 {threshold / 60:.1f} 分钟；{what}；{seen}）")


def _epoch(raw: object) -> float | None:
    """把事件的 `__timestamp`（ISO-8601 UTC，**两个下划线**）解成 epoch 秒；解不开 → `None`。

    ★ 主控第一次就读错了键（读成 `timestamp`），得到"没有时间戳"的错误结论 —— 这里只认
    `__timestamp`，别的键一律当没有（宁可退回保守行为，不猜）。
    ★ 卡 029 §2.3（盘点 A20）加固：四种形状行为**确定**且**绝不抛异常** ——
      ① 带 `Z` 的串 → 把 `Z` 换成 `+00:00` 再解（旧解释器 3.10 不认 `Z`；3.11+ 两者都行）；
      ② 朴素串（naive，没带时区）→ **退回 `None`**（保守：当作没有时间戳 —— 宁可早掐一次，
         不因为猜错时区把卡死判成健康；旧行为是按 UTC 猜，已改）；
      ③ 非法串 → `None`（不抛）；
      ④ 缺字段 / 非字符串 / 空串 → `None`。
    跨版本验证见 复盘/派活器三合一-T-G114.md §时间戳（本机 CPython 3.14 与 3.12 双跑）。
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        stamp = datetime.fromisoformat(text)
    except (ValueError, TypeError, OverflowError, OSError):
        return None
    if stamp.tzinfo is None:                 # 朴素时间 → 保守退回「没有时间戳」（不猜时区）
        return None
    return stamp.timestamp()


def _tool_use_blocks(lines: list[str]):
    """按出现顺序产出 `assistant` 事件里的每一次 `tool_use`：(id, 名字, 参数, `__timestamp` 秒)。

    ★ 与 `tool_signatures()`（空转判据用）分开写、**不去改它** —— 那条判据一个字都不许动。
    ★ T-G96：`message` **不是 dict** 时（畸形 log）当没有 `content` —— 复核 1969b46 §3.2 里
    `message` 是 str/int 会让 `.get` 抛 `AttributeError`，异常逃出 `run_worker` 的轮询循环 →
    看门狗失效。既有的守卫（`content` 不是 list / `item` 不是 dict / `input` 不是 dict）保持。
    """
    for raw in lines:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "assistant":
            continue
        stamp = _epoch(event.get("__timestamp"))
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        for item in content if isinstance(content, list) else []:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                yield (str(item.get("id") or ""), str(item.get("name") or "?"),
                       item.get("input") or {}, stamp)


def _tool_result_blocks(lines: list[str]):
    """按出现顺序产出 `user` 事件里的每一条 `tool_result`：(tool_use_id, `__timestamp` 秒)。

    ★ T-G96：与 `_tool_use_blocks` 同样对 `message` 做类型判断（畸形 log 不许让看门狗炸）。
    """
    for raw in lines:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "user":
            continue
        stamp = _epoch(event.get("__timestamp"))
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        for item in content if isinstance(content, list) else []:
            if isinstance(item, dict) and item.get("type") == "tool_result":
                yield str(item.get("tool_use_id") or ""), stamp


def inflight_tool(lines: list[str], *, now: float | None = None) -> tuple[str, float] | None:
    """识别「正在跑的工具调用」—— 返回 `(工具签名, 已跑秒数)`；没有在飞的 → `None`。

    判据（T-G94，主控已在真 log 上验过形状）：`assistant` 的 `tool_use` 块与 `user` 的
    `tool_result` 块**一一配对**（`id` ↔ `tool_use_id`）；**没配对的**就是正在跑的。
    多个在飞（并行工具调用）→ 取**跑得最久**的那一次（最该被看见）。
    ★ 保守口径：调用没带 `__timestamp`（半截 log / 对方改格式）→ 算不出耗时 → 返回 `None`
    （**不放大阈值**），也绝不抛异常 —— 宁可早掐一次，不因为读不到时间戳把卡死判成健康。
    """
    finished = {rid for rid, _stamp in _tool_result_blocks(lines) if rid}
    reference = time.time() if now is None else now
    best: tuple[str, float] | None = None
    for tid, name, payload, stamp in _tool_use_blocks(lines):
        if tid and tid in finished:
            continue
        if stamp is None:
            continue
        ran = max(reference - stamp, 0.0)
        sig = wb_status._tool_line(name, payload if isinstance(payload, dict) else {})
        if best is None or ran > best[1]:
            best = (sig, ran)
    return best


def tool_durations(lines: list[str]) -> list[float]:
    """每一次**已完成**工具调用的耗时（秒）—— 用 `__timestamp` 把 `tool_use`/`tool_result` 配对算。

    用来把"这活儿能跑多久"变成**实测**而不是猜（自适应阈值就吃它）。
    ★ 缺 `__timestamp` / 解不开 / 时间倒流 → **跳过那一条**（不抛异常、不拿它去放大阈值）。
    """
    starts: dict[str, float] = {}
    for tid, _name, _payload, stamp in _tool_use_blocks(lines):
        if tid and stamp is not None:
            starts[tid] = stamp
    out: list[float] = []
    for rid, stamp in _tool_result_blocks(lines):
        start = starts.get(rid)
        if start is None or stamp is None:
            continue
        ran = stamp - start
        if ran >= 0:
            out.append(ran)
    return out


def watchdog_verdict(*, silent_seconds: float, signatures: list[str],
                     stall_seconds: int = STALL_SECONDS, window: int = REPEAT_WINDOW,
                     need: int = REPEAT_NEED, lines: list[str] | None = None) -> str:
    """**在跑的时候**该不该把它掐了 —— 返回原因（空串 = 健康）。① 卡死 ② 空转。

    ★ 判卡死的阈值**不是常数**（T-G94）：日志静默 ≠ 卡死 —— 一次工具调用期间**本来就静默**
    （全量门禁 ~4 分钟、冷缓存 worktree 里十几分钟），旧写法会把这种正常的长调用误判成卡死。
    所以给了 `lines` 就按现场放宽（在飞 → 30 分钟底线；再按历史最长一次调用 × 2.5 自适应）；
    **不给 `lines`** = 老口径（阈值就是 `stall_seconds`）—— 空转那条判据一个字没动。
    """
    inflight = inflight_tool(lines) if lines is not None else None
    durations = tool_durations(lines) if lines is not None else []
    threshold = stall_threshold_seconds(stall_seconds=stall_seconds, inflight=inflight,
                                        durations=durations)
    if silent_seconds >= threshold:
        return _stall_report(silent_seconds=silent_seconds, threshold=threshold,
                             inflight=inflight, durations=durations)
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
                   silent_seconds: float, inflight: str | None = None) -> str:
    """心跳一行 —— 让"它还在动"变成看得见的事实（而不是主控干等）。

    ★ T-G94：静默很可能是「正在跑一次长工具调用」，所以在末尾**追加**「在跑 <工具>」
    （有帮助）—— 现有字段**一个都不删**（它们已经在被读、被断言）。
    """
    line = (f"[心跳] 已跑 {elapsed / 60:.1f} 分钟 | 回合 {turns} | 工具 {tool_calls} 次 | "
            f"碰过文件 {files} 个 | 日志静默 {silent_seconds:.0f} 秒")
    if inflight:
        line += f" | 在跑 {wb_status._clip(inflight, 80)}"
    return line


def kill_tree(pid: int) -> str:
    """掐掉**整棵进程树**（按 PID，不按进程名 —— 按名字会误伤同名的别的进程）。

    Windows 走 `taskkill /F /T`；别的平台退回 `os.kill`。掐完返回一句人话（原因照实说）。
    ★ T-G96：`taskkill` 的输出是**系统区域编码**（这台机器是 cp936），原来按 `utf-8` 解 → 乱码
    （掐是掐掉了，但那句回话没法读）。改成**系统区域编码** + `errors="replace"`（解不开的字节
    替换掉，**绝不让解码把掐进程这条路带崩**）。只动解码这一处。
    ★ 为什么用 `locale.getencoding()` 而不是 `getpreferredencoding(False)`：本仓一律
    `python -X utf8`，那会让后者返回 `utf-8`（UTF-8 模式）→ 等于没改；前者仍回系统区域编码
    （实测 **cp936**）。
    """
    if os.name == "nt":
        enc = (locale.getencoding() if hasattr(locale, "getencoding")
               else locale.getpreferredencoding(False)) or "utf-8"
        done = subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                              capture_output=True, text=True, encoding=enc,
                              errors="replace", **NO_WINDOW)
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
               printer: Callable[[str], None] = print,
               worker_cwd: Path | None = None) -> tuple[int, str, str, str]:
    """真跑工人并且**盯着它** —— 返回 `(退出码, 掐掉/超时/撞上限的原因, 现场, 会话 id)`。

    第 4 项是给"续跑"用的（T-G90）：中断之后带着同一个会话接着干，而不是从头再来。

    为什么不是一句 `subprocess.run(stdout=file)`（T-G82 的老写法）：那样主控在它跑的那一小时里
    **什么都看不见** —— 卡死了在等、空转烧时间也在等，而这两种"等"都不该发生。
    所以改成 Popen + 读线程（逐行落盘、顺手喂判据）+ 主循环（心跳 / 看门狗 / 超时）。

    ★ 边界（如实写）：判据每轮把已落的 log **整段重解析**（简单、够快：卡 002 那种量级
    300 多条事件，解析一遍是毫秒级）；真跑出几万条事件再谈增量。
    ★ T-G96 第二层兜底：**判据自己抛异常时不许让看门狗失效** —— 退到"当成没有在飞 / 没有耗时
    数据"的保守口径继续盯，并把这次异常**如实记进心跳 / 判决**（不静默吞掉）。
    ★ 卡 103（T-G199）：`worker_cwd` 给了就是**工人进程的 cwd**（工人落在卡树里干活）；
    不给（默认 `None`）仍是仓库根 —— `cwd` 传参逐字不变。
    """
    log.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    state: dict[str, float] = {"last_at": time.monotonic()}
    lock = threading.Lock()
    reason = ""
    guard_note = ""      # 判据抛过异常就记在这里（T-G96）—— 如实说，不假装没发生

    errlog.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    last_beat = started
    with errlog.open("w", encoding="utf-8") as err:
        proc = subprocess.Popen(          # noqa: S603 —— 命令是本地拼好的 CLI，不是外部输入
            list(cmd), cwd=str(worker_cwd or ROOT), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
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
                    try:
                        verdict = watchdog_verdict(silent_seconds=silent, signatures=snapshot,
                                                   stall_seconds=stall_seconds, lines=snapshot)
                    except Exception as exc:      # noqa: BLE001 —— 判据炸了也**不许让看门狗失效**
                        guard_note = (f"（看门狗判据抛异常，已退回保守口径："
                                      f"{type(exc).__name__}: {exc}）")
                        try:                       # 兜底：不给 lines = 老口径（无在飞/无耗时）
                            verdict = watchdog_verdict(silent_seconds=silent, signatures=snapshot,
                                                       stall_seconds=stall_seconds)
                        except Exception:          # noqa: BLE001 —— 兜底也炸：至少别连累主循环
                            verdict = f"卡死：{silent / 60:.1f} 分钟没有新事件"
                    if verdict:
                        reason = verdict + ("" if guard_note in verdict else guard_note)
                        break
                if heartbeat_seconds and now - last_beat >= heartbeat_seconds:
                    last_beat = now
                    try:
                        sigs = tool_signatures(snapshot)
                        live = inflight_tool(snapshot)
                        _, hb = wb_status.parse_events(snapshot)
                        printer(heartbeat_line(
                            elapsed=now - started, turns=turns_seen(snapshot),
                            tool_calls=len(sigs), files=hb["files_total"],
                            silent_seconds=silent, inflight=live[0] if live else None) + guard_note)
                    except Exception as exc:      # noqa: BLE001 —— 心跳这条路同样兜底
                        guard_note = (f"（心跳判据抛异常，已退回保守口径："
                                      f"{type(exc).__name__}: {exc}）")
                        printer(f"[心跳] 已跑 {(now - started) / 60:.1f} 分钟 | "
                                f"日志静默 {silent:.0f} 秒{guard_note}")
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

    sid = session_id_seen(snapshot)
    if reason:
        return code, f"{reason} → {killed}", _scene(snapshot), sid
    return (code, cap_verdict(turns_seen(snapshot), max_turns) or finish_verdict(snapshot),
            "", sid)


def _scene(lines: list[str]) -> str:
    """掐掉那一刻的现场：最后几步 + 它碰过哪些文件（主控据此判断"卡在哪一步"）。

    ★ T-G96 第二层兜底：现场渲染走 `wb_status.parse_events()`，它对畸形 log（`message` 不是 dict）
    同样会抛 —— 若不接住，异常会**逃出** `run_worker` 的收尾路径，等于畸形 log 让看门狗失效。
    所以这里退回一句"现场渲染失败"，**绝不因此让掐进程这件事本身出不来**。
    """
    try:
        timeline, summary = wb_status.parse_events(lines)
    except Exception as exc:              # noqa: BLE001 —— 现场渲染只是辅助，不许带崩主流程
        return f"    （现场渲染失败，退回一句结论：{type(exc).__name__}: {exc}）"
    tail = timeline[-SCENE_LINES:]
    files = "、".join(summary["files"]) or "（没碰过文件）"
    return ("\n".join(f"    {ln}" for ln in tail)
            + f"\n    碰过的文件（{summary['files_total']} 个）：{files}"
            + f"\n    工具调用 {summary['tool_calls']} 次；"
            + f"认不出的行 {summary['unknown_events']} 条")


def _porcelain_path(line: str) -> str:
    """`git status --porcelain` 的一行 → 纯仓库相对路径（posix 风格）。

    porcelain 行形如 `M src/x.py` / `?? file` / ` M docs/c.md` —— 路径取 `XY ` 三字符之后。
    ★ 卡 109：越界判据现在走 `pool.review.outside_allow()`（唯一实现），那只吃**纯路径**，
    所以 porcelain → 纯路径这一步留在**调用点**，不再自己写一份比对逻辑。
    """
    return (line[3:].strip() if len(line) > 3 else line).replace("\\", "/")


# ---------------------------------------------------------------- 内存闸（卡 102 / T-G198）
# 与 `scripts/run_gates.py` **同一套口径**：读 **available**、同一个环境变量 `TF_GATE_MIN_FREE_GB`
# （默认 4.0，`0` = 关）、同一套措辞、同样"读不到就跳过"。派活同样吃内存（工人会跑 pytest /
# 起真服务），所以派活前也要过这道闸。★ 只加这一条前置判据 —— 派活主流程（心跳 / 看门狗 /
# 429 / 判决口径 / retry）与 `--status` 三态判据一个字不动。
DEFAULT_GATE_MIN_FREE_GB = 4.0


def available_memory_gb() -> float | None:
    """读**可用**内存（available，GB）；读不到 → None（调用方跳过这道闸，不静默当通过、也不拒跑）。

    ★ **不许依赖 `psutil`**（本仓 `pyproject.toml` 的 `dependencies` 里没有它）。
    Windows 走 `ctypes` 的 `GlobalMemoryStatusEx`（`ullAvailPhys`）；其它平台 `os.sysconf`。
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
    """内存闸阈值（GB）：`TF_GATE_MIN_FREE_GB`（默认 4.0；`0` = 关掉这道闸）。坏值 → 退回默认。"""
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
    """内存闸判据（卡 102）：可用内存 < 阈值 → 返回一句人话（**不派活**）；否则 None（放行）。

    与 `run_gates.memory_gate_problem` 同一套措辞：阈值 `0` → 打一行"闸已关"并放行；
    读不到内存（None 或抛异常）→ 打印"读不到，闸跳过"并放行（不静默当通过、也不拒跑）；
    正常 → 打印一行读数并放行。
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


def _resolve_port_bases(cli: list[int] | None) -> list[int] | None:
    """端口段来源：`--port-base`（可多次）**优先**；没给则读 **`TF_DISPATCH_PORT_BASE`**。

    ★★ 卡 195（T-G195，真回归）：**绝不读 `TF_GATE_PORT_BASE`** —— 那是**门禁自己**的端口段，
    `run_gates.py` 会把它设进**每一道门**的子进程环境里（**包括 pytest**）。读了它就会在门禁内部
    把"门禁自己的服务正在 `BASE..BASE+16` 上听"误判成"段被占"→ **拒派** → 门内 24 条用例全红
    （2026-10-01 卡 098 那趟实测）。
    返回 `None` = 给的值不是整数（调用方打印原因并退 2）；返回 `[]` = 没给（如实跳过体检）。
    """
    bases = [int(x) for x in (cli or [])]
    if bases:
        return bases
    raw = os.environ.get("TF_DISPATCH_PORT_BASE", "").strip()
    if not raw:
        return []
    try:
        return [int(tok) for tok in re.split(r"[,\s]+", raw) if tok]
    except ValueError:
        print(f"[FAIL] TF_DISPATCH_PORT_BASE 不是整数端口段：{raw!r}", file=sys.stderr, flush=True)
        return None


def port_preflight(port_bases: list[int] | None) -> list[str]:
    """端口段体检（铁律 37）—— 段内有占用就**拒派**；没给段就如实跳过。

    为什么是 17 个端口：行为流 ㉒ 要起「另一台设备」当对端，对端走 `BASE+16`；实测 9197 被
    外来常驻服务 `vivoesService_x64.exe` 占着 → ㉒ 稳定报 `fetch failed`。所以派活前逐段看
    `BASE..BASE+16`。★ 只判「拒派」，**不自动换段**（换段是主控的决定）。
    没给端口段 → 打印一行跳过；★ **不检查也不假装检查**（不许静默当通过）。
    """
    if not port_bases:
        print("  未给端口段，跳过端口体检", file=sys.stderr, flush=True)
        return []
    import tf_portcheck  # 同一目录（tools/），真身见 tools/tf_portcheck.py

    span = tf_portcheck.DEFAULT_SPAN
    busy = tf_portcheck.busy_ports()
    problems: list[str] = []
    for base in port_bases:
        hits = tf_portcheck.segment_hits(base, span, busy)
        if hits:
            who = "；".join(f"{port} ← {name}" for port, name in hits)
            problems.append(
                f"端口段 {base}..{base + span - 1} 内有占用 → 拒派：{who}"
                f"（铁律 37 / 行为流 ㉒：对端用 BASE+16，被占会稳定报 fetch failed）")
    return problems


def worker_tree_label(worker_cwd: Path | None, main_root: Path) -> str:
    """工人要占的树 —— 登记用的标签：**主树 = ""**；卡树 = 相对主树根的 posix 路径。

    ★ `pool.registry` 的树标签就是这种形式（`pool_mcp._dispatch_argv` 把 `--cwd` 传成
      `main_root / tree` 或 `main_root`）—— 这里**反过来**从 `--cwd` 还原出标签，好让
      `tree_guard` 按同一把尺子比。树在仓库外（罕见）：原样给绝对 posix 路径（守卫按字符串比，
      不猜、不归一成"主树"）。
    """
    if worker_cwd is None:
        return ""
    target = worker_cwd.resolve()
    try:
        rel = target.relative_to(main_root.resolve())
    except ValueError:
        return target.as_posix()
    text = rel.as_posix()
    return "" if text == "." else text


def lease_log_for(log: Path) -> str:
    """要写进租约的 `log` 字段 —— **绝对 posix 路径**（口径与 MCP 写面 `pool_dispatch` 一致）。

    **为什么登记它（卡 141 · T-G240）**：`pool.registry` 的死租约判据有两条 —— ① TTL 过期、
    ② **该卡的作业日志被判「断了 / 已判决」**（`registry.is_dead` → `pool.jobs.scan_jobs`）。
    租约不带 `log` 时**只剩 ①**，于是「工人 / 派活器**被强杀**（`atexit` 根本不跑）」这条路上
    的租约要把树占满 TTL（6 小时）—— 2026-10-02 真咬过：`.wt/projguard` 的工人被
    `kill_tree` 掐掉 ⇒ 二十多分钟后别的卡因「冲突域相交」被拒 ⇒ 主控只能**手工**
    `registry.release('120')` 才继续。带上 `log` 之后，日志一静默（> `STALL_SECONDS`）或一有判决，
    `list_reservations()` / `prune()` 就能把它清掉。

    ★ **文件已存在时返回 ""（不登记）**：`reserve` 会连带过 `log_guard`（目标已存在就拒），
      而那正是 `--force` 要覆盖的那条路（`preflight` 的"这一轮的 log 已存在"）—— 硬塞会被守卫
      拦下 ⇒ 连派活都派不出去。所以这种情况**不登记**，退回 TTL 兜底。
      ★ 边界（如实记）：`--force` / log 已存在那条路的租约**仍只能等 TTL** 才消失。
    """
    return "" if log.exists() else log.as_posix()


def queue_files(card: str, *, root: Path | None = None) -> tuple[list[str], str | None]:
    """从队列（backlog）**真读**这张卡的冲突域；查不到 → 返回 `([], 一句原因)`。

    ★ 绝不许把查不到的卡猜成"空域" —— 空域 = 不与任何活租约相交 = 骗过 `domain_guard`
      （`pool/guards.py` 模块头专门写了这条）。查不到就拒，宁可多问人一次。
    """
    base = (root or ROOT) / "docs" / "workbacklog.toml"
    try:
        backlog = load_backlog(base)
    except BacklogError as exc:
        return [], f"读不了队列（冲突域无处可查）：{base}（{exc}）"
    hit = backlog.by_id().get(str(card))
    if hit is None or not hit.files:
        return [], f"队列里没有卡 {card} 的冲突域 ⇒ 不许派活（别猜空域）"
    return list(hit.files), None


def guard_problems(card: str, worker_cwd: Path | None, *, now: float | None = None,
                   project: str | None = None) -> list[str]:
    """守卫的干跑（树 / 冲突域 / 项目 / 门禁锁）—— 返回问题清单（空 = 全过）。

    ★ 判据全在 `pool.guards`（在这里只**喂数据**，不另写一份）：活租约来自
      `pool.registry.list_reservations`（它先清死租约）、锁原文来自
      `pool.registry.read_lock_body`（不许自己拼 shell 命令）。
    ★ 位置与现有 `[FAIL] 不派活` **同一层**：任何一条咬 → 这条派活前置检查全过不了。
    ★ 算不出主工作树 / 读不了登记 / 查不到域 / 项目索引读不了 → **拒**（不静默当通过，也不猜）。
    ★ 卡 120：项目守卫（`project_guard`）接在**树 / 域守卫之后**；`project` 不给 ⇒ 按树反查。
    """
    files, why = queue_files(card)
    if why:
        return [why]
    try:
        main_root = pool_registry.main_tree_root()
    except pool_registry.RegistryError as exc:
        return [f"算不出主工作树（守卫判不了树/锁）：{exc}"]
    tree = worker_tree_label(worker_cwd, main_root)
    try:
        live = pool_registry.list_reservations(now)
    except pool_registry.RegistryError as exc:
        return [f"读不了作业登记（守卫判不了树/域）：{exc}"]
    lock_body = pool_registry.read_lock_body()
    return [
        *pool_guards.tree_guard(tree, live, now),                          # ① 一棵树一个写者
        *pool_guards.domain_guard(files, live, now),                       # ② 冲突域不相交
        *pool_guards.project_guard(tree, project),                         # ③ 项目：登记/前缀/反查
        *pool_guards.lock_guard(card, tree, lock_body, root=main_root),    # ④ 门禁还在跑
    ]


# ================================================================ 卡树基点过期（卡 135 · T-G233）


def _tree_head(tree: Path) -> str | None:
    """`tree` 的 HEAD sha；跑不了 git / 不是仓库 / 算不出 → `None`（不许猜）。"""
    try:
        done = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(tree), capture_output=True, text=True,
            encoding="utf-8", errors="replace", **NO_WINDOW,
        )
    except OSError:
        return None
    out = (done.stdout or "").strip()
    return out if done.returncode == 0 and out else None


def _changed_since(root: Path, base: str, head: str, files: list[str]) -> list[str] | None:
    """`base..head` 之间改过的**域内**文件名；算不出（拿不到主树 / git 报错）→ `None`。"""
    try:
        done = subprocess.run(
            ["git", "diff", "--name-only", f"{base}..{head}", "--", *files],
            cwd=str(root), capture_output=True, text=True, encoding="utf-8",
            errors="replace", **NO_WINDOW,
        )
    except OSError:
        return None
    if done.returncode != 0:
        return None
    return [ln for ln in (done.stdout or "").splitlines() if ln.strip()]


def _commits_since(root: Path, base: str, head: str, files: list[str]) -> str:
    """`base..head` 里与域相关的提交（`git log --oneline` 原文，多行压一行）；取不到就说取不到。"""
    try:
        done = subprocess.run(
            ["git", "log", "--oneline", f"{base}..{head}", "--", *files],
            cwd=str(root), capture_output=True, text=True, encoding="utf-8",
            errors="replace", **NO_WINDOW,
        )
    except OSError:
        return "（取不到提交列表）"
    text = (done.stdout or "").strip()
    return text.replace("\n", " / ") if text else "（没有可点名的提交）"


def stale_base_problem(card: str, worker_cwd: Path | None, *,
                       main_root: Path | None = None) -> str | None:
    """★ 卡 135（T-G233）：**卡树的基点之后，主树有没有改过这张卡要碰的文件？**

    为什么（本轮真咬的一口）：收 `B-FIX1` 时卡树的基点比主树旧，而主树恰好也改了卡树要碰的
    那份文件 ⇒ 收口把卡树那份**拷回主树**时**静默覆盖**了主树的新改动（测试当场红）。口头正解
    是"下一批的卡树要等上一批落地之后再建"，但那**不是判据** —— 这条把它做成机器判据。

    判据（只拒不猜）：
      - 卡树没有给（`worker_cwd is None`）⇒ 工人在**主树**里干活，与主树同基点 ⇒ 放行；
      - 域从**队列真读**（`queue_files`，与既有守卫同源）；查不到域 ⇒ 放行（既有守卫已经会拒，
        这条不重复咬，也不另造一份域来源）；
      - 取卡树 HEAD `A`、主树 HEAD `B`；`A == B` ⇒ 放行；
      - 否则 `git diff --name-only A..B -- <域>`：**空**（基点之后主树只改了域外文件）⇒ 放行
        （多批并行时这很常见，别误伤）；**非空** ⇒ 拒，**点名**那些文件 + 涉及的提交 + 修法。
      - 算不出 `A`/`B`（不在 git 树里等）⇒ **如实说"算不出基点，跳过这条判据"并继续**，
        ★ 不许把"算不出"当"过期"（那会把好卡全拒了）。
    """
    if worker_cwd is None:
        return None
    files, why = queue_files(card)
    if why:
        return None
    root = main_root
    if root is None:
        try:
            root = pool_registry.main_tree_root()
        except pool_registry.RegistryError as exc:
            print(f"  卡树基点体检：算不出主树（{exc}）→ 算不出基点，跳过这条判据",
                  file=sys.stderr, flush=True)
            return None
    a = _tree_head(worker_cwd)
    b = _tree_head(root)
    if a is None or b is None:
        print("  卡树基点体检：算不出基点（有树不在 git 里）→ 跳过这条判据",
              file=sys.stderr, flush=True)
        return None
    if a == b:
        print("  卡树基点体检：卡树与主树同基点 → 过", file=sys.stderr, flush=True)
        return None
    hits = _changed_since(root, a, b, files)
    if hits is None:
        print("  卡树基点体检：算不出基点之后改了哪些文件 → 跳过这条判据",
              file=sys.stderr, flush=True)
        return None
    if not hits:
        print("  卡树基点体检：基点之后主树只改了域外文件 → 过", file=sys.stderr, flush=True)
        return None
    commits = _commits_since(root, a, b, files)
    return (f"卡树基点过期：这张卡要碰的文件在主树基点之后被改过（卡树建早了）→ 卡树 HEAD "
            f"{a[:12]} / 主树 HEAD {b[:12]}；被改的文件：{', '.join(hits)}；相关提交：{commits}；"
            f"修法：这张卡的树建早了 ⇒ 把树重置到主树 HEAD 再派"
            f"（`git -C <树> reset --hard {b[:12]}` 会丢未提交改动，先 `git status` 看清楚），"
            "或重建一棵树")


def preflight(card: str, spec: str, *, force: bool, check_auth: bool,
              cli_override: str | None = None, resuming: bool = False,
              allow: list[str] | None = None,
              port_bases: list[int] | None = None,
              worker_cwd: Path | None = None,
              already_reserved: bool = False,
              project: str | None = None) -> tuple[list[str], Path]:
    """四道检查 —— 返回（问题清单, 日志路径）。问题非空就不许派活。

    ★ 卡 029 §2.10（本轮真撞的）：**续跑**（`--resume <id>` / `--resume auto` 拿到了 id）时
    「工作区必须干净」**不适用** —— 工人上一轮的未提交改动**正是要接着干的活**。但**不能不看**：
    改成把 `git status --porcelain` 原文打出来 + 一行「★ 续跑：…继续」→ 放行；
    脏文件里若有不在 `--allow` 白名单里的 → 醒目告警（可能是别的卡串了树）。
    ★ **非续跑**（全新一轮）保持原判据（必须干净）—— 那是"一写一读"的护栏，不许松。
    ★ **卡 103（T-G199）**：给了 `worker_cwd`（`--cwd`）时，"工作区必须干净"看的是
    **工人要干活的那棵树**（那才是"一写一读"要护的地方）；**主仓状态照打当提示、但不因此拒派**
    （主控自己的文档改动不该挡住派活）。给的路径不是 git 工作树 → 明确报错（不静默当干净）。
    不给 `worker_cwd` 时行为逐字不变（仍看主仓）。
    ★ **卡 125 修订**：`already_reserved=True`（`--already-reserved`）= 调用方（MCP 写面）已经
    占过树 ⇒ **只跳过守卫那一段**；别的检查（规格 / 脏树 / log / 端口 / 内存 / 登录）**照走**。
    不带它时行为**一字不变**。
    ★ **卡 120**：`project` 给或不给，都过 `project_guard`（不给 ⇒ 按树从项目索引反查）；它接在
    既有树 / 域守卫**之后**，**不放宽**任何既有前置（内存 / 登录 / 白名单 / 日志 / 树 / 域 / 锁）。
    """
    problems: list[str] = []
    node, cli = paths(cli_override)
    log = ROOT / "gates" / "diag" / f"wb-{card}.jsonl"
    if not (ROOT / spec).exists():
        problems.append(f"卡规格文件不存在：{spec}（不许凭记忆派活）")
    if not node.exists():
        problems.append(f"找不到内置 node：{node}")
    if not cli.exists():
        problems.append(f"找不到 CLI：{cli}")
    if worker_cwd is not None:
        # ★ 卡 103：脏检查看**工人要干活的那棵树**；主仓状态只当提示、不拒派。
        if not is_git_worktree(worker_cwd):
            problems.append(f"--cwd 不是 git 工作树：{worker_cwd}"
                            "（一写一读要护的那棵树不在 → 不静默当干净）")
            dirty: list[str] = []
        else:
            dirty = git_dirty(worker_cwd)
        root_dirty = git_dirty(ROOT)
        root_state = ("干净" if not root_dirty
                      else f"脏（{len(root_dirty)} 个被跟踪文件有改动）")
        print(f"  工人干活树（--cwd）：{worker_cwd}", file=sys.stderr, flush=True)
        print(f"  主仓状态：{root_state} —— 只提示，不拦派活（卡 103）",
              file=sys.stderr, flush=True)
    else:
        dirty = git_dirty()
    if dirty and not resuming:
        where = f"工人干活树 {worker_cwd}" if worker_cwd is not None else "主仓"
        problems.append(f"工作区不干净（{where}，{len(dirty)} 个被跟踪文件有改动）→ 一写一读："
                        f"先提交或收起它们：{', '.join(dirty[:5])}")
    elif dirty:
        print("  续跑前核对 —— git status --porcelain 原文：", file=sys.stderr, flush=True)
        for ln in dirty:
            print(f"    {ln}", file=sys.stderr, flush=True)
        print(f"★ 续跑：工作区带着 {len(dirty)} 个未提交改动（上一轮的活），继续",
              file=sys.stderr, flush=True)
        if allow:
            # ★ 卡 109：判据走唯一实现 `pool.review.outside_allow()`（只吃纯路径）——
            #   porcelain → 纯路径的还原留在这里；打出来的仍是 porcelain 原文。
            rel_paths = [_porcelain_path(ln) for ln in dirty]
            outside = outside_allow(rel_paths, allow)
            if outside:
                outside_lines = [ln for ln, p in zip(dirty, rel_paths, strict=False)
                                 if p in outside]
                print(f"  [★告警] {len(outside)} 个脏文件不在 --allow 白名单里"
                      f"（可能是别的卡串了树）：{', '.join(outside_lines[:5])}",
                      file=sys.stderr, flush=True)
    if log.exists() and not force:
        problems.append(f"这一轮的 log 已存在：{log}（要覆盖请 --force —— 证据不许被悄悄盖掉）")
    # ★ 卡 125（T-G223）：四条守卫的干跑（树 / 冲突域 / 门禁锁）—— 与 `[FAIL] 不派活` 同一层。
    #   域从队列**真读**（查不到就拒，见 `queue_files`）；判据全在 `pool.guards`，不另写一份。
    #   ★ `--already-reserved`：调用方（MCP）已经占过树 ⇒ 只跳过这一段（占/还树也在 main 里跳过）。
    if already_reserved:
        print("  守卫已跳过（--already-reserved：树由调用方占过，判据在那边）",
              file=sys.stderr, flush=True)
    else:
        guard_list = guard_problems(card, worker_cwd, project=project)
        if not guard_list:
            print("  守卫全过（树被占 / 冲突域相交 / 项目越界 / 门禁还在跑 —— 四条都没咬）",
                  file=sys.stderr, flush=True)
        problems.extend(guard_list)
    # ★ 卡 135（T-G233）：卡树基点过期 —— 基点之后主树改过这张卡域里的文件 ⇒ 拒派
    #   （收口把卡树那份旧文件拷回主树 = 静默覆盖新改动，真咬过：.wt/mcpclaim vs B-FIX1）。
    #   ★ 挂在守卫**之外**：`--already-reserved` 只跳过守卫，这条判据照走（它跟占没占树无关）。
    stale = stale_base_problem(card, worker_cwd)
    if stale:
        problems.append(stale)
    # ★ 卡 095：端口段体检（铁律 37）—— 给了段且段内有占用就拒派；没给段则如实跳过。
    problems.extend(port_preflight(port_bases))
    # ★ 卡 102（T-G198）：内存闸 —— 派活同样吃内存，可用内存不够就不派活（同一环境变量/措辞）。
    mem = memory_gate_problem()
    if mem:
        problems.append(mem)
    if check_auth and not problems:
        ok, why = auth_ok(node, cli)
        if not ok:
            problems.append(why)
    return problems, log


def build_parser() -> argparse.ArgumentParser:
    """命令行解析器 —— 抽成函数，好让测试**真读帮助文本**（卡 125 §2.9：帮助与常量同源）。"""
    parser = argparse.ArgumentParser(description="派活给 CodeBuddy CLI（默认 dry-run）")
    parser.add_argument("--card", required=True, help="卡号（用来命名 log，如 001）")
    parser.add_argument("--spec", default="", help="卡规格文件（相对仓库根；--status 时不必给）")
    parser.add_argument("--cwd", default="",
                        help="工人进程的 cwd（绝对/相对都行，会解析成绝对路径）—— 让工人"
                             "**落在卡树里干活**（卡 103）。★ 派活产物（wb-<卡>.jsonl / "
                             "brief-<卡>.md / 卡规格）仍落在**主仓**的 gates/diag/：那一份目录"
                             "是 gitignore 的、卡树里没有。不给则行为与从前逐字相同（工人 cwd="
                             "仓库根）")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"派活用哪个模型（默认 {DEFAULT_MODEL}）。★ 允许集 = 名单常量 "
                             "MODEL_WHITELIST / ONE_OFF_MODELS **外加**外部开关文件 "
                             "infra/pool/model-switches.toml 里打开(true)的模型；"
                             "表外一律拒单（用户 2026-09-26 令：黑名单锁死）")
    parser.add_argument("--project", default=None,
                        help="项目名（卡 120）—— 不给就按 `--cwd` 那棵树从项目索引反查；"
                             "没登记的项目 / 树不落在该项目的树前缀里 ⇒ 拒派")
    parser.add_argument("--cli", default=None,
                        help="CLI 入口覆盖（默认优先用独立安装的那份）")
    parser.add_argument("--permission-mode", default=DEFAULT_PERMISSION_MODE,
                        help="工人的权限模式（默认 bypassPermissions：否则 python 会被挡回来）")
    parser.add_argument("--execute", action="store_true",
                        help="真派活（默认只做前置检查 + 打印命令）")
    parser.add_argument("--force", action="store_true", help="允许覆盖已有 log")
    parser.add_argument("--already-reserved", action="store_true",
                        help="★ 调用方（MCP 写面）已经占过这棵树 ⇒ **只跳过**守卫与占/还树；"
                             "别的前置检查（规格 / 脏树 / log / 端口 / 内存 / 登录）照走。"
                             "不带它时行为一字不变（守卫照走、照样占树）")
    parser.add_argument("--no-preflight", action="store_true", help="跳过登录自检")
    parser.add_argument("--lean", action="store_true",
                        help="改读 ≤6KB 开工切片 gates/diag/brief-<卡>.md（不拼那四份大文档）")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"工人最长跑多久（秒，默认 {DEFAULT_TIMEOUT}）；"
                             "★ 超时不是失败，是『掐掉再续跑』的信号")
    # ★ 卡 125 §2.9：帮助文本的数字**从常量拼出来**（从前写死"150 / 60"，而常量是 240/80
    #   —— 照帮助估预算会低估 60%）。改常量帮助自动跟着变，钉子（tests）钉住这条同源。
    parser.add_argument("--max-turns", type=int, default=0,
                        help=f"回合上限（0 = 按卡种取默认：写卡 {DEFAULT_MAX_TURNS_WRITE} / "
                             f"只读卡 {DEFAULT_MAX_TURNS_READONLY}）")
    parser.add_argument("--read-only", action="store_true",
                        help=f"这是一张只读卡 → 回合上限默认取 {DEFAULT_MAX_TURNS_READONLY}"
                             "（预算，不是安全边界）")
    parser.add_argument("--autocompact", default=DEFAULT_AUTOCOMPACT,
                        help="自动压缩窗口（默认 1m；CLI 钳位 100k-1M）")
    parser.add_argument("--heartbeat-seconds", type=int, default=HEARTBEAT_SECONDS,
                        help="心跳行间隔（秒；0 = 不打）")
    parser.add_argument("--stall-seconds", type=int, default=STALL_SECONDS,
                        help=f"日志静默多久算卡死（秒，默认 {STALL_SECONDS}）—— ★ 这只是**底线**："
                             "有工具在飞时抬到 BUSY_STALL_SECONDS，再按最近 12 次里最长一次自适应")
    parser.add_argument("--poll-seconds", type=float, default=POLL_SECONDS,
                        help="看门狗多久醒一次（秒）")
    parser.add_argument("--no-watchdog", action="store_true",
                        help="关掉看门狗（卡死/空转不再自动掐；心跳仍在）")
    parser.add_argument("--retry", type=int, default=DEFAULT_RETRIES,
                        help="被中断（卡死/超时/没跑完）后自动带同一会话续跑几次"
                             "（默认 1；0 = 不续）")
    parser.add_argument("--resume", default="",
                        help="带着同一会话接着跑：给 sessionId，或 auto（读 wb-<卡>.session.txt）")
    parser.add_argument("--allow", action="append", default=None,
                        help="该卡的白名单 glob（续跑时脏文件越界告警用；可多次给）")
    parser.add_argument("--port-base", action="append", type=int, default=None,
                        help="端口段起点（可多次给）；不给则读环境变量 "
                             "TF_DISPATCH_PORT_BASE（★ 不是门禁那个）。"
                             "段内有占用 → 拒派（铁律 37）；都没给 → 跳过端口体检")
    parser.add_argument("--quota-wait", type=int, default=DEFAULT_QUOTA_WAIT,
                        help=f"撞 429 先等几秒再探（默认 {DEFAULT_QUOTA_WAIT}；用户 2026-09-26："
                             "「你先等一下」；0 = 测试用）")
    parser.add_argument("--input-budget", type=int, default=DEFAULT_INPUT_BUDGET,
                        help=f"单卡 input tokens 预算（默认 {DEFAULT_INPUT_BUDGET:,}）—— "
                             "超了就止损掐掉，不许自动续跑（防空烧）")
    parser.add_argument("--detach", action="store_true",
                        help="把这次派活**扔出去单独跑**（我的窗口关了它照样跑；过夜/长任务用）")
    parser.add_argument("--detach-done", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--status", action="store_true",
                        help="只看状态（心跳/判决/会话/log 尾巴），不派活、不用给 --spec")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.status:
        print(status_report(args.card), flush=True)
        return 0
    # ★★ 模型白名单硬闸门（卡 029 §2.4，用户 2026-09-26 令：默认拒绝）—— 放在**一切之前**：
    #   拒单必须**零副作用**：不起进程、不建 log、不写判决、不改树。--resume / --retry /
    #   --detach 全都从这里过闸（它们都要带 --model）。
    try:
        rejected = model_rejected(args.model)
    except SwitchFileError as exc:
        # ★ 卡 138：外部开关文件坏了要**响亮地**失败并点名路径与行号（**不静默当空**）——
        #   仍在起进程之前拦下（零副作用），退出码 2（前置检查没过）。
        print(f"[FAIL] {exc}", file=sys.stderr, flush=True)
        return 2
    if rejected:
        print(f"[FAIL] {rejected}", file=sys.stderr, flush=True)
        return 2
    if not args.spec:
        print("[FAIL] 派活得给 --spec（卡规格文件）；只看状态可以加 --status", file=sys.stderr,
              flush=True)
        return 2
    # ★ 卡 029 §2.10：续跑与不续跑的「干净」判据不同 → 先把会话 id 定下来，再过前置检查。
    log_guess = ROOT / "gates" / "diag" / f"wb-{args.card}.jsonl"
    resume_sid = args.resume
    if resume_sid == "auto":
        side = session_file_for(log_guess)
        resume_sid = side.read_text(encoding="utf-8").strip() if side.exists() else ""
        if not resume_sid:
            print(f"[FAIL] --resume auto 但没找到会话文件：{side}", file=sys.stderr)
            return 2
    port_bases = _resolve_port_bases(args.port_base)
    if port_bases is None:
        return 2
    # ★ 卡 103（T-G199）：--cwd 解析成绝对路径（工人进程就落在它里面干活）。
    worker_cwd = Path(args.cwd).expanduser().resolve() if args.cwd else None
    problems, log = preflight(
        args.card, args.spec, force=args.force, check_auth=not args.no_preflight,
        cli_override=args.cli, resuming=bool(resume_sid), allow=args.allow,
        port_bases=port_bases, worker_cwd=worker_cwd,
        already_reserved=args.already_reserved, project=args.project,
    )

    if problems:
        print("[FAIL] 不派活 —— 前置检查没过：", file=sys.stderr, flush=True)
        for item in problems:
            print(f"  · {item}", file=sys.stderr, flush=True)
        # ★ 没过也要留痕（T-G92）：过夜跑时「没跑」和「跑挂了」必须一眼分得清
        #   —— `--status` 读的就是这个文件。旧写法在 detach 那条路上什么都不写。
        verdict = verdict_file_for(log)
        verdict.parent.mkdir(parents=True, exist_ok=True)
        verdict.write_text(
            f"card={args.card} 结束于={datetime.now().isoformat(timespec='seconds')}\n"
            "判决：前置检查没过 → 没派活\n"
            f"原因：{'；'.join(problems)}\n",
            encoding="utf-8")
        # ★ 摘要一样全（T-G95）：没派活也是**一条退出路径**，`--status` 照样能先看摘要。
        write_report(log, card=args.card, code=2, reason="前置检查没过 → 没派活", scene="",
                     sid="", attempts=1, lines=[], started_at=None)
        return 2

    if args.detach and not args.detach_done:
        # ★ 长跑/过夜：**前置检查已全过**，才把**自己**再启动成一个脱离窗口的进程，然后立刻返回。
        #   ★ T-G92 更正：检查必须在**父进程**里先做完 —— 旧写法先 detach（父进程退 0）、
        #   检查在**子进程**里做，于是"扔出去"看起来成功、其实前置检查没过（也没留判决）。
        #   子进程补 `--no-preflight`：父进程已经查过登录，省掉那次真发请求的自检。
        detach_log = ROOT / "gates" / "diag" / f"wb-{args.card}.dispatch.log"
        pid = spawn_detached(detached_argv(sys.argv[1:]), detach_log)
        print(f"[OK ] 前置检查全过 → 扔出去单独跑（pid {pid}），我的窗口关了它照样跑", flush=True)
        print(f"[看 ] 进度：python -X utf8 tools/wb_dispatch.py --card {args.card} --status",
              flush=True)
        print(f"[log ] {detach_log}", flush=True)
        return 0

    node, cli = paths(args.cli)
    max_turns = args.max_turns or max_turns_default(args.read_only)
    lean_brief = ensure_lean_brief(args.card, worker_cwd) if args.lean else ""
    initial_cmd = build_command(node, cli, args.card, prompt_path(args.spec, worker_cwd),
                                args.model, args.permission_mode,
                                max_turns=max_turns, autocompact=args.autocompact,
                                lean=args.lean, brief=prompt_path(lean_brief, worker_cwd))

    done_checks = "规格在 / 工作区干净（续跑则核对后放行）/ log 未占用"
    if args.no_preflight:
        done_checks += " / **登录没查**（--no-preflight）"
    else:
        done_checks += " / 登录通"
    print(f"[OK ] 前置检查全过（{done_checks}）", flush=True)
    if worker_cwd is not None:
        print(f"[cwd ] 工人干活树：{worker_cwd}（工人进程 cwd = 它；产物仍在主仓 gates/diag/）",
              flush=True)
    print(f"[log ] {log}", flush=True)
    print(f"[cmd ] {' '.join(initial_cmd[:4])} … --model {args.model} --output-format stream-json "
          f"--permission-mode {args.permission_mode} --max-turns {max_turns} "
          f"--autocompact {args.autocompact}", flush=True)
    guards = ("看门狗**关**（--no-watchdog）" if args.no_watchdog else
              f"看门狗：日志静默过久（底线 {args.stall_seconds}s；有工具在飞则 30 分钟，"
              f"再按最近 {REPEAT_WINDOW} 次调用里最长一次 ×{TOOL_DURATION_FACTOR} 自适应）或"
              f"最近 {REPEAT_WINDOW} 次调用里"
              f"同一件事重复 {REPEAT_NEED} 次 → 掐")
    print(f"[盯 ] {guards}；心跳每 {args.heartbeat_seconds}s；超时 {args.timeout}s；"
          f"中断自动续跑 {args.retry} 次；input 预算 {args.input_budget:,}/卡；"
          f"429 三拍（等 {args.quota_wait}s → 按序换 → 全挂停，退出码 7）", flush=True)
    if not args.execute:
        print("[dry ] 这是 dry-run；真想派活加 --execute", flush=True)
        return 0

    # ★ 卡 029 §2.1（A 根因）：**真开跑**（过前置检查 + --execute）那一刻，把这张卡的旧
    #   判决 / 摘要改名归档（加 .stale）—— 只归档、不删（证据留档）。dry-run 不会走到这里。
    archived = archive_stale_artifacts(args.card)
    if archived:
        print(f"[归档] 旧判决/摘要已归档：{', '.join(archived)}", flush=True)
    # ★ 卡 029 §2.7：每次真开跑记规格指纹；续跑且指纹变了 → 硬塞「先读规格」进续跑提示词。
    spec_digest = spec_fingerprint(args.spec)
    spec_preamble = ("" if not resume_sid
                     else spec_changed_notice(prompt_path(args.spec, worker_cwd), log))
    spec_file_for(log).parent.mkdir(parents=True, exist_ok=True)
    spec_file_for(log).write_text(f"{args.spec}\nsha256={spec_digest}\n", encoding="utf-8")

    # ★★ 卡 125（T-G223）：真派活（--execute；dry-run 已在上面 return）**起工人之前**先占树 ——
    #   登记一次，别的窗口走正规干跑就看得见这个活（从前看不见 ⇒ 一树两写者不会被咬）。
    #   ★ 位置选这里的原因：`--detach` 的**父进程**在更上面就 return 了（它只负责扔出去），
    #     真正跑工人的是**脱离子进程**（带 `--detach-done`）；于是"占树 + 还树"都落在**跑工人
    #     的那个进程**里 —— 与卡的要求（还树由带租约的那个进程在工人收工后做，而不是父进程
    #     立刻还）一致。dry-run 不走这一段（不占树）。
    if args.already_reserved:
        # ★ 调用方（MCP 写面 `pool_dispatch`）**已经** reserve 过这条树 ⇒ 这里不占、也不还
        #   （还树归调用方：它拿 pid 走 `pool_cancel` / 租约 TTL）。守卫也已在 preflight 里跳过。
        def release_tree(why: str) -> None:
            """`--already-reserved`：占树/还树都归调用方 ⇒ 这里全是空操作。"""
            return

        print("[占树] --already-reserved：树由调用方（MCP）占过 —— 本次不占、不还", flush=True)
    else:
        reserve_files, reserve_why = queue_files(args.card)
        if reserve_why:
            print(f"[FAIL] {reserve_why}", file=sys.stderr, flush=True)
            return 2
        try:
            reserve_root = pool_registry.main_tree_root()
        except pool_registry.RegistryError as exc:
            print(f"[FAIL] 算不出主工作树 ⇒ 不占树、不派活：{exc}", file=sys.stderr, flush=True)
            return 2
        reserve_tree = worker_tree_label(worker_cwd, reserve_root)
        released = False

        def release_tree(why: str) -> None:
            """还树 —— **幂等**（已还过就是空操作）；任何退出路径都要走它（`atexit` 兜底）。"""
            nonlocal released
            if released:
                return
            released = True
            try:
                pool_registry.release(args.card)
            except pool_registry.RegistryError as exc:
                print(f"[还树] 释放失败（卡 {args.card}）：{exc}", file=sys.stderr, flush=True)
                return
            print(f"[还树] 租约已释放（卡 {args.card}；{why}）", flush=True)

        # ★ 卡 141：租约要带上**作业 log** —— 否则「工人被强杀（`atexit` 不跑）」这条路上它
        #   只能等 TTL（6 小时），把树白占着（真咬过，见 `lease_log_for`）。带上之后
        #   `registry.is_dead` 的「日志判死」那条判据就能生效（`list_reservations` / `prune`）。
        #   ★ 已存在的 log 不登记（`log_guard` 与 `--force` 覆盖语义打架，见 `lease_log_for`）。
        lease_log = lease_log_for(log)
        try:
            lease = pool_registry.reserve(args.card, tree=reserve_tree, files=reserve_files,
                                          project=args.project or "", model=args.model,
                                          log=lease_log,
                                          note=f"spec={args.spec}",
                                          lock_body=pool_registry.read_lock_body())
        except pool_registry.GuardError as exc:
            print("[FAIL] 占树被守卫拦下，**不派活**：", file=sys.stderr, flush=True)
            for item in exc.problems:
                print(f"  · {item}", file=sys.stderr, flush=True)
            return 2
        except pool_registry.RegistryError as exc:
            print(f"[FAIL] 占树失败（登记坏了），**不派活**：{exc}", file=sys.stderr, flush=True)
            return 2
        # ★ 照卡 118 给门禁锁做的兜底：进程怎么退都 release 一次（已还过 = 空操作）。
        atexit.register(release_tree, "进程退出兜底")
        print(f"[占树] 已登记租约：卡 {args.card}｜树 {reserve_tree or '（主树）'}｜"
              f"项目 {lease.get('project') or '（未定）'}｜"
              f"域 {'、'.join(reserve_files)}", flush=True)
        # ★ 说实话：按**登记里那条**报（别拿本地的 `lease_log` 报 —— 万一 reserve 没收，就成假读数）
        registered_log = str(lease.get("log") or "")
        print(f"      死租约判据：TTL {int(lease.get('ttl_seconds') or 0)}s"
              + (f" + 日志判死（log={registered_log}）" if registered_log
                 else "（**没有日志判死**：这一轮的 log 已存在，只能等 TTL）"), flush=True)

    attempts, code, reason, scene, sid = 1, 0, "", "", resume_sid
    model = args.model                       # 429 三拍会按序换（只换白名单里的）
    quota_seen: dict[str, str] = {}          # 每个模型撞的额度错（全挂就停时写进判决）
    usage_total = {"input_tokens": 0, "output_tokens": 0, "cache_read": 0}

    def beat(line: str) -> None:
        """心跳：既打出来，也**落成文件** —— 过夜跑时读一个文件就知道它还在不在动。"""
        print(line, flush=True)
        write_heartbeat(log, line)

    while True:
        log_k = log if attempts == 1 else log.with_name(f"wb-{args.card}.r{attempts}.jsonl")
        if attempts == 1 and not sid:
            cmd = build_command(node, cli, args.card, prompt_path(args.spec, worker_cwd),
                                model, args.permission_mode,
                                max_turns=max_turns, autocompact=args.autocompact,
                                lean=args.lean, brief=prompt_path(lean_brief, worker_cwd))
        elif sid:
            prompt = continuation_prompt(reason=reason or "上次被中断", scene=scene,
                                         card=args.card)
            # ★ 卡 029 §2.7：规格改过 → 「先读规格」硬塞在续跑提示词**最前面**（光说"规格改了"
            #   它会锚在旧上下文里当没看见 —— 卡 022 白跑两轮的真因）。
            cmd = resume_command(node, cli, sid, spec_preamble + prompt,
                                 model, args.permission_mode,
                                 max_turns=max_turns, autocompact=args.autocompact)
        else:
            print("[续 ] 没拿到 session id，续不了 → 只能重开一轮", file=sys.stderr, flush=True)
            cmd = build_command(node, cli, args.card, prompt_path(args.spec, worker_cwd),
                                model, args.permission_mode,
                                max_turns=max_turns, autocompact=args.autocompact,
                                lean=args.lean, brief=prompt_path(lean_brief, worker_cwd))
        print(f"[跑 ] 第 {attempts} 次；log {log_k.name}", flush=True)
        attempt_started = time.time()
        code, reason, scene, new_sid = run_worker(
            cmd, log_k, log_k.with_suffix(".stderr.txt"), timeout=args.timeout,
            max_turns=max_turns, watchdog=not args.no_watchdog,
            heartbeat_seconds=args.heartbeat_seconds, stall_seconds=args.stall_seconds,
            poll_seconds=args.poll_seconds, printer=beat, worker_cwd=worker_cwd,
        )
        sid = new_sid or sid
        if sid:                      # ★ 一拿到就落盘：这样中断之后 `--resume auto` 才用得上
            session_file_for(log).write_text(sid, encoding="utf-8")
        round_lines = log_k.read_text(encoding="utf-8", errors="replace").splitlines()
        # ★ 卡 029 §2.6：用量落账（无论成败）—— 数从 CLI 的 result.usage 拿，别自己估。
        usage = result_usage(round_lines)
        for key in usage_total:
            usage_total[key] += usage[key]
        append_usage_line(card=args.card, model=model, attempt=attempts,
                          started_at=attempt_started, usage=usage, code=code, reason=reason)
        # ★ T-G95：**每一条退出路径都落一份摘要**（含"被掐后再续跑"的每一轮），主控只读它。
        report = write_report(log_k, card=args.card, code=code, reason=reason, scene=scene,
                              sid=sid, attempts=attempts, lines=round_lines,
                              started_at=attempt_started)
        # ★ T-G96：判决**按轮落**（`wb-<卡>.r2.verdict.txt`…）—— 第 2 轮不许覆写第 1 轮的。
        verdict = write_verdict(log_k, card=args.card, attempts=attempts, code=code, reason=reason,
                                sid=sid, lines=round_lines,
                                errlog=log_k.with_suffix(".stderr.txt"))
        print(f"[done] 第 {attempts} 次：工人退出码 {code}；stderr 见 {log_k.name[:-6]}.stderr.txt",
              flush=True)
        print(f"[摘 ] 已落盘：{report.relative_to(ROOT).as_posix()}", flush=True)
        print(f"[判决] 已落盘：{verdict.relative_to(ROOT).as_posix()}", flush=True)
        # ★★ 卡 029 §2.5：429 三拍 —— **不许**走 `--retry` 自动续跑（那是拿仅剩的额度空撞）。
        #   先等（--quota-wait）→ 探（极小代价）→ 还挂按白名单顺序换 → 全挂就停（退出码 7）。
        quota = quota_error(round_lines)
        if quota is not None:
            note = quota["kind"] + (f"，将在 {quota['reset']} 重置" if quota["reset"]
                                    else "，无重置时间（余额耗尽）")
            quota_seen[model] = note
            print(f"[额度] ★ 检出 429 / 额度错误：{model} —— {note}"
                  f"（{quota['why']}；subtype=error_during_execution + 退出码 0，"
                  "长得像成功 —— 别被骗）",
                  file=sys.stderr, flush=True)
            # ★★ 卡 045（T-G136）续跑封顶 —— 界就是这一行：额度续跑与中断续跑**共用
            #   `--retry` 这一个界**（已续跑 attempts-1 次 ≥ retry → 到界，写判决、退出码 7）。
            #   R029 真撞过：旧代码这里无界，探针通过就永远「同一模型接着干」，白跑 3 轮。
            if attempts > args.retry:
                stop = ["", f"★★ 额度续跑到界：额度续跑次数已达 --retry={args.retry}"
                            " → 任务停下（退出码 7，不再自动重试）"]
                stop += [f"  · {m}：{n}" for m, n in quota_seen.items()]
                stop.append(f"  · 这次共烧 input tokens {usage_total['input_tokens']:,}"
                            f"（output {usage_total['output_tokens']:,}）")
                with verdict.open("a", encoding="utf-8") as vf:
                    vf.write("\n".join(stop) + "\n")
                print("\n".join(stop), file=sys.stderr, flush=True)
                print("[停 ] 额度续跑到界 → 任务停下（退出码 7）。恢复后由主控重派。",
                      file=sys.stderr, flush=True)
                release_tree("额度续跑到界 → 任务停下")
                return 7
            if args.quota_wait > 0:
                print(f"[额度] 等 {args.quota_wait}s 再探（用户 2026-09-26：「你先等一下」）",
                      flush=True)
                time.sleep(args.quota_wait)
            probe_ok, probe_why = quota_probe_ok(node, cli, model)
            if probe_ok:
                # ★★ 卡 045 §2.4：探针与判别器矛盾时**以探针为准** —— 探针真调了模型，
                #   它通过而这一轮又是「正常成功 + 非空回话」→ 判别器一定是被文本骗了
                #   → 按成功收下，不再续跑。
                if round_is_normal_success(round_lines):
                    print("[额度] 误判？（探针通过但判别器报额度）→ 按成功收下",
                          file=sys.stderr, flush=True)
                    break
                print(f"[额度] 探测通过（{probe_why}）→ 同一模型接着干", flush=True)
            else:
                nxt = next_whitelist_model(model)
                if nxt is None:
                    # ★ 全挂就停（用户原话：「都有问题的话，就直接把任务停下来」）——
                    #   不是「换个模型接着干」；退出码 7，不再自动重试。
                    stop = ["", "★★ 额度判决：白名单里的模型全部不可用 → 任务停下"
                                "（退出码 7，不再自动重试）"]
                    stop += [f"  · {m}：{n}" for m, n in quota_seen.items()]
                    stop.append(f"  · 这次共烧 input tokens {usage_total['input_tokens']:,}"
                                f"（output {usage_total['output_tokens']:,}）")
                    with verdict.open("a", encoding="utf-8") as vf:
                        vf.write("\n".join(stop) + "\n")
                    print("\n".join(stop), file=sys.stderr, flush=True)
                    print("[停 ] 白名单全部额度耗尽 → 任务停下（退出码 7）。"
                          "恢复后由主控重派；不自动换表外模型。", file=sys.stderr, flush=True)
                    release_tree("额度全挂 → 任务停下")
                    return 7
                print(f"[额度] 探测仍挂（{probe_why}）→ 按白名单顺序换：{model} → {nxt}"
                      "（只换白名单里的，不许跳表外）", file=sys.stderr, flush=True)
                model = nxt
            attempts += 1
            print(f"[续 ] 第 {attempts} 次：带同一会话接着干（原因：额度 {quota['kind']}）",
                  file=sys.stderr, flush=True)
            continue
        # ★ 卡 029 §2.6：防空烧 —— input tokens 超预算 → 止损掐掉（这不是失败），不许自动续跑。
        if args.input_budget and usage_total["input_tokens"] >= args.input_budget:
            reason = (f"预算用尽：input tokens 累计 {usage_total['input_tokens']:,} "
                      f"≥ 预算 {args.input_budget:,} → 止损，不自动续跑")
            with verdict.open("a", encoding="utf-8") as vf:
                vf.write(f"\n★★ 预算判决：{reason}（止损，不是失败）\n")
            print(f"[掐 ] {reason}", file=sys.stderr, flush=True)
            break
        if not should_resume(reason, attempts, args.retry):
            break
        attempts += 1
        print(f"[续 ] 第 {attempts} 次：带同一会话接着干（原因：{reason}）", file=sys.stderr,
              flush=True)

    # ★ 卡 125：工人已收工 / 已被判死 → 还树（`--detach` 的那条路里，跑这一段的正是脱离子进程）。
    #   循环内那几个 `return 7`（额度全挂）由 `atexit` 兜底 —— 任何退出路径都会还一次。
    release_tree("工人收工")

    print(f"[会话] {sid or '（没见到 session_id）'}"
          f"（落盘 {session_file_for(log).name}；续跑：--resume auto）", flush=True)
    lines = log_k.read_text(encoding="utf-8", errors="replace").splitlines()
    timeline, summary = wb_status.parse_events(lines)
    for line in timeline:
        print(line)
    print(f"[摘要] 第 {attempts} 次：回合 {turns_seen(lines)} 个（上限 {max_turns}）；"
          f"工具调用 {summary['tool_calls']} 次；碰过的文件 {summary['files_total']} 个；"
          f"认不出的行 {summary['unknown_events']} 条", flush=True)
    if attempts > 1:
        print(f"[注 ] 这一轮跑了 {attempts} 次（前几次的 log / 判决：同目录 wb-{args.card}.r*.*）",
              flush=True)
    if reason:
        print(f"[掐 ] {reason}", file=sys.stderr, flush=True)
        print(f"     现场（最后一次动作之后的几步）：\n{scene}", file=sys.stderr, flush=True)
        print(f"[复核] 先看现场再决定：python -X utf8 tools/wb_status.py {log_k} --tail 20 --repo",
              file=sys.stderr, flush=True)
        return 6
    print(f"[复核] 主控现在去看报告与 git status：python -X utf8 tools/wb_status.py {log_k} --repo",
          flush=True)
    return 0 if code == 0 else 4


if __name__ == "__main__":
    raise SystemExit(main())
