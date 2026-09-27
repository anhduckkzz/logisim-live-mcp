# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

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
