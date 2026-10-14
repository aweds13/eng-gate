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
    """`emit` 把四块都落到目标目录，`package.json` 能当 JSON 解析。"""
    written = dp.emit(tmp_path)
    rels = {p.relative_to(tmp_path).as_posix() for p in written}
    assert rels == {dp.MANIFEST_REL, dp.HOST_REL, dp.CLIENT_REL, dp.README_REL}
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
