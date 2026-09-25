"""读**命令表**（`docs/commands.toml`）—— CLI 那份真源。

CLI 不自己写命令清单：`timeflow commands` 与每条子命令「属于哪条契约操作、走哪条路由」
都从这张表来。**表找不到就拒绝工作**（退 3）—— 这是"四个面读同一个源"从口号变成事实的地方。

只读一个文件、不 import 任何业务模块，所以它也是 `scripts/check_commands.py` 用的那个读法
（两边共用这一份，免得出现"门禁读得出来、CLI 读不出来"这种自相矛盾）。
"""

from __future__ import annotations

import os
from pathlib import Path

import tomllib

#: 指到别处的表（测试与打包外使用时用；不设就按仓库布局往上找）
TABLE_ENV = "TIMEFLOW_COMMANDS_TOML"
RELATIVE = Path("docs") / "commands.toml"


class TableMissingError(RuntimeError):
    """找不到命令表 —— CLI 不猜、不自己造一份。"""


class TableBrokenError(RuntimeError):
    """命令表在、但**语法坏了**（TOML 解析不了）。

    为什么单独一类：这张表在本项目里已经写坏过 **9 次**（多是自己手写 TOML 时引号写错），
    而"表在、只是我打不开"与"表不在"是**两件不同的事**（怎么办也不同）——
    前者要的是文件里的行列号，后者要的是"去哪儿找"。
    `tomllib` 的报错本身就带行列，原样带给用户比自己编一句有用。
    """


def _candidates() -> list[Path]:
    """按优先级列出可能的表位置：环境变量（**只认它**）→ 本文件往上 → 当前目录往上。

    环境变量一旦设了就以它为准、不再兜底：那是调用方**明确指的那张表**，
    找不到就该报错 —— 悄悄换一张表读，等于让人以为自己在看另一份命令清单。
    """
    override = os.environ.get(TABLE_ENV, "").strip()
    if override:
        return [Path(override)]
    out: list[Path] = [base / RELATIVE for base in Path(__file__).resolve().parents]
    cwd = Path.cwd().resolve()
    out.append(cwd / RELATIVE)
    out.extend(base / RELATIVE for base in cwd.parents)
    seen: set[Path] = set()
    uniq: list[Path] = []
    for path in out:
        if path not in seen:
            seen.add(path)
            uniq.append(path)
    return uniq


def find_table() -> Path:
    """找到命令表；找不到抛 `TableMissingError`（并说清找过哪几个地方）。"""
    tried = _candidates()
    for path in tried:
        if path.is_file():
            return path
    raise TableMissingError(
        "找不到命令表 docs/commands.toml（CLI 是它的投影，没有它就不工作）。"
        "找过：" + "、".join(str(p) for p in tried[:6])
    )


def load_file(path: Path) -> dict[str, dict[str, object]]:
    """读一个具体的表文件；不存在或没有 `[commands]` 段就当空表（与检查器口径一致）。

    语法坏了抛 `TableBrokenError`（带上 `tomllib` 的原文 —— 它已经说清第几行第几列）。
    """
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise TableBrokenError(f"命令表语法有问题：{path} —— {exc}") from exc
    table = data.get("commands", {})
    return {str(k): dict(v) for k, v in table.items()} if isinstance(table, dict) else {}


def load() -> dict[str, dict[str, object]]:
    """读命令表（找不到就抛 `TableMissingError`）。"""
    return load_file(find_table())
