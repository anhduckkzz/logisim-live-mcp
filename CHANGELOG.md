# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [2.3.0] - 2026-11-18

### Added
- `record_timing_diagram`: records Logisim's own Timing diagram window (Simulate > Timing
  diagram) while it plays steps on the window's simulation (drive inputs, press buttons, tick
  the clock), then saves the picture that window's File > Export Image writes (png, gif, jpg,
  svg). Signals are shown in the order asked; the sampled values after each step are returned.
- `export_image` draws circuits with Logisim itself by default (`renderer="logisim"`), exactly
  like File > Export Image: png, gif, jpg or svg, any zoom, `printer_view` for the print look.
  No extra Python package is needed. The bridge's own drawing stays available as
  `renderer="bridge"`.
- Push Buttons can be driven by label in `simulate_circuit` and `set_inputs_in_window`
  (1 = pressed, 0 = released, whatever the button's logic level), so reset buttons and other
  push-button inputs are testable without a stand-in Pin.

### Changed
- `create_project`, `save_project_as`, `export_image` and `record_timing_diagram` create missing
  folders under the project root instead of failing, and report them in `created_directories`.
- `update_component` (and its `apply_edits` action) also accepts `properties`, like
  `add_component`.
- A Pin added with `output: true` (or `input: true`) gets the matching `type` property instead of
  an ignored unknown attribute.
- Live protocol 3: a Logisim window started by an older bridge is reported with a clear "close
  Logisim once" message instead of failing on the new commands.

## [2.2.0] - 2026-10-31

### Added
- `disconnect_route` (also inside `apply_edits`): remove a whole routed wire from the `points`
  a smart route returned; a longer collinear wire that only partly covers a segment is split
  instead of being left in place.
- `save_project_as`: fork the open project to a new `.circ` and keep working on the copy; the
  original file is left untouched.
- `export_image`: draw a circuit as SVG (always available, wires coloured by simulated value) or
  PNG (optional `png` extra, `pip install logisim-live-mcp[png]`).
- `open_project` and `create_project` report a `previous_project` entry when they replace an
  open project, with a warning when its edits were never saved.
- `simulate_circuit` and `set_inputs_in_window` list the labelled input and output pins when
  Logisim rejects an unknown pin label.

### Changed
- A new output `Pin` defaults to `facing=west`, which is what Logisim's own toolbar places, so
  the wire attaches on the correct side. An explicit `facing` is still honoured.
- Smart routing keeps a straight run when two aligned points are connected and nothing blocks
  it, instead of jogging off the row because of nearby port congestion.
- Automatic backups (pre-save, pre-rollback, pre-save-as) are skipped when the newest backup
  already holds identical bytes, and only the newest 20 automatic backups are kept per project
  (`LOGISIM_MCP_BACKUP_KEEP`, `0` keeps everything). Backups created on request are never pruned.

## [2.1.0] - 2026-09-27

### Added
- Understanding tools backed by Logisim itself: `list_component_types`, `describe_component`
  (exact ports with names, TTL pin numbers, directions, widths, offsets; properties with
  types, options and defaults), `inspect_circuit` (netlist with live values and problems),
  `view_circuit` (character drawing of the layout), `diagnose_circuit`.
- `simulate_circuit`: truth tables, explicit rows, sequential steps with clock cycles and
  watched internal nets, in a private simulator state; `set_inputs_in_window`.
- `connect_ports` (also inside `apply_edits`): wiring by port name using exact geometry.
- Flip-flop ports use datasheet names (D, T, J/K, S/R, Clock/CLK, Q, Qn, Clear, Preset);
  open Clear/Preset/Enable inputs are reported as information, not warnings.
- Strict router: never runs along, bends on, or touches another net's wire, port or wire end;
  taps existing wires of the same net; avoids device bodies and label text.

### Changed
- Smart routing and layout analysis use Logisim's exact bounds when a window is attached.
- An error value caused by a floating input is reported as `error_value`, not as a conflict.

## [2.0.0] - 2026-09-26

### Added
- Live editing: every edit tool is mirrored into the running Logisim window as one undoable
  action; Logisim validates components, property values and circuit names.
- Hand edits in the window (including Ctrl+Z/Ctrl+Y) are detected and pulled back.
- Saves verify the window against the file and mark it clean without reloading.
- `apply_edits`, `show_in_logisim`, `sync_from_logisim`.

## [1.2.0] - 2026-09-26

### Added
- Live plugin loaded with `-javaagent`: reuse the running Logisim window, launch it when
  closed, bring it to the front.
- Stale unnamed and per-file autosaves are archived, so Logisim never blocks on the
  "save autosave" dialog and file chooser at startup.

## [1.1.0]

- Initial bridge: allowlisted `.circ` editing, smart routing, layout analysis, validation
  with Logisim's own loader, backups and rollback, headless test vectors.
