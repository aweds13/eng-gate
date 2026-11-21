r"""每账号并发闸的测试 —— 八条钉子（卡 A339 · T-AG541）。

被测：`tools/pool/guards.py` 的 `lane_guard` + `tools/pool/lanes.py` + `registry.reserve` 的接入。

**为什么值当测**：一个号被同时派几张卡，今天没有任何判据 —— 两条不同的批 / 两个人各起一次派活，
同一个号就会同时出现在两棵树上，一起撞 vendor 限流、一起抢本机内存与端口。本卡的判据是
「先给租约一个**可判的键**（`account`），再按这个键数在途」。八条钉子分别钉住：到上限会咬、
`limit=0` 是关闸不是全拒、别的账号不误伤、没点名账号不过问、坏配置不许静默当空、
配置缺失就是没闸、`account` 是独立可判的键、以及**死租约不许算在途**（反向钉子）。

八条钉子（每条后面写「怎么坏掉会红」）：

① `test_lane_guard_bites_at_limit` —— 同账号 2 条 + `limit=2` ⇒ 1 条问题，
   文案含「同时在跑 2 张」「上限 2」。坏法：判据写成 `>` ⇒ 该咬不咬。
② `test_lane_guard_zero_limit_is_unlimited` —— `limit=0` 且 10 条同账号 ⇒ `[]`。
   坏法：写成 `>= 0` ⇒ 所有派活都派不出去。
③ `test_lane_guard_ignores_other_accounts` —— 5 条别账号 + 0 条本账号 ⇒ `[]`。
   坏法：不按账号数 ⇒ 误伤别的号。
④ `test_lane_guard_empty_account_judges_nothing` —— `account=""` ⇒ `[]`。
   坏法：空串当「某个号」⇒ 老租约被一起算上。
⑤ `test_lanes_toml_broken_raises_not_empty` —— 坏 TOML ⇒ `LanesError`，
   **不许**回 `{}`。坏法：坏了当空 ⇒ 悄悄松开判据。
⑥ `test_lanes_toml_missing_is_empty` —— 文件不存在 ⇒ `{}`（与今天逐字相同）。
   坏法：缺文件也抛 ⇒ 没人敢删这份配置。
⑦ `test_reserve_records_account_as_own_key` —— `reserve(account=…)` 落盘后
   `entry["account"]` 正是它。坏法：账号只活在 `note` 文本里 ⇒ 判据得反推。
⑧ `test_reverse_lane_guard_counts_dead_leases` —— **反向**：`live` 换成
   `rows` 必须变红。坏法：死租约算在途 ⇒ 号被静默锁死。

★ 一律用 `TF_POOL_REGISTRY` 指临时目录 —— **不往真的 `gates/diag/` 里写**；
上限一律用 `monkeypatch` 灌进去（不依赖仓库那份文件当下的数值，也只测本卡加的这条闸）。

★ 卡 A388（T-AG676，判 SKIP_BY_REDLINE）追加七条钉子 ⑨–⑮：签名里永远没有 `wait`、`queue` 只改文案、
  闸链上没有定时器 / 线程 / 自旋、越界只炸不 clamp、全仓只剩两行 queue_wait、派活器没有 wait 开关、
  shipped 的 lanes.toml 不排队。它们钉的是「**没有**排队 / 没有等待」这件事本身 ——
  队列这一层按本仓纪律不移植（`tools/pool/guards.py` 守卫⑥ 与 `tools/pool/gateway.py:11`）。
"""

from __future__ import annotations

import datetime
import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

guards = importlib.import_module("pool.guards")
lanes = importlib.import_module("pool.lanes")
registry = importlib.import_module("pool.registry")

NOW = 1_700_000_000.0
ACCOUNT = "codearts-1"


def _iso(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def _res(account: str = ACCOUNT, card: str = "100", tree: str = ".wt/a",
         files: tuple[str, ...] = ("a.py",)) -> dict:
    """造一条「只关心账号」的活租约 —— `lane_guard` 只该看 `account` 这一个键。"""
    return {"card": card, "tree": tree, "files": list(files), "account": account}


@pytest.fixture()
def reg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把登记文件指到临时目录（**绝不动真的 `gates/diag/pool-registry.json`**）。"""
    path = tmp_path / "reg.json"
    monkeypatch.setenv("TF_POOL_REGISTRY", str(path))
    return path


@pytest.fixture()
def quiet_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """守卫里的门禁锁一律当「空着」—— 测试不依赖真的门禁锁文件。"""
    monkeypatch.setattr(registry, "read_lock_body", lambda *a, **k: "")


def _use_limits(monkeypatch: pytest.MonkeyPatch, mapping: dict) -> None:
    """把 `lanes.toml` 换成给定的上限表（`reserve()` 每次调用都会重新读一次）。"""
    monkeypatch.setattr(lanes, "load_lanes", lambda *a, **k: dict(mapping))


# ================================================================ ① 到上限会咬


def test_lane_guard_bites_at_limit() -> None:
    """钉子①：同账号 2 条活租约 + `limit=2` ⇒ 回 1 条问题，文案点明账号 / 在跑几张 / 上限几张。

    ★ 故意坏掉会红：判据写成 `running > limit`（而不是 `>=`）⇒ 已有 2 张时第 3 张照样派得出去
      ⇒ 下面 `len(problems) == 1` 失败；文案里少任何一样（账号 / `同时在跑 N 张` / `上限 M`）
      ⇒ 对应 `in` 断言失败。
    """
    live = [_res(card="100"), _res(card="101")]
    problems = guards.lane_guard(ACCOUNT, live, limit=2, now=NOW)
    assert len(problems) == 1, f"到上限没咬：{problems}"
    assert ACCOUNT in problems[0], "文案里没点账号 id"
    assert "同时在跑 2 张" in problems[0], f"文案没说清在跑几张：{problems[0]}"
    assert "上限 2" in problems[0], f"文案没说清上限：{problems[0]}"

    # 差一张不咬：`limit` 是「最多几张同时在跑」，不是「还差几张才许派」
    assert guards.lane_guard(ACCOUNT, live[:1], limit=2, now=NOW) == []

    # `queue > 0` 的判据与 `queue == 0` 相同，只在文案里多一句「队列上限 q 张」
    queued = guards.lane_guard(ACCOUNT, live, limit=2, queue=5, now=NOW)
    assert len(queued) == 1
    assert "同时在跑 2 张" in queued[0] and "上限 2" in queued[0]
    assert "队列上限 5 张" in queued[0], f"queue 只该多一句文案：{queued[0]}"


# ================================================================ ② 0 = 关闸


def test_lane_guard_zero_limit_is_unlimited() -> None:
    """钉子②：`limit=0` 且同账号 10 条 ⇒ `[]` —— 照抄 magpie `concurrency.go:82`，0 是**关掉闸**。

    ★ 故意坏掉会红：判据写成 `limit >= 0` / 漏掉 `limit <= 0` 那一支 ⇒ 10 条一撞上就咬
      ⇒ 所有派活都派不出去（今天的行为被悄悄改掉）。
    """
    ten = [_res(card=str(100 + i)) for i in range(10)]
    assert guards.lane_guard(ACCOUNT, ten, limit=0, now=NOW) == []
    assert guards.lane_guard(ACCOUNT, ten, limit=0, queue=3, now=NOW) == []
    # 负数同样是「关掉闸」（不是「一个都不许」）
    assert guards.lane_guard(ACCOUNT, ten, limit=-1, now=NOW) == []


# ================================================================ ③ 不误伤别的账号


def test_lane_guard_ignores_other_accounts() -> None:
    """钉子③：5 条别的账号 + 0 条本账号 ⇒ `[]`；且看着别的账号时**不读** `tree` / `files`。

    ★ 故意坏掉会红：数条数时不比 `account`（把所有租约都算上）⇒ 5 条别的账号就让本账号
      派不出去 ⇒ `== []` 失败。★ `tree` / `files` 这两个键**故意不给**：只数账号的闸
      去读它们会 `KeyError`（本卡的 `lane_guard` 只认 `account`）。
    """
    others = [{"account": f"other-{i}"} for i in range(5)]
    assert guards.lane_guard(ACCOUNT, others, limit=2, now=NOW) == []

    # 没有 account 键 / account 是 None / 空串的老租约，一律不算到某个号头上
    legacy = [{}, {"account": None}, {"account": ""}, {"card": "108"}]
    assert guards.lane_guard(ACCOUNT, legacy, limit=1, now=NOW) == []


# ================================================================ ④ 没点名账号 = 没闸


def test_lane_guard_empty_account_judges_nothing() -> None:
    """钉子④：`account=""`（或非字符串）⇒ `[]` —— 没点名账号就没闸。

    ★ 故意坏掉会红：把「空账号直接放行」那一支删掉 ⇒ 空串会把一屋子老租约（没有 `account` 键，
      读出来是空串）都算成「同一个号」⇒ 10 条一撞就咬 ⇒ `== []` 失败。
    """
    legacy = [{"card": str(100 + i), "tree": f".wt/{i}"} for i in range(10)]
    assert guards.lane_guard("", legacy, limit=2, now=NOW) == []
    assert guards.lane_guard("   ", legacy, limit=2, now=NOW) == []
    assert guards.lane_guard(None, legacy, limit=2, now=NOW) == []
    assert guards.lane_guard(123, legacy, limit=2, now=NOW) == []


# ================================================================ ⑤ 坏配置不许当空


def test_lanes_toml_broken_raises_not_empty(tmp_path: Path) -> None:
    """钉子⑤：`lanes.toml` **在但读不懂** ⇒ `LanesError`，**绝不**返回 `{}`。

    ★ 为什么这条是硬判据：`{}` = 一条闸都没开 = 悄悄松开判据，正是本仓最忌的
      「判不出来就放行」。所以坏文件必须炸出来（而且 `registry.reserve` **不 catch** 它）。

    ★ 故意坏掉会红：把 `load_lanes` 里那几处 `raise LanesError(...)` 改成 `return {}` ⇒
      `pytest.raises(LanesError)` 不成立 ⇒ 每条断言都失败。
    """
    bad = tmp_path / "lanes.toml"

    # TOML 语法坏
    bad.write_text("[default\nlimit = 2\n", encoding="utf-8")
    with pytest.raises(lanes.LanesError):
        lanes.load_lanes(bad)

    # 值不是整数 / 越界 / 认不识的键 / 认不识的段 / 空账号 id —— 一律炸，不许当 0
    for body in ('[default]\nlimit = 3.5\n',
                 "[default]\nlimit = true\n",
                 f"[default]\nlimit = {lanes.MAX_LIMIT + 1}\n",
                 f"[default]\nqueue = {lanes.MAX_QUEUE_LIMIT + 1}\n",
                 f"[default]\nwait = {lanes.MAX_QUEUE_WAIT + 1}\n",
                 "[default]\nlimit = -1\n",
                 "[default]\nlimit = 2\nnope = 1\n",
                 "[default]\nlimit = 2\n[stray]\nlimit = 1\n",
                 '[accounts]\n"" = {limit = 1}\n',
                 '[accounts."codearts-1"]\nlimit = "two"\n'):
        bad.write_text(body, encoding="utf-8")
        with pytest.raises(lanes.LanesError):
            lanes.load_lanes(bad)


# ================================================================ ⑥ 没配 = 没闸


def test_lanes_toml_missing_is_empty(tmp_path: Path) -> None:
    """钉子⑥：文件**不存在** ⇒ `{}`（= 一条闸都没开，与今天的行为逐字相同）。

    ★ 故意坏掉会红：`load_lanes` 把「文件不存在」也当坏文件抛 ⇒ `== {}` 失败（没人敢删这份配置）。

    ★ 顺手防「永远回 `{}`」这种假绿：仓库里那份真文件必须读得出来，且 `[default]` 在其中。
    """
    assert lanes.load_lanes(tmp_path / "nope.toml") == {}

    repo_file = lanes.lanes_path()
    assert repo_file.exists(), f"仓库里那份 lanes.toml 不见了：{repo_file}"
    loaded = lanes.load_lanes()
    assert loaded, "仓库里的 lanes.toml 读成了空字典 ⇒ 这条闸等于没配"
    assert lanes.DEFAULT_SECTION in loaded
    # 没点名的账号退到 [default]；[default] 那段的 limit 就是本仓当下的默认上限
    assert lanes.lane_for("who-ever", loaded) == loaded[lanes.DEFAULT_SECTION]


# ================================================================ ⑦ account 是独立可判的键


def test_reserve_records_account_as_own_key(reg: Path, quiet_lock: None,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    """钉子⑦：`reserve(account=…)` 落盘后 `entry["account"]` 正是它，**且删掉 `note` 里那段
    显示文本之后仍然判得出来** —— 判据不许从显示文本反推。

    ★ 故意坏掉会红：账号只写进 `note`（`f"｜account={...}"`）而不落成键 ⇒ `entry["account"]`
      取不到 / 不是传入的那个；`lane_guard` 数不到这一条 ⇒ 下面的问题列表为空。
    """
    _use_limits(monkeypatch, {})
    entry = registry.reserve("210", tree=".wt/x", files=["z.py"], account="codebuddy/9f3c",
                             now=NOW)
    assert entry["account"] == "codebuddy/9f3c"
    rows = json.loads(reg.read_text(encoding="utf-8"))
    assert rows[-1]["account"] == "codebuddy/9f3c"

    # `note` 里根本没有这段文本（本次没传 note）⇒ 判据只能靠键
    reg.unlink()
    _use_limits(monkeypatch, {})
    registry.reserve("211", tree=".wt/y", files=["y.py"], account="codebuddy/9f3c", now=NOW)
    plain = json.loads(reg.read_text(encoding="utf-8"))[-1]
    assert plain["account"] == "codebuddy/9f3c"
    assert "codebuddy/9f3c" not in str(plain["note"])
    live = registry.list_reservations(NOW)
    problems = guards.lane_guard("codebuddy/9f3c", live, limit=1, now=NOW)
    assert problems, "从落盘的键数不出这一条 ⇒ account 没有真的落成键"
    assert "同时在跑 1 张" in problems[0] and "上限 1" in problems[0]

    # 端到端：`registry.reserve` 真把 `lane_guard` 接进 `problems` 了（不是只加了个函数）
    reg.unlink()
    _use_limits(monkeypatch, {ACCOUNT: lanes.Lane(limit=2)})
    registry.reserve("300", tree=".wt/t1", files=["t1.py"], account=ACCOUNT, now=NOW)
    registry.reserve("301", tree=".wt/t2", files=["t2.py"], account=ACCOUNT, now=NOW)
    with pytest.raises(registry.GuardError) as exc:
        registry.reserve("302", tree=".wt/t3", files=["t3.py"], account=ACCOUNT, now=NOW)
    assert any("同时在跑 2 张" in p and "上限 2" in p for p in exc.value.problems), (
        f"reserve 没把 lane_guard 接进 problems：{exc.value.problems}")
    # 被咬的那次**不许落盘**（否则一次失败派活会留下一条假租约）
    assert [r["card"] for r in registry.load(reg)] == ["300", "301"]


# ================================================================ ⑧ 反向：死租约不许算在途


def test_reverse_lane_guard_counts_dead_leases(reg: Path, quiet_lock: None,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """钉子⑧（**反向**）：已经死了的租约**不许**算在途 —— 否则一个号被静默锁死。

    ★ 判别力（这条是本卡的反向钉子）：把 `registry.reserve` 里
      `guards.lane_guard(account, live, ...)` 的 `live` 换成 `rows`（不清死租约），
      3 条 `ttl_seconds=1` / `now` 推后 100 秒的租约就会被算成「在跑 3 张」⇒
      `limit=2` 下那次派活被「这个号已经占满」拦下 ⇒ `reserve(...)` 抛 `GuardError`
      ⇒ 本用例变红。
    """
    dead = []
    for i in range(3):
        dead.append({"card": f"31{i}", "task": "", "tree": f".wt/d{i}", "files": [f"d{i}.py"],
                     "project": "", "pool": "", "model": "", "log": "", "owner": "w1",
                     "at": _iso(NOW), "ttl_seconds": 1.0, "note": "", "account": ACCOUNT})
    registry.save(dead, reg)

    # 这 3 条确实还在文件里，而且「若不过滤死租约就会咬」—— 这正是本用例的判别力来源
    rows = registry.load(reg)
    assert len(rows) == 3
    assert guards.lane_guard(ACCOUNT, rows, limit=2)
    assert registry.list_reservations(NOW + 100) == []

    # 真正的判据：reserve 数的是 live（过滤过死租约的），所以这一天照样派得出去
    _use_limits(monkeypatch, {ACCOUNT: lanes.Lane(limit=2)})
    entry = registry.reserve("320", tree=".wt/e", files=["e.py"], account=ACCOUNT, now=NOW + 100)
    assert entry["account"] == ACCOUNT
    assert [r["card"] for r in registry.load(reg)] == ["320"], (
        "死租约没被清掉 ⇒ 它们会被算在途，号被静默锁死")

# ================================================================ ⑨ 签名里永远没有 wait


def test_lane_guard_signature_never_takes_wait() -> None:
    """钉子⑨：`lane_guard` 的签名里**永远**没有 `wait` —— 本卡判 SKIP_BY_REDLINE，不落等待。

    ★ 故意坏掉会红：给 `lane_guard` 加一个 `wait: int = 0` 形参（哪怕函数体里根本不用它）⇒
      `sorted(params)` 与关键字参数集合都对不上；改成 `**kwargs` 偷偷接一个 ⇒ `VAR_KEYWORD`
      断言失败；改成 `*args` ⇒ `VAR_POSITIONAL` 断言失败。
    """
    import inspect

    params = inspect.signature(guards.lane_guard).parameters
    assert sorted(params) == ["account", "limit", "now", "queue", "reservations"], (
        f"签名变了：{sorted(params)} —— 这张卡不许给闸加 wait")
    assert [n for n in params if "wait" in n.lower()] == [], (
        f"签名里出现了 wait：{sorted(params)}")
    assert all(p.kind is not inspect.Parameter.VAR_KEYWORD for p in params.values()), (
        "不许用 **kwargs 兜住一个 wait")
    assert all(p.kind is not inspect.Parameter.VAR_POSITIONAL for p in params.values()), (
        "不许用 *args 兜住一个 wait")
    kw_only = {n for n, p in params.items() if p.kind is inspect.Parameter.KEYWORD_ONLY}
    assert kw_only == {"limit", "queue", "now"}, f"关键字参数变了：{sorted(kw_only)}"


# ================================================================ ⑩ queue 只改文案


def test_lane_guard_queue_only_changes_wording() -> None:
    """钉子⑩：`queue > 0` 与 `queue == 0` 的**判据完全相同**，只多一句「队列上限 q 张」。

    ★ 这就是「没有排队」这件事的可判形态：`queue` 只在文案里出现，不许改变咬 / 不咬，
      也不许在没满的时候提前咬（「先排上队再派」）。
    ★ 故意坏掉会红：把 `queue` 写进判据（例如 `if running < limit + queue: return []`）⇒
      满员时 `queue=1` 就不咬了 ⇒ `len(queued) == 1` 失败；queue=0 的文案里也带上
      「队列上限」⇒「不含」那条断言失败。
    """
    live = [_res(card="100"), _res(card="101")]
    plain = guards.lane_guard(ACCOUNT, live, limit=2, now=NOW)
    assert len(plain) == 1, f"没到上限？{plain}"
    assert "队列上限" not in plain[0], f"queue=0 的文案不该提队列：{plain[0]}"

    for queue in (1, 5, 100):
        queued = guards.lane_guard(ACCOUNT, live, limit=2, queue=queue, now=NOW)
        assert len(queued) == len(plain) == 1, f"queue={queue} 改了判据：{queued}"
        assert queued[0].replace(f"，队列上限 {queue} 张", "") == plain[0], (
            f"queue={queue} 改的不只是一句文案：{queued[0]}")

    # 没满员时 queue 一点作用都不起（不许「还有位子也让人排队等」）
    assert guards.lane_guard(ACCOUNT, live[:1], limit=2, queue=100, now=NOW) == []


# ================================================================ ⑪ 闸链上没有定时器 / 线程 / 自旋


def test_chain_has_no_timer_thread_or_spin() -> None:
    """钉子⑪：并发闸这条链上**没有**定时器 / 后台线程 / 协程等待 / 自旋。

    ★ 三个文件（lanes / guards / registry）的 `ast.While` 必须为空 —— 它们是「判一下」的纯判据，
      一旦出现 `while True: sleep(...)` 就是进程内自旋，正是本卡判 SKIP_BY_REDLINE 不移植的东西。
    ★ 四个文件里都不许出现 sleep / Timer / Thread / create_task / gather / wait 这类调用；
      lanes 与 guards 还**不许 import** time / threading / asyncio / sched / concurrent / signal。
    ★ `tools/pool/gateway.py` 有两处 `while`（`:963` `_iter_stream` 读 chunk、`:1046`
      `read_body` 读 body），那是 HTTP 响应体的 I/O 循环，不是自旋 ⇒ 对它只查调用面。
    ★ 故意坏掉会红：guards 里 `import time` + `time.sleep(0.1)`（卡规格判据 6 的反向变异 (c)）；
      或者起一个 `threading.Timer(...)` 当「到点重试」；或者把闸写成 `while True:` 轮询。
    """
    import ast

    banned = {"sleep", "setitimer", "alarm", "Timer", "Thread", "create_task", "gather",
              "run_until_complete", "wait", "wait_turn", "select", "poll"}

    def _calls(tree: ast.AST) -> list[tuple[int, str]]:
        out: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if name in banned:
                    out.append((node.lineno, name))
        return sorted(out)

    def _imports(tree: ast.AST) -> set[str]:
        out: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                out.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                out.add(node.module.split(".")[0])
        return out

    trees: dict[str, ast.AST] = {}
    for name in ("lanes", "guards", "registry", "gateway"):
        path = ROOT / "tools" / "pool" / f"{name}.py"
        trees[name] = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    for name in ("lanes", "guards", "registry"):
        whiles = [n.lineno for n in ast.walk(trees[name]) if isinstance(n, ast.While)]
        assert whiles == [], f"tools/pool/{name}.py 里出现了 while（自旋 / 定时器）：行 {whiles}"
        assert _calls(trees[name]) == [], (
            f"tools/pool/{name}.py 里有等待类调用：{_calls(trees[name])}")

    spin_modules = {"time", "threading", "asyncio", "sched", "concurrent", "signal"}
    for name in ("lanes", "guards"):
        leaked = sorted(_imports(trees[name]) & spin_modules)
        assert leaked == [], f"tools/pool/{name}.py 引了等待用的模块：{leaked}"

    assert _calls(trees["gateway"]) == [], (
        f"tools/pool/gateway.py 里有等待类调用：{_calls(trees['gateway'])}")


# ================================================================ ⑫ 越界只炸，绝不 clamp


def test_lanes_bounds_are_checked_but_never_clamped(tmp_path: Path) -> None:
    """钉子⑫：`wait` / `queue` / `limit` **越界就炸**，而且**不夹**到上界。

    ★ 为什么这条是硬判据：clamp = 把 `wait = 3601` 悄悄读成 3600，等于「判不出来就往宽松处改」，
      正是本仓最忌的那件事。卡规格判据 4：3601 必抛 `LanesError`，而 3600 读回来**原样**是 3600。
    ★ 故意坏掉会红：把 `_as_lane` 里三处 `raise LanesError(...)` 换成
      `wait = min(wait, MAX_QUEUE_WAIT)` ⇒ `pytest.raises` 不成立；把边界值也当成越界（`>=`）⇒
      「边界原样读回」那条失败。
    """
    good = tmp_path / "good.toml"
    good.write_text("[default]\nlimit = 1000\nqueue = 10000\nwait = 3600\n", encoding="utf-8")
    edge = lanes.load_lanes(good)[lanes.DEFAULT_SECTION]
    assert (edge.limit, edge.queue, edge.wait) == (
        lanes.MAX_LIMIT, lanes.MAX_QUEUE_LIMIT, lanes.MAX_QUEUE_WAIT), (
        f"边界值被夹了：{(edge.limit, edge.queue, edge.wait)}")

    # 中间值原样读回（不夹成 0、也不夹成上界）
    mid = tmp_path / "mid.toml"
    mid.write_text('[default]\nwait = 1800\nqueue = 7\n[accounts."codearts-1"]\nwait = 42\n',
                   encoding="utf-8")
    loaded = lanes.load_lanes(mid)
    assert (loaded[lanes.DEFAULT_SECTION].wait, loaded[lanes.DEFAULT_SECTION].queue) == (1800, 7)
    assert loaded["codearts-1"].wait == 42

    # 越界一个 1 也必须炸，而且报的是**原值**（不是夹完的值）
    over = tmp_path / "over.toml"
    over.write_text(f"[default]\nwait = {lanes.MAX_QUEUE_WAIT + 1}\n", encoding="utf-8")
    with pytest.raises(lanes.LanesError) as exc:
        lanes.load_lanes(over)
    assert str(lanes.MAX_QUEUE_WAIT + 1) in str(exc.value), (
        f"报错里应当是原值：{exc.value}")

    for body in (f"[default]\nqueue = {lanes.MAX_QUEUE_LIMIT + 1}\n",
                 f"[default]\nlimit = {lanes.MAX_LIMIT + 1}\n",
                 f"[accounts.\"codearts-1\"]\nwait = {lanes.MAX_QUEUE_WAIT + 1}\n"):
        over.write_text(body, encoding="utf-8")
        with pytest.raises(lanes.LanesError):
            lanes.load_lanes(over)


# ================================================================ ⑬ 全仓只剩两行 queue_wait


def test_only_two_queue_wait_mentions_in_repo() -> None:
    """钉子⑬：全仓只有两行提到 queue_wait，**没有第二个消费者把 wait 当真**。

    今天的两行（`grep -rn 'QueueWait|queue_wait' tools/ scripts/ --include=*.py`）：
      · `tools/pool/lanes.py:41` —— 注释：「等多久的上界……留给下一张卡，本卡只做越界检查」；
      · `tools/pool/landing.py:2601` —— `merge_queue.wait_turn(a.task, timeout=a.queue_wait, ...)`。

    ★ 为什么放行 landing.py:2601：它排的是**落地合并队列**（`tools/pool/queue.py` 的 `wait_turn`），
      不是每 key 并发闸；卡规格「不许做」第 4 条明确不许动它。这一条断言它确实还是那句
      `wait_turn(`，而不是被悄悄改成第二处闸。
    ★ 故意坏掉会红：在 `registry.reserve` 或 `gateway` 的换号循环里加一个 `queue_wait` 消费者
      ⇒ 命中数变 3 ⇒ 报错里逐条点名。
    """
    import re

    pattern = re.compile(r"QueueWait|queue_wait")
    hits: list[tuple[str, int, str]] = []
    for sub in ("tools", "scripts"):
        for path in sorted((ROOT / sub).rglob("*.py")):
            text = path.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    hits.append((path.relative_to(ROOT).as_posix(), lineno, line.strip()))

    assert len(hits) == 2, f"queue_wait 的消费者多出来了（或少了）：{hits}"
    assert [h[0] for h in hits] == ["tools/pool/landing.py", "tools/pool/lanes.py"], (
        f"命中集变了：{[h[0] for h in hits]}")
    lanes_hit = next(h for h in hits if h[0] == "tools/pool/lanes.py")
    landing_hit = next(h for h in hits if h[0] == "tools/pool/landing.py")
    assert lanes_hit[2].startswith("#"), f"lanes.py 那行应当只是注释：{lanes_hit}"
    assert "wait_turn(" in landing_hit[2] and "a.queue_wait" in landing_hit[2], (
        f"landing.py 那行应当是落地合并队列的 wait_turn（不是第二处闸）：{landing_hit}")


# ================================================================ ⑭ 派活器上没有 wait 开关


def test_dispatch_surface_has_no_wait_switch() -> None:
    """钉子⑭：派活器的命令行上**没有** `--wait` / `--queue` 这种开关。

    ★ 唯一名字里带 wait 的是 `--quota-wait`（默认 300 秒）：那是「撞 429 先等几秒再探」的额度退避，
      与 F22 的槽位排队无关 —— 卡规格判据 5 说的「全仓无第二个消费者」在派活器这一侧就是它。
    ★ 故意坏掉会红：`build_parser()` 里加一个 `--wait`（或 `--lane-wait` / `--queue`）⇒
      开关集合对不上；把 `--quota-wait` 的默认值从 300 改掉 ⇒ 那条数值断言失败。
    ★ 这条只读 `tools/wb_dispatch.py` 的**参数面**（不 grep 全文）：那个文件自己就有
      `time.sleep(backoff)`（认证探针退避）与 `threading.Thread`（日志泵），那不是闸链。
    """
    import argparse

    import wb_dispatch

    parser = wb_dispatch.build_parser()
    actions = list(parser._actions)
    subs = [a for a in actions if isinstance(a, argparse._SubParsersAction)]
    assert subs == [], "派活器长出了子命令 ⇒ 这条用例只看得见顶层开关，得跟着改"

    hits = [a for a in actions
            if any(key in opt.lower() for opt in a.option_strings for key in ("wait", "queue"))]
    assert [a.option_strings for a in hits] == [["--quota-wait"]], (
        f"派活器上多了等待开关：{[a.option_strings for a in hits]}")

    only = hits[0]
    assert only.dest == "quota_wait"
    assert only.default == wb_dispatch.DEFAULT_QUOTA_WAIT == 300, (
        f"--quota-wait 的默认值变了：{only.default}")
    assert "429" in (only.help or ""), (
        f"--quota-wait 讲的是额度 429 退避，不是槽位排队：{only.help}")


# ================================================================ ⑮ shipped 的 lanes.toml 不排队


def test_shipped_lanes_toml_does_not_queue() -> None:
    """钉子⑮：仓库里那份 `lanes.toml` **没有开排队** —— 每一段的 `queue` / `wait` 都是 0。

    ★ 为什么要在仓库真文件上钉：`queue = 5` 写进去虽然今天「只进文案」，但它会让下一个读配置的人
      以为排队已经做完了 —— 本卡判 SKIP_BY_REDLINE，配置必须诚实地写着「不排队」。
    ★ 故意坏掉会红：把 `[default]` 的 `queue` 改成 5（或加一个 `[accounts."codearts-1"]` 段
      写着 `wait = 30`）⇒ 下面两条断言失败。
    """
    repo_file = lanes.lanes_path()
    assert repo_file.exists(), f"仓库里那份 lanes.toml 不见了：{repo_file}"

    text = repo_file.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), 1):
        effective = line.split("#", 1)[0].strip()
        if effective.startswith(("queue", "wait")):
            value = effective.split("=", 1)[1].strip()
            assert value == "0", f"shipped 的 lanes.toml 第 {lineno} 行开了排队：{line.strip()}"

    loaded = lanes.load_lanes()
    assert loaded, "仓库里的 lanes.toml 读成了空字典 ⇒ 这条闸等于没配"
    for name, lane in loaded.items():
        assert (lane.queue, lane.wait) == (0, 0), f"第 [{name}] 段开了排队：{lane}"
