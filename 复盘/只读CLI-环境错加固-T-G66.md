# 只读 CLI · 环境错加固：把"打不开"翻译成人话（T-G66）

> 触发：用户 2026-09-25 问「**有要修复的吗**」。落地 T-G64（`d5c820a`）之后我没有等下一张卡，
> 而是**按"用户会怎么用错"把刚做的东西探了一遍** —— 探出 3 处真缺陷。
> 教训进 `复盘/视觉线地图.md` §6。

---

## 1. 我怎么找的（不靠回想，靠"按错法用一遍"）

跑了一遍现成的诊断尺子（`route_ui_gap` / `squeeze_scan` / `ui_text_scan` / `style_audit`），
再拿最新那张卡（只读 CLI）去撞**四类环境错**：库不存在、库是目录、库是坏文件、命令表语法坏。

| # | 现象（探之前） | 性质 |
|---|---|---|
| A | `timeflow today --db <不存在的路径>` → **静默建了一个空库**，回「0 分钟 / 0 项」，**exit 0** | **真缺陷**（只读命令有文件副作用 + 打错路径会看到"看起来正常"的假数据） |
| B | `--db <目录>` / `--db <坏文件>` → **Python 栈**（`sqlite3.OperationalError` / `DatabaseError`），`exit 1` | **真缺陷**（承诺了稳定错误码，却把栈丢给用户） |
| C | `timeflow help today` → 只打总目录，无视 `today` | 小缺陷（一个卖点是"自描述"的命令行，问"这条怎么用"答不上来） |
| D | 命令表 TOML 语法坏 → **Python 栈**（`tomllib.TOMLDecodeError`） | **真缺陷**（这张表在本项目里**写坏过 9 次**） |

诊断尺子那边**没有新东西**：`squeeze_scan` 0 处；`route_ui_gap` 剩 9 条路由全是"按设计不给界面"
（AI 接口 / health / 已弃用那条）；`ui_text_scan` 剩的是 T-G57 已知的长文案尾巴；
`style_audit` 报的「圆角 4 档」里那个 `0` 是**手机底栏的有意复位**（工具 docstring 早写明
`0`/`50%` 仍按一档计）—— 看着像缺陷，查过是**报告口径**，不是漂移。**这一条我特意没动**：
把尺子改宽容易，改宽之后它就不再拦真漂移了。

## 2. 修了什么

**① 库不存在就拒绝工作**（`db_missing`，退 3）：`cli/call.py` 在调边界前先看
`Path(db_path).is_file()`。**"只读"不只是"不发写请求"，还包括不留副作用** ——
一个只会读的命令不该在磁盘上留下一个文件，更不该让"打错路径"看起来像"我这周什么都没干"。
（顺带这个判断把"`--db` 指到目录"也一起挡了。）

**② 库打不开翻译成稳定码**（`db_unopenable`，退 3）：★ 第一版我只兜了 `create_app()` 那一步，
**实测照样漏** —— 库是**懒连接**的（`storage/db.thread_local` 在第一次用到时才真打开），
"文件不是数据库"这类错是在**请求里**才炸出来的。所以 try 必须把
`asyncio.run(_exchange(...))` 一起罩住。

**③ 判"环境坏"还是"代码 bug"**（`_is_environment_error`）：只把 `OSError` 与 `sqlite3.*`
当环境错，**其余原样抛出** —— 代码 bug 不该被伪装成"你的库有问题"（那会把排查方向带偏）。
判定用 `type(exc).__module__.split(".")[0] == "sqlite3"` 而**不是 import sqlite3**：
CLI 这一层不许碰数据库（有源码级 import 护栏钉着），这里只翻译错误、不开库。

**④ 命令表语法坏**（`table_broken`，退 3，带 `tomllib` 原文的行列号）；
顺带 `scripts/check_commands.py` 也改成**报一条硬冲突**而不是抛栈 —— 跑门的人要的是那一行，
不是一段 traceback。

**⑤ `help <命令>` 认命令**：`timeflow help today` 与 `timeflow today --help` 现在同一件事。

**⑥ 自描述里补 `errors`**：退出码只说"退 3"，而退 3 下面现在有五件不同的事
（`db_missing` / `db_unopenable` / `table_missing` / `table_broken` / …）；
脚本与 AI 要能分辨，所以把**稳定机器码 → 退出码**的映射也放进 `commands --json`。

## 3. 验证

| 层 | 证据 |
|---|---|
| 行为（`tests/test_cli_line.py` +5） | 库不存在 → 退 3 **且断言"一个文件都没留下"**；`--db <目录>` → 退 3；坏库 → `db_unopenable` **且 `"Traceback" not in err`**；坏表 → `table_broken` **且 detail 里有行号**；`help today` 与 `help` 两种写法 |
| 检查器（`tests/test_check_commands.py` +1） | 坏表 → 门禁报「命令表语法坏了」的硬冲突、退 1（不是崩溃） |
| 自描述 | `commands --json` 的 `errors` 六个码与退出码一一对应（测试钉住集合） |
| 手工 | 四类错各跑一遍真命令，确认退 3 与那句人话（见 §1 表） |

## 4. 边界（不许假装）

- **"库坏了"只翻译不修**：CLI 不回退、不自动换成备份 —— 那是设置页「备份与恢复」的事，
  命令行只把路指过去（错误消息里就写着去哪）。
- **"库不存在"是个硬门槛**：第一次用的人得先开一次窗口建库。这是**有意的**：
  宁可让他看到一句"库还没有"，也不要他看到一份空账。
- **还有一类没兜**：库在、结构对，但**迁移失败**（版本比程序新）—— 那条现在是 500/异常。
  它更像"版本不匹配"而不是环境错，留给真遇到时再定（不预先发明错误码）。
- **顺手记一条环境坑**（不是产品缺陷）：`gates/diag/inspect.py` 是前几轮的临时脚本，
  名字**遮蔽标准库 `inspect`** —— 任何从该目录起跑的脚本都会 `AttributeError`（这次就撞了）。
  scratch 目录里的文件名不要用标准库的名字。

## 5. 这一卡改了哪些文件

| 文件 | 改动 |
|---|---|
| `src/timeflow/cli/call.py` | `DatabaseError`（带 code）+ `_is_environment_error` + 两处兜（建 app 与请求）+ 库存在性检查 |
| `src/timeflow/cli/table.py` | `TableBrokenError`（带 `tomllib` 原文） |
| `src/timeflow/cli/main.py` | 两个环境错 → 退 3；`ERROR_CODES` 进自描述；`help <命令>` 认命令 |
| `scripts/check_commands.py` | 坏表 → 报硬冲突（带行列），不抛栈 |
| `tests/test_cli_line.py` / `tests/test_check_commands.py` | +5 / +1 |
