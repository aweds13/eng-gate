# 卡 E154 · 探针仓已归档、噪声 workflow 四仓都关了：把这两条新事实写进入口清单

> 台账号 `T-AG689`｜分区 E（门禁与可信度）｜树 .wt/E154｜层 文书层｜基准见建树时主树 HEAD｜depends E153

## 要解决的问题

### 问题 1 · 清单 G-1 还写着「删四个空仓」，而机器侧能做的最后一步已经做完了

E153（`T-AG688`）在 `复盘/收口后待用户清单.md` 写的 G-1 是「删四个空仓 / 探针仓」，
「要你做什么」那列写的是「网页删，或本机跑 gh auth refresh … 之后我来删」。
2026-11-22 又试了一件 E153 没试的事：**删除做不了，但归档做得了**，四个仓已经全部变成只读归档态：

    gh api -X PATCH repos/aweds13/<仓> -F archived=true        # rc=0
    gh api repos/aweds13/wf-scope-probe --jq .archived          # true

现读四仓（`gh api repos/aweds13/<仓>`）：

| 仓 | private | archived | size |
|---|---|---|---|
| wf-scope-probe | true | **true** | 0 |
| fwprobe5 | true | **true** | 0 |
| fwprobe6 | true | **true** | 0 |
| python- | true | **true** | 0 |

删除仍然不行（本轮复验，原文）：

    gh repo delete aweds13/python- --yes
    HTTP 403: Must have admin rights to Repository.
    This API operation needs the "delete_repo" scope. To request it, run:
      gh auth refresh -h github.com -s delete_repo

⇒ 清单那句「四个空仓还挂在那儿等你删」已经**落后于事实**：它们不再出现在活跃列表里、也不能再被写，
剩下的只是「从账号里彻底消失」。这件事该写成两段（机器已做的 / 还要你做的），而不是一句「网页删」。

### 问题 2 · 「噪声 workflow 已关」只点了三仓，实际是四仓

同一份清单的「已经不需要你做的」那句写「三仓继承的噪声 workflow 已关（eng-gate / dsh-gate / ura-gate 各 9 份）」。
本轮现读 `gh api repos/aweds13/<仓>/actions/workflows`：

| 仓 | total | active | disabled | active 是谁 |
|---|---|---|---|---|
| eng-gate | 10 | 1 | 9 | `CI` |
| fw-gate | 10 | **1** | **9** | `CI` |
| dsh-gate | 10 | 1 | 9 | `CI` |
| ura-gate | 10 | 1 | 9 | `CI` |
| om-gate | 8 | 8 | 0 | （它自己的 8 份，不动） |

⇒ `fw-gate` 也是 9 份已关 1 份 active，口径要与事实对齐写成四仓。
这条不只是措辞：读者会拿「三仓」去推「还有一个仓没收拾」，白跑一次。

## 判据（逐条可执行）

### 判据 1 · G-1 行改写成「已归档，只剩删除」，并给两段分界

`复盘/收口后待用户清单.md` 的 G-1 行必须同时出现三件事：
① 四个仓名；② **已归档**这件事（`archived=true`，并说明归档后仓变只读、从活跃列表退出）；
③ 删除仍要 `delete_repo` scope，且给本轮 403 原文（含 `gh auth refresh -h github.com -s delete_repo` 那一行）。
「要你做什么」那列改成只剩「删」这一个动作 —— 归档不许再写成待办。

### 判据 2 · 「已经不需要你做的」那句是三仓改四仓

同一份清单里那句必须点名 **eng-gate / fw-gate / dsh-gate / ura-gate 四仓**，并保留「各 9 份、只剩 `CI` active」。

### 判据 3 · 只写文书，不碰代码

本卡不改 `scripts/` `tools/` `tests/` 任何一行；两个文书片段由 `tools/wb_stage_card.py` 生成，不许手写。

### 判据 4 · 三道文档门不涨

`scripts/check_docs.py --mode report` 死指针仍 147（基线 147，+0）；`scripts/check_layers.py` PASS；
`scripts/check_derived_docs.py --check` 双 OK。

## 交付

1. `复盘/收口后待用户清单.md`（G-1 行 + 「已经不需要你做的」那句）。
2. 两个文书片段（docs/changelog.d/T-AG689.md 与 docs/traceability.d/T-AG689.toml，**计划建**）：由 `tools/wb_stage_card.py` 生成。

## 验收（落地前自跑）

    cd .wt/E154
    python -X utf8 scripts/check_docs.py --mode report
    python -X utf8 scripts/check_layers.py
    python -X utf8 scripts/gen_doc_index.py --target docs && python -X utf8 scripts/check_derived_docs.py --check

## 不许做

- 不许改 `scripts/` `tools/` `tests/` 任何一行（这张卡只写文书）。
- 不许手改生成产物（docs/INDEX.md、docs/subsystems/pool/README.md 的 margin 段）—— 只跑生成器。
- 不许在反引号里写仓外日志路径或**计划建**的片段路径（`check_docs.py` 会判死指针，基线只许降）。
- 不许顺手去删那四个仓、刷新 token scope、改仓可见性 —— 删是判据 1 写给用户做的。
- 不许把「归档」写成「删掉了」：归档后仓还在，只是只读。
