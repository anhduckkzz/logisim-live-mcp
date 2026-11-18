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
        "disconnect_route",
        "save_project_as",
        "export_image",
    } <= names
    assert next(t for t in tools if t.name == "read_circuit").annotations.readOnlyHint is True
    assert next(t for t in tools if t.name == "delete_component").annotations.destructiveHint is True


class _FakeLive:
    """Stands in for LiveSession: records calls and serves canned INSPECT / error replies."""

    def __init__(self, data, simulate_error=None):
        self.data = data
        self.simulate_error = simulate_error

    def inspect(self, circuit, *, values=True, attributes=False):
        return self.data

    def simulate(self, circuit, spec):
        if self.simulate_error:
            raise self.simulate_error
        return {"circuit": circuit, "rows": [], "outputs": []}

    def drive(self, circuit, values):
        if self.simulate_error:
            raise self.simulate_error
        return {"driven": values}

    def image(self, circuit, dest, *, format, scale, printer_view):
        self.image_call = {"circuit": circuit, "format": format, "scale": scale,
                           "printer_view": printer_view}
        Path(dest).write_bytes(b"\x89PNG\r\n\x1a\nfake")
        return {"circuit": circuit, "width": 10, "height": 20, "bytes": 12}


def _fake_server(tmp_path: Path, fake: _FakeLive):
    (tmp_path / "design.circ").write_bytes(
        (Path(__file__).parent / "fixtures" / "sample.circ").read_bytes()
    )
    server = create_server(tmp_path)
    service = server._logisim_service
    service.open_project("design.circ")
    service.live_session = lambda: fake  # type: ignore[method-assign]
    return server, service


def _call(server, name, args):
    return asyncio.run(server.call_tool(name, args))


def test_unknown_pin_label_error_lists_the_available_pins(tmp_path: Path) -> None:
    import pytest

    from logisim_mcp.live_sync import LiveRejected
    from logisim_mcp.server import _pin_labels
    from tests.test_understanding import INSPECT

    data = {
        **INSPECT,
        "components": [
            *INSPECT["components"],
            {"id": "Pin@500,100", "label": "Y", "name": "Pin", "pin_type": "output", "ports": []},
        ],
    }
    assert _pin_labels(data) == (["A"], ["Y"])
    fake = _FakeLive(data, LiveRejected("No input pin labelled 'Q' in main"))
    server, _ = _fake_server(tmp_path, fake)
    with pytest.raises(Exception) as caught:
        _call(server, "simulate_circuit", {"circuit_name": "main", "inputs": {"Q": 1}})
    message = str(caught.value)
    assert "No input pin labelled 'Q'" in message
    assert "input pins in main: A" in message and "output pins: Y" in message
    with pytest.raises(Exception) as caught:
        _call(server, "set_inputs_in_window", {"circuit_name": "main", "values": {"Q": 1}})
    assert "input pins in main: A" in str(caught.value)


def test_other_live_rejections_pass_through_unchanged(tmp_path: Path) -> None:
    import pytest

    from logisim_mcp.live_sync import LiveRejected
    from tests.test_understanding import INSPECT

    fake = _FakeLive(INSPECT, LiveRejected("Circuit 'zzz' does not exist"))
    server, _ = _fake_server(tmp_path, fake)
    with pytest.raises(Exception) as caught:
        _call(server, "simulate_circuit", {"circuit_name": "zzz", "inputs": {"A": 1}})
    assert "does not exist" in str(caught.value)
    assert "Labelled input pins" not in str(caught.value)


def test_export_image_asks_logisim_to_draw_by_default(tmp_path: Path) -> None:
    from tests.test_understanding import INSPECT

    fake = _FakeLive(INSPECT)
    server, _ = _fake_server(tmp_path, fake)
    result = str(_call(server, "export_image", {"circuit_name": "main", "path": "pics/out.png"}))
    assert '"renderer": "logisim"' in result and "created_directories" in result
    assert fake.image_call == {"circuit": "main", "format": "png", "scale": 2.0, "printer_view": False}
    assert (tmp_path / "pics" / "out.png").read_bytes().startswith(b"\x89PNG")


def test_export_image_accepts_jpeg_extension(tmp_path: Path) -> None:
    from tests.test_understanding import INSPECT

    fake = _FakeLive(INSPECT)
    server, _ = _fake_server(tmp_path, fake)
    for name, fmt in (("a.jpeg", None), ("b.jpeg", "jpeg"), ("c.jpg", "jpg"), ("d.JPEG", None)):
        args = {"circuit_name": "main", "path": name}
        if fmt:
            args["format"] = fmt
        _call(server, "export_image", args)
        assert fake.image_call["format"] == "jpg"
        assert (tmp_path / name).is_file()


def test_export_image_writes_svg_and_respects_overwrite(tmp_path: Path) -> None:
    import pytest

    from tests.test_understanding import INSPECT

    server, _ = _fake_server(tmp_path, _FakeLive(INSPECT))
    bridge = {"renderer": "bridge"}
    result = _call(server, "export_image", {"circuit_name": "main", "path": "out.svg", **bridge})
    assert "out.svg" in str(result)
    written = (tmp_path / "out.svg").read_text(encoding="utf-8")
    assert written.startswith("<svg")
    with pytest.raises(Exception) as caught:
        _call(server, "export_image", {"circuit_name": "main", "path": "out.svg", **bridge})
    assert "overwrite" in str(caught.value)
    _call(server, "export_image", {"circuit_name": "main", "path": "out.svg", "overwrite": True, **bridge})
    with pytest.raises(Exception):
        _call(server, "export_image", {"circuit_name": "main", "path": "out.txt"})
    with pytest.raises(Exception):
        _call(server, "export_image", {"circuit_name": "main", "path": "../escape.svg"})


def test_batch_and_tool_disconnect_route(tmp_path: Path) -> None:
    from tests.test_understanding import INSPECT

    server, service = _fake_server(tmp_path, _FakeLive(INSPECT))
    project = service.require_project()
    project.connect("main", [0, 0], [100, 0])
    project.connect("main", [100, 0], [100, 50])
    _call(
        server,
        "apply_edits",
        {"circuit_name": "main", "operations": [{"action": "disconnect_route", "points": [[0, 0], [100, 0], [100, 50]]}]},
    )
    remaining = service.require_project().read_circuit("main")["wires"]
    assert {"from": "(0,0)", "to": "(100,0)"} not in remaining
    assert {"from": "(100,0)", "to": "(100,50)"} not in remaining
