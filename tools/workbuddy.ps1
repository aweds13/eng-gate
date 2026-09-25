<#
.SYNOPSIS
    从命令行调用本机 WorkBuddy (CodeBuddy Code) 智能体干活的封装脚本。

.DESCRIPTION
    直接调用 WorkBuddy 自带的 CLI，无需打开 GUI、无需模拟键鼠。
    默认使用 WorkBuddy 内置的 Node 运行时，避免依赖系统 node 版本。

.PARAMETER Prompt
    要交给智能体的任务指令。

.PARAMETER Text
    纯文本输出模式（默认），等价于 --output-format text。

.PARAMETER Json
    结构化输出模式，等价于 --output-format json。

.PARAMETER StreamJson
    流式输出模式，等价于 --output-format stream-json，可实时看到每一步。

.PARAMETER Safe
    保守权限：允许改文件，但危险的命令执行仍需确认（acceptEdits）。
    不加此开关时默认 -y，即跳过全部权限确认。

.PARAMETER ContinueSession
    用 --continue 接续“最近一次”对话。注意：见 README 的沙箱限制说明。

.PARAMETER MaxTurns
    限制智能体的最大轮次，防止它停不下来。

.EXAMPLE
    .\tools\workbuddy.ps1 -Prompt "把 src 下的函数按字母排序列出，只回复列表"

.EXAMPLE
    .\tools\workbuddy.ps1 -Prompt "修复 tests 里的失败用例并跑通" -Safe -MaxTurns 30

.EXAMPLE
    .\tools\workbuddy.ps1 -Prompt "统计本仓库各目录的文件数" -Json
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Prompt,

    [switch]$Text,
    [switch]$Json,
    [switch]$StreamJson,
    [switch]$Safe,
    [switch]$ContinueSession,
    [int]$MaxTurns = 0,
    [string]$WorkDir = (Get-Location).Path
)

$ErrorActionPreference = 'Stop'

# --- 定位 WorkBuddy 的内置 Node 运行时 -------------------------------------------------
$nodeRoot = Join-Path $env:USERPROFILE '.workbuddy\binaries\node\versions'
$nodeExe  = $null

if (Test-Path $nodeRoot) {
    $currentFile = Join-Path $nodeRoot 'current'
    if (Test-Path $currentFile) {
        $ver = (Get-Content $currentFile -Raw).Trim()
        $candidate = Join-Path $nodeRoot "$ver\node.exe"
        if (Test-Path $candidate) { $nodeExe = $candidate }
    }
    if (-not $nodeExe) {
        $found = Get-ChildItem $nodeRoot -Directory -ErrorAction SilentlyContinue |
                 Sort-Object Name -Descending |
                 ForEach-Object { Join-Path $_.FullName 'node.exe' } |
                 Where-Object { Test-Path $_ } |
                 Select-Object -First 1
        if ($found) { $nodeExe = $found }
    }
}

# 兜底：用系统 node（CLI 要求 >= 18.20.8）
if (-not $nodeExe) {
    $sys = Get-Command node -ErrorAction SilentlyContinue
    if ($sys) {
        $nodeExe = $sys.Source
        Write-Warning "未找到 WorkBuddy 内置 Node，回退到系统 node: $nodeExe"
    }
}
if (-not $nodeExe) { throw "找不到可用的 Node 运行时（内置和系统都没有）。" }

# --- 定位 CLI 入口 ---------------------------------------------------------------------
$cli = 'D:\workbuddy\resources\app.asar.unpacked\cli\bin\codebuddy'
if (-not (Test-Path $cli)) {
    throw "找不到 WorkBuddy CLI：$cli`n请确认 WorkBuddy 仍安装在 D:\workbuddy\。"
}

# --- 组装参数 -------------------------------------------------------------------------
$argList = @($cli, '-p', $Prompt)

if ($StreamJson)     { $argList += @('--output-format', 'stream-json') }
elseif ($Json)       { $argList += @('--output-format', 'json') }
else                 { $argList += @('--output-format', 'text') }

# 权限：默认跳过全部确认；-Safe 时只放开文件编辑
if ($Safe) { $argList += @('--permission-mode', 'acceptEdits') }
else       { $argList += '-y' }

# 会话持久化：默认关闭，避免写入 ~/.codebuddy 失败
if ($ContinueSession) { $argList += '--continue' }
else                  { $argList += '--no-session-persistence' }

if ($MaxTurns -gt 0) { $argList += @('--max-turns', "$MaxTurns") }

# --- 执行 -----------------------------------------------------------------------------
Write-Host "[workbuddy] cwd=$WorkDir" -ForegroundColor DarkGray
Write-Host "[workbuddy] node=$nodeExe" -ForegroundColor DarkGray
if (-not $StreamJson) { Write-Host "[workbuddy] 执行中..." -ForegroundColor DarkGray }

Push-Location $WorkDir
try {
    & $nodeExe @argList
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}

exit $code
