#!/usr/bin/env python
"""dsh_panel —— 全局面板：把工作台看板接进 DSH 的全局座位（卡 221 · T-G335）。

## 为什么有它

用户令：*「我大概都是在你 DSH 这里工作，所以尽量不要让我切来切去」*。方案里三个「面」的
第 3 个是**全局面板**：`dsh-client-ui-layout` 暴露一个 root 作用域的 **`main` keyed 座**
（`ctx.layout.selectPanel(id)`，`null` = 会话；**默认组合不注册任何面板**）。会话内那个面已落
（卡 213 的 MCP 工具），本工具管**面板**那个面 —— 产出「一份能在 DSH 里被照做的面板插件」。

## 交什么（**只在仓库侧产出**）

1. 一个**面板插件包**的源码（`--emit` 落盘）：`package.json` + `lib/index.js`（宿主半）+
   `lib/client.js`（浏览器半）+ `README.md`（安装/接线说明）。宿主半注册一个**只读**工具
   `workbench_board`；浏览器半占据 `main` 座的 `workbench_board` key，并在 `sidebar.panellist`
   挂一行 —— 于是**不切窗口**就能看板。
2. 一份**安装/接线说明**（`INSTALL_DOC`；`--doc` 打印，`--emit` 落成包内 `README.md`）。

★ **只读**：面板的数据来自卡 207 的唯一读数器 `tools/pipeline_view.py`；面板**不写仓库、
  不起工人**（用户早先拍过：拖动只写意图、主控执行）。`check()` 把这条钉成硬判据。
★ **加载失败要看得见**：数据源缺失 / 读数器非零 / 超时 ⇒ 面板与工具**都显式报错**
  （`data-wb-state="error"`），**绝不用空板子冒充成功**。
★ **不许去改用户的 `~/.dsh` 配置**（那是用户的地盘）；说明只交「能被照着做的事」。

## 用法

    python -X utf8 tools/dsh_panel.py --check              # 清单/schema/只读/失败可见 自检
    python -X utf8 tools/dsh_panel.py --emit <目录>        # 落盘那套插件源码（成稿）
    python -X utf8 tools/dsh_panel.py --doc                # 打印安装/接线说明
    python -X utf8 tools/dsh_panel.py --board --root <根>  # 只读读数（宿主契约的参考实现）

退出码：`0` 绿；`1` 自检不过；`2` 用法/环境错误。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# `python -P -X utf8 tools/dsh_panel.py` 也要能 import pool：
_TOOLS_DIR = str(Path(__file__).resolve().parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from pool.no_window import NO_WINDOW  # noqa: E402  ★ 卡 148：子进程一律不弹窗（唯一真源）

ROOT = Path(__file__).resolve().parent.parent

#: 面板的 id —— `main` keyed 座的 key，也是 `sidebar.panellist` 的行 id。二者必须一致。
PANEL_ID = "workbench_board"
#: 面板的语言命名空间。
NS = "workbenchPanel"
#: 面板包名（本地目录即可，⏳ 不必发布 npm）。
PACKAGE_NAME = "dsh-client-ui-workbench-panel"
PACKAGE_VERSION = "0.0.1"

#: 落盘时每块内容相对包根的位置。
HOST_REL = "lib/index.js"
CLIENT_REL = "lib/client.js"
MANIFEST_REL = "package.json"
README_REL = "README.md"

#: 读数器（卡 207 的唯一读数器）；面板的宿主半只调它，不重写读逻辑。
READER_REL = Path("tools") / "pipeline_view.py"
#: 读数子进程超时上限（秒）；超时要如实报错，不静默返空。
#: ★ 本仓卡树多，真读数实测 ~14s（每棵卡树都跑一遍 `git status`）；留 30s 余量。
BOARD_TIMEOUT_SECONDS = 30

#: 六块读数的名字（与 pipeline_view 的顶层键一致）。
SECTIONS = ("cards", "gates", "verdicts", "leases", "fences", "worktrees")

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

#: 面板元数据（人读 + 自检用）。`check()` 逐字段验。
MANIFEST = {
    "id": PANEL_ID,
    "order": 0,
    "label": {"zh": "工作台看板", "en": "Workbench board"},
    "icon": {"glyph": "▦", "size": 16},
    "read_only": True,
    "data_source": "tools/pipeline_view.py --json（卡 207 的唯一读数器）",
    "seat": "root 作用域 `main` keyed 座（key=workbench_board）",
}

#: `dsh.client.inject`：本包依赖的**包名**（顺序 = 装配面）。
CLIENT_PACKAGE_DEPS = (
    "@deepseek-ai/dsh-client-ui-layout",
    "@deepseek-ai/dsh-client-ui-sidebar",
    "@deepseek-ai/dsh-client-ui-slots",
    "@deepseek-ai/dsh-client-locale",
)


# ================================================================ 生成物：package.json


def package_manifest() -> dict:
    """插件包的 `package.json`（写成 dict，落盘时再序列化）。"""
    return {
        "name": PACKAGE_NAME,
        "version": PACKAGE_VERSION,
        "description": "把工作台看板接到 DSH 的全局座位：只读的六块读数面板（卡 221 · T-G335）。",
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


HOST_JS = r"""/* 卡 221 产物 · 工作台看板：宿主半 —— 只读工具 workbench_board。
 * 只调 tools/pipeline_view.py（卡 207 的唯一读数器），不重写读队列/读门禁的逻辑。
 * ★ 缺什么说什么：读数器不在 / 非零 / 超时 / 输出不是 JSON ⇒ 返回 { ok:false, error }，
 *   绝不用空板子冒充成功。★ 只读：不写仓库、不起工人。 */
import { spawnSync } from "node:child_process";
import path from "node:path";
import process from "node:process";
import { defineTool } from "@deepseek-ai/dsh-tools";

export const inject = ["tools"];

const BOARD_TIMEOUT_MS = 30000;
const SECTION_KEYS = ["cards", "gates", "verdicts", "leases", "fences", "worktrees"];

function repoRoot() {
  return process.env.DSH_WORKBENCH_ROOT || process.cwd();
}

/** 只读一次读数：调 tools/pipeline_view.py --json，缺什么如实报。 */
function readBoard(section) {
  const root = repoRoot();
  const script = path.join(root, "tools", "pipeline_view.py");
  const done = spawnSync(
    process.env.DSH_PYTHON || "python",
    ["-X", "utf8", script, "--json", "--root", root],
    {
      encoding: "utf8",
      timeout: BOARD_TIMEOUT_MS,
      windowsHide: true,
      maxBuffer: 16 * 1024 * 1024,
      cwd: root,
    },
  );
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
  if (section) {
    return { ok: true, section, block: reading[section], note: reading[`${section}_note`] };
  }
  return { ok: true, reading };
}

export function apply(ctx) {
  ctx.tools.register(defineTool({
    name: "workbench_board",
    description: [
      "只读：一次性交出工作台看板的六块读数",
      "（卡/门禁/判决/租约/栅栏/卡树，来源 tools/pipeline_view.py）。",
      "缺哪块如实说哪块，绝不用空板子冒充成功。",
    ].join(""),
    parameters: {
      section: {
        type: "string",
        description: `不给 = 全给；给了 = 只要那一块（${SECTION_KEYS.join("/")}）`,
      },
    },
    output: {
      schema: { type: "json" },
      render: (_args, value) => [{ type: "text", text: JSON.stringify(value, null, 2) }],
    },
    async execute(args) {
      return readBoard(args ? args.section : undefined);
    },
  }));
}
"""


# ================================================================ 生成物：浏览器半


CLIENT_JS = r"""/* 卡 221 产物 · 工作台看板：浏览器半 —— 占据 root 作用域 `main` keyed 座的
 * key=workbench_board，并在 `sidebar.panellist` 挂一行 ⇒ 不切窗口就能看板。
 * ★ 只读：不写仓库、不起工人；点选只写「选中态」。★ 加载失败/数据源缺失要看得见
 * （data-wb-state="error"），绝不静默白屏。 */
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

    function WorkbenchBoard(props) {
      const board = props && props.board;
      if (board === undefined || board === null) {
        return h("div", { "data-wb-state": "error", "data-wb-error": "no-source" },
          h("h2", null, "工作台看板：数据源不可用"),
          h("p", null, "面板没拿到 tools/pipeline_view.py 的读数 —— 这不是空板子，是数据源缺失。"),
          h("p", null, "照 README 接线：宿主半的 workbench_board 注册成功、工作目录 = 仓库根。"));
      }
      if (board.ok === false) {
        return h("div", { "data-wb-state": "error", "data-wb-error": "read-failed" },
          h("h2", null, "工作台看板：读数失败"),
          h("p", { "data-wb-error": "" }, String(board.error || "未知错误")));
      }
      const reading = board.reading || {};
      return h("div", { "data-wb-state": "ok" },
        h("h2", null, "工作台看板"),
        SECTIONS.map((key) => sectionBlock(key, reading[key], reading[key + "_note"])));
    }

    function BoardIcon(props) {
      const size = props && props.size ? props.size : 16;
      return h("span", {
        style: { fontSize: size + "px", lineHeight: 1 },
        "aria-hidden": "true",
      }, "▦");
    }

    const inject = ["slots", "locale", "layout"];
    function apply(ctx) {
      ctx.effect(() => ctx.locale.register(NS, {
        zh: { panel: "工作台看板" },
        en: { panel: "Workbench board" },
      }), "dsh-panel: labels");
      const t = ctx.locale.bind(NS);
      ctx.slots.inject("main", () => ctx.slots.register({
        name: "main",
        key: PANEL_ID,
        locale: NS,
        inject: () => ({
          board: ctx.workbenchBoardSnapshot ? ctx.workbenchBoardSnapshot() : undefined,
        }),
      }, WorkbenchBoard));
      ctx.slots.inject("sidebar.panellist", () => ctx.slots.register({
        name: "sidebar.panellist",
        id: PANEL_ID,
        order: 0,
        label: () => t("panel"),
        locale: NS,
      }, BoardIcon));
      // 侧栏那一行 = selectPanel(PANEL_ID)；null = 回会话。选中面板不改变当前会话。
      const disposeOpen = ctx.reflect.provide("workbenchBoard", {
        open: () => ctx.layout.selectPanel(PANEL_ID),
      });
      return () => { disposeOpen(); };
    }

    exports.apply = apply;
    exports.inject = inject;
    return module.exports;
  },
});
"""


# ================================================================ 生成物：说明文档


INSTALL_DOC = """# 全局面板（工作台看板）—— 安装 / 接线说明（卡 221 · T-G335）

把工作台看板接进 DSH 的**全局座位**：`main` 那座的一个 key，加 `sidebar.panellist` 的一行。
目的只有一个 —— 用户令：*「尽量不要让我切来切去」*。

## 这座位是什么

- `dsh-client-ui-layout` 声明了一个 **root 作用域 `main` keyed 座**；`conversation` 是留给
  会话界面的 key。`ctx.layout.selectPanel(id)` 选中一个**已注册**的面板，`null` 选回会话。
- **默认组合不注册任何全局面板** —— 所以现在 DSH 里根本没有这个座位的占用者，得由本包补上。

## 包里有什么

| 文件 | 作用 |
| --- | --- |
| `package.json` | 清单：`dsh.client.platform = "web"`、`dsh.client.inject`、`exports["./client"]` |
| `lib/index.js` | **宿主半**：注册**只读**工具 `workbench_board`（调 `tools/pipeline_view.py`） |
| `lib/client.js` | **浏览器半**：占 `main` 座的 `workbench_board` key + `sidebar.panellist` 一行 |
| `README.md` | 本说明 |

## 怎么被 DSH 加载（照做，别手改用户配置）

★ **不许去改 `~/.dsh` 里的配置文件**（那是用户的地盘）。只用官方 CLI：

1. **落盘本包**：`python -X utf8 tools/dsh_panel.py --emit <你选的目录>`。
   ★ 插件源码的**真源是本仓的 `tools/dsh_panel.py`**（只在仓库侧产出，不碰 `~/.dsh`）；
   生成物建议放到派生目录（本仓 `.gitignore` 的目录，或临时目录），随时可再 emit。
2. **装进 profile**（⏳ 本地目录即可，不必发布 npm）：
   `dsh plugin --profile web add <那个目录>`（这条会转发给 pnpm）。
3. **在组成里加一行**：把本包加进一个 preset 的 `agent.cordis.yml`，或加进 patch 层
   （`H\\cordis.patch.yml` / profile 的 `cordis.patch.yml`）。patch 语义是**替换整行 config**，
   不是合并 —— 每一行要重述它拥有的全部键。
4. **重启 profile**：★ 换已挂载包的 manifest **需要重启**（manifest 身份在进程存活期内缓存）。
5. **选中面板**：点侧栏那一行「工作台看板」；或 `ctx.layout.selectPanel("workbench_board")`；
   `null` = 回会话，**不改变当前会话**。

## ★ 只有一步没验 —— 数据从宿主半到浏览器半的注入 seam

**这份在真 DSH 里一次都没跑过**（本卡环境不具备：装包要 pnpm、改组成要重启、浏览器半要
框架构建工具链）。下表把「验了什么 / 没验什么 / 需要用户做什么」分清：

| 环节 | 状态 |
| --- | --- |
| 清单 schema、只读不变式、失败可见分支 | ✅ 离线自检 + 判据钉住（`tests/test_dsh_panel.py`） |
| 宿主半 `readBoard()` 契约（缺数据如实报） | ✅ `--board` 是同一契约的参考实现 |
| 装包 / 加行 / 重启 后 DSH 真加载 | ❌ **未验** —— 需用户照上面 1–4 步做一遍 |
| 浏览器半拿到读数（`ctx.workbenchBoardSnapshot()`） | ❌ **未验** —— **需要接线**（见下） |

`main` 座的占用者拿数据的标准 seam 是「Host→Client 的 Remote / 或 root-provided 快照」。
本包**没有**自造这条 seam（框架的 Remote 是生成物，手写不出来）。所以你看到的浏览器半读

    ctx.workbenchBoardSnapshot()   // 本包约定的注入点

它由**谁挂进浏览器 ctx**决定：两条可选路径 ——

- **(a) 最省**：让主控/后续卡把这个快照挂进 Client 组成（照 `ui-layout` 用
  `ctx.slots.provideRoot({ hooks: { panelInfo } })` 的同款手法，把 `workbenchBoardSnapshot`
  挂成 root-provided 的 observable）。
- **(b) 会话内**：本包的宿主半已经把只读工具 `workbench_board` 注册进会话 —— 在会话里直接
  `workbench_board`（卡 213 那张卡的 MCP 面也是同一个读数）就能看板，**不依赖**浏览器半的注入。

★ 在这条 seam 接好之前，浏览器半会**显式显示**「数据源不可用」（`data-wb-state="error"`）——
**不是白屏**。这是故意的：宁可看见一条错误，也不要看见一块假板子。

## 只读保证

数据只经 `tools/pipeline_view.py`（卡 207 的唯一读数器）**读**；面板**不写仓库、不起工人**。
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
    elif "@deepseek-ai/dsh-client-ui-layout" not in inject:
        problems.append("[package] dsh.client.inject 必须包含 ui-layout（它拥有 main 座）")
    return problems


def _check_read_only(name: str, source: str) -> list[str]:
    return [
        f"[只读] {name} 出现越界词 `{token}`（面板不许写仓库 / 起工人）"
        for token in FORBIDDEN_WRITE_TOKENS
        if token in source
    ]


def _check_client(source: str) -> list[str]:
    problems: list[str] = []
    if f'const PANEL_ID = "{PANEL_ID}";' not in source:
        problems.append(f'[浏览器半] 缺 `const PANEL_ID = "{PANEL_ID}";`（座位 id 的唯一真源）')
    if 'name: "main"' not in source:
        problems.append("[浏览器半] 没注册进 `main` 座")
    if "key: PANEL_ID" not in source:
        problems.append("[浏览器半] `main` 注册的 key 必须是 PANEL_ID")
    if '"sidebar.panellist"' not in source:
        problems.append("[浏览器半] 没在 `sidebar.panellist` 挂行（用户就找不到入口）")
    if "id: PANEL_ID" not in source:
        problems.append("[浏览器半] sidebar 行 id 必须是 PANEL_ID（与 main key 一致）")
    if "ctx.layout.selectPanel" not in source:
        problems.append("[浏览器半] 缺 `ctx.layout.selectPanel`（选中/回会话的口子）")
    if 'data-wb-state="error"' not in source:
        problems.append("[浏览器半] 缺 `data-wb-state=\"error\"` 失败可见分支（会静默白屏）")
    if "data-wb-state" not in source or "missing" not in source:
        problems.append("[浏览器半] 缺「某块缺数据」的显式标注")
    problems.extend(_check_read_only("浏览器半", source))
    return problems


def _check_host(source: str) -> list[str]:
    problems: list[str] = []
    if 'name: "workbench_board"' not in source:
        problems.append("[宿主半] 没注册只读工具 workbench_board")
    if "pipeline_view.py" not in source:
        problems.append("[宿主半] 没调 tools/pipeline_view.py（不许另起一套读逻辑）")
    if "windowsHide" not in source:
        problems.append("[宿主半] 起子进程没带不弹窗旗（windowsHide）")
    if "ok: false" not in source and "ok:false" not in source:
        problems.append("[宿主半] 缺失败显式返回（不许静默返空）")
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
    """清单/schema/只读/失败可见 四项自检 —— 返回问题清单（空 = 绿）。

    三个可选入参只为**判据造反例**用（默认全用真产物）：传一份「坏源码」进来，判据必须咬。
    """
    problems: list[str] = []
    problems.extend(_check_manifest())
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


def read_board(root: Path | None = None, *, script: Path | None = None) -> dict:
    """只读一次读数：调 `pipeline_view.py --json`，缺什么如实报。

    返回 `{"ok": True, "reading": {...}}` 或 `{"ok": False, "error": "..."}`。
    ★ 数据源缺失 / 非零 / 超时 / 输出不是 JSON ⇒ **一律显式报错**，绝不返回空板子冒充成功。
    """
    root = Path(root) if root is not None else ROOT
    reader = Path(script) if script is not None else (root / READER_REL)
    if not reader.is_file():
        return {"ok": False, "error": f"读数器不在：{reader}（数据源缺失）"}
    try:
        done = subprocess.run(
            [sys.executable, "-X", "utf8", str(reader), "--json", "--root", str(root)],
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


# ================================================================ CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="全局面板（工作台看板）：清单/schema 自检，或落盘插件源码（卡 221）",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="清单/schema/只读/失败可见 自检（默认）")
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
    print(f"[OK ] 全局面板自检通过：id={PANEL_ID}，六块读数，只读 + 失败可见")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
