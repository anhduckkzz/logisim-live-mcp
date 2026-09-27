# Rebuilds src\logisim_mcp\plugin\logisim-mcp-live-plugin.jar (needs a JDK 21+ with javac and jar).
param(
    [string]$LogisimJar = (Join-Path $PSScriptRoot "..\tools\logisim-evolution-5.0.0-all.jar")
)
$ErrorActionPreference = "Stop"
$build = Join-Path $PSScriptRoot "build"
$classes = Join-Path $build "classes"
Remove-Item -Recurse -Force $build -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $classes | Out-Null
$sources = Get-ChildItem (Join-Path $PSScriptRoot "src\vn\logisimmcp\live") -Filter *.java | ForEach-Object { $_.FullName }
javac --release 21 -cp $LogisimJar -d $classes @sources
if ($LASTEXITCODE -ne 0) { throw "javac failed" }
$out = Join-Path $PSScriptRoot "..\src\logisim_mcp\plugin\logisim-mcp-live-plugin.jar"
jar cfm $out (Join-Path $PSScriptRoot "MANIFEST.MF") -C $classes .
if ($LASTEXITCODE -ne 0) { throw "jar failed" }
Write-Host "Built $out"
