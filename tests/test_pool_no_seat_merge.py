r"""卡 A387（T-AG675）：F88 账号别名与 seat 合并 —— 判 SKIP_NOT_APPLICABLE 的五条钉子。

判据原文见 `复盘/卡/卡A387-F88账号别名与seat合并-判SKIP_NOT_APPLICABLE.md`；这里只写
**会失败**的断言 —— 每一条钉的都是「本仓没有这个东西」，不是「这个东西做对了」。

| 钉子 | 钉哪一位 |
|---|---|
| `test_seat_family_vocabulary_is_absent` | 判据 1：magpie 那一族词一个都没被搬进来 |
| `test_paths_table_is_exactly_four` | 判据 2：PATHS 恰四键、无 `/v1/magpie/` 常量、桩服务 404 |
| `test_ledger_has_no_window_section` | 判据 3：窗口维恒空（仓外账本不存在 ⇒ skip，不许 fail） |
| `test_ledger_dedupes_by_id_only` | 判据 4：`load_ledger` 只按 `id` 去重（无名/别名/座位） |
| `test_cleared_keeps_the_alias_not_ported_anchor` | 判据 5：「别名归并 … 不移植」句逐字在位 |

★ 为什么「钉没有」也值当：判定表 `gates/diag/_magpie_scope.md` 曾把 F88 判成 PORT / partial，
证据写「seat 概念在」——那是**同形不同义**（本仓的 `seat` 是账本 id，不是 magpie 的座位）。
这五条把「对象不存在 / 机制无落脚点 / 出口不存在」变成会红的断言：删掉任何一处重现，
本文件先红，而不是留成一句「还没做」。

★ 判据 1 扫的是 tools/ src/ scripts/，**不扫 tests/**：本文件自己就含那一族词（写成注释
也会被扫到），所以扫描面与卡规格的 pytest 版口径逐字一致。

★ 判据 5 的「hides() 函数体不含 alias」按**可执行体**判（去掉函数自己的 docstring）：
那条「不移植」锚句就写在 `hides` 的 docstring 里（`tools/pool/cleared.py:184-185`），
把 docstring 算进去会自相矛盾 —— 锚句与「不含 alias」只能分别落在「整文件」与「代码体」上。

★ 导入口径照 `tests/test_pool_account_scope.py`：`tools/` 不在 `sys.path` 上，模块级只做
`sys.path.insert` 加 `importlib.import_module`，不写 import 语句（否则踩 E402）。
"""

from __future__ import annotations

import ast
import http.client
import importlib
import re
import sys
import threading
from pathlib import Path

import pytest
import tomllib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

gateway = importlib.import_module("pool.gateway")
pool_accounts = importlib.import_module("pool_accounts")

GATEWAY = ROOT / "tools" / "pool" / "gateway.py"
ACCOUNTS = ROOT / "tools" / "pool_accounts.py"
CLEARED = ROOT / "tools" / "pool" / "cleared.py"

#: 判据 1 的扫描面（与卡规格的原命令同口径：--include=*.py --include=*.toml）。
SCAN_DIRS = ("tools", "src", "scripts")
SCAN_SUFFIXES = (".py", ".toml")

#: magpie F88 那一族名字。**一个都不许出现在本仓**（同形不同义不算：seat 单字不在表里）。
SEAT_FAMILY = re.compile(
    r"seatMatch|seats\.json|seatsPath|planSeatKey|AccountNames|AccountShown|SeatNameOf"
    r"|withAccountNames|setAccountName|magpie/quotas"
)

TOKEN = "no-seat-merge-token"


# ---------------------------------------------------------------- 判据 1：词表零命中


def _scanned_files() -> list[Path]:
    """tools/ src/ scripts/ 下的 .py 与 .toml（逐文件扫 —— 原命令的 --include 两个后缀）。"""
    out: list[Path] = []
    for name in SCAN_DIRS:
        base = ROOT / name
        if not base.is_dir():
            continue
        out.extend(p for p in sorted(base.rglob("*")) if p.is_file() and p.suffix in SCAN_SUFFIXES)
    return out


def test_seat_family_vocabulary_is_absent() -> None:
    """★ 判据 1：`seatMatch` / `seats.json` / `AccountNames` 这一族**一个都没被搬进来**。

    ★ 前提先钉住：扫描面必须真的包含判据要读的那几份（`gateway.py` / `cleared.py`）。
      路径算错时 rglob 会静默少文件 —— 少到零就是「一条断言都证明不了」的假绿。
    """
    files = _scanned_files()
    assert files, "扫描面为空 ⇒ 这条判据什么都证明不了"
    for must in (GATEWAY, ACCOUNTS, CLEARED):
        assert must in files, f"扫描面漏了 {must.relative_to(ROOT).as_posix()}"
    hits: list[str] = []
    for path in files:
        text = path.read_bytes().decode("utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if SEAT_FAMILY.search(line):
                hits.append(f"{path.relative_to(ROOT).as_posix()}:{lineno}: {line.strip()}")
    assert hits == [], "magpie F88 那一族词被搬进来了（本仓判的是不移植）：\n" + "\n".join(hits)


# ---------------------------------------------------------------- 判据 2：路径表恰四键


def _gateway_source() -> tuple[str, ast.Module]:
    """`gateway.py` 的源码与语法树（AST 判据一律从这一处取，不认 import 进来的对象）。"""
    source = GATEWAY.read_bytes().decode("utf-8")
    return source, ast.parse(source)


def _string_constants(tree: ast.Module) -> list[str]:
    """全部 `ast.Constant` 里的 `str`（**含 docstring** —— 管理面路径写进注释也算开了口子）。"""
    return [node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)]


def _get(port: int, path: str, token: str | None) -> tuple[int, bytes]:
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10.0)
    try:
        conn.request("GET", path, headers=headers)
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


def test_paths_table_is_exactly_four(tmp_path: Path) -> None:
    """★ 判据 2：路径表**恰好四键**，且没有任何 `/v1/magpie/` 前缀的常量。

    ★ 与 `tests/test_pool_gateway.py` 的那条钉子（F36）**独立再钉一次**：F88 的读数出口
      就是管理面 `quotas` 的 `alias` / `seat`，F88 的钉子不许依赖另一个卡的文件将来不被改。
    ★ 第三段起真服务：`/v1/magpie/quotas` 必须是 404（路径表里没有它），而且那 404 **不是**
      鉴权挡的 —— 同一服务面上不带令牌的 `/v1/models` 是 401（反证）。
    """
    assert sorted(gateway.PATHS) == ["/v1/chat/completions", "/v1/messages",
                                     "/v1/models", "/v1/pool/routes"]
    _, tree = _gateway_source()
    magpie = [c for c in _string_constants(tree) if c.startswith("/v1/magpie/")]
    assert magpie == [], f"gateway.py 里出现了管理面前缀常量：{magpie}"

    forwarded: list[tuple[str, str, str, bytes]] = []

    def _stub(model: str, account: str, url: str, payload: bytes) -> gateway.Reply:
        forwarded.append((model, account, url, payload))
        return gateway.Reply(status=200, headers={}, body=b'{"ok":true}')

    server = gateway.build_server(_stub, host="127.0.0.1", port=0, token=TOKEN, root=tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = int(server.server_address[1])
        for path in ("/v1/magpie/quotas", "/v1/magpie/quotas?limit=1", "/v1/magpie/"):
            status, body = _get(port, path, TOKEN)
            assert status == 404, (path, status, body)
            assert b"not_found_error" in body, (path, body)
        assert _get(port, "/v1/models", None)[0] == 401, "404 不许是鉴权挡出来的"
        assert forwarded == [], "404 之前一个请求都不许转发"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


# ---------------------------------------------------------------- 判据 3：账本没有窗口段


def test_ledger_has_no_window_section() -> None:
    """★ 判据 3：窗口维**恒为空** —— `seatMatch` 的输入在本仓不存在。

    ★ 真账本在**仓外**（`infra/pool/accounts.toml`）：不存在就 skip，**不许 fail**
      （换台机器 / 云机上它本来就没有）—— 路径一律走 `find_ledger()`，不写死盘符。
    """
    assert gateway._windows({}) == []
    assert gateway._windows({"quota": {"unit": "percent", "samples": []}}) == []
    # 有 windows 段但读不懂 ⇒ 仍是空表（不是「有窗口但都是空的」）。
    assert gateway._windows({"quota": {"windows": []}}) == []
    assert gateway._windows({"quota": {"windows": [1, "x", None]}}) == []

    try:
        ledger = pool_accounts.find_ledger()
    except (pool_accounts.LedgerError, FileNotFoundError) as exc:
        pytest.skip(f"仓外账本不存在（判据 3 只对真账本有意义）：{exc}")
    data = tomllib.loads(ledger.read_bytes().decode("utf-8"))
    rows = data.get("account") or []
    assert rows, f"账本里没有 [[account]] 表：{ledger}"
    for row in rows:
        assert gateway._windows(row) == [], f"账本行 {row.get('id')!r} 起了窗口段"


# ---------------------------------------------------------------- 判据 4 / 5：读源码文本


def _function_source(path: Path, name: str) -> tuple[str, ast.FunctionDef]:
    """取某个模块级函数的**源码段**与语法节点（连同它自己的 docstring）。"""
    source = path.read_bytes().decode("utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segment = ast.get_source_segment(source, node)
            assert segment is not None, f"{path.name} 的 {name}() 取不到源码段"
            return segment, node
    raise AssertionError(f"{path.relative_to(ROOT).as_posix()} 里找不到函数 {name}()")


def _code_body(path: Path, name: str) -> str:
    """函数**可执行体**的源码（去掉开头那条 docstring）。

    ★ 为什么要去 docstring：`cleared.hides()` 的「不移植」锚句与它的「不含 alias」否定断言
      只能分居两处（锚句就在那个 docstring 里，见 `tools/pool/cleared.py:184-185`）。
    """
    source = path.read_bytes().decode("utf-8")
    _, node = _function_source(path, name)
    body = list(node.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    assert body, f"{path.name} 的 {name}() 只有 docstring、没有代码体"
    return "\n".join(filter(None, (ast.get_source_segment(source, stmt) for stmt in body)))


def test_ledger_dedupes_by_id_only() -> None:
    """★ 判据 4：账本校验**只按 `id` 去重**，没有按名字 / 别名 / 座位去重。

    ★ 这条封的是 seat 合并的**另一条实现路径**：不经 `seats.json`，直接在读账本时把
      「两个号同名」合成一行，也能造出「合并后少一张卡」的读数。
    ★ 为什么读源码文本而不是跑运行时：造临时账本会先被批准集与 `[account.credential]`
      两道校验挡住（卡规格「诚实边界」第 4 条记了这次未跑通）。
    """
    body = _function_source(ACCOUNTS, "load_ledger")[0]
    assert 'if acc["id"] in seen:' in body, "load_ledger 不再按 id 去重"
    assert "账号 id 重复" in body, "load_ledger 不再点名重复 id"
    for forbidden in ('acc["label"] in', 'acc["alias"] in', 'acc["seat"] in'):
        assert forbidden not in body, f"load_ledger 里出现了按 {forbidden} 去重/合并（侧门）"


def test_cleared_keeps_the_alias_not_ported_anchor() -> None:
    """★ 判据 5：`cleared.py` 的「别名归并 … 不移植」句**逐字在位**。

    ★ 它是今天仓里唯一写着「这件事判过、判的是不做」的地方 —— 被当成过期注释删掉，
      本仓就再没有任何锚能证明 F88 判过。
    ★ 后半条：`hides()` 的**代码体**里没有把 `model` 映射成别名的分支（否定：不含 alias）。
    """
    text = CLEARED.read_bytes().decode("utf-8")
    for phrase in ("别名归并", "**不移植**", "第二套真源"):
        assert phrase in text, f"cleared.py 的「不移植」锚少了「{phrase}」"
    code = _code_body(CLEARED, "hides")
    assert "alias" not in code, "hides() 的代码体里出现了别名分支（不移植的那一段被搬回来了）"
