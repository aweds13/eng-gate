"""卡 A357 · T-AG570 —— 清空用量：只加一条标记，账一行不动。

本文件钉设计原件 §F44「测试钉子」那 18 条，名字逐字照抄。判据只有一条
（`cleared.go:76-102` 的 `hides`），其余全是它的配套：`Covers` / `usageCleared` /
`ClearUsage` 三处与账本侧那一个可选 kwarg。

★ **假牙夹具条件**（反向变异能不能咬住，全看这五处夹具；改夹具前先读这段）：

- 钉子 7 `test_all_clear_hides_the_row_at_exactly_its_time`：夹具里**必须**有一行的 `at`
  恰好等于 `clear.at`（变异「`<=` 改成 `<`」只在这一行上翻脸，晚一微秒就测不出来）。
- 钉子 13 `test_sums_without_clears_counts_every_row`：**必须同时**跑「有标记」与「无标记」
  两棵树（变异「默认值 `None` 改成 `read_clears()`」在无标记树上完全无害）。
- 钉子 11 `test_prune_drops_a_mark_an_all_clear_covers`：**必须**让全清那条标记**晚于**被它
  覆盖的按模型标记（反过来 `covers()` 为假，就不构成覆盖，变异白改）。
- 钉子 4 `test_read_clears_broken_file_hides_nothing`：坏文件**不只**断言「不抛」，还要断言
  `hides(...) is False`（变异把坏文件当成全清时，只断言不抛照样绿）。
- 钉子 14 `test_sums_with_clears_hides_exactly_the_marked_rows`：夹具里的行**必须**真的带
  非空 `model`（否则 `_entry` 丢掉 `model=` 也照样过滤得对，咬不住那处变异）。

★ 导入口径照 `tests/test_pool_account_scope.py`：`tools/` 不在 `sys.path` 上、本仓禁
  `# noqa`，所以模块级只做 `sys.path.insert` 加 `importlib.import_module`，不写 import 语句
  （否则踩 E402）。

★ 零接线：本文件不 import `tools/wb_dispatch.py`，不碰任何真实账本 —— 全部落在 `tmp_path`。
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

cleared = importlib.import_module("pool.cleared")
ledger_spend = importlib.import_module("pool.ledger_spend")
pool_accounts = importlib.import_module("pool_accounts")

Clear = cleared.Clear
ClearError = cleared.ClearError

#: 钉死的「现在」—— 与 `tests/test_pool_limits.py` 同一个时刻，方便对着读。
NOW = datetime(2026, 10, 12, 23, 28, tzinfo=pool_accounts.TZ)


def _row(
    root: Path,
    account: str,
    model: str,
    at: datetime,
    *,
    tokens: int = 1,
    cost: float = 0.0,
) -> Path:
    """往 `root` 的账里追加一行；`model` **真的**写进行里（钉子 14 的假牙条件）。"""
    return ledger_spend.append(
        account,
        "A357",
        model,
        input_tokens=tokens,
        output_tokens=0,
        cache_read=0,
        cost=cost,
        at=at,
        root=root,
    )


def _sums_calls() -> list[tuple[str, int, list[str | None]]]:
    """扫 `tools/**/*.py` 里所有 `sums(...)` 调用点：`(相对路径, 行号, 关键字名)`。

    ★ 只认**调用**（`ast.Call`），不认 `def sums(` 那个定义；扫不到任何调用点时本函数
      回空表，调用方那条 `assert sites` 会红 —— 免得「扫描器坏了」被读成「判据成立」。
    """
    sites: list[tuple[str, int, list[str | None]]] = []
    for path in sorted((ROOT / "tools").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name != "sums":
                continue
            sites.append(
                (
                    path.relative_to(ROOT).as_posix(),
                    node.lineno,
                    [kw.arg for kw in node.keywords],
                )
            )
    return sites


# ============================================================ 判据 1：点名才清得动


def test_add_clear_rejects_account_without_a_model(tmp_path: Path) -> None:
    """点了号却没点模型 ⇒ `ClearError`，文案逐字，**且文件不得被创建**。

    模型缺席时「清谁的用量」读不出来：宽松放行等于按号清全部模型 —— 那是一句
    收了一个参数却做了另一件事的命令。先判后写，半条标记比没有更坏。
    """
    assert issubclass(ClearError, ValueError)
    with pytest.raises(ClearError) as caught:
        cleared.add_clear("acc1", cleared.ALL_MODEL, NOW, root=tmp_path)
    assert str(caught.value) == "清空 'acc1' 的用量要点名模型"
    assert not cleared.clears_path(tmp_path).exists()


# ============================================================ 判据 2：要一个时间


def test_add_clear_rejects_a_missing_time(tmp_path: Path) -> None:
    """naive 时间与早于纪元的时间都拒，文案逐字，**且文件不得被创建**。

    naive 时间在两种时区下会指到两个不同的瞬间（这一天里 8 小时之差就是一次
    「清没清掉」的判决），所以宁可不收。
    """
    with pytest.raises(ClearError) as naive:
        cleared.add_clear("acc1", "m1", datetime(2026, 10, 12, 8, 0), root=tmp_path)
    assert str(naive.value) == "清空用量要一个时间"
    epoch = datetime(1969, 12, 31, 23, 0, tzinfo=pool_accounts.TZ)
    with pytest.raises(ClearError) as early:
        cleared.add_clear(cleared.ALL_ACCOUNT, cleared.ALL_MODEL, epoch, root=tmp_path)
    assert str(early.value) == "清空用量要一个时间"
    assert not cleared.clears_path(tmp_path).exists()


# ============================================================ 判据 3/4：读不出来就全显


def test_read_clears_missing_file_is_an_empty_list(tmp_path: Path) -> None:
    """没有标记文件 ⇒ `[]`（一条都不隐藏 = 与这个功能不存在时逐字相同）。"""
    assert cleared.read_clears(root=tmp_path) == []
    assert not cleared.clears_path(tmp_path).exists()


def test_read_clears_broken_file_hides_nothing(tmp_path: Path) -> None:
    """坏文件 ⇒ `[]`：**不抛**，也**不当全清**（假牙条件：两件事都要断言）。

    隐藏是危险方向：判不出来时若当成全清，一次手滑的编辑就会把整本账从限额里抹掉。
    只断言「不抛」是不够的 —— 变异把坏文件当成全清时，那种断言照样绿。
    """
    path = cleared.clears_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    bodies = [
        "{这不是 JSON",
        "[]",
        '{"clears": "不是表"}',
        '{"clears": [{"account": 1, "model": "m1", "at": "2026-10-12T00:00:00+08:00"}]}',
        '{"clears": [{"account": "acc1", "model": "m1", "at": "不是时间"}]}',
        '{"clears": [{"account": "acc1", "model": "m1"}]}',
    ]
    for body in bodies:
        path.write_text(body, encoding="utf-8", newline="\n")
        marks = cleared.read_clears(root=tmp_path)
        assert marks == [], f"这份内容不许读出任何标记：{body!r}"
        assert cleared.hides(marks, "acc1", "m1", NOW) is False
        assert cleared.hides(marks, cleared.ALL_ACCOUNT, cleared.ALL_MODEL, NOW) is False


# ============================================================ 判据 5：读回来的时间带时区


def test_read_clears_returns_aware_times(tmp_path: Path) -> None:
    """`at` 一律是 aware、且落在本仓时区（手写进去的 naive 时间也读成 aware）。

    `add_clear()` 本身拒收 naive（判据 2），所以「读法」这一半只能手工落一份 naive 的
    文件来验 —— 那份文件是别的工具 / 手改出来的形状，读的人不能因此崩，也不能读成 UTC。
    """
    cleared.add_clear("acc1", "m1", NOW, root=tmp_path)
    path = cleared.clears_path(tmp_path)
    body = json.loads(path.read_text(encoding="utf-8"))
    body["clears"].append({"account": "acc2", "model": "m1", "at": "2026-10-12T08:00:00"})
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    marks = cleared.read_clears(root=tmp_path)
    assert [mark.account for mark in marks] == ["acc1", "acc2"]
    for mark in marks:
        assert mark.at.tzinfo is not None
        assert mark.at.tzinfo == pool_accounts.TZ
    assert marks[0].at == NOW
    assert marks[1].at == datetime(2026, 10, 12, 8, 0, tzinfo=pool_accounts.TZ)


# ============================================================ 判据 6/7：hides 的两个上界


def test_hides_with_no_marks_is_false(tmp_path: Path) -> None:
    """一条标记都没有 ⇒ 什么都不隐藏（Go `:77` 的 `len(c.marks) == 0`）。"""
    assert cleared.hides([], "acc1", "m1", NOW) is False
    assert cleared.hides([], cleared.ALL_ACCOUNT, cleared.ALL_MODEL, NOW) is False
    assert cleared.read_clears(root=tmp_path) == []


def test_all_clear_hides_the_row_at_exactly_its_time(tmp_path: Path) -> None:
    """全清是**闭区间**：`at == clear.at` 那行也算被清（Go `:80` 的 `!After(c.all)`）。

    ★ 假牙条件：夹具里必须有一行的 `at` **恰好等于** `clear.at`。变异把 `<=` 改成 `<`
    时，只有这一行会翻脸；任何晚一微秒的行都测不出来。
    """
    mark = cleared.Clear(account=cleared.ALL_ACCOUNT, model=cleared.ALL_MODEL, at=NOW)
    assert cleared.hides([mark], "acc1", "m1", NOW) is True
    assert cleared.hides([mark], "acc1", "m1", NOW + timedelta(seconds=1)) is False
    assert cleared.hides([mark], "acc1", "m1", NOW - timedelta(seconds=1)) is True
    # 真账：一行 at 恰好 == clear.at，一行在它之后
    _row(tmp_path, "acc1", "m1", NOW, tokens=4)
    _row(tmp_path, "acc1", "m1", NOW + timedelta(hours=1), tokens=8)
    start, end = NOW - timedelta(days=1), NOW + timedelta(days=1)
    assert ledger_spend.sums("acc1", start, end, root=tmp_path) == (12, 0.0, 2)
    assert ledger_spend.sums("acc1", start, end, root=tmp_path, clears=[mark]) == (8, 0.0, 1)


# ============================================================ 判据 7：按模型清只清一条轴


def test_model_clear_hides_only_its_own_account_and_model(tmp_path: Path) -> None:
    """按模型清：四个方向逐个断言（号 / 模型 / 时间，任一不同都不隐藏）。

    只钉住「同号同模型被隐藏」是不够的 —— 那对「把整本账都隐藏」也成立。四个方向一起
    钉，才排除「清一个模型顺手清了全仓」这种最贵的错法。
    """
    mark = cleared.Clear(account="acc1", model="m1", at=NOW)
    assert cleared.hides([mark], "acc1", "m1", NOW) is True
    assert cleared.hides([mark], "acc1", "m2", NOW) is False
    assert cleared.hides([mark], "acc2", "m1", NOW) is False
    assert cleared.hides([mark], "acc1", "m1", NOW + timedelta(seconds=1)) is False


# ============================================================ 判据 8：covers 逐字照 Go


def test_covers_matches_the_go_expression(tmp_path: Path) -> None:
    """`Covers` 逐字照 `settings.go:2043-2046`：

    `c.At >= o.At && (c.Provider == "" && c.Model == "" || c.Provider == o.Provider &&
    c.Model == o.Model)` —— 表驱动，一行一个分支。
    """
    earlier = NOW - timedelta(hours=2)
    later = NOW + timedelta(hours=2)
    table = [
        # (c 的 account, c 的 model, c 的 at, o 的 account, o 的 model, o 的 at, 期望)
        ("acc1", "m1", NOW, "acc1", "m1", earlier, True),  # 同键、更晚 ⇒ 覆盖
        ("acc1", "m1", earlier, "acc1", "m1", NOW, False),  # 同键、更早 ⇒ 不覆盖
        ("acc1", "m1", NOW, "acc1", "m1", NOW, True),  # 同键、同一刻 ⇒ 互相覆盖
        ("", "", NOW, "acc1", "m1", earlier, True),  # 全清覆盖任何更早的标记
        ("", "", earlier, "acc1", "m1", NOW, False),  # 全清在它之前 ⇒ 不覆盖
        ("acc2", "m1", later, "acc1", "m1", earlier, False),  # 号不同
        ("acc1", "m2", later, "acc1", "m1", earlier, False),  # 模型不同
        ("acc1", "", later, "acc1", "m1", earlier, False),  # 只点号不点模型 ≠ 同键
        ("", "", later, "", "", earlier, True),  # 两条全清：晚的覆盖早的
    ]
    for c_account, c_model, c_at, o_account, o_model, o_at, expected in table:
        c = Clear(account=c_account, model=c_model, at=c_at)
        o = Clear(account=o_account, model=o_model, at=o_at)
        got = cleared.covers(c, o)
        assert got is expected, f"covers({c}, {o}) 期望 {expected} 实得 {got}"


# ============================================================ 判据 9：prune 去重与吃覆盖


def test_prune_keeps_the_first_of_two_same_marks(tmp_path: Path) -> None:
    """两条**互相**覆盖（= 同一个标记）时只留第一条（Go 注释 `the first is kept`）。

    用 `is` 判是**第一条**：两条的字段完全相同，只比值分不出先后。
    """
    first = Clear(account="acc1", model="m1", at=NOW)
    second = Clear(account="acc1", model="m1", at=NOW)
    third = Clear(account="acc2", model="m1", at=NOW)
    pruned = cleared.prune([first, second, third])
    assert len(pruned) == 2
    assert pruned[0] is first
    assert pruned[1] is third


def test_prune_drops_a_mark_an_all_clear_covers(tmp_path: Path) -> None:
    """全清**晚于**一条按模型标记 ⇒ 那条标记被吃掉（Go `:2050-2074`）。

    ★ 假牙条件：全清必须**晚于**被覆盖的那条。反过来（全清更早）`covers()` 为假，
    两条都该留下 —— 变异「prune 什么都不做」在那份夹具上也是绿的，咬不住。
    """
    model_mark = Clear(account="acc1", model="m1", at=NOW)
    all_mark = Clear(account=cleared.ALL_ACCOUNT, model=cleared.ALL_MODEL, at=NOW + timedelta(1))
    assert cleared.prune([model_mark, all_mark]) == [all_mark]
    assert cleared.prune([all_mark, model_mark]) == [all_mark]
    # 反向：全清更早 ⇒ 两条都留（证明上一条不是「看到全清就全丢」的假绿）
    early_all = Clear(account=cleared.ALL_ACCOUNT, model=cleared.ALL_MODEL, at=NOW - timedelta(1))
    assert cleared.prune([model_mark, early_all]) == [model_mark, early_all]


# ============================================================ 判据 10：账一个字节不动


def test_add_clear_leaves_the_spend_log_byte_identical(tmp_path: Path) -> None:
    """`add_clear` **永不重写** `pool-spend.jsonl`：加标记前后 sha256 相等。

    这是整张卡的全部重量：magpie 的页面数 3 / `Visit` 数 5 靠的就是「同一份日志、
    两种读法」。任何「顺手把行删掉」的实现都会让这条红。
    """
    path = _row(tmp_path, "acc1", "m1", NOW, tokens=2, cost=0.25)
    _row(tmp_path, "acc2", "m1", NOW, tokens=3, cost=0.5)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    cleared.add_clear("acc1", "m1", NOW + timedelta(minutes=1), root=tmp_path)
    cleared.add_clear(cleared.ALL_ACCOUNT, cleared.ALL_MODEL, NOW, root=tmp_path)
    after = hashlib.sha256(path.read_bytes()).hexdigest()
    assert before == after
    assert ledger_spend.audit(root=tmp_path) == {"lines": 2, "usable": 2, "damaged": 0}
    assert cleared.clears_path(tmp_path).exists()


# ============================================================ 判据 11：两个面各数各的


def test_sums_without_clears_counts_every_row(tmp_path: Path) -> None:
    """`sums(..., clears=None)` 数**全部**行 = magpie 的 `Visit` 面（5 条那边）。

    ★ 假牙条件：**必须同时**跑「无标记」与「有标记」两棵树。变异把默认值改成
    `read_clears()` 时，无标记那棵树完全无害 —— 只有在有标记的树上才看得见差异。
    另外必须在有标记的树上**显式**给 `clears=` 数出更少的行，证明这棵树的标记是活的
    （否则「标记根本没被写进去」也能让本条假绿）。
    """
    start, end = NOW - timedelta(days=2), NOW + timedelta(days=2)
    bare = tmp_path / "bare"
    _row(bare, "acc1", "m1", NOW, tokens=3)
    _row(bare, "acc1", "m1", NOW + timedelta(hours=1), tokens=5)
    assert ledger_spend.sums("acc1", start, end, root=bare) == (8, 0.0, 2)

    marked = tmp_path / "marked"
    _row(marked, "acc1", "m1", NOW, tokens=3)
    _row(marked, "acc1", "m1", NOW + timedelta(hours=1), tokens=5)
    marks = cleared.add_clear("acc1", "m1", NOW + timedelta(hours=2), root=marked)
    assert len(marks) == 1
    assert ledger_spend.sums("acc1", start, end, root=marked) == (8, 0.0, 2)
    assert ledger_spend.sums("acc1", start, end, root=marked, clears=marks) == (0, 0.0, 0)


# ============================================================ 判据 11 的另一半


def test_sums_with_clears_hides_exactly_the_marked_rows(tmp_path: Path) -> None:
    """显式给 `clears` ⇒ 只少数出来的行（= magpie 的页面面，3 条那边）。

    ★ 假牙条件：夹具里每一行**必须**真的带非空 `model`。把 `_entry` 的 `model=` 删掉
    后 `Entry.model` 恒为 `""`，若夹具的行也都没有模型，这条照样绿 —— 咬不住。
    """
    early = NOW - timedelta(hours=2)
    mark_at = NOW - timedelta(hours=1)
    _row(tmp_path, "acc1", "m1", early, tokens=1)
    _row(tmp_path, "acc1", "m1", mark_at, tokens=2)  # at == 标记时刻 ⇒ 也算被清
    _row(tmp_path, "acc1", "m2", NOW, tokens=4)  # 别的模型 ⇒ 照数
    _row(tmp_path, "acc1", "m1", NOW, tokens=8)  # 标记之后 ⇒ 照数
    marks = [Clear(account="acc1", model="m1", at=mark_at)]
    start, end = NOW - timedelta(days=1), NOW + timedelta(days=1)
    assert ledger_spend.sums("acc1", start, end, root=tmp_path) == (15, 0.0, 4)
    assert ledger_spend.sums("acc1", start, end, root=tmp_path, clears=marks) == (12, 0.0, 2)


# ============================================================ 判据 12：model 的缺席不算坏行


def test_entry_keeps_the_model_and_tolerates_a_missing_one(tmp_path: Path) -> None:
    """`_entry()` 保留 `model`；缺席或不是字符串 ⇒ `""` 且**该行仍可用**。

    老账里的行没有 `model` 这个键（它是这张卡才加上的），把它们判成坏行就是把过去的
    花费一笔抹掉 —— 与本卡「账一行不动」的整个前提相反。
    """
    path = ledger_spend.spend_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    base = {
        "at": "2026-10-12T10:00:00+08:00",
        "account": "acc1",
        "input_tokens": 7,
        "output_tokens": 0,
        "cache_write": 0,
        "cache_read": 0,
        "cost": 0.5,
    }
    lines = [
        json.dumps({**base, "model": "m1"}),
        json.dumps(base),
        json.dumps({**base, "model": 123}),
        json.dumps({**base, "model": None}),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    entries = [ledger_spend._entry(line) for line in lines]
    assert [entry is not None for entry in entries] == [True] * 4
    assert [entry.model for entry in entries if entry is not None] == ["m1", "", "", ""]
    start, end = NOW - timedelta(days=1), NOW + timedelta(days=1)
    assert ledger_spend.sums("acc1", start, end, root=tmp_path) == (28, 2.0, 4)


# ============================================================ 判据 13：限额面不许过滤


def test_no_call_site_passes_clears_to_sums(tmp_path: Path) -> None:
    """`tools/` 里**没有任何一处**给 `sums(` 传 `clears=` —— 限额面永远读全量。

    `clears` 是个能力，不是个默认。今天唯一的生产调用点（`tools/wb_dispatch.py` 的
    派活前限额检查）刻意不传：让「只是不想看见」悄悄松开限额，正是这张卡要防的事。

    ★ 假牙如实申报：本条今天是**因「没人传」而绿**（不是因某处被判红）。所以先断言
    扫描器至少看得见一个调用点 —— 否则扫描器写坏了也会绿。
    """
    sites = _sums_calls()
    assert sites, "扫不到任何 sums( 调用点：扫描器坏了，不是判据成立"
    offenders = [(path, line, keys) for path, line, keys in sites if "clears" in keys]
    assert not offenders, f"限额面不许过滤，这些调用点传了 clears=：{offenders}"
    assert all(isinstance(keys, list) for _, _, keys in sites)


# ============================================================ 判据 14：两个面不许合并


def test_cleared_never_touches_forget(tmp_path: Path) -> None:
    """`cleared.py` 不 import、不调用账本那个「人显式 reset」的动作（只扫 **ast**）。

    语义相反：那个动作把旧账**搬走**（被清的调用不再计入限额），本模块只改**读法**。
    合并两者 = 让「不想看见」悄悄松开限额。

    ★ 只扫 ast 里的 `Name`/`Attribute`，**不扫注释与 docstring** —— 否则在文档里写一句
    「本模块不改那个动作」也会误红。扫描器自检放在末尾：同一次遍历必须看得见本模块
    自己的名字，否则「扫了个空文件」也能绿。
    """
    source = (ROOT / "tools" / "pool" / "cleared.py").read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(source)
    hits: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "forget":
            hits.append(("Name", node.lineno))
        elif isinstance(node, ast.Attribute) and node.attr == "forget":
            hits.append(("Attribute", node.lineno))
    assert not hits, f"cleared.py 碰了那个相反的动作：{hits}"
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert {"hides", "read_clears", "add_clear"} <= functions
    assert {"Clear", "ClearError"} <= names


# ============================================================ 判据 14 的 CLI


def test_cli_add_then_list_round_trips(tmp_path: Path, capsys) -> None:
    """`add` 写进 `tmp_path`、`list` 读得回来；缺模型那条走 `EXIT_USAGE` 且落 stderr。"""
    added = cleared.main(
        [
            "add",
            "--root",
            str(tmp_path),
            "--account",
            "acc1",
            "--model",
            "m1",
            "--now",
            "2026-10-12T23:28:00+08:00",
        ]
    )
    assert added == cleared.EXIT_OK
    assert "[OK" in capsys.readouterr().out
    listed = cleared.main(["list", "--root", str(tmp_path)])
    assert listed == cleared.EXIT_OK
    out = capsys.readouterr().out
    assert "account='acc1'" in out
    assert "model='m1'" in out
    assert "2026-10-12T23:28:00+08:00" in out
    # 缺模型 ⇒ 用法错（2），文案落 stderr，文件不被改动
    before = cleared.clears_path(tmp_path).read_bytes()
    bad = cleared.main(["add", "--root", str(tmp_path), "--account", "acc2"])
    assert bad == cleared.EXIT_USAGE
    captured = capsys.readouterr()
    assert "要点名模型" in captured.err
    assert cleared.clears_path(tmp_path).read_bytes() == before

