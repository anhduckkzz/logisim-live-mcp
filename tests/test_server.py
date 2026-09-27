import asyncio
from pathlib import Path

from logisim_mcp.server import create_server


def test_server_advertises_semantic_tools(tmp_path: Path) -> None:
    server = create_server(tmp_path)
    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}
    assert {
        "get_bridge_status",
        "create_project",
        "open_project",
        "list_circuits",
        "read_circuit",
        "add_circuit",
        "rename_circuit",
        "delete_circuit",
        "set_main_circuit",
        "add_component",
        "update_component",
        "move_component",
        "delete_component",
        "connect_wire",
        "connect_wire_smart",
        "disconnect_wire",
        "analyze_layout",
        "validate_project",
        "validate_with_logisim",
        "save_project",
        "save_and_open_in_logisim",
        "create_backup",
        "list_backups",
        "rollback_project",
        "run_test_vector",
    } <= names
    assert next(t for t in tools if t.name == "read_circuit").annotations.readOnlyHint is True
    assert next(t for t in tools if t.name == "delete_component").annotations.destructiveHint is True
