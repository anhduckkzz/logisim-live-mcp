[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [switch]$SkipLogisimDownload
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ResolvedProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$VenvPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$ToolDir = Join-Path $RepoRoot 'tools'
$LogisimJar = Join-Path $ToolDir 'logisim-evolution-5.0.0-all.jar'
$GeneratedDir = Join-Path $RepoRoot 'generated-config'
$LogisimUrl = 'https://github.com/logisim-evolution/logisim-evolution/releases/download/v5.0.0/logisim-evolution-5.0.0-all.jar'
$ExpectedSha256 = '6b368e894742c04cc83aa9830f869bcab0190ede4df43ad6fecdb89b3a23a41c'

New-Item -ItemType Directory -Force -Path $ResolvedProjectRoot | Out-Null

if (-not (Test-Path -LiteralPath $VenvPython)) {
    $BootstrapPython = $null
    $BootstrapArgs = @()

    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.11 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) {
            $BootstrapPython = 'py'
            $BootstrapArgs = @('-3.11')
        }
    }

    if (-not $BootstrapPython -and (Get-Command python -ErrorAction SilentlyContinue)) {
        & python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) {
            $BootstrapPython = (Get-Command python).Source
        }
    }

    if (-not $BootstrapPython) {
        throw 'Python 3.11 or newer was not found. Install Python for Windows, then run this script again.'
    }

    & $BootstrapPython @BootstrapArgs -m venv (Join-Path $RepoRoot '.venv')
    if ($LASTEXITCODE -ne 0) {
        throw 'Python could not create the virtual environment.'
    }
}

& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw 'Could not upgrade pip. Check the internet connection and Python installation.'
}
& $VenvPython -m pip install -e "$RepoRoot[dev]"
if ($LASTEXITCODE -ne 0) {
    throw 'Could not install Logisim Live MCP and its Python dependencies.'
}

if (-not $SkipLogisimDownload) {
    New-Item -ItemType Directory -Force -Path $ToolDir | Out-Null
    if (-not (Test-Path -LiteralPath $LogisimJar)) {
        Write-Host 'Downloading official Logisim Evolution 5.0.0 JAR...'
        Invoke-WebRequest -Uri $LogisimUrl -OutFile $LogisimJar
    }
    $ActualSha256 = (Get-FileHash -LiteralPath $LogisimJar -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ActualSha256 -ne $ExpectedSha256) {
        throw "Logisim JAR checksum mismatch. Expected $ExpectedSha256, got $ActualSha256"
    }
}

$DoctorArgs = @('--root', $ResolvedProjectRoot, 'doctor')
if (Test-Path -LiteralPath $LogisimJar) {
    $DoctorArgs += @('--logisim', $LogisimJar)
}
& $VenvPython -m logisim_mcp @DoctorArgs
if ($LASTEXITCODE -ne 0) {
    throw 'The bridge doctor check failed. Review the error above before configuring a desktop client.'
}

# Generate copy/paste-ready local stdio configuration without changing either
# desktop application's existing settings.
New-Item -ItemType Directory -Force -Path $GeneratedDir | Out-Null
$ServerArgs = @(
    '-m', 'logisim_mcp',
    '--root', $ResolvedProjectRoot,
    'serve', '--transport', 'stdio',
    '--logisim', $LogisimJar
)
$CommandJson = $VenvPython | ConvertTo-Json -Compress
$ArgsJson = $ServerArgs | ConvertTo-Json -Compress
$RepoRootJson = $RepoRoot | ConvertTo-Json -Compress

$CodexConfig = @"
[mcp_servers.logisim]
command = $CommandJson
args = $ArgsJson
cwd = $RepoRootJson
enabled = true
required = false
startup_timeout_sec = 30
tool_timeout_sec = 300
default_tools_approval_mode = "writes"
"@
Set-Content -LiteralPath (Join-Path $GeneratedDir 'codex-config.toml') -Value $CodexConfig -Encoding utf8

$ClaudeConfig = @{
    mcpServers = @{
        logisim = @{
            command = $VenvPython
            args = $ServerArgs
        }
    }
} | ConvertTo-Json -Depth 5
Set-Content -LiteralPath (Join-Path $GeneratedDir 'claude_desktop_config.json') -Value $ClaudeConfig -Encoding utf8

Write-Host ''
Write-Host 'Installation complete.'
Write-Host "Project root: $ResolvedProjectRoot"
Write-Host "Codex config snippet: $(Join-Path $GeneratedDir 'codex-config.toml')"
Write-Host "Claude Desktop config: $(Join-Path $GeneratedDir 'claude_desktop_config.json')"
Write-Host "Start HTTP MCP: .\scripts\start-http.ps1 -ProjectRoot `"$ResolvedProjectRoot`""
Write-Host "Start stdio MCP: .\scripts\start-stdio.ps1 -ProjectRoot `"$ResolvedProjectRoot`""
