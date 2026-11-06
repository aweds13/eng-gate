r"""卡 E81 · T-AG586 —— 台账并发隔离：立卡那一笔自己拿锁（十条判据的正反向钉子）。

判据原文见 `复盘/卡/卡E81-台账并发隔离.md`。这些钉子钉的是**实测过的丢卡**：
4 进程并发做「读—改—写」，四个都退 0，却静默丢 3 张卡；原型立卡器拆掉锁后
8 进程连跑 4 轮，**每轮丢 3–4 张**，带锁 3 轮都 8/8。所以判据 6（8/8 不丢）与
判据 7（**拆锁必须丢**）必须成对出现 —— 只有 6 而没有 7，这条链可能只是「跑得够慢」。

★ 反向验证的做法（不往生产代码里留后门）：worker 脚本在**子进程里**把
  `ledger.Hold` 换成空操作，再调 `add_card`。生产模块一个开关都不多。

跑法（必须带 `--no-cov`：覆盖率门 `fail-under=70` 会把新建测试读成「覆盖率掉了」）：

    python -X utf8 -m pytest tests/test_ledger_lock.py -q -o addopts= --no-cov
"""

from __future__ import annotations

import concurrent.futures
import os
import pathlib
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from pool import ledger  # noqa: E402 —— tools/ 已在 sys.path 上
from pool.plan import load_backlog  # noqa: E402 —— tomllib 那把尺子（权威读法）

if TYPE_CHECKING:
    from collections.abc import Iterator

CARD_BODY = (
    b'[base]\r\nreviewed = "00000000"\r\n\r\n'
    b"[[cards]]\r\n"
    b'id = "C1"\r\n'
    b'task = "T-AG900"\r\n'
    b'title = "\xe7\xac\xac 1 \xe5\xbc\xa0"\r\n'
    b'tree = ""\r\n'
    b'spec = "x/C1.md"\r\n'
    b'files = ["src/c1.py"]\r\n'
    b'status = "pending"\r\n'
)


# --------------------------------------------------------------------------- 夹具
def _git(repo: pathlib.Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)


def _mk_repo(tmp: pathlib.Path, body: bytes = CARD_BODY) -> pathlib.Path:
    """造一个够 `add_card` 用的最小仓库：git init + 一份 CRLF 台账。"""
    repo = tmp / "repo"
    (repo / "docs").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "e81@example.invalid")
    _git(repo, "config", "user.name", "e81")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "docs" / "workbacklog.toml").write_bytes(body)
    return repo


def _ids_in(raw: bytes) -> list[str]:
    out = []
    for block in ledger.blocks_of(raw):
        cid = ledger.card_id_of(block)
        if cid is not None:
            out.append(cid)
    return out


def _add(repo: pathlib.Path, cid: str, *, wait: float = 30.0) -> str:
    return ledger.add_card(repo, id=cid, task=f"T-AG8{cid[-2:]}", title=f"卡 {cid}",
                           tree=f".wt/{cid}", spec=f"x/{cid}.md",
                           files=[f"tools/{cid}.py"], wait=wait)


@pytest.fixture()
def repo(tmp_path: pathlib.Path) -> Iterator[pathlib.Path]:
    yield _mk_repo(tmp_path)


# ================================================================ 判据 1：只追加尾部
def test_add_card_appends_only_tail(repo: pathlib.Path) -> None:
    """判据 1：新字节必须**逐字节**以旧字节为前缀（已有块一个比特都不许动）。

    反向验证：把 `splice_card` 换成「解析全部块再重新渲染」⇒ 这条红（前缀立刻塌）。
    """
    path = repo / "docs" / "workbacklog.toml"
    before = path.read_bytes()
    assert _add(repo, "C2") == "added"
    after = path.read_bytes()

    assert after.startswith(before), "追加动了已有字节 —— 不是尾部追加"
    assert ledger.non_crlf_lines(after) == 0, "追加带进了裸 LF"
    assert after.count(b"\r\r\n") == 0, "追加带进了三重 CR"
    assert _ids_in(after) == [*_ids_in(before), "C2"]


def test_add_card_keeps_crlf_and_block_separators(repo: pathlib.Path) -> None:
    """判据 2（前半）：块之间仍是**恰好一个**空行，块尾仍是 `\\r\\n`。

    ★ 实测形状：文件以 `\\r\\n` 结尾、末块后没有空行 ⇒ 追加时补一个 `\\r\\n`
      才形成 `\\r\\n\\r\\n` 分隔。少补会粘成一块，多补会长出两个空行。
    """
    path = repo / "docs" / "workbacklog.toml"
    before = path.read_bytes()
    _add(repo, "C2")
    after = path.read_bytes()

    assert after.count(b"\r\n\r\n[[cards]]") == before.count(b"\r\n\r\n[[cards]]") + 1
    assert b"\r\n\r\n\r\n" not in after, "多补了空行"
    assert after.endswith(b"\r\n") and not after.endswith(b"\r\n\r\n")
    assert after[len(before):].startswith(b"\r\n[[cards]]\r\nid = \"C2\"\r\n")


def test_id_is_matched_from_the_parsed_block_field_only() -> None:
    """判据 2（后半 / 反向）：id 只认**块里解析出来的字段**，不认全文里长得像的文本。

    ★ 真会误判的形状（实测）：老脚本 `gates/diag/_add_card.py:27` 拿
      `f'id = "{card}"' in 全文` 判「已在」—— 台账头部本来就有大段**说明注释**
      （含 `id` 字样），任何注释/正文里出现同形文本都会让它说「已在」⇒ 卡**凭空丢**。
      （设计稿里「A1 会被当成已存在于 A11」那句是错的：`id = "A1"` 不是
      `id = "A11"` 的子串，末尾那个引号对不上。按实测改写。）
    这条钉住「块级字段相等」；把 `has_card` 换回全文子串判 ⇒ 这条红。
    """
    raw = (
        b'[base]\r\nreviewed = "00000000"\r\n'
        b'# \xe8\x80\x81\xe8\xb4\xa6\xef\xbc\x9aid = "C9" \xe5\xb7\xb2\xe5\xba\x9f\xe5\xbc\x83\r\n'
        b"\r\n"
        + CARD_BODY.split(b"\r\n\r\n", 1)[1]
    )
    text = raw.decode("utf-8")
    assert 'id = "C9"' in text, "样本没用：注释里得真有同形文本"
    assert ledger.has_card(raw, "C9") is False, "把注释里的 id 当成了一张真卡（子串老毛病）"
    assert ledger.has_card(raw, "C1") is True
    assert ledger.has_card(raw, "C1 ") is False
    assert ledger.has_card(raw, "") is False


# ================================================================ 判据 3：非 CRLF 停手
def test_add_card_rejects_non_crlf_source(tmp_path: pathlib.Path) -> None:
    """判据 3：台账不是纯 CRLF ⇒ `LedgerError`，且**一个字节都没写**。

    反向验证：删掉 `add_card` 的 CRLF 校验那几行 ⇒ 这条红（会「成功」写出混行尾）。
    """
    repo = _mk_repo(tmp_path, CARD_BODY.replace(b"\r\n", b"\n"))
    path = repo / "docs" / "workbacklog.toml"
    before = path.read_bytes()
    with pytest.raises(ledger.LedgerError, match="纯 CRLF"):
        _add(repo, "C2")
    assert path.read_bytes() == before, "报错了还写盘"
    assert not (repo / "gates" / "diag" / ledger.LOCK_NAME).exists(), "报错了没放锁"


def test_skipping_the_crlf_check_would_corrupt_the_file() -> None:
    """判据 3（反向自证）：不校验的话，裸 LF 台账会变成混行尾 —— 校验是挣来的。

    不变量：`non_crlf_lines()` 是**唯一**那把尺子，本条用它自己量：
    在 LF 源上直接 `splice_card` ⇒ 裸 LF 行数 > 0；而 `add_card` 那条路上它被拦住了。
    """
    lf_src = CARD_BODY.replace(b"\r\n", b"\n")
    block = ledger.render_card(id="C2", task="T-AG802", title="卡 C2", tree=".wt/C2",
                               spec="x/C2.md", files=["tools/C2.py"])
    assert ledger.non_crlf_lines(lf_src) > 0
    assert ledger.non_crlf_lines(ledger.splice_card(lf_src, block)) > 0


# ================================================================ 判据 4：锁不分端口段
def test_lock_is_segment_independent(monkeypatch: pytest.MonkeyPatch,
                                     tmp_path: pathlib.Path) -> None:
    """判据 4：`TF_GATE_PORT_BASE` 换成任何值，台账锁都是**同一个**路径。

    ★ 门禁锁（`gates/diag/gate_lock.py`）按端口段分把 —— 对门禁是对的
      （两个端口段的门禁可以并跑）。台账只有一份 ⇒ 绝不能跟着分段，
      否则两个窗口各拿各的锁，等于没锁。
    """
    seen = set()
    for base in ("", "9400", "10250"):
        monkeypatch.setenv("TF_GATE_PORT_BASE", base)
        seen.add(ledger.lock_path(tmp_path))
    assert len(seen) == 1, f"锁路径跟着端口段变了：{seen}"
    assert ledger.lock_path(tmp_path).name == ledger.LOCK_NAME
    # 与门禁锁的 glob 互不干扰（那边只认 gates*.lock）
    assert not ledger.LOCK_NAME.startswith("gates")


# ================================================================ 判据 5：失败关闭
def test_lock_waits_and_fails_closed(repo: pathlib.Path) -> None:
    """判据 5：别人占着锁且未过期 ⇒ 等到 deadline 就抛，**绝不无锁写**。

    另一半：租约过期（mtime 更老）⇒ 可以接管，不用人来删锁。
    """
    path = repo / "docs" / "workbacklog.toml"
    before = path.read_bytes()
    lock = ledger.lock_path(repo)
    held = ledger.acquire(lock, wait=5.0)
    try:
        started = time.monotonic()
        with pytest.raises(ledger.LedgerBusyError, match="等不到台账锁"):
            _add(repo, "C2", wait=0.3)
        assert time.monotonic() - started >= 0.3
        assert path.read_bytes() == before, "等不到锁还是写了盘（失败没关闭）"
    finally:
        ledger.release(held)

    # 租约过期 ⇒ 接管（不读内容，只看 mtime 够老）
    stale = ledger.lock_path(repo)
    stale.write_bytes(b"pid=999999\n")
    old = time.time() - (ledger.LOCK_TTL_S + 5.0)
    os.utime(str(stale), (old, old))
    assert _add(repo, "C2", wait=0.5) == "added"
    assert not stale.exists(), "接管之后没把过期锁清掉"


def test_acquire_gives_up_when_creating_the_lock_is_denied(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """判据 5（Windows 专有形状）：建锁被拒也必须**失败关闭**。

    ★ 实测经历：`O_CREAT|O_EXCL` 撞上「持有者正在 `unlink()`」时，Windows 抛的是
    `PermissionError` 而不是 `FileExistsError`。初版只做 `sleep + continue`
    而没看 deadline ⇒ 真遇上就是无限循环，把整道 pytest 门顶到 1800 s 硬超时被掏。
    这条钉子把那个分支变成确定性可复现：每次建锁都抛 `PermissionError`。
    """
    lock = ledger.lock_path(tmp_path)

    def _denied(*_a: object, **_kw: object) -> int:
        raise PermissionError(13, "Permission denied", str(lock))

    monkeypatch.setattr(ledger.os, "open", _denied)
    started = time.monotonic()
    with pytest.raises(ledger.LedgerBusyError, match="拿不到台账锁"):
        ledger.acquire(lock, wait=0.3)
    elapsed = time.monotonic() - started
    assert 0.3 <= elapsed < 10.0, f"deadline 没生效：等了 {elapsed:.1f}s"


def test_release_does_not_swallow_errors(tmp_path: pathlib.Path) -> None:
    """判据 5（配套）：放锁失败不许静默吞 —— 吞掉就变成「以为放开了，其实还占着」。

    `tools/pool/task.py` 的 `with suppress(OSError): lock.unlink()` 是反例
    （4 进程实测残留锁）。两半都钉：
      ①锁本来就不在 ⇒ **算成功**（否则过期清理路径会被自己绊倒）；
      ②放不掉（这里把锁路径做成一个目录，`unlink` 在 Windows 与 POSIX 都抛）
        ⇒ 重试耗尽后必须抛，不许静默。
    """
    ledger.release(tmp_path / "never-existed.lock")  # ①：不抛就是对的

    stuck = tmp_path / "stuck.lock"
    stuck.mkdir()
    started = time.monotonic()
    with pytest.raises(ledger.LedgerBusyError, match="放不掉台账锁"):
        ledger.release(stuck)
    assert time.monotonic() - started >= 0.5, "没重试就直接抛了"
    assert stuck.is_dir(), "报错了还把别人的东西删了"


# ================================================================ 判据 6/7：并发
def _clear_rendezvous(path: pathlib.Path) -> None:
    """清掉上一轮的会合文件（同一夹具里连跑多轮时用）。"""
    if path.is_dir():
        for item in path.iterdir():
            item.unlink()


def _worker_script(repo: pathlib.Path, card: str, *, no_lock: bool,
                   rendezvous: pathlib.Path | None = None) -> list[str]:
    """子进程要跑的那段（`-c` 传进去）。

    `no_lock=True` 时把 `Hold` 换成空操作，**并且**把 `ledger.write_atomic`
    包成「8 个都读完旧字节才准写盘」—— 这样「8 张只落 1 张」是确定性结论，
    不再取决于机器快慢（2026-11-06 云机 4 逻辑核连跑 3 轮一张没丢过）。
    """
    patch = (
        "import pathlib\n"
        "class _NoLock:\n"
        "    def __init__(self, *a, **k): pass\n"
        "    def __enter__(self): return None\n"
        "    def __exit__(self, *a): return None\n"
        "ledger.Hold = _NoLock\n"
        "_rv = pathlib.Path(sys.argv[4])\n"
        "_rv.mkdir(parents=True, exist_ok=True)\n"
        "_real = ledger.write_atomic\n"
        "def _write_after_all_read(path, data, **kw):\n"
        "    (_rv / sys.argv[3]).write_text('1', encoding='utf-8')\n"
        "    deadline = time.monotonic() + 120.0\n"
        "    while len(list(_rv.iterdir())) < 8:\n"
        "        if time.monotonic() > deadline:\n"
        "            raise SystemExit('会合超时：只到了 %d 个' % len(list(_rv.iterdir())))\n"
        "        time.sleep(0.005)\n"
        "    _real(path, data, **kw)\n"
        "ledger.write_atomic = _write_after_all_read\n"
        if no_lock else ""
    )
    code = (
        "import sys, time\n"
        f"sys.path.insert(0, {str(ROOT / 'tools')!r})\n"
        "from pool import ledger\n"
        f"{patch}"
        "time.sleep(float(sys.argv[2]))\n"
        "ledger.add_card(sys.argv[1], id=sys.argv[3], task='T-AG9' + sys.argv[3],\n"
        "                title='并发卡', tree='.wt/' + sys.argv[3],\n"
        "                spec='x/' + sys.argv[3] + '.md', files=['t.py'], wait=120.0)\n"
    )
    tail = [str(rendezvous)] if no_lock else []
    return [sys.executable, "-X", "utf8", "-c", code, str(repo), "0", card, *tail]


def _run_eight(repo: pathlib.Path, *, no_lock: bool) -> list[str]:
    cards = [f"D{i}" for i in range(8)]
    rendezvous = repo.parent / "rendezvous"
    _clear_rendezvous(rendezvous)
    procs = [subprocess.Popen(_worker_script(repo, c, no_lock=no_lock, rendezvous=rendezvous),
                              cwd=str(repo), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
             for c in cards]
    for p in procs:
        p.communicate(timeout=180)
    return _ids_in((repo / "docs" / "workbacklog.toml").read_bytes())


def test_eight_writers_lose_nothing(repo: pathlib.Path) -> None:
    """判据 6：8 个进程并发立卡 ⇒ 8 张**全在**，每张 `id` 恰好出现 1 次。

    反向验证（判据 7 那条）：把 `Hold` 换成空操作 ⇒ 这条会红或时好时坏。
    """
    ids = _run_eight(repo, no_lock=False)
    for i in range(8):
        assert ids.count(f"D{i}") == 1, f"卡 D{i} 落成 {ids.count(f'D{i}')} 次：{ids}"
    assert len(ids) == len(set(ids)), f"有重复 id：{ids}"


def test_without_lock_loses_updates(repo: pathlib.Path) -> None:
    """判据 7（★ 反向）：拆掉锁，同一批 8 进程**必须丢 ≥1 张** —— 8/8 是锁挣来的。

    ★ 这条要是「也不丢」，说明判据 6 根本没在测并发（工具有没有锁都一样），
      那 6 就只是一句空话。
    ★ 原本靠**墙钟竞态**必丢（本机每轮丢 3–4 张）。2026-11-06 落地卡 E89 时，
      云机（4 逻辑核）连跑 3 轮**一张都没丢** ⇒ 假红，判据本身不可靠。
      现改成**确定性会合**：worker 把 `write_atomic` 包成「8 个都读完旧字节才准写」，
      于是 8 个各自写出的都只是「旧内容 + 自己那张」，最后落盘只剩一张。
      丢卡与机器快慢无关，也不再需要连跑多轮。
    """
    ids = _run_eight(repo, no_lock=True)
    lost = [f"D{i}" for i in range(8) if ids.count(f"D{i}") != 1]
    assert lost, f"拆了锁居然一张都没丢（{ids}）—— 判据 6 的 8/8 不能证明任何东西"


# ================================================================ 判据 8：立刻可见
def test_reader_sees_card_immediately(repo: pathlib.Path) -> None:
    """判据 8：`add` 返回后就该读到 —— 同进程、以及**另一个新进程**。

    ★ 必须显式传台账路径：在卡树里跑时 `pipe_root.data_root()` 会指向卡树，
      读到的是另一份文件（那是本仓已知的坑，不是本卡要改的东西）。
    """
    path = repo / "docs" / "workbacklog.toml"
    _add(repo, "C2")
    assert "C2" in load_backlog(path).by_id()

    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT / 'tools')!r})\n"
        "import pathlib\n"
        "from pool.plan import load_backlog\n"
        "sys.exit(0 if 'C2' in load_backlog(pathlib.Path(sys.argv[1])).by_id() else 3)\n"
    )
    proc = subprocess.run([sys.executable, "-X", "utf8", "-c", code, str(path)],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120)
    assert proc.returncode == 0, f"新进程读不到：{proc.stderr}"


# ================================================================ 判据 9：写入口收敛
def test_production_writes_go_through_ledger_only() -> None:
    """判据 9：全仓对台账的写盘只在 `pool/ledger.py` 里；落地链用同一个原子写。

    ★ 这条钉的是「判据只有一份」：`tools/pool/landing.py` 那条翻账路径
      必须改走 `ledger.write_atomic`，否则两把尺子迟早分叉。
    """
    # ★ 口径要按**行**：同一行既有写盘调用、又提到台账，才可能是旁路。
    #   按文件粗扫会误报 13 处（`tools/wb_plan.py` 之类只是读到路径而已）。
    import re

    write_call = re.compile(r"(write_bytes|write_text)\s*\(")
    offenders = []
    for base in ("tools", "scripts"):
        for path in (ROOT / base).rglob("*.py"):
            if path.name == "ledger.py":
                continue
            for no, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
            ):
                if write_call.search(line) and "backlog" in line.lower():
                    offenders.append(f"{path.relative_to(ROOT).as_posix()}:{no}")
    assert offenders == [], f"还有旁路写台账：{offenders}"

    landing = (ROOT / "tools" / "pool" / "landing.py").read_text(encoding="utf-8",
                                                                errors="replace")
    assert "ledger.write_atomic(" in landing, "落地链没有走同一个原子写"
    assert "backlog_path.write_bytes" not in landing, "落地链还在自己写盘"


# ================================================================ 判据 10：原子写重试
def test_write_atomic_retries_after_permission_error(tmp_path: pathlib.Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 10：第一次 `os.replace` 抛 `PermissionError` ⇒ 重试后成功。

    ★ 为什么要它：Windows 上 `os.replace` 与并发读者互撞，实测 154738 B 台账
      **首试失败 421/500（84%）**。不重试就等于「写着写着偶尔抛异常」。
    反向验证：把重试循环改成单次 `os.replace` ⇒ 这条红。
    """
    target = tmp_path / "a.toml"
    target.write_bytes(b"old\r\n")
    real = os.replace
    calls = {"n": 0}

    def flaky(src: str, dst: str) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(13, "被别的进程占着")
        real(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    ledger.write_atomic(target, b"new\r\n")
    assert calls["n"] == 2, f"没有重试：只试了 {calls['n']} 次"
    assert target.read_bytes() == b"new\r\n"


def test_write_atomic_gives_up_after_all_tries(tmp_path: pathlib.Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 10（另一半）：重试全失败 ⇒ 抛 `LedgerError`，且**不留下临时文件**。"""
    target = tmp_path / "a.toml"
    target.write_bytes(b"old\r\n")

    def always(*_a: object) -> None:
        raise PermissionError(13, "一直占着")

    monkeypatch.setattr(os, "replace", always)
    with pytest.raises(ledger.LedgerError, match="原子写失败"):
        ledger.write_atomic(target, b"new\r\n", tries=3, base=0.001)
    assert target.read_bytes() == b"old\r\n"
    assert list(tmp_path.glob(".*.tmp")) == [], "失败后没清临时文件"


# ================================================================ 幂等 + 提交
def test_add_card_is_idempotent(repo: pathlib.Path) -> None:
    """判据 1 的配套：同一张卡加两次 ⇒ 第二次 `"already"`，文件**一字节不变**。"""
    path = repo / "docs" / "workbacklog.toml"
    assert _add(repo, "C2") == "added"
    once = path.read_bytes()
    assert _add(repo, "C2") == "already"
    assert path.read_bytes() == once


def test_commit_only_touches_the_backlog(repo: pathlib.Path) -> None:
    """`--commit` 只提交台账那一份文件（别的改动一个都不许被带进这一笔）。"""
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    (repo / "stray.txt").write_text("不该被带走\n", encoding="utf-8")
    ledger.add_card(repo, id="C2", task="T-AG802", title="卡 C2", tree=".wt/C2",
                    spec="x/C2.md", files=["t.py"], commit=True)
    shown = subprocess.run(
        ["git", "-c", "core.quotepath=false", "show", "--name-only", "--format=%s", "HEAD"],
        cwd=str(repo), capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout
    assert "docs/workbacklog.toml" in shown
    assert "stray.txt" not in shown, f"提交带走了别的东西：{shown}"


def test_eight_writers_are_serialized_by_the_lock(repo: pathlib.Path) -> None:
    """判据 6 的另一种说法：8 个进程**都**退 0（锁是等来的，不是靠报错躲掉的）。"""
    cards = [f"E{i}" for i in range(8)]

    def run(card: str) -> int:
        proc = subprocess.run(_worker_script(repo, card, no_lock=False), cwd=str(repo),
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=180)
        return proc.returncode

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(run, cards))
    assert codes == [0] * 8, f"有进程没退 0：{codes}"
    ids = _ids_in((repo / "docs" / "workbacklog.toml").read_bytes())
    assert sorted(c for c in ids if c.startswith("E")) == cards
