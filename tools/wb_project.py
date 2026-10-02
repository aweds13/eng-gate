r"""当前项目 CLI `tools/wb_project.py`（卡 120 · T-G232）—— 只标准库。

**防什么**：同一个窗口里会跑**不同的项目** ⇒ 需要一句**显式**的"我现在在哪个项目"，
好让"派活 / 写文书只碰当前项目"、"只加载当前项目的记忆"从**自觉**变成**可查**。
三个动作，**只做**"选 / 看 / 读记忆入口"，不派活、不碰别的项目：

    python -X utf8 tools/wb_project.py use <项目>      # 写当前项目（窗口级）
    python -X utf8 tools/wb_project.py show            # 看当前项目（没选 / 没登记 ⇒ 退非 0）
    python -X utf8 tools/wb_project.py memory [<项目>] # 打印该项目的最小记忆入口（照索引）

- 当前项目落点：`<主工作树>/gates/diag/current-project.json`（**带 `TF_WINDOW_ID`** ——
  窗口级：一个窗口一个当前项目；`TF_CURRENT_PROJECT` 可覆盖路径，测试用）。
- ★ **本卡不做"按 cwd 自动判"**（用户没选）；也**不做硬档**（一个窗口同一时刻只允许一个活跃
  项目 —— 那要派活/写文书前比 target，等用户裁定）。这里只把"显式一句"落成文件。
- ★ `memory` **只**读**当前项目**的记忆入口（别的项目一份都不读）—— 这就是"避免脏 token"的正解。

**退出码**：`0` = 成功；`1` = 状态没就位（没选 / 记录的项目已不在索引里）；`2` = 用法或环境错。
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from pool import projects, registry

if TYPE_CHECKING:
    from collections.abc import Sequence

#: 当前项目的落点（相对主工作树）。
CURRENT_REL = ("gates", "diag", "current-project.json")


class UsageError(Exception):
    """用法 / 数据不对 —— 退 2（与"状态没就位"的退 1 分开）。"""


def current_path() -> Path:
    """当前项目文件：`TF_CURRENT_PROJECT` 覆盖；否则主工作树 `gates/diag/current-project.json`。"""
    override = os.environ.get("TF_CURRENT_PROJECT", "").strip()
    if override:
        return Path(override)
    return registry.main_tree_root() / Path(*CURRENT_REL)


def window_id() -> str:
    """本窗口的 id：`TF_WINDOW_ID`，没有就 `<hostname>:<pid>`（同 `registry.default_owner`）。"""
    return registry.default_owner()


def _known(entries: list[dict] | None = None) -> str:
    rows = projects.load() if entries is None else entries
    return "、".join(row["id"] for row in rows) or "（一个都没登记）"


# ---------------------------------------------------------------- 子命令


def cmd_use(name: str) -> int:
    """写当前项目（窗口级）。没登记过的项目 ⇒ 拒（存在性即授权），别写一个假项目。"""
    try:
        entry = projects.get(name)
    except projects.ProjectsError as exc:
        print(f"[FAIL] 项目索引读不了：{exc}", file=sys.stderr)
        return 2
    if entry is None:
        print(f"[FAIL] 没登记过的项目：{name}（已登记：{_known()}）—— 不许选一个不存在的项目",
              file=sys.stderr)
        return 2
    payload = {
        "project": entry["id"],
        "window": window_id(),
        "at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    path = current_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[项目] 当前项目 = {entry['id']}（窗口 {payload['window']}）→ {path}")
    print(f"       记忆入口：{'、'.join(entry['memory']) or '（这份索引没写 memory）'}")
    return 0


def cmd_show() -> int:
    """看当前项目；没选 / 记录的项目已不在索引里 ⇒ **说清并退非 0**（别静默）。"""
    path = current_path()
    if not path.exists():
        print(f"[项目] 还没选当前项目（{path} 不存在）—— 先 `wb_project.py use <项目>`",
              file=sys.stderr)
        return 1
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[FAIL] 当前项目文件坏了（不清空）：{path}（{exc}）", file=sys.stderr)
        return 1
    name = str(data.get("project") or "").strip()
    if not name:
        print(f"[FAIL] 当前项目文件里没写 `project`：{path}", file=sys.stderr)
        return 1
    print(f"[项目] 当前项目 = {name}（窗口 {data.get('window') or '?'}"
          f"，设于 {data.get('at') or '?'}）")
    try:
        entry = projects.get(name)
    except projects.ProjectsError as exc:
        print(f"       ★ 注意：项目索引读不了（{exc}）—— 这个项目现在对不对判不了")
        return 1
    if entry is None:
        print(f"       ★ 注意：{name} 已不在项目索引里（已登记：{_known()}）—— 请重新 use",
              file=sys.stderr)
        return 1
    current = window_id()
    if str(data.get("window") or "") != current:
        print(f"       ★ 注意：这是**别的窗口**（{data.get('window')}）设的；本窗口是 {current}")
    return 0


def cmd_memory(name: str | None) -> int:
    """打印该项目的最小记忆入口（**照索引**，不发现 / 不推断）。不给项目 ⇒ 用当前项目。"""
    target = (name or "").strip()
    if not target:
        path = current_path()
        if not path.exists():
            print("[FAIL] 还没选当前项目（先 `wb_project.py use <项目>`，"
                  "或 `wb_project.py memory <项目>`）", file=sys.stderr)
            return 2
        try:
            target = str(json.loads(path.read_text(encoding="utf-8")).get("project") or "").strip()
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[FAIL] 当前项目文件读不了：{path}（{exc}）", file=sys.stderr)
            return 2
        if not target:
            print(f"[FAIL] 当前项目文件里没写 `project`：{path}", file=sys.stderr)
            return 2
    try:
        entries = projects.memory_entries(target)
    except projects.ProjectsError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2
    print(f"[记忆] 项目 {target} 的最小记忆入口（只读这几份；别的项目一份都不读）：")
    for rel in entries:
        print(f"  · {rel}")
    if not entries:
        print("  （这份索引没写 memory —— 不猜）")
    return 0


# ---------------------------------------------------------------- 参数 / 入口


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="当前项目：显式一句『我现在在哪个项目』")
    sub = parser.add_subparsers(dest="command", required=True)

    p_use = sub.add_parser("use", help="选当前项目（写 current-project.json，带窗口 id）")
    p_use.add_argument("project", help="项目名（必须在项目索引里登记过）")

    sub.add_parser("show", help="看当前项目（没选 / 没登记 ⇒ 退非 0）")

    p_mem = sub.add_parser("memory", help="打印该项目的最小记忆入口（照索引）")
    p_mem.add_argument("project", nargs="?", default="", help="项目名；不给就用当前项目")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "use":
            return cmd_use(args.project)
        if args.command == "show":
            return cmd_show()
        return cmd_memory(args.project)
    except registry.RegistryError as exc:
        print(f"[FAIL] 算不出主工作树：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
