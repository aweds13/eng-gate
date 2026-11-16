# pipe-card —— 本仓绑定（仓无关骨架之外的那一层）

> **这一页只放"这个仓是什么样"**：命令落在哪、台账与队列叫什么、模型名单从哪读、看守产物挂在哪、读数是多少。
> `SKILL.md` 里的动作与读法换仓也不变；换一个仓用这套技能，**只换这一份**，别改 `SKILL.md`。
> 本仓 = `program/engineering`（`pipe` 框架 + timeflow 实现）。其他仓的等价物按同一骨架填一份。
> 判据（域检查、申报收口、长命令为什么被拒、封存）在 `tools/pool/task.py`、`tools/pool/landing.py`、
> `tools/wb_dispatch.py` 里，本页只做指针与读数。

## 入口与路径

```bash
python -X utf8 tools/wb_card.py add --id E82 --task T-AG587 --title 卡E82示例 --spec 复盘/卡/卡E82-示例.md
python -X utf8 tools/wb_dispatch.py --card <卡号> --spec 复盘/卡/卡<卡号>-<短名>.md \
    --cwd .wt/<卡号> --model <短名> --detach --execute
python -X utf8 tools/wb_task.py register / claim / status / landed
python -X utf8 tools/wb_stage_card.py --tree .wt/<卡号> --id <台账号> --title "<标题>" \
    --evidence <文件> --text-file gates/diag/_text_<台账号>.md
python -X utf8 tools/wb_batch.py plan            # 攒批（plan / make / land / bisect）
```

- 队列台账：`docs/workbacklog.toml`（卡块）。卡规格目录：`复盘/卡/`。工人树：`.wt/<卡号>`，
  分支 `card/<卡号>`。
- 台账号形如 `T-AG<数字>`；与卡号是两套编号，`Task:` trailer 只认台账号。
- 三段文书：`gates/diag/_text_<台账号>.md`（`gaps` / `changelog` / `checkpoint`）。
- 工人日志：`gates/diag/wb-<卡号>.jsonl`。
- 批预声明：`gates/diag/batch/<批号>.toml`（模板在同目录）。

## 立卡的退码与字段

- 立卡子命令 `add` 的字段：`--id` / `--task` / `--title` / `--spec` 必填，
  另有 `--file` / `--depends` / `--risk {low,mid,high}`（默认 `mid`）/ `--status` / `--wait` / `--commit`。
- **退 1** = 台账不是纯 CRLF（**不写盘**）；**退 2** = 等不到锁。两种都别手改台账对齐。
- 属性来自生产代码：`tools/pool/ledger.py`（台账锁跨会话互斥 / 块级幂等 / 尾部按字节追加 / 原子替换带重试）。
- **不要再立第二个写方**：旧的 `gates/diag/_add_card.py` 已废（硬编码绝对路径、按全文子串判「已在」
  ⇒ 卡凭空丢、且住在 gitignore 里、不入库）。依据：卡 E81（提交 87f95ba5）把立卡收成生产代码。

## 队列条目字段的取值（别凭印象写）

| 字段 | 真值 |
|---|---|
| `risk` | **`low` / `mid` / `high`**（不是 `medium`；`tools/wb_card.py --risk` 的 choices 与 `tools/pool/ledger.py` 的默认值都是这一套） |
| `status` | `pending` 可派 · `done` · `failed`（**不许缺行**：缺了被默认读成 `pending`，落地翻状态会静默跳过） |
| `id` / `task` | 卡号（分区前缀形如 `A293`）/ 台账号（`T-AG…`），两套编号 |

2026-11-08 实测队列读数：`risk = "mid"` **200** 条、`medium` **0** 条、`low` 100 条、`high` 39 条。
队列自检：`python -X utf8 tools/wb_plan.py check`（`0` = 队列合法；`1` = 点名：缺字段 / 域相交 / 已落仍 pending）。

## 派活：看守默认自动挂（卡 E7）

- `tools/wb_dispatch.py:1281 def ensure_watch(card, *, mode="one", timeout=DEFAULT_TIMEOUT)`；
  调用点在 `--execute` 那两处（`:3619` / `:3680`）⇒ **默认就挂**，派完那一屏打
  `[看 ] 看守已起（pid …）`。**没看到这行** = 看守没起来（脚本不在 / 起不来会打告警）。
- `--watch {one,shared}`（默认 `one`）/ `--no-watch`（明说「已关看守：完工后请自己轮询」，卡 E7 判据 3 逐字钉着）。
- 完工信号**只看磁盘**：`gates/diag/wb-<卡>.done`（`card` / `task` / `exit_code` / `at` / `log` / `report`）
  + `gates/diag/notifications.jsonl` 末尾那一行。超时只写 `state:"timeout"`，**不把「没判决」当成功**。
- 合用看守的计数与心跳：`gates/diag/watch-registry.json`；心跳过期且还有卡没判决 ⇒
  写 `state:"watcher-stale"` 并退 **5**。
- 手动单看 / 重挂：`python -X utf8 tools/wb_watch.py --cards <卡号>`（只读，加 `--write-done` 才落事件）。
  派活器会给看守一个 `--since`（这一轮开跑的时刻），比它旧的判决 / 日志一律不认。
- `python -X utf8 tools/wb_dispatch.py --card <卡号> --status`：`0` = 打印这一轮判决 / 进度；
  非 `0` = 这一轮没有产物（**不是**「跑完了」，别当成功）。

## 模型批准集（现算，别抄旧笔记）

- 真源一：`tools/pool/model-registry.toml` 里该池的 `[[model]]` 条目。2026-11-08 实读 codebuddy 池**只有 2 条**：
  `deepseek-v4.1-flash`（`default = true`，429 轮换链第 1 项）/ `glm-5.3-flash`（轮换链第 2 项）。
- 真源二：仓外开关 `infra/pool/model-switches.toml` 打开项（**只做加法**，**不进** 429 轮换链）。
  2026-11-08 实读在开的是 `glm-5.3`（对抗性审核用）/ `kimi-k3-1`（问问题、总结用）/ `glm-5.2`。
- 真源三：`wb_dispatch` 的 `ONE_OFF_MODELS`（今天为空）。
- ⇒ 派活时**以那一屏列出的允许集为准**：写错一律被拒单并原样列出允许集。
  「注册表 2 条」与「实际能调度 5 个」是两件事 —— 后者 = 前两条真源的并集。

## 会话闸（卡 A324）

- 卡归另一个对话窗口 ⇒ 退 **2** 并打印持有者；确要接手加 `--take-over`（留痕），别反复重试。
- 看谁是持有者：`python -X utf8 tools/wb_session.py --list`。
- 没有 `DSH_SESSION_ID` 的环境（号池工人 / cron）一律放行 —— 工人不受这条约束。

## 攒批（一天一个栅栏，不是一张卡一个）

- 疼在哪：一张卡要两趟门禁；主控 2026-10-13 实测给**每张卡**各建了一个栅栏（每个只有 1 个成员）⇒
  那样的栅栏**永远攒不成批**，等于逐张落地只换个写法。
- 四条：① 当天所有卡登记到同一个栅栏（如 `B-<日期>`）；② 批 ≤4；③ 成员域两两不相交
  （`wb_plan.py check` 拒同域同批，`register` 当场拒受保护共享文件）；④ `--card` 与 `--batch` 恰好给一个。
- 入口 `tools/wb_batch.py`（`plan` / `make` / `land` / `bisect`）；预声明 TOML 手写，模板在 `gates/diag/batch/`。
- 失败定位：落地按「产物 ∩ 暂存清单」逐成员认领再翻 `status` —— 没认领到谁的产物就点名谁；
  批树 `git apply` 合不上 ⇒ 整批停并点出冲突的卡与路径。

## 复盘缺口（历史证据层）

这一节是**历史证据层**：读它为了知道「为什么有这条检查」，不是当判据用。

- （缺口 · 长跑派给工人）2026-10-15 实测：工人 harness 不支持后台命令，卡里就空转，日志只剩同一条被拒的命令
  （原文 `Command rejected: … Reason: Background command execution is not supported in pr…`）。
  证据：`skills/pipe-card/references/dispatch.md` §4；卡 245 实测两次。
- （缺口 · 申报漏最后一步）卡 180（`T-G280`）：工人正常收工（`finished=true`、`errors=[]`、293s、56 事件、
  `tokens total=37245`）却没交申报 ⇒ 栅栏停在 `collecting 0/1`。这就是「申报 = 一等动作」的由来。
  证据：`skills/pipe-card/NOTES.md`
- （缺口 · 台账被 reset 扫掉）2026-11-02 20:36：另一会话落地失败后手工在主树 `reset --hard`，
  把主控刚写进台账的条目一起扫掉，只能重做立卡 ⇒ 同一天卡 E81 把立卡收成生产代码。
  证据：`skills/pipe-card/NOTES.md`
