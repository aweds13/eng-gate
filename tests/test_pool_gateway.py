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
