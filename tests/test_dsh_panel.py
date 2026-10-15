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
    """`emit` 把六块都落到目标目录，`package.json` 能当 JSON 解析。"""
    written = dp.emit(tmp_path)
    rels = {p.relative_to(tmp_path).as_posix() for p in written}
    assert rels == {
        dp.MANIFEST_REL,
        dp.HOST_REL,
        dp.CLIENT_REL,
        dp.README_REL,
        dp.PATCH_REL,
        dp.ICON_REL,
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
    assert '"sidebar.panellist"' in client and "id: PANEL_ID" in client
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
    assert mains == rows, (mains, rows)
    assert mains == list(dp.SEAT_KEYS), mains
    assert len(mains) == 3


def test_seat_consistency_check_bites_when_row_id_drifts() -> None:
    """★ 反例：行 id 与 main key 错位 ⇒ `check` 必须红（用户点行就打不开面板）。"""
    broken = dp.CLIENT_JS.replace('id: PANEL_ID', 'id: "workbench_board_x"')
    assert broken != dp.CLIENT_JS
    problems = dp.check(client_js=broken)
    assert any("座位" in p for p in problems), problems


# ------------------------------------------------------------ 10. ★ 只读缝三条路由只 GET


def test_seam_routes_are_get_only(tmp_path: Path) -> None:
    """★ 三条只读缝路由：只 GET、写方法一个不许出现、三条路径都在宿主半。"""
    dp.emit(tmp_path)
    host = (tmp_path / dp.HOST_REL).read_text(encoding="utf-8")
    assert 'req.method !== "GET"' in host
    for verb in ("POST", "PUT", "DELETE", "PATCH"):
        assert f'"{verb}"' not in host, verb
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
    for seat in dp.SEAT_KEYS:
        assert f"workbench-panel-tab-{seat}" in client


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

