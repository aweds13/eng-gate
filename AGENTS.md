# AGENTS.md —— 工作区入口（`program/engineering`）

> 这个目录是 **`pipe` 框架**（工作项/门禁/台账/派活器）。本文件只做**路由**，
> 不重复各项目自己的规则。

## 活在哪，先看哪

| 你要干的活 | 先读 |
|---|---|
| **OpenMAIC 二开**（`../OpenMAIC`） | **`../OpenMAIC/AGENTS.md`** —— 维护手册：改哪一层、文件地图、证据命令、坑<br>再看 `../OpenMAIC/复盘/新窗口交接卡.md` —— **当前状态 + 新窗口开场白** |
| `pipe` 框架本身的门禁 / 派活 / 台账 | `skills/README.md`（分工判据）+ `复盘/新窗口交接卡.md`（当前状态） |
| **接手一个已存在的项目 / 新起一个项目** | `skills/pipe-takeover/`（接手）或 `skills/pipe-new/`（新起）：**第一步**先跑 `python -X utf8 tools/wb_takeover.py --root <目录> --strict`（判据不足会退 2 —— 不许猜类别） |
| 接别的 harness | `skills/GLUE-harness.md` |
| DSH 技能 / 插件的写法 | `DSH-技能与插件开发参考.md` |

## 长命令怎么跑（免得看着像卡死）

**禁止**把长命令用管道截断后再跑，例如 `python tools/wb_land.py … | tail -3`：
管道要等进程结束才吐一次，中途后台作业读不到任何输出，看起来像卡死。

**也禁止** `sleep N` 硬等：长任务起后台作业，等运行时给完成通知，中途要看进度就
`tail -n 20 <日志>` 或读作业输出（瞬间返回）。
**也禁止** `job_output(wait: true)` 长时间阻塞：软工预设已把 `waitTimeoutMs` / `maxWaitTimeoutMs` 压到 1 秒，
长等会被截断并回 `running` —— 等完成通知，或用 `job_output`（不带 wait）读增量 + `tail -n 20 <日志>`。

**强制检查**（写法不合规直接拦下）：

```bash
python -X utf8 tools/cmd_guard.py --cmd '<你要跑的命令>'
```

**一律**用带日志的跑法（逐行落盘 + 定时心跳，后台输出增量可读）：

```bash
python -X utf8 tools/run_logged.py --log gates/diag/land-A302.log -- \
    python -X utf8 tools/wb_land.py --card A302 ...
```

要复核进度就读日志 `tail -n 20 gates/diag/land-A302.log`，别再套 `| tail`。

## 两条本地约定（免得踩）

- `skills/` 里**只放操作知识**（顺序、前置检查、常见错、该看哪个产物）。
  判据放库/门里 —— **删掉整个 `skills/` 目录，框架仍要完整可用**。
- `harness.toml` 是 `harness/` 复制体与本项目之间的**唯一胶水**。
  改它之前先读它自己的文件头注释（键的口径写在那里）。
