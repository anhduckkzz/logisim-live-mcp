import io
from contextlib import redirect_stdout

from logisim_mcp.cli import _print


def test_json_output_is_safe_for_legacy_windows_code_pages() -> None:
    output = io.StringIO()
    with redirect_stdout(output):
        _print({"logisim_output": "replacement: \ufffd"})
    encoded = output.getvalue().encode("cp1252")
    assert b"\\ufffd" in encoded
