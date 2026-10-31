"""卡 A361 / F89：账号发现可关（magpie `AccountDiscoveryOff` 移植）的钉子。

每条钉对着设计原件 `_port_design_wave5.md` §2.2 的七条判据，并且**每条都同时证明两件事**：

1. 闸关（`TF_NO_ACCOUNT_DISCOVERY` 取真值）时，那一次「去碰账号位点」的动作**根本没有发生**
   —— 不是「发生了但结果被过滤掉」。判据 1/2 用**调用计数桩**断言次数 = 0，
   因为「返回空列表」这种断言会被「stat 了再过滤」骗过去。
2. 闸不关（默认）时行为**与今天一模一样** —— 这是本卡的回归保护。

「同一个错误」照 `internal/provider/discovery.go:29` 的形状：一个常量文案
`DISCOVERY_OFF_MESSAGE`，三个面（读文件 / 枚举目录 / 发请求）用同一句。
文案里**不许出现任何路径**（判据 7）。
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

pa = importlib.import_module("pool_accounts")
ck = importlib.import_module("pool.checkin")

ENV = "TF_NO_ACCOUNT_DISCOVERY"

PLAT = {
    "name": "codearts",
    "probe": "http",
    "token_env": "A361_TOKEN_A/A361_TOKEN_B",
    "probe_url": "https://example.invalid/quota",
    "base_urls": ["https://example.invalid"],
}
ACC = {"id": "a1", "platform": "codearts", "state": "active"}


@pytest.fixture()
def gate(monkeypatch):
    """默认把闸**清掉**（等于没设）：每条钉自己决定要不要关。"""

    def set_gate(value: str | None) -> None:
        if value is None:
            monkeypatch.delenv(ENV, raising=False)
        else:
            monkeypatch.setenv(ENV, value)

    set_gate(None)
    return set_gate


# --------------------------------------------------------------- 调用计数桩


class StatSpy:
    """把 `Path.exists` 与 `os.scandir` 换成只记调用、再**转发给真实现**的桩（判据 1）。

    两件事都要做对：

    * 记调用次数 —— 判据是「一次都没 stat」，不是「返回空列表」（那样「stat 了再过滤」
      也能过）。
    * 转发给真实现 —— 桩如果自己造返回值，pytest 内部的 `Path.exists` 也会被骗
      （实测：造返回值会让收集阶段 `INTERNALERROR`，于是这条变异「红了但不是那条钉子」，
      算假咬）。

    用闭包而不是绑定方法：把 `self._exists` 直接挂到 `Path` 上时它已经绑好了，
    `p.exists()` 不会再传 path 进来。
    """

    def __init__(self, monkeypatch) -> None:
        self.exists_calls: list[str] = []
        self.scandir_calls: list[str] = []
        real_exists = Path.exists
        real_scandir = pa.os.scandir

        def _exists(path):
            self.exists_calls.append(str(path))
            return real_exists(path)

        def _scandir(path):
            self.scandir_calls.append(str(path))
            return real_scandir(path)

        monkeypatch.setattr(Path, "exists", _exists)
        monkeypatch.setattr(pa.os, "scandir", _scandir)

    @property
    def total(self) -> int:
        return len(self.exists_calls) + len(self.scandir_calls)


class EnvironSpy:
    """把 `os.environ` 换成只记 `get`/`__getitem__` 的映射（判据 2）。

    读写都**转发到真的 os.environ**，只是把每次读的名字记下来 —— 否则
    `monkeypatch.setenv` 会写不进去。
    """

    def __init__(self, monkeypatch) -> None:
        self.reads: list[str] = []
        outer = self
        real = pa.os.environ

        class _Proxy:
            def get(self, key, default=None):
                outer.reads.append(key)
                return real.get(key, default)

            def __getitem__(self, key):
                outer.reads.append(key)
                return real[key]

            def __setitem__(self, key, value):
                real[key] = value

            def __delitem__(self, key):
                del real[key]

            def __contains__(self, key):
                outer.reads.append(key)
                return key in real

            def __iter__(self):
                return iter(real)

            def __getattr__(self, name):
                return getattr(real, name)

        monkeypatch.setattr(pa.os, "environ", _Proxy())


# --------------------------------------------------- 判据 1：discover 不 stat


def test_off_returns_empty_without_stat(gate, monkeypatch):
    """判据 1：闸关 ⇒ `discover(...)` 返回 `[]`，且**一个位点都没被 stat**。

    咬法：把 `Path.exists` / `os.scandir` 换成记录调用的桩，断言次数 = 0。
    只断言「返回空」是不够的 —— 「先 stat 再过滤」也能返回空。
    """
    gate("1")
    spy = StatSpy(monkeypatch)
    rows = pa.discover(["~/codeartsdoer/pool.env", "~/.workbuddy"], ["~/extra"])
    assert rows == []
    assert spy.exists_calls == []
    assert spy.scandir_calls == []
    assert spy.total == 0


def test_off_discover_still_returns_empty_with_root(gate, tmp_path):
    """判据 1 的补充：给了 `root` 注入也一样空（闸比 root 更早）。"""
    gate("true")
    (tmp_path / "probe").mkdir()
    assert pa.discover(["probe"], root=tmp_path) == []


# ------------------------------------------------- 判据 2：_token_for 不读环境


def test_off_reads_no_env(gate, monkeypatch):
    """判据 2：闸关 ⇒ `_token_for(plat)` 返回 `("", "")` 且**没读 token 变量**。

    咬法：把 `os.environ` 换成记录 `get` 的代理，断言这些 token 名一次都没出现。
    """
    gate("1")
    monkeypatch.setenv("A361_TOKEN_A", "should-not-be-read")
    spy = EnvironSpy(monkeypatch)
    assert pa._token_for(PLAT) == ("", "")
    assert "A361_TOKEN_A" not in spy.reads
    assert "A361_TOKEN_B" not in spy.reads


def test_off_token_for_names_empty(gate):
    """判据 2：返回的第二格（环境变量名）也要空 —— 不许「报个名字说没读到」。"""
    gate("yes")
    token, name = pa._token_for({"token_env": "A/B"})
    assert (token, name) == ("", "")


# ------------------------------------------------------ 判据 3：probe 是 skipped


def test_off_probe_is_skipped_not_uncertain(gate):
    """判据 3：闸关 ⇒ `probe_account` 给 `skipped`，**不是** `uncertain` / `failed`。

    三码差别是判据的一部分：`uncertain` 说「我有凭据但不敢发」，
    `skipped` 说「我根本不该看」。
    """
    gate("on")
    row = pa.probe_account(ACC, PLAT)
    assert row["kind"] == "skipped"
    assert row["kind"] not in ("uncertain", "failed")
    assert row["detail"] == pa.DISCOVERY_OFF_MESSAGE


def test_off_probe_all_is_skipped_for_every_account(gate):
    """判据 3：`probe_all` 同理，**每一条**都是 skipped（不是只有第一条）。"""
    gate("1")
    data = {"account": [ACC, {"id": "a2", "platform": "codearts", "state": "active"}]}
    rows = pa.probe_all(data, {"codearts": PLAT})
    assert [r["kind"] for r in rows] == ["skipped", "skipped"]
    assert {r["detail"] for r in rows} == {pa.DISCOVERY_OFF_MESSAGE}


def test_off_probe_all_does_not_consult_platform_table(gate):
    """判据 3 的边界：闸关时连平台能力表都不查 —— 不许给 `unknown-platform`。

    `unknown-platform` 的意思是「查过了、表里没有」；闸关时不该查。
    """
    gate("1")
    data = {"account": [{"id": "a3", "platform": "not-in-table", "state": "active"}]}
    rows = pa.probe_all(data, {})
    assert [r["kind"] for r in rows] == ["skipped"]


# --------------------------------------------------- 判据 4：checkin 取不到凭据


def test_off_checkin_token_is_empty(gate):
    """判据 4：闸关 ⇒ `checkin.tokens_from_env(...)` 返回空（一个 token 都不取）。"""
    gate("1")
    got = ck.tokens_from_env({"token_env": "A361_TOKEN_A/A361_TOKEN_B"}, {"A361_TOKEN_A": "va"})
    assert got == []


# --------------------------------------------------- 判据 5：默认照旧工作（回归）


def test_absent_keeps_todays_behaviour(gate):
    """判据 5：闸**缺席** ⇒ 行为与今天一模一样（否则号池会凭空消失）。"""
    gate(None)
    assert pa.discovery_off() is False
    # discover 照旧按位点数出行，`declared` 只认账本里声明过的那些
    rows = pa.discover(["~/.codeartsdoer/pool.env"])
    pointers = [r["pointer"] for r in rows]
    assert "~/.codeartsdoer/pool.env" in pointers
    assert pointers[0] == "~/.codeartsdoer/pool.env"
    assert len(pointers) == 1 + len(pa.DECLARED_DIRS)
    assert rows[0]["declared"] is True
    assert rows[0]["status"] == "已登记"
    assert rows[1]["status"] == "未声明"
    # _token_for 照旧取第一个非空的
    token, name = pa._token_for(PLAT)
    assert (token, name) == ("", "A361_TOKEN_A/A361_TOKEN_B")
    # checkin 照旧按 / 切
    assert ck.tokens_from_env({"token_env": "A/B"}, {"A": "va", "B": "vb"}) == ["va", "vb"]


def test_absent_probe_keeps_uncertain_when_no_token(gate):
    """判据 5 的回归面：闸没设 ⇒ 没凭据仍是 `uncertain`（不是 skipped）。"""
    gate(None)
    row = pa.probe_account(ACC, PLAT)
    assert row["kind"] == "uncertain"
    assert "要真探请设" in row["detail"]


def test_absent_discover_counts_entries(gate, monkeypatch, tmp_path):
    """判据 5 的回归面：闸没设 ⇒ 目录存在时照旧数条目（`_count` 仍被用上）。"""
    gate(None)
    d = tmp_path / "acct"
    d.mkdir()
    (d / "one.env").write_text("x", encoding="utf-8")
    (d / "two.env").write_text("y", encoding="utf-8")
    rows = pa.discover(["acct"], root=tmp_path)
    assert rows[0]["exists"] is True
    assert rows[0]["entries"] == 2


# ------------------------------------------------------------ 判据 6：真值表


@pytest.mark.parametrize("value", ["1", "true", "TRUE", " yes ", "on", "On"])
def test_truthy_parsing_table_off(gate, value):
    """判据 6：这四个（大小写与空白无关）算「关」。"""
    gate(value)
    assert pa.discovery_off() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "OFF", "maybe", "  "])
def test_truthy_parsing_table_on(gate, value):
    """判据 6：`""` / `"0"` / `"false"` / `"no"` / `"off"` 与认不出来的值算「没关」。

    空串等于没设（与 `tools/pool/models.py` 的 `SWITCH_PATH_ENV` 同体例）。
    """
    gate(value)
    assert pa.discovery_off() is False


def test_empty_string_equals_unset(gate, monkeypatch):
    """判据 6 的同一性：`""` 与「没这个键」走同一条路。"""
    gate("")
    empty = pa.discovery_off()
    monkeypatch.delenv(ENV, raising=False)
    assert empty == pa.discovery_off() is False


# ------------------------------------------------------- 判据 7：文案不带路径


def test_message_names_no_path(gate):
    """判据 7：文案含「account discovery is off」，且不泄露任何路径。"""
    gate("1")
    detail = pa.probe_account(ACC, PLAT)["detail"]
    assert "account discovery is off" in detail
    lowered = detail.lower()
    for leak in ("/", "\\", "~", ":/", "accounts.toml", "platforms.toml"):
        assert leak not in lowered.replace("（", "").replace("）", "")
    assert "Settings" not in detail  # 不抄 magpie 的设置页指引
    assert detail == pa.DISCOVERY_OFF_MESSAGE


def test_error_class_carries_same_message():
    """判据 7：那个「同一个错误」是个异常类，文案与常量逐字相同。"""
    exc = pa.DiscoveryOffError()
    assert isinstance(exc, RuntimeError)
    assert str(exc) == pa.DISCOVERY_OFF_MESSAGE
    assert isinstance(pa.DiscoveryOffError("自定义"), pa.DiscoveryOffError)
    assert str(pa.DiscoveryOffError("自定义")) == "自定义"


# --------------------------------------------------- 命令行面：连账本都不读


def test_cli_discover_off_prints_empty_rows(gate, capsys):
    """闸关 ⇒ `main(["discover"])` 退 0、`{"rows": []}`、且解释走 stderr。"""
    gate("1")
    assert pa.main(["discover", "--json"]) == pa.EXIT_OK
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"rows": []}
    assert "account discovery is off" in captured.err
