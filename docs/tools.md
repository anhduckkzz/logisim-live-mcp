# Tool reference

Generated from the server by `scripts/dev/gen_tool_docs.py`. `R` = read-only, `W` = writes, `D` = destructive (MCP annotations).

## Project

### `get_bridge_status` (R)

Report bridge configuration, the active project, whether it is live-bound to a Logisim window, and optionally probe the configured Logisim Evolution executable.

Parameters: `probe_logisim`?

### `create_project` (W)

Create and open a new native Logisim Evolution 5.0.0 .circ project beneath the allowlisted root and (by default) show it live in the Logisim window. Refuses to replace an existing file unless overwrite=true.

Parameters: `path`, `main_circuit`?, `overwrite`?, `show_in_app`?

### `open_project` (W)

Open a .circ file beneath the configured project root. With show_in_app=true (default) it is also shown in the Logisim window, launching Logisim when it is closed, and later edits appear there live. If the window already holds unsaved hand edits for this file, the bridge starts from those.

Parameters: `path`, `show_in_app`?

### `close_project` (D)

Close the bridge's in-memory project. Unsaved edits are discarded and reported; the Logisim window is left as it is.

Parameters: none

### `list_circuits` (R)

List circuit names, main status, and component/wire counts in the open project.

Parameters: none

### `list_libraries` (R)

List library indices and descriptions used by the open project.

Parameters: none

### `save_project` (W)

Validate, create a timestamped backup, and atomically save the open project. The live Logisim window is checked against the file and marked as saved (no reload, undo history kept).

Parameters: none

### `save_and_open_in_logisim` (W)

Final step: save pending edits, verify the file with Logisim's own loader, and show the project in the Logisim window with no dialogs. A live window is simply brought to the front; otherwise the project is opened in the running Logisim, or Logisim is launched with it. Set force_reload=true only when the user agreed to discard unsaved hand edits in a window that is not live-bound.

Parameters: `force_reload`?

### `create_backup` (W)

Create a timestamped backup of the current on-disk .circ file.

Parameters: `reason`?

### `list_backups` (R)

List bridge-created backups for the open project, newest first.

Parameters: none

### `rollback_project` (D)

Restore the open project from a listed bridge backup. The current file is backed up first, and an open Logisim window is reloaded from the restored file.

Parameters: `backup_path`

## Understanding

### `list_component_types` (R)

Catalog of every component Logisim offers in this project (built-in libraries, loaded libraries, and this project's circuits usable as subcircuits). Filter with query (e.g. 'flip', '74', 'mux') or library ('#Gates' or its index).

Parameters: `library`?, `query`?

### `describe_component` (R)

Ask Logisim for the exact shape of a component type, optionally with properties applied (e.g. {'inputs':'3','facing':'north'}): body bounds and every port with its name, aliases (pin13, in2, p0...), direction, bit width and offset from the component location, plus every property with its type, allowed options and default. Use it before placing a device so ports land exactly where wires will go.

Parameters: `library`, `component_name`, `properties`?

### `inspect_circuit` (R)

Understand a circuit without a screenshot: every component with its exact box and absolute port coordinates, which net each port is on, every net with drivers, loads, bit width and current simulated value, and all problems (unconnected ports, floating or conflicting nets, several drivers, width mismatches, dangling wires, wires through devices, overlaps). Connectivity is computed exactly as Logisim connects wires. format='text' (compact, default) or 'json'.

Parameters: `circuit_name`, `format`?, `include_properties`?, `include_values`?

### `view_circuit` (R)

Draw the circuit as characters on the Logisim grid (1 char = scale units, default 10) with coordinate rulers: device boxes with names, wire shapes, connected junctions vs crossings that do NOT connect, and port markers (upper case = connected, lower case = unconnected). Use region=[x1,y1,x2,y2] to zoom into part of a large circuit.

Parameters: `circuit_name`, `region`?, `scale`?

### `diagnose_circuit` (R)

List electrical and layout problems of one circuit, or of every circuit in the project when circuit_name is omitted.

Parameters: `circuit_name`?

### `read_circuit` (R)

Read semantic components, properties, locations, and wires from one circuit, including hand edits made in the Logisim window.

Parameters: `circuit_name`

### `analyze_layout` (R)

Score schematic readability and report component overlaps, wires through devices, overlapping wire segments, crossings, and non-orthogonal wires.

Parameters: `circuit_name`

### `validate_project` (R)

Check XML structure and Logisim project invariants without saving.

Parameters: none

### `validate_with_logisim` (R)

Load and round-trip the saved project through Logisim Evolution 5.0.0's own XML reader/writer. Save pending edits first.

Parameters: `timeout_seconds`?

## Editing (live)

### `add_circuit` (W)

Add an empty circuit to the open project and optionally make it the main circuit.

Parameters: `circuit_name`, `set_as_main`?

### `rename_circuit` (W)

Rename a circuit and update its main-circuit setting and all native subcircuit references.

Parameters: `circuit_name`, `new_name`

### `delete_circuit` (D)

Delete a non-final circuit. Referencing subcircuit components are rejected unless delete_references=true.

Parameters: `circuit_name`, `delete_references`?

### `set_main_circuit` (W)

Select the circuit Logisim should display and simulate as the project entry point.

Parameters: `circuit_name`

### `add_component` (W)

Add a Logisim component by library index, component type, grid location, and properties. Example: component_name='Pin', library='0', location=[100,100]. Appears live in Logisim.

Parameters: `circuit_name`, `component_name`, `library`, `location`, `properties`?

### `update_component` (W)

Set or remove semantic properties on one uniquely selected component.

Parameters: `circuit_name`, `location`, `component_name`?, `library`?, `new_component_name`?, `new_library`?, `set_properties`?, `remove_properties`?

### `move_component` (W)

Move one uniquely selected component. Wires remain unchanged unless move_exact_wire_endpoints=true; inspect the circuit after moving complex gates.

Parameters: `circuit_name`, `location`, `new_location`, `component_name`?, `library`?, `move_exact_wire_endpoints`?

### `delete_component` (D)

Delete one uniquely selected component. Attached wires are preserved unless remove_exact_endpoint_wires=true.

Parameters: `circuit_name`, `location`, `component_name`?, `library`?, `remove_exact_endpoint_wires`?

### `connect_ports` (W)

Wire two ports by name, using Logisim's exact port positions and device bodies: source/target like 'G1.out', 'U1.pin13', 'AND Gate@300,150.in2', a one-port device label such as 'A', {'component':'G1','port':'in2'}, or a raw point [x,y] (e.g. an existing wire to tap). The route never touches other ports or wire ends and never runs along or bends on another wire, so it cannot short nets by accident.

Parameters: `circuit_name`, `source`, `target`, `clearance`?

### `connect_wire_smart` (W)

Route a multi-segment orthogonal wire on the Logisim grid. Avoids component and IC bodies, heavily penalizes wire overlap, minimizes crossings and bends, and avoids crowding rows/columns near other I/O pins. Use this for normal circuit drawing.

Parameters: `circuit_name`, `start`, `end`, `grid_step`?, `clearance`?

### `connect_wire` (W)

Low-level operation that adds one exact straight segment. Prefer connect_wire_smart for finished circuit drawings.

Parameters: `circuit_name`, `start`, `end`

### `disconnect_wire` (D)

Remove the exact wire segment between two Logisim grid points.

Parameters: `circuit_name`, `start`, `end`

### `apply_edits` (W)

Apply an ordered list of edits to one circuit as a single step: it appears in the Logisim window at once and is one Ctrl+Z. connect_ports items take 'source' and 'target' port references, e.g. {'action':'connect_ports','source':'A','target':'G1.in1'}. Each item has an 'action' (add_component, connect_ports, update_component, move_component, delete_component, connect_wire, connect_wire_smart, disconnect_wire) plus that tool's arguments except circuit_name, e.g. {'action':'add_component','component_name':'AND Gate','library':'1','location':[300,200]} or {'action':'connect_wire_smart','start':[200,200],'end':[260,190]}. If any item fails, nothing is changed.

Parameters: `circuit_name`, `operations`, `label`?

## Simulation

### `simulate_circuit` (R)

Run the circuit in Logisim's simulator (a private copy; the window is not disturbed) and return a table. Give inputs={'A':1,'B':'0101'} for one row, rows=[{...},{...}] for several, or all_combinations=true (optionally with inputs=['A','B'] to choose the order) for a full truth table. Pins are addressed by label. watch=['G1.out', 'U2.pin6', [x,y]] also reports internal nets. sequential=true keeps state between rows and clock_cycles ticks every clock that many full cycles after applying each row.

Parameters: `circuit_name`, `inputs`?, `rows`?, `all_combinations`?, `outputs`?, `watch`?, `sequential`?, `clock_cycles`?, `max_rows`?, `format`?

### `set_inputs_in_window` (W)

Drive input pins (by label) in the window's own simulation so the user sees the values and the resulting wire colours, e.g. values={'A':1,'B':0}.

Parameters: `circuit_name`, `values`

### `run_test_vector` (R)

Run Logisim Evolution --test-vector for a saved circuit and an allowlisted vector file.

Parameters: `circuit_name`, `vector_file`, `timeout_seconds`?

## Window

### `show_in_logisim` (R)

Bring the Logisim window to the front and switch it to the given circuit (or just focus it). Opens or launches Logisim first when the project is not shown yet.

Parameters: `circuit_name`?

### `sync_from_logisim` (R)

Pull the circuit exactly as it is in the Logisim window (hand edits, undo/redo) into the bridge. Normally automatic; use it to be explicit.

Parameters: none
