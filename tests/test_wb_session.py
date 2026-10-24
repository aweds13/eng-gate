"""卡归窗口的闸：没指纹放行、首次认领、别人的卡要 --take-over、释放后可再认领。"""

from __future__ import annotations

import json

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
