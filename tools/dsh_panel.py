#!/usr/bin/env python
"""dsh_panel —— 全局面板：把工作台三个只读面接进 DSH 的全局座位（卡 221/240/242/244/247）。

## 为什么有它

用户令：*「我大概都是在你 DSH 这里工作，所以尽量不要让我切来切去」*；2026-10-14 又令：
*「就是可以在 dsh 开出来看…，开到**左边栏**里」*。方案里三个「面」的第 3 个是**全局面板**：
`dsh-client-ui-layout` 暴露一个 root 作用域的 **`main` keyed 座**（`ctx.layout.selectPanel(id)`，
`null` = 会话）。本工具管**面板**那个面 —— 产出「一份能在 DSH 里被照做的面板插件」。

## 交什么（**只在仓库侧产出**）

卡 221 只注册了一个座位（工作台看板），且**宿主→浏览器那条缝不存在**（浏览器半读的
`ctx.workbenchBoardSnapshot()` 没人提供）。卡 240（T-G358）把**三个座位**接进 DSH 并补上
**一条只读缝**。卡 242（T-G363）再把三行改成**快捷入口**：

1. 一个**面板插件包**的源码（`--emit` 落盘）：`package.json` + `lib/index.js`（宿主半）+
   `lib/client.js`（浏览器半）+ `cordis.patch.yml`（`dsh.bundle.patch` 的包内补丁层）+
   `README.md`（安装/接线说明）。
2. 一份**安装/接线说明**（`INSTALL_DOC`；`--doc` 打印，`--emit` 落成包内 `README.md`）。

★ 卡 242 的三件事（都钉了判据）：① 三行默认**开真实页面**（`ctx.sidebarRight.openTab(
  "browser", { params: { url } })`，依据写在浏览器半源码注释里）；目标页连不上 ⇒
  显式写「没起 + 怎么起」。② 图标**不许再用文字符号**（`▦` 之类）—— 内联 SVG（16px、
  currentColor），几何与外壳自己的图标同口径（依据见 `makeIcon` 注释）。
  ③ 包形态改成官方 `dsh.bundle.patch`（与 `dsh.client` 共存）。

★ 卡 244 的四件（对抗复核点出的缺口，逐条照收，都钉了判据）：
  ① **逃生门**：`openTab` 内部先 `require()` 屏幕会话，无会话抛
  `sidebarRight: no session surface is mounted`（sidebar-right/lib/client.js:6385-6396、
  :6744-6752）；而全局面板占 `main` 时「屏幕会话」恰为 undefined（service.d.ts:141-143）
  ⇒ 点左栏行立刻 `openTab` 第一次就会抛。改成：订 `ctx.sidebarRight.mounted` 记最后在屏的
  sessionId，开页优先 `openTabIn(sessionId, …)`（对未 adopted 会话静默无操作，
  client.js:6418-6421）；拿不到才退回 `openTab`，catch + 如实报错保留。
  ② **真·兼容字段**：真正被强制的是 `peerDependencies` 里名为 `@deepseek-ai/dsh`（或以
  `@deepseek-ai/dsh-` 开头）的 semver 范围（dsh-app-boot/lib/index.js:286-304，前缀过滤
  :294）；`engines.dsh` 是声明性、**不被强制**（dsh-package-manifest/README.zh.md:93）。
  ③ **包内图标**：产出 `icon.svg`（相对路径引用、远小于 256 KiB、不引绝对路径/URL，
  host-plugin.md:45），清单写 `icon`；左栏行 glyph **继续内联 SVG**（两个面不混）。
  ④ **右栏页签 + 自带角标**：三个目标各注册一个官方右栏页签（`sidebarRightTabs` 注册面 +
  `sidebar.right.pane.tab` keyed 座），**探到 `ctx.get("sidebarRight")` 才注册**；
  核心行条目只有 `{id, order, label}`、没有角标槽（sidebar/client.js:454-461）⇒
  「未起」小点画进**自己的 glyph 内容**（probeStore），不声称是核心角标能力。

★ 卡 247（T-G368，落 复盘/DSH插件-可抄清单.md §六的三条）：① 右栏页签 id **带包名前缀**
  （`dsh-client-ui-workbench-panel:board` / `:timeflow` / `:zentao`，dsh-session-diff:file
  同型）+ `keepMounted: true` 常驻（sidebar-right/lib/client.js:5522）+ 正文 = 真实页面入口；
  ② 包级显示链路：`locale/zh.json` / `locale/en.json`（meta + 三座位）+ 清单 `exports`
  补 `./package.json` 与 `./locale/*.json`；③ 补丁层三纪律（顶层 YAML 数组 / 三处
  id-name 一致 / 「删掉补丁层 = 插件不加载」写给人看）—— `check()` 逐条钉死；
  ④ （A273 已删）左栏底部入口 —— 用户 2026-10-17 要求去掉左下角那块；
     三行页自带「一键启动 / 全部起 / 分别停」，不留重复入口。

★ 卡 253（T-G374）：
  ① 「没起」状态带**一键启动**（三个目标各一条动作，白名单写死 = `tools/stack.py`
  组件表里的 `board` / `timeflow` / `zentao`；**没有透传任意命令的口子**）；
  ② 反馈如实：先写「已发起启动」⇒ 宿主半跑 `stack.py`（它**探真端口**）⇒ 真起来才改口
  「已起（端口 N；映像 X）」；超时给原话 + 日志路径；
  ③ 面板里加「全部起 / 停这一件」+ 最近动作（`gates/diag/stack-actions.log`）+ RSS 账本；
  ④ 面板改成**点开才读**（没有常驻定时轮询）。

★ **只读**：面板的数据来自卡 207 / 卡 222 / 卡 223 的**唯一读数器**；面板**不写仓库、
  不派工人**（用户早先拍过：拖动只写意图、主控执行）。卡 253 把这条**精确化**：
  允许起停 `stack.py` 组件表里那几件**服务**，仍然禁止派工人 / 写仓库 / 改 `~/.dsh`；
  `check()` 把两面**分别**钉成硬判据。
★ **加载失败要看得见**：数据源缺失 / 读数器非零 / 超时 ⇒ 面板与工具**都显式报错**
  （`data-wb-state="error"`），**绝不用空板子冒充成功**。
★ **不许去改用户的 `~/.dsh` 配置**（那是用户的地盘）；说明只交「能被照着做的事」。

## 用法

    python -X utf8 tools/dsh_panel.py --check              # 清单/schema/座位/只读/失败可见 自检
    python -X utf8 tools/dsh_panel.py --emit <目录>        # 落盘那套插件源码（成稿）
    python -X utf8 tools/dsh_panel.py --doc                # 打印安装/接线说明
    python -X utf8 tools/dsh_panel.py --board --root <根>  # 只读读数（宿主契约的参考实现）

退出码：`0` 绿；`1` 自检不过；`2` 用法/环境错误。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# `python -P -X utf8 tools/dsh_panel.py` 也要能 import pool：
_TOOLS_DIR = str(Path(__file__).resolve().parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

# 卡 253：动作白名单的**真源** = tools/stack.py 的组件表（面板只许起停表里那几件服务）。
import stack  # noqa: E402
from pool.no_window import NO_WINDOW  # noqa: E402  ★ 卡 148：子进程一律不弹窗（唯一真源）

ROOT = Path(__file__).resolve().parent.parent

#: 面板包名（本地目录即可，⏳ 不必发布 npm）。
PACKAGE_NAME = "dsh-client-ui-workbench-panel"
PACKAGE_VERSION = "0.0.5"

#: 落盘时每块内容相对包根的位置。
HOST_REL = "lib/index.js"
CLIENT_REL = "lib/client.js"
MANIFEST_REL = "package.json"
README_REL = "README.md"
PATCH_REL = "cordis.patch.yml"  # 卡 242：dsh.bundle.patch 指向的包内补丁层
ICON_REL = "icon.svg"  # 卡 244：包内图标（清单 icon 用相对路径指它）
# 卡 247：包级显示链路 —— 核心不激活插件就能读的标题/说明（配清单 exports 的 ./locale/*.json）。
LOCALE_ZH_REL = "locale/zh.json"
LOCALE_EN_REL = "locale/en.json"

#: 卡 244：`peerDependencies["@deepseek-ai/dsh"]` 的范围 —— 故意写**宽**：
#: 只表达「需要 dsh 运行时」，不锁小版本。实测运行时 `0.2.0-rc.2`（pre-release），
#: app-boot 用 `semver.satisfies(runtimeVersion, range, { includePrerelease: true })`
#: （dsh-app-boot/lib/index.js:295-296）⇒ `>=0.2.0-rc` 覆盖它。
DSH_PEER_RANGE = ">=0.2.0-rc"

#: 读数子进程超时上限（秒）；超时要如实报错，不静默返空。
#: ★ 本仓卡树多，真读数实测 ~14s；留 30s 余量。
BOARD_TIMEOUT_SECONDS = 30

#: 六块读数的名字（与 pipeline_view 的顶层键一致）。
SECTIONS = ("cards", "gates", "verdicts", "leases", "fences", "worktrees")

#: 唯一的那条只读缝的前缀（同源路由都在它下面）。
SEAM_PREFIX = "/dsh-panel"

#: 只读不变式 —— 面板源码里出现这些词就说明它越界了（写仓库 / 起工人）。
FORBIDDEN_WRITE_TOKENS = (
    "writeFile",
    "rmSync",
    "unlinkSync",
    "mkdirSync",
    "appendFileSync",
    "writeFileSync",
    "wb_task",
    "wb_dispatch",
    "git commit",
    "cordis_define",
    "cordis_run",
)


@dataclass(frozen=True)
class Seat:
    """一个座位 —— `main` keyed 座的 key = `sidebar.panellist` 的行 id = 会话内工具名。"""

    key: str  # 座位 key（= main key = 左栏行 id = 会话内工具名）
    order: int  # 左栏里的次序
    label_zh: str
    label_en: str
    # 卡 242：图标 = 内联 SVG 的 path 列表（(d, fill) 对；fill 空 = 不填）。
    # ★ 不许再用文字符号（▦ 之类）当图标 —— 判据 `_check_client` 咬。
    icon: tuple[tuple[str, str], ...]
    icon_round: bool  # 是否 strokeLinecap: "round"（甘特条那枚要）
    route: str  # 只读缝上的路径（同源、只 GET）
    script_rel: str  # 只读工具的仓库相对路径
    needs_root: bool  # 是否把 `--root <root>` 传给它
    locale_key: str  # 浏览器半 locale 文案键
    render: str  # 浏览器半渲染器名（内嵌读数分支，卡 242 保留）


# ---- 图标几何：逐字取自外壳自己的图标（卡 242 的依据） ----
# 依据 @deepseek-ai/dsh-client-ui-primitives/lib/index.js：
#   IconGaugeOutlineArtwork :2050（工作台状态）、IconClockOutlineArtwork :2017（timeflow）；
#   禅道为同口径自画的甘特条。口径：viewBox "0 0 16 16"、fill none、stroke currentColor、
#   strokeWidth 1（Regular）、aria-hidden。长 path 拆隐式拼接，别撞 ruff E501。
_ICON_GAUGE_ARC = (
    "M3.4041 13.096C2.49514 12.187 1.87614 11.0288 1.62537 9.76798C1.37459 8.50716 1.50331"
    " 7.20028 1.99525 6.01261C2.48719 4.82494 3.32025 3.80981 4.3891 3.09557C5.45795 2.38134"
    " 6.71458 2.00008 8.0001 2C9.28563 2.00008 10.5423 2.38134 11.6111 3.09557C12.68 3.80981"
    " 13.513 4.82494 14.005 6.01261C14.4969 7.20028 14.6256 8.50716 14.3748 9.76798C14.1241"
    " 11.0288 13.5051 12.187 12.5961 13.096"
)
_ICON_GAUGE_NEEDLE = "M8 8.49994L11.6114 4.88855"
_ICON_GAUGE_DOT = (
    "M8 9.75C8.69036 9.75 9.25 9.19036 9.25 8.5C9.25 7.80964 8.69036 7.25 8 7.25C7.30964"
    " 7.25 6.75 7.80964 6.75 8.5C6.75 9.19036 7.30964 9.75 8 9.75Z"
)
_ICON_CLOCK_FACE = (
    "M8 14C11.3137 14 14 11.3137 14 8C14 4.68629 11.3137 2 8 2C4.68629 2 2 4.68629 2 8"
    "C2 11.3137 4.68629 14 8 14Z"
)
_ICON_CLOCK_HAND = "M8 4.31V8.46L11 10.08"

#: 四格仪表盘：左上/右上/左下**三个描边格**合成一条路径（省行也省一次渲染），
#: 右下那格单独一条、用 `currentColor` 填实（视觉重心落在"右下"）。
_ICON_TILES_OUTLINE = (
    "M3.1 1.6h3.6a1.5 1.5 0 0 1 1.5 1.5v3.6a1.5 1.5 0 0 1-1.5 1.5H3.1a1.5 1.5 0 0 1-1.5-1.5"
    "V3.1a1.5 1.5 0 0 1 1.5-1.5zM9.3 1.6h3.6a1.5 1.5 0 0 1 1.5 1.5v3.6a1.5 1.5 0 0 1-1.5 1.5H9.3"
    "a1.5 1.5 0 0 1-1.5-1.5V3.1a1.5 1.5 0 0 1 1.5-1.5zM3.1 7.8h3.6a1.5 1.5 0 0 1 1.5 1.5v3.6"
    "a1.5 1.5 0 0 1-1.5 1.5H3.1a1.5 1.5 0 0 1-1.5-1.5V9.3a1.5 1.5 0 0 1 1.5-1.5z"
)
_ICON_TILE_BR = (
    "M9.3 7.8h3.6a1.5 1.5 0 0 1 1.5 1.5v3.6a1.5 1.5 0 0 1-1.5 1.5H9.3a1.5 1.5 0 0 1-1.5-1.5"
    "V9.3a1.5 1.5 0 0 1 1.5-1.5z"
)
#: 分支树（主干 + 两个终点环 + 一条分枝到第三个环）。
_ICON_TREE = (
    "M5 2.9v10.2M6.5 4.4a1.5 1.5 0 1 1-3 0 1.5 1.5 0 1 1 3 0"
    "M6.5 11.6a1.5 1.5 0 1 1-3 0 1.5 1.5 0 1 1 3 0"
    "M6.4 4.4h3.05a2 2 0 0 1 2 2v1.15M12.9 9.4a1.5 1.5 0 1 1-3 0 1.5 1.5 0 1 1 3 0"
)
#: 沙漏（上下两条横梁 + 两个对顶漏斗）。
_ICON_HOURGLASS = (
    "M4.3 2.3h7.4M4.3 13.7h7.4"
    "M5.6 2.3v2.1c0 1.35 1.05 2.15 2.4 3.6 1.35-1.45 2.4-2.25 2.4-3.6V2.3"
    "M5.6 13.7v-2.1c0-1.35 1.05-2.15 2.4-3.6 1.35 1.45 2.4 2.25 2.4 3.6v2.1"
)

#: 三枚图标（(d, fill) 对）。
#: ★ 2026-10-15 用户当日指定方向：工作台 = **B（工业刻度·四格仪表盘）**、
#:   禅道 = **B（工业刻度·分支树）**、timeflow = **C（线条拟物·沙漏）**。
#:   三枚都按渲染处的 **16 网格**（`viewBox 0 0 16 16`、描边 1、圆头圆角）手画；
#:   本表只有 (d, fill) 两元组 ⇒ **圆用 arc 路径画成描边环**（不是 fill）；
#:   颜色只用 `currentColor` 或空 ⇒ 跟主题走，**不硬编码颜色**。
ICONS: dict[str, tuple[tuple[str, str], ...]] = {
    "workbench_board": (
        (_ICON_TILES_OUTLINE, ""),
        (_ICON_TILE_BR, "currentColor"),
    ),
    "zentao_gantt": ((_ICON_TREE, ""),),
    "timeflow_inbox": ((_ICON_HOURGLASS, ""),),
}

#: 卡 244：包内图标（`icon.svg`）—— 与左栏行的内联 SVG 是**两个面**：这份是给清单/
#: 市场读的包内文件（相对路径引用、远小于 256 KiB、不引绝对路径/URL，
#: cordis-plugin-development/.../host-plugin.md:45），几何与工作台那枚同口径。
ICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="16" height="16"'
    ' fill="none" stroke="currentColor" stroke-width="1.1" stroke-linejoin="round"'
    ' aria-hidden="true">\n'
    '  <rect x="1.9" y="1.9" width="5.1" height="5.1" rx="1.5"/>\n'
    '  <rect x="9" y="1.9" width="5.1" height="5.1" rx="1.5"/>\n'
    '  <rect x="1.9" y="9" width="5.1" height="5.1" rx="1.5"/>\n'
    '  <rect x="9" y="9" width="5.1" height="5.1" rx="1.5" fill="currentColor"/>\n'
    "</svg>\n"
)

#: ★ 座位表的**唯一真源** —— `main` key 与行 id 都由它生成，不许手抄。
#: 卡 242：label 改成三行快捷入口的文案（key **不许改名**）；glyph 字段废除，改 icon。
SEATS: tuple[Seat, ...] = (
    Seat(
        key="workbench_board",
        order=0,
        label_zh="工作台状态",
        label_en="Workbench status",
        icon=ICONS["workbench_board"],
        icon_round=False,
        route=f"{SEAM_PREFIX}/workbench-board",
        script_rel="tools/pipeline_view.py",
        needs_root=True,
        locale_key="panelWorkbenchBoard",
        render="WorkbenchBoard",
    ),
    Seat(
        key="zentao_gantt",
        order=1,
        label_zh="禅道",
        label_en="ZenTao",
        icon=ICONS["zentao_gantt"],
        icon_round=True,
        route=f"{SEAM_PREFIX}/zentao-gantt",
        script_rel="tools/zentao_gantt.py",
        needs_root=False,
        locale_key="panelZentaoGantt",
        render="ZentaoGantt",
    ),
    Seat(
        key="timeflow_inbox",
        order=2,
        label_zh="timeflow",
        label_en="timeflow",
        icon=ICONS["timeflow_inbox"],
        icon_round=False,
        route=f"{SEAM_PREFIX}/timeflow-inbox",
        script_rel="tools/timeflow_inbox.py",
        needs_root=True,
        locale_key="panelTimeflowInbox",
        render="TimeflowInbox",
    ),
)

#: 座位 key 的列表（顺序 = order）；判据逐项比它。
SEAT_KEYS: tuple[str, ...] = tuple(seat.key for seat in SEATS)
SEAT_BY_KEY: dict[str, Seat] = {seat.key: seat for seat in SEATS}
#: 三条只读缝路由。
ROUTE_PATHS: tuple[str, ...] = tuple(seat.route for seat in SEATS)
#: 兼容卡 221 的既有判据：第一座 = 老的面板 id。
PANEL_ID = SEAT_KEYS[0]

#: 卡 247：官方右栏页签 id —— **带包名前缀**（dsh-session-diff 的 "dsh-session-diff:file"
#: 同型，见 复盘/DSH插件-可抄清单.md §六.1）；后缀照卡规格点名：board / timeflow / zentao。
RIGHT_TAB_SUFFIX: dict[str, str] = {
    "workbench_board": "board",
    "zentao_gantt": "zentao",
    "timeflow_inbox": "timeflow",
}
RIGHT_TAB_IDS: dict[str, str] = {
    seat: f"{PACKAGE_NAME}:{suffix}" for seat, suffix in RIGHT_TAB_SUFFIX.items()
}


@dataclass(frozen=True)
class Target:
    """一个快捷入口的目标（卡 242）：与座位表同源，key 一一对应。"""

    seat: str  # 对应的座位 key
    url: str  # 真实页面的 URL（只许指本机）
    up_hint: str  # 没起时的「怎么起」（卡 242 的原话口径）
    #: 卡 253：这一目标的一键启动动作 = `tools/stack.py` 组件表里的**那一个**组件名。
    start: str = ""


#: ★ TARGETS 表（卡 242；卡 253 加 start 动作）—— 三条真实页面 URL，与 SEATS 的 key
#:   一一对应；目标页归别的卡/别的工具（wb_dash.py / serve.py / 禅道），面板只**指向**它们。
#:   ★ `start` 只许写 `tools/stack.py` 组件表里的名字（白名单见 ACTION_WHITELIST）。
TARGETS: tuple[Target, ...] = (
    Target(
        "workbench_board",
        "http://127.0.0.1:8787/",
        "python -X utf8 tools/stack.py start board（= tools/wb_dash.py，端口 8787）",
        "board",
    ),
    Target(
        "zentao_gantt",
        "http://127.0.0.1/zentao/",
        "python -X utf8 tools/stack.py start zentao（也可点 ZenPanel）",
        "zentao",
    ),
    Target(
        "timeflow_inbox",
        "http://127.0.0.1:8520/",
        "python -X utf8 tools/stack.py start timeflow",
        "timeflow",
    ),
)

#: 卡 253：面板动作缝的路径（与只读缝同前缀；只收 start / stop / start-all）。
ACTION_ROUTE = f"{SEAM_PREFIX}/actions"
#: 卡 253：服务现读 + 最近动作的路径（GET，只读；与 `stack.py status --json` 同口径）。
STACK_STATUS_ROUTE = f"{SEAM_PREFIX}/stack-status"

#: 卡 253：**写死**的服务白名单 —— 真源是 `tools/stack.py` 的组件表（worker 不在表里，
#: 所以面板永远派不出工人）。`start-all` 只是 `stack.py start`（无名字）的等价动作。
SERVICE_WHITELIST: tuple[str, ...] = tuple(stack.COMPONENTS)
ACTION_WHITELIST: dict[str, tuple[str, ...]] = {
    "start": SERVICE_WHITELIST,
    "stop": SERVICE_WHITELIST,
    "start-all": (),
}


def resolve_action(kind: str, name: str = "") -> list[str]:
    """卡 253：把面板动作翻成**写死的 argv**；白名单外一律拒绝并**点名**。

    ★ 只接受 `(kind, name)` 两个枚举值 —— 面板**没有"透传任意命令"的口子**，
      参数不是命令字符串，拼不进别的进程。反例（必须拒）：`rm -rf` / `board; rm -rf`。
    """
    if kind not in ACTION_WHITELIST:
        raise ValueError(f"拒绝：动作 `{kind}` 不在白名单 {tuple(ACTION_WHITELIST)} 里")
    if kind == "start-all":
        return [sys.executable, "-X", "utf8", "tools/stack.py", "start"]
    allowed = ACTION_WHITELIST[kind]
    if name not in allowed:
        raise ValueError(
            f"拒绝：`{name}` 不在 {kind} 白名单 {allowed} 里 —— 面板只许起停这几件服务"
        )
    return [sys.executable, "-X", "utf8", "tools/stack.py", kind, name]

#: 卡 242 判据：这些文字符号**不许**再当图标出现在浏览器半里（反例：塞回一个 ⇒ 红）。
TEXT_GLYPH_BAN: tuple[str, ...] = ("\u25a6", "\u25a4", "\u25a5")

#: 卡 251 判据：生成物里**不许出现硬编码颜色**（`#rrggbb` / `rgb(…)` / `hsl(…)`）。
#: 一切颜色走主题令牌 `var(--dsw-alias-…, 兜底)` 或 `currentColor` —— 深色主题下
#: 硬编码的浅底蓝条会变成一条刺眼白底（卡 251 的起因就是甘特条这一处漏网）。
#: 兜底值也用**关键字**（`transparent` / `currentColor`）：兜底写 `#f0f0f0` 一样会被这条咬。
COLOR_LITERAL_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")

#: 读数器（卡 207 的唯一读数器）；面板的宿主半只调它，不重写读逻辑。
READER_REL = Path("tools") / "pipeline_view.py"

#: 面板元数据（人读 + 自检用）。`check()` 逐字段验。
MANIFEST = {
    "id": PANEL_ID,
    "order": SEATS[0].order,
    "label": {"zh": SEATS[0].label_zh, "en": SEATS[0].label_en},
    "icon": {"kind": "inline-svg", "size": 16, "viewbox": "0 0 16 16"},
    # 卡 253：read_only = **不写仓库 / 不派工人**（不是「不起服务」——起停服务是允许的，
    # 白名单写死在 ACTION_WHITELIST，真源是 tools/stack.py 的组件表）。
    "read_only": True,
    "service_control": True,
    "data_source": "tools/pipeline_view.py --json（卡 207 的唯一读数器）",
    "seat": "root 作用域 `main` keyed 座（key=workbench_board）",
    "seats": list(SEAT_KEYS),
}

#: `dsh.client.inject`：本包依赖的**客户端插件包名**（顺序 = 装配面）。
#: ★ 判据：名单里每一项都必须是**自己声明了 `dsh.client` 的包** —— `dsh-client-modules` 只把
#:   「声明了 `dsh.client` 的活动 Loader 行」变成可加载的浏览器 bundle（它 README 的原话），
#:   一个不声明 `dsh.client` 的包**永远不可能是动态提供方** ⇒ 列进去等于声明一个没人能提供的依赖。
CLIENT_PACKAGE_DEPS = (
    "@deepseek-ai/dsh-client-ui-layout",
    "@deepseek-ai/dsh-client-ui-sidebar",
    # 卡 242：开真实页面走 ctx.sidebarRight.openTab —— 这个服务由 ui-sidebar-right 提供
    # （它自己声明了 dsh.client，实测 package.json；官方 schedule 插件也这样列它）。
    "@deepseek-ai/dsh-client-ui-sidebar-right",
    "@deepseek-ai/dsh-client-locale",
)

#: ★ 实测禁列（2026-10-14，读 DSH 安装里各包的 `package.json`）：
#:   `@deepseek-ai/dsh-client-ui-slots` 的 `dsh` 字段是 **null**（只有 `main`）⇒ 它是宿主侧的库、
#:   不是客户端插件行，**不许**出现在 `inject` 里。`slots` 这个**服务**由浏览器半的
#:   `inject = ["slots", …]`（cordis 服务名）拿到 —— 那是另一条机制，不要混。
#:   ★ 这条 2026-10-14 早上修过一次，晚上被卡 240 的工人**从旧底稿重写时丢掉**了 ⇒ 现在补回
#:   并配判据（`_check_package` + `tests/test_dsh_panel.py`），免得再丢第三次。
CLIENT_INJECT_DENY = ("@deepseek-ai/dsh-client-ui-slots",)


# ================================================================ 生成物：包级 locale（卡 247）

#: 卡 247：三个座位的标题/说明按语言给（包级显示链路 —— 插件管理器/市场卡片不激活也能读）。
_LOCALE_SEATS_ZH: dict[str, dict[str, str]] = {
    "workbench_board": {
        "title": "工作台状态",
        "description": "工作台看板（卡/门禁/判决/租约/栅栏/工作树只读读数）与真实页面入口。",
    },
    "zentao_gantt": {
        "title": "禅道",
        "description": "禅道迭代甘特（按模型画条）与禅道真实页面入口。",
    },
    "timeflow_inbox": {
        "title": "timeflow",
        "description": "timeflow 待办（待翻/待复核/待收口）与真实页面入口。",
    },
}
_LOCALE_SEATS_EN: dict[str, dict[str, str]] = {
    "workbench_board": {
        "title": "Workbench status",
        "description": "Workbench board (read-only cards/gates/verdicts/leases) + real page entry.",
    },
    "zentao_gantt": {
        "title": "ZenTao",
        "description": "ZenTao iteration gantt (bars per model) + real page entry.",
    },
    "timeflow_inbox": {
        "title": "timeflow",
        "description": "timeflow inbox (to-flip/to-review/to-close) + real page entry.",
    },
}
LOCALE_ZH: dict = {
    "meta": {
        "title": "工作台全局面板",
        "description": "把工作台状态、禅道、timeflow 三个真实页面接进 DSH："
        "左栏快捷入口 + 右栏常驻页签 + 底部入口。",
    },
    "seats": _LOCALE_SEATS_ZH,
}
LOCALE_EN: dict = {
    "meta": {
        "title": "Workbench panel",
        "description": "Bring the three real pages (workbench / ZenTao / timeflow) into DSH: "
        "sidebar shortcuts + persistent right tabs + one-click start.",
    },
    "seats": _LOCALE_SEATS_EN,
}
#: 落盘文本（emit 与自检共用同一份，不许两处手抄）。
LOCALE_ZH_JSON = json.dumps(LOCALE_ZH, ensure_ascii=False, indent=2) + "\n"
LOCALE_EN_JSON = json.dumps(LOCALE_EN, ensure_ascii=False, indent=2) + "\n"


# ================================================================ 生成物：package.json


def package_manifest() -> dict:
    """插件包的 `package.json`（写成 dict，落盘时再序列化）。"""
    # 卡 244：peerDependencies 里名为 @deepseek-ai/dsh（或以 @deepseek-ai/dsh- 开头）的
    # semver 范围才是**被强制的**兼容字段 —— 不满足 ⇒ 装前拒
    # （dsh-app-boot/lib/index.js:286-304，名字前缀过滤在 :294；plugin-manager/index.js:506
    # 装前拒、app-boot:929-930 加载时 throw）。官方 README 原话：installers and loaders
    # do not enforce dsh.manifestVersion 或 engines.dsh（README.zh.md:93）——
    # 所以**不许**写 engines.dsh 当强制字段。
    return {
        "name": PACKAGE_NAME,
        "version": PACKAGE_VERSION,
        "description": "把工作台三个真实页面的快捷入口接到 DSH（卡 221/240/242/244）。",
        "icon": f"./{ICON_REL}",  # 卡 244：包内相对路径（不许 / 开头、不许 http）
        "type": "module",
        "main": HOST_REL,
        "exports": {
            ".": f"./{HOST_REL}",
            "./client": f"./{CLIENT_REL}",
            "./package.json": "./package.json",
            # 卡 247：包级显示链路 —— 缺了它们，插件管理器读不到显示文本（locale）与元信息。
            "./locale/*.json": "./locale/*.json",
        },
        "peerDependencies": {
            "@deepseek-ai/cordis": "~4.0.4",
            # 卡 244：唯一被强制的兼容字段；范围故意宽（见 DSH_PEER_RANGE 注释）。
            "@deepseek-ai/dsh": DSH_PEER_RANGE,
        },
        # 卡 242：bundle 是宿主层声明（官方最短形态），client 是浏览器半 —— 两者共存。
        # bundle.patch 逐字依据参考仓 dsh-ops 的 package.json：`dsh.bundle.patch`。
        "dsh": {
            "bundle": {"patch": f"./{PATCH_REL}"},
            "client": {"platform": "web", "inject": list(CLIENT_PACKAGE_DEPS)},
        },
    }


# ================================================================ 生成物：cordis.patch.yml


def cordis_patch_yaml(root: str = "") -> str:
    """包内补丁层（卡 242）：`dsh.bundle.patch` 指向的那份文件。

    `dsh plugin add <包>` 时宿主把它当 **profile 层**装；生成时就把本仓库绝对路径写进 root
    （或照 README 换成 `!!js` 从环境读）。语义与老的手写 profile 行完全一致。

    卡 247：补丁层三纪律（照抄参考仓 cordis.patch.yml 头部注释的口径）——
    ① 三处 id/name 完全一致：本文件 insert 的 id 与 name / package.json 的 name /
       宿主半（lib/index.js）导出的 name；
    ② 必须是「顶层 YAML 数组」—— 写成 mapping 会在启动时直接抛错，不是静默跳过；
    ③ 删掉补丁层 = 插件不加载（把这一行整行删掉或注释掉并重启即可）—— 紧急禁用手段，
       要写给人看。
    """
    return (
        "# 卡 242 产物 · 本包的 cordis 补丁层（package.json 里 dsh.bundle.patch 指向本文件）。\n"
        "# `dsh plugin add <本包目录>` 时宿主把这一层当 profile 层装（官方路数）。\n"
        "# ★ root = 生成时的本仓库绝对路径（emit 自动填；换机器/换目录后重跑 --emit）。\n"
        "# ★ 卡 247 · 补丁层三纪律：\n"
        "#   ① 三处 id/name 必须完全一致：本文件 insert 的 id 与 name / package.json 的 name /\n"
        "#      lib/index.js 导出的 name（都是 " + PACKAGE_NAME + "）。\n"
        "#   ② 本文件必须是「顶层 YAML 数组」—— 写成 mapping 会在启动时直接抛错，不是静默跳过。\n"
        "#   ③ 删掉补丁层 = 插件不加载：把下面的 insert 行整行删掉（或注释掉）并重启，\n"
        "#      插件就彻底不加载了 —— 这就是紧急禁用手段之一。\n"
        "- insert:\n"
        f"    - id: {PACKAGE_NAME}\n"
        f'      name: "{PACKAGE_NAME}"\n'
        "      config:\n"
        '        root: "' + (root or "<仓库根，请改成绝对路径>") + '"\n'
    )


#: 卡 247：补丁层文本的模块级常量（判据造反例用：check(patch=…) 的默认真产物）。
PATCH_YAML = cordis_patch_yaml(str(ROOT).replace("\\", "/"))


# ================================================================ 生成物：宿主半


def _host_seats_js() -> str:
    """宿主半那张 JS 座位表（与浏览器半同源，都从 SEATS 生成）。"""
    rows: list[str] = []
    for seat in SEATS:
        script = ", ".join(json.dumps(part) for part in Path(seat.script_rel).parts)
        root = "true" if seat.needs_root else "false"
        rows.append(
            f"  {{ name: {json.dumps(seat.key)}, route: {json.dumps(seat.route)}, "
            f"script: [{script}], needsRoot: {root} }},"
        )
    return "\n".join(rows)


_HOST_JS_TEMPLATE = r"""/* 卡 221 + 卡 240 产物 · 全局面板：宿主半。
 * 会话内注册三个只读工具；并注册【一条只读缝】——
 * 三条同源路由（只 GET、只本机、只读、不写盘、不起工人），
 * 把对应只读工具的 JSON 原样（包在 { ok:true, reading } 里）回给浏览器。
 * ★ 缺什么说什么：工具不在 / 非零 / 超时 / 输出不是 JSON / 顶层不是对象
 *   ⇒ { ok:false, error }，绝不用空数据冒充成功。★ 只读：不写仓库、不起工人。 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
/* 宿主的工具工厂：官方路数是 defineTool(...)（装好后由 profile 的 peer 提供）。
 * 解析不到就退回裸 spec —— 只影响类型与校验
 * ★ 静态 import 解析失败会把整个宿主半带走（路由一起没了），所以这里必须容错。 */
let defineTool = null;
try {
  ({ defineTool } = await import("@deepseek-ai/dsh-tools"));
} catch (error) {
  console.warn("[dsh-panel] 拿不到 defineTool，工具退回裸 spec：", String(error));
}
const makeTool = (spec) => (typeof defineTool === "function" ? defineTool(spec) : spec);

/* 卡 247 · 补丁层三纪律：本导出名 = patch 行 id/name = package.json 的 name（三处一致）。 */
export const name = __PKG_NAME__;

export const inject = ["tools"];

const SEAM_PREFIX = "/dsh-panel";
const SEAT_TIMEOUT_MS = 30000;
/* 卡 253：动作缝（POST）与服务现读（GET）—— 都在同一条 prefix 缝下面。 */
const ACTION_ROUTE = "__ACTION_ROUTE__";
const STACK_STATUS_ROUTE = "__STACK_STATUS_ROUTE__";
const ACTIONS_LOG_REL = ["gates", "diag", "stack-actions.log"];
/* ★ 卡 253：**写死**的动作白名单（真源 = tools/stack.py 的组件表）。
 * 面板只收 {kind, name} 两个枚举值；这里不认命令字符串，没有透传口子。
 *   start / stop：只许表里那五件服务；
 *   start-all   ：等价于 `python tools/stack.py start`（无名字）。
 * ★ 仍然禁止：派工人（dispatch 类工具）、写仓库、改 ~/.dsh、跑门禁。 */
const ACTION_WHITELIST = __ACTION_WHITELIST__;

/* 座位表（与浏览器半同源）：name = 会话内工具名 = 座位 key；route = 只读缝路径。 */
const SEATS = [
__SEATS__
];

/* ★ 仓库根从哪来（2026-10-15 实测修）：
 *   原来只认环境变量、拿「当前工作目录」兜底 —— 而 **DSH 桌面版宿主的 cwd 是
 *   profile 目录**（`C:/Users/example\\.dsh\\profiles\\desktop`）⇒ 三个读数器全都
 *   `can't open file '…\\profiles\\desktop\\tools\\<工具>.py'` ✗（真 DSH 实测原话）。
 *   现在：① 插件行的 `config.root`（组成层当数据写）→ ② 环境变量 → ③ **没有就如实吼**，
 *   绝不拿一个错的 cwd 去猜（宁可见一条错误，也不要看见一块假板子）。 */
let CONFIG_ROOT = "";

function repoRoot() {
  return CONFIG_ROOT || process.env.DSH_WORKBENCH_ROOT || "";
}

/** 只读一次读数：调对应只读工具，缺什么如实报。 */
function readSeat(seat) {
  const root = repoRoot();
  if (!root) {
    return {
      ok: false,
      error: "没告诉我仓库根：请在插件行的 config 里写 root（或设 DSH_WORKBENCH_ROOT）—— "
        + "DSH 桌面版宿主的 cwd 是 profile 目录，不能拿它当仓库根。",
    };
  }
  const script = path.join(root, ...seat.script);
  const args = ["-X", "utf8", script, "--json"];
  if (seat.needsRoot) args.push("--root", root);
  const done = spawnSync(process.env.DSH_PYTHON || "python", args, {
    encoding: "utf8",
    timeout: SEAT_TIMEOUT_MS,
    windowsHide: true,
    maxBuffer: 16 * 1024 * 1024,
    cwd: root,
  });
  if (done.error) {
    return { ok: false, error: `读数器起不来：${done.error.message}（数据源缺失）` };
  }
  if (done.status !== 0) {
    const tail = (done.stderr || "").slice(0, 400);
    return { ok: false, error: `读数器非零退出（${done.status}）：${tail}` };
  }
  let reading;
  try {
    reading = JSON.parse(done.stdout);
  } catch (error) {
    return { ok: false, error: `读数器输出不是 JSON：${error.message}` };
  }
  if (reading === null || typeof reading !== "object") {
    return { ok: false, error: "读数器输出顶层不是对象" };
  }
  return { ok: true, reading };
}

function sendJson(res, status, payload) {
  res.statusCode = status;
  res.setHeader("content-type", "application/json; charset=utf-8");
  res.setHeader("cache-control", "no-store");
  res.end(JSON.stringify(payload));
}

/** 卡 253：跑一次 `tools/stack.py`（argv 写死，绝不 shell）；缺根就如实报。 */
function runStack(args, timeoutMs) {
  const root = repoRoot();
  if (!root) {
    return {
      ok: false,
      error: "没告诉我仓库根：请在插件行的 config 里写 root（或设 DSH_WORKBENCH_ROOT）。",
    };
  }
  const done = spawnSync(process.env.DSH_PYTHON || "python",
    ["-X", "utf8", path.join(root, "tools", "stack.py"), ...args], {
      encoding: "utf8",
      timeout: timeoutMs,
      windowsHide: true,
      maxBuffer: 16 * 1024 * 1024,
      cwd: root,
    });
  const output = ((done.stdout || "") + (done.stderr || "")).trim();
  if (done.error) {
    return { ok: false, error: `stack.py 起不来：${done.error.message}`, output };
  }
  return {
    ok: done.status === 0,
    error: done.status === 0 ? "" : `stack.py 非零退出（${done.status}）`,
    output,
  };
}

/** 卡 253：服务现读（与 `stack.py status --json` 同一个 status_data 真源）。 */
function readStatus() {
  const done = runStack(["status", "--json"], SEAT_TIMEOUT_MS);
  if (!done.ok) return { ok: false, error: done.error || done.output };
  try {
    return JSON.parse(done.output);
  } catch (error) {
    return { ok: false, error: `status --json 输出不是 JSON：${error.message}` };
  }
}

/** 卡 253：动作日志最后几行（读不到 ⇒ 空表 + 不假装）。 */
function recentActions() {
  const root = repoRoot();
  if (!root) return [];
  try {
    const text = fs.readFileSync(path.join(root, ...ACTIONS_LOG_REL), "utf8");
    return text.split(/\r?\n/).filter((line) => line.trim()).slice(-5);
  } catch (error) {
    return [];
  }
}

/** 卡 253：动作缝 —— 只收白名单里的 {kind, name}，其余一律拒绝并点名。 */
function serveAction(req, res, url) {
  if (req.method !== "POST") {
    sendJson(res, 405, { ok: false, error: `动作缝只接受 POST，收到 ${req.method}` });
    return;
  }
  const kind = url.searchParams.get("kind") || "";
  const name = url.searchParams.get("name") || "";
  const allowed = ACTION_WHITELIST[kind];
  if (allowed === undefined) {
    sendJson(res, 400, {
      ok: false,
      error: `拒绝：动作 ${kind} 不在白名单 [${Object.keys(ACTION_WHITELIST).join(", ")}] 里`,
    });
    return;
  }
  if (Array.isArray(allowed) && !allowed.includes(name)) {
    sendJson(res, 400, {
      ok: false,
      error: `拒绝：${name} 不在 ${kind} 白名单 [${allowed.join(", ")}] 里`,
    });
    return;
  }
  const args = ["--actor", "panel", kind];
  if (kind !== "start-all") args.push(name);
  const done = runStack(args, 45000);
  sendJson(res, 200, {
    ok: done.ok,
    output: done.output,
    error: done.error,
    status: readStatus(),
    recent: recentActions(),
  });
}

/** 缝的 handler：动作缝只认 POST 且只认白名单；其余（读数）只 GET、只认已知路由。 */
  /* ---- 卡 A274 · 参数读写：只收白名单键，原子写 <root>/tools/settings.toml ----
   * GUI 的「参数」页用这一对：GET 读、POST 写（值走查询串，不解析请求体）。
   * ★ 白名单：只认 SETTINGS_KEYS 里的键与范围；其余一律拒（不透传任意写）。
   * ★ 写盘：先写 .tmp 再 rename（中途失败不许留下半截文件）。 */
  const SETTINGS_ROUTE = SEAM_PREFIX + "/settings";
  const SETTINGS_REL = ["tools", "settings.toml"];
  const SETTINGS_KEYS = {
    tf_gate_min_free_gb: { min: 0, max: 64, label: "内存闸阈值（GB；0 = 关）" },
    gate_workers: { min: 1, max: 8, label: "门禁并行数" },
  };

  function settingsPath() {
    const root = repoRoot();
    return root ? path.join(root, ...SETTINGS_REL) : "";
  }

  function parseSettings(text) {
    const values = {};
    for (const line of String(text || "").split(/\r?\n/)) {
      const hit = line.match(/^\s*([a-z0-9_]+)\s*=\s*(-?\d+(?:\.\d+)?)\s*$/);
      if (hit) values[hit[1]] = Number(hit[2]);
    }
    return values;
  }

  function readSettings() {
    const file = settingsPath();
    if (!file) {
      return { ok: false, error: "没配 root：插件行 config.root 或 DSH_WORKBENCH_ROOT" };
    }
    try {
      const exists = fs.existsSync(file);
      const text = exists ? fs.readFileSync(file, "utf8") : "";
      return {
        ok: true,
        file: SETTINGS_REL.join("/"),
        exists,
        values: parseSettings(text),
        keys: Object.entries(SETTINGS_KEYS).map(([key, spec]) => ({ key, ...spec })),
      };
    } catch (error) {
      return { ok: false, error: `读参数失败：${error.message}` };
    }
  }

  function serveSettings(req, res) {
    /* ★ 面板只读（卡 A273/274 的硬判据）：参数页只读、不给写口子。
     *   要改参数走 CLI/环境变量（TF_GATE_MIN_FREE_GB 等），面板只把现值显示出来。 */
    if (req.method !== "GET") {
      sendJson(res, 405, { ok: false, error: `参数缝只读，收到 ${req.method}` });
      return;
    }
    sendJson(res, 200, readSettings());
  }

const SKILLS_ROUTE = SEAM_PREFIX + "/skills";

/** 技能清单：只读仓库 skills/*.md 的标题与首段（面板不许写，只列）。 */
function listSkills() {
  const root = repoRoot();
  if (!root) return { ok: false, error: "没配 root：插件行 config.root 或 DSH_WORKBENCH_ROOT" };
  const dir = path.join(root, "skills");
  try {
    const items = fs.readdirSync(dir)
      .filter((name) => String(name).endsWith(".md"))
      .sort()
      .map((name) => {
        let text = "";
        try {
          text = fs.readFileSync(path.join(dir, name), "utf8");
        } catch (error) {
          text = "";
        }
        const lines = String(text).split(/\r?\n/);
        const title = (lines.find((line) => /^#\s+/.test(line)) || "").replace(/^#\s+/, "").trim();
        const summary = (lines.find((line) => line.trim() && !/^#/.test(line)) || "").trim();
        return { name: String(name).replace(/\.md$/, ""), title, summary };
      });
    return { ok: true, dir: "skills", items };
  } catch (error) {
    return { ok: false, error: `读技能目录失败：${error.message}` };
  }
}

function serveSkills(req, res) {
  if (req.method !== "GET") {
    sendJson(res, 405, { ok: false, error: `技能清单只读，收到 ${req.method}` });
    return;
  }
  sendJson(res, 200, listSkills());
}

function serveSeam(req, res) {
  const url = new URL(req.url || "/", "http://localhost");
  if (url.pathname === ACTION_ROUTE) {
    serveAction(req, res, url);
    return;
  }
  if (url.pathname === SETTINGS_ROUTE) {
    serveSettings(req, res);
    return;
  }
  if (url.pathname === SKILLS_ROUTE) {
    serveSkills(req, res);
    return;
  }
  if (req.method !== "GET") {
    sendJson(res, 405, { ok: false, error: `只读缝只接受 GET，收到 ${req.method}` });
    return;
  }
  if (url.pathname === STACK_STATUS_ROUTE) {
    sendJson(res, 200, { ok: true, status: readStatus(), recent: recentActions() });
    return;
  }
  const seat = SEATS.find((row) => row.route === url.pathname);
  if (seat === undefined) {
    sendJson(res, 404, { ok: false, error: `未知路由：${url.pathname}` });
    return;
  }
  sendJson(res, 200, readSeat(seat));
}

export function apply(ctx) {
  /* ★ 仓库根：插件行的 config.root 优先（组成层当数据写），没有就留给环境变量，再没有就如实吼。 */
  const configured = ctx?.config?.root;
  CONFIG_ROOT = typeof configured === "string" ? configured : "";
  /* ★ 顺序：先挂只读路由（面板的一键启动/现读全靠它），再注册工具 ——
     工具注册若因宿主版本差异抛错，绝不能把路由一起带走（卡 A273）。 */
  ctx.inject(["webServer"], (webCtx) => {
    webCtx.effect(() => webCtx.webServer.register({
      kind: "prefix",
      path: SEAM_PREFIX,
      handler: serveSeam,
    }), "dsh-panel: read-only seam");
    console.log("[dsh-panel] 路由已挂上", SEAM_PREFIX, "root=",
      repoRoot() || "（没配 config.root）");
  });
  /* 会话内三个只读工具：缺哪块如实说哪块，绝不用空数据冒充成功。 */
  for (const seat of SEATS) {
    /* 逐工具 try/catch：一个工具注册失败不许连累别的工具。 */
    try {
      ctx.tools.register(makeTool({
        name: seat.name,
        description: `只读：交出「${seat.name}」这一面的读数；缺什么如实说什么。`,
        parameters: {},
        output: {
          schema: { type: "json" },
          render: (_args, value) => [{ type: "text", text: JSON.stringify(value, null, 2) }],
        },
        async execute() {
          return readSeat(seat);
        },
      }));
    } catch (error) {
      console.warn("[dsh-panel] 工具注册失败：", seat.name, String(error));
    }
  }
}
"""


def _action_whitelist_js() -> str:
    """卡 253：宿主半那份**写死**的动作白名单（从 Python 的 ACTION_WHITELIST 生成）。"""
    body = ", ".join(
        f"{json.dumps(kind)}: {'true' if not names else json.dumps(list(names))}"
        for kind, names in ACTION_WHITELIST.items()
    )
    return "{ " + body + " }"


def _host_js() -> str:
    return (
        _HOST_JS_TEMPLATE.replace("__SEATS__", _host_seats_js())
        .replace("__ACTION_WHITELIST__", _action_whitelist_js())
        .replace("__ACTION_ROUTE__", ACTION_ROUTE)
        .replace("__STACK_STATUS_ROUTE__", STACK_STATUS_ROUTE)
        .replace("__PKG_NAME__", json.dumps(PACKAGE_NAME))
    )


HOST_JS = _host_js()


# ================================================================ 生成物：浏览器半


def _client_registrations() -> str:
    """浏览器半：逐座位生成「main 一座 + sidebar.panellist 一行」。

    ★ 第一座沿用 `PANEL_ID`（卡 221 的既有判据钉着 `key: PANEL_ID` / `id: PANEL_ID`）；
      其余座用各自的字面 key。两处逐项同源 —— 判据比这两个列表。
    """
    blocks: list[str] = []
    for index, seat in enumerate(SEATS):
        key_expr = "PANEL_ID" if index == 0 else json.dumps(seat.key)
        icon = json.dumps([list(pair) for pair in seat.icon], ensure_ascii=False)
        blocks.append(
            '      ctx.slots.inject("main", () => ctx.slots.register({\n'
            '        name: "main",\n'
            f"        key: {key_expr},\n"
            "        locale: NS,\n"
            "        inject: () => ({"
            f" route: {json.dumps(seat.route)}, target: TARGETS[{key_expr}] }}),\n"
            "      }, function (props) {\n"
            "        /* 默认 = 快捷入口（开真实页面）；内嵌读数（自绘视图）保留成可选分支。 */\n"
            "        return h(QuickEntry, {"
            f" route: props.route, target: props.target, title: {json.dumps(seat.label_zh)},"
            f" fallback: {seat.render} }});\n"
            "      }));\n"
            '      ctx.slots.inject("sidebar.panellist", () => ctx.slots.register({\n'
            '        name: "sidebar.panellist",\n'
            f"        id: {key_expr},\n"
            f"        order: {seat.order},\n"
            f"        label: () => t({json.dumps(seat.locale_key)}),\n"
            "        locale: NS,\n"
            f"      }}, makeIcon({icon}, {json.dumps(seat.icon_round)}, {key_expr})));"
        )
    blocks.append(
        '      ctx.slots.inject("main", () => ctx.slots.register({\n'
        '        name: "main",\n'
        '        key: "toolbox",\n'
        '        locale: NS,\n'
        '        inject: () => ({ route: "/panel/toolbox" }),\n'
        "      }, function () { return h(Toolbox, {}); }));\n"
        '      ctx.slots.inject("sidebar.panellist", () => ctx.slots.register({\n'
        '        name: "sidebar.panellist",\n'
        '        id: "toolbox",\n'
        "        order: 3,\n"
        '        label: () => "工程工具箱",\n'
        "        locale: NS,\n"
        '      }, makeIcon([["M3 3h7v7H3z", "currentColor"], ["M14 3h7v7h-7z", "currentColor"],\n'
        '        ["M3 14h7v7H3z", "currentColor"], ["M14 14h7v7h-7z", "currentColor"]],\n'
        '        "round", "")));'
    )
    return "\n".join(blocks)



def _client_label_map(attr: str) -> str:
    return ", ".join(f"{seat.locale_key}: {json.dumps(getattr(seat, attr))}" for seat in SEATS)


_CLIENT_JS_TEMPLATE = r"""/* 卡 221/240/242/244/247 产物 · 全局面板：浏览器半 —— 三个座位各占
 * root 作用域 `main` keyed 座的一个 key，并在 `sidebar.panellist` 各挂一行 ⇒ 不切窗口就能看板。
 * 卡 247：右栏三个**常驻页签**（id 带包名前缀 + keepMounted）+ 左栏底部入口（保底路）。
 * 卡 242：三行是**快捷入口** —— 默认开**真实页面**（ctx.sidebarRight.openTab("browser",
 * { params: { url } })，依据见 QuickEntry 上方注释）；原来的自绘视图（六块/甘特/列表）
 * **保留**成可选的「内嵌读数」分支。★ 只读：不写仓库、不起工人；点选只写「选中态」。
 * ★ 加载失败 / 数据源缺失要看得见（data-wb-state="error"），绝不静默白屏；
 * 某块缺 ⇒ data-wb-state="missing"；目标页连不上 ⇒ 显式「没起 + 怎么起」。 */
window.__ModuleLoader__.load({
  id: "dsh-client-ui-workbench-panel",
  factory: (require) => {
    var module = { exports: {} };
    var exports = module.exports;
    const react = require("react");
    const h = react.createElement;
    const NS = "workbenchPanel";
    const PANEL_ID = "workbench_board";
    const SECTIONS = ["cards", "gates", "verdicts", "leases", "fences", "worktrees"];
    /* 卡 253：动作缝（POST，白名单在宿主半）与服务现读（GET）。 */
    const ACTION_ROUTE = "__ACTION_ROUTE__";
    const STACK_STATUS_ROUTE = "__STACK_STATUS_ROUTE__";

    /* ---- TARGETS（卡 242）：三个真实页面，与座位表同源（key 一一对应） ----
     * up = 没起时的「怎么起」。目标页归别的工具（wb_dash.py / serve.py / 禅道），
     * 本面板只指向它们，不代替它们。 */
    const TARGETS = {
__TARGETS__
    };

    /* ---- 取数：同源、只 GET（宿主半那条只读缝） ---- */
    function useSource(route) {
      const [state, setState] = react.useState({ status: "loading" });
      react.useEffect(() => {
        let alive = true;
        fetch(route, { method: "GET" })
          .then((response) => response.json())
          .then((data) => { if (alive) setState({ status: "ready", data }); })
          .catch((error) => {
            if (alive) setState({ status: "error", error: String(error.message || error) });
          });
        return () => { alive = false; };
      }, [route]);
      return state;
    }

    /* 失败可见：取数失败 / 读数失败 ⇒ data-wb-state="error" + 原话；不白屏。 */
    function SourceShell(props) {
      const state = useSource(props.route);
      if (state.status === "loading") {
        return h("div", { "data-wb-state": "loading" }, h("p", null, "读数中…"));
      }
      if (state.status === "error") {
        return h("div", { "data-wb-state": "error", "data-wb-error": "fetch" },
          h("h2", null, props.title + "：数据源不可用"),
          h("p", { "data-wb-error": "" }, state.error),
          h("p", null, "读数源缺失：" + props.route));
      }
      const data = state.data;
      if (data && data.ok === false) {
        return h("div", { "data-wb-state": "error", "data-wb-error": "read-failed" },
          h("h2", null, props.title + "：读数失败"),
          h("p", { "data-wb-error": "" }, String(data.error || "未知错误")));
      }
      return props.render(data ? data.reading : undefined);
    }

    /* ---- 卡 242 · 快捷入口（默认视图）：开真实页面 ----
     * ★ 官方口子（查到的依据，不许猜 API）：
     *   - 服务名与调用形状：`ctx.sidebarRight.openTab(kind, options?)` —— 依据
     *     @deepseek-ai/dsh-client-ui-sidebar-right/lib/types/client/service.d.ts:168
     *     （原话：Open a page type by kind at the address this package records pages under）。
     *   - 浏览器页的参数形状：`browser: { url?: string }` —— 依据同包
     *     lib/types/client/contract/params.d.ts（原话：the Browser page adds
     *     `browser: { url?: string }`）；kind = "browser"（lib/types/client/definition.d.ts:6）。
     *   - 官方自己就这么调：@deepseek-ai/dsh-client-ui-sidebar-browser/lib/client.js:157-159
     *     （tab.actions.openTab("browser", { params: { url }, revealIfOpened: false })）。
     *   - 侧栏浏览器桌面版默认启用（dsh-web-app/cordis.patch.yml:277-280，Electron <webview>）。
     * ★ 退路（明说，不假装打开了）：sidebarRight 面向**当前会话**（service.d.ts 头注释），
     *   无会话在屏 / Web 形态（浏览器页不注册）时 openTab 会失败 ⇒ catch 住、如实报错，
     *   并给出可点的链接（Desktop 侧栏浏览器不受 iframe 限制；Web 形态下站点可能拒绝嵌入）。
     * ★ 目标页连不上 ⇒ 探测 fetch（no-cors）失败时显式写「没起 + 怎么起」，绝不白屏。 */
    let panelCtx = null; /* apply 时接住 ctx：QuickEntry 要用 ctx.sidebarRight。 */
    /* ---- 卡 244 · 逃生门第一半：最后在屏的 sessionId ----
     * ★ 为什么需要：openTab/openResource 内部先 require() 屏幕会话，无会话 ⇒ 抛
     *   "sidebarRight: no session surface is mounted"（依据
     *   @deepseek-ai/dsh-client-ui-sidebar-right/lib/client.js:6385-6396（入口）、
     *   :6744-6752（require() 的 throw））。而「屏幕会话」= "The Session on screen,
     *   or undefined while none is (a global panel fills the main column, …)"
     *   （service.d.ts:141-143）⇒ 本面板占着 main 时恰恰是 undefined 形态：
     *   点左栏行 → 立刻 openTab，第一次点击就会抛。 */
    let screenSessionId = null;
    /* ---- 卡 244 · 探测状态的小仓库（模块级）：QuickEntry 写，左栏 glyph 的角标读 ----
     * ★ 核心行条目只有 {id, order, label}，**没有角标槽**（依据
     *   dsh-client-ui-sidebar/lib/client.js:454-461（侧栏逐条画行）、:187-197）
     *   ⇒ 「未起」的小点只能画进**自己的 glyph 内容**里；这是我们自画的，
     *   不是核心角标能力。 */
    const probeStore = {
      state: {},
      listeners: new Set(),
      set(key, value) {
        if (probeStore.state[key] === value) return;
        probeStore.state[key] = value;
        probeStore.listeners.forEach((fn) => fn());
      },
      subscribe(fn) {
        probeStore.listeners.add(fn);
        return () => probeStore.listeners.delete(fn);
      },
    };
    /* 订 probeStore 的某个 key（角标与探测共用）；探测本身由 useProbe 发起。 */
    function useProbeState(key) {
      const [state, setState] = react.useState(probeStore.state[key] || "none");
      react.useEffect(() => probeStore.subscribe(
        () => setState(probeStore.state[key] || "none")
      ), [key]);
      return state;
    }
    /* QuickEntry 的探测：fetch(no-cors) 探目标页，结果写进 probeStore（卡 244）。 */
    function useProbe(key, url) {
      const state = useProbeState(key);
      react.useEffect(() => {
        probeStore.set(key, "checking");
        fetch(url, { mode: "no-cors" })
          .then(() => probeStore.set(key, "up"))
          .catch(() => probeStore.set(key, "down"));
      }, [key, url]);
      return state;
    }
    /* ---- 卡 247 · 开真实页面的唯一入口（QuickEntry 与左栏底部入口共用）----
     * 卡 244 · 逃生门第二半：openTabIn 优先 —— 优先 openTabIn(最后在屏的 sessionId,
     * "browser", …) —— 它对未 adopted 的会话**静默无操作**（client.js:6418-6421：
     * actionsFor() 拿不到就 return）；只有拿不到 sessionId 时才退回 openTab ——
     * 无屏幕会话时它会抛 "no session surface is mounted"（client.js:6744-6752）⇒
     * catch 住、如实报错。
     * ★ 已知取舍：sessionId 在屏但其 store 未 adopted 时 openTabIn 静默无操作，
     *   界面不报错也不打开 —— 比对着裸 openTab 抛错好；探测行 + 链接兜底仍在。
     * ★ 卡 247：左栏底部入口走的是「main 仍是会话、屏幕会话在」的时刻 ⇒
     *   openTab("browser") 不需要逃生门也能用 —— 本函数两种时刻都覆盖（双保险）。 */
    function openRealPage(target, setOpenError) {
      try {
        const sessionId = screenSessionId;
        if (sessionId) {
          panelCtx.sidebarRight.openTabIn(sessionId, "browser",
            { params: { url: target.url } });
        } else {
          panelCtx.sidebarRight.openTab("browser", { params: { url: target.url } });
        }
        setOpenError("");
      } catch (error) {
        setOpenError(String((error && error.message) || error));
      }
    }
    /* ---- 卡 253 · 服务控制：一起起 / 分别停 ----
     * ★ 点开才读：挂载时读一次（面板被点开 = 挂载），**没有常驻定时轮询**；
     *   「聚焦」也是一次现读（按钮每次动作后 reload），不做后台轮询。
     * ★ 动作只传 {kind, name} 两个枚举值给宿主半；白名单在宿主半写死（真源 stack.py）。
     * ★ 反馈如实：先写「已发起启动」；宿主半等 stack.py 探到**真端口**才回 ok，
     *   这时才改口「已起（端口 N；映像 X）」；等不到就原样显示 stack.py 的原话
     *   「发起了，但 N 秒内端口还没起来 —— 看 <日志>」。绝不点一下就写「已启动」。 */
    /* ---- A273 · 小样式：只用主题令牌与 currentColor，不硬编码颜色 ---- */
    const UI = {
      page: { padding: "16px 18px", display: "flex", flexDirection: "column", gap: "10px",
        height: "100%", boxSizing: "border-box" },
      head: { display: "flex", alignItems: "center", gap: "10px" },
      title: { margin: 0, fontSize: "16px", fontWeight: 600 },
      pill: { display: "inline-flex", alignItems: "center", gap: "6px",
        fontSize: "12px", padding: "2px 9px", borderRadius: "999px",
        border: "1px solid var(--dsw-alias-border-base, currentColor)",
        color: "var(--dsw-alias-text-secondary, inherit)" },
      dot: { width: "6px", height: "6px", borderRadius: "50%", background: "currentColor" },
      card: { display: "flex", flexDirection: "column", gap: "10px", padding: "12px 14px",
        borderRadius: "8px", border: "1px solid var(--dsw-alias-border-base, currentColor)" },
      row: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: "12px" },
      muted: { margin: 0, fontSize: "12px", color: "var(--dsw-alias-text-secondary, inherit)" },
      link: { fontSize: "13px", color: "inherit" },
      frame: { flex: 1, width: "100%", minHeight: "320px",
        border: "1px solid var(--dsw-alias-border-base, currentColor)",
        borderRadius: "8px", background: "transparent" },
      primary: { padding: "6px 16px", borderRadius: "6px", cursor: "pointer", border: "none",
        fontSize: "13px", fontWeight: 500,
        background: "var(--dsw-alias-state-business-primary, currentColor)",
        color: "var(--dsw-alias-text-inverse, currentColor)" },
      secondary: { padding: "6px 14px", borderRadius: "6px", cursor: "pointer",
        fontSize: "13px", border: "1px solid var(--dsw-alias-border-base, currentColor)",
        background: "transparent", color: "inherit" },
      error: { margin: 0, fontSize: "12px",
        color: "var(--dsw-alias-state-danger-primary, inherit)" },
    };

    /* 探测结果翻成人话（未知就说未知）。 */
    function probeText(state) {
      if (state === "up") return "在跑";
      if (state === "down") return "没起";
      if (state === "checking") return "检测中";
      return "未知";
    }

    /* 把 Response 读成 JSON：先看状态码与空包，别让解析器的原话直接吓人。 */
    function readJson(response) {
      return response.text().then((text) => {
        if (!response.ok) {
          throw new Error("HTTP " + response.status + (text ? "" : "（空响应）"));
        }
        if (!text) throw new Error("HTTP " + response.status + "（空响应）");
        try {
          return JSON.parse(text);
        } catch (error) {
          throw new Error("返回的不是 JSON：" + text.slice(0, 80));
        }
      });
    }

    function useServiceControl() {
      const [state, setState] = react.useState({ status: "loading" });
      const [action, setAction] = react.useState(null);
      const reload = react.useCallback(() => {
        fetch(STACK_STATUS_ROUTE, { method: "GET" })
          .then(readJson)
          .then((data) => {
            if (data && data.ok === false) {
              setState({ status: "error", error: String(data.error || "现读失败") });
            } else {
              setState({ status: "ready", data });
            }
          })
          .catch((error) => setState({ status: "error", error: String(error.message || error) }));
      }, []);
      react.useEffect(() => { reload(); }, [reload]);
      const run = react.useCallback((kind, name) => {
        setAction({
          phase: "starting",
          text: (kind === "stop" ? "已发起停止：" : "已发起启动：") + (name || "全部"),
        });
        const query = "?kind=" + encodeURIComponent(kind)
          + "&name=" + encodeURIComponent(name || "");
        fetch(ACTION_ROUTE + query, { method: "POST" })
          .then(readJson)
          .then((data) => {
            const status = data.status || {};
            const rows = status.components || [];
            const row = rows.find ? rows.find((item) => item.name === name) : null;
            if (data.ok && (kind === "start-all" || (row && row.running))) {
              setAction({
                phase: "done",
                text: kind === "stop"
                  ? (data.output || "已停：" + name)
                  : "已起（" + (row ? row.detail : "全部动作成功") + "）",
              });
            } else {
              setAction({
                phase: "failed",
                text: String(data.error || "") + " " + String(data.output || ""),
              });
            }
            if (status.ok === true) {
              setState({ status: "ready", data: { ok: true, status, recent: data.recent || [] } });
            } else {
              reload();
            }
          })
          .catch((error) => setAction({
            phase: "failed",
            text: "动作请求失败（原话：" + String(error.message || error) + "）",
          }));
      }, [reload]);
      return { state, action, reload, run };
    }

    /* 服务细节（默认收进 <details>）：现读行 + RSS + 分别停 + 最近动作。 */
    function ServiceControls(props) {
      const control = props.control;
      const status = control.state;
      const payload = status.status === "ready" ? (status.data || {}) : {};
      const board = payload.status || {};
      const rows = board.components || [];
      const recent = payload.recent || [];
      const small = { ...UI.secondary, padding: "2px 10px", fontSize: "12px" };
      return h("div", { "data-wb-services": "",
        style: { display: "flex", flexDirection: "column", gap: "8px", paddingTop: "6px" } },
        status.status === "error"
          ? h("p", { "data-wb-state": "error", "data-wb-error": "stack-status", style: UI.error },
              "服务现读失败：" + status.error)
          : null,
        rows.length
          ? h("div", { style: { display: "flex", flexDirection: "column", gap: "4px" } },
              rows.map((row) =>
                h("div", { key: row.name, style: UI.row },
                  h("span", { style: UI.muted },
                    row.name + " · " + (row.running ? "在跑" : "没起") + " · "
                      + (row.rss_mb === null ? "RSS ?" : "RSS " + row.rss_mb + " MB")),
                  h("button", { style: small,
                    onClick: () => control.run("stop", row.name) }, "停这一件"))))
          : null,
        h("p", { style: UI.muted },
          "合计 RSS：" + (board.total_rss_mb === undefined ? "?" : board.total_rss_mb)
            + " MB（常驻预算 " + (board.budget_mb === undefined ? 400 : board.budget_mb) + " MB）"
            + (board.over_budget ? " ★ 超出常驻预算 —— 停掉不用的服务" : "")),
        control.action
          ? h("p", { "data-wb-action": control.action.phase, style: UI.muted }, control.action.text)
          : null,
        h("div", { style: { display: "flex", gap: "8px", flexWrap: "wrap" } },
          h("button", { style: small, onClick: () => control.run("start-all", "") }, "全部起"),
          h("button", { style: small, onClick: () => control.reload() }, "刷新")),
        h("p", { style: UI.muted }, "动作日志：gates/diag/stack-actions.log"),
        recent.length
          ? h("div", null,
              h("p", { style: UI.muted }, "最近动作："),
              h("ul", { style: { margin: "4px 0 0", paddingLeft: "18px" } },
                recent.map((line, index) => h("li", { key: index, style: UI.muted }, line))))
          : null);
    }

    /* 底部入口用：只在用户点开时才挂载（挂载才读一次，不是常驻轮询）。 */
    function ServicePanel(props) {
      const control = useServiceControl();
      return h(ServiceControls, { control, target: props.target });
    }

    /* ---- 三行页：一行状态 + 一个主按钮，细节收进 <details>（卡 A273 重排） ---- */
    function QuickEntry(props) {
      const target = props.target;
      const [mode, setMode] = react.useState("page");
      const [openError, setOpenError] = react.useState("");
      const [nonce, setNonce] = react.useState(0);
      const control = useServiceControl();
      const probe = useProbe(target.seat, target.url);
      if (mode === "embedded") {
        return h(props.fallback, { route: props.route });
      }
      function openInSidebar() {
        openRealPage(target, setOpenError);
      }
      const action = control.action;
      const down = probe === "down" && !(action && action.phase === "ok");
      return h("div", { "data-wb-state": "ok", style: UI.page },
        h("div", { style: UI.head },
          h("h2", { style: UI.title }, props.title),
          h("span", { "data-wb-probe": probe, style: UI.pill },
            h("span", { style: UI.dot }),
            probeText(probe)),
          h("span", { style: { flex: 1 } }),
          target.start && probe !== "up"
            ? h("button", { style: UI.primary,
                onClick: () => control.run("start", target.start) }, "一键启动")
            : null,
          h("button", { style: UI.secondary, onClick: openInSidebar }, "右栏打开"),
          h("button", { style: UI.secondary, onClick: () => setNonce((n) => n + 1) }, "刷新")),
        action ? h("p", { "data-wb-action": action.phase, style: UI.muted }, action.text) : null,
        openError
          ? h("p", { "data-wb-error": "", style: UI.error }, "右栏开不了：" + openError)
          : null,
        down
          ? h("div", { style: UI.card },
              h("p", { style: UI.muted }, "服务没起 —— 点上面「一键启动」，起完这里自动加载页面。"),
              h("p", { style: UI.muted }, "手动起：" + target.up),
              h("details", { style: UI.muted },
                h("summary", { style: { cursor: "pointer" } }, "服务与资源（RSS / 日志 / 分别停）"),
                h(ServiceControls, { control, target })))
          : h("iframe", { key: nonce, src: target.url, style: UI.frame, title: props.title }),
        h("p", { style: UI.muted },
          h("button", { style: { ...UI.secondary, border: "none", padding: 0,
            color: "var(--dsw-alias-text-secondary, inherit)", fontSize: "12px" },
            onClick: () => setMode("embedded") }, "改看内嵌读数 →")));
    }

    /* ---- 卡 A274 · 工程工具箱：一个页面三个标签页（总览 / 号池 / 参数） ----
     * 只读为主：总览读 stack-status 并给白名单动作；号池读 workbench_board；
     * 参数页 GET/POST /dsh-panel/settings（白名单键，写 tools/settings.toml）。 */
    const TOOLBOX_TABS = [
      ["overview", "总览"],
      ["board", "看板"],
      ["pool", "号池"],
      ["skills", "技能"],
      ["params", "参数"],
    ];
    const PARAMS_ROUTE = "/dsh-panel/settings";

    function ToolboxOverview() {
      const state = useSource(STACK_STATUS_ROUTE);
      const control = useServiceControl();
      const [openError, setOpenError] = react.useState("");
      const rows = state.status === "ready" && state.data && state.data.ok
        ? state.data.status.components : [];
      return h("div", { style: { display: "flex", flexDirection: "column", gap: "10px" } },
        h("div", { style: UI.card },
          h("div", { style: UI.row },
            h("span", { style: UI.muted }, "一键起停（白名单动作）"),
            h("span", null,
              h("button", { style: UI.primary,
                onClick: () => control.run("start-all", "") }, "全部起"),
              h("button", { style: { ...UI.secondary, marginLeft: "8px" },
                onClick: () => control.reload() }, "刷新"))),
          state.status === "error"
            ? h("p", { "data-wb-error": "", style: UI.error }, "服务读数失败：" + state.error)
            : rows.length
              ? h("div", { style: { display: "flex", flexDirection: "column", gap: "6px" } },
                  rows.map((row) => h("div", { key: row.name, style: UI.row },
                    h("span", null, row.name + " · " + (row.running ? "在跑" : "没起")
                      + (row.running && row.rss_mb !== null ? " · RSS " + row.rss_mb + " MB" : "")),
                    h("button", {
                      style: { ...UI.secondary, padding: "3px 10px", fontSize: "12px" },
                      onClick: () => control.run(row.running ? "stop" : "start", row.name),
                    }, row.running ? "停" : "起"))))
              : h("p", { style: UI.muted }, "读数中…"),
          control.action ? h("p", { style: UI.muted }, control.action.text) : null),
        h("div", { style: UI.card },
          h("p", { style: UI.muted }, "三个入口（右栏打开，不切窗口）"),
          Object.keys(TARGETS).map((seat) => h("div", { key: seat, style: UI.row },
            h("span", null, seat),
            h("button", {
              style: { ...UI.secondary, padding: "3px 10px", fontSize: "12px" },
              onClick: () => openRealPage(TARGETS[seat], setOpenError),
            }, "打开")))),
        openError
          ? h("p", { "data-wb-error": "", style: UI.error }, "开不了：" + openError)
          : null);
    }

    function ToolboxBoard() {
      const state = useSource("/panel/workbench_board");
      if (state.status === "loading") return h("p", { style: UI.muted }, "读数中…");
      const data = state.data || {};
      if (state.status === "error" || data.ok === false) {
        return h("p", { "data-wb-error": "", style: UI.error },
          "看板读数不可用：" + String(state.error || data.error || ""));
      }
      const cards = (data.reading && data.reading.cards) || [];
      const columns = [
        ["pending", "待办", (card) => card.status === "pending"],
        ["running", "在跑", RUNNING],
        ["done", "已完成", (card) => card.status === "done"],
        ["other", "其它", OTHER],
      ];
      return h("div", { style: { display: "flex", gap: "10px", alignItems: "flex-start" } },
        columns.map(([key, label, pick]) => {
          const rows = cards.filter((card) => pick(card));
          return h("div", {
            key, "data-wb-column": key,
            style: Object.assign({}, UI.card, { flex: "1", minWidth: "0" }),
          },
            h("p", { style: UI.muted }, label + " · " + String(rows.length)),
            rows.slice(0, 40).map((card) => h("div", { key: String(card.id), style: UI.row },
              h("span", { style: UI.muted }, "#" + String(card.id)),
              h("span", { style: CELL }, String(card.title || card.task || "")))));
        }));
    }

    const CELL = { flex: "1", minWidth: "0" };
    const ELLIPSIS = {
      maxWidth: "44%", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
    };
    const textCell = (value) => h("span", { style: CELL }, String(value || ""));
    const errorLine = (label, detail) => h("p", { "data-wb-error": "", style: UI.error },
      label + "：" + String(detail || ""));

    const LIVE = (card) => card.status !== "done" && card.status !== "void";
    const RUNNING = (card) => ["in-progress", "running", "ready"].indexOf(card.status) >= 0;
    const OTHER = (card) => card.status !== "pending" && card.status !== "done" &&
      !RUNNING(card);

    function ToolboxBoard() {
      const state = useSource("/panel/workbench_board");
      if (state.status === "loading") return h("p", { style: UI.muted }, "读数中…");
      const data = state.data || {};
      if (state.status === "error" || data.ok === false) {
        return errorLine("看板读数不可用", state.error || data.error);
      }
      const cards = (data.reading && data.reading.cards) || [];
      const columns = [
        ["pending", "待办", (card) => card.status === "pending"],
        ["running", "在跑", RUNNING],
        ["done", "已完成", (card) => card.status === "done"],
        ["other", "其它", OTHER],
      ];
      return h("div", { style: { display: "flex", gap: "10px", alignItems: "flex-start" } },
        columns.map(([key, label, pick]) => {
          const rows = cards.filter((card) => pick(card));
          return h("div", {
            key, "data-wb-column": key,
            style: Object.assign({}, UI.card, { flex: "1", minWidth: "0" }),
          },
          h("p", { style: UI.muted }, label + " · " + String(rows.length)),
          rows.slice(0, 40).map((card) => h("div", { key: String(card.id), style: UI.row },
            h("span", { style: UI.muted }, "#" + String(card.id)),
            textCell(card.title || card.task))));
        }));
    }

    function ToolboxPool() {
      const state = useSource("/panel/workbench_board");
      const [filter, setFilter] = react.useState("live");
      if (state.status === "loading") return h("p", { style: UI.muted }, "读数中…");
      const data = state.data || {};
      if (state.status === "error" || data.ok === false) {
        return errorLine("号池读数不可用", state.error || data.error);
      }
      const cards = (data.reading && data.reading.cards) || [];
      const failed = (card) => LIVE(card) && card.status !== "pending" && !RUNNING(card);
      const filters = [
        ["live", "未收口", LIVE],
        ["all", "全部", () => true],
        ["done", "已完成", (card) => card.status === "done"],
        ["failed", "失败/其它", failed],
      ];
      const picked = filters.filter(([key]) => key === filter);
      const rows = cards.filter((picked.length ? picked[0] : filters[0])[2]);
      const head = h("div", { style: Object.assign({}, UI.row, { padding: "8px 10px" }) },
        h("span", { style: Object.assign({}, UI.muted, { width: "64px" }) }, "卡"),
        h("span", { style: Object.assign({}, UI.muted, { width: "120px" }) }, "状态"),
        h("span", { style: UI.muted }, "任务"));
      return h("div", { style: { display: "flex", flexDirection: "column", gap: "10px" } },
        h("div", {
          style: Object.assign({}, UI.card, { display: "flex", gap: "8px", flexWrap: "wrap" }),
        },
        filters.map(([key, label, pick]) => h("button", {
          key, type: "button", "data-wb-filter": key,
          style: filter === key ? UI.primary : UI.secondary,
          onClick: () => setFilter(key),
        }, label + "（" + String(cards.filter(pick).length) + "）"))),
        h("div", { style: Object.assign({}, UI.card, { padding: "0", overflowX: "auto" }) },
          head,
          rows.slice(0, 60).map((card) => h("div", {
            key: String(card.id), style: Object.assign({}, UI.row, { padding: "6px 10px" }),
          },
          h("span", { style: { width: "64px" } }, "#" + String(card.id)),
          h("span", { style: { width: "120px" } }, String(card.status || "")),
          textCell(card.task)))),
        h("p", { style: UI.muted },
          "共 " + String(cards.length) + " 张；当前 " + String(rows.length) + " 张"));
    }

    function ToolboxSkills() {
      const state = useSource("/dsh-panel/skills");
      if (state.status === "loading") return h("p", { style: UI.muted }, "读数中…");
      const data = state.data || {};
      if (state.status === "error" || data.ok === false) {
        return errorLine("技能清单不可用", state.error || data.error);
      }
      const items = data.items || [];
      return h("div", { style: UI.card },
        h("p", { style: UI.muted },
          "仓库 skills/ 下共 " + String(items.length) + " 份（只读）"),
        items.map((item) => h("div", { key: item.name, style: UI.row },
          h("code", { style: { width: "190px" } }, item.name),
          textCell(item.title),
          h("span", { style: Object.assign({}, UI.muted, ELLIPSIS) }, item.summary || ""))));
    }

    function ToolboxParams() {
      const state = useSource(PARAMS_ROUTE);
      if (state.status === "loading") return h("p", { style: UI.muted }, "读数中…");
      const data = state.data || {};
      if (data.ok === false) {
        return errorLine("参数不可用", data.error);
      }
      const values = data.values || {};
      const keys = data.keys || [];
      return h("div", { style: { display: "flex", flexDirection: "column", gap: "10px" } },
        h("div", { style: UI.card },
          h("p", { style: UI.muted },
            "参数文件：" + (data.file || "（还没建）") + "（面板只读；改参数走 CLI）"),
          keys.map((spec) => h("div", { key: spec.key, style: UI.row },
            h("span", { style: UI.muted }, spec.label),
            h("code", null, values[spec.key] === undefined ? "（未设）" : values[spec.key])))));
    }

    function Toolbox() {
      const [tab, setTab] = react.useState("overview");
      const views = {
        overview: ToolboxOverview,
        board: ToolboxBoard,
        pool: ToolboxPool,
        skills: ToolboxSkills,
        params: ToolboxParams,
      };
      const View = views[tab] || ToolboxOverview;
      return h("div", { style: UI.page },
        h("div", { style: UI.head },
          h("h2", { style: UI.title }, "工程工具箱"),
          h("span", { style: { flex: 1 } }),
          TOOLBOX_TABS.map(([key, label]) => h("button", {
            key, "data-wb-tab": key, type: "button",
            style: tab === key ? UI.primary : UI.secondary,
            onClick: () => setTab(key),
          }, label))),
        h(View));
    }

    /* ---- workbench_board：六块，原样 ---- */
    function sectionBlock(key, block, note) {
      if (block === null || block === undefined) {
        return h("section", { key, "data-wb-state": "missing" },
          h("h3", null, key),
          h("p", { "data-wb-note": "" }, note || "这一块读数器没给（缺数据）"));
      }
      return h("section", { key, "data-wb-state": "ok" },
        h("h3", null, key),
        h("pre", null, JSON.stringify(block, null, 2)));
    }
    function WorkbenchBoardView(reading) {
      const board = reading || {};
      return h("div", { "data-wb-state": "ok" },
        h("h2", null, "工作台看板"),
        SECTIONS.map((key) => sectionBlock(key, board[key], board[key + "_note"])));
    }
    function WorkbenchBoard(props) {
      const props2 = { route: props.route, title: "工作台看板", render: WorkbenchBoardView };
      return h(SourceShell, props2);
    }

    /* ---- zentao_gantt：按模型画条（迭代分组 + 任务条） ---- */
    function dayOffset(range, date) {
      if (!range.begin || !date) return null;
      const a = Date.parse(range.begin);
      const b = Date.parse(date);
      if (Number.isNaN(a) || Number.isNaN(b)) return null;
      return Math.round((b - a) / 86400000);
    }
    function ganttBar(range, total, begin, end, label) {
      const start = dayOffset(range, begin);
      const stop = dayOffset(range, end);
      const days = (start === null || stop === null) ? 1 : Math.max(1, stop - start + 1);
      const left = (total > 0 && start !== null) ? (start / total) * 100 : 0;
      const width = total > 0 ? (days / total) * 100 : 100;
      const track = { position: "relative", height: "18px" };
      track.margin = "2px 0";
      track.background = "var(--dsw-alias-bg-base, transparent)";
      const fill = { position: "absolute", left: left + "%", width: width + "%" };
      fill.height = "100%";
      fill.background = "var(--dsw-alias-state-business-primary, currentColor)";
      const text = { position: "relative", paddingLeft: "4px", fontSize: "11px" };
      return h("div", { "data-bar": label, style: track },
        h("div", { style: fill }),
        h("span", { style: text }, label + " " + begin + "→" + end));
    }
    function ZentaoGanttView(reading) {
      const model = reading || {};
      const range = model.range || {};
      const total = Number(range.days) || 0;
      const rows = Array.isArray(model.rows) ? model.rows : [];
      if (!rows.length) {
        return h("div", { "data-wb-state": "missing" }, h("p", null, "甘特没有 rows（缺数据）"));
      }
      const head = "来源 " + String(model.origin || "") + "；范围 " + String(range.begin || "");
      return h("div", { "data-wb-state": "ok" },
        h("h2", null, "禅道迭代甘特"),
        h("p", null, head + " ~ " + String(range.end || "") + "（" + total + " 天）"),
        rows.map((row) => h("section", { key: "exec-" + row.id, "data-wb-state": "ok" },
          h("h3", null, String(row.name || "") + "（" + String(row.status || "") + "）"),
          ganttBar(range, total, row.begin, row.end, String(row.name || "")),
          (Array.isArray(row.tasks) ? row.tasks : []).map((task) =>
            h("div", { key: "task-" + task.id },
              ganttBar(range, total, row.begin, task.deadline, String(task.name || "")))))));
    }
    function ZentaoGantt(props) {
      const props2 = { route: props.route, title: "禅道迭代甘特", render: ZentaoGanttView };
      return h(SourceShell, props2);
    }

    /* ---- timeflow_inbox：列表 ---- */
    function inboxGroup(title, items, render) {
      if (!items.length) {
        return h("section", { "data-wb-state": "missing" },
          h("h3", null, title), h("p", null, "这一类没有条目（缺数据）"));
      }
      return h("section", { "data-wb-state": "ok" },
        h("h3", null, title), h("ul", null, items.map(render)));
    }
    function TimeflowInboxView(reading) {
      const model = reading || {};
      const flip = ((model.status_flip || {}).cards) || [];
      const review = ((model.review || {}).cards) || [];
      const open = ((model.batches || {}).open) || [];
      const line = (item, prefix) =>
        String(item.task || "") + (item.card ? " · 卡" + item.card : "") + " · " + prefix;
      return h("div", { "data-wb-state": "ok" },
        h("h2", null, "timeflow 待办"),
        inboxGroup("待翻 status 的卡", flip, (c, i) =>
          h("li", { key: "f" + i }, line(c, String(c.title || "")))),
        inboxGroup("待复核的卡", review, (c, i) =>
          h("li", { key: "r" + i }, line(c, String(c.title || "")))),
        inboxGroup("待收口的批", open, (b, i) =>
          h("li", { key: "b" + i }, String(b.name || b.id || JSON.stringify(b)))));
    }
    function TimeflowInbox(props) {
      const props2 = { route: props.route, title: "timeflow 待办", render: TimeflowInboxView };
      return h(SourceShell, props2);
    }

    /* ---- 左栏行的图标（卡 242：内联 SVG，不许文字符号） ----
     * 照外壳自己的图标口径画（依据 @deepseek-ai/dsh-client-ui-primitives/lib/index.js）：
     * viewBox "0 0 16 16"、fill none、stroke currentColor、strokeWidth 1（Regular）、
     * aria-hidden、size 由侧栏传入（默认 16）。几何逐字取自：
     * IconGaugeOutlineArtwork :2050（工作台状态）、IconClockOutlineArtwork :2017（timeflow）；
     * 禅道为同口径自画的甘特条。外壳给侧栏行画图标同款做法：
     * dsh-client-ui-schedule/lib/client.js:6196（TaskManagerIcon 用 primitives 的图标组件）。 */
    function makeIcon(paths, round, seatKey) {
      /* 卡 244：第三个参 seatKey —— 有它才订 probeStore 画「未起」小点。
       * ★ 核心行条目只有 {id, order, label}，没有角标槽（sidebar/client.js:454-461、
       *   :187-197）⇒ 角标画进**自己 glyph 的 SVG 内容**里（一个实心小圆）；
       *   这是本插件自画的装饰，**不是**核心角标能力。 */
      return (props) => {
        const size = props && props.size ? props.size : 16;
        const probe = seatKey ? useProbeState(seatKey) : "none";
        const children = paths.map((pair, index) =>
          h("path", { key: index, d: pair[0], fill: pair[1] || undefined }));
        if (probe === "down") {
          /* 「未起」小点：右下角实心圆（currentColor），探测数据来自 probeStore。 */
          children.push(h("circle", {
            key: "wb-badge", cx: 12.5, cy: 12.5, r: 2.5,
            fill: "currentColor", stroke: "none",
          }));
        }
        return h("svg", {
          width: size,
          height: size,
          viewBox: "0 0 16 16",
          fill: "none",
          stroke: "currentColor",
          strokeWidth: 1,
          strokeLinecap: round ? "round" : undefined,
          "aria-hidden": "true",
          style: { flex: "none", verticalAlign: "-2px" },
        }, children);
      };
    }

    /* 卡 247：sidebarRightTabs 也在服务清单里（官方 dsh-session-diff 的 inject 同款：
     * const inject = ["slots","locale","sidebarRightTabs","remote",…] —— 80-apply.js:12）。 */
    const inject = ["slots", "locale", "layout", "sidebarRight", "sidebarRightTabs"];
    function apply(ctx) {
      panelCtx = ctx; /* QuickEntry 的 ctx.sidebarRight.openTab 用（卡 242）。 */
      ctx.effect(() => ctx.locale.register(NS, {
        zh: { __ZH__ },
        en: { __EN__ },
      }), "dsh-panel: labels");
      const t = ctx.locale.bind(NS);
      /* ---- 卡 244 · 逃生门第一半（订阅）：订 ctx.sidebarRight.mounted ----
       * mounted 是 ObservableSnapshot<SessionId | undefined>（service.d.ts:148；
       * 语义原话 :141-143）—— 读快照 + 订变化，把「最后在屏的 sessionId」记进
       * screenSessionId，给 QuickEntry 的 openTabIn 用。 */
      let disposeMounted = null;
      if (panelCtx.sidebarRight && panelCtx.sidebarRight.mounted
        && typeof panelCtx.sidebarRight.mounted.subscribe === "function") {
        const syncMounted = () => {
          screenSessionId = panelCtx.sidebarRight.mounted.getSnapshot() || null;
        };
        disposeMounted = panelCtx.sidebarRight.mounted.subscribe(syncMounted);
        syncMounted();
      }
__REGISTRATIONS__
      const KEYS = __KEYS__;
      const disposeOpen = ctx.reflect.provide("workbenchPanel", {
        // 点左栏一行 = selectPanel(key)；null = 回会话。选中面板不改变当前会话。
        open: (key) => ctx.layout.selectPanel(key),
        seats: KEYS,
      });
      /* ---- 卡 244 · 官方右栏页签：探到 sidebarRight 才注册 ----
       * ★ 官方口子（不许猜 API）：tab 类型注册面 = ctx.get("sidebarRightTabs")
       *   （sidebar-right/lib/client.js:9073 ctx.reflect.provide("sidebarRightTabs", tabs)；
       *   register(definition)：{id, kind, title}，id 重复/kind 冲突会 throw，:8688-8700）；
       *   页签内容 = keyed 座 `sidebar.right.pane.tab`，**key 必须 = 类型 id**
       *   （渲染按 entryKey = definition.id 找注册：client.js:5579；座位声明 :9154-9158）；
       *   guide 条目（{id, order, title()}）让页签出现在右栏「+」的向导里（:8844-8848、
       *   :512 entry.title() 是函数）。ctx.get 是官方插件同款用法（sidebar/client.js:447）。
       * ★ 本包 inject 已含 "sidebarRight" ⇒ 走到 apply 时服务必已提供（探测只是双保险）。 */
      const hasSidebarRight = typeof ctx.get === "function"
        && Boolean(ctx.get("sidebarRight")) && Boolean(ctx.get("sidebarRightTabs"));
      if (hasSidebarRight) { /* 卡 244：探到 sidebarRight 才注册右栏页签（无条件注册 ⇒ 判据咬） */
__RIGHT_TABS__
      }
      return () => {
        disposeOpen();
        if (disposeMounted) disposeMounted();
      };
    }

    exports.apply = apply;
    exports.inject = inject;
    return module.exports;
  },
});
"""


def _client_targets_js() -> str:
    """浏览器半那张 TARGETS 表（卡 242；与 SEATS 同源，key 一一对应）。卡 244 加 seat 字段
    （= 座位 key）：探测状态写进 probeStore 时要用它当键（左栏 glyph 的角标按 key 订）。"""
    rows = [
        f"      {json.dumps(target.seat)}: {{"
        f" seat: {json.dumps(target.seat)},"
        f" url: {json.dumps(target.url)}, up: {json.dumps(target.up_hint)},"
        f" start: {json.dumps(target.start)} }},"
        for target in TARGETS
    ]
    return "\n".join(rows)


def _client_right_tabs_js() -> str:
    """卡 244/247：官方右栏页签的注册体（插在「探到 sidebarRight」的 if 里，8 空格缩进）。

    卡 247：页签 id **带包名前缀**（dsh-session-diff 的 "dsh-session-diff:file" 同型，
    可抄清单 §六.1）；`keepMounted: true` 常驻（sidebar-right/lib/client.js:5522，
    保住滚动位置/登录态）；正文挂 `sidebar.right.pane.tab` keyed 座、**key = 该 id**
    （渲染按 definition.id 找注册，client.js:5579）。正文内容 = 真实页面（QuickEntry：
    browser 口子开 url +「没起 + 怎么起」兜底）。页签 kind 用自定义名 —— kind 撞官方
    "browser" 会 throw（client.js:8688-8700），所以真实页面在正文里开。
    """
    rows: list[str] = []
    for seat in SEATS:
        tab_id = RIGHT_TAB_IDS[seat.key]
        kind = f"workbench-panel-{seat.key}"
        rows.append(
            "        {\n"
            f"          const tabId = {json.dumps(tab_id)};\n"
            f"          const kind = {json.dumps(kind)};\n"
            "          /* 卡 247：id 带包名前缀（dsh-session-diff:file 同型，可抄清单 §六.1）；\n"
            "           * keepMounted: true = 常驻真实页面（保滚动位置/登录态），依据\n"
            "           * sidebar-right/lib/client.js:5522 与 复盘/DSH插件-可抄清单.md §六.1。 */\n"
            "          ctx.sidebarRightTabs.register({\n"
            "            id: tabId,\n"
            "            kind: kind,\n"
            f"            title: () => t({json.dumps(seat.locale_key)}),\n"
            "            keepMounted: true,\n"
            "            guide: [{ id: tabId + \"-guide\","
            f" order: {seat.order + 1},"
            f" title: () => t({json.dumps(seat.locale_key)}) }}],\n"
            "          });\n"
            '          ctx.slots.inject("sidebar.right.pane.tab", () => ctx.slots.register({\n'
            '            name: "sidebar.right.pane.tab",\n'
            "            key: tabId, /* 卡 247：key 必须 = 页签 id（渲染按 definition.id 找） */\n"
            "            locale: NS,\n"
            "          }, function () {\n"
            "            /* 卡 247：正文 = 真实页面（browser 口子开 url）\n"
            "             * +「没起 + 怎么起」兜底（沿用既有口径）。 */\n"
            "            return h(QuickEntry, {"
            f" route: {json.dumps(seat.route)},"
            f" target: TARGETS[{json.dumps(seat.key)}],"
            f" title: {json.dumps(seat.label_zh)}, fallback: {seat.render} }});\n"
            "          }));\n"
            "        }"
        )
    return "\n".join(rows)


def _client_js() -> str:
    return (
        _CLIENT_JS_TEMPLATE.replace("__REGISTRATIONS__", _client_registrations())
        .replace("__RIGHT_TABS__", _client_right_tabs_js())
        .replace("__TARGETS__", _client_targets_js())
        .replace("__ACTION_ROUTE__", ACTION_ROUTE)
        .replace("__STACK_STATUS_ROUTE__", STACK_STATUS_ROUTE)
        .replace("__ZH__", _client_label_map("label_zh"))
        .replace("__EN__", _client_label_map("label_en"))
        .replace("__KEYS__", json.dumps(list(SEAT_KEYS)))
    )


CLIENT_JS = _client_js()


# ================================================================ 生成物：说明文档


INSTALL_DOC = """# 全局面板（快捷入口 + 一键启动）—— 安装 / 接线说明（卡 221~253）

把工作台**三个真实页面**接进 DSH：左栏三行是**快捷入口** —— 每行点开默认给
「开真实页面」的入口 + 目标页连不上时的「没起 + 怎么起」；原来的自绘视图（六块/甘特/列表）
**保留**成可选的「内嵌读数」分支。目的只有一个 —— 用户令：*「尽量不要让我切来切去」*、
*「开到左边栏里」*、*「禅道直接跳可以吗…开真实页面」*（2026-10-15）。

## 这座位是什么

- `dsh-client-ui-layout` 声明了一个 **root 作用域 `main` keyed 座**；`conversation` 是留给
  会话界面的 key。`ctx.layout.selectPanel(id)` 选中一个**已注册**的面板，`null` 选回会话。
- **默认组合不注册任何全局面板** —— 所以现在 DSH 里根本没有这个座位的占用者，得由本包补上。
- 左栏那一行来自 `sidebar.panellist`（list 槽）：侧栏逐条画 `{id, order, label}`，
  **点它 = `selectPanel(id)`** ⇒ 行 id 必须等于 `main` 的 key。

## 三个座位（key = 左栏行 id = 会话内工具名；TARGETS 与座位表同源）

| key | 左栏 label（zh / en） | order | 目标 URL（真实页面） |
| --- | --- | --- | --- |
| `workbench_board` | 工作台状态 / Workbench status | 0 | `http://127.0.0.1:8787/` |
| `zentao_gantt` | 禅道 / ZenTao | 1 | `http://127.0.0.1/zentao/` |
| `timeflow_inbox` | timeflow / timeflow | 2 | `http://127.0.0.1:8520/` |

没起？怎么起（按 key）：

- `workbench_board` ⇒ `python -X utf8 tools/wb_dash.py`
- `zentao_gantt` ⇒ 点 ZenPanel（禅道只听 127.0.0.1:80）
- `timeflow_inbox` ⇒ `python -X utf8 tools/stack.py start timeflow`

## 「开真实页面」的官方口子（卡 242 查到的依据，不许猜 API）

- **服务名与调用形状**：`ctx.sidebarRight.openTab(kind, options?)` —— 依据
  `@deepseek-ai/dsh-client-ui-sidebar-right/lib/types/client/service.d.ts:168`；
  浏览器页的参数形状是 `browser: { url?: string }` —— 依据同包
  `lib/types/client/contract/params.d.ts`（原话：the Browser page adds
  `browser: { url?: string }`）；
  kind = `"browser"`（`dsh-client-ui-sidebar-browser/lib/types/client/definition.d.ts:6`）。
- **官方自己就这么调**：`dsh-client-ui-sidebar-browser/lib/client.js:157-159`
  （`tab.actions.openTab("browser", { params: { url }, revealIfOpened: false })`）。
- 侧栏浏览器**桌面版默认启用**（`dsh-web-app/cordis.patch.yml:277-280`），用 Electron
  `<webview>`，不受 iframe 嵌入限制；**Web 形态**下浏览器页不注册 ⇒ `openTab` 失败
  ⇒ 面板**如实报错**并给出可点的链接，**不假装打开了**。
- **目标页连不上** ⇒ 面板里显式写「没起 + 怎么起」（上面表里那一列），**不许白屏**。

### 逃生门（卡 244：先 `openTabIn`，退路才是 `openTab`）

`openTab` 内部先 `require()` 屏幕会话，无会话 ⇒ 抛 `sidebarRight: no session surface is
mounted`（`dsh-client-ui-sidebar-right/lib/client.js:6385-6396`、`:6744-6752`）；而「屏幕
会话」= *"The Session on screen, or undefined while none is (a global panel fills the main
column, …)"*（`service.d.ts:141-143`）⇒ **本面板占着 `main` 时恰恰是 undefined**：点左栏行
立刻 `openTab`，第一次点击就会抛。所以面板：

1. 订 `ctx.sidebarRight.mounted`（`ObservableSnapshot<SessionId | undefined>`，读快照 +
   订变化），记住**最后在屏的 sessionId**；
2. 点「打开」时优先 `openTabIn(sessionId, "browser", { params: { url } })` —— 它对未
   adopted 的会话**静默无操作**（`client.js:6418-6421`），不会抛；
3. 拿不到 sessionId 才退回 `openTab`，并**保留 catch + 如实报错**（给出可点的链接）。

## 图标（卡 242：不许再用文字符号 `▦` 之类）

左栏三行用**内联 SVG**（16px、`currentColor`、viewBox 16），几何与外壳自己的图标同口径 ——
依据 `@deepseek-ai/dsh-client-ui-primitives/lib/index.js`：工作台状态 =
IconGaugeOutlineArtwork（:2050）、timeflow = IconClockOutlineArtwork（:2017）、禅道 =
同口径自画的甘特条。外壳给侧栏行画图标就是这套做法（`dsh-client-ui-schedule/lib/client.js:6196`
的 TaskManagerIcon 直接用 primitives 的图标组件）。

**包内图标（卡 244）**：包根另有一份 `icon.svg`，清单 `package.json` 的 `icon` 字段用
**相对路径**（`./icon.svg`）指它 —— 那是给清单/市场读的另一个面：相对路径、SVG、远小于
256 KiB、不引用绝对路径/URL（`cordis-plugin-development/.../host-plugin.md:45`）。
左栏行的 glyph **继续用内联 SVG**，两个面不混。

## 兼容字段（卡 244：`peerDependencies` 才是被强制的）

`package.json` 的 `peerDependencies` 里声明了 `"@deepseek-ai/dsh": ">=0.2.0-rc"` ——
真正被强制的只有 `peerDependencies` 里名为 `@deepseek-ai/dsh`（或以 `@deepseek-ai/dsh-`
开头）的 semver 范围：不满足 ⇒ 装前拒（`dsh-app-boot/lib/index.js:286-304`，前缀过滤
在 `:294`；`plugin-manager/index.js:506`）、加载时 throw（`app-boot:929-930`）。
官方 README 原话：*installers and loaders do not enforce `dsh.manifestVersion` or
`engines.dsh`*（`dsh-package-manifest/README.zh.md:93`）—— **别拿 `engines.dsh` 当强制
字段**。范围故意写宽：只表达「需要 dsh 运行时」，不锁小版本（实测运行时 `0.2.0-rc.2`
是 pre-release，app-boot 用 `semver.satisfies(…, { includePrerelease: true })`）。

## 右栏页签与角标（卡 244 · 卡 247 常驻 + 带包名前缀 id）

三个目标各注册一个**官方右栏页签**（正文 = 真实页面的入口 +「没起 + 怎么起」兜底）：

- 页签 id **带包名前缀**（卡 247）：`dsh-client-ui-workbench-panel:board` / `:timeflow` /
  `:zentao` —— 照 `dsh-session-diff` 的 `"dsh-session-diff:file"` 同型
  （`复盘/DSH插件-可抄清单.md` §六.1）；
- 注册面：`ctx.get("sidebarRightTabs").register({ id, kind, title, guide })`（依据
  `dsh-client-ui-sidebar-right/lib/client.js:9073` 的 `reflect.provide("sidebarRightTabs")`）；
- 页签内容：keyed 座 `sidebar.right.pane.tab`，**key = 类型 id**（渲染按
  `definition.id` 找注册，`client.js:5579`）；guide 条目让页签出现在右栏「+」的向导里；
- **常驻（卡 247）**：页签定义带 `keepMounted: true`（依据
  `sidebar-right/lib/client.js:5522`）—— 常驻真实页面，保住滚动位置/登录态；
- **只在宿主真的有右栏服务时才注册**：包的 `dsh.client.inject` 已含
  `sidebarRight`（没有它本包根本不装配），注册体再包一层
  `ctx.get("sidebarRight")` 探测（双保险）。

**左栏底部入口：已删（A273）** 用户 2026-10-17 要求去掉左下角那块；三行页各自带
一键启动 / 全部起 / 分别停，不留重复入口。
左栏行的「未起」小点：核心行条目只有 `{id, order, label}`、**没有角标槽**
（`sidebar/client.js:454-461`、`:187-197`）⇒ 小点画进**自己 glyph 的 SVG 内容**
（目标页探测连不上时右下角一个实心小圆）—— 这是本插件自画的，**不是**核心角标能力。

## 包级显示链路（卡 247：核心不激活插件就能读）

- 包根有 `icon.svg`（清单 `icon` 用相对路径 `./icon.svg` 指它）；
- 包根有 `locale/zh.json` 与 `locale/en.json`，各含
  `{"meta":{"title","description"}}` + 三个座位的标题/说明（按语言给）；
- 清单 `exports` 含 `"./package.json"` 与 `"./locale/*.json"` —— 缺了它们，
  插件管理器/市场卡片**读不到**显示文本与元信息（插件管理器卡片 / bundle 详情 /
  组件行 / 设置里的插件清单都吃这条）。

## 补丁层三纪律（卡 247，照参考仓 cordis.patch.yml 头部注释的口径）

1. **三处 id/name 必须完全一致**：包内 `cordis.patch.yml` insert 的 id 与 name /
   `package.json` 的 name / `lib/index.js` 导出的 name（都是
   `dsh-client-ui-workbench-panel`）—— `--check` 会咬不一致；
2. **必须是「顶层 YAML 数组」**：写成 mapping 会在启动时**直接抛错**，不是静默跳过；
3. **删掉补丁层 = 插件不加载**：把 `cordis.patch.yml` 里的 insert 行整行删掉（或整行
   注释掉）并重启，插件就彻底不加载了 —— 这就是紧急禁用手段之一（写给人看）。

## 包里有什么

| 文件 | 作用 |
| --- | --- |
| `package.json` | 清单：`dsh.bundle.patch` + `dsh.client` + `icon` + `peerDependencies` 等 |
| `icon.svg` | 包内图标（清单 `icon` 用相对路径指它；卡 244） |
| `locale/zh.json` / `locale/en.json` | 包级显示文本（meta + 三座位的标题/说明；卡 247） |
| `cordis.patch.yml` | 包内补丁层（`dsh.bundle.patch` 指向它；root 由 emit 写成真实绝对路径） |
| `lib/index.js` | **宿主半**：三个只读工具 + **一条只读缝**（三条同源路由，只 GET） |
| `lib/client.js` | **浏览器半**：快捷入口 + 右栏常驻页签 + 底部入口 + 内联 SVG 图标 |
| `README.md` | 本说明 |

## 那条只读缝（宿主 → 浏览器）

宿主半用 `ctx.webServer.register({ kind: "prefix", path: "/dsh-panel", handler })` 注册
**一条只读缝**，其下三条同源路由（**只 GET、只本机、只读、不写盘、不起工人**）：

    /dsh-panel/workbench-board    → tools/pipeline_view.py --json --root <root>
    /dsh-panel/zentao-gantt       → tools/zentao_gantt.py --json
    /dsh-panel/timeflow-inbox     → tools/timeflow_inbox.py --json --root <root>

每个 handler 起对应**只读**工具（`spawnSync`、`windowsHide: true`、带超时），把它的 JSON
**原样**回给浏览器。**缺数据**（工具不在 / 非零退出 / 超时 / 输出不是 JSON / 顶层不是对象）
⇒ 回 `{ ok: false, error: "<原话>" }` —— ★ **绝不用空数据冒充成功**。浏览器半用
`fetch("/dsh-panel/…")` 取数（内嵌读数分支用）；失败 ⇒ `data-wb-state="error"` + 原话，
某块缺 ⇒ `data-wb-state="missing"`（**不许白屏**）。

## 怎么被 DSH 加载（两条路，照做，别手改用户配置）

★ **不许去改 `~/.dsh` 里的配置文件**（那是用户的地盘）。只用官方 CLI：

1. **落盘本包**：`python -X utf8 tools/dsh_panel.py --emit <你选的目录>`。
   ★ 插件源码的**真源是本仓的 `tools/dsh_panel.py`**（只在仓库侧产出，不碰 `~/.dsh`）；
   生成物建议放到派生目录（本仓 `.gitignore` 的目录，或临时目录），随时可再 emit。
2. **路 ①（推荐，官方路数）**：`dsh plugin add <那个目录>` —— 本包 `package.json` 里声明了
   `dsh.bundle.patch`（最短官方形态，逐字依据参考仓 dsh-ops 的 `package.json`：
   `"dsh": { "bundle": { "patch": "./cordis.patch.yml" } }`），`dsh plugin add` 会把包内
   `cordis.patch.yml` 当 **profile 层**装。
   ★★ **装本地包必须用 `file:`，绝不可以用 `link:`**：今天实测 —— 用 `link:` 装，
   宿主半会**裸导入**、报 `ERR_MODULE_NOT_FOUND` ⇒ 整行 Loader 条目起不来 ⇒
   界面里**什么都没有**。`file:` 才会把包内容拷进 profile、按 manifest 正常解析。
   ★ 包内 `cordis.patch.yml` 里的 `root:` 由 `--emit` 写成**真实绝对路径**（换目录后重跑 emit）
   （或把 config 换成 `!!js` 从环境读：`root: !!js "process.env.DSH_WORKBENCH_ROOT"`）。
3. **路 ②（保留兼容，老的手写 profile 行）**：把本包加进一个 preset 的 `agent.cordis.yml`，
   或加进 patch 层（`H\\cordis.patch.yml` / profile 的 `cordis.patch.yml`；装包用
   `dsh plugin --profile web add <那个目录>`，同样 `file:` 不 `link:`）。
   patch 语义是**替换整行 config**，不是合并 —— 每一行要重述它拥有的全部键。
   ★★ **这一行必须带上 `config: { root: "<仓库绝对路径>" }`** —— 2026-10-15 在真 DSH 里实测：
   DSH 桌面版**宿主的 cwd 是 profile 目录**（`…\\.dsh\\profiles\\desktop`），拿 cwd 当仓库根会让
   三个读数器全报 `can't open file '…\\profiles\\desktop\\tools\\pipeline_view.py'` ✗。
   例：
   ```yaml
   - insert:
       - id: dsh-client-ui-workbench-panel
         name: "dsh-client-ui-workbench-panel"
         config:
           root: "D:/repo/engineering"
   ```
   （也认环境变量 `DSH_WORKBENCH_ROOT`；两个都没有 ⇒ 工具会**如实吼**「没告诉我仓库根」，不猜。）
4. **重启 profile**：★ 换已挂载包的 manifest **需要重启**（manifest 身份在进程存活期内缓存）。
5. **选中面板**：点侧栏那一行（三行里的任意一行）；或 `ctx.layout.selectPanel("workbench_board")`；
   `null` = 回会话，**不改变当前会话**。点面板里的「打开 …」按钮 = `openTab("browser")`，
   在右侧侧栏浏览器里开真实页面。

## 一键启动与起停入口（卡 253）

目标页「没起」时，面板里直接给**一键启动**按钮（不用再跳文件夹）：

| 目标 | 一键启动动作（= `tools/stack.py` 组件表里那一件） |
| --- | --- |
| `workbench_board` | `board`（`tools/wb_dash.py`，端口 8787） |
| `timeflow_inbox` | `timeflow`（`tools/serve.py`，端口 8520） |
| `zentao_gantt` | `zentao`（mysqld + httpd，起前先探 3306/80，已在听就不重复起） |

面板里还有「**全部起**」（= `python -X utf8 tools/stack.py start`）与每件的「**停这一件**」
（= `stack.py stop <名>`）；状态与 `stack.py status` **同一口径**现读（端口 / pid）。
桌面那份 cmd **原样不动**（那是用户资产）—— 这里只是 DSH 里的一条同样的路。

**反馈如实**：按下先写「已发起启动」；宿主半跑 `stack.py start`，**探到真端口**才回成功，
面板这时才改口「已起（端口 N；映像 X）」；等不到就原样显示
「发起了，但 N 秒内端口还没起来 —— 看 `<gates/diag/stack/log>`」—— 绝不点一下就写「已启动」。

**动作日志**：每次起停写一行到 `gates/diag/stack-actions.log`
（`<时间>  <谁>  <start|stop> <组件>  <OK|FAIL>  <结果>`），面板显示最近几条。

**内存账本**：`stack.py status` 每件带一行 **RSS（MB）** + 末尾**合计**与
**常驻预算 400 MB**；超了在尾行显式提示（不是静默）。面板按同一份读数显示。
★ 面板**点开才读**：没有 `setInterval` 常驻轮询；每次动作后现读一次。

## 只读保证（卡 253 精确化）

数据只经**既有只读工具**（`tools/pipeline_view.py` 卡 207 / `tools/zentao_gantt.py` 卡 223 /
`tools/timeflow_inbox.py` 卡 222）**读**；读数路由**只 GET**。

卡 253 把护栏**改判据、不是删判据**：

- **允许**：起/停 `tools/stack.py` 组件表里那几件**服务**（`board` / `timeflow` / `zentao` /
  `closer` / `trae`）；动作缝只收 `{kind, name}` 两个枚举值，白名单**写死**在宿主半，
  **没有透传任意命令的口子**（`rm -rf` 之类一律拒绝并点名）；
- **仍然禁止**：派工人（`wb_dispatch`）、写仓库文件、改 `~/.dsh`、跑门禁。

目标页本身（wb_dash.py / serve.py / 禅道）归别的卡，本面板只**指向**它们。
用户早先拍过：**拖动只写意图、主控执行** —— 本面板连拖动都没有，只有选中态。
"""


# ================================================================ 自检


def _check_manifest() -> list[str]:
    problems: list[str] = []
    if MANIFEST.get("id") != PANEL_ID:
        problems.append(f"[清单] id 必须 = {PANEL_ID}")
    if not isinstance(MANIFEST.get("order"), int) or MANIFEST["order"] < 0:
        problems.append("[清单] order 必须是 >=0 的整数")
    label = MANIFEST.get("label") or {}
    if not label.get("zh") or not label.get("en"):
        problems.append("[清单] label 必须同时有 zh 与 en")
    if MANIFEST.get("read_only") is not True:
        problems.append("[清单] read_only 必须为 true（面板只读：不写仓库、不派工人）")
    # 卡 253：护栏精确化 —— 允许起停 stack.py 表里那几件服务；仍然禁止派工人/写仓库。
    if MANIFEST.get("service_control") is not True:
        problems.append("[清单] service_control 必须为 true（卡 253：允许起停白名单服务）")
    if "pipeline_view" not in str(MANIFEST.get("data_source", "")):
        problems.append("[清单] data_source 必须点名 tools/pipeline_view.py")
    if list(MANIFEST.get("seats") or []) != list(SEAT_KEYS):
        problems.append("[清单] seats 必须与 SEATS 的 key 逐项一致")
    return problems


def _check_seats() -> list[str]:
    """座位表本身：三个座位、key/order 唯一、label 齐、route 同前缀且唯一。"""
    problems: list[str] = []
    if len(SEATS) != 3:
        problems.append(f"[座位] 应为三个座位，实得 {len(SEATS)}")
    if len(set(SEAT_KEYS)) != len(SEAT_KEYS):
        problems.append("[座位] 座位 key 有重复")
    if len({seat.order for seat in SEATS}) != len(SEATS):
        problems.append("[座位] order 有重复")
    if {seat.order for seat in SEATS} != set(range(len(SEATS))):
        problems.append("[座位] order 必须是 0..n-1 且无洞")
    for seat in SEATS:
        if not seat.label_zh or not seat.label_en:
            problems.append(f"[座位] {seat.key} 的 label 必须同时有 zh 与 en")
        if not seat.icon:
            problems.append(f"[座位] {seat.key} 缺图标 path（左栏就没有图标）")
        if not seat.route.startswith(SEAM_PREFIX):
            problems.append(f"[座位] {seat.key} 的路由必须挂在 {SEAM_PREFIX} 下")
    if len(set(ROUTE_PATHS)) != len(ROUTE_PATHS):
        problems.append("[座位] 路由有重复")
    return problems


def _check_package(package: dict) -> list[str]:
    problems: list[str] = []
    if not package.get("name"):
        problems.append("[package] 缺 name")
    elif package.get("name") != PACKAGE_NAME:
        problems.append(
            f"[package] name 必须是 {PACKAGE_NAME}"
            "（卡 247：补丁层三纪律 —— patch 行 id/name / 清单 name / 宿主半导出名 三处一致）"
        )
    if not package.get("version"):
        problems.append("[package] 缺 version")
    if package.get("type") != "module":
        problems.append("[package] type 必须是 'module'（ESM）")
    if package.get("main") != HOST_REL:
        problems.append(f"[package] main 应指向宿主半 {HOST_REL}")
    exports = package.get("exports") or {}
    if exports.get("./client") != f"./{CLIENT_REL}":
        problems.append(f"[package] exports['./client'] 应指向 {CLIENT_REL}")
    # 卡 247：包级显示链路 —— 缺了它们，核心不激活插件就读不到元信息/显示文本。
    if exports.get("./package.json") != "./package.json":
        problems.append(
            "[package] exports 缺 \"./package.json\""
            "（卡 247：插件管理器/市场要能不激活就读清单）"
        )
    if exports.get("./locale/*.json") != "./locale/*.json":
        problems.append(
            "[package] exports 缺 \"./locale/*.json\""
            "（卡 247：读不到 locale 显示文本 —— 标题/说明给不出来）"
        )
    client = (package.get("dsh") or {}).get("client") or {}
    if client.get("platform") != "web":
        problems.append("[package] dsh.client.platform 必须是 'web'")
    # 卡 242：官方 bundle 形态 —— 与 dsh.client 共存（bundle 是宿主层声明，client 是浏览器半）。
    bundle = (package.get("dsh") or {}).get("bundle") or {}
    if bundle.get("patch") != f"./{PATCH_REL}":
        problems.append(f"[package] dsh.bundle.patch 必须指向 ./{PATCH_REL}（官方 bundle 形态）")
    inject = client.get("inject")
    if not isinstance(inject, list) or not inject:
        problems.append("[package] dsh.client.inject 必须是非空列表")
    else:
        if "@deepseek-ai/dsh-client-ui-layout" not in inject:
            problems.append("[package] dsh.client.inject 必须包含 ui-layout（它拥有 main 座）")
        for bad in CLIENT_INJECT_DENY:
            if bad in inject:
                problems.append(
                    f"[package] dsh.client.inject 不许列 `{bad}`：它没声明 dsh.client，"
                    "不可能是客户端模块提供方（会被组合判成缺提供方）"
                )
    # ---- 卡 244 判据 ----
    peers = package.get("peerDependencies") or {}
    dsh_peer = peers.get("@deepseek-ai/dsh")
    if not isinstance(dsh_peer, str) or not dsh_peer.strip():
        problems.append(
            '[package] 缺 peerDependencies["@deepseek-ai/dsh"]'
            "（唯一被强制的兼容字段，app-boot/lib/index.js:286-304）"
        )
    if "dsh" in (package.get("engines") or {}):
        problems.append(
            "[package] engines.dsh 不被强制（dsh-package-manifest/README.zh.md:93），"
            "别把它当兼容判据写"
        )
    icon = package.get("icon")
    if (
        not isinstance(icon, str)
        or not icon.startswith("./")
        or not icon.endswith(".svg")
        or icon.startswith("/")
        or "http" in icon
    ):
        problems.append("[package] icon 必须是包内相对路径（./icon.svg；不许绝对路径 / http）")
    elif icon != f"./{ICON_REL}":
        problems.append(f"[package] icon 应指向 ./{ICON_REL}")
    return problems


def _check_read_only(name: str, source: str) -> list[str]:
    return [
        f"[只读] {name} 出现越界词 `{token}`（面板不许写仓库 / 起工人）"
        for token in FORBIDDEN_WRITE_TOKENS
        if token in source
    ]


def _client_seat_lists(source: str) -> tuple[list[str], list[str]]:
    """从浏览器半源码里抽出两个列表：`main` 座 key、`sidebar.panellist` 行 id。

    ★ 逐项比这两个列表（写死不许手抄）—— 行 id 与 key 一错位，用户点行就打不开面板。
    """
    def norm(value: str) -> str:
        return PANEL_ID if value == "PANEL_ID" else value.strip('"')

    mains = [norm(m) for m in re.findall(r'name: "main",\s*key: (PANEL_ID|"[^"]+")', source)]
    rows = [
        norm(m)
        for m in re.findall(r'name: "sidebar\.panellist",\s*id: (PANEL_ID|"[^"]+")', source)
    ]
    return mains, rows


def _check_client(source: str) -> list[str]:
    problems: list[str] = []
    if f'const PANEL_ID = "{PANEL_ID}";' not in source:
        problems.append(f'[浏览器半] 缺 `const PANEL_ID = "{PANEL_ID}";`（第一座 id 的唯一真源）')
    if 'name: "main"' not in source:
        problems.append("[浏览器半] 没注册进 `main` 座")
    if "key: PANEL_ID" not in source:
        problems.append("[浏览器半] `main` 注册的 key 必须是 PANEL_ID")
    if '"sidebar.panellist"' not in source:
        problems.append("[浏览器半] 没在 `sidebar.panellist` 挂行（用户就找不到入口）")
    if "id: PANEL_ID" not in source:
        problems.append("[浏览器半] sidebar 行 id 必须是 PANEL_ID（与 main key 一致）")
    mains, rows = _client_seat_lists(source)
    if mains != rows:
        problems.append(f"[浏览器半] 座位不一致：main 座 key {mains} != 行 id {rows}")
    # ★ 卡 A274：允许在三个座位之后追加**非服务行**（目前只有「工程工具箱」一行）；
    #   前 len(SEAT_KEYS) 项必须与 SEAT_KEYS 逐项一致，额外的只许是登记过的 toolbox。
    extra_rows = [key for key in mains if key not in SEAT_KEYS]
    if mains[: len(SEAT_KEYS)] != list(SEAT_KEYS):
        problems.append(f"[浏览器半] 座位顺序与 SEAT_KEYS 不一致：{mains} != {list(SEAT_KEYS)}")
    elif extra_rows not in ([], ["toolbox"]):
        problems.append(f"[浏览器半] 出现未登记的额外行：{extra_rows}")
    if "ctx.layout.selectPanel" not in source:
        problems.append("[浏览器半] 缺 `ctx.layout.selectPanel`（选中/回会话的口子）")
    if "fetch(" not in source:
        problems.append("[浏览器半] 缺 `fetch(`（没取只读缝的读数）")
    if 'data-wb-state="error"' not in source:
        problems.append('[浏览器半] 缺 `data-wb-state="error"` 失败可见分支（会静默白屏）')
    if "data-wb-state" not in source or "missing" not in source:
        problems.append("[浏览器半] 缺「某块缺数据」的显式标注")
    # ---- 卡 242 判据（三行快捷入口）----
    for glyph in TEXT_GLYPH_BAN:
        if glyph in source:
            problems.append(f"[浏览器半] 又出现文字符号 {glyph} 当图标（卡 242：必须内联 SVG）")
    # ---- 卡 251 判据（颜色一律走主题令牌，不许硬编码）----
    hard_colors = [m.group(0) for m in COLOR_LITERAL_RE.finditer(source)]
    if hard_colors:
        problems.append(
            "[浏览器半] 出现硬编码颜色 " + "、".join(sorted(set(hard_colors))[:4])
            + "（卡 251：必须用 `var(--dsw-alias-…, 兜底)` 或 `currentColor` —— 深色主题下会刺眼）"
        )
    if "var(--dsw-alias-" not in source:
        problems.append(
            "[浏览器半] 缺主题令牌 `var(--dsw-alias-…)`（卡 251：甘特条底/填充必须跟主题）"
        )
    if 'viewBox: "0 0 16 16"' not in source or "currentColor" not in source:
        problems.append("[浏览器半] 缺内联 SVG 图标口径（viewBox 16 / currentColor）")
    if 'sidebarRight.openTab("browser"' not in source:
        problems.append(
            '[浏览器半] 缺 ctx.sidebarRight.openTab("browser", { params: { url } })'
            "（卡 242：默认开真实页面）"
        )
    if "service.d.ts:168" not in source or "params.d.ts" not in source:
        problems.append("[浏览器半] 缺「开真实页面」的源码依据注释（service.d.ts / params.d.ts）")
    if "没起" not in source or "怎么起" not in source:
        problems.append("[浏览器半] 缺「没起 + 怎么起」文案（目标页连不上时要显式说）")
    for needle in ("wb_dash.py", "stack.py start timeflow", "ZenPanel"):
        if needle not in source:
            problems.append(f"[浏览器半] 缺「怎么起」的命令原文（{needle}）")
    # ---- 卡 244 判据（逃生门 / 右栏页签 / 自带角标）----
    if "sidebarRight.mounted" not in source or "getSnapshot()" not in source:
        problems.append(
            "[浏览器半] 缺「订 ctx.sidebarRight.mounted 记最后在屏 sessionId」的逃生门"
            "（卡 244：全局面板占 main 时屏幕会话为 undefined，裸 openTab 第一次就抛）"
        )
    if "openTabIn(" not in source:
        problems.append(
            "[浏览器半] 缺 openTabIn 优先的逃生门"
            "（卡 244：对未 adopted 会话静默无操作，client.js:6418-6421）"
        )
    if "client.js:6418-6421" not in source or "service.d.ts:141-143" not in source:
        problems.append(
            "[浏览器半] 缺逃生门的源码依据注释"
            "（client.js:6418-6421 / service.d.ts:141-143）"
        )
    if "const hasSidebarRight =" not in source or 'ctx.get("sidebarRight")' not in source:
        problems.append('[浏览器半] 缺「探到 sidebarRight」的探测（ctx.get("sidebarRight")）')
    if not re.search(r"if \(hasSidebarRight\) \{ /\* 卡 244", source):
        problems.append(
            "[浏览器半] 右栏页签注册没包进「探到 sidebarRight」的 if"
            "（卡 244：不许无条件注册右栏页签）"
        )
    if 'name: "sidebar.right.pane.tab"' not in source:
        problems.append("[浏览器半] 没注册官方右栏页签座位（sidebar.right.pane.tab，卡 244）")
    if "probeStore" not in source or "sidebar/client.js:454-461" not in source:
        problems.append(
            "[浏览器半] 缺「角标画进自己 glyph」的 probeStore 与依据注释"
            "（核心行没有角标槽：sidebar/client.js:454-461，卡 244）"
        )
    # ---- 卡 247 判据（右栏页签带包名前缀 id / keepMounted / 左栏底部入口）----
    if "sidebarRightTabs.register" not in source:
        problems.append("[浏览器半] 缺 sidebarRightTabs.register（卡 247：官方右栏页签注册面）")
    for tab_id in RIGHT_TAB_IDS.values():
        if f'const tabId = "{tab_id}"' not in source:
            problems.append(
                "[浏览器半] 右栏页签 id 缺包名前缀：应有 const tabId = "
                f"\"{tab_id}\"（卡 247：照 dsh-session-diff:file 同型）"
            )
    if "keepMounted: true" not in source or "client.js:5522" not in source:
        problems.append(
            "[浏览器半] 右栏页签缺 keepMounted: true 或其依据注释"
            "（卡 247：常驻真实页面，依据 sidebar-right/lib/client.js:5522）"
        )
    # ---- 卡 253 判据（一键启动 / 如实反馈 / 起停入口 / 点开才读）----
    if "一键启动" not in source:
        problems.append("[浏览器半] 缺「一键启动」按钮（卡 253：「没起」状态要能直接起）")
    if "已发起启动" not in source:
        problems.append("[浏览器半] 缺「已发起启动」的即时反馈（卡 253）")
    if "已起（" not in source:
        problems.append("[浏览器半] 缺「已起（端口 …；映像 …）」的**真起来后**才改口（卡 253）")
    if '(kind === "start-all" || (row && row.running))' not in source:
        problems.append(
            "[浏览器半] 「已起」必须由现读的 `row.running` 决定"
            "（卡 253：不是点了就算；缺 `(kind === \"start-all\" || (row && row.running))`）"
        )
    if "还没起来" not in source or "stack-actions.log" not in source:
        problems.append(
            "[浏览器半] 缺超时原话「发起了，但 N 秒内端口还没起来 —— 看 <日志>」"
            "或动作日志路径（卡 253：不许点一下就写「已启动」）"
        )
    if "全部起" not in source or "停这一件" not in source:
        problems.append("[浏览器半] 缺「全部起 / 停这一件」（卡 253：一起起 / 分别停）")
    if "最近动作" not in source or "RSS" not in source or "常驻预算" not in source:
        problems.append("[浏览器半] 缺最近动作/RSS/常驻预算（卡 253：日志与内存账本要看得见）")
    if "setInterval" in source:
        problems.append(
            "[浏览器半] 出现 `setInterval` 常驻轮询（卡 253：改成「点开/聚焦时才读一次」）"
        )
    if "ACTION_ROUTE" not in source or 'method: "POST"' not in source:
        problems.append("[浏览器半] 缺动作缝调用（ACTION_ROUTE + POST，卡 253）")
    if "STACK_STATUS_ROUTE" not in source:
        problems.append("[浏览器半] 缺服务现读路由（STACK_STATUS_ROUTE，卡 253）")
    problems.extend(_check_read_only("浏览器半", source))
    return problems


def _check_host(source: str) -> list[str]:
    problems: list[str] = []
    if 'name: "workbench_board"' not in source:
        problems.append("[宿主半] 没注册只读工具 workbench_board")
    if f'export const name = "{PACKAGE_NAME}"' not in source:
        problems.append(
            f'[宿主半] 缺导出名 name = "{PACKAGE_NAME}"'
            "（卡 247：补丁层三纪律 —— patch 行 id/name / 清单 name / 宿主半导出名 三处一致）"
        )
    if "defineTool" not in source:
        problems.append("[宿主半] 没注册会话内只读工具（缺 defineTool）")
    if "pipeline_view.py" not in source:
        problems.append("[宿主半] 没调 tools/pipeline_view.py（不许另起一套读逻辑）")
    if "windowsHide" not in source:
        problems.append("[宿主半] 起子进程没带不弹窗旗（windowsHide）")
    if "ok: false" not in source and "ok:false" not in source:
        problems.append("[宿主半] 缺失败显式返回（不许静默返空）")
    if "webServer.register" not in source:
        problems.append("[宿主半] 缺只读缝（webServer.register）")
    # ★ 2026-10-15 实测：DSH 桌面版宿主的 cwd 是 **profile 目录** ⇒ 拿 cwd 当仓库根会让三个读数器
    #   全部 `can't open file '…\\profiles\\desktop\\tools\\*.py'` ✗。所以：必须能从 config 拿根，
    #   且**不许**再用 `process.cwd()` 兜底。
    if "CONFIG_ROOT" not in source or not ("ctx.config" in source or "ctx?.config" in source):
        problems.append("[宿主半] 不能从插件行 config 拿仓库根（缺 CONFIG_ROOT / ctx.config）")
    if "process.cwd()" in source:
        problems.append("[宿主半] 还在拿 process.cwd() 当仓库根 —— DSH 桌面版那里是 profile 目录 ✗")
    if "没告诉我仓库根" not in source:
        problems.append("[宿主半] 没写「没配根就如实吼」那条分支")
    if 'kind: "prefix"' not in source:
        problems.append('[宿主半] 只读缝没按 kind: "prefix" 注册')
    if 'req.method !== "GET"' not in source:
        problems.append('[宿主半] 只读缝没钉住只 GET（缺 req.method !== "GET" 守卫）')
    # 卡 253：护栏精确化 —— 读数只 GET；**动作缝**只 POST、只收白名单里的 {kind,name}。
    for verb in ("PUT", "DELETE", "PATCH"):
        if f'"{verb}"' in source:
            problems.append(f"[宿主半] 出现写方法 {verb}（只读缝只许 GET，动作缝只许 POST）")
    if "ACTION_WHITELIST" not in source:
        problems.append("[宿主半] 缺动作白名单 ACTION_WHITELIST（卡 253：不许透传任意命令）")
    if 'req.method !== "POST"' not in source:
        problems.append('[宿主半] 动作缝没钉住只 POST（缺 req.method !== "POST" 守卫）')
    if "ACTION_ROUTE" not in source or "STACK_STATUS_ROUTE" not in source:
        problems.append("[宿主半] 缺动作缝 / 服务现读路由（ACTION_ROUTE / STACK_STATUS_ROUTE）")
    if "start-all" not in source:
        problems.append("[宿主半] 缺「全部起」（start-all）这条白名单动作（卡 253）")
    for bad in ("shell: true", "shell:true", "exec(", "execSync"):
        if bad in source:
            problems.append(f"[宿主半] 出现 `{bad}` —— 不许 shell 透传命令（卡 253）")
    for seat in SEATS:
        if seat.route not in source:
            problems.append(f"[宿主半] 缺路由 {seat.route}")
    problems.extend(_check_read_only("宿主半", source))
    return problems


def _check_targets(targets: tuple[Target, ...] | None = None) -> list[str]:
    """卡 242：TARGETS 表与座位表同源 —— key 一一对应（同序）、URL 只指本机、「怎么起」齐全。"""
    targets = TARGETS if targets is None else targets
    problems: list[str] = []
    if tuple(t.seat for t in targets) != SEAT_KEYS:
        problems.append(f"[目标] TARGETS 的座位 key 必须与 SEAT_KEYS 一一对应（同序）：{targets}")
    for target in targets:
        if not target.url.startswith("http://127.0.0.1"):
            problems.append(f"[目标] {target.seat} 的 URL 只许指本机（127.0.0.1）：{target.url}")
        if not target.up_hint:
            problems.append(f"[目标] {target.seat} 缺「怎么起」（连不上时要显式说）")
        # 卡 253：三个目标各一条启动动作，且只许是 stack.py 组件表里的那几件。
        if not target.start:
            problems.append(f"[目标] {target.seat} 缺一键启动动作（卡 253）")
        elif target.start not in SERVICE_WHITELIST:
            problems.append(
                f"[目标] {target.seat} 的启动动作 `{target.start}` 不在 stack.py 组件表 "
                f"{SERVICE_WHITELIST} 里（白名单写死，不许透传任意命令）"
            )
    starts = [t.start for t in targets if t.start]
    if len(set(starts)) != len(starts):
        problems.append(f"[目标] 三个目标的一键启动动作必须各不相同：{starts}")
    return problems


def _check_doc(doc: str) -> list[str]:
    problems: list[str] = []
    for needle, why in (
        ("dsh plugin", "缺装包命令"),
        ("--profile web", "缺 profile"),
        ("重启", "没写「换 manifest 要重启」"),
        ("selectPanel", "没写怎么选中面板"),
        ("~/.dsh", "没写「别手改用户配置」"),
        ("默认组合不注册任何", "没写「默认没有面板占用者」"),
        ("file:", "缺「本地包必须用 file: 装」"),
        ("link:", "没写「不许用 link:（会 ERR_MODULE_NOT_FOUND）」"),
        ("config", "没写「插件行要写 config.root（仓库根）」"),
        ("root", "没写「config 里那个键叫 root」"),
        ("dsh plugin add", "没写官方装法路①（dsh plugin add ⇒ bundle.patch 变 profile 层）"),
        ("cordis.patch.yml", "没写包内补丁层那份文件"),
        ("127.0.0.1:8787", "没写工作台的目标 URL（TARGETS）"),
        ("icon.svg", "没写包内图标 icon.svg（卡 244）"),
        ("peerDependencies", "没写「被强制的兼容字段是 peerDependencies」（卡 244）"),
        ("右栏页签", "没写官方右栏页签（卡 244）"),
        ("openTabIn", "没写逃生门 openTabIn（卡 244）"),
        ("keepMounted", "没写右栏页签常驻（卡 247）"),
        ("删掉补丁层 = 插件不加载", "没写补丁层的紧急禁用手段（卡 247 三纪律）"),
        ("locale/zh.json", "没写包级 locale 文件（卡 247：包级显示链路）"),
        ("一键启动", "没写面板一键启动（卡 253）"),
        ("stack-actions.log", "没写动作日志在哪（卡 253）"),
        ("常驻预算", "没写 RSS 内存账本的常驻预算（卡 253）"),
        ("点开才读", "没写「点开才读、没有 setInterval」（卡 253）"),
    ):
        if needle not in doc:
            problems.append(f"[说明] 缺「{why}」（找不到 `{needle}`）")
    return problems


def _check_patch(text: str) -> list[str]:
    """卡 247：补丁层三纪律 —— 顶层 YAML 数组 / 三处 id-name 一致 / 紧急禁用说明写给人看。

    ★ 顶层是否数组用**文本断言**（首行非注释内容以 '- ' 开头）：tomllib 不认 YAML，
      PyYAML 不保证在所有跑门禁的环境里都有（有 PyYAML 的判据在 tests 里用真解析器补）。
    """
    problems: list[str] = []
    first = next(
        (ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")),
        "",
    )
    if not first.startswith("- "):
        problems.append(
            "[补丁层] 顶层必须是 YAML 数组（首行非注释内容要以 '- ' 开头；"
            "写成 mapping 会在启动时直接抛错，不是静默跳过）"
        )
    ids = re.findall(r"^\s*-\s*id:\s*(\S+)\s*$", text, re.M)
    names = re.findall(r'name:\s*"([^"]+)"', text)
    if set(ids) != {PACKAGE_NAME} or set(names) != {PACKAGE_NAME}:
        problems.append(
            f"[补丁层] 补丁行 id/name 必须 = {PACKAGE_NAME}"
            "（卡 247 三纪律：patch 行 id/name / 清单 name / 宿主半导出的 name 三处一致）"
        )
    if "删掉补丁层 = 插件不加载" not in text:
        problems.append(
            "[补丁层] 缺「删掉补丁层 = 插件不加载」的紧急禁用说明（卡 247：要写给人看）"
        )
    return problems


def _check_locale(zh_text: str, en_text: str) -> list[str]:
    """卡 247：两份 locale 是合法 JSON、含 meta.title/meta.description、三个座位按语言给齐。"""
    problems: list[str] = []
    for name, text in (("zh", zh_text), ("en", en_text)):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            problems.append(f"[locale] locale/{name}.json 不是合法 JSON：{exc}")
            continue
        if not isinstance(data, dict):
            problems.append(f"[locale] locale/{name}.json 顶层必须是对象")
            continue
        meta = data.get("meta") or {}
        if not meta.get("title") or not meta.get("description"):
            problems.append(
                f"[locale] locale/{name}.json 缺 meta.title / meta.description"
                "（卡 247：包级显示链路 —— 核心不激活插件就能读标题/说明）"
            )
        seats = data.get("seats") or {}
        for seat in SEAT_KEYS:
            row = seats.get(seat) or {}
            if not row.get("title") or not row.get("description"):
                problems.append(
                    f"[locale] locale/{name}.json 缺座位 {seat} 的 title/description（卡 247）"
                )
    return problems


def check(
    *,
    package: dict | None = None,
    client_js: str | None = None,
    host_js: str | None = None,
    doc: str | None = None,
    patch: str | None = None,
    locale_zh: str | None = None,
    locale_en: str | None = None,
) -> list[str]:
    """清单/schema/座位/只读/失败可见 五项自检 —— 返回问题清单（空 = 绿）。

    可选入参只为**判据造反例**用（默认全用真产物）：传一份「坏源码」进来，判据必须咬。
    卡 247 新增 patch / locale_zh / locale_en 三个面。
    """
    problems: list[str] = []
    problems.extend(_check_manifest())
    problems.extend(_check_seats())
    problems.extend(_check_targets())
    problems.extend(_check_package(package if package is not None else package_manifest()))
    problems.extend(_check_client(client_js if client_js is not None else CLIENT_JS))
    problems.extend(_check_host(host_js if host_js is not None else HOST_JS))
    problems.extend(_check_doc(doc if doc is not None else INSTALL_DOC))
    problems.extend(_check_patch(patch if patch is not None else PATCH_YAML))
    problems.extend(
        _check_locale(
            locale_zh if locale_zh is not None else LOCALE_ZH_JSON,
            locale_en if locale_en is not None else LOCALE_EN_JSON,
        )
    )
    return problems


# ================================================================ 落盘


def package_files() -> dict[str, str]:
    """包内每块内容：`相对路径 -> 文本`（`package.json` 已序列化）。"""
    manifest = json.dumps(package_manifest(), ensure_ascii=False, indent=2) + "\n"
    return {
        MANIFEST_REL: manifest,
        HOST_REL: HOST_JS,
        CLIENT_REL: CLIENT_JS,
        README_REL: INSTALL_DOC,
        PATCH_REL: cordis_patch_yaml(str(ROOT).replace("\\", "/")),
        ICON_REL: ICON_SVG,  # 卡 244：包内图标（清单 icon 用相对路径指它）
        LOCALE_ZH_REL: LOCALE_ZH_JSON,  # 卡 247：包级显示链路（exports ./locale/*.json）
        LOCALE_EN_REL: LOCALE_EN_JSON,
    }


def emit(dest: Path) -> list[Path]:
    """把整套插件源码写到 `dest` 下（缺目录就建）。★ 幂等：同样的输入写出的字节一样。"""
    dest = Path(dest)
    written: list[Path] = []
    for rel, text in package_files().items():
        path = dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path)
    return written


# ================================================================ 只读读数（宿主契约参考实现）


def read_source(name: str, root: Path | None = None, *, script: Path | None = None) -> dict:
    """只读一次读数：调对应座位的只读工具，缺什么如实报（宿主半 handler 的参考实现）。

    返回 `{"ok": True, "reading": {...}}` 或 `{"ok": False, "error": "..."}`。
    ★ 工具不在 / 非零 / 超时 / 输出不是 JSON / 顶层不是对象 ⇒ **一律显式报错**，
      绝不返回空数据冒充成功。
    """
    seat = SEAT_BY_KEY[name]
    root = Path(root) if root is not None else ROOT
    reader = Path(script) if script is not None else (root / seat.script_rel)
    if not reader.is_file():
        return {"ok": False, "error": f"读数器不在：{reader}（数据源缺失）"}
    args = [sys.executable, "-X", "utf8", str(reader), "--json"]
    if seat.needs_root:
        args += ["--root", str(root)]
    try:
        done = subprocess.run(
            args,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=BOARD_TIMEOUT_SECONDS, cwd=str(root), **NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"读数器超时（>{BOARD_TIMEOUT_SECONDS}s）"}
    except OSError as exc:
        return {"ok": False, "error": f"读数器起不来：{exc}"}
    if done.returncode != 0:
        tail = (done.stderr or "").strip()[:400]
        return {"ok": False, "error": f"读数器非零退出（{done.returncode}）：{tail}"}
    try:
        reading = json.loads(done.stdout)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"读数器输出不是 JSON：{exc}"}
    if not isinstance(reading, dict):
        return {"ok": False, "error": "读数器输出顶层不是对象"}
    return {"ok": True, "reading": reading}


def read_board(root: Path | None = None, *, script: Path | None = None) -> dict:
    """工作台看板那一座位的只读读数（卡 221 的既有契约；转发给 read_source）。"""
    return read_source(PANEL_ID, root, script=script)


# ================================================================ CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="全局面板（三座位）：清单/schema/座位 自检，或落盘插件源码（卡 240）",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="清单/schema/座位/只读/失败可见 自检")
    mode.add_argument("--emit", metavar="DIR", help="把插件源码（成稿）写到 DIR")
    mode.add_argument("--doc", action="store_true", help="打印安装/接线说明")
    mode.add_argument("--board", action="store_true", help="只读读数（参考实现）")
    parser.add_argument("--root", default="", help="仓库根（默认本文件推出来）")
    parser.add_argument("--json", action="store_true", help="--board 用：输出 JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.emit:
        written = emit(Path(args.emit))
        for path in written:
            print(f"[写 ] {path}")
        return 0
    if args.doc:
        print(INSTALL_DOC)
        return 0
    if args.board:
        root = Path(args.root) if args.root else ROOT
        result = read_board(root)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        elif result["ok"]:
            print(f"[OK ] 读数到手：{len(result['reading'])} 个顶层键")
        else:
            print(f"[FAIL] {result['error']}")
        return 0 if result["ok"] else 1
    problems = check()
    if problems:
        print(f"[FAIL] 全局面板自检不过（{len(problems)} 条）：", file=sys.stderr)
        for item in problems:
            print("  ·", item, file=sys.stderr)
        return 1
    seats = "、".join(SEAT_KEYS)
    print(f"[OK ] 全局面板自检通过：三座位（{seats}）；只读 + 失败可见 + 只 GET")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
