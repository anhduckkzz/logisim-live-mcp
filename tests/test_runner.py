from pathlib import Path

from logisim_mcp.runner import LogisimRunner
from logisim_mcp.security import PathPolicy


def test_jar_command_uses_documented_test_vector_syntax(tmp_path: Path) -> None:
    jar = tmp_path / "logisim-evolution.jar"
    jar.write_bytes(b"placeholder")
    project = tmp_path / "design.circ"
    vector = tmp_path / "vectors.txt"
    project.write_text("<project/>", encoding="utf-8")
    vector.write_text("A Y\n0 0\n", encoding="utf-8")
    runner = LogisimRunner(PathPolicy(tmp_path), jar, java_executable="java")
    assert runner.build_command("main", vector, project) == [
        "java",
        "-jar",
        str(jar),
        "--test-vector",
        "main",
        str(vector),
        str(project),
    ]


def test_output_cleaner_folds_java_preferences_noise() -> None:
    raw = (
        "useful line\n"
        "Sep 26 java.util.prefs.WindowsPreferences openKey\n"
        "WARNING: Could not open windows registry node x\n"
    )
    cleaned, count = LogisimRunner._clean_output(raw)
    assert cleaned == "useful line\n[suppressed 2 repetitive Java preferences warning lines]\n"
    assert count == 2


def test_build_open_command_loads_project_positionally(tmp_path: Path) -> None:
    jar = tmp_path / "logisim-evolution.jar"
    jar.write_bytes(b"placeholder")
    project = tmp_path / "design.circ"
    project.write_text("<project/>", encoding="utf-8")
    runner = LogisimRunner(PathPolicy(tmp_path), jar, java_executable="java")
    assert runner.build_open_command(project) == [
        "java",
        "-jar",
        str(jar),
        "--no-splash",
        str(project),
    ]
    assert runner.build_validation_command(project, tmp_path / "normalized.circ") == [
        "java",
        "-jar",
        str(jar),
        "--new-file-format",
        str(project),
        str(tmp_path / "normalized.circ"),
    ]
