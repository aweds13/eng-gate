---
name: pipe-forensics
description: 出事了从已落盘的证据里查——用 pipe gate 的产物、金丝雀自检、台账对账、封存指纹定位哪一步坏了。当门红了、判决说不清、或要复盘一次失败时用。
---

# pipe-forensics —— 出事了从证据里查

出事了（门红 / 判决说不清 / 复现不了）时，**从已经落盘的证据查**，不要靠回忆。

## 什么时候用

- 门红了，要定位**是哪道门、哪一步**。
- 判决是 `inconclusive`，要分清「是空集、还是根本没跑」。
- 要核对「这次的结论是不是**这一棵树**的结论」。
- 要复盘一次失败：先看留痕，再看代码。

## 什么时候别用

- 只想跑一次门看红没红 —— 用 `pipe-gate`。
- 想验证**门本身还活着** —— 那是金丝雀自检 `pipe doctor`，它查的是判据有没有退化成注释，不是查你的代码。
- 想让红变绿而**改判据** —— 那是改库 / 改门，是另一件事，不是「查证据」。

## 前置检查

1. 先知道证据落在哪：`[paths].gates_state`（模板默认 `gates/last.json`）、`[paths].logs_dir`、`[paths].evidence_dir`。
2. 手边有 `pipeline.toml`（否则用 `--config` 指）。
3. 手边有**出事那一棵树**（要按它记的 `rev` / `tree` 对）。

## 真命令

```bash
# 1) 这次的门结论（结构化，字段稳定）
python framework/cli/main.py gate --config <pipeline.toml> --json

# 2) 门还活着吗（金丝雀自检：每道门真跑一遍它的反例钉子）
python framework/cli/main.py doctor --config <pipeline.toml> --json

# 3) 逐条对台账证据（--missing 只回报失败的条目，最省眼睛）
python framework/cli/main.py ledger check --config <pipeline.toml> --missing

# 4) 给当前提交树打封存指纹（用来核对"结论属于哪棵树"）
python framework/cli/main.py trace seal --reason <为什么改封存>
```

装成命令后：`pipe gate …` / `pipe doctor …` / `pipe ledger check …` / `pipe trace seal …`。

## 怎么读结果

- **先看整体判决，再看每道门那一行**：名字 → 运行状态 → 判决 → exit → 秒数 → 是否复用。
- ★ **`inconclusive`（判不了）与 `not-run`（没跑）是两种不同的"非通过"**：前者是空集 / 判不了，后者是运行时依赖缺失根本没跑。**两者都不算通过**，但查法不同 —— 前者补样例，后者补依赖。
- `doctor`：看 `all_have_teeth` 与每门的 `has_teeth`；有门失效（判据退化成注释）会退 `1`。它查的是**门**，不是你的代码。
- 某门带 `[复用]`：这一门是**增量执行读缓存**，不是现在重跑的；要当下的结论就用 `--only <门>` 重来。
- **封存指纹**：`trace seal --json` 给 `tree` / `rev` / `algorithm`；拿它和失败报告里的 `rev` 对，判断「结论是不是这一棵树的」。
- 台账对账：`ledger check --missing` 只回报失败条目。
- ★ 当前实现里 `ledger check` 与 `trace seal` 也是**薄壳**：调用即退 `5`（未实现）。这**不是**「台账没问题」，是「这一层还没建」—— 别读反。

## 常见错与处置

| 现象 | 真因 | 处置 |
|---|---|---|
| 判决 `inconclusive` | 空集：没收集到样例 | 补样例或修收集器；**别当绿** |
| 判决 `not-run` | 运行时依赖缺失 | 补依赖；阻断门会把它拖成 `inconclusive` |
| 某门带 `[复用]` | 读的是缓存，不是当下重跑 | 用 `--only <门>` 重跑；pytest 类恒 `never` 不复用 |
| `doctor` 退 `1` | 有门失效（钉子不再咬） | 修那道门的判据 / 钉子；不是修业务代码 |
| `ledger check` / `trace seal` 退 `5` | 薄壳未实现 | 这一层还没建；**不是"没问题"** |
| 复现不了 | 结论属于**另一棵树** | 用 `tree` / `rev` 对齐后再读 |

> 三值判决、「空集绝不绿灯」、增量执行的**判据**都在库与门里（`framework/src/framework/gates.py`、`framework/PIPELINE.md`）。本 skill 只教怎么从证据里读，不复述判据。
