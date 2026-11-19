"""F37 诊断三件套（heap / cpu / goroutines）的**否定式钉子**（卡 A377 · T-AG665）。

magpie 的 /v1/magpie/heap、/v1/magpie/cpu、/v1/magpie/goroutines 是三个 Go runtime
专属的只读端点（pprof heap protobuf / Go CPU profiler / pprof.Lookup("goroutine")）。
Python 侧没有对应物，本仓也没有管理面 ⇒ 判 **SKIP_NOT_APPLICABLE**；本文件钉的是
「不存在的继续不存在」，不是「以后再做」。

钉子表（逐条与卡 A377 的判据对应）：

1. `test_magpie_diag_paths_are_404_even_with_a_valid_token`
   三条诊断路径带**合法** Bearer 也 404（体是 JSON `not_found_error`）；
   `GET /v1/models` 不带 token ⇒ 401 对照。
2. `test_gateway_paths_are_exactly_four_and_carry_no_diag_paths`
   `PATHS` 恰四键（集合级）；AST 常量集里没有 `/v1/magpie/`、`/v1/responses`、
   `/v1/embeddings`、`/v1/ollama`。
3. `test_repo_has_no_in_process_introspection`
   `tools/` 与 `scripts/` 全量 `.py` 对 profiler / 抓栈正则零命中；
   `usage_ingest.py` 的 `magpie/` 只在说明文字里。
4. `test_pipeline_view_mem_only_in_report`：`[mem]` 只进 `--report`，
   `--json` 里 `mem` / `tracemalloc` 都不出现（池侧等价读数）；
   以及 `test_job_state_uses_log_silence_not_stacks`：「卡住」的口径来自
   **日志静默**（`jobs.STALL_SECONDS`），不是抓栈。
5. `test_gateway_imports_no_profiler_modules`
   网关导入表里没有 `cProfile` / `profile` / `pprof` / `gc` / `tracemalloc`
   （没有 profiler 就没法悄悄开一个）。

★ 为什么新建而不是塞进 tests/test_pool_gateway.py：那个文件是「六条判据逐条钉」的**行为**
  钉子表（:5-28），本卡钉的是「这一面不存在」—— 两类钉子混一张表会让否定式判据读起来像
  行为缺失。两卡文件互不 import，夹具各带一份。

★ 全部只造数据：build_server(port=0) 起在回环上、端点表打桩；pipeline_view 跑在
  tmp_path 空根上 ⇒ 一个字节不出网、不碰真仓。
"""

from __future__ import annotations

import ast
import http.client
import json
import re
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import pipeline_view  # noqa: E402 —— tools/ 已在 sys.path 上
from pool import (  # noqa: E402
    gateway,
    jobs,
)

TOKEN = "tok"


# ---------------------------------------------------------------- 夹具（自带，不借别的测试文件）


class _ForwardRecorder:
    """转发桩：**本卡一条都不许真转发** —— 记下来，判据 1 断言为空。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, bytes]] = []

    def __call__(self, model: str, account: str, url: str,
                 payload: bytes) -> gateway.Reply:
        self.calls.append((model, account, url, payload))
        return gateway.Reply(status=200, headers={"Content-Type": "application/json"},
                             body=b'{"ok":true}')


@pytest.fixture()
def gateway_server(tmp_path: Path):
    """起一条真服务在后台线程（port=0 由内核挑），teardown 真收干净。"""
    forward = _ForwardRecorder()
    server = gateway.build_server(forward, host="127.0.0.1", port=0, token=TOKEN,
                                  pool="codebuddy", root=tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(server.server_address[1]), forward
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def _header(headers: dict[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None


def _request(port: int, method: str, path: str, *,
             token: str | None = TOKEN) -> tuple[int, dict[str, str], bytes]:
    merged: dict[str, str] = {}
    if token is not None:
        merged["Authorization"] = f"Bearer {token}"
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10.0)
    try:
        conn.request(method, path, headers=merged)
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


# ================================================================ 判据 1


def test_magpie_diag_paths_are_404_even_with_a_valid_token(gateway_server) -> None:
    """三条诊断路径带合法 Bearer 也是 404；401 对照证明那不是鉴权挡的。"""
    port, forward = gateway_server
    for path in ("/v1/magpie/heap", "/v1/magpie/cpu?seconds=30",
                 "/v1/magpie/goroutines"):
        status, _headers, body = _request(port, "GET", path, token=TOKEN)
        assert status == 404, f"{path} 应当是 404（本仓没有这条路径）"
        payload = json.loads(body.decode("utf-8"))
        assert payload["error"]["type"] == "not_found_error", path

    # 对照：合法 token 打已有路径是 200 ⇒ 上面三条的 404 不是「token 不对」挡出来的。
    status, _headers, body = _request(port, "GET", "/v1/models", token=TOKEN)
    assert status == 200
    assert json.loads(body.decode("utf-8"))["object"] == "list"
    # 同一路径不带 token ⇒ 401：鉴权确实在起作用，只是与那三条 404 无关。
    status, headers, _body = _request(port, "GET", "/v1/models", token=None)
    assert status == 401
    assert _header(headers, "WWW-Authenticate") == "Bearer"

    assert forward.calls == [], "这几条请求一个都不许转发到上游"


# ================================================================ 判据 2


def test_gateway_paths_are_exactly_four_and_carry_no_diag_paths() -> None:
    """PATHS 恰四键（集合级）；源码常量里没有任何诊断 / 兼容面前缀。"""
    assert sorted(gateway.PATHS) == [
        "/v1/chat/completions", "/v1/messages", "/v1/models", "/v1/pool/routes",
    ], "网关只许这四条路径（gateway.py:98「四条路径，一个都不多」）"

    source = Path(gateway.__file__).read_text(encoding="utf-8")
    consts = [node.value for node in ast.walk(ast.parse(source))
              if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    assert [c for c in consts if c.startswith("/v1/magpie/")] == [], \
        "源码里不许出现任何 /v1/magpie/ 前缀（诊断三件套不移植）"
    for prefix in ("/v1/responses", "/v1/embeddings", "/v1/ollama"):
        assert [c for c in consts if c.startswith(prefix)] == [], f"不许留 {prefix} 面"


# ================================================================ 判据 3

_INTROSPECT_RE = re.compile(
    r"pprof|goroutine|faulthandler|cProfile|py-spy|_current_frames"
    r"|threading\.enumerate|dump_traceback",
    re.I,
)


def _docstring_ids(tree: ast.AST) -> set[int]:
    """模块 / 类 / 函数头上那段说明文字的节点 id（**不算代码字符串**）。"""
    ids: set[int] = set()
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, holders):
            continue
        body = node.body
        if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            ids.add(id(body[0].value))
    return ids


def test_repo_has_no_in_process_introspection() -> None:
    """tools/ 与 scripts/ 全量源码对 profiler / 抓栈正则零命中（读文件，不 shell 出去）。"""
    hits: list[str] = []
    for base in ("tools", "scripts"):
        for path in sorted((ROOT / base).rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for number, line in enumerate(text.splitlines(), 1):
                if _INTROSPECT_RE.search(line):
                    hits.append(f"{path.relative_to(ROOT).as_posix()}:{number}: {line.strip()}")
    assert hits == [], "本仓没有进程内省 / 抓栈能力：\n" + "\n".join(hits)

    # magpie/ 在本仓唯一那次出现是说明文字（usage_ingest.py:11 的模块 docstring），
    # 不在任何**代码字符串**里 —— 免得将来拿「反正已经出现过一次」当借口引进来。
    ingest = (TOOLS / "pool" / "usage_ingest.py").read_text(encoding="utf-8")
    tree = ast.parse(ingest)
    doc_ids = _docstring_ids(tree)
    in_code = [node.value for node in ast.walk(tree)
               if isinstance(node, ast.Constant) and isinstance(node.value, str)
               and id(node) not in doc_ids and "magpie/" in node.value]
    assert in_code == [], "magpie/ 只许出现在说明文字里，不许进代码字符串"
    assert "magpie/" in (ast.get_docstring(tree) or "")


# ================================================================ 判据 4


def _run_cli(root: Path, flag: str) -> tuple[int, str]:
    """跑一次 pipeline_view CLI（带 NO_WINDOW），回 (rc, stdout)。"""
    done = subprocess.run(
        [sys.executable, "-X", "utf8", str(TOOLS / "pipeline_view.py"), flag,
         "--root", str(root)],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace", **pipeline_view.NO_WINDOW,
    )
    return done.returncode, done.stdout


def test_pipeline_view_mem_only_in_report(tmp_path: Path) -> None:
    """本仓的等价读数：[mem] 峰值只进 --report，--json 里一个字都不许有。"""
    rc_report, report = _run_cli(tmp_path, "--report")
    assert rc_report == 0, report[-800:]
    assert "[mem] Python 侧峰值" in report

    rc_json, payload = _run_cli(tmp_path, "--json")
    assert rc_json == 0, payload[-800:]
    assert "mem" not in payload, "--json 里出现 mem ⇒ 冷跑/热跑不再逐字节相同"
    assert "tracemalloc" not in payload
    json.loads(payload)  # 体仍是 JSON（不是被顺手改坏的东西）


def test_job_state_uses_log_silence_not_stacks() -> None:
    """「卡住」的口径来自**日志静默**（jobs.STALL_SECONDS），不是抓本进程栈。"""
    assert jobs.classify_job_state(0.0, False)[0] == "在跑"
    stalled = jobs.classify_job_state(jobs.STALL_SECONDS + 1, False)
    assert stalled[0] == "断了"
    assert "静默" in stalled[1], "断了的口径必须说「日志已静默」——这是本仓的答案"
    assert jobs.classify_job_state(9999.0, True)[0] == "已判决"


# ================================================================ 判据 5

_DISALLOWED_IMPORTS = frozenset({"cProfile", "profile", "pprof", "gc", "tracemalloc"})


def test_gateway_imports_no_profiler_modules() -> None:
    """网关导入表里没有 profiler / 内存观测模块 —— 没有它就没法悄悄开一个端点。"""
    tree = ast.parse(Path(gateway.__file__).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    assert names & _DISALLOWED_IMPORTS == set(), sorted(names & _DISALLOWED_IMPORTS)
    # 扫描不是空转：导入表真读到了几条已知项。
    assert {"json", "http", "hmac"} <= names
