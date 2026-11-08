# pipe-takeover —— 本仓绑定（仓无关骨架之外的那一层）

> **这一页只放「这个仓是什么样」**：勘察器落在哪、骨架铺几个文件、卡登记进哪份队列、
> 快照与分支怎么叫、本仓实测读数、历史证据挂在哪。
> `SKILL.md` 的动作顺序与读法换仓也不变；换一个仓用这套技能，**只换这一份**，别改 `SKILL.md`。
> 本仓 = `program/engineering`（`pipe` 框架 + timeflow 实现），分支 `line/impl-v1`。

## 本仓是哪种形态

- **A 类（已有完整管线）**：本仓自己就是被接管方向的另一端 —— 有队列、台账、门表、判据。
  用本仓的勘察器看本仓，`kind = A`、`strict_ok = true`、`strict_problems = []`。
  所以「接管本仓」这件事不存在；本技能只用在本仓**外面**的目录。
- **两套入口并存**：框架层 `python -X utf8 framework/cli/main.py`（子命令 `init / gate / doctor / card /
  claim / land / ledger / trace`）与本仓工作链 `python -X utf8 tools/wb_*.py`。本仓根**没有** `pipeline.toml`，
  所以主路径上一律走 `wb_*`；框架 CLI 只在「对方仓铺了骨架之后、在对方仓里」用。
- **工具根与数据根已分开**（`tools/pipe_root.py`，卡 A326）：同一份 `tools/` 可以服务别的仓，
  设 `PIPE_DATA` 指向对方的数据根即可 —— 但**接管**仍然只加文件，不是搬工具。

## 勘察器与它的输出

```bash
python -X utf8 tools/wb_takeover.py --root <目录> --json            # 5 键：ok/root/kind/readings/mapping_hints
python -X utf8 tools/wb_takeover.py --root <目录> --strict --json   # 7 键，多 strict_ok/strict_problems
```

- `--root` 必填（目录不存在 ⇒ 退 2 + `{ok:false, error}`）。
- `readings` 是本仓认的八条信号，名固定：`own_pipeline_config` / `own_trio` / `foreign_framework` /
  `tests` / `ci` / `src` / `content` / `agents_md`；每条形如 `{name, ok, detail}`（**不是** `class`/`signals`）。
- `strict_problems` 在本仓会对两类情况点名：D 类但没有任何别家框架标记、以及缺 `AGENTS.md`
  （`tools/wb_takeover.py` 的 `_agents_md_reading`：`AGENTS.md` 在 / 缺 `AGENTS.md`（README 不算））。
- 定类优先级与逐条口径见 [四类判据](classify.md)。

## 骨架铺几个文件

- `framework/templates/minimal` 受控文件恰 **14** 个（2026-11-08 `git ls-files framework/templates/minimal | wc -l`
  ⇒ 14；`find -type f` 会多数出 5 个 `__pycache__/*.pyc`，别拿它当读数）。
- 顺序与幂等：目标非空且没给 `--force` ⇒ 退 5；给了 `--force` 且目标在仓内 ⇒ 覆盖，仓外 ⇒ 退 4
  （`framework/src/framework/scaffold.py`：`dst.exists() and not force` ⇒ `ScaffoldError(…, 5)`；
  `--force` 且 `dst` 不在 `repo_root` 内 ⇒ `ScaffoldError(…, 4)`）。
- 清单随模板变 —— 真源是模板目录，要当下清单就跑一次 `--json`。

## 卡登记进哪份队列

- 目标目录在**本仓内**：卡进 `docs/workbacklog.toml` 的 `[[cards]]`，规格进 `复盘/卡/卡<号>-<短名>.md`。
- 目标目录在**本仓外**：卡进对方骨架的 `backlog.toml`，规格按对方模板写；框架层口径见
  [骨架清单](../../pipe-init/references/scaffold.md)。
- 落地：本仓内走 `python -X utf8 tools/wb_land.py --card <号> --tree <卡树> --task <台账号> …`；
  仓外只跑对方那一道门，不要指望本仓的落地链。

## 回滚点与隔离

- 快照 ref 形状：`refs/snapshots/<段或卡>-<%Y%m%d-%H%M%S>`（`tools/pool/snapshot.py` 现拼）。
- 接管自己的回滚点用 tag：`git -C <目录> tag snap/pre-takeover`（比裸 rev 好找，能删）。
- 隔离分支命名本仓没有硬约定；**判据**是「不在对方主干上直接提交」，名字自取。

## 入口文档与历史证据

- 入口文档（`AGENTS.md`）的分节与「命令必须真跑过」口径：[入口文档写法](agents-md.md)。
- 「为什么顺序不能换」「哪类错误踩过」的人类版在同目录上一级的 `NOTES.md`（不是 `references/` 里的一份）。
- 六条禁止：[限制清单](limits.md)。映射反例：[映射表](mapping.md)。
