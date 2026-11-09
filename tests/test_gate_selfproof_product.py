"""product 档 11 道门「真的会咬」的自证 —— 表钉 + 逐门造错双钉子。

## 这个文件管什么

姊妹文件 `tests/test_gate_selfproof.py` 钉的是**全量门**的主台账
（`gates/gate-selfproof.toml`，`schema = 1`，四字段
`name` / `reverse_case` / `why_no_case` / `since`，
它的 `reverse_case` 指向一条已有用例的 nodeid）。

本文件钉的是 product 档专用的**自证表** `gates/gate-selfproof-product.toml`。它比主台账多记三列：

| 列 | 记什么 | 为什么非有不可 |
|---|---|---|
| `probe` | 可复现的造错命令 / 脚本片段 | 主台账只有「哪条用例在钉」，换个环境没法照着重放 |
| `evidence` | 一条**真实读数**（退出码或失败断言原文） | 「会跑」和「会咬」的差别就在这条读数里 |
| `residue` | 这道门还剩什么没被盖住 | 不写盲区 = 假装 100%，那是自己骗自己 |

## 「会咬」的判据（两道，缺一不算）

1. **造错时必须退非零** —— 只证明「会跑」是不够的；
2. **必须点名造的那个错** —— 报出具体是哪条、哪个值，而不是笼统一句「失败」。

只有 ① 的是「会跑」；只有 ② 而没有 ① 的是「会说话但不拦」。

## 这里的 11 条反向用例都是**真的跑**

不是拿判据函数走个过场：能起子进程的一律起子进程跑门的 CLI（`contrast` / `proxy` / `commands` /
`web_live` / `ui_dom_probe` / `render` / `ui_flow`），纯函数判据（`style` / `ui_text`）
直接喂合成数据，`lf1_live` 真起 uvicorn 把 LF-1 主链走一遍。

每条红都配一条**绿基线**，并且变异那一侧都断言「变异真的生效了」——
否则红可能只是树搭错了（这是 `tests/test_dark_teeth.py` 的教训，照抄）。

★ 诚实边界：`render` / `ui_flow` 的**真浏览器采集层**不在这里跑（要真 Edge + ~12s/门 + 抢端口）。
那一层的反向是用 `gates/diag/_probe_product_heavy.py` 手工实测的（`❌ 渲染与黄金不一致：3 份不同`、
`❌ 行为流有失败：1/1 条`），读数是自证表 `render` / `ui_flow` 两行的 `evidence`；
本文件只钉它们**不依赖浏览器**的那几段判据（CLI 硬拒 + 人工验收清单对账）。
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import tomllib

if TYPE_CHECKING:
    from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
NODE = shutil.which("node")
TABLE = ROOT / "gates" / "gate-selfproof-product.toml"
MAIN_LEDGER = ROOT / "gates" / "gate-selfproof.toml"
VERIFIED_AT = "2026-10-27"

for _extra in ("scripts", "src", "tools"):
    _p = str(ROOT / _extra)
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _load(name: str, path: Path) -> ModuleType:
    """按路径加载一个模块 —— 必须先登记 `sys.modules`，否则里面的 dataclass 会炸。"""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rg = _load("run_gates_under_test_for_product", ROOT / "scripts" / "run_gates.py")
PRODUCT_DOORS: tuple[str, ...] = tuple(rg.GATE_PROFILES["product"])
ALL_DOORS: tuple[str, ...] = tuple(
    door for profile in ("lang", "audit", "product") for door in rg.GATE_PROFILES[profile]
)


# ---------------------------------------------------------------- 小工具


def _run(
    argv: list[str],
    cwd: Path = ROOT,
    timeout: int = 300,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env if env is not None else dict(os.environ),
    )


def _out(proc: subprocess.CompletedProcess[str]) -> str:
    return (proc.stdout or "") + (proc.stderr or "")


def _rows() -> list[dict[str, object]]:
    data = tomllib.loads(TABLE.read_text(encoding="utf-8"))
    rows = data["gate"]
    assert isinstance(rows, list)
    return rows


def _write(path: Path, text: str) -> Path:
    """按字节写 —— 不让 Windows 把 `\\n` 翻成 `\\r\\n`（仓内多文件是 CRLF，别被动改）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


# ---------------------------------------------------------------- 一、表本身


def test_the_table_covers_exactly_the_product_doors() -> None:
    """product 档 11 道，不多不少 —— 且顺序与 `GATE_PROFILES` 一致（门表是唯一真源）。"""
    doors = [str(row["door"]) for row in _rows()]
    assert len(doors) == len(set(doors)), f"自证表里有重复的门：{doors}"
    assert set(doors) == set(PRODUCT_DOORS), (
        f"自证表与 GATE_PROFILES['product'] 对不上；"
        f"多了 {sorted(set(doors) - set(PRODUCT_DOORS))}，"
        f"少了 {sorted(set(PRODUCT_DOORS) - set(doors))}"
    )
    assert doors == list(PRODUCT_DOORS), "顺序也对齐，好让人两列并排读"


def test_the_table_really_covers_all_doors_once_merged_with_the_main_ledger() -> None:
    """两份表合起来必须正好是全量门 —— 否则「每一道门都自证过」这句话是假的。"""
    if not MAIN_LEDGER.is_file():
        pytest.skip(f"主台账 {MAIN_LEDGER.name} 不在，全量门全集的联合判据无从谈起")
    main = tomllib.loads(MAIN_LEDGER.read_text(encoding="utf-8"))["gate"]
    covered = {str(row["name"]) for row in main} | {str(row["door"]) for row in _rows()}
    assert covered == set(ALL_DOORS), (
        f"两份表合起来并没有覆盖全量门；"
        f"多了 {sorted(covered - set(ALL_DOORS))}，少了 {sorted(set(ALL_DOORS) - covered)}"
    )
    # ★ 这个数字**故意**写着：门表变了就得有人来看一眼（卡 E104 加第 23 道时就是这次「看一眼」）。
    #   改它之前先问：新门有没有自证台账行？没行的门等于没门。
    assert len(ALL_DOORS) == 23, f"门表本身变了：现在是 {len(ALL_DOORS)} 道（lang+audit+product）"


def test_every_row_carries_a_real_reading_not_a_promise() -> None:
    """`evidence` 非空，并且得是**读数**（带数字），不能是「已验证」三个字。"""
    problems: list[str] = []
    for row in _rows():
        door = str(row["door"])
        evidence = str(row["evidence"])
        if not evidence.strip():
            problems.append(f"{door}: evidence 是空的")
            continue
        if not any(ch.isdigit() for ch in evidence):
            problems.append(f"{door}: evidence 里一个数字都没有 —— 那不是读数，是结论")
        if len(evidence) < 60:
            problems.append(f"{door}: evidence 只有 {len(evidence)} 字，太短，复现不了")
        for field in ("kind", "probe", "expect", "residue"):
            if not str(row.get(field, "")).strip():
                problems.append(f"{door}: {field} 是空的")
        if str(row.get("verified_at", "")) != VERIFIED_AT:
            problems.append(f"{door}: verified_at={row.get('verified_at')!r} 不是 {VERIFIED_AT}")
    assert not problems, "自证表有洞：\n  " + "\n  ".join(problems)


def test_the_summary_numbers_match_the_rows() -> None:
    """汇总段不许跟正文对不上 —— 那是最容易被手抄坏的数。"""
    data = tomllib.loads(TABLE.read_text(encoding="utf-8"))
    summary = data["summary"]
    rows = _rows()
    assert summary["total"] == len(rows) == len(PRODUCT_DOORS)
    assert summary["tier_a"] + summary["tier_b"] + summary["tier_c"] == summary["total"]
    assert summary["can_self_prove"] + summary["manual_only"] == summary["total"]


# ---------------------------------------------------------------- 二、逐门造错（真的跑）


def test_check_layers_bites_on_a_missing_domain_spec() -> None:
    """删掉一个域规格 → `check_layers` 必须退 1 并点名缺的是哪一个。"""
    import test_check_layers as tcl

    files = tcl.skeleton_files()
    green_code, green_out = tcl.run_on_synthetic(files)
    assert green_code == 0, f"合成小树自己就不干净，后面的红说明不了事：{green_out[-800:]}"

    victim = "docs/specification/domains/F5-合成.md"
    assert victim in files, "变异锚点不见了"
    del files[victim]
    red_code, red_out = tcl.run_on_synthetic(files)
    assert red_code == 1, f"删了域规格还退 {red_code}：{red_out[-800:]}"
    assert "缺详细规格" in red_out and "F5-" in red_out, f"退非零但没点名：{red_out[-800:]}"


def test_contrast_bites_on_a_darkened_ink(tmp_path: Path) -> None:
    """把正文墨色改成接近底色 → 对比度门必须退 1，并逐行点名欠账的那几组。"""
    css = (ROOT / "src" / "web" / "app.css").read_bytes().decode("utf-8")
    green = _run([PY, "-X", "utf8", "tools/contrast_audit.py", "--strict"])
    assert green.returncode == 0, f"真 CSS 先就没过：{_out(green)[-800:]}"

    needle = "\n  --ink: #1e293b;"
    assert css.count(needle) == 1, "变异锚点不见了（`--ink` 的声明）"
    bad = css.replace(needle, "\n  --ink: #f8fafc;")
    assert bad != css, "变异没生效"
    bad_path = _write(tmp_path / "bad.css", bad)

    red = _run([PY, "-X", "utf8", "tools/contrast_audit.py", "--strict", "--css", str(bad_path)])
    text = _out(red)
    assert red.returncode == 1, f"改坏了还退 {red.returncode}：{text[-800:]}"
    assert "新欠账" in text, f"退非零但没点名欠账：{text[-800:]}"
    assert "--ink" in text, f"没点名是哪一组：{text[-800:]}"


def test_style_bites_on_an_orphan_literal() -> None:
    """追加一条只出现一次的字面量 → 风格门必须把它判成 NEW（纯函数，不起子进程）。"""
    import style_audit as sa

    css = (ROOT / "src" / "web" / "app.css").read_bytes().decode("utf-8")
    green_findings = sa.collect(css)
    sa.evaluate(green_findings, sa.load_baseline())
    assert [f.key for f in green_findings if f.verdict == "NEW"] == [], "真 CSS 先就有新问题"

    bad = css + "\n.probe-orphan { gap: 2px }\n"
    assert bad != css, "变异没生效"
    findings = sa.collect(bad)
    assert findings != green_findings, "变异没被解析到"
    sa.evaluate(findings, sa.load_baseline())
    new = {f.key: f.detail for f in findings if f.verdict == "NEW"}
    assert "literal:gap:2px" in new, f"孤儿字面量没被判 NEW：{sorted(new)}"
    assert "只出现" in new["literal:gap:2px"], f"判了但没说清为什么：{new['literal:gap:2px']}"


def test_ui_text_bites_on_an_over_long_line() -> None:
    """往界面片段里塞一条 35 字的长句 → 文案门的两档（硬门 + 棘轮）必须同时红。"""
    import ui_text_audit as uta

    known, limit = uta.load()
    frags = uta.scan.fragments()
    fails, _notes, n_over, n_hard = uta.verdicts(frags, known, limit)
    assert fails == [] and n_hard == 0, f"真界面先就红了：{fails}"
    assert n_over == limit, f"真界面 ≥20 字的条数 {n_over} 与基线 {limit} 对不上"

    long_one = "把复盘写进产品的典型句子就是这一条它长得离谱而且没有任何理由留在界面上"
    assert len(long_one) == 35
    red_fails, _red_notes, red_over, red_hard = uta.verdicts(
        [*frags, (7, len(long_one), long_one)], known, limit
    )
    assert red_hard == 1, f"硬门没数出来：{red_hard}"
    assert red_over == n_over + 1, f"棘轮没数出来：{red_over} vs {n_over}"
    joined = "\n".join(red_fails)
    assert "35 字" in joined and long_one in joined, f"硬门红但没点名那条：{joined}"
    assert "这一档只许减" in joined, f"棘轮红但没说清口径：{joined}"


def test_commands_bites_on_a_route_that_is_not_in_app_py() -> None:
    """改一条路由 → 命令表门必须退 1，并同时点名「app.py 里不存在」与「CLI 投影跟着错」。"""
    import check_commands as cc

    saved_argv = sys.argv
    saved_commands = cc.COMMANDS
    real = (ROOT / "docs" / "commands.toml").read_bytes().decode("utf-8")
    needle = 'routes = ["POST /api/tasks"]'
    assert real.count(needle) == 1, "变异锚点不见了（add-task 的路由声明）"
    bad = real.replace(needle, 'routes = ["POST /api/tasksPROBE"]')

    tmp = Path(tempfile.mkdtemp(prefix="sp_commands_"))
    try:
        bad_path = _write(tmp / "commands.toml", bad)
        cc.COMMANDS = bad_path
        sys.argv = ["check_commands.py", "--check"]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            red = cc.main()
        text = buf.getvalue()
        assert red == 1, f"改坏了还退 {red}：{text[-800:]}"
        assert "[FAIL]" in text and "tasksPROBE" in text, f"退非零但没点名：{text[-1500:]}"
        assert "在 app.py 里不存在" in text, f"没点名真源：{text[-1500:]}"
        assert "CLI timeflow add-task" in text, f"没点名跟着错的投影：{text[-1500:]}"
    finally:
        cc.COMMANDS = saved_commands
        sys.argv = saved_argv
        shutil.rmtree(tmp, ignore_errors=True)

    green = _run([PY, "-X", "utf8", "scripts/check_commands.py", "--check"])
    assert green.returncode == 0, f"真表先就没过：{_out(green)[-800:]}"


def test_proxy_bites_on_a_stale_verified_date(tmp_path: Path) -> None:
    """把 last_verified 推到 2020 → 代理指标门必须退 1，并逐条点名 id 与过期天数。"""
    green = _run([PY, "-X", "utf8", "tools/proxy_audit.py", "--check"])
    assert green.returncode == 0, f"真表先就没过：{_out(green)[-800:]}"

    text = (ROOT / "docs" / "proxy-map.toml").read_bytes().decode("utf-8")
    stale = re.sub(r'last_verified = "\d{4}-\d{2}-\d{2}"', 'last_verified = "2020-01-01"', text)
    assert stale != text and "2020-01-01" in stale, "变异没生效"
    stale_path = _write(tmp_path / "stale.toml", stale)

    red = _run([PY, "-X", "utf8", "tools/proxy_audit.py", "--check", "--map", str(stale_path)])
    out = _out(red)
    assert red.returncode == 1, f"推到 2020 还退 {red.returncode}：{out[-800:]}"
    assert "条过期" in out, f"退非零但没点名过期：{out[-800:]}"
    assert "2020-01-01" in out and "done-count" in out, (
        f"没点名是哪条、上次什么时候验的：{out[-800:]}"
    )


@pytest.mark.skipif(NODE is None, reason="这台机器没有 node")
def test_ui_dom_probe_bites_on_a_throwing_view(tmp_path: Path) -> None:
    """换根 + 改坏一个视图 → DOM 探针必须退 1，并把抛的错原样打出来。

    换根是这道门唯一的人工注入口（它没有 `--index` 之类的参数），所以这里连**绿基线**也是换根的：
    同一棵副本、只把 index.html 换回真的那一份，必须回 0 —— 否则上面的红只是树搭错了。
    """
    assert NODE is not None
    dst = tmp_path
    (dst / "tools").mkdir()
    (dst / "src" / "web").mkdir(parents=True)
    shutil.copy2(ROOT / "tools" / "ui_dom_probe.mjs", dst / "tools" / "ui_dom_probe.mjs")
    shutil.copy2(ROOT / "src" / "web" / "offline.js", dst / "src" / "web" / "offline.js")
    index = _write(
        dst / "src" / "web" / "index.html",
        '<!doctype html><html><body><div id="app"></div><script>\n'
        "function render(){ throw new TypeError('boom-from-a-deliberately-broken-view'); }\n"
        "render();\n"
        "</script></body></html>\n",
    )

    red = _run([NODE, "tools/ui_dom_probe.mjs"], cwd=dst)
    text = _out(red)
    assert red.returncode == 1, f"视图抛错还退 {red.returncode}：{text[-800:]}"
    assert "boom-from-a-deliberately-broken-view" in text, f"退非零但没点名那个错：{text[-800:]}"

    shutil.copy2(ROOT / "src" / "web" / "index.html", index)
    green = _run([NODE, "tools/ui_dom_probe.mjs"], cwd=dst)
    assert green.returncode == 0, f"副本用真页面跑不绿，上面那条红不算数：{_out(green)[-800:]}"
    assert "14/14 个视图正常渲染" in _out(green)


class _RewriteBody:
    """把某个路径的 JSON 响应体换掉 —— 只改**判据看到的东西**，不碰产品代码。"""

    def __init__(self, app: object, suffix: str, new_body: dict[str, object]) -> None:
        self.app = app
        self.suffix = suffix
        self.new_body = new_body

    async def __call__(self, scope: dict, receive: object, send: object) -> None:
        if scope["type"] != "http" or not str(scope["path"]).endswith(self.suffix):
            await self.app(scope, receive, send)  # type: ignore[operator]
            return

        async def _send(message: dict) -> None:
            if message["type"] == "http.response.start":
                return  # 丢掉原来那一条，自己重发
            if message["type"] == "http.response.body" and message.get("more_body"):
                return
            body = json.dumps(self.new_body, ensure_ascii=False).encode()
            await send(  # type: ignore[operator]
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"application/json; charset=utf-8"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})  # type: ignore[operator]

        await self.app(scope, receive, _send)  # type: ignore[operator]


def _run_lf1(workroot: Path, mutate: bool) -> tuple[int, str]:
    """把 `lf1_live_check.main()` 真跑一遍（真起 uvicorn、真走 LF-1 主链）。"""
    import lf1_live_check as lf1

    saved_argv = sys.argv
    saved_factory = lf1.create_app
    saved_failures = list(lf1.FAILURES)
    saved_export = os.environ.get("TIMEFLOW_EXPORT__DIR")
    workroot.mkdir(parents=True, exist_ok=True)
    os.environ["TIMEFLOW_EXPORT__DIR"] = str(workroot / "export")
    lf1.FAILURES.clear()
    sys.argv = ["lf1_live_check.py"]
    if mutate:
        original = lf1.create_app
        lf1.create_app = lambda db: _RewriteBody(  # noqa: E731
            original(db), "/complete", {"status": "PROBE-未开始"}
        )
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            code = lf1.main()
    finally:
        lf1.FAILURES[:] = saved_failures
        lf1.create_app = saved_factory
        sys.argv = saved_argv
        if saved_export is None:
            os.environ.pop("TIMEFLOW_EXPORT__DIR", None)
        else:
            os.environ["TIMEFLOW_EXPORT__DIR"] = saved_export
    return code, buf.getvalue()


def test_lf1_live_bites_on_a_wrong_complete_response(tmp_path: Path) -> None:
    """真起服务跑一遍 lf1 → 把 complete 的响应体换掉 → 断言 ⑦ 那一项必须红。"""
    green_code, green_out = _run_lf1(tmp_path / "green", mutate=False)
    assert green_code == 0, f"真产品先就没过：{green_out[-1500:]}"
    assert "LF-1 真实运行验证：PASS" in green_out, green_out[-800:]

    red_code, red_out = _run_lf1(tmp_path / "red", mutate=True)
    assert red_code == 1, f"响应体换掉了还退 {red_code}：{red_out[-1500:]}"
    assert "[FAIL] ⑦ 任务状态" in red_out, f"退非零但没点名叫哪一项：{red_out[-1500:]}"
    assert "got='PROBE-未开始' want='完成'" in red_out, f"没把两边的值都打出来：{red_out[-1500:]}"
    assert "FAIL（1 项：⑦ 任务状态）" in red_out, f"收尾没点名：{red_out[-800:]}"


@pytest.mark.skipif(NODE is None, reason="这台机器没有 node")
def test_web_live_bites_when_the_event_delegation_is_gone(tmp_path: Path) -> None:
    """换根 + 拆掉事件委托 → `web_live` 必须退 1，且只点名这一条。

    这道门拿的是**服务出来的 html**（`urlopen(f"{base}/")`），而 `app.py` 的 `web_dir` 是
    `Path(__file__).parent.parent.parent / "web"` —— 所以副本必须连 `src/` 一起搬，
    并用 `PYTHONPATH` 把 `timeflow` 顶到副本那一份，页面才会来自副本。
    """
    assert NODE is not None
    needle = "document.addEventListener('click'"

    def stage(root: Path, mutate: bool) -> dict[str, str]:
        root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(ROOT / "src", root / "src", ignore=shutil.ignore_patterns("__pycache__"))
        (root / "tools").mkdir()
        # 判据本体 + 它 spawn 的子工具（`phone_check.mjs` 也从 `HERE/../src/web` 取 offline.js，
        # 必须一起搬，否则副本上的绿基线会因为「造包脚本不存在」而假红）
        for name in ("web_live_check.py", "contrast_audit.py", "phone_check.mjs"):
            shutil.copy2(ROOT / "tools" / name, root / "tools" / name)
        if mutate:
            index = root / "src" / "web" / "index.html"
            text = index.read_bytes().decode("utf-8")
            assert text.count(needle) == 1, "变异锚点不见了（事件委托那一行）"
            bad_text = text.replace(needle, "document.addEventListener('clickPROBE'")
            assert bad_text != text and needle not in bad_text, "变异没生效"
            _write(index, bad_text)
        env = dict(os.environ)
        env["PYTHONPATH"] = str(root / "src")
        env["TIMEFLOW_EXPORT__DIR"] = str(root / "export")
        return env

    good_root = tmp_path / "good"
    good = _run(
        [PY, "-X", "utf8", "tools/web_live_check.py"], cwd=good_root, env=stage(good_root, False)
    )
    assert good.returncode == 0, f"副本原样跑不绿，下面那条红就只是树搭错了：{_out(good)[-1500:]}"
    assert "[OK ] 有事件委托监听" in _out(good)

    bad_root = tmp_path / "bad"
    bad = _run(
        [PY, "-X", "utf8", "tools/web_live_check.py"], cwd=bad_root, env=stage(bad_root, True)
    )
    bad_text = _out(bad)
    assert bad.returncode == 1, f"拆了事件委托还退 {bad.returncode}：{bad_text[-1500:]}"
    assert "[FAIL] 有事件委托监听" in bad_text, f"退非零但没点名：{bad_text[-1500:]}"


@pytest.mark.skipif(NODE is None, reason="这台机器没有 node")
def test_render_bites_on_the_cli_hard_rejects() -> None:
    """render 的「不依赖浏览器」那一半：改黄金不写理由 / 未知参数，都必须退非零并点名。"""
    assert NODE is not None
    no_reason = _run([NODE, "tools/render_check.mjs", "--update", "--only", "today"])
    assert no_reason.returncode == 1, f"改黄金没带理由还退 {no_reason.returncode}"
    assert "--reason" in _out(no_reason), f"没点名缺什么：{_out(no_reason)[-500:]}"

    bogus = _run([NODE, "tools/render_check.mjs", "--selfproof-bogus"])
    assert bogus.returncode == 1, f"未知参数还退 {bogus.returncode}"
    assert "未知参数" in _out(bogus) and "--selfproof-bogus" in _out(bogus)


@pytest.mark.skipif(NODE is None, reason="这台机器没有 node")
def test_ui_flow_bites_on_unclaimed_items_and_unknown_flags(tmp_path: Path) -> None:
    """ui_flow 的「不依赖浏览器」那一半：未知参数、过滤后零条流、人工清单里没人认账的项。"""
    assert NODE is not None

    bogus = _run([NODE, "tools/ui_flow_check.mjs", "--selfproof-bogus"])
    assert bogus.returncode == 1 and "未知参数" in _out(bogus)

    nomatch = _run([NODE, "tools/ui_flow_check.mjs", "--only", "自证-不存在的流"])
    assert nomatch.returncode == 1, f"一条流都没匹配上还退 {nomatch.returncode}"
    assert "一条流都没匹配上" in _out(nomatch)

    item = "自证-没有人认账的第 99 项"
    header = "| 编号 | 怎么点 | 机器判得了吗 |\n|---|---|---|\n"
    unclaimed = _write(
        tmp_path / "unclaimed.md",
        f"# 人工验收\n\n## 功能项\n\n{header}| **{item}** | 点一下 | ？ |\n",
    )
    red = _run([NODE, "tools/ui_flow_check.mjs", "--coverage", "--doc", str(unclaimed)])
    assert red.returncode == 1, f"有没人认账的项还退 {red.returncode}：{_out(red)[-800:]}"
    assert "未对账的功能项" in _out(red) and item in _out(red), (
        f"退非零但没点名：{_out(red)[-800:]}"
    )

    claimed = _write(
        tmp_path / "claimed.md",
        f"# 人工验收\n\n## 功能项\n\n{header}| **{item}** | 点一下 | 人的观感，机器判不了 |\n",
    )
    green = _run([NODE, "tools/ui_flow_check.mjs", "--coverage", "--doc", str(claimed)])
    assert green.returncode == 0, f"写明理由了还不绿：{_out(green)[-800:]}"
    assert "正向对账通过" in _out(green)
