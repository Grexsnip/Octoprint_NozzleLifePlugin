# build_dev.ps1
# Build an installable sdist for OctoPrint Plugin Manager upload.

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

$ArtifactsDir = Join-Path $RepoRoot "build_artifacts"
New-Item -ItemType Directory -Force $ArtifactsDir | Out-Null

# Read version from plugin.yaml (authoritative)
$PluginYamlPath = Join-Path $RepoRoot "octoprint_nozzlelifetracker\plugin.yaml"
if (!(Test-Path $PluginYamlPath)) { throw "plugin.yaml not found: $PluginYamlPath" }

$VersionLine = (Get-Content $PluginYamlPath) | Where-Object { $_ -match "^\s*version\s*:" } | Select-Object -First 1
if (!$VersionLine) { throw "Could not find version field in plugin.yaml." }
$Version = ($VersionLine -split ":")[1].Trim()

# Optional: run tests before building (recommended)
.\.venv\Scripts\python.exe -m pytest -q

# Build sdist
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel build
.\.venv\Scripts\python.exe -m build --sdist

# Copy sdist to build_artifacts with clear name
$Sdist = Get-ChildItem -Path (Join-Path $RepoRoot "dist") -Filter "*.tar.gz" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (!$Sdist) { throw "No sdist found in dist/. Build step failed." }

$OutPath = Join-Path $ArtifactsDir ("nozzlelifetracker-dev-v{0}.tar.gz" -f $Version)
Copy-Item -Force $Sdist.FullName $OutPath

Write-Host ""
Write-Host "Created experimental sdist:"
Write-Host "  $OutPath"
Write-Host ""