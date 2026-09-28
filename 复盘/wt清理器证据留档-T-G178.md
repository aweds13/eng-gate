# 补漏卡 083 · `.wt` 清理器补「删前证据留档」：不补就**不许删**（`T-G178`）

> 卡 081（`T-G176`，集成 `46c76d7`）交付了 `tools/wt_prune.py`（默认 dry-run、七条判据、`--apply` 两拍复核、
> 不带 `--force`）—— 那部分**没问题**。但它**完全没有"删前拷证据"的逻辑**，而仓库**既有规矩**明写这件事。
> 本笔补齐；**真树一棵未删，`--apply` 未对真 `.wt` 跑过**（红线）。

## §一 缺口原文（照抄 `gates/diag/do_tg120.py` §19.3，同见台账 `T-G120`）

```
拆树之前，把这三份**拷回主树** `gates/diag/`（它们会随树一起消失）：

gates/diag/wb-<卡>.dispatch.log     ← ★ 里面有 `--model` 那行：「这张卡用了哪个模型」的唯一凭证
gates/diag/wb-<卡>.verdict.txt
gates/diag/wb-<卡>.report.md

★ **真丢过一次**：2026-09-26 跑在 worktree 里的那批卡（后来换成 kimi 的那几轮）日志随树一起没了 →
事后**从仓库里查不出「哪张卡用了哪个模型」**，只能靠会话记忆。
★ 所以这也是**集成者收尾步骤**的一部分（卡 012b / 012c 的 §2.7）：
`git worktree remove` **之前**先拷这三份。
```

### 为什么这是**真问题**（不是洁癖）

081 自报的「可删」里就包含 `.wt/lean1`(078) · `.wt/accept2`(079) · `.wt/darkgate`(080) ——
**一跑 `--apply` 就会烧掉这三张卡的模型凭证与报告**。本卡的规矩：**没拷走就不许删**（宁可保留）。

### 现算：真实的 `wb-*` 家族（不是三个写死的名字）

`ls .wt/darkfix/gates/diag/` 现测：

```
wb-082.heartbeat.txt  wb-082.jsonl        wb-082.report.md   wb-082.session.txt
wb-082.spec.txt       wb-082.stderr.txt   wb-082.verdict.txt wb-usage.jsonl
```

★ 两处与规矩原文的偏差，**以现算为准**：

- `do_tg120` 里写的 `wb-<卡>.dispatch.log` **已经不存在了**（那是旧版派活器的名字）；
  模型凭证现在长在 **`wb-<卡>.jsonl` 第 1 行 `{"type":"system","subtype":"init",…}`** 的 `model=` 里。
- 除每卡独占的文件外，还有一份 **`wb-usage.jsonl`**——它不是某张卡的，是**累积台账**。

## §二 修法（`tools/wt_prune.py`）

### 2.1 通配整族，不写死卡号

`scan_rescue(<树>/gates/diag)` 用 `glob("wb-*")` 取整族（**不写死卡号**——卡 081 判据 7 硬编码就保护不到东西）；
`wb-usage.jsonl` 单独拎出来（它是累积台账，要合并不是覆盖）；**别的文件一概不碰**（范围越小越好）。

### 2.2 两类不同的拷法（★ 弄错会烧掉历史）

1. **`wb-<卡>.*`（每卡独占）→ 拷到主树 `<root>/gates/diag/`**；**目标已存在则不覆盖**（打印 `已存在→跳过` 并计数）；
   目标同名位置竟是**目录** → 算**冲突失败**（不覆盖、不硬写）。
2. ★★ **`wb-usage.jsonl` 是累积台账（追加语义）→ 逐行追加合并，绝不许覆盖**。
   合并规则：按 `(卡, 开始)` 去重，已存在的行跳过；**只追加缺的行，既有行一个字节都不改**。

### 2.3 「没拷走就不许删」

`rescue_tree` 返回 `(是否成功, 报告行, …)`；任何一份拷不出来 / usage 合并失败 → **成功=False**
→ `do_apply` 把这棵树标记为**本轮不删**（`deletable = False`）、理由写进表里、**退出码计 1**（宁可保留）。

### 2.4 插在哪一行之前（§5.1 要求）

★ 留档在 `git worktree remove` **之前**做。`tools/wt_prune.py:698-707` 是留档块，
`:708` 才是删除行（`do_apply` 内、第二拍复核通过之后）：

```python
698        if rescue:
699            ok, line, _n_files, _n_add = rescue_tree(root, v.path)
700            if not ok:
701                v.deletable = False
702                v.apply_result = "留档失败"
703                v.apply_ok = False
704                failed += 1
705                v.reason = f"apply：{line} → 保留"
706                kept.append(f"{v.name}（{v.reason}）")
707                continue
708        rc, out, err = _git(["worktree", "remove", str(v.path)], root)
```

### 2.5 `--no-rescue` 逃生门（默认**关**）

默认**必须留档**；只在显式传 `--no-rescue` 时才跳过，并在 stderr 打醒目警告
（说明 `wb-*.jsonl` 第 1 行含 `model=`，是「这张卡用了哪个模型」的唯一凭证，会随树永久消失）。

### 2.6 干跑也预演

默认 dry-run 时，表里加一列 **「待留档」**：可删的树显示 `N份+usage追加K/跳过J`
（`N` = 每卡独占文件数，`K/J` = 只读预演一次 usage 合并会追加/跳过几行）；`--no-rescue` 时显示「不留档」。

## §三 三份读数（临时仓库 `--apply`，绝不碰真 `.wt`）

在 `git init` 的临时仓库里造树、放整套假 `wb-*`，逐场景跑：

### 场景 A：可删的树，带一整套假证据 → 留档后**成功删树**，退 **0**

```
[rescue] …\.wt\clean → 拷了 7 份（跳过 0 份已存在）；usage 追加 1 行（跳过 0 行已存在）
[apply] 删了 1 棵：.wt/clean
--- apply 后汇总：已删 1 棵 / 未删 0 棵 ---      RC_A=0    树：已删

主树 gates/diag/ 跑后（ls）：
wb-900.heartbeat.txt  wb-900.jsonl        wb-900.report.md   wb-900.session.txt
wb-900.spec.txt       wb-900.stderr.txt   wb-900.verdict.txt wb-usage.jsonl
```

### 场景 B：拷贝会失败（目标同名位置是**目录**）→ 树**被保留** + 退 **1**

```
[apply] 留住 1 棵：.wt/blocked（apply：留档失败：目标 wb-901.jsonl 是同名目录（不覆盖） → 保留）
[apply] ★ 1 棵本应删掉的树删失败（已保留，原因见上）
RC_B=1    树：在（保留）
```

### 场景 C：`--no-rescue` → 不拷不合并，但树仍按判据删，退 **0**

```
[apply] 删了 2 棵：.wt/nores、.wt/blocked      RC_C=0
主树 gates/diag/ 里 wb-902.* 计数 = 0（没拷）；usage 没被碰
stderr：★★★ 警告：--no-rescue 已开 —— 本轮**不留档**……会随树一起**永久消失**……
```

### usage **追加合并**（本卡最容易写错的一格）

`tests/test_wt_prune.py::test_apply_merges_usage_without_clobbering`：
主树先放 2 行（A、B），树里放 **1 行新（C）+ 1 行已在主树（B）** → 跑完主树那份 = **3 行**，
且 `after_bytes.startswith(before)` 为真（**既有 2 行逐字节未变**）、重复的 B **没有被重复追加**。

## §四 真树只读预演（**只读，一棵未删，`--apply` 一次未跑**）

`python -X utf8 tools/wt_prune.py`（dry-run）汇总行：

```
汇总：可删 11 棵 / 保留 76 棵 / 可释放 332.5 MB
```

★ **与卡的偏差（如实）**：卡 §0/§1.3 写「9 棵可删」，那是卡 081 当时的快照；本卡现算（底座 `68df254`）是 **11 棵**
（期间 077/079/082 等已陆续集成，判据 2 由红转绿）。**以现算为准**，逐棵列**待留档份数**：

| 树 | tip | 待留档 | 说明 |
|---|---|---|---|
| `.wt/darkfix` | `68df254` | 7份+usage追加1/跳过0 | 082，usage 尚未进主树 → 会**追加 1 行** |
| `.wt/lean1` | `764a316` | 7份+usage追加0/跳过1 | 078，usage 主树已有 → 跳过 |
| `.wt/wtprune` | `46c76d7` | 7份+usage追加0/跳过1 | 081，同上 |
| `.wt/darkgate` | `4870bea` | 7份+usage追加0/跳过1 | 080，同上 |
| `.wt/traepool1` | `150de81` | 7份+usage追加0/跳过1 | 077，同上 |
| `.wt/accept2` | `c9d22a1` | 7份+usage追加0/跳过1 | 079，同上 |
| `.wt/index2` | `d842771` | 0份 | 无 `gates/diag/wb-*`，无凭证可留 |
| `.wt/RI10` | `c2fed5e` | 7份+usage追加0/跳过1 | usage 主树已有 → 跳过 |
| `.wt/ledger5` | `a4a5224` | 6份 | 无 usage 文件 |
| `.wt/survey4` | `a4a5224` | 6份 | 无 usage 文件 |
| `.wt/decide` | `277cf49` | 6份 | 无 usage 文件 |

★ 结论：**11 棵里 10 棵有凭证**（共 7×7 + 3×6 = **67 份**独占文件待拷），
其中 **只有 `.wt/darkfix` 会往 usage 台账号追加 1 行**（082），其余都在主树里了 → 跳过。

### 「真树一棵未删」证据

```
git worktree list --porcelain | grep -c '^worktree '   跑前 = 88
python -X utf8 tools/wt_prune.py                        （dry-run，一棵未删）
git worktree list --porcelain | grep -c '^worktree '   跑后 = 88
```

★ 两个数**相等**。`--apply` **一次都没对真 `.wt` 跑过**。真正删哪些树由**主控**看过表之后决定并单独做。

### 「本树 `gates/diag/` 没被写进任何证据」

留档目标恒为**主树** `<root>/gates/diag/`（`root` = `main_root()` 定位的主仓），**不是本树**。
本树的 `gates/diag/` 里只有派活器自己的文件（`wb-083.*`、`brief-083.md`、`卡083-*.md`、`gate_lock.py`），
跑完 dry-run 后其内容**一字未变**；`git status --porcelain`（本树）只多白名单里的两个被测/改动文件。

## §五 先红后绿（照卡 081 的好做法）

- **变异副本**（去掉 usage 去重那三行）→ `WT_PRUNE_UNDER_TEST=<变异副本> pytest tests/test_wt_prune.py` →
  **1 failed**（`test_apply_merges_usage_without_clobbering`：`assert 4 == 3`）+ 15 passed —— **必红**。
- **真文件** → `pytest tests/test_wt_prune.py` → **16 passed** —— **全绿**。

## §六 没动什么

`.wt/**` 的**任何**树一个字未删未改；`src/**`、`scripts/**`、别的 `tools/**`、别的 `tests/**`、
其余 `docs/**`、其余 `复盘/**`、`gates/diag/**`（本树没往里拷任何证据）、`data/`、
主树外来未跟踪文件 —— **全未碰**。本笔只改白名单内的：`tools/wt_prune.py`、`tests/test_wt_prune.py`、
本复盘、`docs/changelog.md`、`docs/traceability.toml`、`复盘/交接-重构进度.md`、`gates/last.json`、`gates/reuse.json`。
