# 核 `gates/reuse.json` 的复用判定本身对不对（T-G106 / 外包卡 019）

> 台账号 `T-G106`（卡 019）。树 = `.wt/gates`，基点 `6268ce9`。
> 一句话：给"门禁的复用判据**本身会不会咬**"补上判据 —— 16 条单元测试先红后绿跑过；
> 顺手核出 `REUSE_INPUTS` **两处漏网输入**（如实记，按卡不擅自动）。

## §1 为什么有这张卡（出处）

盘点卡 S-1 的 **A16**（`gates/diag/盘点-20260926.md`）。原话出处 = `gates/diag/复核-1969b46.md`
§7.8（396–397 行）：

> 「门禁说 5 道门『复用判定』，我**没去核** reuse 判定本身对不对（那是门禁工具的活，超出本卡）」。

**从那以后没人核过这个判据。** 它恰恰是**门禁自己的护栏** —— 它替你回答"这一层能不能跳过"。
一条永远回「复用」或永远回「真跑」的判据**等于注释**（`check_commands.py` 里那两条恒真的
`is_write` 判定是活教材）。所以本卡先证明它会咬，再谈它判得对不对。

## §2 做了什么

**判据落在哪**：按主控裁定 §2.9 路①，新建 `tests/test_gates_reuse_line.py`（**16 条**）。
它把 `scripts/run_gates.py` 当模块 `import`，用 `tmp_path` 造假 `REUSE_INPUTS` / 假文件 / 假记录，
**不跑任何门**（并发期口径：§0-3 禁的是"跑门禁"，import 它不算）。

覆盖的情形（卡 §2.1 点名要的 + 顺手补的）：

| 情形 | 期望 | 用例 |
|---|---|---|
| 输入一个字节没变 + 上次通过 | 复用（返回哈希） | `test_unchanged_inputs_are_reused` |
| ★ 输入**改一字节** | 不复用 | `test_one_byte_change_disables_reuse` |
| ★ 新增一个被 glob 命中的文件 | 不复用 | `test_new_matching_file_disables_reuse` |
| `--no-reuse` | 恒不复用 | `test_no_reuse_flag_never_reuses` |
| 上次 `verdict != pass` | 不复用 | `test_failed_record_is_not_reused` |
| 记录里没有这一门 | 不复用 | `test_missing_record_is_not_reused` |
| 不在 `REUSE_INPUTS`（如 `pytest`） | 恒不复用 | `test_gate_outside_reuse_inputs_is_never_reused` |
| `input_hash` 确定性 + 16 位 | 稳定 | `test_input_hash_is_deterministic` |
| 未命中 glob 的文件 | 不影响哈希 | `test_unmatched_file_does_not_change_hash` |
| ★ 真表每道门都把 `src/**` 算输入 | 改一个 src 文件哈希必变 | `test_every_reusable_gate_treats_src_as_an_input`（5 道门各一条） |
| ★ 黄金 `gates/render/*.txt` 是 render 输入 | 改黄金 → 不复用 | `test_render_golden_files_are_inputs` |
| `reuse.json` 往返 + 坏文件当空 | 一致 / 不崩 | `test_reuse_records_roundtrip_and_bad_file_is_defensive` |

**为什么没有改 `run_gates.py` 的逻辑**：卡 §1 要核的是"判据本身对不对"，主控 §2.9 把判据裁定进
测试文件 —— 判据是可求值的事实，改它属于产品/口径决策，不该由工人自己动。`run_gates.py` 只加了
一处**指针注释**（见 §3 末）：在 `skip_reused` 的 docstring 里写明"这个判据会咬"由哪个测试
钉住，让代码里留一条通往判据的路。行为一字未改。

## §3 反证（先红后绿，原始输出）

**突变① —— 让 `input_hash` 恒返回同一个常量**（等于"输入永远没变"，判据退化成恒真）：

```
$ python -X utf8 -m pytest tests/test_gates_reuse_line.py --no-cov
FAILED tests/test_gates_reuse_line.py::test_one_byte_change_disables_reuse
FAILED tests/test_gates_reuse_line.py::test_new_matching_file_disables_reuse
FAILED tests/test_gates_reuse_line.py::test_every_reusable_gate_treats_src_as_an_input[lf1_live]
FAILED tests/test_gates_reuse_line.py::test_every_reusable_gate_treats_src_as_an_input[render]
FAILED tests/test_gates_reuse_line.py::test_every_reusable_gate_treats_src_as_an_input[ui_dom_probe]
FAILED tests/test_gates_reuse_line.py::test_every_reusable_gate_treats_src_as_an_input[ui_flow]
FAILED tests/test_gates_reuse_line.py::test_every_reusable_gate_treats_src_as_an_input[web_live]
FAILED tests/test_gates_reuse_line.py::test_render_golden_files_are_inputs
8 failed, 8 passed in 0.43s
```

**突变② —— 让 `skip_reused` 无视记录里的哈希、永远复用**（等于"上次通过就一直通过"）：

```
$ python -X utf8 -m pytest tests/test_gates_reuse_line.py --no-cov
E       AssertionError: assert 'e0cdfc76630a44ce' is None
E        +  where 'e0cdfc76630a44ce' = <function skip_reused ...>('render',
E            {'render': {'hash': '2917b8d550fbe315', 'verdict': 'pass'}}, no_reuse=False)
FAILED tests/test_gates_reuse_line.py::test_one_byte_change_disables_reuse
FAILED tests/test_gates_reuse_line.py::test_new_matching_file_disables_reuse
2 failed, 14 passed in 0.38s
```

**还原后（绿）**：

```
$ python -X utf8 -m pytest tests/test_gates_reuse_line.py --no-cov
................                                                         [100%]
16 passed in 0.22s

$ python -X utf8 -m ruff check scripts/run_gates.py tests/test_gates_reuse_line.py
All checks passed!
```

**`run_gates.py` 的净差异**（`git diff scripts/run_gates.py`，只有注释）：

```diff
 def skip_reused(name: str, records: dict[str, dict[str, str]], no_reuse: bool) -> str | None:
-    """输入没变且上次是通过 → 返回那条记录里的哈希（调用方据此记 `reused`）；否则 None。"""
+    """输入没变且上次是通过 → 返回那条记录里的哈希（调用方据此记 `reused`）；否则 None。
+
+    ★ 这个判据**本身会不会咬**由 `tests/test_gates_reuse_line.py` 钉住（T-G106）：输入改一个
+      字节 / 新增文件 → 不复用；`--no-reuse` / `pytest`（不在 `REUSE_INPUTS`）/ 上次没过 /
+      没有记录 → 一律不复用。一条永远回「复用」的判据等于注释。
+    """
```

> 两种突变都是**单点**改一行：能红，说明这批量最多的断言（"输入变→不复用"）**不是**在替
> 被测者兜底。这正是复核 §2.2 那个下场的反面（"删掉 `lines=snapshot` 仍 50 passed"）。

## §4 ★ 真东西验证（逐门核 `REUSE_INPUTS`）

**判据覆盖的情形**：见 §2 表（12 类，16 条用例）。

**`REUSE_INPUTS` 的 glob 有没有漏网输入** —— 按各门脚本**真读了什么**逐门核（只读，未改）：

| 门 | 登记的输入 | 真读的其它东西 | 结论 |
|---|---|---|---|
| `render` | `src/**`、`tools/render_check.mjs`、`tools/tf_browser.mjs`、`tools/serve.py`、`gates/render/*.txt` | ★ `tools/render_signatures.json`（`render_check.mjs:59`，采集当场按它核对） | **漏网**：改签名文件不会让哈希变 |
| `ui_flow` | `src/**`、`tools/ui_flow_check.mjs`、`tools/tf_browser.mjs`、`tools/serve.py` | （未发现） | 未发现漏网 |
| `lf1_live` | `src/**`、`tools/lf1_live_check.py`、`tools/serve.py` | 它 **不 import** `serve.py`（`:26` 直接 `create_app`） | `serve.py` 属**多算**（多跑一次，安全，不是漏网） |
| `web_live` | `src/**`、`tools/web_live_check.py`、`tools/serve.py` | ★ `tools/phone_check.mjs`（`web_live_check.py:31` 定义、`:656` 真跑它造手机包） | **漏网**：改 `phone_check.mjs` 不会让哈希变 |
| `ui_dom_probe` | `src/web/**`、`tools/ui_dom_probe.mjs` | 只读 `src/web/index.html` + `src/web/offline.js`（假 DOM，**不起服务**） | 不含 `serve.py` 是**有意**，不是漏网 |

**卡 §1 点名的三个问题，逐条答**：

1. 「改了 `src/**` 里一个文件，`input_hash` 真会变吗（→ 真会不复用）？」—— **会**。
   `test_every_reusable_gate_treats_src_as_an_input` 对 5 道门逐条钉住；突变①证明这条会红。
2. 「glob 覆盖够不够（有没有漏网输入）？」—— **有两处真漏网**（上表 ★ 两行）。
   ★ 按卡 §4 口径**如实记、不擅自改**，由主控定（是并入某张卡还是立新卡）。
3. 「黄金 `gates/render/*.txt` 进了 `render` 的输入 —— 那『黄金自己被改』时它算不算输入变了？」
   —— **算**。`test_render_golden_files_are_inputs` 钉住：改一份黄金 → 哈希变 → 不复用。

## §5 边界（如实写，没做到的部分）

- 本卡判据只证明**这套机制会咬**（输入变→不复用 / 输入不变→复用 / 几条否定路径）。
  **不判 `REUSE_INPUTS` 是否完整** —— 那是 §4 的人工核对，结论是"有两处漏网"，
  且按卡**未修**。
- `main()` 里 `--fast` 那条既有口径（`run_gates.py:481`，`--fast` 一律 `mark=None` 不碰复用）
  **本卡判据未覆盖**：要真跑 `main()`（门禁装配）才碰得到，与本卡"不跑重活"冲突。
  （`--quick` 里本来就没有真机层，同理。）
- `REUSE_INPUTS` 里 `ui_dom_probe` 只登记 `src/web/**`：本轮**判为有意**（假 DOM 不起服务、
  不读后端），但没有测试钉住"它有没有偷偷读了 `src/timeflow/**`" —— 靠读脚本确认，
  不是机器判据。

## §6 没动的

`gates/reuse.json`、`gates/last.json`（★ 共享文件、工具产物，一字未碰）、`tools/**`、
`docs/**`（含台账 / changelog）、`src/**`、`复盘/**` 其它文件、真实库 / 真实备份目录、
三个外来未跟踪文件。`scripts/run_gates.py` **除 §3 那条指针注释外一个字没动**（未跑全量门禁
——并发期口径，真机全量由主控集成时跑）。

---

## 台账条目（供集成者粘贴）

```toml
[entries."T-G106"]
id = "T-G106"
title = "核 `gates/reuse.json` 的复用判定本身对不对 —— 补一条能证明判据会咬的断言（T-G106 = 外包卡 019）"
group = "PROCESS"
status = "done"
evidence = [
  "file:复盘/reuse判定自证-T-G106.md",
  "file:tests/test_gates_reuse_line.py",
  "text:scripts/run_gates.py::tests/test_gates_reuse_line.py",
]
gaps = "**为什么有这张卡**：盘点卡 S-1 的 A16（出处 = 复核 §7.8 396–397「门禁说 5 道门复用判定，我没去核 reuse 判定本身对不对」）。**做了什么**：按主控 §2.9 路①，把判据落在新建的 `tests/test_gates_reuse_line.py`（16 条）—— import `run_gates` 做单元验证、不跑任何门；覆盖「输入不变→复用」「改一字节/新增文件→不复用」「--no-reuse→不复用」「不在 REUSE_INPUTS（含 pytest）→不复用」「上次没过/无记录→不复用」「每道门都把 src 算作输入」「黄金是 render 的输入」「reuse.json 往返 + 坏文件当空」。`scripts/run_gates.py` 只加一条指针注释（行为未改）。**反证（先红后绿）**：突变① `input_hash` 恒返回常量 → 8 failed；突变② `skip_reused` 无视记录哈希永远复用 → 2 failed；还原 → 16 passed（原始输出见复盘 §3）。**边界（如实写、按卡不擅自改）**：`REUSE_INPUTS` 有两处**真漏网输入** —— ① `render` 真读 `tools/render_signatures.json`（render_check.mjs:59）却未登记；② `web_live` 真跑 `tools/phone_check.mjs`（web_live_check.py:31/656）却未登记；`ui_dom_probe` 不含 `serve.py` 是有意（假 DOM 不起服务），`lf1_live` 登记 `serve.py` 属多算（安全）。判据只证明这套机制会咬，**不判 REUSE_INPUTS 是否完整**；`--fast` 不碰复用那条既有口径本卡未覆盖。**没动的**：`gates/reuse.json`、`gates/last.json`、`tools/**`、`docs/**`、`src/**`、复盘其它文件、真实库/备份、三个外来未跟踪文件。"
```
