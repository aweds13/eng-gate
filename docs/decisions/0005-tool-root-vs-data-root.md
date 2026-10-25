# 0005 工具根与数据根切分：一份 tools/ 能服务别的仓

Status: Accepted
Date: 2026-10-24
Supersedes:
Superseded-by:
来源: 台账 A326 / T-AG441；`复盘/卡/卡A326-工具根与数据根切分.md`；`tools/pipe_root.py`

## 背景与问题

`tools/*.py` 一直用 `Path(__file__).resolve().parent.parent` 当仓库根 —— 那等于说
「根 = 我躺的那棵树」。于是**工具住在哪个仓**与**账本 / 门禁 / 卡规格住在哪个仓**被绑死：
同一份 `tools/` 想服务另一个仓（工具复用、数据自分家的项目）时，读的仍是工具自己那棵树的账。

## 候选方案

A 给每个入口加 `--root` 参数（不改目录结构，但调用点漏一个就静默读错仓）。

B 两个根显式切分：**工具根**管「import 什么」，**数据根**管「读谁的账」，
默认在主树里两根同值，所以不传参数时行为逐字不变。

## 决定

选 B，落点 `tools/pipe_root.py`：

- `home_root()`：`PIPE_HOME` 或 `tools/` 的上一级，只用来 import 判据、起子工具，不读账本；
- `data_root()`：显式参数 > `PIPE_DATA` > 当前目录像数据根（有 `docs/workbacklog.toml` /
  `docs/traceability.toml` / `gates/diag`）> 工具根，管台账、`gates/` 产物、`src/`、门命令 cwd。

放弃 A 的代价：多了一个「两个根可能不同」的概念要解释；换来的是换仓不用逐个调用点改。

## 把握程度

medium —— 有 `tests/test_pipe_root.py` 的钉子（`PIPE_DATA` 指到别的仓时 `wb_plan` 读那个仓的队列），
但还没在真实的第二个仓上长期跑过。
