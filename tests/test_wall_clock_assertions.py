"""钉子：测试**不许拿墙钟秒数当判据**（卡 E136 · `T-AG645`）。

## 为什么有这张测试

`tests/test_gate_lock.py::test_status_names_the_holder` 原本写着
`assert "已 0s" in out or "已 1s" in out` —— 它断言的是「锁刚造出来距今 0~1 秒」。
锁的 `age_seconds` 是墙钟差（`gates/diag/gate_lock.py:604`），机器一忙（xdist 多 worker
+ 落地链并行）夹具与断言之间就隔了 4 秒 ⇒ `已 4s` ⇒ 红。现场：卡 E125 第三次落地
（`gates/diag/land-E125e.log`）22 道门 21 绿，唯一红的就是这条，烧掉 23 分钟全量 pytest。

这类断言的通病：**钉子想钉的是「输出里有这个读数」，写成了「这个数等于几」**。
今天机器闲就绿、明天忙就红 —— 与卡 E126（`--hours 0` 只在验证当天绿）是同一类病，
只是自变量从「日期」换成了「时刻」。

## 这张测试钉住什么

| # | 钉子 | 坏掉会红在哪 |
|---|---|---|
| ① | 真仓 `tests/**/*.py` 里没有「死秒数断言」 | 谁再把 `"已 0s" in out` 写回来 |
| ② | 扫描器**真的在扫**（文件数下限 + 负样例被点名） | 正则写坏 / rglob 错 ⇒ 扫 0 个也算绿 |
| ③ | `test_status_names_the_holder` 用的是形状判据（`re.search`），不是死数 | 判据 1 被改回去 |

## 边界（如实写，未覆盖）

判据只看**字符串常量**：`f"已 {n}s"` 这种插值形态扫不到（那时数字来自变量，
通常已经是「从读数里取出来再比」的写法）。本钉子挡的是「把某个具体秒数写进断言」这一类，
不是万能的「时间敏感测试」检测器。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: 死在断言里的「秒数」形状。只收**带单位 s** 的写法，避免把「5 秒超时」这类合法配置误伤。
#: ★ 卡 E136 现场：第一版正则里写了「任何 N s」，把 `tests/test_pool_patience.py` 的
#: `assert "预算只剩 1s" in err` 也点成了 offender —— 那条是判据 ⑦ 的正当读数（预算剩 1 秒
#: 就该这么说），不是墙钟。所以只收**时刻语**：`已 Ns`（锁/租约已持有）与 `Ns 前 / 后`。
#: 代价是「已过期 30s」这类变体扫不到；本钉子只管把「锁刚造出来距今 0~1 秒」这一种形状挡住。
WALL_CLOCK_PAT = re.compile(r"已\s*\d+\s*s|\d+\s*s\s*[前后]")

#: 比较运算里出现这类常量就算「拿它当判据」；`re.search(...)` 是 Call，不是 Compare ⇒ 不算。
COMPARE_OPS = (ast.In, ast.NotIn, ast.Eq, ast.NotEq)

#: 防「扫了 0 个文件也算绿」：真仓 tests/ 下现读的 .py 数量不许低于这个数。
MIN_SCANNED_FILES = 100


def _literal_hits(node: ast.AST) -> list[str]:
    """这个表达式里有没有「死在里面的秒数」字符串常量。"""
    hits: list[str] = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Constant) or not isinstance(sub.value, str):
            continue
        if WALL_CLOCK_PAT.search(sub.value):
            hits.append(sub.value)
    return hits


def scan_wall_clock_asserts(root: Path) -> tuple[list[str], int]:
    """扫 root 下所有 *.py，返回 (offenders, 扫过的文件数)。

    offender 形如 `tests/x.py:12`，只报 `assert` 里拿秒数字面量做比较的那些。
    """
    offenders: list[str] = []
    seen = 0
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as exc:  # 语法坏的文件该由别的门报，这里不吞
            raise AssertionError(f"{rel} 解析不了：{exc}") from exc
        seen += 1
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assert):
                continue
            for sub in ast.walk(node.test):
                if not isinstance(sub, ast.Compare):
                    continue
                if not any(isinstance(op, COMPARE_OPS) for op in sub.ops):
                    continue
                operands = [sub.left, *sub.comparators]
                for operand in operands:
                    if _literal_hits(operand):
                        offenders.append(f"{rel}:{sub.lineno}")
                        break
    return offenders, seen


def _dedup(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


# ---------------------------------------------------- ① 真仓里一条都没有
def test_real_tree_has_no_wall_clock_assertions() -> None:
    """★ 钉子 ①：真仓 `tests/**/*.py` 里没有「拿死秒数当判据」的断言。"""
    offenders, _seen = scan_wall_clock_asserts(ROOT / "tests")
    assert not offenders, (
        "这些断言把墙钟秒数写死成判据 —— 机器一忙就红"
        "（卡 E136 现场：E125 落地烧 23 分钟全量）：\n  "
        + "\n  ".join(_dedup(offenders))
        + "\n修法：改判形状（re.search(r\"已 \\d+s\", out)）或读结构化读数再比区间。"
    )


# ---------------------------------------------------- ② 扫描器不是空转
def test_scanner_actually_reads_the_tree() -> None:
    """★ 钉子 ②-a：扫过的文件数有下限（rglob 写错 / 正则写坏 ⇒ 一条都不报也「绿」）。"""
    _offenders, seen = scan_wall_clock_asserts(ROOT / "tests")
    assert seen >= MIN_SCANNED_FILES, (
        f"只扫到 {seen} 个 .py，少于下限 {MIN_SCANNED_FILES} ⇒ 扫描器大概是坏的"
    )


def test_scanner_bites_on_a_synthetic_offender(tmp_path: Path) -> None:
    """★ 钉子 ②-b：自造坏样本必须被点名（「扫不到」与「没有坏样本」要分得开）。"""
    bad = tmp_path / "tests"
    bad.mkdir()
    (bad / "test_bad.py").write_text(
        "def test_x() -> None:\n"
        "    out = \"[锁] 已 4s\"\n"
        "    assert \"已 0s\" in out, out\n",
        encoding="utf-8",
    )
    offenders, seen = scan_wall_clock_asserts(bad)
    assert seen == 1, seen
    assert len(offenders) == 1, offenders
    assert offenders[0].endswith("test_bad.py:3"), offenders


def test_scanner_lets_the_shape_form_through(tmp_path: Path) -> None:
    """★ 钉子 ②-c：正则匹配形态**不许**被误伤（否则修法本身就被拦住了）。"""
    good = tmp_path / "tests"
    good.mkdir()
    (good / "test_good.py").write_text(
        "import re\n"
        "def test_x() -> None:\n"
        "    out = \"[锁] 已 4s\"\n"
        "    assert re.search(r\"已 \\d+s\", out), out\n",
        encoding="utf-8",
    )
    offenders, _seen = scan_wall_clock_asserts(good)
    assert not offenders, offenders


# ---------------------------------------------------- ③ 那条具体的钉子改对了
def test_gate_lock_status_pin_uses_a_shape() -> None:
    """★ 钉子 ③：`test_status_names_the_holder` 判的是形状，不是某个具体秒数。"""
    path = ROOT / "tests" / "test_gate_lock.py"
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "test_status_names_the_holder":
            fn = node
    assert fn is not None, (
        "tests/test_gate_lock.py 里找不到 test_status_names_the_holder（钉子被改名 / 删了？）"
    )
    src = ast.get_source_segment(path.read_text(encoding="utf-8", errors="replace"), fn) or ""
    dead = re.search(r"已\s*0\s*s|已\s*1\s*s", src)
    assert dead is None, f"死秒数断言又回来了（命中 {dead.group(0) if dead else ''}）：\n{src}"
    assert "re.search" in src, f"秒数改成形状判据这一处不见了（re.search 没出现在函数里）：\n{src}"
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assert):
            continue
        for sub in ast.walk(node.test):
            if isinstance(sub, ast.Compare):
                for operand in [sub.left, *sub.comparators]:
                    assert not _literal_hits(operand), f"第 {sub.lineno} 行还在拿秒数字面量比较"


def test_this_file_is_itself_clean() -> None:
    """★ 自证：这张测试自己在 `tests/` 下，判据 ① 已经把它一起扫了 —— 这里只是把话说明白。"""
    me = ROOT / "tests" / "test_wall_clock_assertions.py"
    assert me.is_file(), me
    others = scan_wall_clock_asserts(me.parent)[0]
    assert not others, f"① 已经覆盖了本文件；这条红了说明别处的 offender 还在：{others}"

