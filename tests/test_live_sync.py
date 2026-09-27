import json
from pathlib import Path

import pytest

from logisim_mcp.errors import LogisimMcpError
from logisim_mcp.live import LiveAppClient
from logisim_mcp.live_sync import LiveSession, capture, diff_ops, expected_state
from logisim_mcp.project import LogisimProject
from logisim_mcp.runner import LogisimRunner
from logisim_mcp.security import PathPolicy
from logisim_mcp.service import ProjectService

from test_live import FakeAgent


def _project(tmp_path: Path) -> LogisimProject:
    project = LogisimProject.create(tmp_path / "d.circ", "main")
    project.add_component("main", "Pin", "0", [100, 100], {"label": "A"})
    project.connect("main", [100, 100], [150, 100])
    return project


def test_capture_maps_library_ids_to_descriptors(tmp_path: Path) -> None:
    snap = capture(_project(tmp_path))
    comp = snap["circuits"]["main"]["components"][0]
    assert comp == {"lib": "#Wiring", "name": "Pin", "loc": [100, 100], "props": {"label": "A"}}
    assert snap["circuits"]["main"]["wires"] == [[100, 100, 150, 100]]
    assert snap["main"] == "main" and snap["names"] == ["main"]


def test_diff_add_and_update_component(tmp_path: Path) -> None:
    project = _project(tmp_path)
    before = capture(project, ["main"])
    project.add_component("main", "AND Gate", "1", [300, 200])
    project.update_component("main", [100, 100], set_properties={"label": "B"})
    ops = diff_ops(before, capture(project, ["main"]))
    assert len(ops) == 1 and ops[0]["op"] == "edit"
    added = {(c["name"], tuple(c["loc"])) for c in ops[0]["add_components"]}
    assert added == {("AND Gate", (300, 200)), ("Pin", (100, 100))}
    assert ops[0]["remove_components"][0]["props"] == {"label": "A"}
    assert ops[0]["add_wires"] == [] and ops[0]["remove_wires"] == []


def test_diff_wires_ignore_direction(tmp_path: Path) -> None:
    project = _project(tmp_path)
    before = capture(project)
    project.disconnect("main", [100, 100], [150, 100])
    project.connect("main", [150, 100], [100, 100])
    assert diff_ops(before, capture(project)) == []


def test_diff_circuit_level_operations(tmp_path: Path) -> None:
    project = _project(tmp_path)
    project.add_circuit("sub")
    project.add_component("main", "sub", "", [400, 400])
    project.get_circuit("main")[-2].attrib.pop("lib")  # subcircuit instances have no lib
    before = capture(project)
    project.delete_circuit("sub", delete_references=True)
    ops = diff_ops(before, capture(project))
    assert [op["op"] for op in ops] == ["edit", "remove_circuit"]
    assert ops[0]["remove_components"][0]["lib"] is None

    before = capture(project)
    project.add_circuit("alu", set_as_main=True)
    ops = diff_ops(before, capture(project))
    assert [op["op"] for op in ops] == ["add_circuit", "set_main"]


def test_diff_rename_does_not_recreate_contents(tmp_path: Path) -> None:
    project = _project(tmp_path)
    before = capture(project)
    project.rename_circuit("main", "top")
    ops = diff_ops(before, capture(project), rename=("main", "top"))
    assert ops == [{"op": "rename_circuit", "from": "main", "to": "top"}]


def test_expected_state_lists_every_circuit(tmp_path: Path) -> None:
    project = _project(tmp_path)
    project.add_circuit("x")
    state = expected_state(project)
    assert [c["name"] for c in state["circuits"]] == ["main", "x"]


# ---------------------------------------------------------------- service + fake window


class FakeWindow:
    """Minimal stand-in for the Java plugin with STATUS/APPLY/EXPORT/SAVED."""

    def __init__(self, export_source: Path):
        self.external = 0
        self.dirty = False
        self.reject: str | None = None
        self.applied: list = []
        self.saved: list = []
        self.export_source = export_source
        self.agent = FakeAgent("tok", self.respond)

    def respond(self, parts):
        command = parts[0]
        status = {
            "open_in_app": True,
            "dirty": self.dirty,
            "revision": len(self.applied),
            "external_revision": self.external,
        }
        if command == "PING":
            return "OK\t" + json.dumps({"ready": True, "protocol": "2", "projects": []})
        if command == "STATUS":
            return "OK\t" + json.dumps(status)
        if command == "OPEN":
            return "OK\t" + json.dumps({**status, "action": "shown", "reloaded": False})
        if command == "APPLY":
            if int(parts[2]) != self.external:
                return f"ERR\tSTALE\t{self.external}"
            if self.reject:
                return f"ERR\tINVALID\t{self.reject}"
            self.applied.append((parts[3], json.loads(parts[4])))
            self.dirty = True
            return "OK\t" + json.dumps({**status, "dirty": True, "warnings": []})
        if command == "EXPORT":
            Path(parts[2]).write_bytes(self.export_source.read_bytes())
            return "OK\t" + json.dumps(status)
        if command == "SAVED":
            self.saved.append(json.loads(parts[2]))
            self.dirty = False
            return "OK\t" + json.dumps({**status, "dirty": False, "verified": True, "mismatches": []})
        if command == "SHOW":
            return "OK\t" + json.dumps(status)
        return "ERR\tBAD_REQUEST\tunknown"


@pytest.fixture()
def live_service(tmp_path: Path):
    project = _project(tmp_path)
    project.path.write_bytes(project.serialize())
    other = LogisimProject.load(project.path)
    other.add_component("main", "NOT Gate", "1", [500, 500])
    window_state = tmp_path / "window-state.xml"
    window_state.write_bytes(other.serialize())
    window = FakeWindow(window_state)
    jar = tmp_path / "logisim.jar"
    jar.write_bytes(b"x")
    runner = LogisimRunner(
        PathPolicy(tmp_path), jar, live_client=LiveAppClient(port=window.agent.port, token="tok")
    )
    service = ProjectService(tmp_path, live=LiveSession(runner))
    service.open_project("d.circ", show_in_app=True)
    yield service, window
    window.agent.close()


def test_open_binds_and_edits_are_mirrored(live_service) -> None:
    service, window = live_service
    assert service.live.bound
    result = service.edit(
        "MCP: add AND", lambda p: p.add_component("main", "AND Gate", "1", [300, 200]), scope=["main"]
    )
    assert result["logisim_window"] == {"mirrored": True}
    label, ops = window.applied[-1]
    assert label == "MCP: add AND"
    assert ops[0]["add_components"][0]["lib"] == "#Gates"


def test_rejected_edit_leaves_bridge_unchanged(live_service) -> None:
    service, window = live_service
    window.reject = "Component 'Bogus' does not exist in library #Gates"
    before = service.require_project().serialize()
    with pytest.raises(LogisimMcpError, match="does not exist"):
        service.edit("x", lambda p: p.add_component("main", "Bogus", "1", [1, 1]), scope=["main"])
    assert service.require_project().serialize() == before


def test_hand_edits_are_pulled_before_the_next_edit(live_service) -> None:
    service, window = live_service
    window.external = 3  # user edited the window
    window.dirty = True
    service.edit(
        "MCP: add AND", lambda p: p.add_component("main", "AND Gate", "1", [300, 200]), scope=["main"]
    )
    names = {c["name"] for c in service.require_project().read_circuit("main")["components"]}
    assert names == {"Pin", "NOT Gate", "AND Gate"}  # NOT Gate came from the window
    assert window.applied[-1][1][0]["add_components"][0]["name"] == "AND Gate"


def test_failed_batch_is_all_or_nothing_without_window(tmp_path: Path) -> None:
    project = _project(tmp_path)
    project.path.write_bytes(project.serialize())
    service = ProjectService(tmp_path)
    service.open_project("d.circ")
    before = service.require_project().serialize()

    def batch(p):
        p.add_component("main", "AND Gate", "1", [300, 200])
        p.delete_component("main", [999, 999])  # does not exist

    with pytest.raises(LogisimMcpError):
        service.edit("batch", batch)
    assert service.require_project().serialize() == before


def test_save_marks_window_clean_without_reload(live_service) -> None:
    service, window = live_service
    service.edit("add", lambda p: p.add_component("main", "AND Gate", "1", [300, 200]), scope=["main"])
    result = service.save()
    assert result["logisim_window"]["method"] == "verified_in_place"
    assert window.saved and not window.dirty
