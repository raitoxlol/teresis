"""Teresis mark explorations: 25 versions of concept 2 (Keystone Facet), each built on a non-square grid.

Every mark is a set of whole cells from a real tiling (triangles, 45-degree triangles, hexagons,
isometric rhombi, kites). A design is a shape predicate; the cells whose centroid falls inside are
filled, then merged into seamless outlines. So every edge lies on the grid by construction.

    python3 build.py  -> teresis-25.html (contact sheet) + marks/NN.svg
"""

from __future__ import annotations

import math
from pathlib import Path

OUT = Path(__file__).resolve().parent
SQ3 = math.sqrt(3)


# ----------------------------------------------------------------------------- tilings
class Tiling:
    """cells: list of (vertex keys, meta). key -> xy via self.xy. Keys are exact integers."""

    def __init__(self, name, cells, xy):
        self.name, self.cells, self.xy = name, cells, xy


def _ccw(keys, xy):
    pts = [xy(k) for k in keys]
    area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
               for i in range(len(pts)))
    return keys if area > 0 else list(reversed(keys))


def tri_tiling(s, span=26):
    """Equilateral triangles, horizontal rows. Key (u, r) with u+r even: x=60+u*s/2, y=r*h."""
    h = s * SQ3 / 2
    xy = lambda k: (60 + k[0] * s / 2, k[1] * h)
    cells = []
    for r in range(-span, span):
        for u in range(-2 * span, 2 * span):
            if (u + r) % 2:
                continue
            cells.append((_ccw([(u, r), (u + 2, r), (u + 1, r + 1)], xy), {}))
            cells.append((_ccw([(u + 1, r + 1), (u + 3, r + 1), (u + 2, r)], xy), {}))
    return Tiling("triangle", cells, xy)


def tetrakis_tiling(q, span=14):
    """Squares cut by both diagonals (45-degree grid). Keys doubled: corners even, centres odd."""
    xy = lambda k: (60 + k[0] * q / 2, k[1] * q / 2)
    cells = []
    for j in range(-span, span):
        for i in range(-span, span):
            a, b = 2 * i, 2 * j
            c = (a + 1, b + 1)
            corners = [(a, b), (a + 2, b), (a + 2, b + 2), (a, b + 2)]
            for t in range(4):
                cells.append((_ccw([corners[t], corners[(t + 1) % 4], c], xy), {}))
    return Tiling("45deg", cells, xy)


def _hex_centres(span):
    for r in range(-span, span):
        for u in range(-2 * span, 2 * span):
            if (u + r) % 2:
                continue
            q = (u - r) // 2
            if (q - r) % 3 == 0:
                yield u, r


_NB = [(2, 0), (1, 1), (-1, 1), (-2, 0), (-1, -1), (1, -1)]  # flat-top hex vertices around a centre


def hex_tiling(s, span=24):
    """Flat-top hexagons (edge s) on the triangular lattice."""
    h = s * SQ3 / 2
    xy = lambda k: (60 + k[0] * s / 2, k[1] * h)
    cells = [(_ccw([(u + du, r + dr) for du, dr in _NB], xy), {"c": xy((u, r))}) for u, r in _hex_centres(span)]
    return Tiling("hexagon", cells, xy)


def rhombille_tiling(s, span=24):
    """Isometric cubes: pointy-top hexagons (edge s) each split into top / left / right rhombi."""
    h = s * SQ3 / 2
    xy = lambda k: (60 + k[1] * h, k[0] * s / 2)  # transposed lattice -> pointy-top hexes
    cells = []
    for u, r in _hex_centres(span):
        v = [(u + du, r + dr) for du, dr in _NB]
        c = (u, r)
        for face, idx in (("a", (0, 1, 2)), ("b", (2, 3, 4)), ("c", (4, 5, 0))):
            keys = [c] + [v[i] for i in idx]
            pts = [xy(k) for k in keys]
            cx = sum(p[0] for p in pts) / 4
            cy = sum(p[1] for p in pts) / 4
            hx, hy = xy(c)
            # classify the rhombus by where it sits relative to its cube centre
            if cy < hy - 1 and abs(cx - hx) < 1:
                f = "top"
            else:
                f = "left" if cx < hx else "right"
            cells.append((_ccw(keys, xy), {"face": f, "c": (hx, hy)}))
    return Tiling("cube", cells, xy)


def kite_tiling(s, span=20):
    """Deltoidal trihexagonal: each flat-top hexagon (edge s) cut into 6 kites. Keys doubled."""
    h = s * SQ3 / 2
    xy = lambda k: (60 + k[0] * s / 4, k[1] * h / 2)
    cells = []
    for u, r in _hex_centres(span):
        c = (2 * u, 2 * r)
        v = [(2 * (u + du), 2 * (r + dr)) for du, dr in _NB]
        m = [((v[i][0] + v[(i + 1) % 6][0]) // 2, (v[i][1] + v[(i + 1) % 6][1]) // 2) for i in range(6)]
        for i in range(6):
            cells.append((_ccw([c, m[i - 1], v[i], m[i]], xy), {"c": xy(c), "k": i}))
    return Tiling("kite", cells, xy)


# ----------------------------------------------------------------------------- union
def union_paths(keys_list, xy):
    """Boundary of a union of cells sharing exact vertices -> SVG path (nonzero, holes reversed)."""
    edges = {}
    for keys in keys_list:
        for i in range(len(keys)):
            a, b = keys[i], keys[(i + 1) % len(keys)]
            if (b, a) in edges:
                del edges[(b, a)]
            else:
                edges[(a, b)] = True
    nxt = {}
    for a, b in edges:
        nxt.setdefault(a, []).append(b)
    loops = []
    while nxt:
        start = next(iter(nxt))
        loop, cur = [start], start
        while True:
            b = nxt[cur].pop()
            if not nxt[cur]:
                del nxt[cur]
            if b == start:
                break
            loop.append(b)
            cur = b
            if cur not in nxt:
                break
        loops.append(loop)
    d = []
    for loop in loops:
        pts = [xy(k) for k in loop]
        # drop collinear points
        clean = []
        n = len(pts)
        for i in range(n):
            p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % n]
            cross = (p1[0] - p0[0]) * (p2[1] - p1[1]) - (p1[1] - p0[1]) * (p2[0] - p1[0])
            if abs(cross) > 1e-6:
                clean.append(p1)
        if len(clean) >= 3:
            d.append("M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in clean) + " Z")
    return " ".join(d)


# ----------------------------------------------------------------------------- shape helpers
def diamond_d(x, y, cy, a, b):
    """Signed distance-like value from a diamond (|dx|/a + |dy|/b = 1); <= 0 inside."""
    dx, dy = abs(x - 60), abs(y - cy)
    return (dx * b + dy * a - a * b) / math.hypot(a, b)


def lower_band(x, y, cy, a, b):
    """Perpendicular distance from the diamond's lower edges (positive outside, below the equator)."""
    dx = abs(x - 60)
    return (dx * b + (y - cy) * a - a * b) / math.hypot(a, b)


def hex_flat(x, y, cx, cy, R):
    dx, dy = abs(x - cx), abs(y - cy)
    return dy <= R * SQ3 / 2 and dx + dy / SQ3 <= R


def hex_pointy(x, y, cx, cy, R):
    dx, dy = abs(x - cx), abs(y - cy)
    return dx <= R * SQ3 / 2 and dy + dx / SQ3 <= R


def tri_down(x, y, top, half):
    """Downward equilateral triangle with top edge at y=top, half-width `half`."""
    dx = abs(x - 60)
    return y >= top and dx <= half - (y - top) / SQ3


def octagon(x, y, cy, R, c):
    dx, dy = abs(x - 60), abs(y - cy)
    return dx <= R and dy <= R and dx + dy <= 2 * R - c


# ----------------------------------------------------------------------------- the 25 designs
# Each design: (tiling, predicate(x, y, meta) -> bool, name, one-line idea). Coordinates on 0..120.

def keystone(cy, a, b, g, w, ybot, gap, xmax=999):
    def f(x, y, m):
        if diamond_d(x, y, cy, a, b) <= 0:
            return True
        d = lower_band(x, y, cy, a, b)
        return g <= d <= g + w and cy <= y <= ybot and abs(x - 60) >= gap / 2 and abs(x - 60) <= xmax
    return f


T60 = tri_tiling(10)
T45 = tetrakis_tiling(14)
HEX = hex_tiling(7)
CUBE = rhombille_tiling(12)
KITE = kite_tiling(14)

A60, B60 = 1.0, SQ3  # 60-degree diamond proportions


def d02(x, y, m):  # Hex Vessel: one hexagon carved into gem + cradle
    a, b, cy = 13, 13 * SQ3, 44
    if diamond_d(x, y, cy, a, b) <= 0:
        return True
    return hex_flat(x, y, 60, 60, 47) and diamond_d(x, y, cy, a, b) >= 8 and abs(x - 60) >= 5


def d03(x, y, m):  # Wing Keep: stepped feathers (Hermes) cradling the gem
    a, b, cy = 11, 11 * SQ3, 40
    if diamond_d(x, y, cy, a, b) <= 0:
        return True
    d = lower_band(x, y, cy, a, b)
    ax = abs(x - 60)
    if ax < 5:
        return False
    tiers = [(8, 18, cy, 100), (27, 37, cy - 13, 88), (46, 56, cy - 26, 76)]
    return any(lo <= d <= hi and top <= y <= bot for lo, hi, top, bot in tiers)


def d04(x, y, m):  # Shield Keep: inverted triangle split by a Y channel
    a, b, cy = 12, 12 * SQ3, 38
    if diamond_d(x, y, cy, a, b) <= 0:
        return True
    return tri_down(x, y, 16, 50) and diamond_d(x, y, cy, a, b) >= 8 and abs(x - 60) >= 4


def d05(x, y, m):  # Key Teeth: thick cup whose seam is a zigzag key-bit
    a, b, cy = 12, 12 * SQ3, 34
    if diamond_d(x, y, cy, a, b) <= 0:
        return True
    d = lower_band(x, y, cy, a, b)
    seam = abs(x - 60) < 1  # the axis triangles alternate up/down -> zigzag teeth
    return 8 <= d <= 34 and cy - 4 <= y <= 98 and not seam


def d07(x, y, m):  # Octagon Seal
    a = b = 18
    cy = 44
    if diamond_d(x, y, cy, a, b) <= 0:
        return True
    return octagon(x, y, 60, 46, 26) and diamond_d(x, y, cy, a, b) >= 8 and abs(x - 60) >= 5


def d08(x, y, m):  # Version Stack: two chevron cradles = kept history
    a = b = 15
    cy = 28
    if diamond_d(x, y, cy, a, b) <= 0:
        return True
    d = lower_band(x, y, cy, a, b)
    if abs(x - 60) < 5:
        return False
    return (8 <= d <= 19 and cy <= y <= 80) or (28 <= d <= 39 and cy + 14 <= y <= 104)


def d09(x, y, m):  # Gem Keyhole: one solid with a diamond pocket and slot
    big = abs(x - 60) + abs(y - 58) <= 50
    hole = diamond_d(x, y, 46, 17, 17) <= 0
    slot = abs(x - 60) < 5 and y >= 46
    gem = diamond_d(x, y, 46, 8, 8) <= 0
    return gem or (big and not hole and not slot)


def d10(x, y, m):  # Gem T: diamond-gem profile split by a negative T (girdle + pavilion seam)
    crown = 22 <= y <= 46 and abs(x - 60) <= 22 + (y - 22)
    pavilion = y >= 46 and abs(x - 60) <= 46 - (y - 46)
    chan = (46 <= y <= 55) or (y > 55 and abs(x - 60) < 5)
    return (crown or pavilion) and not chan


def d11(x, y, m):  # Hive Keystone
    return keystone(40, 15, 15 * SQ3, 9, 15, 100, 8)(x, y, m)


def d12(x, y, m):  # Honey Cup: a flower of cells kept in a hex bowl
    gem = hex_flat(x, y, 60, 44, 15)
    bowl = hex_flat(x, y, 60, 50, 50) and not hex_flat(x, y, 60, 50, 31) and y >= 44
    return gem or bowl


def d13(x, y, m):  # Hex Brackets: two hex halves guarding one cell
    ring = hex_flat(x, y, 60, 60, 48) and not hex_flat(x, y, 60, 60, 30)
    return hex_flat(x, y, 60, 60, 12) or (ring and abs(x - 60) >= 8)


def d14(x, y, m):  # Hive Triad: three hexes, the top one kept
    return (hex_flat(x, y, 60, 30, 20) or hex_flat(x, y, 34, 75, 20) or hex_flat(x, y, 86, 75, 20))


def d15(x, y, m):  # Comb Wings
    a, b, cy = 13, 13 * SQ3, 36
    if diamond_d(x, y, cy, a, b) <= 0:
        return True
    d = lower_band(x, y, cy, a, b)
    if abs(x - 60) < 6:
        return False
    return (9 <= d <= 22 and cy - 6 <= y <= 96) or (31 <= d <= 44 and cy - 22 <= y <= 80)


def cube_face(x, y, cx, cy, R, gap):
    """Which face of a pointy-top cube (centre cx,cy radius R) the point sits on, honouring a Y gap."""
    if not hex_pointy(x, y, cx, cy, R):
        return None
    dx, dy = x - cx, y - cy
    # spokes: centre->upper-left (150deg), centre->upper-right (30deg), centre->down (90deg)
    def dist_to_ray(ax, ay):
        t = max(0.0, dx * ax + dy * ay)
        return math.hypot(dx - t * ax, dy - t * ay)
    spokes = [(-SQ3 / 2, -0.5), (SQ3 / 2, -0.5), (0.0, 1.0)]
    if min(dist_to_ray(*s) for s in spokes) < gap:
        return None
    if dy < 0 and abs(dx) < -dy * SQ3:
        return "top"
    return "left" if dx < 0 else "right"


def d16(x, y, m):  # Kept Cube: concept 2 IS a cube - the gem is its top face
    return cube_face(x, y, 60, 60, 48, 5.5) is not None


def d17(x, y, m):  # Lifted Lid: the top face floats above an open box
    f = cube_face(x, y, 60, 66, 42, 5.5)
    lid = cube_face(x, y + 16, 60, 66, 42, 5.5) == "top"
    return lid or f in ("left", "right")


def d18(x, y, m):  # Two-tone Cube: walls solid, gem drawn as cells of the lattice
    f = cube_face(x, y, 60, 60, 48, 0.1)
    if f in ("left", "right"):
        return True
    return f == "top" and m.get("face") == "top"


def d19(x, y, m):  # Cube Stack: kept cube resting on a stepped base of history
    top = cube_face(x, y, 60, 36, 26, 4)
    base_l = cube_face(x, y, 37.5, 75, 26, 4)
    base_r = cube_face(x, y, 82.5, 75, 26, 4)
    return top is not None or base_l in ("left", "top") or base_r in ("right", "top")


def d20(x, y, m):  # Cube T: an isometric T built from unit cubes
    if m.get("face") is None:
        return False
    hx, hy = m["c"]
    on_bar = abs(hy - 30) < 14 and abs(hx - 60) < 44
    on_stem = abs(hx - 60) < 6 and 30 <= hy <= 100
    return (on_bar or on_stem) and m["face"] in ("top", "left", "right")


def d21(x, y, m):  # Cut Gem: kite facets make a brilliant-cut stone, kites cradle it
    gem = hex_flat(x, y, 60, 42, 26)
    d = lower_band(x, y, 42, 26, 26 * SQ3 * 0.0001 + 22)
    cradle = hex_flat(x, y, 60, 58, 52) and not hex_flat(x, y, 60, 46, 36) and y >= 46 and abs(x - 60) >= 6
    return gem or cradle


def d22(x, y, m):  # Keystone Arch: kites as voussoirs, the keystone kept at the crown
    hx, hy = m["c"]
    r = math.hypot(x - 60, y - 84)
    arch = 30 <= r <= 52 and y <= 84
    key = abs(x - 60) < 9 and 22 <= y <= 44
    return (arch and not (abs(x - 60) < 12 and y < 50)) or key


def d23(x, y, m):  # Kite Wings
    a, b, cy = 12, 21, 38
    if diamond_d(x, y, cy, a, b) <= 0:
        return True
    d = lower_band(x, y, cy, a, b)
    if abs(x - 60) < 6:
        return False
    return (8 <= d <= 22 and cy - 8 <= y <= 100) or (30 <= d <= 44 and cy - 26 <= y <= 82)


def d24(x, y, m):  # Kite Bloom: a six-kite flower, the lower petals open into hands
    flower = hex_flat(x, y, 60, 40, 21)
    hands = hex_flat(x, y, 60, 62, 50) and not hex_flat(x, y, 60, 50, 34) and y >= 50 and abs(x - 60) >= 7
    return flower or hands


def d25(x, y, m):  # Kite T: kites form a T whose crossbar cradles the gem
    gem = diamond_d(x, y, 30, 12, 18) <= 0
    bar = 50 <= y <= 66 and abs(x - 60) <= 48 and not (abs(x - 60) < 8 and y < 58)
    stem = abs(x - 60) <= 9 and 66 <= y <= 104
    return gem or bar or stem


DESIGNS = [
    # Row 1 - equilateral triangles (60 degrees)
    (T60, keystone(44, 17, 17 * SQ3, 9, 13, 92, 10), "Keystone 60", "Concept 2 snapped to a 60° triangle grid."),
    (T60, d02, "Hex Vessel", "One hexagon carved into the kept gem and its cradle."),
    (T60, d03, "Wing Keep", "Three stepped feathers — Hermes wings holding the gem."),
    (T60, d04, "Shield Keep", "An inverted-triangle shield split by a Y channel."),
    (T60, d05, "Key Teeth", "A deep cup; its seam zigzags like the bit of a key."),
    # Row 2 - 45-degree triangles
    (T45, keystone(40, 22, 22, 9, 13, 98, 10, 48), "Keystone 45", "The original, rebuilt cell by cell on a 45° grid."),
    (T45, d07, "Octagon Seal", "An octagon seal carved into gem and cradle."),
    (T45, d08, "Version Stack", "Two chevrons under the gem: kept history."),
    (T45, d09, "Gem Keyhole", "One solid with a diamond pocket and slot — a keyhole holding a gem."),
    (T45, d10, "Gem T", "A gemstone profile; the cut between crown and pavilion is a T."),
    # Row 3 - hexagons
    (HEX, d11, "Hive Keystone", "Concept 2 built from honeycomb cells."),
    (HEX, d12, "Honey Cup", "A flower of cells kept in a hexagonal bowl."),
    (HEX, d13, "Hex Brackets", "Two hex halves guarding one cell."),
    (HEX, d14, "Hive Triad", "Three hexagons; the top one is kept."),
    (HEX, d15, "Comb Wings", "Two-tier honeycomb wings holding the gem."),
    # Row 4 - isometric cubes
    (CUBE, d16, "Kept Cube", "Concept 2 is a cube: the gem is its top face."),
    (CUBE, d17, "Lifted Lid", "The top face floats above an open box."),
    (CUBE, d18, "Lattice Cube", "Solid walls; the gem keeps the grid's facets."),
    (CUBE, d19, "Cube Stack", "A kept cube resting on a stepped base."),
    (CUBE, d20, "Cube T", "An isometric T made of unit cubes."),
    # Row 5 - kites
    (KITE, d21, "Cut Gem", "Kite facets cut a brilliant stone; kites cradle it."),
    (KITE, d22, "Keystone Arch", "Kites as voussoirs; the keystone is kept at the crown."),
    (KITE, d23, "Kite Wings", "Two-tier kite feathers around the gem."),
    (KITE, d24, "Kite Bloom", "A six-kite flower whose lower petals open into hands."),
    (KITE, d25, "Kite T", "A T whose crossbar cradles the gem."),
]


def build_mark(tiling, pred):
    chosen = []
    for keys, meta in tiling.cells:
        pts = [tiling.xy(k) for k in keys]
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        if -10 <= cx <= 130 and -10 <= cy <= 130 and pred(cx, cy, meta):
            chosen.append(keys)
    path = union_paths(chosen, tiling.xy)
    ys = [tiling.xy(k)[1] for keys in chosen for k in keys]
    xs = [tiling.xy(k)[0] for keys in chosen for k in keys]
    bbox = (min(xs), min(ys), max(xs), max(ys)) if xs else (0, 0, 0, 0)
    return path, bbox, len(chosen)


def grid_lines(tiling, box):
    bx0, by0, bx1, by1 = box
    seen, segs = set(), []
    for keys, _ in tiling.cells:
        for i in range(len(keys)):
            a, b = keys[i], keys[(i + 1) % len(keys)]
            e = (a, b) if a < b else (b, a)
            if e in seen:
                continue
            seen.add(e)
            (x1, y1), (x2, y2) = tiling.xy(a), tiling.xy(b)
            if max(x1, x2) < bx0 - 1 or min(x1, x2) > bx1 + 1 or max(y1, y2) < by0 - 1 or min(y1, y2) > by1 + 1:
                continue
            segs.append(f"M{x1:.1f},{y1:.1f}L{x2:.1f},{y2:.1f}")
    return "".join(segs)


ROWS = ["Triangles · 60°", "Triangles · 45°", "Hexagons", "Isometric cubes", "Kites"]


def main():
    import json
    marks_dir = OUT / "marks"
    marks_dir.mkdir(exist_ok=True)
    tiles = []
    for i, (tiling, pred, name, idea) in enumerate(DESIGNS, 1):
        path, (x0, y0, x1, y1), n = build_mark(tiling, pred)
        side = max(x1 - x0, y1 - y0) * 1.14
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        box = (cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)
        vb = f"{box[0]:.2f} {box[1]:.2f} {side:.2f} {side:.2f}"
        tiles.append({"n": f"{i:02d}", "name": name, "idea": idea, "row": ROWS[(i - 1) // 5],
                      "path": path, "vb": vb, "lines": grid_lines(tiling, box), "cells": n,
                      "asym": round(abs(cx - 60), 2)})
        (marks_dir / f"{i:02d}.svg").write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}"><path d="{path}" fill="#000"/></svg>')
    (OUT / "tiles.json").write_text(json.dumps(tiles))
    html = (OUT / "sheet.template.html").read_text().replace("/*TILES*/[]", json.dumps(tiles))
    (OUT / "teresis-25.html").write_text(html)
    for t in tiles:
        print(t["n"], t["name"].ljust(15), "cells", str(t["cells"]).rjust(4), "asym", t["asym"])


if __name__ == "__main__":
    main()
