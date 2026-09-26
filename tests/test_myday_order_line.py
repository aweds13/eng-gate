"""T-G79 · 今天清单（My Day）的**自定义顺序**：拖拽落点 + 键盘 ↑↓ 两条路。

## 口径（用户 2026-09-25 在两张预演图上选了 **B 真拖拽**）

- 拖过的按**拖的顺序**（`myday_rank` 小的在前）；**没拖过的排在后面**，它们之间仍按统一口径
  （截止日 → 优先级 → 创建时间）—— 也就是"新加进今天的排在后面"，不猜；
- ★ **2026-09-26（T-G86）**：拖一次**不再把整份清单都写号** —— 只给"真的换了位置"的行写号，
  没动过的仍保持 `NULL`（"不许把没拖过的冻结成序号"）。所以"拖过一次 → 全都有号"这句已作废
  （那是 T-G79 那句错话的根因，见 `复盘/幂等写库-T-G86.md`）。幂等动作（拖到自己前面、
  已在头/尾按 ↑↓）现在**一行都不写库**；
- **只有「在今天」的任务才有序号**：移出今天一律清成 NULL（不留幽灵序号）；
- 序号由领域层维护，**不进 PATCH 白名单**（不是内容字段，不给人手改）；
- 落点是"**放到谁前面**"（`before`），不是"第几格"：隐藏/新增条目都不会让落点错位；
  两个键都给、或都不给 → **400 说清楚**（不静默挑一个执行）。

## 这一批用例在防什么

① **顺序真的变了、而且落库**（刷新/重开还是那个顺序 —— 这是"真拖拽"与"前端自己排一排"的分界）；
② **反证**：拖到自己前面不动、划到边界不动（幂等，不报错）、落点不在今天 → **400 而不是静默**；
③ **不污染**：移出今天清序号、别的视图排序口径一个字没变（`_MYDAY_ORDER_BY` 只加前缀）；
④ **旧库**：v18 升 v19 只加一列，老行全 NULL（不猜顺序）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import tasks as tm
from timeflow.storage import db as db_mod

if TYPE_CHECKING:
    from pathlib import Path


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(str(tmp_path / "myday.db")))


def _add(client: TestClient, title: str, *, myday: bool = True, due: str | None = None) -> str:
    body: dict[str, object] = {"title": title, "is_myday": myday}
    if due:
        body["due_date"] = due
    resp = client.post("/api/tasks", json=body)
    assert resp.status_code == 200, resp.text
    return str(resp.json()["id"])


def _order(client: TestClient) -> list[str]:
    return [t["title"] for t in client.get("/api/mydays").json()]


# ------------------------------------------------------------------ 拖动：放到谁前面
def test_drag_puts_a_task_before_the_target_and_persists(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for t in ("甲", "乙", "丙", "丁"):
        _add(client, t)
    assert _order(client) == ["甲", "乙", "丙", "丁"]

    # 把「丁」拖到「甲」前面
    first = client.get("/api/mydays").json()[0]["id"]
    last = client.get("/api/mydays").json()[-1]["id"]
    moved = client.post(f"/api/tasks/{last}/myday-move", json={"before": first})
    assert moved.status_code == 200, moved.text
    assert moved.json()["myday_rank"] == 1, "拖到最前面 → 序号 1"
    assert _order(client) == ["丁", "甲", "乙", "丙"]

    # ★ 落库了：**新开一个客户端**（同一份库）读出来还是这个顺序
    again = TestClient(create_app(str(tmp_path / "myday.db")))
    assert [t["title"] for t in again.get("/api/mydays").json()] == ["丁", "甲", "乙", "丙"]


def test_drag_to_the_end_with_explicit_null(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for t in ("甲", "乙", "丙"):
        _add(client, t)
    first = client.get("/api/mydays").json()[0]["id"]
    assert client.post(f"/api/tasks/{first}/myday-move", json={"before": None}).status_code == 200
    assert _order(client) == ["乙", "丙", "甲"]


def test_drag_onto_itself_and_off_the_edge_are_noops(tmp_path: Path) -> None:
    """反证：拖到自己前面、或落在边界外 —— **不许报错、也不许改顺序**。"""
    client = _client(tmp_path)
    for t in ("甲", "乙", "丙"):
        _add(client, t)
    mid = client.get("/api/mydays").json()[1]["id"]
    assert client.post(f"/api/tasks/{mid}/myday-move", json={"before": mid}).status_code == 200
    assert _order(client) == ["甲", "乙", "丙"], "拖到自己前面 = 原地不动"

    first = client.get("/api/mydays").json()[0]["id"]
    assert client.post(f"/api/tasks/{first}/myday-move",
                       json={"direction": "up"}).status_code == 200
    assert _order(client) == ["甲", "乙", "丙"], "已经在头上再往上 = 不动"


def test_drag_target_must_be_in_today(tmp_path: Path) -> None:
    """反证：落点不在今天清单里 → **400 说清原因**（静默忽略会让人以为"拖了没反应"）。"""
    client = _client(tmp_path)
    inside = _add(client, "今天的")
    outside = _add(client, "不在今天的", myday=False)
    resp = client.post(f"/api/tasks/{inside}/myday-move", json={"before": outside})
    assert resp.status_code == 400, resp.text
    assert "落点不在" in resp.json()["detail"]
    # 任务本身不在今天时同样拒绝（不是"悄悄把它加进今天"）
    resp2 = client.post(f"/api/tasks/{outside}/myday-move", json={"before": inside})
    assert resp2.status_code == 400 and "今天" in resp2.json()["detail"]
    # ★ 被拒之后**库里还是能读**（T-G79 实测踩到：某一版把规整序号的写留在未提交的事务里，
    #   于是下一条读直接 `database is locked` —— 这条断言就是那次回归的守卫）
    assert _order(client) == ["今天的"]


def test_move_endpoint_validates_the_shape(tmp_path: Path) -> None:
    """两个键都给 / 都不给 / 方向非法 / 任务不存在 —— 各回各的码，不静默。"""
    client = _client(tmp_path)
    tid = _add(client, "甲")
    assert client.post(f"/api/tasks/{tid}/myday-move", json={}).status_code == 400
    assert client.post(f"/api/tasks/{tid}/myday-move",
                       json={"before": tid, "direction": "up"}).status_code == 400
    assert client.post(f"/api/tasks/{tid}/myday-move",
                       json={"direction": "sideways"}).status_code == 400
    assert client.post("/api/tasks/nope/myday-move", json={"direction": "up"}).status_code == 404
    # ★ 四条错误路径走完，连接上不许留下没提交的写（否则后面每条请求都 locked）
    assert _order(client) == ["甲"]


# ------------------------------------------------------------------ 键盘那条路
def test_keyboard_up_down_shares_the_same_order(tmp_path: Path) -> None:
    """↑↓ 与拖拽落到**同一份序号**上：先拖、再按 ↓，仍然对得上。"""
    client = _client(tmp_path)
    for t in ("甲", "乙", "丙"):
        _add(client, t)
    first = client.get("/api/mydays").json()[0]["id"]      # 甲
    last = client.get("/api/mydays").json()[-1]["id"]      # 丙
    client.post(f"/api/tasks/{last}/myday-move", json={"before": first})   # 把丙拖到最前
    assert _order(client) == ["丙", "甲", "乙"]
    client.post(f"/api/tasks/{last}/myday-move", json={"direction": "down"})   # 再按 ↓
    assert _order(client) == ["甲", "丙", "乙"], "↓ = 与下一条换位置"


# ------------------------------------------------------------------ 不污染 / 不留幽灵
def test_leaving_today_clears_the_rank_and_coming_back_goes_last(tmp_path: Path) -> None:
    """移出今天 → 序号清掉；再加回来 → **排在末尾**（不带着旧号插回原位置）。

    ★ 2026-09-26（T-G86）改过这条的**走法**（结论不变）：原来靠"拖一次 → 整份清单都写号"
    来制造"丙 有号"，而那正是被修掉的整表归一化。现在改成**让那一条真的换位置**（丙 拖到最前
    → 丙 拿到号 1，甲/乙 仍是 NULL），再把它移出/加回 —— 它加回来是 NULL（没排过号），
    按口径排在"排过号的那一截"后面 = 列表最后一条（这里那一截已经空了，于是落到老口径的末尾）。
    """
    client = _client(tmp_path)
    for t in ("甲", "乙", "丙"):
        _add(client, t)
    ids = client.get("/api/mydays").json()
    first, last = ids[0]["id"], ids[-1]["id"]              # 甲 / 丙
    client.post(f"/api/tasks/{last}/myday-move", json={"before": first})   # 丙 拖到最前（真换位置）
    assert _order(client) == ["丙", "甲", "乙"], "丙 拖到甲前面"
    assert client.get(f"/api/tasks/{last}").json()["myday_rank"] == 1, "真换了位置才有号"

    assert client.post(f"/api/tasks/{last}/myday").json()["myday_rank"] is None, \
        "移出今天要清成 NULL（不留幽灵序号）"
    client.post(f"/api/tasks/{last}/myday")               # 再加回来
    assert _order(client) == ["甲", "乙", "丙"], "加回来排在末尾（不插回原来那个位置）"


def test_untouched_tasks_keep_the_old_order(tmp_path: Path) -> None:
    """★ 没拖过的时候，顺序**一个字没变**（还是截止日 → 优先级 → 创建时间）。"""
    client = _client(tmp_path)
    _add(client, "没截止日")
    _add(client, "明天到期", due="2099-01-01")
    _add(client, "今天到期", due="2020-01-01")   # 已逾期也算有截止日 → 排前面
    assert _order(client) == ["今天到期", "明天到期", "没截止日"]
    # 拖过之后：拖过的那条在最前，其余仍按老口径
    last = client.get("/api/mydays").json()[-1]["id"]
    client.post(f"/api/tasks/{last}/myday-move", json={"before": None})
    # （已经在末尾，顺序不变）
    assert _order(client) == ["今天到期", "明天到期", "没截止日"]


def test_myday_rank_is_not_writable_by_patch(tmp_path: Path) -> None:
    """序号是领域层的东西：PATCH 传它 **不许生效**（与 `doing_rank` 同一条规矩）。"""
    client = _client(tmp_path)
    tid = _add(client, "甲")
    before = client.get(f"/api/tasks/{tid}").json()["myday_rank"]
    patched = client.patch(f"/api/tasks/{tid}", json={"myday_rank": 99})
    assert patched.status_code == 200
    assert patched.json()["myday_rank"] == before, "PATCH 不该能改序号"


def test_other_views_keep_the_shared_order(tmp_path: Path) -> None:
    """别的视图（全部任务 / 逾期）**不受这张卡影响**：口径仍是那一份。"""
    client = _client(tmp_path)
    _add(client, "b", due="2030-01-02")
    _add(client, "a", due="2030-01-01")
    assert [t["title"] for t in client.get("/api/tasks").json()][:2] == ["a", "b"]
    dragged = client.get("/api/mydays").json()[-1]["id"]
    client.post(f"/api/tasks/{dragged}/myday-move", json={"before": None})
    assert [t["title"] for t in client.get("/api/tasks").json()][:2] == ["a", "b"], \
        "拖今天清单不许把「全部任务」的排序也带跑"


# ------------------------------------------------------------------ 旧库
def test_upgrade_v18_adds_myday_rank_without_guessing(tmp_path: Path) -> None:
    """v18 → v19：把列**真的拿掉**再升一次 —— 补回来、老行全 NULL（不猜顺序）。"""
    path = tmp_path / "old.db"
    conn = db_mod.connect(str(path))
    conn.execute("ALTER TABLE tasks DROP COLUMN myday_rank")   # 造一个"v18 形状"的表
    conn.execute("UPDATE schema_version SET version = 18")
    conn.execute(
        "INSERT INTO tasks (id, title, due_date, is_myday, status, created_at, updated_at, version)"
        " VALUES ('old1', '老任务', NULL, 1, '未开始', '2020-01-01T00:00:00',"
        " '2020-01-01T00:00:00', 1)"
    )
    conn.commit()
    conn.close()

    conn2 = db_mod.connect(str(path))
    cols = {r["name"] for r in conn2.execute("PRAGMA table_info(tasks)").fetchall()}
    assert "myday_rank" in cols, "升上来要补回这一列（结构补齐那条路）"
    row = conn2.execute("SELECT myday_rank FROM tasks WHERE id = 'old1'").fetchone()
    assert row["myday_rank"] is None, "老行不许被猜一个顺序"
    assert db_mod.SCHEMA_VERSION == 19
    conn2.close()


def test_manager_rejects_a_target_that_is_not_visible(tmp_path: Path) -> None:
    """领域层那道校验也要在（API 之外直接调时同样不许静默）。"""
    client = _client(tmp_path)
    tid = _add(client, "甲")
    client.close()
    conn = db_mod.connect(str(tmp_path / "myday.db"))
    with pytest.raises(ValueError):
        tm.place_myday(conn, tid, "不存在的 id")
    conn.close()
