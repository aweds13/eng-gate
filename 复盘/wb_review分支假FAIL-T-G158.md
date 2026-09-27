# 卡 064 · `wb_review` 在 detached worktree 里必然假 FAIL（T-G158）

> 工具卡。只动 `tools/wb_review.py` 的分支判据 + 一个新建的钉子测试 + 四份文档。
> 底座 `6d41e0e`（卡 062）· 树 `.wt/review1`（分离头指针，**没切过分支**）。

## 一、现场：复核器在说假话

`tools/wb_review.py` 的第 ④ 组判据里有一条**分支判据**（旧代码 `:139`、`:154`）：

```python
branch = git("rev-parse", "--abbrev-ref", "HEAD")     # 旧 :139
...
if branch != args.branch:                             # 旧 :154；args.branch 默认 "line/impl-v1"
    problems.append(f"分支不对：现在在 {branch!r}，期望 {args.branch!r}")
```

`git rev-parse --abbrev-ref HEAD` 在**分离头指针**（detached HEAD）下返回的**就是字面量** `HEAD`，
于是 `"HEAD" != "line/impl-v1"` **永远**为真。而外包链路的每张卡都在 `.wt/<卡>` 的 detached
worktree 里干活（卡规格明令"不许切分支"）—— 结果：**每一笔干净的提交都被判 4/5**。

卡 062 的回报边界 (b) 原文（`复盘/门禁三项加固-T-G156.md` 那一轮的回报）：

> `wb_review.py` 自检 **4/5 过**，唯一 FAIL 是「分支不对：现在 `HEAD`，期望 `line/impl-v1`」
> —— 本树是卡规定的 detached worktree（**不许切分支**），属口径差异。

★ 这不是"多一条噪音"：`wb_review.py` 是**防漏活的工具**。它说假话的次数一多，主控就会学会
忽略它（每张卡都手动加 `--branch HEAD` 绕过）—— **一条被人习惯性绕过的判据等于没有**。

## 二、改法：分支判据三态

新增纯函数 `check_branch(branch, expected) -> (problems, 如实信息行)`（改后 `tools/wb_review.py:101`）：

| 情况 | 行为 |
|---|---|
| ① 附着分支且 = `expected` | **不报**（保持原样） |
| ② 附着分支但 ≠ `expected` | **必须仍报**「分支不对」（★ 判据不许一起废掉） |
| ③ detached（`HEAD`）且 `expected` = 默认分支 | **跳过** + 记一行 `分离头指针（detached HEAD）→ 跳过分支判据（没有分支可比，不等于通过了分支检查）` |

`main()` 里：`branch_problems, branch_note = check_branch(branch, args.branch)`（`:194`）；
`branch_note` 同时进 `--json` 的 `branch_note` 字段（`:200`）与人类可读那行（`:210`）。
默认分支抽成模块常量 `DEFAULT_BRANCH`（`:49`，`--branch` 的默认值也改用它）。

★ **口径**：detached 时**没有分支可比**，所以跳过是对的 —— 但**不许**把它当成「通过了一个分支检查」
（那句 info 行就是防止这个误读的）。**没有**删除任何判据。

## 三、卡内一处口径张力，以及我的对齐（★ 请主控复核这一条）

卡 §2.1 第三行写「detached（`HEAD`）→ **不报**「分支不对」」（无条件）；
卡 §5 的反证 C 要求**在本树（detached）里** `--branch main` **仍报**「分支不对」
（原话："这是本卡的核心：**别把有用的判据一起废掉**"）。

两条要**同时**成立，只有一种读法：**跳过只针对"期望 = 默认分支"这个假阳性**
（也就是每张外包卡都撞到的那一下）；一旦显式要**别的**期望分支（`--branch main`），
那就是一条**真要求** —— detached 的树**确实不是** `main`，照报。
否则"detached 一律跳过"写成无条件的，这条判据在 detached 树里就**等于被删掉**，反证 C 永远失败。

`--branch HEAD` 在两种读法下都过（`"HEAD" == "HEAD"`），与卡 §7 第 3 条一致，不受影响。
★ 若主控的裁定是"无条件跳过"，改动只有一行（去掉 `and expected == DEFAULT_BRANCH`）——
我把这条张力单列出来，是因为它是本卡唯一一处"卡内两节互相矛盾"，不是我替卡做的取舍暗改。

## 四、验证：先红后绿 + 突变检验

- **先红**：新建的 `tests/test_wb_review_branch.py` 跑在**旧实现**上 → **6 条红**
  （`KeyError: 'branch_note'` / `AttributeError` 那一族），证明它真咬这个 bug，不是自证。
- **后绿**：改动后 `tests/test_wb_review_branch.py` **12 passed**（+ 同族 `tests/test_wb_review.py`
  4 passed，共 24 passed，`--no-cov -q`）。
- **突变检验（反空转）**：把 §2.1 的「附着但不匹配」也改成不报（`if branch != expected:` → `if False:`）
  → 立刻 **4 条红**（`test_attached_but_mismatched_branch_is_still_reported` /
  `test_cli_still_fails_on_an_attached_mismatched_branch` /
  `test_detached_with_an_explicit_other_branch_still_reports` /
  `test_the_stub_really_drives_the_verdict`）→ 还原后 **12 passed**。
- **替身自己也得看得见东西**：`test_the_stub_really_drives_the_verdict` 用同一个 git 替身喂两种分支，
  要求给出**相反**判决；`test_the_stub_rejects_unexpected_git_calls` 要求替身对没预料的 git 调用**报错**
  —— 防止"替身写错 → 上面几条一起变成没牙的绿"。
- 轻门：`ruff check tools/wb_review.py tests/test_wb_review_branch.py` → All checks passed；
  `mypy src/` → Success（没动 `src/**`，跑了是留个基线）。

## 五、三条反证（改前 / 改后 / 判据没废）

- **反证 A（改前假 FAIL 现场）**：在本树（detached，`HEAD=6d41e0e`）用**改动前**的
  `tools/wb_review.py` 跑 `--rev HEAD --allow "**"` → **exit 1**，那一条是
  `· 分支不对：现在在 'HEAD'，期望 'line/impl-v1'`（那一刻输出里还有一条"工作区脏"，
  是我临时把文件换回旧版造成的，与判据无关）。
- **反证 B（改后本树过）**：本卡这一笔提交之后，在本树（干净、detached）跑 `--rev HEAD --allow "**"`：

  ```
  === 复核 <HEAD>（父提交 6d41e0e，分支 HEAD）===
    ★ 分支判据：分离头指针（detached HEAD）→ 跳过分支判据（没有分支可比，不等于通过了分支检查）
    ① audit：审计通过 ✅
    ② trailer：T-G158
    ③ 门禁：ok=True rev=6d41e0e（这一笔的父提交 6d41e0e）+ 17 道门
    ④ 这一笔改了 8 个文件：docs/changelog.md、docs/traceability.toml、gates/last.json、
       gates/reuse.json、tests/test_wb_review_branch.py、tools/wb_review.py
    ⑤ 工作区未提交改动：0 个

  [OK ] 五条全过：这一笔算数（台账证据对得上、门禁是为它跑的、改动没越界）
  ```

  ★ 首行提交号写成 `<HEAD>`、**不钉 sha**：把反证读数写进同一条提交要再 `--amend` 一次，
  钉了 sha 就会漂（本仓 `外包-卡表与规矩.md` §22 ③ 是同一条规矩）——
  真正的凭据是**父提交 `6d41e0e`** 与门禁 `rev` 相等。
  **exit 0**；`--json` 里同样看得见 detached 那条如实信息：
  `branch= HEAD` / `branch_note= 分离头指针（detached HEAD）→ 跳过分支判据（…）` / `problems= []`。
- **反证 C（判据没废）**：同一棵树、同一笔提交，`--branch main` →

  ```
  [FAIL] 1 条不过 —— **这一笔不算数**：
    · 分支不对：现在在 'HEAD'，期望 'main'
  ```

  **exit 1** —— ★ 判据没被"detached 一律跳过"废掉。

★ **提交方式（如实写）**：B/C 的读数只有**提交之后**才拿得到（⑤ 要求工作区干净），而卡又要求
读数进台账与复盘 —— 所以先提交、拿到 B/C、再用 `git commit --amend` 把复盘并进**同一条**提交
（父提交始终是 `6d41e0e`，`wb_review` ③ 与 `audit` 都不受影响）；`--seal` 也跟着重跑了一次，
把 `gates/last.json` 的 `tree` 刷到最终状态。

## 六、没动什么

`--allow` 白名单逻辑 / 「五条」的其余四条 / `--read-only` / 退出码约定（有问题才非 0）/
`src/**` / `scripts/**` / 其余 `tools/**` / `gates/diag/**` / `.wt/**` / `data/` 与真实库备份。
**没切过分支**（本树全程 detached）。

## 七、台账条目（供集成者粘贴）

```toml
[entries."T-G158"]
id = "T-G158"
title = "修 wb_review 在 detached worktree 里的假 FAIL：分支判据改三态（detached 跳过并如实记录）"
group = "PROCESS"
status = "done"
evidence = [
  "file:tests/test_wb_review_branch.py",
  "text:tools/wb_review.py::detached",
]
gaps = "**根因**：旧 `tools/wb_review.py:139` 用 `git rev-parse --abbrev-ref HEAD` 取分支，分离头指针下返回字面量 `HEAD`，旧 `:154` 的 `if branch != args.branch`（默认 `line/impl-v1`）**必然**成立 → 每张在 detached worktree 里干活的卡都被判 4/5。**062 原话**（`复盘/门禁三项加固-T-G156.md` 那一轮回报边界 b）：「wb_review.py 自检 4/5 过，唯一 FAIL 是「分支不对：现在 `HEAD`，期望 `line/impl-v1`」—— 本树是卡规定的 detached worktree（不许切分支），属口径差异」。**改法**：新增纯函数 `check_branch`（改后 `tools/wb_review.py:101`）分三态 —— 附着且匹配不报 / 附着但不匹配**仍报** / detached（`HEAD`）且期望是默认分支则跳过并记一行「分离头指针（detached HEAD）→ 跳过分支判据」；默认分支抽成 `DEFAULT_BRANCH`（`:49`），信息行进 `--json` 的 `branch_note` 字段（`:200`）与人类可读行（`:210`）。**卡内一处口径张力（如实写，请主控裁定）**：卡 §2.1 第三行要求 detached 无条件不报，卡 §5 反证 C 要求本树（detached）里 `--branch main` **仍报**；我的对齐 = **跳过只对默认期望分支生效**，否则该判据在 detached 树里等于被删掉、反证 C 永远失败（无条件跳过的改法只是去掉 `and expected == DEFAULT_BRANCH` 一行）。**读数**：先红 —— 新测试跑旧实现 6 条红；后绿 —— `tests/test_wb_review_branch.py` 12 passed（含同族 `tests/test_wb_review.py` 共 24 passed）；突变检验 —— 把「附着但不匹配」也改成不报 → 4 条红、还原后 12 绿；反证 A —— 本树 detached 上改前 `--rev HEAD --allow **` → exit 1 且含「分支不对：现在在 HEAD」；反证 B —— 提交后同命令五条全过（exit 0）；反证 C —— 提交后 `--branch main` → exit 1 仍报「分支不对」。**没动**：`--allow` 白名单逻辑、「五条」其余四条、`--read-only`、退出码约定、`src/**`、`scripts/**`、其余 `tools/**`、`gates/diag/**`、`.wt/**`、`data/` 与真实库备份；**没切过分支**。"
```
