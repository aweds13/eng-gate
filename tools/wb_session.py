"""卡 ↔ 对话窗口（DSH 会话）的归属闸。

一个 DSH 窗口有一个稳定指纹 `DSH_SESSION_ID`（环境变量，由宿主注入）。本工具把「哪张卡归哪个窗口」
记进 `gates/diag/session-leases.json`，并在派活/落地前拦「别的窗口的卡」。

三条口径（写死在这里，别处不许再判）：
- **没有指纹就当工人/CLI**：`DSH_SESSION_ID` 缺失时一律放行，否则号池工人、定时巡检全会卡死。
- **首次接触即认领**：没有租约的卡，谁先动谁认领，写进账本并在 stdout 说明。
- **换手要明说**：别的窗口的卡，必须带 `--take-over` 才让过；过了把租约改成当前窗口，
  旧窗口记进 `history`（留痕，不静默抢）。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "gates" / "diag" / "session-leases.json"
TTL_SECONDS = 24 * 3600


def session_id() -> str:
    """当前窗口的指纹；终端里没有就是空串（= 工人口径）。"""
    return os.environ.get("DSH_SESSION_ID", "").strip()


def _load() -> dict:
    if not LEDGER.exists():
        return {"version": 1, "cards": {}}
    try:
        data = json.loads(LEDGER.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "cards": {}}
    if not isinstance(data.get("cards"), dict):
        data["cards"] = {}
    return data


def _save(data: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    tmp = LEDGER.with_suffix(".tmp")
    body = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    tmp.write_text(body + chr(10), encoding="utf-8")
    tmp.replace(LEDGER)


def _stale(entry: dict, now: float) -> bool:
    return now - float(entry.get("since") or 0) > TTL_SECONDS


def owner(card: str) -> str:
    """这张卡现在归谁（空串 = 没人认领 / 租约过期）。"""
    data = _load()
    entry = data["cards"].get(card)
    if not entry or _stale(entry, time.time()):
        return ""
    return str(entry.get("session") or "")


def claim(card: str, take_over: bool = False, note: str = "") -> tuple[bool, str]:
    """认领/校验。返回 (allowed, message)。"""
    sid = session_id()
    if not sid:
        return True, ""
    cur = owner(card)
    data = _load()
    now = time.time()
    if cur and cur != sid and not take_over:
        short = f"{cur[:8]}…"
        return False, (
            f"卡 {card} 归另一个对话窗口（{short}）；换手要显式加 `--take-over`，"
            f"或让那个窗口先 `python tools/wb_session.py --release {card}`"
        )
    prev = data["cards"].get(card) or {}
    history = list(prev.get("history") or [])[-9:]
    if cur and cur != sid:
        history.append({"session": cur, "released_at": int(now), "reason": "take-over"})
    data["cards"][card] = {
        "session": sid,
        "since": int(now),
        "note": note or prev.get("note", ""),
        "history": history,
    }
    _save(data)
    if cur and cur != sid:
        return True, f"卡 {card} 已换手到当前窗口（原 {cur[:8]}…）"
    if not cur:
        return True, f"卡 {card} 归当前窗口（首次接触即认领）"
    return True, ""


def release(card: str) -> str:
    """放开这张卡（谁的窗口都能放开；只动账本，不判归属）。"""
    data = _load()
    entry = data["cards"].pop(card, None)
    if not entry:
        return f"卡 {card} 本来就没有租约"
    _save(data)
    return f"卡 {card} 已释放（原 {str(entry.get('session'))[:8]}…）"


def listing() -> list[dict]:
    now = time.time()
    out = []
    for card, entry in sorted(_load()["cards"].items()):
        out.append({
            "card": card,
            "session": str(entry.get("session") or ""),
            "age_hours": round((now - float(entry.get("since") or now)) / 3600, 1),
            "stale": _stale(entry, now),
        })
    return out


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print(__doc__)
        return 0
    cmd = args[0]
    if cmd in {"--list", "list"}:
        rows = listing()
        if not rows:
            print("  没有租约（谁都没认领过卡）")
            return 0
        for row in rows:
            mark = "过期" if row["stale"] else "在租"
            print(f"  {row['card']:<6} {row['session'][:8]:<10} {row['age_hours']:>5}h {mark}")
        return 0
    if cmd in {"--claim", "claim"} and len(args) > 1:
        ok, msg = claim(args[1], take_over="--take-over" in args)
        print(f"  {msg or '（已在当前窗口名下）'}")
        return 0 if ok else 2
    if cmd in {"--release", "release"} and len(args) > 1:
        print(f"  {release(args[1])}")
        return 0
    print(f"  不认识的参数：{args}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
