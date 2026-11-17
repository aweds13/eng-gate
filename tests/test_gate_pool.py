r"""云侧门禁池的钉子（卡 E42 · `T-AG494` 判据 1 至少 10 条）。

钉的是**口径**，不是"看起来对了"：

| # | 钉子 | 坏掉会红在哪 |
|---|---|---|
| ① | 槽位计算：4 vCPU ⇒ 1、8 vCPU ⇒ 2、内存不够 ⇒ 1 | 槽数写死 1 ⇒ 8 vCPU 那条红 |
| ② | 端口段 `9200 + slot*40` 且两两不重叠 | 步长 < 一趟占用的端口数 ⇒ 重叠 |
| ③ | 同一槽的并发提交**排队**，不是并行 | 同槽两笔同时 running = 抢同一段端口 |
| ④ | 队列文件原子替换：并发写不丢行 | 读改写不加锁 ⇒ 丢行 |
| ⑤ | `done` 行必须带 `ok / rev / port_base` | 少了端口段就不知道是哪一槽的结果 |
| ⑥ | 断连后能**按 commit** 找回结果 | 按下标/按 task 找回 ⇒ 重试就丢 |
| ⑦ | 回传五条逐条 fail closed（host/rev/门数/用例<95%/工作区） | 去掉任一条 ⇒ 对应钉子红 |
| ⑧ | 槽锁：抢两次第二次 False；陈旧锁可抢；release 后能再抢 | 不加锁 = 两趟同槽并行 |
| ⑨ | `run_cloud_gate`：不可达 ⇒ 抛错；可达 ⇒ 写回 `last.json` + `done` 行 | 不可达静默继续 = 假绿 |
| ⑩ | `Gates-on:` 行与实际一致（`cloud@<host>` / `local`） | 写死 `local` ⇒ 云那趟的 trailer 撒谎 |

★ 全部用**假 transport / 假回传数据**，不连任何云机（卡规格：云机实测由主控做）。
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import gate_pool as gp  # noqa: E402


# ---------------------------------------------------------------- ① 槽位
def test_slot_count_four_vcpu_is_one() -> None:
    """4 vCPU / 15.5 GB ⇒ **1 槽**（云机现规格，`docs/subsystems/ci/云门禁机.md` §1）。"""
    assert gp.slot_count(4, 15.5) == 1


def test_slot_count_eight_vcpu_is_two() -> None:
    """8 vCPU / 16 GB ⇒ **2 槽**；把槽数写死 1 这条当场红。"""
    assert gp.slot_count(8, 16.0) == 2


def test_slot_count_low_memory_falls_back_to_one() -> None:
    """8 vCPU 但可用内存不够（6 GB）⇒ **1 槽**（下限 1，不给 0 槽）。"""
    assert gp.slot_count(8, 6.0) == 1
    assert gp.slot_count(2, 64.0) == 1        # CPU 不够 ⇒ 1


# ---------------------------------------------------------------- ② 端口段
def test_port_segments_do_not_overlap() -> None:
    """每槽 `9200 + slot*40`，段长 = 步长；两两不重叠（一趟全量 ≤20 个端口）。"""
    assert gp.port_base_for(0) == 9200
    assert gp.port_base_for(1) == 9240
    assert gp.port_base_for(2) == 9280
    segs = gp.port_segments(4)
    assert segs == [(9200, 9239), (9240, 9279), (9280, 9319), (9320, 9359)]
    for i, (a0, a1) in enumerate(segs):
        for b0, b1 in segs[i + 1:]:
            assert a1 < b0 or b1 < a0, f"端口段重叠：{(a0, a1)} 与 {(b0, b1)}"
    with pytest.raises(ValueError):
        gp.port_base_for(-1)


# ---------------------------------------------------------------- ③ 同槽排队
def test_same_slot_submissions_queue_not_parallel(tmp_path: Path) -> None:
    """同一槽的第二次提交**排队**（不是并行）；`promote` 在空出槽后才上槽。"""
    q = gp.PoolQueue(tmp_path / "queue.json")
    row1, queued1 = q.submit({"task": "T-1", "commit": "aaa"}, n_slots=1)
    row2, queued2 = q.submit({"task": "T-2", "commit": "bbb"}, n_slots=1)
    assert queued1 is False and row1["state"] == "running"
    assert queued2 is True and row2["state"] == "waiting"
    assert row2.get("slot") is None, "排队的行不许先占槽"

    q.mark_done("aaa", ok=True, rev="aaa", host="cloud", seconds=1.0)
    promoted = q.promote(n_slots=1)
    assert promoted is not None and promoted["commit"] == "bbb"
    assert promoted["state"] == "running" and promoted["slot"] == 0
    assert promoted["port_base"] == 9200


# ---------------------------------------------------------------- ④ 原子写不丢行
def test_concurrent_submits_lose_no_rows(tmp_path: Path) -> None:
    """12 个线程各提交一条（6 槽）⇒ 队列里**一行不少**（原子替换 + 短锁）。"""
    path = tmp_path / "queue.json"
    n = 12
    start = threading.Barrier(n)

    def worker(index: int) -> None:
        start.wait()
        gp.PoolQueue(path).submit({"task": f"T-{index}", "commit": f"c{index:02d}"}, n_slots=6)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    state = gp.PoolQueue(path).load()
    rows = ([state["head"]] if state["head"] else []) + state["waiting"]
    commits = {str(r.get("commit")) for r in rows}
    assert len(commits) == n, f"丢了行：只看到 {sorted(commits)}"
    running = [r for r in rows if r.get("state") == "running"]
    assert len(running) == 6, f"6 槽最多 6 条在跑，实际 {len(running)} 条"


# ---------------------------------------------------------------- ⑤ done 行字段
def test_done_row_carries_ok_rev_port_base(tmp_path: Path) -> None:
    """`done` 行必须带 `ok / rev / port_base`；没有端口段的请求不许写 done。"""
    q = gp.PoolQueue(tmp_path / "queue.json")
    q.submit({"task": "T-1", "commit": "aaa"}, n_slots=1)
    row = q.mark_done("aaa", ok=False, rev="abc123", host="cloud", seconds=2.5)
    assert row["state"] == "done"
    for key in ("ok", "rev", "port_base"):
        assert key in row, f"done 行少了 {key}：{row}"
    assert row["port_base"] == 9200 and row["rev"] == "abc123"
    with pytest.raises(KeyError):
        q.mark_done("nope", ok=True, rev="x")


# ---------------------------------------------------------------- ⑥ 按 commit 找回
def test_find_result_by_commit_after_disconnect(tmp_path: Path) -> None:
    """断连后**按 commit** 找回上一趟的结果（不按下标、不按 task）。"""
    q = gp.PoolQueue(tmp_path / "queue.json")
    q.submit({"task": "T-1", "commit": "aaa"}, n_slots=1)
    q.mark_done("aaa", ok=True, rev="aaa", host="cloud", seconds=9.0)
    assert gp.PoolQueue(tmp_path / "queue.json").done_row("aaa")["rev"] == "aaa"
    assert q.find("aaa")["state"] == "done"
    assert q.find("bbb") is None
    # 重连后同一个 commit 再提交 ⇒ 幂等（不新增一行）
    row, queued = q.submit({"task": "T-1-retry", "commit": "aaa"}, n_slots=1)
    assert row["state"] == "done" and queued is False
    assert len(q.load()["done"]) == 1


# ---------------------------------------------------------------- ⑦ 五条回传校验
def _ok_payload() -> dict:
    return {"rev": "abc1234", "ok": True, "host": "fake-cloud",
            "gates": [{"name": "pytest", "exit_code": 0}, {"name": "ruff", "exit_code": 0}],
            "not_run": []}


def test_return_check_all_five_pass() -> None:
    """五条全过 ⇒ **空清单**（这就不许判红，否则云绿也不算数）。"""
    problems = gp.validate_cloud_return(
        _ok_payload(), expected_rev="abc1234", expected_doors=["pytest", "ruff"],
        pytest_passed=3303, pytest_total=3303, workspace_clean=True, expect_host="fake-cloud")
    assert problems == [], problems


def test_return_check_rejects_missing_host() -> None:
    """缺 `host` ⇒ 拒（证明不了是云机跑的）。去掉这条检查 ⇒ 本钉子红。"""
    payload = _ok_payload()
    payload.pop("host")
    problems = gp.validate_cloud_return(
        payload, expected_rev="abc1234", expected_doors=["pytest", "ruff"],
        pytest_passed=3303, pytest_total=3303, workspace_clean=True)
    assert any(p.startswith("③ host") for p in problems), problems


def test_return_check_rejects_rev_mismatch() -> None:
    """`rev != 父提交` ⇒ 拒（云机跑的是别的提交）。"""
    payload = {**_ok_payload(), "rev": "deadbee"}
    problems = gp.validate_cloud_return(
        payload, expected_rev="abc1234", expected_doors=["pytest", "ruff"],
        pytest_passed=3303, pytest_total=3303, workspace_clean=True)
    assert any(p.startswith("① rev") for p in problems), problems


def test_return_check_rejects_door_count() -> None:
    """门数/门名与该档要求不一致 ⇒ 拒；`not_run` 非空也拒。"""
    short = {**_ok_payload(), "gates": [{"name": "pytest"}]}
    problems = gp.validate_cloud_return(
        short, expected_rev="abc1234", expected_doors=["pytest", "ruff"],
        pytest_passed=3303, pytest_total=3303, workspace_clean=True)
    assert any(p.startswith("② 门数") for p in problems), problems

    not_run = {**_ok_payload(), "not_run": ["render"]}
    problems2 = gp.validate_cloud_return(
        not_run, expected_rev="abc1234", expected_doors=["pytest", "ruff"],
        pytest_passed=3303, pytest_total=3303, workspace_clean=True)
    assert any("not_run" in p for p in problems2), problems2


def test_return_check_rejects_pytest_subset() -> None:
    """`N passed < 全量 95%` ⇒ 拒（像「跑了个子集当全量」）；不知道全量数也拒。"""
    problems = gp.validate_cloud_return(
        _ok_payload(), expected_rev="abc1234", expected_doors=["pytest", "ruff"],
        pytest_passed=3000, pytest_total=3303, workspace_clean=True)
    assert any(p.startswith("④") for p in problems), problems
    assert gp.validate_cloud_return(
        _ok_payload(), expected_rev="abc1234", expected_doors=["pytest", "ruff"],
        pytest_passed=3303, pytest_total=3303, workspace_clean=True, expect_host="other") \
        .__len__() == 1, "host 与期望不一致也要红"
    unknown = gp.validate_cloud_return(
        _ok_payload(), expected_rev="abc1234", expected_doors=["pytest", "ruff"],
        pytest_passed=3303, pytest_total=0, workspace_clean=True)
    assert any("没有基线" in p for p in unknown), unknown


def test_return_check_rejects_dirty_workspace() -> None:
    """云机工作区不干净 ⇒ 拒（`run_gate.sh` 的 `require_no_residue()`）。"""
    problems = gp.validate_cloud_return(
        _ok_payload(), expected_rev="abc1234", expected_doors=["pytest", "ruff"],
        pytest_passed=3303, pytest_total=3303, workspace_clean=False)
    assert any(p.startswith("⑤") for p in problems), problems


def test_parse_pytest_passed_takes_last_number() -> None:
    """`pytest.log` 里取**最后**一条 `N passed`；没有 ⇒ 0（不许默认当通过）。"""
    assert gp.parse_pytest_passed("3303 passed, 1513 warnings in 270.28s") == 3303
    assert gp.parse_pytest_passed("1 failed, 3300 passed in 10s") == 3300
    assert gp.parse_pytest_passed("no summary here") == 0


# ---------------------------------------------------------------- ⑧ 槽锁
def test_slot_lock_acquire_twice_second_false(tmp_path: Path) -> None:
    """同一槽抢两次 ⇒ 第二次 False；release 后能再抢。"""
    lock_dir = tmp_path / "diag"
    assert gp.acquire_slot_lock(lock_dir, 0, card="T-1") is True
    assert gp.acquire_slot_lock(lock_dir, 0, card="T-2") is False
    assert gp.slot_lock_path(lock_dir, 0).is_file()
    assert gp.release_slot_lock(lock_dir, 0) is True
    assert gp.acquire_slot_lock(lock_dir, 0, card="T-2") is True


def test_slot_lock_stale_can_be_stolen(tmp_path: Path) -> None:
    """文件 mtime 旧于 `stale_after` ⇒ 视为陈旧可抢（与 gate_lock 同族语义）。"""
    lock_dir = tmp_path / "diag"
    lock_dir.mkdir(parents=True)
    path = gp.slot_lock_path(lock_dir, 1)
    path.write_text("{}", encoding="utf-8")
    old = time.time() - gp.DEFAULT_STALE_AFTER - 10
    import os

    os.utime(path, (old, old))
    assert gp.acquire_slot_lock(lock_dir, 1, card="T-3") is True


# ---------------------------------------------------------------- ⑨ 云那趟的编排
class _Boom:
    def reachable(self) -> bool:
        return False

    def run_gate(self, entry: dict, tree: Path) -> dict:
        raise AssertionError("不可达就不许真跑（这行不该被走到）")


def test_run_cloud_gate_unreachable_raises(tmp_path: Path) -> None:
    """云机不可达 ⇒ `CloudUnreachable`（调用方退 2、**不回落本机**）。"""
    q = gp.PoolQueue(tmp_path / "queue.json")
    with pytest.raises(gp.CloudUnreachable):
        gp.run_cloud_gate(wt=tmp_path, card="T-1", task="T-1", commit="abc",
                          transport=_Boom(), host="fake-cloud",
                          expected_doors=["pytest"], pytest_total=10, queue=q)
    assert not (tmp_path / "gates" / "last.json").exists(), "不可达不许写回任何东西"


def test_run_cloud_gate_writes_back_and_marks_done(tmp_path: Path) -> None:
    """可达 + 回传合格 ⇒ 写回 `gates/last.json` + `gates/logs/pytest.log`，队列有 done 行。"""
    fake = gp.FakeTransport(data={
        "reachable": True,
        "payload": {"rev": "abc1234", "ok": True, "host": "fake-cloud",
                    "gates": [{"name": "pytest", "exit_code": 0}],
                    "not_run": []},
        "pytest_log": "10 passed in 1s", "workspace_clean": True})
    q = gp.PoolQueue(tmp_path / "queue.json")
    result = gp.run_cloud_gate(
        wt=tmp_path, card="T-1", task="T-1", commit="abc1234", transport=fake,
        host="fake-cloud", expected_doors=["pytest"], pytest_total=10, queue=q,
        lock_dir=tmp_path / "diag")
    assert result.ok and result.problems == []
    payload = json.loads((tmp_path / "gates" / "last.json").read_text(encoding="utf-8"))
    assert payload["host"] == "fake-cloud"
    assert (tmp_path / "gates" / "logs" / "pytest.log").read_text(encoding="utf-8") \
        .startswith("10 passed")
    done = q.done_row("abc1234")
    assert done is not None and done["ok"] is True and done["port_base"] == 9200


# ---------------------------------------------------------------- ⑩ Gates-on
def test_gates_on_line_and_trailer_check() -> None:
    """`Gates-on:` 行：云必须带云机名；与实际不符/多行 都要说出来。"""
    cloud = gp.gates_on_line(gate_on="cloud", host="fake-cloud")
    local = gp.gates_on_line(gate_on="local")
    assert cloud == "Gates-on: cloud@fake-cloud"
    assert local == "Gates-on: local"
    assert gp.check_gates_on_trailer(f"x\n{cloud}\n", expect=cloud) == ""
    assert "不符" in gp.check_gates_on_trailer(f"x\n{local}\n", expect=cloud)
    assert "恰好一行" in gp.check_gates_on_trailer(f"{cloud}\n{cloud}\n", expect=cloud)
    assert "云机名" in gp.check_gates_on_trailer("Gates-on: cloud\n", expect="Gates-on: cloud")

# ---------------------------------------------------------------- ⑪ 卡 E55：锁等待
def test_pool_queue_timeout_defaults_to_thirty(tmp_path: Path) -> None:
    """`PoolQueue.timeout` 默认 >= 30 s，且与 `pool/queue.py::LOCK_WAIT_S` 同值（卡 E55）。

    疼点：`avail 0.73 GB / used 95.2%` 时这条链上的 12 线程抢锁被调度饿住 10 s，
    `locked()` 等满就 `break` 出去**照样写** ⇒ `test_concurrent_submits_lose_no_rows`
    在整趟全量门禁里红过两次（`gate-E50f.log`），单跑全绿。
    """
    assert gp.PoolQueue(tmp_path / "q.json").timeout >= 30.0
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "pool_queue_for_agree", ROOT / "tools" / "pool" / "queue.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.LOCK_WAIT_S == gp.LOCK_WAIT_S, (
        f"同族口径漂了：gate_pool.LOCK_WAIT_S={gp.LOCK_WAIT_S} vs "
        f"queue.LOCK_WAIT_S={mod.LOCK_WAIT_S}"
    )



# ================ 卡 E120（T-AG629）：读不到 != 读到空
# 每处都钉「改前返回什么 / 改后必须抛或退非 0」；全用 tmp_path + 独占句柄。

import contextlib  # noqa: E402
import ctypes  # noqa: E402
import os  # noqa: E402


@contextlib.contextmanager
def _exclusive(path: Path):
    """独占一个文件（Windows：别的进程 open / unlink 都拿 WinError 32）。"""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
    if handle in (-1, None):
        raise OSError(ctypes.get_last_error(), "CreateFileW 失败（造不出独占句柄）")
    try:
        yield handle
    finally:
        kernel32.CloseHandle(handle)


# ---------------------------------------------------------------- (11) 判据 1
def test_queue_load_distinguishes_missing_from_unreadable(tmp_path: Path) -> None:
    """不存在 ⇒ 空状态；目录冒充 / 被独占 / 坏 JSON ⇒ 抛（消息点名 errno 与「不是合法 JSON」）。"""
    q = gp.PoolQueue(tmp_path / "queue.json")
    assert q.load() == {"head": None, "waiting": [], "done": [], "slots": {}}

    as_dir = tmp_path / "as_dir.json"
    as_dir.mkdir()
    with pytest.raises(gp.GatePoolUnreadable) as err:
        gp.PoolQueue(as_dir).load()
    assert "队列读不到" in str(err.value)
    assert "13" in str(err.value)

    good = tmp_path / "held.json"
    good.write_text(json.dumps({"head": None, "waiting": [], "done": [], "slots": {}}),
                    encoding="utf-8")
    with _exclusive(good), pytest.raises(gp.GatePoolUnreadable) as err2:
        gp.PoolQueue(good).load()
    assert "13" in str(err2.value)

    bad = tmp_path / "bad.json"
    bad.write_text("{ 这不是 JSON", encoding="utf-8")
    with pytest.raises(gp.GatePoolUnreadable) as err3:
        gp.PoolQueue(bad).load()
    assert "不是合法 JSON" in str(err3.value)


# ---------------------------------------------------------------- (12) 判据 2
def test_submit_refuses_when_queue_unreadable(tmp_path: Path) -> None:
    """队列读不到 ⇒ submit 拒写，盘上原文件字节不变（不许把还在跑的那条抹掉）。"""
    q = gp.PoolQueue(tmp_path / "queue.json")
    q.submit({"task": "T-1", "card": "T-1", "commit": "aaa", "host": "h"}, n_slots=4)
    before = q.path.read_bytes()
    assert b"aaa" in before

    with _exclusive(q.path), pytest.raises(gp.GatePoolUnreadable):
        q.submit({"task": "T-2", "card": "T-2", "commit": "bbb", "host": "h"}, n_slots=4)
    assert q.path.read_bytes() == before, "读不到时一个字节都不许动"


# ---------------------------------------------------------------- (13) 判据 4
def test_slots_unreadable_memory_is_not_zero(monkeypatch, capsys) -> None:
    """量不出内存 ⇒ 印 avail_gb=unknown 并退 2，不许印 0.0（那是编出来的读数）。"""
    import types

    fake_pkg = types.ModuleType("scripts")
    fake_mod = types.ModuleType("scripts.run_gates")

    def _boom() -> float:
        raise OSError(13, "自己造的：读不到可用内存")

    fake_mod.available_memory_gb = _boom
    fake_pkg.run_gates = fake_mod
    monkeypatch.setitem(sys.modules, "scripts", fake_pkg)
    monkeypatch.setitem(sys.modules, "scripts.run_gates", fake_mod)

    rc = gp.main(["slots"])
    out = capsys.readouterr()
    both = out.out + out.err
    assert rc == 2
    assert "avail_gb=0.0" not in both
    assert "unknown" in both
    assert "判不了" in both


def test_slot_count_none_memory_rejected() -> None:
    """slot_count(cpu, None) 显式拒绝 —— 落到 1 槽也是编数字。"""
    with pytest.raises(ValueError) as err:
        gp.slot_count(8, None)
    assert "判不了" in str(err.value)


# ---------------------------------------------------------------- (14) 判据 5
def test_acquire_slot_lock_times_out_on_undeletable_stale_lock(tmp_path: Path) -> None:
    """陈旧但删不掉的锁 ⇒ timeout 必须真到期（改前是无出口死循环）。"""
    lock_dir = tmp_path / "diag"
    lock_dir.mkdir()
    path = gp.slot_lock_path(lock_dir, 0)
    path.write_text("{}", encoding="utf-8")
    old = time.time() - 20_000.0
    os.utime(path, (old, old))

    started = time.time()
    with _exclusive(path):
        got = gp.acquire_slot_lock(lock_dir, 0, card="T-1", timeout=0.5)
    elapsed = time.time() - started
    assert got is False
    assert elapsed < 1.5, f"timeout 没生效：卡了 {elapsed:.1f}s"


def test_release_slot_lock_distinguishes_no_lock_from_failure(tmp_path: Path) -> None:
    """还锁三态：本来没锁 "no-lock" / 删掉了 True / 删不掉 False。"""
    lock_dir = tmp_path / "diag"
    lock_dir.mkdir()
    assert gp.release_slot_lock(lock_dir, 0) == "no-lock"

    assert gp.acquire_slot_lock(lock_dir, 0, card="T-1") is True
    assert gp.release_slot_lock(lock_dir, 0) is True

    path = gp.slot_lock_path(lock_dir, 0)
    path.write_text("{}", encoding="utf-8")
    with _exclusive(path):
        assert gp.release_slot_lock(lock_dir, 0) is False


def test_locked_reports_unlock_failure(tmp_path: Path, monkeypatch, capsys) -> None:
    """locked() 还锁失败必须打印（改前 suppress 掉就跑，锁会留在盘上）。"""
    q = gp.PoolQueue(tmp_path / "queue.json")
    real = Path.unlink

    def boom(self, *args, **kwargs):
        if self.name.endswith(".lock"):
            raise PermissionError(13, "自己造的：还锁失败")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", boom)
    with q.locked():
        pass
    out = capsys.readouterr().out
    assert "还锁失败" in out
    assert "无锁写" in out


# ---------------------------------------------------------------- (15) 判据 6
def test_write_back_does_not_leave_stale_log(tmp_path: Path) -> None:
    """回传里没有的日志 ⇒ 卡树里上一趟那份必须删掉（下游正是拿它当入口）。"""
    old = tmp_path / "gates" / "logs" / "pytest.log"
    old.parent.mkdir(parents=True)
    old.write_text("上一趟的 20 passed\n", encoding="utf-8")

    gp._write_back(tmp_path, {"ok": True, "rev": "abc"}, {})
    assert not old.exists(), "上一趟的 pytest.log 还在 ⇒ 它会冒充这一趟"

    gp._write_back(tmp_path, {"ok": True, "rev": "abc"},
                   {"pytest.log": "这一趟的 3 passed\n"})
    assert old.read_text(encoding="utf-8") == "这一趟的 3 passed\n"
