# tests/acceptance — 可执行验收层（B4）

> 默认被 `pyproject.toml` 的 `-m "not acceptance"` 排除。
> 显式运行：`python -m pytest -m acceptance`。
>
> `test_mvp_journey` 标记 `xfail(strict=True)`：第 2 步接线前应失败；接线后会 XPASS，强制移除标记。
> 对应 LF-1 / OP-4 / OP-5；目标：不用人工点点点也能验证 MVP 主链。
