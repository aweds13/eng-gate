# 卡 A374：`web_fetch` —— 只读公共地址、按 charset 转 Markdown、按字符窗口分段

> 台账号 `T-AG662`｜分区 A（magpie 移植 / 号池 pool）｜树 `.wt/A374`｜层 判据层（纯函数 + 钉子，**不接 MCP 工具面、不接线生产**）｜基准 `7a4cc513`（立卡时主树 HEAD，2026-11-19 23:50 实读）｜depends A338、A348、A365、A367、A370、A371、A372
> depends 说明：**A338**（done，`tools/pool/limits_check.py`）是本仓唯一「限额要在派活之前拦」的判据面（模块 docstring 逐字「移植 magpie `budget.Reserve` / `Refusal`」）—— 本卡只**读**它，不改一个字节。**A348**（done，`tools/pool/callers.py`）是调用方名册：`:61` 逐字 `_KNOWN_KEYS = frozenset({"label", "off", "models", "accounts"})`、`:69` 的 `Caller` docstring 逐字「一个调用方：**恰五个字段**，没有一个跟凭据有关」—— 本卡靠它说明「按调用方 key 预留限额」在本仓**无处可落**（缺口 4）。**A365**（done，`tools/pool/mcp_http.py`）是 MCP 传输层，本卡**不接**它（理由见缺口 5），列它是让「不接」有据可查。**A367 / A370 / A371 / A372**（均 pending，且 `docs/workbacklog.toml` 里这四张的 `files` 都含 `docs/subsystems/pool/modules.toml`）—— 本卡 files 也含那个文件，而 `tools/pool/plan.py:170` 的 `files_intersect()` 是精确字符串相交、`:233` `dependency_path()` 与 `:257` `validate()` 的冲突类 ① 要求「同域两卡之间必须有依赖路径」才允许共存 ⇒ 这四张必须进 depends，否则落卡即拒单。
> 基准说明：起草时主树 HEAD = `35930ab1`（`git rev-parse --short HEAD` 实读，2026-11-19 20:07:10 +0800，提交语「chore(ledger): 卡 A367 的域加上 docs/subsystems/pool/modules.toml（新增 .toml 必须登记职责）」）。本文每条 文件:行号 都是本轮 `grep -n` / `sed -n` 实读；magpie 原件行号逐条核过（`_ext/magpie-main/`）。本仓行号在起草期间随 E143（`466a2578`）与 A367（`35930ab1`）两次前移，已按 `35930ab1` 重核。落地前按当时 HEAD 再核一次。
> 依据：`gates/diag/_magpie_scope.md:66` 逐字 `| F58 | web_fetch：只读公共地址、按 charset 转 Markdown、按字符窗口分段 | PORT | no | tools/ 下无 web_fetch 实现（现有 markdown 命中是 GUI/serve 的渲染代码） |` + `_ext/_magpie_features.md:496-502` + magpie 原件 `internal/gateway/search_fetch.go`（479 行，逐行读过）、`internal/netguard/netguard.go`（97 行，全文读过）、`internal/gateway/image_fetch_guard.go`（公共地址 Guard 真正拦截处，逐行读过）。

## 前情

magpie 的 `web_fetch` 不是一个「下载网页」的小工具，它是一条把「用户给的 URL」变成「可交给模型读的文本」的**判据链**。features 文档 `_ext/_magpie_features.md:496-502` 逐字：

> ## F58 `web_fetch`：只读公共地址、按 charset 转 Markdown、按字符窗口分段
>
> - 解决：没有 fetch 工具的 agent（Claude Desktop 之类）也要能读网页，且不能被诱导去打内网。
> - 入口：MCP 工具 `web_fetch`（挂在 `/mcp/magpie/web-search` 上）；参数 `max_chars`（默认 **20000**，至多 **100000**）与 `offset`。
> - 判据/结构（已核 `internal/netguard/netguard.go` 存在、97 行）：只公共地址，**每个解析地址都查并钉住**，至多 **5** 次重定向各自同样检查，不论请求来自何处；最多读 **30 秒**、**5 MiB**；HTML 按 charset 解码后给 Markdown（标题、列表、链接绝对化、代码；script/style/隐藏元素丢弃），其它类型是工具错误，状态 **400 及以上**也是；每次调用像搜索一样预留调用方 key 的限额；fake-IP resolver（Clash TUN / Surge / Loon 在 `198.18.0.0/15` 答）是唯一放过的形状（#2593）。

原件里这件事被拆成**三层**，本卡只移植第 1 层与第 3 层（第 2 层的 socket 钉地址不移植，见未坐实项 3）：

| 层 | 原件 | 管什么 | 本卡 |
|---|---|---|---|
| 1. 判地址 | `internal/netguard/netguard.go` | 只说「这个 IP 在不在公网」，**不解析名字**（`:1-5` 包注释逐字 `It judges addresses only; each caller decides what to do with a name's answers (pin them, or hand a proxy the name).`） | 移植成 tools/pool/netguard.py 的 `public()` / `fake_ip()` / `loon_paired()` |
| 2. 真拦 | `internal/gateway/image_fetch_guard.go` 的 `publicClient` | 解析 → 每个地址都查 → 钉住第一个 → socket 连接时**再查一次** → 至多 5 次重定向 | 只移植「**每一跳都查**、至多 5 跳」的形状；socket 钉地址**不移植**（未坐实项 3） |
| 3. 取页与呈现 | `internal/gateway/search_fetch.go` | 30 秒 / 5 MiB / charset 解码 / HTML→Markdown / 按字符窗口分段 | 移植成 tools/pool/web_fetch.py（出网由**注入的** fetcher 承担） |

第三层的关键常量（`search_fetch.go:36-46` 逐字，缩进省略）：

```go
const fetchMCPTool = "web_fetch"
    webFetchTimeout  = 30 * time.Second
    webFetchRead     = 5 << 20
    webFetchChars    = 20000
    webFetchMaxChars = 100000
var webFetchClient = publicClient
```

按字符窗口分段（`search_fetch.go:100-122` 关键行逐字）：

```go
func fetchPart(final, title, text string, offset, limit int) string {
    b.WriteString("URL: " + final + "\n")
        b.WriteString("Title: " + title + "\n")
    runes := []rune(text)
            b.WriteString("(the page has no text)")
            fmt.Fprintf(&b, "(the page has %d characters, none from offset %d)", len(runes), offset)
    end := min(offset+limit, len(runes))
        fmt.Fprintf(&b, "[%d more characters: call web_fetch with offset=%d to read on]", len(runes)-end, end)
```

★ `runes := []rune(text)` 这一行是**整个分段逻辑的判据**：按 rune 切，不按字节切。中文页按字节切会切出半个字。

三种拒收（`search_fetch.go` 逐字）：`:73` `"web_fetch reads only http:// and https:// URLs, not " + raw`、`:76` `"offset can't be negative"`、`:183` `fmt.Errorf("it is %s, not a page of text", mt)`；状态码 `:174` `fmt.Sprintf("the site answered %s", resp.Status)`；私有地址 `:154` `"it is at a private address (this computer, its network, or a name that resolves to one), which web_fetch doesn't read"`。

地址判词（`netguard.go:46-68` 逐字）：

```go
func Public(a netip.Addr) bool {
    a = a.Unmap() // ::ffff:127.0.0.1 is 127.0.0.1
    if !a.IsValid() || a.IsLoopback() || a.IsPrivate() || a.IsUnspecified() ||
        a.IsLinkLocalUnicast() || a.IsLinkLocalMulticast() || a.IsInterfaceLocalMulticast() || a.IsMulticast() {
        return false
    }
    for _, n := range specialNets {
        if n.Contains(a) {
            return false
        }
    }
    if a.Is6() {
        b := a.As16()
        if nat64.Contains(a) {
            return Public(netip.AddrFrom4([4]byte{b[12], b[13], b[14], b[15]}))
        }
        if b[0] == 0x20 && b[1] == 0x02 {
            return Public(netip.AddrFrom4([4]byte{b[2], b[3], b[4], b[5]}))
        }
    }
    return true
}
```

`specialNets` 十四个前缀（`netguard.go:10-33`，连注释一起搬）：

| 前缀 | 原件注释 |
|---|---|
| `0.0.0.0/8` | `"this" network` |
| `100.64.0.0/10` | `CGNAT, Tailscale` |
| `192.0.0.0/24` | `IETF protocol assignments` |
| `192.0.2.0/24` | `documentation` |
| `198.18.0.0/15` | `benchmarking; a fake-IP resolver's (FakeIP)` |
| `198.51.100.0/24` | `documentation` |
| `203.0.113.0/24` | `documentation` |
| `240.0.0.0/4` | `reserved, broadcast` |
| `::/96` | `IPv4-compatible (deprecated)` |
| `100::/64` | `discard` |
| `2001::/32` | `Teredo` |
| `2001:db8::/32` | `documentation` |
| `fec0::/10` | `site-local (deprecated)` |
| `64:ff9b:1::/48` | `local-use NAT64` |

## 缺口（逐条带现场原文与 文件:行号）

### 缺口 1 · 本仓**完全没有** web_fetch —— 不是「有代码没接线」

基准 `35930ab1` 实测三组 grep（本轮真跑）：

```
$ grep -rn -e web_fetch -e webfetch -e webFetch tools/ scripts/ tests/ src/ --include=*.py --include=*.toml
(零命中)
$ grep -rn -e HTMLParser -e "html.parser" -e markdownify -e html2text -e BeautifulSoup tools/ scripts/ tests/ src/ --include=*.py
(零命中)
$ grep -rn -e ipaddress -e is_global -e is_private -e netguard -e getaddrinfo tools/ scripts/ --include=*.py
(零命中)
$ ls tools/pool/ | grep -E "fetch|guard"
(无)
```

⇒ **不是「有代码没接线」，是「完全没有」**。`tools/pool/` 48 个条目里没有任何一件能下载网页、判公共地址、或把 HTML 变成 Markdown。

### 缺口 2 · 最像的三件既有物都不是这个语义 —— 别拿来冒充

- `src/timeflow/core/lan.py:65` `def is_loopback(host: str | None) -> bool:` —— docstring 逐字「本机来源判定：`127.0.0.0/8` 与 `::1`（以及字面 `localhost`）。刻意**不**把 `0.0.0.0` 当本机：那是"监听所有网卡"的地址，不是来源地址。」它是**局域网配对门闸**（判「请求是不是本机来的」），方向与「目标地址是否公共」相反；`:82` 的 `local_addresses()` 才碰 `socket.getaddrinfo`，且只在 `src/` 里。
- `tools/pool/checkin.py:221` `def http_fetch(...) -> tuple[int, str]:` —— 它真的出网，但 `noqa: S310` 的理由逐字是「**端点来自能力表常量，不是用户输入**」（`:229`）。web_fetch 的 URL **恰恰来自用户/模型** ⇒ 这条理由**不成立**，本卡必须自己判公共地址。
- `tools/pool/gateway.py:827` `resp = urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 —— 端点来自 platforms.toml` —— 同上，端点固定。

### 缺口 3 · 本仓没有地址判词，而**标准库 ipaddress 判不了 magpie 的规则**

Python 3.14.6 实测读数（本轮真跑）：

| 地址 | `is_private` | `is_global` | magpie `Public()` 应给 |
|---|---|---|---|
| `100.64.0.1` | **False** | False | False（CGNAT） |
| `64:ff9b::7f00:1`（NAT64 里的 127.0.0.1） | **False** | **True** | False（递归判内嵌 v4） |
| `fec0::1`（deprecated site-local） | **False** | **True** | False（`fec0::/10`） |
| `198.18.0.1` | True | False | False（benchmarking / fake-IP） |
| `198.19.255.255` | True | False | False（`198.18.0.0/15` 的上界） |
| `192.0.2.5` | True | False | False（documentation） |
| `169.254.169.254` | True | False | False（link-local，云元数据） |
| `8.8.8.8` | False | True | True |
| `198.17.255.255` | False | True | True（`198.18.0.0/15` 边界外） |

⇒ **只用 `is_global` 会放过三类**：CGNAT `100.64.0.0/10`、NAT64 内嵌私网、`fec0::/10`。这就是为什么必须把 `specialNets` 十四个前缀 + NAT64/6to4 递归**照抄成表**，而不是写一句 `return ip.is_global`。

### 缺口 4 · 「每次调用像搜索一样预留调用方 key 的限额」在本仓**没有对应物**

- `tools/pool/callers.py:61` 逐字 `_KNOWN_KEYS = frozenset({"label", "off", "models", "accounts"})`；`:69` `class Caller:` docstring 逐字「一个调用方：**恰五个字段**，没有一个跟凭据有关。」⇒ 名册**没有预算/限额字段**，而且 `:124` 对未知键是**拒**（不是忽略）。
- `tools/pool/limits.py` 的 `limits.toml` 是**按卡 / 按账号**的（`limits_check.py` 模块 docstring 逐字「限额要在**派活之前**拦」），不是「按调用方 key」。
- 仓外 `D:/repo/infra/pool/` 今天**没有** `limits.toml`（只有 `accounts.toml` / `model-switches.toml` 等）。

⇒ magpie 的 `budget.Reserve(access.Caller(...), ...)`（`search_fetch.go:83`）在本仓**无处可落**。本卡**不移植**这一条，只留一个可核的空位（判据 5 最后一段）。

### 缺口 5 · MCP 面**接不上**：三条既有钉子会同时红

- `tools/pool_mcp.py` 里 `openWorldHint` 命中 **13 处**（首 `:401`、末 `:610`），全部逐字 `"annotations": {"readOnlyHint": True, "openWorldHint": False},` —— 现有十三个只读工具的公开声明就是「**不出网**」。加一个会出网的 `web_fetch` 与这条声明冲突（magpie 那边是 `"openWorldHint": true`，`search_fetch.go:54`）。
- 计数钉子：`tests/test_pool_mcp_task.py:807` `def test_tools_list_counts_unchanged(...)`，`:819` `assert len(thirteen) == 13, [t["name"] for t in thirteen]`、`:824` `assert len(eighteen) == 18, [t["name"] for t in eighteen]`；另有两份 13 项硬列：`tests/test_pool_mcp.py:45` `TOOL_NAMES = [`、`tests/test_pool_mcp_write.py:40` `READ_TOOL_NAMES = [`。
- 传输面：`tools/pool/mcp_http.py` 只绑回环（`DEFAULT_HOST = "127.0.0.1"`、`ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})`）。

⇒ 本卡**不接 MCP**，只落判据层。接面另开卡（那要同时改 13/18 两条计数、逐名 `readOnlyHint` 断言、以及「不出网」这句声明本身）。

### 缺口 6 · 卡域：`docs/subsystems/pool/modules.toml` 与四张 pending 卡相交

`tools/pool/plan.py:170-180` 逐字（省略 docstring）：

```python
def files_intersect(a: Card, b: Card) -> set[str]:
    return set(a.files) & set(b.files)
```

`:257-275` `validate()` docstring 逐字「冲突类（★ **只判"还在队列里"的卡**，即 `pending` / `running`）：① 两卡 `files` 相交 **且两者之间没有依赖路径**」。实测（本轮用 `tomllib` 读 `docs/workbacklog.toml`）：碰 `docs/subsystems/pool/modules.toml` 的 pending 卡是 **A367、A370、A371、A372** 四张。⇒ 本卡把 `modules.toml` 写进 files 时**必须**把那四张写进 depends（只有 `dependency_path()` 认这条边），否则拒单。

★ 而 `scripts/gen_pool_readme.py:102-106` 逐字 `for path in sorted(pool_dir.glob(f"*{suffix}")):` ⇒ `tools/pool/` 下**任何新 .py / .toml 都必须在 modules.toml 有条目**，否则 `--check` 退 1（现 **50** 条 `[[module]]`）。所以 `modules.toml` **不能**从 files 里去掉 —— 去掉就交不了差。

## 判据（六条，逐条给「怎么证明」）

### 判据 1 · 地址判词：十四个前缀 + NAT64/6to4 递归 + 映射地址，一个都不许漏

**要什么**：tools/pool/netguard.py 提供三个纯函数 —— `public(addr: str) -> bool`、`fake_ip(addr: str) -> bool`、`loon_paired(addr: str, answers: Sequence[str]) -> bool`。`public()` 逐条照 `netguard.go:46-68`：先 `unmap`（`::ffff:127.0.0.1` 当 `127.0.0.1`），再八连判（无效 / 回环 / 私有 / 未指定 / link-local 单播 / link-local 组播 / 接口本地组播 / 组播），再 `SPECIAL_NETS` 十四个前缀，最后 IPv6 的 NAT64（`64:ff9b::/96` 取第 12-15 字节）与 6to4（`2002::/16` 取第 2-5 字节）**递归**判内嵌 v4。`fake_ip()` 照 `:78`（`198.18.0.0/15`）；`loon_paired()` 照 `:85-96`（`fd27:712::/96` 且内嵌 v4 在 `answers` 里）。

**怎么证明**：新建 tests/test_pool_netguard.py，表驱动 ——

(a) **24 行必 false**：`127.0.0.1`、`10.0.0.1`、`172.16.0.1`、`192.168.1.1`、`169.254.169.254`、`100.64.0.1`、`0.0.0.0`、`192.0.0.8`、`192.0.2.5`、`198.18.0.1`、`198.19.255.255`、`198.51.100.7`、`203.0.113.9`、`240.0.0.1`、`::1`、`::ffff:127.0.0.1`、`64:ff9b::7f00:1`、`64:ff9b:1::1`、`2002:7f00:1::`、`fec0::1`、`100::1`、`2001::1`、`2001:db8::1`、`fd27:712::1`。
(b) **6 行必 true**：`8.8.8.8`、`1.1.1.1`、`198.17.255.255`、`2606:4700::1111`、`2002:808:808::`（6to4 里的 8.8.8.8）、`64:ff9b::808:808`（NAT64 里的 8.8.8.8）。
(c) **交叉断言（反向）**：对 `100.64.0.1` / `64:ff9b::7f00:1` / `fec0::1` 三行，同时断言标准库 `ipaddress.ip_address(x).is_global` 为 `True`（或 `is_private` 为 `False`）而本模块给 `False` —— 这三句就是「**不许用标准库一句糊过去**」的机器证据。
(d) `fake_ip("198.18.0.1")` 与 `fake_ip("198.19.255.255")` 为真；`"198.17.255.255"` 与 `"198.20.0.1"` 为假。
(e) `loon_paired("fd27:712::7f00:1", ["127.0.0.1"])` 真；给 `["127.0.0.2"]` 或 `[]` 假。

**钉子落点**：新建 tests/test_pool_netguard.py（本仓无同名文件；现 55 份 `test_pool_*.py` 里零冲突）。体例照 `tests/test_pool_sticky.py:1-26` 的模块 docstring「①-⑥ 每条写怎么坏掉会红」。

### 判据 2 · 三分类 + 按 charset 解码：GBK 页要出中文，未知 charset 不许崩

**要什么**：tools/pool/web_fetch.py 提供 `kind_of(media_type: str) -> str`（`"html"` / `"text"` / `""`，逐条照 `search_fetch.go:190-200`：`text/html` 与 `application/xhtml+xml` 是 html；前缀 `text/`、`application/json`、`application/xml`、后缀 `+json` / `+xml`、`application/javascript`、`application/x-ndjson` 是 text；其余 `""`）与 `to_text(body: bytes, content_type: str, kind: str, base: str) -> tuple[str, str]`（回 `(title, text)`，逐条照 `:203-217`：先按 `content-type` 的 `charset` 解码，**解码器建不起来就退回裸字节**；text 类标题为空 + 非法 UTF-8 替换；html 类交 `html_to_markdown`）。

**怎么证明**：新建 tests/test_pool_web_fetch.py ——

(a) `kind_of` 十行表：`text/html` / `application/xhtml+xml` / `text/plain` / `text/csv` / `application/json` / `application/activity+json` / `application/xml` / `application/javascript` / `image/png`→`""` / `""`→`""`；
(b) **GBK**：把「中文」按 GBK 编码 + `content-type: text/html; charset=gbk` ⇒ 输出里含「中文」、不含「锟斤拷」、且**不含 U+FFFD 替换符**；
(c) **未知 charset**（`charset=x-user-defined`）⇒ 不抛，返回字符串（内容可以乱，但不许崩）；
(d) `body` 含非法 UTF-8 字节 + `kind == "text"` ⇒ 出现 U+FFFD 替换符而不是异常。

**钉子落点**：新建 tests/test_pool_web_fetch.py。★ 不许用 `charset_normalizer` 兜底 —— 它**本机装着**（本轮 `importlib.util.find_spec` 实测命中 `requests` / `httpx` / `charset_normalizer`），但 `pyproject.toml:10-14` 的 `dependencies` 只有 `fastapi` / `uvicorn[standard]` / `pydantic>=2` ⇒ 用了就是隐式依赖，CI 机器上没有。

### 判据 3 · HTML→Markdown 六件事 + `done()` 的空壳行清理

**要什么**：`html_to_markdown(html: str, base: str) -> tuple[str, str]`，逐条照 `search_fetch.go`：

(1) `:346` `mdSkip`（script/style/noscript/template/svg/iframe/object/canvas/head/select/button/input/textarea）与 `hidden` / `aria-hidden="true"` 整棵丢；
(2) `:357-362` `h1..h6` ⇒ `"#" * n + " "`；
(3) `:363-385` `li` ⇒ 缩进 `"  " * (len(lists) - 1)` + 有序 `"N. "` / 无序 `"- "`；
(4) `:386-394` `pre` ⇒ 三反引号围栏，`:395-406` `code` 在 `pre` 内不再加反引号；
(5) `:413-439` `a` ⇒ 用 `base` 解析且 scheme 必须是 http/https 才写 `[text](… 目标地址 …)`；`href` 空 / 以 `#` 开头 / 在 `pre` 内 ⇒ 只写文字；**只有空文本的链接（图标）整段丢掉**；
(6) `:458-479` `done()` ⇒ 行尾空白裁掉、`"-"` / `">"` 空壳行清空、连续空行压成一行、末尾 `TrimSpace`。

**怎么证明**：tests/test_pool_web_fetch.py —— 一段手写 HTML（含 `<h1>`、嵌套 `<ul><li>`、`<pre><code>`、相对链接 `<a href="/x">`、`javascript:` 链接、纯图标 `<a href="/i"><img></a>`、`<script>` 与 `<div hidden>`、`<blockquote>`）⇒ 逐条断言：`"# 标题"` 在输出里；二级列表行以 `"  - "` 开头；围栏 `"```"` 出现两次且 `<code>` 内文不被单反引号包裹；相对链接变成 `(http://example.com/x)`；`javascript:` 与图标链接**不出现** `](`；`script` 内容与 `hidden` 内容**整段不出现**；输出**不含连续两个空行**；`done()` 对「a / - / > / b」四行（`"-"` 与 `">"` 是空壳行）把两行清成空行。

**钉子落点**：同上。

### 判据 4 · 字符窗口：默认 20000、上限 100000、按 rune 不按字节

**要什么**：`split_part(final_url: str, title: str, text: str, offset: int = 0, max_chars: int = 0) -> str`，逐条照 `search_fetch.go:100-122` 与 `:78-82`：`limit = max_chars if max_chars > 0 else 20000`，再 `limit = min(limit, 100000)`；首行 `"URL: <final>"`、次行 `"Title: <title>"`（title 空则不写）；`offset >= len(runes)` 时 —— 空页 ⇒ `"(the page has no text)"`，否则 ⇒ `"(the page has %d characters, none from offset %d)"`；还有余量 ⇒ 末尾追加 `[%d more characters: call web_fetch with offset=%d to read on]`（前面**两个换行**）。

**怎么证明**：tests/test_pool_web_fetch.py ——

(a) 30000 字的 ASCII 页 + 默认参数 ⇒ 正文恰好 `20000` 字、末行提示逐字 `[10000 more characters: call web_fetch with offset=20000 to read on]`；
(b) `max_chars=999999` ⇒ 实际按 `100000`；
(c) `max_chars=-5` ⇒ 走默认 `20000`（`search_fetch.go:78-82` 的 `if limit <= 0`）；
(d) 页长 30000、`offset=100000` ⇒ 文案逐字 `(the page has 30000 characters, none from offset 100000)`；
(e) 空文本 + `offset=0` ⇒ `(the page has no text)`；
(f) **中文页**（40000 个「中」字）+ `offset=19999, max_chars=2` ⇒ 输出是**两个完整「中」**，且 U+FFFD 不出现、rune 数可核 —— 这一条专抓「按字节切」。

**钉子落点**：同上。

### 判据 5 · 取页编排：只 http(s)、每跳都查地址、至多 5 跳、30 秒 / 5 MiB、三种拒收文案逐字

**要什么**：`fetch_page(fetch, resolve, url, *, max_chars=0, offset=0) -> str`。`fetch` 与 `resolve` 都是**注入的**（照 `tools/pool/gateway.py:504-507` 的 docstring 逐字「forward 是**注入的**（签名 (model, account, url, payload) -> Reply）：干跑时给桩，整条链路照走不误、一个字节都不出网」，以及 `tools/pool/checkin.py:53` `Fetcher = Callable[[str, str, Mapping[str, str] | None, bytes | None], tuple[int, str]]` 的注入体例）。建议签名：`fetch(url: str, headers: Mapping[str, str], timeout: float) -> tuple[int, Mapping[str, str], bytes]`、`resolve(host: str) -> Sequence[str]`。

规则逐条：(1) 空 url ⇒ `web_fetch needs a url`；scheme 非 http/https 或 host 空 ⇒ `web_fetch reads only http:// and https:// URLs, not ` + 原样 url；`offset < 0` ⇒ `offset can't be negative`（`search_fetch.go:69/73/76`）。(2) **每一跳**都用 `netguard.public()` 判 `resolve()` 回来的**每一个**地址（有一个不公共就拒），并把这批地址钉住给 `fetch`。(3) 重定向**自己跟**，至多 `WEB_FETCH_REDIRECTS = 5` 跳，超出 ⇒ `it redirects more than 5 times`；第 n 跳指向私有地址 ⇒ 与第 1 跳**同一条**私有地址错误。(4) `WEB_FETCH_TIMEOUT_S = 30.0` 原样传给 `fetch`；`WEB_FETCH_READ = 5 << 20` 是读回字节上限（超了按 `:160` 的 `io.LimitReader` 口径截断，不报错）。(5) `status >= 400` ⇒ `the site answered ` + 状态行（如 `the site answered 404 Not Found`）；`kind_of(mt) == ""` ⇒ `it is image/png, not a page of text` 形状；私有地址 ⇒ `it is at a private address (this computer, its network, or a name that resolves to one), which web_fetch doesn't read`。

**怎么证明**：tests/test_pool_web_fetch.py —— 全部用桩，**零网络**：

(a) `fetch` 桩记录收到的 `(url, timeout)` ⇒ 断言 `timeout == 30.0`；
(b) `resolve` 桩对 `127.0.0.1` 回 `["127.0.0.1"]` ⇒ 抛 `FetchError` 且 `str(exc)` **逐字**等于那句私有地址文案；
(c) 一个域名解析出 `["8.8.8.8", "10.0.0.1"]` 两条 ⇒ 也拒（**每个地址都查**）；
(d) 6 次 `302` 链 ⇒ `it redirects more than 5 times`；5 次 ⇒ 放行；
(e) 第 3 跳指向 `http://127.0.0.1/` ⇒ 私有地址文案（**每跳都查**）；
(f) `404` ⇒ `the site answered 404 Not Found`；`content-type: image/png` ⇒ `it is image/png, not a page of text`；
(g) `fetch` 桩收到的字节上限参数是 `5 << 20`，或由桩回 6 MiB 内容、断言交给 `to_text` 的字节数被截到 `WEB_FETCH_READ`；
(h) **没实现的那条要钉成空位**：`inspect.getsource(web_fetch.fetch_page)` 里不出现 `budget` / `reserve` 字样 —— magpie `search_fetch.go:83` 的 `budget.Reserve(access.Caller(r.Context()), int64(len(raw)), "", limitClock())` 在本仓没有对应物（缺口 4），「没实现」必须是**可核的缺席**，不许悄悄缺席。

**钉子落点**：tests/test_pool_web_fetch.py + 一条模块头断言照 `tests/test_pool_rest.py:323-333` 的体例（把模块源码按「第一个空行」与「`ROOT = Path`」切两刀，切出来的头部里不许出现 `import urllib` / `import socket` / `import requests` / `import httpx`）。

### 判据 6 · 反向变异 ≥3 条（每条真改真跑真复原）+ 一条只改注释的安静对照

脚本落 `gates/diag/_rev_F58.py`（gitignored，`.gitignore:70-77` 已整体忽略 `gates/diag/`），末行打印「结论：N/N 条全部咬住，收尾绿。」

| # | 改哪一行（锚点原文） | 哪条判据该红 |
|---|---|---|
| M1 | tools/pool/netguard.py 的 `SPECIAL_NETS` 表里删掉 `"100.64.0.0/10"` 那一行 | 判据 1(a) 的 `100.64.0.1` 行 ⇒ 红（CGNAT 被当公网） |
| M2 | tools/pool/netguard.py 的 `public()` 里把 NAT64 那条递归 `return public(_v4(addr, 12))` 改成 `return True` | 判据 1(a) 的 `64:ff9b::7f00:1` 行 + 判据 1(c) 的交叉断言 ⇒ 红 |
| M3 | tools/pool/web_fetch.py 的 `split_part` 里 `end = min(offset + limit, len(runes))` 改成 `end = min(offset + limit, len(text))`（按字节切） | 判据 4(f) 的中文页 ⇒ 红（切出半个字 / U+FFFD 出现） |
| M4（安静对照） | **只改注释**：把 `# 按 rune 切，不按字节切` 这句中文注释换个说法，**不改任何代码** | 六条判据**全绿**（若有一条红，说明有判据在咬注释而不是咬行为 —— 那是坏钉子） |

**怎么证明**：脚本逐条 `shutil.copyfile` 备份 → `src.replace(锚点, 改写, 1)` → 断言替换**恰好发生一次**（`assert src.count(锚点) == 1`；替换 0 次说明锚点漂了，必须报红而不是静默通过）→ 跑对应 `pytest` 选测 → `assert rc != 0` → 复原 → 最后跑一遍全绿 → 打印结论行。

## 交付

| 文件 | 性质 | 说明 |
|---|---|---|
| tools/pool/netguard.py | **新增** | 三个纯函数 `public()` / `fake_ip()` / `loon_paired()` + `SPECIAL_NETS` 十四项 + 三个前缀常量。**不解析名字、不出网、不读盘、不读钟、不 print**（`netguard.go:1-5` 的边界） |
| tools/pool/web_fetch.py | **新增** | `kind_of` / `to_text` / `html_to_markdown` / `split_part` / `fetch_page` + 五个常量（30.0 / 5 MiB / 20000 / 100000 / 5 跳）。**不 import urllib / socket / requests / httpx**：出网与解析都由注入的 `fetch` / `resolve` 承担 |
| tests/test_pool_netguard.py | **新增** | 判据 1 的钉子（表驱动 + 交叉断言） |
| tests/test_pool_web_fetch.py | **新增** | 判据 2-5 的钉子（全桩化，零网络零落盘） |
| `docs/subsystems/pool/modules.toml` | 改 | 追加**两条** `[[module]]`（`netguard.py` / `web_fetch.py`）：`name` + `duty` + `cli` 三键缺一 `scripts/gen_pool_readme.py --check` 就退 1（`:102-106` 会 glob `tools/pool/*.py`） |
| 复盘/卡/卡F58-web_fetch-只读公共地址.md | **新增** | 本卡规格落成正式件（文件名随立卡人定） |

★ **不碰**：`tools/pool_mcp.py`、`tools/pool/mcp_http.py`、`tools/pool/gateway.py`、`tools/pool/checkin.py`、`tools/pool/callers.py`、`tools/pool/limits.py`、`tools/pool/limits_check.py`、`src/timeflow/core/lan.py`。理由不是洁癖 —— `tools/pool/plan.py:170-180` 的 `files_intersect()` 是**精确字符串集合相交**，碰了 A372 / A368 / E143 的文件就会与它们串批（`:257-275`）。

## 验收（可直接跑）

```bash
cd .wt/A374

# 1. 新钉子全绿（单跑必须绕开覆盖率门：pyproject.toml:51 的 addopts 带 --cov-fail-under=70）
python -X utf8 -m pytest tests/test_pool_netguard.py tests/test_pool_web_fetch.py -o addopts= -q --no-cov

# 2. 老钉子一条没被放宽（这些文件本卡一个字节都没改，条数不许动）
python -X utf8 -m pytest tests/test_pool_rest.py tests/test_pool_mcp.py tests/test_pool_mcp_write.py tests/test_pool_mcp_task.py tests/test_pool_checkin.py -o addopts= -q --no-cov

# 3. 两个新模块进了清单（仓里有、modules.toml 没有 ⇒ 退 1 并点名）
python -X utf8 scripts/gen_pool_readme.py --check

# 4. 反向变异（3 条必须咬住 + 1 条安静对照必须全绿）
python -X utf8 gates/diag/_rev_F58.py

# 5. 零出网断言：两个新模块里不许出现任何 HTTP / DNS 客户端（grep 命中退 0、无命中退 1）
grep -n -e "import urllib" -e "import socket" -e "import requests" -e "import httpx" -e "urlopen" -e "getaddrinfo" tools/pool/netguard.py tools/pool/web_fetch.py
test $? -eq 1

# 6. ruff（line-length 100、select E/W/F/I/N/UP/B/SIM/TCH —— pyproject.toml:78/:81）
python -X utf8 -m ruff check tools/pool/netguard.py tools/pool/web_fetch.py tests/test_pool_netguard.py tests/test_pool_web_fetch.py
```

六条都退 0 才算成。第 3 条退 1 时会逐行点名缺的是哪个文件 —— 那就是没进 `modules.toml`。第 5 条拆成两行跑（`grep` 后单独 `test $? -eq 1`），避免管道吞退出码（写法口径见 `AGENTS.md`「长命令怎么跑」）。

**已知噪音**：第 2 条里 `tests/test_pool_checkin.py` 与 `tests/test_pool_rest.py` 都会 import `pool.checkin` / `pool_quota`，只用桩不发真请求；若它们红，先看是否本卡意外改了那两个文件（本卡不该改）。

## 不许做

- **不许**改 `tools/pool_mcp.py` 的**一个字节** —— 十三个只读工具全部声明 `"openWorldHint": False`（`:401` 到 `:610`，共 13 处），且 `tests/test_pool_mcp_task.py:819/:824` 硬等 `13` / `18`、`tests/test_pool_mcp.py:45` 与 `tests/test_pool_mcp_write.py:40` 各有一份 13 项硬列。加一个会出网的工具是**另一张卡**的事。
- **不许**改 `tools/pool/checkin.py:229` 与 `tools/pool/gateway.py:827` 那两处 `noqa: S310` 及它们的理由 —— 那两处的端点是常量；本卡的 URL 来自用户，所以本卡**没有** `noqa` 可写，只能自己判地址。
- **不许**在 `netguard.py` / `web_fetch.py` 里 import `requests` / `httpx` / `charset_normalizer` / `bs4` / `markdownify` / `html5lib`。本机**装着**前三个（本轮实测），但 `pyproject.toml:10-14` 的 `dependencies` 只有三件 ⇒ 用了就是在 CI 上必崩的隐式依赖。HTML 解析只能用标准库 `html.parser`。
- **不许**把重定向上限改成 `10`。`search_fetch.go:142-143` 那条 `len(via) >= 10` 是 `webFetchClient.CheckRedirect == nil` 的**兜底分支**；走 `publicClient` 时实际生效的是 `image_fetch_guard.go:355` 的 `len(via) > imageRedirects`（`:72` `const imageRedirects = 5`）。本卡取 **5**，并把「为什么不是 10」写进代码注释。
- **不许**在 `web_fetch.py` 里复制第二份「失败分类」：状态码七值分类只有 `tools/pool/gateway.py:180` 一份（`def classify(status: int, body: bytes | dict | None = None) -> Kind`）。本卡的 `>= 400` 是**网页取回**的判据，不是上游号池的判据 —— 两件事不许合并。
- **不许**在 `netguard.py` 里再写一份「本机来源」判词，也不许改 `src/timeflow/core/lan.py`：那是局域网配对门闸，与「目标是否公共」方向相反（缺口 2）。
- **不许**动 `tools/pool/plan.py` / `tools/pool/callers.py` / `tools/pool/limits*.py` 的判据，也不许为了「凑齐 magpie 那条预留」给 `callers.toml` 加预算字段（`callers.py:124` 对未知键是**拒**，不是忽略）。
- **不许**改仓外文件：`D:/repo/infra/**`（`accounts.toml` / `model-switches.toml` 与那台机器上的任何文件）一个字都不许动；本卡也不读它。
- **不许**手改 `docs/subsystems/pool/README.md` 的生成区（`<!-- pool-margin:begin -->` 到 `<!-- pool-margin:end -->` 之间由 `scripts/gen_pool_readme.py` 重算）。
- **不许**把 `web_fetch` 接成生产路径（不接 `gateway.py`、不接 `pool_mcp.py`、不接 `mcp_http.py`）：接面会同时撞「不出网声明 + 13/18 计数 + 只绑回环」三条既有钉子（缺口 5），必须单独一张卡。

## 与已完成卡的关系

| 卡 | 状态 | 关系 |
|---|---|---|
| A338（F33） | done | `limits_check.py` 是「限额要在派活之前拦」的**唯一**判据面。本卡**只读**它；「按调用方 key 预留」在本仓没有对应物（缺口 4），本卡不假装有。 |
| A348（F32） | done | `callers.py` 的 `Caller` 恰五字段（`:69`），名册不含预算 ⇒ 本卡不往里加字段。 |
| A365 | done | `mcp_http.py` 只绑回环。本卡**不接**传输层，只在缺口 5 里点名那三条会红的钉子。 |
| E94 | done | `gateway.py` 的四条硬边界（不翻译协议 / 不做凭据发现 / 不做定时器 / 不复制判据）本卡全部继承；`:180` 的 `classify` 七值本卡不动。 |
| A367 / A370 / A371 / A372 | pending | 四张的 files 都含 `docs/subsystems/pool/modules.toml`；本卡 depends 它们只为满足 `plan.py:233-240` 的「同域必须有依赖路径」。**本卡不改它们的任何文件。** |
| A372（F56） | pending | 与 F57 同一个依赖源（搜索 vendor 表）。本卡与它**无代码重叠**，只在 `modules.toml` 上串行。 |

## 未坐实项（草稿如实标注，别当成结论）

1. **重定向上限原件是两处不同的数**：`image_fetch_guard.go:72` `const imageRedirects = 5` + `:355` `len(via) > imageRedirects` 对 `search_fetch.go:142-143` 的 `len(via) >= 10`。features 文档（`:496-502`）写「至多 **5** 次」，与前者一致；后者只在 `CheckRedirect == nil` 时生效。本卡取 **5**。**这是判据取舍，不是原件自洽** —— 若立卡人要求与原件逐字一致，得写成「走 publicClient 分支才是 5」。
2. **「每次调用像搜索一样预留调用方 key 的限额」没有移植**：本仓 `callers.toml` 无预算字段、`limits.toml` 按卡/账号、仓外今天也没有 `limits.toml`。判据 5(h) 只把「没实现」钉成可核的空位。**要不要补这条能力是另一张卡的事。**
3. **fake-IP（`198.18.0.0/15`）与 Loon（`fd27:712::/96`）只移植了判词，没移植放行路径**：magpie 在 `publicTransport.RoundTrip`（`image_fetch_guard.go:195` 起）里对 `fake` 与 `named` 放行并钉住 `pinned`，还在 socket 层用 `guardDialer` 的 `Control` **再查一次**（`:166-183`）。本仓不出网 ⇒ 这两条**今天无处可验**。判据 1(d)(e) 只钉「判词真假」。**未坐实：本仓将来真出网时是否照搬这一整套。**
4. **接不接 MCP 工具面未拍板**：接了要同时改 `openWorldHint` 十三条声明、13/18 计数、`mcp_http` 的回环口径。本卡选**不接**（缺口 5）。**若立卡人要求本卡就接面**，files 必须加 `tools/pool_mcp.py` + `tools/pool/mcp_http.py`，并对 `tests/test_pool_mcp*.py` 三处计数做**显式**更新（那不是放松判据，是如实记账，但要单独写进判据）。
5. **HTML 解析器不可能与 Go 的 `x/net/html` 逐字节相同**：标准库 `html.parser` 是流式的、不建树，隐式闭合与错误恢复都与 Go 不同（`<p>` 未闭合、嵌套表格等）。本卡只钉「六件事」（标题 / 列表 / 代码 / 链接绝对化 / 丢弃 / 压空行），**不钉**与 magpie 输出逐字节相同。
6. **30 秒 / 5 MiB 在「注入 fetcher」形态下只是常量传递**：本卡断言常量被原样传给 `fetch`（判据 5(a)(g)），但真正的 `read(5 << 20)` 与 socket 超时由 fetcher 侧保证 —— **真 HTTP 客户端本卡不写，未真机验证**。
7. **`240.0.0.0/4` 与 `0.0.0.0/8` 在 Python 标准库里已判 private**，本卡的表仍逐字照抄（重复不省略）—— 理由是「表就是判据」，少一行会让下一个改表的人以为那行不重要。**未坐实的只是「要不要精简」**，不影响行为。
