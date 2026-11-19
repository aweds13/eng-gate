# 卡 A384：F10 previous_response_id 的内存态跟随 —— 判 SKIP_BY_REDLINE（本仓没有 Responses 面可挂），只钉「同协议直通原样透传」
> 台账号 `T-AG672`｜分区 A（magpie 移植 / 号池 pool）｜树 `.wt/A384`｜层 判据层｜基准 `f7d4d305`（立卡时主树 HEAD，2026-11-20 05:35 实读）｜depends A372、A373、A375、A376、A380、A381
> depends 说明：草稿只写 `depends A372`；立卡时按台账实况重核。本卡域三个文件与今天 20 张活跃卡（R5）求**精确**相交，命中 **6 张**（R6）：A372 / A373 / A375 / A376 / A380 与本卡共用 `tests/test_pool_gateway.py`，A381 与本卡共用 `docs/subsystems/pool/模型与号池.md`；这六张今天全是 `pending` ⇒ 六张全写进 depends（`tools/pool/plan.py:318-327`：活跃卡 files 相交且无依赖路径 ⇒ 拒单「同一文件两个写者」；`dependency_path()` 任一方向含传递都算，`greedy_pack()` 不跨层打包）。**已 done 的三张（E94 / E143 / A368）不进 depends** —— 它们只作读法参照，留在 depends 里只会让这张卡白等一批。本卡**不写** `tools/pool/gateway.py`，所以 A372 / A375 / A380 与本卡相交的只有测试文件那一处。
> 基准说明：`f7d4d305` = 立卡时主树 HEAD（`git rev-parse --short HEAD` 实读，R1）。本文行号逐行读过；复核命令 `git diff --stat 7a4cc513..HEAD -- tools/pool/gateway.py tests/test_pool_gateway.py docs/subsystems/pool/模型与号池.md gates/diag/_magpie_scope.md` **输出为空**（R12；`7a4cc513` 是草稿起草时的 HEAD）⇒ 起草时的行号今天仍有效，那一段提交没碰这四份文件。落地前按当时 HEAD 重核。
> 依据：`gates/diag/_magpie_scope.md:18` 今天把 F10 判成 `PORT / no`（R9 实读），证据只有一行「grep prev_response 在 tools/ scripts/ 零命中（Responses 协议状态未落）」。本卡把这个 `PORT` 改成 `SKIP_BY_REDLINE`，并把「不移植」落成可核证据 —— 留成「还没做」是错的：它**不该做**。

## 读数口径（2026-11-20 05:37 实读；每条都给算它的命令）

| # | 读什么 | 读数 | 命令 |
|---|---|---|---|
| R1 | 主树 HEAD | `f7d4d305` | `git rev-parse --short HEAD` |
| R2 | `tools/pool/gateway.py` 行数 | 1300 行 | `wc -l tools/pool/gateway.py` |
| R3 | `tests/test_pool_gateway.py` 行数 / `^def test_` 条数 | 1150 行 / 72 条 | `wc -l tests/test_pool_gateway.py`、`grep -c "^def test_" tests/test_pool_gateway.py` |
| R4 | `docs/subsystems/pool/模型与号池.md` 行数与换行 | 170 行，纯 CRLF 170/170 | `python -X utf8 -c "from pathlib import Path;b=Path('docs/subsystems/pool/模型与号池.md').read_bytes();print(len(b.splitlines()),b.count(b'\r\n'),b.count(b'\n'))"` |
| R5 | 活跃卡（pending / running）张数 | 20 张 | `python -X utf8 -c "import sys;sys.path.insert(0,'tools/pool');import plan;b=plan.load_backlog();print(sum(1 for c in b.cards if c.status in plan.ACTIVE_STATUS))"` |
| R6 | 与本卡域相交的活跃卡 | 6 张：A372 / A373 / A375 / A376 / A380（共用 `tests/test_pool_gateway.py`）、A381（共用 `docs/subsystems/pool/模型与号池.md`）；六张全 `pending` | 见下方「R6 / R8 / R11 的脚本」 |
| R7 | `tools/` 下 .py 文件数 | 149 个 | `python -X utf8 -c "from pathlib import Path;print(len(list(Path('tools').rglob('*.py'))))"` |
| R8 | 全 `tools/` 的 `prev*` 标识符 / 含 `response` 的字符串常量 / 去注释源码含 `/v1/responses` 的文件 | 30 处（10 个文件）/ 3 处 / 0 个 | 见下方「R6 / R8 / R11 的脚本」 |
| R9 | `gates/diag/_magpie_scope.md` 的 F10 行与计数行 | :18 = `PORT / no`；:106 = `PORT 共 69 条 / SKIP_BY_REDLINE 4 条 / SKIP_NOT_APPLICABLE 23 条 / PORT 中 landed=yes 20、partial 22、no 27`；锚定 `grep -c '^\| .* \| SKIP_BY_REDLINE \|'` = 4，不加锚 = 6 | `sed -n '18p;106p' gates/diag/_magpie_scope.md`、`grep -c '^\| .* \| SKIP_BY_REDLINE \|' gates/diag/_magpie_scope.md` |
| R10 | 探针产物 | `ls gates/diag/_probe_tmp_F10*.py` 报 `No such file or directory` ⇒ 起草时的探针脚本今天不在 | `ls gates/diag/_probe_tmp_F10*.py` |
| R11 | `tools/pool/gateway.py` 的 Responses 语义（tokenize + AST，本会话复跑） | `CODE_HAS_RESP_PATH False` / `AST_CONST_RESPONSE []` / `AST_PREV_NAMES []` / `PLAIN_COUNT 1` | 见下方「R6 / R8 / R11 的脚本」 |
| R12 | 起草基准到今天的差异 | 空输出 | `git diff --stat 7a4cc513..HEAD -- tools/pool/gateway.py tests/test_pool_gateway.py docs/subsystems/pool/模型与号池.md gates/diag/_magpie_scope.md` |

R6 / R8 / R11 的脚本（`python -X utf8` 直接喂 stdin，只读，0 出网）：

~~~python
import ast, io, tokenize, sys
from pathlib import Path
sys.path.insert(0, "tools/pool")
import plan
b = plan.load_backlog()
mine = {"tests/test_pool_gateway.py", "docs/subsystems/pool/模型与号池.md",
        "复盘/卡/卡A384-F10-previous_response_id不移植只钉原样透传.md"}
print("R6", [(c.id, c.status, sorted(set(c.files) & mine)) for c in b.cards
             if c.status in plan.ACTIVE_STATUS and set(c.files) & mine])
prev, resp, resp_path = 0, 0, []
for p in sorted(Path("tools").rglob("*.py")):
    src = p.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, (ast.Name, ast.Attribute, ast.FunctionDef,
                          ast.AsyncFunctionDef, ast.ClassDef)):
            nm = n.id if isinstance(n, ast.Name) else (
                n.attr if isinstance(n, ast.Attribute) else n.name)
            prev += "prev" in nm
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and "response" in n.value:
            resp += 1
    toks = [t for t in tokenize.generate_tokens(io.StringIO(src).readline)
            if t.type != tokenize.COMMENT]
    if "/v1/responses" in tokenize.untokenize(toks):
        resp_path.append(p.as_posix())
print("R8", "PY", len(list(Path("tools").rglob("*.py"))), "PREV", prev,
      "RESP_CONST", resp, "RESP_PATH", resp_path)
src = Path("tools/pool/gateway.py").read_text(encoding="utf-8")
toks = [t for t in tokenize.generate_tokens(io.StringIO(src).readline)
        if t.type != tokenize.COMMENT]
code = tokenize.untokenize(toks)
tree = ast.parse(src)
print("R11",
      "/v1/responses" in code,
      [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)
       and isinstance(n.value, str) and "response" in n.value],
      src.count("/v1/responses"))
~~~

## 前情（实测于 `7a4cc513`，2026-11-20 05:37 按 R12 复核为仍有效）

F10 在 magpie 侧不是一个管道，是「Responses 协议的会话状态跟随」—— 三件互不相同的东西：

1. **入口**：`POST /v1/responses` body 里的 `previous_response_id`；`store: false` 可不让记。功能清单 `D:/repo/program/_ext/_magpie_features.md:116` 逐字：`- 入口：\`POST /v1/responses\` body 里的 \`previous_response_id\`；\`store: false\` 可不让记。`
2. **内存态**：LRU **256 MB** 出、每条留 **6 小时**，按「造它的调用方」隔离。`_magpie_features.md:118` 逐字：「只在内存，LRU 过 **256 MB** 出，每条留 **6 小时**（`prevTTL`/`prevCap`）；按"造它的调用方"（gateway key / 经哪个远端 magpie / 无 key 的远端地址）隔离，别人点名该 id 被告知不存在；没见过的 id 在翻译路由上发送前回 OpenAI 的 400 `previous_response_not_found`，Responses 直通则原样转发。」常量在 `internal/gateway/prev_response.go:40-46`：`:41 prevTTL = 6 * time.Hour`、`:44 prevCap = 256 << 20`、`:46 prevReplyMax = 64 << 20`（2026-11-20 05:37 回读 Go 原件，三行逐字对上）。
3. **只在 Responses 协议上生效** —— 这是全功能的**第一道闸**，`internal/gateway/prev_response.go:216-220` 逐字：

~~~go
func previousResponse(w http.ResponseWriter, r *http.Request, from provider.Protocol, body []byte) (http.ResponseWriter, *http.Request, []byte, func()) {
	nothing := func() {}
	if from != provider.Responses {
		return w, r, body, nothing
	}
~~~

- 接线点两处，都带 `proto == provider.Responses` 条件：`internal/gateway/middleware.go:26` `w, r, body, kept := previousResponse(w, r, from, body)`（在 `serveAgent` 里、任何 hook / 翻译 / mask 之前，`:27 defer kept()`）；`internal/gateway/gateway.go:4892-4896` `sentWhole, delta := body, false` / `if proto == provider.Responses {` / `body, delta = prevDelta(r, p, body)` / `}`；`:4912-4913` `if proto == provider.Responses && prevKeptBy(p) && !storeOff(body) {` / `noteAnswered(r, prevRoute(p))`。
- `store: false` 的出口在 `prev_response.go:257-259`：`var store bool` / `if json.Unmarshal(q["store"], &store) == nil && !store {` / `return w, r, body, nothing // the client asked that nothing be kept`。
- 未知 id 的 400 也只在**翻译路由**上：`gateway.go:4212-4213` `if id := prevLost(r); id != "" {` / `return writePrevNotFound(w, id)`；文案在 `prev_response.go:199-202`：`msg := "Previous response with id '" + id + "' not found."`。
- 它改写 body 的那一处（把上一轮 items 拼进 `input`，再删掉 `previous_response_id`）在 `prev_response.go:246-252`，**那是改写请求体**。

★ 一句话：**F10 的全部行为都挂在 `provider.Responses` 这个协议分支上**。这不是风格，是源码里的第一个 `if`。

本仓侧（`tools/pool/gateway.py`，1300 行 = R2）：

- 路径表是**四条**，`gateway.py:99-104` 逐字：

~~~python
PATHS: dict[str, tuple[str, str]] = {
    "/v1/chat/completions": ("POST", PROTOCOL_CHAT),
    "/v1/messages": ("POST", PROTOCOL_MESSAGES),
    "/v1/models": ("GET", ""),
    "/v1/pool/routes": ("GET", ""),
}
~~~

- 那句「不开」写在 `gateway.py:98`（**是全仓生产侧唯一出现 `/v1/responses` 的地方，且是注释**；R8 实读：去注释源码含它的文件 0 个）：`#: 四条路径，一个都不多（不开 /v1/responses、Gemini、Ollama 兼容、管理面）。`
- 协议判定认不出 Responses：`gateway.py:239-245` `def endpoint_protocol(url: str) -> str:` / `:240` docstring `只看 URL 的路径尾巴判协议。认不出回空串 —— **不猜、不试、不发请求**。` / `:245 return {"/v1/chat/completions": PROTOCOL_CHAT, "/v1/messages": PROTOCOL_MESSAGES}.get(path, "")`。
- 端点挑选同一个口径：`gateway.py:248-263`，`:262-263` 逐字 `return None, (f"平台 {platform!r} 登记了端点，但没有 {protocol} 协议的端点：" "本网关只做同协议直通，不做协议翻译")`。
- 转发时 body 是调用方 payload **原样**：`gateway.py:676 reply = forward(model, seat, url, body)`；来源在 `:1134-1138 outcome = route_once(..., body=payload, root=getattr(self.server, "root", None))`（`:1120 obj = json.loads(payload.decode("utf-8"))` 只取 model / stream，不回写 payload）。口径逐字在 `:919`（`forward_http` 的 docstring）：`只做同协议：payload 原样发（不改写 stream / 不搬家字段），回来的 SSE 直接给 chunks。`
- 没这条路径就 404，文案在 `gateway.py:1085-1090` 逐字：`path = urlsplit(self.path).path.rstrip("/") or "/"` / `spec = PATHS.get(path)` / `if spec is None:` / `self._fail(404, f"没有这条路径：{path!r}。本网关只有四条：" "POST /v1/chat/completions、POST /v1/messages、" "GET /v1/models、GET /v1/pool/routes。", kind="not_found_error")`。

探针实跑（起草时产物 `gates/diag/_probe_tmp_F10.py`，桩 forward，**0 出网**，号池目录造在临时目录；★ 2026-11-20 05:37 复核：该脚本今天**不在**，R10 的 `ls` 报 No such file ⇒ 下面这段是**起草时的原样输出，本卡未复跑**；同判据里能复跑的那一半（tokenize + AST）已在本会话复跑，见 R11）：

~~~text
POST /v1/responses  => 404 {"error": {"type": "not_found_error", "message": "没有这条路径：'/v1/responses'。本网关只有四条：POST /v1/chat/completions、POST /v1/messages、GET /v1/models、GET /v1/pool/routes。"}}   calls: 0
POST /v1/chat/completions  body={"model": "huaweicloud-maas/GLM-5.2", "previous_response_id": "resp_1", "input": "hi", "store": false}
  => 200 {"ok":true}   calls: 1   byte-identical: True
sorted(gateway.PATHS) => ['/v1/chat/completions', '/v1/messages', '/v1/models', '/v1/pool/routes']
[k for k in dir(gateway) if k.startswith('PROTOCOL_')] => ['PROTOCOL_CHAT', 'PROTOCOL_MESSAGES']
endpoint_protocol('https://x.test/v1/responses') => ''
pick_endpoint(('https://chat.example.test/v1/chat/completions',), 'responses', platform='codearts')
  => (None, "平台 'codearts' 登记了端点，但没有 responses 协议的端点：本网关只做同协议直通，不做协议翻译")
~~~

## 结论：判 **SKIP_BY_REDLINE**（不是 PORT，也不是 SKIP_NOT_APPLICABLE）

| F10 的三件 | 本仓现状（文件:行号） | 本卡判 |
|---|---|---|
| ① 记上一轮对话、按 id 跟随，只在 Responses 协议上生效 | 无 Responses 面：`tools/pool/gateway.py:98`（注释「不开」）+ `:99-104`（四键）+ `:239-245`（协议判定两键）；magpie 侧闸门 `prev_response.go:218-220` | **无挂载点** ⇒ 不移植 |
| ② 内存 LRU（256MB / 6h）、按调用方隔离 | 仓内零实现：`grep -rn "prev_response\|previous_response" tools/ scripts/ --include=*.py` 零命中 | **不移植**（没有宿主状态可挂在一个不存在的协议面上） |
| ③ 未知 id 回 400 `previous_response_not_found`（仅翻译路由） | 翻译路由本身就是红线段（`gateway.py:3-5` 明写不搬 `forwardOnce` / `ir.go` / `decoderFor`；scope 表 `:10` F2 已判 SKIP_BY_REDLINE） | **不移植**（随 ② 一起没有意义） |
| ★ 但「同协议直通」这一半**今天已经成立**，且必须钉住 | 带 `previous_response_id` / `store: false` 的 body 逐字节到 forward（探针 `byte-identical: True`；源码锚点 `gateway.py:1138 body=payload` / `:919`） | **本卡的交付就是这个钉子** |

为什么不能两头都占（这是本卡的核心论证，逐条给源码）：

- **出路 A：开 `/v1/responses` 面** ⇒ 那是新增一个协议面，直接踩红线段。文件头 `gateway.py:3-5` 逐字：`对等 magpie 的 internal/gateway/gateway.go 的一小块 —— 只搬「选号 → 转发 → 换号 → 留痕」` / `这条链。**不搬**它的协议翻译层（forwardOnce / ir.go / decoderFor）：` / `客户端说 Chat 就只往 Chat 端点发，说 Messages 就只往 Messages 端点发，SSE 逐字节转发。`；`:98` 逐字把「不开 /v1/responses」写在常量旁边。scope 表 `:3` 把 `SKIP_BY_REDLINE` 定义成「永不做协议翻译层」，`:10` 的 F2（三种协议互译）已经按这条判过。
- **出路 B：在 `/v1/chat/completions` 上「跟随」** ⇒ 要么把 `previous_response_id` 展开成整段 `input`（= 改写请求体），要么把它删掉（= 改写请求体）—— 两种都违反 `gateway.py:919` 逐字「payload 原样发（不改写 stream / 不搬家字段）」，也就是**协议翻译**。`gateway.py:8` 逐字再压一次：`1. **不做协议翻译**：上游只回流式、调用方要非流式 ⇒ 400 拒绝并说明，绝不自己攒流。`
- **为什么不是 SKIP_NOT_APPLICABLE**：它并不是「不可移植资产」（如密钥、私有协议），而是一条**在红线段另一侧的**功能 —— 判 `SKIP_BY_REDLINE` 才说得清「等哪天红线松了它就能移」。
- ⇒ **本仓对 F10 的正确行为是「不动它，原样透传」**：客户端在 chat body 里塞什么字段都行（包括 `previous_response_id` / `store`），网关一个字节都不碰，由上游自己认。这条今天成立 —— 所以本卡不写代码，只把「成立」钉成判据。

★ 落地时把 `gates/diag/_magpie_scope.md:18` 就地改成：`| F10 | previous_response_id 的内存态跟随 | SKIP_BY_REDLINE | — | 只在 Responses 协议上生效（prev_response.go:218-220 第一道闸 \`if from != provider.Responses\`）；本仓无 Responses 面（tools/pool/gateway.py:99-104 四键、:98 明写不开）⇒ 无挂载点。往 chat payload 里展开 = 改写 payload = 协议翻译，违反 gateway.py:919「payload 原样发…不搬家字段」。今天靠原样透传兜（判据 2） |`，并把 `:106` 的计数从 `PORT 共 69 条 / SKIP_BY_REDLINE 4 条 / … / PORT 中 landed=yes 20、partial 22、no 27` 改成 `PORT 共 68 条 / SKIP_BY_REDLINE 5 条 / SKIP_NOT_APPLICABLE 23 条 / PORT 中 landed=yes 20、partial 22、no 26`（`PORT −1`、`SKIP_BY_REDLINE +1`、`PORT landed=no −1`；改前读数见 R9）。那份文件在 `.gitignore` 内，改它**不算入库** ⇒ 是主树验收动作，不是 pytest 输入。

## 本仓今天有没有这个东西：**完全没有**（不是「有代码但没接线」）

| 查什么 | 命令（在工作树根跑） | 读数 |
|---|---|---|
| 生产侧有没有 Responses 字样 | `grep -rn "responses" tools/ scripts/ --include=*.py` | 唯一命中 `tools/pool/gateway.py:98`（**注释**，且是「不开」）；排除该行后 rc=1 |
| 生产侧有没有跟随逻辑 | `grep -rn "prev_response\|previous_response" tools/ scripts/ --include=*.py` | **零命中**（rc=1） |
| 测试侧有没有 | `grep -rn "previous_response" tests/ --include=*.py` | **零命中**（rc=1） |
| 测试侧有没有 `/v1/responses` | `grep -rn "/v1/responses" tests/ --include=*.py` | 两处：`tests/test_pool_gateway.py:268`（`endpoint_protocol` 回空）、`:689`（404 走一遍）；后者不断言文案、不断言 `calls` |
| 代码里有没有 Responses 语义（去注释 + AST） | R11 的脚本（本会话复跑） | `CODE_HAS_RESP_PATH False`、`AST_CONST_RESPONSE []`、`AST_PREV_NAMES []`、`TOKENIZE_STRING_HITS 0`、`PLAIN_COUNT 1` |
| 文档有没有投影 | `grep -rn "chat/completions" docs/`、`grep -rn "/v1/responses" docs/` | 两条都 **rc=1 零命中** ⇒ 网关「四条路径」这条事实今天在 `docs/` 里没有任何投影（`复盘/` 那边有四份已有卡规格提到 `/v1/responses`，那是卡的论证、不是产品文档） |

分清两件事（本任务要求）：

- **不是「有代码没接线」**：AST 扫 `tools/pool/gateway.py` 的 `Name` / `Attribute` / `FunctionDef` / `ClassDef` 里含 `prev` 的标识符是 **`[]`**，`ast.Constant` 里含 `response` 的字符串也是 **`[]`**（R11 复跑）。没有函数、没有常量、没有字符串 —— 一行都没写过。
- **全仓 `tools/`（今天 149 个 .py = R7）也扫过**：去注释源码含 `/v1/responses` 的 **`RESP_PATH []`**（R8）。但**同名前缀噪音很多**：`prev*` 标识符今天 30 处 / 10 个文件（R8；逐处清单与行号见下）、含 `response` 的字符串常量 3 处（`tools/dsh_panel.py:1600` 那一段内嵌 JS 模板、`tools/serve.py:111` 的 docstring、`tools/serve.py:128 no_response`）⇒ **判据 3 只能钉 `tools/pool/gateway.py` 一个文件**，扫全 `tools/` 会被这 33 处假红。全仓那一条只留 `RESP_PATH == []` 做辅助 grep。

`prev*` 噪音清单（2026-11-20 05:37 逐文件 `grep -n` 实读；同一条 grep 可复核）：
`tools/pool/landing.py:1780/:1823 previous_pytest_total`、`tools/pool/route.py:545/:547/:550 previous`、`tools/pool/warmup.py prev_used`、`tools/pool_accounts.py:1759/:1789/:1790 previous`（草稿记的是 `:1620/:1650/:1651`，今天已漂）、`tools/sync_docs.py:286-289 prev_date`、`tools/trae_watch.py:177-199 prev_icon/prev`、`tools/wb_retention.py:208/:251/:385 pruneable_preview`、`tools/wb_session.py:113-120 prev`、`tools/web_live_check.py:811/:845 preview`、`tools/wt_prune.py:600/:773 preview_usage`。

## 缺口（逐条带现场原文与 文件:行号）

### 缺口 1 · 本仓没有 Responses 面，F10 的宿主协议不存在

- `tools/pool/gateway.py:99-104` 四键；`:98` 注释明写「不开 /v1/responses」。
- magpie 侧 `prev_response.go:218-220` 的第一道闸就是 `if from != provider.Responses { return w, r, body, nothing }`。
- ⇒ 「跟随」没有可挂的分支。这不是「实现成本高」，是**没有地方可写**。

### 缺口 2 · 「不移植」这件事今天零投影，下一个人会把它当「还没做」

- `grep -rn "chat/completions" docs/` 零命中；`grep -rn "/v1/responses" docs/` 零命中。
- scope 表 `:18` 今天写的是 `PORT / no`（R9），按 `:3` 的定义它就是「该移植、还没落地」——**错的方向**。
- 仓里已有「不移植」写进正文的先例，体例照抄：`docs/subsystems/pool/模型与号池.md:165-167` 逐字 `**F86 ③「按 95% 挑号」不移植**：pool 的候选池是同一个模型的多个号，窗口是模型属性不是号属性 ⇒` / `换号装不下还是装不下（\`tools/pool/gateway.py:184\` / \`:597\`）。按 95% 挑号需要 token 计数，` / `本仓没有分词器。所以本仓只做**发布读数**这一半，挑号那一半留给消费方。`

### 缺口 3 · 「原样透传」这件今天成立的事，一个钉子都没有

- `grep -n "calls\[0\]\[3\]" tests/test_pool_gateway.py` 零命中；`grep -n "PATHS" tests/test_pool_gateway.py` 零命中。
- 既有 `tests/test_pool_gateway.py:686-696` 只断言 `status == 404`（`:690`），**不断言 404 文案、不断言 `calls` 为空**；既有 `:820 assert body == payload` 是**响应体**透传（`test_non_streaming_upstream_is_passed_through`），不是请求体。
- ⇒ 今天要是有人把 `:1138 body=payload` 改成「顺手删掉不认识的字段」，**没有任何判据会红**。

## 判据（六条，逐条给「怎么证明」）

### 判据 1 · `/v1/responses` 仍是 404，且 404 路径一个请求都不转发

- 断言三条：`status == 404`；body 文案含 `只有四条`（`gateway.py:1088-1090`）；`stub.calls == []`。
- **怎么证明**：在 `tests/test_pool_gateway.py` 新增 `test_responses_path_is_404_and_forwards_nothing`（放在既有 `test_http_only_four_paths` **之后**，不复用它的名字、不改它一行）。写法照同文件既有体例：`port = start_server(_Stub(_ok()))`（`:688`）、`status, _, body = _request(port, "POST", "/v1/responses", body=payload)`（`:653` 的 `_request`，bytes 原样发）、`stub.calls`（`:617-619` 的 property）。
- 跑：`python -X utf8 -m pytest tests/test_pool_gateway.py -q -k "responses_path_is_404" -o addopts= --no-cov -p no:xdist`。

### 判据 2 · 带 `previous_response_id` / `store: false` 的 body 逐字节到 forward（「不移植」的兜底形态）

- 断言：`status == 200`；`len(stub.calls) == 1`；**`stub.calls[0][3] == payload`**（`_Stub.calls` 的元素是 `(model, account, url, payload)`，见 `tests/test_pool_gateway.py:614` 的签名与 `:111` 的 `calls` 类型 `list[tuple[str, str, str, bytes]]`）。
- payload 用**带三个怪字段**的 body：`{"model": MODEL, "previous_response_id": "resp_1", "input": "hi", "store": false}` —— 一个字段都不许在网关上被吃掉或改写。
- **怎么证明**：新增 `test_chat_body_with_previous_response_id_reaches_forward_verbatim`；跑 `-k "previous_response_id"`。这条是本卡真正的交付物：它证明「不移植」不等于「不支持」—— 调用方在 chat body 里写什么，网关原样送。

### 判据 3 · 源码级零 Responses 语义（tokenize + AST，**不许用纯文本 grep**）

- 三问全部断言为空 / False，且**只扫 `tools/pool/gateway.py`**：
  1. `tokenize` 去掉 `COMMENT` 后 `untokenize`，`"/v1/responses" not in code`（⇒ 只有注释能提它）；
  2. `ast.Constant` 里含 `response` 的字符串 == `[]`；
  3. `Name` / `Attribute` / `AsyncFunctionDef` / `FunctionDef` / `ClassDef` 名里含 `prev` 的 == `[]`。
- **怎么证明**：新增 `test_gateway_source_has_no_responses_semantics`，体例照同文件既有 AST 钉子 `tests/test_pool_gateway.py:573-584`（`:575 source = (ROOT / "tools" / "pool" / "gateway.py").read_text(encoding="utf-8")` / `:576 tree = ast.parse(source)` / `:579 ast.get_source_segment`）—— 同文件、同 `ROOT`、同 `ast`，不引新依赖。
- **为什么必须 AST/tokenize**：今天 `gateway.py` 里 `/v1/responses` 纯文本计数 = **1**（就是 `:98` 那条注释，R11 的 `PLAIN_COUNT 1`）。若写成 `assert source.count("/v1/responses") == 0`，它今天**红**；若写成 `<= 1`，则「哪天有人把注释改掉」就假红、「哪天有人真加代码」反而可能仍绿。实测见「反向变异」M3 / M4。
- **范围决策（写死，别扩）**：只扫这一个文件。全 `tools/` 扫会被 30 处 `prev*` 与 3 处 `response` 字符串**假红**（清单见上一节，R8）。

### 判据 4 · 端点侧也认不出 responses：`endpoint_protocol` 回空 + `pick_endpoint` 点名「不做协议翻译」

- 断言：`gateway.endpoint_protocol("https://x.test/v1/responses") == ""`；`gateway.pick_endpoint((CHAT_URL,), "responses", platform="codearts")` 回 `url is None` 且 `"不做协议翻译" in why`。
- **怎么证明**：新增 `test_responses_protocol_has_no_endpoint_and_is_named`。注意既有的 `tests/test_pool_gateway.py:258-268` 只钉了 `endpoint_protocol(...) == ""`（`:268`），**没有** `pick_endpoint(..., "responses", ...)` 的调用 ⇒ 这是新钉子；既有六条断言（`:261` / `:263` / `:265` / `:266` / `:267` / `:268`）**一个字都不许改**。

### 判据 5 · 文档投影：`模型与号池.md` 增一节写「F10 不移植」+ scope 表改判定

- `docs/subsystems/pool/模型与号池.md`（170 行、**纯 CRLF 170/170**，R4）在**文件末尾追加** `## 8. Responses 的 previous_response_id：不移植，原样透传`，内容照 `:165-167` 的「不移植」体例，必须写清三件：① 它是 Responses 协议的会话状态跟随；② 本仓没有 Responses 面（四条路径是 `gateway.py:99-104`，`:98` 明写不开），往 chat payload 里展开 = 改写 payload = 协议翻译（`gateway.py:919`）；③ 今天靠**原样透传**兜 —— 调用方写什么字段都原样送（判据 2 钉着）。
- **怎么证明**：新增 `test_f10_skip_is_written_into_the_model_doc`（读 `ROOT / "docs" / "subsystems" / "pool" / "模型与号池.md"`，断言含标题行、含 `SKIP_BY_REDLINE`、含 `原样`、含 `gateway.py:919` 这类可核指针）。★ 这条**今天不可能绿**（§8 还没写）—— 它是**交付投影的钉子**，不是现状钉子。既有入库钉子 `tests/test_pool_mcp.py:1040-1053` 只查 `| \`in_both\` |` 那一行与 `复盘/Trae-接入结论.md` 的逐字块，**不数行数、不查章节** ⇒ 追加 §8 不撞它，落地时必须重跑它证明没撞（见「验收」）。
- scope 表 `gates/diag/_magpie_scope.md:18` 改判定 + `:106` 改三个计数（改法见「结论」末段）。**怎么证明**：主树 `grep -n "F10" gates/diag/_magpie_scope.md` 必须回一行且含 `SKIP_BY_REDLINE`；`grep -c "^| .* | SKIP_BY_REDLINE |" gates/diag/_magpie_scope.md` 从 4 变 5（今天不加锚会数出 6 —— `:3` 判据定义与 `:106` 计数行也含这串，R9 实读）。该文件 gitignored、卡树里没有 ⇒ **只能当主树验收，不能当 pytest 输入**。

### 判据 6 · 闹钟：哪天有人开 Responses 面，这条判据自己红

- 三条断言：`"/v1/responses" not in gateway.PATHS`；`sorted(gateway.PATHS) == ["/v1/chat/completions", "/v1/messages", "/v1/models", "/v1/pool/routes"]`（顺序按字符串排序，实测如此）；`sorted(k for k in dir(gateway) if k.startswith("PROTOCOL_")) == ["PROTOCOL_CHAT", "PROTOCOL_MESSAGES"]`。
- **怎么证明**：新增 `test_alarm_responses_surface_stays_closed`；跑 `-k "alarm_responses"`。
- **为什么不用 `xfail`**：`xfail` 的语义是「预期失败」，这里是「预期它**仍然关着**」—— 关着就是绿。用 `xfail` 会得到相反语义（有人开面时才绿），那是把红线钉反。
- 为什么需要这条：判据 1 只钉 HTTP 面（要起服务、要 404），判据 6 是**同一件事的静态版本**，它连「有人在 `PATHS` 里偷偷加一条但忘了改 404 文案」都能红。

## 反向变异（四条 + 一条只改注释的安静对照，全部实测于起草时）

| # | 改哪一行（锚点原文） | 改成什么 | 哪条判据必须红 | 实测输出 |
|---|---|---|---|---|
| M1 | `tools/pool/gateway.py:104` `}` 之前（`PATHS` 字典末尾） | 加 `"/v1/responses": ("POST", PROTOCOL_CHAT),` | 判据 1（不再 404）与判据 6（`not in PATHS` 与精确清单两问） | `M1 ALARM_RED True True` |
| M2 | `tools/pool/gateway.py:1138` `body=payload, root=getattr(self.server, "root", None))` | `body=payload.replace(b"previous_response_id", b"x"), root=…` | 判据 2（`stub.calls[0][3] == payload`） | `BASELINE judge2 True` / `M2 judge2 False rewritten True` |
| M3 | `tools/pool/gateway.py:245` `return {"/v1/chat/completions": PROTOCOL_CHAT, "/v1/messages": PROTOCOL_MESSAGES}.get(path, "")` | 字典里加 `"/v1/responses": "responses"` | 判据 3（AST 常量出现 response）与判据 4（`endpoint_protocol` 不再回空） | `M3 SOURCE_CHANGED True judge3 (True, True, False)` |
| M4（**安静对照，只改注释**） | `tools/pool/gateway.py:98` `#: 四条路径，一个都不多（不开 /v1/responses、Gemini、Ollama 兼容、管理面）。` | 改成 `#: 四条路径，一个都不多。`（只删注释里的六个字） | **判据 3 / 6 都不许红** | `M4 SOURCE_CHANGED True judge3 (False, False, False) PLAIN_TEXT_COUNT 1 0` |

M4 是判据 3 写法的**存在理由**：纯文本计数从 1 变 0，只有 tokenize/AST 才不受注释影响。谁把判据 3 改回 `source.count(...)`，M4 就会红成假红。

（M1 的探针是内存里改对象 `gateway.PATHS["/v1/responses"] = ("POST", gateway.PROTOCOL_CHAT)`；M2 是替换 `gateway.route_once` 为改写 body 的版本；M3 / M4 是对源码字符串做 `str.replace` 后再跑同一个 `judge3()`。三个探针脚本起草时在 `gates/diag/_probe_tmp_F10mut*.py`，gitignored、0 出网。★ 2026-11-20 05:37 复核：这类产物今天都不在（R10），上表读数是**起草时的原样输出，本卡未复跑**；落地时重跑变异脚本再校一遍。）

## 交付

- `tests/test_pool_gateway.py`：**新增 6 个测试函数**（判据 1-6 各一个），并在文件头判据表 `:5-28` **末尾追加 6 行**（体例照既有行：`| \`test_xxx\` | 钉哪一位 |`）。既有 72 个 `^def test_`（R3 实读）**一个都不许改**。
- `docs/subsystems/pool/模型与号池.md`：**文件末尾追加** `## 8. …`（判据 5 的第一半）。既有 §1-§7（`:8` / `:20` / `:50` / `:68` / `:101` / `:114` / `:141`）与 `:165-167` 那段 F86 先例**一个字都不许改**。
- 复盘/卡/卡A384-F10-previous_response_id不移植只钉原样透传.md：卡文件本体（立卡时由 `tools/wb_stage_card.py` 生成骨架，正文用本文）。
- `gates/diag/_magpie_scope.md:18` + `:106`：**只读勘察产物，不入库**（`.gitignore` 覆盖 `gates/diag/`，`git ls-files gates/diag` 只有 `gate_lock.py`）⇒ 交付里写成「落地时的主树动作」，不写进 `files`。

## 卡域 files（精确路径，不写通配）

~~~toml
files = [
  "tests/test_pool_gateway.py",
  "docs/subsystems/pool/模型与号池.md",
  "复盘/卡/卡A384-F10-previous_response_id不移植只钉原样透传.md",
]
depends = ["A372", "A373", "A375", "A376", "A380", "A381"]
~~~

- **不写 `tools/pool/gateway.py`**：本卡钉的是「不移植」，一行代码都不改（探针只读它）。因此 A372 / A375 / A380 与本卡相交的只有 `tests/test_pool_gateway.py` 一处。
- **不写 `docs/subsystems/pool/README.md`**：它同时出现在 `tools/pool/landing.py:103 RECOUNT_DOCS = ("docs/subsystems/pool/README.md", "docs/INDEX.md")` 与 `:110 RESOLVABLE = (*DERIVED, *RECOUNT_DOCS)` 里 —— 落地链会重算 / 回退它，写进去等于给自己造冲突。
- **不写 `docs/subsystems/pool/modules.toml`**：今天被 A372 / A374 / A375 / A380 四张 pending 占着（`plan.load_backlog()` 实读，活跃卡 20 张 = R5；占者清单与 R6 同一条命令，把集合换成该文件即可）。
- **不写 `docs/changelog.d/*`**：落地链 ⑤′ 自动补。
- 不写通配（`tools/pool/plan.py:61-64` / `:283-291`：`files` 含 `*` `?` `[` 直接拒单，因为 `files_intersect()` 是**精确**集合相交）；不含 `PROTECTED_FILES`（`tools/pool/plan.py:46-53` 六份）。
- 精确相交六处：`tests/test_pool_gateway.py` 与 A372 / A373 / A375 / A376 / A380 撞，`docs/subsystems/pool/模型与号池.md` 与 A381 撞 ⇒ `depends` 写这六张（`plan.py:59` 只有 `pending` / `running` 参与冲突判定；六张今天全 pending = R6）。

## 验收（可直接跑）

~~~bash
# 0) 起卡树后，在 .wt/A384 里跑
cd .wt/A384

# 1) 六条新判据（判据 5 在 §8 写完后才绿；其余五条起草时已真跑绿）
python -X utf8 -m pytest tests/test_pool_gateway.py -q -o addopts= --no-cov -p no:xdist \
  -k "responses_path_is_404 or previous_response_id or no_responses_semantics or no_endpoint_and_is_named or f10_skip_is_written or alarm_responses"

# 2) 整个文件回归：既有 72 条 + 新增 6 条，一条都不许红
python -X utf8 -m pytest tests/test_pool_gateway.py -q -o addopts= --no-cov -p no:xdist

# 3) 证明没撞「同一份文档」的既有入库钉子（它读 模型与号池.md 的 in_both 行）
python -X utf8 -m pytest tests/test_pool_mcp.py -q -o addopts= --no-cov -p no:xdist -k doc_projections

# 4) 风格
python -X utf8 -m ruff check tests/test_pool_gateway.py

# 5) 主树验收（scope 表不入库，只能在主树改与核）
grep -n "| F10 |" gates/diag/_magpie_scope.md          # 必须一行，且含 SKIP_BY_REDLINE
grep -c "^| .* | SKIP_BY_REDLINE |" gates/diag/_magpie_scope.md  # 4 -> 5（★ 别用不加锚的 SKIP_BY_REDLINE：:3 定义与 :106 计数也含这串，今天会数出 6）
grep -n "PORT 共" gates/diag/_magpie_scope.md         # 69 -> 68
~~~

已知噪音：

- 判据 5 的 pytest 在 §8 写进文档**之前**必然红（这是设计，不是失败）。
- `tests/test_pool_gateway.py` 全量要起本地 HTTP 服务（`build_server` + `serve_forever`），本仓既有做法就是如此（`:622-632` 的 `start_server` fixture）；一个字节都不出网（文件头 `:30-31` 逐字「★ 全部用桩：…**一个字节都不出网**，也不往真的 `gates/diag/` 写。」）。
- `tools/pool/gateway.py:917` 逐字 `真发一次上游请求。★ 今天 chat_urls 全空 ⇒ **生产上走不到这里，未真机验证**。` —— 本卡也不做真机验证。

## 不许做

- **不许**改 `tests/test_pool_gateway.py` 既有 72 个测试的任何一个断言，尤其：`:686-696 test_http_only_four_paths`（只许原样留着，判据 1 是新函数，不许把文案断言塞进它）、`:258-268 test_pick_endpoint_never_guesses_from_base_url`（判据 4 是新函数）、`:801-811`（SSE 逐字节）、`:814-820`（响应体透传）。
- **不许**在 `tools/pool/gateway.py` 里加任何一行代码、注释、常量 —— 本卡不占该文件；`/v1/responses` 那条注释（`:98`）也不许动（它现在**恰好**是判据 3「注释里可以有、代码里不许有」的对照物）。
- **不许**开 `/v1/responses` 路径、不许加 `PROTOCOL_RESPONSES` 之类常量、不许写任何 `previous_response_id` 的展开 / 删除逻辑（= 协议翻译）。
- **不许**改 `docs/subsystems/pool/模型与号池.md` 的 §1-§7 与 `:165-167`（F86 先例）：只在**末尾追加** §8。
- **不许**改 `docs/subsystems/pool/README.md`（landing 的 `RECOUNT_DOCS` 会回退）、`modules.toml`（四张 pending 占着）、`docs/changelog.d/*`（落地链自动补）。
- **不许**改 `gates/diag/_magpie_scope.md` 的其它行（`:9` F1 的证据里 `:921/:930` 已过时、`:10` F2 是别的卡的判据）—— 本卡只动 `:18` 与 `:106`。
- **不许**碰仓外 `D:/repo/infra/**`（号池账本 `accounts.toml`、快照 `models.live.json`、日志）。
- **不许**跑 `scripts/run_gates.py` 全量（本卡只跑上面五条选测 + ruff）。
- **不许**把状态（内存 LRU / TTL / 256MB / 6h）搬进本仓任何形态（包括写进注释当「计划」）—— 没有宿主协议，搬进来就是死代码。

## 与已完成卡的关系 / 冲突

- **E94（号池网关同协议直通，done）**：本卡是它在 F10 这一条上的延长线。`复盘/卡/卡E94-号池网关同协议直通.md:61` 逐字 `- **不做协议翻译层**（不移植 magpie 的 \`forwardOnce\` / \`ir.go\` / \`decoderFor\`）。` —— 判据 1 / 3 / 4 / 6 都是这条决定的可核形态。**已 done，仅作读法参照，不进 depends。**
- **E143（F86，done）**：`gates/diag/_draft_F86.md:41` 给了「把判定改掉 + 带日期」的写法先例，本卡判据 5 照抄。**已 done，仅作读法参照，不进 depends。**
- **A368（F24，done）**：体例来源（抬头 / 前情 / 缺口 / 判据 / 交付 / 验收 / 不许做 / 未坐实项）。它的 `tools/pool/gateway.py` 改动已落地，本卡只读它。**已 done，仅作读法参照，不进 depends。**
- **A372（pending，F56）、A373（pending）、A375（pending）、A376（pending）、A380（pending）**：五张都占 `tests/test_pool_gateway.py` ⇒ 全部写进 depends（R6 实读；本卡只撞这一个文件，不碰它们的其它文件）。
- **A381（pending，F14）**：占 `docs/subsystems/pool/模型与号池.md`（它要在同一份文档里写自己的不移植一节）⇒ 写进 depends。
- **A367 / A370 / A371（已 done）**：草稿写它们与 A372 一起 pending 占 `docs/subsystems/pool/modules.toml`，**今天已不成立** —— 这三张已 done（`plan.load_backlog()` 实读），modules.toml 现占者是 A372 / A374 / A375 / A380（R6 同款命令，集合换成该文件）。本卡照旧不碰该文件。
- **F2（三协议互译，SKIP_BY_REDLINE）**：F10 与它同一条红线段，但**不是同一条功能**（F2 是翻译，F10 是状态跟随）。本卡把它标成 SKIP_BY_REDLINE 的理由必须写成「无挂载点」而不是「属于 F2」—— 否则别人会以为 F2 松了它就能自动落。

## 未坐实项（如实标注，别当成结论）

1. **判据 5 的后半（scope 表）没法用 pytest 钉**：`gates/diag/_magpie_scope.md` 在 `.gitignore:70-77` 覆盖范围内（`git ls-files gates/diag` 只有 `gate_lock.py`），卡树 `.wt/A384` 里**没有**这份文件 ⇒ 只能主树 grep 验收。
2. **`tools/pool/gateway.py:16-17` 的自引用已经漂了**：逐字 `（见 gateway.py:184 / :597）`，而今天 `:184` 是注释行 `判据（卡 E94 判据 1，照勘察件 §5.5 的方案 B）：`、`:597` 是 `status=status, started_at=started_at, root=base)`（2026-11-20 05:37 逐行回读）。**本卡不修**（gateway.py 不在本卡域），登记给后续卡。
3. **scope 表 `:9` 的 F1 行证据也已过时**（写 `tools/pool/gateway.py:94-97`、`:921/:930`），今天 `:94-97` 是 `CHUNK_BYTES` / `DEFAULT_PROTOCOL` / `PROTOCOL_CHAT` / `PROTOCOL_MESSAGES`，`:921/:930` 不是那句话。**不属本卡**，只登记。
4. **magpie 侧未做运行验证**：Go 项目未编译、未跑 `prev_response_test.go`。所有 Go 语义都来自**逐行读源码**（2026-11-20 05:37 回读 `:216-220` / `:257-259` / `:246-252` / `:40-46`，与草稿引文逐字一致），不是实测行为。
5. **判据 3 的「全仓零」只用辅助 grep 表述**：`RESP_PATH == []` 那条扫的是 `tools/` 全部 149 个 .py（R7）的**去注释源码**，今天成立；但它没有进 pytest（会因为 `scripts/` 未扫而语义不完整）⇒ 本卡只在文档里写它是「辅助证据」。
6. **没有验证真实上游对 `previous_response_id` 的反应**：`gateway.py:917` 明写 `chat_urls` 全空、生产上走不到 `forward_http`，本卡不碰这条。
7. **探针与变异读数是起草时的**：`gates/diag/_probe_tmp_F10*.py` 今天不在（R10），「前情」里的 404 / byte-identical 输出与「反向变异」四条读数**未复跑**；能复跑的那一半（tokenize + AST，R11）本会话已复跑并一致。落地时用 R6 / R8 / R11 的脚本 + 重写变异脚本再校。
8. 本文所有行号实测于 `7a4cc513`；落卡时（`f7d4d305`）复核 `git diff --stat 7a4cc513..HEAD -- tools/pool/gateway.py tests/test_pool_gateway.py docs/subsystems/pool/模型与号池.md gates/diag/_magpie_scope.md` **输出为空**（R12）⇒ 行号仍有效。落地时若 HEAD 再前进，先跑同一条命令，**输出为空则行号仍有效**，不空就只重核它点到的文件。

（本文件于 2026-11-20 由 `T-AG672` 物化自立卡草稿 `gates/diag/_draft_F10.md`；它就是卡规格本体，不是草稿。）
