# 卡 A373：F94 图像识别替身（seer）—— 判 SKIP_BY_REDLINE

> 台账号 T-AG661｜分区 A（magpie 移植 / 号池 pool）｜树 .wt/A373｜层 判据层 + 不移植证据｜基准 7a4cc513（立卡时主树 HEAD，2026-11-19 23:50 实读）｜depends E94、A362、E143

> depends 说明：E94 是号池网关本体（tools/pool/gateway.py 的四条路径与 classify 七值表都在它名下）—— 本卡只**加钉子、不改它一行**；A362 是「MCP 那一行有多长才算太长」，本仓唯一引证过 magpie vision_mcp.go:34 常量值的地方就在它名下（tools/pool_mcp.py:281-284）；E143（F86 ③）刚给 ModelEntry 加了两个窗口字段，判据 4 钉的是**它之后**的字段集合，所以必须 depends 它。

> 基准说明：起草时主树 HEAD = 466a2578（git rev-parse --short HEAD 实读，2026-11-19，提交「feat(pool): 上下文窗口读数进模型清单…（T-AG657）」）。起草中途基准从 08364825 跳到 466a2578，把 ModelEntry 从五个字段变成七个（多了 context_window / max_output）—— 本文行号与字段集合**全部按 466a2578 重核过**。起草收尾时 HEAD 又前进到 35930ab1（只改 docs/workbacklog.toml：「卡 A367 的域加上 docs/subsystems/pool/modules.toml」），本文引用的产品码与测试行号逐条重核过、未漂移。落地前按当时 HEAD 再核一次。

> 依据：gates/diag/_magpie_scope.md:102（F94 现判 PORT / landed=no）、:3（三值口径「PORT / SKIP_BY_REDLINE（永不做协议翻译层）/ SKIP_NOT_APPLICABLE（不可移植资产）」）；magpie 原件 D:/repo/program/_ext/magpie-main/internal/gateway/ 下的 vision.go（538 行）、vision_mcp.go（201 行）、side_effort.go（104 行）、gateway.go、routing.go、image_input.go。

## 前情：magpie 的 seer 到底是什么（三根支柱 + 一个工具面）

> 本节逐行读过原件。行号相对 D:/repo/program/_ext/magpie-main/internal/gateway/。

**支柱一 · 在网关内部把图换成文字（body 改写）。** seer() 只是选一个「能看图」的模型当替身，函数头在 vision.go:119：

    func seer() (string, bool)

vision.go:120-131 三个分支：Settings 的 Vision 为 off ⇒ 返回空串与 false；为空 ⇒ 落到 AutoVision()；非空且 pickedMissing(v) 为空串 ⇒ 返回 v 与 true。:113-118 的注释逐字：「the Settings' Vision while it resolves, else AutoVision's. None when Vision is off or no model sees.」

真正的改写发生在 seenBody()（vision.go:442 起，到 :494）：walkImages 收集去重后的图片 src → 并发 describe()（visionParallel = 4，:49）→ 每张图换成一段 textBlock，逐字（:492）：「[Image, as <替身模型> describes it for this model, which can't see images:]」+ 描述正文 +「[End of the image's description]」。

当前轮描述失败 ⇒ 直接 return error；旧轮 / 工具结果里失败 ⇒ 换成「[Image omitted: this model accepts text only, and the image couldn't be described.]」；当前轮 src 为空 ⇒ errors.New("the image is a file only its vendor can open")。描述缓存键是 sha256(model + 零字节 + visionEffort(model) + 零字节 + src)（:316-360），失败不缓存。替身自己发请求时打的是自己的 chat 端点 http://magpie/v1/chat/completions（:368-436），User-Agent 是 VisionAgent = "magpie-vision/1"（:39）。

**支柱二 · 按上游措辞判「这个模型不吃图」。** vision.go:515 的 imageRefusedWords 是一条**认厂商措辞**的正则，注释里逐字列了它要认的几家：DeepSeek 的 unknown variant image_url、Responses 的 input_image、OpenAI 的 image_url is only supported by certain models、OpenRouter 的 No endpoints found that support image input、vLLM 的 is not a multimodal model，以及 不支持图片。imageRefused(status, body)（:520-527）**只认 400 / 415 / 422**；命中后 refuseSight(pid, model)（:532）把 pid 与 model 拼起来记进 s.blind，以后 blindTo()（:102-111）就先认它瞎。

**支柱三 · 同一候选改写 body 后立刻重试（不换号先改）。** gateway.go:3260-3286：上游回 400/415/422 且正文命中那串措辞、且请求里真有图 ⇒ s.refuseSight(...)，然后改写 body、把这次尝试标记成 failSight、**把候选指针退回去重来一次**（i--; continue）—— 同一个候选在别的候选之前立刻重试（routing.go:305：failSight = "sight"）；group 路径同理（gateway.go:2473-2478 的 seenGroup = sync.OnceValues(...)、:2757-2759）。另有 image_input.go:19 的 textOnlyBody(proto, body) 与 :11 的 imageOmitted = "[Image omitted: this model accepts text only.]"（:33 的 hasImage 与 :24 的 `return textBlock(proto, imageOmitted), nil` 是同一族） —— 同一类「按协议改写 wire JSON」的活。

**工具面 · 把 seer 开成 MCP 工具。** vision_mcp.go:28 VisionMCPPath = "/mcp/magpie/vision"、:30 visionMCPTool = "analyze_image"、:34 visionMCPBody = 32 << 20；gateway.go:836-837 用 mux.HandleFunc(VisionMCPPath, s.visionMCP) 挂上去，:879 的 apis 清单里另外还有 /v1/images/generations、/v1/images/edits。工具实现 visionMCPRun（:111-148）：seer 不存在 ⇒ 「magpie has no model that sees images…」、Vision 为 off ⇒ 「Image recognition is off in magpie…」；mcpImageSrc（:153-200）只认 data:image/、http(s)、file:// 与 ~/，相对路径拒、非本机请求拒、目录 / 超 20MB / DetectContentType 非 image 全拒。

一句话：seer = **改写客户端 body** + **按措辞判上游** + **同候选改写后立刻重试**，外加一个能读本机文件的 MCP 工具面。

## 缺口：本仓今天有没有这个东西 —— 完全没有（不是「有代码没接线」）

**缺口 1 · 没有任何图像路径。** tools/pool/gateway.py:97-103：

    #: 四条路径，一个都不多（不开 /v1/responses、Gemini、Ollama 兼容、管理面）。
    PATHS: dict[str, tuple[str, str]] = {
        "/v1/chat/completions": ("POST", PROTOCOL_CHAT),
        "/v1/messages": ("POST", PROTOCOL_MESSAGES),
        "/v1/models": ("GET", ""),
        "/v1/pool/routes": ("GET", ""),
    }

未知路径一律 404（:981，文案「没有这条路径：…。本网关只有四条：…」）；方法不对回 405 且带 Allow: GET, POST（:972-975）。实测 tuple(gateway.PATHS) == ('/v1/chat/completions', '/v1/messages', '/v1/models', '/v1/pool/routes')。

**缺口 2 · 生产代码里一个图像相关的标识符都没有。** 本次实测（2026-11-19，466a2578）：

- grep -rn -F 'seer' tools/ scripts/ ⇒ **0 行**。（gates/diag/_magpie_scope.md:102 现写的「grep seer 只命中 task.RefuseError」**不精确**：-i 能命中的十几处全是 provisional 的子串，RefuseError 本体不含 seer。）
- grep -rn -E 'failSight|refuseSight|seenBody|textOnly' tools/ ⇒ **0 行**。
- grep -rn 'v1/images|mcp/magpie|analyze_image' tools/ scripts/ docs/ tests/ ⇒ **0 行**。
- grep -rn -i -E 'image|vision|modalit' tools/pool/*.py ⇒ 只有 tools/pool/checkin.py:130-142 的 provisional 子串（函数名、docstring、报错文案）。

全仓唯一真提 vision 的生产代码是注释：tools/pool_mcp.py:281-283 逐字「照 magpie internal/gateway/mcp.go:83 的 readMCPBody(w, r, 32<<20)（vision_mcp.go:34 的 visionMCPBody 也是同一个值）」，紧跟 :284 的 MAX_LINE_BYTES: int = 32 << 20 —— 那是 **MCP 一行的字节上限**（A362 的判据），不是图像通道。

**缺口 3 · 模型注册表没有模态维度，而且多写一个键也不会报错。** tools/pool/model_registry.py:135-149：

    @dataclass(frozen=True)
    class ModelEntry:
        """一条注册表记录：``alias / pool / id / default / note`` + 两个**可选**窗口字段。

        ★ 卡 E143（F86）：``context_window`` / ``max_output`` **缺字段 = 不知道（None）**，不是 0。
        ...
    alias: str
    pool: str
    id: str
    default: bool
    note: str = ""
    context_window: int | None = None
    max_output: int | None = None

实测 dataclasses.fields(mr.ModelEntry) ⇒ ['alias', 'pool', 'id', 'default', 'note', 'context_window', 'max_output'] —— **七个字段里没有一个是模态**。_parse_model_entries（:184-220）只强制 ("alias", "pool", "id") 三个键（:197），构造时只读 default / note / context_window / max_output ⇒ **往 toml 里加 images = true 既不报错也不进 ModelEntry**（静默忽略，这是最坏的一种假进展）。load_registry()（:276）今天 **4 条**，pools = ['codearts', 'codebuddy']，any(hasattr(e, 'images'/'vision'/'modalities')) ⇒ **False**。仓内 tools/pool/model-registry.toml 的 grep -c -i -E 'image|vision|modalit' ⇒ **0**（context_window 已出现 2 次，说明窗口维刚进来、模态维仍空）。

**缺口 4 · 仓外也没有可采信的模态数据源。** D:/repo/infra/pool/models.whitelist.toml（1578 字节，只有 [[approved]] 的 pool/model/by/at/note）与 accounts.toml（3457 字节），grep -i -E 'vision|modalit|image|sees' ⇒ **两者都 0**。也就是说：即使今天硬写一条「按模态挑替身」的判据，也**没有可采信的数据源** —— 要么编，要么造。

结论：F94 在本仓是 **完全没有**（既不是「有代码没接线」，也不是「接线了没开」）。唯一痕迹是上面那条引证用的注释，以及一次都没接的字段空位。

## 为什么不移植：三条支柱逐一撞在既有红线/判据上（SKIP_BY_REDLINE）

**对撞一 · 改写客户端 body。** tools/pool/gateway.py:1-24 的模块头写着四条硬边界，:3-5 逐字：「只搬「选号 → 转发 → 换号 → 留痕」这条链。**不搬**它的协议翻译层（forwardOnce / ir.go / decoderFor）：客户端说 Chat 就只往 Chat 端点发，说 Messages 就只往 Messages 端点发，SSE 逐字节转发。」:8 逐字：「1. **不做协议翻译**：上游只回流式、调用方要非流式 ⇒ 400 拒绝并说明，绝不自己攒流。」gates/diag/magpie-gateway-recon.md:405 逐字：「**不做协议翻译**。pool 没有 ir.go 那层，也不打算有 …… **只做同协议转发** …… 协议 mismatch 直接 400 拒绝，不猜。」:606 更直白：「**不要移植协议翻译层，只做同协议直通 + 选号。** …… 翻译层永远不做。」

seenBody() 要做的正是「读客户端 wire JSON → 改 messages 里的 image 块 → 重编码」—— 与 textOnlyBody() 同族，是按协议改 body 的活。**红线覆盖。**

**对撞二 · 按上游措辞判失败。** tools/pool/gateway.py:19-24 逐字：「★ 这里的 classify() 与 pool_quota.classify() **不是一回事**…… 这里的 classify(status, body: bytes|dict|None) 七值，**只看状态码与结构化字段**（error.type / error.code 这类枚举值里的 insufficient_quota），**绝不解析自由文案**（含中文提示语）。网关每条请求背后都可能是不同上游，正文措辞不可信。」:194-195 在函数 docstring 里再写一遍：「★ 绝不解析自由文案：正文写「额度用完了」「余额不足」都只是 bad_request / server —— 网关背后可能是任意上游，措辞不可信，只认枚举值。」（注意 :19-21 同时承认 pool_quota.classify 是**看自由文案正则**的五值 —— 那是额度账本那一侧，与本网关这一侧刻意分开，不许拿来当先例。）

imageRefusedWords 恰恰是**一张按厂商措辞认字符串的表**。本次实测本仓 classify 对这些措辞的判决（这就是今天的真值）：

| 状态码 + 上游原文 | 本仓判 |
|---|---|
| 400 + DeepSeek「Failed to deserialize … unknown variant image_url, expected text」 | bad_request |
| 415 + vLLM「is not a multimodal model」 | bad_request |
| 422 +「不支持图片」 | bad_request |
| 403 + OpenRouter「No endpoints found that support image input」 | auth |

前三条落在 bad_request（:210-211 那句 if 400 <= status < 500: return KIND_BAD_REQUEST），第四条落在 auth（:204-205 的 401/403 分支）—— 也就是说「模型不吃图」在本仓**没有、也不许有**专门通道；有的话就得先破 :194-195 这条明文禁令。

**对撞三 · 同候选改写后立刻重试。** tools/pool/gateway.py:600-601 逐字：

    if kind in (KIND_OVERFLOW, KIND_BAD_REQUEST):
        break  # 不换号：换号也装不下 / 是请求本身不对，原样透传

bad_request 的语义是「请求本身不对，原样透传、一次都不重发」，_exhausted（:663-664）也是「不换号那两类：最后一次上游的 status + body 原样透传（不包装）」。seer 要的却是「422 之后把 body 改了、同一个号再试一次」—— 与这条 break 的语义正面相反。tests/test_pool_gateway.py:417-424 把这条钉成了断言：assert len(forward.calls) == 1, "bad_request 不换号（换号也装不下）"。

**结论：判 SKIP_BY_REDLINE，不是 SKIP_NOT_APPLICABLE。** 它不是「宿主不可移植的资产」（如账号登录流、凭据发现），而是**能做、但做了就破本仓三条明文边界**的活。所以本卡的产物不是代码，而是：①三条「不移植」的行为钉子（判据 1~3）；②一条「注册表没有模态维」的形状钉子（判据 4）；③一条把「不移植」写进 tracked 文档的证据（判据 5）。

## 判据（五条，逐条给「怎么证明」）

### 判据 1 · 路径只有四条，图像路径一个都不认

/v1/images/generations、/v1/images/edits（magpie gateway.go:879 有）、/mcp/magpie/vision（magpie vision_mcp.go:28）在本仓必须**一律 404**，且 PATHS 的键集合逐字钉死。

- **怎么证明**：tests/test_pool_gateway.py:686 的 test_http_only_four_paths **同一个函数内**追三条断言（照 :689-690 现有写法 `status, _, _ = _request(port, "POST", "/v1/images/generations", body={"model": MODEL})` 后 `assert status == 404`），并追加 `assert tuple(gateway.PATHS) == ("/v1/chat/completions", "/v1/messages", "/v1/models", "/v1/pool/routes")`。**不新建函数** —— 这条钉子的语义就是「只有四条」，拆开就散了。

### 判据 2 · classify 对「模型不吃图」的措辞仍只按状态码判

上游明说「不认识 image_url」「不是多模态」「不支持图片」时，本仓仍然只按状态码判 —— 措辞一个字也不算数。

- **怎么证明**：在 tests/test_pool_gateway.py:186-193 的 `@pytest.mark.parametrize("body", [...])` 表里加三项（400 的 `unknown variant image_url, expected text`、415 的 `is not a multimodal model`、422 的 `不支持图片`），沿用 :196-198 那三行断言（400⇒bad_request、503⇒server、429⇒rate）。**不要加 403 + No endpoints found that support image input** —— 实测它判 auth（gateway.py:204-205），与「措辞不生效」这条钉子不是一回事，硬塞会让判据 2 变成一条永远解释不清的红。

### 判据 3 · 带图请求只发一次，body 一个字节不改

上游以「不吃图」拒掉之后，本仓**不许**改写 body 重试，也不许换号重发（bad_request 的既有语义）。

- **怎么证明**：tests/test_pool_gateway.py 新建 `test_image_request_is_one_forward_call(env)`，直接调 gateway.route_once(...)（_run 在 :123-134、body 写死在 :131 的 `b'{"model":"x"}'`，本用例要自带 body，所以照 :129-134 的形状自己拼一次；_Forward 桩在 :106-116，calls 第 4 位是 payload —— :111 的类型注解 `list[tuple[str, str, str, bytes]]` 就是锚）。body 用一条带 image_url 的 chat JSON，forward 回 422 + `unknown variant image_url`。断言两条：`assert len(forward.calls) == 1` 与 `assert forward.calls[0][3] == body`（逐字节相同 = 没被 seenBody 那类改写碰过）。起草时手跑同样条件实测：n_calls 1、seats ['codearts-1']、payload_identical True。

### 判据 4 · 注册表条目的形状里没有模态维

ModelEntry 的字段集合必须逐字是**今天这七个**；真表 4 条也不许带 images / vision / modalities 属性。

- **怎么证明**：tests/test_model_registry.py 新建 `test_model_entry_has_no_modality_dimension()`（该文件今天 `grep -n 'ModelEntry|dataclasses|fields('` ⇒ 只命中 :46 的 `_write_registry`，没有一处碰 ModelEntry 形状 ⇒ 是新空位；体例见 :1-42 的 docstring「## 钉什么」+ `sys.path.insert(0, str(ROOT / "tools"))` + `from pool import model_registry as mr`）。断言 `{f.name for f in dataclasses.fields(mr.ModelEntry)} == {"alias", "pool", "id", "default", "note", "context_window", "max_output"}`；再对 `mr.load_registry()` 逐条 `assert not any(hasattr(e, k) for k in ("images", "vision", "modalities"))`。第二条依赖宿主真源（未设 TF_MODEL_REGISTRY 时读仓内 tools/pool/model-registry.toml，今天 4 条）—— 与文件里既有的读真表用例同一个体例；要完全隔离可用 :46-51 的 `_write_registry`，但那样证明不了「真表今天没有模态字段」，两条都留更好。

> ★ 这条判据**故意把 context_window / max_output 写进期望集合**：E143 刚加的窗口维是合法的「模型属性维」，模态维不是 —— 混为一谈的人会顺手把 images 也加进来，而这条断言会当场拦住。

### 判据 5 · 「不移植」这件事本身有 tracked 证据

SKIP 不能只活在 gitignore 的 gates/diag/ 里（docs/subsystems/pool/README.md:78 逐字：「卡树里的 gates/diag/ 是 gitignore 的，写进去等于没写」）。证据落在表 B「pool 不做的事」。

- **怎么证明**：在 docs/subsystems/pool/README.md:172（现表 B 第 7 行「不做技能口径」）之后加第 8 行：不做 = 「图像识别替身（seer）：改写客户端 body 把图换成文字 / 按厂商措辞判『拒图』/ 同候选改写后立刻重试」；归谁 = magpie 原件 internal/gateway/vision.go；证据 = tools/pool/gateway.py:97-103、:194-195、:600-601 与 tests/test_pool_gateway.py:686、:194。三条硬读数：① `grep -c '^| 8 |' docs/subsystems/pool/README.md` == 1；② 新增行里不含「未来会做」（:183-184 的越界判据明写：出现『未来会做』即判不通过）；③ `python -X utf8 scripts/gen_pool_readme.py --check` **exit 0**（证明标记外手改没弄坏生成块；起草时实测 exit 0，输出「[OK  ] docs/subsystems/pool/README.md 与现算一致（50 个文件 / 20462 行 / 2026-11-19）」）。

## 反向变异（四条，外加一条只改注释的安静对照）

脚本一次跑完，落 gates/diag/_rev_F94.py（gitignored，**不当长期钉子**），末行打印「结论：4/4 咬住 + 1 条安静对照未响」，每条跑完自己 `git checkout --` 复原。

| # | 改哪一行（锚点原文） | 哪条判据红 | 怎么红 |
|---|---|---|---|
| M1 | tools/pool/gateway.py:103 的右花括号（PATHS 收尾那行）之前插 `"/v1/images/generations": ("POST", PROTOCOL_CHAT),` | 判据 1 | `tuple(PATHS)` 不等；且该路径不再 404（会被转发，桩回 200） |
| M2 | tools/pool/gateway.py:210 的 `if 400 <= status < 500:` 之前插 `if 400 <= status < 500 and isinstance(obj, dict) and "image" in str(obj).lower(): return KIND_OVERFLOW` | 判据 2 | 参数表里 400 / 415 / 422 三条从 bad_request 变 overflow |
| M3 | tools/pool/gateway.py:600 的 `if kind in (KIND_OVERFLOW, KIND_BAD_REQUEST):` 之前插「BAD_REQUEST 且 payload 带 image_url ⇒ 改写 body、`i -= 1`、`continue`」 | 判据 3 | forward.calls 变 2 条（第一条 payload 相同、第二条不是） |
| M4 | tools/pool/model_registry.py:149 的 `max_output: int | None = None` 之后加 `images: bool = False` | 判据 4 | fields() 名字集合多一个 images；真表属性断言仍绿，形状断言红 |
| N1 | **只改注释**：tools/pool/gateway.py:97 的「不开 /v1/responses」改成「不开 /v1/responses 等」 | 无 | 五条判据全绿 —— 安静对照，证明钉子咬的是行为不是文字 |

> M2 / M3 是「把 seer 的三根支柱各塞一条进去」的最小模拟，不是要真实现；M3 那句必须自己造一个「改写后的 body」再 `i -= 1`，否则只是重复调用同一份 payload，测不出改写。

## 交付（逐文件）

- `tests/test_pool_gateway.py` —— 在 :686 `test_http_only_four_paths` 同函数内追三条 404 断言 + 一条 PATHS 键集合断言；在 :186-193 的 parametrize 表加三条措辞用例；新建 `test_image_request_is_one_forward_call`。**既有断言正文一字不改**（:688-696、:196-198、:424）。
- `tests/test_model_registry.py` —— 新建 `test_model_entry_has_no_modality_dimension()`（七字段集合 + 真表无模态属性），放文件末尾、沿用该文件「## 钉什么」的 docstring 体例。
- `docs/subsystems/pool/README.md` —— 表 B 加第 8 行（不做 / 归谁 / 证据三列齐全，证据必须是真路径）。只在 pool-margin 标记**之外**（:92 之后）改，标记内 (:11-92) 一个字节不动。
- `复盘/卡/卡A373-F94图像识别替身seer-判SKIP_BY_REDLINE.md`（计划建）—— 由本草稿转正；抬头台账号替换为真号、树名替换为 .wt/A373、基准换成立卡时主树 HEAD。
- docs/changelog.d/T-AG661.md（计划建）—— 落地时按台账号改名，写「F94 判不移植 + 表 B 第 8 行 + 五条判据」。

> **卡域里不列 `tools/pool/gateway.py` 与 `tools/pool/model_registry.py`**：本卡产品码一个字不改（判据 1~4 全是「现状已成立、只要钉住」）。这正是这条 SKIP 的分量所在 —— 如果哪天有人要动这两个文件，那是另一张卡，得先把「为什么不移植」这篇推翻。

## 验收（可直接跑）

```bash
cd .wt/A373
python -X utf8 -m pytest tests/test_pool_gateway.py tests/test_model_registry.py -q -o addopts= --no-cov
python -X utf8 -m pytest tests/test_pool_gateway.py::test_http_only_four_paths tests/test_pool_gateway.py::test_classify_ignores_free_text tests/test_pool_gateway.py::test_image_request_is_one_forward_call tests/test_model_registry.py::test_model_entry_has_no_modality_dimension -q -o addopts= --no-cov
python -X utf8 -m ruff check tests/test_pool_gateway.py tests/test_model_registry.py
python -X utf8 scripts/gen_pool_readme.py --check
grep -c '^| 8 |' docs/subsystems/pool/README.md
python -X utf8 gates/diag/_rev_F94.py
```

已知噪音（别当红）：

- `-o addopts= --no-cov` 必须带：仓内 pyproject.toml:51 的默认 addopts 是 `-q -m "not acceptance and not chain" --cov=timeflow --cov-fail-under=70`，全量跑一个文件也会因覆盖率不达标而红。起草时按本条验收的第一行实测过：`pytest tests/test_pool_gateway.py tests/test_model_registry.py -q -o addopts= --no-cov` ⇒ 122 passed in 10.12s（466a2578，主树）。
- 判据 3 与判据 1 是**新建/新加**，第一次跑会是新增用例；它们在 .wt 里跑，主树今天还是 0 条。
- `scripts/gen_pool_readme.py` **未接门**（`grep -rn gen_pool_readme gates/defs/ scripts/run_gates.py` 全 0 命中），所以这条必须手跑；但落地链会跑 `scripts/check_derived_docs.py`（tools/wb_land.py:124-128 的 DERIVED_TARGETS 含 docs/subsystems/pool/README.md）—— 生成器 --check 绿了它才绿。
- 反向变异脚本跑完要 `git checkout -- tools/pool/gateway.py tools/pool/model_registry.py` 复原；**不许**把变异带进落地提交。

## 不许做

1. **不许动** `tools/pool/gateway.py:98-103` 的 PATHS 四键、`:194-195` 的 classify 判据注释、`:200-212` 的七值分支、`:600-601` 的 BAD_REQUEST break、`:663-664` 的透传分支。本卡只在测试里**加**断言。
2. **不许改** `tests/test_pool_gateway.py:196-198`、`:424`、`:689-695` 这三处既有断言的正文 —— 只许在同一函数、同一参数表里追加用例。
3. **不许**把判据写进 `gates/diag/`：`docs/subsystems/pool/README.md:78` 逐字「卡树里的 gates/diag/ 是 gitignore 的，写进去等于没写」。本草稿与 `_rev_F94.py` 都只是过程产物。
4. **不许碰** `tools/pool/plan.py:46-53` 的六份 PROTECTED_FILES（docs/traceability.toml、docs/changelog.md、复盘/交接-重构进度.md、复盘/新窗口交接卡.md、gates/last.json、gates/reuse.json）。
5. **不许改仓外** `D:/repo/infra/**`：models.whitelist.toml 与 accounts.toml 今天都没有模态字段（grep -c -i 'image|vision|modalit|sees' 均 0），硬塞一个「images」等于造假数据源。
6. **不许真去实现** seenBody / imageRefused / refuseSight / textOnlyBody / visionMCPRun —— 本条 SKIP 的整个意思就是不移植它们。
7. **不许把未建的文件写成反引号路径**：本仓 f432cd34 那笔提交（`fix(docs): 七份 pool 卡规格把「计划建」的路径写成反引号 ⇒ 死指针回涨到 200（基线 147）`）就是这么红的，08364825 又为同族问题再修一次（`E144 规格里那条 enggate-logs 读数路径是死指针（dead_refs 148 > 基线 147）`）；本草稿里凡未创建的文件都写「（计划建）」且不加反引号。

## 与已完成卡的关系

- **E94**（号池网关同协议直通，tools/pool/gateway.py 本体）：F94 之所以是 SKIP，根子在 E94 的红线；本卡不改 E94 一行，只把它「不做协议翻译 / 不解析文案 / 不换号」三条写成钉子。
- **A362**（MCP 那一行有多长才算太长）：本仓唯一引证过 magpie vision_mcp.go:34 常量值的地方（tools/pool_mcp.py:281-284）。A362 搬的是 MCP 帧长判据，**不是** vision 工具面；本卡不碰 pool_mcp.py。
- **E143**（F86 上下文窗口与回复上限，卡 T-AG657，status=done）：刚给 ModelEntry 加了 context_window / max_output，且它自己就是「一半做、一半判 SKIP_NOT_APPLICABLE」的先例（卡规格 :38 逐字「③ 到 95% 把一个请求迁移给组里装得下的成员 | SKIP_NOT_APPLICABLE（需重新定义）」、:77「判据 4 · 「95% 迁移」判为不移植，并把理由钉住（不是遗漏）」）—— 本草稿学的是它「把不移植写成可核判据」的写法。判据 4 的期望集合包含它俩，就是为了区分「合法属性维」与「模态维」—— 前者已被 E143 裁定要做，后者本卡裁定永远不做。
- **A368**（窗口维度的模型过滤）：同一族「模型属性维」的正面案例（做了），与本卡形成对照：窗口维影响选号与配额采信，模态维只影响 body 改写，而 body 改写是红线。

## 未坐实项（草稿如实标注，别当成结论）

- **未坐实**：magpie seer 的**运行时行为**只有文档级证据。功能清单 `D:/repo/program/_ext/_magpie_features.md:790` 的核实等级逐字是「已核 internal/gateway/vision_mcp.go、internal/gateway/side_effort.go（存在性）；判据为仅文档 docs/subsystems/gateway-routing.md」—— 意思是「文件在、文档这么写」，不是「实测过它怎么跑」。本卡列的 magpie 行号与正文都是**读源码**所得，未跑 magpie 本体。
- **未取证**：magpie 侧 `vision_test.go`、`vision_mcp_test.go`、`vision_refused_test.go`、`vision_missing_test.go`、`vision_enabled_test.go`、`vision_unknown_test.go`、`vision_wait_test.go`、`vision_agents_test.go`、`vision_ark_plan_test.go`、`modelspec_test.go`（TestAutoVisionTakesTheUsersVision）共 10 份测试**只列过文件名、内容未读**。若日后要争「seer 的降级顺序到底是 tier 优先还是 cost 优先」，必须回去读这些。
- **未坐实**：`gates/diag/_magpie_scope.md:102` 对 F94 的证据列写「grep seer 只命中 task.RefuseError，无图像识别替身」—— 实测 `grep -rn -F 'seer' tools/ scripts/` 是 **0 行**（RefuseError 里不含 seer 子串，-i 命中的都是 provisional）。该行结论（判 PORT、landed no）方向没错，但**证据列不精确**；本卡转正时应顺手改成实测读数（不过该文件 gitignore，改它不进提交）。
- **未坐实**：magpie `internal/gateway/vision.go:218-255 autoVision()` 的 tier 排序（claude 0 / codex 1 / 无账号 2 / 其它 3）读自源码，未与 `modelspec_test.go` 的期望对齐 —— 本卡不依赖这个顺序（SKIP 的理由是「改写 body」本身，不是「怎么挑替身」），但若有人拿它当依据要回读。

