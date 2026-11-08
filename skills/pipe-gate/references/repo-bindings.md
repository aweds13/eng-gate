# pipe-gate —— 本仓绑定（仓无关骨架之外的那一层）

> **这一页只放"这个仓是什么样"**：命令落在哪、锁在哪、环境变量叫什么、文档指哪份、读数是多少。
> `SKILL.md` 里的动作与读法换仓也不变；换一个仓用这套技能，**只换这一份**，别改 `SKILL.md`。
> 本仓 = `program/engineering`（`pipe` 框架 + timeflow 实现）。其他仓的等价物按同一骨架填一份。

## 跑门入口与档位

```bash
python -X utf8 scripts/run_gates.py --fast            # 内循环：十几秒那几道（不落盘）
python -X utf8 scripts/run_gates.py --quick           # 跳过真机层
python -X utf8 scripts/run_gates.py                   # 全量（提交前用这一档）
python -X utf8 scripts/run_gates.py --no-reuse        # 不信复用记录，全部重跑
python -X utf8 scripts/run_gates.py --affected <路径>  # 只跑受影响的门（自查，不是提交闸）
python -X utf8 scripts/run_gates.py --seal            # 只更新 last.json 的 tree 字段，不跑门
# 每道门的全量输出落 gates/logs/<门名>.log（不进仓库）
```

- 产物：`gates/last.json`（判决）+ `gates/logs/<门名>.log`（逐门原始输出）。
- 本仓门数是**现算**的，真源只有一处：`scripts/run_gates.py` 落盘的 `gates/last.json` 的 `gates[]` 条数。
  **2026-11-08 现读 22 道**。文档可以写带日期的读数，但**不许**把数字当常量引用 —— 门表一变，写死的老数字就在骗人。
- 档与门的对应只有一处真源：`scripts/run_gates.py` 的 `GATE_PROFILES`；成员在 `gates/defs/`
  （`lang_python.py` / `contract.py` / `product_timeflow.py`）。

## 分档与按域选档（卡 A321 / A327 · T-AG442）

```bash
python -X utf8 scripts/run_gates.py --profile lang    # 本语言的门（Python 仓 = pytest/验收/ruff/mypy/自测）
python -X utf8 scripts/run_gates.py --profile audit   # 台账与证据（audit/invariants/titles）
python -X utf8 scripts/run_gates.py --profile product # timeflow 产品门（五层/UI/真机）
```

- **默认是 `all`**，收口链（`tools/wb_land.py`）也照旧跑全量 —— 分档只给内循环，不许当提交闸。
- **★ 提交闸只认全量**：`last.json` 里若记了 `profile`（≠ all），落地链直接拒 ——「挑一档跑绿」不能冒充
  「全量跑绿」；不给 `--profile` 时封存形状逐字不变。
- **★ 按域选档**：落地链传 `--profiles auto`，改动面 → 必需档查 `gates/defs/domains.py` 这一张表
  （判不出 ⇒ 全量），产物里记 `profiles_run / required_profiles / changed_paths`；提交闸（`wb_review` ③ / ③′）
  按「必需档 ⊆ 已跑档」判。改 `scripts/**`、`tools/**`、`gates/**`（判据本体）仍强制全量。

## 并发闸：全量门禁只有一把锁

- 锁文件：`gates/diag/gates.lock`（没给段）/ `gates/diag/gates-<端口段>.lock`（给了段）。
- `TF_GATE_MAX_CONCURRENT=2` 是**并发上限，不是目标**。锁在 = 有人正在跑这趟 —— **等锁不是卡死**；
  锁文件消失 = 那趟收口了。
- 被判「卡死」之前先读账本：`python -X utf8 gates/diag/gate_lock.py status`
  （给每段的持有者与**租约剩余**；它自己写着「别看 pid 判活」—— 租约才是判活依据，默认 **10800 s**，
  `--stale-after` 可调）。这一步只读工具读数，不追某张卡的进度。
- 红门隔离复核默认**关**：`TF_GATE_FLAKE_PROBE=1` 才开；开了才会在 `detail` 里写 `[隔离跑绿]` / `[隔离也红]` / `[判不出]` 三档判定（判据在 `scripts/flake_probe.py`）。
- 人工兜底**只有一条**：`TF_GATE_PORT_BASE=<段> python -X utf8 gates/diag/gate_lock.py release --card <卡> --force`
  —— 不带段会在默认段里找锁、报「没有锁，无需释放」，真锁照样泄漏。

## 逐门硬超时

门禁有逐门硬超时，不是没有：`scripts/run_gates.py` 的 `DEFAULT_DOOR_TIMEOUT = 1800.0` 秒，
`TF_GATE_DOOR_TIMEOUT` 可覆盖、`0` = 关掉；到点掐整棵进程树并判红，`gates/last.json` 里那道门
记 `exit_code = 124` + `timeout=True`。清洗残留按 PID 收，别杀用户的浏览器。

## 跨会话共享一台机（云门禁机）

口径见 `docs/subsystems/ci/云门禁机.md` —— 别自己发明排队规矩；那台机器现在能不能上，读那份里的自检命令，
别读某张卡的进度。该跑哪一档、跑在哪台机器、何时选测与夜间：`docs/subsystems/ci/测试流程.md`
（五维口径与决策树）。

## 复盘缺口（环境假绿 / 读判决 / 接缝预检）

这一节是**历史证据层**：每条缺口挂 2–3 份复盘。读它为了知道「为什么有这条检查」，不是当判据用。

- （缺口 JU3）门禁假绿头号来源是环境：PYTHONPATH / cwd / 编码不对时，门会绿在错的输入上 —— 跑门前先核这三项
  （见 `SKILL.md`「前置检查」），绿了也要确认绿在这棵树。证据：`复盘/门禁假绿-PYTHONPATH-T-G157.md`、
  `复盘/功能验收机器化-T-G34.md`、`复盘/门禁改进清单.md`
- （缺口 JU1）旧判决不许冒充当前状态：`gates/last.json` 必须带 base/rev，读的人先核它是不是这一轮的 ——
  用 `python -X utf8 tools/wb_verify.py --tree .` 对 `rev` 与父提交。证据：`复盘/卡/卡156-旧判决冒充当前状态.md`、
  `复盘/问题清单-组3.md`、`复盘/卡/卡164-观测面与通则.md`
- （缺口 JU2）判决文案要分真因（门没挡住 / 挡住了但不是这条 / 输入没给），否则读判决的人永远在猜 ——
  写判决时三选一写清；读判决时先分真因再动手。证据：`复盘/卡/卡156-旧判决冒充当前状态.md`、
  `复盘/卡/卡151-判决文案要分真因.md`、`复盘/留痕与配额策略.md`
- （缺口 SE1）跨卡接缝必须派活前预检（谁改签名、谁还在用旧签名）：事后发现的接缝等于两张卡白做 ——
  派活前跑 `python -X utf8 tools/seam_check.py --card 名字=sha`。证据：`复盘/跨卡接缝预检-T-G139.md`、
  `复盘/接缝预检假阳性-T-G146.md`、`复盘/审计-GLM53-外包系统对抗审核.md`
- （缺口 SE2）接缝预检会假阳性（桩签名、同名不同参）：要人工复核一次，不许把预检红直接当判决红。
  证据：`复盘/跨卡接缝预检-T-G139.md`、`复盘/接缝预检假阳性-T-G146.md`、`复盘/审计-GLM53-外包系统对抗审核.md`
- （缺口 GV2）门乘输入表：每道门的输入面要显式列出，`--affected` 才有依据裁；匹配不上就当全量跑 ——
  增量跑法见 `python -X utf8 scripts/run_gates.py --help`。证据：`复盘/问题清单-组3.md`、
  `复盘/卡/卡140-门乘输入表与自查提速.md`、`复盘/卡/卡147-复核器查门数.md`
- （缺口 GV1）门禁峰值要治：并行 pytest + 内存阈值随可用内存自适应，否则门红在 OOM 而不是红在判据 ——
  内存吃紧时先降并行再跑，别拿 OOM 当红判据。证据：`复盘/卡/卡A266-门禁跑法与内存自适应.md`、
  `复盘/质量门提速-pytest并行-T-G7.md`、`复盘/卡/卡254-门禁峰值治理.md`

## 本仓特有的两道门怎么读

- `docs` 与 `skills_claims` 跑 `--mode report` ⇒ **判不出也退 0**，要看它们 summary 里的 `判不出 N` / `[DEBT]`
  （`--mode block` 才退 `3`）；回报里如实写「未跑」「判不出」，别折成绿。
- `check_layers` 报「引用断裂」：`docs/` 里反引号包了个**不存在 / 计划中**的 `.md`（通配符也算）——
  单跑 `python -X utf8 scripts/check_layers.py`（0 / 1）点名到「哪篇引了哪个」；改成「路径（计划建）」并去掉
  反引号，或把文件真建出来。
- 换机器后自己的门莫名「复用」：解释器版本不同会改门输入哈希的展开语义（卡 E44：3.12 的
  `Path.glob("X/**")` 只给目录 ⇒ 哈希恒为 `sha256("")`）。看 `gates/last.json` 的 `python` 字段与 `rev`；
  `python < 3.11` 会被开跑前拦下。别把「哈希一样」当「文件没变」。
