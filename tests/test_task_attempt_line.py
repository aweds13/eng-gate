"""F 批 · T-F3：「尝试失败」显式计次（N11 的"过去做过的尝试"）。

**口径（用户 2026-09-21 定，`复盘/口径定案-待定清单.md` §1）**：
- **只认显式点击**「尝试失败」—— 不自动从"推到明天/取消"推断（原话的"数字要可信"）；
- 事实 `task.attempt.failed`：一次点击一条（同一天失败两次就是两条）；
- 可带**一句可选说明**（"试到哪儿了"），将来进 md 存档；
- 详情显示「试了 N 回」；失败之后给三选：**取消 / 待定 / 推到明天**（这三个各自的动作
  已经在 T-F1/T-F2 里落过，本卡只负责把它们接在失败之后）。

覆盖：
- 计数口径：0 次 / 多次 / 说明只收有字的那几次（新的在前）；
- **不改状态、不动账本**（失败 ≠ 完成 ≠ 取消：它是"我试过"的记录，不是"事情变了"）；
- 边界：完成 / 待定 / 取消 / 归档 / 已删 → 拒绝（这些任务不在"手上"）；
- 「只认显式点击」：别的动作（推到明天 / 取消 / 完成）**不会**让计数上涨；
- API：`GET .../attempts` 与 `POST .../attempt-failed` 的读写与 404/400。
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import facts as facts_mod
from timeflow.core import tasks as tm
from timeflow.core.ledger import ledger
from timeflow.storage import db as db_mod


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "attempt.db"))
    facts_mod.clear()
    yield c
    c.close()
    facts_mod.clear()


def _client(tmp_path, name: str = "attempt_api.db") -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(create_app(str(tmp_path / name)))


# ---------------------------------------------------------------- 计数口径


def test_first_attempt_starts_at_one(conn) -> None:  # type: ignore[no-untyped-def]
    """没试过 = 0；点一次 = 1（不是"从 0 开始数事件"那种含糊口径）。"""
    task = tm.create_task(conn, "写论文")
    assert tm.attempt_count(conn, task.id) == 0
    tm.attempt_failed(conn, task.id)
    assert tm.attempt_count(conn, task.id) == 1


def test_each_click_is_one_attempt(conn) -> None:  # type: ignore[no-untyped-def]
    """一次点击一条：同一天失败三次就是三条（如实计数，不做"一天合并成一次"）。"""
    task = tm.create_task(conn, "调那个 bug")
    for _ in range(3):
        tm.attempt_failed(conn, task.id)
    assert tm.attempt_count(conn, task.id) == 3
    assert len(facts_mod.query(conn, kind=tm.ATTEMPT_FAILED, subject_id=task.id)) == 3


def test_notes_keep_only_written_ones_newest_first(conn) -> None:  # type: ignore[no-untyped-def]
    """说明只收"有字的"那几次（空说明不占一行），且**新的在前**。"""
    task = tm.create_task(conn, "推公式")
    tm.attempt_failed(conn, task.id, "先试了代入法")
    tm.attempt_failed(conn, task.id)  # 这次没写说明
    tm.attempt_failed(conn, task.id, "   ")  # 只有空白 ≈ 没写
    tm.attempt_failed(conn, task.id, "换成积分因子")

    assert tm.attempt_count(conn, task.id) == 4  # 计数如实算四次
    assert tm.attempt_notes(conn, task.id) == ["换成积分因子", "先试了代入法"]
    assert tm.attempt_notes(conn, task.id, limit=1) == ["换成积分因子"]


def test_notes_and_count_are_per_task(conn) -> None:  # type: ignore[no-untyped-def]
    """计到各自任务头上：别的任务试过多少回，与这个任务无关。"""
    a = tm.create_task(conn, "甲")
    b = tm.create_task(conn, "乙")
    tm.attempt_failed(conn, a.id, "甲的说明")
    tm.attempt_failed(conn, b.id)
    tm.attempt_failed(conn, b.id)

    assert tm.attempt_count(conn, a.id) == 1
    assert tm.attempt_count(conn, b.id) == 2
    assert tm.attempt_notes(conn, a.id) == ["甲的说明"]
    assert tm.attempt_notes(conn, b.id) == []


# ---------------------------------------------------------------- 它**不改**什么


def test_attempt_failed_does_not_change_status_or_ledger(conn) -> None:  # type: ignore[no-untyped-def]
    """「尝试失败」不是状态变化、也不是完成：状态照旧、账本一分不动。

    为什么专门钉这条：失败之后要做什么是**用户下一步的选择**（取消/待定/推到明天），
    这个动作只负责把"试过、没成"记下来 —— 如果它顺手改了状态，那三选就成了摆设。
    """
    task = tm.create_task(conn, "试了没成的事", due_date="2020-01-01")
    before = tm.get_task(conn, task.id)
    is_overdue_before = tm.overdue_days(before)
    debt_before = ledger.summary(conn).debt_count

    tm.attempt_failed(conn, task.id, "试了一下午")

    after = tm.get_task(conn, task.id)
    assert after.status == before.status
    assert after.due_date == before.due_date
    assert after.is_myday == before.is_myday
    assert tm.overdue_days(after) == is_overdue_before
    assert ledger.summary(conn).debt_count == debt_before
    assert ledger.summary(conn).gain_count == 0  # 失败不是收益
    # 也没顺手记"状态改了" —— 只留那一条失败事实
    assert [f["kind"] for f in facts_mod.query(conn, subject_id=task.id)] == [tm.ATTEMPT_FAILED]


def test_other_actions_do_not_bump_attempt_count(conn) -> None:  # type: ignore[no-untyped-def]
    """**只认显式点击**：推到明天 / 取消 / 待定 / 完成 都不会让「试了 N 回」上涨。

    这是本卡的核心口径（用户："数字要可信"）—— 一旦让别的动作推断它，
    记的就成了我的猜测。
    """
    task = tm.create_task(conn, "拖着的活", due_date="2020-01-01")
    tm.update_task(conn, task.id, due_date=date.today().isoformat())  # ≈推到明天
    tm.park_task(conn, task.id)  # ≈待定
    tm.un_park_task(conn, task.id)
    tm.cancel_task(conn, task.id)  # ≈取消
    assert tm.attempt_count(conn, task.id) == 0

    other = tm.create_task(conn, "做完了的")
    tm.complete_task(conn, other.id)
    assert tm.attempt_count(conn, other.id) == 0


# ---------------------------------------------------------------- 边界


def test_attempt_failed_rejects_closed_tasks(conn) -> None:  # type: ignore[no-untyped-def]
    """完成 / 搁置（待定·取消）/ 归档 / 已删 → 拒绝：这些任务已不在"手上"，记失败没有意义。"""
    done = tm.create_task(conn, "完成的")
    tm.complete_task(conn, done.id)
    with pytest.raises(ValueError):
        tm.attempt_failed(conn, done.id)

    pending = tm.create_task(conn, "待定的")
    tm.park_task(conn, pending.id)
    with pytest.raises(ValueError):
        tm.attempt_failed(conn, pending.id)

    cancelled = tm.create_task(conn, "取消的")
    tm.cancel_task(conn, cancelled.id)
    with pytest.raises(ValueError):
        tm.attempt_failed(conn, cancelled.id)

    archived = tm.create_task(conn, "归档的")
    tm.archive_task(conn, archived.id)
    with pytest.raises(ValueError):
        tm.attempt_failed(conn, archived.id)

    gone = tm.create_task(conn, "删掉的")
    tm.delete_task(conn, gone.id)
    with pytest.raises(ValueError):
        tm.attempt_failed(conn, gone.id)


def test_attempt_failed_on_missing_task_raises_keyerror(conn) -> None:  # type: ignore[no-untyped-def]
    """任务不存在 → KeyError（接口层翻成 404，不静默记一条挂在空气上的失败）。"""
    with pytest.raises(KeyError):
        tm.attempt_failed(conn, "没有这个 id")


# ---------------------------------------------------------------- API


def test_api_attempts_read_and_write(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """`POST .../attempt-failed` 记一次并回读 `{task, count, notes}`；`GET .../attempts` 同源。"""
    client = _client(tmp_path)
    task = client.post("/api/tasks", json={"title": "面试准备"}).json()

    assert client.get(f"/api/tasks/{task['id']}/attempts").json() == {"count": 0, "notes": []}

    first = client.post(f"/api/tasks/{task['id']}/attempt-failed",
                        json={"note": "简历没写完"}).json()
    assert first["count"] == 1
    assert first["notes"] == ["简历没写完"]
    assert first["task"]["status"] == "未开始"  # 接口也不改状态

    second = client.post(f"/api/tasks/{task['id']}/attempt-failed", json={}).json()
    assert second["count"] == 2
    assert second["notes"] == ["简历没写完"]  # 没写说明的那次不占一行
    assert client.get(f"/api/tasks/{task['id']}/attempts").json()["count"] == 2

    # 失败之后的三选各自都是**已有的**动作（本卡不新增状态跃迁）
    assert client.post(f"/api/tasks/{task['id']}/park").json()["status"] == "待定"
    assert client.post(f"/api/tasks/{task['id']}/attempt-failed").status_code == 400  # 搁置后不能记


def test_api_attempts_404_and_400(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """不存在 → 404；已完成 → 400（两条路都不静默）。"""
    client = _client(tmp_path)
    assert client.get("/api/tasks/nope/attempts").status_code == 404
    assert client.post("/api/tasks/nope/attempt-failed", json={}).status_code == 404

    task = client.post("/api/tasks", json={"title": "做完了"}).json()
    client.post(f"/api/tasks/{task['id']}/complete")
    r = client.post(f"/api/tasks/{task['id']}/attempt-failed", json={"note": "其实试过"})
    assert r.status_code == 400
    assert "撤销完成" in r.json()["detail"]
