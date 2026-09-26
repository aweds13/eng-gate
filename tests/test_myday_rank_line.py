"""T-G98 · 今天清单序号的「整列写回」根因：隐藏条目的旧号 vs 可见条目的新号。

## 为什么单开一个文件

T-G86（`复盘/幂等写库-T-G86.md`）修掉了"**没动也写库**"那半 —— 空转不再整表重写、也不再
把没拖过的 `NULL` 冻成序号。但同一处"读整列 → 算 → 整列写回"还长着另一半：

- **`myday_tasks()` 把完成 / 取消 / 待定 / 归档 / 已删从查询里滤掉，却不动它们的 `myday_rank`**；
  而规整只按**可见**条目编号 —— 于是隐藏条目带着旧号回来时，会和可见条目的号**撞车**
  （重号），"撤销完成"的那条还会**幽灵归位**到旧号所在的位置（`gates/diag/wb-review-T-G79.md`
  的边界 B）。

## 这一批用例在防什么

① **非排序动作不许动序号列**（症状 C）：完成 / 取消 / 备注 / 改标题这些动作**一个**
   `myday_rank` 都不许改 —— 因为 `version` 是跨端合并（LWW）的首选键，乱写它会让别的端的
   真改动被顶掉（`src/web/offline.js` 的字段白名单里有 `myday_rank`，`syncpack` 整行覆盖）；
② **隐藏条目的旧号不许和可见条目的新号撞**（症状 B）：规整可见条目时要绕开被隐藏条目
   **占着**的号，断言"今天清单里 `is_myday=1` 的非空号两两不同"；
③ **撤销完成排最后**（T-G98 选的那一支）：那条已经离开过清单，回来时**排到末尾**，
   不插回旧号的位置（与"移出今天再加回来排末尾"同一条规矩，见 `test_myday_order_line.py`）；
④ **排序动作只写"真的换了号"的行**（症状 C 的另一面）：一次真拖里号没变的行 `version` 不许白涨。

判据是**数出来的**：拿一条直连库的连接，动作前后各取一次 `{id: (myday_rank, version)}`
逐行比 —— 与 `test_myday_idempotence_line.py` 同一个读法。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.storage import db as db_mod

if TYPE_CHECKING:
    from pathlib import Path

    Row = tuple[object, int]


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(str(tmp_path / "myday.db")))


def _add(client: TestClient, title: str, *, due: str | None = None) -> str:
    body: dict[str, object] = {"title": title, "is_myday": True}
    if due:
        body["due_date"] = due
    resp = client.post("/api/tasks", json=body)
    assert resp.status_code == 200, resp.text
    return str(resp.json()["id"])


def _snap(path: Path) -> dict[str, Row]:
    """今天清单每一行（含被隐藏的）的 `(myday_rank, version)` —— 直连库读，绕开被测接口。"""
    conn = db_mod.connect(str(path))
    try:
        rows = conn.execute(
            "SELECT id, myday_rank, version FROM tasks WHERE is_myday = 1"
        ).fetchall()
        return {str(r["id"]): (r["myday_rank"], int(r["version"])) for r in rows}
    finally:
        conn.close()


def _changed(before: dict[str, Row], after: dict[str, Row]) -> set[str]:
    return {tid for tid, val in before.items() if after.get(tid) != val}


def _ranks(snap: dict[str, Row]) -> list[object]:
    return [rank for rank, _ in snap.values() if rank is not None]


def _order(client: TestClient) -> list[str]:
    return [t["title"] for t in client.get("/api/mydays").json()]


def _rank(client: TestClient, task_id: str) -> object:
    return client.get(f"/api/tasks/{task_id}").json()["myday_rank"]


def _three_with_numbers(client: TestClient) -> dict[str, str]:
    """摆成 `[B2, B1, B3]`，且号是 `B2=1, B1=2, B3=3`（复核报告边界 B 的那个现场）。

    走的是**真拖**（不是直接写库）：先拖 B3 到最前让整列拿到号，再把 B3 拖到末尾还原次序。
    截止日各不相同，所以"老口径"的先后是确定的（不靠 `created_at` 撞秒）。
    """
    ids = {
        "B2": _add(client, "B2", due="2026-03-01"),
        "B1": _add(client, "B1", due="2026-03-02"),
        "B3": _add(client, "B3", due="2026-03-03"),
    }
    assert _order(client) == ["B2", "B1", "B3"]
    assert client.post(f"/api/tasks/{ids['B3']}/myday-move",
                       json={"before": ids["B2"]}).status_code == 200   # B3 到最前
    assert client.post(f"/api/tasks/{ids['B3']}/myday-move",
                       json={"before": None}).status_code == 200        # B3 到末尾 → 还原
    assert _order(client) == ["B2", "B1", "B3"]
    return ids


# ---------------------------------------------------------------- ① 非排序动作不许动序号列
def test_hiding_or_editing_a_task_never_moves_the_sort_column(tmp_path: Path) -> None:
    """完成 / 取消 / 备注 / 改标题 / 改优先级 —— **今天清单里一个 `myday_rank` 都不许变**。

    尤其是「完成」：它只是把一条从**可见清单**里藏起来，不是"重排"。要是它顺手改了号，
    这条改动会跟着 `version` 同步到别的端，把那边真正的改动顶掉（症状 C）。
    """
    client = _client(tmp_path)
    ids = _three_with_numbers(client)
    path = tmp_path / "myday.db"

    before = _snap(path)
    assert client.patch(f"/api/tasks/{ids['B1']}", json={"title": "B1改"}).status_code == 200
    assert client.patch(f"/api/tasks/{ids['B1']}", json={"note": "备注"}).status_code == 200
    assert client.patch(f"/api/tasks/{ids['B1']}", json={"priority": "高"}).status_code == 200
    assert client.patch(f"/api/tasks/{ids['B1']}", json={"flagged": True}).status_code == 200
    assert client.post(f"/api/tasks/{ids['B2']}/complete").status_code == 200
    after = _snap(path)

    ranks_before = {tid: val[0] for tid, val in before.items()}
    ranks_after = {tid: val[0] for tid, val in after.items()}
    assert ranks_after == ranks_before, \
        "非排序动作（完成 / 改标题 / 备注 / 优先级 / 标记）把 myday_rank 动了"
    # 被完成的那条也仍然留着它的号（留号是刻意的：不留号就说明"完成"动了序号列）
    assert _rank(client, ids["B2"]) == before[ids["B2"]][0]
    assert _order(client) == ["B1改", "B3"], "完成只是把它藏起来，可见次序不变"


def test_cancelling_and_archiving_do_not_touch_the_sort_column(tmp_path: Path) -> None:
    """取消 / 待定 / 归档 / 已删 —— 同样一个号都不许动（机制与「完成」是同一条过滤）。"""
    client = _client(tmp_path)
    ids = _three_with_numbers(client)
    path = tmp_path / "myday.db"

    before = _snap(path)
    client.patch(f"/api/tasks/{ids['B2']}", json={"status": "取消"})
    client.patch(f"/api/tasks/{ids['B3']}", json={"status": "归档"})
    after = _snap(path)

    assert {t: v[0] for t, v in after.items()} == {t: v[0] for t, v in before.items()}
    assert _order(client) == ["B1"], "搁置 / 归档的都从可见清单里消失，剩下的次序不变"


# ---------------------------------------------------------------- ② 隐藏旧号 vs 可见新号：不许撞
def test_a_visible_renumber_never_collides_with_a_hidden_rank(tmp_path: Path) -> None:
    """复核报告边界 B 的现场：完成 B2（留号 1）→ 再拖 B3 到 B1 前 —— 号**不许**重。

    ★ 这一条在改之前是**红的**：可见条目从 `1` 起编号，B3 会拿到 1，与藏着 B2 的旧号 1 撞车。
    修法是"可见条目取号时绕开被隐藏条目占着的号"（`_myday_reserved_ranks`）。
    """
    client = _client(tmp_path)
    ids = _three_with_numbers(client)
    path = tmp_path / "myday.db"
    ranks_setup = {t: _snap(path)[tid][0] for t, tid in ids.items()}
    assert all(r is not None for r in ranks_setup.values()), "摆好现场：三条都要有号"
    assert len(set(ranks_setup.values())) == 3, "摆好现场：三个号互不相同"
    assert ranks_setup["B2"] < ranks_setup["B1"] < ranks_setup["B3"], "摆好现场：B2<B1<B3"
    b2_before = ranks_setup["B2"]

    client.post(f"/api/tasks/{ids['B2']}/complete")           # B2 藏起来，留着号 1
    assert client.post(f"/api/tasks/{ids['B3']}/myday-move",
                       json={"before": ids["B1"]}).status_code == 200

    ranks = _ranks(_snap(path))
    assert len(ranks) == len(set(ranks)), f"今天清单里出现了重号：{ranks}"
    assert _order(client) == ["B3", "B1"]
    assert _rank(client, ids["B3"]) is not None \
        and _rank(client, ids["B3"]) != _rank(client, ids["B2"]), \
        "可见条目要绕开被隐藏条目占着的号（不许重号）"
    assert _rank(client, ids["B2"]) == b2_before, "藏起来的那条留着它的号（非排序动作没动它）"


def test_uncompleting_goes_last_not_back_to_the_old_slot(tmp_path: Path) -> None:
    """撤销完成 → **排最后**（不插回旧号的位置）。

    ★ 这一条在改之前是**红的**：B2 带着旧号 1 回来，和可见条目的号撞车，靠"并列时按老口径"
    的兜底排序**幽灵归位**到第 1 位。修法：从隐藏态回到可见态时**清号**（`update_task`），
    于是它按老口径排到"排过号的那一截"后面 = 末尾。
    """
    client = _client(tmp_path)
    ids = _three_with_numbers(client)
    path = tmp_path / "myday.db"
    client.post(f"/api/tasks/{ids['B2']}/complete")
    client.post(f"/api/tasks/{ids['B3']}/myday-move", json={"before": ids["B1"]})
    assert _order(client) == ["B3", "B1"]

    assert client.post(f"/api/tasks/{ids['B2']}/uncomplete").status_code == 200
    assert _order(client) == ["B3", "B1", "B2"], "撤销完成要排最后，不许幽灵归位到旧号的位置"
    assert _rank(client, ids["B2"]) is None, "回到可见态要清号（旧号已经不该留着）"
    ranks = _ranks(_snap(path))
    assert len(ranks) == len(set(ranks)), f"撤销完成之后又重号了：{ranks}"


# ---------------------------------------------------------------- ④ 排序动作只写"真的换了号"的行
def test_a_real_drag_only_bumps_the_rows_whose_rank_changed(tmp_path: Path) -> None:
    """一次真拖里，号没变的行 `version` **不许**白涨（症状 C：跨端 LWW 里空写最伤人）。"""
    client = _client(tmp_path)
    ids = {t: _add(client, t, due=f"2026-04-0{i}") for i, t in enumerate("甲乙丙丁", start=1)}
    path = tmp_path / "myday.db"
    # 整列拿到 1..4（丁 拖到最前），再还原成 甲乙丙丁
    client.post(f"/api/tasks/{ids['丁']}/myday-move", json={"before": ids["甲"]})
    client.post(f"/api/tasks/{ids['丁']}/myday-move", json={"before": None})
    assert _order(client) == ["甲", "乙", "丙", "丁"]

    before = _snap(path)
    assert client.post(f"/api/tasks/{ids['丁']}/myday-move",
                       json={"before": ids["乙"]}).status_code == 200
    after = _snap(path)
    assert _order(client) == ["甲", "丁", "乙", "丙"]

    for tid, (rank0, ver0) in before.items():
        rank1, ver1 = after[tid]
        if rank0 == rank1:
            assert (rank0, ver0) == (rank1, ver1), \
                f"号没变却写了这一行（version 白涨）：{rank0}->{rank1} v{ver0}->{ver1}"
        else:
            assert ver1 == ver0 + 1, "真换了号的行才涨 version，且只涨一格"
    assert before[ids["甲"]] == after[ids["甲"]], "「甲」的号与位置都没变，不该被写"
