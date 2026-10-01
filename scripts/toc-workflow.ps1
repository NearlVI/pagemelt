param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("review", "resolve", "validate", "apply", "audit", "accept", "freeze")]
    [string]$Command,
    [Parameter(Mandatory = $true, Position = 1)]
    [string]$EpubDir,
    [string]$Spec = "",
    [string]$WorkDir = "",
    [string]$BackupDir = "",
    [string]$SearchSpec = "",
    [string]$OutputSpec = ""
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "python"
}

$arguments = @(
    (Join-Path $root "tools\toc_workflow.py"),
    $Command,
    $EpubDir
)
if ($Spec) {
    $arguments += @("--spec", $Spec)
}
if ($WorkDir) {
    $arguments += @("--work-dir", $WorkDir)
}
if ($BackupDir) {
    $arguments += @("--backup-dir", $BackupDir)
}
if ($SearchSpec) {
    $arguments += @("--search-spec", $SearchSpec)
}
if ($OutputSpec) {
    $arguments += @("--output-spec", $OutputSpec)
}

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
& $python @arguments
exit $LASTEXITCODE
