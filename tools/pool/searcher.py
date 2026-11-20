"""searcher 的选择与「让位」：三种失败要分开（卡 A385 · F57）。

magpie `internal/gateway/search.go` 的**判据层**，pool 版。六个纯函数、**不接线**：
不读盘、不读钟、不出网、不 print。真正去问模型的那一句由调用方注入（`ask` /
`search_api`），和 `tools/pool/gateway.py:613-614` 的 `forward` 同一个体例：
干跑时给桩，整条链路照走不误、一个字节都不出网。

## 为什么有它

magpie 解决的是一个**静默失效**问题：把「搜了但没找到」「压根没搜」「报错」三件事混成一团，
搜索就会在没人发现的情况下退化成「模型凭记忆回答」。本仓今天**完全没有** searcher 这个概念
（卡规格缺口 1 的实测），所以这套判据先在纯函数里立住，接线另开卡。

## 四件事，四种读数

| 要回答 | 这里 | 原件 |
|---|---|---|
| 谁被点了名、它为什么不能用 | `chosen` + `rank` | `chosenSearcher` :387-424、`searchRank`
  :300-327 |
| 这一轮按什么序问、问几个 | `turn` | `Searchers` :426-458 + `modelSearch` :768-795 |
| 这一次到底搜没搜 | `verdict` | `searchWith` :950-1002 |
| 让给了谁、算不算静默 | `instead` + `search` | `searchingInstead` :874-897、`modelSearch`
  :731-797 |

## 移植口径（与原件逐条对照）

- **四值 why 逐字照抄**（:379-385）：`gone`（没有这个 provider 了）/ `off`（关了、
  或登出了）/ `cant`（它自己不会搜）/ `nomodel`（它一个能搜的模型都列不出来）。
  点名的**模型**已下线 ⇒ 退到它的小模型，**不报 gone**（:387-392 注释）。
- **`rank` 是静态表**，十行照 :300-327；`MANUAL_RELAY_RANK = 6` 排在所有
  机器自己挑的之后，**只在被点名时可问**（:329-331 注释）。
- **三种结局照 :992-997 逐字**：说了空话、或者一个页面都没找到又没在话里写地址 ⇒ 没找到；
  但**它有没有真去搜**是另一问（`server_tool_use` / `web_search_tool_result` 才算搜过，:965-968）。
- **让位**（:768-795）：`len(tried) >= 3` 停、同一个 provider 不重复问、**点名的那个一个都不让位**
  （:753-761 的文案逐字带 `PICKED_LONE`）。

## 与原件**不同**的三处（都是判断，不是遗漏）

1. **`searcherSpent` 没有移植**（卡规格「未坐实项 3」）：它要 magpie 自己的额度读数
   （:769 / :786），本仓对应物是 `pool_quota.status` 的四态，两者能不能一一对上**未坐实**。
   这里只留 autoSearcher 的形状：**有额度的排在全耗尽的之前**（:364-374 的 `bestReady`），
   由 `ProviderView.ready` 表达 —— 那是**调用方给的读数**，本模块不猜。
2. **`ProviderView` 是「读法」，不是第二份名单**：谁自己会搜、谁只有被点名才搜、
   哪些模型可搜，magpie 分散在 `searchesItself`（:101-125）、`partSearcher`（:234-247）、
   `remoteSearchesAny`（`search_remote.go:49`）、`searchableModel`
   （`search_remote.go:58`）里算。本模块**不复制那张 host 表**（那是 A372 的 vendor 表的邻居），
   只读传进来的事实；`searchable` 空元组的意思就是「全部可搜」。
3. **`verdict` 多认一种块**：`type == "error"` 的块（原件在 :941-950 由 HTTP 层
   判，不在这里）。本模块拿不到状态码，就把它当**已经判好的失败**接住，`why` 用块里的
   `message`。

## 与卡规格字面的一处出入（如实记）

卡规格判据 3 把 :961 的 **citation 过滤** 与 :999-1000 的 `Sources:` **上限**写在一句里，
读起来像「sources 收的是 citation」。原件里不是：`sources` 只来自
`web_search_tool_result` 的每条结果（:972-986，行形 `- title — url`），citation 只进
`quoted`（:961），用来给 `Hit.Cited` 配音（:988-990），**不影响** `Sources:` 段。
这里按**原件**走：判据 3(e) 的 21/20 条上限用**结果条目**钉；citation 的三条过滤（URL 非空、
CitedText 非空、同 URL 只认第一次）单独钉在 `Failure.found[i].cited` 上。两处都有钉子。

作者：T-AG673（卡 A385）
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

#: 读法可以按 id 给（`Mapping`），也可以直接给一串（`Sequence`，同一 id 只认第一条）。
Views = "Mapping[str, ProviderView] | Sequence[ProviderView]"

#: 一轮最多问几个 searcher（原件 `searchersInTurn = 3`，:720-722）。
SEARCHERS_IN_TURN = 3

#: 只有人在 Settings 里点得到的名次（原件 `manualRelayRank = 6`，:329-331）。
MANUAL_RELAY_RANK = 6

#: 四值 `why`，逐字照 :379-385。**四个值一个都不能并**。
WHY_GONE = "gone"  # no such provider any more
WHY_OFF = "off"  # turned off, or signed out
WHY_CANT = "cant"  # it can't search the web by itself
WHY_NONE_OF = "nomodel"  # it lists no model to search with
WHY: tuple[str, ...] = (WHY_GONE, WHY_OFF, WHY_CANT, WHY_NONE_OF)

#: 三种结局 + 一种「接住的失败」（原件 :992-997 三种，error 见模块 docstring 第 3 条）。
KIND_OK = "ok"
KIND_FOUND_NOTHING = "found_nothing"
KIND_NOT_SEARCHED = "not_searched"
KIND_ERROR = "error"

#: 两个哨兵的错误文本，逐字照 :899 / :906（`errNotSearched` 包着 `errFoundNothing`）。
FOUND_NOTHING_TEXT = "found nothing"
NOT_SEARCHED_TEXT = "answered without searching the web: found nothing"

#: 一个能搜的都没有、也没有 Search API（:709 逐字）。
NO_SEARCHER = "no provider that can search the web, nor a search API, is set up in magpie"
#: 点名的那个失败时挂的尾巴（:759 逐字，含 `›`）。
PICKED_LONE = (
    "(the searcher picked in Settings \u203a Web search: no other provider searches in its place)"
)

#: `Sources:` 段的头与上限（:999-1000：**1 到 20 条**才追加）。
SOURCES_HEAD = "\n\nSources:\n"
SOURCES_MOST = 20

#: `Result.by` 的三个取值：谁答的这次搜索。
BY_SEARCHER = "searcher"
BY_SEARCH_API = "search_api"
BY_NONE = "none"


@dataclass(frozen=True)
class ProviderView:
    """一个 provider 的**读法**：magpie 在别处算好的事实，本模块只读、不重算。

    每个字段都对应原件里一个判据函数（模块 docstring「与原件不同的第 2 条」）：

    - `agent`：登录的是哪个 agent（`claude` / `codex` / `copilot` /
      `gemini` / `antigravity`），空串 = 没有账号。
    - `searches_itself`：它在**哪几个协议**上自己会搜（`anthropic` /
      `responses` / `chat`）—— 原件 `searchesItself` :101-125 的结论。
    - `part_searcher` / `searches_alone`：只有那几个模型自己会搜（:234-247、:223-231）。
    - `google`：Google 登录（:127-130）；`remote_searches`：另一个 magpie 会替自己的模型搜
      （`search_remote.go:49`）。
    - `relay` / `service`：说了会搜的 relay、Kimi Code 那种「靠服务搜、没有模型」的，
      **都只能被点名**（:333-346）。
    - `models`：它列出来的模型；`searchable`：其中**真的可搜**的那些
      （原件 `searchableModel`，`search_remote.go:58`）；空元组 = 全部可搜。
    - `small`：没点名时用它搜的那个小模型（:620-644）；`ready`：它还有额度
      （:561-583 的 `smallReadyOf`）—— 有额度的排在全耗尽的之前（:364-374）。
    """

    id: str
    on: bool = True
    agent: str = ""
    searches_itself: tuple[str, ...] = ()
    part_searcher: bool = False
    searches_alone: tuple[str, ...] = ()
    google: bool = False
    remote_searches: bool = False
    relay: bool = False
    service: bool = False
    models: tuple[str, ...] = ()
    searchable: tuple[str, ...] = ()
    small: str = ""
    ready: bool = True


@dataclass(frozen=True)
class Choice:
    """Settings 点了名的那个：`picked`（`None` = 没点名）、用哪个模型、为什么不能用。"""

    picked: str | None
    model: str
    why: str


@dataclass(frozen=True)
class Hit:
    """搜到的一页：标题、地址、以及 citation 引的它那一段（:988-990）。"""

    title: str
    url: str
    cited: str = ""


@dataclass
class Failure:
    """这一次问出来的结局。

    `kind` 走四种；`nothing_found` 与 `not_searched` 是**两个互斥的结构体字段**
    （:830 / :890 逐字 `!f.NotSearched && errors.Is(err, errFoundNothing)`），而
    `is_found_nothing()` 才是**语义包含**（`errNotSearched` 包着 `errFoundNothing`）。
    两问两答，缺一个就复现不了那个歧义（卡规格判据 3 的星号段）。
    """

    kind: str
    why: str = ""
    sources: tuple[str, ...] = ()
    nothing_found: bool = False
    not_searched: bool = False
    said: str = ""
    found: tuple[Hit, ...] = ()

    def is_found_nothing(self) -> bool:
        """它到底找没找到：`not_searched` 也算没找到（:906 注释 It is found nothing too.）。"""
        return self.not_searched or self.nothing_found


@dataclass(frozen=True)
class Result:
    """一次搜索的去向：问过谁（按序）、结局、让位账、以及给调用方的错误串。"""

    kind: str
    tried: tuple[str, ...] = ()
    failure: Failure | None = None
    instead: Mapping[str, object] | None = None
    said: str = ""
    error: str = ""
    by: str = BY_NONE


def rank(view: ProviderView) -> int:
    """它排第几（原件 `searchRank`，:300-327）；`-1` = 机器自己绝不挑它。

    十行照抄：claude 0、codex 1、copilot -1（只替自己的模型搜）、Anthropic 2、Responses 3、
    Chat 4、`partSearcher && searchesAlone` 4、Google 登录 5、远端会搜 5、兜底 -1。
    relay 与 service 在这里**也是 -1** —— 它们只在 `chosen` / `turn` 那一层按
    `MANUAL_RELAY_RANK` 处理。
    """
    if view.agent == "claude":
        return 0
    if view.agent == "codex":
        return 1
    if view.agent == "copilot":
        return -1
    if "anthropic" in view.searches_itself:
        return 2
    if "responses" in view.searches_itself:
        return 3
    if "chat" in view.searches_itself:
        return 4
    if view.part_searcher and any(m in view.searches_alone for m in view.models):
        return 4
    if view.google or view.remote_searches:
        return 5
    return -1


def _named_rank(view: ProviderView) -> tuple[int, bool]:
    """`rank` 的「点名版」：relay / service 并列 6，且标成只能被点名（:333-346）。"""
    r = rank(view)
    if r >= 0:
        return r, False
    if view.relay or view.service:
        return MANUAL_RELAY_RANK, True
    return -1, False


def _searchable(view: ProviderView, model: str) -> bool:
    """这个模型能不能拿去搜（原件 `searchableModel`，`search_remote.go:58`）。"""
    return not view.searchable or model in view.searchable


def _label(provider: str, model: str) -> str:
    """`provider` 或 `provider/model`（原件 :881-884 的 Instead 形状）。"""
    return provider if not model else f"{provider}/{model}"


def chosen(picker: str, providers: Mapping[str, ProviderView]) -> Choice:
    """Settings 点了谁、能不能用（原件 `chosenSearcher`，:387-424）。

    `picker` 为空或 off ⇒ `Choice(None, "", "")`；点名的**模型**已不在它的模型表
    ⇒ 退到它的小模型（:387-392），不报 gone。四值 why 的顺序照原件：先 gone（连 provider 都没了），
    再 off（关着）、cant（不会搜）、nomodel（一个能搜的模型都没有）。
    """
    v = picker.strip()
    if v == "" or v == "off":
        return Choice(None, "", "")
    pid, _, model = v.partition("/")
    view = providers.get(pid)
    if view is None:
        return Choice(None, "", WHY_GONE)
    r, _ = _named_rank(view)
    if not view.on:
        return Choice(pid, "", WHY_OFF)
    if r < 0:
        return Choice(pid, "", WHY_CANT)
    if view.service:
        return Choice(pid, "", "")
    if model and model in view.models and _searchable(view, model):
        return Choice(pid, model, "")
    if view.small:
        return Choice(pid, view.small, "")
    if view.models:
        return Choice(pid, view.models[0], "")
    return Choice(pid, "", WHY_NONE_OF)


def _view_list(views: Views) -> list[ProviderView]:
    """把传进来的读法摊成一串，**同一个 provider 只留第一次出现的那条**。

    原件里一个 provider 可能列多个模型（:441-448），而一轮里同一个 provider 只问一次
    （:779 `slices.ContainsFunc(tried, ...)`）。这里先摊平再去重，判据 2(d) 与 4(d) 才对得上。
    """
    items = list(views.values()) if isinstance(views, Mapping) else list(views)
    seen: set[str] = set()
    out: list[ProviderView] = []
    for view in items:
        if view.id in seen:
            continue
        seen.add(view.id)
        out.append(view)
    return out


def _plan(choice: Choice, views: Views) -> list[tuple[str, str]]:
    """这一轮要问的 (provider, model)，按问的先后。

    点名的且能用 ⇒ **只它一个**（:753-761：点名的 give way to none）；否则机器自己挑：
    有额度的排在全耗尽的之前（:364-374）、同额度按 `rank` 升序、并列按传进来的顺序。
    relay / service 不进这条链（原件 :768-772 逐字
    `if c.ManualOnly || c.Small == "" { continue }`）。
    """
    if choice.why == "" and choice.picked is not None:
        return [(choice.picked, choice.model)]
    tail: list[tuple[int, int, int, str, str]] = []
    for i, view in enumerate(_view_list(views)):
        if not view.on or view.relay or view.service or not view.small:
            continue
        r = rank(view)
        if r < 0:
            continue
        tail.append((0 if view.ready else 1, r, i, view.id, view.small))
    tail.sort()
    return [(pid, small) for _, _, _, pid, small in tail]


def turn(choice: Choice, views: Views) -> list[str]:
    """这一轮按序问谁（最多 `SEARCHERS_IN_TURN` 个，同一个 provider 只出现一次）。

    被点名的 relay / service **会出现**，而且就是这一轮的**最后一个** —— 点名的 give way to none
    （:753-761），链条到它就停，所以它同时是第一个也是最后一个；没被点名时它**绝不出现**。
    """
    return [_label(pid, model) for pid, model in _plan(choice, views)][:SEARCHERS_IN_TURN]


def verdict(blocks: Sequence[Mapping]) -> Failure:
    """看这一次的回复：搜没搜、找没找到、引了哪几页（原件 `searchWith`，:950-1002）。

    `searched` 只在出现 `server_tool_use`（:965-966）或 `web_search_tool_result`
    （:967-968）块时置真 —— 这是「压根没搜」与「搜了没找到」唯一的判据。`sources` 只收结果条目里
    URL 非空的那些，行形 `- title — url`；`Sources:` 段只在 1 到 20 条时追加（:999-1000）。
    citation 的三条过滤照 :961（URL 非空、CitedText 非空、同 URL 只认第一次），落进 `Hit.cited`。
    """
    text: list[str] = []
    sources: list[str] = []
    hits: list[Hit] = []
    quoted: dict[str, str] = {}
    searched = False
    for block in blocks:
        if not isinstance(block, Mapping):
            continue
        kind = block.get("type")
        if kind == KIND_ERROR:
            return Failure(
                kind=KIND_ERROR,
                why=str(block.get("message") or block.get("error") or ""),
            )
        if kind == "text":
            text.append(str(block.get("text") or ""))
            for c in block.get("citations") or ():
                if not isinstance(c, Mapping):
                    continue
                url = str(c.get("url") or "")
                cited = str(c.get("cited_text") or "")
                if url and cited and url not in quoted:
                    quoted[url] = cited
        elif kind == "server_tool_use":
            searched = True
        elif kind == "web_search_tool_result":
            searched = True
            for raw in block.get("content") or ():
                if not isinstance(raw, Mapping):
                    continue
                url = str(raw.get("url") or "")
                if not url:
                    continue
                title = str(raw.get("title") or "")
                sources.append(f"- {title} \u2014 {url}")
                hits.append(Hit(title=title, url=url))
    found = tuple(Hit(title=h.title, url=h.url, cited=quoted.get(h.url, "")) for h in hits)
    said = "".join(text).strip()
    found_nothing = not found and "://" not in said
    if said == "" or found_nothing:
        f = Failure(
            kind=KIND_FOUND_NOTHING if searched else KIND_NOT_SEARCHED,
            why=FOUND_NOTHING_TEXT if searched else NOT_SEARCHED_TEXT,
            sources=tuple(sources),
            not_searched=not searched,
            found=found,
        )
        # 两个 bool 互斥（:830 / :890 逐字 `!f.NotSearched && errors.Is(err, errFoundNothing)`），
        # 所以这里先钉成 False，再只由 searched 打开 —— 别写成 not_searched or found_nothing。
        f.nothing_found = False
        if searched:
            f.nothing_found = True
        return f
    if 0 < len(sources) <= SOURCES_MOST:
        said += SOURCES_HEAD + "\n".join(sources)
    return Failure(kind=KIND_OK, said=said, sources=tuple(sources), found=found)


def instead(
    provider: str,
    model: str,
    failure: Failure,
    *,
    picked: bool = False,
) -> dict[str, object]:
    """让位账，五键齐（原件 `searchingInstead`，:874-897）。

    `why` **只在既不是没找到、也不是没搜时才填**（:891-894），而且要把
    `<instead>: ` 这个前缀去掉（原件的 `strings.TrimPrefix`）。
    """
    label = _label(provider, model)
    not_searched = bool(failure.not_searched)
    nothing_found = not not_searched and bool(failure.nothing_found)
    why = ""
    if not nothing_found and not not_searched:
        why = failure.why
        head = label + ": "
        if why.startswith(head):
            why = why[len(head) :]
    return {
        "instead": label,
        "picked": picked,
        "nothing_found": nothing_found,
        "not_searched": not_searched,
        "why": why,
    }


def search(
    choice: Choice,
    views: Views,
    ask: Callable[[str, str], Failure],
    *,
    picker: str = "",
    search_api: Callable[[], Failure] | None = None,
) -> Result:
    """问出去、该让位就让位（原件 `modelSearch`，:731-797；off 分支照 `webSearch` :666-673）。

    `ask(provider, model) -> Failure` 是**注入的**：本模块自己不出去。规则三条照原件：
    最多问 `SEARCHERS_IN_TURN` 个（:776）、同一个 provider 不重复问（:779）、点名的那个
    **只问一次**且失败原样回、错误串带 `PICKED_LONE`（:753-761）。

    `picker` 只用来看 off：`chosen("off", ...)` 与 `chosen("", ...)` 返回值
    一模一样，这件事在 `Choice` 里看不出来，所以得单独给。off ⇒ **provider 搜索整个关掉，
    但 Search API 那条路照跑**（:668-673）；连 Search API 都没有才回 `NO_SEARCHER`（:709）。
    """
    if picker.strip() == "off":
        if search_api is None:
            return Result(kind=KIND_ERROR, error=NO_SEARCHER)
        f = search_api()
        return Result(kind=f.kind, failure=f, said=f.said, by=BY_SEARCH_API)

    named = choice.why == "" and choice.picked is not None
    plan = _plan(choice, views)
    if not plan:
        return Result(kind=KIND_ERROR, error=NO_SEARCHER)

    tried: list[str] = []
    errors: list[str] = []
    ledger: dict[str, object] | None = None
    first: tuple[str, str, Failure] | None = None
    last = Failure(kind=KIND_ERROR, why=NO_SEARCHER)
    for pid, model in plan:
        if len(tried) >= SEARCHERS_IN_TURN:
            break
        if any(t.split("/", 1)[0] == pid for t in tried):
            continue
        if len(tried) == 1 and first is not None and ledger is None:
            ledger = instead(first[0], first[1], first[2], picked=False)
        tried.append(_label(pid, model))
        f = ask(pid, model)
        last = f
        if f.kind == KIND_OK:
            return Result(
                kind=KIND_OK,
                tried=tuple(tried),
                failure=f,
                instead=ledger,
                said=f.said,
                by=BY_SEARCHER,
            )
        errors.append(f"{_label(pid, model)}: {f.why}" if f.why else _label(pid, model))
        if len(tried) == 1:
            first = (pid, model, f)

    if search_api is not None:
        f = search_api()
        if f.kind == KIND_OK:
            return Result(
                kind=KIND_OK,
                tried=tuple(tried),
                failure=f,
                instead=ledger,
                said=f.said,
                by=BY_SEARCH_API,
            )
        errors.append(f"search_api: {f.why}" if f.why else "search_api")

    error = "\n".join(errors)
    if named and error:
        error = f"{error} {PICKED_LONE}"
    return Result(
        kind=last.kind,
        tried=tuple(tried),
        failure=first[2] if first is not None else None,
        instead=ledger,
        error=error,
        by=BY_SEARCHER,
    )
