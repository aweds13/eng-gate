"""卡 E7（T-AG453）的钉子 —— 工人完工事件接进派活链：**派活即看守**。

为什么值当测（每一条都对应卡上的判据，红了就是那条判据破了）：
  1. **派活即看守**：`--execute` 成功起工人后自动起看守 —— 忘了起看守的世界里，
     主控只能靠每 2 分钟敲 `--status`（真发生过，5 张卡全靠手敲才发现收工）。
  2. **`--no-watch` 明说**：关掉看守必须打印「已关看守：完工后请自己轮询」——**不静默**。
  3. **看守不许骗人**：超时没判决只写 `state:"timeout"`，**绝不**写 `.done`（没做完不算完）。
  4. **完工事件落盘**：`wb-<卡>.done` 六个字段齐全 + `notifications.jsonl` 一行（带 card/verdict，
     正好是 `wb_notify` 的幂等键）。
  5. **合用看守的引用计数**：派 3 张、2 张先出判决 ⇒ `refcount == 1`；最后一张 ⇒ `0` 且写
     `batch-done`。
  6. **看守重启从磁盘重建计数**：已出判决的卡不算未完成（不靠内存变量）。
  7. **看守自己死了不算完**：心跳过期 + 还有卡没判决 ⇒ `watcher-stale` 事件 + 退非零。

★ 全用**假时间源 + 假目录**（`tmp_path` 当仓库根）：不真等、不碰任何真实 `gates/diag`，
  也不让派活器去占真树（`--already-reserved` + 删掉 `DSH_SESSION_ID`，会话账本一个字不动）。
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_dispatch as wd  # noqa: E402 —— 派活器（看守在它里面被挂上）
import wb_watch  # noqa: E402 —— 看守（判据 / 事件 / 登记表都在它里面）

#: 一份 `wb_dispatch` 判决文件的样子（第一行带退出码 + 开始 / 结束时刻）。
CB_VERDICT = (
    "card=213 第=1 次 退出码=0 会话=ses_x 开始于=2026-10-24T10:00:00 结束于=2026-10-24T10:12:00\n"
    "判决：正常收工（工人退出码 0）\n"
)


# ---------------------------------------------------------------- 假时间源 / 造文件
class FakeClock:
    """假时间源：`clock()` 回当前秒；`sleep` 只把它往前推，**不真等**。"""

    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def _write(path: Path, text: str, *, age: float = 0.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if age:
        then = time.time() - age
        os.utime(path, (then, then))
    return path


def _cb_verdict(root: Path, card: str, *, text: str = CB_VERDICT) -> Path:
    return _write(root / "gates" / "diag" / f"wb-{card}.verdict.txt", text)


def _cb_log(root: Path, card: str, *, age: float = 0.0) -> Path:
    return _write(root / "gates" / "diag" / f"wb-{card}.jsonl",
                  '{"type":"system","subtype":"init","model":"m"}\n', age=age)


def _rows(root: Path) -> list[dict]:
    """`notifications.jsonl` 的每一行（按落盘顺序）。"""
    path = root / "gates" / "diag" / "notifications.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# ---------------------------------------------------------------- 判据 1：派活即看守
def _dispatch_sandbox(tmp_path: Path, monkeypatch) -> None:
    """把派活器指到一个空沙箱：不起真工人、不碰真登记表、不碰真会话账本。"""
    (tmp_path / "spec.md").write_text("卡规格", encoding="utf-8")
    node = tmp_path / "node.exe"
    cli = tmp_path / "cli"
    node.write_text("", encoding="utf-8")
    cli.write_text("", encoding="utf-8")
    monkeypatch.setattr(wd, "ROOT", tmp_path)
    monkeypatch.setattr(wd, "paths", lambda *a, **k: (node, cli))
    monkeypatch.setattr(wd, "preflight",
                        lambda *a, **k: ([], tmp_path / "gates" / "diag" / "wb-E7.jsonl"))
    monkeypatch.setattr(wd, "preflight_auth", lambda *a, **k: (wd.AuthState.OK, "登录自检通过"))
    monkeypatch.delenv("DSH_SESSION_ID", raising=False)      # 不写真会话账本
    monkeypatch.delenv("TF_DISPATCH_PORT_BASE", raising=False)


def _fake_runner(cmd, log, errlog, **kwargs):                # noqa: ANN001, ANN202
    """工人「正常收工」：落一行 result 事件，返回（退出码 0, 无中断原因）。"""
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps({"type": "result", "subtype": "success", "result": "做完了"}) + "\n",
                   encoding="utf-8")
    errlog.write_text("", encoding="utf-8")
    return 0, "", "", "sid-x"


def test_execute_starts_a_watcher_by_default(tmp_path: Path, monkeypatch, capsys) -> None:
    """★ 判据 1：`--execute` 真派活 ⇒ **自动**挂看守（默认 `one` 形态），不用人记着起。"""
    _dispatch_sandbox(tmp_path, monkeypatch)
    started: list[tuple[str, dict]] = []
    monkeypatch.setattr(wd, "spawn_watcher",
                        lambda card, **kw: started.append((card, kw)) or 4242)
    monkeypatch.setattr(wd, "run_worker", _fake_runner)
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "E7", "--spec", "spec.md",
                                      "--execute", "--already-reserved"])
    assert wd.main() == 0
    out = capsys.readouterr().out
    assert started, "派活成功后必须自动起一份看守（忘了起 = 又回到人肉轮询）"
    assert started[0][0] == "E7"
    assert started[0][1]["mode"] == "one", "默认必须是专属看守（一张卡一次通知）"
    assert "看守已起" in out and "wb-E7.done" in out


def test_no_watch_says_it_out_loud(tmp_path: Path, monkeypatch, capsys) -> None:
    """★ 判据 3：`--no-watch` 不起看守，但必须**明说**「已关看守：完工后请自己轮询」。"""
    _dispatch_sandbox(tmp_path, monkeypatch)
    started: list[str] = []
    monkeypatch.setattr(wd, "spawn_watcher", lambda card, **kw: started.append(card) or 4242)
    monkeypatch.setattr(wd, "run_worker", _fake_runner)
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "E7", "--spec", "spec.md",
                                      "--execute", "--already-reserved", "--no-watch"])
    assert wd.main() == 0
    out = capsys.readouterr().out
    assert started == [], "--no-watch 不许起看守"
    assert wd.no_watch_notice() in out
    assert "已关看守：完工后请自己轮询" in out, "关掉看守必须说清楚（不静默）"


def test_watch_horizon_covers_every_attempt(tmp_path: Path, monkeypatch) -> None:
    """★ 看守期限要盖过「每一轮都能跑 `--timeout`、还能续 `--retry` 次」——
    否则工人在续跑时看守先喊「超时」并退出，那是**假超时**（比不挂更误导）。"""
    assert wd.watch_horizon(7200, 0) > 7200
    assert wd.watch_horizon(7200, 1) >= 7200 * 2


def test_shared_watch_registers_the_card_and_spawns_once(tmp_path: Path, monkeypatch) -> None:
    """`--watch shared`：先登记（refcount +1），再起一份合用看守。"""
    monkeypatch.setattr(wd, "ROOT", tmp_path)
    started: list[dict] = []
    monkeypatch.setattr(wd, "spawn_watcher", lambda card, **kw: started.append(kw) or 777)
    msg = wd.ensure_watch("E7", mode="shared", timeout=60)
    reg = wb_watch.read_registry(tmp_path)
    assert reg["refcount"] == 1 and reg["cards"]["E7"] == wb_watch.STATE_WATCHING
    assert started and started[0]["mode"] == "shared"
    assert "refcount=1" in msg


def test_shared_dispatch_notices_a_dead_watcher(tmp_path: Path, monkeypatch) -> None:
    """★ 判据 8 的派活侧：上一个合用看守心跳早停了 ⇒ 写 `watcher-stale`、重建计数、再起一份。

    ★ 窗口按「几分钟没心跳」（`wb_watch.ALIVE_WINDOW`）算，**不是**看守的硬期限 ——
      否则死了三小时的看守还会被当成在盯，新派的卡就没人守了。
    """
    monkeypatch.setattr(wd, "ROOT", tmp_path)
    wb_watch.register_cards(tmp_path, ["OLD"])
    reg = wb_watch.read_registry(tmp_path)
    reg["pid"] = 999999
    reg["heartbeat"] = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
    wb_watch.write_registry(tmp_path, reg)
    started: list[str] = []
    monkeypatch.setattr(wd, "spawn_watcher", lambda card, **kw: started.append(card) or 888)
    wd.ensure_watch("NEW", mode="shared", timeout=wd.watch_horizon(7200, 1))
    assert [r for r in _rows(tmp_path) if r.get("state") == "watcher-stale"], "死人必须被说出来"
    assert started == ["NEW"], "发现看守死了就该重起一份"
    assert wb_watch.read_registry(tmp_path)["refcount"] == 2


# ---------------------------------------------------------------- 判据 4：超时不冒充成功
def test_watch_timeout_writes_timeout_event_and_never_a_done(tmp_path: Path) -> None:
    """★ 判据 4：超时没判决 ⇒ 只写 `state:"timeout"`，**不写** `.done`（没判决 ≠ 成功）。"""
    _cb_log(tmp_path, "E7", age=0)                       # 日志刚动过 → 一直在跑
    clock = FakeClock(time.time())
    said: list[str] = []
    rc = wb_watch.watch(["E7"], root=tmp_path, timeout=10, interval=5,
                        clock=clock, sleep=clock.sleep, emit=said.append, write_done=True)
    assert rc == wb_watch.EXIT_TIMEOUT
    assert not (tmp_path / "gates" / "diag" / "wb-E7.done").exists(), "没判决不许写完工事件"
    events = [r for r in _rows(tmp_path) if r.get("card") == "E7"]
    assert events and events[-1]["state"] == "timeout"
    assert "不算" in "\n".join(said)


# ---------------------------------------------------------------- 判据 2：完工事件落盘
def test_done_event_has_the_six_fields_and_one_notification_row(tmp_path: Path) -> None:
    """★ 判据 2：`wb-<卡>.done` = 一行 JSON，六个字段齐全；通知流追加一行（带 card/verdict）。"""
    _cb_verdict(tmp_path, "E7")
    _cb_log(tmp_path, "E7")
    done = wb_watch.write_done_event(tmp_path, "E7")
    assert done is not None
    assert set(done) == {"card", "task", "exit_code", "at", "log", "report"}
    assert done["card"] == "E7" and done["exit_code"] == 0
    on_disk = json.loads((tmp_path / "gates" / "diag" / "wb-E7.done").read_text(encoding="utf-8"))
    assert on_disk == done
    rows = _rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["card"] == "E7" and rows[0]["verdict"].startswith("正常收工")
    # ★ 幂等：再写一次不产生第二行（看守重启 / 两种形态并发都不许重复写）
    assert wb_watch.write_done_event(tmp_path, "E7") == done
    assert len(_rows(tmp_path)) == 1


def test_no_verdict_means_no_done_event(tmp_path: Path) -> None:
    """★ 反例：没有判决就**写不出** `.done`（看守不猜成功）。"""
    _cb_log(tmp_path, "E7", age=0)
    assert wb_watch.write_done_event(tmp_path, "E7") is None
    assert not (tmp_path / "gates" / "diag" / "wb-E7.done").exists()


# ---------------------------------------------------------------- 旧证据不许冒充这一轮
def test_old_silent_log_is_not_a_death_for_this_round(tmp_path: Path) -> None:
    """★ 真现场（`--force` 重派）：上一轮的 `wb-<卡>.jsonl` 还在、也早就静默 ⇒ 不许读成「判死」。

    不切 `since` 时它**确实**长得像判死（这正是坑）；切了之后只能说「看不见 / 还没开始」。
    """
    _cb_log(tmp_path, "E7", age=3600)
    assert wb_watch.probe_card("E7", tmp_path, time.time()).kind == wb_watch.DEAD
    sig = wb_watch.probe_card("E7", tmp_path, time.time(), since=time.time())
    assert sig.kind != wb_watch.DEAD, "旧日志不许把新派的这一轮判死"


def test_old_verdict_is_not_this_rounds_completion(tmp_path: Path) -> None:
    """★ 旧判决同理：比 `since` 旧的判决不是这一轮的收工信号（归档失败时尤其要防）。

    ★ 卡 E22 改口径：旧件用 **5 秒前** 造（原来是"刚写完就拿 `time.time()` 当 since"）——
      文件时间戳粒度粗（实测 mtime 可落后墙钟 1.4 ms、NTFS 更新周期 ~15.6 ms），
      差几毫秒的写法考不出"旧件"，考的是时钟精度，本身就是条会闪的钉子。
    """
    _cb_verdict(tmp_path, "E7")
    assert wb_watch.probe_card("E7", tmp_path, time.time()).kind == wb_watch.FINISHED
    os.utime(_cb_verdict(tmp_path, "E7"), (time.time() - 5, time.time() - 5))
    assert wb_watch.probe_card("E7", tmp_path, time.time(),
                               since=time.time()).kind != wb_watch.FINISHED


def test_fresh_tolerates_a_file_timestamp_behind_the_wall_clock(tmp_path: Path) -> None:
    """★ 卡 E22：刚写的判决必须算这一轮 —— 哪怕文件 mtime 比 `since` 早几毫秒。

    真现场（2026-10-25 01:23 本机 `-n 4` 门禁）：`rebuild_registry` 把已收工的卡
    算进未完成 ⇒ `test_shared_registry_rebuilds_from_disk_after_restart` 偶发红。
    """
    _cb_verdict(tmp_path, "E7")
    mtime = (tmp_path / "gates" / "diag" / "wb-E7.verdict.txt").stat().st_mtime
    reg = wb_watch.register_cards(tmp_path, ["E7"], since=mtime + 0.0014)
    assert reg["cards"]["E7"] == wb_watch.STATE_DONE, reg["cards"]


def test_register_records_the_cutoff_and_ignores_the_old_round(tmp_path: Path) -> None:
    """登记时记下这一轮的开跑时刻：旧日志不算「判死」，refcount 照常算 1。"""
    _cb_log(tmp_path, "E7", age=3600)
    reg = wb_watch.register_cards(tmp_path, ["E7"], since=time.time())
    assert reg["refcount"] == 1
    assert reg["cards"]["E7"] == wb_watch.STATE_WATCHING
    assert "E7" in reg["since"]


# ---------------------------------------------------------------- 判据 6/7：合用看守的计数
def test_shared_refcount_three_cards_two_finish_then_one(tmp_path: Path) -> None:
    """★ 判据 7：派 3 张、2 张先出判决 ⇒ `refcount == 1`；最后一张 ⇒ `0` + `batch-done`。"""
    wb_watch.register_cards(tmp_path, ["301", "302", "303"])
    assert wb_watch.read_registry(tmp_path)["refcount"] == 3
    _cb_verdict(tmp_path, "301")
    _cb_verdict(tmp_path, "302")
    resolved, refcount = wb_watch.shared_tick(tmp_path, emit=lambda _s: None)
    assert sorted(resolved) == ["301", "302"]
    assert refcount == 1
    assert wb_watch.read_registry(tmp_path)["refcount"] == 1
    # 中间态**逐张落盘**：两张先完成的各有一个 .done + 一行 done 通知
    assert (tmp_path / "gates" / "diag" / "wb-301.done").is_file()
    assert (tmp_path / "gates" / "diag" / "wb-302.done").is_file()
    assert sum(1 for r in _rows(tmp_path) if r.get("state") == "done") == 2
    _cb_verdict(tmp_path, "303")
    _, refcount = wb_watch.shared_tick(tmp_path, emit=lambda _s: None)
    assert refcount == 0
    assert wb_watch.read_registry(tmp_path)["refcount"] == 0
    batch = [r for r in _rows(tmp_path) if r.get("state") == "batch-done"]
    assert len(batch) == 1 and batch[0]["cards"] == ["301", "302", "303"]
    # 再走一拍不许重复写 batch-done（计数已经是 0）
    wb_watch.shared_tick(tmp_path, emit=lambda _s: None)
    assert len([r for r in _rows(tmp_path) if r.get("state") == "batch-done"]) == 1


def test_shared_registry_rebuilds_from_disk_after_restart(tmp_path: Path) -> None:
    """★ 判据（抗崩溃）：看守重启 ⇒ 从磁盘重建计数，**已出判决的卡不算未完成**。"""
    wb_watch.register_cards(tmp_path, ["401", "402", "403"])
    _cb_verdict(tmp_path, "402")
    reg = wb_watch.rebuild_registry(tmp_path, pid=1234, heartbeat="2026-10-24T10:00:00")
    assert reg["refcount"] == 2, "已出判决的卡（402）不许再算进未完成"
    assert reg["cards"]["402"] == wb_watch.STATE_DONE
    assert reg["pid"] == 1234


# ---------------------------------------------------------------- 判据 8：看守自己死了
def test_stale_watcher_writes_event_and_exits_nonzero(tmp_path: Path) -> None:
    """★ 判据 8：心跳过期 + 还有卡没判决 ⇒ `watcher-stale` 事件 + 退非零（不留假象）。"""
    wb_watch.register_cards(tmp_path, ["501", "502"])
    stale_at = (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds")
    reg = wb_watch.read_registry(tmp_path)
    reg["pid"] = 999999
    reg["heartbeat"] = stale_at
    wb_watch.write_registry(tmp_path, reg)
    rc = wb_watch.main(["--cards", "501", "--mode", "shared", "--root", str(tmp_path),
                        "--timeout", "60"])
    assert rc == wb_watch.EXIT_STALE
    events = [r for r in _rows(tmp_path) if r.get("state") == "watcher-stale"]
    assert events and events[-1]["cards"] == ["501", "502"]
    assert events[-1]["heartbeat"] == stale_at


def test_fresh_heartbeat_is_not_stale(tmp_path: Path) -> None:
    """反例：心跳是新的 ⇒ 不是 stale（别把「还在盯」误判成「死了」去重起）。"""
    wb_watch.register_cards(tmp_path, ["601"])
    reg = wb_watch.read_registry(tmp_path)
    reg["pid"] = 4321
    reg["heartbeat"] = datetime.now().isoformat(timespec="seconds")
    wb_watch.write_registry(tmp_path, reg)
    assert wb_watch.registry_stale(tmp_path, timeout=60) is None
    assert wb_watch.watcher_alive(tmp_path, timeout=60)
