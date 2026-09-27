"""Real GUI test of the v2.1 understanding tools: build a full adder by port names only."""

import json
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
    return result


def test_full_adder_by_port_names(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", f"-Duser.home={home}")
    server = create_server(root)
    pid = None
    try:
        created = _call(server, "create_project", path="fa.circ")
        pid = created["save"]["logisim_window"]["process_id"]

        xor = _call(server, "describe_component", library="1", component_name="XOR Gate")
        assert [p["name"] for p in xor["ports"]] == ["out", "in1", "in2"]
        assert {"name", "type", "value"} <= set(xor["properties"][0])
        chip = _call(server, "describe_component", library="#TTL", component_name="7408")
        assert any(p.get("pin") == 3 for p in chip["ports"])  # TTL pins carry their numbers

        pins = [("A", 100, 100, "input"), ("B", 100, 200, "input"), ("Cin", 100, 300, "input")]
        ops = [
            {"action": "add_component", "component_name": "Pin", "library": "0",
             "location": [x, y], "properties": {"label": label}}
            for label, x, y, _ in pins
        ]
        ops += [
            {"action": "add_component", "component_name": "XOR Gate", "library": "1",
             "location": [260, 130], "properties": {"label": "X1"}},
            {"action": "add_component", "component_name": "XOR Gate", "library": "1",
             "location": [420, 190], "properties": {"label": "X2"}},
            {"action": "add_component", "component_name": "AND Gate", "library": "1",
             "location": [260, 260], "properties": {"label": "N1"}},
            {"action": "add_component", "component_name": "AND Gate", "library": "1",
             "location": [420, 320], "properties": {"label": "N2"}},
            {"action": "add_component", "component_name": "OR Gate", "library": "1",
             "location": [560, 290], "properties": {"label": "O1"}},
            {"action": "add_component", "component_name": "Pin", "library": "0", "location": [660, 190],
             "properties": {"label": "S", "facing": "west", "type": "output"}},
            {"action": "add_component", "component_name": "Pin", "library": "0", "location": [660, 290],
             "properties": {"label": "Cout", "facing": "west", "type": "output"}},
        ]
        _call(server, "apply_edits", circuit_name="main", operations=ops)
        links = [
            ("A", "X1.in1"), ("B", "X1.in2"), ("X1.out", "X2.in1"), ("Cin", "X2.in2"),
            ("X2.out", "S"), ("O1.out", "Cout"), ("N1.out", "O1.in1"), ("N2.out", "O1.in2"),
            ("A", "N1.in1"), ("B", "N1.in2"), ("X1.out", "N2.in1"), ("Cin", "N2.in2"),
        ]
        wired = _call(
            server,
            "apply_edits",
            circuit_name="main",
            operations=[{"action": "connect_ports", "source": s, "target": t} for s, t in links],
        )
        assert wired["logisim_window"]["mirrored"] is True

        again = _call(server, "connect_ports", circuit_name="main", source="A", target="X1.in1")
        assert again.get("already_connected") is True

        assert "no problems" in _text(_call(server, "diagnose_circuit", circuit_name="main"))
        netlist = _text(_call(server, "inspect_circuit", circuit_name="main"))
        assert "UNCONNECTED" not in netlist and "NETS" in netlist
        view = _text(_call(server, "view_circuit", circuit_name="main"))
        assert "╔" in view and "legend" in view

        table = _call(server, "simulate_circuit", circuit_name="main", all_combinations=True, format="json")
        if isinstance(table, list):
            table = json.loads(_text(table))
        for row in table["rows"]:
            total = sum(int(row["in"][k]) for k in ("A", "B", "Cin"))
            assert row["out"] == {"S": str(total % 2), "Cout": str(total // 2)}

        with pytest.raises(Exception, match="bits"):
            _call(server, "simulate_circuit", circuit_name="main", all_combinations=True, max_rows=4)

        saved = _call(server, "save_project")
        assert saved["logisim_window"]["method"] == "verified_in_place"
    finally:
        if pid:
            try:
                os.kill(pid, 9)
            except OSError:
                pass


def test_clocked_toggle_flip_flop(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", f"-Duser.home={home}")
    server = create_server(root)
    pid = None
    try:
        created = _call(server, "create_project", path="toggle.circ")
        pid = created["save"]["logisim_window"]["process_id"]
        dff = _call(server, "describe_component", library="4", component_name="D Flip-Flop")
        assert [p["name"] for p in dff["ports"]] == ["D", "Clock", "Q", "Qn", "Clear", "Preset"]
        _call(server, "apply_edits", circuit_name="main", operations=[
            {"action": "add_component", "component_name": "Clock", "library": "0",
             "location": [150, 200], "properties": {"label": "CLK"}},
            {"action": "add_component", "component_name": "D Flip-Flop", "library": "4",
             "location": [300, 150], "properties": {"label": "FF"}},
            {"action": "add_component", "component_name": "Pin", "library": "0",
             "location": [500, 160], "properties": {"label": "Q", "facing": "west", "type": "output"}},
            {"action": "connect_ports", "source": "CLK", "target": "FF.CLK"},
            {"action": "connect_ports", "source": "FF.Q", "target": "Q"},
            {"action": "connect_ports", "source": "FF.Qn", "target": "FF.D"},
        ])
        report = _text(_call(server, "diagnose_circuit", circuit_name="main"))
        assert "warning" not in report  # open Clear/Preset are only informational
        table = _call(server, "simulate_circuit", circuit_name="main", rows=[{}, {}, {}, {}],
                      sequential=True, clock_cycles=1, format="json")
        if isinstance(table, list):
            table = json.loads(_text(table))
        assert [row["out"]["Q"] for row in table["rows"]] == ["1", "0", "1", "0"]
    finally:
        if pid:
            try:
                os.kill(pid, 9)
            except OSError:
                pass
