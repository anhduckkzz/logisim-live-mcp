from pathlib import Path

import pytest
from lxml import etree

from logisim_mcp.errors import AmbiguousComponentError
from logisim_mcp.project import LogisimProject


FIXTURE = Path(__file__).parent / "fixtures" / "sample.circ"


@pytest.fixture
def project(tmp_path: Path) -> LogisimProject:
    path = tmp_path / "sample.circ"
    path.write_bytes(FIXTURE.read_bytes())
    return LogisimProject.load(path)


def test_lists_and_reads_circuits(project: LogisimProject) -> None:
    assert project.main_circuit_name() == "main"
    assert [c["name"] for c in project.list_circuits()] == ["main", "helper"]
    main = project.read_circuit("main")
    assert len(main["components"]) == 2
    assert main["components"][0]["properties"]["label"] == "A"
    assert main["wires"] == [{"from": "(100,100)", "to": "(200,100)"}]
    assert project.list_libraries()[1]["description"] == "#Gates"


def test_component_crud_and_wires(project: LogisimProject) -> None:
    created = project.add_component(
        "main", "AND Gate", "1", [150, 150], {"inputs": "3", "label": "G1"}
    )
    assert created["location"] == "(150,150)"
    updated = project.update_component(
        "main",
        [150, 150],
        component_name="AND Gate",
        set_properties={"label": "AND1", "facing": "west"},
        remove_properties=["inputs"],
    )
    assert updated["properties"] == {"label": "AND1", "facing": "west"}
    moved = project.move_component(
        "main", [150, 150], [170, 150], component_name="AND Gate"
    )
    assert moved["location"] == "(170,150)"
    assert project.connect("main", [100, 120], [170, 120])["created"] is True
    assert project.connect("main", [170, 120], [100, 120])["created"] is False
    assert project.disconnect("main", [170, 120], [100, 120])["removed"] == 1
    deleted = project.delete_component(
        "main", [170, 150], component_name="AND Gate"
    )
    assert deleted["name"] == "AND Gate"
    assert project.dirty
    assert not [issue for issue in project.validate() if issue.severity == "error"]


def test_project_smart_connect_creates_clean_segmented_route(project: LogisimProject) -> None:
    project.add_component("main", "AND Gate", "1", [160, 100])
    routed = project.connect_smart("main", [20, 100], [260, 100])
    assert routed["segment_count"] >= 3
    assert routed["overlap_length"] == 0
    assert len(routed["created_segments"]) == routed["segment_count"]
    report = project.analyze_layout("main")
    assert report["circuit"] == "main"


def test_ambiguous_selector_is_rejected(project: LogisimProject) -> None:
    project.add_component("main", "Probe", "0", [100, 100])
    with pytest.raises(AmbiguousComponentError):
        project.find_component("main", [100, 100])
    assert project.find_component("main", [100, 100], component_name="Pin").get("name") == "Pin"


def test_preserves_unknown_structure_and_comments(project: LogisimProject) -> None:
    project.update_component("main", [100, 100], set_properties={"label": "INPUT"})
    data = project.serialize()
    assert b"preservation marker" in data
    assert b"gateUndefined" in data
    etree.fromstring(data)


def test_validation_finds_bad_wire(project: LogisimProject) -> None:
    circuit = project.get_circuit("main")
    etree.SubElement(circuit, "wire", **{"from": "oops", "to": "(1,2)"})
    issues = project.validate()
    assert any(issue.code == "bad-wire" and issue.severity == "error" for issue in issues)


def test_create_v5_project_and_manage_circuits(tmp_path: Path) -> None:
    created = LogisimProject.create(tmp_path / "new.circ", "main")
    assert created.root.get("source") == "5.0.0"
    assert created.main_circuit_name() == "main"
    assert created.list_libraries()[0] == {"library": "0", "description": "#Wiring", "properties": {}}
    created.add_circuit("helper")
    created.add_component("main", "helper", "", [200, 100])
    renamed = created.rename_circuit("helper", "logic")
    assert renamed["updated_subcircuit_references"] == 1
    assert created.find_component("main", [200, 100]).get("name") == "logic"
    with pytest.raises(ValueError, match="used by"):
        created.delete_circuit("logic")
    deleted = created.delete_circuit("logic", delete_references=True)
    assert deleted["deleted_subcircuit_references"] == 1
    assert created.circuit_names() == ["main"]
