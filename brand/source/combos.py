"""Hybrids of picks 1, 3, 5, 11, 19, 23, 24 on one 30-60-90 grid, with geometric rounded corners.

Polygons are validated on the grid (sharp), then rounded in the page with one fixed radius.
    python3 combos.py -> teresis-hybrids.html
"""

from __future__ import annotations

import json
from pathlib import Path

from fractions import Fraction as F

from build2 import KIS, fr, kis_lines, sym, validate

OUT = Path(__file__).resolve().parent

GEM = fr((0, 0), (2, 2), (0, 4), (-2, 2))

HYBRIDS = [
    ("Soft Keystone", "1 · 11 · 24",
     "The facet keystone with every corner softened — it turns into a geometric lotus.",
     [GEM] + sym(fr((-4, 2), (-1, 5), (-1, 9), (-6, 4), (-6, 2)))),
    ("Soft Stack", "19 · 1 · 24",
     "The gem on two layered chevrons: kept history, a database stack, a lotus.",
     [GEM] + sym(fr((-4, 2), (-1, 5), (-1, 7), (-6, 2)), fr((-6, 4), (-1, 9), (-1, 11), (-8, 4)))),
    ("Keystone Arch", "23 · 11 · 1",
     "A gateway on vertical piers with 30° haunches; the keystone wedge stands proud at the crown.",
     [fr((-4, -4), (4, -4), (1, -1), (-1, -1))]
     + sym([(F(-10), F(8)), (F(-6), F(8)), (F(-6), F(-2, 3)), (F(-7, 2), F(-3, 2)), (F(-5), F(-3)),
            (F(-10), F(-4, 3))])),
    ("Key Lotus", "5 · 11 · 24",
     "The lotus with a key-bit seam: the centre channel zigzags like a key.",
     [GEM,
      fr((-4, 2), (-1, 5), (-2, 6), (-1, 7), (-2, 8), (-1, 9), (-6, 4), (-6, 2)),
      fr((4, 2), (6, 2), (6, 4), (1, 9), (0, 8), (1, 7), (0, 6), (1, 5))]),
    ("Soft Wings", "3 · 1 · 24",
     "Three stepped feathers each side, rounded into Hermes' wing.",
     [fr((0, 0), (3, 3), (0, 6), (-3, 3))]
     + sym(fr((-2, 0), (-10, 0), (-11, 1), (-3, 1)), fr((-4, 2), (-10, 2), (-11, 3), (-5, 3)),
           fr((-4, 4), (-8, 4), (-7, 5), (-3, 5)))),
    ("Arch Stack", "23 · 19 · 3",
     "Two nested gateways under one keystone: an arch made of layers.",
     [fr((-4, -4), (4, -4), (2, -2), (-2, -2))]
     + sym([(F(-10), F(8)), (F(-6), F(8)), (F(-6), F(-2, 3)), (F(-7, 2), F(-3, 2)), (F(-5), F(-3)),
            (F(-10), F(-4, 3))],
           [(F(-4), F(8)), (F(-2), F(8)), (F(-2), F(2, 3)), (F(-1), F(1, 3)), (F(-1), F(-1)), (F(-4), F(0))])),
]


def main():
    lines = kis_lines()
    tiles = []
    for i, (name, src, idea, polys) in enumerate(HYBRIDS, 1):
        validate(KIS, polys, name)
        xy = [[list(KIS.to_xy(p)) for p in poly] for poly in polys]
        pts = [p for poly in xy for p in poly]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        side = max(max(xs) - min(xs), max(ys) - min(ys)) * 1.16
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        tiles.append({"n": f"H{i}", "name": name, "src": src, "idea": idea, "polys": xy,
                      "vb": [cx - side / 2, cy - side / 2, side, side], "lines": lines, "off": round(abs(cx - 60), 2)})
        print(f"H{i}", name.ljust(14), "sources", src, "offset", tiles[-1]["off"])
    html = (OUT / "hybrids.template.html").read_text().replace("/*TILES*/[]", json.dumps(tiles))
    (OUT / "teresis-hybrids.html").write_text(html)


if __name__ == "__main__":
    main()
