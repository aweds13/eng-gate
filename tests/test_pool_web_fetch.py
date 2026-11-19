"""取页编排 + 三分类 + 变 Markdown + 字符窗口（卡 A374 · F58）。

就是 magpie ``search_fetch.go`` 的 pool 版。

为什么值当测：``fetch_page`` 是全仓**第一个按用户给的 URL 取东西**的地方。它坏掉的样子不是
「少一页」，而是三种更糟的：① 放过一个内网地址（云元数据 / 本机）；② 跟着重定向跳进内网
（第一跳查了、第三跳没查）；③ 按字节切窗口，把中文切成半个字。所以本文件**全程用桩**：
``fetch`` 与 ``resolve`` 都是假的，**零网络、零落盘**，断言只看「交给谁、判了谁、文案是什么」。

★ 本文件钉的五件事（对应卡 `「判据 2-5」）：
  ① 三分类十行 + GBK 出中文（不含 ``锟斤拷``、不含 U+FFFD）+ 未知 charset 不崩
     + 非法 UTF-8 出 U+FFFD；
  ② HTML 的六件事：丢 ``script`` / ``hidden``、``#`` 标题、两空格缩进列表、``pre`` 围栏、链接绝对化
     （相对变绝对、``javascript:`` 与纯图标链接不出现 ``](``）、``done()`` 清空壳行并压空行；
  ③ 窗口三件：默认 20000 / 上限 100000 / 负数走默认，且**按 rune 切**（中文页两个整字）；
  ④ 取页编排：30.0 超时原样传、三条拒收文案逐字、**每跳**都判地址、5 跳上限、``>= 400``、
     非文本类型拒收、5 MiB 截断不报错；
  ⑤ 两处**可核的缺席**：模块头没有出网库、``fetch_page`` 里没有 ``budget`` / ``reserve``
     （卡规格缺口 4）。

★ 两条不许松：``to_text`` 不许引 ``charset_normalizer``（``pyproject.toml`` 里没有它）；
``fetch_page`` 的重定向上限不许写成 10（那是 ``CheckRedirect == nil`` 的兜底分支，
见模块 docstring）。
"""

from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from pool import web_fetch as wf  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上
from pool.web_fetch import (  # noqa: E402
    WEB_FETCH_CHARS,
    WEB_FETCH_MAX_CHARS,
    WEB_FETCH_READ,
    WEB_FETCH_REDIRECTS,
    WEB_FETCH_TIMEOUT_S,
    FetchError,
    fetch_page,
    html_to_markdown,
    kind_of,
    split_part,
    to_text,
)

PRIVATE_MESSAGE = (
    "it is at a private address (this computer, its network, or a name that resolves to one), "
    "which web_fetch doesn't read"
)


# ---------------------------------------------------------------- 桩


class FakeFetch:
    """按顺序回放 (status, headers, body)，并记下每一次调用。"""

    def __init__(self, responses: list[tuple[int, dict[str, str], bytes]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def __call__(self, url, headers, timeout, addresses):
        self.calls.append(
            {"url": url, "headers": dict(headers), "timeout": timeout, "addresses": list(addresses)}
        )
        if len(self.calls) > len(self.responses):
            raise AssertionError(f"多取了一次：{url}")
        return self.responses[len(self.calls) - 1]


class FakeResolve:
    """主机名 -> 地址表；没配的按公网 8.8.8.8 回。"""

    def __init__(self, table: dict[str, list[str]] | None = None) -> None:
        self.table = table or {}
        self.hosts: list[str] = []

    def __call__(self, host: str):
        self.hosts.append(host)
        return self.table.get(host, ["8.8.8.8"])


def ok(body: bytes, media: str = "text/html; charset=utf-8") -> tuple[int, dict[str, str], bytes]:
    return 200, {"content-type": media}, body


def page(text: str) -> bytes:
    return f"<html><head><title>T</title></head><body><p>{text}</p></body></html>".encode()


# ================================================================ 判据 2：三分类


@pytest.mark.parametrize(
    ("media", "want"),
    [
        ("text/html", "html"),
        ("application/xhtml+xml", "html"),
        ("text/plain", "text"),
        ("text/csv", "text"),
        ("application/json", "text"),
        ("application/activity+json", "text"),
        ("application/xml", "text"),
        ("application/javascript", "text"),
        ("image/png", ""),
        ("", ""),
    ],
)
def test_kind_of_ten_rows(media: str, want: str) -> None:
    """① 十行表 —— 逐条照原件的 ``fetchKind``。"""
    assert kind_of(media) == want


def test_gbk_page_comes_out_as_chinese() -> None:
    """① GBK 页要出中文：不含 ``锟斤拷``、不含 U+FFFD（U+FFFD 说明解码退回了 UTF-8）。"""
    body = "<html><body><p>中文</p></body></html>".encode("gbk")
    title, text = to_text(body, "text/html; charset=gbk", "html", "http://e/")
    assert "中文" in text
    assert "锟斤拷" not in text
    assert "\ufffd" not in text


def test_unknown_charset_does_not_raise() -> None:
    """① ``charset=x-user-defined``：解码器建不起来 ⇒ 退回 UTF-8，**不抛**。"""
    title, text = to_text(b"<p>abc</p>", "text/html; charset=x-user-defined", "html", "http://e/")
    assert isinstance(text, str)
    assert "abc" in text


def test_invalid_utf8_becomes_replacement_char_in_text_kind() -> None:
    """① 非法 UTF-8 + ``kind == "text"`` ⇒ U+FFFD 而不是异常（原件的 ``ToValidUTF8``）。"""
    title, text = to_text(b"good \xff\xfe bad", "text/plain; charset=utf-8", "text", "http://e/")
    assert title == ""
    assert "\ufffd" in text


def test_to_text_does_not_use_charset_normalizer() -> None:
    """① 隐式依赖的钉子：``charset_normalizer`` 本机装着、CI 上没有，用了就是必崩。

    ★ 只查**可执行的 import 行**，不查整份源码 —— 模块 docstring 里要点名它解释「为什么不用」，
    查整份就等于自己咬自己。
    """
    src = Path(wf.__file__).read_text(encoding="utf-8")
    for word in ("charset_normalizer", "bs4", "markdownify", "html5lib"):
        pattern = rf"^\s*(?:import|from)\s+{word}\b"
        assert re.search(pattern, src, re.MULTILINE) is None, f"真的 import 了 {word}"


# ================================================================ 判据 3：HTML -> Markdown

SAMPLE = """<html><head><title>示例 页面</title>
<script>var secret = 1;</script></head>
<body>
<h1>标题</h1>
<p>第一段 <b>加粗</b> 文字。</p>
<ul><li>一<ul><li>一之一</li></ul></li><li>二</li></ul>
<pre><code>print(1)</code></pre>
<p><a href="/x">相对</a> <a href="javascript:alert(1)">脚本</a> <a href="#top">锚点</a>
<a href="/i"><img src="i.png"></a></p>
<blockquote>引用</blockquote>
<div hidden>藏起来</div>
<div aria-hidden="true">也藏起来</div>
</body></html>"""


def test_titles_and_headings() -> None:
    """② ``h1..h6`` ⇒ ``"#" * n + " "``，标题来自 ``<title>``。"""
    title, md = html_to_markdown(SAMPLE, "http://example.com/")
    assert title == "示例 页面"
    assert "# 标题" in md


def test_nested_lists_are_indented_two_spaces() -> None:
    """② 二级列表行以两个空格开头（``"  " * (len(lists) - 1)``）。"""
    _, md = html_to_markdown(SAMPLE, "http://example.com/")
    assert "- 一" in md
    assert "  - 一之一" in md
    assert "- 二" in md


def test_pre_fence_and_no_backticks_inside() -> None:
    """② ``pre`` ⇒ 三反引号围栏，围栏内的 ``code`` 不再加单反引号。"""
    _, md = html_to_markdown(SAMPLE, "http://example.com/")
    assert md.count("```") == 2
    assert "print(1)" in md
    assert "`print(1)`" not in md


def test_links_are_absolutized_and_junk_links_dropped() -> None:
    """② 相对链接变绝对；``javascript:`` / 锚点 / 纯图标链接都不出现 ``](``。"""
    _, md = html_to_markdown(SAMPLE, "http://example.com/")
    assert "[相对](http://example.com/x)" in md
    assert "脚本" in md
    assert "javascript:" not in md
    assert "[脚本]" not in md
    assert "#top" not in md
    assert "](/i)" not in md


def test_script_and_hidden_are_dropped_whole() -> None:
    """② ``script`` / ``hidden`` / ``aria-hidden="true"`` 整棵丢。"""
    _, md = html_to_markdown(SAMPLE, "http://example.com/")
    assert "secret" not in md
    assert "藏起来" not in md
    assert "也藏起来" not in md


def test_no_two_blank_lines_and_trimmed() -> None:
    """② 输出不含连续两个空行，且首尾没有空白。"""
    _, md = html_to_markdown(SAMPLE, "http://example.com/")
    assert "\n\n\n" not in md
    assert md == md.strip()


def test_done_clears_empty_shell_lines() -> None:
    """② ``done()``：``"-"`` / ``">"`` 空壳行清成空行、连续空行压一行。"""
    _, md = html_to_markdown("<p>a</p><p>-</p><p>&gt;</p><p>b</p>", "http://e/")
    assert md == "a\n\nb"


# ================================================================ 判据 4：字符窗口


def _window(out: str) -> str:
    """取正文里**被切出来的那一段**（丢掉尾部提示行）—— 数长度只许数它。"""
    body = out.split("\n\n", 1)[1]
    return body.partition("\n\n[")[0]


def test_default_window_is_20000_chars() -> None:
    """③ 30000 字默认切 20000，末行提示逐字。"""
    out = split_part("http://e/", "", "a" * 30000)
    assert out.split("\n\n", 1)[1].endswith(
        "[10000 more characters: call web_fetch with offset=20000 to read on]"
    )
    assert len(_window(out)) == 20000


def test_window_is_capped_at_100000() -> None:
    """③ ``max_chars=999999`` ⇒ 按 100000。"""
    out = split_part("http://e/", "", "a" * 200000, max_chars=999999)
    assert len(_window(out)) == WEB_FETCH_MAX_CHARS == 100000


def test_negative_max_chars_falls_back_to_default() -> None:
    """③ ``max_chars=-5`` ⇒ 走默认 20000（原件的 ``if limit <= 0``）。"""
    out = split_part("http://e/", "", "a" * 30000, max_chars=-5)
    assert len(_window(out)) == WEB_FETCH_CHARS == 20000


def test_offset_past_the_end_names_the_length() -> None:
    """③ ``offset >= len`` 且页非空 ⇒ 逐字文案带两个数。"""
    out = split_part("http://e/", "", "x" * 30000, offset=100000)
    assert out.endswith("(the page has 30000 characters, none from offset 100000)")


def test_empty_text_says_so() -> None:
    """③ 空页 ⇒ ``(the page has no text)``。"""
    assert split_part("http://e/", "", "").endswith("(the page has no text)")


def test_window_cuts_by_rune_not_by_byte() -> None:
    """③ 中文页 ``offset=19999, max_chars=2`` ⇒ **两个完整的「中」**。

    ★ 这条专抓「按字节切」：把 ``end = min(offset + limit, len(runes))`` 换成 ``len(text)``
    之类按字节的口径，切出来就会是半个字 / U+FFFD（反向变异 M3）。
    """
    out = split_part("http://e/", "", "中" * 40000, offset=19999, max_chars=2)
    body = out.split("\n\n", 1)[1]
    head, _, tail = body.partition("\n\n[")
    assert head == "中中"
    assert "\ufffd" not in out
    assert tail.startswith("19999 more characters")


def test_header_lines() -> None:
    """③ 首行 ``URL:``、次行 ``Title:``（空则不写）。"""
    assert split_part("http://e/x", "标题", "hello").startswith(
        "URL: http://e/x\nTitle: 标题\n\nhello"
    )
    assert split_part("http://e/x", "", "hello").startswith("URL: http://e/x\n\nhello")


# ================================================================ 判据 5：取页编排


def test_timeout_is_the_constant() -> None:
    """④ 30.0 原样传给 ``fetch``（常量不是装饰）。"""
    fake = FakeFetch([ok(page("hi"))])
    fetch_page(fake, FakeResolve(), "http://example.com/")
    assert fake.calls[0]["timeout"] == 30.0 == WEB_FETCH_TIMEOUT_S


def test_private_address_message_is_verbatim() -> None:
    """④ 解析出 ``127.0.0.1`` ⇒ 逐字那句私有地址文案，且**一个字节都没发出去**。"""
    fake = FakeFetch([ok(page("hi"))])
    with pytest.raises(FetchError) as excinfo:
        fetch_page(fake, FakeResolve({"127.0.0.1": ["127.0.0.1"]}), "http://127.0.0.1/")
    assert str(excinfo.value) == PRIVATE_MESSAGE
    assert fake.calls == []


def test_every_answer_is_checked() -> None:
    """④ 一个名字回两条地址，其中一条是 ``10.0.0.1`` ⇒ 也拒（每个地址都查）。"""
    fake = FakeFetch([ok(page("hi"))])
    resolve = FakeResolve({"example.com": ["8.8.8.8", "10.0.0.1"]})
    with pytest.raises(FetchError) as excinfo:
        fetch_page(fake, resolve, "http://example.com/")
    assert str(excinfo.value) == PRIVATE_MESSAGE
    assert fake.calls == []


def test_unresolvable_name_is_refused() -> None:
    """④ 一个地址都解析不出来 ⇒ 拒（不许「没地址也照连」）。"""
    fake = FakeFetch([ok(page("hi"))])
    with pytest.raises(FetchError):
        fetch_page(fake, FakeResolve({"example.com": []}), "http://example.com/")
    assert fake.calls == []


def test_empty_url() -> None:
    """④ 空 url ⇒ ``web_fetch needs a url``。"""
    with pytest.raises(FetchError) as excinfo:
        fetch_page(FakeFetch([]), FakeResolve(), "   ")
    assert str(excinfo.value) == "web_fetch needs a url"


@pytest.mark.parametrize("url", ["ftp://example.com/x", "file:///etc/passwd", "example.com"])
def test_only_http_and_https(url: str) -> None:
    """④ 非 http(s) ⇒ 逐字文案 + **原样**的 url。"""
    with pytest.raises(FetchError) as excinfo:
        fetch_page(FakeFetch([]), FakeResolve(), url)
    assert str(excinfo.value) == wf.ONLY_HTTP + url


def test_negative_offset() -> None:
    """④ ``offset < 0`` ⇒ ``offset can't be negative``。"""
    with pytest.raises(FetchError) as excinfo:
        fetch_page(FakeFetch([]), FakeResolve(), "http://example.com/", offset=-1)
    assert str(excinfo.value) == "offset can't be negative"


def test_six_redirects_is_too_many() -> None:
    """④ 6 次 302 ⇒ ``it redirects more than 5 times``。"""
    hop = (302, {"location": "/next", "content-type": "text/html"}, b"")
    fake = FakeFetch([hop] * 6)
    with pytest.raises(FetchError) as excinfo:
        fetch_page(fake, FakeResolve(), "http://example.com/a")
    assert str(excinfo.value) == "it redirects more than 5 times"
    assert len(fake.calls) == WEB_FETCH_REDIRECTS + 1 == 6


def test_five_redirects_is_fine() -> None:
    """④ 5 次 302 + 一页 ⇒ 放行（上限是「至多 5 跳」，第 6 跳才拒）。"""
    hop = (302, {"location": "/next", "content-type": "text/html"}, b"")
    fake = FakeFetch([hop] * 5 + [ok(page("到了"))])
    out = fetch_page(fake, FakeResolve(), "http://example.com/a")
    assert "到了" in out
    assert len(fake.calls) == 6


def test_every_hop_is_checked() -> None:
    """④ 第 3 跳指向 ``http://127.0.0.1/`` ⇒ 同一条私有地址文案（**每跳都查**，不只第一跳）。

    ★ 这条专抓「只在开头查一次」：前两跳都是公网、第 3 跳才拐进本机，仍必须死在解析上。
    """
    hop_a = (302, {"location": "http://a.example/1", "content-type": "text/html"}, b"")
    hop_b = (302, {"location": "http://127.0.0.1/", "content-type": "text/html"}, b"")
    fake = FakeFetch([hop_a, hop_b])  # 只给两跳：第三跳必须死在解析上，不许再发
    with pytest.raises(FetchError) as excinfo:
        fetch_page(fake, FakeResolve({"127.0.0.1": ["127.0.0.1"]}), "http://example.com/a")
    assert str(excinfo.value) == PRIVATE_MESSAGE
    assert [c["url"] for c in fake.calls] == ["http://example.com/a", "http://a.example/1"]


def test_every_hop_private_redirect_target() -> None:
    """④ 直接 302 到 ``http://127.0.0.1/`` ⇒ 私有地址文案。"""
    fake = FakeFetch([(302, {"location": "http://127.0.0.1/x"}, b"")])
    resolve = FakeResolve({"127.0.0.1": ["127.0.0.1"]})
    with pytest.raises(FetchError) as excinfo:
        fetch_page(fake, resolve, "http://example.com/a")
    assert str(excinfo.value) == PRIVATE_MESSAGE


def test_404_message() -> None:
    """④ 404 ⇒ ``the site answered 404 Not Found``。"""
    fake = FakeFetch([(404, {"content-type": "text/html"}, b"<html>no</html>")])
    with pytest.raises(FetchError) as excinfo:
        fetch_page(fake, FakeResolve(), "http://example.com/a")
    assert str(excinfo.value) == "the site answered 404 Not Found"


def test_non_text_media_type_message() -> None:
    """④ ``image/png`` ⇒ ``it is image/png, not a page of text``。"""
    fake = FakeFetch([(200, {"content-type": "image/png"}, b"\x89PNG")])
    with pytest.raises(FetchError) as excinfo:
        fetch_page(fake, FakeResolve(), "http://example.com/a")
    assert str(excinfo.value) == "it is image/png, not a page of text"


def test_body_is_cut_at_the_read_limit() -> None:
    """④ 超过 5 MiB 的部分不许进 ``to_text`` —— 交回的字数封顶在 5 MiB。"""
    fake = FakeFetch([ok(b"a" * (6 << 20), "text/plain; charset=utf-8")])
    out = fetch_page(fake, FakeResolve(), "http://example.com/a", max_chars=200000)
    assert WEB_FETCH_READ == 5 << 20
    assert len(_window(out)) == WEB_FETCH_MAX_CHARS


def test_redirect_target_is_the_reported_url() -> None:
    """④ 报告的 ``URL:`` 是**最终**那一跳，不是最初那个。"""
    fake = FakeFetch([(302, {"location": "/next"}, b""), ok(page("到了"))])
    out = fetch_page(fake, FakeResolve(), "http://example.com/a")
    assert out.startswith("URL: http://example.com/next\n")


def test_no_budget_reserve_in_fetch_page() -> None:
    """⑤ 可核的缺席：``fetch_page`` 里没有 ``budget`` / ``reserve``（卡规格缺口 4 没实现那条）。"""
    src = inspect.getsource(fetch_page)
    assert "budget" not in src
    assert "reserve" not in src


FORBIDDEN = (
    "import urllib",
    "import socket",
    "import requests",
    "import httpx",
    "urlopen",
    "getaddrinfo",
)


def test_web_fetch_module_imports_no_network_library() -> None:
    """⑤ 模块头零出网库（体例照 ``tests/test_pool_rest.py:323-333``）。"""
    mod_src = Path(wf.__file__).read_text(encoding="utf-8")
    head = mod_src.split("\n\n", 1)[0] + mod_src.split("ROOT = Path", 1)[0]
    for word in FORBIDDEN:
        assert word not in head, f"模块头部出现了出网库：{word}"


def test_netguard_module_imports_no_network_library() -> None:
    """⑤ netguard 同样零出网（判词只吃字符串，不出网解析）。"""
    from pool import netguard

    mod_src = Path(netguard.__file__).read_text(encoding="utf-8")
    for word in FORBIDDEN:
        assert word not in mod_src, f"出现了出网库：{word}"
