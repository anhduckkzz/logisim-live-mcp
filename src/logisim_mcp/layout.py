from __future__ import annotations

from dataclasses import dataclass
import heapq
import math
from typing import Any, Iterable

from .models import Point


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    def inflate(self, amount: int) -> "Rect":
        return Rect(
            self.left - amount,
            self.top - amount,
            self.right + amount,
            self.bottom + amount,
        )

    def contains(self, point: tuple[int, int], *, strict: bool = False) -> bool:
        x, y = point
        if strict:
            return self.left < x < self.right and self.top < y < self.bottom
        return self.left <= x <= self.right and self.top <= y <= self.bottom

    def overlaps(self, other: "Rect") -> bool:
        return not (
            self.right <= other.left
            or other.right <= self.left
            or self.bottom <= other.top
            or other.bottom <= self.top
        )


@dataclass(frozen=True)
class Segment:
    start: tuple[int, int]
    end: tuple[int, int]

    @property
    def horizontal(self) -> bool:
        return self.start[1] == self.end[1]

    @property
    def vertical(self) -> bool:
        return self.start[0] == self.end[0]

    def normalized(self) -> "Segment":
        return self if self.start <= self.end else Segment(self.end, self.start)


def _int_property(properties: dict[str, str], name: str, default: int) -> int:
    try:
        return int(properties.get(name, default))
    except (TypeError, ValueError):
        aliases = {"narrow": 30, "medium": 50, "wide": 70}
        return aliases.get(str(properties.get(name, "")).lower(), default)


def _rotate_rect(rect: Rect, facing: str) -> Rect:
    if facing == "east":
        return rect
    corners = (
        (rect.left, rect.top),
        (rect.left, rect.bottom),
        (rect.right, rect.top),
        (rect.right, rect.bottom),
    )
    if facing == "west":
        rotated = [(-x, -y) for x, y in corners]
    elif facing == "north":
        rotated = [(y, -x) for x, y in corners]
    else:  # south
        rotated = [(-y, x) for x, y in corners]
    xs, ys = zip(*rotated)
    return Rect(min(xs), min(ys), max(xs), max(ys))


def component_footprint(component: dict[str, Any]) -> Rect:
    """Estimate v5 component bounds from the upstream factory conventions.

    Exact formulas are used for standard gates, pins and DIP-style TTL devices;
    conservative bounds are used for other factories so routing stays outside
    the visible body even when a component has custom attributes.
    """
    exact = component.get("bounds")
    if isinstance(exact, dict) and exact.get("width") is not None:
        # Exact bounds reported by Logisim through the live plugin.
        return Rect(
            int(exact["x"]),
            int(exact["y"]),
            int(exact["x"]) + int(exact["width"]),
            int(exact["y"]) + int(exact["height"]),
        )
    point = Point.parse(component["location"])
    x, y = point.x, point.y
    name = str(component.get("name") or "")
    library = str(component.get("library") or "")
    props = component.get("properties") or {}
    facing = str(props.get("facing", "east")).lower()

    if library == "1" and name in {"Buffer", "NOT Gate"}:
        width = 30 if name == "NOT Gate" else 20
        local = Rect(-width, -10, 0, 10)
    elif library == "1" and ("Gate" in name or name in {"Controlled Buffer", "Controlled Inverter"}):
        width = _int_property(props, "size", 50)
        inputs = max(2, _int_property(props, "inputs", 2))
        height = max(width, 10 * (inputs if inputs % 2 else inputs + 1))
        local = Rect(-width, -(height // 2), 0, math.ceil(height / 2))
    elif library == "0" and name in {"Pin", "Probe", "Clock"}:
        # Evolution's new single-bit pin/probe shape is 40x20 and the anchor is
        # the connection point at the facing side.
        local = Rect(-40, -10, 0, 10)
    elif library in {"6", "A"} or (name.isdigit() and name.startswith("74")):
        pins = _int_property(props, "pins", 14)
        local = Rect(0, -30, max(80, pins * 10), 30)
    else:
        width = _int_property(props, "layoutWidth", 60)
        height = _int_property(props, "layoutHeight", 40)
        local = Rect(-(width // 2), -(height // 2), math.ceil(width / 2), math.ceil(height / 2))

    rotated = _rotate_rect(local, facing)
    return Rect(x + rotated.left, y + rotated.top, x + rotated.right, y + rotated.bottom)


def component_port_axes(component: dict[str, Any]) -> list[tuple[int, int]]:
    """Return anchor/pin points whose short row/column corridors should stay clear."""
    exact = component.get("port_points")
    if exact is not None:
        return [(int(x), int(y)) for x, y in exact]
    point = Point.parse(component["location"])
    name = str(component.get("name") or "")
    library = str(component.get("library") or "")
    props = component.get("properties") or {}
    facing = str(props.get("facing", "east")).lower()
    bounds = component_footprint(component)
    ports = [(point.x, point.y)]
    if library == "1" and name in {"Buffer", "NOT Gate"}:
        distance = 30 if name == "NOT Gate" else 20
        offsets = {
            "east": (-distance, 0),
            "west": (distance, 0),
            "north": (0, distance),
            "south": (0, -distance),
        }
        dx, dy = offsets.get(facing, offsets["east"])
        ports.append((point.x + dx, point.y + dy))
    elif library == "1" and "Gate" in name:
        size = _int_property(props, "size", 50)
        inputs = max(2, _int_property(props, "inputs", 2))
        if inputs <= 3:
            if size < 40:
                skip_start, skip_dist, skip_lower_even = -5, 10, 10
            elif size < 60 or inputs <= 2:
                skip_start, skip_dist, skip_lower_even = -10, 20, 20
            else:
                skip_start, skip_dist, skip_lower_even = -15, 30, 30
        elif inputs == 4 and size >= 60:
            skip_start, skip_dist, skip_lower_even = -5, 20, 0
        else:
            skip_start, skip_dist, skip_lower_even = -5, 10, 10
        for index in range(inputs):
            if inputs % 2:
                perpendicular = skip_start * (inputs - 1) + skip_dist * index
            else:
                perpendicular = skip_start * inputs + skip_dist * index
                if index >= inputs // 2:
                    perpendicular += skip_lower_even
                if inputs == 4 and size >= 60:
                    perpendicular -= 10
            offsets = {
                "east": (-size, perpendicular),
                "west": (size, perpendicular),
                "north": (perpendicular, size),
                "south": (perpendicular, -size),
            }
            dx, dy = offsets.get(facing, offsets["east"])
            ports.append((point.x + dx, point.y + dy))
    elif library in {"6", "A"} or (name.isdigit() and name.startswith("74")):
        pins = _int_property(props, "pins", 14)
        half = pins // 2
        width, height = bounds.right - bounds.left, bounds.bottom - bounds.top
        for index in range(pins):
            if index < half:
                offsets = {
                    "east": (index * 20 + 10, height - 30),
                    "west": (-10 - 20 * index, 30 - height),
                    "north": (width - 30, -10 - 20 * index),
                    "south": (30 - width, index * 20 + 10),
                }
            else:
                upper_index = index - half
                offsets = {
                    "east": (width - upper_index * 20 - 10, -30),
                    "west": (-width + upper_index * 20 + 10, 30),
                    "north": (-30, -height + upper_index * 20 + 10),
                    "south": (30, height - upper_index * 20 - 10),
                }
            dx, dy = offsets.get(facing, offsets["east"])
            ports.append((point.x + dx, point.y + dy))
    return ports


def _segment_interaction(candidate: Segment, existing: Segment) -> tuple[int, int]:
    """Return (overlap_length, interior_crossings) for orthogonal segments."""
    if not (candidate.horizontal or candidate.vertical):
        return 0, 0
    if not (existing.horizontal or existing.vertical):
        return 0, 0
    if candidate.horizontal and existing.horizontal and candidate.start[1] == existing.start[1]:
        a1, a2 = sorted((candidate.start[0], candidate.end[0]))
        b1, b2 = sorted((existing.start[0], existing.end[0]))
        return max(0, min(a2, b2) - max(a1, b1)), 0
    if candidate.vertical and existing.vertical and candidate.start[0] == existing.start[0]:
        a1, a2 = sorted((candidate.start[1], candidate.end[1]))
        b1, b2 = sorted((existing.start[1], existing.end[1]))
        return max(0, min(a2, b2) - max(a1, b1)), 0
    horizontal = candidate if candidate.horizontal else existing
    vertical = existing if candidate.horizontal else candidate
    hx1, hx2 = sorted((horizontal.start[0], horizontal.end[0]))
    vy1, vy2 = sorted((vertical.start[1], vertical.end[1]))
    cross = (vertical.start[0], horizontal.start[1])
    if hx1 <= cross[0] <= hx2 and vy1 <= cross[1] <= vy2:
        shared_endpoint = cross in {candidate.start, candidate.end} and cross in {
            existing.start,
            existing.end,
        }
        return 0, 0 if shared_endpoint else 1
    return 0, 0


def _wire_segments(wires: Iterable[dict[str, Any]]) -> list[Segment]:
    segments: list[Segment] = []
    for wire in wires:
        try:
            a, b = Point.parse(wire["from"]), Point.parse(wire["to"])
        except (KeyError, TypeError, ValueError):
            continue
        segments.append(Segment((a.x, a.y), (b.x, b.y)))
    return segments


def _compress_path(path: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if len(path) <= 2:
        return path
    result = [path[0]]
    previous_direction = None
    for index in range(1, len(path)):
        direction = (
            path[index][0] - path[index - 1][0],
            path[index][1] - path[index - 1][1],
        )
        if previous_direction is not None and direction != previous_direction:
            result.append(path[index - 1])
        previous_direction = direction
    result.append(path[-1])
    return result


def route_orthogonal(
    start: Point,
    end: Point,
    components: list[dict[str, Any]],
    wires: list[dict[str, Any]],
    *,
    grid_step: int = 10,
    clearance: int = 10,
    max_search_nodes: int = 120_000,
    strict: bool = True,
    sources: Iterable[tuple[int, int]] | None = None,
    targets: Iterable[tuple[int, int]] | None = None,
    friendly_points: Iterable[tuple[int, int]] | None = None,
) -> dict[str, Any]:
    """A* orthogonal router optimized for readable Logisim schematics.

    With ``strict`` (default) the route never creates an accidental electrical connection.
    Logisim joins wires only at wire ends and component ports, but it also splits a wire where
    another wire end or a port touches its middle. So the route may cross an existing wire at a
    right angle, yet it must not run along one, bend on one, or pass through any port or wire
    end other than its own start and end.
   
    ``sources``/``targets`` add alternative start/end points (typically every grid point of the
    wires already on the source/target net, so a new wire can tap an existing one), and
    ``friendly_points`` are points of those nets that the route may touch freely.
    """
    if grid_step < 5 or grid_step > 50:
        raise ValueError("grid_step must be between 5 and 50")
    if clearance < 0 or clearance > 100:
        raise ValueError("clearance must be between 0 and 100")
    origin, target = (start.x, start.y), (end.x, end.y)
    if origin == target:
        raise ValueError("A wire must have two different endpoints")
    for label, point in (("start", origin), ("end", target)):
        if point[0] % grid_step or point[1] % grid_step:
            raise ValueError(f"Smart-route {label} must align to the {grid_step}-unit grid")

    base_rects = [component_footprint(component) for component in components]
    obstacles = [rect.inflate(clearance) for rect in base_rects]
    existing = _wire_segments(wires)
    friendly = set(friendly_points or ())
    start_set = {origin} | {tuple(p) for p in (sources or ()) if p[0] % grid_step == 0 and p[1] % grid_step == 0}
    goal_set = {target} | {tuple(p) for p in (targets or ()) if p[0] % grid_step == 0 and p[1] % grid_step == 0}
    friendly |= start_set | goal_set

    def _is_friendly(segment: Segment) -> bool:
        return segment.start in friendly and segment.end in friendly

    hostile = [segment for segment in existing if not _is_friendly(segment)]
    protected_ports = [
        port
        for component in components
        for port in component_port_axes(component)
        if port not in {origin, target}
    ]

    all_x = [origin[0], target[0]]
    all_y = [origin[1], target[1]]
    for rect in obstacles:
        all_x.extend((rect.left, rect.right))
        all_y.extend((rect.top, rect.bottom))
    for segment in existing:
        all_x.extend((segment.start[0], segment.end[0]))
        all_y.extend((segment.start[1], segment.end[1]))
    margin = max(100, clearance * 4)
    min_x = math.floor((min(all_x) - margin) / grid_step) * grid_step
    max_x = math.ceil((max(all_x) + margin) / grid_step) * grid_step
    min_y = math.floor((min(all_y) - margin) / grid_step) * grid_step
    max_y = math.ceil((max(all_y) + margin) / grid_step) * grid_step

    allowed_escape = {origin, target}
    for endpoint in (origin, target):
        for rect in obstacles:
            if not rect.contains(endpoint):
                continue
            candidates: list[list[tuple[int, int]]] = []
            for dx, dy in ((grid_step, 0), (-grid_step, 0), (0, grid_step), (0, -grid_step)):
                cells: list[tuple[int, int]] = []
                current = endpoint
                while rect.contains(current):
                    cells.append(current)
                    current = (current[0] + dx, current[1] + dy)
                cells.append(current)
                candidates.append(cells)
            shortest = min(len(cells) for cells in candidates)
            for cells in candidates:
                if len(cells) == shortest:
                    allowed_escape.update(cells)

    endpoint_or_port: set[tuple[int, int]] = set()
    on_wire: set[tuple[int, int]] = set()
    if strict:
        for component in components:
            endpoint_or_port.update(component_port_axes(component) if "port_points" in component else [])
        for segment in hostile:
            endpoint_or_port.add(segment.start)
            endpoint_or_port.add(segment.end)
            a, b = segment.normalized().start, segment.normalized().end
            if segment.horizontal:
                for x in range(a[0], b[0] + 1):
                    on_wire.add((x, a[1]))
            elif segment.vertical:
                for y in range(a[1], b[1] + 1):
                    on_wire.add((a[0], y))
        # A tap point that lies on another net's wire, port or wire end would short the nets.
        clash = on_wire | endpoint_or_port
        start_set = {p for p in start_set if p == origin or p not in clash}
        goal_set = {p for p in goal_set if p == target or p not in clash}
        endpoint_or_port -= friendly

    def blocked(point: tuple[int, int]) -> bool:
        if point in endpoint_or_port:
            return True  # would connect to someone else's port or wire end
        return point not in allowed_escape and any(rect.contains(point, strict=True) for rect in obstacles)

    def edge_cost(a: tuple[int, int], b: tuple[int, int], previous_dir: int) -> tuple[float, int, int]:
        direction = 0 if a[1] == b[1] else 1
        cost = 1.0
        if previous_dir != -1 and previous_dir != direction:
            cost += 2.5
        candidate = Segment(a, b)
        overlaps = crossings = 0
        for segment in existing:
            overlap, crossing = _segment_interaction(candidate, segment)
            overlaps += overlap
            crossings += crossing
        # Overlapping a wire is substantially worse than one clean crossing.
        cost += (overlaps / grid_step) * 80.0 + crossings * 12.0
        for px, py in protected_ports:
            if candidate.horizontal and candidate.start[1] == py:
                if min(abs(candidate.start[0] - px), abs(candidate.end[0] - px)) <= 80:
                    cost += 3.0
            elif candidate.vertical and candidate.start[0] == px:
                if min(abs(candidate.start[1] - py), abs(candidate.end[1] - py)) <= 80:
                    cost += 3.0
        return cost, direction, crossings

    goals = list(goal_set)

    def heuristic_to_goal(point: tuple[int, int]) -> float:
        return min(abs(point[0] - g[0]) + abs(point[1] - g[1]) for g in goals) / grid_step

    queue: list[tuple[float, float, int, int, int]] = []
    best: dict[tuple[int, int, int], float] = {}
    for start_point in start_set:
        # Prefer leaving from the port itself; tapping an existing wire costs a little more.
        start_cost = 0.0 if start_point == origin else 1.5
        best[(start_point[0], start_point[1], -1)] = start_cost
        heapq.heappush(
            queue,
            (start_cost + heuristic_to_goal(start_point), start_cost, start_point[0], start_point[1], -1),
        )
    parent: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    final_state: tuple[int, int, int] | None = None
    visited = 0
    while queue:
        _, cost_so_far, x, y, previous_dir = heapq.heappop(queue)
        state = (x, y, previous_dir)
        if cost_so_far != best.get(state):
            continue
        visited += 1
        if visited > max_search_nodes:
            break
        if (x, y) in goal_set:
            final_state = state
            break
        for dx, dy in ((grid_step, 0), (-grid_step, 0), (0, grid_step), (0, -grid_step)):
            neighbor = (x + dx, y + dy)
            if not (min_x <= neighbor[0] <= max_x and min_y <= neighbor[1] <= max_y):
                continue
            if blocked(neighbor):
                continue
            direction_here = 0 if dy == 0 else 1
            if strict:
                if previous_dir != -1 and previous_dir != direction_here and (x, y) in on_wire:
                    continue  # a bend on an existing wire would join the two nets
                step = Segment((x, y), neighbor)
                if any(_segment_interaction(step, segment)[0] > 0 for segment in hostile):
                    continue  # running along an existing wire merges it with this one
            increment, direction, _ = edge_cost((x, y), neighbor, previous_dir)
            next_state = (neighbor[0], neighbor[1], direction)
            new_cost = cost_so_far + increment
            if new_cost >= best.get(next_state, math.inf):
                continue
            best[next_state] = new_cost
            parent[next_state] = state
            arrival = 0.0 if neighbor == target or neighbor not in goal_set else 1.5
            heapq.heappush(queue, (new_cost + arrival + heuristic_to_goal(neighbor), new_cost, *next_state))

    if final_state is None:
        raise ValueError(
            "No clean orthogonal route was found without touching other wires or ports; move "
            "components farther apart, reduce clearance, or route through a free corridor with "
            "explicit connect_wire segments"
        )
    path: list[tuple[int, int]] = []
    state = final_state
    while True:
        path.append((state[0], state[1]))
        if state not in parent:
            break
        state = parent[state]
    path.reverse()
    points = _compress_path(path)
    routed_segments = [Segment(a, b) for a, b in zip(points, points[1:])]
    overlap_length = crossings = 0
    for routed in routed_segments:
        for prior in hostile:
            overlap, crossing = _segment_interaction(routed, prior)
            overlap_length += overlap
            crossings += crossing
    return {
        "points": [[x, y] for x, y in points],
        "segment_count": len(routed_segments),
        "turn_count": max(0, len(routed_segments) - 1),
        "crossing_count": crossings,
        "overlap_length": overlap_length,
        "visited_nodes": visited,
    }


def analyze_layout(
    components: list[dict[str, Any]], wires: list[dict[str, Any]]
) -> dict[str, Any]:
    rectangles = [component_footprint(component) for component in components]
    segments = _wire_segments(wires)
    component_overlaps: list[dict[str, int]] = []
    for left in range(len(rectangles)):
        for right in range(left + 1, len(rectangles)):
            if rectangles[left].overlaps(rectangles[right]):
                component_overlaps.append({"first": left, "second": right})

    wire_component_intersections: list[dict[str, int]] = []
    for wire_index, segment in enumerate(segments):
        if not (segment.horizontal or segment.vertical):
            continue
        for component_index, rect in enumerate(rectangles):
            if segment.start in {
                (rect.left, segment.start[1]),
                (rect.right, segment.start[1]),
                (segment.start[0], rect.top),
                (segment.start[0], rect.bottom),
            }:
                pass
            if segment.horizontal:
                lo, hi = sorted((segment.start[0], segment.end[0]))
                intersects = rect.top < segment.start[1] < rect.bottom and max(lo, rect.left) < min(hi, rect.right)
            else:
                lo, hi = sorted((segment.start[1], segment.end[1]))
                intersects = rect.left < segment.start[0] < rect.right and max(lo, rect.top) < min(hi, rect.bottom)
            if intersects and not (rect.contains(segment.start) or rect.contains(segment.end)):
                wire_component_intersections.append(
                    {"wire": wire_index, "component": component_index}
                )

    overlap_pairs: list[dict[str, int]] = []
    crossing_pairs: list[dict[str, int]] = []
    overlap_length = 0
    for left in range(len(segments)):
        for right in range(left + 1, len(segments)):
            overlap, crossing = _segment_interaction(segments[left], segments[right])
            if overlap:
                overlap_pairs.append({"first": left, "second": right, "length": overlap})
                overlap_length += overlap
            if crossing:
                crossing_pairs.append({"first": left, "second": right})
    diagonal_wires = [
        index for index, segment in enumerate(segments) if not (segment.horizontal or segment.vertical)
    ]
    penalty = (
        len(component_overlaps) * 20
        + len(wire_component_intersections) * 20
        + len(overlap_pairs) * 12
        + len(crossing_pairs) * 4
        + len(diagonal_wires) * 10
    )
    return {
        "clean": not (
            component_overlaps
            or wire_component_intersections
            or overlap_pairs
            or diagonal_wires
        ),
        "quality_score": max(0, 100 - penalty),
        "component_overlaps": component_overlaps,
        "wire_component_intersections": wire_component_intersections,
        "wire_overlaps": overlap_pairs,
        "wire_overlap_length": overlap_length,
        "wire_crossings": crossing_pairs,
        "diagonal_wires": diagonal_wires,
    }
