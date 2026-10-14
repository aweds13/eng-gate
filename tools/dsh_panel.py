#!/usr/bin/env python
"""dsh_panel —— 全局面板：把工作台三个只读面接进 DSH 的全局座位（卡 221 + 卡 240）。

## 为什么有它

用户令：*「我大概都是在你 DSH 这里工作，所以尽量不要让我切来切去」*；2026-10-14 又令：
*「就是可以在 dsh 开出来看…，开到**左边栏**里」*。方案里三个「面」的第 3 个是**全局面板**：
`dsh-client-ui-layout` 暴露一个 root 作用域的 **`main` keyed 座**（`ctx.layout.selectPanel(id)`，
`null` = 会话）。本工具管**面板**那个面 —— 产出「一份能在 DSH 里被照做的面板插件」。

## 交什么（**只在仓库侧产出**）

卡 221 只注册了一个座位（工作台看板），且**宿主→浏览器那条缝不存在**（浏览器半读的
`ctx.workbenchBoardSnapshot()` 没人提供）。本卡（卡 240 · T-G358）把两件事一起做掉：
把 **三个座位**（工作台看板 / 禅道迭代甘特 / timeflow 待办）接进 DSH，并补上**一条只读缝**
（三条同源路由，把对应只读工具的 JSON 原样回给浏览器）。

1. 一个**面板插件包**的源码（`--emit` 落盘）：`package.json` + `lib/index.js`（宿主半）+
   `lib/client.js`（浏览器半）+ `README.md`（安装/接线说明）。
2. 一份**安装/接线说明**（`INSTALL_DOC`；`--doc` 打印，`--emit` 落成包内 `README.md`）。

★ **只读**：面板的数据来自卡 207 / 卡 222 / 卡 223 的**唯一读数器**；面板**不写仓库、
  不起工人**（用户早先拍过：拖动只写意图、主控执行）。`check()` 把这条钉成硬判据。
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

from pool.no_window import NO_WINDOW  # noqa: E402  ★ 卡 148：子进程一律不弹窗（唯一真源）

ROOT = Path(__file__).resolve().parent.parent

#: 面板包名（本地目录即可，⏳ 不必发布 npm）。
PACKAGE_NAME = "dsh-client-ui-workbench-panel"
PACKAGE_VERSION = "0.0.2"

#: 落盘时每块内容相对包根的位置。
HOST_REL = "lib/index.js"
CLIENT_REL = "lib/client.js"
MANIFEST_REL = "package.json"
README_REL = "README.md"

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
    glyph: str  # 左栏行的字形
    route: str  # 只读缝上的路径（同源、只 GET）
    script_rel: str  # 只读工具的仓库相对路径
    needs_root: bool  # 是否把 `--root <root>` 传给它
    locale_key: str  # 浏览器半 locale 文案键
    render: str  # 浏览器半渲染器名


#: ★ 座位表的**唯一真源** —— `main` key 与行 id 都由它生成，不许手抄。
SEATS: tuple[Seat, ...] = (
    Seat(
        key="workbench_board",
        order=0,
        label_zh="工作台看板",
        label_en="Workbench board",
        glyph="\u25a6",
        route=f"{SEAM_PREFIX}/workbench-board",
        script_rel="tools/pipeline_view.py",
        needs_root=True,
        locale_key="panelWorkbenchBoard",
        render="WorkbenchBoard",
    ),
    Seat(
        key="zentao_gantt",
        order=1,
        label_zh="禅道迭代甘特",
        label_en="ZenTao gantt",
        glyph="\u25a4",
        route=f"{SEAM_PREFIX}/zentao-gantt",
        script_rel="tools/zentao_gantt.py",
        needs_root=False,
        locale_key="panelZentaoGantt",
        render="ZentaoGantt",
    ),
    Seat(
        key="timeflow_inbox",
        order=2,
        label_zh="timeflow 待办",
        label_en="timeflow inbox",
        glyph="\u25a5",
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

#: 读数器（卡 207 的唯一读数器）；面板的宿主半只调它，不重写读逻辑。
READER_REL = Path("tools") / "pipeline_view.py"

#: 面板元数据（人读 + 自检用）。`check()` 逐字段验。
MANIFEST = {
    "id": PANEL_ID,
    "order": SEATS[0].order,
    "label": {"zh": SEATS[0].label_zh, "en": SEATS[0].label_en},
    "icon": {"glyph": SEATS[0].glyph, "size": 16},
    "read_only": True,
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
    "@deepseek-ai/dsh-client-locale",
)

#: ★ 实测禁列（2026-10-14，读 DSH 安装里各包的 `package.json`）：
#:   `@deepseek-ai/dsh-client-ui-slots` 的 `dsh` 字段是 **null**（只有 `main`）⇒ 它是宿主侧的库、
#:   不是客户端插件行，**不许**出现在 `inject` 里。`slots` 这个**服务**由浏览器半的
#:   `inject = ["slots", …]`（cordis 服务名）拿到 —— 那是另一条机制，不要混。
#:   ★ 这条 2026-10-14 早上修过一次，晚上被卡 240 的工人**从旧底稿重写时丢掉**了 ⇒ 现在补回
#:   并配判据（`_check_package` + `tests/test_dsh_panel.py`），免得再丢第三次。
CLIENT_INJECT_DENY = ("@deepseek-ai/dsh-client-ui-slots",)


# ================================================================ 生成物：package.json


def package_manifest() -> dict:
    """插件包的 `package.json`（写成 dict，落盘时再序列化）。"""
    return {
        "name": PACKAGE_NAME,
        "version": PACKAGE_VERSION,
        "description": "把工作台三个只读面接到 DSH 的全局座位（卡 221 + 卡 240）。",
        "type": "module",
        "main": HOST_REL,
        "exports": {
            ".": f"./{HOST_REL}",
            "./client": f"./{CLIENT_REL}",
            "./package.json": "./package.json",
        },
        "peerDependencies": {"@deepseek-ai/cordis": "~4.0.4"},
        "dsh": {"client": {"platform": "web", "inject": list(CLIENT_PACKAGE_DEPS)}},
    }


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
import path from "node:path";
import process from "node:process";
import { defineTool } from "@deepseek-ai/dsh-tools";

export const inject = ["tools"];

const SEAM_PREFIX = "/dsh-panel";
const SEAT_TIMEOUT_MS = 30000;

/* 座位表（与浏览器半同源）：name = 会话内工具名 = 座位 key；route = 只读缝路径。 */
const SEATS = [
__SEATS__
];

function repoRoot() {
  return process.env.DSH_WORKBENCH_ROOT || process.cwd();
}

/** 只读一次读数：调对应只读工具，缺什么如实报。 */
function readSeat(seat) {
  const root = repoRoot();
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

/** 只读缝的 handler：只 GET、只认三条已知路由。 */
function serveSeam(req, res) {
  if (req.method !== "GET") {
    sendJson(res, 405, { ok: false, error: `只读缝只接受 GET，收到 ${req.method}` });
    return;
  }
  const url = new URL(req.url || "/", "http://localhost");
  const seat = SEATS.find((row) => row.route === url.pathname);
  if (seat === undefined) {
    sendJson(res, 404, { ok: false, error: `未知路由：${url.pathname}` });
    return;
  }
  sendJson(res, 200, readSeat(seat));
}

export function apply(ctx) {
  /* 会话内三个只读工具：缺哪块如实说哪块，绝不用空数据冒充成功。 */
  for (const seat of SEATS) {
    ctx.tools.register(defineTool({
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
  }
  /* 一条只读缝：三条同源路由。kind 取 "prefix"（与 modules 包注册 /plugins 同款）。 */
  ctx.inject(["webServer"], (webCtx) => {
    webCtx.effect(() => webCtx.webServer.register({
      kind: "prefix",
      path: SEAM_PREFIX,
      handler: serveSeam,
    }), "dsh-panel: read-only seam");
  });
}
"""


def _host_js() -> str:
    return _HOST_JS_TEMPLATE.replace("__SEATS__", _host_seats_js())


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
        blocks.append(
            '      ctx.slots.inject("main", () => ctx.slots.register({\n'
            '        name: "main",\n'
            f"        key: {key_expr},\n"
            "        locale: NS,\n"
            f"        inject: () => ({{ route: {json.dumps(seat.route)} }}),\n"
            f"      }}, {seat.render}));\n"
            '      ctx.slots.inject("sidebar.panellist", () => ctx.slots.register({\n'
            '        name: "sidebar.panellist",\n'
            f"        id: {key_expr},\n"
            f"        order: {seat.order},\n"
            f"        label: () => t({json.dumps(seat.locale_key)}),\n"
            "        locale: NS,\n"
            f"      }}, makeIcon({json.dumps(seat.glyph)})));"
        )
    return "\n".join(blocks)


def _client_label_map(attr: str) -> str:
    return ", ".join(f"{seat.locale_key}: {json.dumps(getattr(seat, attr))}" for seat in SEATS)


_CLIENT_JS_TEMPLATE = r"""/* 卡 221 + 卡 240 产物 · 全局面板：浏览器半 —— 三个座位各占 root 作用域
 * `main` keyed 座的一个 key，并在 `sidebar.panellist` 各挂一行 ⇒ 不切窗口就能看板。
 * 渲染：workbench_board 六块原样；zentao_gantt 条；timeflow_inbox 列表（纯 DOM/SVG）。
 * ★ 只读：不写仓库、不起工人；点选只写「选中态」。★ 加载失败 / 数据源缺失要看得见
 * （data-wb-state="error"），绝不静默白屏；某块缺 ⇒ data-wb-state="missing"。 */
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
      track.background = "#f0f0f0";
      const fill = { position: "absolute", left: left + "%", width: width + "%" };
      fill.height = "100%";
      fill.background = "#7aa7ff";
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

    /* ---- 左栏行的字形 ---- */
    function makeIcon(glyph) {
      return (props) => {
        const size = props && props.size ? props.size : 16;
        return h("span", { style: { fontSize: size + "px", lineHeight: 1 },
          "aria-hidden": "true" }, glyph);
      };
    }

    const inject = ["slots", "locale", "layout"];
    function apply(ctx) {
      ctx.effect(() => ctx.locale.register(NS, {
        zh: { __ZH__ },
        en: { __EN__ },
      }), "dsh-panel: labels");
      const t = ctx.locale.bind(NS);
__REGISTRATIONS__
      const KEYS = __KEYS__;
      const disposeOpen = ctx.reflect.provide("workbenchPanel", {
        // 点左栏一行 = selectPanel(key)；null = 回会话。选中面板不改变当前会话。
        open: (key) => ctx.layout.selectPanel(key),
        seats: KEYS,
      });
      return () => { disposeOpen(); };
    }

    exports.apply = apply;
    exports.inject = inject;
    return module.exports;
  },
});
"""


def _client_js() -> str:
    return (
        _CLIENT_JS_TEMPLATE.replace("__REGISTRATIONS__", _client_registrations())
        .replace("__ZH__", _client_label_map("label_zh"))
        .replace("__EN__", _client_label_map("label_en"))
        .replace("__KEYS__", json.dumps(list(SEAT_KEYS)))
    )


CLIENT_JS = _client_js()


# ================================================================ 生成物：说明文档


INSTALL_DOC = """# 全局面板（三座位）—— 安装 / 接线说明（卡 221 + 卡 240 · T-G358）

把工作台**三个只读面**接进 DSH 的**全局座位**：每个面 = `main` 那座的一个 key +
`sidebar.panellist` 的一行。目的只有一个 —— 用户令：*「尽量不要让我切来切去」*、
*「开到左边栏里」*。

## 这座位是什么

- `dsh-client-ui-layout` 声明了一个 **root 作用域 `main` keyed 座**；`conversation` 是留给
  会话界面的 key。`ctx.layout.selectPanel(id)` 选中一个**已注册**的面板，`null` 选回会话。
- **默认组合不注册任何全局面板** —— 所以现在 DSH 里根本没有这个座位的占用者，得由本包补上。
- 左栏那一行来自 `sidebar.panellist`（list 槽）：侧栏逐条画 `{id, order, label}`，
  **点它 = `selectPanel(id)`** ⇒ 行 id 必须等于 `main` 的 key。

## 三个座位（key = 左栏行 id = 会话内工具名）

| key | 左栏 label（zh / en） | order | 数据源 |
| --- | --- | --- | --- |
| `workbench_board` | 工作台看板 / Workbench board | 0 | `tools/pipeline_view.py --json` |
| `zentao_gantt` | 禅道迭代甘特 / ZenTao gantt | 1 | `tools/zentao_gantt.py --json` |
| `timeflow_inbox` | timeflow 待办 / timeflow inbox | 2 | `tools/timeflow_inbox.py --json` |

## 包里有什么

| 文件 | 作用 |
| --- | --- |
| `package.json` | 清单：`dsh.client.platform = "web"`、`dsh.client.inject`、`exports["./client"]` |
| `lib/index.js` | **宿主半**：三个只读工具 + **一条只读缝**（三条同源路由，只 GET） |
| `lib/client.js` | **浏览器半**：三个座位 + `sidebar.panellist` 三行 + 三块渲染 |
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
`fetch("/dsh-panel/…")` 取数；失败 ⇒ `data-wb-state="error"` + 原话，某块缺 ⇒
`data-wb-state="missing"`（**不许白屏**）。

## 怎么被 DSH 加载（照做，别手改用户配置）

★ **不许去改 `~/.dsh` 里的配置文件**（那是用户的地盘）。只用官方 CLI：

1. **落盘本包**：`python -X utf8 tools/dsh_panel.py --emit <你选的目录>`。
   ★ 插件源码的**真源是本仓的 `tools/dsh_panel.py`**（只在仓库侧产出，不碰 `~/.dsh`）；
   生成物建议放到派生目录（本仓 `.gitignore` 的目录，或临时目录），随时可再 emit。
2. **装进 profile**（本地目录即可，不必发布 npm）：
   `dsh plugin --profile web add <那个目录>`（这条会转发给 pnpm）。
   ★★ **装本地包必须用 `file:`，绝不可以用 `link:`**：今天实测 —— 用 `link:` 装，
   宿主半会**裸导入**、报 `ERR_MODULE_NOT_FOUND` ⇒ 整行 Loader 条目起不来 ⇒
   界面里**什么都没有**。`file:` 才会把包内容拷进 profile、按 manifest 正常解析。
3. **在组成里加一行**：把本包加进一个 preset 的 `agent.cordis.yml`，或加进 patch 层
   （`H\\cordis.patch.yml` / profile 的 `cordis.patch.yml`）。patch 语义是**替换整行 config**，
   不是合并 —— 每一行要重述它拥有的全部键。
4. **重启 profile**：★ 换已挂载包的 manifest **需要重启**（manifest 身份在进程存活期内缓存）。
5. **选中面板**：点侧栏那一行（三行里的任意一行）；或 `ctx.layout.selectPanel("workbench_board")`；
   `null` = 回会话，**不改变当前会话**。

## 只读保证

数据只经**既有只读工具**（`tools/pipeline_view.py` 卡 207 / `tools/zentao_gantt.py` 卡 223 /
`tools/timeflow_inbox.py` 卡 222）**读**；面板**不写仓库、不起工人**，路由**只 GET**。
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
        problems.append("[清单] read_only 必须为 true（面板只读）")
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
        if not seat.glyph:
            problems.append(f"[座位] {seat.key} 缺 glyph（左栏就没有图标）")
        if not seat.route.startswith(SEAM_PREFIX):
            problems.append(f"[座位] {seat.key} 的路由必须挂在 {SEAM_PREFIX} 下")
    if len(set(ROUTE_PATHS)) != len(ROUTE_PATHS):
        problems.append("[座位] 路由有重复")
    return problems


def _check_package(package: dict) -> list[str]:
    problems: list[str] = []
    if not package.get("name"):
        problems.append("[package] 缺 name")
    if not package.get("version"):
        problems.append("[package] 缺 version")
    if package.get("type") != "module":
        problems.append("[package] type 必须是 'module'（ESM）")
    if package.get("main") != HOST_REL:
        problems.append(f"[package] main 应指向宿主半 {HOST_REL}")
    exports = package.get("exports") or {}
    if exports.get("./client") != f"./{CLIENT_REL}":
        problems.append(f"[package] exports['./client'] 应指向 {CLIENT_REL}")
    client = (package.get("dsh") or {}).get("client") or {}
    if client.get("platform") != "web":
        problems.append("[package] dsh.client.platform 必须是 'web'")
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
    if mains != list(SEAT_KEYS):
        problems.append(f"[浏览器半] 座位与 SEAT_KEYS 不一致：{mains} != {list(SEAT_KEYS)}")
    if "ctx.layout.selectPanel" not in source:
        problems.append("[浏览器半] 缺 `ctx.layout.selectPanel`（选中/回会话的口子）")
    if "fetch(" not in source:
        problems.append("[浏览器半] 缺 `fetch(`（没取只读缝的读数）")
    if 'data-wb-state="error"' not in source:
        problems.append('[浏览器半] 缺 `data-wb-state="error"` 失败可见分支（会静默白屏）')
    if "data-wb-state" not in source or "missing" not in source:
        problems.append("[浏览器半] 缺「某块缺数据」的显式标注")
    problems.extend(_check_read_only("浏览器半", source))
    return problems


def _check_host(source: str) -> list[str]:
    problems: list[str] = []
    if 'name: "workbench_board"' not in source:
        problems.append("[宿主半] 没注册只读工具 workbench_board")
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
    if 'kind: "prefix"' not in source:
        problems.append('[宿主半] 只读缝没按 kind: "prefix" 注册')
    if 'req.method !== "GET"' not in source:
        problems.append('[宿主半] 只读缝没钉住只 GET（缺 req.method !== "GET" 守卫）')
    for verb in ("POST", "PUT", "DELETE", "PATCH"):
        if f'"{verb}"' in source:
            problems.append(f"[宿主半] 只读缝出现写方法 {verb}（只许 GET）")
    for seat in SEATS:
        if seat.route not in source:
            problems.append(f"[宿主半] 缺路由 {seat.route}")
    problems.extend(_check_read_only("宿主半", source))
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
    ):
        if needle not in doc:
            problems.append(f"[说明] 缺「{why}」（找不到 `{needle}`）")
    return problems


def check(
    *,
    package: dict | None = None,
    client_js: str | None = None,
    host_js: str | None = None,
    doc: str | None = None,
) -> list[str]:
    """清单/schema/座位/只读/失败可见 五项自检 —— 返回问题清单（空 = 绿）。

    三个可选入参只为**判据造反例**用（默认全用真产物）：传一份「坏源码」进来，判据必须咬。
    """
    problems: list[str] = []
    problems.extend(_check_manifest())
    problems.extend(_check_seats())
    problems.extend(_check_package(package if package is not None else package_manifest()))
    problems.extend(_check_client(client_js if client_js is not None else CLIENT_JS))
    problems.extend(_check_host(host_js if host_js is not None else HOST_JS))
    problems.extend(_check_doc(doc if doc is not None else INSTALL_DOC))
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
