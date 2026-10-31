"""卡 A355（`T-AG564`）：**按请求**算结局 —— 13 条钉子，逐条钉行为或源码事实。

为什么值当测：`gates/diag/wb-usage.jsonl` 是**每轮一行**，于是「轮数」随处可算；缺的是
「这个请求最后成没成、一共试了几次」。结局判据只有一份（`tools/pool/outcomes.py`），
写侧（`wb_dispatch`）把它一次写对 —— 这两侧任何一侧松了，读数都会悄悄变成「按轮」。
所以这里既钉读（`count_requests` / `request_of` / `is_failed`），也钉写（`append_usage_line`
的三列与唯一调用点），还钉「`should_resume` 每轮只算一次」（判据只有一份）。

★ 一律用隔壁 `tests/test_wb_dispatch.py` 的 `sandbox` 夹具：`wd.ROOT` 被 patch 到临时目录
  ⇒ 落盘的 `wb-usage.jsonl` 绝不碰真仓（那是本机运行状态，测试不该写它）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import test_wb_dispatch as twd
from pool import outcomes as oc

from tools import wb_session as wb_session

ROOT = Path(__file__).resolve().parent.parent
# ★ 必须复用隔壁模块那个 `wd` **对象**（`from tools import wb_dispatch` 会执行出第二个
#   模块 —— 夹具 patch 的 `ROOT` 就落不到它身上）。
wd = twd.wd

#: 沙箱夹具在隔壁模块（同一套「像仓库的临时根」，别再造一份）。
sandbox = twd.sandbox

#: 改造前那一行的 11 个键，**一个不许少、类型不许变**（钉子 9）。
OLD_KEYS = ("卡", "模型", "轮次", "开始", "结束", "用时分钟", "input_tokens",
            "output_tokens", "cache_read", "退出码", "判决")
#: 本卡新加的三个结局列（钉子 9）。
NEW_KEYS = (oc.OUTCOME_TRIES, oc.OUTCOME_HANDED_ON, oc.OUTCOME_STOP)

_USAGE = {"input_tokens": 10, "output_tokens": 2, "cache_read": 3}


@pytest.fixture(autouse=True)
def isolated_session_ledger(tmp_path: Path, monkeypatch) -> Path:
    """照隔壁模块同款隔离：`wd.main()` 的 `wb_session.claim()` 不许写**真**账本。"""
    ledger = tmp_path / "gates" / "diag" / "session-leases.json"
    monkeypatch.setattr(wb_session, "LEDGER", ledger)
    return ledger


def _row(*, card: str = "001", round_no: int = 1, code: int = 0,
         reason: str = "正常收工", **extra: object) -> dict:
    """造一行 `wb-usage.jsonl` 形状的账（键与 `append_usage_line()` 落盘的一致）。"""
    row: dict = {"卡": card, "模型": "m", "轮次": round_no,
                 "开始": "2026-01-01T00:00:00", "结束": "2026-01-01T00:01:00",
                 "用时分钟": 1.0, **_USAGE, "退出码": code, "判决": reason}
    row.update(extra)
    return row


def _usage_rows(root: Path) -> list[dict]:
    path = root / "gates" / "diag" / "wb-usage.jsonl"
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _runner(verdicts: list[str], calls: list[list[str]]):
    """假工人：第 N 次按 `verdicts[N-1]` 报判决，事件流用隔壁那份 `EVENTS`。"""
    def run(cmd, log, errlog, **kwargs):          # noqa: ANN001, ANN202
        n = len(calls)
        calls.append(list(cmd))
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("\n".join(twd.EVENTS) + "\n", encoding="utf-8")
        errlog.write_text("", encoding="utf-8")
        return 0, verdicts[n], "", "sid-abc"
    return run


# ============================================ 读侧：`count_requests()` 的三条口径（钉子 1-3）


def test_handed_on_row_is_neither_a_request_nor_a_failure() -> None:
    """交出去的 try：**不计**请求、**不计**失败；后来的 try 答上了算「重试答上」。"""
    rows = [_row(round_no=1, code=6, reason="卡死：8 分钟没有新事件", handed_on=True, tries=1),
            _row(round_no=2, code=0, reason="正常收工", tries=2)]
    got = oc.count_requests(rows, card="001")
    assert got == {"requests": 1, "errors": 0, "retried": 1, "handed_on": 1}, got


def test_failed_last_try_counts_as_error() -> None:
    """最后一轮也失败 ⇒ 这个请求**算一次失败**（不是两次、也不是零次）。"""
    rows = [_row(round_no=1, code=6, reason="卡死：8 分钟没有新事件", handed_on=True, tries=1),
            _row(round_no=2, code=4, reason="工人非零退出", tries=2)]
    got = oc.count_requests(rows, card="001")
    assert got["requests"] == 1 and got["errors"] == 1, got
    assert got["retried"] == 0, "失败的那一轮不许算成「重试答上」"


def test_all_handed_on_rows_leave_zero_requests() -> None:
    """全是交出去的 try ⇒ `requests == 0`（不是 1）—— 咬「跳过」那条语句本身。"""
    rows = [_row(round_no=1, code=6, reason="卡死", handed_on=True, tries=1),
            _row(round_no=2, code=6, reason="超时", handed_on=True, tries=1)]
    got = oc.count_requests(rows, card="001")
    assert got["requests"] == 0, got
    assert got["errors"] == 0 and got["retried"] == 0, got
    assert got["handed_on"] == 2, got


# ============================================ `tries` 只写在结局行（钉子 4）


def test_tries_only_on_the_outcome_row(sandbox: Path, monkeypatch, capsys) -> None:
    """★ 端到端：两轮被掐 + 第三轮成功 ⇒ 交出去的行 `tries` 恒 1，**结局行**才写 3。"""
    calls: list[list[str]] = []
    monkeypatch.setattr(wd, "run_worker", _runner(
        ["卡死：8.0 分钟没有新事件 → 已掐", "卡死：8.0 分钟没有新事件 → 已掐", ""], calls))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute", "--retry", "2"])
    assert wd.main() == 0
    capsys.readouterr()
    rows = _usage_rows(sandbox)
    assert [r["轮次"] for r in rows] == [1, 2, 3], rows
    assert [r["handed_on"] for r in rows] == [True, True, False], rows
    assert [r["tries"] for r in rows] == [1, 1, 3], "交出去的行恒 1（不累加）；结局行才是总轮数"


# ============================================ 老行 / 空值 / tier（钉子 5-7）


def test_old_rows_without_outcome_keys_read_as_one_try() -> None:
    """老行（没有 `tries`/`handed_on` 键）⇒ `tries=1`、`handed_on=False`，**不许崩**。"""
    old = _row(round_no=3, code=0, reason="正常收工")
    assert "tries" not in old and "handed_on" not in old
    one = oc.request_of([old], card="001")
    assert len(one) == 1
    assert one[0].tries == 1 and one[0].handed_on is False, one[0]
    assert one[0].stop == "" and one[0].tier_served == "", "缺键一律读成空串，不猜"
    assert oc.count_requests([old], card="001")["requests"] == 1


def test_stop_stays_empty_when_the_upstream_said_none(sandbox: Path) -> None:
    """上游没报就是 `""` —— **不许**写 `"unknown"`/`"none"`/`"-"` 顶替。"""
    path = wd.append_usage_line(card="001", model="m", attempt=1, started_at=None,
                                usage=dict(_USAGE), code=0, reason="")
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    assert row[oc.OUTCOME_STOP] == "", row
    assert row[oc.OUTCOME_STOP] not in ("unknown", "none", "-"), row
    assert oc.request_of([row], card="001")[0].stop == "", "读出来也得是空串"


def test_tier_served_is_never_inferred_from_tier_sent() -> None:
    """只给了 `tier_sent` ⇒ `tier_served` 仍是 `""`（绝不从 asked/sent 推）。"""
    asked = oc.request_of([_row(tier_asked="priority")], card="001")[0]
    sent = oc.request_of([_row(tier_sent="flex")], card="001")[0]
    served = oc.request_of([_row(tier_served="standard")], card="001")[0]
    assert served.tier_served == "standard"
    assert asked.tier_served == "", asked
    assert sent.tier_served == "", sent
    assert sent.tier_asked == "" and sent.tier_sent == "flex", "三列各自独立"


# ============================================ 失败判据（钉子 8）


def test_is_failed_uses_the_exit_code_not_the_verdict_text() -> None:
    """★ 咬「pool 不许照抄 Go 的 `code >= 400 or reason != ""`」：正常收工写的就是非空串。"""
    assert oc.is_failed(0, "正常收工") is False, "正常收工是非空串，但它不是失败"
    assert oc.is_failed(0, "") is False
    assert oc.is_failed(1, "") is True, "`code >= 400` 会漏掉 code=1 这种失败"
    assert oc.is_failed(6, "卡死：8 分钟没有新事件") is True
    assert oc.is_failed(4, "工人非零退出") is True
    assert oc.is_failed(0, "预算用尽：止损") is True, "退出码 0 但判决不是正常收工 ⇒ 算一笔"


# ============================================ 写侧：老键 / 老调用点（钉子 9-10）


def test_append_usage_line_keeps_the_eleven_old_keys(sandbox: Path) -> None:
    """老 11 个键**一个不少**、类型不变；新三列另算。"""
    path = wd.append_usage_line(card="001", model="m", attempt=2, started_at=None,
                                usage=dict(_USAGE), code=0, reason="正常收工",
                                tries=3, handed_on=False, stop="")
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    for key in OLD_KEYS:
        assert key in row, f"老键丢了：{key}"
    assert row["卡"] == "001" and row["模型"] == "m" and row["轮次"] == 2
    assert isinstance(row["开始"], str) and isinstance(row["结束"], str)
    assert isinstance(row["用时分钟"], float)
    for key in ("input_tokens", "output_tokens", "cache_read", "退出码"):
        assert isinstance(row[key], int), key
    assert row["input_tokens"] == 10 and row["output_tokens"] == 2 and row["cache_read"] == 3
    assert row["判决"] == "正常收工"
    assert set(row) == set(OLD_KEYS) | set(NEW_KEYS), "不许再冒别的键出来"


def test_append_usage_line_defaults_leave_old_callers_identical(sandbox: Path,
                                                               monkeypatch) -> None:
    """不传三个新参数 ⇒ 落盘行**除新增键外**与改造前逐字节相同（老调用点一行不用改）。"""
    monkeypatch.setattr(wd.time, "time", lambda: 1_700_000_000.0)
    path = wd.append_usage_line(card="001", model="m", attempt=1, started_at=None,
                                usage=dict(_USAGE), code=0, reason="")
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    assert row == {
        "卡": "001", "模型": "m", "轮次": 1,
        "开始": wd._iso_local(1_700_000_000.0), "结束": wd._iso_local(1_700_000_000.0),
        "用时分钟": 0.0,
        "input_tokens": 10, "output_tokens": 2, "cache_read": 3,
        "退出码": 0, "判决": "正常收工",
        "tries": 1, "handed_on": False, "stop": "",
    }, row


# ============================================ 展示 / 不混口径（钉子 11-12）


def test_usage_summary_still_says_rounds_not_requests(sandbox: Path) -> None:
    """「本卡 N 轮」说的是**轮**，一个字不改；按请求那一行是**另加**的一行。"""
    diag = sandbox / "gates" / "diag"
    diag.mkdir(parents=True, exist_ok=True)
    rows = [_row(round_no=1, code=6, reason="卡死", handed_on=True, tries=1),
            _row(round_no=2, code=0, reason="正常收工", tries=2)]
    (diag / "wb-usage.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    said = wd.usage_summary("001")
    assert "本卡 2 轮" in said, said
    assert "本卡 2 请求" not in said and "本卡 2 次请求" not in said, said
    assert "请求 1 / 失败 0 / 重试答上 1" in said, said
    assert "累计（所有卡）" in said, said


def test_count_requests_does_not_double_count_tokens() -> None:
    """函数**不返回** token（token 归 `ledger_spend.sums()`）—— 两条口径不许混。"""
    got = oc.count_requests([_row(code=0, reason="正常收工", tries=2)], card="001")
    assert set(got) == set(oc.COUNT_KEYS), got
    assert set(got) == {"requests", "errors", "retried", "handed_on"}
    for leaked in ("input_tokens", "output_tokens", "cache_read", "tokens", "cost", "calls"):
        assert leaked not in got, f"计数里混进了 token / 金额 / 轮数：{leaked}"


# ============================================ 判据只有一份（钉子 13）


def test_should_resume_is_called_once_per_round(sandbox: Path, monkeypatch,
                                                capsys) -> None:
    """★ 咬接入点 2：写行前算**一次**、续跑判断复用同一份 —— 每轮只许调一次。"""
    calls: list[list[str]] = []
    seen: list[tuple[str, int, int]] = []
    real = wd.should_resume

    def counting(reason: str, attempts_done: int, retries: int) -> bool:
        seen.append((reason, attempts_done, retries))
        return real(reason, attempts_done, retries)

    monkeypatch.setattr(wd, "should_resume", counting)
    monkeypatch.setattr(wd, "run_worker",
                        _runner(["卡死：8.0 分钟没有新事件 → 已掐", ""], calls))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute"])
    assert wd.main() == 0
    capsys.readouterr()
    assert len(calls) == 2, "被掐一次 ⇒ 应当续跑一次"
    assert len(seen) == len(calls), f"每轮只许算一次续跑结论，实际 {len(seen)} 次：{seen}"
    rows = _usage_rows(sandbox)
    assert [r["handed_on"] for r in rows] == [True, False], rows
    assert [r["tries"] for r in rows] == [1, 2], rows
