# 卡 117 —— 主树里算错主工作树 + MCP 的「机器可读块」被报告正文冒充（T-G215）

**树**：`.wt/poolfix`（★ 开局就在这棵树里；`git rev-parse --short HEAD` 必须是主控给你的 base）
**base**：`b7dcdc2`（主控派活时给的那个）
**号池**：CodeBuddy ｜ 模型：由派活器定 ｜ **提交**：★ **你不要 commit**（主控复核后提交）

---

## 来路（今晚收一批**文档**时，门禁在**主树**咬出来的两条 pytest —— 都不是文档的错）

主控在主树（`--tree .`）收一个任务时，`pytest` 门红了 **2 failed, 1792 passed**：

```
FAILED tests/test_pool_registry.py::test_registry_path_does_not_depend_on_cwd
FAILED tests/test_pool_mcp.py::test_six_tools_return_and_write_nothing
```

★ **为什么在卡树里一直绿**：这两条都以「主树里没有真材料 / git 回绝对路径」为隐含前提，
只有在**主树**跑才现形。这正是"桩验过了 ≠ 真机能用"的又一例。

## ① `tools/pool/registry.py`：相对路径解析用了**进程 cwd**（卡 114 只修了一半）

**现场证据**（主控实测，两条命令）：

```
主树里   git rev-parse --git-common-dir  →  '.git'                              ← 相对路径！
卡树里   git rev-parse --git-common-dir  →  'D:/repo/engineering/.git'  ← 绝对
```

`main_tree_root()` 现在这么写（错在最后两行）：

```python
done = subprocess.run(["git", "rev-parse", "--git-common-dir"],
                      cwd=str(tree_root) if tree_root.is_dir() else None, ...)
common = Path(raw)
if not common.is_absolute():
    common = Path.cwd() / common        # ★ 用了**进程 cwd**，而不是"给 git 的那个 cwd"
return common.resolve().parent
```

**病**：git 是在 `tree_root`（仓库根）里跑的，所以它回的相对路径是**相对 `tree_root`**；
可代码拿**进程 cwd**去解析 —— 只要进程 cwd 不是仓库根（卡 114 那条钉子的场景、DSH 起 MCP 子进程也一样），
主工作树就算成 `<进程 cwd>/gates/diag/pool-registry.json`（实测断言差异就是这么来的）。

**修**：相对路径按**给 git 的那个 cwd** 解析（给了 `tree_root` 就用它，没给才退回 `Path.cwd()`）；
并把这条理由写进 docstring（"相对路径是相对 git 的 cwd，不是相对进程 cwd"）。

**验收（★ 必须在**主树**里验，不能在卡树里自证完就交）**：
- 单元钉子 `tests/test_pool_registry.py::test_registry_path_does_not_depend_on_cwd`：**先在主树复现红**
  （原样跑一次，存下报错原文），改完**在主树变绿**；卡树里也绿。
- ★ 另加一条钉子（防"只对某个 cwd 成立"）：`monkeypatch.chdir(<临时目录>)` 后
  `registry.main_tree_root()` 必须等于仓库根；再把 `TF_POOL_REGISTRY` 设成临时值，`registry_path()` 必须**优先用它**。

## ② MCP 的「机器可读块」不能是"正文里第一个像 JSON 的东西"

**现场证据**（`gates/logs/pytest.log`）：

```
tests/test_pool_mcp.py:166: _json_block(result["content"][0]["text"])
json.decoder.JSONDecodeError: Invalid control character at: line 1 column 96
s = ' {"jsonrpc":"2.0","id":2,"result":{"tools":[ {"name":"pool_plan","inputSchema":{"type":"object…
--- 摘要 ---  模型：dee…
```

**病**：`job_result` 把**工人报告正文**原样带出来，而那篇报告里正好**引用了 tools/list 的报文样例**
⇒ 测试的 `_json_block()`（取正文里第一个 `{ … }`）抓到的是**报告里的样例**、不是工具自己的机器块
⇒ 主树（有真报告）必红，卡树（没报告、返回"没有"）必绿。

**修（二选一，选完把理由写进注释；★ 不许只改测试、不改工具）**：
- ★ 首选：`tools/pool_mcp.py` 每条输出把机器可读块放在**唯一标记**之后（例如独占一行 `--- tf-json ---`
  之后紧跟**单行紧凑 JSON**），`tests/test_pool_mcp.py::_json_block` **只认标记之后那一段**；
- 次选：机器块固定用围栏 ```` ```json ```` 且**放在末尾**，测试取**最后一个能解析的围栏块**
  （★ 必须能扛住"报告正文里也有围栏 json 样例"）。

**验收**：钉子 `test_six_tools_return_and_write_nothing` 在**主树**里绿（那里真报告存在）；
另加一条钉子：**构造一份正文里含 JSON 样例（含围栏 json 块）的报告** ⇒ 六个工具的输出仍能解析出机器块；
再核一遍原来的判据不放松：跑一遍六个工具**工作区不多出一个文件**。

## 禁区（越了就是白干）

- **不改** `scripts/run_gates.py`、`scripts/audit_progress.py`、`gates/last.json`；**不跑门禁**（主控跑）。
- **不 commit / 不 tag / 不 push**；**不动**主树（你只在自己的 `.wt/poolfix` 里干活，`--cwd` 已经把你放对地方）。
- 只动白名单：`tools/pool/registry.py`、`tools/pool_mcp.py`、`tests/test_pool_registry.py`、`tests/test_pool_mcp.py`。

## 回报格式（照这个写，缺一条我就得重问）

1. 改了哪些文件 + 每个文件一句话。
2. ①的**先红后绿**：**主树**里改前的报错原文 + 改后的通过原文（各一小段）。
3. ②的标记/围栏长什么样（贴**原样**两三行），以及你选了哪个方案、为什么。
4. `pytest` 相关套件 + `ruff` 的原样结论（数字要说清）。
5. **没做到 / 不确定**的地方（如实写，别圆）。
6. 你判断"该改但不属本卡"的地方。
