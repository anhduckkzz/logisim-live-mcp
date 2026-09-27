from __future__ import annotations

import copy
import hashlib
import re
from pathlib import Path
from typing import Any, Iterable

from lxml import etree

from .errors import (
    AmbiguousComponentError,
    CircuitNotFoundError,
    ComponentNotFoundError,
    ValidationFailedError,
)
from .models import Point, ValidationIssue
from .layout import analyze_layout as analyze_circuit_layout
from .layout import route_orthogonal

_LOC_RE = re.compile(r"^\(-?\d+,-?\d+\)$")

# Exact library identifiers and default toolbar layout from Logisim Evolution
# v5.0.0's resources/logisim/default.templ.  Keeping these here lets the
# bridge create a project that the official loader treats exactly like a new
# project created by the application.
_V5_LIBRARIES = (
    ("0", "#Wiring"),
    ("1", "#Gates"),
    ("2", "#Plexers"),
    ("3", "#Arithmetic"),
    ("D", "#FPArithmetic"),
    ("4", "#Memory"),
    ("5", "#I/O"),
    ("A", "#TTL"),
    ("7", "#TCL"),
    ("8", "#Base"),
    ("9", "#BFH-Praktika"),
    ("B", "#Input/Output-Extra"),
    ("C", "#Soc"),
)


def _element_children(element: etree._Element, tag: str) -> Iterable[etree._Element]:
    for child in element:
        if isinstance(child.tag, str) and etree.QName(child).localname == tag:
            yield child


def _properties(component: etree._Element) -> dict[str, str]:
    result: dict[str, str] = {}
    for child in _element_children(component, "a"):
        name = child.get("name")
        if name:
            result[name] = child.get("val", "")
    return result


class LogisimProject:
    """In-memory semantic view of one Logisim Evolution .circ XML file."""

    def __init__(self, path: Path, tree: etree._ElementTree, original: bytes):
        self.path = path
        self.tree = tree
        self.original_bytes = original
        self.dirty = False
        self._had_declaration = original.lstrip().startswith(b"<?xml")
        self._encoding = tree.docinfo.encoding or "UTF-8"
        self._doctype = tree.docinfo.doctype or None
        self._standalone = tree.docinfo.standalone

    @classmethod
    def load(cls, path: Path) -> "LogisimProject":
        original = path.read_bytes()
        parser = etree.XMLParser(
            remove_blank_text=False,
            remove_comments=False,
            strip_cdata=False,
            resolve_entities=False,
            load_dtd=False,
            no_network=True,
            recover=False,
            huge_tree=False,
        )
        try:
            tree = etree.fromstring(original, parser=parser).getroottree()
        except (etree.XMLSyntaxError, ValueError) as exc:
            raise ValidationFailedError(f"Malformed XML in {path.name}: {exc}") from exc
        return cls(path, tree, original)

    @classmethod
    def create(cls, path: Path, circuit_name: str = "main") -> "LogisimProject":
        """Create the official Logisim Evolution 5.0.0 plain-project shape."""
        name = cls._checked_circuit_name(circuit_name)
        root = etree.Element("project", source="5.0.0", version="1.0")
        for library, description in _V5_LIBRARIES:
            etree.SubElement(root, "lib", name=library, desc=description)
        etree.SubElement(root, "main", name=name)

        options = etree.SubElement(root, "options")
        for key, value in (
            ("showgrid", "true"),
            ("simulate", "true"),
            ("showghosts", "true"),
            ("zoom", "1.0"),
        ):
            etree.SubElement(options, "a", name=key, val=value)

        mappings = etree.SubElement(root, "mappings")
        etree.SubElement(mappings, "tool", lib="8", name="Poke Tool", map="Button2")
        etree.SubElement(mappings, "tool", lib="8", name="Menu Tool", map="Button3")
        etree.SubElement(mappings, "tool", lib="8", name="Menu Tool", map="Ctrl Button1")

        toolbar = etree.SubElement(root, "toolbar")
        for tool in ("Poke Tool", "Edit Tool", "Wiring Tool", "Text Tool", "Image"):
            etree.SubElement(toolbar, "tool", lib="8", name=tool)
        etree.SubElement(toolbar, "sep")
        input_pin = etree.SubElement(toolbar, "tool", lib="0", name="Pin")
        etree.SubElement(input_pin, "a", name="tristate", val="false")
        output_pin = etree.SubElement(toolbar, "tool", lib="0", name="Pin")
        etree.SubElement(output_pin, "a", name="facing", val="west")
        etree.SubElement(output_pin, "a", name="type", val="output")
        etree.SubElement(toolbar, "sep")
        for tool in ("NOT Gate", "AND Gate", "OR Gate", "XOR Gate", "NAND Gate", "NOR Gate"):
            etree.SubElement(toolbar, "tool", lib="1", name=tool)
        etree.SubElement(toolbar, "sep")
        for tool in ("D Flip-Flop", "Register"):
            etree.SubElement(toolbar, "tool", lib="4", name=tool)

        circuit = etree.SubElement(root, "circuit", name=name)
        etree.SubElement(circuit, "a", name="appearance", val="logisim_evolution")
        tree = etree.ElementTree(root)
        original = etree.tostring(
            tree,
            encoding="UTF-8",
            xml_declaration=True,
            standalone=False,
            pretty_print=True,
        )
        project = cls(path, tree, original)
        project._had_declaration = True
        project._encoding = "UTF-8"
        project._standalone = False
        project.dirty = True
        return project

    @staticmethod
    def _checked_circuit_name(name: str) -> str:
        checked = str(name).strip()
        if not checked:
            raise ValueError("Circuit name must not be empty")
        if any(char in checked for char in "\r\n\0"):
            raise ValueError("Circuit name contains an invalid control character")
        return checked

    @property
    def root(self) -> etree._Element:
        return self.tree.getroot()

    def clone(self) -> "LogisimProject":
        return LogisimProject(self.path, copy.deepcopy(self.tree), self.original_bytes)

    def circuit_names(self) -> list[str]:
        return [c.get("name", "") for c in _element_children(self.root, "circuit")]

    def get_circuit(self, name: str) -> etree._Element:
        for circuit in _element_children(self.root, "circuit"):
            if circuit.get("name") == name:
                return circuit
        raise CircuitNotFoundError(f"Circuit not found: {name}")

    def main_circuit_name(self) -> str | None:
        for node in _element_children(self.root, "main"):
            return node.get("name")
        names = self.circuit_names()
        return names[0] if names else None

    def add_circuit(self, name: str, *, set_as_main: bool = False) -> dict[str, Any]:
        checked = self._checked_circuit_name(name)
        if checked in self.circuit_names():
            raise ValueError(f"Circuit already exists: {checked}")
        circuit = etree.Element("circuit", name=checked)
        etree.SubElement(circuit, "a", name="appearance", val="logisim_evolution")
        self.root.append(circuit)
        self.dirty = True
        if set_as_main:
            self.set_main_circuit(checked)
        return self.read_circuit(checked)

    def rename_circuit(self, name: str, new_name: str) -> dict[str, Any]:
        circuit = self.get_circuit(name)
        checked = self._checked_circuit_name(new_name)
        if checked != name and checked in self.circuit_names():
            raise ValueError(f"Circuit already exists: {checked}")
        circuit.set("name", checked)
        for main in _element_children(self.root, "main"):
            if main.get("name") == name:
                main.set("name", checked)
        updated_references = 0
        for owner in _element_children(self.root, "circuit"):
            for component in _element_children(owner, "comp"):
                if not component.get("lib") and component.get("name") == name:
                    component.set("name", checked)
                    updated_references += 1
        self.dirty = True
        result = self.read_circuit(checked)
        result["renamed_from"] = name
        result["updated_subcircuit_references"] = updated_references
        return result

    def delete_circuit(self, name: str, *, delete_references: bool = False) -> dict[str, Any]:
        circuit = self.get_circuit(name)
        if len(self.circuit_names()) <= 1:
            raise ValueError("A Logisim project must retain at least one circuit")
        references: list[tuple[etree._Element, etree._Element]] = []
        for owner in _element_children(self.root, "circuit"):
            for component in _element_children(owner, "comp"):
                if not component.get("lib") and component.get("name") == name:
                    references.append((owner, component))
        if references and not delete_references:
            raise ValueError(
                f"Circuit {name!r} is used by {len(references)} subcircuit component(s); "
                "set delete_references=true to remove them"
            )
        for owner, component in references:
            owner.remove(component)
        self.root.remove(circuit)
        if self.main_circuit_name() == name:
            self.set_main_circuit(self.circuit_names()[0])
        self.dirty = True
        return {
            "deleted": True,
            "name": name,
            "deleted_subcircuit_references": len(references),
            "main_circuit": self.main_circuit_name(),
        }

    def set_main_circuit(self, name: str) -> dict[str, Any]:
        self.get_circuit(name)
        main_nodes = list(_element_children(self.root, "main"))
        if main_nodes:
            main = main_nodes[0]
            main.set("name", name)
            for extra in main_nodes[1:]:
                self.root.remove(extra)
        else:
            main = etree.Element("main", name=name)
            insert_at = 0
            for idx, child in enumerate(self.root):
                if isinstance(child.tag, str) and etree.QName(child).localname == "lib":
                    insert_at = idx + 1
            self.root.insert(insert_at, main)
        self.dirty = True
        return {"main_circuit": name}

    def summary(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "source": self.root.get("source"),
            "version": self.root.get("version"),
            "main_circuit": self.main_circuit_name(),
            "circuits": self.list_circuits(),
            "dirty": self.dirty,
            "sha256": hashlib.sha256(self.serialize()).hexdigest(),
        }

    def list_circuits(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        main = self.main_circuit_name()
        for circuit in _element_children(self.root, "circuit"):
            comps = list(_element_children(circuit, "comp"))
            wires = list(_element_children(circuit, "wire"))
            items.append(
                {
                    "name": circuit.get("name", ""),
                    "is_main": circuit.get("name") == main,
                    "component_count": len(comps),
                    "wire_count": len(wires),
                }
            )
        return items

    def list_libraries(self) -> list[dict[str, Any]]:
        libraries: list[dict[str, Any]] = []
        for node in _element_children(self.root, "lib"):
            libraries.append(
                {
                    "library": node.get("name"),
                    "description": node.get("desc"),
                    "properties": _properties(node),
                }
            )
        return libraries

    def read_circuit(self, name: str) -> dict[str, Any]:
        circuit = self.get_circuit(name)
        components = [self._component_data(name, c) for c in _element_children(circuit, "comp")]
        wires = [
            {"from": w.get("from"), "to": w.get("to")}
            for w in _element_children(circuit, "wire")
        ]
        circuit_properties: dict[str, str] = {}
        for node in _element_children(circuit, "a"):
            if node.get("name"):
                circuit_properties[node.get("name")] = node.get("val", "")
        return {
            "name": name,
            "properties": circuit_properties,
            "components": components,
            "wires": wires,
        }

    def _component_data(self, circuit_name: str, component: etree._Element) -> dict[str, Any]:
        loc = component.get("loc", "")
        return {
            "ref": self.component_ref(circuit_name, component),
            "library": component.get("lib"),
            "name": component.get("name"),
            "location": loc,
            "properties": _properties(component),
        }

    @staticmethod
    def component_ref(circuit_name: str, component: etree._Element) -> str:
        return "|".join(
            [
                circuit_name,
                component.get("loc", ""),
                component.get("lib", ""),
                component.get("name", ""),
            ]
        )

    def find_component(
        self,
        circuit_name: str,
        location: str | list[int] | tuple[int, int] | Point,
        *,
        component_name: str | None = None,
        library: str | None = None,
    ) -> etree._Element:
        circuit = self.get_circuit(circuit_name)
        loc = str(Point.parse(location))
        matches = []
        for component in _element_children(circuit, "comp"):
            if component.get("loc") != loc:
                continue
            if component_name is not None and component.get("name") != component_name:
                continue
            if library is not None and component.get("lib") != str(library):
                continue
            matches.append(component)
        selector = f"{circuit_name} at {loc}"
        if not matches:
            raise ComponentNotFoundError(f"No component matches {selector}")
        if len(matches) > 1:
            raise AmbiguousComponentError(
                f"Multiple components match {selector}; include component_name and library"
            )
        return matches[0]

    def add_component(
        self,
        circuit_name: str,
        component_name: str,
        library: str | int,
        location: str | list[int] | tuple[int, int] | Point,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        circuit = self.get_circuit(circuit_name)
        loc = str(Point.parse(location))
        component = etree.Element(
            "comp", lib=str(library), loc=loc, name=str(component_name)
        )
        for key, value in (properties or {}).items():
            etree.SubElement(component, "a", name=str(key), val=str(value))
        insert_at = len(circuit)
        for idx, child in enumerate(circuit):
            if isinstance(child.tag, str) and etree.QName(child).localname == "wire":
                insert_at = idx
                break
        circuit.insert(insert_at, component)
        self.dirty = True
        return self._component_data(circuit_name, component)

    def update_component(
        self,
        circuit_name: str,
        location: str | list[int] | tuple[int, int] | Point,
        *,
        component_name: str | None = None,
        library: str | None = None,
        new_component_name: str | None = None,
        new_library: str | None = None,
        set_properties: dict[str, Any] | None = None,
        remove_properties: list[str] | None = None,
    ) -> dict[str, Any]:
        component = self.find_component(
            circuit_name, location, component_name=component_name, library=library
        )
        if new_component_name is not None:
            component.set("name", new_component_name)
        if new_library is not None:
            component.set("lib", str(new_library))
        to_remove = set(remove_properties or [])
        for child in list(_element_children(component, "a")):
            if child.get("name") in to_remove:
                component.remove(child)
        current = {node.get("name"): node for node in _element_children(component, "a")}
        for key, value in (set_properties or {}).items():
            node = current.get(str(key))
            if node is None:
                node = etree.SubElement(component, "a", name=str(key))
            node.set("val", str(value))
        self.dirty = True
        return self._component_data(circuit_name, component)

    def move_component(
        self,
        circuit_name: str,
        location: str | list[int] | tuple[int, int] | Point,
        new_location: str | list[int] | tuple[int, int] | Point,
        *,
        component_name: str | None = None,
        library: str | None = None,
        move_exact_wire_endpoints: bool = False,
    ) -> dict[str, Any]:
        component = self.find_component(
            circuit_name, location, component_name=component_name, library=library
        )
        old_loc = component.get("loc", "")
        new_loc = str(Point.parse(new_location))
        component.set("loc", new_loc)
        moved_wires = 0
        if move_exact_wire_endpoints:
            circuit = self.get_circuit(circuit_name)
            for wire in _element_children(circuit, "wire"):
                for attr in ("from", "to"):
                    if wire.get(attr) == old_loc:
                        wire.set(attr, new_loc)
                        moved_wires += 1
        self.dirty = True
        result = self._component_data(circuit_name, component)
        result["wire_endpoints_moved"] = moved_wires
        return result

    def delete_component(
        self,
        circuit_name: str,
        location: str | list[int] | tuple[int, int] | Point,
        *,
        component_name: str | None = None,
        library: str | None = None,
        remove_exact_endpoint_wires: bool = False,
    ) -> dict[str, Any]:
        circuit = self.get_circuit(circuit_name)
        component = self.find_component(
            circuit_name, location, component_name=component_name, library=library
        )
        data = self._component_data(circuit_name, component)
        loc = component.get("loc")
        removed_wires = 0
        if remove_exact_endpoint_wires:
            for wire in list(_element_children(circuit, "wire")):
                if loc in (wire.get("from"), wire.get("to")):
                    circuit.remove(wire)
                    removed_wires += 1
        circuit.remove(component)
        self.dirty = True
        data["removed_wire_count"] = removed_wires
        return data

    def connect(
        self,
        circuit_name: str,
        start: str | list[int] | tuple[int, int] | Point,
        end: str | list[int] | tuple[int, int] | Point,
    ) -> dict[str, str | bool]:
        circuit = self.get_circuit(circuit_name)
        a, b = str(Point.parse(start)), str(Point.parse(end))
        if a == b:
            raise ValueError("A wire must have two different endpoints")
        for wire in _element_children(circuit, "wire"):
            if {wire.get("from"), wire.get("to")} == {a, b}:
                return {"from": wire.get("from", a), "to": wire.get("to", b), "created": False}
        wire = etree.Element("wire", **{"from": a, "to": b})
        circuit.append(wire)
        self.dirty = True
        return {"from": a, "to": b, "created": True}

    def connect_smart(
        self,
        circuit_name: str,
        start: str | list[int] | tuple[int, int] | Point,
        end: str | list[int] | tuple[int, int] | Point,
        *,
        grid_step: int = 10,
        clearance: int = 10,
        components: list[dict[str, Any]] | None = None,
        strict: bool = True,
        sources: Any = None,
        targets: Any = None,
        friendly_points: Any = None,
    ) -> dict[str, Any]:
        """Route a readable orthogonal wire while avoiding devices and wire overlap.

        ``components`` may carry exact Logisim bounds and port points (see geometry.py); by
        default the bridge's own footprint estimates are used.
        """
        a, b = Point.parse(start), Point.parse(end)
        current = self.read_circuit(circuit_name)
        route = route_orthogonal(
            a,
            b,
            components if components is not None else current["components"],
            current["wires"],
            grid_step=grid_step,
            clearance=clearance,
            strict=strict,
            sources=sources,
            targets=targets,
            friendly_points=friendly_points,
        )
        created = []
        for first, second in zip(route["points"], route["points"][1:]):
            created.append(self.connect(circuit_name, first, second))
        route["created_segments"] = created
        return route

    def analyze_layout(
        self, circuit_name: str, components: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        circuit = self.read_circuit(circuit_name)
        result = analyze_circuit_layout(
            components if components is not None else circuit["components"], circuit["wires"]
        )
        result["circuit"] = circuit_name
        result["component_count"] = len(circuit["components"])
        result["wire_segment_count"] = len(circuit["wires"])
        return result

    def disconnect(
        self,
        circuit_name: str,
        start: str | list[int] | tuple[int, int] | Point,
        end: str | list[int] | tuple[int, int] | Point,
    ) -> dict[str, Any]:
        circuit = self.get_circuit(circuit_name)
        a, b = str(Point.parse(start)), str(Point.parse(end))
        removed = 0
        for wire in list(_element_children(circuit, "wire")):
            if {wire.get("from"), wire.get("to")} == {a, b}:
                circuit.remove(wire)
                removed += 1
        if removed:
            self.dirty = True
        return {"from": a, "to": b, "removed": removed}

    def validate(self) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if not isinstance(self.root.tag, str) or etree.QName(self.root).localname != "project":
            issues.append(ValidationIssue("error", "root", "Root element must be <project>"))
            return issues
        names = self.circuit_names()
        if not names:
            issues.append(ValidationIssue("error", "no-circuits", "Project has no circuits"))
        duplicates = sorted({name for name in names if names.count(name) > 1})
        for name in duplicates:
            issues.append(ValidationIssue("error", "duplicate-circuit", f"Duplicate circuit: {name}"))
        main = self.main_circuit_name()
        if main and main not in names:
            issues.append(
                ValidationIssue("error", "missing-main", f"Main circuit does not exist: {main}")
            )
        for circuit_name in names:
            circuit = self.get_circuit(circuit_name)
            seen_wires: set[frozenset[str | None]] = set()
            for component in _element_children(circuit, "comp"):
                loc = component.get("loc")
                if not loc or not _LOC_RE.match(loc):
                    issues.append(
                        ValidationIssue(
                            "error", "bad-component-location", "Invalid component location", circuit_name, loc
                        )
                    )
                if not component.get("name"):
                    issues.append(
                        ValidationIssue(
                            "error", "missing-component-name", "Component is missing name", circuit_name, loc
                        )
                    )
            for wire in _element_children(circuit, "wire"):
                start, end = wire.get("from"), wire.get("to")
                if not start or not end or not _LOC_RE.match(start) or not _LOC_RE.match(end):
                    issues.append(
                        ValidationIssue(
                            "error", "bad-wire", "Wire has an invalid endpoint", circuit_name
                        )
                    )
                    continue
                if start == end:
                    issues.append(
                        ValidationIssue(
                            "error", "zero-length-wire", "Wire endpoints are identical", circuit_name, start
                        )
                    )
                signature = frozenset((start, end))
                if signature in seen_wires:
                    issues.append(
                        ValidationIssue(
                            "warning", "duplicate-wire", f"Duplicate wire {start} -> {end}", circuit_name
                        )
                    )
                seen_wires.add(signature)
        return issues

    def assert_valid(self) -> None:
        errors = [issue for issue in self.validate() if issue.severity == "error"]
        if errors:
            detail = "; ".join(issue.message for issue in errors[:5])
            raise ValidationFailedError(f"Project validation failed: {detail}")

    def serialize(self) -> bytes:
        return etree.tostring(
            self.tree,
            encoding=self._encoding,
            xml_declaration=self._had_declaration,
            doctype=self._doctype,
            standalone=self._standalone if self._had_declaration else None,
            pretty_print=False,
        )
