# 卡 209 —— **skill 层加严**：长度上限 + 「验收必须指向脚本」+ 人类理解版（T-G318）

**树**：`.wt/skillnails` ｜ **base**：主控派活时的主树 HEAD ｜ **提交**：★ 不要 commit
**成员号**：任务 `B-SKILLNAILS` 的 **M-1**。★ **干完必须交成送申请**：`python -X utf8 tools/wb_task.py claim B-SKILLNAILS M-1 --claim success --why "…" --evidence "…"`。

## 为什么有这张卡

用户 2026-10-13 让主控读他的一篇笔记《AI agent skill 的一些开发经验》，里面三条与**本仓 `skills/` 直接对应**：

| 笔记原话（意译） | 本仓现状 |
|---|---|
| 「**用确定的程序验收 AI 的输出**……写在 skill 里 agent 会因上下文/随机因素忽略」 | 本仓已有 `skills/nails/check_skills.py`（**正是这件事**），但它只查 frontmatter 与六个必需小节在**不在** |
| 「`SKILL.md` **不能太长**；几百行、一个 skill 里三条以上不同流程，就别再往主文件补丁」 | **没有长度/流程数的判据**（现在 5 份是 52~68 行；上限设了下限就长不起来） |
| 「**两个版本**：机器执行版 `SKILL.md` + 人类理解版（为什么这么设计、失败过什么、脚本接口）」 | **完全没有**这一层；也没有"两版同步"的任何判据 |

★ 第三格是最要紧的：**规矩与来历只住在人的脑子里**。

## 要做的事

### 1. `skills/nails/check_skills.py` 加四条（**只加**，现有判据一条不许松）

1. **长度上限**：`SKILL.md` ≤ **120 行**（超出 ⇒ 红并点名 + 报实际行数）。
2. **流程数上限**：正文里"流程级"小节 ≤ **3**（口径你自己定，但**必须写进 docstring**：
   数哪种标题、怎么算一条——不许含糊）。
3. ★★ **「怎么读结果」那一节里的每条验收口径，必须指向一个真实存在的脚本路径**
   （`tools/**` 或 `skills/**/scripts/**`）。指不出来 ⇒ **红并点名是哪一条**。
   ★ 判据口径写清：允许的写法（如 `python -X utf8 tools/xxx.py --check`）与不许的写法（如"看输出对不对"）。
4. **人类理解版**：每个技能目录下必须有 `NOTES.md`，且含**三节**：
   「这一层在防哪类错误」/「失败过什么（带读数）」/「脚本接口与以后怎么改」。缺节 ⇒ 红并点名。

- ★ **四条都要能被证明看得见东西**：每条至少一条**反例**用例（见 §3）。

### 2. 给**现存 5 份** `SKILL.md` 补齐

- 每份加一个 `skills/<名>/NOTES.md`（三节齐）。
- ★ **第 3 条会当场咬出现有 5 份的欠账**（现在「怎么读结果」里基本没指向脚本）——
  按本仓纪律**不许静默豁免**：**要么补上脚本指针**，**要么**在 `skills/README.md` 里
  **如实登记为已知欠账并写明理由**。★ 两种你选一种，并在回报里写清选了哪种、为什么。
- ★ **不许把判据写进 skill**（本层铁律：删掉整个 `skills/` 框架仍完整可用）——
  你加的只能是「怎么用」与「该看哪个产物」。

### 3. 新 `tests/test_check_skills.py`（每条判据至少一条反例）

在 `tmp_path` 里造假的 `skills/`：超 120 行 ⇒ 红；四个流程小节 ⇒ 红；「怎么读结果」里那句
指不到脚本 ⇒ 红；缺 `NOTES.md` 或缺节 ⇒ 红；**全部合规 ⇒ 绿**。
★ **先红后绿**：先跑现在这份实现（应红/或该项尚无），改后绿 —— 把两次读数都贴出来。

## 硬约束

- ★ **改完必须 `python -X utf8 tools/wb_plan.py check` 退 0**；把**尾行**贴出来。
- ★ **必须跑 `ruff`**（门禁那条命令）。
- ★ 不许 commit / tag；不许跑全量门禁。
- ★ **不许放松任何既有判据**（`check_skills.py` 原有的 frontmatter/kebab/目录名一致/六个必需小节，一条不许松）；
  **不许改 `skills/pipe-*/SKILL.md` 以外的既有内容**（除了加 `NOTES.md` 与必要的脚本指针）。
- ★ 本层自检不变：**删掉整个 `skills/`，框架仍完整可用**。
- 白名单（只能改这些）：`skills/nails/check_skills.py` · `skills/README.md` ·
  `skills/pipe-init/NOTES.md` · `skills/pipe-gate/NOTES.md` · `skills/pipe-card/NOTES.md` ·
  `skills/pipe-land/NOTES.md` · `skills/pipe-forensics/NOTES.md` · 五个 `SKILL.md`（只为补脚本指针）·
  `tests/test_check_skills.py`

## 验收（照这个报）

1. `python -X utf8 tools/wb_plan.py check` 的**尾行**（退 0）；
2. `python -X utf8 skills/nails/check_skills.py` 在**改后**的完整输出（要绿；红的话逐条说明为什么）；
3. ★ 四条判据各自的**反例读数**（红）+ 合规读数（绿）；
4. 5 份 `NOTES.md` 的清单 + 各自三节标题；
5. ★ 第 2 节那个选择：**补指针**还是**登记欠账**，以及**为什么**；
6. `python -X utf8 -m pytest tests/test_check_skills.py -q --no-cov` 的**尾行**；
7. `ruff` 那一趟的尾行；
8. ★ **成送申请**：`wb_task.py claim` 那一条命令与它的回话。
