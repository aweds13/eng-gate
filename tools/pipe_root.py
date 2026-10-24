"""工具根 vs 数据根（卡 A326：工具链与数据分离的第一刀）。

背景：`tools/*.py` 一直用 `Path(__file__).parent.parent` 当仓库根，于是「工具住在哪个仓」
和「账本/门禁/卡规格住在哪个仓」被绑死。dsmate 这类新项目要复用工具链、数据留在自己仓里，
就必须把这两个根分开。

口径（三条，按优先级）：
1. `PIPE_DATA`：显式指定数据根（另一个仓的绝对路径）。
2. 当前工作目录：若它看起来像一个数据根（有 `docs/workbacklog.toml` 或 `gates/diag`），就用它。
3. 回落：工具所在仓（老行为，逐字不变）。

工具根固定为 `tools/` 的上一级（或 `PIPE_HOME`），只用来 import 代码，不读账本。
"""

from __future__ import annotations

import os
from pathlib import Path

MARKERS = ("docs/workbacklog.toml", "docs/traceability.toml", "gates/diag")


def home_root() -> Path:
    """工具根：代码住的地方。"""
    env = os.environ.get("PIPE_HOME", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parent.parent


def _looks_like_data_root(path: Path) -> bool:
    return any((path / m).exists() for m in MARKERS)


def data_root(explicit: str | os.PathLike[str] | None = None) -> Path:
    """数据根：账本、门禁产物、卡规格住的地方。"""
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("PIPE_DATA", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    cwd = Path.cwd().resolve()
    if _looks_like_data_root(cwd):
        return cwd
    return home_root()


def describe() -> dict[str, str]:
    """给 `--check` 用的一行读数。"""
    return {"home": str(home_root()), "data": str(data_root())}


def main(argv: list[str] | None = None) -> int:
    """`python -X utf8 tools/pipe_root.py --check` —— 打印两个根（诊断用；不写任何文件）。"""
    import json
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if "--check" not in args:
        print("用法：python -X utf8 tools/pipe_root.py --check")
        return 2
    print(json.dumps(describe(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
