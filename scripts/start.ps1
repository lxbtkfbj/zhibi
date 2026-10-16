# 执笔 · 本机一键启动
# 数据库与 Redis 跑在 Docker 里；后端、后台任务和网页直接在本机运行。
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$logDir = Join-Path $root 'data\logs'
$pidFile = Join-Path $root 'data\pids.json'
New-Item -ItemType Directory -Force $logDir | Out-Null

function Step($text) { Write-Host "`n▶ $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "`n✗ $text" -ForegroundColor Red; exit 1 }
function PortOpen($port) {
    try { $c = New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1', $port); $c.Close(); return $true } catch { return $false }
}

foreach ($cmd in 'docker', 'uv', 'npm') {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { Fail "没有找到 $cmd，请先安装" }
}

if (Test-Path $pidFile) {
    Step '检测到上次启动的进程，先停止'
    & (Join-Path $PSScriptRoot 'stop.ps1') -Quiet
}

Step '检查配置文件 .env'
if (-not (Test-Path '.env')) {
    $key = (uv run --directory backend python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())").Trim()
    $text = (Get-Content '.env.example' -Raw -Encoding UTF8) -replace 'ZHIBI_SECRET_KEY=', "ZHIBI_SECRET_KEY=$key"
    [IO.File]::WriteAllText((Join-Path $root '.env'), $text, (New-Object Text.UTF8Encoding $false))
    Write-Host '已生成 .env（含加密密钥，请勿外传）'
}

Step '启动数据库和 Redis（Docker）'
docker info *> $null
if ($LASTEXITCODE -ne 0) { Fail '请先打开 Docker Desktop，等它启动完成后再运行' }
docker compose up -d --wait postgres redis
if ($LASTEXITCODE -ne 0) { Fail '数据库启动失败，请查看上面的错误信息' }

Step '安装后端依赖并升级数据库结构'
uv sync --directory backend --quiet
if ($LASTEXITCODE -ne 0) { Fail '后端依赖安装失败' }
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
if ($current.Count -gt 0 -and $current[0] -ne $heads[0]) {
    Step '升级前备份数据库'
    $backupPath = & (Join-Path $PSScriptRoot 'backup-db.ps1') -Label "before-$($heads[0])"
    if ($LASTEXITCODE -ne 0) { Fail '升级前备份失败，没有升级数据库' }
    Write-Host "已备份到 $backupPath"
}
uv run --directory backend alembic upgrade head
if ($LASTEXITCODE -ne 0) { Fail '数据库升级失败' }

Step '安装前端依赖'
if (-not (Test-Path 'frontend\node_modules')) { npm --prefix frontend install --silent }

foreach ($port in 8000, 4320) {
    if (PortOpen $port) { Fail "端口 $port 已被占用，请先关闭占用它的程序（或运行 停止.cmd）" }
}

Step '启动后端、后台任务和网页'
$backend = Join-Path $root 'backend'
$procs = @{
    api    = Start-Process uv -WorkingDirectory $backend -WindowStyle Hidden -PassThru `
        -ArgumentList 'run', 'uvicorn', 'app.main:app', '--port', '8000', '--loop', 'asyncio:SelectorEventLoop' `
        -RedirectStandardOutput "$logDir\api.log" -RedirectStandardError "$logDir\api.err.log"
    worker = Start-Process uv -WorkingDirectory $backend -WindowStyle Hidden -PassThru `
        -ArgumentList 'run', 'celery', '-A', 'app.worker.celery_app', 'worker', '-P', 'solo', '-l', 'info' `
        -RedirectStandardOutput "$logDir\worker.log" -RedirectStandardError "$logDir\worker.err.log"
    web    = Start-Process npm.cmd -WorkingDirectory (Join-Path $root 'frontend') -WindowStyle Hidden -PassThru `
        -ArgumentList 'run', 'dev' `
        -RedirectStandardOutput "$logDir\web.log" -RedirectStandardError "$logDir\web.err.log"
}
$procs.GetEnumerator() | ForEach-Object { @{ name = $_.Key; pid = $_.Value.Id } } | ConvertTo-Json | Set-Content $pidFile

Step '等待服务就绪'
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline) {
    if ((PortOpen 8000) -and (PortOpen 4320)) { break }
    Start-Sleep -Seconds 1
}
if (-not ((PortOpen 8000) -and (PortOpen 4320))) { Fail "服务没有按时启动，请查看日志：$logDir" }

Write-Host "`n✓ 执笔已启动：http://127.0.0.1:4320" -ForegroundColor Green
Write-Host "  日志在 $logDir；关闭请运行 停止.cmd"
Start-Process 'http://127.0.0.1:4320'
