param([string]$KiCadVersion = "10.0")

$ErrorActionPreference = "Stop"
$pluginsRoot = (Join-Path $env:USERPROFILE "Documents\KiCad\$KiCadVersion\plugins")
$target = Join-Path $pluginsRoot "com.partport.kicad10"
$resolvedRoot = [IO.Path]::GetFullPath($pluginsRoot).TrimEnd('\')
$resolvedTarget = [IO.Path]::GetFullPath($target).TrimEnd('\')
if (-not $resolvedTarget.StartsWith($resolvedRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to remove a path outside the KiCad plugins directory: $resolvedTarget"
}
if (Test-Path -LiteralPath $resolvedTarget) {
    Remove-Item -LiteralPath $resolvedTarget -Recurse -Force
    Write-Host "Removed: $resolvedTarget"
} else {
    Write-Host "PartPort is not installed at: $resolvedTarget"
}
