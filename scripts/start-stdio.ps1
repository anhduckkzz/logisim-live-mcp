[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,
    [string]$LogisimPath
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    throw 'Run .\scripts\install-windows.ps1 first.'
}
if (-not $LogisimPath) {
    $LogisimPath = Join-Path $RepoRoot 'tools\logisim-evolution-5.0.0-all.jar'
}

& $Python -m logisim_mcp --root $ProjectRoot serve --transport stdio --logisim $LogisimPath
