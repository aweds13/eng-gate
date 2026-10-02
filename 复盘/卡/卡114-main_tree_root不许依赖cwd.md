# 卡 114 —— `main_tree_root()` 不许依赖**当前目录**（MCP 真机跑出来的 bug）（T-G211）

**树**：`.wt/poolcwd`（★ 开局就在这棵树里；`git rev-parse --short HEAD` 必须是主控给你的 base）
**base**：以派活时主控给的为准
**号池**：CodeBuddy ｜ **模型**：`deepseek-v4.1-flash` ｜ **提交**：★ **你不要 commit**（主控复核后提交）

---

## 来路（主控按"注册命令"真起了一次服务，当场现形）

主控把 `mcp-pool` 注册进 DSH 的 `cordis.patch.yml` 之后，**用注册时那条命令真起了一次服务**
（miniconda python + `tools/pool_mcp.py`，`POOL_MCP_WRITE=1`）：
`initialize` 正常、`tools/list` **8 个工具**、`lock_status` 真跑 —— 六个**只读**工具**全对**；
但一调**写面**就：

```
pool_cancel：读登记失败：算不出主工作树：`git rev-parse --git-common-dir` 没回路径
```

**根因**：`tools/pool/registry.py::main_tree_root()` 跑 `git rev-parse --git-common-dir` 时**没给 `cwd=`**
⇒ 用的是**进程当前目录**。而 DSH 起 MCP 子进程时 cwd **不在仓库里**（在仓库外）⇒ git 报错 ⇒ 算不出主工作树。
只读那六个工具不受影响（它们的 `ROOT` 从**脚本路径**推导），所以**只有写面（`pool_dispatch` / `pool_cancel`）中招**。

★ 为什么卡 108 / 111 的测试没抓到：**所有测试都在仓库里跑**（cwd 就是仓库），这条依赖一直没暴露
—— 这正是"**桩验过了 ≠ 真机能用**"的又一例。

## 你要做的

1. **`tools/pool/registry.py`**：给 `main_tree_root()` 里那次 `subprocess.run` 加 `cwd=`，
   用**从本文件推出来的仓库根**（`Path(__file__).resolve().parents[2]` —— 即 `tools/pool/registry.py` 的上三级）；
   它存在就给它，取不到才退回 `None`。**加一句注释**说明为什么（"服务可能被别的程序从任意 cwd 拉起"）。
   ★ **卡树行为不许变**：在卡树里 `parents[2]` = **卡树**（它也是 git 工作树）⇒ `--git-common-dir` 照样回
   **主仓**的 `.git` ⇒ 父目录仍是主工作树（这正是卡 108 设计的那条语义）。
2. ★ **顺手审一遍**：`tools/pool/**` 与 `tools/pool_mcp.py` 里**所有** `subprocess.run` 是否都显式给了 `cwd=`。
   （主控已 grep 过：只有 `registry.py:79` 这一处漏；`jobs.py:283` 是"可选 cwd"、`registry.py:242` 有 cwd。）
   把审计结论写进回报：**逐个列出**，没改的那几处要说明为什么不用改；**有别的漏网就一起修**。
3. 钉子（加到 `tests/test_pool_registry.py`），**两条**：
   - ① **单元**：`monkeypatch.chdir(<一个临时目录>)` 之后，`registry.registry_path()` **仍然**等于
     `<仓库根>/gates/diag/pool-registry.json`（改之前这里会抛 `RegistryError`）。
   - ② **端到端（真起服务）**：用 `subprocess` 起 `tools/pool_mcp.py`，**把子进程的 cwd 设成一个临时目录**，
     **不设** `TF_POOL_REGISTRY`，然后喂：
     - `tools/list` ⇒ 断言 **8** 个工具都在（顺带把"注册环境里 `POOL_MCP_WRITE=1`"也钉住）；
     - `tools/call pool_cancel {"card":"999","confirm":"999"}` ⇒ 回话必须是
       「本机登记里没有卡 999 的**活租约**」（= 正常路径），**不许**再出现"算不出主工作树"。
     ★ 测试要**自己收尾**（把起的服务进程 kill 掉）；★ **一个字节都不许写进真的 `gates/diag/`**。
   - ★ 先红后绿：把①的修复临时撤掉，证明两条钉子**真会红**，再撤掉那个临时改动（回报里贴原样输出）。

## 禁区

- 只许改 **`tools/pool/registry.py`** + **`tests/test_pool_registry.py`**；**不许**碰其它任何文件
  （尤其 `tools/pool_mcp.py`、`tools/pool/guards.py`、`tools/wb_dispatch.py`、`scripts/**`、`src/**`、`docs/**`、`复盘/**`）
- **不要** commit / push / 打 tag；不动 `.git` 里任何东西
- 不许装依赖 / 联网；★ 不许真去杀任何进程（端到端那条只用 `pool_cancel` 的"没租约"路径，**不会**杀东西）

## 回报（≤9 行）

```
1) 改了哪几行（改前 / 改后）
2) subprocess cwd 审计结论（逐个列出；没改的说明为什么不用改）
3) 两条钉子的原样输出（尤其②：改前会怎么报 vs 改后怎么答，两份都贴）
4) pytest + ruff 原样结论
5) ★ 没做到 / 不确定的：<如实写，没有就写"无">
6) ★ 你判断"该改但不属于本卡"的地方
```
