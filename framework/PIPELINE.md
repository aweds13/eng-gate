# PIPELINE.md —— 为什么这样设计（explanation）

> Diátaxis 的 `explanation` 象限：回答「它为什么长这样」。
> 要「怎么用」看 `README.md`；要「参数/字段到底是什么」看 `--help` 与 `pipeline.schema.json`。

## 一句话

这是一套**能带走的管线**：把「配置 → 门 → 判定 → 证据」做成一个**核心库** + 一层**薄 CLI** +
一个**模板仓**，项目专有值全部外置到 `pipeline.toml`。优先级写死：**自己先能用得好 > 好维护 > 别人也能用**。

## 三层（判据：把 CLI 删掉，库仍然可测）

| 层 | 在哪 | 职责 |
|---|---|---|
| 核心库 | `src/framework/**` | 配置加载 · 门运行器 · 退出码 · 台账/申报/集成/封存的接口 |
| 薄 CLI | `cli/main.py` | **只做三件事**：解析参数 → 调库 → 把结果映射成退出码 |
| 模板 / 示例 | `templates/**` · `examples/**` | `pipe init` 铺出的骨架；一个非本项目的示例仓 |

## 三条核心判据（都带反例钉子）

### 1. 三值判决：`pass` / `fail` / `inconclusive`

- `pass`：**拿到了通过证据**（退出码在 `exit_ok` 内，**且**收集到的样例数 > 0）。
- `fail`：**拿到了不通过证据**（退出码不在 `exit_ok`、或硬超时）。
- `inconclusive`：**判不了** —— 例：一条样例都没收集到（空集）。

★ **空集绝不许绿灯**：`inconclusive` 不许被当成 `pass`。
★ `inconclusive` **不等于** `not-run`：`not-run` 是**运行状态**（运行时依赖缺失，根本没跑），
  它**不是**一种判决，也**不算通过** —— 阻断门 `not-run` 时总判决折成 `inconclusive`。

### 2. 判据随件走：没有反例钉子不许进门

每道门必须声明一个 `nail`（反例钉子）：一条**喂进故意坏掉的样本、断言门会把它逮住**的用例。
- 钉子**通过** ⇒ 门**有牙**（正常）。
- 钉子**失败** ⇒ 门**失效**（判据退化成注释）。

`pipe doctor` 对每道门真跑一遍它的钉子，就是金丝雀自检。

> 措辞冲突（如实记）：骨架设计 §③.2 把这一句写成「钉子红 = 有牙」。本实现按卡 179 §④ 的用法
> 取「断言成立（钉子通过）= 有牙」，两处措辞相反、语义等价（都是「坏样本必须被判据逮住」）。

### 3. 一句真源：项目专有值只写 `pipeline.toml`

路径 / 端口 / 模型白名单 / 超时都在配置里，**代码里不写死**。配置校验是**白名单式**的：
缺键 / 拼错 / 未知键**一律明确报错**，不静默兜底（可选键的默认值是 schema 的一部分，见 `pipeline.schema.json`）。

## 唯一一张退出码表

`0` 通过 · `1` 判据不通过 · `2` 用法错 · `3` 资源闸拒跑 · `4` 被策略拒绝 · `5` 前置条件缺失 ·
`6` 被外部打断（可续跑）· `7` 资源全挂停止 · `124` 单门硬超时。

- **我们发的**：上列。
- **shell 发的**（我们永不发）：`126`（找到但不可执行）· `127`（命令未找到）· `128+N`（被信号 N 杀）。

## 提升就绪（promotion-ready）

目标：将来「把它提成一个独立仓」时**只是搬家、不是重写**。为此在现在就干净：

| # | 硬条件 | 判据 |
|---|---|---|
| P1 | 不许项目专有引用 | 全框架目录 grep 项目专有名 = 0 命中 |
| P2 | 自带 `pyproject.toml` | 可独立 `pip install` |
| P3 | 配置里无项目专有路径 | schema 与 templates 里 grep 项目专有路径 = 0 |
| P4 | 判据与钉子随件走 | 每道门的 `nail` 指向框架自己的 `tests/**` |
| P5 | 自带测试 + 自带门禁 | 在框架里跑 `pipe gate` 全绿、`pipe doctor` 每门有牙 |
| P6 | 不依赖外部 helper | 代码只 import 标准库与自身 |

## 边界（如实写）

- 本轮 `ledger` / `invariants` / `claim` / `land` / `trace` 是**薄壳**：签名在、行为未建，
  调用即抛「未实现」，**不返回假结果**（卡 179 §主控裁的范围）。
- 门运行器实现了「并发 + 硬超时 + 输入面 + 三值判决 + JUnit 计数」；复用只做 `hash` 的增量执行，
  `pytest` 类恒 `never`。
- 跨平台：进程树掐杀在 Windows 用 `taskkill /T /F`，其它平台用进程组 `SIGKILL`；**Linux 未在 CI 验证**。
- 本框架**尚未接进本项目的主门禁**（已知缺口，由后续独立仓门禁去关）。

## 验证分层（F1~F11，卡 185 / T-G285）

> 把「验证分层的行业要求」折进框架。依据见 `复盘/框架-验证分层的行业做法.md` §四（带真实 arXiv 编号）。
> ★ 每条都落到**代码 + 产物字段 + 判据**，不是只写文档。反例钉子随件走在 `tests/`。

### 术语（F11，依据 [arXiv:1305.4776] / [arXiv:2511.02810]）

| 这一趟 | 官方词 | 产物字段 |
|---|---|---|
| 收口 | `triggered_strict_build` | `build_kind` |
| 每日全量 | `scheduled_build` | `build_kind` |
| 增量窗口 | `regression_test_window` | `build_kind` |

### 逐条落点

| # | 条目 | 代码::符号 | 产物字段 | 钉子 |
|---|---|---|---|---|
| **F1** | 并行度优先，降级留痕 | `gates.py::run_gates` | `parallelism.{requested,used,degraded,reason}` | `test_full_run_capture::test_f1_degradation_is_recorded` |
| **F2** | 选择面报两个数 | `selection.py::select_gates` | `selection.{total,chosen,skipped,selection_rate}` | `test_selection::test_nail_f2_missing_selection_is_red` |
| **F3** | 兜底层报捕获率 | `selection.py::backstop_capture` | `backstop.{failures_caught,from_skipped,capture_rate}` | `test_selection::test_nail_f3_scheduled_missing_backstop_is_red` |
| **F4** | 输入面含动态读数 | `gates.py::run_gate(reads_manifest=)` | `gates[].{dynamic_reads,input_hash_with_dynamic}` | `test_full_run_capture::test_f4_dynamic_reads_change_the_combined_hash` |
| **F5** | 粒度按门/测试，不许跳整棵树 | `selection.py::validate_granularity` | —（抛 `SelectionError`） | `test_selection::test_nail_f5_tree_skip_is_red` |
| **F6** | 区分无关失败 | `selection.py::classify_failure` | `gates[].failure_attribution` | `test_selection::test_nail_f6_failure_missing_attribution_is_red` |
| **F7** | silent failure 三族一等风险 | `selection.py::check_ignored_exit_code` / `check_cache_stale` / `check_artifact_op` | —（抛 `SilentFailureError`） | `test_silent_failure_family`（三族各一） |
| **F8** | 跃迁检测 | `selection.py::detect_transitions` | `transitions[]` | `test_selection::test_nail_f8_scheduled_missing_transitions_is_red` |
| **F9** | 覆盖率不单独当绿 | `gates.py::run_gate`（`is_sole_coverage`） | —（`pass`→`inconclusive`） | `test_full_run_capture::test_f9_sole_coverage_is_inconclusive` |
| **F10** | 外部证据纪律 | `selection.py::lint_external_evidence` | —（抛 `EvidenceDisciplineError`） | `test_selection::test_f10_lint_catches_negation_without_search_terms` |
| **F11** | 术语对齐 | `selection.py::BUILD_KINDS` | `build_kind` | `test_selection::test_nail_f11_bad_build_kind_in_state_is_red` |

### 产物校验（`selection.py::validate_state`）

跑完一趟门禁，产物 dict 可过 `validate_state` 校验：缺 `selection`（F2）/ scheduled build 缺 `backstop`（F3）/ 失败门缺 `failure_attribution`（F6）/ scheduled build 缺 `transitions`（F8）/ `build_kind` 非官方词（F11）⇒ `StateValidationError`。★ 反例钉子：故意造缺字段的产物 ⇒ 必须红。

### F10 的纪律（写进框架，也约束本文件）

凡写「文献里没有 X」必须附检索词与检索范围 —— 否则不可复核 = 自证清白。
本文件引用的文献结论都是**设计输入**，不是产物的读数；要照某条改代码前先打开原文核（二手证据）。

## G1~G10 · 可控性与安全修改（卡 186 / T-G286）

> 一句话（照 `复盘/框架-可控性与安全修改.md`）：**不是追求完美，是让偏差被看见、
> 被限制、可回收**。本框架只管 G1/G3/G5/G7/G8/G9/G10 这一侧；G2/G4/G6 由本仓的
> 卡 160 / 162 / 156 管（闭环可判 / 债务带利息 / 证据要新鲜）。

| G | 文件::符号 | 产物字段 | 反例钉子 |
|---|---|---|---|
| **G1** 架构级 fitness | `fitness.py::architecture_fitness`（四条：`layered_dependencies_no_backflow` / `no_project_specific_imports` / `dangling_references` / `directory_discipline`） | `FitnessViolation{constraint,where,detail}` | `test_g1_layered_backflow_is_red` 等 4 条：造倒流 / 造项目 import / 造悬空引用 / 造缺目录 ⇒ 各红 |
| **G3** 多样性不许削减 | `fitness.py::diversity_not_reduced` | `FitnessViolation{constraint="G3·多样性削减"}` | `test_g3_reduction_without_justification_is_red`：砍门无论证 ⇒ 红（依据 [2510.20041]） |
| **G5** 可转换性分类 | `migration.py::validate_checklist` + `FRAMEWORK_MIGRATION` | `checklist_to_dict(){items,violations,ok}` | `test_g5_reversible_without_rollback_is_red` 等：缺回滚 / 不可逆没写「无」 ⇒ 红 |
| **G7** 拒绝点活性扫描 | `fitness.py::classify_refusal_scan` / `refusal_site_mutation` | `MutationReading{site,subject,original_verdict,mutated_verdict,is_vacuous_pass}` | `test_g7_refusal_scan_has_vacuous_pass`：删「empty」拒绝点 ⇒ collected=0 本该 inconclusive 却变 pass（★ 现成读数） |
| **G8** 三个数分开报 | `evidence.py::metrics_from_runs` / `Metrics.to_dict` | `{false_positive_rate,false_negative_rate,rerun_rate}` 各含 `{numerator,denominator,ratio}` | `test_g8_degenerate_green_only_is_caught`：只报 `ok` 的退化产物被 `metrics_complete` 咬住 |
| **G9** 验证器脆弱性 | `fitness.py::verifier_stable_under_reorder` | `EquivalenceReading{stable,detail}` | `test_g9_fragile_validator_is_caught`：脆弱验证器（依赖 dict 顺序）被等价重排改判 ⇒ 钉子有牙 |
| **G10** 复核面 | `review.py::run_review` + `ReviewConfig` + 检查面（`outside_allow` / `check_gate_evidence` / `check_full_gate_run` / `check_gates_trailer_truth` / `check_branch` / `check_seal_tree`） | `ReviewVerdict{landed,problems,notes,readings}` + `exit_code()` | ① `test_g10_nail_no_review_record_not_landed` ② `test_g10_nail_rev_mismatch_is_red` ③ `test_g10_nail_affected_block_is_red_with_original` |

### G7 现成读数（贴出）

对框架自己的三值判决 `gates.classify` 做拒绝点活性扫描，删掉「空集 ⇒ inconclusive」拒绝点后：

```
site(empty)被删  subject=collected=0,exit=0
原判 = inconclusive（空集：一条样例都没收集到 —— 不许当绿）
删后 = pass（退出码 0 在 exit_ok 内）  ⇒ ★ vacuous pass：本该不绿却变绿
```

★ 文献 [2608.26183] 说「对验证器自身拒绝逻辑做活性测试，比对具体 bug 写回归测试有效得多」；
★ 文献里**没有现成工具** —— 这是本框架自研的差异化能力。

### G10 复核面（`pipe review`）

`pipe review` 的库实现是 `review.py::run_review`：输入「一次集成的结果 + 卡的权威域」，
输出 `ReviewVerdict`（能不能算这一笔 + 稳定 `--json` + 退出码照卡 177 的表）。
`pipeline.toml` 的 `[review]` 段字段（`who`/`what`/`where`/`on_fail`）由 `ReviewConfig` 定义，
schema 接线由后续卡做（本卡白名单不含 `pipeline.schema.json`）。
本仓的 `tools/wb_review.py` + `tools/pool/review.py` 是那个零件，本卡把它**抽空进库**
（路径 / 常量由调用方传，库里不写死本仓路径）。

### 证据缺口（如实上，照文书 §四）

文献里**没有** CI 门禁可靠性的 SLO 定义、**没有**「规则被删仍变绿」的现成检测工具、
**没有**变异门禁的工业成本数据 ⇒ G7 是本框架自己补的洞，不是照抄。
