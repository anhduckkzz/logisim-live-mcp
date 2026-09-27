"""Real end-to-end test of v2 live editing against a running Logisim GUI.

Needs LOGISIM_EVOLUTION (the Logisim JAR) and a display (DISPLAY on Linux, e.g. Xvfb).
"""

import asyncio
import os
import time
from pathlib import Path

import pytest

from logisim_mcp.server import create_server

pytestmark = pytest.mark.skipif(
    not os.environ.get("LOGISIM_EVOLUTION") or not os.environ.get("DISPLAY"),
    reason="Set LOGISIM_EVOLUTION and DISPLAY to run the real live-editing GUI test",
)


def _call(server, name, **args):
    result = asyncio.run(server.call_tool(name, args))
    out = result[1] if isinstance(result, tuple) else result
    if isinstance(out, dict) and set(out) == {"result"}:
        out = out["result"]
    return out


def _user_presses_ctrl_z(display: str) -> bool:
    try:
        from Xlib import X, XK, display as xdisplay
        from Xlib.ext import xtest
    except ImportError:
        return False
    d = xdisplay.Display(display)
    xtest.fake_input(d, X.MotionNotify, x=500, y=600)
    xtest.fake_input(d, X.ButtonPress, 1)
    xtest.fake_input(d, X.ButtonRelease, 1)
    d.sync()
    time.sleep(0.3)
    ctrl = d.keysym_to_keycode(XK.string_to_keysym("Control_L"))
    z = d.keysym_to_keycode(XK.string_to_keysym("z"))
    for code, kind in ((ctrl, X.KeyPress), (z, X.KeyPress), (z, X.KeyRelease), (ctrl, X.KeyRelease)):
        xtest.fake_input(d, kind, code)
    d.sync()
    time.sleep(0.8)
    return True


def test_live_editing_round_trip(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    (root / "and.txt").write_text("A B Y\n0 0 0\n0 1 0\n1 0 0\n1 1 1\n", encoding="utf-8")
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", f"-Duser.home={home}")
    server = create_server(root)
    runner = server._logisim_runner
    pid = None
    try:
        created = _call(server, "create_project", path="demo.circ")
        window = created["save"]["logisim_window"]
        assert window["live_editing"] is True
        pid = window["process_id"]

        drawn = _call(
            server,
            "apply_edits",
            circuit_name="main",
            operations=[
                {"action": "add_component", "component_name": "Pin", "library": "0",
                 "location": [100, 100], "properties": {"label": "A"}},
                {"action": "add_component", "component_name": "Pin", "library": "0",
                 "location": [100, 200], "properties": {"label": "B"}},
                {"action": "add_component", "component_name": "AND Gate", "library": "1",
                 "location": [300, 150]},
                {"action": "add_component", "component_name": "Pin", "library": "0",
                 "location": [420, 150],
                 "properties": {"label": "Y", "facing": "west", "type": "output"}},
                {"action": "connect_wire_smart", "start": [100, 100], "end": [250, 130]},
                {"action": "connect_wire_smart", "start": [100, 200], "end": [250, 170]},
                {"action": "connect_wire_smart", "start": [300, 150], "end": [420, 150]},
            ],
        )
        assert drawn["logisim_window"] == {"mirrored": True}

        # Logisim itself rejects bad edits, and the bridge stays unchanged.
        with pytest.raises(Exception, match="does not exist"):
            _call(server, "add_component", circuit_name="main", component_name="AND Gatee",
                  library="1", location=[600, 600])
        assert len(_call(server, "read_circuit", circuit_name="main")["components"]) == 4

        extra = _call(server, "add_component", circuit_name="main", component_name="Pin",
                      library="0", location=[100, 300], properties={"label": "C"})
        assert extra["logisim_window"]["mirrored"] is True

        if _user_presses_ctrl_z(os.environ["DISPLAY"]):
            labels = {
                c["properties"].get("label")
                for c in _call(server, "read_circuit", circuit_name="main")["components"]
            }
            assert "C" not in labels  # the user's undo in the window was pulled back

        saved = _call(server, "save_project")
        assert saved["logisim_window"]["method"] == "verified_in_place"
        status = runner.live.ping()
        entry = next(p for p in status["projects"] if p["path"].endswith("demo.circ"))
        assert entry["dirty"] is False  # the window shows the project as saved

        result = _call(server, "run_test_vector", circuit_name="main", vector_file="and.txt")
        assert result["passed"] is True

        final = _call(server, "save_and_open_in_logisim")
        assert final["logisim"]["mode"] == "live_window"
        assert runner.live.ping()["pid"] == pid
        assert not list(root.glob(".*.autosave"))
    finally:
        if pid:
            try:
                os.kill(pid, 9)
            except OSError:
                pass
