param(
    [switch]$SkipDependencyInstall,
    [switch]$SkipInstaller,
    [switch]$InstallTools
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Missing .venv. Run: python -m venv .venv"
}

Push-Location $Root
try {
    if (-not $SkipDependencyInstall) {
        & $Python -m pip install -e ".[build]"
        if ($LASTEXITCODE -ne 0) { throw "Build dependency installation failed." }
    }

    & $Python -m PyInstaller --clean --noconfirm "packaging\retrofetch.spec"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

    $PortableExe = Join-Path $Root "dist\Retrofetch.exe"
    if (-not (Test-Path -LiteralPath $PortableExe)) {
        throw "Portable executable was not created."
    }
    $ArchiveViewer = Join-Path $Root ".venv\Scripts\pyi-archive_viewer.exe"
    $ArchiveListing = (& $ArchiveViewer -l $PortableExe | Out-String)
    if ($LASTEXITCODE -ne 0 -or $ArchiveListing -notmatch 'selectolax[\\/].*parser') {
        throw "Portable executable is missing the selectolax parser."
    }
    $Version = (& $PortableExe --version).Trim()
    if ($LASTEXITCODE -ne 0 -or $Version -notmatch '^retrofetch \d+\.\d+\.\d+$') {
        throw "Portable executable smoke test failed: $Version"
    }

    $SmokeDir = Join-Path ([IO.Path]::GetTempPath()) ("retrofetch-smoke-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $SmokeDir | Out-Null
    try {
        Push-Location $SmokeDir
        try {
            & $PortableExe init
            if ($LASTEXITCODE -ne 0) { throw "Portable executable resource smoke test failed." }
            foreach ($Name in @("config.yml", "overrides.yml", ".env.example", "consoles.yml")) {
                if (-not (Test-Path -LiteralPath (Join-Path $SmokeDir $Name))) {
                    throw "Portable executable did not create $Name."
                }
            }
        }
        finally {
            Pop-Location
        }
    }
    finally {
        Remove-Item -LiteralPath $SmokeDir -Recurse -Force
    }

    if ($SkipInstaller) {
        Write-Host "Built $PortableExe"
        return
    }

    [string[]]$IsccCandidates = @(
        (Get-Command iscc.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

    if (-not $IsccCandidates -and $InstallTools) {
        & winget install --id JRSoftware.InnoSetup --exact --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup installation failed." }
        [string[]]$IsccCandidates = @(
            (Get-Command iscc.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
            "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
        ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    }
    if (-not $IsccCandidates) {
        throw "Inno Setup 6 was not found. Re-run with -InstallTools or install JRSoftware.InnoSetup."
    }

    $AppVersion = $Version.Split(' ')[1]
    & $IsccCandidates[0] "/DMyAppVersion=$AppVersion" "packaging\retrofetch.iss"
    if ($LASTEXITCODE -ne 0) { throw "Installer build failed." }

    $Installer = Join-Path $Root "dist\RetrofetchSetup.exe"
    if (-not (Test-Path -LiteralPath $Installer)) {
        throw "Installer executable was not created."
    }
    Write-Host "Built $PortableExe"
    Write-Host "Built $Installer"
}
finally {
    Pop-Location
}
