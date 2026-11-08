# pipe-init —— 本仓绑定（仓无关骨架之外的那一层）

> **这一页只放「这个仓是什么样」**：CLI 落在哪、脚手架库与模板在哪、本仓根有没有 `pipeline.toml`、
> 铺出几个文件、框架两条总纲缺口的证据挂在哪。
> `SKILL.md` 的动作与读法换仓也不变；换一个仓用这套技能，**只换这一份**，别改 `SKILL.md`。
> 本仓 = `program/engineering`（`pipe` 框架 + timeflow 实现），分支 `line/impl-v1`。

## 本仓是哪种形态

- **本仓根没有 `pipeline.toml`**（`ls pipeline.toml` ⇒ No such file）。框架 CLI 的 `gate` / `card` /
  `land` / `ledger` / `trace` 子命令都读它，所以在本仓主路径上**跑不起来**；本仓日常走
  `python -X utf8 tools/wb_*.py`（工作链）。本技能只在**别的目录**（或做对照实验时的临时目录）里用。
- **框架就在本仓里**：CLI = `framework/cli/main.py`，库 = `framework/src/framework/`，模板 =
  `framework/templates/`。没装包时用 `python -X utf8 framework/cli/main.py …`；装了包
  （`pip install -e framework`）才有 `pipe` 这条命令。
- **全局参数必须写在子命令前**（`--config` / `--json` / `--version`）。写成
  `main.py gate --config pipeline.toml` 实测 rc=2，原文
  `pipe: error: unrecognized arguments: --config pipeline.toml`；正确式
  `main.py --config pipeline.toml gate` 在铺出的骨架里 rc=0，输出 `门禁总判决：pass（绿）`。
  `main.py --help` 明写 `--config CONFIG  pipeline.toml 路径（默认读 $PIPELINE_TOML 或 ./pipeline.toml）`。

## 脚手架库与模板在哪

- 判据（铺哪些文件、什么算幂等）：`framework/src/framework/scaffold.py`。两条实测口径：
  `dst.exists() and not force` ⇒ `ScaffoldError(f"目标已存在：{dst}（未给 --force，拒绝覆盖 —— 保护用户改动）", 5)`；
  `--force` 且目标不在 `repo_root` 内 ⇒ `ScaffoldError(…, 4)`。
- 模板：`framework/templates/minimal/`。受控文件恰 **14** 个
  （2026-11-08 `git ls-files framework/templates/minimal | wc -l` ⇒ 14）。★ 用 `find -type f` 会数出 19 ——
  多出的 5 个是 `__pycache__/*.pyc`，别拿它当读数。
- 逐条清单与退出码表：[骨架清单](scaffold.md)。

## 本仓实测读数（数字会漂，口径不能漂）

- `python -X utf8 framework/cli/main.py init --help`（2026-11-08）⇒
  `usage: pipe init [-h] [--template TEMPLATE] [--dir DIR] [--force]`，三个参数面就这些。
- `python -X utf8 framework/cli/main.py --help` 尾部「退出码（唯一一张表）」原文：
  `0 通过` / `1 判据不通过（门红 / 审计红）` / `2 用法 / 参数错` / `3 资源闸拒跑` /
  `4 被策略拒绝（越界 / 未授权）` / `5 前置条件缺失（文件 / 段 / 键不存在；含「薄壳未实现」）` /
  `6 被外部打断（可续跑）` / `7 资源全挂，停止` / `124 单道门硬超时`，并注明
  `（126 / 127 / 128+N 由 shell / 信号层发，我们永不发。）`

## 铺完之后在骨架里跑门

```bash
cd <目标目录>
python -X utf8 <本仓>/framework/cli/main.py --config pipeline.toml gate
```

- `--config` 在子命令**前**（见上「本仓是哪种形态」的实跑读数）。也可以不写 `--config`：
  在目标目录里跑时默认读 `./pipeline.toml`（或 `$PIPELINE_TOML`）。
- 铺出来的骨架里那道样例门是 `tests`，产物与门分片在 `gates.d/`。
- 本仓根跑同一条命令会退 5（找不到 `pipeline.toml`）—— 那是**预期**，不是骨架坏了。

## 框架两条总纲缺口（历史证据层，不是判据）

这一节是**历史证据**：读它为了知道「为什么骨架里那些东西是工具写、不是人写」，别当判据用。

- （缺口 FW1）事实层是唯一真源：AI 只写「做了什么」的事实回报，结论与产物由库/门产出，不许自证 ——
  铺出的骨架里台账与门产物都由工具写；新接一条线时先问「事实谁发、结论谁算」。
  证据：`复盘/事实层架构设计复盘.md`、`复盘/第0步实施-事实层落地.md`、`复盘/框架-术语表与契约.md`
- （缺口 FW2）框架要能整体提升为独立仓：无隐藏本地依赖，提升前先跑抽取清单，先抽后搬 ——
  往骨架里加东西时别引入只在本仓成立的路径。
  证据：`复盘/框架-独立仓提升.md`、`复盘/卡/卡181-框架独立仓与参与管线.md`、`复盘/卡/卡178-框架骨架设计.md`

## 与工作链那条路的分界

| | 框架层（本技能） | 本仓工作链 |
|---|---|---|
| 入口 | `python -X utf8 framework/cli/main.py init` | `python -X utf8 tools/wb_*.py` |
| 需要什么 | 目标目录里自己的 `pipeline.toml` + `gates.d/` | 本仓根的数据根（队列 / 台账 / 门禁产物） |
| 用在哪 | 新目录要一套自己的门与骨架 | 在本仓内开卡 / 建树 / 落地 |
| 谁管 | 本技能 | `pipe-new`（起链）、`pipe-card` / `pipe-gate` / `pipe-land`（日常） |

一句话：**目标目录里要不要一份自己的 `pipeline.toml`**。要 —— 本技能；不要 —— 工作链那条路。
