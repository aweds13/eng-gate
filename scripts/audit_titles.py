"""台账 ↔ 规格 「标题对账」（T-D2 的产物）：抓「编号在、含义错」这类躲过审计的漂移。

**为什么需要它**（2026-09-20 实测教训）：`audit_progress.py` 的「规格覆盖」是
`sr_ids - set(entries)` —— 只要**编号**在台账里存在就算通过，**不比对标题/含义**。
于是台账里 `SR-NF2`~`SR-NF12` 写的是规格**前一条**的内容（整体错位一格）也能一直"通过"。
本脚本把这一步补上：把台账条目的标题与规格里的同名条目标题做**内容字重叠度**比对。

判据（故意简单、可解释）：
- 取「内容字」集合 = 中文 + 字母数字，去掉标点与常见虚词；
- 重叠度 = 交集 ÷ 并集（Jaccard）；
- **`shifted`（确定错位）**：与**相邻编号**的规格标题重叠明显高于与自己的 —— 这就是
  「条目写的是前一条/后一条的要求」，可以直接当失败用；
- **`unmapped`（无规格对应）**：台账里出现了规格里没有的 `SR-*` 编号 —— 违反 2026-09-20
  定下的编号规则 A（**规格号只属于规格**），也是失败；
- `needs_review`（需人核对）：与自己那条几乎不重合，但也不像邻居 —— 多半是"缩写式改写"
  （规格标题很短时如「视觉美感」「配置工程化」，台账写的是具体做法），**也可能是真错**，要人看一眼；
- 其它 → 通过。

## 编号规则 A（2026-09-20 用户定，本脚本按它判）

1. `SR-Fx.y` / `SR-NFnn` —— **规格条目**，台账条目的含义必须与规格一致（标题建议以规格原词开头）；
2. 一条规格被拆成多张卡 → 加小写后缀（`SR-F1.1a` / `SR-F1.1b`），后缀卡算**同一个规格条目**；
3. 不属于任何规格条目的**实现层自造卡** → 只用 `T-*` / `STEP-*` / `OP-*`，**不许**用 `SR-` 前缀。

落地经过见 `复盘/台账编号校正-方案A落地.md`。

用法
  python -X utf8 scripts/audit_titles.py            # 打印对账表（人类可读）
  python -X utf8 scripts/audit_titles.py --json     # 机器可读
  python -X utf8 scripts/audit_titles.py --check    # 有「确定错位」或「无规格对应」就退出码 1

**已接进门禁（2026-09-20，T-D2 收口）**：`scripts/run_gates.py` 的 `audit_titles` 步骤
（阻断项，`--check`）。校正前它挂的是"信息性"（`blocking=false`）—— 那段历史见上面提到的复盘文档。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs" / "traceability.toml"
FUNCTIONAL = ROOT / "docs" / "specification" / "functional.md"
NONFUNCTIONAL = ROOT / "docs" / "specification" / "nonfunctional.md"

# 虚词/套话：这些字不算"内容"，否则任何两条中文标题都会"重合"
STOP_CHARS = set(
    "的了与和及或在为对做要不要能否可用于按用给把被从到中上下一二字个条件条项点实现支持必须"
    "提供显示记录当前可用类等及其它其他每个系统支持"
)
# 规格标题里的括注（N 编号、一版/二版、口径调整说明）先剥掉
_PAREN = re.compile(r"[（(][^）)]*[）)]")
# 拆卡后缀：一条规格被拆成多张卡时用（规则 A）
_SUFFIX = re.compile(r"^(SR-(?:F\d+(?:\.\d+)?|NF\d+))[a-z]$")


def base_id(eid: str) -> str:
    """去掉拆卡后缀，得到规格条目的基号（`SR-F1.1a` → `SR-F1.1`）。"""
    m = _SUFFIX.match(eid)
    return m.group(1) if m else eid


def extract_spec_titles() -> dict[str, str]:
    """从规格文档抽 `SR-xxx → 标题`（两种写法都要认）。

    - `docs/specification/nonfunctional.md`：`## SR-NF13 · 可观测/日志审计（N42）——一版`
    - `docs/specification/functional.md`：`- **SR-F1.2**（N7，一版）～ 提供视图：…`
    续行（规格里偶尔换行）按"读到下一个条目为止"拼接。
    """
    titles: dict[str, str] = {}

    for line in NONFUNCTIONAL.read_text(encoding="utf-8").splitlines():
        m = re.match(r"##\s*(SR-NF\d+)\s*·\s*(.+)", line.strip())
        if m:
            titles[m.group(1)] = _clean(m.group(2))

    lines = FUNCTIONAL.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"-\s*\*\*(SR-F\d+(?:\.\d+)?)\*\*.*?～\s*(.*)", line.strip())
        if not m:
            continue
        text = m.group(2)
        # 续行：后续以两个空格开头、且不是新条目的行，算同一条标题的一部分
        for nxt in lines[i + 1:]:
            if nxt.startswith("  ") and not nxt.strip().startswith("- **SR-"):
                text += " " + nxt.strip()
            elif not nxt.strip():
                break
            else:
                break
        titles[m.group(1)] = _clean(text)
    return titles


def _clean(text: str) -> str:
    text = _PAREN.sub("", text)
    text = text.split("——")[0]
    return text.strip().rstrip("。；;：")


def content_chars(text: str) -> set[str]:
    """内容字集合：中文 + 字母数字，去掉虚词。"""
    return {
        c
        for c in str(text)
        if (("\u4e00" <= c <= "\u9fff") or c.isalnum()) and c not in STOP_CHARS
    }


def overlap(ledger_title: str, spec_title: str) -> float:
    """标题重叠度（Jaccard，0~1）。两边都空 → 0（无法判定，按"疑似"处理）。"""
    a, b = content_chars(ledger_title), content_chars(spec_title)
    if not a or not b:
        return 0.0
    return round(len(a & b) / len(a | b), 3)


def _neighbours(ids: list[str], eid: str) -> list[str]:
    """同层里紧邻的编号（前一条 / 后一条）—— F 层按 (主号, 子号) 排，NF 层按数字排。"""
    if eid not in ids:
        return []
    i = ids.index(eid)
    out = []
    if i > 0:
        out.append(ids[i - 1])
    if i + 1 < len(ids):
        out.append(ids[i + 1])
    return out


def _sort_key(eid: str) -> tuple[int, int]:
    m = re.match(r"SR-F(\d+)(?:\.(\d+))?", eid)
    if m:
        return (int(m.group(1)), int(m.group(2) or 0))
    m = re.match(r"SR-NF(\d+)", eid)
    if m:
        return (100 + int(m.group(1)), 0)
    return (999, 0)


def compare() -> list[dict[str, object]]:
    """逐条对账，返回 `[{id, base, status, overlap, level, ...}]`。

    `level`：`shifted`（与相邻编号更像 → 确定错位）/ `unmapped`（规格里没有这个 `SR-*` 编号
    → 违反规则 A）/ `needs_review`（与自己的规格标题几乎不重合，但也不像邻居）/ `ok`。
    """
    spec = extract_spec_titles()
    data = tomllib.load(LEDGER.open("rb"))
    entries = data.get("entries", {})
    sr_entries = sorted((e for e in entries if str(e).startswith("SR-")), key=_sort_key)
    # 参与"邻居"比较的规格基号：台账里真有卡的才算
    bases = sorted({base_id(e) for e in sr_entries if base_id(e) in spec}, key=_sort_key)
    rows: list[dict[str, object]] = []
    for eid in sr_entries:
        title = str(entries[eid].get("title", ""))
        base = base_id(eid)
        row: dict[str, object] = {
            "id": eid,
            "base": base,
            "status": entries[eid].get("status"),
            "ledger_title": title,
            "spec_title": spec.get(base),
        }
        if base not in spec:
            row.update(overlap=0.0, level="unmapped", looks_like=None, looks_like_overlap=None)
            rows.append(row)
            continue
        own = overlap(title, spec[base])
        near: list[tuple[str, float]] = [
            (n, overlap(title, spec[n])) for n in _neighbours(bases, base)
        ]
        best_near = max(near, key=lambda x: x[1]) if near else ("", 0.0)
        shifted = best_near[1] >= 0.2 and best_near[1] - own >= 0.15
        if shifted:
            level = "shifted"
        elif own == 0:
            level = "needs_review"
        else:
            level = "ok"
        row.update(
            overlap=own,
            level=level,
            looks_like=best_near[0] if shifted else None,
            looks_like_overlap=best_near[1] if shifted else None,
        )
        rows.append(row)
    order = {"unmapped": 0, "shifted": 1, "needs_review": 2, "ok": 3}
    rows.sort(key=lambda r: (order[str(r["level"])], float(str(r["overlap"])), str(r["id"])))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="台账 ↔ 规格 标题对账")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--check", action="store_true", help="有「确定错位/无规格对应」就退出码 1")
    parser.add_argument("--all", action="store_true", help="连通过的一起打印")
    args = parser.parse_args()

    rows = compare()
    bad = [r for r in rows if r["level"] != "ok"]
    shifted = [r for r in rows if r["level"] == "shifted"]
    unmapped = [r for r in rows if r["level"] == "unmapped"]
    review = [r for r in rows if r["level"] == "needs_review"]
    if args.json:
        print(json.dumps(
            {
                "rows": rows,
                "problems": len(bad),
                "shifted": len(shifted),
                "unmapped": len(unmapped),
                "needs_review": len(review),
            },
            ensure_ascii=False,
            indent=2,
        ))
    else:
        print(f"=== 台账 ↔ 规格 标题对账（{len(rows)} 条可比） ===")
        shown = rows if args.all else bad
        for r in shown:
            if r["level"] == "shifted":
                near = float(str(r["looks_like_overlap"]))
                mark = f"❌ 确定错位（更像 {r['looks_like']}，重叠 {near:.2f}）"
            elif r["level"] == "unmapped":
                mark = "❌ 无规格对应（违反规则 A：SR- 只给规格条目用）"
            elif r["level"] == "needs_review":
                mark = "❓ 需人核对（与自己那条 0 重合）"
            else:
                mark = "✅"
            print(f"  {mark} {r['id']:<10} 重叠 {float(str(r['overlap'])):.2f}  [{r['status']}]")
            print(f"        台账「{r['ledger_title']}」")
            print(f"        规格「{r['spec_title'] or '（规格里没有这个编号）'}」")
        if not bad:
            print("  ✅ 全部对得上（标题含义与规格一致）")
            print(f"  OK 规则 A 对账通过：{len(rows)} 条 SR 卡全部有同号规格，0 条错位")
        else:
            print(f"\n共 {len(bad)} 条要处理：**{len(shifted)} 条确定错位** + "
                  f"{len(unmapped)} 条无规格对应 + {len(review)} 条需人核对")
            print("  说明：「需人核对」里有**假阳性**（规格标题很短时，如「视觉美感」"
                  "「配置工程化」，台账写的是具体做法，看着 0 重合其实对得上）"
                  "—— 要人看一眼，别当失败（`--check` 不因它退 1）。")
            print("→ 编号规则与落地经过见 `复盘/台账编号校正-方案A落地.md`")
    return 1 if (args.check and (shifted or unmapped)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
