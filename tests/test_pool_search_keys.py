"""搜索 API 的多 key 轮换与各自 rest（卡 A372 · F56）—— 判据 2 / 3 / 4 / 5 逐条钉。

卡规格：`复盘/卡/卡A372-F56搜索API多key轮换-被拒才换下一个与各自rest.md`。
寿命判据（11 个 rest 真值）在 `tools/pool_quota.py`，分类七值在 `pool/gateway.classify`，
轮转在 `pool/route.rotate` —— 本文件只钉「搜索这条路把它们接对了」。

| 钉子 | 钉哪一位 |
|---|---|
| `test_two_keys_of_one_model_do_not_overwrite_each_other` | 判据 2(a)：同 model 两个 key 两条记录 |
| `test_plaintext_key_never_reaches_the_disk` | 判据 2(b)：落盘字节里查不到 key 明文 |
| `test_old_record_signature_still_behaves_the_same` | 判据 2(c)：旧签名 `record(...)` 行为不变 |
| `test_search_rest_table` | 判据 3：8 行表 —— 401/403/402/限流四档/tavily-433 |
| `test_four_truths_are_untouched` | 判据 3：旧路径 credit=1800、auth=60 起指数，一个数不改 |
| `test_search_path_stops_at_the_first_non_refusal` | 判据 4(a)：搜索首 key 500 ⇒ attempts 长 1 |
| `test_chat_path_still_walks_to_the_next_seat_on_500` | 判据 4(b)：聊天同 500 ⇒ attempts 长 2 |
| `test_mask_search_key` | 判据 5：`tvly-` 够长 ⇒ `tvly-…`+后 4 位，其余退回 `mask()` |
| `test_key_label_carries_no_plaintext` | 判据 5：标签里只有打码值 |
| `test_search_module_holds_no_numbers_and_no_hash` | 判据 6(b)(c)：无哈希、无 rest 秒数 |
| `test_vendor_table_is_readable_and_holds_no_rest_numbers` | 判据 6：vendor 表四个、无秒数 |

★ 全部走 tmp（`root=tmp_path`），不碰仓外的 `accounts.toml`，也不往真的 `gates/diag/` 写。
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pool_accounts  # noqa: E402
import pool_quota  # noqa: E402
from pool import gateway  # noqa: E402
from pool import search as pool_search  # noqa: E402

NOW = "2026-11-09T12:00:00+00:00"
NOW_DT = dt.datetime(2026, 11, 9, 12, 0, 0, tzinfo=dt.timezone.utc)
MODEL = "huaweicloud-maas/GLM-5.2"
SEAT_A = "codearts-1"
SEAT_B = "workbuddy-1"
CHAT_URL = "https://chat.example.test/v1/chat/completions"
SEARCH_URL = "https://search.example.test/search"
#: 两把「可识别」的假 key：20 位身子都是大写/数字混排，落盘里出现就是泄漏。
KEY_A = "tvly-" + "0123456789abcdefghij"
KEY_B = "tvly-" + "ZYXWVUTSRQPONMLKJIHG"


# ---------------------------------------------------------------- 夹具（号池目录）


def _pool_dir(root: Path) -> Path:
    """在 `root` 下造一个号池目录（锚点 + 批准集 + 快照）。**只写 tmp**。"""
    pool = root / "infra" / "pool"
    pool.mkdir(parents=True, exist_ok=True)
    (pool / "pool_models.py").write_text("", encoding="utf-8")
    (pool / "models.whitelist.toml").write_text(
        f'[[approved]]\npool = "codebuddy"\nmodel = "{MODEL}"\n', encoding="utf-8")
    snap = {"live": [MODEL], "live_names": {}, "at": ""}
    (pool / "models.live.json").write_text(json.dumps(snap), encoding="utf-8")
    return pool


def _row(seat: str) -> dict[str, Any]:
    return {"id": seat, "label": seat, "platform": "codearts", "state": "active",
            "approved_models": [MODEL]}


class _Forward:
    """按下标依次回预设答复；记下每次调用。**一个字节都不出网。**"""

    def __init__(self, *replies: gateway.Reply) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, str, str, bytes]] = []

    def __call__(self, model: str, account: str, url: str, payload: bytes) -> gateway.Reply:
        self.calls.append((model, account, url, payload))
        index = min(len(self.calls) - 1, len(self.replies) - 1)
        return self.replies[index]


def _ok() -> gateway.Reply:
    return gateway.Reply(status=200, headers={"Content-Type": "application/json"},
                         body=b'{"ok":true}')


def _boom(status: int) -> gateway.Reply:
    body = json.dumps({"error": {"message": f"upstream {status}"}}).encode("utf-8")
    return gateway.Reply(status=status, headers={"Content-Type": "application/json"}, body=body)


def _route(env: Path, forward: _Forward, *, protocol: str, rows: tuple[dict[str, Any], ...],
           endpoints: dict[str, list[str]]) -> gateway.Outcome:
    return gateway.route_once(
        pool="codebuddy", model=MODEL, caller="alice", forward=forward, protocol=protocol,
        body=b'{"q":"x"}', now=NOW_DT, root=env, endpoints=endpoints,
        rpm_limits={}, stamps={}, ledger={"account": [dict(r) for r in rows]}, scopes={})


# ==================================================== 判据 2：每个 key 一条 rest，互不覆盖


def test_two_keys_of_one_model_do_not_overwrite_each_other(tmp_path: Path) -> None:
    """判据 2(a)：同 model 两把不同 key ⇒ 两条记录（旧表 `cards[card][model]` 会互相覆盖）。"""
    wanted = set()
    for key in (KEY_A, KEY_B):
        key_id = pool_quota.search_key_id("tavily", key)
        wanted.add(key_id)
        pool_quota.record(card="gw:alice", model=MODEL, pool="codebuddy", kind="余额耗尽",
                          reset_raw="", vendor="tavily", key_id=key_id,
                          rest=pool_search.rest_for(vendor="tavily", status=402, now=NOW),
                          root=tmp_path)
    records = pool_quota.read_search_records(MODEL, root=tmp_path)
    assert len(records) == 2, records
    assert {r["key_id"] for r in records} == wanted
    assert {r["vendor"] for r in records} == {"tavily"}
    assert all(r["rest"]["by"] == "out-of-credit" for r in records)
    # 旧那一格照旧存在（两条都写了 card/model，最后一条赢 —— 它本来就是这个语义）
    assert pool_quota.read_record("gw:alice", MODEL, root=tmp_path) is not None


def test_plaintext_key_never_reaches_the_disk(tmp_path: Path) -> None:
    """判据 2(b)：落盘字节里查不到 key 明文（连 20 位身子都不许整段出现）。"""
    for key in (KEY_A, KEY_B):
        pool_quota.record(card="gw:alice", model=MODEL, pool="codebuddy", kind="余额耗尽",
                          reset_raw="", vendor="tavily",
                          key_id=pool_quota.search_key_id("tavily", key),
                          rest=pool_search.rest_for(vendor="tavily", status=403, now=NOW),
                          root=tmp_path)
    state = tmp_path / "gates" / "diag" / "quota-state.json"
    blob = state.read_bytes()
    for key in (KEY_A, KEY_B):
        assert key.encode("utf-8") not in blob, "整把 key 落盘了"
        assert key[len("tvly-"):].encode("utf-8") not in blob, "key 的身子落盘了"
    text = blob.decode("utf-8")
    assert pool_quota.search_key_id("tavily", KEY_A) in text, "身份得在（否则读不回来）"


def test_old_record_signature_still_behaves_the_same(tmp_path: Path) -> None:
    """判据 2(c)：旧签名 `record(card, model, pool, kind, reset_raw)` 一个参数不多传。"""
    rec = pool_quota.record(card="A332", model="deepseek-v4.1-flash", pool="p",
                            kind="限流", reset_raw="", root=tmp_path)
    assert set(rec) == {"card", "model", "pool", "kind", "reset_raw", "reset_at",
                        "recorded_at", "source_log", "source_line"}, sorted(rec)
    data = json.loads((tmp_path / "gates" / "diag" / "quota-state.json")
                      .read_text(encoding="utf-8"))
    assert data["cards"]["A332"]["deepseek-v4.1-flash"] == rec
    assert "search" not in data, "旧调用不许顺手造出一张搜索表"


# ==================================================== 判据 3：搜索档的八个读数


@pytest.mark.parametrize(("status", "retry_after_s", "seconds", "by"), [
    (401, None, 600, "turned-away"),
    (403, None, 600, "turned-away"),
    (402, None, 3600, "out-of-credit"),
    (429, 10, 30, "rate-limited"),
    (429, 90, 90, "rate-limited"),
    (429, 3600, 600, "rate-limited"),
    (429, None, 60, "rate-limited"),
    (433, None, 3600, "out-of-credit"),
])
def test_search_rest_table(status: int, retry_after_s: int | None,
                           seconds: int, by: str) -> None:
    """判据 3：magpie `searchRestFor` 的八行读数（表挪一格这里就红）。"""
    got = pool_search.rest_for(vendor="tavily", status=status,
                               retry_after_s=retry_after_s, now=NOW)
    assert got["seconds"] == seconds, got
    assert got["by"] == by, got


def test_four_truths_are_untouched() -> None:
    """判据 3：既有四真值一个数不改 —— credit 仍 30 分钟、auth 仍 60 起指数。"""
    credit = pool_quota.rest_after(why="credit", status=429, reset_at=None, now=NOW)
    assert (credit["seconds"], credit["by"]) == (1800, "credit")
    auth = pool_quota.rest_after(why="auth", status=401, reset_at=None, now=NOW)
    assert (auth["seconds"], auth["by"]) == (60, "backoff")
    twice = pool_quota.rest_after(why="auth", status=401, reset_at=None, failures=2, now=NOW)
    assert twice["seconds"] == 120
    # 搜索档是**另一条路**：不给 search_vendor 时一次都不许走它
    plain = pool_quota.rest_after(why="rate", status=429, reset_at=None, now=NOW)
    assert (plain["seconds"], plain["by"]) == (60, "cooldown")


# ==================================================== 判据 4：只有被拒才换下一个 key


def test_search_path_stops_at_the_first_non_refusal(tmp_path: Path) -> None:
    """判据 4(a)：搜索路径第一把 key 回 500 ⇒ attempts 长 1、forward 只调一次。"""
    env = tmp_path
    _pool_dir(env)
    forward = _Forward(_boom(500), _ok())
    out = _route(env, forward, protocol=gateway.PROTOCOL_SEARCH,
                 rows=(_row(SEAT_A), _row(SEAT_B)),
                 endpoints={"codearts": [SEARCH_URL]})
    assert len(out.attempts) == 1, out.attempts
    assert len(forward.calls) == 1, forward.calls
    assert out.status == 500, "上游的 500 原样透传，不许改写成 502"
    assert out.stop_reason, "走的是哪一档要读得出来（判据 4 的「可读地记下来」）"
    assert "不是拒绝类" in out.stop_reason, out.stop_reason


def test_search_path_switches_key_on_a_refusal(tmp_path: Path) -> None:
    """判据 4 的正面：429 是拒绝类 ⇒ 换下一把 key（不是就地结束）。"""
    env = tmp_path
    _pool_dir(env)
    forward = _Forward(_boom(429), _ok())
    out = _route(env, forward, protocol=gateway.PROTOCOL_SEARCH,
                 rows=(_row(SEAT_A), _row(SEAT_B)),
                 endpoints={"codearts": [SEARCH_URL]})
    assert len(out.attempts) == 2, out.attempts
    assert len(forward.calls) == 2
    assert out.status == 200
    assert out.stop_reason == "", "答上了就没有「为什么停」"


def test_chat_path_still_walks_to_the_next_seat_on_500(tmp_path: Path) -> None:
    """判据 4(b)：聊天路径同一个 500 ⇒ attempts 长 2（裁决 1：这里一个字节不动）。"""
    env = tmp_path
    _pool_dir(env)
    forward = _Forward(_boom(500), _boom(500))
    out = _route(env, forward, protocol=gateway.PROTOCOL_CHAT,
                 rows=(_row(SEAT_A), _row(SEAT_B)),
                 endpoints={"codearts": [CHAT_URL]})
    assert len(out.attempts) == 2, out.attempts
    assert len(forward.calls) == 2
    assert out.stop_reason == "", "聊天路径没有 stop_reason 这一档"


def test_not_refused_status_gets_no_rest() -> None:
    """判据 4 的另一半：非拒绝类不换 key，也就不该有 rest（`by="not-refused"`）。"""
    got = pool_search.rest_for(vendor="tavily", status=500, now=NOW)
    assert (got["seconds"], got["by"]) == (0, "not-refused"), got
    assert pool_search.refused(500) is False
    assert pool_search.refused(429) is True
    assert pool_search.refused(433) is True, "六个拒绝码是全局闭集（跟哪家无关）"
    # 分家的只有 rest 的档位：433 只有 tavily 算「没钱了」，别家按限流算
    tavily = pool_search.rest_for(vendor="tavily", status=433, now=NOW)
    brave = pool_search.rest_for(vendor="brave", status=433, now=NOW)
    assert (tavily["seconds"], tavily["by"]) == (3600, "out-of-credit"), tavily
    assert (brave["seconds"], brave["by"]) == (60, "rate-limited"), brave


# ==================================================== 判据 5：打码（tvly- + 后 4 位）


@pytest.mark.parametrize(("raw", "want"), [
    ("tvly-abcdefghijklmnop", "tvly-…mnop"),
    ("tvly-short", "tvly-short"),
    ("sk-abcdefgh12345678", "***"),
])
def test_mask_search_key(raw: str, want: str) -> None:
    """判据 5：`tvly-` 且够长 ⇒ `tvly-…`+后 4 位；其余退回既有 `mask()`。"""
    assert pool_accounts.mask_search_key(raw) == want


def test_mask_search_key_is_not_a_second_mask() -> None:
    """判据 5 的边界：既有 `mask()` / `mask_token()` 的行为一个字节不改。"""
    assert pool_accounts.mask("sk-abcdefgh12345678") == "***"
    assert pool_accounts.mask("tvly-abcdefghijklmnop") == "tvly-abcdefghijklmnop", \
        "既有 mask() 认不出 tvly-（本卡不改它）"
    assert pool_accounts.mask_token("a.b.c") == "a.b…"


def test_key_label_carries_no_plaintext() -> None:
    """判据 5：标签里只有打码值 —— 错误串也得能直接给人看。"""
    label = pool_search.key_label(1, "tvly-abcdefghijklmnop")
    assert label == "key 2 (tvly-…mnop)"
    assert "abcdefghijklmnop" not in label


# ==================================================== 判据 6：本模块里没有第二份数字/哈希


def test_search_module_holds_no_numbers_and_no_hash() -> None:
    """判据 6(b)(c)：`search.py` 里不许有 key 哈希，也不许有 rest 秒数。"""
    src = (ROOT / "tools" / "pool" / "search.py").read_text(encoding="utf-8")
    for token in ("sha256", "hexdigest", "600", "3600", "1800"):
        assert token not in src, f"search.py 里出现了 {token!r}"


def test_vendor_table_is_readable_and_holds_no_rest_numbers() -> None:
    """判据 6：vendor 表四个、能读，且里面一个 rest 秒数都没有。"""
    table = pool_search.load_vendors()
    assert sorted(table) == ["brave", "searxng", "serper", "tavily"], sorted(table)
    assert table["tavily"].out_of_credit == (432, 433)
    assert table["searxng"].key_required is False
    raw = (ROOT / "tools" / "pool" / "search-vendors.toml").read_text(encoding="utf-8")
    for token in ("600", "3600", "1800"):
        assert token not in raw, f"vendor 表里出现了 {token!r}"


def test_order_rotates_and_keeps_resting_keys_last(tmp_path: Path) -> None:
    """轮转与 resting 都走 `route.rotate`：resting 的排后但**不丢弃**。"""
    keys = [KEY_A, KEY_B, "tvly-cccccccccccccccc"]
    turns: dict[str, int] = {}
    assert pool_search.order(keys, pool="tavily", turns=turns) == [0, 1, 2]
    assert pool_search.order(keys, pool="tavily", turns=turns) == [1, 2, 0]
    resting = pool_search.order(keys, pool="tavily", turns={}, resting=[True, False, False])
    assert resting == [1, 2, 0], "休息的排最后，但还在列表里"

