# Understanding circuits

Everything the bridge knows about a circuit now comes from Logisim itself, so a model can
work on large designs from data instead of screenshots.

**Before placing a device**, `describe_component(library, component_name, properties)` returns
the body box and every port as an offset from the component location, e.g. for an AND gate
with `inputs=3`: `out (0,0)`, `in1 (-50,-20)`, `in2 (-50,0)`, `in3 (-50,20)`. TTL chips report
pin numbers and names (`7421`: `A0` = pin 1, ..., `Y1` = pin 8), subcircuits report their pin
labels. Every property is listed with its type, allowed options (or min/max) and default.

**Wiring by name**: `connect_ports(circuit, "A", "G1.in1")`, or `connect_ports` items inside
`apply_edits`. References may be a label (`G1.out`), an id (`AND Gate@300,150.in2`), a TTL pin
(`U1.pin13`), a one-port device (`A`), or a raw point `[x, y]`. The router uses Logisim's exact
device and label boxes and follows Logisim's connection rules: wires join only at wire ends
and ports, and Logisim splits a wire wherever another wire end or a port touches its middle.
So a new route may cross other wires at right angles, but never runs along one, bends on one,
or touches another port or wire end. When a port is already wired, the new wire may start
from any point of that net (a T-junction), like a person would draw it. Ports already on the
same net are reported as `already_connected`.

**Reading a circuit**:

- `inspect_circuit` (text by default, `format="json"` for data) lists every component with its
  box and absolute port coordinates and the net each port is on, then every net with its
  drivers, loads, width and current value from the window's simulation, then all problems.
- `view_circuit` draws the layout as characters (1 char = 10 units; `region` and `scale` for
  big circuits): `╔═╗` device bodies, wires, `┬┴├┤╋` connected junctions, `┼` crossings that do
  **not** connect, and `I/O/B` connected ports vs `i/o/b` unconnected ones.
- `diagnose_circuit` reports: unconnected ports, floating nets (no driver), several drivers,
  conflicts and error values (red wires), width mismatches, dangling wire ends, wires through
  device bodies or over labels, overlapping devices, duplicate labels.

**Proving it works**: `simulate_circuit` runs a private copy of Logisim's simulator (the window
is not disturbed): one row, explicit rows, or `all_combinations` for a truth table; `watch`
reports internal nets such as `G1.out`; `sequential` with `clock_cycles` steps clocked designs.
`set_inputs_in_window` drives the window's own pins so the user sees the result.

Verified end to end against the Logisim GUI: a full adder and a hierarchical 4-bit ripple
adder (four full-adder subcircuits) were drawn only with `describe_component` and
`connect_ports`; `diagnose_circuit` reported no problems and all 512 input combinations
simulated correctly (about 80 ms).
