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


def test_repeated_identical_saves_do_not_pile_up_backups(
    workspace: tuple[ProjectService, Path],
) -> None:
    service, _ = workspace
    # The first save normalises the file's bytes; after that, saves change nothing on disk.
    service.save()
    service.save()
    settled = len(service.list_backups())
    third = service.save()
    fourth = service.save()
    assert third["backup"]["reused"] is True
    assert fourth["backup"]["reused"] is True
    assert len(service.list_backups()) == settled
    # A backup holds the file as it was before a save, so it only grows once a save replaces
    # content that was itself different from the newest backup.
    service.require_project().update_component("main", [100, 100], set_properties={"label": "X"})
    service.save()
    assert len(service.list_backups()) == settled
    service.require_project().update_component("main", [100, 100], set_properties={"label": "Y"})
    service.save()
    assert len(service.list_backups()) == settled + 1


def test_backup_retention_prunes_only_automatic_backups(
    workspace: tuple[ProjectService, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _ = workspace
    monkeypatch.setenv("LOGISIM_MCP_BACKUP_KEEP", "2")
    manual = service.create_backup("keep-me")
    for index in range(6):
        service.require_project().update_component(
            "main", [100, 100], set_properties={"label": f"V{index}"}
        )
        service.save()
    backups = service.list_backups()
    automatic = [b for b in backups if str(b.get("reason", "")).startswith("pre-")]
    assert len(automatic) == 2
    assert any(b["backup"] == manual["backup"] for b in backups)


def test_unlimited_retention_when_keep_is_zero(
    workspace: tuple[ProjectService, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _ = workspace
    monkeypatch.setenv("LOGISIM_MCP_BACKUP_KEEP", "0")
    for index in range(5):
        service.require_project().update_component(
            "main", [100, 100], set_properties={"label": f"V{index}"}
        )
        service.save()
    assert len(service.list_backups()) == 5


def test_open_project_reports_replaced_project_with_unsaved_edits(
    workspace: tuple[ProjectService, Path], tmp_path: Path
) -> None:
    service, _ = workspace
    other = tmp_path / "other.circ"
    other.write_bytes(FIXTURE.read_bytes())
    service.require_project().update_component("main", [100, 100], set_properties={"label": "DIRTY"})
    result = service.open_project("other.circ")
    assert result["previous_project"]["path"] == "design.circ"
    assert result["previous_project"]["had_unsaved_changes"] is True
    assert "warning" in result["previous_project"]
    clean = service.open_project("design.circ")
    assert clean["previous_project"]["had_unsaved_changes"] is False
    assert "warning" not in clean["previous_project"]


def test_first_open_has_no_previous_project(tmp_path: Path) -> None:
    (tmp_path / "design.circ").write_bytes(FIXTURE.read_bytes())
    result = ProjectService(tmp_path).open_project("design.circ")
    assert "previous_project" not in result


def test_save_project_as_forks_and_leaves_original_untouched(
    workspace: tuple[ProjectService, Path], tmp_path: Path
) -> None:
    service, original = workspace
    before = original.read_bytes()
    service.require_project().update_component("main", [100, 100], set_properties={"label": "FORK"})
    result = service.save_project_as("variant.circ")
    assert result["saved"] is True
    assert result["path"] == "variant.circ"
    assert result["previous_path"] == "design.circ"
    assert original.read_bytes() == before
    assert b"FORK" in (tmp_path / "variant.circ").read_bytes()
    assert service.require_project().path == (tmp_path / "variant.circ").resolve()
    assert service.require_project().dirty is False
    with pytest.raises(FileExistsError):
        service.save_project_as("design.circ")
    with pytest.raises(ValueError):
        service.save_project_as("variant.circ")
    assert service.save_project_as("design.circ", overwrite=True)["backup"] is not None
