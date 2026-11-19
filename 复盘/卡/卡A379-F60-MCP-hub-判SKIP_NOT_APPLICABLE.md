# 卡 A379：F60 MCP hub（一条 magpie 条目替代该 agent 的所有 server）—— 判 SKIP_NOT_APPLICABLE

> 台账号 `T-AG667`｜分区 A（magpie 移植 / 号池 pool）｜树 `.wt/A379`｜层 判据层 + 不移植证据｜基准 `6573205b`（立卡时主树 HEAD，2026-11-20 02:20 实读）｜depends A378、A365

> depends 说明：**F60 的前提是 F59 的传输半**（hub 是把「多条 server 路径」收进一个入口，先得有「路径」这根轴）。F59 已立为 A378（树 .wt/A378），本卡 depends 它。**A365** 是 `tools/pool/mcp_http.py` 的出生卡（`docs/workbacklog.toml:5129` `id = "A365"`，`status = "done"`），本卡要钉的「一个进程一个 server」现状就在它那层。

> **不许写 depends F12 / F13 / F61**：`docs/workbacklog.toml:4853` 的 `id = "F12"` 与 `:5185` 的 `id = "F13"` 是 backlog 自己的 F 系列（与 magpie 的 F12/F13 不是一套）；`F61` 只活在 `gates/diag/_magpie_scope.md` 与 `_ext/_magpie_features.md`，backlog 里 `grep '^id = "F6[01]"' docs/workbacklog.toml` = **0 命中**，写进 depends 会被 `tools/pool/plan.py:292-294` 以「depends 不存在」拒单。

> 基准说明：起草时主树 HEAD = `dce8d904`（`git rev-parse --short HEAD` 实读）。起草跨了两个 HEAD（`7a4cc513` → `dce8d904`，后者只动 pool 文档与 accounts/warmup 一族）；本文引的源码行号（`tools/pool/mcp_http.py:337-348`、`:59`、`tools/pool_mcp.py:283`、`:284`、`src/timeflow/mcp/server.py:68`）与三组 grep 读数在 `dce8d904` 上**复读未变**；`docs/subsystems/pool/modules.toml` 的 mcp_http 条目已从 :240-243 移到 **:245-248**。落地前按当时 HEAD 重核。

> 依据：`gates/diag/_magpie_scope.md:68` 逐字「| F60 | MCP hub：一条 magpie 条目替代该 agent 的所有 server | PORT | no | 无 hub 概念（grep hub 零命中） |」；三值口径 `:3`「PORT / SKIP_BY_REDLINE（永不做协议翻译层）/ SKIP_NOT_APPLICABLE（不可移植资产）」。功能原文 `D:/repo/program/_ext/_magpie_features.md:512-518`。**本草稿把判定从 PORT 改判 SKIP_NOT_APPLICABLE**，理由见「结论」三条 —— 那条 PORT 是普查时的粗判：它只看了「本仓没有」，没看「本仓有没有这个对象」。

---

## 前情：magpie 的 hub 到底是什么

1. **要解决的问题**：`_magpie_features.md:514` 逐字「解决：同一个 MCP server 被 5 个 agent 各起一份，进程和登录都重复；但如果那个 agent 只支持逐 server 配置，就不能替。」
2. **入口与实现**：`_magpie_features.md:515-516`「入口 GUI Library 的 MCPHub 开关；`/mcp/magpie/hub`、`/mcp/magpie/hub/{agent}`；`Settings.MCPHub`」「实现 mcp_hub.go + hub_mcp.go」。
3. **协议面**：`internal/gateway/hub_mcp.go:24-25` `const HubMCPPath = "/mcp/magpie/hub/"`、`:27-30` `HubMCPAll = "/mcp/magpie/hub"`、`:92` `const hubSep = "__"`（工具名拼成 `<server>__<tool>`，`:96-105` 的 `hubNamed`）、`:69-72` `hubListWait = 40 * time.Second` / `hubCallWait = 50 * time.Second`、`:74` `const hubBody = 4 << 20`。
4. **背后要有一个会起进程、会回收的宿主**：`internal/gateway/hub_mcp.go:43-60` `type Hub interface { On() bool; Tools(ctx, agent string) []HubTool; Call(ctx, agent, server, tool string, args json.RawMessage) (json.RawMessage, error); Stop(); Prune() }`、`:63` `var MCPHub Hub`；`internal/library/mcp_hub.go:52-53` 逐字「// hubIdle is how long a server the hub started is kept with no call.」`var hubIdle = 10 * time.Minute`、`:416` `t = time.AfterFunc(hubIdle, func() {`。
5. **还有一层写配置的**：hub 的「一条 `magpie` 条目」是写进**每个 agent 的配置文件**的东西 —— `internal/library/mcp.go:33` 逐字「// Transport is stdio for a command, http (streamable) or sse for a URL.」、`:530` `add("type", "streamable_http")`、`:557` `t := "streamable-http"`。

所以 F60 是**四层叠起来的**：一个 hub 服务端（协议面）+ 一个会拉起子进程并 10 分钟回收的宿主 + 一层 per-agent 可见性（`Tools(ctx, agent)`）+ 一层「把 `magpie` 这一条写进每个 agent 的配置」。

## 缺口：本仓今天有没有这个东西 —— **完全没有**（连「对象」都不存在）

```text
grep -rnE 'MCPHub|mcp_hub|mcpServers|hubSep|hubIdle' tools/ src/ scripts/ tests/   -> 0 命中（四根各跑一遍）
grep -rnE 'threading\.Timer|Timer\(|AfterFunc'          tools/ src/                -> 0 命中
grep -rnE 'mcpServers|mcp_servers|cursor://|vscode:mcp'   src/ tools/                -> 0 命中
grep -nE  'subprocess|Popen'  tools/pool/mcp_http.py src/timeflow/mcp/server.py     -> 0 命中
```

本仓的 MCP 面只有**两个各自独立的 server**，一个进程一个，互不相干：

- `tools/pool_mcp.py:232` `SERVER_NAME = "pool"`；`:3606` `return mcp_http.serve_http(` —— 号池 MCP；stdio 与 HTTP 两种入口，**同一个进程**。
- `src/timeflow/mcp/server.py:68` `SERVER_NAME = "timeflow"`；`:41` 逐字「- 传输只做 **stdio**（没做 HTTP/SSE 那种）：本地工具，够用且最省事。」；`:185` `def tool_list(allow_write: bool) -> list[dict[str, Any]]:`（工具清单由 registry 现算）。

三条「没有 hub 的对象」的读数（都真跑过）：

1. **没有「拉起一个 MCP server 并复用它」这件事**。注意别把话说满：`tools/pool_mcp.py` 里 `subprocess|Popen` **有 20 处命中**（`grep -cE 'subprocess|Popen' tools/pool_mcp.py` = 20），但**一处都不是 MCP server**：`:818` / `:840` 跑 `gate_lock.py status`（`:40` 逐字「（唯一 subprocess，见下）」，`:44` 交代它是 `gates/diag/` 下的独立脚本）、`:2401` / `:2449` / `:2468` 起工人（`:2397` 逐字「**起工人**（带 `--detach`…）—— 本模块第二处 subprocess。」）、`:3070` 跑 task claim（`:2839-2841` 交代超时只带走直连子进程，所以换 `Popen` + `communicate(timeout=…)`）。**没有一处把 MCP server 当子进程拉起来复用**。而真正承载 MCP 面的两个文件 `tools/pool/mcp_http.py` 与 `src/timeflow/mcp/server.py` 里 `subprocess|Popen` **0 命中**（实跑）。
2. **没有 per-agent 维度**：`pool_mcp.tool_list()` 现算 —— 13 个工具的 `inputSchema` 里含 `"agent"` 字样的 **0** 个；`annotations.openWorldHint` 为 True 的 **0** 个；`any("__" in name)` = **False**（`<server>__<tool>` 那套命名一个都没有）。
3. **没有空闲回收定时器、没有配置写出层**：`threading.Timer|Timer(|AfterFunc` 在 `tools/` 与 `src/` 都 **0 命中**（hub 的 10 分钟空闲回收没有可落脚的机制）；`mcpServers|mcp_servers|cursor://|vscode:mcp` 在 `src/` 与 `tools/` **0 命中** ⇒ 本仓不写任何 agent 的 MCP 配置、不产 deeplink。

## 结论：判 SKIP_NOT_APPLICABLE（不是 SKIP_BY_REDLINE，也不是 PORT）

**不是 SKIP_BY_REDLINE**：hub 本身不碰红线（它在本地起进程、走回环，数据不出本地）。

**不是 PORT**：PORT 的意思是「本仓该有、只是还没写」。hub 不是「还没写」，是**本仓没有它要替代的那个东西**。三条论证：

1. **hub 的替代对象在本仓不存在**。hub 成立的前提逐字写在 `_magpie_features.md:514`：「同一个 MCP server 被 5 个 agent 各起一份」。本仓的 MCP 消费者是**一个客户端按需起一个子进程**（`tests/test_mcp_client_independent.py:1` 逐字「T-G78：**独立实现的最小 MCP 客户端**（`tools/mcp_client.py`）—— 用它去读我们的服务端。」），并且**本仓不写任何 agent 的配置文件**（上节读数 3）。「一条条目替代所有 server」是**配置写入层**的动作，而那层已经判过 SKIP：`gates/diag/_magpie_scope.md:12`（F4 一个模型目录 → 原子改写各 agent 配置）判 SKIP_NOT_APPLICABLE「红线外：绑定具体 agent 配置文件格式（文档「不可移植」节列 70+ agent 格式）」、`:69`（F61 Library：instructions/MCP/skills 一次写成每个 agent 的格式）判 SKIP_NOT_APPLICABLE「红线外：绑定具体 agent 配置格式」、`:83`（F75 Agent 接线五步）判 SKIP_NOT_APPLICABLE「红线外：绑定具体 agent 配置写入」。F60 的「一条 `magpie` 条目」正是 F61 那条链的产物 —— 上游都判了不可移植，下游没有落点。
2. **hub 的机制核心（按需起 server 子进程 + 空闲回收）在本仓空白且无必要**。`internal/library/mcp_hub.go:52-53` 的 `hubIdle = 10 * time.Minute` 与 `:416` 的 `time.AfterFunc` 是 hub 的命门；本仓 `tools/` 与 `src/` 里定时器 **0 命中**，承载 MCP 面的两个文件里 `subprocess|Popen` 也 **0 命中**（号池 MCP 的那 20 处 subprocess 全是 CLI 脚本：门禁锁 / 起工人 / task claim，见缺口读数 1）。要搬就得先造一个「MCP server 进程池 + 回收器」，而它服务的对象（5 个 agent 各起一份的重复）不存在 —— 这是**为不存在的负载造机器**。
3. **hub 的 per-agent 可见性没有语义**。`hub_mcp.go:43-60` 的 `Tools(ctx, agent string)` 与 `_magpie_features.md:517`「Library 关掉的不列」都以「每个 agent 有自己的开关」为前提。本仓 13 个工具里带 agent 维度的 **0** 个（读数 2），也没有「Library 开关」这层配置。

> **所以本卡的产物不是代码，是三样**：①这份 SKIP 论证（可复核的 文件:行号）；②一组**反向钉子**（判据 1~2：谁哪天把 hub 概念引进本仓，它们先红）；③一组**缺席钉子**（判据 3~5：把「MCP 面起 server 子进程 / 空闲回收定时器 / 写 agent 配置」这三件 hub 的前提钉成「不在」）。

> ★ 与 F59 的分工：F59 是「本仓该有、只是缺一根轴」⇒ 那半判 PORT，要写产品码；F60 是「本仓没有这个对象」⇒ SKIP，只写钉子。两张卡都**不接** magpie 的三个能力后端（搜索 / 看图 / 画图），那三样是红线。

## 判据（五条，逐条给「怎么证明」）

全部落在**新建**的 tests/test_pool_mcp_no_hub.py（今天不存在：`ls tests/test_pool_mcp_no_hub.py` 报 No such file or directory；`git ls-files tests | grep -i mcp` 八份里也没有它 —— test_mcp_client_independent.py、test_mcp_line.py、test_pool_mcp.py、test_pool_mcp_board.py、test_pool_mcp_http.py、test_pool_mcp_line_cap.py、test_pool_mcp_task.py、test_pool_mcp_write.py）。体例照 `tests/test_pool_rest.py:303-320` 的**反向钉子**：一张 `FORBIDDEN_* = (...)` 词表 + `inspect.getsource(...)` 逐个扫，docstring 写明「★ 反向钉子：…，这条必须变红。」（那一处逐字：`#: status() 里**不许**出现的字样 —— 它是「读记录 + 读钟表」的函数，零网络零等待。` 与 `assert hits == [], f"status() 里出现了网络/等待：{hits}"`）

### 判据 1 · hub 这个概念在本仓源码里零命中（反向钉子）

- **怎么证明**：`test_no_hub_concept_in_sources` —— 遍历 `tools/`、`src/`、`scripts/` 的 `*.py`（**排除** `tests/`），对每个文件 `re.search(r"\b(MCPHub|mcp_hub|hubSep|hubIdle)\b", text)`，断言命中列表为空。词表要**带词边界**：光秃秃的 `hub` 会撞上 `github` / `.github/` 字样（今天 `grep -rn --binary-files=without-match hub tools/` 的 10 条命中**全部**含 `github` 字样 —— `… | grep -c github` = 10；另有一条是 `tools/__pycache__/wb_takeover.cpython-314.pyc` 的二进制命中，不算源码）—— 那不是 hub。
- **今天的读数**：`MCPHub|mcp_hub|hubSep|hubIdle` 在 `tools/ src/ scripts/ tests/` 四根 **0 命中**（实跑）。
- 这条咬的是「引进 hub 概念」这一个动作：谁加了 `MCPHub` 类、加了 `hubIdle` 常量，先红。

### 判据 2 · 传输层至今没有 per-agent 维度（hub 的入口形状不在）

- **怎么证明**：`test_transport_has_no_agent_dimension` —— `sig = inspect.signature(mcp_http.build_server)`，断言 `assert "agent" not in {name.lower() for name in sig.parameters}`；`serve_http` 同理；再加一条 `assert not hasattr(mcp_http, "HubMCPPath")`。
- **为什么要这条**：magpie 的 hub 入口是 `/mcp/magpie/hub/{agent}`（`hub_mcp.go:24-25` + `:78-83` 的 `agent := r.PathValue("agent")`）。本仓 F59 落地后会有**静态**路径表，但没有 `{agent}` 这一段；这条钉子把「静态表 ≠ per-agent 路由」钉死，防止 F59 的路径表被当成 hub 的地基。
- **今天的读数**：`mcp_http.build_server` 的形参是 `handle / host / port / token / origins / max_bytes / protocols / require_origin / log`（`tools/pool/mcp_http.py:337-348`），一个 `agent` 都没有。

### 判据 3 · 承载 MCP 面的两层不起子进程（hub 的「首次调用启动 server」无对象）

- **怎么证明**：`test_mcp_face_never_spawns_a_process` —— 取两处源码 `srcs = [inspect.getsource(mcp_http), (ROOT/"src"/"timeflow"/"mcp"/"server.py").read_text(encoding="utf-8")]`，`FORBIDDEN_SPAWN = ("subprocess", "Popen", "os.system", "os.exec", "multiprocessing")`，对每处断言 `assert [w for w in FORBIDDEN_SPAWN if w in src] == [], f"MCP 面开始拉进程了：{hits}"`。
- **为什么不扫 `tools/pool_mcp.py`**：它今天**有** 20 处 `subprocess|Popen`（门禁锁 / 起工人 / task claim，见缺口读数 1），拿它当对象这条判据今天就是红的 —— 那是**把断言写错了**，不是本仓有问题。判据要钉的是「MCP server 不被当子进程拉起」，而 MCP server 的承载面就是这两个文件。
- **今天的读数**：`grep -nE 'subprocess|Popen' tools/pool/mcp_http.py src/timeflow/mcp/server.py` = **0 命中**（实跑）。
- ★ 这是**反向钉子**，不是「未来会做」的预告：它的意义是「MCP 面永远是 in-process 的」，一旦有人为了 hub 在传输层去 spawn，判据 1 与 3 一起红。

### 判据 4 · 本仓没有空闲回收定时器（hub 的 10 分钟机制无落脚点）

- **怎么证明**：`test_no_idle_reclaim_timer` —— 扫 `tools/` 与 `src/` 的 `*.py`，`FORBIDDEN_TIMER = ("threading.Timer", "Timer(", "AfterFunc")`，断言命中为空。
- **今天的读数**：`threading\.Timer|Timer\(|AfterFunc` 在 `tools/` **0**、`src/` **0**（实跑）。
- 注释里**可以**出现「定时器」中文字样（词表只收代码形状）—— 这条与下面 N1 安静对照配套。

### 判据 5 · 本仓不写任何 agent 的 MCP 配置、不产 deeplink（hub 的落点层不在）

- **怎么证明**：`test_no_agent_config_writer` —— 扫 `src/` 与 `tools/` 的 `*.py`，`FORBIDDEN_CONFIG = ("mcpServers", "mcp_servers", "cursor://", "vscode:mcp")`，断言命中为空；另加 `assert "mcpServers" not in (ROOT/"docs"/"subsystems"/"pool"/"modules.toml").read_text(encoding="utf-8")`（模块清单里也不许冒出一个「写配置」的模块）。
- **今天的读数**：`mcpServers|mcp_servers|cursor://|vscode:mcp` 在 `src/` **0**、`tools/` **0**、`tests/` **0**（实跑）。
- 这条与 `gates/diag/_magpie_scope.md:12`、`:69`、`:83` 三行 SKIP 判定是同一件事的钉子化：那三行是**决定**，这条是**可执行的复核**。

## 反向变异（四条，外加一条只改注释的安静对照）

脚本一次跑完，落 `gates/diag/_rev_F60.py`（gitignored，**不当长期钉子**），每条真改真跑真复原（`git checkout --` 复原 + sha256 自证），末行打印「结论：4/4 咬住 + 1 条安静对照未响，收尾绿」。

| # | 改哪一行 / 加哪一行（锚点原文） | 哪条判据红 | 怎么红 |
|---|---|---|---|
| M1 | 在 `tools/pool_mcp.py` 里加 `MCPHUB = "hub"`（或 `class MCPHub: ...`） | 判据 1 | `MCPHub|mcp_hub` 词表命中 ⇒ 断言列表非空 |
| M2 | `tools/pool/mcp_http.py:337-348` 的 `build_server` 形参表里加一个 `agent: str = ""` | 判据 2 | `sig.parameters` 含 `agent` ⇒ `assert "agent" not in ...` 红 |
| M3 | `tools/pool/mcp_http.py` 顶部加 `import subprocess`（**别拿 pool_mcp.py 做这条**：它本来就有 20 处，变异不成立） | 判据 3 | `FORBIDDEN_SPAWN` 命中 `subprocess` ⇒ 断言非空 |
| M4 | `src/timeflow/mcp/server.py` 里写一行 `threading.Timer(1.0, lambda: None)` | 判据 4 | `FORBIDDEN_TIMER` 命中 ⇒ 断言非空 |
| N1 | **只改注释**：把 `tools/pool_mcp.py:283` 那句「**只定义一次**：报错文案引这个常量，不另写字面量」换种说法（例如改成「只在此处定义」） | 无 | 五条判据全绿 —— 安静对照，证明钉子咬的是代码形状不是文字 |

> 变异脚本**不许**留在树上当钉子：`docs/subsystems/pool/README.md:79-80` 逐字「> 前两张都锚在**主工作树**…不在卡树 ——」「> 卡树里的 `gates/diag/` 是 gitignore 的，写进去等于没写（`tools/pool/registry.py:72`、`tools/pool/task.py:119`）。」

## 交付（逐文件）

- tests/test_pool_mcp_no_hub.py（**新建**）—— 五条判据全在这个文件里；文件头写一段「钉哪一位」表格（体例照 `tests/test_pool_gateway.py:1-32` 的头注释：r""" 里一张 `| 钉子 | 钉哪一位 |` 表 + 末段「★ 全部用桩：…**一个字节都不出网**」），docstring 第一句写明「★ 本文件钉的是**不移植**：F60 判 SKIP_NOT_APPLICABLE」，并注明五条全是反向钉子。
- `复盘/卡/卡A379-F60-MCP-hub-判SKIP_NOT_APPLICABLE.md`（计划建）—— 由本草稿转正（文件名立卡时定）；抬头把 `T-AG667` / `.wt/A379` 换成真号、基准换成立卡时主树 HEAD。
- docs/changelog.d/T-AG667.md（计划建）—— 落地时按真台账号改名（`ls docs/changelog.d` 今天 365 份，命名形如 `T-AG385.md`），写「F60 判不移植 + 五条反向钉子」。

> **卡域里不列** `tools/pool_mcp.py`、`tools/pool/mcp_http.py`、`src/timeflow/mcp/server.py`、`docs/subsystems/pool/README.md`、`docs/subsystems/pool/modules.toml`：本卡**产品码一个字不改**（五条判据全是「现状已成立、只要钉住」）。
> **README 表 B 那一行归 A373**：`复盘/卡/卡A373-F94图像识别替身seer-判SKIP_BY_REDLINE.md` 的交付段已声明「表 B 加第 8 行」（表 B 今天七行，第 7 行在 `docs/subsystems/pool/README.md:174`）并把它列进自己的域。本卡**不碰 README**，避免两卡同一行打架（`tools/pool/plan.py:60-64` 是精确字符串相交，同一路径进两张卡就会被冲突域拦下）。
> **modules.toml 也不列**：本卡不新增 `tools/pool/*.py`，按 `scripts/gen_pool_readme.py:27-29`「仓里有、清单里没有的模块 ⇒ 退 1 并**点名**（不许静默跳过：漏一个模块，读者就以为它不存在）」，清单不需要动，`--check` 保持绿。

## 验收（可直接跑）

```bash
cd .wt/A379
python -X utf8 -m pytest tests/test_pool_mcp_no_hub.py -q -o addopts= --no-cov
python -X utf8 -m ruff check tests/test_pool_mcp_no_hub.py
python -X utf8 scripts/gen_pool_readme.py --check
grep -rnE 'MCPHub|mcp_hub|hubSep|hubIdle' tools/ src/ scripts/ tests/ ; echo 期望 0 命中
grep -rnE 'threading\.Timer|Timer\(|AfterFunc' tools/ src/ ; echo 期望 0 命中
grep -nE 'subprocess|Popen' tools/pool/mcp_http.py src/timeflow/mcp/server.py ; echo 期望 0 命中
python -X utf8 gates/diag/_rev_F60.py
```

已知噪音（别当红）：

- `-o addopts= --no-cov` **必须带**：`pyproject.toml:51` 的默认 addopts 是 `-q -m "not acceptance and not chain" --cov=timeflow --cov-fail-under=70`，只跑一个新文件也会因覆盖率不达标而红。
- 光秃秃的 `grep -rn hub` 会撞 `github`：今天 10 条命中全是 `github:` / `.github/` 字样 ⇒ 验收里的 grep 必须用上面那份词表，不要用 `hub`。
- **别在 `tools/pool_mcp.py` 上做「零 subprocess」断言**：它今天 20 处命中且都是正当的 CLI 子进程（门禁锁 / 起工人 / task claim）。谁把判据 3 的对象写成整个 `pool_mcp`，那条判据当场就是红的 —— 那是断言写错。
- 判据 2 依赖 `tools/pool/mcp_http.py` 已存在（A365 已 done）—— 若在更早的树上跑，`import` 会失败，那是树不对不是判据错。
- 反向变异脚本跑完必须 `git checkout --` 复原；**不许**把变异带进落地提交。

## 不许做

1. **不许实现 hub**：不新建 tools/pool/mcp_hub.py、不在 `tools/pool/mcp_http.py` 里加 `{agent}` 路由、不加 `<server>__<tool>` 命名 —— 本卡的全部意思是**不做**。
2. **不许在 MCP 面起子进程**：`tools/pool/mcp_http.py` 与 `src/timeflow/mcp/server.py` 里 `subprocess|Popen` 今天 **0 命中**（判据 3 咬着），加一行就红。号池侧那 20 处既有 subprocess 是 CLI 用途，**本卡一个都不动、也不许拿它们当 hub 的起点**。
3. **不许写 agent 配置文件、不许产 deeplink**：`mcpServers|mcp_servers|cursor://|vscode:mcp` 今天在 `src/` 与 `tools/` 都 0 命中（判据 5）；同族判定见 `gates/diag/_magpie_scope.md:12`、`:69`、`:83`。
4. **不许碰** `tools/pool/plan.py:46-53` 列出的六份 PROTECTED_FILES（docs/traceability.toml、docs/changelog.md、复盘/交接-重构进度.md、复盘/新窗口交接卡.md、gates/last.json、gates/reuse.json）；卡域 `files` 不许写通配（`:60-64`、`:285-291`）。
5. **不许碰** `docs/subsystems/pool/README.md` 表 B（那一行归 A373 的域），也不许改 `docs/subsystems/pool/modules.toml:245-248` 的既有条目（本卡没有新模块）。
6. **不许改仓外** `D:/repo/infra/**`；也不许改 magpie 源码 `D:/repo/program/_ext/magpie-main/**`（那份是只读参照）。
7. **不许**把未建的文件写成反引号路径（死指针会回涨到基线之上）：本草稿里凡未创建的文件都写「（计划建）」。

## 与已完成卡的关系

- **A365**（`tools/pool/mcp_http.py` 的出生卡）：本仓「一个进程一个 server」的传输现状就是它定的；本卡判据 2、3 钉在这层的签名与 import 面上，**不改它一行**。
- **A373**（F94 判 SKIP_BY_REDLINE）：同一批 magpie 判定里的 SKIP 体例来源（论证 + 反向钉子 + 反向变异）。它占用 `docs/subsystems/pool/README.md` 表 B 第 8 行；本卡让开。
- **卡 A378（F59）**：本卡 depends 它。理由不是代码耦合，而是**判定次序**：F59 落地后本仓才有「路径表」，判据 2（没有 `agent` 维度）才有一个具体对象可钉；F59 还没落时那条断言只能钉在 `build_server` 的形参表上，一样成立但说服力弱一层。
- **E143**：上限/窗口类元数据的常客依赖（`MAX_LINE_BYTES` 那族），同批落地。

## 未坐实项（草稿如实标注，别当成结论）

- **未坐实**：`_magpie_features.md:514` 说的「5 个 agent」这个数字 —— 我没有在 magpie 源码里数出是哪五个，也没有逐行读 `internal/library/mcp.go` 的写出逻辑（只读了 `:33`、`:530`、`:557` 三行）。SKIP 的结论**不依赖**这个数字（它论证的是「本仓没有配置写入层」，而不是「agent 少于 5 个」），但引用这个数字时要知道它是功能清单的话、不是源码读数。
- **未坐实**：hub 的 per-agent 可见性（`Tools(ctx, agent string)` 与「Library 关掉的不列」）我只读到接口签名（`hub_mcp.go:43-60`）与功能清单的判据行（`_magpie_features.md:517`），**没有**逐行读它的实现，所以「per-agent 需要一层开关配置」这句是从签名推的。
- **未取证**：tests/test_pool_mcp_no_hub.py 这个文件名今天不存在（`ls` 报 No such file；`git ls-files tests | grep -i mcp` 八份里也没有 `test_no_hub*`）；若立卡时发现同名/近名文件已存在，按既有文件合并，别硬建第二个。
- **未取证**：判据 5 里那条 `assert "mcpServers" not in .../modules.toml` 今天为真（`grep` 0 命中），但我**没有**逐条读那 52 条 `[[module]]` 的 duty 文本（`grep -c "\[\[module\]\]" docs/subsystems/pool/modules.toml` = 52，`dce8d904` 实读）；若立卡时发现某条 duty 里出现该词，按「只钉代码不钉文档」把那条断言缩到 `src/ 与 tools/` 的 `*.py`。
- **未坐实**：`gates/diag/_magpie_scope.md:68` 那条 PORT|no 是普查时的粗判；本卡改判 SKIP_NOT_APPLICABLE 的理由写在「结论」三条里，但**改判定表本身不是本卡的活**（那张表未跟踪、也没有门咬它）—— 立卡后应把 `:68` 那一行同步改掉，否则两张纸会漂。

## 落地时实测与口径（2026-11-20，本卡自己；读数都在 `.wt/A379` 里真跑，不是估的）

> 这一段是落地后追加的实测记录（体例同卡 E125 的「落地时的两处调整」）；上面判据原文一字未改。

- **判据 1 的词表带词边界，验收 grep 要排除钉子文件自己**：`tests/test_pool_mcp_no_hub.py` 自己就写着这四个词（词表在 `:44`、两处 docstring 在 `:49`/`:81`），所以规格验收里那条 `grep -rnE 'MCPHub|mcp_hub|hubSep|hubIdle' tools/ src/ scripts/ tests/` 按字面跑会**自撞 3 条**。实读：整根跑 3 条命中**全在新文件里**，**排除钉子文件后 0 命中**（`grep … | grep -v test_pool_mcp_no_hub.py` 退 1）。判据 1 的扫描根是 `tools/ src/ scripts/`、**不含 `tests/`**，所以这条钉子本身不受影响 —— `__pycache__` 里的 `.pyc` 二进制命中同理（`_py_files()` 跳过 `__pycache__`）。
- **M1 用了规格「或」里的后一半**：规格写「加 `MCPHUB = "hub"`（或 `class MCPHub: ...`）」；判据 1 的词表**大小写敏感**，全大写的 `MCPHUB` 咬不住，故变异用括号里的写法（`MCPHub = "hub"` 与 `class MCPHub` 词形状相同）。这是与规格字面的唯一偏差，读数照抄在 `gates/diag/_rev_379_result.txt`。
- **实现落点**：五条判据全在新建的 `tests/test_pool_mcp_no_hub.py`（169 行）—— `test_no_hub_concept_in_sources` / `test_transport_has_no_agent_dimension` / `test_mcp_face_never_spawns_a_process` / `test_no_idle_reclaim_timer` / `test_no_agent_config_writer`。判据 1 扫 `tools/ src/ scripts/` 的 `*.py` 并对**文件名**也扫一遍；判据 2 用 `inspect.signature` 读 `build_server` 与 `serve_http` 的形参表，另加 `not hasattr(mcp_http, "HubMCPPath")`；判据 3 取 `inspect.getsource(mcp_http)` + `src/timeflow/mcp/server.py` 两处源码（**不扫 `tools/pool_mcp.py`**，它今天 20 处正当 CLI 子进程）；判据 4 扫 `tools/ src/`；判据 5 扫 `tools/ src/` 并另加 `docs/subsystems/pool/modules.toml` 不含 `mcpServers`。
- **变异落点**（脚本在主树 `gates/diag/_rev_379.py`，**不在卡树**；结果落 `gates/diag/_rev_379_result.txt`；★ 验收 `:128` 写的是 _rev_F60.py —— 那个名字今天不存在，按「一卡一脚本」实际命名为 _rev_379.py，体例同 `gates/diag/_rev_E98.py`）：M1 `tools/pool_mcp.py` 加 `MCPHub` 常量 ⇒ 咬住 `test_no_hub_concept_in_sources`；M2 `tools/pool/mcp_http.py` 的 `build_server` 加 `agent: str = ""` ⇒ 咬住 `test_transport_has_no_agent_dimension`；M3 `tools/pool/mcp_http.py` 顶部 `import subprocess` ⇒ 咬住 `test_mcp_face_never_spawns_a_process`；M4 `src/timeflow/mcp/server.py` 写一行 `threading.Timer(1.0, lambda: None)` ⇒ 咬住 `test_no_idle_reclaim_timer`；N1 只改 `tools/pool_mcp.py:283` 那句注释的措辞 ⇒ 五条全绿（安静对照未响，是对的）。每条都真改→真跑→`try/finally` 真还原→`sha256[:16]` 核对；三份被改文件复原后分别是 `28b3f8db34dbb849`、`9e4ea2721f3b2818`、`e2607526e99cbfbb`，钉子文件 `6b3ede3c5af81286`。
- **实测读数**（全部实跑，原样）：
  - `python -X utf8 -m pytest tests/test_pool_mcp_no_hub.py -q -o addopts= --no-cov -p no:xdist` ⇒ `5 passed in 2.76s`，exit 0。
  - `python -X utf8 -m ruff check tests/test_pool_mcp_no_hub.py` ⇒ `All checks passed!`，exit 0。
  - `python -X utf8 scripts/gen_pool_readme.py --check` ⇒ `[OK  ] docs/subsystems/pool/README.md 与现算一致（52 个文件 / 21297 行 / 2026-11-20）`，exit 0。
  - 判据 4、5 的 grep 各自 exit 1（0 命中）；判据 1 的那条 grep 排除钉子文件后 exit 1。
  - `python -X utf8 gates/diag/_rev_379.py` ⇒ 末行「结论：4/4 条全部咬住，收尾绿。」，exit 0。
- **第二份「计划建」的现实**：`docs/changelog.d/T-AG667.md` 本卡**没有**产出（试写过一份，`tools/sync_docs.py --check` 当场红：`[FAIL] … docs/changelog.d/T-AG667.md 的内容没在 docs/changelog.md 里`，已撤）。它**不在** `docs/workbacklog.toml` 的 A379 `files` 两项里（那两项是钉子文件与本规格）—— changelog 片段由落地链 ② 生成（`tools/pool/stage_card.py:303-306` 的片段模式、`tools/pool/landing.py:95` 的 `RESET_FRAGMENTS` ⓪ 步先删卡树里的新片段），手写一份只会让全量门的 `docs_fragments_problems()`（`scripts/run_gates.py:1152`）红。
- **未做**：`gates/diag/_magpie_scope.md:68` 那行仍写着 PORT（改判定表不是本卡的活，见上面「未坐实项」最后一条）；`docs/subsystems/pool/README.md` 表 B 那一行归 A373，本卡一字未碰。
