"""卡 021 · myday 拖拽**无版本守卫**：先验证 A8「并发丢更新/重号」是不是真的（T-G109）。

## 背景（出处）

盘点卡 S-1 的 A8（`gates/diag/盘点-20260926.md`；原话在 `gates/diag/wb-review-T-G79.md` §3）：
`place_myday` / `move_myday` 是「读整个清单 → 算新顺序 → 写回」，读与写之间**没有版本守卫**
（`_write_myday_rank` 的 UPDATE 只抬 `version`、不比较它）—— 两个请求交错理论上会丢更新
或撞重号，"只是怀疑，没验"。本文件先是那一次验证（复现**成立**）；随后按主控裁定 ① 落地
乐观锁（`_write_myday_rank` 加 `AND version = ?`、撞了重读重算重试一次、再撞抛
`MydayConflictError`；整份调序计划原子化，见 `复盘/myday版本守卫-T-G109.md` §4），
本文件现在是**钉住这条守卫的回归用例**。

## 复现怎么造的（确定性，不靠 sleep 碰运气）

`monkeypatch` 换掉 `manager._apply_myday_order`：两个线程各持**独立连接**跑 `place_myday`，
先到者（leader）与后到者（follower）在**写之前**用 `Barrier(2)` 会合 —— 于是两边读的
是**同一份快照**；leader 写完后 follower 才写（`Event`），follower 的计划建立在**已过期**
的快照上。这就是「A 读列 → B 读列 → A 写 → B 写」那条交错，只是用屏障把它钉成必然发生。

初态：戊 甲 乙 丙 丁（号 1..5）。一程把「丁」拖到「戊」前，另一程把「丙」拖到「甲」前。
**两种到达次序下，两次移动都生效的串行正解都是 丁 戊 丙 甲 乙**（对照用例先把它钉死）。
无守卫时的实测（行号以提交 `0ba5953` 为准）：
- follower 是「丙→甲前」那一程：它的计划只写 {丙：2, 甲：3, 乙：4}，盖在 leader 已写的
  {丁：1, 戊：2, …} 上 → **戊=2 与 丙=2 并存（重号）**，号 5 没人拿（号段残缺）；
- follower 是「丁→戊前」那一程：它把全表重写成 {丁：1, 戊：2, 甲：3, 乙：4, 丙：5} →
  「丙→甲前」那一程**整段被丢（丢更新）**，最终顺序 丁 戊 甲 乙 丙 ≠ 正解。
"""

from __future__ import annotations

import itertools
import threading
from typing import TYPE_CHECKING

from timeflow.core.tasks import manager
from timeflow.storage import db as db_mod

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    import pytest

    Row = tuple[object, int]


def _fresh_db(path: Path) -> sqlite3.Connection:
    """建五条都进今天的任务，各带不同截止日 —— 老口径次序定死为 甲乙丙丁戊。"""
    conn = db_mod.connect(str(path))
    for i, title in enumerate(("甲", "乙", "丙", "丁", "戊")):
        manager.create_task(conn, title, due_date=f"2026-01-0{i + 1}", is_myday=True)
    return conn


def _rank_all(conn: sqlite3.Connection) -> dict[str, str]:
    """把「戊」拖到最前 → 整列拿到号 1..5（初态：戊 甲 乙 丙 丁）。返回 {标题： id}。"""
    items = manager.myday_tasks(conn)
    manager.place_myday(conn, items[-1].id, items[0].id)
    return {t.title: t.id for t in manager.myday_tasks(conn)}


def _snapshot(path: Path) -> dict[str, Row]:
    """每一行的 `(myday_rank, version)` —— 直连库读，与幂等卡（T-G86）同一个判据读法。"""
    conn = db_mod.connect(str(path))
    try:
        rows = conn.execute(
            "SELECT id, myday_rank, version FROM tasks WHERE is_myday = 1"
        ).fetchall()
        return {str(r["id"]): (r["myday_rank"], int(r["version"])) for r in rows}
    finally:
        conn.close()


def _order(path: Path) -> list[str]:
    conn = db_mod.connect(str(path))
    try:
        return [t.title for t in manager.myday_tasks(conn)]
    finally:
        conn.close()


# ------------------------------------------------------------------ 对照：串行正解
def test_sequential_moves_give_the_expected_order(tmp_path: Path) -> None:
    """对照：同两条移动**串行**做 —— 这就是并发用例断言的那个「两次都生效」的正解。"""
    path = tmp_path / "myday.db"
    conn = _fresh_db(path)
    ids = _rank_all(conn)
    manager.place_myday(conn, ids["丁"], ids["戊"])   # 丁 → 最前
    manager.place_myday(conn, ids["丙"], ids["甲"])   # 丙 → 甲前
    conn.close()

    assert _order(path) == ["丁", "戊", "丙", "甲", "乙"]
    ranks = [r for r, _ in _snapshot(path).values() if r is not None]
    assert sorted(ranks) == [1, 2, 3, 4, 5]


# ------------------------------------------------------------------ 复现：读→算→写 交错
def test_concurrent_drags_do_not_lose_updates_or_duplicate_ranks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """两线程、各持独立连接同时拖 —— 交错开「读→算→写」窗口后，两次移动都必须生效。

    屏障只负责**把交错钉成必然**（卡 021 §7-1 钦点的做法），不改变被测代码的路径：
    两边照常走 `place_myday` 的「读清单 → 算号 → 逐行 UPDATE」。
    """
    path = tmp_path / "myday.db"
    base = _fresh_db(path)
    ids = _rank_all(base)
    base.close()

    barrier = threading.Barrier(2)
    leader_done = threading.Event()
    arrivals = itertools.count()
    original = manager._apply_myday_order

    def interleaved(
        conn: sqlite3.Connection, items: list[manager.Task], order: list[str]
    ) -> None:
        if next(arrivals) == 0:
            barrier.wait(timeout=30)       # leader：等 follower 也读完快照，再整段写
            original(conn, items, order)
            leader_done.set()
        else:
            barrier.wait(timeout=30)       # follower：快照就此过期
            assert leader_done.wait(timeout=30), "leader 没写完（复现装置自己卡住了）"
            original(conn, items, order)   # 按过期快照写回 —— A8 怀疑的就是这一步

    monkeypatch.setattr(manager, "_apply_myday_order", interleaved)

    errors: list[BaseException] = []

    def drag(task: str, before: str) -> None:
        conn = db_mod.connect(str(path))
        try:
            manager.place_myday(conn, ids[task], ids[before])
        except BaseException as exc:  # noqa: BLE001 —— 线程里的错带回主线程报
            errors.append(exc)
        finally:
            conn.close()

    t1 = threading.Thread(target=drag, args=("丁", "戊"))   # 丁 → 最前
    t2 = threading.Thread(target=drag, args=("丙", "甲"))   # 丙 → 甲前
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not errors, f"并发拖拽抛错： {errors!r}"
    snap = _snapshot(path)
    ranks = [r for r, _ in snap.values() if r is not None]
    assert len(ranks) == len(set(ranks)), f"并发之后 myday_rank 撞出重号： {snap}"
    assert sorted(ranks) == [1, 2, 3, 4, 5], f"并发之后号段残缺： {snap}"
    assert _order(path) == ["丁", "戊", "丙", "甲", "乙"], (
        f"两次移动都生效的串行正解（对照用例已钉）；实际： {_order(path)} / {snap}"
    )
