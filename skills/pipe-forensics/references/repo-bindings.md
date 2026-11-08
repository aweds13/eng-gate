# pipe-forensics —— 本仓绑定（仓无关骨架之外的那一层）

> **这一页只放"这个仓是什么样"**：证据落在哪些目录、哪几条命令的退出码、层怎么分、
> 历史证据挂在哪。`SKILL.md` 里的查证顺序换仓也不变；
> 换一个仓用这套技能，**只换这一份**，别改 `SKILL.md`。
> 本仓 = `program/engineering`（`pipe` 框架 + timeflow 实现）。

## 证据落点（本仓路径）

| 证据 | 路径 | 谁写的 |
|---|---|---|
| 判决文件（全量门禁一趟一份） | `gates/last.json`（`ok` / `rev` / `branch` / 每门 `exit_code` / `detail`） | 门禁入口 |
| 逐门日志尾 | `gates/logs/<门名>.log` | 各门 |
| 派活侧诊断目录 | `gates/diag/`（工人逐事件 `.jsonl`、判决 `.verdict.txt` / `.report.md`、租约 `pool-registry.json`、批栅栏 `batch/*.toml`、锁账本 `ledger.lock`） | 派活器 / 门 / 看守 |
| 复核产物 | `gates/review/` | 复核链 |
| 复用记录 | `gates/reuse.json` | 门禁入口（增量执行） |
| 工人逐事件日志 | `gates/diag/wb-<卡号>.jsonl` | 工人 |

四份目录 2026-11-08 实查都存在（`ls gates/logs gates/review gates/reuse.json`）。

## 四条查证命令的真路径与参数

| 用途 | 本仓入口 | 参数（实测 `--help`） |
|---|---|---|
| 一屏核对 | `tools/wb_verify.py` | `--tree` / `--expect-parent` / `--allow` |
| 工人日志 | `tools/wb_diag.py` | 位置参数 `log`；`--full` / `--exit-code <码>` |
| 六块读数 | `tools/pipeline_view.py` | `--json` / `--report` / `--root` |
| 队列对账 | `tools/wb_reconcile.py` | `--root` / `--json` |

```bash
python -X utf8 tools/wb_verify.py --tree .                       # 一屏五块
python -X utf8 tools/wb_diag.py gates/diag/wb-<卡号>.jsonl       # 工人时间线
python -X utf8 tools/wb_diag.py gates/diag/wb-<卡号>.jsonl --exit-code <码>
python -X utf8 tools/pipeline_view.py --json                     # 六块，缺块 null + note
python -X utf8 tools/wb_reconcile.py                             # stale-pending / stale-done
```

- `tools/wb_verify.py --tree .` 在本仓当前树上的实跑末行是 `SUMMARY FAIL=4 OK=2` ——
  **那是本仓当下真实的 4 处红**（别人未提交的改动），不是工具坏了；别顺手去「修绿」。
- `tools/wb_reconcile.py`（卡 A318 起）派生对账：①状态由 git 派生 ②孤儿号。退出码 `0` 无孤儿 / `1` 有孤儿 / `2` 读不了台账。
- `tools/wb_card.py` 子命令 `add` / `lock-status`；退 `1` = 台账非纯 CRLF、退 `2` = 等不到锁；锁在 `gates/diag/ledger.lock`（**跨机不互斥**）。
- 门禁记 `not_run`（**NOT RUN 不是 PASS**）：node 缺失的门在本仓统一落 `not_run`，见 `scripts/run_gates.py`。

## ★ 层归属：哪些是本仓工作链，哪些是框架层

- 上面四条全是**本仓工作链**（`tools/wb_*.py` + 根 `scripts/run_gates.py`）。
- 框架层那条「门本身还有没有牙」的自检（框架 CLI 的 `doctor`，要一份 `pipeline.toml`）**不在本仓主路径上**：
  2026-11-08 实查仓库根**没有** `pipeline.toml`（`ls pipeline.toml` → No such file or directory），
  故 `pipe gate` / `pipe doctor` 在本仓主路径跑不了，硬跑只报「配置不存在」。
  它归框架层，命令与口径见 `skills/pipe-init/SKILL.md`，别拿它当本仓的门。

## 复盘缺口（编码 / 对账 / 证据指针 / 时钟 / 幂等 / 落地安全）

这一节是**历史证据层**：每条缺口挂 2–3 份复盘。读它为了知道「为什么有这条纪律」，不是当判据用。

- （缺口 EN2）外部命令 stdout 是系统区域编码（cp936）：用 `locale.getencoding()` 解，不许用 `getpreferredencoding(False)`（`-X utf8` 会让它回 utf-8）—— 证据文件读不出等于没留证据。证据：`复盘/口径坑.md`、`复盘/看门狗护栏补强-T-G96.md`、`复盘/看门狗误杀-T-G94.md`
- （缺口 LD1）台账对账器只认标题 / 批次围栏 / 证据指针语法，不认「差不多」；对不上的按死账处理，不就地改数 —— 对账红了就按死账流程走，别手改数对齐。证据：`复盘/卡/卡A280-对账器认批次围栏.md`、`复盘/卡/卡A272-对账器只认标题.md`、`复盘/契约-判据对账.md`
- （缺口 LD2）证据指针要有固定语法（`文件#段落` / `文件:行`），否则半年后没人能追回那条结论 —— 写证据指针前先看 `tools/wb_land.py --help` 的 `--evidence` 口径。证据：`复盘/证据指针语法-T-G133.md`、`复盘/卡/卡A271-补证据指针254.md`、`复盘/卡/卡A270-补证据指针.md`
- （缺口 LD3）封存之后才翻 status：先写指纹再改状态，顺序反了就是「状态说完了、证据说没完」—— 落地链⑤在⑥之前就是这个原因，别颠倒。证据：`复盘/卡/卡228-封存后才翻status.md`、`复盘/坑总账.md`、`复盘/DSH插件-定点深读-第二批.md`
- （缺口 LD4）主树禁 `reset --hard`：落地失败后手工 reset 会把主控刚写进台账的条目一起扫掉（2026-11-02 20:36，F13 条目被扫、只能重做立卡）—— 落地链自带主干保护：`tools/pool/landing.py:957` `def main_tree_offenders(allow: list[str], pen: pathlib.Path | None = None) -> list[str]:`，调用在 `tools/pool/landing.py:1673`（⑦ 主树 offender 为空）与 `:2407`（★★ 主干保护前置守卫，拒时 `return 5`）—— 主树有未白名单的跟踪文件改动就拒，主干只接受合并、不接受直接改。要清干净用 stash 挪开再精确复原。证据：`tools/pool/ledger.py` 头注释、`复盘/卡/卡G8-两条纪律进技能.md`
- （缺口 DF1）跨天/时区类缺陷的根治是注入「今天」（可注入时钟），不是改判定式 —— 复现这类缺陷先找时钟注入点，别改判定式迁就。证据：`复盘/黄金跨天漂移-可注入的今天-T-G62.md`、`复盘/审计-GLM53-外包系统对抗审核.md`、`复盘/坑总账.md`
- （缺口 DF2）幂等写库：重放同一笔不许产生第二行，判据是「再跑一次读数为 0」—— 查幂等缺陷时重放一遍，读数不变才算修住。证据：`复盘/幂等写库-T-G86.md`、`复盘/外包卡-002-修T-G79幂等写库.md`、`复盘/文档重整方案.md`

## 其他本仓读数

- 落地链的主干保护闸口在 `tools/pool/landing.py` —— 拒绝时的退出码 `5`（`tools/pool/landing.py:2407` 那段 `return 5`）。
- 工人在 Trae 面板里跑时没有进程也没有判决：它的收工 / 被掐信号归工作台那个技能（pipe-workbench）管，别在这里重写一份。
