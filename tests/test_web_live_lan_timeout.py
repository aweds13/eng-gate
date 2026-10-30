"""核「局域网客户端自己那份 3 秒窗」修好了没有（卡 E71 · T-AG554）。

## 为什么有这张测试

`tools/web_live_check.py` 里有**两份** HTTP 客户端。卡 E67 只修了 `_json_call()`，
第二份 `_lan_json()` 还留着自己的病灶：

- 自己写死 `timeout: int = 3`，**不认** `call_timeout()`，也不认 env `TF_WEB_LIVE_TIMEOUT`；
- 结尾 `except (urllib.error.URLError, OSError): return 0, None` —— `TimeoutError` 是
  `OSError` 的子类 ⇒ 超时被静默降级成「连不上」。

于是服务端明明回了 401，调用点 `nopair[0] == 401` 只看到 0，云机门报
`[FAIL] 手机直传：没配对传不进来（401）`。**判据没错，诊断错了**：真因是那 3 秒没等够
（云机 2 物理核，带整包体的 `POST /api/sync/import` 慢过 3 秒是常态）。

## 怎么验

① 等待窗与 `_json_call` **同源**（`None` ⇒ `call_timeout()`，env 可调）；
② 超时是**可判定的第三态**：抛点名 `LiveCallError`，不混进「连不上」；
③ 探针现场转绿：真起一个睡 5 秒再回 401 的 HTTP 服务，默认窗（10 秒）能读到 401；
④ 一个地址等不到不许杀死整组检查，已算出的 checks 一条都不许丢。

## 边界（如实写，未覆盖）

- ③ 是**真** `ThreadingHTTPServer`（不是桩），但仍在回环上，**没在真云机复核**。
- ⑦⑧ 把 uvicorn / app / `_lan_json` 打成桩，验的是 `live_lan_checks()` 的**收口行为**
  （控制流），不是真局域网。
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import timeflow.core.lan as lan_mod

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


wlc = _load("web_live_check_for_e71", TOOLS / "web_live_check.py")


class _RefusedError(Exception):
    """假的底层异常（`URLError.reason` 的形状）。"""


def _bad_opener(monkeypatch, exc: BaseException, seen: dict[str, object]):
    """把 `build_opener()` 换成一个**一定失败**的私有 opener，并记下等待窗。"""

    class _Opener:
        def open(self, req, timeout=None):
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["timeout"] = timeout
            raise exc

    monkeypatch.setattr(wlc.urllib.request, "build_opener", lambda *_a, **_kw: _Opener())


# ============================================================ ① 等待窗与 _json_call 同源


def test_lan_wait_window_defaults_to_call_timeout(monkeypatch):
    """★ 主钉子：`timeout=None` ⇒ `call_timeout()`（默认 10 秒），**不再是写死的 3**。"""
    monkeypatch.delenv(wlc.CALL_TIMEOUT_ENV, raising=False)
    seen: dict[str, object] = {}
    _bad_opener(monkeypatch, TimeoutError("timed out"), seen)
    with pytest.raises(wlc.LiveCallError):
        wlc._lan_json("http://10.0.0.9:8531", "/api/sync/import", "POST", {"pack": {}})
    assert seen["timeout"] == wlc.call_timeout() == 10.0, (
        f"等待窗没走 call_timeout()：{seen['timeout']!r}"
    )
    assert seen["timeout"] != 3, "又变回那份自己写死的 3 秒窗了"


def test_lan_wait_window_follows_the_env(monkeypatch):
    """★ 主钉子：env `TF_WEB_LIVE_TIMEOUT` 一给，局域网这份客户端也得认（云机调它）。"""
    monkeypatch.setenv(wlc.CALL_TIMEOUT_ENV, "42")
    seen: dict[str, object] = {}
    _bad_opener(monkeypatch, TimeoutError("timed out"), seen)
    with pytest.raises(wlc.LiveCallError):
        wlc._lan_json("http://10.0.0.9:8531", "/")
    assert seen["timeout"] == 42.0, f"env 是个摆设：{seen['timeout']!r}"


def test_lan_explicit_timeout_still_wins(monkeypatch):
    """按次覆盖仍可用（签名里的 `timeout` 参数没被吞掉）。"""
    monkeypatch.setenv(wlc.CALL_TIMEOUT_ENV, "42")
    seen: dict[str, object] = {}
    _bad_opener(monkeypatch, TimeoutError("timed out"), seen)
    with pytest.raises(wlc.LiveCallError):
        wlc._lan_json("http://10.0.0.9:8531", "/", timeout=1.5)
    assert seen["timeout"] == 1.5, f"按次覆盖失效：{seen['timeout']!r}"


# ============================================================ ② 超时是可判定的第三态


def test_lan_timeout_is_named_not_swallowed(monkeypatch):
    """★ 主钉子：超时抛**点名**的 `LiveCallError`，消息含 endpoint 与秒数。"""
    monkeypatch.delenv(wlc.CALL_TIMEOUT_ENV, raising=False)
    seen: dict[str, object] = {}
    _bad_opener(monkeypatch, TimeoutError("timed out"), seen)
    with pytest.raises(wlc.LiveCallError) as ei:
        wlc._lan_json("http://10.0.0.9:8531", "/api/sync/import", "POST", {"pack": {}})
    msg = str(ei.value)
    assert "/api/sync/import" in msg, f"没点名 endpoint：{msg}"
    assert "POST" in msg, f"没点名方法：{msg}"
    assert "TimeoutError" in msg, f"没点名原始异常类型：{msg}"
    assert "10" in msg, f"没写等了几秒：{msg}"


def test_lan_urlerror_wrapping_timeout_is_also_named(monkeypatch):
    """★ 主钉子：`URLError` 只是外壳 —— `reason` 是超时就必须点名，不许当「连不上」。"""
    monkeypatch.delenv(wlc.CALL_TIMEOUT_ENV, raising=False)
    seen: dict[str, object] = {}
    _bad_opener(monkeypatch, urllib.error.URLError(TimeoutError("timed out")), seen)
    with pytest.raises(wlc.LiveCallError) as ei:
        wlc._lan_json("http://10.0.0.9:8531", "/api/health")
    msg = str(ei.value)
    assert "/api/health" in msg and "URLError" in msg, f"包着超时的 URLError 被吞了：{msg}"
    assert "10" in msg, f"没写等了几秒：{msg}"


def test_lan_refused_is_still_zero_and_none(monkeypatch):
    """**反例**：连接被拒（真·连不上）保持 `(0, None)`，**不许抛**。"""
    monkeypatch.delenv(wlc.CALL_TIMEOUT_ENV, raising=False)
    seen: dict[str, object] = {}
    _bad_opener(monkeypatch, urllib.error.URLError(_RefusedError("connection refused")), seen)
    assert wlc._lan_json("http://10.0.0.9:8531", "/") == (0, None)


def test_lan_http_401_still_returns_its_code(monkeypatch):
    """**反例**：4xx 仍返回 `(状态码, body)` —— 判据 `[0] == 401` 靠的就是这一路。"""

    class _Opener:
        def open(self, req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(wlc.urllib.request, "build_opener", lambda *_a, **_kw: _Opener())
    code, _body = wlc._lan_json("http://10.0.0.9:8531", "/api/sync/import", "POST", {"pack": {}})
    assert code == 401, f"401 被降级了：{code}"


# ============================================================ ③ 探针现场：真起服务


class _Slow401(BaseHTTPRequestHandler):
    """真 HTTP 服务：收 POST 后**睡 5 秒**再回 401（复现云机那条慢请求）。"""

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        threading.Event().wait(5.0)
        body = json.dumps({"detail": "没配对码，传不进来"}).encode("utf-8")
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_a):
        return


@pytest.fixture
def slow_401_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Slow401)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=10)


def test_slow_401_is_read_when_the_window_is_wide_enough(monkeypatch, slow_401_server):
    """★ 主钉子（判据 3）：服务端睡 5 秒再回 401，不设 env（默认 10 秒）⇒ 读到的是 401。"""
    monkeypatch.delenv(wlc.CALL_TIMEOUT_ENV, raising=False)
    code, _body = wlc._lan_json(
        slow_401_server, "/api/sync/import", "POST", {"pack": {"v": 1}}
    )
    assert code == 401, f"慢请求被当成了「连不上」：code={code!r}"


# ============================================================ ④ 一条地址不许杀死整组


def _install_fake_lan_env(monkeypatch, lan_json, addrs=("http://10.0.0.9:8531",)):
    """把 uvicorn / app / 线程 / 手机包都打桩，只留 `live_lan_checks()` 自己的控制流。"""

    class _Cfg:
        def __init__(self, *_a, **_kw):
            pass

    class _Srv:
        def __init__(self, _cfg):
            self.started = True
            self.should_exit = False

        def run(self):
            return

    class _Thread:
        def __init__(self, *_a, **_kw):
            pass

        def start(self):
            return

        def join(self, timeout=None):
            return

    def _json_call(_base, _path, _method="GET", _payload=None, _headers=None, timeout=None):
        return 200, {
            "code": "654321",
            "self_reachable": True,
            "addresses": ["10.0.0.9"],
            "hint": "校园网 / 移动热点",
        }

    monkeypatch.setattr(wlc.uvicorn, "Config", _Cfg)
    monkeypatch.setattr(wlc.uvicorn, "Server", _Srv)
    monkeypatch.setattr(wlc.threading, "Thread", _Thread)
    monkeypatch.setattr(wlc, "create_app", lambda *_a, **_kw: object())
    monkeypatch.setattr(lan_mod, "local_addresses", lambda port=0: list(addrs))
    monkeypatch.setattr(wlc, "_lan_json", lan_json)
    monkeypatch.setattr(wlc, "_json_call", _json_call)
    monkeypatch.setattr(wlc, "_phone_pack", lambda *_a, **_kw: None)


def test_one_dead_address_does_not_kill_the_other_checks(monkeypatch, capsys):
    """★ 主钉子（判据 4 前半）：第一个地址等不到 ⇒ 打提示换下一个，整组照跑。"""
    dead, good = "http://10.0.0.9:8531", "http://192.168.1.7:8531"

    def lan_json(base, path, method="GET", payload=None, headers=None, timeout=None):
        if base == dead:
            wait = wlc.call_timeout() if timeout is None else timeout
            raise wlc.LiveCallError(method, f"{base}{path}", wait, TimeoutError("timed out"))
        if path == "/api/health":
            if headers is None:
                return 401, {"detail": "要配对码"}
            return 200, {"ok": True}
        if path == "/api/lan/pair":
            return (401, None) if (payload or {}).get("code") == "000000" else (200, None)
        if path == "/api/settings/lan":
            return 200, {"code": ""}
        return 200, None

    _install_fake_lan_env(monkeypatch, lan_json, addrs=(dead, good))
    monkeypatch.delenv(wlc.CALL_TIMEOUT_ENV, raising=False)

    checks = wlc.live_lan_checks(Path("."))

    out = capsys.readouterr().out
    assert dead in out and "换下一个" in out, f"没说换下一个：{out!r}"
    assert "[SKIP] 局域网真机检查" not in out, f"一条地址等不到就把整组跳了：{out!r}"
    assert checks, "整组检查被一条坏地址杀光了"
    assert not any(k.startswith("局域网：有一步没等到") for k in checks), (
        f"好地址那条路不该出现「等不到」：{checks}"
    )
    assert checks["局域网：静态壳能打开（否则手机没处输配对码）"] is True
    assert all(isinstance(v, bool) for v in checks.values())


def test_partial_lan_checks_are_kept_with_one_false_row(monkeypatch, capsys):
    """★ 主钉子（判据 4 后半）：主体某步等不到 ⇒ 已算出的 checks 全留，再加一条点名 False。"""
    base = "http://10.0.0.9:8531"

    def lan_json(addr, path, method="GET", payload=None, headers=None, timeout=None):
        if path == "/api/lan/pair":
            wait = wlc.call_timeout() if timeout is None else timeout
            raise wlc.LiveCallError(method, f"{addr}{path}", wait, TimeoutError("timed out"))
        if path == "/api/health":
            return 401, {"detail": "要配对码"}
        return 200, None

    _install_fake_lan_env(monkeypatch, lan_json, addrs=(base,))
    monkeypatch.delenv(wlc.CALL_TIMEOUT_ENV, raising=False)

    checks = wlc.live_lan_checks(Path("."))

    assert checks["局域网：静态壳能打开（否则手机没处输配对码）"] is True, "已算出的那条被丢了"
    assert checks["局域网：没配对读不到数据（401 + 原话）"] is True, "已算出的那条被丢了"
    false_rows = [k for k, v in checks.items() if v is False]
    assert len(false_rows) == 1, f"不该多出别的 False：{checks}"
    assert false_rows[0].startswith("局域网：有一步没等到（") and "/api/lan/pair" in false_rows[0]
    assert len(checks) == 3, f"整组被换成一条笼统 FAIL 了：{checks}"
    assert "[FAIL]" in capsys.readouterr().out
