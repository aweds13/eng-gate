"""卡 E48 / T-AG497：手动签到（拉取式）的钉子。

每条钉都对着卡 §4 的判据，用假 fetcher 回放真实响应形状 —— 不打真接口、
不依赖网络。真正会**发写请求**的路径只有 ``tools/pool/checkin.py``，这里连它一起钉。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from tools.pool import checkin as ck

# ---------------------------------------------------------------- 假 fetcher


WRITE_ENDPOINTS = (
    "/daily-checkin",
    "/signin/claim",
    "/checkin_credits/claim",
    "/ops/claim",
    "/ops/confirm",
)


def _is_write(url: str) -> bool:
    """这条 URL 是不是写动作（领取 / 确认）。"""
    if any(url.endswith(suffix) for suffix in WRITE_ENDPOINTS):
        return True
    return "/campaigns/" in url and url.endswith("/claim")


class FakeFetcher:
    """按顺序回放响应，并记下每一次调用（方法/URL/头/体）。"""

    def __init__(self, responses: list[tuple[int, object]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def __call__(self, method, url, headers, body):
        self.calls.append(
            {"method": method.upper(), "url": url, "headers": dict(headers or {}), "body": body}
        )
        if not self.responses:
            raise AssertionError(f"意外多出来的请求：{method} {url}")
        status, payload = self.responses.pop(0)
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return status, text

    @property
    def writes(self) -> list[dict[str, object]]:
        """**真正会改动上游状态**的调用 —— 按端点语义认，不按 HTTP 方法认。

        腾讯 WorkBuddy 与 Trae 的状态查询本来就是 ``POST``（magpie
        ``workbuddy_checkin.go:342``、参考实现 ``src_trae-credits.ts:191``），所以
        「非 GET 即写」会把只读的状态查询也算成写动作，判据随之失真。
        """
        return [c for c in self.calls if _is_write(c["url"])]


def env(**kwargs) -> dict[str, str]:
    return {k: v for k, v in kwargs.items()}


CODEARTS_TOKEN = "AKIDEXAMPLE"
CODEARTS_CRED = ck.CodeArtsCredential(CODEARTS_TOKEN, "secret-key", "session-token")


def package_response(*, credit: bool = True, token: bool = False) -> dict[str, object]:
    return {"package": {"is_credit_package": credit, "is_token_package": token}}


def delivery_response(
    *, claimable: bool = True, status: str = "CLAIMABLE", campaign: object = 1
) -> dict[str, object]:
    return {
        "items": [
            {"type": "NEW_USER", "campaignId": 99, "claimable": False, "status": "CLAIMED"},
            {
                "type": ck.CODEARTS_DAILY_TYPE,
                "campaignId": campaign,
                "claimable": claimable,
                "status": status,
                "benefitAmount": 1000,
            },
        ]
    }


def ops_ok(data: dict[str, object]) -> dict[str, object]:
    return {"code": 0, "message": "ok", "data": data}


# ---------------------------------------------------------------- 结论码本身


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError, match="未知结论码"):
        ck.Outcome("半成功")


def test_to_dict_omits_empty_fields():
    assert ck.Outcome(ck.ALREADY_CLAIMED).to_dict() == {"kind": ck.ALREADY_CLAIMED}
    full = ck.Outcome(ck.CLAIMED, message="领取成功", credit=1000, unit="积分")
    assert full.to_dict() == {
        "kind": ck.CLAIMED,
        "message": "领取成功",
        "credit": 1000.0,
        "unit": "积分",
    }
    assert full.summary == "+1000 积分；领取成功"


# ---------------------------------------------------------------- 签名


def test_sign_huawei_shape_and_rule_of_extra_headers():
    headers = ck.sign_huawei(CODEARTS_TOKEN, "sk", "st", "POST", ck.CODEARTS_BASE + "/v1/ops/claim")
    assert headers["host"] == "snap-access.cn-north-4.myhuaweicloud.com"
    assert headers["content-type"] == "application/json"
    assert re.fullmatch(r"\d{8}T\d{6}Z", headers["x-sdk-date"])
    assert headers["x-sdk-content-sha256"] == ck._sha256_hex(b"")
    match = re.fullmatch(
        r"SDK-HMAC-SHA256 Access=([^,]+),SignedHeaders=([^,]+),Signature=([0-9a-f]{64})",
        headers["Authorization"],
    )
    assert match, headers["Authorization"]
    assert match.group(1) == CODEARTS_TOKEN
    signed = match.group(2).split(";")
    # 签名头必须排序，且**不含** Agent-Type / X-Language（进了就 401 APIG.0301）
    assert signed == sorted(signed)
    assert "agent-type" not in [s.lower() for s in signed]


def test_sign_huawei_get_has_no_content_type():
    headers = ck.sign_huawei(
        CODEARTS_TOKEN, "sk", "", "GET", ck.CODEARTS_BASE + "/snap-manager/v1/statistics/plugin"
    )
    assert "content-type" not in headers


def test_sign_huawei_is_deterministic_for_same_inputs():
    first = ck.sign_huawei("a", "b", "", "GET", "https://x.cn/a")
    second = ck.sign_huawei("a", "b", "", "GET", "https://x.cn/a")
    assert first["Authorization"] == second["Authorization"]


# ---------------------------------------------------------------- codearts


def test_codearts_non_credit_account_is_inactive_without_writes():
    fetcher = FakeFetcher([(200, package_response(credit=False, token=True))])
    outcome = ck.claim_codearts(CODEARTS_CRED, fetcher)
    assert outcome.kind == ck.INACTIVE
    assert "Token 计费账户" in outcome.message
    assert fetcher.writes == []


def test_codearts_already_claimed_sends_no_claim():
    fetcher = FakeFetcher(
        [
            (200, package_response()),
            (200, delivery_response(claimable=False, status="CLAIMED")),
        ]
    )
    outcome = ck.claim_codearts(CODEARTS_CRED, fetcher)
    assert outcome.kind == ck.ALREADY_CLAIMED
    assert fetcher.writes == []


def test_codearts_claim_then_confirm_and_credit_come_back():
    fetcher = FakeFetcher(
        [
            (200, package_response()),
            (200, delivery_response()),
            (200, ops_ok({"id": 4321})),
            (200, ops_ok({})),
        ]
    )
    outcome = ck.claim_codearts(CODEARTS_CRED, fetcher)
    assert outcome.kind == ck.CLAIMED
    assert outcome.credit == 1000
    assert outcome.unit == "积分"
    writes = fetcher.writes
    # 卡 §4.4：遗漏「id !== null 后补 confirm」这一步，积分停在待确认
    assert [w["url"].rsplit("/", 1)[-1] for w in writes] == ["claim", "confirm"]
    claim_body = json.loads(writes[0]["body"] or b"{}")
    # campaignId 原样发数字（实测服务端就是数字 1，串成字符串可能被拒）
    assert claim_body == {"campaignId": 1, "channel": "IDE"}
    assert json.loads(writes[1]["body"] or b"{}") == {"campaignId": 1}


def test_codearts_claim_with_null_id_skips_confirm():
    fetcher = FakeFetcher(
        [
            (200, package_response()),
            (200, delivery_response()),
            (200, ops_ok({"id": None})),
        ]
    )
    outcome = ck.claim_codearts(CODEARTS_CRED, fetcher)
    assert outcome.kind == ck.CLAIMED
    assert [w["url"].rsplit("/", 1)[-1] for w in fetcher.writes] == ["claim"]


def test_codearts_confirm_failure_does_not_flip_to_failed():
    fetcher = FakeFetcher(
        [
            (200, package_response()),
            (200, delivery_response()),
            (200, ops_ok({"id": 7})),
            (500, {"error": "boom"}),
        ]
    )
    outcome = ck.claim_codearts(CODEARTS_CRED, fetcher)
    # 积分已进待确认态：报 failed 会让人重复点（卡 §4.4）
    assert outcome.kind == ck.CLAIMED
    assert outcome.extra.get("confirm_failed") is True


def test_codearts_auth_failure_is_uncertain_with_server_reason():
    fetcher = FakeFetcher([(401, {"error_code": "APIG.0301", "error_msg": "verify ak sk failed"})])
    outcome = ck.claim_codearts(CODEARTS_CRED, fetcher)
    assert outcome.kind == ck.UNCERTAIN
    assert "APIG.0301" in outcome.message
    assert len(fetcher.calls) == 1  # 不重试


def test_codearts_business_code_non_zero_is_failed():
    fetcher = FakeFetcher(
        [
            (200, package_response()),
            (200, delivery_response()),
            (200, {"code": 4001, "message": "活动已结束", "data": {}}),
        ]
    )
    outcome = ck.claim_codearts(CODEARTS_CRED, fetcher)
    assert outcome.kind == ck.FAILED
    assert outcome.code == 4001
    assert "活动已结束" in outcome.message


def test_codearts_missing_daily_activity_is_inactive():
    fetcher = FakeFetcher([(200, package_response()), (200, {"items": []})])
    outcome = ck.claim_codearts(CODEARTS_CRED, fetcher)
    assert outcome.kind == ck.INACTIVE
    assert "每日签到" in outcome.message


def test_rate_limit_is_uncertain_and_never_retried():
    fetcher = FakeFetcher([(429, "too many requests")])
    outcome = ck.claim_codearts(CODEARTS_CRED, fetcher)
    assert outcome.kind == ck.UNCERTAIN
    assert len(fetcher.calls) == 1


def test_network_error_is_uncertain_not_failed():
    def boom(method, url, headers, body):
        raise ck.NetworkError("connection reset")

    outcome = ck.claim_for_platform(
        "codearts",
        {"claim_flow": ["x"], "token_env": "TF_CODEARTS_AK/TF_CODEARTS_SK"},
        ["ak", "sk"],
        boom,
    )
    assert outcome.kind == ck.UNCERTAIN
    assert "网络不明" in outcome.message


# ---------------------------------------------------------------- probe 模式


@pytest.mark.parametrize(
    ("platform_name", "tokens", "responses"),
    [
        (
            "workbuddy",
            ["t"],
            [(200, {"code": 0, "data": {"active": True, "today_checked_in": False}})],
        ),
        ("qoder", ["t"], [(200, {"campaigns": [{"campaignId": 5, "claimable": True}]})]),
        ("trae", ["t"], [(200, {"code": 0, "data": {"checked_in": False}})]),
        ("minimax", ["t"], [(200, {"base_resp": {"status_code": 0}, "data": {"is_today": False}})]),
    ],
)
def test_probe_mode_never_posts(platform_name, tokens, responses):
    fetcher = FakeFetcher(responses)
    outcome = ck.claim_for_platform(
        platform_name, {"claim_flow": ["x"], "token_env": "T"}, tokens, fetcher, apply=False
    )
    assert outcome.kind in (ck.INACTIVE, ck.ALREADY_CLAIMED)
    assert fetcher.writes == []


def test_probe_codearts_only_reads():
    fetcher = FakeFetcher([(200, package_response()), (200, delivery_response(claimable=True))])
    outcome = ck.claim_for_platform(
        "codearts",
        {"claim_flow": ["x"], "token_env": "A/B"},
        ["ak", "sk"],
        fetcher,
        apply=False,
    )
    assert outcome.kind == ck.INACTIVE
    assert "可领取" in outcome.message
    assert fetcher.writes == []


# ---------------------------------------------------------------- 其它平台


def test_workbuddy_404_is_not_supported():
    fetcher = FakeFetcher([(404, "not found")])
    outcome = ck.claim_workbuddy("t", fetcher)
    assert outcome.kind == ck.NOT_SUPPORTED
    assert fetcher.writes == []
    # 状态查询本身也要带 UA：网关认不出客户端就回 code 10085，签到一次都领不到
    assert fetcher.calls[0]["headers"]["User-Agent"] == "WorkBuddy/5.5.6"


def test_workbuddy_claim_returns_points():
    fetcher = FakeFetcher(
        [
            (200, {"code": 0, "data": {"active": True, "today_checked_in": False}}),
            (200, {"code": 0, "data": {"credit": 20}}),
        ]
    )
    outcome = ck.claim_workbuddy("t", fetcher)
    assert outcome.kind == ck.CLAIMED
    assert outcome.credit == 20
    assert outcome.unit == "点"


def test_workbuddy_duplicate_claim_is_already_claimed_not_failed():
    """幂等判据在**响应体**：重复领取是 HTTP 400 + code 10001（参考实现 buddy.js:678）。"""
    fetcher = FakeFetcher(
        [
            (200, {"code": 0, "data": {"active": True, "today_checked_in": False}}),
            (400, {"code": 10001, "msg": "already checked in"}),
        ]
    )
    outcome = ck.claim_workbuddy("t", fetcher)
    assert outcome.kind == ck.ALREADY_CLAIMED, outcome


def test_workbuddy_gateway_without_ua_answers_10085_is_failed():
    """认不出 UA 时上游回 code 10085（HTTP 200）⇒ 必须判失败，不许当成功。"""
    fetcher = FakeFetcher([(200, {"code": 10085, "msg": "请求不合法"})])
    outcome = ck.claim_workbuddy("t", fetcher)
    assert outcome.kind == ck.FAILED
    assert outcome.code == 10085


def test_qoder_claim_then_second_round_is_already_claimed():
    first = FakeFetcher(
        [
            (200, {"campaigns": [{"campaignId": 5, "claimable": True}]}),
            (200, {"credit": 30}),
        ]
    )
    assert ck.claim_qoder("t", first).kind == ck.CLAIMED
    assert first.writes[0]["url"].endswith("/campaigns/5/claim")
    # 领取成功后活动列表仍非空 —— 用空列表判已领会永远「没领过」
    second = FakeFetcher(
        [(200, {"campaigns": [{"campaignId": 5, "claimable": False, "status": "CLAIMED"}]})]
    )
    outcome = ck.claim_qoder("t", second)
    assert outcome.kind == ck.ALREADY_CLAIMED
    assert second.writes == []


def test_trae_claimed_and_claim_paths():
    done = FakeFetcher([(200, {"code": 0, "data": {"checked_in": True}})])
    assert ck.claim_trae("t", done).kind == ck.ALREADY_CLAIMED
    # claim 响应不含积分数（实测就是 {"code":0,"message":"success"}）⇒ 成功后补查 status
    fresh = FakeFetcher(
        [
            (200, {"code": 0, "data": {"checked_in": False}}),
            (200, {"code": 0, "message": "success"}),
            (200, {"code": 0, "credits": 50}),
        ]
    )
    outcome = ck.claim_trae("t", fresh)
    assert outcome.kind == ck.CLAIMED
    assert outcome.credit == 50


def test_trae_business_failure_is_not_reported_as_claimed():
    """失败响应与成功同形、HTTP 都是 200 —— 只看 HTTP 会把 {"code":9004} 报成成功 +0。"""
    fetcher = FakeFetcher(
        [(200, {"code": 0, "data": {"checked_in": False}}), (200, {"code": 9004, "message": "x"})]
    )
    outcome = ck.claim_trae("t", fetcher)
    assert outcome.kind == ck.FAILED
    assert outcome.code == 9004


def test_trae_busy_code_is_failed_with_message():
    fetcher = FakeFetcher(
        [(200, {"code": 0, "data": {"checked_in": False}}), (200, {"code": "9074"})]
    )
    outcome = ck.claim_trae("t", fetcher)
    assert outcome.kind == ck.FAILED
    assert outcome.code == 9074
    assert "人数过多" in outcome.message


def test_minimax_http_200_business_failure_is_failed():
    fetcher = FakeFetcher(
        [(200, {"base_resp": {"status_code": 1004, "status_msg": "signin closed"}})]
    )
    outcome = ck.claim_minimax("t", fetcher)
    assert outcome.kind == ck.FAILED
    assert outcome.code == 1004
    assert "signin closed" in outcome.message
    assert fetcher.writes == []


def test_minimax_claimed_needs_both_flags():
    fetcher = FakeFetcher(
        [(200, {"base_resp": {"status_code": 0}, "data": {"is_today": True, "status": 3}})]
    )
    assert ck.claim_minimax("t", fetcher).kind == ck.ALREADY_CLAIMED
    # is_today=False 就算 status=3 也不算今天已领（探针视角：仍会去领）
    stale = FakeFetcher(
        [(200, {"base_resp": {"status_code": 0}, "data": {"is_today": False, "status": 3}})]
    )
    assert ck.claim_minimax("t", stale, apply=False).kind == ck.INACTIVE


# ---------------------------------------------------------------- 分派与凭据


def test_unsupported_platform_is_not_supported():
    outcome = ck.claim_for_platform("opencode", {"claim_flow": []}, [], FakeFetcher([]))
    assert outcome.kind == ck.NOT_SUPPORTED


def test_missing_token_is_uncertain_and_names_env():
    outcome = ck.claim_for_platform(
        "workbuddy", {"claim_flow": ["x"], "token_env": "TF_WORKBUDDY_TOKEN"}, [], FakeFetcher([])
    )
    assert outcome.kind == ck.UNCERTAIN
    assert "TF_WORKBUDDY_TOKEN" in outcome.message


def test_missing_codearts_secret_is_uncertain():
    outcome = ck.claim_for_platform(
        "codearts", {"claim_flow": ["x"], "token_env": "A/B"}, ["only-ak"], FakeFetcher([])
    )
    assert outcome.kind == ck.UNCERTAIN
    assert "AK/SK" in outcome.message


def test_unimplemented_platform_is_not_supported():
    outcome = ck.claim_for_platform(
        "lobsterai", {"claim_flow": ["x"], "token_env": "T"}, ["t"], FakeFetcher([])
    )
    assert outcome.kind == ck.NOT_SUPPORTED
    assert "还没实现" in outcome.message


def test_tokens_from_env_splits_on_slash():
    tokens = ck.tokens_from_env({"token_env": "A / B / C"}, env(A="1", B="2"))
    assert tokens == ["1", "2", ""]


def test_platform_supports_claim():
    assert ck.platform_supports_claim({"claim_flow": ["GET x"]}) is True
    assert ck.platform_supports_claim({"claim_flow": []}) is False
    assert ck.platform_supports_claim({}) is False


# ---------------------------------------------------------------- 命令行层
#
# 上面钉的是「结论码对不对」，这里钉的是「一次手动签到跑下来留下了什么」——
# 留档、账本回写、间隔、只读纪律。

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import pool_accounts as pa  # noqa: E402 —— tools/ 已在 sys.path 上

LEDGER_TEXT = """
[[account]]
id = "codearts-1"
label = "备用号 codearts"
platform = "codearts"
state = "active"
added_at = "2026-09-30"
approved_models = ["huaweicloud-maas/deepseek-v4.1-flash"]

[account.credential]
kind = "file"
locator = "~/.codeartsdoer/pool.env"

[account.quota]
unit = "积分"
source = "unknown"

[account.health]
state = "unknown"

[[account]]
id = "workbuddy-1"
label = "腾讯号"
platform = "workbuddy"
state = "active"
added_at = "2026-10-01"
approved_models = []

[account.credential]
kind = "dir"
locator = "~/.workbuddy"

[account.quota]
unit = "点"
source = "unknown"

[account.health]
state = "unknown"
"""

PLATFORMS = {
    "codearts": {
        "label": "华为云码道",
        "claim_flow": ["GET x"],
        "token_env": "TF_CODEARTS_AK/TF_CODEARTS_SK",
        "unit": "积分",
    },
    "workbuddy": {
        "label": "腾讯 WorkBuddy",
        "claim_flow": ["GET x"],
        "token_env": "TF_WORKBUDDY_TOKEN",
        "unit": "点",
    },
}


def make_ledger(tmp_path) -> Path:
    path = tmp_path / "accounts.toml"
    path.write_text(LEDGER_TEXT, encoding="utf-8")
    return path


def test_run_checkin_writes_rows_and_spacing(tmp_path):
    data = pa.load_ledger(make_ledger(tmp_path), PLATFORMS, strict=False)
    fetcher = FakeFetcher(
        [
            (200, package_response()),
            (200, delivery_response()),
            (200, ops_ok({"id": 1})),
            (200, ops_ok({})),
            (200, {"data": {"checked_in": True}}),
        ]
    )
    slept: list[float] = []
    rows = pa.run_checkin(
        data,
        PLATFORMS,
        apply=True,
        environ={"TF_CODEARTS_AK": "ak", "TF_CODEARTS_SK": "sk", "TF_WORKBUDDY_TOKEN": "t"},
        fetcher=fetcher,
        sleep=slept.append,
        spacing=2.0,
    )
    assert [r["kind"] for r in rows] == [ck.CLAIMED, ck.ALREADY_CLAIMED]
    assert rows[0]["credit"] == 1000
    # 串行：平台之间才等，最后一个后面不等
    assert slept == [2.0]


def test_run_checkin_zero_spacing_never_sleeps(tmp_path):
    data = pa.load_ledger(make_ledger(tmp_path), PLATFORMS, strict=False)
    fetched = []

    def no_network(method, url, headers, body):
        fetched.append(method)
        return 404, "nope"

    rows = pa.run_checkin(
        data, PLATFORMS, apply=True, environ={}, fetcher=no_network, sleep=lambda s: None, spacing=0
    )
    # 两个号都没有凭据：缺凭据 ⇒ uncertain，且一条请求都不发
    assert [r["kind"] for r in rows] == [ck.UNCERTAIN, ck.UNCERTAIN]
    assert fetched == []


def test_probe_mode_sends_no_write_requests(tmp_path):
    data = pa.load_ledger(make_ledger(tmp_path), PLATFORMS, strict=False)
    fetcher = FakeFetcher(
        [
            (200, package_response()),
            (200, delivery_response(claimable=True)),
            (200, {"data": {"checked_in": False}}),
        ]
    )
    rows = pa.run_checkin(
        data,
        PLATFORMS,
        apply=False,
        environ={"TF_CODEARTS_AK": "ak", "TF_CODEARTS_SK": "sk", "TF_WORKBUDDY_TOKEN": "t"},
        fetcher=fetcher,
        sleep=lambda s: None,
    )
    assert [r["kind"] for r in rows] == [ck.INACTIVE, ck.INACTIVE]
    assert fetcher.writes == []


def test_probe_mode_never_touches_the_verdict_bits(tmp_path):
    """★ `--probe` 只探不领：只许写留档 + `last_probe`，不许写 `last_checkin` / 失败计数。

    卡 E48 §4.3 授权的是「写进留档 JSON 与账本 `last_probe`」。写了 `last_checkin` 会把
    「今天问过了」烙进账本 —— `recheck_rows()` 拿它当结论码判 `due`，于是**探一次就把
    当天真正的签到机会判成「当日已定案」**，再也不会去领。
    """
    # 只给最后一个号（workbuddy）一个旧结论 + 失败计数
    tail = (
        '[[account]]\n'
        'id = "workbuddy-1"\n'
        'label = "腾讯号"\n'
        'platform = "workbuddy"\n'
        'state = "active"\n'
        'added_at = "2026-10-01"\n'
        "approved_models = []\n"
        "\n"
        "[account.credential]\n"
        'kind = "dir"\n'
        'locator = "~/.workbuddy"\n'
        "\n"
        "[account.quota]\n"
        'unit = "点"\n'
        'source = "unknown"\n'
        "\n"
        "[account.health]\n"
        'state = "unknown"\n'
        "consecutive_failures = 3\n"
        'last_probe = "2026-10-25T09:00:00+08:00"\n'
        'last_checkin = "uncertain"\n'
    )
    path = tmp_path / "accounts.toml"
    path.write_text(tail, encoding="utf-8")
    data = pa.load_ledger(path, PLATFORMS, strict=False)
    acc = data["account"][-1]
    assert acc["platform"] == "workbuddy", acc["platform"]

    fetcher = FakeFetcher([(200, {"data": {"checked_in": False}})])
    rows = pa.run_checkin(
        data,
        PLATFORMS,
        apply=False,
        platform="workbuddy",
        environ={"TF_WORKBUDDY_TOKEN": "t"},
        fetcher=fetcher,
        sleep=lambda s: None,
        spacing=0,
    )
    health = acc.get("health") or {}
    assert [r["kind"] for r in rows] == [ck.INACTIVE]
    assert fetcher.writes == []
    # 许写的那个：时刻被刷新了
    assert health.get("last_probe") != "2026-10-25T09:00:00+08:00"
    # 不许动的三个：结论码、失败计数、额度样本
    assert health.get("last_checkin") == "uncertain"
    assert health.get("consecutive_failures") == 3
    assert not (acc.get("quota") or {}).get("samples")


def test_run_checkin_unknown_platform_is_not_supported_without_calls(tmp_path):
    text = LEDGER_TEXT.replace('platform = "workbuddy"', 'platform = "nowhere"')
    path = tmp_path / "accounts.toml"
    path.write_text(text, encoding="utf-8")
    data = pa.load_ledger(path, PLATFORMS, strict=False)
    fetched: list[str] = []

    def no_network(method, url, headers, body):
        fetched.append(url)
        return 200, "{}"

    rows = pa.run_checkin(
        data, PLATFORMS, apply=True, environ={}, fetcher=no_network, sleep=lambda s: None, spacing=0
    )
    assert rows[-1]["kind"] == ck.NOT_SUPPORTED
    assert "nowhere" in rows[-1]["detail"]
    assert fetched == []


def test_platform_filter_only_touches_that_platform(tmp_path):
    data = pa.load_ledger(make_ledger(tmp_path), PLATFORMS, strict=False)
    rows = pa.run_checkin(
        data,
        PLATFORMS,
        apply=True,
        platform="workbuddy",
        environ={"TF_WORKBUDDY_TOKEN": "t"},
        fetcher=FakeFetcher([(200, {"data": {"checked_in": True}})]),
        sleep=lambda s: None,
        spacing=0,
    )
    assert [r["id"] for r in rows] == ["workbuddy-1"]


def test_record_checkin_counts_failures_and_resets(tmp_path):
    data = pa.load_ledger(make_ledger(tmp_path), PLATFORMS, strict=False)
    acc = data["account"][0]
    pa._record_checkin(acc, {"id": acc["id"], "kind": ck.UNCERTAIN, "credit": 0.0}, "T1")
    pa._record_checkin(acc, {"id": acc["id"], "kind": ck.UNCERTAIN, "credit": 0.0}, "T2")
    assert acc["health"]["consecutive_failures"] == 2
    pa._record_checkin(acc, {"id": acc["id"], "kind": ck.CLAIMED, "credit": 1000}, "T3")
    assert acc["health"]["consecutive_failures"] == 0
    assert acc["health"]["last_checkin"] == ck.CLAIMED
    # amount 是「余额」，本次发放只进 samples
    assert "amount" not in acc["quota"]
    # ★ 判据 7：只有 `claimed` 才追加额度样本；两次 uncertain 一条都不许留
    assert [s["kind"] for s in acc["quota"]["samples"]] == [ck.CLAIMED]
    # 结论变了才记 `was`（一次扫描能看出「上次还是 uncertain」）
    assert acc["quota"]["samples"][-1] == {
        "at": "T3",
        "kind": ck.CLAIMED,
        "credit": 1000,
        "was": ck.UNCERTAIN,
    }


def test_save_ledger_round_trip_drops_read_side_fields(tmp_path):
    path = make_ledger(tmp_path)
    data = pa.load_ledger(path, PLATFORMS, strict=False)
    assert data["account"][0]["_platform_known"] is True
    pa.save_ledger(path, data)
    text = path.read_text(encoding="utf-8")
    assert "_platform_known" not in text
    again = pa.load_ledger(path, PLATFORMS, strict=False)
    assert [a["id"] for a in again["account"]] == ["codearts-1", "workbuddy-1"]


def test_archive_is_atomic_and_shaped(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "DATA_ROOT", tmp_path)
    payload = {"date": "2026-10-25", "applied": True, "results": [{"id": "a"}]}
    path = pa.write_checkin_archive("2026-10-25", payload)
    assert path == tmp_path / "gates" / "diag" / "checkin-2026-10-25.json"
    assert json.loads(path.read_text(encoding="utf-8"))["applied"] is True
    assert not list(path.parent.glob(".checkin-*"))  # 没有半成品残留


def test_archive_path_follows_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "DATA_ROOT", tmp_path)
    assert (
        pa._checkin_archive("2026-01-02") == tmp_path / "gates" / "diag" / "checkin-2026-01-02.json"
    )


def test_claim_endpoints_live_only_in_checkin_module():
    """卡 §2 的静态扫描：写端点只许出现在 `tools/pool/checkin.py`。

    判据不是「谁 import 了」而是**端点字符串的住所** —— 抄一份端点去别处发请求，
    等于绕开这里的三条硬规矩（幂等 / 不重试 / 留痕）。
    """
    tools = Path(__file__).resolve().parent.parent / "tools"
    endpoints = ("/v1/ops/claim", "daily-checkin", "checkin_credits/claim", "signin/claim")
    offenders = []
    for path in tools.rglob("*.py"):
        if path.name == "checkin.py":
            continue
        text = path.read_text(encoding="utf-8")
        for endpoint in endpoints:
            if endpoint in text:
                offenders.append(f"{path.name}:{endpoint}")
    assert offenders == []


# ------------------------------------------------- 判据 2：五个平台的「第二次跑」


def _two_rounds(claimer, responses):
    """同一账号连跑两次，返回 (首轮结论, 次轮结论, 请求次数)。"""
    fetcher = FakeFetcher(responses)
    first = claimer(fetcher)
    before = len(fetcher.calls)
    second = claimer(fetcher)
    return first.kind, second.kind, len(fetcher.calls) - before


def test_second_run_is_already_claimed_on_codearts():
    def run(fetcher):
        return ck.claim_codearts(ck.CodeArtsCredential("ak", "sk"), fetcher)

    first, second, _ = _two_rounds(
        run,
        [
            (200, package_response()),
            (200, delivery_response()),
            (200, ops_ok({"id": 1})),
            (200, ops_ok({})),
            (200, package_response()),
            (200, delivery_response(claimable=False, status="CLAIMED")),
        ],
    )
    assert (first, second) == (ck.CLAIMED, ck.ALREADY_CLAIMED)


def test_second_run_is_already_claimed_on_workbuddy():
    def run(fetcher):
        return ck.claim_workbuddy("t", fetcher)

    first, second, _ = _two_rounds(
        run,
        [
            (200, {"code": 0, "data": {"active": True, "today_checked_in": True}}),
            (200, {"code": 0, "data": {"active": True, "today_checked_in": True}}),
        ],
    )
    assert (first, second) == (ck.ALREADY_CLAIMED, ck.ALREADY_CLAIMED)


def test_second_run_is_already_claimed_on_trae():
    def run(fetcher):
        return ck.claim_trae("t", fetcher)

    first, second, _ = _two_rounds(
        run,
        [
            (200, {"code": 0, "data": {"checked_in": False}}),
            (200, {"code": 0, "message": "success"}),
            (200, {"code": 0, "credits": 100}),
            (200, {"code": 0, "data": {"checked_in": True}}),
        ],
    )
    assert (first, second) == (ck.CLAIMED, ck.ALREADY_CLAIMED)


def test_second_run_is_already_claimed_on_qoder():
    def run(fetcher):
        return ck.claim_qoder("t", fetcher)

    first, second, _ = _two_rounds(
        run,
        [
            (200, {"campaigns": [{"id": 7, "claimable": True}]}),
            (200, {"ok": True}),
            # 领取成功后活动列表仍非空：claimable 转 false，claimStatus 转 CLAIMED
            (200, {"campaigns": [{"campaignId": 7, "claimable": False, "status": "CLAIMED"}]}),
        ],
    )
    assert (first, second) == (ck.CLAIMED, ck.ALREADY_CLAIMED)


def test_second_run_is_already_claimed_on_minimax():
    def run(fetcher):
        return ck.claim_minimax("t", fetcher)

    first, second, _ = _two_rounds(
        run,
        [
            (200, {"base_resp": {"status_code": 0}, "data": {"is_today": False}}),
            (200, {"base_resp": {"status_code": 0}, "data": {"is_today": True, "status": 3}}),
            (200, {"base_resp": {"status_code": 0}, "data": {"is_today": True, "status": 3}}),
        ],
    )
    assert (first, second) == (ck.CLAIMED, ck.ALREADY_CLAIMED)


# ------------------------------------------------- 判据 4：同一天重复跑 = 覆盖


def test_archive_same_day_is_overwritten_not_appended(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "DATA_ROOT", tmp_path)
    pa.write_checkin_archive("2026-10-25", {"date": "2026-10-25", "results": [{"id": "a"}]})
    path = pa.write_checkin_archive("2026-10-25", {"date": "2026-10-25", "results": [{"id": "b"}]})
    assert json.loads(path.read_text(encoding="utf-8"))["results"] == [{"id": "b"}]
    assert len(list(path.parent.glob("checkin-*.json"))) == 1


# ------------------------------------------------- 判据 10：写入口唯一（AST 扫）


def test_only_cmd_checkin_reaches_the_apply_path():
    """静态 AST：能走到写动作的只有 `cmd_checkin` → `run_checkin` 这一条路。

    判据 9 的补强：端点字符串住在 `checkin.py` 只是"写代码归谁"，真正危险的是
    「`pool_accounts.py` 里多出一个函数顺手领一下」。这里按调用图钉死。
    """
    import ast

    src = (Path(__file__).resolve().parent.parent / "tools" / "pool_accounts.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(src)
    writers = {
        "claim_for_platform",
        "claim_codearts",
        "claim_workbuddy",
        "claim_qoder",
        "claim_trae",
        "claim_minimax",
    }

    def calls(node):
        found = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                fn = sub.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if name in writers:
                    found.add(name)
        return found

    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    callers = {name: sorted(calls(node)) for name, node in funcs.items() if calls(node)}
    assert callers == {"run_checkin": ["claim_for_platform"]}, callers
    # 再钉一层：run_checkin 只许被 cmd_checkin 调用
    run_callers = [
        name
        for name, node in funcs.items()
        if any(
            isinstance(sub, ast.Call)
            and getattr(sub.func, "id", getattr(sub.func, "attr", "")) == "run_checkin"
            for sub in ast.walk(node)
        )
    ]
    assert run_callers == ["cmd_checkin"], run_callers


# ---------------------------------------------------------------- 卡 E97：额度读数只认 total


def _metric(name: str, amount, used, remain):
    """一条 metric 的原样形状（真机 `statistics/plugin` 的 `metrics[]` 元素）。"""
    return {
        "name": name,
        "package_credit_amount": amount,
        "package_credit_used": used,
        "package_credit_remain": remain,
    }


def _package(*metrics):
    return {"is_credit_package": True, "is_token_package": False, "metrics": list(metrics)}


#: 2026-11-09 真机读到的六个 metric（照抄，一位小数都不改）。
REAL_METRICS = (
    _metric("usageDataChatMessages", None, None, None),
    _metric("usageTokenChatMessages", None, None, None),
    _metric("usageTotalPackageCredit", 9000.0, 4185.59, 4814.41),
    _metric("usageBasicPackageCredit", 0, 0, 0),
    _metric("usageOnDemandPackageCredit", 0, 0, 0),
    _metric("usageBonusPackageCredit", 9000.0, 4185.59, 4814.41),
)


def test_codearts_package_used_matches_real_reading():
    """卡 E97 ①：`usageTotalPackageCredit` 那一条 ⇒ 46.50655555555556。"""
    assert ck.codearts_package_used(_package(*REAL_METRICS)) == pytest.approx(46.50655555555556)
    assert ck.codearts_package_remain(_package(*REAL_METRICS)) == pytest.approx(4814.41)


def test_codearts_package_used_never_sums_categories():
    """卡 E97 ① 反向：三类都与 total 同值时**仍** 46.51（不是 3 倍）。

    立卡时记的形状（basic / ondemand / bonus 都与 total 同值）：真照「求和」写，
    `used` 会变成 3 × 4185.59 ⇒ 139.5%（或除以 3 倍 amount 时看着对、换个形状就错）。
    """
    all_same = (
        _metric("usageTotalPackageCredit", 9000.0, 4185.59, 4814.41),
        _metric("usageBasicPackageCredit", 9000.0, 4185.59, 4814.41),
        _metric("usageOnDemandPackageCredit", 9000.0, 4185.59, 4814.41),
        _metric("usageBonusPackageCredit", 9000.0, 4185.59, 4814.41),
    )
    assert ck.codearts_package_used(_package(*all_same)) == pytest.approx(46.50655555555556)
    # 今日真机形状：basic / ondemand 是 0，只有 bonus 与 total 同值 ⇒ 仍 46.51。
    # （把 bonus 那份 used 也加进来再除以 total 的 amount，就会得到 ~93% 这种假读数。）
    assert ck.codearts_package_used(_package(*REAL_METRICS)) == pytest.approx(46.50655555555556)


@pytest.mark.parametrize(
    "metrics",
    [
        # 只有分类、没有 total：不许回退成求和 ⇒ 不知道
        (
            _metric("usageBasicPackageCredit", 9000.0, 4185.59, 4814.41),
            _metric("usageBonusPackageCredit", 9000.0, 4185.59, 4814.41),
        ),
        # total 在，但 amount 是 0 ⇒ 除不了（真机 basic/ondemand 就是 0/0）
        (_metric("usageTotalPackageCredit", 0, 0, 0),),
        # used > amount：自相矛盾
        (_metric("usageTotalPackageCredit", 100.0, 120.0, 0.0),),
        # 负数
        (_metric("usageTotalPackageCredit", 100.0, -1.0, 101.0),),
        # 空串 / 缺键 / None
        (_metric("usageTotalPackageCredit", "", "", ""),),
        ({"name": "usageTotalPackageCredit"},),
        (_metric("usageTotalPackageCredit", None, 1.0, 1.0),),
        # bool 不是数（`True` 会被 Python 当 1）
        (_metric("usageTotalPackageCredit", True, 1, 0),),
    ],
)
def test_codearts_package_used_says_unknown_on_bad_shapes(metrics):
    """卡 E97 ①：算不出来就 `None`（= 不知道），绝不回 0、绝不求和。

    ★ 这里只管**百分比**。`package_credit_remain` 是另一格读数，它的合法性不依赖
      `used / amount` 那一对（余额 0 是真读数，不是「没读到」）—— 单独钉在下面。
    """
    assert ck.codearts_package_used(_package(*metrics)) is None


@pytest.mark.parametrize(
    ("metric", "expect"),
    [
        (_metric("usageTotalPackageCredit", 9000.0, 4185.59, 4814.41), pytest.approx(4814.41)),
        (_metric("usageTotalPackageCredit", 0, 0, 0), 0.0),
        (_metric("usageTotalPackageCredit", 9000.0, 1.0, ""), None),
        (_metric("usageTotalPackageCredit", 9000.0, 1.0, None), None),
        (_metric("usageTotalPackageCredit", 9000.0, 1.0, True), None),
        ({"name": "usageTotalPackageCredit"}, None),
        # 只有分类、没有 total ⇒ 不许拿分类的余额凑数
        (_metric("usageBonusPackageCredit", 9000.0, 4185.59, 4814.41), None),
    ],
)
def test_codearts_package_remain_is_only_the_total_row(metric, expect):
    """`amount` = total 那条的 `package_credit_remain`；读不到 ⇒ `None`（不从别处反算）。"""
    assert ck.codearts_package_remain(_package(metric)) == expect


@pytest.mark.parametrize("package", [None, {}, {"metrics": None}, {"metrics": {}}, "x", []])
def test_codearts_package_used_tolerates_garbage(package):
    assert ck.codearts_package_used(package) is None
    assert ck.codearts_package_remain(package) is None


def test_codearts_package_remain_is_balance_not_total():
    """`amount` 是**余额**口径：取 `package_credit_remain`，不是套餐总额 9000。"""
    package = _package(_metric("usageTotalPackageCredit", 9000.0, 4185.59, 4814.41))
    assert ck.codearts_package_remain(package) == pytest.approx(4814.41)
    assert ck.codearts_package_remain(package) != pytest.approx(9000.0)
    # 上游没给 remain ⇒ 不知道（不从 amount - used 反算）
    no_remain = _package(
        {
            "name": "usageTotalPackageCredit",
            "package_credit_amount": 9000.0,
            "package_credit_used": 1.0,
        }
    )
    assert ck.codearts_package_remain(no_remain) is None
