param(
    [Parameter(Mandatory = $true)]
    [string]$InputPath,

    [string]$OutputDir = "",

    [ValidateSet("epub", "azw3", "both")]
    [string]$Format = "epub",

    [string]$Title = "",
    [string]$Author = "",

    [ValidateSet("auto", "txt", "ocr")]
    [string]$Method = "auto",

    [ValidateSet("vlm-engine", "hybrid-engine", "pipeline")]
    [string]$Backend = "vlm-engine",

    [string]$Lang = "ch",
    [ValidateSet("modelscope", "huggingface", "local")]
    [string]$ModelSource = "modelscope",

    [switch]$SkipMinerU,
    [switch]$KeepWork
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$tool = Join-Path $root "tools\mineru_content_to_markdown.py"
$htmlTool = Join-Path $root "tools\markdown_to_simple_html.py"
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$mineruExe = Join-Path $root ".venv\Scripts\mineru.exe"
$artifactTool = Join-Path $root "tools\ebook_artifacts.py"
$provenanceTool = Join-Path $root "tools\conversion_provenance.py"
$calibre = Get-Command "ebook-convert" -ErrorAction SilentlyContinue
$ebookConvert = if ($calibre) { $calibre.Source } else { Join-Path $root "tools\calibre-extracted\PFiles64\Calibre2\ebook-convert.exe" }

if ($OutputDir -eq "") {
    $OutputDir = Join-Path $root "output"
}

if (-not (Test-Path $tool)) {
    throw "Missing converter: $tool"
}
if (-not (Test-Path $htmlTool)) {
    throw "Missing HTML fallback converter: $htmlTool"
}
if (-not (Test-Path $venvPython)) {
    throw "Missing local Python environment. Run .\scripts\setup-mineru.ps1 first."
}
if (-not $SkipMinerU -and -not (Test-Path $mineruExe)) {
    throw "Missing MinerU CLI. Run .\scripts\setup-mineru.ps1 first."
}
if (-not (Test-Path -LiteralPath $ebookConvert)) {
    throw "Calibre ebook-convert was not found. Install Calibre first."
}

function Ensure-CudaPathForLmdeploy {
    param(
        [string]$ProjectRoot,
        [string]$ProjectWorkRoot
    )

    if ($env:CUDA_PATH) {
        $cudaBin = Join-Path $env:CUDA_PATH "bin"
        if (Test-Path -LiteralPath $cudaBin) {
            return
        }
    }

    $torchLib = Join-Path $ProjectRoot ".venv\Lib\site-packages\torch\lib"
    $torchCudart = Join-Path $torchLib "cudart64_12.dll"
    if (-not (Test-Path -LiteralPath $torchCudart)) {
        return
    }

    $shimRoot = Join-Path $ProjectWorkRoot "cuda-shim"
    $shimBin = Join-Path $shimRoot "bin"
    New-Item -ItemType Directory -Force -Path $shimRoot | Out-Null
    if (-not (Test-Path -LiteralPath $shimBin)) {
        New-Item -ItemType Junction -Path $shimBin -Target $torchLib | Out-Null
    }

    $env:CUDA_PATH = $shimRoot
    Write-Host "Using CUDA_PATH shim: $shimRoot"
}

$resolvedInput = (Resolve-Path -LiteralPath $InputPath).Path
$pdfFiles = @()
if ((Get-Item -LiteralPath $resolvedInput).PSIsContainer) {
    $pdfFiles = @(Get-ChildItem -LiteralPath $resolvedInput -Filter *.pdf -File | Sort-Object Name)
} else {
    $pdfFiles = @(Get-Item -LiteralPath $resolvedInput)
    if ($pdfFiles[0].Extension -ine ".pdf") { throw "Input file must be a PDF: $resolvedInput" }
}

if ($pdfFiles.Count -eq 0) {
    throw "No PDF files found at $InputPath"
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$workRoot = Join-Path $root "work"
New-Item -ItemType Directory -Force -Path $workRoot | Out-Null

$env:MINERU_MODEL_SOURCE = $ModelSource
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

if ($Backend -in @("vlm-engine", "hybrid-engine")) {
    Ensure-CudaPathForLmdeploy -ProjectRoot $root -ProjectWorkRoot $workRoot
}

foreach ($pdf in $pdfFiles) {
    if ($pdf.Extension.ToLowerInvariant() -ne ".pdf") {
        Write-Warning "Skipping non-PDF file: $($pdf.FullName)"
        continue
    }

    $safeName = [IO.Path]::GetFileNameWithoutExtension($pdf.Name)
    $bookWork = Join-Path $workRoot $safeName
    $mineruOut = Join-Path $bookWork "mineru"
    $provenanceArgs = @("--source-pdf", $pdf.FullName, "--work-dir", $bookWork,
        "--backend", $Backend, "--method", $Method, "--lang", $Lang, "--model-source", $ModelSource)
    if ($SkipMinerU) {
        & $venvPython $provenanceTool verify @provenanceArgs
        if ($LASTEXITCODE -ne 0) { throw "Retained extraction cannot be reused safely: $bookWork" }
    }
    # Retain prior extraction for diagnosis and recovery. A fresh run never mixes outputs.
    if (-not $SkipMinerU -and (Test-Path -LiteralPath $bookWork)) {
        $archiveRoot = Join-Path $workRoot "previous-conversions"
        New-Item -ItemType Directory -Force -Path $archiveRoot | Out-Null
        $archive = Join-Path $archiveRoot ([guid]::NewGuid().ToString())
        $resolvedBookWork = [IO.Path]::GetFullPath($bookWork)
        if (-not $resolvedBookWork.StartsWith($workRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Work directory is outside project work root: $resolvedBookWork"
        }
        Move-Item -LiteralPath $resolvedBookWork -Destination $archive
        Write-Host "Previous work preserved: $archive"
    }
    if ($SkipMinerU -and -not (Test-Path -LiteralPath $mineruOut)) { throw "No retained extraction for -SkipMinerU: $mineruOut" }
    New-Item -ItemType Directory -Force -Path $mineruOut | Out-Null

    Write-Host ""
    Write-Host "=== $($pdf.Name) ===" -ForegroundColor Cyan

    if (-not $SkipMinerU) {
        $mineruInput = Join-Path $bookWork "source.pdf"
        Copy-Item -LiteralPath $pdf.FullName -Destination $mineruInput -Force

        $mineruArgs = @("-p", $mineruInput, "-o", $mineruOut, "-b", $Backend)
        if ($Backend -in @("pipeline", "hybrid-engine")) {
            $mineruArgs += @("-m", $Method)
        }
        if ($Backend -eq "pipeline" -and $Lang) {
            $mineruArgs += @("-l", $Lang)
        }
        Write-Host "Running MinerU..."
        & $mineruExe @mineruArgs
        if ($LASTEXITCODE -ne 0) {
            throw "MinerU failed for $($pdf.FullName)"
        }
    }

    $contentSource = Get-ChildItem -LiteralPath $mineruOut -Recurse -File |
        Where-Object { $_.Name -like "*_content_list_v2.json" } |
        Sort-Object Length -Descending |
        Select-Object -First 1

    if (-not $contentSource) {
        $contentSource = Get-ChildItem -LiteralPath $mineruOut -Recurse -File |
            Where-Object { $_.Name -like "*_content_list.json" } |
            Sort-Object Length -Descending |
            Select-Object -First 1
    }

    if (-not $contentSource) {
        $contentSource = Get-ChildItem -LiteralPath $mineruOut -Recurse -Filter *.md -File |
            Sort-Object Length -Descending |
            Select-Object -First 1
    }

    if (-not $contentSource) {
        throw "No MinerU Markdown or content_list JSON was found under $mineruOut"
    }

    if (-not $SkipMinerU) {
        & $venvPython $provenanceTool record @provenanceArgs
        if ($LASTEXITCODE -ne 0) { throw "Could not record extraction provenance: $bookWork" }
    }

    $bookTitle = if ($Title) { $Title } else { $safeName }
    $buildProvenanceArgs = @($provenanceArgs) + @("--title", $bookTitle, "--calibre", $ebookConvert)
    if ($Author) { $buildProvenanceArgs += @("--author", $Author) }
    & $venvPython $provenanceTool build @buildProvenanceArgs
    if ($LASTEXITCODE -ne 0) { throw "Could not verify build provenance: $bookWork" }
    $ebookMd = Join-Path $bookWork "ebook_source.md"
    $cleanArgs = @(
        $contentSource.FullName,
        "--output", $ebookMd,
        "--title", $bookTitle
    )
    if ($Author) {
        $cleanArgs += @("--author", $Author)
    }

    Write-Host "Building ebook-friendly Markdown from $($contentSource.Name)..."
    & $venvPython $tool @cleanArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Markdown conversion failed for $($pdf.FullName)"
    }

    $htmlSource = Join-Path $bookWork "ebook_source.html"
    Write-Host "Building safe HTML source..."
    & $venvPython $htmlTool $ebookMd "--output" $htmlSource "--title" $bookTitle
    if ($LASTEXITCODE -ne 0) {
        throw "HTML preparation failed for $($pdf.FullName)"
    }

    $targets = if ($Format -eq "both") { @("epub", "azw3") } else { @($Format) }
    $stagingDir = Join-Path $bookWork ("build-" + [guid]::NewGuid().ToString())
    New-Item -ItemType Directory -Path $stagingDir | Out-Null
    $stagedTargets = @()
    foreach ($targetFormat in $targets) {
        $target = Join-Path $stagingDir "$safeName.$targetFormat"
        $ebookArgs = @(
            $htmlSource,
            $target,
            "--input-encoding", "utf-8",
            "--language", "zh",
            "--title", $bookTitle,
            "--use-auto-toc",
            "--level1-toc", "//*[local-name()='h1']",
            "--level2-toc", "//*[local-name()='h2']",
            "--level3-toc", "//*[local-name()='h3']"
        )
        if ($Author) {
            $ebookArgs += @("--authors", $Author)
        }

        Write-Host "Writing $targetFormat..."
        & $ebookConvert @ebookArgs
        if ($LASTEXITCODE -ne 0) {
            throw "ebook-convert failed for $target"
        }
        $stagedTargets += $target
    }
    $receipt = Join-Path $workRoot ("conversion-receipts\" + [guid]::NewGuid().ToString() + ".json")
    & $venvPython $artifactTool publish @stagedTargets --source-pdf $pdf.FullName --output-dir $OutputDir --backup-dir (Join-Path $workRoot "artifact-backups") --receipt $receipt --provenance (Join-Path $bookWork "build-provenance.json")
    if ($LASTEXITCODE -ne 0) { throw "Output verification/publication failed for $($pdf.FullName); intermediates retained at $bookWork" }

    if ($KeepWork) {
        Write-Host "Intermediate files kept in $bookWork for inspection."
    } else {
        $resolvedBookWork = [IO.Path]::GetFullPath($bookWork)
        if (-not $resolvedBookWork.StartsWith($workRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing cleanup outside project work root: $resolvedBookWork"
        }
        Remove-Item -LiteralPath $resolvedBookWork -Recurse -Force
        Write-Host "Cleaned intermediate files."
    }
}
