# CI 子系统（分区 E）—— 项目书

> 立项：2026-10-24（用户裁定「CI 是独立系统，单独立项，全部做」）。
> 一句话：**CI 不是"跑测试的脚本"，是本仓的准入系统**——它决定"哪一笔提交算数"。
> 今天三个半小时里 65 分钟花在返工，全部是它的判据"事后才说话"；这份项目书就是把它当系统管。

## 1. 它现在是什么（代码边际）

| 件 | 位置 | 职责 |
|---|---|---|
| 门表 | `gates/defs/{lang_python,contract,product_timeflow}.py` | 每道门的**定义**（命令/超时/说明）—— 真值与**门数**都以 `scripts/run_gates.py` 的 `GATE_PROFILES` 为准（现读 `build_jobs()`；2026-11-10 实测 `lang` 6 + `audit` 6 + `product` 11）。门数会随卡增长：卡 F6 把 `docs` 门接进 `audit` 档（20→21），本批把 `skills_claims` 接进来（21→22），卡 E104 又把 `contract_doc_table` 接进来（22→23） |
| 编排 | `scripts/run_gates.py` | 选档、跑门、复用、封存（`seal()`）、落 `gates/last.json` |
| 选档 | `gates/defs/domains.py` | 改动面 → 必需档（`--profiles auto`，fail closed） |
| 落地链 | `tools/pool/landing.py` | 八步：迁树→文书→快门禁→全量→封存→白名单提交→审计→ff→复核 |
| 复核 | `tools/wb_review.py` | 五档：卡、台账、域、门禁真伪、提交树=封存树 |
| 封存/复用 | `gates/last.json` / `gates/reuse.json` | 指纹 `rev`+`tree`；逐门复用 |
| 并行闸 | `tools/pool/lease.py` + `tools/wb_session.py` | 门禁锁、端口段、卡归窗口 |

口径：**判据住代码，技能只讲顺序**。这条不变。

## 2. 度量（2026-10-30 实测，全量 23 道；门数现读 `scripts/run_gates.py` 的 `build_jobs()`，由 `tests/test_ci_docs_counts.py` 与真门表对账）

读数取**同一趟**：`gates/last.json`（`at = 2026-10-30T21:46:41`、`rev = 2fdaba1f`、
`tree = 72a05a17`、4 worker、`pytest 4006 passed`）。`0 s` 表示那趟**复用**上次通过判定、
没有真跑（源：同一份 `gates/last.json` 的 `reused` 块）。收集条数是**快照**不是常量：
2026-10-31 实测 `python -X utf8 -m pytest --collect-only -q -o addopts= --no-cov`
⇒ **4040 条**（每加一个用例它就变，重跑这条命令即可对账）。

| 门 | 耗时 | 备注 |
|---|---|---|
| `pytest` | 414.77 s | 唯一逐次全跑的（源：`gates/last.json` 的 `gates[].seconds`） |
| `pytest_chain` | 177.68 s | 慢 e2e 单独一道门跑（同源） |
| `acceptance` | 19.62 s | 验收层 2 条（同源） |
| `mypy` | 17.36 s | `src/` 全量型检查（同源） |
| `contract_doc_table` | 0.2 s | 契约对账表逐格核（卡 E104 起；源：本卡落地前实测 `python -X utf8 tools/contract_audit.py --check-doc` 0.15 s，进门前没有这门所以那趟 `gates/last.json` 里没有它的 `seconds`） |
| 其余 18 道 | 合计 40.71 s | 含 5 道复用（`ui_dom_probe` / `lf1_live` / `web_live` / `render` / `ui_flow`，各 0 s）；真跑的最大 `check_layers_selftest` 7.06 s、`audit` 6.58 s、`check_layers` 4.72 s、`ruff` 0.79 s（同源） |
| **整趟** | **670.14 s ≈ 11.2 min** | 那趟全量门逐门 `seconds` 相加（同源；`contract_doc_table` 是 2026-11-10 才加的第 23 道，只多 0.2 s，没并进这个和） |

落地尝试 8 次，**5 次失败在"走到那一步才说的规矩"**（缺文书、卡树祖先、spec 未跟踪、changelog 首行、队列缺 status、ruff 未用 import）。

## 3. 决策（D1–D7，对应卡 E1–E6 与 E72）

- **D1 判据前置**：所有能在 10 秒内判完的前置，必须在落地第一秒全部说出来（`wb_land --preflight`，零副作用）。**先修这个，后面每一步都受益。**
- **D2 测试影响分析（TIA）**：按"改动文件 → 覆盖它的测试"选测，而不是按目录选档。pinned 兜底（新增/上次失败/判据钉子永远跑）。
- **D3 提交面算档**：`--profiles auto` 一律按**提交面**（父提交..HEAD + 暂存）算，不看脏工作区；`blobs/`、`.dsh-probe/` 进 `.gitignore`。
- **D4 红单归并**：同一 traceback 归并成一条 + 计数，报告只打前 3 条。
- **D5 合并队列**：单写者队列 + 投机预检，取代"各自 ff"；落地途中主树前进不再白跑。
- **D6 文档纪律**：卡树里**不许先提交**（落地链要求工作区改动）；文书三段照模板；写进 `skills/pipe-land`。
- **D7 假红不许靠重跑洗白**：红门的 `detail` 第一段先给隔离判定 —— `[隔离跑绿]` / `[隔离也红]` / `[判不出]`，一律由 `scripts/flake_probe.py` 单跑那条 nodeid 得出。**`[隔离跑绿]` 也不等于通过**：门照样是红的、退出码不改，只是把"这片红复现不了"说清楚。默认关（`TF_GATE_FLAKE_PROBE=1` 才开）；关着时 detail 明写"本次未做隔离复核"，不许静默省略。**再跑一次门禁不是证据。**

## 4. 目标值（SLA）

| 指标 | 现在 | 目标 |
|---|---|---|
| preflight 一次说全 | 无 | ≤ 15 s，0 副作用，列出全部问题 |
| 单卡落地墙钟 | 15–25 min | ≤ 8 min（提交面选档 + TIA） |
| pytest（典型提交） | 427 s 全量 | ≤ 90 s（TIA 命中 ≥ 95% 相关测试） |
| 红单报告 | 788 KB 日志 | ≤ 3 行（归并后） |
| 落地一次过率 | 3/8 | ≥ 6/8 |

## 5. 卡表

| 卡 | 台账号 | 标题 | 依赖 |
|---|---|---|---|
| E1 | T-AG443 | 判据前置：`wb_land --preflight` 一次说全 | — |
| E2 | T-AG444 | 测试影响分析：按覆盖映射选测 + pinned 兜底 | E1 |
| E3 | T-AG445 | 提交面算档 + `.gitignore` 收残留 | E1 |
| E4 | T-AG446 | 红单归并：同 traceback 只打一次 + 计数 | E1 |
| E5 | T-AG447 | 合并队列：单写者 + 投机预检 | E3 |
| E6 | T-AG448 | 文档纪律：卡树不许先提交（写进技能与钉子） | — |

判据清单（今天踩过的每一条，含代码位置）见 [`事后判据清单.md`](事后判据清单.md)。

## 6. 边界（明确不做的）

- 不把 CI 代码搬到新目录：`gates/`、`scripts/run_gates.py`、`tools/pool/landing.py` 就地演进（搬家的成本远大于收益，且会让 200+ 处引用失效）。
- 不改判据强度（宁可多跑，不许漏跑）——只改**什么时候说**和**选哪些测**。
- 不引入外部 CI 服务：这套的价值是"判据在仓内、可读可改"。
