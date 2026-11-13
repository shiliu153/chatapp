#Requires -Version 5.1
<#
.SYNOPSIS
    派发工单前的守门:确认 WSL 与 superagent 在跑,没跑就拉起来。

.DESCRIPTION
    派工单的动作是「在 issue 里评论 @shiliu655」,而读评论的 superagent 跑在 WSL 里。
    WSL 没起来时那条评论**不会有人读**,单子看起来派了、实际在空转 —— 和
    docs/ops/superagent.md §4.1「入队三连」里记的「静默丢单」长得一模一样。
    所以派单前先跑这个。

    做四件事:
      1. 探测 WSL(短超时)。冷状态就显式拉起并等它起来。
      2. 调 WSL 里的 /root/ensure-superagent.sh:没跑就 start,并等到十个健康位 ready。
      3. **探测 WSL 直连出网**(2026-11-13 加):宿主连得通、WSL 连不通时 worker 会全断,
         但所有健康位都显示 ready —— 不查这一项就会「派了单、永远不动」。
      4. 报告周边依赖(出口代理 / 模型兜底 / docker),缺了只警告不拦。

.PARAMETER TimeoutSeconds
    拉起 WSL + 等 superagent 可接单的总上限,默认 360 秒。
    冷启动实测:WSL 起来约 10s,DSH 初始化 + 首轮轮询起步约 60~90s。
    注意这个超时**不覆盖 github 首轮**(那要 ~20 分钟,见 §12.6),脚本只等
    「除 github 外全部 ready」—— 首轮期间派单不会丢,只是核回执要等。

.PARAMETER Distro
    WSL 发行版名,默认 Ubuntu-24.04。

.EXAMPLE
    pwsh -File scripts\superagent-start\ensure-running.ps1

    **必须用 `pwsh`(PowerShell 7),不要用 `powershell`(Windows PowerShell 5.1)**:
    本文件是 UTF-8 **无 BOM**,正文含中文,5.1 会按 ANSI 解码 → 整片 ParserError
    (2026-11-11 实测;同文件 `pwsh -File` 正常)。

.NOTES
    退出码:0 = 可以派单;1 = 拉不起来或出网不通,别派。
#>
[CmdletBinding()]
param(
    [int]$TimeoutSeconds = 360,
    [string]$Distro = 'Ubuntu-24.04'
)

$ErrorActionPreference = 'Stop'

# wsl.exe 自己的消息是 UTF-16,bash 的输出是 UTF-8。统一按 UTF-8 读,
# 代价是 wsl.exe 的告警行(如 localhost 转发提示)会显示成乱码 —— 无害,过滤掉即可。
$OutputEncoding = [System.Text.Encoding]::UTF8

function Invoke-Wsl {
    <#
    .SYNOPSIS
        跑一次 wsl.exe,带硬超时,返回 { Ok, ExitCode, Out, Err }。
    .DESCRIPTION
        不用 Start-Process -Wait(没有超时),也不用管道(会挂住)。
        WSL 冷启动时进程可能几分钟才回,必须有硬超时,否则脚本自己卡死。
    #>
    param(
        [Parameter(Mandatory)][string[]]$WslArgs,
        [int]$TimeoutMs = 60000
    )
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'wsl.exe'
    $psi.Arguments = ($WslArgs -join ' ')
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8

    $p = [System.Diagnostics.Process]::Start($psi)
    $outTask = $p.StandardOutput.ReadToEndAsync()
    $errTask = $p.StandardError.ReadToEndAsync()
    if (-not $p.WaitForExit($TimeoutMs)) {
        try { $p.Kill() } catch { }
        return @{ Ok = $false; ExitCode = -1; Out = ''; Err = "超时(${TimeoutMs}ms)" }
    }
    # 进程已退出,读流不会阻塞;给 5s 兜底。
    $null = $outTask.Wait(5000)
    $null = $errTask.Wait(5000)
    return @{
        Ok       = ($p.ExitCode -eq 0)
        ExitCode = $p.ExitCode
        Out      = $outTask.Result
        Err      = $errTask.Result
    }
}

function Show-WslOutput {
    <#
    .SYNOPSIS
        打印 wsl 的输出,过滤掉 wsl.exe 自己那几行会乱码的告警。
    .DESCRIPTION
        wsl.exe 的告警是 UTF-16,按 UTF-8 读会变成「w s l :  …」这种每个字符
        中间夹空格的样子,所以不能用 'localhost' 这种正常正则去匹配 —— 要按
        字符间带空白的形态匹配。
    #>
    param([hashtable]$Result)
    foreach ($line in ($Result.Out -split "`r?`n")) {
        if ($line.Trim()) { Write-Host "  $line" }
    }
    foreach ($line in ($Result.Err -split "`r?`n")) {
        if (-not $line.Trim()) { continue }
        # 乱码后的 wsl.exe 告警:w s l : ... / N A T ... / l o c a l h o s t
        if ($line -match '^\s*w\s*s\s*l\s*:') { continue }
        if ($line -match 'l\s*o\s*c\s*a\s*l\s*h\s*o\s*s\s*t') { continue }
        Write-Host "  $line" -ForegroundColor DarkYellow
    }
}

Write-Host "[gate] 检查 WSL($Distro)…" -ForegroundColor Cyan

# ---------- 1. 探测:已启动的话秒回 ----------
$probe = Invoke-Wsl -WslArgs @('-d', $Distro, '-e', '/bin/true') -TimeoutMs 10000

if ($probe.Ok) {
    Write-Host "[gate] WSL 已在运行" -ForegroundColor Green
} else {
    Write-Host "[gate] WSL 未运行($($probe.Err.Trim())),拉起中 —— 冷启动可能要几十秒…" -ForegroundColor Yellow
    $boot = Invoke-Wsl -WslArgs @('-d', $Distro, '-e', '/bin/true') -TimeoutMs ($TimeoutSeconds * 1000)
    if (-not $boot.Ok) {
        Write-Host "[gate] 失败:WSL 拉不起来($($boot.Err.Trim()))" -ForegroundColor Red
        Write-Host "       手动试:wsl -d $Distro -e /bin/true" -ForegroundColor Red
        exit 1
    }
    Write-Host "[gate] WSL 已拉起" -ForegroundColor Green
}

# ---------- 2. 确保 superagent ----------
Write-Host "[gate] 确保 superagent 在跑…" -ForegroundColor Cyan
$run = Invoke-Wsl -WslArgs @('-d', $Distro, '-e', 'bash', '/root/ensure-superagent.sh') -TimeoutMs ($TimeoutSeconds * 1000)
Show-WslOutput -Result $run

if (-not $run.Ok) {
    Write-Host "[gate] 不能派单:superagent 没就绪(退出码 $($run.ExitCode))" -ForegroundColor Red
    Write-Host "       面板:http://127.0.0.1:3082" -ForegroundColor Red
    exit 1
}

Write-Host "[gate] 可以派单" -ForegroundColor Green

# ---------- 3. WSL 出网:2026-11-13 的血案 ----------
# 宿主机装了 Sangfor aTrust 之后,WSL 的**直连 TCP 被整体拦掉**(UDP DNS 仍通),于是
# mihomo 连不上任何机场节点、模型网关 443 也不可达;worker 的 git / 轮询 / 模型调用全断,
# 而面板上每个健康位都是 ready。判据就在这一层:宿主通、WSL 不通。
# 这里直接调 curl(不经过 shell),避免 wsl.exe 参数拼接时的引号问题。
Write-Host "[gate] 检查 WSL 出网…" -ForegroundColor Cyan
$probeArgs = @('-o', '/dev/null', '-w', '%{http_code}', '-m', '8', 'https://api.github.com/')
$direct = Invoke-Wsl -WslArgs (@('-d', $Distro, '-e', 'curl', '-sS') + $probeArgs) -TimeoutMs 20000
$proxy = Invoke-Wsl -WslArgs (@('-d', $Distro, '-e', 'curl', '-sS', '-x', 'http://127.0.0.1:7890') + $probeArgs) -TimeoutMs 20000

function Test-HttpOk {
    <#
    .SYNOPSIS
        从 curl -w '%{http_code}' 的输出里判断是否 2xx。
    .DESCRIPTION
        失败时 curl 会把 000 打出来或什么都不打,两种都当失败。
    #>
    param([hashtable]$Result)
    $code = ($Result.Out -replace '\s', '')
    if ($code -match '^\d{3}$') {
        $value = [int]$code
        return ($value -ge 200 -and $value -lt 300)
    }
    return $false
}

$directOk = Test-HttpOk -Result $direct
$proxyOk = Test-HttpOk -Result $proxy

if ($proxyOk -and $directOk) {
    Write-Host "[gate] 出网正常(直连 + 代理 127.0.0.1:7890 都通)" -ForegroundColor Green
} elseif ($proxyOk) {
    Write-Host "[gate] 警告:WSL 直连不通,但代理通(worker 走代理,可以先干活)" -ForegroundColor Yellow
    Write-Host "       若是 VPN 引起的,按 docs/ops/superagent.md §12.0 把 WSL 切到 networkingMode=mirrored" -ForegroundColor Yellow
} else {
    Write-Host "[gate] 不能派单:WSL 出网不通(直连 $($direct.Out -replace '\s',''),代理 $($proxy.Out -replace '\s',''))" -ForegroundColor Red
    Write-Host "       这会让 worker 收不到单、模型调用全超时,而面板上所有健康位仍是 ready。" -ForegroundColor Red
    Write-Host "       最常见原因:Sangfor aTrust 等企业 VPN 拦掉 WSL 的直连 TCP(UDP DNS 仍通)。" -ForegroundColor Red
    Write-Host "       修法:C:\Users\<你>\.wslconfig 加 [wsl2] networkingMode=mirrored + dnsTunneling=true," -ForegroundColor Red
    Write-Host "             然后 wsl --shutdown;详见 docs/ops/superagent.md §12.0。" -ForegroundColor Red
    Write-Host "       另一个常见原因:mihomo 端口在听但出网 0%(机场节点全挂,见 #284)。" -ForegroundColor Red
    exit 1
}

exit 0
