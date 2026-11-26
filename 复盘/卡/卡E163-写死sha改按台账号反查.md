# 卡 E163 · 写死 sha 的判据改成按台账号反查 + log_batch 不把 NUL 当台账号

> 台账号 `T-AG699`｜分区 E（门禁与可信度）｜树 .wt/E163｜层 实现层｜depends —

## 要解决的问题

镜像仓 `aweds13/eng-gate` 的历史被 filter-repo 重写过（内容一字不改、sha 全变），
那棵树上四条红，两类根因：

### 问题 1 · 三条判据把「那一笔的形状」写成了「那个 sha 还在」

- `tests/test_pool_sink_wiring.py:263` 写死 `git show eaeb3923:tools/pool/sink.py`；
- `tests/test_pool_failclosed.py:58` 写死 `CARD_COMMIT` 默认值 `e3641bb9aa15…`；
- `tests/test_card_doc_budget.py:157` 写死纯数字短 sha `2051255`。

镜像里三条都报 `fatal: invalid object name`。判据本来钉的是「那一笔只加了 docstring」
「sink 八个函数以那一笔为基准」「纯数字短 sha 也算指针」—— 与 sha 具体是几无关。

### 问题 2 · `tools/pytest_select.py::log_batch` 把 `-z` 的记录分隔符当台账号

`git log -z --name-only --format=%x01%h%x1f%(trailers:key=Task,valueonly)` 里，**没有**
`Task:` trailer 的提交，`%x1f` 后面紧跟的就是记录分隔符 `\x00`；`task.strip()` 不剥 NUL
⇒ `task == "\x00"`，而逐笔读的 `git_task()` 回空串 ⇒ `assert '\x00' == ''`。
源仓最近几笔**每笔都有** trailer，所以这个 bug 只在重写过 / 没有 trailer 的历史上露头。

## 判据（逐条可执行）

1. `tools/git_anchor.py` 四件口径齐备且行为可验：`exists()` 是对象探测；`find_by_task()`
   按 `Task:` trailer 反查并取**最老**那笔；`anchor()` 本仓是对象就原样返回（源仓行为逐字
   不变）、否则反查、都查不到**原样返回**（不把「查不到」洗成某个看着像对的值）；
   `numeric_short_sha()` 从当前历史现取一笔纯数字短 sha。
2. 三处写死 sha 的判据都改走 `git_anchor`，**源仓行为不变**：主树里三份测试照旧全绿。
3. `log_batch()` 对没有 trailer 的提交返回空串台账号，与 `git_task()` 逐笔一致；
   `tests/test_git_anchor.py` 里那条回归在**修复前必红**（`assert '\x00' not in task`）。
4. 镜像仓（`C:/tmp/engpub/eng3`）里四条红全转绿：
   `tests/{test_card_doc_budget,test_pool_failclosed,test_pool_sink_wiring,test_pytest_select}.py`
   ⇒ 61 passed。
5. 主树侧回归：`tests/test_git_anchor.py tests/test_pytest_select.py tests/test_pool_sink_wiring.py
   tests/test_pool_failclosed.py tests/test_card_doc_budget.py tests/test_audit_tightening.py` 全绿；
   `python -X utf8 -m ruff check` 对改过的文件 `All checks passed!`。
6. 改过的文件仍是**纯 CRLF**（`count(b"\r\n") == count(b"\n")`）。

## 交付

- `tools/git_anchor.py`（新建）：写死 sha 的锚点。
- `tools/pytest_select.py`：`log_batch()` 剥 NUL。
- `tests/test_pool_sink_wiring.py` / `tests/test_pool_failclosed.py` / `tests/test_card_doc_budget.py`：
  三处写死 sha 改走锚点。
- `tests/test_git_anchor.py`（新建）：七条判据（锚点五条 + 批量取数一条 + 兜底）。
- `docs/changelog.d/T-AG699.md` / `docs/traceability.d/T-AG699.toml`：落地链生成。

## 验收（落地前自跑）

```bash
cd .wt/E163
python -X utf8 -m pytest -q -o addopts= -p no:cacheprovider \
    tests/test_git_anchor.py tests/test_pytest_select.py tests/test_pool_sink_wiring.py \
    tests/test_pool_failclosed.py tests/test_card_doc_budget.py tests/test_audit_tightening.py
python -X utf8 -m ruff check tools/git_anchor.py tools/pytest_select.py \
    tests/test_git_anchor.py tests/test_pool_sink_wiring.py tests/test_pool_failclosed.py \
    tests/test_card_doc_budget.py
```

`--gate-on local` 是**故意**的：本期没有可用云机（卡 E160 2026-11-25 实测那台已不存在），
`--gate-on cloud` 必退 2。

## 不许做

- 不许放宽判据：`anchor()` 查不到时**不许**返回 `HEAD` 或任意一笔，必须原样返回写死的值，
  让 `invalid object name` 照旧出现。
- 不许因为「镜像仓没有那笔」就把三条判据删掉或 `skip` —— 钉的东西仍在，只是改成按台账号定位。
- 不许改 `tools/card_doc_budget.py` 的判据本体（纯数字短 sha 走 `git cat-file -e` 实测是
  卡 193 定下的口径，本卡只改它那条测试的取样方式）。
- 不许把 `log_batch()` 的批量读改成逐笔读（卡 E127 实测 300 笔从 0.42 s 涨回 ~50 s）。
