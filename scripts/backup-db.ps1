# 数据库自定义格式备份：二进制只在容器和文件间复制，不经过 PowerShell 管道。
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9_-]+$')]
    [string]$Label,
    [ValidatePattern('^[A-Za-z0-9_-]+$')]
    [string]$Database = 'zhibi'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$directory = Join-Path $root 'data\backups'
$filename = '{0}-{1}-{2}.dump' -f $Database, $Label, (Get-Date -Format 'yyyyMMdd-HHmm')
$destination = Join-Path $directory $filename
$containerFile = '/tmp/zhibi-backup.dump'
$failure = $null
$dumpAttempted = $false

Push-Location $root
try {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    # 同一分钟重复运行也不覆盖已经存在的备份。
    if (Test-Path -LiteralPath $destination) { throw "备份文件已存在，不覆盖：$destination" }
    $dumpAttempted = $true
    docker compose exec -T postgres pg_dump -U zhibi -d $Database -Fc -f $containerFile
    if ($LASTEXITCODE -ne 0) { throw "数据库 $Database 导出失败" }
    docker compose cp "postgres:$containerFile" $destination
    if ($LASTEXITCODE -ne 0) { throw '备份文件复制失败' }
    if (!(Test-Path -LiteralPath $destination -PathType Leaf) -or (Get-Item -LiteralPath $destination).Length -eq 0) {
        throw '备份文件不存在或为空'
    }
} catch {
    $failure = $_.Exception.Message
} finally {
    if ($dumpAttempted) {
        docker compose exec -T postgres rm -f $containerFile
        if ($LASTEXITCODE -ne 0 -and !$failure) { $failure = '备份临时文件清理失败' }
    }
    Pop-Location
}
if ($failure) {
    Write-Error $failure -ErrorAction Continue
    exit 1
}
Write-Output $destination
exit 0
