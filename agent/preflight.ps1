# Enterprise Agent Hub - pre-install check for Windows (read-only: it changes nothing on this computer).
# Served by the hub at /api/agent/preflight.ps1 with the hub address and the Chinese texts filled in. Run it on its own:
#   powershell -NoExit -ExecutionPolicy Bypass -c "irm http://<hub>:8088/api/agent/preflight.ps1 | iex"
# install.ps1 runs it first and stops when something would make the install fail.
# Output: one line per check (PASS / WARN / FAIL), a summary, and a JSON report in %TEMP%.
# FAIL = the install would not work as it is. WARN = it works but something will not (or may not).
# Environment variables:
#   HUB_PREFLIGHT_UPLOAD=off   do not send the (anonymous) result to the hub    HUB_PREFLIGHT_MIN_FREE_MB=1500  free disk space needed
#   HUB_APPS_ROOT              app root to check (default %USERPROFILE%\HubApps)  HUB_PREFLIGHT_CALLBACK_PORT=27891  sign-in callback port
# (ASCII only on purpose: Windows PowerShell 5 may decode piped scripts with the system code page. Chinese text is filled in by the hub.)
param([switch]$Quiet)
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$Hub = '__HUB_URL__'
if ($env:HUB_URL) { $Hub = $env:HUB_URL }
$Hub = $Hub.TrimEnd('/')
$Root = if ($env:HUB_APPS_ROOT) { $env:HUB_APPS_ROOT } else { Join-Path $env:USERPROFILE 'HubApps' }
$MinFreeMb = 1500
if ($env:HUB_PREFLIGHT_MIN_FREE_MB) { $MinFreeMb = [int]$env:HUB_PREFLIGHT_MIN_FREE_MB }
$CallbackPort = 27891
if ($env:HUB_PREFLIGHT_CALLBACK_PORT) { $CallbackPort = [int]$env:HUB_PREFLIGHT_CALLBACK_PORT }

# Chinese labels / fixes, filled in by the hub as an ASCII-escaped JSON object { code: "label | fix" }; stays empty when run from a file.
$Zh = @{}
try {
    $zhText = '__ZH_JSON__'
    if ($zhText.StartsWith('{')) { $o = $zhText | ConvertFrom-Json; foreach ($p in $o.PSObject.Properties) { $Zh[$p.Name] = [string]$p.Value } }
} catch { }

$Results = New-Object System.Collections.ArrayList
function Add-Result($Level, $Code, $Title, $Detail, $Fix) {
    [void]$Results.Add([ordered]@{ level = $Level; code = $Code; title = $Title; detail = ('' + $Detail); fix = ('' + $Fix) })
}
function Pass($Title, $Detail) { Add-Result 'PASS' '' $Title $Detail '' }
function Warn($Code, $Title, $Detail, $Fix) { Add-Result 'WARN' $Code $Title $Detail $Fix }
function Fail($Code, $Title, $Detail, $Fix) { Add-Result 'FAIL' $Code $Title $Detail $Fix }

function Test-TcpPort($HostName, $Port, $TimeoutMs) {
    $c = New-Object Net.Sockets.TcpClient
    try {
        $iar = $c.BeginConnect($HostName, $Port, $null, $null)
        if (-not $iar.AsyncWaitHandle.WaitOne($TimeoutMs)) { return 'timeout' }
        $c.EndConnect($iar)
        return 'ok'
    } catch { return ('' + $_.Exception.InnerException.Message + $_.Exception.Message) } finally { $c.Close() }
}
function Get-Listener($Port) {
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop | Select-Object -First 1
        if ($conn) { return (Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue).ProcessName }
    } catch { }
    return ''
}

# ---- system ----------------------------------------------------------------
$v = [Environment]::OSVersion.Version
$arch = ('' + $env:PROCESSOR_ARCHITECTURE).ToLower()
if ($v.Major -lt 10 -or ($v.Major -eq 10 -and $v.Build -lt 17763)) {
    Fail 'PREFLIGHT_OS_UNSUPPORTED' 'Windows version' "Windows $v" 'Windows 10 1809 (build 17763) or newer is required.'
} elseif (-not [Environment]::Is64BitOperatingSystem) {
    Fail 'PREFLIGHT_OS_UNSUPPORTED' 'Windows architecture' '32-bit Windows' 'A 64-bit Windows is required.'
} else { Pass 'Windows' "$v $arch" }

$mode = '' + $ExecutionContext.SessionState.LanguageMode
if ($mode -ne 'FullLanguage') {
    Fail 'PREFLIGHT_PS_CONSTRAINED' 'PowerShell language mode' $mode 'Security software restricts PowerShell on this computer; ask IT to allow it, or install from another computer.'
} else { Pass 'PowerShell language mode' "FullLanguage (PowerShell $($PSVersionTable.PSVersion))" }

$eff = ''
try { $eff = '' + (Get-ExecutionPolicy) } catch { }
if ($eff -in 'Restricted', 'AllSigned') {
    Warn 'PREFLIGHT_EXEC_POLICY' 'Execution policy' $eff 'Scripts on disk will not run. Use: powershell -ExecutionPolicy Bypass -File <script>.'
} else { Pass 'Execution policy' $eff }

$polluted = @(Get-ChildItem Env: | Where-Object { $_.Name -match '^(WORKBUDDY_|CODEBUDDY_)' } | ForEach-Object { $_.Name })
if ($env:NODE_OPTIONS -match 'workbuddy') { $polluted += 'NODE_OPTIONS' }
if ($polluted.Count -gt 0) {
    Warn 'PREFLIGHT_AGENT_SANDBOX' 'Started from inside an agent' ($polluted[0..([Math]::Min(2, $polluted.Count - 1))] -join ', ') 'Close the agent and run this from your own Win+R window; an agent sandbox can block steps and kill what it starts.'
} else { Pass 'Own terminal (not started by an agent)' '' }

# ---- location and disk -----------------------------------------------------
$rootProblems = @()
if ($Root -match '[^\x00-\x7F]') { $rootProblems += 'non-ASCII characters' }
if ($Root -match '\s') { $rootProblems += 'spaces' }
if ($Root.Length -gt 80) { $rootProblems += 'long path' }
if ($rootProblems.Count -gt 0) {
    Warn 'PREFLIGHT_PATH_UNSAFE' 'App folder path' ($Root + ' (' + ($rootProblems -join ', ') + ')') 'Batch launchers can break. Set HUB_APPS_ROOT to a plain ASCII folder such as C:\HubApps and run again.'
} else { Pass 'App folder path' $Root }

$probe = $Root
while ($probe -and -not (Test-Path -LiteralPath $probe)) { $probe = Split-Path $probe -Parent }
if (-not $probe) { Fail 'PREFLIGHT_NOT_WRITABLE' 'App folder' $Root 'The drive of this folder does not exist.' }
else {
    try {
        $free = [math]::Round((New-Object IO.DriveInfo ($probe.Substring(0, 1))).AvailableFreeSpace / 1MB)
        if ($free -lt $MinFreeMb) { Fail 'PREFLIGHT_DISK_LOW' 'Free disk space' "$free MB free, $MinFreeMb MB needed" 'Free some space or set HUB_APPS_ROOT to another drive.' }
        else { Pass 'Free disk space' "$free MB" }
    } catch { Warn 'PREFLIGHT_DISK_LOW' 'Free disk space' 'could not be read' '' }
    $tmp = Join-Path $probe ('.hub-preflight-' + [guid]::NewGuid().ToString('N'))
    try { [IO.File]::WriteAllText($tmp, 'x'); Remove-Item -LiteralPath $tmp -Force; Pass 'Folder is writable' $probe }
    catch { Fail 'PREFLIGHT_NOT_WRITABLE' 'Folder is writable' ("$probe : " + $_.Exception.Message) 'Controlled-folder access or a permission rule blocks writing here; allow it or set HUB_APPS_ROOT elsewhere.' }
}

# ---- network: hub, sign-in, MCP -------------------------------------------
$cfg = $null
$hubOk = $false
if (-not $Hub -or $Hub.Contains('__HUB' + '_URL__')) {
    Fail 'PREFLIGHT_HUB_UNREACHABLE' 'Hub address' 'not set' 'Run the command from the hub console page (it fills in the address), or set HUB_URL.'
} else {
    try {
        $sw = [Diagnostics.Stopwatch]::StartNew()
        $resp = Invoke-WebRequest -UseBasicParsing -Uri "$Hub/api/agent/config" -TimeoutSec 8
        $sw.Stop()
        $cfg = $resp.Content | ConvertFrom-Json
        $hubOk = $true
        if ($sw.ElapsedMilliseconds -gt 2000) { Warn 'PREFLIGHT_HUB_SLOW' 'Hub response time' "$($sw.ElapsedMilliseconds) ms" 'The network to the hub is slow; downloads may time out.' }
        else { Pass 'Hub reachable' "$Hub ($($sw.ElapsedMilliseconds) ms)" }
        $d = $null
        try { $d = [DateTimeOffset]::Parse(('' + $resp.Headers['Date'])) } catch { }
        if ($d) {
            $skew = [math]::Abs(([DateTimeOffset]::UtcNow - $d).TotalSeconds)
            if ($skew -gt 300) { Warn 'PREFLIGHT_CLOCK_SKEW' 'Computer clock' ("$([math]::Round($skew / 60)) minutes off") 'Sign-in tokens may be rejected; set the date, time and time zone to automatic.' }
            else { Pass 'Computer clock' 'in sync with the hub' }
        }
    } catch {
        Fail 'PREFLIGHT_HUB_UNREACHABLE' 'Hub reachable' ("$Hub : " + $_.Exception.Message) 'Open the hub address in a browser. If it does not load, check the network / VPN; this computer must reach the hub.'
    }
}
if ($hubOk -and $cfg) {
    foreach ($t in @(@('PREFLIGHT_CASDOOR_UNREACHABLE', 'Sign-in service', $cfg.casdoor_url), @('PREFLIGHT_MCP_UNREACHABLE', 'Hub MCP service', $cfg.mcp_url))) {
        $u = $null
        try { $u = [Uri]('' + $t[2]) } catch { }
        if (-not $u) { Warn $t[0] $t[1] 'address not provided by the hub' ''; continue }
        $r = Test-TcpPort $u.Host $u.Port 5000
        if ($r -eq 'ok') { Pass $t[1] ($u.Host + ':' + $u.Port) }
        else { Fail $t[0] $t[1] ($u.Host + ':' + $u.Port + ' ' + $r) 'This port is blocked between this computer and the hub; ask IT to open it (or use the same network as the hub).' }
    }
}

$proxy = $env:HTTPS_PROXY
if (-not $proxy) { $proxy = $env:HTTP_PROXY }
if (-not $proxy) { try { $ie = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -ErrorAction Stop; if ($ie.ProxyEnable -eq 1) { $proxy = '' + $ie.ProxyServer } } catch { } }
if ($proxy -match '(127\.0\.0\.1|localhost):(\d+)') {
    $pr = Test-TcpPort '127.0.0.1' ([int]$Matches[2]) 1500
    if ($pr -ne 'ok') { Warn 'PREFLIGHT_PROXY_DEAD' 'System proxy' ("$proxy is not listening") 'A proxy program that is no longer running is set; turn the system proxy off or start that program.' }
    else { Pass 'System proxy' "$proxy (running)" }
}

# ---- ports -----------------------------------------------------------------
$holder = ''
$listener = $null
try { $listener = New-Object Net.Sockets.TcpListener ([Net.IPAddress]::Loopback), $CallbackPort; $listener.Start(); $listener.Stop() }
catch { $holder = Get-Listener $CallbackPort; if (-not $holder) { $holder = 'unknown program' } }
if ($holder) { Fail 'PREFLIGHT_PORT_CALLBACK' 'Sign-in callback port' ("$CallbackPort is used by $holder") 'Close that program (or restart the computer) and run again; sign-in needs this port.' }
else { Pass 'Sign-in callback port' "$CallbackPort is free" }

# ---- other software (information; never a FAIL) -----------------------------
$edge = @("$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe", "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe") | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if ($edge) { Pass 'Microsoft Edge' $edge } else { Warn 'PREFLIGHT_NO_EDGE' 'Microsoft Edge' 'not found' 'Page collection needs Edge with the WorkBuddy extension; everything else works without it.' }

$wb = @("$env:LOCALAPPDATA\Programs\WorkBuddy", "$env:ProgramFiles\WorkBuddy", "$env:USERPROFILE\.workbuddy") | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if ($wb) { Pass 'WorkBuddy' $wb } else { Pass 'WorkBuddy' 'not found (needed only for page collection)' }
$cb = Get-Command codebuddy -ErrorAction SilentlyContinue
if (-not $cb) { $cbLocal = Join-Path $Root 'runtime\node\codebuddy.cmd'; if (Test-Path -LiteralPath $cbLocal) { $cb = $cbLocal } }
if ($cb) { Pass 'CodeBuddy CLI' 'found (login is checked later by hub-check --deep)' } else { Pass 'CodeBuddy CLI' 'not installed yet (the installer can add it)' }

$days7 = (Get-Date).AddDays(-7)
try {
    $ev = Get-WinEvent -FilterHashtable @{ LogName = 'Microsoft-Windows-Windows Defender/Operational'; Id = 1116, 1117, 1121, 1123; StartTime = $days7 } -MaxEvents 50 -ErrorAction Stop |
        Where-Object { $_.Message -match 'HubApps|node\.exe|codebuddy|uv\.exe' } | Select-Object -First 1
    if ($ev) { Warn 'PREFLIGHT_AV_BLOCK' 'Antivirus' 'Defender blocked or flagged one of our files in the last 7 days' 'Add the app folder to the antivirus exclusions, then run again.' }
    else { Pass 'Antivirus (Defender log)' 'nothing flagged in the last 7 days' }
} catch { Pass 'Antivirus (Defender log)' 'could not be read here (not checked)' }

# ---- result ----------------------------------------------------------------
$fails = @($Results | Where-Object { $_.level -eq 'FAIL' })
$warns = @($Results | Where-Object { $_.level -eq 'WARN' })
if (-not $Quiet) {
    foreach ($r in $Results) {
        if ($r.level -eq 'PASS') { Write-Host ('[PASS] ' + $r.title + $(if ($r.detail) { ' - ' + $r.detail })) -ForegroundColor DarkGray; continue }
        $color = if ($r.level -eq 'FAIL') { 'Red' } else { 'Yellow' }
        Write-Host ('[' + $r.level + '] ' + $r.title + ' - ' + $r.detail + '  (' + $r.code + ')') -ForegroundColor $color
        if ($r.fix) { Write-Host ('       ' + $r.fix) -ForegroundColor $color }
        if ($Zh.ContainsKey($r.code)) { Write-Host ('       ' + $Zh[$r.code]) -ForegroundColor $color }
    }
    Write-Host ''
    if ($fails.Count -gt 0) { Write-Host ("Pre-install check: $($fails.Count) problem(s) must be fixed first, $($warns.Count) warning(s).") -ForegroundColor Red }
    elseif ($warns.Count -gt 0) { Write-Host ("Pre-install check: can install, $($warns.Count) warning(s).") -ForegroundColor Yellow }
    else { Write-Host 'Pre-install check: all good.' -ForegroundColor Green }
}

# ---- report ------------------------------------------------------------------
$deviceId = [guid]::NewGuid().ToString('N')
$devFile = Join-Path (Join-Path $env:USERPROFILE '.hub-agent') 'device-id'
try { if (Test-Path -LiteralPath $devFile) { $x = (Get-Content -LiteralPath $devFile -Raw).Trim(); if ($x) { $deviceId = $x } } } catch { }
$report = [ordered]@{ at = (Get-Date).ToUniversalTime().ToString('o'); device_id = $deviceId; os = "Windows $($v.Major)"; os_version = $v.ToString(); arch = $arch
    summary = [ordered]@{ fail = $fails.Count; warn = $warns.Count }; results = @($Results | Where-Object { $_.level -ne 'PASS' } | ForEach-Object { [ordered]@{ level = $_.level; code = $_.code; message = ($_.title + ': ' + $_.detail) } }) }
$jsonFile = Join-Path $env:TEMP 'hub-preflight.json'
try { [IO.File]::WriteAllText($jsonFile, ($report | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding $false)) } catch { }
# Anonymous, redacted on the hub side (user folder -> ~). Sent only when the hub could be reached at all; a computer that cannot reach it has nothing to send to.
if ($hubOk -and $env:HUB_PREFLIGHT_UPLOAD -notin 'off', '0', 'no' -and $report.results.Count -gt 0) {
    try { Invoke-WebRequest -UseBasicParsing -Uri "$Hub/api/agent/preflight" -Method Post -ContentType 'application/json' -Body ($report | ConvertTo-Json -Depth 5) -TimeoutSec 8 | Out-Null } catch { }
}
if (-not $Quiet -and $report.results.Count -gt 0) { Write-Host "Report: $jsonFile" -ForegroundColor DarkGray }

# Result for install.ps1, which runs this through & [scriptblock]::Create(...) and reads $global:HubPreflight.
$null = $global:HubPreflight = [pscustomobject]@{ Fail = $fails.Count; Warn = $warns.Count; Codes = @($Results | Where-Object { $_.level -ne 'PASS' } | ForEach-Object { $_.code }) }
