# Enterprise Agent Hub - one-command setup for Windows.
# Served by the hub at /api/agent/install.ps1 with __HUB_URL__ filled in. Easiest way for an employee:
#   press Win+R, paste the command below, press Enter (it runs in your own window, outside any agent sandbox):
#   powershell -NoProfile -NoExit -ExecutionPolicy Bypass -c "irm http://<hub>:8088/api/agent/install.ps1 | iex"
# An agent that is not allowed to run "irm | iex" can download this file and run it with:  powershell -ExecutionPolicy Bypass -File <file>
#
# Everything goes into one app root, %USERPROFILE%\HubApps (no admin rights, nothing outside your user folder):
#   runtime\node  portable Node.js LTS (SHA-256 verified) + CodeBuddy CLI installed with it
#   runtime\uv    uv, only when uv is not installed yet
#   apps\  data\  logs\  bin\   company apps, their data, health events, double-click launchers
# Steps: pre-install check -> base runtime from the hub (versioned, falls back to the internet) -> uv -> portable Node.js -> (ask) CodeBuddy CLI -> download the connector -> browser sign-in -> configure your agents
#        -> desktop / Start menu shortcuts for the apps in your role pack.
# Environment variables:
#   HUB_INSTALL_TOOLS=yes   install CodeBuddy CLI without asking      HUB_INSTALL_TOOLS=no   install nothing optional
#   HUB_INSTALL_DRYRUN=1    only print what would be done (stops before sign-in)
#   HUB_HEALTH=off          do not record install problems for the hub's "app health" page
#   HUB_PREFLIGHT=skip      do not run the pre-install check          HUB_BUNDLE=off  do not use the hub's base bundle
#   HUB_INSTALL_BASE_ONLY=1 stop after the base runtime (for tests)   HUB_INSTALL_STOP=connector  stop after the connector libraries are ready (for tests)
# (ASCII only on purpose: Windows PowerShell 5 may decode piped scripts with the system code page.)
$ErrorActionPreference = 'Stop'
# Windows PowerShell 5 draws a progress bar for downloads and Expand-Archive, which makes them many times slower (35 s instead of 5 s here, minutes inside a VM).
$ProgressPreference = 'SilentlyContinue'
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
function Get-HubBundle {
    # Base bundle (fixed Node.js / uv / Python, SHA-256 verified) from the hub. Returns the manifest, or $null to fall back to downloading from the internet.
    if ($env:HUB_BUNDLE -in 'off', '0', 'no' -or $DryRun) { return $null }
    try { return (Invoke-RestMethod -UseBasicParsing -Uri "$Hub/api/agent/bundle/manifest.json" -TimeoutSec 15) } catch { if ($env:HUB_DEBUG) { Write-Host "bundle manifest: $_" }; return $null }
}
function Install-BundleComponent($Name, $C) {
    # Download -> verify -> unpack beside the target -> swap in; the previous copy is kept as <dest>.prev during the swap so a failure rolls back (removed once everything succeeded).
    $dest = Join-Path $Root ($C.dest -replace '/', '\')
    $zip = Join-Path $env:TEMP $C.file
    $tmp = Join-Path $env:TEMP ('bundle-' + $Name + '-' + [guid]::NewGuid().ToString('N'))
    try {
        Write-Host "      Downloading $($C.file) from the hub ($([math]::Round($C.size / 1MB)) MB) ..."
        Invoke-WebRequest -UseBasicParsing "$Hub/api/agent/bundle/files/$($C.file)" -OutFile $zip
        $got = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
        if ($got -ne ('' + $C.sha256).ToLower()) { throw "SHA-256 check failed for $($C.file); nothing was installed." }
        Write-Host "      Unpacking $($C.file) ..."
        Expand-Archive $zip -DestinationPath $tmp -Force
        $src = $tmp
        if ($C.strip) { $src = Join-Path $tmp $C.strip }
        if (-not (Test-Path $src)) { throw "unexpected layout in $($C.file)" }
        New-Item -ItemType Directory -Force (Split-Path $dest -Parent) | Out-Null
        $prev = $dest + '.prev'
        if (Test-Path $prev) { Remove-Item $prev -Recurse -Force }
        $hadOld = Test-Path $dest
        if ($hadOld -and $Name -eq 'node') {
            # Older installs put global npm packages (CodeBuddy CLI and its codebuddy.cmd launchers) inside the Node folder itself.
            # Carry over whatever the new Node does not already have (its own npm / corepack stay), otherwise upgrading would silently remove CodeBuddy CLI.
            foreach ($item in Get-ChildItem $dest -Force) {
                if ($item.Name -eq 'node_modules') {
                    foreach ($m in Get-ChildItem $item.FullName -Force) {
                        $target = Join-Path (Join-Path $src 'node_modules') $m.Name
                        if (-not (Test-Path $target)) { Copy-Item $m.FullName $target -Recurse -Force }
                    }
                } else {
                    $target = Join-Path $src $item.Name
                    if (-not (Test-Path $target)) { Copy-Item $item.FullName $target -Recurse -Force }
                }
            }
        }
        if ($hadOld) {
            # A running node.exe / python.exe from the old folder blocks the move: say so plainly instead of leaving a half-done upgrade.
            try { Move-Item $dest $prev -ErrorAction Stop } catch { throw "the old $($C.dest) is in use (close the company app / agent windows that are running and run the command again): $_" }
        }
        try { Move-Item $src $dest -ErrorAction Stop } catch { if ($hadOld) { Move-Item $prev $dest -ErrorAction SilentlyContinue }; throw }
    } finally {
        Remove-Item $zip, $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
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
# ---- 0. Pre-install check (read-only). Stops here when something would make the install fail; HUB_PREFLIGHT=skip bypasses it.
if ($env:HUB_PREFLIGHT -ne 'skip') {
    Write-Host '[0/5] Checking this computer (changes nothing)...'
    $global:HubPreflight = $null
    try {
        $pf = (Invoke-WebRequest -UseBasicParsing "$Hub/api/agent/preflight.ps1" -TimeoutSec 15).Content
        & ([scriptblock]::Create($pf))
    } catch {
        Write-Health 'NET_UNREACHABLE' "cannot download the pre-install check from $Hub : $_"
        Write-Host "      Cannot reach the hub at $Hub ($_)."
        Write-Host '      Check that this computer is on the same network as the hub: open the address in a browser; you should see the sign-in page.'
        return
    }
    if ($global:HubPreflight -and $global:HubPreflight.Fail -gt 0) {
        Write-Host '      Nothing was installed. Fix the items marked FAIL above and run the command again (HUB_PREFLIGHT=skip ignores this check).'
        return
    }
}
# ---- 0.5 Base bundle from the hub (versioned). Falls back to the old internet downloads below when the hub has none or HUB_BUNDLE=off.
$BaseFile = Join-Path $Root 'runtime\BASE_VERSION'
$bundle = Get-HubBundle
if ($bundle -and $bundle.base) {
    $have = ''
    if (Test-Path $BaseFile) { $have = (Get-Content $BaseFile -Raw).Trim() }
    if ($have -eq $bundle.base) {
        Write-Host "[0/5] Base runtime $have is up to date."
    } else {
        Write-Host "[0/5] Installing base runtime $($bundle.base) from the hub (was: $(if ($have) { $have } else { 'none' }))..."
        $allOk = $true
        foreach ($p in $bundle.components.PSObject.Properties) {
            try { Install-BundleComponent $p.Name $p.Value } catch {
                $allOk = $false
                Write-Health 'BUNDLE_FAILED' "base runtime component $($p.Name) failed: $_"
                Write-Host "      $($p.Name) could not be installed from the hub: $_"
            }
        }
        if ($allOk) {
            New-Item -ItemType Directory -Force (Split-Path $BaseFile -Parent) | Out-Null
            [IO.File]::WriteAllText($BaseFile, $bundle.base)
            # Everything swapped in fine: the .prev copies (hundreds of MB) are no longer needed.
            foreach ($p in $bundle.components.PSObject.Properties) { Remove-Item ((Join-Path $Root ($p.Value.dest -replace '/', '\')) + '.prev') -Recurse -Force -ErrorAction SilentlyContinue }
        } else { Write-Host '      Falling back to downloading the missing pieces from the internet.' }
    }
    $pyDir = Join-Path $Root 'runtime\python'
    if (Test-Path $pyDir) {
        # uv looks for Python here; set for this run and for later uv runs (agents, launchers).
        $env:UV_PYTHON_INSTALL_DIR = $pyDir
        if (-not $DryRun -and $env:HUB_INSTALL_NO_USER_PATH -ne '1') { [Environment]::SetEnvironmentVariable('UV_PYTHON_INSTALL_DIR', $pyDir, 'User') }
    }
}

if ($env:HUB_INSTALL_BASE_ONLY -eq '1') { Write-Host '[0/5] HUB_INSTALL_BASE_ONLY=1: stopping after the base runtime.'; return }

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
                # China mirror first (the default npm registry is often unreachable or very slow there; HUB_NPM_REGISTRY overrides), then the default one.
                $mirror = if ($env:HUB_NPM_REGISTRY) { $env:HUB_NPM_REGISTRY } else { 'https://registry.npmmirror.com' }
                Invoke-Step "npm install -g --prefix $RtNode @tencent-ai/codebuddy-code (registry $mirror)" {
                    & $npm install -g --prefix $RtNode --registry $mirror '@tencent-ai/codebuddy-code'
                    if ($LASTEXITCODE -ne 0) {
                        Write-Host '      The mirror failed; trying the default npm registry...'
                        & $npm install -g --prefix $RtNode '@tencent-ai/codebuddy-code'
                    }
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

# Connector libraries: when the hub's base bundle brought them (runtime\wheels), install from there only. uv needs NO_INDEX as well as FIND_LINKS,
# otherwise it still asks PyPI first. Process-scoped; the first run fills uv's cache, so later runs work even when PyPI is unreachable.
$Wheels = Join-Path $Root 'runtime\wheels'
$wheelEnv = $false
if ((Test-Path $Wheels) -and $env:HUB_BUNDLE -notin 'off', '0', 'no') {
    $env:UV_FIND_LINKS = $Wheels
    $env:UV_NO_INDEX = '1'
    $wheelEnv = $true
}
if (-not $DryRun -and $Uv) {
    Write-Host '      Preparing the connector libraries...'
    $env:PYTHONUTF8 = '1'
    # uv prints progress ("Installed 8 packages") on stderr; with ErrorActionPreference=Stop Windows PowerShell 5 would turn that into an exception.
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $warm = & $Uv run (Join-Path $Dir 'hub_agent.py') --help 2>&1 | Out-String
    $warmCode = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    if ($warmCode -ne 0) {
        Write-Health 'BUNDLE_FAILED' ("connector libraries could not be prepared: " + $warm.Substring(0, [Math]::Min(250, $warm.Length)))
        Write-Host '      The connector libraries could not be prepared:'
        Write-Host $warm
        if ($wheelEnv) { Remove-Item Env:UV_FIND_LINKS, Env:UV_NO_INDEX -ErrorAction SilentlyContinue; $wheelEnv = $false; Write-Host '      Retrying with the internet...' }
    }
}
if ($env:HUB_INSTALL_STOP -eq 'connector') { Write-Host '[4/5] HUB_INSTALL_STOP=connector: stopping after the connector libraries are ready.'; if ($wheelEnv) { Remove-Item Env:UV_FIND_LINKS, Env:UV_NO_INDEX -ErrorAction SilentlyContinue }; return }

if ($DryRun) { Write-Host '[5/5] [dry-run] stopping before sign-in.'; return }
# ---- 5. Sign in and configure the agents (the connector also registers the app root with WorkBuddy / CodeBuddy and writes app launchers).
Write-Host '[5/5] Signing in (a browser window will open) and configuring your agents...'
Write-Host '      First sign-in: you will be asked to change the initial password.'
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'
$env:HUB_APPS_ROOT = $Root
& $Uv run (Join-Path $Dir 'hub_agent.py') setup --hub $Hub
$ok = ($LASTEXITCODE -eq 0)
if ($wheelEnv) { Remove-Item Env:UV_FIND_LINKS, Env:UV_NO_INDEX -ErrorAction SilentlyContinue }
if (-not $ok) {
    # Failures before the connector itself runs (for example uv could not install its dependencies) leave no other trace.
    Write-Health 'UNKNOWN' "connector setup exited with code $LASTEXITCODE (dependency install, sign-in or agent configuration failed; see the messages above)"
    Write-Host ''
    Write-Host "Setup did not finish (exit code $LASTEXITCODE). Read the messages above; run the same command again after fixing the cause."
}

# Desktop / Start menu shortcuts for the apps in your role pack: apps started by double-click keep running when an agent exits.
$launchers = Join-Path $Root 'bin\launchers.json'
if ($ok -and (Test-Path $launchers)) {
    try {
        $items = @(Get-Content $launchers -Raw -Encoding UTF8 | ConvertFrom-Json)
        if ($items.Count -gt 0) {
            $dirs = if ($env:HUB_SHORTCUT_DIR) { @($env:HUB_SHORTCUT_DIR) } else { @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs')) }
            $ws = New-Object -ComObject WScript.Shell
            # App icons come from the hub (best effort): without one a shortcut to a .cmd shows the blank "file" icon.
            $iconDir = Join-Path $Root 'bin\icons'
            New-Item -ItemType Directory -Force $iconDir | Out-Null
            foreach ($l in $items) {
                $icon = Join-Path $iconDir ($l.id + '.ico')
                try { Invoke-WebRequest -UseBasicParsing "$Hub/api/agent/icons/$($l.id).ico" -OutFile $icon -TimeoutSec 15 } catch { Remove-Item $icon -Force -ErrorAction SilentlyContinue }
            }
            foreach ($l in $items) {
                $iconFile = Join-Path $iconDir ($l.id + '.ico')
                foreach ($d in $dirs) {
                    New-Item -ItemType Directory -Force $d | Out-Null
                    $lnk = $ws.CreateShortcut((Join-Path $d ($l.name + '.lnk')))
                    $lnk.TargetPath = $l.path
                    if (Test-Path $iconFile) { $lnk.IconLocation = $iconFile + ',0' }
                    $lnk.WorkingDirectory = $Root
                    $lnk.WindowStyle = 7
                    $lnk.Description = 'Open ' + $l.id + ' (Enterprise Agent Hub)'
                    $lnk.Save()
                    # The connector already put a plain copy of the launcher here (it works without COM); the real shortcut replaces it.
                    $copy = Join-Path $d ($l.name + '.cmd')
                    if ((Test-Path $copy) -and ((Get-FileHash $copy).Hash -eq (Get-FileHash $l.path).Hash)) { Remove-Item $copy -Force }
                }
            }
            Write-Host ''
            Write-Host "Shortcuts created on the desktop and in the Start menu for: $(($items | ForEach-Object { $_.name }) -join ', ')"
            Write-Host '  Open company apps by double-clicking them (not through an agent): they keep running when the agent is closed.'
        }
    } catch {
        # Shortcut (.lnk) creation needs COM, which agent sandboxes block: copy the launchers themselves to the desktop instead.
        $why = $_
        $copied = @()
        try {
            $desk = if ($env:HUB_SHORTCUT_DIR) { $env:HUB_SHORTCUT_DIR } else { [Environment]::GetFolderPath('Desktop') }
            foreach ($l in $items) { Copy-Item $l.path (Join-Path $desk ($l.name + '.cmd')) -Force; $copied += $l.name }
        } catch { }
        Write-Host ''
        if ($copied.Count -gt 0) {
            Write-Host "Shortcuts could not be created here ($why); copied the launchers to the desktop instead: $($copied -join ', ')"
        } else {
            Write-Host "Could not create shortcuts ($why). The launchers are in $(Join-Path $Root 'bin'): double-click open-<app>.cmd there."
        }
    }
}
if ($ok -and (Test-Cmd codebuddy)) {
    Write-Host ''
    Write-Host 'CodeBuddy CLI note: for automated browser tasks it needs its own account sign-in, once:'
    Write-Host '  open a terminal, run:  codebuddy   then type  /login  and finish the sign-in in the browser, then /exit.'
}
