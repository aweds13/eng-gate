"""卡 E73 钉子（判据 5 的六条）：两条门不许抢同一个端口。

★★ 病灶原文（2026-10-31 实测，`.wt/F12`）：`tests/test_only_selector_parity.py` 的
`run_render()` 一个 `--port` 都不传 ⇒ 落到 `tools/render_check.mjs` 的**默认值** 8531；
`pytest -n 2` 并行时，后起的那个 `waitHealth()` 立刻通（前一个已经把服务拉起来了），
于是它往**别人的**服务里重复 seed ⇒ `POST /api/groups {name:'高数'}` 得 400
⇒「fixture（种子数据）没造全」⇒ **假红**，但红得像真的。

六条钉子各钉一处：
  1. `portBase()` 跟着 `TF_GATE_PORT_BASE` 走（不设 = 8531）
  2. 非整数 ⇒ 退 8531 且 **stderr 有话说**（不静默吞）
  3. 两个工具里**没有**可执行的 `port: 8531` / `port: 8541` 默认字面量
  4. 端口被占 ⇒ 点名 + 非零退出 + **一次 `POST /api/groups` 都不发**
  5. `tests/test_only_selector_parity.py::run_render()` 必须显式传 `--port`
  6. 真起两条：同端口必须红（反证）／不同端口必须都绿
"""

from __future__ import annotations

import ast
import contextlib
import os
import shutil
import socket
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RENDER = ROOT / "tools" / "render_check.mjs"
FLOW = ROOT / "tools" / "ui_flow_check.mjs"
LIB = ROOT / "tools" / "tf_browser.mjs"
PARITY = ROOT / "tests" / "test_only_selector_parity.py"
NODE = shutil.which("node")
#: 别的钉子会 `import run_gates`；`scripts/` 不在 `sys.path` 上（conftest 只插 `src`）。
sys.path.insert(0, str(ROOT / "scripts"))

pytestmark = pytest.mark.skipif(NODE is None, reason="环境里没有 node（这几条钉子本来就跑不了）")


# ---------------------------------------------------------------- 小工具


def _base() -> int:
    """本树门禁端口段的基准（与 `scripts/run_gates.py::port_base()` 同源）。"""
    return int(os.environ.get("TF_GATE_PORT_BASE", "8531"))


def _node_env(**over: str) -> dict[str, str]:
    """`os.environ` 去掉 `TF_GATE_PORT_BASE` 再按需设置 —— 「不设」这个态必须真不设。"""
    env = {k: v for k, v in os.environ.items() if k != "TF_GATE_PORT_BASE"}
    env.update({k: v for k, v in over.items() if v is not None})
    return env


def _node_eval(code: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    assert NODE is not None
    return subprocess.run(
        [NODE, "--input-type=module", "-e", code],
        cwd=ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False,
    )


_PORT_BASE_JS = (
    "import { portBase } from './tools/tf_browser.mjs';"
    " console.log('port=' + portBase())"
)


def _port_base_of(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return _node_eval(_PORT_BASE_JS, env)


def _run_render(*args: str, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    assert NODE is not None
    return subprocess.run(
        [NODE, str(RENDER), *args], cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False, timeout=timeout,
    )


def _run_flow(*args: str, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    assert NODE is not None
    return subprocess.run(
        [NODE, str(FLOW), *args], cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False, timeout=timeout,
    )


def _port_free(port: int, host: str = "127.0.0.1") -> bool:
    """能不能 bind 上（照 `tools/serve.py::can_bind`：bind 不说谎，HTTP 探测会）。"""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _free_port(start: int | None = None, need: tuple[int, ...] = (0,)) -> int:
    """从 `start` 起找一段空端口：`port + d` 对每个 `d in need` 都空着。

    `need` 里写偏移：`render_check.mjs` 用 `port` 与 `port+1`（CDP），两条并行还得错开，所以这里的
    调用方传 `(0, 1)` 或 `(0, 1, 3, 4)` —— 免得两条命令抢上 CDP 端口，红得跟本卡无关。
    """
    base = _base() + 300 if start is None else start
    for port in range(base, base + 500):
        if all(_port_free(port + d) for d in need):
            return port
    raise AssertionError(f"从 {base} 起找不到空端口（need={need}）")


def _wait_listening(port: int, timeout: float = 90.0) -> bool:
    """等**真的有人在这个端口上听**（不是等它跑完）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _port_free(port):
            return True
        time.sleep(0.2)
    return False


def _strip_comments(text: str) -> str:
    """去掉 `//` 行注释与 `/* … */` 块注释 —— 判据是「**可执行的**默认值里不许有字面量」。"""
    out = []
    in_block = False
    for line in text.splitlines():
        if in_block:
            if "*/" in line:
                in_block = False
                line = line.split("*/", 1)[1]
            else:
                continue
        while "/*" in line:
            head, rest = line.split("/*", 1)
            if "*/" in rest:
                line = head + rest.split("*/", 1)[1]
            else:
                line = head
                in_block = True
                break
        out.append(line.split("//", 1)[0])
    return "\n".join(out)


class _Recorder(socketserver.BaseRequestHandler):
    """占住端口，并把每一条请求**原样记下来**（判据 3：一次 `POST /api/groups` 都不许发）。"""

    hits: list[bytes] = []

    def handle(self) -> None:
        try:
            data = self.request.recv(8192)
        except OSError:
            data = b""
        type(self).hits.append(data)
        with contextlib.suppress(OSError):
            self.request.sendall(
                b"HTTP/1.1 400 Bad Request\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}"
            )


# ---------------------------------------------------------------- 1


def test_default_port_follows_gate_base_env() -> None:
    """设了 `TF_GATE_PORT_BASE=9111` ⇒ `portBase()` 回 9111；不设 ⇒ 8531。"""
    off = _port_base_of(_node_env())
    assert off.returncode == 0, off.stderr
    assert off.stdout.strip() == "port=8531", (
        f"不设 TF_GATE_PORT_BASE 应回 8531，实得 {off.stdout!r}"
    )

    on = _port_base_of(_node_env(TF_GATE_PORT_BASE="9111"))
    assert on.returncode == 0, on.stderr
    assert on.stdout.strip() == "port=9111", (
        f"TF_GATE_PORT_BASE=9111 应回 9111，实得 {on.stdout!r} —— 默认端口没跟着门禁段走"
    )


# ---------------------------------------------------------------- 2


def test_bad_port_base_env_warns_and_falls_back() -> None:
    """`TF_GATE_PORT_BASE=abc` ⇒ 8531 **且 stderr 说一句**（不静默退回）。"""
    proc = _port_base_of(_node_env(TF_GATE_PORT_BASE="abc"))
    assert proc.stdout.strip() == "port=8531", f"非整数应退回 8531，实得 {proc.stdout!r}"
    assert proc.stderr.strip(), "非整数退回默认时**必须**在 stderr 说一句，实际一个字都没说"
    assert "TF_GATE_PORT_BASE" in proc.stderr, f"stderr 里得点名是哪个变量：{proc.stderr!r}"


# ---------------------------------------------------------------- 3


def test_no_hardcoded_default_port_left() -> None:
    """两个工具里**没有**可执行的 `port: 8531` / `port: 8541`（注释行先去掉）。"""
    for path, want in ((RENDER, "port: portBase()"), (FLOW, "port: portBase() + 10")):
        raw = path.read_text(encoding="utf-8", errors="replace")
        code = _strip_comments(raw)
        for lit in ("port: 8531", "port: 8541"):
            assert lit not in code, f"{path.name} 里还有可执行的默认字面量 `{lit}`"
        # 反面控制：不许靠「删掉那行」让上面两条空过。
        assert want in code, f"{path.name} 的默认端口应当是 `{want}`"


# ---------------------------------------------------------------- 4


def test_busy_port_is_refused_not_seeded() -> None:
    """端口先被占着 ⇒ 点名 + 非零退出 + **一次 `POST /api/groups` 都不发**。"""
    port = _free_port(need=(0, 1))
    _Recorder.hits = []
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", port), _Recorder)
    srv.daemon_threads = True
    th = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    th.start()
    try:
        proc = _run_render("--only", "today", "--port", str(port))
        out = proc.stdout + proc.stderr
        assert proc.returncode != 0, f"端口 {port} 被占着居然退 0：{out[-800:]}"
        assert f"端口 {port} 已被占用" in out, f"没有点名端口 {port}：{out[-800:]}"
        assert "fixture（种子数据）没造全" not in out, f"它还是去 seed 别人的服务了：{out[-800:]}"
        posts = [b for b in _Recorder.hits if b"POST" in b]
        assert not posts, f"端口被占时**不许**发 POST，实际发了：{[p[:120] for p in posts]}"
        assert not [b for b in _Recorder.hits if b"/api/groups" in b], (
            f"端口被占时碰了别人的 `/api/groups`：{[b[:120] for b in _Recorder.hits]}"
        )
    finally:
        srv.shutdown()
        srv.server_close()


# ---------------------------------------------------------------- 5


def test_parity_test_passes_an_explicit_port() -> None:
    """`tests/test_only_selector_parity.py::run_render()` 的命令行里必须含 `"--port"`。"""
    src = PARITY.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "run_render" in funcs, "run_render 不见了 —— 那时的钉子已经不钉在真东西上"
    body = ast.get_source_segment(src, funcs["run_render"]) or ""
    assert '"--port"' in body or "'--port'" in body, (
        "run_render 的命令行里没有 --port —— 它会落回默认端口，这正是卡 E73 的病灶"
    )
    assert "_test_port" in funcs, "缺模块级 `_test_port()`（判据 4 要求端口取法可被钉子直接调）"
    port_src = ast.get_source_segment(src, funcs["_test_port"]) or ""
    assert "TF_GATE_PORT_BASE" in port_src, f"_test_port() 没跟门禁段同源：{port_src}"
    assert "200" in port_src, f"_test_port() 的 +200 偏移不见了：{port_src}"


# ---------------------------------------------------------------- 6


def test_two_runs_at_once_do_not_collide() -> None:
    """真起两条：**同一个** `--port` 必须红（反证），**各自不同** `--port` 必须都绿。

    ★ 反证怎么做得**确定**：不等「第一条跑完」（那是另一回事），只等它「真的在听」——
      这正是 2026-10-31 病灶的形状（前一个已把服务拉起来，后起的那条 `waitHealth()` 立刻通）。
      两条同时探测会有「都探到空」的竞态窗口，红不红取决于谁先 bind —— 那不叫钉子。
    """
    assert NODE is not None
    # ---- 反证：同一个端口，第二条必须被拒
    port = _free_port(need=(0, 1))
    first = subprocess.Popen(
        [NODE, str(RENDER), "--only", "today", "--port", str(port)],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    try:
        assert _wait_listening(port), f"第一条 90 秒内没在这个端口上听起来（{port}）"
        second = _run_render("--only", "today", "--port", str(port))
        out2 = second.stdout + second.stderr
        assert second.returncode != 0, (
            f"同一个端口 {port} 已经有人在听，第二节居然退 0：{out2[-800:]}"
        )
        assert f"端口 {port} 已被占用" in out2, f"第二条没点名端口 {port}：{out2[-800:]}"
    finally:
        first.communicate(timeout=300)

    # ---- 正路：各自不同端口，两条都绿
    p1 = _free_port(need=(0, 1, 3, 4))
    p2 = p1 + 3
    procs = [
        subprocess.Popen(
            [NODE, str(RENDER), "--only", "today", "--port", str(p)],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        for p in (p1, p2)
    ]
    outs = [pr.communicate(timeout=600)[0] or "" for pr in procs]
    codes = [pr.returncode for pr in procs]
    assert codes == [0, 0], (
        f"两条各自 {p1} / {p2} 并行居然有红的：{codes}\n第一条末段：{outs[0][-600:]}"
        f"\n第二条末段：{outs[1][-600:]}"
    )
    for out in outs:
        assert "分组「高数」已存在" not in out, f"并行又踩上了：{out[-600:]}"
