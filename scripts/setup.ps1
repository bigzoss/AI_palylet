param([string]$Python = '')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
if (-not $Python) {
    $bundled = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (Test-Path -LiteralPath $bundled) { $Python = $bundled } else { $Python = 'python' }
}
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python venv creation failed.' }
}
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.lock
if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
& '.\.venv\Scripts\python.exe' -m pip install -e . --no-deps
if ($LASTEXITCODE -ne 0) { throw 'Backend package installation failed.' }
& npm.cmd --prefix frontend ci
if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
Write-Host 'Dependencies installed. Run: .\scripts\start.ps1'
