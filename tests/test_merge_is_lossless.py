r"""台账合并的**无损**判据（`tools/wb_plan.py`，卡 E88 / T-AG595）。

**为什么值当测**：`merge --execute` 今天会把 332 张卡的总表写成 1 张（rc=0、零警告），
就算不丢卡，块序 / 表头注释 / 块内注释也会全漂，落盘还是裸 LF。
分片是「让并发写入不打架」的手段，不是「让台账变差」的理由 —— 所以合并必须先做成无损：

| 判据 | 钉什么 |
|---|---|
| 1 | 覆盖性守卫：分片少一张就拒写、点名缺哪些、**总表字节一字未变** |
| 2 | 无变化就零 diff：真总表拆片再 merge ⇒ `read_bytes()` 相等 |
| 3 | 块级搬运：块内 `#` 注释逐字还在（不许在解析里蒸发） |
| 4 | 新卡只往末尾长，既有卡相对顺序不动 |
| 5 | 落盘纯 CRLF（`ledger.non_crlf_lines(raw) == 0`） |
| 6 | 既有行为一字不变：无分片 / 重号 / 不带 `--execute` |

★ 用**真件**建模：真 `tools/wb_plan.py`、真总表副本（`docs/workbacklog.toml`）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:                       # 只当注解用（`from __future__ import annotations`）
    import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_plan  # noqa: E402 —— 主角
from pool import ledger as pool_ledger  # noqa: E402 —— 块函数（纯 CRLF 判据也用它）

MASTER = ROOT / "docs" / "workbacklog.toml"
SHARD_REVIEWED = "38522420"
SHARD_HEAD = f'[base]\r\nreviewed = "{SHARD_REVIEWED}"\r\n\r\n'.encode()


# ---------------------------------------------------------------- 小工具

def _master_raw() -> bytes:
    """真总表的字节（测试只读它，绝不写回）。"""
    return MASTER.read_bytes()


def _blocks(raw: bytes) -> list[tuple[str, bytes]]:
    """按 `[[cards]]` 切出 `(卡号, 块字节)`；块字节原样（含块内注释）。"""
    pairs: list[tuple[str, bytes]] = []
    for block in pool_ledger.blocks_of(raw):
        card_id = pool_ledger.card_id_of(block)
        if card_id:
            pairs.append((card_id, b"".join(block)))
    return pairs


def _write_shards(directory: Path, groups: dict[str, list[bytes]]) -> Path:
    """按片名写分片：表头 + 若干块字节（块字节原样搬运）。"""
    directory.mkdir(parents=True, exist_ok=True)
    for name, blocks in groups.items():
        (directory / name).write_bytes(SHARD_HEAD + b"".join(blocks))
    return directory


def _split_by_prefix(raw: bytes) -> dict[str, list[bytes]]:
    """把真总表按卡号前缀拆成若干片 —— 内容是**块字节原样**，只换存放位置。"""
    groups: dict[str, list[bytes]] = {}
    for card_id, block in _blocks(raw):
        prefix = wb_plan.card_prefix(card_id) or "LEGACY"
        groups.setdefault(f"{prefix}.toml", []).append(block)
    return groups


def _card_block(card_id: str, *, bodies: str = "") -> bytes:
    """造一块卡（`bodies` 里可塞注释行，用来钉判据 3）。"""
    return (
        f'[[cards]]\r\nid = "{card_id}"\r\ntask = "T-ZZZ5"\r\ntitle = "样卡"\r\n'
        f'tree = ".wt/{card_id}"\r\nspec = ""\r\nfiles = ["a.py"]\r\ndepends = []\r\n'
        f'{bodies}risk = "low"\r\nstatus = "pending"\r\n'
    ).encode()


def _tail(expected: bytes, got: bytes) -> str:
    """失败时给一段可读的对照（别把 15 万字节糊到终端里）。"""
    return (f"期望 {len(expected)} B / 实得 {len(got)} B\n"
            f"  期望尾 80 B: {expected[-80:]!r}\n  实得尾 80 B: {got[-80:]!r}")


# ---------------------------------------------------------------- 判据 1：覆盖性守卫

def test_a_shard_that_misses_cards_is_refused(tmp_path: Path) -> None:
    """判据 1：真总表 333 张 + 只放 1 张卡的片 ⇒ 拒写、点名、总表字节一字未变。

    今天的行为是 rc=0 把总表写成 1 张卡（`.tmp/_probe_merge_guard.py` 实测 158788 B → 175 B）——
    这条钉子就是为了关掉那条路。
    """
    out = tmp_path / "workbacklog.toml"
    out.write_bytes(_master_raw())
    before = out.read_bytes()
    shards = _write_shards(tmp_path / "shards", {"E.toml": [_card_block("E999")]})

    rc = wb_plan.cmd_merge(shards, out, execute=True)

    assert rc != 0, "分片没覆盖总表却写盘了 —— 吃卡"
    assert out.read_bytes() == before, "拒绝了但总表被改过"
    assert len(_blocks(out.read_bytes())) == len(_blocks(before))


def test_the_refusal_names_every_missing_card(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """判据 1（续）：拒的时候要**逐个点名**缺哪些卡号，不能只说「缺了一些」。"""
    out = tmp_path / "workbacklog.toml"
    master = _master_raw()
    out.write_bytes(master)
    shards = _write_shards(tmp_path / "shards", {"E.toml": [_card_block("E999")]})

    assert wb_plan.cmd_merge(shards, out, execute=True) != 0

    err = capsys.readouterr().err
    assert "缺" in err
    missing = [card_id for card_id, _ in _blocks(master)]
    assert "E999" not in missing
    assert missing[0] in err, f"没点名第一张缺的卡 {missing[0]}：{err[:400]}"


# ---------------------------------------------------------------- 判据 2：零 diff

def test_a_round_trip_through_shards_is_byte_identical(tmp_path: Path) -> None:
    """判据 2：真总表拆成各前缀分片、再 merge 回去 ⇒ **逐字节相同**。

    这一条同时钉住块序、表头（2187 B 注释 + `[base]`）与块内注释：任何一件漂了都过不了。
    """
    master = _master_raw()
    out = tmp_path / "workbacklog.toml"
    out.write_bytes(master)
    shards = _write_shards(tmp_path / "shards", _split_by_prefix(master))

    assert wb_plan.cmd_merge(shards, out, execute=True) == 0

    got = out.read_bytes()
    assert got == master, _tail(master, got)
    assert len(_blocks(got)) == len(_blocks(master))


# ---------------------------------------------------------------- 判据 3：块内注释

def test_block_comments_survive_the_merge(tmp_path: Path) -> None:
    """判据 3：块内 `#` 注释**逐字还在** —— 合并不是「解析成 Card 再重新渲染」。"""
    comment = "# ★ 这张卡的备注：别删\r\n"
    master = SHARD_HEAD + _card_block("E1") + comment.encode() + _card_block("E2")
    out = tmp_path / "workbacklog.toml"
    out.write_bytes(master)
    shards = _write_shards(
        tmp_path / "shards",
        {"E.toml": [_card_block("E1") + comment.encode(), _card_block("E2")]},
    )

    assert wb_plan.cmd_merge(shards, out, execute=True) == 0

    got = out.read_bytes().decode("utf-8")
    assert comment in got, f"块内注释丢了：{got[:400]!r}"
    assert got.count("这张卡的备注") == 1


def test_the_master_header_comments_are_kept(tmp_path: Path) -> None:
    """判据 3（续）：真总表表头那 2187 B 口径注释必须原样留在新总表里。"""
    master = _master_raw()
    cut = master.find(b"[[cards]]")
    header = master[:cut]
    out = tmp_path / "workbacklog.toml"
    out.write_bytes(master)
    shards = _write_shards(tmp_path / "shards", _split_by_prefix(master))

    assert wb_plan.cmd_merge(shards, out, execute=True) == 0

    assert out.read_bytes()[:cut] == header


# ---------------------------------------------------------------- 判据 4：只往末尾长

def test_a_new_card_is_appended_and_the_old_order_holds(tmp_path: Path) -> None:
    """判据 4：分片里有、总表里没有的卡 ⇒ 追加末尾；既有卡顺序一律不动。"""
    master = _master_raw()
    out = tmp_path / "workbacklog.toml"
    out.write_bytes(master)
    groups = _split_by_prefix(master)
    groups["LEGACY.toml"].append(_card_block("E999"))       # 新卡：塞在中间那片里
    shards = _write_shards(tmp_path / "shards", groups)

    assert wb_plan.cmd_merge(shards, out, execute=True) == 0

    old_ids = [card_id for card_id, _ in _blocks(master)]
    new_ids = [card_id for card_id, _ in _blocks(out.read_bytes())]
    assert new_ids[: len(old_ids)] == old_ids, "既有卡的相对顺序被挤动了"
    assert new_ids[-1] == "E999", f"新卡没长在末尾：{new_ids[-3:]}"
    assert len(new_ids) == len(old_ids) + 1


# ---------------------------------------------------------------- 判据 5：纯 CRLF

def test_what_merge_writes_is_pure_crlf(tmp_path: Path) -> None:
    """判据 5：落盘必须是纯 CRLF —— 台账自己的硬规矩（`ledger.non_crlf_lines() == 0`）。"""
    master = _master_raw()
    out = tmp_path / "workbacklog.toml"
    out.write_bytes(master)
    shards = _write_shards(tmp_path / "shards", _split_by_prefix(master))

    assert wb_plan.cmd_merge(shards, out, execute=True) == 0

    raw = out.read_bytes()
    assert pool_ledger.non_crlf_lines(raw) == 0, "merge 写出了裸 LF —— 台账不再合法"
    assert raw.count(b"\r\n") > 0


def test_a_bare_lf_shard_is_normalised_to_crlf(tmp_path: Path) -> None:
    """判据 5（续）：分片本身是裸 LF（标准差分片常这样）⇒ 落盘仍要纯 CRLF。"""
    head = SHARD_HEAD.replace(b"\r\n", b"\n")
    body = _card_block("E1").replace(b"\r\n", b"\n")
    shards = tmp_path / "shards"
    shards.mkdir()
    (shards / "E.toml").write_bytes(head + body)
    out = tmp_path / "workbacklog.toml"

    assert wb_plan.cmd_merge(shards, out, execute=True) == 0

    raw = out.read_bytes()
    assert pool_ledger.non_crlf_lines(raw) == 0
    assert [c for c, _ in _blocks(raw)] == ["E1"]


# ---------------------------------------------------------------- 判据 6：既有行为

def test_merge_without_shards_stays_a_noop(tmp_path: Path) -> None:
    """判据 6：没有分片 ⇒ 仍 `merge_shards() is None`、`cmd_merge(...) == 0`、不写盘。"""
    out = tmp_path / "workbacklog.toml"
    assert wb_plan.merge_shards(tmp_path / "empty") is None
    assert wb_plan.cmd_merge(tmp_path / "empty", out, execute=True) == 0
    assert not out.exists()


def test_a_duplicate_card_id_still_fails_with_two(tmp_path: Path) -> None:
    """判据 6：跨片重号 ⇒ 仍退 2（既有判据一字不变）。"""
    shards = _write_shards(
        tmp_path / "shards",
        {"A.toml": [_card_block("E1")], "B.toml": [_card_block("E1")]},
    )
    out = tmp_path / "workbacklog.toml"
    assert wb_plan.cmd_merge(shards, out, execute=True) == 2
    assert not out.exists()


def test_without_execute_it_only_prints(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """判据 6：不带 `--execute` ⇒ 只打印、不落盘。"""
    shards = _write_shards(tmp_path / "shards", {"E.toml": [_card_block("E1")]})
    out = tmp_path / "workbacklog.toml"

    assert wb_plan.cmd_merge(shards, out, execute=False) == 0

    assert not out.exists(), "带了 --execute 才许落盘"
    printed = capsys.readouterr().out
    assert "[[cards]]" in printed and "E1" in printed
