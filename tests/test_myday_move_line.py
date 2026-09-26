"""T-G102 · `myday-move` 的「空 `before`」口径：空串（`""`）→ 400，不再静默当末尾。

## 背景（为什么单开一个文件）

同一个形状（"给了键但没给值"）原来有**两种答案**：复盘「拖拽排序-T-G79.md」写「两个键
要么给一个、要么不给（**都给空 → 400**）」，而 `POST /api/tasks/{task_id}/myday-move` 的实现
把 `{"before": ""}` 与 `{"before": null}` **一把抓**（`raw in (None, "")`）→ 空串被静默当
"末尾"、回 200。复核报告「边界 E」（`gates/diag/wb-review-T-G79.md`）复现了这条不一致。

主控裁定（卡 015 §2.9①）**先用证据定方向**：查界面与现有调用方**有没有真的发 `before=""`**——
`src/web/index.html:2037` 把落点设成 `target ? target.dataset.mydayId : null`（真 id 或 `null`，
**从不发空串**），现有测试也只传真 id 或 `None`。**没有人在用"空 = 末尾"** → **改代码对齐契约**。

## 这一批用例在防什么

① ★ **空串 → 400**（不再静默当末尾）：`{"before": ""}` 必须被拒，且**顺序一个都不动**；
② ★ **别把 `null` 一起改坏**：`{"before": null}` 仍是合法值 = **末尾**（契约点名）；
③ **别的形状照旧**：`{}` → 400、`{"direction": "up"}` 正常、真 id 落点正常 —— 本卡只碰空串那一支。

★ 先红后绿：改实现**之前**本文件第 ① 条就是红的（`""` 回 200），改后转绿（见复盘 §真机证据）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from timeflow.api.app import create_app

if TYPE_CHECKING:
    from pathlib import Path


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(str(tmp_path / "myday.db")))


def _add(client: TestClient, title: str) -> str:
    resp = client.post("/api/tasks", json={"title": title, "is_myday": True})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["id"])


def _order(client: TestClient) -> list[str]:
    return [t["title"] for t in client.get("/api/mydays").json()]


def test_empty_before_is_rejected_not_silently_treated_as_end(tmp_path: Path) -> None:
    """★ 本卡的核心：`{"before": ""}` → 400，且**不挪动**（不许静默当末尾）。"""
    client = _client(tmp_path)
    for t in ("甲", "乙", "丙"):
        _add(client, t)
    first = client.get("/api/mydays").json()[0]["id"]  # 甲
    resp = client.post(f"/api/tasks/{first}/myday-move", json={"before": ""})
    assert resp.status_code == 400, resp.text
    # 被拒之后顺序一个都没动（改前这条会红：空串被当末尾 → ["乙","丙","甲"]）
    assert _order(client) == ["甲", "乙", "丙"]


def test_null_before_still_means_end(tmp_path: Path) -> None:
    """★ 别把 `null` 一起改坏：`{"before": null}` 仍 → 200 且落到**末尾**。"""
    client = _client(tmp_path)
    for t in ("甲", "乙", "丙"):
        _add(client, t)
    first = client.get("/api/mydays").json()[0]["id"]  # 甲
    assert client.post(f"/api/tasks/{first}/myday-move",
                       json={"before": None}).status_code == 200
    assert _order(client) == ["乙", "丙", "甲"]


def test_other_shapes_are_unchanged(tmp_path: Path) -> None:
    """`{}` → 400、`{"direction": "up"}` 正常、真 id 落点正常 —— 只碰空串那一支。"""
    client = _client(tmp_path)
    for t in ("甲", "乙", "丙"):
        _add(client, t)
    order = client.get("/api/mydays").json()
    first, last = order[0]["id"], order[-1]["id"]  # 甲 / 丙
    assert client.post(f"/api/tasks/{first}/myday-move", json={}).status_code == 400
    # direction 那条路照常（丙 上移一位）
    assert client.post(f"/api/tasks/{last}/myday-move",
                       json={"direction": "up"}).status_code == 200
    assert _order(client) == ["甲", "丙", "乙"]
    # 真 id 落点照常（丙 拖到 甲 前面）
    assert client.post(f"/api/tasks/{last}/myday-move",
                       json={"before": first}).status_code == 200
    assert _order(client) == ["丙", "甲", "乙"]
