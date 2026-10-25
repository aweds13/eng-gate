# 云门禁机装配（卡 E35 · T-AG489；从 gates/diag/cloud_bootstrap.ps1 搬入库）
#
# 用法（云机管理员 PowerShell）：
#   powershell -ExecutionPolicy Bypass -File scripts\cloud\bootstrap.ps1
#   powershell ... -File scripts\cloud\bootstrap.ps1 -IndexUrl <pypi 镜像> -PythonUrl <url> -GitUrl <url>
# 全过程写 C:\setup.log（时间戳逐行）。
#
# ★ 版本一律钉死（2026-10-25 本机 pip freeze 的原样 pin）。
#   为什么必须钉：判据在两个环境里给两个答案 = 门禁结论不可复现。实测 rami：
#   云机 ruff 0.17.2 vs 本机 0.16.6，`I001` 判出不同结果 ⇒ tests/test_wb_land.py
#   的 test_preflight_* 4 条在云机红。钉子：tests/test_cloud_sync.py::test_bootstrap_pins_*。
#
# ★ 这份文件必须存成「UTF-8 with BOM」：PowerShell 5.1 读无 BOM 的中文 .ps1 会按 ANSI 解，
#   报「字符串缺少终止符」，且报的位置与真因无关。钉子同上（看首 3 字节 EF BB BF）。
# ★ .ps1 里不要嵌 `python -c "..."`：PowerShell 会先吃掉里层引号，python 收到半句话。
#
# 边界（如实写）：本脚本只装「解释器 + 依赖」，**不**碰仓外索引。
#   TF_PROJECTS_TOML（项目索引）由 scripts/cloud/run_gate.sh 显式注入并在跑之前断言存在。

param(
  [string]$IndexUrl = 'https://pypi.tuna.tsinghua.edu.cn/simple',
  [string]$PythonUrl = 'https://registry.npmmirror.com/-/binary/python/3.12.8/python-3.12.8-amd64.exe',
  [string]$GitUrl = 'https://registry.npmmirror.com/-/binary/git-for-windows/v2.47.1.windows.1/Git-2.47.1-64-bit.exe'
)

$ErrorActionPreference = 'Continue'
$log = 'C:\setup.log'
function Log($m) { $t = Get-Date -Format 'HH:mm:ss'; "$t $m" | Tee-Object -FilePath $log -Append }

Log "=== 开始装配（scripts/cloud/bootstrap.ps1）==="
$env:PATH = "C:\Program Files\Python312;C:\Program Files\Python312\Scripts;C:\Program Files\Git\cmd;" + $env:PATH

# ---- 依赖清单：★ 每条都带版本，改这里等于改判据口径（tests/test_cloud_sync.py 逐条核）----
# httpx / fsrs / psutil 三条是 2026-10-25 实测缺了必红的（见 docs/subsystems/ci/云门禁机.md §7.3）：
#   缺 httpx ⇒ starlette.testclient 起不来（65 条收集错误）；缺 fsrs ⇒ 39 条 ModuleNotFoundError；
#   缺 psutil ⇒ 53 条红（判据「psutil 不可用，判不了有没有进程」）。
$Packages = @(
  'fastapi==0.141.1',
  'uvicorn[standard]==0.52.4',
  'pydantic==2.13.4',
  'httpx==0.28.1',
  'fsrs==6.3.2',
  'psutil==7.2.2',
  'pytest==9.1.1',
  'pytest-cov==7.1.0',
  'pytest-xdist==3.8.0',
  'mypy==2.3.1',
  'ruff==0.16.6'
)

# ---------- Python ----------
if (-not (Test-Path 'C:\Program Files\Python312\python.exe')) {
  $urls = @($PythonUrl, 'https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe')
  foreach ($u in $urls) {
    try {
      Log "下载 Python: $u"
      Invoke-WebRequest -Uri $u -OutFile C:\py.exe -UseBasicParsing -TimeoutSec 300
      if ((Get-Item C:\py.exe).Length -gt 20MB) {
        Log "Python 下载完成 $((Get-Item C:\py.exe).Length) 字节"; break
      }
    } catch { Log "失败：$($_.Exception.Message)" }
  }
  Log "静默安装 Python"
  Start-Process C:\py.exe -ArgumentList '/quiet','InstallAllUsers=1','PrependPath=1','Include_pip=1' -Wait
}
Log ("python: " + (& 'C:\Program Files\Python312\python.exe' -V 2>&1))

# ---------- Git ----------
if (-not (Test-Path 'C:\Program Files\Git\cmd\git.exe')) {
  $gurls = @($GitUrl, 'https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/Git-2.47.1-64-bit.exe')
  foreach ($u in $gurls) {
    try {
      Log "下载 Git: $u"
      Invoke-WebRequest -Uri $u -OutFile C:\git.exe -UseBasicParsing -TimeoutSec 300
      if ((Get-Item C:\git.exe).Length -gt 30MB) {
        Log "Git 下载完成 $((Get-Item C:\git.exe).Length) 字节"; break
      }
    } catch { Log "失败：$($_.Exception.Message)" }
  }
  Log "静默安装 Git"
  Start-Process C:\git.exe -ArgumentList '/VERYSILENT','/NORESTART','/NOCANCEL','/SP-' -Wait
}
Log ("git: " + (& 'C:\Program Files\Git\cmd\git.exe' --version 2>&1))

# ---------- pip 镜像 + 依赖（钉版本）----------
$py = 'C:\Program Files\Python312\python.exe'
& $py -m pip config set global.index-url $IndexUrl 2>&1 | Out-Null
Log "安装门禁依赖（钉版本，镜像 $IndexUrl）"
& $py -m pip install --quiet --upgrade pip 2>&1 | Tee-Object -FilePath $log -Append | Out-Null
& $py -m pip install --quiet @Packages 2>&1 | Tee-Object -FilePath $log -Append | Out-Null

# ---------- 装完自检：三条必须**逐字**对上，对不上就响亮说出来（别让人半信半疑地开跑）----------
$frozen = & $py -m pip freeze 2>&1
$missing = @()
foreach ($pkg in $Packages) {
  $want = $pkg -replace '\[.*?\]', ''
  if ($frozen -notcontains $want) { $missing += $want }
}
if ($missing.Count -gt 0) {
  Log ("✗ 版本不符（装完的 pip freeze 里找不到）：" + ($missing -join ', '))
} else {
  Log "✓ 依赖版本与清单逐条一致"
}
Log ("pytest: " + (& $py -m pytest --version 2>&1))
Log ("ruff: " + (& $py -m ruff --version 2>&1))
Log ("mypy: " + (& $py -m mypy --version 2>&1))
Log "=== 装配结束 ==="
