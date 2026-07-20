param(
    [string]$KiCadVersion = "10.0",
    [string]$Destination
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $Destination) {
    $Destination = Join-Path $env:USERPROFILE "Documents\KiCad\$KiCadVersion\plugins\com.partport.kicad10"
}
$Destination = [IO.Path]::GetFullPath($Destination).TrimEnd('\')
if ([IO.Path]::GetFileName($Destination) -ne "com.partport.kicad10") {
    throw "Destination must end in com.partport.kicad10: $Destination"
}

New-Item -ItemType Directory -Force -Path $Destination | Out-Null
$rootCache = Join-Path $Destination "__pycache__"
if (Test-Path -LiteralPath $rootCache) {
    Remove-Item -LiteralPath $rootCache -Recurse -Force
}
foreach ($name in @("plugin.json", "requirements.txt", "partport_plugin.py")) {
    Copy-Item -LiteralPath (Join-Path $repoRoot $name) -Destination $Destination -Force
}
foreach ($name in @("partport", "resources")) {
    $source = Join-Path $repoRoot $name
    $target = Join-Path $Destination $name
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    Get-ChildItem -LiteralPath $source -File | Where-Object {
        $_.Extension -notin @(".pyc", ".pyo")
    } | Copy-Item -Destination $target -Force
}

Write-Host "PartPort installed to: $Destination"
Write-Host "Restart KiCad or reload IPC plugins. The first dependency setup can take a minute."
Write-Host "If an editor was open during first-time setup, close and reopen it after setup completes."
