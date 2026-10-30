"""卡 A346 / T-AG548：配额历史曲线的钉子。

每条钉都对着卡 §1–§8 的判据。曲线是**纯判据**模块，所以钉子分三组：
判据本身（`new_cycle` / `add_point` / `prune` / `hist_key` / `point_of`）、
接入点（`record_probe_result` 之后记不记点）、以及两条「今天必须为空」的事实钉。

★ 一律注入 `root=tmp_path`，绝不摸真仓的 `gates/diag/`（卡 §6）。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from tools import pool_accounts as pa
from tools.pool import quota_history as qh

ROOT = Path(__file__).resolve().parent.parent

LEDGER = """
version = 1

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

[[account]]
id = "wb-1"
label = "WorkBuddy 主号"
platform = "workbuddy"
state = "active"
added_at = "2026-10-20"
approved_models = ["hunyuan/x"]

[account.credential]
kind = "dir"
locator = "~/.workbuddy"

[account.quota]
unit = "点"

[account.health]
state = "unknown"
"""


# ---------------------------------------------------------------- 夹具


@pytest.fixture()
def ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """账本写进 tmp，数据根与曲线出口全都钉在 tmp 上（曲线绝不许落到真仓）。"""
    path = tmp_path / "infra" / "pool" / "accounts.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(LEDGER, encoding="utf-8")
    monkeypatch.delenv("TF_ACCOUNTS_TOML", raising=False)
    monkeypatch.delenv(qh.ENV_HISTORY, raising=False)
    monkeypatch.setattr(pa, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(pa, "TOOL_ROOT", ROOT)
    monkeypatch.setattr(pa, "_approved_models_from_whitelist", lambda: None)
    return path


@pytest.fixture()
def curve(tmp_path: Path) -> Path:
    """曲线文件的预期落点：`<root>/gates/diag/quota-history.json`。"""
    return tmp_path.joinpath(*qh.HISTORY_REL)


def _point(at: int, left: float, *, start: int | None = None, resets: int | None = None):
    return qh.QuotaPoint(at=at, left=left, start=start, resets_at=resets)


def _probe(path: Path, rows: list[dict], *, hour: int = 12) -> None:
    """按真账本的形状跑一遍 `record_probe_result`（账本重读一次，与 CLI 同法）。"""
    data = pa.load_ledger(path)
    pa.record_probe_result(path, data, rows, now=datetime(2026, 10, 26, hour, 0, 0, tzinfo=pa.TZ))


# ---------------------------------------------------------------- new_cycle


def test_new_cycle_two_deadline_less_refill():
    """① 两个都没有 deadline ⇒ 只看剩余涨没涨，涨过 `REFILL_PCT` 才算新窗。"""
    a = _point(1000, 40.0)
    assert qh.new_cycle(a, _point(1060, 46.0)) is True  # 涨 6 > 5
    assert qh.new_cycle(a, _point(1060, 45.0)) is False  # 涨 5 不算（严格大于）
    assert qh.new_cycle(a, _point(1060, 44.9)) is False  # 只涨 4.9
    assert qh.new_cycle(a, _point(1060, 30.0)) is False  # 掉血不是新窗
    assert qh.REFILL_PCT == 5.0  # 判据 2：它必须是有名字的常量


def test_new_cycle_one_deadline_only():
    """② 只有一个有 deadline ⇒ 一定算新窗（一个窗开始了，或者结束了）。"""
    assert qh.new_cycle(_point(1000, 40.0), _point(1060, 40.0, resets=9000)) is True
    assert qh.new_cycle(_point(1000, 40.0, resets=9000), _point(1060, 40.0)) is True
    assert qh.new_cycle(_point(1000, 40.0, resets=9000), _point(1060, 45.0, resets=9000)) is False


def test_new_cycle_deadline_passed():
    """③ `a` 的终点已经过了 `b` 的读数时刻 ⇒ 重置时刻到了，一定是新窗。"""
    a = _point(1000, 10.0, resets=2000)
    assert qh.new_cycle(a, _point(2000, 10.0, resets=2000)) is True  # 正好相等也算过关
    assert qh.new_cycle(a, _point(2500, 10.0, resets=2000)) is True
    assert qh.new_cycle(a, _point(1500, 10.0, resets=2000)) is False  # 终点没到时不许误判


def test_new_cycle_rolling_window_is_not_a_new_cycle():
    """④ 终点跟着读数一起往前挪的是滚动窗 —— `rolling` 必须压住 ⑤ 的「涨了就是新窗」。"""
    a = _point(1000, 10.0, resets=4600)
    b = _point(1060, 50.0, resets=4660)  # 终点也后挪 60s，剩额猛涨
    assert b.resets_at - a.resets_at == b.at - a.at
    assert qh.new_cycle(a, b) is False


def test_new_cycle_backwards_jump_after_slack():
    """⑥ 兜底：终点大幅后挪 ⇒ 新窗；大幅前挪（越过 `SLACK_S`）⇒ 也算换了窗。"""
    a = _point(1000, 40.0, resets=9000)
    assert qh.new_cycle(a, _point(1060, 40.0, resets=9000 + 60 + qh.SLACK_S + 1)) is True
    assert qh.new_cycle(a, _point(1060, 40.0, resets=9000 + 60 + qh.SLACK_S)) is False
    assert qh.new_cycle(a, _point(1060, 40.0, resets=9000 - qh.SLACK_S - 1)) is True
    assert qh.new_cycle(a, _point(1060, 40.0, resets=9000 - qh.SLACK_S)) is False


# ---------------------------------------------------------------- add_point


def test_add_point_ignores_older_or_equal():
    """不比最后一个新（同刻且同值）⇒ 原样返回，且**不改入参**。"""
    pts = [_point(1000, 40.0), _point(1060, 39.0)]
    snapshot = list(pts)
    same_value = qh.add_point(pts, _point(1060, 39.0))
    assert same_value == snapshot
    assert same_value is not pts  # 永远回新列表
    assert qh.add_point(pts, _point(1000, 39.0)) == snapshot
    assert pts == snapshot  # 入参一个字节没动


def test_add_point_flat_line_moves_the_last_point():
    """相邻两点都平（`left` 差 < 0.05）⇒ 顶掉最后一个，不涨点数。"""
    pts = [_point(1000, 40.0), _point(1400, 40.01)]
    out = qh.add_point(pts, _point(1800, 40.02))
    assert out == [_point(1000, 40.0), _point(1800, 40.02)]
    assert pts == [_point(1000, 40.0), _point(1400, 40.01)]  # 入参没动


def test_add_point_within_gap_moves_the_last_point():
    """`point.at - p1.at < GAP_S`（两读同在一阵里）⇒ 顶掉最后一个。

    三点都只是缓慢掉血（涨不过 `REFILL_PCT`，谁也不是新窗），所以差别只在时间：
    隔 200s 顶掉、隔 600s 追加。
    """
    pts = [_point(1000, 40.0), _point(1100, 39.0)]
    out = qh.add_point(pts, _point(1200, 38.0))  # 1200-1000 < GAP_S
    assert out == [_point(1000, 40.0), _point(1200, 38.0)]
    far = qh.add_point(pts, _point(1600, 38.0))  # 隔着 600s ⇒ 正常追加
    assert far == [_point(1000, 40.0), _point(1100, 39.0), _point(1600, 38.0)]


def test_add_point_same_instant_different_cycle_appends():
    """`< SAME_S` 但**是新周期** ⇒ 不顶掉，追加（重置那一瞬必须留痕）。"""
    pts = [_point(1000, 10.0, resets=5000)]
    out = qh.add_point(pts, _point(1010, 90.0))  # 只有新点有 deadline ⇒ 新窗
    assert out == [_point(1000, 10.0, resets=5000), _point(1010, 90.0)]
    stay = qh.add_point(pts, _point(1010, 10.0, resets=5000))  # 同窗没涨 ⇒ 顶掉
    assert stay == [_point(1010, 10.0, resets=5000)]


# ---------------------------------------------------------------- prune


def test_prune_drops_beyond_kept_days():
    """`at < now - KEPT_DAYS*86400` 的丢掉；边界那条留着。"""
    now = 10_000_000
    cut = now - 45 * 86400  # 45 天硬写：从 `qh.KEPT_DAYS` 推的话，改常量测试会跟着改，咬不住
    pts = [_point(cut - 1, 10.0), _point(cut, 20.0), _point(now, 30.0)]
    assert qh.prune(pts, now=now) == [_point(cut, 20.0), _point(now, 30.0)]


def test_prune_keeps_at_most_max_points():
    """超过 6000（同样硬写）条 ⇒ 只留尾部。"""
    now = 10_000_000
    pts = [_point(now - i, 10.0) for i in range(6005, 0, -1)]
    out = qh.prune(pts, now=now)
    assert len(out) == 6000
    assert out[-1] == pts[-1]
    assert out[0] == pts[-6000]


# ---------------------------------------------------------------- hist_key


def test_hist_key_lowercases_account():
    """key = `"<scope>|<account 小写>"`；scope 不改（它大小写敏感）。"""
    assert qh.hist_key("codearts", "CodeArts-1") == "codearts|codearts-1"
    assert qh.hist_key("CodeArts", "ABC") == "CodeArts|abc"
    assert "ABC" not in qh.hist_key("codearts", "ABC")


# ---------------------------------------------------------------- point_of


def test_point_of_skips_unusable_windows():
    """五种不可画的窗口一律回 `None`（unlimited / aside 非池 / family / 无 name / used 非数）。"""
    at = 1_000_000
    base = {"name": "m1", "used": 30.0}
    got = qh.point_of(base, at=at)
    assert got is not None and got.at == at
    assert qh.point_of({**base, "unlimited": True}, at=at) is None
    assert qh.point_of({**base, "aside": True}, at=at) is None
    assert qh.point_of({**base, "aside": True, "pool": "p1"}, at=at) is not None  # 池窗不跳
    assert qh.point_of({**base, "family": "claude"}, at=at) is None
    assert qh.point_of({**base, "name": ""}, at=at) is None
    assert qh.point_of({**base, "used": "30"}, at=at) is None  # 字符串不是数
    assert qh.point_of({**base, "used": True}, at=at) is None  # bool 不是数
    assert qh.point_of({**base, "used": None}, at=at) is None
    assert qh.point_of("不是窗口", at=at) is None


def test_point_of_clamps_and_rounds():
    """`left = round(clamp(100 - used, 0, 100), 2)`；`start` 只在 `span > 0` 时写。"""
    at = 1_000_000
    assert qh.point_of({"name": "m", "used": 0.0}, at=at).left == 100.0
    assert qh.point_of({"name": "m", "used": 100.0}, at=at).left == 0.0
    assert qh.point_of({"name": "m", "used": 150.0}, at=at).left == 0.0  # 夹到 0
    assert qh.point_of({"name": "m", "used": -20.0}, at=at).left == 100.0  # 夹到 100
    # 第三位必须被 round 掉：100 - 33.333 = 66.667 → 66.67
    assert qh.point_of({"name": "m", "used": 33.333}, at=at).left == 66.67
    assert qh.point_of({"name": "m", "used": 12.345}, at=at).left == 87.66
    got = qh.point_of({"name": "m", "used": 25.0, "resets_at": 2000.0, "span": 600.0}, at=at)
    assert (got.resets_at, got.start) == (2000, 1400)
    no_span = qh.point_of({"name": "m", "used": 25.0, "resets_at": 2000.0, "span": 0}, at=at)
    assert (no_span.resets_at, no_span.start) == (2000, None)
    bare = qh.point_of({"name": "m", "used": 25.0}, at=at)
    assert (bare.resets_at, bare.start) == (None, None)


# ---------------------------------------------------------------- 落盘 / 读盘


def test_load_history_is_fail_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """文件不在 / 解不开 / 顶层不是对象 ⇒ `{}`，一条都不抛（§1 + §4）。"""
    monkeypatch.delenv(qh.ENV_HISTORY, raising=False)
    assert qh.load_history(root=tmp_path) == {}
    path = tmp_path.joinpath(*qh.HISTORY_REL)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")
    assert qh.load_history(root=tmp_path) == {}
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert qh.load_history(root=tmp_path) == {}


def test_save_then_load_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, curve):
    """存进去再读回来一模一样；空列表的 key 不落盘；`.bak` 落后一次写。"""
    monkeypatch.delenv(qh.ENV_HISTORY, raising=False)
    hist = {"codearts|codearts-1": [_point(1000, 40.0, start=400, resets=9000)]}
    assert qh.save_history(hist, root=tmp_path) == curve
    assert qh.load_history(root=tmp_path) == hist
    qh.save_history({"codearts|x": []}, root=tmp_path)
    assert qh.load_history(root=tmp_path) == {}
    qh.save_history({"a|b": [_point(2000, 50.0)]}, root=tmp_path)
    assert curve.with_name(curve.name + ".bak").exists()
    assert qh.load_history(root=tmp_path) == {"a|b": [_point(2000, 50.0)]}


# ---------------------------------------------------------------- 接入点（§4）


def test_real_ledger_produces_no_curve_today(ledger: Path, curve: Path):
    """真账本四个号都没有 `used_percent` 与窗口 ⇒ 跑完 `record_probe_result` **文件不存在**。

    这份夹具按真账本的形状裁到两个号（真账本是四个），要证明的事一样：`[account.quota]`
    里没有 `used_percent`、没有窗口起止 ⇒ `point_of()` 一个点都画不出 ⇒ 一个字节都不写。
    """
    data = pa.load_ledger(ledger)
    ids = [acc["id"] for acc in data["account"]]
    assert ids == ["codearts-1", "wb-1"]
    for acc in data["account"]:
        assert "used_percent" not in acc["quota"]
        assert "resets_at" not in acc["quota"]
    rows = [
        {"id": acc["id"], "platform": acc["platform"], "kind": "ok", "amount": 1.0}
        for acc in data["account"]
    ]
    _probe(ledger, rows)
    assert not curve.exists()  # 画不出点 ⇒ 一个字节都不写
    assert qh.load_history(root=ledger.parent.parent.parent) == {}
    assert "2026-10-26T12:00:00+08:00" in ledger.read_text(encoding="utf-8")  # 账本照写


def test_curve_failure_never_blocks_the_ledger(ledger: Path, tmp_path: Path, monkeypatch):
    """把曲线路径指到不可写的地方 ⇒ 账本照写，一个都不许抛出去。"""
    blocker = tmp_path / "blocked"
    blocker.write_text("我是文件，不是目录", encoding="utf-8")
    monkeypatch.setenv(qh.ENV_HISTORY, str(blocker / "quota-history.json"))
    before = ledger.read_bytes()
    rows = [{"id": "codearts-1", "platform": "codearts", "kind": "ok", "used": 7.0}]
    _probe(ledger, rows)  # 不抛就是过
    assert ledger.read_bytes() != before  # 账本那一笔照落
    assert "2026-10-26T12:00:00+08:00" in ledger.read_text(encoding="utf-8")
    assert not (blocker / "quota-history.json").exists()


def test_record_probe_result_notes_a_drawable_window(ledger: Path, curve: Path):
    """窗口形状对了才记点：`used` + `resets_at` + `span` ⇒ 曲线里有一个点。"""
    at = int(datetime(2026, 10, 26, 12, 0, 0, tzinfo=pa.TZ).timestamp())
    rows = [
        {
            "id": "codearts-1",
            "platform": "codearts",
            "kind": "ok",
            "used": 40.0,
            "resets_at": at + 3600,
            "span": 86400,
        }
    ]
    _probe(ledger, rows)
    hist = qh.load_history(root=ledger.parent.parent.parent)
    key = qh.hist_key("codearts", "codearts-1")
    assert list(hist) == [key]
    assert hist[key] == [_point(at, 60.0, start=at + 3600 - 86400, resets=at + 3600)]
    assert curve.exists()


def test_record_probe_result_twice_advances_the_curve(ledger: Path):
    """两次探测 ⇒ 曲线按 key 分组、按时刻递增，第二次不覆盖第一次。"""
    rows = [
        {"id": "wb-1", "platform": "workbuddy", "kind": "ok", "used": 10.0},
        {"id": "codearts-1", "platform": "codearts", "kind": "ok", "used": 20.0},
    ]
    for hour in (12, 13):
        _probe(ledger, rows, hour=hour)
    hist = qh.load_history(root=ledger.parent.parent.parent)
    assert sorted(hist) == [qh.hist_key("codearts", "codearts-1"), qh.hist_key("workbuddy", "wb-1")]
    for points in hist.values():
        assert len(points) == 2
        assert [p.at for p in points] == sorted(p.at for p in points)


# ---------------------------------------------------------------- 模块边界


def test_save_history_raises_oserror_for_callers_to_swallow(tmp_path: Path, monkeypatch):
    """写不进去就抛 `OSError`（由 `note_quota_history` 吞掉），不许静默换路径。"""
    blocker = tmp_path / "blocked2"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv(qh.ENV_HISTORY, str(blocker / "nested" / "quota-history.json"))
    with pytest.raises(OSError):
        qh.save_history({}, root=tmp_path)


def test_module_keeps_the_five_magpie_constants():
    """五个数值逐字取自 magpie；它们**不是**策略旋钮（判据 1 + 2 的字面）。"""
    assert (qh.KEPT_DAYS, qh.MAX_POINTS) == (45, 6000)
    assert (qh.GAP_S, qh.SAME_S, qh.SLACK_S) == (300, 30, 300)
    assert qh.HISTORY_REL == ("gates", "diag", "quota-history.json")
    assert qh.ENV_HISTORY == "TF_POOL_QUOTA_HISTORY"


def test_public_surface_is_exactly_what_the_card_asks_for():
    """判据 1「必须有且仅有这些公开名字」：`__all__` 逐字钉住，多一个少一个都红。

    不比对 `dir()` —— 那里还有 `json` / `os` / `pathlib` 这些 import 带进来的名字，
    它们不是本模块给调用方的零件；`__all__` 才是边界。
    """
    assert sorted(qh.__all__) == [
        "ENV_HISTORY",
        "GAP_S",
        "HISTORY_REL",
        "KEPT_DAYS",
        "MAX_POINTS",
        "QuotaPoint",
        "REFILL_PCT",
        "SAME_S",
        "SLACK_S",
        "add_point",
        "hist_key",
        "load_history",
        "new_cycle",
        "point_of",
        "prune",
        "save_history",
    ]
    assert [name for name in qh.__all__ if not hasattr(qh, name)] == []

