# 落地参数与文书（细则）

> `pipe-land/SKILL.md` 的按需参考。**判据在 `tools/pool/landing.py`**；
> 这里只讲「每个参数是干什么的、文书三段写什么」。

## 1. 参数表

| 参数 | 必填 | 作用 / 常见误用 |
|---|---|---|
| `--card` / `--batch` | 二者**恰好一个** | 卡号或批号，也当门禁锁的标签；两个都给会被拒 |
| `--tree` | 是 | 卡树路径（`.wt/<卡号>`） |
| `--task` | 是 | 台账号（`T-AG…`）；`Task:` trailer 用它 |
| `--title` / `--type` / `--scope` | 标题是 | 组提交信息 |
| `--evidence` | 是 | 证据指针（可多个），会进台账 `evidence` |
| `--allow` | 是 | **白名单**：这一笔允许进提交的路径（可多个）。少一个 ⇒ 那个文件进不来 |
| `--refs` | 否 | 其它相关编号，进 `Refs:` |
| `--port-base` | 否 | 门禁锁的端口段；**释放锁要带同一个段**，否则锁泄漏 |
| `--no-gate` | 否 | 只在文档件 / 白名单上试跑；trailer 会如实写「这一笔没跑门禁」 |
| `--no-reset` | 否 | 关掉⓪回退；**重跑时别关**，否则必撞「重复合成」 |
| `--commit-only` | 否 | 门禁已绿、封存没变：⑥ 起接着走 |
| `--affected` / `--changed-from` | 否 | 增量门禁（默认关）；碰 `scripts/` `tools/` `gates/` 会强制回全量 |
| `--no-review` | 否 | 跳过⑧复核落盘（默认开） |
| `--skip-preflight` | 否 | 跳过③″快门禁预检（已知道要跑全量时）。**旧写法 `--no-preflight` 已改名，仍收但会提示** |
| `--precheck` | 否 | **壳层参数、不转发给落地链**：落地前置快检（文书裸文件名 + 两道秒级检查），见 §5.1 |

## 2. 三段文书（`gates/diag/_text_<台账号>.md`）

`wb_stage_card.py` / 落地链读的是同一个文件，三段用标记切开：

```markdown
=== gaps ===
（边界与没做的事，每行带真实路径；不许写「一切正常」）
=== changelog ===
（≤6 行；下一行必须是 `## 2026-…` 标题，别把条目插到标题上面）
=== checkpoint ===
（当前状态一句话 + 指针）
```

两个会咬人的细节：

- `=== changelog ===` 的下一行**必须**是日期标题；把 bullet 插在它上面会让下一次生成器停手。
- 反引号里别写不存在的 `.md` 路径或通配符（`复盘/卡/*.md` 这种）——
  `check_layers` 会当断链咬。

## 3. 封存（seal）读法

- `gates/last.json`：`rev` 是**被封的那笔**，落地后应等于 `HEAD^`；`tree` 是去掉 `gates/**` 的提交树。
- 封存之后再新增文件，「提交树」就 ≠ 「封存树」—— 台账 / changelog / 复盘**必须在跑门禁之前就位**。
- 对不上时**不许手改** `last.json`；重跑落地。

## 4. 断点与重跑

| 现场 | 用哪个 |
|---|---|
| 被内存闸 / 门禁红挡在④之前 | 直接重跑（⓪ 会回退派生物） |
| 门禁已绿、封存没变，只差提交 | `--commit-only` |
| 只想在文档件上试跑 | `--no-gate`（并在回报里如实写「没跑门禁」） |
| 锁没释放 | 按端口段释放，带同一个 `--port-base` |

## 4.1 `--commit-only` 的五步前置（全漏过一遍，各红一次）

`--commit-only` 在 `tools/pool/landing.py` 里**跳过 ①~⑤**（含 ② 文书、③ `sync_counts`、⑤ 封存），
只做 ⑤′ 翻账 + ⑥ 提交 + ⑦ 审计 + ⑧ 复核。所以那五步得**先手工做到位**，顺序不许换：

1. **卡树 realign 到主树 HEAD**：`git -C .wt/<卡> reset --hard <主树HEAD>`（在卡树里直接建、基点落后时，
   ⑥ 出的提交会在 rebase 时撞 `docs/workbacklog.toml` / `docs/traceability.toml` 冲突，工具判「非派生物」停手退 3）。
   换基点又不想丢改动：`git branch -f parked <旧提交>` → `reset --hard <新基点>` → `cherry-pick -n parked`。
2. **派生文件按“主树版 + 重算”解**：冲突里的 `docs/traceability.toml` / `docs/changelog.md` /
   `复盘/交接-重构进度.md` 都是生成物 ⇒ 取主树版后用 `tools/sync_docs.py` + `tools/sync_counts.py` 重算；
   **`docs/workbacklog.toml` 是非派生物，只能人来判**（一般只有本卡的 `status` 要翻 `done`，其余取主树版）。
3. **三个片段先 `git add`（不提交）**：`docs/changelog.d/<台账号>.md`、`docs/traceability.d/<台账号>.toml`、
   `复盘/交接.d/<台账号>.md`。漏了这一步，审计 ⑪ 会判「封存时未跟踪、现在仍未被 git 跟踪 ⇒ 集成时 `--allow` 漏了它」，
   并连带 `tests/test_docs_fragments.py::test_audit_verdict_unchanged_by_sync` 红 —— 红得像“门禁坏了”。
4. **本树 `gates/last.json` 必须是绿的上一趟**：钉子 `tests/test_false_success_pins.py::
   test_pin_gate_green_is_exit_codes_not_the_ok_field` 读的是**本树**那份，上一轮红过就把自己判红
   （`真 last.json 被判红 —— 判据先自己坏了`，读数里会写 `exit_code 非零 2 道：['pytest','audit']`）。
   处置：`cp gates/last.json .wt/<卡>/gates/last.json`（主树那份绿的；该钉子会把 `rev` 归一化到 `HEAD^`，所以能借用）。
5. **跑全量门禁 → `--seal` → 收口**：`TF_PYTEST_WORKERS=4 TF_GATE_PORT_BASE=<段> python -X utf8 scripts/run_gates.py`
   在**卡树里**跑（`run_logged.py` 用 `../../../tools/run_logged.py`、日志写 `../../gates/diag/…`），
   绿了再 `scripts/run_gates.py --seal`，最后 `wb_land.py --commit-only`。

另两条同族硬约束：`gates/diag/batch/<批号>.toml` **不许**进 `--allow`（`gates/diag/*` 被 `.gitignore` 忽略，
链里 `git add` 不带 `-f` ⇒ 直接退 2）；`--title` / `--evidence` / `--allow` 三者必填（漏了 argparse 退 2）。

## 跑法：长门禁别用管道截断

落地要跑全量门（8–12 分钟）。**不要**写成 `wb_land.py … | tail -3`：管道会攒到结束才吐，后台作业中途读不到任何输出，看着像卡死。一律用带日志的跑法：

```bash
python -X utf8 tools/run_logged.py --log gates/diag/land-<卡>.log -- \n    python -X utf8 tools/wb_land.py --card <卡> ...
```

进度看 `tail -n 20 gates/diag/land-<卡>.log`；跑前先过 `python -X utf8 tools/cmd_guard.py --cmd '<命令>'`。

## 5. 落地三坑（会真红的那种）

> 这三条都让落地链**真红**过；写文书 / 给白名单 / 合卡树时逐条对照，别撞上了才知道。
> 同族见 `复盘/口径坑.md` 坑 21/29/40（反引号里写 `.md` 断链那一族）。

### 5.1 文书里写裸文件名反引号 → check_layers 断链

- **规则一句话**：**文书只许写仓内全路径，裸文件名会被 check_layers 当路径**。
- **症状原文**：`scripts/check_layers.py` 报「引用断裂: docs\changelog.md 引用了不存在的 SKILL.md」，814 条引用断链 2 处。
- **根因**：`scripts/check_layers.py` 把**反引号里包着的 `.md` 词**当路径引用去查；裸文件名不是真路径，查不到就判断链。占位符、通配符一样咬。
- **处置写法**：反引号里只写真路径（如 `skills/pipe-card/SKILL.md`）；占位符去掉反引号（写成「md 文件」）；通配符别带 `.md`。
- **★ 前移到秒级（卡 A301）**：第 ② 步（文档件）跑完、进全量门禁之前，先跑
  `python -X utf8 tools/wb_land.py --precheck <台账号>` —— 它只扫本次那两份文书
  （`gates/diag/_text_<台账号>.md` 与 `docs/changelog.d/<台账号>.md`）里反引号包着的裸文件名
  （无 `/` 或 `\`、以 `.md` / `.toml` / `.py` 结尾），再跑 `scripts/check_layers.py` 与
  `tests/test_check_skills.py`；红了**退非 0 并停手**，全量门禁一步不跑（几秒 vs 几分钟）。
  ★ 唯一的放行：**仓根下真有这个文件**（根级文件的全路径就是裸名），其余照红。
  ★ 边界：接线（把它插在落地链 ② 与 ④ 之间）要改 `tools/pool/landing.py`，卡 A301 的 files 域里没有它 ⇒
  眼下由落地的人手动先跑这一句。
- **证据路径**：`复盘/口径坑.md` 坑 21/29/40；`复盘/卡/卡A295-坑进流程.md`；`tests/test_false_success_pins.py`（快检与真门同向那条）。

### 5.2 主树里未跟踪的卡规格挡住 ff 合流

- **症状原文**：`error: The following untracked working tree files would be overwritten by merge`。
- **根因**：主树里有未跟踪的卡规格（同名的已在卡树提交里），ff 合流要写它但工作区已有一份 ⇒ git 拒绝覆盖。
- **处置命令**：先确认内容已在卡树提交里（`git -C .wt/<卡号> log -- <规格路径>`），删主树那份，再 `git merge --ff-only <sha>`；或先把规格 `git add` 进卡树再合。
- **证据路径**：`复盘/卡/卡A295-坑进流程.md`；ff 合流在 `tools/pool/landing.py` 落地链里。

### 5.3 `--allow` 是精确路径匹配，不是 glob

- **症状原文**：`tools/pool/landing.py` 的 `staged_and_extra` 里 `extra = [f for f in staged if f not in allow]`——少给一个文件，那个文件就进不来。
- **根因**：`--allow` 是**精确路径匹配**（`f not in allow`），不是 glob；且每个改动文件都要有一条 evidence 指针，否则审计按文件点名红。
- **处置写法**：白名单逐文件列（`--allow <路径1> --allow <路径2> …`），证据指针同样逐文件给；别指望通配或目录覆盖。
- **证据路径**：`tools/pool/landing.py`（`staged_and_extra` / `f not in allow`）；`复盘/卡/卡A295-坑进流程.md`。

### 5.4 要提交的文件没先进卡树 → 文书引用不可达

- （缺口 PO8）收口链先把「要提交的文件」同步进卡树，否则文书生成时引用不可达 ⇒ 每笔都可能假红。
- **症状原文**：文书里的 `file:` 引用指向的文件还只在主树，卡树里没有这份 ⇒ 复算 / 审计在卡树里查引用查不到，按断引用判红——红在「顺序」，不是红在判据。
- **根因**：文书（§2 三段）在卡树里生成、随卡树一起封存；引用的文件若没先进卡树，引用对这棵树就是不可达的。
- **处置命令**：先把要提交的文件同步进卡树（`git checkout <主树> -- <文件>`），再生成文书；顺序不许反。
- **证据路径**：`复盘/交接.d/T-G274.md`；文书三段写法见本文件 §2。
