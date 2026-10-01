param(
    [Parameter(Mandatory = $true)]
    [string]$InputDir,
    [string]$OutputDir = "",
    [ValidateSet("epub", "azw3", "both")]
    [string]$Format = "epub",
    [ValidateSet("auto", "txt", "ocr")]
    [string]$Method = "auto",
    [ValidateSet("vlm-engine", "hybrid-engine", "pipeline")]
    [string]$Backend = "vlm-engine",
    [int]$MaxBooks = 0,
    [switch]$KeepWork,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$converter = Join-Path $root "scripts\convert-pdfbook.ps1"
$python = Join-Path $root ".venv\Scripts\python.exe"
$artifactTool = Join-Path $root "tools\ebook_artifacts.py"
$provenanceTool = Join-Path $root "tools\conversion_provenance.py"
$calibreDir = Join-Path $root "tools\calibre-extracted\PFiles64\Calibre2"

if ($OutputDir -eq "") {
    $OutputDir = Join-Path $root "output\psychology-books"
}

if (Test-Path -LiteralPath $calibreDir) {
    $env:PATH = "$calibreDir;$env:PATH"
}
$calibre = Get-Command "ebook-convert" -ErrorAction SilentlyContinue
$ebookConvert = if ($calibre) { $calibre.Source } else { Join-Path $calibreDir "ebook-convert.exe" }

$env:UV_NO_CONFIG = "1"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

if (-not (Test-Path -LiteralPath $InputDir)) {
    throw "Input directory not found: $InputDir"
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$logDir = Join-Path $root "work\batch-psychology-books"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$summaryPath = Join-Path $logDir "summary.csv"

if (-not (Test-Path -LiteralPath $summaryPath)) {
    "timestamp,status,input,output,log" | Set-Content -LiteralPath $summaryPath -Encoding UTF8
}

$pdfs = @(Get-ChildItem -LiteralPath $InputDir |
    Where-Object { -not $_.PSIsContainer -and $_.Extension -ieq ".pdf" } |
    Sort-Object Length, Name)
if ($pdfs.Count -eq 0) { throw "No PDF files found under $InputDir" }

Write-Host "Found $($pdfs.Count) PDF files under $InputDir"
Write-Host "Output: $OutputDir"
Write-Host "Logs: $logDir"

$processed = 0
$failed = 0
foreach ($pdf in $pdfs) {
    $safeName = [IO.Path]::GetFileNameWithoutExtension($pdf.Name)
    $targets = if ($Format -eq "both") { @("epub", "azw3") } else { @($Format) }
    $existing = @()
    foreach ($targetFormat in $targets) {
        $target = Join-Path $OutputDir "$safeName.$targetFormat"
        if (Test-Path -LiteralPath $target) {
            $existing += $target
        }
    }

    if ($existing.Count -gt 0 -and -not $Force) {
        $canSkip = $false
        if ($existing.Count -eq $targets.Count) {
            & $python $provenanceTool outputs --source-pdf $pdf.FullName --backend $Backend --method $Method --calibre $ebookConvert --receipt-dir (Join-Path $root "work\conversion-receipts") --paths @existing
            $canSkip = ($LASTEXITCODE -eq 0)
        }
        if ($canSkip) {
            & $python $artifactTool sync @existing --source-pdf $pdf.FullName --backup-dir (Join-Path $root "work\artifact-backups")
            if ($LASTEXITCODE -ne 0) { throw "Failed to synchronize existing outputs for $($pdf.FullName)" }
            Write-Host "SKIP (verified and synchronized) $($pdf.Name)"
            continue
        }
        Write-Warning "Existing outputs are incomplete or could not be tied to this source/configuration. Preserved unchanged: $($pdf.Name). Review or use -Force to rebuild."
        $failed += 1
        [pscustomobject]@{timestamp=(Get-Date -Format "s"); status="failed-provenance"; input=$pdf.FullName; output=($existing -join ";"); log=""} |
            Export-Csv -LiteralPath $summaryPath -Append -NoTypeInformation -Encoding UTF8
        continue
    }

    if ($MaxBooks -gt 0 -and $processed -ge $MaxBooks) {
        Write-Host "Reached MaxBooks=$MaxBooks"
        break
    }

    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $logName = ($safeName -replace '[<>:"/\\|?*\[\]]', '_')
    $logPath = Join-Path $logDir "$stamp-$logName.log"
    Write-Host "START $($pdf.Name)"

    $args = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $converter,
        "-InputPath", $pdf.FullName,
        "-OutputDir", $OutputDir,
        "-Format", $Format,
        "-Backend", $Backend,
        "-Method", $Method
    )
    if ($KeepWork) {
        $args += "-KeepWork"
    }

    $started = Get-Date
    $oldErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & powershell @args > $logPath 2>&1
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $oldErrorActionPreference
    $elapsed = [int]((Get-Date) - $started).TotalSeconds

    if ($exitCode -eq 0) {
        Write-Host "DONE  $($pdf.Name) (${elapsed}s)" -ForegroundColor Green
        $status = "done"
    } else {
        Write-Host "FAIL  $($pdf.Name) (${elapsed}s). See $logPath" -ForegroundColor Red
        $status = "failed"
        $failed += 1
    }

    $outputText = ($targets | ForEach-Object { Join-Path $OutputDir "$safeName.$_" }) -join ";"
    $line = ('"{0}","{1}","{2}","{3}","{4}"' -f (Get-Date -Format "s"), $status, $pdf.FullName.Replace('"', '""'), $outputText.Replace('"', '""'), $logPath.Replace('"', '""'))
    Add-Content -LiteralPath $summaryPath -Value $line -Encoding UTF8
    $processed += 1
}

Write-Host "Batch complete."
if ($failed -gt 0) { throw "$failed book(s) failed; see $summaryPath" }
