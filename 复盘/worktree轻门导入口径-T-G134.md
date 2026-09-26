# worktree 轻门「测的是哪棵树」—— 修导入口径 + 自身钉子（T-G134）· 卡 043

## 为什么有这张卡

只读复核卡 R022 复核 T-G110 时实测：在 worktree 里照字面轻门命令（`PYTHONPATH=$PWD/tools/sandbox_shim` + `pytest tests/test_myday_*.py`）跑 → **5 failed**（全是新用例）；补上本树 `src` 后 → **30 passed**。根因：miniconda 的 editable 安装 `__editable__.timeflow-0.1.0.pth`（2026-09-17 装）硬指主树 `engineering\src`，worktree 里 `import timeflow` 拿到的是主树旧代码 —— 既造假红也造假绿。

## 本树复现（改前，原样输出）

```
$ cd <本树> && PYTHONPATH="$PWD/tools/sandbox_shim" python -X utf8 -c "import timeflow, pathlib; print(pathlib.Path(timeflow.__file__).resolve())"
D:/repo/engineering\src\timeflow\__init__.py
```

指向主树、不在本树（本树根是 `…\engineering\.wt\imports`）→ 复现成功。

## 做了什么

- `tests/conftest.py`（**只加不改**）：pytest session 一开始把**本树** `src` 前置到 `sys.path` 最前。本树根从 `__file__`（`<树根>/tests/conftest.py`）往上推 `parents[1]`，**不写死任何绝对路径**；`is_dir()` 兜底。核心一行：`sys.path.insert(0, str(_TREE_SRC))`。
  - 顺带核过：`tools/sandbox_shim/` 只是 `sitecustomize.py`（启动期 os.mkdir 钩子），与本卡前置 `src` 无模块名冲突。
- `tests/test_src_import_line.py`（**新建钉子**）：两条判据全部**相对**本树根（由钉子文件 `__file__` 推出，Windows 下再过 `normcase`）：
  1. `import timeflow` 拿到的文件必须在本树之下；
  2. 本树 `src` 在 `sys.path` 里的位置必须先于**任何**树外条目（`.pth` 注入的主树 src、site-packages 都算外部）。

## 先红后绿三贴

| 贴 | 命令 | 读数 |
|---|---|---|
| ① 改前红 | `PYTHONPATH="$PWD/tools/sandbox_shim" python -X utf8 -m pytest tests/test_src_import_line.py --no-cov` | **2 failed**，失败信息原样可见「导入的是主树」：`import timeflow 拿到的不是本树的代码：D:/repo/engineering\src\timeflow\__init__.py`；第二条「本树 src 不在 sys.path 里」 |
| ② 改后绿 | 同上 | **2 passed**（0.06s） |
| ② 既有测试 | `PYTHONPATH="$PWD/src;$PWD/tools/sandbox_shim" python -X utf8 -m pytest tests/ --no-cov` | **1430 passed / 1 failed / 2 deselected**（5:36）；唯一 failed 见下节「既有红」 |
| ③ 改坏再红 | 把注入点 `parents[1]` 临时改成 `parents[2]`（`.wt/src` 不存在 → 不注入） | **2 failed** → 还原后 `git status` 只剩白名单两文件（`M tests/conftest.py`、`?? tests/test_src_import_line.py`），再跑同命令 **2 passed** |

ruff：`python -X utf8 -m ruff check tests/conftest.py tests/test_src_import_line.py` → **All checks passed!**

## 主树没倒退（对照读数）

主树根跑同一命令：`PYTHONPATH="$PWD/tools/sandbox_shim" python -X utf8 -c "import timeflow, …"` →
`D:/repo/engineering\src\timeflow\__init__.py` —— 仍是主树自己的 src，语义不变。
（主树里若将来带入这段 conftest 改动，前置的「本树 src」就是它自己，等于把 `.pth` 已做的事提前，无行为差异。）

## 既有红（与卡无关，如实记）

`tests/test_wb_review.py::test_current_head_passes_the_gate_evidence_check` 在**干净底座上也是红的**（stash 我的改动后单跑该用例 → 1 failed → pop 还原）：HEAD（`83b020c`）里提交的 `gates/last.json` 记 `rev=803be3a`，而 HEAD 的父提交是 `277cf49` —— 底座那一笔（T-G114）提交时没有重跑全量门禁更新 `gates/last.json`。该用例只读 git 提交数据（`git show HEAD:gates/last.json`），与工作区改动无关 → **非本卡倒退**，留给主控在集成跑全量门禁时自然修复（跑完 `gates/last.json` 会重新落盘）。

## 边界（如实写）

- **裸 `python -c "import timeflow"` 仍指主树**：注入点在 `tests/conftest.py`，只对 pytest 生效 —— 卡 §2.2 裁定的口径就是「让**在本树里跑 pytest** 时导入本树的 src」，本卡没超出这个范围。若要连普通解释器也修，得动 `.pth`/环境（禁区）。
- `test:` 证据指针这次合法：`test_src_import_line.py` 就在 `tests/` 下。
- 全量 pytest 在本树跑过两次（-x 与不带 -x），**不是**全量门禁（没跑 `run_gates.py`，遵守 §0.3）。
- 残余风险：若某卡在 pytest 里**故意**用 `PYTHONPATH` 指向另一份 timeflow 想测「装出去的包」，本前置会赢过它 —— 目前仓库没有这种用法（sandbox_shim 只是 sitecustomize），真出现时那张卡应显式改 `sys.path` 并说明。

## 没动的

`src/**`、`tools/**`、`scripts/**`、`docs/**`、`gates/**`、卡 042 占着的 `复盘/外包-卡表与规矩.md`、其它 `tests/**` 文件、交接文档、主树那三个外来未跟踪文件（`DSH-*.md` ×2、`dsh-skill-docs-report.zh.md`）—— 全部一字未碰。

## 台账条目（供集成者粘贴）

```toml
[entries."T-G134"]
id = "T-G134"
title = "修 worktree 轻门的导入口径：editable .pth 硬指主树 src 导致「测的是旧代码」（能造假红也能造假绿）—— 前置本树 src + 自证钉子"
group = "TEST"
status = "done"
evidence = [
  "file:复盘/worktree轻门导入口径-T-G134.md",
  "text:tests/conftest.py::sys.path.insert(0, str(_TREE_SRC))",
  "test:test_src_import_line.py",
]
gaps = "**为什么有这张卡**：R022 实测字面轻门命令 5 failed / 补本树 src 后 30 passed；editable `__editable__.timeflow-0.1.0.pth`（2026-09-17 装）硬指主树 `engineering\\src`。**做了什么**：`tests/conftest.py` 只加一段 —— pytest session 起手把本树 `src`（由 conftest 的 `__file__` 往上 `parents[1]` 推出，不写死绝对路径）前置到 `sys.path` 最前；新建钉子 `tests/test_src_import_line.py` 两条相对判据（import timeflow 在本树之下 + 本树 src 先于一切树外 sys.path 条目）。**先红后绿三贴**：① 改前 2 failed（读数原样可见导入主树 `…\\engineering\\src\\timeflow\\__init__.py`）② 改后 2 passed，既有测试 1430 passed / 1 failed（唯一 failed 是底座自带的 `test_wb_review.py::test_current_head_passes_the_gate_evidence_check`，stash 验证干净底座同样红，非本卡倒退）③ 改坏 `parents[1]→parents[2]` 再红 → 还原后 git status 只剩白名单两文件、再跑 2 passed。**主树没倒退**：主树根同一命令仍指主树自己的 src。**边界（如实写）**：裸 `python -c` 导入仍指主树（注入只对 pytest 生效，卡 §2.2 裁定口径即如此）；`test:` 指针合法因文件在 `tests/` 下；若将来有测试故意经 PYTHONPATH 换包，前置会赢过它（现无此用法）。**没动的**：src/tools/scripts/docs/gates、卡 042 占着的卡表、其它 tests、交接文档、主树三个外来未跟踪文件。"
```
