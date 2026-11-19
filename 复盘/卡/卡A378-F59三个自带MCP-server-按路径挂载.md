# 卡 A378：F59 三个自带 MCP server（web-search / vision / image）—— 传输/挂载半判 PORT，三个能力面判不移植

> 台账号 `T-AG666`｜分区 A（magpie 移植 / 号池 pool）｜树 `.wt/A378`｜层 判据层 + 传输层数据形状｜基准 `6573205b`（立卡时主树 HEAD，2026-11-20 02:20 实读）｜depends A365、A362、E143

> depends 说明：本卡改的是 `tools/pool/mcp_http.py` —— 它的出生卡是 **A365**（`docs/workbacklog.toml:5129` `id = "A365"`，`title = "MCP 只能在同机 stdio 里用：给它开一条 HTTP 传输"`，`status = "done"`）；上限的来源卡是 **A362**（`docs/workbacklog.toml:4982` `id = "A362"`）；`MAX_LINE_BYTES` 的读数与窗口类元数据要 **E143** 同批（`docs/workbacklog.toml:6575` `id = "E143"`）。三张都 `status = "done"`，符合 `tools/pool/plan.py:292-294` 的「depends 必须存在」。

> **不许写 depends F12 / F13**：`docs/workbacklog.toml:4853` 的 `id = "F12"` 与 `:5185` 的 `id = "F13"` 是**另一套编号体系**（backlog 的 F 系列），与 `_ext/_magpie_features.md` 里 magpie 的 F12（图像生成）/ F13（视频）不是同一批东西。混写会让落地时的 depends 指错卡。

> 基准说明：起草时主树 HEAD = `dce8d904`（`git rev-parse --short HEAD` 实读）。本文每条 文件:行号 都在 `dce8d904` 上重核过（起草过程跨了两个 HEAD：`7a4cc513` → `dce8d904`，后者只动了 `docs/subsystems/pool/README.md`、`docs/subsystems/pool/modules.toml`、`docs/workbacklog.toml` 与 accounts/warmup 一族；`tools/pool/mcp_http.py` 406 行、`tools/pool_mcp.py` 3637 行、`tests/test_pool_mcp_http.py` 487 行、`tools/pool/gateway.py` 1300 行四个读数与全部 `mcp_http.py` 行号在 `dce8d904` 上**复读未变**；唯一的漂移是 `docs/subsystems/pool/modules.toml` 的 mcp_http 条目从 :240-243 移到 **:245-248**，本文已按新行号写）。落地前按当时 HEAD 重核。行数读数（`wc -l` 实读）：`tools/pool/mcp_http.py` = 406、`tools/pool_mcp.py` = 3637、`tests/test_pool_mcp_http.py` = 487、`tools/pool/gateway.py` = 1300。

> 依据：`gates/diag/_magpie_scope.md:67` 逐字「| F59 | 三个自带 MCP server：web-search/vision/image | PORT | no | tools/pool_mcp.py 是号池 MCP；无 /mcp/<name> 三个 server |」；三值口径见同文件 `:3`「判据：PORT / SKIP_BY_REDLINE（永不做协议翻译层）/ SKIP_NOT_APPLICABLE（不可移植资产）」。功能原文 `D:/repo/program/_ext/_magpie_features.md:504-510`。

---

## 前情：magpie 的 F59 是三件事叠在一起

1. **三个能力工具**：`_magpie_features.md:507` 逐字「入口：`/mcp/magpie/web-search`（`web_search`、`web_fetch`）、`/mcp/magpie/vision`（`analyze_image`）、`/mcp/magpie/image`（`generate_image`、`generate_video`、`generation_result`）；`magpie tool generate_image|analyze_image|web_search`。」
2. **三条独立路径 + 一张注册表**：`internal/gateway/search_mcp.go:30` `const SearchMCPPath = "/mcp/magpie/web-search"`；`:35-40` `var OwnMCPServers = []struct{ Name, Path string }{{"image", ImageMCPPath},{"vision", VisionMCPPath},{"web-search", SearchMCPPath},{"tools", ToolsMCPPath}}`（★ 第四个 `tools` 要插件宿主，**不属本卡**）；`internal/gateway/gateway.go:836-842` 把它们用 `mux.HandleFunc` 接上。
3. **每路径各自一个请求体上限**：`search_mcp.go:56` `serveMCP(w, r, "magpie's web search", 1<<20, s.searchMCPCall)`；`vision_mcp.go:34` `const visionMCPBody = 32 << 20`；`tools_mcp.go:35` `const toolsMCPBody = 4 << 20`；`hub_mcp.go:74` `const hubBody = 4 << 20`。判据原文 `_magpie_features.md:509`「上限 web-search 1 MiB / vision+image 32 MiB、超长整包 413 且在消息转发之前」。

三件事里，第 1 件是**能力**，第 2 + 3 件是**机制**。本卡把两层拆开判：机制那半判 PORT，能力那半逐条判不移植。

## 缺口：本仓今天有没有这个东西

### A 面（三个能力工具）—— **完全没有**（不是「有代码没接线」）

```bash
# 带 path 限定，四个根各跑一遍
grep -rnE 'web_search|web_fetch|analyze_image|generate_image|generate_video|generation_result' tools/ src/ scripts/ tests/
```
读数：`tools/` 0 命中、`src/` 0 命中、`scripts/` 0 命中、`tests/` 0 命中。

工具面现算（真跑 `python -c "import pool_mcp; ..."` 遍历 `pool_mcp.tool_list()`）：
- 工具数 **13**，六个 magpie 工具名**一个都不在**；
- `any("__" in t["name"])` = **False**；
- 13 个 `inputSchema` 里含 `"agent"` 字样的 **0** 个；
- `annotations.openWorldHint` 为 True 的 **0** 个（magpie 的 `web_search` 标了 `openWorldHint: true`，见 `search_mcp.go:129-146` 段的工具清单）。

⇒ 这一半不是「差一根线」，是**能力、后端、工具面三样都没有**。

### B 面（路径挂载 + 每路径上限）—— **有代码，但这一层根本没有「路径」这根轴**

真跑实测（`mcp_http.build_server(handle, host="127.0.0.1", port=0, token="t", origins=(), max_bytes=1024, protocols=("2025-03-26",))` 起在后台线程，逐枪真 socket）：

```text
POST /nope                                              -> 200  {"jsonrpc": "2.0", "id": 1, "result": {}}   ← 虚构路径照样执行
POST /a/b/c                                             -> 200  id 2
POST /v1/models                                         -> 200  id 3
POST /mcp/magpie/web-search                             -> 200  id 7（handle 真收到这笔）
GET  /nope                                              -> 405  Allow: POST
POST / 体=[{"jsonrpc":"2.0","id":8,"method":"ping"}]    -> 400
POST /mcp/magpie/web-search 声明 Content-Length 2048    -> 413
POST /mcp/magpie/image      声明 Content-Length 2048    -> 413（与上一条是同一个上限）
413 正文：请求体太大：2048 字节 > 上限 1024 字节（0 MiB）。
```

根因在代码里读得到，三句：

- `tools/pool/mcp_http.py:214` `def do_POST(self) -> None:  # noqa: N802 —— 基类约定`，起手 `:215` `max_bytes = getattr(self.server, "max_bytes", 0)` —— **单一上限、不看路径**；
- `:245-254` 的 413 文案只有一处数字来源：`f"请求体太大：{exc.size} 字节 > 上限 {max_bytes} 字节（{max_bytes >> 20} MiB）。"`；
- `:337-348` `def build_server(` … `*, max_bytes: int, protocols: Iterable[str], require_origin: bool = False, log: Callable[[str], None] | None = None) -> _Server:` —— 只有**一个** `max_bytes: int`，没有「每路径一个」的位置。

全文件 grep `PATHS|urlsplit|self\.path` = **0 命中** ⇒ 没有路径表、没有 `urllib.parse`、没有 404 分支（`:286-291` 的 `do_GET` 也只回固定 405）。`grep -n "<<" tools/pool/mcp_http.py` = **0 行** ⇒ 这一层今天连一个上限字面量都没有，32 MiB 是调用方 `tools/pool_mcp.py:284` `MAX_LINE_BYTES: int = 32 << 20` 传进来的（`:3606` 的 `mcp_http.serve_http(…, max_bytes=MAX_LINE_BYTES, …)`）。

⇒ **判「有代码但缺这根轴」，不是「完全没有」**：传输层在（Origin / Bearer / 版本头 / 202 / 405 / 413 都齐），**路径分发与按路径分档两样都不存在**。这也是本卡唯一要写的产品码。

### 另有一处差异，本卡**刻意不搬**

magpie 收 JSON-RPC batch：`search_mcp.go:80-124` 里 `batch := len(body) > 0 && body[0] == '['`，无回话 ⇒ 202，有回话 ⇒ 200 数组。本仓 `mcp_http.py:266-268` `if not isinstance(message, dict): self._fail(400, "JSON-RPC 消息必须是对象。")`，`tests/test_pool_mcp_http.py:391-399` 把空数组 `b"[]"` 钉成 **400**。本卡**保住这条 400**：batch 是「一条 HTTP 请求跑多条消息」，与本卡的「一条路径一个 server」是两件事，混在一起会把既有钉子撞红。

## 结论：混合判定（四条，**不是**整条 SKIP，也**不是**整条 PORT）

1. `web_search` / `web_fetch` ⇒ **SKIP_BY_REDLINE**。magpie 的实现是调外部搜索 API（同族证据见 `gates/diag/_magpie_scope.md:64-66`：F56 搜索 API 多 key 轮换 / F57 / F58 三条都判 PORT|no）。搬进来 = 把「查什么」发出去，撞 `docs/EXTENDING.md:73` 逐字「2. **数据不出本地** —— 不上云、不新增对用户数据的外部依赖；外部监测走独立脚本 + 接口。」与 `docs/CODING_GUIDELINES.md:101` 逐字「- **数据不出本地**（不上云）；复杂外部监测不硬塞进主工具（走接口）。」、`:103`「- **不新增对用户数据的外部依赖**（保持本地优先/隐私最小）。」
2. `analyze_image` ⇒ **SKIP_BY_REDLINE**。它要把图发出去给外部 VLM 才有回话（`vision_mcp.go:37` `const visionFileMax = 20 << 20` 就是为上传图设的），同样撞上面两条红线；另有一层：magpie 这条路径的守卫是「非本机要带 gateway key」（`search_mcp.go:63-64` 逐字「…is served to another machine only when magpie is shared on the local network and the request carries a gateway key (Authorization: Bearer <key>)」），而本仓 pool 层**明文不持凭据**：`tools/pool/callers.py:5-7` 逐字「1. **本模块不持有凭据**：不生成任何密钥、不做常量时间比较、不写 `0600` 权限。」⇒ 那个 403 分支在本仓没有对应物，真搬就是新造一层凭据。
3. `generate_image` / `generate_video` / `generation_result` ⇒ **SKIP_NOT_APPLICABLE**（归 magpie F12 / F13，本仓尚无对应卡）。判据：`image_mcp.go` 的整套形状是「提交任务 + 短期保留 + 淘汰」——`:109` `imageMCPWithin = 20 * time.Second`、`:116` `imageMCPKeep = time.Hour`、`:119` `imageMCPFilesMost = 256 << 20`、`:121` `imageMCPInline = 5 << 20`、`:123` `imageMCPJobMost = 15 * time.Minute`、`:633` 淘汰、`:666-668` `f.key != access.Caller(...).KeyID` ⇒ 404「no such image: images are kept for an hour, and only for the key that had them made」。这套是**宿主资产的形状**（任务表 + 配额 + 密钥归属），本仓既无生成后端也无该宿主。
4. **传输/挂载那半 ⇒ PORT**：给 `tools/pool/mcp_http.py` 加一条路径表 + 未挂载路径 404 + 每路径各自 `max_bytes`，范本直接照 `tools/pool/gateway.py:99-104` 与 `:1084-1101`。**只做机制，不接任何真实能力**：不新增工具、不写搜索/看图/画图后端、不搬 batch、不加 SSE、不加会话。

> ★ 这就是为什么这一条**不该**整条判 SKIP：机制那半是本仓真缺的轴（未挂载路径今天返回 200 并执行），而能力那半是红线。把两半写进同一张卡、判据分开钉，比「整条 SKIP + 将来另开一张」少一次漂移。

## 判据（六条，逐条给「怎么证明」）

### 判据 1 · 未挂载的路径 404，且 handle 一次都不执行

- **怎么证明**：新建 tests/test_pool_mcp_http_paths.py（体例照 `tests/test_pool_mcp_http.py`：真 socket + `_Stub` 记调用 + `_free_port`，**不桩 http.server**，见该文件 `:1-4` 的文件头与 `:41-50` 的 `_Stub`），写 `test_unmounted_path_is_404_and_never_executes`：`POST /mcp/magpie/not-mine` ⇒ `assert response.status == 404` 且 `assert stub.calls == []`。
- **今天的反证**：同一枪现在返回 **200** 并把这笔交给了 handle（见「缺口 B 面」实测第 1 行）⇒ 新钉子必须有咬。
- 404 的判法要**先路径后方法**（与 `tools/pool/gateway.py:1086` 在 `:1092` 之前同序）：未挂载路径不论 GET/POST 都是 404。

### 判据 2 · 每路径各自一个上限，不是共用一个

- **怎么证明**：同文件 `test_each_mounted_path_has_its_own_limit`：`{"/small": 1024, "/big": 4096}` 两条挂载，声明 `Content-Length: 2048` 打 `/small` ⇒ `assert status == 413`；同一长度打 `/big` ⇒ `assert status == 200`；再断言 413 正文里的数字是**该路径自己的**上限：`assert "1024" in text`。
- **今天的反证**：今天两条不同路径（`/mcp/magpie/web-search` 与 `/mcp/magpie/image`）对同一个 2048 都回 413，用的是同一个 `max_bytes`（实测第 7、8 行）。
- 上限的**来源仍只有一处**：不许在 `mcp_http.py` 里写 `32 << 20` 这类字面量（否则判据 5 红）。

### 判据 3 · `/` 的既有行为一字不改（`tests/test_pool_mcp_http.py` 25 条全绿）

- **怎么证明**：`python -X utf8 -m pytest tests/test_pool_mcp_http.py -q -o addopts= --no-cov` ⇒ 25 条全绿（起草时 `grep -c "^def test_"` = 25）。★ 这些用例全都打 `"/"`（`:79` `conn.request("POST", "/", body=payload, headers=merged)`、`:352` `conn.putrequest("POST", "/")`）⇒ `/` 必须继续是挂载的缺省路径，一个断言都不许改。
- 另加一条新钉子 `test_mounted_path_get_is_still_405_with_allow`：对**已挂载**路径 `GET` ⇒ `405` 且 `assert _header(dict(response.getheaders()), "Allow") == "POST"`（沿用 `tests/test_pool_mcp_http.py:285-296` 的读法）。

### 判据 4 · 不搬 batch、不搬 SSE、不加会话

- **怎么证明**：沿用 `tests/test_pool_mcp_http.py:391-399` 的三条断言（`payload` 三项含 `b"[]"` ⇒ `400`、`stub.calls == []`、再 ping `200`）；在新文件加 `test_single_element_batch_is_still_400_on_mounted_path`：体 `[{"jsonrpc":"2.0","id":8,"method":"ping"}]` 打**已挂载**路径 ⇒ `400` 且 `stub.calls == []`（实测今天已是 400，这条钉的是「加路径分发时别顺手把 list 收下」）；再加 `assert _header(headers, "Mcp-Session-Id") is None`（沿用 `:332` 与 `:463` 的读法）。
- 为什么这条值钱：`search_mcp.go:80-124` 的 batch 分支就在 `serveMCP` 里，照着它抄最容易连实证一起搬过来。

### 判据 5 · 32 MiB 仍只有一个来源；传输层仍零移位字面量

- **怎么证明**：既有 `tests/test_pool_mcp_http.py:402-405` 两条 `assert "32 << 20" not in source` / `assert "32<<20" not in source` 必须继续绿；再加 `tests/test_pool_mcp_line_cap.py:225` 那条 `source.count("32 << 20") == 1`（`"上限字面量只许出现在常量定义那一行"`）继续绿；在新文件加 `test_http_layer_still_has_no_shift_literal`：读 `ROOT/tools/pool/mcp_http.py` 源码，`assert "<<" not in source` —— 今天的读数是 **0 行**，这条等于把「每路径上限由调用方给」钉成结构约束。
- 这条是判据 2 的**反向护栏**：判据 2 要求分档，这一条禁止分档时把数字写进传输层。

### 判据 6 · 三个能力面钉在「不在」（不移植那一半的可核证据）

- **怎么证明**：同文件 `test_three_capability_surfaces_are_absent`，三段断言：
  1. 工具名单对账：`assert [t["name"] for t in pool_mcp.tool_list()] == TOOL_NAMES`，`TOOL_NAMES` 直接 `from test_pool_mcp import TOOL_NAMES`（该表在 `tests/test_pool_mcp.py:45-59`，十三项固定），并 `assert not any(name in TOOL_NAMES for name in ("web_search", "web_fetch", "analyze_image", "generate_image", "generate_video", "generation_result"))`；
  2. 源码缺席：遍历 `tools/` 与 `src/` 的 `*.py`，`assert not [p for p in files if re.search(r"web_search|analyze_image|generate_image", p.read_text(encoding="utf-8"))]`（今天 0 命中）；
  3. 开放世界标记：`assert [t["name"] for t in pool_mcp.tool_list() if t.get("annotations", {}).get("openWorldHint")] == []`。
- 为什么不在 `tests/test_pool_mcp.py` 里加：那张文件已经被 `TOOL_NAMES` 与「未知工具 -32602」占住（`:313` `assert "没有这个工具" in reply["error"]["message"]`），本卡的缺席判据放新文件，卡域才不撞（`tools/pool/plan.py:60-64` 精确字符串相交）。

## 反向变异（四条，外加一条只改注释的安静对照）

脚本一次跑完，落 `gates/diag/_rev_F59.py`（gitignored，**不当长期钉子**），每条真改真跑真复原（`git checkout --` 复原并 sha256 自证），末行打印「结论：4/4 咬住 + 1 条安静对照未响，收尾绿」。

| # | 改哪一行（锚点原文） | 哪条判据红 | 怎么红 |
|---|---|---|---|
| M1 | `mcp_http.py` 新加的 404 分支：删掉 `if spec is None:` 那一段（或改成落到缺省挂载） | 判据 1 | 未挂载路径重新返回 200 且 `stub.calls` 非空 ⇒ `assert response.status == 404` 先红 |
| M2 | 新加的取上限那句：把 `max_bytes = mounts[path]` 改回 `max_bytes = getattr(self.server, "max_bytes", 0)`（原文见 `:215`） | 判据 2 | `/big` 对 2048 也回 413 ⇒ `assert status == 200` 红 |
| M3 | `mcp_http.py:266-268` 前后加 batch 分支（照 `search_mcp.go:80-124` 抄 `if text.startswith("["):`） | 判据 4 | `b"[]"` 与单元素数组不再 400 ⇒ `assert status == 400, payload` 红（既有 `:391-399` 直接咬） |
| M4 | `tools/pool_mcp.py:615-620` `tool_list()` 的 `specs` 里加一条 `{"name": "web_search", …}` | 判据 6 | 工具数 13→14 ⇒ `assert [t["name"] …] == TOOL_NAMES` 红，且缺席断言红 |
| N1 | **只改注释**：把 `mcp_http.py:26-27` 那句「**无会话**」换一种说法（同一个意思） | 无 | 六条判据全绿 —— 安静对照，证明钉子咬的是行为不是文字 |

> 变异脚本**不许**留在树上当钉子：`docs/subsystems/pool/README.md:79-80` 逐字「> 卡树里的 `gates/diag/` 是 gitignore 的，写进去等于没写（`tools/pool/registry.py:72`、`tools/pool/task.py:119`）。」

## 交付（逐文件）

- `tools/pool/mcp_http.py` —— 加三样，别的一个字节不动：①模块级 `DEFAULT_PATH = "/"` 与「路径 → 上限」的冻结表；②`build_server` / `serve_http` 各加一个 keyword-only `mounts: Mapping[str, int] | None = None`（`None` ⇒ `{"/": max_bytes}`，保住既有 25 条用例）；③`do_POST` / `do_GET` / `do_DELETE` / `do_PUT` / `do_PATCH` 起手先 `path = urlsplit(self.path).path.rstrip("/") or "/"`，未挂载 ⇒ 404（**在方法判定之前**，同 `tools/pool/gateway.py:1086` 的次序），`max_bytes` 改成该路径自己的数。**不动** `:165-190` 的 `_send`/`_fail`、`:119-139` 的 `read_body`、`:216-268` 的六道闸文案（Origin / Bearer / Accept / 版本 / 411 / 413 / UTF-8 / JSON / 非对象）、`:269-284` 的 202/200。
- `tools/pool_mcp.py` —— 只改 `:3606-3615` 那一次调用：传 `mounts={"/": MAX_LINE_BYTES}`。`MAX_LINE_BYTES`（`:284`）与 `tool_list()`（`:615-620`）**一个字不改**。
- tests/test_pool_mcp_http_paths.py（新建）—— 判据 1、2、3（新增那条）、4（单元素那半）、5（`<<` 那半）、6；文件头照 `tests/test_pool_mcp_http.py:1-4` 的「★ 全部走**真 socket**…不桩 http.server」体例写一段「## 钉什么」表格。
- `复盘/卡/卡A378-F59三个自带MCP-server-按路径挂载.md`（计划建）—— 由本草稿转正（文件名立卡时定）。
- docs/changelog.d/T-AG666.md（计划建）—— 落地时按真台账号改名。

> **卡域里不列** `tools/pool/gateway.py`、`docs/subsystems/pool/modules.toml`、`docs/subsystems/pool/README.md`：`gateway.py` 只是**读**的范本（一行不改）；`modules.toml:245-248` 的 duty 逐字「MCP 的 Streamable HTTP 传输：Origin / Bearer / 版本头 / 上限 / 202-405 都在这一层；判据只在传进来的 handle 上跑，不重写方法分发」在加路径表之后**仍然成立**（上限仍在这一层，只是从「一个」变「按路径」），所以不改它、也就不会触发 README 重生成。本卡**不新增** `tools/pool/*.py`，因此 `modules.toml` 也不需要有新条目（新增才会有：`scripts/gen_pool_readme.py:27-29`「仓里有、清单里没有的模块 ⇒ 退 1 并**点名**」）。
> docs/traceability.d/T-AG666.toml 不进卡域：A365 的 `files` 六条里没有它（`docs/workbacklog.toml:5134-5141`），形状照 `docs/traceability.d/T-AG584.toml` 落地时补。汇总 `docs/traceability.toml` 在 `tools/pool/plan.py:46-53` 的 PROTECTED_FILES 里，**不许碰**。

## 验收（可直接跑）

```bash
cd .wt/A378
python -X utf8 -m pytest tests/test_pool_mcp_http.py -q -o addopts= --no-cov
python -X utf8 -m pytest tests/test_pool_mcp_http_paths.py -q -o addopts= --no-cov
python -X utf8 -m pytest tests/test_pool_mcp_line_cap.py tests/test_pool_mcp.py -q -o addopts= --no-cov
python -X utf8 -m ruff check tools/pool/mcp_http.py tools/pool_mcp.py tests/test_pool_mcp_http_paths.py
python -X utf8 scripts/gen_pool_readme.py --check
grep -c '<<' tools/pool/mcp_http.py                    # 期望 0
grep -c 'MAX_LINE_BYTES: int = ' tools/pool_mcp.py     # 期望 1
python -X utf8 gates/diag/_rev_F59.py
```

已知噪音（别当红）：

- `-o addopts= --no-cov` **必须带**：`pyproject.toml:51` 的默认 addopts 是 `-q -m "not acceptance and not chain" --cov=timeflow --cov-fail-under=70`，只跑几个文件也会因覆盖率不达标而红。
- 判据 1/2/5/6 是**新建用例**，第一次跑是新增；主树今天 0 条。
- 反向变异脚本跑完必须 `git checkout -- tools/pool/mcp_http.py tools/pool_mcp.py` 复原，**不许**把变异带进落地提交。
- `scripts/gen_pool_readme.py` 未接门（`grep -rn gen_pool_readme gates/defs/ scripts/run_gates.py` 全 0 命中），但落地链会跑 `scripts/check_derived_docs.py`；本卡不改 `modules.toml` 与 README，`--check` 应保持绿（起草时为绿：`[OK  ] docs/subsystems/pool/README.md 与现算一致`）。

## 不许做

1. **不许**把 `web_search` / `web_fetch` / `analyze_image` 实现进本仓，也**不许**为此加任何出网客户端 —— 依据 `docs/EXTENDING.md:73`、`docs/CODING_GUIDELINES.md:101`/`:103`。
2. **不许**动 `tests/test_pool_mcp_http.py` 既有用例的断言正文（`:266-274`、`:285-296`、`:391-399`、`:402-405` 逐条读过后确认：加路径分发不需要改它们）；新判据只许进新文件。
3. **不许**改 `tools/pool_mcp.py:284` `MAX_LINE_BYTES: int = 32 << 20`、`:615-620` `tool_list()`、`:3296-3339` `_initialize` —— `tests/test_pool_mcp_line_cap.py:225` 与 `tests/test_pool_mcp.py:186-203`（`test_tools_list_shape_is_pinned` 整个函数体）咬在这三处。
4. **不许**搬 batch / SSE / `Mcp-Session-Id`：`mcp_http.py:34-39` 的三条边界是 A365 立过的判据，`:26-27` 逐字「**无会话**：**不发** `Mcp-Session-Id`…**带了**这个头的请求照样处理（不认识 ≠ 拒收）」。
5. **不许**碰 `tools/pool/plan.py:46-53` 列出的六份 PROTECTED_FILES（docs/traceability.toml、docs/changelog.md、复盘/交接-重构进度.md、复盘/新窗口交接卡.md、gates/last.json、gates/reuse.json）；卡域 `files` 不许写通配（`:60-64` 与 `:285-291` 的拒单文案「域必须是**精确路径**」）。
6. **不许**改仓外 `D:/repo/infra/**`（号池账本、模型开关、能力表都在那里，本仓只读）。
7. **不许**顺手修 `tests/test_pool_mcp.py:187` 那句陈旧的 docstring（逐字「`tools/list`：十二个只读工具、每个 inputSchema 是 object、annotations 说只读。」，实际 13 —— 见 `tools/pool_mcp.py:616`「十三个只读工具（十个号池 + 三个任务）；有 `POOL_MCP_WRITE=1` 时再补五个写工具。」）：那是另一张卡；碰它会让 `test_tools_list_shape_is_pinned` 的 diff 变大、卡域也脏。
8. **不许**把未建的文件写成反引号路径（死指针会回涨到基线之上）：本草稿里凡未创建的文件都写「（计划建）」且不加反引号。

## 与已完成卡的关系

- **A365**（`tools/pool/mcp_http.py` 的出生卡）：本卡改的就是它建的那一层。A365 的判据（Origin / 只绑回环 / 必须鉴权 / 202-405 / 413 不读流 / 无会话）**一条都不作废**，本卡只是在同一层加「路径」与「每路径上限」两根轴。
- **A362**（MCP 那一行有多长才算太长）：`MAX_LINE_BYTES` 的唯一来源。本卡不许产生第二份字面量（判据 5）。
- **A373**（F94 判 SKIP_BY_REDLINE）：同一批 magpie 判定里的 SKIP 体例来源；它计划给 `docs/subsystems/pool/README.md` 表 B 加一行 —— 本卡不碰 README，两卡无域交叠。
- **E143**：窗口/上限类元数据的常客依赖，同批落地。

## 未坐实项（草稿如实标注，别当成结论）

- **未取证**：`tools/pool/mcp_http.py` 加 `urlsplit` 后 `tests/test_pool_mcp_http.py` 的 25 条是否**全部**仍绿 —— 我只逐条读了断言（全打 `"/"`）并推演，没有真改产品码验证（本轮是起草，改码不是本轮的活）。
- **未取证**：`mounts` 这个形参名是否该与 `tools/pool/gateway.py` 的 `PATHS` 统一 —— 那边是模块级常量表，本卡是运行期传入的映射，我倾向保持两种形状（一次性 vs 可配置），但没有第二处消费者来证。
- **未坐实**：magpie `web_search` 的后端到底调哪家外部 API —— 我只据 `gates/diag/_magpie_scope.md:64`（F56「搜索 API 多 key 轮换」判 PORT|no）与 `_magpie_features.md` 的入口描述推断它出网，**没有**在 magpie 源码里逐行读搜索实现。SKIP_BY_REDLINE 的结论不依赖具体厂商，但「一定出网」这句我只到「同族已知出网」这一级。
- **未坐实**：`vision_mcp.go` 的 `analyze_image` 是否也走外部 VLM —— 同一类推断（`:37` `visionFileMax = 20 << 20` 的 20 MiB 上传上限是强旁证，但不是逐行读到的调用点）。
- **未取证**：本仓 `tools/` 下已有的出网客户端（`pool_accounts.py` / `checkin.py` / `gateway.py` 的固定端点 `urllib.request`）与本卡「不许出网」是否冲突 —— 那些是**固定端点**（都带 `# noqa: S310` 与「端点来自常量，不是用户输入」的注释），不是「按用户查询去搜网页」，我按不同类处理；这条判断没有门禁背书。
