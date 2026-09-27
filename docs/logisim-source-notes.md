# Logisim Evolution 5.0.0 source alignment

This bridge was implemented and integration-tested against the official
`logisim-evolution/logisim-evolution` tag `v5.0.0`, commit
`7c3343e134c6a1c304e5531ace503b01273d7fbc`.

## Project XML

- `Template.java` and `resources/logisim/default.templ` define the empty/plain
  project form and the v5 built-in library identifiers. `create_project` uses
  those exact identifiers and toolbar conventions.
- `XmlWriter.java` writes `source=BuildInfo.version`, the project version,
  libraries, main circuit, options, mappings, toolbar, circuits, components,
  and wires. It writes component `lib`, `name`, and `loc`, stores only relevant
  attribute overrides, and writes wire `from`/`to` coordinates.
- `XmlReader.java` and `XmlCircuitReader.java` resolve component factories from
  each project library, create the factory's default attribute set, apply `<a>`
  overrides, parse locations, reject zero-length wires, and support the optional
  `buswidthpos` wire attribute.

The bridge therefore preserves the project tree and makes focused semantic edits
instead of regenerating an existing file or exposing an arbitrary XML write API.

## Component movement and wires

`MoveGesture.java` obtains actual component ends and uses Logisim's internal
connector routing code. That router is not a stable command-line API. The bridge
does not pretend that a component's anchor coordinate is every one of its ports:
moving a component preserves wires by default, and exact-anchor endpoint movement
is explicitly opt-in. Complex moves should be followed by inspection and explicit
wire edits.

For new connections, the bridge provides its own deterministic orthogonal A*
router. Standard gate bounds follow `AbstractGate.getOffsetBounds`, pin/probe
bounds follow the v5 `Probe`/`Pin` layout, and DIP-style TTL bounds follow
`AbstractTtlGate.getOffsetBounds`. Other factories receive conservative fallback
bounds. The cost function strongly penalizes collinear overlap, then crossings,
I/O-axis congestion, and turns, in that order.

## Native validation and application launch

- `Startup.java` accepts a `.circ` path as a positional argument, supports
  `--no-splash`, and implements `--new-file-format <input> <output>` as an
  XML-consistency round trip through Logisim's own loader/writer.
- `ProjectActions.java` can reload an already-open clean project only inside the
  same JVM. It does not provide an external file-watcher protocol for another
  process editing the project.

Consequently `validate_with_logisim` uses `--new-file-format` in a temporary
allowlisted directory. Since release 1.2.0, `save_and_open_in_logisim` talks to the live
agent (`java-agent/`) running inside the Logisim JVM: it calls
`ProjectActions.doOpen(Component, Project, File)`, which reloads a clean, already open
project in its own window and otherwise opens a new one. Only when no agent answers is a
new Logisim process launched, with the agent attached.

- `Startup.java` scans `user.home` for `Loader.LOGISIM_UNNAMED_AUTOSAVE_PREFIX` files on
  every GUI start and prompts with an option dialog plus a `JFileChooser` for each.
- `LogisimFile.load` prompts "load autosave / discard" when `Loader.findAutosaveFile`
  finds `.<name>.circ.autosave` beside the file.

The agent archives both kinds of leftovers before they are read.

## Live editing (release 2.0.0)

The live plugin uses only Logisim's own model APIs, the same ones its editing tools use:

- `CircuitMutation` (`add`, `remove`, `set`, `replace`, `setForCircuit`) turned into one
  action with `toAction(StringGetter)` and executed by `Project.doAction`, so each bridge
  edit is a normal entry in Edit > Undo. `CircuitTransaction` runs `WireRepair` afterwards,
  so Logisim may merge or split wire segments; the bridge compares wires geometrically
  (collinear segments merged) rather than segment by segment.
- `LogisimFileActions.addCircuit/removeCircuit/setMainCircuit` for circuit-level edits.
  Circuit names are checked with `SyntaxChecker.getErrorMessage` and
  `CorrectLabel.isKeyword` first, because the rename listener in `CircuitAttributes` would
  otherwise show a modal dialog.
- Component attributes are built like `XmlReader.initAttributeSet`: the attribute list is
  re-fetched while iterating (it grows for a Splitter), unknown names are ignored, and a
  missing `appearance` becomes `APPEAR_EVOLUTION` (and Probe/Pin appearance `APPEAR_CLASSIC`),
  so the window and a later reload of the saved file agree.
- `ProjectListener` events `ACTION_COMPLETE`, `UNDO_COMPLETE`, `REDO_COMPLETE`,
  `ACTION_MERGE` and `ACTION_SET_FILE` feed a revision counter; events raised while the
  plugin is applying its own change are not counted as hand edits.
- `LogisimFile.write(OutputStream, LibraryLoader, File)` exports the window's model without
  changing its main file (used to pull hand edits). After a verified bridge save,
  `Project.setFileAsClean()` plus `Loader.deleteAutosave()` reproduce what a save from the
  Logisim menu leaves behind.

## Understanding tools (release 2.1.0)

- Ports: `Component.getEnds()` gives each `EndData` (location, `BitWidth`, input/output/inout);
  `InstanceComponent.getInstance().getPorts()` gives the matching `Port` tooltips. TTL chips
  (`AbstractTtlGate.updatePorts`) put the physical pin number and name in the tooltip;
  `SubcircuitFactory` uses the subcircuit's pin labels. Gates have no tooltips, so the bridge
  names them `in1..inN` / `out`.
- Connectivity: `CircuitPoints` indexes only wire ends and component ends, so wires connect
  there and nowhere else; `WireRepair` (run by every `CircuitTransaction`, including
  `XmlCircuitReader` when a file is loaded) splits a wire where another end touches its
  middle. Tunnels join nets by label (`CircuitWires` bundles). The plugin rebuilds nets with
  the same rules; `Circuit.getWidthIncompatibilityData()` gives width conflicts.
- Values and simulation: `Project.getCircuitState(circuit).getValue(Location)` reads the
  window's values. Private simulation follows `TestVectorEvaluator`:
  `CircuitState.createRootState(project, circuit, thread)`, `Pin.FACTORY.driveInputPin`,
  `markComponentAsDirty`, `Propagator.propagate/toggleClocks/isOscillating`, all on the thread
  that owns the private state.
- Property metadata: attribute classes in `Attributes` keep their choices in private fields
  (`vals`, `start`/`end`); `BitWidth.Attribute` keeps `choices`. The plugin reads them
  reflectively to report options and ranges.
- Label boxes: `InstanceComponent.getBounds(Graphics)` adds the label text field, measured
  with real font metrics; the router treats it as an obstacle.

## Upstream references

- <https://github.com/logisim-evolution/logisim-evolution/tree/v5.0.0>
- <https://github.com/logisim-evolution/logisim-evolution/blob/v5.0.0/src/main/java/com/cburch/logisim/prefs/Template.java>
- <https://github.com/logisim-evolution/logisim-evolution/blob/v5.0.0/src/main/resources/resources/logisim/default.templ>
- <https://github.com/logisim-evolution/logisim-evolution/blob/v5.0.0/src/main/java/com/cburch/logisim/file/XmlWriter.java>
- <https://github.com/logisim-evolution/logisim-evolution/blob/v5.0.0/src/main/java/com/cburch/logisim/file/XmlReader.java>
- <https://github.com/logisim-evolution/logisim-evolution/blob/v5.0.0/src/main/java/com/cburch/logisim/file/XmlCircuitReader.java>
- <https://github.com/logisim-evolution/logisim-evolution/blob/v5.0.0/src/main/java/com/cburch/logisim/tools/MoveGesture.java>
- <https://github.com/logisim-evolution/logisim-evolution/blob/v5.0.0/src/main/java/com/cburch/logisim/gui/start/Startup.java>
- <https://github.com/logisim-evolution/logisim-evolution/blob/v5.0.0/src/main/java/com/cburch/logisim/proj/ProjectActions.java>
