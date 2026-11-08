# 派活分工与卡规格（细则）

> `pipe-card/SKILL.md` 的按需参考。**判据不在这里**：域检查、申报收口、长命令怎么被拒，
> 都在 `tools/pool/task.py`、`tools/pool/landing.py`、`tools/wb_dispatch.py` 里。

## 1. 卡规格的四段（照抄骨架，别自创标题）

```markdown
# 卡 <ID> — <一句话>

## 问题          # 现在错在哪 / 缺什么，带读数
## 改法          # 改哪些文件、怎么改；文件清单要等于域
## 判据          # 怎么验（命令 + 预期读数）
## 证据          # 干完要交什么（读数 / 文件 / 门结论）
```

★ 卡里若写了「验收含真机 / 长跑 / ≥30 秒的命令」，**必须**在同一段写明**由谁跑** ——
秒级归工人、跑不完的归主控。否则工人会在那一步空转，日志里只剩同一条被拒的命令。

## 2. 队列条目字段（`docs/workbacklog.toml`）

| 字段 | 含义 |
|---|---|
| `id` | 卡号（分区前缀形如 `A293`） |
| `task` | 台账号（`T-AG…`），与 `id` 是两套编号 |
| `title` / `spec` | 一句话标题 / 卡规格路径 |
| `tree` | 工人树 `.wt/<id>` |
| `files` | **域**：这张卡允许碰的文件 |
| `depends` | 依赖的卡号（没 done 就排不出来） |
| `risk` | `low` / `mid` / `high`（默认 `mid`；**没有 `medium`** —— 真源 `tools/wb_card.py --risk` 与 `tools/pool/ledger.py`） |
| `status` | `pending` 可派 · `done` · `failed` |

★ **`status` 行不许缺**（卡 E9）：缺了会被**默认读成 `pending`**，而落地翻状态找不到那一行就**静默跳过**
⇒ 「已落却仍 pending」（踩过两次，面板/排班跟着一起错）。开卡那一笔就写进去；落地前先补。
落地前置体检的第 ⑧ 条现在**全队列扫**，缺一块就 ❌（不再只看这一趟要落的那张）：

```bash
python -X utf8 tools/wb_plan.py check          # 0 = 队列合法；1 = 点名（缺字段 / 域相交 / 已落仍 pending）
```

## 3. 三条道怎么分

| 道 | 用来干什么 | 不许 |
|---|---|---|
| CodeBuddy（默认池） | 实现类卡：改代码 / 写判据 / 落地前的活 | 模型名要短名，写 `vendor/model` 会被拒 |
| 复核道（`--model kimi-k3-1`） | 只做复核 / 对抗性审查：证伪既有结论、开工前审规格、落地后审产物 | 不许当实现工人 |
| 主控 | 长跑（真机 / 全量门禁 / 落地链）、跨域决策、与用户对话 | 不许抢工人域内的活 |

★ **批准集是现算的，不许凭记忆写**：真源 = `tools/pool/model-registry.toml` 里该池的条目（codebuddy 池 =
`deepseek-v4.1-flash` 默认 / `glm-5.3-flash`）＋ 仓外开关 `infra/pool/model-switches.toml` 里打开的（只做加法）
＋ `wb_dispatch.ONE_OFF_MODELS`（今天为空）。写错一律拒单并**原样列出允许集**。
★ 2026-11-08 实读：注册表 codebuddy 池**只有 2 条**（`deepseek-v4.1-flash` 默认 / `glm-5.3-flash`），
另 3 个（`glm-5.3` / `kimi-k3-1` / `glm-5.2`）是**仓外开关**打开的 —— 「注册表 2 条」与「实际能调度 5 个」
是两件事，别把并集当成注册表内容。429 轮换链只走注册表那两条，不掺开关。
逐条读数与真源指针：见 [本仓绑定](repo-bindings.md) 的「模型批准集」一节。

★ **派活/落地前先过会话闸**（卡 A324）：卡归另一个对话窗口 ⇒ 退 2 并打印持有者；
确要接手加 `--take-over`（留痕）。看谁是持有者：`python -X utf8 tools/wb_session.py --list`。
没 `DSH_SESSION_ID` 的环境（号池工人 / cron）一律放行 —— 工人不受这条约束。

## 4. 工人被 harness 拒绝长命令时

真实现场（卡 245 实测两次）：

```text
Command rejected: … Reason: Background command execution is not supported in pr…
```

处置顺序：

1. **别把它当「工人不行」** —— 这是 harness 能力边界。
2. 改分工：工人只做秒级能跑完的（改代码 / `--selftest` / 小口径 pytest）。
3. 长跑由主控用后台作业跑，把读数贴回文书。
4. 卡里预先写清**降级口径**：环境不具备就如实写「没做」+ 证据，并交回可替代的证据
   （离线桩 / 类型面 / 源码行号）。

## 5. 派的现场检查（派活器自己会做的，别重复也别绕过）

- 规格文件存在且在 git 里；
- 工作区干净（**当前工作区**，不是 `--cwd` 那棵树）；
- 日志不覆盖（`--force` 才覆盖）；
- 端口 / 内存 / 登录自检。

## 6. 派活必带看守（卡 E7 —— 派完别再人肉轮询）

★ **默认就有，不用你另起命令**（`ensure_watch` 在 `--execute` 的两处调用点自动挂）：`wb_dispatch.py --execute` 起完工**自动**挂一份
`tools/wb_watch.py` 盯着这张卡，出判决就落事件。派完那一屏会打一行 `[看 ] 看守已起（pid …）`；
**没看到这行** = 看守没起来（脚本不在 / 起不来会打告警），这时才需要自己处理。

| 你怎么想 | 加什么 | 结果 |
|---|---|---|
| 默认（推荐） | 什么都不加 | `--watch one`：这张卡一个看守，出判决写 `.done` + 通知一行，然后退出 |
| 大批判跑、不想刷屏 | `--watch shared` | 全局**一份**合用看守：每派一张 `refcount +1`、每出判决 `-1`、归 0 写一条 `batch-done` 并退 |
| 明确不要看守 | `--no-watch` | 不起看守，并**明说**「已关看守：完工后请自己轮询」（静默 = 骗人，卡里禁止） |

★ **完工信号只看磁盘**：`gates/diag/wb-<卡>.done`（一行 JSON：`card` / `task` / `exit_code` /
`at` / `log` / `report`）+ `gates/diag/notifications.jsonl` 末尾那一行。
看守不判断内容对不对（那是主控复核），也**不把「没判决」当成功**：超时只写 `state:"timeout"`。
★ 合用看守的计数与心跳落 `gates/diag/watch-registry.json`（`refcount` / `cards` / `pid` / 心跳）；
心跳过期且还有卡没判决 ⇒ 写 `state:"watcher-stale"` 事件并退 **5** —— 看到它就说明「这批没人守了」，
别以为还在盯。
★ 手动单看 / 重挂：`python -X utf8 tools/wb_watch.py --cards <卡号>`（只读）；
要它顺手落事件就加 `--write-done`。
★ 派活器还会给看守一个 `--since`（这一轮**开跑的时刻**）：比它旧的判决 / 日志一律不认 ——
所以 `--force` 重派时，上一轮那份静默日志不会被新看守读成「判死」。手动跑不给 `--since`
就全认（看历史），要避开旧件就自己给一个时刻。

退出码：`python -X utf8 tools/wb_dispatch.py --card <卡号> --status` —— `0` = 打印这一轮判决 / 进度；
非 `0` = 这一轮没有产物（不是「跑完了」，别当成功）。`wb_watch.py` 判 `watcher-stale` 时退 **5**
（心跳过期且还有卡没判决 ⇒ 这批已经没人守了）。

## 7. 攒批落地：一天一个栅栏，不是一张卡一个（卡 228 / T-G344）

★ **疼在哪**：一张卡要两趟门禁（登记一趟 + 落地一趟，各 3~5 分钟）。主控 2026-10-13 实测给**每张卡**
各建了一个栅栏（`B-DTREE` / `B-DSHTIE` …，每个只有 1 个成员）⇒ 那样的栅栏**永远攒不成批**，
`--batch B-XXX` 一次只能收一个成员，等于逐张落地只换了个写法。

照着做不会踩的四条：

1. **当天所有卡登记到同一个栅栏**（如 `B-<日期>`），成员逐个列进去 —— 收口一次 = **一次门禁、一笔提交**。
2. **批要小（≤4）**：批树合不上一句话就整批停，只有小批才二分得动「是哪张卡」。
3. 成员域**两两不相交**（`wb_plan.py check` 拒同域同批）；`register` 时会当场拒受保护共享文件。
4. `--card` 与 `--batch` **恰好给一个**（批号也能当门禁锁的标签）。

```bash
python -X utf8 tools/wb_task.py register gates/diag/batch/<批号>.toml   # 0 = 登记成；2 = 预声明被拒（点名原因）
python -X utf8 tools/wb_land.py --batch <批号> --tree .wt/batch<号> --task <台账号> ...   # 同单卡八步链的退出码
```

★ **失败怎么定位**：落地按「产物 ∩ 暂存清单」逐成员认领再翻 `status` —— 没认领到谁的产物就点名谁；
批树 `git apply` 合不上 ⇒ 整批停并点出冲突的卡与路径。
★ **入口**：`tools/wb_batch.py`（`plan` / `make` / `land` / `bisect`；现读 `python -X utf8 tools/wb_batch.py plan` 可跑）；
预声明 TOML 仍要手写（模板见 `gates/diag/batch/`）。
