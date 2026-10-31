"""Real GUI test of the 2.2 features against a running Logisim Evolution window."""

import os
from pathlib import Path

import pytest

from logisim_mcp.server import create_server
from test_live_gui import _call

pytestmark = pytest.mark.skipif(
    not os.environ.get("LOGISIM_EVOLUTION") or not os.environ.get("DISPLAY"),
    reason="Set LOGISIM_EVOLUTION and DISPLAY to run the real GUI test",
)


def _text(result):
    if isinstance(result, list):
        return "\n".join(getattr(item, "text", str(item)) for item in result)
    return str(result)


def test_output_pin_route_removal_hints_export_and_save_as(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", f"-Duser.home={home}")
    server = create_server(root)
    pid = None
    try:
        created = _call(server, "create_project", path="inv.circ")
        pid = created["save"]["logisim_window"]["process_id"]
        ops = [
            {"action": "add_component", "component_name": "Pin", "library": "0",
             "location": [100, 100], "properties": {"label": "A"}},
            {"action": "add_component", "component_name": "NOT Gate", "library": "1",
             "location": [260, 100], "properties": {"label": "N1"}},
            # no facing given: the bridge must default an output pin to west
            {"action": "add_component", "component_name": "Pin", "library": "0",
             "location": [400, 100], "properties": {"label": "Y", "type": "output"}},
        ]
        _call(server, "apply_edits", circuit_name="main", operations=ops)
        read = _call(server, "read_circuit", circuit_name="main")
        out_pin = next(c for c in read["components"] if c["properties"].get("label") == "Y")
        assert out_pin["properties"]["facing"] == "west"

        _call(server, "connect_ports", circuit_name="main", source="A", target="N1.in")
        routed = _call(server, "connect_ports", circuit_name="main", source="N1.out", target="Y")
        assert routed["points"][0] != routed["points"][-1]
        assert "no problems" in _text(_call(server, "diagnose_circuit", circuit_name="main"))

        table = _call(server, "simulate_circuit", circuit_name="main", all_combinations=True, format="json")
        rows = table["rows"] if isinstance(table, dict) else __import__("json").loads(_text(table))["rows"]
        assert [(r["in"]["A"], r["out"]["Y"]) for r in rows] == [("0", "1"), ("1", "0")]

        with pytest.raises(Exception) as caught:
            _call(server, "simulate_circuit", circuit_name="main", inputs={"Q": 1})
        assert "input pins in main: A" in str(caught.value)
        assert "output pins: Y" in str(caught.value)

        svg = _call(server, "export_image", circuit_name="main", path="inv.svg")
        assert svg["exported"] is True
        assert (root / "inv.svg").read_text(encoding="utf-8").startswith("<svg")

        removed = _call(server, "disconnect_route", circuit_name="main", points=routed["points"])
        assert removed["not_found"] == [] and removed["removed"] == len(routed["points"]) - 1
        assert "unconnected_port" in _text(_call(server, "diagnose_circuit", circuit_name="main"))

        _call(server, "save_project")
        original = (root / "inv.circ").read_bytes()
        forked = _call(server, "save_project_as", path="inv2.circ")
        assert forked["path"] == "inv2.circ" and forked["original_file_unchanged"] is True
        assert (root / "inv.circ").read_bytes() == original
    finally:
        if pid:
            try:
                os.kill(pid, 9)
            except OSError:
                pass
