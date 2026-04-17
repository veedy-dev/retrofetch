param(
    [Parameter(Mandatory = $true)][string]$Wave,
    [Parameter(Mandatory = $true)][string]$Task,
    [Parameter(Mandatory = $true)][string]$Slug
)

$ErrorActionPreference = 'Stop'
$qaDir = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $qaDir '..\..')).Path

if ($Task -eq 'sample') {
    $stem = "wave$Wave-sample-$Slug"
} else {
    $stem = "wave$Wave-task$Task-$Slug"
}

$shFile = Join-Path $qaDir "$stem.sh"
$pyFile = Join-Path $qaDir "$stem.py"
$pyExe = Join-Path $repoRoot '.venv\Scripts\python.exe'

if (Test-Path $pyFile) {
    & $pyExe $pyFile
    exit $LASTEXITCODE
}

if (Test-Path $shFile) {
    Write-Host 'skipped: tmux required'
    exit 77
}

Write-Host "no scenario at $stem.(py|sh)"
exit 1
