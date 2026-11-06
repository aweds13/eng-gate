"""钉子：台账分片**启用**（卡 E89 · `T-AG596`）—— 写侧落片、覆盖守卫、静默读者、真件切换。

## 为什么这些用例存在

`docs/workbacklog.toml` 从此是**只读聚合产物**（`tools/wb_plan.py merge --execute` 写回），
各分区各写 `docs/backlog/<分区>.toml`。四组缺陷全部用真件复现过，每组建在这里：

1. **写侧硬编码单文件**：`ledger.add_card()` 与 `landing.flip_card_status()` 都写死总表
   ⇒ 新卡不在任何分片（合并时被覆盖守卫永久挡住）、翻好的 done 下次合并被分片顶回 pending。
2. **分片集合不全时静默少卡**（本卡核心）：只建一片时 `load_sharded_backlog` 静默返子集，
   而 `gates/defs/` 里没有任何一道门看队列 ⇒ 少 107 张卡没人会红。
3. **静默型读者**：`pipeline_view` / `gen_pool_readme` / `wb_tree` / `wt_prune` / `wb_flow`
   只看总表 ⇒ 少卡、少告警；`wt_prune` 那一处还会把**未完工**的树当垃圾删（不可逆）。
4. **切换没有安全网**：真件拆七片再合并必须**逐字节**相同；抽掉一片必须被拒。

夹具一律 `tempfile.mkdtemp()` 到**仓外**：`ledger.main_root()` 走 `git rev-parse
--git-common-dir`，仓内沙箱会解析回主仓根、`add_card()` 会去写**真台账**（实测踩过）。
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import pipeline_view  # noqa: E402  —— 需要先把 tools/ 挂上
import wb_flow  # noqa: E402
import wb_plan  # noqa: E402
import wb_tree  # noqa: E402
import wt_prune  # noqa: E402
from pool import landing, ledger  # noqa: E402
from pool.plan import BacklogError  # noqa: E402

BASE = '[base]\nreviewed = "00000000"\n\n'


def _card(card_id: str, task: str, *, status: str = "pending",
          files: tuple[str, ...] = ("x.txt",)) -> str:
    """一张卡的块文本（字段顺序与 `ledger.render_card()` 同）。"""
    listed = ", ".join('"' + f + '"' for f in files)
    return (
        "[[cards]]\n"
        'id = "' + card_id + '"\n'
        'task = "' + task + '"\n'
        'title = "卡 ' + card_id + '"\n'
        'tree = ".wt/' + card_id + '"\n'
        'spec = "x/' + card_id + '.md"\n'
        "files = [" + listed + "]\n"
        "depends = []\n"
        'risk = "low"\n'
        'status = "' + status + '"\n'
    )


def _write_crlf(path: Path, text: str) -> None:
    """按纯 CRLF 落盘（台账的硬规矩：裸 LF 会被 `ledger` 判「不是纯 CRLF」）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))


def _git(repo: Path, *argv: str) -> None:
    """在沙箱里跑一条 git（身份与 CRLF 都现配，不吃宿主配置）。"""
    proc = subprocess.run(["git", *argv], cwd=str(repo), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise AssertionError(f"git {argv} 失败：{proc.stderr}")


def _sandbox(prefix: str, *, master: str | None, shards: dict[str, str]) -> Path:
    """仓外沙箱：`master` 为 None ⇒ 没有总表；`shards` 是 `{文件名: 内容}`。"""
    root = Path(tempfile.mkdtemp(prefix=prefix))
    assert ledger.main_root(root) == root.resolve(), "沙箱解析回了别的仓根 —— 会写真台账"
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    if master is not None:
        _write_crlf(docs / "workbacklog.toml", master)
    for name, text in shards.items():
        _write_crlf(docs / "backlog" / name, text)
    shutil.copy2(ROOT / "docs" / "partitions.toml", docs / "partitions.toml")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "e89@example.invalid")
    _git(root, "config", "user.name", "E89")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed")
    return root


@pytest.fixture()
def sharded_repo() -> Path:
    """总表只有 C2（done），分片 C.toml 有 C1（pending）+ C2 —— 分片盖住总表。"""
    root = _sandbox("e89-enabled-",
                    master=BASE + _card("C2", "T-AG902", status="done"),
                    shards={"C.toml": BASE + _card("C1", "T-AG901")
                            + _card("C2", "T-AG902", status="done")})
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ============================================================ 1. 写侧：立卡落片


def test_add_card_lands_in_the_partition_shard(sharded_repo: Path) -> None:
    """判据 1：带前缀的新卡落 `docs/backlog/<分区>.toml`，**总表字节一字未变**。

    反向：把 `ledger.target_path()` 里的分片分支删掉（一律总表）⇒ 这条红
    （总表被写、`E.toml` 不存在）。
    """
    master = sharded_repo / "docs" / "workbacklog.toml"
    before = master.read_bytes()
    ledger.add_card(sharded_repo, id="E900", task="T-AG900", title="卡 E900",
                    tree=".wt/E900", spec="x/E900.md", files=["tools/e900.py"])
    assert master.read_bytes() == before, "启用分片后总表不许再被立卡写"
    shard = sharded_repo / "docs" / "backlog" / "E.toml"
    assert shard.is_file(), sorted(p.name for p in (sharded_repo / "docs" / "backlog").iterdir())
    ids = [card.id for card in wb_plan.load_sharded_backlog(master, shard.parent).cards]
    assert "E900" in ids, ids
    assert "T-AG900" in shard.read_text(encoding="utf-8")


def test_add_card_refuses_a_duplicate_in_another_shard() -> None:
    """判据 1：查重**跨全部文件** —— 同一张卡不许在两片各有一份。

    现场形状：`C1` 还留在 `A.toml`（分区改过 / 旧号按 `[legacy] default` 归 A），
    而它现在该落 `C.toml` —— 只看目标文件就会**再写一份**（同号两处，合并时重号）。

    反向：把 `add_card` 的跨文件查重删掉（只看目标文件）⇒ 这条红（`C.toml` 里多出一张 C1）。
    """
    root = _sandbox("e89-enabled-dup-",
                    master=BASE + _card("C2", "T-AG902", status="done"),
                    shards={"A.toml": BASE + _card("C1", "T-AG901"),
                            "C.toml": BASE + _card("C2", "T-AG902", status="done")})
    try:
        verdict = ledger.add_card(root, id="C1", task="T-AG901", title="重复",
                                  tree=".wt/C1", spec="x/C1.md", files=["x.txt"])
        assert verdict == "already", verdict
        assert "C1" not in (root / "docs" / "backlog" / "C.toml").read_text(encoding="utf-8")
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ============================================================ 2. 写侧：翻账落片


def test_flip_card_status_writes_into_the_shard(sharded_repo: Path) -> None:
    """判据 1：`flip_card_status` 翻的是分片那一份，总表不动；合并后仍是 done。

    反向：把 `_queue_file_for()` 换回恒返总表 ⇒ 这条红（C1 的分片仍是 pending）。
    """
    master = sharded_repo / "docs" / "workbacklog.toml"
    folder = sharded_repo / "docs" / "backlog"
    before = master.read_bytes()
    assert landing.flip_card_status(sharded_repo, "C1", "T-AG901") == "flipped"
    assert master.read_bytes() == before, "翻账不许再写总表（它是 merge 的产物）"
    assert 'status = "done"' in (folder / "C.toml").read_text(encoding="utf-8")
    assert wb_plan.cmd_merge(folder, master, execute=True) == 0
    merged = master.read_bytes().decode("utf-8")
    assert 'status = "pending"' not in merged, merged


# ============================================================ 3. 覆盖守卫：少片必须响亮


def test_missing_shards_raise_and_name_the_gap() -> None:
    """判据 2：分片没盖住总表 ⇒ 抛 `BacklogError` 并点名缺几张，**不许返子集**。

    反向：把 `load_sharded_backlog` 的覆盖比对整段删掉 ⇒ 这条红（静默返 1 张）。
    """
    root = _sandbox(
        "e89-enabled-gap-",
        master=BASE + _card("A1", "T-AG801") + _card("B1", "T-AG802") + _card("C1", "T-AG901"),
        shards={"A.toml": BASE + _card("A1", "T-AG801")},
    )
    try:
        with pytest.raises(BacklogError) as caught:
            wb_plan.load_sharded_backlog(root / "docs" / "workbacklog.toml",
                                         root / "docs" / "backlog")
        message = str(caught.value)
        assert "分片没覆盖总表" in message, message
        assert "缺 2 张卡" in message, message
        assert "B1" in message and "C1" in message, message
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_shards_without_a_master_are_not_an_error() -> None:
    """判据 2 反向（**不算错**）：总表还没合出来、只有分片 —— 刚立的新卡就是这个阶段。

    反向：把「总表路径不存在 ⇒ 不比」那支删掉 ⇒ 这条红（抛异常或空队列）。
    """
    root = _sandbox("e89-enabled-nomaster-", master=None,
                    shards={"C.toml": BASE + _card("C1", "T-AG901")})
    try:
        backlog = wb_plan.load_sharded_backlog(root / "docs" / "workbacklog.toml",
                                               root / "docs" / "backlog")
        assert [card.id for card in backlog.cards] == ["C1"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ============================================================ 4. 静默型读者（五个）


def _load_gen_pool_readme():
    """`scripts/` 不是包 ⇒ 按路径加载（与既有测试同一手法）。"""
    src = ROOT / "scripts" / "gen_pool_readme.py"
    spec = importlib.util.spec_from_file_location("gen_pool_readme_under_e89_enabled", src)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_pipeline_view_sees_the_shard_card(sharded_repo: Path) -> None:
    """判据 3：`pipeline_view.read_cards` 看得见只在分片里的 C1（工作台 / 面板同源）。"""
    reading = pipeline_view.read_cards(sharded_repo)
    assert reading["cards"] is not None, reading.get("cards_note")
    ids = [card["id"] for card in reading["cards"]]
    assert "C1" in ids and "C2" in ids, ids


def test_pipeline_view_fingerprint_follows_the_shards(sharded_repo: Path) -> None:
    """判据 3：缓存指纹的来源清单跟着读法走（否则改分片不重算 ⇒ 静默少卡）。"""
    shard = sharded_repo / "docs" / "backlog" / "C.toml"
    assert pipeline_view._backlog_sources(sharded_repo) == [shard]


def test_gen_pool_readme_counts_the_shard_card(sharded_repo: Path) -> None:
    """判据 3：`backlog_metrics` 按分片数（2 张 / 1 done / 1 pending），且不告警。"""
    mod = _load_gen_pool_readme()
    total, done, pending, warns = mod.backlog_metrics(sharded_repo, sharded_repo)
    assert (total, done, pending) == (2, 1, 1), (total, done, pending)
    assert warns == [], warns


def test_wb_tree_sees_the_shard_card(sharded_repo: Path) -> None:
    """判据 3：卡谱系树里有分片卡（`task -> 卡号` 与 `卡号 -> 记录` 两张表）。"""
    by_task, by_id = wb_tree.load_cards(sharded_repo)
    assert by_task.get("T-AG901") == "C1", by_task
    assert "C1" in by_id and "C2" in by_id, sorted(by_id)


def test_wt_prune_keeps_the_tree_of_a_shard_card(sharded_repo: Path) -> None:
    """判据 3（最要紧）：分片里的 pending 卡算「占着树」—— 否则未完工的树被删，不可逆。"""
    claimed = wt_prune.backlog_pending_trees(sharded_repo)
    assert claimed is not None, "判不了 = 保留；这里不该判不了"
    key = wt_prune._norm(sharded_repo / ".wt" / "C1")
    assert key in claimed, sorted(claimed)
    assert "C1" in claimed[key], claimed[key]


def test_wb_flow_reads_the_shard_cards(sharded_repo: Path, monkeypatch) -> None:
    """判据 3 + 5：`wb_flow.load_backlog` 读分片；取历史的 pathspec 同时带 `docs/backlog`。"""
    monkeypatch.setattr(wb_flow, "BACKLOG", sharded_repo / "docs" / "workbacklog.toml")
    ids = [str(card.get("id") or "") for card in wb_flow.load_backlog()]
    assert "C1" in ids and "C2" in ids, ids
    seen: list[list[str]] = []

    def fake_run(argv, **kwargs):  # noqa: ANN001, ANN003 —— 只截 argv，别的原样收下
        seen.append(list(argv))
        return types.SimpleNamespace(stdout="")

    monkeypatch.setattr(wb_flow.subprocess, "run", fake_run)
    wb_flow._git_diff_ids("midnight")
    assert seen, "没调 git"
    assert seen[0][-2:] == ["docs/workbacklog.toml", "docs/backlog"], seen[0]


# ============================================================ 5. 真件切换：可核可回滚


def _split_real_backlog(raw: bytes, folder: Path) -> None:
    """把真总表按 `docs/partitions.toml` 拆成各片（块字节原样搬、reviewed 沿用总表）。"""
    header, pairs = wb_plan._split_master(raw)
    reviewed = wb_plan._reviewed_of(header)
    partitions = wb_plan.load_partitions()
    assert partitions is not None, "仓库里没有 docs/partitions.toml"
    per: dict[str, list[bytes]] = {}
    for card_id, block in pairs:
        per.setdefault(wb_plan.partition_of(card_id, partitions), []).append(block)
    for prefix, blocks in per.items():
        target = folder / (prefix + ".toml")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(wb_plan.shard_header(reviewed) + b"".join(blocks))


def test_real_backlog_split_then_merge_is_byte_identical() -> None:
    """判据 6：真件拆七片 → `merge --execute` **逐字节**相同；抽掉 A 片必须被拒。

    反向：把 `merge_lossless()` 换成按 TOML 重渲染（`render_merged_toml`）⇒ 这条红
    （表头注释与块内注释蒸发 ⇒ 字节不再相同）。
    """
    real = ROOT / "docs" / "workbacklog.toml"
    if not real.is_file():
        pytest.skip("这棵树上没有真总表")
    raw = real.read_bytes()
    root = Path(tempfile.mkdtemp(prefix="e89-enabled-real-"))
    try:
        master = root / "docs" / "workbacklog.toml"
        master.parent.mkdir(parents=True, exist_ok=True)
        master.write_bytes(raw)
        folder = root / "docs" / "backlog"
        folder.mkdir(parents=True, exist_ok=True)
        _split_real_backlog(raw, folder)
        assert len(list(folder.glob("*.toml"))) >= 5, sorted(p.name for p in folder.iterdir())
        assert wb_plan.cmd_merge(folder, master, execute=True) == 0
        assert master.read_bytes() == raw, "拆再合并必须逐字节相同"

        shard_a = folder / "A.toml"
        assert shard_a.is_file(), "真件里 A 片必然存在"
        shard_a.unlink()
        assert wb_plan.cmd_merge(folder, master, execute=True) == 1, "抽掉一片必须被拒"
        assert master.read_bytes() == raw, "被拒的那一趟不许改总表"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_partition_of_matches_every_real_card() -> None:
    """判据 6：真总表里**每一张卡**都判得出分区（判不出 ⇒ 落片会静默退回总表）。"""
    real = ROOT / "docs" / "workbacklog.toml"
    if not real.is_file():
        pytest.skip("这棵树上没有真总表")
    partitions = wb_plan.load_partitions()
    assert partitions is not None
    backlog = wb_plan.load_backlog(real)
    unknown = [card.id for card in backlog.cards if not wb_plan.partition_of(card.id, partitions)]
    assert unknown == [], unknown[:10]
