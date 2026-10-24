r"""文档归位迁移器：`复盘/卡/*.md` → `docs/cards/`（卡 F1 · T-AG449）。

## 为什么要有这一支

`复盘/` 长期是三类东西的合租房：真复盘 / 卡规格 / 交接片段（见 `docs/文档架构.md`）。
本工具只管**二期**：把卡规格这一**在飞的工作定义**搬进 `docs/cards/`，并把全仓的引用
**按同一张表**改写 —— 手改引用是这一层最容易漏的地方（漏一处 = 落地链 / 审计红）。

口径三条，改之前先读：

1. **只改路径，不改内容**。搬过去的文件正文除了路径前缀，一个字都不动；`revert` 之后
   整棵树（路径 + sha256）必须与迁移前**逐字节相同**。所以 journal 里存的是「原文 + 迁前/迁后
   sha」—— 还原照原文写回，写前先比 sha：文件被人动过就**拒跑**（不盖掉别人的改动）。
2. **先记账再动手**。`--apply` 第一步就把 old→new 全表写进 journal
   （默认 `gates/diag/doc-migration.json`），中途炸了也有据可查；`--revert` 只认这张表。
3. **搬完要自检**。改写面里还剩旧前缀 ⇒ 退 3（迁移没做完，不许报成功）。
   跳过清单里的残留只算「需人工」—— 那些是**拓扑数据**（比如"一条 复盘 路径应判为 复盘区"），
   机械改会把断言的语义改没，得人看一眼。

## 表长什么样

见 `docs/migration-map.json`：`moves`（glob → to_dir，按**期**分）、`rewrite`（改写根 /
后缀 / 跳过清单）、`code_probes`（迁移后**必须人手改**的代码点）、`candidates`（三期候选，
`verdict=pending` 的一律**不动**）。

## 用法

```bash
python -X utf8 tools/migrate_docs.py --dry-run     # 只算不写（默认模式）
python -X utf8 tools/migrate_docs.py --apply       # 搬 + 改写 + 自检
python -X utf8 tools/migrate_docs.py --check       # 只看残留 / 待人工 / 代码点
python -X utf8 tools/migrate_docs.py --revert      # 依 journal 还原（校验不过就拒跑）
```

退出码：`0` 成功 / `2` 前置不满足（缺源、目标冲突、表坏了、journal 缺）/
`3` 迁移已执行但**自检发现残留**（可 `--revert` 回到原状）。

★ 本工具**不起子进程**（没有 NO_WINDOW 问题），也**不碰** `gates/` 以外的东西：
journal 是它唯一的落盘产物。
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAP_REL = "docs/migration-map.json"
JOURNAL_REL = "gates/diag/doc-migration.json"

#: 扫盘时整目录跳过（版本库 / 卡树 / 门禁产物 / 缓存）。
SKIP_DIRS = frozenset(
    {
        ".git",
        ".wt",
        "gates",
        "node_modules",
        "__pycache__",
        ".ruff_cache",
        ".pytest_cache",
        "export",
        "logs",
        "dist",
        "build",
    }
)

#: 表里没写 `suffixes` 时的默认值（只改文本，二进制一个字节不动）。
DEFAULT_SUFFIXES = (
    ".md",
    ".toml",
    ".py",
    ".json",
    ".txt",
    ".yml",
    ".yaml",
    ".mjs",
    ".js",
    ".ps1",
    ".sh",
)


# ---------------------------------------------------------------- 基础工具


def _posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_text(path: Path) -> str:
    """原样读：`newline=""` 不做换行翻译（CRLF 进来就 CRLF 出去）。"""
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def _write_json(path: Path, payload: dict) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _prune_empty(path: Path, root: Path) -> None:
    """搬空之后把空目录收掉（`复盘/卡/` 空了就不该留着）；到 root 为止。"""
    while path != root and path.is_dir() and not any(path.iterdir()):
        path.rmdir()
        path = path.parent


def _skipped(rel: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if rel == pat or fnmatch.fnmatch(rel, pat):
            return True
        if pat.endswith("/**") and (rel == pat[:-3] or rel.startswith(pat[:-3] + "/")):
            return True
    return False


def _in_skip_dir(path: Path, root: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.relative_to(root).parts[:-1])


# ---------------------------------------------------------------- 表与计划


@dataclass(frozen=True)
class Move:
    """一次搬家：`old`/`new` 是仓库相对的 posix 路径。"""

    old: str
    new: str
    phase: str = ""
    kind: str = "file"  # file | dir
    prefix_old: str = ""
    prefix_new: str = ""

    def as_json(self, sha: str) -> dict:
        return {
            "old": self.old,
            "new": self.new,
            "phase": self.phase,
            "kind": self.kind,
            "prefix_old": self.prefix_old,
            "prefix_new": self.prefix_new,
            "sha256": sha,
        }


@dataclass
class Rewrite:
    """一个文件的改写：`rel_before` 读、`rel_after` 写（搬走的文件两者不同）。"""

    rel_before: str
    rel_after: str
    count: int
    before_sha: str
    after_sha: str
    before_text: str
    text_after: str


@dataclass
class Plan:
    moves: list[Move]
    pending: list[tuple[str, str]]
    rewrites: list[Rewrite]
    skipped: list[str]
    candidates: list[str]
    probes: list[str]
    problems: list[str]


def load_map(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1:
        raise ValueError(f"{path} 的 version 不是 1：{payload.get('version')!r}")
    if not isinstance(payload.get("moves", []), list):
        raise ValueError(f"{path} 的 moves 不是数组")
    return payload


def _expand_one(root: Path, rule: dict) -> tuple[list[Move], list[tuple[str, str]], list[str]]:
    """一条迁移规则 → `(搬家清单, 已迁移清单, 问题清单)`。"""
    phase = rule.get("phase", "")
    if "glob" in rule:
        pattern = rule["glob"]
        to_dir = rule["to_dir"].rstrip("/")
        hits = sorted(p for p in root.glob(pattern) if p.is_file())
        prefix_old = pattern.rsplit("/", 1)[0] if "/" in pattern else ""
        prefix_new = to_dir
        if not hits:
            # 幂等分支：源已搬空、目标里有东西 ⇒ 上一轮跑过了
            if (root / to_dir).is_dir() and any((root / to_dir).glob("*.md")):
                return [], [(pattern, to_dir)], []
            return [], [], [f"{pattern} 一条都没匹配到，且 {to_dir}/ 里也没有东西"]
        moves = [
            Move(
                old=_posix(p, root),
                new=f"{to_dir}/{p.name}",
                phase=phase,
                kind="dir",
                prefix_old=prefix_old,
                prefix_new=prefix_new,
            )
            for p in hits
        ]
        return moves, [], []

    old = rule["from"].rstrip("/")
    new = rule["to"].rstrip("/")
    if (root / old).exists() and (root / new).exists():
        return [], [], [f"目标已存在，拒覆盖：{new}"]
    if not (root / old).exists():
        if (root / new).exists():
            return [], [(old, new)], []
        return [], [], [f"源不存在：{old}"]
    return [Move(old=old, new=new, phase=phase)], [], []


def expand_moves(root: Path, mapping: dict) -> tuple[list[Move], list[tuple[str, str]], list[str]]:
    moves: list[Move] = []
    pending: list[tuple[str, str]] = []
    problems: list[str] = []
    for rule in mapping.get("moves", []):
        got, already, bad = _expand_one(root, rule)
        moves.extend(got)
        pending.extend(already)
        problems.extend(bad)

    old_slots = {m.old: m for m in moves}
    new_slots = {m.new: m for m in moves}
    if len(old_slots) != len(moves):
        problems.append("这张表把同一个源写了两遍（old 重复）")
    if len(new_slots) != len(moves):
        problems.append("这张表把两个源搬到同一个目标（new 重复）")
    for move in moves:
        if (root / move.new).exists():
            problems.append(f"目标已存在，拒覆盖：{move.new}")
    return moves, pending, problems


def substitution_pairs(moves: list[Move]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """`(单文件对, 目录前缀对)`。目录前缀对去重（222 张卡只需一条）。"""
    exact: list[tuple[str, str]] = []
    prefixes: list[tuple[str, str]] = []
    for move in moves:
        if move.kind == "dir":
            pair = (move.prefix_old, move.prefix_new)
            if pair not in prefixes:
                prefixes.append(pair)
        else:
            exact.append((move.old, move.new))
    return exact, prefixes


def substitute(
    text: str,
    exact: list[tuple[str, str]],
    prefixes: list[tuple[str, str]],
) -> tuple[str, int]:
    """按 `(旧, 新)` 改写文本；返回 `(新文本, 命中次数)`。

    目录前缀要认四种写法（`旧/`、`旧\\`、`旧\\\\`、裸 `旧`），裸的那种**带负向前瞻**：
    后面跟词字符 / `.` / `-` 的**不是**这个目录（`复盘/卡.md`、`复盘/卡-095.md` 不许中招）。
    """
    hits = 0
    for old_base, new_base in prefixes:
        old_bs = old_base.replace("/", "\\")
        new_bs = new_base.replace("/", "\\")
        # 源码里的转义写法（`旧\\`）在文本里是两个字符，得单独认
        old_esc = old_base.replace("/", "\\\\")
        new_esc = new_base.replace("/", "\\\\")
        # 长的先换：`旧\\\\`（转义写法）先于 `旧\\`
        for old, new in (
            (old_base + "/", new_base + "/"),
            (old_esc + "\\\\", new_esc + "\\\\"),
            (old_bs + "\\", new_bs + "\\"),
        ):
            hits += text.count(old)
            text = text.replace(old, new)
        for old, new in (
            (old_base, new_base),
            (old_esc, new_esc),
            (old_bs, new_bs),
        ):
            pattern = re.compile(re.escape(old) + r"(?![\w.\-])")
            text, count = pattern.subn(lambda _m, value=new: value, text)
            hits += count
    for old, new in exact:
        hits += text.count(old)
        text = text.replace(old, new)
    return text, hits


def _iter_text_files(root: Path, cfg: dict) -> list[Path]:
    suffixes = {s.lower() for s in cfg.get("suffixes", DEFAULT_SUFFIXES)}
    skip = cfg.get("skip", [])
    out: list[Path] = []
    for entry in cfg.get("roots", []):
        base = root / entry
        if base.is_file():
            out.append(base)
            continue
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            if _in_skip_dir(path, root):
                continue
            if _skipped(_posix(path, root), skip):
                continue
            out.append(path)
    return out


def build_plan(root: Path, mapping: dict) -> Plan:
    moves, pending, problems = expand_moves(root, mapping)
    exact, prefixes = substitution_pairs(moves)
    moved = {m.old: m for m in moves}
    cfg = mapping.get("rewrite", {})

    rewrites: list[Rewrite] = []
    seen: set[str] = set()
    for path in _iter_text_files(root, cfg):
        rel = _posix(path, root)
        if rel in seen:
            continue
        seen.add(rel)
        try:
            text = _read_text(path)
        except UnicodeDecodeError:  # 不是 utf-8 的当二进制，跳过
            continue
        new_text, count = substitute(text, exact, prefixes)
        if not count:
            continue
        target = moved[rel].new if rel in moved else rel
        rewrites.append(
            Rewrite(
                rel_before=rel,
                rel_after=target,
                count=count,
                before_sha=_sha(text.encode("utf-8")),
                after_sha=_sha(new_text.encode("utf-8")),
                before_text=text,
                text_after=new_text,
            )
        )

    skipped = sorted(rel for rel in set(cfg.get("skip", [])) if (root / rel).is_file())
    candidates = [
        c["path"]
        for c in mapping.get("candidates", [])
        if c.get("verdict", "pending") != "approved"
    ]
    probes = [p["path"] for p in mapping.get("code_probes", []) if p.get("path")]
    return Plan(
        moves=moves,
        pending=pending,
        rewrites=rewrites,
        skipped=skipped,
        candidates=candidates,
        probes=probes,
        problems=problems,
    )


# ---------------------------------------------------------------- 自检


def scan_leftovers(root: Path, mapping: dict) -> tuple[dict[str, int], dict[str, int]]:
    """全仓扫旧前缀：`(残留, 需人工)`，值是命中次数。

    残留 = 该改而没改（表里的改写面内、且不在跳过清单）；需人工 = 跳过清单里点名保留的
    （拓扑数据 / 语义要人看）。`gates/`、`.wt/` 这种产物目录不扫。
    """
    exact: list[tuple[str, str]] = []
    prefixes: list[tuple[str, str]] = []
    for rule in mapping.get("moves", []):
        if "glob" in rule:
            pattern = rule["glob"]
            base = pattern.rsplit("/", 1)[0] if "/" in pattern else ""
            prefixes.append((base, rule.get("to_dir", "").rstrip("/")))
        elif "from" in rule:
            old = rule["from"].rstrip("/")
            exact.append((old, rule["to"].rstrip("/")))
    needles: list[str] = []
    for old in [old for old, _ in prefixes] + [old for old, _ in exact]:
        for form in (old, old.replace("/", "\\"), old.replace("/", "\\\\")):
            if form not in needles:
                needles.append(form)
    cfg = mapping.get("rewrite", {})
    suffixes = {s.lower() for s in cfg.get("suffixes", DEFAULT_SUFFIXES)}
    skip = list(cfg.get("skip", [])) + [MAP_REL]
    residual: dict[str, int] = {}
    manual: dict[str, int] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        rel = _posix(path, root)
        if _in_skip_dir(path, root):
            continue
        try:
            text = _read_text(path)
        except UnicodeDecodeError:
            continue
        hits = 0
        for needle in needles:
            hits += len(re.findall(re.escape(needle) + r"(?![\w.\-])", text))
        if not hits:
            continue
        if _skipped(rel, skip):
            manual[rel] = hits
        else:
            residual[rel] = hits
    return residual, manual


def check_probes(root: Path, mapping: dict) -> list[tuple[str, str]]:
    """迁移后仍命中的代码点：`[(文件, 理由)]` —— 这些是**人手改**，不是脚本改。"""
    out: list[tuple[str, str]] = []
    for probe in mapping.get("code_probes", []):
        path = root / probe["path"]
        if not path.is_file():
            continue
        if probe.get("pattern", "") in _read_text(path):
            out.append((probe["path"], probe.get("why", "")))
    return out


# ---------------------------------------------------------------- 三个动作


def _summary(plan: Plan, mapping: dict) -> dict:
    by_phase: dict[str, int] = {}
    for move in plan.moves:
        by_phase[move.phase] = by_phase.get(move.phase, 0) + 1
    return {
        "moves": len(plan.moves),
        "by_phase": by_phase,
        "pending": len(plan.pending),
        "rewrite_files": len(plan.rewrites),
        "rewrite_hits": sum(item.count for item in plan.rewrites),
        "skipped": plan.skipped,
        "candidates": plan.candidates,
        "probes": plan.probes,
        "problems": plan.problems,
    }


def _print_skipped(skipped: list[str], label: str) -> None:
    if skipped:
        print(f"  {label} {len(skipped)} 个：" + "、".join(skipped))


def cmd_dry_run(root: Path, mapping: dict) -> int:
    plan = build_plan(root, mapping)
    summary = _summary(plan, mapping)
    if plan.problems:
        for problem in plan.problems:
            print(f"  ✘ {problem}")
        return 2
    print(f"[migrate·dry-run] root={root}")
    moves = summary["moves"]
    phases = "、".join(f"{k} {v} 个" for k, v in summary["by_phase"].items()) or "无"
    print(f"  待迁移 {moves} 个文件（{phases}）")
    for rule in mapping.get("moves", []):
        if "to_dir" in rule:
            print(f"    → {rule['to_dir']}/")
    print(f"  改写 {summary['rewrite_files']} 个文件 / {summary['rewrite_hits']} 处引用")
    print(f"  已迁移（幂等）{summary['pending']}")
    _print_skipped(plan.skipped, "跳过（需人工）")
    _print_skipped(plan.candidates, "三期候选（未批准，不动）")
    if summary["probes"]:
        print(f"  code_probes {len(summary['probes'])} 条（迁移后必须人手改）")
    return 0


def cmd_check(root: Path, mapping: dict) -> int:
    plan = build_plan(root, mapping)
    residual, manual = scan_leftovers(root, mapping)
    probes = check_probes(root, mapping)
    print(f"[migrate·check] root={root}")
    print(f"  待迁移 {len(plan.moves)} · 已迁移 {len(plan.pending)}")
    if residual:
        print(f"  残留（可改写）{len(residual)} 个文件：")
        for rel, hits in residual.items():
            print(f"    - {rel}（{hits} 处）")
    else:
        print("  残留（可改写）0")
    _print_skipped(manual, "需人工（跳过清单）")
    if probes:
        print("  code_probes 仍未处理：")
        for rel, why in probes:
            print(f"    - {rel}：{why}")
    _print_skipped(plan.candidates, "三期候选（未批准）")
    # 还没搬 ⇒ 满仓旧前缀是正常的；搬完了还有残留 ⇒ 才是错
    return 3 if residual and not plan.moves else 0


def cmd_apply(root: Path, mapping: dict, journal_path: Path) -> int:
    plan = build_plan(root, mapping)
    if plan.problems:
        for problem in plan.problems:
            print(f"  ✘ {problem}")
        return 2
    if not plan.moves:
        print(f"[migrate·apply] 没有要搬的文件（已迁移 {len(plan.pending)} 条）")
        if not plan.pending:
            print("  ✘ 源头和目标都是空的 —— 表写错了？")
            return 2
        residual, manual = scan_leftovers(root, mapping)
        _print_skipped(manual, "需人工（跳过清单）")
        return 3 if residual else 0

    journal = {
        "version": 1,
        "status": "applying",
        "root": str(root),
        "map": MAP_REL,
        "moves": [],
        "rewrites": [],
        "pending": [{"old": o, "new": n} for o, n in plan.pending],
    }
    for move in plan.moves:
        journal["moves"].append(move.as_json(_sha((root / move.old).read_bytes())))
    for item in plan.rewrites:
        journal["rewrites"].append(
            {
                "path": item.rel_after,
                "read_from": item.rel_before,
                "before_sha256": item.before_sha,
                "after_sha256": item.after_sha,
                "count": item.count,
                "before_text": item.before_text,
            }
        )
    # 判据 4：先记账，再动手
    _write_json(journal_path, journal)

    for item in plan.rewrites:
        if item.rel_before == item.rel_after:
            _write_text(root / item.rel_after, item.text_after)
    for move in plan.moves:
        target = root / move.new
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(root / move.old, target)
        _prune_empty((root / move.old).parent, root)
    for item in plan.rewrites:
        if item.rel_before != item.rel_after:
            _write_text(root / item.rel_after, item.text_after)

    residual, manual = scan_leftovers(root, mapping)
    journal["status"] = "applied"
    journal["residual"] = residual
    journal["needs_review"] = manual
    _write_json(journal_path, journal)

    hits = sum(item.count for item in plan.rewrites)
    print(f"[migrate·apply] 搬走 {len(plan.moves)} 个文件")
    print(f"  改写 {len(plan.rewrites)} 个 / {hits} 处引用")
    print(f"  journal → {journal_path}")
    _print_skipped(manual, "需人工（跳过清单）")
    if residual:
        print(f"  ✘ 残留 {len(residual)} 个文件（迁移没做完）：")
        for rel, count in residual.items():
            print(f"    - {rel}（{count} 处）")
        return 3
    print("  ✔ 自检：改写面内无残留")
    return 0


def _moves_from_journal(entries: list[dict]) -> list[Move]:
    out: list[Move] = []
    for entry in entries:
        out.append(
            Move(
                old=entry["old"],
                new=entry["new"],
                phase=entry.get("phase", ""),
                kind=entry.get("kind", "file"),
                prefix_old=entry.get("prefix_old", ""),
                prefix_new=entry.get("prefix_new", ""),
            )
        )
    return out


def cmd_revert(root: Path, mapping: dict, journal_path: Path) -> int:
    if not journal_path.is_file():
        print(f"  ✘ 找不到 journal：{journal_path}（没有账就不敢猜着还原）")
        return 2
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    if journal.get("status") == "reverted":
        print("[migrate·revert] 已经是还原状态，无需再跑")
        return 0

    moves = _moves_from_journal(journal.get("moves", []))
    rewrites = journal.get("rewrites", [])
    touched = {item["path"] for item in rewrites}

    # 先全部验一遍，验不过就一个字节都不动
    drift: list[str] = []
    for item in rewrites:
        path = root / item["path"]
        if not path.is_file():
            drift.append(f"{item['path']}（不见了）")
        elif _sha(path.read_bytes()) != item["after_sha256"]:
            drift.append(f"{item['path']}（内容被改过）")
    for entry in journal.get("moves", []):
        if entry["new"] in touched:
            continue  # 上面按"迁后 sha"验过了
        path = root / entry["new"]
        if not path.is_file():
            drift.append(f"{entry['new']}（不见了）")
        elif _sha(path.read_bytes()) != entry["sha256"]:
            drift.append(f"{entry['new']}（内容被改过）")
    if drift:
        print("  ✘ 拒跑：还原会盖掉别人的改动，先人工看一眼")
        for rel in drift:
            print(f"    - {rel}")
        return 2

    for item in rewrites:
        _write_text(root / item["path"], item["before_text"])
    for move in moves:
        target = root / move.old
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(root / move.new, target)
        _prune_empty((root / move.new).parent, root)

    journal["status"] = "reverted"
    _write_json(journal_path, journal)
    print(f"[migrate·revert] 还原 {len(moves)} 个文件、{len(rewrites)} 个文件的正文")
    return 0


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="migrate_docs.py",
        description="文档归位迁移器（复盘/卡 → docs/cards，只改路径不改内容）",
    )
    parser.add_argument("--root", default=str(ROOT), help="仓库根（默认本文件上一级）")
    parser.add_argument("--map", default=None, help=f"迁移表（默认 <root>/{MAP_REL}）")
    parser.add_argument("--journal", default=None, help=f"账本（默认 <root>/{JOURNAL_REL}）")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", help="只算不写（默认）")
    group.add_argument("--apply", action="store_true", help="搬 + 改写 + 自检")
    group.add_argument("--check", action="store_true", help="只看残留 / 待人工 / 代码点")
    group.add_argument("--revert", action="store_true", help="依 journal 还原")
    parser.add_argument("--json", action="store_true", help="机器可读（只对 dry-run）")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    map_path = Path(args.map) if args.map else root / MAP_REL
    journal_path = Path(args.journal) if args.journal else root / JOURNAL_REL
    try:
        mapping = load_map(map_path)
    except (OSError, ValueError) as exc:
        print(f"  ✘ 迁移表读不了：{exc}")
        return 2

    if args.apply:
        return cmd_apply(root, mapping, journal_path)
    if args.revert:
        return cmd_revert(root, mapping, journal_path)
    if args.check:
        return cmd_check(root, mapping)
    if args.json:
        plan = build_plan(root, mapping)
        payload = {"mode": "dry-run", **_summary(plan, mapping)}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2 if plan.problems else 0
    return cmd_dry_run(root, mapping)


if __name__ == "__main__":
    sys.exit(main())
