r"""刷新令牌只能有一个持有者（卡 A335 / T-AG537）的判据钉子。

为什么值当测：供应商的 refresh token 是**轮换**的 —— 两个持有者同时去刷，
第二个花掉的是第一个刚轮换掉的旧令牌，等于把刚拿到的凭据当场作废
（`internal/provider/logins_on.go:22-26`：「the second would spend a refresh
token the first just rotated」）。而「刷失败了要不要把号标记成吊销」更要命：
把 403 / 超时也当成吊销，一个好号会被永久打死；反过来把 401 当成「这一次没成」，
则会拿着死凭据一直撞。

| 钉子 | 判什么 | 会红在哪 |
|---|---|---|
| ① jwt_exp | 四条坏形状都回 None（非三段/坏 base64/无 exp/exp 非数） | 若抛异常或打印 token |
| ② needs_renew | 5 分钟余量：299⇒True、301⇒False；读不出⇒True；force⇒True | 若余量写错 |
| ③ refresh_failed | 只有 400/401 是 `RefreshRefused`；403/5xx/0 是 `RuntimeError` | 若混类型 |
| ④ saved_refresh_failed | 只有 Refused 写标记；其他异常账本**逐字节不变** | 若超时也写吊销 |
| ⑤ revoked_mark | 稳定、加盐会变、只存 sha256 前 16 位、不含明文 | 若存明文或哈希写错 |
| ⑥ mask_token | 只留 `header.payload` 前 6 字符 + `…`，其余 `<token>` | 若把 JWT 原样回显 |
| ⑦ renew_lock 串行 | 第一个没放锁之前，第二个拿不到（`held=False`） | 若锁没生效 |
| ⑧ renew_lock 超时 | ★ 反向钉子：拿不到锁**fail-open 回 False**，不许抛 | 若超时改 `raise` |

★ 导入口径照既有测试：把 `tools/` 挂上 `sys.path` 再 `import`。
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pool_accounts as pa  # noqa: E402 —— tools/ 已在 sys.path 上

#: 一份最小可读账本（`load_ledger` 会逐字段校验，缺 approved_models 直接抛）
LEDGER = """\
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
unit = "credits"
amount = 12
observed_at = "2026-10-25T09:00:00+08:00"
source = "codearts-credits"

[account.health]
state = "ok"
consecutive_failures = 0
"""

NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=pa.TZ)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _jwt(claims: dict) -> str:
    head = _b64(b'{"alg":"HS256","typ":"JWT"}')
    body = _b64(json.dumps(claims).encode("utf-8"))
    return f"{head}.{body}.{_b64(b'sig')}"


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    """tmp 里的一份账本；平台表用真的那份，批准集判据单独钉，不依赖宿主机。"""
    p = tmp_path / "infra" / "pool" / "accounts.toml"
    p.parent.mkdir(parents=True)
    p.write_bytes(LEDGER.encode("utf-8"))
    monkeypatch.setattr(pa, "_platforms_path", lambda: ROOT / "tools" / "pool" / "platforms.toml")
    monkeypatch.setattr(pa, "_approved_models_from_whitelist", lambda: None)
    return p


# ---------------------------------------------------------------- ① jwt_exp


def test_jwt_exp_reads_exp_and_none_for_junk():
    """读得出就读出来；**读不出来一律 None**（四条坏形状逐条钉）。"""
    assert pa.jwt_exp(_jwt({"exp": 1700000000})) == 1700000000.0
    assert pa.jwt_exp(_jwt({"exp": 1700000000.5})) == 1700000000.5

    # ① 非三段
    assert pa.jwt_exp("only-one-segment") is None
    assert pa.jwt_exp("two.segments") is None
    assert pa.jwt_exp("a.b.c.d") is None
    assert pa.jwt_exp("") is None
    # ② base64 坏 / 解不开（第二段不是 UTF-8）
    assert pa.jwt_exp("head.!!!!.sig") is None
    not_utf8 = base64.urlsafe_b64encode(b"\xff\xfe\x00").decode("ascii").rstrip("=")
    assert pa.jwt_exp("head." + not_utf8 + ".sig") is None
    # ③ 没有 exp
    assert pa.jwt_exp(_jwt({"sub": "account-1"})) is None
    # ④ exp 不是数
    assert pa.jwt_exp(_jwt({"exp": "1700000000"})) is None
    assert pa.jwt_exp(_jwt({"exp": None})) is None
    assert pa.jwt_exp(_jwt({"exp": True})) is None

    # ★ 不许把 token 片段漏进异常/日志：这里干脆不抛
    assert pa.jwt_exp("head.!!!!.sig") is None


# ------------------------------------------------------------- ② needs_renew


def test_needs_renew_uses_the_five_minute_margin():
    """`logins_on.go:275` 的 5 分钟余量：299 秒要刷、301 秒不刷。"""
    assert pa.RENEW_MARGIN_S == 5 * 60
    base = NOW.timestamp()
    assert pa.needs_renew(_jwt({"exp": base + 299}), now=NOW) is True
    assert pa.needs_renew(_jwt({"exp": base + 301}), now=NOW) is False
    assert pa.needs_renew(_jwt({"exp": base + 300}), now=NOW) is True  # 恰好卡在余量上
    assert pa.needs_renew(_jwt({"exp": base - 10}), now=NOW) is True
    # 读不出来的 JWT：**宁可多刷**，不许拿着可能过期的 token 去撞供应商
    assert pa.needs_renew("not-a-jwt", now=NOW) is True
    assert pa.needs_renew("", now=NOW) is True
    # force 恒 True（哪怕刚刷过）
    assert pa.needs_renew(_jwt({"exp": base + 86400}), force=True, now=NOW) is True
    # 余量可覆盖（SIWC 那条 3 分钟是另一个常量）
    assert pa.SIWC_MARGIN_S == 3 * 60
    assert pa.needs_renew(_jwt({"exp": base + 200}), now=NOW, margin_s=180) is False


# ---------------------------------------------------------- ③ refresh_failed


def test_refresh_failed_only_400_401_is_refused():
    """照 `account.go:867-872`：只有 400/401 是「供应商答复并拒绝」。"""
    for status in (400, 401):
        exc = pa.refresh_failed(status, "codearts", "invalid_grant")
        assert isinstance(exc, pa.RefreshRefused)
        assert not isinstance(exc, RuntimeError)  # 两个类型**不许混**（下游只认 Refused）
        assert "invalid_grant" in str(exc)
    for status in (403, 404, 500, 502, 503, 0):
        exc = pa.refresh_failed(status, "codearts", "boom")
        assert isinstance(exc, RuntimeError)
        assert not isinstance(exc, pa.RefreshRefused)
        assert f"HTTP {status}" in str(exc)
        assert "codearts" in str(exc)


# --------------------------------------------------- ④ saved_refresh_failed


def test_saved_refresh_failed_marks_only_on_refused(ledger):
    """「A refresh that never got an answer marks nothing.」—— 没答复就不留痕。"""
    before = ledger.read_bytes()

    # 非 Refused（5xx / 超时 / 403）：回 False，账本**一个字节都不许动**
    for status in (500, 0, 403):
        exc = pa.refresh_failed(status, "codearts", "boom")
        assert (
            pa.saved_refresh_failed(
                ledger, account_id="codearts-1", agent="codearts", exc=exc, now=NOW
            )
            is False
        )
        assert ledger.read_bytes() == before, f"HTTP {status} 竟然改了账本"

    # Refused：写吊销标记
    refused = pa.refresh_failed(401, "codearts", "invalid_grant")
    assert (
        pa.saved_refresh_failed(
            ledger, account_id="codearts-1", agent="codearts", exc=refused, now=NOW
        )
        is True
    )
    after = ledger.read_bytes()
    assert after != before
    text = after.decode("utf-8")
    assert "revoked " in text
    assert "invalid_grant" not in text  # ★ 明文不许落账本

    data = pa.load_ledger(ledger)
    acc = next(a for a in data["account"] if a["id"] == "codearts-1")
    assert acc["health"]["revoked"].startswith("revoked ")
    assert acc["health"]["revoked_at"] == "2026-05-01T12:00:00+08:00"
    # 改完还得是**能读回来的账本**（写坏比不写更糟）
    assert acc["state"] == "active"


# ------------------------------------------------------------ ⑤ revoked_mark


def test_revoked_mark_is_stable_and_salted():
    """只存 sha256 前 8 字节 hex（照 `quota_last.go:52-55 keyTag()`），永不存明文。"""
    mark = pa.revoked_mark("super-secret-reason")
    assert mark == pa.revoked_mark("super-secret-reason")  # 稳定
    assert mark.startswith("revoked ")
    assert len(mark) == len("revoked ") + 16
    assert "super-secret-reason" not in mark  # 不含明文
    # 与明文哈希逐位一致（不许是随手编的串）
    assert mark == "revoked " + hashlib.sha256(b"super-secret-reason").hexdigest()[:16]
    # 加盐 ⇒ 变（且盐在**前**：salt + reason）
    salted = pa.revoked_mark("super-secret-reason", salt="acc-1")
    assert salted != mark
    assert salted == "revoked " + hashlib.sha256(b"acc-1super-secret-reason").hexdigest()[:16]
    assert pa.revoked_mark("super-secret-reason", salt="acc-1") == salted
    # 不同原因不同标记
    assert pa.revoked_mark("a") != pa.revoked_mark("b")


# -------------------------------------------------------------- ⑥ mask_token


def test_mask_token_keeps_only_the_prefix():
    """JWT 打码：既有 `mask()` 只认 sk-/ak-/ghp-/xoxb-，**管不到 JWT**。"""
    token = _jwt({"exp": 1700000000})
    head, body, sig = token.split(".")
    masked = pa.mask_token(token)
    assert masked == (head + "." + body)[:6] + "…"
    assert masked.endswith("…")
    assert body not in masked  # 载荷不许整段漏出去
    assert sig not in masked
    # 既有 mask() 对 JWT 是空操作 —— 这正是另写一个的理由
    assert pa.mask(token) == token

    for junk in ("", "not-a-jwt", "two.segments", "head..sig"):
        assert pa.mask_token(junk) == "<token>"


# --------------------------------------------------------------- ⑦ renew_lock


def test_renew_lock_serialises_two_holders(tmp_path):
    """同一个账本**只能有一个持有者**：第一个没放手，第二个拿不到。"""
    lock_file = pa.renew_lock_file(tmp_path)
    started = threading.Event()
    release = threading.Event()
    held_by_first: list[bool] = []

    def first_holder() -> None:
        with pa.renew_lock("codearts-1", root=tmp_path, wait_s=1.0) as held:
            held_by_first.append(held)
            started.set()
            release.wait(10.0)

    thread = threading.Thread(target=first_holder)
    thread.start()
    try:
        assert started.wait(10.0), "第一个持有者没起来"
        assert lock_file.exists()
        # 锁文件吸附在**账本自己旁边**（不是按号一把）
        assert lock_file.parent == tmp_path / "infra" / "pool"
        assert lock_file.name == "accounts.toml.renew.lock"
        payload = json.loads(lock_file.read_text(encoding="utf-8"))
        assert {"owner", "pid", "task", "at"} <= set(payload)
        assert payload["task"] == "codearts-1"

        # ★ 第一个还没放锁 ⇒ 第二个必须拿不到（且 fail-open，不抛）
        with pa.renew_lock("wb-1", root=tmp_path, wait_s=0.05) as held2:
            assert held2 is False
    finally:
        release.set()
        thread.join(10.0)

    assert held_by_first == [True], "第一个持有者应当拿到锁"
    assert not lock_file.exists(), "放锁后锁文件必须清掉"
    # 前一个放手之后，下一个立刻能拿
    with pa.renew_lock("wb-1", root=tmp_path, wait_s=0.05) as held3:
        assert held3 is True
        assert lock_file.exists()
    assert not lock_file.exists()


# -------------------------------------------- ⑧ renew_lock 超时（反向钉子）


def test_renew_lock_timeout_is_fail_open(tmp_path, capsys):
    """★ 反向钉子：`wait_s` 内拿不到锁 ⇒ 说一行 + `yield False`，**绝不抛**。

    照 `filelock.go:57`：`another magpie held it for %v; going on without it`。
    把这里改成 `raise TimeoutError` 必须让本用例红（一次可用的刷新不该变成硬失败）。
    """
    lock_file = pa.renew_lock_file(tmp_path)
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    other = {"owner": "另一个持有者", "pid": 1, "task": "wb-1", "at": pa._iso(pa._now())}
    lock_file.write_text(json.dumps(other, ensure_ascii=False), encoding="utf-8")
    before = lock_file.read_bytes()

    started_at = time.monotonic()
    with pa.renew_lock("codearts-1", root=tmp_path, wait_s=0.2) as held:
        assert held is False  # ★ 不许抛 TimeoutError
        assert time.monotonic() - started_at < 5.0
    assert time.monotonic() - started_at >= 0.2  # 确实等过 wait_s

    err = capsys.readouterr().err
    assert "另一个持有者占了" in err
    assert "无锁继续" in err
    # 别人的锁不许被我删掉
    assert lock_file.read_bytes() == before
# ------------------------------------- ⑨ 陈旧只按时间判（不许 pid 探活）


def test_renew_lock_takes_over_only_by_age(tmp_path):
    """陈旧判定**只按时间**：`at` 超过 TTL ⇒ 接管；没超 ⇒ 老实等（不许 pid 探活）。

    `tools/pool/registry.py:18-30` 是硬禁令 —— Windows 上 `os.kill(pid, 0)` 走
    `TerminateProcess`，那不是探活，那是把真在跑的进程杀掉。
    """
    lock_file = pa.renew_lock_file(tmp_path)
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    assert pa.RENEW_LOCK_TTL_S == 120.0

    stale = {
        "owner": "早就死掉的持有者",
        "pid": 1,
        "task": "wb-1",
        "at": pa._iso(pa._now() - timedelta(seconds=pa.RENEW_LOCK_TTL_S * 5)),
    }
    lock_file.write_text(json.dumps(stale, ensure_ascii=False), encoding="utf-8")
    with pa.renew_lock("codearts-1", root=tmp_path, wait_s=1.0) as held:
        assert held is True, "超过 TTL 的锁必须按时间被接管"
        assert json.loads(lock_file.read_text(encoding="utf-8"))["task"] == "codearts-1"
    assert not lock_file.exists()

    fresh = dict(stale, at=pa._iso(pa._now()))
    lock_file.write_text(json.dumps(fresh, ensure_ascii=False), encoding="utf-8")
    with pa.renew_lock("codearts-1", root=tmp_path, wait_s=0.1) as held:
        assert held is False, "没过 TTL 的锁不许被接管"
    assert lock_file.exists()  # 别人的活锁不许删
    lock_file.unlink()
