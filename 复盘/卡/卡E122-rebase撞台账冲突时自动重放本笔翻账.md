# 卡 E122 · 落地链 rebase 撞到 `docs/workbacklog.toml` 冲突时自动重放「本笔翻账」，不再停手

> 台账号 `T-AG631`｜分区 E（门禁与可信度）｜树 `.wt/E122`｜层 判据层｜基准 `f8e13652`（立卡时主树 HEAD）｜depends E86

## 要解决的问题

落链在 ⑦ 段把卡树 rebase 到主树新 HEAD；只要**并发插队的两笔改过 `docs/workbacklog.toml`**，`resolve_derived_conflicts()` 就判「非派生物 ⇒ 必须人来判」、退 3。可这一笔对台账做的改动，是落地链自己在 ⑤′ 段刚做的那一行 `status` 翻账 —— 机器完全知道自己写了什么，却把答案扔掉让人重做一遍。

### 问题 1 —— 现场：E115 第四次落地被台账挡住（退 3）

`gates/diag/land-E115.log` 共 122 行，尾部原文：

```
land-E115.log:111  卡树提交不在主树 HEAD 上 → 先 rebase 到主树新 HEAD（并发/插队）
land-E115.log:112  rebase 冲突（并发两笔都动了共享文档 / 门禁产物）： docs/subsystems/pool/README.md · docs/workbacklog.toml
land-E115.log:113  ★★ 自动解决不了 ⇒ **停手**： ["冲突里有**非派生物**（必须人来判）：['docs/workbacklog.toml']"]
```

同一份日志的上下文读数：`:84  [队列] 卡 E115：pending → done（docs/workbacklog.toml；这一笔是它的落地）`、`:112` 之前 `HEAD = 64b58520`、退出码 3。人工随后做了四步：`checkout --theirs`（取主树台账）→ 手改 E115 的 `status = "done"` → 保留 E118 新卡块 → `rebase --continue`。**这四步里没有一步用到了机器不知道的信息。**

### 问题 2 —— 台账确实不是派生物，不能靠「重新生成整份」解决

读数（`tools/pool/landing.py`）：

```
:79   DOCS = ("docs/traceability.toml", "docs/changelog.md", "复盘/交接-重构进度.md")
:89   DERIVED = DOCS
:102  RECOUNT_DOCS = ("docs/subsystems/pool/README.md", "docs/INDEX.md")
:109  RESOLVABLE = (*DERIVED, *RECOUNT_DOCS)
:206  extra = [x for x in conflicted if x not in RESOLVABLE and x not in GATE_ARTIFACTS]
:207-208  if extra: return False, [f"冲突里有**非派生物**（必须人来判）：{extra}"]
```

`docs/workbacklog.toml`（171794 B / 6039 行，`file` 读数：`UTF-8 text, with CRLF line terminators`）是**唯一权威**：`scripts/gen_pool_readme.py:306 backend_metrics` 从它数「队列卡数 N 张（a done / b pending）」（`gen_pool_readme.py:294 _queue_sources`，E89 起分片优先）；反过来没有任何生成器能**造**它。所以本卡的口径是「重放这一笔的那一处改动」，**不是**「把台账并进 DERIVED」。

顺带一条容易搞错的读数：`复盘/交接-重构进度.md` 里那行「台账进度：done a / partial b / …」由 `tools/sync_counts.py:46-55 counts()` 从 **`docs/traceability.toml` 的 entries** 数出来（`sync_counts.py:42 LEDGER = ROOT/"docs"/"traceability.toml"`），与 `docs/workbacklog.toml` **无关** ⇒ 台账重放不会改它，别拿它当「台账的投影」来论证。

### 问题 3 —— 本笔对台账的改动是一行，且能机器认领

读数（`git -C .wt/E115`，只读）：

```
REBASE_HEAD                = 64b58520f2aeb4538663b684e4472cf90e349476   # 卡树本笔
REBASE_HEAD^               = f833d006                                  # 本笔的父（= merge-base）
merge-base HEAD REBASE_HEAD= f833d006                                  # 实测：就是本笔父，**不是**主树 HEAD
git diff --numstat REBASE_HEAD^ REBASE_HEAD -- docs/workbacklog.toml
  1       1       docs/workbacklog.toml
git diff -U0 REBASE_HEAD^ REBASE_HEAD -- docs/workbacklog.toml
  @@ -6023 +6023 @@ risk = "mid"
  -status = "pending"
  +status = "done"
```

★ 极性实测（临时仓，已消费）：rebase 冲突里 `git show :2:<path>` = **主树侧**（`--ours`），`:3:<path>` = **卡树侧**（`--theirs`）。⇒ 「本笔改了哪一行」必须用 `git diff -U0 $(git merge-base HEAD REBASE_HEAD) REBASE_HEAD -- <path>` 取；用 `HEAD` 会取到主树那两笔插队的改动，认领错文件。

### 问题 4 —— 重放 == 人工解，逐字节（已实测）

临时仓里用**真的三份 blob**（base `f833d006` / 主树 `ebd39871` / 卡树 `64b58520`）复现那次 rebase：

```
sizes base/trunk/card/hand: 171395 171794 171392 171791
rebase rc= 1 ; unmerged= ['docs/workbacklog.toml']
merge-base == base ? True
stage2(ours)==trunk ? True | stage3(theirs)==card ? True
ours 含 E118 ? True | theirs 含 E118 ? False
card-side -U0 body: ['-status = "pending"', '+status = "done"']
  [队列] 卡 E115：pending → done（docs/workbacklog.toml；这一笔是它的落地）
verdict= flipped
REPLAY == HAND 逐字节 ? True | sha cf8c5eb5b47d9038 cf8c5eb5b47d9038
continue rc= 0 [detached HEAD 85ff9e7] card  1 file changed, 1 insertion(+), 1 deletion(-)
post-continue == HAND ? True
```

sha256 读数（三份都用 `git show <rev>:docs/workbacklog.toml` 取的 blob 字节）：主树 `7e2104c3155f1c8d`（171794 B）、卡树 `94d35715404bcbbe`（171392 B，缺 E118 整块 16 行）、人工解 `cf8c5eb5b47d9038`（171791 B）。**重放结果与人工解同 sha。**

反向也测了：对卡树版字节重放 ⇒ `verdict="not-needed"`（「已是 done ⇒ 跳过」）、字节未变 ⇒ 幂等。

> 字节层面的注记：git 里这三份 blob 都是 **LF**（`CRLF=0`）；工作区里的 CRLF 来自 `core.autocrlf=true`（本机实测 `true`）。`.gitattributes` 只钉了两条（`gates/render/*.txt text eol=lf`、`*.cmd text eol=crlf`），`git check-attr -a docs/workbacklog.toml` 输出为空 ⇒ 该文件**无属性**。所以判定一律在**字节层**做，重写必须走 `flip_card_status` 的按字节路径（`_split_blocks` = `raw.splitlines(keepends=True)`，`landing.py:1126`；落盘 `ledger.write_atomic`，`landing.py:744`），不许用文本模式重写。

### 问题 5 —— 输入在不在作用域（结论：在，但签名要加两个关键字参数）

```
landing.py:193   def resolve_derived_conflicts(wt: pathlib.Path) -> tuple[bool, list[str]]:
landing.py:2985  ok, detail = resolve_derived_conflicts(wt)        # ⑦ 段调用点
landing.py:2811  _verdict = flip_card_status(wt, a.card, a.task)   # ⑤′ 段：同一个 main 函数体
landing.py:2355  parser.add_argument("--card", ...)   :2358 --task
```

⑦ 段与 ⑤′ 段在**同一个 `main()` 函数体**里（`landing.py:2349 def main(...)`），`a`（argparse 结果）、`allow`、`new` 都还在作用域 ⇒ 只要给 `resolve_derived_conflicts` 加 `*, card: str | None = None, task: str | None = None`，⑧/:2985 传 `a.card, a.task` 即可，**不需要重构**。既有的 7 处单参调用（`tests/test_landing_derived_resolvable.py:211 / :221 / :233 / :242 / :251 / :264 / :298`）默认 None ⇒ 一字不变。

**批模式拿不到输入**：`landing.py:2799 flip_batch_member_statuses(wt, a.batch, staged)` 的 `staged` 来自 `:2798 staged, extra = staged_and_extra(wt, allow)`，是 ⑤′ 段的局部量，⑦ 段已不在作用域；`--batch` 的 `a.task` 是**批台账号**（永远比不中成员卡的 task，见 `:2794-2796` 注释）。⇒ 批模式**必须继续停手**（本卡不碰）。

### 问题 6 —— 反例清单（哪些几何下重放会给出不同答案）

| # | 反例 | 重放会怎样 | 本卡口径 |
|---|---|---|---|
| 1 | 主树那侧**也翻过同一张卡**（并发另一笔把它标 done） | 卡树侧 `--ours` 已是 done ⇒ `flip_card_status` 返回 `not-needed`，字节不变 | 正确，但必须**单独判**：只有当 `-U0` body 恰是 `-status`/`+status = "done"` 且 ours 已是 done 时才算成功 |
| 2 | 主树那侧翻的是**别的卡** | 重放只动目标卡，其余块原样 | 正确 |
| 3 | 批模式（一提交翻多张成员卡） | ⑦ 段拿不到 `staged` 清单 ⇒ 无法逐成员判「产物 ∩ 暂存」 | **停手**（不算本卡范围） |
| 4 | 台账分片 `docs/backlog/*.toml`（`landing.py:610 _shard_paths` / `:640 _queue_file_for`） | 重放只写**目标卡所在的那一片**；总表在分片启用后是生成物 | 本仓 `ls docs/backlog` ⇒ `No such file or directory`（无分片）；分片环境须按 `_queue_rels(wt)` 逐个认，**且只认 hunk 落在的那一份** |
| 5 | 登记型提交（`--task` ≠ 卡.task，`landing.py:714-717`） | 重放返回 `not-needed` 且字节不变 | 正确，但**不能报「已自动解决」** —— 要按 `not-needed` 走停手并说明原因 |
| 6 | 同一提交里改了**两张以上**卡块 | `-U0` body 会有 4+ 行 | 停手并点名（不给自动解决） |
| 7 | 目标卡块里**没有 `status` 行** | `flip_card_status` 返回 `unflippable`（`landing.py:718-722`） | 停手（「该翻却翻不动」不许沉默） |
| 8 | 极性搞反（以为 `--ours` 是卡树） | 会拿卡树版当底、把主树的 E118 块丢掉 | 必须用 merge-base 取本笔 hunk，并断言 `:2` 含插队块、`:3` 不含 |
| 9 | 重放后忘了 `git add` | 索引仍是 `UU`（E86 实测过，见 `tests/test_landing_derived_resolvable.py:215`） | 必须 `git add -- <path>` |

### 问题 7 —— 幂等与锁

`flip_card_status` 写盘走 `landing.py:735 with ledger.Hold(ledger.lock_path(ledger.main_root(wt))):`，`ledger.main_root`（`tools/pool/ledger.py:122-138`）用 `--git-common-dir` 的 parent = **主树**，rebase 期间卡树 detached 也解析得出来；`ledger.lock_path`（`:157-163`）**不看** `TF_GATE_PORT_BASE`（台账只有一份）。⇒ 重放不需要新锁、不需要新写路径。

## 兼容面（改了会碰到谁 —— grep 出来的，不是猜的）

- `tools/pool/landing.py:2985` —— ⑦ 段唯一调用点；加关键字参数要在这里传 `a.card, a.task`。
- `tools/pool/landing.py:206-208` —— `extra` 过滤：**不许**把台账并进 `RESOLVABLE`，台账要走单独一条「先认领 hunk、再重放」的支路。
- `tools/pool/landing.py:226-238` —— 现算文档的重算顺序：重放台账**必须排在 `sync_docs` 之前、`check_derived_docs` 之前**（README 的队列卡数从台账数出来，台账改了就得重算）。
- `tools/pool/landing.py:657-747` —— `flip_card_status` 本身**不改**（三态语义已是判据：`flipped` / `not-needed` / `unflippable`）。
- `tools/pool/landing.py:657` 的 `require_task_match`：单卡路径默认 `True`，重放沿用默认值（登记型提交天然 no-op）。
- `tests/test_landing_derived_resolvable.py:194-199` —— 「两张表的语义不同，不许悄悄并进 `DERIVED`」。
- `scripts/gen_pool_readme.py:294/306-332/365` —— 台账的投影消费者（分片优先，总表兜底）。

## 判据

### 判据 1（钉子名：`signature_defaults_keep_callsite_unchanged`）—— 签名加参、调用序列一字不变

`resolve_derived_conflicts(wt, *, card=None, task=None)`。不传参时（= 现有 7 处单参调用与 `tests/test_landing_derived_resolvable.py:272-307` 的录制式桩）调用序列必须**逐字相同**：`checkout --ours` × N → `sync_docs` → `sync_docs --check` → [`check_derived_docs`（仅当现算文档在冲突表）] → `git add` 一条。传了 `card`/`task` 但台账不在冲突表 ⇒ 同样不进新支路。

### 判据 2（钉子名：`only_the_landed_hunk_is_claimed`）—— 只认领本笔的那一行

用 `git diff -U0 $(git merge-base HEAD REBASE_HEAD) REBASE_HEAD -- <台账文件>` 取 body（去掉 `+++`/`---`）。**必须恰好两行**：`-status = "..."` 与 `+status = "done"`；否则 `return False` 并点名原因（不是 `flipped`、不是静默成功）。E115 实测 body 就是这两行（见问题 3 读数）。禁止用 `HEAD` 代替 `merge-base HEAD REBASE_HEAD`。

### 判据 3（钉子名：`replay_is_ours_then_flip`）—— 取 ours 再重放，三态各自处置

顺序固定：`git checkout --ours -- <path>` → `flip_card_status(wt, card, task)` → 判返回值：

- `flipped` ⇒ 继续（进 `add` 名单）
- `not-needed` ⇒ **只在**「ours 侧该卡已是 `done` 且卡树侧是别的值」时视为成功（并发那笔已经翻过，no-op 正确）；其它 `not-needed`（登记型提交 / 卡不存在）⇒ `return False` 并点名
- `unflippable` ⇒ `return False`（该翻却翻不动，不许沉默 —— E61 的口径）

### 判据 4（钉子名：`replay_is_byte_exact`）—— 逐字节不变量

重放后的台账字节必须同时满足：

1. `sha256` == 「主树那版字节，且只把目标卡块的 `status` 行换成 `done`」的 sha256（E115 参考值 `cf8c5eb5b47d9038`）；
2. **其他卡块一字未变**：用 `_split_blocks` / `_scan_blocks`（`landing.py:1106-1162`）逐块比，除目标块外每块的 `(起行, 止行, fields)` 与原字节对应块完全相等；
3. 目标块 `status == "done"`，且该块内**只有** `status` 行变化（行数不变）；
4. 残留冲突标记计数 0：`<<<<<<<` / `=======` / `>>>>>>>` 在文件字节里各 0 次；
5. 行尾不变：`b"\r\n"` 出现次数与主树版相同（重放不许把 CRLF 洗成 LF，也不许反向）；
6. 之后 `git diff --name-only --diff-filter=U` 为空（必须 `git add`，否则索引仍是 `UU` —— `tests/test_landing_derived_resolvable.py:215` 的原文注释就写着这条）。

### 判据 5（钉子名：`any_guard_failure_restores_the_scene`）—— 停手必须还原冲突现场

任何守卫失败（判据 2/3 不过、重放异常）都要把人工可接手的现场还回去：`git checkout --merge -- <path>` 实测能把已被 `--ours` 解开的文件**重新变回带标记的 `UU`**（实测 `rc=0`、`unmerged after --merge: ['f.toml']`、`has markers: True`）。不许留「一半已解决」的树 —— 对齐既有钉子 `tests/test_landing_derived_resolvable.py:268 assert _unmerged(repo), "停手时不许动冲突现场"`。

### 判据 6（钉子名：`resolvable_tables_and_scope_unchanged`）—— 放宽只到台账，不外溢

`RESOLVABLE` / `DERIVED` / `RECOUNT_DOCS` 三张表**一字不改**（`tests/test_landing_derived_resolvable.py:196` 的等式仍成立，`:199` 的「不许悄悄并进 DERIVED」仍成立）；台账**不**进 `RESOLVABLE`（`:201` 的 `extra` 过滤串照旧）；源码文件进冲突集合仍 `return False` 并点名（`:259-268`）；批模式仍停手。

## 交付

1. `tools/pool/landing.py`：
   - `resolve_derived_conflicts` 加 `*, card: str | None = None, task: str | None = None`；
   - 新增内部函数（建议 `_replay_backlog_status(wt, path, card, task) -> tuple[bool, list[str]]`），只做「认领 hunk → `--ours` → `flip_card_status` → 校验」四件事，**不新造任何翻账口径**（一律调 `flip_card_status`）；
   - 位置：现算文档重算（`:226-238`）**之前**，`git add`（`:239-241`）之前；`add` 名单加上台账那一份；
   - `:2985` 传 `a.card, a.task`。
2. 新增 `tests/test_landing_backlog_replay.py`：真 `git init` 夹具 + 真造 rebase 冲突（照抄 `tests/test_landing_derived_resolvable.py:126-169` 的造法，`core.autocrlf=false`），覆盖判据 1–6 与反例 1/5/6/7/8。
3. `docs/changelog.d/T-AG631.md`：记「台账重放」这条口径、为什么**不**并进 `DERIVED`、批模式为何不在范围内。

## 验收（三条，落地前自跑，零手工步骤）

```
python -X utf8 -m pytest tests/test_landing_backlog_replay.py tests/test_landing_derived_resolvable.py \
    tests/test_mixed_endings.py tests/test_e89_shards_enabled.py -q --no-cov
python -X utf8 -m ruff check --line-length 100 tools/pool/landing.py tests/test_landing_backlog_replay.py
python -X utf8 scripts/check_derived_docs.py --check
```

（`pyproject.toml:51 addopts = "-q -m \"not acceptance and not chain\" --cov=timeflow --cov-fail-under=70"`；`--no-cov` 已确认存在，`python -m pytest --help` 第 242 行。ruff 基线：`python -m ruff check --select E,F,W,I --line-length 100 tools/pool/landing.py` ⇒ `All checks passed!`。）

## 不许做

- **不许**把 `docs/workbacklog.toml` 并进 `DERIVED`（它是唯一权威、不是派生物；并进去会让「重汇总」这条腿长出第二份真源）。
- **不许**把台账加进 `RESOLVABLE`（那会让 `:206` 的 `extra` 过滤放行，源码之外的一切都跟着放宽）。
- **不许**放宽到源码文件或其他非派生物：本条支路只认 `docs/workbacklog.toml`（分片环境再加 `docs/backlog/*.toml` 中**hunk 落在的那一份**）。
- **不许**在冲突解决里另造翻账口径（不许自己拼 `status = "done"` 字符串、不许另写正则、不许另开写盘路径）：唯一实现是 `flip_card_status`，唯一写盘是 `ledger.write_atomic`。
- **不许**在批模式（`--batch`）上自动解决：⑦ 段拿不到 `staged` 成员清单，判不出「哪些成员该翻」。
- **不许**用 `git diff` 的默认上下文认领 hunk（必须 `-U0` 且基准是 `merge-base HEAD REBASE_HEAD`）。
- **不许**在重放失败时留下半解决的树（见判据 5）。
- **不许**动 `.wt/` 工作树或主树被跟踪文件来做实验（本次取证只在临时目录里重建几何）。

