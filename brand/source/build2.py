"""Teresis: 25 versions of concept 2 (Keystone Facet), each authored on a non-square grid.

Rows 1-4: every polygon vertex is a lattice point and every edge runs along a grid line
(checked by `validate`). Row 5 is built from whole kite cells, merged without seams.
    python3 build2.py -> teresis-25.html
"""

from __future__ import annotations

import json
import math
from fractions import Fraction as F
from pathlib import Path

from build import kite_tiling, union_paths  # reuse the kite tiling + seamless union

OUT = Path(__file__).resolve().parent
SQ3 = math.sqrt(3)


class Grid:
    def __init__(self, name, to_xy, line_ok, lines_svg):
        self.name, self.to_xy, self.line_ok, self.lines_svg = name, to_xy, line_ok, lines_svg


def _even(v):
    return F(v).denominator == 1 and int(v) % 2 == 0


def _int(v):
    return F(v).denominator == 1


def _long(p, d, to_xy, reach=60):
    a = to_xy((p[0] - d[0] * reach, p[1] - d[1] * reach))
    b = to_xy((p[0] + d[0] * reach, p[1] + d[1] * reach))
    return f"M{a[0]:.1f},{a[1]:.1f}L{b[0]:.1f},{b[1]:.1f}"


# 1. equilateral triangles, horizontal rows: (u, r) -> x = 60 + 6u, y = 10.392 r ; s = 12
def tri_xy(p):
    return 60 + 6 * float(p[0]), 6 * SQ3 * float(p[1])


def tri_ok(p, q):
    du, dr = q[0] - p[0], q[1] - p[1]
    if dr == 0:
        return _int(p[1])
    if du == dr:
        return _even(p[0] - p[1])
    if du == -dr:
        return _even(p[0] + p[1])
    return False


def tri_lines():
    out = []
    for k in range(-40, 41):
        out.append(_long((0, k), (1, 0), tri_xy))
        out.append(_long((2 * k, 0), (1, 1), tri_xy))
        out.append(_long((2 * k, 0), (-1, 1), tri_xy))
    return "".join(out)


# 2. 45-degree triangles (squares cut by both diagonals), shifted so a square centre sits on the axis:
#    (A, B) -> x = 60 + 7A, y = 7B ; corners at odd/odd, centres at even/even ; square = 14
def t45_xy(p):
    return 60 + 7 * float(p[0]), 7 * float(p[1])


def t45_ok(p, q):
    da, db = q[0] - p[0], q[1] - p[1]
    if da == 0:
        return _int(p[0]) and int(p[0]) % 2 == 1
    if db == 0:
        return _int(p[1]) and int(p[1]) % 2 == 1
    if da == db:
        return _even(p[0] - p[1])
    if da == -db:
        return _even(p[0] + p[1])
    return False


def t45_lines():
    out = []
    for k in range(-41, 42, 2):
        out.append(_long((k, 0), (0, 1), t45_xy))
        out.append(_long((0, k), (1, 0), t45_xy))
    for k in range(-60, 61, 2):
        out.append(_long((k, 0), (1, 1), t45_xy))
        out.append(_long((k, 0), (-1, 1), t45_xy))
    return "".join(out)


# 3. 30-60-90 triangles (each equilateral triangle cut by its medians): same (X, Y) frame as row 1,
#    plus vertical lines (X integer) and 30-degree lines (X -/+ 3Y even).
def kis_ok(p, q):
    dx, dy = q[0] - p[0], q[1] - p[1]
    if dx == 0:
        return _int(p[0])
    if dy == 0:
        return _int(p[1])
    if dx == dy:
        return _even(p[0] - p[1])
    if dx == -dy:
        return _even(p[0] + p[1])
    if dx == 3 * dy:
        return _even(p[0] - 3 * p[1])
    if dx == -3 * dy:
        return _even(p[0] + 3 * p[1])
    return False


def kis_lines():
    out = [tri_lines()]
    for k in range(-60, 61):
        out.append(_long((k, 0), (0, 1), tri_xy))
    for k in range(-120, 121, 2):
        out.append(_long((k, 0), (3, 1), tri_xy))
        out.append(_long((k, 0), (-3, 1), tri_xy))
    return "".join(out)


# 4. isometric grid (vertical + 30-degree lines): (c, v) -> x = 60 + 10.392c, y = 6v ; c+v even
def iso_xy(p):
    return 60 + 6 * SQ3 * float(p[0]), 6 * float(p[1])


def iso_ok(p, q):
    dc, dv = q[0] - p[0], q[1] - p[1]
    if dc == 0:
        return _int(p[0])
    if dc == dv:
        return _even(p[1] - p[0])
    if dc == -dv:
        return _even(p[1] + p[0])
    return False


def iso_lines():
    out = []
    for k in range(-40, 41):
        out.append(_long((k, 0), (0, 1), iso_xy))
    for k in range(-80, 81, 2):
        out.append(_long((0, k), (1, 1), iso_xy))
        out.append(_long((0, k), (1, -1), iso_xy))
    return "".join(out)


TRI = Grid("Triangles · 60°", tri_xy, tri_ok, tri_lines)
T45 = Grid("Triangles · 45°", t45_xy, t45_ok, t45_lines)
KIS = Grid("Triangles · 30-60-90", tri_xy, kis_ok, kis_lines)
ISO = Grid("Isometric", iso_xy, iso_ok, iso_lines)


def mirror(poly):
    return [(-x, y) for x, y in reversed(poly)]


def sym(*left):
    """Left-side polygons plus their mirror images."""
    out = []
    for p in left:
        out += [p, mirror(p)]
    return out


def fr(*pts):
    return [(F(x), F(y)) for x, y in pts]


T = F(1, 3)

# ----------------------------------------------------------------------------- row 1: 60 degrees
GEM60 = fr((0, 0), (2, 2), (0, 4), (-2, 2))
R1 = [
    ("Keystone 60", "Concept 2 on a 60° grid: the gem between two parallel chevrons.",
     [fr((0, 0), (3, 3), (0, 6), (-3, 3))] + sym(fr((-5, 3), (-7, 3), (-3, 7), (-1, 7)))),
    ("Hex Vessel", "One hexagon with a V cut out — a cell that holds the gem.",
     [GEM60, fr((-2, 0), (-4, 0), (-8, 4), (-4, 8), (4, 8), (8, 4), (4, 0), (2, 0), (4, 2), (0, 6), (-4, 2))]),
    ("Wing Keep", "Three stepped feathers: Hermes' wing around the kept gem.",
     [fr((0, 0), (3, 3), (0, 6), (-3, 3))]
     + sym(fr((-2, 0), (-10, 0), (-11, 1), (-3, 1)), fr((-4, 2), (-10, 2), (-11, 3), (-5, 3)),
           fr((-4, 4), (-8, 4), (-7, 5), (-3, 5)))),
    ("Shield Keep", "An inverted-triangle shield with the gem set into its top.",
     [GEM60, fr((-2, 0), (-8, 0), (0, 8), (8, 0), (2, 0), (4, 2), (0, 6), (-4, 2))]),
    ("Key Teeth", "A deep cup whose seam zigzags like the bit of a key.",
     [GEM60,
      fr((-4, 2), (-10, 2), (-3, 9), (-1, 9), (-2, 8), (-1, 7), (-2, 6), (-1, 5), (-2, 4)),
      fr((4, 2), (1, 5), (0, 6), (1, 7), (0, 8), (1, 9), (3, 9), (10, 2))]),
]

# ----------------------------------------------------------------------------- row 2: 45 degrees
GEM45 = fr((0, 0), (3, 3), (0, 6), (-3, 3))
R2 = [
    ("Keystone 45", "The original concept, rebuilt exactly on a 45° grid.",
     [GEM45] + sym(fr((-5, 3), (-1, 7), (-1, 11), (-7, 5), (-7, 3)))),
    ("Octagon Seal", "An octagon seal split into gem and cradle by one Y-shaped cut.",
     [GEM45] + sym(fr((-1, -1), (-3, -1), (-7, 3), (-7, 7), (-3, 11), (-1, 11), (-1, 7), (-5, 3)))),
    ("Version Stack", "Two chevrons under the gem — the kept history of a fact.",
     [GEM45] + sym(fr((-5, 3), (-1, 7), (-1, 9), (-7, 3)), fr((-7, 5), (-1, 11), (-1, 13), (-9, 5)))),
    ("Gem Keyhole", "One solid with a diamond pocket and slot: a keyhole that holds a gem.",
     [fr((0, 0), (2, 2), (0, 4), (-2, 2)),
      fr((0, -6), (-10, 4), (-1, 13), (-1, 5), (-4, 2), (0, -2), (4, 2), (1, 5), (1, 13), (10, 4))]),
    ("Gem T", "A gemstone profile; the cut between crown and pavilion spells T.",
     [fr((-3, 1), (3, 1), (7, 5), (-7, 5))] + sym(fr((-7, 7), (-1, 7), (-1, 13)))),
]

# ----------------------------------------------------------------------------- row 3: 30-60-90
def phex(m, yc):
    """Pointy-top hexagon of 'radius' m centred on the axis at row yc (yc even)."""
    return fr((0, yc - 2 * m), (3 * m, yc - m), (3 * m, yc + m), (0, yc + 2 * m), (-3 * m, yc + m), (-3 * m, yc - m))


R3 = [
    ("Facet Keystone", "Concept 2 with vertical walls and a straight centre channel.",
     [GEM60] + sym(fr((-4, 2), (-1, 5), (-1, 9), (-6, 4), (-6, 2)))),
    ("Hex Cup", "A hexagonal gem resting in a hexagonal cup.",
     [phex(1, 2), fr((-9, 2), (-6, 2), (-6, 4), (0, 6), (6, 4), (6, 2), (9, 2), (9, 5), (0, 8), (-9, 5))]),
    ("Hex Brackets", "Two hex halves guarding one cell: ( ⬢ ).",
     [phex(1, 0)] + sym([(F(-1), F(-17, 3)), (F(-9), F(-3)), (F(-9), F(3)), (F(-1), F(17, 3)),
                         (F(-1), F(11, 3)), (F(-6), F(2)), (F(-6), F(-2)), (F(-1), F(-11, 3))])),
    ("Hex T", "A hexagon cut by a negative T: the crown kept above, two halves below.",
     [fr((0, -6), (9, -3), (9, -1), (-9, -1), (-9, -3))]
     + sym([(F(-9), F(0)), (F(-1), F(0)), (F(-1), F(17, 3)), (F(-9), F(3))])),
    ("Winged Hex", "A hexagonal gem on two long 30° wings.",
     [phex(1, 2)] + sym([(F(-9), F(3)), (F(-1), F(17, 3)), (F(-1), F(23, 3)), (F(-15), F(3))])),
]

# ----------------------------------------------------------------------------- row 4: isometric
def cube(n, oc=0, ov=0, faces=("top", "left", "right"), lift=0):
    """Isometric cube (radius n) with a one-line channel between faces; centre (oc, ov)."""
    top = fr((0, -2 * n), (n - 1, -n - 1), (0, -2), (-(n - 1), -n - 1))
    left = fr((-n, 2 - n), (-1, 1), (-1, 2 * n - 1), (-n, n))
    out = []
    for f in faces:
        poly = {"top": top, "left": left, "right": mirror(left)}[f]
        dv = lift if f == "top" else 0
        out.append([(x + oc, y + ov + dv) for x, y in poly])
    return out


R4 = [
    ("Kept Cube", "Concept 2 is a cube: the gem is its top face, the cradle its walls.", cube(6)),
    ("Lifted Lid", "The top face floats off an open box: something is kept inside.",
     cube(6, faces=("left", "right")) + cube(6, faces=("top",), lift=-4)),
    ("Wire Cube", "16 flipped: the cuts become the ink — a wireframe cube.",
     [fr((0, -14), (7, -7), (7, 7), (0, 14), (-7, 7), (-7, -7)),
      fr((0, -10), (4, -6), (0, -2), (-4, -6))] + sym(fr((-5, -3), (-1, 1), (-1, 9), (-5, 5)))),
    ("Memory Stack", "A kept cube on two slabs — reads as a database.",
     cube(4) + sym(fr((-4, 6), (-1, 9), (-1, 13), (-4, 10)), fr((-4, 12), (-1, 15), (-1, 19), (-4, 16)))),
    ("Lidded Cube", "One solid base under a gem lid: the box and its keepsake.",
     [fr((0, -12), (6, -6), (0, 0), (-6, -6)), fr((-6, -4), (0, 2), (6, -4), (6, 6), (0, 12), (-6, 6))]),
]


def validate(grid, polys, name):
    bad = []
    for poly in polys:
        for i in range(len(poly)):
            p, q = poly[i], poly[(i + 1) % len(poly)]
            if not grid.line_ok(p, q):
                bad.append((p, q))
    if bad:
        raise SystemExit(f"{name}: {len(bad)} edge(s) off-grid, e.g. {bad[0]}")


def poly_path(polys, to_xy):
    return " ".join("M" + " L".join("%.2f,%.2f" % to_xy(p) for p in poly) + " Z" for poly in polys)


# ----------------------------------------------------------------------------- row 5: kites
KT = kite_tiling(12)
K_NAMES = ["E", "SE", "SW", "W", "NW", "NE"]


def kite_cells(pred):
    chosen = []
    for keys, meta in KT.cells:
        pts = [KT.xy(k) for k in keys]
        cx = sum(p[0] for p in pts) / 4
        cy = sum(p[1] for p in pts) / 4
        hx, hy = meta["c"]
        if pred(cx, cy, hx, hy, K_NAMES[meta["k"]]):
            chosen.append(keys)
    return chosen


H = 6 * SQ3  # hex half-height for edge 12; neighbour centres: (+-18, +-H) and (0, +-2H)


def at(hx, hy, ux, uy):
    return abs(hx - (60 + ux)) < 1 and abs(hy - uy) < 1


def k21(cx, cy, hx, hy, k):  # Kite Gem: a six-kite hexagon held by the inner kites of its neighbours
    if at(hx, hy, 0, 0):
        return True
    for ux, want in ((-18, {"E", "SE"}), (18, {"W", "SW"})):
        if at(hx, hy, ux, H) and k in want:
            return True
    for ux, want in ((-18, {"NE", "E"}), (18, {"NW", "W"})):
        if at(hx, hy, ux, 3 * H) and k in want:
            return True
    return at(hx, hy, -36, 2 * H) and k in {"NE", "E"} or at(hx, hy, 36, 2 * H) and k in {"NW", "W"}


def k22(cx, cy, hx, hy, k):  # Keystone Arch: kite voussoirs around a kept keystone
    dx, dy = cx - 60, cy - 2 * H
    r = math.hypot(dx, dy)
    if at(hx, hy, 0, 0) and k in {"SE", "SW"}:
        return True
    return 22 <= r <= 40 and dy <= 4 and abs(dx) >= 10


def k23(cx, cy, hx, hy, k):  # Triangle Keep: kites gather into triangles - gem above, two below
    def tri(x0, y0, up):
        # equilateral triangle of hex centres; select kites whose centroid lies inside
        h = 36 * SQ3 / 2
        y = cy - y0
        if up:
            return 0 <= y <= h and abs(cx - x0) <= (y / SQ3)
        return -h <= y <= 0 and abs(cx - x0) <= (-y / SQ3)
    return tri(60, -2 * H, True) or tri(42, 4 * H, False) or tri(78, 4 * H, False)


def k24(cx, cy, hx, hy, k):  # Kite Bloom: a full flower, its lower neighbours open like hands
    if at(hx, hy, 0, 0):
        return True
    if at(hx, hy, -18, H):
        return k in {"SW", "W", "SE"}
    if at(hx, hy, 18, H):
        return k in {"SE", "E", "SW"}
    if at(hx, hy, -36, 0):
        return k in {"SE", "E"}
    if at(hx, hy, 36, 0):
        return k in {"SW", "W"}
    return False


def k25(cx, cy, hx, hy, k):  # Kite Star Keep: six-point bloom of kites around a kept core
    if at(hx, hy, 0, 0):
        return True
    ring = {(0, -2 * H): {"SE", "SW"}, (0, 2 * H): {"NE", "NW"},
            (18, -H): {"SW", "W"}, (-18, -H): {"SE", "E"},
            (18, H): {"NW", "W"}, (-18, H): {"NE", "E"}}
    for (ux, uy), want in ring.items():
        if at(hx, hy, ux, uy) and k in want:
            return False
    return any(at(hx, hy, ux, uy) for ux, uy in ring) and abs(cx - 60) > 0.5 or False


R5 = [
    ("Kite Gem", "A six-kite gem held by the inner kites of its neighbours.", k21),
    ("Keystone Arch", "Kites as the stones of an arch; the keystone is kept at the crown.", k22),
    ("Triangle Keep", "Kites gather into triangles: one kept above, two holding below.", k23),
    ("Kite Bloom", "A full flower whose lower neighbours open like hands.", k24),
    ("Kite Halo", "A ring of kites around a kept core, each petal turned outward.", k25),
]


def frame(xs, ys, pad=1.14):
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    side = max(x1 - x0, y1 - y0) * pad
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return f"{cx - side / 2:.2f} {cy - side / 2:.2f} {side:.2f} {side:.2f}", abs(cx - 60)


def kite_lines():
    seen, segs = set(), []
    for keys, _ in KT.cells:
        for i in range(4):
            a, b = keys[i], keys[(i + 1) % 4]
            e = (a, b) if a < b else (b, a)
            if e in seen:
                continue
            seen.add(e)
            (x1, y1), (x2, y2) = KT.xy(a), KT.xy(b)
            if -80 < x1 < 200 and -80 < y1 < 200:
                segs.append(f"M{x1:.1f},{y1:.1f}L{x2:.1f},{y2:.1f}")
    return "".join(segs)


def main():
    tiles = []
    n = 0
    for grid, row in ((TRI, R1), (T45, R2), (KIS, R3), (ISO, R4)):
        lines = grid.lines_svg()
        for name, idea, polys in row:
            n += 1
            validate(grid, polys, name)
            pts = [grid.to_xy(p) for poly in polys for p in poly]
            vb, asym = frame([p[0] for p in pts], [p[1] for p in pts])
            tiles.append({"n": f"{n:02d}", "name": name, "idea": idea, "row": grid.name,
                          "path": poly_path(polys, grid.to_xy), "vb": vb, "lines": lines, "asym": round(asym, 2)})
    import circles
    flower = circles.flower_lines()
    for name, idea, fn in circles.DESIGNS:
        n += 1
        polys, cons = fn()
        pts = [p for poly in polys for p in poly]
        vb, asym = frame([p[0] for p in pts], [p[1] for p in pts])
        path = " ".join("M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in poly) + " Z" for poly in polys)
        lines = flower + "".join(circles.circle_path(x, y, r) for x, y, r in cons)
        tiles.append({"n": f"{n:02d}", "name": name, "idea": idea, "row": "Circles",
                      "path": path, "vb": vb, "lines": lines, "asym": round(asym, 2)})
    html = (OUT / "sheet.template.html").read_text().replace("/*TILES*/[]", json.dumps(tiles))
    (OUT / "teresis-25.html").write_text(html)
    marks = OUT / "marks"
    marks.mkdir(exist_ok=True)
    for t in tiles:
        (marks / f"{t['n']}.svg").write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{t["vb"]}"><path d="{t["path"]}" fill="#000" fill-rule="evenodd"/></svg>')
        print(t["n"], t["name"].ljust(15), "offset", t["asym"])


if __name__ == "__main__":
    main()
