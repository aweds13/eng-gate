# 卡 A362 —— MCP 那一行有多长才算太长（T-AG573）

> 台账号 `T-AG573` ｜ 分区 A（magpie 移植）｜ 树 `.wt/A362` ｜ 层 判据层
> 依据：magpie `internal/gateway/search_mcp.go:226-243`（`readMCPBody` 与那条 #1766 注释）/ `:80`、`internal/gateway/mcp.go:83`（`readMCPBody(w, r, 32<<20)`）、`internal/gateway/vision_mcp.go:34`（`const visionMCPBody = 32 << 20`）。
> 设计原件：`D:/repo/program/_ext/_port_design_wave5.md` 的 **§2.3（第 522–683 行，先整节读完）**。
> 基准提交 `55863a2b`（主树 HEAD）。
> 与在飞卡的关系：只碰 `tools/pool_mcp.py`（`_read_line` 加长度上限 + `serve()` 加一个 except 分支）+ 新 `tests/test_pool_mcp_line_cap.py`。

## 要解决的问题

`tools/pool_mcp.py:233 _read_line()` 的 docstring 逐字写着「按字节逐行读 → 坏行只坏那一行」，那三句关于**坏字节**的话都是对的、都不许改。但它有个**没有上限**的洞：`raw: bytes = buffer.readline()` —— 一行可以是无限长，`serve()` 只处理 `UnicodeDecodeError`（解码失败），**没有长度判据**。

magpie 那边撞过同一个洞，并且留下了这个仓库里少见的「一句话把判据讲完」的注释（`search_mcp.go:226-229` 逐字）：

> readMCPBody reads a request body of at most limit bytes, answering 413 for a longer one.
> **A LimitReader alone ends at the limit as if the body had, so a valid message padded past it
> was read as its prefix and run (#1766); one byte more tells a body that ended from one that was cut.**

即：**只读满上限就停**会让「超限的合法消息」被当成它的前缀**照常执行** —— 那不是拒绝，那是把一个被截断的东西当完整的跑。判据是**多读一字节**：读满 `limit` 之后不能下结论，要再读 1 字节，看有没有第 `limit+1` 个。

## 判据（8 条，逐条可执行）

**本卡的判据就是设计原件 §2.3「判据（每条能被一条 pytest 咬住）」那 7 条 + 一条常量钉子**：

1. 喂一行**超限的合法 JSON** ⇒ 回一条错误，**不执行它**。这是 #1766 的全部要点：超限体**不许**被当成前缀执行。
2. **边界两侧**：长度恰等于 `MAX_LINE_BYTES` ⇒ **执行**；等于 `MAX_LINE_BYTES + 1` ⇒ 拒。两条都要，否则 `>` 与 `>=` 改错看不出来。
3. 拒的判定必须**多读一字节**才下结论。咬法：一个正好 `MAX_LINE_BYTES` 字节、**末尾没有换行**的合法 JSON ⇒ 必须执行（如果实现只读满就判「被切」，这条会红）。
4. 拒之后**继续服务下一行**（不许退出循环），并且**要能把这一行剩下的字节吃完** —— 否则残余字节会被当成下一行。咬法：写「超限的合法 JSON + `\n` + 一条正常 `tools/list`」⇒ 必须回一条错误 + 一条正常结果，且顺序如此。
5. 判据 4 的边界：若残余字节吃完过程中**又**出现坏字节 ⇒ 只坏那一行（既有行为，`tools/pool_mcp.py` 的三道防线不许破）。
6. `MAX_LINE_BYTES` 是**常量**，只定义一次，报错文案里引它；另有一条钉子断言 `MAX_LINE_BYTES == 32 << 20`（照 `mcp.go:83`）。
7. 报错文案说清「这一行太长」+ **实际字节数**（照 `_read_capped` 的「截断明示总长」体例）。断言文案里的数字 == `MAX_LINE_BYTES`，**不是**随便一个数字（否则改常量钉子跟着变 = 空转）。
8. **`_read_line` 的三句既有注释所描述的行为一个字不改**：按字节读、坏字节抛给调用方、不 `errors="replace"`。本卡只加长度上限。

## 交付

- `tools/pool_mcp.py`：
  - 加 `MAX_LINE_BYTES: int = 32 << 20`（模块级常量，**只定义一次**）与 `class LineTooLong(Exception)`（带读到的字节数）。
  - `_read_line(limit: int = MAX_LINE_BYTES) -> str | None`：读满 `limit` 之后**再读 1 字节**才判；超限抛 `LineTooLong`；EOF 仍回 `None`。
  - `serve()` 主循环（`:2466-2477`）在 `except UnicodeDecodeError` **之前**加 `except LineTooLong` 分支：回一条 JSON-RPC 错误（**码用 `JSONRPC_INVALID_PARAMS`**，这是本卡的判断题不是抄的，在注释里写明）+ **把残余字节吞到行尾** + `continue`。
  - **不许动 `_emit` 的「唯一写 stdout」不变量**。
- `tests/test_pool_mcp_line_cap.py`（新）：设计原件 §2.3「测试钉子名」那 **8 条**，名字逐字。
- `gates/diag/_rev_A362.py`（新）：设计原件「反向变异」表那 **5 条**，逐条真改坏、跑、证明某条钉子变红、再还原。★ 原表如实交代了**最容易空转的一位**（`limit+1` → `limit`）：钉子 3 必须用「正好 `limit` 字节 + **无换行**」，否则末尾有 `\n` 时两种实现在 `readline()` 下表现一样、改了没人发现。脚本必须有 `_preflight()`（锚点命中恰好 1 次）+ `try/finally` 必还原 + `_snapshot()`/`_restore_all()` + 每次先 `shutil.rmtree(tools/__pycache__)` 并传 `PYTHONDONTWRITEBYTECODE=1`。收尾打印 `结论：X/X 条全部咬住，收尾绿。`
- 卡规格：`复盘/卡/卡A362-MCP那一行有多长才算太长.md`。**卡规格里不许点名任何还没落地的文件路径**（会被 `check_docs` 判成死指针 —— 本轮已踩 4 次）。

## 验收

```bash
cd .wt/A362
python -X utf8 -m pytest tests/test_pool_mcp_line_cap.py tests/test_pool_mcp.py -q -o addopts= --no-cov
python -X utf8 -m ruff check tools/pool_mcp.py tests/test_pool_mcp_line_cap.py
python -X utf8 gates/diag/_rev_A362.py
```

末行要求：`N passed` / `All checks passed!` / `结论：X/X 条全部咬住，收尾绿。`
★ **不要跑全量 pytest / `scripts/run_gates.py`**（本机并发全量会把 1800 秒硬超时撞穿），只跑上面这几个文件。

## 不许做

- **不许搬 `defaultBodyLimit = 512 << 20` 与 gzip/zstd**：那是 HTTP 请求体，pool 的入站是 stdio 一行，量级不同；抄 512 MB 当行上限等于没有上限。
- **不许搬 415**（媒体类型）：stdio 没有 `Content-Type`。
- **不许把上限做成「读到就截断再解 JSON」**：那正是 #1766 修的 bug。
- **不许动 `_emit` 的「唯一写 stdout」**。
- **不许改 `_read_line` 那三句注释所描述的行为**（按字节读、坏字节抛给调用方）。本卡只加长度上限。
- 不许碰 `tools/pool/lastgood.py` / `tools/pool_accounts.py` / `tools/pool/pricing.py` / `tools/pool/cleared.py` / `tools/render_check.mjs` / `tools/ui_flow_check.mjs`（各有在飞卡或刚落）。
- 不许碰六份 `PROTECTED_FILES`。

## 缺口的如实交代（进 changelog 的 gaps）

1. **`413` 这个状态码没有对应物**：pool 回的是 JSON-RPC 错误对象，不是 HTTP 状态码。本卡选 `JSONRPC_INVALID_PARAMS` 并在 message 里写明长度 —— **这是本卡的判断题，不是从 magpie 抄的**，标「判不出」的部分在这里。
2. **`Connection: close` 没有对应物**：stdio 长连接不关，所以只能「吞残余、继续服务」。
3. **`search_mcp.go:80` 的「`limit` 由调用方给」形态不抄**：pool 只有一个 stdio 面，一个常量够。
4. **`LineTooLong` 若是 `UnicodeDecodeError` 的子类，有一位变异没有钉子**（设计原件如实记的），本卡不处理。

## 直做

先整节读完设计原件 `_ext/_port_design_wave5.md` §2.3（Go 源码逐字取证、7 条判据、完整签名、接入点锚点原文、8 条钉子名、5 条变异与空转条件、禁令、4 条缺口）。然后按上面直接实现、直接跑验收、直接写反向验证。回执里逐项给：改了哪些文件（字节 / crlf / bare_lf）、三条验收末行原文、变异清单与咬住情况、以及任何一处需要主控知情的偏离。
