---
name: pipe-init
description: 用 pipe init 把管线骨架（pipeline.toml + gates.d/ + 卡模板 + 台账壳 + 钉子树）铺到一个目录。当你要在空目录起一个新项目、或把骨架铺到别处做对照时用。
---

# pipe-init —— 铺骨架

把一套能直接跑 `pipe gate` 的最小项目铺到目标目录。

## 什么时候用

- 在一个**新目录**开一个新项目，要一套「配置 + 门 + 卡模板 + 台账壳 + 钉子树」。
- 想把框架自带的 `minimal` 模板骨架铺到别处，做第二个项目的起点或做对照。

## 什么时候别用

- 目标目录**已经有**你的项目文件 —— `pipe init` 不合并、不覆盖；已存在就退 `5`，要覆盖必须显式 `--force`，而 `--force` 的目标还必须在仓内（否则退 `4`）。
- 你只是想**跑门**，不是想铺骨架 —— 那用 `pipe-gate`。
- 你想改**已有项目**的配置 —— 那要手改它自己的 `pipeline.toml`，不是重铺；重铺会把你改过的东西盖掉。

## 前置检查

1. `python` 能起来（本框架只用标准库，不用先装包）。
2. 目标目录存在（`--dir` 不填就是当前目录）。
3. 干跑一次帮助，看得到参数就是能跑：`python framework/cli/main.py init --help`。

## 真命令

没装包时（在本仓根，或把路径换成 CLI 的绝对路径）：

```bash
python framework/cli/main.py init --dir <目标目录>
python framework/cli/main.py init --dir <目标目录> --template minimal
python framework/cli/main.py init --dir <目标目录> --force        # 目标必须在仓内
```

装成命令后（先 `pip install -e framework`）：

```bash
pipe init --dir <目标目录>
```

加 `--json` 拿结构化清单（`files` 清单 + `count`）。

## 怎么读结果

> 每条口径末尾的「复核」都指着**能重跑的那个脚本**——结论别靠人眼，跑它。

- 退出码 `0`：铺好了 —— 人读输出有一行「铺出 N 个文件到 …」，`--json` 里有 `files` 清单和 `count`（复核 `python -X utf8 framework/cli/main.py init --json`）。
- 退出码 `5`：**前置条件缺失** —— 目标已存在且没给 `--force`（或模板缺失）。这是「可修了再来」，不是坏了（复核 `python -X utf8 framework/cli/main.py init --json`）。
- 退出码 `4`：**被策略拒绝** —— `--force` 的目标在仓外（越界）（复核 `python -X utf8 framework/cli/main.py init --json`）。
- 退出码 `2`：用法 / 参数错（复核 `python -X utf8 framework/cli/main.py init --help`）。
- 拿不准时看 `--json` 的 `error.message`；完整退出码表见 `pipe --help` 尾部（复核 `python -X utf8 framework/cli/main.py init --json`）。

## 常见错与处置

| 现象 | 真因 | 处置 |
|---|---|---|
| 退 `5`，说目标已存在 | 没给 `--force` 且目录非空 | 换空目录；确认要覆盖再加 `--force` |
| 退 `4`，`--force` 被拒 | 目标在仓外 | 目标放仓内，或去掉 `--force` 只铺空目录 |
| 提示找不到 `pipe` 命令 | 没装包 | 用 `python framework/cli/main.py init …` 直接跑 |
| 铺完 `pipe gate` 跑不起来 | 没 `cd` 进铺出的目录，或模板没铺全 | `cd` 过去再跑；先看 `pipeline.toml` 在不在 |

> 哪些文件该铺、幂等语义（第二次拒绝或逐字节相同）是**判据**，在框架库里（`framework/src/framework/scaffold.py`）。本 skill 只讲怎么用，不复述判据。
