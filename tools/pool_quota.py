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
    python -X utf8 tools/pool_quota.py wait --card 201 --model X --timeout 6h
    python -X utf8 tools/pool_quota.py refresh --card 201 --model X --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

ROOT = Path(__file__).resolve().parent.parent

#: 记录文件（派生、可重建、gitignored —— `gates/diag/` 整体在 .gitignore 里）。
STATE_REL = "gates/diag/quota-state.json"

#: 「上次问过刷新」的时间戳（同目录、派生、gitignored）—— 只为 30 秒抑制，不作判据。
REFRESH_REL = "gates/diag/quota-refresh.json"

# ---- 等待口径直接照 magpie（`quotaWaitMin` / `quotaWaitMax` / `quotaWaitMargin` /
# ---- `quotaRefreshGap`）—— 不是 `wb_dispatch.DEFAULT_QUOTA_WAIT = 300`（那是派活器兜底）。
WAIT_MIN_S = 60          # magpie quotaWaitMin = time.Minute
WAIT_MAX_S = 600         # magpie quotaWaitMax = 10 * time.Minute
WAIT_MARGIN_S = 30       # magpie quotaWaitMargin = 30 * time.Second
REFRESH_GAP_S = 30       # magpie quotaRefreshGap = 30 * time.Second

#: 退出码（`--card` / `--model` 缺参由 argparse 直接退 2 = `EXIT_USAGE`）。
EXIT_OK, EXIT_TIMEOUT, EXIT_USAGE, EXIT_INTERRUPT = 0, 1, 2, 130

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


# ================================================================ 等待子命令（magpie 移植）


def round_wait(back_at: str | None, *, now: datetime | str | None = None) -> tuple[int, str]:
    """按「最早续期」算**一轮**睡多久：`clamp(diff + 30, 60, 600)`；续期未知 ⇒ 睡满 600。

    ★ 三件事都不许省：① 加 `WAIT_MARGIN_S`（续期到点还差一口气，早醒就白等）；
      ② 下限 `WAIT_MIN_S`（**不许负数 / 不许 0** —— 已过期的记录不许把循环烧成忙等）；
      ③ 上限 `WAIT_MAX_S`（一个坏记录不许把 `wait` 冻几小时）。
    ★ 口径照 magpie 的 `quotaWaitMin/Max/Margin`，**不是** `DEFAULT_QUOTA_WAIT = 300`。
    """
    if not back_at:
        return WAIT_MAX_S, "未知续期 ⇒ 睡满上限"
    try:
        back_dt = _to_aware(datetime.fromisoformat(back_at))
    except ValueError:
        return WAIT_MAX_S, "未知续期 ⇒ 睡满上限"
    diff = (back_dt - _to_aware(_resolve_now(now))).total_seconds()
    seconds = min(max(int(diff) + WAIT_MARGIN_S, WAIT_MIN_S), WAIT_MAX_S)
    return seconds, f"最早续期 + {WAIT_MARGIN_S}s（clamp 到 {WAIT_MIN_S}..{WAIT_MAX_S}）"


# ---------------------------------------------------------------- 刷新时间戳


def refresh_stamp_path(root: Path = ROOT) -> Path:
    """「上次问过刷新」的时间戳文件（派生、可重建、gitignored）。"""
    return root / REFRESH_REL


def refresh_key(card: str, model: str) -> str:
    """同卡同模型一条 key（小写化 —— 模型名大小写不当成两个模型）。"""
    return f"{card}|{model}".lower()


def _load_refresh(root: Path = ROOT) -> dict[str, Any]:
    path = refresh_stamp_path(root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def refreshed_within(key: str, *, now: datetime | str | None = None,
                     root: Path = ROOT) -> float | None:
    """距上次「问过刷新」的秒数；`None` = 没问过 / 读不懂。

    ★ **读不懂就当作没问过，立刻可问** —— 30 秒抑制只许建立在可信的时间戳上；
      坏 JSON / 坏时间字符串不许把刷新能力冻住（宁可多问一次，不可不问）。
    """
    raw = _load_refresh(root).get(key.lower())
    if not isinstance(raw, str):
        return None
    try:
        last = _to_aware(datetime.fromisoformat(raw))
    except ValueError:
        return None
    return (_to_aware(_resolve_now(now)) - last).total_seconds()


def note_refreshed(key: str, *, now: datetime | str | None = None,
                   root: Path = ROOT) -> None:
    """记一条「刚问过刷新」（key 小写化；`tmp` + `os.replace` 原子替换，不写半截文件）。"""
    path = refresh_stamp_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamps = _load_refresh(root)
    stamps[key.lower()] = _to_aware(_resolve_now(now)).isoformat()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(stamps, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------- 时长解析


_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)([smhd]?)", re.IGNORECASE)
_UNIT_S = {"": 1.0, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}


def parse_timeout(raw: str) -> float:
    """`30s` / `5m` / `2h` / `6h` / 纯数字（秒）→ 秒数；解析不出抛 `ValueError`。"""
    m = _DURATION_RE.fullmatch((raw or "").strip())
    if m is None:
        raise ValueError(f"解析不出时长：{raw!r}（认 30s / 5m / 2h / 6h）")
    return float(m.group(1)) * _UNIT_S[m.group(2).lower()]


# ---------------------------------------------------------------- 等 / 刷新


def _recorded_after(st: dict[str, Any], *, after: datetime) -> bool:
    """记录里的 `recorded_at` 是否**严格晚于** `after` —— 只有它才算「有人探过了」。"""
    raw = st.get("recorded_at")
    if not isinstance(raw, str):
        return False
    try:
        return _to_aware(datetime.fromisoformat(raw)) > after
    except ValueError:
        return False


def wait_until(*, card: str, model: str, timeout: str = "6h", quiet: bool = False,
               now: datetime | str | None = None, root: Path = ROOT) -> int:
    """等一个卡/模型从「不能派活」走到「有证据说明能派活」；等不到 ⇒ `EXIT_TIMEOUT`。

    ★ **不许凭空判成功**（本卡最值钱的一条）：
      · `限流中` ⇒ 按 `round_wait` 睡（按记录算，不睡死 300 秒）；
      · `已过期，需重新探测` / `余额耗尽` / `未记录` ⇒ **都不算成功**；只有看到一条
        `recorded_at` 严格晚于本次等待起点的记录，才退 `EXIT_OK`；
      · 认不出的状态（包括别人塞进来的「可派」）⇒ 同样不算成功，一路等到超时。
    ★ **零网络**：本模块不碰任何网络；探测在 `tools/pool_accounts.py`，`refresh` 只记时间戳。
    ★ 时钟：给了 `now` 就全程走**虚拟钟**（睡多少推多少），测试里一条真实钟表都不许碰。
    """
    base_now = _to_aware(_resolve_now(now)) if now is not None else None
    slept = 0.0

    def _tick() -> datetime:
        if base_now is None:
            return datetime.now().astimezone()
        return base_now + timedelta(seconds=slept)

    try:
        limit = parse_timeout(timeout)
    except ValueError as exc:
        print(f"[额度等待] {exc}", file=sys.stderr)
        return EXIT_USAGE
    started = _tick()
    if not quiet:
        print(f"[额度等待] 卡 {card} · 模型 {model} —— 上限 {timeout}"
              f"（{limit:.0f}s；起点 {started.isoformat()}）")
    hinted = False
    try:
        while True:
            left = limit - slept
            if left <= 0:
                if not quiet:
                    print(f"[额度等待] 卡 {card} · 模型 {model} —— 超时（{limit:.0f}s）："
                          "没看到比起点更新的记录 ⇒ 退 1（★ 不许凭空判成功）")
                return EXIT_TIMEOUT
            now_dt = _tick()
            st = status(card=card, model=model, now=now_dt, root=root)
            state = st["state"]
            if state == "限流中":
                seconds, why = round_wait(st["reset_at"], now=now_dt)
                nap = min(float(seconds), left)
                if not quiet:
                    print(f"[额度等待] 限流中 —— 睡 {nap:.0f}s（{why}；"
                          f"记录重置 {st['reset_at']}）")
            elif state == "已过期，需重新探测" and _recorded_after(st, after=started):
                if not quiet:
                    print(f"[额度等待] 卡 {card} · 模型 {model} —— 有了新记录"
                          f"（recorded_at {st['recorded_at']} 晚于起点）⇒ 退 0")
                return EXIT_OK
            else:
                nap = min(float(REFRESH_GAP_S), left)
                if not quiet and not hinted:
                    print(f"[额度等待] {state} —— 不算成功（★ 过期 ≠ 可用），等一条比起点"
                          "更新的记录；先跑 refresh（探测在 tools/pool_accounts.py）")
                    hinted = True
            time.sleep(nap)
            slept += nap
    except KeyboardInterrupt:
        print(f"[额度等待] 卡 {card} · 模型 {model} —— 收到中断，停在第 {slept:.0f}s")
        return EXIT_INTERRUPT


def refresh_once(*, card: str, model: str, now: datetime | str | None = None,
                 root: Path = ROOT) -> dict[str, Any]:
    """问一次「要不要重新探测」—— `REFRESH_GAP_S` 内问过就跳过；**不联网**。

    ★ 跳过只省重复问，**不是**「额度可用」的判据 —— 判定仍归 `status()` 的四态。
    """
    key = refresh_key(card, model)
    since = refreshed_within(key, now=now, root=root)
    out: dict[str, Any] = {
        "card": card, "model": model, "key": key, "gap_seconds": REFRESH_GAP_S,
        "seconds_since_last": since, "probe": False, "network": False, "why": "",
    }
    if since is not None and since < REFRESH_GAP_S:
        out["why"] = f"{REFRESH_GAP_S} 秒内已看过，跳过"
        return out
    note_refreshed(key, now=now, root=root)
    out["probe"] = True
    out["why"] = "需要重新探测（探测在 tools/pool_accounts.py）—— 本命令不联网"
    return out


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
    p_wait = sub.add_parser("wait", help="等额度（按记录算等待；等不到退 1）")
    p_wait.add_argument("--card", required=True, help="卡号")
    p_wait.add_argument("--model", required=True, help="模型名")
    p_wait.add_argument("--timeout", default="6h", help="总上限（30s / 5m / 2h；默认 6h）")
    p_wait.add_argument("-q", "--quiet", action="store_true", help="不打印过程")
    p_wait.add_argument("--now", default=None,
                        help="注入「现在」（ISO-8601；测试用，不许靠真实钟表）")
    p_wait.add_argument("--root", default=None, help="仓库根（测试用）")
    p_refresh = sub.add_parser("refresh", help="问一次要不要重新探测（30 秒内不重复问）")
    p_refresh.add_argument("--card", required=True, help="卡号")
    p_refresh.add_argument("--model", required=True, help="模型名")
    p_refresh.add_argument("--json", action="store_true", help="输出 JSON")
    p_refresh.add_argument("--now", default=None,
                           help="注入「现在」（ISO-8601；测试用，不许靠真实钟表）")
    p_refresh.add_argument("--root", default=None, help="仓库根（测试用）")
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else ROOT
    if args.cmd == "status":
        st = status(card=args.card, model=args.model, now=args.now, root=root)
        print(render(st))
        return EXIT_OK
    if args.cmd == "wait":
        return wait_until(card=args.card, model=args.model, timeout=args.timeout,
                          quiet=args.quiet, now=args.now, root=root)
    if args.cmd == "refresh":
        out = refresh_once(card=args.card, model=args.model, now=args.now, root=root)
        if args.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            print(f"[额度刷新] 卡 {out['card']} · 模型 {out['model']} —— {out['why']}")
        return EXIT_OK
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
