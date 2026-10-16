r"""卡 250 判据 —— 挑端口用「能不能 bind」+ 接入前**验明正身**（T-G371）。

## 为什么有它（复盘/DSH插件-定点深读.md §四.3，照 dsh-pilot 抄的两条做法）

挑端口靠「HTTP 探测超时」会骗人：端口被**非 HTTP** 的东西占着（裸 socket）⇒ 探测超时 ⇒
误判「空闲」✗；端口上是**别的 HTTP 服务** ⇒ 探测成功 ⇒ 误判「我们的服务活着」✗。
判据（对应卡 §3）：

- a. **裸 socket 占口** ⇒ 挑端口必须**报忙并顺延**（bind 探测，不许靠 HTTP 超时当空闲）；
  ★ 反例：把 bind 探测换成 HTTP 探测 ⇒ 本文件当场红（`test_bare_socket_*`）。
- b. **冒充者**（别的 HTTP 服务返回 200 但指纹不对）⇒ 判活必须给「**验明失败**」
  且错误信息带下一步排查命令；★ 反例：把指纹判活换成「任意 200 = 活」⇒ 当场红。
- c. **自己的服务** ⇒ 判活「活着」+ 指纹对。
- d. 既有判据不删不降级：`serve.py` 此前没有判据文件（本文件是第一份），
  但 `test_no_window.py` 等既有钉子必须保绿（收工时另行真跑）。

★ 测试不起子进程（裸 socket / 假 HTTP 服务都在本进程内起线程）—— 避开 NO_WINDOW 判据域。
"""

from __future__ import annotations

import http.server
import inspect
import json
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import serve  # noqa: E402 —— tools/ 不是包，靠 sys.path 直入

from timeflow.api.app import create_app  # noqa: E402 —— 本树 src（conftest 已前置）

# ---------------------------------------------------------------- 造现场的零件


def _free_port() -> int:
    """拿一个当前空闲的端口（bind 后立刻还掉；测试窗口内被抢的概率可忽略）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _BareSocket:
    """只 listen 不说话的裸 socket（非 HTTP）—— 占住一个端口，制造「探测超时」陷阱。"""

    def __init__(self) -> None:
        self.sock: socket.socket | None = None
        self.port = 0

    def __enter__(self) -> _BareSocket:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        s.listen(1)  # 永不 accept、永不回话
        self.sock = s
        self.port = int(s.getsockname()[1])
        return self

    def __exit__(self, *exc: object) -> None:
        assert self.sock is not None
        self.sock.close()


class _Impostor(http.server.BaseHTTPRequestHandler):
    """冒充者：是 HTTP、返回 200，但**不是**本项目的服务（/api/health 指纹对不上）。"""

    def do_GET(self) -> None:  # noqa: N802 —— http.server 的命名
        body = json.dumps({"hello": "world", "note": "我是别的服务"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:  # 静音，别刷测试输出
        pass


class _FakeService:
    """在端口上起一个假 HTTP 服务（`handler` 是 http.server 的 handler 类）。"""

    def __init__(self, handler: type[http.server.BaseHTTPRequestHandler]) -> None:
        self.handler = handler
        self.httpd: http.server.ThreadingHTTPServer | None = None
        self.port = 0

    def __enter__(self) -> _FakeService:
        # 先占一个空位再让 handler 绑上去：直接绑 0 端口，由系统分
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), self.handler)
        self.port = int(self.httpd.server_address[1])
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc: object) -> None:
        assert self.httpd is not None
        self.httpd.shutdown()
        self.httpd.server_close()


def _own_service() -> tuple[Any, int]:
    """起**本项目真实服务**（临时空库），返回 (uvicorn server, port)。"""
    import uvicorn

    db = Path(tempfile.mkdtemp(prefix="tf-serve-port-")) / "timeflow.db"
    app = create_app(str(db))
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    return server, port


def _stop_own(server: Any) -> None:
    server.should_exit = True
    time.sleep(0.3)  # 给 uvicorn 一口气退出、还掉端口（daemon 线程，进程结束兜底）


# ---------------------------------------------------------------- a. 占用时的行为


def test_bare_socket_is_busy_and_pick_moves_on() -> None:
    """★ a：裸 socket 占口 ⇒ 挑端口必须报忙并**顺延**到下一个候选。

    反例性质：HTTP 探测对裸 socket 只会超时 ⇒ 误判「空闲」⇒ 本断言当场红。
    """
    with _BareSocket() as busy:
        port, tried = serve.pick_port(busy.port, "127.0.0.1", tries=5)
    assert port is not None, "全判忙 —— 连空口都没挑到（探测把一切都当忙了？）"
    assert port != busy.port, (
        f"把被裸 socket 占住的 {busy.port} 当成了空闲 —— 这正是 HTTP 探测超时的假空闲"
    )
    assert busy.port in tried, f"试过的端口要原样记账：tried={tried}"


def test_all_candidates_busy_returns_none_and_lists_tried() -> None:
    """★ a2：全试完仍不行 ⇒ 返回 None + **试过哪些端口原样**（main 拿它非零退出并打印）。"""
    with _BareSocket() as busy:
        port, tried = serve.pick_port(busy.port, "127.0.0.1", tries=1)
    assert port is None, "唯一候选被占着却挑中了它"
    assert tried == [busy.port], f"试过的端口要原样记账：{tried}"


def test_pick_probe_is_bind_not_http() -> None:
    """★ a 反例钉（结构）：探测必须真 `bind`，不许是 HTTP 探测（否则 a 的行为判据会红）。"""
    src = inspect.getsource(serve.can_bind)
    assert ".bind(" in src, "挑端口探测里没有 bind() —— 这不是 bind 探测"
    assert "urlopen" not in src and "urllib" not in src, "探测里混进了 HTTP —— 那是会骗人的旧法"


# ---------------------------------------------------------------- b. 冒充者


def test_impersonator_is_rejected_with_next_command() -> None:
    """★ b：冒充者（200 但指纹不对）⇒ 判「验明失败」+ 下一步排查命令，**不许判「活着」**。"""
    with _FakeService(_Impostor) as fake:
        ok, msg = serve.check_alive(f"http://127.0.0.1:{fake.port}", timeout=2.0)
    assert ok is False, "别的 HTTP 服务也被判成「活着」—— 这就是今天咬过人的误判"
    assert "验明失败" in msg, f"要判「验明失败」，实际输出：{msg}"
    assert "下一步" in msg, f"错误要带下一步排查命令（错误即修复指令），实际输出：{msg}"
    assert "netstat" in msg, f"下一步里要有看谁占端口的命令（netstat），实际输出：{msg}"


def test_no_response_is_judged_not_started() -> None:
    """★ b2：端口**根本没有响应** ⇒ 才判「没起」（与「验明失败」分开，别混）。"""
    port = _free_port()  # 已还掉，没人听
    ok, msg = serve.check_alive(f"http://127.0.0.1:{port}", timeout=2.0)
    assert ok is False
    assert "没起" in msg, f"没响应要判「没起」，实际输出：{msg}"
    assert "验明失败" not in msg, "没响应不许报「验明失败」—— 两种失败要分得开"


# ---------------------------------------------------------------- c. 自己的服务


def test_own_service_alive_with_matching_fingerprint() -> None:
    """★ c：自己正常起 ⇒ 判活「活着」+ 指纹对（真起本项目服务，不是假桩）。"""
    server, port = _own_service()
    try:
        ok, msg = serve.wait_alive(f"http://127.0.0.1:{port}", timeout=15.0)
        assert ok is True, f"本项目服务被判活失败：{msg}"
        assert "活着" in msg, f"判活输出要明说「活着」：{msg}"
    finally:
        _stop_own(server)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q", "--no-cov"]))
