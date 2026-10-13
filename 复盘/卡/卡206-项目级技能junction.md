# 卡 206 —— **项目级技能 junction**：一进这个项目，技能就在（T-G314）

**树**：`.wt/dshtie` ｜ **base**：主控派活时的主树 HEAD ｜ **提交**：★ 不要 commit
**成员号**：任务 `B-DSHTIE` 的 **M-1**（干完要交成成送申请，见最后）

## 为什么有这张卡

用户 2026-10-13 的令：*「我大概都是在你 DSH 这里工作，所以尽量**不要让我切来切去**」*。
主控查了 DSH 的技能扫描根（`DSH-技能与插件开发参考.md` §3.2）：

| rank | 路径 | 来源 |
|---|---|---|
| **100** | **`<项目>/.dsh/skills`** | `project-dsh` ← ★ 本卡要用的那个 |
| 200 | `<项目>/.agents/skills` | `project-agents` |
| 300 | `customSkillDirs` | `custom` |
| 400 | `~/.dsh/skills` | `user-dsh` |
| 500 | `~/.agents/skills` | `user-agents` |

★ **rank 100 = 项目级**：放在那儿，**一进这个项目技能就在**，不用记、不用切、不用 `/点名`。
而本仓现在**没有 `.dsh/`**（`~/.dsh/skills` 里那 9 个全是通用的数学/笔记/UI 技能，**管线的一个都没有**）。

本仓的 `skills/`（`pipe-init` / `pipe-gate` / `pipe-card` / `pipe-land` / `pipe-forensics`）是**框架的人机接口**，
`skills/nails/check_skills.py` 已经在钉它们的 frontmatter 与必需小节 —— 而 DSH 认的 SKILL.md 格式**几乎一致**
（`name` kebab-case + 与目录名一致 + `description`）。⇒ 这一层可以**一份真源，两个 harness 都读**。

## 要做的事

### 1. 新 `tools/dsh_skills_link.py`

- **把 `skills/` 下那几个技能目录，各做一个 `<项目>/.dsh/skills/<技能名>` 的 junction**（Windows 目录联接），
  指向 `../../skills/<技能名>` —— **零副本、单向**（真源仍在 `skills/`，入库、被钉子扫）。
- `--check`：逐个断言 **junction 存在且指向正确**（指错方向 / 指到不存在 ⇒ 非零并**点名哪一个**）。
- `--list`：打印「技能名 → 目标」，人读。
- ★ **幂等**：跑两次结果一样；已存在且指向正确 ⇒ 不重复建（打印一句跳过）；已存在但**指向错** ⇒ **报错并停下**，
  不许静默重建（那会把"有人手工改过"这件事抹掉）。
- ★ **只挂技能目录**：`skills/` 下还有 `README.md`、`GLUE-harness.md`、`nails/` ——
  **一个都不许挂**。理由（实测口径）：DSH 的技能扫描**还认平铺形态** `<root>/<名>.md`，
  把整个 `skills/` 挂进去，`README.md` 与 `GLUE-harness.md` 会被当成两个没有 frontmatter 的**坏技能**。
- ★ 起子进程要带 `NO_WINDOW`。

### 2. `.dsh/` 进 `.gitignore`

- junction 是**本机派生物**，不进版本管理（.gitignore 里加 `.dsh/`）。
- ★ 判据要能证明这一点（见下）；**不许**把 `.dsh/skills/...` 意外提交上去。

### 3. 新 `tests/test_dsh_skills_link.py`（≥4 条）

- 在 **tmp_path** 里搭一个假 `skills/`（几个技能目录 + `README.md` + `GLUE-harness.md` + `nails/`）
  ⇒ 跑一次 ⇒ **只有那几个技能目录**被挂上；`README.md` / `GLUE-harness.md` / `nails` **一个都没挂**；
- 幂等：跑两次 ⇒ 第二次全部"跳过"、结果不变；
- `--check` 对**指错**的 junction ⇒ 非零并点名；
- ★ **反例**：把 `nails/` 也挂上 ⇒ `--check` 必须**红**（证明这条判据真看得见东西）。

### 4. ★ 如实报：junction 能不能被 DSH 的 watcher 读

**主控没验过**：DSH 的 `dsh-skill-filesystem` 扫的是「根目录下的目录束 / 平铺 `.md`」——
**junction 算不算目录、watcher 跟不跟随，未实测**。
- 你**真建一个**（在你自己的树里跑一遍 `tools/dsh_skills_link.py`），把**实际目录列表**贴出来；
- 如果 DSH 那边读不到（你没法直接验 DSH，那就**如实写"不知道"**）——
  ★ **不许**把"我建成了 junction"说成"DSH 一定能读到"。这一条是本卡最要紧的边界。
- 如果发现在你这台机器上 junction 建不起来（权限 / 文件系统）⇒ **如实报**并说明你退回了什么方案（如有），
  **不许**改成"复制一份"就悄悄了事（那会变成第二份真源，与缝层口头规矩冲突）。

## 硬约束

- ★ **改完必须 `python -X utf8 tools/wb_plan.py check` 退 0**；把**尾行**贴出来。
- ★ **必须跑 `ruff`**（门禁那条命令）。
- ★ 不许 commit / tag；不许跑全量门禁。
- ★ **不许放松任何既有判据**；**不许改 `skills/**`**（真源一个字都不许动 —— 那是钉子① ② 的地盘）。
- 白名单（只能改这些）：`tools/dsh_skills_link.py` · `.gitignore` · `tests/test_dsh_skills_link.py`

## 验收（照这个报）

1. `python -X utf8 tools/wb_plan.py check` 的**尾行**（必须退 0）；
2. `tools/dsh_skills_link.py --list` 的**真实输出**（你树里建完之后的）；
3. ★ **哪些被挂了 / 哪些没挂**的目录列表（要能看出 `README.md` / `GLUE-harness.md` / `nails` 没被挂）；
4. 新测试的 **≥4 条**真跑 + ★ 那条反例（把 `nails` 挂上 ⇒ 红）的读数；
5. `python -X utf8 -m pytest tests/test_dsh_skills_link.py -q --no-cov` 的**尾行**；
6. `ruff` 那一趟的尾行；
7. ★ **第 4 节那段边界**：照你实际看到的写（读到 / 读不到 / 不知道），**别猜**。
