# Reference: CLI, transports, test vectors and backups

## Local CLI

These commands do not start an MCP client:

```powershell
.\.venv\Scripts\logisim-mcp.exe --root "$env:LOGISIM_PROJECT_ROOT" create adder.circ
.\.venv\Scripts\logisim-mcp.exe --root "$env:LOGISIM_PROJECT_ROOT" inspect adder.circ
.\.venv\Scripts\logisim-mcp.exe --root "$env:LOGISIM_PROJECT_ROOT" doctor --logisim "$env:LOGISIM_EVOLUTION"
.\.venv\Scripts\logisim-mcp.exe --root "$env:LOGISIM_PROJECT_ROOT" inspect adder.circ --circuit main
.\.venv\Scripts\logisim-mcp.exe --root "$env:LOGISIM_PROJECT_ROOT" validate adder.circ
.\.venv\Scripts\logisim-mcp.exe --root "$env:LOGISIM_PROJECT_ROOT" backup adder.circ --reason before-demo
.\.venv\Scripts\logisim-mcp.exe --root "$env:LOGISIM_PROJECT_ROOT" backups adder.circ
.\.venv\Scripts\logisim-mcp.exe --root "$env:LOGISIM_PROJECT_ROOT" test adder.circ main vectors.txt --logisim "$env:LOGISIM_EVOLUTION"
.\.venv\Scripts\logisim-mcp.exe --root "$env:LOGISIM_PROJECT_ROOT" open adder.circ --logisim "$env:LOGISIM_EVOLUTION"
```

Rollback accepts only a path returned by `backups` and only from the internal
`.logisim-mcp/backups` directory:

```powershell
.\.venv\Scripts\logisim-mcp.exe --root "$env:LOGISIM_PROJECT_ROOT" rollback adder.circ ".logisim-mcp\backups\adder\BACKUP.circ"
```

## MCP transport

### Local stdio client

Configure an MCP client to run:

```text
command: C:\path\to\repo\.venv\Scripts\logisim-mcp.exe
arguments: --root C:\Users\you\Documents\LogisimProjects serve --transport stdio
```

Do not put logging on stdout in stdio mode; stdout is reserved for MCP messages.

### Streamable HTTP for ChatGPT / custom plugin development

Start a loopback-only server:

```powershell
.\.venv\Scripts\logisim-mcp.exe --root "$env:LOGISIM_PROJECT_ROOT" serve --transport streamable-http --host 127.0.0.1 --port 8765 --logisim "$env:LOGISIM_EVOLUTION"
```

The endpoint is:

```text
http://127.0.0.1:8765/mcp
```

Test it with MCP Inspector:

```powershell
npx @modelcontextprotocol/inspector@latest
```

Select **Streamable HTTP** and enter `http://127.0.0.1:8765/mcp`.

For ChatGPT developer-mode connection, use an OpenAI Secure MCP Tunnel when it is
available to your account/workspace, or place an authenticated HTTPS gateway in
front of the server. Do **not** expose this unauthenticated local process directly
to the public internet. In the ChatGPT connection UI, use the resulting HTTPS URL
with `/mcp` appended. Availability and labels can vary by account and workspace.

Current official references:

- [Build an MCP server](https://developers.openai.com/plugins/build/mcp-server)
- [Connect and test a plugin](https://developers.openai.com/plugins/deploy/connect-chatgpt)
- [MCP servers in the OpenAI API](https://developers.openai.com/api/docs/guides/tools-connectors-mcp)

## Test vector format

The first non-comment line contains pin labels, optionally with widths such as
`A[4]`. Each following line supplies input and expected output values. A sample is
included at `examples/full-adder-vectors.txt`.

The bridge invokes the official CLI form:

```text
java -jar logisim-evolution.jar --test-vector <circuit> <vectors> <project.circ>
```

It returns the process exit code and bounded stdout/stderr. Exit code zero is
reported as `passed: true`. Repetitive Windows Java Preferences warnings are folded
so they cannot flood an MCP response.

## Backup layout

Backups remain inside the allowlisted root:

```text
<root>/.logisim-mcp/backups/<relative-project-parent>/<project-stem>/
  20260926T123456.000000Z-ab12cd34.circ
  20260926T123456.000000Z-ab12cd34.json
```

The sidecar records source, reason, timestamp, and SHA-256. An automatic backup (reason
starting with `pre-`) is skipped when the newest backup already holds identical bytes, and only
the newest 20 automatic backups per project are kept; set `LOGISIM_MCP_BACKUP_KEEP` to another
number, or to `0` to keep everything. Backups created with `create_backup` are never pruned.

## Scope and limitations

- Library indices and property names come from the open project and Logisim's XML
  conventions. Use `list_libraries` and inspect nearby components before adding one.
- Structural validation is conservative and cannot replace opening the saved file in
  the exact Logisim Evolution version used by the project.
- Actual simulation requires a local Logisim Evolution installation and Java runtime.
- Logisim windows started by hand (without the plugin) cannot be edited live; close them
  once and let the bridge relaunch Logisim. Edits made while the window is closed are
  saved normally and shown the next time the project is opened.
- Release 2.2.0 adds `disconnect_route`, `save_project_as`, `export_image` and the changes listed
  in the changelog. Its Python side is unit-tested; the Java plugin is unchanged from 2.1.0.
- Release 2.1.0 adds the understanding tools above, tested the same way.
- Release 2.0.0 is tested end to end against a real Logisim 5.0.0 GUI (live drawing,
  rejected edits, a user's Ctrl+Z pulled back, save verification, test vectors, circuit
  add/rename/delete/main, stale autosaves). Release 1.1.0 was integration-tested with `logisim-evolution-5.0.0-all.jar` and Java 23,
  including a project created from scratch by the bridge and executed by Logisim itself.
- The HTTP server has no built-in multi-user authentication. Keep it on loopback and
  use the authenticated tunnel/gateway supplied by the client environment.

