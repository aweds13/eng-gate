"""`timeflow.clock`（T-G62）—— 全仓唯一的「现在」出口 + 采集用的假时钟。

三件事必须有护栏（这一层的价值全在"能钉住"上，钉不住就退回"黄金跨午夜自己变红"）：

1. **默认路径一点不变**：不设 `TIMEFLOW_FAKE_TODAY` 时，`today()/now()` 与
   `date.today()` / `datetime.now()` 一致（否则就是偷偷改了产品行为）；
2. **设了就钉在那一天的本地正午**（固定到秒 —— 这样"几点跑"也不影响结果）；
   坏值当没设（**静默改成别的行为比报错更坏**）；
3. ★ **全仓不许再绕过它**：`src/timeflow/**`（除 `clock.py` 自己）里出现裸的
   `date.today()` / `datetime.now()` 就是没走这个出口 —— 那是这条线重新开始漂的第一步。
   判据是**剥掉注释与字符串之后**的代码（注释里可以讲历史，不能算违规）。
"""

from __future__ import annotations

import io
import re
import tokenize
from datetime import date, datetime, time, timezone
from pathlib import Path

from timeflow import clock

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "timeflow"


def _strip_comments_and_strings(source: str) -> str:
    """把注释与字符串字面量换成空格，只留下真代码（用 `tokenize`，不靠正则）。

    为什么要这样：`review.py` 的 docstring 里**故意**提到 `date.today()`（讲 T-D12 的历史），
    注释里写历史不算违规；正则扫会把那种句子判红，于是只能靠人绕过护栏 —— 那就没有护栏了。
    """
    out: list[str] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                out.append(" " * len(tok.string))
            else:
                out.append(tok.string)
    except tokenize.TokenError:  # 语法坏掉的文件：交给 ruff/pytest 去报，别在这里假红
        return source
    return "".join(out)


# ---------------------------------------------------------------- 默认路径


def test_default_matches_the_system_clock(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """不设假时钟时，`clock` 与系统时钟**完全一致**（这是"改了 27 处调用点"的安全前提）。"""
    monkeypatch.delenv(clock.FAKE_TODAY_ENV, raising=False)
    assert clock.fake_today() is None
    assert clock.today() == date.today()
    assert clock.today_iso() == date.today().isoformat()
    assert abs((clock.now() - datetime.now()).total_seconds()) < 5
    assert abs((clock.now_utc() - datetime.now(timezone.utc)).total_seconds()) < 5


# ---------------------------------------------------------------- 假时钟


def test_fake_today_pins_the_whole_day(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """设了 `TIMEFLOW_FAKE_TODAY`：日期是那一天、时刻固定在那一天的**本地正午**（UTC 一致换算）。"""
    monkeypatch.setenv(clock.FAKE_TODAY_ENV, "2026-06-15")
    assert clock.fake_today() == date(2026, 6, 15)
    assert clock.today() == date(2026, 6, 15)
    assert clock.today_iso() == "2026-06-15"
    assert clock.now() == datetime.combine(date(2026, 6, 15), time(12, 0))
    # 本地正午 → UTC：差值就是本机时区偏移（不写死 +08:00，跑在别的时区也成立）
    assert clock.now_utc() == clock.now().astimezone(timezone.utc)
    assert clock.now_utc().tzinfo == timezone.utc


def test_fake_today_ignores_broken_values(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """写坏的值 / 空串**当没设**：静默按别的日期跑比报错更坏（黄金会一夜之间全红）。"""
    for bad in ("2026-13-99", "今天", "", "   ", "2026/06/15"):
        monkeypatch.setenv(clock.FAKE_TODAY_ENV, bad)
        assert clock.fake_today() is None, bad
        assert clock.today() == date.today(), bad


def test_fake_today_is_stable_no_matter_what_time_it_is(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """假时钟下**时刻也不动**（不是"今天固定、几点随意"）—— 这是 FSRS 那种分钟级调度也需要的事。

    判据：同一句话连问两次拿到同一个瞬间；而且它离午夜 ≥ 11 小时（正午）。
    """
    monkeypatch.setenv(clock.FAKE_TODAY_ENV, "2026-06-15")
    first, second = clock.now(), clock.now()
    assert first == second
    midnight = datetime.combine(date(2026, 6, 15), time(0, 0))
    assert abs((first - midnight).total_seconds()) >= 11 * 3600


# ---------------------------------------------------------------- 全仓护栏


def test_no_module_asks_the_system_clock_directly() -> None:
    """★ `src/timeflow/**`（除 `clock.py`）里不许出现裸的 `date.today()` / `datetime.now()`。

    这条是 T-G62 的**反悔闸**：只要有一处绕过去，"今天"就又有了第二个来源，
    而第二个来源正是黄金跨午夜变红的根。判据只看**真代码**（注释/字符串已剥掉）。
    """
    banned = ("date.today()", "datetime.now()", "datetime.utcnow()", "datetime.now(timezone.utc)")
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        if path.name == "clock.py":
            continue
        code = _strip_comments_and_strings(path.read_text(encoding="utf-8"))
        for needle in banned:
            if needle in code:
                offenders.append(f"{path.relative_to(ROOT)}：{needle}")
    assert offenders == [], (
        "这些地方绕过了 `timeflow.clock`（今天是第二个来源了）：\n  " + "\n  ".join(offenders)
    )


def test_all_ported_call_sites_import_the_clock() -> None:
    """反过来也要查：**用了 `clock.` 的文件必须真的 import 了它**（否则 NameError 逃到运行期）。

    为什么值得一条：这一轮是**脚本批量替换**的（27 处 + 19 个 import），
    脚本最容易犯的错就是"改了用法忘了加 import"。
    """
    missing: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        if path.name == "clock.py":
            continue
        text = path.read_text(encoding="utf-8")
        code = _strip_comments_and_strings(text)
        if "clock." not in code:
            continue
        prefixes = ("from timeflow import clock", "from timeflow.clock import",
                    "import timeflow.clock")
        imported = any(line.startswith(prefixes) for line in text.splitlines())
        if not imported:
            missing.append(str(path.relative_to(ROOT)))
    assert missing == [], f"用了 clock 却没 import：{missing}"


# ---------------------------------------------------------------- 采集侧的接线（标记层）


def test_capture_tools_pin_the_same_day_everywhere() -> None:
    """采集侧三处必须一致：`serve --today` / fixture 基准日 / 浏览器 `Date` 垫片。

    ★ 边界：这只钉**标记层**（三处接线还在、用的是同一个常量）。真的"跨天也不红"由
    渲染层每轮跑出来的结果证明（`day=` 写在黄金第一行，改了常量 45 份会一起红）。
    """
    browser = (ROOT / "tools" / "tf_browser.mjs").read_text(encoding="utf-8")
    render = (ROOT / "tools" / "render_check.mjs").read_text(encoding="utf-8")
    serve = (ROOT / "tools" / "serve.py").read_text(encoding="utf-8")
    assert "export const CAPTURE_DAY = " in browser, "采集日常量没了"
    assert "export function clockShimSource(" in browser, "浏览器 Date 垫片没了"
    assert "export function setFixtureDay(" in browser, "fixture 基准日没了"
    assert "Page.addScriptToEvaluateOnNewDocument" in browser, "垫片必须是导航前注入的"
    assert "TIMEFLOW_FAKE_TODAY: CAPTURE_DAY" in render, "起服务时没把假时钟传下去"
    assert "setFixtureDay(CAPTURE_DAY)" in render, "fixture 没按采集日算相对日期"
    assert "installClock(CAPTURE_DAY)" in render, "浏览器时钟没钉"
    assert "day=${CAPTURE_DAY}" in render, "黄金头一行没记采集日"
    assert "--today" in serve and "TIMEFLOW_FAKE_TODAY" in serve, "serve.py 没有假时钟入口"


def test_capture_day_is_a_real_date_and_never_written_twice() -> None:
    """采集日必须是个**真日期**，而且只写一处（`CAPTURE_DAY`）—— 写两处就会漂。

    写坏值不会报错（`clock.fake_today()` 把它当没设），所以只能在这里拦：
    一个 `'2026-6-15'` 之类的手滑，会让假时钟**静默失效**，黄金第二天又开始漂。
    """
    browser = (ROOT / "tools" / "tf_browser.mjs").read_text(encoding="utf-8")
    m = re.search(r"export const CAPTURE_DAY = '([^']+)'", browser)
    assert m is not None, "tools/tf_browser.mjs 里找不到 CAPTURE_DAY"
    day = m.group(1)
    assert date.fromisoformat(day).isoformat() == day, f"CAPTURE_DAY={day!r} 不是规范的 YYYY-MM-DD"
    assert day not in (ROOT / "tools" / "render_check.mjs").read_text(encoding="utf-8"), (
        "render_check.mjs 里又写死了一遍采集日（应该引用 CAPTURE_DAY）"
    )
    # `serve.py` 的 docstring 里拿它当**用法例子**是允许的 → 判据只看真代码（注释/字符串剥掉）
    serve_src = (ROOT / "tools" / "serve.py").read_text(encoding="utf-8")
    serve_code = _strip_comments_and_strings(serve_src)
    assert day not in serve_code, "serve.py 里又写死了一遍采集日（应该由 --today 传进来）"
