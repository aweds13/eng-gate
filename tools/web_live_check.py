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
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

import uvicorn

from timeflow.api.app import create_app

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))  # 同目录的令牌层工具
import contrast_audit as ca  # noqa: E402 —— 复用它的令牌切法/正则（T-G177）

INDEX = ROOT / "src" / "web" / "index.html"
SCRIPTS = (ROOT / "src" / "web" / "offline.js", ROOT / "src" / "web" / "sw.js")
PHONE_CHECK = ROOT / "tools" / "phone_check.mjs"
SCRIPT = re.compile(r"<script>(.*?)</script>", re.S)

# ★ 2026-09-28（T-G177）：暗色块里**必须真有**的令牌（背景 / 文字 / 表面）。
# ★ 存在性层（`tests/test_web_frontend.py`）与本文件的活体判据**共用这一份**，别两处各写一份 ——
#   这正是本卡要灭的病根（同一个口径写两套，切法和集合各自漂移）。
DARK_REQUIRED_TOKENS: tuple[str, ...] = ("--bg", "--panel", "--panel-2", "--border", "--ink")

# 取真暗色块的切法 = 令牌层 `contrast_audit.token_blocks` 用的同一条：同一正则、同样先剥注释。
_DARK_BLOCK = re.compile(r'\[data-theme="dark"\]\s*\{(.*?)\n\}', re.S)


def dark_block_text(css: str) -> str:
    """真 `[data-theme="dark"] { … }` 规则的块体（已剥注释）。

    ★ 为什么不用 `css.split('[data-theme="dark"]', 1)`:那句话在 `app.css` 的**文件头注释**
    （第 6 行）先出现过一次，split 会切到"注释之后到第一个 `}`" —— 也就是 `:root` **亮色**块，
    真暗色块永远读不到（卡 080 实测：清空暗色块它仍绿）。用令牌层同一条正则取，命中即真规则。
    """
    m = _DARK_BLOCK.search(css)
    if m is None:
        raise SystemExit('web_live：app.css 里找不到 [data-theme="dark"] 令牌区')
    return re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)


def dark_declared_tokens(css: str) -> set[str]:
    """暗色块里**真正声明**的令牌名（只看 delta —— 不含亮色块可回落的那些）。

    ★ 不能直接用 `contrast_audit.token_blocks(css)["dark"]`：那个 dark 是 `{**light, **delta}`，
    亮色块有而暗色块没有的令牌（如被删掉的 `--border`）会从亮色"看得见"，判不出"暗色块自己缺令牌"。
    """
    return {m.group(1) for m in ca._TOKEN.finditer(dark_block_text(css))}


def check_js_syntax(tmp: Path) -> tuple[bool, str]:
    """页面脚本 + 手机离线引擎 + service worker 都过一遍 `node --check`。

    `offline.js` 与 `sw.js` 是**独立文件**（不是页面里那段内联脚本），所以各查一次 ——
    一个语法错就能让离线记整块失效，而字符串护栏看不出来。
    """
    node = shutil.which("node")
    m = SCRIPT.search(INDEX.read_text(encoding="utf-8"))
    if not m:
        return False, "index.html 里找不到 <script> 块"
    js_file = tmp / "app_extract.mjs"
    js_file.write_text(m.group(1), encoding="utf-8")
    if not node:
        return True, "跳过：环境没有 node，无法做语法解析（未验证）"
    proc = subprocess.run(
        [node, "--check", str(js_file)], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60,
    )
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout).strip()[:500]
    names = [js_file.name]
    for path in SCRIPTS:
        # 复制成 .mjs 再查：`node --check` 对 `.js` 会按 CommonJS 解析，`.mjs` 才是我们实际用的形态
        target = tmp / (path.stem + "_check.mjs")
        target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        got = subprocess.run(
            [node, "--check", str(target)], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60,
        )
        if got.returncode != 0:
            return False, f"{path.name}: " + (got.stderr or got.stdout).strip()[:500]
        names.append(target.name)
    return True, f"node --check 通过（{' / '.join(names)}）"


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
    - **报告进展（T-G21）**：往**你建的**任务上报一句 → 200 且那条任务的
      状态/版本/备注**一个字节不动**，报告出现在卡片字段上；空话 400；
      撤销之后**原事实还在**（只是被指回去了）；
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
    # 报告进展（T-G21）：整张卡的新那一段 —— 往**你建的**任务上报一句，任务字段一个都不许动。
    # 走真 HTTP 才验得出的正是"它改没改你那条任务"（单元测试里读的是同一个进程里的对象）。
    mine_id = (mine or {}).get("id")
    before_prog = _json_call(base, f"/api/tasks/{mine_id}")[1] or {}
    prog = _json_call(base, f"/api/ai/tasks/{mine_id}/progress", "POST",
                      {"note": "真机自检·AI 报了一句话"})
    after_prog = _json_call(base, f"/api/tasks/{mine_id}")[1] or {}
    blank = _json_call(base, f"/api/ai/tasks/{mine_id}/progress", "POST", {"note": "   "})[0]
    undo = _json_call(base, f"/api/tasks/{mine_id}/progress/retract", "POST", {})
    prog_facts = _json_call(base, f"/api/tasks/{mine_id}/facts")[1] or []
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
        "AI 报告进展不改你的任务": prog[0] == 200
        and (after_prog.get("status"), after_prog.get("version"), after_prog.get("note"))
        == (before_prog.get("status"), before_prog.get("version"), before_prog.get("note")),
        "AI 报告落到卡片字段上": after_prog.get("progress_count") == 1
        and after_prog.get("progress_note") == "真机自检·AI 报了一句话"
        and after_prog.get("progress_label") == "AI 报告",
        "AI 空话报告被 400 拦下": blank == 400,
        "撤销报告后原事实还在": undo[0] == 200
        and ((undo[1] or {}).get("task", {}) or {}).get("progress_count") == 0
        and any(str(f.get("kind")) == "task.progress.reported" for f in prog_facts),
        "AI 跨站读写都拦": cross_read == 403 and cross_write == 403,
        "AI 的动作在事实里可回溯": any(str(f.get("source")) == "ai" for f in facts),
        "AI 关掉后又回到 403": after_off == 403,
    }


def live_team_checks(base: str) -> dict[str, bool]:
    """T-G12 真机自检：团队视角页（OP-33）在**真服务**上成立 —— 两个视角 + 四条边界。

    走真 HTTP 而不是只看函数返回值：验的是"界面上那两个按钮打到的接口"到底怎么答。
    只碰**临时库**（`web_live_check` 起的一次性库），不动你真实的任务清单。
    - 默认视角 = 管理者；按执行者分组（不是相邻同名归组）；
    - 执行者视角只给这个名字的（中文名字要 URL 编码才能进 query）；
    - **没填"我是谁"就不猜**：空列表 + 说明，不报错；
    - 非法视角 / 非法状态 → 400（不静默回落成默认值）；
    - 任务进回收站（软删）后分配记录**留着**并标明"在回收站"。
    """
    t1 = _json_call(
        base, "/api/tasks", "POST", {"title": "真机自检·甲", "due_date": "2030-01-01"}
    )[1]
    t2 = _json_call(base, "/api/tasks", "POST", {"title": "真机自检·乙"})[1]
    a1 = _json_call(base, "/api/team/assign", "POST",
                    {"task_id": t1["id"], "assignee": "小王", "note": "周五前"})[1]
    _json_call(base, "/api/team/assign", "POST", {"task_id": t2["id"], "assignee": "小李"})
    _json_call(base, f"/api/team/assign/{a1['id']}", "PATCH", {"status": "blocked"})

    mgr = _json_call(base, "/api/team/board")[1] or {}
    exe = _json_call(base, f"/api/team/board?view=executor&me={quote('小王')}")[1] or {}
    nobody = _json_call(base, "/api/team/board?view=executor")[1] or {}
    bad_view = _json_call(base, "/api/team/board?view=boss")[0]
    bad_status = _json_call(base, "/api/team/board?status=sleeping")[0]

    groups = mgr.get("groups") or []
    names = [g.get("assignee") for g in groups]
    wang = next((g for g in groups if g.get("assignee") == "小王"), {})
    exe_items = [i for g in (exe.get("groups") or []) for i in (g.get("items") or [])]

    _json_call(base, f"/api/tasks/{t2['id']}", "DELETE")          # 软删 = 进回收站
    after = _json_call(base, "/api/team/board")[1] or {}
    recycled = next(
        (i for g in (after.get("groups") or []) for i in (g.get("items") or [])
         if i.get("task_id") == t2["id"]),
        {},
    )

    return {
        "团队默认视角是管理者": mgr.get("view") == "manager" and mgr.get("total") == 2,
        "团队按执行者分组（交替分配也合成一组）":
            names == sorted(names, key=str.casefold) and set(names) == {"小王", "小李"}
            and wang.get("count") == 1
            and (wang.get("items") or [{}])[0].get("status") == "blocked",
        "执行者视角只给自己的": bool(exe_items) and all(
            i.get("assignee") == "小王" for i in exe_items) and exe.get("total") == 1,
        "执行者视角没填名字就不猜": nobody.get("total") == 0 and nobody.get("groups") == []
            and "我是谁" in str(nobody.get("note")),
        "团队非法视角/状态被 400 拦下": bad_view == 400 and bad_status == 400,
        "任务进回收站后分配记录留着并标明": recycled.get("task_deleted") is True
            and recycled.get("task_missing") is False
            and recycled.get("task_title") == "真机自检·乙",
    }


def live_focus_mirror_checks(base: str) -> dict[str, bool]:
    """T-G20 真机自检：跨端同步专注的**数据那一半**（走真 HTTP，只碰临时库）。

    界面那一半（只读镜像、0 个按钮、10 秒轮询）在 DOM 探针里验；这里验"镜子后面那面墙"：
    ① `device_id` 真的落库、真能从 `/api/focus/active` 回传（不然界面判不出"谁开的"）；
    ② 另一台设备**只读**看几眼：会话不被改、投入不增加（镜像不重复记账的前提）；
    ③ 另一台设备想"我也开一个" → 被 400 拦（同一时间只允许一条）；
    ④ 结束之后 active 变 null（对面那台设备的镜像随之消失）、投入只记一笔。
    """
    mine = {"kind": "plain", "device_id": "cl-live-a"}
    started = _json_call(base, "/api/focus/start", "POST", mine)[1]
    active = _json_call(base, "/api/focus/active")[1] or {}
    peeks = [_json_call(base, "/api/focus/active")[1] or {} for _ in range(3)]
    during = _json_call(base, "/api/focus/today")[1] or {}
    parallel = _json_call(
        base, "/api/focus/start", "POST", {"kind": "plain", "device_id": "ph-live-b"}
    )[0]
    _json_call(
        base, f"/api/focus/{started['id']}/finish", "POST",
        {"duration_sec": 1500, "status": "finished"},
    )
    after = _json_call(base, "/api/focus/active")[1]
    done = _json_call(base, "/api/focus/today")[1] or {}
    # 空白 device_id 要在**干净状态**下验（否则会被"已有进行中的专注"抢先拦掉，验了个寂寞）
    blank = {"kind": "plain", "device_id": "   "}
    blank_sid = _json_call(base, "/api/focus/start", "POST", blank)[1]
    blank_active = _json_call(base, "/api/focus/active")[1] or {}
    _json_call(
        base, f"/api/focus/{blank_sid['id']}/finish", "POST",
        {"duration_sec": 0, "status": "abandoned"},
    )
    cfg = _json_call(base, "/api/config")[1] or {}
    return {
        "跨端专注：device_id 落库并回传": active.get("device_id") == "cl-live-a"
            and active.get("id") == started.get("id"),
        # T-G23：番茄钟时长必须由配置给（以前 `/api/config` 没暴露，界面只能 `||25`，
        # config.toml 里改过的值永远不生效）
        "番茄钟时长由 /api/config 给": cfg.get("pomodoro_minutes") == 25,
        "跨端专注：只读查询不改任何东西": all(
            p.get("id") == started.get("id") and p.get("device_id") == "cl-live-a" for p in peeks
        ) and during.get("focus_minutes") == 0,
        "跨端专注：并行开第二个被 400 拦下": parallel == 400,
        "跨端专注：空白 device_id 归一成 null": blank_active.get("device_id") is None
            and blank_active.get("id") == blank_sid.get("id"),
        "跨端专注：结束后镜像消失且只记一笔": after is None and done.get("focus_minutes") == 25.0,
    }


def _day(offset: int = 0) -> str:
    """相对今天第 N 天的日期（自检里造"排期日"用；别写死日期，否则过几天就假红）。"""
    return (date.today() + timedelta(days=offset)).isoformat()


def live_repeat_rhythm_checks(base: str) -> dict[str, bool]:
    """T-G25 真机自检：重复节奏投影在**真服务**上的行为（只碰临时库）。

    这一卡最容易做假的地方是"把没排过的日子也画出来"（周期是"每 N 天"，锚点会漂）——
    所以真跑一遍：只完成一轮，图里就**只有那一格**；再补一轮没做的，那是"排了没做"。
    """
    empty = _json_call(base, "/api/insights/repeat-rhythm")[1] or {}
    first = _json_call(
        base, "/api/tasks", "POST",
        {"title": "真机自检·背单词", "due_date": _day(-2), "repeat_days": 1, "is_myday": True},
    )[1]
    _json_call(base, f"/api/tasks/{first['id']}/complete", "POST")
    missed = _json_call(
        base, "/api/tasks", "POST",
        {"title": "真机自检·背单词", "due_date": _day(-1), "repeat_days": 1, "is_myday": True},
    )[1]
    got = _json_call(base, "/api/insights/repeat-rhythm")[1] or {}
    series = [s for s in (got.get("series") or []) if s.get("title") == "真机自检·背单词"]
    states = [c.get("state") for s in series for c in (s.get("cells") or [])]
    other = _json_call(
        base, "/api/tasks", "POST", {"title": "真机自检·不重复的活儿", "due_date": _day(-1)}
    )[1]
    after = _json_call(base, "/api/insights/repeat-rhythm")[1] or {}
    return {
        "重复节奏：空的时候是空表不是报错": empty.get("series") == [] and bool(empty.get("note")),
        "重复节奏：一轮做完 = 一格 done": states.count("done") == 1,
        "重复节奏：排了没做 = 一格 missed": states.count("missed") == 1,
        "重复节奏：只画真实排过的日子": len(states) == 2,
        "重复节奏：不重复的任务不进图": all(
            s.get("title") != "真机自检·不重复的活儿" for s in (after.get("series") or [])
        )
        and bool(other.get("id") and missed.get("id")),
        "重复节奏：窗口非法被 400 拦下": _json_call(
            base, "/api/insights/repeat-rhythm?days=0"
        )[0] == 400,
    }


def live_regrade_checks(base: str) -> dict[str, bool]:
    """T-G13 真机自检：复习「改判」在**真服务**上的行为（走真 HTTP，只碰临时库）。

    这一卡最容易骗过自己的地方是"投入重复计"和"改判后从错的起点重算" —— 所以真跑一遍：
    先记「记得」→ 改判成「忘了」→ 账本里**还是 1 张**、卡片的次数没有翻倍、
    流水里原事实留着（`review.undone` + `review.regraded`）。
    """
    rid = _json_call(base, "/api/review/items", "POST", {"title": "真机自检·改判"})[1]["id"]
    before = _json_call(base, f"/api/review/{rid}/review", "POST", {"feedback": "remember"})[1]
    listed = _json_call(base, "/api/review/today")[1] or []
    same = _json_call(base, f"/api/review/{rid}/regrade", "POST", {"feedback": "remember"})[0]
    got = _json_call(base, f"/api/review/{rid}/regrade", "POST", {"feedback": "forgot"})[1] or {}
    after = _json_call(base, "/api/review/today")[1] or []
    summary = _json_call(base, "/api/summary")[1] or {}
    # 这一路只回 `review.completed`（撤销/改判那两类事实没有 HTTP 出口，由单元测试直接查库兜着），
    # 但"原来那次没被抹掉"正好可以从这里看出来：改判后应当是**两条** completed。
    facts = _json_call(base, f"/api/review/{rid}/facts")[1] or []
    never = _json_call(base, "/api/review/items", "POST", {"title": "真机自检·没复习过"})[1]
    refuse = _json_call(
        base, f"/api/review/{never['id']}/regrade", "POST", {"feedback": "fuzzy"}
    )[0]
    missing = _json_call(base, "/api/review/nope/regrade", "POST", {"feedback": "fuzzy"})[0]
    meta = _json_call(base, "/api/review/meta")[1] or {}
    return {
        "复习三档中文由后端给": [r.get("value") for r in (meta.get("ratings") or [])]
            == ["remember", "fuzzy", "forgot"],
        "今天复习过的带档位": any(
            i.get("id") == rid and i.get("feedback_label") == "记得" for i in listed
        ),
        "改判真的改了那一档": got.get("regraded_from") == "remember"
            and got.get("regraded_to") == "forgot"
            and any(i.get("id") == rid and i.get("feedback_label") == "忘了" for i in after),
        "改判不改排期起点（次数不翻倍）": got.get("reps") == before.get("reps") == 1,
        "改判不重复计投入": summary.get("review_count") == 1,
        "改判留痕（原来那次没被抹掉）": len(facts) == 2,
        "改成同一档被 400 拦下": same == 400,
        "没复习过就改判被 400 拦下": refuse == 400,
        "改判不存在的卡 404": missing == 404,
    }


def live_notify_checks(base: str) -> dict[str, bool]:
    """T-G14 真机自检：学校通知的合作接口在**真服务**上的行为（只碰临时库）。

    "未接入"与"参数错"必须**分得开**（403 vs 400）：调用方是用户自己写的脚本，
    这两种情况的处理方式完全不同（一个去设置页点开关，一个改脚本）。
    另外验去重真的靠库约束（重复投递不产生第二行）、转任务走的是普通任务路径。
    """
    off = _json_call(base, "/api/settings/notify")[1] or {}
    off_post = _json_call(
        base, "/api/notify/school", "POST", {"source": "真机自检", "title": "未接入时投递"}
    )
    cross = _json_call(
        base, "/api/notify/school", "POST", {"source": "x", "title": "y"},
        headers={"Origin": "https://evil.example"},
    )[0]
    _json_call(base, "/api/settings/notify", "PUT", {"enabled": True})
    bad = _json_call(base, "/api/notify/school", "POST", {"title": "少了来源"})[0]
    first = _json_call(base, "/api/notify/school", "POST", {
        "source": "教务处网站", "title": "真机自检·期中考试安排", "external_id": "LIVE-1",
        "url": "https://example.edu/x", "due_date": "2030-01-08", "批次": "第 1 批",
    })[1] or {}
    again = _json_call(base, "/api/notify/school", "POST", {
        "source": "教务处网站", "title": "真机自检·期中考试安排", "external_id": "LIVE-1",
    })[1] or {}
    listing = _json_call(base, "/api/notify/school")[1] or {}
    task = _json_call(
        base, f"/api/notify/school/{first.get('id')}/to-task", "POST", {"is_myday": True}
    )[1] or {}
    made = _json_call(base, f"/api/tasks/{task.get('task_id')}")[1] or {}
    second = _json_call(base, "/api/notify/school", "POST", {
        "source": "班级群", "title": "真机自检·可以忽略的那条",
    })[1] or {}
    ignored = _json_call(
        base, f"/api/notify/school/{second.get('id')}/ignore", "POST", {"ignored": True}
    )[1] or {}
    converted_ignore = _json_call(
        base, f"/api/notify/school/{first.get('id')}/ignore", "POST", {"ignored": True}
    )[0]
    export = _json_call(base, "/api/sync/export", "POST", {})[1] or {}
    return {
        "学校通知默认关且投递 403": off.get("enabled") is False and off_post[0] == 403,
        "学校通知跨站投递被拦": cross == 403,
        "学校通知参数错是 400（与未接入分得开）": bad == 400,
        "学校通知能收下一条（带来源与扩展字段）": first.get("created") is True
            and (first.get("notice") or {}).get("source") == "教务处网站"
            and (first.get("notice") or {}).get("extra") == {"批次": "第 1 批"},
        "学校通知重复投递不产生第二行": again.get("duplicate") is True
            and again.get("id") == first.get("id")
            and (again.get("notice") or {}).get("url") == "https://example.edu/x",
        "学校通知收件箱看得到": any(
            i.get("id") == first.get("id") for i in (listing.get("items") or [])
        ),
        "学校通知转任务是普通任务（带来源备注与截止）": task.get("created") is True
            and made.get("title") == "真机自检·期中考试安排"
            and made.get("due_date") == "2030-01-08"
            and "来自学校通知" in str(made.get("note") or ""),
        "学校通知可忽略、已转任务的不许忽略": ignored.get("status") == "ignored"
            and converted_ignore == 400,
        "学校通知不进同步包（是收件箱，不是你的数据）":
            "school_notices" not in (export.get("tables") or {}),
    }


def live_phone_view_checks(base: str) -> dict[str, bool]:
    """T-G16 真机自检：手机要"**看**"的那几份清单在真服务上答得上来，而且**口径由后端算好**。

    为什么强调后半句：手机上不做计算（没有库、没有领域层），它显示什么就是后端给什么 ——
    所以"逾期几天""该不该提醒"必须由接口算完，不能让界面自己拿今天去减。
    这里建一条**早就过期还带提醒**的任务，看这两样是不是都算好了。
    """
    made = _json_call(base, "/api/tasks", "POST", {
        "title": "真机自检·逾期与提醒", "due_date": "2020-01-01",
        "remind_at": "2020-01-01T08:00", "is_myday": True,
    })[1] or {}
    mydays = _json_call(base, "/api/mydays")[1]
    overdue = _json_call(base, "/api/overdue")[1]
    reminders = _json_call(base, "/api/reminders/due")[1]
    review = _json_call(base, "/api/review/due")[1]
    summary = _json_call(base, "/api/summary")[1] or {}
    got = next((x for x in (overdue or []) if x.get("id") == made.get("id")), {})
    rem = next((x for x in (reminders or []) if x.get("id") == made.get("id")), {})
    return {
        "手机要看的四份清单在真服务上都答得上来": all(
            isinstance(x, list) for x in (mydays, overdue, reminders, review)
        ) and isinstance(summary, dict),
        "手机看的口径由后端算好（逾期天数 / 提醒状态）": got.get("overdue_days", 0) > 0
            and rem.get("reminder_state") == "over" and bool(rem.get("remind_at")),
        "摘要字段够拼一句话（手机不自己算）":
            {"debt_count", "invest_hours", "review_count"} <= set(summary),
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
    # T-G8b：删除是**可选项** —— 先确认默认不删，再确认勾上能删（真服务上走完整接口）
    victim = _json_call(base, "/api/tasks", "POST", {"title": "自检·会被对方删掉的"})[1] or {}
    del_pack = tmp / "del.json"
    del_pack.write_text(json.dumps({
        "format": "timeflow-sync", "format_version": 1,
        "schema_version": 17, "device_id": "another-machine-9",
        "created_at": "2026-09-23T10:00:00", "tables": {}, "counts": {},
        # 删除时刻取**远期**：这条包要证明"勾上就删"，而判据是"本地行有没有比删除时刻更新"
        # —— 写一个固定日期会变成**定时炸弹**（本用例第一版写的 2026-09-23T10:00:00，
        #   当天 10:00 一过，本地行就"比删除更新"→ 规则正确地不删 → 用例开始红）。
        "tombstones": [{"entity": "tasks", "entity_id": victim.get("id"),
                        "deleted_at": "2099-01-01T00:00:00"}],
    }, ensure_ascii=False), encoding="utf-8")
    keep = _json_call(base, "/api/sync/import", "POST", {"path": str(del_pack)})
    after_keep = _json_call(base, "/api/tasks")[1] or []
    gone = _json_call(base, "/api/sync/import", "POST",
                      {"path": str(del_pack), "apply_deletions": True})
    after_gone = _json_call(base, "/api/tasks")[1] or []
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
        # T-G8b：默认不删 / 勾上才删（同一个包、同一个接口，只有那个开关不同）
        "删除默认不生效": keep[0] == 200
        and (keep[1] or {}).get("totals", {}).get("deleted", 0) == 0
        and any(t["id"] == victim.get("id") for t in after_keep),
        "勾上才真的删": gone[0] == 200
        and (gone[1] or {}).get("totals", {}).get("deleted", 0) == 1
        and not any(t["id"] == victim.get("id") for t in after_gone),
        "删了也留痕": bool((gone[1] or {}).get("conflicts"))
        and any("本地也删了" in str(c.get("result")) for c in (gone[1] or {}).get("conflicts", [])),
    }


def _phone_pack(tmp: Path, name: str = "phone.json") -> Path | None:
    """跑 `tools/phone_check.mjs` 造一份**真手机包**（用的是页面里同一个 `offline.js`）。

    没有 node、或造包脚本失败 → 返回 None（调用方如实报"未验证"，不谎报通过）。
    """
    node = shutil.which("node")
    if not node:
        return None
    pack = tmp / name
    proc = subprocess.run(
        [str(node), str(PHONE_CHECK), str(pack)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, cwd=str(ROOT),
    )
    return pack if proc.returncode == 0 and pack.is_file() else None


def live_offline_checks(base: str, tmp: Path) -> dict[str, bool]:
    """T-G10 真机自检：**手机侧的那份真包**在真服务上走一遍导入（跨端场景 ① 的后半程）。

    链路的完整形态是"手机的浏览器 → 导出文件 → 电脑导入"，本环境没有浏览器，
    但中间那两个文件都是真的：这里用 `tools/phone_check.mjs` 跑**页面用的同一个 offline.js**
    造一份包，再通过真 HTTP 打 `/api/sync/import`。于是"手机造的包电脑吃不下"这类错这里就能拦住。
    """
    checks: dict[str, bool] = {}
    offline_js = urllib.request.urlopen(f"{base}/offline.js", timeout=10).read().decode("utf-8")
    sw = urllib.request.urlopen(f"{base}/sw.js", timeout=10).read().decode("utf-8")
    html = urllib.request.urlopen(f"{base}/", timeout=10).read().decode("utf-8")
    checks["离线引擎真的发得出来"] = "TFOffline" in offline_js and "timeflow-sync" in offline_js
    checks["页面引了离线引擎"] = '<script src="/offline.js">' in html
    checks["离线页在导航里可达"] = 'data-view="offline"' in html
    checks["service worker 预缓存离线引擎"] = '"/offline.js"' in sw and 'timeflow-v2' in sw
    pack = _phone_pack(tmp)
    checks["手机侧造包自检通过"] = pack is not None
    if pack is None:
        return checks
    first = _json_call(base, "/api/sync/import", "POST", {"path": str(pack)})
    tasks = _json_call(base, "/api/tasks")[1] or []
    second = _json_call(base, "/api/sync/import", "POST", {"path": str(pack)})
    totals = (first[1] or {}).get("totals", {}) if first[0] == 200 else {}
    checks["手机包能在真服务上导入"] = first[0] == 200 and totals.get("inserted", 0) >= 5
    checks["手机记的任务真的进了库"] = any(t.get("title") == "手机上记的" for t in tasks)
    checks["再导一次是幂等的（不重复计数）"] = second[0] == 200 and (
        (second[1] or {}).get("totals", {}).get("inserted", 0) == 0
    )
    checks["导入后账本还答得上来"] = _json_call(base, "/api/summary")[0] == 200
    src_dev = str((first[1] or {}).get("from_device", ""))
    checks["设备号写进了包（认得出来源）"] = src_dev.startswith("ph-")
    return checks


def _lan_json(base: str, path: str, method: str = "GET",
              payload: dict | None = None, headers: dict | None = None, timeout: int = 3):
    """打局域网地址用的 HTTP（**绕开系统代理** —— 否则 192.168.x 会被丢给代理，白测一场）。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{base}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    def _body(raw: bytes) -> object:
        try:
            return json.loads(raw.decode("utf-8") or "null")
        except (ValueError, UnicodeDecodeError):
            return None      # 静态壳回的是 HTML —— 这一路只看状态码

    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, _body(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, _body(e.read())
    except (urllib.error.URLError, OSError):
        return 0, None      # 连不上（防火墙 / 没有局域网地址）—— 由调用方决定怎么报


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def live_lan_checks(tmp: Path, port: int | None = None) -> dict[str, bool]:
    """T-G10b 真机自检：**真起一个绑 0.0.0.0 的服务**，再从本机的**局域网地址**访问它。

    本环境没有第二台设备，所以拿"本机局域网 IP"当"别人" —— 这已经够了：
    服务看到的**来源地址不是回环**，走的就是手机那条路（静态壳能开 → 数据要配对码 →
    配对后能读 → 配对码不会通过局域网漏出去）。

    ★ T-G47：端口改成**自动挑空闲的**（原来钉死 8531）。两个理由，都不是洁癖：
      ① 8531 正好是**渲染层默认的服务端口** —— 门禁串行跑时看不出来，一旦把两层并起来跑
         就是"两个服务抢同一个端口"，而表现为**随机失败**（最难查的那种）；
      ② 用户机器上 8531 被别的东西占着时，这里会假红。
    端口下面每一处都从同一个变量取（`lan.local_addresses(port)` 也是），所以换端口不影响断言。

    连不上自己的局域网地址（没连网 / 防火墙拦了）→ 打印 `[SKIP]` **明说跳过**，
    不谎报"通过"（`checks` 里不加条目，退出码不受影响）。
    """
    from timeflow.core import lan as lan_mod

    port = port or _free_port()
    app = create_app(str(tmp / "lan_live.db"), allow_lan=True, port=port)
    server = uvicorn.Server(
        uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")  # noqa: S104
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)

    local = f"http://127.0.0.1:{port}"
    code = (_json_call(local, "/api/settings/lan")[1] or {}).get("code") or ""
    addrs = [a for a in lan_mod.local_addresses(port) if "127." not in a]
    reachable = ""
    for addr in addrs:
        if _lan_json(addr, "/")[0] == 200:
            reachable = addr
            break
    if not reachable:
        print(f"  [SKIP] 局域网真机检查：这台机器连不上自己的局域网地址"
              f"（{addrs or '没查到地址'}）—— 本机防火墙/网络原因，未验证（不算通过）")
        server.should_exit = True
        thread.join(timeout=10)
        return {}

    shell = _lan_json(reachable, "/")[0]
    blocked_code, blocked = _lan_json(reachable, "/api/health")
    pair_bad = _lan_json(reachable, "/api/lan/pair", "POST", {"code": "000000"})[0]
    paired = _lan_json(reachable, "/api/lan/pair", "POST", {"code": code})[0]
    auth = {"X-Timeflow-Pair": code}
    ok_code, health = _lan_json(reachable, "/api/health", headers=auth)
    seen_code = (_lan_json(reachable, "/api/settings/lan", headers=auth)[1] or {}).get("code")
    local_ok = _json_call(local, "/api/health")[0] == 200   # 本机自己不受影响（关服务之前问）
    # 本机自检（T-G10c）：服务真的绑在 0.0.0.0 上时，它应当报"本机可达"
    _sc_code, self_check = _json_call(local, "/api/lan/selfcheck", "POST", {})

    # 手机**直接上传**同步包（G 批 · T-G15）：走的就是手机那条路 —— 包里带上内容（不是路径），
    # 从局域网地址打过来，带着配对码。没配对必须传不进来（这是那道门的意义）。
    upload: dict[str, bool] = {}
    pack_path = _phone_pack(tmp, "phone-lan.json")
    if pack_path is None:
        print("  [SKIP] 手机直传：造不出手机包（缺 node？）—— 未验证（不算通过）")
    else:
        body = {"pack": json.loads(pack_path.read_text(encoding="utf-8"))}
        nopair = _lan_json(reachable, "/api/sync/import", "POST", body)
        up = _lan_json(reachable, "/api/sync/import", "POST", body, headers=auth)
        again = _lan_json(reachable, "/api/sync/import", "POST", body, headers=auth)
        up_totals = (up[1] or {}).get("totals", {}) if up[0] == 200 else {}
        again_totals = (again[1] or {}).get("totals", {}) if again[0] == 200 else {}
        upload = {
            "手机直传：没配对传不进来（401）": nopair[0] == 401,
            "手机直传：配对后能把包传上来并合并": up[0] == 200
            and up_totals.get("inserted", 0) >= 5,
            "手机直传：同一份包再传一次是幂等的": again[0] == 200
            and again_totals.get("inserted", 0) == 0,
            "手机直传：认得出来源设备（ph-）":
                str((up[1] or {}).get("from_device", "")).startswith("ph-"),
        }
    server.should_exit = True
    thread.join(timeout=10)

    detail = (blocked or {}).get("detail", "") if isinstance(blocked, dict) else ""
    sc = self_check if isinstance(self_check, dict) else {}
    return {
        "局域网：静态壳能打开（否则手机没处输配对码）": shell == 200,
        "局域网：没配对读不到数据（401 + 原话）": blocked_code == 401 and "配对码" in str(detail),
        "局域网：错码被拒": pair_bad == 401,
        "局域网：对码配对成功": paired == 200,
        "局域网：配对后能读数据": ok_code == 200 and isinstance(health, dict),
        "局域网：配对码不会通过局域网漏出去": seen_code == "",
        "局域网：本机自己不受影响": local_ok,
        "局域网：自检说得出本机可达": sc.get("self_reachable") is True
        and bool(sc.get("addresses")),
        "局域网：自检把校园网/热点写进排查顺序": "校园网" in str(sc.get("hint", ""))
        and "移动热点" in str(sc.get("hint", "")),
        **upload,
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
        "样式可取到": "--panel-2" in css,
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
        # ★ 2026-09-28（T-G177）：原先只断 `'[data-theme="dark"]' in css` ——
        # 只验选择器**字符串**在不在，块里有没有令牌根本不看（清空暗色块照样绿）。
        # 改成"真暗色块里必需令牌都在"，与存在性层同一份集合。
        "暗色令牌可取到": all(tok in dark_declared_tokens(css) for tok in DARK_REQUIRED_TOKENS),
        # 智能视图可达（T-B3）：左栏 / 全部任务页 / 设置页都有入口 ——
        # 手机端（≤640px）左栏导航被 CSS 隐藏，所以不能只靠左栏（否则手机上直接进不去）。
        "智能视图可达": all(
            f'data-view="{v}"' in _rail_nav(html) and f'data-view="{v}"' in html
            for v in ("important", "planned", "flagged")
        ) and html.count("smartViewNavHTML(") >= 3,
        # 团队视角页（T-G12 / OP-33）：宽屏走左栏、手机走底栏（≤1023px 左栏被 CSS 藏起来）
        # —— 只挂一边就等于有一类设备进不去，所以两边都要有。
        "团队视角可达（左栏 + 手机底栏）":
            'data-view="team"' in _rail_nav(html)
            and 'data-view="team"' in html.split('class="bottom-nav"', 1)[1].split("</nav>", 1)[0],
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
    checks.update(live_team_checks(base))
    checks.update(live_repeat_rhythm_checks(base))
    checks.update(live_focus_mirror_checks(base))
    checks.update(live_regrade_checks(base))
    checks.update(live_notify_checks(base))
    checks.update(live_phone_view_checks(base))
    checks.update(live_sync_checks(base, tmp))
    checks.update(live_offline_checks(base, tmp))
    checks.update(live_lan_checks(tmp))
    for name, passed in checks.items():
        print(f"[{'OK ' if passed else 'FAIL'}] {name}")
    server.should_exit = True
    thread.join(timeout=10)
    return 0 if ok and all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
