import socket

import pytest


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(autouse=True)
def isolated_live_state(tmp_path_factory, monkeypatch):
    """Never touch the real ~/.logisim-mcp state or a real running Logisim from unit tests."""
    monkeypatch.setenv("LOGISIM_MCP_STATE_DIR", str(tmp_path_factory.mktemp("live-state")))
    monkeypatch.setenv("LOGISIM_MCP_LIVE_PORT", str(_free_port()))
