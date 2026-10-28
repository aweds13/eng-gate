r"""`tools/trae_watch.py`（卡 E29 · T-AG483）的测试 —— 给「Trae 停了可发现」上护栏。

为什么值当测：把「停了」判错的代价都很实在 ——
  · **被手动终止**当成「还在跑」⇒ 卡树一小时零改动没人知道（10:39 那次就是）；
  · **一轮跑完交还**没有 `.done` ⇒ 主控以为活没完，或者干脆以为它还在干；
  · **空转塌陷**当成在跑 ⇒ 一直占着一个并发位（比停了更贵）；
  · 宁可「只读」的看守偷偷写了盘 ⇒ 下一次 `--stale-min` 调参就把现场搞脏。

★ 全用**假采样 + 假时间源**（`ScriptedSampler` 注入 sample、`FakeClock` 注入 clock/sleep）——
**不真等、不碰 Trae、不碰任何真实 `gates/diag`**。

跑法：`python -X utf8 -m pytest tests/test_trae_watch.py -q -o addopts=`
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import trae_watch  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上
import wb_watch  # noqa: E402 —— 事件面真源（判它是不是真被复用）

STOP = trae_watch.ICON_STOP
UP = trae_watch.ICON_ARROW_UP
TERMINATED = trae_watch.TERMINATED_HINT


# ---------------------------------------------------------------- 工具根 ≠ 数据根（卡 A326）
def test_events_follow_pipe_data_not_the_script_location(tmp_path):
    """卡树里跑看守，事件不许写进卡树 —— 工具根给 mjs，数据根给事件。

    为什么值当测：E29 第一版就是 `ROOT = Path(__file__).parent.parent`，我在 `.wt/E29` 里跑一次
    真机采样，`trae-watch.jsonl` 直接落进了**卡树**的 `gates/diag/`（主控看的是数据根，等于没落）。
    ★ 判据必须能**分辨**两个根：这里另起一个进程，把 `PIPE_DATA` 指到临时目录 ——
    数据根必须跟着 `PIPE_DATA` 走，工具根必须仍是脚本所在那棵树。
    """
    import os
    import subprocess

    data = tmp_path / "data-root"
    data.mkdir()
    code = (
        "import sys;"
        f"sys.path.insert(0, r'{ROOT / 'tools'}');"
        "import trae_watch as t;"
        "print(t.ROOT);print(t.TOOL_ROOT)"
    )
    env = dict(os.environ, PIPE_DATA=str(data))
    done = subprocess.run([sys.executable, "-X", "utf8", "-c", code],
                         capture_output=True, text=True,
                         encoding="utf-8", errors="replace", env=env,
                         check=True)
    out = done.stdout
    got_data, got_tool = [Path(line.strip()) for line in out.strip().splitlines()]
    assert got_data == data.resolve(), "事件根要跟 PIPE_DATA 走（经 pipe_root）"
    assert got_tool == ROOT, "工具根仍是脚本所在树（mjs 住这儿）"
    import inspect

    default = inspect.signature(trae_watch.sample_trae).parameters["root"].default
    assert default == trae_watch.TOOL_ROOT, "采样默认走工具根，不是数据根"


# ---------------------------------------------------------------- 假采样 / 假时间源
class FakeClock:
    """假时间源：`clock()` 回当前秒；`sleep` 只把它往前推，**不真等**。"""

    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def frame(icon: str, body: str, *, task: str = "卡 E28 真活") -> dict:
    """一条**与 `trae_pool.mjs sample --json` 同形**的采样（字段由 JS 侧算好）。"""
    return {
        "ok": True,
        "task": task,
        "icon": icon,
        "running": icon == STOP,
        "bodyLen": len(body),
        "bodyHash": hashlib.md5(body.encode("utf-8")).hexdigest()[:8],
        "terminated": TERMINATED in body,
    }


class ScriptedSampler:
    """按剧本吐采样（用完后重复最后一条）—— 判据仍是真判，只是「面板」换成了剧本。"""

    def __init__(self, frames: list[dict]) -> None:
        assert frames, "剧本不能是空的"
        self.frames = list(frames)
        self.calls = 0

    def __call__(self) -> dict:
        index = min(self.calls, len(self.frames) - 1)
        self.calls += 1
        return dict(self.frames[index])


def run(tmp: Path, frames: list[dict], **kwargs):
    """跑一遍 `watch()`（假采样 + 假时钟），返回（退出码, 打出来的行）。"""
    clock = FakeClock(time.time())
    said: list[str] = []
    rc = trae_watch.watch(
        task="E28", card="E28", root=tmp, sample=ScriptedSampler(frames),
        clock=clock, sleep=clock.sleep, emit=said.append, **kwargs,
    )
    return rc, said


def notifications(tmp: Path) -> list[dict]:
    path = tmp / "gates" / "diag" / "notifications.jsonl"
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ---------------------------------------------------------------- 四态各一条
def test_finished_writes_done_event(tmp_path: Path) -> None:
    """`finished`：图标 stop → arrow-up ⇒ 落 `wb-<卡>.done` + 通知流 `state:"done"`，退 0。"""
    rc, said = run(tmp_path, [frame(STOP, "干活中"), frame(STOP, "干活中"), frame(UP, "干活中")],
                   write_done=True, interval=30, timeout=600)
    assert rc == trae_watch.EXIT_FINISHED
    done = tmp_path / "gates" / "diag" / "wb-E28.done"
    assert done.is_file(), "\n".join(said)
    row = json.loads(done.read_text(encoding="utf-8"))
    assert row["card"] == "E28"
    assert row["task"] == "卡 E28 真活", "task 用面板里的真标题（采样的 task），不是 --task 子串"
    assert row["exit_code"] == 0
    assert notifications(tmp_path)[-1]["state"] == "done"


def test_terminated_writes_stopped_and_exits_five(tmp_path: Path) -> None:
    """`terminated`：正文出现「手动终止输出」⇒ `trae-<卡>.stopped` + `trae-stopped`，退 5。"""
    rc, said = run(tmp_path, [frame(STOP, f"我在写代码… {TERMINATED}")],
                   write_done=True, interval=30, timeout=600)
    assert rc == trae_watch.EXIT_STOPPED, "\n".join(said)
    stopped = tmp_path / "gates" / "diag" / "trae-E28.stopped"
    assert stopped.is_file()
    row = json.loads(stopped.read_text(encoding="utf-8"))
    assert row["state"] == "terminated" and TERMINATED in row["why"]
    assert notifications(tmp_path)[-1]["state"] == "trae-stopped"
    assert not (tmp_path / "gates" / "diag" / "wb-E28.done").exists(), "被掐了不许写 .done"


def test_stalled_writes_stopped_and_exits_five(tmp_path: Path) -> None:
    """`stalled`：图标仍 stop、正文 ≥ `--stale-min` 没变
    ⇒ 同一个 `.stopped` + `trae-stalled`，退 5。

    ★ 门槛用**真默认值**（`trae_watch.DEFAULT_STALE_MIN`）：把默认调成 `0`（= 关掉空转判定）
      这条当场红 —— 卡 E29 §3 的第一条反向验证。
    """
    same = "同一段正文"
    rc, said = run(tmp_path, [frame(STOP, same)], write_done=True,
                   interval=300, timeout=3600, stale_min=trae_watch.DEFAULT_STALE_MIN)
    assert rc == trae_watch.EXIT_STOPPED, "\n".join(said)
    stopped = tmp_path / "gates" / "diag" / "trae-E28.stopped"
    assert stopped.is_file()
    assert json.loads(stopped.read_text(encoding="utf-8"))["state"] == "stalled"
    assert notifications(tmp_path)[-1]["state"] == "trae-stalled"


def test_running_only_writes_notifications(tmp_path: Path) -> None:
    """`running`：只写通知流（含 `bodyLen`），**不落 mark**；到点超时退 4（没结论不算有结果）。"""
    rc, said = run(tmp_path, [frame(STOP, "第一段"), frame(STOP, "第二段")],
                   write_done=True, interval=60, timeout=120)
    assert rc == trae_watch.EXIT_TIMEOUT, "\n".join(said)
    diag = tmp_path / "gates" / "diag"
    assert not (diag / "wb-E28.done").exists()
    assert not (diag / "trae-E28.stopped").exists()
    states = [row["state"] for row in notifications(tmp_path)]
    assert "trae-running" in states
    running = [row for row in notifications(tmp_path) if row["state"] == "trae-running"]
    assert all("bodyLen" in row for row in running)


# ---------------------------------------------------------------- 幂等
def test_stopped_is_idempotent(tmp_path: Path) -> None:
    """`.stopped` 幂等：重复写不追加第二行（文件一行、通知一行）。"""
    body = frame(STOP, TERMINATED)
    first = trae_watch.write_stopped_event(tmp_path, "E28", "terminated", why="掐了", sample=body)
    second = trae_watch.write_stopped_event(tmp_path, "E28", "terminated", why="掐了", sample=body)
    assert first == second
    path = tmp_path / "gates" / "diag" / "trae-E28.stopped"
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1
    rows = [r for r in notifications(tmp_path) if r["state"] == "trae-stopped"]
    assert len(rows) == 1, f"幂等破了，通知写了 {len(rows)} 行"


def test_done_is_idempotent(tmp_path: Path) -> None:
    """`.done` 幂等：重复写不追加第二行（看守重启 / 两形态并发都不许写两次）。"""
    body = frame(UP, "收工")
    first = trae_watch.write_done_event(tmp_path, "E28", task="E28", sample=body)
    second = trae_watch.write_done_event(tmp_path, "E28", task="E28", sample=body)
    assert first == second
    path = tmp_path / "gates" / "diag" / "wb-E28.done"
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1
    rows = [r for r in notifications(tmp_path) if r["state"] == "done"]
    assert len(rows) == 1, f"幂等破了，通知写了 {len(rows)} 行"


# ---------------------------------------------------------------- 只读 / 行格式 / JSON
def test_without_write_done_writes_nothing(tmp_path: Path) -> None:
    """★ 不给 `--write-done` ⇒ **一个字节都不写**（连 `gates/` 目录都不许建）。"""
    rc, said = run(tmp_path, [frame(STOP, "干活中"), frame(UP, "干活中")],
                   write_done=False, interval=30, timeout=600)
    assert rc == trae_watch.EXIT_FINISHED, "\n".join(said)
    assert not (tmp_path / "gates").exists(), "只读模式下居然建了 gates/（写盘了）"


def test_done_row_is_isomorphic_with_wb_watch(tmp_path: Path) -> None:
    """`.done` 六字段与 `wb_watch` **逐字同构**；通知行的基本键名也与它一致。"""
    base = wb_watch.write_card_event(tmp_path, "E7", wb_watch.STATE_DEAD)
    assert set(base) == {"at", "card", "state", "log", "report"}, base

    trae_watch.write_done_event(tmp_path, "E28", task="E28", sample=frame(UP, "收工"))
    done = json.loads((tmp_path / "gates" / "diag" / "wb-E28.done").read_text(encoding="utf-8"))
    assert set(done) == {"card", "task", "exit_code", "at", "log", "report"}, done

    row = notifications(tmp_path)[-1]
    assert set(base) <= set(row), f"通知行缺 wb_watch 的键：{set(base) - set(row)}"
    for key in ("at", "card", "state", "log", "report"):
        assert isinstance(row[key], type(base[key])), f"{key} 的类型与 wb_watch 不一致"


def test_json_lines_have_fixed_keys(tmp_path: Path, capsys) -> None:
    """`--json`：每拍一行，键名固定
    （`at` / `card` / `state` / `icon` / `bodyLen` / `bodyHash` / `why`）。"""
    clock = FakeClock(time.time())
    rc = trae_watch.watch(
        task="E28", card="E28", root=tmp_path,
        sample=ScriptedSampler([frame(STOP, "甲"), frame(UP, "甲")]),
        clock=clock, sleep=clock.sleep, write_done=False,
        interval=30, timeout=600, as_json=True,
    )
    assert rc == trae_watch.EXIT_FINISHED
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(lines) >= 2, lines
    expected = {"at", "card", "state", "icon", "bodyLen", "bodyHash", "why"}
    for line in lines:
        row = json.loads(line)
        assert set(row) == expected, row
    assert [json.loads(ln)["state"] for ln in lines][-1] == "finished"


def test_event_surface_is_reused_not_rebuilt() -> None:
    """★ 事件面**只有一份真源**：`diag_dir` / `done_path` / `append_notification` 是 wb_watch 的，
    本文件不许再定义一份（卡 E29「不许另起一套通知文件」）。"""
    assert trae_watch.wb_watch is wb_watch
    src = (ROOT / "tools" / "trae_watch.py").read_text(encoding="utf-8")
    for name in ("diag_dir", "done_path", "append_notification"):
        assert f"def {name}(" not in src, f"trae_watch.py 里又造了一份 {name}()"
