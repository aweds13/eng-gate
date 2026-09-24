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
# 手机离线记的引擎与 service worker（G 批 · T-G10）：都是独立文件，护栏直接读它们
WEB_ENGINE = Path(__file__).resolve().parent.parent / "src" / "web" / "offline.js"
WEB_SW = Path(__file__).resolve().parent.parent / "src" / "web" / "sw.js"


def _fn_body(html: str, name: str) -> str:
    """取页面里某个函数的函数体（从 `function 名字(` 到下一行单独的 `}`）。

    为什么按名字切而不是把签名抄进测试：签名会随功能加参数
    （`renderDetail` 就加过 `attempts`），抄签名等于**每加一个参数就崩一批无关测试** ——
    那些测试要断言的是"函数体里有什么"，不是"参数列表长什么样"。
    """
    return html.split(f"function {name}(", 1)[1].split("\n}", 1)[0]


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
        "--accent", "--accent-ink", "--panel-2", "--bg", "--panel", "--panel-2",
        "--border", "--ink", "--muted", "--danger", "--ok", "--shadow",
    ):
        assert token in css, f"缺少令牌 {token}"
    # 暗色块里也要有背景/文字/表面的覆盖（否则暗色会是半成品）
    dark = css.split('[data-theme="dark"]', 1)[1].split("}", 1)[0]
    for token in ("--bg", "--panel", "--panel-2", "--border", "--ink"):
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
    assert "连不上电脑" in html and "toast('连不上电脑" in html, "非取消类网络错误仍应提示"
    # 提示换了措辞（T-G10 起要顺带告诉人"可以记在手机上"），但两件事都还在：
    # ① 提示不许省；② 只有网络失败才标 `__offline`（后端拒绝不许被当成离线）。
    api_fn = _fn_body(html, "api")
    assert "err.__offline=true" in api_fn and "paintOfflineBar()" in api_fn


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
    # 窄屏才需要给底部固定 Tab 留出空间；宽屏不该白留一条（R5 起这个尺寸是令牌 --nav-clearance）
    assert "@media (min-width: 980px)" in css and "padding: 0 var(--sp-5)" in wide


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
                 "border-radius: var(--r-pill)", "padding: 0"):
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
    detail = _fn_body(html, "renderDetail")
    for need in ("humanTime(f.occurred_at)", "建于 ", "更新于 ", "步骤（子任务）", "subtaskTitle"):
        assert need in detail, f"详情面板缺少 {need}"
    assert "任务详情" in detail and "记录（最近" in detail
    # 选中态：列表里那张卡要有标记，否则不知道右栏在看哪个
    css = WEB_CSS.read_text(encoding="utf-8")
    assert "t.id===detailTaskId?'selected'" in html and ".card.selected" in css
    # 详情面板要取子任务列表（否则"步骤"永远是空的）
    assert "/subtasks`" in html


def test_task_note_is_editable_in_detail_only() -> None:
    """T-B1（SR-F1.4a 备注）：详情面板能读能写，**列表卡片不显示**（渐进聚焦）。"""
    html = WEB_INDEX.read_text(encoding="utf-8")
    edit = html.split("function editForm(t){", 1)[1].split("\n}", 1)[0]
    assert 'id="editNote"' in edit, "编辑态缺少备注输入（备注就只能靠 API 写了）"
    save = html.split("async function saveTaskEdit(){", 1)[1].split("\n}", 1)[0]
    assert "editNote" in save and "note:" in save, "保存时没把备注带上"
    detail = _fn_body(html, "renderDetail")
    assert "t.note" in detail, "详情面板没有显示备注"
    card = html.split("function taskCard(t,isOverdue){", 1)[1].split("\n}", 1)[0]
    # 断言的是"**任务自己的备注**不上卡"，所以认字段访问 `t.note` —— 不是裸子串 `note`：
    # T-G21 加了一枚「AI 报告」徽标（`t.progress_note` = AI 记的那一句话，**该**显示在卡上），
    # 裸子串会把那个诚实的字段一起判红（过宽的护栏会罚老实人，同 T-G11 的教训）。
    assert "t.note" not in card, "备注不该出现在列表卡片里（渐进聚焦）"


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


def _strip_js_comments(body: str) -> str:
    """去掉 JS 注释（`//…` 与 `/*…*/`）—— 判"代码里怎么写"，不判注释里怎么解释。

    为什么必须先剥注释（这条教训在 T-G39 刚吃过一次：`contrast_audit.py` 抽令牌不剥注释，
    把注释里那句形状像声明的示例吞了进去）：修 T-G41 时我在函数里写了
    "别用 `toISOString()`，它拿的是 UTC 日期" —— 不剥注释的话，**这句解释会被当成违规**，
    而下一个人最自然的反应就是把解释删掉（护栏把文档赶走了）。
    """
    out: list[str] = []
    for line in body.split("\n"):
        line = re.sub(r"/\*.*?\*/", "", line)
        out.append(re.sub(r"//.*$", "", line))
    return "\n".join(out)


def _utc_date_misuse(html: str) -> list[str]:
    """找出"把 UTC 日期当本地今天"的写法（空列表 = 干净）。

    抽成**纯函数**是为了能用合成数据证明这条护栏真的咬得住（同 `test_flows_selfcheck.py` 的做法）——
    只对真文件断言的话，"护栏到底在不在工作"永远没人验过。
    """
    bad: list[str] = []
    if "new Date().toISOString()" in html:
        bad.append("裸的 new Date().toISOString()（那是 UTC 日期，不是本地今天）")
    for name in ("renderHabit", "heatmap"):
        if f"function {name}(" not in html:
            bad.append(f"找不到 {name}（切函数的方式过期了？）")
            continue
        if "toISOString" in _strip_js_comments(_fn_body(html, name)):
            bad.append(f"{name} 里出现 toISOString（要 UTC 必须先显式做时区换算）")
    return bad


def test_today_is_local_not_utc() -> None:
    """T-G41：习惯页的「今天」按**本地**时区算（`todayISO()`），不许用 `toISOString()`。

    为什么值得单独立一条：`new Date().toISOString()` 给的是 **UTC** 日期 —— 本机 UTC+8，
    本地凌晨 0–8 点算出的是**昨天**，于是"今天已打卡"显示成「打卡」，
    而点下去（服务端按本地今天翻转）会把今天那次打卡**取消**掉（真缺陷，
    见 `复盘/习惯页今天差一天-T-G41.md`）。热力图那边同族：格子按本地构造、日期却取 UTC
    → 整张图差一天。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    assert _utc_date_misuse(html) == [], "日期的「今天」一律走 todayISO()（本地时区）"
    assert "todayISO()" in _fn_body(html, "renderHabit")
    assert "todayISO(" in _fn_body(html, "heatmap")
    # 负样例（合成数据）：两种写法都必须被抓出来，否则这条护栏只是"看起来在管"
    assert _utc_date_misuse("const today=new Date().toISOString().slice(0,10);")
    assert _utc_date_misuse(
        "async function renderHabit(m){\n  const t=d.toISOString().slice(0,10);\n}"
        "\nfunction heatmap(l){\n  return '';\n}"
    )


def test_reminder_ui_and_notify_switch() -> None:
    """T-B5（SR-F1.4a 提醒）：能设、能标出来；通知通道（B′ 计划任务）有开关且**默认关**。

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
    """T-B4（SR-F1.4a 附件 / SR-F5.3 跳转要求）：能挂、能点开、**打不开必出声**。

    规则在后端（`core/attach.py`），前端只负责把三种结果分开处理：
    网址→新标签、本机动作→已执行、其余→**复制路径 + 提示**（不许静默失败）。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    # ① 任务详情：附件区（列表 + 添加 + 打开 + 删除）
    detail = _fn_body(html, "renderDetail")
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
    """T-B3（SR-F1.2「提供视图」）：三个智能视图要真的进得去 —— 左栏、全部任务页、设置页都有入口。

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
    """T-B2（SR-F1.1b 排序）：卡片有优先级色标、编辑态能改优先级，颜色只住 app.css。"""
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


def test_today_done_section_is_expandable_inline() -> None:
    """T-C4 + T-C11：产出分两类；「今天做成了什么」三个项**原地展开**看明细（不用弹窗）。

    用户点名："大任务一天推不完，完成了哪些子步骤也要看得见" —— 所以步骤要**按父任务分组**并
    显示父任务进度；撤销的产出要如实标出。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    # T-C4：摘要行与备忘录页都按两类分开报
    assert "学校 KPI ${s.output_kpi} 条" in html and "知识资产 ${s.output_asset} 条" in html
    assert "output_kpi" in html and "output_asset" in html
    # T-C11：三个可点开的项 + 原地展开
    assert "function doneSection(" in html and "done-toggle" in html
    assert "'done-toggle':" in html
    assert "今天做成了什么" in html and "/api/today/done" in html
    assert "完成任务 ${taskCount} 项" in html
    assert "完成步骤 ${stepCount} 个" in html
    # 步骤按父任务分组 + 显示父任务进度（"该任务进度 2/5 步"）
    assert "该任务进度" in html and "p.total_steps" in html
    # 就地展开：不许用弹窗/confirm 展示明细
    done = html.split("function doneSection(d){", 1)[1].split("\n}", 1)[0]
    assert "confirm(" not in done and "ask(" not in done, "明细要就地展开，不要弹窗"
    # 撤销的产出如实标注
    assert "已撤销（不计入条数）" in html


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
        # T-G56：5 条「无界面路由」里的 1/2 接进设置页（只读展示 + 一个"读一次"按钮）——
        # 这两条以前**从没被界面调用过**，所以也从来没被这张表覆盖。
        ("get", "/api/sync/logs", None),
        ("get", "/api/reminders", None),
        ("get", "/api/focus/today", None),
        ("get", "/api/focus/active", None),
        ("get", "/api/focus/guard", None),
        ("get", "/api/settings/backups", None),
        ("get", "/api/feedback", None),
        ("get", "/api/selfcheck", None),
        ("get", "/api/review/due", None),
        ("get", "/api/review/meta", None),
        ("get", "/api/settings/vocab", None),
        ("get", "/api/settings/export", None),
        ("get", "/api/settings/ai", None),
        ("get", "/api/insights/heatmap-dimensions", None),
        ("get", "/api/insights/academic-vs-self?days=90", None),
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


# ---------------------------------------------------------------- 前端批次（2026-09-20）
# 这一批是把"后端已就绪、界面没入口"的三件事接上：任务→复习卡、复习卡改形式/句柄、均衡度显示。
# 每一条都同时钉两件：**界面接线**（模板 + ACTIONS 注册）与**后端契约**（真发一次请求）。

def test_task_can_be_upgraded_to_review_card_from_detail() -> None:
    """T-C5（SR-F6.2）：任务详情有「升级为复习卡」；升级过就在详情里列出已有的卡。

    幂等由后端保证 —— 界面**不许**自己算"有没有升级过"（那样两处口径就会漂）。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    assert 'data-action="task-to-review"' in html and "'task-to-review':" in html
    detail = _fn_body(html, "renderDetail")
    assert "rcards.length" in detail, "详情面板没根据「已有复习卡」改变呈现"
    assert "复习卡（" in detail, "详情面板没列出已升级出来的复习卡"
    fn = html.split("async function toReview(id){", 1)[1].split("\n}", 1)[0]
    assert "to-review" in fn and "已升级为复习卡" in fn
    # 也真的走一遍后端的幂等语义（界面按钮点两次只应有一张卡）
    assert "created" in fn, "界面没有把「这张卡是不是新建的」如实说出来"


def test_review_card_form_and_handle_are_editable() -> None:
    """T-C6 + T-C7（SR-F6.5 形式 / SR-F8.3 引用句柄）：能选形式、能填/清句柄。

    两条硬口径：
    ① **词表只在后端一处** —— 界面按需拉 `/api/review/meta`，不许在前端再写一份中文表；
    ② **排期字段不给人手改** —— 到期/间隔/次数是 FSRS 的记忆状态，界面上只能改定义类字段。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    assert "function reviewEditForm(" in html and "async function editReview(" in html
    assert "async function saveReviewEdit(" in html
    assert "'/api/review/meta'" in html, "形式/执行源的中文词表必须从后端拿"
    save = html.split("async function saveReviewEdit(){", 1)[1].split("\n}", 1)[0]
    for key in ("form", "source", "ref_handle"):
        assert key in save, f"保存时没把 {key} 带上"
    form = html.split("function reviewEditForm(it,meta){", 1)[1].split("\n}", 1)[0]
    assert 'id="rvForm"' in form and 'id="rvSource"' in form and 'id="rvHandle"' in form
    assert "不给人手改" in form, "必须写明排期字段不给人手改（否则用户会以为能改到期时间）"
    for action in ("review-edit", "review-save", "review-edit-cancel"):
        assert f"'{action}':" in html, f"动作 {action} 没注册"


def test_review_edit_roundtrip_via_api(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """前端实际发的那个 PATCH：改 form/source/ref_handle 生效，且**排期字段纹丝不动**。"""
    client = TestClient(create_app(str(tmp_path / "rv.db")))
    tid = client.post("/api/tasks", json={"title": "背单词"}).json()["id"]
    up = client.post(f"/api/tasks/{tid}/to-review", json={}).json()
    assert up["created"] is True and up["card"]["task_id"] == tid
    rid = up["card"]["id"]
    again = client.post(f"/api/tasks/{tid}/to-review", json={}).json()
    assert again["created"] is False and again["card"]["id"] == rid, "重复升级不该再建卡"

    before = client.get(f"/api/review/items/{rid}").json()
    patched = client.patch(
        f"/api/review/items/{rid}",
        json={"form": "cloze", "source": "external", "ref_handle": "notes/英语.md"},
    )
    assert patched.status_code == 200, patched.text
    after = client.get(f"/api/review/items/{rid}").json()
    assert (after["form"], after["source"], after["ref_handle"]) == (
        "cloze", "external", "notes/英语.md"
    )
    for key in ("due_date", "reps", "interval_days"):
        assert after[key] == before[key], f"排期字段 {key} 被改了（FSRS 的记忆状态不该手改）"
    # 空串 = 清除（存 NULL，不写空串）—— 界面留空就是这个意思
    cleared = client.patch(f"/api/review/items/{rid}", json={"ref_handle": ""}).json()
    assert cleared["ref_handle"] is None
    assert client.get("/api/review/meta").json()["forms"], "词表接口不能为空"


def test_week_rhythm_is_displayed() -> None:
    """T-C3（SR-F2.5）：周结算卡片要显示**波动 / 空档**与那句温和的话。

    呈现红线：只报分钟/天数这类不折算的原始单位，措辞只描述事实（不设目标、不告警）——
    所以这里也顺手断言界面没有把它们包装成"达标/未达标"。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    assert "function rhythmRow(w)" in html
    week = html.split("function weekCard(w){", 1)[1].split("\n}", 1)[0]
    assert "rhythmRow(w)" in week, "周结算卡片没显示均衡度"
    row = html.split("function rhythmRow(w){", 1)[1].split("\n}", 1)[0]
    for needle in ("focus_variation_minutes", "longest_gap_days", "rhythm_note"):
        assert needle in row, f"均衡度少了字段 {needle}"
    for bad in ("达标", "未达标", "目标", "警告", "落后"):
        assert bad not in row, f"均衡度措辞不许出现「{bad}」（温和不施压）"


def test_hard_assessment_is_marked_more_strongly() -> None:
    """T-C8（SR-F1.8 的"强"侧 / GAP-F1-06）：学校硬考核要比普通逾期**呈现得更明显**。

    口径（`复盘/C批口径定案.md` §四）：硬考核 = 考核项**有 due_date 且未录成绩**
    （`upcoming_assessments()` 本来就只返回这一类）。要做到：置顶 + 更粗的左边条 + 角标 + 一句说明；
    **但只做视觉** —— 不加声音、不弹窗（温和不施压），所以这里也断言界面没说"催/警告"。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    academic = html.split("async function renderAcademic(m){", 1)[1].split("\n}", 1)[0]
    assert "card hard" in academic and 'class="badge hard"' in academic, "硬考核卡片没用强呈现的类"
    assert "硬考核：临期与逾期" in academic, "硬考核区没有单独的小标题"
    assert "未录成绩" in academic and "逾期不候" in academic, "没说明为什么它被单独标出来"
    assert "days_until-b.days_until" in academic, "硬考核没有按剩余天数排（逾期优先）"
    css = WEB_CSS.read_text(encoding="utf-8")
    assert ".card.hard" in css and ".badge.hard" in css, "app.css 缺硬考核样式（颜色只能住这里）"
    for bad in ("alert(", "confirm(", "Notification"):
        assert bad not in academic, f"硬考核不该用 {bad}（不加声音、不弹窗）"


def test_review_completion_offers_output_entry() -> None:
    """T-C2（SR-F2.2）：复习完**想记才点**「记一笔产出」—— 不自动弹窗、不打断复习。

    用户 2026-09-20 定的形态：入口挂在 toast 上（6 秒内可点），产出入知识资产（`kind=asset`）。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    # 注意：`review()` 结尾是 `view(current)}`（闭括号不单独成行）→ 按"下一个函数"切，别按 "\n}"
    head, tail = html.split("async function review(id,fb){", 1)
    fn = tail.split("async function reviewOutput", 1)[0]
    assert "toastAction(" in fn and "记一笔产出" in fn, "复习完成没给「记一笔产出」入口"
    assert "await ask(" not in fn, "不可以在完成复习时立刻弹窗拦住用户（形态是「想记才点」）"
    out = html.split("async function reviewOutput(id){", 1)[1].split("\n}", 1)[0]
    assert "/api/ledger/output" in out and "kind:'asset'" in out, "温故知新产出应入知识资产"
    assert "'/api/review/meta'" not in out, "记产出不该再拉复习词表"


def test_review_regrade_is_wired_and_labels_come_from_backend() -> None:
    """T-G13（F6 OP-27 可逆的延伸）：「今天复习过的」里能**改判**，三档中文来自后端。

    三条硬口径：
    ① 三态中文（记得/模糊/忘了）**只在后端一处**（`meta.ratings`）—— 界面不许自己再写一份；
    ② 「改判」只给**另外两档**的按钮（改成一样的没有意义，后端也会 400）；
    ③ 改判是**撤销 + 按新档重来**，所以界面上要明说代价（排期重算、原来那次留痕、投入不重复计）。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    assert "function reviewDoneCard(r,ratings){" in html, "复习页没有「今天复习过的」那一段"
    assert "api('/api/review/today')" in html and "'/api/review/meta'" in html
    assert "reviewRatings=meta.ratings||[]" in html, "三档中文必须从后端 meta 拿"
    # ① 后端给的词表渲染三态按钮 → reviewCard 里不该再出现硬编码的档位中文
    card = html.split("function reviewCard(r,ratings){", 1)[1].split("\n}", 1)[0]
    assert "ratings.map(" in card, "三态按钮没从 ratings 渲染"
    for hard in ("data-feedback=\"remember\">记得", "data-feedback=\"forgot\">忘了"):
        assert hard not in card, "界面又自己写了一份档位中文（词表应只在后端一处）"
    # ② 只给另外两档
    done = html.split("function reviewDoneCard(r,ratings){", 1)[1].split("\n}", 1)[0]
    assert "ratings.filter(x=>x.value!==r.feedback)" in done, "改判必须排除「和现在一样」的那一档"
    assert 'data-action="review-regrade"' in done
    assert "'review-regrade':" in html and "async function regradeReview(" in html
    # ③ 说清代价
    fn = html.split("async function regradeReview(id,feedback){", 1)[1].split("\n}", 1)[0]
    assert "/regrade" in fn and "confirmAsk(" in fn
    assert "重算" in fn and "不会重复计" in fn, "改判前必须说清排期重算与投入不重复计"
    # 复习完成后的提示里要告诉用户「记错了去哪改判」（否则这个入口没人找得到）
    review_fn = html.split("async function review(id,fb){", 1)[1]
    review_fn = review_fn.split("async function reviewOutput", 1)[0]
    assert "改判" in review_fn


def test_academic_vs_self_chart_is_wired() -> None:
    """T-C10（SR-F5.1b / GAP-F5-03）：统计页要有「学业投入 vs 自学投入」对照。

    口径（用户 2026-09-20 定）：**只算挂了课程的任务专注**；没挂课程的算自学；
    未绑定任务的专注**单列、不归入任何一边**。★ T-G55 起这条口径由**后端契约**
    （`tests/test_insights.py` 的 `academic_vs_self` 那一组）与 `docs/user-guide.md` 承担，
    **不再**在界面上写一整段解释 —— 按 `conventions.md`「界面文案」，界面上只留
    「学业：挂了课程的任务 / 自学：没挂课程的任务」这两条**数据标签**（它们自己就说清了归因）。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    assert "/api/insights/academic-vs-self?days=90" in html, "统计页没取对照数据"
    stats = html.split("function renderStats(m){", 1)[1].split("\n}\n", 1)[0]
    assert "split" in stats and "acSplit" in stats, "对照图没接进统计页"
    assert "学业：挂了课程的任务" in stats and "自学：没挂课程的任务" in stats
    for bad in ("应该", "达标", "落后"):
        assert bad not in stats.split("acSplit=", 1)[1][:1200], f"对照图措辞不许出现「{bad}」"


# ------------------------------------------------------- 前端批次③（R5 收口 / 折叠 / 引导）

def test_no_native_confirm_left_on_the_page() -> None:
    """R5（SR-NF5「不可逆操作二次确认」）：二次确认必须走**壳级模态**，不许再叫原生 `confirm`。

    理由：原生弹窗样式与主题无关、挡不住、文案里写不清"在确认什么"（永远是"确定"），
    也没法在护栏里测。壳级模态给了 `confirmAsk(title, okLabel)`：确定按钮写上动作名，
    取消/ESC/点外面都归成 false。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    assert "confirm(" not in html, "还有原生 confirm（应换成 confirmAsk）"
    assert "function confirmAsk(" in html and "let modalMode='ask'" in html
    assert "'modal-ok':       () => closeModal(modalMode==='confirm'?true:" in html, \
        "确定按钮没按模式归一（confirm 态必须给 true/false，不能给输入框的空串）"
    assert "modalMode==='confirm'?result===true:result" in html, "closeModal 没按模式归一返回值"
    # 二次确认的"动作名"要写上（否则用户看不出在确认什么）
    for label in ("'删除分组'", "'彻底删除'", "'清空回收站'", "'全部永久删除'", "'取消任务'"):
        assert label in html, f"确认按钮缺动作名 {label}"


def test_empty_states_go_through_one_helper() -> None:
    """R5（SR-NF1b 视觉统一）：空态只有**一处**标记与措辞入口（`emptyState()`）。"""
    html = WEB_INDEX.read_text(encoding="utf-8")
    # 唯一允许出现字面量空态标记的地方就是 emptyState() 自己（它把标记收在一处）
    assert html.count('<div class="empty">') == 1, "还有直接写死的空态（应收进 emptyState）"
    assert "function emptyState(text)" in html
    assert html.count("emptyState('") >= 12, "空态用得这么少，多半是没收干净"
    css = WEB_CSS.read_text(encoding="utf-8")
    assert ".empty {" in css, "app.css 缺空态样式"


def test_right_rail_is_collapsible() -> None:
    """SR-NF4 / GAP-NF-03：右栏可折叠（宽屏换更宽中列），选择记在本机，两处入口。"""
    html = WEB_INDEX.read_text(encoding="utf-8")
    css = WEB_CSS.read_text(encoding="utf-8")
    assert ".shell.rail-off .sidebar { display: none }" in css, "缺折叠样式"
    assert "function applyRail(" in html and "function toggleRail(" in html
    assert "'rail-toggle':" in html and 'data-action="rail-toggle"' in html
    assert "const RAIL_KEY='tf_rail'" in html, "折叠选择没记在本机（刷新就丢）"
    assert "railOff?'展开右栏':'收起右栏'" in html, "按钮文案没跟着状态走"
    setting = html.split('data-action="rail-toggle">', 1)[1][:80]
    assert "收起右栏" in setting or "展开右栏" in setting, "设置页缺折叠入口（手机端左栏是隐藏的）"


def test_first_run_guide_is_skippable_and_replayable() -> None:
    """SR-NF2 / GAP-NF-02：新手引导（三步）可跳过、可重看，**且不拦路**（不是遮罩弹窗）。"""
    html = WEB_INDEX.read_text(encoding="utf-8")
    assert "function guideCard(" in html and "function guideReplay(" in html
    assert "const GUIDE_KEY='tf_guide'" in html, "引导状态没记在本机（每次打开都弹）"
    for action in ("guide-start", "guide-done", "guide-replay"):
        assert f"'{action}':" in html, f"动作 {action} 没注册"
    today = html.split("async function renderToday(m){", 1)[1].split("\n}", 1)[0]
    assert "${guideCard()}" in today, "引导卡片没进今日页"
    guide = html.split("function guideCard(){", 1)[1].split("\n}", 1)[0]
    for step in ("①", "②", "③"):
        assert step in guide, "三步要写全（建任务 → 开专注 → 记反馈）"
    assert "不再显示" in guide, "必须有一键关掉（不许拦路）"
    assert "box.hidden=false" not in guide, "引导不该用遮罩弹窗"
    assert 'data-action="guide-replay"' in html, "设置页缺「再看一遍」入口"


def test_r5_scale_tokens_are_the_only_way_to_write_sizes() -> None:
    """R5（SR-NF1b「字体/间距/圆角/阴影统一」）：组件只写**令牌**，不写裸像素。

    为什么值得一条护栏：R5 的验收标准是"统一"，而"统一"如果只写在文档里，下一轮就漂了。
    有了令牌 + 这条断言，"48 种间距取值"这类事会被挡住。
    白名单只留发丝级内缩（1~3px：描边/内衬，不是间距档位）。

    ★ **判的是"剥掉注释后的代码"**（T-G43 实测撞到）：注释里为了说明"原来那处裸像素是什么"
    会**原文引用**它，第一版护栏就把自己的说明文字判红了 —— 同一类坑 T-G39 的令牌抽取、T-G41 的
    日期护栏各栽过一次。注释不是代码，护栏该看代码。
    """
    css = re.sub(r"/\*.*?\*/", "", WEB_CSS.read_text(encoding="utf-8"), flags=re.S)
    for token, value in (("--sp-1", "4px"), ("--sp-2", "8px"), ("--sp-6", "32px"),
                         ("--r-sm", "6px"), ("--r-md", "10px"), ("--r-pill", "999px"),
                         ("--fs-xs", "11px"), ("--fs-xl", "18px"),
                         ("--lh-tight", "1.2"), ("--lh-base", "1.5"),
                         ("--fw-semi", "600"), ("--fw-bold", "700"),
                         ("--nav-clearance", "90px"), ("--page-bottom", "60px")):
        assert f"{token}: {value};" in css, f"尺度令牌 {token} 缺失或值变了"
    # ★ T-G51：档位收敛的**棘轮** —— 并到包的网格之后只许是 6 档间距 / 3 档圆角。
    # 这条断言是"收敛过"的凭证（`tools/style_audit.py` 的档数报告按**令牌名**数，
    # 所以"同值两个名字"也算两档）：再有人加第 7 档间距、第 4 档圆角，这里先红。
    assert sorted(re.findall(r"--sp-(\d+):", css)) == ["1", "2", "3", "4", "5", "6"]
    assert sorted(re.findall(r"--r-([a-z]+):", css)) == ["md", "pill", "sm"]
    assert not re.findall(r"border-radius:\s*[^;{}]*\d+px", css), "圆角还有裸像素"
    assert not re.findall(r"font-size:\s*[^;{}]*\d+px", css), "字号还有裸像素"
    spacing = re.findall(
        r"((?:padding|margin|gap)(?:-(?:top|right|bottom|left))?):\s*([^;{}]+)", css
    )
    bad = [f"{p}: {v.strip()}" for p, v in spacing
           if re.search(r"(?<![\w-])(?!1px\b|2px\b|3px\b)\d+px", v)]
    assert bad == [], f"间距还有裸像素（用令牌，或进白名单并说明理由）：{bad}"
    # 状态色只走语义令牌：完成=--ok、到期债务=--danger、专注=--accent
    assert ".card.overdue { border-left: 3px solid var(--danger) }" in css
    assert ".card.hard { border-left: 5px solid var(--danger) }" in css
    # ★ T-G42：徽标里的状态由 **8px 圆点**承担（workbench 的 StatusDot），**不再拿状态色写字** ——
    # 原来那三条 `color-mix(… 18% …) + 同色字` 是全表最差的三条对比度（最糟 1.96）。
    # 点是 `<i class="dot">`（真元素，不是 ::before）：伪元素采不进渲染清单，
    # 那就等于"这个点还在不在、什么颜色"没有任何一层能验 —— 见 `tools/render_check.mjs`。
    assert ".badge.done .dot { background: var(--ok) }" in css
    assert ".badge.doing .dot { background: var(--accent) }" in css
    assert ".badge.hard .dot { background: var(--danger) }" in css
    html = WEB_INDEX.read_text(encoding="utf-8")
    for state in ("done", "doing", "hard"):
        hits = re.findall(rf'<span class="badge {state}">', html)
        assert hits, f"模板里找不到 .badge.{state}（状态徽标被改名了？）"
        for m in re.finditer(rf'<span class="badge {state}">', html):
            assert html[m.end():m.end() + len('<i class="dot"></i>')] == '<i class="dot"></i>', (
                f".badge.{state} 忘了带状态点 —— 那这一枚就没有任何颜色信号了"
            )
    # 徽标本体不许再"同色写字"：剥掉注释后，`.badge*` 的规则体里既不该有 color-mix，
    # 也不该自己定 color（判的是**剥掉注释后的代码** —— T-G39/T-G41 都栽在
    # "护栏咬到自己的说明文字"上）
    bare = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    badge_rules = [(s.strip(), b) for s, b in re.findall(r"([^{}]+)\{([^{}]*)\}", bare)
                   if s.strip().startswith(".badge")]
    assert badge_rules, "找不到徽标规则（选择器换名字了？）"
    for sel, body in badge_rules:
        assert "color-mix" not in body, f"徽标又用合成底了（{sel}）：{body.strip()}"
        # 基座 `.badge` 定字色是它的职责（芯片字色）；**状态变体不许再自己定字色** ——
        # 那正是"色块里用同一个颜色写字"的入口（原来那三条最差组合就是这么来的）。
        if sel != ".badge":
            assert not re.search(r"(?<![-\w])color\s*:", body), f"{sel} 又自己定字色了"
    # 阴影也走令牌（亮/暗各一处定义）
    assert css.count("--shadow:") == 2 and "box-shadow: var(--shadow)" in css


def test_cards_have_two_levels_and_the_quiet_one_keeps_its_shapes() -> None:
    """T-G51（用户 2026-09-24 选的候选 C「静音层」）：卡片分**两级**。

    为什么值得一条护栏：这是"平/丑"最直接的病根 —— 66 张卡权重完全相同（白底 + 同圆角 + 同内距），
    层次全靠 1px 边框，而全表唯一那条阴影又淡到看不见。包的答案是两级：`.wb-card` 抬升面
    （一条**事**）与 `.wb-stat` 静音面（一个**读数**）。护栏钉三件事：

      · 读数卡真的挂着 `.card.quiet`（**显式类名**，不是候选里那个 `:has()` ——
        预演用 `:has()` 只是"不必先改标记就能出图"）；
      · 静音面上**靠浅底当形状**的两笔必须画 `--border`：预演当场抓到过真缺陷 ——
        卡片一退到 `--panel-2`，同色的环轨道与雷达网格线**直接消失**（环只剩一段弧）；
      · 同义类 `.card.panel-card` 不许回来（它与 `.card.block` 都只写 `display: block`）。
    """
    css = re.sub(r"/\*.*?\*/", "", WEB_CSS.read_text(encoding="utf-8"), flags=re.S)
    html = WEB_INDEX.read_text(encoding="utf-8")
    assert ".card.quiet { background: var(--panel-2) }" in css
    assert ".ring-track { stroke: var(--border) }" in css, (
        "环轨道又画回 --panel-2 了（静音面上会消失）"
    )
    assert ".axis-line { stroke: var(--border) }" in css, "雷达网格线又画回 --panel-2 了"
    assert "panel-card" not in css and "panel-card" not in html, "同义类 .card.panel-card 又回来了"
    assert ".card.block .title { margin-bottom: var(--sp-1) }" in css
    assert ".card.block .form { margin: var(--sp-3) 0 var(--sp-1) }" in css
    assert '<div class="card quiet"><div class="ring-head">' in html
    assert html.count('class="card quiet"') == 4, (
        "单读数卡（环 / 今日专注 / 两个 GPA 读数）数量变了"
    )
    assert html.count('class="card block quiet"') == 2, "块内容读数卡（雷达 / 本周柱状）数量变了"


def test_typography_and_bare_inputs_go_through_tokens() -> None:
    """T-G53（视觉线步 3 排版节奏）+ T-G46（5 个没穿衣服的输入框）。

    合成一条护栏是因为它们是同一种病：**样式不住在体系里**。

      · 行高：全表原来**只有一处**行高（`.rail-summary` 的 `line-height: 1.5`，还是
        `tools/style_baseline.toml` 里最后一条欠账），等于"行距靠浏览器默认"。
        现在两档令牌（`--lh-tight` 标题与读数 / `--lh-base` 正文与多行说明）——
        **行高只许写令牌**，这就是"字号 9 档、行高 1 档"那件事的修法。
      · 输入框：`.new input` 与 `.field input` 都是**上下文样式**，于是不住在那两种容器里的输入框
        （导出目录 / Vault 名 / Vault 根目录 / 离线包路径 / 归档天数）只有浏览器默认外观 ——
        渲染清单里它们长这样：`圆角 0;内边距 1px 2px`。元素级那条规则照 `select` 写，并同样
        **排除勾选框**（勾选框不是文本框：T-G32 与 T-G38 各栽过一回）。
    """
    css = re.sub(r"/\*.*?\*/", "", WEB_CSS.read_text(encoding="utf-8"), flags=re.S)
    heights = [v.strip() for v in re.findall(r"line-height:\s*([^;{}]+)", css)]
    assert heights and all(v.startswith("var(--lh-") for v in heights), f"还有裸行高：{heights}"
    assert len(heights) >= 10, "行高档位被撤掉了？"
    assert 'input:not([type="checkbox"]):not([type="radio"]) {' in css
    assert '.modal-box input:not([type="checkbox"]):not([type="radio"]) {' in css
    # 元素级规则（0,2,1）比 `.modal-box input`（0,1,1）**权重高** —— 那一条不排除勾选框就会被盖掉
    assert ".modal-box input {" not in css


def test_layout_containers_that_hold_buttons_allow_wrapping() -> None:
    """T-G45 修「中文被压碎」的三处 —— 病根是同一个：**不换行的 flex 容器 + 中文处处可断行**。

    flex 的默认行为是「先压缩、压不动才换行」，而中文的下限能低到**一个字宽**：
    实测 390px 下习惯页的标题列被压到 128px（两行）、三个按钮压成 43×56（「改名」两个字各占一行），
    摘要卡那一行更惨（68×80）。**别把这三条修好的路再堵回去** —— 它们是量出来的，不是猜的：

      · `.habit-head` 必须允许换行（它是唯一漏掉 wrap 的动作行；`.card .row` / `.new` /
        `.offline-bar` / `.gpa-head` 早就有）；
      · 习惯页的摘要卡必须是**块内容卡**（两个块级孩子并排挤在一行里就是那个 68×80）；
      · 分组名必须带宽度下限（否则右边那个长 `select` 会把它压到 19px）。
    """
    css = re.sub(r"/\*.*?\*/", "", WEB_CSS.read_text(encoding="utf-8"), flags=re.S)
    head = ".habit-head { display: flex; align-items: center; gap: var(--sp-3); flex-wrap: wrap }"
    assert head in css, ".habit-head 又不允许换行了（中文会被压成一行一个字）"
    html = WEB_INDEX.read_text(encoding="utf-8")
    assert '<div class="card block"><div class="meta">本周专注' in html
    assert '<span class="grow minw-160">${esc(g.path)}</span>' in html
    # `.minw-160` 得真在（别把它当"没人用的工具类"删了）
    assert ".minw-160 { min-width: 160px }" in css


def test_guard_settings_are_editable_from_the_setting_page() -> None:
    """SR-F3.3 / GAP-F3-02：白名单与勿扰时段能在设置页增删 —— 以前只有只读的 GET。

    界面只发 `{block_by_default|whitelist|do_not_disturb}`；**规则与判定在后端一处**
    （`/api/focus/guard` 连口径说明一起返回，界面不复述）。非法值由后端 400 + api() 弹原话。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    assert "'/api/focus/guard'" in html and "set-focus-guard" in html
    for action in ("guard-block", "guard-wl-add", "guard-wl-del", "guard-dnd-add", "guard-dnd-del"):
        assert f"'{action}':" in html, f"动作 {action} 没注册"
    setting = html.split("async function renderSetting(m){", 1)[1].split("\n}", 1)[0]
    assert "api('/api/focus/guard')" in setting, "设置页没取 guard 当前值"
    put = html.split("async function setGuard(body,okMsg){", 1)[1].split("\n}", 1)[0]
    assert "/api/settings/focus-guard" in put and "method:'PUT'" in put
    assert "guardNow()" in html, "增删要以当前值为基准（否则并发改会互相覆盖）"
    # 口径说明来自后端，界面不复述规则
    assert "guard.note" in setting and "guard.window_format" in setting


def test_backup_restore_is_wired_in_settings() -> None:
    """SR-NF12 / SR-F9.3：设置页列出最近几个备份，点一个就能恢复（不可逆 → 必须二次确认）。

    两条要在界面上说清的：
    ① 恢复是**整库回到那一刻**（连设置一起）—— 不说清用户以为只回滚任务；
    ② 恢复前会**自动再备份一次现库**，所以选错了还能回去 —— 这是"敢点"的前提。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    setting = html.split("async function renderSetting(m){", 1)[1].split("\n}", 1)[0]
    assert "api('/api/settings/backups')" in setting, "设置页没取备份列表"
    assert "set-backup" in setting and "备份与恢复" in setting
    assert "restore-backup" in setting and "'restore-backup':" in html
    fn = html.split("async function restoreBackup(name){", 1)[1].split("\n}", 1)[0]
    assert "confirmAsk(" in fn, "恢复是不可逆动作，必须二次确认"
    assert "/api/settings/restore" in fn and "method:'POST'" in fn
    assert "恢复到这个备份" in fn, "确认按钮要写清在确认什么（不是笼统的「确定」）"
    assert "newer_than_app" in fn, "备份比程序新时要如实提示（降级场景）"
    assert "function sizeLabel(" in html, "备份要显示大小（不然看不出哪份是完整的）"


def test_gain_metric_is_shown_next_to_debt() -> None:
    """T-F6（N3 贯穿口径「**完成悬赏 = 收益/储蓄**」）：摘要行与周结算要显示「完成收益」。

    这条口径一直在 `conventions.md:20`（储蓄 = 完成悬赏 / 复习完成），但**账本里一直没有读数** ——
    是用户 2026-09-21 问「我怎么没看到你开发这个系统」时查出来的缺口。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    line = html.split("function summaryLine(s){", 1)[1].split("\n}", 1)[0]
    assert "完成收益" in line and "gain_count" in line, "摘要行没显示完成收益"
    # 只看真正拼摘要的那一行（函数体里的注释也提到了"完成收益"，别被它骗了）
    parts = next(ln for ln in line.splitlines() if "const parts=" in ln)
    assert parts.index("债务") < parts.index("完成收益"), "债务→收益是一对，要排在一起（N3 口径）"
    week = html.split("function weekCard(w){", 1)[1].split("\n}", 1)[0]
    assert "完成收益" in week and "gain_count" in week, "周结算没显示完成收益"


def test_obsidian_jump_is_wired_and_read_only() -> None:
    """T-G5（SR-F8.2 / 约定层第 11 行）：引用句柄能一键跳进 Obsidian，**只读**、失败必出声。

    三条口径：
    ① **URL 只在后端拼**（编码/相对路径换算都在 `core/vault.py`）—— 界面里不许出现 `obsidian://`
       字面量，否则两处各拼一份、编码口径早晚不一致；
    ② **没配 Vault 就不摆按钮**（`ref_url` 为空时不渲染）—— 不做"点了没用"的按钮；
    ③ 调不起来 → **复制链接 + 提示**（与附件打开同一条兜底，不许静默）。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    setting = html.split("async function renderSetting(m){", 1)[1].split("\n}", 1)[0]
    assert 'id="vaultName"' in setting and 'id="vaultDir"' in setting, "设置页缺少 Vault 两栏"
    assert "api('/api/settings/export')" in setting, "Vault 状态与导出目录同源（一次请求读出来）"
    for action in ("set-vault", "vault-open"):
        assert f"'{action}':" in html, f"动作 {action} 没注册"

    save = html.split("async function saveVault(){", 1)[1].split("\n}", 1)[0]
    assert "/api/settings/vault" in save and "method:'PUT'" in save

    open_fn = html.split("async function openInVault(handle){", 1)[1].split("\n}", 1)[0]
    assert "/api/vault/open" in open_fn and "method:'POST'" in open_fn
    for needle in ("r.executed", "copyText(", "toast("):
        assert needle in open_fn, f"openInVault 缺少 {needle}（打不开不许静默）"

    card = html.split("function reviewCard(r,ratings){", 1)[1].split("\n}", 1)[0]
    assert "r.ref_url" in card and "在 Obsidian 打开" in card, "复习卡没有跳转入口"
    memo = html.split("async function renderMemo(m){", 1)[1]
    memo = memo.split("async function addMemo(", 1)[0]
    assert "x.ref_url" in memo, "备忘录没有跳转入口（T-G5 的主要场景就是备忘/复习卡）"
    # 「只读」这句口径由**后端一处给**（`vault_note`），界面只负责显示 ——
    # 原文见 tests/test_vault_obsidian_line.py 的 test_describe_states_the_read_only_note
    assert "Obsidian（只读跳转）" in setting and "ex.vault_note" in setting, "界面没显示只读口径"
    # URL **只在后端拼**：界面里不许出现现成的链接（注释里提一下协议名没关系，拼出来才算漏口径）
    assert "obsidian://open?" not in html, "URL 只能在后端拼（编码口径一处）"


def test_ai_boundary_is_wired_and_explained() -> None:
    """T-G6（SR-F7.3 / OP-34）：设置页能开关 AI 接口，并把**边界、动作表、示例**显示出来。

    三条口径：
    ① 边界与动作表**由后端一处给**（`core/ai.py`）—— 界面只渲染，不复述规则（否则两处会漂）；
    ② AI 建的任务/步骤在卡片与详情上带「AI 建的」徽标（"可回溯"在界面上的那一半）；
    ③ 默认关这件事要**说在界面上**（不是靠用户去翻文档）。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    setting = html.split("async function renderSetting(m){", 1)[1].split("\n}", 1)[0]
    assert 'id="set-ai"' in setting and "AI 接口（只读 + 新增）" in setting, "设置页缺少 AI 一节"
    assert 'data-action="set-ai"' in setting, "缺少开关"
    assert 'data-on="true"' in setting and 'data-on="false"' in setting, "开关要能开也能关"
    for needle in ("ai.boundary", "ai.surface", "ai.example", "ai.note"):
        assert needle in setting, f"这一节没有用后端给的自述：{needle}"
    assert "默认" in setting, "要写明默认是关的"
    for action in ("set-ai", "ai-copy"):
        assert f"'{action}':" in html, f"动作 {action} 没注册"
    fn = html.split("async function setAiEnabled(on){", 1)[1].split("\n}", 1)[0]
    assert "/api/settings/ai" in fn and "method:'PUT'" in fn
    copy_fn = html.split("async function copyAiExample(){", 1)[1].split("\n}", 1)[0]
    assert "copyText(" in copy_fn, "示例命令要能复制（不然只能手抄）"
    # 归属徽标：卡片与详情都要有（只标 AI 建的，默认情形不标）
    card = html.split("function taskCard(t,isOverdue){", 1)[1].split("\n}", 1)[0]
    assert "t.created_by==='ai'" in card and "AI 建的" in card
    detail = _fn_body(html, "renderDetail")
    assert "t.created_by==='ai'" in detail, "详情面板没显示归属"
    css = WEB_CSS.read_text(encoding="utf-8")
    assert ".ai-example {" in css, "示例命令块缺样式（R1：样式只住 app.css）"


def test_ai_progress_report_is_wired_and_reversible() -> None:
    """T-G21（N46 / OP-32）：AI 记的那句进展要**看得见**（卡片 + 详情），并且能**撤销**。

    四条口径：
    ① 卡片上就要有 —— 报告的意义是"你看见了"，藏进详情等于没回报；
    ② 中文前缀由后端给（`progress_label`）—— 界面不自己写一份「AI 报告」（同 OP-33 的视角名）；
    ③ 撤销按钮走**追加撤销事实**那条路（后缀 `progress/retract`），不是删事实；
    ④ 详情里要写明"报告 ≠ 状态"（要不要勾完成仍由你决定）—— 这是这张卡最容易误解的地方。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    card = html.split("function taskCard(t,isOverdue){", 1)[1].split("\n}", 1)[0]
    assert "t.progress_count" in card and "t.progress_note" in card and "t.progress_label" in card
    assert "'AI 报告'" not in card, "中文前缀由后端给，界面不许自己写一份"
    detail = _fn_body(html, "renderDetail")
    assert "t.progress_count" in detail and "t.progress_note" in detail
    assert "不是状态" in detail, "详情要写明「报告 ≠ 状态」（不然会被当成 AI 帮你标了完成）"
    assert 'data-action="progress-retract"' in detail, "缺撤销入口"
    assert "'progress-retract':" in html, "动作没注册（点了没反应比报错更难查）"
    fn = html.split("async function retractProgress(id){", 1)[1].split("\n}", 1)[0]
    assert "/progress/retract" in fn and "method:'POST'" in fn
    assert "/api/tasks/${id}/progress/retract" in fn, "撤销打到的是人侧那条路由"
    # 事实流里的人话映射（记录区按 kind 显示，缺了就会漏出英文 kind）
    labels = html.split("function factLabel(kind){", 1)[1].split("\n}", 1)[0]
    assert "task.progress.reported" in labels and "task.progress.retracted" in labels


def test_sync_pack_is_wired_and_non_destructive() -> None:
    """T-G8（SR-F9.2 场景 ③）：设置页能导出/预览/导入同步包，并把**不删你数据**这条写在界面上。

    三条口径：
    ① 导入前必须能**预览**（`dry_run`）——"覆盖"是真会改东西的，不能点了就干；
    ② 界面上要写明包里**不含**本机设置（否则用户会以为设置也跟着同步）；
    ③ 三个动作都注册在 `ACTIONS` 里（点了没反应比报错更难查）。
    ④（T-G8b 起）：**删不删由勾选框当场决定、默认不删**，且这个选择要**看得见**（不是隐藏设置）。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    setting = html.split("async function renderSetting(m){", 1)[1].split("\n}", 1)[0]
    assert 'id="set-syncpack"' in setting and "跨端同步（走文件）" in setting
    for action in ("sync-export", "sync-preview", "sync-import"):
        assert f'data-action="{action}"' in setting, f"缺少 {action} 入口"
        assert f"'{action}':" in html, f"动作 {action} 没注册"
    assert 'id="syncPath"' in setting, "导入要有路径输入框"
    assert "不含" in setting and "schema 版本" in setting, "要写明包里不含什么"
    assert "sync.device_id" in setting, "要显示设备号（判断两份包谁是谁）"
    # T-G8b：默认不删 + 勾选框 + 勾上之后的代价写清楚
    assert 'id="syncDel"' in setting and 'data-change="sync-del-toggle"' in setting, \
        "要有「同时应用删除」那颗勾选框"
    assert "默认不删" in setting, "要说明默认不删"
    assert "不可撤销" in setting and "本地在那之后又改过它" in setting, \
        "勾上之后的代价与例外要写在界面上"
    assert "'sync-del-toggle':" in html, "勾选框的变化动作没注册"
    assert "function syncApplyDeletions()" in html and "function syncDelHint()" in html

    fn = html.split("async function importSyncPack(){", 1)[1].split("\n}", 1)[0]
    assert "dry_run:true" in fn and "confirmAsk(" in fn, "导入必须先预览再二次确认"
    assert "apply_deletions:applyDel" in fn, "真导入要把勾选状态传下去"
    assert fn.count("apply_deletions:applyDel") >= 2, "预览与真导入必须传**同一个**选择"
    assert "会删掉本机" in fn, "勾了删的时候，确认框要写明会删几行"
    export_fn = html.split("async function exportSyncPack(){", 1)[1].split("\n}", 1)[0]
    assert "/api/sync/export" in export_fn and "copyText(" in export_fn


def test_mobile_offline_capture_is_wired_and_honest() -> None:
    """T-G10（SR-NF17 场景 ①）：断网时能记（进本机队列）、能导出同格式包、并且把话说清楚。

    五条口径（每一条都对应一个"看起来能用其实是坑"的写法）：
    ① **连不上 ≠ 后端拒绝**：只有网络失败（`fetch` 抛）才允许入队兜底；
       后端回 400/404 是它说了算 —— 那时候"帮你存起来"就是骗人（`writeOrQueue` 里就这一条分支）；
    ② 「离线记」这一页**不依赖后端**：它排在 `/api/config` 之前 —— 断网时配置拉不到，
       排在后面就等于"最需要它的时候整页空白"；
    ③ 包与电脑↔电脑（场景 ③）**同一个格式**，且导出**不清空**队列（"重复导入安全"靠这个前提）；
    ④ 边界写在界面上（能做/不做），包括"手机现在打不开这个应用"这句实话；
    ⑤ 手机侧引擎是**独立文件**（Node 里能真跑，见 `tests/test_offline_phone_line.py`），
       页面真引它、service worker 真预缓存它（不然离线时它自己就取不到）。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    engine = WEB_ENGINE.read_text(encoding="utf-8")
    sw = WEB_SW.read_text(encoding="utf-8")

    # ⑤ 引擎是独立文件，页面引它、sw 预缓存它
    assert "TFOffline" in engine and "'timeflow-sync'" in engine
    assert "indexedDB" in engine and "putCache" in engine and "clearQueue" in engine
    assert '<script src="/offline.js"></script>' in html, "页面没引离线引擎"
    assert '"/offline.js"' in sw and "timeflow-v2" in sw, "service worker 没预缓存离线引擎"

    # ② 离线页排在 /api/config 之前（断网时它是唯一还能打开的一页）
    render_fn = _fn_body(html, "render")
    assert "name==='offline'" in render_fn and "renderOffline" in render_fn
    assert render_fn.index("name==='offline'") < render_fn.index("api('/api/config')"), \
        "离线页必须在拉配置之前处理（否则断网时它渲染不出来）"

    # ① 只有网络失败才兜底
    api_fn = _fn_body(html, "api")
    assert "__offline=true" in api_fn, "api() 没标出「连不上」"
    assert "rememberForOffline(path,opts,data)" in api_fn, "读过的清单没留一份给离线看"
    wq = html.split("async function writeOrQueue(", 1)[1].split("\n}\n", 1)[0]
    assert "e.__offline" in wq, "入队兜底必须只认「连不上」"
    assert "method:'POST'" not in wq, "兜底逻辑里不该出现具体接口（它只负责决定走哪条路）"

    # ③ 同一个格式 + 导出不清空 + 幂等
    offline_view = html.split("async function renderOffline(m){", 1)[1]
    assert "timeflow-sync" in offline_view, "界面上要说明包与电脑↔电脑同格式"
    assert "<b>不会清空</b>" in offline_view and "<b>重复导入是安全的</b>" in offline_view
    clear_fn = html.split("async function offlineClear(){", 1)[1].split("\n}", 1)[0]
    assert "confirmAsk(" in clear_fn, "清空队列是不可逆动作，必须二次确认"
    assert "offline-export" in offline_view and "offline-copy" in offline_view, \
        "下载失败要有兜底（复制包文本）"
    # 入队之后要**就地改缓存**：界面读的是缓存那份清单，不改它就会"看着没反应"
    # （点两次不会错账 —— 账本按 task id 去重 —— 但界面不该骗人）。任务与习惯各一处。
    toggle = html.split("async function toggleDone(id,isDone){", 1)[1].split("\n}", 1)[0]
    assert "t.status=isDone?'未开始':'完成'" in toggle, "离线勾完成后没更新缓存那一行"
    habit_fn = html.split("async function offlineHabitToggle(id){", 1)[1].split("\n}", 1)[0]
    assert "h.logs=" in habit_fn, "离线打卡后没更新缓存（连点两次分不出打卡/取消）"

    # ④ 边界说在界面上
    for needle in ("不做：离线", "同一 WiFi 直连", "缓存里最近看到的那份清单"):
        assert needle in offline_view, f"离线页缺少边界说明：{needle}"

    # 入口与动作：视图名在 VIEWS、左栏有入口、动作都注册了
    views = re.search(r"const VIEWS=\[([^\]]*)\]", html)
    assert views and "'offline'" in views.group(1), "offline 不在视图白名单里"
    rail = html.split('class="rail"', 1)[1].split("</nav>", 1)[0]
    assert 'data-view="offline"' in rail, "左栏没有「离线记」入口"
    for action in ("offline-task-add", "offline-memo-add", "offline-feedback-save",
                   "offline-habit", "offline-done", "offline-export", "offline-copy",
                   "offline-clear"):
        assert f"'{action}':" in html, f"动作 {action} 没注册"
    # 提示条（手机上没有左栏，靠它进得去）与断网/回网两个监听
    assert 'id="offlineBar"' in html and "function paintOfflineBar()" in html
    assert "addEventListener('offline'" in html and "addEventListener('online'" in html
    assert "view(offlineNow()?'offline':'today')" in html, "断网首屏没落到离线页"
    # 样式只住 app.css（R1）
    css = WEB_CSS.read_text(encoding="utf-8")
    assert ".offline-bar {" in css and ".offline-bar[hidden]" in css


def test_lan_pairing_is_wired_and_the_code_stays_home() -> None:
    """T-G10b（SR-NF17 场景 ②）：局域网访问 + 配对码在界面上的那一半。

    四条口径：
    ① 配对码带在每个请求的**头上**（`X-Timeflow-Pair`），**对不对由后端说了算** ——
       前端不自己判、更不把"看起来对的码"留在本机；
    ② 没配对时不是"空页 + 一句操作失败"，而是**整页的配对墙**：说清发生了什么、码在哪；
    ③ 设置页那一节要**跟着后端的事实**走：开着才给地址、**本机才显示配对码**
       （非本机时界面上必须写"看不到，这是故意的"，且不摆"换一个"那颗只有本机才该有的按钮）；
    ④ 代价写在界面上（同一 WiFi 下别的设备也可能访问到 / 不是加密）。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")

    # ① 头上带码 + 只有"配对码"这一类 401 才走配对流程
    api_fn = _fn_body(html, "api")
    assert "function pairCode()" in html and "PAIR_KEY='tf_pair'" in html
    assert "X-Timeflow-Pair" in api_fn and "pairCode()" in api_fn
    assert "isPairCall" in api_fn, "配对接口自己不能再触发配对流程（会递归）"
    assert "pairNeeded=true" in api_fn and "pairNeeded=false" in api_fn
    # ② 配对墙 + 输入 + 清掉本机记的码
    render_fn = _fn_body(html, "render")
    assert "pairNeeded&&mySeq===renderSeq" in render_fn and "pairWallHTML()" in render_fn
    wall = html.split("function pairWallHTML(){", 1)[1].split("\n}", 1)[0]
    for needle in ('id="pairWall"', "pair-ask", "pair-clear", "只在那台电脑上显示"):
        assert needle in wall, f"配对墙缺少 {needle}"
    ask_fn = html.split("async function askPair(){", 1)[1].split("\n}", 1)[0]
    assert "/api/lan/pair" in ask_fn, "验码必须问后端（前端不自己判）"
    assert "setPairCode('')" in ask_fn, "后端说不对就不该把错的码留在本机"

    # ③ 设置页那一节：跟后端事实走
    setting = html.split("async function renderSetting(m){", 1)[1].split("\n}", 1)[0]
    assert 'id="set-lan"' in setting and "局域网访问（手机连电脑）" in setting
    assert "api('/api/settings/lan')" in setting, "这一节的数据要来自后端"
    assert "lan.code_visible" in setting and "lan.code_visible?'':" not in setting
    for needle in ("这是故意的", "copy-lan", "lan-rotate", "lan.lan_open"):
        assert needle in setting, f"设置页那一节缺少 {needle}"
    # 不是本机就不摆"换一个"（后端也会 403 —— 两头一致）
    assert re.search(r"lan\.code_visible\?`<button[^`]*lan-rotate", setting), \
        "「换一个配对码」只该在本机出现"
    for action in ("pair-ask", "pair-clear", "copy-lan", "lan-rotate"):
        assert f"'{action}':" in html, f"动作 {action} 没注册"

    # ⑤ 校园网/热点场景（T-G10c，用户就是校园网）：排查顺序要**热点在前**，
    #    并且有一支"本机自检"（查得到的查、查不到的直说）
    assert "怎么让手机连上（按顺序试）" in setting
    assert "移动热点" in setting and "192.168.137.1" in setting
    assert "客户端隔离" in setting and "校园网" in setting, "要主动提校园网，别让人自己猜"
    assert setting.index("移动热点") < setting.index("客户端隔离"), "先给能通的那条"
    assert 'data-action="lan-selfcheck"' in setting and 'id="lanSelfCheck"' in setting
    assert "'lan-selfcheck':" in html, "动作 lan-selfcheck 没注册"
    check_fn = html.split("async function runLanSelfCheck(){", 1)[1].split("\n}", 1)[0]
    assert "/api/lan/selfcheck" in check_fn and "r.hint" in check_fn and "r.caveat" in check_fn, \
        "自检要把后端说的（hint/caveat）原样显示，不自己编结论"

    # ④ 代价写在界面上（离线页 + 设置页）：
    #    "不是加密、也不挡同 WiFi 抓包"这句由**后端一处给**（`core/lan.py` 的 note）——
    #    界面只负责显示，不复述规则（否则两处会漂）。后端那句由 test_lan_pairing_line.py 钉。
    assert "同一个 WiFi" in html and "不涉及公网" in html
    assert "noteHTML(lan.note" in setting, "设置页要显示后端给的边界说明"
    offline_view = html.split("async function renderOffline(m){", 1)[1]
    assert "--lan" in offline_view, "离线页要告诉人：手机能打开它靠的是 --lan（默认关）"


def test_repeat_rhythm_view_is_wired_and_kind() -> None:
    """T-G25（SR-F1.5b）：重复任务的节奏要看得到 —— 规格原话「节奏可用时间热力图管理」。

    四条口径：
    ① 统计页真接这个投影（`/api/insights/repeat-rhythm`），空的时候给空态而不是空白；
    ② 三种格子状态**形状+颜色都不同**（实心/空心/淡灰）—— 只靠颜色区分，色觉差异就读不出来；
    ③ 数字只给「完成 K / 排期 M」，**不给百分比、不设目标**（约定层：温和不施压）；
    ④ 说明用**后端给的那句**（`note`），界面不复述规则（改口径只改一处）。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    stats = html.split("function renderStats(m){", 1)[1].split("\nlet hmCells", 1)[0]
    assert "api('/api/insights/repeat-rhythm?days=56')" in stats, "统计页没接重复节奏投影"
    assert "重复节奏（近 ${rhythm.days} 天）" in stats
    assert "emptyState('还没有重复任务" in stats, "没有重复任务时要有空态，不是一片空白"
    # T-G34 起这句要走 `noteHTML`（后端说明文字里用 `**重点**` 标重点，`esc` 会把它原样画成星号）
    assert "noteHTML(rhythm.note)" in stats, "说明要用后端给的那句（别在界面复述口径）"

    row = html.split("function repeatRhythmRow(s){", 1)[1].split("\n}", 1)[0]
    # ★ T-G55 改了口径：三种状态的**画法**从标记里的内联属性搬进了 `app.css` 的类
    # （`.chart-cell-done` / `-missed` / `-off-state`）。所以这里判"标记有没有把三态分开"
    # + "样式表有没有给出三种不同的画法" —— 而不是判标记里还写着 `stroke-width="1.5"`
    # （那正是 T-G55 要消灭的东西：值住在标记里，令牌与一致性门都够不着）。
    assert ("chart-cell-done" in row and "chart-cell-missed" in row
            and "chart-cell-off-state" in row), "三种状态要三种类（实心 / 空心红边 / 空心灰边）"
    css = WEB_CSS.read_text(encoding="utf-8")
    assert ".chart-cell-missed { fill: none; stroke: var(--accent); stroke-width: 1.5 }" in css, \
        "空心格要有描边（不只靠颜色）—— 这条笔宽现在住在样式表里"
    assert ".chart-cell-off-state { fill: none; stroke: var(--border); stroke-width: 1 }" in css
    assert "完成 ${s.done} / 排期 ${s.planned}" in row, "只给这两个数"
    for bad in ("达标", "目标", "比例"):
        assert bad not in row, f"重复节奏不该出现「{bad}」（温和不施压，只描述事实）"


def test_pomodoro_length_comes_from_config_and_only_notifies() -> None:
    """T-G23（FLOW-3 验收第 1 条）：番茄钟要能**倒计时**、到点要**提示**，而且**不自动结束**。

    起因（回头看查出来的）：`flows.md` 的 FLOW-3 验收写着「番茄钟能倒计时并在结束时自动提示
    或结束」—— 而这条**从来没成立过**：计时器一直正计时（`fmt(elapsed)`），
    `pomodoro_minutes` 只在按钮
    文案里出现；更要命的是 `/api/config` **根本没暴露**这个配置项，界面只能
    `cfg.pomodoro_minutes||25`，于是 config.toml 里改过的值永远不生效（配置项是死的）。
    这里钉四件事：
    ① 倒计时用配置里的分钟数（番茄钟），到点后显示"已继续多久"（`+MM:SS`）；
    ② 普通计时仍是正计时（倒着数对"随便计一会儿"没意义）；
    ③ 到点**只提示一次**（按 session id 记），并且提示里写明"不会替你停"；
    ④ 到点**不改任何数据**：不自动发 finish、不发新请求（配置那次拉取除外）。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    # 只取"我开的"那一支（镜像函数排在它后面，别混进来）
    active_fn = html.split("function renderActive(el,active){", 1)[1]
    active_fn = active_fn.split("function renderActiveMirror", 1)[0]
    assert "focusCfg*60" in active_fn, "倒计时要用配置里的番茄钟分钟数"
    assert "sec<total?fmt(total-sec):'+'+fmt(sec-total)" in active_fn, \
        "到点前倒计时、到点后显示已继续多久"
    assert "pomoNotified!==active.id" in active_fn, "一轮只提示一次（按 session id 记）"
    assert "不会替你停" in active_fn and "到点了（${focusCfg} 分）" in active_fn
    assert "api('/api/config')" in active_fn, "分钟数从 /api/config 来（不写死在界面里）"
    # ④ 到点这一支不许碰数据：提示块里没有请求、没有 POST（不自动结束、不改状态）
    notice = active_fn.split("if(total&&sec>=total&&pomoNotified!==active.id){", 1)[1]
    notice = notice.split("};", 1)[0]
    assert "api(" not in notice and "method:'POST'" not in notice, f"到点提示不该发请求：{notice}"
    assert active_fn.count("api(") == 2, \
        f"这一段只该有两次只读请求（配置 + 任务名）：{active_fn.count('api(')}"

    # ①' 后端必须真的暴露它（否则界面拿不到配置值，`||25` 会把自定义时长吃掉）
    root = Path(__file__).resolve().parent.parent
    api_src = (root / "src" / "timeflow" / "api" / "app.py").read_text(encoding="utf-8")
    assert '"pomodoro_minutes": settings.focus.pomodoro_minutes' in api_src
    assert "pomodoro_minutes = 25" in (root / "config.example.toml").read_text(encoding="utf-8"), \
        "配置项要在模板里（否则没人知道有它）"


def test_cross_device_focus_mirror_is_read_only() -> None:
    """T-G20（SR-F3.4 / N17）：跨端同步专注 = **实时启动 + 结束时再同步**。

    口径与两条硬边界（都是"看起来能用其实是坑"的写法）：
    ① 判断"这是不是我开的"靠 `device_id`（我自己发的那份客户端号），
       老数据（None）必须算"我开的" —— 否则「重开页面恢复计时」这条既有行为会退化成"别处正在专注"；
    ② 镜像**只读**：镜像卡里一个 `data-action` 都不许有（加"结束"= 让这台设备去停另一台；
       加"我也开始"= 同一段时间记两笔投入）；
    ③ 实时性靠**轮询**（本地单机没有服务器可推）：间隔是常量、只在页面可见且在线时问、失败静默；
    ④ 结束**不做实时推**：只发既有 finish 请求，记录各自入库后走同步包 —— 这里不新增任何推送。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")

    # ① 客户端身份：自己发的号（不是数据库主人号、也不是手机包号）
    assert "const CLIENT_KEY='tf_client'" in html and "function clientId()" in html
    assert "TFOffline.deviceId" in html, "手机（局域网打开的页面）要沿用它自己的 ph- 号"
    start_body = _fn_body(html, "startFocus")
    assert "device_id:clientId()" in start_body, "开始专注必须带上「谁在计时」"
    start_for = html.split("async function startFocusFor(taskId){", 1)[1].split("\n}", 1)[0]
    assert "device_id:clientId()" in start_for, "从任务开始专注也要带（两条入口都要）"

    # ①' 老数据算"我开的"（`device_id` 为假值 → 走自己那一支）
    active_fn = html.split("function renderActive(el,active){", 1)[1]
    active_fn = active_fn.split("\nfunction teamButtonsHTML", 1)[0]
    guard = "if(active.device_id&&active.device_id!==clientId())"
    assert f"{guard}{{renderActiveMirror(el,active);return}}" in active_fn, \
        "镜像判定必须是「有来源 且 不是我自己」——空白/None 仍归自己"

    # ② 镜像只读：抽出来单独看，里面不许有任何动作按钮
    mirror = html.split("function renderActiveMirror(el,active){", 1)[1]
    mirror = mirror.split("\nfunction teamButtonsHTML", 1)[0]
    assert "别处正在专注" in mirror and "只看不动" in mirror
    assert "data-action" not in mirror, f"镜像卡里不许有按钮：{mirror[:200]}"
    assert "renderActiveMirror" in active_fn
    # `#clock` 的唯一主人仍是本机计时器（R3 护栏）：镜像用另一个 id 照对面的秒数
    assert 'id="clockPeer"' in mirror and 'id="clock"' not in mirror
    assert html.count('id="clock"') == 1, "镜像不该再引入一个 #clock"

    # ③ 轮询：常量 + 只在可见且在线时问 + 失败静默 + 变了才重画
    assert "const FOCUS_POLL_MS=10000" in html
    poll = html.split("function startFocusPoll(){", 1)[1].split("\n}", 1)[0]
    assert "document.hidden" in poll and "offlineNow()" in poll, "后台/离线时不问"
    assert "catch(e){return}" in poll, "轮询失败要静默（别每 10 秒弹一次错）"
    assert "focusSeenKey" in poll and "return;" in poll, "指纹没变就别重画"
    assert "startFocusPoll();" in html, "首屏之后要真的把它开起来"

    # ④ 结束不做实时推：只有既有的 finish 请求，没有新增推送/轮询上报
    finish_fn = _fn_body(html, "finishFocus")
    assert "${active.id}/finish" in finish_fn and "device_id" not in finish_fn
    assert "EventSource" not in html and "WebSocket" not in html, "别为这件事引入推送通道"


def test_ui_does_not_explain_itself() -> None:
    """界面不解释（T-G49，用户 2026-09-24 定）—— 反向棘轮：那些"教用户怎么用/为什么这么设计"
    的长句删了就**不许再回来**。

    为什么要有这条：这类句子不是一次失误，是一个**习惯** —— 每加一个功能就顺手写一段
    "为什么这么算"（「不折算成投入时间（时间折算只在有真实时长时才算）」）。逐个删完不留钉子，
    下一个窗口会照着同一套直觉再写一遍。所以这里钉的是**具体句子**（不是长度阈值）：
    长度阈值要等清理全部落地、允许表稳定之后再上（见 `复盘/界面不解释-T-G49.md` §5）。

    规则本身写在 `docs/specification/conventions.md` 的「界面文案」一节。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")

    # ① 空态：不写怎么用、不写为什么、不写评价。旁边就有输入框/按钮的两处 → 一个字的占位都不留
    gone_empty_states = [
        "还没有步骤。拆成小步",                      # 40 字（任务详情·步骤）
        "还没有附件：可以挂作业要求网页",              # 26 字（任务详情·附件）
        "还没有记录（完成、撤销、删除",                # 27 字（任务详情·记录）
        "今天还没复习过卡。点上面的",                  # 33 字（复习）
        "没有到期复习，轻松一下",                     # 评价词
        "没有逾期，很好",                            # 评价词
        "今天还没有任务，挑一件加进来吧",              # 劝告
        "还没有习惯；建一个，明天就能看到热力图",       # 20 字
        "还没有成绩记录：录入后",                     # 32 字
        "还没有挂到这门课的任务：",                    # 35 字
        "还没有重复任务：给一件事设个",                # 28 字
        "还没有可看的维度 —— 去设置页",               # 24 字
        "还没有分配出去的任务。在任务卡片或详情里点",   # 38 字
        "还没有备份（起一次服务就会有一份）",           # 17 字
        # T-G55 补的三条**图表口径解释句**（不是空态，是同一条规则里"数字口径"那一半）：
        # 用户 2026-09-24 先在「也全删 / ≤8 字 / 留着」里选了「≤8 字」，2026-09-25 又改成**全删** ——
        # 所以这一档现在**界面上一个字都不留**（长句与短句都不许回来），
        # 事实本身住在 `docs/user-guide.md` 与后端契约测试里。
        # 改动前它们各自钉在 `tools/ui_flow_check.mjs` 第 ⑥ 条流、本文件
        # `test_academic_vs_self_chart_is_wired` 以及 6 份渲染黄金（today ×3 / stats ×3）。
        # ★ 这几条钉的是**整句**，所以代码注释里也不许把整句抄回去（抄了就是红 —— 故此处不写全句）。
        "只统计今天的清单与今天完成的",
        "任务可属多个分组，各组之和可能大于总投入",
        "手动投入不参与这张图",
        # 短的那一版也不许回来（就是"先改短、再全删"中间那一步的措辞）
        "只算今天",
        "任务可属多组",
        "手动投入不计入",
    ]
    for needle in gone_empty_states:
        assert needle not in html, (
            f"空态/口径不许出现在界面上：{needle!r}（见 conventions.md「界面文案」）"
        )

    # ② 旁边有控件的空态：整块占位都不留（不是"留一句短的"，是**不渲染**）
    assert "subtaskList||''" in html or "subtaskList||" in html, "步骤空态：直接不渲染"
    assert "还没有步骤" not in html and "还没有附件" not in html

    # ③ 设计意图不强调（"我为什么这么设计"不是给用的人看的）
    for needle in ["不用于跨人比较", "标记只是提醒自己", "不重新定义"]:
        assert needle not in html, f"设计意图不许写进界面：{needle!r}"

    # ④ 教学性引导语删掉，但那三步操作与两个按钮**留着**（用户选的是"留卡、删解释句"）
    assert "第一次用，按这三步走就行" in html, "引导卡的标题留着"
    assert 'data-action="guide-start"' in html and 'data-action="guide-done"' in html
    assert "不用一次做全，这只是个起点" not in html, "引导卡里的解释句要删"




def test_orphan_routes_are_shown_in_the_setting_page() -> None:
    """T-G56：5 条「无界面路由」里的 1/2 接进设置页 —— **只读展示 + 一个"读一次"按钮**。

    为什么钉它：这两条路由（全量提醒列表 OP-47 / 冲突日志 OP-40·OP-41）在契约里早就写着
    「入口：设置页」，却一直没有界面入口 —— 于是它们既不被门禁覆盖，也没人知道它们存在。
    这里钉三件事：① 两节真在设置页里（各带锚点 id，好在「常用」区做跳转）；
    ② 各有一个动作按钮（`remind-list` / `sync-log`）—— 注册那半由上面那条通用断言兜着；
    ③ 两条路由的路径真在模板里（数据是**点一下拉**的，不进首屏 `Promise.all`：
    它们都是"看时才要"、而且会变，点一下天然就是刷新）。

    ★ 边界（不许假装验证过）：这里只钉**标记层**。点下去之后的渲染要真浏览器才验得了 ——
    目前靠人工/后续的流层覆盖，别把它说成"已经机器验过"。
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    for needle in ('id="set-remind-list"', 'data-action="remind-list"', 'id="remindList"',
                   'id="set-conflict-log"', 'data-action="sync-log"', 'id="syncLog"'):
        assert needle in html, f"设置页缺了 T-G56 的落点：{needle}"
    assert "/api/reminders" in html and "/api/sync/logs" in html
