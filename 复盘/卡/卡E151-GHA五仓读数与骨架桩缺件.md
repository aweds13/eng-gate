# 卡 E151 · GHA 五个仓的读数回写 + 骨架号池桩缺件

> 台账号 `T-AG686`｜分区 E（门禁与可信度）｜树 .wt/E151｜层 文书层 + 代码层（一段小修）｜基准见建树时主树 HEAD｜depends E146 / E148 / E150

## 要解决的问题

### 问题 1 · §6 的「最近一趟」还停在 `97d009e5`，而最近跑完的是 `ce93720e`

`docs/subsystems/ci/GitHub-Actions-云门禁.md` §6 现在钉的是 job `136685943795`（run `44852205296`，head `97d009e5`）。
之后又推了一趟 `ce93720e`（run `44871996999`），它的 attempt 1（job `136748365260`）红了一门
`web_live`，同 head 的 attempt 2（job `136757280859`）23 门全绿。这一对读数要一起写进去 ——
只写绿的那趟会让人以为「这棵树一次就绿」，只写红的那趟会让人以为门禁坏了。

### 问题 2 · 五个仓搬上 GitHub 这件事，文档里只写了一个半

「把测试搬到 GitHub」已经落在五个镜像仓上（eng-gate / om-gate / fw-gate / dsh-gate / ura-gate），
但文档只在 §8.3 写了 om-gate 一个。读者要自己翻 GitHub 才知道另外四个跑什么、读数是多少。
要有一张表：每仓跑什么、最新读数是哪个 job、结论是什么。

### 问题 3 · 骨架的号池桩缺件时是裸 `FileNotFoundError`

`scripts/cloud/gha/build_snapshot.py` 的桩段先按 `[pool].need` 校验清单，再在 `rewrite_root` 段
直接 `open(<stub>/projects.toml)`。而 `profiles/engineering.toml` 的 `need` 只列了四件，
**没有 `projects.toml`** ⇒ 桩缺它时不会报 `POOL_STUB_INCOMPLETE`，而是抛
`FileNotFoundError: [Errno 2] No such file or directory: '<stub>/projects.toml'`，
退出码变成 1，与这套工具的 0/2/3/4/5/6 表对不上（2026-11-21 真踩：删掉临时目录后重推，两趟都撞这个）。

## 判据（逐条可执行）

### 判据 1 · §6 的抬头与正文指到 `ce93720e` 那趟，attempt 1 的红也写进去

抬头日期改成这一趟的日子；正文换 job `136757280859` / run `44871996999` / head `ce93720e`，
并写明：同 head 的 attempt 1（job `136748365260`）红门是 `web_live`，原文
`[FAIL] 真机自检没跑完：PUT http://127.0.0.1:56390/api/settings/ai`，重跑同环境就绿 ⇒ 那是抖动不是稳定红。

### 判据 2 · 每个数字都能从读数复算

逐门 `seconds` 从 job `136757280859` 的 `=== GHA-GATE-READING-BEGIN/END ===` 段取；
23 门求和 **3669.14 s**；job 墙钟 **1046 s**（`started_at 2026-11-21T06:18:05Z` / `completed_at 2026-11-21T06:35:31Z`）。
`pytest` 那门的 `summary` 原文照抄。

### 判据 3 · 新增一节写五个镜像仓各自跑什么

一张表：仓、可见性、跑什么（哪份 workflow / 哪个作业）、最新读数（job 号 + 结论）。
表下面要写清两件事：① 五仓都只剩 `CI` 一个 workflow 处于 active，其余九份模板 workflow 已用
`PUT /repos/<owner>/<repo>/actions/workflows/<id>/disable` 关掉；② 每个仓的 workflow 都是**模板生成**带过来的，
本机 token 没有 workflow scope，写不进去（实测六次，含首推新仓与 contents / git-data API 两条路）。

### 判据 4 · `rewrite_root` 的缺件由 profile 校验兜住，不是靠记得

三处一起改（缺一处都留着老洞）：

1. `scripts/cloud/gha/gate_profile.py` 的 `_cross_check`：`rewrite_root = true` 时 `projects.toml` 必须在 `need` 里，
   否则 `PROFILE_INVALID` 退 2 —— 判据住在加载器里，写 profile 的人不用记得。
2. `scripts/cloud/gha/profiles/engineering.toml` 的 `need` 补上它（补完加载器才认这份 profile）。
3. `scripts/cloud/gha/build_snapshot.py` 的 rewrite 段：读之前先判存在，缺了就 `POOL_STUB_INCOMPLETE` 退 6。

### 判据 5 · 缺陷有钉子

`tests/test_gha_cloud_gate.py` 新增两条：一条钉「`rewrite_root` 但 `need` 缺 `projects.toml` 的 profile 加载即拒」，
一条钉「目录里每份 profile 都过得了这条校验」（防止只修 engineering 那份）。

### 判据 6 · 三道文档门不涨

`check_docs.py --mode report` 死指针不涨过基线 147；`check_layers.py` PASS；
`check_derived_docs.py --check` 双 OK（该重跑生成器就重跑，不许手改产物）。

## 交付

1. `docs/subsystems/ci/GitHub-Actions-云门禁.md`：§6 换 `ce93720e`（attempt 1/2 都写）、新增 §9 五仓表、§7 边界补 workflow scope 的实测轮次。
2. `scripts/cloud/gha/gate_profile.py`、`scripts/cloud/gha/profiles/engineering.toml`、`scripts/cloud/gha/build_snapshot.py`：判据 4 那三处。
3. `tests/test_gha_cloud_gate.py`：判据 5 那两条。
4. 两个文书片段（docs/changelog.d/T-AG686.md 与 docs/traceability.d/T-AG686.toml，**计划建**）：
   由 `tools/wb_stage_card.py` 现生成，不许手写。

## 验收（落地前自跑）

    cd .wt/E151
    python -X utf8 -m pytest -q -o addopts= -p no:cacheprovider tests/test_gha_cloud_gate.py tests/test_cloud_profiles.py
    python -X utf8 scripts/cloud/gha/build_snapshot.py --repo engineering --stage build
    python -X utf8 scripts/check_docs.py --mode report
    python -X utf8 scripts/check_layers.py
    python -X utf8 scripts/gen_doc_index.py --target docs
    python -X utf8 scripts/check_derived_docs.py --check

## 不许做

- 不许改 `scripts/cloud/run_gate.sh`（ECS 那条腿与这页无关，改它要另开卡）。
- 不许手改 `docs/INDEX.md` / `docs/changelog.md` / `docs/traceability.toml` / `复盘/交接-重构进度.md`
  （都是生成 / 汇总产物）。
- 不许把旧几趟的读数删掉（`190903a0` / `97d009e5` / 2026-11-19 两趟必须留着当对照）。
- 不许在反引号里写仓外日志路径（`gates/enggate-logs/…` 不进仓，写它会被 `check_docs.py` 判死指针）；
  要指出处就写「job 编号 + 日志里的 BEGIN/END 段」。
- 不许顺手去删探针仓 / 刷新 token scope —— 那是人做的（§9 会写清）。
