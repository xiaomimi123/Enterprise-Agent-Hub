# Enterprise Agent Hub - one-command setup for Windows.
# Served by the hub at /api/agent/install.ps1 with __HUB_URL__ filled in. Easiest way for an employee:
#   press Win+R, paste the command below, press Enter (it runs in your own window, outside any agent sandbox):
#   powershell -NoExit -ExecutionPolicy Bypass -c "irm http://<hub>:8088/api/agent/install.ps1 | iex"
# An agent that is not allowed to run "irm | iex" can download this file and run it with:  powershell -ExecutionPolicy Bypass -File <file>
#
# Everything goes into one app root, %USERPROFILE%\HubApps (no admin rights, nothing outside your user folder):
#   runtime\node  portable Node.js LTS (SHA-256 verified) + CodeBuddy CLI installed with it
#   runtime\uv    uv, only when uv is not installed yet
#   apps\  data\  logs\  bin\   company apps, their data, health events, double-click launchers
# Steps: uv -> portable Node.js -> (ask) CodeBuddy CLI -> download the connector -> browser sign-in -> configure your agents
#        -> desktop / Start menu shortcuts for the apps in your role pack.
# Environment variables:
#   HUB_INSTALL_TOOLS=yes   install CodeBuddy CLI without asking      HUB_INSTALL_TOOLS=no   install nothing optional
#   HUB_INSTALL_DRYRUN=1    only print what would be done (stops before sign-in)
#   HUB_HEALTH=off          do not record install problems for the hub's "app health" page
# (ASCII only on purpose: Windows PowerShell 5 may decode piped scripts with the system code page.)
$ErrorActionPreference = 'Stop'
# Never 'exit' below: under 'irm | iex' it would close the whole window and hide the error message. 'return' stops only this script.
$Hub = '__HUB_URL__'
$Dir = if ($env:HUB_AGENT_HOME) { $env:HUB_AGENT_HOME } else { Join-Path $env:USERPROFILE '.hub-agent' }
$Root = if ($env:HUB_APPS_ROOT) { $env:HUB_APPS_ROOT } else { Join-Path $env:USERPROFILE 'HubApps' }
$RtNode = Join-Path $Root 'runtime\node'
$RtUv = Join-Path $Root 'runtime\uv'
$Logs = Join-Path $Root 'logs'
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
    foreach ($p in $RtNode, $RtUv, (Join-Path $env:APPDATA 'npm')) {
        if ((Test-Path $p) -and -not $have.ContainsKey($p.ToLower())) { $have[$p.ToLower()] = 1; [void]$parts.Add($p) }
    }
    $env:Path = ($parts -join ';')
}
function Add-UserPath($PathDir) {
    $cur = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ($null -eq $cur) { $cur = '' }
    if (($cur -split ';') -notcontains $PathDir) {
        [Environment]::SetEnvironmentVariable('Path', (($cur.TrimEnd(';') + ';' + $PathDir).TrimStart(';')), 'User')
    }
}
function Get-DeviceId {
    # Same random device id the connector uses (no hardware information is read).
    $f = Join-Path $Dir 'device-id'
    if (Test-Path $f) { $v = (Get-Content $f -Raw).Trim(); if ($v) { return $v } }
    $v = [guid]::NewGuid().ToString('N')
    New-Item -ItemType Directory -Force $Dir | Out-Null
    [IO.File]::WriteAllText($f, $v)
    return $v
}
function Write-Health($Code, $Message) {
    # Install problems are written locally; the connector sends them to the hub after a successful sign-in (now or next time).
    if ($DryRun -or ($env:HUB_HEALTH -in 'off', '0', 'no')) { return }
    try {
        $msg = ('' + $Message).Replace($env:USERPROFILE, '~')
        if ($msg.Length -gt 300) { $msg = $msg.Substring(0, 300) }
        $v = [Environment]::OSVersion.Version
        $ev = [ordered]@{ at = (Get-Date).ToUniversalTime().ToString('o'); stage = 'install'; ok = $false; code = $Code; message = $msg
            app_id = ''; app_version = ''; device_id = (Get-DeviceId); agent = ''; os = "Windows $($v.Major)"; os_version = $v.ToString()
            arch = ('' + $env:PROCESSOR_ARCHITECTURE).ToLower(); connector_version = 'install.ps1' }
        New-Item -ItemType Directory -Force $Logs | Out-Null
        [IO.File]::AppendAllText((Join-Path $Logs 'health-install.jsonl'), (($ev | ConvertTo-Json -Compress) + "`n"), (New-Object Text.UTF8Encoding $false))
    } catch { }
}
function Install-NodePortable($Dest) {
    # Official portable zip, SHA-256 verified, unpacked into the app root. No admin rights, no winget, no system-wide changes.
    $arch = 'x64'
    if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { $arch = 'arm64' }
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
    New-Item -ItemType Directory -Force $Dest | Out-Null
    Copy-Item (Join-Path $tmp "node-$ver-win-$arch\*") $Dest -Recurse -Force
    Remove-Item $tmp, $zip -Recurse -Force -ErrorAction SilentlyContinue
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

Write-Host "App root: $Root"
# ---- 1. uv (runs the connector). Reuse an existing one; otherwise install it into the app root.
$Uv = $null
foreach ($c in (Join-Path $RtUv 'uv.exe'), (Join-Path $env:USERPROFILE '.local\bin\uv.exe')) { if (-not $Uv -and (Test-Path $c)) { $Uv = $c } }
if (-not $Uv -and (Test-Cmd uv)) { $Uv = (Get-Command uv).Source }
if ($Uv) {
    Write-Host "[1/5] uv is already installed: $Uv"
} else {
    Write-Host '[1/5] Installing uv (Python runner) into the app root...'
    try {
        Invoke-Step "install uv into $RtUv" {
            $env:UV_INSTALL_DIR = $RtUv
            $env:UV_NO_MODIFY_PATH = '1'
            powershell -ExecutionPolicy Bypass -NoProfile -c "irm https://astral.sh/uv/install.ps1 | iex"
            if (-not (Test-Path (Join-Path $RtUv 'uv.exe'))) { throw 'uv.exe was not found after the installer finished.' }
        }
        $Uv = Join-Path $RtUv 'uv.exe'
    } catch {
        Write-Health 'UNKNOWN' "uv install failed: $_"
        Write-Host "      uv could not be installed: $_"
        return
    }
}

# ---- 2. Portable Node.js in the app root (company apps such as the Xiaohongshu workbench run on it).
if (Test-Path (Join-Path $RtNode 'node.exe')) {
    Write-Host "[2/5] Node.js (app root): already there."
} elseif ($env:HUB_INSTALL_TOOLS -eq 'no') {
    Write-Host '[2/5] Node.js: skipped (HUB_INSTALL_TOOLS=no).'
} else {
    Write-Host '[2/5] Installing portable Node.js LTS into the app root (no admin rights needed)...'
    try {
        Invoke-Step "download the official Node.js LTS zip into $RtNode" { Install-NodePortable $RtNode }
    } catch {
        Write-Health 'NODE_MISSING' "portable Node.js install failed: $_"
        Write-Host "      Node.js could not be installed: $_  (company apps will not open until this works; run the command again later)"
    }
}
# HUB_INSTALL_NO_USER_PATH=1 is for tests in a throw-away app root: do not touch the real user PATH.
if (-not $DryRun -and $env:HUB_INSTALL_NO_USER_PATH -ne '1' -and (Test-Path (Join-Path $RtNode 'node.exe'))) { Add-UserPath $RtNode }
Update-SessionPath

# ---- 3. CodeBuddy CLI: only needed for automated browser tasks in the workbench (it runs in the background).
if (Test-Cmd codebuddy) {
    Write-Host '[3/5] CodeBuddy CLI: installed.'
} else {
    Write-Host '[3/5] CodeBuddy CLI: NOT installed (only needed for automated browser tasks in the workbench; skip it if you only use WorkBuddy).'
    $npm = Join-Path $RtNode 'npm.cmd'
    if (-not (Test-Path $npm) -and (Test-Cmd npm.cmd)) { $npm = (Get-Command npm.cmd).Source }
    if ($DryRun -or (Test-Path $npm)) {
        if (Confirm-Install 'CodeBuddy CLI') {
            try {
                # npm.cmd on purpose: with a Restricted execution policy PowerShell refuses to run npm.ps1.
                Invoke-Step "npm install -g --prefix $RtNode @tencent-ai/codebuddy-code" {
                    & $npm install -g --prefix $RtNode '@tencent-ai/codebuddy-code'
                    if ($LASTEXITCODE -ne 0) { throw "npm exited with code $LASTEXITCODE" }
                }
                Update-SessionPath
            } catch {
                Write-Health 'NPM_FAILED' "CodeBuddy CLI install failed: $_"
                Write-Host "      CodeBuddy CLI could not be installed: $_"
            }
        } else {
            Write-Host '      To install it later: run this command again and answer y.'
        }
    } else {
        Write-Host '      Node.js is missing, so CodeBuddy CLI cannot be installed yet.'
    }
}

# ---- 4. The connector.
Write-Host '[4/5] Downloading the hub connector...'
New-Item -ItemType Directory -Force $Dir | Out-Null
try {
    Invoke-WebRequest -UseBasicParsing "$Hub/api/agent/hub_agent.py" -OutFile (Join-Path $Dir 'hub_agent.py')
} catch {
    Write-Health 'NET_UNREACHABLE' "cannot download the connector from $Hub : $_"
    Write-Host "      Cannot reach the hub at $Hub ($_)."
    Write-Host '      Check that this computer is on the same network as the hub: open the address in a browser; you should see the sign-in page.'
    return
}

if ($DryRun) { Write-Host '[5/5] [dry-run] stopping before sign-in.'; return }
# ---- 5. Sign in and configure the agents (the connector also registers the app root with WorkBuddy / CodeBuddy and writes app launchers).
Write-Host '[5/5] Signing in (a browser window will open) and configuring your agents...'
Write-Host '      First sign-in: you will be asked to change the initial password.'
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'
$env:HUB_APPS_ROOT = $Root
& $Uv run (Join-Path $Dir 'hub_agent.py') setup --hub $Hub
$ok = ($LASTEXITCODE -eq 0)

# Desktop / Start menu shortcuts for the apps in your role pack: apps started by double-click keep running when an agent exits.
$launchers = Join-Path $Root 'bin\launchers.json'
if ($ok -and (Test-Path $launchers)) {
    try {
        $items = @(Get-Content $launchers -Raw -Encoding UTF8 | ConvertFrom-Json)
        if ($items.Count -gt 0) {
            $dirs = if ($env:HUB_SHORTCUT_DIR) { @($env:HUB_SHORTCUT_DIR) } else { @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs')) }
            $ws = New-Object -ComObject WScript.Shell
            foreach ($l in $items) {
                foreach ($d in $dirs) {
                    New-Item -ItemType Directory -Force $d | Out-Null
                    $lnk = $ws.CreateShortcut((Join-Path $d ($l.name + '.lnk')))
                    $lnk.TargetPath = $l.path
                    $lnk.WorkingDirectory = $Root
                    $lnk.WindowStyle = 7
                    $lnk.Description = 'Open ' + $l.id + ' (Enterprise Agent Hub)'
                    $lnk.Save()
                }
            }
            Write-Host ''
            Write-Host "Shortcuts created on the desktop and in the Start menu for: $(($items | ForEach-Object { $_.name }) -join ', ')"
            Write-Host '  Open company apps by double-clicking them (not through an agent): they keep running when the agent is closed.'
        }
    } catch {
        Write-Host ''
        Write-Host "Could not create shortcuts ($_). The launchers are in $(Join-Path $Root 'bin'): double-click open-<app>.cmd there."
    }
}
if ($ok -and (Test-Cmd codebuddy)) {
    Write-Host ''
    Write-Host 'CodeBuddy CLI note: for automated browser tasks it needs its own account sign-in, once:'
    Write-Host '  open a terminal, run:  codebuddy   then type  /login  and finish the sign-in in the browser, then /exit.'
}
