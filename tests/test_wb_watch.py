"""`tools/wb_watch.py`（卡 215 · T-G328）的测试 —— 给「一次盯多张卡、收工出结论」上护栏。

为什么值当测：「收工信号」判错的代价很实在 ——
  · 把**没跑完**的卡当成已完成 → 主控以为活干完了（本卡要治的就是「忘了挂看守」这件事）；
  · 把**还活着**的卡误判成「判死」 → 主控白重派 / 白慌（卡 052 的「已停（无判决）」同款教训）；
  · 只认**一种池**（另一种永远认不出）→ 码道那张卡永远等不到结论。

★ 全用**假时间源 + 假目录**（`FakeClock` 注入 clock/sleep、`tmp_path` 当仓库根）——
**不真等**，也不碰任何真实 `gates/diag`。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_watch  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上


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


#: 一份 `wb_dispatch` 判决文件的样子（第一行带退出码 + 开始 / 结束时刻）。
CB_VERDICT = (
    "card=213 第=1 次 退出码=0 会话=ses_x 开始于=2026-10-13T10:00:00 结束于=2026-10-13T10:12:00\n"
    "判决：正常收工（工人退出码 0）\n"
)


def _cb_verdict(root: Path, card: str, *, age: float = 0.0, text: str = CB_VERDICT) -> Path:
    return _write(root / "gates" / "diag" / f"wb-{card}.verdict.txt", text, age=age)


def _cb_log(root: Path, card: str, *, age: float = 0.0) -> Path:
    return _write(root / "gates" / "diag" / f"wb-{card}.jsonl",
                  '{"type":"system","subtype":"init","model":"m"}\n', age=age)


def _ca_logs(root: Path) -> Path:
    # 号池目录逐级向上找不到 ⇒ `dispatch_log_dirs` 退回 `<root>/infra/pool/logs`（tmp 里就是它）。
    return root / "infra" / "pool" / "logs"


def _ca_meta(root: Path, card: str, *, finished: bool = True, exit_code: int = 0,
             seconds: int = 600, verdict: str = "正常收工", age: float = 0.0,
             name: str | None = None) -> Path:
    body = json.dumps({"card": card, "finished": finished, "exit_code": exit_code,
                       "seconds": seconds, "verdict": verdict}, ensure_ascii=False)
    target = _ca_logs(root) / (name or f"card-{card}-20261013-100000.meta.json")
    return _write(target, body, age=age)


def _ca_log(root: Path, card: str, *, age: float = 0.0) -> Path:
    return _write(_ca_logs(root) / f"card-{card}-20261013-100000.jsonl", '{"type":"x"}\n', age=age)


# ---------------------------------------------------------------- 两种池的信号各自认得出
def test_codebuddy_verdict_is_a_finish_signal(tmp_path: Path) -> None:
    """CodeBuddy：`wb-<卡>.verdict.txt` 出现且非空 = 收工；判决首行 / 退出码 / 时长都读得出。"""
    _cb_verdict(tmp_path, "213")
    sig = wb_watch.probe_card("213", tmp_path, time.time())
    assert sig.kind == wb_watch.FINISHED
    assert sig.pool == "codebuddy"
    assert sig.exit_code == 0
    assert sig.duration_s == 720.0                    # 10:00:00 → 10:12:00
    assert sig.verdict_line.startswith("card=213")


def test_codearts_meta_finished_true_is_a_finish_signal(tmp_path: Path) -> None:
    """码道：`card-<卡>-*.meta.json` 里 `finished == true` = 收工；退出码 / 时长从 meta 读。"""
    _ca_meta(tmp_path, "900", finished=True, exit_code=0, seconds=600)
    sig = wb_watch.probe_card("900", tmp_path, time.time())
    assert sig.kind == wb_watch.FINISHED
    assert sig.pool == "codearts"
    assert sig.exit_code == 0
    assert sig.duration_s == 600.0
    assert sig.verdict_line == "正常收工"


def test_both_pools_are_seen_not_just_one(tmp_path: Path) -> None:
    """★ 反例（卡 215 §3）：只认**一种**池 ⇒ 另一张卡永远认不出 ⇒ **这条必须红**。

    两张卡各只有一条路的信号：213 只有 CodeBuddy 判决、900 只有码道 meta。
    一个写死只认其中一条路的实现，会让另一张判成「在跑 / 看不见信号」→ 这里的断言当场红 ——
    这正是「证明它真看得见两条路」的机器判据。
    """
    _cb_verdict(tmp_path, "213")
    _ca_meta(tmp_path, "900", finished=True)
    by = {c: wb_watch.probe_card(c, tmp_path, time.time()) for c in ("213", "900")}
    assert by["213"].kind == wb_watch.FINISHED and by["213"].pool == "codebuddy"
    assert by["900"].kind == wb_watch.FINISHED and by["900"].pool == "codearts"


# ---------------------------------------------------------------- 反例：空信号文件
def test_empty_verdict_file_is_not_finished(tmp_path: Path) -> None:
    """★ 反例（卡 215 §3）：信号文件是**空的** ⇒ 不许当「已完成」。

    空判决 + 刚动过的日志 → 只能是在跑，绝不能是收工。
    """
    _cb_verdict(tmp_path, "213", text="")
    _cb_log(tmp_path, "213", age=0)
    sig = wb_watch.probe_card("213", tmp_path, time.time())
    assert sig.kind != wb_watch.FINISHED
    assert sig.kind == wb_watch.RUNNING


def test_empty_meta_file_is_not_finished(tmp_path: Path) -> None:
    """★ 反例（码道侧）：空的 `meta.json`（半截写 / 坏文件）⇒ 不许当完成，也不许凭它判死。"""
    _ca_meta(tmp_path, "900", name="card-900-20261013-100000.meta.json")
    (_ca_logs(tmp_path) / "card-900-20261013-100000.meta.json").write_text("", encoding="utf-8")
    _ca_log(tmp_path, "900", age=0)
    sig = wb_watch.probe_card("900", tmp_path, time.time())
    assert sig.kind != wb_watch.FINISHED
    assert sig.kind != wb_watch.DEAD                    # 没证据不下「死」的结论（卡 052）
    assert sig.kind == wb_watch.RUNNING


# ---------------------------------------------------------------- 判死 / 超时 / 收工
def test_dead_card_returns_nonzero_and_names_it(tmp_path: Path) -> None:
    """★ 反例（卡 215 §3）：某张卡**没有信号且已判死** ⇒ 退出码非零并点名。

    CodeBuddy 日志静默超过 `pool.jobs.STALL_SECONDS`（480s）且没有判决 → `classify_job_state`
    判「断了」→ watcher 退 `EXIT_DEAD`（3）并点名这张卡。
    """
    _cb_log(tmp_path, "215", age=600)
    clock = FakeClock(time.time())
    said: list[str] = []
    rc = wb_watch.watch(["215"], root=tmp_path, timeout=7200, interval=45,
                        clock=clock, sleep=clock.sleep, emit=said.append)
    assert rc == wb_watch.EXIT_DEAD
    text = "\n".join(said)
    assert "215" in text and "判死" in text


def test_timeout_reports_and_lists_unfinished(tmp_path: Path) -> None:
    """超时路径：到点**如实报「超时」**并列出还没完的卡（错的是码，别硬等）。"""
    _cb_log(tmp_path, "213", age=0)                     # 刚动过 → 一直在跑
    clock = FakeClock(time.time())
    said: list[str] = []
    rc = wb_watch.watch(["213"], root=tmp_path, timeout=10, interval=5,
                        clock=clock, sleep=clock.sleep, emit=said.append)
    assert rc == wb_watch.EXIT_TIMEOUT
    text = "\n".join(said)
    assert "超时" in text and "213" in text


def test_all_finished_returns_zero_and_prints_conclusions(tmp_path: Path) -> None:
    """全收工 = 0，并打印每张卡的结论（判决首行 / 退出码 / 时长）。"""
    _cb_verdict(tmp_path, "213")
    _ca_meta(tmp_path, "900", finished=True)
    clock = FakeClock(time.time())
    said: list[str] = []
    rc = wb_watch.watch(["213", "900"], root=tmp_path, timeout=7200, interval=45,
                        clock=clock, sleep=clock.sleep, emit=said.append)
    assert rc == wb_watch.EXIT_FINISHED
    text = "\n".join(said)
    for token in ("收工结论", "判决首行", "退出码", "时长", "卡 213", "卡 900"):
        assert token in text


def test_heartbeat_says_where_it_is_now(tmp_path: Path) -> None:
    """★ 心跳里要有「现在到哪了」——不是一句「还在等」，而是每张卡此刻的读数。"""
    _cb_log(tmp_path, "213")                            # 没有判决、日志是现在 → 在跑
    clock = FakeClock(time.time())
    said: list[str] = []
    wb_watch.watch(["213"], root=tmp_path, timeout=10, interval=5,
                   clock=clock, sleep=clock.sleep, emit=said.append)
    beats = [ln for ln in said if ln.startswith("[心跳]")]
    assert beats, "必须打印心跳（真轮询，不许静默 sleep 固定时长假装查过了）"
    assert "213=" in beats[0]


def test_codearts_meta_finished_false_is_dead(tmp_path: Path) -> None:
    """码道侧判死：`meta.json` 存在但 `finished` 不是 `true`（被看门狗 / 超时掐了）→ 判死。"""
    _ca_meta(tmp_path, "900", finished=False, verdict="被掐（超时或静默看门狗）")
    sig = wb_watch.probe_card("900", tmp_path, time.time())
    assert sig.kind == wb_watch.DEAD
    assert "被掐" in sig.detail


def test_blind_card_is_not_treated_as_finished(tmp_path: Path) -> None:
    """两条路都看不见这张卡 → 「看不见信号」（★ 不许当成已完成，也不许当成判死）。"""
    sig = wb_watch.probe_card("999", tmp_path, time.time())
    assert sig.kind == wb_watch.BLIND


# ---------------------------------------------------------------- 批次 → 卡号
def test_resolve_batch_reads_member_ids(tmp_path: Path) -> None:
    """`--batch B-XXX` 收整批：读预声明的 `[[member]].id`（卡号）。"""
    manifest = tmp_path / "B-T.toml"
    manifest.write_text(
        'id = "B-T"\nwhy = "测试"\n'
        '[[member]]\nid = "215"\nlayer = "派活层"\npaths = ["tools/wb_watch.py"]\n'
        '[[member]]\nid = "216"\nlayer = "队列层"\npaths = ["tools/wb_queue_audit.py"]\n',
        encoding="utf-8")
    assert wb_watch.resolve_batch("B-T", manifest_path=manifest) == ["215", "216"]


def test_resolve_batch_missing_manifest_raises(tmp_path: Path) -> None:
    """预声明不在 ⇒ 拒绝（不猜空批）——`BatchWatchError`，CLI 退 2。"""
    import pytest

    with pytest.raises(wb_watch.BatchWatchError):
        wb_watch.resolve_batch("B-NOPE", manifest_path=tmp_path / "B-NOPE.toml")


# ---------------------------------------------------------------- 交付面：该挂哪个看守
def test_dispatch_detach_reply_points_to_wb_watch(tmp_path: Path, monkeypatch, capsys) -> None:
    """卡 215 §2：`--detach` 成功回话里要**多加一行**指向该挂哪个看守（只加一行，不改派活逻辑）。"""
    import wb_dispatch as wd

    monkeypatch.setattr(wd, "ROOT", tmp_path)
    monkeypatch.setattr(wd, "paths", lambda *a, **k: (tmp_path / "node", tmp_path / "cli"))
    monkeypatch.setattr(wd, "preflight", lambda *a, **k: ([], tmp_path / "wb-215.jsonl"))
    monkeypatch.setattr(wd, "preflight_auth", lambda *a, **k: (wd.AuthState.OK, "登录自检通过"))
    monkeypatch.delenv("TF_DISPATCH_PORT_BASE", raising=False)
    thrown: list[list[str]] = []
    monkeypatch.setattr(wd, "spawn_detached",
                        lambda argv, log: thrown.append(list(argv)) or 4242)
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "215", "--spec", "spec.md",
                                      "--detach", "--execute"])
    assert wd.main() == 0
    out = capsys.readouterr().out
    assert len(thrown) == 1, "应当只扔一次"
    assert "wb_watch.py --cards 215" in out, out
