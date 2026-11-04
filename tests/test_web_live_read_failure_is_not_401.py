"""核「没读到响应」不许被说成「服务端没回 401」（卡 E85 · T-AG592）。

## 为什么有这张测试

云门禁 E84 那趟 22 门只有 `web_live` 一门红，摘要写的是
`[FAIL] 手机直传：没配对传不进来（401）`——听起来像「服务端没给 401」，
可服务端那一刻**确实回了 401**（`.wt/E84/gates/logs/web_live.log` 有
`"path":"/api/sync/import","status":401`）。真因在客户端：服务端中间件
（`src/timeflow/api/app.py:303`）不读请求体就回 401 并关连接，客户端撞
`ConnectionResetError`，而 `tools/web_live_check.py:851` 的
`except OSError: return 0, None` 把「连上了但没读到响应」洗成了「连不上」，
判据 `nopair[0] == 401` 只看到 0。

## 怎么验

① 「请求根本没送到」（拒连 / 无路由）仍是 `(0, None)`——这条不许被改坏；
② 「连上了但没读到状态行」（对端 RST）必须抛 `LiveCallError`，`.kind` 是原始异常名；
③ 这类失败**有界重试**（默认 1 次），重试成功就正常返回状态码；
④ `TF_WEB_LIVE_RETRY=0` 关掉重试；⑤ **已拿到状态码的调用绝不重试**；
⑥ `live_lan_checks()` 收口不许退化：已算出的 checks 全留 + 一条点名 False，
且**不出现**把责任推给 401 的那一条。

## 边界（如实写，未覆盖）

- ②③④ 用的是**真 socket 服务**（`SO_LINGER=0` 主动发 RST），不是桩。
- ⑥ 把 uvicorn / app / `_lan_json` 打成桩，验的是控制流，不是真局域网。
- 现场那一趟的**真正成因没有复现出来**（卡 E85 卡规格里逐条写了八个探针），
  本文件只保证「下次发生时门说的是实话」。
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import socket
import struct
import sys
import threading
import time
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


wlc = _load("web_live_check_for_e85", TOOLS / "web_live_check.py")


# ==================================================== 真 socket：接受后立刻 RST

class _RstServer:
    """真 TCP 服务：accept 后带 `SO_LINGER=0` 关连接（客户端会收到 RST）。

    `serve_after` 给了就「前 N 次 RST，之后按 HTTP/1.1 回 401」——用来区分
    「重试后成功」与「只重试一次」。`hits` 记一共收了几条连接。
    """

    def __init__(self, *, serve_after: int | None = None) -> None:
        self.hits: list[float] = []
        self._serve_after = serve_after
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(16)
        self._stop = threading.Event()
        self.port = int(self._sock.getsockname()[1])
        self.base = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _addr = self._sock.accept()
            except OSError:
                return
            self.hits.append(time.monotonic())
            try:
                self._handle(conn)
            finally:
                conn.close()

    def _handle(self, conn: socket.socket) -> None:
        if self._serve_after is None or len(self.hits) <= self._serve_after:
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            return
        # ★ 必须把请求体也读完再回包。只读到 `\r\n\r\n` 就收工的话，body 还留在
        # socket 里，Windows 上带着未读数据 close 会发 RST —— 客户端有时先撞 RST，
        # 读不到这条 401，于是「第一次 RST、第二次该成功」的用例整文件跑时才红
        # （实测：单跑绿、整文件红，就是这么来的）。
        conn.settimeout(5.0)
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = conn.recv(65536)
            if not chunk:
                break
            buf += chunk
        head_raw, _, rest = buf.partition(b"\r\n\r\n")
        want = 0
        for line in head_raw.split(b"\r\n")[1:]:
            name, _, value = line.partition(b":")
            if name.strip().lower() == b"content-length":
                want = int(value.strip() or 0)
        while len(rest) < want:
            chunk = conn.recv(65536)
            if not chunk:
                break
            rest += chunk
        body = json.dumps({"detail": "没配对码，传不进来"}).encode("utf-8")
        head = (
            b"HTTP/1.1 401 Unauthorized\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            b"Connection: close\r\n\r\n"
        )
        conn.sendall(head + body)
        # 半关写端：客户端读满 body 就会收到干净的 FIN，不会撞 RST。
        with contextlib.suppress(OSError):
            conn.shutdown(socket.SHUT_WR)

    def close(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        finally:
            self._sock = None  # type: ignore[assignment]
        self._thread.join(timeout=10)


def _refused_base() -> str:
    """挑一个「一定没人听」的回环端口：绑上再立刻关。"""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}"


# ==================================================== ① 真的没送到 ⇒ 仍是 (0, None)


@pytest.mark.parametrize("retry", [None, "0", "3"])
def test_refused_connection_is_still_zero_and_none(monkeypatch, retry):
    """★ 判据 1 反例：拒连 = 请求根本没送到 ⇒ `(0, None)`，**不许**变成抛错。

    三个重试档位都验一遍：把拒连也算成「没读到」会让这条路径随重试次数抖动。
    """
    if retry is None:
        monkeypatch.delenv(wlc.LAN_RETRY_ENV, raising=False)
    else:
        monkeypatch.setenv(wlc.LAN_RETRY_ENV, retry)
    assert wlc._lan_json(_refused_base(), "/api/health") == (0, None)


# ==================================================== ② 连上了但没读到 ⇒ 点名抛错


def test_reset_connection_is_named_not_swallowed(monkeypatch):
    """★ 判据 1 主钉子：对端 RST ⇒ `LiveCallError`，`.kind` 是原始异常名，`.broken_read` 为真。"""
    monkeypatch.delenv(wlc.CALL_TIMEOUT_ENV, raising=False)
    srv = _RstServer()
    try:
        with pytest.raises(wlc.LiveCallError) as ei:
            wlc._lan_json(srv.base, "/api/sync/import", "POST", {"pack": {"v": 1}})
    finally:
        srv.close()
    msg = str(ei.value)
    assert ei.value.kind == "ConnectionResetError", f"类名丢了：{ei.value.kind!r}"
    assert ei.value.broken_read is True, "没标出这是「没读到响应」"
    assert "POST" in msg and "/api/sync/import" in msg, f"没点名：{msg}"
    assert "401" in msg, f"没说清这不是 401 的问题：{msg}"
    assert srv.hits, "服务端一条连接都没收到 —— 这场测的不是「连上了」"


def test_lan_retry_defaults_to_one_and_is_env_tunable(monkeypatch):
    """★ 判据 2：重试次数默认 1、env 可调、`0` 合法、坏值退回默认。"""
    monkeypatch.delenv(wlc.LAN_RETRY_ENV, raising=False)
    assert wlc.lan_retry() == 1
    monkeypatch.setenv(wlc.LAN_RETRY_ENV, "0")
    assert wlc.lan_retry() == 0
    monkeypatch.setenv(wlc.LAN_RETRY_ENV, "3")
    assert wlc.lan_retry() == 3
    for bad in ("abc", "-1", ""):
        monkeypatch.setenv(wlc.LAN_RETRY_ENV, bad)
        assert wlc.lan_retry() == 1, f"坏值 {bad!r} 没退回默认"


def test_reset_then_success_only_retries_once(monkeypatch):
    """★ 判据 2 主钉子：第一次 RST、第二次回 401 ⇒ 返回 401，且**只**重试了 1 次。"""
    monkeypatch.delenv(wlc.LAN_RETRY_ENV, raising=False)
    srv = _RstServer(serve_after=1)
    try:
        code, _body = wlc._lan_json(srv.base, "/api/sync/import", "POST", {"pack": {"v": 1}})
    finally:
        srv.close()
    assert code == 401, f"重试后仍没读到 401：{code!r}"
    assert len(srv.hits) == 2, f"请求次数不是 2（1 次原打 + 1 次重试）：{len(srv.hits)}"


def test_retry_zero_means_no_second_request(monkeypatch):
    """★ 判据 2：`TF_WEB_LIVE_RETRY=0` ⇒ 不重试，直接抛，服务端只该收到 1 条连接。"""
    monkeypatch.setenv(wlc.LAN_RETRY_ENV, "0")
    srv = _RstServer()
    try:
        with pytest.raises(wlc.LiveCallError) as ei:
            wlc._lan_json(srv.base, "/api/sync/import", "POST", {"pack": {"v": 1}})
    finally:
        srv.close()
    assert ei.value.broken_read is True
    assert len(srv.hits) == 1, f"关了重试还打了 {len(srv.hits)} 次"


# ==================================================== ④ 已拿到状态码 ⇒ 绝不重试


class _Count401(BaseHTTPRequestHandler):
    """真 HTTP 服务：永远回 401，并记下被请求了几次。"""

    hits: list[str] = []

    def do_POST(self) -> None:  # noqa: N802 —— BaseHTTPRequestHandler 的约定名
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        type(self).hits.append(self.path)
        body = json.dumps({"detail": "没配对码"}).encode("utf-8")
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_a):
        return


@pytest.fixture
def count_401_server():
    _Count401.hits = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Count401)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=10)


def test_a_status_code_is_never_retried(count_401_server, monkeypatch):
    """★ 判据 2 反例：服务端回了 401 ⇒ 一次就收工，**不许**重试（那会掩盖真错）。"""
    monkeypatch.setenv(wlc.LAN_RETRY_ENV, "3")
    code, _body = wlc._lan_json(count_401_server, "/api/sync/import", "POST", {"pack": {"v": 1}})
    assert code == 401
    assert len(_Count401.hits) == 1, f"拿到 401 之后又打了 {len(_Count401.hits) - 1} 次"


# ==================================================== ⑤ 收口：一条不许丢、也不许甩锅 401


def _install_fake_lan_env(monkeypatch, lan_json, pack_path: Path):
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
    monkeypatch.setattr(lan_mod, "local_addresses", lambda port=0: ["http://10.0.0.9:8531"])
    monkeypatch.setattr(wlc, "_lan_json", lan_json)
    monkeypatch.setattr(wlc, "_json_call", _json_call)
    monkeypatch.setattr(wlc, "_phone_pack", lambda *_a, **_kw: pack_path)


def test_import_read_failure_is_reported_as_read_failure(tmp_path, monkeypatch, capsys):
    """★ 判据 5 主钉子：传包那步「没读到响应」⇒ 已算出的 checks 全留 + 点名 False，
    而且**不出现**把责任推给 401 的那一条（那正是云机门报出误导结论的地方）。
    """
    pack = tmp_path / "phone-lan.json"
    pack.write_text(json.dumps({"v": 1}), encoding="utf-8")

    def lan_json(base, path, method="GET", payload=None, headers=None, timeout=None):
        if path == "/api/sync/import":
            wait = wlc.call_timeout() if timeout is None else timeout
            raise wlc.LiveCallError(
                method, f"{base}{path}", wait, ConnectionResetError("reset"), broken_read=True
            )
        if path == "/api/health":
            if headers is None:
                return 401, {"detail": "要配对码"}
            return 200, {"ok": True}
        if path == "/api/lan/pair":
            return (401, None) if (payload or {}).get("code") == "000000" else (200, None)
        if path == "/api/settings/lan":
            return 200, {"code": ""}
        return 200, None

    _install_fake_lan_env(monkeypatch, lan_json, pack)
    monkeypatch.delenv(wlc.CALL_TIMEOUT_ENV, raising=False)

    checks = wlc.live_lan_checks(tmp_path)

    assert checks["局域网：静态壳能打开（否则手机没处输配对码）"] is True, "已算出的那条被丢了"
    assert checks["局域网：配对后能读数据"] is True, "已算出的那条被丢了"
    false_rows = [k for k, v in checks.items() if v is False]
    assert len(false_rows) == 1, f"不该多出别的 False：{checks}"
    assert false_rows[0].startswith("局域网：有一步没等到（POST ")
    assert "/api/sync/import" in false_rows[0]
    assert not any(k.startswith("手机直传") for k in checks), (
        f"读不到响应却报成了「手机直传」判据失败（甩锅 401）：{list(checks)}"
    )
    assert "[FAIL]" in capsys.readouterr().out

# ==================================================== ⑥ 判据本身不许被放宽

def test_the_401_judgement_is_not_relaxed():
    """★ 判据 3：门里那条 `nopair[0] == 401` 必须原样留着。

    这条是本卡最容易被"顺手放宽"的地方——把 `== 401` 改成 `in (401, 0)` 就能让
    云机那趟变绿，但那等于承认"没读到响应也算服务端拒了"，门从此不再证明配对门有效。
    """
    src = (TOOLS / "web_live_check.py").read_text(encoding="utf-8")
    judge = [ln.strip() for ln in src.splitlines() if "没配对传不进来" in ln and "checks[" in ln]
    assert len(judge) == 1, f"判据行不是 1 条：{judge}"
    assert judge[0].endswith("= nopair[0] == 401"), f"判据被改宽了：{judge[0]}"
