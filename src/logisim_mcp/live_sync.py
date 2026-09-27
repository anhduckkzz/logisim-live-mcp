"""Mirror bridge edits into the running Logisim window (v2 live editing).

The bridge keeps its XML model as the source of truth for what is written to disk. Every
edit tool call is diffed against the model before the call, and the difference is sent to
the live plugin inside Logisim, which applies it as one ordinary, undoable Logisim action.
Hand edits made in the window (including Ctrl+Z) are detected through a revision counter
and pulled back into the bridge before the next edit, so neither side overwrites the other.
"""

from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .errors import LogisimMcpError
from .live import LiveAppError, LiveAppUnavailable
from .project import LogisimProject

_LOC = re.compile(r"^\((-?\d+),(-?\d+)\)$")


class LiveStale(LogisimMcpError):
    def __init__(self, external: int):
        super().__init__("The Logisim window changed since the bridge last synchronised")
        self.external = external


class LiveRejected(LogisimMcpError):
    """Logisim refused an edit (unknown component, bad property value, invalid name...)."""


class LiveNotOpen(LogisimMcpError):
    """The project is no longer open in the running Logisim window."""


def _xy(value: str | None) -> list[int]:
    match = _LOC.match(value or "")
    if not match:
        raise ValueError(f"Invalid Logisim location: {value!r}")
    return [int(match.group(1)), int(match.group(2))]


def capture(project: LogisimProject, only: Iterable[str] | None = None) -> dict[str, Any]:
    """Semantic snapshot: circuit names, main circuit, and (optionally scoped) contents."""
    libraries = {
        str(lib["library"]): lib["description"] for lib in project.list_libraries()
    }
    names = project.circuit_names()
    wanted = set(names) if only is None else {n for n in only if n in names}
    circuits: dict[str, dict[str, Any]] = {}
    for name in names:
        if name not in wanted:
            continue
        data = project.read_circuit(name)
        components = []
        for comp in data["components"]:
            lib_id = comp.get("library")
            components.append(
                {
                    "lib": libraries.get(str(lib_id), str(lib_id)) if lib_id not in (None, "") else None,
                    "name": comp["name"],
                    "loc": _xy(comp["location"]),
                    "props": dict(comp["properties"]),
                }
            )
        wires = []
        for wire in data["wires"]:
            try:
                a, b = _xy(wire["from"]), _xy(wire["to"])
            except ValueError:
                continue
            if a != b:
                wires.append(a + b)
        circuits[name] = {"components": components, "wires": wires}
    return {"main": project.main_circuit_name(), "names": names, "circuits": circuits}


def _comp_key(comp: dict[str, Any]) -> tuple:
    return (
        comp["lib"],
        comp["name"],
        comp["loc"][0],
        comp["loc"][1],
        tuple(sorted(comp["props"].items())),
    )


def _wire_key(wire: list[int]) -> tuple[int, int, int, int]:
    a, b = (wire[0], wire[1]), (wire[2], wire[3])
    first, second = sorted((a, b))
    return (*first, *second)


def _multiset_diff(before: list, after: list, key) -> tuple[list, list]:
    b = Counter(key(x) for x in before)
    a = Counter(key(x) for x in after)
    by_key_before = {key(x): x for x in before}
    by_key_after = {key(x): x for x in after}
    removed = [by_key_before[k] for k, n in (b - a).items() for _ in range(n)]
    added = [by_key_after[k] for k, n in (a - b).items() for _ in range(n)]
    return removed, added


def diff_ops(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    rename: tuple[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Ordered live operations that turn the ``before`` window state into ``after``."""
    ops: list[dict[str, Any]] = []
    before_names = list(before["names"])
    before_circuits = {name: data for name, data in before["circuits"].items()}
    if rename and rename[0] != rename[1]:
        old, new = rename
        ops.append({"op": "rename_circuit", "from": old, "to": new})
        before_names = [new if n == old else n for n in before_names]
        if old in before_circuits:
            before_circuits[new] = before_circuits.pop(old)
        # Logisim renames subcircuit instances by itself; mirror that in the old snapshot.
        for data in before_circuits.values():
            for comp in data["components"]:
                if comp["lib"] is None and comp["name"] == old:
                    comp["name"] = new

    for name in after["names"]:
        if name not in before_names:
            ops.append({"op": "add_circuit", "name": name})

    empty = {"components": [], "wires": []}
    for name, data in after["circuits"].items():
        previous = before_circuits.get(name, empty if name not in before_names else None)
        if previous is None:
            continue  # not captured before; nothing reliable to diff against
        removed_c, added_c = _multiset_diff(previous["components"], data["components"], _comp_key)
        removed_w, added_w = _multiset_diff(previous["wires"], data["wires"], _wire_key)
        if removed_c or added_c or removed_w or added_w:
            ops.append(
                {
                    "op": "edit",
                    "circuit": name,
                    "remove_components": removed_c,
                    "add_components": added_c,
                    "remove_wires": removed_w,
                    "add_wires": added_w,
                }
            )

    for name in before_names:
        if name not in after["names"]:
            ops.append({"op": "remove_circuit", "name": name})

    if after["main"] and after["main"] != (
        rename[1] if rename and before["main"] == rename[0] else before["main"]
    ):
        ops.append({"op": "set_main", "name": after["main"]})
    return ops


def expected_state(project: LogisimProject) -> dict[str, Any]:
    """Full snapshot in the shape the plugin's SAVED verification expects."""
    snap = capture(project)
    return {
        "main": snap["main"],
        "circuits": [
            {"name": name, **snap["circuits"][name]} for name in snap["names"]
        ],
    }


class LiveSession:
    """Binding between the bridge's open project and the same project in the Logisim window."""

    def __init__(self, runner):
        self.runner = runner
        self.path: Path | None = None
        self.external = -1

    @property
    def client(self):
        return self.runner.live

    @property
    def bound(self) -> bool:
        return self.path is not None

    def bind(self, path: Path, status: dict[str, Any] | None = None) -> bool:
        self.path = path
        if status is None or "external_revision" not in status:
            status = self.status()
        if not status or not status.get("open_in_app"):
            self.unbind()
            return False
        self.external = int(status.get("external_revision", 0))
        return True

    def unbind(self) -> None:
        self.path = None
        self.external = -1

    def _request(self, command: str, *args: str, timeout: float = 30.0) -> dict[str, Any]:
        assert self.path is not None
        try:
            return self.client.request(command, str(self.path), *args, timeout=timeout)
        except LiveAppError as exc:
            if exc.code == "NOT_OPEN":
                self.unbind()
                raise LiveNotOpen(exc.message) from exc
            if exc.code == "STALE":
                raise LiveStale(int(exc.message or 0)) from exc
            if exc.code == "INVALID":
                raise LiveRejected(exc.message) from exc
            raise

    def status(self) -> dict[str, Any] | None:
        if self.path is None:
            return None
        try:
            status = self._request("STATUS", timeout=5.0)
        except (LiveAppUnavailable, LiveNotOpen, LiveAppError):
            # Includes a Logisim started by an older bridge whose plugin lacks STATUS.
            self.unbind()
            return None
        if not status.get("open_in_app"):
            self.unbind()
            return None
        return status

    def has_external_changes(self) -> dict[str, Any] | None:
        """Return the status when the window was edited by hand since the last sync."""
        status = self.status()
        if status and int(status.get("external_revision", 0)) != self.external:
            return status
        return None

    def apply(self, ops: list[dict[str, Any]], label: str) -> dict[str, Any]:
        clean_label = " ".join(label.split())[:120] or "MCP edit"
        payload = json.dumps(ops, separators=(",", ":"))
        response = self._request("APPLY", str(self.external), clean_label, payload)
        self.external = int(response.get("external_revision", self.external))
        return response

    def pull(self, runtime_dir: Path, real_path: Path) -> LogisimProject:
        """Load the window's current model (hand edits included) through Logisim's writer."""
        runtime_dir.mkdir(parents=True, exist_ok=True)
        temp = runtime_dir / f"pull-{uuid.uuid4().hex}.circ"
        try:
            status = self._request("EXPORT", str(temp))
            project = LogisimProject.load(temp)
        finally:
            try:
                temp.unlink()
            except OSError:
                pass
        project.path = real_path
        project.original_bytes = real_path.read_bytes() if real_path.exists() else b""
        project.dirty = bool(status.get("dirty", True))
        self.external = int(status.get("external_revision", self.external))
        return project

    def saved(self, project: LogisimProject) -> dict[str, Any]:
        payload = json.dumps(expected_state(project), separators=(",", ":"))
        return self._request("SAVED", payload)

    def show(self, circuit: str | None = None) -> dict[str, Any]:
        return self._request("SHOW", circuit or "")

    # ------------------------------------------------------------------ understanding (v2.1)

    def _json(self, command: str, args: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
        return self._request(command, json.dumps(args, separators=(",", ":")), timeout=timeout)

    def catalog(self, library: str | None = None, query: str | None = None) -> dict[str, Any]:
        return self._json("CATALOG", {"library": library, "query": query})

    def describe(self, lib: str | None, name: str, props: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._json(
            "DESCRIBE", {"lib": lib, "name": name, "props": {k: str(v) for k, v in (props or {}).items()}}
        )

    def describe_many(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._json("DESCRIBE_MANY", {"items": items})["items"]

    def inspect(self, circuit: str, *, values: bool = True, attributes: bool = False) -> dict[str, Any]:
        return self._json("INSPECT", {"circuit": circuit, "values": values, "attributes": attributes})

    def simulate(self, circuit: str, spec: dict[str, Any], timeout: float = 120.0) -> dict[str, Any]:
        return self._json("SIMULATE", {**spec, "circuit": circuit}, timeout=timeout)

    def drive(self, circuit: str, values: dict[str, Any]) -> dict[str, Any]:
        return self._json("DRIVE", {"circuit": circuit, "values": values})
