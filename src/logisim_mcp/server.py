from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import __version__
from .live import LiveAppUnavailable
from .live_sync import LiveNotOpen, LiveSession
from .project import LogisimProject
from .runner import LogisimRunner
from .service import ProjectService
from .views import ascii_view, netlist_text, problems_text, truth_table_text

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
DELETE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)

BATCH_ACTIONS = (
    "add_component",
    "connect_ports",
    "update_component",
    "move_component",
    "delete_component",
    "connect_wire",
    "connect_wire_smart",
    "disconnect_wire",
)


def _route_components(service: ProjectService, project: LogisimProject, circuit_name: str):
    geometry = service.geometry(circuit_name, project)
    return geometry.router_components() if geometry is not None else None


def _connect_ports(
    service: ProjectService,
    project: LogisimProject,
    circuit_name: str,
    source: Any,
    target: Any,
    *,
    clearance: int = 10,
    strict: bool = True,
) -> dict[str, Any]:
    geometry = service.geometry(circuit_name, project)
    if geometry is None:
        raise ValueError(
            "connect_ports needs the project to be shown in Logisim (open_project with "
            "show_in_app=true, or save_and_open_in_logisim)"
        )
    a = geometry.resolve(source)
    b = geometry.resolve(target)
    if a.get("width") and b.get("width") and a["width"] != b["width"]:
        raise ValueError(
            f"{a['component']}.{a['port']} is {a['width']} bits but {b['component']}.{b['port']} "
            f"is {b['width']} bits"
        )
    nets = geometry.connectivity()
    pa, pb = (a["x"], a["y"]), (b["x"], b["y"])
    if nets.net_of(pa) is not None and nets.net_of(pa) == nets.net_of(pb):
        return {
            "already_connected": True,
            "from": {k: a[k] for k in ("component", "port", "x", "y") if a.get(k) is not None},
            "to": {k: b[k] for k in ("component", "port", "x", "y") if b.get(k) is not None},
        }
    source_net = nets.net_points(pa)
    target_net = nets.net_points(pb)
    route = project.connect_smart(
        circuit_name,
        [a["x"], a["y"]],
        [b["x"], b["y"]],
        clearance=clearance,
        components=geometry.router_components(),
        strict=strict,
        sources=source_net,
        targets=target_net,
        friendly_points=source_net | target_net,
    )
    route["from"] = {k: a[k] for k in ("component", "port", "x", "y") if a.get(k) is not None}
    route["to"] = {k: b[k] for k in ("component", "port", "x", "y") if b.get(k) is not None}
    route.pop("visited_nodes", None)
    return route


def _run_batch_step(
    service: ProjectService, project: LogisimProject, circuit_name: str, step: dict[str, Any]
) -> Any:
    args = dict(step)
    action = args.pop("action", None)
    if action == "connect_ports":
        return _connect_ports(
            service, project, circuit_name, args["source"], args["target"],
            clearance=args.get("clearance", 10), strict=args.get("strict", True),
        )
    if action == "add_component":
        return project.add_component(
            circuit_name,
            args["component_name"],
            args["library"],
            args["location"],
            args.get("properties"),
        )
    if action == "update_component":
        return project.update_component(circuit_name, args.pop("location"), **args)
    if action == "move_component":
        return project.move_component(
            circuit_name, args.pop("location"), args.pop("new_location"), **args
        )
    if action == "delete_component":
        return project.delete_component(circuit_name, args.pop("location"), **args)
    if action == "connect_wire":
        return project.connect(circuit_name, args["start"], args["end"])
    if action == "connect_wire_smart":
        return project.connect_smart(
            circuit_name,
            args.pop("start"),
            args.pop("end"),
            components=_route_components(service, project, circuit_name),
            **args,
        )
    if action == "disconnect_wire":
        return project.disconnect(circuit_name, args["start"], args["end"])
    raise ValueError(f"Unknown batch action {action!r}; expected one of {', '.join(BATCH_ACTIONS)}")


def create_server(
    allowed_root: str | Path,
    *,
    logisim_executable: str | Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> FastMCP:
    service = ProjectService(allowed_root)
    runner = LogisimRunner(service.policy, logisim_executable)
    service.live = LiveSession(runner)
    mcp = FastMCP(
        "Logisim Live MCP",
        instructions=(
            "Native live editing: open_project and create_project show the project in the "
            "Logisim window (launching Logisim if it is closed), and from then on every edit "
            "tool appears in that window immediately as one undoable Logisim action. Logisim "
            "itself validates each edit: an unknown component, an invalid property value or an "
            "invalid circuit name is rejected and nothing changes. Hand edits made in the window "
            "are picked up automatically before the next tool call. Use apply_edits to draw "
            "several components and wires as one smooth step. "
            "Understand circuits through data, not screenshots: describe_component gives a "
            "type's exact ports, box and properties before placing it; connect_ports wires ports "
            "by name ('G1.in2', 'U1.pin13', 'A') and can never short another net; inspect_circuit "
            "gives the full netlist with live values and problems; view_circuit draws the layout "
            "as text; diagnose_circuit lists problems; simulate_circuit returns truth tables. "
            "After drawing, run diagnose_circuit and simulate_circuit to prove the design works. "
            "Lay components out in clear left-to-right logic stages with generous spacing. Prefer "
            "connect_wire_smart over raw segments: minimize overlapping wires, device crossings, "
            "I/O-axis congestion, total crossings, and unnecessary bends. Run analyze_layout before "
            "the final save and improve avoidable warnings. Every save creates a backup and marks "
            "the window as saved. Finish with save_and_open_in_logisim. "
            "Never claim a circuit passed simulation unless run_test_vector reports passed=true."
        ),
        host=host,
        port=port,
        streamable_http_path="/mcp",
        stateless_http=False,
        json_response=False,
    )

    def edit(
        label: str,
        change: Callable[[LogisimProject], Any],
        *,
        scope: list[str] | None = None,
        rename: tuple[str, str] | None = None,
    ) -> Any:
        return service.edit(label, change, scope=scope, rename=rename)

    @mcp.tool(
        title="Get bridge status",
        description=(
            "Report bridge configuration, the active project, whether it is live-bound to a "
            "Logisim window, and optionally probe the configured Logisim Evolution executable."
        ),
        annotations=READ_ONLY,
    )
    def get_bridge_status(probe_logisim: bool = False) -> dict[str, Any]:
        project = service.project
        result: dict[str, Any] = {
            "bridge_version": __version__,
            "allowed_root": str(service.policy.root),
            "active_project": service.policy.relative(project.path) if project else None,
            "unsaved_changes": project.dirty if project else False,
            "live_editing": bool(service.live and service.live.bound),
            "logisim_configured": runner.executable is not None,
            "logisim_executable": str(runner.executable) if runner.executable else None,
        }
        result["live_app"] = runner.live_status()
        if probe_logisim:
            result["logisim_probe"] = runner.probe()
        return result

    @mcp.tool(
        title="Open Logisim project",
        description=(
            "Open a .circ file beneath the configured project root. With show_in_app=true "
            "(default) it is also shown in the Logisim window, launching Logisim when it is "
            "closed, and later edits appear there live. If the window already holds unsaved hand "
            "edits for this file, the bridge starts from those."
        ),
        annotations=WRITE,
    )
    def open_project(path: str, show_in_app: bool = True) -> dict[str, Any]:
        return service.open_project(path, show_in_app=show_in_app)

    @mcp.tool(
        title="Create Logisim 5 project",
        description=(
            "Create and open a new native Logisim Evolution 5.0.0 .circ project beneath the "
            "allowlisted root and (by default) show it live in the Logisim window. Refuses to "
            "replace an existing file unless overwrite=true."
        ),
        annotations=WRITE,
    )
    def create_project(
        path: str, main_circuit: str = "main", overwrite: bool = False, show_in_app: bool = True
    ) -> dict[str, Any]:
        return service.create_project(
            path, main_circuit=main_circuit, overwrite=overwrite, show_in_app=show_in_app
        )

    @mcp.tool(
        title="Close Logisim project",
        description=(
            "Close the bridge's in-memory project. Unsaved edits are discarded and reported; the "
            "Logisim window is left as it is."
        ),
        annotations=DELETE,
    )
    def close_project() -> dict[str, Any]:
        return service.close_project()

    @mcp.tool(
        title="List circuits",
        description="List circuit names, main status, and component/wire counts in the open project.",
        annotations=READ_ONLY,
    )
    def list_circuits() -> list[dict[str, Any]]:
        return service.fresh_project().list_circuits()

    @mcp.tool(
        title="List Logisim libraries",
        description="List library indices and descriptions used by the open project.",
        annotations=READ_ONLY,
    )
    def list_libraries() -> list[dict[str, Any]]:
        return service.fresh_project().list_libraries()

    @mcp.tool(
        title="Read circuit",
        description=(
            "Read semantic components, properties, locations, and wires from one circuit, "
            "including hand edits made in the Logisim window."
        ),
        annotations=READ_ONLY,
    )
    def read_circuit(circuit_name: str) -> dict[str, Any]:
        return service.fresh_project().read_circuit(circuit_name)

    @mcp.tool(
        title="Add circuit",
        description="Add an empty circuit to the open project and optionally make it the main circuit.",
        annotations=WRITE,
    )
    def add_circuit(circuit_name: str, set_as_main: bool = False) -> dict[str, Any]:
        return edit(
            f"MCP: add circuit {circuit_name}",
            lambda p: p.add_circuit(circuit_name, set_as_main=set_as_main),
            scope=[circuit_name],
        )

    @mcp.tool(
        title="Rename circuit",
        description=(
            "Rename a circuit and update its main-circuit setting and all native subcircuit references."
        ),
        annotations=WRITE,
    )
    def rename_circuit(circuit_name: str, new_name: str) -> dict[str, Any]:
        return edit(
            f"MCP: rename circuit {circuit_name}",
            lambda p: p.rename_circuit(circuit_name, new_name),
            rename=(circuit_name, new_name.strip()),
        )

    @mcp.tool(
        title="Delete circuit",
        description=(
            "Delete a non-final circuit. Referencing subcircuit components are rejected unless "
            "delete_references=true."
        ),
        annotations=DELETE,
    )
    def delete_circuit(circuit_name: str, delete_references: bool = False) -> dict[str, Any]:
        return edit(
            f"MCP: delete circuit {circuit_name}",
            lambda p: p.delete_circuit(circuit_name, delete_references=delete_references),
        )

    @mcp.tool(
        title="Set main circuit",
        description="Select the circuit Logisim should display and simulate as the project entry point.",
        annotations=WRITE,
    )
    def set_main_circuit(circuit_name: str) -> dict[str, Any]:
        return edit(
            f"MCP: set main circuit {circuit_name}",
            lambda p: p.set_main_circuit(circuit_name),
            scope=[],
        )

    @mcp.tool(
        title="Add component",
        description=(
            "Add a Logisim component by library index, component type, grid location, and properties. "
            "Example: component_name='Pin', library='0', location=[100,100]. Appears live in Logisim."
        ),
        annotations=WRITE,
    )
    def add_component(
        circuit_name: str,
        component_name: str,
        library: str,
        location: list[int],
        properties: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return edit(
            f"MCP: add {component_name}",
            lambda p: p.add_component(circuit_name, component_name, library, location, properties),
            scope=[circuit_name],
        )

    @mcp.tool(
        title="Update component",
        description="Set or remove semantic properties on one uniquely selected component.",
        annotations=WRITE,
    )
    def update_component(
        circuit_name: str,
        location: list[int],
        component_name: str | None = None,
        library: str | None = None,
        new_component_name: str | None = None,
        new_library: str | None = None,
        set_properties: dict[str, str] | None = None,
        remove_properties: list[str] | None = None,
    ) -> dict[str, Any]:
        return edit(
            f"MCP: update {component_name or 'component'}",
            lambda p: p.update_component(
                circuit_name,
                location,
                component_name=component_name,
                library=library,
                new_component_name=new_component_name,
                new_library=new_library,
                set_properties=set_properties,
                remove_properties=remove_properties,
            ),
            scope=[circuit_name],
        )

    @mcp.tool(
        title="Move component",
        description=(
            "Move one uniquely selected component. Wires remain unchanged unless "
            "move_exact_wire_endpoints=true; inspect the circuit after moving complex gates."
        ),
        annotations=WRITE,
    )
    def move_component(
        circuit_name: str,
        location: list[int],
        new_location: list[int],
        component_name: str | None = None,
        library: str | None = None,
        move_exact_wire_endpoints: bool = False,
    ) -> dict[str, Any]:
        return edit(
            f"MCP: move {component_name or 'component'}",
            lambda p: p.move_component(
                circuit_name,
                location,
                new_location,
                component_name=component_name,
                library=library,
                move_exact_wire_endpoints=move_exact_wire_endpoints,
            ),
            scope=[circuit_name],
        )

    @mcp.tool(
        title="Delete component",
        description=(
            "Delete one uniquely selected component. Attached wires are preserved unless "
            "remove_exact_endpoint_wires=true."
        ),
        annotations=DELETE,
    )
    def delete_component(
        circuit_name: str,
        location: list[int],
        component_name: str | None = None,
        library: str | None = None,
        remove_exact_endpoint_wires: bool = False,
    ) -> dict[str, Any]:
        return edit(
            f"MCP: delete {component_name or 'component'}",
            lambda p: p.delete_component(
                circuit_name,
                location,
                component_name=component_name,
                library=library,
                remove_exact_endpoint_wires=remove_exact_endpoint_wires,
            ),
            scope=[circuit_name],
        )

    @mcp.tool(
        title="Connect wire",
        description=(
            "Low-level operation that adds one exact straight segment. Prefer connect_wire_smart "
            "for finished circuit drawings."
        ),
        annotations=WRITE,
    )
    def connect_wire(circuit_name: str, start: list[int], end: list[int]) -> dict[str, Any]:
        return edit(
            "MCP: add wire",
            lambda p: p.connect(circuit_name, start, end),
            scope=[circuit_name],
        )

    @mcp.tool(
        title="Smart-route wire",
        description=(
            "Route a multi-segment orthogonal wire on the Logisim grid. Avoids component and IC "
            "bodies, heavily penalizes wire overlap, minimizes crossings and bends, and avoids "
            "crowding rows/columns near other I/O pins. Use this for normal circuit drawing."
        ),
        annotations=WRITE,
    )
    def connect_wire_smart(
        circuit_name: str,
        start: list[int],
        end: list[int],
        grid_step: int = 10,
        clearance: int = 10,
    ) -> dict[str, Any]:
        return edit(
            "MCP: route wire",
            lambda p: p.connect_smart(
                circuit_name,
                start,
                end,
                grid_step=grid_step,
                clearance=clearance,
                components=_route_components(service, p, circuit_name),
            ),
            scope=[circuit_name],
        )

    @mcp.tool(
        title="Disconnect wire",
        description="Remove the exact wire segment between two Logisim grid points.",
        annotations=DELETE,
    )
    def disconnect_wire(circuit_name: str, start: list[int], end: list[int]) -> dict[str, Any]:
        return edit(
            "MCP: remove wire",
            lambda p: p.disconnect(circuit_name, start, end),
            scope=[circuit_name],
        )

    @mcp.tool(
        title="Apply several edits",
        description=(
            "Apply an ordered list of edits to one circuit as a single step: it appears in the "
            "Logisim window at once and is one Ctrl+Z. connect_ports items take 'source' and "
            "'target' port references, e.g. {'action':'connect_ports','source':'A','target':'G1.in1'}. "
            "Each item has an 'action' "
            f"({', '.join(BATCH_ACTIONS)}) plus that tool's arguments except circuit_name, e.g. "
            "{'action':'add_component','component_name':'AND Gate','library':'1','location':[300,200]} "
            "or {'action':'connect_wire_smart','start':[200,200],'end':[260,190]}. If any item "
            "fails, nothing is changed."
        ),
        annotations=WRITE,
    )
    def apply_edits(
        circuit_name: str, operations: list[dict[str, Any]], label: str = "MCP: edits"
    ) -> dict[str, Any]:
        if not operations:
            raise ValueError("operations must not be empty")

        def run(project: LogisimProject) -> dict[str, Any]:
            results = []
            for index, step in enumerate(operations):
                try:
                    results.append(_run_batch_step(service, project, circuit_name, step))
                except KeyError as exc:
                    raise ValueError(f"operation {index}: missing argument {exc}") from None
                except Exception as exc:
                    raise type(exc)(f"operation {index} ({step.get('action')}): {exc}") from None
            return {"applied": len(results), "results": results}

        return edit(label, run, scope=[circuit_name])

    @mcp.tool(
        title="Show in Logisim",
        description=(
            "Bring the Logisim window to the front and switch it to the given circuit (or just "
            "focus it). Opens or launches Logisim first when the project is not shown yet."
        ),
        annotations=READ_ONLY,
    )
    def show_in_logisim(circuit_name: str | None = None) -> dict[str, Any]:
        with service._lock:
            project = service.require_project()
            if not (service.live and service.live.bound):
                if project.dirty:
                    raise ValueError(
                        "The project has unsaved edits that are not in a Logisim window; "
                        "call save_and_open_in_logisim instead"
                    )
                service.open_project(project.path, show_in_app=True)
            if circuit_name:
                service.require_project().get_circuit(circuit_name)
            return service.live.show(circuit_name)

    @mcp.tool(
        title="Sync from Logisim window",
        description=(
            "Pull the circuit exactly as it is in the Logisim window (hand edits, undo/redo) into "
            "the bridge. Normally automatic; use it to be explicit."
        ),
        annotations=READ_ONLY,
    )
    def sync_from_logisim() -> dict[str, Any]:
        with service._lock:
            project = service.require_project()
            if not (service.live and service.live.bound):
                return {"synced": False, "reason": "project is not live-bound to a Logisim window"}
            service.project = service.live.pull(service.runtime_dir, project.path)
            summary = service.project.summary()
            summary["synced"] = True
            return summary

    # ------------------------------------------------------------ understanding (v2.1)

    def _libraries_by_id() -> dict[str, str]:
        return {
            str(l["library"]): l["description"] for l in service.require_project().list_libraries()
        }

    def _lib_desc(library: str | None) -> str | None:
        if library in (None, ""):
            return None
        return _libraries_by_id().get(str(library), str(library))

    @mcp.tool(
        title="List component types",
        description=(
            "Catalog of every component Logisim offers in this project (built-in libraries, loaded "
            "libraries, and this project's circuits usable as subcircuits). Filter with query "
            "(e.g. 'flip', '74', 'mux') or library ('#Gates' or its index)."
        ),
        annotations=READ_ONLY,
    )
    def list_component_types(library: str | None = None, query: str | None = None) -> dict[str, Any]:
        live = service.live_session()
        result = live.catalog(_lib_desc(library), query)
        ids = {v: k for k, v in _libraries_by_id().items()}
        for lib in result["libraries"]:
            if lib["library"] in ids:
                lib["index"] = ids[lib["library"]]
        return result

    @mcp.tool(
        title="Describe component type",
        description=(
            "Ask Logisim for the exact shape of a component type, optionally with properties "
            "applied (e.g. {'inputs':'3','facing':'north'}): body bounds and every port with its "
            "name, aliases (pin13, in2, p0...), direction, bit width and offset from the component "
            "location, plus every property with its type, allowed options and default. Use it "
            "before placing a device so ports land exactly where wires will go."
        ),
        annotations=READ_ONLY,
    )
    def describe_component(
        library: str, component_name: str, properties: dict[str, str] | None = None
    ) -> dict[str, Any]:
        live = service.live_session()
        result = live.describe(_lib_desc(library), component_name, properties)
        return result

    @mcp.tool(
        title="Inspect circuit",
        description=(
            "Understand a circuit without a screenshot: every component with its exact box and "
            "absolute port coordinates, which net each port is on, every net with drivers, loads, "
            "bit width and current simulated value, and all problems (unconnected ports, floating "
            "or conflicting nets, several drivers, width mismatches, dangling wires, wires through "
            "devices, overlaps). Connectivity is computed exactly as Logisim connects wires. "
            "format='text' (compact, default) or 'json'."
        ),
        annotations=READ_ONLY,
    )
    def inspect_circuit(
        circuit_name: str,
        format: str = "text",
        include_properties: bool = False,
        include_values: bool = True,
    ) -> Any:
        live = service.live_session()
        data = live.inspect(circuit_name, values=include_values, attributes=include_properties)
        return data if format == "json" else netlist_text(data)

    @mcp.tool(
        title="View circuit layout as text",
        description=(
            "Draw the circuit as characters on the Logisim grid (1 char = scale units, default 10) "
            "with coordinate rulers: device boxes with names, wire shapes, connected junctions vs "
            "crossings that do NOT connect, and port markers (upper case = connected, lower case = "
            "unconnected). Use region=[x1,y1,x2,y2] to zoom into part of a large circuit."
        ),
        annotations=READ_ONLY,
    )
    def view_circuit(circuit_name: str, region: list[int] | None = None, scale: int = 10) -> str:
        live = service.live_session()
        return ascii_view(live.inspect(circuit_name, values=False), region=region, scale=scale)

    @mcp.tool(
        title="Diagnose circuits",
        description=(
            "List electrical and layout problems of one circuit, or of every circuit in the "
            "project when circuit_name is omitted."
        ),
        annotations=READ_ONLY,
    )
    def diagnose_circuit(circuit_name: str | None = None) -> str:
        live = service.live_session()
        names = [circuit_name] if circuit_name else service.require_project().circuit_names()
        return "\n\n".join(problems_text(live.inspect(n)) for n in names)

    @mcp.tool(
        title="Simulate circuit",
        description=(
            "Run the circuit in Logisim's simulator (a private copy; the window is not disturbed) "
            "and return a table. Give inputs={'A':1,'B':'0101'} for one row, rows=[{...},{...}] "
            "for several, or all_combinations=true (optionally with inputs=['A','B'] to choose "
            "the order) for a full truth table. Pins are addressed by label. watch=['G1.out', "
            "'U2.pin6', [x,y]] also reports internal nets. sequential=true keeps state between rows "
            "and clock_cycles ticks every clock that many full cycles after applying each row."
        ),
        annotations=READ_ONLY,
    )
    def simulate_circuit(
        circuit_name: str,
        inputs: Any = None,
        rows: list[dict[str, Any]] | None = None,
        all_combinations: bool = False,
        outputs: list[str] | None = None,
        watch: list[Any] | None = None,
        sequential: bool = False,
        clock_cycles: int = 0,
        max_rows: int = 1024,
        format: str = "text",
    ) -> Any:
        live = service.live_session()
        spec: dict[str, Any] = {
            "all_combinations": all_combinations,
            "sequential": sequential,
            "clock_cycles": clock_cycles,
            "max_rows": max_rows,
        }
        if rows is not None:
            spec["rows"] = rows
        if inputs is not None:
            spec["inputs"] = inputs
        if outputs:
            spec["outputs"] = outputs
        if watch:
            geometry = service.geometry(circuit_name)
            spec["watch"] = []
            for ref in watch:
                point = geometry.resolve(ref)
                name = (
                    f"{point['component']}.{point['port']}" if point.get("component") else f"{point['x']},{point['y']}"
                )
                spec["watch"].append({"name": name, "at": [point["x"], point["y"]]})
        result = live.simulate(circuit_name, spec)
        result["sequential"] = sequential
        return result if format == "json" else truth_table_text(result)

    @mcp.tool(
        title="Set inputs in the Logisim window",
        description=(
            "Drive input pins (by label) in the window's own simulation so the user sees the "
            "values and the resulting wire colours, e.g. values={'A':1,'B':0}."
        ),
        annotations=WRITE,
    )
    def set_inputs_in_window(circuit_name: str, values: dict[str, Any]) -> dict[str, Any]:
        live = service.live_session()
        return live.drive(circuit_name, values)

    @mcp.tool(
        title="Connect ports",
        description=(
            "Wire two ports by name, using Logisim's exact port positions and device bodies: "
            "source/target like 'G1.out', 'U1.pin13', 'AND Gate@300,150.in2', a one-port device "
            "label such as 'A', {'component':'G1','port':'in2'}, or a raw point [x,y] (e.g. an "
            "existing wire to tap). The route never touches other ports or wire ends and never "
            "runs along or bends on another wire, so it cannot short nets by accident."
        ),
        annotations=WRITE,
    )
    def connect_ports(
        circuit_name: str, source: Any, target: Any, clearance: int = 10
    ) -> dict[str, Any]:
        service.live_session()
        return edit(
            f"MCP: connect {source} to {target}",
            lambda p: _connect_ports(service, p, circuit_name, source, target, clearance=clearance),
            scope=[circuit_name],
        )

    @mcp.tool(
        title="Validate project",
        description="Check XML structure and Logisim project invariants without saving.",
        annotations=READ_ONLY,
    )
    def validate_project() -> dict[str, Any]:
        service.fresh_project()
        return service.validate()

    @mcp.tool(
        title="Analyze circuit layout",
        description=(
            "Score schematic readability and report component overlaps, wires through devices, "
            "overlapping wire segments, crossings, and non-orthogonal wires."
        ),
        annotations=READ_ONLY,
    )
    def analyze_layout(circuit_name: str) -> dict[str, Any]:
        project = service.fresh_project()
        return project.analyze_layout(
            circuit_name, _route_components(service, project, circuit_name)
        )

    @mcp.tool(
        title="Validate with Logisim",
        description=(
            "Load and round-trip the saved project through Logisim Evolution 5.0.0's own XML "
            "reader/writer. Save pending edits first."
        ),
        annotations=READ_ONLY,
    )
    def validate_with_logisim(timeout_seconds: int = 60) -> dict[str, Any]:
        project = service.require_project()
        if project.dirty:
            raise ValueError("Save or discard in-memory edits before Logisim validation")
        return runner.validate_project_file(project.path, timeout_seconds=timeout_seconds)

    @mcp.tool(
        title="Save project",
        description=(
            "Validate, create a timestamped backup, and atomically save the open project. The "
            "live Logisim window is checked against the file and marked as saved (no reload, "
            "undo history kept)."
        ),
        annotations=WRITE,
    )
    def save_project() -> dict[str, Any]:
        return service.save()

    @mcp.tool(
        title="Save and open in Logisim",
        description=(
            "Final step: save pending edits, verify the file with Logisim's own loader, and show "
            "the project in the Logisim window with no dialogs. A live window is simply brought "
            "to the front; otherwise the project is opened in the running Logisim, or Logisim is "
            "launched with it. Set force_reload=true only when the user agreed to discard "
            "unsaved hand edits in a window that is not live-bound."
        ),
        annotations=WRITE,
    )
    def save_and_open_in_logisim(force_reload: bool = False) -> dict[str, Any]:
        with service._lock:
            project = service.fresh_project()
            project.assert_valid()
            if project.dirty:
                save_result = service.save()
            else:
                save_result = {
                    "saved": False,
                    "path": service.policy.relative(project.path),
                    "reason": "project already matches the on-disk file",
                }
            project = service.require_project()
            logisim_validation = runner.validate_project_file(project.path)
            if not logisim_validation["valid"]:
                raise ValueError(
                    "The saved project did not pass Logisim Evolution's native loader; "
                    "the application was not opened"
                )
            layout_reports = {
                name: project.analyze_layout(name) for name in project.circuit_names()
            }
            window = None
            if service.live is not None and service.live.bound:
                try:
                    shown = service.live.show(None)
                    window = {"opened": True, "mode": "live_window", **shown}
                except (LiveNotOpen, LiveAppUnavailable):
                    service.live.unbind()  # closed meanwhile: open it again below
            if window is None:
                window = runner.open_project(project.path, force_reload=force_reload)
                if service.live is not None:
                    service.live.bind(project.path)
                    window["live_editing"] = service.live.bound
            return {
                "save": save_result,
                "layout": layout_reports,
                "logisim_validation": logisim_validation,
                "logisim": window,
            }

    @mcp.tool(
        title="Create backup",
        description="Create a timestamped backup of the current on-disk .circ file.",
        annotations=WRITE,
    )
    def create_backup(reason: str = "manual") -> dict[str, Any]:
        return service.create_backup(reason)

    @mcp.tool(
        title="List backups",
        description="List bridge-created backups for the open project, newest first.",
        annotations=READ_ONLY,
    )
    def list_backups() -> list[dict[str, Any]]:
        return service.list_backups()

    @mcp.tool(
        title="Rollback project",
        description=(
            "Restore the open project from a listed bridge backup. The current file is backed up "
            "first, and an open Logisim window is reloaded from the restored file."
        ),
        annotations=DELETE,
    )
    def rollback_project(backup_path: str) -> dict[str, Any]:
        return service.rollback(backup_path)

    @mcp.tool(
        title="Run Logisim test vector",
        description=(
            "Run Logisim Evolution --test-vector for a saved circuit and an allowlisted vector file."
        ),
        annotations=READ_ONLY,
    )
    def run_test_vector(
        circuit_name: str, vector_file: str, timeout_seconds: int = 120
    ) -> dict[str, Any]:
        project = service.require_project()
        if project.dirty:
            raise ValueError("Save or discard in-memory edits before running Logisim")
        project.get_circuit(circuit_name)
        return runner.run_test_vector(
            project.path, circuit_name, vector_file, timeout_seconds=timeout_seconds
        )

    # Exposed for the CLI and tests, not as an MCP tool.
    mcp._logisim_service = service  # type: ignore[attr-defined]
    mcp._logisim_runner = runner  # type: ignore[attr-defined]
    return mcp
