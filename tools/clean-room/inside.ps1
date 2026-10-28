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
$env:HUB_INSTALL_DRYRUN = '1'
$env:HUB_INSTALL_TOOLS = 'no'
$env:HUB_PREFLIGHT_UPLOAD = 'off'
try {
    # the same one line an employee pastes into Win+R:  irm <hub>/api/agent/install.ps1 | iex
    $text = (Invoke-WebRequest -UseBasicParsing ($cfg.hub + '/api/agent/install.ps1') -TimeoutSec 30).Content
    $out = & ([scriptblock]::Create($text)) 2>&1 | Out-String
    Say $out
} catch { Say ("install.ps1 raised: " + $_) }
Copy-Item (Join-Path $env:TEMP 'hub-preflight.json') C:\out\preflight.json -ErrorAction SilentlyContinue
$pf = $global:HubPreflight
if ($pf) { Say ("RESULT preflight fail=" + $pf.Fail + " warn=" + $pf.Warn + " codes=" + ($pf.Codes -join ',')) } else { Say 'RESULT preflight did not run' }
Say 'DONE'
