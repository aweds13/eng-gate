# 三层资产边界：产品 / 谁来做 / 在什么机器上

> 给 `softeng-manage` 用的按需参考。三句话记住：**timeflow 是产品，pool 是「谁来做」，infra 是「在什么机器上」**。
> 三层的真源、写权限、盘的归属都不同；判据在 `tools/pool/` 与 `infra/pool/` 的代码里，本文件只讲边界与取证。

## 1. 一眼分清

| 层 | 指什么 | 真源在哪 | 谁能改 | 改了谁疼 |
|---|---|---|---|---|
| 产品 | timeflow 的代码与五层文档 | 本仓 `src/`、`docs/` | 卡（本仓工作链） | 用户与验收 |
| 谁来做 | 队列、卡、树、派活、号池 | 本仓 `docs/workbacklog.toml`、`tools/pool/`；号池在仓外 `infra/pool/` | 主控；号池目录只有用户能改 | 派活与账本 |
| 机器 | 账号、模型白名单、浏览器、DB | 仓外 `D:/repo/infra/` | 只有用户，卡不改 | 全部工人 |

判据：**问「删掉它，谁的活会停」**。停派活 = 工作链层；停功能 = 产品层；停机器 = infra 层。

## 2. 为什么 pool 与 infra 必须分开

- `pool` 是**只读消费端**：`pool.models` 只读号池的白名单快照，`pool.projects` 读项目索引，
  `pool.registry` / `pool.guards` 只做核对。它不派活、不跑门、不起进程。
- **写面在别处**：派活写面在 `tools/pool_mcp.py`；号池本身在仓外的 `infra/pool/`，
  改账号、轮换凭据、切模型是运维动作，不是卡能做的事。
- 这么切的好处：卡树里没有凭据，主树里没有账号；坏一个层的读数不会连带污染另外两层。

## 3. 本仓引用 `infra/pool` 的耦合点（读数）

取证命令（在卡树根跑）：

```bash
grep -rl --include=*.py --include=*.toml "infra/pool" tools | wc -l   # 16
grep -rn --include=*.py --include=*.toml "infra/pool" tools | wc -l   # 41
```

源码口径（**2026-11-08 实测**）：**16 个文件、41 处**。

| 文件 | 处数 | 它在读什么 |
|---|---|---|
| `tools/wb_dispatch.py` | 10 | 派活前解析号池与项目索引 |
| `tools/pool_mcp.py` | 5 | MCP 面读号池快照的入口 |
| `tools/pool_accounts.py` | 5 | 账号账本与号池目录 |
| `tools/pool/model_registry.py` | 4 | 模型登记与白名单文件的位置 |
| `tools/pool/projects.py` | 2 | 从祖先逐级找项目索引 |
| `tools/pool/platforms.toml` | 2 | 能力表里的只读口径 |
| `tools/pool/model-registry.toml` | 2 | 登记表里写死的相对位置 |
| `tools/pool/callers.py` | 2 | 调用方登记 |
| `tools/pool/accounts_scope.py` | 2 | 账本作用域 |
| `tools/pool/models.py` | 1 | 白名单只读路径 |
| `tools/pool/limits.py` | 1 | 限额表位置 |
| `tools/pool/lease.py` | 1 | 租约与号池目录的关系 |
| `tools/pool/lanes.toml` | 1 | 通道表 |
| `tools/pool/failclosed.py` | 1 | 判不出就拒的口径 |
| `tools/pool/account_id.py` | 1 | 账号号形校验 |
| `tools/pool/__init__.py` | 1 | 包级说明与只读口径 |

★ 计数陷阱：不带 `--include` 的 `grep -rl` 在**主树**跑会读到 29 个文件 —— 多出来的是 `__pycache__/*.pyc`。
报数一律用 `--include=*.py --include=*.toml` 的源码口径，并把命令一起写上，否则下次没人能复现。

## 4. 三条边界（越界会怎样）

1. **号池目录只读**：`tools/pool/models.py` 与 `tools/pool/__init__.py` 都写明「`infra/pool/` 只读」。
   在卡里改它 = 改别人的机器；要改就交给用户。
2. **项目索引三条硬判据**：`root` 存在、不重根、`tree_prefixes` 非空；找不到就抛错，**不猜**。
   索引文件用 `TF_PROJECTS_TOML` 覆盖，这是给测试与特殊仓的口子，不是给卡的口子。
3. **派活不跨项目根**：`wb_dispatch` 的 `--cwd` 必须落在项目索引的 `tree_prefixes` 里；
   跨根的活要先在索引里登记，再派。

## 5. 跨层改动怎么开卡

- **一张卡一层**。要动号池同时改产品：开两张卡，让产品卡 `depends` 号池卡。
- **需要用户动手的，卡里只写「要用户做什么 + 验收」，不写命令替他做**（账号、密钥、模型白名单）。
- **证据分三层引用**：产品给门禁读数，工作链给队列/判决读数，机器给「用户已确认」的原话。
  三层证据不能互相顶替。

## 6. 常见错

| 现象 | 真因 | 处置 |
|---|---|---|
| 卡里出现账号、token | 把机器层写进了卡 | 删掉，改成「需用户提供」 |
| 派活报「找不到项目根」 | `--cwd` 不在 `tree_prefixes` 里 | 先登记索引，或换到已登记的子树 |
| 号池读数与主树不一致 | 读的是 `__pycache__` 或另一棵树的快照 | 用源码口径重数，并写明在哪棵树跑 |
| 模型名不在批准集 | 用了 `pool` 层之外的名字 | 看号池的只读面（`pool_models` 这类只读工具）返回的「批准集 ∩ 可用集」，不要猜 |

> 判据在 `tools/pool/models.py`（只读白名单）、`tools/pool/projects.py`（三条硬判据）、
> `tools/pool_mcp.py`（唯一写面）；号池本体在仓外，本仓只读。
