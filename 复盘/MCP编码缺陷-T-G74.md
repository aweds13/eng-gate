# MCP 的 stdio 编码缺陷（T-G74）—— 中文出去是乱码、进来直接把服务端打崩

> 一句话：MCP 规范要求 stdio 上的消息是 **UTF-8**，而 `timeflow mcp` 跟着 Windows 控制台
> 代码页走（这台是 cp936）—— **出去**的中文是 GBK（规范客户端看到乱码）、
> **进来**的中文会让服务端当场崩（`UnicodeEncodeError`，客户端拿不到任何回话）。
> 触发这条卡的是用户 2026-09-25 选的「**用 DSH 接一次**」：配置写出来之前先自己探了一遍。
> 2026-09-25；分支 `line/impl-v1`。**只改 MCP，不动交互式命令行。**

---

## §1 怎么发现的（不是猜的，是读原始字节读出来的）

用户选了"用 DSH（就是我现在跑的这个 harness）接一次"→ 要给一条**能真用**的配置 →
先按客户端真实的方式手动握一次手（`timeflow.exe mcp`，真子进程真 stdio）：

| 探针 | 做什么 | 结果 |
|---|---|---|
| `gates/diag/probes/mcp_exe_check.py` | 照 DSH 的配置形状起子进程：`initialize` → `tools/list` → `tools/call today` | ✅ 14 个只读工具、没列出写工具、`db_missing` 也不建库 —— **协议层是通的** |
| `gates/diag/probes/mcp_encoding_probe.py` | 把**原始字节**按 UTF-8 与 GBK 各解一次 | ★ UTF-8 **解不开**（invalid start byte @130）、GBK 解得开 → **stdout 上是 GBK** |
| `gates/diag/probes/mcp_inbound_probe.py` | 发一条**中文标题**的 `add-task`（UTF-8），再看库里存了什么 | ★ 服务端**崩了**：`UnicodeEncodeError: 'utf-8' codec can't encode character '\udcad' ... surrogates not allowed`，任务没建、库是空的 |

三个探针都在 `gates/diag/probes/`（诊断用，**不进仓库**）。

**根因**（一眼就明白，但只有真跑才看得见）：

```python
for line in sys.stdin:                                    # ← 按语言环境编码解码（cp936）
    ...
sys.stdout.write(json.dumps(response, ensure_ascii=False)) # ← 按语言环境编码写（cp936）
```

客户端按规范发 UTF-8 → cp936 把它解成带**孤立代理**的怪字符（JSON 结构还在，所以不报错、
**静默改字**）→ 该字符串再被 `json.dumps(...).encode("utf-8")` 编码时抛 `UnicodeEncodeError`
→ 没兜住 → **整个服务端进程退掉**。

## §2 为什么以前的测试全绿（这才是最该记的一条）

`tests/test_mcp_line.py` 的"真 stdio"那几条，起子进程时写的是：

```python
[sys.executable, "-X", "utf8", "-c", SERVER_SNIPPET, *args], text=True, encoding="utf-8"
```

**`-X utf8` 正好把要验的那件事关掉了**：解释器被强制用 UTF-8 起，于是"服务端自己钉没钉编码"
从来没被问过；parent 侧又是 `encoding="utf-8"`，等于两头都由测试替它兜住了。
真客户端不会替我们加解释器开关 —— 它照配置直接 `spawn timeflow.exe mcp`。

> 教训与 T-G69/T-G71 同一族：**判据自己会在错的地方替被测者兜底**。
> 修法：测试改成**不加 `-X utf8`、按字节收发**（发 UTF-8 字节、收回来先按 UTF-8 解），
> 并把 stdout 的**原始字节**也断言一遍。这样这条判据在**任何**语言环境的机器上都在问真问题。

## §3 修法（三件，缺一件都不行）

1. **两头钉 UTF-8**（`_pin_stdio_utf8()`）：`sys.stdin/stdout/stderr` 都 `reconfigure(encoding="utf-8")`。
   ★ **只钉 MCP 这条协议**，**不动交互式命令行**：命令行是写给人看的、落在 Windows 老控制台上，
   本地编码反而是对的（钉成 UTF-8 会让 `cmd.exe` 里全是乱码）。协议是机器对机器，才必须 UTF-8。
   `--help` / 参数错那几条**在钉之前**就返回了 —— 它们是给人看的，走本地编码。
2. ★ **协议数据走字节，不走文本层**（`_read_line()` / `_emit()`）：JSON 自己 `.encode("utf-8")`
   写 `sys.stdout.buffer`，读也从 `sys.stdin.buffer` 读、**逐行解码**。
   为什么非这样不可：**第一版只做了第 1 条，实测不够** —— 一行坏字节之后 TextIOWrapper
   整个进入坏状态，连**它前面**那条正常请求的回话都拿不到（`mcp_badline_probe.py` 实测
   只收到 1 条回话）。改成逐行读之后：`[1, None, None, 4]` —— 坏行只坏那一行。
3. **一条坏消息不许打死循环**：不是 UTF-8 的字节 / 不是 JSON / 处理时冒出来的异常，
   一律只换**一条 JSON-RPC 错误**（`-32700` / 新增的 `-32603`），循环继续。
   与 T-G66 那句"别把栈丢给用户"是同一件事，只是对面从人换成了客户端：
   拿到一条错误还能接着用，拿到 EOF 就只能以为"这个服务坏了"。
   ★ 坏字节**故意不用** `errors="replace"`：替换符会把乱码当合法内容一路写进库 ——
   **静默改字比回一条错误坏得多**。

## §4 验收（`tests/test_mcp_line.py`，14 条全过）

| 测试 | 判什么 |
|---|---|
| `test_real_stdio_speaks_utf8_in_both_directions` | ★ ① stdout 原始字节能被 UTF-8 解码；② 中文标题发过去**一字不差**落库、回话里也是它 |
| `test_real_stdio_survives_a_bad_line` | ★ 坏字节 + 坏 JSON 插在**中间**：回两条 `-32700`，**后面那条正常请求照样有回话**（id 序列 `[1, None, None, 4]`） |
| 原有 12 条 | 形状 / 默认关 / 协议 / 端到端 —— 全部改成**不加 `-X utf8`** 的真客户端起法 |

真机探针（诊断，人手跑）：`mcp_exe_check.py`（`timeflow.exe` 直接握手）、
`mcp_encoding_probe.py`（原始字节判编码）、`mcp_inbound_probe.py`（中文进库）、
`mcp_badline_probe.py`（坏行之后还活着）。

## §5 给用户的 DSH 配置（这一卡的实际交付物之一）

`C:/Users/example\.dsh\profiles\web\cordis.patch.yml`（原来是空数组 `[]`）：

```yaml
- insert:
  - id: mcp-timeflow
    name: '@deepseek-ai/dsh-mcp-client'
    config:
      serverName: timeflow
      transport: stdio
      command: 'C:/Users/example\miniconda3\Scripts\timeflow.exe'
      args: ['mcp']
      cwd: 'D:/repo/engineering'
```

- `command` 用**装的入口 `.exe`** 而不是 `timeflow`：Windows 上 `spawn` 一个 `.cmd` 需要 shell，
  而 MCP 客户端是直接 spawn 的（`Get-Command timeflow` 在本机解析到的是 `.exe`，正好）。
- `cwd` 给死，`--db` 不写时用的就是那个项目的默认库（与桌面端同一个）。
- 插件包**不用另装**：`@deepseek-ai/dsh-mcp-client` 是 `@deepseek-ai/dsh` 自己的依赖。
- 该 profile 的 patch 是**热加载**的（`patchReload: live`），存盘即可；没出现就重启 DSH。
- 想连写工具：`args: ['mcp', '--allow-write', '--db', '<一份测试库>']`。

配置写进 `docs/人工验收-照着点.md` 的 D 组（连同"要看的三件事"）。
**这一条**仍留在人工那一栏：我能证明协议层通、编码对、边界在，但"DSH 里真接上、模型真调到"
要人在那个界面上点一次。

## §6 成本与边界

- 改动落点 **1 个文件**（`src/timeflow/mcp/server.py`）：+`_pin_stdio_utf8` / `_read_line` / `_emit`，
  `serve()` 的循环重写；测试文件重写了子进程起法 + 2 条新测试。
- **不动**：CLI 的输出编码（理由见 §3-1）、`contrast`/`render`/45 份黄金、命令表、契约、界面。
- 边界（不谎报）：① 我们仍然**没有**第三方 MCP SDK，"兼容"只证明到"按规范手写的握手 + 真字节 UTF-8"；
  ② 传输仍只做 stdio；③ `initialize` 的 `instructions` 与工具的 `description` 文案没动（措辞那条是另一件事）。
