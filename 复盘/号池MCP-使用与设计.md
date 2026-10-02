# 号池 MCP：给**任意窗口的 AI** 用的一页（2026-10-02 · T-G213）

> **给谁看**：在别的 DSH 窗口 / 别的会话里接手这套外包流程的 AI。
> **一句话**：号池的 MCP 面把"派活 / 看进度 / 取消"摊成 8 个工具 —— **哪个窗口都能派活与看进度**，
> 但**跑门禁、提交、记账（收口）只有主控做**。下面写清"能碰什么、不能碰什么、东西在哪"。
> 真源仍是 `docs/workbacklog.toml`（队列）+ `gates/last.json`（门禁结论）+ `docs/traceability.toml`（台账）。

## 一、怎么接（已经接好了）

注册点（**仓库外**）：`C:/Users/example\.dsh\profiles\desktop\cordis.patch.yml` 里的 `- id: mcp-pool`：

```yaml
    - id: mcp-pool
      name: "@deepseek-ai/dsh-mcp-client"
      config:
        serverName: pool
        transport: stdio
        command: C:/Users/example\miniconda3\python.exe
        args:
          - -X
          - utf8
          - D:/repo/engineering\tools\pool_mcp.py
        env:
          PYTHONUTF8: '1'
          PYTHONIOENCODING: utf-8
          POOL_MCP_WRITE: '1'      # ★ 删掉这一行 ⇒ 只剩 6 个只读工具（写面"存在性即授权"）
        toolCallTimeoutMs: 120000
```

★ 三条**踩过的**：
1. **服务进程是会话启动时拉起的，磁盘上的 `.py` 不会热加载** —— 改完 `tools/pool_mcp.py`（或它 import 的
   `tools/pool/*.py`）要**重启 DSH / 换一个新会话**才生效。`touch` 配置文件**没用**（改内容才会重挂载，
   而且本会话里实测也没能重挂载）。
2. `args` 必须指向**主仓**那份脚本（指向卡树会读不到队列）；`ROOT` 由脚本路径自己推导，**不需要** cwd。
3. `dsh-mcp-client` 会剥掉名字含 `KEY`/`PASSWORD`/`SECRET`/`TOKEN` 的环境变量与全部 `DSH_*`
   ⇒ 要传给服务端的东西必须在 `env:` 里显式写。

## 二、八个工具

| 工具 | 干什么 | 备注 |
|---|---|---|
| `pool_plan` | 队列与冲突域：哪些卡能同批跑（现算 `wb_plan.py plan`） | 只读 |
| `job_list` | 扫 `gates/diag/wb-*.jsonl`：在跑 / 已判决 / 断了（**给判断依据**，不猜） | 只读 |
| `job_status(card)` | 一张卡现在到哪了：时间线 + 仓库状态 | 只读 |
| `job_result(card)` | 那张卡的判决 / 摘要**原文**（截断会明示总长） | 只读 |
| `lock_status` | 门禁锁：哪把、谁的、租约剩多久 | 只读 |
| `pool_models` | 号池模型白名单（批准 ∩ 可用，**读快照、不联网**） | 只读 |
| `pool_dispatch(card, tree, …)` | **派活**：干跑守卫 → 先占树 → 起工人（`--detach`，立刻返回） | ★ 要 `confirm` = 卡号 |
| `pool_cancel(card, reason)` | **取消**那张卡的工人（**先核对 pid 映像名**，不对就拒绝动手） | ★ 要 `confirm` = 卡号；`destructiveHint` |

## 三、谁可以做什么（**分工，别越界**）

| 动作 | 谁能做 | 为什么 |
|---|---|---|
| 查队列 / 看某卡到哪 / 看锁 / 看白名单 | **任何窗口** | 全只读，不改变任何状态 |
| 派活（`pool_dispatch`） | **任何窗口** | 守卫会挡下"树被占 / 冲突域相交 / 日志会覆盖 / 门禁在跑"；占位是**先占后起**，并发安全 |
| 取消（`pool_cancel`） | **任何窗口** | 只动**本机登记**里那张卡的 pid，且**先核对映像名**（`node.exe`/`python.exe`），否则拒绝 |
| **跑门禁 + 提交 + 记账 + 集成**（收口） | **只有主控** | 收口是**判断**活（哪些文件进这笔、台账/changelog/交接怎么写、红了怎么办），而且**一棵树只能一个写者** |

★ **收口为什么不能下放**：一笔提交要同时满足 —— 门禁绿（17 道门）、`audit` 绿（提交信息逐条 / 子卡一致性）、
台账与三个共享文档按**片段**重汇总、封存指纹对得上。这套**判断**住在**收口链工具**里 ——
★ **已进 git（2026-10-02，卡 139 / `T-G237`）**：权威副本 `tools/pool/landing.py`（收口链）+
`tools/pool/stage_card.py`（文书生成器），命令行壳 `tools/wb_land.py` / `tools/wb_stage_card.py`。
★ **原文（改动前）**：「这套**判断**目前只在主控的 scratch 工具里（`gates/diag/_integrate.py` /
`_stage_card.py`，**未进 git**）—— 这是**已知缺口**」（用户当面问过"你不应该把自己的记录放出去吗"）。
**剩下那半**（要不要**下放给别的窗口执行**收口）见 §六。

## 四、六条不变量（**谁判**）

| # | 不变量 | 谁判 |
|---|---|---|
| ① | 一棵树同时一个写者 | `tools/pool/guards.py::tree_guard` |
| ② | 冲突域不许相交（域从队列读，**查不到就拒**） | `tools/pool/guards.py::domain_guard` |
| ③ | 门禁还在跑就别动手 | `tools/pool/guards.py::lock_guard` |
| ④ | 内存不够不派活 | **委托** `tools/wb_dispatch.py` 的前置检查（`TF_GATE_MIN_FREE_GB`） |
| ⑤ | 日志不许覆盖 | `tools/pool/guards.py::log_guard` + 写面**不给** `--force` |
| ⑥ | 模型白名单 | `tools/wb_dispatch.py::MODEL_WHITELIST` + `tools/pool/models.py` |

## 五、队列、卡规格、开新卡

- **队列**：`docs/workbacklog.toml`（在 git 里）。字段口径见文件头：`tree` / `files`（冲突域）/ `depends` / `risk` / `status`。
- **卡规格**：`复盘/卡/卡<编号>-<短名>.md`（**在 git 里** —— 卡 116 之后队列自洽：每条 `spec` 都存在且被跟踪）。
  更早的历史卡规格留在主控 scratch 的 `gates/diag/`（**不进 git**，只是存档）。
- **开一张新卡的四步**（谁都能做前三步）：
  1. 写卡规格 → `复盘/卡/卡<编号>-<短名>.md`（**树** / base / 号池与模型 / 要做什么 / **禁区** / 回报格式）；
  2. 登记队列 → `docs/workbacklog.toml` 加一段（★ `files` 就是**冲突域**，写全，别写目录通配）；
  3. 建卡树 → `git worktree add --detach .wt/<名> <base>`；生成切片 → `python -X utf8 tools/wb_brief.py --card <编号> --spec 复盘/卡/卡<编号>-<短名>.md --cwd .wt/<名>`；
  4. **派活** → 任意窗口都能：`pool_dispatch(card="<编号>", tree=".wt/<名>", confirm="<编号>")`（或 CLI
     `python -X utf8 tools/wb_dispatch.py --card <编号> --spec … --cwd .wt/<名> --lean --detach --execute`）。
- **判"能不能同批跑"**：`pool_plan`（或 `python -X utf8 tools/wb_plan.py plan`）—— 它是**机器判据**，别靠眼看。

## 六、诚实边界（没做到的，照实写）

- ✅ **已治一半（2026-10-02，卡 139 / `T-G237`）**：**收口工具已进 git** —— `tools/wb_land.py` +
  `tools/pool/landing.py`（收口链）、`tools/wb_stage_card.py` + `tools/pool/stage_card.py`（文书生成器）；
  旧 scratch `gates/diag/_integrate.py` / `_stage_card.py` 留转发壳。★ **原文（改动前）**：「**收口工具
  没进 git**（见 §三 ★）：别的窗口能**派活 / 看进度 / 取消**，但**不能落地**。这是当前最大的缺口。」
  ★ **仍留一半**：工具在 git 里了，但**权限口径没变** —— §三 仍是"收口**只有主控**做"，
  "要不要下放给别人执行"仍是**未决**。
- 号池目录（模型白名单的真源）**不在本仓**（在 `<祖先>/infra/pool/`），`pool_models` 读的是**快照**、不联网。
- `pool_dispatch` 只**派**不**收**：派完要么自己看 `job_status` 轮询，要么交给主控。
- `pool_cancel` 只认**本机登记**里的 pid；登记里没有 pid（服务端在"起工人"和"补 pid"之间死了）⇒ **拒绝动手**。
- 写面在服务端 env 里要 `POOL_MCP_WRITE=1`；**没这个 env 就等于没有写工具**（不是"有但禁用"）。
