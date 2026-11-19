r"""号池网关（`tools/pool/gateway.py`，卡 E94 · T-AG603）的测试 —— 六条判据逐条钉。

判据表见 `复盘/卡/卡E94-号池网关同协议直通.md`；这里只写**会失败**的断言。

| 钉子 | 钉哪一位 |
|---|---|
| `test_classify_status_table` | 七值表逐格：429/402/401/403/413/5xx/4xx/其它 |
| `test_classify_structured_quota_wins_over_status` | 结构化 insufficient_quota 比状态码更具体 |
| `test_classify_ignores_free_text` | 正文写「余额不足」/quota 字样**不算数**（不解析文案） |
| `test_classify_is_pure` | 同输入同输出、不读环境变量、不写盘 |
| `test_retry_after_zero_is_a_legal_value` | `Retry-After: 0` 合法（判空必须 `is not None`） |
| `test_platform_table_chat_urls_all_empty` | 九平台各有一列 `chat_urls`，且全空 |
| `test_empty_chat_urls_is_403_and_named` | 空 `chat_urls` ⇒ 403 + 点名没登记 chat 端点 |
| `test_pick_endpoint_never_guesses_from_base_url` | 不许拿 base_url 猜端点；协议不符也不算 |
| `test_dry_run_walks_the_whole_chain` | 干跑：候选 → 跳过 → 循环 → 落账，一个字节不出网 |
| `test_429_switches_seat_and_sinks` | 429 ⇒ 沉底 + 换下一个号 |
| `test_sunk_seat_is_skipped_without_trying` | 沉底中的号**不试** |
| `test_rpm_blocked_seat_is_skipped` | 每分钟闸拒 ⇒ 跳过 |
| `test_narrowed_out_is_403_not_502` | 收窄挡 ⇒ 403 且点名收窄，不叫「挂了」 |
| `test_unapproved_model_is_404_not_429` | 未批模型 ⇒ 404（不回 429） |
| `test_empty_tried_does_not_log` | ★ tried 为空**不落记录** |
| `test_route_log_records_gw_card_and_real_order` | `card=f"gw:{caller}"`，`tried` 是真实次序 |
| `test_order_uses_apply_order_and_survives_bad_permutation` | 排序走 apply_order：坏排列回恒等 |
| `test_check_host_* `/`test_build_server_requires_token` | 只绑回环、没有 token 不建服务 |
| `test_bearer_ok_uses_compare_digest` | 常量时间比较（AST 钉） |
| `test_streaming_upstream_non_stream_caller_is_400` | 上游只流式 + 调用方非流式 ⇒ 400（不攒流） |
| `test_streaming_is_forwarded_byte_for_byte` | SSE 逐字节转发、不解析、不改写 |
| `test_chat_path_never_uses_messages_endpoint` | 只做同协议直通 |
| `test_f36_*`（六条） | F36：集合恰三值、路径恰四键、Host 与转发头不改答复、`null` 仍 403 |

★ 全部用桩：`forward` 是注入的，`ledger` / `endpoints` / `rpm_limits` / `stamps` 都是参数，
  号池目录造在 `tmp_path` 里 —— **一个字节都不出网**，也不往真的 `gates/diag/` 写。
"""

from __future__ import annotations

import ast
import datetime as dt
import http.client
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from pool import (  # noqa: E402
    accounts_scope,
    gateway,  # tools/ 已在 sys.path 上
)
from pool import model_registry as pool_model_registry  # noqa: E402
from pool import route as pool_route  # noqa: E402
from pool import sink as pool_sink  # noqa: E402
from pool.no_window import NO_WINDOW  # noqa: E402 —— 起子进程必须带（卡 148）

TOKEN = "gateway-unit-token"
MODEL = "huaweicloud-maas/GLM-5.2"
CHAT_URL = "https://chat.example.test/v1/chat/completions"
MSG_URL = "https://chat.example.test/v1/messages"
SEAT_A = "codearts-1"
SEAT_B = "workbuddy-1"
NOW = dt.datetime(2026, 11, 9, 12, 0, 0, tzinfo=dt.timezone.utc)


# ---------------------------------------------------------------- 夹具


def _pool_dir(root: Path, *, approved: tuple[str, ...] = (MODEL,), stale_at: str = "") -> Path:
    """在 `root` 下造一个号池目录（锚点 + 批准集 + 快照）。**只写 tmp，不碰仓外那份。**"""
    pool = root / "infra" / "pool"
    pool.mkdir(parents=True, exist_ok=True)
    (pool / "pool_models.py").write_text("", encoding="utf-8")
    body = "".join(
        f'[[approved]]\npool = "codebuddy"\nmodel = "{name}"\n' for name in approved)
    (pool / "models.whitelist.toml").write_text(body, encoding="utf-8")
    snap = {"live": list(approved), "live_names": {}, "at": stale_at}
    (pool / "models.live.json").write_text(json.dumps(snap), encoding="utf-8")
    return pool


def _row(seat: str, *, platform: str = "codearts", state: str = "active",
         models: tuple[str, ...] = (MODEL,)) -> dict[str, Any]:
    return {"id": seat, "label": seat, "platform": platform, "state": state,
            "approved_models": list(models)}


@pytest.fixture()
def env(tmp_path: Path) -> Path:
    """号池目录 + 账本行 + 端点表；一律指到 tmp，不碰真仓外账本。"""
    _pool_dir(tmp_path)
    return tmp_path


def _ledger(*rows: dict[str, Any]) -> dict[str, Any]:
    return {"account": [dict(row) for row in rows]}


class _Forward:
    """按下标依次回预设答复；记下每次调用（模型、号、URL、payload）。"""

    def __init__(self, *replies: gateway.Reply) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, str, str, bytes]] = []

    def __call__(self, model: str, account: str, url: str, payload: bytes) -> gateway.Reply:
        self.calls.append((model, account, url, payload))
        index = min(len(self.calls) - 1, len(self.replies) - 1)
        return self.replies[index]


def _ok(body: bytes = b'{"ok":true}') -> gateway.Reply:
    return gateway.Reply(status=200, headers={"Content-Type": "application/json"}, body=body)


def _run(env: Path, forward: Any, *, model: str = MODEL, caller: str = "alice",
         protocol: str = gateway.PROTOCOL_CHAT, rows: tuple[dict[str, Any], ...] | None = None,
         endpoints: dict[str, list[str]] | None = None,
         **extra: Any) -> gateway.Outcome:
    table = endpoints if endpoints is not None else {"codearts": [CHAT_URL, MSG_URL],
                                                     "workbuddy": [CHAT_URL, MSG_URL]}
    return gateway.route_once(
        pool="codebuddy", model=model, caller=caller, forward=forward, protocol=protocol,
        body=b'{"model":"x"}', now=NOW, root=env,
        endpoints=table, rpm_limits={}, stamps={},
        ledger=_ledger(*(rows if rows is not None else (_row(SEAT_A),))),
        scopes={}, **extra)


def _route_log(env: Path) -> list[dict[str, Any]]:
    path = env / "gates" / "diag" / "wb-route.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


# ================================================================ 判据 1：失败分类只有一份


def test_kind_vocabulary_is_seven_values() -> None:
    """七值闭集 —— 第八个值不许发明（卡 E94 判据 1）。"""
    assert gateway.KINDS == ("rate", "quota", "auth", "overflow", "server", "bad_request", "other")
    assert len(set(gateway.KINDS)) == 7


@pytest.mark.parametrize(("status", "kind"), [
    (429, "rate"),
    (402, "quota"),
    (401, "auth"),
    (403, "auth"),
    (413, "overflow"),
    (500, "server"),
    (503, "server"),
    (400, "bad_request"),
    (404, "bad_request"),
    (422, "bad_request"),
    (200, "other"),
    (302, "other"),
])
def test_classify_status_table(status: int, kind: str) -> None:
    """一次上游失败按状态码落格；表挪一格这里就红。"""
    assert gateway.classify(status) == kind
    assert gateway.classify(status, b'{"error":{"message":"boom"}}') == kind


@pytest.mark.parametrize(("field", "value"), [
    ("type", "insufficient_quota"), ("code", "insufficient_quota"),
    ("code", "quota_exceeded"), ("type", "insufficient_balance"),
])
def test_classify_structured_quota_wins_over_status(field: str, value: str) -> None:
    """结构化字段说「余额没了」比状态码更具体：429 + insufficient_quota ⇒ quota。"""
    body = json.dumps({"error": {"message": "whatever", field: value}}).encode("utf-8")
    assert gateway.classify(429, body) == "quota"
    assert gateway.classify(400, body) == "quota"
    assert gateway.classify(402, {"error": {"message": "x"}}) == "quota"


@pytest.mark.parametrize("body", [
    "余额不足，请充值".encode(),
    b'{"error":{"message":"insufficient_quota"}}',
    b'{"error":{"message":"rate limit exceeded, please retry"}}',
    b'{"detail":"\xe4\xbd\x99\xe9\xa2\x9d\xe7\x94\xa8\xe5\xae\x8c\xe4\xba\x86"}',
    b"quota exceeded",
    b"",
])
def test_classify_ignores_free_text(body: bytes) -> None:
    """★ 绝不解析自由文案：措辞里写着 quota / 余额不足也**只按状态码**判。"""
    assert gateway.classify(400, body) == "bad_request"
    assert gateway.classify(503, body) == "server"
    assert gateway.classify(429, body) == "rate"


def test_classify_is_pure(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """纯函数：同输入同输出、不读环境变量、不写盘（两次调用之间什么都不变）。"""
    marker = env / "must-not-exist"
    monkeypatch.setenv("TF_POOL_GATEWAY_TOKEN", "changed")
    first = gateway.classify(402, b'{"error":{"code":"insufficient_quota"}}')
    monkeypatch.setenv("TF_POOL_GATEWAY_TOKEN", "")
    monkeypatch.setenv("TF_POOL_SINK", str(marker))
    second = gateway.classify(402, b'{"error":{"code":"insufficient_quota"}}')
    assert first == second == "quota"
    assert not marker.exists(), "classify 不许写盘"
    assert not (env / "gates").exists(), "classify 一次 IO 都不该有"


def test_classify_rejects_non_status() -> None:
    """status 必须是整数 —— 形状变了就炸，不猜。"""
    for bad in (None, "429", 4.29, True):
        with pytest.raises(TypeError):
            gateway.classify(bad)  # type: ignore[arg-type]


def test_retry_after_zero_is_a_legal_value() -> None:
    """★ `Retry-After: 0` 是**合法值**（判空必须 `is not None`，不能 `if retry`）。"""
    assert gateway.parse_retry_after("0", now=NOW) == NOW
    assert gateway.parse_retry_after("7", now=NOW) == NOW + dt.timedelta(seconds=7)
    assert gateway.parse_retry_after(None, now=NOW) is None
    assert gateway.parse_retry_after("", now=NOW) is None
    assert gateway.parse_retry_after("not-a-date", now=NOW) is None


# ================================================================ 判据 2：端点先立接口不编造


def test_platform_table_chat_urls_all_empty() -> None:
    """九平台各有一列 `chat_urls`，且**全空**（空 = 没登记，不是不支持）。"""
    import tomllib

    text = (ROOT / "tools" / "pool" / "platforms.toml").read_text(encoding="utf-8")
    data = tomllib.loads(text)
    platforms = data["platform"]
    assert len(platforms) == 9, sorted(platforms)
    for name, row in platforms.items():
        assert "chat_urls" in row, name
        assert row["chat_urls"] == [], name
    assert "空 = 没登记，不是不支持" in text, "文件头要说清「空」是什么意思"


def test_empty_chat_urls_is_403_and_named(env: Path) -> None:
    """★ 平台没登记 chat 端点 ⇒ 403 + **点名**；不许伪造成功。"""
    forward = _Forward(_ok())
    outcome = _run(env, forward, endpoints={"codearts": []})
    assert outcome.status == 403
    assert forward.calls == [], "端点没登记就一个字节都不许发"
    text = outcome.body.decode("utf-8")
    assert "这个平台没登记 chat 端点" in text
    assert "codearts" in text


def test_pick_endpoint_never_guesses_from_base_url() -> None:
    """空表 / 只有站点根 / 协议不符 ⇒ 一律挑不到，**不许试着拼一个**。"""
    url, why = gateway.pick_endpoint((), "chat", platform="codearts")
    assert url is None and "没登记 chat 端点" in why
    url, why = gateway.pick_endpoint(("https://api.example.test",), "chat", platform="codearts")
    assert url is None and "不做协议翻译" in why
    url, why = gateway.pick_endpoint((MSG_URL,), "chat", platform="codearts")
    assert url is None and "不做协议翻译" in why
    assert gateway.pick_endpoint((CHAT_URL,), "chat", platform="codearts") == (CHAT_URL, "")
    assert gateway.endpoint_protocol(MSG_URL) == "messages"
    assert gateway.endpoint_protocol("https://x.test/v1/responses") == ""


# ================================================================ 判据 3：干跑能整段走完


def test_dry_run_walks_the_whole_chain(env: Path) -> None:
    """完整一条：候选 → 逐条闸 → 循环 → 有答案 → 落账。**不出网。**"""
    forward = _Forward(_ok())
    outcome = _run(env, forward)
    assert outcome.status == 200
    assert outcome.body == b'{"ok":true}'
    assert len(forward.calls) == 1
    assert forward.calls[0][2] == CHAT_URL, "客户端说 Chat ⇒ 只往 Chat 端点发"
    rows = _route_log(env)
    assert len(rows) == 1
    assert rows[0]["card"] == "gw:alice"
    assert rows[0]["status"] == "served"
    assert rows[0]["asked"] == MODEL
    assert rows[0]["served"] == f"{SEAT_A}/{MODEL}"
    assert outcome.attempts and outcome.attempts[0].kind is None


def test_429_switches_seat_and_sinks(env: Path) -> None:
    """429 ⇒ 沉底这个 (号, 模型) + 换下一个号；`tried` 记真实次序。"""
    forward = _Forward(
        gateway.Reply(status=429, headers={"Retry-After": "0"}, body=b'{"error":{}}'), _ok())
    outcome = _run(env, forward, rows=(_row(SEAT_A), _row(SEAT_B)))
    assert outcome.status == 200
    assert [call[1] for call in forward.calls] == [SEAT_A, SEAT_B]
    assert pool_sink.sunk_at(pool_sink.key_of(SEAT_A, MODEL), root=env) is not None
    assert pool_sink.sunk_at(pool_sink.key_of(SEAT_B, MODEL), root=env) is None
    rows = _route_log(env)
    assert [item["model"] for item in rows[0]["tried"]] == [MODEL, MODEL]
    assert rows[0]["tried"][0]["fail"].startswith(SEAT_A), "失败原因要点名是哪个号"
    assert rows[0]["served"] == f"{SEAT_B}/{MODEL}"


def test_sunk_seat_is_skipped_without_trying(env: Path) -> None:
    """沉底中的号**不试**（一个字节都不发给它）。"""
    pool_sink.sink(pool_sink.key_of(SEAT_A, MODEL), root=env)
    forward = _Forward(_ok())
    outcome = _run(env, forward, rows=(_row(SEAT_A), _row(SEAT_B)))
    assert outcome.status == 200
    assert [call[1] for call in forward.calls] == [SEAT_B]


def test_rpm_blocked_seat_is_skipped(env: Path) -> None:
    """每分钟闸拒 ⇒ 跳过这个号（换下一个，不是整轮失败）。"""
    forward = _Forward(_ok())
    outcome = gateway.route_once(
        pool="codebuddy", model=MODEL, caller="alice", forward=forward, body=b"{}",
        now=NOW, root=env, endpoints={"codearts": [CHAT_URL], "workbuddy": [CHAT_URL]},
        rpm_limits={SEAT_A: 1}, stamps={SEAT_A: [NOW]},
        ledger=_ledger(_row(SEAT_A), _row(SEAT_B)), scopes={})
    assert outcome.status == 200
    assert [call[1] for call in forward.calls] == [SEAT_B]


def test_narrowed_out_is_403_not_502(env: Path) -> None:
    """★ 全被收窄挡 ⇒ 403 并点名「收窄」，不叫「挂了」。"""
    scope = accounts_scope.Scope(caller_kind="card", caller_id="alice",
                                 patterns=("codearts/*",))
    forward = _Forward(_ok())
    outcome = gateway.route_once(
        pool="codebuddy", model=MODEL, caller="alice", forward=forward, body=b"{}",
        now=NOW, root=env, endpoints={"codearts": [CHAT_URL]}, rpm_limits={}, stamps={},
        ledger=_ledger(_row(SEAT_A)), scopes={("card", "alice"): scope})
    assert outcome.status == 403
    assert forward.calls == []
    text = outcome.body.decode("utf-8")
    assert "没有可用的号" in text
    assert "判不动它属于哪个 provider" in text, "点名是「收窄」，不是「挂了」"


def test_unapproved_model_is_404_not_429(env: Path) -> None:
    """未批模型 ⇒ 404 + 点名；**不回 429**（回 429 会让调用方白等一个 reset）。"""
    forward = _Forward(_ok())
    outcome = _run(env, forward, model="not-approved/model")
    assert outcome.status == 404
    assert "不在批准集里" in outcome.body.decode("utf-8")
    assert forward.calls == []


def test_stale_snapshot_is_404(env: Path) -> None:
    """快照过期 ⇒ 404 + 点名过期（**不许拿几天前的名单当权威**）。"""
    _pool_dir(env, stale_at="2020-01-01 00:00:00")
    forward = _Forward(_ok())
    outcome = _run(env, forward)
    assert outcome.status == 404
    assert "快照" in outcome.body.decode("utf-8")
    assert forward.calls == []


def test_empty_tried_does_not_log(env: Path) -> None:
    """★ `tried` 为空 ⇒ **不落记录**（append_route 自己不拒，纪律由网关守）。"""
    pool_sink.sink(pool_sink.key_of(SEAT_A, MODEL), root=env)
    forward = _Forward(_ok())
    outcome = _run(env, forward)
    assert forward.calls == []
    assert outcome.attempts == ()
    assert outcome.logged is False
    assert _route_log(env) == [], "一条空记录就是把「不知道」写成「知道」"


def test_log_refuses_to_write_an_empty_tried(env: Path) -> None:
    """★ 第二道闸：`_log` 自己就拒空 `tried`（append_route 会老老实实写一条空记录）。

    只靠 route_once 的出口分支守不够 —— 以后谁加一条新的出口、忘了先判空，
    这条钉子会当场红，而不是悄悄在 wb-route.jsonl 里写一行「什么都没试」。
    """
    assert gateway._log(env, caller="alice", model=MODEL, attempts=[], served="",
                        status="served", started_at=0.0) is False
    assert _route_log(env) == []


def test_route_log_records_gw_card_and_real_order(env: Path) -> None:
    """账落 `gates/diag/wb-route.jsonl`，`card=gw:<caller>`，`tried` 是真实次序，status 在闭集。"""
    forward = _Forward(gateway.Reply(status=500, body=b"{}"), _ok())
    outcome = _run(env, forward, rows=(_row(SEAT_A), _row(SEAT_B)))
    assert outcome.status == 200
    rows = _route_log(env)
    assert len(rows) == 1
    assert rows[0]["card"] == "gw:alice"
    assert rows[0]["status"] in ("served", "all_failed", "stopped", "quota_blocked")
    assert [item["model"] for item in rows[0]["tried"]] == [MODEL, MODEL]
    assert "alice" in rows[0]["card"] and rows[0]["card"].startswith("gw:")
    assert (env / "gates" / "diag" / "wb-route.jsonl").exists()


def test_all_quota_like_is_429_with_retry_after(env: Path) -> None:
    """全 rate/quota 且知道何时回来 ⇒ 429 + `Retry-After`（最早回来的秒数）。"""
    forward = _Forward(
        gateway.Reply(status=429, headers={"Retry-After": "9"}, body=b"{}"),
        gateway.Reply(status=429, headers={"Retry-After": "3"}, body=b"{}"))
    outcome = _run(env, forward, rows=(_row(SEAT_A), _row(SEAT_B)))
    assert outcome.status == 429
    assert outcome.headers.get("Retry-After") == "3", "取最早回来的那个"
    assert len(forward.calls) == 2, "上限 = 候选个数，不重试同一个"


def test_retry_after_zero_reaches_the_caller(env: Path) -> None:
    """`Retry-After: 0` 一路传成 `"0"`（不是被当成「没有」而丢掉）。"""
    forward = _Forward(gateway.Reply(status=429, headers={"Retry-After": "0"}, body=b"{}"))
    outcome = _run(env, forward)
    assert outcome.status == 429
    assert outcome.headers.get("Retry-After") == "0"


def test_bad_request_is_passed_through_not_wrapped(env: Path) -> None:
    """上游 4xx 非额度类 ⇒ 原样透传 status + body（不吞、不包装）。"""
    upstream = b'{"error":{"message":"upstream-says-no"}}'
    forward = _Forward(gateway.Reply(status=422, body=upstream))
    outcome = _run(env, forward, rows=(_row(SEAT_A), _row(SEAT_B)))
    assert outcome.status == 422
    assert outcome.body == upstream
    assert len(forward.calls) == 1, "bad_request 不换号（换号也装不下）"


def test_overflow_is_not_retried_on_another_seat(env: Path) -> None:
    """413 ⇒ 不换号（换号也装不下），原样回 413。"""
    forward = _Forward(gateway.Reply(status=413, body=b'{"error":{"message":"too long"}}'))
    outcome = _run(env, forward, rows=(_row(SEAT_A), _row(SEAT_B)))
    assert outcome.status == 413
    assert len(forward.calls) == 1


def test_auth_failure_switches_without_sinking(env: Path) -> None:
    """401/403 ⇒ 换号，但**不写沉底**（auth 不是限流，沉底会把它永久烧掉）。"""
    forward = _Forward(gateway.Reply(status=401, body=b"{}"), _ok())
    outcome = _run(env, forward, rows=(_row(SEAT_A), _row(SEAT_B)))
    assert outcome.status == 200
    assert pool_sink.sunk_at(pool_sink.key_of(SEAT_A, MODEL), root=env) is None


def test_forward_exception_does_not_kill_the_gateway(env: Path) -> None:
    """forward 抛异常 ⇒ 记一次 502 类失败，继续换下一个号（网关不许被打挂）。"""
    class _Boom:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self, model: str, account: str, url: str, payload: bytes) -> gateway.Reply:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("上游炸了")
            return _ok()

    boom = _Boom()
    outcome = _run(env, boom, rows=(_row(SEAT_A), _row(SEAT_B)))
    assert outcome.status == 200
    assert boom.calls == 2


def test_order_uses_apply_order_and_survives_bad_permutation(
        env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 排序走 `route.apply_strategy`（它末行就是 `route.apply_order`）：
    策略给出坏排列（越界 / 重复 / 负数）时**回恒等、不抛** —— 网关不自己写映射循环。"""
    rows = (_row(SEAT_A), _row(SEAT_B))
    monkeypatch.setattr(pool_route, "ordered", lambda seats: [9, 9, -1])
    assert gateway._order(rows, "order", pool="codebuddy") == [0, 1]
    monkeypatch.setattr(pool_route, "ordered", lambda seats: [1])
    assert gateway._order(rows, "order", pool="codebuddy") == [0, 1]
    monkeypatch.setattr(pool_route, "ordered", lambda seats: ["a", "b"])
    assert gateway._order(rows, "order", pool="codebuddy") == [0, 1]
    monkeypatch.setattr(pool_route, "ordered", lambda seats: None)
    assert gateway._order(rows, "order", pool="codebuddy") == [0, 1]
    monkeypatch.setattr(pool_route, "ordered", lambda seats: [1, 0])
    assert gateway._order(rows, "order", pool="codebuddy") == [1, 0], "好排列照用"


def test_seat_does_not_invent_used_percent() -> None:
    """★ 账本没有 `used_percent` ⇒ Seat 必须 `used is None` + `known is False`。

    真机四个号**都没有** `[account.quota].used_percent`（recon §4.1）。早先这里落 0.0，
    于是「没有读数」被当成「用得最少」排到第一位。网关只管不伪造；怎么排归卡 E95。
    """
    for row in (_row(SEAT_A),
                {**_row(SEAT_A), "quota": {}},
                {**_row(SEAT_A), "quota": {"used_percent": None}},
                {**_row(SEAT_A), "quota": {"used_percent": "12.5"}},
                {**_row(SEAT_A), "quota": {"used_percent": True}},
                {**_row(SEAT_A), "quota": "nonsense"}):
        seat = gateway._seat(row)
        assert seat.used is None, row
        assert seat.known is False, row


def test_seat_keeps_a_real_used_percent() -> None:
    """有读数就照用：`used_percent=12.5` ⇒ `used == 12.5` + `known is True`。"""
    seat = gateway._seat({**_row(SEAT_A), "quota": {"used_percent": 12.5}})
    assert seat.used == 12.5
    assert seat.known is True
    whole = gateway._seat({**_row(SEAT_A), "quota": {"used_percent": 0}})
    assert whole.used == 0.0 and whole.known is True, "真读数 0 与「没有读数」不是一回事"


def test_route_once_swallows_bad_ordering(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """坏排列不许把整轮变成 500：照样把两个候选都试一遍。"""
    monkeypatch.setattr(pool_route, "ordered", lambda seats: [3, 3])
    forward = _Forward(_ok())
    outcome = _run(env, forward, rows=(_row(SEAT_A), _row(SEAT_B)))
    assert outcome.status == 200
    assert len(forward.calls) == 1


# ================================================================ 判据 4：HTTP 面只有四条且默认关


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "::", "*", "", " 10.0.0.1 "])
def test_check_host_rejects_non_loopback(host: str) -> None:
    """★ 只绑回环；文案照 `mcp_http.check_host`（「不绑非回环地址」+ 隧道那句话）。"""
    with pytest.raises(gateway.ConfigError) as info:
        gateway.check_host(host)
    text = str(info.value)
    assert "不绑非回环地址" in text
    assert "SSH / frp" in text
    for good in ("127.0.0.1", "localhost", "::1"):
        assert gateway.check_host(good) == good


def test_build_server_requires_token() -> None:
    """★ 没有 `TF_POOL_GATEWAY_TOKEN` ⇒ 拒建：**不给「无鉴权」留默认路径**。"""
    with pytest.raises(gateway.ConfigError) as info:
        gateway.build_server(host="127.0.0.1", port=0, token="")
    text = str(info.value)
    assert "TF_POOL_GATEWAY_TOKEN" in text
    assert "无鉴权" in text
    assert "TF_MCP_HTTP_TOKEN" in text, "要写明不复用 MCP 的 token"


def test_build_server_rejects_non_loopback() -> None:
    with pytest.raises(gateway.ConfigError):
        gateway.build_server(host="0.0.0.0", port=0, token=TOKEN)


def test_build_server_rejects_bad_max_bytes() -> None:
    with pytest.raises(gateway.ConfigError):
        gateway.build_server(host="127.0.0.1", port=0, token=TOKEN, max_bytes=0)


def test_main_exits_nonzero_without_token() -> None:
    """命令壳：没有 token ⇒ **退非零、一个端口都不绑**。"""
    environ = {key: value for key, value in os.environ.items()
               if key != gateway.TOKEN_ENV}
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "tools" / "pool" / "gateway.py"),
         "--port", "0"],
        cwd=str(ROOT), env=environ, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60, **NO_WINDOW)
    assert proc.returncode != 0
    assert "TF_POOL_GATEWAY_TOKEN" in proc.stderr


def test_main_rejects_non_loopback_host() -> None:
    """命令壳：非回环 ⇒ 退非零（文案里有「回环」）。"""
    environ = {**os.environ, gateway.TOKEN_ENV: TOKEN}
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "tools" / "pool" / "gateway.py"),
         "--host", "0.0.0.0", "--port", "0"],
        cwd=str(ROOT), env=environ, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60, **NO_WINDOW)
    assert proc.returncode != 0
    assert "回环" in proc.stderr


def test_bearer_ok_uses_compare_digest() -> None:
    """★ 语义钉：`bearer_ok` 里必须是 `hmac.compare_digest`，且**不许**出现裸等号。"""
    source = (ROOT / "tools" / "pool" / "gateway.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    funcs = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    func = next(node for node in funcs if node.name == "bearer_ok")
    body = ast.get_source_segment(source, func) or ""
    assert "hmac.compare_digest" in body
    equalities = [node for node in ast.walk(func)
                  if isinstance(node, ast.Compare)
                  and any(isinstance(op, ast.Eq) for op in node.ops)]
    assert equalities == [], "Bearer 比对不许用裸等号"


def test_bearer_ok_semantics() -> None:
    assert gateway.bearer_ok(f"Bearer {TOKEN}", TOKEN) is True
    assert gateway.bearer_ok(f"bearer {TOKEN}", TOKEN) is True
    assert gateway.bearer_ok(f"Bearer {TOKEN}x", TOKEN) is False
    assert gateway.bearer_ok("Basic abc", TOKEN) is False
    assert gateway.bearer_ok(None, TOKEN) is False
    assert gateway.bearer_ok(f"Bearer {TOKEN}", "") is False


def test_split_origins_and_require_origin() -> None:
    assert gateway.split_origins(None) == ()
    assert gateway.split_origins(" http://a.test , ,http://b.test ") == (
        "http://a.test", "http://b.test")
    assert gateway.require_origin_from_env("1") is True
    assert gateway.require_origin_from_env("0") is False
    assert gateway.require_origin_from_env(None) is False


# ---------------------------------------------------------------- 真 socket


class _Stub:
    """HTTP 面的转发桩：记调用并按预设回。"""

    def __init__(self, *replies: gateway.Reply) -> None:
        self.inner = _Forward(*replies)

    def __call__(self, model: str, account: str, url: str, payload: bytes) -> gateway.Reply:
        return self.inner(model, account, url, payload)

    @property
    def calls(self) -> list[tuple[str, str, str, bytes]]:
        return self.inner.calls


@pytest.fixture()
def start_server(env: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """起一条真服务在后台线程；`port=0` 由内核挑。端点表打桩（真表全空 ⇒ 一律 403）。"""
    monkeypatch.setattr(gateway, "_platform_endpoints",
                        lambda: {"codearts": [CHAT_URL], "workbuddy": [CHAT_URL]})
    started: list[tuple[gateway._Server, threading.Thread]] = []

    def _start(forward: Any, *, token: str = TOKEN, origins: tuple[str, ...] = (),
               require_origin: bool = False, max_bytes: int = 4096) -> int:
        server = gateway.build_server(forward, host="127.0.0.1", port=0, token=token,
                                      origins=origins, require_origin=require_origin,
                                      max_bytes=max_bytes, pool="codebuddy", root=env)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        started.append((server, thread))
        return int(server.server_address[1])

    yield _start
    for server, thread in started:
        server.shutdown()
        server.server_close()
        thread.join(5)


def _header(headers: dict[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None


def _request(port: int, method: str, path: str, *, body: object = None,
             token: str | None = TOKEN, headers: dict[str, str] | None = None,
             timeout: float = 10.0) -> tuple[int, dict[str, str], bytes]:
    merged: dict[str, str] = {}
    payload: bytes | None = None
    if body is not None:
        payload = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        merged["Content-Type"] = "application/json"
    if token is not None:
        merged["Authorization"] = f"Bearer {token}"
    merged.update(headers or {})
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request(method, path, body=payload, headers=merged)
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


def test_http_requires_bearer_token(start_server: Any) -> None:
    """没有 / 错的令牌 ⇒ 401 + `WWW-Authenticate: Bearer`，且**一个请求都不转发**。"""
    stub = _Stub(_ok())
    port = start_server(stub)
    status, headers, _ = _request(port, "POST", "/v1/chat/completions",
                                  body={"model": MODEL}, token=None)
    assert status == 401
    assert _header(headers, "WWW-Authenticate") == "Bearer"
    assert _request(port, "POST", "/v1/chat/completions", body={"model": MODEL},
                    token="wrong")[0] == 401
    assert stub.calls == []


def test_http_only_four_paths(start_server: Any) -> None:
    """只有四条路径：别的一律 404；方法不对一律 405 且带 `Allow`。"""
    port = start_server(_Stub(_ok()))
    status, headers, _ = _request(port, "POST", "/v1/responses", body={"model": MODEL})
    assert status == 404
    for path in ("/v1/chat/completions", "/v1/messages"):
        status, headers, _ = _request(port, "GET", path)
        assert status == 405, path
        assert "GET" in (_header(headers, "Allow") or "")
    status, _, _ = _request(port, "POST", "/v1/models", body={"model": MODEL})
    assert status == 405


def test_http_origin_whitelist(start_server: Any) -> None:
    """Origin 不在白名单 ⇒ 403 且不转发；本机回环 Origin 放行。"""
    stub = _Stub(_ok())
    port = start_server(stub, origins=("http://ok.test",))
    status, _, _ = _request(port, "POST", "/v1/chat/completions", body={"model": MODEL},
                            headers={"Origin": "http://evil.test"})
    assert status == 403
    assert stub.calls == []
    status, _, _ = _request(port, "POST", "/v1/chat/completions", body={"model": MODEL},
                            headers={"Origin": "http://ok.test"})
    assert status == 200


def test_http_require_origin_rejects_missing_header(start_server: Any) -> None:
    """`TF_POOL_GATEWAY_REQUIRE_ORIGIN=1` ⇒ 没有 Origin 也 403。"""
    port = start_server(_Stub(_ok()), require_origin=True)
    status, _, _ = _request(port, "POST", "/v1/chat/completions", body={"model": MODEL})
    assert status == 403


def test_http_body_over_limit_is_413(start_server: Any) -> None:
    """请求体超过上限 ⇒ 413，且一个字节都不读（连接关掉）。"""
    stub = _Stub(_ok())
    port = start_server(stub, max_bytes=64)
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.putrequest("POST", "/v1/chat/completions")
        conn.putheader("Authorization", f"Bearer {TOKEN}")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", "65")
        conn.endheaders()
        response = conn.getresponse()
        assert response.status == 413
        response.read()
    finally:
        conn.close()
    assert stub.calls == []


def test_http_missing_model_is_400(start_server: Any) -> None:
    """payload 里没有 model ⇒ 400（**不让网关替你猜模型**）。"""
    stub = _Stub(_ok())
    port = start_server(stub)
    assert _request(port, "POST", "/v1/chat/completions", body={"messages": []})[0] == 400
    assert stub.calls == []


def test_http_serves_models_snapshot(start_server: Any) -> None:
    """`GET /v1/models` 只报批准集（只读快照，不联网）。"""
    port = start_server(_Stub(_ok()))
    status, _, body = _request(port, "GET", "/v1/models")
    assert status == 200
    data = json.loads(body)
    assert [item["id"] for item in data["data"]] == [MODEL]
    assert data["snapshot_stale"] is False


def test_http_serves_route_replay(start_server: Any, env: Path) -> None:
    """`GET /v1/pool/routes` 读回刚才那条路由记录（只读面）。"""
    port = start_server(_Stub(_ok()))
    assert _request(port, "POST", "/v1/chat/completions", body={"model": MODEL},
                    headers={"X-Pool-Caller": "alice"})[0] == 200
    status, _, body = _request(port, "GET", "/v1/pool/routes?limit=5")
    assert status == 200
    data = json.loads(body)
    assert data["total"] >= 1
    assert data["data"][-1]["card"] == "gw:alice"


# ================================================================ 判据 5：只做同协议直通


def test_chat_path_never_uses_messages_endpoint(env: Path) -> None:
    """客户端说 Chat、平台只登记 Messages ⇒ 拒绝（**不做协议翻译**）。"""
    forward = _Forward(_ok())
    outcome = _run(env, forward, endpoints={"codearts": [MSG_URL]})
    assert forward.calls == []
    assert outcome.status == 400
    assert "不做协议翻译" in outcome.body.decode("utf-8")


def test_messages_path_uses_messages_endpoint(env: Path) -> None:
    """客户端说 Messages ⇒ 只用 Messages 端点。"""
    forward = _Forward(_ok())
    outcome = _run(env, forward, protocol=gateway.PROTOCOL_MESSAGES,
                   endpoints={"codearts": [CHAT_URL, MSG_URL]})
    assert outcome.status == 200
    assert forward.calls[0][2] == MSG_URL


def test_streaming_upstream_non_stream_caller_is_400(start_server: Any) -> None:
    """★ 上游只流式 + 调用方要非流式 ⇒ **400 并说明**（绝不自己攒流）。"""
    stub = _Stub(gateway.Reply(status=200, headers={"Content-Type": "text/event-stream"},
                               chunks=iter([b"data: 1\n\n"])))
    port = start_server(stub)
    status, _, body = _request(port, "POST", "/v1/chat/completions", body={"model": MODEL})
    assert status == 400
    text = body.decode("utf-8")
    assert "不做攒流翻译" in text
    assert "forwardOnce" in text, "要点名不移植 magpie 的翻译层"


def test_streaming_is_forwarded_byte_for_byte(start_server: Any) -> None:
    """SSE 逐字节转发：回来的字节**一个不差**（不解析、不改写）。"""
    pieces = [b"data: {\"a\":1}\n\n", b"data: {\"b\":2}\n\n", b"data: [DONE]\n\n"]
    stub = _Stub(gateway.Reply(status=200, headers={"Content-Type": "text/event-stream"},
                               chunks=iter(pieces)))
    port = start_server(stub)
    status, headers, body = _request(port, "POST", "/v1/chat/completions",
                                     body={"model": MODEL, "stream": True})
    assert status == 200
    assert (headers.get("Content-Type") or "").startswith("text/event-stream")
    assert body == b"".join(pieces), "逐字节转发，不解析也不改写"


def test_non_streaming_upstream_is_passed_through(start_server: Any) -> None:
    """上游整块答复 ⇒ 原样回（不改写 body）。"""
    payload = b'{"id":"x","choices":[]}'
    port = start_server(_Stub(_ok(payload)))
    status, _, body = _request(port, "POST", "/v1/chat/completions", body={"model": MODEL})
    assert status == 200
    assert body == payload

# ---------------------------------------------------------------- 路由名（卡 E103 · T-AG612）


def test_build_server_rejects_unknown_routing_with_the_name() -> None:
    """★ 启动面不许 fail-open：名字不认识 ⇒ 起不来，且**点名**收到的值（同原件的 parseRouting）。"""
    with pytest.raises(gateway.ConfigError) as info:
        gateway.build_server(host="127.0.0.1", port=0, token=TOKEN, routing="nope")
    text = str(info.value)
    assert "nope" in text, "要点名运维敲的那个值"
    assert "smart" in text, "要给出可用名字（至少默认那个）"


def test_build_server_normalizes_the_routing_name() -> None:
    """别名/大小写/空串归一到**规范名**：同一个网关只认一种写法，日志与 sink 口径才对得上。"""
    server = gateway.build_server(host="127.0.0.1", port=0, token=TOKEN, routing="  LEAST-USED ")
    try:
        assert server.routing == pool_route.LEAST_USED
    finally:
        server.server_close()
    server = gateway.build_server(host="127.0.0.1", port=0, token=TOKEN, routing="")
    try:
        assert server.routing == pool_route.SMART, "原件默认值就是空串 = smart"
    finally:
        server.server_close()


def test_main_exits_2_without_binding_when_routing_is_unknown(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """命令壳：不认识的路由名 ⇒ 退 2，**一个端口都不绑**（与「没有 token」同一条硬边界）。"""
    monkeypatch.setenv(gateway.TOKEN_ENV, TOKEN)
    calls: list[dict[str, Any]] = []

    def _never(**kwargs: Any) -> int:
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(gateway, "serve_http", _never)
    assert gateway.main(["--routing", "nope"]) == 2
    assert calls == [], "既然起不来，就不许先建服务再报错"


def test_main_passes_the_normalized_routing(monkeypatch: pytest.MonkeyPatch) -> None:
    """命令壳把**规范名**交给 `serve_http`（空串 ⇒ smart），别让下游各自再猜一遍。"""
    monkeypatch.setenv(gateway.TOKEN_ENV, TOKEN)
    seen: dict[str, Any] = {}

    def _capture(**kwargs: Any) -> int:
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(gateway, "serve_http", _capture)
    assert gateway.main(["--routing", ""]) == 0
    assert seen["routing"] == pool_route.SMART


def test_gateway_ordering_actually_reaches_smart(env: Path) -> None:
    """★ 卡 E103 的现场：`--routing smart` 曾静默等于列出顺序。

    网关只做一次映射（账本行 → Seat），排位仍归 `route.apply_strategy`。
    """
    rows = (_row(SEAT_A), _row(SEAT_B))
    ledger_rows = (
        {**rows[0], "quota": {"used_percent": 95.0}},
        {**rows[1], "quota": {"used_percent": 10.0}},
    )
    assert gateway._order(ledger_rows, "order", pool="codebuddy") == [0, 1]
    assert gateway._order(ledger_rows, "smart", pool="codebuddy") == [1, 0]
    assert gateway._order(ledger_rows, "", pool="codebuddy") == [1, 0], "空串 = 原件默认 smart"


def test_gateway_ordering_still_falls_open_on_a_bad_name(env: Path) -> None:
    """请求路径上**不许**抛：名字写坏也只退列出顺序（起不来的是启动面，不是每一条请求）。"""
    rows = (_row(SEAT_A), _row(SEAT_B))
    assert gateway._order(rows, "totally-bogus", pool="codebuddy") == [0, 1]


# ================================================ 卡 E105（T-AG614）：禁用表在网关上的口径
#
# 原件 `_ext/magpie-main/internal/gateway/disabled.go` 逐字：「refused on every route before
# anything is sent upstream, with a **403** in the API's own shape」。404 = 「没有这个模型」，
# 403 = 「有，但你现在不许用」—— 禁用属于后者。
# ★ 一律把 `TF_POOL_DISABLED` 指到 tmp，不读主树那份。


def _point_disabled(tmp_path: Path, body: str, monkeypatch) -> Path:  # noqa: ANN001
    path = tmp_path / "model-disabled.toml"
    path.write_text(body, encoding="utf-8")
    monkeypatch.setenv("TF_POOL_DISABLED", str(path))
    return path


def test_disabled_model_is_403_not_404(env: Path, tmp_path: Path, monkeypatch) -> None:
    """模型在批准集里、但被禁用表停掉 ⇒ **403** + 点名禁用，且一个字节都不出网。"""
    _point_disabled(tmp_path, 'disabled = ["huaweicloud-maas/*"]\n', monkeypatch)
    forward = _Forward(_ok())
    out = _run(env, forward)
    assert out.status == 403, f"禁用该回 403（不是 404，也不是 429）：{out.status}"
    body = out.body.decode("utf-8")
    assert "被禁用" in body and "huaweicloud-maas/*" in body, body
    assert forward.calls == [], "被禁用的模型不许发上游"


def test_unknown_disabled_table_is_403(env: Path, tmp_path: Path, monkeypatch) -> None:
    """禁用表读不懂 ⇒ 不知道 ≠ 空表：403 + 点名「不知道」，同样一个字节都不出网。"""
    _point_disabled(tmp_path, "disabled = [\n", monkeypatch)
    forward = _Forward(_ok())
    out = _run(env, forward)
    assert out.status == 403, f"读不懂禁用表也该 403：{out.status}"
    body = out.body.decode("utf-8")
    assert "不知道" in body and "禁用表" in body, body
    assert forward.calls == []


def test_absent_disabled_table_keeps_the_gateway_green(env: Path, tmp_path: Path,
                                                       monkeypatch) -> None:
    """反向钉子：禁用表不存在 ⇒ 老路照走（本卡只接判据，不改数据）。"""
    monkeypatch.setenv("TF_POOL_DISABLED", str(tmp_path / "no-such-disabled.toml"))
    forward = _Forward(_ok())
    out = _run(env, forward)
    assert out.status == 200, f"没有禁用表就该照常转发：{out.status}"
    assert forward.calls, "没有禁用表就该真发上游"


# ================================================ 卡 E107（T-AG616）：_seat 的 docstring 别撒谎
#
# 原 docstring 说「route.tier() 拿到 None 会抛 RouteError，apply_strategy 的 fail-open
# 于是退回原列顺序」—— 实测 route.tier(None) == UNKNOWN_TIER == 3，**不抛**；
# 四个分桶策略（smart / usage / pace / fast）把「不知道」的座排到**所有知道的之后**。
# 一句话：docstring 说的必须是代码做的。


def test_seat_docstring_does_not_claim_a_raise_that_no_longer_happens() -> None:
    """★ 判据 4：docstring 里那两句过时断言必须消失，且点明真实口径。"""
    import inspect  # noqa: PLC0415

    doc = inspect.getdoc(gateway._seat) or ""
    assert "会抛 RouteError" not in doc, doc
    assert "退回原列顺序" not in doc, doc
    assert "UNKNOWN_TIER" in doc, doc


def test_seat_hands_unknown_quota_to_route_as_unknown_tier(env: Path) -> None:
    """★ 判据 4：docstring 说的就是代码做的 —— 网关排位与 route 直接排位逐项相等。"""
    rows = (
        {**_row(SEAT_A), "quota": {"used_percent": 90.0}},
        {**_row(SEAT_B), "quota": {}},
        {**_row("codearts-2"), "quota": {"used_percent": 10.0}},
    )
    seats = [gateway._seat(row) for row in rows]
    assert pool_route.tier(None) == pool_route.UNKNOWN_TIER, "不知道的座有自己的档"
    for name in ("smart", "usage", "pace", "fast"):
        assert gateway._order(rows, name, pool="codebuddy") == pool_route.apply_strategy(
            name, seats, pool="codebuddy"
        ), name
    # 不知道的座排最后（不是「退回原列顺序」—— 原列顺序是 [0, 1, 2]）
    assert gateway._order(rows, "smart", pool="codebuddy") == [2, 0, 1]


# ============================================ 卡 E110（T-AG619）：过期文案带命令、且只说一遍


def test_stale_gateway_message_carries_the_command_once(env: Path) -> None:
    """★ 判据 2：404 文案要带「怎么探」，且那句「先重新探测再派活」**只许出现一次**。

    改前现场：models.py 的 note 里已带一遍，_model_block 又接一遍 ⇒
    「…⇒ 先重新探测再派活 ⇒ 先重新探测再派活」。
    """
    _pool_dir(env, stale_at="2020-01-01 00:00:00")
    forward = _Forward(_ok())
    outcome = _run(env, forward)
    assert outcome.status == 404
    body = outcome.body.decode("utf-8")
    assert "模型快照不可信" in body, "那四个 marker 不许丢（disabled_wiring 钉着）"
    assert body.count("先重新探测再派活") == 1, body
    assert "--check" in body, "过期了却不说怎么探：" + body
    assert (env / "infra" / "pool" / "pool_models.py").as_posix() in body, body
    assert forward.calls == []


def test_the_snapshot_gate_really_differs_from_the_dispatcher(env: Path) -> None:
    """★ 判据 3 的实测面：同一个过期号池，网关**拒**（404）；派活器那句自己写明「不拦」。

    这条不是文案对文案：左边真调 _model_block，右边读的是派活器那句的 docstring
    （它只往 stderr 打提示、不参与派活判决）。
    """
    import wb_dispatch  # noqa: PLC0415 —— tools/ 已在 sys.path 上

    _pool_dir(env, stale_at="2020-01-01 00:00:00")
    status, blocked = gateway._model_block("codebuddy", MODEL, env, now=NOW)
    assert status == 404 and blocked, (status, blocked)
    doc = wb_dispatch.snapshot_stale_problem.__doc__ or ""
    assert "不拦派活" in doc, "派活器那边只提示不拦这件事，docstring 里得留着：" + doc


# ========================================== 卡 E131（T-AG639）：坏清单也是读数


def test_gateway_list_models_broken_whitelist_is_a_reading(env: Path) -> None:
    """★ 判据 5：坏 whitelist 不许让 `/v1/models` 裸抛 —— data 空 + note 点名 + 原文旁挂。

    ★ 卡 E131：`:687` 直调 `load_pool_models`，`TOMLDecodeError` 一路冒到
      `BaseHTTPRequestHandler`（H4）—— 客户端拿到的是连接错误，不是「清单读不懂」。
    """
    (env / "infra" / "pool" / "models.whitelist.toml").write_text("[[approved]\n", encoding="utf-8")
    out = gateway.list_models(root=env)
    assert out["object"] == "list"
    assert out["data"] == [], "读不懂就不许把「一条都没批」当成答案"
    assert "models.whitelist.toml" in out["note"], out["note"]
    assert out["models_source_broken"]["file"] == "models.whitelist.toml"
    assert "Expected ']]'" in out["models_source_broken"]["error"]


def test_gateway_model_block_broken_whitelist_is_404_named(env: Path) -> None:
    """★ 判据 5：准入侧同源 —— 404 + 点名，人话面**不透异常类名**。"""
    (env / "infra" / "pool" / "models.whitelist.toml").write_text("[[approved]\n", encoding="utf-8")
    status, msg = gateway._model_block("codebuddy", MODEL, env, now=NOW)
    assert status == 404, (status, msg)
    assert "models.whitelist.toml" in msg, msg
    assert "坏了" in msg, msg
    assert "TOMLDecodeError" not in msg, "人话面不许透异常类名：" + msg



# ========================================== 卡 E143（F86 ①）：/v1/models 发布窗口读数
def _point_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, models: str) -> Path:
    """把注册表指到 tmp 里那份（判据自带条目，不读宿主上那份真注册表）。"""
    path = tmp_path / "model-registry.toml"
    path.write_text(models, encoding="utf-8")
    monkeypatch.setenv("TF_MODEL_REGISTRY", str(path))
    return path


def _one_model(name: str, *, extra: str = "") -> str:
    """造一条 codebuddy 条目（alias == id == name）；extra 是额外的窗口行。"""
    return (
        "[[model]]" + chr(10) +
        f'alias = "{name}"' + chr(10) +
        'pool = "codebuddy"' + chr(10) +
        f'id = "{name}"' + chr(10) +
        "default = true" + chr(10) +
        extra
    )


def test_list_models_publishes_window_readings(
        env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 判据 3（F86 ①）：注册表里填了窗口 ⇒ 每条 data 原样念出来，limits_source = registry。

    ★ 「知道」就念知道的：context_window / max_output_tokens 是注册表里那两个数，
      不许被网关再加工（不是 95%、不是减一个余量 —— 那是**读数的消费者**的事）。
    """
    _pool_dir(env, approved=("deepseek-v4.1-flash",))
    _point_registry(tmp_path, monkeypatch, _one_model(
        "deepseek-v4.1-flash",
        extra="context_window = 1000000" + chr(10) + "max_output = 32000" + chr(10)))
    out = gateway.list_models(root=env)
    assert [item["id"] for item in out["data"]] == ["deepseek-v4.1-flash"]
    item = out["data"][0]
    assert item["context_window"] == 1000000, item
    assert item["max_output_tokens"] == 32000, item
    assert item["limits_source"] == "registry", item
    assert item["object"] == "model" and item["owned_by"] == "pool", item
    assert "0 条模型的窗口未知" in out["note"], out["note"]


def test_list_models_unknown_window_is_null_not_zero(
        env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 判据 3（F86 ①）：**不知道就说不知道** —— context_window 是 null，不是 0。

    ★ 0 是一个**读数**（一点都装不下），null 是「没人量过」。两者混起来，
      下游会把「没量过」当成「装不下」⇒ 全拒。回复上限照 UNKNOWN_MAX_OUTPUT 发，
      并明说 limits_source = unknown（那是读数，不是缺陷）。
    """
    _pool_dir(env, approved=("deepseek-v4.1-flash",))
    _point_registry(tmp_path, monkeypatch, _one_model("deepseek-v4.1-flash"))
    out = gateway.list_models(root=env)
    item = out["data"][0]
    assert item["context_window"] is None, item
    # ★ 钉住**读数本身**（16 KiB 这么写，本文件也不许出现那个字面量）：
    #   拿常量比自己会永远绿 —— 常量被改成 0 也照样过，那就不是判据。
    assert item["max_output_tokens"] == 16 << 10, item
    assert pool_model_registry.UNKNOWN_MAX_OUTPUT == 16 << 10
    assert item["limits_source"] == "unknown", item
    assert "1 条模型的窗口未知" in out["note"], out["note"]
    assert str(16 << 10) in out["note"], out["note"]


def test_list_models_zero_window_is_a_reading(
        env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 判据 1 的读数面：0 是合法读数 ⇒ context_window 念 0（不是 null）。"""
    _pool_dir(env, approved=("deepseek-v4.1-flash",))
    _point_registry(tmp_path, monkeypatch, _one_model(
        "deepseek-v4.1-flash", extra="context_window = 0" + chr(10)))
    item = gateway.list_models(root=env)["data"][0]
    assert item["context_window"] == 0, item
    assert item["limits_source"] == "registry", item
    assert item["max_output_tokens"] == pool_model_registry.UNKNOWN_MAX_OUTPUT, item


def test_broken_registry_does_not_break_models_face(
        env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 注册表坏掉 ⇒ 窗口这一维退化成「不知道」，/v1/models 照旧发布清单。

    ★ 清单的真源是批准集，不是注册表：注册表坏了该让**派活**拒绝，不该让只读读面 500
      （那会把「注册表写歪了」读成「网关坏了」）。
    """
    _pool_dir(env, approved=("deepseek-v4.1-flash",))
    _point_registry(tmp_path, monkeypatch, "this is not = valid = toml =" + chr(10))
    item = gateway.list_models(root=env)["data"][0]
    assert item["id"] == "deepseek-v4.1-flash", item
    assert item["context_window"] is None, item
    assert item["limits_source"] == "unknown", item


def test_http_models_face_carries_window_readings(
        start_server: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 判据 3 的 HTTP 面：真起服务、真 GET /v1/models，六键一个不少。"""
    _point_registry(tmp_path, monkeypatch, _one_model(
        MODEL, extra="context_window = 1000000" + chr(10) + "max_output = 32000" + chr(10)))
    port = start_server(_Stub(_ok()))
    status, _, body = _request(port, "GET", "/v1/models")
    assert status == 200
    data = json.loads(body)
    assert [item["id"] for item in data["data"]] == [MODEL]
    item = data["data"][0]
    assert item["context_window"] == 1000000, item
    assert item["max_output_tokens"] == 32000, item
    assert item["limits_source"] == "registry", item
    assert "条模型的窗口未知" in data["note"], data["note"]


# ================================================================ F36：网络准入（卡 A376）


def _gateway_source() -> tuple[str, ast.Module]:
    """`tools/pool/gateway.py` 的源码与语法树 —— AST 判据一律从这一处取。"""
    source = (ROOT / "tools" / "pool" / "gateway.py").read_text(encoding="utf-8")
    return source, ast.parse(source)


def _string_constants(tree: ast.Module) -> list[str]:
    """全部 `ast.Constant` 里的 `str`（**含 docstring**）。"""
    return [node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)]


def test_f36_allowed_hosts_is_exactly_three() -> None:
    """★ 判据 1：`ALLOWED_HOSTS` 恰好三个回环值，且源码里没有第二个 host 来源。

    ★ 钉的是**集合本身**，不是「坏值被收」—— 后者既有 `test_check_host_rejects_non_loopback`
      已经管了，往集合里加第四个值它照样全绿。
    """
    assert sorted(gateway.ALLOWED_HOSTS) == ["127.0.0.1", "::1", "localhost"]
    source, tree = _gateway_source()
    constants = _string_constants(tree)
    # 整串相等（不是子串）：报错文案里本来就有「不给 0.0.0.0 开口子」这句话
    # （:969 docstring / :974 ConfigError 文案），子串判据一落地就是假红。
    # 这里挡的是「有人写 if host == "0.0.0.0" 放行」——那必然留下一个整串相等的常量。
    assert "0.0.0.0" not in constants, [c for c in constants if "0.0.0.0" in c]
    assert "::" not in constants, [c for c in constants if c.strip() == "::"]
    assert "TF_POOL_GATEWAY_HOST" not in source


def test_f36_host_and_forward_headers_change_nothing(start_server: Any) -> None:
    """★ 判据 2：伪造 `Host` + 六个转发头拿不到任何额外东西（答复逐字节不变）。

    ★ 今天源码一次都不读 `Host`，六个转发头也零命中 —— 这是「安全靠没写」。
      下一个人为了打日志顺手读 `Host` 做分支时，这条该红。
    """
    stub = _Stub(_ok())
    port = start_server(stub)
    status, _, body0 = _request(port, "GET", "/v1/models")
    assert status == 200
    status, _, body = _request(port, "GET", "/v1/models", headers={"Host": "evil.example"})
    assert status == 200
    assert body == body0, "伪造 Host 改动了答复"
    forwarded = {
        "Host": "evil.example",
        "Forwarded": "for=10.0.0.1",
        "X-Forwarded-For": "10.0.0.1",
        "X-Real-IP": "10.0.0.1",
        "Cf-Connecting-IP": "10.0.0.1",
        "True-Client-IP": "10.0.0.1",
        "Tailscale-User-Login": "evil@example.test",
    }
    status, _, body = _request(port, "GET", "/v1/models", headers=forwarded)
    assert status == 200
    assert body == body0, "转发头改动了答复"
    assert stub.calls == []


def test_f36_origin_null_and_localhost_subdomain_still_refused(start_server: Any) -> None:
    """★ 判据 3 上半：magpie 点名的两个形状（`Origin: null` / `*.localhost`）仍然 403。

    ★ 只钉 `http://a.localhost` 这一个具体值（卡规格「未坐实项 2」：别的形状没扫过），
      别把它读成「所有 localhost 子域都被挡」。
    """
    stub = _Stub(_ok())
    port = start_server(stub)
    status, _, body = _request(port, "GET", "/v1/models", headers={"Origin": "null"})
    assert status == 403
    assert b"permission_error" in body, body
    status, _, _ = _request(port, "GET", "/v1/models",
                            headers={"Origin": "http://a.localhost"})
    assert status == 403
    # 对照：不是把 Origin 一刀切 —— 本机回环 Origin 放行。
    status, _, _ = _request(port, "GET", "/v1/models",
                            headers={"Origin": f"http://127.0.0.1:{port}"})
    assert status == 200
    assert stub.calls == []


def test_f36_options_and_put_stay_unavailable(start_server: Any) -> None:
    """★ 判据 3 下半：`OPTIONS` 仍然 501（没有 `do_OPTIONS`），`PUT` 仍然 405 + `Allow`。

    ★ 补一个 `do_OPTIONS` 去过 CORS 预检，这条就该红：预检在客户端解决，不在服务面开端。
    """
    stub = _Stub(_ok())
    port = start_server(stub)
    status, headers, body = _request(port, "OPTIONS", "/v1/chat/completions")
    assert status == 501, "补了 do_OPTIONS 就该红"
    assert _header(headers, "Allow") is None
    assert b"/v1/" not in body, body
    status, headers, _ = _request(port, "PUT", "/v1/chat/completions")
    assert status == 405
    assert _header(headers, "Allow") == "GET, POST"
    assert stub.calls == []


def test_f36_paths_table_is_exactly_four(start_server: Any) -> None:
    """★ 判据 4：路径表恰好四键，且没有任何 `/v1/magpie/` 前缀的常量。

    ★ `test_http_only_four_paths` 只验了三条具体反例，集合本身没人管 —— 加第五键它照样绿。
    """
    assert sorted(gateway.PATHS) == ["/v1/chat/completions", "/v1/messages",
                                     "/v1/models", "/v1/pool/routes"]
    _, tree = _gateway_source()
    constants = _string_constants(tree)
    assert [c for c in constants if c.startswith("/v1/magpie/")] == []
    stub = _Stub(_ok())
    port = start_server(stub)
    for path in ("/v1/magpie/heap", "/v1/magpie/cpu?seconds=30", "/v1/magpie/goroutines"):
        status, _, body = _request(port, "GET", path)
        assert status == 404, path
        assert b"not_found_error" in body, (path, body)
    # 反证：那三条 404 不是鉴权挡的 —— 同一个服务面上，去掉 token 的 /v1/models 是 401。
    assert _request(port, "GET", "/v1/models", token=None)[0] == 401
    assert stub.calls == []


def test_f36_no_transport_layer_switches() -> None:
    """★ 判据 5：源码里没有任何传输层 / 准入层开关（纯 AST + 文本，不起服务、不联网）。"""
    _, tree = _gateway_source()
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint({"ssl", "socket"}), sorted(imported)
    constants = [c.lower() for c in _string_constants(tree)]
    needles = ("x-forwarded-for", "x-real-ip", "cf-connecting-ip", "tailscale-user-login",
               "trust_proxy", "cidr", "allow_ips", "certfile")
    hits = {needle: [c for c in constants if needle in c] for needle in needles}
    assert not any(hits.values()), {key: value for key, value in hits.items() if value}


def test_f36_port_8766_is_declared_once_and_not_orchestrated() -> None:
    """★ 判据 6：端口与接线现状被记着 —— 8766 只在这里声明一次，且没人编排它。

    ★ 「以为 stack.py 会起它」是空想：网关今天只能手工 `python tools/pool/gateway.py` 起。
    """
    assert gateway.DEFAULT_PORT == 8766
    assert gateway.DEFAULT_HOST == "127.0.0.1"
    source, _ = _gateway_source()
    assert source.count("8766") == 1, "端口被写在了第二处：改这条断言前先想清楚谁才是真源"
    stack = (ROOT / "tools" / "stack.py").read_text(encoding="utf-8")
    assert "gateway" not in stack, "网关被编排进 stack.py 了：先重取读数，再改这条"
    lock = (ROOT / "gates" / "diag" / "gate_lock.py").read_text(encoding="utf-8")
    assert "8766" not in lock, "8766 进了门禁端口表：两个东西会抢同一个端口"
