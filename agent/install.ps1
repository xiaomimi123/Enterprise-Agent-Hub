# Enterprise Agent Hub - one-command setup for Windows.
# Served by the hub at /api/agent/install.ps1 with __HUB_URL__ filled in. Usage (PowerShell):
#   powershell -ExecutionPolicy Bypass -c "irm http://<hub>:8088/api/agent/install.ps1 | iex"
# Steps: install uv if missing -> download the connector -> browser sign-in -> configure WorkBuddy / Cursor / Claude Desktop.
# (ASCII only on purpose: Windows PowerShell 5 may decode piped scripts with the system code page.)
$ErrorActionPreference = 'Stop'
$Hub = '__HUB_URL__'
$Dir = Join-Path $env:USERPROFILE '.hub-agent'
$Uv = Join-Path $env:USERPROFILE '.local\bin\uv.exe'

if (-not (Get-Command uv -ErrorAction SilentlyContinue) -and -not (Test-Path $Uv)) {
    Write-Host '[1/3] Installing uv (Python runner)...'
    powershell -ExecutionPolicy Bypass -NoProfile -c "irm https://astral.sh/uv/install.ps1 | iex"
} else {
    Write-Host '[1/3] uv is already installed.'
}
if (Get-Command uv -ErrorAction SilentlyContinue) { $Uv = (Get-Command uv).Source }

Write-Host '[2/3] Downloading the hub connector...'
New-Item -ItemType Directory -Force $Dir | Out-Null
Invoke-WebRequest -UseBasicParsing "$Hub/api/agent/hub_agent.py" -OutFile (Join-Path $Dir 'hub_agent.py')

Write-Host '[3/3] Signing in (a browser window will open) and configuring your agents...'
$env:PYTHONUTF8 = '1'
& $Uv run (Join-Path $Dir 'hub_agent.py') setup --hub $Hub
