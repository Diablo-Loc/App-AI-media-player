<#
.SYNOPSIS
    Build the official Windows Inno Setup installer (Installer\BoTube_Setup.exe) and SHA-256 checksum.

.DESCRIPTION
    Reads APP_VERSION directly from app\version.py, optionally invokes build_app.py to compile a fresh
    PyInstaller portable folder, compiles packaging\BoTube_Setup.iss with Inno Setup 6 (ISCC.exe),
    and writes Installer\BoTube_Setup.exe.sha256 for GitHub Releases verification.

.EXAMPLE
    # Build fresh PyInstaller portable bundle first, then package Inno Setup installer:
    .\packaging\build_release_installer.ps1 -BuildPortable

.EXAMPLE
    # Build using the newest dist\release-*\BoTube (or dist\BoTube) folder already built:
    .\packaging\build_release_installer.ps1

.EXAMPLE
    # Build installer from an explicit portable folder:
    .\packaging\build_release_installer.ps1 -SourceDir "D:\HocTap\11_MusicApp\App-AI-media-player\dist\release-20261127-180000-000000\BoTube"
#>
[CmdletBinding()]
param(
    [string]$SourceDir = "",
    [switch]$BuildPortable
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VersionFile = Join-Path $RepoRoot "app\version.py"
$IssFile = Join-Path $RepoRoot "packaging\BoTube_Setup.iss"
$OutDir = Join-Path $RepoRoot "Installer"

# 1. Read canonical APP_VERSION from app/version.py
$VersionContent = Get-Content -Path $VersionFile -Raw -Encoding UTF8
$VersionMatch = [regex]::Match($VersionContent, "APP_VERSION\s*=\s*['""]([^'""]+)['""]")
if (-not $VersionMatch.Success) {
    throw "Could not parse APP_VERSION from $VersionFile"
}
$AppVersion = $VersionMatch.Groups[1].Value
Write-Host "BoTube release version: v$AppVersion" -ForegroundColor Cyan

# 2. Optionally run build_app.py first
if ($BuildPortable) {
    $VenvPython = Join-Path $RepoRoot "venv\Scripts\python.exe"
    $PyExe = if (Test-Path $VenvPython) { $VenvPython } else { "python" }
    Write-Host "Running PyInstaller portable build via build_app.py..." -ForegroundColor Yellow
    & $PyExe (Join-Path $RepoRoot "build_app.py")
    if ($LASTEXITCODE -ne 0) {
        throw "build_app.py failed with exit code $LASTEXITCODE"
    }
}

# 3. Resolve PyInstaller output directory containing BoTube.exe
if (-not $SourceDir) {
    $DistRoot = Join-Path $RepoRoot "dist"
    $Candidates = @()
    if (Test-Path $DistRoot) {
        $Candidates += Get-ChildItem -Path $DistRoot -Directory -Filter "release-*" |
            Sort-Object LastWriteTime -Descending |
            ForEach-Object { Join-Path $_.FullName "BoTube" } |
            Where-Object { Test-Path (Join-Path $_ "BoTube.exe") }
        $DefaultDist = Join-Path $DistRoot "BoTube"
        if (Test-Path (Join-Path $DefaultDist "BoTube.exe")) {
            $Candidates += $DefaultDist
        }
    }
    if ($Candidates.Count -eq 0) {
        throw "No built BoTube.exe found under $DistRoot. Run with -BuildPortable or specify -SourceDir."
    }
    $SourceDir = $Candidates[0]
}
$SourceDir = (Resolve-Path $SourceDir).Path
if (-not (Test-Path (Join-Path $SourceDir "BoTube.exe"))) {
    throw "BoTube.exe not found inside SourceDir: $SourceDir"
}
Write-Host "Packaging SourceDir: $SourceDir" -ForegroundColor Green

# 4. Locate Inno Setup 6 compiler (ISCC.exe)
$IsccCandidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe"
)
$IsccExe = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $IsccExe) {
    $Cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($Cmd) { $IsccExe = $Cmd.Source }
}
if (-not $IsccExe) {
    throw "Inno Setup 6 (ISCC.exe) was not found. Install Inno Setup 6 first."
}

# 5. Compile Inno Setup installer
Write-Host "Compiling $IssFile using $IsccExe..." -ForegroundColor Yellow
& $IsccExe "/DAppVersion=$AppVersion" "/DSourceDir=$SourceDir" $IssFile
if ($LASTEXITCODE -ne 0) {
    throw "ISCC.exe failed with exit code $LASTEXITCODE"
}

$SetupExe = Join-Path $OutDir "BoTube_Setup.exe"
if (-not (Test-Path $SetupExe)) {
    throw "Expected installer was not produced at $SetupExe"
}

# 6. Compute SHA-256 checksum & companion .sha256 file
$Hash = (Get-FileHash -Path $SetupExe -Algorithm SHA256).Hash.ToLowerInvariant()
$ShaFile = "$SetupExe.sha256"
"$Hash  BoTube_Setup.exe" | Set-Content -Path $ShaFile -Encoding ASCII
$SizeMB = [math]::Round((Get-Item $SetupExe).Length / 1MB, 2)

Write-Host ""
Write-Host "BUILD COMPLETE!" -ForegroundColor Green
Write-Host "  Installer : $SetupExe ($SizeMB MB)"
Write-Host "  SHA-256   : $Hash"
Write-Host "  Checksum  : $ShaFile"
Write-Host "  GitHub Tag: v$AppVersion"
