import os
from pathlib import Path
import shutil

import pytest

from logisim_mcp.runner import LogisimRunner
from logisim_mcp.service import ProjectService


FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.skipif(
    not os.environ.get("LOGISIM_EVOLUTION"),
    reason="Set LOGISIM_EVOLUTION to run the real Logisim integration test",
)
def test_edit_save_and_run_real_logisim(tmp_path: Path) -> None:
    shutil.copy2(FIXTURE_DIR / "sample.circ", tmp_path / "sample.circ")
    shutil.copy2(FIXTURE_DIR / "sample-vectors.txt", tmp_path / "sample-vectors.txt")
    service = ProjectService(tmp_path)
    service.open_project("sample.circ")
    service.require_project().update_component(
        "main", [100, 100], component_name="Pin", set_properties={"facing": "east"}
    )
    saved = service.save()
    assert saved["backup"] is not None
    result = LogisimRunner(service.policy).run_test_vector(
        service.require_project().path, "main", "sample-vectors.txt", timeout_seconds=60
    )
    assert result["passed"] is True, result
    assert "Passed: 2, Failed: 0" in result["stdout"]


@pytest.mark.skipif(
    not os.environ.get("LOGISIM_EVOLUTION"),
    reason="Set LOGISIM_EVOLUTION to run the real Logisim integration test",
)
def test_create_project_from_scratch_and_run_real_logisim(tmp_path: Path) -> None:
    service = ProjectService(tmp_path)
    service.create_project("native-not.circ")
    project = service.require_project()
    project.add_component("main", "Pin", "0", [100, 100], {"label": "A"})
    project.add_component("main", "NOT Gate", "1", [150, 100])
    project.add_component(
        "main", "Pin", "0", [200, 100], {"facing": "west", "type": "output", "label": "Y"}
    )
    project.connect("main", [100, 100], [120, 100])
    project.connect("main", [150, 100], [200, 100])
    service.save()
    native_validation = LogisimRunner(service.policy).validate_project_file(project.path)
    assert native_validation["valid"] is True, native_validation
    vector = tmp_path / "not-vectors.txt"
    vector.write_text("A Y\n0 1\n1 0\n", encoding="utf-8")
    result = LogisimRunner(service.policy).run_test_vector(
        project.path, "main", vector, timeout_seconds=60
    )
    assert result["passed"] is True, result
    assert "Passed: 2, Failed: 0" in result["stdout"]


@pytest.mark.skipif(
    not os.environ.get("LOGISIM_EVOLUTION"),
    reason="Set LOGISIM_EVOLUTION to run the real Logisim integration test",
)
def test_smart_routed_multistage_logic_runs_in_real_logisim(tmp_path: Path) -> None:
    service = ProjectService(tmp_path)
    service.create_project("clean-and-or.circ")
    project = service.require_project()
    for label, y in (("A", 80), ("B", 120), ("C", 180), ("D", 220)):
        project.add_component("main", "Pin", "0", [50, y], {"label": label})
    project.add_component("main", "AND Gate", "1", [200, 100])
    project.add_component("main", "AND Gate", "1", [200, 200])
    project.add_component("main", "OR Gate", "1", [350, 150])
    project.add_component(
        "main", "Pin", "0", [450, 150],
        {"facing": "west", "type": "output", "label": "Y"},
    )
    for start, end in (
        ([50, 80], [150, 80]),
        ([50, 120], [150, 120]),
        ([50, 180], [150, 180]),
        ([50, 220], [150, 220]),
        ([200, 100], [300, 130]),
        ([200, 200], [300, 170]),
        ([350, 150], [450, 150]),
    ):
        route = project.connect_smart("main", start, end)
        assert route["overlap_length"] == 0
    layout = project.analyze_layout("main")
    assert layout["clean"] is True
    assert layout["quality_score"] == 100
    service.save()
    vector = tmp_path / "and-or-vectors.txt"
    vector.write_text(
        "A B C D Y\n0 0 0 0 0\n1 1 0 0 1\n0 0 1 1 1\n1 0 1 0 0\n",
        encoding="utf-8",
    )
    runner = LogisimRunner(service.policy)
    assert runner.validate_project_file(project.path)["valid"] is True
    result = runner.run_test_vector(project.path, "main", vector, timeout_seconds=60)
    assert result["passed"] is True, result
    assert "Passed: 4, Failed: 0" in result["stdout"]
