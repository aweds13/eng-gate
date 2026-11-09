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
  ⑧ ★ 卡 149（T-G249）：**多号 profile**（`--account <名>`）—— 用沙箱 profile 并存两个号、
     **不切号**。那组环境变量的**唯一真源**是仓外工具
     `infra/pool/codebuddy_accounts.py profile env <名>`（这里**只调不抄**）；**不给 `--account`
     时行为逐字不变**（工人继承今天的家目录），**给而拿不到 ⇒ 拒派并点名**（绝不悄悄退回默认号）。

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
import contextlib
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
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pool_accounts  # noqa: E402 —— 账本读数（卡 A345：粘性命中要复查这号还在不在）
import pool_quota  # noqa: E402 —— 额度按钟表算（卡 201）：429 不许凭记忆，按记录时间 vs 现实时间
import wb_status  # noqa: E402 —— 同一个目录，渲染复用状态器（别写第二份）
import wb_watch  # noqa: E402 —— 看守唯一实现（卡 E7）：登记表 / 心跳 / .done 都在那儿
import workbench_bridge  # noqa: E402 —— 工作台状态一处真源（卡 224）：只调它，别在这儿现拼

# ★ 卡 109（T-G206）/ 卡 125（T-G223）：这些判据**只有一份真源**，都在 `tools/pool/` 包里
#   —— 这里只 import、只调用，不另写一份（本地副本各删一处；判据漂一次就会越界 / 串卡）。
#   ★ 卡 125 的来路（GLM-5.3 审查 2.1）：从前只有 MCP 写面与手工 CLI 接守卫，走**默认派活器**
#   `wb_dispatch --execute` 时不变量 ①②③⑤ 全部失效、且对其他窗口不可见（一树两写者不会被咬）。
from pool import account_id as pool_account_id  # noqa: E402 —— 名字↔号 唯一映射（卡 A344）
from pool import guards as pool_guards  # noqa: E402 —— 守卫唯一实现（pool.guards）
from pool import outcomes as pool_outcomes  # noqa: E402 —— 按请求算结局，判据唯一真源（卡 A355）
from pool import registry as pool_registry  # noqa: E402 —— 作业登记唯一实现（pool.registry）
from pool import rpm as pool_rpm  # noqa: E402 —— 每分钟派活闸（卡 A340，magpie 的 MaxRPM）
from pool import sink as pool_sink  # noqa: E402 —— 沉底（卡 A351，magpie sinkOrder）
from pool import sticky as pool_sticky  # noqa: E402 —— 卡粘性（卡 A345，magpie affinity）
from pool import task as pool_task  # noqa: E402 —— 批次预声明 / 状态（卡 E10：--batch）
from pool.jobs import card_artifacts  # noqa: E402 —— 产物定位唯一实现（pool.jobs）
from pool.model_registry import (  # noqa: E402 —— 一层注册表 + 按池分流（卡 166 · T-G266）
    DEFAULT_POOL,
    ModelRegistryError,
    PoolMismatchError,
    PoolNotWiredError,
    UnknownPoolError,
    clean_caller_patterns,
    default_model_for,
    effective_allowed_for,
    get_adapter,
    id_names,
    load_registry,
    minimum_ruleset_text,
    narrow_for_caller,
    resolve_model,
    rotation_chain_for,
)
from pool.models import (  # noqa: E402 —— 外部模型开关（卡 138）+ 号池定位（卡 149）
    SwitchFileError,
    find_pool_dir,
    load_switches,
)
from pool.plan import (  # noqa: E402 —— 队列/冲突域唯一实现（pool.plan）
    BacklogError,
    batch_manifest_path,
    extract_batch_claim,
)
from pool.review import outside_allow  # noqa: E402 —— 白名单越界唯一实现（pool.review）

# ★ 卡 262（T-G383）：队列读取走「先分片后总表」——新卡号带分区前缀时（A261），它登记在
#   `docs/backlog/<分区>.toml` 分片里，只读总表就读不到它的冲突域（守卫会拒派活）。
from wb_plan import load_sharded_backlog  # noqa: E402 —— 分片/总表读取唯一实现（tools/wb_plan.py）

# ★ T-G96：Windows 上派活器自己发起的那些 `subprocess` 不加这个，Windows 11 会把控制台程序
#   转交给**默认终端宿主**（WindowsTerminal.exe -Embedding）→ 任务栏里留下一个**空窗口**、
#   标题还是那个 node.exe 的名字，让人以为「它还在跑」。用户 2026-09-26 实际被它迷惑过。
#   非 Windows 平台这个 kwargs 是空字典（别的平台没有这个概念）。
NO_WINDOW: dict = ({"creationflags": subprocess.CREATE_NO_WINDOW}     # type: ignore[attr-defined]
                   if os.name == "nt" else {})

# ★★ 模型白名单（用户 2026-09-26 明令：「黑名单锁死吧，就是只有白名单里面的模型，名字，
#   带模型的名字，你才能调用」→ **默认拒绝**：不在名单里的模型一律调不动，这是代码里的
#   硬闸门，不是一句叮嘱）。
# ★★ 卡 166（T-G266，2026-10-03 用户拍板「一层统一，按池分流」）：真源收成**一处** =
#   `tools/pool/model-registry.toml`（跨池统一层；CodeBuddy 池条目直接写、码道池引用
#   `infra/pool/models.whitelist.toml`）。本模块**改成读它**，不再硬编码第二份
#   （本仓铁律：最忌第二份真源 —— 凡「两边都写一份」，迟早漂）。
#   ★ 名字 `MODEL_WHITELIST` / `DEFAULT_MODEL` / `ALLOWED_MODELS` 保留成「**读出来的结果**」
#     （模块 `__getattr__` 每次现读，见下）—— 免得动到一堆调用点（pool_mcp / wb_state / 测试）。
#   ★ 默认值**按池声明**（判据 ②）：`--model` 缺省时按当前池取该池默认，**绝不取注册表首项**
#     —— 那正是卡 146 踩的雷（跨池串了默认值）。
#   ★ 真源**找不到/坏掉 ⇒ 拒绝派活**并点名（`ModelRegistryError`）—— **绝不**退回一份
#     内置名单，那就是又造了第二份真源。

# ★★ 2026-10-02 **一次性**模型的入口（**故意不进轮换链**）—— ★ **当天已按用户令清空**。
#   用户原话两句，第二句是**撤回**：
#   ① 「把这些东西再喂给 GLM5.3，注意，我这次要求的是 GLM5.3 不是 Flash …
#      你可以把它列到白名单，但是**我希望是一次性的调用**」；
#   ② ★ **「GLM5.3 用完就撤。」**
#   ⇒ 处置：**机制留着、名额清空** —— 本常量是"一次性放行"的**唯一入口**，
#     要再放行谁就填进来（**仍然不进 429 轮换链**：轮换只走注册表名单）。
#   ★ 当时现场核过的读数（留档）：`--model glm-5.3 -p "只回 OK"` ⇒ `subtype=success`，
#     且 init 事件的 `model` 就是 `glm-5.3`（**没被静默降级**）；那次外部审查已落档
#     （批 `B-ARCH1` / `T-G220`）。
#   ★ **撤掉之后的行为**：`glm-5.3` 回到「默认拒绝」，与任何表外模型**一视同仁**
#     （要再派会被拒，并列出允许集）。
ONE_OFF_MODELS: tuple[str, ...] = ()
#: 一次性授权 = 轮换名单（真源注册表）之外的**加法**（★ **下限仍是注册表名单**）。
#: 闸门查的是「注册表名单 ∪ 一次性授权 ∪ 外部开关文件里打开的」—— 见 `effective_allowed_models()`；
#: 轮换只走注册表名单（一次性授权与开关**都不进轮换链**）。
# ★ 卡 138：外部开关文件里 `true` 的模型**额外放行**（按池读，见 `pool.models.load_switches`）。
#   文件 = `infra/pool/model-switches.toml`（只有用户能改）。
#   **只做加法**（名单是下限、开关不许把名单里的关掉），**不进 429 轮换链**。


def __getattr__(name: str) -> Any:  # noqa: ANN401
    """PEP 562：`MODEL_WHITELIST` / `DEFAULT_MODEL` / `ALLOWED_MODELS` 是「读出来的结果」。

    ★ 每次访问都从注册表**现读**（按 CodeBuddy 池 —— 今天在用的、向后兼容）——
      改注册表 ⇒ 允许集跟着变（这正是单一真源的机器语义）；保留旧名字免得动到一堆调用点。
    ★ 卡 166 判据 ⑥：CodeBuddy 池的条目与卡 166 之前的 `MODEL_WHITELIST` 逐字相同。
    """
    if name == "MODEL_WHITELIST":
        return rotation_chain_for("codebuddy")
    if name == "DEFAULT_MODEL":
        return default_model_for("codebuddy").alias
    if name == "ALLOWED_MODELS":
        return (*rotation_chain_for("codebuddy"), *ONE_OFF_MODELS)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

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
# ★ 卡 A351（T-AG563）：magpie `sinks(on, routing)` 里那个 routing —— 本仓**没有**可配的 routing
#   （magpie 的 rotate / weighted / manual 在 pool 里零命中），调用侧一律传这个常量（= Ordered）。
#   将来有人真加 routing 配置时**改这一个常量**就够，别把字面量散回判据里。
SINK_ROUTING = "order"


NODE_VERSIONS_REL = r".workbuddy\binaries\node\versions"
# ★ 2026-10-12（主控）：这里原来把版本号**写死**成 `22.22.2-3`；机器升到 `22.22.2-6` 之后，
#   整条 CodeBuddy 路**直接断**（干跑报「找不到内置 node」）。改成**解析**：
#   ① 读 `versions/current` —— 它是个**内容为版本名的小文件**（不是目录！）；
#   ② 退而扫 `versions/*/node.exe` 取**最新**（按版本目录名倒序）；
#   ③ 都不行才退回旧的写死路径（宁可报错，也不静默换一个不存在的）。
NODE_REL_FALLBACK = r".workbuddy\binaries\node\versions\22.22.2-3\node.exe"
# ★ 优先用**独立安装**的 CodeBuddy CLI（官方 npm 包，带 TUI、能登录）：
#   WorkBuddy 自带那份是**无头版**（缺 dist/codebuddy.js，`config`/`doctor`/`install` 全废、
#   也没有 `/login` 可敲）—— 2026-09-26 实测，见 复盘/外包-卡表与规矩.md §10。
NPM_CLI_PARTS = ("npm", "node_modules", "@tencent-ai", "codebuddy-code", "bin", "codebuddy")
FALLBACK_CLI_REL = r"workbuddy\resources\app.asar.unpacked\cli\bin\codebuddy"
# 工人要跑 pytest / 脚本，`-y` 不够（实测 `python …` 会被"非交互无法确认"挡回来）
DEFAULT_PERMISSION_MODE = "bypassPermissions"
AUTH_NEEDLE = "Authentication required"
# ★ 卡 154（T-G254）：登录自检三态 + 重试一次 —— 派活器自检分得清「真没登录」与「探失败」。
#   旧口径只看 AUTH_NEEDLE 一个字符串，超时/起不来/非零退出/空输出也被当成「没登录」⇒ 假红三次。
#   · `AUTH_PROBE_FAILED_TAG`：auth_ok 给「探失败」类结果打的前缀标签（供 _classify_probe 认）；
#     用字符串标签而不改 auth_ok 的返回类型 —— 卡 190 已定签名为 (bool, str)，改签名会推回 190。
#   · `AUTH_RETRY_BACKOFF_SECONDS`：第一次「探失败」后退避几秒再试一次（卡 154 规格）。
AUTH_PROBE_FAILED_TAG = "探失败"
AUTH_RETRY_BACKOFF_SECONDS = 5

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
# ★ 卡 167（T-G267）：`--effort` 透传 —— CLI 支持 minimal/low/medium/high/xhigh/max 六档，
#   从前**刻意不传**（两处注释写着「`--effort` 不加 = 保持默认 High」，2026-09-26 的口径）。
#   要跑 MAX 就得显式透传一条下去。★ 缺省**仍不传**（不给 --effort ⇒ 命令行里没有它 =
#   CLI 默认 High，逐字不变）；不许把默认改成显式 high —— 那会改变现有每一笔的行为。
#   ★ 值域以 CLI 2.158.0 的 `--help` 为准（6 档）；CLI 若新增档位，本卡不预判。
EFFORT_LEVELS: tuple[str, ...] = ("minimal", "low", "medium", "high", "xhigh", "max")
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
# ★★ 启动宽限（T-G260b，卡 160 那一笔的域修订）：**零输出 = 「在启动」，不是「卡死」**。
#   为什么必须有（真现场 2026-10-03 18:4x：全量门禁连红两趟，两次都是这一族）：
#     `Popen` 起来到第一行落地之间有**真实延迟**（Python 冷启动 + xdist 满载时可超过 2 秒），
#     而静默计时从**进程起来那一刻**就开始了 ⇒ `--stall-seconds 2` 这种压缩阈值下，
#     看门狗会拿着**空快照**判卡死。现场指纹（逐字）：
#       `判决：卡死：0.0 分钟没有新事件（这一次的阈值 0.0 分钟；` +
#       `没有在飞的调用；历史最长一次调用：没有记录）`
#     ★「**历史最长一次调用：没有记录**」= 判据当时**什么都还没看见** ——
#       它判的不是静默，是还没开始。
#   ★ 口径：**零输出期间**阈值抬到 `max(原阈值, 启动宽限)`；
#     一旦有第一行，立刻回到老口径（一个字没改）。
#   ★ 对生产**无影响**：`STALL_SECONDS = 480 > 60` ⇒ 宽限永远不生效；
#     它只治压缩阈值下的那个真实竞态。
#   ★ 不是「放宽」：零输出**照样会被掐**，只是从「起手就掐」改成「过了宽限再掐」，
#     而且报告会**点名**是零输出（不许含糊成「没有在飞的调用」）。
STARTUP_GRACE_SECONDS = 60
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
    "④ 小步提交到本卡分支 card/<号>（每完成一小步就 commit；卡 192：未提交 = 无保护，"
    "今晚卡 160 丢东西的根因）；门禁不过不许提交；提交信息末尾四行 trailer 一行不许少"
    "（Task/Refs/Ledger/Gates）；★ 不许碰主干、不许 push 主干、不许打 tag；"
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


def _resolve_node(home: Path) -> Path:
    """内置 node 的可执行文件 —— **不写死版本号**（见 `NODE_VERSIONS_REL` 那段的注释）。

    ★ 2026-10-12：机器上的 node 从 `22.22.2-3` 升到 `22.22.2-6` ⇒ 写死的那条路整条断。
    顺序：`versions/current`（指针文件）→ `versions/*/node.exe` 取最新 → 旧的写死路径。
    """
    versions = home / NODE_VERSIONS_REL
    if versions.is_dir():
        marker = versions / "current"
        if marker.is_file():
            try:
                name = marker.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                name = ""
            if name:
                cand = versions / name / "node.exe"
                if cand.is_file():
                    return cand
        cands = sorted((p / "node.exe" for p in versions.iterdir() if p.is_dir()),
                       key=lambda p: p.parent.name, reverse=True)
        for cand in cands:
            if cand.is_file():
                return cand
    return home / NODE_REL_FALLBACK


def paths(cli_override: str | None = None) -> tuple[Path, Path]:
    """（内置 node, CLI 入口）—— 默认优先独立安装的那份，找不到才退回 WorkBuddy 自带的。"""
    home = Path(os.environ.get("USERPROFILE", str(Path.home())))
    node = _resolve_node(home)
    if cli_override:
        return node, Path(cli_override)
    appdata = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
    npm_cli = appdata.joinpath(*NPM_CLI_PARTS)
    if npm_cli.exists():
        return node, npm_cli
    return node, Path("D:/") / FALLBACK_CLI_REL


def switch_open_models(pool: str = DEFAULT_POOL) -> tuple[str, ...]:
    """外部开关文件里**打开**（值为 `true`）的模型 —— **只做加法**、不进 429 轮换链。

    ★ 按池读（卡 166）：`pool` 决定读 `[switch.<pool>]` 段还是 `[switch]` 段（向后兼容）。
    ★ 文件不存在 ⇒ 空（不报错）；文件坏 ⇒ `SwitchFileError` 冒泡（**不许静默当空**）。
    """
    return tuple(name for name, on in load_switches(pool=pool).items() if on)


def effective_allowed_models(pool: str = DEFAULT_POOL) -> tuple[str, ...]:
    """允许集 = 注册表该池条目 ∪ 一次性授权（仅 codebuddy）∪ 开关文件里打开的。

    ★ 名单是**下限**、开关只做**加法**。
    ★ 现算（每次读注册表 + 开关文件），**不**拼进模块常量：开关是**数据**、用户随时能改。
    ★ 轮换链仍只走注册表该池条目（`rotation_chain_for(pool)`）。
    """
    out = list(effective_allowed_for(pool))
    if pool == "codebuddy":
        for name in ONE_OFF_MODELS:
            if name not in out:
                out.append(name)
    return tuple(out)


def model_rejected(model: str, pool: str = DEFAULT_POOL) -> str:
    """模型白名单硬闸门 —— 不在**允许集**里 → 返回拒单理由（在集合里 → 空串）。

    ★ 逐字比较（连大小写 / 连字符都不许含糊）；拒绝必须**零副作用**：不起进程、不建 log、
    不改树。★ `--resume` / `--retry` / `--detach` 全都从 `main()` 过这道闸；续跑必须沿用
    原来那个模型，不许因为「原模型挂了」就换成表外的。
    ★ 允许集 = `effective_allowed_models(pool)`（注册表该池条目 + 一次性授权 + 开关打开的）
    —— **但不是轮换链**：`next_whitelist_model()` 只走注册表该池条目。
    ★ 跨池串用由 `resolve_model(model, pool)` 在 `main()` 里另拒（`PoolMismatchError`）。
    """
    allowed = effective_allowed_models(pool)
    if model in allowed:
        return ""
    return (f"未授权模型，已拒绝派活：{model}\n"
            f"  当前池：{pool}；允许集（注册表 {pool} 池条目 + 一次性授权 ONE_OFF_MODELS"
            f" + 外部开关文件(infra/pool/model-switches.toml) 里打开的；只有用户能改）："
            f"{'、'.join(allowed)}\n"
            "  默认拒绝：既不在名单、也没在开关文件里打开的模型一律调不动"
            "（用户 2026-09-26 令：黑名单锁死）。")


def caller_model_patterns(account: str | None) -> tuple[str, ...]:
    """读**这个账号**的模型白名单（`limits.toml` 的 `[accounts."<id>"].models`；卡 A341 · F34）。

    ★ 数据在**仓外** `D:/repo/infra/pool/limits.toml`（与 F33 共用同一份策略表）；
      路径与 `TF_POOL_LIMITS` 覆盖口径**复用** `pool.limits`（不在这里另立第二套路径/env）。
    ★ 键用 `accounts.toml` 的 **id**（不是 email）。
    ★ **读不到 / 段不存在 / 没写 `models` ⇒ 空元组 ⇒ 不收窄**（照 magpie `Restricted()` `:37`
      「空 = 不受限」）。这条与 `tools/pool_accounts.py:147-151` 的 `approved_models = []`
      （= 这个号**不许派活**）**含义相反，是故意的** —— 见 `clean_caller_patterns()` 的 docstring。
    ★ 写了的条目走 `clean_caller_patterns()` 校验：越界**响亮地**抛 `ModelRegistryError`，
      **不许**静默丢掉越界那条（丢一条 = 悄悄放宽一条）。
    """
    if not account:
        return ()
    # 本文件的 pool 依赖块整块落在 `sys.path.insert` 之后（ruff E402）⇒ 常规写法都要
    # 一条豁免注释；卡 A341 的铁律禁用那类注释，所以这只读一次的 import 放函数内。
    from pool import limits as pool_limits

    table = pool_limits.load_limits(pool_limits.limits_path())
    accounts = table.get("accounts")
    if not isinstance(accounts, dict):
        return ()
    section = accounts.get(account)
    if not isinstance(section, dict):
        return ()
    raw = section.get("models")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ModelRegistryError(
            f"{pool_limits.limits_path()} 里 [accounts.{account!r}].models 必须是数组，"
            f"实际是 {type(raw).__name__} —— 读不懂就**响亮地**失败，不静默当「不收窄」。")
    return clean_caller_patterns(raw)


def caller_model_rejected(
    model: str,
    pool: str = DEFAULT_POOL,
    account: str | None = None,
) -> str:
    """第 ③ 步：caller（账号）白名单**只收窄**的硬闸门（卡 A341 · F34）。

    ★ 顺序固定三步、不许调换（调换会让上一步的拒单文案被吞掉）：
      ①`resolve_model(model, pool)` → ②`model_rejected(model, pool)` → ③本函数。
    ★ 本函数**不改**前两步的判据：它只是在 `effective_allowed_models(pool)` **外面**加一层
      `narrow_for_caller()` —— 而 `narrow_for_caller()` 的返回**必然 ⊆ `allowed`**，所以这里
      不可能放开任何前两步拒掉的模型（反向验证见 `tests/test_pool_model_scope.py` 第 8 条钉子）。
    ★ 两个接入点（`tools/wb_dispatch.py` 派活主路径 / `tools/pool_mcp.py` 干跑路径）**都调本函数**，
      判据只有一份（`tools/pool/__init__.py:1-25` 逐字「它只 import 本包、不在这里重写判据」）。
    ★ 返回空串 = 放行；返回文案 = 退 2 / 回 isError（**零副作用**：不起进程、不建 log、不改树）。
    """
    patterns = caller_model_patterns(account)
    if not patterns:
        return ""
    narrowed = narrow_for_caller(pool, effective_allowed_models(pool), patterns)
    if model in narrowed:
        return ""
    from pool import limits as pool_limits

    shown = "、".join(narrowed) or "（空：等于全禁）"
    return (
        f"该账号的模型白名单不含 {model}（账号 {account}）；它被允许的是：{shown}\n"
        f"  —— 白名单只能**收窄**不能放宽（照 magpie access/models.go:55-70；"
        f"数据在 {pool_limits.limits_path()} 的 [accounts.\"{account}\"].models）"
    )


def next_whitelist_model(model: str, pool: str = DEFAULT_POOL) -> str | None:
    """按该池注册表顺序取下一个（429 三拍「按序换」用）；已经是最后一个 → None（全挂就停）。

    ★ 卡 166：轮换链按池（`rotation_chain_for(pool)`），不许跨池串。
    """
    chain = rotation_chain_for(pool)
    try:
        idx = chain.index(model)
    except ValueError:
        return None
    return chain[idx + 1] if idx + 1 < len(chain) else None


# ---------------------------------------------------------------- 多号 profile（卡 149 · T-G249）
# ★ 为什么有它：用户要「两个号并行派活」—— 不切号、不打扰在跑的活。当晚实测出的隔离法：
#   登录态住在 `<USERPROFILE>\.workbuddy\`；只把 `USERPROFILE` + `HOME` 等**六个**环境变量
#   指到一个沙箱 profile，实例就变成「未登录」，而外面那个号**一字未动**。
# ★ 那六个变量的**唯一真源**是**仓外**工具 `infra/pool/codebuddy_accounts.py`（`profile env <名>`）
#   —— 这里**只调它、只读它的输出**，**绝不**把那份清单抄进本仓（抄一份 = 第二份真源；
#   两份一漂，这里就会让工人**悄悄跑到别的号**上 —— 本仓最恨的"看着成了其实用错号"）。
ACCOUNT_SCRIPT_ENV = "TF_ACCOUNT_SCRIPT"   # ★ 只给测试用：覆盖 profile 工具路径（生产别设）
ACCOUNT_TIMEOUT = 120
#: 卡 A340：每分钟派活闸取锁的上限（秒）—— 锁本身有界，**不许**自旋等（判据 5）。
RPM_LOCK_WAIT = 5.0
#: `KEY=VALUE` 行的合法形状 —— 只收**像变量名**的 key（`export X=…` / `$env:X = …` 自然被滤掉）。
_ENV_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


class AccountError(Exception):
    """拿不到某个 profile 的那组环境变量 —— 点名 profile 与原因（**绝不悄悄退回默认号**）。"""


#: `--account` 的名字在账本里对不上唯一的号（歧义 / 账本读不到）—— 拒派并点名。
#: 类型来自 `pool.account_id`（**只有一份**），这里只是给调用方一个本地名字。
AccountMapError = pool_account_id.AccountMapError


def _account_rows() -> list[dict]:
    """读一次仓外账本，回 `[[account]]` 行；读不到 ⇒ `AccountMapError`（点名 + 原因）。

    ★ 为什么读不到要**拒派**而不是「按原名继续」：`--account` 一旦给了名字，三条闸
      （并发 A339 / 每分钟 A340 / 白名单 A341）都要拿**稳定 id** 查表。账本读不到就没法判
      「这个名字到底是哪个号」—— 按原名继续等于闸照旧不生效，而人以为配了（本卡的病根）。
    """
    try:
        import pool_accounts  # noqa: E402 —— 见 caller_model_patterns 的同款理由（E402）
    except ImportError:  # pragma: no cover —— 从仓根跑（tools/ 不在 sys.path 最前）时走这条
        from tools import pool_accounts  # type: ignore[no-redef]  # noqa: E402
    try:
        path = pool_accounts.find_ledger()
        data = pool_accounts.load_ledger(path)
    except (pool_accounts.LedgerError, OSError) as exc:
        raise AccountMapError(
            f"账号账本读不到，判不出「这个名字是哪个号」⇒ 拒派（不许按原名悄悄派活）：{exc}"
        ) from exc
    rows = data.get("account")
    return list(rows) if isinstance(rows, list) else []


def resolve_account(arg: str | None) -> tuple[str, str]:
    """`--account` 给的名字 → `(稳定 id, 依据)`；空名字 → `("", "")`。

    ★ 卡 A344 判据 2：三条闸（`lanes.toml` / `rpm.toml` / 仓外 `limits.toml`）的键都是
      `infra/pool/accounts.toml` 的**稳定 id**（如 `codebuddy-tongxue3`），而 `--account` 收的是
      `codebuddy_accounts.py` 的 **profile 名**（如 `tongxue3`）。两边不对上，闸就永远不生效 ——
      这个函数是**唯一**把那两个名字对起来的地方（映射逻辑在 `pool.account_id`，只有一份）。
    ★ 歧义 / 账本读不到 ⇒ 抛 `AccountMapError`（调用方退 2 拒派，**不许猜第一条**）。
    ★ 两种情况都说话，但**说的必须是实话**：
      · 三步都不中（依据 == `NO_STABLE_ID`）⇒ stderr 打判据 2 那行逐字文案：
        这个号今天按名字查表，等于闸没生效；
      · ③ 步推断出来了（依据非空但**有** id）⇒ 闸是**生效**的，只能说「按 locator 解析成
        稳定 id「X」」。把生效的闸说成「等于不生效」是同一类谎（本卡要消灭的就是这个）。
    """
    want = str(arg or "").strip()
    if not want:
        return "", ""
    ident, why = pool_account_id.resolve_account_id(want, _account_rows())
    if why == pool_account_id.NO_STABLE_ID:
        # 判据 2 的**逐字**文案：三步都不中 ⇒ 闸按这个名字查表，等于不生效。
        print(f"[账号] profile「{want}」{why} ⇒ 三条闸按这个名字查表（今天等于不生效）",
              file=sys.stderr, flush=True)
    elif why:
        # ③ 步推断出来的（非空依据但**有**稳定 id）⇒ 闸照旧生效，别吓人。
        #   ★ 判据 2 那行只属于「没有稳定 id」那一种，不许拿来套这一种：
        #     把生效的闸说成「等于不生效」是同一类谎（本卡要消灭的就是「说的和做的不一致」）。
        print(f"[账号] profile「{want}」按{why}解析成稳定 id「{ident}」⇒ 三条闸按这个 id 查表",
              file=sys.stderr, flush=True)
    return ident, why


def account_script_path(root: Path | None = None) -> Path | None:
    """号池工具 `codebuddy_accounts.py` 的位置：`TF_ACCOUNT_SCRIPT` 覆盖 > 号池目录里那份。

    ★ 号池目录用 `pool.models.find_pool_dir`（**唯一实现**）定位 —— 那份工具**不在本仓**
      （跨项目复用，在 `jelly_ware/infra/pool/`），写死相对层级会漂。找不到 → `None`。
    """
    override = os.environ.get(ACCOUNT_SCRIPT_ENV, "").strip()
    if override:
        return Path(override)
    pool = find_pool_dir(root or ROOT)
    return None if pool is None else pool / "codebuddy_accounts.py"


def _run_account_script(script: Path, argv: list[str]) -> subprocess.CompletedProcess[str]:
    """调号池工具（`python -X utf8 <脚本> …`）—— 不弹窗、有超时；**只读它的输出**。"""
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(script), *argv],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=ACCOUNT_TIMEOUT, **NO_WINDOW,
    )


def available_profiles(script: Path) -> list[str]:
    """可用 profile 名（**只在拒绝派活时**取，best-effort）—— 读号池工具 `list` 的**输出**。

    取不到（跑不了 / 输出认不出）→ 空列表：**拒绝照样发生**，只是少一行提示，**不因此放宽**。
    """
    try:
        done = _run_account_script(script, ["list"])
    except (OSError, subprocess.TimeoutExpired):
        return []
    names: list[str] = []
    for line in (done.stdout or "").splitlines():
        hit = re.match(r"^\s*·\s*(.+?)（\d+\s*件）\s*$", line)
        if hit:
            names.append(hit.group(1).strip())
    return names


def account_env(name: str) -> dict[str, str]:
    """跑 `codebuddy_accounts.py profile env <名>`，把输出解析成**环境变量字典**。

    ★ **调，不是抄**：本函数**不知道**是哪六个变量 —— 凡 `KEY=VALUE` 行都收（`#` 注释与非
      变量名行丢掉）。于是"清单"只有一份真源（那份仓外工具），它改了这里跟着改。
    ★ **profile 不存在**：`profile env` **不查存在性**（实测：不存在的名字照样回 0 并打印路径）
      ⇒ 存在性用**那份工具自己**的 `profile check`（退出码 2 = 没有这个 profile）判，
      仍不抄任何清单。
    ★ **拿不到就抛 `AccountError`**（点名 profile + 可用清单），**绝不**回空 dict 让调用方
      悄悄退回默认号 —— 那会让工人跑到**别的号**上。
    """
    script = account_script_path()
    if script is None or not script.is_file():
        raise AccountError(f"找不到号池工具 codebuddy_accounts.py（{script}）→ 拒绝派活"
                           f"（不许悄悄用默认号）")
    try:
        checked = _run_account_script(script, ["profile", "check", name])
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AccountError(f"核 profile「{name}」失败（跑不了号池工具）：{exc}") from exc
    if checked.returncode == 2:                     # 那份工具自己判：没有这个 profile
        avail = available_profiles(script)
        tail = f"；可用 profile：{'、'.join(avail)}" if avail else ""
        raise AccountError(f"没有这个 profile：「{name}」（`profile check` 退出码 2）"
                           f"→ 拒绝派活（不许悄悄退回默认号）{tail}")
    if checked.returncode != 0:
        blob = wb_status._clip((checked.stderr or "") + (checked.stdout or ""), 200)
        raise AccountError(f"核 profile「{name}」失败（退出码 {checked.returncode}）：{blob}")
    try:
        done = _run_account_script(script, ["profile", "env", name])
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AccountError(f"取 profile「{name}」的环境变量失败：{exc}") from exc
    if done.returncode != 0:
        blob = wb_status._clip((done.stderr or "") + (done.stdout or ""), 200)
        raise AccountError(f"取 profile「{name}」的环境变量失败"
                           f"（退出码 {done.returncode}）：{blob}")
    out: dict[str, str] = {}
    for line in (done.stdout or "").splitlines():
        hit = _ENV_LINE_RE.match(line.strip())
        if hit:
            val = hit.group(2).strip()
            # ★ 卡 190（T-G290）F4：值里带引号 = 真源形状漂移（如 KEY="v"），静默收会
            #   连引号一起当值用 → 响亮拒（不许静默收错值）。廉价健全性：路径里不会有引号。
            #   ★ F5 并入：④b 清单钉是文本存在性（防抄有效、不验行为）；这条验**行为**。
            if '"' in val or "'" in val:
                raise AccountError(f"profile「{name}」的 {hit.group(1)}={val!r} 值里带引号"
                                   f" → 解析形状漂移，拒派（不许静默收错值）")
            out[hit.group(1)] = val
    if not out:
        raise AccountError(f"profile「{name}」没输出任何环境变量（`profile env` 回话认不出）"
                           f"→ 拒绝派活（不许悄悄退回默认号）")
    return out


def ledger_accounts() -> list[dict]:
    """账本里的 `[[account]]` 原始行（粘性要判「这号还在不在 / 还 active 不 active」）。

    ★ 为什么不用 `pool_accounts.list_rows()`：它把 `quota` 洗成人读的文本，拿不到
      `used_percent` —— 而粘性的 `spent` 判据正要用它。
    ★ 判不了（账本找不到 / 读坏了 / 形状不对）⇒ **空表**：粘性 fail-open，判不了就当没有，
      **绝不**因此拦派活（与 `pool.route.apply_order()` 同一条纪律）。
    ★★ **与 `_account_rows()`（卡 A344）故意相反，别合并**：那个是 **fail-closed** ——
      `--account` 给了名字却判不出是哪个号，就退 2 拒派（闸按名字查表等于没生效，不许装作派得动）。
      这里是 **fail-open** —— 粘性是省钱的优化，账本读不到只是「这次不粘」，**不许**把一句
      本来能跑的派活变成退 2。两边同名函数看着像重复，语义正好相反，合并就会悄悄改掉
      其中一张卡的判据（A345 判据 7 / A344 判据 2）。
    """
    try:
        data = pool_accounts.load_ledger(pool_accounts.find_ledger())
    except (pool_accounts.LedgerError, OSError, ValueError):
        return []
    rows = data.get("account")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _account_env_probe(env: dict[str, str], expected: dict[str, str]) -> tuple[bool, str]:
    """★ 卡 190（T-G290）F2 子进程侧读数 —— 不再"自己打印自己"。

    用 `env` 起一个极小子进程，让它读**自己的**环境回话：`expected` 里每一项
    `KEY=VALUE` 都在子进程环境里对得上 ⇒ 接缝（account_env 输出 → main 合成 → Popen）
    在"真输出 + 真子进程"组合下成立。对不上 ⇒ 拒派（接缝断了，不许放行）。
    ★ 廉价：一个 `python -c`，30s 超时；只在给了 `--account` 时跑。
    """
    pairs = [f"{k}={v}" for k, v in expected.items()]
    check = subprocess.run(
        [sys.executable, "-X", "utf8", "-c",
         "import os, sys\n"
         "bad = 0\n"
         "for a in sys.argv[1:]:\n"
         "    k, v = a.split('=', 1)\n"
         "    if os.environ.get(k) != v:\n"
         "        bad = 1\n"
         "sys.exit(bad)\n",
         *pairs],
        env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=30, **NO_WINDOW,
    )
    if check.returncode == 0:
        return True, f"子进程侧读数通过（{len(expected)} 项变量全到位）"
    blob = wb_status._clip((check.stderr or "") + (check.stdout or ""), 200)
    return False, (f"账号环境注入自检失败：子进程没拿到 profile 的变量"
                   f"（退出码 {check.returncode}）：{blob} → 拒派（接缝断了）")


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


def auth_ok(node: Path, cli: Path, timeout: int = 180, *,
            env: dict[str, str] | None = None,
            model: str | None = None) -> tuple[bool, str]:
    """真发一条极短请求 —— 登录没通就当场认出来（别把一轮白等当成"工人在想"）。

    ★ 卡 190（T-G290）F1 两半：探针必须打在「将要用的那个「号 × 模型」组合」上 ——
      · `env`（给了 --account 时 = 合成后的 profile 环境）⇒ 探针用**那个号**发，不是默认号；
      · `model`（给了 --account 时 = 派活要用的 --model）⇒ 探针判**那个模型桶**，不是 CLI 默认。
      两半都不给（默认 None）⇒ 行为逐字不变（父进程环境、不带 --model）。
    ★ 卡 154（T-G254）：False 的两类结果**分开打标签**（让 _classify_probe 能分三态）——
      · NEEDLE 命中 → 「登录没通（Authentication required）」（NEEDS_LOGIN，进程正常退出）
      · 超时/起不来/非零退出/空输出 → 「探失败：…」（INCONCLUSIVE —— 不许当「没登录」）
      重试与两条出路提示在 `preflight_auth`；本函数只发**一次**探针。
    """
    argv = [str(node), str(cli), "-p", "只回复四个字：连接成功", "--output-format", "text"]
    if model:
        argv += ["--model", model]
    argv += ["--no-session-persistence", "-y"]
    try:
        done = subprocess.run(
            argv,
            cwd=str(ROOT), env=env, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, **NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return False, f"{AUTH_PROBE_FAILED_TAG}：探针超时（{timeout}s）—— 可能是机器换页/CLI 起不来"
    except OSError as exc:
        return False, f"{AUTH_PROBE_FAILED_TAG}：探针起不来（{exc}）"
    body = f"{done.stdout or ''}\n{done.stderr or ''}"
    if AUTH_NEEDLE in body:
        return False, "登录没通（Authentication required）→ 先在 TUI 里敲 /login（T-G80）"
    if "连接成功" in body:
        return True, "登录自检通过"
    # ★ 卡 154：剩下都是「探失败」—— 非零退出 / 空输出 / 没有可判读的结论 —— 不许当「没登录」
    return False, (f"{AUTH_PROBE_FAILED_TAG}：自检没拿到预期回话（退出码 {done.returncode}）："
                   + wb_status._clip(body, 200))


class AuthState(StrEnum):
    """登录自检的三态（卡 154 / T-G254）：分得清「真没登录」与「探失败」。

    · OK               —— 拿到会话 → 放行；
    · NEEDS_LOGIN      —— 明确拿到 Authentication required 且进程正常退出 → 拦 + 提示 /login；
    · INCONCLUSIVE     —— 超时/非零退出/空输出/起不来 → 不许当「没登录」，重试一次；
                          两次都得不出来 ⇒ 给两条出路（/login 或 --no-preflight）。
    """

    OK = "ok"
    NEEDS_LOGIN = "needs_login"
    INCONCLUSIVE = "inconclusive"


def _classify_probe(ok: bool, why: str) -> AuthState:
    """把 `auth_ok` 的 (bool, why) 归到三态之一（卡 154）。

    · True → OK；
    · False 且 why 含 `AUTH_PROBE_FAILED_TAG` → INCONCLUSIVE（探本身失败了）；
    · False 且 why 不含该标签 → NEEDS_LOGIN（保留旧语义：False 默认 = 没登录 ——
      卡 190 的桩与 test:199 都按这个签名 stub，不在 why 里打「探失败」标签）。
    """
    if ok:
        return AuthState.OK
    if AUTH_PROBE_FAILED_TAG in why:
        return AuthState.INCONCLUSIVE
    return AuthState.NEEDS_LOGIN


def preflight_auth(node: Path, cli: Path, *, env: dict[str, str] | None = None,
                   model: str | None = None, timeout: int = 180,
                   retry_backoff: float | None = None) -> tuple[AuthState, str]:
    """登录自检（三态 + 重试一次）—— 卡 154（T-G254）。

    旧口径只看 `AUTH_NEEDLE` 一个字符串，超时/起不来/非零退出也被当成「没登录」⇒ 当晚假红三次
    （每次都：不派活 + 白等 + 换号重试 + 白花额度）。本函数把「真没登录」与「探失败」分开：

    · **登录有效**（拿到会话）⇒ 放行；
    · **真没登录**（明确拿到 `Authentication required` 且进程正常退出）⇒ 拦，提示去 `/login`；
    · **探失败**（超时/非零退出/空输出/起不来）⇒ **不许当「没登录」** ⇒ 退避几秒**重试一次**；
      两次都得不出来 ⇒ 明确告诉人「**要么去 `/login`，要么用 `--no-preflight` 自己担**」，
      **不许静默按「没登录」处理**。

    ★ 不改任何放行判据（内存闸 / 白名单 / 树 / 域 / 锁 / 基点一个都不松）—— 本函数只判登录自检。
    ★ 不真发请求去打真实号池（钉子用桩，别花额度、别碰真登录态）—— 由 test_wb_dispatch 保证。
    ★ `retry_backoff=None` 时用模块常量 `AUTH_RETRY_BACKOFF_SECONDS`（测试可置零加速）。
    """
    backoff = AUTH_RETRY_BACKOFF_SECONDS if retry_backoff is None else retry_backoff
    ok, why = auth_ok(node, cli, timeout=timeout, env=env, model=model)
    state = _classify_probe(ok, why)
    if state is AuthState.OK or state is AuthState.NEEDS_LOGIN:
        # ★ 确定的态不重试：拿到会话就放行；明确没登录就拦 —— 重试只会白等 + 漂移结论。
        return state, why
    # INCONCLUSIVE → 退避几秒重试一次（★ 只对「探失败」续，不对「真没登录」续 —— 那是确定的）
    if backoff > 0:
        time.sleep(backoff)
    ok2, why2 = auth_ok(node, cli, timeout=timeout, env=env, model=model)
    state2 = _classify_probe(ok2, why2)
    if state2 is AuthState.OK:
        return AuthState.OK, why2
    if state2 is AuthState.NEEDS_LOGIN:
        return AuthState.NEEDS_LOGIN, why2
    # 两次都探失败 → 不许静默按「没登录」处理，明确给两条出路
    return AuthState.INCONCLUSIVE, (
        "登录自检两次都没能得出结论（探失败：超时 / 非零退出 / 空输出 / 起不来）。"
        "要么去 TUI 敲 /login 重登，要么用 --no-preflight 自己担（跳过自检直接派）。"
        f"第一次：{why}；第二次：{why2}"
    )


def prompt_path(p: str, worker_cwd: Path | None, *, writable: bool = False) -> str:
    """★ T-G204：给了 `--cwd` 就把路径转成**绝对**（不给时**逐字不变**）。

    为什么：`--cwd` 让**工人进程的 cwd** 变成卡树，而切片与规格是**仓库相对**路径
    （`gates/diag/…` 只存在于主仓）⇒ 相对写法会把工人指到一个**不存在的路径**上，
    它只能自己满盘找（卡 106 的工人就是这么找到的 —— 那是运气，不是设计）。

    ★ 卡 194（T-G294）：**两类路径不许一刀切** ——
      · `writable=False`（默认，**只读临时件**：规格 / 切片）⇒ 解析到 **主仓 `ROOT`**
        （它们只存在于主仓，卡树里没有）；
      · `writable=True`（**工人要改的**：白名单 / 域里的仓库相对路径）⇒ 解析到 **卡树
        `worker_cwd`**（工人顺着绝对路径改时落到它自己的树，不窜到主树 —— 卡 151 现场就是
        一刀切到主仓，工人报成功却把改动落进主树，挡住 ff 合流）。
    不给 `worker_cwd` 时两类都逐字不变（向后兼容）。
    """
    if not p or worker_cwd is None:
        return p
    q = Path(p)
    if q.is_absolute():
        return p
    base = worker_cwd if writable else ROOT
    return str((base / q).resolve())


def domain_path_hint(card: str, worker_cwd: Path | None) -> str:
    """★ 卡 194（T-G294）：给了 `--cwd` 时，把这张卡的**域文件**（= 白名单）解析成**卡树绝对路径**
    塞进开场白 —— 工人顺着绝对路径改时落到它自己的树，不窜到主树。

    为什么（现场）：`--cwd` 只管**进程起点**，管不住工人从规格 / 切片里读到的白名单相对路径
    被它**相对于主仓**解析（规格本身在主仓）⇒ 改到主树。这里**显式**把域文件写成卡树绝对路径，
    覆盖规格里的相对写法。★ 不给 `--cwd` ⇒ 空串（逐字不变）；域查不到 ⇒ 空串
    （判据归守卫，不在这儿拒）。
    """
    if worker_cwd is None:
        return ""
    files, why = queue_files(card)
    if why or not files:
        return ""
    paths = [prompt_path(f, worker_cwd, writable=True) for f in files]
    return ("★ 你要改的文件在卡树（--cwd）下 —— 用这些**绝对路径**改，别改主仓：\n"
            + "\n".join(f"  {p}" for p in paths) + "\n")


def workbench_brief_text(card: str, worker_cwd: Path | None) -> str:
    """★ 卡 224（T-G338）：把工作台状态（我在哪张卡 / 谁在飞 / 我的域有没有被别人占 /
    该看哪个产物）拼进开场白 —— 就一段文字，数据只来自 `tools/workbench_bridge.py`
    （它是**唯一真源**，这里**不**自己再读一遍队列 / 租约 / 判决 —— 一份读数）。

    ★ **只加不改**：不给 `--cwd`（从主树跑 / 向后兼容）⇒ 回空串，开场白**逐字不变**（卡 166）；
      给了 `--cwd`（工人在卡树里干活）⇒ 追加这段（工人看到的东西**只多不少**，不会变差）。
    ★ 树标签用 `worker_tree_label(...)`（与守卫**同一把尺子**）；算不出主树 ⇒ 退空串
      （**不新增失败**：这段是加料，不是判据）。
    """
    if worker_cwd is None:
        return ""
    try:
        main_root = pool_registry.main_tree_root()
        tree = worker_tree_label(worker_cwd, main_root)
    except pool_registry.RegistryError:
        tree = ""
    return workbench_bridge.bridge_text(card=card, tree=tree, root=ROOT)


def build_command(node: Path, cli: Path, card: str, spec: str, model: str,
                  permission_mode: str = DEFAULT_PERMISSION_MODE, *,
                  max_turns: int = DEFAULT_MAX_TURNS_WRITE,
                  autocompact: str = DEFAULT_AUTOCOMPACT,
                  lean: bool = False, brief: str = "",
                  effort: str | None = None,
                  domain_hint: str = "",
                  workbench_text: str = "") -> list[str]:
    prompt = (LEAN_OPENING.format(brief=brief, spec=spec, card=card) if lean
              else OPENING.format(spec=spec, card=card))
    if domain_hint:
        prompt = domain_hint + prompt
    # ★ 卡 166 追加要求 2：最小规矩集拼进提示（换池不许改变工人看到的东西）。
    prompt = prompt + "\n" + minimum_ruleset_text()
    # ★ 卡 224（T-G338）：工作台状态注入 —— **只加不改**：空串 = 逐字不变；给了就**追加在末尾**
    #   ⇒ 改动前的提示词是改动后的**前缀**（删不掉、改不动，工人看到的东西只多不少）。
    if workbench_text:
        prompt = prompt + "\n" + workbench_text
    cmd = [
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
    # ★ 卡 167（T-G267）：显式给 --effort 才透传；不给 = 不传 = CLI 默认 High（逐字不变）
    if effort:
        cmd += ["--effort", effort]
    return cmd


def resume_command(node: Path, cli: Path, session_id: str, prompt: str, model: str,
                   permission_mode: str = DEFAULT_PERMISSION_MODE, *,
                   max_turns: int = DEFAULT_MAX_TURNS_WRITE,
                   autocompact: str = DEFAULT_AUTOCOMPACT,
                   effort: str | None = None) -> list[str]:
    """带着**同一个会话**接着跑（`--resume <sessionId>`）—— 中断不等于白干。

    实测（T-G90 探针）：首轮 `-p 「请记住一个数字：42」` → 回「记下了」；
    `--resume <同一个 id>` 再问「我刚才让你记的数字是多少」→ 回 **42**，且 session_id 没变。
    """
    cmd = [
        str(node), str(cli), "--resume", session_id, "-p", prompt,
        "--model", model, "--output-format", "stream-json",
        "--permission-mode", permission_mode,
        "--max-turns", str(max_turns),
        "--autocompact", autocompact,
        "--append-system-prompt", IRON_RULES,
        "-y",
    ]
    # ★ 卡 167（T-G267）：续跑也要带 --effort，否则续跑那一轮掉回 High
    if effort:
        cmd += ["--effort", effort]
    return cmd


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


def _spawn(argv: list[str], log_path: Path) -> int:
    """把**任何**后台活扔出去单独跑（脱离窗口）：返回 pid，输出落到 `log_path`。

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


def spawn_detached(argv: list[str], log_path: Path) -> int:
    """把派活**扔出去单独跑**（我的窗口关了它照样跑）：返回子进程 pid，输出落到 `log_path`。"""
    return _spawn(argv, log_path)


# ★ 卡 A297（T-AG411）· 收工回推通道：`--detach` 派活成功后自动起 `wb_notify.py --daemon`，
#   把「收工」变成落盘事件（不靠人记着轮询）。失败只告警，**不让派活失败**。
def _notify_daemon_alive(pid_path: Path) -> bool:
    """`wb_notify.pid` 里那个 pid 还在不在、是不是一个 python 进程（用 tasklist/ps 判映像名）。

    ★ 不许盲杀 / 不许盲起：pid 文件在但进程已死 ⇒ 返回 False（可重新起）；
      pid 活但映像名不是 python（pid 被别的进程复用）⇒ 也返回 False。
    ★ `tasklist` / `ps` 是子进程 —— 必须带 `NO_WINDOW`（卡 148 铁律）。
    """
    if not pid_path.is_file():
        return False
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        # tasklist /FI "PID eq 1234" /FO CSV /NH  →  "python.exe","1234",...
        try:
            # text=True 必给 encoding：云机 cp936 解码中文会崩，本机 utf-8 看不出来。
            # errors="replace"：宁可拿到带替换符的中文，也不要整条炸掉。
            done = subprocess.run(  # noqa: S603 —— 命令本地拼好，不是外部输入
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5,
                                encoding="utf-8", errors="replace", **NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        if done.returncode != 0:
            return False
        line = (done.stdout or "").strip().splitlines()
        return bool(line) and "python" in line[0].lower() and str(pid) in line[0]
    # POSIX：ps -p <pid> -o comm=
    try:
        # text=True 必给 encoding：云机 cp936 解码中文会崩，本机 utf-8 看不出来。
        # errors="replace"：宁可拿到带替换符的中文，也不要整条炸掉。
        done = subprocess.run(  # noqa: S603 —— 命令本地拼好，不是外部输入
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True, text=True, timeout=5,
                            encoding="utf-8", errors="replace", **NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if done.returncode != 0:
        return False
    return "python" in (done.stdout or "").lower()


def ensure_notify_daemon(root: Path) -> None:
    """派活成功后起 `wb_notify.py --daemon`（若没起）—— 收工自动落盘 + 面板可见。

    ★ 若 `wb_notify.pid` 的进程已活 ⇒ 跳过（不重复起）；否则用 `spawn_detached` 起一个
      脱离窗口的守护进程（活过父进程）。失败只打印告警，**不让派活失败**（卡 A297 规格）。
    """
    diag = root / "gates" / "diag"
    pid_path = diag / "wb_notify.pid"
    if _notify_daemon_alive(pid_path):
        return
    log_path = diag / "wb_notify.log"
    argv = [sys.executable, "-X", "utf8", str(root / "tools" / "wb_notify.py"),
            "--daemon", "--interval", "60"]
    try:
        spawn_detached(argv, log_path)
    except OSError as exc:
        # ★ 守护进程起不来不能让派活失败 —— 只告警（卡 A297 规格）。
        print(f"[告警] wb_notify 守护进程没起来（不影响派活）：{exc}", file=sys.stderr, flush=True)


# ★ 卡 E7（T-AG453）· 派活即看守：`--execute` 成功起工人后**自动**挂一份看守 ——
#   「等通知」不再退化成「轮询」（今天第一批 5 张卡是靠每 2 分钟敲 `--status` 才发现的）。
#   看守不猜成功：只读 `gates/diag/wb-<卡>.verdict.txt`，出判决才写 `wb-<卡>.done`。
WATCH_INTERVAL = 30.0      # 看守查一次文件（卡 E7：这批最多 10 张卡，单看守成本可忽略）


def watch_log_for(card: str) -> Path:
    """看守自己的 log（和工人的 `wb-<卡>.jsonl` 分开放，免得混成一锅）。"""
    return ROOT / "gates" / "diag" / f"watch-{card}.log"


def watch_horizon(timeout: int, retries: int) -> float:
    """看守的硬超时：工人的**每一轮**都可能跑到 `--timeout`，被中断还自动续 `retries` 次。

    ★ 看守的期限必须**盖过所有这些轮**（再留 10 分钟收尾），否则它会在工人正续跑时
      提前写一条 `state:"timeout"` 然后退出 —— 那是「假超时」，比不挂看守更误导人。
    """
    return float(timeout) * (max(0, retries) + 1) + 600.0


def spawn_watcher(card: str, *, mode: str, timeout: float,
                  interval: float = WATCH_INTERVAL,
                  since: float | None = None) -> int | None:
    """起一份**后台看守**（`wb_watch.py`），盯这张卡直到出判决。

    ★ 脚本跟着 `ROOT/tools/` 走；没有那份脚本（测试沙箱 / 独立拷贝的树）⇒ **跳过并说明**，
      不让派活失败（看守是锦上添花，不是派活的前提）。
    ★ `since` = 这一轮开跑的时刻（默认现在）：比它旧的判决 / 日志一律不认 ——
      否则 `--force` 重派时，上一轮那份静默日志会被新看守读成「判死」（假死比不挂更误导）。
    ★ 走 `_spawn` 而不是 `spawn_detached`：后者被调用方与测试当成「把派活扔出去」的唯一入口
      （`tests/test_wb_watch.py` 钉着 detach 只扔一次），看守不该混进那个计数。
    """
    script = ROOT / "tools" / "wb_watch.py"
    if not script.is_file():
        print(f"[告警] 没找到看守脚本 {script} ⇒ 这张卡**没有**看守（完工不会自动通知）",
              file=sys.stderr, flush=True)
        return None
    argv = [sys.executable, "-X", "utf8", "-u", str(script),
            "--cards", card, "--root", str(ROOT), "--mode", mode,
            "--write-done", "--timeout", str(timeout), "--interval", str(interval),
            "--since", str(time.time() if since is None else since)]
    return _spawn(argv, watch_log_for(card))


def ensure_watch(card: str, *, mode: str = "one", timeout: float = DEFAULT_TIMEOUT) -> str:
    """派活成功后挂看守；返回**要打印的那句话**（主控据此就知道「谁在替我等收工」）。

    · `one`（默认）= 这张卡一个看守，出判决就写 `.done` + 通知并退出（推送粒度最细）。
    · `shared` = 全局一份合用看守：引用计数 +1 / 出判决 -1 / 归 0 写 `batch-done`；
      已有活着的合用看守 ⇒ **只登记、不再起进程**。
    ★ 计数和心跳全在 `gates/diag/watch-registry.json`（写入方是 `wb_watch`；派活器只登记，
      不碰心跳 —— 派活器写心跳等于冒充「看守还活着」）。
    ★ `timeout` 要用 `watch_horizon()` 算出来的**看守期限**，别直接传工人的 `--timeout`。
    """
    if mode == "one":
        pid = spawn_watcher(card, mode=mode, timeout=timeout, since=time.time())
        if pid is None:
            return "[看 ] 看守没起来（见上面的告警）—— 完工不会自动通知，请自己轮询"
        return (f"[看 ] 看守已起（pid {pid}，one 专属）：出判决自动写 "
                f"gates/diag/wb-{card}.done 并追加 gates/diag/notifications.jsonl；退出码随判决")
    cutoff = time.time()          # 这一轮的开跑时刻：比它旧的判决 / 日志不认（见 spawn_watcher）
    # ---- shared：先看上一个看守是不是死了（卡 E7 判据 8）
    # ★ 「还活着吗」用小窗口（几分钟），**不是**看守的硬期限（那要盖过工人的全部轮次）。
    stale = wb_watch.registry_stale(ROOT, timeout=wb_watch.ALIVE_WINDOW)
    if stale is not None:
        wb_watch.write_stale_event(ROOT, stale)
        print(f"[告警] 上一个合用看守心跳停在 {stale['heartbeat'] or '（空）'}"
              f"（超过 {wb_watch.ALIVE_WINDOW:.0f}s 没心跳）—— "
              f"还没判决的卡：{'、'.join(stale['cards'])}；已写 watcher-stale 事件，重起一份。",
              file=sys.stderr, flush=True)
        wb_watch.rebuild_registry(ROOT, pid=None, heartbeat="")
    if wb_watch.watcher_alive(ROOT, timeout=wb_watch.ALIVE_WINDOW):
        reg = wb_watch.register_cards(ROOT, [card], since=cutoff)
        return (f"[看 ] 已挂到现有合用看守（refcount={reg.get('refcount')}；出判决减 1，"
                "归 0 写 batch-done）")
    reg = wb_watch.register_cards(ROOT, [card], since=cutoff)
    pid = spawn_watcher(card, mode=mode, timeout=timeout, since=cutoff)
    if pid is None:
        return "[看 ] 合用看守没起来（见上面的告警）—— 完工不会自动通知，请自己轮询"
    return (f"[看 ] 合用看守已起（pid {pid}，refcount={reg.get('refcount')}）："
            "逐张写 gates/diag/wb-<卡>.done，计数归 0 写 batch-done")


# ---------------------------------------------------------------- 看守的开关提示
def no_watch_notice() -> str:
    """`--no-watch` 的原话 —— **明说，不静默**（卡 E7 判据 3 逐字钉着这句）。"""
    return "已关看守：完工后请自己轮询"


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
        lines = wb_status.read_log_lines(newest)
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

def archive_stale_artifacts(card: str) -> tuple[list[str], list[str]]:
    """**真开跑那一刻**，把这张卡的旧判决 / 摘要**改名归档**（加 `.stale` 后缀）—— 只归档、不删。

    为什么（主控 2026-09-26 真撞到）：一次被前置检查拒绝的派活会留下「前置检查没过 → 没派活」
    的判决；同一张卡随后真跑时它不清掉 → `--status` 半小时里一直显示「没派活」，而工人其实在跑。
    ★ 归档不删：`--force` 才让覆盖那条规矩的精神是**留证据**，归档兼容它、删除不兼容。
    ★ dry-run 不许归档（没真跑）—— 调用点在 `main()` 的 dry-run 返回**之后**。
    ★ 用 `card_artifacts`（精确匹配）—— 别把卡 421 的判决归档到卡 42 头上（§2.9 同源）。

    ★ 卡 156（T-G256）：Windows 上 `Path.rename` 在**目标已存在**时抛 `FileExistsError`，旧写法
      用 `except OSError: continue` 静默吞掉 ⇒ **第二次以后的归档全失败**，旧判决留在原地冒充
      当前状态。修法：目标已存在 ⇒ 用带时间戳的**唯一名**（`wb-<卡>.verdict.<ts>.stale`），
      既不丢历史归档又不撞；失败 ⇒ 收进 `failed` 让调用方**出声**，不许让"失败"与"没有旧件"
      长得一样。
    """
    diag = ROOT / "gates" / "diag"
    moved: list[str] = []
    failed: list[str] = []
    for suffix in (".verdict.txt", ".report.md"):
        for p in card_artifacts(diag, card, suffix):
            target = p.with_name(p.name + ".stale")
            if target.exists():
                # ★ 卡 156：撞已存在 ⇒ 唯一名（不丢历史归档、也不静默失败）
                ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                target = p.with_name(f"{p.stem}.{ts}.stale")
            try:
                p.rename(target)
                moved.append(target.name)
            except OSError as exc:
                # ★ 归档失败不许挡住真跑，但**必须出声**（留在原地会冒充当前状态 —— 卡 156 真因）
                failed.append(f"{p.name}：{exc}")
    return moved, failed


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
                      usage: dict[str, int], code: int, reason: str,
                      tries: int = 1, handed_on: bool = False, stop: str = "") -> Path:
    """每张卡每轮跑完（无论成败）往 `gates/diag/wb-usage.jsonl` 追加一行用量（只数 token，
    **不做金额换算**——用户明说「不用太担心怎么计价」）。该文件在 gitignore 里，不脏树。

    ★ 卡 A355：多三列**结局**（`tries` / `handed_on` / `stop`）——「每行一轮」不变，结局判据
    只看 `tools/pool/outcomes.py` 那一份（`count_requests()`），这里只负责**写一次**。
    ★ 三个新参数**全有默认值**：`usage_in()` 的 docstring 逐字承诺本函数的签名与
      `usage_summary()` 的行为一个字节都不动 —— 老调用点照旧一行不用改。
    ★ `handed_on` 必须由**写侧一次算好**（`row` 只写一次，**不许**回头补写第二行）：判据是
      「这一轮失败 **且** 之后确实会续」—— 缺任一条都是把「交出去了」写宽或写窄。
    ★ `stop` 今天**没有写方**（pool 派的是 CLI，拿不到上游自报的结束原因）⇒ 恒 `""`，
      而 `""` 正是「上游没报」的正确取值（**不许**写 `"none"` / `"unknown"` 顶替）。
    """
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
        # ★ 卡 A355 的三个结局列（口径见 `tools/pool/outcomes.py`）。三个 `tier_*`
        #   今天在 pool 侧没有任何输入面 ⇒ **不写**空键（读方按缺键读成 `""`，不造假）。
        "tries": tries, "handed_on": handed_on, "stop": stop,
    }
    with path.open("a", encoding="utf-8") as out:
        out.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def usage_summary(card: str) -> str:
    """`--status` 的用量一行：这张卡的 + 全部卡的累计（读不出来 / 没记录 → 空串，不显示）。"""
    path = ROOT / "gates" / "diag" / "wb-usage.jsonl"
    try:
        rows = [json.loads(ln) for ln in wb_status.read_log_lines(path) if ln.strip()]
    except (OSError, wb_status.UnknownLogEncodingError, json.JSONDecodeError):
        return ""
    rows = [r for r in rows if isinstance(r, dict)]
    mine = [r for r in rows if r.get("卡") == card]
    if not mine:
        return ""
    def total(items: list[dict], field: str) -> int:
        return sum(int(r.get(field) or 0) for r in items)
    # ★ 卡 A355：多一行**按请求**的结局 —— 上面那行「本卡 N 轮」说的是**轮**（是对的，
    #   一个字都不改）；这一行说的是「这些轮最终算几次请求」：交出去的试不计请求、不计失败，
    #   失败被接住算「重试答上」。口径只有一份（`tools/pool/outcomes.py`）。
    counts = pool_outcomes.count_requests(rows, card=card)
    parts = [f"本卡 {len(mine)} 轮：input {total(mine, 'input_tokens'):,} / "
             f"output {total(mine, 'output_tokens'):,} / cache_read {total(mine, 'cache_read'):,}",
             f"请求 {counts['requests']} / 失败 {counts['errors']} / "
             f"重试答上 {counts['retried']}",
             f"累计（所有卡）：input {total(rows, 'input_tokens'):,} / "
             f"output {total(rows, 'output_tokens'):,} / cache_read {total(rows, 'cache_read'):,}"]
    return " ｜ ".join(parts)


# ★ 卡 E97：模型名的别名表 —— 只在**第一次**调用时读盘（模块级缓存），读不到就一直是 None。
_ALIAS_TABLE: dict[str, tuple[str, ...]] | None = None
_ALIAS_TABLE_LOADED = False


def _alias_table() -> dict[str, tuple[str, ...]] | None:
    """注册表里每个模型写法的索引（小写 → 该条目的别名组）；读不到 ⇒ `None`。

    ★ 只在第一次调用时读盘：`load_registry()` 之后结果就钉在模块里（真实进程里注册表
    不会半路变）。给测试的清缓存钩子是 `reset_model_aliases()`。
    """
    global _ALIAS_TABLE, _ALIAS_TABLE_LOADED
    if _ALIAS_TABLE_LOADED:
        return _ALIAS_TABLE
    _ALIAS_TABLE_LOADED = True
    try:
        entries = load_registry()
    except (ModelRegistryError, OSError):
        _ALIAS_TABLE = None
        return None
    table: dict[str, tuple[str, ...]] = {}
    for entry in entries:
        names = id_names(str(entry.id))
        for alias in names:
            key = alias.strip().lower()
            if key and key not in table:
                table[key] = names
    _ALIAS_TABLE = table
    return table


def reset_model_aliases() -> None:
    """清掉 `_alias_table()` 的缓存（测试用；下次调用会重新读盘）。"""
    global _ALIAS_TABLE, _ALIAS_TABLE_LOADED
    _ALIAS_TABLE = None
    _ALIAS_TABLE_LOADED = False


def model_aliases(name: str) -> tuple[str, ...]:
    """一个模型名的全部写法：原形 + 别名（卡 E97，`usage_in()` 归一口径的唯一实现）。

    三档口径**不另写一套**，直接复用 `tools/pool/model_registry.py::id_names`（原样 /
    最后一个 `/` 之后 / 第一个 `/` 之后）；注册表读得到时再把同一个模型在表里的其它写法
    补进来。★ **大小写不敏感**：注册表里是 `huaweicloud-maas/GLM-5.2`，而
    `gates/diag/wb-usage.jsonl` 的 `模型` 字段写的是小写 `glm-5.2` —— 不归一就恒 0；
    反过来 `glm-5.2` 也要能命中写成 `GLM-5.2` 的行。

    注册表读不到 ⇒ 只回 `id_names(name)` 那三档（`_matches_model()` 会退回字面相等）。
    """
    base = str(name or "").strip()
    if not base:
        return ()
    seen: list[str] = []
    for alias in id_names(base):
        if alias not in seen:
            seen.append(alias)
    table = _alias_table()
    if table is not None:
        for alias in list(seen):
            for extra in table.get(alias.strip().lower(), ()):
                if extra not in seen:
                    seen.append(extra)
    return tuple(seen)


def _matches_model(row_name: object, model: str) -> bool:
    """用量行的 `模型` 是否算这个模型：任一别名命中即算；注册表读不到 ⇒ 字面相等。"""
    raw = str(row_name or "").strip()
    if not raw:
        return False
    if _alias_table() is None:  # fail-open：注册表坏了不许一律回 0
        return raw == model.strip()
    wanted = {alias.lower() for alias in model_aliases(model)}
    return raw.lower() in wanted


def usage_in(model: str, start: datetime, end: datetime, *,
             root: Path = ROOT) -> tuple[int, float]:
    """按**模型**与时间区间 `[start, end)` 汇总 `gates/diag/wb-usage.jsonl`（卡 A334 · T-AG536）。

    为什么要有它：`usage_summary(card)` 只按「卡」聚合，pool 要的是「某个**模型**在某个
    **窗口**里路由了多少」—— 那是整窗估算的分子（`tools/pool/holds.py::estimate`）。本函数
    **只读不改**，`append_usage_line()` 的签名与 `usage_summary()` 的行为一个字节都不动。

    口径（逐条写清，做不到的写做不到）：

    * **时区钉死 +08:00**：行里的 `开始` / `结束` 是秒级、**无时区**的本地串
      （`_iso_local()` 用 `datetime.fromtimestamp().isoformat()`）。这里按
      `tools/pool_accounts.py:47` 的同一口径 `UTC+8` 补上 tzinfo 再比，
      **不用 `astimezone()` 猜**、不读系统时区。入参 `start` / `end` 必须自带 tzinfo；
      给 naive 的会抛 `TypeError`（故意不兜底 —— 猜时区比报错糟）。
    * **区间** `[start, end)`，按 `开始` 落点算（与 `append_usage_line()` 写的那个字段一致）。
    * **dry run 不计入**：`判决` / `退出码` 里带 `dry` 字样的行跳过。★ 如实写：现行
      `append_usage_line()` 只在真跑完时调用，落盘行**没有** dry-run 字段，所以这条现在是
      防御性的（照 `window_holds.go:100`/`:108` 的 `dryRun`/`dryRuns` 口径先把闸门留好）。
    * **token 口径**：`input_tokens + output_tokens + cache_read` 三个字段全加。★ 为什么不去重：
      本机没有权威说明 `cache_read` 是否已含在 `input_tokens` 里（两种 API 口径都存在），
      猜错会系统性少算或多算 ⇒ **不做减法**，原样相加并在文档里说清（这是「没核到的」一条）。
    * **金额恒 0.0**：仓里没有计价表（`model-registry.toml` 里 `price|cost|单价` 零命中），
      第二档不编单价，等有计价表再填。
    * **模型名按别名归一（卡 E97）**：行里的 `模型` 与入参只要落在同一组别名里就算命中
      （`model_aliases()`：`id_names` 的三档 + 注册表里的其它写法，**大小写不敏感**）。
      为什么必须有：`wb-usage.jsonl` 写的是小写 `glm-5.2`，注册表里是
      `huaweicloud-maas/GLM-5.2` —— 字面比就是恒 0。注册表读不到 ⇒ 退回**字面相等**
      （fail-open：注册表坏了不许把用量一律算成 0）。别名表只在第一次调用时读盘。
    * 读不出来 / 没有这个文件 / 某行 JSON 坏 / `开始` 解不开 ⇒ **跳过或回 (0, 0.0)**，
      不猜、不抛（与 `usage_summary()` 的「读不出来就空串」同一种态度）。
    """
    from datetime import timedelta, timezone  # 本函数是 wb_dispatch 里唯一的时区用法

    tz = timezone(timedelta(hours=8))
    path = root / "gates" / "diag" / "wb-usage.jsonl"
    try:
        lines = wb_status.read_log_lines(path)
    except (OSError, wb_status.UnknownLogEncodingError):
        return 0, 0.0

    def number(value: object) -> int:
        """JSONL 里的 token 数：只认 int/float，别的（缺字段 / 字符串）当 0 —— 不猜。"""
        if isinstance(value, (int, float)):
            return int(value)
        return 0

    def local(raw: object) -> datetime | None:
        """无时区的本地串 → 带 +08:00 的时刻；解不开 ⇒ None（跳过这一行）。"""
        if not isinstance(raw, str) or not raw:
            return None
        try:
            return datetime.fromisoformat(raw).replace(tzinfo=tz)
        except ValueError:
            return None

    tokens = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if not _matches_model(row.get("模型"), model):
            continue
        verdict = f"{row.get('判决') or ''} {row.get('退出码') or ''}".lower()
        if "dry" in verdict:
            continue
        began = local(row.get("开始"))
        if began is None:
            continue
        if not start <= began < end:
            continue
        tokens += number(row.get("input_tokens"))
        tokens += number(row.get("output_tokens"))
        tokens += number(row.get("cache_read"))
    return tokens, 0.0


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
        reset_raw = hit.group(1) if hit else ""
        # ★ 卡 201（T-G303）：加 `reset_at`（ISO 或 None）—— 解析只调 `pool_quota.parse_reset`
        #   （判据只许一份真源）。原有 `kind` / `reset` / `why` 一字不变；两道闸门没动。
        reset_dt = pool_quota.parse_reset(reset_raw) if reset_raw else None
        return {"kind": "限流" if hit else "余额耗尽", "reset": reset_raw,
                "reset_at": reset_dt.isoformat() if reset_dt is not None else None,
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
                  lines: list[str], errlog: Path,
                  started_at: float | None = None) -> Path:
    """这一轮的判决落盘 —— **按轮落、不互相覆写**（T-G96）。

    `wb-<卡>.jsonl` → `wb-<卡>.verdict.txt`；`wb-<卡>.r2.jsonl` → `wb-<卡>.r2.verdict.txt`。
    ★ 每轮要能查到**断在哪**：退出码 / 有没有 `result` 事件 / 末事件类型 / log 行数 / stderr 5 行。
    ★ 卡 164（T-G264）：判决带**轮次 + 开始时刻 + 结束时刻** —— 读的人要能判「这是不是当前这一轮」
      （旧判决冒充当前状态的现场就是它：判决里没开始时刻，分不清是哪一轮）。
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
    end_iso = datetime.now().isoformat(timespec="seconds")
    began_iso = (datetime.fromtimestamp(started_at).isoformat(timespec="seconds")
                 if started_at is not None else "（无）")
    out.write_text(
        f"card={card} 第={attempts} 次 退出码={code} "
        f"会话={sid or '（无）'} 开始于={began_iso} 结束于={end_iso}\n"
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
                  inflight: tuple[str, float] | None, durations: list[float],
                  no_output: bool = False) -> str:
    """卡死报告 —— ★ **必须带现场**（T-G94）：最后一次调用是什么 / 已跑多久 / 历史最长一次 /
    这一次用的阈值。旧报告只说「X 分钟没有新事件」，主控拿到现场还得自己翻 log 去猜它当时在跑什么。

    ★ T-G260b：`no_output`（一行输出都没有、且启动宽限已过）**必须点名**——
    它与「有输出但没在飞」是两回事，报告里含糊过去就等于把判据的对象藏起来了。
    """
    longest = max(durations) if durations else 0.0
    if inflight:
        sig, ran = inflight
        what = f"在跑 {wb_status._clip(sig, 100)}（已跑 {ran / 60:.1f} 分钟）"
    elif no_output:
        what = f"它**一行输出都还没有**（启动宽限 {STARTUP_GRACE_SECONDS} 秒已过）"
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


def tool_use_missing_fields(lines: list[str]) -> list[str]:
    """★★ 卡 164（T-G264 / INV-36）：列出 `tool_use` 块里**缺 `id` 或 `__timestamp`** 的那些。

    为什么要有它：`_epoch` 的保守分支（缺字段 → None）+ `inflight_tool`/`tool_durations`
    的 `if stamp is None: continue` 会**悄悄跳过**残桩 —— 生产里这是对的（半截 log 不许炸），
    但**测试里**它会让断言**恒真**（桩缺字段 ⇒ 没数据放大阈值 ⇒ 阈值 == 底线 ⇒ 断言"阈值
    没被抬"绿了，但其实是因为桩什么都没喂进去）。这条就是那个假绿的根因。

    用法（测试里自检桩完整性）：
    `assert not wd.tool_use_missing_fields(桩), wd.tool_use_missing_fields(桩)`
    —— 桩缺字段时这条**红**，并指出缺的是哪一块。
    """
    missing: list[str] = []
    for raw in lines:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "assistant":
            continue
        has_stamp = _epoch(event.get("__timestamp")) is not None
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        for item in content if isinstance(content, list) else []:
            if not isinstance(item, dict) or item.get("type") != "tool_use":
                continue
            tid = item.get("id")
            lacks: list[str] = []
            if not tid:
                lacks.append("id")
            if not has_stamp:
                lacks.append("__timestamp")
            if lacks:
                missing.append(f"tool_use name={item.get('name') or '?'} 缺 {'+'.join(lacks)}")
    return missing


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
                     need: int = REPEAT_NEED, lines: list[str] | None = None,
                     startup_grace_seconds: float = STARTUP_GRACE_SECONDS) -> str:
    """**在跑的时候**该不该把它掐了 —— 返回原因（空串 = 健康）。① 卡死 ② 空转。

    ★ 判卡死的阈值**不是常数**（T-G94）：日志静默 ≠ 卡死 —— 一次工具调用期间**本来就静默**
    （全量门禁 ~4 分钟、冷缓存 worktree 里十几分钟），旧写法会把这种正常的长调用误判成卡死。
    所以给了 `lines` 就按现场放宽（在飞 → 30 分钟底线；再按历史最长一次调用 × 2.5 自适应）；
    **不给 `lines`** = 老口径（阈值就是 `stall_seconds`）—— 空转那条判据一个字没动。
    ★★ T-G260b **启动宽限**：`lines` 给了但**是空的**（工人一行都还没吐）⇒ 这不是「静默」，
    是「还没开始」⇒ 阈值抬到 `max(阈值, startup_grace_seconds)`。
    理由与现场指纹见 `STARTUP_GRACE_SECONDS` 上面那段。★ 一旦有第一行就**不再**生效。
    """
    inflight = inflight_tool(lines) if lines is not None else None
    durations = tool_durations(lines) if lines is not None else []
    threshold = stall_threshold_seconds(stall_seconds=stall_seconds, inflight=inflight,
                                        durations=durations)
    no_output = lines is not None and not lines
    if no_output:
        threshold = max(threshold, float(startup_grace_seconds))
    if silent_seconds >= threshold:
        return _stall_report(silent_seconds=silent_seconds, threshold=threshold,
                             inflight=inflight, durations=durations, no_output=no_output)
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
      ② `subtype != success` → 中途停下（撞上限、被中断、工具连环失败、429 限流…）；
      ③ 回话是空的 → 没交出东西。
    ★ 两条判据（数回合 vs 读事件）是**互补**的：数回合能提前预警，读事件才是硬证据。
    ★ 卡 151（T-G251）：`subtype != success` **不再无脑归到「撞 `--max-turns`」** ——
      派活器**已经**有 `quota_error()` 这个判据（429 / 额度），把它的结论**带进判决**：
      有 429 命中 ⇒ 写「429 限流（额度重置时间：…）」；没有 ⇒ 写「**真因未识别**」
      （★★ **不许**默认归到 `--max-turns` —— 那是猜；`--max-turns` 该由 `cap_verdict()`
      数回合来判，本函数只判 `result` 事件）。判决带**依据**（log 行号 / 字段名），让人能核。
    """
    result: dict | None = None
    result_line: int = 0
    for i, raw in enumerate(lines, 1):
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") == "result":
            result = event
            result_line = i
    if result is None:
        return "没跑完：整段 log 里没有 `result` 事件（进程被打断 / 被杀 / 还在跑）"
    subtype = str(result.get("subtype") or "")
    text = str(result.get("result") or "").strip()
    if subtype != "success":
        # ★ 卡 151：先把派活器已有的 429 / 额度判据带进判决 —— 同一个指纹（subtype + 空回话）
        #   背后可能是 429 限流，也可能是真撞 --max-turns；只看指纹 = 猜，要查真因。
        quota = quota_error(lines)
        if quota is not None:
            reset = (f"额度重置时间：{quota['reset']}" if quota["reset"]
                     else "无重置时间（余额耗尽）")
            return (f"没跑完：`result.subtype = {subtype or '（空）'}` —— 429 限流"
                    f"（{reset}）；依据：log 第 {result_line} 行 result 事件，{quota['why']}")
        detail = "回话是空的" if not text else f"回话：{wb_status._clip(text, 120)}"
        return (f"没跑完：`result.subtype = {subtype or '（空）'}` —— 真因未识别"
                f"（429 与回合数到顶都没命中；不许默认归到 `--max-turns`，那是猜）；"
                f"依据：log 第 {result_line} 行 result 事件，"
                f"subtype={subtype or '（空）'}，{detail}")
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
               worker_cwd: Path | None = None,
               worker_env: dict[str, str] | None = None) -> tuple[int, str, str, str]:
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
    ★ 卡 149（T-G249）：`worker_env` 给了就是**工人进程的整份环境**（多号 profile 用）——
    由 `account_env()` 从仓外号池工具解析出来 + 现进程环境合成；**不给（默认 `None`）时
    `Popen(env=None)` = 逐字继承**今天的家目录，行为一字不变。
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
            stdout=subprocess.PIPE, env=worker_env, **NO_WINDOW,
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
# （默认 4.0 → ★ **2026-10-03 18:2x 用户令改为 2.0**，理由与留痕见 `scripts/run_gates.py` 同段注释；
# 两处**必须一起改**，否则"同一套口径"当场变成两套）、同一套措辞、同样"读不到就跳过"。
# 派活同样吃内存（工人会跑 pytest / 起真服务），所以派活前也要过这道闸。★ 只加这一条前置判据 ——
# 派活主流程（心跳 / 看门狗 / 429 / 判决口径 / retry）与 `--status` 三态判据一个字不动。
DEFAULT_GATE_MIN_FREE_GB = 2.0


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


def snapshot_stale_problem() -> str:
    """号池快照过期提示（卡 320）。

    ★ 快照 `models.live.json` 是**静态产物**，不是现场读数：拿三天前的名单当权威
    正是「未记录 ⇒ 以为没额度」的来源。这里只**响亮点名**，不拦派活 —— 真额度由
    派活时的一次真实调用探出来（失败特征见 `infra/pool`）。
    """
    try:
        from pool.models import STALE_HOURS, find_pool_dir, load_pool_models

        pool_dir = find_pool_dir(ROOT)
        if pool_dir is None:
            return ""
        data = load_pool_models(pool_dir)
    except Exception:  # noqa: BLE001 —— 提示性判据，读不到就不嚷
        return ""
    if data.get("snapshot_stale"):
        # ★ 卡 320：坏时间戳也会走到这里（那时 `snapshot_age_hours` 是 None）——
        #   文案必须跟着走，否则会打出「已过期 None 小时」。
        age = data.get("snapshot_age_hours")
        when = f"已过期 {age} 小时" if age is not None else "时间戳读不出来"
        return (
            f"★★ 号池快照{when}"
            f"（上限 {STALE_HOURS}h，快照时间 {data.get('snapshot_at')}）"
            f"⇒ 名单只当历史；派活前先用一次真实调用探额度"
        )
    return ""


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

    ★★ 卡 203（T-G307）：**不给 `--cwd`**（`worker_cwd is None`）时**按进程 cwd 还原标签**
      —— 工人进程的 cwd 就是派活器的进程 cwd（从卡树里跑那棵树里那份脚本时 = 卡树，从主仓跑
      = 主仓）。**老行为是"一律 `""`"（= 主树）** ⇒ 从卡树里跑会把**主树**误登记成被占、
      而工人在卡树里干活（症状 A：197/201/202 三张卡都被自己那条 `tree: ""` 租约挡过）。
      ★ 只改**标签怎么算**，不改树/域/锁/日志/模型白名单/内存闸任何一条守卫的语义。
    """
    if worker_cwd is None:
        # 不给 `--cwd` ⇒ 工人 cwd 就是派活器的进程 cwd（卡 203）。
        worker_cwd = Path.cwd()
    target = worker_cwd.resolve()
    try:
        rel = target.relative_to(main_root.resolve())
    except ValueError:
        return target.as_posix()
    text = rel.as_posix()
    return "" if text == "." else text


def wrong_copy_warning() -> str:
    """★ 卡 203（T-G307）：跑的是**树里那份**派活器时，给一句人话提示（**不拒跑**）。

    判据：`ROOT != 主树根` —— 即 `wb_dispatch.py` 不是主仓那份，而是从卡树 / 别的树里跑的那份。
    那时 `ROOT` 是产物目录（`gates/diag/wb-<卡>.jsonl` / brief / 规格路径）的基 ⇒ 派活产物会
    落卡树（症状 B），而卡树里**没有**主仓那份 `gates/diag/`（gitignore 目录）。

    ★ 选了**只提示、不拒跑**，理由三条：
      ① 卡 203 只许改"标签怎么算" —— 拒跑是**新增一条守卫语义**，不在卡的改法里；
      ② `ROOT` 被显式指到别处（测试沙箱 / 别的项目）是**合法调用**，拒跑会误伤；
      ③ 登记的树已由 `worker_tree_label` 按进程 cwd 还原（**症状 A 已治**），
         剩下"产物落哪"用一句人话点破就够。
    主树根算不出（git 不可用）⇒ 回 `""`（**不新增失败**）。
    """
    try:
        main_root = pool_registry.main_tree_root()
    except pool_registry.RegistryError:
        return ""
    if ROOT.resolve() == main_root.resolve():
        return ""
    return (f"[提示] 你在卡树里跑了**树里那份**派活器（ROOT={ROOT}；主树={main_root}）："
            "派活产物会落卡树。正确跑法：从**主仓**跑 + `--cwd <树>`（卡 203）")


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
        # ★ 卡 262：先合分片（docs/backlog/<分区>.toml）后读总表 —— 带分区前缀的卡
        #   （A261）登记在分片里，只读总表查不到它的域（守卫会拒派活）。
        backlog = load_sharded_backlog(base, base.parent / "backlog")
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
    else:
        # ★ 卡 157（T-G257）派活前置：规格声称了批次 `B-XXX` ⇒ 预声明必须在 ——
        #   缺就**拒发**（工人的第一分钟就知道，而不是第 28 分钟交申请时才被栅栏咬）。
        #   与其它前置检查并列（规格在 / 脏树 / log / 端口 / 内存 / 登录 / 守卫 / 卡树基点）。
        try:
            batch = extract_batch_claim(ROOT / spec)
        except OSError as exc:
            problems.append(f"读不到卡规格 {spec}（{exc}）")
            batch = None
        if batch and not batch_manifest_path(batch).exists():
            rel = f"gates/diag/batch/{batch}.toml"
            problems.append(
                f"卡 {card} 声称属于 {batch}，但预声明 {rel} 不存在"
                f"（先 `wb_task.py register {rel}`）")
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
    if log.exists() and not force and not resuming:
        problems.append(f"这一轮的 log 已存在：{log}（要覆盖请 --force —— 证据不许被悄悄盖掉）")
    # ★ 卡 163 INV-40：续跑时 log 已存在是正常的（那是上一轮的证据）⇒ 不拒。
    #   续跑从 first_attempt（已有轮次+1）起，log_k = wb-<卡>.r<N>.jsonl，不覆盖旧证据。
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
    # ★ 卡 320：号池快照过期 ⇒ 响亮提示（不拦，快照不是现场读数）
    snap = snapshot_stale_problem()
    if snap:
        print(f"  {snap}", file=sys.stderr, flush=True)
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


# ---------------------------------------------------------------- 卡 E10：--batch
def batch_gate_problem(batch: str, card: str | None) -> str | None:
    r"""★ 卡 E10 判据 7：`--batch` 的三道响亮拒绝（`None` = 放行）。

    · 批号没有可用预声明（缺 / 不合法）⇒ 拒绝并点名（先 `wb_batch.py make`
      或 `wb_task.py register`）；
    · `--card` 不在成员名单里 ⇒ 拒绝（名单外的派活不算数 —— 防夹带）；
    · 批已 `landed` ⇒ 拒绝并给现状（它字段里挂着那笔 commit，不许复活）。
    """
    try:
        man = pool_task.load_manifest(batch)
    except Exception as exc:  # noqa: BLE001 —— 缺 / 坏都要响亮拒绝，理由原样带出
        return (f"批 {batch} 读不到可用预声明：{exc}"
                "（先 `wb_batch.py make <批号>` 或 `wb_task.py register <预声明>`）")
    members = [str(m.get("id", "")) for m in man.get("member") or []]
    if card and card not in members:
        return (f"卡 {card} 不在批 {batch} 的成员名单里（名单：{'、'.join(members)}）"
                "—— 不在名单里的派活不算数（防夹带）")
    state = None
    try:
        state = pool_task.read_json(pool_task.state_path(batch))
    except Exception:  # noqa: BLE001 —— 还没登记（或状态坏了）：下一步 ensure_batch_task 处理
        state = None
    if isinstance(state, dict) and state.get("state") == "landed":
        landed = state.get("landed") or {}
        return (f"批 {batch} 已经 landed（commit {landed.get('commit', '?')}，"
                f"{landed.get('at', '')}）—— 不再派活；"
                f"现状：state=landed / 成员 {len(members)} 张")
    return None


def ensure_batch_task(batch: str) -> str | None:
    """★ `--batch` 派活时就把成员登记进**同一任务**（状态缺 ⇒ 按预声明 register）。"""
    if pool_task.state_path(batch).exists():
        return None
    try:
        rc = pool_task.cmd_register(
            argparse.Namespace(manifest=str(pool_task.manifest_path(batch)), force=False))
    except pool_task.BatchError as exc:
        return f"批 {batch} 登记进任务失败：{exc}"
    return None if rc == 0 else f"批 {batch} 登记进任务失败（退出码 {rc}）"


def dispatch_batch(args: argparse.Namespace) -> int:
    """`--batch` 不给 `--card`：按预声明成员逐个派活（dry-run 只打印命令）。"""
    man = pool_task.load_manifest(args.batch)
    members = [str(m.get("id", "")) for m in man.get("member") or []]
    try:
        backlog = load_sharded_backlog(
            ROOT / "docs" / "workbacklog.toml", ROOT / "docs" / "backlog")
    except BacklogError as exc:
        print(f"[FAIL] 读不了队列（{exc}）⇒ 不派批", file=sys.stderr, flush=True)
        return 2
    by_id = backlog.by_id()
    main_root = pool_task.main_tree_root()
    for member_id in members:
        card = by_id.get(member_id)
        if card is None:
            print(f"[FAIL] 批 {args.batch} 成员 {member_id} 不在队列里 ⇒ 不派",
                  file=sys.stderr, flush=True)
            return 2
        argv = [sys.executable, "-X", "utf8", str(ROOT / "tools" / "wb_dispatch.py"),
                "--card", member_id, "--spec", card.spec, "--batch", args.batch]
        if card.tree:
            argv += ["--cwd", str((main_root / card.tree).resolve())]
        if args.model:
            argv += ["--model", args.model]
        if args.account:
            argv += ["--account", args.account]
        if args.sticky:
            argv.append("--sticky")   # 卡 A345：逐成员 re-exec 不许丢
        if args.execute:
            argv.append("--execute")
        if args.detach:
            argv.append("--detach")
        print(f"[派 ] {' '.join(argv)}", flush=True)
        if args.execute:
            done = subprocess.run(argv, cwd=str(ROOT), **NO_WINDOW)
            if done.returncode:
                return int(done.returncode)
    if not args.execute:
        print("[dry ] 默认只打印；真要派活加 --execute（会逐成员起工人）", flush=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """命令行解析器 —— 抽成函数，好让测试**真读帮助文本**（卡 125 §2.9：帮助与常量同源）。"""
    parser = argparse.ArgumentParser(description="派活给 CodeBuddy CLI（默认 dry-run）")
    parser.add_argument("--card", default="",
                        help="卡号（用来命名 log，如 001）；★ 给 --batch 单独时可省（一次派整批）")
    parser.add_argument("--batch", default="",
                        help="★ 批号（gates/diag/batch/<批号>.toml）：成员派进同一任务；"
                             "卡不在预声明里 / 批已 landed ⇒ 响亮拒绝")
    parser.add_argument("--take-over", action="store_true",
                        help="卡归别的对话窗口时，显式换手到当前窗口（会留痕）")
    parser.add_argument("--spec", default="", help="卡规格文件（相对仓库根；--status 时不必给）")
    parser.add_argument("--cwd", default="",
                        help="工人进程的 cwd（绝对/相对都行，会解析成绝对路径）—— 让工人"
                             "**落在卡树里干活**（卡 103）。★ 派活产物（wb-<卡>.jsonl / "
                             "brief-<卡>.md / 卡规格）仍落在**主仓**的 gates/diag/：那一份目录"
                             "是 gitignore 的、卡树里没有。不给则行为与从前逐字相同（工人 cwd="
                             "仓库根）")
    parser.add_argument("--pool", default=DEFAULT_POOL,
                        help=f"派到哪个池（默认 {DEFAULT_POOL}；卡 166 按池分流）。"
                             "codebuddy = CodeBuddy CLI（今天在用的）；"
                             "codearts = 华为码道 CLI（卡 166 只留接口 + 拒绝路径）；"
                             "未知池 ⇒ 响亮拒绝并点名已接的池")
    parser.add_argument("--model", default=None,
                        help="派活用哪个模型（不给 = 该池默认，按池声明、不取注册表首项）。"
                             "★ 允许集 = 注册表该池条目 + 一次性授权 + 外部开关文件里打开的；"
                             "表外一律拒单（用户 2026-09-26 令：黑名单锁死）。"
                             "★ 跨池串用被拒（codebuddy 用裸名、codearts 用 provider/model 形式）")
    parser.add_argument("--project", default=None,
                        help="项目名（卡 120）—— 不给就按 `--cwd` 那棵树从项目索引反查；"
                             "没登记的项目 / 树不落在该项目的树前缀里 ⇒ 拒派")
    parser.add_argument("--account", default=None,
                        help="★ 多号（卡 149）：把工人跑在指定 profile 里的那组环境变量现取注入；"
                             "不给 = 今天家目录、逐字不变；名字不存在 / 取不到 ⇒ 拒派并点名")
    parser.add_argument("--caller", default=None,
                        help="★ 调用方（卡 A348）：名册 `infra/pool/callers.toml` 里的 id —— "
                             "答「谁在花谁的钱」，与 `--account`（用哪个号）正交；"
                             "不给 = 按 `TF_WINDOW_ID` / `<hostname>:<pid>` 认；"
                             "这个人被撤（`off = true`）⇒ 拒派并点名（走前置检查出口、退 2）")
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
    # ★ 卡 167（T-G267）：--effort 透传。help 文本里的值域**从常量拼出来**（与 --max-turns
    #   同款：改常量即改 help，不许写死 —— 本仓有过 help 与常量漂了的老坑）。
    parser.add_argument("--effort", default=None,
                        help=f"思考等级（CLI 2.158.0 的 {len(EFFORT_LEVELS)} 档："
                             f"{' / '.join(EFFORT_LEVELS)}）。★ 不给 = 不传 = CLI 默认 High"
                             "（2026-09-26 口径，逐字不变）；给了才透传给工人")
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
    parser.add_argument("--patience", type=int, default=0,
                        help=f"全都忙时「歇一会儿再问」的总预算（秒）—— 默认 0 = 用标准预算 "
                             f"{pool_quota.PATIENCE_DEFAULT_S}s（0 不是关！）；-1 = 关"
                             "（行为与没有这个参数逐字相同）；"
                             f"上限收 {pool_quota.PATIENCE_LONGEST_S}"
                             f"（配 3600 实际用 {pool_quota.PATIENCE_LONGEST_S}）")
    parser.add_argument("--input-budget", type=int, default=DEFAULT_INPUT_BUDGET,
                        help=f"单卡 input tokens 预算（默认 {DEFAULT_INPUT_BUDGET:,}）—— "
                             "超了就止损掐掉，不许自动续跑（防空烧）")
    # ★ 卡 A345（T-AG547）：卡粘性 —— 同一张卡第二次派活别换号。**默认关**，
    #   不给时 reserve() 的入参 / lease_note / 判决文案与以前逐字相等。
    parser.add_argument("--sticky", action="store_true",
                        help="同一张卡第二次派活时，还用它上次答过的那个号"
                             "（只在本轮没给 --account 时生效；"
                             "记录见 gates/diag/pool-sticky.json）")
    parser.add_argument("--detach", action="store_true",
                        help="把这次派活**扔出去单独跑**（我的窗口关了它照样跑；过夜/长任务用）")
    parser.add_argument("--detach-done", action="store_true", help=argparse.SUPPRESS)
    # ★ 卡 E7（T-AG453）：派活即看守。默认 `one`（一张卡一个看守 = 一张卡一次通知）。
    parser.add_argument("--watch", choices=("one", "shared"), default="one",
                        help="派活成功后挂哪种看守（默认 one=专属：出判决就写 "
                             "gates/diag/wb-<卡>.done 并退出；shared=全局一份合用看守，"
                             "引用计数 +1 / 出判决 -1 / 归 0 写 batch-done）")
    parser.add_argument("--no-watch", action="store_true",
                        help="不起看守 —— ★ 会明说「已关看守：完工后请自己轮询」，不静默")
    parser.add_argument("--status", action="store_true",
                        help="只看状态（心跳/判决/会话/log 尾巴），不派活、不用给 --spec")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.status:
        if not args.card:
            print("[FAIL] --status 要给 --card（批状态看 wb_task.py status <批号>）",
                  file=sys.stderr, flush=True)
            return 2
        print(status_report(args.card), flush=True)
        return 0
    # ★ 卡 E10（T-AG461）判据 7：`--batch` 先过三道响亮拒绝（缺预声明 / 夹带 / 已 landed），
    #   再把成员登记进同一任务（状态缺就按预声明 register）；不给 --card ⇒ 逐成员派出去。
    if args.batch:
        problem = batch_gate_problem(args.batch, args.card or None)
        if problem:
            print(f"[FAIL] {problem}", file=sys.stderr, flush=True)
            return 2
        registered = ensure_batch_task(args.batch)
        if registered:
            print(f"[FAIL] {registered}", file=sys.stderr, flush=True)
            return 2
        if not args.card:
            return dispatch_batch(args)
    if not args.card:
        print("[FAIL] 派活得给 --card（或 --batch <批号> 一次派整批）",
              file=sys.stderr, flush=True)
        return 2
    # ★ 卡归窗口：一张卡默认只归一个 DSH 窗口；没有指纹（工人/CLI）一律放行。
    try:
        from tools import wb_session
    except ModuleNotFoundError:  # `python tools/wb_land.py` 时 sys.path[0] 是 tools/
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import wb_session  # type: ignore[no-redef]

    ok, msg = wb_session.claim(args.card, take_over=getattr(args, "take_over", False))
    if not ok:
        print(f"  ★ {msg}", file=sys.stderr, flush=True)
        return 2
    if msg:
        print(f"  [窗口] {msg}", flush=True)
    # ★ 卡 203（T-G307）：跑的是**树里那份**派活器 ⇒ 一句人话提示（**不拒跑**，理由见该函数）。
    wrong_copy = wrong_copy_warning()
    if wrong_copy:
        print(wrong_copy, file=sys.stderr, flush=True)
    # ★★ 模型白名单硬闸门（卡 029 §2.4 + 卡 166 按池分流）—— 放在**一切之前**：
    #   拒单必须**零副作用**：不起进程、不建 log、不写判决、不改树。--resume / --retry /
    #   --detach 全都从这里过闸（它们都要带 --model）。
    #   ★ 卡 166：--model 缺省按池取默认（不取注册表首项，判据 ②）；跨池串用被拒（判据 ③）；
    #   未知池 / 未接池被拒（判据 ④）；注册表坏掉退 2 零副作用点名（判据 ⑤）。
    try:
        pool = args.pool
        get_adapter(pool)                                 # 未知池 ⇒ 拒（判据 ④）
        if args.model is None:
            args.model = default_model_for(pool).alias    # 按池取默认（判据 ②）
        resolve_model(args.model, pool)                   # 跨池串用 ⇒ 拒（判据 ③）
        get_adapter(pool).assert_wired()                  # 已知但未接 ⇒ 拒（判据 ④）
        rejected = model_rejected(args.model, pool)
    except (ModelRegistryError, PoolMismatchError, UnknownPoolError, PoolNotWiredError,
            SwitchFileError) as exc:
        # ★ 卡 138 / 卡 146 / 卡 166：开关文件 / 注册表 / 适配器坏了要**响亮地**失败并点名
        #   （**不静默当空、不退回内置名单**）—— 仍在起进程之前拦下（零副作用），退 2。
        print(f"[FAIL] {exc}", file=sys.stderr, flush=True)
        return 2
    if rejected:
        print(f"[FAIL] {rejected}", file=sys.stderr, flush=True)
        return 2
    # ★ 卡 A345（T-AG547）：接入点 1 —— 粘性（**占树之前**，也在 caller 白名单之前：
    #   换了号就得按新的号重判白名单）。粘性是省钱的优化：判不了就当没有，绝不拦派活。
    sticky_why = ""
    sticky_age = 0.0
    if args.sticky and not args.account:
        sticky_hit = pool_sticky.stick_for(args.card)
        if sticky_hit is not None:
            sticky_why = pool_sticky.choose(sticky_hit, ledger_accounts())[1]
            sticky_age = time.time() - sticky_hit.at
            if sticky_why in pool_sticky.REASONS_KEEP:
                # ★ 最后一道自证：记录里的名字**这轮真能用**吗？粘性只许「照旧」，不许
                #   把一句本来能跑的派活变成退 2 —— 记录里的名字若认不出（A344 落地后账本里
                #   是稳定 id，而 `--account` 仍收 profile 名，见卡规格缺口 3），就当没粘。
                try:
                    account_env(sticky_hit.account)
                except AccountError as sticky_exc:
                    print(f"[粘 ] 卡 {args.card} 上次的号 {sticky_hit.account} 这轮认不出"
                          f"（{sticky_exc}）⇒ 正常挑号", file=sys.stderr, flush=True)
                    sticky_why = ""
                else:
                    args.account = sticky_hit.account
                    print(f"[粘 ] 卡 {args.card} 上次在号 {args.account} 上答过"
                          f"（why={sticky_why}，{pool_sticky.age_text(sticky_age)}）⇒ 这次还用它",
                          file=sys.stderr, flush=True)
            if sticky_why and sticky_why not in pool_sticky.REASONS_KEEP:
                print(f"[粘 ] 卡 {args.card} 上次的号 {sticky_hit.account} 已 {sticky_why}"
                      " ⇒ 正常挑号", file=sys.stderr, flush=True)
    # ★ 卡 A341（T-AG543 · F34）：第 ③ 步 —— caller（账号）白名单**只收窄**。
    #   前两步（①resolve_model 跨池 / ②model_rejected 池内）一字不改；本步只是在外面加一层
    #   收窄，`not patterns` ⇒ 不收窄（照 magpie Restricted() 「空 = 不受限」）。
    #   读表/清洗坏了要**响亮地**失败（不静默当「不收窄」），仍在起进程之前（零副作用），退 2。
    # ★ 卡 A344（T-AG546）：本文件**唯一**把 `--account` 的 profile 名换成账本稳定 id 的地方。
    #   三条闸（lanes A339 / rpm A340 / caller 白名单 A341）的键都是那个稳定 id，全在它之后查表。
    #   账本读不到 / 名字对不上唯一的号 ⇒ 退 2 拒派并点名（**不许**按原名悄悄派活）。
    try:
        account_id, _account_why = resolve_account(args.account)
    except AccountMapError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr, flush=True)
        return 2
    try:
        caller_rejected = caller_model_rejected(args.model, pool, account_id or None)
    except ModelRegistryError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr, flush=True)
        return 2
    if caller_rejected:
        print(f"[FAIL] {caller_rejected}", file=sys.stderr, flush=True)
        return 2
    # ★ 卡 167（T-G267）：--effort 白名单硬校验（照 --model 闸门那套）—— 非法值退 2、
    #   零副作用（不起进程、不建 log、不写判决）、点名合法值。值域以 CLI --help 为准。
    if args.effort is not None and args.effort not in EFFORT_LEVELS:
        print(f"[FAIL] 未授权的思考等级，已拒绝派活：{args.effort}\n"
              f"合法值（CLI 2.158.0 的 --help）：{'、'.join(EFFORT_LEVELS)}",
              file=sys.stderr, flush=True)
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
    # ★ 卡 190（T-G290）F1：登录自检移出 preflight —— 要用 profile 合成的环境 + 要用的 --model
    #   发探针，而 profile 环境在 preflight **之后**才取。改成：preflight 不做 auth
    #   （check_auth=False），account_env 取好之后由 main 自己用「那个号 × 那个模型」组合发探针。
    #   ★ 不给 --account ⇒ env=None, model=None ⇒ auth_ok 逐字不变（父进程环境、不带 --model）。
    problems, log = preflight(
        args.card, args.spec, force=args.force, check_auth=False,
        cli_override=args.cli, resuming=bool(resume_sid), allow=args.allow,
        port_bases=port_bases, worker_cwd=worker_cwd,
        already_reserved=args.already_reserved, project=args.project,
    )

    # ★ 卡 149（T-G249）：多号 profile —— 起工人**之前**先把那组环境变量取好。
    #   ★ 不给 `--account` ⇒ `worker_env=None` ⇒ 工人**逐字继承**今天的家目录（行为一字不变）。
    #   ★ 给而拿不到 ⇒ 并入前置检查的问题清单 ⇒ **拒绝派活并点名**（走同一套留痕 / 退出码 2）
    #     —— **绝不悄悄退回默认号**（那会让工人跑到别的号上）。
    account_vars: dict[str, str] = {}
    if args.account:
        try:
            account_vars = account_env(args.account)
        except AccountError as exc:
            problems.append(str(exc))

    # ★ 卡 A348（F32 调用方名册）：这个人还在吗 —— 撤了（`off = true`）就**不派活**。
    #   ★ 名册是**加法**：文件不在 / 这个人没登记 ⇒ 一律放行（落地当天零行为变化）。
    #   ★ 名册**在但读不懂** ⇒ 拒派并点名（`CallersError`）—— 坏配置绝不当「没配」。
    #   ★ 复用下面的 `problems` 出口（打印 + 退 2）：不新开退出码、不碰 `reserve()` 签名。
    #     pool 依赖块整块在 `sys.path.insert` 之后（E402）⇒ 照 `caller_model_patterns()`
    #     的先例走**函数内 import**（本文件铁律：不写那类豁免注释）。
    from pool import callers as pool_callers

    try:
        this_caller = pool_callers.resolve(
            args.caller or "", env_window=os.environ.get("TF_WINDOW_ID", "")
        )
    except pool_callers.CallersError as exc:
        problems.append(f"调用方名册读不了，**不派活**：{exc}")
    else:
        if pool_callers.is_off(this_caller):
            problems.append(
                f"调用方 {this_caller.id}（{this_caller.label or '无名'}）已撤"
                "（off = true）—— 不许派活"
            )

    # ★ 卡 149：profile 取到了 ⇒ 与现进程环境合成一份交给工人（**不给 = None = 逐字继承**）。
    #   ★ 放在 `--detach` **之前**：坏 profile 在**父进程**就拒（脱离子进程带 `--detach-done`，
    #     会自己再取一次同一份数据 —— 幂等）。
    worker_env: dict[str, str] | None = None
    if args.account and account_vars:
        worker_env = {**os.environ, **account_vars}

    # ★ 卡 154（T-G254）：登录自检三态 + 重试一次 —— 分得清「真没登录」与「探失败」。
    #   旧口径：auth_ok 返 False 就一律拒（探失败也当没登录 → 当晚假红三次：
    #     白等 + 换号 + 白花额度）。
    #   新口径：preflight_auth 三态 ——
    #     · OK              → 放行；
    #     · NEEDS_LOGIN     → 拦 + 提示 /login（明确拿到 Authentication required）；
    #     · INCONCLUSIVE    → 两次探都失败 → 拦 + 提示「要么 /login 要么 --no-preflight」，
    #                        **不许静默按「没登录」处理**（卡规格硬要求）。
    #   ★ 卡 190 的 env/model 透传一字不动（只在它之上加三态与重试，不推回 190）。
    #   ★ 不给 --account ⇒ env=None, model=None ⇒ 逐字不变（与卡 149 硬要求 2 同）。
    node, cli = paths(args.cli)
    if not args.no_preflight and not problems:
        state, why = preflight_auth(node, cli, env=worker_env,
                                    model=args.model if args.account else None)
        if state is AuthState.OK:
            pass  # 放行 —— 「登录通」由后面 done_checks 那段统一打
        elif state is AuthState.NEEDS_LOGIN:
            problems.append(why)
        else:  # AuthState.INCONCLUSIVE —— 两次都探失败
            problems.append(why)

    # ★ 卡 190（T-G290）F2 子进程侧读数：派活前用 worker_env 起子进程读自己的环境回话 ——
    #   不再"自己打印自己"（[账号] 那行只是留痕，不是判据）。接缝断了 ⇒ 拒派。
    #   ★ 不给 --account ⇒ 不跑（逐字不变）。
    if args.account and worker_env and not problems:
        probe_ok, probe_msg = _account_env_probe(worker_env, account_vars)
        if not probe_ok:
            problems.append(probe_msg)
        else:
            print(f"[账号自检] {probe_msg}", flush=True)

    # ★ 卡 A350（T-AG562）：限额闸（F33 判据层第一次有生产调用方）。位置固定在
    #   **占树之前、既有 `if problems:` 出口之前** —— 判不过就并进 problems，走同一条
    #   `[FAIL] 不派活 —— 前置检查没过：` 出口（退 2，**不新开退出码**）。
    #   ★ 判据 2：`limits` 的键是**稳定 id**（`account_id`，与租约 / RPM / lanes 同一个键），
    #     不是 `args.account` 的 profile 名；`spent[i]` 的窗口用
    #     `limits_policy.window(limits[i], now)` 算，求和使用 `ledger_spend.sums(...)`，
    #     两边**必须同一个 `now`** —— 所以这里只取一次时间，往下传同一个对象。
    #   ★ 判据 5：策略文件存在但读不懂 ⇒ `LimitError` ⇒ **拒派**并说清哪一段坏了，
    #     **不许**吞成「没设限额」（那是悄悄松开判据）。
    #   ★ 判据 4：文件不存在 ⇒ `load_limits()` 回 `{}` ⇒ 这一段一个副作用都没有。
    if account_id:
        from pool import ledger_spend as pool_ledger_spend
        from pool import limits_check as pool_limits_check
        from pool import limits_policy as pool_limits_policy
        try:
            limits = pool_limits_policy.load_limits().get(account_id, ())
        except pool_limits_policy.LimitError as exc:
            limits = ()
            problems.append(f"限额策略读不懂 ⇒ 拒派（不许当成「没设限额」）：{exc}")
        if limits:
            limit_now = datetime.now(pool_limits_policy.TZ)
            spent: dict[int, tuple[int, float]] = {}
            try:
                for index, limit in enumerate(limits):
                    start, end = pool_limits_policy.window(limit, limit_now)
                    tokens, cost, _calls = pool_ledger_spend.sums(
                        account_id, start, end, cache_reads=limit.cache_reads, root=ROOT)
                    spent[index] = (tokens, cost)
                limit_verdict = pool_limits_check.check(limits, spent=spent, now=limit_now)
            except pool_limits_policy.LimitError as exc:
                limit_verdict = None
                problems.append(f"限额窗口算不出来 ⇒ 拒派：{exc}")
            if limit_verdict is not None and not limit_verdict.allowed:
                reset_at = (limit_verdict.reset_at.isoformat()
                            if limit_verdict.reset_at is not None else "（未知）")
                problems.append(
                    f"限额已满（号 {account_id}）：{limit_verdict.why}；"
                    f"reset_at={reset_at}；retry_after_s={limit_verdict.retry_after_s}"
                    f"（等 {limit_verdict.retry_after_s} 秒再来）⇒ 不占树、不派活")

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

    # ★ 卡 A342：账号白名单（每 caller）。放在**占树之前** —— 这里还没 `reserve()`、
    #   也没归档，拒了就是零副作用；`--detach` 的父进程也会在把工人扔出去之前先拒。
    #   `--account` 今天传的是 profile 名，白名单里写的是账本 id（卡 A344 之后两者合一）：
    #   这里**不映射、不猜形状**，只把它当不透明的键交给 `account_guard` 查表。
    if args.account:
        from pool import accounts_scope as pool_accounts_scope

        try:
            scopes = pool_accounts_scope.load_scopes()
        except pool_accounts_scope.ScopeError as exc:
            print(f"[FAIL] 账号白名单读不了，**不派活**：{exc}", file=sys.stderr, flush=True)
            return 2
        account_problems = pool_guards.account_guard(
            args.account,
            scopes,
            card=args.card,
            project=args.project or "",
            pool=args.pool,
        )
        if account_problems:
            print("[FAIL] 账号不在白名单里，**不派活**：", file=sys.stderr, flush=True)
            for item in account_problems:
                print(f"  · {item}", file=sys.stderr, flush=True)
            return 2

    # ★ 留痕（不是判据；判据是上面的子进程侧读数）。
    if args.account and worker_env:
        print(f"[账号] profile「{args.account}」并入 {len(account_vars)} 个环境变量："
              + "；".join(f"{k}={v}" for k, v in account_vars.items()), flush=True)

    # ★★ 卡 164（T-G264）：归档旧判决**必须**在 detach 父进程 return **之前** ——
    #   旧写法把 archive_stale_artifacts 放在 detach return 之后（原 line 2473），于是
    #   `--force --detach` 时父进程 return 0、旧判决还在原位；子进程起来到归档之间有一个
    #   **时序窗口**，谁读判决都读到旧的（146 现场就是它：23:10「没派活」的旧判决在
    #   23:40 真跑完前一直冒充当前状态）。改法：真跑（--execute）才归档，且在 detach 之前。
    #   ★ dry-run 不归档（args.execute 守卫）；子进程带 --detach-done 时旧判决已被父进程
    #   归档，再调一次找不到文件、返回空，幂等。
    if args.execute:
        archived, archive_failures = archive_stale_artifacts(args.card)
        if archived:
            print(f"[归档] 旧判决/摘要已归档：{', '.join(archived)}", flush=True)
        if archive_failures:
            # ★ 卡 156：归档失败必须出声 —— 旧判决留在原地会冒充当前状态（146 现场）
            print("[归档失败] 以下旧件没归成（留在原地，可能冒充当前状态，请手工挪走）："
                  f"{'; '.join(archive_failures)}", file=sys.stderr, flush=True)

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
        # ★ 卡 215（T-G328）：`--detach` 出去之后**没有回推通道**，别靠人记着轮询 ——
        #   挂上 `wb_watch`（只读看守）就默认收工出结论。
        # ★ 卡 E7（T-AG453）：这行从「请你自己挂」改成「已经替你挂好了」——
        #   真挂看守在下面（`ensure_watch`）；这里保留可照抄的重挂命令（老窗口的肌肉记忆）。
        print(f"[看 ] 重挂/单看：python -X utf8 tools/wb_watch.py --cards {args.card}"
              f" --write-done", flush=True)
        # ★ 卡 E7 判据 1/3：真派活才挂看守；`--no-watch` 必须**明说**（不静默）。
        if args.execute:
            if args.no_watch:
                print(no_watch_notice(), flush=True)
            else:
                print(ensure_watch(args.card, mode=args.watch,
                                  timeout=watch_horizon(args.timeout, args.retry)),
                      flush=True)
        print(f"[log ] {detach_log}", flush=True)
        return 0

    # ★ 卡 A297（T-AG411）：派活成功后自动起 `wb_notify.py --daemon`（若没起）——
    #   收工自动落盘 notifications.jsonl + 面板可见，不靠人记。失败只告警，不让派活失败。
    #   ★ 放在 detach 块**之后**：父进程（--detach）已 return，这里跑的是**子进程**
    #   （带 --detach-done）与同步 --execute 路径；用 args.detach_done 守卫 ⇒ 只在
    #   「真脱离开跑」时起，同步 --execute（自己看着终端，没有回推缺口）不起多余的。
    if args.detach_done:
        ensure_notify_daemon(ROOT)

    max_turns = args.max_turns or max_turns_default(args.read_only)
    lean_brief = ensure_lean_brief(args.card, worker_cwd) if args.lean else ""
    domain_hint = domain_path_hint(args.card, worker_cwd)
    # ★ 卡 224（T-G338）：工作台状态一处真源 —— 派活器**改用它**拼开场白（只加不改；
    #   不给 --cwd ⇒ 空串，开场白逐字不变）。
    workbench_text = workbench_brief_text(args.card, worker_cwd)
    initial_cmd = build_command(node, cli, args.card, prompt_path(args.spec, worker_cwd),
                                args.model, args.permission_mode,
                                max_turns=max_turns, autocompact=args.autocompact,
                                lean=args.lean, brief=prompt_path(lean_brief, worker_cwd),
                                effort=args.effort, domain_hint=domain_hint,
                                workbench_text=workbench_text)

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
    # ★ 卡 167（T-G267）：[cmd] 摘要也带上 --effort（给了才带，不给 = 逐字不变）
    effort_tag = f" --effort {args.effort}" if args.effort else ""
    print(f"[cmd ] {' '.join(initial_cmd[:4])} … --model {args.model} --output-format stream-json "
          f"--permission-mode {args.permission_mode} --max-turns {max_turns} "
          f"--autocompact {args.autocompact}{effort_tag}", flush=True)
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

    # ★ 卡 E7（T-AG453）判据 1：**派活即看守** —— 真起工人之前把看守挂上（免得人记着起）。
    #   `--detach` 的父进程已在上面那一段挂过；这里只管同步 `--execute` 与内部 `--detach-done`
    #   （后者父进程已挂，跳过 —— 一份活只要一份看守）。
    if not args.detach and not args.detach_done:
        if args.no_watch:
            print(no_watch_notice(), flush=True)
        else:
            print(ensure_watch(args.card, mode=args.watch,
                                  timeout=watch_horizon(args.timeout, args.retry)),
                      flush=True)

    # ★ 卡 029 §2.7：每次真开跑记规格指纹；续跑且指纹变了 → 硬塞「先读规格」进续跑提示词。
    spec_digest = spec_fingerprint(args.spec)
    spec_preamble = ("" if not resume_sid
                     else spec_changed_notice(prompt_path(args.spec, worker_cwd), log))
    spec_file_for(log).parent.mkdir(parents=True, exist_ok=True)
    spec_file_for(log).write_text(f"{args.spec}\nsha256={spec_digest}\n", encoding="utf-8")

    # ★ 卡 163 INV-40：续跑时从已有轮次的下一个开始 —— 旧证据不许被覆盖。
    #   非续跑（resume_sid 空）⇒ first_attempt=1（仍*仍*用 wb-<卡>.jsonl，向后兼容）；
    #   续跑 ⇒ 扫已有 wb-<卡>.r*.jsonl + wb-<卡>.jsonl，从 max+1 起（不覆盖任何旧证据）。
    if resume_sid:
        _rounds_seen = [1] if log.exists() else []
        for _p in log.parent.glob(f"wb-{args.card}.r*.jsonl"):
            _m = re.match(rf"^wb-{re.escape(args.card)}\.r(\d+)\.jsonl$", _p.name)
            if _m:
                _rounds_seen.append(int(_m.group(1)))
        first_attempt = max(_rounds_seen) + 1 if _rounds_seen else 1
    else:
        first_attempt = 1

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
        # ★ 卡 163 INV-39：派活前先清死租约 —— 被强杀的工人留的租约，
        #   下一位不该只能靠"读者过滤"（list_reservations 只读不清）。prune 落盘 + 说清清了什么。
        try:
            _pruned = pool_registry.prune()
            if _pruned:
                print(f"[清租] 派活前清掉 {_pruned} 条死租约（日志已死/TTL 过期）", flush=True)
        except pool_registry.RegistryError as _exc:
            print(f"[清租] 读不了登记，跳过清理：{_exc}", file=sys.stderr, flush=True)

        reserve_files, reserve_why = queue_files(args.card)
        if reserve_why:
            print(f"[FAIL] {reserve_why}", file=sys.stderr, flush=True)
            return 2
        try:
            reserve_root = pool_registry.main_tree_root()
        except pool_registry.RegistryError as exc:
            print(f"[FAIL] 算不出主工作树 ⇒ 不占树、不派活：{exc}", file=sys.stderr, flush=True)
            return 2
        # ★ 卡 A340（T-AG542）：**每分钟派活闸** —— magpie 的 MaxRPM 移植
        #   （判据在 tools/pool/rpm.py）。
        #   ① 位置固定在**占树之前**：判不过 ⇒ 一眼 exit 2、**不占树、零副作用**（判据 4）。
        #   ② 不给 `--account` ⇒ 整套跳过（今天的行为逐字不变）。
        #   ③ 「读 → 判 → 写」在**同一把** `spin_lock` 里（判据 5）：两个窗口同时派同一个号时，
        #      只有第一个看得到空账本；拆成两段持锁就会双双放行。
        #   ④ 只有**开了闸**（limit > 0）的号才落时刻：0 = 不限，账本不给没开闸的号留垃圾。
        #   ⑤ ★ 卡 A340 裁定 1：判完就写（同一把锁内），**占树没成就还回去** —— 照 magpie 的
        #      `reserve()`（`rpm.go:122-138`，持锁时就追加）+
        #      `giveBack()`（`:141-154`，没派成按值删回）。
        #      如实说的缺口：magpie 的回滚挂在 ctx 取消上，pool 没有等价的可取消边界 ——
        #      进程被强杀 / 异常退出**不会**还，只能等那一趟 61 秒后自己滑出窗口。
        #   ★ `stamps_target` 在闸外就算出来：`give_back_stamp` 也要用它
        #     （同一把锁 = 同一个锁文件）。
        stamps_target = ROOT.joinpath(*pool_rpm.STAMPS_REL)
        rpm_at: datetime | None = None
        # ★ 卡 A344：闸的键是**账本稳定 id**（`rpm.toml` 的 `[accounts."codebuddy-tongxue3"]`），
        #   不是 `--account` 收到的 profile 名 `tongxue3`。读写两侧都用同一个 `account_id` ——
        #   只改写侧不改读侧，闸会恒放行（记在 id 名下、读在名字名下）。
        if account_id:
            try:
                with pool_task.spin_lock(stamps_target, timeout=RPM_LOCK_WAIT):
                    rpm_now = pool_rpm.now_tz()
                    rpm_limit = pool_rpm.load_rpm().get(account_id, 0)
                    rpm_stamps = pool_rpm.read_stamps(root=ROOT).get(account_id, [])
                    rpm_verdict = pool_rpm.decide(account_id, rpm_stamps,
                                                  limit=rpm_limit, now=rpm_now)
                    if not rpm_verdict.allowed:
                        print(f"[FAIL] 每分钟派活闸：号「{args.account}」{rpm_verdict.why}"
                              " ⇒ 不占树、不派活", file=sys.stderr, flush=True)
                        return 2
                    if rpm_limit > 0:
                        pool_rpm.note_stamp(account_id, rpm_now, root=ROOT)
                        rpm_at = rpm_now
            except pool_rpm.RpmError as exc:
                print(f"[FAIL] 每分钟派活闸判不了（配置/账本坏了，**不猜**）：{exc}",
                      file=sys.stderr, flush=True)
                return 2
            except pool_task.BatchError as exc:
                print(f"[FAIL] 每分钟派活闸拿不到锁 ⇒ 不派活：{exc}", file=sys.stderr, flush=True)
                return 2

        def give_back_stamp(why: str) -> None:
            """把这一趟的分钟位**还回去** —— 对应 magpie 的 `giveBack`（幂等，还没记过就是空操作）.

            ★ **同一条路径不许还两次**：还完就把 `rpm_at` 抹成 None（重复还只是白做一次读写）。
            ★ 还不上**不许**盖掉原本的失败原因：只白占一个分钟位（61 秒后自己滑出窗口），
              所以这里吞掉异常、但**必须**喊一声 —— 静默吞掉下一个人会以为账本干净。
            """
            nonlocal rpm_at
            if rpm_at is None:
                return
            stamp, rpm_at = rpm_at, None
            try:
                with pool_task.spin_lock(stamps_target, timeout=RPM_LOCK_WAIT):
                    pool_rpm.give_back(account_id, stamp, root=ROOT)
            except (pool_rpm.RpmError, pool_task.BatchError, OSError) as exc:
                print(f"[FAIL] 每分钟派活闸还不回去（{why}）：{exc}"
                      " ⇒ 这一趟白占一个分钟位，61 秒后自己滑出窗口",
                      file=sys.stderr, flush=True)
                return
            print(f"[还闸] 已去掉这一趟的派活记录（卡 {args.card}；{why}）", flush=True)

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
        #   ★ 卡 163 INV-40：续跑时 lease 的 log 用 first_attempt 那一轮的 log_k
        #     （wb-<卡>.r<N>.jsonl），这样日志判死看的是真在跑的那一轮，不是被覆盖的第 1 轮。
        if first_attempt > 1:
            _first_log = log.with_name(f"wb-{args.card}.r{first_attempt}.jsonl")
            lease_log = lease_log_for(_first_log)
        else:
            lease_log = lease_log_for(log)
        # ★ 卡 149：留痕 —— 这一趟是哪个号跑的，一眼可查（与 `project` / `model` 同一风格）。
        #   ★ 不给 `--account` 时**逐字不变**（仍是 `spec=…`），免得打穿既有读数。
        #   ★ 卡 A344：note 里留的是**人给的名字**（给人看的），而 `account=` 传的是**稳定 id**
        #     （给 lanes 守卫查表用的）—— 两者都要，别合并：一个给人读、一个给判据读。
        # ★ 卡 A348：`caller=` 与 `account=` **并列**（一个答「谁在用」、一个答「用哪个号」），
        #   不给 `--caller` 时逐字不变 —— 免得打穿既有读数。
        lease_note = f"spec={args.spec}" + (f"｜account={args.account}" if args.account else "")
        if args.caller:
            lease_note += f"｜caller={args.caller}"
        try:
            # ★ 卡 A345（rebase 到 A344 之后）：`account=` 由 **A344** 传（稳定 id，给 lanes
            #   守卫查表用）—— 本卡原来那句 `account_kw` 已被它取代，**删掉不重复传**：
            #   粘性命中的号同样是走 `args.account` ⇒ 这里自动跟着它走，判据 7 的
            #   「`reserve(account=…)` 收到那个号」由 A344 这一行满足。
            lease = pool_registry.reserve(args.card, tree=reserve_tree, files=reserve_files,
                                          project=args.project or "", model=args.model,
                                          log=lease_log,
                                          note=lease_note,
                                          account=account_id,
                                          lock_body=pool_registry.read_lock_body())
        except pool_registry.GuardError as exc:
            print("[FAIL] 占树被守卫拦下，**不派活**：", file=sys.stderr, flush=True)
            for item in exc.problems:
                print(f"  · {item}", file=sys.stderr, flush=True)
            give_back_stamp("占树被守卫拦下")
            return 2
        except pool_registry.RegistryError as exc:
            print(f"[FAIL] 占树失败（登记坏了），**不派活**：{exc}", file=sys.stderr, flush=True)
            give_back_stamp("占树失败（登记坏了）")
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

    attempts, code, reason, scene, sid = first_attempt, 0, "", "", resume_sid
    model = args.model                       # 429 三拍会按序换（只换白名单里的）
    quota_seen: dict[str, str] = {}          # 每个模型撞的额度错（全挂就停时写进判决）
    usage_total = {"input_tokens": 0, "output_tokens": 0, "cache_read": 0}
    # ★ 卡 A349：耐心预算（0 = 关）+ 已重问几轮 + `--quota-wait` 原件（每轮复位用）
    patience_left_s = pool_quota.patience_waits(args.patience)
    patience_round = 0
    quota_wait_s = args.quota_wait

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
                                lean=args.lean, brief=prompt_path(lean_brief, worker_cwd),
                                effort=args.effort, domain_hint=domain_hint,
                                workbench_text=workbench_text)
        elif sid:
            prompt = continuation_prompt(reason=reason or "上次被中断", scene=scene,
                                         card=args.card)
            # ★ 卡 029 §2.7：规格改过 → 「先读规格」硬塞在续跑提示词**最前面**（光说"规格改了"
            #   它会锚在旧上下文里当没看见 —— 卡 022 白跑两轮的真因）。
            cmd = resume_command(node, cli, sid, spec_preamble + prompt,
                                 model, args.permission_mode,
                                 max_turns=max_turns, autocompact=args.autocompact,
                                 effort=args.effort)
        else:
            print("[续 ] 没拿到 session id，续不了 → 只能重开一轮", file=sys.stderr, flush=True)
            cmd = build_command(node, cli, args.card, prompt_path(args.spec, worker_cwd),
                                model, args.permission_mode,
                                max_turns=max_turns, autocompact=args.autocompact,
                                lean=args.lean, brief=prompt_path(lean_brief, worker_cwd),
                                effort=args.effort, domain_hint=domain_hint,
                                workbench_text=workbench_text)
        print(f"[跑 ] 第 {attempts} 次；log {log_k.name}", flush=True)
        attempt_started = time.time()
        code, reason, scene, new_sid = run_worker(
            cmd, log_k, log_k.with_suffix(".stderr.txt"), timeout=args.timeout,
            max_turns=max_turns, watchdog=not args.no_watchdog,
            heartbeat_seconds=args.heartbeat_seconds, stall_seconds=args.stall_seconds,
            poll_seconds=args.poll_seconds, printer=beat, worker_cwd=worker_cwd,
            worker_env=worker_env,
        )
        sid = new_sid or sid
        if sid:                      # ★ 一拿到就落盘：这样中断之后 `--resume auto` 才用得上
            session_file_for(log).write_text(sid, encoding="utf-8")
        round_lines = wb_status.read_log_lines(log_k)
        # ★ 卡 029 §2.6：用量落账（无论成败）—— 数从 CLI 的 result.usage 拿，别自己估。
        usage = result_usage(round_lines)
        for key in usage_total:
            usage_total[key] += usage[key]
        # ★ 卡 A350（T-AG562）：限额账本写回 —— 与上一行**同一处、同一轮**：数还是 `usage`
        #   那三个计数器（CLI 自己报的，**不自己估**），`at` 用这一轮的**开始**时间
        #   （窗口归属才和上面 `sums()` 的口径对得上）。
        #   ★ 走 `ledger_spend.append()`（**不许**在这里另写一份 JSONL —— 那是第二份真源）。
        #   ★ `cost` 恒写 `0.0`：vendor 自报里没有金额 ⇒ **不编乘数**。这意味着 cost 轴今天
        #     永远不涨，「按钱限额」那一支实际不生效（只有 tokens 轴真在拦）——这条落差
        #     在卡的回执与变更记录里说实话，不在这里偷偷补一个乘数。
        #   ★ 空账号（没给 `--account`）⇒ **整行不写**：否则账本里全是空账号，
        #     按号求和 / 按号判限额的读数全被污染。
        if account_id:
            from pool import ledger_spend as pool_ledger_spend
            try:
                pool_ledger_spend.append(
                    account_id, args.card, model,
                    input_tokens=usage["input_tokens"],
                    output_tokens=usage["output_tokens"],
                    cache_read=usage["cache_read"],
                    cost=0.0,
                    at=datetime.fromtimestamp(attempt_started, tz=pool_ledger_spend.TZ),
                    root=ROOT)
            except (OSError, ValueError) as spend_exc:   # 记不下来不许影响派活
                print(f"[账 ] 用量没记进限额账本：{spend_exc}（不影响这次派活）",
                      file=sys.stderr, flush=True)
        # ★ 卡 A355（判据 2）：`handed_on` 必须在**写之前**就知道 —— 所以把下面 `:4020`
        #   那次 `should_resume()` 前移到这里算**一次**、存成局部变量，两处复用同一份结论
        #   （判据只有一份：**不许**在 `:4020` 再调一次，也不许写完再回头补第二行）。
        #   `handed_on = 这一轮失败 且 之后确实会续`（两条缺一不可：不失败就不是交出去，
        #   不会续就没人接住）。
        #   ★ 如实记一处落差：429 三拍那段（下面 `quota is not None`）也会 `attempts += 1`
        #     接着干，但它的判断在**本行之后**（`quota_error(round_lines)` 在那里才解析）⇒
        #     那一轮的 `handed_on` 会留在 `False`。本卡不动 A351 的地盘，这条写进回执与变更
        #     记录：额度换模型那条路今天**低估** `handed_on`（如实，不补写）。
        #   ★ 还有一条同型的：下面「预算用尽」那一支也会 `break`（止损，不是失败）——
        #     它同样在**本行之后**才判，所以这里把它一并算进来：会被预算掐掉的那一轮
        #     也不算「交出去」（没人接住）。`usage_total` 在上面已经加过这一轮的用量，
        #     所以这里算出来的结论与下面那一支**逐字一致**（判据仍然只有一份）。
        resume_next = should_resume(reason, attempts, args.retry)
        budget_stop = bool(args.input_budget
                           and usage_total["input_tokens"] >= args.input_budget)
        handed_on = pool_outcomes.is_failed(code, reason) and resume_next and not budget_stop
        append_usage_line(card=args.card, model=model, attempt=attempts,
                          started_at=attempt_started, usage=usage, code=code, reason=reason,
                          # `tries` 只写在**结局**行上（判据 5）：交出去的行恒 1；
                          # 结局行 = 本请求到这一轮为止试了几轮（含自己）。
                          tries=1 if handed_on else attempts - first_attempt + 1,
                          handed_on=handed_on, stop="")
        # ★ 卡 A345（T-AG547）：接入点 2 —— 记下「这张卡这次是谁答的」。与用量落账**同一处**
        #   （同一缩进层级、同一轮）：写在 dry-run 之后，`--execute` 之前那段一个字节没碰。
        if args.sticky:
            try:
                pool_sticky.note(pool_sticky.Stick(
                    card=args.card, account=args.account or "", tree=reserve_tree,
                    session=sid or "", model=model, at=time.time(),
                    why=pool_sticky.WHY_CARD if args.account else pool_sticky.WHY_FIRST))
            except (OSError, ValueError) as sticky_exc:   # 记不下来不许影响派活
                print(f"[粘 ] 记录没写成：{sticky_exc}（不影响这次派活）",
                      file=sys.stderr, flush=True)
        # ★ T-G95：**每一条退出路径都落一份摘要**（含"被掐后再续跑"的每一轮），主控只读它。
        report = write_report(log_k, card=args.card, code=code, reason=reason, scene=scene,
                              sid=sid, attempts=attempts, lines=round_lines,
                              started_at=attempt_started)
        # ★ T-G96：判决**按轮落**（`wb-<卡>.r2.verdict.txt`…）—— 第 2 轮不许覆写第 1 轮的。
        verdict = write_verdict(log_k, card=args.card, attempts=attempts, code=code, reason=reason,
                                sid=sid, lines=round_lines,
                                errlog=log_k.with_suffix(".stderr.txt"),
                                started_at=attempt_started)
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
            # ★ 卡 201（T-G303）：把这次 429 落成一条记录 —— 解析在 `pool_quota.record` 里
            #   （判据只许一份真源）。落记录失败不许影响派活主流程。
            with contextlib.suppress(OSError, ValueError):
                pool_quota.record(card=args.card, model=model, pool=pool,
                                  kind=quota["kind"], reset_raw=quota["reset"],
                                  source_log=log_k.name, root=ROOT)
            # ★ 卡 A349：全都忙就歇一会儿再问（算术只在 pool_quota 里，判据一份真源）。
            #   只有「限流」进门：「余额耗尽」是硬挡，等多久都不会好 —— 照旧走到界出口。
            #   耐心不越过下面卡 045 的 `--retry` 界：它只管这一歇歇多久、还能歇多久。
            args.quota_wait = quota_wait_s    # 每轮先复位：耐心不生效时与今天逐字相同
            if quota.get("kind") == "限流" and patience_left_s > 0 \
                    and patience_round < pool_quota.REPLAN_ROUNDS:
                # 成员自报的续期只做下限：先按记录折成秒（没记录就是 0）。
                # ★ `upper` 给一个大数 = 「只解析、不封顶」：`wait_seconds` 默认把 fallback
                #   当**上限**，传 0 会恒得 0（那就等于这一层没接）—— 这里要的是原始 diff。
                soonest_s = pool_quota.wait_seconds(quota.get("reset_at"), 0, upper=10 ** 9)
                pause = pool_quota.replan_wait(patience_round, soonest_s=soonest_s)
                if pause > patience_left_s:
                    print(f"[耐心] 这一歇要 {pause}s，预算只剩 {patience_left_s}s"
                          " → 不再重问（照旧走到界出口，退出码不变）",
                          file=sys.stderr, flush=True)
                else:
                    patience_left_s -= pause
                    patience_round += 1
                    args.quota_wait = pause   # 这一歇就是下游 wait_seconds 的封顶
                    print(f"[耐心] 第 {patience_round} 次重问：最多歇 {pause}s"
                          f"（预算还剩 {patience_left_s}s）",
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
            # ★ 卡 201（T-G303）：等待按记录算 —— reset_at 在 1 分钟后 ⇒ 等 60 秒（不睡满 300）；
            #   reset_at 解析不出 ⇒ 退回 --quota-wait。上限 = --quota-wait（不让坏记录冻几小时）。
            wait = pool_quota.wait_seconds(quota.get("reset_at"), args.quota_wait)
            if wait > 0:
                _reset = quota.get("reset_at") or "（无）"
                print(f"[额度] 等 {wait}s 再探（按记录算；reset_at={_reset}）", flush=True)
                time.sleep(wait)
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
                # ★ 卡 A351（T-AG563）：探针仍挂 ⇒「这个 key 现在真的不能用」→ 沉底
                #   （magpie `sinkOrder`；沉的是「这次撞限流的那个 key」）。
                #   沉不沉**只问** `should_sink()`（`余额耗尽` 由它内部硬拦，调用侧不加旁路）。
                if pool_sink.should_sink(quota.get("kind"), SINK_ROUTING):
                    pool_sink.sink(pool_sink.key_of(account_id, model), root=ROOT)
                nxt = next_whitelist_model(model, pool)
                # ★ 卡 A351 判据 6：换之前先看**整条尾巴**（含 `nxt` 自己）—— 全沉过 ⇒ 置 None，
                #   落进下面既有的停路（退出码 7）；尾巴里只要有一个没沉过，就照旧换过去。
                tail = rotation_chain_for(pool)
                rest = tail[tail.index(nxt):] if nxt is not None and nxt in tail else ()
                if rest and all(pool_sink.sunk_at(pool_sink.key_of(account_id, m), root=ROOT)
                                is not None for m in rest):
                    nxt = None
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
        if not resume_next:      # ★ 卡 A355：复用上面**写之前**算好的那一份结论，不调第二次
            break
        attempts += 1
        print(f"[续 ] 第 {attempts} 次：带同一会话接着干（原因：{reason}）", file=sys.stderr,
              flush=True)

    # ★ 卡 125：工人已收工 / 已被判死 → 还树（`--detach` 的那条路里，跑这一段的正是脱离子进程）。
    #   循环内那几个 `return 7`（额度全挂）由 `atexit` 兜底 —— 任何退出路径都会还一次。
    release_tree("工人收工")

    print(f"[会话] {sid or '（没见到 session_id）'}"
          f"（落盘 {session_file_for(log).name}；续跑：--resume auto）", flush=True)
    lines = wb_status.read_log_lines(log_k)
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
