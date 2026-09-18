"""第 4 步（前端补交互）· API 契约烟测。

前端是单文件 `src/web/index.html`（无构建步骤），无法用浏览器跑自动化；
这里守护「前端依赖的每个 API 契约」与「页面确实调用/暴露了这些能力」，
防止后端改口径后前端静默断链。

覆盖：
- 页面能被应用挂载并返回（HTML 含关键入口与关键 API 路径）；
- 前端用到的每个 endpoint 都存在且返回预期结构；
- 完成/撤销、专注→反馈、复习进 My Day 三条主链在 API 层可用。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app

WEB_INDEX = Path(__file__).resolve().parent.parent / "src" / "web" / "index.html"
WEB_CSS = Path(__file__).resolve().parent.parent / "src" / "web" / "app.css"


def _html(tmp_path) -> str:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "f.db")))
    resp = client.get("/")
    assert resp.status_code == 200
    return resp.text


def test_index_served_at_root(tmp_path) -> None:  # type: ignore[no-untyped-def]
    html = _html(tmp_path)
    assert "<title>timeflow</title>" in html


def test_index_has_no_hardcoded_colors() -> None:
    """R1 护栏：颜色只允许出现在 app.css 的令牌区，index.html 里不许写死。

    唯一豁免：`<meta name="theme-color">` —— 那是给浏览器 UI（地址栏/状态栏）看的，
    不接受 CSS 变量，必须留字面色值。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    offenders = [
        line.strip()
        for line in html.splitlines()
        if re.search(r"#[0-9a-fA-F]{3,8}\b", line) and "theme-color" not in line
    ]
    assert offenders == [], f"index.html 出现硬编码颜色：{offenders}"


def test_css_tokens_exist_and_cover_both_themes() -> None:
    """R1 护栏：令牌区必须同时定义亮/暗两套，且覆盖关键语义色。"""
    css = WEB_CSS.read_text(encoding="utf-8")
    assert ":root" in css
    assert '[data-theme="dark"]' in css
    for token in (
        "--accent", "--accent-on", "--accent-soft", "--bg", "--card", "--surface-2",
        "--line", "--text", "--muted", "--danger", "--ok", "--shadow",
    ):
        assert token in css, f"缺少令牌 {token}"
    # 暗色块里也要有背景/文字/表面的覆盖（否则暗色会是半成品）
    dark = css.split('[data-theme="dark"]', 1)[1].split("}", 1)[0]
    for token in ("--bg", "--card", "--surface-2", "--line", "--text"):
        assert token in dark, f"暗色令牌缺少 {token}"


def test_index_links_app_css_and_serves_it(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """样式抽出去之后，页面要真的引用到它，且服务端能取到（否则会白屏无样式）。"""
    html = _html(tmp_path)
    assert '/app.css' in html

    client = TestClient(create_app(str(tmp_path / "css.db")))
    resp = client.get("/app.css")
    assert resp.status_code == 200
    assert "--accent" in resp.text


def test_no_inline_event_handlers() -> None:
    """R2 护栏：交互一律走 `data-action` 事件委托，模板里不许再出现内联 onclick/onkeydown。

    理由：内联字符串要手工转义引号（习惯名处踩过）、三栏布局会引入三处事件源、无法统一测试。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    offenders = re.findall(r'on(?:click|keydown|input|change)\s*=', html)
    assert offenders == [], f"仍有内联事件处理器 {len(offenders)} 处：{offenders[:5]}"


def test_every_data_action_is_registered() -> None:
    """R2 护栏：模板里用到的每个 data-action 都必须在 JS 的 ACTIONS 表里注册。

    否则点了没反应（比报错更难发现）—— 这是事件委托最大的坑。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    used = set(re.findall(r'data-action="([a-z-]+)"', html))
    registered = set(re.findall(r"'([a-z-]+)':\s*(?:el\s*=>|\()", html.split("const ACTIONS")[1]))
    missing = sorted(used - registered)
    assert not missing, f"这些 data-action 未注册：{missing}"
    assert len(used) >= 30, f"data-action 数量异常偏少（{len(used)}），可能漏改模板"


def test_no_alert_or_prompt_in_script() -> None:
    """R2 护栏：不用浏览器模态框做确认/输入（温和基调 + 部分环境会禁用 prompt）。

    允许 confirm（删除类二次确认当前仍用它）；alert/prompt 不允许新增。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    assert "alert(" not in html, "不要用 alert 打断用户"
    assert "prompt(" not in html, "不要用 prompt 做输入（改用内联表单/面板）"


def test_race_guard_exists() -> None:
    """护栏：「快速点击顶部 → 操作未完成」的修复必须留在代码里。

    修复要点：渲染序号（后点的那次说了算）+ AbortController（切视图取消上一组请求）+
    AbortError 静默（取消不是错误，不该弹提示）。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    for needle in (
        "let renderSeq=0",
        "let abortCtl=null",
        "abortCtl.abort()",
        "mySeq!==renderSeq",
        "name==='AbortError'",
    ):
        assert needle in html, f"缺少竞态防护：{needle}"
    assert "toast('网络请求失败，稍后再试')" in html, "非取消类网络错误仍应提示"


def test_gpa_scale_is_switchable_in_page() -> None:
    """护栏：GPA 制式要能**在页面上切换**（而不是只弹一句"去改 config.toml"）。"""
    html = WEB_INDEX.read_text(encoding="utf-8")
    assert "let gpaScale=" in html
    assert "data-action=\"set-gpa\"" in html and 'data-scale="5.0"' in html
    assert "gpaScale=" in html.split("async function setGpa")[1][:200]
    assert "/api/gpa?scale=" in html
    # 加权平均成绩（Σ学分×成绩 / Σ学分）必须展示
    assert "weighted_average" in html and "加权平均成绩" in html


def test_index_exposes_core_entries(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """关键入口必须在页面上存在（回归：改前端别把主链按钮弄丢）。"""
    html = _html(tmp_path)
    for needle in (
        'id="main"',
        "renderToday",
        "renderTasks",
        "renderFocus",
        "taskCard",
        "toggleDone(",
        "undoDone(",
        "finishFocus(",
        "restoreTask(",
        "retractOutput(",
        "retractInvest(",
        "addInvest(",
        "weekCard(",
        "renderStats",
        "lineChart(",
        "barList(",
        "heatmap(",
        "valueHeatmap(",
        "setHeatmap(",
        "/api/insights/heatmap",
        "ring(",
        "todayCard(",
        "progressBar(",
        "radar(",
        "gpaRadar(",
        "/api/grades",
        "addAssessment(",
        "delAssessment(",
        "delGrade(",
        "/api/assessments/upcoming",
        "renameHabit(",
        "deleteHabit(",
        "memoToTask(",
        "deleteMemo(",
        "assignTask(",
        "teamStatus(",
        "TEAM_NEXT",
        "/api/sync/status",
        "/api/focus/active",
        "/api/tasks/deleted",
        "/api/ledger/outputs",
        "/api/ledger/invests",
        "/api/summary/weekly",
        "/api/insights/daily",
        "/api/insights/groups",
    ):
        assert needle in html, f"前端缺少入口: {needle}"


def test_index_calls_backend_contract_paths(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """前端调用的 API 路径必须与后端一致（按前缀核对，避免拼错/漏改）。"""
    html = _html(tmp_path)
    called = set(re.findall(r"api\((?:`|')?(/[a-zA-Z0-9/_{}$.\-]*)", html))
    prefixes = {c.split("${")[0] for c in called}
    for path in (
        "/api/mydays",
        "/api/overdue",
        "/api/summary",
        "/api/tasks",
        "/api/focus/",
        "/api/feedback",
        "/api/selfcheck",
        "/api/ledger/outputs",
    ):
        assert any(p.startswith(path) or path.startswith(p.rstrip("/")) for p in prefixes), (
            f"前端未调用 {path}"
        )


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("get", "/api/mydays?include_reviews=1", None),
        ("get", "/api/overdue", None),
        ("get", "/api/tasks", None),
        ("get", "/api/tasks/deleted", None),
        ("get", "/api/summary", None),
        ("get", "/api/ledger/outputs", None),
        ("get", "/api/ledger/invests", None),
        ("get", "/api/summary/weekly", None),
        ("get", "/api/insights/daily?days=30", None),
        ("get", "/api/insights/groups?days=30", None),
        ("get", "/api/insights/heatmap?days=30", None),
        ("get", "/api/habits", None),
        ("get", "/api/grades", None),
        ("get", "/api/assessments/upcoming?days=14", None),
        ("get", "/api/sync/status", None),
        ("get", "/api/focus/today", None),
        ("get", "/api/focus/active", None),
        ("get", "/api/feedback", None),
        ("get", "/api/selfcheck", None),
        ("get", "/api/review/due", None),
        ("get", "/api/memos", None),
        ("get", "/api/courses", None),
        ("get", "/api/config", None),
    ],
)
def test_backend_contracts_used_by_frontend(
    tmp_path, method: str, path: str, payload: dict[str, object] | None
) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "c.db")))
    resp = getattr(client, method)(path, json=payload) if payload else getattr(client, method)(path)
    assert resp.status_code == 200, f"{path} → {resp.status_code}"


def test_frontend_main_chain_works_end_to_end(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """页面主链三步：完成任务（含撤销）/ 专注结束→反馈即时变化 / 复习进 My Day。"""
    client = TestClient(create_app(str(tmp_path / "e2e.db")))

    # ① 完成任务 → 可撤销
    tid = client.post("/api/tasks", json={"title": "写高数", "is_myday": True}).json()["id"]
    assert client.post(f"/api/tasks/{tid}/complete").json()["status"] == "完成"
    assert client.post(f"/api/tasks/{tid}/uncomplete").json()["status"] == "未开始"

    # ② 专注：开始 → 进行中 → 结束 → 摘要/反馈即时变化
    sid = client.post("/api/focus/start", json={"kind": "plain", "task_id": tid}).json()["id"]
    active = client.get("/api/focus/active").json()
    assert active["id"] == sid
    assert client.get("/api/summary").json()["invest_hours"] == 0.0  # 进行中不计投入
    client.post(f"/api/focus/{sid}/finish", json={"duration_sec": 1800})
    assert client.get("/api/focus/active").json() is None
    assert client.get("/api/summary").json()["invest_hours"] == 0.5
    assert client.get("/api/feedback").json()["focus_minutes"] == 30.0

    # ③ 复习：到期卡进 My Day，三态反馈后留下事实
    rid = client.post("/api/review/items", json={"title": "泰勒展开"}).json()["id"]
    items = client.get("/api/mydays?include_reviews=1").json()
    assert any(i.get("kind") == "review" and i["id"] == rid for i in items)
    client.post(f"/api/review/{rid}/review", json={"feedback": "remember"})
    assert client.get("/api/summary").json()["review_count"] == 1
