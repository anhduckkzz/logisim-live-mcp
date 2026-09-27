# Live editing

### How it works

```text
MCP client  --tool call-->  bridge (Python)  --loopback TCP-->  live plugin inside Logisim
                             | XML model = what is saved         | applies the change as one
                             | diff before/after each tool       | Logisim action (undoable)
```

1. The bridge applies the tool to its own XML model (the source of truth for the file).
2. It diffs the model before and after the call and sends the difference to the plugin.
3. The plugin resolves components and properties through Logisim's own libraries and
   applies them as one undoable action. The canvas repaints at once, switches to the edited
   circuit, and scrolls only when the new part is completely off screen.
4. If Logisim rejects anything (unknown component, invalid property value, invalid or
   duplicate circuit name), nothing is applied on either side and the tool returns the
   reason. Properties Logisim does not know are reported as warnings, exactly as Logisim
   would ignore them when loading the file.
5. Every edit carries the window's revision number. If you changed the window by hand
   (drawing, moving, Ctrl+Z, Ctrl+Y), the plugin refuses the stale edit, the bridge pulls the
   window's state through Logisim's own writer, and replays the edit on top of your changes.
   Read tools pull hand edits too, so the model always sees what you see.
6. `save_project` writes the file (with backup), then asks the plugin to verify that the
   window matches it. If it does, the window is marked as saved (the `*` disappears, undo
   history and zoom are kept, the stale autosave is removed). If not, the window is reloaded
   from the file and the differences are reported.

Typical latency on a desktop is under 50 ms per edit; opening an already running window is
about 100 ms; a cold Logisim launch is 2 to 5 s.

### Opening, launching and existing windows

| Logisim state | `open_project` / `create_project` / `save_and_open_in_logisim` |
|---|---|
| Closed | Launched with the plugin and the project; the call waits until it is loaded. |
| Running, project shown and saved | Bound to that window as it is (no reload, undo history kept). |
| Running, project shown with unsaved hand edits | The bridge starts from the window's state. |
| Running, project not open | Opened in the running Logisim (reusing an empty start window). |
| Running, started by bridge 1.x | Refused with a message: close Logisim once, it is relaunched. |

Pass `show_in_app=false` to `open_project` / `create_project` to work on a file without
showing it. `close_project` leaves the window alone. `rollback_project` reloads the window
from the restored file.

### The plugin

`src/logisim_mcp/plugin/logisim-mcp-live-plugin.jar` (source in `java-plugin/`) is attached
with Java's standard `-javaagent` switch when the bridge launches Logisim. It is ordinary
local code: it does not call any AI model or online service. It listens on `127.0.0.1` only
(port `51235`) and every request must carry a random token that the bridge keeps in
`%USERPROFILE%\.logisim-mcp\live.json` and passes to Logisim through an environment
variable, never on the command line. Rebuild it with a JDK 21+ using
`.\java-plugin\build-plugin.ps1`.

Configuration: `LOGISIM_MCP_LIVE_PORT`, `LOGISIM_MCP_PLUGIN_JAR`, `LOGISIM_MCP_STATE_DIR`,
`LOGISIM_MCP_ARCHIVE_AUTOSAVES=0` (keep Logisim's original autosave prompts).

### Why the "save autosave" dialog used to appear

On every GUI start, stock Logisim looks for `.logisim-unnamed-autosave_*.circ.autosave`
files in the home folder (left behind when an Untitled project was modified and Logisim
did not close cleanly). For each one it shows a Save / Save and load / Discard prompt and
then a file chooser asking where to save it. Opening a file that has a stale
`.<name>.circ.autosave` next to it shows a similar "load autosave" prompt. The plugin moves
those leftovers to `%USERPROFILE%\.logisim-mcp\autosave-archive\<timestamp>\` before
Logisim starts (and before a reload), so nothing is lost and no dialog blocks the window.
