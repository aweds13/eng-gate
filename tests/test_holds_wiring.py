"""卡 A369（T-AG654）：整窗用量估算接进派活面 —— 薄层侧的判据钉子。

判据 1（唯一判据源）：`tools/pool/holds_wiring.py` 只准调 `holds.estimate()` 与
`holds.holds_bounds()`，源码里不许出现 `scale = 100 / used` 那类字面除法。

判据 2（核心）：账本没有 `used_percent`（缺键 / None / 非有限）⇒ 那一窗 `why == "-"`、
`tokens == 0`、`why_text` 非空；**不许** `used=0.0`、**不许** `why == "low"`、
**不许**「`tokens=0` 但 `why == ""`」宣称整窗 0。

判据 4：`tools/wb_dispatch.py` 的 `[整窗]` 留痕段在占树之前 —— 没料（`why == "-"`）
**只留痕、不拒派**（拒绝分支本轮未接，见卡规格「未坐实项」第三条）。

判据 5：`routed_tokens` 只许来自 `tools/wb_dispatch.py::usage_in()` —— 本模块 import 它、
且不自己 `open()` 那份 jsonl。

★ 本文件刻意不带 `# noqa`：`tools/` 的挂载与兄弟模块的 import 都放进函数体，
  `sys.path` 的挂载不触发 E402。（判据 2·② 与卡规格原话有一处偏差，见那条用例的
  docstring：账本层拒的是**越界**，0 是合法值、由 `HOLDS_FLOOR` 挡。）
"""

from __future__ import annotations

import ast
import datetime as dt
import json
import math
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TZ = dt.timezone(dt.timedelta(hours=8))
NOW = dt.datetime(2026, 10, 12, 12, 0, tzinfo=TZ)


# --------------------------------------------------------------------------- 装载
def _tools_on_path() -> None:
    """把 `tools/` 挂上（本仓禁 `# noqa`，所以挂载只能放函数里）。"""
    path = str(ROOT / "tools")
    if path not in sys.path:
        sys.path.insert(0, path)


def _wiring():
    """薄层：账本 → 窗口的搬运（卡 A369 新增的那一份）。"""
    _tools_on_path()
    from pool import holds_wiring

    return holds_wiring


def _holds():
    """判据层（算式与五因顺序的唯一一份，本卡一个字节都不改）。"""
    _tools_on_path()
    from pool import holds

    return holds


def _pa():
    """账本读入 / 校验（`used_percent` 的唯一校验在它那里）。"""
    _tools_on_path()
    import pool_accounts

    return pool_accounts


def _twd():
    """兄弟测试模块：复用它的沙箱夹具与号池桩（判据 4 要真跑一趟 `main()`）。"""
    for extra in (ROOT / "tests", ROOT / "tools"):
        path = str(extra)
        if path not in sys.path:
            sys.path.insert(0, path)
    import test_wb_dispatch

    return test_wb_dispatch


# --------------------------------------------------------------------------- 夹具
def _account(ident: str = "codearts-1", **quota: object) -> dict:
    """一条 `[[account]]` 的字典形状（账本里读出来就是 dict）。"""
    account: dict = {
        "id": ident,
        "label": "样例号",
        "platform": "codearts",
        "state": "active",
        "added_at": "2026-10-01",
        "approved_models": ["huaweicloud-maas/deepseek-v4.1-flash"],
    }
    if quota:
        account["quota"] = quota
    return account


LEDGER_NO_QUOTA = (
    '[[account]]\n'
    'id = "codearts-1"\n'
    'label = "样例号"\n'
    'platform = "codearts"\n'
    'state = "active"\n'
    'added_at = "2026-10-01"\n'
    'approved_models = ["huaweicloud-maas/deepseek-v4.1-flash"]\n'
    '\n'
    '[account.credential]\n'
    'kind = "file"\n'
    'locator = "~/.codeartsdoer/pool.env"\n'
    '\n'
    '[account.quota]\n'
    'unit = "credits"\n'
    'source = "unknown"\n'
)


def _ledger_with_used(tmp_path: pathlib.Path, used: object) -> pathlib.Path:
    """造一份带 `used_percent` 的账本（越界 / 非数要验账本层的拒）。"""
    path = tmp_path / "accounts.toml"
    path.write_text(LEDGER_NO_QUOTA + f"used_percent = {used}\n", encoding="utf-8")
    return path


def _poison(*_a: object, **_k: object):
    """没有窗口边界时**不许**去碰日志：真碰了就该在这里炸。"""
    raise AssertionError("没有窗口边界却去读了日志 —— 分子与日志起点都不该取")


@pytest.fixture
def wired(tmp_path: pathlib.Path, monkeypatch) -> pathlib.Path:
    """沙箱 + 号账本（`demo` → `codebuddy-demo`，**没有 quota 段**）+ 假号池工具。"""
    twd = _twd()
    sandbox = pathlib.Path(twd.sandbox.__wrapped__(tmp_path, monkeypatch))
    ledger = twd._ledger_with_profiles(
        sandbox, ("codebuddy-demo", "demo", "~/codebuddy-accounts/demo"))
    twd._use_ledger(monkeypatch, ledger)
    stub = twd._account_stub(sandbox, {"demo": twd._demo_vars()})
    monkeypatch.setenv("TF_ACCOUNT_SCRIPT", str(stub))
    monkeypatch.setenv("TF_POOL_LIMITS", str(sandbox / "no-such-limits.toml"))
    return sandbox


# --------------------------------------------------------------------------- 判据 1
def test_only_one_scale() -> None:
    """判据 1：算式只有一份（`tools/pool/holds.py`）；薄层里一个字面除法都不许有。"""
    wiring = _wiring()
    source = pathlib.Path(wiring.__file__).read_text(encoding="utf-8")
    assert "100 /" not in source, "薄层抄了 holds.py 的 scale = 100 / used"
    tree = ast.parse(source)
    divisions = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
    ]
    assert divisions == [], f"薄层里出现了 {len(divisions)} 处除法（算式只许在 holds.py）"
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "estimate" in called, "没有调 holds.estimate() ⇒ 算式多半被抄了一份"
    assert "holds_bounds" in called, "没有调 holds.holds_bounds() ⇒ 五因顺序多半被抄了一份"


# --------------------------------------------------------------------------- 判据 2
def test_missing_used_is_dash_not_zero(tmp_path: pathlib.Path, monkeypatch) -> None:
    """判据 2·①：账本没有 `used_percent` ⇒ `why == "-"`、`tokens == 0`、理由非空。"""
    wiring = _wiring()
    holds = _holds()
    pa = _pa()
    ledger = tmp_path / "accounts.toml"
    ledger.write_text(LEDGER_NO_QUOTA, encoding="utf-8")
    monkeypatch.setenv(wiring.LEDGER_ENV, str(ledger))
    monkeypatch.setattr(pa, "_approved_models_from_whitelist", lambda: None)
    reading = wiring.read_holds(ROOT, now=NOW)
    assert reading.rows is not None and len(reading.rows) == 1, reading
    row = reading.rows[0]
    assert row["why"] == holds.HOLDS_UNKNOWN == "-", row
    assert row["why"] != holds.HOLDS_LOW, "「没观测过」不许冒充「已用比例太低」"
    assert row["tokens"] == 0 and row["cost"] == 0.0, f"没料就不许有数：{row!r}"
    assert row["why_text"], "没料也要说得出为什么（why_text 不许空）"
    assert row["why_text"] == holds.why_text("-")


@pytest.mark.parametrize(
    "quota",
    [None, {}, {"unit": "credits"}, {"used_percent": float("nan")},
     {"used_percent": float("inf")}],
)
def test_non_finite_used_is_dash_not_zero(quota: object, tmp_path: pathlib.Path) -> None:
    """判据 2·①：缺键 / None / 非有限 ⇒ 同一档 `"-"`（都不许被当成 0）。"""
    wiring = _wiring()
    holds = _holds()
    account = _account()
    if quota is not None:
        account["quota"] = quota
    row = wiring.holds_row(account, root=tmp_path, now=NOW,
                           usage_in_fn=_poison, first_log_fn=_poison)
    assert row["why"] == "-", row
    used = row["used_percent"]
    assert used is None or not math.isfinite(used), f"非有限值不许被洗成数：{row!r}"
    assert row["tokens"] == 0 and row["why_text"] == holds.why_text("-")


def test_zero_used_is_refused_at_the_ledger(tmp_path: pathlib.Path, monkeypatch) -> None:
    """判据 2·②：分母坏掉的越界值在**账本层**就被拒（`_check_used_percent` 只有一份）。

    ★ 与卡规格原话的一处偏差（如实记）：卡上写「`used_percent = 0` 写账本 ⇒ `LedgerError`」，
      实文是 `not 0 <= percent <= 100` 才抛 ⇒ **0 是合法值**，由判据层的 `HOLDS_FLOOR`
      挡成 `"low"`（`0 < 5.0`），所以「除以零」在算式里根本到不了。两条都钉在这里。
    """
    wiring = _wiring()
    holds = _holds()
    pa = _pa()
    monkeypatch.setattr(pa, "_approved_models_from_whitelist", lambda: None)
    for bad in (-1, 101):
        ledger = _ledger_with_used(tmp_path, bad)
        with pytest.raises(pa.LedgerError):
            pa.load_ledger(ledger)
    ledger = _ledger_with_used(tmp_path, 0)
    monkeypatch.setenv(wiring.LEDGER_ENV, str(ledger))
    reading = wiring.read_holds(ROOT, now=NOW)
    assert reading.rows is not None
    row = reading.rows[0]
    assert row["used_percent"] == 0.0
    assert row["why"] == holds.HOLDS_LOW, f"0 已用 ⇒ 低于 HOLDS_FLOOR，不许估：{row!r}"
    assert row["tokens"] == 0


def test_real_ledger_all_dash_today(monkeypatch) -> None:
    """判据 2·③：**真账本**今天一个 `used_percent` 都没有 ⇒ 每个号都必须 `"-"`（不许造假变绿）。"""
    wiring = _wiring()
    holds = _holds()
    monkeypatch.delenv(wiring.LEDGER_ENV, raising=False)
    ledger = wiring.ledger_path_for(ROOT)
    if ledger is None:
        pytest.skip("这台机器上没有真账本（infra/pool/accounts.toml）⇒ 这一条没验证")
    reading = wiring.read_holds(ROOT, now=dt.datetime.now(TZ))
    assert reading.rows, f"真账本读出来了却零号：{reading.note}"
    for row in reading.rows:
        assert row["why"] == "-", f"{row['account']} 今天没有已用比例却给了 {row['why']!r}"
        assert row["tokens"] == 0, row
        assert row["why_text"] == holds.why_text("-"), row


# --------------------------------------------------------------------------- 判据 4
def test_wb_dispatch_holds_never_refuses_without_data(
        wired: pathlib.Path, monkeypatch, capsys) -> None:
    """判据 4：没料 ⇒ 只在 stdout 留一行 `[整窗]`，**零新增 problems、不拒派**。"""
    twd = _twd()
    dispatched: list[list[str]] = []
    monkeypatch.setattr(twd.wd, "run_worker", twd._fake_runner(dispatched))
    twd._spy_reserve(monkeypatch)
    twd._account_argv(monkeypatch, "--account", "demo", "--execute")
    code = twd.wd.main()
    out = capsys.readouterr()
    assert code == 0, f"缺读数不等于号坏了，不许拒派：{out.err}"
    assert "[FAIL]" not in out.err, f"没料那一档不许进 problems 出口：{out.err}"
    marks = [line for line in out.out.splitlines() if line.startswith("[整窗]")]
    assert len(marks) == 1, f"该留且只留一行 [整窗]：{out.out}"
    assert "why=-" in marks[0], f"留痕要念出原串：{marks[0]}"
    assert "不估：这一窗没有可估的东西" in marks[0], marks[0]
    assert dispatched, "这一趟本来就该真派活"


# --------------------------------------------------------------------------- 判据 5
def test_holds_wiring_uses_usage_in() -> None:
    """判据 5：分子只许来自 `wb_dispatch.usage_in` —— 薄层不自己读那份 jsonl。"""
    wiring = _wiring()
    source = pathlib.Path(wiring.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "wb_dispatch"
        for alias in node.names
    }
    assert "usage_in" in imported, f"薄层没有从 wb_dispatch import usage_in：{imported}"
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "wb_status" not in modules, f"薄层自己 import 了日志读入模块：{modules}"
    fetched = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "read_log_lines" not in fetched, f"薄层自己读了日志：{fetched}"
    opens = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "open"
    ]
    assert opens == [], "薄层自己 open() 了文件 ⇒ 分子 / 起点不再是唯一一份"


def test_numerator_equals_usage_in_on_the_same_log(
        tmp_path: pathlib.Path) -> None:
    """判据 5（等价性）：同一份 jsonl、同一段窗口 ⇒ 两边拿到的分子逐字相等。"""
    wiring = _wiring()
    twd = _twd()
    model = "huaweicloud-maas/deepseek-v4.1-flash"
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    rows: list[object] = [
        {"模型": model, "开始": "2026-10-12T09:30:00", "判决": "通过", "退出码": "0",
         "input_tokens": 10, "output_tokens": 5, "cache_read": 2},
        {"模型": model, "开始": "2026-10-12T11:00:00", "判决": "dry-run", "退出码": "0",
         "input_tokens": 1000, "output_tokens": 0, "cache_read": 0},
        {"模型": "other/model", "开始": "2026-10-12T10:30:00", "判决": "通过",
         "退出码": "0", "input_tokens": 999, "output_tokens": 0, "cache_read": 0},
        {"模型": model, "开始": "2026-10-12T13:00:00", "判决": "通过", "退出码": "0",
         "input_tokens": 777, "output_tokens": 0, "cache_read": 0},
        "坏行不是 JSON",
    ]
    text = "\n".join(
        row if isinstance(row, str) else json.dumps(row, ensure_ascii=False)
        for row in rows
    )
    (diag / "wb-usage.jsonl").write_text(text + "\n", encoding="utf-8")
    start = dt.datetime(2026, 10, 12, 9, 0, tzinfo=TZ)
    end = dt.datetime(2026, 10, 12, 12, 0, tzinfo=TZ)
    direct = twd.wd.usage_in(model, start, end, root=tmp_path)
    via_wiring = wiring.numerator(model, start, end, root=tmp_path)
    assert via_wiring == direct, f"两个分子不同源：{via_wiring} != {direct}"
    assert direct == (17, 0.0), f"分子口径（+08:00 / [start,end) / 排除 dry）：{direct}"

