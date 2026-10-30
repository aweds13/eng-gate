r"""卡 A348（`T-AG551`）：调用方名册 —— 12 条钉子。

判据都在 `tools/pool/callers.py`；这里逐条钉「写坏了会不会红」：

① `test_missing_callers_toml_is_empty` —— 文件不在 ⇒ `{}`、`resolve()` 退靠
   `<hostname>:<pid>`、派活照常（落地当天零行为变化）。改成「不在就抛」⇒ 红。
② `test_unknown_caller_is_not_refused` —— 名册里没这个人 ⇒ 不抛、`is_off()` False、
   派活照常（名册是加法）。改成「查不到就拒」⇒ 红。
③ `test_off_caller_is_refused_with_exit_2` —— `off = true` ⇒ 走 `problems` 既有出口
   （打印 + 退 2）并点名 id 与 label，一个工人都别起。改成恒 False ⇒ 红。
④ `test_bad_callers_toml_raises` —— 坏 TOML / 段名不对 / `off` 非布尔 / 数组写坏 ⇒
   `CallersError`。改成静默回 `{}` ⇒ 红。
⑤ `test_empty_models_means_all` —— `models = []` 与缺键都是 `()`（= 全允许），与
   `off` 无关。改成「空 = 全拒」⇒ 红。
⑥ `test_resolve_three_levels` —— 显式 > 窗口 > `<hostname>:<pid>`，前两级与
   `pool.registry.default_owner()` 同口径。次序反过来 ⇒ 红。
⑦ `test_callers_path_derives_from_anchor` —— 覆盖 > 号池目录 > 仓根；源码里除锚点
   `infra/pool` 外没有仓外绝对路径。改成 cwd 版 ⇒ 红。
⑧ `test_no_secret_field_anywhere` —— `compare_digest` / `Bearer` / `chmod` /
   `secret` / `masked` 零命中，`Caller` 恰五字段。加一栏凭据 ⇒ 红。
⑨ `test_label_defaults_to_empty_and_is_never_used_as_id` —— `label` 缺 ⇒ `""`；
   两个同名 label 不影响按 id 命中，label 也不当 id 用。改成拿 label 当键 ⇒ 红。
⑩ `test_off_is_the_only_revocable_switch` —— `deleted` / `revoked` / `removed` 一律
   `CallersError`；撤只有 `off`。加一个「软删」开关 ⇒ 红。
⑪ `test_load_callers_does_not_write` —— 读一次后字节、mtime、目录里都没变。偷偷写
   `.bak` 或回写规范化 TOML ⇒ 红。
⑫ `test_pool_dir_does_not_follow_cwd` —— 换 cwd 后 `pool_dir()` 结果不变。
   `Path.cwd()` 版 ⇒ 红。

★ 导入用 `importlib`：`tools/` 不在 `sys.path` 上，且本仓禁 `# noqa`，所以不能像别的
  测试那样在 `sys.path.insert` 之后写 import 语句 —— 那会踩 E402。
★ 派活那三条钉子（① ② ③）复用 `tests/test_wb_dispatch.py` 的 `sandbox` 夹具与
  `_account_argv` / `_fake_runner` / `_capture_worker`：那套夹具已经把 `wd.ROOT`、
  池登记表、项目索引都指到临时目录 —— 重造一份只会两处走样。
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib
import os
import re
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

callers = importlib.import_module("pool.callers")
registry = importlib.import_module("pool.registry")
dispatch_tests = importlib.import_module("test_wb_dispatch")

Caller = callers.Caller
CallersError = callers.CallersError
SOURCE = Path(callers.__file__).read_text(encoding="utf-8")

sandbox = dispatch_tests.sandbox
wb_session = dispatch_tests.wb_session
wd = dispatch_tests.wd


@pytest.fixture(autouse=True)
def _ledger_in_tmp(tmp_path: Path, monkeypatch) -> None:
    """账本指到 tmp —— 不然派活钉子会往主树的 `gates/diag/` 里写。"""
    ledger = tmp_path / "gates" / "diag" / "session-leases.json"
    monkeypatch.setattr(wb_session, "LEDGER", ledger)


def _roster(tmp_path: Path, body: str, name: str = "callers.toml") -> Path:
    """落一份名册到临时目录（临时文件不是入库源码，用 `write_text` 就够）。"""
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_missing_callers_toml_is_empty(sandbox: Path, monkeypatch) -> None:
    """① 名册不在 ⇒ `{}`、`resolve()` 退靠 `<hostname>:<pid>`、派活照常。"""
    monkeypatch.setenv("TF_POOL_CALLERS", str(sandbox / "no-such-dir" / "callers.toml"))
    assert callers.load_callers() == {}
    fallback = f"{socket.gethostname()}:{os.getpid()}"
    assert callers.resolve() == Caller(id=fallback)
    assert callers.resolve("", env_window="").id == fallback
    assert callers.is_off(callers.resolve()) is False

    seen: dict = {}
    monkeypatch.setattr(wd, "run_worker", dispatch_tests._capture_worker(seen))
    dispatch_tests._account_argv(monkeypatch, "--execute")
    assert wd.main() == 0, "名册不在 ⇒ 派活必须照常（落地当天零行为变化）"
    assert seen["cmd"], "一个工人都没起 —— 名册不在不该影响派活"


def test_unknown_caller_is_not_refused(sandbox: Path, monkeypatch) -> None:
    """② 名册里没这个人 ⇒ 不抛、`is_off()` False、派活照常。"""
    path = _roster(sandbox, '[caller."alice"]\nlabel = "外包 A"\n')
    monkeypatch.setenv("TF_POOL_CALLERS", str(path))
    stranger = callers.resolve("stranger")
    assert stranger == Caller(id="stranger")
    assert callers.is_off(stranger) is False

    seen: dict = {}
    monkeypatch.setattr(wd, "run_worker", dispatch_tests._capture_worker(seen))
    dispatch_tests._account_argv(monkeypatch, "--caller", "stranger", "--execute")
    assert wd.main() == 0, "没登记的人不许被拒 —— 名册是加法"
    assert seen["cmd"], "没登记的人也该照常派活"


def test_off_caller_is_refused_with_exit_2(sandbox: Path, monkeypatch, capsys) -> None:
    """③ 撤了的人 ⇒ 走 `problems` 既有出口（打印 + 退 2）并点名 id 与 label。"""
    path = _roster(
        sandbox,
        '[caller."alice"]\nlabel = "外包 A"\noff = true\n\n[caller."bob"]\noff = true\n',
    )
    monkeypatch.setenv("TF_POOL_CALLERS", str(path))
    dispatched: list[list[str]] = []
    monkeypatch.setattr(wd, "run_worker", dispatch_tests._fake_runner(dispatched))

    dispatch_tests._account_argv(monkeypatch, "--caller", "alice", "--execute")
    assert wd.main() == 2, "撤了的人必须拒派（退 2），不许退回「没登记」"
    err = capsys.readouterr().err
    assert "不派活" in err
    assert "调用方 alice（外包 A）已撤" in err
    assert "（off = true）—— 不许派活" in err

    monkeypatch.setattr(
        sys,
        "argv",
        ["wb_dispatch.py", "--card", "002", "--spec", "spec.md",
         "--caller", "bob", "--execute"],
    )
    assert wd.main() == 2
    err = capsys.readouterr().err
    assert "调用方 bob（无名）已撤" in err, f"没 label 要点「无名」：{err}"
    assert dispatched == [], "拒派时一个工人都不能起"


def test_bad_callers_toml_raises(tmp_path: Path) -> None:
    """④ 坏 TOML / 段名不对 / `off` 非布尔 / 数组写坏 ⇒ `CallersError`（**不当空**）。"""
    cases = {
        "语法坏（表头没闭合）": '[caller."alice"\noff = true\n',
        "段名不是 caller.<id>": '[callers."alice"]\noff = true\n',
        "调用方 id 是空串": '[caller.""]\noff = true\n',
        "off 不是布尔": '[caller."alice"]\noff = "yes"\n',
        "models 不是数组": '[caller."alice"]\nmodels = "m1"\n',
        "accounts 里有空串": '[caller."alice"]\naccounts = [""]\n',
        "label 不是字符串": '[caller."alice"]\nlabel = 1\n',
    }
    for name, body in cases.items():
        path = _roster(tmp_path, body, name="bad.toml")
        with pytest.raises(CallersError) as caught:
            callers.load_callers(path)
        assert str(caught.value), f"{name}：抛了但没给原因"


def test_empty_models_means_all(tmp_path: Path) -> None:
    """⑤ `models = []` 与缺键都是 `()`（= 全允许），与 `off` 无关。"""
    path = _roster(
        tmp_path,
        '[caller."explicit"]\nmodels = []\naccounts = []\n\n'
        '[caller."bare"]\nlabel = "没写那两栏"\n',
    )
    roster = callers.load_callers(path)
    assert roster["explicit"].models == ()
    assert roster["bare"].models == ()
    assert roster["explicit"].accounts == ()
    assert roster["bare"].accounts == ()
    assert callers.is_off(roster["explicit"]) is False
    assert callers.is_off(roster["bare"]) is False


def test_resolve_three_levels(tmp_path: Path, monkeypatch) -> None:
    """⑥ 显式 > 窗口 > `<hostname>:<pid>`；前两级与 `default_owner()` 同口径。"""
    monkeypatch.setenv("TF_POOL_CALLERS", str(tmp_path / "absent.toml"))
    fallback = f"{socket.gethostname()}:{os.getpid()}"
    monkeypatch.delenv("TF_WINDOW_ID", raising=False)
    assert registry.default_owner() == fallback
    assert callers.resolve().id == fallback
    assert callers.resolve("", env_window="").id == fallback

    monkeypatch.setenv("TF_WINDOW_ID", "window-7")
    assert registry.default_owner() == "window-7"
    assert callers.resolve(env_window=registry.default_owner()).id == "window-7"
    assert callers.resolve("explicit", env_window="window-7").id == "explicit"
    assert callers.resolve("  spaced  ", env_window="window-7").id == "spaced"


#: 本机私有盘符路径（`D:` / `C:` 后接分隔符）—— 判据 ⑦ 要挡的东西。
#: 写成正则而不是字面量：测试自己也不许出现仓外路径字面量。
_DRIVE_LETTER = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]")


def test_callers_path_derives_from_anchor(tmp_path: Path, monkeypatch) -> None:
    """⑦ 覆盖 > 号池目录 > 仓根；源码里除锚点外没有仓外绝对路径。"""
    override = tmp_path / "override.toml"
    monkeypatch.setenv("TF_POOL_CALLERS", str(override))
    assert callers.callers_path() == override

    monkeypatch.delenv("TF_POOL_CALLERS", raising=False)
    anchor = callers.pool_dir()
    base = anchor if anchor is not None else callers.TOOL_ROOT.joinpath(*callers.POOL_ANCHOR)
    assert callers.callers_path() == base / "callers.toml"
    assert callers.POOL_ANCHOR == ("infra", "pool")
    assert callers.CALLERS_NAME == "callers.toml"
    assert callers.ENV_CALLERS == "TF_POOL_CALLERS"
    assert callers.TOOL_ROOT == ROOT
    assert _DRIVE_LETTER.search(SOURCE) is None, "源码里不许有仓外绝对路径"


def test_no_secret_field_anywhere() -> None:
    """⑧ 凭据方向零命中；`Caller` 的字段集恰好五个。"""
    for word in ("compare_digest", "Bearer", "chmod", "secret", "masked"):
        assert word not in SOURCE, f"callers.py 里出现了 {word!r} —— 本卡不搬 secret"
    assert [field.name for field in dataclasses.fields(Caller)] == [
        "id",
        "label",
        "off",
        "models",
        "accounts",
    ]


def test_label_defaults_to_empty_and_is_never_used_as_id(
        tmp_path: Path, monkeypatch) -> None:
    """⑨ `label` 缺 ⇒ `""`；同名 label 不影响按 id 命中，label 也不当 id 用。"""
    path = _roster(
        tmp_path,
        '[caller."a"]\nlabel = "同一个名字"\n\n'
        '[caller."b"]\nlabel = "同一个名字"\n\n'
        '[caller."c"]\n',
    )
    monkeypatch.setenv("TF_POOL_CALLERS", str(path))
    roster = callers.load_callers()
    assert roster["c"].label == ""
    assert roster["a"].label == roster["b"].label == "同一个名字"
    assert callers.resolve("a").id == "a"
    assert callers.resolve("b").id == "b"
    assert callers.resolve("同一个名字") == Caller(id="同一个名字")


def test_off_is_the_only_revocable_switch(tmp_path: Path) -> None:
    """⑩ `deleted` / `revoked` / `removed` 一律 `CallersError`；撤只有 `off`。"""
    for bad in ("deleted", "revoked", "removed"):
        path = _roster(tmp_path, f'[caller."alice"]\n{bad} = true\n', name=f"{bad}.toml")
        with pytest.raises(CallersError) as caught:
            callers.load_callers(path)
        assert bad in str(caught.value), f"要点名那个键：{caught.value}"
    ok = _roster(tmp_path, '[caller."alice"]\noff = true\n', name="off.toml")
    assert callers.is_off(callers.load_callers(ok)["alice"]) is True


def test_load_callers_does_not_write(tmp_path: Path, monkeypatch) -> None:
    """⑪ 读一次后字节、mtime、目录里都没变（不许写 `.bak`、不许回写规范化 TOML）。"""
    path = _roster(tmp_path, '[caller."alice"]\nlabel = "外包 A"\nmodels = ["m1"]\n')
    before = (
        path.stat().st_mtime_ns,
        path.stat().st_size,
        hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    monkeypatch.setenv("TF_POOL_CALLERS", str(path))
    callers.load_callers()
    callers.load_callers(path)
    assert callers.resolve("alice").id == "alice"
    after = (
        path.stat().st_mtime_ns,
        path.stat().st_size,
        hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    assert after == before, "读名册不许改它（换了 mtime / 大小 / 字节）"
    assert sorted(item.name for item in tmp_path.iterdir()) == ["callers.toml"], \
        "读名册不许在旁边生出文件（`.bak` 兜底是最坏回归）"


def test_pool_dir_does_not_follow_cwd(tmp_path: Path, monkeypatch) -> None:
    """⑫ 换 cwd 后 `pool_dir()` 结果不变（`Path.cwd()` 版会跟着跑）。"""
    fake_root = tmp_path / "tree"
    (fake_root / "infra" / "pool").mkdir(parents=True)
    elsewhere = tmp_path / "deep" / "cwd"
    elsewhere.mkdir(parents=True)
    expected = fake_root / "infra" / "pool"
    assert callers.pool_dir(start=fake_root) == expected
    before = callers.pool_dir()
    monkeypatch.chdir(elsewhere)
    assert callers.pool_dir(start=fake_root) == expected
    assert callers.pool_dir() == before
