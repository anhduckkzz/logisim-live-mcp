import json
import os
import shutil
import socket
import threading
import time
from pathlib import Path

import pytest

from logisim_mcp.errors import LogisimMcpError
from logisim_mcp.live import LiveAppClient, LiveAppError, LiveAppUnavailable, default_plugin_jar
from logisim_mcp.runner import LogisimRunner
from logisim_mcp.security import PathPolicy

FIXTURE_DIR = Path(__file__).parent / "fixtures"


class FakeAgent:
    """Speaks the agent's line protocol so the Python side can be tested without Java."""

    def __init__(self, token: str, responder):
        self.token = token
        self.responder = responder
        self.requests: list[list[str]] = []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                data = b""
                while not data.endswith(b"\n"):
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                parts = data.decode().rstrip("\n").split("\t")
                self.requests.append(parts)
                if parts[0] != self.token:
                    reply = "ERR\tAUTH\tinvalid token"
                elif parts[1:2] == ["PING"]:
                    reply = 'OK\t{"ready":true,"protocol":"2","projects":[]}'
                else:
                    reply = self.responder(parts[1:])
                conn.sendall((reply + "\n").encode())

    def close(self) -> None:
        self.sock.close()


def _runner(tmp_path: Path, client: LiveAppClient) -> tuple[LogisimRunner, Path]:
    jar = tmp_path / "logisim-evolution.jar"
    jar.write_bytes(b"placeholder")
    agent = tmp_path / "agent.jar"
    agent.write_bytes(b"placeholder")
    project = tmp_path / "design.circ"
    project.write_text("<project/>", encoding="utf-8")
    runner = LogisimRunner(
        PathPolicy(tmp_path), jar, java_executable="java", live_client=client, plugin_jar=agent
    )
    return runner, project


def test_live_open_command_injects_agent_before_jar(tmp_path: Path) -> None:
    client = LiveAppClient(port=50001, token="secret")
    runner, project = _runner(tmp_path, client)
    command, env = runner.build_live_open_command(project)
    assert command == [
        "java",
        f"-javaagent:{tmp_path / 'agent.jar'}=port=50001",
        "-jar",
        str(tmp_path / "logisim-evolution.jar"),
        "--no-splash",
        str(project),
    ]
    assert env["LOGISIM_MCP_LIVE_TOKEN"] == "secret"
    assert env["LOGISIM_MCP_LAUNCH_FILE"] == str(project)
    assert "secret" not in " ".join(command)  # token never appears on the command line


def test_native_launcher_gets_agent_through_java_tool_options(tmp_path: Path) -> None:
    exe = tmp_path / "Logisim-evolution.exe"
    exe.write_bytes(b"placeholder")
    agent = tmp_path / "agent.jar"
    agent.write_bytes(b"x")
    project = tmp_path / "design.circ"
    project.write_text("<project/>", encoding="utf-8")
    runner = LogisimRunner(
        PathPolicy(tmp_path), exe, live_client=LiveAppClient(port=50002, token="t"), plugin_jar=agent
    )
    command, env = runner.build_live_open_command(project)
    assert command == [str(exe), "--no-splash", str(project)]
    assert f"-javaagent:{agent}=port=50002" in env["JAVA_TOOL_OPTIONS"]


def test_client_persists_token_for_later_server_processes() -> None:
    first = LiveAppClient()
    second = LiveAppClient()
    assert first.token == second.token
    assert first.port == second.port


def test_client_reports_unavailable_when_nothing_listens() -> None:
    client = LiveAppClient()
    assert client.ping(timeout=0.5) is None
    with pytest.raises(LiveAppUnavailable):
        client.request("PING", timeout=0.5)


def test_open_reuses_running_app_instead_of_launching(tmp_path: Path, monkeypatch) -> None:
    agent = FakeAgent(
        "tok",
        lambda parts: "OK\t"
        + json.dumps({"open_in_app": True, "reloaded": True, "archived_autosave": None}),
    )
    try:
        runner, project = _runner(tmp_path, LiveAppClient(port=agent.port, token="tok"))

        def no_launch(*args, **kwargs):
            raise AssertionError("must not start a second Logisim process")

        monkeypatch.setattr("subprocess.Popen", no_launch)
        result = runner.open_project(project)
        assert result["mode"] == "reloaded_in_running_app"
        assert agent.requests[-1] == ["tok", "OPEN", str(project.resolve()), "0", "1"]
    finally:
        agent.close()


def test_dirty_window_is_reported_not_overwritten(tmp_path: Path) -> None:
    agent = FakeAgent("tok", lambda parts: "ERR\tDIRTY\tunsaved GUI edits")
    try:
        runner, project = _runner(tmp_path, LiveAppClient(port=agent.port, token="tok"))
        with pytest.raises(LogisimMcpError, match="unsaved GUI edits"):
            runner.open_project(project)
    finally:
        agent.close()


def test_force_reload_is_forwarded(tmp_path: Path) -> None:
    agent = FakeAgent("tok", lambda parts: 'OK\t{"open_in_app":true,"reloaded":true}')
    try:
        runner, project = _runner(tmp_path, LiveAppClient(port=agent.port, token="tok"))
        runner.open_project(project, force_reload=True)
        assert agent.requests[-1][3] == "1"
    finally:
        agent.close()


def test_sync_running_app_is_best_effort(tmp_path: Path) -> None:
    runner, project = _runner(tmp_path, LiveAppClient())
    assert runner.sync_running_app(project)["synced"] is False
    agent = FakeAgent("tok", lambda parts: 'OK\t{"open_in_app":false,"reloaded":false}')
    try:
        runner._live = LiveAppClient(port=agent.port, token="tok")
        result = runner.sync_running_app(project)
        assert result["synced"] is True and agent.requests[-1][1] == "RELOAD"
    finally:
        agent.close()


def test_packaged_agent_jar_is_present() -> None:
    jar = default_plugin_jar()
    assert jar is not None and jar.name == "logisim-mcp-live-plugin.jar"


@pytest.mark.skipif(
    not os.environ.get("LOGISIM_EVOLUTION") or not os.environ.get("DISPLAY"),
    reason="Set LOGISIM_EVOLUTION and DISPLAY to run the real end-to-end GUI test",
)
def test_real_logisim_launch_then_reload_without_dialogs(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    # Leftovers that make stock Logisim show "save autosave" and "load autosave" dialogs.
    (home / ".logisim-unnamed-autosave_20260101000000.circ.autosave").write_text("<x/>")
    shutil.copy2(FIXTURE_DIR / "sample.circ", tmp_path / "sample.circ")
    (tmp_path / ".sample.circ.autosave").write_text("stale")
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", f"-Duser.home={home}")
    runner = LogisimRunner(PathPolicy(tmp_path))
    pid = None
    try:
        launched = runner.open_project(tmp_path / "sample.circ", wait_seconds=60)
        pid = launched["process_id"]
        assert launched["mode"] == "launched_app" and launched["live_control"] is True
        assert "warning" not in launched
        assert not (tmp_path / ".sample.circ.autosave").exists()
        assert not list(home.glob(".logisim-unnamed-autosave_*"))

        again = runner.open_project(tmp_path / "sample.circ")
        assert again["mode"] == "reloaded_in_running_app"
        assert runner.live.ping()["pid"] == pid  # same process, no second window
    finally:
        if pid:
            try:
                os.kill(pid, 9)
            except OSError:
                pass
            time.sleep(0.5)


def test_old_plugin_window_is_reported_clearly(tmp_path: Path) -> None:
    runner, project = _runner(tmp_path, LiveAppClient(port=1, token="tok"))
    runner.live.ping = lambda timeout=2.0: {"ready": True, "protocol": "1"}
    with pytest.raises(LogisimMcpError, match="older version"):
        runner.open_project(project)
