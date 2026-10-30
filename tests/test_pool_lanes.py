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
