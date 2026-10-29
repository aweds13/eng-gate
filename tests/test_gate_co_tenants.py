"""卡 E65 / T-AG524：抢 CPU 的时候，红门不算数（但要标出来、并留着读数）。

五条判据各一组用例，且每组都有「把产品改回老写法 ⇒ 这组必红」的反向验证
（见卡规格 §反向验证 的实测命令与输出）：

1. `co_tenants` 采集**失败要显式说没采到**，不许写 0 蒙人；
2. 症状像「等不到东西」的红门要标 `SUSPECT`，且**只标不改判**（`exit_code` 一字不动）；
3. `SUSPECT` **不是绿**：`judge().ok` 仍 `False`、`state == "suspect"`、整趟 `gates_ok` 仍 `False`；
4. `SUSPECT` 必须带读数与理由 —— 缺 `co_tenants` / 缺 `suspect_reason` / 明明 `exit_code=0`
   却标怀疑，三种都是「想把红洗干净」⇒ 判红（比不标更严重）；
5. 并发度**不是免罪符**：`co_tenants` 多大都不能把 `ok` 变成 `True`。

★ 本文件不许 mock 判据本体（`judge()` / `gates_ok()` / `mark_suspect_rows()` 都真跑）：
  判据要是能被桩替掉，钉子咬的就只是桩。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tools"))

import gate_verdict as gv  # noqa: E402  三把尺子共用的那一份判据
import run_gates as rg  # noqa: E402  本地尺子（co_tenants 采集 + SUSPECT 标注在这）


def _payload(rows: list[dict], **extra) -> dict:
    base = {
        "host": "test-host",
        "rev": "abc1234",
        "not_run": [],
        "gates": rows,
    }
    base.update(extra)
    return base


def _red_row(**kw) -> dict:
    row = {
        "name": "ui_flow",
        "exit_code": 1,
        "blocking": True,
        "summary": "⑮ 能关掉跳转 —— 等了约 12s",
    }
    row.update(kw)
    return row


def _green_rows() -> list[dict]:
    return [{"name": "pytest", "exit_code": 0, "blocking": True, "summary": "ok"}]


# ---------------------------------------------------------------- 判据 1：采集失败要说得出口


def test_a_failed_collection_says_so_instead_of_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """没有 psutil（或枚举炸了）⇒ `collected=False` + 理由，**不许**返回 `like=0`。

    反向验证（把采集改成「失败即 0」）：把 `co_tenant_snapshot()` 的异常分支改成
    `return {"collected": True, "like": 0, "self_pid": me}` ⇒ 本条必红。
    """
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "psutil":
            raise ImportError("没有 psutil")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    snap = rg.co_tenant_snapshot()
    assert snap["collected"] is False
    assert "like" not in snap, "「没采到」不许伪装成「确实没有」"
    assert snap["reason"]


def test_a_real_collection_carries_the_reading() -> None:
    """能采的时候必须有 `like` 这个数（不要求它是多少）。"""
    pytest.importorskip("psutil")
    snap = rg.co_tenant_snapshot()
    assert snap["collected"] is True
    assert isinstance(snap["like"], int)


# ---------------------------------------------------------------- 判据 2：只标不改判


def test_a_timeout_shaped_red_door_is_marked_suspect() -> None:
    rows = _green_rows() + [_red_row()]
    snap = {"collected": True, "like": 3, "self_pid": 1}
    rg.mark_suspect_rows(rows, snap)
    red = rows[1]
    assert red["status"] == "SUSPECT"
    assert red["co_tenants"] == snap
    assert red["suspect_reason"]


def test_marking_does_not_touch_the_verdict_fields() -> None:
    """标 `SUSPECT` 只加字段：`exit_code` / `blocking` 一个字都不许动。"""
    rows = [_green_rows()[0], _red_row()]
    before = (rows[1]["exit_code"], rows[1]["blocking"])
    rg.mark_suspect_rows(rows, {"collected": True, "like": 1, "self_pid": 1})
    assert (rows[1]["exit_code"], rows[1]["blocking"]) == before
    assert rg.gates_ok(rows) is False, "标了 SUSPECT 也不许整趟变通过"


def test_an_assertion_mismatch_is_not_marked_suspect() -> None:
    """断言值不符是代码错，机器再忙也只该更慢 —— 不许拿它当「忙」。"""
    rows = [_green_rows()[0], _red_row(summary="能关掉跳转 —— 实际 false，期望 true")]
    rg.mark_suspect_rows(rows, {"collected": True, "like": 9, "self_pid": 1})
    assert "status" not in rows[1]


def test_a_green_door_is_never_marked_suspect() -> None:
    rows = [_green_rows()[0]]
    rg.mark_suspect_rows(rows, {"collected": True, "like": 9, "self_pid": 1})
    assert "status" not in rows[0]


# ---------------------------------------------------------------- 判据 3 / 5：SUSPECT 不是绿


def test_suspect_is_its_own_state_and_still_not_ok() -> None:
    rows = _green_rows() + [_red_row()]
    rg.mark_suspect_rows(rows, {"collected": True, "like": 2, "self_pid": 1})
    verdict = gv.judge(_payload(rows))
    assert verdict.ok is False, "SUSPECT 不许当绿"
    assert verdict.state == gv.SUSPECT
    assert verdict.state != gv.RED, "机器忙与代码错必须分得开"
    assert verdict.problems and "同机" in verdict.problems[0]


def test_a_bigger_co_tenant_count_is_not_a_pardon() -> None:
    """判据 5：同租户再多，`ok` 也不许翻成 `True`。"""
    for like in (0, 1, 4, 64):
        rows = _green_rows() + [_red_row()]
        rg.mark_suspect_rows(rows, {"collected": True, "like": like, "self_pid": 1})
        assert gv.judge(_payload(rows)).ok is False


def test_a_hard_red_beside_a_suspect_row_stays_red() -> None:
    """既有真红又有嫌疑红 ⇒ 状态必须是 RED（不许被「忙」稀释）。"""
    rows = [
        _green_rows()[0],
        _red_row(),
        {"name": "ruff", "exit_code": 1, "blocking": True, "summary": "E501 line too long"},
    ]
    rg.mark_suspect_rows(rows, {"collected": True, "like": 2, "self_pid": 1})
    verdict = gv.judge(_payload(rows))
    assert verdict.ok is False
    assert verdict.state == gv.RED


# ---------------------------------------------------------------- 判据 4：想洗干净 ⇒ 判红


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (lambda r: r.pop("co_tenants"), "co_tenants"),
        (lambda r: r.pop("suspect_reason"), "suspect_reason"),
        (lambda r: r.update(exit_code=0), "没红就不许标怀疑"),
    ],
    ids=["缺读数", "缺理由", "没红也标"],
)
def test_a_suspect_row_without_evidence_is_red(mutate, needle: str) -> None:
    """带 `SUSPECT` 却缺证据 ⇒ **红**（不是 suspect、不是绿）。"""
    rows = _green_rows() + [_red_row()]
    rg.mark_suspect_rows(rows, {"collected": True, "like": 2, "self_pid": 1})
    mutate(rows[1])
    verdict = gv.judge(_payload(rows))
    assert verdict.ok is False
    assert verdict.state == gv.RED
    assert any(needle in p for p in verdict.problems), verdict.problems
