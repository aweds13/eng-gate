r"""换行保真读写 `tools/read_write.py`（卡 E59 · T-AG517）—— **唯一实现**。

## 为什么有它

`Path.read_text(newline=...)` / `Path.write_text(newline=...)` 这两个关键字参数是
**Python 3.13 才加的**。云门禁机跑 **3.12.8**，本机跑 **3.14.6** ⇒ 任何用 `newline=` 的代码
在本机绿、在云机 `TypeError: Path.read_text() got an unexpected keyword argument 'newline'`。

实测（本卡）：云门禁 B-20261052 第一趟，11 条用例因这一个参数同时红，`pytest` 门与
`pytest_chain` 门双双失守。这类缺陷**本机永远看不见** —— 只能靠云机或低版本解释器暴露。

## 口径

**不自己实现换行翻译**，直接委托内置 `open()` —— 它从 Python 3 起就支持 `newline=`，
语义与 3.13 的 `Path.read_text(newline=)` **逐字节一致**（3.13 的 pathlib 也只是转手给
`io.open`）。重写一份翻译逻辑只会引入偏差：实测 `write_text(newline="\n")` 的真实语义是
「**只**把 `\n` 翻成 `\n`、`\r` 原样保留」，与「把所有行尾归一」不是一回事。

| 参数 | 读 | 写 |
|---|---|---|
| `None`（默认） | 三种行尾全归一成 `\n` | `\n` → `os.linesep`（Windows 上是 `\r\n`） |
| `""` | 不翻译（原样） | 不翻译（原样） |
| `"\n"` / `"\r\n"` | 不翻译（按该串断行，行尾不翻译） | `\n` → 该串，`\r` 原样保留 |

字节保真（`.gitignore` 这类 CRLF/LF 混合文件）用 `newline=""`。

## 用法

```python
from read_write import read_text, write_text   # tools/ 在 sys.path 里时

src = read_text(path, newline="")              # 保真读
write_text(path, src, newline="")              # 保真写回
```
"""

from __future__ import annotations

import builtins
import pathlib

__all__ = ["read_text", "write_text"]


def read_text(
    path: str | pathlib.Path,
    encoding: str = "utf-8",
    errors: str | None = None,
    newline: str | None = None,
) -> str:
    """读文本；`newline` 语义同 `open(..., newline=...)`（3.13 之前 `pathlib` 没有它）。"""
    kwargs: dict[str, object] = {"encoding": encoding, "newline": newline}
    if errors is not None:
        kwargs["errors"] = errors
    with builtins.open(pathlib.Path(path), **kwargs) as f:  # type: ignore[arg-type]
        return f.read()


def write_text(
    path: str | pathlib.Path,
    text: str,
    encoding: str = "utf-8",
    errors: str | None = None,
    newline: str | None = None,
) -> int:
    """写文本；`newline` 语义同 `open(..., newline=...)`。

    返回写入的**字符**数（同 `Path.write_text`）。
    """
    kwargs: dict[str, object] = {"encoding": encoding, "newline": newline}
    if errors is not None:
        kwargs["errors"] = errors
    with builtins.open(pathlib.Path(path), "w", **kwargs) as f:  # type: ignore[arg-type]
        return f.write(text)
