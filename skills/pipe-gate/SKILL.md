---
name: pipe-gate
description: 判断「现在这棵树过不过门」，并读懂门禁结果（每道门的退出码 / 未跑 / 复用）。当你要跑门禁、只看某几道门、确认某道门红没红、或提交前要一份全量结论时用；它给你命令档位与读法，判据在门表与工具里。
---

# pipe-gate —— 跑门禁并读懂结果

跑门用 `scripts/run_gates.py`，读结论看 `gates/last.json` 与 `gates/logs/`。
本仓门数是**现算**的（门表只有一处真源）：以 `python -X utf8 scripts/run_gates.py` 落盘的
`gates/last.json` 的 `gates[]` 条数为准（**2026-10-28 现读 22 道**）。文档可以写**带日期**的读数，
但**不许**把数字当常量引用 —— 门表一变，写死的老数字就在骗人。

## 什么时候用

- 改完一小块，自查这棵树还绿不绿（`--fast`，十几秒）。
- 提交 / 收口前要一份全量结论（`--quick` 次之；`wb_land` 内部跑全量）。
- 某道门红了，要知道「哪道门、什么退出码、日志在哪」。

## 什么时候别用

- 要验证**门本身还活着**（判据没退化成注释）：那是金丝雀自检，不是跑门。
- 想把红改成绿：先修代码或修门；**不许**放宽判据、加豁免、手改 `gates/last.json`；**也不许靠再跑一次门禁把它跑绿** —— 假红要读红门 `detail` 第一段的隔离判定，重跑不是证据。
- 只想看「今天该做什么 / 谁在飞」：用 `pipe-workbench`。
- 已经有一趟门禁在跑：**同一时间只跑一趟**（重活并发 = 假红的头号来源）。

## 前置检查

1. 在**要判的那棵树**里跑 —— 每棵 worktree 有各自的 `gates/`：`pwd` + `git rev-parse --show-toplevel`。
2. 工作区状态先看清：`git status --porcelain -uno`（有别人的未提交改动就先停手）。
3. 内存 / 端口够不够：真机层要起服务与浏览器；`--fast` 只跑轻门，不受影响。
4. 读法细则（每行字段、未跑、复用、退出码）见 [输出读法](references/output.md)。
5. ★ **全量门禁只有一把锁**：`gates/diag/gates.lock`（没给段）/ `gates/diag/gates-<端口段>.lock`（给了段）。
   `TF_GATE_MAX_CONCURRENT=2` 是**并发上限，不是目标**。锁在 = 有人正在跑这趟 —— **等锁不是卡死**；
   锁文件消失 = 那趟收口了。被判「卡死」之前先读账本：`python -X utf8 gates/diag/gate_lock.py status`
   （它给每段的持有者与**租约剩余**；★ 它自己写着「别看 pid 判活」—— 租约才是判活依据，默认 **10800 s**，
   `--stale-after` 可调）。这一段只读工具读数，不追某张卡的进度。
   人工兜底**只有一条**：`TF_GATE_PORT_BASE=<段> python -X utf8 gates/diag/gate_lock.py release --card <卡> --force`
   —— 不带段会在默认段里找锁、报「没有锁，无需释放」，真锁照样泄漏。
6. **跨会话共享一台机**（云门禁机）的口径见 `docs/subsystems/ci/云门禁机.md` —— 本页不写推断，别自己发明排队规矩；
   那台机器现在能不能上，读那份里的自检命令，别读某张卡的进度。

## 真命令

```bash
python -X utf8 scripts/run_gates.py --fast            # 内循环：十几秒那几道（不落盘）
python -X utf8 scripts/run_gates.py --quick           # 跳过真机层
python -X utf8 scripts/run_gates.py                   # 全量（提交前用这一档）
python -X utf8 scripts/run_gates.py --no-reuse        # 不信复用记录，全部重跑
python -X utf8 scripts/run_gates.py --affected <路径>  # 只跑受影响的门（自查，不是提交闸）
python -X utf8 scripts/run_gates.py --seal            # 只更新 last.json 的 tree 字段，不跑门
# 每道门的全量输出落 gates/logs/<门名>.log（不进仓库）
```

## 怎么读结果

- 一屏核对五块（提交骨架 / 门禁 / 封存 / 台账 / 审计，且报出「not_run N 道 · 复用 N 道」）：`python -X utf8 tools/wb_verify.py --tree .`。
- 每道门一行（名字 / `exit_code` / 秒数）：`python -X utf8 tools/pipeline_view.py --json` 的 `gates.items`。
- 自己动过的门（或它的输入）要 `--no-reuse` 真跑；复跑后用 `python -X utf8 tools/wb_verify.py --tree .` 看「复用 N 道」有没有降下来。
- 红门的日志尾在 `gates/logs/<门名>.log`；跨树汇总、缺源说明用 `python -X utf8 tools/pipeline_view.py --json`（缺块给 `null` + note，不洗成空）。
- 红门先看 `detail` 第一段的隔离判定：`[隔离跑绿]` / `[隔离也红]` / `[判不出]` —— **`[隔离跑绿]` 也不等于通过**，门照样红、退出码不改。默认关（`TF_GATE_FLAKE_PROBE=1` 才开），关着时 detail 会明写「本次未做隔离复核」；跨树读数用 `python -X utf8 tools/pipeline_view.py --json`。

## 常见错与处置

| 现象 | 真因 | 处置 |
|---|---|---|
| `--fast` 全绿就改了提交 | `--fast` **不落盘**、只覆盖「改一行就能犯」那几类 | 提交前跑 `--quick` 或全量；`--fast` 不是提交闸 |
| 有门 `not_run` 却当通过；或门是绿的但 summary 写着「没判完 / 判不出 N」 | 运行状态 ≠ 判决；「判不出」也不是判过 | 补依赖再跑；`docs` / `skills_claims` 两门跑 `--mode report` ⇒ **判不出也退 0**，要看它们 summary 里的 `判不出 N` / `[DEBT]`（`--mode block` 才退 `3`）；回报里如实写「未跑」「判不出」，别折成绿 |
| 门全绿但结论是上一棵树的 | 在别的 worktree 里读到了自己的 `gates/last.json` | 用 `rev` / 树路径对齐；`wb_verify` 会报 `rev` 与父提交关系 |
| 自己改过的门显示复用 | 增量执行读了缓存 | `--no-reuse` 真跑；别拿复用当验证 |
| 整趟门禁卡住几十分钟 | 某道门卡死（**门禁有逐门硬超时**，不是没有） | 先看 `gates/last.json` 里那道门是不是 `exit_code = 124` + `timeout=True`（超时口径在 `scripts/run_gates.py`：`DEFAULT_DOOR_TIMEOUT = 1800.0` 秒，`TF_GATE_DOOR_TIMEOUT` 可覆盖、`0` = 关掉；到点掐整棵进程树并判红）；清洗残留按 PID 收，别杀用户的浏览器 |
| 两趟门禁同时跑 | 重活并发 | 串行；两个池也别同时满载 |
| 一直等锁 / 报「卡死」 | 死主没清锁（租约默认 10800 s） | 先 `python -X utf8 gates/diag/gate_lock.py status` 看是哪一段、持有者是谁、租约还剩多久（**别看 pid 判活**）；确实过了租约才按上面第 5 条的**一条**兜底命令强放，别反复重试 |
| `check_layers` 报「引用断裂」 | `docs/` 里反引号包了个**不存在 / 计划中**的 `.md`（通配符也算） | 单跑 `python -X utf8 scripts/check_layers.py`（0 / 1）点名到"哪篇引了哪个"；改成「路径（计划建）」并去掉反引号，或把文件真建出来 |
| 换机器后自己的门莫名「复用」| 解释器版本不同会改门输入哈希的展开语义（卡 E44：3.12 的 `Path.glob("X/**")` 只给目录 ⇒ 哈希恒为 `sha256("")`）| 看 `gates/last.json` 的 `python` 字段与 `rev`；`python < 3.11` 会被开跑前拦下。别把「哈希一样」当「文件没变」 |

## 复盘缺口（环境假绿 / 读判决 / 接缝预检）

- （缺口 JU3）门禁假绿头号来源是环境：PYTHONPATH / cwd / 编码不对时，门会绿在错的输入上 —— 跑门前先核这三项（见「前置检查」），绿了也要确认绿在这棵树。证据：`复盘/门禁假绿-PYTHONPATH-T-G157.md`、`复盘/功能验收机器化-T-G34.md`、`复盘/门禁改进清单.md`
- （缺口 JU1）旧判决不许冒充当前状态：`gates/last.json` 必须带 base/rev，读的人先核它是不是这一轮的 —— 用 `python -X utf8 tools/wb_verify.py --tree .` 对 `rev` 与父提交。证据：`复盘/卡/卡156-旧判决冒充当前状态.md`、`复盘/问题清单-组3.md`、`复盘/卡/卡164-观测面与通则.md`
- （缺口 JU2）判决文案要分真因（门没挡住 / 挡住了但不是这条 / 输入没给），否则读判决的人永远在猜 —— 写判决时三选一写清；读判决时先分真因再动手。证据：`复盘/卡/卡156-旧判决冒充当前状态.md`、`复盘/卡/卡151-判决文案要分真因.md`、`复盘/留痕与配额策略.md`
- （缺口 SE1）跨卡接缝必须派活前预检（谁改签名、谁还在用旧签名）：事后发现的接缝等于两张卡白做 —— 派活前跑 `python -X utf8 tools/seam_check.py --card 名字=sha`。证据：`复盘/跨卡接缝预检-T-G139.md`、`复盘/接缝预检假阳性-T-G146.md`、`复盘/审计-GLM53-外包系统对抗审核.md`
- （缺口 SE2）接缝预检会假阳性（桩签名、同名不同参）：要人工复核一次，不许把预检红直接当判决红。证据：`复盘/跨卡接缝预检-T-G139.md`、`复盘/接缝预检假阳性-T-G146.md`、`复盘/审计-GLM53-外包系统对抗审核.md`
- （缺口 GV2）门乘输入表：每道门的输入面要显式列出，`--affected` 才有依据裁；匹配不上就当全量跑 —— 增量跑法见 `python -X utf8 scripts/run_gates.py --help`。证据：`复盘/问题清单-组3.md`、`复盘/卡/卡140-门乘输入表与自查提速.md`、`复盘/卡/卡147-复核器查门数.md`
- （缺口 GV1）门禁峰值要治：并行 pytest + 内存阈值随可用内存自适应，否则门红在 OOM 而不是红在判据 —— 内存吃紧时先降并行再跑，别拿 OOM 当红判据。证据：`复盘/卡/卡A266-门禁跑法与内存自适应.md`、`复盘/质量门提速-pytest并行-T-G7.md`、`复盘/卡/卡254-门禁峰值治理.md`

## 自查

按顺序四条，任一条不成立就**别报「绿了」**：

1. 我跑的是**这棵树**：`git rev-parse --show-toplevel` 与 `pwd` 同一棵。
2. 我报的那一档是**落盘档**（全量 / `--quick`），不是 `--fast`。
3. `gates/last.json` 的 `ok` 为真，且 `rev` 是本笔的父提交（封存口径见 `pipe-land`）。
4. 每道 `not_run` 都在回报里点了名，没有混进「通过」里。

> 判据（哪道门算过、三值与空集、复用规则）在 `scripts/run_gates.py` 与门表里，本技能只讲怎么跑、怎么读。
> 该跑哪一档、跑在哪台机器（本机 / 云机）、何时选测与夜间：见 `docs/subsystems/ci/测试流程.md`（五维口径与决策树）。

## 内循环：只跑一档（卡 A321）

改 `tools/**` 或 `tests/**` 时，等全量十几分钟不值得（档位按**门类**分，不按仓库）：

```bash
python -X utf8 scripts/run_gates.py --profile lang    # 本语言的门（Python 仓 = pytest/验收/ruff/mypy/自测）
python -X utf8 scripts/run_gates.py --profile audit   # 台账与证据（audit/invariants/titles）
python -X utf8 scripts/run_gates.py --profile product # timeflow 产品门（五层/UI/真机）
```

**默认仍是 `all`**，收口链（`tools/wb_land.py`）照旧跑全量 —— 分档只给内循环，不许当提交闸。
档与门的对应只有一处真源：`scripts/run_gates.py` 的 `GATE_PROFILES`。

**★ 提交闸只认全量**：`last.json` 里若记了 `profile`（≠ all），落地链直接拒 ——「挑一档跑绿」
不能冒充「全量跑绿」；默认不给 `--profile` 时封存形状逐字不变。档位成员的真源在 `gates/defs/`。

**★ 按域选档（卡 A327 · T-AG442）**：落地链默认不再一律全量 —— 它传 `--profiles auto`，
改动面 → 必需档查 `gates/defs/domains.py` 这一张表（判不出 ⇒ 全量），产物里记
`profiles_run / required_profiles / changed_paths`；提交闸（`wb_review` ③ / ③′）按
「必需档 ⊆ 已跑档」判。改 `scripts/**`、`tools/**`、`gates/**`（判据本体）仍强制全量。

