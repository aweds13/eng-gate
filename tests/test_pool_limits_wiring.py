"""卡 A350 · T-AG562 —— 限额必须在**派活之前真的拦一次**。

本文件钉判据 1–6。判据 7（反向验证）在 `gates/diag/_rev_A350.py`：逐条真改、真跑、
真复原，每条变异都必须把这里的一条打红 —— 那才是「钉子真咬住」的自证。

判据 1：跑完往 pool-spend.jsonl 写一行 —— account 是稳定 id、数是 CLI 自报、
        cost 恒 0.0；没给 --account（空账号）⇒ 整行不写。
判据 2：window() 与 check() 拿到同一个 now；spent 按第几条限额的索引取；
        cache_reads 跟 limit.cache_reads 走；键是稳定 id 不是 profile 名。
判据 2·3：窗口花完 ⇒ 退 2、占树之前、走既有 problems 出口，文案含
        reset_at 与 retry_after_s。
判据 4：没有策略文件 ⇒ 工人拿到的 argv 与接线之前逐项一字不差。
判据 5：策略文件读不懂 ⇒ 拒派，并原样带出判据层的报错（不吞成「没设限额」）。
判据 6：只调 limits_policy.load_limits；旧语义那份读同一份文件是 {}，
        它一旦被用上，判据 5 那条就会悄悄放行 —— 这就是这条的分辨力。

★ 本文件刻意不带 `# noqa`：tools/ 与 tests/ 的挂载、兄弟模块的 import 全放进
  函数体，免得 E402 逼出豁免。
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- 沙箱
def _twd():
    """取兄弟测试模块 `test_wb_dispatch`（复用它的沙箱夹具与号池桩）。

    本仓禁 `# noqa`，所以 `sys.path` 的挂载与 import 都只能在函数里做 —— 函数内 import
    不触发 E402。
    """
    for extra in (ROOT / "tests", ROOT / "tools"):
        path = str(extra)
        if path not in sys.path:
            sys.path.insert(0, path)
    import test_wb_dispatch

    return test_wb_dispatch


@pytest.fixture
def wired(tmp_path: pathlib.Path, monkeypatch) -> pathlib.Path:
    """沙箱 + 号账本（`demo` → `codebuddy-demo`）+ 假号池工具；返回沙箱根。"""
    twd = _twd()
    sandbox = pathlib.Path(twd.sandbox.__wrapped__(tmp_path, monkeypatch))
    ledger = twd._ledger_with_profiles(
        sandbox, ("codebuddy-demo", "demo", "~/codebuddy-accounts/demo"))
    twd._use_ledger(monkeypatch, ledger)
    stub = twd._account_stub(sandbox, {"demo": twd._demo_vars()})
    monkeypatch.setenv("TF_ACCOUNT_SCRIPT", str(stub))
    # 默认指向沙箱里**不存在**的那份 —— 判据 4 的生产默认形状；各用例按需要改。
    monkeypatch.setenv("TF_POOL_LIMITS", str(sandbox / "no-such-limits.toml"))
    return sandbox


def _run(twd, monkeypatch, capsys, *extra: str) -> tuple[int, str, str]:
    """跑一趟 `main()`（沙箱里、`--card 001 --spec spec.md`），回 `(退出码, stdout, stderr)`。"""
    twd._account_argv(monkeypatch, *extra)
    code = twd.wd.main()
    out = capsys.readouterr()
    return code, out.out, out.err


def _policy(sandbox: pathlib.Path, body: str) -> pathlib.Path:
    path = sandbox / "limits.toml"
    path.write_text(body, encoding="utf-8")
    return path


def _spend(sandbox: pathlib.Path, *, account: str = "codebuddy-demo",
           tokens: int = 0, cache_read: int = 0) -> pathlib.Path:
    """往**真账本**里记一笔（判据 2 的喂料面：派活前先有已花的钱）。"""
    from pool import ledger_spend

    return ledger_spend.append(
        account, "009", "deepseek-v4.1-flash",
        input_tokens=tokens, output_tokens=0, cache_read=cache_read, cost=0.0,
        at=dt.datetime.now(ledger_spend.TZ), root=sandbox)


def _usage_events(*, input_tokens: int = 7, output_tokens: int = 3,
                  cache_read: int = 5) -> list[str]:
    """一条带 `usage` 的 `result` 事件 —— 判据 1 要证明数是从这里**抄**过去的。"""
    return [json.dumps({
        "type": "result",
        "subtype": "success",
        "result": "复核完了",
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": cache_read,
        },
    }, ensure_ascii=False)]


def _rows(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _ledger(sandbox: pathlib.Path) -> pathlib.Path:
    return sandbox / "gates" / "diag" / "pool-spend.jsonl"


# --------------------------------------------------------------------------- 判据 1
def test_spend_lands_in_the_pool_ledger_under_the_stable_id(
        wired: pathlib.Path, monkeypatch, capsys) -> None:
    """判据 1：一轮跑完就记一行 —— `account` 是稳定 id、数是 CLI 自报、`cost` 恒 `0.0`。"""
    twd = _twd()
    dispatched: list[list[str]] = []
    monkeypatch.setattr(twd.wd, "run_worker",
                        twd._fake_runner(dispatched, events=_usage_events()))
    code, _out, _err = _run(twd, monkeypatch, capsys, "--account", "demo", "--execute")
    assert code == 0
    rows = _rows(_ledger(wired))
    assert len(rows) == 1, f"跑完一轮必须记且只记一行：{rows}"
    row = rows[0]
    assert row["account"] == "codebuddy-demo", (
        f"账本的键是稳定 id（与租约 / RPM / lanes 同一把），不是 profile 名：{row!r}")
    assert (row["input_tokens"], row["output_tokens"], row["cache_read"]) == (7, 3, 5), (
        f"数必须是 CLI 自己报的那三个（不自己估）：{row!r}")
    assert row["cost"] == 0.0, "vendor 不报金额 ⇒ cost 写 0.0，**不许编乘数**"
    assert row["cache_write"] == 0, "cache_write 由 append() 自己填 0"
    assert row["card"] == "001"
    moment = dt.datetime.fromisoformat(row["at"])
    assert moment.tzinfo is not None, f"at 必须带时区：{row['at']!r}"
    drift = abs((dt.datetime.now(moment.tzinfo) - moment).total_seconds())
    assert drift < 120, f"at 该是这一轮的开始时间（现在差 {drift:.0f}s）"


def test_without_account_not_a_single_row(wired: pathlib.Path, monkeypatch, capsys) -> None:
    """判据 1：没给 `--account` ⇒ 空账号 ⇒ **整行不写**（否则账本里全是空账号）。"""
    twd = _twd()
    dispatched: list[list[str]] = []
    monkeypatch.setattr(twd.wd, "run_worker",
                        twd._fake_runner(dispatched, events=_usage_events()))
    code, _out, _err = _run(twd, monkeypatch, capsys, "--execute")
    assert code == 0
    assert dispatched, "这一趟本来就该真派活（只是不记限额账）"
    assert _rows(_ledger(wired)) == [], "空账号那一行不许写"


# --------------------------------------------------------------------------- 判据 2
def test_spend_and_the_ask_share_one_now(wired: pathlib.Path, monkeypatch, capsys) -> None:
    """判据 2：求和的窗口与判的 `now` 必须**同一个对象**（两个时间源 ⇒ 窗口漂移）。"""
    twd = _twd()
    monkeypatch.setenv("TF_POOL_LIMITS", str(_policy(
        wired, '[[codebuddy-demo.limit]]\nperiod = "day"\ntokens = 100000\n')))
    from pool import limits_check, limits_policy

    seen: dict = {}
    real_window = limits_policy.window
    real_check = limits_check.check

    def spy_window(limit, now):
        seen.setdefault("window_nows", []).append(now)
        return real_window(limit, now)

    def spy_check(limits, **kwargs):
        seen["now"] = kwargs["now"]
        seen["spent"] = kwargs["spent"]
        return real_check(limits, **kwargs)

    monkeypatch.setattr(limits_policy, "window", spy_window)
    monkeypatch.setattr(limits_check, "check", spy_check)
    dispatched: list[list[str]] = []
    monkeypatch.setattr(twd.wd, "run_worker", twd._fake_runner(dispatched))
    code, _out, _err = _run(twd, monkeypatch, capsys, "--account", "demo", "--execute")
    assert code == 0
    assert seen.get("window_nows"), "限额闸根本没问过 window()"
    assert seen["now"] == seen["window_nows"][0], (
        "两个 now 不同源：window() 用了一个、check() 又取了另一个 —— "
        "跨窗口那一刻两边算的不是同一段，闸就会拦错 / 漏拦")
    assert list(seen["spent"]) == [0], f"spent 的键是第几条限额（索引）：{seen['spent']!r}"


def test_refuses_before_taking_the_tree_when_the_window_is_spent(
        wired: pathlib.Path, monkeypatch, capsys) -> None:
    """判据 2·3：窗口花完 ⇒ 退 2、**占树之前**、走既有 problems 出口、文案给续期。"""
    twd = _twd()
    monkeypatch.setenv("TF_POOL_LIMITS", str(_policy(
        wired, '[[codebuddy-demo.limit]]\nperiod = "day"\ntokens = 10\n')))
    _spend(wired, tokens=10)
    dispatched: list[list[str]] = []
    monkeypatch.setattr(twd.wd, "run_worker", twd._fake_runner(dispatched))
    lease = twd._spy_reserve(monkeypatch)
    code, _out, err = _run(twd, monkeypatch, capsys, "--account", "demo", "--execute")
    assert code == 2, "窗口已花完 ⇒ 必须拒派；退出码沿用 2（**不许新开**）"
    assert "[FAIL] 不派活 —— 前置检查没过：" in err, err
    assert "  · 限额已满" in err, f"要并进既有 problems 出口（逐条 `  · `）：{err}"
    assert "reset_at=" in err, f"拒派必须给续期时刻：{err}"
    assert "retry_after_s=" in err, f"拒派必须给 Retry-After：{err}"
    assert "限额已满（号 codebuddy-demo）" in err, f"点名要落到稳定 id：{err}"
    assert dispatched == [], "被闸拦下时一个工人都不能起"
    assert lease == {}, f"拒派必须在**占树之前**：reserve 已被调用，参数 {lease}"
    assert not (wired / "gates" / "diag" / "pool-registry.json").exists()


def test_cache_reads_axis_follows_the_limit_flag(
        wired: pathlib.Path, monkeypatch, capsys) -> None:
    """判据 2：`cache_reads = true` ⇒ 缓存读也计入 tokens 轴（否则这条限额形同虚设）。"""
    twd = _twd()
    monkeypatch.setenv("TF_POOL_LIMITS", str(_policy(
        wired, '[[codebuddy-demo.limit]]\nperiod = "day"\ntokens = 40\n'
               'cache_reads = true\n')))
    _spend(wired, tokens=0, cache_read=40)
    dispatched: list[list[str]] = []
    monkeypatch.setattr(twd.wd, "run_worker", twd._fake_runner(dispatched))
    code, _out, err = _run(twd, monkeypatch, capsys, "--account", "demo", "--execute")
    assert code == 2, f"策略说要算缓存读、缓存读已到 40/40 ⇒ 必须拦：{err}"
    assert "限额已满" in err, err
    assert dispatched == []


def test_cache_reads_ignored_when_the_limit_says_so(
        wired: pathlib.Path, monkeypatch, capsys) -> None:
    """判据 2：默认（`cache_reads` 未开）**不收** cache_read —— 同一个数就不该拦。"""
    twd = _twd()
    monkeypatch.setenv("TF_POOL_LIMITS", str(_policy(
        wired, '[[codebuddy-demo.limit]]\nperiod = "day"\ntokens = 40\n')))
    _spend(wired, tokens=0, cache_read=40)
    dispatched: list[list[str]] = []
    monkeypatch.setattr(twd.wd, "run_worker", twd._fake_runner(dispatched))
    code, _out, err = _run(twd, monkeypatch, capsys, "--account", "demo", "--execute")
    assert code == 0, f"策略没开 cache_reads ⇒ 那 40 个缓存读不算数，不该拦：{err}"
    assert len(dispatched) == 1


def test_limits_are_keyed_by_the_stable_id_not_the_profile_name(
        wired: pathlib.Path, monkeypatch, capsys) -> None:
    """判据 2：`limits` 的键是**稳定 id**；按 profile 名查会凭空拦下（或凭空放过）。

    ★ 前提自证：策略按 profile 名 `demo` 声明满额，账本里按 `demo` 也花满。
      按稳定 id 查（正确）⇒ 看不到这条策略 ⇒ 放行；
      按 profile 名查（错误）⇒ 命中并拦住 —— 所以这条能分辨两种实现。
    """
    twd = _twd()
    monkeypatch.setenv("TF_POOL_LIMITS", str(_policy(
        wired, '[[demo.limit]]\nperiod = "day"\ntokens = 10\n')))
    _spend(wired, account="demo", tokens=10)
    dispatched: list[list[str]] = []
    monkeypatch.setattr(twd.wd, "run_worker", twd._fake_runner(dispatched))
    code, _out, err = _run(twd, monkeypatch, capsys, "--account", "demo", "--execute")
    assert code == 0, f"策略挂在 profile 名下 ⇒ 稳定 id 下没这条限额，不该拦：{err}"
    assert len(dispatched) == 1
    assert "限额已满" not in err


# --------------------------------------------------------------------------- 判据 4
def test_no_policy_file_keeps_the_exact_argv(
        wired: pathlib.Path, monkeypatch, capsys) -> None:
    """判据 4：没有策略文件 ⇒ 派活路径与接线之前**一字不差**（正面钉子）。

    ★ 比的是 `main()` 交到工人手里的那条 argv：接线只许加「问一次」与「记一笔」，
      不许动命令行的任何一个元素。
    ★ 两个长 blob（开场白 / 八条铁律）只断开头；默认模型名从注册表取 —— 它们会随
      别的卡变动，钉死字面只会在无关的卡上炸，反而掩护了真正的回归。
    """
    twd = _twd()
    dispatched: list[list[str]] = []
    monkeypatch.setattr(twd.wd, "run_worker", twd._fake_runner(dispatched))
    code, _out, err = _run(twd, monkeypatch, capsys, "--account", "demo", "--execute")
    assert code == 0
    assert "限额" not in err, f"没有策略文件时这一段一句话都不该说：{err}"
    assert len(dispatched) == 1
    argv = dispatched[0]
    from pool.model_registry import DEFAULT_POOL, default_model_for
    assert len(argv) == 17, argv
    assert argv[:3] == [str(wired / "node.exe"), str(wired / "codebuddy"), "-p"], argv[:3]
    assert argv[3].startswith("读 复盘/交接-重构进度.md"), argv[3][:40]
    assert "卡号 001" in argv[3], "开场白里该有这张卡的卡号"
    assert (argv[4], argv[5]) == ("--model", default_model_for(DEFAULT_POOL).alias), argv[4:6]
    assert argv[6:11] == ["--output-format", "stream-json", "--permission-mode",
                          "bypassPermissions", "--max-turns"], argv[6:11]
    assert argv[11] == "240", argv[11]
    assert argv[12:15] == ["--autocompact", "1m", "--append-system-prompt"], argv[12:15]
    assert argv[15].startswith("你是这个仓库的外包工人"), argv[15][:40]
    assert argv[16] == "-y", argv[16]


# --------------------------------------------------------------------------- 判据 5
def test_a_broken_policy_file_refuses_and_names_it(
        wired: pathlib.Path, monkeypatch, capsys) -> None:
    """判据 5：策略文件读不懂 ⇒ **拒派**并说清哪一段坏了，不许吞成「没设限额」。"""
    twd = _twd()
    body = '[[codebuddy-demo.limit]]\nperiod = "day"\ntokens = "很多"\n'
    monkeypatch.setenv("TF_POOL_LIMITS", str(_policy(wired, body)))
    dispatched: list[list[str]] = []
    monkeypatch.setattr(twd.wd, "run_worker", twd._fake_runner(dispatched))
    lease = twd._spy_reserve(monkeypatch)
    code, _out, err = _run(twd, monkeypatch, capsys, "--account", "demo", "--execute")
    assert code == 2, f"策略读不懂 ⇒ 退 2 拒派（不是退 0 悄悄派）：{err}"
    assert "限额策略读不懂" in err, err
    assert "tokens 必须是整数" in err, f"要说清哪一段坏了（原样带出判据层的话）：{err}"
    assert "很多" in err, f"把坏掉的那个值也带出来：{err}"
    assert dispatched == []
    assert lease == {}, f"拒派必须在占树之前：reserve 已被调用，参数 {lease}"


# --------------------------------------------------------------------------- 判据 6
def test_only_the_policy_loader_is_consulted(wired: pathlib.Path, monkeypatch, capsys) -> None:
    """判据 6：只调 `limits_policy.load_limits`（新语义），旧语义那份一个字节都没动。

    ★ 分辨力自证：同一份坏文件，旧语义那份**原样把 `limit` 段当字典返回**（它只做
      TOML 解析、从不校验 `limit` 数组，所以永远不抛）⇒ 若实现退回它，这一趟就会
      **悄悄放行**；新语义那份抛 `LimitError` ⇒ 拒派。
    """
    twd = _twd()
    path = _policy(wired, '[[codebuddy-demo.limit]]\nperiod = "day"\ntokens = "很多"\n')
    from pool import limits as legacy_limits
    from pool import limits_policy

    raw = legacy_limits.load_limits(path)
    assert raw == {"codebuddy-demo": {"limit": [{"period": "day", "tokens": "很多"}]}}, (
        f"旧语义那份不校验、不抛，原样回字典（判据 6 前提）：{raw!r}")
    with pytest.raises(limits_policy.LimitError) as caught:
        limits_policy.load_limits(path)
    assert "tokens 必须是整数" in str(caught.value), str(caught.value)
    monkeypatch.setenv("TF_POOL_LIMITS", str(path))
    dispatched: list[list[str]] = []
    monkeypatch.setattr(twd.wd, "run_worker", twd._fake_runner(dispatched))
    code, _out, err = _run(twd, monkeypatch, capsys, "--account", "demo", "--execute")
    assert code == 2, f"新语义读不懂就拒派（旧语义会悄悄放行）：{err}"
    assert "tokens 必须是整数" in err, err
    assert dispatched == []
