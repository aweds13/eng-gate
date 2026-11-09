r"""台账（`docs/workbacklog.toml`）的**唯一写入口** + 立卡那一笔的短事务（卡 E81 · T-AG586）。

## 为什么要这个模块

`docs/workbacklog.toml` 只有一处生产写方：`tools/pool/landing.py` 的
`flip_card_status()`，做法是**整文件 read-modify-write**，无锁、无 CAS。
立卡则连生产代码都没有 —— 只有 `gates/diag/_add_card.py`（硬编码绝对路径、
子串判幂等、住在 gitignore 里）。实测后果：

* 4 个进程并发跑同一形状的读改写 ⇒ 四个都 exit 0，**静默丢 3 张卡**；
* 原型立卡器拆掉锁后 8 进程连跑 4 轮，**每轮丢 3–4 张**；带锁 3 轮都 8/8；
* 真实事故：2026-11-02 20:36 另一会话落地失败后手工 `git reset --hard`，
  把主控刚写进台账的条目一起扫掉。

## 这个模块做什么、不做什么

做的：把「拿锁 → 读字节 → 切块 → 查重 → 尾部追加 → 原子写（带重试）→ 放锁」
包成约 160 ms 的短事务，并给落地链的 status 翻写提供同一个 `write_atomic`。

不做的（故意的）：**块的格式、块序、字节一律不变**。
本模块不重新渲染 TOML —— 它把新块当作字节**追加**到目标文件尾，
所以现有所有读者（`tools/pool/plan.py` 的 `load_backlog()` 等）都不用改一行。
这条纪律由 `tests/test_ledger_lock.py` 的逐字节前缀判据钉住。

★ 卡 E89（T-AG596）：台账**启用分片**后目标文件会变 —— 新卡按分区落
  `docs/backlog/<分区>.toml`（`wb_plan.shard_file_for()` 判），分片目录还空着
  或卡号形态判不出分区 ⇒ 落总表（**不猜**）。判据只有一份，就在 `wb_plan` 里。

## 锁的三条纪律（缺一条就在 Windows 上漏锁）

1. **不读别人的锁文件内容**：只 `stat()` 拿 mtime。实测在 Windows 上
   读别人的锁文件会与持有者的 `unlink()` 撞，把对方的锁顶掉。
2. **释放重试到成功，不吞异常**：`tools/pool/task.py` 的
   `with suppress(OSError): lock.unlink()` 是反例，4 进程实测会残留锁。
3. **等不到就失败关闭**：超时抛 `LedgerBusyError`，绝不「等满就拿无锁写」
   （`tools/pool/queue.py` 的 `break` 是反例）。
4. **`PermissionError` 也当「有人在写」**：Windows 上持有者正在 `unlink()`
   的那一瞬，`O_CREAT|O_EXCL` 抛的是 `PermissionError [WinError 5]` 而不是
   `FileExistsError`（实测 8 写者连跑第 2 轮就撞一次）。当成「这一刻有人占着」
   轮询重试；真 ACL 拒绝时由 deadline 兜住、失败关闭。

## 已知边界（别让人误以为它能包住一切）

* 锁在 `gates/diag/ledger.lock` ⇒ **跨机器不互斥**。本仓是单机多会话，
  够用；将来多机要换分布式锁。
* 锁与 `gates/diag/gate_lock.py` 的 `gates*.lock` **互不干扰**：
  那把按 `TF_GATE_PORT_BASE` 分段，这把**故意不看端口段**（台账只有一份）。
* 提交后仍可能被 `git reset --hard` 回到旧 HEAD —— 那是 git 语义，
  属纪律问题：**主树禁止 `git reset --hard`**（写进 `skills/pipe-card/`）。
"""
from __future__ import annotations

import contextlib
import errno
import os
import pathlib
import re
import subprocess
import sys
import time

import tomllib

from pool.no_window import NO_WINDOW

#: 锁文件名。**故意**用 `ledger.lock` 而不是 `gates*.lock`：
#: `gates/diag/gate_lock.py` 的 `all_lock_paths()` 只 glob `gates*.lock`，
#: 这把锁因此不会出现在门禁锁的「谁占着」清单里，也不会被它清理。
LOCK_NAME = "ledger.lock"

#: 租约秒数。进程崩掉后，别人最多等这么久就能接管（只按 mtime 判，不读内容）。
LOCK_TTL_S = 120.0

#: 默认等待秒数。等不到就 `raise LedgerBusyError`（失败关闭）。
LOCK_WAIT_S = 30.0

#: 轮询间隔。5 ms ⇒ 160 ms 的事务最多 32 次探测，开销可忽略。
POLL_S = 0.005

#: 释放锁的重试次数。Windows 上 `unlink` 会与别人的 `stat` 短暂相撞。
RELEASE_TRIES = 400

#: 原子写的 `os.replace` 重试次数与退避基数（第 n 次等 `REPLACE_BASE_S * n` 秒）。
#: 实测 154738 B 台账带并发读者时**首试失败 421/500（84%）**，
#: 退避后 500/500 成功；所以这里不是保险，是必需。
REPLACE_TRIES = 5
REPLACE_BASE_S = 0.02

#: 台账相对主仓根的路径（只用于拼路径与提示，不参与解析）。
BACKLOG_REL = "docs/workbacklog.toml"

#: 队列卡数所在的派生文档，与它的**唯一**生成器（卡 E100）。
#: ★ 这里不算卡数、也不解析台账：重算只走生成器一份真源。
README_REL = "docs/subsystems/pool/README.md"
POOL_README_GEN = "scripts/gen_pool_readme.py"

_KV = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
_CARD_HEAD = b"[[cards]]"


class LedgerError(RuntimeError):
    """台账操作失败（内容或形状不对，**没写盘**）。"""


class LedgerBusyError(LedgerError):
    """等不到锁，或放锁失败 —— 一律失败关闭，调用方不许当成成功。"""


# --------------------------------------------------------------------------- 根与锁
def main_root(start: pathlib.Path | str | None = None) -> pathlib.Path:
    r"""主仓根：在卡树（worktree）里跑也返回**主树**。

    照抄 `gates/diag/gate_lock.py:main_root()`：worktree 的 `.git` 是个文件，
    `--git-common-dir` 指回主仓的 `.git` 目录 ⇒ 取它的 parent 就是主仓根。
    git 都不认（不是仓库：裸目录夹具、非仓库树）时**退化成本身** ——
    `flip_card_status` 早就能在非仓库树上跑，加锁不许把这个前提变成新要求。
    退化而不是「跳过加锁」：写盘只有一份（判据 9），跳锁等于留第二条写路径。
    """
    cwd = pathlib.Path(start) if start is not None else pathlib.Path.cwd()
    common = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common:
        return pathlib.Path(common).resolve().parent
    top = _git(cwd, "rev-parse", "--show-toplevel")
    if top:
        return pathlib.Path(top).resolve()
    return cwd.resolve()


def _git(cwd: pathlib.Path, *args: str) -> str:
    r"""跑一条 git 命令，成功回 stdout（去空白），失败回空串。"""
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace", **NO_WINDOW,
    )
    return (proc.stdout or "").strip() if proc.returncode == 0 else ""


def lock_dir(root: pathlib.Path | None = None) -> pathlib.Path:
    r"""锁目录 `gates/diag/` —— 不存在就建（那是 scratch 目录，git 不跟踪）。"""
    base = (root or main_root()) / "gates" / "diag"
    base.mkdir(parents=True, exist_ok=True)
    return base


def lock_path(root: pathlib.Path | None = None) -> pathlib.Path:
    r"""锁文件绝对路径。

    ★ **不看 `TF_GATE_PORT_BASE`**（与 `gate_lock.py` 按端口段分把相反）：
      台账只有一份，两个端口段上的两个会话必须互斥 —— 这是本卡判据 4。
    """
    return lock_dir(root) / LOCK_NAME


def backlog_path(root: pathlib.Path | None = None) -> pathlib.Path:
    r"""台账绝对路径。"""
    return (root or main_root()) / BACKLOG_REL


def acquire(path: pathlib.Path | None = None, *, wait: float = LOCK_WAIT_S,
            ttl: float = LOCK_TTL_S) -> pathlib.Path:
    r"""拿锁，返回锁文件路径；等不到抛 `LedgerBusyError`（卡 E81 判据 5）。

    `O_CREAT | O_EXCL` 建锁文件是原子操作；已存在 ⇒ 只 `stat()` 看 mtime：
    比 `ttl` 更老就当持有者已死、`unlink` 后接手。

    ★ 三条纪律见模块 docstring —— 尤其**不要**为了「看清楚谁占着」去读锁内容。
    """
    target = pathlib.Path(path) if path is not None else lock_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(0.0, wait)
    while True:
        try:
            fd = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except PermissionError:
            # ★ Windows 专有：持有者正在 `unlink()` 的那一瞬，`O_EXCL` 建锁撞的是
            #   `PermissionError [WinError 5]`，不是 `FileExistsError`（实测 8 写者
            #   连跑第 2 轮就有一个进程这样退 1）。语义与「锁还在」相同 ⇒ 同路处理。
            #   若其实是 ACL 真拒绝，重试到 deadline 也必须失败关闭
            #   （★ 初版漏了这个判定：一直 `continue` 不看 deadline，真遇上就是无限循环 ——
            #    实测把整道 pytest 门顶到 1800 s 硬超时被掏）。
            if time.monotonic() >= deadline:
                raise LedgerBusyError(
                    f"拿不到台账锁 {target}（等了 {wait:.0f}s，建锁被拒）；"
                    "另一笔写入还占着。改小并发或稍后重试 —— 别绕过去无锁写。"
                ) from None
            time.sleep(POLL_S)
            continue
        except FileExistsError:
            try:
                age = time.time() - target.stat().st_mtime
            except FileNotFoundError:
                continue  # 刚好被释放，立刻重试（不计入等待）
            if age > ttl:
                with contextlib.suppress(FileNotFoundError, PermissionError):
                    target.unlink()
                continue
            if time.monotonic() >= deadline:
                raise LedgerBusyError(
                    f"等不到台账锁 {target}（等了 {wait:.0f}s）；另一笔写入还占着。"
                    "改小并发或稍后重试 —— 别绕过去无锁写。"
                ) from None
            time.sleep(POLL_S)
            continue
        os.close(fd)
        return target


def release(path: pathlib.Path | None = None) -> None:
    r"""放锁（重试到成功；仍失败抛 `LedgerBusyError`）。

    `FileNotFoundError` 算成功：锁已经不在 = 目的达成。
    """
    target = pathlib.Path(path) if path is not None else lock_path()
    for _ in range(RELEASE_TRIES):
        try:
            os.unlink(str(target))
        except FileNotFoundError:
            return
        except OSError:  # 只在 Windows 上与并发 stat/rename 相撞
            time.sleep(POLL_S)
            continue
        return
    raise LedgerBusyError(f"放不掉台账锁 {target}（重试 {RELEASE_TRIES} 次）；请人工看一眼")


class Hold:
    r"""`with Hold():` —— 拿锁/放锁的成对写法（放锁失败会抛出来，不吞）。"""

    def __init__(self, path: pathlib.Path | None = None, *,
                 wait: float = LOCK_WAIT_S, ttl: float = LOCK_TTL_S) -> None:
        self.path = pathlib.Path(path) if path is not None else lock_path()
        self.wait, self.ttl = wait, ttl

    def __enter__(self) -> pathlib.Path:
        return acquire(self.path, wait=self.wait, ttl=self.ttl)

    def __exit__(self, *_exc: object) -> None:
        release(self.path)


# --------------------------------------------------------------------------- 块与追加
def blocks_of(raw: bytes) -> list[list[bytes]]:
    r"""按 `[[cards]]` 把台账切成块（**行带行尾**，`b"".join` 可无损拼回）。

    与 `tools/pool/landing.py` 的 `_split_blocks()` + `_scan_blocks()` 同一口径：
    `raw.splitlines(keepends=True)` 只认 `\r\n` / `\n` / `\r`，
    所以「手写的裸 LF 块」不会被并进上一块（卡 E61 · T-AG519 的真事故）。
    块头与 `id` 行都可能带缩进 ⇒ 一律 `.strip()` 后比较。
    """
    out: list[list[bytes]] = []
    for line in raw.splitlines(keepends=True):
        if line.strip() == _CARD_HEAD:
            out.append([line])
        elif out:
            out[-1].append(line)
    return out


def card_id_of(block: list[bytes]) -> str | None:
    r"""块里 `id = "…"` 的值（取第一处；没有就 `None`）。"""
    for line in block:
        m = _KV.match(line.decode("utf-8", "replace").strip())
        if m and m.group(1) == "id":
            return m.group(2).strip().strip('"')
    return None


def has_card(raw: bytes, card_id: str) -> bool:
    r"""台账里是否已有这张卡（卡 E81 判据 2）。

    ★ **块级整行精确匹配** —— 不许子串判。`gates/diag/_add_card.py` 用
      `f'id = "{card}"' in text`，于是「加 A1 时 A11 已存在」会被判成已在，
      卡就凭空丢了。这里逐块取 `id` 再用 `==` 比。
    """
    return any(card_id_of(block) == card_id for block in blocks_of(raw))


def render_card(*, id: str, task: str, title: str, tree: str, spec: str,
                files: list[str] | tuple[str, ...],
                depends: list[str] | tuple[str, ...] = (),
                risk: str = "mid", status: str = "pending") -> bytes:
    r"""生成**新块**的字节（纯 CRLF，与仓里既有块同形）。

    缩进与键序照抄既有块：`[[cards]]` 顶格、`files = [` 每行两空格缩进、
    末项不带逗号；`depends` 在 `risk` 前，`status` 最后。
    """
    out = ["[[cards]]", f'id = "{id}"', f'task = "{task}"', f'title = "{title}"',
           f'tree = "{tree}"', f'spec = "{spec}"', "files = ["]
    out += [f'  "{f}",' for f in files]
    if files:
        out[-1] = out[-1][:-1]
    out.append("]")
    if depends:
        out.append("depends = [")
        out += [f'  "{d}",' for d in depends]
        out[-1] = out[-1][:-1]
        out.append("]")
    else:
        out.append("depends = []")
    out += [f'risk = "{risk}"', f'status = "{status}"']
    return ("\r\n".join(out) + "\r\n").encode("utf-8")


def splice_card(raw: bytes, block: bytes) -> bytes:
    r"""把一块**追加**到台账尾部（只加字节，绝不动已有字节 —— 卡 E81 判据 1）。

    实测尾部形状：文件以 `\r\n` 结尾、末块后**没有**空行，块之间是
    `\r\n\r\n` 分隔 ⇒ 追加时按当前结尾补足分隔，再拼块。
    """
    if raw.endswith(b"\r\n\r\n"):
        return raw + block
    if raw.endswith(b"\r\n"):
        return raw + b"\r\n" + block
    return raw + b"\r\n\r\n" + block


def non_crlf_lines(raw: bytes) -> int:
    r"""裸 LF 的行数（纯 CRLF 时必须是 0 —— 卡 E81 判据 3）。"""
    return raw.count(b"\n") - raw.count(b"\r\n")


# --------------------------------------------------------------------------- 原子写
def write_atomic(path: pathlib.Path, data: bytes, *,
                 tries: int = REPLACE_TRIES, base: float = REPLACE_BASE_S) -> None:
    r"""字节级原子写：写同目录临时文件 → `os.replace`（带线性退避重试）。

    ★ 为什么要重试：Windows 上 `os.replace` 与并发读者互撞，实测 154738 B
      文件**首试失败 84%**（`PermissionError [WinError 5]`）。不重试就等于
      「写着写着偶尔抛异常」——而抛在锁里会把锁一起带走。

    `tries <= 1` ⇒ 单次尝试（反向变异就靠这个参数把重试撤掉）。
    """
    path = pathlib.Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    last: BaseException | None = None
    for i in range(max(1, tries)):
        try:
            os.replace(str(tmp), str(path))
            return
        except PermissionError as exc:  # 只在 Windows 上与并发读者相撞
            last = exc
            if i + 1 < tries:
                time.sleep(base * (i + 1))
    tmp.unlink(missing_ok=True)
    raise LedgerError(f"原子写失败（{tries} 次）：{path}：{_err_name(last)}")


# --------------------------------------------------------------------------- 分片路由
_WB_PLAN: object | None = None


def _wb_plan() -> object | None:
    """延迟加载 `tools/wb_plan.py`（本模块不 import 它，免得成环）。

    ★ `sys.modules[...]` 必须在 `exec_module()` **之前**填 —— 否则 `@dataclass`
      求值时 `sys.modules[cls.__module__]` 是 None，报 `'NoneType' has no __dict__`
      （`tools/wt_prune.py` 实测踩过同一条）。
    """
    global _WB_PLAN
    if _WB_PLAN is not None:
        return _WB_PLAN
    src = pathlib.Path(__file__).resolve().parents[1] / "wb_plan.py"
    if not src.is_file():
        return None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("wb_plan_under_ledger", src)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
    except Exception:
        return None
    _WB_PLAN = mod
    return mod


def shard_dir(root: pathlib.Path | str | None = None) -> pathlib.Path:
    """分片目录（`<根>/docs/backlog`）—— 只算路径，不看存在性。"""
    return main_root(root) / "docs" / "backlog"


def target_path(root: pathlib.Path | str | None, card_id: str) -> pathlib.Path:
    """这张卡该写进哪个文件：分片已启用且分区判得出 ⇒ 那一片；否则总表。"""
    base = main_root(root)
    master = base / BACKLOG_REL
    wb = _wb_plan()
    if wb is None:
        return master
    folder = base / "docs" / "backlog"
    try:
        if not wb.shards_present(folder):        # 分片还没启用 ⇒ 旧行为一字不变
            return master
        shard = wb.shard_file_for(card_id, directory=folder)
    except Exception:
        return master
    return shard if shard is not None else master


def _peer_files(root: pathlib.Path | str | None) -> list[pathlib.Path]:
    """查重要看的全部文件：总表 + 所有现存分片（分片启用与否都看，防同号两处）。"""
    base = main_root(root)
    files = [base / BACKLOG_REL]
    wb = _wb_plan()
    if wb is not None:
        with contextlib.suppress(Exception):
            files.extend(wb.shard_files(base / "docs" / "backlog"))
    return files


def _new_shard_header() -> bytes:
    """新建分片文件的表头（`[base]` + `reviewed`）—— 判据只有一份，在 wb_plan 里。"""
    wb = _wb_plan()
    if wb is not None:
        try:
            return wb.shard_header()
        except Exception:
            pass
    return b'[base]\r\nreviewed = "00000000"\r\n\r\n'


# --------------------------------------------------------------------------- 立卡
def add_card(root: pathlib.Path | str | None, *, id: str, task: str, title: str,
             tree: str, spec: str, files: list[str] | tuple[str, ...],
             depends: list[str] | tuple[str, ...] = (), risk: str = "mid",
             status: str = "pending", wait: float = LOCK_WAIT_S,
             commit: bool = False) -> str:
    r"""在锁里追加一张卡，返回 `"added"` 或 `"already"`（幂等）。

    步骤（全在锁里，约 160 ms）：
    ①读字节 ②验纯 CRLF（否则 `LedgerError`，**不写盘**）③块级查重
    ④拼块追加 ⑤验 TOML（`tomllib.loads` 失败就不 replace）⑥原子写 ⑦（可选）提交。

    ★ 卡 E89：写哪个文件由 `target_path()` 决定 —— 分片启用后是新卡所属的那一片
      （不存在就先写 `shard_header()` 再造块）；否则总表。查重**跨全部文件**
      （总表 + 所有分片），同一张卡不许在两处各有一份。
    """
    base = main_root(root)
    master = base / BACKLOG_REL
    if not master.is_file():
        raise LedgerError(f"台账不存在：{master}")
    path = target_path(base, id)
    with Hold(lock_path(base), wait=wait):
        for peer in _peer_files(base):
            if peer.is_file() and peer != path and has_card(peer.read_bytes(), id):
                return "already"
        raw = path.read_bytes() if path.is_file() else _new_shard_header()
        bad = non_crlf_lines(raw)
        if bad:
            raise LedgerError(
                f"台账不是纯 CRLF（裸 LF {bad} 行）：{path}。"
                "按字节读写、按原始行尾分割是这套写法的前提 —— 停手比写坏强。"
            )
        if has_card(raw, id):
            return "already"
        block = render_card(id=id, task=task, title=title, tree=tree, spec=spec,
                            files=files, depends=depends, risk=risk, status=status)
        new = splice_card(raw, block)
        if not new.startswith(raw):
            raise LedgerError("内部错误：新字节不是旧字节的前缀（只许尾部追加）")
        try:
            tomllib.loads(new.decode("utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
            raise LedgerError(f"追加后 TOML 解析失败，未写盘：{exc}") from exc
        write_atomic(path, new)
        if commit:
            _commit_backlog(base, path, id, task)
        else:
            print(f"  · 没带 --commit ⇒ 没叫 {POOL_README_GEN} 重算 {README_REL}"
                  "（提交时记得一起算：队列卡数差一次重算，下一张卡的腿② 就白红一次）")
    return "added"


def _run_gen(base: pathlib.Path, extra: tuple[str, ...]) -> int:
    r"""跑一次队列卡数的生成器（**唯一**真源：这里不算卡数）。回退码，输出逐行带上缩进。"""
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", POOL_README_GEN, "--root", str(base), *extra],
        cwd=str(base), capture_output=True, text=True,
        encoding="utf-8", errors="replace", **NO_WINDOW,
    )
    for line in (proc.stdout or "").splitlines():
        if line.strip():
            print(f"  {line}")
    for line in (proc.stderr or "").splitlines():
        if line.strip():
            print(f"  {line}")
    return proc.returncode


def _refresh_queue_counts(base: pathlib.Path) -> str | None:
    r"""立卡这一笔顺手重算队列卡数；返回**要一起提交**的相对路径（None = 不带）。

    ★ 为什么要在这里做（卡 E100）：立卡是唯一一笔「不经落地链 ⑤′」的台账写入。
      E98 立卡只提交了台账 ⇒ `docs/subsystems/pool/README.md` 的「队列卡数 | 345 张」
      比台账慢一拍 ⇒ 下一张卡落地的腿② 当场报红，只好单开一笔
      `796ea840 fix(docs): 队列卡数跟上 E98 立卡` 补上。

    四条「不带」的口径，每一条都要**说出来**（静默跳过等于假装算过）：

    1. 这棵树里没有生成器 / 没有 README（假仓、最小树）⇒ 只提交台账；
    2. README **本来就**有未提交改动 ⇒ 不重算、不带上（那是别人验到一半的改动）；
    3. 生成器自己失败 ⇒ 台账照提交（**卡不能丢**），派生文档留给下一趟；
    4. 写完 `--check` 判不一致 ⇒ 不提交这份结果，工作区还原成原样。
    """
    readme = base / README_REL
    generator = base / POOL_README_GEN
    if not generator.is_file() or not readme.is_file():
        missing = POOL_README_GEN if not generator.is_file() else README_REL
        print(f"  · 立卡这一笔没带 {README_REL}：这棵树里没有 {missing}"
              " ⇒ 只提交台账（其余由落地链 ⑤′ 重算）")
        return None
    dirty = _git(base, "status", "--porcelain", "--", README_REL)
    if dirty:
        print(f"  · 立卡这一笔没带 {README_REL}：它本来就有未提交改动"
              f"（{dirty.splitlines()[0].strip()}）⇒ 不替别人提交、也不重算覆盖它")
        return None
    before = readme.read_bytes()
    wrote = _run_gen(base, ())
    if wrote != 0:
        print(f"  · 立卡这一笔没带 {README_REL}：队列卡数的生成器 {POOL_README_GEN} 退 {wrote}"
              " ⇒ 台账照提交（卡不能丢），派生文档留给下一趟")
        readme.write_bytes(before)
        return None
    if readme.read_bytes() == before:
        print(f"  · {README_REL} 已经是现算的样子（队列卡数没变）⇒ 不重复带进这一笔")
        return None
    checked = _run_gen(base, ("--check",))
    if checked != 0:
        print(f"  · 立卡这一笔没带 {README_REL}：写完 --check 判不一致（退 {checked}）"
              " ⇒ 不提交这份重算结果，工作区还原成原样")
        readme.write_bytes(before)
        return None
    print(f"  ★ {README_REL} 的队列卡数随这一笔重算（不用另开一笔补）")
    return README_REL


def _commit_backlog(base: pathlib.Path, path: pathlib.Path, card_id: str, task: str) -> None:
    r"""提交台账，并把**同一次立卡**重算出来的队列卡数一起带上（卡 E100）。

    ★ 提交发生在**锁里**：先放锁再提交，就会出现「台账已改、提交还没落」的
      窗口，别人在这窗口里读到的台账与 HEAD 不一致。

    ★ 为什么 README 要进同一笔：队列卡数是台账的**投影**，两个提交之间必然有
      一拍不一致 —— 落地链的腿② 正好在读那一拍。重算的判据不在这里，
      在 `scripts/gen_pool_readme.py`（这里只负责叫它、判它自检过没过）。
    """
    rel = path.relative_to(base).as_posix()
    extra = _refresh_queue_counts(base)
    staged = [rel, *([extra] if extra else [])]
    add = subprocess.run(["git", "add", "--", *staged], cwd=str(base), capture_output=True,
                         text=True, encoding="utf-8", errors="replace", **NO_WINDOW)
    if add.returncode != 0:
        raise LedgerError(f"git add 失败：{(add.stderr or '').strip()}")
    msg = (f"chore(ledger): 立卡 {card_id}（{task}）\n\n"
           f"Task: {task}\nLedger: 新增 {task}（ENGINEERING/pending）\n")
    if extra:
        msg += f"Docs: {extra}（队列卡数随这一笔重算）\n"
    proc = subprocess.run(["git", "commit", "-q", "-F", "-", "--", *staged], cwd=str(base),
                          input=msg, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **NO_WINDOW)
    if proc.returncode != 0:
        raise LedgerError(f"提交台账失败：{(proc.stderr or proc.stdout or '').strip()}")


# --------------------------------------------------------------------------- 自查
def toml_ok(raw: bytes) -> bool:
    r"""这份字节还是不是合法 TOML（写前自检用）。"""
    try:
        tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        return False
    return True


def _err_name(exc: BaseException | None) -> str:
    r"""异常的可读名（Windows 错误码翻成符号名，便于日志里认）。"""
    if exc is None:
        return "?"
    code = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
    if code is None:
        return type(exc).__name__
    try:
        return f"{type(exc).__name__}({errno.errorcode.get(int(code), code)})"
    except (ValueError, TypeError):
        return type(exc).__name__
