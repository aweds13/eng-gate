---
name: pipe-gate
description: 用 pipe gate 按 pipeline.toml 跑门，并读懂三值判决（pass / fail / inconclusive）。当你要判断现在这棵树过不过门、或某道门红没红时用。
---

# pipe-gate —— 跑门禁并读懂三值判决

## 什么时候用

- 改动之后，要判断「现在这棵树过不过它自己的门」。
- 想只看某几道门（`--only`），或想看机器可读的同一份结果（`--json`）。

## 什么时候别用

- 想**铺骨架**：用 `pipe-init`。
- 想验证**门本身还活着**（判据没退化成注释）：那是金丝雀自检 `pipe doctor`，不是 `pipe gate`。
- 想**集成发布**：跑门只是整条链里的一步；整条链用 `pipe-land`。

## 前置检查

1. 有 `pipeline.toml`；默认读 `$PIPELINE_TOML` 或 `./pipeline.toml`，否则用 `--config` 指。
2. 帮助能起来：`python framework/cli/main.py gate --help`。
3. 跑道与资源：门可能很重（真机门要起浏览器 / 起服务）；同一时间**只跑一个**重门禁，别并发抢端口。

## 真命令

```bash
python framework/cli/main.py gate --config <pipeline.toml>
python framework/cli/main.py gate --config <pipeline.toml> --only <门名> <门名>
python framework/cli/main.py gate --config <pipeline.toml> --json
```

装成命令后：

```bash
pipe gate --config <pipeline.toml> --json
```

## 怎么读结果

> 每条口径末尾的「复核」都指着**能重跑的那个脚本**——结论别靠人眼，跑它。

- **整体判决**：输出第一行「门禁总判决：<pass|fail|inconclusive>（绿 / 非绿）」（复核 `python -X utf8 framework/cli/main.py gate --json`）。
- **每道门一行**：`名字 / 运行状态 / 判决 / exit / 秒数 / 是否复用`（复核 `python -X utf8 framework/cli/main.py gate --json`）。
- ★ **三值里的 `inconclusive` 不等于通过**：它的意思是「判不了」（例如一条样例都没收集到）。看到它**不许当绿** —— 下一步要么补样例、要么停手报清楚（复核 `python -X utf8 framework/cli/main.py gate --json`）。
- ★ **`not-run` 是运行状态，不是判决**：运行时依赖缺失就没跑；阻断门 `not-run` 会把总判决折成 `inconclusive`。别把「没跑」读成「过了」（复核 `python -X utf8 framework/cli/main.py gate --json`）。
- 结构化结果落进 `[paths].gates_state`（模板默认 `gates/last.json`）；`--json` 是它的 stdout 版，字段稳定（复核 `python -X utf8 framework/cli/main.py gate --json`）。
- 退出码：`0` 全绿 / `1` 有门红 / `2` 用法错 / `3` 资源闸拒跑 / `6` 被外部打断（可续跑）/ `124` 单道门硬超时（复核 `python -X utf8 framework/cli/main.py gate --json`）。

## 常见错与处置

| 现象 | 真因 | 处置 |
|---|---|---|
| 找不到配置 | 没 `--config`，且默认路径没有 `pipeline.toml` | 传 `--config`，或设 `PIPELINE_TOML` |
| 退 `3` | 资源闸（内存 / 并发不够） | 腾资源重跑；**别把闸关掉当通过** |
| 某门 `inconclusive` | 空集：没收集到样例 | 补样例或修收集器；**别当绿** |
| 某门 `not-run` | 运行时依赖缺失 | 补依赖；阻断门会把它拖成 `inconclusive` |
| 退 `124` | 单道门硬超时 | 看那门的日志定位；别改小超时糊过去 |
| 某门显示 `[复用]` | 读的是缓存，不是现在重跑的 | 用 `--only <门>` 重跑要当下的结论 |

> 三值判决与「空集绝不绿灯」的**判据**在库与门里（`framework/src/framework/gates.py`、`framework/PIPELINE.md`）。本 skill 只说怎么读，不复述判据。
