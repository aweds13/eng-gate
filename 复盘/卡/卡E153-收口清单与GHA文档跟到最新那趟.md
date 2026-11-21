# 卡 E153 · 收口：把「只剩人要做的几件」写进入口清单 + GHA 文档跟着最新那趟

> 台账号 `T-AG688`｜分区 E（门禁与可信度）｜树 .wt/E153｜层 文书层｜基准见建树时主树 HEAD｜depends E152

## 要解决的问题

### 问题 1 · 「只剩人要做的」散在临时草稿里，入口文档没有这一栏

2026-11-21 起云门禁整体搬到 GitHub，机器侧能做的都做完了；剩下三件全卡在 GitHub 权限层
（delete_repo scope / workflow scope / 仓可见性），但 `复盘/收口后待用户清单.md` 里
只有产品层的六条（人工验收、口味项、三条已定不做的 SR），**没有一栏讲 GitHub 权限**。
结果：用户问「还差什么」时只能靠对话回答，关掉窗口就丢。

实测事实（2026-11-22 现读，命令与原文见下）：
- 删探针仓：`gh repo delete aweds13/wf-scope-probe --yes` ⇒
  `HTTP 403: Must have admin rights to Repository.` + `This API operation needs the "delete_repo" scope.`
- 改 workflow：git push 被拒 `refusing to allow an OAuth App to create or update workflow ... without 'workflow' scope`；
  **新实测**：挂到仓上的 deploy key 也绕不过（同一句 remote rejected）。
- 本机 token scopes `gh auth status` ⇒ `'gist', 'read:org', 'repo', 'user'`。

### 问题 2 · GHA 文档 §6 指的仍是 E152 修之前那一趟

`docs/subsystems/ci/GitHub-Actions-云门禁.md` §6 现钉 head `3a5bc8cc`（job 136874445171，attempt 3）。
E152 落地（主树 `d45578d8`）后重新快照推送，eng-gate 已起新一趟（head `7ec400f0`，run 44930214907）——
这一趟是 `gate_detail` 症状兜底与收口保留 ★ **第一次在真 runner 上跑**。
文档若停在三趟红红绿那一段，读者会以为「SUSPECT 标不出来」的现状没变。

## 判据（逐条可执行）

### 判据 1 · 清单新增一栏，三条事项各自带「要你做什么」与真源指针

`复盘/收口后待用户清单.md` 末尾新增 `## GitHub 侧待你动手（2026-11-22 新增…）` 一节，
表格三行 G-1（删四个空仓/探针仓，含四个仓名）／G-2（改 workflow 需 workflow scope）／
G-3（eng-gate 转 public 可选），每行都有「要你做什么」与「真源指针」两列；
另附一段「已经不需要你做的」与一段「五个仓各自在跑什么」。

### 判据 2 · 文档 §6 换成 E152 之后那一趟，且写清「这一趟验的是什么」

§6 抬头与正文指向 `7ec400f0` 那趟的 job / run / attempt；读数块给 `ok` / `host` / `rev` / `n_gates`；
逐门秒与同源求和可从读数 JSON 复算；并写明这一趟是 `gate_detail` 症状兜底上线后的首跑 ——
**web_live 若再红，`status` 该是 SUSPECT 或 detail 首行带 ★；若仍是无症状的 FAIL，就是兜底没生效，如实记**。

### 判据 3 · 旧读数降级保留，一条不删

原来 §6 的 `3a5bc8cc` 三趟表整段移进 §6.1「往前数」，与更早的 ce93720e / 97d009e5 / 190903a0 /
2026-11-19 两趟 / 1e815a96 并列。

### 判据 4 · §9 五仓表 eng-gate 行跟着走

`## 9. 五个仓都在 GitHub 上跑` 里 eng-gate 行的 head / run / job / 求和与判据 2 一致。

### 判据 5 · 三道文档门不涨

`scripts/check_docs.py --mode report` 死指针仍 147（基线 147，+0）；
`scripts/check_layers.py` PASS；`scripts/check_derived_docs.py --check` 双 OK。

## 交付

1. `复盘/收口后待用户清单.md`（+ 一节 GitHub 权限层）。
2. `docs/subsystems/ci/GitHub-Actions-云门禁.md`（§6 换最新一趟 + 旧读数降级 + §9 表同步）。
3. 两个文书片段（docs/changelog.d/T-AG688.md 与 docs/traceability.d/T-AG688.toml，**计划建**）：由 `tools/wb_stage_card.py` 生成，不许手写。

## 验收（落地前自跑）

    cd .wt/E153
    python -X utf8 scripts/check_docs.py --mode report
    python -X utf8 scripts/check_layers.py
    python -X utf8 scripts/gen_doc_index.py --target docs && python -X utf8 scripts/check_derived_docs.py --check
    python -X utf8 -m pytest -q -o addopts= -p no:cacheprovider tests/test_cloud_profiles.py tests/test_gha_cloud_gate.py

## 不许做

- 不许改 `scripts/` `tools/` `tests/` 任何一行（这张卡只写文书）。
- 不许手改生成产物（docs/INDEX.md、docs/subsystems/pool/README.md 的 margin 段）—— 只跑生成器。
- 不许删旧读数（降级到 §6.1 保留）。
- 不许在反引号里写仓外日志路径或**计划建**的片段路径（`check_docs.py` 会判死指针，基线只许降）。
- 不许顺手去删探针仓、刷新 token scope、改仓可见性 —— 这三件是判据 1 写给用户做的。
