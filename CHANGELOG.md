# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

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
