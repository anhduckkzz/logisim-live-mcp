"""Client for the live plugin that runs inside the Logisim Evolution JVM.

The plugin (``java-plugin/``, shipped as ``plugin/logisim-mcp-live-plugin.jar``) is attached
with Java's standard ``-javaagent`` switch when the bridge launches Logisim. It is plain
local code: no AI model, no network access beyond a loopback-only port. The bridge uses that
port to open, edit and reload projects in the running application, the same way the Blender
MCP add-on lets its server drive an already open Blender.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
from pathlib import Path
from typing import Any

from .errors import LogisimMcpError

DEFAULT_LIVE_PORT = 51235
PLUGIN_JAR_NAME = "logisim-mcp-live-plugin.jar"


class LiveAppUnavailable(LogisimMcpError):
    """No live plugin answered on the configured port."""


class LiveAppError(LogisimMcpError):
    """The running Logisim application refused or failed a request."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def state_dir() -> Path:
    configured = os.environ.get("LOGISIM_MCP_STATE_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".logisim-mcp"


def default_plugin_jar() -> Path | None:
    configured = os.environ.get("LOGISIM_MCP_PLUGIN_JAR") or os.environ.get("LOGISIM_MCP_AGENT_JAR")
    candidate = (
        Path(configured).expanduser()
        if configured
        else Path(__file__).resolve().parent / "plugin" / PLUGIN_JAR_NAME
    )
    return candidate if candidate.is_file() else None


class LiveAppClient:
    """Talks to the plugin over a one-line, tab-separated loopback protocol."""

    def __init__(self, port: int | None = None, token: str | None = None):
        state = self._load_state()
        env_port = os.environ.get("LOGISIM_MCP_LIVE_PORT")
        self.port = int(port or env_port or state.get("port") or DEFAULT_LIVE_PORT)
        self.token = token or state.get("token") or secrets.token_urlsafe(24)
        if state.get("port") != self.port or state.get("token") != self.token:
            self._save_state()

    # The token is persisted so a restarted MCP server can still control a Logisim
    # window that an earlier server process launched.
    @staticmethod
    def _state_path() -> Path:
        return state_dir() / "live.json"

    def _load_state(self) -> dict[str, Any]:
        try:
            return json.loads(self._state_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_state(self) -> None:
        path = self._state_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"port": self.port, "token": self.token}, indent=2), encoding="utf-8"
            )
        except OSError:
            pass  # still usable for this process

    def request(self, command: str, *args: str, timeout: float = 5.0) -> dict[str, Any]:
        for value in (command, *args):
            if "\t" in value or "\n" in value or "\r" in value:
                raise ValueError("live-control arguments cannot contain tabs or newlines")
        line = "\t".join((self.token, command, *args)) + "\n"
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=min(timeout, 2.0)) as sock:
                sock.settimeout(timeout)
                sock.sendall(line.encode("utf-8"))
                chunks: list[bytes] = []
                while True:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    if chunk.endswith(b"\n"):
                        break
        except OSError as exc:
            raise LiveAppUnavailable(f"No Logisim live plugin on port {self.port}: {exc}") from exc
        response = b"".join(chunks).decode("utf-8", errors="replace").rstrip("\r\n")
        if response.startswith("OK\t"):
            try:
                return json.loads(response[3:])
            except ValueError as exc:
                raise LiveAppUnavailable(
                    f"Port {self.port} answered with an unexpected payload"
                ) from exc
        if response.startswith("ERR\t"):
            _, _, rest = response.partition("\t")
            code, _, message = rest.partition("\t")
            raise LiveAppError(code or "ERROR", message)
        raise LiveAppUnavailable(f"Port {self.port} is not a Logisim live plugin")

    def ping(self, timeout: float = 2.0) -> dict[str, Any] | None:
        """Return the plugin status, or None when nothing is listening."""
        try:
            return self.request("PING", timeout=timeout)
        except LiveAppUnavailable:
            return None

    def open(
        self, path: Path, *, force: bool = False, reload: bool = True, timeout: float = 60.0
    ) -> dict[str, Any]:
        return self.request(
            "OPEN", str(path), "1" if force else "0", "1" if reload else "0", timeout=timeout
        )

    def reload_if_open(
        self, path: Path, *, force: bool = False, timeout: float = 60.0
    ) -> dict[str, Any]:
        return self.request("RELOAD", str(path), "1" if force else "0", timeout=timeout)
