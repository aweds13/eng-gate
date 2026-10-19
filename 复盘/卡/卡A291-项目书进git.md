# 卡 A291 · 项目书进 git（T-AG405）

## 问题

- `复盘/DSH三入口-项目书与接手单.md` 已写，但未入库；巡检与卡规格引用不到它，交接时找不到「这摊是哪几件、验收数字是多少」。

## 改法

1. 把项目书纳入 git（`git add`），并让 A289/A290 卡规格的「证据」节能引用它。
2. 项目书第 4 节拆卡表与实际卡号保持一致（A289–A292）。

## 判据

- `git ls-files 复盘/DSH三入口-项目书与接手单.md` 非空。
- `python -X utf8 scripts/audit_progress.py` 通过。
- 项目书里四张卡的 id 与 `docs/workbacklog.toml` 一致（脚本比对）。

## 证据

- `git ls-files` 输出；`docs/workbacklog.toml` 中 A289–A292 四条。
