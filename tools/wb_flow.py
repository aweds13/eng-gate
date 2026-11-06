r"""wb_flow —— 队列流量仪表（只读）：把「会不会收敛/收敛」变成读数（卡 164 / T-G264）。

为什么要有它：用户问「全部做完大概要多久？」→ 主控先答「按现在的动态永远不会空」→
用户追问「你确定到最后不会收敛吗？」⇒ 主控那条断言太强。正确的做法不是争，是**量**。
本工具每天/每次跑，输出四个数 + 流量分解，让「收敛/平台/发散」变成机器判据。

用法：
    python -X utf8 tools/wb_flow.py              # 人读报告
    python -X utf8 tools/wb_flow.py --json       # 机器可读
    python -X utf8 tools/wb_flow.py --since midnight   # 窗口（默认今天 0 点）

四个数：
  1. 到达 = 窗口内 `docs/workbacklog.toml` 里**新增**的卡 id（按 git diff 现算）；
  2. 离开 = 窗口内标成 `done`/`failed` 的卡数（同一窗口的 git diff）；
  3. WIP = 当前 `status == "pending"` 的卡数（就是今天的「待派」）；
  4. 流量分解 = 新增卡按**来源**分类 —— 从卡的 `why` 字段现读
     （`用户提问/裁定` · `文献/外部调研` · `审计/复核发现` · `(坑)现场咬出来的` · `结构性重构`）；
     读不到 ⇒ `未标`（**不许猜**）。

判据（这才是「会不会收敛」的机器判据，不许拍）：
  - 到达 < 离开 ⇒ 收敛中；
  - 到达 ≈ 离开 ⇒ 平台；
  - 到达 > 离开 连续 N 天 ⇒ 报警。

★ 只读：不改队列、不判断「该不该立卡」（那是产品决定）。
★ 边界：`why` 字段缺 ⇒ 标 `未标`，不猜来源。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

import tomllib
import wb_plan  # 台账分片（卡 E89）：分片目录 / 分片读法只此一份

ROOT = Path(__file__).resolve().parent.parent
BACKLOG = ROOT / "docs" / "workbacklog.toml"

#: 合法的来源标签（卡的 `why` 字段里写其中一个；不在表里 ⇒ `未标`）。
SOURCES = ("用户提问/裁定", "文献/外部调研", "审计/复核发现", "坑（现场咬出来的）", "结构性重构")
UNTAGGED = "未标"

_ID_RE = re.compile(r'^\+id\s*=\s*"([^"]+)"')
_STATUS_DONE_RE = re.compile(r'^\+status\s*=\s*"(done|failed)"')


def _git_diff_ids(since: str) -> tuple[set[str], set[str]]:
    """窗口内 workbacklog 的 git diff 里**新增**的卡 id 与**标成 done/failed**的卡 id。

    用 `git log -p --since=<窗口> -- docs/workbacklog.toml docs/backlog` 拿补丁，扫
    `+id = "..."` 行（新增条目）与 `+status = "done"/"failed"` 行（标成离开）。★ 只读 git。
    ★ 卡 E89：分片启用后新卡进 `docs/backlog/*.toml` —— 历史路径必须覆盖这一层，
      否则「到达」恒为 0（静默少记）。
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "log", "-p", f"--since={since}",
             "--pretty=format:%H%x1e", "--", "docs/workbacklog.toml", "docs/backlog"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            # ★ 防窗旗（卡 164）：Windows 上别弹控制台窗口（POSIX 上落到 0 = 无操作）。
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=30, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return set(), set()
    arrived: set[str] = set()
    left: set[str] = set()
    current_ids: set[str] = set()
    for line in out.splitlines():
        if line == "\x1e":                              # 提交分隔
            current_ids = set()
            continue
        m = _ID_RE.match(line)
        if m:
            current_ids.add(m.group(1))
            arrived.add(m.group(1))
        m2 = _STATUS_DONE_RE.match(line)
        if m2:
            left |= current_ids                         # 这一提交里标成 done 的卡
    return arrived, left


def _queue_sources() -> list[Path]:
    """队列的**来源文件**：`BACKLOG` 旁边有 `backlog/*.toml` 分片就只算分片（卡 E89）。

    ★ 从模块级 `BACKLOG` 现推（测试会 monkeypatch 它），不另起 ROOT 常量。
    """
    shards = wb_plan.shard_files(BACKLOG.parent / "backlog")
    return shards if shards else [BACKLOG]


def load_backlog() -> list[dict]:
    """读当前 workbacklog.toml（或分片）的全部卡（**不校验**）。读不了 ⇒ 空列表。"""
    cards: list[dict] = []
    try:
        for path in _queue_sources():
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            cards.extend(c for c in data.get("cards", []) if isinstance(c, dict))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    return cards


def _source_of(card: dict) -> str:
    """卡的来源：读 `why` 字段，落在 SOURCES 里就用它，否则 `未标`（**不猜**）。"""
    why = str(card.get("why") or "").strip()
    for src in SOURCES:
        if src in why:
            return src
    return UNTAGGED


def flow_snapshot(since: str = "midnight") -> dict:
    """四个数 + 流量分解 + 判据。"""
    arrived_ids, left_ids = _git_diff_ids(since)
    cards = load_backlog()
    wip = sum(1 for c in cards if str(c.get("status") or "") == "pending")
    # 流量分解：新增卡按来源
    by_source: dict[str, int] = {src: 0 for src in SOURCES}
    by_source[UNTAGGED] = 0
    arrived_cards = [c for c in cards if str(c.get("id") or "") in arrived_ids]
    for c in arrived_cards:
        by_source[_source_of(c)] += 1
    arrived = len(arrived_ids)
    left = len(left_ids)
    # 判据：到达 < 离开 ⇒ 收敛中；≈ ⇒ 平台；> ⇒ 报警（单窗口看不出「连续 N 天」）
    if arrived < left:
        verdict = "收敛中"
    elif abs(arrived - left) <= max(1, left // 10):
        verdict = "平台"
    else:
        verdict = "到达 > 离开（报警：单窗口看不出连续性，多跑几天再判）"
    return {
        "since": since,
        "arrived": arrived,
        "left": left,
        "wip": wip,
        "by_source": by_source,
        "verdict": verdict,
        "arrived_ids": sorted(arrived_ids),
        "left_ids": sorted(left_ids),
    }


def render_report(snap: dict) -> str:
    lines = [
        f"=== 队列流量（窗口 {snap['since']}）===",
        f"  到达 {snap['arrived']} · 离开 {snap['left']} · WIP {snap['wip']}",
        f"  判据：{snap['verdict']}",
        "  流量分解（新增卡按来源）：",
    ]
    for src, n in snap["by_source"].items():
        if n or src == UNTAGGED:
            lines.append(f"    {src}：{n}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="队列流量仪表（只读）：到达/离开/WIP/流量分解")
    ap.add_argument("--since", default="midnight", help="窗口（git --since 的值，默认 midnight）")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args()
    snap = flow_snapshot(args.since)
    if args.json:
        print(json.dumps(snap, ensure_ascii=False, indent=2))
    else:
        print(render_report(snap))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
