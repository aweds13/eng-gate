# tests/acceptance — 可执行验收层（B4）

> 默认被 `pyproject.toml` 的 `-m "not acceptance"` 排除。
> 显式运行：`python -m pytest -m acceptance`。
>
> `test_mvp_journey` 已在第 2 步接线完成（原 `xfail(strict=True)` 靶子已按要求移除，现为真实验收）。
> 对应 LF-1 / OP-4 / OP-5；目标：不用人工点点点也能验证 MVP 主链。
