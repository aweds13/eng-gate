"""第 2 步 LF-1 真实运行验证：起真服务 + 真 HTTP 走完 MVP 主链。

用法（在项目根）：
    python -X utf8 tools/lf1_live_check.py [port]

流程：新建任务 → 绑定任务专注 → 正常结束 → 摘要投入 + 当日反馈自动累加
      → 任务流水可见时长 → 完成任务（task.completed 事实）→ 撤销完成（task.uncompleted）
只使用标准库 urllib，不改动任何项目代码，不写项目库（用临时目录建库）。
"""

from __future__ import annotations

import json
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import uvicorn

from timeflow.api.app import create_app

FAILURES: list[str] = []


def check(label: str, got: object, want: object) -> None:
    ok = got == want
    print(f"[{'OK ' if ok else 'FAIL'}] {label}: got={got!r} want={want!r}")
    if not ok:
        FAILURES.append(label)


def http(method: str, url: str, payload: dict[str, object] | None = None) -> object:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 —— 本地回环
        return json.loads(resp.read().decode("utf-8"))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else free_port()
    base = f"http://127.0.0.1:{port}"
    workdir = Path(tempfile.mkdtemp(prefix="lf1_"))
    db_path = str(workdir / "live.db")

    app = create_app(db_path)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    if not server.started:
        print("FAIL: 服务未启动")
        return 1
    print(f"服务已启动：{base}（库 {db_path}）")

    try:
        # ① 新建任务（进 My Day）
        task = http("POST", f"{base}/api/tasks", {"title": "写高数", "is_myday": True})
        tid = task["id"]  # type: ignore[index]
        print(f"① 新建任务 {tid} 标题={task['title']!r}")  # type: ignore[index]

        # ② 绑定任务开始专注
        session = http("POST", f"{base}/api/focus/start", {"kind": "plain", "task_id": tid})
        sid = session["id"]  # type: ignore[index]

        # ③ 正常结束 1800 秒
        http("POST", f"{base}/api/focus/{sid}/finish", {"duration_sec": 1800})

        # ④ 摘要投入 = 0.5h
        check("④ 摘要 invest_hours", http("GET", f"{base}/api/summary")["invest_hours"], 0.5)  # type: ignore[index]

        # ⑤ 当日反馈自动累加（不靠前端传参）
        feedback = http("GET", f"{base}/api/feedback")
        check("⑤ 当日反馈 focus_minutes", feedback["focus_minutes"], 30.0)  # type: ignore[index]

        # ⑥ 任务流水可见时长
        sessions = http("GET", f"{base}/api/focus/tasks/{tid}")
        check(
            "⑥ 绑定任务时长合计(秒)",
            sum(int(s["duration_sec"] or 0) for s in sessions),  # type: ignore[union-attr]
            1800,
        )

        # ⑦ 完成任务 → task.completed 事实
        done = http("POST", f"{base}/api/tasks/{tid}/complete")
        check("⑦ 任务状态", done["status"], "完成")  # type: ignore[index]
        facts = http("GET", f"{base}/api/tasks/{tid}/facts")
        check("⑦ 事实流水", [f["kind"] for f in facts], ["task.completed"])  # type: ignore[union-attr]

        # ⑧ 撤销完成 → task.uncompleted 反向事实
        back = http("POST", f"{base}/api/tasks/{tid}/uncomplete")
        check("⑧ 撤销后状态", back["status"], "未开始")  # type: ignore[index]
        facts2 = http("GET", f"{base}/api/tasks/{tid}/facts")
        check(
            "⑧ 事实流水（含反向）",
            [f["kind"] for f in facts2],  # type: ignore[union-attr]
            ["task.completed", "task.uncompleted"],
        )
    except (urllib.error.URLError, KeyError) as exc:
        print(f"FAIL: 请求异常 {exc!r}")
        FAILURES.append("http")
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    print()
    if FAILURES:
        print(f"LF-1 真实运行验证：FAIL（{len(FAILURES)} 项：{', '.join(FAILURES)}）")
        return 1
    print("LF-1 真实运行验证：PASS（主链 8 步全通过）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
