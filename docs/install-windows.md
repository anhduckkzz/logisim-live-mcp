# End-to-end Windows setup: Codex Desktop and Claude Desktop

This guide connects the Logisim Live MCP to both desktop clients.
The recommended transport is local **stdio**: the desktop client starts the
bridge only when needed, no background service is required, and no network port
is exposed.

At the end, you can ask either client to create or edit a `.circ` project: Logisim
Evolution opens (or is launched) with the project, and every edit appears in its window
live. ChatGPT is covered in [clients.md](clients.md#chatgpt-secure-mcp-tunnel).

## 1. Requirements

- Windows 10 or 11.
- Python 3.11 or newer. During Python setup, enable **Add Python to PATH**.
- Java 21 or newer. Logisim Evolution 5.0.0 requires Java 21+.
- Codex Desktop and/or Claude Desktop, updated to a current version.
- The `logisim-live-mcp` repository cloned (or its release ZIP extracted) to a permanent
  folder, for example `C:\Tools\logisim-live-mcp`.

Do not install the bridge in a temporary folder and do not move the extracted
folder after connecting it to a desktop client. Both clients store absolute
paths to the bridge's private Python environment.

Check the runtimes in PowerShell:

```powershell
python --version
java -version
```

`python` must report 3.11 or newer and `java` must report 21 or newer.

## 2. Install the bridge and Logisim Evolution 5.0.0

Open PowerShell in the extracted source folder. Choose one folder that will
contain every `.circ` project and test-vector file the bridge is allowed to
access:

```powershell
Set-Location "C:\Tools\logisim-live-mcp"
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install-windows.ps1 -ProjectRoot "$env:USERPROFILE\Documents\LogisimProjects"
```

The installer:

1. creates a private Python environment in `.venv`;
2. installs the MCP bridge and its dependencies;
3. downloads the official Logisim Evolution 5.0.0 all-in-one JAR;
4. verifies the JAR's published SHA-256;
5. runs the bridge doctor check; and
6. creates ready-to-copy configurations in `generated-config`.

Successful output includes paths similar to:

```text
generated-config\codex-config.toml
generated-config\claude_desktop_config.json
```

The installer does not overwrite either application's existing settings.

### Verify the installation again

```powershell
.\.venv\Scripts\python.exe -m logisim_mcp `
  --root "$env:USERPROFILE\Documents\LogisimProjects" `
  doctor `
  --logisim ".\tools\logisim-evolution-5.0.0-all.jar"
```

The result should show the chosen `allowed_root` and a successful Logisim
runtime probe.

## 3. Connect Codex Desktop

Codex stores local MCP configuration in `%USERPROFILE%\.codex\config.toml`.
The ChatGPT desktop Codex surface, Codex CLI, and Codex IDE extension share this
configuration on the same host. OpenAI also supports adding a server in the app
under **Settings > MCP servers > Add server**, choosing **STDIO**, then restarting
the app.

The file-based setup is easiest because the installer generated the exact
Windows paths:

1. Open `generated-config\codex-config.toml` in Notepad.
2. Open `%USERPROFILE%\.codex\config.toml` in another Notepad window. Create it
   if it does not exist.
3. Append the complete `[mcp_servers.logisim]` block from the generated file.
   Do not remove unrelated existing settings or other MCP servers.
4. Save the file and fully restart Codex Desktop.
5. In a chat, type `/mcp` and confirm that `logisim` is connected.

The generated entry looks like this, with real absolute paths substituted by
the installer:

```toml
[mcp_servers.logisim]
command = "C:\\Tools\\logisim-live-mcp\\.venv\\Scripts\\python.exe"
args = ["-m", "logisim_mcp", "--root", "C:\\Users\\YOU\\Documents\\LogisimProjects", "serve", "--transport", "stdio", "--logisim", "C:\\Tools\\logisim-live-mcp\\tools\\logisim-evolution-5.0.0-all.jar"]
cwd = "C:\\Tools\\logisim-live-mcp"
enabled = true
required = false
startup_timeout_sec = 30
tool_timeout_sec = 300
default_tools_approval_mode = "writes"
```

`default_tools_approval_mode = "writes"` lets read-only inspection run normally
while keeping approval prompts for changes when the client supports tool
annotations.

Official reference: [OpenAI Model Context Protocol setup](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

## 4. Connect Claude Desktop

The bridge can run as a Claude Desktop local developer MCP server. This local
connection applies to normal Claude Desktop conversations; it is separate from
cloud-hosted custom connectors and is not available in `claude.ai` or Cowork.

1. Fully quit Claude Desktop, including its notification-area process.
2. Open this folder in File Explorer:

   ```text
   %APPDATA%\Claude
   ```

3. If `claude_desktop_config.json` does not exist, copy the generated
   `generated-config\claude_desktop_config.json` into that folder using that
   exact filename.
4. If the file already exists, keep its current contents and merge only the
   generated `"logisim"` object into the existing `"mcpServers"` object.
5. Start Claude Desktop again.
6. Click the **+** button beside the composer, choose **Connectors**, and confirm
   that the Logisim server and its tools are listed. Developer settings can also
   show the server status and logs.

Example structure—the installer supplies the real paths:

```json
{
  "mcpServers": {
    "logisim": {
      "command": "C:\\Tools\\logisim-live-mcp\\.venv\\Scripts\\python.exe",
      "args": [
        "-m",
        "logisim_mcp",
        "--root",
        "C:\\Users\\YOU\\Documents\\LogisimProjects",
        "serve",
        "--transport",
        "stdio",
        "--logisim",
        "C:\\Tools\\logisim-live-mcp\\tools\\logisim-evolution-5.0.0-all.jar"
      ]
    }
  }
}
```

JSON does not allow comments or trailing commas. If Claude is managed by a Team
or Enterprise administrator, local developer MCP must also be allowed by the
`isLocalDevMcpEnabled` policy.

Official references:

- [Getting started with local MCP servers on Claude Desktop](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop)
- [Claude Desktop enterprise configuration](https://support.claude.com/en/articles/12622667-enterprise-configuration-for-claude-desktop)

## 5. End-to-end acceptance test

Run this test separately in Codex Desktop and Claude Desktop:

```text
Use the Logisim tools to create `desktop-test.circ` inside the allowed project
root. In circuit `main`, build a two-input AND circuit with input pins A and B and
output pin Y, wire it with connect_ports, run diagnose_circuit and a full truth
table with simulate_circuit, then save it.
```

Approve write/open actions when prompted. A successful result has all of these
outcomes:

- `desktop-test.circ` exists under `Documents\LogisimProjects`;
- Logisim Evolution opened by itself and the gate, pins and wires appeared as they
  were added, without any dialog;
- `diagnose_circuit` reports no problems and the truth table is Y = A AND B;
- after saving, the window title has no `*` (the window is marked as saved); and
- a later save creates a timestamped recovery copy under
  `Documents\LogisimProjects\.logisim-mcp\backups`.

A Logisim window started by hand (not by the bridge) has no live plugin. Close it
once; the bridge relaunches Logisim with the plugin the next time it needs it.

## 6. Troubleshooting

### The MCP server is missing or disconnected

- Confirm the paths in the generated configuration still exist.
- Restart the desktop app after every configuration change.
- Do not run `start-stdio.ps1` yourself when using a desktop client; the client
  owns that stdio process.
- Codex: use `/mcp` and inspect `%USERPROFILE%\.codex\config.toml`.
- Claude: open Developer settings and inspect the MCP logs.

### Python cannot start

The extracted bridge folder was probably moved or its `.venv` was removed.
Return it to its original location or rerun `install-windows.ps1`, then replace
the old desktop configuration with the newly generated paths.

### Logisim validation or launch fails

```powershell
java -version
.\scripts\install-windows.ps1 -ProjectRoot "$env:USERPROFILE\Documents\LogisimProjects"
```

Java must be 21+. Rerunning the installer is safe; it reuses the verified JAR
and regenerates both desktop configuration files.

### The bridge rejects a project path

This is expected outside the allowlisted project root. Move the `.circ` and
test-vector files into `Documents\LogisimProjects`, or rerun the installer with
the intended dedicated root and update both desktop configurations.

### Claude Desktop is organization-managed

Ask the workspace administrator to allow local MCP/desktop extensions. The
current Windows policy name is `isLocalDevMcpEnabled`.

## 7. Security boundary

Both desktop clients receive the same restricted toolset. The bridge can only
read/write `.circ` projects and relevant test files beneath the configured
project root; it exposes no arbitrary file-write or raw XML-write tool. Saves
are validated, backed up, and replaced atomically. Keep the stdio configuration
as the default. The optional HTTP mode should remain bound to `127.0.0.1` unless
it is placed behind an authenticated MCP tunnel or HTTPS gateway.

