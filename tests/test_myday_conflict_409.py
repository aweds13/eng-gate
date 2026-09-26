"""卡 035（T-G126）· `MydayConflictError` 经 HTTP 要显 **409**（原为 500）。

## 背景（出处）

T-G109 给 myday 排序焊上乐观锁：「重试一次仍撞」原样抛 `MydayConflictError`
（`src/timeflow/core/tasks/manager.py` 的 `place_myday` / `move_myday`）——但接口层
`POST /api/tasks/{task_id}/myday-move` 的 except 链只接了 `KeyError`（404）与
`ValueError`（400），这条 `RuntimeError` 无人接 → 经 HTTP 显 **500** +
`Internal Server Error`（卡 035 探针实测，见 `复盘/myday撞击409映射-T-G126.md`）。
core 的 docstring（manager.py「报 409 的载体」）与本卡口径都是 **409 + 人话**。

## 装置（确定性，不靠真并发碰运气）

`monkeypatch` 把 `manager._write_myday_rank`（乐观锁咬中的那一行 UPDATE）换成
「每次调用都抛真异常 `MydayConflictError`」的桩 —— 第一次撞 + 重试一次仍撞，
正是 T-G109 口径里「重试一次仍撞原样抛出」的那条路；真并发交错的复现装置在
`tests/test_myday_version_guard_line.py`（屏障法），本文件只关心 **HTTP 面**。

★ 本文件只**新增**用例、不改任何既有断言（022 在另一棵树里改 myday 的域）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core.tasks import manager

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _client(tmp_path: Path) -> TestClient:
    # raise_server_exceptions=False：让「没人接的异常」真以响应形式出来（500），
    # 而不是把异常直接抛进测试 —— 否则钉不住「显成什么状态码」。
    return TestClient(
        create_app(str(tmp_path / "myday.db")), raise_server_exceptions=False
    )


def _add(client: TestClient, title: str) -> str:
    resp = client.post("/api/tasks", json={"title": title, "is_myday": True})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["id"])


def _order(client: TestClient) -> list[str]:
    return [t["title"] for t in client.get("/api/mydays").json()]


def _conflict_every_write(monkeypatch: pytest.MonkeyPatch) -> None:
    """桩：`_write_myday_rank` 每次调用都撞 —— 第 1 次 = 初写撞，第 2 次 = 重试仍撞。"""

    def always_conflict(
        conn: object, task_id: str, rank: int, expected_version: int
    ) -> None:
        raise manager.MydayConflictError(
            f"myday 排序撞上并发更新：写 {task_id} 时快照 version={expected_version}，"
            f"库里已是 999 —— 这次拖拽建立在过期快照上（用例注入：每次写都撞）"
        )

    monkeypatch.setattr(manager, "_write_myday_rank", always_conflict)


# ------------------------------------------------------------------ ★ 本卡核心
def test_myday_conflict_surfaces_as_409_with_readable_detail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """撞车（重试一次仍撞）→ **409** + detail 是能看懂的人话；顺序一个都不动。"""
    client = _client(tmp_path)
    for t in ("甲", "乙", "丙"):
        _add(client, t)
    ids = [t["id"] for t in client.get("/api/mydays").json()]

    _conflict_every_write(monkeypatch)
    resp = client.post(f"/api/tasks/{ids[2]}/myday-move", json={"before": ids[0]})

    assert resp.status_code == 409, resp.text          # 改前这条红：500
    detail = str(resp.json().get("detail") or "")
    assert "并发" in detail, detail                    # body 要说人话（不是 Internal Server Error）
    # 乐观锁已整笔回滚 + 接口层拒绝 → 顺序一个都没动
    assert _order(client) == ["甲", "乙", "丙"]


# ------------------------------------------------------------------ 邻居不被误伤
def test_404_and_400_of_myday_move_are_unchanged(tmp_path: Path) -> None:
    """新加的 except 不许把既有分支吞掉：任务不存在 → 404、入参非法 → 400 照旧。"""
    client = _client(tmp_path)
    for t in ("甲", "乙"):
        _add(client, t)
    first = client.get("/api/mydays").json()[0]["id"]
    assert (
        client.post("/api/tasks/tf-nope/myday-move", json={"before": None}).status_code
        == 404
    )
    assert client.post(f"/api/tasks/{first}/myday-move", json={}).status_code == 400
    assert (
        client.post(
            f"/api/tasks/{first}/myday-move",
            json={"direction": "up", "before": None},
        ).status_code
        == 400
    )
    assert _order(client) == ["甲", "乙"]
