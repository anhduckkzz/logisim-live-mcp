"""Unit tests of the 2.3 additions that need no Logisim."""

import asyncio
from pathlib import Path

import pytest

from logisim_mcp.errors import PathNotAllowedError
from logisim_mcp.project import LogisimProject, _pin_type_alias
from logisim_mcp.security import PathPolicy
from logisim_mcp.server import _pin_labels, _run_batch_step, create_server
from logisim_mcp.service import ProjectService


def test_pin_type_alias_accepts_output_and_input_flags() -> None:
    assert _pin_type_alias({"label": "Y", "output": "true"}) == {"label": "Y", "type": "output"}
    assert _pin_type_alias({"output": False}) == {"type": "input"}
    assert _pin_type_alias({"input": "yes"}) == {"type": "input"}
    # an explicit type wins and the stray flag is dropped
    assert _pin_type_alias({"type": "input", "output": "true"}) == {"type": "input"}
    assert _pin_type_alias({"label": "A"}) == {"label": "A"}


def test_add_component_translates_output_flag(tmp_path: Path) -> None:
    project = LogisimProject.create(tmp_path / "p.circ", "main")
    data = project.add_component("main", "Pin", "0", [100, 100], {"label": "Y", "output": "true"})
    assert data["properties"]["type"] == "output"
    assert data["properties"]["facing"] == "west"
    assert "output" not in data["properties"]


def test_batch_update_component_accepts_properties(tmp_path: Path) -> None:
    service = ProjectService(tmp_path)
    service.create_project("p.circ")
    project = service.require_project()
    project.add_component("main", "Pin", "0", [100, 100], {"label": "A"})
    _run_batch_step(service, project, "main", {
        "action": "update_component", "location": [100, 100], "properties": {"label": "B"},
    })
    pin = project.read_circuit("main")["components"][0]
    assert pin["properties"]["label"] == "B"


def test_ensure_parent_creates_folders_inside_root_only(tmp_path: Path) -> None:
    policy = PathPolicy(tmp_path)
    target = policy.resolve("a/b/c.png", must_exist=False)
    assert policy.ensure_parent(target) == ["a", "a/b"]
    assert (tmp_path / "a" / "b").is_dir()
    assert policy.ensure_parent(target) == []
    with pytest.raises(PathNotAllowedError):
        policy.resolve("../outside/x.png", must_exist=False)


def test_create_and_save_as_create_missing_folders(tmp_path: Path) -> None:
    service = ProjectService(tmp_path)
    created = service.create_project("lab/ex2/counter.circ")
    assert created["created_directories"] == ["lab", "lab/ex2"]
    assert (tmp_path / "lab" / "ex2" / "counter.circ").is_file()
    saved = service.save_project_as("copies/counter.circ")
    assert saved["created_directories"] == ["copies"]


def test_pin_labels_include_buttons() -> None:
    data = {"components": [
        {"name": "Pin", "label": "A", "pin_type": "input"},
        {"name": "Button", "label": "RESET"},
        {"name": "Pin", "label": "Y", "pin_type": "output"},
        {"name": "LED", "label": "L"},
    ]}
    assert _pin_labels(data) == (["A", "RESET"], ["Y"])


def test_new_tools_are_advertised(tmp_path: Path) -> None:
    tools = {t.name: t for t in asyncio.run(create_server(tmp_path).list_tools())}
    assert "record_timing_diagram" in tools
    export = tools["export_image"].inputSchema["properties"]
    assert {"renderer", "printer_view", "scale"} <= set(export)
    assert "properties" in tools["update_component"].inputSchema["properties"]


def test_record_timing_diagram_checks_steps_before_touching_logisim(tmp_path: Path) -> None:
    server = create_server(tmp_path)
    with pytest.raises(Exception) as caught:
        asyncio.run(server.call_tool("record_timing_diagram", {
            "circuit_name": "main", "path": "t.png", "steps": [{"cycles": 2}],
        }))
    assert "unknown keys" in str(caught.value)
    with pytest.raises(Exception) as caught:
        asyncio.run(server.call_tool("record_timing_diagram", {
            "circuit_name": "main", "path": "t.bmp", "steps": [{"clock_cycles": 1}], "format": "bmp",
        }))
    assert "format" in str(caught.value)
