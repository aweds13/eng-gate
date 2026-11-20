"""卡 A385 / F57 的钉子：searcher 的选择与「让位」，三种失败要分开。

这里的每一条都对着 `tools/pool/searcher.py` 的六个纯函数，**零网络、零落盘、零钟表** ——
去问模型的 `ask` 全是本地桩（卡规格「判据」段）。

钉子清单：

1. `chosen` 的 8 行表（"" / off / ghost / 关着 / 不会搜 / 没模型 / 模型下线 / 全在），
   加一条反向断言：gone / off / cant / nomodel **四个值两两不等**（并成一个就分不出三种失败了）。
2. `rank` 的 10 行表（逐条照 `search.go:300-327`）；`turn` 一轮最多 3 个、按 rank 升序、
   同一个 provider 只出现一次、relay **自动挑选时永不入选**、被点名时出现且排最后。
3. `verdict` 的三种结局 + 那一对互斥 bool：`not_searched is True and nothing_found is False
   and is_found_nothing() is True` 三句一起断言（判据 3(d)）；`Sources:` 段只在 1..20 条时追加。
4. `search` 的让位四条：最多问 3 个、同 provider 不重复、点名的只问一次且错误串带逐字尾巴、
   让位账五键。
5. `instead` 五键 + off 的真语义：off 关的是 **provider 搜索**，Search API 那条路照跑；
   连 Search API 都没有才回那句逐字错误。

★ 本文件**故意不碰** `tests/test_pool_gateway.py`：换号循环（@gateway.py:651-709@）是另一层，
  「换号 ≠ 让位」是卡规格「不许做」的第 2 条。本卡一个字节都没动它。

★ 判据 3(e) 的口径：卡规格把 :961 的 citation 过滤与 :999-1000 的 20 条上限写在一句里；
  原件里 `sources` 只来自 `web_search_tool_result` 的结果条目，citation 只进 `Hit.cited`。
  这里按原件钉（模块 docstring「与卡规格字面的一处出入」），两处各有一组断言。

作者：T-AG673（卡 A385）
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from pool import searcher as se  # noqa: E402


def _p(**kw):
    """造一个 ProviderView，只写关心的那几个字段。"""
    return se.ProviderView(**kw)


def _asks(fail_first_n=99):
    """一个会记流水、并按顺序判失败的 ask 桩（第 fail_first_n 次之后成功）。"""
    seen: list[tuple[str, str]] = []

    def ask(provider: str, model: str) -> se.Failure:
        seen.append((provider, model))
        if len(seen) > fail_first_n:
            return se.Failure(kind=se.KIND_OK, said=f"{provider} answered")
        return se.Failure(kind=se.KIND_ERROR, why=f"{provider}/{model}: timed out")

    return ask, seen


# ---------------------------------------------------------------- 判据 1：chosen


def test_chosen_table():
    """8 行表。点名的**模型**下线 ⇒ 退小模型，**不报 gone**（`search.go:387-392`）。"""
    providers = {
        "p1": _p(id="p1", agent="claude", small="s1", models=("m1", "m2")),
        "off1": _p(id="off1", agent="claude", on=False),
        "cant1": _p(id="cant1"),  # 什么都不会搜 ⇒ rank -1
        "bare": _p(id="bare", agent="claude"),  # 会搜，但 small 与 models 都空
        "gone": _p(id="p1", agent="claude"),
    }
    # 四值这里写**字面量**，不用模块常量：常量改名/改值必须在表上当场红，
    # 而不是跟着一起漂（判据 1 的反向断言就靠这一条）。
    rows = [
        ("", se.Choice(None, "", "")),
        ("off", se.Choice(None, "", "")),
        ("ghost", se.Choice(None, "", "gone")),
        ("off1", se.Choice("off1", "", "off")),
        ("cant1", se.Choice("cant1", "", "cant")),
        ("bare", se.Choice("bare", "", "nomodel")),
        ("p1/m9", se.Choice("p1", "s1", "")),  # m9 不在模型表 ⇒ 退小模型
        ("p1/m1", se.Choice("p1", "m1", "")),
    ]
    for picker, want in rows:
        assert se.chosen(picker, providers) == want, picker


def test_chosen_why_values_are_four_distinct():
    """gone / off / cant / nomodel 两两不等 —— 并成一个，三种失败就分不出来了。"""
    providers = {
        "off1": _p(id="off1", agent="claude", on=False),
        "cant1": _p(id="cant1"),
        "bare": _p(id="bare", agent="claude"),
    }
    whys = {
        se.chosen("ghost", providers).why,
        se.chosen("off1", providers).why,
        se.chosen("cant1", providers).why,
        se.chosen("bare", providers).why,
    }
    assert whys == {"gone", "off", "cant", "nomodel"}
    assert len(whys) == 4
    assert (se.WHY_GONE, se.WHY_OFF, se.WHY_CANT, se.WHY_NONE_OF) == (
        "gone",
        "off",
        "cant",
        "nomodel",
    )
    assert len(se.WHY) == 4


def test_chosen_off_and_empty_are_the_same_reading():
    """`chosen("off")` 与 `chosen("")` 返回值一模一样 —— 这就是 `search` 要单独收 picker 的原因。"""
    assert se.chosen("off", {}) == se.chosen("", {})


# ------------------------------------------------------------------ 判据 2：rank


def test_rank_table():
    """10 行，逐条照 `search.go:300-327`。"""
    rows = [
        (_p(id="a", agent="claude"), 0),
        (_p(id="b", agent="codex"), 1),
        (_p(id="c", agent="copilot", searches_itself=("responses",)), -1),
        (_p(id="d", searches_itself=("anthropic",)), 2),
        (_p(id="e", searches_itself=("responses",)), 3),
        (_p(id="f", searches_itself=("chat",)), 4),
        (_p(id="g", part_searcher=True, models=("m",), searches_alone=("m",)), 4),
        (_p(id="h", google=True), 5),
        (_p(id="i", remote_searches=True), 5),
        (_p(id="j"), -1),
    ]
    for view, want in rows:
        assert se.rank(view) == want, view.id


def test_rank_part_searcher_needs_a_searches_alone_model():
    """`partSearcher && searchesAlone` 是「有那个模型」而不是「声明了会搜」（:234-247）。"""
    assert se.rank(_p(id="x", part_searcher=True, models=("m",), searches_alone=("other",))) == -1
    assert se.rank(_p(id="x", part_searcher=True, models=("m",), searches_alone=("m",))) == 4


def test_turn_stops_at_three_in_rank_order():
    """5 个都会失败 ⇒ 一轮只问 3 个，且按 rank 升序（判据 2(b)）。"""
    views = [
        _p(id="chat4", searches_itself=("chat",), small="c"),
        _p(id="claude0", agent="claude", small="a"),
        _p(id="anthropic2", searches_itself=("anthropic",), small="b"),
        _p(id="codex1", agent="codex", small="d"),
        _p(id="responses3", searches_itself=("responses",), small="e"),
    ]
    got = se.turn(se.chosen("", views), views)
    assert got == ["claude0/a", "codex1/d", "anthropic2/b"]


def test_turn_skips_relay_unless_named_and_puts_it_last():
    """relay 自动挑选时**永不入选**；被点名时出现，且排在最后（判据 2(c)）。"""
    views = {
        "claude0": _p(id="claude0", agent="claude", small="a"),
        "relay": _p(id="relay", relay=True, models=("r",)),
        "svc": _p(id="svc", service=True),
    }
    assert se.turn(se.chosen("", views), views) == ["claude0/a"]

    named = se.turn(se.chosen("relay", views), views)
    assert named == ["relay/r"]
    assert named[-1] == "relay/r"
    assert se.chosen("relay", views).why == ""


def test_turn_asks_each_provider_once():
    """同一个 provider 两个模型 ⇒ 一轮里只出现一次（判据 2(d) / 原件 :779）。"""
    views = [
        _p(id="p1", agent="claude", small="s1", models=("m1", "m2")),
        _p(id="p1", agent="claude", small="s2", models=("m3",)),
        _p(id="p2", agent="codex", small="s3"),
    ]
    got = se.turn(se.chosen("", views), views)
    assert got == ["p1/s1", "p2/s3"]
    assert [label.split("/", 1)[0] for label in got].count("p1") == 1


def test_turn_prefers_ready_and_keeps_out_of_credit_last():
    """有额度的排在全耗尽的之前（原件 :364-374 的 `bestReady`）。"""
    views = {
        "spent": _p(id="spent", agent="claude", small="a", ready=False),
        "fresh": _p(id="fresh", searches_itself=("chat",), small="b", ready=True),
    }
    assert se.turn(se.chosen("", views), views) == ["fresh/b", "spent/a"]


# --------------------------------------------------------------- 判据 3：verdict


def test_verdict_ok_when_searched_and_named_a_page():
    """(a) server_tool_use + 带 "://" 的话 ⇒ ok。"""
    f = se.verdict([{"type": "server_tool_use"}, {"type": "text", "text": "see http://a"}])
    assert f.kind == se.KIND_OK
    assert f.not_searched is False
    assert f.nothing_found is False
    assert f.said == "see http://a"


def test_verdict_found_nothing_when_searched_but_named_no_page():
    """(b) 结果条目是空的、话里也没有地址 ⇒ 搜过了，但没找到。"""
    f = se.verdict(
        [
            {"type": "web_search_tool_result", "content": []},
            {"type": "text", "text": "I think it is probably fine."},
        ]
    )
    assert f.kind == se.KIND_FOUND_NOTHING
    assert f.nothing_found is True
    assert f.not_searched is False
    assert f.why == se.FOUND_NOTHING_TEXT


def test_verdict_not_searched_when_it_never_reached_the_tool():
    """(c)(d) 只有文字、没有任何搜索块 ⇒ 压根没搜。三句一起断言（判据 3(d)）。"""
    f = se.verdict([{"type": "text", "text": "From memory: the answer is 42."}])
    assert f.kind == se.KIND_NOT_SEARCHED
    assert f.not_searched is True
    assert f.nothing_found is False
    assert f.is_found_nothing() is True  # errNotSearched 包着 errFoundNothing（:906）
    assert f.why == se.NOT_SEARCHED_TEXT


def test_verdict_sources_cap_is_twenty():
    """(e) 20 条结果 ⇒ 追加 `Sources:` 段；21 条 ⇒ 不追加（:999-1000）。"""

    def _blocks(n: int):
        return [
            {
                "type": "web_search_tool_result",
                "content": [{"url": f"http://x/{i}", "title": f"T{i}"} for i in range(n)],
            },
            {"type": "text", "text": "summary"},
        ]

    f20 = se.verdict(_blocks(20))
    assert f20.kind == se.KIND_OK
    assert se.SOURCES_HEAD in f20.said
    assert f20.said.count("\n- ") == 20
    assert f20.said.endswith("- T19 \u2014 http://x/19")

    f21 = se.verdict(_blocks(21))
    assert f21.kind == se.KIND_OK
    assert se.SOURCES_HEAD not in f21.said


def test_verdict_citations_do_not_make_sources():
    """21 条 citation 一条都不进 `Sources:` —— 它们只给 `Hit.cited` 配音（:961 / :988-990）。"""
    citations = [{"url": f"http://c/{i}", "cited_text": f"q{i}"} for i in range(21)]
    f = se.verdict(
        [
            {"type": "server_tool_use"},
            {"type": "text", "text": "see http://c", "citations": citations},
        ]
    )
    assert f.kind == se.KIND_OK
    assert se.SOURCES_HEAD not in f.said
    assert f.sources == ()


def test_verdict_citation_filters():
    """citation 的三条过滤：URL 非空、CitedText 非空、同 URL 只认第一次（:961）。"""
    f = se.verdict(
        [
            {
                "type": "web_search_tool_result",
                "content": [{"url": "http://a", "title": "A"}, {"url": "http://b", "title": "B"}],
            },
            {
                "type": "text",
                "text": "see http://a",
                "citations": [
                    {"url": "http://a", "cited_text": "first"},
                    {"url": "http://a", "cited_text": "second"},
                    {"url": "", "cited_text": "no url"},
                    {"url": "http://b", "cited_text": ""},
                ],
            },
        ]
    )
    assert f.found[0].cited == "first"
    assert f.found[1].cited == ""
    assert f.sources == ("- A \u2014 http://a", "- B \u2014 http://b")


def test_verdict_takes_an_error_block_as_an_already_judged_failure():
    """`type == "error"` 的块当接住的失败（模块 docstring 第 3 条）。"""
    f = se.verdict([{"type": "error", "message": "429 too many requests"}])
    assert f.kind == se.KIND_ERROR
    assert f.why == "429 too many requests"


# ---------------------------------------------------------------- 判据 5：instead


def test_instead_five_keys_when_it_found_nothing():
    """(a) 找不到的让位：`why` 空、`nothing_found` 真。"""
    f = se.Failure(kind=se.KIND_FOUND_NOTHING, nothing_found=True, why=se.FOUND_NOTHING_TEXT)
    got = se.instead("p1", "m1", f)
    assert got == {
        "instead": "p1/m1",
        "picked": False,
        "nothing_found": True,
        "not_searched": False,
        "why": "",
    }


def test_instead_why_is_the_unprefixed_message():
    """(b) 报错的让位：`why` 等于 "provider: " 之后那一段（原件的 `TrimPrefix`）。"""
    f = se.Failure(kind=se.KIND_ERROR, why="p1/m1: boom")
    assert se.instead("p1", "m1", f)["why"] == "boom"
    # 没有那个前缀就原样留着
    assert se.instead("p1", "m1", se.Failure(kind=se.KIND_ERROR, why="boom"))["why"] == "boom"


def test_instead_not_searched_is_a_finding_not_an_error():
    """「没搜」既不算报错也不算没找到：`why` 空、两个 bool 里只有 `not_searched` 真。"""
    got = se.instead("p1", "", se.Failure(kind=se.KIND_NOT_SEARCHED, not_searched=True))
    assert got == {
        "instead": "p1",
        "picked": False,
        "nothing_found": False,
        "not_searched": True,
        "why": "",
    }


# ----------------------------------------------------------------- 判据 4：search


def test_search_stops_after_three_searchers():
    """(a) 5 个都会失败 ⇒ 只问 3 个（判据 4(a) / 原件 :776）。"""
    views = {f"s{i}": _p(id=f"s{i}", searches_itself=("chat",), small=f"m{i}") for i in range(5)}
    ask, seen = _asks()
    r = se.search(se.chosen("", views), views, ask)
    assert len(r.tried) == se.SEARCHERS_IN_TURN == 3
    assert len(seen) == 3
    assert r.by == se.BY_SEARCHER
    assert r.kind == se.KIND_ERROR


def test_search_named_searcher_gets_no_relief():
    """(b) 点名的失败 ⇒ 只问一次，错误串带逐字尾巴（:753-761）。"""
    views = {
        "p1": _p(id="p1", agent="claude", small="s1"),
        "p2": _p(id="p2", agent="codex", small="s2"),
    }
    ask, seen = _asks()
    r = se.search(se.chosen("p1", views), views, ask)
    assert r.tried == ("p1/s1",)
    assert len(seen) == 1
    assert r.error.endswith(se.PICKED_LONE)
    assert se.PICKED_LONE in r.error


def test_search_gives_way_and_keeps_the_ledger():
    """(c) 非点名的第一个失败 ⇒ 第二个被问，结果带五键让位账。"""
    views = {
        "p1": _p(id="p1", agent="claude", small="s1"),
        "p2": _p(id="p2", agent="codex", small="s2"),
    }
    ask, seen = _asks(fail_first_n=1)
    r = se.search(se.chosen("", views), views, ask)
    assert [pid for pid, _ in seen] == ["p1", "p2"]
    assert r.tried == ("p1/s1", "p2/s2")
    assert r.kind == se.KIND_OK
    assert r.by == se.BY_SEARCHER
    assert r.instead == {
        "instead": "p1/s1",
        "picked": False,
        "nothing_found": False,
        "not_searched": False,
        "why": "timed out",
    }


def test_search_never_asks_the_same_provider_twice():
    """(d) 一个 provider 出现两次 ⇒ `tried` 只出现一次（原件 :779）。"""
    views = [
        _p(id="p1", agent="claude", small="s1", models=("m1", "m2")),
        _p(id="p1", agent="claude", small="s2", models=("m3",)),
        _p(id="p2", agent="codex", small="s3"),
    ]
    ask, seen = _asks()
    r = se.search(se.chosen("", views), views, ask)
    assert [pid for pid, _ in seen] == ["p1", "p2"]
    assert r.tried == ("p1/s1", "p2/s3")


def test_search_falls_back_to_the_search_api():
    """全都没问出来时，Search API 那条路才接手（原件 :790-795）。"""
    views = {"p1": _p(id="p1", agent="claude", small="s1")}
    ask, seen = _asks()
    r = se.search(
        se.chosen("", views),
        views,
        ask,
        search_api=lambda: se.Failure(kind=se.KIND_OK, said="api answer"),
    )
    assert r.kind == se.KIND_OK
    assert r.by == se.BY_SEARCH_API
    assert r.said == "api answer"
    assert len(seen) == 1


# ------------------------------------------------------------ 判据 5：off 的真语义


def test_off_keeps_the_search_api_road_open():
    """(c) off + 有 Search API ⇒ `ask` 调 0 次、`search_api` 调 1 次（:668-673）。"""
    calls = {"api": 0}

    def api() -> se.Failure:
        calls["api"] += 1
        return se.Failure(kind=se.KIND_OK, said="api answer")

    views = {"p1": _p(id="p1", agent="claude", small="s1")}
    ask, seen = _asks()
    r = se.search(se.chosen("off", views), views, ask, picker="off", search_api=api)
    assert seen == []
    assert calls["api"] == 1
    assert r.kind == se.KIND_OK
    assert r.by == se.BY_SEARCH_API


def test_off_without_a_search_api_is_the_verbatim_error():
    """(d) off 且无 Search API ⇒ 文案逐字等于 `search.go:709`。"""
    views = {"p1": _p(id="p1", agent="claude", small="s1")}
    ask, seen = _asks()
    r = se.search(se.chosen("off", views), views, ask, picker="off")
    assert seen == []
    assert r.kind == se.KIND_ERROR
    assert r.error == "no provider that can search the web, nor a search API, is set up in magpie"
    assert r.error == se.NO_SEARCHER


def test_no_searcher_at_all_is_the_verbatim_error():
    """一个能搜的都没有（连 off 都不是）⇒ 同一句逐字错误。"""
    ask, seen = _asks()
    r = se.search(se.chosen("", {}), {}, ask)
    assert seen == []
    assert r.error == se.NO_SEARCHER


# ------------------------------------------------- 不许做 ④：这几个词一个都不许进

FORBIDDEN_IN_SEARCHER = (
    "urllib",
    "requests",
    "httpx",
    "socket",
    "urlopen",
    "http.client",
    "time.sleep",
    "sleep(",
    "time.time(",
    "datetime.now(",
    "hashlib",
    "open(",
    "print(",
    "os.environ",
)


def test_searcher_has_no_network_no_clock_no_disk_no_print():
    """纯函数：不读盘、不读钟、不出网、不 print（卡规格「不许做」第 4 条）。"""
    src = inspect.getsource(se)
    hits = [word for word in FORBIDDEN_IN_SEARCHER if word in src]
    assert hits == []
    for number in ("600", "3600", "1800"):
        assert number not in src


def test_searcher_module_head_has_no_network_import():
    """模块头（第一个空行段之前）不 import 任何出网/读盘的东西。"""
    src = inspect.getsource(se)
    head = src.split("\n\n", 1)[0]
    for word in ("import requests", "import urllib", "import httpx", "import socket"):
        assert word not in head


def test_six_public_functions_are_here():
    """六个纯函数齐全，且都是普通函数（不是类方法、不是桩）。"""
    for name in ("rank", "chosen", "turn", "verdict", "instead", "search"):
        assert callable(getattr(se, name)), name
    assert se.SEARCHERS_IN_TURN == 3
    assert se.MANUAL_RELAY_RANK == 6
