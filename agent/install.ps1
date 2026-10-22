# Enterprise Agent Hub - one-command setup for Windows.
# Served by the hub at /api/agent/install.ps1 with __HUB_URL__ filled in. Usage (PowerShell):
#   powershell -ExecutionPolicy Bypass -c "irm http://<hub>:8088/api/agent/install.ps1 | iex"
# Steps: install uv if missing -> (ask) install Node.js and CodeBuddy CLI if missing -> download the connector
#        -> browser sign-in -> configure WorkBuddy / CodeBuddy CLI / Cursor / Claude Desktop.
# Optional tools are NEVER installed silently. Environment variables:
#   HUB_INSTALL_TOOLS=yes   install Node.js / CodeBuddy CLI without asking
#   HUB_INSTALL_TOOLS=no    never install them (no questions)
#   HUB_INSTALL_DRYRUN=1    only print what would be installed
# When there is no interactive console (for example an agent runs this script), nothing is installed and the commands are printed.
# No winget? Node.js is installed from the official portable zip (SHA-256 verified, no admin rights, user PATH only).
# Easiest way for an employee: press Win+R, paste the command, press Enter (runs outside any agent sandbox).
# (ASCII only on purpose: Windows PowerShell 5 may decode piped scripts with the system code page.)
$ErrorActionPreference = 'Stop'
$Hub = '__HUB_URL__'
$Dir = Join-Path $env:USERPROFILE '.hub-agent'
$Uv = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
$DryRun = ($env:HUB_INSTALL_DRYRUN -eq '1')

function Test-Cmd($Name) { return [bool](Get-Command $Name -ErrorAction SilentlyContinue) }
function Update-SessionPath {
    # Merge, never replace: hosts such as agent sandboxes put their own runtimes on the session PATH, and replacing it hides them.
    $have = @{}
    $parts = New-Object System.Collections.ArrayList
    foreach ($p in ($env:Path -split ';')) { if ($p -and -not $have.ContainsKey($p.ToLower())) { $have[$p.ToLower()] = 1; [void]$parts.Add($p) } }
    foreach ($scope in 'Machine', 'User') {
        foreach ($p in ([Environment]::GetEnvironmentVariable('Path', $scope) -split ';')) {
            if ($p -and -not $have.ContainsKey($p.ToLower())) { $have[$p.ToLower()] = 1; [void]$parts.Add($p) }
        }
    }
    # Places where per-user (no admin) installs end up.
    foreach ($p in (Join-Path $env:APPDATA 'npm'), (Join-Path $env:LOCALAPPDATA 'Programs\nodejs'), (Join-Path $env:LOCALAPPDATA 'nodejs')) {
        if ((Test-Path $p) -and -not $have.ContainsKey($p.ToLower())) { $have[$p.ToLower()] = 1; [void]$parts.Add($p) }
    }
    $env:Path = ($parts -join ';')
}
function Add-UserPath($Dir) {
    $cur = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ($null -eq $cur) { $cur = '' }
    if (($cur -split ';') -notcontains $Dir) {
        [Environment]::SetEnvironmentVariable('Path', (($cur.TrimEnd(';') + ';' + $Dir).TrimStart(';')), 'User')
    }
}
function Install-NodePortable {
    # No admin rights and no winget needed: official portable zip -> %LOCALAPPDATA%\Programs\nodejs, SHA-256 verified, user PATH only.
    $arch = 'x64'
    if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { $arch = 'arm64' }
    $dest = Join-Path $env:LOCALAPPDATA 'Programs\nodejs'
    $index = Invoke-RestMethod -UseBasicParsing 'https://nodejs.org/dist/index.json'
    $ver = ($index | Where-Object { $_.lts } | Select-Object -First 1).version
    if (-not $ver) { throw 'Could not find the latest Node.js LTS version.' }
    $name = "node-$ver-win-$arch.zip"
    $zip = Join-Path $env:TEMP $name
    Write-Host "      Downloading $name ..."
    Invoke-WebRequest -UseBasicParsing "https://nodejs.org/dist/$ver/$name" -OutFile $zip
    $sums = (Invoke-WebRequest -UseBasicParsing "https://nodejs.org/dist/$ver/SHASUMS256.txt").Content
    $line = ($sums -split "`n" | Where-Object { $_ -match [regex]::Escape($name) } | Select-Object -First 1)
    $want = ''
    if ($line) { $want = (($line.Trim() -split '\s+')[0]).ToLower() }
    $got = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
    if (-not $want -or $got -ne $want) { Remove-Item $zip -Force -ErrorAction SilentlyContinue; throw "SHA-256 check failed for $name; nothing was installed." }
    $tmp = Join-Path $env:TEMP ('node-extract-' + [guid]::NewGuid().ToString('N'))
    Expand-Archive $zip -DestinationPath $tmp -Force
    New-Item -ItemType Directory -Force $dest | Out-Null
    Copy-Item (Join-Path $tmp "node-$ver-win-$arch\*") $dest -Recurse -Force
    Remove-Item $tmp, $zip -Recurse -Force -ErrorAction SilentlyContinue
    Add-UserPath $dest
    Update-SessionPath
}
function Confirm-Install($What) {
    if ($env:HUB_INSTALL_TOOLS -eq 'yes') { return $true }
    if ($env:HUB_INSTALL_TOOLS -eq 'no') { return $false }
    $interactive = $true
    try { if ([Console]::IsInputRedirected) { $interactive = $false } } catch { }
    if (-not $interactive) { Write-Host "      (no interactive console: skipped. Set HUB_INSTALL_TOOLS=yes to install automatically)"; return $false }
    $answer = Read-Host "      Install $What now? [y/N]"
    return ($answer -match '^(y|yes)$')
}
function Invoke-Step($Description, [scriptblock]$Action) {
    if ($DryRun) { Write-Host "      [dry-run] would run: $Description"; return }
    Write-Host "      Running: $Description"
    & $Action
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue) -and -not (Test-Path $Uv)) {
    Write-Host '[1/4] Installing uv (Python runner)...'
    powershell -ExecutionPolicy Bypass -NoProfile -c "irm https://astral.sh/uv/install.ps1 | iex"
} else {
    Write-Host '[1/4] uv is already installed.'
}
if (Get-Command uv -ErrorAction SilentlyContinue) { $Uv = (Get-Command uv).Source }

Write-Host '[2/4] Checking optional tools...'
Update-SessionPath
# Node.js: needed to open company apps (for example the Xiaohongshu workbench) and to install CodeBuddy CLI.
if (Test-Cmd node) {
    Write-Host '      Node.js: installed.'
} else {
    Write-Host '      Node.js: NOT installed (needed to open company apps such as the Xiaohongshu workbench).'
    if (Confirm-Install 'Node.js LTS') {
        if (Test-Cmd winget) {
            Invoke-Step 'winget install -e --id OpenJS.NodeJS.LTS' { winget install -e --id OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements }
            Update-SessionPath
        } else {
            Write-Host '      winget is not available: using the official portable Node.js (no admin rights needed, installed for your user only).'
            Invoke-Step 'download and unpack the official portable Node.js LTS' { Install-NodePortable }
        }
        if (-not $DryRun -and -not (Test-Cmd node)) { Write-Host '      Node.js was installed but is not on PATH yet. Reopen the terminal and run this command again.' }
    } else {
        Write-Host '      To install it yourself:  winget install -e --id OpenJS.NodeJS.LTS   (or download the Windows zip from https://nodejs.org)'
    }
}
# CodeBuddy CLI: only needed for automated browser tasks in the workbench (the workbench runs it in the background).
if (Test-Cmd codebuddy) {
    Write-Host '      CodeBuddy CLI: installed.'
} else {
    Write-Host '      CodeBuddy CLI: NOT installed (only needed for automated browser tasks in the workbench; skip it if you only use WorkBuddy).'
    if (Test-Cmd npm.cmd) {
        if (Confirm-Install 'CodeBuddy CLI') {
            # npm.cmd on purpose: with a Restricted execution policy PowerShell refuses to run npm.ps1.
            Invoke-Step 'npm install -g @tencent-ai/codebuddy-code' { & npm.cmd install -g '@tencent-ai/codebuddy-code' }
            Update-SessionPath
            if (-not $DryRun -and -not (Test-Cmd codebuddy)) { Write-Host '      CodeBuddy CLI was installed but is not on PATH yet. Reopen the terminal and run this command again.' }
        } else {
            Write-Host '      To install it yourself:  npm install -g @tencent-ai/codebuddy-code'
        }
    } else {
        Write-Host '      Install Node.js first, then:  npm install -g @tencent-ai/codebuddy-code'
    }
}

Write-Host '[3/4] Downloading the hub connector...'
New-Item -ItemType Directory -Force $Dir | Out-Null
Invoke-WebRequest -UseBasicParsing "$Hub/api/agent/hub_agent.py" -OutFile (Join-Path $Dir 'hub_agent.py')

if ($DryRun) { Write-Host '[4/4] [dry-run] stopping before sign-in.'; exit 0 }
Write-Host '[4/4] Signing in (a browser window will open) and configuring your agents...'
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'
& $Uv run (Join-Path $Dir 'hub_agent.py') setup --hub $Hub
if ($LASTEXITCODE -eq 0 -and (Test-Cmd codebuddy)) {
    Write-Host ''
    Write-Host 'CodeBuddy CLI note: for automated browser tasks it needs its own account sign-in, once:'
    Write-Host '  open a terminal, run:  codebuddy   then type  /login  and finish the sign-in in the browser, then /exit.'
}
