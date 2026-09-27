# Readable circuit layout policy

The MCP server instructs the model to treat schematic readability as a required
part of circuit generation, not a cosmetic follow-up.

## Placement

- Arrange logic in left-to-right stages: inputs, intermediate logic, outputs.
- Keep input and output labels aligned and use consistent spacing.
- Leave enough horizontal space for orthogonal routes before placing the next
  stage. Keep unrelated functional blocks separated vertically.
- Never place component bodies on top of each other.

## Routing

- Use `connect_wire_smart` for finished drawings. `connect_wire` remains a
  low-level exact-segment tool for deliberate manual corrections.
- Use horizontal/vertical segments on Logisim's grid.
- Component and IC bodies are hard obstacles.
- Collinear wire overlap has the highest routing penalty. A clean crossing is
  preferable to an accidental overlapping run, but avoiding both is preferred.
- Rows and columns near other component ports receive a congestion penalty so a
  route does not visually merge into unrelated inputs/outputs.
- Fewer bends are preferred after obstacle, overlap, crossing, and port-axis
  constraints have been satisfied.
- For fan-out, branch at an explicit existing endpoint/junction rather than
  drawing duplicate wire segments on top of an existing net.

## Final checks

Run `analyze_layout` on every circuit. The report identifies:

- overlapping component bodies;
- wires crossing component bodies;
- overlapping wire segments and their total overlap length;
- wire crossings;
- diagonal segments;
- an overall quality score.

Avoidable hard issues should be corrected before `save_and_open_in_logisim`.
That final operation returns the layout report together with native Logisim XML
validation and the application-launch result.
