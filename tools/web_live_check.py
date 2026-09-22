"""R2 真机自检：提取 index.html 的脚本做语法检查 + 起真服务取页面/样式。

为什么需要：前端测试查的是字符串存在性，**JS 语法错误会让整页白屏而测试照样全绿**。
这里用 `node --check` 做真正的语法解析（node 缺失时明确跳过并说明，不谎报通过）。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import uvicorn

from timeflow.api.app import create_app

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "src" / "web" / "index.html"
SCRIPT = re.compile(r"<script>(.*?)</script>", re.S)


def check_js_syntax(tmp: Path) -> tuple[bool, str]:
    node = shutil.which("node")
    m = SCRIPT.search(INDEX.read_text(encoding="utf-8"))
    if not m:
        return False, "index.html 里找不到 <script> 块"
    js_file = tmp / "app_extract.mjs"
    js_file.write_text(m.group(1), encoding="utf-8")
    if not node:
        return True, "跳过：环境没有 node，无法做语法解析（未验证）"
    proc = subprocess.run(
        [node, "--check", str(js_file)], capture_output=True, text=True, timeout=60
    )
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout).strip()[:500]
    return True, f"node --check 通过（{js_file.name}）"


def _rail_nav(html: str) -> str:
    """取出左栏导航那一段（用于检查「设置」入口是否在宽屏左栏里）。"""
    return html.split('class="rail"', 1)[1].split("</nav>", 1)[0]


def _json_call(base: str, path: str, method: str = "GET", payload: dict | None = None,
               headers: dict | None = None) -> tuple[int, object]:
    """打真服务的 JSON 接口，返回 (状态码, 解析结果)。"""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{base}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:  # 4xx/5xx 也要看得到状态码
        return e.code, None


def live_remind_checks(base: str) -> dict[str, bool]:
    """T-B5 真机自检：到点提醒的**只读**面（开关状态与守卫）。

    **不在这里开启通知**：那会真的注册系统计划任务（改系统状态），属用户显式动作；
    而且本沙箱屏蔽了任务计划程序/WMI，注册必然失败 —— 用假 runner 的单元测试覆盖逻辑，
    真机验证交给用户点「试一下」与开关。
    """
    st_code, st = _json_call(base, "/api/settings/reminder")
    cross = _json_call(
        base, "/api/settings/reminder", "PUT", {"enabled": True},
        headers={"Origin": "https://evil.example"},
    )[0]
    return {
        "提醒通道状态可读": st_code == 200 and isinstance(st, dict)
        and st.get("enabled") is False and st.get("task_name") == "timeflow-reminders",
        "提醒开关拒绝跨站": cross == 403,
    }


def live_attach_checks(base: str, tmp: Path) -> dict[str, bool]:
    """T-B4 真机自检：附件打开规则在**真服务 + 真文件系统**上的行为。

    只走 `dry_run`（不真的弹资源管理器/开程序）——验的是"规则与解析"这段；
    真正弹窗那一下由用户点「打开」触发，属于人工确认项（见 CHECKPOINT 说明）。
    """
    folder = tmp / "课件"
    folder.mkdir(exist_ok=True)
    pdf = folder / "第3章.pdf"
    pdf.write_text("x", encoding="utf-8")

    _, default_run = _json_call(
        base, "/api/attach/open", "POST", {"target": str(pdf), "dry_run": True}
    )
    _json_call(base, "/api/settings/attach", "PUT", {"mode": "auto"})
    _, auto_run = _json_call(
        base, "/api/attach/open", "POST", {"target": str(pdf), "dry_run": True}
    )
    _, url_run = _json_call(base, "/api/attach/open", "POST", {"target": "https://example.com/x"})
    _, missing_run = _json_call(
        base, "/api/attach/open", "POST", {"target": str(tmp / "没有这个.pdf")}
    )
    dir_run = _json_call(
        base, "/api/attach/open", "POST", {"target": str(folder), "dry_run": True}
    )[1]
    bad_mode = _json_call(base, "/api/settings/attach", "PUT", {"mode": "乱写"})[0]
    bad_ext = _json_call(base, "/api/settings/attach", "PUT", {"whitelist": [".exe"]})[0]
    cross = _json_call(
        base, "/api/attach/open", "POST", {"target": str(pdf), "dry_run": True},
        headers={"Origin": "https://evil.example"},
    )[0]

    def action(payload: object) -> object:
        return payload.get("action") if isinstance(payload, dict) else None

    return {
        "附件规则（默认只到文件夹）": action(default_run) == "folder",
        "附件规则（按格式→定位文件）": action(auto_run) == "select",
        "附件规则（网址交浏览器）": action(url_run) == "browser",
        "附件规则（路径不存在→复制兜底）": action(missing_run) == "copy",
        "附件规则（目录→开目录）": action(dir_run) == "folder",
        "打开方式非法值被拒": bad_mode == 400,
        "白名单拒绝可执行类": bad_ext == 400,
        "跨站来源被拒（本机接口守卫）": cross == 403,
    }


def live_c_line_checks(base: str) -> dict[str, bool]:
    """C 批新增能力的**真机**检查（跑在临时库上的真服务）：类型+课程 / 复习线 / 产出分两类 /
    今天做成了什么 / 均衡度字段。

    为什么放这里而不只放单测：单测验的是"函数对"，这里验的是"**装起来之后**这条链真的通"
    （路由在场、字段真的顺着 JSON 出来、跨站仍被拒）。**刻意不碰真实数据**：库是临时目录里的。
    """
    tid = _json_call(base, "/api/tasks", "POST", {"title": "C 批检查用任务"})[1]["id"]
    # 类型 + 所属课程（T-C12）：普通不挂课程；作业能挂；课程名由后端给出
    cid = _json_call(base, "/api/courses", "POST", {"name": "检查用课程"})[1]["id"]
    normal_with_course = _json_call(
        base, "/api/tasks", "POST", {"title": "普通+课程", "course_id": cid}
    )[0]
    hw = _json_call(
        base, "/api/tasks", "POST", {"title": "第三章习题", "task_type": "作业", "course_id": cid}
    )[1]
    patched = _json_call(
        base, f"/api/tasks/{tid}", "PATCH", {"task_type": "考试", "course_id": cid}
    )[1]
    # 复习线（T-C5/C6/C7）：任务升级为复习卡（幂等）+ 词表 + 改形式/句柄
    meta = _json_call(base, "/api/review/meta")[1]
    up1 = _json_call(base, f"/api/tasks/{tid}/to-review", "POST", {"form": "exam"})[1]
    up2 = _json_call(base, f"/api/tasks/{tid}/to-review", "POST", {})[1]
    card_id = up1["card"]["id"]
    card = _json_call(
        base, f"/api/review/items/{card_id}", "PATCH", {"ref_handle": "Vault/x.md"}
    )[1]
    # 产出分两类 + 今天做成了什么 + 均衡度（T-C4 / T-C11 / T-C3）
    _json_call(base, "/api/ledger/output", "POST", {"kind": "kpi", "value": 1, "note": "卷子"})
    _json_call(base, "/api/ledger/output", "POST", {"kind": "asset", "value": 2, "note": "笔记"})
    _json_call(base, f"/api/tasks/{tid}/complete", "POST", {})
    summary = _json_call(base, "/api/summary")[1]
    week = _json_call(base, "/api/summary/weekly")[1]
    done = _json_call(base, "/api/today/done")[1]
    health = _json_call(base, "/api/health")[1]

    return {
        "类型+课程：普通不挂课程被拒": normal_with_course == 400,
        "类型+课程：作业挂上课、课程名后端给出": (
            hw.get("task_type") == "作业" and hw.get("course_name") == "检查用课程"
        ),
        "类型+课程：PATCH 能改类型并带出课程": (
            patched.get("task_type") == "考试" and patched.get("course_name") == "检查用课程"
        ),
        "复习词表从后端来（挖空/问答/真题）": [f["value"] for f in meta["forms"]]
        == ["cloze", "qa", "exam"],
        "任务→复习卡：升级成功且幂等": up1["created"] is True and up2["created"] is False,
        "复习卡：句柄可写": card.get("ref_handle") == "Vault/x.md",
        "产出分两类（KPI/资产各自计数）": (
            summary.get("output_kpi") == 1 and summary.get("output_asset") == 1
        ),
        "今天做成了什么：完成的任务在列": any(t["id"] == tid for t in done["tasks"]),
        "今天做成了什么：两类产出计数": (
            done["output_kpi"] == 1 and done["output_asset"] == 1 and len(done["outputs"]) == 2
        ),
        "均衡度字段齐（波动/空档/温和话）": (
            isinstance(week.get("focus_variation_minutes"), (int, float))
            and isinstance(week.get("longest_gap_days"), int)
            and bool(week.get("rhythm_note"))
        ),
        "健康检查报能自证的事实": (
            health.get("database_ok") is True and health.get("tasks", 0) >= 1
        ),
    }


def live_ai_checks(base: str) -> dict[str, bool]:
    """T-G6 真机自检：AI 接口的**边界**在真实服务上成立（开着/关着两条路都走一遍）。

    刻意按"关 → 开 → 用完再关"来做，与用户实际用法一致；这里只碰**临时库**，
    不会动你真实的任务清单。测的是边界，不是"AI 能不能用"：
    - 默认关时整组 403（读也拦）；
    - 打开后能读、能新增（归属 `ai`）；
    - **勾你建的 → 400**（这一条是整张卡的核心）；
    - 勾它自己建的 → 200，且事实里留下 `source=ai`；
    - 改/删方法 → 403 带原话；
    - 跨站 Origin → 403（读写都拦）。
    """
    evil = {"Origin": "https://evil.example"}
    off_read = _json_call(base, "/api/ai/tasks")[0]
    off_write = _json_call(base, "/api/ai/tasks", "POST", {"title": "x"})[0]
    turned_on = _json_call(base, "/api/settings/ai", "PUT", {"enabled": True})[0]
    ping = _json_call(base, "/api/ai/ping")
    mine_code, mine = _json_call(base, "/api/tasks", "POST", {"title": "真机自检·你建的"})
    ai_code, ai = _json_call(base, "/api/ai/tasks", "POST", {"title": "真机自检·AI 建的"})
    ai_task = (ai or {}).get("task", {}) if ai_code == 200 else {}
    own = _json_call(base, f"/api/ai/tasks/{ai_task.get('id')}/complete", "POST", {})[0]
    yours = _json_call(base, f"/api/ai/tasks/{(mine or {}).get('id')}/complete", "POST", {})
    refused = _json_call(base, f"/api/ai/tasks/{ai_task.get('id')}", "PATCH", {"title": "改"})[0]
    cross_read = _json_call(base, "/api/ai/tasks", headers=evil)[0]
    cross_write = _json_call(base, "/api/ai/tasks", "POST", {"title": "x"}, headers=evil)[0]
    facts = _json_call(base, f"/api/tasks/{ai_task.get('id')}/facts")[1] or []
    _json_call(base, "/api/settings/ai", "PUT", {"enabled": False})
    after_off = _json_call(base, "/api/ai/tasks")[0]
    return {
        "AI 默认关时整组 403": off_read == 403 and off_write == 403,
        "AI 开关能打开": turned_on == 200,
        "AI ping 自证边界": ping[0] == 200 and isinstance(ping[1], dict)
        and bool(ping[1].get("boundary")) and bool(ping[1].get("surface")),
        "AI 能新增（归属 ai）": ai_code == 200 and ai_task.get("created_by") == "ai"
        and (mine or {}).get("created_by") == "me",
        "AI 能勾自己建的": own == 200,
        "AI 勾你建的被 400 拦下": yours[0] == 400,
        "AI 改/删被明确拒绝": refused == 403,
        "AI 跨站读写都拦": cross_read == 403 and cross_write == 403,
        "AI 的动作在事实里可回溯": any(str(f.get("source")) == "ai" for f in facts),
        "AI 关掉后又回到 403": after_off == 403,
    }


def live_sync_checks(base: str, tmp: Path) -> dict[str, bool]:
    """T-G8 真机自检：同步包的**导出 → 预览 → 导入**在真服务上走一遍（场景 ③）。

    只碰临时库与临时目录：不会碰你真实的库，也不会把包写到别的地方。
    测的是三件事：能导出文件、预览**不改库**、导入后数据真的过来（并且**没删**本地的东西）。
    """
    mine = _json_call(base, "/api/tasks", "POST", {"title": "自检·本机原有的"})[1] or {}
    exported = _json_call(base, "/api/sync/export", "POST", {})
    path = (exported[1] or {}).get("path") if exported[0] == 200 else None
    status = _json_call(base, "/api/sync/status")[1] or {}
    bad_path = _json_call(base, "/api/sync/import", "POST", {"path": "Z:/没有这个包.json"})[0]
    cross = _json_call(
        base, "/api/sync/export", "POST", {}, headers={"Origin": "https://evil.example"}
    )[0]
    before = _json_call(base, "/api/tasks")[1] or []
    # 预览：把刚导出的包当"别人的"来合（设备号相同 → 400，正好也验证"自己导给自己被拒"）；
    # 再拿一个**改过设备号**的包预览一次，确认"预览不动库"。
    own = _json_call(base, "/api/sync/import", "POST", {"path": path, "dry_run": True})
    alien_path = tmp / "alien.json"
    if path:
        pack = json.loads(Path(str(path)).read_text(encoding="utf-8"))
        pack["device_id"] = "another-machine-9"
        pack["tables"] = {"tasks": [
            {"id": "probe-new-task", "title": "来自另一台的", "status": "未开始",
             "created_at": "2026-09-22T20:00:00", "is_myday": 1}]}
        alien_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
    preview = _json_call(base, "/api/sync/import", "POST",
                         {"path": str(alien_path), "dry_run": True})
    after = _json_call(base, "/api/tasks")[1] or []
    applied = _json_call(base, "/api/sync/import", "POST", {"path": str(alien_path)})
    final = _json_call(base, "/api/tasks")[1] or []
    return {
        "同步包能导出": exported[0] == 200 and bool(path) and Path(str(path)).is_file(),
        "导出报告含条数与设备号": bool((exported[1] or {}).get("rows"))
        and bool((exported[1] or {}).get("device_id")),
        "同步状态分文件/网络两笔": status.get("file_sync") is True
        and status.get("network_sync") is False and bool(status.get("device_id")),
        "状态写明不含本机设置": "app_settings" in (status.get("excluded_tables") or []),
        "导入不存在的包被 400": bad_path == 400,
        "同步接口拒绝跨站来源": cross == 403,
        "自己导给自己被 400（不白跑）": own[0] == 400,
        "预览不动库": [t["id"] for t in after] == [t["id"] for t in before]
        and (preview[1] or {}).get("totals", {}).get("inserted", 0) == 1,
        "导入后数据真的过来": applied[0] == 200
        and any(t["title"] == "来自另一台的" for t in final),
        "导入没删本机的任务": mine.get("title") is not None
        and any(t["title"] == "自检·本机原有的" for t in final),
    }


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="r2_"))
    ok, detail = check_js_syntax(tmp)
    print(f"[{'OK ' if ok else 'FAIL'}] JS 语法：{detail}")

    # 临时库 → markdown 也写临时目录（别往仓库 `export/` 里写合成数据，见 T-G4）
    os.environ.setdefault("TIMEFLOW_EXPORT__DIR", str(tmp / "export"))
    app = create_app(str(tmp / "r2.db"))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)

    base = f"http://127.0.0.1:{port}"
    html = urllib.request.urlopen(f"{base}/", timeout=10).read().decode("utf-8")
    css = urllib.request.urlopen(f"{base}/app.css", timeout=10).read().decode("utf-8")
    cfg = json.loads(
        urllib.request.urlopen(f"{base}/api/config", timeout=10).read().decode("utf-8")
    )
    # 右栏计时器的数据源：新库没有进行中的专注，应返回 null（而不是 500）
    active = json.loads(
        urllib.request.urlopen(f"{base}/api/focus/active", timeout=10).read().decode("utf-8")
    )

    checks = {
        "无内联事件处理器": "onclick=" not in html and "onkeydown=" not in html,
        "有事件委托监听": "document.addEventListener('click'" in html,
        "无 alert/prompt": "alert(" not in html and "prompt(" not in html,
        "模板用 data-action": html.count("data-action=") >= 40,
        "页面引用 app.css": "/app.css" in html,
        "样式可取到": "--accent-soft" in css,
        "config 提供强调色": bool(cfg.get("accent_color")),
        # R3 三栏（SR-NF4）：壳里三个区域都在，且右栏计时器/详情挂载点存在
        "三栏骨架齐全": all(k in html for k in
                            ('class="shell"', 'class="rail"', 'id="main"', 'class="sidebar"',
                             'id="focusRail"', 'id="detailRail"')),
        "宽屏三栏是弹性布局": "flex: 0 0 168px" in css and "max-width: 820px" in css,
        "断点互斥(980/979)": "@media (min-width: 980px)" in css
        and "@media (max-width: 979px)" in css,
        "计时器归属右栏": "function renderActive(el,active)" in html and "paintRail(mySeq)" in html,
        "计时器数据源可用": active is None or isinstance(active, dict),
        # 设置页（用户要求统一收拢）+ 挤压/遮挡修复的样式约定
        "左栏有设置入口": 'data-view="setting"' in _rail_nav(html),
        "挤压修复样式在位": ".new button { flex: none }" in css and ".field" in css,
        "暗色令牌可取到": '[data-theme="dark"]' in css,
        # 智能视图可达（T-B3）：左栏 / 全部任务页 / 设置页都有入口 ——
        # 手机端（≤640px）左栏导航被 CSS 隐藏，所以不能只靠左栏（否则手机上直接进不去）。
        "智能视图可达": all(
            f'data-view="{v}"' in _rail_nav(html) and f'data-view="{v}"' in html
            for v in ("important", "planned", "flagged")
        ) and html.count("smartViewNavHTML(") >= 3,
    }
    # 视图路由自检：每个 data-view 要么是合法视图，要么是已注册的动作（点了没反应最难查）
    views = set(re.findall(r"const VIEWS=\[([^\]]*)\]", html)[0].replace("'", "").split(","))
    views = {v.strip() for v in views if v.strip()}
    actions = set(re.findall(r"'([a-z-]+)':\s*(?:el\s*=>|\()", html.split("const ACTIONS")[1]))
    targets = set(re.findall(r'data-view="([a-z-]+)"', html))
    unknown = sorted(targets - views - actions)
    checks["data-view 全部有落点"] = not unknown
    if unknown:
        print(f"[提示] 以下 data-view 既不是视图也没注册动作：{unknown}")
    checks.update(live_attach_checks(base, tmp))
    checks.update(live_remind_checks(base))
    checks.update(live_c_line_checks(base))
    checks.update(live_ai_checks(base))
    checks.update(live_sync_checks(base, tmp))
    for name, passed in checks.items():
        print(f"[{'OK ' if passed else 'FAIL'}] {name}")
    server.should_exit = True
    thread.join(timeout=10)
    return 0 if ok and all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
