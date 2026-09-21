"""例 4（集成）· 从**外部脚本**调 timeflow 的 REST 接口。

什么时候用这个示例：你想让**别的东西**（自己的脚本、手机上的快捷指令、另一个程序、
Obsidian 里的按钮、定时任务）跟 timeflow 打交道 —— 而不改 timeflow 的代码。
**这已经能做到了**：timeflow 跑起来就是一个本机 HTTP 服务，`/api/...` 就是它的全部能力。

三条必懂的规矩：
1. **别直接改 SQLite 库**。走 REST：库里的派生数字（账本/债务/洞察）都由**事实层**算出来，
   绕过接口直接 `UPDATE` 会让"事实"和"状态"对不上（下次迁移或回填时就会打架）。
2. **接口是成对的**：写了就能撤（`complete`/`uncomplete`、`invest`/`DELETE invest`、
   `output`/`DELETE output`）—— 外部脚本也要按这个来，别自己造一套"删除"。
3. **日期口径是本地日历、日界 00:00**（`specification/behaviors.md`）。传日期就传 `YYYY-MM-DD`。

跑法（在项目根目录）：
    python -X utf8 examples/04_external_script.py

真机上怎么调：先 `python -X utf8 tools/serve.py`（或桌面窗口），服务在
`http://127.0.0.1:8000`；把下面的 `client.<方法>` 换成对同一路径的 HTTP 请求即可 ——
本示例用 `TestClient`（进程内跑同一套路由）是为了**不占端口、不依赖先起服务**，
请求与响应的形状和真机完全一致（见 `docs/EXTENDING.md` §七 的 PowerShell 版对照）。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from timeflow.api.app import create_app


def main() -> int:
    # `ignore_cleanup_errors`：Windows 上 SQLite 连接可能还占着库文件，删临时目录会报"拒绝访问" ——
    # 那是收尾噪声，不该让示例变红（真机上你自己起的服务也是常驻的）。
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        # 独立临时库：示例不碰你的真实数据（红线 2：数据不出本地）
        client = TestClient(create_app(str(Path(tmp) / "ex4.db")))

        # ① 先自报家门：健康检查给出"能自证的事实"（schema 版本 / 表条数 / 调试开关）
        health = client.get("/api/health").json()
        assert health["status"] == "ok" and health["database_ok"] is True, health
        print(f"[例4] 服务健康：schema v{health['schema_version']}  任务 {health['tasks']} 条")

        # ② 外部脚本**写**：建一个任务 → 完成它（成对动作，可撤销）
        task = client.post(
            "/api/tasks", json={"title": "外部脚本建的任务", "is_myday": True}
        ).json()
        assert task["title"] == "外部脚本建的任务", task
        done = client.post(f"/api/tasks/{task['id']}/complete").json()
        assert done["status"] == "完成", done
        print(f"[例4] 建任务 → 完成：{done['title']}（状态 {done['status']}）")

        # ③ 外部脚本**读**：账本数字来自事实层（这里"完成收益"= 1）
        summary = client.get("/api/summary").json()
        assert summary["gain_count"] == 1, summary
        print(f"[例4] 读账本：完成收益 {summary['gain_count']} · 债务 {summary['debt_count']} 项")

        # ④ **撤销也要走接口**（成对）：撤销完成后账本自己回退，不用外部脚本去"改数字"
        undone = client.post(f"/api/tasks/{task['id']}/uncomplete").json()
        assert undone["status"] == "未开始", undone
        assert client.get("/api/summary").json()["gain_count"] == 0
        print(f"[例4] 撤销完成 → 账本回退到 {client.get('/api/summary').json()['gain_count']}")

        # ⑤ 写错的姿势会得到明确的 4xx（不静默、不写脏数据）—— 外部脚本要照着"原话"改
        bad = client.post(f"/api/tasks/{task['id']}/attempt-failed", json={})
        assert bad.status_code == 200, bad.status_code  # 这个是合法动作，允许空说明
        missing = client.get("/api/tasks/nope").json()
        assert "detail" in missing, missing
        print(f"[例4] 不存在的任务 → 404 原话：{missing['detail']}")

        print("OK 例4：外部脚本能读能写能撤销（**没改 timeflow 一行代码**）")
        client.close()   # 关掉测试客户端（真机上外部脚本跑完也该关连接）
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
