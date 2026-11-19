"""取一个网页：判地址 -> 每跳查 -> 解码 -> 变 Markdown -> 切窗口（卡 A374 · F58）。

magpie ``internal/gateway/search_fetch.go`` 的 pool 版。**这个模块不出网**：地址解析与 HTTP
取回都是**注入的**（``resolve`` / ``fetch``），所以本文件里没有任何 socket / urllib / requests /
httpx —— 判据 5 的模块头断言钉的正是这一条。

## 为什么把出网摘出去

仓里那两处真出网的地方都写着同一条理由：``tools/pool/checkin.py:229`` 与
``tools/pool/gateway.py:827`` 逐字「端点来自能力表常量，不是用户输入」。本模块的 URL **恰恰
来自用户或模型** —— 那条理由在这里不成立，所以地址判词必须自己算（``pool/netguard.py``），
而且**每一跳**都要算。把 ``fetch`` 摘成参数不是为了好测，是因为「谁真的连」这件事不该藏在
一个纯函数里。

## 移植口径（与原件逐条对照）

- ``kind_of`` 照 ``search_fetch.go:190-200``：``text/html`` 与 ``application/xhtml+xml`` 是 html；
  前缀 ``text/``、``application/json``、``application/xml``、后缀 ``+json`` / ``+xml``、
  ``application/javascript``、``application/x-ndjson`` 是 text；其余空串。
- ``to_text`` 照 ``:203-217``：先按 content-type 的 charset 解码，**解码器建不起来就退回裸字节**；
  text 类标题为空；html 类交 ``html_to_markdown``。
- ``html_to_markdown`` 照 ``:230-479`` 的 ``mdWriter``：丢弃表 / 标题六级 / 列表 / 围栏 /
  链接绝对化 / ``done()`` 的空壳行与压空行。
- ``split_part`` 照 ``:100-122`` + ``:78-82``：默认 20000、上限 100000、**按 rune 不按字节**。
- ``fetch_page`` 照 ``:66-187``：三条拒收文案逐字、每跳判地址、``>= 400`` 判据、``kind`` 空判据。

## 与原件**不同**的三处（都是判断，不是遗漏）

1. **重定向上限取 5，不取 10**。原件有两处数：``search_fetch.go:142-143`` 的 ``len(via) >= 10`` 只在
   ``CheckRedirect == nil`` 时生效；走 ``publicClient`` 时真正生效的是
   ``image_fetch_guard.go:72`` 的 ``const imageRedirects = 5``
   与 ``:355`` 的 ``len(via) > imageRedirects``。
   本卡取 **5**（卡规格「不许把重定向上限改成 10」把理由写死了）。
2. **没有 ``budget.Reserve(...)``**（原件 ``:83``）。本仓 ``callers.toml`` 没有预算字段、
   ``limits.toml`` 按卡 / 按账号，没有「按调用方 key 预留」的对应物（卡规格缺口 4）。
   判据 5(h) 把这条**没实现**钉成可核的缺席：``inspect.getsource(fetch_page)``
   里不许出现 ``budget`` / ``reserve``。
3. **钉住的那批地址显式交给 ``fetch``**（第四个参数）。原件在 socket 层再查一次
   （``guardDialer`` 的 ``Control``），本仓没有那一层 —— 与其假装钉住了，不如把地址摆到台面上，
   谁实现 ``fetch`` 谁负责只连这几个地址。

作者：T-AG662（卡 A374）
"""

from __future__ import annotations

from html.parser import HTMLParser
from http import HTTPStatus
from typing import TYPE_CHECKING

from pool.netguard import public

if TYPE_CHECKING:
    from collections.abc import Mapping

#: 一次取页最多等多久（原件 ``webFetchTimeout = 30 * time.Second``）。**原样传给注入的 ``fetch``**。
WEB_FETCH_TIMEOUT_S = 30.0
#: 读回的字节上限（原件 ``webFetchRead = 5 << 20``）。超了截断，**不报错**
#: （原件的 ``io.LimitReader`` 就是这个口径）。
WEB_FETCH_READ = 5 << 20
#: 一次交回的默认字符数（原件 ``webFetchChars = 20000``）。
WEB_FETCH_CHARS = 20000
#: 一次能要的上限（原件 ``webFetchMaxChars = 100000``）。
WEB_FETCH_MAX_CHARS = 100000
#: 至多跟几跳重定向（见模块 docstring 第 1 条：取 5，不取 10）。
WEB_FETCH_REDIRECTS = 5

#: 请求头照原件 ``search_fetch.go:132-135``。
HEADERS: Mapping[str, str] = {
    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
    "User-Agent": "Mozilla/5.0 (compatible; web-fetch)",
}

ONLY_HTTP = "web_fetch reads only http:// and https:// URLs, not "
PRIVATE_MESSAGE = (
    "it is at a private address (this computer, its network, or a name that resolves to one), "
    "which web_fetch doesn't read"
)
NO_ANSWER = "it has no address to connect to (the name didn't resolve)"


class FetchError(Exception):
    """取不到这一页（拒收 / 解析不出地址 / 站点回错）。文案就是给用户看的那句。"""


Fetch = (
    "Callable[[str, Mapping[str, str], float, Sequence[str]], "
    "tuple[int, Mapping[str, str], bytes]]"
)
Resolve = "Callable[[str], Sequence[str]]"


# ================================================================ 三分类（判据 2）


def kind_of(media_type: str) -> str:
    """``media_type`` 属于哪一类：``"html"`` / ``"text"`` / ``""``（原件 ``:190-200``）。"""
    mt = media_type.strip().lower()
    if mt in ("text/html", "application/xhtml+xml"):
        return "html"
    if (
        mt.startswith("text/")
        or mt in (
            "application/json",
            "application/xml",
            "application/javascript",
            "application/x-ndjson",
        )
        or mt.endswith("+json")
        or mt.endswith("+xml")
    ):
        return "text"
    return ""


def _charset_of(content_type: str) -> str:
    """从 content-type 里取 charset（取不到回空串）。"""
    for part in content_type.split(";")[1:]:
        name, sep, value = part.partition("=")
        if sep and name.strip().lower() == "charset":
            return value.strip().strip("\"'")
    return ""


def _decode(body: bytes, content_type: str) -> str:
    """按 charset 解码；解码器建不起来 / 该编码解不动 ⇒ 退回 UTF-8。

    原件走的是 ``charset.NewReader`` 的兜底（``:203-217``）。

    ★ 不引 ``charset_normalizer``：它在本机装着，但 ``pyproject.toml`` 的 ``dependencies`` 里没有 ——
    用了就是在 CI 上必崩的隐式依赖（卡规格判据 2 的★）。
    """
    charset = _charset_of(content_type)
    if charset:
        try:
            return body.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError, ValueError):
            pass
    return body.decode("utf-8", errors="replace")


def to_text(body: bytes, content_type: str, kind: str, base: str) -> tuple[str, str]:
    """``(title, text)``：text 类标题为空，html 类交 ``html_to_markdown``（原件 ``:203-217``）。"""
    decoded = _decode(body, content_type)
    if kind == "html":
        return html_to_markdown(decoded, base)
    return "", decoded


# ================================================================ HTML -> Markdown（判据 3）

#: 整棵丢掉的标签（原件 ``mdSkip``，``:346`` 十四个）。
_MD_SKIP = frozenset(
    {
        "script",
        "style",
        "noscript",
        "template",
        "svg",
        "iframe",
        "object",
        "canvas",
        "head",
        "select",
        "button",
        "input",
        "textarea",
    }
)

#: 块级：前后各两个换行（原件 ``mdBlock``，``:347-350``）。
_MD_BLOCK = frozenset(
    {
        "p",
        "div",
        "section",
        "article",
        "header",
        "footer",
        "main",
        "aside",
        "nav",
        "table",
        "tr",
        "blockquote",
        "form",
        "figure",
        "figcaption",
        "dl",
        "dt",
        "dd",
        "address",
        "details",
        "summary",
        "body",
        "ul",
        "ol",
    }
)

_VOID = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


class _Node:
    """一个元素或一段文字（文字节点的 ``tag`` 是 None）。"""

    __slots__ = ("attrs", "children", "tag", "text")

    def __init__(
        self,
        tag: str | None = None,
        attrs: dict[str, str | None] | None = None,
        text: str | None = None,
    ) -> None:
        self.tag = tag
        self.attrs = attrs or {}
        self.text = text
        self.children: list[_Node] = []


class _Builder(HTMLParser):
    """标准库流式解析器 + 一层最小建树（原件用 ``x/net/html`` 的树；这里只建够用的那点）。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("#document")
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag, dict(attrs))
        self._stack[-1].children.append(node)
        if tag not in _VOID:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._stack[-1].children.append(_Node(tag, dict(attrs)))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self._stack[-1].children.append(_Node(text=data))


def _text_of(node: _Node) -> str:
    """节点下全部文字拼起来（标题用）。"""
    if node.tag is None:
        return node.text or ""
    return "".join(_text_of(child) for child in node.children)


class _Writer:
    """原件 ``mdWriter`` 的逐条搬运。

    ``space`` 是「欠一个空格」，``tight`` 是「刚写过前缀，首词不加空格」。
    """

    def __init__(self, base: str) -> None:
        self.base = base
        self._buf = ""
        self.title = ""
        self.pre = 0
        self.space = False
        self.tight = False
        self.lists: list[int] = []

    # ------------------------------------------------------------ 底层

    def at_line_start(self) -> bool:
        return not self._buf or self._buf.endswith("\n")

    def newline(self, count: int) -> None:
        self.tight = False
        have = 0
        if self._buf:
            for char in reversed(self._buf):
                if char != "\n":
                    break
                have += 1
        else:
            have = count
        if have < count:
            self._buf += "\n" * (count - have)
        self.space = False

    def words(self, text: str) -> None:
        if self.pre:
            self._buf += text
            return
        lead = bool(text) and text[0].isspace()
        trail = bool(text) and text[-1].isspace()
        fields = text.split()
        if not fields:
            if lead:
                self.space = True
            return
        if (lead or self.space) and not self.at_line_start() and not self.tight:
            self._buf += " "
        self.tight = False
        self._buf += " ".join(fields)
        self.space = trail

    def kids(self, node: _Node) -> None:
        for child in node.children:
            self.walk(child)

    def done(self) -> str:
        """收尾（``:458-479``）：行尾空白裁掉、``-`` / ``>`` 空壳行清空、
        连续空行压成一行、末尾 TrimSpace。
        """
        out: list[str] = []
        blank = 0
        for line in self._buf.split("\n"):
            line = line.rstrip(" \t")
            if line.strip() in ("-", ">"):
                line = ""
            if line:
                blank = 0
            else:
                blank += 1
                if blank > 1:
                    continue
            out.append(line)
        return "\n".join(out).strip()

    # ------------------------------------------------------------ 走树

    def walk(self, node: _Node) -> None:
        if node.tag is None:
            if node.text:
                self.words(node.text)
            return
        tag = node.tag
        if tag == "#document":
            self.kids(node)
            return
        if tag == "title":
            if not self.title:
                self.title = _text_of(node)
            return
        if tag == "head":
            for child in node.children:
                if child.tag == "title":
                    self.walk(child)
            return
        if tag in _MD_SKIP or "hidden" in node.attrs or node.attrs.get("aria-hidden") == "true":
            return
        if tag == "br":
            self._buf += "\n"
            self.space = False
            return
        if tag == "hr":
            self.newline(2)
            self._buf += "---"
            self.newline(2)
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.newline(2)
            self._buf += "#" * int(tag[1]) + " "
            self.tight = True
            self.kids(node)
            self.newline(2)
            return
        if tag == "li":
            self.newline(1)
            self._buf += "  " * max(len(self.lists) - 1, 0)
            if self.lists and self.lists[-1] > 0:
                self._buf += f"{self.lists[-1]}. "
                self.lists[-1] += 1
            else:
                self._buf += "- "
            self.tight = True
            self.kids(node)
            self.newline(1)
            return
        if tag in ("ul", "ol"):
            self.lists.append(1 if tag == "ol" else 0)
            self.newline(1)
            self.kids(node)
            self.lists.pop()
            self.newline(1)
            return
        if tag == "pre":
            self.newline(2)
            self._buf += "```\n"
            self.pre += 1
            self.kids(node)
            self.pre -= 1
            self.newline(1)
            self._buf += "```"
            self.newline(2)
            return
        if tag == "code":
            if self.pre:
                self.kids(node)
                return
            if self.space and not self.at_line_start():
                self._buf += " "
            self.space = False
            self._buf += "`"
            self.kids(node)
            self._buf += "`"
            return
        if tag in ("td", "th"):
            if not self.at_line_start():
                self._buf += " | "
            self.space = False
            self.kids(node)
            return
        if tag == "a":
            self._anchor(node)
            return
        if tag == "img":
            alt = (node.attrs.get("alt") or "").strip()
            if alt:
                self.words(" " + alt + " ")
            return
        if tag in _MD_BLOCK:
            self.newline(2)
            if tag == "blockquote":
                self._buf += "> "
            self.kids(node)
            self.newline(2)
            return
        self.kids(node)

    def _anchor(self, node: _Node) -> None:
        """``a``（``:413-439``）：只认 http(s) 的绝对化，``#`` 与 ``pre`` 内只写文字，
        纯图标链接整段丢。
        """
        href = (node.attrs.get("href") or "").strip()
        link = "" if not href or href.startswith("#") else _absolute(href, self.base)
        if not link or self.pre:
            self.kids(node)
            return
        if self.space and not self.at_line_start():
            self._buf += " "
        self.space = False
        start = len(self._buf)
        self._buf += "["
        self.tight = True
        self.kids(node)
        self.tight = False
        if len(self._buf) == start + 1:  # 只有一个「[」⇒ 图标链接，整段丢
            self._buf = self._buf[:start]
            return
        self._buf += "](" + link + ")"


def html_to_markdown(html: str, base: str) -> tuple[str, str]:
    """``(title, markdown)``（原件 ``htmlText``，``:230-234``）。"""
    builder = _Builder()
    builder.feed(html)
    builder.close()
    writer = _Writer(base)
    writer.walk(builder.root)
    return " ".join(writer.title.split()), writer.done()


# ================================================================ URL 小工具（不引 urllib）

def _split_scheme(url: str) -> tuple[str, str]:
    """``(小写 scheme, 其余)``；没有 scheme 就回 ``("", url)``。"""
    for index, char in enumerate(url):
        if char == ":":
            head = url[:index]
            if head and head[0].isalpha() and all(c.isalnum() or c in "+-." for c in head):
                return head.lower(), url[index + 1 :]
            return "", url
        if char in "/?#":
            break
    return "", url


def _parse_url(url: str) -> tuple[str, str, str]:
    """``(scheme, authority, path)``；不是 ``scheme://...`` 的形状就回空 scheme。"""
    scheme, rest = _split_scheme(url)
    if not scheme or not rest.startswith("//"):
        return "", "", ""
    rest = rest[2:]
    cut = len(rest)
    for marker in "/?#":
        found = rest.find(marker)
        if found != -1:
            cut = min(cut, found)
    authority = rest[:cut]
    tail = rest[cut:]
    if not tail.startswith("/"):
        tail = "/" + tail
    return scheme, authority, tail


def _host_of(authority: str) -> str:
    """``authority`` 里的主机名（去 userinfo、去端口、IPv6 去方括号）。"""
    host = authority.rpartition("@")[2]
    if host.startswith("["):
        end = host.find("]")
        return host[1:end] if end != -1 else host
    return host.partition(":")[0]


def _strip_dots(path: str) -> str:
    """消掉 ``.`` / ``..`` 段（够用即止：只处理路径部分）。"""
    cut = len(path)
    for marker in "?#":
        found = path.find(marker)
        if found != -1:
            cut = min(cut, found)
    body, tail = path[:cut], path[cut:]
    parts: list[str] = []
    for part in body.split("/"):
        if part == ".":
            continue
        if part == "..":
            if len(parts) > 1:
                parts.pop()
            continue
        parts.append(part)
    joined = "/".join(parts)
    if body.startswith("/") and not joined.startswith("/"):
        joined = "/" + joined
    return joined + tail


def _absolute(href: str, base: str) -> str:
    """把 ``href`` 按 ``base`` 解析成绝对 URL；scheme 不是 http(s) 就回空串。

    原件用 ``base.Parse`` 再查 scheme（``:420-434``）。
    """
    href = href.strip()
    if not href:
        return ""
    scheme, _ = _split_scheme(href)
    if scheme:
        return href if scheme in ("http", "https") else ""
    base_scheme, authority, path = _parse_url(base)
    if base_scheme not in ("http", "https") or not authority:
        return ""
    if href.startswith("//"):
        return base_scheme + ":" + href
    if href.startswith("/"):
        return f"{base_scheme}://{authority}{_strip_dots(href)}"
    if href.startswith("?"):
        return f"{base_scheme}://{authority}{path}{href}"
    directory = path[: path.rfind("/") + 1]
    return f"{base_scheme}://{authority}{_strip_dots(directory + href)}"


# ================================================================ 字符窗口（判据 4）


def split_part(
    final_url: str,
    title: str,
    text: str,
    offset: int = 0,
    max_chars: int = 0,
) -> str:
    """``URL:`` / ``Title:`` 两行头 + 从 ``offset`` 起最多 ``limit`` 个字符。

    原件是 ``:100-122`` 的 ``fetchPart``。
    """
    limit = max_chars if max_chars > 0 else WEB_FETCH_CHARS
    limit = min(limit, WEB_FETCH_MAX_CHARS)
    # 按 rune 切，不按字节切：Go 的 []rune(text) 与 Python 的 str 下标是同一个单位（码位）。
    runes = list(text)
    head = "URL: " + final_url + "\n"
    if title:
        head += "Title: " + title + "\n"
    head += "\n"
    if offset >= len(runes):
        if not runes:
            return head + "(the page has no text)"
        return head + f"(the page has {len(runes)} characters, none from offset {offset})"
    end = min(offset + limit, len(runes))
    body = "".join(runes[offset:end])
    if end < len(runes):
        body += (
            f"\n\n[{len(runes) - end} more characters: "
            f"call web_fetch with offset={end} to read on]"
        )
    return head + body


# ================================================================ 取页编排（判据 5）


def _header(headers: Mapping[str, str], name: str) -> str:
    """大小写不敏感地取一个响应头。"""
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return ""


def _media_type(content_type: str) -> str:
    return content_type.split(";")[0].strip().lower()


def _status_line(status: int) -> str:
    """``404 Not Found`` 这个形状（原件的 ``resp.Status``）。"""
    try:
        phrase = HTTPStatus(status).phrase
    except ValueError:
        phrase = ""
    return f"{status} {phrase}".strip()


def _sniff(body: bytes) -> str:
    """content-type 缺失时的粗判 —— 只管 html 与「其它」。

    原件的 ``http.DetectContentType`` 没有逐字移植（它认几十种类型，这里只认 html）。
    """
    head = body[:64].lstrip().lower()
    if head.startswith((b"<!doctype html", b"<html", b"<head", b"<body")):
        return "text/html"
    return "application/octet-stream"


def fetch_page(
    fetch: Fetch,
    resolve: Resolve,
    url: str,
    *,
    max_chars: int = 0,
    offset: int = 0,
) -> str:
    """取一页并切成窗口。``fetch(url, headers, timeout, addresses)`` /
    ``resolve(host)`` 都是注入的。

    每一跳都把 ``resolve`` 回来的**每一个**地址过一遍 ``netguard.public()``：有一个不公共就拒（而且
    那一跳不会发出去）。重定向自己跟，至多 ``WEB_FETCH_REDIRECTS`` 跳。读回字节按 ``WEB_FETCH_READ``
    截断 —— 截断**不是错误**（原件的 ``io.LimitReader`` 就是这个口径）。
    """
    raw = url.strip()
    if not raw:
        raise FetchError("web_fetch needs a url")
    scheme, authority, _ = _parse_url(raw)
    if scheme not in ("http", "https") or not authority:
        raise FetchError(ONLY_HTTP + raw)
    if offset < 0:
        raise FetchError("offset can't be negative")

    current = raw
    redirects = 0
    while True:
        scheme, authority, _ = _parse_url(current)
        if scheme not in ("http", "https") or not authority:
            raise FetchError(ONLY_HTTP + current)
        answers = tuple(resolve(_host_of(authority)))
        if not answers:
            raise FetchError(NO_ANSWER)
        if not all(public(address) for address in answers):
            raise FetchError(PRIVATE_MESSAGE)
        status, headers, body = fetch(current, dict(HEADERS), WEB_FETCH_TIMEOUT_S, answers)
        body = body[:WEB_FETCH_READ]
        location = _header(headers, "location")
        if location and 300 <= status < 400:
            redirects += 1
            if redirects > WEB_FETCH_REDIRECTS:
                raise FetchError(f"it redirects more than {WEB_FETCH_REDIRECTS} times")
            current = _absolute(location, current)
            if not current:
                raise FetchError(ONLY_HTTP + location)
            continue
        content_type = _header(headers, "content-type") or _sniff(body)
        if status >= 400:
            raise FetchError("the site answered " + _status_line(status))
        media = _media_type(content_type)
        kind = kind_of(media)
        if not kind:
            raise FetchError(f"it is {media}, not a page of text")
        title, text = to_text(body, content_type, kind, current)
        return split_part(current, title, text, offset, max_chars)
