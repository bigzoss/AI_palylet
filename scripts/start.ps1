param([switch]$Production)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
Set-Location -LiteralPath $root
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run scripts/setup.ps1 first.' }
$runtime = Join-Path $root '.runtime'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
$managedMysql = & $python -c "from backend.config import settings; print('true' if settings.mysql_local_managed else 'false')"
if ($LASTEXITCODE -ne 0) { throw 'Could not read backend database configuration.' }
if ($managedMysql -eq 'true') {
    & $python scripts/mysql_local.py start
    if ($LASTEXITCODE -ne 0) { throw 'Local MySQL startup failed.' }
}
foreach ($port in $(if ($Production) { @(18400) } else { @(18400, 5173) })) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $port is already in use. Stop the old service first."
    }
}
if ($Production) {
    & npm.cmd --prefix frontend run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
}
$ownedProcesses = @()
try {
    $ownedProcesses += Start-Process -FilePath $python -ArgumentList @('-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', '18400') -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtime 'api.out.log') -RedirectStandardError (Join-Path $runtime 'api.err.log')
    $ownedProcesses += Start-Process -FilePath $python -ArgumentList @('-m', 'worker.main') -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtime 'worker.out.log') -RedirectStandardError (Join-Path $runtime 'worker.err.log')
    if (-not $Production) {
        $vite = Join-Path $root 'frontend\node_modules\vite\bin\vite.js'
        $node = (Get-Command node.exe).Source
        $ownedProcesses += Start-Process -FilePath $node -ArgumentList @(('"' + $vite + '"'), '--host', '127.0.0.1', '--port', '5173', '--strictPort') -WorkingDirectory (Join-Path $root 'frontend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtime 'frontend.out.log') -RedirectStandardError (Join-Path $runtime 'frontend.err.log')
    }
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 700
        foreach ($process in $ownedProcesses) {
            if ($process.HasExited) { throw 'A service exited. Check .runtime/*.err.log.' }
        }
        try {
            $response = Invoke-RestMethod -Uri 'http://127.0.0.1:18400/api/v1/auth/me' -TimeoutSec 2
            if ($response.username) { $ready = $true; break }
        } catch {
            # An unauthenticated response confirms the authentication API is ready.
            if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 401) {
                $ready = $true
                break
            }
        }
    }
    if (-not $ready) { throw 'Backend health check timed out. Check .runtime logs.' }
    $url = if ($Production) { 'http://127.0.0.1:18400' } else { 'http://127.0.0.1:5173' }
    Write-Host "Framecraft ready: $url"
    Write-Host 'API documentation: http://127.0.0.1:18400/docs'
    Write-Host 'Press Ctrl+C to stop these services.'
    while ($true) {
        Start-Sleep -Seconds 2
        foreach ($process in $ownedProcesses) {
            if ($process.HasExited) { throw 'A service exited. Check .runtime logs.' }
        }
    }
} finally {
    foreach ($process in $ownedProcesses) {
        if (-not $process.HasExited) { Stop-Process -Id $process.Id -ErrorAction SilentlyContinue }
    }
}
