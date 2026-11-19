"""卡 A369（T-AG654）：读数面第七块 `holds` 自己的判据钉子。

为什么单开一份：`tests/test_pipeline_view.py` 只钉「六块 → 七块」这一处投影（那文件原
属 207 / 249 / E26 / E115 / E59），第七块**自己的**判据在这里 —— 两件事分开写，
改一块不会顺手放松另一块。

判据 3（卡规格）：
  · `BLOCKS` 的 `holds` 块 + `_READERS` + `_report_holds()` 三处同步（只加一处会被
    `test_blocks_table_declares_seven_blocks` / `test_json_sources_and_fields_come_from_blocks`
    / `test_report_block_sources_match_blocks_and_json` 立刻拦下 —— 那三条按声明表遍历）。
  · 账本缺 / 账本零号 / 账本坏 ⇒ `--json` 与 `--report` **都不许抛**：缺什么说什么。
  · 行里必须有 `why`（判据层原串）与 `why_text`（人话）。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- 装载
def _sys_paths() -> None:
    """本仓禁 `# noqa` ⇒ `sys.path` 的挂载放进函数体（不触发 E402）。"""
    for extra in (ROOT / "tests", ROOT / "tools"):
        path = str(extra)
        if path not in sys.path:
            sys.path.insert(0, path)


def _pv():
    """读数面（本卡只加一块，判据一个字不在它里面）。"""
    _sys_paths()
    import pipeline_view

    return pipeline_view


def _tpv():
    """兄弟测试模块：复用它的最小假仓夹具与 `_run_cli`（同一条 CLI 口径）。"""
    _sys_paths()
    import test_pipeline_view

    return test_pipeline_view


def _wiring():
    """薄层：账本里那句「一个号都没有」的原话从这里来（不许两边各写一句）。"""
    _sys_paths()
    from pool import holds_wiring

    return holds_wiring


# --------------------------------------------------------------------------- 夹具
def _account(ident: str = "codearts-1", *, platform: str = "codearts",
             models: list[str] | None = None, with_used: float | None = None) -> str:
    """一段 `[[account]]` 的 TOML 文本（`with_used=None` ⇒ **不写** `used_percent`）。"""
    approved = models if models is not None else ["huaweicloud-maas/deepseek-v4.1-flash"]
    body = "".join([
        "[[account]]\n",
        f'id = "{ident}"\n',
        'label = "样例号"\n',
        f'platform = "{platform}"\n',
        'state = "active"\n',
        'added_at = "2026-10-01"\n',
        f"approved_models = [{', '.join(json_str(m) for m in approved)}]\n",
        "\n",
        "[account.credential]\n",
        'kind = "file"\n',
        f'locator = "~/.{ident}/pool.env"\n',
        "\n",
        "[account.quota]\n",
        'unit = "credits"\n',
        'source = "unknown"\n',
    ])
    if with_used is not None:
        body += f"used_percent = {with_used}\n"
    return body


def json_str(value: str) -> str:
    """TOML 里的一根字符串（本夹具只放 ASCII 标识符，不引 json 只为少一层依赖）。"""
    return '"' + value.replace('"', '') + '"'


def _ledger(tmp_path: pathlib.Path, body: str) -> pathlib.Path:
    """把账本落到仓**外**的位置（真账本就在仓外，读数面不许跟仓的相对路径绑定）。"""
    path = tmp_path / "ledger" / "accounts.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """最小假仓（`worktrees` 块要能读出来，其余块缺源也算「读得出来」）。"""
    tpv = _tpv()
    return pathlib.Path(tpv._full_fake_repo(tmp_path))


# --------------------------------------------------------------------------- 判据 3
def test_pipeline_view_holds_block_empty_ledger(
        repo: pathlib.Path, tmp_path: pathlib.Path, monkeypatch) -> None:
    """判据 3：账本在、但**一个号都没有** ⇒ 块有来源、行数 0、note 说清为什么。"""
    pv = _pv()
    wiring = _wiring()
    ledger = _ledger(tmp_path, "# 一个号都没有\n")
    monkeypatch.setenv(wiring.LEDGER_ENV, str(ledger))
    reading = pv.build_reading(repo)
    spec = {b["id"]: b for b in pv.BLOCKS}["holds"]
    assert reading["holds"] == [], f"零号账本 ⇒ 空表，不是 null：{reading.get('holds')!r}"
    assert reading["holds_source"] == spec["source"], "块级来源必须逐字来自声明表"
    note = reading.get("holds_note", "")
    assert note, "零号账本必须带一句说明（null 静默会被判据拦）"
    assert "一个号都没有" in note, note
    assert "整窗 0" in note, f"要明说「这不是整窗 0」：{note}"


def test_pipeline_view_holds_rows_carry_reason(
        repo: pathlib.Path, tmp_path: pathlib.Path, monkeypatch) -> None:
    """判据 3：一行读数必须同时带 `why`（原串）与 `why_text`（人话）。"""
    pv = _pv()
    wiring = _wiring()
    ledger = _ledger(tmp_path, _account("codearts-1"))
    monkeypatch.setenv(wiring.LEDGER_ENV, str(ledger))
    reading = pv.build_reading(repo)
    rows = reading["holds"]
    assert isinstance(rows, list) and rows, f"账本里有一个号，读数块就该有一行：{rows!r}"
    row = rows[0]
    assert row["why"] == "-", f"没有 used_percent ⇒ 原串就是「-」：{row!r}"
    assert row["why_text"], "只有原串没有人话 ⇒ 下一个读的人还得回来翻源码"
    assert row["why_text"] != row["why"], "why_text 是给人看的解释，不许回抄原串"
    assert row["tokens"] == 0 and row["cost"] == 0.0, f"没料就不许有数：{row!r}"
    assert set(row) == set({b["id"]: b for b in pv.BLOCKS}["holds"]["row_fields"]), (
        f"行字段必须与声明表逐字一致：{sorted(row)}")


def test_pipeline_view_holds_rows_are_ordered_like_the_ledger(
        repo: pathlib.Path, tmp_path: pathlib.Path, monkeypatch) -> None:
    """判据 3：一行一个号、顺序照账本（读数面不重排、不合并同一个号的多个窗口）。"""
    pv = _pv()
    wiring = _wiring()
    ledger = _ledger(
        tmp_path,
        _account("codearts-1") + "\n" + _account("workbuddy-1", platform="workbuddy",
                                                  models=[]),
    )
    monkeypatch.setenv(wiring.LEDGER_ENV, str(ledger))
    rows = pv.build_reading(repo)["holds"]
    assert [row["account"] for row in rows] == ["codearts-1", "workbuddy-1"]
    assert rows[1]["model"] == "", "没有批准模型的号，model 是空串（不许编一个）"


def test_missing_ledger_is_a_note_not_a_crash(
        repo: pathlib.Path, tmp_path: pathlib.Path, monkeypatch) -> None:
    """判据 3：**账本根本不在** ⇒ `holds=null` + 一句「没有账号账本」，读数面不许抛。"""
    pv = _pv()
    wiring = _wiring()
    monkeypatch.setenv(wiring.LEDGER_ENV, str(tmp_path / "nowhere" / "accounts.toml"))
    reading = pv.build_reading(repo)
    assert reading["holds"] is None
    assert reading["holds_note"] == wiring.MISSING_LEDGER_NOTE, (
        f"缺账本那一句只有一份（逐字复用薄层那句）：{reading.get('holds_note')!r}")
    assert pv.HOLDS_MISSING_NOTE == wiring.MISSING_LEDGER_NOTE, (
        "读数面的常量与薄层那句漂了 —— 两处各写一句迟早不一致")


def test_broken_ledger_does_not_break_the_reading(
        repo: pathlib.Path, tmp_path: pathlib.Path, monkeypatch) -> None:
    """判据 3：坏账本 ⇒ 照样出读数，但**点出原文**（不许静默成 null 也不许带崩）。"""
    pv = _pv()
    wiring = _wiring()
    ledger = _ledger(tmp_path, _account("codearts-1", with_used=101))
    monkeypatch.setenv(wiring.LEDGER_ENV, str(ledger))
    reading = pv.build_reading(repo)
    assert reading["holds"] is None
    note = reading.get("holds_note", "")
    assert "账号账本读不了" in note, note
    assert "used_percent" in note, f"坏在哪要念出来：{note}"


def test_cli_json_and_report_survive_both_ends(
        repo: pathlib.Path, tmp_path: pathlib.Path, monkeypatch) -> None:
    """判据 3：`--json` 与 `--report` 在「账本零号」与「账本坏了」两端都不许抛。"""
    tpv = _tpv()
    wiring = _wiring()
    cases = [
        ("# 一个号都没有\n", None),
        (_account("codearts-1", with_used=101), "读不了"),
    ]
    for body, expected in cases:
        monkeypatch.setenv(wiring.LEDGER_ENV, str(_ledger(tmp_path, body)))
        js = tpv._run_cli(repo, "--json")
        assert js.strip(), "CLI --json 一个字都没吐 ⇒ 抛了"
        report = tpv._run_cli(repo, "--report")
        assert "[holds]" in report, f"报告里必须有 holds 那一段：{report[-400:]}"
        if expected:
            assert expected in report, f"坏账本要在报告里点名：{report[-400:]}"


def test_json_identical_cold_then_hot(
        repo: pathlib.Path, tmp_path: pathlib.Path, monkeypatch) -> None:
    """判据 3：冷跑 / 热跑 --json **逐字节相同**（沿用 :163 的纪律；holds 不走缓存）。"""
    tpv = _tpv()
    wiring = _wiring()
    monkeypatch.setenv(wiring.LEDGER_ENV, str(_ledger(tmp_path, _account("codearts-1"))))
    cold = tpv._run_cli(repo, "--json")
    hot = tpv._run_cli(repo, "--json")
    assert cold == hot, "冷热两次 --json 不一致 ⇒ 读数不幂等"
    assert '"holds"' in cold, "冷跑里连 holds 键都没有"

