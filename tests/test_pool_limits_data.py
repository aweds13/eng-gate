r"""卡 A367 / T-AG652：`limits.toml` 的**数据面** —— 位址唯一、一份文件两个形状、没数据≠无限。

判据（卡规格「判据」一节）

1. **数据文件位址唯一且被钉住** —— 不设 `TF_POOL_LIMITS` 时 `limits_path()` 落在卡规格写的
   那条路径上（`D:/repo/infra/pool/limits.toml`）；再加一条对照：换 cwd 不改结果
   （体例 `tests/test_pool_callers.py` 的 `test_pool_dir_does_not_follow_cwd`）。
2. **两份 reader 的顶层形状**（形状裁决 (b)）—— 同一份临时 `limits.toml`：限额段留顶层
   （`[[<id>.limit]]`），`[accounts."<id>"]` 只放 `models`。两边都能读、语义都对；
   **反向**：把裁决 (a) 那个形状（`limit` 写进 `[accounts."<id>"]`）写回文件，被改的那一侧
   （`pool.limits_policy.load_limits`）必须**抛**，而旧语义那一侧照旧原样给 —— 证明这次改动
   不是「什么都收」。`accounts` 这个键必须在 docstring 与错误文案里被**点名**，不是被静默忽略。
3. **「没数据=不限」与「坏数据=拒」同时成立** ——
   ① 文件不存在 ⇒ `{}`，`wb_dispatch` 的限额闸**零副作用**（照旧派活、err 里没有「限额」）；
   ② 坏 TOML ⇒ `LimitError`，且 wb_dispatch 那条「限额策略读不懂 ⇒ 拒派」的文案出现、不派活；
   ③ 不许回「无上限」哨兵值（体例 pin_18）：空策略 = **没有声明**，不是「一个很大的数」。
4. **数据文件体例** —— 仓内模板 `tools/pool/limits.example.toml` 拿真文件跑两边 `load_limits`
   都不许抛；文件头写清「键用账本稳定 id」「不在表里 = 没设限额」与 `MAX_LIMITS` / `MAX_DAYS` /
   `MAX_HOURS` 的边界；正文是空表（模板里**不许**有一条真会拦人的限额）。

★ 真文件路径只出现在**判据 1 与判据 4** 这两处（判据 1 比的是路径本身，判据 4 读的是仓内模板）；
  其余测试一律用 `TF_POOL_LIMITS` / 显式 `path=` 指临时文件 —— 不碰仓外那份（卡 A338 的
  `tests/test_pool_failclosed.py` 同样纪律）。
"""

from __future__ import annotations

import datetime as dt
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from pool import limits, limits_check, limits_policy  # noqa: E402

#: 卡规格逐字写下的那条路径（判据 1）。`str(Path)` 在 Windows 上是反斜杠形态，
#: 所以「逐字」比对走 `as_posix()`，真钉子仍是 `Path` 对象相等。
DOCUMENTED = "D:/repo/infra/pool/limits.toml"
#: 仓内**模板**（不是生产读的那份）：判据 4 的「真文件」是它。
TEMPLATE = ROOT / "tools" / "pool" / "limits.example.toml"
#: 判据 3③ 用；不靠真实钟表（与 `tests/test_pool_limits.py` 同一个写法）。
NOW = dt.datetime.fromisoformat("2026-10-12T23:28:00+08:00")


def _write(path: pathlib.Path, body: str) -> pathlib.Path:
    path.write_text(body, encoding="utf-8")
    return path


def _twd():
    """取兄弟测试模块 `test_wb_dispatch` 的夹具（判据 3 要真跑一遍 `wb_dispatch.main()`）。

    照 `tests/test_pool_limits_wiring.py` 的体例：挂载与 import 都放在函数里。
    """
    for extra in (ROOT / "tests", ROOT / "tools"):
        if str(extra) not in sys.path:
            sys.path.insert(0, str(extra))
    import test_wb_dispatch

    return test_wb_dispatch


def _wired(twd, tmp_path, monkeypatch) -> pathlib.Path:
    """一张能派活的沙箱 + 一条**不存在**的限额文件（= 判据 3① 的前提）。"""
    sandbox = pathlib.Path(twd.sandbox.__wrapped__(tmp_path, monkeypatch))
    ledger = twd._ledger_with_profiles(
        sandbox, ("codebuddy-demo", "demo", "~/codebuddy-accounts/demo")
    )
    twd._use_ledger(monkeypatch, ledger)
    stub = twd._account_stub(sandbox, {"demo": twd._demo_vars()})
    monkeypatch.setenv("TF_ACCOUNT_SCRIPT", str(stub))
    monkeypatch.setenv("TF_POOL_LIMITS", str(sandbox / "no-such-limits.toml"))
    # `wd.main()` 会调 `wb_session.claim()` 写「卡归窗口」账本；这份测试不测那个，
    # 所以把它指到 tmp（与 `tests/test_wb_dispatch.py` 的 autouse 夹具同口径）。
    import wb_session

    monkeypatch.setattr(wb_session, "LEDGER", tmp_path / "session-leases.json")
    monkeypatch.delenv("DSH_SESSION_ID", raising=False)
    return sandbox


def _run(twd, monkeypatch, capsys, *extra):
    twd._account_argv(monkeypatch, *extra)
    code = twd.wd.main()
    captured = capsys.readouterr()
    return code, captured.out, captured.err

# ================================================================ 判据 1：位址


def test_limits_path_is_the_one_we_document(monkeypatch) -> None:
    """不设 env 时 `limits_path()` 就是卡规格写的那条路径 —— 位址只有一处真源。"""
    monkeypatch.delenv(limits.LIMITS_ENV, raising=False)
    got = limits.limits_path()
    assert got == pathlib.Path(DOCUMENTED)
    assert got.as_posix() == DOCUMENTED


def test_pool_dir_does_not_follow_cwd(tmp_path, monkeypatch) -> None:
    """换 cwd 不改位址（体例：`tests/test_pool_callers.py::test_pool_dir_does_not_follow_cwd`）。

    位址从 `TOOL_ROOT`（`tools/pool/limits.py` 自己往上数三层）推，不是从 cwd 推 ——
    否则「在哪个目录跑的命令」会悄悄改掉「读哪份限额」。
    """
    monkeypatch.delenv(limits.LIMITS_ENV, raising=False)
    fake_root = tmp_path / "fake"
    (fake_root / "infra" / "pool").mkdir(parents=True)
    elsewhere = tmp_path / "deep" / "cwd"
    elsewhere.mkdir(parents=True)
    expected = fake_root / "infra" / "pool"
    assert limits.pool_dir(start=fake_root) == expected
    before = limits.limits_path()
    monkeypatch.chdir(elsewhere)
    assert limits.pool_dir(start=fake_root) == expected
    assert limits.limits_path() == before


# ================================================================ 判据 2：形状


def _both_shapes() -> str:
    """裁决 (b) 的**一份**文件：顶层限额段 + `[accounts."<id>"]` 只放 models。"""
    return (
        '[accounts."codebuddy-demo"]\n'
        'models = ["deepseek-*"]\n'
        "\n"
        "[[codebuddy-demo.limit]]\n"
        'period = "day"\n'
        "tokens = 1000\n"
    )


def test_both_readers_accept_one_file(tmp_path) -> None:
    """同一份临时 limits.toml：两边都读得成，且各取各的那一半。"""
    path = _write(tmp_path / "limits.toml", _both_shapes())
    table = limits.load_limits(path)
    assert table["accounts"] == {"codebuddy-demo": {"models": ["deepseek-*"]}}
    policy = limits_policy.load_limits(path)
    assert set(policy) == {"codebuddy-demo"}
    (limit,) = policy["codebuddy-demo"]
    assert (limit.period, limit.tokens) == ("day", 1000)
    # 两边各取各的那一半：policy 侧看不到 models；旧语义侧原样给两个顶层键（它不校验）。
    assert "models" not in str(policy)
    assert set(table) == {"accounts", "codebuddy-demo"}


def test_old_shape_is_refused_by_the_changed_side(tmp_path) -> None:
    """反向：裁决 (a) 那个形状（limit 写进 `[accounts."<id>"]`）必须**抛**，不是 {}。

    只放行、不验那一侧 = 把「限额段里混着别的东西」变成正常态（pin_19 正是靠这条守住的）。
    """
    body = '[accounts."codebuddy-demo"]\nlimit = [{ period = "day", tokens = 1000 }]\n'
    path = _write(tmp_path / "limits.toml", body)
    # 旧语义那一侧照旧原样给：这证明「被改的是 policy 那一侧」，不是两边都不收。
    assert limits.load_limits(path) == {
        "accounts": {"codebuddy-demo": {"limit": [{"period": "day", "tokens": 1000}]}}
    }
    with pytest.raises(limits_policy.LimitError) as caught:
        limits_policy.load_limits(path)
    assert "accounts" in str(caught.value)
    assert "limit" in str(caught.value)


def test_accounts_key_is_named_not_ignored(tmp_path) -> None:
    """`accounts` 必须在 docstring 与错误文案里被**点名** —— 跳过的键不能是「谁也不知道」。"""
    doc = limits_policy._check_accounts.__doc__ or ""
    assert "accounts" in doc
    assert "F34" in doc or "A341" in doc
    assert "accounts" in (limits_policy.load_limits.__doc__ or "")
    # 文案点名：段里混进别的键时，错的是**那一侧**，得说出来是哪个段。
    path = _write(
        tmp_path / "limits.toml",
        '[accounts."codebuddy-demo"]\nmodels = ["*"]\ntokens = 5\n',
    )
    with pytest.raises(limits_policy.LimitError) as caught:
        limits_policy.load_limits(path)
    text = str(caught.value)
    assert "accounts" in text
    assert "codebuddy-demo" in text
    assert "tokens" in text
    # 空表 / 只有 models 的段放行（放行的只有这一种）。
    ok = _write(tmp_path / "ok.toml", '[accounts."codebuddy-demo"]\nmodels = ["*"]\n')
    assert limits_policy.load_limits(ok) == {}


def test_accounts_side_that_is_not_a_table_refuses(tmp_path) -> None:
    """`accounts` 读不懂（不是表 / 段不是表）⇒ 抛；「读不懂」不是「没写」。"""
    flat = _write(tmp_path / "flat.toml", 'accounts = "codebuddy-demo"\n')
    with pytest.raises(limits_policy.LimitError) as caught:
        limits_policy.load_limits(flat)
    assert "accounts" in str(caught.value)
    odd = _write(tmp_path / "odd.toml", '[accounts]\n"codebuddy-demo" = 3\n')
    with pytest.raises(limits_policy.LimitError) as caught2:
        limits_policy.load_limits(odd)
    assert "codebuddy-demo" in str(caught2.value)

# ================================================================ 判据 3：没数据≠无限


def test_missing_file_is_empty_not_refuse(tmp_path, monkeypatch, capsys) -> None:
    """文件不存在 ⇒ `{}`，且 wb_dispatch 的限额闸**零副作用**（照旧派活、err 里没有「限额」）。"""
    missing = tmp_path / "nope" / "limits.toml"
    assert limits_policy.load_limits(missing) == {}
    assert limits.load_limits(missing) == {}
    twd = _twd()
    sandbox = _wired(twd, tmp_path, monkeypatch)
    dispatched: list[list[str]] = []
    monkeypatch.setattr(twd.wd, "run_worker", twd._fake_runner(dispatched))
    lease = twd._spy_reserve(monkeypatch)
    assert not (sandbox / "limits.toml").exists()
    code, _out, err = _run(twd, monkeypatch, capsys, "--account", "demo", "--execute")
    assert code == 0
    assert "限额" not in err
    assert len(dispatched) == 1
    assert lease != {}


def test_broken_file_refuses(tmp_path, monkeypatch, capsys) -> None:
    """坏 TOML ⇒ `LimitError`，且 wb_dispatch 走「拒派」那一支（不许当成「没设限额」）。"""
    broken = _write(tmp_path / "limits.toml", "this is not toml =\n")
    with pytest.raises(limits_policy.LimitError, match="TOML"):
        limits_policy.load_limits(broken)
    twd = _twd()
    sandbox = _wired(twd, tmp_path, monkeypatch)
    again = _write(sandbox / "limits.toml", "this is not toml =\n")
    monkeypatch.setenv("TF_POOL_LIMITS", str(again))
    dispatched: list[list[str]] = []
    monkeypatch.setattr(twd.wd, "run_worker", twd._fake_runner(dispatched))
    lease = twd._spy_reserve(monkeypatch)
    code, _out, err = _run(twd, monkeypatch, capsys, "--account", "demo", "--execute")
    assert code == 2
    assert "限额策略读不懂" in err
    assert "拒派" in err
    assert dispatched == []
    assert lease == {}


def test_no_data_is_not_infinite(tmp_path) -> None:
    """「没声明」不是「无上限」—— 不许回哨兵值（体例：`tests/test_pool_limits.py` pin_18）。"""
    empty = _write(tmp_path / "empty.toml", "")
    for path in (tmp_path / "nope.toml", empty):
        got = limits_policy.load_limits(path)
        assert got == {}
        assert not got  # 空就是空：没有 default 段、没有「无上限」哨兵
        verdict = limits_check.check([], spent={}, now=NOW)
        assert verdict.allowed is True
        assert verdict.binding is None
        assert verdict.retry_after_s == 0
        assert "没有声明" in verdict.why
        # 反向：真声明了一条就**会**拦（否则上面那句就是空话）。
        tight = _write(
            tmp_path / "tight.toml",
            '[[a1.limit]]\nperiod = "day"\ntokens = 10\n',
        )
        declared = limits_policy.load_limits(tight)["a1"]
        blocked = limits_check.check(declared, spent={0: (10, 0.0)}, now=NOW)
        assert blocked.allowed is False

# ================================================================ 判据 4：数据文件体例


def test_data_file_parses() -> None:
    """仓内模板拿**真文件**跑两边 `load_limits()`：都不许抛；正文是空表（没有真会拦人的限额）。

    这是「模板本身是合法 TOML、且读者不会因为读到它就拒」的证明 —— 不是文案钉子。
    生产读的那份在仓外（判据 1 钉的位址），这里读的是**仓内模板**，不碰它。
    """
    assert TEMPLATE.is_file(), f"模板不在：{TEMPLATE}"
    assert limits_policy.load_limits(TEMPLATE) == {}
    assert limits.load_limits(TEMPLATE) == {}
    text = TEMPLATE.read_text(encoding="utf-8")
    # 正文里不许有生效的限额表（`[accounts]` 空表那一行在 rpm.toml 体例里有先例，可留）。
    live = [
        line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")
    ]
    assert all(line.strip().startswith("[") and line.strip().endswith("]") for line in live)
    assert not any("limit" in line for line in live), f"模板里有生效的限额：{live}"


def test_template_states_the_boundaries() -> None:
    """文件头把三条边界**按常量的当前值**写清（改常量不改模板 ⇒ 红；不是钉文案，是防漂）。"""
    text = TEMPLATE.read_text(encoding="utf-8")
    for name, value in (
        ("MAX_LIMITS", limits_policy.MAX_LIMITS),
        ("MAX_DAYS", limits_policy.MAX_DAYS),
        ("MAX_HOURS", limits_policy.MAX_HOURS),
    ):
        assert name in text, f"模板没写 {name}"
        assert str(value) in text, f"模板里 {name} 的值与常量不一致（应为 {value}）"
