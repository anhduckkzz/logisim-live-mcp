from logisim_mcp.layout import analyze_layout, component_port_axes, route_orthogonal
from logisim_mcp.models import Point


def test_smart_route_avoids_gate_body() -> None:
    components = [
        {
            "location": "(100,0)",
            "library": "1",
            "name": "AND Gate",
            "properties": {},
        }
    ]
    result = route_orthogonal(Point(0, 0), Point(200, 0), components, [])
    assert result["points"] != [[0, 0], [200, 0]]
    assert result["segment_count"] == 3
    assert result["overlap_length"] == 0
    assert result["crossing_count"] == 0


def test_smart_route_prefers_detour_over_existing_wire_overlap() -> None:
    wires = [{"from": "(0,0)", "to": "(200,0)"}]
    result = route_orthogonal(Point(0, 0), Point(200, 0), [], wires)
    assert result["overlap_length"] == 0
    assert result["turn_count"] == 2
    assert result["points"][1][1] != 0


def test_smart_route_stays_straight_when_aligned_ports_sit_on_the_row() -> None:
    # A gate beyond the target has its input on the same row; the congestion cost used to push
    # the wire onto a pointless jog even though the straight run is free.
    components = [{"location": "(240,0)", "library": "1", "name": "NOT Gate", "properties": {}}]
    result = route_orthogonal(Point(0, 0), Point(200, 0), components, [])
    assert result["points"] == [[0, 0], [200, 0]]
    assert result["turn_count"] == 0


def test_smart_route_straight_run_still_avoids_existing_wire_overlap() -> None:
    wires = [{"from": "(50,0)", "to": "(150,0)"}]
    components = [{"location": "(240,0)", "library": "1", "name": "NOT Gate", "properties": {}}]
    result = route_orthogonal(Point(0, 0), Point(200, 0), components, wires)
    assert result["overlap_length"] == 0
    assert result["points"] != [[0, 0], [200, 0]]


def test_layout_analysis_reports_overlap_crossing_and_device_intersection() -> None:
    components = [
        {
            "location": "(100,0)",
            "library": "1",
            "name": "AND Gate",
            "properties": {},
        }
    ]
    wires = [
        {"from": "(0,0)", "to": "(200,0)"},
        {"from": "(20,0)", "to": "(80,0)"},
        {"from": "(50,-20)", "to": "(50,20)"},
    ]
    report = analyze_layout(components, wires)
    assert report["clean"] is False
    assert report["wire_component_intersections"]
    assert report["wire_overlaps"]
    assert report["wire_crossings"]


def test_port_axes_follow_v5_gate_and_ttl_geometry() -> None:
    gate = {
        "location": "(200,100)",
        "library": "1",
        "name": "AND Gate",
        "properties": {"inputs": "2", "size": "50"},
    }
    assert component_port_axes(gate) == [(200, 100), (150, 80), (150, 120)]
    ttl = {
        "location": "(300,300)",
        "library": "A",
        "name": "7408",
        "properties": {},
    }
    ports = component_port_axes(ttl)
    assert (310, 330) in ports
    assert (430, 270) in ports
