# 本仓命令速查（六段流水线）

> `softeng-manage/SKILL.md` 的按需参考。**这里不写判据** —— 每段的「怎样算成」在对应工具里；
> 本表只给命令与产物名，防止把 `pipe` CLI 的想象命令敲进终端。

## ⓪ 新机制八条（卡 G2 · 2026-10-24 现算；每条都写「疼在哪 + 命令 + 退出码」）

> 这八条以前在技能里**一个字都没有** ⇒ 规矩只在最后时刻说话（实测：18 处断链等到落地第 20 分钟才红）。
> 判据仍在工具与门里，本节只给**该在什么时候敲哪一句、读到的退出码是什么意思**。

### 1) 工具根 ≠ 数据根（卡 A326）

- **疼在哪**：`tools/*.py` 曾一律拿 `Path(__file__).parent.parent` 当根 ⇒「工具住哪个仓」与「账本住哪个仓」
  被绑死；拿同一份 `tools/` 服务别的仓时，台账 / 门禁产物会被写回工具仓。
- **口径**：**门表跟工具根**（`tools/` 的上一级，或 `PIPE_HOME`）；**台账、门禁产物、卡规格跟数据根**
  （`PIPE_DATA` > 当前目录像数据根 > 工具根）。默认两根同值 ⇒ 老行为逐字不变。
- **命令与退出码**：

```bash
python -X utf8 tools/pipe_root.py --check   # 打印 {"home":…, "data":…}；0 = 两根都解析出来了；2 = 没给 --check
```

- 设错根时最先炸的通常不是它，而是 `sync_counts` / `audit` 说「找不到台账」—— 先核这两行再查别的。

### 2) 引用完整性门（`scripts/check_layers.py` 的 `check_link_integrity`）

- **疼在哪**：`docs/` 下 md 里**反引号包着**的 `.md` 会被当成一条**真路径**去查，查不到就 `[FAIL] 引用断裂`，
  连坐 `check_layers` 与 `check_layers_selftest` 两道门。实测：两篇文档 18 处断链，全量门禁跑到第 20 分钟才全红。
- **规矩**：计划中 / 还没建的文件**别写成反引号路径** —— 写成「路径（计划建）」并去掉反引号；
  通配符（`卡/*.md` 这种）同样会被当真去查。`gates/**` 下的引用按 gitignore 跳过，`复盘/` `docs/` 下的照查。
- **命令与退出码**：

```bash
python -X utf8 scripts/check_layers.py      # 0 = 无断链；1 = 逐条点名断链（哪篇文档引用了哪个不存在的路径）
```

### 3) 队列卡块的 `status` 行（卡 E9）

- **疼在哪**：`docs/workbacklog.toml` 的卡块缺 `status` ⇒ 读队列时**默认成 `pending`**，而落地翻状态时
  找不到那一行就**静默跳过** ⇒ 「已落却仍 pending」；面板与排班跟着错。实测 11 块缺这一行。
- **规矩**：**开卡那一笔就把 `status` 写进卡块**；落地前先补，别指望落地链替你补。
  落地前置体检第 ⑧ 条现在**全队列扫**，缺一块就 ❌（不再只看这一趟要落的那张）。
- **命令与退出码**：

```bash
python -X utf8 tools/wb_plan.py check        # 0 = 队列合法；1 = 点名问题（缺字段 / 域相交 / 已落仍 pending）
```

### 4) 审计 ⑫ 反向（本笔实际改的文件 ⊆ 台账证据指针）

- **疼在哪**：正向判据只查「你声称的有没有」；⑫ 查相反的方向 —— **本笔实际改动的每个文件**
  都得有台账指针（`file:` / `text:` / `test:`）或进 `[exceptions]` 豁免。实测：新增两个文件没指针，⑫ 咬下来重跑。
- **规矩**：`--evidence` 按**文件**给，别按「一件事」给；新增文件 = 新指针。台账只许在**末尾追加**自己的条目。
- **命令与退出码**：

```bash
python -X utf8 scripts/audit_progress.py --rev <提交>   # 0 = 审计通过；1 = 不过（逐条点名，不许提交）
python -X utf8 scripts/audit_progress.py --all          # 只对账台账 + 重建进度（不查 git 那半）；同样 0/1
```

### 5) E1 `--preflight`（落地前十几秒的只读体检）

- **疼在哪**：落地链 ④ 全量要十几分钟；参数写错 / 卡域空 / 文书缺段这类错，以前都拖到第 12 分钟才红。
- **口径**：`--preflight` 一次说全 **12 条判据**（不 fail-fast），**只读**、一步都不动，约十几秒
- **别和 `--skip-preflight` 混**：那个是落地链**内层**旗标（跳过③″快门禁预检，`tools/pool/landing.py`）；`--preflight` 是**壳层**只读体检（`tools/wb_land.py`，卡 E1）。同名不同义已在卡 G3 消掉
  （大头是 audit 那 10~15 秒）。给了 `--card` / `--batch` 时，体检绿了**才**接着落地，且只体检一次。
- **命令与退出码**：

```bash
python -X utf8 tools/wb_land.py --preflight --task <台账号> --allow <文件>...
# 0 = 12 条全绿（可以直接落地）/ 1 = 有 ❌（逐条点名，修完重跑）
```

### 6) E7 派活即看守（已落，别再加一步）

- **疼在哪**：派完活靠人肉轮询「跑完没有」，一忙就忘，卡在树里过夜。
- **口径**：`wb_dispatch.py --execute` 起完工**自动**挂一份 `tools/wb_watch.py`（默认 `--watch one`）。
  派完那一屏打 `[看 ] 看守已起（pid …）` —— **没看到这行 = 没起来**（脚本不在会打告警）。
  只有显式 `--no-watch` 才不起，那时它**明说**「已关看守：完工后请自己轮询」。
  完工信号只看磁盘：`gates/diag/wb-<卡>.done` + `gates/diag/notifications.jsonl`。
- **命令与退出码**：

```bash
python -X utf8 tools/wb_dispatch.py --card <卡号> --status   # 0 = 打印这一轮的判决 / 进度；非 0 = 没有这一轮的产物
```

### 7) 攒批落地（`wb_task.py register` 多成员栅栏 + `wb_land.py --batch`）

- **疼在哪**：一张卡两趟门禁（登记一趟 + 落地一趟，各 3~5 分钟）；N 张卡 = 2N 趟。批把「一次门禁、
  一笔提交」摊给整批。实测漂移：给**每张卡**各建一个栅栏（每个只有 1 个成员）⇒ 永远攒不成批，
  等于逐张落地只是换了个写法。
- **规矩**：**一天一个栅栏**（如 `B-<日期>`），成员逐个列进去；`--card` 与 `--batch` **恰好给一个**；
  **批要小（≤4）** —— 批树合不上时整批停，只有小批才二分得动「是哪张卡」；成员域必须两两不相交。
- **现状**：入口 `tools/wb_batch.py`，子命令 `plan` / `make` / `land` / `bisect`
  （现读：`python -X utf8 tools/wb_batch.py plan` 能跑，`--help` 那份 usage 列的就是这四个）；
  预声明 TOML 仍要手写（模板见 `gates/diag/batch/`）。
- **命令与退出码**：

```bash
python -X utf8 tools/wb_task.py register gates/diag/batch/<批号>.toml   # 0 = 登记成；2 = 预声明被拒（逐条点名原因）
python -X utf8 tools/wb_land.py --batch <批号> --tree .wt/batch<号> --task <台账号> ...   # 同单卡落地链的退出码
```

- **失败怎么定位**：落地按「产物 ∩ 暂存清单」逐成员认领再翻 `status`（`flip_batch_member_statuses`），
  没认领到谁的产物就点名谁；批树 `git apply` 合不上 ⇒ 整批停、点冲突的卡与路径 —— 所以别把批攒大。

### 8) 零 LLM 收口器 `tools/auto_land.py`（卡 233 / 卡 235）

- **疼在哪**：曾经把「什么时候该落哪一批」写成一段自然语言提示词交给 agent 读 —— 能用，但不是本仓形态
  （判据能写成代码，就不该交给模型读自然语言）。
- **四态（各自明确）**：无批 ⇒ **退 0、一行不打印**；内存紧 ⇒ 什么都不落、非零退并点名「内存紧」；
  门禁红 ⇒ 非零退、**原话带出来**；该落 ⇒ 走既定收口链落掉、打印批号 + 提交号。
  **按批独立判定**：能落的批照落，混着「用户决策项 / 要动 `data/` 下用户资产 / 树解析烂了」的批**只跳过它自己**
  并点名原因；**全部都没法落**才退 4。
- **什么时候别用它**：要在**非主树**里落（它必须跑在主树上，卡树里真落前会拒退 2）；
  内存紧的时候（它不绕内存闸，也不许别人绕）；需要人拍板口径的时候（那是停下来问，不是自动落）。
- **命令与退出码**：

```bash
python -X utf8 tools/auto_land.py --dry-run   # 只说会落哪几批 / 会停在哪；一行都不改；0 = 说完了
python -X utf8 tools/auto_land.py             # 有批就落（调度器挂的就是这一句）
# 0 = 落成 / 无批 / dry-run；2 = 不在主树或队列读不了；3 = 内存紧；4 = 每批都不能自动落；5 = 上一趟还在跑
# 链子失败原码透传（1 = 门禁红）
```

### 9) 云门禁机（多会话共享一台）

- **正式口径**：`docs/subsystems/ci/云门禁机.md`。
  共享机器怎么排队、什么时候开机、内存闸多少 —— 都在那份，别按想象写。
  那台机器今天开没开、锁在谁手里：读工具（`python -X utf8 gates/diag/gate_lock.py status`），别读记忆里某张卡的进度。

## ① 开卡

```bash
python -X utf8 tools/wb_plan.py plan --concurrency 2   # 排批（只认 status=pending）
```

- 卡规格：`复盘/卡/卡<ID>-<短名>.md`，四段固定：问题 / 改法 / 判据 / 证据。
- 队列：`docs/workbacklog.toml`，字段 `id / task / title / tree / spec / files / depends / risk / status`。
- `status`：`pending` 可派 · `done` · `failed`。

## ② 派活

```bash
git worktree add .wt/<卡号> -b card/<卡号>
python -X utf8 tools/wb_dispatch.py --card <卡号> --spec <规格> --cwd .wt/<卡号> \
    --model <短名> --detach --execute
python -X utf8 tools/wb_dispatch.py --card <卡号> --status
```

- 模型名用**短名**；写 `vendor/model` 会被拒。
- 派活产物落在**主仓** `gates/diag/`（gitignored，卡树里没有）。

## ③ 跑门

```bash
python -X utf8 scripts/run_gates.py --fast     # 内循环（不落盘）
python -X utf8 scripts/run_gates.py            # 全量（提交前）
python -X utf8 scripts/audit_progress.py       # 台账 / 证据审计
```

结论在 `gates/last.json`（`ok` / `rev` / `gates[]` / `not_run` / `reused`）。

## ④ 落地

```bash
python -X utf8 tools/wb_land.py --card <卡号> --tree .wt/<卡号> --task <台账号> \
    --title "<一句话>" --type feat --scope <域> \
    --allow <文件>... --evidence <指针>... --port-base <端口段>
```

八步链：⓪回退派生物 → ①迁树 → ②文书 → ③sync_counts → ④门禁 → ⑤seal →
⑥白名单提交 → ⑦audit + ff → ⑧复核落盘。

## ⑤ 巡检

```bash
python -X utf8 tools/wb_daily.py                # 今日一页
python -X utf8 tools/pipeline_view.py --report  # 六块读数
python -X utf8 tools/wb_dash.py                 # 工人面板（只读本地页）
```

## ⑥ 复盘 / 对账

```bash
python -X utf8 tools/wb_verify.py --tree .      # 这一笔算不算数
python -X utf8 tools/wb_reconcile.py            # 队列 vs git
python -X utf8 tools/wb_diag.py gates/diag/wb-<卡>.jsonl   # 工人日志失败定位
```

## 附：技能自身

```bash
npx -y skills-ref@latest validate ./skills/<名>     # 官方校验器
python -X utf8 skills/nails/check_skills.py         # 格式钉子
python -X utf8 skills/nails/check_commands.py       # 命令名钉子
python -X utf8 tools/dsh_skills_link.py --check     # 注册（junction，零副本）
```
