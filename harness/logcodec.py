r"""工人日志的**读法**（就地实现；卡 E75）。

为什么这份是**复制体**、不是 `from pool.jobs import read_log_lines`：`harness/README.md` 的
硬规矩是复制体**不依赖 `tools/`**（不挂 `sys.path`、不 import `tools/` 或 `pool/`，卡 205 选①）。
所以 `tools/pool/jobs.py` 与本文件各有一份，靠 `tests/test_log_codec.py` 的**对等钉子**
（同一份输入，两边 `lines` 逐字节相等，覆盖 UTF-16LE-BOM / UTF-16BE-BOM / UTF-8-BOM / 纯 UTF-8
四种）钉住 —— 只改一边的 BOM 判定顺序，那条钉子就会红。

**防什么**：`gates/diag/wb-045.jsonl` 是 UTF-16LE 带 BOM。按 UTF-8 读（`errors="replace"` 让解码
永不失败）会读出 2096 行乱码、`tool_calls` 0、`models` 空 —— **整条时间线静默消失**，
比没有窗更坏。编码要**判出来**（看 BOM），不是**试出来**（失败再退回 utf-8 重试）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

#: 顺序有意义：先 utf-16 的两个，再 utf-8 的（`ff fe` 不是 `fe ff` 的前缀，但顺序仍要定死）。
BOM_CODECS: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
)


class UnknownLogEncodingError(ValueError):
    """没有 BOM、又不像 UTF-8 的日志 —— **不猜**，让调用方看见（判据 4）。"""


def log_codec(data: bytes) -> str:
    """按 **BOM** 判编码；无 BOM ⇒ 必须是合法 UTF-8，否则抛 `UnknownLogEncodingError`。"""
    for bom, codec in BOM_CODECS:
        if data.startswith(bom):
            return codec
    if b"\x00" in data:
        raise UnknownLogEncodingError(
            f"没有 BOM，但字节里带 NUL —— 像 UTF-16/32 又没 BOM，不猜编码（{len(data)} 字节）")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UnknownLogEncodingError(
            f"没有 BOM，也不是合法的 UTF-8（{exc.reason} @ 第 {exc.start} 字节）—— "
            "不猜编码：要么在源头写对，要么给这份日志补 BOM") from exc
    return "utf-8"


def read_log_lines(path: Path) -> list[str]:
    """先读**字节**、按 BOM 判编码、剥掉 BOM、再 `splitlines()`。

    `errors="replace"` 留着只治"坏几个字节就读不下去"，不治编码 —— 编码由 `log_codec` 判。
    """
    data = path.read_bytes()
    codec = log_codec(data)
    for bom, _ in BOM_CODECS:
        if data.startswith(bom):
            data = data[len(bom):]
            break
    return data.decode(codec, errors="replace").splitlines()
