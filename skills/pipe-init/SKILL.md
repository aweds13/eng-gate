---
name: pipe-init
description: 把管线骨架（pipeline.toml + gates.d/ + 卡模板 + 台账壳 + 钉子树）铺到一个空目录。当你要在新目录起一个能直接跑门禁的项目、或把同一套骨架铺到别处做对照时用；铺什么、算不算幂等在脚手架库与门里。
---

# pipe-init —— 铺骨架

铺出来的是一个**能直接跑门禁的最小项目**，不是把当前仓库复制一份。

★ **框架层 vs 本仓工作链（两条路，别混）**：

| | 框架层（本技能） | 本仓工作链 |
|---|---|---|
| 入口 | 框架 CLI 的 `init`（下面的命令） | `python -X utf8 tools/wb_*.py` |
| 需要什么 | 铺出来的 `pipeline.toml` + `gates.d/` | 本仓根 `scripts/run_gates.py`（门表在 `gates/defs/`，按语言/产品/契约分模块里） |
| 用在哪 | 新目录要一套自己的门与骨架 | 在本仓内开卡 / 建树 / 落地 |
| 谁管 | 本技能 | `pipe-new`（起链）、`pipe-card` / `pipe-gate` / `pipe-land`（日常） |

本技能的 CLI 命令**只在框架层成立**：它要求目标目录里有一份 `pipeline.toml`。本仓根没有这份配置，
所以本仓主路径上一律 `wb_*`，别把这里的命令当成本仓的门。

## 什么时候用

- 在一个**新目录**开新项目，要一套「配置 + 门 + 卡模板 + 台账壳 + 钉子」。
- 想把 `minimal` 模板铺到别处，做第二项目的起点或做对照实验。

## 什么时候别用

- 目标目录**已经有**你的项目文件 —— 它不合并、不覆盖；已存在就退 `5`，要覆盖得显式 `--force`。
- 只想**跑门**：用 `pipe-gate`。
- 想改**已有项目**的配置：手改它自己的 `pipeline.toml`；重铺会把你改过的东西盖掉。
- 想用 `--force` 往仓外铺：`--force` 的目标必须在仓内，仓外退 `4`。

## 前置检查

1. `python` 能起来（本框架只用标准库，不必先装包）。
2. 目标目录**为空或不存在**（`--dir` 不填就是当前目录）。
3. 先看帮助确认参数面：`python -X utf8 framework/cli/main.py init --help`。
4. 想知道会铺出哪些文件：见 [骨架清单](references/scaffold.md)（真源是模板目录，不是那份清单）。

## 真命令

```bash
# 没装包时（本仓根，或把路径换成 CLI 绝对路径）
python -X utf8 framework/cli/main.py init --dir <目标目录>
python -X utf8 framework/cli/main.py init --dir <目标目录> --template minimal
python -X utf8 framework/cli/main.py init --dir <目标目录> --force      # 目标必须在仓内

# 机器可读：--json 是**全局**开关，要写在子命令前面
python -X utf8 framework/cli/main.py --json init --dir <目标目录>
```

装成命令后（先 `pip install -e framework`）：`pipe init --dir <目标目录>`。

## 怎么读结果

- 铺成功：退 `0`，人读输出一行「铺出 N 个文件到 …」；结构化清单用 `python -X utf8 framework/cli/main.py --json init --dir <目标目录>`（`files` 清单 + `count`）。
- 退 `5`：前置条件缺失（目标已存在且没给 `--force`，或模板缺失）——「可修了再来」，不是坏了；同样用 `python -X utf8 framework/cli/main.py --json init --dir <目标目录>` 读 `error.message`。
- 退 `4`：被策略拒绝（`--force` 的目标在仓外）；用 `python -X utf8 framework/cli/main.py --json init --dir <目标目录>` 读 `error.message` 确认。
- 退 `2`：用法 / 参数错；用 `python -X utf8 framework/cli/main.py init --help` 对参数面。
- 退出码全表（`0/1/2/3/4/5/6/7/124` 各自含义）：`python -X utf8 framework/cli/main.py --help` 尾部那一张。

## 常见错与处置

| 现象 | 真因 | 处置 |
|---|---|---|
| 退 `5`，说目标已存在 | 没给 `--force` 且目录非空 | 换空目录；确认要覆盖再加 `--force` |
| 退 `4`，`--force` 被拒 | 目标在仓外 | 放仓内，或去掉 `--force` 只铺空目录 |
| 提示找不到 `pipe` 命令 | 没装包 | 用 `python -X utf8 framework/cli/main.py init …` |
| `--json` 报 `unrecognized arguments` | 它是**全局**开关，写在子命令后面了 | 写成 `main.py --json init …` |
| 铺完跑门禁失败 | 没 `cd` 进铺出的目录，或模板没铺全 | `cd` 过去再跑；先看 `pipeline.toml` 在不在 |

## 复盘缺口（框架两条总纲）

- （缺口 FW1）事实层是唯一真源：AI 只写「做了什么」的事实回报，结论与产物由库/门产出，不许自证 —— 铺出的骨架里台账与门产物都由工具写；新接一条线时先问「事实谁发、结论谁算」。证据：`复盘/事实层架构设计复盘.md`、`复盘/第0步实施-事实层落地.md`、`复盘/框架-术语表与契约.md`
- （缺口 FW2）框架要能整体提升为独立仓：无隐藏本地依赖，提升前先跑抽取清单，先抽后搬 —— 往骨架里加东西时别引入只在本仓成立的路径；提升动作先跑抽取清单再搬。证据：`复盘/框架-独立仓提升.md`、`复盘/卡/卡181-框架独立仓与参与管线.md`、`复盘/卡/卡178-框架骨架设计.md`

## 铺出来的是什么

| 落点 | 作用 |
|---|---|
| `pipeline.toml` | 顶层配置（门表、路径、卡段） |
| `gates.d/` | 各道门的配置分片 |
| `card-template.md` + `backlog.toml` | 卡模板与队列壳 |
| `ledger.toml` + `invariants.toml` | 台账壳与不变量壳 |
| `src/` + `tests/` | 一个最小示例（含一条钉子样例） |
| `README.md` + `docs/README.md` + `.gitignore` | 项目壳 |

逐条清单见 [骨架清单](references/scaffold.md)。

## 自查

1. 目标目录在铺之前是空的（或我**明确**接受 `--force` 的覆盖后果）。
2. 退 `0` 且 `count` 与目录里实际文件数一致。
3. `cd` 进目标目录后 `pipeline.toml` 在，门禁能起来。
4. 我没在仓外 `--force`，也没把已有项目重铺。

> 铺哪些文件、什么算幂等（第二次拒绝还是逐字节相同）：判据在 `framework/src/framework/scaffold.py` 与 `framework/templates/`，本技能只讲怎么用。
