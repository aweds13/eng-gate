"""卡 A349（T-AG552）：全都忙就歇一会儿再问 —— magpie 耐心层的算术与接入。

为什么值当测：耐心层是**行为变化**（默认就开），它同时决定「歇多久」和「还能歇多久」，
还夹在「额度判据」与「卡 045 的 `--retry` 界」之间。这三样错任何一样，代价都不是报错
而是「悄悄多睡 5 分钟」或「悄悄把轮次烧光」——所以算术三个边界、目录外两种额度错、
预算耗尽后的退出码、以及 `-1` 的回退开关，都得各有一颗钉子。

★ 与本卡的验收表一一对应（表里 10 条 + 2 条补的，见下）：
  ① `test_patience_waits_three_branches`（判据 2 三支）
  ② `test_replan_wait_doubles`（判据 3 前四轮）
  ③ `test_replan_wait_caps_at_replan_longest`（判据 3 封顶）
  ④ `test_replan_wait_never_shorter_than_retry_after`（判据 3 的 max）
  ⑤ `test_replan_wait_capped_beats_retry_after`（soonest 只做下限不做上限）
  ⑥ `test_credit_kind_never_enters_patience`（判据 4 只放「限流」进门）
  ⑦ `test_patience_budget_spent_keeps_the_original_exit`（判据 4 预算耗尽走原出口）
  ⑧ `test_patience_off_matches_today`（判据 5 的 `-1` 回退开关）
  ⑨ `test_round_wait_untouched`（判据 6 两套语义不合并、不互调）
  ⑩ `test_reverse_patience_must_not_apply_to_credit`（反向：额度错不许吃耐心预算）
  ⑪ `test_patience_help_names_minus_one_as_off`（判据 5 文案：`-1 = 关` 必须在 `--help` 里）
  ⑫ `test_replan_wait_rejects_negative_round`（判据 3 的 `ValueError`）
"""

from __future__ import annotations

import inspect
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_TOOLS = ROOT / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

# ★ 不用「先 sys.path 再 import + 闭嘴注释」那套（本仓规矩不许闭嘴注释）。
#   `__import__` 是**表达式**，不是模块级 import 语句 ⇒ 不触发 E402，也就不需要闭嘴。
pool_quota = __import__("pool_quota")
wd = __import__("wb_dispatch")

#: `wd.main()` 里走的是 `from tools import wb_session` —— 夹具得 patch **同一个**模块对象。
wb_session = __import__("tools.wb_session", fromlist=["wb_session"])

_QUOTA_MSG = "使用量已超出频率限制"
_RESET_PAST = "2026-09-27 07:38"        # 过去的时间：`wait_seconds` 折出负数 ⇒ 不真睡


def _reset_in(seconds: int) -> str:
    """造一个「`seconds` 秒之后」的重置时间串（`parse_reset` 吃的是 `YYYY-MM-DD HH:MM`）。"""
    return (datetime.now() + timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M")
_SUCCESS = json.dumps({"type": "result", "subtype": "success", "is_error": False,
                       "result": "干完了"}, ensure_ascii=False)
_SANDBOX_CARD_IDS = ("001",)
_SANDBOX_BACKLOG = """[base]
reviewed = "sandbox"

[[cards]]
id = "001"
task = "T-001"
title = "沙箱卡 001"
tree = ""
spec = "spec.md"
files = ["sandbox-001.md"]
"""


@pytest.fixture(autouse=True)
def isolated_session_ledger(tmp_path: Path, monkeypatch) -> Path:
    """`wd.main()` 会写「卡归窗口」账本 —— 隔离到 `tmp_path`，别和落地链抢真账本。"""
    ledger = tmp_path / "gates" / "diag" / "session-leases.json"
    monkeypatch.setattr(wb_session, "LEDGER", ledger)
    return ledger


@pytest.fixture()
def sandbox(tmp_path: Path, monkeypatch) -> Path:
    """一个「像仓库」的临时根（与 `tests/test_wb_dispatch.py` 的沙箱同款，只留用得上的）。"""
    (tmp_path / "spec.md").write_text("卡规格", encoding="utf-8")
    node = tmp_path / "node.exe"
    cli = tmp_path / "codebuddy"
    node.write_text("", encoding="utf-8")
    cli.write_text("", encoding="utf-8")
    monkeypatch.setattr(wd, "ROOT", tmp_path)
    monkeypatch.setattr(wd, "paths", lambda *a, **k: (node, cli))
    monkeypatch.setattr(wd, "git_dirty", lambda *a, **k: [])
    monkeypatch.setattr(wd, "auth_ok", lambda *a, **k: (True, "登录自检通过"))
    monkeypatch.setenv("TF_GATE_MIN_FREE_GB", "0")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "workbacklog.toml").write_text(_SANDBOX_BACKLOG, encoding="utf-8")
    monkeypatch.setenv("TF_POOL_REGISTRY", str(tmp_path / "gates" / "diag" / "pool-registry.json"))
    real_root = Path(wd.__file__).resolve().parents[2]
    projects_toml = tmp_path / "projects.toml"
    projects_toml.write_text(chr(10).join([
        "[project.sandbox]",
        'name = "沙箱"',
        f'root = "{tmp_path.as_posix()}"',
        "memory = []",
        "layers = []",
        f'tree_prefixes = ["{tmp_path.as_posix()}", ".wt/"]',
        'queue = ""',
        'ledger = ""',
        'cards = ""',
        "",
        "[project.sandbox-ancestor]",
        'name = "沙箱（祖先）"',
        f'root = "{real_root.parent.as_posix()}"',
        "memory = []",
        "layers = []",
        f'tree_prefixes = ["{tmp_path.as_posix()}"]',
        'queue = ""',
        'ledger = ""',
        'cards = ""',
    ]) + chr(10), encoding="utf-8")
    monkeypatch.setenv("TF_PROJECTS_TOML", str(projects_toml))
    monkeypatch.setattr(wd.pool_registry, "read_lock_body", lambda *a, **k: "")
    return tmp_path


def _quota_event(*, kind: str, reset_at: str | None = None) -> str:
    """造一条额度错 result 事件：`限流` 带「将在 <时间> 重置」，`余额耗尽` 不带。"""
    when = _RESET_PAST if reset_at is None else reset_at
    message = _QUOTA_MSG if kind == "余额耗尽" else f"{_QUOTA_MSG}，将在 {when} 重置"
    errors = {"status": 429, "code": 6004, "category": "quota", "message": message}
    return json.dumps({"type": "result", "subtype": "error_during_execution",
                       "result": "", "errors": errors}, ensure_ascii=False)


# ====================================================================== 判据 2：三支


def test_patience_waits_three_branches() -> None:
    """① `None`/`-1` ⇒ 0（关不是最短）；`0` ⇒ 60（没配不是关）；其余 ⇒ `min(x, 240)`。"""
    assert pool_quota.PATIENCE_OFF == -1
    assert pool_quota.PATIENCE_DEFAULT_S == 60
    assert pool_quota.PATIENCE_LONGEST_S == 240
    assert pool_quota.patience_waits(None) == 0, "没给参数 = 关"
    assert pool_quota.patience_waits(-1) == 0, "-1 是关，不是「最短」"
    assert pool_quota.patience_waits(-3600) == 0, "任何负数都是关"
    assert pool_quota.patience_waits(0) == pool_quota.PATIENCE_DEFAULT_S, "0 是「没配」⇒ 60"
    assert pool_quota.patience_waits(1) == 1
    assert pool_quota.patience_waits(240) == 240, "正好到上限，不动"
    assert pool_quota.patience_waits(3600) == 240, "配 3600 也只给 240"


# ================================================================== 判据 3：递增与封顶


def test_replan_wait_doubles() -> None:
    """② 第 0/1/2/3 轮：2 / 4 / 8 / 16 秒（`retryPause << (n+1)`）。"""
    assert [pool_quota.replan_wait(n) for n in range(4)] == [2, 4, 8, 16]


def test_replan_wait_caps_at_replan_longest() -> None:
    """③ 第 4 轮起封顶 30 秒（`replanLongest() = 30 * retryPause`），再往后也不涨。"""
    assert pool_quota.REPLAN_LONGEST_S == 30 * pool_quota.RETRY_PAUSE_S
    assert [pool_quota.replan_wait(n) for n in (4, 5, 12)] == [30, 30, 30]


def test_replan_wait_never_shorter_than_retry_after() -> None:
    """④ 成员自报的续期只做**下限**：`soonest_s` 比本轮间隔大就听它的。"""
    assert pool_quota.replan_wait(0, soonest_s=45) == 45, "本轮 2 秒，但人家说 45 秒后再来"
    assert pool_quota.replan_wait(4, soonest_s=10) == 30, "本轮已 30 秒，10 秒不许把它压短"


def test_replan_wait_capped_beats_retry_after() -> None:
    """⑤ `soonest_s` 只做下限**不做上限**：报 9999 就等 9999，不许被 30 秒截断。"""
    assert pool_quota.replan_wait(0, soonest_s=9999) == 9999


def test_retry_after_floor_reaches_the_sleep(sandbox: Path, monkeypatch, capsys) -> None:
    """★ 真路钉子：自报续期要**真的**决定这一歇 —— 不是只活在 `replan_wait` 的入参里。

    做法：让 reset 落在未来（约 2 分钟后），预算给足，看 `time.sleep` 实际被喂了几秒。
    第 0 轮的递增间隔只有 2 秒，所以只要真睡到 **≥55 秒**，就只可能是「自报续期做下限」
    在起作用。若接入处把 `soonest_s` 折成 0（`wait_seconds(..., 0)` 恒 0），这里只会看到 2。
    """
    sleeps: list[int] = []

    def runner(cmd, log, errlog, **kwargs):
        log.parent.mkdir(parents=True, exist_ok=True)
        events = [_quota_event(kind="限流", reset_at=_reset_in(120)) if len(sleeps) < 1
                  else _SUCCESS]
        log.write_text("\n".join(events) + "\n", encoding="utf-8")
        errlog.write_text("", encoding="utf-8")
        return 0, "", "", "sid-x"

    monkeypatch.setattr(wd, "run_worker", runner)
    monkeypatch.setattr(wd, "quota_probe_ok", lambda *a, **k: (False, "额度仍挂"))
    monkeypatch.setattr(wd, "next_whitelist_model", lambda *a, **k: None)
    monkeypatch.setattr(wd.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute", "--quota-wait", "0",
                                      "--patience", "240"])
    wd.main()
    assert sleeps, "这一轮必须真去睡（被 monkeypatch 记下来了）"
    assert sleeps[0] >= 55, f"自报 120 秒后续期 ⇒ 应该真睡到那个点，实际只睡了 {sleeps[0]}s"


def test_replan_wait_rejects_negative_round() -> None:
    """⑫ 没有「第 -1 轮」：负数轮次必须炸，不许悄悄变成一次短睡。"""
    with pytest.raises(ValueError, match="负"):
        pool_quota.replan_wait(-1)


# ================================================================ 判据 6：两套语义不合并


def test_round_wait_untouched() -> None:
    """⑨ `round_wait()` 还是「按记录算一次等多久」：clamp 60..600、文案不变、与耐心不互调。"""
    now = "2026-10-30T12:00:00+08:00"
    assert pool_quota.round_wait("2026-10-30T12:10:00+08:00", now=now) == (
        600, f"最早续期 + {pool_quota.WAIT_MARGIN_S}s"
             f"（clamp 到 {pool_quota.WAIT_MIN_S}..{pool_quota.WAIT_MAX_S}）")
    assert pool_quota.round_wait("2026-10-30T12:00:05+08:00", now=now)[0] == 60, "低于下限抬到 60"
    assert pool_quota.round_wait("2026-10-30T12:01:40+08:00", now=now)[0] == 130, "区间内照加 30"
    assert pool_quota.round_wait(None)[0] == 600
    assert pool_quota.round_wait("不是时间") == (600, "未知续期 ⇒ 睡满上限")
    patience_src = inspect.getsource(pool_quota.patience_waits)
    replan_src = inspect.getsource(pool_quota.replan_wait)
    for src in (patience_src, replan_src):
        assert "WAIT_MIN_S" not in src and "WAIT_MAX_S" not in src, "两套 clamp 不许串台"
    # ★ 注释/docstring 里提到名字不算调用 —— 查**真被加载的全局名**（`co_names` 才是调用面）。
    for fn in (pool_quota.patience_waits, pool_quota.replan_wait):
        names = set(fn.__code__.co_names)
        assert "round_wait" not in names, names
        assert "WAIT_MIN_S" not in names and "WAIT_MAX_S" not in names, names
        assert "WAIT_MARGIN_S" not in names, names
    rw = pool_quota.round_wait.__code__
    assert "patience" not in set(rw.co_names) | set(rw.co_varnames) | set(rw.co_freevars)
    assert "replan_wait" not in set(rw.co_names), "round_wait 不许反向调耐心"


# ============================================================ 判据 5：`--patience` 文案


def test_patience_help_names_minus_one_as_off() -> None:
    """⑪ `--help` 必须写清「-1 = 关」，且值域与常量同源（写死就咬）。"""
    helps = {a.dest: (a.help or "") for a in wd.build_parser()._actions}
    assert "patience" in helps, "--patience 要进 parser"
    assert "-1 = 关" in helps["patience"], helps["patience"]
    assert str(pool_quota.PATIENCE_DEFAULT_S) in helps["patience"], "默认预算要从常量来"
    assert str(pool_quota.PATIENCE_LONGEST_S) in helps["patience"], "上限要从常量来"


# =========================================== 判据 4：接入（只放限流进门、预算耗尽走原出口）


def _run(sandbox: Path, monkeypatch, capsys, *, argv_extra: list[str],
         kinds: list[str], probe_ok: bool = True) -> tuple[int, str, str, list[list[str]]]:
    """跑一次 `wd.main()`：第 i 轮回 `kinds[i]` 的额度事件，用完后回正常成功。"""
    calls: list[list[str]] = []
    slept: list[int] = []

    def runner(cmd, log, errlog, **kwargs):
        calls.append(list(cmd))
        log.parent.mkdir(parents=True, exist_ok=True)
        idx = len(calls) - 1
        events = [_quota_event(kind=kinds[idx])] if idx < len(kinds) else [_SUCCESS]
        log.write_text("\n".join(events) + "\n", encoding="utf-8")
        errlog.write_text("", encoding="utf-8")
        return 0, "", "", f"sid-{len(calls)}"

    monkeypatch.setattr(wd, "run_worker", runner)
    monkeypatch.setattr(wd, "quota_probe_ok", lambda *a, **k: (probe_ok, "探测通过"))
    monkeypatch.setattr(wd.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute", "--quota-wait", "0", *argv_extra])
    code = wd.main()
    captured = capsys.readouterr()
    return code, captured.out, captured.err, calls


def test_credit_kind_never_enters_patience(sandbox: Path, monkeypatch, capsys) -> None:
    """⑥ 「余额耗尽」是硬挡：等多久都不会好 ⇒ 一个字的 `[耐心]` 都不许出。"""
    code, _out, err, calls = _run(sandbox, monkeypatch, capsys,
                                  argv_extra=["--retry", "1", "--patience", "60"],
                                  kinds=["余额耗尽", "余额耗尽"])
    assert code == 7, "额度续跑到界，退出码照旧 7"
    assert len(calls) == 2
    assert "[耐心]" not in err, err
    assert "余额耗尽" in err


def test_patience_budget_spent_keeps_the_original_exit(
        sandbox: Path, monkeypatch, capsys) -> None:
    """⑦ 预算装不下这一歇 ⇒ 不再重问，且**照原样**走卡 045 的出口（退出码 7 不变）。"""
    code, _out, err, calls = _run(sandbox, monkeypatch, capsys,
                                  argv_extra=["--retry", "1", "--patience", "1"],
                                  kinds=["限流", "限流", "限流"])
    assert code == 7, "预算耗尽不是新出口：还是卡 045 那个 7"
    assert len(calls) == 2, "第 1 轮续跑在 --retry 界内；第 2 轮再报额度 ⇒ 到界"
    assert "预算只剩 1s" in err, err
    assert "第 1 次重问" not in err, "预算装不下就不许自我安慰地记一轮"
    stop = (sandbox / "gates" / "diag" / "wb-001.r2.verdict.txt").read_text(encoding="utf-8")
    assert "额度续跑到界" in stop


def test_reverse_patience_must_not_apply_to_credit(sandbox: Path, monkeypatch, capsys) -> None:
    """⑩ 反向钉子：先「余额耗尽」再「限流」—— 硬挡那一轮不许把耐心轮次/预算吃掉。

    判据写的是 `quota.get("kind") == "限流"`。若放宽成「只要 quota 不是 None」，
    第一轮（余额耗尽）就会先记一轮重问 ⇒ 下面看到的是「第 2 次重问」。所以这里数次数：
    整场只许出现**一次** `[耐心]`，且是第 1 次。
    """
    code, _out, err, calls = _run(sandbox, monkeypatch, capsys,
                                  argv_extra=["--retry", "2", "--patience", "60"],
                                  kinds=["余额耗尽", "限流"])
    assert code == 0, "第三个回合正常成功 ⇒ 收下"
    assert len(calls) == 3
    assert err.count("[耐心]") == 1, err
    assert "第 1 次重问：最多歇 2s" in err, err
    assert "第 2 次重问" not in err, "余额耗尽那一轮不许先吃掉一轮重问"


def test_patience_off_matches_today(sandbox: Path, monkeypatch, capsys) -> None:
    """⑧ `--patience -1` = 今天的代码：与「耐心预算恒为 0」的基线逐字相同。

    ★ 手上没有旧代码副本，基线这么造：`patience_waits` 唯一的作用就是算 `patience_left_s`，
    而新代码里**唯一**的新闸是 `patience_left_s > 0`。桩返回 0 ⇒ 那道闸必不开 ⇒ 走的就是
    旧代码的路。所以这不是「假装测过」，而是「把新增的那道闸关死」再比 输出/退出码/命令。
    """
    def clear() -> None:
        """每次跑完清场：判决 / 回合日志 / 账本 / 会话都不许串场。"""
        for p in (sandbox / "gates" / "diag").glob("*"):
            if p.is_file():
                p.unlink()

    # 三跑：① 默认（0 ⇒ 60 秒预算，本卡落地当天的新行为）② `-1`（关）③ 基线（闸关死）
    results: dict[str, tuple[int, str, str, list[list[str]]]] = {}
    for label, extra in (("默认", []), ("关", ["--patience", "-1"])):
        clear()
        results[label] = _run(sandbox, monkeypatch, capsys, argv_extra=extra,
                              kinds=["限流", "限流", "限流"])
    clear()
    with monkeypatch.context() as patched:
        patched.setattr(pool_quota, "patience_waits", lambda *a, **k: 0)
        results["基线"] = _run(sandbox, patched, capsys, argv_extra=[],
                               kinds=["限流", "限流", "限流"])

    off, base, default = results["关"], results["基线"], results["默认"]
    assert off[0] == base[0] == 7
    assert off[1] == base[1], "stdout 要逐字相同"
    assert off[2] == base[2], f"stderr 要逐字相同：\n关：{off[2]}\n基：{base[2]}"
    assert off[3] == base[3], "派出去的命令要逐字相同"
    assert "[耐心]" not in off[2]
    assert default[2] != base[2] and "[耐心] 第 1 次重问" in default[2], \
        "默认 0 ⇒ 60 秒预算**真的**多问一轮 —— 这是行为变化，别当纯新增"
