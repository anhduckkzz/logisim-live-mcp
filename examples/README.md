# Examples

## Circuits built by an agent

Both circuits were drawn only with `describe_component`, `apply_edits` and `connect_ports`
(no hand-computed coordinates), then checked with `diagnose_circuit` (no problems) and
`simulate_circuit`.

| File | Content | Check |
|---|---|---|
| [circuits/full-adder.circ](circuits/full-adder.circ) | 1-bit full adder: 2 XOR, 2 AND, 1 OR | all 8 rows correct |
| [circuits/ripple-adder-4bit.circ](circuits/ripple-adder-4bit.circ) | 4-bit ripple-carry adder from four `FA` subcircuits | all 512 rows correct |

## Test vectors

[full-adder-vectors.txt](full-adder-vectors.txt) is a Logisim test-vector file for
`run_test_vector` (headless `--test-vector`).

## A typical session

```text
create_project(path="full-adder.circ")                 # Logisim opens with the new file
describe_component(library="1", component_name="XOR Gate")
apply_edits(circuit_name="main", operations=[          # place parts, one undo step
  {"action":"add_component","component_name":"Pin","library":"0","location":[100,100],"properties":{"label":"A"}},
  ...
])
apply_edits(circuit_name="main", operations=[          # wire by port name
  {"action":"connect_ports","source":"A","target":"X1.in1"},
  {"action":"connect_ports","source":"X1.out","target":"X2.in1"},
  ...
])
diagnose_circuit(circuit_name="main")                  # "no problems"
simulate_circuit(circuit_name="main", all_combinations=true)
save_project()                                         # window marked as saved
```
