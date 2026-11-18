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
