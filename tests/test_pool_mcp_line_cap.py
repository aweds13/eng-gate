r"""MCP 那一行有多长才算太长（卡 A362 · T-AG573 · F7「请求体边界与 413 归责」）—— 8 条钉子。

## 钉什么（一层意思）

`tools/pool_mcp.py` 的 stdio 入站是**一行一个 JSON-RPC**，而那一行原来**没有上限**：
`raw: bytes = buffer.readline()` 可以无限长，`serve()` 也只处理「解不开 UTF-8」。
magpie 撞过同一个洞，并把判据写进了注释（`internal/gateway/search_mcp.go:226-229` 逐字）：

> A LimitReader alone ends at the limit as if the body had, so a valid message padded
> past it was read as its prefix and run (#1766); **one byte more tells a body that
> ended from one that was cut.**

⇒ 读满 `limit` **不能下结论**，要**再读 1 字节**看有没有第 `limit + 1` 个。超限时**不许**
把超限的合法消息当成它的前缀执行 —— 那不是拒绝，那是把「被截断的东西」当完整的跑。

## 九条钉子一览

| 钉子 | 判什么 |
|---|---|
| ① `test_over_limit_is_refused_not_run` | 超限的**合法 JSON** ⇒ 回一条错误、**不执行**它 |
| ② `test_exactly_limit_is_run` | 边界内侧：内容恰等于 `MAX_LINE_BYTES` ⇒ **执行** |
| ③ `test_limit_plus_one_is_refused` | 边界外侧：内容 `MAX + 1` ⇒ **拒**（数**内容**字节） |
| ④ `test_exactly_limit_without_newline_still_runs` | 多读一字节才判：`MAX`+**无换行**+EOF ⇒ 执行 |
| ⑤ `test_refusal_keeps_serving` | 拒之后**继续服务**下一行（stdio 没有 `Connection: close`） |
| ⑥ `test_residue_does_not_become_next_line` | 拒之后吞干净剩余字节（否则残余成下一行） |
| ⑦ `test_bad_bytes_still_only_spoil_their_line` | 吞残余时**不解码**：残余有坏字节也只坏那一行 |
| ⑧ `test_message_names_actual_size` | 文案说清「太长」+ 实际字节数，且数字就是 `MAX_LINE_BYTES` |
| ⑨ `test_max_line_bytes_is_32_mib` | 常量本身：`MAX_LINE_BYTES == 32 << 20`（照 `mcp.go:83`） |

## 为什么 ④ 必须「无换行」

`readline()` 下，末尾有 `\n` 时「读满 limit 就停」与「读 limit + 1」**表现一样**（都能看见
换行、都判得出「到此为止」）—— 那一版实现改了没人发现。只有「正好 limit 字节 + **没有换行**
+ 紧跟 EOF」这种输入，才分得开「读满了就以为被切」与「再问一字节才知道到此为止」。
反向变异脚本 `gates/diag/_rev_A362.py` 的变异 1（`limit + 1` → `limit`）就是靠它这一族输入
咬住的，那里如实记了哪几条钉子变红。

★ 导入用 `importlib`：本仓禁 n-o-q-a 注释，而 `sys.path.insert` 之后直接写 import 会踩 E402
（口径同 `tests/test_pool_disabled.py` / `tests/test_pool_callers.py`）。
"""

from __future__ import annotations

import importlib
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

pool_mcp = importlib.import_module("pool_mcp")

#: 那行大消息的骨架：`tools/list` 不看 `params`，塞多大的 pad 都不会真跑工具。
_PREFIX = b'{"jsonrpc":"2.0","id":7,"method":"tools/list","params":{"pad":"'
_SUFFIX = b'"}}'
_SKELETON = len(_PREFIX) + len(_SUFFIX)


def _frame(total: int) -> bytes:
    """造一行**恰好 `total` 字节**的合法 JSON-RPC 消息（`total` 是**内容**字节，不含行尾）。"""
    pad = total - _SKELETON
    assert pad > 0, f"{total} 字节装不下骨架（骨架 {_SKELETON} 字节）"
    out = _PREFIX + b"a" * pad + _SUFFIX
    assert len(out) == total, (len(out), total)
    return out


class _FakeStdin:
    """只暴露 `.buffer` 的假 stdin —— 走**字节路径**（协议真正的入站路径）。"""

    def __init__(self, payload: bytes) -> None:
        self.buffer = io.BytesIO(payload)


def _serve(payload: bytes, monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """喂**原始字节**给 `serve()`，按出现顺序收回它吐的每一条协议消息。"""
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdin", _FakeStdin(payload))
    monkeypatch.setattr(sys, "stdout", out)
    assert pool_mcp.serve([]) == 0
    return [json.loads(x) for x in out.getvalue().splitlines() if x.strip()]


def _read_line_of(monkeypatch: pytest.MonkeyPatch, payload: bytes, limit: int) -> object:
    """直接调 `_read_line(limit=…)`（小上限，省掉 32 MiB）。"""
    monkeypatch.setattr(sys, "stdin", _FakeStdin(payload))
    return pool_mcp._read_line(limit=limit)


def _codes(replies: list[dict]) -> list[int | None]:
    return [None if "result" in r else r["error"]["code"] for r in replies]


def _messages(replies: list[dict]) -> str:
    return "\n".join(str(r.get("error", {}).get("message", "")) for r in replies)


# ================================================================ 钉子①：超限不执行


def test_over_limit_is_refused_not_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """超限的**合法 JSON** ⇒ 一条错误、**没有结果**（#1766：不许把超限体当它的前缀跑）。"""
    replies = _serve(_frame(pool_mcp.MAX_LINE_BYTES + 1) + b"\n", monkeypatch)
    assert len(replies) == 1, replies  # 只有一条错误：那一行没有被执行
    assert "result" not in replies[0], replies
    assert replies[0]["error"]["code"] == pool_mcp.JSONRPC_INVALID_PARAMS
    assert "太长" in _messages(replies)

    # ★ 别名是**活的**：`serve()` 里 `except LineTooLong` 捕获到的就是这个类。
    #   删掉 `LineTooLong = LineTooLongError` 那行 ⇒ 这里 AttributeError ⇒ 红。
    with pytest.raises(pool_mcp.LineTooLong) as caught:
        _read_line_of(monkeypatch, b"x" * 100 + b"\n", 64)
    # 带出来的是**读到多少报多少**（65 = limit + 1）；整行总长由 `serve()` 加上吞掉的残余算出来。
    assert caught.value.size == 65


# ================================================================ 钉子②：边界内侧


def test_exactly_limit_is_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """内容**恰等于** `MAX_LINE_BYTES` ⇒ **执行**（与钉子③成对：`>` 与 `>=` 改错就分得开）。"""
    replies = _serve(_frame(pool_mcp.MAX_LINE_BYTES) + b"\n", monkeypatch)
    assert _codes(replies) == [None], replies
    assert len(replies[0]["result"]["tools"]) == len(pool_mcp.tool_list())


# ================================================================ 钉子③：边界外侧


def test_limit_plus_one_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """内容 `MAX_LINE_BYTES + 1` ⇒ **拒**。

    ★ 判的是**内容**字节：末尾照样带一个 `\n`（整行 `MAX + 2` 字节），拒的理由只能是内容超了
    一格 —— 若有人按「整行字节数」算上限，钉子②会跟着红（那条的整行是 `MAX + 1`）。
    """
    replies = _serve(_frame(pool_mcp.MAX_LINE_BYTES + 1) + b"\n", monkeypatch)
    assert len(replies) == 1, replies
    assert "result" not in replies[0], replies
    assert replies[0]["error"]["code"] == pool_mcp.JSONRPC_INVALID_PARAMS


# ================================================================ 钉子④：多读一字节才判


def test_exactly_limit_without_newline_still_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """正好 `MAX_LINE_BYTES` 字节内容 **+ 无换行 + 紧跟 EOF** ⇒ **执行**。

    这是本卡**唯一**能咬住「读满 limit 就以为被切了」那一位的写法：末尾一旦有 `\n`，
    「读满就停」与「再读一字节」在 `readline()` 下表现**一模一样**（假绿）。
    与钉子③合起来把边界两侧各错一格的实现都封死：超一格拒（③）、正正好好照跑（②④）。
    """
    content = _frame(pool_mcp.MAX_LINE_BYTES)
    assert not content.endswith(b"\n")
    replies = _serve(content, monkeypatch)  # ★ 末尾**没有**换行，EOF 就在它后面
    assert _codes(replies) == [None], replies
    assert len(replies[0]["result"]["tools"]) == len(pool_mcp.tool_list())


# ================================================================ 钉子⑤：拒之后继续服务


def test_refusal_keeps_serving(monkeypatch: pytest.MonkeyPatch) -> None:
    """超限 + `\\n` + 一条正常 `tools/list` ⇒ **一条错误 + 一条正常结果**，且顺序如此。

    stdio 是长连接、`Connection: close` 没有对应物：拒了之后**循环不许退出**。
    """
    payload = _frame(pool_mcp.MAX_LINE_BYTES + 1) + b"\n" + _frame(80) + b"\n"
    replies = _serve(payload, monkeypatch)
    assert len(replies) == 2, replies
    assert replies[0]["error"]["code"] == pool_mcp.JSONRPC_INVALID_PARAMS
    assert "result" in replies[1], replies
    assert len(replies[1]["result"]["tools"]) == len(pool_mcp.tool_list())


# ================================================================ 钉子⑥：残余不许变成下一行


def test_residue_does_not_become_next_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """超限那一行**剩下的字节**必须被吃干净：不许变成下一行、换一条「不是合法 JSON」的假回话。"""
    content = _frame(pool_mcp.MAX_LINE_BYTES + 500)  # 拒的时候只消费了 limit + 1 字节
    payload = content + b"\n" + _frame(80) + b"\n"
    replies = _serve(payload, monkeypatch)
    assert len(replies) == 2, replies  # 三条 = 残余被当成了一行
    assert "不是合法 JSON" not in _messages(replies)  # 残余没被当下一行解析
    assert replies[0]["error"]["code"] == pool_mcp.JSONRPC_INVALID_PARAMS
    assert "result" in replies[1], replies


# ================================================================ 钉子⑦：坏字节只坏那一行


def test_bad_bytes_still_only_spoil_their_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """残余里有**坏 UTF-8 字节**时，吞残余**不解码**：只坏那一行，后面那行照常服务。"""
    content = _frame(pool_mcp.MAX_LINE_BYTES + 200)
    spoiled = content[:-2] + b'\xff\xfe"'  # 行尾附近塞坏字节；反正这一行已经判死
    payload = spoiled + b"\n" + _frame(80) + b"\n"
    replies = _serve(payload, monkeypatch)
    assert len(replies) == 2, replies  # 崩了就只有一条（后面那行拿不到回话）
    assert replies[0]["error"]["code"] == pool_mcp.JSONRPC_INVALID_PARAMS
    assert "result" in replies[1], replies  # 既有防线没破：坏字节没把整条流搞坏


# ================================================================ 钉子⑧：文案带实际字节数


def test_message_names_actual_size(monkeypatch: pytest.MonkeyPatch) -> None:
    """文案说清「太长」+ **实际字节数**，且引的是 `MAX_LINE_BYTES`（不是随便一个数）。"""
    total = pool_mcp.MAX_LINE_BYTES + 7
    replies = _serve(_frame(total) + b"\n", monkeypatch)
    assert len(replies) == 1, replies
    message = _messages(replies)
    assert "太长" in message
    assert str(total) in message, message  # 实际读到的**总长**
    assert str(pool_mcp.MAX_LINE_BYTES) in message, message  # 上限引的是常量


# ================================================================ 钉子⑨：常量本身


def test_max_line_bytes_is_32_mib() -> None:
    """`MAX_LINE_BYTES == 32 << 20`（照 `internal/gateway/mcp.go:83`，**只定义一次**）。"""
    assert pool_mcp.MAX_LINE_BYTES == 32 << 20
    source = (ROOT / "tools" / "pool_mcp.py").read_text(encoding="utf-8")
    assert source.count("MAX_LINE_BYTES: int = ") == 1, "常量只许定义一次"
    assert source.count("32 << 20") == 1, "上限字面量只许出现在常量定义那一行"
