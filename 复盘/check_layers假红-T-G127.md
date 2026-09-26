# 卡 036 · `check_layers.py` 对 gitignored 产物的假红（T-G127）

## 1. 为什么有这张卡

卡 033 在自己的 worktree 里跑 `python -X utf8 scripts/check_layers.py` → **FAIL**，
断点是 `docs/changelog.md` 反引号引用的 `gates/diag/wb-review-T-G79.md`：

- `gates/diag/` 整个目录 gitignored（`.gitignore:71`），那份文件**只在主树存在**；
- 主树同一条命令 **PASS**。

本轮实测复现（§3），与卡 033 现场一致。结论：不是 033 的错，也不是 `docs/changelog.md` 的错
（那条引用合法），是判据没区分「承诺给读者的文档」与「gitignored 过程产物」。

## 2. 判据选择：A（问 git），不是硬编码

**选 A**：对解析出的引用路径逐个候选基准问 `git check-ignore -q -- <相对路径>`，
**任一候选被忽略** → 跳过存在性检查、只打一行 `[skip]` 说明。

- 为什么不是 B（只对同层级判存在性）：B 会放过「docs 引用同层级之外的真实断链」，放松了真判据。
- 为什么不许硬编码 `gates/diag/`：目录将来改名就静默失效；问 git 则跟着 `.gitignore` 走。
- **从严取向**：`git check-ignore` 出错（退出码非 0/1，如不在仓库内）按「未忽略」处理 ——
  宁可多报一条断链，也不悄悄放过真断链（`is_git_ignored()` 的 docstring 写明）。

核心改动一行（`scripts/check_layers.py:133`）：

```python
if any(is_git_ignored(c) for c in candidates):
    notes.append(f"跳过 gitignored 产物引用: {md.relative_to(ROOT)} → {rel}")
    continue
```

`check_link_integrity()` 改为返回 `(problems, notes)`，`main()` 把 notes 打成 `[skip]` 行
（只记录说明，不影响判定）。

## 3. 真机证据（先红后绿）

**改前 · 主树 PASS**（`cd 主树 && python -X utf8 scripts/check_layers.py`，exit=0）：

```
LAYER CHECKS: PASS ✅
```

**改前 · 本树（worktree）FAIL**（exit=1）：

```
[FAIL] 引用断裂: docs\changelog.md 引用了不存在的 gates/diag/wb-review-T-G79.md
[FAIL] 引用断裂: docs\changelog.md 引用了不存在的 gates/diag/wb-review-T-G79.md
LAYER CHECKS: FAIL ❌
```

**改后 · 本树 PASS**（exit=0）：

```
[skip] 跳过 gitignored 产物引用: docs\changelog.md → gates/diag/wb-review-T-G79.md
[skip] 跳过 gitignored 产物引用: docs\changelog.md → gates/diag/wb-review-T-G79.md
LAYER CHECKS: PASS ✅
```

（两行 skip = `docs/changelog.md` 里那两处合法引用，原样保留、一个字没动。）

## 4. 自检（新增用例 + 全量）

`python -X utf8 scripts/test_check_layers.py`（exit=0）：

```
[正样例] 干净仓库 → exit=0
[负样例1] 约定层缺 N 标注 → exit=1
[负样例2] 断链引用 → exit=1
[负样例3] 契约层引用未知 SR → exit=1
[负样例4] 覆盖矩阵缺 SR-F10 → exit=1
[正样例2] gitignored 产物引用被跳过 → exit=0
[负样例5] 受管文件断链仍咬 → exit=1
SELF-TEST PASS ✅ （2 正样例 + 5 负样例 + 1 豁免用例）
```

新增两例（原 1 正 + 4 负 + 1 豁免**一条没动**）：

- **正样例2**（新规则的豁免面）：往 `docs/README.md` 注入引用
  `gates/diag/绝不存在的产物-别创建-T-G127.md`（不存在但被 git 忽略）→ 应跳过、exit=0；
- **负样例5**（新规则的咬合面）：注入引用 `docs/绝不存在的受管文件-T-G127.md`
  （不存在、**不受忽略**）→ 必须仍报「引用断裂」、exit=1。

`python -X utf8 -m ruff check scripts/check_layers.py scripts/test_check_layers.py` → `All checks passed!`

## 5. 突变检验（护栏真有牙）

把豁免规则**改坏**：`is_git_ignored()` 一律 `return True`（等于连受管文件的断链也豁免）→

```
[负样例2] 断链引用 → exit=0        ← 原本 exit=1
[负样例5] 受管文件断链仍咬 → exit=0  ← 原本 exit=1
SELF-TEST FAIL ❌
  - 应抓出断链引用，实际: [skip] 跳过 gitignored 产物引用: …
  - 受管文件断链应仍被抓，实际: [skip] 跳过 gitignored 产物引用: …
```

还原后复跑：`SELF-TEST PASS ✅ （2 正样例 + 5 负样例 + 1 豁免用例）` + `LAYER CHECKS: PASS ✅`。

## 6. 边界（如实写）

- **跳过时打印什么**：`[skip] 跳过 gitignored 产物引用: <文档> → <路径>`，一行一条，不进判定。
- **可能漏掉的真问题**：一个**真实存在但被 gitignore 的文件**若被引用，本来就该让人知道
  「读者拿不到它」—— 本判据对此**静默放过**（exit 0）。这是刻意的取舍：check_layers 管的是
  「断链」，不管「产物该不该被引用」；若要管，得另立口径（如要求产物引用旁标注生成方式）。
- **多基准语义**：候选基准是「当前文档目录 / docs 根 / 仓库根」三种写法，任一候选被忽略即跳过
  —— 若某引用在所有基准下都既不存在又不受忽略，仍 FAIL（负样例5 钉着）。
- **`git check-ignore` 不可用时**（如 git 缺失、退出码 128）：按「未忽略」从严处理，不豁免。
- **没动的**：`docs/**`（`docs/changelog.md` 那两处引用合法、原样保留）、`gates/**`、`tools/**`、
  `src/**`、`tests/**`、共享文件、三个外来未跟踪文件；已知豁免（`DESIGN.md`/`LEARN.md` 待建）
  与原 4 条负样例的判据一个字没改。

## 台账条目（供集成者粘贴）

```toml
[entries."T-G127"]
id = "T-G127"
title = "`check_layers.py` 不再对 **gitignored 产物**的引用报假红（worktree 里跑必然假红 → 卡住工人）；该咬的仍咬"
group = "PROCESS"
status = "done"
evidence = [
  "file:复盘/check_layers假红-T-G127.md",
  "text:scripts/check_layers.py::if any(is_git_ignored(c) for c in candidates):",
  "test:test_check_layers.py",
]
gaps = '**为什么有这张卡**：卡 033 在自己的 worktree 里跑 `check_layers.py` 被假红卡住、拒绝提交 —— 断点是 `docs/changelog.md` 引用的 `gates/diag/wb-review-T-G79.md`（`gates/diag/` 整目录 gitignored、只存在于主树）。两次原始输出：主树 `LAYER CHECKS: PASS ✅`（exit=0）；worktree `[FAIL] 引用断裂: docs\changelog.md 引用了不存在的 gates/diag/wb-review-T-G79.md`（exit=1，出现两处）。**做了什么**：选 **A（问 git）** —— 对引用的每个候选基准路径跑 `git check-ignore -q -- <相对路径>`（命令见复盘 §2），任一候选被忽略 → 跳过存在性检查、只打一行 `[skip]` 说明；**不硬编码目录名**（`gates/diag/` 将来改名也不失效）；`check-ignore` 出错按「未忽略」从严处理（宁可多报断链、不悄悄放过）。候选 B（只对同层级判存在性）会放过跨层级的真断链，弃。**真机证据（先红后绿）**：改前 worktree FAIL（上面原文）→ 改后同树同命令 PASS，输出两行 `[skip] 跳过 gitignored 产物引用: docs\changelog.md → gates/diag/wb-review-T-G79.md` + `LAYER CHECKS: PASS ✅`（exit=0）。**反证（不许放松）**：自检新增两条 —— 正样例2（引用 gitignored 的不存在产物 → 跳过、exit=0）、负样例5（引用不存在的受管文件 → 仍 `[FAIL] 引用断裂`、exit=1）；原 1 正 + 4 负 + 1 豁免一条没动。**突变检验**：把 `is_git_ignored` 改成恒真（连受管断链也豁免）→ 负样例2/5 双双变 exit=0、`SELF-TEST FAIL ❌`（原文见复盘 §5）；还原 → `SELF-TEST PASS ✅ （2 正样例 + 5 负样例 + 1 豁免用例）`。ruff 两文件 `All checks passed!`。**边界（如实写）**：被跳过的引用只打 `[skip]` 行、不进判定；一个**真实存在但被 gitignore 的文件**被引用时本判据**静默放过**（它管断链、不管「产物该不该被引用」，要管需另立口径）；引用在所有基准下既不存在又不受忽略 → 仍 FAIL（负样例5 钉着）。**没动的**：`docs/**`（changelog 那两处引用合法、原样保留）、`gates/**`、`tools/**`、`src/**`、`tests/**`、共享文件、三个外来未跟踪文件。'
```
