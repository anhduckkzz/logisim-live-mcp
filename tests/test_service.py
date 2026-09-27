from pathlib import Path

import pytest
from lxml import etree

from logisim_mcp.errors import PathNotAllowedError, ValidationFailedError
from logisim_mcp.service import ProjectService


FIXTURE = Path(__file__).parent / "fixtures" / "sample.circ"


@pytest.fixture
def workspace(tmp_path: Path) -> tuple[ProjectService, Path]:
    path = tmp_path / "design.circ"
    path.write_bytes(FIXTURE.read_bytes())
    service = ProjectService(tmp_path)
    service.open_project("design.circ")
    return service, path


def test_path_escape_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.circ"
    outside.write_bytes(FIXTURE.read_bytes())
    service = ProjectService(root)
    with pytest.raises(PathNotAllowedError):
        service.open_project(outside)


def test_save_is_atomic_and_creates_backup(workspace: tuple[ProjectService, Path]) -> None:
    service, path = workspace
    before = path.read_bytes()
    service.require_project().update_component(
        "main", [100, 100], set_properties={"label": "CHANGED"}
    )
    result = service.save()
    assert result["saved"] is True
    assert result["backup"] is not None
    backup = service.policy.resolve(result["backup"]["backup"])
    assert backup.read_bytes() == before
    assert b"CHANGED" in path.read_bytes()
    assert not list(path.parent.glob(".design.circ.*.tmp"))


def test_invalid_project_is_not_saved(workspace: tuple[ProjectService, Path]) -> None:
    service, path = workspace
    before = path.read_bytes()
    service.require_project().get_circuit("main").append(
        etree.Element("wire", **{"from": "bad", "to": "(1,2)"})
    )
    with pytest.raises(ValidationFailedError):
        service.save()
    assert path.read_bytes() == before


def test_rollback_restores_and_safety_backs_up(workspace: tuple[ProjectService, Path]) -> None:
    service, path = workspace
    original = path.read_bytes()
    initial_backup = service.create_backup("baseline")
    service.require_project().update_component(
        "main", [100, 100], set_properties={"label": "CHANGED"}
    )
    service.save()
    result = service.rollback(initial_backup["backup"])
    assert result["rolled_back"] is True
    assert result["safety_backup"] is not None
    assert path.read_bytes() == original


def test_rollback_rejects_backup_for_another_project(
    workspace: tuple[ProjectService, Path], tmp_path: Path
) -> None:
    service, _ = workspace
    other = tmp_path / "other.circ"
    other.write_bytes(FIXTURE.read_bytes())
    other_service = ProjectService(tmp_path)
    other_service.open_project("other.circ")
    other_backup = other_service.create_backup("other")
    with pytest.raises(ValueError, match="currently open project"):
        service.rollback(other_backup["backup"])


def test_create_project_is_atomic_and_refuses_implicit_overwrite(tmp_path: Path) -> None:
    service = ProjectService(tmp_path)
    result = service.create_project("fresh.circ")
    assert result["created"] is True
    assert result["source"] == "5.0.0"
    assert (tmp_path / "fresh.circ").is_file()
    assert not list(tmp_path.glob(".fresh.circ.*.tmp"))
    with pytest.raises(FileExistsError):
        service.create_project("fresh.circ")
