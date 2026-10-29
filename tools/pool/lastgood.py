r"""写盘纪律（卡 A330 · `T-AG532`）：原子替换 + `.bak` 落后一次 + fail-closed 读。

## 每条纪律对应 magpie 的哪个包

- `write_atomic` ← `internal/steady` 的 `Rename`
  一律 `writePrivate` + 同目录临时文件 + rename：读者只看到**旧整份**或**新整份**。
- `backup_path` / `.bak` ← `internal/lastgood` 的 `Write`
  `.bak` **故意落后一次写**：写新的之前，把**旧的**顶成 `.bak`（不是写完再备份新的）。
- `read_with_fallback` ← `internal/lastgood` 的 `Read` / `Fallback`
  冷启动读不了正式文件就读 `.bak`；**恢复必须记日志**。
- `read_strict` ← F77 的 `caller-keys.json` 纪律
  「撤过的凭据不许复活」的文件**从不**读 `.bak`，读不了就拒（fail-closed）。
- （**本卡不动**）多进程互斥 ← `internal/filelock` 的 `Mutex` / `Wait`
  pool 现在是 `O_CREAT|O_EXCL` 自旋锁、**等满照样往下写**；改它要动并发语义，另开一张卡。

## 为什么单独一个模块

五处写盘（`pool.registry` / `pool.task` / `pool.queue` / `pool_accounts` / `gate_pool`）
原先各写一套「tmp + `os.replace`」，`.bak` 一处都没有：登记文件读到半截就整条链停摆，
而且没人知道「上一份好的是什么」。判据只写一遍，五处都调这里。

## 三条硬规矩

1. **坏文件不许当 lastgood**：正式文件解析不了（`validate` 抛）⇒ 它的字节**不进** `.bak`，
   否则「上一份好的」被坏字节顶掉，兜底就是假的。
2. **`.bak` 落后一次写**：写 B 之前把 A 顶成 `.bak`，所以冷启动至多丢**一次**写。
3. **恢复要留痕**：从 `.bak` 读成功**必须**调 `log(...)` —— 静默恢复等于把
   「账本被写坏过」这件事藏起来。

★ 只用标准库（不许第三方依赖）。★ 换行走内建 `open()` 的 `newline=`：`Path.write_text(newline=)`
是 Python 3.13+ 才有的参数，云机跑 3.12（卡 E59 的坑，别踩）。
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 只在注解里用（本文件已开 `from __future__ import annotations`）
    from collections.abc import Callable

#: 备份后缀：`<正式文件名>.bak`（同目录）。
BACKUP_SUFFIX = ".bak"


def backup_path(target: Path) -> Path:
    """`.bak` 的路径：同目录、同文件名后面加 `.bak`（不做 `.json` → `.bak` 那种变形）。"""
    target = Path(target)
    return target.with_name(target.name + BACKUP_SUFFIX)


def _tmp_path(target: Path) -> Path:
    """同目录的唯一临时名（以 `.tmp` 结尾 —— 既有钉子用 `glob("*.tmp")` 核「没留渣」）。"""
    fd, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    os.close(fd)
    return Path(name)


@contextlib.contextmanager
def _unlink_on_error(tmp: Path):
    """失败路径：把临时文件清掉再抛（成功路径由 `os.replace` 把 tmp 消掉）。"""
    try:
        yield
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def _is_good(target: Path, validate: Callable[[str], None] | None) -> bool:
    """旧文件能不能当 lastgood：读不出来 / 空 / `validate` 抛 ⇒ 不能（坏的不许进 `.bak`）。"""
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    if not text.strip():
        return False
    if validate is not None:
        try:
            validate(text)
        except Exception:
            return False
    return True


def _copy_bytes_atomic(source: Path, target: Path) -> None:
    """把 `source` 的字节整份顶成 `target`：先写 tmp 再 `os.replace`（不许半个 `.bak`）。"""
    raw = source.read_bytes()
    tmp = _tmp_path(target)
    with _unlink_on_error(tmp):
        tmp.write_bytes(raw)
        os.replace(tmp, target)


def write_atomic(
    target: Path,
    text: str,
    *,
    newline: str = "\n",
    validate: Callable[[str], None] | None = None,
) -> None:
    """原子写：①旧的好就顶成 `.bak` ②写 tmp ③`os.replace`。任一步失败清掉 tmp 再抛。

    `validate(text)` 用来判「旧的这份还能不能当 lastgood」；传 `None` 时只要求读得出来
    且非空（调用方知道格式就传一个 —— 坏字节不许进 `.bak`）。
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and _is_good(target, validate):
        _copy_bytes_atomic(target, backup_path(target))
    tmp = _tmp_path(target)
    with _unlink_on_error(tmp):
        # ★ 换行走内建 open 的 newline=（Path.write_text 的 newline= 是 3.13+，云机跑 3.12）。
        with open(tmp, "w", encoding="utf-8", newline=newline) as fh:
            fh.write(text)
        os.replace(tmp, target)


def _read_checked(target: Path, validate: Callable[[str], None]) -> str:
    """读 + 验：读不出来 / 空 / `validate` 抛 ⇒ 原样抛（不吞、不返回空串）。"""
    text = target.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"文件是空的：{target}")
    validate(text)
    return text


def _merged_error(first: BaseException, second: BaseException, bak: Path) -> BaseException:
    """两边都坏时抛什么：消息带「`.bak` 也坏了」，能从同类型复刻就复刻（保住异常类型）。"""
    message = f"{first}；.bak 也坏了（{bak}）：{second}"
    try:
        return type(first)(message)
    except Exception:  # pragma: no cover —— 少数异常类不吃单参构造（如 json.JSONDecodeError）
        return first


def read_with_fallback(
    target: Path,
    *,
    validate: Callable[[str], None],
    log: Callable[[str], None] | None = None,
) -> tuple[str, bool]:
    """先读正式的；读不了（缺失 / 空 / 坏）就读 `.bak`。

    返回 `(text, 是否从 .bak 恢复)`。恢复成功**必须**调 `log("从 .bak 恢复：<path>（<原因>）")`；
    两边都坏 ⇒ 抛第一条错误（消息里带上「`.bak` 也坏了」），**不吞、不返回空串**。
    """
    target = Path(target)
    try:
        return _read_checked(target, validate), False
    except Exception as first:
        reason = first
    bak = backup_path(target)
    try:
        text = _read_checked(bak, validate)
    except Exception as second:
        raise _merged_error(reason, second, bak) from reason
    if log is not None:
        log(f"从 .bak 恢复：{target}（{reason}）")
    return text, True


def read_strict(target: Path, *, validate: Callable[[str], None]) -> str:
    """只读正式文件，**永不**看 `.bak`（凭据账本这类「撤过的凭据不许复活」的文件）。"""
    target = Path(target)
    text = target.read_text(encoding="utf-8")
    validate(text)
    return text
