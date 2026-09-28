# Trae 池适配器 `tools/trae_pool.mjs`（卡 077 · 台账号 `T-G172`）

> 一句话：把主控 2026-09-27 深夜用 CDP 试通的 **TraeCode IDE 驱动**正式化成两条子命令的工具
> （`balance` 读免费积分 / `send` 发指令+自动授权+判完成+记账），**零新依赖**（Node 22 内建
> `WebSocket` + `fetch` + `child_process`）。底座 `d842771`。

## §1 用法（就是卡 §1.1 的两条）

```
node tools/trae_pool.mjs balance  [--port 9333]
node tools/trae_pool.mjs send --workspace <目录> --prompt-file <文件> --log <jsonl> --out <md> \
     [--port 9333] [--timeout-sec 3600] [--no-launch]
```

- `balance`：连 CDP，读 `.icube-titlebar-cn-free-upgrade-button` 的积分文本并打印，退出码 0；连不上 **2**。
- `send`：未给 `--no-launch` 且 9333 连不上 → 起 IDE（`D:\Trae CN\Trae CN.exe --remote-debugging-port=<port> <工作区>`，
  detached+unref）；`insertText` 打字 → Enter 发送；每 3 秒自动点授权 + 判完成；
  收工把**最后一条 agent 轮次**写 `--out`，打印一行摘要。退出码：完成 **0** / 超时 **3** / 连不上 CDP **2**。
- 退出码 `balance` 不拉 IDE（只读）。

## §2 实测读数（2026-09-28，本机 TraeCode 3.3.104）

| 项 | 读数 |
|---|---|
| `node --check tools/trae_pool.mjs` | **退出码 0**；文件 **371 行** |
| 冒烟（提示词「只回两个字：在吗」） | `[trae] DONE sec=15 turns=5 balance 4,544->4,544`，**退出码 0** |
| `--out` 原文 | `Agent` / `思考过程` / `在吗` / `10%`（即最后一条 agent 轮次，含 10% 上下文用量徽标） |
| 冒烟 log（JSONL） | **10 行**：`connect`×1 · `balance(value)`×1 · `send`×1 · `poll`×5 · `balance(before/after)`×1 · `done`×1；`approve`×**0** |
| 拉起 IDE | 冒烟前 9333 **未监听**（`curl /json/version` 空）→ 脚本自起 IDE，之后 9333 存活、后续冒烟直接连 |
| `balance` 子命令 | 打印 `4,544`，退出码 0 |
| 本卡消耗积分 | 约 **1 个**（主要花在「跑一会儿」的诊断任务上：4,545→4,544；三条「只回两个字：在吗」的冒烟**没扣分**，前后都是 4,544） |

### §2.1 ★ 两处与卡规格原文不一致的实测发现（如实记）

卡 §1.5 给的完成判据是 `done = /任务耗时/.test(last) && !busy`。实测在本机**不成立/不够**，两处：

1. **`任务耗时` 在"纯文字回复"的轮次里根本不出现**。探针（边跑边读 DOM）显示：
   一条**没有调用工具**的回复（如「在吗」），最后一条 agent 轮次里**没有** `任务耗时` 字样 →
   照卡原文判定，冒烟会**白等到超时**（实测第一趟确实 300 秒超时、退出码 3）。
   而一条**跑了 4 条命令**的任务，轮次里**有** `任务耗时 3m 17s` → 这条路径是好的。
   → 现场补的判据：**发送键 `.chat-input-v2-send-button` 的 `disabled`** ——
   生成中它**不带** `disabled`（此刻它是"停止"键）、`busy=true`；完成时它**带** `disabled`、`busy=false`。
   实测定稿：`isDone = 新轮次 && (卡原文 specDone || 连续 2 拍(!busy && sendDisabled))`。
   （读数为证：生成中 `busy:true, sendDisabled:false`；完成 `busy:false, sendDisabled:true`。）
2. **最后一条 `.turn__agent-message` 的 `innerText` 会混进 chrome 小挂件**：实测两个 ——
   一个**回显"之前某条用户话"**、一个是「好的，执行吧」这类**建议块**。直接取 innerText 当回复会脏。
   结构上：**正文与工具块都带 `data-item-type`**（`turn:assistant-avatar` / `task:explore-group` /
   `plan-item:toolcall` / `widget:action-bar`…），脏挂件是**没有 `data-item-type` 的 `container-*`**。
   → 取"**有 `data-item-type` 或含 `.markdown-renderer` 的直接子块**"拼接。实测该法**保留工具输出**
   （`任务耗时` / `已执行 N 条命令` / 逐条命令）**且丢掉脏挂件**；不钉任何 hash class、不靠中文文案。
   ★ 这与卡 §1.5「回复正文取 last innerText，别只取 markdown-renderer」的**意图一致**（要保住工具输出），
   只是把 innerText 里那两类 chrome 屏掉了。

两条都写进 `tools/trae_pool.mjs` 的注释里（`readAgents` 上方），并在下面 §4 记为已知限制。

## §3 与 `tools/wb_dispatch.py`（CodeBuddy 池派活器）的差异

| 维度 | `wb_dispatch.py`（CodeBuddy CLI） | `tools/trae_pool.mjs`（Trae IDE，CDP） |
|---|---|---|
| 后端 | 子进程 + CLI `-p` | Chromium CDP（`Runtime.evaluate` / `Input.insertText` / `Input.dispatchKeyEvent`） |
| 事件流 | `--output-format stream-json`，有 `result` 事件 | 无结构化事件；**自己扫 DOM** 判状态 |
| 用量读数 | token / 回合 / 阶段耗时 | **只有整数积分**（前后各读一次） |
| 完成判据 | 读 `result`（含 `subtype=success`） | 轮末 `busy` + 发送键 `disabled`（见 §2.1） |
| 权限 | `--permission-mode bypassPermissions` | **工作区内零审批**；跨界弹框 → 按**文案**自动点「本次会话允许/始终允许/…」 |
| 预算闸 | `--max-turns` / 看门狗 / 心跳 | **无**（卡死只能靠外部 `--timeout-sec`） |
| 续跑 | `--resume` / `--retry` | **无** |
| 429/配额 | 有专门判据（`result.errors`） | **不适用**（额度看积分 DOM） |
| 退出码 | 0 / 2 / 4 / 6 / 7 | **0 / 2 / 3** |

★ 本卡**只交付适配器本身**，**没有**改 `wb_dispatch.py`、也没有把 Trae 池接进派活器（那是下一张卡）。

## §4 已知限制（别指望它等于 CodeBuddy 池）

1. **脆**：全是 UI 自动化；面板改版/选择器改名就废。选择器里**不钉中文文案**，唯一用中文的是**授权框文案判据**
   （两套并集：路径授权 + `git commit`「高风险命令」；且**排除**「拒绝/取消/Deny/Reject/Cancel」）。
2. **串行**：一个面板一次一个任务；并发得靠多开 IDE 实例+不同调试口（未验）。
3. **无预算闸**：没有 `--max-turns`/看门狗；卡死只能靠 `--timeout-sec`（默认 3600s）。
4. **完成判据是启发式**：靠"轮末非 busy + 发送键 disabled"；`任务耗时` 只在**有工具调用**的轮次出现。
   极长任务若中途长时间停顿（既非 busy 又恰好 send 键 disabled）理论上可能早判（未撞到，如实记）。
5. **回复清洗是启发式**：按 `data-item-type` 过滤 chrome；若未来 Trae 把正文放进不带该属性的块，
   会漏内容（已加 `.markdown-renderer` 兜底）。
6. **拉起 IDE 的存活依赖父作业**：`detached+unref` 在**父进程正常退出**时子进程存活（实测多次），
   但父**被 kill** 会连坐（探测结论 §9.1 记过）。长任务别只靠它，遵循「一写一读/外部超时」。
7. **没有"新建任务"能力**：本卡只按 spec 实现 `balance`/`send`。一卡一任务需要主控先用面板「新建任务」
   （选择器已定位在探测结论，但不在本卡范围）。
8. **门禁跨界**（`run_gates.py` 写跨树锁/起 Edge/写 TEMP）会弹授权 —— 自动点授权**未在真跨界场景实测**
   （本次所有冒烟都在工作区内，`approve` 计数为 0）。

## §5 没动什么（边界）

- **只新建** `tools/trae_pool.mjs` 与本文；另追加 `docs/changelog.md` 一段、`docs/traceability.toml` 末尾 `T-G172` 一块、
  `复盘/交接-重构进度.md` 一段 CHECKPOINT；`gates/last.json` / `gates/reuse.json` 为门禁盖章件。
- **没动**：`src/**`、`scripts/**`、其余 `tools/**`、`tests/**`、`docs/**`（除上述）、
  `gates/diag/**`（除 §3 自测约定的 `traepool-*` 临时证据，本目录被 git 忽略）、`复盘/` 下其它文件、
  `.wt/` 的别的树、主树外来未跟踪文件、`data/`、真实库与备份目录；**没动** `wb_dispatch.py`。

## §6 台账条目（append 到 `docs/traceability.toml` 末尾）

```toml
[entries."T-G172"]
id = "T-G172"
title = "TraeCode 池适配器 tools/trae_pool.mjs（CDP：发指令/自动授权/判完成/积分记账）"
group = "PROCESS"
status = "done"
evidence = [
  "file:tools/trae_pool.mjs",
  "file:复盘/Trae池适配器-T-G172.md",
]
gaps = "**实测读数**：node --check 退出码 0（371 行）；冒烟（提示词「只回两个字：在吗」）DONE sec=15 turns=5、balance 4,544->4,544、退出码 0；--out 为最后一条 agent 轮次（Agent/思考过程/在吗/10%）；log 10 行（connect/balance/send/poll×5/balance/done）、approve 0 次；balance 子命令打印 4,544 退出码 0；本卡约耗 1 个积分（4,545->4,544，三条「只回两个字：在吗」未扣分）。**两处与卡原文不一致（如实记）**：① 卡 §1.5 的 done=/任务耗时/ 在「纯文字回复」轮次里不出现（实测首趟白等 300 秒超时退出码 3），而「有工具调用」的轮次里出现（任务耗时 3m 17s）→ 现场补判据「发送键 sendDisabled 连续 2 拍 + 非 busy」；② 最后一条 .turn__agent-message 的 innerText 会混进无 data-item-type 的 container-* chrome（回显旧用户话 / 建议块）→ 取「有 data-item-type 或含 .markdown-renderer 的直接子块」拼接，保留工具输出且去脏。**两套授权文案**：路径授权 + git commit 高风险命令，判据取并集且排除拒绝/取消。**完成判据为什么只看最后一条 agent 轮次**：看整段尾部会被上一轮的「完成。」骗（探测结论 §5.2 主控实测）。**零新依赖**：只用 Node 22 内建 WebSocket/fetch/child_process。**没动派活器** wb_dispatch.py。**没动什么**：src/scripts/其余 tools/tests/docs 除白名单外零改动，gates/diag 除自测临时证据（本目录 git 忽略）未动，.wt 别的树/主树外来文件/data/真实库未碰。**未实测边界**：自动点授权未在「真跨界」场景验（本次冒烟全在工作区内 approve=0）；拉起 IDE 的 detached 子进程在父被 kill 时会连坐（探测结论 §9.1）。"
```
