---
name: pipe-forensics
description: 出事了从已落盘的证据里查——门禁产物、工人日志、封存指纹、队列与台账对账，定位是哪一步坏。当某道门红了、判决说不清、工人不动、或要复盘一次失败时用；它给查的顺序，不给你改判据的权力。
---

# pipe-forensics —— 出事了从证据里查

出事了（门红 / 判决说不清 / 复现不了）时，唯一可信的是**已经落盘的产物**，不是回忆。
顺序固定：先确认「这是哪棵树的哪一笔」，再逐层往下看。

## 什么时候用

- 门红了，要定位**是哪道门、哪一步**。
- 判决说不清（判不了 / 没跑 / 被复用），要分清是哪一种。
- 工人不动、日志里反复同一条命令。
- 要复盘一次失败：先看留痕，再看代码。

## 什么时候别用

- 只想跑一次门看红没红：用 `pipe-gate`。
- 想把红改成绿而**改判据**：那是改库 / 改门，另一件事；本技能只查不改。
- 想验证**门本身还活着**：那是金丝雀自检（它查判据有没有退化成注释），不是查你的代码。
- 手边没有出事那棵树 / 那份产物：先拿到产物，别猜。

## 前置检查

1. 知道证据落点：`gates/last.json`、`gates/logs/`、`gates/diag/`、`gates/review/`、`gates/diag/wb-<卡>.jsonl`。
2. 确认**是哪棵树**：`pwd` + `git rev-parse --show-toplevel` + `git rev-parse --short HEAD`。
3. 看一眼 `gates/last.json` 的 `rev` / `branch` —— 和你在的树对不上，读数就不能直接用。
4. 证据落点全表见 [证据落点](references/evidence-map.md)。

## 真命令

```bash
# 一屏核对：提交骨架 / 门禁 / 封存 / 台账 / 审计（哪个块 FAIL 就从哪查）
python -X utf8 tools/wb_verify.py --tree .

# 工人日志：哪一步失败、退出码、时间线（默认省略全文，--full 才打全）
python -X utf8 tools/wb_diag.py gates/diag/wb-<卡号>.jsonl
python -X utf8 tools/wb_diag.py gates/diag/wb-<卡号>.jsonl --exit-code <派活器看到的退出码>

# 队列 / 租约 / 门 / 判决 / 栅栏 / 树：六块一起看，缺块会给 null + note
python -X utf8 tools/pipeline_view.py --json

# 队列状态与 git 历史对账（stale-pending / stale-done）
python -X utf8 tools/wb_reconcile.py

# 门本身还有没有牙（要 pipeline.toml；本仓根没有，得指向真有配置的目录）
# ★ --json 是全局开关，写在子命令前面
python -X utf8 framework/cli/main.py --json doctor --config <pipeline.toml>
```

## 怎么读结果

- 先看 `python -X utf8 tools/wb_verify.py --tree .`：五块里哪块 FAIL，就先修那块对应的证据，不要跳着查。
- 门红：`gates/last.json` 里该门 `exit_code` 非 0，日志尾在 `gates/logs/<门名>.log`；跨树汇总用 `python -X utf8 tools/pipeline_view.py --json`。
- 工人不动：`python -X utf8 tools/wb_diag.py gates/diag/wb-<卡号>.jsonl` 看最后一个事件；「反复同一条被拒命令」是 harness 不支后台执行，不是工人不行。
- 队列说不清（落了没翻 / 翻了没落）：`python -X utf8 tools/wb_reconcile.py` 的三份清单。
- 「结论是不是这棵树的」：`gates/last.json` 的 `rev` / `branch` / `tree`，与 `python -X utf8 tools/wb_verify.py --tree .` 报的父提交对一遍。

## 常见错与处置

| 现象 | 真因 | 处置 |
|---|---|---|
| 判决「判不了」 | 空集：一条样例都没收集到 | 补样例或修收集器；**别当绿** |
| 判决「没跑」 | 运行时依赖缺失（node / 浏览器 / 服务） | 补依赖；回报里如实写「未跑」 |
| 某门带复用 | 读的是缓存，不是当下重跑 | 按 `pipe-gate` 的 `--no-reuse` 重跑 |
| 复现不了 | 结论属于**另一棵树**或另一笔提交 | 用 `rev` / `branch` 对齐后再读 |
| 工人日志一片 `UnicodeDecodeError` | 证据文件按错编码写的（PowerShell `>` 是 UTF-16） | 用 python 写证据，别用 `>` 重定向 |
| 台账里某条证据指不到 | 指针路径不存在 / 被 gitignore | 改成真路径；被 gitignore 的产物不算证据 |

## 从证据查到真因（五步）

| 步 | 看什么 | 判「到这一步为止」的标志 |
|---|---|---|
| ① | 是哪棵树 / 哪一笔：`rev` / `branch` / `tree` | 三处对得上，再往下 |
| ② | 门整体：`ok` 与每道门 `exit_code` | 找到第一道红门 |
| ③ | 该门日志尾：`gates/logs/<门名>.log` | 拿到一句真错误（不是「失败」两个字） |
| ④ | 这道门的输入有没有变 / 有没有被复用 | 输入变了 ⇒ 必须 `--no-reuse` 重跑 |
| ⑤ | 台账 / 队列 / 封存是否与 git 一致 | `wb_verify` + `wb_reconcile` 都无 FAIL |

## 自查

1. 我引用的每条读数都带**命令**（能重跑），不是「我看过」。
2. 我报的树 / 提交 / 分支是同一组。
3. 我没为了让红变绿去改判据、加豁免、手改门产物。
4. 边界（没做到 / 没跑 / 证据缺失）我在回报里如实写了。

> 三值判决、空集不算过、复用规则：判据在 `scripts/run_gates.py` 与门表；台账与封存的判据在 `tools/pool/`。
