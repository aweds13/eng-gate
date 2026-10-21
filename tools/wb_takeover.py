#!/usr/bin/env python
"""wb_takeover —— 只读勘察器（卡 A300）：把「要接手的旧项目」目录分类成 A/B/C/D。

四类（操作顺序与判据解读在 `skills/pipe-takeover/`，逐条口径见
`skills/pipe-takeover/references/classify.md`）：

- A 已有完整管线 —— 仓里有 `pipeline.toml` / `harness.toml`，或本仓三件套
  （`docs/workbacklog.toml` + `gates/last.json` + `tools/wb_*.py`）。
- B 有测试无门禁 —— 有测试 / CI 信号（`tests/`、`pytest.ini`、`pyproject.toml`、
  `package.json` 的 scripts.test、`.github/workflows/`、`Makefile` 等），但没管线。
- C 裸仓 —— 只有代码（或什么都没有），无测试、无 CI、无管线 ⇒ 兜底类。
- D 别人的框架 —— 检出别家 agent 框架标记（`CLAUDE.md`、`.claude/`、`.cursor/` 等）
  ⇒ 只勘察，不落文件。

判定优先级：A → D → B → C（自己的管线最优先；其次认别人的框架；再次借测试；
都不沾就是裸仓）。

用法：
    python -X utf8 tools/wb_takeover.py --root <目录> [--json]

退出码：`0` 勘察完成（判哪类都是 0）；`2` 目录不存在（此时 JSON 输出 `ok: false`）。
只读：零写盘、零网络、不起子进程（全部判据都是「文件在不在」）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

#: A 类：自己这套管线的骨架配置（任一存在即 A）。
OWN_PIPELINE_FILES = ("pipeline.toml", "harness.toml")
#: A 类：本仓形态的三件套（全齐也算 A —— 本仓没有根级 pipeline.toml）。
OWN_TRIO = ("docs/workbacklog.toml", "gates/last.json")
#: D 类：别家 agent 框架的标记（任一存在即 D）。
FOREIGN_MARKERS = (
    "CLAUDE.md",
    ".claude",
    ".cursor",
    ".cursorrules",
    ".windsurfrules",
    ".aider.conf.yml",
    ".github/copilot-instructions.md",
)
#: B 类：测试信号（文件 / 目录名）。
TEST_SIGNALS = ("tests", "pytest.ini", "pyproject.toml", "tox.ini")
#: B 类：CI 信号。
CI_SIGNALS = (".github/workflows", "Makefile", ".gitlab-ci.yml", "Jenkinsfile")

MAPPING_HINTS = {
    "A": [
        "管线已齐：直接复用现有门表与台账；新工作项写进队列文件（卡）",
        "issue/缺陷单 → 卡；测试报告 → 证据；变更集 → 一笔提交",
        "口头约定、wiki 里的「应该怎么改」→ none（不映射，只当背景写进复盘）",
    ],
    "B": [
        "CI job / 检查脚本 → 门（能退出码判读的检查）",
        "测试报告 / 覆盖率产物 → 证据（机器可求值的指针）",
        "issue / 缺陷单 → 卡；TODO 注释 → 台账条目的 gaps",
        "口头约定、聊天记录 → none（不映射）",
    ],
    "C": [
        "先铺最小骨架：骨架配置 + 队列壳 + 台账壳 + 至少一道真门（只加文件）",
        "TODO 注释 / 未完事项 → 台账条目的 gaps",
        "口头约定 → none（不映射）",
    ],
    "D": [
        "只勘察、不落任何文件；对方框架的产物一律 none（不映射进我们的台账）",
        "勘察结论写进自己这边的复盘文件",
    ],
}


def _reading(name: str, ok: bool, detail: str) -> dict:
    return {"name": name, "ok": ok, "detail": detail}


def probe(root: Path) -> dict:
    """对一个目录做只读勘察，返回 {ok, kind, readings, mapping_hints}。"""
    readings: list[dict] = []

    own_files = [f for f in OWN_PIPELINE_FILES if (root / f).is_file()]
    readings.append(_reading(
        "own_pipeline_config", bool(own_files),
        "；".join(own_files) if own_files else "无 pipeline.toml / harness.toml",
    ))
    trio_missing = [f for f in OWN_TRIO if not (root / f).is_file()]
    tools_dir = root / "tools"
    wb_tools = sorted(p.name for p in tools_dir.glob("wb_*.py")) if tools_dir.is_dir() else []
    trio_ok = not trio_missing and bool(wb_tools)
    readings.append(_reading(
        "own_trio", trio_ok,
        "三件套齐" if trio_ok else f"缺：{'、'.join(trio_missing) or 'tools/wb_*.py'}",
    ))

    foreign = [m for m in FOREIGN_MARKERS if (root / m).exists()]
    readings.append(_reading(
        "foreign_framework", bool(foreign),
        "；".join(foreign) if foreign else "未检出别家框架标记",
    ))

    test_hits = [s for s in TEST_SIGNALS if (root / s).exists()]
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            scripts = json.loads(pkg.read_text(encoding="utf-8")).get("scripts") or {}
            if "test" in scripts:
                test_hits.append("package.json#scripts.test")
        except (OSError, ValueError):
            test_hits.append("package.json(不可解析)")
    readings.append(_reading(
        "tests", bool(test_hits), "；".join(test_hits) if test_hits else "无测试信号",
    ))

    ci_hits = [s for s in CI_SIGNALS if (root / s).exists()]
    readings.append(_reading(
        "ci", bool(ci_hits), "；".join(ci_hits) if ci_hits else "无 CI 信号",
    ))

    src_ok = (root / "src").is_dir()
    readings.append(_reading("src", src_ok, "有 src/" if src_ok else "无 src/"))

    entries = [p for p in root.iterdir() if p.name != ".git"] if root.is_dir() else []
    readings.append(_reading(
        "content", bool(entries),
        f"{len(entries)} 个顶层条目" if entries else "空目录（除 .git）",
    ))

    if own_files or trio_ok:
        kind = "A"
    elif foreign:
        kind = "D"
    elif test_hits or ci_hits:
        kind = "B"
    else:
        kind = "C"

    return {
        "ok": True,
        "root": str(root),
        "kind": kind,
        "readings": readings,
        "mapping_hints": MAPPING_HINTS[kind],
    }


def strict_problems(result: dict) -> list[str]:
    """`--strict` 的判据：类别必须有**正证据**支撑，否则算「判不出」。

    ★ 卡 A311 的来由：`kind` 总会给出一个字母（兜底 C），于是「信息不足」和
      「真的是裸仓」看起来一样。strict 把这两者分开：空目录 / 无任何信号 ⇒ 返回问题，
      调用方（技能第一步）据此停手，不许往下猜。
    """
    problems: list[str] = []
    if not result.get("ok"):
        return [str(result.get("error") or "勘察失败")]

    by_name = {r["name"]: r for r in result.get("readings") or []}
    kind = result.get("kind")

    if kind == "C":
        content = by_name.get("content")
        if not (content and content.get("ok")):
            problems.append(
                "判成 C（裸仓）但目录里没有任何内容 —— 缺：源码 / 测试 / CI / 管线任一信号"
            )
    if kind == "A":
        own = (by_name.get("own_pipeline_config", {}).get("ok")
               or by_name.get("own_trio", {}).get("ok"))
        if not own:
            problems.append(
                "判成 A 但没找到自己的管线文件（pipeline.toml / harness.toml / 三件套）"
            )
    if kind == "B":
        borrowed = (by_name.get("tests", {}).get("ok")
                    or by_name.get("ci", {}).get("ok"))
        if not borrowed:
            problems.append("判成 B 但测试与 CI 信号都为无")
    if kind == "D" and not by_name.get("foreign_framework", {}).get("ok"):
        problems.append("判成 D 但没检出别家框架标记")

    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="只读勘察器：把旧项目目录分类成 A/B/C/D")
    ap.add_argument("--root", required=True, help="要勘察的目录")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument(
        "--strict", action="store_true",
        help="判据严格模式：类别没有正证据支撑（如空目录）⇒ 退 2 并点名缺什么（卡 A311）",
    )
    args = ap.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        err = f"目录不存在：{root}"
        if args.json:
            print(json.dumps({"ok": False, "error": err}, ensure_ascii=False))
        else:
            print(f"[FAIL] {err}", file=sys.stderr)
        return 2

    result = probe(root.resolve())
    problems = strict_problems(result) if args.strict else []
    if args.json:
        payload = dict(result)
        if args.strict:
            payload["strict_ok"] = not problems
            payload["strict_problems"] = problems
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"类别：{result['kind']}（{result['root']}）")
        for r in result["readings"]:
            print(f"  {'[有]' if r['ok'] else '[无]'} {r['name']}：{r['detail']}")
        print("映射提示：")
        for h in result["mapping_hints"]:
            print(f"  - {h}")
    if problems:
        for line in problems:
            print(f"[FAIL] {line}", file=sys.stderr)
        print("★ --strict：判据不足，停手；先补读数，别猜类别", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
