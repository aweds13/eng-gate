# 0008 复盘/ 不收项目书：回头看 vs 往前做分家

Status: Accepted
Date: 2026-10-24
Supersedes:
Superseded-by:
来源: 台账 F1 / T-AG449（`docs/workbacklog.toml:3596-3606`）、A291 / T-AG405；`复盘/卡/卡F1-文档归位.md`、`复盘/卡/卡A291-项目书进git.md`；`tools/migrate_docs.py`、`docs/migration-map.json`

## 背景与问题

`复盘/` 名不副实：卡规格、项目书、计划混在一起，「复盘」两个字既指回头看也指往前做。
交接时找不到「这摊是哪几件、验收数字是多少」；卡规格引用项目书时又常指向一篇没入库的文件
（A291 就是为这个开的：项目书写完了但没进 git，巡检与卡规格都引用不到）。

## 候选方案

A 都留在 `复盘/`（不用动任何路径，但名与内容继续不符，交接靠人翻一遍）。

B 按「回头看 vs 往前做」分家：`复盘/` 只留真复盘与交接；卡规格迁 `docs/cards/`，
项目书迁 `docs/subsystems/*`；迁移**只改路径不改内容**（`git diff -M` 全是 rename），
脚本先记账（journal）再动手，失败可 `--revert` 还原。

## 决定

选 B，落点 `tools/migrate_docs.py`：`--dry-run`（默认只算不写）/ `--apply`（第一步把
old→new 全表写进 `gates/diag/doc-migration.json`）/ `--revert`（只认这张表）；
映射表是 `docs/migration-map.json`。验收三件一起过才算搬迁成功：
`scripts/audit_progress.py --all` ✅、`tools/wb_plan.py check` `[OK ]`、
`pytest tests/test_card_specs_tracked.py -q` 全绿。

**已知边界（照实写）**：脚本与映射表已经在了，但**搬迁还没实际执行** ——
`复盘/卡/` 仍在、`docs/cards/` 还不存在、台账里的 `spec=` 仍全部指向 `复盘/卡/`。
放弃 A 的代价：要维护一张映射表与回滚路径；换来的是「复盘」这个目录名重新能信。

## 把握程度

medium —— 迁移脚本的改写规则、回滚、幂等有测试（`tests/test_migrate_docs.py`），
但真实搬迁一次都没跑过，所以「搬完三件仍然全绿」这条还没验。
