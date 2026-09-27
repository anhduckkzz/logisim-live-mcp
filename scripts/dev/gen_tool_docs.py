"""Regenerate docs/tools.md from the MCP server's own tool list: python scripts/dev/gen_tool_docs.py"""

import asyncio
import tempfile
from pathlib import Path

from logisim_mcp.server import create_server

GROUPS = [
    ("Project", ["get_bridge_status", "create_project", "open_project", "close_project",
                 "list_circuits", "list_libraries", "save_project", "save_and_open_in_logisim",
                 "create_backup", "list_backups", "rollback_project"]),
    ("Understanding", ["list_component_types", "describe_component", "inspect_circuit",
                       "view_circuit", "diagnose_circuit", "read_circuit", "analyze_layout",
                       "validate_project", "validate_with_logisim"]),
    ("Editing (live)", ["add_circuit", "rename_circuit", "delete_circuit", "set_main_circuit",
                        "add_component", "update_component", "move_component", "delete_component",
                        "connect_ports", "connect_wire_smart", "connect_wire", "disconnect_wire",
                        "apply_edits"]),
    ("Simulation", ["simulate_circuit", "set_inputs_in_window", "run_test_vector"]),
    ("Window", ["show_in_logisim", "sync_from_logisim"]),
]


def main() -> None:
    with tempfile.TemporaryDirectory() as root:
        tools = {t.name: t for t in asyncio.run(create_server(root).list_tools())}
    lines = [
        "# Tool reference",
        "",
        "Generated from the server by `scripts/dev/gen_tool_docs.py`. "
        "`R` = read-only, `W` = writes, `D` = destructive (MCP annotations).",
        "",
    ]
    seen = set()
    for title, names in GROUPS:
        lines += [f"## {title}", ""]
        for name in names:
            tool = tools.get(name)
            if tool is None:
                continue
            seen.add(name)
            ann = tool.annotations
            kind = "D" if ann and ann.destructiveHint else ("R" if ann and ann.readOnlyHint else "W")
            props = (tool.inputSchema or {}).get("properties", {})
            required = set((tool.inputSchema or {}).get("required", []))
            params = ", ".join(
                f"`{p}`" + ("" if p in required else "?") for p in props
            ) or "none"
            lines += [f"### `{name}` ({kind})", "", tool.description or "", "", f"Parameters: {params}", ""]
    missing = sorted(set(tools) - seen)
    if missing:
        lines += ["## Other", ""] + [f"- `{n}`: {tools[n].description}" for n in missing] + [""]
    out = Path(__file__).resolve().parents[2] / "docs" / "tools.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out} ({len(tools)} tools)")


if __name__ == "__main__":
    main()
