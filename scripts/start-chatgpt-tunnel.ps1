# Connects this bridge to ChatGPT through OpenAI's Secure MCP Tunnel.
#
# ChatGPT only talks to remote MCP servers. tunnel-client runs on this PC, makes an
# outbound-only HTTPS connection to OpenAI, and starts the bridge locally over stdio, so the
# bridge, the live Logisim plugin and your files all stay on this machine.
#
# One-time prerequisites (done by you in the browser; they use your OpenAI account):
#   1. ChatGPT with developer mode enabled (Settings > Apps > Advanced > Developer mode).
#   2. platform.openai.com > Settings > Organization > Tunnels: create a tunnel, note its
#      tunnel_... id and link it to your ChatGPT workspace (Tunnels Read/Manage/Use needed).
#   3. A Runtime API key from the same page, set by you in this shell:
#        $env:CONTROL_PLANE_API_KEY = "sk-..."      (this script never stores it)
#   4. tunnel-client for Windows from https://github.com/openai/tunnel-client/releases/latest
#      on PATH, or pass -TunnelClient C:\path\to\tunnel-client.exe
#
# Usage:
#   .\scripts\start-chatgpt-tunnel.ps1 -ProjectRoot C:\Users\you\Documents\LogisimProjects -TunnelId tunnel_...
# Then in ChatGPT: Plugins > + (developer-mode app) > Connection: Tunnel > pick the tunnel.
param(
    [Parameter(Mandatory = $true)][string]$ProjectRoot,
    [Parameter(Mandatory = $true)][string]$TunnelId,
    [string]$TunnelClient = "tunnel-client",
    [string]$Profile = "logisim-live-mcp",
    [switch]$Reinit
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo ".venv\Scripts\python.exe"
$jar = Join-Path $repo "tools\logisim-evolution-5.0.0-all.jar"
foreach ($p in @($python, $jar, $ProjectRoot)) {
    if (-not (Test-Path $p)) { throw "Missing: $p (run .\scripts\install-windows.ps1 first)" }
}
if (-not $env:CONTROL_PLANE_API_KEY) {
    throw "Set `$env:CONTROL_PLANE_API_KEY to your OpenAI Runtime API key first."
}
if (-not (Get-Command $TunnelClient -ErrorAction SilentlyContinue)) {
    throw "tunnel-client not found; download it from https://github.com/openai/tunnel-client/releases/latest"
}
$mcpCommand = "`"$python`" -m logisim_mcp --root `"$ProjectRoot`" serve --transport stdio --logisim `"$jar`""
Write-Host "MCP command: $mcpCommand"
Push-Location $repo
try {
    if ($Reinit -or -not (& $TunnelClient doctor --profile $Profile 2>$null)) {
        & $TunnelClient init --sample sample_mcp_stdio_local --profile $Profile --tunnel-id $TunnelId --mcp-command $mcpCommand
        if ($LASTEXITCODE -ne 0) { throw "tunnel-client init failed" }
    }
    & $TunnelClient doctor --profile $Profile --explain
    Write-Host "Starting tunnel. Keep this window open while ChatGPT uses Logisim (Ctrl+C to stop)."
    & $TunnelClient run --profile $Profile
} finally {
    Pop-Location
}
