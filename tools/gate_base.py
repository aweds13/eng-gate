"""派生物差异分类器（卡 E123 / T-AG632）—— **全仓唯一一份**分类实现。

问题（卡 E123 §1）：门禁在 R 上跑完，主树又前进几笔（只动台账 / 派生物），复核器
却用「last.json.rev 必须**等于**父提交」把两者判成两笔 ⇒ 红对了、理由错了。
这里把「差在哪」分成三档，供四处判据共用（tools/wb_review.py、tools/wb_verify.py、
tools/gate_pool.py、framework/src/framework/review.py）：

- MATCH：rev 解析后 == 父提交（行为与旧口径**完全一致**，含「字面量相同」快路径 ——
  合成 sha / 仓外树 / 浅克隆的既有夹具靠它继续可用）；
- LEDGER_ONLY：rev 是父提交的**真祖先**，且 rev..父提交 的差异**每一条**都落在台账族
  （台账族由 gates/defs/domains.py 的 REQUIRED_PROFILES 反推：只 allow {audit} 的
  前缀 —— **不许**在这里抄第二张表）；
- DRIFT：其余一切（源码差异 / 非祖先 / 任一方解析不出 / 差异取不到）—— 拿不准就红。

★ LEDGER_ONLY 不是「放行」：调用方必须把读数（reading）如实标出来 ——
  「结论未经复验」这几个字不许省。本模块只判定，不 print、不 sys.exit。
★ LEDGER_ONLY 还要求**见过**这件事发生过，两种见证：
  (1) 第一现场读数 gates/diag/base_drift/<task>.json（落地链 rebase 后落的，判据 6）；
  (2) 产物自带的时间见证：门禁封存时刻（sealed_at）不早于父提交的提交时刻
      ⇒ 父提交是在门禁跑的那段时间里落进来的。
  两种都没有 ⇒ 一律 DRIFT（fail closed：没有见证的「台账-only」与「查不到」不可分）。
★ git 取数由调用方注入（providers() 是默认实现；wb_review / wb_verify 用自己那份，
  好让测试的 monkeypatch 仍然生效）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 只在注解里用（本文件已开 `from __future__ import annotations`）
    from collections.abc import Callable

MATCH = "MATCH"
LEDGER_ONLY = "LEDGER_ONLY"
DRIFT = "DRIFT"

#: 落地链第一现场的读数目录（卡 E123 判据 6）：gates/diag/base_drift/<task>.json
RECORD_DIR = ("gates", "diag", "base_drift")

_NO_WINDOW = {"creationflags": 0x08000000} if sys.platform == "win32" else {}


def ledger_prefixes() -> tuple[str, ...]:
    """台账族前缀 —— 从 gates/defs/domains.py 的 REQUIRED_PROFILES **反推**。

    只留 allow {audit} 的前缀（本仓现状：docs/ 复盘/ skills/）。import 不到 domains
    ⇒ 回空元组 ⇒ 任何非空差异都判 DRIFT（**fail closed**：宁红不漏）。
    """
    try:
        from gates.defs import domains
    except ModuleNotFoundError:
        root = str(Path(__file__).resolve().parents[1])
        if root not in sys.path:
            sys.path.insert(0, root)
        try:
            from gates.defs import domains
        except ModuleNotFoundError:
            return ()
    out: list[str] = []
    for prefix, profiles in getattr(domains, "REQUIRED_PROFILES", ()):
        if {str(x) for x in profiles} == {"audit"}:
            out.append(str(prefix))
    return tuple(sorted(out))


def is_ledger_path(path: str, prefixes: tuple[str, ...] | None = None) -> bool:
    """这一条路径算不算台账 / 派生物（只认 {audit} 前缀）。空路径一律不算。"""
    text = str(path or "").replace("\\", "/").lstrip("./")
    if not text:
        return False
    for p in (ledger_prefixes() if prefixes is None else prefixes):
        if text == p.rstrip("/") or text.startswith(p):
            return True
    return False


def _same_commit(a: str, b: str) -> bool:
    a, b = str(a or ""), str(b or "")
    if not a or not b:
        return False
    return a == b or a.startswith(b) or b.startswith(a)


def find_record(root: Path | str, gates_rev: str, parent_short: str) -> dict | None:
    """找落地链落的第一现场读数（gates/diag/base_drift/*.json）。

    命中条件：gates_rev == 这一笔的 rev，且 rebase_after_parent == 这一笔的父提交。
    找不到 ⇒ None（调用方按「没有见证」处理）。
    """
    base = Path(root).joinpath(*RECORD_DIR)
    if not base.is_dir():
        return None
    for path in sorted(base.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        if _same_commit(str(data.get("gates_rev") or ""), gates_rev) and _same_commit(
            str(data.get("rebase_after_parent") or ""), parent_short
        ):
            data.setdefault("_path", str(path))
            return data
    return None


def _git(root: Path | str, *args: str) -> tuple[int, str]:
    done = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=str(root), capture_output=True, text=True,
        encoding="utf-8", errors="replace", **_NO_WINDOW,
    )
    return done.returncode, (done.stdout or "")


def providers(root: Path | str) -> dict:
    """默认取数：全部跑在 root 这棵树上（复核器传自己的 ROOT）。"""
    base = Path(root)

    def _resolve(short: str) -> str:
        rc, out = _git(base, "rev-parse", "--verify", str(short) + "^{commit}")
        return out.strip() if rc == 0 else ""

    def _ancestor(a: str, b: str) -> bool | None:
        rc, _out = _git(base, "merge-base", "--is-ancestor", a, b)
        if rc == 0:
            return True
        if rc == 1:
            return False
        return None

    def _diff(a: str, b: str) -> list[str] | None:
        rc, out = _git(base, "diff", "--name-only", a, b)
        if rc != 0:
            return None
        return [ln.strip() for ln in out.splitlines() if ln.strip()]

    def _ctime(rev: str) -> str:
        rc, out = _git(base, "show", "-s", "--format=%cI", str(rev))
        return out.strip() if rc == 0 else ""

    def _recorded(a: str, b: str) -> dict | None:
        return find_record(base, a, b)

    return {
        "resolve": _resolve,
        "ancestor": _ancestor,
        "diff": _diff,
        "commit_time": _ctime,
        "recorded": _recorded,
    }


def _naive(ts: str) -> datetime | None:
    text = str(ts or "").strip()
    if not text:
        return None
    try:
        got = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return got.replace(tzinfo=None)


def _rows_text(rows: list[str]) -> str:
    return "、".join(rows) if rows else "一个都没动"


def gate_base_drift(
    payload_rev: str,
    parent_short: str,
    *,
    resolve: Callable[[str], str] | None = None,
    ancestor: Callable[[str, str], bool | None] | None = None,
    diff: Callable[[str, str], list[str] | None] | None = None,
    commit_time: Callable[[str], str] | None = None,
    recorded: Callable[[str, str], dict | None] | None = None,
    sealed_at: str = "",
    is_ledger: Callable[[str], bool] | None = None,
) -> tuple[str, list[str], str]:
    """判「门禁基点」与「父提交」差在哪 ⇒ (分类, 差异文件, 读数)。

    两处判据（复核 ③ 与 Gates 真伪 ⓖ）**共用这一份**；另三处（wb_verify /
    gate_pool / framework）也调这里，免得同一条判据说两种话。
    """
    raw = str(payload_rev or "").strip()
    parent = str(parent_short or "").strip()
    ledger = is_ledger if is_ledger is not None else is_ledger_path

    if raw and raw == parent:  # 字面量相同：合成 sha / 仓外树都靠它
        return MATCH, [], ""
    if not raw or not parent:
        return DRIFT, [], (
            f"门禁基点 {raw or '(空)'} 与父提交 {parent or '(空)'}："
            "提交对不上，也解析不出差异 ⇒ 按 DRIFT（拿不准就红）"
        )
    if resolve is None or ancestor is None or diff is None:
        return DRIFT, [], (
            "这一档没有可用的 git 取数（分类器只认解析后的提交）⇒ 按 DRIFT（拿不准就红）"
        )

    a = str(resolve(raw) or "").strip()
    b = str(resolve(parent) or "").strip()
    if not a or not b:
        return DRIFT, [], (
            f"提交解析不出（last.json.rev={raw!r} 解析={a[:8] or '解析不出'}，"
            f"父提交 {parent!r} 解析={b[:8] or '解析不出'}；合成 sha / 浅克隆 / 仓外树）"
            " ⇒ 按 DRIFT，不许当「没改」"
        )
    if _same_commit(a, b):
        return MATCH, [], ""

    seen = ancestor(a, b)
    if seen is not True:
        return DRIFT, [], (
            f"last.json.rev={raw}（解析={a[:8]}）不是父提交 {parent}（解析={b[:8]}）"
            "的真祖先 ⇒ 按 DRIFT（一次门禁跑完提交两笔？第二笔没验过）"
        )

    rows = diff(a, b)
    if rows is None:
        return DRIFT, [], (
            f"门禁基点 {raw}（解析={a[:8]}）与父提交 {parent}（解析={b[:8]}）"
            "之间的差异取不到 ⇒ 按 DRIFT（不许把「查不到」当「没改」）"
        )

    off = [p for p in rows if not ledger(p)]
    if off:
        return DRIFT, rows, (
            f"门禁基点 {raw}（解析={a[:8]}）与父提交 {parent}（解析={b[:8]}）之间改了源码："
            f"{'；'.join(off)} ⇒ 必须重跑门禁"
        )

    head = (
        f"last.json.rev={raw} 是父提交 {parent} 的真祖先；"
        f"{raw}..{parent} 只动了 {len(rows)} 个台账/派生物文件（{_rows_text(rows)}）；"
        "pytest / docs 属「永远跑」⇒ 结论未经复验"
    )

    rec = recorded(a, b) if recorded is not None else None
    if rec:
        where = str(rec.get("_path") or "").strip()
        tail = f"（第一现场读数：{where}）" if where else "（第一现场读数：gates/diag/base_drift/）"
        return LEDGER_ONLY, rows, head + tail

    sealed = _naive(sealed_at)
    if sealed is not None and commit_time is not None:
        born = _naive(str(commit_time(b) or ""))
        if born is not None and born <= sealed:
            return LEDGER_ONLY, rows, (
                head
                + f"（时间见证：父提交提交于 {born.isoformat()}，"
                f"门禁封存于 {sealed.isoformat()}）"
            )

    return DRIFT, rows, (
        head + "；但既没有第一现场读数（gates/diag/base_drift/），也没有时间见证"
        "（产物里的 sealed_at 不早于父提交的提交时刻）⇒ 按 DRIFT（拿不准就红）"
    )


def category_is_red(category: str) -> bool:
    """只有 MATCH / LEDGER_ONLY 不算红 —— 其余（含未知值）一律算红。"""
    return str(category) not in (MATCH, LEDGER_ONLY)


BASIS_DRIFT = "BASIS_DRIFT"
TRUE_MISMATCH = "TRUE_MISMATCH"

_BASIS_DEFAULT_ROOT = Path(__file__).resolve().parents[1]


def required_profiles_of(paths: list[str]) -> frozenset[str]:
    """这条路径清单要跑哪些档 —— 现读 gates/defs/domains.py；读不到就 **fail closed 全档**。

    ★ 卡 E137 判据 1 的硬边界要的是「档表真源」而不是抄一份常量：档表一改，这里必须跟着变。
    """
    try:
        try:
            from gates.defs import domains
        except ModuleNotFoundError:
            root = str(_BASIS_DEFAULT_ROOT)
            if root not in sys.path:
                sys.path.insert(0, root)
            from gates.defs import domains
        got = domains.required_profiles(list(paths))
    except Exception:  # noqa: BLE001 —— 读不到档表就拿不准，全档最严
        return frozenset({"lang", "audit", "product"})
    return frozenset(str(x) for x in got)


def _basis_norm(path: object) -> str:
    return str(path or "").replace("\\", "/").lstrip("./")


def basis_providers(root: Path | str | None = None) -> dict[str, object]:
    """gate_basis_verdict 的默认取数器（git 只读 + 现算封存树 + 现读档表）。"""
    base = Path(root) if root is not None else _BASIS_DEFAULT_ROOT
    out: dict[str, object] = dict(providers(base))

    def _kind(name: str) -> str:
        if not name:
            return ""
        rc, text = _git(base, "cat-file", "-t", str(name))
        return text.strip() if rc == 0 else ""

    def _count(old: str, new: str) -> int | None:
        if not old or not new:
            return None
        rc, text = _git(base, "rev-list", "--count", f"{old}..{new}")
        if rc != 0:
            return None
        try:
            return int(text.strip())
        except ValueError:
            return None

    def _trees(old: str, new: str) -> list[str] | None:
        if not old or not new:
            return None
        rc, text = _git(base, "diff", "--name-only", str(old), str(new))
        if rc != 0:
            return None
        return [ln for ln in text.splitlines() if ln.strip()]

    def _without_gates(rev: str) -> str:
        try:
            scripts = str(base / "scripts")
            if scripts not in sys.path:
                sys.path.insert(0, scripts)
            import run_gates as _rg  # noqa: PLC0415 —— 现读，免得 tools/ 反依赖 scripts/

            return _rg.tree_without_gates(base, str(rev)) or ""
        except Exception:  # noqa: BLE001
            return ""

    out["object_kind"] = _kind
    out["count_between"] = _count
    out["diff_trees"] = _trees
    out["tree_without_gates"] = _without_gates
    out["required_profiles"] = required_profiles_of
    return out


def gate_basis_verdict(
    payload_rev: str,
    parent_short: str,
    recorded_tree: str,
    commit_sha: str,
    files: list[str],
    *,
    root: Path | str | None = None,
    **providers_in: object,
) -> tuple[str, list[str], str]:
    """判「封存树 vs 本笔提交树」的差异该算谁的 ⇒ (档, 差异路径, 读数)。

    ★ 卡 E137：对不上不等于「伪造」。两档 ——
      * ``BASIS_DRIFT``：门禁基点真落后了（真祖先），差异全由中间提交带入、且只落台账/文档档
        ⇒ 结论**未经复验**（如实留痕，不判红）；
      * ``TRUE_MISMATCH``：其余一切（不是祖先 / 差异里有本笔自己改的 / 无法解释 / 落被测代码档 /
        封存树不在对象库 / 拿不到差异）⇒ 照红、点名路径。

    四个必要条件缺一即 ``TRUE_MISMATCH``（拿不准就红）。本函数**只判定**：不 print、不 sys.exit。
    """
    taken: dict[str, object] = basis_providers(root)
    taken.update(providers_in)
    resolve = taken.get("resolve")
    ancestor = taken.get("ancestor")
    diff_trees = taken.get("diff_trees")
    diff_range = taken.get("diff_range") or taken.get("diff")
    count_between = taken.get("count_between")
    object_kind = taken.get("object_kind")
    tree_without_gates = taken.get("tree_without_gates")
    required_profiles = taken.get("required_profiles") or required_profiles_of

    raw = str(payload_rev or "")
    parent = str(parent_short or "")
    files_n = [_basis_norm(f) for f in (files or [])]

    a = str(resolve(raw) or "") if callable(resolve) else ""
    b = str(resolve(parent) or "") if callable(resolve) else ""
    if not a or not b:
        return TRUE_MISMATCH, [], (
            f"门禁 rev={raw!r}（解析={a[:8] or '失败'}）与本笔父提交 {parent!r}"
            f"（解析={b[:8] or '失败'}）不是两个都解析得出的提交 —— 没法证明是同一条基点"
            " ⇒ 拿不准不放过"
        )

    same = _same_commit(a, b)
    seen = True if same else (ancestor(a, b) if callable(ancestor) else None)
    if seen is not True:
        return TRUE_MISMATCH, [], (
            f"门禁跑在 {raw}（解析={a[:8]}），而本笔父提交是 {parent}（解析={b[:8]}）"
            " —— 前者**不是**后者的祖先：门禁结论没有复验过，不能当本笔证据"
        )

    middle = 0 if same else (count_between(a, b) if callable(count_between) else None)
    middle_n = "?" if middle is None else str(middle)

    kind = str(object_kind(recorded_tree) or "") if callable(object_kind) else ""
    if not str(recorded_tree or "") or kind != "tree":
        return TRUE_MISMATCH, [], (
            f"封存树 {str(recorded_tree or '(空)')[:12]} 不在对象库里"
            f"（cat-file 给 {kind or '失败'}）—— 旧口径产物（tree 没进对象库），封存树核不了"
            " —— 拿不准不放过"
        )

    if not commit_sha:
        return TRUE_MISMATCH, [], "没给本笔提交，判不出差异该算谁的：拿不准不放过"
    calc = str(tree_without_gates(str(commit_sha)) or "") if callable(tree_without_gates) else ""
    if not calc:
        return TRUE_MISMATCH, [], (
            f"复算本笔提交 {str(commit_sha)[:12]} 去 gates/** 的 tree 失败：拿不准不放过"
        )
    rows = diff_trees(str(recorded_tree), calc) if callable(diff_trees) else None
    if rows is None:
        return TRUE_MISMATCH, [], (
            "封存树与本笔提交树差在哪取不到（git diff 没回东西）—— 拿不准不放过"
        )
    diff = [str(p) for p in rows if str(p).strip()]

    if not diff:
        return BASIS_DRIFT, [], (
            f"门禁跑在 {raw}，本笔父提交已前进到 {parent}（中间 {middle_n} 笔）；"
            "封存树 = 本笔提交树（内容未变）—— 门禁结论**未经复验**，但没有内容差异"
        )

    mid_rows = diff_range(a, b) if callable(diff_range) else None
    mid_set = {_basis_norm(p) for p in (mid_rows or [])}
    diff_n = [_basis_norm(p) for p in diff]

    mine_only = [p for p in diff if _basis_norm(p) in files_n and _basis_norm(p) not in mid_set]
    if mine_only:
        return TRUE_MISMATCH, mine_only, (
            f"封存树 vs 本笔提交树差 {len(diff)} 条，其中 {len(mine_only)} 条"
            f"是**封存之后本笔自己改的**"
            f"（不在中间提交 {raw}..{parent} 里）：{mine_only[:6]} —— 门禁没见过这些内容 ⇒ 照红"
        )
    explained = set(mid_set) | set(files_n)
    unexplained = [p for p in diff if _basis_norm(p) not in explained]
    if unexplained:
        return TRUE_MISMATCH, unexplained, (
            f"封存树 vs 本笔提交树差 {len(diff)} 条，其中 {len(unexplained)} 条**无法解释**"
            f"（既不是中间提交 {raw}..{parent} 带入的、也不在本笔改动里）：{unexplained[:6]}"
            " —— 拿不准不放过"
        )

    profiles = sorted(str(x) for x in required_profiles(diff_n))
    hit = sorted(set(profiles) & {"lang", "product"})
    if hit:
        return TRUE_MISMATCH, diff, (
            f"门禁跑在 {raw}，本笔父提交已前进到 {parent}（中间 {middle_n} 笔），"
            f"差异 {len(diff)} 条"
            f"**落在被测代码档（{'/'.join(hit)}）** —— 门禁没为这些文件跑过：{diff[:6]} ⇒ 照红"
        )
    return BASIS_DRIFT, diff, (
        f"门禁跑在 {raw}，本笔父提交已前进到 {parent}（中间 {middle_n} 笔），差异 {len(diff)} 条"
        f"全由中间提交带入，只落 {'/'.join(profiles)} 档 —— 门禁结论**未经复验**"
    )


def basis_is_red(tier: str) -> bool:
    """只有 BASIS_DRIFT 不算红 —— 其余（含未知值）一律算红。"""
    return str(tier) != BASIS_DRIFT
