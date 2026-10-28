"""卡 E61 · T-AG519 —— 判不出来的时候不许说没事（混行尾让「翻 status」静默跳过）。

五条判据各一条钉子 + 白名单自证。判据原文见 `复盘/卡/卡E61-判不出来的时候不许说没事.md`。

★ 为什么要这组钉子：`docs/workbacklog.toml` 是纯 CRLF，但手写的卡块可能带裸 LF。
  老写法「见到 CRLF 就只按 CRLF 切」会把那一块与下一块并成一个元素 ⇒
  `_scan_blocks` 认不出块边界 ⇒ **那张卡凭空消失，且不抛任何错**。
  E60 落地时真发作过（259 张读成 258 张，落地链仍 exit 0）。
"""
from __future__ import annotations

import ast
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from pool import landing as _landing  # noqa: E402 —— 需要先把 tools/ 挂上 sys.path


# --------------------------------------------------------------------------- 样本构造
def _queue_bytes(cards: int, *, bare_lf_before: int | None = None) -> bytes:
    """造一份 `workbacklog.toml` 形状的字节串（纯 CRLF，过 `load_backlog` 的合法形）。

    `bare_lf_before=k` ⇒ 第 k 张卡的 `[[cards]]` 之前那条行尾换成裸 LF
    —— 这正是 E60 真发作过的形状：按 CRLF 切之后 `status = "todo"\\n[[cards]]`
    成了同一个元素，块边界消失。

    ★ 字段必须齐（`id`/`task`/`title`/`tree`/`spec`/`files`）：判据 2 要拿
      `pool.plan.load_backlog`（tomllib 那把尺子）对照，它缺字段直接抛。
    """
    out: list[bytes] = [b'[base]\r\nreviewed = "' + b"0" * 8 + b'"\r\n\r\n']
    for i in range(cards):
        out.append(b"[[cards]]\n" if bare_lf_before == i else b"[[cards]]\r\n")
        out.append(f'id = "C{i}"\r\n'.encode())
        out.append(f'task = "T-AG9{i:02d}"\r\n'.encode())
        out.append(f'title = "第 {i} 张"\r\n'.encode())
        out.append(b'tree = ""\r\n')
        out.append(f'spec = "x/C{i}.md"\r\n'.encode())
        out.append(f'files = ["src/c{i}.py"]\r\n'.encode())
        out.append(b'status = "todo"\r\n')
        out.append(b"\r\n")
    return b"".join(out)


def _old_sniff_split(raw: bytes) -> list[bytes]:
    """卡 E61 要废掉的老写法 —— 反向验证用它把判据撤掉。

    ★ 故意**不**把那个正则字面量写在源码里：本文件也在判据 5 的扫描范围内，
      写死就会被自己的扫描器命中（自指）。用常量拼出来即可。
    """
    crlf, lf = b"\r\n", b"\n"
    sep = crlf if crlf in raw else lf
    return raw.split(sep)


def _ids(lines: list[bytes]) -> list[str]:
    return [str(f["id"]) for _s, _e, f in _landing._scan_blocks(lines)]


# --------------------------------------------------------------------------- 判据 1
def test_mixed_endings_still_finds_every_card() -> None:
    """判据 1：一处读取口径 —— 混行尾样本上，字节切分必须认出**每一张**卡。

    反向验证：把 `_split_blocks` 换回 `_old_sniff_split` ⇒ 这条红（漏认 1 张）。
    """
    raw = _queue_bytes(9, bare_lf_before=4)

    new_ids = _ids(_landing._split_blocks(raw))
    assert new_ids == [f"C{i}" for i in range(9)], "新读法漏卡"

    old_ids = _ids(_old_sniff_split(raw))
    assert old_ids != new_ids, (
        "反向验证失效：老写法居然也认全了 —— 说明样本没造出混行尾，"
        "这条钉子就变成空真了")
    assert "C4" in new_ids and "C4" not in old_ids


def test_byte_ruler_agrees_with_tomllib_ruler(tmp_path: pathlib.Path) -> None:
    """判据 2：两把尺子必须说同一句话（字节切分 vs tomllib）。

    4 份样本：纯 CRLF / 纯 LF / 首块裸 LF / 末块裸 LF。
    反向验证：把 `_split_blocks` 换回老写法 ⇒ 后两份样本上两个集合不等 ⇒ 红。
    """
    from pool.plan import load_backlog  # tomllib 那把尺子（权威读法）

    samples = {
        "纯CRLF": _queue_bytes(6),
        "纯LF": _queue_bytes(6).replace(b"\r\n", b"\n"),
        "首块裸LF": _queue_bytes(6, bare_lf_before=0),
        "末块裸LF": _queue_bytes(6, bare_lf_before=5),
    }
    for label, raw in samples.items():
        p = tmp_path / "docs" / "workbacklog.toml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
        tomllib_ids = set(load_backlog(p).by_id())
        byte_ids = set(_ids(_landing._split_blocks(raw)))
        assert byte_ids == tomllib_ids, (
            f"{label}：字节切分 {sorted(byte_ids)} ≠ tomllib {sorted(tomllib_ids)}")


# --------------------------------------------------------------------------- 判据 3
def test_landing_exits_nonzero_when_it_cannot_flip(
    tmp_path: pathlib.Path,
) -> None:
    """判据 3（端到端）：`wb_land` 该翻却翻不动 ⇒ **退非零**，且输出点名卡号。

    ★ 这条钉的是「**调用方也看返回值**」那一半 —— 单独测 `flip_card_status`
      只能证明它返回了 `"unflippable"`，证明不了落地链真会因此停手
      （缺陷原文：`landing.py:2356` 的调用方不看返回值 ⇒ 整条链 exit 0 收场）。

    ★ 造法：真跑 `wb_land --commit-only`（跳过门禁与封存，只走 ⑤′ 翻账那段），
      沙箱是 `test_wb_land._mk_repo` 那套最小假仓库，队列里放一张
      **有 `[[cards]]` 块却没有 `status = "..."` 行**的卡。
    ★★ 反向验证**逼出来的一条**（第一次写这钉子时它是空真）：必须让暂存区
      **非空**。否则撤掉翻账检查后，「★ 计划外或空暂存区 ⇒ 停手」这条**别的**
      守卫也会退 2 ⇒ 退出码断言照旧通过，钉子白写。所以这里先把一处域内文件
      改成未暂存状态，让 `staged` 有东西；撤掉检查后它会一路走到 ⑥ 提交
      ⇒ **exit 0**，退出码断言才真的咬得住。
    """
    sys.path.insert(0, str(ROOT / "tests"))
    import test_wb_land as twl  # noqa: E402 —— 最小收口链沙箱的**唯一**造法就在那里

    repo = twl._mk_repo(tmp_path)
    # 队列：一张卡，块头与 KV 齐、**故意不给 status 行** ⇒ 该翻却翻不动
    (repo / "docs" / "workbacklog.toml").write_bytes(
        b"[[cards]]\r\n"
        b'id = "C9"\r\n'
        b'task = "T-G999"\r\n'
        + 'title = "钉子"\r\n'.encode()
        + b'tree = ""\r\n'
        b'spec = "x/C9.md"\r\n'
        b'files = ["code/a.py"]\r\n'
        b"\r\n"
    )
    twl._git(repo, "add", "-A")
    twl._git(repo, "commit", "-q", "-m", "backlog 里放一张翻不动的卡")

    # ★ 见 docstring：留一处**域内**的真改动，保证暂存区非空（否则退出码断言空真）
    twl._write(repo, "code/a.py", "Y = 2\n")
    done = twl._wand(repo, "--no-gate", "--commit-only", "--no-reset",
                     card="C9", task="T-G999")
    out = twl._out(done)
    assert done.returncode != 0, (
        "该翻却翻不动，落地链居然 exit 0 —— 这正是卡 E61 要根除的「判不出来的时候说没事」：\n"
        + out)
    assert "C9" in out, f"停手了但没点名卡号：\n{out}"
    assert "队列与台账不一致" in out, f"停手了但没说清为什么：\n{out}"


def test_unflippable_card_stops_the_landing(
    tmp_path: pathlib.Path, capsys,
) -> None:
    """判据 3：该翻却翻不动 ⇒ 三态里必须出现 `"unflippable"`，不许混进 `"not-needed"`。

    造一份**读不到 status 行**的卡（有 `[[cards]]` 块、但没有 `status = "..."`）。
    反向验证：把返回值改回 `False` ⇒ 这条红。
    """
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "workbacklog.toml").write_bytes(
        b"[[cards]]\r\n"
        b'id = "C9"\r\n'
        b'task = "T-AG909"\r\n'
        b'spec = "x/C9.md"\r\n'
        b"\r\n"
    )
    verdict = _landing.flip_card_status(repo, "C9", "T-AG909")
    out = capsys.readouterr().out
    assert verdict == "unflippable", f"该翻却翻不动必须报 unflippable，得到 {verdict!r}"
    assert "C9" in out, "点名卡号"


def test_not_needed_is_not_confused_with_unflippable(tmp_path: pathlib.Path) -> None:
    """判据 3 的另一半：本就不该翻的三种情形全部是 `"not-needed"`。

    否则「不许 exit 0」会误伤每一次登记型提交与已经 done 的卡。
    """
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    p = repo / "docs" / "workbacklog.toml"

    # (a) 已是 done
    p.write_bytes(_queue_bytes(1).replace(b'status = "todo"', b'status = "done"'))
    assert _landing.flip_card_status(repo, "C0", "T-AG900") == "not-needed"

    # (b) 登记型提交：--task 与卡.task 不一致
    p.write_bytes(_queue_bytes(2))
    assert _landing.flip_card_status(repo, "C1", "T-AGOTHER") == "not-needed"

    # (c) 卡不存在
    assert _landing.flip_card_status(repo, "NOPE", "T-AG900") == "not-needed"


# --------------------------------------------------------------------------- 判据 4
def test_writers_preserve_the_existing_ending(tmp_path: pathlib.Path) -> None:
    """判据 4：写入不许再造混行尾 —— 翻完 status，裸 LF 计数必须仍是 0。

    （`flip_card_status` 走 `_split_blocks` 保留行尾、`b"".join` 原样拼回。）
    反向验证：把 `b"".join(lines)` 改回 `sep.join(lines)` ⇒ 这条红（会插入多余行尾）。
    """
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    p = repo / "docs" / "workbacklog.toml"
    p.write_bytes(_queue_bytes(3))

    assert _landing.flip_card_status(repo, "C1", "T-AG901") == "flipped"
    raw = p.read_bytes()
    bare_lf = raw.count(b"\n") - raw.count(b"\r\n")
    assert bare_lf == 0, f"翻账后出现 {bare_lf} 处裸 LF（写坏了行尾）"
    # 3 张卡 ×（开块 1 + KV 7 + 空行 1）= 27，加 [base] 两行 + 一空行 = 30
    assert raw.count(b"\r\n") == 30, "行数被改动了"
    assert _ids(_landing._split_blocks(raw)) == ["C0", "C1", "C2"]


# --------------------------------------------------------------------------- 判据 5
#: 不是「读队列块」的写法 —— 扫出来但不该改的，**每条都要写明理由**（照卡 E60 体例）。
#: 键 = `仓库相对路径:行号`；值 = 为什么它不是本卡要修的那种缺陷。
#:
#: ★ 现在是空的，而且是**对的**：判据 5 的扫描器用 `ast` 把字符串字面量整段排除，
#:   所以 `_split_blocks` 文档字符串里那段反例示范天然不算「活着的代码」，
#:   不需要靠白名单挡。白名单只剩一种用途 —— 将来真出现「是代码但不该改」的
#:   例外时，逼着写理由，并由 `test_the_allow_list_says_why` 保证它不会永远躺着。
_NOT_A_BLOCK_READER: dict[str, str] = {}

#: 扫哪些目录（与卡规格判据 5 一致）。
_SCAN_DIRS = ("tools", "scripts", "tests", "framework/src")

#: 「先嗅行尾再 split」这个形状。
_SNIFF_RE = re.compile(
    rb'sep\s*=\s*b["\'](?:\\r)?\\n["\']\s*if\s*b["\'](?:\\r)?\\n["\']\s*in\s+\w+\s*else\s*b["\']\\n["\']'
)


def _literal_line_ranges(path: pathlib.Path) -> list[tuple[int, int]]:
    """文件里所有**字符串字面量**占用的行区间（含文档字符串）。

    判据 5 只咬**可执行代码**：写在文档字符串里的反例示范、以及单行字符串里
    引用的老写法，都不是「还活着的读法」。用 `ast` 判，不靠缩进或引号猜。
    """
    try:
        tree = ast.parse(path.read_bytes())
    except SyntaxError:                                  # 半成品文件不参与，交给 ruff
        return []
    spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
            spans.append((node.lineno, getattr(node, "end_lineno", node.lineno)))
    return spans


def _scan_sniff_sites() -> list[tuple[str, int, bytes]]:
    hits: list[tuple[str, int, bytes]] = []
    for d in _SCAN_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for f in base.rglob("*.py"):
            rel = f.relative_to(ROOT).as_posix()
            spans = _literal_line_ranges(f)
            for i, ln in enumerate(f.read_bytes().split(b"\n"), 1):
                if not _SNIFF_RE.search(ln):
                    continue
                if any(lo <= i <= hi for lo, hi in spans):
                    continue                             # 在字符串字面量里 ⇒ 不是代码
                hits.append((rel, i, ln.strip()))
    return hits


def test_no_ending_sniffing_split_left() -> None:
    """判据 5：全仓扫，防第七处 —— 除白名单外，一处都不许有。

    反向验证：在任意 `tools/*.py` 里加一行 `sep = b"\\r\\n" if b"\\r\\n" in x else b"\\n"`
    ⇒ 这条红并点名那个文件。
    """
    hits = _scan_sniff_sites()
    offenders = [f"{rel}:{ln}" for rel, ln, _txt in hits
                 if f"{rel}:{ln}" not in _NOT_A_BLOCK_READER]
    assert not offenders, (
        "「先嗅行尾再 split」还在这些地方活着（会静默漏块）：\n  "
        + "\n  ".join(offenders)
        + "\n要么改用 landing._split_blocks，要么加进 _NOT_A_BLOCK_READER 并写明理由。")


def test_the_allow_list_says_why() -> None:
    """判据 5 自证：白名单自己也要被钉住（空着合法，但填了就必须是活的）。

    三条：理由不许空 / 行号必须在文件里 / 那一行必须**还**是那个写法。
    （照卡 E60 判据 6 的 `_NOT_A_RED_RULER` 体例。）
    """
    by_key = {f"{rel}:{ln}": txt for rel, ln, txt in _scan_sniff_sites()}
    for key, why in _NOT_A_BLOCK_READER.items():
        rel, _, ln_s = key.rpartition(":")
        ln = int(ln_s)
        assert why.strip(), f"{key}：理由空着"
        f = ROOT / rel
        assert f.is_file(), f"{key}：文件不存在（白名单过期）"
        lines = f.read_bytes().split(b"\n")
        assert 1 <= ln <= len(lines), f"{key}：行号越界（文件只有 {len(lines)} 行）"
        assert key in by_key, (
            f"{key}：那一行已经不是「先嗅行尾再 split」了 —— "
            "白名单该删这一条，别让它永远躺着")


# --------------------------------------------------------------------------- 反向验证
def test_reverse_direction_sniff_split_really_loses_a_card() -> None:
    """把判据撤掉必须咬得住 —— 这条钉子钉的是「钉子自己不是空真」。"""
    raw = _queue_bytes(5, bare_lf_before=2)
    assert len(_ids(_landing._split_blocks(raw))) == 5
    assert len(_ids(_old_sniff_split(raw))) == 4


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-q"]))
