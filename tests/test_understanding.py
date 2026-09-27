from logisim_mcp.geometry import Connectivity
from logisim_mcp.layout import route_orthogonal
from logisim_mcp.models import Point
from logisim_mcp.views import ascii_view, netlist_text, problems_text, truth_table_text

INSPECT = {
    "circuit": "main",
    "extent": [80, 90, 360, 120],
    "components": [
        {"id": "Pin@100,100", "label": "A", "library": "#Wiring", "name": "Pin", "loc": [100, 100],
         "pin_type": "input", "bounds": [80, 90, 20, 20],
         "ports": [{"index": 0, "name": "port", "direction": "out", "width": 1, "x": 100, "y": 100, "net": "n1"}]},
        {"id": "AND Gate@300,150", "label": "G1", "library": "#Gates", "name": "AND Gate", "loc": [300, 150],
         "bounds": [250, 125, 50, 50],
         "ports": [
             {"index": 0, "name": "out", "direction": "out", "width": 1, "x": 300, "y": 150, "net": None},
             {"index": 1, "name": "in1", "direction": "in", "width": 1, "x": 250, "y": 130, "net": "n1"},
             {"index": 2, "name": "in2", "direction": "in", "width": 1, "x": 250, "y": 170, "net": None},
         ]},
    ],
    "wires": [
        {"from": [100, 100], "to": [200, 100], "net": "n1"},
        {"from": [200, 100], "to": [200, 130], "net": "n1"},
        {"from": [200, 130], "to": [250, 130], "net": "n1"},
        {"from": [150, 60], "to": [150, 200], "net": "n2"},
    ],
    "nets": [
        {"id": "n1", "names": ["A"], "width": 1, "drivers": ["Pin@100,100.port"],
         "loads": ["AND Gate@300,150.in1"], "wire_segments": 3, "value": "1"},
    ],
    "problems": [
        {"severity": "warning", "kind": "unconnected_port", "message": "G1 port in2 is not connected",
         "at": [250, 170]},
    ],
}


def test_ascii_view_draws_devices_wires_ports_and_crossings() -> None:
    text = ascii_view(INSPECT)
    assert "╔" in text and "╝" in text  # device boxes
    assert "O" in text  # connected output port of pin A
    assert "i" in text  # unconnected input of G1 is lower case
    assert "┼" in text  # the vertical wire crosses A's wire without connecting
    assert "legend:" in text
    lines = text.splitlines()
    assert lines[1].strip().startswith("50")  # x ruler starts at the padded origin


def test_ascii_view_rejects_huge_views() -> None:
    try:
        ascii_view(INSPECT, region=[0, 0, 100000, 100], scale=10)
    except ValueError as exc:
        assert "region" in str(exc)
    else:
        raise AssertionError("expected a size error")


def test_netlist_and_problem_text() -> None:
    text = netlist_text(INSPECT)
    assert "G1  AND Gate  @300,150" in text
    assert "in2(in)@250,170->UNCONNECTED" in text
    assert "n1 [A] 1b =1 : Pin@100,100.port -> AND Gate@300,150.in1" in text
    assert "unconnected_port" in problems_text(INSPECT)


def test_truth_table_text_aligns_columns() -> None:
    text = truth_table_text(
        {
            "circuit": "main",
            "outputs": ["Y"],
            "rows": [
                {"in": {"A": "0", "B": "0"}, "out": {"Y": "0"}},
                {"in": {"A": "1", "B": "1"}, "out": {"Y": "1"}, "watch": {}},
            ],
        }
    )
    assert text.splitlines()[1].split() == ["A", "B", "|", "Y"]
    assert text.splitlines()[-1].split() == ["1", "1", "|", "1"]


def test_connectivity_follows_logisim_rules() -> None:
    wires = [((0, 0), (100, 0)), ((50, 0), (50, 50)), ((0, 80), (100, 80)), ((20, 40), (20, 120))]
    nets = Connectivity(wires, ports=[(100, 0), (200, 200)], tunnel_groups=[[(200, 200), (300, 300)]])
    # T-junction: an end touching the middle of a wire joins it
    assert nets.net_of((50, 50)) == nets.net_of((0, 0))
    # plain crossing without a shared point stays separate
    assert nets.net_of((20, 40)) != nets.net_of((0, 80))
    # same-label tunnels are one net
    assert nets.net_of((200, 200)) == nets.net_of((300, 300))
    assert (70, 0) in nets.net_points((0, 0))


def test_strict_router_never_shorts_another_net() -> None:
    # An existing horizontal wire of another net sits between start and end.
    wires = [{"from": "(0,100)", "to": "(300,100)"}]
    route = route_orthogonal(Point(100, 50), Point(100, 150), [], wires)
    points = [tuple(p) for p in route["points"]]
    # It may cross y=100 at a right angle but must not bend on it or run along it.
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        assert not (ay == by == 100)
    for p in points[1:-1]:
        assert p[1] != 100


def test_router_can_tap_an_existing_wire_of_its_own_net() -> None:
    wires = [{"from": "(0,0)", "to": "(200,0)"}]
    own = {(x, 0) for x in range(0, 201, 10)}
    route = route_orthogonal(
        Point(0, 0), Point(150, 100), [], wires, sources=own, friendly_points=own
    )
    # Starting from the nearest point of the same net is shorter than starting at (0,0).
    assert route["points"][0] != [0, 0]
    assert route["overlap_length"] == 0
