# `.wt` 工作树清理器 —— 证据（卡 081 · `T-G176`）

> 交付物：`tools/wt_prune.py`（**新建**，默认 dry-run）+ `tests/test_wt_prune.py`（**新建**，11 用例）。
> ★ **真树一棵都没删**（下面 §二 有跑前/跑后计数）—— 删除由主控看完表再决定。

## 一、七条判据：各自的原文命令 + 判法（贴代码行号）

判据全部落在 `tools/wt_prune.py:judge()`（`tools/wt_prune.py:339`），按 1→7 取**首条不成立**的当保留理由；
**七条全过才 `可删`**；任何一条"判不了"（psutil 缺 / backlog 读坏 / git status 读不到）→ **保留**。

| # | 判据 | 原文命令 / 判法 | 代码 |
|---|------|----------------|------|
| 1 | 在 `<仓库根>/.wt/` 下，且不是主树、不是当前工作树 | `git worktree list --porcelain` 取全部树；`git rev-parse --show-toplevel` 取当前树（从 cwd 起算）。路径不在 `<root>/.wt/` 或 == 主树/当前树 → 保留 | `:154 list_worktrees` · `:350 判据1` |
| 2 | 它的 tip **已集成** | **在主树里** `git merge-base --is-ancestor <tip> HEAD`，退 0 = 活已进主树 | `:355 事实一` · `:390` |
| 3 | **没有未提交的已跟踪改动** | `git -C <树> status --porcelain --untracked-files=all`：**不以 `??` 开头**的行数 = 未提交跟踪改动；`??` 行数 = 未跟踪文件（**不算阻塞**，只计数） | `:323 _status_counts` · `:392` |
| 4 | 没有别的进程在这棵树里 | **铁律 28 树侧判据**：进程的 **cwd == 树根（或在其下）**。一次 `psutil` 扫全机进程的 cwd；**绝不按进程名判**（铁律 27/28）。psutil 拿不到 → 保留 | `:215 occupancy` · `:394/:396` |
| 5 | 没有门禁锁被它持有 | 读 `<root>/gates/diag/gates*.lock`（`gates.lock` / `gates-<BASE>.lock`）的 **`cwd` 字段**；持有者 cwd 在这棵树里 → 保留 | `:230 lock_holders` · `:398/:400` |
| 6 | 没有 `locked` 标记 | `git worktree list --porcelain` 里的 `locked` 行 | `:144 list_worktrees` · `:402` |
| 7 | 不是"未完工的卡"占的树 | **现读** `docs/workbacklog.toml`（与 `tools/wb_plan.py` 的 `load_backlog` 同一口径）→ `status != done` 的卡的 `tree` 一律保留。**不硬编码卡号**；backlog **存在但读坏** → 判不了 → 全保留；**文件不存在** → 没有卡占树 | `:272 backlog_pending_trees` · `:405/:407` |

`--apply` 的第二拍：`do_apply()`（`:511`）对每棵候选**先用 `recheck_apply()`（`:499`）从零再判一遍七条**，
再跑**不带 `--force`** 的 `git worktree remove`（`:526`）；失败即保留并打印原因（退出码 1）。
★ 另有 `--json`（`:main` 里 `ensure_ascii=False` 的 json）/ `--min-size <MB>` / `--root <仓库根>`。

## 二、真树 dry-run 现跑读数（`python -X utf8 tools/wt_prune.py`）

```
$ git worktree list --porcelain | grep -c '^worktree '     # 跑前
86
$ python -X utf8 tools/wt_prune.py ; echo EXIT=$?
=== .wt 工作树清理器 · DRY-RUN（只看不删） · 仓库根 D:/repo/engineering ===
（判据：①在 .wt 下非主树非当前树 ②tip 已集成 ③无未提交跟踪改动 ④无进程占用 ⑤无门禁锁 ⑥无 locked ⑦非未完工卡）
树名 | tip | 已集成 | 跟踪改动 | 未跟踪 | 进程占用 | 锁 | 大小MB | 裁决 | 理由
------------------------------------------------------------------------------
.wt/acad1 | 63b0f8b | 否 | 0 | 0 | 否 | 否 | 43.8 | 保留 | 判据2：tip 未集成到主树 HEAD
.wt/copy1 | 6007290 | 否 | 0 | 0 | 否 | 否 | 43.6 | 保留 | 判据2：tip 未集成到主树 HEAD
.wt/lean1 | 764a316 | 是 | 0 | 0 | 否 | 否 | 43.4 | 可删 |
.wt/gates1 | 6d41e0e | 否 | 0 | 0 | 否 | 否 | 43.3 | 保留 | 判据2：tip 未集成到主树 HEAD
.wt/rev1 | 99b114a | 否 | 0 | 0 | 否 | 否 | 43.3 | 保留 | 判据2：tip 未集成到主树 HEAD
.wt/darkgate | 4870bea | 是 | 0 | 0 | 否 | 否 | 43.3 | 可删 |
.wt/left1 | 71de85d | 否 | 0 | 0 | 否 | 否 | 43.0 | 保留 | 判据2：tip 未集成到主树 HEAD
.wt/rail2 | a9f541a | 否 | 0 | 0 | 否 | 否 | 43.0 | 保留 | 判据2：tip 未集成到主树 HEAD
.wt/traepool1 | 150de81 | 是 | 0 | 0 | 否 | 否 | 43.0 | 可删 |
.wt/pypath1 | 71695f6 | 否 | 0 | 0 | 否 | 否 | 42.7 | 保留 | 判据2：tip 未集成到主树 HEAD
.wt/accept2 | c9d22a1 | 是 | 0 | 0 | 否 | 否 | 42.7 | 可删 |
.wt/habit1 | 0a0029d | 否 | 0 | 0 | 否 | 否 | 42.7 | 保留 | 判据2：tip 未集成到主树 HEAD
.wt/accept1 | 921e1c0 | 否 | 0 | 0 | 否 | 否 | 42.5 | 保留 | 判据2：tip 未集成到主树 HEAD
.wt/locks1 | 97f59b7 | 否 | 0 | 0 | 否 | 否 | 42.4 | 保留 | 判据2：tip 未集成到主树 HEAD
.wt/wave1 | 75c8665 | 否 | 0 | 0 | 否 | 否 | 42.4 | 保留 | 判据2：tip 未集成到主树 HEAD
.wt/index1 | 709d5e0 | 否 | 0 | 0 | 否 | 否 | 42.4 | 保留 | 判据2：tip 未集成到主树 HEAD
.wt/docsync1 | 6c55059 | 否 | 0 | 0 | 否 | 否 | 42.3 | 保留 | 判据2：tip 未集成到主树 HEAD
.wt/bg1 | 3deeb47 | 否 | 0 | 0 | 否 | 否 | 42.2 | 保留 | 判据2：tip 未集成到主树 HEAD
.wt/traegate | c2fed5e | 是 | 2 | 0 | 否 | 否 | 42.2 | 保留 | 判据3：有 2 个未提交的已跟踪改动
.wt/cli1 | be33d0e | 否 | 0 | 0 | 否 | 否 | 42.1 | 保留 | 判据2：tip 未集成到主树 HEAD
.wt/lease1 | 3145051 | 否 | 0 | 0 | 否 | 否 | 42.1 | 保留 | 判据2：tip 未集成到主树 HEAD
（中略 65 行）
汇总：可删 9 棵 / 保留 76 棵 / 可释放 245.5 MB
EXIT=0
$ git worktree list --porcelain | grep -c '^worktree '     # 跑后（与跑前相等 = 一棵没删）
86
```

- **可删 9 棵**：`.wt/lean1` `764a316` / `.wt/darkgate` `4870bea` / `.wt/traepool1` `150de81` /
  `.wt/accept2` `c9d22a1` / `.wt/index2` `d842771` / `.wt/RI10` `c2fed5e` / `.wt/ledger5` `a4a5224` /
  `.wt/survey4` `a4a5224` / `.wt/decide` `277cf49`（tip 都已进主树 HEAD `4870bea`、无未提交改动、无进程、无锁、非 locked）。
- **保留 76 棵**的理由分布：判据2（tip 未集成）为主；`.wt/traegate`（2 个跟踪改动）与
  `.wt/vis`（2 个跟踪改动 + 1 个未跟踪）撞判据3；`.wt/wtprune` 是**当前工作树**（判据1）。
- `--min-size` 默认 0（全看）；本次 9 棵里有 3 棵只有 7–8 MB（其余 42–43 MB）。

## 三、临时仓库 `--apply` 证据（**没碰真 `.wt`**）

命令（在 `mktemp -d` 造的临时仓库里，`git init` + 一次提交，再建 4 棵 worktree）：

```
git -C <R> worktree add --detach <R>/.wt/clean  HEAD              # 已集成 + 干净 → 该删
git -C <R> worktree add --detach <R>/.wt/dirty  HEAD              # 已集成 + 改 a.txt → 该留
git -C <R> worktree add --detach <R>/.wt/ahead  HEAD              # 再提交一笔 → 未集成 → 该留
git -C <R> worktree add --detach <R>/.wt/locked HEAD ; git -C <R> worktree lock <R>/.wt/locked   # locked → 该留
python -X utf8 tools/wt_prune.py --root <R> --apply
```

现跑读数：

```
=== 建好：worktree 计数 5 ===
=== .wt 工作树清理器 · APPLY（真删） · 仓库根 ...\repo ===
树名 | tip | 已集成 | 跟踪改动 | 未跟踪 | 进程占用 | 锁 | 大小MB | 裁决 | 理由
------------------------------------------------------------------------------
.wt/ahead | 0bcbb86 | 否 | 0 | 0 | 否 | 否 | 0.0 | 保留 | 判据2：tip 未集成到主树 HEAD
.wt/dirty | 1be9784 | 是 | 1 | 0 | 否 | 否 | 0.0 | 保留 | 判据3：有 1 个未提交的已跟踪改动
.wt/locked | 1be9784 | 是 | 0 | 0 | 否 | 是 | 0.0 | 保留 | 判据6：worktree 被 locked
.wt/clean | 1be9784 | 是 | 0 | 0 | 否 | 否 | 0.0 | 可删 |

汇总：可删 1 棵 / 保留 3 棵 / 可释放 0.0 MB

=== --apply：开始真删（每棵先复核七条，且不用 --force）===
[apply] 删了 1 棵：.wt/clean
[apply] 留住 0 棵

--- apply 后汇总：已删 1 棵 / 未删 0 棵 ---
EXIT=0
=== apply 后：worktree 计数 4 ===
.wt/clean 没了   .wt/dirty 在   .wt/ahead 在   .wt/locked 在
```

→ **删掉 1 棵该删的、保住 3 棵该留的，退出码 0**；计数 5 → 4。

## 四、先红后绿（变异副本，不改工作区）

`tests/test_wt_prune.py` 支持环境变量 `WT_PRUNE_UNDER_TEST` 指一份**变异副本**（同
`tests/test_gate_lock_multi.py` 的手法）。把判据 6 改坏（`elif tree.locked:` → `elif False and tree.locked:`）：

```
$ WT_PRUNE_UNDER_TEST=<变异副本> python -X utf8 -m pytest tests/test_wt_prune.py -q --no-cov
FAILED tests/test_wt_prune.py::test_locked_is_kept              # locked 的树被误判成"可删" → 红
FAILED tests/test_wt_prune.py::test_cli_apply_removes_only_deletable
2 failed, 9 passed
$ python -X utf8 -m pytest tests/test_wt_prune.py -q --no-cov   # 真文件（绿）
...........                                                      [100%]
11 passed
```

## 五、结论一句话

**真树一棵都没删** —— `tools/wt_prune.py` 默认只看不删，本次只跑了 dry-run；哪些可删由主控看完上表再决定
（真删命令：`python -X utf8 tools/wt_prune.py --apply`，它会每棵再复核一遍七条且不用 `--force`）。

## 六、如实登记的边界 / 我判不准的（★ 不回缩）

1. ★ **判据 7 今天"保护不到任何树"**：`docs/workbacklog.toml` 当前 3 张卡**全是 `status = done`** →
   判据 7 的命中集是空 → 它只证明"没有 backlog 登记的未完工卡占这些树"，**不能**证明"这些树没人在用"。
   `.wt` 下 85 棵树里有多少是**在飞但没登记进 backlog** 的卡，本工具**判不出**（卡里只给了 backlog 这一条口径，
   不硬编码卡号）。→ 我把这点如实登记，请主控在采纳"可删"结论前用别的账（卡表 / 派活记录）再核一遍。
2. ★ **判据 4 取的是保守方向**：铁律 28 的完整双判据是"端口段 ∩ cwd==树根"，但那套是为"**掐进程**"设计的
   （用端口段圈定要处理的进程）。本卡**不杀任何进程**、只判"树里有没有进程"，所以我实现为**更宽的安全侧**：
   只要有进程的 cwd 在树里就算占用（**端口段只用来标注**，不参与判定）—— 这只会**多保留**、不会误删。
   若主控要求**逐字**复刻"端口 ∩ cwd"的窄口径，请明说，我改。
3. **未跟踪文件与 `git worktree remove` 的张力**：判据 3 说未跟踪**不算阻塞**（判"可删"），
   但 `git worktree remove`（不带 `--force`）**遇到未跟踪文件会拒**。所以一棵"干净但带未跟踪文件"的树会被判
   `可删`，`--apply` 时**删失败 → 保留 + 退 1**（这是卡 §2.1 明写的"失败就保留并打印原因"，不是 bug；
   `tests/test_wt_prune.py::test_cli_apply_keeps_when_remove_fails` 钉着它）。本次真树 9 棵"可删"的
   **未跟踪计数都是 0**，不会踩到这个。
4. **`--min-size` 的语义我自己定的**：小于阈值的树**不显示**、计入"跳过"（卡没写清语义）。默认 0 = 全看。
5. **本卡没做的**：不删任何真树；不碰 `.wt/**` 一个字；不改 `tools/`（除新增 `wt_prune.py`）、别的 `tests/`、
   `src/`、`scripts/`、别的 `docs/`、`gates/diag/**`、`data/`、主树外来未跟踪文件。
