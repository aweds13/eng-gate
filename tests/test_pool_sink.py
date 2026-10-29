r"""Sink 沉底（`tools/pool/sink.py`，卡 A331 · `T-AG533`）的测试 —— 8 条钉子 + 4 条边界。

**为什么值当测**：`sink_order` 的「未沉在前、沉者按沉序」是一条**稳定排序**判据。状态文件只是
诊断产物，没人肉眼核；它一旦写错（分段写反、或退化成单段），「先沉下去的候选排更后面」就
悄悄变成「不排序」，429 换模型会原地打转。所以每条口径都要有一条会红的钉子，外加一条反向钉
（`test_reverse_*`）证明这些钉子真的咬住了 `seq`。

- `test_sink_order_never_sunk_keep_theirs`：全未沉 ⇒ 原序 `[0, 1, 2]`
- `test_sink_order_sank_first_goes_first_among_sunk`：沉序 k2 先、k0 后 ⇒ `[1, 2, 0]`
- `test_sink_order_moves_sunk_behind_unsunk`：只沉 k1 ⇒ `[0, 2, 1]`（沉者挪后）
- `test_sink_is_idempotent_but_bumps_seq`：同 key 再沉 ⇒ 刷新 `n`、`sunk_at` 回新 `n`
- `test_unsink_all_drops_account_and_its_models`：`unsink_all("acct")` 删 `acct` 与 `acct/m1`
- `test_sinks_disabled_for_rotate_weighted_manual`：rotate / weighted / manual 全 False
- `test_balance_exhausted_never_sinks`：`kind == "余额耗尽"` 绝不沉（真跑 `quota_error`）
- `test_reverse_sink_order_without_seq`：key 退化成常数 0 必得另一个序 ⇒ 上面那条有牙

边界另四条：`unsink` 只擦精确 key、`sunk_at` 模型级优先于账号级、坏 JSON 只读回空且不重写、
`seq` 非正整数视为从未沉且在 stderr 说一句。

★ 一律用 `TF_POOL_SINK` 指临时目录 —— 不往真的 `gates/diag/` 里写。
★ 测试不许靠真实钟表：`now` 一律注入固定值 `NOW`。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_dispatch  # noqa: E402 —— 429 分类的唯一真源（quota_error）
from pool import sink  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上

NOW = 1_700_000_000.0

#: 钉子里固定用的三个候选（对应 magpie 的 `[]{k0, k1, k2}`）。
KEYS = ("k0", "k1", "k2")


def _key_of(i: int) -> str:
    return KEYS[i]


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把状态文件指到临时目录；返回它的路径（测试里要读坏文件的字节痕迹）。"""
    p = tmp_path / "pool-sink.json"
    monkeypatch.setenv(sink.ENV_SINK, str(p))
    return p


def test_sink_order_never_sunk_keep_theirs(state: Path) -> None:
    """判据：一个都没沉过 ⇒ 各自位置不动（照 sink.go:94-117 的 seq==0 分支）。"""
    assert sink.sink_order(3, _key_of) == [0, 1, 2]


def test_sink_order_sank_first_goes_first_among_sunk(state: Path) -> None:
    """判据：沉者按沉序 —— 先沉的排后续沉者之前；未沉者仍在最前（保原序）。"""
    sink.sink("k2", now=NOW)  # 先沉 k2 ⇒ n=1
    sink.sink("k0", now=NOW)  # 后沉 k0 ⇒ n=2
    # k1 从未沉 ⇒ 排最前；沉者里 k2(n=1) 先于 k0(n=2) ⇒ [1, 2, 0]
    assert sink.sink_order(3, _key_of) == [1, 2, 0]


def test_sink_order_moves_sunk_behind_unsunk(state: Path) -> None:
    """判据：只沉中间那个 ⇒ 它挪到队尾，另外两个保原序（`[0, 2, 1]`）。"""
    sink.sink("k1", now=NOW)
    assert sink.sink_order(3, _key_of) == [0, 2, 1]
    # 串起来的重排也要一致（sink_last 是 sink_order 的唯一用法）
    assert sink.sink_last(list(KEYS), lambda k: k) == ["k0", "k2", "k1"]


def test_sink_is_idempotent_but_bumps_seq(state: Path) -> None:
    """判据：同 key 再沉不是「保持原序号」，而是**刷新**成新的 n（照 sink.go:43-48）。"""
    first = sink.sink("k1", now=NOW)
    assert first == 1
    assert sink.sunk_at("k1") == (1, NOW)
    second = sink.sink("k1", now=NOW + 30)
    assert second == 2, "同 key 再沉必须刷新序号，不许原地不动"
    assert sink.sunk_at("k1") == (2, NOW + 30)
    # 刷新之后它才是「最后沉的」⇒ 排在其它沉者之后
    sink.sink("k0", now=NOW)  # k0 ⇒ n=3
    assert sink.sunk_at("k0") == (3, NOW)
    sink.sink("k1", now=NOW + 60)  # k1 再刷新 ⇒ n=4
    assert sink.sink_order(3, _key_of) == [2, 0, 1]


def test_unsink_all_drops_account_and_its_models(state: Path) -> None:
    """判据：`unsink_all("acct")` 删 `acct` **与它下面所有** `acct/…`，不碰同前缀的别人。"""
    sink.sink("acct", now=NOW)
    sink.sink("acct/m1", now=NOW)
    sink.sink("acct2", now=NOW)  # 前缀像，但不是它下面的
    assert sink.unsink_all("acct") == 2, "应删 acct 与 acct/m1 两条"
    assert sink.sunk_at("acct") is None
    assert sink.sunk_at("acct/m1") is None
    assert sink.sunk_at("acct2") is not None, "acct2 不在半开前缀里，不许被删"
    assert sink.unsink_all("acct") == 0, "幂等：再擦一次删 0 条"


def test_unsink_only_exact_key(state: Path) -> None:
    """判据：`unsink` 只擦精确那一个（照 sink.go:53）；模型级要 `unsink_all`。"""
    sink.sink("acct", now=NOW)
    sink.sink("acct/m1", now=NOW)
    sink.unsink("acct")
    assert sink.sunk_at("acct") is None
    assert sink.sunk_at("acct/m1") is not None


def test_sinks_disabled_for_rotate_weighted_manual(state: Path) -> None:
    """判据：轮转 / 按权重 / 手动 三种 routing 下**不许沉**（照 sink.go:87-89）。"""
    for routing in ("rotate", "weighted", "manual"):
        assert sink.sinks(True, routing) is False, f"{routing} 本身就在轮转/手动，沉了会打架"
    assert sink.sinks(True, "smart") is True
    assert sink.sinks(False, "smart") is False, "总开关关掉就一律不沉"


def test_balance_exhausted_never_sinks(state: Path) -> None:
    """判据：**只有「限流」这类 429 才沉**；`kind == "余额耗尽"` 绝不沉（routing.go:1096-1148）。

    这里真跑 `tools/wb_dispatch.py::quota_error` 的分类（429 分类的唯一真源），
    不自己编 kind 字符串 —— 否则这条钉子只是在测我自己写的常量。
    """
    rate_event = {
        "type": "result",
        "is_error": True,
        "result": "API Error: 429 使用量已超出频率限制，将在 2026-10-24 15:30:00 重置",
    }
    bal_event = {
        "type": "result",
        "is_error": True,
        "result": "API Error: 400 额度已用尽，请充值后再试",
    }
    rate = wb_dispatch.quota_error([json.dumps(rate_event, ensure_ascii=False)])
    bal = wb_dispatch.quota_error([json.dumps(bal_event, ensure_ascii=False)])
    assert rate is not None and rate["kind"] == "限流", f"分类器口径变了？{rate!r}"
    assert bal is not None and bal["kind"] == "余额耗尽", f"分类器口径变了？{bal!r}"

    assert sink.should_sink(rate["kind"], "smart") is True
    assert sink.should_sink(bal["kind"], "smart") is False

    # 主流程形状：连着两次 429，只有限流那次落账
    for quota in (rate, bal):
        if sink.should_sink(quota["kind"], "smart"):
            sink.sink("acct/m1", now=NOW)
    assert sink.sunk_at("acct/m1") == (1, NOW)

    # 余额耗尽再单独跑一遍：不许动已有状态（一个字节都不许写）
    before = state.read_bytes()
    for quota in (bal,):
        if sink.should_sink(quota["kind"], "smart"):
            sink.sink("acct/m1", now=NOW)
    assert state.read_bytes() == before, "余额耗尽不许落盘（沉下去就再也回不来）"


def test_sunk_at_model_before_account(state: Path) -> None:
    """判据：`sunk_at` 先查 `<account>/<model>`（模型级），查不到才查 `<account>`（账号级）。"""
    sink.sink("acct", now=NOW)  # n=1 账号级
    sink.sink("acct/m1", now=NOW)  # n=2 模型级
    assert sink.sunk_at("acct/m1") == (2, NOW), "模型级命中优先，不许先回账号级那个"
    assert sink.sunk_at("acct/m2") == (1, NOW), "模型级没有 ⇒ 落到账号级"
    assert sink.sunk_at("other/m1") is None


def test_bad_json_reads_empty_and_is_not_rewritten(
    state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """判据：坏 JSON ⇒ 只读回空、**不抛**、且**不重写**那个文件（写时才建）。"""
    state.write_text("{ 这不是 JSON", encoding="utf-8")
    before = state.read_bytes()
    assert sink.sunk_at("k0") is None
    assert sink.sink_order(3, _key_of) == [0, 1, 2]
    assert sink.unsink("k0") is None  # 擦不存在的 key 不许落盘
    assert state.read_bytes() == before, "只读那一侧不许顺手把坏文件洗成空壳"

    # 文件不存在也算空，且一次只读都不许把文件创建出来
    missing = tmp_path / "nope.json"
    monkeypatch.setenv(sink.ENV_SINK, str(missing))
    assert sink.sunk_at("k0") is None
    assert not missing.exists(), "读不许建文件"


def test_bad_seq_treated_never_sunk_and_warns_stderr(
    state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """判据：`seq` 非正整数 ⇒ 该 key 视为从未沉，并在 **stderr** 说一句（不静默）。"""
    state.write_text(
        json.dumps({"n": 9, "m": {"k1": {"n": 0, "at": NOW}, "k2": {"n": "x", "at": NOW}}}),
        encoding="utf-8",
    )
    assert sink.sunk_at("k1") is None, "seq=0 不算沉过"
    assert sink.sunk_at("k2") is None, "seq 不是正整数不算沉过"
    err = capsys.readouterr().err
    assert "[sink]" in err, f"坏值必须在 stderr 说一句，实际 stderr={err!r}"
    assert "k1" in err and "k2" in err
    # 外面那个 n=9 仍被尊重 ⇒ 下一次 sink 从 10 起（不倒退）
    assert sink.sink("k0", now=NOW) == 10


def test_reverse_sink_order_without_seq(state: Path) -> None:
    r"""反向钉：把 `sink_order` 的 key 退化成 `lambda i: 0`（丢掉 seq），必得**另一个**序。

    `tools/pool/sink.py::sink_order` 用的是两段式
    `lambda i: (0, 0) if seq[i] == 0 else (1, seq[i])`。若退化成常数 0（等于「不排序」），
    在「只沉 k1」这个场景里会给出 `[0, 1, 2]`，而真解得 `[0, 2, 1]` —— 两者**不同**，
    所以 `test_sink_order_moves_sunk_behind_unsunk` 确实咬住了 `seq`：
    `gates/diag/_rev_A331.py` 把 key 真改成 `lambda i: 0` 之后它必须变红。
    """
    sink.sink("k1", now=NOW)
    real = sink.sink_order(3, _key_of)
    assert real == [0, 2, 1]
    degenerate = sorted(range(3), key=lambda _i: 0)  # 变异体：丢掉 seq
    assert degenerate == [0, 1, 2]
    assert real != degenerate, "两种 key 给出同一个序 ⇒ 上面那条钉子没咬住任何东西，得改钉"
