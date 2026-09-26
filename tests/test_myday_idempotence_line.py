"""T-G86 · 今天清单的「幂等动作零写库」：修 T-G79 那句错话。

## 背景（为什么会单开一个文件）

T-G79 交出拖拽排序时，`复盘/拖拽排序-T-G79.md` 与提交信息都写着：拖到自己前面 /
已在头尾按 ↑↓ 这些**幂等动作"原地不动且不写库"**。**这句是错的** —— 卡 001 的独立复核
（`gates/diag/wb-review-T-G79.md`）与主控探针（`gates/diag/probes/myday_noop_write_check.py`）
两处独立复现出：那两种空转把**整张今天清单**都改写了一遍（`version + 1`），还把 `NULL`
冻成显式 `1..N`。

根因：`place_myday()` / `move_myday()` 的**第一句**都是 `_myday_sequence(conn)`，而
`_myday_sequence()` 会把今天清单的**每一行**都写一次号。

## 这一批用例在防什么

① **幂等 = 零写库**：空转调用之后，被改写的行数必须是 **0**（`myday_rank` 与 `version`
   一个都不许动）；② **不许冻 NULL**：离落点很远、没换过位置、还带着 `NULL` 的行**不许**
   被写上一个号；③ **值没变就不写**：一次真拖里，位置也没变、号也没变的行不许被 `UPDATE`
   （否则 `version` 白涨，跨端合并里真改动更容易输给空写）。

判据是**数出来的**：拿一条直连库的连接，动作前后各取一次
`{id: (myday_rank, version)}`，逐行比 —— 与主控那份探针同一个读法。
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


def _snapshot(path: Path) -> dict[str, Row]:
    """今天清单每一行的 `(myday_rank, version)` —— 直连库读，绕开被测的接口。"""
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


def _by_title(client: TestClient) -> dict[str, str]:
    return {t["title"]: t["id"] for t in client.get("/api/mydays").json()}


def _order(client: TestClient) -> list[str]:
    return [t["title"] for t in client.get("/api/mydays").json()]


def _rank(client: TestClient, task_id: str) -> object:
    return client.get(f"/api/tasks/{task_id}").json()["myday_rank"]


def _five(client: TestClient) -> dict[str, str]:
    """五条都放进今天、**各带一个不同的截止日** —— 老口径（截止日 → …）的次序就定死了。

    为什么不用"创建先后"定序：`created_at` 只到秒，同一秒建的五条谁在前是没保证的
    （老口径最后才比 `created_at`）—— 那样这几条断言就成了看运气。
    """
    ids: dict[str, str] = {}
    for i, t in enumerate(("甲", "乙", "丙", "丁", "戊")):
        ids[t] = _add(client, t, due=f"2026-01-0{i + 1}")
    return ids


# ---------------------------------------------------------------- ① 幂等 = 零写库
def test_dragging_onto_itself_writes_nothing(tmp_path: Path) -> None:
    """拖到自己前面 = 原地不动 —— **一行都不许写**，也不许把 NULL 冻成序号。"""
    client = _client(tmp_path)
    for t in ("甲", "乙", "丙"):
        _add(client, t)
    path = tmp_path / "myday.db"
    mid = _by_title(client)["乙"]

    before = _snapshot(path)
    resp = client.post(f"/api/tasks/{mid}/myday-move", json={"before": mid})
    assert resp.status_code == 200, resp.text
    after = _snapshot(path)

    assert _changed(before, after) == set(), "幂等动作把库写了（T-G79 那个缺陷）"
    assert all(rank is None for rank, _ in after.values()), \
        "空转不许把没拖过的 NULL 冻结成显式序号"
    assert _order(client) == ["甲", "乙", "丙"]


def test_keyboard_at_the_edges_writes_nothing(tmp_path: Path) -> None:
    """已在最前按 ↑ / 已在最后按 ↓ = 原地不动 —— 同样一行都不许写。"""
    client = _client(tmp_path)
    for t in ("甲", "乙", "丙"):
        _add(client, t)
    path = tmp_path / "myday.db"
    ids = _by_title(client)

    before = _snapshot(path)
    assert client.post(f"/api/tasks/{ids['甲']}/myday-move",
                       json={"direction": "up"}).status_code == 200
    assert client.post(f"/api/tasks/{ids['丙']}/myday-move",
                       json={"direction": "down"}).status_code == 200
    after = _snapshot(path)

    assert _changed(before, after) == set(), "已到头/到尾再按 ↑↓ 把库写了"
    assert all(rank is None for rank, _ in after.values()), "空转不许冻 NULL"


# ---------------------------------------------------------------- ② 不冻没动过的 NULL
def test_a_drag_leaves_the_untouched_null_tail_alone(tmp_path: Path) -> None:
    """拖一次只波及**真的动了的那几条**：离落点很远、没换位置的那条仍是 NULL。

    甲 乙 丙 丁 戊（都没号）→ 把「丁」拖到「乙」前面。动的是 丁 自己 + 夹在中间那几条；
    **「戊」在末尾、位置一点没动** → 不许被写上一个号（T-G79 那版会把它也写成 5）。
    """
    client = _client(tmp_path)
    ids = _five(client)
    path = tmp_path / "myday.db"

    before = _snapshot(path)
    assert client.post(f"/api/tasks/{ids['丁']}/myday-move",
                       json={"before": ids["乙"]}).status_code == 200
    after = _snapshot(path)

    assert _order(client) == ["甲", "丁", "乙", "丙", "戊"], "落在「乙前面」= 夹在甲和乙之间"
    assert ids["戊"] not in _changed(before, after), "没动过的尾条不许被写"
    assert _rank(client, ids["戊"]) is None, "没动过的 NULL 不许被冻成序号"
    rank_ding = _rank(client, ids["丁"])
    assert rank_ding is not None, "真换了位置的那条要拿到新号"
    assert _rank(client, ids["甲"]) < rank_ding, "丁 的号要排在甲后面（相对判据，不钉具体值）"
    assert len(_changed(before, after)) < len(before), "不许整表归一化（每行都写一遍）"


# ---------------------------------------------------------------- ③ 值没变就不写
def test_a_real_drag_does_not_bump_rows_it_did_not_change(tmp_path: Path) -> None:
    """一次真拖里，**号没变、位置也没变**的行不许被 `UPDATE`（`version` 不许白涨）。

    先拖一次让整列都有号，再把「丁」拖到「乙」前面 —— 「戊」「甲」的号与位置都没变，
    它们应当**一个字节都没动**（这正是 T-G79 那版每个空写都犯的毛病）。
    """
    client = _client(tmp_path)
    ids = _five(client)
    path = tmp_path / "myday.db"
    assert client.post(f"/api/tasks/{ids['戊']}/myday-move",
                       json={"before": ids["甲"]}).status_code == 200   # 戊 到最前 → 全列有号

    before = _snapshot(path)
    assert client.post(f"/api/tasks/{ids['丁']}/myday-move",
                       json={"before": ids["乙"]}).status_code == 200
    after = _snapshot(path)

    assert _order(client) == ["戊", "甲", "丁", "乙", "丙"]
    for title in ("戊", "甲"):
        assert before[ids[title]] == after[ids[title]], \
            f"「{title}」的号与位置都没变，却把它写了（version 白涨）"
    assert _rank(client, ids["甲"]) < _rank(client, ids["丁"]) < _rank(client, ids["乙"]), \
        "丁 的号要落在甲与乙之间（稀疏取号的本质，相对判据）"


# ---------------------------------------------------------------- 幂等的另两种走法
def test_repeating_the_same_drag_is_a_noop(tmp_path: Path) -> None:
    """拖过一次之后，再用同一个落点拖一次 → 顺序没变 → **一行都不许写**。"""
    client = _client(tmp_path)
    ids = _five(client)
    path = tmp_path / "myday.db"
    assert client.post(f"/api/tasks/{ids['甲']}/myday-move",
                       json={"before": None}).status_code == 200   # 甲 → 末尾（真的换了位置）

    before = _snapshot(path)
    assert client.post(f"/api/tasks/{ids['甲']}/myday-move",
                       json={"before": None}).status_code == 200   # 再拖同一个落点
    after = _snapshot(path)

    assert _changed(before, after) == set(), "落点相同、顺序没变 → 不许写"


def test_a_noop_does_not_poison_the_connection(tmp_path: Path) -> None:
    """空转之后还得能读（T-G79 那条 `database is locked` 的回归守卫）。

    原来的写法在空转里写完整表再早退 —— 只要有一处漏了提交，下一个读就炸；
    修好之后空转**根本不写**，这条路径自然干净。
    """
    client = _client(tmp_path)
    for t in ("甲", "乙", "丙"):
        _add(client, t)
    for tid in _by_title(client).values():
        assert client.post(f"/api/tasks/{tid}/myday-move",
                           json={"before": tid}).status_code == 200
    assert _order(client) == ["甲", "乙", "丙"]
