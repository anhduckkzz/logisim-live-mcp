"""Text views of a circuit so it can be understood without a screenshot.

* ``netlist_text``: every component, its exact ports and which net each port is on, every net
  with its drivers/loads/value, and every problem, in a compact form.
* ``ascii_view``: a character drawing of the layout on the Logisim grid (1 char = 10 units by
  default) with coordinate rulers, device boxes, wire shapes, junctions and port markers.
* ``truth_table_text``: simulation results as an aligned table.
"""

from __future__ import annotations

import math
from typing import Any

# wire direction bits
_N, _E, _S, _W = 1, 2, 4, 8
_WIRE_CHARS = {
    _E: "─", _W: "─", _E | _W: "─",
    _N: "│", _S: "│", _N | _S: "│",
    _E | _S: "┌", _W | _S: "┐", _N | _E: "└", _N | _W: "┘",
    _E | _W | _S: "┬", _E | _W | _N: "┴", _N | _S | _E: "├", _N | _S | _W: "┤",
    _N | _E | _S | _W: "╋",
}
_CROSSING = "┼"  # two wires cross WITHOUT connecting


def _short_type(comp: dict[str, Any]) -> str:
    name = comp["name"]
    table = {
        "AND Gate": "AND", "OR Gate": "OR", "NAND Gate": "NAND", "NOR Gate": "NOR",
        "XOR Gate": "XOR", "XNOR Gate": "XNOR", "NOT Gate": "NOT", "Buffer": "BUF",
        "Odd Parity": "ODD", "Even Parity": "EVEN", "Controlled Buffer": "TRI",
        "Controlled Inverter": "TRI~", "Multiplexer": "MUX", "Demultiplexer": "DMX",
        "Decoder": "DEC", "Priority Encoder": "ENC", "Bit Selector": "SEL",
        "D Flip-Flop": "DFF", "T Flip-Flop": "TFF", "J-K Flip-Flop": "JKFF",
        "S-R Flip-Flop": "SRFF", "Register": "REG", "Counter": "CNT", "Adder": "ADD",
        "Subtractor": "SUB", "Comparator": "CMP", "Constant": "K", "Splitter": "SPL",
        "Tunnel": "TUN", "Clock": "CLK", "Probe": "PRB", "Pin": "PIN",
    }
    return table.get(name, name)


def _display_name(comp: dict[str, Any]) -> str:
    return comp.get("label") or comp["id"]


def netlist_text(data: dict[str, Any]) -> str:
    lines: list[str] = []
    ext = data.get("extent") or [0, 0, 0, 0]
    lines.append(
        f"CIRCUIT {data['circuit']}  extent x {ext[0]}..{ext[0] + ext[2]}  y {ext[1]}..{ext[1] + ext[3]}"
        f"  ({len(data['components'])} components, {len(data['wires'])} wire segments, "
        f"{len(data['nets'])} nets)"
    )
    if data.get("values_from"):
        lines.append(f"values from {data['values_from']}")
    lines.append("")
    lines.append("COMPONENTS  (name  type  @anchor  [box x,y,w,h]  ports: name(dir,width)@x,y->net)")
    for comp in data["components"]:
        head = f"  {_display_name(comp)}"
        typ = comp["name"]
        if comp.get("pin_type"):
            typ += f"({comp['pin_type']})"
        extra = []
        if comp.get("label"):
            extra.append(f"id={comp['id']}")
        if comp.get("facing") and comp.get("facing") != "east":
            extra.append(f"facing {comp['facing']}")
        if comp.get("width", 1) != 1:
            extra.append(f"{comp['width']} bits")
        b = comp.get("bounds") or [0, 0, 0, 0]
        ports = []
        for p in comp["ports"]:
            d = {"in": "in", "out": "out", "inout": "io"}[p["direction"]]
            w = "" if p["width"] == 1 else f",{p['width']}b"
            pin = f"#{p['pin']}" if p.get("pin") else ""
            ports.append(f"{p['name']}{pin}({d}{w})@{p['x']},{p['y']}->{p['net'] or 'UNCONNECTED'}")
        lines.append(
            f"{head}  {typ}  @{comp['loc'][0]},{comp['loc'][1]}  [{b[0]},{b[1]},{b[2]},{b[3]}]"
            + (f"  {' '.join(extra)}" if extra else "")
        )
        if comp.get("properties"):
            lines.append("      props: " + ", ".join(f"{k}={v}" for k, v in comp["properties"].items()))
        lines.append("      ports: " + "  ".join(ports))
    lines.append("")
    lines.append("NETS  (id [names] width =value : drivers -> loads)")
    for net in data["nets"]:
        names = f" [{', '.join(net['names'])}]" if net.get("names") else ""
        value = f" ={net['value']}" if net.get("value") is not None else ""
        drivers = ", ".join(net.get("drivers", []) + [f"{b}(io)" for b in net.get("bidirectional", [])])
        loads = ", ".join(net.get("loads", []))
        lines.append(
            f"  {net['id']}{names} {net['width']}b{value} : {drivers or 'NO DRIVER'} -> {loads or 'no loads'}"
            f"  ({net['wire_segments']} wires)"
        )
    lines.append("")
    problems = data.get("problems") or []
    if problems:
        lines.append(f"PROBLEMS ({len(problems)})")
        for p in problems:
            at = f" at {p['at'][0]},{p['at'][1]}" if p.get("at") else ""
            lines.append(f"  {p['severity']:7} {p['kind']}: {p['message']}{at}")
    else:
        lines.append("PROBLEMS none: every port is connected, no floating, conflicting or width-mismatched nets")
    return "\n".join(lines)


def problems_text(data: dict[str, Any]) -> str:
    problems = data.get("problems") or []
    counts: dict[str, int] = {}
    for p in problems:
        counts[p["severity"]] = counts.get(p["severity"], 0) + 1
    head = (
        f"{data['circuit']}: {len(data['components'])} components, {len(data['nets'])} nets, "
        + (", ".join(f"{n} {s}" for s, n in sorted(counts.items())) if counts else "no problems")
    )
    lines = [head]
    for p in problems:
        at = f" at {p['at'][0]},{p['at'][1]}" if p.get("at") else ""
        lines.append(f"  {p['severity']:7} {p['kind']}: {p['message']}{at}")
    return "\n".join(lines)


def ascii_view(
    data: dict[str, Any],
    *,
    region: list[int] | None = None,
    scale: int = 10,
    max_cols: int = 260,
    max_rows: int = 180,
) -> str:
    if scale < 5 or scale > 100:
        raise ValueError("scale must be between 5 and 100 Logisim units per character")
    comps = data["components"]
    wires = data["wires"]
    if region:
        x0, y0, x1, y1 = region
    else:
        xs: list[int] = []
        ys: list[int] = []
        for c in comps:
            b = c["bounds"]
            xs += [b[0], b[0] + b[2]]
            ys += [b[1], b[1] + b[3]]
        for w in wires:
            xs += [w["from"][0], w["to"][0]]
            ys += [w["from"][1], w["to"][1]]
        if not xs:
            return f"{data['circuit']} is empty"
        pad = 3 * scale
        x0, y0, x1, y1 = min(xs) - pad, min(ys) - scale, max(xs) + pad, max(ys) + scale
    x0 = math.floor(x0 / scale) * scale
    y0 = math.floor(y0 / scale) * scale
    cols = (x1 - x0) // scale + 1
    rows = (y1 - y0) // scale + 1
    if cols > max_cols or rows > max_rows:
        raise ValueError(
            f"view would be {cols}x{rows} characters; pass region=[x1,y1,x2,y2] to zoom in or a "
            f"larger scale (e.g. scale={scale * 2})"
        )

    def cell(x: float, y: float) -> tuple[int, int]:
        return round((x - x0) / scale), round((y - y0) / scale)

    grid = [[" "] * cols for _ in range(rows)]
    inside = lambda c, r: 0 <= c < cols and 0 <= r < rows  # noqa: E731

    # 1. device boxes
    names_placed: list[tuple[dict[str, Any], int, int, int, int]] = []
    for comp in comps:
        b = comp["bounds"]
        c0, r0 = cell(b[0], b[1])
        c1, r1 = cell(b[0] + b[2], b[1] + b[3])
        if c1 <= c0:
            c1 = c0 + 1
        if r1 <= r0:
            r1 = r0 + 1
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                if not inside(c, r):
                    continue
                if r in (r0, r1) and c in (c0, c1):
                    ch = {(r0, c0): "╔", (r0, c1): "╗", (r1, c0): "╚", (r1, c1): "╝"}[(r, c)]
                elif r in (r0, r1):
                    ch = "═"
                elif c in (c0, c1):
                    ch = "║"
                else:
                    ch = " "
                grid[r][c] = ch
        names_placed.append((comp, c0, r0, c1, r1))

    # 2. wires with junction shapes; crossings without a shared end are marked distinctly
    mask: dict[tuple[int, int], int] = {}
    ends: set[tuple[int, int]] = set()
    for w in wires:
        (ax, ay), (bx, by) = w["from"], w["to"]
        ca, cb = cell(ax, ay), cell(bx, by)
        ends.add(ca)
        ends.add(cb)
        if ca[1] == cb[1]:
            lo, hi = sorted((ca[0], cb[0]))
            for c in range(lo, hi + 1):
                bits = (_E if c < hi else 0) | (_W if c > lo else 0)
                mask[(c, ca[1])] = mask.get((c, ca[1]), 0) | bits
        elif ca[0] == cb[0]:
            lo, hi = sorted((ca[1], cb[1]))
            for r in range(lo, hi + 1):
                bits = (_S if r < hi else 0) | (_N if r > lo else 0)
                mask[(ca[0], r)] = mask.get((ca[0], r), 0) | bits
    for (c, r), bits in mask.items():
        if not inside(c, r) or bits == 0:
            continue
        ch = _WIRE_CHARS.get(bits, "+")
        if bits == (_N | _E | _S | _W) and (c, r) not in ends:
            ch = _CROSSING
        grid[r][c] = ch

    # 3. ports: I/O/B when connected, i/o/b when unconnected
    for comp in comps:
        for p in comp["ports"]:
            c, r = cell(p["x"], p["y"])
            if not inside(c, r):
                continue
            letter = {"in": "i", "out": "o", "inout": "b"}[p["direction"]]
            grid[r][c] = letter.upper() if p.get("net") else letter

    # 4. names: inside the box when it fits, otherwise beside it on a free side
    legend: list[str] = []
    for comp, c0, r0, c1, r1 in names_placed:
        text = comp.get("label") or _short_type(comp)
        if comp.get("label") and comp["name"] not in ("Pin", "Tunnel", "Clock", "Probe", "Constant"):
            text = f"{_short_type(comp)} {comp['label']}"
        inner = c1 - c0 - 1
        mid = (r0 + r1) // 2
        placed = False
        if inner >= 1 and r1 - r0 >= 2:
            t = text[:inner]
            start = c0 + 1 + (inner - len(t)) // 2
            for i, ch in enumerate(t):
                if inside(start + i, mid) and grid[mid][start + i] == " ":
                    grid[mid][start + i] = ch
            placed = len(t) == len(text)
        if not placed:
            for start in (c0 - len(text) - 1, c1 + 2):
                span = range(start, start + len(text))
                if all(inside(c, mid) and grid[mid][c] == " " for c in span) and inside(start - 1, mid):
                    for i, ch in enumerate(text):
                        grid[mid][start + i] = ch
                    placed = True
                    break
        if not placed:
            legend.append(f"  {text} = {comp['id']} (box at col {c0}, row {r0})")

    # rulers
    gutter = max(len(str(y0 + (rows - 1) * scale)), len(str(y0))) + 1
    ruler = [" "] * cols
    for c in range(0, cols, 10):
        label = str(x0 + c * scale)
        for i, ch in enumerate(label):
            if c + i < cols:
                ruler[c + i] = ch
    tick = ["┬" if c % 10 == 0 else ("·" if c % 5 == 0 else " ") for c in range(cols)]
    out = [
        f"{data['circuit']}: 1 char = {scale} units, x from {x0}, y from {y0}"
        f"  (cell col c, row r = point ({x0}+{scale}*c, {y0}+{scale}*r))",
        " " * gutter + "".join(ruler).rstrip(),
        " " * gutter + "".join(tick).rstrip(),
    ]
    for r in range(rows):
        y = y0 + r * scale
        side = str(y) if r % 5 == 0 else ""
        out.append(side.rjust(gutter - 1) + " " + "".join(grid[r]).rstrip())
    out.append("")
    out.append(
        "legend: ╔═╗ device body; ─│┌┐└┘ wire; ┬┴├┤╋ connected junction; ┼ crossing (NOT connected);"
        " I/O/B port connected (in/out/bidir); i/o/b port NOT connected"
    )
    if legend:
        out.append("unlabelled in drawing:")
        out.extend(legend)
    return "\n".join(out)


def truth_table_text(result: dict[str, Any]) -> str:
    rows = result.get("rows") or []
    ins = list(rows[0]["in"].keys()) if rows else list(result.get("inputs", []))
    outs = list(result.get("outputs", []))
    watch = list(rows[0].get("watch", {}).keys()) if rows else []
    stepped = bool(result.get("sequential")) or not ins
    headers = (["step"] if stepped else []) + ins + ["|"] + outs + ([":"] + watch if watch else [])
    table = []
    for index, row in enumerate(rows, start=1):
        line = ([str(index)] if stepped else []) + [row["in"].get(n, "") for n in ins] + ["|"] + [
            row["out"].get(n, "") for n in outs
        ]
        if watch:
            line += [":"] + [row.get("watch", {}).get(n, "") for n in watch]
        if row.get("oscillating"):
            line.append("OSCILLATING")
        table.append(line)
    widths = [max(len(str(h)), *(len(str(r[i])) for r in table)) if table else len(str(h)) for i, h in enumerate(headers)]
    fmt = lambda cells: "  ".join(str(c).rjust(widths[i]) for i, c in enumerate(cells[: len(widths)])) + (  # noqa: E731
        "  " + " ".join(cells[len(widths):]) if len(cells) > len(widths) else ""
    )
    lines = [f"{result.get('circuit')}: {len(rows)} rows (x = floating, E = conflict)", fmt(headers)]
    lines += [fmt(r) for r in table]
    for w in result.get("warnings", []):
        lines.append(f"warning: {w}")
    return "\n".join(lines)
