#!/usr/bin/env python
r"""留痕与配额：把「读数 + 判据 + 归档」接上常规（卡 182 · `T-G282`）。

为什么有它（卡 182 §1）
----------------------
`tools/wt_prune.py`（卡 081）**早就有**七条判据 + 默认 dry-run —— 但没有任何一条
常规说「谁、什么时候、按什么读数跑它」。`gates/diag/wb-*.jsonl` 也在积压，没人定
它们该留多久。本模块**不新写清理器**（那条能力已经有了），只做三件事：

  1. **现算读数**：工作树数 / 派活日志份数 / 判决份数 / 无判决份数 —— 一个函数掏出来，
     给派活前置检查和收工后摘要各印一行（★ 只看不删）。
  2. **配额告警**：树数 / 日志数超阈值 → 在摘要里印 WARNING，指名谁在哪个环节看。
  3. **归档**（ISO 15489-1 的「处置」）：把过期的无判决日志移到 `gates/diag/archive/`
     并留索引；**幂等**（跑两次结果一样）；**默认 dry-run**，`--apply` 才真移。

★ 本卡**不许真删任何工作树**（卡 182 硬要求 1）：真删由主控看完干跑读数后调
`wt_prune.py --apply`；本模块只管到「读数 + 判据 + 归档日志」。

判据口径（机器可复算）
----------------------
- 一份派活日志 = `gates/diag/wb-*.jsonl`（含 `.claim`/`.old` 等变体名）。
- 一份判决 = `gates/diag/wb-*.verdict.txt`。
- 「这份日志有判决」 ⟺ 存在**同名** `wb-<X>.verdict.txt`（`wb-125.claim.jsonl` →
  `wb-125.claim.verdict.txt`）。★ 这是逐文件口径，不按卡号聚合 —— 因为每次跑活
  尝试（含 claim/重跑）都该各自留一份判决，按卡号聚合会把「claim 没判决但正跑有判决」
  误判成「有判决」。
- 「无判决日志」= 有 jsonl 但无同名 verdict.txt。

用法
----
    python -X utf8 tools/wb_retention.py summary                 # 读数 + 配额告警（默认）
    python -X utf8 tools/wb_retention.py summary --json          # 给主控读的机器可读输出
    python -X utf8 tools/wb_retention.py archive                 # dry-run：报要归档哪些，不动
    python -X utf8 tools/wb_retention.py archive --apply         # 才真移 + 留索引（幂等）
    python -X utf8 tools/wb_retention.py archive --min-age 14    # 只归档 ≥14 天的无判决日志
    python -X utf8 tools/wb_retention.py --root <仓库根>         # 指定仓库根

退出码：0 = 正常；1 = 归档时至少一份移失败（已保留原位）；2 = 环境不对。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pool.no_window import NO_WINDOW  # ★ 卡 148：子进程一律不弹窗（flag 的唯一真源）

# ================================================================ 配额阈值（卡 182 §配额）
#
# ★ 阈值是「该报警的线」，不是「该删的线」。超了只印 WARNING，不动任何东西。
# 工作树：T-G180 记 89 棵时一切正常 → 100 是「该收尾了」的线，150 是「该主控介入」的线。
# 日志：现 118 份 → 150 是「该归档了」的线。
DEFAULT_TREE_WARN = 100
DEFAULT_TREE_CRIT = 150
DEFAULT_LOG_WARN = 150

_DAY = 86400  # 秒


def _git(args: list[str], cwd: Path) -> tuple[int, str, str]:
    try:
        r = subprocess.run(
            ["git", "-c", "core.quotepath=false", *args],
            cwd=str(cwd), capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False, **NO_WINDOW,
        )
    except OSError:
        return 1, "", "git 不可用"
    return r.returncode, (r.stdout or ""), (r.stderr or "")


def main_root(explicit: str | None = None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p.resolve() if p.exists() else None
    rc, out, _ = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], Path.cwd())
    if rc == 0 and out.strip():
        return Path(out.strip()).resolve().parent
    rc, out, _ = _git(["rev-parse", "--show-toplevel"], Path.cwd())
    if rc == 0 and out.strip():
        return Path(out.strip()).resolve()
    return None


# ================================================================ 复用 wt_prune（不重造轮子）

_WT_PRUNE: Any = None


def _load_wt_prune() -> Any:
    """按路径加载兄弟 `tools/wt_prune.py`（`tools/` 不是包 → 同 wt_prune._load_wb_plan 手法）。"""
    global _WT_PRUNE
    if _WT_PRUNE is not None:
        return _WT_PRUNE
    src = Path(__file__).resolve().parent / "wt_prune.py"
    spec = importlib.util.spec_from_file_location("wt_prune_under_retention", src)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    _WT_PRUNE = mod
    return mod


# ================================================================ 读数

_CARD_RE = re.compile(r"wb-(\d+)")


def card_of(filename: str) -> str | None:
    """从 `wb-125.claim.jsonl` / `wb-125.verdict.txt` 里提卡号 `125`。提不出 → None。"""
    m = _CARD_RE.search(filename)
    return m.group(1) if m else None


@dataclass
class Counts:
    worktrees: int = 0
    jsonl_files: list[Path] = field(default_factory=list)
    verdict_files: list[Path] = field(default_factory=list)
    no_verdict_jsonl: list[Path] = field(default_factory=list)  # 同名 verdict 不存在
    no_verdict_cards: list[str] = field(default_factory=list)   # 卡号聚合：该卡无任何 verdict

    @property
    def n_jsonl(self) -> int:
        return len(self.jsonl_files)

    @property
    def n_verdict(self) -> int:
        return len(self.verdict_files)

    @property
    def n_no_verdict(self) -> int:
        return len(self.no_verdict_jsonl)


def has_verdict(jsonl_path: Path) -> bool:
    """★ 机器判据：这份日志有判决 ⟺ 同名 `.verdict.txt` 存在。

    `wb-125.claim.jsonl` → 找 `wb-125.claim.verdict.txt`（逐文件，不按卡号聚合）。
    """
    if jsonl_path.name.endswith(".jsonl"):
        stem = jsonl_path.name[: -len(".jsonl")]
    else:
        stem = jsonl_path.stem
    return (jsonl_path.parent / f"{stem}.verdict.txt").is_file()


def read_counts(root: Path) -> Counts:
    """现算读数（卡 182 §现算读数）。"""
    c = Counts()
    rc, out, _ = _git(["worktree", "list"], root)
    if rc == 0:
        c.worktrees = sum(1 for ln in out.splitlines() if ln.strip())
    diag = root / "gates" / "diag"
    if diag.is_dir():
        c.jsonl_files = sorted(diag.glob("wb-*.jsonl"))
        c.verdict_files = sorted(diag.glob("wb-*.verdict.txt"))
    c.no_verdict_jsonl = [p for p in c.jsonl_files if not has_verdict(p)]
    v_cards = {card_of(p.name) for p in c.verdict_files if card_of(p.name)}
    j_cards = {card_of(p.name) for p in c.jsonl_files if card_of(p.name)}
    c.no_verdict_cards = sorted(j_cards - v_cards, key=lambda s: int(s) if s.isdigit() else 0)
    return c


# ================================================================ 配额告警

@dataclass
class QuotaWarning:
    level: str  # "WARN" / "CRIT"
    what: str
    value: int
    threshold: int
    where: str  # 在哪个环节看


def quota_check(c: Counts, *,
                tree_warn: int = DEFAULT_TREE_WARN,
                tree_crit: int = DEFAULT_TREE_CRIT,
                log_warn: int = DEFAULT_LOG_WARN) -> list[QuotaWarning]:
    out: list[QuotaWarning] = []
    if c.worktrees >= tree_crit:
        out.append(QuotaWarning("CRIT", "工作树数", c.worktrees, tree_crit,
                                "派活前置检查（wb_dispatch preflight）/ 收工后 summary"))
    elif c.worktrees >= tree_warn:
        out.append(QuotaWarning("WARN", "工作树数", c.worktrees, tree_warn,
                                "收工后 summary（主控看一眼该收尾了）"))
    if c.n_jsonl >= log_warn:
        out.append(QuotaWarning("WARN", "派活日志份数", c.n_jsonl, log_warn,
                                "收工后 summary（该归档无判决的旧日志）"))
    return out


# ================================================================ 该拆哪些树（复用 wt_prune）
# ★ 只看不删：真删由主控另开 `wt_prune.py --apply`。

def pruneable_preview(root: Path, *, min_size_mb: float = 0.0) -> dict[str, Any]:
    """调 `wt_prune.collect` 得「可删 / 保留 / 跳过」读数 —— **只看不删**。

    返回 `{total, deletable, keep, skipped, reclaim_mb, top_deletable: [(name, mb), ...]}`。
    ★ 不调 `do_apply`；真删由主控另开 `wt_prune.py --apply`。
    """
    wt = _load_wt_prune()
    current = wt.current_worktree()
    verdicts = wt.collect(root, current, min_size_mb)
    deletable = [v for v in verdicts if v.deletable]
    return {
        "total": len(verdicts),
        "deletable": len(deletable),
        "keep": sum(1 for v in verdicts if not v.deletable and not v.skipped),
        "skipped": sum(1 for v in verdicts if v.skipped),
        "reclaim_mb": round(sum(v.size_bytes for v in deletable) / (1024 * 1024), 1),
        "top_deletable": [(v.name, round(v.size_bytes / (1024 * 1024), 1)) for v in deletable[:10]],
    }


# ================================================================ 摘要（给人读）

def summary_lines(root: Path, *, prune: bool = True) -> list[str]:
    """给人读的摘要：读数 + 配额告警 + 该拆哪些树。派活前 / 收工后各印一次。"""
    c = read_counts(root)
    lines: list[str] = []
    lines.append(f"=== 留痕与配额读数 · 仓库根 {root} ===")
    lines.append(f"工作树数：{c.worktrees}")
    lines.append(f"派活日志 wb-*.jsonl：{c.n_jsonl} 份")
    lines.append(f"判决 wb-*.verdict.txt：{c.n_verdict} 份")
    lines.append(f"无判决日志（同名 verdict 不存在）：{c.n_no_verdict} 份")
    if c.no_verdict_cards:
        lines.append(f"无判决卡号（该卡无任何 verdict）：{', '.join(c.no_verdict_cards)}")
    warns = quota_check(c)
    if warns:
        lines.append("")
        lines.append("── 配额告警 ──")
        for w in warns:
            lines.append(f"[{w.level}] {w.what} = {w.value} ≥ 阈值 {w.threshold}（看：{w.where}）")
    else:
        lines.append("配额：未超阈值。")
    if prune:
        try:
            pv = pruneable_preview(root)
            lines.append("")
            lines.append("── 该拆哪些树（wt_prune dry-run，只看不删）──")
            lines.append(f"可删 {pv['deletable']} / 保留 {pv['keep']} / 跳过 {pv['skipped']} / "
                         f"可释放 {pv['reclaim_mb']} MB")
            if pv["top_deletable"]:
                lines.append("可删前 10（按大小）：" +
                             "、".join(f"{n}({mb}MB)" for n, mb in pv["top_deletable"]))
            lines.append("真删：python -X utf8 tools/wt_prune.py --apply（主控看完表再决定）")
        except Exception as exc:  # noqa: BLE001 —— 读树失败不该把摘要整张打挂
            lines.append(f"（wt_prune 读树失败，已跳过：{exc}）")
    return lines


# ================================================================ 归档（ISO 15489-1「处置」）
# 移动 + 留索引，幂等。默认 dry-run，--apply 才真移。

ARCHIVE_DIR = "archive"
ARCHIVE_INDEX = "index.jsonl"


def _archive_root(root: Path) -> Path:
    return root / "gates" / "diag" / ARCHIVE_DIR


def _index_path(root: Path) -> Path:
    return _archive_root(root) / ARCHIVE_INDEX


def _index_keys(root: Path) -> set[str]:
    """读归档索引，返回已归档的文件名集合（幂等判据）。索引坏行跳过。"""
    p = _index_path(root)
    if not p.is_file():
        return set()
    keys: set[str] = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            name = obj.get("name")
            if isinstance(name, str):
                keys.add(name)
        except Exception:
            continue
    return keys


@dataclass
class ArchiveAction:
    name: str
    src: Path
    dst: Path
    age_days: float
    done: bool = False
    skipped_reason: str = ""  # "已归档" / "有判决" / "太新"


def archive_plan(root: Path, *, min_age_days: float = 0.0,
                 now: float | None = None) -> list[ArchiveAction]:
    """列归档计划：**无判决且 ≥ min_age 天**的日志移到 `archive/`。**不落盘**。

    ★ 归档判据（机器可判）：① 无同名 verdict.txt；② 文件年龄 ≥ min_age_days。
    ★ 幂等：已在索引里 / `archive/` 里已有同名 → 标 `skipped_reason="已归档"`。
    ★ 有判决的不归档（反例钉子守这条）→ 标 `skipped_reason="有判决"`。
    """
    import time
    c = read_counts(root)
    keys = _index_keys(root)
    adir = _archive_root(root)
    now_t = now if now is not None else time.time()
    plan: list[ArchiveAction] = []
    for p in c.no_verdict_jsonl:
        try:
            age = (now_t - p.stat().st_mtime) / _DAY
        except OSError:
            age = 0.0
        act = ArchiveAction(name=p.name, src=p, dst=adir / p.name, age_days=round(age, 1))
        if p.name in keys or (adir / p.name).exists():
            act.skipped_reason = "已归档"
        elif min_age_days > 0 and age < min_age_days:
            act.skipped_reason = "太新"
        plan.append(act)
    return plan


def archive_apply(root: Path, *, min_age_days: float = 0.0,
                  now: float | None = None) -> tuple[int, int, int]:
    """真归档：移文件 + 追加索引。返回 `(归档数, 跳过数, 失败数)`。**幂等**。

    ★ 留档在先：先移成功才写索引；移失败 → 原位不动、计失败、不写索引。
    ★ 索引逐行追加（同 wt_prune.merge_usage 口径），既有行一个字节不改。
    """
    plan = archive_plan(root, min_age_days=min_age_days, now=now)
    adir = _archive_root(root)
    adir.mkdir(parents=True, exist_ok=True)
    done = skipped = failed = 0
    for act in plan:
        if act.skipped_reason:
            skipped += 1
            continue
        try:
            shutil.move(str(act.src), str(act.dst))
        except OSError as exc:
            print(f"[archive] 移失败 {act.name}：{exc}（原位保留）", file=sys.stderr)
            failed += 1
            continue
        with _index_path(root).open("a", encoding="utf-8", newline="") as fh:
            fh.write(json.dumps({"name": act.name, "age_days": act.age_days},
                                ensure_ascii=False) + "\n")
        act.done = True
        done += 1
        print(f"[archive] {act.name}（{act.age_days} 天）→ {act.dst}")
    return done, skipped, failed


# ================================================================ CLI


def _cmd_summary(ns: argparse.Namespace, root: Path) -> int:
    c = read_counts(root)
    if ns.json:
        payload = {
            "root": str(root),
            "worktrees": c.worktrees,
            "n_jsonl": c.n_jsonl,
            "n_verdict": c.n_verdict,
            "n_no_verdict": c.n_no_verdict,
            "no_verdict_cards": c.no_verdict_cards,
            "quota": [{"level": w.level, "what": w.what, "value": w.value,
                       "threshold": w.threshold, "where": w.where}
                      for w in quota_check(c)],
        }
        try:
            payload["prune_preview"] = pruneable_preview(root)
        except Exception:
            payload["prune_preview"] = None
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    for line in summary_lines(root):
        print(line)
    return 0


def _cmd_archive(ns: argparse.Namespace, root: Path) -> int:
    mode = "APPLY（真移）" if ns.apply else "DRY-RUN（只看不动）"
    print(f"=== 归档无判决日志 · {mode} · 仓库根 {root} ===")
    print(f"（判据：① 无同名 verdict.txt ② 年龄 ≥ {ns.min_age} 天；幂等；有判决的不动）")
    plan = archive_plan(root, min_age_days=ns.min_age)
    if not plan:
        print("没有待归档的无判决日志。")
        return 0
    for act in plan:
        tag = act.skipped_reason or "待归档"
        print(f"  {act.name}（{act.age_days} 天）→ {tag}")
    if not ns.apply:
        print(f"\n汇总：待归档 {sum(1 for a in plan if not a.skipped_reason)} / "
              f"跳过 {sum(1 for a in plan if a.skipped_reason)}（dry-run，未动）")
        return 0
    done, skipped, failed = archive_apply(root, min_age_days=ns.min_age)
    print(f"\n汇总：归档 {done} / 跳过 {skipped} / 失败 {failed}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="留痕与配额：读数 + 判据 + 归档（T-G282）")
    ap.add_argument("--root", default=None, help="仓库根（默认自动定位主仓）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("summary", help="读数 + 配额告警 + 该拆哪些树（默认只看不删）")
    sp.add_argument("--json", action="store_true", help="机器可读输出")
    ap_arch = sub.add_parser("archive", help="归档无判决的旧日志（移动 + 留索引，幂等）")
    ap_arch.add_argument("--apply", action="store_true", help="才真移；默认 dry-run")
    ap_arch.add_argument("--min-age", type=float, default=0.0, metavar="天",
                         help="只归档 ≥ 这么多天的无判决日志（默认 0 = 全部无判决）")
    ns = ap.parse_args(argv)

    root = main_root(ns.root)
    if root is None:
        print("[FAIL] 定位不到仓库根（不是 git 仓库？）", file=sys.stderr)
        return 2
    if ns.cmd == "summary":
        return _cmd_summary(ns, root)
    if ns.cmd == "archive":
        return _cmd_archive(ns, root)
    return 2


if __name__ == "__main__":
    sys.exit(main())
