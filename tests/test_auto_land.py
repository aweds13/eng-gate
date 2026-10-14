r"""`tools/auto_land.py`（卡 233 · `T-G350`）的判据 —— 四态各一条 + 反向（落函数被调用 0 次）。

★ 全用**假的批目录**（`TF_BATCH_DIR` 指到 `tmp_path`）与**假的链子 / 假的内存读数 /
  假的队列**（monkeypatch 四条小缝：`run_chain` / `wb_dispatch.available_memory_gb` /
  `load_backlog` / `_tree_exists`）—— **不真跑门禁**（本卡要测门禁红，用假的 ✓）、
  不碰真仓的任何状态文件、不真落任何东西。

四态与反向：
  · 该落     ⇒ 退 0，打印批号 + 提交号，链子恰好被调 1 次；
  · 内存紧   ⇒ 退 3、点名"内存紧"、**落函数被调用 0 次**；
  · 门禁红   ⇒ 退 1、门禁原话带出来、**落成被调用 0 次**、后续批不再试（链子总数 = 批数 − 1）；
  · 无批     ⇒ 退 0 且**输出为空**（别刷屏，这条也是判据）。
外加停下来问三条（deferred SR / 用户资产 / 缺收件）与 dry-run 只读一条。
卡 235（按批跳）补两条：混批（停 + 能落）⇒ 能落的**必须被落**（链子恰好 1 次、参数是那批）；
全部停 ⇒ 退 4、落函数 0 次。

边界（如实写，未覆盖）：多成员批的台账号现算（`next_task_id`）与"上一趟还在跑"的
自旋锁路径没在本文件钉（前者逻辑简单，后者要真并发）；卡树里拒落的守卫没钉（要在
卡树里起测试才能咬，收益低）。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import auto_land as al  # noqa: E402 —— 需要先把 tools/ 挂上
import wb_dispatch as wd  # noqa: E402 —— 内存闸唯一实现（fake 它的**读数**，不 fake 判据）
from pool import task as pool_task  # noqa: E402 —— 主树根（守卫用）

GATE_RED_VERBATIM = (
    "=== ④ 锁（段 9034）→ 门禁（硬超时 1800s；全量）===\n"
    "★★ 门禁退出码 = 1【全量】\n"
    "FAILED tests/test_something.py::test_x - assert 1 == 2\n"
    "★ 不绿 ⇒ 不提交\n"
)


# ------------------------------------------------------------------ 假批目录 / 假队列


def _mk_batch(tmp_path: Path, bid: str, members: tuple[str, ...] = ("9001",), *,
              state: str = "awaiting-commit", why: str = "测试批：把收口器做成程序",
              claims: dict[str, dict] | None = None,
              draft: dict | None = None) -> Path:
    """在 tmp_path 里造一个批状态 + 各成员的成功申请收件（全假，不碰真仓）。"""
    bdir = tmp_path / "batch"
    (bdir / f"{bid}.d").mkdir(parents=True, exist_ok=True)
    st: dict = {
        "id": bid, "why": why, "declared": list(members), "read_only": [],
        "claims": {m: "success" for m in members}, "waived": [], "state": state,
    }
    if draft is not None:
        st["draft"] = draft
    (bdir / f"{bid}.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    inbox = claims if claims is not None else _default_claims(members)
    for mid, payload in inbox.items():
        (bdir / f"{bid}.d" / f"{mid}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return bdir


def _default_claims(members: tuple[str, ...], *, why: str = "改好了，pytest 绿",
                    files: list[str] | None = None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for m in members:
        out[m] = {"member": m, "claim": "success", "why": why, "evidence": "pytest 3 passed",
                  "log": "", "files": files if files is not None else [f"tools/x_{m}.py"]}
    return out


@pytest.fixture()
def fake_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    """队列与树都换成假的：9001/9002 在 .wt/fake，台账号预登记好。"""
    monkeypatch.setattr(al, "load_backlog", lambda: {
        "9001": {"id": "9001", "tree": ".wt/fake", "task": "T-G9001"},
        "9002": {"id": "9002", "tree": ".wt/fake", "task": "T-G9002"},
    })
    monkeypatch.setattr(al, "_tree_exists", lambda rel: True)


@pytest.fixture()
def as_main_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试进程在**卡树**里跑 ⇒ `al.ROOT`（卡树）≠ `main_tree_root()`（主树）。

    走到「落」路径的用例把 `al.ROOT` 钉到主树根 —— 守卫（必须在主树跑）才放行；
    假链子不真起进程，所以钉的只是这个模块常量，不碰真仓。
    """
    monkeypatch.setattr(al, "ROOT", pool_task.main_tree_root())


@pytest.fixture()
def fake_memory_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 每个要走到「落」的用例都必须 fake 内存读数 —— 不许拿真机器内存赌（会闪红）。"""
    monkeypatch.setenv("TF_GATE_MIN_FREE_GB", "4")
    monkeypatch.setattr(wd, "available_memory_gb", lambda: 8.0)


@pytest.fixture()
def chain_recorder(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """假链子：记录每次调用的 argv，退 0（门禁绿的假读数在 argv 断言里钉）。"""
    calls: list[list[str]] = []

    def _fake(argv: list[str]) -> tuple[int, str]:
        calls.append(list(argv))
        return 0, "== ⑥ add → commit ==（假链子：说明全链路被走到）"

    monkeypatch.setattr(al, "run_chain", _fake)
    return calls


# ------------------------------------------------------------------ 四态


def test_no_batch_exits_zero_and_prints_nothing(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """★ 态「无批」：退 0 且**输出为空** —— 它每 5 分钟跑一次，别刷屏（这条也是判据）。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path / "batch"))
    (tmp_path / "batch").mkdir()

    rc = al.main([])

    assert rc == 0
    assert capsys.readouterr().out == ""          # ★ 一个字都不许有


def test_should_land_prints_batch_and_commit(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
        fake_queue: None, as_main_tree: None, fake_memory_ok: None,
        chain_recorder: list[list[str]],
) -> None:
    """★ 态「该落」：退 0；打印批号 + 提交号；链子恰好被调 1 次，argv 是 wb_land --batch 全套。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(_mk_batch(tmp_path, "B-T")))
    out_path = tmp_path / "batch" / "B-T.d" / "9001.json"
    assert out_path.is_file()                      # 前置：假申请确实造出来了

    rc = al.main([])

    out = capsys.readouterr().out
    assert rc == 0
    assert len(chain_recorder) == 1                # 链子恰好 1 次
    argv = chain_recorder[0]
    assert argv[3].endswith("wb_land.py")          # 链子 = tools/wb_land.py（别另写一套）
    for needle in ("--batch", "B-T", "--tree", ".wt/fake",
                   "--task", "T-G9001", "--evidence", "tools/x_9001.py",
                   "--allow", "tools/x_9001.py", "--port-base", "9034"):
        assert needle in argv, f"argv 缺 {needle}：{argv}"
    assert re.search(r"★ 落了 B-T → [0-9a-f]{12}", out), out   # 批号 + 提交号都在


def test_low_memory_lands_nothing(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
        fake_queue: None, as_main_tree: None, chain_recorder: list[list[str]],
) -> None:
    """★ 反向「内存紧」：内存读数喂成低于闸 ⇒ 退非 0、点名内存紧、**落函数被调用 0 次**。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(_mk_batch(tmp_path, "B-T")))
    monkeypatch.setenv("TF_GATE_MIN_FREE_GB", "4")
    monkeypatch.setattr(wd, "available_memory_gb", lambda: 1.0)   # ★ 喂低读数（假的）
    landed: list[str] = []
    monkeypatch.setattr(al, "_record_landed", lambda bid, root: landed.append(bid))

    rc = al.main([])

    out = capsys.readouterr().out
    assert rc == 3                                 # 非 0
    assert "内存紧" in out
    assert "1.0" in out and "4.0" in out           # 两个数都在（与 wb_dispatch 同一套口径）
    assert chain_recorder == []                    # ★ 链子 0 次
    assert landed == []                            # ★ 落成 0 次


def test_gate_red_brings_verbatim_lands_nothing_and_stops(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
        fake_queue: None, as_main_tree: None, fake_memory_ok: None,
) -> None:
    """★ 反向「门禁红」：门禁原话带出来、**落成被调用 0 次**、后续批不再试。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(_mk_batch(tmp_path, "B-T1")))
    _mk_batch(tmp_path, "B-T2", members=("9002",))   # 第二个批：红了之后不许再碰
    calls: list[list[str]] = []

    def _red_chain(argv: list[str]) -> tuple[int, str]:
        calls.append(list(argv))
        return 1, GATE_RED_VERBATIM                 # 假门禁：红

    landed: list[str] = []
    monkeypatch.setattr(al, "run_chain", _red_chain)
    monkeypatch.setattr(al, "_record_landed", lambda bid, root: landed.append(bid))

    rc = al.main([])

    out = capsys.readouterr().out
    assert rc == 1                                  # 门禁红的码原样透传
    assert "FAILED tests/test_something.py::test_x" in out   # ★ 门禁原话带出来
    assert "★ 不绿 ⇒ 不提交" in out
    assert landed == []                             # ★ 落成被调用 0 次
    assert len(calls) == 1                          # ★ 第二批不再试（红一家伙就停）


def test_dry_run_only_says_lands_nothing(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
        fake_queue: None, chain_recorder: list[list[str]],
) -> None:
    """`--dry-run`：只说「会落哪几批」，一行都不改（状态文件字节级不变、链子 0 次）。"""
    bdir = _mk_batch(tmp_path, "B-T")
    monkeypatch.setenv("TF_BATCH_DIR", str(bdir))
    state_file = bdir / "B-T.json"
    before = state_file.read_bytes()

    rc = al.main(["--dry-run"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "会落：B-T" in out and "T-G9001" in out
    assert chain_recorder == []                     # 链子 0 次
    assert state_file.read_bytes() == before        # ★ 一行都不改


# ------------------------------------------------------------------ 停下来问 + 扫描边界


def test_stop_on_deferred_sr_item(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
        fake_queue: None, as_main_tree: None, fake_memory_ok: None,
        chain_recorder: list[list[str]],
) -> None:
    """批里混着用户决策项（deferred SR）⇒ 非零退出 + 点名，链子 0 次。"""
    claims = _default_claims(("9001",), why="顺手把 SR-F2.8 的账也收了")
    monkeypatch.setenv("TF_BATCH_DIR", str(_mk_batch(tmp_path, "B-T", claims=claims)))

    rc = al.main([])

    out = capsys.readouterr().out
    assert rc == 4
    assert "SR-F2.8" in out and "停下来问" in out
    assert chain_recorder == []


def test_stop_on_user_asset(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
        fake_queue: None, as_main_tree: None, fake_memory_ok: None,
        chain_recorder: list[list[str]],
) -> None:
    """批要动用户资产（data/ 硬编码禁区）⇒ 非零退出 + 点名，链子 0 次。"""
    claims = _default_claims(("9001",), files=["tools/a.py", "data/timeflow.db"])
    monkeypatch.setenv("TF_BATCH_DIR", str(_mk_batch(tmp_path, "B-T", claims=claims)))

    rc = al.main([])

    out = capsys.readouterr().out
    assert rc == 4
    assert "用户资产" in out and "data/timeflow.db" in out
    assert chain_recorder == []


def test_missing_claim_stops(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
        fake_queue: None, as_main_tree: None, fake_memory_ok: None,
        chain_recorder: list[list[str]],
) -> None:
    """★ 改坏就红：awaiting 批的成员收件被清掉 ⇒ 停下来问（没证据的东西不叫落），链子 0 次。"""
    bdir = _mk_batch(tmp_path, "B-T")               # 造完把收件删掉
    (bdir / "B-T.d" / "9001.json").unlink()
    monkeypatch.setenv("TF_BATCH_DIR", str(bdir))

    rc = al.main([])

    out = capsys.readouterr().out
    assert rc == 4
    assert "9001" in out and "收件" in out
    assert chain_recorder == []


def test_collecting_batch_is_ignored_silently(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """★ 改坏就红：state 不是 awaiting-commit 的批不扫进来 —— 退 0 且输出为空，链子 0 次。"""
    calls: list[list[str]] = []
    monkeypatch.setattr(al, "run_chain", lambda argv: calls.append(argv) or (0, ""))
    monkeypatch.setenv("TF_BATCH_DIR", str(
        _mk_batch(tmp_path, "B-T", state="collecting")))

    rc = al.main([])

    assert rc == 0
    assert capsys.readouterr().out == ""
    assert calls == []


# ------------------------------------------------------------------ 卡 235：按批跳


def test_mixed_stop_and_landable_still_lands_the_landable_batch(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
        fake_queue: None, as_main_tree: None, fake_memory_ok: None,
        chain_recorder: list[list[str]],
) -> None:
    """★ 卡 235 反向（本卡核心）：{一批停 + 一批能落} ⇒ 能落的那批**必须被落**。

    停的批排在前面（B-A < B-B，仿真实事故：B-20261017 堵死能落的 B-20261018）：
    旧码在停的批上一家伙退 4 ⇒ 链子 0 次 —— 本判据在旧码上必红；
    按批跳 ⇒ 只跳过 B-A（点名），B-B 照落（落函数恰好 1 次、参数是 B-B）。
    """
    bdir = _mk_batch(tmp_path, "B-A")               # 停的批：收件被清掉（没证据 ⇒ 停）
    (bdir / "B-A.d" / "9001.json").unlink()
    _mk_batch(tmp_path, "B-B", members=("9002",))   # 能落的批
    monkeypatch.setenv("TF_BATCH_DIR", str(bdir))
    landed: list[str] = []
    monkeypatch.setattr(al, "_record_landed", lambda bid, root: landed.append(bid))

    rc = al.main([])

    out = capsys.readouterr().out
    assert rc == 0                                   # 有能落的 ⇒ 不许退 4
    assert len(chain_recorder) == 1                  # ★ 落函数恰好被调 1 次
    argv = chain_recorder[0]
    assert argv[argv.index("--batch") + 1] == "B-B"  # ★ 调用参数是能落的那批
    assert landed == ["B-B"]                         # 落成也恰好这一批
    assert "停下来问" in out and "收件" in out        # 停的批照旧点名（原因说清）
    assert "只跳过这一批" in out and "B-B" in out     # 停的点名不再说"什么都不落"堵人


def test_all_stopped_exits_four_and_lands_nothing(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
        fake_queue: None, as_main_tree: None, fake_memory_ok: None,
        chain_recorder: list[list[str]],
) -> None:
    """★ 卡 235 边界：**全部**批都不能自动决定 ⇒ 退 4、落函数被调用 0 次（两家都点名）。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(_mk_batch(
        tmp_path, "B-A", claims=_default_claims(("9001",), why="顺手把 SR-F2.8 的账也收了"))))
    _mk_batch(tmp_path, "B-B", members=("9002",), claims=_default_claims(
        ("9002",), files=["tools/a.py", "data/timeflow.db"]))
    landed: list[str] = []
    monkeypatch.setattr(al, "_record_landed", lambda bid, root: landed.append(bid))

    rc = al.main([])

    out = capsys.readouterr().out
    assert rc == 4                                   # 全停 ⇒ 退 4
    assert chain_recorder == []                      # ★ 落函数 0 次
    assert landed == []
    assert "SR-F2.8" in out and "用户资产" in out     # 两家停因都点名
    assert out.count("停下来问") == 2                 # 两批各点各的（不是只点第一家）
