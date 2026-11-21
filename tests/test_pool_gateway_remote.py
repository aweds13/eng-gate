r"""远端 provider 显式登记（卡 A375 / F82 · T-AG663）—— 六条判据里跟「远端」有关的那些位。

判据表见 `复盘/卡/卡A375-F82远端provider显式登记.md`；这里只写**会失败**的断言。

| 钉子 | 钉哪一位 |
|---|---|
| `test_remote_platform_is_registered_explicitly` | 判据 1：恰好一段显式登记 |
| `test_remote_address_never_derives_a_second_endpoint` | 判据 2：一址不派生 |
| `test_connect_failure_names_the_machine` | 判据 3(a)：连接层失败文案点名机器（真 socket，回环） |
| `test_remote_connect_failure_stops_after_one_seat` | 判据 3(b)：当场停 |
| `test_local_connect_failure_still_switches_seat` | 判据 3(b) 反面 |
| `test_default_remote_set_comes_from_the_real_table` | 不传 `remote=` ⇒ 现读真表 |
| `test_remote_token_comes_only_from_env` | 判据 4：凭据只走 `token_env`，取不到就报 |
| `test_no_gateway_key_or_identity_header_in_sources` | 判据 4/5：没有 key 形状、没有跨机身份头 |
| `test_cross_machine_identity_headers_canary` | 判据 5：身份头若被搬进来 ⇒ xpass ⇒ 红 |
| `test_no_remote_quota_paths_and_paths_stay_four` | 判据 5：`/v1/magpie/*` 零命中、`PATHS` 四条 |
| `test_loopback_boundary_not_moved` | 判据 5：`ALLOWED_HOSTS` 没放宽、非回环仍拒 |
| `test_wb_dispatch_has_no_transport_flags` | 判据 5：派活器无传输选项 |

★ 全部用桩 + 回环 socket：`forward` 是注入的，`ledger` / `endpoints` / `remote` 都是参数，
  号池目录造在 `tmp_path` 里 —— **一个字节都不出网**，也不往真的 `gates/diag/` 写。
  判据 3(a) 那一条真连一次 socket，但连的是 `127.0.0.1` 上一个只 listen 不 accept 的裸 socket。
"""

from __future__ import annotations

import datetime as dt
import json
import re
import socket
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import tomllib

if TYPE_CHECKING:
    from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from pool import gateway  # noqa: E402  —— tools/ 已在 sys.path 上

TOKEN = "gateway-unit-token"
MODEL = "huaweicloud-maas/GLM-5.2"
CHAT_URL = "https://chat.example.test/v1/chat/completions"
REMOTE = "remote-magpie"
REMOTE_ROOT = "https://magpie.example.test:3425"
REMOTE_CHAT = REMOTE_ROOT + "/v1/chat/completions"
REMOTE_TOKEN_ENV = "TF_POOL_REMOTE_MAGPIE_TOKEN"
SEAT_A = "codearts-1"
SEAT_B = "workbuddy-1"
NOW = dt.datetime(2026, 11, 9, 12, 0, 0, tzinfo=dt.timezone.utc)

PLATFORMS = ROOT / "tools" / "pool" / "platforms.toml"
GATEWAY = ROOT / "tools" / "pool" / "gateway.py"


# ---------------------------------------------------------------- 夹具


def _pool_dir(root: Path, *, approved: tuple[str, ...] = (MODEL,)) -> Path:
    """在 `root` 下造一个号池目录（锚点 + 批准集 + 快照）。**只写 tmp，不碰仓外那份。**"""
    pool = root / "infra" / "pool"
    pool.mkdir(parents=True, exist_ok=True)
    (pool / "pool_models.py").write_text("", encoding="utf-8")
    body = "".join(
        f'[[approved]]\npool = "codebuddy"\nmodel = "{name}"\n' for name in approved)
    (pool / "models.whitelist.toml").write_text(body, encoding="utf-8")
    snap = {"live": list(approved), "live_names": {}, "at": ""}
    (pool / "models.live.json").write_text(json.dumps(snap), encoding="utf-8")
    return pool


def _row(seat: str, *, platform: str = "codearts", state: str = "active",
         models: tuple[str, ...] = (MODEL,)) -> dict[str, Any]:
    return {"id": seat, "label": seat, "platform": platform, "state": state,
            "approved_models": list(models)}


@pytest.fixture()
def env(tmp_path: Path) -> Path:
    _pool_dir(tmp_path)
    return tmp_path


def _ledger(*rows: dict[str, Any]) -> dict[str, Any]:
    return {"account": [dict(row) for row in rows]}


def _run(env: Path, forward: Any, *,
         rows: tuple[dict[str, Any], ...] | None = None,
         endpoints: dict[str, list[str]] | None = None,
         **extra: Any) -> gateway.Outcome:
    """与 `tests/test_pool_gateway.py` 的 `_run` 同形，端点默认表缩到本卡用得上的范围。

    ★ 这里**不替** `remote` 兜默认值：要不要显式传，本身就是被测的那一位。
    """
    table = endpoints if endpoints is not None else {"codearts": [CHAT_URL]}
    return gateway.route_once(
        pool="codebuddy", model=MODEL, caller="alice", forward=forward,
        protocol=gateway.PROTOCOL_CHAT, body=b'{"model":"x"}', now=NOW, root=env,
        endpoints=table, rpm_limits={}, stamps={},
        ledger=_ledger(*(rows if rows is not None else (_row(SEAT_A),))),
        scopes={}, **extra)


class _BareSocket:
    """只 listen 不说话的裸 socket（非 HTTP）—— 占住一个回环端口，永不 accept。"""

    def __init__(self) -> None:
        self.sock: socket.socket | None = None
        self.port = 0

    def __enter__(self) -> _BareSocket:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        s.listen(1)  # 永不 accept、永不回话
        self.sock = s
        self.port = int(s.getsockname()[1])
        return self

    def __exit__(self, *exc: object) -> None:
        assert self.sock is not None
        self.sock.close()


class _Unreachable:
    """每次都回「连接层失败」（502 + 点名机器）—— 数一共被问了几次。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, bytes]] = []

    def __call__(self, model: str, account: str, url: str, payload: bytes) -> gateway.Reply:
        self.calls.append((model, account, url, payload))
        message = f"{gateway.CONNECT_FAILED} magpie.example.test:3425：<urlopen error timed out>"
        return gateway.Reply(
            status=502, headers={"Content-Type": "application/json"},
            body=json.dumps({"error": {"type": "api_error", "message": message}},
                            ensure_ascii=False).encode("utf-8"))


def _sources() -> str:
    """本卡碰过的两份**产品**源码（gateway.py + platforms.toml）拼起来，供零命中断言。"""
    return GATEWAY.read_text(encoding="utf-8") + PLATFORMS.read_text(encoding="utf-8")


# ================================================================ 判据 1：远端 = 显式登记的一段


def test_remote_platform_is_registered_explicitly() -> None:
    """判据 1：远端是平台表里**恰好一段**显式登记，八项齐全；其余九段一个字节都没动。"""
    data = tomllib.loads(PLATFORMS.read_text(encoding="utf-8"))
    rows = data["platform"]
    assert len(rows) == 10, sorted(rows)

    row = rows[REMOTE]
    assert row["remote"] is True, "远端是一个要写进表的事实，不是从 URL 形状里读出来的猜测"
    assert row["auth_kind"] == "bearer", "只做 bearer 直通"
    assert row["base_urls"] == [], "裸根故意不登记 —— 地址是端点，不是可以拼的零件"
    assert len(row["chat_urls"]) == 1, row["chat_urls"]
    assert gateway.endpoint_protocol(row["chat_urls"][0]) == "chat"
    assert re.match(r"^(github:[\w.-]+/[\w.-]+/\S+:\S+|local:\S+:\d+)$", row["source"])
    assert row["verified"] is True and row["token_env"].strip()

    for name, other in rows.items():
        if name == REMOTE:
            continue
        assert other["chat_urls"] == [], name
        assert other.get("remote") is not True, name


# ================================================================ 判据 2：一址不派生第二端点


def test_remote_address_never_derives_a_second_endpoint() -> None:
    """判据 2：`remoteMagpieEndpoints` 那套「剥后缀 + root+\"/v1\"」**不移植**。"""
    root = REMOTE_ROOT
    assert gateway.endpoint_protocol(root) == "", "裸根不是端点"
    url, why = gateway.pick_endpoint((root,), "chat", platform=REMOTE)
    assert url is None, "拿裸根拼一个 /v1 试试 = 猜，禁止"
    assert "不做协议翻译" in why

    assert gateway.endpoint_protocol(root + "/v1") == "", "magpie 那边会派生 /v1，本仓不派生"
    assert gateway.pick_endpoint((root + "/v1/messages",), "chat", platform=REMOTE)[0] is None

    one = REMOTE_CHAT
    assert gateway.pick_endpoint((one,), "chat", platform=REMOTE) == (one, "")
    assert gateway.pick_endpoint((one,), "messages", platform=REMOTE)[0] is None, "只做同协议直通"


# ================================================================ 判据 3：连不上 ⇒ 点名 + 不换号


def test_connect_failure_names_the_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 3(a)：只说「连不上」等于没说**哪台** —— 文案必须带 `urlsplit(url).netloc`。"""
    monkeypatch.setenv(REMOTE_TOKEN_ENV, "tkn")
    # 绕过「这个号在不在账本里」：本条钉的是**连接层**那一段文案，不是账本定位。
    monkeypatch.setattr(gateway, "_account_platform", lambda account: REMOTE)

    with _BareSocket() as bare:
        url = f"http://127.0.0.1:{bare.port}/v1/chat/completions"
        reply = gateway.forward_http("m", "seat", url, b"{}", timeout=0.3)

    assert reply.status == 502, reply.status
    body = reply.body.decode("utf-8")
    assert f"127.0.0.1:{bare.port}" in body, f"没点名机器：{body}"
    assert gateway.CONNECT_FAILED in body


def test_remote_connect_failure_stops_after_one_seat(env: Path) -> None:
    """判据 3(b)：远端的一次连接层失败之后，第二个号**一次都不许试**。"""
    fwd = _Unreachable()
    out = _run(env, fwd,
               rows=(_row("remote-1", platform=REMOTE), _row("remote-2", platform=REMOTE)),
               endpoints={REMOTE: [REMOTE_CHAT]},
               remote={REMOTE})
    assert len(fwd.calls) == 1, f"换号了 —— 把 120 秒超时又乘了一遍：{fwd.calls}"
    assert out.status == 502
    assert "全部候选都失败了" in out.body.decode("utf-8")


def test_local_connect_failure_still_switches_seat(env: Path) -> None:
    """判据 3(b) 的反面：**本地**平台的 502 仍换下一个号（这条分支只对远端生效）。"""
    fwd = _Unreachable()
    out = _run(env, fwd,
               rows=(_row(SEAT_A), _row(SEAT_B, platform="workbuddy")),
               endpoints={"codearts": [CHAT_URL], "workbuddy": [CHAT_URL]},
               remote={REMOTE})
    assert len(fwd.calls) == 2, f"本地平台不该被这条分支拦下：{fwd.calls}"
    assert out.status == 502


def test_default_remote_set_comes_from_the_real_table(env: Path) -> None:
    """不传 `remote=`（None）⇒ 现读真 platforms.toml，与 `endpoints` 同体例。"""
    fwd = _Unreachable()
    out = _run(env, fwd,
               rows=(_row("remote-1", platform=REMOTE), _row("remote-2", platform=REMOTE)),
               endpoints={REMOTE: [REMOTE_CHAT]})
    assert gateway._remote_platforms() == frozenset({REMOTE}), "真表里就该只有这一段"
    assert len(fwd.calls) == 1, f"默认没读到「哪些平台是远端」：{fwd.calls}"
    assert out.status == 502


# ================================================================ 判据 4：凭据只走 token_env


def test_remote_token_comes_only_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 4：取不到就报（点名 env 名），不猜、不读文件；取到就原样回。"""
    monkeypatch.delenv(REMOTE_TOKEN_ENV, raising=False)
    with pytest.raises(gateway.ConfigError) as ei:
        gateway.resolve_token(REMOTE)
    assert "凭据不在 env 里" in str(ei.value)
    assert REMOTE_TOKEN_ENV in str(ei.value), "报错必须点名是哪个 env"

    monkeypatch.setenv(REMOTE_TOKEN_ENV, "tkn")
    assert gateway.resolve_token(REMOTE) == "tkn"


def test_no_gateway_key_or_identity_header_in_sources() -> None:
    """判据 4/5：没有 magpie 的 key 形状、没有跨机身份头。

    ★ `compare_digest` **不在** 这份榜上：`gateway.py` 的 `bearer_ok` 本来就用它
      （判据 4 那条 grep 里「compare_digest / chmod」只对 `platforms.toml` 成立）。
      既有钉子 `tests/test_pool_accounts.py` 与 `tests/test_pool_callers.py` 都在原处，不放宽。
    """
    text = PLATFORMS.read_text(encoding="utf-8")
    for word in ("sk-magpie", "X-Magpie-", "compare_digest", "chmod"):
        assert word not in text, f"平台表里出现了 {word!r}"

    src = GATEWAY.read_text(encoding="utf-8")
    for word in ("sk-magpie", "X-Magpie-"):
        assert word not in src, f"网关里出现了 {word!r}"


# ================================================================ 判据 5：不移植的三块


@pytest.mark.xfail(strict=True, reason="F82 不移植跨机身份")
def test_cross_machine_identity_headers_canary() -> None:
    """判据 5 的金丝雀：`X-Magpie-Agent` / `X-Magpie-Via` **不移植**。

    现在必须是 xfail（= 那两条头在本仓并不存在）；真有人把它们搬进来，这条变成
    xpass ⇒ `strict=True` 当场判红，逼人回来重读判据 5。
    """
    text = _sources()
    assert "X-Magpie-Agent" in text, "不移植：本仓没有跨机身份头"
    assert "X-Magpie-Via" in text, "不移植：本仓没有跨机身份头"


def test_no_remote_quota_paths_and_paths_stay_four() -> None:
    """判据 5：`/v1/magpie/limit` 与 `/v1/magpie/quotas/*` 零命中；`PATHS` 仍恰好四条。"""
    for base in (ROOT / "tools", ROOT / "scripts"):
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in {".py", ".toml"}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for needle in ("magpie/limit", "magpie/quotas", "RemoteCardsPath"):
                assert needle not in text, f"{path} 里出现了 {needle!r}"

    assert set(gateway.PATHS) == {"/v1/chat/completions", "/v1/messages",
                                  "/v1/models", "/v1/pool/routes"}
    assert len(gateway.PATHS) == 4, "远端段**不**加第五条路径"


def test_loopback_boundary_not_moved() -> None:
    """判据 5：`ALLOWED_HOSTS` 没放宽、`build_server` 仍拒非回环（远端是**连出**）。"""
    assert frozenset({"127.0.0.1", "localhost", "::1"}) == gateway.ALLOWED_HOSTS
    assert gateway.DEFAULT_HOST == "127.0.0.1"
    with pytest.raises(gateway.ConfigError):
        gateway.build_server(host="0.0.0.0", port=0, token=TOKEN)


def test_wb_dispatch_has_no_transport_flags() -> None:
    """判据 5：派活器没有 `--host/--ssh/--remote/--transport` —— 远端 provider 不改派活路径。

    ★ 读**真 parser**（不读源码文本），且按**整串**比：`--resume` 在，不能用子串匹配。
    """
    import wb_dispatch  # noqa: PLC0415 —— 只为读它的 parser；模块导入较慢，不放文件头

    parser = wb_dispatch.build_parser()
    options = {opt for action in parser._actions for opt in action.option_strings}
    for banned in ("--host", "--ssh", "--remote", "--transport"):
        assert banned not in options, banned
