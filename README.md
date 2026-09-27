# Logisim Live MCP

**Let AI agents design digital circuits in Logisim Evolution, live.**

Logisim Live MCP is a [Model Context Protocol](https://modelcontextprotocol.io) server that
lets Claude, Codex, ChatGPT or any MCP client build, wire, inspect and simulate circuits in
[Logisim Evolution](https://github.com/logisim-evolution/logisim-evolution). Every edit
appears immediately in the running Logisim window as a normal, undoable action, the way the
Blender MCP drives Blender. The agent understands the circuit through data that comes from
Logisim itself (exact ports, the real netlist, simulated values), not through screenshots.

[![CI](https://github.com/anhduckkzz/logisim-live-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/anhduckkzz/logisim-live-mcp/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Logisim Evolution](https://img.shields.io/badge/Logisim%20Evolution-5.0.0-orange)
![License](https://img.shields.io/badge/license-MIT%20%2B%20GPL--3.0%20plugin-green)

## What it looks like

Ask *"build a full adder with inputs A, B, Cin and outputs S, Cout, then prove it works"*.
The agent places the parts, wires them by port name (`A` to `X1.in1`, `X1.out` to `N2.in1`,
...) while you watch them appear in Logisim, and then checks its work:

```text
> view_circuit("main")
    50        150       250       350       450       550       650
    ┬    ·    ┬    ·    ┬    ·    ┬    ·    ┬    ·    ┬    ·    ┬    ·
       ╔═╗
       ║AO────────┐╔═════╗
       ╚═╝        ├I     ║
130         XOR X1│║XOR XO────────┐
                 ┌┘║     ║        │
                 │┌I     ║        │╔═════╗
                 ││╚═════╝        ├I     ║
       ╔═╗       ││         XOR X2│║XOR XO───────────────────────IS║
       ║BO──────┬┼┘               │║     ║
       ...

> diagnose_circuit("main")
main: 10 components, 8 nets, no problems

> simulate_circuit("main", all_combinations=true)
A  B  Cin  |  S  Cout
0  0    0  |  0     0
0  0    1  |  1     0
...
1  1    1  |  1     1
```

## Features

- **Live, undoable editing.** Opening or creating a project shows it in Logisim (launching
  it if needed). Each tool call becomes one Logisim action: it repaints at once, can be
  undone with Ctrl+Z, and is validated by Logisim, so an unknown component, a bad property
  value or an invalid circuit name is rejected and nothing changes.
- **Understanding without screenshots.** `describe_component` gives a part's exact ports
  (names, TTL pin numbers, direction, bit width, offsets) and properties (types, options,
  defaults). `inspect_circuit` gives the netlist exactly as Logisim connects it, with live
  values. `view_circuit` draws the layout as text. `diagnose_circuit` finds unconnected
  ports, floating or conflicting nets, width mismatches, dangling wires and overlaps.
- **Wiring by name that cannot short nets.** `connect_ports("U1.pin13", "G2.in1")` routes an
  orthogonal wire around real device and label boxes. Logisim joins wires at any wire end or
  port that touches them, so the router never runs along, bends on, or touches another net;
  it taps existing wires of the same net like a person would.
- **Proof by simulation.** `simulate_circuit` returns truth tables, explicit rows or clocked
  sequences from Logisim's own simulator in a private state, plus internal nets you watch.
  Headless `--test-vector` runs are supported too.
- **Works with you, not around you.** Your own edits in the window (and Ctrl+Z) are pulled
  back before the agent's next step. Saves are validated, backed up and atomic, and the
  window is marked as saved without reloading.
- **Hierarchical designs.** Several circuits per file, subcircuits addressed by their pin
  labels, main-circuit selection. Verified on a 4-bit ripple adder built from full-adder
  subcircuits (512/512 simulated rows correct).
- **No startup dialogs.** Stale Logisim autosaves, which normally trigger "save autosave"
  prompts and file choosers, are archived instead of blocking the window.
- **Safe by design.** Access is limited to one project folder; no arbitrary file or XML
  write tool; the in-Logisim plugin listens on loopback only with a per-user token.

## Quick start

Requirements: Python 3.11+, Java 21+ (for Logisim Evolution 5.0.0), and an MCP client.

**Windows** (PowerShell, in the cloned repository):

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install-windows.ps1 -ProjectRoot "$env:USERPROFILE\Documents\LogisimProjects"
```

**Linux / macOS**:

```bash
scripts/install.sh ~/LogisimProjects
```

The installer creates `.venv`, installs the server, downloads the official Logisim Evolution
5.0.0 JAR and verifies its SHA-256, runs a health check, and writes ready-to-paste client
configs to `generated-config/`. Then connect your client:

| Client | How |
|---|---|
| Claude Desktop | merge `generated-config/claude_desktop_config.json` into the Developer config, restart |
| Codex | append `generated-config/codex-config.toml` to `~/.codex/config.toml` |
| ChatGPT | through OpenAI's Secure MCP Tunnel: `scripts/start-chatgpt-tunnel.ps1` |
| Others | stdio command in [docs/clients.md](docs/clients.md), or Streamable HTTP |

Details: [docs/clients.md](docs/clients.md) and [docs/install-windows.md](docs/install-windows.md).

## Example prompts

- "Create `alu.circ` and build a 1-bit ALU with AND, OR and ADD selected by a 2-bit op code.
  Check it with diagnose_circuit and a full truth table."
- "Open `lab3.circ`, explain what circuit `main` does from its netlist, and find wiring
  mistakes."
- "Use one 7421 chip to implement two 2-input AND gates (a 7408 half), tie the unused inputs
  high, and prove it with simulate_circuit."
- "Add a 4-bit register clocked by CLK to `counter.circ` and show its outputs over 8 clock
  cycles."

## Tools

38 tools in five groups (full reference: [docs/tools.md](docs/tools.md)):

| Group | Tools |
|---|---|
| Project | `create_project`, `open_project`, `save_project`, `save_and_open_in_logisim`, backups and rollback, status |
| Understanding | `list_component_types`, `describe_component`, `inspect_circuit`, `view_circuit`, `diagnose_circuit`, `read_circuit`, `analyze_layout`, validation |
| Editing (live) | `add_component`, `update_component`, `move_component`, `delete_component`, `connect_ports`, `connect_wire_smart`, `connect_wire`, `disconnect_wire`, `apply_edits` (batch, one undo step), circuit add/rename/delete/main |
| Simulation | `simulate_circuit`, `set_inputs_in_window`, `run_test_vector` |
| Window | `show_in_logisim`, `sync_from_logisim` |

## How it works

```text
MCP client --stdio--> Python bridge --loopback TCP + token--> live plugin inside Logisim
                      XML model (saved file)                  applies edits as Logisim actions,
                      diff per tool call                      reports ports, nets, values,
                      port-aware router                       simulates in private states
```

The bridge keeps an XML model of the project (what gets saved) and diffs it before and after
each tool call. The difference goes to a small Java plugin that Logisim loads through the
standard `-javaagent` switch; it applies the change through Logisim's own model APIs, so the
result is exactly what a user editing by hand would get. A revision counter detects hand
edits, and saves are verified against the window. More in
[docs/architecture.md](docs/architecture.md), [docs/live-editing.md](docs/live-editing.md)
and [docs/understanding.md](docs/understanding.md).

## Documentation

| Document | Content |
|---|---|
| [docs/clients.md](docs/clients.md) | Claude Desktop, Codex, ChatGPT (tunnel), other clients |
| [docs/install-windows.md](docs/install-windows.md) | Step-by-step Windows setup and troubleshooting |
| [docs/tools.md](docs/tools.md) | Every tool and its parameters |
| [docs/understanding.md](docs/understanding.md) | Ports, netlists, text view, diagnostics, simulation |
| [docs/live-editing.md](docs/live-editing.md) | Live window binding, hand edits, saves, autosaves |
| [docs/architecture.md](docs/architecture.md) | Components and consistency model |
| [docs/reference.md](docs/reference.md) | CLI, transports, test vectors, backups, limitations |
| [docs/layout-policy.md](docs/layout-policy.md) | Drawing conventions enforced by the router |
| [docs/logisim-source-notes.md](docs/logisim-source-notes.md) | Logisim 5.0.0 source behaviour the design relies on |
| [docs/development.md](docs/development.md) | Tests (including real GUI tests), plugin build, releases |

Example circuits built by the agent are in [examples/circuits](examples/circuits).

## Status and limitations

- Built and tested for **Logisim Evolution 5.0.0** on Windows and Linux (real GUI tests
  under Xvfb). macOS should work but is not yet tested.
- One project is open per server session. Logisim windows started by hand have no plugin;
  close them once and the bridge relaunches Logisim.
- VHDL components and FPGA board mapping are not covered by dedicated tools.

## License

- Python bridge (`src/`, `scripts/`, `tests/`, docs): [MIT](LICENSE).
- Live plugin (`java-plugin/`, and the built `logisim-mcp-live-plugin.jar`): runs inside
  Logisim Evolution and uses its APIs, so it is licensed [GPL-3.0-or-later](java-plugin/LICENSE),
  like Logisim Evolution.

Logisim Evolution is developed by the Logisim Evolution team and is not affiliated with this
project.
