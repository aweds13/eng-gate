"""全局面板（卡 221 · T-G335）的判据 —— **不连真 DSH**。

判什么（每条都是卡规格里点名的）：

1. **清单 / schema 自检通过** —— `dsh_panel.check()` 返回空；包清单字段齐全、指向正确文件；
2. **落盘的插件源码成稿结构对** —— `package.json` + 宿主半 + 浏览器半 + README 都在；
3. **浏览器半占对座位** —— `main` keyed 座（key=PANEL_ID）+ `sidebar.panellist` 一行；
4. ★ **反例（只读）** —— 给一份带写 API 的浏览器半 ⇒ `check` 必须**红**（证明判据真看得见）；
5. ★ **反例（失败可见）** —— 切掉 `data-wb-state="error"` 分支 ⇒ `check` 必须**红**；
6. ★ **反例（数据源缺失）** —— 读数器不在 / 输出不是 JSON / 非零退出 ⇒ `read_board`
   **如实报错**，**不许**返回一个「看起来正常」的空板子；
7. **真读数** —— 在一份假仓 fixture 上 `read_board` 拿到 `cards` 那一块；
8. **幂等** —— `emit` 两次逐字节一致。

★ 本判据**一条都不碰真 DSH**：它验的是「清单 + 源码 + 宿主读数契约」，跑得动、不依赖 pnpm/浏览器。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import dsh_panel as dp  # noqa: E402  —— 先把 tools/ 挂上 sys.path 才能 import

#: 真读数器（跑假仓 fixture 时显式传它；不抄一份逻辑）。
REAL_READER = ROOT / "tools" / "pipeline_view.py"


def _write_backlog(root: Path) -> None:
    """给假仓铺一份最小 `docs/workbacklog.toml`（一张待派卡）。"""
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "workbacklog.toml").write_text(
        "\n".join(
            [
                "[base]",
                'reviewed = "deadbeef"',
                "[[cards]]",
                'id = "001"',
                'task = "T-G1"',
                'title = "smoke"',
                'tree = ""',
                'spec = "x.md"',
                "files = []",
                "depends = []",
                'risk = "low"',
                'status = "pending"',
                "",
            ]
        ),
        encoding="utf-8",
    )


# ------------------------------------------------------------------ 1. 自检绿


def test_check_is_green() -> None:
    """真产物的清单/schema/只读/失败可见 四项自检 ⇒ 零问题。"""
    assert dp.check() == []


def test_manifest_schema_fields() -> None:
    """清单本身：id / order / label(zh+en) / read_only / data_source 都对。"""
    assert dp.MANIFEST["id"] == dp.PANEL_ID
    assert isinstance(dp.MANIFEST["order"], int) and dp.MANIFEST["order"] >= 0
    assert dp.MANIFEST["label"]["zh"] and dp.MANIFEST["label"]["en"]
    assert dp.MANIFEST["read_only"] is True
    assert "pipeline_view" in dp.MANIFEST["data_source"]


def test_package_manifest_points_at_the_right_files() -> None:
    """包清单：main = 宿主半、exports['./client'] = 浏览器半、platform = web。"""
    pkg = dp.package_manifest()
    assert pkg["type"] == "module"
    assert pkg["main"] == dp.HOST_REL
    assert pkg["exports"]["./client"] == f"./{dp.CLIENT_REL}"
    assert pkg["dsh"]["client"]["platform"] == "web"
    assert "@deepseek-ai/dsh-client-ui-layout" in pkg["dsh"]["client"]["inject"]


# ------------------------------------------------------------------ 2. 成稿落盘


def test_emit_writes_the_whole_package(tmp_path: Path) -> None:
    """`emit` 把八块都落到目标目录，`package.json` 能当 JSON 解析（卡 247：+ 两份 locale）。"""
    written = dp.emit(tmp_path)
    rels = {p.relative_to(tmp_path).as_posix() for p in written}
    assert rels == {
        dp.MANIFEST_REL,
        dp.HOST_REL,
        dp.CLIENT_REL,
        dp.README_REL,
        dp.PATCH_REL,
        dp.ICON_REL,
        dp.LOCALE_ZH_REL,
        dp.LOCALE_EN_REL,
    }
    json.loads((tmp_path / dp.MANIFEST_REL).read_text(encoding="utf-8"))
    for rel in (dp.HOST_REL, dp.CLIENT_REL, dp.README_REL):
        assert (tmp_path / rel).read_text(encoding="utf-8").strip()


def test_emit_is_idempotent(tmp_path: Path) -> None:
    """`emit` 两次 ⇒ 每个文件逐字节一致（同样的输入写出一样的字节）。"""
    dp.emit(tmp_path)
    first = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in dp.emit(tmp_path)}
    second = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in dp.emit(tmp_path)}
    assert first == second


# ------------------------------------------------------------------ 3. 座位对


def test_client_registers_the_global_seat_and_row(tmp_path: Path) -> None:
    """浏览器半：注册进 `main` 座（key=PANEL_ID）+ `sidebar.panellist` 一行 + selectPanel。"""
    dp.emit(tmp_path)
    client = (tmp_path / dp.CLIENT_REL).read_text(encoding="utf-8")
    assert f'const PANEL_ID = "{dp.PANEL_ID}";' in client
    assert 'name: "main"' in client and "key: PANEL_ID" in client
    # ★ 卡 A286：工作台状态并进工具箱后不再单挂一行，所以「id: PANEL_ID」不再是判据
    #   （那一条仍由 ROW_KEYS 与 main 座的比对照看）；行挂载本身必须还在。
    assert '"sidebar.panellist"' in client and "sidebar.panellist" in client
    assert "id: " in client
    assert "ctx.layout.selectPanel" in client


# ------------------------------------------------------------------ 4. ★ 反例：只读


@pytest.mark.parametrize("token", ["writeFileSync", "rmSync", "wb_dispatch"])
def test_read_only_check_bites_on_a_write_api(token: str) -> None:
    """★ 反例：浏览器半里塞写 API / 起工人 ⇒ `check` 必须红并点名那个词。"""
    problems = dp.check(client_js=dp.CLIENT_JS + f'\nconst evil = {token}("a");\n')
    assert any("只读" in p and token in p for p in problems), problems


def test_read_only_check_bites_on_the_host_half() -> None:
    """★ 反例：宿主半里塞 `cordis_run`（起工人/越界）⇒ 必须红。"""
    problems = dp.check(host_js=dp.HOST_JS + "\nexport const evil = cordis_run;\n")
    assert any("只读" in p and "cordis_run" in p for p in problems), problems


# ------------------------------------------------------------------ 5. ★ 反例：失败可见


def test_failure_visible_check_bites_when_error_branch_removed() -> None:
    """★ 反例：切掉 `data-wb-state="error"` ⇒ `check` 必须红（会静默白屏）。"""
    broken = dp.CLIENT_JS.replace('data-wb-state="error"', 'data-wb-state="ok"')
    problems = dp.check(client_js=broken)
    assert any("失败可见" in p for p in problems), problems


# ------------------------------------------------------------------ 6. ★ 反例：数据源缺失


def test_board_reports_missing_source(tmp_path: Path) -> None:
    """★ 反例：读数器不在 ⇒ `ok=False` 且点名「数据源缺失」，绝不空板子冒充成功。"""
    result = dp.read_board(tmp_path)
    assert result["ok"] is False
    assert "数据源缺失" in result["error"]
    assert "reading" not in result


def test_board_reports_non_json_output(tmp_path: Path) -> None:
    """★ 反例：读数器只吐非 JSON ⇒ `ok=False`（别把坏输出当读数）。"""
    bogus = tmp_path / "bogus.py"
    bogus.write_text('print("not json at all")\n', encoding="utf-8")
    result = dp.read_board(tmp_path, script=bogus)
    assert result["ok"] is False
    assert "不是 JSON" in result["error"]


def test_board_reports_nonzero_exit(tmp_path: Path) -> None:
    """★ 反例：读数器非零退出 ⇒ `ok=False` 且带退出码。"""
    bogus = tmp_path / "boom.py"
    bogus.write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
    result = dp.read_board(tmp_path, script=bogus)
    assert result["ok"] is False
    assert "非零退出" in result["error"] and "3" in result["error"]


# ------------------------------------------------------------------ 7. 真读数


def test_board_reads_a_fixture_repo(tmp_path: Path) -> None:
    """在一份假仓上拿到真读数：`cards` 那一块在，基点读出来了。"""
    _write_backlog(tmp_path)
    result = dp.read_board(tmp_path, script=REAL_READER)
    assert result["ok"] is True, result.get("error")
    reading = result["reading"]
    assert isinstance(reading["cards"], list) and len(reading["cards"]) == 1
    assert reading["cards_reviewed"] == "deadbeef"
    assert reading["cards"][0]["id"] == "001"


# ================================================================== 卡 240 · T-G358
# 三座位（main key = sidebar.panellist 行 id）+ 宿主→浏览器那条只读缝（只 GET）。
# ★ 每条都配反例（故意坏掉 ⇒ 判据必须咬）。


def _parse_seat_lists(client: str) -> tuple[list[str], list[str]]:
    """从浏览器半源码里**独立**抽出两个列表：`main` 座 key、`sidebar.panellist` 行 id。

    ★ 故意不调 `dp._client_seat_lists`（那是被测对象自己的解析器）—— 判据要能独立复核。
    """
    def norm(value: str) -> str:
        return dp.PANEL_ID if value == "PANEL_ID" else value.strip('"')

    mains = [norm(m) for m in re.findall(r'name: "main",\s*key: (PANEL_ID|"[^"]+")', client)]
    rows = [
        norm(m)
        for m in re.findall(r'name: "sidebar\.panellist",\s*id: (PANEL_ID|"[^"]+")', client)
    ]
    return mains, rows


# ------------------------------------------------------------ 9. ★ 三座位的 key 与行 id 逐项一致


def test_client_main_keys_equal_sidebar_row_ids(tmp_path: Path) -> None:
    """★ 三个座位：`main` 座 key 与 `sidebar.panellist` 行 id **逐项一致**（不手抄）。"""
    dp.emit(tmp_path)
    client = (tmp_path / dp.CLIENT_REL).read_text(encoding="utf-8")
    mains, rows = _parse_seat_lists(client)
    # ★ 卡 A286：main 座 = 全部座位 + 工具箱；左栏行 = ROW_KEYS + 工具箱。
    #   两边不再逐项相等（工作台状态并入工具箱页签，不再单列一行）。
    assert mains == list(dp.SEAT_KEYS) + ["toolbox"], mains
    assert rows == list(dp.ROW_KEYS) + ["toolbox"], rows
    assert set(rows) <= set(mains), (rows, mains)
    assert dp.SEAT_BY_KEY["workbench_board"].row is False, "工作台状态不该再单挂一行"


def test_seat_consistency_check_bites_when_row_id_drifts() -> None:
    """★ 反例：行 id 与 main key 错位 ⇒ `check` 必须红（用户点行就打不开面板）。"""
    broken = dp.CLIENT_JS.replace('id: "timeflow_inbox"', 'id: "timeflow_inbox_x"')
    assert broken != dp.CLIENT_JS
    problems = dp.check(client_js=broken)
    assert any("左栏行" in p or "座位" in p for p in problems), problems


# ------------------------------------------------------------ 10. ★ 只读缝三条路由只 GET


def test_seam_routes_are_get_only(tmp_path: Path) -> None:
    """★ 三条**读数**路由只 GET；写方法只剩动作缝那一个 POST（卡 253 把判据精确化）。

    ★ 改判据、不是删判据：读数路由仍然钉死 `req.method !== "GET"`，PUT/DELETE/PATCH
    一个不许出现；新增的 POST **只**在 `ACTION_ROUTE` 上、且只收白名单 {kind,name}。
    """
    dp.emit(tmp_path)
    host = (tmp_path / dp.HOST_REL).read_text(encoding="utf-8")
    assert 'req.method !== "GET"' in host
    for verb in ("PUT", "DELETE", "PATCH"):
        assert f'"{verb}"' not in host, verb
    assert "ACTION_WHITELIST" in host
    assert 'req.method !== "POST"' in host
    assert host.count('method === "POST"') == 0  # 只认白名单动作，不是任意 POST 都放行
    assert len(dp.ROUTE_PATHS) == 3
    for seat in dp.SEATS:
        assert seat.route in host


def test_seam_uses_prefix_kind_and_registers_three_tools() -> None:
    """★ 只读缝按 `kind: "prefix"` 注册；三个会话内只读工具都注册了。"""
    host = dp.HOST_JS
    assert dp.SEAM_PREFIX == "/dsh-panel"
    assert 'kind: "prefix"' in host
    assert "webServer.register" in host
    for seat in dp.SEATS:
        assert f'name: "{seat.key}"' in host


def test_get_only_check_bites_when_guard_removed() -> None:
    """★ 反例：拿掉只 GET 守卫 ⇒ `check` 必须红。"""
    broken = dp.HOST_JS.replace('req.method !== "GET"', 'req.method === "n/a"')
    assert broken != dp.HOST_JS
    problems = dp.check(host_js=broken)
    assert any("只 GET" in p for p in problems), problems


# ------------------------------------------------------------ 11. ★ 缺数据 ⇒ ok:false


def test_read_source_missing_tool_is_ok_false(tmp_path: Path) -> None:
    """★ 缺数据：造一个「工具不在」的目录 ⇒ `read_source` 回 `ok:false` + 原话，绝不返空。"""
    for seat in dp.SEATS:
        result = dp.read_source(seat.key, tmp_path)
        assert result["ok"] is False, (seat.key, result)
        assert "数据源缺失" in result["error"], result
        assert "reading" not in result


# ------------------------------------------------------------ 12. ★ 复用 FORBIDDEN_WRITE_TOKENS


@pytest.mark.parametrize("token", dp.FORBIDDEN_WRITE_TOKENS)
def test_forbidden_write_tokens_bite_in_host(token: str) -> None:
    """★ 反例：宿主半塞任一越界词 ⇒ `check` 必须红并点名那个词。"""
    problems = dp.check(host_js=dp.HOST_JS + f'\nconst evil = "{token}";\n')
    assert any("只读" in p and token in p for p in problems), problems


@pytest.mark.parametrize("token", dp.FORBIDDEN_WRITE_TOKENS)
def test_forbidden_write_tokens_bite_in_client(token: str) -> None:
    """★ 反例：浏览器半塞任一越界词 ⇒ `check` 必须红并点名那个词。"""
    problems = dp.check(client_js=dp.CLIENT_JS + f'\nconst evil = "{token}";\n')
    assert any("只读" in p and token in p for p in problems), problems


# ------------------------------------------------------------ 13. ★ 装法必须 file: 且不许 link:


def test_install_doc_requires_file_and_names_link_forbidden() -> None:
    """★ 说明必须写 `file:`，并写明**不许 `link:`**（link: ⇒ ERR_MODULE_NOT_FOUND）。"""
    doc = dp.INSTALL_DOC
    assert "file:" in doc
    assert "link:" in doc
    assert "不许" in doc
    assert "ERR_MODULE_NOT_FOUND" in doc


def test_doc_check_bites_when_file_scheme_missing() -> None:
    """★ 反例：拿掉 `file:` ⇒ `check` 必须红。"""
    problems = dp.check(doc=dp.INSTALL_DOC.replace("file:", "scheme:"))
    assert any("file:" in p for p in problems), problems


# ------------------------------------------------- ★ 反例：禁列（ui-slots 无 dsh.client）


def test_inject_lists_only_real_client_plugin_packages() -> None:
    """★ `dsh.client.inject` 只许列**自己声明 dsh.client 的包**（禁列名单与它不交）。"""
    inject = dp.package_manifest()["dsh"]["client"]["inject"]
    assert not set(inject) & set(dp.CLIENT_INJECT_DENY), inject
    assert "@deepseek-ai/dsh-client-ui-slots" not in inject


def test_inject_check_bites_on_a_non_client_package() -> None:
    """★ 反例：把 ui-slots（实测它 `dsh` 字段是 null）塞进 inject ⇒ 自检必须红并点名。"""
    pkg = dp.package_manifest()
    pkg["dsh"]["client"]["inject"] = [
        *pkg["dsh"]["client"]["inject"],
        "@deepseek-ai/dsh-client-ui-slots",
    ]
    problems = dp._check_package(pkg)
    assert any("dsh-client-ui-slots" in x and "dsh.client" in x for x in problems), problems


# ================================================================== 卡 242 · T-G363
# 三行快捷入口：开真实页面 + 图标合规 + dsh.bundle.patch 化。
# ★ 每条先红后绿；既有判据一条不许删/降级。


# ------------------------------------------------------------ 卡 242-①：bundle.patch 声明 + 真落盘


def test_package_manifest_declares_bundle_patch() -> None:
    """① package.json 同时有 dsh.bundle.patch 与 dsh.client.platform，patch 指 cordis.patch.yml。"""
    pkg = dp.package_manifest()
    assert pkg["dsh"]["bundle"]["patch"] == "./cordis.patch.yml"
    assert pkg["dsh"]["client"]["platform"] == "web"


def test_bundle_patch_is_really_emitted(tmp_path: Path) -> None:
    """① 续：patch 指向的文件在 emitted 目录里真存在，且带我们那一行 insert。"""
    dp.emit(tmp_path)
    patch = tmp_path / dp.PATCH_REL
    assert patch.is_file()
    text = patch.read_text(encoding="utf-8")
    assert "- insert:" in text
    assert dp.PACKAGE_NAME in text
    assert "workbench-panel" in text and "root:" in text


def test_bundle_check_bites_when_patch_missing() -> None:
    """① 反例：拿掉 dsh.bundle.patch ⇒ 自检必须红。"""
    pkg = dp.package_manifest()
    del pkg["dsh"]["bundle"]
    problems = dp._check_package(pkg)
    assert any("bundle" in p for p in problems), problems


# ------------------------------------------------ 卡 242-②：key 不改名 + TARGETS 对应


def test_seat_keys_are_unchanged() -> None:
    """② 三个座位 key 未改名（改名会毁掉已落地的判据与左栏 id 约定）。"""
    assert dp.SEAT_KEYS == ("workbench_board", "zentao_gantt", "timeflow_inbox")


def test_targets_map_three_urls_to_three_keys() -> None:
    """② 新 TARGETS 表：三条 URL 与座位 key 一一对应（同源、只指本机 127.0.0.1）。"""
    assert tuple(t.seat for t in dp.TARGETS) == dp.SEAT_KEYS
    urls = {t.seat: t.url for t in dp.TARGETS}
    assert urls == {
        "workbench_board": "http://127.0.0.1:8787/",
        "zentao_gantt": "http://127.0.0.1/zentao/",
        "timeflow_inbox": "http://127.0.0.1:8520/",
    }


def test_targets_check_bites_on_drift() -> None:
    """② 反例：TARGETS 与座位表错位 ⇒ 自检必须红。"""
    problems = dp._check_targets(dp.TARGETS[:2])
    assert problems, "少一条目标也必须被咬住"


def test_client_labels_are_the_three_new_shortcuts(tmp_path: Path) -> None:
    """② 三行 label：工作台状态 / 禅道 / timeflow（key 不变，只改文案）。"""
    dp.emit(tmp_path)
    client = (tmp_path / dp.CLIENT_REL).read_text(encoding="utf-8")
    for label in ("工作台状态", "禅道", "timeflow"):
        assert label in client, label


# ------------------------------------------------------------ 卡 242-③：开真实页面那条路必须有据


def test_client_opens_real_pages_and_cites_evidence(tmp_path: Path) -> None:
    """③ 「开真实页面」有据：openTab("browser") 的调用 + 源码里的依据注释（file:行号）。"""
    dp.emit(tmp_path)
    client = (tmp_path / dp.CLIENT_REL).read_text(encoding="utf-8")
    assert 'sidebarRight.openTab("browser"' in client
    assert "service.d.ts:168" in client and "params.d.ts" in client


def test_open_tab_check_bites_when_official_path_removed() -> None:
    """③ 反例：切掉官方口子 ⇒ check 必须红。"""
    broken = dp.CLIENT_JS.replace(
        'sidebarRight.openTab("browser"', 'sidebarRight.openTab("other"'
    )
    assert broken != dp.CLIENT_JS
    problems = dp.check(client_js=broken)
    assert any("openTab" in p for p in problems), problems


# ------------------------------------------------ 卡 242-④：没起要显式说怎么起


def test_client_says_how_to_start_when_page_is_down(tmp_path: Path) -> None:
    """④ 目标页连不上 ⇒ 「没起 + 怎么起」文案与三条启动命令都在（不许白屏）。"""
    dp.emit(tmp_path)
    client = (tmp_path / dp.CLIENT_REL).read_text(encoding="utf-8")
    assert "没起" in client and "怎么起" in client
    for needle in ("wb_dash.py", "stack.py start timeflow", "ZenPanel"):
        assert needle in client, needle


def test_down_hint_check_bites_when_copy_removed() -> None:
    """④ 反例：切掉「没起/怎么起」⇒ check 必须红。"""
    broken = dp.CLIENT_JS.replace("没起", "").replace("怎么起", "")
    assert broken != dp.CLIENT_JS
    problems = dp.check(client_js=broken)
    assert any("没起" in p or "怎么起" in p for p in problems), problems


# ------------------------------------------------ 卡 242-⑤：图标合规（内联 SVG）


def test_icons_are_inline_svg_not_text_glyphs(tmp_path: Path) -> None:
    """⑤ 图标合规：16px viewBox + currentColor 的内联 SVG；文字符号一个不许有。"""
    dp.emit(tmp_path)
    client = (tmp_path / dp.CLIENT_REL).read_text(encoding="utf-8")
    assert 'viewBox: "0 0 16 16"' in client and "currentColor" in client
    for glyph in dp.TEXT_GLYPH_BAN:
        assert glyph not in client


def test_glyph_ban_check_bites_when_glyph_returns() -> None:
    """⑤ 反例：塞回一个文字符号 ⇒ check 必须红。"""
    broken = dp.CLIENT_JS + '\nconst evil = "' + dp.TEXT_GLYPH_BAN[0] + '";\n'
    problems = dp.check(client_js=broken)
    assert any("文字符号" in p for p in problems), problems


def test_icon_svg_convention_check_bites_when_removed() -> None:
    """⑤ 反例：图标口径被改掉（viewBox 不是 16）⇒ check 必须红。"""
    broken = dp.CLIENT_JS.replace('viewBox: "0 0 16 16"', 'viewBox: "0 0 24 24"')
    assert broken != dp.CLIENT_JS
    problems = dp.check(client_js=broken)
    assert any("图标" in p for p in problems), problems


# ------------------------------------------------------------ 卡 242-⑥：说明两条装路都写清


def test_install_doc_names_both_install_paths() -> None:
    """④ 安装说明两条路都写清：官方 dsh plugin add（bundle.patch）+ 老的手写 profile 行。"""
    assert "dsh plugin add" in dp.INSTALL_DOC
    assert "cordis.patch.yml" in dp.INSTALL_DOC
    assert "127.0.0.1:8787" in dp.INSTALL_DOC


# ================================================================== 卡 244 · T-G365
# 面板收尾四件：逃生门 / 真·兼容字段 / 包内图标 / 右栏页签 + 自带角标。
# ★ 每条先红后绿；既有判据一条不许删/降级。


# ------------------------------------------------------------ 卡 244-a：逃生门


def test_client_subscribes_mounted_and_prefers_open_tab_in(tmp_path: Path) -> None:
    """a 逃生门：订 `sidebarRight.mounted` 记最后在屏 sessionId；开页优先 `openTabIn`。

    依据（写进源码注释）：openTab/openResource 内部先 require() 屏幕会话，无会话抛
    "no session surface is mounted"（sidebar-right/lib/client.js:6385-6396、:6744-6752）；
    「屏幕会话」= The Session on screen, or undefined while none is —— 全局面板占 main
    恰是 undefined 形态（service.d.ts:141-143）；openTabIn 对未 adopted 会话静默无操作
    （client.js:6418-6421）。
    """
    dp.emit(tmp_path)
    client = (tmp_path / dp.CLIENT_REL).read_text(encoding="utf-8")
    assert "sidebarRight.mounted" in client
    assert "getSnapshot()" in client  # mounted 是 ObservableSnapshot：读快照记 sessionId
    assert "openTabIn(" in client
    assert "client.js:6418-6421" in client and "service.d.ts:141-143" in client


def test_escape_hatch_check_bites_when_open_tab_in_removed() -> None:
    """a 反例：把 openTabIn 删掉 ⇒ check 必须红。"""
    broken = dp.CLIENT_JS.replace("openTabIn(", "openTabGone(")
    assert broken != dp.CLIENT_JS
    problems = dp.check(client_js=broken)
    assert any("openTabIn" in p for p in problems), problems


def test_escape_hatch_check_bites_when_mounted_subscription_removed() -> None:
    """a 反例：切掉 mounted 订阅 ⇒ check 必须红（退回裸 openTab，第一次点击就抛）。"""
    broken = dp.CLIENT_JS.replace("sidebarRight.mounted", "sidebarRight.__gone__")
    assert broken != dp.CLIENT_JS
    problems = dp.check(client_js=broken)
    assert any("mounted" in p for p in problems), problems


# ------------------------------------------------------------ 卡 244-b：真·兼容字段


def test_manifest_declares_enforced_dsh_peer() -> None:
    """b 被强制的只有 peerDependencies 里名为 @deepseek-ai/dsh 的 semver 范围
    （dsh-app-boot/lib/index.js:286-304，前缀过滤 :294）；engines.dsh 不被强制
    （dsh-package-manifest/README.zh.md:93）⇒ 不许写。"""
    pkg = dp.package_manifest()
    peers = pkg["peerDependencies"]
    assert peers["@deepseek-ai/dsh"] == dp.DSH_PEER_RANGE
    # 宽范围：实测运行时 0.2.0-rc.2（pre-release），app-boot 用 semver.satisfies(includePrerelease)
    assert peers["@deepseek-ai/dsh"].startswith(">=")
    assert "dsh" not in (pkg.get("engines") or {})


def test_peer_check_bites_when_only_engines_dsh() -> None:
    """b 反例：改成只有 engines.dsh ⇒ check 必须红。"""
    pkg = dp.package_manifest()
    del pkg["peerDependencies"]["@deepseek-ai/dsh"]
    pkg["engines"] = {"dsh": dp.DSH_PEER_RANGE}
    problems = dp._check_package(pkg)
    assert any("peerDependencies" in p for p in problems), problems


# ------------------------------------------------------------ 卡 244-c：包内图标


def test_package_icon_emitted_and_relative(tmp_path: Path) -> None:
    """c 生成包内有 icon.svg；清单 icon 是包内相对路径（不许 / 开头、不许 http）。

    图标核心规则是协议级的：相对路径、SVG/PNG/JPEG/WebP、≤256 KiB、拒绝绝对路径/URL
    （cordis-plugin-development/.../host-plugin.md:45）。
    """
    dp.emit(tmp_path)
    icon_path = tmp_path / dp.ICON_REL
    assert icon_path.is_file()
    svg = icon_path.read_text(encoding="utf-8")
    assert "<svg" in svg and "</svg>" in svg
    assert len(svg.encode("utf-8")) < 256 * 1024  # 协议上限远够
    assert "href" not in svg and "url(" not in svg  # 不引用外部资源
    icon = dp.package_manifest()["icon"]
    assert icon == f"./{dp.ICON_REL}"
    assert not icon.startswith("/") and "http" not in icon


def test_icon_check_bites_on_absolute_path() -> None:
    """c 反例：清单 icon 写成绝对路径 ⇒ check 必须红。"""
    pkg = dp.package_manifest()
    pkg["icon"] = "C:/icons/icon.svg"
    problems = dp._check_package(pkg)
    assert any("icon" in p for p in problems), problems


# ------------------------------------------------------------ 卡 244-d：右栏页签守卫


def test_right_tabs_registered_only_when_sidebar_right_probed(tmp_path: Path) -> None:
    """d 三个目标各注册一个右栏页签，且注册体包在「探到 sidebarRight」的 if 里。

    官方口子：tab 类型注册面 = ctx.get("sidebarRightTabs")（sidebar-right/lib/client.js:9073
    reflect.provide）；页签内容 = keyed 座 sidebar.right.pane.tab，key 必须 = 类型 id
    （渲染按 entryKey = definition.id 找注册，client.js:5579；座位声明 :9154-9158）。
    """
    dp.emit(tmp_path)
    client = (tmp_path / dp.CLIENT_REL).read_text(encoding="utf-8")
    assert 'name: "sidebar.right.pane.tab"' in client
    assert 'ctx.get("sidebarRight")' in client
    # 守卫：if (hasSidebarRight) { /* 卡 244：… */ —— 注册体必须在这层 if 里
    assert re.search(r'if \(hasSidebarRight\) \{ /\* 卡 244', client)
    # 卡 247：页签 id 改成带包名前缀（参照 dsh-session-diff 的 "dsh-session-diff:file"）。
    for tab_id in dp.RIGHT_TAB_IDS.values():
        assert f'const tabId = "{tab_id}"' in client, tab_id


def test_right_tab_check_bites_when_guard_removed() -> None:
    """d 反例：无条件注册（拆掉守卫）⇒ check 必须红。"""
    broken = re.sub(
        r'if \(hasSidebarRight\) \{ /\*[^*]*\*/', "if (true) { /*", dp.CLIENT_JS, count=1
    )
    assert broken != dp.CLIENT_JS
    problems = dp.check(client_js=broken)
    assert any("右栏页签" in p for p in problems), problems


# ------------------------------------------------------------ 卡 244-e：角标画在自己 glyph 里


def test_badge_is_drawn_into_own_glyph_not_a_core_slot(tmp_path: Path) -> None:
    """e 核心行条目只有 {id, order, label}，没有角标槽（sidebar/client.js:454-461、:187-197）
    ⇒ 「未起」的小点画进自己的 glyph 内容（probeStore），且不声称是核心角标能力。"""
    dp.emit(tmp_path)
    client = (tmp_path / dp.CLIENT_REL).read_text(encoding="utf-8")
    assert "probeStore" in client
    assert "sidebar/client.js:454-461" in client


def test_badge_check_bites_when_probe_store_removed() -> None:
    """e 反例：切掉 probeStore（角标数据源）⇒ check 必须红。"""
    broken = dp.CLIENT_JS.replace("probeStore", "probeGone")
    assert broken != dp.CLIENT_JS
    problems = dp.check(client_js=broken)
    assert any("probeStore" in p for p in problems), problems


# ------------------------------------------------------------ 卡 244：说明文档跟上


def test_install_doc_mentions_icon_peer_and_right_tabs() -> None:
    """说明文档要跟上四件事：icon.svg / peerDependencies / 右栏页签 / 逃生门。"""
    for needle in ("icon.svg", "peerDependencies", "右栏页签", "openTabIn"):
        assert needle in dp.INSTALL_DOC, needle


# ================================================================== 卡 247 · T-G368
# 右栏常驻页签（带包名前缀 id + keepMounted）+ 包级显示链路 + 补丁层三纪律 + 底部入口。
# ★ 每条先红后绿；既有判据一条不许删/降级（244 那套原样保留，页签 id 按本卡规格迁移）。


def test_right_tab_ids_carry_package_prefix(tmp_path: Path) -> None:
    """① 页签 id 带包名前缀（"dsh-session-diff:file" 同型，可抄清单 §六.1）+ 正文挂对槽。

    类型注册面 = ctx.sidebarRightTabs.register；正文 = keyed 座 sidebar.right.pane.tab，
    key = 该 id（渲染按 definition.id 找注册，sidebar-right/lib/client.js:5579）。
    """
    dp.emit(tmp_path)
    client = (tmp_path / dp.CLIENT_REL).read_text(encoding="utf-8")
    assert "sidebarRightTabs.register" in client
    assert '"sidebar.right.pane.tab"' in client
    assert set(dp.RIGHT_TAB_IDS) == set(dp.SEAT_KEYS)
    for tab_id in dp.RIGHT_TAB_IDS.values():
        assert tab_id.startswith(dp.PACKAGE_NAME + ":"), tab_id
        assert f'const tabId = "{tab_id}"' in client, tab_id
    assert "key: tabId" in client  # 正文座的 key = 页签 id


def test_right_tab_prefix_check_bites_when_prefix_stripped() -> None:
    """① 反例：把 id 改成不带前缀 ⇒ check 必须红。"""
    board_id = dp.RIGHT_TAB_IDS["workbench_board"]
    broken = dp.CLIENT_JS.replace(f'const tabId = "{board_id}"', 'const tabId = "board"')
    assert broken != dp.CLIENT_JS
    problems = dp.check(client_js=broken)
    assert any("页签" in p and "前缀" in p for p in problems), problems


def test_right_tab_body_opens_the_real_page(tmp_path: Path) -> None:
    """① 正文 = 真实页面（browser 口子的入口 + url）+「没起 + 怎么起」兜底（QuickEntry）。"""
    dp.emit(tmp_path)
    client = (tmp_path / dp.CLIENT_REL).read_text(encoding="utf-8")
    assert "h(QuickEntry, { route:" in client  # 右栏页签正文复用快捷入口
    assert "没起" in client and "怎么起" in client  # 兜底文案（既有口径）


def test_right_tabs_are_keep_mounted_with_evidence(tmp_path: Path) -> None:
    """② keepMounted 打开（常驻真实页面，保滚动位置/登录态），注释写明依据 文件:行号。

    依据：sidebar-right/lib/client.js:5522（页签定义的 keepMounted 开关）；
    复盘/DSH插件-可抄清单.md §六.1。
    """
    dp.emit(tmp_path)
    client = (tmp_path / dp.CLIENT_REL).read_text(encoding="utf-8")
    assert "keepMounted: true" in client
    assert "client.js:5522" in client


def test_keep_mounted_check_bites_when_removed() -> None:
    """② 反例：删掉 keepMounted ⇒ check 必须红。"""
    broken = dp.CLIENT_JS.replace("keepMounted: true", "keepMounted: false")
    assert broken != dp.CLIENT_JS
    problems = dp.check(client_js=broken)
    assert any("keepMounted" in p for p in problems), problems


def test_package_display_chain_files_and_exports(tmp_path: Path) -> None:
    """③ 包级显示链路：icon.svg + locale/zh.json + locale/en.json 都落盘；
    清单 exports 含 ./package.json 与 ./locale/*.json（缺了插件管理器读不到显示文本/图标）。"""
    dp.emit(tmp_path)
    for rel in (dp.ICON_REL, dp.LOCALE_ZH_REL, dp.LOCALE_EN_REL):
        assert (tmp_path / rel).is_file(), rel
    pkg = dp.package_manifest()
    assert pkg["exports"]["./package.json"] == "./package.json"
    assert pkg["exports"]["./locale/*.json"] == "./locale/*.json"
    assert pkg["icon"] == f"./{dp.ICON_REL}"


def test_display_exports_check_bites_when_removed() -> None:
    """③ 反例：exports 去掉任一 ⇒ check 必须红。"""
    pkg = dp.package_manifest()
    del pkg["exports"]["./locale/*.json"]
    problems = dp._check_package(pkg)
    assert any("locale" in p for p in problems), problems


def test_locale_files_are_valid_json_with_meta(tmp_path: Path) -> None:
    """④ locale/zh.json 与 en.json 是合法 JSON，各含 meta.title / meta.description，
    且三个座位的标题/说明按语言给齐（包级显示链路：核心不激活插件就能读）。"""
    dp.emit(tmp_path)
    for rel in (dp.LOCALE_ZH_REL, dp.LOCALE_EN_REL):
        data = json.loads((tmp_path / rel).read_text(encoding="utf-8"))
        assert data["meta"]["title"], rel
        assert data["meta"]["description"], rel
        for seat in dp.SEAT_KEYS:
            assert data["seats"][seat]["title"], (rel, seat)
            assert data["seats"][seat]["description"], (rel, seat)


def test_locale_check_bites_on_empty_object() -> None:
    """④ 反例：locale 写成空对象 ⇒ check 必须红（不合法的显示链路要被咬住）。"""
    problems = dp.check(locale_zh="{}", locale_en="{}")
    assert any("locale" in p for p in problems), problems


def test_patch_layer_is_a_top_level_yaml_array(tmp_path: Path) -> None:
    """⑤ 补丁层是顶层 YAML 数组（cordis.patch.yml 头部原话：写成 mapping 启动时直接抛错）。

    用 PyYAML 真解析（本机 6.0.3 可用）；tomllib 不认 YAML，所以这里必须另用解析器。
    """
    dp.emit(tmp_path)
    import yaml  # noqa: PLC0415  —— 判据里就地 import（环境无 PyYAML 时本卡退文本断言）

    text = (tmp_path / dp.PATCH_REL).read_text(encoding="utf-8")
    first = next(
        ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")
    )
    assert first.startswith("- "), first
    loaded = yaml.safe_load(text)
    assert isinstance(loaded, list) and loaded, loaded


def test_patch_array_check_bites_on_mapping() -> None:
    """⑤ 反例：把补丁层改成 mapping ⇒ check 必须红（且 PyYAML 会解成 dict，不是 list）。"""
    mapping = dp.PATCH_YAML.replace("- insert:", "insert:")
    assert mapping != dp.PATCH_YAML
    problems = dp.check(patch=mapping)
    assert any("数组" in p for p in problems), problems
    import yaml  # noqa: PLC0415

    assert isinstance(yaml.safe_load(mapping), dict)


def test_patch_three_place_id_name_consistency(tmp_path: Path) -> None:
    """补丁层三纪律之一：patch 行 id/name = 清单 name = 宿主半导出的 name，三处完全一致。"""
    dp.emit(tmp_path)
    patch = (tmp_path / dp.PATCH_REL).read_text(encoding="utf-8")
    assert f"- id: {dp.PACKAGE_NAME}" in patch
    assert f'name: "{dp.PACKAGE_NAME}"' in patch
    assert dp.package_manifest()["name"] == dp.PACKAGE_NAME
    host = (tmp_path / dp.HOST_REL).read_text(encoding="utf-8")
    assert f'export const name = "{dp.PACKAGE_NAME}";' in host


def test_patch_consistency_check_bites_when_name_drifts() -> None:
    """反例：补丁行 name 与清单 name 错位 ⇒ check 必须红（三处一致被打破）。"""
    drifted = dp.PATCH_YAML.replace(f'name: "{dp.PACKAGE_NAME}"', 'name: "some-other-pkg"')
    assert drifted != dp.PATCH_YAML
    problems = dp.check(patch=drifted)
    assert any("三处" in p or "一致" in p for p in problems), problems


def test_patch_emergency_disable_note_is_written_for_humans(tmp_path: Path) -> None:
    """补丁层三纪律之三：「删掉补丁层 = 插件不加载」必须在文档与补丁层注释里出现
    （紧急禁用手段要写给人看）。"""
    dp.emit(tmp_path)
    patch = (tmp_path / dp.PATCH_REL).read_text(encoding="utf-8")
    assert "删掉补丁层 = 插件不加载" in patch
    assert "删掉补丁层 = 插件不加载" in dp.INSTALL_DOC


def test_emergency_note_check_bites_when_missing_from_doc() -> None:
    """反例：文档里没这句 ⇒ check 必须红。"""
    problems = dp.check(doc=dp.INSTALL_DOC.replace("删掉补丁层 = 插件不加载", "（已删）"))
    assert any("插件不加载" in p for p in problems), problems


# ------------------------------------------------ 卡 251：颜色一律走主题令牌


def test_no_hardcoded_colors_in_emitted_artifacts(tmp_path: Path) -> None:
    """卡 251：全份生成物零硬编码颜色（`#rrggbb` / `rgb(` / `hsl(`）。

    为什么：深色主题下甘特条的 `#f0f0f0` 底 + `#7aa7ff` 条会变成一条刺眼白底蓝条。
    """
    dp.emit(tmp_path)
    for rel in (dp.CLIENT_REL, "lib/index.js", "icon.svg"):
        text = (tmp_path / rel).read_text(encoding="utf-8")
        hits = dp.COLOR_LITERAL_RE.findall(text)
        assert not hits, f"{rel} 里还有硬编码颜色：{sorted(set(hits))[:6]}"


def test_gantt_uses_theme_tokens() -> None:
    """卡 251：甘特条的底与填充必须是 `var(--dsw-alias-…)`（删掉 ⇒ 红）。"""
    assert "var(--dsw-alias-bg-base" in dp.CLIENT_JS
    assert "var(--dsw-alias-state-business-primary" in dp.CLIENT_JS


def test_hardcoded_color_counterexample_bites() -> None:
    """卡 251 反例：塞回一个硬编码颜色 ⇒ `check` 必须点名（不是静默通过）。"""
    nl = chr(10)
    broken = dp.CLIENT_JS + nl + 'const evil = "#f0f0f0";' + nl
    problems = dp.check(client_js=broken)
    assert any("硬编码颜色" in p for p in problems), problems


# ================================================================== 卡 253 · T-G374
# 一键启动（三条白名单动作）+ 如实反馈（探端口）+ 一起起/分别停 + 点开才读。
# ★ 每条先红后绿；既有「不派工人 / 不写仓库」判据一条不删，只精确化（允许起停服务）。


# ------------------------------------------------------------ a. 三个目标各一条启动动作


def test_three_targets_have_one_whitelisted_start_action() -> None:
    """★ 判据 a：三个目标各一条启动动作，且只许是 stack.py 组件表里的那几件。"""
    assert tuple(t.start for t in dp.TARGETS) == ("board", "zentao", "timeflow")
    assert tuple(dp.stack.COMPONENTS) == dp.SERVICE_WHITELIST
    for target in dp.TARGETS:
        assert target.start in dp.SERVICE_WHITELIST, (target.seat, target.start)


@pytest.mark.parametrize("evil", ["rm -rf", "board; rm -rf", "python evil.py", "wb_dispatch"])
def test_unknown_command_is_rejected_and_named(evil: str) -> None:
    """★ 判据 a 反例：塞一条不在表里的命令 ⇒ 必须被拒并**点名**。"""
    with pytest.raises(ValueError) as caught:
        dp.resolve_action("start", evil)
    message = str(caught.value)
    assert "白名单" in message and evil in message, message


def test_unknown_action_kind_is_rejected() -> None:
    """★ 判据 a 反例：动作种类也不许自由发挥。"""
    with pytest.raises(ValueError) as caught:
        dp.resolve_action("explode", "board")
    assert "explode" in str(caught.value)


def test_action_argv_is_written_down_not_passthrough() -> None:
    """★ 白名单怎么写的：argv 由枚举值**拼死**（没有命令字符串透传口子）。"""
    assert dp.resolve_action("start", "board") == [
        sys.executable, "-X", "utf8", "tools/stack.py", "start", "board",
    ]
    assert dp.resolve_action("stop", "zentao")[-2:] == ["stop", "zentao"]
    assert dp.resolve_action("start-all") == [
        sys.executable, "-X", "utf8", "tools/stack.py", "start",
    ]


def test_target_check_bites_when_start_action_is_outside_the_table() -> None:
    """★ 判据 a 反例：把某条启动动作改成 `rm -rf` ⇒ 自检必须红并点名。"""
    targets = list(dp.TARGETS)
    first = targets[0]
    targets[0] = dp.Target(first.seat, first.url, first.up_hint, "rm -rf")
    problems = dp._check_targets(tuple(targets))
    assert any("白名单" in p and "rm -rf" in p for p in problems), problems


def test_host_action_seam_is_post_only_with_written_whitelist(tmp_path: Path) -> None:
    """★ 宿主半的动作缝：只 POST、只收白名单里的 {kind,name}；没有 shell 透传。"""
    dp.emit(tmp_path)
    host = (tmp_path / dp.HOST_REL).read_text(encoding="utf-8")
    assert "const ACTION_WHITELIST = {" in host
    for name in dp.SERVICE_WHITELIST:
        assert f'"{name}"' in host, name
    assert "start-all" in host
    assert 'req.method !== "POST"' in host
    for bad in ("shell: true", "shell:true", "execSync"):
        assert bad not in host, bad


def test_action_seam_check_bites_when_post_guard_removed() -> None:
    """★ 反例：拿掉动作缝的 POST 守卫 ⇒ check 必须红。"""
    broken = dp.HOST_JS.replace('req.method !== "POST"', 'req.method === "n/a"')
    assert broken != dp.HOST_JS
    problems = dp.check(host_js=broken)
    assert any("POST" in p for p in problems), problems


def test_action_seam_check_bites_on_shell_passthrough() -> None:
    """★ 反例：塞 `shell: true` ⇒ check 必须红（不许把命令交给 shell）。"""
    problems = dp.check(host_js=dp.HOST_JS + "\nconst evil = { shell: true };\n")
    assert any("shell" in p for p in problems), problems


# ------------------------------------------------------------ b. 启动后的判定必须探端口


def test_client_says_started_only_after_status_says_running(tmp_path: Path) -> None:
    """★ 判据 b：面板只有 `row.running` 为真才改口「已起（端口 …；映像 …）」。

    反例（必须红）：把启动判定短路成"点了就算" ⇒ 源码里不再有 row.running 这个门。
    """
    dp.emit(tmp_path)
    client = (tmp_path / dp.CLIENT_REL).read_text(encoding="utf-8")
    assert "已发起启动" in client
    assert "已起（" in client
    assert '(kind === "start-all" || (row && row.running))' in client, (
        "「已起」必须由现读的 running 决定，不是点击本身"
    )
    assert "还没起来" in client and "stack-actions.log" in client


def test_client_start_feedback_check_bites_when_running_gate_removed() -> None:
    """★ 判据 b 反例：拆掉 running 门（改成一按就报已起）⇒ check 必须红。"""
    broken = dp.CLIENT_JS.replace("(row && row.running)", "(row || true)")
    assert broken != dp.CLIENT_JS
    problems = dp.check(client_js=broken)
    assert any("row.running" in p or "已起" in p for p in problems), problems


# ------------------------------------------------------------ c. 护栏两面分别可验


def test_service_control_allowed_but_dispatch_and_repo_write_still_forbidden() -> None:
    """★ 判据 c：允许面（起服务）能走；禁止面（派工人 / 写仓库）仍然被拒。"""
    # 允许面：白名单里的服务能翻成 argv
    assert dp.resolve_action("start", "board")
    assert dp.resolve_action("stop", "trae")
    # 禁止面：派工人 / 写仓库的 token 仍然咬（分别给读数）
    for token in ("wb_dispatch", "writeFileSync"):
        problems = dp.check(host_js=dp.HOST_JS + f"\n// {token}\n")
        assert any("只读" in p and token in p for p in problems), (token, problems)
    assert "wb_dispatch" not in dp.HOST_JS
    assert "wb_dispatch" not in dp.CLIENT_JS


# ------------------------------------------------------------ d. 起停入口 + 日志可见


def test_client_has_start_all_stop_each_and_recent_actions(tmp_path: Path) -> None:
    """★ 判据 d：面板有「全部起」/「停这一件」/ 最近动作日志（一行一条）。"""
    dp.emit(tmp_path)
    client = (tmp_path / dp.CLIENT_REL).read_text(encoding="utf-8")
    for needle in ("全部起", "停这一件", "最近动作", "gates/diag/stack-actions.log"):
        assert needle in client, needle
    assert 'fetch(ACTION_ROUTE + query, { method: "POST" })' in client
    assert 'fetch(STACK_STATUS_ROUTE, { method: "GET" })' in client


# ------------------------------------------------------------ 3.5.1 内存账本 / 3.5.2 点开才读


def test_client_shows_rss_and_budget(tmp_path: Path) -> None:
    """★ 3.5.1：面板显示每件 RSS、合计、常驻预算（超出要显式提示）。"""
    dp.emit(tmp_path)
    client = (tmp_path / dp.CLIENT_REL).read_text(encoding="utf-8")
    assert "RSS" in client and "常驻预算" in client
    assert "over_budget" in client and "超出常驻预算" in client


def test_client_has_no_interval_polling_and_reads_on_open(tmp_path: Path) -> None:
    """★ 3.5.2：源码里不再有常驻定时轮询；点开时仍读一次（useEffect → GET）。"""
    dp.emit(tmp_path)
    client = (tmp_path / dp.CLIENT_REL).read_text(encoding="utf-8")
    assert "setInterval" not in client
    assert "react.useEffect(() => { reload(); }, [reload])" in client
    assert 'fetch(STACK_STATUS_ROUTE, { method: "GET" })' in client


def test_polling_ban_bites_when_a_timer_returns() -> None:
    """★ 3.5.2 反例：塞回一个 setInterval ⇒ check 必须红。"""
    problems = dp.check(client_js=dp.CLIENT_JS + "\nsetInterval(() => {}, 5000);\n")
    assert any("setInterval" in p for p in problems), problems


def test_doc_mentions_oneclick_log_and_budget() -> None:
    """卡 253：安装说明要写一键启动 / 日志 / 常驻预算 / 点开才读。"""
    for needle in ("一键启动", "stack-actions.log", "常驻预算", "点开才读"):
        assert needle in dp.INSTALL_DOC, needle


def test_every_seam_handler_is_dispatched() -> None:
    """卡 A286：处理函数定义了就必须被 serveSeam 调用。

    反代与号池动作曾是这样死的：`serveProxy` / `servePoolAction` 和路由常量都在，
    `serveSeam` 里却没有对应分支 —— 反代落到「未知路由 404」，号池动作被只读门挡成
    405。这条用例直接盯「定义」与「调用」两件事同时存在。
    """
    src = dp._host_js()
    for name in ("serveProxy", "servePoolAction"):
        assert f"function {name}(" in src, f"{name} 没有定义"
        assert f"{name}(req, res, url)" in src, f"{name} 定义了却没被分发"


def test_toolbox_has_workbench_tab_and_row_is_gone() -> None:
    """卡 A286：工作台状态收进工具箱「工作台」页签，不再单挂左栏一行。"""
    client = dp.CLIENT_JS
    assert '["workbench", "工作台"]' in client, "工具箱缺「工作台」页签"
    assert "function ToolboxWorkbench()" in client
    assert "workbench: ToolboxWorkbench" in client
    assert dp.SEAT_BY_KEY["workbench_board"].row is False
    assert "workbench_board" not in dp.ROW_KEYS


def test_params_page_is_writable_with_whitelisted_keys() -> None:
    """卡 A286：参数页可改 —— 白名单键含号池并发度，页面有保存动作。"""
    assert "pool_concurrency" in dp._host_js(), "白名单里没有号池并发度"
    client = dp.CLIENT_JS
    assert "method: \"POST\"" in client, "参数页没有写动作"
    assert "param" not in client.lower() or "PARAMS_ROUTE" in client


def test_settings_handler_receives_url() -> None:
    """卡 A286：`serveSettings` 用 `url.searchParams` 取键值，分发时必须把 url 传进去。

    实测 bug：只传 (req, res) ⇒ POST /dsh-panel/settings 直接
    `Cannot read properties of undefined (reading 'searchParams')`（参数页永远写不进去）。
    """
    host = dp._host_js()
    assert "serveSettings(req, res, url)" in host
    assert "serveSettings(req, res);" not in host


def test_install_doc_lists_the_interface() -> None:
    """卡 A286：接口要写进安装说明（读哪些、写哪三条、白名单键与范围）。"""
    for needle in ("/dsh-panel/pool-action", "/dsh-panel/settings?",
                   "pool_concurrency", "/dsh-panel/proxy/z/zentao"):
        assert needle in dp.INSTALL_DOC, needle


def test_panel_concurrency_reaches_wb_plan(tmp_path: Path) -> None:
    """卡 A286：面板写的号池并发度必须被 wb_plan 读到（否则输入框是摆设）。"""
    import sys

    sys.path.insert(0, str(dp.ROOT / "tools"))
    import wb_plan

    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "settings.toml").write_text("pool_concurrency = 5\n", encoding="utf-8")
    assert wb_plan.settings_concurrency(tmp_path) == 5
    (tmp_path / "tools" / "settings.toml").write_text("pool_concurrency = 99\n", encoding="utf-8")
    assert wb_plan.settings_concurrency(tmp_path) is None, "越界值不许透传"
    (tmp_path / "tools" / "settings.toml").unlink()
    assert wb_plan.settings_concurrency(tmp_path) is None, "没文件就退回默认"


# ================================================================== 卡 A289 · T-AG403
# 首屏秒开：不拿加载占位行挡首帧 —— 客户端 SWR 缓存 + 骨架 + 宿主 stack-status 缓存。
# ★ 每条先红后绿；既有判据一条不删。


def test_client_first_frame_reads_cache_and_marks_stale() -> None:
    """★ A289：浏览器半有 SWR —— localStorage 缓存（键含 route、带时间戳）+「上次读数」。"""
    client = dp.CLIENT_JS
    assert "localStorage" in client
    assert "readCache(" in client and "writeCache(" in client
    assert "cacheKey(" in client
    assert "上次读数 " in client


def test_client_never_walls_first_frame_with_loading_text() -> None:
    """★ A289：加载占位字面不许再独占首屏 —— 整份浏览器半零命中；骨架要有。"""
    assert "读数中…" not in dp.CLIENT_JS
    assert '"data-wb-state": "loading"' in dp.CLIENT_JS
    assert "data-wb-skeleton" in dp.CLIENT_JS


def test_client_keeps_stale_reading_on_failure() -> None:
    """★ A289：断服务保留上次读数 + 红点 + 原话（error setState 保留 prev.data/prev.at）。"""
    client = dp.CLIENT_JS
    assert "prev.data" in client and "prev.at" in client
    assert "T.bad" in client  # 红点走主题令牌，不引颜色字面量（卡 251 仍咬）


def test_client_swr_check_bites_when_cache_removed() -> None:
    """★ A289 反例：切掉缓存读 ⇒ check 必须红。"""
    broken = dp.CLIENT_JS.replace("readCache(", "readGone(")
    assert broken != dp.CLIENT_JS
    problems = dp.check(client_js=broken)
    assert any("A289" in p for p in problems), problems


def test_client_loading_wall_check_bites_when_text_returns() -> None:
    """★ A289 反例：塞回加载占位字面 ⇒ check 必须红。"""
    broken = dp.CLIENT_JS + '\nconst evil = "读数中…";\n'
    problems = dp.check(client_js=broken)
    assert any("读数中…" in p for p in problems), problems


def test_host_stack_status_cache_with_ttl_budget_and_flag() -> None:
    """★ A289：宿主半 stack-status 有进程内缓存：TTL 5s + 命中 cached:true + 单次 1.5s 预算。"""
    host = dp._host_js()
    assert "STACK_STATUS_TTL_MS" in host
    assert "STACK_STATUS_BUDGET_MS" in host
    assert "cached: true" in host
    assert "serveStackStatus(res)" in host  # 路由真走到缓存版 handler


def test_host_stack_status_cache_invalidated_after_actions() -> None:
    """★ A289：起停动作之后缓存就地作废（动作缝里 stackStatusCache = null）。"""
    assert "stackStatusCache = null" in dp._host_js()


def test_host_stack_status_cache_check_bites_when_cache_removed() -> None:
    """★ A289 反例：拿掉 TTL 缓存 ⇒ check 必须红。"""
    broken = dp.HOST_JS.replace("STACK_STATUS_TTL_MS", "STACK_STATUS_GONE")
    assert broken != dp.HOST_JS
    problems = dp.check(host_js=broken)
    assert any("A289" in p or "缓存" in p for p in problems), problems


def test_client_exports_a289_test_hooks() -> None:
    """★ A289：判据钩子导出（Node 判据/计时用；DSH 只消费 apply/inject）。"""
    assert "exports.__a289" in dp.CLIENT_JS
    for name in ("SourceShell", "useSource", "readCache", "writeCache"):
        assert name in dp.CLIENT_JS


# ================================================================== 卡 A297 · T-AG411
# 收工回推通道：宿主半加只读路由 /dsh-panel/notifications；总览页顶部显示状态条。
# ★ 每条先红后绿；既有判据一条不删。


def test_notifications_route_constant() -> None:
    """★ A297：宿主半有 NOTIFICATIONS_ROUTE 常量 = /dsh-panel/notifications。"""
    assert dp.NOTIFICATIONS_ROUTE == "/dsh-panel/notifications"
    assert dp.NOTIFICATIONS_ROUTE in dp.HOST_JS


def test_host_serves_notifications_and_dispatches() -> None:
    """★ A297：serveNotifications 既定义又分发（卡 A286 同型坑：定义了不分发 = 死代码）。"""
    src = dp._host_js()
    assert "function serveNotifications(" in src, "serveNotifications 没定义"
    assert "serveNotifications(req, res)" in src, "serveNotifications 没被 serveSeam 分发"


def test_host_reads_done_cards_to_filter_notifications() -> None:
    """★ A297：宿主半读 backlog 排掉已落地卡（readDoneCards；不引 TOML 解析器）。"""
    src = dp._host_js()
    assert "function readDoneCards()" in src
    assert "status" in src and "done" in src  # 简单逐行扫，认 status = "done"


def test_host_scans_verdicts_live_not_only_jsonl() -> None:
    """★ A298：可见性不许只靠守护进程 —— 宿主半要能直接扫 verdict 文件。

    背景：`notifications.jsonl` 由 `wb_notify.py --daemon` 追加；关机重启后守护不在，
    只读 JSONL 就会漏掉「已收工未收口」的卡。所以路由必须每次请求现扫
    `gates/diag/wb-*.verdict.txt`，再与 JSONL 合并去重。
    """
    src = dp._host_js()
    assert "function scanVerdicts()" in src, "缺 scanVerdicts（实时扫 verdict）"
    assert "scanVerdicts().concat(" in src, "没把实时扫描并进通知列表"
    # 扫描只看文件名与判决行，不写盘（宿主半只读判据见 _check_read_only）。
    assert "verdict.txt" in src


def test_check_bites_when_live_scan_is_removed() -> None:
    """★ A298：把 scanVerdicts 删掉，自检必须报红（钉子会咬）。"""
    problems = dp._check_host(dp._host_js().replace("function scanVerdicts()", "function nope()"))
    assert any("scanVerdicts" in p for p in problems), problems


def test_host_notifications_route_is_get_only() -> None:
    """★ A297：/dsh-panel/notifications 只 GET —— serveNotifications 自带方法守卫，
    且分发在 serveSeam 的 GET 闸门之后（双保险）。"""
    src = dp._host_js()
    # serveNotifications 自带 `req.method !== "GET"` ⇒ 非 GET 一律 405。
    ns = src.find("function serveNotifications(")
    assert ns > 0
    guard_in_handler = src.find('req.method !== "GET"', ns)
    end_of_handler = src.find("\n}", ns)
    assert 0 < guard_in_handler < end_of_handler, "serveNotifications 自带 GET 守卫"
    # 分发也在 serveSeam 的 GET 闸门之后（serveSeam 里那道 GET 闸门）。
    seam_guard = src.rfind('req.method !== "GET"', 0, src.find("function apply("))
    dispatch = src.rfind("serveNotifications(req, res)", 0, src.find("function apply("))
    assert seam_guard > 0 and dispatch > 0
    assert dispatch > seam_guard, "notifications 分发必须在 serveSeam 的 GET 闸门之后"


def test_client_fetches_notifications_route() -> None:
    """★ A297：客户端读 /dsh-panel/notifications（NotificationsBanner 用 useSource）。"""
    assert "/dsh-panel/notifications" in dp.CLIENT_JS
    assert "NotificationsBanner" in dp.CLIENT_JS
    assert "useSource" in dp.CLIENT_JS


def test_client_shows_unread_count_and_recent_card() -> None:
    """★ A297：状态条文案「已收工未收口 N（最近：A289 20:14）」齐全。"""
    for needle in ("已收工未收口", "最近：", "data-wb-notifications"):
        assert needle in dp.CLIENT_JS, needle


def test_client_zero_unread_hides_banner() -> None:
    """★ A297：零未读 ⇒ 不显示状态条（return null）。"""
    # 函数体里要有 unread === 0 的早退分支。
    assert "if (unread === 0) return null" in dp.CLIENT_JS


# ---- ★ 反例（先红后绿）----


def test_host_check_bites_when_dispatch_removed() -> None:
    """★ A297 反例：serveNotifications 定义了但 serveSeam 里不调 ⇒ check 必须红（A286 同型坑）。"""
    broken = dp.HOST_JS.replace("serveNotifications(req, res)", "serveNotificationsGone(req, res)")
    assert broken != dp.HOST_JS
    problems = dp.check(host_js=broken)
    assert any("serveNotifications" in p for p in problems), problems


def test_host_check_bites_when_handler_undefined() -> None:
    """★ A297 反例：连 serveNotifications 函数都没了 ⇒ check 必须红。"""
    broken = dp.HOST_JS.replace("function serveNotifications(", "function serveNotificationsGone(")
    assert broken != dp.HOST_JS
    problems = dp.check(host_js=broken)
    assert any("serveNotifications" in p for p in problems), problems


def test_host_check_bites_when_read_done_cards_removed() -> None:
    """★ A297 反例：拿掉 readDoneCards ⇒ check 必须红（已落地卡会冒充未读）。"""
    broken = dp.HOST_JS.replace("function readDoneCards()", "function readDoneCardsGone()")
    assert broken != dp.HOST_JS
    problems = dp.check(host_js=broken)
    assert any("readDoneCards" in p for p in problems), problems


def test_client_check_bites_when_banner_removed() -> None:
    """★ A297 反例：删掉 NotificationsBanner 组件名 ⇒ check 必须红。"""
    broken = dp.CLIENT_JS.replace(
        "function NotificationsBanner()", "function NotificationsBannerGone()"
    )
    assert broken != dp.CLIENT_JS
    problems = dp.check(client_js=broken)
    assert any("NotificationsBanner" in p for p in problems), problems


def test_client_check_bites_when_unread_text_removed() -> None:
    """★ A297 反例：切掉「已收工未收口」文案 ⇒ check 必须红。"""
    broken = dp.CLIENT_JS.replace("已收工未收口", "（无未读）")
    assert broken != dp.CLIENT_JS
    problems = dp.check(client_js=broken)
    assert any("已收工未收口" in p for p in problems), problems


# ================================================================== 卡 A290 · T-AG404
# 内嵌页壳：服务停了也不出白框（工具条先画 / 8 s 超时重试 / down 空态 / 右栏退回内嵌）。
# ★ 每条先红后绿；既有判据一条不删。


def _quick_entry_body() -> str:
    """切出 QuickEntry 那一段（到工具箱注释为止），免得拿整份源码当判据。"""
    client = dp.CLIENT_JS
    start = client.index("function QuickEntry(props)")
    return client[start:client.index("/* ---- 卡 A274", start)]


def test_embed_shell_draws_toolbar_before_iframe() -> None:
    """★ A290 ①：工具条（标题 + 状态点 + 一键启动 / 刷新 / 右栏）先画，iframe 在后。"""
    body = _quick_entry_body()
    assert 'h("h2", { style: UI.title }, frameTitle)' in body, "工具条要先有标题"
    assert '"data-wb-probe": shown' in body, "状态点要以 stack-status 为准（probe 只探一次）"
    for label in ('"一键启动"', '"右栏"', '"刷新"'):
        assert label in body, label
    assert body.index("UI.bar") < body.index('h("iframe"'), "工具条必须先于 iframe 画出来"


def test_embed_shell_8s_timeout_and_retry() -> None:
    """★ A290 ①：iframe 区先给骨架；8 s 没 load ⇒「还在加载…」+ 可点「重试」。"""
    client = dp.CLIENT_JS
    assert "const EMBED_LOAD_TIMEOUT_MS = 8000;" in client
    assert 'onLoad: () => setFrameState("loaded")' in client
    assert "setTimeout(" in client and "clearTimeout(" in client
    assert "setFrameState((prev) => embedAfterTimeout(prev))" in client
    assert "setInterval" not in client, "8 s 只能挂一次性定时器，不许退回常驻轮询"
    assert "还在加载…" in client
    assert '"重试"' in client
    assert "data-wb-frame-overlay" in client
    assert "data-wb-skeleton" in client


def test_embed_shell_exports_three_state_hooks() -> None:
    """★ A290：三态判定导出成钩子（证据脚本喂读数即可复现，不靠浏览器）。"""
    client = dp.CLIENT_JS
    assert "exports.__a290" in client
    for name in ("embedShellState", "embedAfterTimeout", "EMBED_LOAD_TIMEOUT_MS"):
        assert name in client, name
    assert "function embedShellState(board, probe, target, frameState)" in client
    assert "embedShellState(board, probe, target, frameState)" in client


def test_embed_shell_check_bites_when_three_state_logic_is_inlined() -> None:
    """★ A290 反例：把三态判定从 QuickEntry 里拿掉（各抄一份）⇒ check 必须红。"""
    broken = dp.CLIENT_JS.replace(
        "const shell = embedShellState(board, probe, target, frameState);",
        "const shell = { down: false, overlay: \"none\" };",
    )
    assert broken != dp.CLIENT_JS
    problems = dp.check(client_js=broken)
    assert any("embedShellState" in p for p in problems), problems


def test_embed_down_gate_skips_iframe_and_shows_reason() -> None:
    """★ A290 ②：down（stack-status 里不是 running）⇒ 不加载 iframe，画空态 + 原因。"""
    client = dp.CLIENT_JS
    gate = client[client.index("function embedShellState("):]
    gate = gate[:gate.index("function embedAfterTimeout(")]
    assert "row.running !== true" in gate, "down 的真源必须是 stack-status 的现读"
    body = _quick_entry_body()
    assert "不是 running" in body and "data-wb-reason" in body, "空态要写一句原因"
    assert "data-wb-embed-empty" in body
    assert re.search(
        r'down\s*\?\s*h\("div", \{ "data-wb-embed-empty"', body
    ), "空态必须是 down 分支画出来的"
    assert body.count('h("iframe"') == 1, "QuickEntry 里只许有一个 iframe"
    assert body.index("data-wb-embed-empty") < body.index('h("iframe"'), (
        "iframe 只能出现在非 down 分支（down 时连加载都不许）"
    )


def test_right_sidebar_unavailable_falls_back_embedded() -> None:
    """★ A290 ③：右栏不可用 ⇒ 自动退回内嵌（留在本页），工具条标「已退回内嵌」。"""
    client = dp.CLIENT_JS
    assert "已退回内嵌" in client
    assert '"data-wb-fallback": "embedded"' in client
    start = client.index("function openInSidebar()")
    body = client[start:client.index("function reloadFrame()", start)]
    assert "setFellBack(true)" in body
    assert "setMode(" not in body, "退回内嵌 = 留在本页 iframe，不是跳去「读数」视图"
    # openRealPage 要如实回报成败（否则「不可用」无从判断）
    open_start = client.index("function openRealPage(target, setOpenError)")
    open_body = client[open_start:client.index("function useServiceControl()", open_start)]
    assert "return true;" in open_body and "return false;" in open_body


def test_embed_shell_keeps_zero_color_literals() -> None:
    """★ A290 判据：零颜色字面量（一律主题令牌 / currentColor）。"""
    assert not dp.COLOR_LITERAL_RE.search(dp.CLIENT_JS)


def test_client_check_bites_when_embed_timeout_removed() -> None:
    """★ A290 反例：拿掉 8 s 超时常量 ⇒ check 必须红。"""
    broken = dp.CLIENT_JS.replace("EMBED_LOAD_TIMEOUT_MS = 8000", "EMBED_LOAD_TIMEOUT_MS = 0")
    assert broken != dp.CLIENT_JS
    problems = dp.check(client_js=broken)
    assert any("A290" in p for p in problems), problems


def test_client_check_bites_when_retry_copy_removed() -> None:
    """★ A290 反例：切掉「还在加载…」⇒ check 必须红（超时就不再有话可说）。"""
    broken = dp.CLIENT_JS.replace("还在加载…", "加载失败")
    assert broken != dp.CLIENT_JS
    problems = dp.check(client_js=broken)
    assert any("还在加载" in p for p in problems), problems


def test_client_check_bites_when_down_gate_removed() -> None:
    """★ A290 反例：down 不看 stack-status ⇒ check 必须红（会退回「凭按钮猜」）。"""
    broken = dp.CLIENT_JS.replace("row.running !== true", "false")
    assert broken != dp.CLIENT_JS
    problems = dp.check(client_js=broken)
    assert any("row.running" in p for p in problems), problems


def test_client_check_bites_when_embed_empty_state_removed() -> None:
    """★ A290 反例：删掉空态标记 ⇒ check 必须红（down 就只剩白框）。"""
    broken = dp.CLIENT_JS.replace('"data-wb-embed-empty": ""', '"data-wb-embed-gone": ""')
    assert broken != dp.CLIENT_JS
    problems = dp.check(client_js=broken)
    assert any("data-wb-embed-empty" in p for p in problems), problems


def test_client_check_bites_when_fallback_label_removed() -> None:
    """★ A290 反例：右栏退回内嵌却不标明 ⇒ check 必须红。"""
    broken = dp.CLIENT_JS.replace("已退回内嵌", "（右栏不可用）")
    assert broken != dp.CLIENT_JS
    problems = dp.check(client_js=broken)
    assert any("已退回内嵌" in p for p in problems), problems

