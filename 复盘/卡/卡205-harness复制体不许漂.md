# 卡 205 —— **`harness/` 复制体不许悄悄漂**（T-G313）

**树**：`.wt/harnesssy` ｜ **base**：主控派活时的主树 HEAD ｜ **提交**：★ 不要 commit
**成员号**：任务 `B-HARNESSSY` 的 **M-1**（干完要交成成送申请，见最后）

## 为什么有这张卡

`harness/` 是 `tools/` 工作台脚本的**复制体**（缝层：项目专有值抽到仓根 `harness.toml`，见 `harness/README.md`）。
它的不变量写在 README 里：**冻结输入下原件/复制体输出逐字节相同**。主控 2026-10-13 实测**两条都破了**：

1. ★ **复制体漂了**：卡 203 把 `tools/wb_plan.py` 的派活命令改成对的形态（加 `--cwd`、不再 `pushd`），
   而 `harness/wb_plan.py:422` **仍是老的** `return f"pushd {card.tree}; {base}" if card.tree else base`
   ⇒ **框架那条路（别的项目按框架跑）拿到的仍是错形态**。
2. ★★ **没有任何判据盯着这件事**：`tests/test_harness_manifest.py` 只测 `harness.toml` 的加载
   （缺文件 / 坏 TOML / 缺段 / 缺键 / 拼错 / 空值…），**从不比较复制体与原件**。
   ⇒ 这条不变量破了一路绿灯，没人知道。
3. ★ README 还写着「复制体**不依赖 `tools/`**：不挂 `sys.path`、不 `from tools...`」—— 主控实测
   **对 `wb_plan.py` 不成立**：单独跑它报 `ModuleNotFoundError: No module named 'pool'`（它要 `tools/pool/plan.py`）。

## 要做的事

### 1. 把 `harness/wb_plan.py` 同步成与原件**同一形态**

- 拿卡 203 之后的主树 HEAD 上的 `tools/wb_plan.py` 做基准，把 `dispatch_argv()` / `render_dispatch()`
  改成同一形态：**加 `--cwd <该卡树绝对路径>`、不再 `pushd`**。
- ★ **项目专有值仍走 `harness.toml`**（`paths.workbench`），不许在复制体里写死 `tools/` —— 那是缝层的规矩。
- ★ **只同步这一件事**：其余差异（docstring 里 `tools/` ↔ `harness/` 的措辞、`--help` 文本）**原样保留**，
  别顺手"抄一份新的"（复制体是**登记外的新东西**，不是 rsync 的产物）。

### 2. 给这条不变量装牙（`tests/test_harness_manifest.py`）

新增判据，**至少**钉住：

- 冻结输入下，**复制体与原件对同一张卡渲染出的派活命令一致**（含 `--cwd`、不含 `pushd`）；
  ★ 允许的差异只有**程序名/路径前缀**那种（`tools/` ↔ `harness/`）—— 判据里要**写清允许哪些差异**，
  不许用「大致相等」这种模糊比较。
- 复制体的输出里**不许出现 `pushd`**；卡树必须带 `--cwd`、主树必须不带（与原件同一条反例）。
- ★ **反证要求（先红后绿）**：把复制体改回老的 `pushd` 形态 ⇒ 这条判据必须**红**（贴出红的那次读数）。

### 3. 把 README 那句说清（`harness/README.md`）

- 「复制体不依赖 `tools/`」这句**与实测不符**（`wb_plan.py` 要 `tools/pool/`）。**二选一**并写明你选了哪个：
  ① 让复制的 `wb_plan.py` **真的自包含**（把 `pool/plan.py` 的那部分也复制进来）；或
  ② **如实改文**：写清哪些复制体依赖 `tools/` 的哪一部分、跑的时候需要什么。
- ★ 不许两种都不做（那就是把不实当已知）。

## 硬约束

- ★ **改完必须 `python -X utf8 tools/wb_plan.py check` 退 0**；把**尾行**贴出来。
- ★ **必须跑 `ruff`**（门禁那条：`python -X utf8 -m ruff check src/ tests/ scripts/ tools/ examples/ harness/`）——
  ★ 注意 `harness/` **在**这条命令的扫描范围内。
- ★ 不许 commit / tag；不许跑全量门禁。
- ★ **不许放松任何既有判据**；不许改 `tools/`（原件不动 —— 复制体的差异靠这份判据说话）。
- ★ 起子进程要带 `NO_WINDOW`。
- 白名单（只能改这些）：`harness/wb_plan.py` · `harness/README.md` · `tests/test_harness_manifest.py`

## 验收（照这个报）

1. `python -X utf8 tools/wb_plan.py check` 的**尾行**（必须退 0）；
2. 复制体与原件**同输入的真实输出**（并排贴出来，看得到 `--cwd`、看不到 `pushd`）；
3. ★ 新判据**先红后绿**的两次读数（红那一次 = 把复制体改回 `pushd`）；
4. `python -X utf8 -m pytest tests/test_harness_manifest.py -q --no-cov` 的**尾行**；
5. `ruff` 那一趟的尾行（含 `harness/`）；
6. README 那句你怎么处置（① 还是 ②），以及改前/改后**原文**。
