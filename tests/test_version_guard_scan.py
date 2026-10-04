"""钉子测试：`tools/version_guard_scan.py`（卡 164 / INV-61 / T-G264）。

判据：
- 合成一个**无守卫**的读-改-写函数（SELECT + UPDATE 无 `AND version = ?`）⇒ 必须被抓进「无守卫」；
- 合成一个**有守卫**的读-改-写函数 ⇒ 必须进「有守卫」；
- 合成一个**只有 upsert** 的函数 ⇒ 不算读-改-写（不报）；
- 真实 `src/` 扫描：有守卫 / 无守卫各**非零**（证明扫描看得到东西），
  且 `_write_myday_rank` 在有守卫里。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import version_guard_scan as vgs  # noqa: E402

_UNGUARDED_SRC = '''
def move_doing(conn, task_id, direction):
    """读整列 → 算 → 写回，无 version 守卫。"""
    items = conn.execute("SELECT * FROM tasks WHERE status = ?").fetchall()
    for i, item in enumerate(items, start=1):
        conn.execute("UPDATE tasks SET doing_rank = ? WHERE id = ?", (i, item["id"]))
'''


_GUARDED_SRC = '''
def place_myday(conn, task_id, rank):
    """读序列 → 写回，带 AND version = ? 乐观锁守卫。"""
    seq = conn.execute("SELECT id, myday_rank, version FROM tasks WHERE is_myday = 1").fetchall()
    expected = next(t["version"] for t in seq if t["id"] == task_id)
    cur = conn.execute(
        "UPDATE tasks SET myday_rank = ?, version = version + 1 WHERE id = ? AND version = ?",
        (rank, task_id, expected),
    )
    if cur.rowcount == 0:
        raise ConflictError("撞并发")
'''


_UPSERT_ONLY_SRC = '''
def put_kv(conn, key, value):
    """只有 upsert，不算读-改-写。"""
    conn.execute(
        "INSERT INTO kv (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
'''


def _func(src: str, name: str) -> ast.FunctionDef:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"没找到函数 {name}")


def test_unguarded_read_modify_write_is_caught() -> None:
    """★ 反例钉子：无守卫的读-改-写 ⇒ 进「无守卫」清单。"""
    hit = vgs.scan_function(_func(_UNGUARDED_SRC, "move_doing"), Path("synthetic.py"))
    assert hit is not None, "读-改-写（SELECT + UPDATE）必须被识别"
    assert hit["guarded"] is False, "无 AND version = ? 必须判为无守卫"
    assert "无 version 守卫" in hit["why"]


def test_guarded_read_modify_write_is_listed_as_guarded() -> None:
    """★ 正例钉子：有守卫的读-改-写 ⇒ 进「有守卫」清单。"""
    hit = vgs.scan_function(_func(_GUARDED_SRC, "place_myday"), Path("synthetic.py"))
    assert hit is not None
    assert hit["guarded"] is True
    assert hit["read_modify_write"] is True
    assert "version 守卫" in hit["why"]


def test_upsert_only_is_not_read_modify_write() -> None:
    """★ upsert 单独一族，不算读-改-写（不报）。"""
    hit = vgs.scan_function(_func(_UPSERT_ONLY_SRC, "put_kv"), Path("synthetic.py"))
    assert hit is None, "只有 upsert 不该被当成读-改-写"


def test_real_src_scan_sees_things_and_myday_rank_is_guarded() -> None:
    """★★ 真实 src/ 扫描：证明扫描**看得到东西** ——
    有守卫 / 无守卫各非零，且 `_write_myday_rank` 在有守卫里、`_write_doing_rank` 在无守卫里
    （doing 排序的底层写 helper 无 `AND version =`，正是 INV-61 要抓的对称缺口）。
    """
    rows = vgs.scan_path(ROOT / "src")
    guarded_names = {r["name"] for r in rows if r["guarded"]}
    unguarded_names = {r["name"] for r in rows if not r["guarded"]}
    assert rows, "src/ 里必须有含 UPDATE 的函数（扫描器坏了或 src 空了）"
    assert "_write_myday_rank" in guarded_names, "myday 排序的守卫必须被认出来"
    assert "_write_doing_rank" in unguarded_names, "doing 排序的写 helper 无守卫必须被抓"
    # 报告能渲染（不炸）
    report = vgs.render_report(rows)
    assert "有守卫" in report and "无守卫" in report
