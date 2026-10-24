r"""分档门禁的复核口径（卡 E24 · `T-AG477`）。

为什么要有这一组钉子：`tools/wb_verify.check_gates` 原来把「应有门数」写死成**全量 19 道**
（`expected_gate_names(tree)`），而卡 A327 的 `--profiles auto` 允许一趟只跑**必需档**——
改了 `tools/` 的卡那一趟本来就只有 `audit+lang` = 8 道。两边一撞：**任何分档绿的树在跑全量
pytest 时都会被自己咬**（2026-10-25 E21 的落地就是这么红的，`land-E21.log` 里
`8 门（应有 19）`）。

口径（三条，别改语义）：
1. `gates/last.json` 里有 `profiles_run` ⇒ 期望集合**按那几档派生**（`run_gates.GATE_PROFILES`）；
2. 没有该字段（旧笔） / 写的是 `all` ⇒ 仍按**全量**核（fail closed，旧证据不许松）；
3. `profiles_run` 里出现不认识的档 ⇒ 判红「读不到应有的门数」，不许当成都跑过了。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "scripts"))

import run_gates as rg  # noqa: E402
import wb_verify as wv  # noqa: E402


def _payload(profiles: list[str] | None, names: list[str]) -> dict:
    data: dict = {
        "ok": True,
        "rev": "abc1234",
        "gates": [{"name": n, "exit_code": 0} for n in names],
        "not_run": [],
        "reused": {},
    }
    if profiles is not None:
        data["profiles_run"] = profiles
    return data


def _screen_with(monkeypatch: pytest.MonkeyPatch, payload: dict) -> wv.Screen:
    body = json.dumps(payload, ensure_ascii=False)

    def fake_git(tree: Path, *args: str) -> str:  # noqa: ANN001
        return body if args[:1] == ("show",) else "abc1234"

    monkeypatch.setattr(wv, "_git", fake_git)
    s = wv.Screen()
    wv.check_gates(s, ROOT, "abc1234")
    return s


def test_a_partial_profile_run_is_not_a_missing_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """① 分档绿（`audit+lang` 的 8 道）⇒ 不咬。这正是 E21 落地时被误咬的那一处。"""
    names = [n for n in rg.GATE_PROFILES["lang"] + rg.GATE_PROFILES["audit"]]
    s = _screen_with(monkeypatch, _payload(["audit", "lang"], names))
    assert s.fails == 0


def test_a_gate_missing_from_a_claimed_profile_still_bites(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """② 说了跑 `audit+lang` 却少一道 ⇒ 咬（不是"分档就什么都放过"）。"""
    names = list(rg.GATE_PROFILES["lang"] + rg.GATE_PROFILES["audit"])[1:]
    s = _screen_with(monkeypatch, _payload(["audit", "lang"], names))
    assert s.fails == 1


def test_a_red_gate_in_a_partial_run_still_bites(monkeypatch: pytest.MonkeyPatch) -> None:
    """③ 分档里有一道 `exit_code=1` ⇒ 咬「有门没过」（结论的 ok 字段骗不了判据）。"""
    names = list(rg.GATE_PROFILES["lang"] + rg.GATE_PROFILES["audit"])
    payload = _payload(["audit", "lang"], names)
    payload["gates"][0]["exit_code"] = 1
    s = _screen_with(monkeypatch, payload)
    assert s.fails >= 1


def test_old_evidence_without_profiles_run_is_still_checked_against_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """④ 旧笔没有 `profiles_run` ⇒ 仍按全量核（fail closed：老证据不许因为新规则变松）。"""
    names = list(rg.GATE_PROFILES["lang"] + rg.GATE_PROFILES["audit"])
    s = _screen_with(monkeypatch, _payload(None, names))
    assert s.fails == 1


def test_an_unknown_profile_name_is_not_treated_as_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """⑤ 档名不认识 ⇒ 判红（判不了 ≠ 都跑过了）。"""
    s = _screen_with(monkeypatch, _payload(["lang", "nonesuch"], list(rg.GATE_PROFILES["lang"])))
    assert s.fails == 1
