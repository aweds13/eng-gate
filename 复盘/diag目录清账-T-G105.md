# diag 目录清账：`inspect.py` 改名 + 两份过期草稿删除（T-G105 = 外包卡 018）

> 台账 `T-G105`（`group=PROCESS`）。卡规格 `gates/diag/卡018-diag目录清账.md`（在 gitignored 的 `gates/diag/` 下，不进 git）。
> 三个目标文件**全在 gitignored 的 `gates/diag/` 下** → 本卡在 git 里**唯一被跟踪的产物就是这份复盘**。

## §1 为什么有这张卡

料来自盘点卡 S-1 的 A15 + A22/D18：

- **A15 · `gates/diag/inspect.py` 遮蔽标准库 `inspect`**（出处 `gates/diag/wb-review-T-G79.md` §2 尾注 183–186）：
  任何**从 `gates/diag/` 目录起跑**的临时脚本会在 `import fastapi` 时炸
  `ImportError: cannot import name 'isasyncgen' from 'inspect'`。复核者第一版就是这么炸的，
  解法是 `python -X utf8 -P …`（3.11+，不把脚本目录塞进 `sys.path`）。
- **A22/D18 · 两份草稿已完成使命**：
  - `gates/diag/round-plan-T-G92-G93.md` 尾注自己写着「等两卡落地、收口完成后**删掉或折进
    `复盘/并发两卡-T-G92T-G93.md`**」——而那份复盘**已存在**；
  - `gates/diag/T-G93-ledger-draft.md` 标题即「等 B 落地后……再贴进 `docs/traceability.toml`」——
    B 已落地、`T-G93` 条目已进台账且已是 `done`。

## §2 主控裁定（卡 §2.9，逐条照做）

1. **`inspect.py` → 改名** `diag_inspect.py`（命名与同目录 `count_ui.py` / `dump_commands.py` /
   `baseline_gen.py` 一致）。比"删"安全，且**改名就消除遮蔽标准库这个根因**。
2. **两份草稿 → 删**（`round-plan-T-G92-G93.md`、`T-G93-ledger-draft.md`）——教训已折进
   `复盘/并发两卡-T-G92T-G93.md`，留着只会让人误当现状。
3. **只提交这份复盘**（三个目标文件不进 git）。

★ **删前先核"教训真覆盖了"**（卡 §7-4）：`复盘/并发两卡-T-G92T-G93.md:49` 确有
「这次没出事只因为收口是**按文件复制**（不是按分支合并）」那一条 —— 草稿里的这条教训确实已被承接，
删草稿不会丢信息。★ 同一条坑也已在 `复盘/外包-卡表与规矩.md` §16 与 `复盘/视觉线地图.md` §6 留着。

★ **改名先查引用**（卡 §7-3）：`grep -rn "inspect\.py"` 命中的**全是文档**（`docs/workbacklog.toml`
的任务定义、`复盘/*.md` 的史话与坑表），**没有任何脚本按名字 import / 执行它** → 改名不会断引用。
（这些命中文件也都不在本卡白名单，无需、也不许改动。）

## §3 改前 / 改后

| 文件 | 改前 | 改后 |
|---|---|---|
| `gates/diag/inspect.py` | 2618→614 字节临时脚本，文件名遮蔽标准库 | **改名为** `gates/diag/diag_inspect.py`（内容一字未动） |
| `gates/diag/round-plan-T-G92-G93.md` | 3903 字节收口计划草稿 | **删除** |
| `gates/diag/T-G93-ledger-draft.md` | 2618 字节台账条目草稿 | **删除** |

## §4 验证（先红后绿；临时探针用过即删，未留痕）

从 `gates/diag/` 起跑一次性探针 `_probe_shadow.py`（`import inspect` + `import fastapi`），
**改名前后各跑一次**：

**改名前（红）** —— `inspect` 被同目录 `inspect.py` 顶掉：

```
inspect.__file__ = D:/repo/engineering\.wt\diag\gates\diag\inspect.py
cwd-first sys.path[0] = D:/repo/engineering\.wt\diag\gates\diag
import fastapi 失败: ImportError cannot import name 'isasyncgen' from 'inspect'
  (consider renaming '…\gates\diag\inspect.py' since it has the same name as the standard
   library module named 'inspect' …)
```

**改名后（绿）** —— `inspect` 回到标准库、`fastapi` 可 import：

```
inspect.__file__ = C:/Users/example\miniconda3\Lib\inspect.py
cwd-first sys.path[0] = D:/repo/engineering\.wt\diag\gates\diag
import fastapi: OK
```

**改名后的脚本自身仍可跑、无需 `-P`**（卡 §2.9① 要求贴输出）：

```
$ python -X utf8 gates/diag/diag_inspect.py
line 2249, len 1134
'类 —— 用户原话：这是给人用的）；③ **清单搬进 `docs/user-guide.md`**（离线能做/不做、局域网怎么开、
 跨端包里不含什么、任务字段口径）。**尺子修过两次，都值得记**：第一版按「行首是不是注释'
exit=0
```

**目录对照**（清账前后）与 **git 看不见**（预期，不是失败）：

```
改前 gates/diag/：inspect.py  round-plan-T-G92-G93.md  T-G93-ledger-draft.md  wb-018.*  卡018-…md
改后 gates/diag/：diag_inspect.py                        wb-018.*  卡018-…md

$ git -c core.quotepath=false status --porcelain     # 空
$ git check-ignore -v gates/diag/diag_inspect.py
.gitignore:71:gates/diag/   gates/diag/diag_inspect.py
```

## §5 边界（如实写）

- ★ **三个目标文件都在 gitignored 的 `gates/diag/` 下（`.gitignore:71`），改动不进 git。**
  所以本卡**唯一的被跟踪产物是这份复盘** —— 别人 `clone` 下来的工作区里**仍然有**
  `gates/diag/inspect.py` 与那两份草稿（`git` 里从没有过它们，也就无从"删进 git"）。
  这是**预期**，不是没做完。
- **本卡不产生机器可验的断言**：纯清理（改文件名 / 删草稿），没有对应的轻门可跑。
  证据只有**人可复核**的动作与上表输出。
- 台账 `T-G105` 的 `evidence` **只钉这份复盘**（若写 `file:gates/diag/inspect.py`，一旦改名
  `audit_progress.py` 的 `file:` 求值当场红）。

## §6 没动的

白名单之外**一个字没碰**：`docs/**`、`tools/**`、`tests/**`、`scripts/**`、`src/**`、
其它 `复盘/*.md`（含 `复盘/并发两卡-T-G92T-G93.md`）、`gates/` 里除上述三个文件外的东西、
真实库 / 备份目录、三个外来未跟踪文件。`gates/diag/` 里 `wb-018.*` 那几个是我的派活状态文件，
不属于本卡产物、原样留着。

## 台账条目（供集成者粘贴）

```toml
[entries."T-G105"]
id = "T-G105"
title = "diag 目录清账：`inspect.py` 遮蔽标准库（改名 diag_inspect.py）+ 清掉两份已完成使命的草稿"
group = "PROCESS"
status = "done"
evidence = [
  "file:复盘/diag目录清账-T-G105.md",
]
gaps = "**为什么有这张卡**：A15（复核 `gates/diag/wb-review-T-G79.md` §2 尾注 183-186：文件名就叫 inspect.py，任何从该目录起跑的脚本 import fastapi 必炸 `cannot import name 'isasyncgen'`）+ A22/D18（两份草稿自身尾注自称已完成使命）。**做了什么**：① `inspect.py` 按主控裁定**改名** `diag_inspect.py`（内容一字未动，改名即消除遮蔽标准库这个根因）；② 两份草稿（`round-plan-T-G92-G93.md`、`T-G93-ledger-draft.md`）**删除**——删前核过 `复盘/并发两卡-T-G92T-G93.md` 已承接其教训（尤其「按文件复制、不是按分支合并」那条）。验证先红后绿：改名前后各跑一次同目录探针，`inspect.__file__` 从 `gates/diag/inspect.py` 变回标准库、`import fastapi` 从 ImportError 变 OK。改名先查引用：`grep inspect.py` 命中全是文档、无脚本按名引用。**边界（如实写）**：三个目标文件都在 gitignored 的 `gates/diag/` 下（`.gitignore:71`）→ 改动不进 git，本卡唯一被跟踪产物是本复盘；clone 后仍见旧状态，是预期。本卡不产生机器可验断言（纯清理），evidence 只钉复盘。**没动的**：`docs/**`、`tools/**`、`tests/**`、`scripts/**`、`src/**`、其它复盘（含 `复盘/并发两卡-T-G92T-G93.md`）、`gates/` 其它、真实库/备份、三个外来未跟踪文件。"
```
