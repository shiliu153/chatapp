<#
.SYNOPSIS
    把生产最新的数据库备份拉回本机(零成本「异地」方案)。

.DESCRIPTION
    生产备份落在服务器自己的磁盘上 —— 与数据库同盘,整机/磁盘挂掉就一起没了。
    在没有对象存储预算的前提下,最便宜的异地就是「每天把最新 dump 拉回自己的电脑」。

    本脚本只做三件事:
      1. 问服务器要最新的 `chatapp-db-*.sql.gz` 与 `chatapp_im` 对应文件;
      2. 连同服务器上生成的 `.sha256` 一起拉回,并用 Get-FileHash 校验;
      3. 本地保留 N 天,超期删除。

    幂等:最新那份已经在本地就直接跳过,不会重复下载。

.PARAMETER Remote
    服务器 SSH 别名或 IP(默认 47.116.114.110,依赖免密登录)。

.PARAMETER LocalDir
    本地保存目录(默认 %USERPROFILE%\chatapp-backups)。

.PARAMETER KeepDays
    本地保留天数(默认 30,比服务器上的 14 天长一点,留出发现故障的窗口)。

.EXAMPLE
    .\pull-backup.ps1
    .\pull-backup.ps1 -LocalDir D:\backups\chatapp -KeepDays 60
#>
[CmdletBinding()]
param(
    [string]$Remote = "47.116.114.110",
    [string]$RemoteDir = "/www/wwwroot/chatapp/backups/db",
    [string]$LocalDir = (Join-Path $env:USERPROFILE "chatapp-backups"),
    [int]$KeepDays = 30
)

$ErrorActionPreference = "Stop"
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

function Write-Log {
    param([string]$Message)
    $line = "$stamp $Message"
    Write-Host $line
    Add-Content -Path (Join-Path $LocalDir "pull-backup.log") -Value $line -Encoding utf8
}

New-Item -ItemType Directory -Force -Path $LocalDir | Out-Null

# 1) 取服务器上最新的两份 dump(按修改时间)
$remoteFiles = & ssh -o BatchMode=yes $Remote "ls -1t $RemoteDir/chatapp-db-*.sql.gz $RemoteDir/chatapp-im-db-*.sql.gz 2>/dev/null | head -2"
if ($LASTEXITCODE -ne 0 -or -not $remoteFiles) {
    Write-Log "失败: 拿不到远端备份清单(ssh 不通或目录为空)"
    exit 1
}

$failed = $false
foreach ($remotePath in @($remoteFiles)) {
    $name = Split-Path $remotePath -Leaf
    $localPath = Join-Path $LocalDir $name
    $localHash = Join-Path $LocalDir "$name.sha256"

    if ((Test-Path $localPath) -and (Test-Path $localHash)) {
        Write-Log "跳过(已存在): $name"
        continue
    }

    Write-Log "拉取: $name"
    & scp -q -o BatchMode=yes "${Remote}:${remotePath}" $localPath
    if ($LASTEXITCODE -ne 0) {
        Write-Log "失败: scp $name"
        $failed = $true
        continue
    }
    & scp -q -o BatchMode=yes "${Remote}:${remotePath}.sha256" $localHash
    if ($LASTEXITCODE -ne 0) {
        Write-Log "失败: scp $name.sha256"
        $failed = $true
        continue
    }

    # 2) 校验:服务器上算的 sha256 与本地实际内容必须一致
    $expected = ((Get-Content -Path $localHash -Raw) -split '\s+')[0].ToLower()
    $actual = (Get-FileHash -Path $localPath -Algorithm SHA256).Hash.ToLower()
    if ($expected -ne $actual) {
        Write-Log "失败: $name 校验和不一致(远端 $expected / 本地 $actual)"
        Remove-Item $localPath, $localHash -Force -ErrorAction SilentlyContinue
        $failed = $true
        continue
    }
    $sizeMb = [math]::Round((Get-Item $localPath).Length / 1MB, 2)
    Write-Log "  ok $name (${sizeMb} MB,sha256 校验通过)"
}

# 3) 本地保留策略
$cutoff = (Get-Date).AddDays(-$KeepDays)
Get-ChildItem -Path $LocalDir -File |
    Where-Object { $_.Name -match '^chatapp-(db|im-db)-.*\.sql\.gz(\.sha256)?$' -and $_.LastWriteTime -lt $cutoff } |
    ForEach-Object {
        Write-Log "清理: $($_.Name)"
        Remove-Item $_.FullName -Force
    }

$total = (Get-ChildItem -Path $LocalDir -File -Filter "*.sql.gz" | Measure-Object -Property Length -Sum).Sum
Write-Log ("完成: 本地共 {0:N1} MB,保留 {1} 天" -f ($total / 1MB), $KeepDays)

if ($failed) { exit 1 }
exit 0
