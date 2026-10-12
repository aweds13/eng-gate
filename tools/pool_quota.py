r"""额度状态按钟表算（卡 201 · T-G303）—— 429 不许凭记忆，一律「记录时间 vs 现实时间」。

为什么有它（用户 2026-10-12 原话）：

> 「还有 pool 要有个功能，就是你 429 了，**不要凭记忆确定是否 429**，
>   要根据**记录时间和现实时间对比**。」

旧坑三条（都在主树 HEAD 上现读）：
  ① `wb_dispatch.quota_error()` 抠出「将在 <时间> 重置」只当字符串返回 ——
    **全仓没有一处把它解析成时间戳**；
  ② 等待写死 `DEFAULT_QUOTA_WAIT = 300` —— 记录写 5 分钟后还是 5 小时后都睡 300 秒；
  ③ MCP 面不报额度 —— 会话里问「现在能不能派活」得到的是人的记忆，不是读数。

本模块就是那条「记录时间 vs 现实时间」的判据 —— **唯一真源**：
  · `parse_reset(raw)` —— 把「2026-10-12 16:52:45 UTC+8」解析成 `datetime`（解析不出 → None）；
  · `record(...)` —— 把一次 429 落成一条记录（`gates/diag/quota-state.json`，派生、可重建、
    gitignored）；
  · `status(...)` —— 每次现算，读记录 + 读「现在」，输出**四态**（每态带判据）。

★ 四态（每一态都不许猜）：

| 态 | 条件 | 含义 |
|---|---|---|
| `限流中` | `reset_at > now` | 还在限流里，等剩余时间 |
| `已过期，需重新探测` | `reset_at <= now` | 过期 ≠ 可用，只有探测才是证据 |
| `余额耗尽` | 有记录但无 `reset_at` | 没有重置时间 ⇒ 不自动等，只能探 |
| `未记录` | 没有这条记录 | 没记录 ⇒ 不猜（不许默认当可用） |

★ `--now <ISO>`：注入「现在」（测试不许靠真实钟表）。

用法：
    python -X utf8 tools/pool_quota.py status --card 201 --model deepseek-v4.1-flash
    python -X utf8 tools/pool_quota.py status --card 201 --model X --now 2026-10-12T23:28:00+08:00
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

ROOT = Path(__file__).resolve().parent.parent

#: 记录文件（派生、可重建、gitignored —— `gates/diag/` 整体在 .gitignore 里）。
STATE_REL = "gates/diag/quota-state.json"

#: 「将在 <时间> 重置」里那个时间的形状 —— `YYYY-MM-DD HH:MM:SS` + 可选 `UTC+N`。
_RESET_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})"
    r"(?:\s*UTC\s*([+-]?\d{1,2}))?"
)


# ================================================================ 解析（唯一真源）


def parse_reset(raw: str | None) -> datetime | None:
    """把「2026-10-12 16:52:45 UTC+8」解析成 `datetime`；解析不出 → `None`。

    ★ 这是**唯一**的解析真源 —— `wb_dispatch.quota_error()` 加 `reset_at` 字段时调它，
      `record()` 落记录时也调它，**不许在别处再写一份**（本仓最忌两份真源）。
    ★ 解析不出就回 `None` —— **不许拿别的数冒充**（卡 201 硬约束）。

    认的形状：
      · `2026-10-12T16:52:45+08:00`（ISO-8601，`datetime.fromisoformat` 直吃）；
      · `2026-10-12 16:52:45 UTC+8`（CLI / 模型回话里常见的写法）；
      · `2026-10-12 16:52:45`（无时区 → naive，比较时当本地时间）。
    """
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        pass
    m = _RESET_RE.match(raw)
    if m is None:
        return None
    date_part, time_part, tz_hour = m.group(1), m.group(2), m.group(3)
    tz: timezone | None = None
    if tz_hour is not None:
        tz = timezone(timedelta(hours=int(tz_hour)))
    try:
        return datetime.fromisoformat(f"{date_part}T{time_part}").replace(tzinfo=tz)
    except ValueError:
        return None


def _to_aware(dt: datetime) -> datetime:
    """naive → aware（当本地时间）；aware 原样。比较时 aware/naive 混用会抛 `TypeError`。"""
    if dt.tzinfo is None:
        return dt.astimezone()
    return dt


def _resolve_now(now: datetime | str | None) -> datetime:
    """把 `now` 参数统一成 `datetime`：`None` = 真实现在（aware，本地时区）。"""
    if now is None:
        return datetime.now().astimezone()
    if isinstance(now, str):
        return _to_aware(datetime.fromisoformat(now))
    return now


# ================================================================ 记录读写


def _state_path(root: Path = ROOT) -> Path:
    return root / STATE_REL


def _load(root: Path = ROOT) -> dict[str, Any]:
    path = _state_path(root)
    if not path.exists():
        return {"cards": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"cards": {}}
    if not isinstance(data, dict) or not isinstance(data.get("cards"), dict):
        return {"cards": {}}
    return data


def _save(data: dict[str, Any], root: Path = ROOT) -> None:
    path = _state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_record(card: str, model: str, *, root: Path = ROOT) -> dict[str, Any] | None:
    """读一条记录；没有 → `None`。"""
    data = _load(root)
    return data.get("cards", {}).get(card, {}).get(model)


def record(*, card: str, model: str, pool: str, kind: str,
           reset_raw: str, source_log: str | None = None, source_line: int | None = None,
           root: Path = ROOT) -> dict[str, Any]:
    """把一次 429 落成一条记录 —— 同卡同模型覆盖。

    `reset_at` 用 ISO-8601；**解析不出来就写 `null` 并保留 `reset_raw`**（不许拿别的数冒充）。
    `recorded_at` = 真实现在（ISO-8601，aware）。
    """
    reset_dt = parse_reset(reset_raw)
    reset_at = reset_dt.isoformat() if reset_dt is not None else None
    rec: dict[str, Any] = {
        "card": card,
        "model": model,
        "pool": pool,
        "kind": kind,
        "reset_raw": reset_raw,
        "reset_at": reset_at,
        "recorded_at": datetime.now().astimezone().isoformat(),
        "source_log": source_log,
        "source_line": source_line,
    }
    data = _load(root)
    cards = data.setdefault("cards", {})
    cards.setdefault(card, {})[model] = rec
    _save(data, root)
    return rec


# ================================================================ 四态（每次现算）


def status(*, card: str, model: str, now: datetime | str | None = None,
           root: Path = ROOT) -> dict[str, Any]:
    """读记录 + 读「现在」→ 四态。每一态都带**判据**（`why`）。

    ★ **不许猜**：`未记录` 不当可用，`已过期` 不当可用 —— 只有 `限流中` 是确定的「不能派活」，
      其余三态都是「要探测才能确定」。
    """
    rec = read_record(card, model, root=root)
    now_dt = _resolve_now(now)
    now_iso = now_dt.isoformat()
    base: dict[str, Any] = {
        "card": card, "model": model,
        "reset_at": None, "recorded_at": None, "now": now_iso,
        "remaining_seconds": None, "expired_seconds": None,
        "can_dispatch": False, "need_probe": True,
    }
    if rec is None:
        return {**base, "state": "未记录",
                "why": "没有这条记录 ⇒ 不猜（★ 不许默认当可用）"}
    recorded_at = rec.get("recorded_at")
    reset_at_raw = rec.get("reset_at")
    base["recorded_at"] = recorded_at
    if reset_at_raw is None:
        return {**base, "state": "余额耗尽", "reset_at": None,
                "why": "有记录但没有重置时间 ⇒ 不自动等，只能探"}
    try:
        reset_dt = _to_aware(datetime.fromisoformat(reset_at_raw))
    except ValueError:
        return {**base, "state": "余额耗尽", "reset_at": reset_at_raw,
                "why": "reset_at 解析失败 ⇒ 不自动等，只能探"}
    diff = (reset_dt - _to_aware(now_dt)).total_seconds()
    if diff > 0:
        return {**base, "state": "限流中", "reset_at": reset_at_raw,
                "remaining_seconds": int(diff), "need_probe": False,
                "why": f"reset_at > now（剩余 {int(diff)} 秒）"}
    return {**base, "state": "已过期，需重新探测", "reset_at": reset_at_raw,
            "expired_seconds": int(-diff),
            "why": f"reset_at <= now（过期 {int(-diff)} 秒）—— 过期 ≠ 可用，要探"}


# ================================================================ 人话渲染


def _hms(seconds: int | None) -> str:
    if seconds is None:
        return "?"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def render(st: dict[str, Any]) -> str:
    """四态的人话输出 —— 每一态都把**判据**念出来。"""
    state = st["state"]
    lines = [f"[额度] 卡 {st['card']} · 模型 {st['model']} —— {state}"]
    if state == "限流中":
        lines.append(f"  剩余 {_hms(st['remaining_seconds'])}"
                     f"（记录重置时间 {st['reset_at']}；现在 {st['now']}）")
    elif state == "已过期，需重新探测":
        lines.append(f"  过期 {_hms(st['expired_seconds'])}"
                     f"（记录重置时间 {st['reset_at']}；现在 {st['now']}）")
        lines.append("  ★ 过期 ≠ 可用，要探")
    elif state == "余额耗尽":
        lines.append("  没有重置时间 ⇒ 不自动等，只能探")
    elif state == "未记录":
        lines.append("  没记录 ⇒ 不猜（★ 不许默认当可用）")
    lines.append(f"  判据：{st['why']}")
    return "\n".join(lines)


# ================================================================ 等待按记录算


def wait_seconds(reset_at: str | None, fallback: int, *,
                 upper: int | None = None, now: datetime | str | None = None) -> int:
    """按记录算等待：`clamp(reset_at - now, 0, 上限)`；`reset_at` 解析不出 → 退回 `fallback`。

    ★ 卡 201：旧写法一律睡 `fallback`（300 秒）—— 记录写 5 分钟后还是 5 小时后都一样。
      现在按钟表算：`reset_at` 在 1 分钟后 ⇒ 等 60 秒（不睡满 300）。
      上限默认 = `fallback`（不让一个坏记录把派活器冻几小时）。
    """
    if not reset_at:
        return fallback
    try:
        reset_dt = _to_aware(datetime.fromisoformat(reset_at))
    except ValueError:
        return fallback
    now_dt = _to_aware(_resolve_now(now))
    diff = int((reset_dt - now_dt).total_seconds())
    cap = fallback if upper is None else upper
    return max(0, min(diff, cap))


# ================================================================ CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pool_quota.py",
        description="额度状态按钟表算（卡 201）—— 429 不许凭记忆，一律「记录时间 vs 现实时间」。",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_status = sub.add_parser("status", help="看一个卡/模型的额度四态（每次现算）")
    p_status.add_argument("--card", required=True, help="卡号")
    p_status.add_argument("--model", required=True, help="模型名")
    p_status.add_argument("--now", default=None,
                          help="注入「现在」（ISO-8601；测试用，不许靠真实钟表）")
    p_status.add_argument("--root", default=None, help="仓库根（测试用）")
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else ROOT
    if args.cmd == "status":
        st = status(card=args.card, model=args.model, now=args.now, root=root)
        print(render(st))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
