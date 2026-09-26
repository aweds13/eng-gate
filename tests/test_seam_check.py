"""`tools/seam_check.py`（跨卡接缝预检，T-G139）的护栏 —— 钉子③：假 diff 单测。

为什么要有测试：这个工具的全部价值是「文件不相交也能报警」，它错了两个方向都致命 ——
漏报（真接缝没报出来 = 白做）与误报（无关卡被拦 = 狼来了）。所以三条钉子至少要有一条
不依赖真仓库：喂假 diff，钉住抽取判据本身。

四条：
1. 有共同符号（签名改动 vs 桩替换同一函数）→ 交集非空 —— 正是卡 022 × T-G126 的形状；
2. 无共同符号 → 交集为空；
3. **同一个文件、不同符号 → 交集为空**（证明不是拿文件路径冒充符号）；
4. 函数体里的局部变量 / 字符串里的词不许被算成形参（反「过度取符号」）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import seam_check as sc  # noqa: E402

# 卡 022 的形状：def 行是上下文行，改动的是参数表里的参数行
DIFF_SIGNATURE = """\
diff --git a/src/timeflow/core/tasks/manager.py b/src/timeflow/core/tasks/manager.py
--- a/src/timeflow/core/tasks/manager.py
+++ b/src/timeflow/core/tasks/manager.py
@@ -10,8 +10,11 @@ def other_helper():
     return vals


 def _write_myday_rank(
-    conn: Connection, task_id: str, rank: int, expected_version: int
+    conn: Connection,
+    task_id: str,
+    rank: int,
+    expected_version: int,
+    *,
+    bump_version: bool = True,
 ) -> None:
     \"\"\"只改顺序号。\"\"\"
"""

# T-G126 的形状：另一个文件，monkeypatch 整只替换成桩
DIFF_STUB = """\
diff --git a/tests/test_myday_conflict_409.py b/tests/test_myday_conflict_409.py
--- a/tests/test_myday_conflict_409.py
+++ b/tests/test_myday_conflict_409.py
@@ -20,5 +20,8 @@ def test_conflict():
+    def always_conflict(conn, task_id, rank, expected_version):
+        raise RuntimeError
+
+    monkeypatch.setattr(manager, "_write_myday_rank", always_conflict)
"""


def _cards(*pairs: tuple[str, str]) -> dict[str, list]:
    return {name: sc.extract_symbols(diff) for name, diff in pairs}


def test_common_symbol_reported() -> None:
    """签名改动 × 桩替换同一函数 → 交集必须报出 _write_myday_rank（钉子③-有）。"""
    cards = _cards(("022", DIFF_SIGNATURE), ("126", DIFF_STUB))
    common = sc.find_common(cards)
    assert "_write_myday_rank" in common, common
    assert set(common["_write_myday_rank"]) == {"022", "126"}
    # 形参名也要被抽出来（卡 022 的契约变化就是多了 bump_version）
    names_022 = {s.name for s in cards["022"]}
    assert {"_write_myday_rank", "bump_version"} <= names_022
    # 桩替换对象也要被抽出来
    names_126 = {s.name for s in cards["126"]}
    assert "_write_myday_rank" in names_126


def test_no_common_symbols_empty() -> None:
    """两份 diff 没有共同符号 → 交集为空。"""
    diff_other = DIFF_STUB.replace("_write_myday_rank", "totally_other_fn")
    cards = _cards(("022", DIFF_SIGNATURE), ("126", diff_other))
    assert sc.find_common(cards) == {}


def test_same_file_different_symbols_empty() -> None:
    """同一个文件、不同符号 → 交集为空（不是拿文件路径冒充符号）。"""
    diff_a = DIFF_SIGNATURE.replace("bump_version", "alpha_param")
    diff_b = DIFF_STUB.replace(
        "tests/test_myday_conflict_409.py", "src/timeflow/core/tasks/manager.py"
    ).replace("_write_myday_rank", "unrelated_fn")
    cards = _cards(("a", diff_a), ("b", diff_b))
    # 两边 path 相同（都是 manager.py），但符号不同 → 交集必须为空
    assert sc.find_common(cards) == {}


def test_body_locals_not_collected() -> None:
    """函数体里的局部变量、字符串里的词不许被算成形参（反过度取符号）。"""
    diff_body = """\
diff --git a/src/timeflow/core/tasks/manager.py b/src/timeflow/core/tasks/manager.py
--- a/src/timeflow/core/tasks/manager.py
+++ b/src/timeflow/core/tasks/manager.py
@@ -30,6 +30,9 @@ def _write_myday_rank(conn, task_id, rank, expected_version):
     快照在写之前过期时这条 UPDATE 影响行数 0。
+    ★ bump_version=False：只改数字（这是文档行，不是参数行）。
+    set_clause = (
+        "myday_rank = ?, version = version + 1" if bump_version else "x = 1"
+    )
+    total = 1,
+        monkeypatch.setattr(manager, "version", 3)
 """
    syms = sc.extract_symbols(diff_body)
    names = {s.name for s in syms}
    # 文档行 / 局部变量 / 字符串里的词都不算形参
    assert "bump_version" not in names, syms
    assert "set_clause" not in names, syms
    assert "total" not in names, syms
    assert "x" not in names, syms
    # 但字符串出现在 setattr 里 → 桩替换对象照样要报（version 被 patch 的形状）
    assert "version" in names, syms


def test_param_names_parse() -> None:
    """参数行的各种形状都能取到名字；取不动的 token 跳过。"""
    assert sc._param_names("bump_version: bool = True,") == ["bump_version"]
    assert sc._param_names("*, alpha_param") == ["alpha_param"]
    assert sc._param_names("conn: sqlite3.Connection,") == ["conn"]
    assert sc._param_names("rank: int | None,") == ["rank"]
    # 下标/属性链不是形参名 → 跳过（宁可少）
    assert sc._param_names("by_id[task_id].version)") == []
    assert sc._param_names("*,") == []


# ---- 卡 054（T-G146）的钉子：注释/字符串里的 setattr/patch 形状不算符号 ----

DIFF_COMMENT = """\
diff --git a/tests/test_a.py b/tests/test_a.py
--- a/tests/test_a.py
+++ b/tests/test_a.py
@@ -1,2 +1,3 @@
+    # see monkeypatch.setattr(w, "egg.spam", x)
"""

DIFF_IN_STRING = """\
diff --git a/tests/test_b.py b/tests/test_b.py
--- a/tests/test_b.py
+++ b/tests/test_b.py
@@ -1,2 +1,3 @@
+    log("patch('egg.spam')")
"""

DIFF_IN_FSTRING = """\
diff --git a/tests/test_b.py b/tests/test_b.py
--- a/tests/test_b.py
+++ b/tests/test_b.py
@@ -1,2 +1,3 @@
+    log(f"patch('egg.spam') end")
"""

DIFF_TRUE_CODE = """\
diff --git a/tests/test_c.py b/tests/test_c.py
--- a/tests/test_c.py
+++ b/tests/test_c.py
@@ -1,2 +1,3 @@
+    monkeypatch.setattr(manager, "_write_myday_rank", always_conflict)
"""

# 三引号跨行：docstring 内容里带 def / setattr 形状（同一病根，一并收）
DIFF_MULTILINE_DOCSTRING = """\
diff --git a/tests/test_d.py b/tests/test_d.py
--- a/tests/test_d.py
+++ b/tests/test_d.py
@@ -1,2 +1,7 @@
+    def helper_with_doc(self):
+        \"\"\"Usage example:
+        def broken_example():
+            monkeypatch.setattr(w, "egg.spam", x)
+        \"\"\"
+        pass
"""


def test_comment_shape_not_collected() -> None:
    """钉子①：一行注释里的 setattr 形状不许产出 spam（RC 反例）。"""
    names = {s.name for s in sc.extract_symbols(DIFF_COMMENT)}
    assert "spam" not in names, names


def test_string_shape_not_collected() -> None:
    """钉子②：字符串里的 patch 形状不许产出 spam（RC 反例）。"""
    names = {s.name for s in sc.extract_symbols(DIFF_IN_STRING)}
    assert "spam" not in names, names


def test_fstring_shape_not_collected() -> None:
    """f-string 里的形状同样不算（三引号/f-string/转义要照顾到）。"""
    names = {s.name for s in sc.extract_symbols(DIFF_IN_FSTRING)}
    assert "spam" not in names, names


def test_true_code_shape_still_collected() -> None:
    """钉子③：真代码的 setattr 实参必须照常产出（不许把真阳性一起收掉）。"""
    syms = sc.extract_symbols(DIFF_TRUE_CODE)
    names = {s.name for s in syms}
    assert "_write_myday_rank" in names, syms
    kinds = {s.name: s.kind for s in syms}
    assert kinds["_write_myday_rank"] == "stub", syms


def test_multiline_docstring_content_not_collected() -> None:
    """三引号 docstring 的内容行不许产出 def / 桩替换符号（宁可少、不可滥）。"""
    syms = sc.extract_symbols(DIFF_MULTILINE_DOCSTRING)
    names = {s.name for s in syms}
    assert "broken_example" not in names, syms
    assert "spam" not in names, syms


def test_false_positive_pair_has_no_intersection() -> None:
    """RC 那对假反例合起来也不许再出交集（原先是 exit 1 的假串行）。"""
    cards = _cards(("a", DIFF_COMMENT), ("b", DIFF_IN_STRING))
    assert sc.find_common(cards) == {}
