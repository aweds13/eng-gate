"""归置机械码的执行器 —— **只认** `docs/归置-机械码.toml` 一个文件（卡 087 / 台账号 T-G182）。

## 一句话
搬迁要「锁死，但允许的话就能搬」：没列进 `[allow]` 的一律不许搬；`[lock]` **永远优先**于
`[allow]`；`[regroup]` 只打标签、**不动任何文件**（`index` 现算、**不落盘**）。

## 唯一一套优先级（别处不许再写第二份口径）
`[regroup.exact]` **先于** `[regroup.rules]` —— 具体（逐条路径）盖过通配（glob）；
多条规则命中同一文件时，以机械码里的**先后**为准，先命中者赢。

## 子命令
- `check`（默认，只读）：三张表 —— **待搬** / **锁定** / ★**幽灵条目**（策略里写了、盘上找不到；
  非空 → 退 2）。
- `apply`：只搬 `[allow]`；每条**搬前逐条复核**（在盘上？没被 `[lock]` 命中？不在禁区？目标可写？）
  → 任一不过就**跳过并计数**；真搬动的写成**搬动记录**（供 `undo`）。
- `undo`：按搬动记录**原样回退**（幂等：没有记录的再跑一次是空操作）。
- `index`：按 `[regroup]` **现算**一张索引**打印**（★ **不落盘**）；`--by <归属>` 只打一桶。

## 禁区（**硬编码**，机械码也不许放行）
`src/**` · `pyproject.toml` · `.wt/**` · `gates*.lock` · 主树 4 个外来 md · `data/`。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent
CODE = ROOT / "docs" / "归置-机械码.toml"

# ★ 禁区（硬编码）：机械码也放行不了。相对仓库根（posix）。
FORBIDDEN_DIRS = ("src/", ".wt/", "data/")
FORBIDDEN_EXACT = (
    "pyproject.toml",
    "DSH-技能与插件开发参考.md",
    "DSH-窗口化方案.md",
    "Hermes-数据位置.md",
    "dsh-skill-docs-report.zh.md",
)

_RE_CACHE: dict[str, re.Pattern[str]] = {}


def _glob_re(pat: str) -> re.Pattern[str]:
    """把机械码里的 glob 编成正则：`*` 不跨 `/`、`**` 跨 `/`、`?` 一个非 `/` 字符。"""
    if pat not in _RE_CACHE:
        out: list[str] = []
        i = 0
        while i < len(pat):
            ch = pat[i]
            if ch == "*":
                if i + 1 < len(pat) and pat[i + 1] == "*":
                    out.append(".*")
                    i += 2
                    if i < len(pat) and pat[i] == "/":
                        i += 1
                    continue
                out.append("[^/]*")
            elif ch == "?":
                out.append("[^/]")
            else:
                out.append(re.escape(ch))
            i += 1
        _RE_CACHE[pat] = re.compile("^" + "".join(out) + "$")
    return _RE_CACHE[pat]


def matches(rel: str, pat: str) -> bool:
    """`rel`（posix 相对路径）是否命中 glob `pat`。"""
    return bool(_glob_re(pat).match(rel))


def load_code(path: Path) -> dict:
    """读机械码那一个文件（工具不内置任何"应搬清单"）。"""
    return tomllib.loads(path.read_text(encoding="utf-8"))


def lock_hit(rel: str, lock: dict[str, str]) -> str | None:
    """`rel` 命中的第一条 `[lock]` 规则（命中即锁死；没有则 None）。"""
    for pat in lock:
        if matches(rel, pat):
            return pat
    return None


def forbidden(rel: str) -> str | None:
    """命中硬编码禁区就返回理由（否则 None）。"""
    if rel in FORBIDDEN_EXACT:
        return "硬编码禁区（主树外来件/构建件）"
    if any(rel == d[:-1] or rel.startswith(d) for d in FORBIDDEN_DIRS):
        return "硬编码禁区（目录）"
    if matches(rel.rsplit("/", 1)[-1], "gates*.lock"):
        return "硬编码禁区（门禁锁）"
    return None


def glob_files(root: Path, pat: str) -> list[str]:
    """盘上命中 glob 的文件（posix 相对路径，字典序）。"""
    return sorted(p.relative_to(root).as_posix() for p in root.glob(pat) if p.is_file())


def spec_to(spec: object) -> str:
    """取 `[allow]` 一行的目标目录（`to`）。"""
    if isinstance(spec, dict):
        return str(spec.get("to", ""))
    return ""


# ---------------------------------------------------------------- 三张表 / index

def pending(root: Path, code: dict) -> list[tuple[str, str]]:
    """**待搬**：在 `[allow]`、盘上存在、且**不在** `[lock]`、也不在禁区。"""
    lock = code.get("lock", {})
    out: list[tuple[str, str]] = []
    for rel, spec in code.get("allow", {}).items():
        if not (root / rel).exists():
            continue
        if lock_hit(rel, lock) or forbidden(rel):
            continue
        out.append((rel, spec_to(spec)))
    return out


def locked_table(root: Path, code: dict) -> list[tuple[str, str, int]]:
    """**锁定**：`[lock]` 每条规则 + 盘上命中数。"""
    out: list[tuple[str, str, int]] = []
    for pat, why in code.get("lock", {}).items():
        out.append((pat, str(why), len(glob_files(root, pat))))
    return out


def ghosts(root: Path, code: dict) -> list[tuple[str, str]]:
    """★**幽灵条目**：`[allow]` 与 `[regroup.exact]` 里写了、盘上却找不到的**字面路径**。"""
    out: list[tuple[str, str]] = []
    for rel in code.get("allow", {}):
        if not (root / rel).exists():
            out.append((rel, "[allow]"))
    for rel in code.get("regroup", {}).get("exact", {}):
        if not (root / rel).exists():
            out.append((rel, "[regroup.exact]"))
    return out


def compute_index(root: Path, code: dict) -> dict[str, str]:
    """按 `[regroup]` 现算 `{rel: 归属}`：规则先铺、exact 再盖（exact 优先）。"""
    regroup = code.get("regroup", {})
    result: dict[str, str] = {}
    for pat, label in regroup.get("rules", {}).items():
        for rel in glob_files(root, pat):
            result.setdefault(rel, str(label))  # 先命中者赢
    for rel, label in regroup.get("exact", {}).items():
        result[rel] = str(label)  # exact 盖过 rules（具体优先）
    return result


# ---------------------------------------------------------------- 子命令

def cmd_check(root: Path, code: dict) -> int:
    print("=== 待搬（在 [allow]、盘上有、且不在 [lock]/禁区）===")
    rows = pending(root, code)
    for rel, to in rows:
        print(f"  {rel}  ->  {to or '（未写 to）'}")
    print(f"  （{len(rows)} 条）")
    print("=== 锁定（[lock] 命中，永远不许搬）===")
    for pat, why, n in locked_table(root, code):
        print(f"  {pat:<40} 命中 {n:>3} 个  | {why}")
    print("=== 幽灵条目（策略里写了、盘上找不到）===")
    gh = ghosts(root, code)
    for rel, where in gh:
        print(f"  [幽灵] {rel}  （来自 {where}）")
    print(f"  （{len(gh)} 条）")
    if gh:
        print(f"[FAIL] 幽灵条目 {len(gh)} 条 —— 策略与盘上对不上，先修机械码")
        return 2
    print("[OK ] 无幽灵条目")
    return 0


def cmd_apply(root: Path, code: dict, journal: Path) -> int:
    lock = code.get("lock", {})
    moved: list[dict[str, str]] = []
    skipped: list[tuple[str, str]] = []
    for rel, spec in code.get("allow", {}).items():
        src = root / rel
        if not src.exists():
            skipped.append((rel, "源不在盘上"))
            continue
        hit = lock_hit(rel, lock)
        if hit:
            skipped.append((rel, f"被 [lock] 命中：{hit}"))
            continue
        forb = forbidden(rel)
        if forb:
            skipped.append((rel, forb))
            continue
        to = spec_to(spec)
        if not to:
            skipped.append((rel, "没写 to"))
            continue
        dst_dir = root / to
        try:
            dst_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # 目标不可写
            skipped.append((rel, f"目标不可写：{exc}"))
            continue
        dst = dst_dir / src.name
        if dst.exists():
            skipped.append((rel, f"目标已存在：{dst.relative_to(root).as_posix()}"))
            continue
        shutil.move(str(src), str(dst))
        moved.append({"from": rel, "to": dst.relative_to(root).as_posix()})
    if moved:
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text(json.dumps({"moves": moved}, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print(f"[OK ] 搬了 {len(moved)} 个；跳过 {len(skipped)} 个")
    for rel, why in skipped:
        print(f"  [跳过] {rel} —— {why}")
    return 0


def _prune_empty(root: Path, d: Path) -> None:
    """回退后，把 `apply` 现建出来的**空**目标目录一并收掉（只收空的，收到 root 为止）。"""
    while d != root and d.is_dir():
        try:
            d.rmdir()
        except OSError:
            break
        d = d.parent


def cmd_undo(root: Path, journal: Path) -> int:
    if not journal.exists():
        print("[OK ] 没有搬动记录，无需回退")
        return 0
    moves = json.loads(journal.read_text(encoding="utf-8")).get("moves", [])
    undone = 0
    for mv in reversed(moves):
        cur, back = root / mv["to"], root / mv["from"]
        if not cur.exists():
            continue  # 已经回退过（幂等）
        back.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(cur), str(back))
        _prune_empty(root, cur.parent)
        undone += 1
    journal.write_text(json.dumps({"moves": []}, ensure_ascii=False), encoding="utf-8")
    print(f"[OK ] 回退 {undone} 个（记录已清空，空目录已收）")
    return 0


def cmd_index(root: Path, code: dict, by: str | None) -> int:
    idx = compute_index(root, code)
    labels = sorted({v for v in idx.values()})
    total: dict[str, int] = {}
    for label in idx.values():
        total[label] = total.get(label, 0) + 1
    print("=== 归属计数（现算，不落盘）===")
    for label in labels:
        print(f"  {label:<8} {total[label]}")
    print(f"  {'合计':<8} {len(idx)}")
    print(f"=== 索引{'（只看 '+by+'）' if by else ''} ===")
    for rel in sorted(idx):
        if by and idx[rel] != by:
            continue
        print(f"  {idx[rel]:<8} {rel}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="relocate.py", description="归置机械码执行器（只认 docs/归置-机械码.toml）")
    ap.add_argument("--code", type=Path, default=CODE, help="机械码文件")
    ap.add_argument("--root", type=Path, default=ROOT, help="在哪棵树上算/搬")
    ap.add_argument("--journal", type=Path, default=None, help="搬动记录路径")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("check", help="只读：待搬 / 锁定 / 幽灵")
    sub.add_parser("apply", help="只搬 [allow]（逐条复核，跳过计数）")
    sub.add_parser("undo", help="按搬动记录回退（幂等）")
    p_index = sub.add_parser("index", help="按 [regroup] 现算索引（不落盘）")
    p_index.add_argument("--by", default=None, help="只看某个归属")
    args = ap.parse_args(argv)

    code = load_code(args.code)
    root = args.root
    journal = args.journal or (root / ".relocate-journal.json")
    if args.cmd == "apply":
        return cmd_apply(root, code, journal)
    if args.cmd == "undo":
        return cmd_undo(root, journal)
    if args.cmd == "index":
        return cmd_index(root, code, args.by)
    return cmd_check(root, code)


if __name__ == "__main__":
    raise SystemExit(main())
