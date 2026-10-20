# 执笔 · 本机一键启动
# 数据库与 Redis 跑在 Docker 里；后端、后台任务和网页直接在本机运行。
param(
    [switch]$Isolated,
    [string]$DataDirectory,
    [int]$ApiPort = 8000,
    [int]$WebPort = 4320,
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$defaultData = [IO.Path]::GetFullPath((Join-Path $root 'data'))
if ($Isolated) {
    # 独立验收必须显式提供全部资源；绝不启动日常容器、写日常 PID 或用日常端口。
    if (-not $DataDirectory -or -not [IO.Path]::IsPathRooted($DataDirectory) -or
        [IO.Path]::GetFullPath($DataDirectory).TrimEnd('\') -eq $defaultData.TrimEnd('\') -or
        $ApiPort -in 8000, 4320 -or $WebPort -in 8000, 4320 -or $ApiPort -eq $WebPort -or
        $env:ZHIBI_DATABASE_URL -notmatch '/[^/?]*(?:test|preview|accept)[^/?]*(?:\?.*)?$' -or
        $env:ZHIBI_REDIS_URL -notmatch '/[1-9][0-9]*(?:\?.*)?$' -or -not $env:ZHIBI_SECRET_KEY) {
        throw '独立启动需要独立 data 绝对路径、非 8000／4320 的两个端口、名称含 test／preview／accept 的数据库、非 0 Redis 库和 ZHIBI_SECRET_KEY'
    }
    $env:ZHIBI_API_URL = "http://127.0.0.1:$ApiPort"
}
if (-not $DataDirectory) { $DataDirectory = $defaultData }
$logDir = Join-Path $DataDirectory 'logs'
$pidFile = Join-Path $DataDirectory 'pids.json'
New-Item -ItemType Directory -Force $logDir | Out-Null

function Step($text) { Write-Host "`n▶ $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "`n✗ $text" -ForegroundColor Red; exit 1 }
function PortOpen($port) {
    try { $c = New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1', $port); $c.Close(); return $true } catch { return $false }
}

foreach ($cmd in $(if ($Isolated) { @('uv', 'npm') } else { @('docker', 'uv', 'npm') })) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { Fail "没有找到 $cmd，请先安装" }
}

if (Test-Path $pidFile) {
    Step '检测到上次启动的进程，先停止'
    & (Join-Path $PSScriptRoot 'stop.ps1') -Quiet -Isolated:$Isolated -DataDirectory $DataDirectory
}

Step '检查配置文件 .env'
if (-not $Isolated -and -not (Test-Path '.env')) {
    $key = (uv run --directory backend python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())").Trim()
    $text = (Get-Content '.env.example' -Raw -Encoding UTF8) -replace 'ZHIBI_SECRET_KEY=', "ZHIBI_SECRET_KEY=$key"
    [IO.File]::WriteAllText((Join-Path $root '.env'), $text, (New-Object Text.UTF8Encoding $false))
    Write-Host '已生成 .env（含加密密钥，请勿外传）'
}

if (-not $Isolated) {
    Step '启动数据库和 Redis（Docker）'
    docker info *> $null
    if ($LASTEXITCODE -ne 0) { Fail '请先打开 Docker Desktop，等它启动完成后再运行' }
    docker compose up -d --wait postgres redis
    if ($LASTEXITCODE -ne 0) { Fail '数据库启动失败，请查看上面的错误信息' }
}

Step '安装后端依赖并升级数据库结构'
if (-not $Isolated) {
    uv sync --directory backend --quiet
    if ($LASTEXITCODE -ne 0) { Fail '后端依赖安装失败' }
}
# 只解析 Alembic 的版本行；日志走标准错误，不把日志误认成版本号。
$currentOutput = @(uv run --directory backend alembic current)
if ($LASTEXITCODE -ne 0) { Fail '读取当前数据库版本失败，没有升级数据库' }
$headsOutput = @(uv run --directory backend alembic heads)
if ($LASTEXITCODE -ne 0) { Fail '读取最新数据库版本失败，没有升级数据库' }
$current = @($currentOutput | Where-Object { $_ -match '^\S+(?:\s+\([^)]*\))*\s*$' } | ForEach-Object { ($_ -split '\s+')[0] })
$heads = @($headsOutput | Where-Object { $_ -match '^\S+\s+\(head\)\s*$' } | ForEach-Object { ($_ -split '\s+')[0] })
if ($heads.Count -ne 1 -or $current.Count -gt 1 -or ($currentOutput.Count -gt 0 -and $current.Count -eq 0)) {
    Fail '数据库迁移版本无法唯一确认，没有升级数据库'
}
if (-not $Isolated -and $current.Count -gt 0 -and $current[0] -ne $heads[0]) {
    Step '升级前备份数据库'
    $backupPath = & (Join-Path $PSScriptRoot 'backup-db.ps1') -Label "before-$($heads[0])"
    if ($LASTEXITCODE -ne 0) { Fail '升级前备份失败，没有升级数据库' }
    Write-Host "已备份到 $backupPath"
}
uv run --directory backend alembic upgrade head
if ($LASTEXITCODE -ne 0) { Fail '数据库升级失败' }

Step '安装前端依赖'
if (-not $Isolated -and -not (Test-Path 'frontend\node_modules')) { npm --prefix frontend install --silent }

foreach ($port in $ApiPort, $WebPort) {
    if (PortOpen $port) { Fail "端口 $port 已被占用，请先关闭占用它的程序（或运行 停止.cmd）" }
}

Step '启动后端、后台任务和网页'
$backend = Join-Path $root 'backend'
$procs = @{
    api    = Start-Process uv -WorkingDirectory $backend -WindowStyle Hidden -PassThru `
        -ArgumentList 'run', 'uvicorn', 'app.main:app', '--port', "$ApiPort", '--loop', 'asyncio:SelectorEventLoop' `
        -RedirectStandardOutput "$logDir\api.log" -RedirectStandardError "$logDir\api.err.log"
    worker = Start-Process uv -WorkingDirectory $backend -WindowStyle Hidden -PassThru `
        -ArgumentList 'run', 'celery', '-A', 'app.worker.celery_app', 'worker', '-P', 'solo', '-Q', 'zhibi', '-n', 'zhibi@%h', '-l', 'info' `
        -RedirectStandardOutput "$logDir\worker.log" -RedirectStandardError "$logDir\worker.err.log"
    teardown = Start-Process uv -WorkingDirectory $backend -WindowStyle Hidden -PassThru `
        -ArgumentList 'run', 'celery', '-A', 'app.worker.celery_app', 'worker', '-P', 'solo', '-Q', 'teardown', '-n', 'teardown@%h', '-l', 'info' `
        -RedirectStandardOutput "$logDir\teardown.log" -RedirectStandardError "$logDir\teardown.err.log"
    web    = Start-Process npm.cmd -WorkingDirectory (Join-Path $root 'frontend') -WindowStyle Hidden -PassThru `
        -ArgumentList 'run', 'dev', '--', '--port', "$WebPort" `
        -RedirectStandardOutput "$logDir\web.log" -RedirectStandardError "$logDir\web.err.log"
}
$procs.GetEnumerator() | ForEach-Object { @{ name = $_.Key; pid = $_.Value.Id } } | ConvertTo-Json | Set-Content $pidFile

Step '等待服务就绪'
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline) {
    if ((PortOpen $ApiPort) -and (PortOpen $WebPort)) { break }
    Start-Sleep -Seconds 1
}
if (-not ((PortOpen $ApiPort) -and (PortOpen $WebPort))) { Fail "服务没有按时启动，请查看日志：$logDir" }

Write-Host "`n✓ 执笔已启动：http://127.0.0.1:$WebPort" -ForegroundColor Green
Write-Host "  日志在 $logDir；关闭请运行 停止.cmd"
if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$WebPort" }
