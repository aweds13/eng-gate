r"""钉子：`wb-*.jsonl` 里「哪几个不是卡」只许有一份定义（卡 E74 · 台账号 `T-AG576`）。

## 为什么有这个文件

pool 的「工人日志」口径是文件名 `gates/diag/wb-<卡>.jsonl`。按这个通配扫的读者有**四个**：
`tools/pool/jobs.py`（`scan_jobs`）、`tools/wb_dash.py`（面板）、`tools/wb_retention.py`
（留痕巡检）、`scripts/gen_pool_readme.py`（项目书的「派活日志 N 份」）。今天多了一本旁账
`gates/diag/wb-route.jsonl`（F39 路由回放，卡 A363 落）—— 它落进四个读者的眼里，每个都得
再答一次「这份算不算卡」。T-G137 的先例是 `wb-usage.jsonl`（9 棵树 9 行 `usage` 幻影）。

所以本卡的判据只有一句：**「哪几个 `wb-*.jsonl` 不是卡」这件事只在
`tools/pool/jobs.py` 定义一次**（`NON_CARD_LOG_RE` + `is_card_log()` + `non_card_reason()`），
四个读者全部引用它。本文件的八条钉子逐条钉住这句话的每个后果：

| 钉子 | 判据 | 钉什么 |
|---|---|---|
| ① `test_single_definition_no_second_literal_set` | 判据 1 | 另外三个读者里没有第二份名单 |
| ② `test_predicate_is_regex_not_enumeration` | 判据 2 | 轮次变体与 `B1` / `B-20261052` 都判对 |
| ③ `test_wb_dash_card_list_has_no_route` | 判据 3 | 面板卡片列表里**没有** `route` |
| ④ `test_wb_retention_excludes_non_card_but_keeps_real_card` | 判据 4 | 假欠账不出现，真欠账仍在 |
| ⑤ `test_scan_jobs_marks_non_card_logs_apart` | 判据 5 | 旁账都标「非派活」，只有 `001` 是卡 |
| ⑥ `test_adding_a_name_in_one_place_takes_effect_everywhere` | 判据 6 | 改一处，四个读者都生效 |
| ⑦ `test_gen_pool_readme_counts_only_card_logs` | 判据 1 扩域 | 项目书的「派活日志 N 份」也过谓词 |
| ⑧ `test_gen_pool_readme_check_is_green` | 主控硬要求 | `--check` 仍退 0（数字今天不变） |

★ 判据 5 的读法（主控 2026-10-31 裁定）：`scan_jobs` 对非卡日志**保留** `state="非派活"` 那一行
（`job_list` 的「共 N 个日志」依赖它）—— 本卡治的是「别把非卡当卡」，不是「别看见非卡」。
所以断言写成「状态不是 `非派活` 的行里只有 `001`」，**不是** `{r["card"]} == {"001"}`。

★ `wb-route.jsonl` 在 um 这棵树里**不存在**（它在卡 A363 的树里）—— 所以每条用例都自己把
这个文件名造出来。判据不该依赖某张在飞的卡是否落地。
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for _rel in ("tools", "scripts"):
    if str(REPO / _rel) not in sys.path:
        sys.path.insert(0, str(REPO / _rel))

import gen_pool_readme as gpr  # noqa: E402 —— scripts/ 已在 sys.path 上
import wb_dash  # noqa: E402 —— tools/ 已在 sys.path 上
import wb_retention as rt  # noqa: E402
from pool import jobs  # noqa: E402

#: 这四份文件里，除了 `tools/pool/jobs.py`，谁也不许自己抄一份名单。
READERS = (
    REPO / "tools" / "pool" / "jobs.py",
    REPO / "tools" / "wb_dash.py",
    REPO / "tools" / "wb_retention.py",
    REPO / "scripts" / "gen_pool_readme.py",
)
OTHER_READERS = READERS[1:]

#: 非卡（旁账）与是卡（派活日志）的两组真值 —— 判据 2 的靶子。
NON_CARDS = (
    "wb-usage.jsonl",
    "wb-usage.r2.jsonl",
    "wb-usage.r13.jsonl",
    "wb-route.jsonl",
    "wb-route.r2.jsonl",
)
CARDS = (
    "wb-001.jsonl",
    "wb-B1.jsonl",
    "wb-B-20261052.jsonl",
    "wb-105.r2.jsonl",
    "wb-E14.trae.jsonl",
)


_WB_NAME_RE = re.compile(r"wb-[^ \t\"'`]*?(usage|route)")


def _names_wb_logs(value: str) -> bool:
    """这个字符串是不是在点某本旁账的名 —— 直写与正则写法（`wb-(usage|route)`）都算。"""
    return _WB_NAME_RE.search(value) is not None


def _is_filename(value: str) -> bool:
    """这个字符串长得像**一个文件名**（不是一句人话）—— 用来把「名单」与「印给人看的句子」分开。"""
    return "/" not in value and "`" not in value and "|" not in value and value.endswith(".jsonl")


def _judgement_literals(path: Path) -> list[str]:
    """这份源码里**拿文件名当判据**的地方（`路径:行号 形状 名字`）—— 人话与注释都不算。

    只认三种形状（都是「代码在判这件事」，不是「文字在提这件事」）：

      · 比较运算：`path.name != "wb-usage.jsonl"`、`name in ("wb-usage.jsonl",)`
      · 集合 / 元组 / 列表字面量：`frozenset({"wb-usage.jsonl"})`、`NON_CARD_LOGS = (...)`
      · 正则字面量：`re.compile(r"^wb-usage$")`

    ★ 为什么不是「所有字符串常量」：`scripts/gen_pool_readme.py` 的 `LEDGERS` 里有
    `"| 派活日志 | {logs} 份（不含 `wb-usage.jsonl`） |"` —— 那是**印给人看的一句话**，
    本卡明令「不许改输出格式与人话」，它必须留。判据要的是第二份**判据**，不是第二个提法。
    """
    tree = ast.parse(path.read_bytes().decode("utf-8"))
    hits: list[str] = []

    def note(node: ast.AST, kind: str, value: str) -> None:
        where = f"{path.relative_to(REPO).as_posix()}:{getattr(node, 'lineno', '?')}"
        hits.append(f"{where} {kind} {value!r}")

    def scan_value(node: ast.AST, kind: str) -> None:
        """`node` 是不是一份**名单**。

        ★ 只有「整块都是文件名」的集合/元组/列表才算名单：`gen_pool_readme.py` 的
        `LEDGERS` 那种「一句句人话」的元组里也提到 `wb-usage.jsonl`，但那是输出文字，
        本卡明令不许改 —— 它不是判据。`frozenset({...})` / `{...}` 一律算（集合就是判据形状）。
        """
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if kind in ("比较", "正则") and _names_wb_logs(node.value):
                note(node, kind, node.value)
        elif isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            members = [
                elt.value for elt in node.elts if isinstance(elt, ast.Constant)
            ]
            pure_names = (
                members
                and len(members) == len(node.elts)
                and all(isinstance(m, str) and _is_filename(m) for m in members)
            )
            named = [m for m in members if isinstance(m, str) and _names_wb_logs(m)]
            if named and (pure_names or isinstance(node, ast.Set)):
                note(node, f"{kind}（{len(named)} 个名字）", ", ".join(named))

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for operand in [node.left, *node.comparators]:
                scan_value(operand, "比较")
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            if node.value is not None:
                scan_value(node.value, "赋值")
        elif isinstance(node, ast.Set):
            scan_value(node, "集合")
        elif isinstance(node, ast.Call):
            func = node.func
            fname = getattr(func, "attr", getattr(func, "id", ""))
            if fname == "compile":
                for arg in node.args:
                    scan_value(arg, "正则")
    return hits


def _diag(root: Path) -> Path:
    d = root / "gates" / "diag"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _touch(p: Path, text: str = "x\n") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------- ① 一份名单（判据 1）


def test_single_definition_no_second_literal_set() -> None:
    """★ 判据 1：名单只准在 `tools/pool/jobs.py` 有一份 —— 另外三份源码里不许有文件名字面量。

    只认**拿文件名当判据**的三种形状（比较 / 集合字面量 / 正则），不认注释、docstring 与
    印给人看的那句话：`gen_pool_readme.py` 的「派活日志 N 份（不含 …）」是输出人话，
    本卡明令不许改 —— 它必须留。判据要的是第二份**判据**，不是第二个提法。
    """
    offenders: list[str] = []
    for path in OTHER_READERS:
        offenders.extend(_judgement_literals(path))
    assert offenders == [], (
        "这些地方又拿文件名当判据了（判据 1：只准 `tools/pool/jobs.py` 一处）：\n"
        + "\n".join(offenders)
    )

    # ★ 防这条钉子自己空转：真源里**必须**被扫出来（不然就是扫描器退化成恒真）。
    assert _judgement_literals(READERS[0]) != [], "扫描器没认出真源里的名单 —— 它在空转"

    # 真源本身在，且它才是唯一能回答这件事的地方。
    assert jobs.NON_CARD_LOG_RE.pattern.startswith("^wb-"), jobs.NON_CARD_LOG_RE.pattern
    assert "usage" in jobs.NON_CARD_LOG_RE.pattern
    assert "route" in jobs.NON_CARD_LOG_RE.pattern

    # 另外三个读者都**引用**它（不是各写一份）：源码里出现 `pool.jobs` 的 `is_card_log`。
    for path in OTHER_READERS:
        text = path.read_bytes().decode("utf-8")
        assert "is_card_log" in text, f"{path.name} 没有引用 `is_card_log` —— 它又自己判了一遍"


# ---------------------------------------------------------------- ② 正则不是枚举（判据 2）


@pytest.mark.parametrize("name", NON_CARDS)
def test_predicate_is_regex_not_enumeration(name: str) -> None:
    """★ 判据 2：带轮次的变体（`.r<N>`）与今天的两个真值一样判非卡 —— 不许退化成枚举。"""
    assert jobs.is_card_log(name) is False, f"{name} 被判成卡了"
    assert jobs.non_card_reason(name), f"{name} 判了非卡却说不出理由"


@pytest.mark.parametrize("name", CARDS)
def test_predicate_keeps_non_numeric_card_names(name: str) -> None:
    """★ 反例（卡 §不许做）：不许收紧成「只认数字卡号」—— `B1` / `B-20261052` 今天都在用。"""
    assert jobs.is_card_log(name) is True, f"{name} 是真卡，被判掉了"
    assert jobs.non_card_reason(name) == ""


# ---------------------------------------------------------------- ③ 面板不把旁账当卡（判据 3）


def test_wb_dash_card_list_has_no_route(tmp_path: Path) -> None:
    """★ 判据 3：目录里有 `wb-route.jsonl` ⇒ 面板的卡片列表里**没有** `route`。"""
    diag = _diag(tmp_path)
    _touch(diag / "wb-001.jsonl", '{"type":"assistant"}\n')
    _touch(diag / "wb-route.jsonl", '{"route":"codearts"}\n')
    _touch(diag / "wb-usage.r2.jsonl", '{"tokens_in":1}\n')

    cards = [card for _tree, card, _path in wb_dash.discover_logs(tmp_path)]
    assert cards == ["001"], cards
    assert not any(c.startswith("route") for c in cards)
    assert not any(c.startswith("usage") for c in cards)

    # 转发的那层谓词与真源同一结论（改一处两处一起变）。
    assert wb_dash.is_card_log("wb-001.jsonl") is True
    assert wb_dash.is_card_log("wb-route.jsonl") is False
    assert wb_dash.is_card_log("wb-usage.jsonl") is False


# ---------------------------------------------------------------- ④ 假欠账 + 反证（判据 4）


def test_wb_retention_excludes_non_card_but_keeps_real_card(tmp_path: Path) -> None:
    """★ 判据 4：`no_verdict_jsonl` 里没有旁账；**反证**：真卡 `wb-999.jsonl` 无判决必须还在。

    这条的反证是本卡的护栏：把非卡滤掉很容易顺手把整个检查改瞎（`no_verdict_jsonl` 恒空
    ⇒ 巡检永远报「没有欠账」）。所以同一条用例里既有「旁账不在」也有「真欠账还在」。
    """
    diag = _diag(tmp_path)
    (tmp_path / "gates").mkdir(exist_ok=True)
    _touch(diag / "wb-100.jsonl")
    _touch(diag / "wb-100.verdict.txt")
    _touch(diag / "wb-999.jsonl")            # 真卡、无判决 ⇒ 必须报出来（反证）
    _touch(diag / "wb-usage.jsonl")          # 旁账、无判决 ⇒ 不许报
    _touch(diag / "wb-route.jsonl")          # 旁账、无判决 ⇒ 不许报
    _touch(diag / "wb-usage.r2.jsonl")       # 旁账的轮次变体 ⇒ 也不许报

    c = rt.read_counts(tmp_path)
    names = sorted(p.name for p in c.no_verdict_jsonl)
    assert names == ["wb-999.jsonl"], names
    assert c.no_verdict_cards == ["999"], c.no_verdict_cards
    # 旁账压根不进「派活日志」这份名单（`:168` 那一处就滤掉了，下游三处自动对）。
    assert sorted(p.name for p in c.jsonl_files) == ["wb-100.jsonl", "wb-999.jsonl"]
    assert c.n_jsonl == 2, c.n_jsonl
    assert c.n_verdict == 1, c.n_verdict
    assert c.n_no_verdict == 1, c.n_no_verdict

    # 归档计划也跟着对（它读的是 `no_verdict_jsonl`）：只该动 999。
    plan = rt.archive_plan(tmp_path, min_age_days=0.0)
    assert [a.src.name for a in plan] == ["wb-999.jsonl"], plan


# ---------------------------------------------------------------- ⑤ scan_jobs（判据 5）


def test_scan_jobs_marks_non_card_logs_apart(tmp_path: Path) -> None:
    """★ 判据 5：`wb-usage*` 与 `wb-route.jsonl` 都标「非派活」，只有 `001` 是真卡态。

    读法（主控 2026-10-31 裁定）：非卡**保留**那一行、`state="非派活"`（`job_list` 的
    「共 N 个日志」依赖它）—— 所以断言是「非 `非派活` 的行里只有 `001`」。
    """
    diag = _diag(tmp_path)
    _touch(diag / "wb-001.jsonl", '{"type":"assistant"}\n')
    _touch(diag / "wb-usage.jsonl", '{"tokens_in":1}\n')
    _touch(diag / "wb-usage.r2.jsonl", '{"tokens_in":2}\n')
    _touch(diag / "wb-route.jsonl", '{"route":"codearts"}\n')

    rows = jobs.scan_jobs(diag, now=None)
    by_log = {row["log"]: row for row in rows}
    assert set(by_log) == {
        "wb-001.jsonl", "wb-usage.jsonl", "wb-usage.r2.jsonl", "wb-route.jsonl"
    }, sorted(by_log)

    real = [row for row in rows if row["state"] != "非派活"]
    assert [row["log"] for row in real] == ["wb-001.jsonl"], real

    for name in ("wb-usage.jsonl", "wb-usage.r2.jsonl", "wb-route.jsonl"):
        assert by_log[name]["state"] == "非派活", by_log[name]
        assert by_log[name]["why"], f"{name} 标了非派活却没给理由"
        assert "不是派活日志" in by_log[name]["why"], by_log[name]["why"]


# ---------------------------------------------------------------- ⑥ 一处加、四处生效（判据 6）


def test_adding_a_name_in_one_place_takes_effect_everywhere(tmp_path: Path, monkeypatch) -> None:
    """★ 判据 6：只改**那一处定义**，四个读者同时生效 —— 没有第二处要改。

    这里改的是真源那个正则（`jobs.NON_CARD_LOG_RE`，全仓唯一一份名单），然后问四个读者：
    `scan_jobs` / 面板 / 留痕 / 项目书 —— 全都必须立刻认新名字。任何一处还要另外改，
    这条就会红。
    """
    assert jobs.is_card_log("wb-foo.jsonl") is True, "前提不成立：foo 现在本该算卡"

    monkeypatch.setattr(
        jobs,
        "NON_CARD_LOG_RE",
        jobs.re.compile(r"^wb-(?P<kind>usage|route|foo)(?:\.r\d+)?\.jsonl$"),
    )

    # 读者一：库自己的谓词（另外三个读者都问它）。
    assert jobs.is_card_log("wb-foo.jsonl") is False
    assert jobs.non_card_reason("wb-foo.jsonl"), "新名字认成非卡了，却给不出理由"

    # 读者二：面板（`wb_dash.is_card_log` 只是转发）。
    assert wb_dash.is_card_log("wb-foo.jsonl") is False
    diag = _diag(tmp_path)
    _touch(diag / "wb-002.jsonl")
    _touch(diag / "wb-foo.jsonl")
    assert [card for _t, card, _p in wb_dash.discover_logs(tmp_path)] == ["002"]

    # 读者三：留痕巡检。
    c = rt.read_counts(tmp_path)
    assert sorted(p.name for p in c.jsonl_files) == ["wb-002.jsonl"]
    assert [p.name for p in c.no_verdict_jsonl] == ["wb-002.jsonl"]

    # 读者四：项目书的派活日志份数。
    assert gpr._is_card_log("wb-foo.jsonl") is False
    assert gpr._is_card_log("wb-002.jsonl") is True
    _touch(diag / "wb-usage.jsonl")
    batch, logs, warns = gpr.diag_metrics(tmp_path)
    assert logs == 1, f"项目书把旁账算进派活日志了（数到 {logs}）；warns={warns}"


# ---------------------------------------------------------------- 第四读者（判据 1 扩域）


def test_gen_pool_readme_counts_only_card_logs(tmp_path: Path) -> None:
    """★ `scripts/gen_pool_readme.py` 是 `wb-*.jsonl` 的**第四个**读者 —— 它也得过同一谓词。

    它算的是 README 里那句「派活日志 241 份」的人话数字。改前它的写法是
    `path.name != "wb-usage.jsonl"` 这样一句字面量：`wb-route.jsonl` 一落地，那句数字就会
    从 241 变成 242，多出来的那份**不是**派活日志。
    """
    diag = _diag(tmp_path)
    _touch(diag / "wb-001.jsonl")
    _touch(diag / "wb-B1.jsonl")
    _touch(diag / "wb-usage.jsonl")
    _touch(diag / "wb-usage.r2.jsonl")
    _touch(diag / "wb-route.jsonl")          # ★ 这棵树里真实不存在，用例自己造
    batch, logs, warns = gpr.diag_metrics(tmp_path)
    assert logs == 2, f"派活日志数错了：{logs}（只该数 001 与 B1）"
    assert batch == 0
    assert warns == []


def test_gen_pool_readme_check_is_green() -> None:
    """★ 主控硬要求：本卡改完，`--check` 仍退 0（今天的数字一字不变）。

    `wb-route.jsonl` 今天不在盘上 ⇒ 改前改后都必须数到同一个数。真正的读数写进回执。
    """
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(REPO / "scripts" / "gen_pool_readme.py"), "--check"],
        cwd=str(REPO),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "与现算一致" in proc.stdout, proc.stdout
