# 卡 A285 · ruff 112 → 0（framework 27 个文件 + gate_lock.py）

## 缺口

门禁里的 ruff 只扫 `src/ tests/ scripts/ tools/ examples/ harness/`（`scripts/run_gates.py` 的
`COMMON` 清单），**`framework/` 不在里面**。于是那边长期躺着 107 个 ruff 错，加上
`gates/diag/gate_lock.py` 5 个，一共 **112 个** —— 门禁从不报，手动 `ruff check .` 一跑就红。

分布（`python -X utf8 -m ruff check framework gates/diag/gate_lock.py --statistics`）：

```
72  E501   line-too-long            13  I001  unsorted-imports        [*]
 9  TC003  typing-only-stdlib-import  8  F401  unused-import          [*]
 3  UP035  deprecated-import        [*]  2  B011  assert-false
 2  SIM105 suppressible-exception       2  TC001 typing-only-first-party-import
 1  UP009  utf8-encoding-declaration[*]  → Found 112 errors（25 fixable）
```

## 变更

28 个文件（`framework/` 27 个 + `gates/diag/gate_lock.py`），**ruff 配置零改动**
（`pyproject.toml` 一个字没碰）：

- **E501 72 处**：只折行（字符串/调用按 100 列拆开），不合并、不改字面量。
- **`ruff --fix` 自动项 25 处**：I001 导入排序 13、F401 未用导入 8、UP035 弃用导入 3、
  UP009 utf8 编码声明 1。
- **TC001 / TC003 共 11 处**：只在类型标注里用到的导入挪进 `if TYPE_CHECKING:`（12 个文件）。
- **B011 2 处**：`assert False, "…"` → `raise AssertionError("…")`
  （`framework/src/framework/config.py:159`、`framework/tests/test_meta_verification.py:192`）。
- **SIM105 2 处**：`try/except: pass` → `contextlib.suppress(...)`（`framework/src/framework/gates.py:317`）。

## 检查点

- `python -X utf8 -m ruff check .` → All checks passed（112 → 0）
- `python -X utf8 -m pytest framework/tests -q --no-cov` → 150 passed
- 配置零改动：`git diff --stat -- pyproject.toml ruff.toml .ruff.toml` 为空

## 陷阱

- **`framework/` 不在门禁的 ruff 覆盖面里** ⇒ 这 112 个错本来不会被 ⑤ 拦住任何一笔落地。
  改成 0 只让"手动跑 `ruff check .` 可信"，门禁覆盖面**没有**变宽 —— 别把它当"多了一道闸"。
- **`assert False` → `raise AssertionError` 是行为变化**：`python -O` 会把 `assert` 整条优化掉，
  `raise` 不会。这 2 处本来就在 `pragma: no cover` 的不可达分支里，但语义确实变了（变正确）。
- **SIM105 是等价改写**：`contextlib.suppress(E)` 与 `try: … except E: pass` 语义一致，
  但如果块里还有 `else`/`finally` 就不能这么换 —— 这 2 处都没有。

## 影响面

28 个文件，全是格式 / 导入 / 等价改写。不动判据、不动任何测试断言、不动 `pyproject.toml`；
`pytest framework/tests` 前后都是 150 passed。
