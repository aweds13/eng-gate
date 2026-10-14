r"""并发调度器（`tools/wb_plan.py`，台账号 T-G99 · 外包卡 010）的测试 —— 纯函数为主。

为什么值当测：这个工具干的是**决定"谁和谁能同时跑"**这件事。判错的代价不是"报个错"，而是
两张工人在**同一个文件 / 同一棵树**上同时写 —— 合并必冲突、audit 会因为两份台账条目互相盖而红，
而且要到收口那一刻才发现（那时两轮的活都白干了一半）。所以**六类拒单各钉一条**，外加两道
最容易漏的：拓扑分层要取**最长路径**（菱形依赖）、打包遇到"两两相交"要**各占一批**。

★ 只造**纯数据**（`Card` / `Backlog` / 临时 TOML），**不起服务、不建树、不派活** ——
"会动世界"的那一半（`--execute`）留作手工证据，不进测试（卡 010 §8 坑 1）。
★ 每条"拒单"用例本身就是**反空转**：它构造一份**故意坏掉**的 backlog 并断言判据真的咬了
（判据删掉/放宽 → 这条当场红）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import tomllib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_plan  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上
from pool import plan as pool_plan  # noqa: E402 —— find_spec 在逻辑层（卡 127 钉子要直测它）

SEED = ROOT / "docs" / "workbacklog.toml"


def _card(cid: str, *, files: tuple[str, ...] = ("a.py",), tree: str = "",
          task: str = "T-G9x", title: str = "样卡", depends: tuple[str, ...] = (),
          risk: str = "low", status: str = "pending", spec: str = "") -> wb_plan.Card:
    return wb_plan.Card(id=cid, task=task, title=title, tree=tree, spec=spec,
                        files=tuple(files), depends=tuple(depends), risk=risk, status=status)


def _backlog(*cards: wb_plan.Card) -> wb_plan.Backlog:
    return wb_plan.Backlog(reviewed="abc1234", cards=tuple(cards))


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "workbacklog.toml"
    path.write_text(body, encoding="utf-8")
    return path


# ------------------------------------------------------------------ 受保护集常量


def test_protected_set_is_exactly_the_six() -> None:
    """受保护共享文件集**没被写漏**（卡 010 §2.4 写死的六个，多一个少一个都红）。"""
    expected = frozenset({
        "docs/traceability.toml",
        "docs/changelog.md",
        "复盘/交接-重构进度.md",
        "复盘/新窗口交接卡.md",
        "gates/last.json",
        "gates/reuse.json",
    })
    assert set(wb_plan.PROTECTED_FILES) == set(expected)


@pytest.mark.parametrize("path", sorted(wb_plan.PROTECTED_FILES))
def test_every_protected_file_is_rejected(path: str) -> None:
    """每一个受保护文件**都被真拒**（常量里有、判据不认 = 假护栏）。"""
    problems = wb_plan.validate(_backlog(_card("007", files=(path,))))
    assert any("受保护共享文件" in p for p in problems), problems


# ------------------------------------------------------------------ ① 相交检测


def test_files_intersect_helper() -> None:
    a = _card("007", files=("x.py", "a.py"))
    b = _card("008", files=("x.py", "b.py"))
    c = _card("009", files=("z.py",))
    assert wb_plan.files_intersect(a, b) == {"x.py"}
    assert wb_plan.files_intersect(a, c) == set()


def test_intersection_is_rejected() -> None:
    """两卡 files 相交 → 拒单，且报出到底哪个文件。"""
    problems = wb_plan.validate(_backlog(
        _card("007", files=("tools/wb_dispatch.py",)),
        _card("008", files=("tools/wb_dispatch.py",)),
    ))
    assert any("相交" in p and "tools/wb_dispatch.py" in p for p in problems), problems


# ---------------------------------------- 卡 127：禁通配 + find_spec 精确（T-G225）
#
# ★ 这两条判据治 GLM 外部审查的 2.2b / 2.11：域写成通配 ⇒ 静默绕过冲突域检查；
#   找卡规格用 `*<号>*` 乱兜 ⇒ 卡号 `12` 会命中 `卡112-…` / `卡120-…`。
#   每条都是**反空转**：判据删掉/放宽 → 当场红。


def test_wildcard_in_files_is_rejected() -> None:
    """★ 2.2b：`files` 写 `tools/pool/*.py` ⇒ **拒单**，错误文本**点名**那张卡与该条目。

    `files_intersect()` 是精确匹配，含通配的域与任何精确路径都不相交 ⇒ 静默绕过冲突域检查。
    """
    problems = wb_plan.validate(_backlog(_card("007", files=("tools/pool/*.py",))))
    assert any("通配字符" in p and "007" in p and "tools/pool/*.py" in p
               for p in problems), problems


@pytest.mark.parametrize("bad", ["tools/pool/*.py", "tools/foo?.py", "tools/[ab].py"])
def test_each_wildcard_char_is_rejected(bad: str) -> None:
    """`*` / `?` / `[` **三个**都要咬（漏一个 = 假护栏）。"""
    problems = wb_plan.validate(_backlog(_card("007", files=(bad,))))
    assert any("通配字符" in p for p in problems), problems


def test_exact_files_pass_the_wildcard_rule() -> None:
    """② 全精确路径（真队列的形态）**不该**被新判据误伤。"""
    exact = ("tools/pool/plan.py", "tools/wb_plan.py", "tests/test_wb_plan.py")
    assert wb_plan.validate(_backlog(_card("007", files=exact))) == []


def test_find_spec_card_number_is_boundary_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ 2.11：`find_spec("12")` **不许**命中 `卡112-…` / `卡120-…`。

    造一棵临时树放这两张，断言 `12` 返回 `""`（找不到就**如实**说找不到，不猜最像的）。
    """
    monkeypatch.setattr(pool_plan, "ROOT", tmp_path)
    monkeypatch.setattr(pool_plan, "DIAG", tmp_path / "gates" / "diag")
    card_dir = tmp_path / "复盘" / "卡"
    card_dir.mkdir(parents=True)
    (card_dir / "卡112-切片误报.md").write_text("x", encoding="utf-8")
    (card_dir / "卡120-另一张.md").write_text("x", encoding="utf-8")
    assert pool_plan.find_spec("12") == ""


def test_find_spec_finds_existing_card_exactly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """④ 精确匹配对**存在**的卡号照样找得到（`卡<号>-…` 整段匹配），返回真实路径。"""
    monkeypatch.setattr(pool_plan, "ROOT", tmp_path)
    monkeypatch.setattr(pool_plan, "DIAG", tmp_path / "gates" / "diag")
    card_dir = tmp_path / "复盘" / "卡"
    card_dir.mkdir(parents=True)
    (card_dir / "卡108-号池.md").write_text("x", encoding="utf-8")
    assert pool_plan.find_spec("108") == "复盘/卡/卡108-号池.md"


# ------------------------------------------------------------------ ② 共享文件拒单（见上 ¶ 参数化）


# ------------------------------------------------------------------ ③ 同树拒单


def test_same_worktree_is_rejected() -> None:
    problems = wb_plan.validate(_backlog(
        _card("007", files=("a.py",), tree=".wt/x"),
        _card("008", files=("b.py",), tree=".wt/x"),
    ))
    assert any("同一棵树" in p for p in problems), problems


def test_main_tree_can_only_hold_one_card() -> None:
    """主树（""）也是"一棵树"—— 两张卡都用主树 = 拒单。"""
    problems = wb_plan.validate(_backlog(
        _card("007", files=("a.py",), tree=""),
        _card("008", files=("b.py",), tree=""),
    ))
    assert any("同一棵树" in p and "主树" in p for p in problems), problems


# ------------------------------------------------------------------ ④ depends 指向不存在的卡


def test_missing_dep_is_rejected() -> None:
    problems = wb_plan.validate(_backlog(
        _card("007", files=("a.py",), depends=("999",)),
    ))
    assert any("不存在的卡 999" in p for p in problems), problems


# ------------------------------------------------------------------ ⑤ 成环检测


def test_cycle_is_rejected() -> None:
    cards = (_card("007", files=("a.py",), depends=("008",)),
             _card("008", files=("b.py",), depends=("007",)))
    ring = wb_plan.find_cycle(cards)
    assert ring is not None and ring[0] == ring[-1]              # 首尾相接 = 闭环
    assert any("依赖成环" in p for p in wb_plan.validate(_backlog(*cards)))


def test_self_dependency_is_a_cycle() -> None:
    problems = wb_plan.validate(_backlog(_card("007", files=("a.py",), depends=("007",))))
    assert any("依赖成环" in p for p in problems), problems


# ------------------------------------------------------------------ ⑥ files 为空


def test_empty_files_is_rejected() -> None:
    problems = wb_plan.validate(_backlog(_card("007", files=())))
    assert any("files 为空" in p for p in problems), problems


# ------------------------------------------------------------------ 拓扑分层


def test_topo_layers_diamond() -> None:
    """菱形依赖：A→B、A→C、B→D、C→D → 三层 [A] / [B,C] / [D]。"""
    a = _card("A", files=("a.py",))
    b = _card("B", files=("b.py",), depends=("A",))
    c = _card("C", files=("c.py",), depends=("A",))
    d = _card("D", files=("d.py",), depends=("B", "C"))
    layers = wb_plan.topo_layers((a, b, c, d))
    assert [[x.id for x in layer] for layer in layers] == [["A"], ["B", "C"], ["D"]]


def test_topo_layers_takes_longest_path() -> None:
    """既依赖 0 层的 A、又依赖 1 层的 B → 必须在第 2 层（取**最长**路径，别提前到跟 B 同批）。"""
    a = _card("A", files=("a.py",))
    b = _card("B", files=("b.py",), depends=("A",))
    c = _card("C", files=("c.py",), depends=("A", "B"))
    layers = wb_plan.topo_layers((a, b, c))
    assert [[x.id for x in layer] for layer in layers] == [["A"], ["B"], ["C"]]


def test_topo_layers_raises_on_cycle() -> None:
    with pytest.raises(wb_plan.BacklogError, match="成环"):
        wb_plan.topo_layers((_card("A", depends=("B",)), _card("B", depends=("A",))))


# ------------------------------------------------------------------ 贪心打包


def test_greedy_pack_pairwise_intersecting_each_gets_own_batch() -> None:
    """同层三卡两两相交（都在 `x.py` 上）→ 只能各占一批（上限 3 不是约束，冲突域才是）。"""
    a = _card("A", files=("x.py", "a.py"))
    b = _card("B", files=("x.py", "b.py"))
    c = _card("C", files=("x.py", "c.py"))
    batches = wb_plan.greedy_pack((a, b, c), 3)
    assert [[x.id for x in batch] for batch in batches] == [["A"], ["B"], ["C"]]


def test_greedy_pack_respects_concurrency_limit() -> None:
    """三张零相交、各占一棵树 → 上限 2 时只能装 2 + 1（别的约束都不挡，才测得准上限）。"""
    cards = (_card("A", files=("a.py",), tree=".wt/a"),
             _card("B", files=("b.py",), tree=".wt/b"),
             _card("C", files=("c.py",), tree=".wt/c"))
    batches = wb_plan.greedy_pack(cards, 2)
    assert [[x.id for x in batch] for batch in batches] == [["A", "B"], ["C"]]


def test_greedy_pack_keeps_trees_unique_within_batch() -> None:
    """两卡 files 不相交、但同树 → 不许放同一批（一棵树只能一个写者）。"""
    cards = (_card("A", files=("a.py",), tree=".wt/x"),
             _card("B", files=("b.py",), tree=".wt/x"))
    batches = wb_plan.greedy_pack(cards, 2)
    assert [[x.id for x in batch] for batch in batches] == [["A"], ["B"]]


def test_greedy_pack_rejects_bad_limit() -> None:
    with pytest.raises(wb_plan.BacklogError):
        wb_plan.greedy_pack((_card("A"),), 0)


def test_plan_never_spans_layers() -> None:
    """依赖卡不许跟它依赖的卡同批（批次不跨层）。"""
    a = _card("A", files=("a.py",))
    b = _card("B", files=("b.py",), depends=("A",))
    batches = wb_plan.plan_batches(_backlog(a, b), 5)
    assert [[x.id for x in batch] for batch in batches] == [["A"], ["B"]]


# ------------------------------------------------------------------ 非法 backlog（文件坏）


def test_load_backlog_missing_file(tmp_path: Path) -> None:
    with pytest.raises(wb_plan.BacklogError, match="不存在"):
        wb_plan.load_backlog(tmp_path / "nope.toml")


def test_load_backlog_bad_toml(tmp_path: Path) -> None:
    with pytest.raises(wb_plan.BacklogError, match="不是合法 TOML"):
        wb_plan.load_backlog(_write(tmp_path, "[base\nreviewed = "))


def test_load_backlog_missing_base(tmp_path: Path) -> None:
    with pytest.raises(wb_plan.BacklogError, match=r"\[base\]"):
        wb_plan.load_backlog(_write(tmp_path, '[[cards]]\nid = "007"\n'))


def test_load_backlog_missing_field_is_clear(tmp_path: Path) -> None:
    body = ('[base]\nreviewed = "abc"\n\n[[cards]]\nid = "007"\ntask = "T-G96"\n'
            'title = "t"\ntree = ""\n')
    with pytest.raises(wb_plan.BacklogError, match="卡 007 缺字段 `spec`"):
        wb_plan.load_backlog(_write(tmp_path, body))


def test_load_backlog_duplicate_id_is_clear(tmp_path: Path) -> None:
    body = ('[base]\nreviewed = "abc"\n\n'
            '[[cards]]\nid = "007"\ntask = "t"\ntitle = "t"\ntree = ""\nspec = "s"\n'
            'files = ["a.py"]\n\n'
            '[[cards]]\nid = "007"\ntask = "t2"\ntitle = "t2"\ntree = ".wt/x"\nspec = "s2"\n'
            'files = ["b.py"]\n')
    with pytest.raises(wb_plan.BacklogError, match="卡号重复：007"):
        wb_plan.load_backlog(_write(tmp_path, body))


def test_load_backlog_files_must_be_array(tmp_path: Path) -> None:
    body = ('[base]\nreviewed = "abc"\n\n[[cards]]\nid = "007"\ntask = "t"\ntitle = "t"\n'
            'tree = ""\nspec = "s"\nfiles = "a.py"\n')
    with pytest.raises(wb_plan.BacklogError, match="必须是字符串数组"):
        wb_plan.load_backlog(_write(tmp_path, body))


# ------------------------------------------------------------------ 种子 backlog（在飞的 007~010）
#
# ★ 真文件 `docs/workbacklog.toml` 会随调度**继续追加卡**（卡 013 就追加了 014–020 七张）。
#   对它的**内容**做"恰好几张"式断言，必然被下一次追加撞红 —— 卡 010 原本那 5 条判据就是这么
#   在卡 013 上红的（`== ["007","008","009","010"]`、`"4 张卡 → 2 批"`）。所以这里分两层：
#   · 对**真文件**只钉**不变量**：能读 / 无冲突 / id 唯一 / 两个读法一致 / 四条种子在里头；
#   · 对**批次**改用一份**冻结夹具**（下面 `_SEED_FIXTURE_TOML` = 四条种子的一字不差副本）——
#     批次是调度器的**纯函数输出**，就该在**已知输入**上精确断言，与真文件的长短无关。


_SEED_FIXTURE_TOML = """\
[base]
reviewed = "1969b46"

[[cards]]
id = "007"
task = "T-G96"
title = "看门狗护栏补强"
tree = ""
spec = ""
files = [
  "tools/wb_dispatch.py",
  "tests/test_wb_dispatch.py",
  "复盘/看门狗护栏补强-T-G96.md",
]
depends = []
risk = "high"
status = "pending"

[[cards]]
id = "008"
task = "T-G97"
title = "面板口径对齐"
tree = ".wt/dash"
spec = ""
files = [
  "tools/wb_dash.py",
  "tests/test_wb_dash.py",
  "复盘/面板口径对齐-T-G97.md",
]
depends = []
risk = "mid"
status = "pending"

[[cards]]
id = "009"
task = "T-G98"
title = "myday序号根因"
tree = ".wt/core"
spec = ""
files = [
  "src/timeflow/core/tasks/manager.py",
  "tests/test_myday_rank_line.py",
  "复盘/myday序号根因-T-G98.md",
]
depends = []
risk = "high"
status = "pending"

[[cards]]
id = "010"
task = "T-G99"
title = "并发调度器"
tree = ".wt/plan"
spec = ""
files = [
  "tools/wb_plan.py",
  "tests/test_wb_plan.py",
  "docs/workbacklog.toml",
  "复盘/并发架构-T-G99.md",
]
depends = []
risk = "low"
status = "pending"
"""

_SEED_IDS = frozenset({"007", "008", "009", "010"})


def _seed_fixture(tmp_path: Path) -> Path:
    """四条种子的**冻结夹具**（写进临时目录的 TOML）—— 批次断言只认它，不认真文件。"""
    return _write(tmp_path, _SEED_FIXTURE_TOML)


def test_seed_backlog_loads_and_is_conflict_free() -> None:
    """真种子（`docs/workbacklog.toml`）必须能读、能过 check（这才是"能并行"的证据）。

    ★ 判据**不写死张数**（文件会随调度继续追加卡）：只钉**不变量** —— 能读、`validate` 返回空、
    id 唯一、四条种子是实际 id 集合的**子集**。批次的精确断言见下面的冻结夹具用例。
    """
    backlog = wb_plan.load_backlog(SEED)
    ids = [c.id for c in backlog.cards]
    assert len(ids) == len(set(ids)), f"卡号重复：{ids}"
    assert ids, "真 backlog 不该是空的（队列可以只剩一两张，但不能空）"
    assert wb_plan.validate(backlog) == []


def test_seed_toml_roundtrips_with_tomllib() -> None:
    """用 `tomllib` 读回来验一遍（卡 010 §8 坑 4：写 TOML 必须能读回）。

    ★ 钉的是**两个读法一致**（`tomllib` 与 `load_backlog` 读出同一串 id）+ 种子在里头 +
    没有受保护文件；**不写死张数**（文件会长）。
    """
    data = tomllib.loads(SEED.read_text(encoding="utf-8"))
    assert data["base"]["reviewed"]
    raw_ids = [c["id"] for c in data["cards"]]
    assert raw_ids == [c.id for c in wb_plan.load_backlog(SEED).cards]
    assert raw_ids, "真 backlog 不该是空的"
    # 受保护文件一个都不在种子里（作者不许碰）
    for card in data["cards"]:
        assert not (set(card["files"]) & wb_plan.PROTECTED_FILES)


def test_seed_plan_with_concurrency_three(tmp_path: Path) -> None:
    """`plan --concurrency 3` 在**四条种子**（冻结夹具）上 = 2 批：[007,008,009] + [010]。"""
    backlog = wb_plan.load_backlog(_seed_fixture(tmp_path))
    batches = wb_plan.plan_batches(backlog, 3)
    assert [[c.id for c in batch] for batch in batches] == [["007", "008", "009"], ["010"]]


def test_seed_plan_with_concurrency_two(tmp_path: Path) -> None:
    """上限 2 时四条种子（冻结夹具） = 2 批：[007,008] + [009,010]。"""
    backlog = wb_plan.load_backlog(_seed_fixture(tmp_path))
    batches = wb_plan.plan_batches(backlog, 2)
    assert [[c.id for c in batch] for batch in batches] == [["007", "008"], ["009", "010"]]


def test_seed_high_risk_cards_are_seeded(tmp_path: Path) -> None:
    """高风险卡（high = 才派对抗性复核）在**冻结夹具**上记录在案（不认真文件 —— 队列会变）。"""
    backlog = wb_plan.load_backlog(_seed_fixture(tmp_path))
    high = {c.id for c in backlog.cards if c.risk == "high"}
    assert high == {"007", "009"}


def test_seed_fixture_keeps_the_four_seeds(tmp_path: Path) -> None:
    """★ 四条种子在**冻结夹具**里必须在齐 —— 真文件那份是**待派队列**、完成的卡会移出。

    （这条接替原来钉在真文件上的「四条种子必须都在」断言：**覆盖一点没丢**，只是宿主从
    "会变的真文件"换成了"冻结夹具"。）
    """
    backlog = wb_plan.load_backlog(_seed_fixture(tmp_path))
    ids = [c.id for c in backlog.cards]
    assert set(ids) == set(_SEED_IDS), f"夹具里的种子应恰为四条：{sorted(ids)}"
    assert wb_plan.validate(backlog) == []


# ------------------------------------------------------------------ 命令拼装


def test_worktree_commands_skip_main_tree() -> None:
    backlog = _backlog(_card("007", files=("a.py",), tree=""),
                       _card("008", files=("b.py",), tree=".wt/dash"))
    commands = wb_plan.worktree_commands(backlog, "1969b46")
    assert [card.id for card, _ in commands] == ["008"]
    # ★ 卡 192（T-G292）：建树用 -b card/<号>（卡分支），不是 detached HEAD
    assert commands[0][1] == "git worktree add -b card/008 .wt/dash 1969b46"


def test_worktree_commands_use_card_branch_not_detach() -> None:
    """★ 卡 192：每张卡的建树命令都含 `-b card/<号>` —— detached HEAD 的提交没有 ref，
    `clone --mirror` 带不走、gc 会清掉（今晚卡 160 丢东西的根因）。"""
    backlog = _backlog(
        _card("A", files=("a.py",), tree=".wt/a"),
        _card("B", files=("b.py",), tree=".wt/b"),
    )
    for card, cmd in wb_plan.worktree_commands(backlog, "abc1234"):
        assert f"-b card/{card.id}" in cmd, cmd
        assert "--detach" not in cmd, cmd


def test_dispatch_argv_points_at_the_card() -> None:
    card = _card("008", spec="gates/diag/卡008-面板口径.md", tree=".wt/dash")
    argv = wb_plan.dispatch_argv(card)
    assert argv[:3] == ["python", "-X", "utf8"]
    assert "--card" in argv and "008" in argv
    assert "--spec" in argv and "gates/diag/卡008-面板口径.md" in argv
    assert argv[-2:] == ["--detach", "--execute"]


def test_dispatch_argv_carries_an_absolute_cwd_for_a_card_tree() -> None:
    """★ 卡 203：卡树的派活命令要带 `--cwd <该卡树绝对路径>` —— 登记树 = 工人树。

    ★ 绝对路径锚在**主树根**上（树标签就是"相对主树根"的），不是锚在"wb_plan 从哪跑"。
    """
    from pool import registry as pool_registry

    card = _card("008", spec="s.md", tree=".wt/dash")
    argv = wb_plan.dispatch_argv(card)
    assert "--cwd" in argv, argv
    assert "pushd" not in argv, argv
    cwd = argv[argv.index("--cwd") + 1]
    assert cwd == (pool_registry.main_tree_root() / ".wt/dash").as_posix(), cwd
    assert Path(cwd).is_absolute(), cwd


def test_dispatch_argv_omits_cwd_for_the_main_tree() -> None:
    """★ 卡 203：主树（`tree == ""`）**不给** `--cwd` —— 从主仓跑时标签仍是主树（`""`），
    工人看到的东西逐字不变（卡 166）。"""
    argv = wb_plan.dispatch_argv(_card("007", spec="s.md", tree=""))
    assert "--cwd" not in argv, argv
    assert "pushd" not in argv, argv


def test_render_dispatch_never_pushes_into_own_tree() -> None:
    """★ 卡 203：印的命令**不再 `pushd`**；卡树版**看得到 `--cwd`**（从主仓跑）。"""
    main = _card("007", spec="s.md", tree="")
    tree = _card("008", spec="s.md", tree=".wt/dash")
    rendered_main = wb_plan.render_dispatch(main)
    rendered_tree = wb_plan.render_dispatch(tree)
    assert "pushd" not in rendered_main, rendered_main
    assert "pushd" not in rendered_tree, rendered_tree
    assert "--cwd" in rendered_tree, rendered_tree
    assert rendered_tree == " ".join(wb_plan.dispatch_argv(tree)), rendered_tree


# ------------------------------------------------------------------ 子命令（主线）


def test_check_command_passes_on_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ 卡 234（T-G351）：注入**空栅栏目录** —— 这条测试不许因主仓多了条围栏就红。

    栅栏从哪来：`find_gate_drift` → `pool.task.batch_dir()` 没有覆盖时读**主树根**的
    `gates/diag/batch/`（`main_tree_root()` 用 `git rev-parse --git-common-dir` 解析 ——
    在卡树里跑也指向主仓）。旧夹具真队列 × 真栅栏：worktree 的 SEED 是基点副本（没有卡 231），
    主仓栅栏却是实时的（B-20261020 有成员 231）⇒ 兜底乱兜到 done 的卡 164 ⇒ 假漂移 ⇒ 红。
    `TF_BATCH_DIR` 是既有注入点（卡 212 那族全用它）；真队列 × 真栅栏的一致性是收口时
    `wb_plan.py check` 的事，不归夹具管。
    """
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path))
    assert wb_plan.main(["check", "--backlog", str(SEED)]) == 0


def test_check_command_fails_on_conflict(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    body = ('[base]\nreviewed = "abc"\n\n'
            '[[cards]]\nid = "007"\ntask = "t"\ntitle = "t"\ntree = ""\nspec = ""\n'
            'files = ["a.py"]\n\n'
            '[[cards]]\nid = "008"\ntask = "t2"\ntitle = "t2"\ntree = ".wt/x"\nspec = ""\n'
            'files = ["a.py"]\n')
    code = wb_plan.main(["check", "--backlog", str(_write(tmp_path, body))])
    assert code == 1
    assert "相交" in capsys.readouterr().err


def test_load_failure_exit_code(tmp_path: Path) -> None:
    assert wb_plan.main(["check", "--backlog", str(tmp_path / "nope.toml")]) == 2


def test_plan_command_prints_batches(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """`plan` 子命令在**四条种子夹具**上端到端印出 2 批（走 main → load → plan → 渲染）。"""
    code = wb_plan.main(
        ["plan", "--concurrency", "3", "--backlog", str(_seed_fixture(tmp_path))])
    out = capsys.readouterr().out
    assert code == 0
    assert "4 张卡 → 2 批" in out
    assert "第 1 批" in out and "卡 007" in out

# ================================================== T-G119：队列语义（done / depends / stats）


def test_done_cards_do_not_conflict_with_pending() -> None:
    """★ done 的卡占过的文件与树**已经释放** —— 它不该跟待派卡报冲突。"""
    backlog = _backlog(
        _card("001", files=("a.py",), tree="", status="done"),
        _card("002", files=("a.py",), tree="", status="pending"),
    )
    assert wb_plan.validate(backlog) == []


def test_done_card_fields_are_still_validated() -> None:
    """★ 「跳过冲突」不是「跳过校验」—— done 的卡字段非法照样要报。"""
    backlog = _backlog(_card("001", files=(), tree="", status="done"))
    problems = wb_plan.validate(backlog)
    assert any("files 为空" in item for item in problems), problems


def test_overlapping_cards_need_a_dependency_path() -> None:
    """同域两卡：**有依赖路径**才允许共存（会被分到不同层 → 不可能同批）。"""
    no_dep = _backlog(_card("001", files=("a.py",), tree=".wt/x"),
                      _card("002", files=("a.py",), tree=".wt/y"))
    assert any("files 相交" in item for item in wb_plan.validate(no_dep))
    with_dep = _backlog(_card("001", files=("a.py",), tree=".wt/x"),
                        _card("002", files=("a.py",), tree=".wt/y", depends=("001",)))
    assert wb_plan.validate(with_dep) == []


def test_dependent_overlapping_cards_land_in_different_batches() -> None:
    """依赖把同域两卡推到不同批，且**被依赖者在前**。"""
    backlog = _backlog(_card("001", files=("a.py",), tree=".wt/x"),
                       _card("002", files=("a.py",), tree=".wt/y", depends=("001",)))
    assert [[c.id for c in b] for b in wb_plan.plan_batches(backlog, 4)] == [["001"], ["002"]]


def test_transitive_dependency_also_allows_overlap() -> None:
    """传递依赖同样算路径：001 → 002 → 003，001 与 003 同域也允许。"""
    backlog = _backlog(_card("001", files=("a.py",), tree=".wt/x"),
                       _card("002", files=("b.py",), tree=".wt/y", depends=("001",)),
                       _card("003", files=("a.py",), tree=".wt/z", depends=("002",)))
    assert wb_plan.validate(backlog) == []


def test_plan_skips_done_cards() -> None:
    """★ backlog 是**队列**：done 的卡不进批次。"""
    backlog = _backlog(_card("001", files=("a.py",), tree=".wt/x", status="done"),
                       _card("002", files=("b.py",), tree=".wt/y"))
    assert [[c.id for c in b] for b in wb_plan.plan_batches(backlog, 4)] == [["002"]]


def test_worktree_commands_skip_done_cards() -> None:
    """建树只给待派的卡建。"""
    backlog = _backlog(_card("001", files=("a.py",), tree=".wt/x", status="done"),
                       _card("002", files=("b.py",), tree=".wt/y"))
    assert [card.id for card, _ in wb_plan.worktree_commands(backlog, "abc1234")] == ["002"]


def test_stats_reports_the_queue(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """`stats`：一条命令看队列全貌（待派 / 其它 / 批数 / 最大一批 / 占用的树）。"""
    body = """
[base]
reviewed = "abc1234"

[[cards]]
id = "001"
task = "T-G9x"
title = "已完成的样卡"
tree = ".wt/x"
spec = ""
files = ["a.py"]
depends = []
risk = "low"
status = "done"

[[cards]]
id = "002"
task = "T-G9x"
title = "待派样卡一"
tree = ".wt/y"
spec = ""
files = ["b.py"]
depends = []
risk = "low"
status = "pending"

[[cards]]
id = "003"
task = "T-G9x"
title = "待派样卡二"
tree = ".wt/z"
spec = ""
files = ["c.py"]
depends = []
risk = "low"
status = "pending"
"""
    backlog = wb_plan.load_backlog(_write(tmp_path, body))
    assert wb_plan.cmd_stats(backlog, 2) == 0
    out = capsys.readouterr().out
    assert "待派 2" in out, out
    assert "最大一批 2" in out, out


# ------------------------------------------------------------------ 卡 157（T-G257）
#   写卡必须同写预声明
#
# ★ 这一族判据治「写卡时声称了批次 B-XXX，但预声明 gates/diag/batch/B-XXX.toml 从没写」
#   ⇒ 工人干到最后一步交申请时才被栅栏咬（已咬 9 次：141/147/148/146/150…）。
#   五条钉子：① 缺 ⇒ 拒 ② 在 ⇒ 放 ③ 没声称 ⇒ 放 ④ 孤儿 ⇒ 报不算错 ⑤ spec 不存在 ⇒ 拒。


def _claim_spec(tmp_path: Path, batch: str = "B-X", member: str = "M-1") -> str:
    """写一份声称属于 `batch` 的 `member` 的卡规格到 tmp_path，返回相对 spec 路径。"""
    spec = tmp_path / "spec.md"
    spec.write_text(f"# 卡\n\n**成员号**：任务 `{batch}` 的 **{member}**\n",
                    encoding="utf-8")
    return "spec.md"


def test_batch_claim_missing_manifest_is_rejected(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """① pending 卡声称了 `B-X` 但预声明缺 ⇒ **拒**，且报里**点名**卡号与缺的文件路径。"""
    monkeypatch.setattr(pool_plan, "ROOT", tmp_path)
    monkeypatch.setattr(pool_plan, "DIAG", tmp_path / "gates" / "diag")
    spec = _claim_spec(tmp_path, "B-X")
    card = _card("007", files=("a.py",), spec=spec, status="pending")
    problems = wb_plan.validate(_backlog(card))
    hit = [p for p in problems if "B-X" in p and "007" in p and "gates/diag/batch/B-X.toml" in p]
    assert hit, f"应点名卡号与缺的预声明路径，拿到 {problems}"


def test_batch_claim_with_manifest_is_allowed(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """② 声称了 `B-X` 且预声明在 ⇒ **放行**（不因这条判据报 problem）。"""
    monkeypatch.setattr(pool_plan, "ROOT", tmp_path)
    monkeypatch.setattr(pool_plan, "DIAG", tmp_path / "gates" / "diag")
    spec = _claim_spec(tmp_path, "B-X")
    (tmp_path / "gates" / "diag" / "batch").mkdir(parents=True)
    (tmp_path / "gates" / "diag" / "batch" / "B-X.toml").write_text(
        'id = "B-X"\nwhy = "x"\non_complete = ["draft"]\n'
        '\n[[member]]\nid = "M-1"\nlayer = "后端"\nwhat = "x"\npaths = ["a.py"]\n',
        encoding="utf-8")
    card = _card("007", files=("a.py",), spec=spec, status="pending")
    problems = wb_plan.validate(_backlog(card))
    assert not any("B-X" in p and "预声明" in p for p in problems), problems


def test_no_batch_claim_is_allowed(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """③ 规格里没有「成员号」那行 ⇒ **放行**（只读审计型卡，如卡 153 —— 别误杀）。"""
    monkeypatch.setattr(pool_plan, "ROOT", tmp_path)
    monkeypatch.setattr(pool_plan, "DIAG", tmp_path / "gates" / "diag")
    (tmp_path / "spec.md").write_text("# 对抗审核卡\n\n没有成员号那行\n", encoding="utf-8")
    card = _card("007", files=("a.py",), spec="spec.md", status="pending")
    problems = wb_plan.validate(_backlog(card))
    assert not any("声称" in p or "预声明" in p for p in problems), problems


def test_orphan_manifest_is_reported_but_not_an_error(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """④ 反向：孤儿预声明（有 `B-*.toml`、没卡声称）⇒ `audit_batch_claims` **报一行**，但不算错。"""
    monkeypatch.setattr(pool_plan, "ROOT", tmp_path)
    monkeypatch.setattr(pool_plan, "DIAG", tmp_path / "gates" / "diag")
    batch_dir = tmp_path / "gates" / "diag" / "batch"
    batch_dir.mkdir(parents=True)
    (batch_dir / "B-ORPHAN.toml").write_text("x", encoding="utf-8")
    card = _card("007", files=("a.py",), spec="", status="pending")
    backlog = _backlog(card)
    assert wb_plan.validate(backlog) == []          # 不算错
    notes = wb_plan.audit_batch_claims(backlog)
    assert any("孤儿" in n and "B-ORPHAN" in n for n in notes), notes


def test_missing_spec_is_rejected_not_silently_passed(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⑤ spec 文件不存在（队列指向一个没有的规格）⇒ 如实报「读不到规格」，**不许静默放行**。"""
    monkeypatch.setattr(pool_plan, "ROOT", tmp_path)
    monkeypatch.setattr(pool_plan, "DIAG", tmp_path / "gates" / "diag")
    card = _card("007", files=("a.py",), spec="nope.md", status="pending")
    problems = wb_plan.validate(_backlog(card))
    assert any("读不到规格" in p and "007" in p and "nope.md" in p for p in problems), problems


def test_done_card_missing_manifest_is_reported_not_rejected(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """★ done 卡缺预声明 ⇒ **只报**（历史欠账，不追溯），不让 check 变红。

    这是 T-G257 的边界取舍：判据的目标语义是对 done 也拒（预声明是历史证据），但当前有
    大量历史欠账 ⇒ 本卡暂缓对 done 的拒，走 `audit_batch_claims` 的提醒通道。
    """
    monkeypatch.setattr(pool_plan, "ROOT", tmp_path)
    monkeypatch.setattr(pool_plan, "DIAG", tmp_path / "gates" / "diag")
    spec = _claim_spec(tmp_path, "B-DONE")
    card = _card("007", files=("a.py",), spec=spec, status="done")
    backlog = _backlog(card)
    assert wb_plan.validate(backlog) == []          # done 不拒
    notes = wb_plan.audit_batch_claims(backlog)
    assert any("B-DONE" in n and "历史欠账" in n for n in notes), notes


# ================================================ 卡 204（T-G311）：已落却仍 pending
#
# ★ 判据：队列里 status=pending 的卡，其 task 出现在 git log 的 Task: trailer 里 ⇒ 报红。
#   四条钉子：① 红并点名卡号+sha；② 翻成 done ⇒ 绿；③ 没有对应提交的 pending ⇒ 不报红；
#   ④ 没有 git 时优雅跳过。另加端到端 check 退 1。

def _git_init(tmp_path: Path) -> Path:
    """造一个空 git 仓用于测「已落却仍 pending」。"""
    repo = tmp_path / "gitrepo"
    repo.mkdir()
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    for cmd in (["git", "init", "-q"],
                ["git", "config", "user.email", "nail@example.invalid"],
                ["git", "config", "user.name", "nail"],
                ["git", "config", "commit.gpgsign", "false"]):
        subprocess.run(cmd, cwd=str(repo), env=env, capture_output=True, text=True)
    return repo


def _commit_with_task(repo: Path, task: str, msg: str = "test") -> str:
    """造一笔含 `Task:` trailer 的提交，返回短 sha。"""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    (repo / "f.txt").write_text(task, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(repo), env=env,
                   capture_output=True, text=True)
    subprocess.run(["git", "commit", "-q", "-m", f"{msg}\n\nTask: {task}"],
                   cwd=str(repo), env=env, capture_output=True, text=True)
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         cwd=str(repo), env=env, capture_output=True,
                         text=True).stdout.strip()
    return sha


def test_landed_but_pending_is_reported(tmp_path: Path) -> None:
    """① 判据红：pending 卡的 task 出现在 git log ⇒ 红并点名卡号 + sha。"""
    repo = _git_init(tmp_path)
    sha = _commit_with_task(repo, "T-G999")
    backlog = _backlog(_card("007", task="T-G999", status="pending"))
    reports = wb_plan.find_landed_but_pending(backlog, repo=repo)
    assert len(reports) == 1, reports
    assert "007" in reports[0] and "T-G999" in reports[0] and sha in reports[0], reports


def test_landed_but_pending_done_card_not_reported(tmp_path: Path) -> None:
    """② 翻成 done ⇒ 绿：done 的卡不报（反向保护①）。"""
    repo = _git_init(tmp_path)
    _commit_with_task(repo, "T-G999")
    backlog = _backlog(_card("007", task="T-G999", status="done"))
    assert wb_plan.find_landed_but_pending(backlog, repo=repo) == []


def test_pending_without_landed_commit_not_reported(tmp_path: Path) -> None:
    """③ 没有对应提交的 pending 卡 ⇒ 不许报红（这条错了会天天误伤）。"""
    repo = _git_init(tmp_path)
    _commit_with_task(repo, "T-G888")          # 不同 task
    backlog = _backlog(_card("007", task="T-G999", status="pending"))
    assert wb_plan.find_landed_but_pending(backlog, repo=repo) == []


def test_landed_but_pending_no_git_skips(tmp_path: Path) -> None:
    """④ 没有 git 时优雅跳过（不崩、不当通过）（反向保护③）。"""
    repo = tmp_path / "nogit"
    repo.mkdir()
    backlog = _backlog(_card("007", task="T-G999", status="pending"))
    assert wb_plan.find_landed_but_pending(backlog, repo=repo) == []


def test_landed_but_pending_does_not_pull_unlisted_cards(tmp_path: Path) -> None:
    """反向保护②：队列里没有条目的已落卡不许被牵进来（只看队列里的 pending 卡）。"""
    repo = _git_init(tmp_path)
    _commit_with_task(repo, "T-G999")
    # 队列里只有一张 task=T-G888 的卡；T-G999 虽已落但不在队列 ⇒ 不报
    backlog = _backlog(_card("007", task="T-G888", status="pending"))
    assert wb_plan.find_landed_but_pending(backlog, repo=repo) == []


def test_check_fails_on_landed_but_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """端到端：check 在「已落却仍 pending」时退 1 并点名。"""
    repo = _git_init(tmp_path)
    sha = _commit_with_task(repo, "T-G999")
    monkeypatch.setattr(wb_plan, "ROOT", repo)
    backlog = _backlog(_card("007", task="T-G999", status="pending", spec=""))
    code = wb_plan.cmd_check(backlog)
    err = capsys.readouterr().err
    assert code == 1, f"check 应当退 1：{err}"
    assert "已落却仍 pending" in err and "007" in err and sha in err, err


def test_check_passes_when_no_landed_but_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """端到端：没有「已落却仍 pending」时 check 退 0。"""
    repo = _git_init(tmp_path)
    monkeypatch.setattr(wb_plan, "ROOT", repo)
    backlog = _backlog(_card("007", task="T-G999", status="pending", spec=""))
    assert wb_plan.cmd_check(backlog) == 0


# ================================================================ 卡 212（T-G323）：栅栏漂移判据

import json as _json  # noqa: E402


def _make_gate(
    bd: Path, gate_id: str, state: str,
    members: list[dict[str, object]],
) -> None:
    """在 `bd` 下造一个栅栏（toml + json），供 `find_gate_drift` 测试。"""
    bd.mkdir(parents=True, exist_ok=True)
    member_text = "".join(
        f'\n[[member]]\nid = "{m["id"]}"\nlayer = "{m.get("layer", "test")}"\n'
        + (f'what = "{m.get("what", "")}"\n' if m.get("what") else "")
        + ('read_only = true\n' if m.get("read_only") else "")
        + f'paths = {_json.dumps(m.get("paths", []))}\n'
        for m in members)
    (bd / f"{gate_id}.toml").write_text(
        f'id = "{gate_id}"\nwhy = "test"\non_complete = ["draft"]\n{member_text}',
        encoding="utf-8")
    declared = [str(m["id"]) for m in members]
    read_only = [str(m["id"]) for m in members if m.get("read_only")]
    st = {
        "id": gate_id, "why": "test", "layers": ["test"], "declared": declared,
        "read_only": read_only, "need": len(declared) - len(read_only),
        "claims": {}, "waived": [], "state": state, "auto": ["draft"],
        "gate_cmd": None, "deadline": None, "gate": None, "draft": None,
        "landed": None, "history": [],
    }
    (bd / f"{gate_id}.json").write_text(
        _json.dumps(st, ensure_ascii=False) + "\n", encoding="utf-8")


def test_gate_drift_done_card_collecting_gate_is_red(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """① 判据红：卡 done 而栅栏 collecting ⇒ 红并点名（paths 匹配）。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path))
    _make_gate(tmp_path, "B-TEST", "collecting",
               [{"id": "M-1", "layer": "工具层", "paths": ["tools/x.py"]}])
    backlog = _backlog(_card("007", task="T-G999", status="done",
                             files=("tools/x.py",)))
    reports = wb_plan.find_gate_drift(backlog)
    assert len(reports) == 1, reports
    assert "B-TEST" in reports[0] and "007" in reports[0] and "done" in reports[0]


def test_gate_drift_member_id_equals_card_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """⑦ 成员号 == 卡 id 直接匹配（B-20261014 的 210/211/212 那种）。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path))
    _make_gate(tmp_path, "B-TEST", "collecting",
               [{"id": "007", "layer": "工具层", "paths": ["tools/x.py"]}])
    backlog = _backlog(_card("007", task="T-G999", status="done",
                             files=("tools/x.py",)))
    reports = wb_plan.find_gate_drift(backlog)
    assert len(reports) == 1, reports
    assert "007" in reports[0]


def test_gate_drift_landed_gate_not_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """② 栅栏已 landed ⇒ 不报（终态）。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path))
    _make_gate(tmp_path, "B-TEST", "landed",
               [{"id": "M-1", "layer": "工具层", "paths": ["tools/x.py"]}])
    backlog = _backlog(_card("007", task="T-G999", status="done",
                             files=("tools/x.py",)))
    assert wb_plan.find_gate_drift(backlog) == []


def test_gate_drift_pending_card_not_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """③ 反向保护①：卡 pending ⇒ 不报（没落地，栅栏等着是对的）。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path))
    _make_gate(tmp_path, "B-TEST", "collecting",
               [{"id": "M-1", "layer": "工具层", "paths": ["tools/x.py"]}])
    backlog = _backlog(_card("007", task="T-G999", status="pending",
                             files=("tools/x.py",)))
    assert wb_plan.find_gate_drift(backlog) == []


def test_gate_drift_member_no_card_not_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """④ 反向保护②：成员找不到对应卡 ⇒ 不报（可能还没派活）。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path))
    _make_gate(tmp_path, "B-TEST", "collecting",
               [{"id": "M-1", "layer": "工具层", "paths": ["tools/x.py"]}])
    backlog = _backlog(_card("007", task="T-G999", status="done",
                             files=("tools/z.py",)))  # 不相交
    assert wb_plan.find_gate_drift(backlog) == []


def test_gate_drift_read_only_member_not_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """⑤ 反向保护④：只读成员不参与放行 ⇒ 不报。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path))
    _make_gate(tmp_path, "B-TEST", "collecting",
               [{"id": "M-1", "layer": "审计层", "paths": [],
                 "read_only": True}])
    backlog = _backlog(_card("007", task="T-G999", status="done",
                             files=("tools/x.py",)))
    assert wb_plan.find_gate_drift(backlog) == []


def test_gate_drift_no_gate_dir_skips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """⑥ 反向保护⑤：没有栅栏目录 ⇒ 优雅跳过（不崩）。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path / "nonexistent"))
    backlog = _backlog(_card("007", task="T-G999", status="done"))
    assert wb_plan.find_gate_drift(backlog) == []


def test_gate_drift_awaiting_commit_not_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """③ 扩展：栅栏到 awaiting-commit（齐了等人提交）⇒ 不报。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path))
    _make_gate(tmp_path, "B-TEST", "awaiting-commit",
               [{"id": "M-1", "layer": "工具层", "paths": ["tools/x.py"]}])
    backlog = _backlog(_card("007", task="T-G999", status="done",
                             files=("tools/x.py",)))
    assert wb_plan.find_gate_drift(backlog) == []


def test_check_fails_on_gate_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """端到端：check 在「栅栏漂移」时退 1 并点名。"""
    repo = _git_init(tmp_path)
    monkeypatch.setattr(wb_plan, "ROOT", repo)
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path / "batch"))
    _make_gate(tmp_path / "batch", "B-TEST", "collecting",
               [{"id": "M-1", "layer": "工具层", "paths": ["tools/x.py"]}])
    backlog = _backlog(_card("007", task="T-G999", status="done",
                             files=("tools/x.py",), spec=""))
    code = wb_plan.cmd_check(backlog)
    err = capsys.readouterr().err
    assert code == 1, f"check 应当退 1：{err}"
    assert "B-TEST" in err and "007" in err, err


# ================================================================ 卡 234（T-G351）：假漂移挡住收口
#
# ★ 兜底不许乱兜：纯数字成员号（卡号形态）只认「号 == 卡 id」，不在队列里就是认不出；
#   别名成员（M-1）走 paths 兜底也必须「真有相交（全部兜住）且唯一最多」。
#   三条判据：① 真围栏的成员号不在合成队列 ⇒ 不许假漂移（231→164 的病）；
#   ② 真漂移照样能红（别名成员被唯一 done 卡全兜住 ⇒ 必须报）；③ 认不出必须有一行可见输出。


def test_gate_drift_missing_member_number_is_not_matched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    """① 先红后绿：真围栏成员号 `231` 不在合成队列 ⇒ **不许**兜到 done 的卡 164。

    复刻真读数：B-20261020 成员 231 的 paths 交到 done 卡 164 的 `src/timeflow/api/app.py`
    （只交 1/2 个）—— 旧兜底「paths ∩ files 取相交最多」照取 ⇒ 假漂移 ⇒ 收口被挡（实咬三趟）。
    """
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path))
    _make_gate(tmp_path, "B-20261020", "collecting",
               [{"id": "231", "layer": "面层",
                 "paths": ["src/timeflow/api/app.py", "tests/test_workbench_line.py"]}])
    backlog = _backlog(_card("164", task="T-G264", status="done",
                             files=("tools/wb_dispatch.py", "src/timeflow/api/app.py")))
    assert wb_plan.find_gate_drift(backlog) == []          # 不许假报
    err = capsys.readouterr().err
    assert "认不出" in err and "231" in err, err           # 但不许静默


def test_gate_drift_alias_partial_overlap_is_not_matched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    """① 续：别名成员的 paths **只被兜住一部分** ⇒ 也不算「真有相交」（不兜、不静默）。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path))
    _make_gate(tmp_path, "B-TEST", "collecting",
               [{"id": "M-1", "layer": "工具层",
                 "paths": ["tools/x.py", "tools/only_in_member.py"]}])
    backlog = _backlog(_card("007", task="T-G999", status="done",
                             files=("tools/x.py",)))
    assert wb_plan.find_gate_drift(backlog) == []
    err = capsys.readouterr().err
    assert "认不出" in err and "M-1" in err, err


def test_gate_drift_tied_best_is_not_matched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    """① 续：paths 被**两张并列**的卡全兜住 ⇒ 「唯一最多」不成立 ⇒ 认不出（不许按顺序挑）。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path))
    _make_gate(tmp_path, "B-TEST", "collecting",
               [{"id": "M-1", "layer": "工具层", "paths": ["tools/shared.py"]}])
    backlog = _backlog(_card("007", task="T-G999", status="done",
                             files=("tools/shared.py",)),
                       _card("008", task="T-G998", status="done",
                             files=("tools/shared.py",)))
    assert wb_plan.find_gate_drift(backlog) == []
    err = capsys.readouterr().err
    assert "认不出" in err and "M-1" in err, err


def test_gate_drift_alias_full_cover_still_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """② 反向：真漂移**照样能红** —— 别名成员的 paths 被唯一一张 done 卡**全部**兜住 ⇒ 必须报。

    （别把真漂移一起治没了：这条与卡 212 的 `test_gate_drift_done_card_collecting_gate_is_red`
    同型，钉的是新兜底语义下 paths 匹配的判据还咬人。）
    """
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path))
    _make_gate(tmp_path, "B-TEST", "collecting",
               [{"id": "M-1", "layer": "工具层",
                 "paths": ["tools/x.py", "tests/y.py"]}])
    backlog = _backlog(_card("007", task="T-G999", status="done",
                             files=("tools/x.py", "tests/y.py")))
    reports = wb_plan.find_gate_drift(backlog)
    assert len(reports) == 1, reports
    assert "B-TEST" in reports[0] and "007" in reports[0] and "done" in reports[0], reports


def test_match_member_number_missing_id_returns_none() -> None:
    """③ 单元钉子：纯数字成员号不在队列 ⇒ None（不许 paths 兜底）；别名成员才走兜底。"""
    by_id = {"164": _card("164", status="done", files=("a.py",))}
    assert wb_plan._match_member_to_card("231", ["a.py"], by_id) is None   # 数字号只认 ①
    assert wb_plan._match_member_to_card(
        "M-1", ["a.py", "c.py"], by_id) is None                            # 别名只兜住一半
    assert wb_plan._match_member_to_card(
        "M-1", ["a.py", "b.py"], by_id | {"X": _card("X", status="done",
                                                     files=("a.py", "b.py"))}) is not None
