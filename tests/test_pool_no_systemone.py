r"""决策模型与 `/v1/systemone` **不移植**的钉子（卡 A381 · T-AG669）。

## 病

magpie 有一整套「决策模型」设施：一条自己的端点 `POST /v1/systemone`、一类只做决定的模型
与只装它们的路由组、一个拿 decision 模型判「这句话是哪个 intent / 这一轮多难」的 classifier
宿主。本仓**一条都没有**，而且**不该有**：

- 端点撞两条明文边界 —— `tools/pool/gateway.py` 模块头的「**不做协议翻译**」（System One 的
  body 不是对话，是「问题 + 候选答案 + 概率」）与「**四条路径，一个都不多**」；
- decision 组与 classifier 缺**输入** —— 仓外账本 / 平台表 / 模型注册表里一个 decision 号
  都没有，本仓路由也只有排序（`tools/pool/route.py` 的 `apply_strategy`），没有 rules /
  intent / effort auto 这套东西。

决定写在 `docs/decisions/0011-no-systemone.md`，同一句话投影到 `docs/subsystems/pool/模型与号池.md`
§9 与 `docs/subsystems/pool/README.md` 表 B。这里钉的是「今天确实没有」—— 哪天有人要接，
先推翻那份 ADR，再把这几条钉子一起改。

## 判据判什么

| 钉子 | 钉哪一位 |
|---|---|
| `test_systemone_endpoint_is_404` | 真服务 404 + `not_found_error`，文案只点四条 |
| `test_systemone_endpoint_is_404_without_bearer` | ★ 不带 Bearer 也是 404（先查 `PATHS` 后鉴权）|
| `test_decide_endpoint_is_404` | 同族端点 `POST /v1/decide` 也 404 |
| `test_gateway_source_has_no_decision_literal` | 源码：没有 `systemone` / `decide_group` |
| `test_paths_are_exactly_four` | `tuple(PATHS)` 精确等于四元组；`_Server` 无 system / decide |
| `test_production_code_has_zero_hits` | 扫描：`tools/` + `scripts/` 的生产码四形状零命中 |
| `test_adr_exists_and_passes_machine_check` | ADR 存在 + 文件名合规 + 四节齐全 |
| `test_decision_is_written_in_tracked_docs` | tracked 文档写着它；生成器仍退 0 |

## 为什么零命中扫描只到生产码

扫描范围写死为 `tools/` 与 `scripts/` 下的 `*.py`（**不含** `tests/`、不含 `docs/`、
不含 `__pycache__`）。理由只有一条：**本卡自己的产物必须写出 systemone 才说得清这个决定** ——
这份测试文件、`docs/decisions/0011-no-systemone.md`、`模型与号池.md` 的新节、README 表 B 的
新行，全都得点它的名（`test_decision_is_written_in_tracked_docs` 反过来断言它们**确实写了**）。
把 `docs/` 或 `tests/` 也纳入零命中扫描，就是自己咬自己。这条边界是**判据本身**
（生产码里一个都不许有），不是一份可以随时加长的跳过名单。

★ 两个必避的假阳性（实测，不是猜的）：裸词 `jev` 会命中云机 instance-id
`i-0123456789abcdef0`，所以只扫 `jev-latest` 与 `gptload-jev`；裸词 `intent` 会命中
`scripts/check_layers.py` 里的 `intention`（五层对齐），所以用词边界 `\bintent\b`。
另有：不加 `--include` 时 `__pycache__/*.pyc` 的字节会让 `decider` 假命中 —— 这里逐文件读
`.py` 源码，天然避开。
"""

from __future__ import annotations

import http.client
import importlib.util
import json
import re
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from pool import gateway  # noqa: E402 —— tools/ 已挂上 sys.path
from pool.no_window import NO_WINDOW  # noqa: E402 —— 起子进程必须带（卡 148）

TOKEN = "no-systemone-token"
ADR = ROOT / "docs" / "decisions" / "0011-no-systemone.md"
POOL_DOC = ROOT / "docs" / "subsystems" / "pool" / "模型与号池.md"
POOL_README = ROOT / "docs" / "subsystems" / "pool" / "README.md"

#: 网关的四条路径 —— 一个不多、一个不少（判据 2 的精确比对项）。
FOUR_PATHS = (
    "/v1/chat/completions",
    "/v1/messages",
    "/v1/models",
    "/v1/pool/routes",
)

#: 生产码零命中扫描的形状（判据 3）。第一个元素只是人读的标签。
HIT_PATTERNS = (
    ("systemone（大小写不敏感）", re.compile(r"systemone", re.I)),
    ("jev-latest", re.compile(r"jev-latest")),
    ("gptload-jev", re.compile(r"gptload-jev")),
    ("decision-model-preview", re.compile(r"decision-model-preview")),
    ("词边界 intent", re.compile(r"\bintent\b")),
)


# ------------------------------------------------ 夹具（自带，不 import 别的测试文件）
@pytest.fixture()
def start_server(tmp_path):
    """起一个真网关（`port=0` 让系统给端口），收尾一定关掉。"""
    started: list[tuple[object, threading.Thread]] = []

    def _start() -> int:
        server = gateway.build_server(
            host="127.0.0.1", port=0, token=TOKEN, root=tmp_path
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        started.append((server, thread))
        return int(server.server_address[1])

    yield _start
    for server, thread in started:
        server.shutdown()
        server.server_close()
        thread.join(5)


def _request(port: int, method: str, path: str, *, body: object = None,
             token: str | None = TOKEN) -> tuple[int, bytes]:
    """发一条真 HTTP 请求，回（状态码, 原始 body）。"""
    payload = b""
    headers = {"Content-Type": "application/json"}
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10.0)
    try:
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


def _not_found_message(raw: bytes) -> str:
    """把 404 的 body 解成 `error.message`（形状不对就让它炸，别静默跳过）。"""
    payload = json.loads(raw.decode("utf-8"))
    assert payload["error"]["type"] == "not_found_error", payload
    message = payload["error"]["message"]
    assert isinstance(message, str) and message
    return message


def _text(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


# ---------------------------------------------------------------- 判据 1：真服务上 404
def test_systemone_endpoint_is_404(start_server):
    """带 Bearer 的 `POST /v1/systemone` ⇒ 404，文案只点四条，不点名 magpie。"""
    port = start_server()
    status, raw = _request(port, "POST", "/v1/systemone", body={"model": "group/x"})
    assert status == 404, status
    message = _not_found_message(raw)

    assert "只有四条" in message, message
    for path in FOUR_PATHS:
        assert path in message, f"文案里少了 {path}：{message}"
    # 文案里可以回显**调用方自己写的**路径，但不许把 systemone 当成一条可用路径再点一次，
    # 也不许提 magpie —— 那等于给调用方指路。
    assert '"systemone"' not in message, message
    assert "magpie" not in message.lower(), message


def test_systemone_endpoint_is_404_without_bearer(start_server):
    """★ 不带 Bearer 也必须是 404（不是 401）：`_dispatch` 先查 `PATHS` 后鉴权。"""
    port = start_server()
    status, raw = _request(port, "POST", "/v1/systemone", body={"model": "group/x"},
                           token=None)
    assert status == 404, f"不带 Bearer 的拼错路径回到了 {status}（次序被打乱了？）"
    assert status != 401
    message = _not_found_message(raw)
    assert "只有四条" in message, message


def test_decide_endpoint_is_404(start_server):
    """同族的 `POST /v1/decide` 也 404（一个都不多，不是只关了一扇门）。"""
    port = start_server()
    status, raw = _request(port, "POST", "/v1/decide", body={"model": "group/x"})
    assert status == 404, status
    message = _not_found_message(raw)
    assert "只有四条" in message, message
    assert "magpie" not in message.lower(), message


# ---------------------------------------------------------------- 判据 2：源码 / 结构钉
def test_gateway_source_has_no_decision_literal():
    """`gateway.py` 里没有 `systemone` / `decide_group` 字面 —— 只加常量不接线也会红。"""
    source = (ROOT / "tools" / "pool" / "gateway.py").read_text(encoding="utf-8")
    assert "systemone" not in source.lower()
    assert "decide_group" not in source


def test_paths_are_exactly_four():
    """`PATHS` 精确等于四元组；服务类上没有任何 system / decide 方法。"""
    assert tuple(gateway.PATHS) == FOUR_PATHS
    extra = [n for n in dir(gateway._Server) if "system" in n.lower() or "decide" in n.lower()]
    assert extra == [], extra


# ---------------------------------------------------------------- 判据 3：生产码零命中扫描
def test_production_code_has_zero_hits():
    """`tools/` + `scripts/` 的生产码四形状零命中（范围见模块 docstring）。"""
    files = sorted(
        path
        for top in ("tools", "scripts")
        for path in (ROOT / top).rglob("*.py")
        if "__pycache__" not in path.parts
    )
    assert files, "扫描范围一个文件都没扫到 —— 判据空转"

    hits: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for label, pattern in HIT_PATTERNS:
            if pattern.search(text):
                hits.append(f"{path.relative_to(ROOT).as_posix()}：{label}")
    assert hits == [], "生产码里出现了决策模型相关字面：\n" + "\n".join(hits)


# ---------------------------------------------------------------- 判据 4：ADR
def test_adr_exists_and_passes_machine_check():
    """ADR 存在、文件名合规、四节齐全、头信息非空，且过真检查器。"""
    assert ADR.is_file(), ADR
    assert re.match(r"^([0-9]{4})-([a-z0-9]+(?:-[a-z0-9]+)*)\.md$", ADR.name), ADR.name

    text = _text(ADR)
    for section in ("## 背景与问题", "## 候选方案", "## 决定", "## 把握程度"):
        assert section in text, f"ADR 缺段落 {section}"
    assert re.search(r"(?m)^Status:[ \t]*(\S.*)$", text), "ADR 缺 Status"
    assert re.search(r"(?m)^来源:[ \t]*(\S.*)$", text), "ADR 缺 来源"

    spec = importlib.util.spec_from_file_location(
        "check_docs_381", ROOT / "scripts" / "check_docs.py"
    )
    assert spec is not None and spec.loader is not None
    cd = importlib.util.module_from_spec(spec)
    # 必须先登记进 sys.modules：check_docs 里有 dataclass，exec_module 时
    # dataclasses 会按 cls.__module__ 反查模块，没登记就 AttributeError。
    sys.modules[spec.name] = cd
    spec.loader.exec_module(cd)
    assert cd.check(ROOT).problems == []


# ---------------------------------------------------------------- 判据 5：决定写在 tracked 文档里
def test_decision_is_written_in_tracked_docs():
    """`模型与号池.md` §9 与 README 表 B 都写着这个决定，且生成器仍判一致。"""
    doc = _text(POOL_DOC)
    lines = doc.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith("## 9.")), None)
    assert start is not None, "模型与号池.md 里没有 §9 那一节（决定被删了？）"
    section = "\n".join(lines[start:])
    assert "不移植" in section, section
    assert "0011" in section, section

    readme = _text(POOL_README)
    parts = readme.split("### 表 B · pool 不做的事", 1)
    assert len(parts) == 2, "README 里找不到表 B（标题被改了？）"
    body = parts[1].split("\n### ", 1)[0]
    rows = [ln for ln in body.splitlines()
            if "0011-no-systemone" in ln and "systemone" in ln.lower()]
    assert rows, "表 B 里没有同时点名 systemone 与 0011-no-systemone 的一行"

    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "gen_pool_readme.py"), "--check"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", check=False, **NO_WINDOW,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "与现算一致" in proc.stdout, proc.stdout
