# Start fit-git: creates .venv and installs requirements on first run (or when they change).
#   ./scripts/run.ps1                 # http://127.0.0.1:8000
#   ./scripts/run.ps1 -Port 9000 -Reload
param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$Reload,
    [switch]$Dev  # also install test dependencies
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Creating virtual environment in .venv ..."
    $base = (Get-Command py -ErrorAction SilentlyContinue) ? @("py", "-3") : @("python")
    & $base[0] @($base | Select-Object -Skip 1) -m venv .venv
    if ($LASTEXITCODE) { throw "could not create .venv" }
}

$req = if ($Dev) { "requirements-dev.txt" } else { "requirements.txt" }
$hash = (Get-FileHash requirements.txt).Hash + $(if ($Dev) { (Get-FileHash requirements-dev.txt).Hash } else { "" })
$stamp = Join-Path $root ".venv\.fitgit-requirements"
if (-not (Test-Path $stamp) -or (Get-Content $stamp -Raw).Trim() -ne $hash) {
    Write-Host "Installing $req ..."
    & $python -m pip install --disable-pip-version-check -q -r $req
    if ($LASTEXITCODE) { throw "pip install failed" }
    Set-Content $stamp $hash
}

$appArgs = @("-m", "app", "--host", $BindHost, "--port", $Port)
if ($Reload) { $appArgs += "--reload" }
Write-Host "fit-git on http://${BindHost}:$Port  (Ctrl+C to stop)"
& $python @appArgs
