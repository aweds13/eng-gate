"""台账 `group` 归类建议器（卡 096 · 台账号 `T-G191`）—— ★ **只读**，绝不写台账。

## 一句话
台账 `docs/traceability.toml` 每条有一个 `group`。历史上 `PROCESS` 曾堆到 200 条，
靠人一条条读标题、手工分桶（`T-G182`）。这个「读标题 → 猜归属」有**稳定规律**，
本工具把规律写成一张 `RULES` 表，**逐条给建议**；归类**仍由主控拍**，机器只出建议。

## 三个子命令（全部**只读**）
- `report`  现算分布（每组多少条）+ 与文件里现有 `group` 的**不一致清单**。
- `propose [--only GROUP]`  逐条给出「建议 group + 命中哪条规则 + 那句理由」。
- `check`  有不一致就退 1（可当门禁用），没有退 0。

## ★ 口径（与 `T-G182` 一致，别处不许再写第二份）
- 规则是**顺序**匹配、先命中者赢；四条规则见 `RULES`。
- 都命不中 → 留 `PROCESS` 并标「**判不了**」。★ **不许硬塞**。
- `check` 报「不一致」只针对**本工具管的五个桶**（`OUTSOURCE / ENGINEERING / OPS / RULES /
  PROCESS`）：现有 group 与建议 group 冲突才算冲突；**建议=判不了（`PROCESS`）不算冲突**；
  现有 group 不在五桶里（规格号 `F1`/`NF`/`OP`… 之类）**跳过不报**（那是另一条轴，本工具不管）。
- ★ 整个工具**不写任何文件**（含台账）。归类由主控拍。

用法：
    python -X utf8 tools/tf_group.py report [--ledger PATH]
    python -X utf8 tools/tf_group.py propose [--only PROCESS] [--ledger PATH]
    python -X utf8 tools/tf_group.py check [--ledger PATH]
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from typing import NamedTuple

import tomllib

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LEDGER = ROOT / "docs" / "traceability.toml"

# ★ 本工具管的五个桶；别的 group（规格号等）不归它管，见 `check` 口径。
MANAGED_GROUPS = ("OUTSOURCE", "ENGINEERING", "OPS", "RULES", "PROCESS")

# 一条建议 = `(建议 group, 命中规则名或 None, 理由)`
Suggestion = tuple[str, str | None, str]
# 一条不一致 = `(eid, 现在, 建议, 规则名, 理由, 标题)`
Conflict = tuple[str, str, str, str | None, str, str]


class Rule(NamedTuple):
    """一条归类规则：一串关键词 → 目标 group + 一句理由。"""

    group: str
    name: str
    reason: str
    words: tuple[str, ...]


# ★ 规则表：**顺序**匹配，先命中者赢。改口径就改这张表，别处不许再写第二份。
RULES: tuple[Rule, ...] = (
    Rule(
        "OUTSOURCE", "外包/派活/号池",
        "外包链路：派活器 / 号池 / 工人 / 看门狗 / worktree / 并发调度",
        ("外包", "派活", "号池", "工人", "看门狗", "worktree", "工作树",
         "并发", "调度", "台账号", "codebuddy", ".wt"),
    ),
    Rule(
        "ENGINEERING", "门禁/测试/构建/复用",
        "工程门禁与验证层：门禁 / 测试 / 构建 / 工具链 / 依赖 / 复用 / 封存",
        ("门禁", "测试", "构建", "工具链", "依赖", "复用", "封存", "pytest",
         "覆盖率", "断言", "回归", "指纹", "审计"),
    ),
    Rule(
        "OPS", "运维/端口/锁/清理",
        "工程运维：端口 / 锁 / 清理 / 进程 / 日志 / 磁盘 / 环境",
        ("运维", "端口", "锁", "清理", "进程", "日志", "磁盘", "环境", "备份", "恢复"),
    ),
    Rule(
        "RULES", "铁律/口径/协议/规矩/模板",
        "规矩与口径：铁律 / 口径 / 协议 / 规矩 / 模板 / 样板",
        ("铁律", "口径", "协议", "规矩", "模板", "样板", "规范"),
    ),
)

_UNCLASSIFIED = ("PROCESS", None, "判不了")


def classify(title: str) -> Suggestion:
    """一条标题 → `(建议 group, 命中规则名或 None, 理由)`；都命不中 → `PROCESS` 判不了。"""
    for rule in RULES:
        for word in rule.words:
            if re.search(re.escape(word), title, re.IGNORECASE):
                return rule.group, rule.name, rule.reason
    return _UNCLASSIFIED


def load_entries(ledger: Path) -> dict[str, dict]:
    """读台账的 `[entries.*]`（**只读**；path 不存在/坏 TOML 直接抛）。"""
    data = tomllib.loads(ledger.read_text(encoding="utf-8"))
    entries = data.get("entries", {})
    if not isinstance(entries, dict):
        raise ValueError(f"{ledger}: [entries] 不是表")
    return entries


def suggest_all(entries: dict[str, dict]) -> dict[str, Suggestion]:
    """对每条现算建议（不落盘）。"""
    return {eid: classify(str(entry.get("title", ""))) for eid, entry in entries.items()}


def inconsistency(entries: dict[str, dict], sugg: dict[str, Suggestion]) -> list[Conflict]:
    """不一致清单：`(eid, 现在, 建议, 规则名, 理由, 标题)`。

    口径：只对**五桶内**的现有 group 判；建议=判不了（PROCESS）不算冲突；
    非五桶（规格号等）跳过。
    """
    out: list[Conflict] = []
    for eid, entry in entries.items():
        now = str(entry.get("group", ""))
        if now not in MANAGED_GROUPS:
            continue
        got, rule_name, reason = sugg[eid]
        if got == "PROCESS" or got == now:
            continue
        out.append((eid, now, got, rule_name, reason, str(entry.get("title", ""))))
    return out


def _fmt_line(eid: str, now: str, got: str, rule_name: str | None, reason: str,
              title: str, width: int = 40) -> str:
    rule_txt = f'"{rule_name}"' if rule_name else "(无)"
    return (f"{eid} · 现在={now} · 建议={got} · 命中规则={rule_txt} · "
            f"理由={reason} · 标题={title[:width]}")


# ------------------------------------------------------------------ 子命令

def cmd_report(ledger: Path) -> int:
    entries = load_entries(ledger)
    sugg = suggest_all(entries)
    dist = Counter(g[0] for g in sugg.values())
    now_dist = Counter(str(e.get("group", "")) for e in entries.values())
    bad = inconsistency(entries, sugg)
    n_unclass = sum(1 for g in sugg.values() if g[0] == "PROCESS")
    print(f"已读台账：{ledger}（{len(entries)} 条）")
    print("现算分布（按建议 group；PROCESS 那格就是「判不了、原样留」）：")
    for grp in MANAGED_GROUPS:
        tail = f"（判不了 {n_unclass} 条，不硬塞）" if grp == "PROCESS" else ""
        print(f"  {grp:<12} {dist.get(grp, 0)}{tail}")
    print("现有 group 分布（对照）：")
    for grp, n in sorted(now_dist.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {grp:<12} {n}")
    print(f"不一致清单（{len(bad)} 条）：")
    if not bad:
        print("  （无）")
    for eid, now, got, rule_name, reason, title in bad:
        print("  " + _fmt_line(eid, now, got, rule_name, reason, title))
    return 0


def cmd_propose(ledger: Path, only: str | None) -> int:
    entries = load_entries(ledger)
    sugg = suggest_all(entries)
    n = 0
    for eid, entry in entries.items():
        now = str(entry.get("group", ""))
        if only is not None and now != only:
            continue
        got, rule_name, reason = sugg[eid]
        print(_fmt_line(eid, now, got, rule_name, reason, str(entry.get("title", ""))))
        n += 1
    print(f"# 共 {n} 条" + (f"（只列 现在={only}）" if only is not None else ""))
    return 0


def cmd_check(ledger: Path) -> int:
    entries = load_entries(ledger)
    sugg = suggest_all(entries)
    bad = inconsistency(entries, sugg)
    if not bad:
        print(f"OK：{ledger} 无「现在 group 与建议 group 冲突」的条目")
        return 0
    print(f"FAIL：{ledger} 有 {len(bad)} 条与建议 group 冲突：")
    for eid, now, got, rule_name, reason, title in bad:
        print("  " + _fmt_line(eid, now, got, rule_name, reason, title))
    return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tf_group.py",
        description="台账 group 归类建议器（★ 只读，绝不写台账）",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_ledger(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--ledger", default=str(DEFAULT_LEDGER),
                        help="台账路径（默认 docs/traceability.toml；测试可指别处）")

    sp_report = sub.add_parser("report", help="现算分布 + 不一致清单")
    add_ledger(sp_report)
    sp_propose = sub.add_parser("propose", help="逐条给建议 group + 命中规则 + 理由")
    sp_propose.add_argument("--only", default=None,
                            help="只列「现在 group = 这个值」的条目（如 PROCESS）")
    add_ledger(sp_propose)
    sp_check = sub.add_parser("check", help="有不一致退 1，没有退 0")
    add_ledger(sp_check)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ledger = Path(args.ledger)
    if not ledger.is_file():
        print(f"台账不存在：{ledger}", file=sys.stderr)
        return 2
    if args.cmd == "report":
        return cmd_report(ledger)
    if args.cmd == "propose":
        return cmd_propose(ledger, args.only)
    return cmd_check(ledger)


if __name__ == "__main__":
    raise SystemExit(main())
