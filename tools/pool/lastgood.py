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
- （**卡 E139 已改**）多进程互斥 ← `internal/filelock` 的 `Mutex` / `Wait`
  pool 是 `O_CREAT|O_EXCL` 自旋锁；**等不到就失败关闭**（`GatePoolBusy` /
  `QueueBusy`），不再「等满照样往下写」（卡 E139 推翻 E55 `:48-49` 那条禁令）。

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

## 卡 A356 加的四个能力（照 magpie `internal/edit/file.go` / `internal/lastgood`）

- **坏文件先旁存**（`keep_bad` / `describe_bad` ← `KeepBad`，`lastgood.go:165-218`）：
  旧文件坏了，它的字节落成 `<名>.bad-<stamp>`（权限 `0o600`、`O_EXCL` 建），`.bak` 原样不动。
  从前是「坏的一不进 `.bak` 二不旁存，就悄悄没了」—— 场景 A 的缺陷。
- **BOM / 权限位 / 换行原样保留**（`keep_bom` / `keep_mode` / `follow_ending`）
  ← `keepBOM`（`file.go:58-77`）、`tmp.Chmod(mode)`（`:151-154`）、
  `joinLinesLike`（`text.go:109-115`）。
- ★ **与 magpie 的一处有意不同**：`KeepBad` 失败在 magpie 里会让整趟写盘失败（`file.go` 的
  `Keep` 返回 err）；这里 `keep_bad` **不抛**（用尽名字返回 `None`）。理由：pool 的写盘点有
  3 处是拒运行键路径（吊销标记 / 额度刷新 / 签到留档），「旁存不了就让整条链停摆」比丢一份
  坏字节更糟。这条差异是**选的**，不是漏的。
- ★ **不做**的两件事，因为不在本卡边界内：①不加 `fsync`（magpie 的 `steady.Sync` 防的是
  「断电留全零文件」#1505，pool 侧**没有防住**，如实记在卡的缺口 4）；②不处理
  `target.is_symlink()`（magpie 有 `Target()` 先指真身，这里会把链接替换成普通文件，缺口 6）。

★ 只用标准库（不许第三方依赖）。★ 换行走内建 `open()` 的 `newline=`：`Path.write_text(newline=)`
是 Python 3.13+ 才有的参数，云机跑 3.12（卡 E59 的坑，别踩）。
"""

from __future__ import annotations

import contextlib
import errno
import os
import stat
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 只在注解里用（本文件已开 `from __future__ import annotations`）
    from collections.abc import Callable

#: 备份后缀：`<正式文件名>.bak`（同目录）。
BACKUP_SUFFIX = ".bak"

#: 坏文件旁存的后缀：`<正式文件名>.bad-<stamp>`（同目录）。
BAD_SUFFIX = ".bad-"

#: 旁存名的时刻格式 —— 逐字照 `internal/lastgood/lastgood.go:170` 的 `"20060102-150405"`。
BAD_STAMP = "%Y%m%d-%H%M%S"

#: 旁存文件的权限位 —— 逐字照 `lastgood.go:179` 的 `os.OpenFile(..., 0o600)`。
BAD_PERM = 0o600

#: 新文件的默认权限位 —— 逐字照 `internal/edit/file.go:151` 的 `fs.FileMode(0o644)`。
DEFAULT_PERM = 0o644

#: 同秒冲突最多试几个名 —— 照 `lastgood.go:171` 的 `for i := 1; i < 1000; i++`。
MAX_BAD_NAMES = 1000

#: UTF-8 BOM（`file.go:58-77` 的 `bom`）。
BOM = b"\xef\xbb\xbf"

#: `os.replace` 的有界重试次数与退避基数（第 i 次等 `REPLACE_BASE_S * (i + 1)` 秒）。
#: ★ 卡 E139：口径照抄 `tools/pool/ledger.py:87-91`。Windows 上 `os.replace` 与并发读者
#: 互撞抛 `PermissionError [WinError 5]` —— 实测 20000 B 队列文件带 1 个并发读者时
#: **103/200** 次首试失败。重试**不是零失败**（读者 2 个、`tries=10` 时仍 64/120 失败）。
REPLACE_TRIES = 5
REPLACE_BASE_S = 0.02


class LastgoodError(RuntimeError):
    """写盘失败（有界重试都试过了）—— 消息带「原子写失败（N 次）」+ 路径 + errno 名。"""


def _err_name(exc: BaseException | None) -> str:
    """异常的可读名（Windows 错误码翻成符号名，便于日志里认）—— 照 `ledger.py:624-635`。"""
    if exc is None:
        return "?"
    code = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
    if code is None:
        return type(exc).__name__
    try:
        return f"{type(exc).__name__}({errno.errorcode.get(int(code), code)})"
    except (ValueError, TypeError):
        return type(exc).__name__


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


def _replace_retry(tmp: Path, target: Path, *,
                   tries: int = REPLACE_TRIES,
                   base: float = REPLACE_BASE_S) -> None:
    """`os.replace(tmp, target)` 的**有界**重试（照 `tools/pool/ledger.py:335-358` 的口径）。

    ★ 为什么要重试：Windows 上 `os.replace` 与并发读者互撞，实测 20000 B 队列文件带
      1 个并发读者时 **103/200** 次抛 `PermissionError [WinError 5]`。不重试就等于
      「写着写着偶尔抛异常」，而抛在读改写锁里会把这一趟一起带走。
    ★ 只对 `PermissionError` 重试；别的 `OSError` 立刻抛（盘满了重试也没用）。
    ★ `tries <= 1` ⇒ 单次尝试（反向变异靠它把重试撤掉，判据 3 的钉子咬这一条）。
    ★ 重试**不是零失败**：读者 2 个、`tries=10/base=0.05` 时实测仍 64/120 失败 ——
      这里只承诺「有界重试 + 仍失败才抛且文案说清」，**不**承诺以后再也不会抛。
    """
    last: BaseException | None = None
    for i in range(max(1, tries)):
        try:
            os.replace(tmp, target)
            return
        except PermissionError as exc:  # 只在 Windows 上与并发读者 / 杀软相撞
            last = exc
            if i + 1 < tries:
                time.sleep(base * (i + 1))
    raise LastgoodError(f"原子写失败（{max(1, tries)} 次）：{target}：{_err_name(last)}")


def _copy_bytes_atomic(source: Path, target: Path, *,
                       tries: int = REPLACE_TRIES,
                       base: float = REPLACE_BASE_S) -> None:
    """把 `source` 的字节整份顶成 `target`：先写 tmp 再 `os.replace`（不许半个 `.bak`）。

    ★ 卡 E139：`os.replace` 走 `_replace_retry` —— 实测 `timeout=0.0` 的 12 线程压测里，
      这一处独占 21/37 次 `PermissionError`（只给正式文件那处加重试会漏掉它）。
    """
    raw = source.read_bytes()
    tmp = _tmp_path(target)
    with _unlink_on_error(tmp):
        tmp.write_bytes(raw)
        _replace_retry(tmp, target, tries=tries, base=base)


# ---------------------------------------------------------------------------
# 坏文件旁存（卡 A356）← internal/lastgood 的 KeepBad
# ---------------------------------------------------------------------------


def describe_bad(raw: bytes | None) -> str:
    """坏在哪 —— 逐字照 `lastgood.go:93-103` 的 `describe`。

    三支：`None` ⇒ `it doesn't parse`；全零字节 ⇒ `"<N> bytes, every one zero"`
    （断电留下的全零文件 #1505 就长这样，认出来才能让人一眼看懂）；只有空白 ⇒ `it is empty`；
    其余 ⇒ `it doesn't parse`。
    """
    if raw is None:
        return "it doesn't parse"
    if len(raw) > 0 and len(raw.strip(b"\x00")) == 0:
        return f"{len(raw)} bytes, every one zero"
    # 空白判据照 `bytes.TrimSpace`（Go 认 unicode 空白）⇒ 先解码再 `str.strip()`。
    if not raw.decode("utf-8", "replace").strip():
        return "it is empty"
    return "it doesn't parse"


def _now() -> datetime:
    """当前时刻（`keep_bad` 的注入点：钉子用固定 `now` 逼出同秒冲突）。"""
    return datetime.now()


def _kept_already(target: Path, raw: bytes) -> Path | None:
    """这份坏字节是不是已经旁存过（按长度 + 字节比）—— 照 `lastgood.go:207-218` 的
    `keptAlready`。"""
    prefix = target.name + BAD_SUFFIX
    try:
        entries = sorted(target.parent.iterdir())
    except OSError:
        return None
    for cand in entries:
        if not cand.name.startswith(prefix):
            continue
        try:
            if cand.stat().st_size != len(raw):
                continue
            if cand.read_bytes() == raw:
                return cand
        except OSError:
            continue
    return None


def keep_bad(target: Path, raw: bytes, *, now: datetime | None = None) -> Path | None:
    """把坏字节旁存成 `<名>.bad-<stamp>`，返回那个路径；**不抛**（用尽名字返回 `None`）。

    照 `lastgood.go:165-205` 的 `KeepBad`，只改一处：**不抛**。magpie 的 `KeepBad` 失败会让
    整趟写盘失败（`file.go` 的 `Keep` 把 err 往上返）；这里「旁存不了」不许挡住写盘 ——
    写盘点里有 3 处是拒运行键路径（吊销标记 / 额度刷新 / 签到留档），停摆比丢一份坏字节更糟。

    去重先于编号：同样的字节（长度 + 逐字节比）已经存过 ⇒ 返回**已有的**那个路径，不再存第二份。
    同秒冲突往后加 `-2`、`-3`…，最多 `MAX_BAD_NAMES` 个名（照 `lastgood.go:171`）。
    """
    target = Path(target)
    already = _kept_already(target, raw)
    if already is not None:
        return already
    stamp = (now or _now()).strftime(BAD_STAMP)
    base = f"{target.name}{BAD_SUFFIX}{stamp}"
    for i in range(1, MAX_BAD_NAMES + 1):
        name = base if i == 1 else f"{base}-{i}"
        cand = target.parent / name
        try:
            # `xb` = `O_CREAT|O_EXCL`：同秒撞名绝不覆盖（照 `lastgood.go:179` 的 `os.O_EXCL`）。
            with open(cand, "xb") as fh:
                fh.write(raw)
        except FileExistsError:
            continue
        except OSError:
            return None  # ★ 不抛：旁存不了也让写盘继续
        # 权限位照 `lastgood.go:179` 的 `0o600`。Windows 上 os.chmod 只认只读位（实测），
        # 调了不一定生效 —— 与 magpie 在 Windows 上的实际效果同型，不额外补偿。
        with contextlib.suppress(OSError):
            os.chmod(cand, BAD_PERM)
        return cand
    return None  # 名字用尽（`lastgood.go:202` 那句「no free name」）——仍不抛


def _has_bom(path: Path) -> bool:
    """原文件头三个字节是不是 UTF-8 BOM（照 `file.go:69-76` 的读头比对）。"""
    try:
        with open(path, "rb") as fh:
            return fh.read(len(BOM)) == BOM
    except OSError:
        return False


def _mode_of(path: Path) -> int | None:
    """原文件的权限位；读不到 ⇒ `None`（调用方退回 `DEFAULT_PERM`）。"""
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return None


def _ending_of(path: Path) -> str:
    """原文件的换行：**纯 CRLF** 才返回 `"\\r\\n"`，其余一律 `"\\n"`。

    ★ 判据逐字照 `text.go:109-115` 的 `joinLinesLike`：
    `n := strings.Count(orig, "\\n"); n > 0 && strings.Count(orig, "\\r\\n") == n`。
    混合换行（1 个 CRLF + 1 个 LF）**不算**纯 CRLF —— 写成 `crlf > 0` 就会把混合文件整份改成
    CRLF，钉子 11 咬的正是这个方向。
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return "\n"
    crlf = raw.count(b"\r\n")
    if crlf > 0 and crlf == raw.count(b"\n"):
        return "\r\n"
    return "\n"


def write_atomic(
    target: Path,
    text: str,
    *,
    newline: str | None = "\n",
    validate: Callable[[str], None] | None = None,
    keep_bom: bool = True,
    keep_mode: bool = True,
    follow_ending: bool = False,
    tries: int = REPLACE_TRIES,
    base: float = REPLACE_BASE_S,
) -> None:
    """原子写：①旧的好就顶成 `.bak`、坏的旁存成 `.bad-*` ②写 tmp ③`os.replace`。

    任一步失败清掉 tmp 再抛（`keep_bad` 例外：它自己吞，见其 docstring）。

    `validate(text)` 用来判「旧的这份还能不能当 lastgood」；传 `None` 时只要求读得出来
    且非空（调用方知道格式就传一个 —— 坏字节不许进 `.bak`）。

    三个保留位（卡 A356；默认值都**不改**字节内容）：
    - `keep_bom=True`：原文件带 UTF-8 BOM ⇒ 新文件也带（照 `file.go:58-77` 的 `keepBOM`）。
    - `keep_mode=True`：沿用原文件权限位；原文件不存在 ⇒ `DEFAULT_PERM`（照 `file.go:151-154`）。
    - `follow_ending=False`：**默认不跟**原文件的换行（本仓还没定仓级换行策略，见卡 A356 缺口 2）；
      传 `True` 且原文件是**纯 CRLF** ⇒ 用 `"\\r\\n"`，否则仍用调用方给的 `newline`
      （照 `text.go:109-115` 的 `joinLinesLike`）。

    `tries` / `base`（卡 E139）：`os.replace` 的有界重试，照 `tools/pool/ledger.py` 的口径 ——
    只对 `PermissionError` 重试，其它 `OSError` 立刻抛，`tries <= 1` ⇒ 单次尝试。两处
    `os.replace`（`.bak` 那一份拷贝 + 正式文件这一次）都走它。重试用完仍失败 ⇒ 抛
    `LastgoodError`（消息是「原子写失败（N 次）」+ 路径 + 最后一次的 errno 名），
    tmp 由 `_unlink_on_error` 清掉。★ 重试**不是零失败**，见 `_replace_retry` 的 docstring。
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    if existed:
        if _is_good(target, validate):
            _copy_bytes_atomic(target, backup_path(target), tries=tries, base=base)
        else:
            # ★ 坏的先旁存（`.bak` 原样不动）。`keep_bad` 自己吞异常，这里再兜一层
            # 「读原字节就失败了」——旁存不了也**不许**挡住写盘。
            with contextlib.suppress(Exception):
                keep_bad(target, target.read_bytes())
    bom = bool(keep_bom and existed and text and not text.startswith("\ufeff") and _has_bom(target))
    mode = _mode_of(target) if existed else DEFAULT_PERM
    if follow_ending and _ending_of(target) == "\r\n":
        newline = "\r\n"
    tmp = _tmp_path(target)
    with _unlink_on_error(tmp):
        # ★ 换行走内建 open 的 newline=（Path.write_text 的 newline= 是 3.13+，云机跑 3.12）。
        with open(tmp, "w", encoding="utf-8", newline=newline) as fh:
            if bom:
                fh.write("\ufeff")
            fh.write(text)
        if keep_mode and mode is not None:
            os.chmod(tmp, mode)
        _replace_retry(tmp, target, tries=tries, base=base)


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

    ★ 「文件不存在也看 `.bak`」是**故意**的（A330 的决定，`tests/test_pool_lastgood.py:132` 钉住），
      magpie 的 `Read`（`lastgood.go:63-78`）语义相反 —— 本卡**不许**顺手翻掉。
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
