r"""wb_notify —— 收工回推通道的判据（卡 A297 · T-AG411）。

钉三件事：
  1. **JSONL 追加** —— verdict 文件在 ⇒ notifications.jsonl 多一条，字段齐全；
  2. **幂等** —— 连跑两次 `scan_once`，行数不变（同卡同判决不重复写）；
  3. **done 过滤** —— 卡在 backlog 里 `status == "done"` ⇒ 不产生通知。

★ 只读 verdict / backlog 文件，不碰真仓；用 tmp_path fixture 自造最小仓。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_notify as wn  # noqa: E402 —— 先挂 tools/ 才能 import


def _verdict(path: Path, *, card: str, verdict: str = "正常收工",
             ended_at: str = "2026-10-19T19:24:00") -> Path:
    """造一份最小判决文件（首行带 `结束于=`、`判决：` 行；口径照 wb_dispatch.write_verdict）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"card={card} 第=1 次 退出码=0 会话=abc 开始于={ended_at} 结束于={ended_at}\n"
        f"判决：{verdict}\n"
        "诊断（这一轮断在哪）：\n"
        f"  退出码=0；有 result 事件=有\n",
        encoding="utf-8",
    )
    return path


def _backlog(root: Path, cards: list[tuple[str, str]]) -> Path:
    """造一份最小 `docs/workbacklog.toml`（cards = [(id, status), ...]）。"""
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    parts = ["[base]", 'reviewed = "deadbeef"', ""]
    for cid, status in cards:
        parts += [
            "[[cards]]",
            f'id = "{cid}"',
            'task = "T-X"',
            f'title = "smoke-{cid}"',
            'tree = ""',
            'spec = "x.md"',
            "files = []",
            "depends = []",
            'risk = "low"',
            f'status = "{status}"',
            "",
        ]
    path = docs / "workbacklog.toml"
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


# ---------------------------------------------------------------- 1. JSONL 追加 + 字段

def test_scan_once_writes_a_notification_with_fixed_fields(tmp_path: Path) -> None:
    """verdict 在、卡未落地 ⇒ notifications.jsonl 多一条，字段 = at/card/verdict/report。"""
    diag = tmp_path / "gates" / "diag"
    _verdict(diag / "wb-A289.verdict.txt", card="A289", verdict="正常收工",
             ended_at="2026-10-19T19:24:00")
    _backlog(tmp_path, [("A289", "pending")])
    out = diag / "notifications.jsonl"

    assert not out.exists()
    wrote = wn.scan_once(tmp_path, diag=diag, out_path=out)
    assert wrote == 1
    assert out.is_file()
    lines = [ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert set(row) == {"at", "card", "verdict", "report"}
    assert row["card"] == "A289"
    assert row["verdict"] == "正常收工"
    assert row["at"] == "2026-10-19T19:24:00"
    assert row["report"] == "gates/diag/wb-A289.report.md"


def test_scan_once_picks_latest_verdict_when_retry_exists(tmp_path: Path) -> None:
    """两张判决（r1 / r2）⇒ 取最新那条的判决文本（不混淆两轮）。"""
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True, exist_ok=True)
    _verdict(diag / "wb-A289.verdict.txt", card="A289", verdict="判死：卡死",
             ended_at="2026-10-19T18:00:00")
    # r2 更新（mtime 更晚）⇒ 取它
    r2 = _verdict(diag / "wb-A289.r2.verdict.txt", card="A289", verdict="正常收工",
                  ended_at="2026-10-19T19:24:00")
    # 确保 r2 的 mtime 比 r1 新
    import os
    older = diag / "wb-A289.verdict.txt"
    os.utime(older, (older.stat().st_mtime - 60, older.stat().st_mtime - 60))
    os.utime(r2, (r2.stat().st_mtime + 60, r2.stat().st_mtime + 60))
    _backlog(tmp_path, [("A289", "pending")])
    out = diag / "notifications.jsonl"

    wrote = wn.scan_once(tmp_path, diag=diag, out_path=out)
    assert wrote == 1
    row = json.loads(out.read_text(encoding="utf-8").strip())
    assert row["verdict"] == "正常收工"
    assert row["report"] == "gates/diag/wb-A289.r2.report.md"


# ---------------------------------------------------------------- 2. 幂等

def test_scan_once_is_idempotent(tmp_path: Path) -> None:
    """连跑两次 ⇒ 第二次新写 0 条，文件行数不变（同卡同判决不重复写）。"""
    diag = tmp_path / "gates" / "diag"
    _verdict(diag / "wb-A289.verdict.txt", card="A289", verdict="正常收工")
    _backlog(tmp_path, [("A289", "pending")])
    out = diag / "notifications.jsonl"

    first = wn.scan_once(tmp_path, diag=diag, out_path=out)
    assert first == 1
    lines_after_first = out.read_text(encoding="utf-8").splitlines()

    second = wn.scan_once(tmp_path, diag=diag, out_path=out)
    assert second == 0
    lines_after_second = out.read_text(encoding="utf-8").splitlines()
    assert lines_after_first == lines_after_second


def test_scan_once_idempotent_across_different_cards(tmp_path: Path) -> None:
    """多卡幂等：A289 已写、A294 新来 ⇒ 只多 A294 一条。"""
    diag = tmp_path / "gates" / "diag"
    _verdict(diag / "wb-A289.verdict.txt", card="A289", verdict="正常收工")
    _backlog(tmp_path, [("A289", "pending"), ("A294", "pending")])
    out = diag / "notifications.jsonl"
    assert wn.scan_once(tmp_path, diag=diag, out_path=out) == 1  # A289

    _verdict(diag / "wb-A294.verdict.txt", card="A294", verdict="正常收工")
    assert wn.scan_once(tmp_path, diag=diag, out_path=out) == 1  # A294
    rows = [json.loads(ln) for ln in
            out.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert {r["card"] for r in rows} == {"A289", "A294"}
    # 再跑一次 ⇒ 0（都幂等）
    assert wn.scan_once(tmp_path, diag=diag, out_path=out) == 0


def test_scan_once_new_verdict_for_same_card_writes_again(tmp_path: Path) -> None:
    """同卡但判决**变了**（重试后）⇒ 写新一条（幂等键是 (card, verdict)，不是 card）。"""
    diag = tmp_path / "gates" / "diag"
    _verdict(diag / "wb-A289.verdict.txt", card="A289", verdict="判死：卡死")
    _backlog(tmp_path, [("A289", "pending")])
    out = diag / "notifications.jsonl"
    assert wn.scan_once(tmp_path, diag=diag, out_path=out) == 1

    # 重试后判决变了（mtime 也更晚）⇒ 取新判决
    import os
    older = diag / "wb-A289.verdict.txt"
    new = diag / "wb-A289.r2.verdict.txt"
    _verdict(new, card="A289", verdict="正常收工")
    os.utime(older, (older.stat().st_mtime - 60, older.stat().st_mtime - 60))
    os.utime(new, (new.stat().st_mtime + 60, new.stat().st_mtime + 60))

    assert wn.scan_once(tmp_path, diag=diag, out_path=out) == 1
    rows = [json.loads(ln) for ln in
            out.read_text(encoding="utf-8").splitlines() if ln.strip()]
    verdicts = sorted(r["verdict"] for r in rows)
    assert verdicts == ["判死：卡死", "正常收工"]


# ---------------------------------------------------------------- 3. done 过滤

def test_scan_once_skips_done_cards(tmp_path: Path) -> None:
    """卡在 backlog 里 status == "done" ⇒ 不产生通知（已落地）。"""
    diag = tmp_path / "gates" / "diag"
    _verdict(diag / "wb-A289.verdict.txt", card="A289", verdict="正常收工")
    _backlog(tmp_path, [("A289", "done")])  # 已落地
    out = diag / "notifications.jsonl"

    assert wn.scan_once(tmp_path, diag=diag, out_path=out) == 0
    assert not out.exists()


def test_scan_once_skips_done_but_keeps_pending(tmp_path: Path) -> None:
    """混批：A289 done、A294 pending ⇒ 只写 A294 一条。"""
    diag = tmp_path / "gates" / "diag"
    _verdict(diag / "wb-A289.verdict.txt", card="A289", verdict="正常收工")
    _verdict(diag / "wb-A294.verdict.txt", card="A294", verdict="正常收工")
    _backlog(tmp_path, [("A289", "done"), ("A294", "pending")])
    out = diag / "notifications.jsonl"

    assert wn.scan_once(tmp_path, diag=diag, out_path=out) == 1
    row = json.loads(out.read_text(encoding="utf-8").strip())
    assert row["card"] == "A294"


# ---------------------------------------------------------------- 边界

def test_scan_once_with_no_verdicts_writes_zero(tmp_path: Path) -> None:
    """没 verdict 文件 ⇒ 0 条、不建文件。"""
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True, exist_ok=True)
    _backlog(tmp_path, [("A289", "pending")])
    out = diag / "notifications.jsonl"
    assert wn.scan_once(tmp_path, diag=diag, out_path=out) == 0
    assert not out.exists()


def test_scan_once_ignores_verdict_without_judgment_line(tmp_path: Path) -> None:
    """判决文件没有「判决：」行 ⇒ 不算收工，跳过（空/半截判决不算）。"""
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True, exist_ok=True)
    (diag / "wb-A300.verdict.txt").write_text(
        "card=A300 第=1 次 退出码=0\n（没有判决行）\n", encoding="utf-8")
    _backlog(tmp_path, [("A300", "pending")])
    out = diag / "notifications.jsonl"
    assert wn.scan_once(tmp_path, diag=diag, out_path=out) == 0


def test_scan_once_falls_back_to_mtime_when_no_ended_at(tmp_path: Path) -> None:
    """判决文件没有 `结束于=` ⇒ at 用文件 mtime（仍 ISO8601，不空）。"""
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True, exist_ok=True)
    path = diag / "wb-A301.verdict.txt"
    path.write_text("判决：正常收工\n", encoding="utf-8")
    _backlog(tmp_path, [("A301", "pending")])
    out = diag / "notifications.jsonl"
    assert wn.scan_once(tmp_path, diag=diag, out_path=out) == 1
    row = json.loads(out.read_text(encoding="utf-8").strip())
    assert row["at"]  # 非空
    # 能被 fromisoformat 解析
    from datetime import datetime
    datetime.fromisoformat(row["at"])


def test_load_existing_skips_bad_lines(tmp_path: Path) -> None:
    """notifications.jsonl 有坏行 ⇒ 跳过，不让整份文件废掉。"""
    out = tmp_path / "notifications.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"at": "t1", "card": "A289", "verdict": "正常收工",
                    "report": "gates/diag/wb-A289.report.md"}) + "\n"
        "这不是 JSON\n"
        "\n"
        + json.dumps({"at": "t2", "card": "A294", "verdict": "正常收工",
                       "report": "gates/diag/wb-A294.report.md"}) + "\n",
        encoding="utf-8")
    seen = wn._load_existing(out)
    assert seen == {("A289", "正常收工"), ("A294", "正常收工")}


def test_done_cards_reads_sharded_backlog(tmp_path: Path) -> None:
    """分片 backlog（docs/backlog/<区>.toml）也能读出 done 集合。"""
    shard = tmp_path / "docs" / "backlog"
    shard.mkdir(parents=True, exist_ok=True)
    # 分片也是一份完整 backlog（要 [base] + [[cards]]，见 pool.plan.merge_shards）
    (shard / "A.toml").write_text(
        "[base]\nreviewed = \"deadbeef\"\n\n"
        "[[cards]]\nid = \"A297\"\ntask = \"T-X\"\ntitle = \"t\"\n"
        'tree = ""\nspec = "x.md"\nfiles = []\ndepends = []\nrisk = "low"\n'
        'status = "done"\n', encoding="utf-8")
    (tmp_path / "docs" / "workbacklog.toml").write_text(
        "[base]\nreviewed = \"deadbeef\"\n", encoding="utf-8")
    assert wn._done_cards(tmp_path) == {"A297"}


def test_done_cards_empty_when_backlog_missing(tmp_path: Path) -> None:
    """backlog 读不到 ⇒ 空 done 集合（**不许**把读不到当成全部已落地）。"""
    assert wn._done_cards(tmp_path) == set()
