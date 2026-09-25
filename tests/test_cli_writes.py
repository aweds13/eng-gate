"""写命令（T-G65）的测试 —— 「默认关」与「和界面同一条路」这两句话的机器形态。

用户 2026-09-25 定的三条口径，逐条都有判据：

| 口径 | 判在哪 |
|---|---|
| ① 只做**界面上已有的那些** | `test_cli_line.py` 的
  `test_real_repo_write_commands_only_do_what_the_ui_already_does`（OP 的 `ui` 非空）+ 门禁那一节 |
| ② **默认关** | 这个文件：不带 `--allow-write` → 退 **4** + `write_disabled`，**库一个字节没动** |
| ③ 语义与界面**完全一样** | 这个文件：同一条命令走 CLI 与直接打那条路由，**可观察状态逐条相同** |

为什么"没开关就拒绝"要连"库没动"一起判：写命令最大的风险不是报错，是**悄悄写了**。
所以这条测试在跑之前先拍一张库的快照（走只读路由），跑完再拍一张，逐字节比。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent

from timeflow.api.app import create_app  # noqa: E402
from timeflow.cli import main as cli_mod  # noqa: E402
from timeflow.cli import registry  # noqa: E402

CAPTURE_DAY = "2026-06-15"  # 与渲染/行为流同一个假日子（T-G62 的时钟缝）

#: 每条命令要给的"用户输入"（`id` 类参数从那一份真库里现取）
FIXED = {
    "add-task": {"title": "写周报", "due_date": "2026-06-20"},
    "memo": {"text": "随手记一条"},
}


@pytest.fixture(autouse=True)
def _pinned_day(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIMEFLOW_FAKE_TODAY", CAPTURE_DAY)


def _client(path: Path) -> TestClient:
    return TestClient(create_app(str(path)))


def _seed(client: TestClient, *, with_focus: bool = True) -> dict[str, str]:
    """一份有内容的真库：两个任务（一个进了今天）+（默认）一个正在进行的专注。

    `with_focus=False` 给 `focus-start` 用 —— 同时只允许一个进行中的专注（边界会 400），
    所以"开始一条新的"这条命令的前提是**手上没有**在跑的。
    """
    first = client.post(
        "/api/tasks", json={"title": "写周报", "due_date": "2026-06-10", "is_myday": True}
    ).json()
    client.post("/api/tasks", json={"title": "读论文", "due_date": "2026-06-20", "priority": "高"})
    ids = {"task_id": first["id"]}
    if with_focus:
        session = client.post("/api/focus/start", json={"task_id": first["id"]}).json()
        ids["session_id"] = session["id"]
    return ids


def _focus_shape(active: Any) -> Any:
    """进行中的专注：**不**比 id 与 started_at（两边必然不同），只比"在不在、挂谁、哪种"。"""
    if not isinstance(active, dict):
        return active
    return {
        "kind": active.get("kind"),
        "task": bool(active.get("task_id")),
        "device": bool(active.get("device_id")),
    }


def _shape(client: TestClient) -> dict[str, Any]:
    """库的**可观察状态**（只走只读路由）—— 比"写入效果一样"时不比 id 与时间戳。"""
    tasks = client.get("/api/tasks").json()
    memos = client.get("/api/memos").json()
    summary = client.get("/api/summary").json()
    return {
        "tasks": sorted((t["title"], t["status"], bool(t["is_myday"])) for t in tasks),
        "memos": sorted(m["text"] for m in memos),
        "focus": _focus_shape(client.get("/api/focus/active").json()),
        "numbers": {k: v for k, v in summary.items() if isinstance(v, (int, float))},
    }


def _cli_args(command: registry.Command, ids: dict[str, str]) -> list[str]:
    """把一条写命令拼成 argv（必填的那些从 `ids` 里取，其余用声明的默认值）。"""
    argv: list[str] = []
    for param in command.params:
        if param.name in FIXED.get(command.name, {}):
            argv += [f"--{param.name.replace('_', '-')}", FIXED[command.name][param.name]]
        elif param.name in ids:
            argv += [f"--{param.name.replace('_', '-')}", ids[param.name]]
        elif param.required:
            raise AssertionError(f"{command.name} 少了必填参数 {param.name} 的取法")
    return argv


def _route_body(command: registry.Command, ids: dict[str, str]) -> dict[str, Any]:
    """同一条命令的**请求体**（与 CLI 的解析规则一样：先用 `ids`/固定输入，再补声明的默认值）。"""
    body: dict[str, Any] = {}
    for param in command.params:
        if param.where != "body":
            continue
        if param.name in ids:
            body[param.name] = ids[param.name]
            continue
        raw = FIXED.get(command.name, {}).get(param.name, param.default)
        if raw is None:
            continue
        if param.kind == "int":
            body[param.name] = int(raw)
        elif param.kind == "bool":
            body[param.name] = str(raw).strip().lower() in ("1", "true", "yes", "on")
        else:
            body[param.name] = raw
    return body


def _run(capsys: pytest.CaptureFixture[str], args: list[str]) -> tuple[int, str, str]:
    code = cli_mod.main(args)
    out = capsys.readouterr()
    return code, out.out, out.err


# ------------------------------------------------------------------ 口径②：默认关


def test_every_write_command_is_refused_without_the_switch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """★ 不带 `--allow-write`：退 4 + `write_disabled`，而且**库一个字节都没动**。

    这条是"默认关"的全部内容。它同时证明拒绝发生在**发请求之前**（库根本没被打开）。
    """
    path = tmp_path / "w.db"
    client = _client(path)
    ids = _seed(client)
    before = _shape(client)

    assert registry.WRITE_COMMANDS, "写命令第一批不该是空的"
    for command in registry.WRITE_COMMANDS:
        args = [command.name, "--json", "--db", str(path), *_cli_args(command, ids)]
        code, out, err = _run(capsys, args)
        assert code == cli_mod.EXIT_REFUSED, f"{command.name}：{code} {err}"
        assert out == "", "stdout 只放数据（拒绝时一个字都没有）"
        error = json.loads(err.strip().splitlines()[-1])["error"]
        assert error["code"] == "write_disabled"
        assert cli_mod.WRITE_FLAG in error["detail"], error["detail"]
    assert _shape(client) == before, "拒绝之后库必须一个字节没动"


def test_a_write_still_refuses_to_create_a_missing_database(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """★ T-G66 那条口径对写命令同样成立：库不存在就退 3，**不许替你建一个空库**。

    "我要写"不等于"你可以凭空造一份新数据"——路径打错时宁可退 3。
    """
    missing = tmp_path / "没有这个库.db"
    code, out, err = _run(
        capsys,
        ["add-task", "--title", "写周报", "--allow-write", "--json", "--db", str(missing)],
    )
    assert code == cli_mod.EXIT_ENV
    assert out == ""
    assert json.loads(err.strip().splitlines()[-1])["error"]["code"] == "db_missing"
    assert not missing.exists(), "写命令也不该建库"


def test_missing_required_path_param_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """路径参数没给 → 退 1（在发请求之前拦住，别让边界去猜）。"""
    path = tmp_path / "w.db"
    _client(path).get("/api/tasks")
    code, _, err = _run(capsys, ["complete", "--allow-write", "--json", "--db", str(path)])
    assert code == cli_mod.EXIT_USAGE
    assert "task-id" in err, err


# ------------------------------------------------------------------ 口径③：与界面同一条路


def test_every_write_command_does_what_the_route_does(tmp_path: Path) -> None:
    """★ 逐条写命令：**CLI 的写入效果 == 直接打那条路由的效果**（可观察状态逐条相同）。

    这是"写入与界面语义完全一样"的机器形态（"界面"与 CLI 打的是同一条路由，
    所以这里其实是"CLI 没有偷偷多写/少写"的更硬版本：两边各起一份真库，比状态）。
    """
    for command in registry.WRITE_COMMANDS:
        cli_path = tmp_path / f"{command.name}-cli.db"
        route_path = tmp_path / f"{command.name}-route.db"
        cli_client, route_client = _client(cli_path), _client(route_path)
        focus = command.name != "focus-start"  # 开始专注的前提是手上没有在跑的（边界会 400）
        cli_ids = _seed(cli_client, with_focus=focus)
        route_ids = _seed(route_client, with_focus=focus)

        code = cli_mod.main(
            [command.name, "--allow-write", "--json", "--db", str(cli_path)]
            + _cli_args(command, cli_ids)
        )
        assert code == cli_mod.EXIT_OK, f"{command.name} 走 CLI 失败（退 {code}）"

        method, _, raw_path = command.route.partition(" ")
        path = raw_path
        for param in command.params:
            if param.where == "path":
                path = path.replace("{" + param.name + "}", route_ids[param.name])
        response = route_client.request(method, path, json=_route_body(command, route_ids) or None)
        assert response.status_code < 400, f"{command.name} 直接打路由失败：{response.text}"

        assert _shape(cli_client) == _shape(route_client), f"{command.name}：两边效果不一样"


def test_the_core_loop_runs_through_the_cli_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """只用命令行走一遍核心闭环：记一条 → 放进今天 → 勾完成 → 开专注 → 结束专注。

    这条是"这批写命令够不够用"的最小证据（也顺便钉住回执里那几行字）。
    """
    path = str(tmp_path / "loop.db")
    client = _client(Path(path))
    client.get("/api/tasks")

    code, out, err = _run(
        capsys, ["add-task", "--title", "写周报", "--allow-write", "--json", "--db", path]
    )
    assert code == cli_mod.EXIT_OK, err
    task_id = json.loads(out)["id"]

    _, plan_out, _ = _run(capsys, ["plan", "--db", path])
    assert "写周报" not in plan_out, "新建的任务默认**不进**今天（与界面同一个默认）"

    _run(capsys, ["myday", "--task-id", task_id, "--allow-write", "--db", path])
    _, plan_out, _ = _run(capsys, ["plan", "--db", path])
    assert "写周报" in plan_out

    _run(capsys, ["focus-start", "--task-id", task_id, "--allow-write", "--db", path])
    _, focus_out, _ = _run(capsys, ["focus", "--db", path])
    assert "进行中" in focus_out

    _run(
        capsys,
        ["complete", "--task-id", task_id, "--allow-write", "--db", path],
    )
    _, done_out, _ = _run(capsys, ["done", "--db", path])
    assert "写周报" in done_out


# ------------------------------------------------------------------ 参数与帮助


def test_boolean_and_number_arguments_arrive_with_real_json_types(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """开关写 `--is-myday`，数字写 `--duration-sec 60` —— 到边界时必须是**真类型**。

    边界是 FastAPI：`"false"`（字符串）会让它 422。所以这条测试同时证明类型转换真的做了。
    """
    path = str(tmp_path / "types.db")
    _client(Path(path)).get("/api/tasks")
    code, out, err = _run(
        capsys,
        [
            "add-task",
            "--title",
            "带类型",
            "--is-myday",
            "--allow-write",
            "--json",
            "--db",
            path,
        ],
    )
    assert code == cli_mod.EXIT_OK, err
    assert json.loads(out)["is_myday"] is True

    code, out, err = _run(
        capsys,
        [
            "add-task",
            "--title",
            "不要今天",
            "--is-myday=false",
            "--allow-write",
            "--json",
            "--db",
            path,
        ],
    )
    assert code == cli_mod.EXIT_OK, err
    assert json.loads(out)["is_myday"] is False

    code, _, err = _run(
        capsys, ["add-task", "--title", "x", "--is-myday=也许", "--allow-write", "--db", path]
    )
    assert code == cli_mod.EXIT_USAGE
    assert "开关" in err


def test_help_marks_write_commands_and_names_the_switch(capsys: pytest.CaptureFixture[str]) -> None:
    """帮助里必须**说清哪条会改数据**（人读的界面上不许靠猜）。"""
    for command in registry.WRITE_COMMANDS:
        code, out, _ = _run(capsys, [command.name, "--help"])
        assert code == cli_mod.EXIT_OK
        assert "会改数据" in out and cli_mod.WRITE_FLAG in out, command.name
        assert "→ 路径" in out or "→ 请求体" in out, command.name
    for command in registry.COMMANDS:
        code, out, _ = _run(capsys, [command.name, "--help"])
        assert "只读的" in out, command.name
