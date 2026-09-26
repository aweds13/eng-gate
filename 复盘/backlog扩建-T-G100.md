# backlog 扩建：把盘点结果切成「域不相交」的卡（T-G100 · 外包卡 013）

> 一句话：并发的上限**不是机器**（32 核、每个工人只吃 ~270 MB），是**"互不相交的源码域有几个"**。
> 这张卡把盘点卡 S-1 挖出的 **A 类（纯技术）+ D 类（文档漂移）** 按**文件域**切成一张张卡，写进
> `docs/workbacklog.toml`，让调度器 `tools/wb_plan.py` 以后能**自动排出最大并发**。
>
> 边界先说：这是一张**只写 backlog** 的规划卡 —— 不动任何源码、不动四条种子、不建树、不派活。

---

## §1 输入（两张，先完整读过）

1. `gates/diag/盘点-20260926.md`（盘点卡 S-1）：A 类 **23** 条 / B 类 **9** 条 / C 类 **11** 条 / D 类 **18** 条。
   **每条都带"涉及文件"** —— 这正是切域要的料。
2. `docs/workbacklog.toml`（调度器的 backlog）：已有**四条种子** `007/008/009/010`（当前在飞）。

## §2 怎么切域（机械口径，可复算）

对每条活做四步：

1. **取域**：把盘点报告"涉及文件"列读成一个文件集合 = 这张卡的**冲突域**。
2. **同文件必合并**：两条活的文件集有交集 → **合成一张卡**（卡 013 §2.2：同一文件的活本来就该一个人做）。
   例：A4（myday 死代码）与 A21（长文案）都只碰 `src/web/index.html` → 合成卡 014。
3. **避开种子域**：与种子卡（007/008/009/010）的文件相交的活 → **不另立卡**（立了必相交）。
4. **避开受保护共享文件**：`files` 不许含那六个（`wb_plan.py check` 会拒）。

★ **一条读完 `wb_plan.py` 才看清的硬约束**（卡 013 §2 没明写、但决定了切法）：
`validate()` 把**整份 backlog 当作同一批**来判 —— 也就是**两卡的 `files` 全局不许相交**、**树全局不许重复**。
所以「两张卡给其中一张标 `depends`（串行）」**并不能让相交的两卡共存**（`check` 仍拒）。
**唯一出路是"合并"** —— 这跟卡 §2.2「同一文件上的多条活优先合成一张卡」正好同向。

## §3 切出多少张卡

**新增 7 张卡**（`014`–`020`）；连同四条种子，backlog 共 **11 张**，**11 个两两不相交的域**。

| 新卡 | Task | 覆盖的盘点条 | 文件域（= 冲突域） | 树 | risk |
|---|---|---|---|---|---|
| **014** | T-G101 | A4 + A21 | `src/web/index.html` | `.wt/web` | mid |
| **015** | T-G102 | A5 | `src/timeflow/api/app.py`、`docs/contracts/domains/F1-tasks.md`、`docs/commands.toml` | `.wt/api` | mid |
| **016** | T-G103 | A12 | `tools/contrast_audit.py`、`tests/test_contrast_nontext.py` | `.wt/contrast` | mid |
| **017** | T-G104 | A13 | `src/web/app.css` | `.wt/css` | mid |
| **018** | T-G105 | A15 + A22 + D18 | `gates/diag/inspect.py`、`gates/diag/round-plan-T-G92-G93.md`、`gates/diag/T-G93-ledger-draft.md` | `.wt/diag` | low |
| **019** | T-G106 | A16 | `scripts/run_gates.py` | `.wt/gates` | mid |
| **020** | T-G107 | D9 + D12 + D13 + D14 + D15 + D16 | `复盘/视觉线地图.md`、`复盘/任务重规划-剩余工作.md`、`复盘/跨端实时专注-T-G20.md`、`复盘/使用体验问题与修改台账.md`、`复盘/外包-卡表与规矩.md`、`docs/contracts/flows.md` | `.wt/docs` | low |

> **卡 020 是 D 类合卡**：它改的全是**跨卡共享的复盘/文档**，按卡 013 §2.4 标「**独占共享文档，必须单独跑**」。

## §4 没进 backlog 的活（都写清为什么）

### 4.1 A 类里**被种子卡占住域**的 15 条（立了必相交 → 不另立）

| 种子卡（域） | 被它占住域的 A 类条目 |
|---|---|
| **007** `tools/wb_dispatch.py` | A2 / A3 / A10 / A11 / A14 / A17 / A19 / A20 / A23 |
| **008** `tools/wb_dash.py` | A1 / A18（+ D10 同域） |
| **009** `src/timeflow/core/tasks/manager.py` | A6 / A7 / A8 / A9 |

★ 盘点报告里 A9 写着「**先 A6/A7**」、A6 写着「**可并入 A9**」—— 这些依赖**全在种子 009 的域内部**，
所以**不进新卡的 `depends`**（卡 013 §2.3：依赖只写真的有的，别为排得好看硬造）。

### 4.2 D 类里**要改受保护共享文件**的 10 条（作者一律不许碰 → 只能主控串行收口）

- **D1–D8**：目标含 `复盘/交接-重构进度.md` 和/或 `复盘/新窗口交接卡.md`（**受保护**）。
- **D11**（`docs/traceability.toml` 的 `T-G79.title`「13 条」）+ **D17**（`docs/traceability.toml` 的
  `T-G56.gaps` 说没有弃用标记）—— 目标含 `docs/traceability.toml`（**受保护**）。

★ 把它们塞进任何卡的 `files` 都会被 `check` **直接拒单**（"含受保护共享文件"）→ 这几条只能由主控在
收口时改，**不进 backlog**。

### 4.3 B 类（9 条）/ C 类（11 条）

按卡 013 §2.4 一律**不进 backlog**（要用户决策 / 要人工动手）。

## §5 check / plan 的真实输出（可复现）

```text
$ python -X utf8 tools/wb_plan.py check
[OK ] backlog 校验通过：11 张卡，无冲突（基点 1969b46）

$ python -X utf8 tools/wb_plan.py plan --concurrency 6
[计划] 并发上限 6；11 张卡 → 2 批
第 1 批（6 张，可同时跑）
  · 卡 007（T-G96）｜树 （主树）｜看门狗护栏补强
  · 卡 008（T-G97）｜树 .wt/dash｜面板口径对齐
  · 卡 009（T-G98）｜树 .wt/core｜myday序号根因
  · 卡 010（T-G99）｜树 .wt/plan｜并发调度器
  · 卡 014（T-G101）｜树 .wt/web｜…index.html：删 myday 拖拽死代码 + 压长文案棘轮
  · 卡 015（T-G102）｜树 .wt/api｜myday-move 的空 before 口径对齐
第 2 批（5 张，可同时跑）
  · 卡 016（T-G103）｜树 .wt/contrast｜非文字对比度门补暗色悬停/选中态那一半
  · 卡 017（T-G104）｜树 .wt/css｜字号档位令牌化
  · 卡 018（T-G105）｜树 .wt/diag｜diag 目录清账：inspect.py + 两份草稿
  · 卡 019（T-G106）｜树 .wt/gates｜核 gates/reuse.json 的复用判定
  · 卡 020（T-G107）｜树 .wt/docs｜★ 独占共享文档，必须单独跑：把过时的字改对
```

（上面 `plan` 的"域"行与 `check` 的完整输出见命令原始输出；此处只留结构与批次。）

### 5.1 ★ 轻门有一条**红**：`tests/test_wb_plan.py`（5 条）—— 卡 010 的测试把 backlog 内容**写死**了

```text
$ python -X utf8 -m pytest tests/test_wb_plan.py -q
5 failed, 36 passed in 0.39s
FAILED tests/test_wb_plan.py::test_seed_backlog_loads_and_is_conflict_free
FAILED tests/test_wb_plan.py::test_seed_toml_roundtrips_with_tomllib
FAILED tests/test_wb_plan.py::test_seed_plan_with_concurrency_three
FAILED tests/test_wb_plan.py::test_seed_plan_with_concurrency_two
FAILED tests/test_wb_plan.py::test_plan_command_prints_batches
```

**根因**：这 5 条把**真种子文件** `docs/workbacklog.toml` 的内容断言成**恰好四张** ——
`assert [c.id for c in backlog.cards] == ["007", "008", "009", "010"]`（`test_wb_plan.py:264`、`:272`）
与 `assert ... == [["007","008","009"], ["010"]]`（`:282`、`:288`）、`assert "4 张卡 → 2 批" in out`（`:351`）。
本卡的任务**就是**往这个文件里追加卡 → 这 5 条**必然红**。

★ 也就是说：**卡 013 §0.3（要跑 `tests/test_wb_plan.py` 当轻门）与 §3（禁碰 `tests/**`）在"追加卡"这件任务上
互相矛盾** —— 门必然红，而我**不许**改那个测试文件。**这是本卡无法自行解开的一处死结** → 按铁律
「拿不准口径就停下、在回报里说明」**没有提交**（见 §回报）。

**建议的最小修法**（改的是 `tests/test_wb_plan.py`，属卡 010 的域 → 须主控授权或另立一张小卡）：
把这 5 条从「**内容恰好等于四张**」放宽成**对新卡增长免疫**的判据 —— 二选一：
- ① **断言不变量**：`validate(backlog) == []` + `{"007","008","009","010"} <= {c.id for c in backlog.cards}`
  + id 唯一；批次断言改成「007 在 008 前、009 在 010 前」这类**相对顺序**，而不是整份相等；
- ② **用固定夹具**：把"四张种子"复制进 `tmp_path` 的临时 TOML，`plan_batches` 对**夹具**断言真的批次，
  真文件只保留"能读 + 无冲突"这一条。
（我**没有**动它，也没有动 `tools/wb_plan.py` —— 卡 013 §2.5 明令不许改判据去绕。）

## §6 边界（如实写，没做到 / 没法做的部分）

1. ★ **D 类合卡没能用 `tree = ""`（主树）**。卡 013 §2.4 说 D 类那种卡标 `tree = ""`（主树），
   但**主树 `""` 已被种子 007 占住**，而 `check` 拒「一树两写者」→ 只能给卡 020 用独立树
   `.wt/docs`，并在 `title` 里**保留**那句「独占共享文档，必须单独跑」。**这是与 §2.4 的一处偏离**，
   如实记在这里（根因：整份 backlog 全局判"一树一写者"，不是同批才判）。
2. ★ **种子 007/008/009/010 的 `status` 仍是 `pending`，但它们的活其实已经落地**（`line/impl-v1` 里
   有 `T-G96`/`T-G97`/`T-G98`/`T-G99` 四笔提交，对应主树的 `ba16589`/`7a99642`/`3d319f8`/`738e3ef`）。
   卡 013 §6.1 明令**别改种子** → 一个字没改；这导致 `plan` 把**已完成**的种子也排进批次。
   **backlog 与现实的这处不一致，留给规划者收口时按实际情况调 `status`。**
3. **`spec` 路径按种子惯例填**（`gates/diag/卡0NN-*.md`）—— 这些**规格文件目前还不存在**，
   跟种子 007/008/009 一样（`复盘/并发架构-T-G99.md` §九.7 已说明："按命名惯例填"）。
   派活前由**规划者**把每张卡的规格落盘（`wb_dispatch.py` 的前置检查会核"卡规格在不在"）。
   ★ 我**没有**改 `check` 口径去绕它（卡 013 §2.5）；这一版 `check` **确实不校验 `spec`**，
   所以没报错 —— 如实记：**不是"绕开了"，是这条判据不存在**。
4. **新卡号从 `014` 起**（不是 `011`）：本轮并发批次里 `011`/`012`/`013` 已是别的卡
   （`gates/diag/` 里能看到 `卡012-集成者.md`、`卡013-backlog扩建.md`）→ 新卡接 `014`。
   若规划者的编号口径不同，这是**一处需要主控确认的假设**（见 §回报"疑问"）。
5. **A13（字号令牌化）会动界面** → 需要**重采渲染黄金**（`gates/render/*`）。黄金路径**没写进**
   `files`（盘点"涉及文件"列只给了 `src/web/app.css`；种子卡也不把黄金写进域）→ 派活时按
   `复盘/视觉线地图.md` 的做法全量重采，别用 `--only`。**这是"域声明"与"实际会碰的东西"的一处差**。
6. **A5 与 B9 是同一件事的两面**：A5 让人"改代码对齐文档"（选默认当末尾→400 那条），B9 说若认为
   该改文档则要一句口径。我把 A5 按盘点报告的 A 类处理（立了卡 015，默认方向 = 改代码对齐文档），
   **若主控认为这其实是产品口径（B9），应把卡 015 撤下并等用户一句话** —— 这一条**请主控定**。
7. **A22/D18 是"删文件"**（删 `gates/diag/` 两份已完成使命的草稿）。这两份是 **gitignored 的**、
   不进 git，删了不影响仓库历史；但"删"本身属不可逆动作 → 已在卡 018 的 `title` 里写明目标，
   派活时须让工人确认这两份确已无用。
8. **"互不相交的域有 11 个"是就**这份 backlog 的 11 张卡**而言**；它**不等于**"仓库能开的并发上界"
   —— 还有 CLI/账号侧的上界（`wb_plan.py` §九.1 已记"未探测"）。`--concurrency 6` 是我按
   `N ≤ max(2, cores//2)`（本机 32 核）取的一个显式值，**不是测出来的上界**。

## §7 没动的

`src/**`、`tools/**`（含 `wb_plan.py`）、`scripts/**`、`tests/**`、`docs/` 下其它文件
（含 `docs/traceability.toml` / `docs/changelog.md`）、`复盘/交接-重构进度.md`、
`复盘/新窗口交接卡.md`、`gates/**`、`gates/diag/盘点-20260926.md`（只读）、真实库/备份目录、
三个外来未跟踪文件。**四条种子 007/008/009/010 一个字没改**（`git diff` = 纯追加 +120 行、0 删除）。

## 台账条目（供集成者粘贴）

```toml
[entries."T-G100"]
id = "T-G100"
title = "把盘点结果切成域不相交的 backlog：并发上限由「互不相交的源码域个数」决定，不由机器决定"
group = "PROCESS"
status = "done"
evidence = [
  "file:复盘/backlog扩建-T-G100.md",
  "file:docs/workbacklog.toml",
  'text:docs/workbacklog.toml::id = "020"',
]
gaps = "**为什么有这张卡**（T-G100，= 外包卡 013）：并发上限**不是机器**（32 核、每个工人只吃 ~270 MB），而是「互不相交的源码域有几个」；盘点卡 S-1 已把「还剩哪些活」挖齐（A23/B9/C11/D18，每条带涉及文件），本卡把 A+D 按**文件域**切成一张张卡写进 `docs/workbacklog.toml`，让 `tools/wb_plan.py` 能自动排最大并发。**怎么切域**：每条活取「涉及文件」= 冲突域 → 同文件的两条合成一卡 → 与种子（007/008/009/010）同域的不另立 → `files` 不许含六个受保护共享文件；★ 关键约束是 `validate()` 把**整份 backlog 当同一批**判（两卡 `files` **全局**不许相交、树全局不许重复），所以「标 `depends` 串行」救不了相交的两卡，**唯一出路是合并**。**切出多少张卡**：新增 **7** 张（`014`–`020`，task `T-G101`–`T-G107`）+ 四条种子 = **11** 张，**11 个两两不相交的域**；覆盖 A4/A21（014）、A5（015）、A12（016）、A13（017）、A15/A22/D18（018）、A16（019）、D9+D12+D13+D14+D15+D16（020）；`plan --concurrency 6` → **2 批（6 + 5）**。**没进 backlog 的**：A 类里被种子占住域的 15 条（与 007 同域 A2/A3/A10/A11/A14/A17/A19/A20/A23；与 008 同域 A1/A18/D10；与 009 同域 A6/A7/A8/A9 —— 其依赖全在种子卡内部，故不写 depends）；D 类里要改**受保护共享文件**的 10 条（D1–D8 改交接/新窗口交接卡、D11/D17 改台账 —— 作者不许碰，只能主控收口）；B/C 类一律不进。**check 与 plan 的真实输出**：`check` → 「校验通过：11 张卡，无冲突（基点 1969b46）」；`plan --concurrency 6` → 第 1 批 6 张（007/008/009/010/014/015）、第 2 批 5 张（016/017/018/019/020）。**边界（如实写）**：① D 类合卡**没能用 `tree = \"\"`（主树）** —— 主树已被种子 007 占、`check` 拒一树两写者 → 卡 020 用独立树 `.wt/docs`，`title` 保留「独占共享文档，必须单独跑」；② 种子 `status` 仍 `pending` 但活已落地（T-G96–T-G99 已在 `line/impl-v1`）→ `plan` 会把已完成的种子排进批次，留规划者调 `status`；③ 新卡 `spec` 按种子惯例填（文件尚未存在，派活前由规划者落盘；本版 `check` **不校验 `spec`**，如实记）；④ 新卡号从 `014` 起（011/012/013 已是本批别的卡）——需主控确认编号口径；⑤ A13 动界面需**全量重采渲染黄金**，黄金路径未写进 `files`；⑥ A5 与 B9 是同一件事两面（默认方向 = 改代码对齐文档），若判为产品口径需撤下卡 015；⑦ A22/D18 是删 gitignored 草稿（不进 git，但属不可逆动作）；⑧ 「11 个域」只就这份 backlog 而言，**不等于** CLI/账号侧并发上界（`wb_plan.py` 已记「未探测」）；⑨ ★ **轻门 `tests/test_wb_plan.py` 有 5 条红** —— 卡 010 的测试把 backlog 内容**写死成恰好四张**（`== [\"007\",\"008\",\"009\",\"010\"]` 等），追加卡必红，而本卡 §3 禁碰 `tests/**` → **本卡未提交**（详见复盘 §5.1 与回报；修 `tests/test_wb_plan.py` 须主控授权或另立小卡）。**没动的**：`src/**`、`tools/**`（含 `wb_plan.py`）、`scripts/**`、`tests/**`、`docs/` 其它文件（含台账/changelog）、两张交接文档、`gates/**`、`gates/diag/盘点-20260926.md`（只读）、真实库/备份目录、三个外来未跟踪文件；四条种子 007/008/009/010 一字未改（git diff = 纯追加）。"
```

## 6 交给你（卡 014）的那处死结怎么解的

### 6.1 修法：两层 —— 真文件只钉「不变量」，「批次」改用冻结夹具

那 5 条红的根子是**把真文件的内容写死成"恰好四张种子"**。修法按「断言的是什么」分两类：

- `test_seed_backlog_loads_and_is_conflict_free` / `test_seed_toml_roundtrips_with_tomllib`
  → 对**真文件**只钉**不变量**：`validate(backlog) == []`（无冲突）、id **唯一**、
  `{"007","008","009","010"}` 是实际 id 集合的**子集**；roundtrip 那条改成
  「`tomllib` 与 `load_backlog` 两个读法读出**同一串 id**」+ 种子在里头 + 无受保护文件。
- `test_seed_plan_with_concurrency_{two,three}` / `test_plan_command_prints_batches`
  → 对一份**冻结夹具 TOML**（测试里的 `_SEED_FIXTURE_TOML` = 四条种子的一字不差副本，写进 `tmp_path`）
  断言**精确**批次（`[["007","008","009"],["010"]]` / `[["007","008"],["009","010"]]`）
  与 `4 张卡 → 2 批`。CLI 那条改走 `--backlog <夹具>` —— 端到端仍过 `main → load → plan → 渲染`。

**为什么两层都用（而不是只做一层）**：只用「①不变量」会把**批次**判据一起放宽成「存在性」
（比如只断言「007 在 008 前」）—— 那是**真的削弱**调度器的输出判据；只用「②夹具」则**真文件没人验**
（连"能不能读、有没有冲突"都不验）。两层合起来：真文件钉「这份 backlog 站得住」，
夹具钉「调度器对已知输入吐出的批次一字不差」。**新卡随便加、两层都不假红；调度器逻辑一错，夹具那层当场咬。**

### 6.2 突变检验（★ 改测试之前先证明它还会咬）

**突变 ①（卡 §2.2 要求的那条）**：把 `tools/wb_plan.py` 的冲突检测改坏 ——
`files_intersect()` 恒返回空集（= 从不认为两卡相交）。

```text
$ python -X utf8 -m pytest tests/test_wb_plan.py --no-cov
...
FAILED tests/test_wb_plan.py::test_files_intersect_helper - AssertionError: a...
FAILED tests/test_wb_plan.py::test_intersection_is_rejected - AssertionError:...
FAILED tests/test_wb_plan.py::test_check_command_fails_on_conflict - assert 0...
3 failed, 38 passed in 0.41s
（退出码 1）
```

→ **咬住了**（红的 3 条全是判「冲突检测」的）。还原（`git checkout -- tools/wb_plan.py`）后：

```text
$ python -X utf8 -m pytest tests/test_wb_plan.py --no-cov
.........................................                                [100%]
41 passed in 0.26s
```

★ 如实记一条：`test_greedy_pack_pairwise_intersecting_each_gets_own_batch`（三卡两两相交、各占一批）
这次**没红** —— 因为那三张卡的**树都在主树**，是**「同树」那条判据**把它们拆开的，与 `files` 相交无关。
「这次没红」不代表它不咬，只是这道突变换了条判据拦它。

**突变 ②（我自加的，专证「改完的那几条」还咬）**：删掉 `greedy_pack` 的并发上限判据
（`if len(batch) >= limit:` → `if False:`）。

```text
FAILED tests/test_wb_plan.py::test_greedy_pack_respects_concurrency_limit - A...
FAILED tests/test_wb_plan.py::test_seed_plan_with_concurrency_three - Asserti...
FAILED tests/test_wb_plan.py::test_seed_plan_with_concurrency_two - Assertion...
FAILED tests/test_wb_plan.py::test_plan_command_prints_batches - AssertionErr...
4 failed, 37 passed in 0.41s
```

→ **两条改过的夹具用例 + 那条 CLI 用例都红了** —— 它们不是「改宽了就什么都不验」，是对
**调度器的真实输出**在下判据。同样 `git checkout --` 还原（`git status` 只剩 `tests/test_wb_plan.py`）。

### 6.3 哪条「咬不动」（如实写）

- 两条改成「不变量」的用例（load / roundtrip）**对「冲突检测被改坏」不咬**：它们断言的是
  「真文件无冲突」，冲突检测坏了只会让「无冲突」更容易成立、不会红。**这是设计如此** ——
  它们钉「这份 backlog 站得住」；「冲突检测写对了没有」由上面 3 条专门用例钉。
- 其余每条都有一次对应的突变让它红。**本案没有「删掉接线仍全绿」的假护栏。**

### 6.4 一处如实记（越出你点名范围、我没动的地方）

`test_seed_high_risk_cards_are_seeded`（同节）也把**真文件的风险集**写死成 `== {"007","009"}` ——
它**现在恰好不红**（013 追加的 7 张卡都是 mid/low），但只要以后往 backlog 加一张 `risk = "high"`
的卡，它就是**同一类死结**（会假红）。它**不在你点名的 5 条里**，卡 §2.1 说只修这 5 条 → **我没动它**。
要不要一并解耦（改成 `set(high) >= {"007", "009"}`），**请主控示下**。
