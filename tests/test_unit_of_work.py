"""跨函数事务（T-G71，收的是 T-G33 那条残留）—— 「一起成功或一起撤」的机器判据。

背景：`POST /api/tasks` 先 `tm.create_task()`（自己 commit）、再 `tm.set_task_groups()`
（又自己 commit）。中间那一步出**数据库级**错误时，任务已经落库 —— 客户端看到报错、
库里却多一条，重试就多两条。T-G33 只把"坏分组"这类**输入错**先验掉了，
"验完之后再出数据库级错误"那半句记成了残留，本卡用 `db.unit_of_work()` 收口。

四层判据：
1. **机制层**：`unit_of_work` 里 `commit()` 真的被推迟（另一条连接看不到），退出才落库；
2. **回滚层**：段里抛异常 → 整段撤掉；嵌套 → 只提交一次；
3. **接口层**：让第二条 core 调用**真的**抛数据库错 → 接口 500 而且**库里什么都没留下**
   （并用"第一条调用确实跑过"证明这不是"什么都没发生"）；
4. **清单层**：扫 `app.py`，把"一个处理函数里调了 ≥2 个会自己 commit 的 core 函数"的
   找出来，逐个要求**要么包在 `unit_of_work` 里、要么在带理由的豁免清单上** ——
   以后新写一个这样的处理函数会被这条拦住。
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent

from timeflow import clock  # noqa: E402
from timeflow.api.app import create_app  # noqa: E402
from timeflow.core import memo as memo  # noqa: E402
from timeflow.core import tasks as tm  # noqa: E402
from timeflow.storage import db  # noqa: E402

APP = ROOT / "src" / "timeflow" / "api" / "app.py"


@pytest.fixture(autouse=True)
def _pinned_day(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIMEFLOW_FAKE_TODAY", "2026-06-15")

#: 允许"两条 core 调用不包在同一个事务里"的处理函数 —— **每条都要写清为什么**。
#: 现在的三条都是同一类：第二笔是**导出一份 md**（派生文件，T-G4 起就吞错、不挡主流程），
#: 它不是第二笔**权威**写入，而且顺序上必须在提交**之后**（先写库、再落 md）。
EXEMPT_MULTI_WRITE = {
    "create_memo": "memo.create_memo 是唯一权威写入；vault.try_export 是派生 md，必须在提交之后",
    "delete_memo": "同上（删完再导出一份）",
    "ledger_output": "同上（记一笔产出，再导出一份）",
}


def _proxy(tmp_path: Path) -> object:
    """HTTP 那条路的连接代理（`unit_of_work` 只支持它）。"""
    return db.thread_local(str(tmp_path / "uow.db"))


def _texts(conn: object) -> list[str]:
    return [str(row["text"]) for row in conn.execute("SELECT text FROM memos ORDER BY text")]


def _outside_texts(path: Path) -> list[str]:
    """**另一条连接**看到的 —— 真提交了才看得见（这就是"提没提交"的判据）。"""
    other = sqlite3.connect(path)
    other.row_factory = sqlite3.Row
    try:
        return [str(row["text"]) for row in other.execute("SELECT text FROM memos ORDER BY text")]
    finally:
        other.close()


# ------------------------------------------------------------------ 1. 机制层


def test_commit_inside_the_unit_is_deferred_until_the_exit(tmp_path: Path) -> None:
    """★ 核心判据：段里的 `commit()` 只是记账，**退出那一刻**才真落库。"""
    path = tmp_path / "uow.db"
    conn = db.thread_local(str(path))
    with db.unit_of_work(conn, what="测试"):
        memo.create_memo(conn, text="段内写的")
        assert _texts(conn) == ["段内写的"], "同一条连接当然看得见自己没提交的写"
        assert _outside_texts(path) == [], "★ 还没提交：另一条连接不该看得见"
    assert _outside_texts(path) == ["段内写的"], "退出之后必须真落库"


def test_a_failure_rolls_the_whole_unit_back(tmp_path: Path) -> None:
    """段里抛异常 → 整段撤掉（连同之前那些已经"commit 过"的写）。"""
    path = tmp_path / "uow.db"
    conn = db.thread_local(str(path))

    class _BoomError(RuntimeError):
        pass

    with pytest.raises(_BoomError), db.unit_of_work(conn, what="测试"):
        memo.create_memo(conn, text="第一条")
        memo.create_memo(conn, text="第二条")
        raise _BoomError
    assert _outside_texts(path) == []
    assert _texts(conn) == []


def test_nested_units_commit_once(tmp_path: Path) -> None:
    """嵌套：内层退出**不**提交，外层退出才提交（否则内层会把外层撕开）。"""
    path = tmp_path / "uow.db"
    conn = db.thread_local(str(path))
    with db.unit_of_work(conn, what="外层"):
        memo.create_memo(conn, text="外")
        with db.unit_of_work(conn, what="内层"):
            memo.create_memo(conn, text="内")
        assert _outside_texts(path) == [], "内层退出不该提交"
    assert _outside_texts(path) == ["内", "外"]


def test_the_deferral_marker_is_per_thread(tmp_path: Path) -> None:
    """★ 延迟标记必须跟着**连接**走：一个线程进事务，不许把别的线程的提交也扣下。

    这是并发那组用例抓到的**真缺陷**的最小复现：`_ThreadLocalConn` 是**全进程一个**、
    被所有线程共用；标记若挂在实例上，线程 A 进事务后线程 B 的 `commit()` 也被记成"推迟"，
    而 A 退出时提交的是 **A 自己的连接** —— B 那笔写于是**永远没人提交**（别的连接看不见，
    写锁还一直攥着，并发下报 `database is locked`）。
    """
    import threading

    path = tmp_path / "threads.db"
    proxy = db.thread_local(str(path))
    proxy.execute("SELECT 1").fetchone()  # 先把库建出来
    inside = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def holder() -> None:
        try:
            with db.unit_of_work(proxy, what="A 线程"):
                inside.set()
                assert release.wait(timeout=10)
                memo.create_memo(proxy, text="A 的")
        except BaseException as exc:  # noqa: BLE001 —— 线程里的异常要带回主线程
            errors.append(exc)

    thread = threading.Thread(target=holder)
    thread.start()
    assert inside.wait(timeout=10), "A 线程没能进事务"
    try:
        memo.create_memo(proxy, text="B 的")  # 主线程：不在任何 unit 里
        assert "B 的" in _outside_texts(path), "★ 别的线程的提交被 A 的事务扣下了"
    finally:
        release.set()
        thread.join(timeout=10)
    assert errors == []
    assert _outside_texts(path) == ["A 的", "B 的"]


def test_a_real_connection_is_refused_instead_of_pretending(tmp_path: Path) -> None:
    """★ 真 `sqlite3.Connection` → **直接报错**，不给"以为有事务"的假象。

    这条是本卡最要紧的口径：`unit_of_work` 靠的是代理层拦 `commit()`，
    而真连接的 `commit` 是 C 方法、拦不住 —— 宁可不支持，也不静默降级
    （与 `db.raw_conn()` 同一条规矩）。
    """
    real = db.connect(str(tmp_path / "raw.db"))
    with pytest.raises(TypeError) as exc, db.unit_of_work(real, what="单线程脚本那条路"):
        memo.create_memo(real, text="不该走到这里")
    assert "代理" in str(exc.value)
    assert "单线程脚本那条路" in str(exc.value)


# ------------------------------------------------------------------ 3. 接口层（真缺陷的那两条路）


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(str(tmp_path / "api.db")))


def _fail_second_write(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    """让**第二条** core 调用抛一个数据库级错误（第一条照常跑）。"""
    real_create = tm.create_task
    real_update = tm.update_task

    def spy_create(conn: object, *args: object, **kwargs: object) -> object:
        task = real_create(conn, *args, **kwargs)  # type: ignore[arg-type]
        calls.append("create_task")
        return task

    def spy_update(conn: object, *args: object, **kwargs: object) -> object:
        task = real_update(conn, *args, **kwargs)  # type: ignore[arg-type]
        calls.append("update_task")
        return task

    def boom(conn: object, *args: object, **kwargs: object) -> None:
        calls.append("set_task_groups")
        raise sqlite3.OperationalError("磁盘满了（合成的数据库级错误）")

    monkeypatch.setattr(tm, "create_task", spy_create)
    monkeypatch.setattr(tm, "update_task", spy_update)
    monkeypatch.setattr(tm, "set_task_groups", boom)


def test_create_task_leaves_nothing_behind_when_the_group_link_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ 建任务时第二笔写崩了 → 接口报错，而且**库里不许留下那半条任务**。"""
    group = client.post("/api/groups", json={"name": "学习"}).json()["id"]
    calls: list[str] = []
    _fail_second_write(monkeypatch, calls)

    with pytest.raises(sqlite3.OperationalError):
        client.post("/api/tasks", json={"title": "写周报", "groups": [group]})

    assert calls == ["create_task", "set_task_groups"], "★ 第一条必须真的跑过（否则这条测试是空转）"
    assert client.get("/api/tasks").json() == [], "★ 半条任务不许留下"


def test_update_task_rolls_the_field_change_back_too(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ 改任务时第二笔写崩了 → **标题也不许被改掉**（以前它已经落库了）。"""
    task = client.post("/api/tasks", json={"title": "原标题"}).json()
    group = client.post("/api/groups", json={"name": "学习"}).json()["id"]
    calls: list[str] = []
    _fail_second_write(monkeypatch, calls)

    with pytest.raises(sqlite3.OperationalError):
        client.patch(f"/api/tasks/{task['id']}", json={"title": "新标题", "groups": [group]})

    assert calls == ["update_task", "set_task_groups"]
    got = client.get(f"/api/tasks/{task['id']}").json()
    assert got["title"] == "原标题", "★ 第一笔写必须跟着第二笔一起撤"


def test_the_happy_path_still_lands_both_writes(client: TestClient) -> None:
    """对照组：一切正常时，任务与分组关联**都要在**（事务不能把正常路径吃掉了）。"""
    group = client.post("/api/groups", json={"name": "学习"}).json()["id"]
    task = client.post("/api/tasks", json={"title": "写周报", "groups": [group]}).json()
    assert task["groups"] == ["学习"]
    assert [t["title"] for t in client.get("/api/tasks").json()] == ["写周报"]
    assert [t["title"] for t in client.get(f"/api/groups/{group}/tasks").json()] == ["写周报"]


# ------------------------------------------------------------------ 4. 清单层（机械扫描）


def _committing_functions(path: Path) -> set[str]:
    """这个模块（包的话扫整棵树）里**函数体含 `commit()`** 的函数名。"""
    files = sorted(path.parent.glob("*.py")) if path.name == "__init__.py" else [path]
    names: set[str] = set()
    for file in files:
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any(
                isinstance(c, ast.Call)
                and isinstance(c.func, ast.Attribute)
                and c.func.attr in ("commit", "executescript")
                for c in ast.walk(node)
            ):
                names.add(node.name)
    # `unit_of_work` 自己就是那个"把提交推迟"的东西，不是被数的写入
    return names - {"unit_of_work"}


def _module_path(dotted: str) -> Path | None:
    base = ROOT / "src" / dotted.replace(".", "/")
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _multi_write_handlers() -> dict[str, tuple[int, bool]]:
    """`app.py` 里"调了 ≥2 个会自己 commit 的 core 函数"的处理函数 → (条数, 有没有包事务)。"""
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    aliases: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("timeflow."):
            for alias in node.names:
                found = _module_path(f"{node.module}.{alias.name}") or _module_path(node.module)
                if found is not None:
                    aliases[alias.asname or alias.name] = _committing_functions(found)

    found_handlers: dict[str, tuple[int, bool]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(
            isinstance(dec, ast.Call)
            and isinstance(dec.func, ast.Attribute)
            and dec.func.attr in ("get", "post", "put", "patch", "delete", "api_route")
            for dec in node.decorator_list
        ):
            continue
        count = 0
        wrapped = False
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                base = child.func.value
                if isinstance(base, ast.Name) and child.func.attr in aliases.get(base.id, set()):
                    count += 1
                if child.func.attr == "unit_of_work":
                    wrapped = True
        if count >= 2:
            found_handlers[node.name] = (count, wrapped)
    return found_handlers


def test_every_multi_write_handler_is_wrapped_or_explicitly_exempt() -> None:
    """★ 清单层：一个处理函数里 ≥2 笔会自己提交的 core 调用 → 要么包事务、要么写明理由豁免。

    实测今天是 **6 个**：三个包了 `unit_of_work`（建任务 / 改任务 / 改提醒设置），
    三个在豁免清单上（第二笔是导出一份 md）。**新写一个这样的处理函数会被这条拦住** ——
    这就是"残留不再长回来"的机器形态。
    """
    handlers = _multi_write_handlers()
    assert set(handlers) == {"create_task", "update_task", "put_reminder_settings"} | set(
        EXEMPT_MULTI_WRITE
    ), f"多写处理函数的清单变了：{sorted(handlers)}"
    for name, (count, wrapped) in handlers.items():
        if name in EXEMPT_MULTI_WRITE:
            assert not wrapped, f"{name} 已经包了事务，就该从豁免清单里删掉"
            assert len(EXEMPT_MULTI_WRITE[name]) >= 10, f"{name} 的豁免理由太短"
            continue
        assert wrapped, f"{name} 调了 {count} 个会自己 commit 的 core 函数，却没包 db.unit_of_work"


def test_the_scan_actually_sees_the_writes_it_counts() -> None:
    """给扫描器一条"它真的看得到东西"的判据 —— 否则上面那条可能是空转。

    ★ 这里顺带钉住第一版扫描器的错：`timeflow.core.tasks` 是**包**（`__init__.py` 只做
    re-export），只解析 `__init__.py` 的话 `set_task_groups`（真身在 `groups.py`）根本看不到 ——
    当时量出来的清单是假的（只有 1 条）。所以扫包必须扫整棵树。
    """
    names = _committing_functions(_module_path("timeflow.core.tasks"))  # type: ignore[arg-type]
    assert {"create_task", "set_task_groups", "update_task"} <= names
    assert _multi_write_handlers()["create_task"][0] >= 2


def test_the_day_is_pinned_so_nothing_here_depends_on_when_it_runs() -> None:
    """这些用例不碰日期，但把"今天"钉住与全仓一个口径（免得哪天被别的断言带进来）。"""
    assert clock.today_iso() == "2026-06-15"
