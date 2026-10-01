param(
    [string]$Python = "3.11",
    [ValidateSet("auto", "huggingface", "modelscope")]
    [string]$ModelSource = "modelscope",
    [ValidateSet("pipeline", "vlm", "all")]
    [string]$ModelType = "vlm",
    [switch]$DownloadModels,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$venv = Join-Path $root ".venv"
$pythonExe = Join-Path $venv "Scripts\python.exe"

function Assert-Command {
    param([string]$Name, [string]$InstallHint)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name was not found. $InstallHint"
    }
}

Assert-Command "uv" "Install uv first: https://docs.astral.sh/uv/"
if (-not (Test-Path -LiteralPath (Join-Path $root "tools\calibre-extracted\PFiles64\Calibre2\ebook-convert.exe"))) {
    Assert-Command "ebook-convert" "Install Calibre first: winget install calibre.calibre"
}

$env:MINERU_MODEL_SOURCE = $ModelSource

if ((Test-Path $venv) -and $Force) {
    $backup = Join-Path $root ("work\environment-backups\" + [guid]::NewGuid().ToString())
    New-Item -ItemType Directory -Force -Path (Split-Path $backup -Parent) | Out-Null
    $resolvedVenv = [IO.Path]::GetFullPath($venv)
    if ($resolvedVenv -ne [IO.Path]::GetFullPath((Join-Path $root ".venv"))) { throw "Unexpected environment path: $resolvedVenv" }
    Move-Item -LiteralPath $resolvedVenv -Destination $backup
    Write-Host "Previous environment preserved: $backup"
}

if (-not (Test-Path $venv)) {
    & uv venv $venv --python $Python
    if ($LASTEXITCODE -ne 0) { throw "Python environment creation failed" }
}

& uv pip install --python $pythonExe --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip installation failed" }
& uv pip install --python $pythonExe -U "mineru[all]"
if ($LASTEXITCODE -ne 0) { throw "MinerU installation failed" }
& uv pip install --python $pythonExe -r (Join-Path $root "requirements-toc.txt")
if ($LASTEXITCODE -ne 0) { throw "TOC dependencies installation failed" }

$mineruExe = Join-Path $venv "Scripts\mineru.exe"
if (-not (Test-Path $mineruExe)) {
    throw "MinerU installed but mineru.exe was not found at $mineruExe"
}

$modelsDownloadExe = Join-Path $venv "Scripts\mineru-models-download.exe"
if ($DownloadModels) {
    if (-not (Test-Path $modelsDownloadExe)) {
        throw "MinerU installed but mineru-models-download.exe was not found at $modelsDownloadExe"
    }
    & $modelsDownloadExe -s $ModelSource -m $ModelType
    if ($LASTEXITCODE -ne 0) { throw "MinerU model download failed" }
}

& $mineruExe --help | Select-Object -First 25
if ($LASTEXITCODE -ne 0) { throw "MinerU CLI verification failed" }
Write-Host ""
Write-Host "MinerU setup complete." -ForegroundColor Green
Write-Host "Model source: $ModelSource"
Write-Host "Next: .\scripts\convert-pdfbook.ps1 -InputPath <pdf-or-folder>"
