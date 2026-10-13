r"""判据：`docs/工作台-不建模清单.md` 每条**必须四样齐**（卡 219 · 批 B-20261016 · T-G333）。

为什么有它（用户 2026-10-13 笔记，意译「把不建模的东西写下来」）：一个系统里最容易被人
「顺手加进去」的，就是当初明确决定不做的东西；这些东西此前没有一处权威、也没东西拦住违反。
这份清单把「决定不做」写成可核对的条目 —— 每条四样：

    **不建什么 · 为什么不做 · 谁拍的 · 替代做法**

四样缺一 ⇒ 红，并**点名**是哪一条、缺哪一样。
另加一样 **出处**（卡规格的 ★ 要求：每条都要能指回出处）。

★ 反向保护（两条都要）：
  ① 清单文件**不存在** ⇒ 报「没有」，**不许当通过**（没有 ≠ 通过）；
  ② 一条都解析不到 ⇒ 报「0 条」，同样**不许当通过**。

★ 判据只管**结论区**（`### NM-<号>` 条目）。清单末尾另有一节「我记得、但找不到出处」（用
  `- ` 列表，不是 `### NM-` 标题）——那是**如实标注、不作为结论**，判据**不判**它。

用法：
    python -X utf8 tools/notmodel_audit.py            # 查默认清单（本仓 docs/）
    python -X utf8 tools/notmodel_audit.py --path <文件>
退出码：0 = 全过；1 = 有问题（缺样 / 没有 / 0 条）。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: 默认清单（相对本仓根）。
DEFAULT_PATH = ROOT / "docs" / "工作台-不建模清单.md"

#: 每条**必须**齐的五样（卡规格的四样 + ★ 出处）。
REQUIRED_FIELDS = ("不建什么", "为什么不做", "谁拍的", "替代做法", "出处")

#: 条目标题：`### NM-<号> <标题>`。只有这种标题才算「结论条目」。
_ITEM_RE = re.compile(r"^###\s+(NM-\d+)\b[ \t]*(.*)$")


def split_items(text: str) -> list[dict[str, str]]:
    """把清单切成「结论条目」列表。

    条目 = 以 `### NM-<号> …` 开头的一块；它到**下一个标题**（`#`/`##`/`###` 任意一级）为止。
    末尾「找不到出处」那节用 `- ` 列表、不是 `### NM-` 标题 ⇒ 不会落进这里（判据不判它）。
    """
    items: list[dict[str, str]] = []
    cur: dict[str, str] | None = None
    for line in text.splitlines():
        m = _ITEM_RE.match(line)
        if m:
            if cur is not None:
                items.append(cur)
            cur = {"id": m.group(1), "title": m.group(2).strip(), "body": ""}
            continue
        if cur is not None:
            if line.startswith("#"):      # 下一节（含 `##` 找不到出处节）⇒ 收掉当前条
                items.append(cur)
                cur = None
                continue
            cur["body"] += line + "\n"
    if cur is not None:
        items.append(cur)
    return items


def check_doc(path: Path | str = DEFAULT_PATH) -> list[str]:
    """检查一份清单。返回问题列表（空 = 全过）。

    ★ 不许「没有就当通过」：文件不存在 ⇒ 报「没有」；解析到 0 条 ⇒ 报「0 条」。
    """
    p = Path(path)
    if not p.exists():
        return [f"没有这份清单（找不到 {p}）—— 没有 ≠ 通过，须先把清单写出来"]
    text = p.read_text(encoding="utf-8", errors="replace")
    items = split_items(text)
    if not items:
        return [f"清单里一条「### NM-<号>」条目都没解析到（{p}）—— 0 条 ≠ 通过"]
    problems: list[str] = []
    for item in items:
        missing = [field for field in REQUIRED_FIELDS if field not in item["body"]]
        if missing:
            problems.append(
                f"{item['id']}「{item['title']}」缺：{'、'.join(missing)}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="判据：不建模清单每条须四样齐（不建什么/为什么不做/谁拍的/替代做法）+ 出处")
    ap.add_argument("--path", default=str(DEFAULT_PATH),
                    help=f"清单文件（默认 {DEFAULT_PATH.name}）")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    path = Path(args.path)
    problems = check_doc(path)
    if problems:
        print("[FAIL] 不建模清单：四样不齐 ——", file=sys.stderr)
        for p in problems:
            print(f"  · {p}", file=sys.stderr)
        print(f"[FAIL] 不建模清单：{len(problems)} 条有问题（文件 {path}）", file=sys.stderr)
        return 1
    items = split_items(path.read_text(encoding="utf-8", errors="replace"))
    print(f"[OK ] 不建模清单：{len(items)} 条，每条四样 + 出处齐（文件 {path}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
