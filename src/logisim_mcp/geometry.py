"""Exact component geometry from Logisim itself (via the live plugin).

Logisim decides where every port of every component is. Instead of estimating, the bridge asks
the plugin to build each component type once (with its properties) and caches the resulting
bounds and port offsets. With that, ports can be referenced by name ("G1.in2", "U3.pin13",
"A") and the wire router avoids the real device bodies.
"""

from __future__ import annotations

import re
from typing import Any

from .errors import LogisimMcpError
from .project import LogisimProject

_POINT = re.compile(r"^\s*[\[(]?\s*(-?\d+)\s*,\s*(-?\d+)\s*[\])]?\s*$")
_LOC = re.compile(r"^\((-?\d+),(-?\d+)\)$")


def _xy(value: str) -> tuple[int, int]:
    m = _LOC.match(value)
    if not m:
        raise ValueError(f"bad location {value!r}")
    return int(m.group(1)), int(m.group(2))


def _geometry_props(props: dict[str, str]) -> dict[str, str]:
    """Properties sent to Logisim to measure a component (labels change the drawn text box)."""
    return dict(props)


class GeometryResolver:
    """Resolves component references and port names to exact coordinates for one circuit."""

    def __init__(self, session, project: LogisimProject, circuit: str):
        self.session = session
        self.project = project
        self.circuit = circuit
        self._libs = {str(l["library"]): l["description"] for l in project.list_libraries()}
        self._components: list[dict[str, Any]] | None = None

    # ---------------------------------------------------------------- components

    def components(self) -> list[dict[str, Any]]:
        """Components of the circuit (current bridge model) with exact bounds and ports."""
        if self._components is not None:
            return self._components
        comps = self.project.read_circuit(self.circuit)["components"]
        cache: dict = getattr(self.session, "_geometry_cache", None)
        if cache is None:
            cache = {}
            self.session._geometry_cache = cache
        wanted: dict[tuple, dict[str, Any]] = {}
        keys = []
        for comp in comps:
            lib_id = comp.get("library")
            lib = self._libs.get(str(lib_id), str(lib_id)) if lib_id not in (None, "") else None
            props = _geometry_props(comp.get("properties") or {})
            key = (lib, comp["name"], tuple(sorted(props.items())))
            keys.append(key)
            # Subcircuit shapes change when their pins change, so never reuse them across calls.
            if key not in cache or lib is None:
                wanted[key] = {"lib": lib, "name": comp["name"], "props": props}
        if wanted:
            order = list(wanted)
            results = self.session.describe_many([wanted[k] for k in order])
            for key, result in zip(order, results):
                cache[key] = result
        ids: dict[str, int] = {}
        resolved = []
        for comp, key in zip(comps, keys):
            x, y = _xy(comp["location"])
            info = cache.get(key) or {}
            base_id = f"{comp['name']}@{x},{y}"
            ids[base_id] = ids.get(base_id, 0) + 1
            cid = base_id if ids[base_id] == 1 else f"{base_id}#{ids[base_id]}"
            entry = dict(comp)
            entry["id"] = cid
            entry["label"] = (comp.get("properties") or {}).get("label") or None
            entry["x"], entry["y"] = x, y
            if "error" in info:
                entry["geometry_error"] = info["error"]
                entry["ports_exact"] = []
            else:
                b = info.get("bounds") or {}
                entry["bounds"] = {
                    "x": x + b.get("x", 0),
                    "y": y + b.get("y", 0),
                    "width": b.get("width", 0),
                    "height": b.get("height", 0),
                }
                entry["ports_exact"] = [
                    {**p, "x": x + p["x"], "y": y + p["y"]} for p in info.get("ports", [])
                ]
                vb = info.get("visual_bounds")
                if vb:
                    entry["visual_bounds"] = {
                        "x": x + vb["x"], "y": y + vb["y"], "width": vb["width"], "height": vb["height"]
                    }
            resolved.append(entry)
        self._components = resolved
        return resolved

    def invalidate(self) -> None:
        self._components = None

    def find_component(self, ref: str) -> dict[str, Any]:
        comps = self.components()
        exact = [c for c in comps if c["id"] == ref]
        if exact:
            return exact[0]
        labelled = [c for c in comps if c.get("label") == ref]
        if len(labelled) == 1:
            return labelled[0]
        if len(labelled) > 1:
            raise LogisimMcpError(
                f"Label {ref!r} is used by {len(labelled)} components; use an id such as "
                f"{labelled[0]['id']!r}"
            )
        at = _POINT.match(ref)
        if at:
            x, y = int(at.group(1)), int(at.group(2))
            anchored = [c for c in comps if (c["x"], c["y"]) == (x, y)]
            if len(anchored) == 1:
                return anchored[0]
        known = ", ".join(sorted({c.get("label") or c["id"] for c in comps})[:30])
        raise LogisimMcpError(f"No component {ref!r} in {self.circuit}. Known: {known}")

    @staticmethod
    def _find_port(comp: dict[str, Any], port: str | int | None) -> dict[str, Any]:
        ports = comp.get("ports_exact") or []
        if not ports:
            raise LogisimMcpError(
                f"{comp['id']} has no known ports ({comp.get('geometry_error', 'no geometry')})"
            )
        if port is None or port == "":
            if len(ports) == 1:
                return ports[0]
            raise LogisimMcpError(
                f"{comp.get('label') or comp['id']} has several ports; name one of: "
                + ", ".join(p["name"] for p in ports)
            )
        if isinstance(port, int) or (isinstance(port, str) and port.isdigit() and not port.startswith("0")):
            index = int(port)
            for p in ports:
                if p["index"] == index:
                    return p
        text = str(port)
        lowered = text.lower()
        for p in ports:
            if p["name"] == text or text in p.get("aliases", []):
                return p
        for p in ports:
            if p["name"].lower() == lowered or lowered in [a.lower() for a in p.get("aliases", [])]:
                return p
        raise LogisimMcpError(
            f"{comp.get('label') or comp['id']} has no port {port!r}; ports: "
            + ", ".join(
                p["name"] + (f" ({'/'.join(p.get('aliases', []))})" if p.get("aliases") else "")
                for p in ports
            )
        )

    def resolve(self, ref: Any) -> dict[str, Any]:
        """Turn a port reference into {"x","y","component","port",...}.

        Accepted forms: "G1.in2", "AND Gate@300,150.out", "U1.pin13", "A" (a one-port device such
        as a Pin), {"component": "G1", "port": "in2"}, {"at": [x, y]} or [x, y] for a raw point.
        """
        if isinstance(ref, (list, tuple)) and len(ref) == 2:
            return {"x": int(ref[0]), "y": int(ref[1]), "component": None, "port": None}
        if isinstance(ref, dict):
            if "component" in ref:
                comp = self.find_component(str(ref["component"]))
                port = self._find_port(comp, ref.get("port"))
                return self._result(comp, port)
            if "at" in ref:
                x, y = ref["at"]
                return {"x": int(x), "y": int(y), "component": None, "port": None}
            raise LogisimMcpError(f"Cannot read port reference {ref!r}")
        text = str(ref).strip()
        point = _POINT.match(text)
        if point and not any(c.get("label") == text for c in self.components()):
            return {"x": int(point.group(1)), "y": int(point.group(2)), "component": None, "port": None}
        try:
            comp = self.find_component(text)
            return self._result(comp, self._find_port(comp, None))
        except LogisimMcpError as whole_error:
            if "." not in text:
                raise whole_error
        comp_ref, _, port = text.rpartition(".")
        comp = self.find_component(comp_ref)
        return self._result(comp, self._find_port(comp, port))

    @staticmethod
    def _result(comp: dict[str, Any], port: dict[str, Any]) -> dict[str, Any]:
        return {
            "x": port["x"],
            "y": port["y"],
            "component": comp.get("label") or comp["id"],
            "port": port["name"],
            "direction": port.get("direction"),
            "width": port.get("width"),
        }

    def router_components(self) -> list[dict[str, Any]]:
        """Components in the shape layout.py expects, carrying exact bounds and port points."""
        out = []
        for comp in self.components():
            entry = {
                "location": comp["location"],
                "name": comp["name"],
                "library": comp.get("library"),
                "properties": comp.get("properties") or {},
            }
            if "bounds" in comp:
                # Route around what the user sees: the body and its label text.
                entry["bounds"] = comp.get("visual_bounds") or comp["bounds"]
                entry["port_points"] = [(p["x"], p["y"]) for p in comp["ports_exact"]]
            out.append(entry)
        return out

    # ---------------------------------------------------------------- connectivity

    def connectivity(self) -> "Connectivity":
        """Nets of the bridge model, with Logisim's rules (see Connectivity)."""
        wires = []
        for wire in self.project.read_circuit(self.circuit)["wires"]:
            try:
                a, b = _xy(wire["from"]), _xy(wire["to"])
            except ValueError:
                continue
            if a != b:
                wires.append((a, b))
        ports: list[tuple[int, int]] = []
        tunnels: dict[str, list[tuple[int, int]]] = {}
        for comp in self.components():
            for p in comp.get("ports_exact") or []:
                ports.append((p["x"], p["y"]))
            if comp["name"] == "Tunnel" and comp.get("label") and comp.get("ports_exact"):
                p = comp["ports_exact"][0]
                tunnels.setdefault(comp["label"], []).append((p["x"], p["y"]))
        return Connectivity(wires, ports, list(tunnels.values()))


class Connectivity:
    """Union-find of points joined the way Logisim joins them.

    Wires connect at their ends. A wire end or a component port that touches the middle of a
    wire is joined to it too, because Logisim splits the wire there when the circuit is built.
    Tunnels with the same label are one net. Crossing wires without a shared point stay apart.
    """

    def __init__(
        self,
        wires: list[tuple[tuple[int, int], tuple[int, int]]],
        ports: list[tuple[int, int]],
        tunnel_groups: list[list[tuple[int, int]]],
    ):
        self.parent: dict[tuple[int, int], tuple[int, int]] = {}
        self.wires = wires
        special = set(ports)
        rows: dict[int, list[tuple[int, int, int]]] = {}
        cols: dict[int, list[tuple[int, int, int]]] = {}
        for index, (a, b) in enumerate(wires):
            special.add(a)
            special.add(b)
            self.union(a, b)
            if a[1] == b[1]:
                rows.setdefault(a[1], []).append((min(a[0], b[0]), max(a[0], b[0]), index))
            elif a[0] == b[0]:
                cols.setdefault(a[0], []).append((min(a[1], b[1]), max(a[1], b[1]), index))
        for point in special:
            self.find(point)
            x, y = point
            for lo, hi, index in rows.get(y, ()):
                if lo < x < hi:
                    self.union(point, wires[index][0])
            for lo, hi, index in cols.get(x, ()):
                if lo < y < hi:
                    self.union(point, wires[index][0])
        for group in tunnel_groups:
            for other in group[1:]:
                self.union(group[0], other)

    def find(self, p: tuple[int, int]) -> tuple[int, int]:
        parent = self.parent.setdefault(p, p)
        if parent != p:
            parent = self.find(parent)
            self.parent[p] = parent
        return parent

    def union(self, a: tuple[int, int], b: tuple[int, int]) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb

    def net_of(self, point: tuple[int, int]) -> tuple[int, int] | None:
        return self.find(point) if point in self.parent else None

    def net_points(self, point: tuple[int, int], step: int = 10) -> set[tuple[int, int]]:
        """Every grid point on the wires of ``point``'s net, plus the net's known points."""
        root = self.net_of(point)
        if root is None:
            return {point}
        members = {p for p in self.parent if self.find(p) == root}
        result = set(members)
        for a, b in self.wires:
            if self.find(a) != root:
                continue
            if a[1] == b[1]:
                lo, hi = sorted((a[0], b[0]))
                start = -(-lo // step) * step
                result.update((x, a[1]) for x in range(start, hi + 1, step))
            elif a[0] == b[0]:
                lo, hi = sorted((a[1], b[1]))
                start = -(-lo // step) * step
                result.update((a[0], y) for y in range(start, hi + 1, step))
        return result
