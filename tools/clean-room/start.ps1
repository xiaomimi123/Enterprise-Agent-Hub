# Starts a clean Windows Sandbox, runs the install flow in it and prints the result.
#   powershell -ExecutionPolicy Bypass -File tools\clean-room\start.ps1 -Hub http://192.168.0.41:8088
# Needs Windows 10/11 Pro with the "Windows Sandbox" feature on (Turn Windows features on or off -> Windows Sandbox, then reboot)
# and virtualization enabled in the BIOS. The sandbox must be able to reach the hub (default networking can reach the LAN).
param([Parameter(Mandatory)][string]$Hub, [int]$TimeoutMin = 15)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path "$env:windir\System32\WindowsSandbox.exe")) { throw 'Windows Sandbox is not installed. Turn it on in "Turn Windows features on or off", reboot, and run again.' }
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$work = Join-Path $env:TEMP ('clean-room-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
$in = Join-Path $work 'in'; $out = Join-Path $work 'out'
New-Item -ItemType Directory -Force $in, $out | Out-Null
Copy-Item (Join-Path $here 'inside.ps1') $in
[IO.File]::WriteAllText((Join-Path $in 'config.json'), (@{ hub = $Hub.TrimEnd('/') } | ConvertTo-Json))
$wsb = @"
<Configuration>
  <VGpu>Disable</VGpu>
  <Networking>Default</Networking>
  <MappedFolders>
    <MappedFolder><HostFolder>$in</HostFolder><SandboxFolder>C:\clean-room</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder>
    <MappedFolder><HostFolder>$out</HostFolder><SandboxFolder>C:\out</SandboxFolder><ReadOnly>false</ReadOnly></MappedFolder>
  </MappedFolders>
  <LogonCommand><Command>powershell.exe -ExecutionPolicy Bypass -File C:\clean-room\inside.ps1</Command></LogonCommand>
</Configuration>
"@
$wsbFile = Join-Path $work 'clean-room.wsb'
[IO.File]::WriteAllText($wsbFile, $wsb)
Write-Host "Starting Windows Sandbox (a new window opens)... results: $out"
Start-Process $wsbFile
$report = Join-Path $out 'report.txt'
$deadline = (Get-Date).AddMinutes($TimeoutMin)
while ((Get-Date) -lt $deadline) {
    if ((Test-Path $report) -and ((Get-Content $report -Raw) -match 'DONE')) { break }
    Start-Sleep 3
}
if (Test-Path $report) { Get-Content $report } else { Write-Host 'No report appeared (the sandbox did not start or could not run the script).' }
Write-Host "Close the sandbox window when you are done. Files: $work"
if ((Test-Path $report) -and ((Get-Content $report -Raw) -match 'RESULT preflight fail=0')) { exit 0 } else { exit 1 }
