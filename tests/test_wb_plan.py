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

import sys
from pathlib import Path

import pytest
import tomllib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_plan  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上

SEED = ROOT / "docs" / "workbacklog.toml"


def _card(cid: str, *, files: tuple[str, ...] = ("a.py",), tree: str = "",
          task: str = "T-G9x", title: str = "样卡", depends: tuple[str, ...] = (),
          risk: str = "low", status: str = "pending", spec: str = "s.md") -> wb_plan.Card:
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
spec = "gates/diag/卡007-看门狗护栏补强.md"
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
spec = "gates/diag/卡008-面板口径.md"
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
spec = "gates/diag/卡009-myday序号根因.md"
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
spec = "gates/diag/卡010-并发调度器.md"
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
    assert commands[0][1] == "git worktree add .wt/dash 1969b46"


def test_dispatch_argv_points_at_the_card() -> None:
    card = _card("008", spec="gates/diag/卡008-面板口径.md", tree=".wt/dash")
    argv = wb_plan.dispatch_argv(card)
    assert argv[:3] == ["python", "-X", "utf8"]
    assert "--card" in argv and "008" in argv
    assert "--spec" in argv and "gates/diag/卡008-面板口径.md" in argv
    assert argv[-2:] == ["--detach", "--execute"]


def test_render_dispatch_pushes_into_own_tree() -> None:
    main = _card("007", spec="s.md", tree="")
    tree = _card("008", spec="s.md", tree=".wt/dash")
    assert "pushd" not in wb_plan.render_dispatch(main)
    assert wb_plan.render_dispatch(tree).startswith("pushd .wt/dash; ")


# ------------------------------------------------------------------ 子命令（主线）


def test_check_command_passes_on_seed() -> None:
    assert wb_plan.main(["check", "--backlog", str(SEED)]) == 0


def test_check_command_fails_on_conflict(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    body = ('[base]\nreviewed = "abc"\n\n'
            '[[cards]]\nid = "007"\ntask = "t"\ntitle = "t"\ntree = ""\nspec = "s"\n'
            'files = ["a.py"]\n\n'
            '[[cards]]\nid = "008"\ntask = "t2"\ntitle = "t2"\ntree = ".wt/x"\nspec = "s2"\n'
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
spec = "s.md"
files = ["a.py"]
depends = []
risk = "low"
status = "done"

[[cards]]
id = "002"
task = "T-G9x"
title = "待派样卡一"
tree = ".wt/y"
spec = "s.md"
files = ["b.py"]
depends = []
risk = "low"
status = "pending"

[[cards]]
id = "003"
task = "T-G9x"
title = "待派样卡二"
tree = ".wt/z"
spec = "s.md"
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
