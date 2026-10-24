"""卡归窗口的闸：没指纹放行、首次认领、别人的卡要 --take-over、释放后可再认领。

后半段是卡 E17 的钉子：`_save()` 对 Windows sharing violation（`WinError 32`）的有限重试，
以及「测试别去写仓库真账本」的隔离。
再往后是卡 E20 的钉子：临时文件名必须唯一、`FileNotFoundError` 也要重试
（`-n4` 门禁的假红根因）。
"""

from __future__ import annotations

import json
import os

import pytest

from tools import wb_session


def _use_tmp(tmp_path, monkeypatch):
    ledger = tmp_path / "leases.json"
    monkeypatch.setattr(wb_session, "LEDGER", ledger)
    return ledger


def test_no_session_id_always_allowed(tmp_path, monkeypatch):
    _use_tmp(tmp_path, monkeypatch)
    monkeypatch.delenv("DSH_SESSION_ID", raising=False)
    assert wb_session.claim("A1") == (True, "")
    assert not wb_session.LEDGER.exists(), "工人口径不该写租约"


def test_first_touch_claims(tmp_path, monkeypatch):
    ledger = _use_tmp(tmp_path, monkeypatch)
    monkeypatch.setenv("DSH_SESSION_ID", "sess-a")
    ok, msg = wb_session.claim("A2")
    assert ok and "认领" in msg
    assert json.loads(ledger.read_text(encoding="utf-8"))["cards"]["A2"]["session"] == "sess-a"


def test_other_session_is_blocked_until_take_over(tmp_path, monkeypatch):
    _use_tmp(tmp_path, monkeypatch)
    monkeypatch.setenv("DSH_SESSION_ID", "sess-a")
    wb_session.claim("A3")
    monkeypatch.setenv("DSH_SESSION_ID", "sess-b")
    ok, msg = wb_session.claim("A3")
    assert not ok and "另一个对话窗口" in msg
    ok2, msg2 = wb_session.claim("A3", take_over=True)
    assert ok2 and "换手" in msg2
    assert wb_session.owner("A3") == "sess-b"


def test_release_frees_the_card(tmp_path, monkeypatch):
    _use_tmp(tmp_path, monkeypatch)
    monkeypatch.setenv("DSH_SESSION_ID", "sess-a")
    wb_session.claim("A4")
    wb_session.release("A4")
    monkeypatch.setenv("DSH_SESSION_ID", "sess-c")
    ok, _ = wb_session.claim("A4")
    assert ok


# --------------------------------------------------- 卡 E17：写盘抖动 + 测试隔离


def _flaky_replace(monkeypatch, failures: int, exc: Exception | None = None) -> dict:
    """把 `os.replace` 换成桩：前 `failures` 次抛异常，之后走真实现。

    返回调用计数（`{"n": ...}`），让用例能证明「到底试了几次」。
    """
    real = os.replace
    calls = {"n": 0}

    def fake(src, dst):
        calls["n"] += 1
        if calls["n"] <= failures:
            raise exc or PermissionError(13, "另一个程序正在使用此文件", str(dst))
        return real(src, dst)

    monkeypatch.setattr(wb_session.os, "replace", fake)
    return calls


def test_save_retries_a_transient_sharing_violation(tmp_path, monkeypatch):
    """钉子 1：前两次 PermissionError、第三次成功 ⇒ `_save()` 成功且账本内容正确。"""
    ledger = _use_tmp(tmp_path, monkeypatch)
    calls = _flaky_replace(monkeypatch, failures=2)
    data = {"version": 1, "cards": {"A5": {"session": "sess-a", "since": 1}}}

    wb_session._save(data)

    assert calls["n"] == 3, f"应该试 3 次，实际 {calls['n']} 次"
    assert json.loads(ledger.read_text(encoding="utf-8")) == data


def test_save_raises_the_original_error_when_every_attempt_fails(tmp_path, monkeypatch):
    """钉子 2：三次都抛 ⇒ 原样抛 PermissionError，且不留半截 tmp。"""
    ledger = _use_tmp(tmp_path, monkeypatch)
    calls = _flaky_replace(monkeypatch, failures=10)

    with pytest.raises(PermissionError):
        wb_session._save({"version": 1, "cards": {}})

    assert calls["n"] == wb_session._SAVE_RETRIES, "失败后试的次数必须等于 _SAVE_RETRIES"
    assert not ledger.with_suffix(".tmp").exists(), "失败后不许留下半截 session-leases.tmp"
    assert not ledger.exists(), "一次都没换名成功，账本不该出现"


def test_only_permission_errors_are_retried(tmp_path, monkeypatch):
    """判据 2：别的异常（这里是 OSError 的父类情形）第一次就抛，不许重试。"""
    _use_tmp(tmp_path, monkeypatch)
    calls = _flaky_replace(monkeypatch, failures=10, exc=IsADirectoryError(21, "是个目录"))

    with pytest.raises(IsADirectoryError):
        wb_session._save({"version": 1, "cards": {}})

    assert calls["n"] == 1, "非 PermissionError 不该重试"


def test_one_retry_degrades_the_flaky_save(tmp_path, monkeypatch):
    """钉子 4（反空转）：把 `_SAVE_RETRIES` 改成 1 ⇒ 钉子 1 那个场景必须红。

    这不是「额外的用例」，是把「钉子 1 真咬重试」这件事本身钉死：少了重试，
    同样的抖动就得抛出去。
    """
    ledger = _use_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(wb_session, "_SAVE_RETRIES", 1)
    _flaky_replace(monkeypatch, failures=2)

    with pytest.raises(PermissionError):
        wb_session._save({"version": 1, "cards": {}})
    assert not ledger.exists()


def test_claim_writes_only_the_isolated_ledger(tmp_path, monkeypatch):
    """钉子 3：`LEDGER` 指到 tmp 上的假 `gates/diag/` ⇒ 真仓账本字节不变。"""
    real_ledger = wb_session.LEDGER
    before = real_ledger.read_bytes() if real_ledger.exists() else None

    fake = tmp_path / "gates" / "diag" / "session-leases.json"
    monkeypatch.setattr(wb_session, "LEDGER", fake)
    monkeypatch.setenv("DSH_SESSION_ID", "sess-a")
    ok, _ = wb_session.claim("A6")

    assert ok
    assert json.loads(fake.read_text(encoding="utf-8"))["cards"]["A6"]["session"] == "sess-a"
    after = real_ledger.read_bytes() if real_ledger.exists() else None
    assert after == before, f"真仓账本被写了：{real_ledger}"


def test_save_retries_when_its_own_tmp_was_swapped_away(tmp_path, monkeypatch):
    """卡 E20 钉子 1：`FileNotFoundError`（自己的 tmp 被别人换走了）也要重试，别直接抛。"""
    ledger = _use_tmp(tmp_path, monkeypatch)
    calls = _flaky_replace(monkeypatch, failures=2, exc=FileNotFoundError(2, "没了"))
    data = {"version": 1, "cards": {"A7": {"session": "sess-a", "since": 1}}}

    wb_session._save(data)

    assert calls["n"] == 3, f"FileNotFoundError 也该重试，实际只试了 {calls['n']} 次"
    assert json.loads(ledger.read_text(encoding="utf-8")) == data


def test_tmp_name_is_unique_per_write(tmp_path, monkeypatch):
    """卡 E20 钉子 2：临时文件名不许是固定的 `session-leases.tmp`。"""
    ledger = _use_tmp(tmp_path, monkeypatch)

    first, second = wb_session._tmp_path(), wb_session._tmp_path()

    assert first != second, "两次写盘不能共用同一个临时文件名（并发写会互相换走）"
    assert first != ledger.with_suffix(".tmp"), "不许再退回固定名 session-leases.tmp"
    assert first.parent == ledger.parent, "临时文件必须和目标同目录（同一卷才能原子换名）"


def test_concurrent_saves_keep_the_ledger_readable(tmp_path, monkeypatch):
    """卡 E20 钉子 3：两个线程同时写 20 次 ⇒ 不抛异常，最终账本仍是合法 JSON。

    旧实现（固定 tmp 名）在这条上会抛 `FileNotFoundError`（实测于 `-n 4` 的门禁里）。
    """
    import threading

    ledger = _use_tmp(tmp_path, monkeypatch)
    errors: list[BaseException] = []

    def writer(tag: str) -> None:
        for i in range(20):
            try:
                payload = {"version": 1, "cards": {f"{tag}{i}": {"session": tag, "since": 1}}}
                wb_session._save(payload)
            except BaseException as exc:  # noqa: BLE001 - 并发用例要把异常带回来断
                errors.append(exc)
                return

    threads = [threading.Thread(target=writer, args=(tag,)) for tag in ("t1", "t2")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"并发写抛了：{errors[:1]}"
    assert json.loads(ledger.read_text(encoding="utf-8"))["version"] == 1
    assert not list(ledger.parent.glob("*.tmp")), "并发写完后不该留下 tmp 文件"
