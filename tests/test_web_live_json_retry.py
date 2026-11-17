"""核「一次没读到不等于服务坏了」的有界重放会不会咬（卡 E134 · T-AG643）。

## 为什么有这张测试

GitHub Actions 的 windows runner 上，`web_live` 门真红，原文：

```text
[FAIL] 真机自检没跑完：PUT http://127.0.0.1:50280/api/settings/ai
         ★ PUT http://127.0.0.1:50280/api/settings/ai 等了 30 秒没等到（TimeoutError: timed out）
```

而服务端日志是 `PUT /api/settings/ai status 200 ms 19.4` —— 客户端在等一个**已经写完的响应**。
同一份文件里 `_lan_json` 早就有有界重试（卡 E85），`_json_call` 一直没有。

## 怎么验

把 `urllib.request.urlopen` 打成桩，验的是 `_json_call` 自己的重放收口：
① 已拿到状态码（`HTTPError`）**绝不重放**；
② 超时 / 对端先关 ⇒ 有界重放，用尽后报 `broken_read=True`；
③ 写方法默认**不**重放，要调用点显式 `retry_ok=True`；
④ 等待窗与默认次数都不变（不允许拿「等得更久」顶替就绪判据）。

## 边界（如实写，未覆盖）

- 不真起 uvicorn（`tests/test_web_live_lan_timeout.py` 已记录真机层是盲区）。
- 桩只替「网络怎么回」，不替判据本体。
"""

from __future__ import annotations

import importlib.util
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"


def _load(name: str, path: Path):
    """按文件路径装模块（同名模块可能已被别的测试装过，这里换唯一名字）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # 先登记：否则模块里的 dataclass 会炸
    spec.loader.exec_module(mod)
    return mod


wlc = _load("web_live_check_for_e134", TOOLS / "web_live_check.py")


class _Resp:
    """假的 200 响应（与 `tests/test_web_live_timeout.py` 同形）。"""

    status = 200

    def read(self):
        return b'{"id": "t-1"}'

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class _Counter:
    """记「`urlopen` 被打了几次」，并按预约定序列回应。"""

    def __init__(self, script: list[object]) -> None:
        self.script = list(script)
        self.calls = 0

    def __call__(self, *_a, **_kw):
        self.calls += 1
        step = self.script.pop(0) if self.script else self.script_default
        if isinstance(step, BaseException):
            raise step
        return step

    script_default: object = _Resp()


def _install(monkeypatch, counter: _Counter) -> None:
    monkeypatch.setattr(wlc.urllib.request, "urlopen", counter)


# ============================================================ 判据 1 · 次数可调、有上限


def test_json_retry_defaults_to_one_and_is_env_tunable(monkeypatch):
    """★ 主钉子：默认 1 次；`3` 就是 3；`0` 是**合法**值（明确关掉）。"""
    monkeypatch.delenv(wlc.JSON_RETRY_ENV, raising=False)
    assert wlc.json_retry() == 1, "默认次数被改了"
    monkeypatch.setenv(wlc.JSON_RETRY_ENV, "3")
    assert wlc.json_retry() == 3
    monkeypatch.setenv(wlc.JSON_RETRY_ENV, "0")
    assert wlc.json_retry() == 0


def test_junk_retry_value_falls_back_instead_of_going_infinite(monkeypatch):
    """**反例**：坏值 / 负数 ⇒ 退回默认；超大值 ⇒ 夹上限，不允许打到天荒地老。"""
    for bad in ("abc", "-1", "", " "):
        monkeypatch.setenv(wlc.JSON_RETRY_ENV, bad)
        assert wlc.json_retry() == 1, f"坏值 {bad!r} 没退回默认"
    monkeypatch.setenv(wlc.JSON_RETRY_ENV, "9999")
    assert wlc.json_retry() == wlc.JSON_RETRY_MAX == 5, "env 写多大就真打多少次"


# ============================================================ 判据 2 · 三态


def test_a_status_code_is_never_retried(monkeypatch):
    """★ 主钉子：已拿到状态码（404）⇒ `urlopen` 只被打 **1** 次，返回 `(404, None)`。"""
    counter = _Counter([urllib.error.HTTPError("http://x/y", 404, "Not Found", {}, None)])
    counter.script_default = urllib.error.HTTPError("http://x/y", 404, "Not Found", {}, None)
    _install(monkeypatch, counter)
    assert wlc._json_call("http://x", "/y") == (404, None)
    assert counter.calls == 1, f"状态码被重放了 {counter.calls} 次（会把 403/404 洗成 200）"


def test_timeout_then_success_retries_only_once(monkeypatch):
    """★ 主钉子：第一次超时、第二次 200 ⇒ 返回 200，计数 = 2（就是这一步吸掉了 GHA 那次抖动）。"""
    counter = _Counter([TimeoutError("timed out"), _Resp()])
    _install(monkeypatch, counter)
    code, body = wlc._json_call(
        "http://x", "/api/settings/ai", "PUT", {"enabled": True}, retry_ok=True
    )
    assert (code, body["id"]) == (200, "t-1")
    assert counter.calls == 2


def test_broken_read_then_success_is_also_retried(monkeypatch):
    """「连上了但对端先关了」与超时同一类（`broken_read`）—— 也要重放。"""
    counter = _Counter([ConnectionResetError(10054, "An existing connection was forcibly closed")])
    _install(monkeypatch, counter)
    assert wlc._json_call("http://x", "/api/summary")[0] == 200
    assert counter.calls == 2


def test_a_request_that_never_arrived_is_not_retried(monkeypatch):
    """**反例**：拒连（`ConnectionRefusedError`）⇒ 请求根本没送到。

    重放只是白等；应当直接抛且计数 = 1。
    """
    counter = _Counter([ConnectionRefusedError(10061, "actively refused")])
    counter.script_default = ConnectionRefusedError(10061, "actively refused")
    _install(monkeypatch, counter)
    with pytest.raises(wlc.LiveCallError) as ei:
        wlc._json_call("http://x", "/api/summary")
    assert counter.calls == 1, "拒连被重放了"
    assert ei.value.broken_read is False, "拒连不是「没读到响应」"
    assert "ConnectionRefusedError" in str(ei.value)


# ============================================================ 判据 3 · 幂等面


def test_post_is_not_retried_by_default(monkeypatch):
    """★ 主钉子：`POST` 第一次超时 ⇒ 直接抛，计数 = 1（重放一次就多建一条任务）。"""
    counter = _Counter([TimeoutError("timed out")])
    counter.script_default = _Resp()
    _install(monkeypatch, counter)
    with pytest.raises(wlc.LiveCallError):
        wlc._json_call("http://x", "/api/tasks", "POST", {"title": "t"})
    assert counter.calls == 1


def test_explicitly_idempotent_write_is_retried(monkeypatch):
    """★ 主钉子：同一场景加 `retry_ok=True` ⇒ 计数 = 2、返回 200。"""
    counter = _Counter([TimeoutError("timed out"), _Resp()])
    _install(monkeypatch, counter)
    assert wlc._json_call("http://x", "/api/settings/ai", "PUT", {"enabled": True},
                          retry_ok=True)[0] == 200
    assert counter.calls == 2


def test_get_and_head_are_replayable_without_a_flag(monkeypatch):
    """**反例**：`GET` / `HEAD` 是纯读，不用标 `retry_ok` 也进重放面。"""
    for method in ("GET", "HEAD"):
        counter = _Counter([TimeoutError("timed out"), _Resp()])
        _install(monkeypatch, counter)
        assert wlc._json_call("http://x", "/api/summary", method)[0] == 200
        assert counter.calls == 2, f"{method} 没进重放面"


# ============================================================ 判据 4 · 日志与命名


def test_retry_zero_means_no_second_request(monkeypatch):
    """`TF_WEB_LIVE_JSON_RETRY=0` ⇒ 计数 1（就是改前的行为，留着回退口）。"""
    counter = _Counter([TimeoutError("timed out")])
    counter.script_default = _Resp()
    _install(monkeypatch, counter)
    monkeypatch.setenv(wlc.JSON_RETRY_ENV, "0")
    with pytest.raises(wlc.LiveCallError):
        wlc._json_call("http://x", "/api/summary")
    assert counter.calls == 1


def test_exhausted_retry_is_named_broken_read(monkeypatch):
    """★ 主钉子：用尽后报 `broken_read=True`，消息里有 endpoint 与方法。"""
    counter = _Counter([TimeoutError("timed out")])
    counter.script_default = TimeoutError("timed out")
    _install(monkeypatch, counter)
    with pytest.raises(wlc.LiveCallError) as ei:
        wlc._json_call("http://x", "/api/settings/ai", "PUT", {"enabled": True}, retry_ok=True)
    err = ei.value
    assert counter.calls == 2, f"默认应该试 2 次，实际 {counter.calls}"
    assert err.broken_read is True
    assert "/api/settings/ai" in str(err) and "PUT" in str(err)
    assert "没读到响应" in str(err), "没把「没读到」说清楚"


def test_each_replay_prints_one_retry_line(monkeypatch, capsys):
    """每次重放打一行 `[ 重试]`（与 `_lan_json` 同形）—— 否则日志里看不出来抖了。"""
    counter = _Counter([TimeoutError("timed out"), _Resp()])
    _install(monkeypatch, counter)
    wlc._json_call("http://x", "/api/summary")
    out = capsys.readouterr().out
    assert "[重试]" in out and "TimeoutError" in out, f"没打重试行：{out!r}"

