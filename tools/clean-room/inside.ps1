# Runs INSIDE Windows Sandbox (a brand-new Windows every time). Started by the .wsb that start.ps1 writes.
# Does what a new employee does: Win+R command -> pre-install check -> install (dry run, stops before sign-in).
# Result goes to C:\out (a folder shared with the host): report.txt and preflight.json. ASCII only.
$ErrorActionPreference = 'Continue'
$cfg = Get-Content C:\clean-room\config.json -Raw | ConvertFrom-Json
New-Item -ItemType Directory -Force C:\out | Out-Null
$log = 'C:\out\report.txt'
function Say($t) { $t | Out-File -FilePath $log -Append -Encoding utf8; Write-Host $t }
Say ("clean-room start " + (Get-Date -Format s) + "  hub=" + $cfg.hub)
Say ("Windows: " + [Environment]::OSVersion.Version + "  PowerShell " + $PSVersionTable.PSVersion)
# network diagnostics: which route from this sandbox reaches the hub?
$hu = [Uri]$cfg.hub
$gw = (Get-NetRoute -DestinationPrefix 0.0.0.0/0 -ErrorAction SilentlyContinue | Select-Object -First 1).NextHop
Say ("sandbox ip: " + ((Get-NetIPAddress -AddressFamily IPv4 | Where-Object IPAddress -notmatch '^127' | ForEach-Object IPAddress) -join ',') + "  gateway: " + $gw)
foreach ($h in @($hu.Host, $gw) | Where-Object { $_ } | Select-Object -Unique) {
    $r = Test-NetConnection -ComputerName $h -Port $hu.Port -WarningAction SilentlyContinue -InformationLevel Quiet
    Say ("tcp " + $h + ":" + $hu.Port + " -> " + $r)
}
# Real install of the base runtime and the connector libraries (no sign-in): HUB_INSTALL_STOP=connector stops right after they are ready.
$env:HUB_INSTALL_STOP = 'connector'
$env:HUB_INSTALL_TOOLS = 'no'
$env:HUB_PREFLIGHT_UPLOAD = 'off'
$root = Join-Path $env:USERPROFILE 'HubApps'
function Run-Install($title) {
    Say ("--- " + $title)
    try {
        $text = (Invoke-WebRequest -UseBasicParsing ($cfg.hub + '/api/agent/install.ps1') -TimeoutSec 30).Content
        Say (& ([scriptblock]::Create($text)) *>&1 | Out-String)
    } catch { Say ("install.ps1 raised: " + $_) }
}
Run-Install 'first run (should download and install the base runtime)'
Run-Install 'second run (should say it is up to date)'
Say '--- what is installed'
$bv = Join-Path $root 'runtime\BASE_VERSION'
if (Test-Path $bv) { Say ("BASE_VERSION " + (Get-Content $bv -Raw).Trim()) } else { Say 'BASE_VERSION missing' }
$node = Join-Path $root 'runtime\node\node.exe'; $uv = Join-Path $root 'runtime\uv\uv.exe'
if (Test-Path $node) { Say ("node " + (& $node -v)) } else { Say 'node missing' }
if (Test-Path $uv) { Say ("uv " + (& $uv --version)) } else { Say 'uv missing' }
$env:UV_PYTHON_INSTALL_DIR = Join-Path $root 'runtime\python'
if (Test-Path $uv) { Say ("python " + (& $uv python find 3.12 2>&1)) }
$wheels = Test-Path (Join-Path $root 'runtime\wheels')
Say ("wheels bundled: " + $wheels)
$cl = ""; if (Test-Path $log) { $cl = Get-Content $log -Raw }
$connOk = ($cl -match "HUB_INSTALL_STOP=connector: stopping") -and ($cl -notmatch "could not be prepared")
Say ("connector libraries ready (from bundled wheels, no PyPI): " + $connOk)
$ok = (Test-Path $bv) -and (Test-Path $node) -and (Test-Path $uv) -and $wheels -and $connOk
Say ("RESULT base-runtime installed=" + $ok)
Copy-Item (Join-Path $env:TEMP 'hub-preflight.json') C:\out\preflight.json -ErrorAction SilentlyContinue
$pf = $global:HubPreflight
if ($pf) { Say ("RESULT preflight fail=" + $pf.Fail + " warn=" + $pf.Warn + " codes=" + ($pf.Codes -join ',')) } else { Say 'RESULT preflight did not run' }
Say 'DONE'
