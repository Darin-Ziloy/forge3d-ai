$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required.' }
}
& '.\.venv\Scripts\python.exe' -m pip install -e .
if ($LASTEXITCODE -ne 0) { throw 'Python dependencies failed to install.' }
if (-not (Test-Path -LiteralPath 'forge3d\web\vendor\build\three.module.js')) {
    npm.cmd ci --ignore-scripts --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Node.js/npm is required to prepare the viewer.' }
    npm.cmd run vendor
    if ($LASTEXITCODE -ne 0) { throw 'Viewer preparation failed.' }
}
& '.\.venv\Scripts\python.exe' -m forge3d mcp-config | Set-Content -LiteralPath 'mcp-config.json' -Encoding UTF8
Write-Host 'Ready. Run Start-Forge3D.cmd or Start-Demo.cmd.'
