# 卡 E117 · skills 里的号池命令跑不起来，而检查器只核「这个字符串在源码里出现过」

> 台账号 `T-AG627`｜分区 E（门禁与可信度）｜树 `.wt/E117`｜层 判据层｜基准 `e815e1c5`｜★ depends = `["E113"]`（同分区 E、同判据层，都在 skills/ + check_skills_claims.py 这条链上；E113 已 done，不阻塞）｜
> 依据：用户 m00001「skills 里的号池命令跑不起来，而检查器只核『这个字符串在源码里出现过』」。
> 归属划分：本卡只负责 `tools/check_skills_claims.py` 的判据面 + `skills/softeng-manage/references/dispatch.md` 的坏命令；落地链、派活器、号池写面一概不碰（别顺手扩域）。

## 要解决的问题（逐条实测，不是推测）

### 问题 1 · 三处命令**根本跑不起来**：rc=2

主树 `0d28b544` 实测：

```text
$ python -X utf8 tools/pool_quota.py status
[rc=2]
usage: pool_quota.py status [-h] --card CARD --model MODEL [--now NOW]
                            [--root ROOT]
pool_quota.py status: error: the following arguments are required: --card, --model
```

三处都在 `skills/softeng-manage/references/dispatch.md`，都写同一个坏形状：

- `:48`「3. **配额**：各号池额度处在哪一态——`python -X utf8 tools/pool_quota.py status`（四态判见下文 QU2）。」
- `:77`「操作：看额度用 `python -X utf8 tools/pool_quota.py status`；别自己估间隔。」
- `:80`「操作：429 后先 `python -X utf8 tools/pool_quota.py status` 分清是哪一态，再决定重派 / 换号 / 停手；回报里写清是哪一态。」

`tools/pool_quota.py:942-944`：`p_status = sub.add_parser("status", …)` / `p_status.add_argument("--card", required=True, …)` / `p_status.add_argument("--model", required=True, …)`
⇒ 不带这两个参数必然退 2。这是**判据撒谎**，不是笔误：读者照着敲就被 argparse 拒单。

实测两条能跑通的替代（同一次运行）：

```text
$ python -X utf8 tools/pool_quota.py line                       # 全池一眼，无必填参数
[rc=0]
E11/deepseek-v4.1-flash 耗尽 | E11/glm-5.3-flash 耗尽 | E30/deepseek-v4.1-flash 耗尽 | E30/glm-5.3-flash 耗尽 | E33/deepseek-v4.1-flash 耗尽 | E33/glm-5.3-flash* 耗尽 | E38/deepseek-v4.1-flash 耗尽 | E38/glm-5.3-flash 耗尽

$ python -X utf8 tools/pool_quota.py status --card E113 --model deepseek-v4.1-flash
[rc=0]
[额度] 卡 E113 · 模型 deepseek-v4.1-flash —— 未记录
  没记录 ⇒ 不猜（★ 不许默认当可用）
  判据：没有这条记录 ⇒ 不猜（★ 不许默认当可用）
  要探就跑：python -X utf8 tools/pool_accounts.py probe（…）
```

`tools/pool_quota.py:963-970` 是 `line` 的 parser：`--card` / `--model` 都是 `action="append", default=[]`、**没有 required** ⇒ `line` 无参合法。

### 问题 2 · 检查器对「零 flag 命令」**天生免疫**

`tools/check_skills_claims.py:230-242 _flags_of`：

```python
        if not token.startswith("--") or len(token) <= 2:
            continue
        body = token.split("=", 1)[0]
```

只收 `--` 开头的 token ⇒ `pool_quota.py status` 这种无参命令 `claim.flags == []`；
`:339-341` 的 `for flag in claim.flags:` **一次都不进** ⇒ 必然 OK。

`:245-248 _flag_registered` 的判据只是「这串字符在源码里出现过」：

```python
    pattern = r"""["']""" + re.escape(flag) + r"""(?:=|["'])"""
    return re.search(pattern, source) is not None
```

全文件 `grep -n 'required' tools/check_skills_claims.py` ⇒ **rc=1（0 命中）**：既不核 required，也不核子命令。

临时假仓复现（探针 `gates/diag/_probe_p.py`，假工具只有 `status`（需 --card/--model）与 `line`）四种写法全是 `[OK  ] 引用 1 处 / 对得上 1 / 对不上 0 / 判不出 0 / 豁免 0`、rc 全 0：

```text
B1 缺必填 status 无 card/model   => rc 0  claims problems=[] unverifiable=[]
B2 子命令拼错 statuss            => rc 0  claims problems=[] unverifiable=[]
B3 正确 line                     => rc 0
B4 完整 status --card … --model … => rc 0
```

⇒ **「对得上 / 对不上」之间没有第三种判决**，四种写法一律 OK。四个目标引用在真仓的现行判决（探针 `gates/diag/_probe_y.py`）：`skills/pipe-card/references/repo-bindings.md:30` 与 `dispatch.md:48 / :77 / :80` 全是 `status=ok`、`flags=[]`、`problems=[]`。

真仓现行读数（未改任何文件）：`[DEBT] 引用 209 处 / 对得上 131 / 对不上 0 / 判不出 78 / 豁免 0`，三处坏命令**不在** FAIL/WARN 里。

### 问题 3 · 子命令拼错同样看不见

```text
$ python -X utf8 tools/pool_quota.py statuss
[rc=2]
usage: pool_quota.py [-h] {status,wait,refresh,line} ...
pool_quota.py: error: argument cmd: invalid choice: 'statuss' (choose from 'status', 'wait', 'refresh', 'line')
```

而检查器对 `statuss` 的判决与 `status` 完全相同（问题 2 的 B2）。子命令 token 从不进入 `_flags_of`。

### 问题 4 · 装上 required 尺子，真仓会新红 4 条 —— 3 条正是问题 1，第 4 条在本卡域内

可运行原型 `gates/diag/_probe_w.py`（107 行；`python -X utf8 gates/diag/_probe_w.py [root]`）在真仓的读数：

```text
claim 209；口径 W 新红 4；新增判不出 0
  R ('skills/pipe-card/references/repo-bindings.md:30', ['缺必填参数：--id、--spec、--task、--title'], [])
  R ('skills/softeng-manage/references/dispatch.md:48', ['缺必填参数：--card、--model'], [])
  R ('skills/softeng-manage/references/dispatch.md:77', ['缺必填参数：--card、--model'], [])
  R ('skills/softeng-manage/references/dispatch.md:80', ['缺必填参数：--card、--model'], [])
```

第 4 条原文（`skills/pipe-card/references/repo-bindings.md:30-31`）是「字段清单」散文行：

```text
- `python -X utf8 tools/wb_card.py add`：`--id` / `--task` / `--title` / `--spec` 必填，
  另有 `--file` / `--depends` / `--risk {low,mid,high}`（默认 `mid`）/ `--status` / `--wait` / `--commit`。
```

`tools/wb_card.py:59-63` 四个参数都 `required=True` ⇒ 若只修 dispatch 三处，本卡落地时**自己新造一条红**（在只修 dispatch 的副本上实测：新红 1，剩这一条）。

### 问题 5 · 三处全改成 `line` 会把「可核性」换成「不可核性」

`line` 无必填参数 ⇒ required 尺子对它**无话可说**；子命令尺子也只核 `line` 这个词拼得对。若三处全改成 `line`、不留一条带 `--card / --model` 的具体命令，接口再变时这三处又回到「机器看不见」—— 本卡要防的正是这种**静默回归**。
⇒ 判据 1 要求 `:80` 额外保留一条**具体**的单卡单模型命令（实测 rc=0，见问题 1），给尺子留一个咬得住的位置。

## 判据

### 判据 1 · 三处坏命令改成实测 rc=0 的写法，且四把尺子都不因此变红

- `skills/softeng-manage/references/dispatch.md:48 / :77` 的 `pool_quota.py status` ⇒ `pool_quota.py line`；`:80` ⇒ 先 `line` 看全池、再钉死出事那一条：`python -X utf8 tools/pool_quota.py status --card E113 --model deepseek-v4.1-flash`（写**具体值**；**不许**写 `<卡号>` / `<模型>` 占位符 —— 占位符版实测让现行检查器从 `对得上 131 / 判不出 78` 变成 `130 / 79`，多一条判不出）。
- `skills/pipe-card/references/repo-bindings.md:30` 同卡改成字段清单形态（否则判据 2 的尺子一装上就红，见问题 4）：
  改完那一行长这样（行首一个反引号把工具名括起来，四个 flag 各自独立反引号）：``- `tools/wb_card.py add`：`--id` / `--task` / `--title` / `--spec` 必填，``
  ★ 理由不只是「缺必填」：`scripts/check_docs.py:499-511 is_pointer` 头一条就是 `if not token or " " in token or "\t" in token: return False` —— **含空格的整条命令串永不算引用**；拆成「工具名 + 四个独立反引号 flag」既躲开 required 缺口、也不产生死指针。
  ★ **不许**写成 `--spec 复盘/卡/卡E117-….md`：实测 `is_pointer('复盘/卡/卡E117-xxx.md')` = True 而 resolve = **None** ⇒ 立刻新增一条死指针（`docs` 门 ratchet 只许降不许升）。
- 改完四处必须同时满足（全部现跑；四条读数写进落地记录）：
  - `python -X utf8 scripts/check_layers.py` ⇒ rc=0、末行 `LAYER CHECKS: PASS ✅`（它只扫 `docs/**.md`：`scripts/check_layers.py:191-194`，改 skills 本不该动它 —— 拿它当「没误伤」的对照）；
  - `python -X utf8 skills/nails/check_skills.py` ⇒ rc=0、`钉子② 绿`（只 `rglob("SKILL.md")`：`skills/nails/check_skills.py:231`，不扫 references）；
  - `python -X utf8 skills/nails/check_commands.py` ⇒ rc=0（同理只看 SKILL.md 里的 `pipe <命令>`）；
  - `python -X utf8 scripts/check_docs.py --mode report --file skills/softeng-manage/references/dispatch.md --file skills/pipe-card/references/repo-bindings.md`
    ⇒ 改前实测 `死指针 0（收窄读数，不比基线）` / `drift 533（基线 379，+154 · 可漂移量，只报告）` / `判不出 5 条（skip）` / `CHECK_DOCS: 没判完（有 skip）—— 不许当 PASS`；改后必须**死指针 0 且 skip 不多于 5**。
    ★ 这条**不能用 `--root` 指临时树**验：实测 `--root gates/diag/_tmp_E117_fix8` 给出 `死指针 0（基线未记）` + `判不出 58 条` + `没有基线 doc-debt-baseline.toml ⇒ ratchet 判不了` + `CHECK_DOCS: FAIL ❌` —— 临时树里的同名文件不在扫描集，读数无意义。
- 钉子：不新增文档断言，交给判据 2/3 的尺子咬 —— 变异 A（改成 `statuss`）与变异 B（改回 `status`）都已实测必红（判据 5）。改回坏写法而门全绿 ⇒ 判据 2 没做成。

### 判据 2 · required 判据：缺必填参数必须报「对不上」，不许再报「对得上」

- 判据写在 `tools/check_skills_claims.py` 的 `_judge`（`:330-353`）里、追加到 `claim.problems`（**不是**新字段）—— 这样 `Claim.status`（`:107-115`）的三态与 `EXEMPT` 语义自动继承（豁免压过 problems：`if self.exempt_reason: return STATUS_OK` 先于 problems 判定）。
- required 从**静态 AST** 读（不跑 `--help`、不起子进程）：**只认 `add_argument(..., required=True)` 字面为真**。
  ★ **位置参数不算必填**（这一条是实测后被推翻的）：原型把「位置参数（`nargs` 缺省）⇒ 必填」也算进去，真仓额外新红 **27 条**（`gates/diag/_probe_pos.py` 现读），全部是 `tools/pipeline_view.py --json` / `--report` 与 `tools/auto_land.py --dry-run` 被要求补一个 `command` —— 而 `tools/pipeline_view.py` 里 `add_argument` **一次都没出现**（`grep -n add_argument tools/pipeline_view.py` = 0 命中），那个 `command` 来自它 import 的 `tools/wb_plan.py:1054`。这正是本判据第 4 个陷阱（**不许把 import 到的模块的 parser 合并成一张表**）的同一个病：位置参数没有 `required=True` 这种自证标记，跨文件归属一错就直接冤枉 27 条正确写法。
  ⇒ 位置参数一支**不做**；要做也只能在同一张 parser 表里做，且必须先把跨文件归属修对 —— 那是另一张卡的事。
  代价已量（`gates/diag/_probe_count.py`）：`add_argument 509 次 / required=True(字面) 48 次 / positional 31 个 / 非字面 required 0 次`，15 个文件用 `add_subparsers`。
  ★ 位置参数那 31 个**不进判据**（理由见上一条）：把它们算进必填 ⇒ 真仓额外新红 27 条，全是假红。
  ★ 为什么走 `--help` 那条不行：那要为每条引用手搓 argv 真跑（含 `--preflight` 这类壳层开关的工具跑不通），**本卡未逐个复验（未验证）**；静态读不引子进程、不依赖运行时状态，故选它。
- 遍历必须**分作用域**：模块级只走模块语句、函数只看自己 body、不进入嵌套函数（否则 `tools/pool/task.py` 函数内的 parser 被当模块级，实测多出 61 条假「判不出」）。
- **分批策略（本卡红线，写清为什么）**：只对「完整命令」报 required 缺口，四类**不报**：
  1. 裸工具名零参数（`python -X utf8 tools/wb_land.py` 是**入口指路**，不是待执行的完整命令）；
  2. 含 `--help / -h / --preflight / --precheck`（壳层自己的开关后面不带落地链必填是合法写法：`tools/wb_land.py:48` 与 `:76-79` 导出 `precheck_docs / precheck_main / preflight_main / run_precheck`；分支见 `:571-580`）；
  3. 含占位符 / 重定向（`PLACEHOLDER`，`tools/check_skills_claims.py:78` 命中 ⇒ 本来就 `not verified`）；
  4. 工具不存在或工具名是通配（`tools/wb_*.py`）。
  量化理由（`gates/diag/_probe_v.py` 与 `_probe_ph.py` 现读）：不跳裸名 ⇒ 红 6（多 `skills/pipe-new/references/repo-bindings.md:27`、`skills/softeng-manage/references/mapping.md:72`）；不跳 `--help/--preflight` ⇒ 红 6（多 `skills/pipe-land/references/repo-bindings.md:64`、`skills/pipe-land/SKILL.md:77`）；两条都不跳 ⇒ 红 8；再把含占位符的也核 required ⇒ **额外 11 条**（`skills/pipe-new/references/first-landing.md:31`、`skills/softeng-manage/references/dispatch.md:12` / `:83` 等）。按本卡口径真仓新红正好 **4** 条、全在两份要改的文件里。
- 钉子：`tests/test_check_skills_claims.py` 新增 `test_missing_required_flag_is_named` —— `tmp_path` 造 root，假工具的 `--card / --model` 都 `required=True`，命令写 `python -X utf8 tools/wb_plan.py status` ⇒ 断言 `rc == 1` 且 `"缺必填参数：--card、--model" in out`；同树写全参数 ⇒ `rc == 0`。
  ★ 现有 16 条钉子（`:21-27 TOOL_SRC` 里既无 `required=True`、也无子命令表）在新判据下都是**空转**：探针 `gates/diag/_probe_t.py` 逐条复核 9 个夹具形状，判决逐项不变（`good_tree` ok / `missing_tool` fail / `missing_flag` 仍 fail / `placeholder` 仍 not verified）。但那是**原型**读数 ⇒ 实现后必须真跑 pytest 复核 16 条全绿（**未验证**，且不许删任何断言）。

### 判据 3 · 子命令判据：拼错必须报（本卡就做，不另开卡）

- 词表来源两条都要认：① 主文件自己的 `add_subparsers(...)` + `add_parser("name")`（`tools/pool_quota.py:941-963`）；② 位置参数带 `choices=`（`tools/wb_plan.py:1054-1055`：`choices=("check","plan","stats","worktrees","dispatch","merge")`）。
- 主文件自己没有词表时才退到 `tool_sources()` 跟 import 取（`IMPORT_DEPTH = 2`，`:87`）：`tools/wb_task.py:76-88` 是薄壳，`:86 return _task.main(argv)` 转发 `tools/pool/task.py`。
- 代价已量（`gates/diag/_probe_sub6.py`）：`词表来源计数 {'main': 30, 'union': 1}` / `判不出（无任何词表）: 0` / `命中: 31` / `真红: 0` ⇒ **今天不产生红，装尺子零代价**；装上后变异 A 红 3，说明它咬得住。
- 四个陷阱（真仓都踩过，实现时必须处理）：
  1. 位置 token 必须跳过**紧跟 `--flag` 的值**：否则 `tools/wb_verify.py --tree .` 的 `.`、`tools/wb_dash.py --port 8787` 的 `8787`（`skills/pipe-workbench/references/repo-bindings.md:22`）会被当子命令（早期探针因此多 23 条假「判不出」）；
  2. **不许按「变量名 → 作用域」静态映射**：`tools/pool/task.py:1491 / :1505 / :1516 / :1526 / …` 反复 `p = sub.add_parser(…)` 复用同一变量名，按名字映射会把后续 `add_argument` 全记到最后一个子命令（早期探针因此误报 181 条、串出 `--commit / --reason / --to`）；必须按语句顺序更新映射；
  3. `tools/pool/trae_dispatch.py:322-325` 用 `for name in ("start", "finish", "status"): p = sub.add_parser(name)` 循环建 parser ⇒ 词表取得到，但 required 的 owner 取不到（全仓唯一一处，见判据 4）；
  4. **不许把 import 到的所有模块的 `add_parser` 合并成一张表**：那会把 `tools/pool/*` 的子命令塞进 `wb_plan.py` 的作用域，22 条 `wb_plan.py` 引用被误判「拼错」。
- 钉子：新增 `test_unknown_subcommand_is_named` —— 假工具带 `sub = ap.add_subparsers(dest="cmd")` + `sub.add_parser("status")`，命令写 `… statuss` ⇒ `rc == 1` 且 `"子命令不存在：statuss" in out`；写 `… status` ⇒ `rc == 0`（该形状已在原型上验过：`statuss` ⇒ `['子命令不存在：statuss']`）。

### 判据 4 · 取不到 required ⇒ 记「判不出 not verified」，不许默认当 OK

- AST 解不出 required 时（`required=` 非字面量 / parser 的 owner 推不出来），往 `claim.unverifiable` 追加 `取不到 required：--x（理由）`，**不许静默跳过**。
  ★ 静默跳过长什么样已经量过：原型第一版在 `required` 非字面时既不报红也不记判不出 ⇒ 变异 C 读数 `新红 0` —— 那是**尺子被弯了**，不是「判据 d 成立」。忠实实现后同一变异给出 `新增判不出 1`。
- 代价已量（`gates/diag/_probe_m.py`，真仓）：`sub命令 61；required 分组 12；取不到 1`，唯一那条是 `tools/pool/trae_dispatch.py:325 owner=p`。忠实实现（`gates/diag/_probe_w.py`）真仓读数 `claim 209；新红 4；新增判不出 0` —— 判据 d 的代价近似为零。
- 钉子：新增 `test_unreadable_required_is_not_verified` —— 假工具写 `p.add_argument("--card", required=FLAG)`（非字面）、命令 `… status`：block 档 ⇒ `rc == 3`、输出含 `判不出 1` 与 `取不到 required`、且**不含** `[OK`（`:227-243` 那条已钉「report 档判不出不许打 OK」，照抄同一口径）；report 档 ⇒ `rc == 0` 但仍打 `判不出 1`。
- 现成形状确认（`gates/diag/_probe_x.py` 在修好形状的副本上）：把 `tools/pool_quota.py:943` 的 `required=True` 改成 `required=FLAG` ⇒ `新增判不出 1` = `NV ('skills/softeng-manage/references/dispatch.md:80', ['取不到 required：--card（required 非字面）'])`。

### 判据 5 · 反向变异 ≥5（真改、真跑、真还原，记 sha256）

在「判据 1–4 全做完」的树上做（实测用 `gates/diag/_tmp_E117_fix8` 副本 + `gates/diag/_probe_mut8.py`，读数落 `gates/diag/_probe_mut8.out`）：

- A：三处 `pool_quota.py line` → `pool_quota.py statuss` ⇒ 必红 3 条，逐条报 `['子命令不存在：statuss']`（`:48 / :77 / :80`）；**现行检查器读数完全不变**（`209 / 131 / 0 / 78`）—— 这正是本卡存在的理由；
- B：`:48 / :77` 的 `line` → `status` ⇒ 必红 2 条，报 `['缺必填参数：--card、--model']`；
- B2：`:80` 的具体示例删掉 `--model` ⇒ 必红 1 条，报 `['缺必填参数：--model']`；
- C：`tools/pool_quota.py:943` 的 `required=True` → `required=FLAG`（非字面）⇒ `新红 0 / 新增判不出 1`，那 1 条必须是 `取不到 required：--card（required 非字面）` 且落 `dispatch.md:80`（`:48 / :77` 的 `line` 无必填，不该命中）；
- D：`skills/pipe-card/references/repo-bindings.md:30` 改回真命令形态（整行一条命令 `python -X utf8 tools/wb_card.py add`，不带任何参数）⇒ 必红 1 条，报 `缺必填参数：--id、--spec、--task、--title`；
- E（安静对照）：只改一句注释（`## 定时巡检要分报（三条输出）` → `（三条输出，见下）`）⇒ 两套读数与基线完全一致（不许把注释当命令）。
- 还原纪律：变异脚本必须**字节级** `read_bytes / write_bytes`（主仓 md / py 全是 CRLF；`read_text / write_text` 会把 CRLF 变 LF、sha 对不上 —— 第一版变异脚本就因此报 `restore mismatch`）。
- 基线 sha256（前 16 位；★ 主树已推进到 `e815e1c5`，**实现前必须现读一次**、不许照抄这张表的旧值）：`skills/softeng-manage/references/dispatch.md` = `5acebddf76ba3e75`、`skills/pipe-card/references/repo-bindings.md` = `ef9ffc45bdba1564`、`tools/check_skills_claims.py` = `67c490b55350af05`、`tools/pool_quota.py` = `634dfdfd53ddcc68`。
- 记录落 `gates/diag/_rev_E117_result.txt`（每条变异：改了什么、两套读数、还原后 sha 是否一致）。

## 交付

1. `tools/check_skills_claims.py`：AST 静态读 required / 子命令词表（两条来源）；缺必填与子命令拼错进 `claim.problems`；取不到 required 进 `claim.unverifiable`；四类排除（裸名 / `--help|--preflight` / 占位符 / 工具不存在或通配）。档位语义与退出码口径**一行不改**。
2. `tests/test_check_skills_claims.py`：≥3 条新钉子（判据 2 / 3 / 4 各一条），既有 16 条断言一条都不削弱。
3. `skills/softeng-manage/references/dispatch.md` 三处 + `skills/pipe-card/references/repo-bindings.md:30`（判据 1 的四处改法）。
4. `gates/diag/_rev_E117.py` + `gates/diag/_rev_E117_result.txt`（判据 5 的变异读数）。
5. 卡规格 + 三片段（由落地链的 ② 文档件按台账号 `T-AG627` 自动生成；落成前它们还不存在，所以这里不写死路径）。

## 验收（落地前自跑，零手工步骤）

```bash
python -X utf8 -m pytest tests/test_check_skills_claims.py -o addopts= -q --no-cov
python -X utf8 -m ruff check tools/check_skills_claims.py tests/test_check_skills_claims.py
python -X utf8 tools/check_skills_claims.py --check --mode report   # 期望：对不上 0，判不出 78（不比今天多）
python -X utf8 tools/check_skills_claims.py --check --mode block    # 期望：仍 rc=3（78 条判不出）—— 记读数，不许当绿
python -X utf8 scripts/check_layers.py                              # 期望：rc=0，LAYER CHECKS: PASS
python -X utf8 skills/nails/check_skills.py                         # 期望：rc=0，钉子② 绿
python -X utf8 skills/nails/check_commands.py                       # 期望：rc=0
python -X utf8 scripts/check_docs.py --mode report --file skills/softeng-manage/references/dispatch.md --file skills/pipe-card/references/repo-bindings.md
python -X utf8 tools/pool_quota.py line                             # 期望：rc=0，一行八段
```

（`skills_claims` 不在 `scripts/run_gates.py:144` 的 `FAST` 元组里 ⇒ 这道门只在全量/门表档跑；本地验收以上面第三行为准。）

## 不许做

- **不许把既有 78 条「判不出」一口气改判 FAIL**：那等于把 `skills_claims` 门染红一片、还挡全量门禁。本卡只对**新扫到的 required / 子命令缺口**报红；四类排除（裸名指路 / `--help|--preflight` / 占位符 / 工具不存在或通配）就是分批策略，量化依据见判据 2（不跳 ⇒ 红 8；再把占位符也核 ⇒ 额外 11 条）。
- **不许改判据阈值 / 口径来消红**：`--mode` 的 `choices` 与 `default="block"`（`:436-444`）、`exit_code`（`:408-425`）、`gates/defs/contract.py:25-26` 的门命令、`gates/gate-selfproof.toml:88-89` 的 `reverse_case` 一条都不许动；不许把 `docs/doc-debt-baseline.toml` 的任何数字上调。
- **不许用 `EXEMPT` 当消红手段**：`Claim.status` 里豁免**压过** problems（`:107-115`），写一条豁免就能把真红洗成 OK。要豁免必须写进卡规格并说明理由，不许在实现里偷偷加。
- **不许把判据写进 `skills/`**：`skills/` 只写「怎么用才不出错」，判据真源只有 `tools/` / `tests/` 的一份。
- **不许在反引号里写不存在的路径**：`check_docs` 的 ratchet 只许降不许升（`复盘/卡/卡E117-….md` 这种还没落成的卡规格路径**就是**死指针）。
- **不许顺手改 `tools/pool_quota.py`**：它的 `status` 需要 `--card / --model` 是正确设计（本卡改的是**文档里的写法**）。
- 不许在本卡里顺手改 `gates/diag/` 下别人的探针与产物（本次勘察留下的 gitignore 杂物由落地链清理或说明）。
