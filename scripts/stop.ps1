# 执笔 · 停止本机进程（数据库容器保留运行，数据不会丢）
param([switch]$Quiet)
$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root 'data\pids.json'

if (Test-Path $pidFile) {
    foreach ($entry in (Get-Content $pidFile -Raw | ConvertFrom-Json)) {
        # /T 连同子进程一起结束（uv、npm 都会再启动子进程）
        taskkill /PID $entry.pid /T /F *> $null
        if (-not $Quiet) { Write-Host "已停止 $($entry.name)" }
    }
    Remove-Item $pidFile
} elseif (-not $Quiet) {
    Write-Host '没有找到正在运行的执笔进程'
}

if (-not $Quiet) {
    Write-Host '数据库和 Redis 仍在 Docker 中运行；需要时可执行 docker compose stop 关闭。'
}
