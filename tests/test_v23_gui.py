"""Real GUI test of the 2.3 features: Buttons in simulation, Logisim-drawn images, timing diagram."""

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

PNG = b"\x89PNG\r\n\x1a\n"


def _json(result):
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        result = "\n".join(getattr(item, "text", str(item)) for item in result)
    return json.loads(result)


def _counter(server) -> None:
    """Synchronous counter 0 -> 2 -> 1 -> 3 with D flip-flops and a RESET push button."""
    ops = [
        {"action": "add_component", "component_name": "D Flip-Flop", "library": "4",
         "location": [300, 100], "properties": {"label": "FF1"}},
        {"action": "add_component", "component_name": "D Flip-Flop", "library": "4",
         "location": [300, 250], "properties": {"label": "FF0"}},
        {"action": "add_component", "component_name": "XOR Gate", "library": "1",
         "location": [260, 260], "properties": {"label": "G1"}},
        {"action": "add_component", "component_name": "Clock", "library": "0",
         "location": [120, 200], "properties": {"label": "CLK"}},
        {"action": "add_component", "component_name": "Button", "library": "5",
         "location": [120, 380], "properties": {"label": "RESET"}},
        # 'output': 'true' is the common spelling; the bridge turns it into type=output
        {"action": "add_component", "component_name": "Pin", "library": "0",
         "location": [480, 110], "properties": {"label": "Q1", "output": "true"}},
        {"action": "add_component", "component_name": "Pin", "library": "0",
         "location": [480, 260], "properties": {"label": "Q0", "output": "true"}},
    ]
    _call(server, "apply_edits", circuit_name="main", operations=ops)
    wires = [
        ("FF1.Q", "Q1"), ("FF0.Q", "Q0"), ("G1.out", "FF0.D"), ("FF1.Qn", "FF1.D"),
        ("CLK", "FF1.CLK"), ("CLK", "FF0.CLK"), ("RESET", "FF0.CLR"), ("RESET", "FF1.CLR"),
        ([400, 110], "G1.in1"), ([420, 260], "G1.in2"),
    ]
    _call(server, "apply_edits", circuit_name="main",
          operations=[{"action": "connect_ports", "source": a, "target": b} for a, b in wires])


def test_buttons_images_and_timing_diagram(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", f"-Duser.home={home}")
    server = create_server(root)
    pid = None
    try:
        # missing folders under the root are created
        created = _call(server, "create_project", path="lab5/ex2/counter.circ")
        pid = created["save"]["logisim_window"]["process_id"]
        assert created["created_directories"] == ["lab5", "lab5/ex2"]
        _counter(server)

        read = _call(server, "read_circuit", circuit_name="main")
        q1 = next(c for c in read["components"] if c["properties"].get("label") == "Q1")
        assert q1["properties"]["type"] == "output" and "output" not in q1["properties"]

        # update_component accepts 'properties' like add_component does
        _call(server, "update_component", circuit_name="main", location=[480, 260],
              component_name="Pin", properties={"labelloc": "east"})
        read = _call(server, "read_circuit", circuit_name="main")
        q0 = next(c for c in read["components"] if c["properties"].get("label") == "Q0")
        assert q0["properties"]["labelloc"] == "east"

        # a push Button is driven like an input pin: 1 = pressed
        rows = [{}, {}, {}, {}, {}, {"RESET": 1}, {"RESET": 0}, {}]
        table = _json(_call(server, "simulate_circuit", circuit_name="main", rows=rows,
                            sequential=True, clock_cycles=1, outputs=["Q1", "Q0"], format="json"))
        values = [int(r["out"]["Q1"] + r["out"]["Q0"], 2) for r in table["rows"]]
        assert values == [2, 1, 3, 0, 2, 0, 2, 1]
        assert "RESET" in table["inputs"]

        # the same Button can be pressed in the window
        pressed = _call(server, "set_inputs_in_window", circuit_name="main", values={"RESET": 1})
        assert pressed["set"] == {"RESET": "1"}
        _call(server, "set_inputs_in_window", circuit_name="main", values={"RESET": 0})

        # Logisim draws the circuit itself; folders are created on the way
        image = _call(server, "export_image", circuit_name="main", path="img/ex2_logic.png")
        assert image["renderer"] == "logisim" and image["created_directories"] == ["img"]
        data = (root / "img" / "ex2_logic.png").read_bytes()
        assert data.startswith(PNG) and image["width"] > 200 and image["height"] > 200
        with pytest.raises(Exception) as caught:
            _call(server, "export_image", circuit_name="main", path="img/ex2_logic.png")
        assert "overwrite" in str(caught.value)
        printed = _call(server, "export_image", circuit_name="main", path="img/ex2_print.gif",
                        format="gif", scale=1, printer_view=True)
        assert (root / "img" / "ex2_print.gif").read_bytes().startswith(b"GIF8")
        assert printed["width"] < image["width"]
        svg = _call(server, "export_image", circuit_name="main", path="img/ex2.svg")  # from the name
        assert svg["renderer"] == "logisim"
        assert "<svg" in (root / "img" / "ex2.svg").read_text(encoding="utf-8")[:400]
        bridge = _call(server, "export_image", circuit_name="main", path="img/bridge.svg",
                       format="svg", renderer="bridge")
        assert bridge["renderer"] == "bridge"

        # Logisim's own Timing diagram window, recorded while the counter runs
        steps = [
            {"clock_cycles": 6, "label": "count"},
            {"set": {"RESET": 1}, "clock_cycles": 1, "label": "reset held"},
            {"set": {"RESET": 0}, "clock_cycles": 3, "label": "count again"},
        ]
        timing = _call(server, "record_timing_diagram", circuit_name="main",
                       path="img/ex2_timing.png", steps=steps,
                       signals=["CLK", "RESET", "Q1", "Q0"])
        assert timing["signals"] == ["CLK", "RESET", "Q1", "Q0"]
        assert timing["ticks"] == 20
        assert (root / "img" / "ex2_timing.png").read_bytes().startswith(PNG)
        samples = {s["at"]: s["values"] for s in timing["samples"]}
        assert samples["start"]["Q1"] + samples["start"]["Q0"] == "00"
        assert samples["count"]["Q1"] + samples["count"]["Q0"] == "01"  # 0,2,1,3,0,2,1
        assert samples["reset held"]["RESET"] == "1"
        assert samples["reset held"]["Q1"] + samples["reset held"]["Q0"] == "00"
        assert samples["count again"]["Q1"] + samples["count again"]["Q0"] == "11"  # 2,1,3

        # without a window on screen and with Logisim's default signal selection
        quiet = _call(server, "record_timing_diagram", circuit_name="main",
                      path="img/ex2_timing_default.gif", format="gif", show=False,
                      steps=[{"clock_cycles": 2}])
        assert set(quiet["signals"]) >= {"CLK", "RESET", "Q1", "Q0"}
        assert (root / "img" / "ex2_timing_default.gif").read_bytes().startswith(b"GIF8")

        with pytest.raises(Exception) as caught:
            _call(server, "record_timing_diagram", circuit_name="main", path="img/bad.png",
                  steps=[{"clock_cycles": 1}], signals=["NOPE"])
        assert "labelled signals" in str(caught.value) and "RESET" in str(caught.value)

        saved_as = _call(server, "save_project_as", path="backup/copy/counter.circ")
        assert saved_as["created_directories"] == ["backup", "backup/copy"]
    finally:
        if pid:
            try:
                os.kill(pid, 9)
            except OSError:
                pass
