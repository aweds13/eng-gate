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


def test_three_column_shell_exists() -> None:
    """R3 护栏（SR-NF4）：三栏骨架必须留在这里 —— 左导航 / 中列表 / 右详情 + 计时器常驻。

    实现要点：布局靠 CSS 网格（宽屏三栏、窄屏折回单列），
    计时器渲染在右栏 `#focusRail`（任何视图都在），详情在 `#detailRail`（点了「详情」才出现）。
    这条护栏防的是「重构把右栏或计时器常驻悄悄弄丢」——那会退化成单列 + 详情靠弹窗。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    css = WEB_CSS.read_text(encoding="utf-8")

    # ① 壳里的三个区域（外加窄屏底部 Tab 仍在）
    for needle in ('class="shell"', 'class="rail"', 'id="main"', 'class="sidebar"',
                   'id="focusRail"', 'id="detailRail"', 'class="bottom-nav"'):
        assert needle in html, f"三栏骨架缺少 {needle}"

    # ② 右栏计时器常驻：`render` 每次都刷右栏，且计时器只在这里走
    assert "function paintRail(mySeq)" in html
    assert "paintRail(mySeq)" in html.split("async function render(")[1][:600], (
        "render 必须每次都刷右栏（否则切视图后计时器消失）"
    )
    assert "function renderActive(el,active)" in html
    assert 'id="clock"' in html.split("function renderActive")[1][:900]
    assert "focusTimer=setInterval(tick,1000)" in html

    # ③ 详情面板 + 渐进聚焦：默认空、点「详情」才填、切视图清空
    assert "let detailTaskId=null" in html
    assert '"task-detail"' in html and 'data-action="task-detail"' in html
    assert "if(!detailTaskId){box.innerHTML='';return}" in html
    assert "detailTaskId=null" in html.split("function view(")[1][:300], (
        "切视图应清掉右栏详情（渐进聚焦：不把上一个视图的详情留在屏上）"
    )

    # ④ CSS 侧：宽屏三栏、窄屏折回单列，且两个断点**互斥**（重叠过一次：980 与 1023）
    assert "@media (min-width: 980px)" in css
    assert "@media (max-width: 979px)" in css
    assert "flex: 0 0 168px" in css and "flex: 0 1 820px" in css, "左栏/中列宽度约束不见了"


def test_main_stays_bounded_and_padded_on_wide_screens() -> None:
    """布局回归守卫（用户报「UI 是不是修崩了」后补，2026-09-18）。

    三栏版把 `main` 交给网格/弹性布局后，**基础规则（写在媒体块之后）会把中列重新拉成整列宽、
    并清掉媒体块里设的上边距** —— 卡片被拉到 1500px+、内容顶到视口顶部，看着就像"崩了"。
    所以：宽屏媒体块里的 `main` 必须自带宽度上限与完整 padding，不能只写定位。
    """
    css = WEB_CSS.read_text(encoding="utf-8")
    wide = css.split("@media (min-width: 980px) {", 1)[1].split("\n}", 1)[0]
    main_rule = [ln for ln in wide.splitlines() if ln.strip().startswith("main {")]
    assert main_rule, "宽屏媒体块里应有 main 规则"
    rule = main_rule[0]
    for need in ("max-width: 820px", "padding:", "min-width: 0"):
        assert need in rule, f"宽屏 main 规则缺 {need}（会被后面的基础规则覆盖）→ {rule.strip()}"
    # 中列同时受"宽度上限"与"自身 max-width"约束，且整体居中
    assert "justify-content: center" in wide
    # 窄屏才需要给底部固定 Tab 留 90px；宽屏不该白留一条
    assert "@media (min-width: 980px)" in css and "padding: 0 24px" in wide


def test_focus_timer_has_single_owner() -> None:
    """R3 护栏：计时器只有右栏一个「主人」（两处计时器会互相打脸）。

    专注页在计时态下只说明「去哪里结束」，不再自己渲染 `#clock`。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    assert html.count('id="clock"') == 1, "页面上只允许有一个计时器读数"
    focus_view = html.split("async function renderFocus(")[1].split("async function startFocus(")[0]
    assert 'id="clock"' not in focus_view, "专注页不应再自渲染计时器（统一交给右栏）"


def test_three_column_shell_exists_in_served_page(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """三栏骨架要真的出现在服务端返回的页面里（不只是源文件里写着）。"""
    html = _html(tmp_path)
    for needle in ('id="focusRail"', 'id="detailRail"', 'class="rail"', 'class="sidebar"'):
        assert needle in html, f"页面缺少 {needle}"


def test_inputs_cannot_cover_submit_buttons() -> None:
    """反馈修（2026-09-18 用户实测）：新增行的「添加」按钮曾被挤出去遮住。

    根因：标题输入 `flex:1` + 日期框/按钮不收缩 → 一行总宽超出容器时按钮溢出被裁。
    约定：新增行允许换行、输入框可收缩且有最小宽度、**按钮永不收缩**；
    表单块 .form/.field 同理（学业页那一堆输入框靠它不再挤成一条缝）。
    """
    css = WEB_CSS.read_text(encoding="utf-8")
    new_block = css.split(".new {", 1)[1].split("/* ---------- 表单块", 1)[0]
    assert "flex-wrap: wrap" in new_block, "新增行必须允许换行"
    assert "flex: 1 1 220px" in new_block, "标题输入应有最小宽度（220px）"
    assert "min-width: 0" in new_block, "输入框必须可收缩，否则会把按钮挤出去"
    assert ".new button { flex: none }" in new_block, "按钮不能被压缩"
    assert ".field" in css and ".form {" in css, "学业/设置这类多字段表单应用表单块"


def test_date_fields_default_to_today() -> None:
    """用户要求：新增任务的日期默认就是**今天**，想看别的日期再点进去改。

    边界要说清：`due_date`（截止日）与 `is_myday`（是否进今天清单）是两件事 ——
    日期默认今天不等于"自动进今天"，所以「加入今天」勾选保留。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    assert "function todayISO(" in html, "应有本地时区的今天（不能用 toISOString 的 UTC 值）"
    assert "function defaultDateFields(" in html
    assert "defaultDateFields(['newDue'])" in html, "今日页的截止日应默认今天"
    assert "defaultDateFields(['allDue'])" in html, "全部任务页的截止日也应默认今天"
    assert "newMyDay" in html, "「加入今天」是独立维度，必须保留"
    assert "截止日（默认今天，可改）" in html


def test_check_circle_is_a_real_circle() -> None:
    """用户要求：完成圈改成**正圆**（各浏览器默认按钮外观会把它压成椭圆）。"""
    css = WEB_CSS.read_text(encoding="utf-8")
    check = css.split(".check {", 1)[1].split("}", 1)[0]
    for need in ("appearance: none", "width: 22px", "height: 22px", "min-width: 22px",
                 "border-radius: 999px", "padding: 0"):
        assert need in check, f"完成圈缺少 {need}（会变椭圆/被压扁）→ {check.strip()}"


def test_task_cards_show_completion_state() -> None:
    """用户要求：任务卡上直接看出「完成于某时/未完成」，时间要是人话。"""
    html = WEB_INDEX.read_text(encoding="utf-8")
    assert "function humanTime(" in html
    assert '完成于 ${humanTime(t.updated_at)}' in html
    assert '>未完成<' in html
    assert "年${m[2]}月${m[3]}日" in html, "时间应显示成「2026年09月18日 17:31」"


def test_task_detail_panel_shows_readable_history() -> None:
    """用户要求：点任务卡进详情，能看到这个任务的历史（完成时间等），不是一串 ISO 串；

    并（F1 段1 起）要能看到/添加**步骤（子任务）**与所属分组。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    detail = html.split("function renderDetail(el,t,facts,kids){", 1)[1].split("\n}", 1)[0]
    for need in ("humanTime(f.occurred_at)", "建于 ", "更新于 ", "步骤（子任务）", "subtaskTitle"):
        assert need in detail, f"详情面板缺少 {need}"
    assert "任务详情" in detail and "记录（最近" in detail
    # 选中态：列表里那张卡要有标记，否则不知道右栏在看哪个
    css = WEB_CSS.read_text(encoding="utf-8")
    assert "t.id===detailTaskId?'selected'" in html and ".card.selected" in css
    # 详情面板要取子任务列表（否则"步骤"永远是空的）
    assert "/subtasks`" in html


def test_task_note_is_editable_in_detail_only() -> None:
    """T-B1（SR-F1.4 备注）：详情面板能读能写，**列表卡片不显示**（渐进聚焦）。"""
    html = WEB_INDEX.read_text(encoding="utf-8")
    edit = html.split("function editForm(t){", 1)[1].split("\n}", 1)[0]
    assert 'id="editNote"' in edit, "编辑态缺少备注输入（备注就只能靠 API 写了）"
    save = html.split("async function saveTaskEdit(){", 1)[1].split("\n}", 1)[0]
    assert "editNote" in save and "note:" in save, "保存时没把备注带上"
    detail = html.split("function renderDetail(el,t,facts,kids){", 1)[1].split("\n}", 1)[0]
    assert "t.note" in detail, "详情面板没有显示备注"
    card = html.split("function taskCard(t,isOverdue){", 1)[1].split("\n}", 1)[0]
    assert "note" not in card, "备注不该出现在列表卡片里（渐进聚焦）"


def test_habit_count_shown_alongside_investment() -> None:
    """T-C1（用户口径）：习惯**只报次数**、与投入并排显示，**不折算成小时**；习惯页指路"手动补记"。"""
    html = WEB_INDEX.read_text(encoding="utf-8")
    summary = html.split("function summaryLine(s){", 1)[1].split("\n}", 1)[0]
    assert "s.habit_count" in summary and "习惯 ${s.habit_count} 次" in summary
    week = html.split("function weekCard(w){", 1)[1].split("\n}", 1)[0]
    assert "w.habits_done" in week and "习惯 ${w.habits_done} 次" in week
    # 不折算：习惯次数绝不能进"投入小时"那个字段（invest_hours 只由专注构成）
    assert "habit_count}h" not in html and "habits_done}h" not in html
    habit_view = html.split("async function renderHabit(", 1)[1]
    habit_view = habit_view.split("async function addHabit(", 1)[0]
    assert "手动投入" in habit_view, "习惯页要指路「想计入投入就手动补记真实分钟」"


def test_reminder_ui_and_notify_switch() -> None:
    """T-B5（SR-F1.4 提醒）：能设、能标出来；通知通道（B′ 计划任务）有开关且**默认关**。

    设置页不许谎报：要写明会注册 Windows 计划任务、以及"注销/关机不响"这条真实边界。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    edit = html.split("function editForm(t){", 1)[1].split("\n}", 1)[0]
    assert 'id="editRemind"' in edit and 'type="datetime-local"' in edit, "编辑态不能设提醒"
    save = html.split("async function saveTaskEdit(){", 1)[1].split("\n}", 1)[0]
    assert "remind_at" in save, "保存时没把提醒带上"
    # 卡片与详情都要标出来（口径来自后端 reminder_state，前端只翻译成人话）
    card = html.split("function taskCard(t,isOverdue){", 1)[1].split("\n}", 1)[0]
    assert "remindBadge(t)" in card, "任务卡片没有提醒标记"
    assert "REMIND_LABEL" in html and "function remindBadge(" in html
    # 今日页「该提醒了」区（不开通知也能用）
    today = html.split("async function renderToday(m){", 1)[1].split("\n}", 1)[0]
    assert "/api/reminders/due" in today and "该提醒了" in today
    # 设置页：真的开关 + 试一下 + 如实边界（不再写"通道尚未接入"）
    setting = html.split("async function renderSetting(", 1)[1]
    setting = setting.split("async function setAttachMode(", 1)[0]
    assert 'id="set-remind"' in setting, "设置页缺少提醒一节"
    assert "/api/settings/reminder" in setting, "设置页没读通知通道状态"
    assert 'data-action="set-remind-notify"' in setting, "缺少到点通知开关"
    assert 'data-action="remind-test"' in setting, "缺少「试一下」按钮"
    assert 'data-action="set-remind-style"' in setting, "缺少「提醒方式」（闹钟式/温和）"
    assert "function setRemindStyle(" in html
    assert "留在屏幕上" in setting, "必须写清闹钟式的效果（留在屏幕上 + 循环响铃）"
    assert "默认关闭" in setting, "必须标出默认是关的"
    # T-B5c 响铃收口（用户实测"电脑一直在响"后加的）：界面上必须能停，且写清"会一直响到你关掉"
    assert 'data-action="remind-stop"' in setting, "缺少「停止响铃」按钮"
    assert "function stopRinging(" in html and "/api/reminders/stop" in html
    assert "一直响到你把它关掉" in setting, "必须写清闹钟式会一直响到被关掉"
    assert "注销/关机时不响" in setting, "必须写明真实边界（不谎报）"
    assert "计划任务" in setting
    assert 'data-target="set-remind"' in html, "常用区没有提醒快捷入口"
    for fn in ("function setRemindNotify(", "function testRemindNotify("):
        assert fn in html, f"缺 {fn}"


def test_attach_open_flow_is_wired_and_never_silent() -> None:
    """T-B4（SR-F1.4 附件 / SR-F5.3 跳转要求）：能挂、能点开、**打不开必出声**。

    规则在后端（`core/attach.py`），前端只负责把三种结果分开处理：
    网址→新标签、本机动作→已执行、其余→**复制路径 + 提示**（不许静默失败）。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    # ① 任务详情：附件区（列表 + 添加 + 打开 + 删除）
    detail = html.split("function renderDetail(el,t,facts,kids){", 1)[1].split("\n}", 1)[0]
    assert "taskAttachHTML(t)" in detail, "详情面板没有附件区"
    for needle in ("function attachRowsHTML(", "function taskAttachHTML(",
                   "function addAttachment(", "function removeAttachment("):
        assert needle in html, f"缺 {needle}"
    # 动作是动态生成的（行模板里带 ${delAction}），所以这里断言 ACTIONS 注册表
    for action in ("attach-open", "attach-add", "attach-del"):
        assert f"'{action}':" in html, f"ACTIONS 里缺 {action}"
    assert "attachRowsHTML(t.attach,'attach-del',t.id)" in html, "附件行没有绑定删除动作"
    # ② 卡片上有附件数徽标（列表不展开内容，渐进聚焦）
    card = html.split("function taskCard(t,isOverdue){", 1)[1].split("\n}", 1)[0]
    assert "附件 ${t.attach.length}" in card, "任务卡片没有附件计数"
    # ③ 打开动作：三种分支齐全 + 复制兜底（不许静默）
    opener = html.split("async function openAttach(", 1)[1].split("\n}", 1)[0]
    for needle in ("action==='browser'", "r.executed", "copyText(", "toast("):
        assert needle in opener, f"openAttach 缺少 {needle}"
    assert "/api/attach/open" in html
    # ④ 设置页：三种打开方式 + 白名单维护 + 常用区快捷入口
    setting = html.split("async function renderSetting(", 1)[1]
    assert 'id="set-attach"' in setting and "set-attach-mode" in setting
    assert "wl-add" in setting and "wl-del" in setting
    assert 'data-target="set-attach"' in html, "常用区没有快捷入口"
    assert "/api/settings/attach" in html
    # ⑤ 学业：考核项列表也能挂要求链接（同一个字段、同一套规则）
    academic = html.split("async function renderAcademic(", 1)[1]
    academic = academic.split("async function addAssessment(", 1)[0]
    assert "assessmentAttachHTML(" in academic and "考核项" in academic
    assert 'data-action="assessment-attach-add"' in html
    assert "function addAssessmentAttachment(" in html
    assert "function removeAssessmentAttachment(" in html


def test_smart_views_are_reachable_at_every_breakpoint() -> None:
    """T-B3（SR-F1.3）：三个智能视图要真的进得去 —— 左栏、全部任务页、设置页都有入口。

    为什么强调"处处"：手机端（≤640px）CSS 把 `.rail nav` 隐藏了，只留底部 Tab；
    只把入口放在左栏 = 手机上根本进不去（这正是"规格有、界面没有"的老毛病）。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    rail_nav = html.split('class="rail"', 1)[1].split("</nav>", 1)[0]
    views_match = re.search(r"const VIEWS=\[([^\]]*)\]", html)
    assert views_match is not None
    views = {v.strip().strip("'") for v in views_match.group(1).split(",")}
    for name in ("important", "planned", "flagged"):
        assert name in views, f"VIEWS 白名单缺少 {name}（render 会直接拒绝渲染）"
        assert f'data-view="{name}"' in rail_nav, f"左栏缺少 {name} 入口"
        assert f'data-view="{name}"' in html, f"页面里缺少 {name} 入口"
    # 互跳行挂在「全部任务」页与各智能视图上（手机端靠它 + 设置页入口）
    assert "function smartViewNavHTML(" in html
    assert html.count("smartViewNavHTML(") >= 3
    # 渲染分发要接上（否则点了白屏）
    assert "renderSmart(m,name)" in html
    setting = html.split("async function renderSetting(", 1)[1]
    assert 'data-view="flagged"' in setting, "设置页「入口」缺少智能视图"
    # 卡片上的标记开关 + 标记徽标
    assert "function flagBadge(" in html and "flagBadge(t)" in html
    assert 'data-action="task-flag"' in html and "function toggleFlag(" in html
    assert "/flag`" in html, "前端没调用 POST /api/tasks/{id}/flag"


def test_task_priority_badge_and_edit() -> None:
    """T-B2（SR-F1.2）：卡片有优先级色标、编辑态能改优先级，颜色只住 app.css。"""
    html = WEB_INDEX.read_text(encoding="utf-8")
    assert "function prioBadge(" in html, "缺少优先级色标组件"
    card = html.split("function taskCard(t,isOverdue){", 1)[1].split("\n}", 1)[0]
    assert "prioBadge(t.priority)" in card, "任务卡片没显示优先级"
    edit = html.split("function editForm(t){", 1)[1].split("\n}", 1)[0]
    assert 'id="editPriority"' in edit, "编辑态不能改优先级"
    save = html.split("async function saveTaskEdit(){", 1)[1].split("\n}", 1)[0]
    assert "editPriority" in save and "priority:" in save, "保存时没把优先级带上"
    css = WEB_CSS.read_text(encoding="utf-8")
    for needle in (".prio {", ".prio.high", ".prio.mid", ".prio.low"):
        assert needle in css, f"app.css 缺少优先级样式 {needle}"


def test_task_type_and_course_are_wired_in_frontend() -> None:
    """T-C12（SR-F5.4）：任务能选「类型」并绑到一门课程 —— 编辑能改、卡片看得见、学业页也找得回来。

    口径护栏（与后端同一条规则）：**「普通」不挂课程** —— 切到普通时课程下拉禁用并可见地清空，
    不是"偷偷清掉"（静默数据丢失正是本项目一直在防的事）。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    assert "const TASK_TYPES=['普通','作业','考试','论文','小测']" in html, "类型词表要与后端同口径"
    assert "function courseBadge(" in html and "function taskTypeOptions(" in html
    assert "function courseOptions(" in html and "function syncTypeCourse(" in html
    card = html.split("function taskCard(t,isOverdue){", 1)[1].split("\n}", 1)[0]
    assert "courseBadge(t)" in card, "任务卡片没显示「课程 · 类型」"
    edit = html.split("function editForm(t){", 1)[1].split("\n}", 1)[0]
    assert 'id="editType"' in edit and 'id="editCourse"' in edit, "编辑态不能改类型/所属课程"
    save = html.split("async function saveTaskEdit(){", 1)[1].split("\n}", 1)[0]
    assert "task_type:" in save and "course_id:" in save, "保存时没把类型/课程带上"
    assert "courseEl.disabled=normal" in html, "「普通」时课程下拉应禁用（与后端校验同一条规则）"
    # 事件委托：change 走 data-change（本页零依赖、无内联脚本）
    assert "data-change=\"type-course\"" in html and "'type-course':" in html
    assert "addEventListener('change'" in html, "change 事件没走委托"
    # 学业页：课程卡能倒着列出挂在这门课上的任务，并能打开任务详情
    assert "data-action=\"task-open\"" in html and "'task-open':" in html
    assert "tasksOfCourse" in html, "课程卡没显示关联任务"


def test_subtask_flow_is_wired_in_frontend() -> None:
    """F1 段1（OP-12）：建步骤、勾完成、脱离父任务都要有界面入口。"""
    html = WEB_INDEX.read_text(encoding="utf-8")
    for needle in ("function addSubtask(", "function setTaskParent(", "subtask-add", "task-parent"):
        assert needle in html, f"子任务前端缺少 {needle}"
    assert "subtask_done" in html and "subtask_total" in html, "任务卡应显示步骤进度"


def test_recycle_bin_can_hard_delete_and_clear() -> None:
    """用户要求：回收站要能彻底删除 / 清空（纯软删除会越积越多）。

    安全约定：界面上的彻底删除**只能作用于回收站里的任务**，活动任务必须先软删除；
    `POST /api/tasks/purge-deleted` 是固定路径，不能被 `/{task_id}` 吃掉（声明顺序回归）。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    assert "function purgeTask(" in html and "function emptyTrash(" in html
    assert 'data-action="task-purge"' in html and 'data-action="trash-empty"' in html
    assert "purge-deleted" in html
    # 不可逆操作必须二次确认（清空是两道确认）
    assert html.count("不可恢复") >= 1, "彻底删除/清空必须给出「不可恢复」的明确警告"
    assert html.count("再确认一次") >= 1, "清空回收站要两道确认"
    root = Path(__file__).resolve().parent.parent
    api = (root / "src" / "timeflow" / "api" / "app.py").read_text(encoding="utf-8")
    idx_bulk = api.index('@app.post("/api/tasks/purge-deleted")')
    idx_single = api.index('@app.get("/api/tasks/{task_id}"')
    assert idx_bulk < idx_single, "purge-deleted 必须声明在 /{task_id} 之前，否则会被当成 task_id"


def test_settings_page_is_unified_and_reachable() -> None:
    """用户要求：把散落的调整收进一个「设置」界面，并且宽屏左栏也要有入口。"""
    html = WEB_INDEX.read_text(encoding="utf-8")
    # ① 宽屏左栏有设置入口（此前只有移动端底部 Tab 才有，宽屏根本进不去）
    rail_nav = html.split('class="rail"', 1)[1].split("</nav>", 1)[0]
    assert 'data-view="setting"' in rail_nav, "左栏导航缺少「设置」入口"
    # ② 设置页收拢了这四类调整
    setting = html.split("async function renderSetting(", 1)[1]
    setting = setting.split("async function setGpa(", 1)[0]
    for needle in ("set-theme", "set-accent", "set-gpa", "set-sync", "数据与同步"):
        assert needle in setting, f"设置页缺少 {needle}"
    # ③ 设置页里的动作都必须已注册（点了没反应比报错更难发现）
    used = set(re.findall(r'data-action="([a-z-]+)"', setting))
    registered = set(re.findall(r"'([a-z-]+)':\s*(?:el\s*=>|\()", html.split("const ACTIONS")[1]))
    assert not (used - registered), f"设置页有未注册动作：{sorted(used - registered)}"


def test_every_data_view_button_has_a_handler() -> None:
    """护栏：`data-view="X"` 要么是合法视图，要么是已注册的动作。

    否则点了没反应（设置页的「跳到某一节」就是这种用法：data-view 指向动作名）。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    views = set(re.findall(r'const VIEWS=\[([^\]]*)\]', html)[0].replace("'", "").split(","))
    views = {v.strip() for v in views if v.strip()}
    targets = set(re.findall(r'data-view="([a-z-]+)"', html))
    registered = set(re.findall(r"'([a-z-]+)':\s*(?:el\s*=>|\()", html.split("const ACTIONS")[1]))
    unknown = sorted(targets - views - registered)
    assert not unknown, f"这些 data-view 既不是视图也没注册动作：{unknown}"
    assert "if(!VIEWS.includes(name))" in html, "render 应对未知视图名报警而不是静默空屏"


def test_theme_is_selectable_and_wired() -> None:
    """R4 接通（用户要求「设置里能调」）：亮 / 暗 / 跟随系统，写在 <html data-theme> 上。

    暗色令牌在 R1 就位；这里的护栏防「开关没接线 / 选择没记住 / 没有跟随系统」。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    css = WEB_CSS.read_text(encoding="utf-8")
    assert "left, dark, system" in html or "'light','dark','system'" in html, "应提供三种主题选择"
    assert "dataset.theme=" in html, "主题必须写到 <html data-theme>（CSS 令牌靠它生效）"
    assert "localStorage.setItem(THEME_KEY" in html and "localStorage.getItem(THEME_KEY)" in html, (
        "主题选择要记住"
    )
    assert "prefers-color-scheme" in html, "「跟随系统」需要监听系统偏好"
    assert "matchMedia" in html and "addEventListener" in html
    assert '[data-theme="dark"]' in css


def test_accent_palette_lives_in_css_not_js() -> None:
    """R1 约定：颜色只住在 app.css；设置页的色板必须从 CSS 令牌读，不能在脚本里写字面色值。"""
    html = WEB_INDEX.read_text(encoding="utf-8")
    css = WEB_CSS.read_text(encoding="utf-8")
    assert "accentPalette()" in html and "getPropertyValue" in html
    assert html.count("--accent-${i}") == 1
    for token in ("--accent-1", "--accent-6"):
        assert token in css, f"app.css 缺少色板令牌 {token}"


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
