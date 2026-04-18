#!/usr/bin/env pwsh
#Requires -Version 5.1
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$venvPython = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "First-run setup: creating .venv and installing retrofetch..."
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to create venv. Ensure 'python' (3.10+) is on PATH."
        exit 1
    }
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -e .
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Install failed. See output above."
        exit 1
    }
}

& $venvPython -m retrofetch tui @args
exit $LASTEXITCODE
