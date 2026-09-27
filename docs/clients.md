# Connecting MCP clients

Logisim Live MCP is a local **stdio** MCP server. The client starts it on demand; nothing
listens on the network except the live plugin's loopback port inside Logisim.

Run the installer first (`scripts/install-windows.ps1` or `scripts/install.sh`). It writes
ready-to-paste snippets with your absolute paths into `generated-config/`.

The server command is always:

```text
<repo>/.venv/Scripts/python.exe -m logisim_mcp --root <project-root> serve --transport stdio --logisim <repo>/tools/logisim-evolution-5.0.0-all.jar
```

(`.venv/bin/python` on Linux/macOS.) `--root` is the only folder the server may read or
write; keep it dedicated to your Logisim projects.

## Claude Desktop

Settings > Developer > Edit Config, then merge `generated-config/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "logisim": {
      "command": "C:\\Tools\\logisim-live-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "logisim_mcp", "--root", "C:\\Users\\you\\Documents\\LogisimProjects",
               "serve", "--transport", "stdio",
               "--logisim", "C:\\Tools\\logisim-live-mcp\\tools\\logisim-evolution-5.0.0-all.jar"]
    }
  }
}
```

Quit Claude Desktop completely (including the tray icon) and start it again.

## Codex (desktop app and CLI)

Append `generated-config/codex-config.toml` to `%USERPROFILE%\.codex\config.toml`
(`~/.codex/config.toml` elsewhere), then restart Codex and check `/mcp`.

## ChatGPT (Secure MCP Tunnel)

ChatGPT connects to remote MCP servers only. OpenAI's
[Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
lets it reach this local server through `tunnel-client`, an outbound-only connector that
starts the stdio server on your machine. Requirements are set by OpenAI and depend on your
plan and workspace (developer mode; write actions may be limited on some plans).

1. Enable developer mode in ChatGPT.
2. In platform.openai.com > Settings > Organization > Tunnels, create a tunnel, link it to
   your ChatGPT workspace, and create a Runtime API key.
3. Install `tunnel-client` from [openai/tunnel-client](https://github.com/openai/tunnel-client/releases/latest).
4. Run:
   ```powershell
   $env:CONTROL_PLANE_API_KEY = "sk-..."
   .\scripts\start-chatgpt-tunnel.ps1 -ProjectRoot "$env:USERPROFILE\Documents\LogisimProjects" -TunnelId tunnel_...
   ```
5. In ChatGPT: Plugins > + > Connection: **Tunnel** > select the tunnel.

## Any other MCP client

Use the stdio command above. For clients that only speak HTTP, run
`scripts/start-http.ps1` (Streamable HTTP on `http://127.0.0.1:8765/mcp`) and keep it on
loopback; put an authenticated gateway or tunnel in front of it if it must be reached
remotely. [MCP Inspector](https://github.com/modelcontextprotocol/inspector) works with both.

## Several clients at once

Claude, Codex and ChatGPT can all be connected. They share one Logisim window: each bridge
sees the others' edits as hand edits and pulls them before its next change.
