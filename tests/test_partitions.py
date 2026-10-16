r"""分区前缀（`tools/wb_plan.py` / `docs/partitions.toml`，卡 262 · T-G383）的测试。

**为什么值当测**：多个主控共用一个卡池，卡号会撞（都写 261）。分区前缀（`A261`）把号
按主控拆开 —— 但拆开之后有两件事**必须仍然成立**：① 旧号（纯数字）**行为一字不变**；
② 分区只避免**号**撞，**不避免文件**撞（两个分区各写一张卡、都声明同一文件时，
`check` 照样要报并点名）。下面按卡规格那四条判据逐条钉：

| 判据 | 钉什么 |
|---|---|
| J1 | 新卡 `A261` 在**登记 / 派活 / 落地**三处都通；旧号 `261` 一字不变 |
| J2 | 两分区同号（`A1`/`B1`）不报；两分区声明同一文件 ⇒ 报并点名 |
| J3 | 同号**同分区**（`A1` 两次）⇒ 拒 |
| J4 | `wb_daily.py` 按分区分别列待人 |

★ 只造**纯数据**（临时 TOML / `Card` / `Backlog`），不建树、不派活、不提交。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_daily  # noqa: E402 —— J4 直调它的 build_page（它自己带 NO_WINDOW）
import wb_dispatch  # noqa: E402 —— J1 派活侧：queue_files 要能找到分片里的卡
import wb_plan  # noqa: E402 —— 主角
import wb_task  # noqa: E402 —— J1 登记侧
from pool import plan as pool_plan  # noqa: E402 —— 旧号不变量做对照

SEED = ROOT / "docs" / "workbacklog.toml"


# ---------------------------------------------------------------- 夹具 / 小工具

def _card(cid: str, *, files: tuple[str, ...] = ("a.py",), tree: str = "",
          task: str = "T-ZZZ1", title: str = "样卡", depends: tuple[str, ...] = (),
          risk: str = "low", status: str = "pending", spec: str = "") -> wb_plan.Card:
    return wb_plan.Card(id=cid, task=task, title=title, tree=tree, spec=spec,
                        files=tuple(files), depends=tuple(depends), risk=risk, status=status)


def _backlog(*cards: wb_plan.Card) -> wb_plan.Backlog:
    return wb_plan.Backlog(reviewed="abc1234", cards=tuple(cards))


def _card_toml(cid: str, *, files: tuple[str, ...] = ("a.py",), tree: str = "",
               task: str = "T-ZZZ1", status: str = "pending") -> str:
    body = json.dumps(list(files))
    return (f'[[cards]]\nid = "{cid}"\ntask = "{task}"\ntitle = "样卡"\n'
            f'tree = "{tree}"\nspec = ""\nfiles = {body}\ndepends = []\n'
            f'risk = "low"\nstatus = "{status}"\n')


def _shard(directory: Path, name: str, *cards: str, reviewed: str = "abc1234") -> Path:
    """写一片台账分片（`docs/backlog/<分区>.toml`）。"""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(f'[base]\nreviewed = "{reviewed}"\n\n' + "\n".join(cards),
                    encoding="utf-8")
    return path


# ================================================================ J1：新卡 A261 / 旧号 261

def test_split_and_prefix() -> None:
    """卡号拆解：`A261` → (A, 261)；`261` → ("", 261)；认不出的形态 ⇒ `PartitionError`。"""
    assert wb_plan.split_card_id("A261") == ("A", "261")
    assert wb_plan.split_card_id("261") == ("", "261")
    assert wb_plan.card_prefix("A261") == "A"
    assert wb_plan.card_prefix("261") == ""
    assert wb_plan.card_prefix("M-1") == ""          # 别名成员号：认不出但**不抛**
    for bad in ("", "A-261", "M-1", "卡A", "A"):
        with pytest.raises(wb_plan.PartitionError):
            wb_plan.split_card_id(bad)


def test_partition_of_legacy_and_prefixed(tmp_path: Path) -> None:
    """现有 240–261 一律归 A；带前缀的新号归前缀；认不出 ⇒ 抛。"""
    partitions = wb_plan.load_partitions(ROOT / "docs" / "partitions.toml")
    assert partitions is not None
    assert wb_plan.partition_of("B261", partitions) == "B"      # 前缀优先
    assert wb_plan.partition_of("261", partitions) == "A"       # 旧号区间 → A
    assert wb_plan.partition_of("250", partitions) == "A"
    assert wb_plan.partition_of("999", partitions) == "A"       # 区间外 → default A
    with pytest.raises(wb_plan.PartitionError):
        wb_plan.partition_of("M-1", partitions)


def test_new_card_works_in_register_dispatch_land(tmp_path: Path) -> None:
    """★ J1：`A261` 在**登记 / 派活 / 落地**三处都通。

    · 登记：分片里登记 A261（树 .wt/A261）⇒ 合并后读得到；
    · 派活：建树命令 = `git worktree add -b card/A261 .wt/A261 <base>`、派活 argv 带 `--card A261`；
    · 落地：合并成总表后 `id = "A261"` 在，且能被 `load_backlog` 读回（登记→派活→落地一条链）。
    """
    shards = tmp_path / "shards"
    _shard(shards, "A.toml", _card_toml("A261", tree=".wt/A261"))
    backlog = wb_plan.load_sharded_backlog(tmp_path / "none.toml", shards)
    assert [c.id for c in backlog.cards] == ["A261"]

    # 派活：树 / 分支都带上分区前缀（卡号本身就是 A261）
    commands = wb_plan.worktree_commands(backlog, "1969b46")
    assert commands[0][1] == "git worktree add -b card/A261 .wt/A261 1969b46"
    argv = wb_plan.dispatch_argv(backlog.cards[0])
    assert "A261" in argv and "--card" in argv

    # 落地：合并成只读总表 → 能被 load_backlog 读回
    merged = wb_plan.merge_shards(shards)
    assert merged is not None
    out = tmp_path / "workbacklog.toml"
    out.write_text(wb_plan.render_merged_toml(merged), encoding="utf-8")
    assert [c.id for c in wb_plan.load_backlog(out).cards] == ["A261"]


def test_legacy_number_behaviour_unchanged(tmp_path: Path) -> None:
    """★ J1 反例：旧号（纯数字）行为一字不变 —— 无分片时读的就是总表，逐字一致。"""
    assert ([c.id for c in wb_plan.load_sharded_backlog(SEED).cards]
            == [c.id for c in pool_plan.load_backlog(SEED).cards])
    legacy = _backlog(_card("261", files=("x.py",), tree=".wt/261"))
    # 旧号的建树/派活命令与从前完全一样（没有多出任何前缀）
    assert wb_plan.worktree_commands(legacy, "abc1234")[0][1] == \
        "git worktree add -b card/261 .wt/261 abc1234"
    # 分区命名判据**不碰**旧号（旧队列不该被新规矩误伤）
    partitions = wb_plan.load_partitions(ROOT / "docs" / "partitions.toml")
    assert wb_plan.validate_partition_naming(_backlog(_card("261", tree=".wt/whatever")),
                                             partitions) == []


def test_partition_naming_rejects_unregistered_and_bad_tree() -> None:
    """分区命名判据：前缀没登记 ⇒ 报；树名不以分区前缀开头 ⇒ 报（只对新卡生效）。"""
    partitions = wb_plan.load_partitions(ROOT / "docs" / "partitions.toml")
    unregistered = wb_plan.validate_partition_naming(
        _backlog(_card("X1", tree=".wt/X1")), partitions)
    assert any("X1" in p and "没在" in p for p in unregistered), unregistered
    bad_tree = wb_plan.validate_partition_naming(
        _backlog(_card("A1", tree=".wt/B1")), partitions)
    assert any("A1" in p and "树名" in p for p in bad_tree), bad_tree
    good = wb_plan.validate_partition_naming(_backlog(_card("A1", tree=".wt/A1")), partitions)
    assert good == []


# ================================================================ J2：跨分区同号 / 同文件

def test_same_number_different_partition_is_allowed(tmp_path: Path) -> None:
    """★ J2：两分区各写一张卡、号可以同（`A1`/`B1`）—— `check` **不报**（不同号）。"""
    shards = tmp_path / "shards"
    _shard(shards, "A.toml", _card_toml("A1", files=("a.py",), tree=".wt/A1"))
    _shard(shards, "B.toml", _card_toml("B1", files=("b.py",), tree=".wt/B1"))
    backlog = wb_plan.load_sharded_backlog(tmp_path / "none.toml", shards)
    assert [c.id for c in backlog.cards] == ["A1", "B1"]
    assert wb_plan.validate(backlog) == []
    assert wb_plan.main(["check", "--shards", str(shards)]) == 0


def test_cross_partition_same_file_is_reported_and_named(tmp_path: Path) -> None:
    """★★ J2：两分区声明**同一文件** ⇒ 必须报并**点名**（分区只避免号撞，不避免文件撞）。"""
    shards = tmp_path / "shards"
    _shard(shards, "A.toml", _card_toml("A1", files=("x.py", "a.py"), tree=".wt/A1"))
    _shard(shards, "B.toml", _card_toml("B1", files=("x.py", "b.py"), tree=".wt/B1"))
    backlog = wb_plan.load_sharded_backlog(tmp_path / "none.toml", shards)
    # ① 交接收敛：validate 报「同一文件两个写者」
    assert any("x.py" in p for p in wb_plan.validate(backlog)), wb_plan.validate(backlog)
    # ② 分区那一层也点名（A / B 各是谁）
    writers = wb_plan.cross_partition_writers(
        backlog, wb_plan.load_partitions(ROOT / "docs" / "partitions.toml"))
    assert len(writers) == 1, writers
    assert "A1" in writers[0] and "B1" in writers[0] and "x.py" in writers[0], writers


def test_check_fails_and_names_both_on_cross_partition(
    tmp_path: Path, capsys: pytest.CaptureFixture,
) -> None:
    """端到端：`check --shards` 在两分区撞同一文件时退 1，err 里点名两张卡与那个文件。"""
    shards = tmp_path / "shards"
    _shard(shards, "A.toml", _card_toml("A1", files=("x.py",), tree=".wt/A1"))
    _shard(shards, "B.toml", _card_toml("B1", files=("x.py",), tree=".wt/B1"))
    code = wb_plan.main(["check", "--shards", str(shards)])
    err = capsys.readouterr().err
    assert code == 1, err
    assert "A1" in err and "B1" in err and "x.py" in err, err
    assert "[跨分区]" in err, err


def test_same_partition_intersection_is_not_cross_reported() -> None:
    """反向：**同分区**两卡撞同一文件 ⇒ cross_partition_writers 不报（那是 validate 的活）。"""
    partitions = wb_plan.load_partitions(ROOT / "docs" / "partitions.toml")
    backlog = _backlog(_card("A1", files=("x.py",), tree=".wt/A1"),
                       _card("A2", files=("x.py",), tree=".wt/A2"))
    assert wb_plan.cross_partition_writers(backlog, partitions) == []
    assert any("x.py" in p for p in wb_plan.validate(backlog))   # validate 照报


# ================================================================ J3：同号同分区 ⇒ 拒

def test_same_number_same_partition_is_rejected(tmp_path: Path) -> None:
    """★ J3：故意用同号**且同分区**（一片里两个 `A1`）⇒ 必须拒。"""
    shards = tmp_path / "shards"
    _shard(shards, "A.toml",
           _card_toml("A1", files=("a.py",), tree=".wt/A1"),
           _card_toml("A1", files=("b.py",), tree=".wt/A1x"))
    with pytest.raises(wb_plan.BacklogError, match="卡号重复：A1"):
        wb_plan.load_sharded_backlog(tmp_path / "none.toml", shards)


def test_duplicate_across_shards_is_rejected(tmp_path: Path) -> None:
    """反例：同号同分区**跨两片**（A.toml 与 A2.toml 都写 A1）⇒ 合并时拒。"""
    shards = tmp_path / "shards"
    _shard(shards, "A.toml", _card_toml("A1", files=("a.py",), tree=".wt/A1"))
    _shard(shards, "A2.toml", _card_toml("A1", files=("b.py",), tree=".wt/A1"))
    with pytest.raises(wb_plan.BacklogError, match="卡号重复：A1"):
        wb_plan.load_sharded_backlog(tmp_path / "none.toml", shards)


def test_same_number_different_partition_not_duplicate(tmp_path: Path) -> None:
    """反向：同号**不同分区**（A1 / B1）不算重复 —— 分区的价值就在这。"""
    shards = tmp_path / "shards"
    _shard(shards, "A.toml", _card_toml("A1", files=("a.py",), tree=".wt/A1"))
    _shard(shards, "B.toml", _card_toml("B1", files=("b.py",), tree=".wt/B1"))
    backlog = wb_plan.load_sharded_backlog(tmp_path / "none.toml", shards)
    assert [c.id for c in backlog.cards] == ["A1", "B1"]   # 号尾同 1、分区不同 ⇒ 允许


# ================================================================ J4：wb_daily 按分区列待人

def _write_total(root: Path, *cards: str) -> Path:
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    path = docs / "workbacklog.toml"
    path.write_text('[base]\nreviewed = "abc1234"\n\n' + "\n".join(cards), encoding="utf-8")
    return path


def test_wb_daily_lists_pending_by_partition(tmp_path: Path) -> None:
    """★ J4：`wb_daily.py` 按分区分别列待人 —— 待派里 A/B 两个分区的卡都看得到。

    `wb_daily` 读的是**合并后的总表**（`docs/workbacklog.toml`）⇒ 各分区的卡合并进总表之后，
    带分区前缀的号自然按分区可辨。这条直调 `build_page`（只读），不起服务。
    """
    _write_total(tmp_path,
                 _card_toml("A1", files=("a.py",), tree=".wt/A1"),
                 _card_toml("B1", files=("b.py",), tree=".wt/B1"),
                 _card_toml("B2", files=("c.py",), tree=".wt/B2", status="done"))
    page = wb_daily.build_page(tmp_path)
    pending = page["to_dispatch"]
    assert pending is not None, page["to_dispatch_note"]
    assert "A1" in pending and "B1" in pending, pending
    assert "B2" not in pending, pending          # done 的不列


def test_wb_daily_merges_shards_when_asked(tmp_path: Path) -> None:
    """落地链路：`merge` 把各分区合并进总表 ⇒ `wb_daily` 就按分区列出来了。"""
    shards = tmp_path / "docs" / "backlog"
    _shard(shards, "A.toml", _card_toml("A1", files=("a.py",), tree=".wt/A1"))
    _shard(shards, "B.toml", _card_toml("B1", files=("b.py",), tree=".wt/B1"))
    out = tmp_path / "docs" / "workbacklog.toml"
    assert wb_plan.cmd_merge(shards, out, execute=True) == 0
    assert out.is_file()
    page = wb_daily.build_page(tmp_path)
    assert set(page["to_dispatch"] or []) == {"A1", "B1"}, page["to_dispatch"]


# ================================================================ 登记 / 派活 两侧的连通

def test_wb_task_accepts_prefixed_member_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """★ J1 登记侧：栅栏的成员号可以是带分区前缀的 `A261` —— `wb_task.py register` 收。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path / "batch"))
    man = tmp_path / "B-X.toml"
    man.write_text('id = "B-X"\nwhy = "分区前缀自证"\non_complete = ["draft"]\n'
                   '\n[[member]]\nid = "A261"\nlayer = "框架层"\nwhat = "分区前缀"\n'
                   'paths = ["tools/wb_plan.py"]\n', encoding="utf-8")
    assert wb_task.main(["register", str(man)]) == 0
    assert (tmp_path / "batch" / "B-X.json").is_file()


def test_wb_task_warns_when_members_span_partitions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    """登记侧的**只报不拒**提醒：成员跨分区 ⇒ stderr 一句，退出码仍是 0。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path / "batch"))
    mixed = tmp_path / "B-MIX.toml"
    mixed.write_text('id = "B-MIX"\nwhy = "跨分区自证"\non_complete = ["draft"]\n'
                     '\n[[member]]\nid = "A1"\nlayer = "框架层"\nwhat = "甲"\n'
                     'paths = ["tools/a.py"]\n'
                     '\n[[member]]\nid = "B1"\nlayer = "框架层"\nwhat = "乙"\n'
                     'paths = ["tools/b.py"]\n', encoding="utf-8")
    assert wb_task.main(["register", str(mixed)]) == 0
    err = capsys.readouterr().err
    assert "[提醒]" in err and "多个分区" in err, err


def test_wb_dispatch_queue_files_finds_prefixed_card_in_shard(tmp_path: Path) -> None:
    """★ J1 派活侧：`queue_files` 先合分片 ⇒ 分片里的 `A261` 也能查到冲突域（守卫不误拒）。"""
    _shard(tmp_path / "docs" / "backlog", "A.toml",
           _card_toml("A261", files=("tools/wb_plan.py",), tree=".wt/A261"))
    files, why = wb_dispatch.queue_files("A261", root=tmp_path)
    assert why is None, why
    assert files == ["tools/wb_plan.py"]


# ================================================================ 登记表 / merge 的边角

def test_load_partitions_missing_returns_none(tmp_path: Path) -> None:
    """登记表不在 ⇒ `None`（不崩）；坏 TOML ⇒ `PartitionError`（不静默）。"""
    assert wb_plan.load_partitions(tmp_path / "nope.toml") is None
    bad = tmp_path / "partitions.toml"
    bad.write_text("[legacy\n", encoding="utf-8")
    with pytest.raises(wb_plan.PartitionError):
        wb_plan.load_partitions(bad)


def test_merge_without_shards_is_a_noop(tmp_path: Path) -> None:
    """没有分片 ⇒ `merge_shards` 返回 `None`、`cmd_merge` 报「没有台账分片」且不写盘。"""
    assert wb_plan.merge_shards(tmp_path / "empty") is None
    out = tmp_path / "workbacklog.toml"
    assert wb_plan.cmd_merge(tmp_path / "empty", out, execute=True) == 0
    assert not out.exists()


def test_check_without_backlog_option_uses_shards(tmp_path: Path) -> None:
    """反例：`check` 默认读 `--shards` 指向的分片（不给 `--backlog` 也读得到两张卡）。"""
    shards = tmp_path / "shards"
    _shard(shards, "A.toml", _card_toml("A1", files=("a.py",), tree=".wt/A1"))
    assert wb_plan.main(["check", "--shards", str(shards)]) == 0
