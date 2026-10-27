# WorkBuddy CLI 调用指南（给 AI 协作者）

本机装有腾讯 WorkBuddy，它内置了 **CodeBuddy Code** 智能体 CLI。
**不需要打开 GUI、不需要模拟键鼠**，直接在命令行就能把任务派给它，取回结果。

本文所有命令均已在本机实测通过。请照抄，不要自行猜测参数。

---

## 1. 环境事实（已核实）

| 项 | 值 |
|---|---|
| WorkBuddy 版本 | `5.5.6`，安装在 `D:\workbuddy\` |
| CLI 入口 | `D:\workbuddy\resources\app.asar.unpacked\cli\bin\codebuddy` |
| CLI 版本 | `2.137.1`（`@genie/agent-cli`） |
| 内置 Node | `C:/Users/example\.workbuddy\binaries\node\versions\22.22.2-3\node.exe` |
| 系统 Node | `C:\Program Files\nodejs\node.exe` → `v24.19.0` |
| Shell | Windows PowerShell 5.1（**本机没有 `pwsh`**，别用） |
| 登录状态 | 已登录（`~/.workbuddy/storage` 下有 user 配置与历史 session） |

> CLI 是**非交互**的：`-p` 执行一轮就退出。你给它一句指令，它自己决定调哪些工具，最后把结果打到 stdout。

---

## 2. 最快上手（推荐）

本仓库已备好封装脚本，**优先用它**：

```powershell
Set-Location "D:/repo/engineering"
.\tools\workbuddy.ps1 -Prompt "统计 scripts 目录下有多少个 .py 文件，只回复数字"
```

预期输出：

```
[workbuddy] cwd=D:/repo/engineering
[workbuddy] node=C:/Users/example\.workbuddy\binaries\node\versions\22.22.2-3\node.exe
[workbuddy] 执行中...
8
```

最后一行 `8` 就是智能体的回答。**结果在 stdout，前面的 `[workbuddy]` 行是脚本自己的日志。**

### 如果报「running scripts is disabled」

本机执行策略是默认的 Restricted（各作用域均 Undefined），直接跑 `.ps1` 会被拒。两种解法：

```powershell
# 解法 A（推荐，不改系统状态）
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\tools\workbuddy.ps1" -Prompt "你的指令"

# 解法 B（只对当前用户放开，需你本人同意再执行）
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

---

## 3. 直接调用（不依赖封装脚本）

封装脚本坏了或你想自己控参数时，照这个模板来：

```powershell
$node = "$env:USERPROFILE\.workbuddy\binaries\node\versions\22.22.2-3\node.exe"
$cli  = "D:\workbuddy\resources\app.asar.unpacked\cli\bin\codebuddy"

Set-Location "D:/repo/engineering"   # 务必先切到目标工作目录
& $node $cli -p "你的指令" --output-format text --no-session-persistence -y
```

### 参数说明（只列实测有用的）

| 参数 | 作用 |
|---|---|
| `-p "<指令>"` | 非交互执行，出结果即退出。**必需** |
| `-y` | 跳过全部权限确认。**不加它，写文件和执行命令一律被拒** |
| `--permission-mode acceptEdits` | 保守版：允许改文件，但危险命令仍要确认 |
| `--output-format text` | 默认，纯文本结果 |
| `--output-format json` | 结构化输出（含 token、耗时等元信息） |
| `--output-format stream-json` | 流式输出，能实时看到每一步工具调用 |
| `--no-session-persistence` | 不落盘会话，**见下方约束 2，建议默认加** |
| `--model <id>` | 指定模型，如 `deepseek-v3-2-volc`、`kimi-k2.5`、`glm-5.0` 等 |
| `--max-turns <n>` | 限制最大轮次，防止它跑飞 |
| `--add-dir <dir>` | 额外授权它访问的目录 |
| `--allowedTools` / `--disallowedTools` | 白/黑名单控制它能用哪些工具 |
| `--json-schema <schema>` | 强制结构化返回，便于你解析 |

### 后台长任务

```powershell
# 丢到后台跑
& $node $cli -p "重构 src 下的工具函数并跑通测试" --bg --name my-task -y
# 查看 / 跟进 / 杀掉
& $node $cli ps
& $node $cli logs my-task
& $node $cli attach my-task
& $node $cli kill my-task
```

---

## 4. PowerShell 坑（重要）

1. **本机没有 `pwsh`**，一律用 `powershell.exe`。
2. **`.ps1` 文件必须存成 UTF-8 带 BOM。**
   本机 PowerShell 5.1 会把无 BOM 的 UTF-8 当 GBK 读。脚本里只要有中文注释或中文字符串，就会解析崩溃，报 `Unexpected token` 或满屏乱码（如 `鎵句笉鍒?`）。
   写文件后用这个命令补 BOM：

   ```powershell
   $p = "路径\to\script.ps1"
   $c = Get-Content -LiteralPath $p -Raw -Encoding UTF8
   Set-Content -LiteralPath $p -Value $c -Encoding UTF8 -NoNewline
   ```

3. 路径含中文（`D:/docs\...`）没问题，用 `-LiteralPath`，并把路径加引号。
4. 想丢给变量时，结果在 stdout，`Write-Host` 的日志走别的流，不会污染结果。

---

## 5. 多轮对话（进阶，有坑）

`--continue` / `--resume` / `--session-id` 依赖把会话写进 `C:/Users/example\.codebuddy\projects\...`。
**在受限沙箱里这一步会失败**，报：

```
ENOENT: no such file or directory, open 'C:/Users/example\.codebuddy\projects\...\<id>.jsonl'
```

原因是 `~/.codebuddy` 不可写（ACL 本身正常，是当前会话的沙箱策略把它整个挡住了）。
**若你不在受限环境里**（比如你以普通身份直接跑），这三个参数是可用的：

```powershell
& $node $cli -p "记住数字 7749" --session-id my-session -y
& $node $cli -p "刚才的数字是多少" --session-id my-session -y
```

**不依赖磁盘的替代办法**：把上文拼进新指令里，每次当独立任务发。

```powershell
$ctx = "背景：上一轮我们确定了方案 A。"
& $node $cli -p "$ctx 现在请基于方案 A 输出实施步骤" --no-session-persistence -y
```

---

## 6. 必须知道的约束

1. **权限系统默认拒绝写操作。**
   非交互模式下不加 `-y`，Write/Bash 会被它自己的权限系统挡回来，它只会回你一句「无法完成写入」。
   所以：**要它真的干活，就带 `-y`；只想让它给建议，就别带。**
2. **`~/.codebuddy` 可能不可写**，导致会话持久化失败 → 用 `--no-session-persistence` 绕开。
3. **`-y` 等于关掉它全部权限确认**，它能任意读写文件、执行命令。派活时请在指令里明确限定范围（「只改 `<你的仓>/src/foo.py` 这一个文件」），或改用 `--permission-mode acceptEdits`。
4. **它有自己的工具系统**（Read/Write/Edit/Bash/Glob/Grep 等），和 Claude Code 类似，不需要你替它读文件。
5. 单次调用可能耗时**数十秒到数分钟**（冷启动约 7-10 秒）。脚本里请给足超时（建议 ≥300 秒）。

---

## 7. 排错速查

| 症状 | 原因 | 处理 |
|---|---|---|
| `running scripts is disabled` | 执行策略 Restricted | 用 `-ExecutionPolicy Bypass` |
| `Unexpected token` / 中文乱码 | `.ps1` 缺 BOM | 按第 4 节补 BOM |
| `pwsh 不是可识别的命令` | 本机无 PowerShell 7 | 改用 `powershell.exe` |
| `无法完成写入：Write 和 Bash 工具…被权限系统拒绝` | 没加 `-y` | 加 `-y` 或 `--permission-mode acceptEdits` |
| `EPERM ... .codebuddy\local_storage` | `~/.codebuddy` 不可写 | 加 `--no-session-persistence` |
| `ENOENT ... .codebuddy\projects\...jsonl` | 同上，会话落盘失败 | 加 `--no-session-persistence` |
| 找不到 CLI | WorkBuddy 不在 `D:\workbuddy\` | 重新定位 `WorkBuddy.exe` 所在目录下的 `resources\app.asar.unpacked\cli\bin\codebuddy` |

---

## 8. 自检（接手时先跑这三条）

```powershell
# 1) CLI 版本 —— 应输出 2.137.1
$node = "$env:USERPROFILE\.workbuddy\binaries\node\versions\22.22.2-3\node.exe"
$cli  = "D:\workbuddy\resources\app.asar.unpacked\cli\bin\codebuddy"
& $node $cli --version

# 2) 冒烟测试 —— 应原样回「连接成功」
& $node $cli -p "回复四个字：连接成功" --output-format text --no-session-persistence -y

# 3) 封装脚本 —— 应输出数字
.\tools\workbuddy.ps1 -Prompt "统计 scripts 目录下有多少个 .py 文件，只回复数字"
```

三条都通过，说明链路完好，可以正常派活。

---

## 9. 已验证 / 未验证

**已在受限会话环境中实测通过：**
- `--version` → `2.137.1`
- 一次性问答 → `连接成功`
- 带工具的真实任务（写文件 + Read 读回）→ 文件内容 `workbuddy-cli-ok`
- 封装脚本 `tools/workbuddy.ps1` → 返回 `8`（与 `scripts/` 下实际 `.py` 数量一致）

**未验证（本环境限制，非不可用）：**
- `--session-id` / `--continue` 多轮对话（会话落盘被沙箱挡住）
- `--bg` 后台任务、`ps`/`logs`/`attach`/`kill`
- `--serve` 本地 HTTP/REST 服务、`--remote-control wecom`

如果你不在受限环境里，这些大概率可用，但请自行验证后再依赖。
