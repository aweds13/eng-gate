"""工人日志的**读法**（卡 E75，T-AG577）—— 按 BOM 判编码，不试、不猜。

**防什么**：`gates/diag/wb-045.jsonl` 是 UTF-16LE 带 BOM。改前 `tools/wb_status.py:201` 是
`path.read_text(encoding="utf-8", errors="replace").splitlines()`：`errors="replace"` 让解码
**永不失败**，于是 122 行事件被当成 2096 行乱码，`tool_calls` 静默变 0、`models` 变空 ——
整条时间线静默消失，比没有窗更坏。

六条判据各至少一条钉子：
  1. UTF-16LE / UTF-16BE **带 BOM** 都认得出事件（`test_utf16_with_bom_*`）；
  2. UTF-8 BOM 按 `utf-8-sig` 读，BOM 不许变成 `\\ufeff` 前缀（`test_utf8_bom_*`）；
  3. 无 BOM 的纯 UTF-8 **一个字节不变**：同一份文件，改前读法与改后读法的 `(timeline, summary)`
     **完全相等**（`test_plain_utf8_*`，回归钉子）；
  4. 认不出编码时**不猜**：抛 `UnknownLogEncodingError`，不许静默当空（`test_*_not_guessed`）；
  5. **一处读法**：所有按行读工人日志的地方共用 `pool.jobs.read_log_lines`
     （`test_only_one_reading_path_*`，grep 全仓）；
  6. 真文件真读数：真 `gates/diag/wb-045.jsonl` 跑一遍 `tool_calls > 0` 且 `models` 非空
     （`test_real_utf16_worker_log_*`，缺失 skip 不 pass）。

另有一条**对等钉子**：`harness/logcodec.py` 是 `harness/` 的复制体（该目录的规矩是不依赖
`tools/`），同一份输入两边 `lines` 必须逐字节相等 —— 覆盖上面四种编码
（`test_harness_logcodec_agrees_with_tools`）。只改一边的 BOM 判定顺序，它就红。

★ 本仓禁 `# noqa`，所以这里**不在顶层 import 本地模块**（那会踩 E402）：一律函数内加载。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"

#: 改前那条读法（`tools/wb_status.py:201` 的原样）—— 判据 3 拿它当"改前"，判据 6 拿它当"今天的病"。
_HISTORICAL_TAG = 'read_text(encoding="utf-8", errors="replace").splitlines()'

#: 允许保留这条写法的四处：都不是"按行读工人日志"，各有各的读法（见 `pool/jobs.py` docstring）。
_NOT_WORKER_LOGS = {
    "tools/pool/landing.py",   # 按 `=== … ===` 分节读文档件
    "tools/run_logged.py",     # 读自己刚写的那份 tail 日志
    "tools/stack.py",          # 读 gates/diag/stack-actions.log
    "tools/wb_brief.py",       # 读 markdown 规矩件
}

#: 该走共享读法的调用点（判据 5：一处读法）。
_CALL_SITES = (
    "tools/wb_status.py",
    "tools/wb_diag.py",
    "tools/pool_mcp.py",
    "tools/pool/trae_dispatch.py",
    "tools/pool/usage_ingest.py",
    "tools/wb_dispatch.py",
    "tools/wb_watch.py",
    "tools/replay_worker_edits.py",
    "harness/wb_status.py",
    "harness/wb_diag.py",
)

#: 真证据：卡树里 `gates/diag/` 被 gitignore（不随卡树走），真件在主树。
REAL_LOG = ROOT.parent.parent / "gates" / "diag" / "wb-045.jsonl"


# ---------------------------------------------------------------- 加载（不在顶层 import 本地模块）

def _jobs() -> ModuleType:
    """`tools/pool/jobs.py` —— 共享读法的真源。"""
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))
    from pool import jobs

    return jobs


def _wb_status() -> ModuleType:
    """`tools/wb_status.py` —— 今天唯一的那处读点。"""
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))
    import wb_status

    return wb_status


def _by_path(name: str, path: Path) -> ModuleType:
    """按路径加载一个模块（给 `harness/logcodec.py` 这种"不与 tools 同包"的复制体用）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"加载不了 {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------- 合成输入

def _payloads() -> list[dict[str, Any]]:
    """一份"什么都有"的工人日志：开场、说话、两次工具调用、错误回话、收尾。"""
    return [
        {"type": "system", "subtype": "init", "model": "deepseek-v3-2-volc",
         "tools": ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "我先读一遍交接文档，再决定动哪里。"}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "git status --short"}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "content": "M src/timeflow/api/app.py"},
            {"type": "tool_result", "content": "boom", "is_error": True}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Edit",
             "input": {"file_path": "src/timeflow/core/tasks/manager.py",
                       "old_string": "a", "new_string": "b"}}]}},
        {"type": "result", "subtype": "success"},
    ]


def _text() -> str:
    return "\n".join(json.dumps(p, ensure_ascii=False) for p in _payloads()) + "\n"


def _messy_text() -> str:
    """纯 UTF-8 但**带坏行**：判据 3 要证明"坏几行照样读得下去"这件事一点没变。"""
    extra = ["not json at all", json.dumps([1, 2])]
    return "\n".join([_text().rstrip("\n"), *extra]) + "\n"


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _historical_lines(path: Path) -> list[str]:
    """改前那条读法，**逐字**照抄（`errors="replace"` 在：它治坏字节，不治编码）。"""
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


# ---------------------------------------------------------------- 判据 1：UTF-16 带 BOM 认得出

@pytest.mark.parametrize(("bom", "codec"), [(b"\xff\xfe", "utf-16-le"),
                                           (b"\xfe\xff", "utf-16-be")])
def test_utf16_with_bom_is_recognised(tmp_path: Path, bom: bytes, codec: str) -> None:
    text = _text()
    path = _write(tmp_path, f"wb-901-{codec}.jsonl", bom + text.encode(codec))

    assert _jobs().log_codec(path.read_bytes()) == codec
    lines = _jobs().read_log_lines(path)
    assert lines == text.splitlines()

    timeline, summary = _jobs().parse_events(lines)
    assert summary["models"] == ["deepseek-v3-2-volc"]
    assert summary["tool_calls"] == 2
    assert summary["unknown_events"] == 0
    assert timeline[0].startswith("  开  init  model=deepseek-v3-2-volc")

    # 改前那条读法会把同一份文件读成乱码 —— 这就是本卡要治的病
    _old_timeline, old_summary = _jobs().parse_events(_historical_lines(path))
    assert old_summary["tool_calls"] == 0
    assert old_summary["models"] == []


def test_wb_status_cli_reads_a_utf16_log(tmp_path: Path) -> None:
    """CLI 层也钉一次：`wb_status.py` 自己那条路不能再静默变空。"""
    text = _text()
    path = _write(tmp_path, "wb-902.jsonl", b"\xff\xfe" + text.encode("utf-16-le"))

    ws = _wb_status()
    assert ws.main([str(path)]) == 0

    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert ws.main([str(path), "--json"]) == 0
    summary = json.loads(buffer.getvalue())
    assert summary["tool_calls"] == 2
    assert summary["models"] == ["deepseek-v3-2-volc"]


# ---------------------------------------------------------------- 判据 2：UTF-8 BOM 不变成 \ufeff

def test_utf8_bom_is_stripped_not_a_feff_prefix(tmp_path: Path) -> None:
    text = _text()
    path = _write(tmp_path, "wb-903.jsonl", b"\xef\xbb\xbf" + text.encode("utf-8"))

    assert _jobs().log_codec(path.read_bytes()) == "utf-8-sig"
    lines = _jobs().read_log_lines(path)
    assert lines == text.splitlines()
    assert not any("\ufeff" in line for line in lines)

    timeline, summary = _jobs().parse_events(lines)
    assert summary["unknown_events"] == 0
    assert "非 JSON 行" not in timeline[0]
    assert timeline[0].startswith("  开  init")


# ---------------------------------------------------------------- 判据 3：纯 UTF-8 一个字节不变

def test_plain_utf8_timeline_and_summary_are_byte_for_byte_unchanged(tmp_path: Path) -> None:
    """回归钉子：同一份无 BOM 的 UTF-8 文件，改前 / 改后读出来的 `(timeline, summary)` 必须相等。"""
    path = _write(tmp_path, "wb-904.jsonl", _messy_text().encode("utf-8"))
    before = path.read_bytes()

    jobs = _jobs()
    assert jobs.log_codec(before) == "utf-8"

    old_lines = _historical_lines(path)
    new_lines = jobs.read_log_lines(path)
    assert new_lines == old_lines                      # 一行都不许变（含两条坏行）

    old_timeline, old_summary = jobs.parse_events(old_lines)
    new_timeline, new_summary = jobs.parse_events(new_lines)
    assert new_timeline == old_timeline                # 时间线完全相等
    assert new_summary == old_summary                  # 摘要完全相等（键序、值都算）
    assert old_summary["unknown_events"] == 2          # 坏行照样留着，没被静默丢
    assert path.read_bytes() == before                 # 读不许改文件


# ---------------------------------------------------------------- 判据 4：认不出时不猜

@pytest.mark.parametrize(("name", "data"), [
    ("utf16le-noBOM", _text().encode("utf-16-le")),
    ("utf16be-noBOM", _text().encode("utf-16-be")),
    ("gbk-noBOM", "中文日志\n".encode("gbk")),
])
def test_unrecognised_encoding_is_not_guessed(tmp_path: Path, name: str,
                                              data: bytes) -> None:
    path = _write(tmp_path, f"{name}.jsonl", data)

    jobs = _jobs()
    assert issubclass(jobs.UnknownLogEncodingError, ValueError)
    with pytest.raises(jobs.UnknownLogEncodingError) as caught:
        jobs.read_log_lines(path)
    assert "不猜" in str(caught.value)


def test_wb_status_does_not_turn_unknown_encoding_into_an_empty_timeline(
        tmp_path: Path) -> None:
    """判据 4 的 CLI 面：宁可抛，也不许"什么也没干"地回 0。"""
    path = _write(tmp_path, "wb-905.jsonl", _text().encode("utf-16-le"))
    ws = _wb_status()
    jobs = _jobs()
    with pytest.raises(jobs.UnknownLogEncodingError):
        ws.main([str(path)])


# ---------------------------------------------------------------- 判据 5：一处读法

def test_only_one_reading_path_for_worker_logs() -> None:
    """全仓 grep：`read_text(...).splitlines()` 只许剩那四处非工人日志的读法。"""
    offenders: dict[str, list[int]] = {}
    for base in ("tools", "harness"):
        for path in sorted((ROOT / base).rglob("*.py")):
            hits = [
                number
                for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
                if _HISTORICAL_TAG in line
            ]
            if hits:
                offenders[path.relative_to(ROOT).as_posix()] = hits
    assert set(offenders) <= _NOT_WORKER_LOGS, f"还有同型写法没归并：{offenders}"

    for rel in _CALL_SITES:
        source = (ROOT / rel).read_text(encoding="utf-8")
        assert "read_log_lines" in source, f"{rel} 没走共享读法"


def test_shared_reader_is_exported_from_the_one_place() -> None:
    """读法只有一份真源；复制体（`harness/logcodec.py`）单独存在，由对等钉子钉住。"""
    jobs = _jobs()
    assert callable(jobs.read_log_lines)
    assert callable(jobs.log_codec)
    assert (ROOT / "harness" / "logcodec.py").is_file()
    # `tools/wb_dash.py` 有自己的 `_read_log_lines`（字节级容错、逐行救），本卡**不裁决**它对不对
    # ——见卡 E75 gaps：同一份坏日志 wb_dash 会救、wb_status 会抛，两个入口结论不同，下一张卡的事。
    dash = (ROOT / "tools" / "wb_dash.py").read_text(encoding="utf-8")
    assert "def _read_log_lines(" in dash


# ---------------------------------------------------------------- 判据 6：真文件真读数

@pytest.mark.skipif(
    not REAL_LOG.is_file(),
    reason=f"真日志不在：{REAL_LOG}（gates/diag/ 被 gitignore，卡树里没有 ⇒ skip，不算 pass）")
def test_real_utf16_worker_log_yields_a_timeline() -> None:
    raw = REAL_LOG.read_bytes()
    assert raw[:2] == b"\xff\xfe"

    jobs = _jobs()
    lines = jobs.read_log_lines(REAL_LOG)
    timeline, summary = jobs.parse_events(lines)

    assert summary["tool_calls"] > 0
    assert summary["models"] == ["glm-5.3-flash"]
    assert timeline[0].startswith("  开  init  model=glm-5.3-flash")

    # 反面：改前那条读法在同一份文件上把时间线读没了（2096 行乱码 / 0 次工具调用）
    old_lines = _historical_lines(REAL_LOG)
    _old_timeline, old_summary = jobs.parse_events(old_lines)
    assert len(old_lines) > len(lines)
    assert old_summary["tool_calls"] == 0
    assert old_summary["models"] == []


# ---------------------------------------------------------------- 对等钉子：harness 复制体

def test_harness_logcodec_agrees_with_tools(tmp_path: Path) -> None:
    """`harness/logcodec.py` 是复制体（该目录不依赖 `tools/`）—— 四种编码下两边必须逐字节相等。"""
    harness = _by_path("e75_harness_logcodec", ROOT / "harness" / "logcodec.py")
    jobs = _jobs()
    text = _text()

    variants = {
        "utf8-noBOM": text.encode("utf-8"),
        "utf8-BOM": b"\xef\xbb\xbf" + text.encode("utf-8"),
        "utf16le-BOM": b"\xff\xfe" + text.encode("utf-16-le"),
        "utf16be-BOM": b"\xfe\xff" + text.encode("utf-16-be"),
    }
    for name, data in variants.items():
        path = _write(tmp_path, f"{name}.jsonl", data)
        assert harness.log_codec(data) == jobs.log_codec(data), name
        assert harness.read_log_lines(path) == jobs.read_log_lines(path), name

    bad = _write(tmp_path, "nul-noBOM.jsonl", b"abc\x00def")
    with pytest.raises(harness.UnknownLogEncodingError):
        harness.read_log_lines(bad)
    with pytest.raises(jobs.UnknownLogEncodingError):
        jobs.read_log_lines(bad)
