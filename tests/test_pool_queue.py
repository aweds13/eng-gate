r"""钉 `tools/pool/queue.py`（合并队列；卡 E5 · `T-AG447`）。

## 为什么有它

落地链 ④–⑦（拿锁 → 门禁 → 封存 → 提交 → ff 合流）是**单写者**段：两笔同时进来，
后到的那笔会在 `git merge --ff-only` 那一刻发现主树已前进 ⇒ rebase / 重跑 / 白烧门禁。
队列要保证三件事（都是卡 E5 的判据）：

1. **单写者**：同一时刻只有队首在 ④–⑦；后来者拿到位次后**继续做自己的 ①②③**（不空等）；
2. **投机预检不复用**：排队期间主树前进过 ⇒ 变队首时 `respec_required()` 必须为真（重跑 ③″）；
3. **出队**：队首干完 `advance()`；ff 失败（rebase 一次仍失败）`drop()` 并打印「需人工」。

## 怎么跑（不碰真仓库）

每个用例把状态文件指到 `tmp_path`（`TF_MERGE_QUEUE`），**不读也不写**真仓库的
`gates/diag/merge-queue.json`。
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_queue():
    spec = importlib.util.spec_from_file_location(
        "pool_queue_under_test", ROOT / "tools" / "pool" / "queue.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def q(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """把状态文件指到 tmp（`TF_MERGE_QUEUE`），并让轮询间隔足够小（测试要快）。"""
    monkeypatch.setenv("TF_MERGE_QUEUE", str(tmp_path / "merge-queue.json"))
    monkeypatch.setenv("TF_QUEUE_POLL", "0.01")
    return _load_queue()


def _raw() -> dict:
    p = Path(os.environ["TF_MERGE_QUEUE"])
    return json.loads(p.read_text(encoding="utf-8"))


def test_enqueue_first_is_head(q) -> None:
    """第一笔入队 ⇒ 位置 1（队首），状态文件落在 `gates/diag/merge-queue.json` 那个位置。"""
    pos = q.enqueue(".wt/a", "T-A", base="sha0")
    assert pos == {"position": 1, "head": "T-A", "total": 1}, pos
    st = _raw()
    assert st["head"]["task"] == "T-A" and st["waiting"] == [], st
    assert st["head"]["base"] == "sha0", st


def test_second_gets_a_slot_and_is_not_head(q) -> None:
    """★ 判据 2（单写者）：第二笔拿到 `queued` 位次，**不是**队首（它继续做自己的 ①②③）。"""
    q.enqueue(".wt/a", "T-A", base="sha0")
    pos = q.enqueue(".wt/b", "T-B", base="sha0")
    assert pos["position"] == 2, pos
    assert pos["head"] == "T-A", pos
    assert q.is_head("T-A") and not q.is_head("T-B")
    assert q.head()["task"] == "T-A"


def test_enqueue_is_idempotent(q) -> None:
    """同一笔重复入队 ⇒ 保持原位（重跑落地不许把自己排到队尾、也不许出现两条）。"""
    q.enqueue(".wt/a", "T-A")
    q.enqueue(".wt/b", "T-B")
    again = q.enqueue(".wt/b", "T-B")
    assert again["position"] == 2, again
    assert again["total"] == 2, again


def test_advance_hands_over_to_next(q) -> None:
    """★ 判据 3：队首 `advance()` 出队 ⇒ 下一个自动变队首；没人了 ⇒ None。"""
    q.enqueue(".wt/a", "T-A")
    q.enqueue(".wt/b", "T-B")
    nxt = q.advance()
    assert nxt["task"] == "T-B", nxt
    assert q.is_head("T-B")
    assert q.advance() is None, "队列空了还给出队首？"
    assert q.head() is None


def test_drop_head_promotes_next(q) -> None:
    """★ 判据 4：ff 失败要出队（队首被摘 ⇒ 下一个顶上；后面的人不被堵死）。"""
    q.enqueue(".wt/a", "T-A")
    q.enqueue(".wt/b", "T-B")
    assert q.drop("T-A") is True
    assert q.is_head("T-B")
    assert q.drop("T-NOSUCH") is False, "摘一笔不在队列里的要如实返回 False"


def test_respec_required_when_base_moves(q) -> None:
    """★ 判据 3（核心）：排队期间**主树前进** ⇒ 投机预检作废（基点一变就要重跑③″）。"""
    q.enqueue(".wt/a", "T-A", base="sha0")
    q.enqueue(".wt/b", "T-B", base="sha0")
    assert q.respec_required("T-B", base="sha0") is False, "基点没变 ⇒ 不该逼它重跑"
    assert q.respec_required("T-B", base="sha1") is True, "基点变了 ⇒ 投机结果不许复用"
    assert q.respec_required("T-NOSUCH", base="sha1") is False, "不在队列里 ⇒ 没有投机可谈"


def test_wait_turn_blocks_until_head_and_times_out(q, capsys) -> None:
    """★ 判据 2：队首在跑时，第二笔 `wait_turn` **等不到**（超时 False）；队首走后立刻轮到。"""
    q.enqueue(".wt/a", "T-A")
    q.enqueue(".wt/b", "T-B")
    assert q.wait_turn("T-B", timeout=0.2, say=print) is False
    out = capsys.readouterr().out
    assert "排队中" in out and "第 2 位" in out, out
    q.advance()                                    # 队首干完
    assert q.wait_turn("T-B", timeout=1.0, say=print) is True


def test_state_file_is_gitignored_location(q, monkeypatch: pytest.MonkeyPatch) -> None:
    """状态落在 `gates/diag/`（gitignore 的运行时目录）—— 不许进提交、不许被复核比对。"""
    assert Path(os.environ["TF_MERGE_QUEUE"]).name == "merge-queue.json"
    monkeypatch.delenv("TF_MERGE_QUEUE")           # 看**默认**落点（不覆写时）
    default = q.state_path()
    assert default.as_posix().endswith("gates/diag/merge-queue.json"), default
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "gates/diag/" in ignore, "gates/diag 必须仍在 .gitignore 里"


# ------------------------------------------------ 卡 E5：同文件卡**不许同批**
#
# 口径与 `tools/pool/plan.py::files_intersect` 同一条：`files` 是冲突域，同批两卡相交 = 冲突。
# 队列里记下这一笔的域；相交的那几笔必须**点名**出来，并落在相邻的两批（串行），不许并排。

def test_enqueue_records_the_conflict_domain(q) -> None:
    """`files` 落进状态文件（POSIX 化）：没有它，「同文件卡不许同批」无从判起。"""
    q.enqueue(".wt/a", "T-A", files=["tools\\pool\\landing.py", "./tools/pool/queue.py"])
    assert _raw()["head"]["files"] == ["tools/pool/landing.py", "tools/pool/queue.py"], _raw()


def test_same_file_conflicts_are_named(q) -> None:
    """★ 判据：与我在**同一个文件**上的那几笔必须被点名（不许静默并排）。"""
    q.enqueue(".wt/a", "T-A", files=["tools/pool/landing.py"])
    q.enqueue(".wt/b", "T-B", files=["tools/pool/landing.py", "tools/pool/queue.py"])
    q.enqueue(".wt/c", "T-C", files=["./tools/pool/queue.py"])

    assert q.same_file_conflicts("T-A") == ["T-B"], q.same_file_conflicts("T-A")
    assert q.same_file_conflicts("T-B") == ["T-A", "T-C"], q.same_file_conflicts("T-B")
    assert q.same_file_conflicts("T-C") == ["T-B"], q.same_file_conflicts("T-C")
    assert q.same_file_conflicts("T-NOSUCH") == [], "不在队列里 ⇒ 没有冲突可谈"


def test_same_file_cards_never_share_a_batch(q) -> None:
    """★ 判据（核心）：同文件卡**不许同批** —— `batches()` 里必须分成两批；域不相交的才可并排。"""
    q.enqueue(".wt/a", "T-A", files=["tools/pool/landing.py"])
    q.enqueue(".wt/b", "T-B", files=["tools/pool/landing.py"])
    q.enqueue(".wt/c", "T-C", files=["docs/x.md"])

    bs = q.batches()
    assert len(bs) == 2, f"同文件卡被并进同一批了：{bs}"
    where = {t: i for i, batch in enumerate(bs) for t in batch}
    assert where["T-A"] != where["T-B"], bs
    assert where["T-C"] == where["T-B"], f"域不相交的不该被挤到第三批：{bs}"


def test_no_files_recorded_means_no_conflict_claim(q) -> None:
    """没记 `files` ⇒ 空列表（「不知道」不等于「不冲突」，不许瞎报警）。"""
    q.enqueue(".wt/a", "T-A")
    q.enqueue(".wt/b", "T-B")
    assert q.same_file_conflicts("T-A") == [], "没记域却报了冲突"
    assert q.batches() == [["T-A", "T-B"]], q.batches()

# ---------------------------------------------------------------- 卡 E55：锁等待窗口
def test_queue_lock_wait_defaults_agree(q) -> None:
    """两处短锁的等待窗口**必须同值且 >= 30 s**（卡 E55 · `T-AG507`）。

    疼点实测：`avail 0.73 GB / used 95.2%` 时 12 线程抢锁，临界区只有毫秒级却被
    调度饿住 10 s ⇒ 等满 `break` 出去**照样往下写** ⇒ 行被后写者盖掉
    （`tests/test_gate_pool.py::test_concurrent_submits_lose_no_rows` 在整趟门禁里红过两次）。
    """
    import sys as _sys

    root = Path(__file__).resolve().parents[1]
    if str(root / "tools") not in _sys.path:
        _sys.path.insert(0, str(root / "tools"))
    import gate_pool as _gp

    assert q.LOCK_WAIT_S >= 30.0, f"pool/queue.py 的 LOCK_WAIT_S={q.LOCK_WAIT_S}，小于 30 s"
    assert _gp.LOCK_WAIT_S == q.LOCK_WAIT_S, (
        f"同族口径漂了：gate_pool.LOCK_WAIT_S={_gp.LOCK_WAIT_S} vs "
        f"queue.LOCK_WAIT_S={q.LOCK_WAIT_S}"
    )


def test_locked_default_waits_for_a_slow_holder(q) -> None:
    """默认参数下，持锁者慢一点也要**等到**（不是等满就走）。

    这里只等 1.0 s（证明「确实在等」）；能不能扛住 10 s 的饥饿由上面的常量钉子守
    —— 同一个数同时喂给 `PoolQueue.timeout` 与 `_locked`。
    """
    import threading
    import time as _time

    lock = q.state_path().with_suffix(".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("holder", encoding="utf-8")
    released = threading.Event()

    def _release_later() -> None:
        _time.sleep(1.0)
        lock.unlink(missing_ok=True)
        released.set()

    threading.Thread(target=_release_later, daemon=True).start()
    t0 = _time.time()
    with q._locked():
        waited = _time.time() - t0
    assert waited >= 0.8, f"没等到持锁者：只等了 {waited:.3f}s"


def test_locked_short_timeout_fails_closed(q) -> None:
    """显式给短 `timeout` ⇒ 到期就抛 `QueueBusy`，**不**绕过去无锁写（窗口仍可调）。

    ★ 卡 E139 改写了这条（原名 `test_locked_short_timeout_still_gives_up`）：改前它断言
      `0.04 <= spent < 3.0` 之后 `with` 正常退出 —— 把「等不到就往下写」当成契约
      （卡 E139 缺口 6）。钉子要守的**还是**「短的 timeout 真的生效」，但生效的结局是
      失败关闭：队列文件一个字节都不许动。

    反向：把 `_locked` 到期分支的 `raise QueueBusy(...)` 换回 `break` ⇒ 这条红
    （变异 D 的 queue 那一半）。
    """
    import time as _time

    state = q.state_path()
    state.parent.mkdir(parents=True, exist_ok=True)
    before = state.read_bytes() if state.exists() else None
    lock = state.with_suffix(".lock")
    lock.write_text("holder", encoding="utf-8")
    try:
        t0 = _time.time()
        with pytest.raises(q.QueueBusy) as err, q._locked(timeout=0.05):
            pass
        spent = _time.time() - t0
    finally:
        lock.unlink(missing_ok=True)
    assert 0.04 <= spent < 3.0, f"短的 timeout 没生效：等了 {spent:.3f}s"
    message = str(err.value)
    assert "等了 0.05s" in message, f"文案缺「等了多久」（必须来自实参）：{message}"
    assert str(lock) in message, f"文案缺锁文件完整路径：{message}"
    assert "holder" in message, f"文案没点名持有者（锁文件里写的是 holder）：{message}"
    assert before is None or state.read_bytes() == before, "等不到锁却写了队列文件 ⇒ 还是「无锁写」"



# ------------------------------------------------ 卡 E139（`T-AG646`）：两族同一个结局
def _two_families(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """造两族的「锁被占住 + `timeout=0.0`」现场，各回一份读数（判据 4 用）。

    ★ 两族**各定义各的异常**（`GatePoolBusy` / `QueueBusy`），所以这里回的是
      「异常元组」而不是一个类：钉子里用 `pytest.raises((子类, 基类))` 同时咬住
      「抛的是它」与「它挂在自家基类下面」。
    ★ 两族的**锁文件名不同**（`merge-queue.lock` vs `gate-pool-queue.json.lock`）——
      卡 E139 明确保留这个差异，所以两边各算各的锁路径，不许互相借用。
    """
    import sys as _sys

    root = Path(__file__).resolve().parents[1]
    if str(root / "tools") not in _sys.path:
        _sys.path.insert(0, str(root / "tools"))
    import gate_pool as _gp

    queue_mod = _load_queue()

    gp_state = tmp_path / "gate-pool-queue.json"
    gp_queue = _gp.PoolQueue(gp_state, timeout=0.0)
    gp_queue.save({"head": None, "waiting": [], "done": [], "slots": {}})
    gp_before = gp_state.read_bytes()
    gp_lock = gp_state.with_suffix(gp_state.suffix + ".lock")

    monkeypatch.setenv("TF_MERGE_QUEUE", str(tmp_path / "merge-queue.json"))
    monkeypatch.setenv("TF_QUEUE_POLL", "0.01")
    q_state = queue_mod.state_path()
    q_state.parent.mkdir(parents=True, exist_ok=True)
    q_before = q_state.read_bytes() if q_state.exists() else None
    q_lock = q_state.with_suffix(".lock")

    return {
        "gate_pool": {
            "enter": gp_queue.locked,
            "lock": gp_lock,
            "before": gp_before,
            "state": gp_state,
            "errors": (_gp.GatePoolBusy, _gp.GatePoolError),
        },
        "queue": {
            "enter": lambda: queue_mod._locked(timeout=0.0),
            "lock": q_lock,
            "before": q_before,
            "state": q_state,
            "errors": (queue_mod.QueueBusy, queue_mod.QueueError),
        },
    }


@pytest.mark.parametrize("family", ["gate_pool", "queue"])
def test_two_families_agree_on_give_up(family, tmp_path, monkeypatch) -> None:
    """★ 判据 4：`PoolQueue.locked` 与 `pool/queue.py::_locked` 在「等不到」上是**同一种结局**。

    两边都：抛自家 `*Busy`（继承自家基类）、文案含锁路径、队列文件一个字节不动、不往下写。
    ★ 反向：只把 gate_pool 改成失败关闭、`queue.py` 保留 `break` ⇒ 这条的 `queue`
      那一半红（变异 D）—— 一颗钉子咬两边就是为此。
    """
    families = _two_families(tmp_path, monkeypatch)
    case = families[family]
    lock = case["lock"]
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(f"{os.getpid()}@fake-host", encoding="utf-8")
    try:
        with pytest.raises(case["errors"]) as err, case["enter"]():
            pass
    finally:
        lock.unlink(missing_ok=True)
    message = str(err.value)
    assert str(lock) in message, f"{family} 的文案没点名锁文件：{message}"
    assert "等了 0s" in message, f"{family} 的文案没写等了多久：{message}"
    assert "fake-host" in message, f"{family} 的文案没说谁可能还持着：{message}"
    if case["before"] is not None:
        assert case["state"].read_bytes() == case["before"], f"{family} 等不到锁却写了队列文件"


def test_two_families_do_not_import_each_other() -> None:
    """★ 判据 4 的另一半：两族只对齐口径，**不许**互相 import（改一处就悄悄改到另一处）。

    ★ 反向：在 `tools/pool/queue.py` 里 `import gate_pool` 然后直接复用 `GatePoolBusy`
      ⇒ 这条红。两族该各自演化（锁文件名、轮询间隔本来就不同）。
    ★ 判据是「有没有这句 import」，**不是**「文件里出没出现这串字符」—— 注释与 docstring
      里点名路径是允许的（它们正是用来解释两族关系的）。
    """
    import ast as _ast

    root = Path(__file__).resolve().parents[1]
    tree = _ast.parse((root / "tools" / "pool" / "queue.py").read_text(encoding="utf-8"))
    names: list[str] = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, _ast.ImportFrom):
            names.append(node.module or "")
            names += [alias.name for alias in node.names]
    offenders = [n for n in names if n == "gate_pool" or n.endswith(".gate_pool")]
    assert not offenders, f"tools/pool/queue.py 反向 import 了 gate_pool：{offenders}"
