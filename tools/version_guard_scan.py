r"""version_guard_scan —— 只读扫描：找出 src/ 里「先 SELECT → 再 UPDATE」的读-改-写函数，
列出哪些 UPDATE 带 `AND version = ?`（乐观锁守卫）、哪些没有（卡 164 / INV-61 / T-G264）。

为什么要有它（INV-61）：「读-改-写必须有版本守卫」只覆盖了 myday 一列（`_write_myday_rank`）；
新写一个读-改-写路径，**没有任何东西会问它要不要版本守卫**。这条扫描把那个通则变成**机器能看见**
的清单 —— 不是自动补守卫（那要人判），是「缺守卫的地方至少列得出来」。

用法：
    python -X utf8 tools/version_guard_scan.py              # 扫 src/，人读报告
    python -X utf8 tools/version_guard_scan.py --json       # 机器可读
    python -X utf8 tools/version_guard_scan.py --path src/  # 自选目录

★ 只读：不写任何文件、不改任何代码。
★ 判据口径（保守、宁可多报不漏报）：
  - 「读-改-写」= 同一函数体内**既**出现 SELECT **又**出现 UPDATE（字符串常量 / f-string 片段）；
  - 「有守卫」= 该 UPDATE 语句的文本里含 `version = ?` 或 `and version =`（大小写不敏感）；
  - 「无守卫」= UPDATE 不含上述守卫标记 —— **可能**是 upsert（`ON CONFLICT ... DO UPDATE`，
    语义不同）、**可能**是迁移回填、**可能**是真缺守卫。扫描都列出来，由人判哪条要补；
  - upsert（`ON CONFLICT ... DO UPDATE`）单独标 `.upsert`，不混进「无守卫」计数（语义不同族）。
★ 钉子（tests/test_version_guard_scan.py）：合成一个无守卫的读-改-写函数 ⇒ 必须被抓。
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

ROOT = Path(__file__).resolve().parent.parent


def _strs_in_node(node: ast.AST) -> Iterable[str]:
    """产出节点里所有**字符串常量**的值（含 f-string 整体拼接 + 拼接字符串各段）。

    ★ f-string（`JoinedStr`）的各 `Constant` 片段要**拼成一个整体**再判 ——
      `f"UPDATE tasks SET {set_clause} WHERE id = ? AND version = ?"` 被拆成
      `"UPDATE tasks SET "` + `" WHERE id = ? AND version = ?"`，守卫在第二段、
      UPDATE 在第一段，分开判会漏掉守卫。
    ★ JoinedStr 拼接后**不再下钻**它的子 Constant（否则同一片段会被重复处理：
      一次作为拼接整体、一次作为孤立片段，后者没守卫 ⇒ 误判无守卫）。
    """
    stack: list[ast.AST] = [node]
    while stack:
        cur = stack.pop()
        if isinstance(cur, ast.JoinedStr):
            parts: list[str] = []
            for val in cur.values:
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    parts.append(val.value)
            if parts:
                yield "".join(parts)
            continue                    # 不下钻 JoinedStr 的子节点
        if isinstance(cur, ast.Constant) and isinstance(cur.value, str):
            yield cur.value
        stack.extend(ast.iter_child_nodes(cur))


_SELECT_RE = re.compile(r"\bselect\b", re.IGNORECASE)
_UPDATE_RE = re.compile(r"\bupdate\b", re.IGNORECASE)
_UPSERT_RE = re.compile(r"\bon\s+conflict\b.*\bdo\s+update\b", re.IGNORECASE)
_GUARD_RE = re.compile(r"version\s*=\s*\?|and\s+version\s*=", re.IGNORECASE)


def _classify(sql_text: str) -> str:
    """这条 SQL 是什么：select / update / upsert / other。"""
    if _UPSERT_RE.search(sql_text):
        return "upsert"
    if _UPDATE_RE.search(sql_text):
        return "update"
    if _SELECT_RE.search(sql_text):
        return "select"
    return "other"


def scan_function(func_node: ast.FunctionDef | ast.AsyncFunctionDef,
                  file: Path) -> dict | None:
    """一个函数若含 UPDATE（非 upsert），返回它的扫描结果；否则 None。

    返回结构：
      {name, file, line, read_modify_write, updates: [...], guarded, why}
    `read_modify_write` = 同体还含 SELECT（上层读-改-写）；只 UPDATE 不 SELECT = 底层写 helper。
    `guarded` = 所有非 upsert UPDATE 都带 version 守卫。
    """
    has_select = False
    updates: list[dict] = []
    for text in _strs_in_node(func_node):
        kind = _classify(text)
        if kind == "select":
            has_select = True
        elif kind == "update":
            updates.append({
                "sql": text.strip()[:160],
                "guarded": bool(_GUARD_RE.search(text)),
                "is_upsert": False,
            })
        elif kind == "upsert":
            updates.append({
                "sql": text.strip()[:160],
                "guarded": True,     # upsert 不要求 version 守卫
                "is_upsert": True,
            })
    real_updates = [u for u in updates if not u.get("is_upsert")]
    if not real_updates:
        return None                 # 只有 upsert / 没 UPDATE，不报
    guarded = all(u["guarded"] for u in real_updates)
    unguarded_n = sum(1 for u in real_updates if not u["guarded"])
    return {
        "name": func_node.name,
        "file": str(file.relative_to(ROOT)) if file.is_relative_to(ROOT) else str(file),
        "line": func_node.lineno,
        "read_modify_write": has_select,
        "updates": updates,
        "guarded": guarded,
        "why": ("所有 UPDATE 带 version 守卫" if guarded else
                f"{unguarded_n} 条 UPDATE 无 version 守卫"),
    }


def scan_path(path: Path) -> list[dict]:
    """扫一棵树（目录或单文件），返回所有读-改-写函数的扫描结果。"""
    files = sorted(path.rglob("*.py")) if path.is_dir() else [path]
    out: list[dict] = []
    for file in files:
        try:
            tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                hit = scan_function(node, file)
                if hit is not None:
                    out.append(hit)
    return out


def render_report(rows: list[dict]) -> str:
    """人读报告：有守卫 / 无守卫分组，各列 file:line name。"""
    guarded = [r for r in rows if r["guarded"]]
    unguarded = [r for r in rows if not r["guarded"]]
    n, g, u = len(rows), len(guarded), len(unguarded)
    lines = [
        f"=== 读-改-写扫描（INV-61）：共 {n} 处 · 有守卫 {g} · 无守卫 {u} ===",
        "",
        f"-- 有守卫（{g}）",
    ]
    for r in sorted(guarded, key=lambda x: (x["file"], x["line"])):
        lines.append(f"  {r['file']}:{r['line']}  {r['name']}")
    lines += ["", f"-- 无守卫（{len(unguarded)}）—— 需人判哪条要补 / 哪条是 upsert 或迁移"]
    for r in sorted(unguarded, key=lambda x: (x["file"], x["line"])):
        lines.append(f"  {r['file']}:{r['line']}  {r['name']}  —— {r['why']}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="只读扫描 src/ 里读-改-写函数的版本守卫情况")
    ap.add_argument("--path", default=str(ROOT / "src"), help="要扫的目录（默认 src/）")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args()
    rows = scan_path(Path(args.path))
    if args.json:
        print(json.dumps({"total": len(rows),
                          "guarded": sum(1 for r in rows if r["guarded"]),
                          "unguarded": sum(1 for r in rows if not r["guarded"]),
                          "rows": rows}, ensure_ascii=False, indent=2))
    else:
        print(render_report(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
