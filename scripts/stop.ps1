# 执笔 · 停止本机进程（数据库容器保留运行，数据不会丢）
param([switch]$Quiet, [switch]$Isolated, [string]$DataDirectory)
$root = Split-Path -Parent $PSScriptRoot
$defaultData = [IO.Path]::GetFullPath((Join-Path $root 'data'))
if ($Isolated -and (-not $DataDirectory -or -not [IO.Path]::IsPathRooted($DataDirectory) -or
    [IO.Path]::GetFullPath($DataDirectory).TrimEnd('\') -eq $defaultData.TrimEnd('\'))) {
    throw '独立停止需要独立 data 绝对路径，不能读取日常 PID'
}
if (-not $DataDirectory) { $DataDirectory = $defaultData }
$pidFile = Join-Path $DataDirectory 'pids.json'

if (Test-Path $pidFile) {
    foreach ($entry in (Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json)) {
        # 包括 teardown 与 teardown2；只停止这次启动登记的独立进程树。
        # /T 连同子进程一起结束（uv、npm 都会再启动子进程）
        taskkill /PID $entry.pid /T /F *> $null
        if (-not $Quiet) { Write-Host "已停止 $($entry.name)" }
    }
    Remove-Item -LiteralPath $pidFile
} elseif (-not $Quiet) {
    Write-Host '没有找到正在运行的执笔进程'
}

if (-not $Quiet) {
    Write-Host '数据库和 Redis 仍在 Docker 中运行；需要时可执行 docker compose stop 关闭。'
}
