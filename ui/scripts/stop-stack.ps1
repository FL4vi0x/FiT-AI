<#
  Stops exactly what scripts\start-stack.ps1 recorded in ui\.stack.json (process trees by PID; the portable Ollama only
  if that script started it). Anything else on the machine is left alone.
#>
$ErrorActionPreference = 'Continue'
$ui = Split-Path -Parent $PSScriptRoot
$repo = Split-Path -Parent $ui
$rt = Join-Path (Split-Path -Parent $repo) 'runtime'
$state = Join-Path $ui '.stack.json'

if (-not (Test-Path $state)) { Write-Host 'Nothing recorded: no stack was started by start-stack.ps1.'; return }
$s = Get-Content $state -Raw | ConvertFrom-Json

foreach ($name in 'ui', 'core', 'octave') {
  $procId = $s.$name
  if ($procId) {
    taskkill /PID $procId /T /F 2>$null | Out-Null   # /T: the venv launcher spawns the real python as a child
    Write-Host "stopped $name (PID $procId)"
  }
}
if ($s.llm) { & (Join-Path $rt 'tools\ollama-stop.ps1') }
Remove-Item $state -Force
Start-Sleep -Milliseconds 800

$left = @(8000, 9876, 11434, 5173) | Where-Object { Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue }
if ($left) { Write-Warning "Still listening: $($left -join ', ')" } else { Write-Host 'Ports 5173, 8000, 9876 and 11434 are free.' }
