"""卡 022 · myday 稀疏序号：真拖只写换位那一行（T-G86.gaps 说的「另一张卡」）。

## 背景（出处）

T-G86 修掉「幂等动作整表重写」时留了一条边界（`复盘/幂等写库-T-G86.md` §3 66-69 行）：
一次真拖仍把**排过号的那一截（头）**整截重排成 `1..m` —— 头里 m 行的 `version` 全抬，
跨端 LWW 按 `version` 判新旧，这正是 A7 那族风险的尾巴。本卡把取号改成**有间隙**的
稀疏序号（主控裁定 卡022 §2.9：首号 1000、步长 1000、插入取中点；间隙耗尽只对冲突
那一小段做局部 renormalize，且**不动 version**），让「挪一步只动自己」成立。

## 这一批用例在防什么

① **真拖只写最少行**：已全带号的清单里拖一次，直连库取 `{id: (myday_rank, version)}`
   前后逐行比 —— 只允许真的换位的那一行变化（旧实现同一动作写 3 行，探针对照见复盘）；
② **取号口径**：首号 / 步长 / 中点按裁定常量钉住（相对判据，不写字面号值）；
③ **间隙耗尽**：中点一路对半收敛逼到相邻时，局部 renormalize 真的被执行到（不是死代码）
   —— 被重排的行**只改数字、不动 version**；旧版稠密号（1、2 这种）插进来同样要走这条路；
④ **A7 跨端（库级）**：两个「端」各持连接读写交错 —— 非排序动作不碰序号列，
   顺序也不被整列覆写。

判据读法与 `test_myday_idempotence_line.py` 同一（直连库取快照逐行比）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from timeflow.core.tasks import manager as tm
from timeflow.storage import db as db_mod

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path


def _fresh(path: Path) -> sqlite3.Connection:
    """五条都进今天、各带不同截止日 —— 老口径次序定死为 甲乙丙丁戊。"""
    conn = db_mod.connect(str(path))
    for i, title in enumerate(("甲", "乙", "丙", "丁", "戊")):
        tm.create_task(conn, title, due_date=f"2026-01-0{i + 1}", is_myday=True)
    conn.commit()
    return conn


def _snap(conn: sqlite3.Connection) -> dict[str, tuple[object, int]]:
    """每行的 `(myday_rank, version)` —— 直连库读，绕开被测代码自己的读法。"""
    rows = conn.execute(
        "SELECT title, myday_rank, version FROM tasks WHERE is_myday = 1"
    ).fetchall()
    return {str(r["title"]): (r["myday_rank"], int(r["version"])) for r in rows}


def _changed(
    before: dict[str, tuple[object, int]], after: dict[str, tuple[object, int]]
) -> set[str]:
    return {t for t in before if after[t] != before[t]}


def _ranked(conn: sqlite3.Connection) -> list[str]:
    return [t.title for t in tm.myday_tasks(conn)]


def _tid(conn: sqlite3.Connection, title: str) -> str:
    return str(conn.execute("SELECT id FROM tasks WHERE title = ?", (title,)).fetchone()[0])


# ------------------------------------------------------------------ ① 真拖只写换位那一行
def test_a_real_drag_writes_only_the_moved_row(tmp_path: Path) -> None:
    """全列有号之后，把「丁」拖到「乙」前面 —— **只有丁那一行**（rank+version）变化。

    旧实现（T-G86 时的整截重排）同一动作写 **3 行**（丁、乙、丙全被重排，version 全抬）；
    稀疏取号后只写 1 行。这个对照读数就是本卡的先红后绿（原始输出贴在复盘里）。
    """
    conn = _fresh(tmp_path / "myday.db")
    tm.place_myday(conn, _tid(conn, "戊"), _tid(conn, "甲"))   # 戊 → 最前：全列拿到号
    assert _ranked(conn) == ["戊", "甲", "乙", "丙", "丁"]

    before = _snap(conn)
    tm.place_myday(conn, _tid(conn, "丁"), _tid(conn, "乙"))   # 丁 → 乙 前
    after = _snap(conn)

    assert _ranked(conn) == ["戊", "甲", "丁", "乙", "丙"]
    assert _changed(before, after) == {"丁"}, \
        f"真拖只许写换位那一行，实际写了：{sorted(_changed(before, after))}"
    rank_jia, rank_yi = before["甲"][0], before["乙"][0]
    assert after["丁"][0] == (rank_jia + rank_yi) // 2, "落点取两邻的中点（卡 022 §2.9）"
    assert after["丁"][1] == before["丁"][1] + 1, "真换位的行 version 只涨一格"
    conn.close()


# ------------------------------------------------------------------ ② 取号口径
def test_first_rank_and_the_end_of_the_list_use_the_ruled_stride(tmp_path: Path) -> None:
    """第一枚号 = 裁定首号；挪到末尾 = 当前最大 + 裁定步长（都按常量比，不写字面值）。"""
    conn = _fresh(tmp_path / "myday.db")
    tm.place_myday(conn, _tid(conn, "戊"), _tid(conn, "甲"))   # 戊 → 最前：第一枚号
    snap1 = _snap(conn)
    assert snap1["戊"][0] == tm._MYDAY_RANK_FIRST, "首号按裁定常量（卡 022 §2.9）"

    before = _snap(conn)                                        # 此时最大号是 丁 那枚
    tm.place_myday(conn, _tid(conn, "乙"), None)                # 乙 → 末尾
    after = _snap(conn)

    assert _ranked(conn) == ["戊", "甲", "丙", "丁", "乙"]
    assert _changed(before, after) == {"乙"}, \
        f"挪到末尾只许写乙自己，实际写了：{sorted(_changed(before, after))}"
    assert after["乙"][0] == before["丁"][0] + tm._MYDAY_RANK_STEP, \
        "末尾取号 = 当前最大 + 步长"
    conn.close()


# ------------------------------------------------------------------ ③ 间隙耗尽 → 局部 renormalize
def test_gap_exhaustion_renormalizes_locally_without_bumping_version(tmp_path: Path) -> None:
    """连续往同一处插新行，中点一路对半收敛 → 间隙必然逼到相邻。

    耗尽那一刻的**签名**：某个已有号的行只改了数字、`version` 没动（renormalize 不动
    version，卡 022 §2.9）—— 这同时证明耗尽路径不是死代码。
    """
    conn = _fresh(tmp_path / "myday.db")
    tm.place_myday(conn, _tid(conn, "戊"), _tid(conn, "甲"))   # 全列有号
    names = ("己", "庚", "辛", "壬", "癸", "子", "丑", "寅", "卯", "辰", "巳", "午")

    renorm_seen = False
    for name in names:
        tm.create_task(conn, name, due_date="2026-02-01", is_myday=True)
        conn.commit()
        before = _snap(conn)
        tm.place_myday(conn, _tid(conn, name), _tid(conn, "乙"))   # 塞到 乙 前面
        after = _snap(conn)
        for t, (r0, v0) in before.items():
            r1, v1 = after[t]
            if t != name and r0 is not None and r1 is not None and r0 != r1 and v1 == v0:
                renorm_seen = True
        if renorm_seen:
            break
    assert renorm_seen, "中点插入直到间隙耗尽，renormalize 一直没被触发（耗尽策略没接上）"
    ranks = [r for r, _ in _snap(conn).values() if r is not None]
    assert len(ranks) == len(set(ranks)), "耗尽重排之后不许重号"
    conn.close()


def test_inserting_into_a_legacy_dense_gap_still_renormalizes(tmp_path: Path) -> None:
    """旧版稠密号（1、2 相邻）升级上来的库：往中间插一行也要走耗尽重排，且只波及一小段。"""
    conn = _fresh(tmp_path / "myday.db")
    conn.execute("UPDATE tasks SET myday_rank = 1 WHERE title = '甲'")
    conn.execute("UPDATE tasks SET myday_rank = 2 WHERE title = '乙'")
    conn.commit()
    before = _snap(conn)

    tm.place_myday(conn, _tid(conn, "丙"), _tid(conn, "乙"))   # 丙 → 乙 前：塞不进 (1, 2)
    after = _snap(conn)

    assert _ranked(conn) == ["甲", "丙", "乙", "丁", "戊"]
    bumped = {t for t in before if after[t][1] == before[t][1] + 1}
    assert bumped == {"丙"}, f"真换位的只有丙（version 抬一格），实际：{sorted(bumped)}"
    renorm = {
        t
        for t in before
        if t != "丙" and after[t][0] != before[t][0] and after[t][1] == before[t][1]
    }
    assert renorm == {"甲"}, \
        f"间隙耗尽要触发局部 renormalize（只改数字不动 version）且只波及甲，实际：{sorted(renorm)}"
    conn.close()


# ------------------------------------------------------------------ ④ A7 跨端（库级）
def test_two_ends_interleave_without_rewriting_the_rank_column(tmp_path: Path) -> None:
    """同一份数据、两个「端」（两条连接）读写交错（A7，库级断言，不引真网络）：

    端 B 真拖一次 → 只有换位那一行变化；端 A 做**非排序动作**（改标题）→ 那一行的
    `myday_rank` 不许动、**别的行一个字节都不许动**；端 A 再拖一次 → 顺序正确且仍然
    只写一行 —— 合并后顺序从不被整列覆写。
    """
    path = tmp_path / "myday.db"
    conn_a = db_mod.connect(str(path))
    for i, title in enumerate(("甲", "乙", "丙", "丁")):
        tm.create_task(conn_a, title, due_date=f"2026-01-0{i + 1}", is_myday=True)
    conn_a.commit()
    tm.place_myday(conn_a, _tid(conn_a, "丁"), _tid(conn_a, "甲"))   # 端 A 先拖一次
    base = _snap(conn_a)

    conn_b = db_mod.connect(str(path))                              # 端 B：另一条连接
    tm.place_myday(conn_b, _tid(conn_b, "丙"), _tid(conn_b, "甲"))
    after_b = _snap(conn_a)
    assert _changed(base, after_b) == {"丙"}, \
        f"端 B 真拖只许写丙自己，实际：{sorted(_changed(base, after_b))}"
    assert after_b["丙"][0] is not None and after_b["丙"][0] != base["丙"][0]
    conn_b.close()

    tid_jia = _tid(conn_a, "甲")
    tm.update_task(conn_a, tid_jia, note="备注")                     # 端 A：非排序动作
    after_ns = _snap(conn_a)
    assert _changed(after_b, after_ns) == {"甲"}, \
        f"改标题不许碰别的行，实际动了：{sorted(_changed(after_b, after_ns))}"
    assert after_ns["甲"][0] == after_b["甲"][0], "非排序动作不许动那一行的序号列"

    tm.place_myday(conn_a, _tid(conn_a, "乙"), _tid(conn_a, "丁"))   # 端 A 再拖一次
    final = _snap(conn_a)
    assert _ranked(conn_a) == ["乙", "丁", "丙", "甲"]
    assert _changed(after_ns, final) == {"乙"}, \
        f"端 A 的拖拽仍只许写一行（不许整列覆写），实际：{sorted(_changed(after_ns, final))}"
    conn_a.close()
