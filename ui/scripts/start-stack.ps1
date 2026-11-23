<#
  Starts the local stack the Fit AI UI needs, on loopback only:
    - OCTAVE in simulation, headless (127.0.0.1:9876)
    - the Fit AI Core (127.0.0.1:8000) with the UI origins allow-listed, so the proxied UI may call POST /api/v1/chat
    - with -WithLlm, the portable Ollama (127.0.0.1:11434)
  It refuses to start if a port is already in use, and records exactly what it started in ui\.stack.json so that
  stop-stack.ps1 stops only that. No global setting is changed (environment variables live only in the child process).

  Usage (from FiT-AI\ui):   powershell -NoProfile -File scripts\start-stack.ps1 [-WithLlm]
                            npm run dev          # then open http://127.0.0.1:5173
                            powershell -NoProfile -File scripts\stop-stack.ps1
#>
param(
  [switch]$WithLlm,
  # also start the UI dev server (http://127.0.0.1:5173); recorded like the rest, so stop-stack.ps1 stops it
  [switch]$WithUi,
  [string]$UiOrigins = 'http://127.0.0.1:5173,http://127.0.0.1:4173'
)
$ErrorActionPreference = 'Stop'

$ui = Split-Path -Parent $PSScriptRoot
$repo = Split-Path -Parent $ui
$rt = Join-Path (Split-Path -Parent $repo) 'runtime'
$state = Join-Path $ui '.stack.json'

if (Test-Path $state) { throw "A stack started by this script is already recorded in $state. Run scripts\stop-stack.ps1 first." }
$ports = @(8000, 9876) + $(if ($WithLlm) { 11434 } else { @() }) + $(if ($WithUi) { 5173 } else { @() })
foreach ($p in $ports) {
  if (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue) { throw "Port $p is already in use; refusing to start (this script only manages what it starts)." }
}

function Wait-Until([scriptblock]$Test, [int]$Seconds, [string]$What) {
  $end = (Get-Date).AddSeconds($Seconds)
  while ((Get-Date) -lt $end) { if (& $Test) { return }; Start-Sleep -Milliseconds 300 }
  throw "Timed out waiting for $What."
}

$octave = Start-Process -FilePath (Join-Path $rt 'octave\OCTAVE.exe') -ArgumentList '--headless', '--sim', '--service', '9876' `
  -WorkingDirectory (Join-Path $rt 'octave') -WindowStyle Hidden -PassThru
$record = [ordered]@{ octave = $octave.Id; core = $null; ui = $null; llm = [bool]$WithLlm; startedAt = (Get-Date).ToString('s') }
$record | ConvertTo-Json | Set-Content -Path $state -Encoding utf8   # recorded first: a failure below is still cleanable
try {
  Wait-Until { Get-NetTCPConnection -LocalPort 9876 -State Listen -ErrorAction SilentlyContinue } 30 'OCTAVE on 9876'

  $env:PYTHONDONTWRITEBYTECODE = '1'
  $env:FIT_AI_CHAT_ALLOWED_ORIGINS = $UiOrigins
  try {
    $core = Start-Process -FilePath (Join-Path $repo '.venv\Scripts\python.exe') -ArgumentList '-B', '-m', 'fit_ai' `
      -WorkingDirectory $repo -WindowStyle Hidden -PassThru
  } finally {
    Remove-Item Env:\FIT_AI_CHAT_ALLOWED_ORIGINS, Env:\PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue
  }
  $record.core = $core.Id
  $record | ConvertTo-Json | Set-Content -Path $state -Encoding utf8
  Wait-Until { try { (Invoke-WebRequest 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch { $false } } 30 'the Fit AI Core'

  if ($WithLlm) {
    # Through Start-Process the helper gets its own hidden console: Ollama then does not inherit THIS script's stdout, which
    # would keep a caller's pipe (or an IDE terminal capturing output) open for as long as Ollama runs. No -Wait: it waits for
    # the whole process tree, and Ollama never exits; readiness is checked on the port just below.
    Start-Process -FilePath 'powershell' -ArgumentList '-NoProfile', '-File', (Join-Path $rt 'tools\ollama-serve.ps1') -WindowStyle Hidden
    Wait-Until { Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue } 30 'Ollama on 11434'
  }

  if ($WithUi) {
    $vite = Start-Process -FilePath (Get-Command node).Source -ArgumentList (Join-Path $ui 'node_modules\vite\bin\vite.js') `
      -WorkingDirectory $ui -WindowStyle Hidden -PassThru
    $record.ui = $vite.Id
    $record | ConvertTo-Json | Set-Content -Path $state -Encoding utf8
    Wait-Until { try { (Invoke-WebRequest 'http://127.0.0.1:5173/' -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch { $false } } 40 'the UI dev server'
  }
} catch {
  Write-Warning "Start-up failed: $($_.Exception.Message). Stopping what was started."
  & (Join-Path $PSScriptRoot 'stop-stack.ps1')
  throw
}

Write-Host ''
Write-Host 'Stack up (loopback only):'
Write-Host '  OCTAVE (simulation)  http://127.0.0.1:9876   (TCP service)'
Write-Host '  Fit AI Core          http://127.0.0.1:8000   (UI origins allow-listed for chat)'
if ($WithLlm) { Write-Host '  Ollama               http://127.0.0.1:11434' } else { Write-Host '  Ollama               not started (use -WithLlm for the chat)' }
if ($WithUi) { Write-Host '  UI (dev server)      http://127.0.0.1:5173' }
Write-Host ''
if (-not $WithUi) { Write-Host 'Next:  npm run dev   -> http://127.0.0.1:5173' }
Write-Host 'Stop:  powershell -NoProfile -File scripts\stop-stack.ps1'
