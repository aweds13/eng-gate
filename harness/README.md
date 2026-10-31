# harness/ —— 基础设施与项目之间的「缝」（T-G183）

`tools/` 工作台脚本的**复制体**：项目专有值已抽空，全读仓根 `harness.toml`
（唯一解析处 `manifest.py`）。复制体是**登记外的新东西**，原件仍在 `tools/`
一字未动，台账证据仍指原件。

## 这是缝，怎么加键

1. 先有**读取点**再加键；用不到不许写，没有装饰性配置。
2. 键要登记进 `manifest.py` 的 `SCHEMA` 白名单；不登记 = 未知键，加载即报错。
3. 只用 `manifest.get("段.键")` / `manifest.path("段.键", must_exist=...)` 读。
   写错（缺文件/坏 TOML/缺段/缺键/拼错/多写段/空值/非字符串/路径不存在）一律抛
   `ManifestError`，指名「哪个键·在哪个文件·期望什么」，**无静默默认值**。
4. 相对路径相对仓根 `ROOT`（本目录上一级）。唯一旁路：`HARNESS_TOML` 指绝对
   路径配置（测试/演示用）。

## 已复制的 4 个（依赖闭包，原件仍在 `tools/`）

| 复制体 | 原件 |
| --- | --- |
| `harness/wb_state.py` | `tools/wb_state.py` |
| `harness/wb_status.py` | `tools/wb_status.py`（wb_diag 的兄弟依赖） |
| `harness/wb_diag.py` | `tools/wb_diag.py` |
| `harness/wb_plan.py` | `tools/wb_plan.py` |

外加 `__init__.py`、`manifest.py`、`logcodec.py`。复制体**不依赖 `tools/`**（卡 205 选了 ①：让这句话
**真的成立**）：不挂 `sys.path`、不 `from tools...`；`wb_diag` 的 `import wb_status`
由同目录天然解析，`wb_plan` 算派活 `--cwd` 要的「主树根」也**就地**自己算
（`git rev-parse --git-common-dir`，算不出退回本复制体所在仓根）—— 不 import
`tools/pool/`。所以复制体跑起来只需要：**标准库 + 一份 `harness.toml` + `git`**，
拿掉 `tools/` 后仍能跑；证据见 T-G183 台账 gaps。

`harness/logcodec.py`（卡 E75）不是某个 `tools/` 文件的复制体，而是**就地实现的共用读法**：
`tools/pool/jobs.py::read_log_lines` 在 `tools/` 里，复制体不许 import 它，于是把「按 **BOM** 判编码
→ 剥 BOM → `splitlines()`」这份逻辑再写一遍，供本目录的 `wb_status` / `wb_diag` 共用
（改前两处各自 `read_text(encoding="utf-8", errors="replace").splitlines()`，UTF-16 的工人日志
被读成乱码 ⇒ 整条时间线静默消失）。**两份实现靠判据钉住，不靠约定**，见下表。

冻结输入下**原件/复制体输出逐字节相同**（允许的差异逐条写明）：

| 复制体 | 允许的差异 |
| --- | --- |
| `wb_plan` | 派活器脚本路径前缀：原件写死 `tools/wb_dispatch.py`，复制体读 `harness.toml` `paths.workbench` |
| `wb_state` | 原件有「白名单对账」行（`line_roster`，惰性 import `tools/wb_dispatch` + `tools/pool.models`）；复制体按「不依赖 `tools/`」约束**不复制这一行** —— 剥掉后逐字相同 |
| `wb_diag` / `wb_status` | 无差异 |
| `logcodec` | 无差异；同一份输入下 `lines` 与 `tools/pool/jobs.py::read_log_lines` **逐字节相等**（覆盖 UTF-16LE-BOM / UTF-16BE-BOM / UTF-8-BOM / 纯 UTF-8 四种） |

★ 这条不变量**已装牙**（卡 205 给 `wb_plan`，卡 214 给另外三份）：`tests/`
下的 `test_harness_manifest.py` 逐字比较两边的输出 —— 卡 203 改对了原件、复制体
却没跟上，正是从前**没有判据**盯它才一路绿灯的。

## 还没复制的 6 个重工具（下期清单，附现算耦合点数）

`wb_dispatch.py`(13) · `wb_verify.py`(9，import run_gates) · `wb_brief.py`(5) ·
`wb_dash.py`(5，import wb_dispatch/wb_status) · `wb_review.py`(4) · `wt_prune.py`(4)。
耦合点 = 本地 import + 仓内脚本路径 + 项目固定路径（`gates/diag`、`复盘/*` 等）。
下期复制时同样逐个抽空进 `harness.toml`（按需加键，别提前设计）。

## 为什么是复制，不是搬

台账证据按**路径**钉死文件位置：钉在 `tools/` 226 条、`scripts/` 45 条，
`audit_progress.py` 会求值其中的 `file:/text:/test:` 断言；铁律 35 定台账只许
末尾追加。搬文件 = 同时改这 271 条，走不通。复制则原件不动、证据照常解析，
复制体抽空后天生可独立，还能用「原件 vs 复制体」证明等价。

## 门禁接线

`scripts/run_gates.py` 的 ruff 目标加了 `"harness/"`（T-G183 对该文件唯一改动）：

```python
("ruff", [PY, "-m", "ruff", "check", "src/", "tests/", "scripts/",
          "tools/", "examples/", "harness/"]),
```

## 将来退役原件要做什么（属下一期）

退役 = 把台账按 `tools/` 钉死的证据（含三处按路径加载：`wt_prune.py` load
`wb_plan.py`、两个测试挂 `sys.path`）成批迁到 `harness/`，并给出迁移后 audit
全求值通过的证据。属下一期；**本卡不动原件**。
