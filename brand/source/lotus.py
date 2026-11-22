"""H1 pushed toward a lotus flower. Same 30-60-90 grid, validated sharp, rounded in the page."""
import json
from pathlib import Path

import combos
from build2 import KIS, fr, kis_lines, sym, validate

OUT = Path(__file__).resolve().parent

PETAL = fr((0, -2), (2, 0), (2, 2), (0, 4), (-2, 2), (-2, 0))          # tall centre petal
SIDE = fr((-6, 0), (-1, 5), (-1, 9), (-6, 4))                          # pointed side petal
OUTER = fr((-10, 2), (-2, 10), (-6, 10), (-10, 6))                     # lower, wider outer petal
H1 = combos.HYBRIDS[0]
FAN = ([fr((0, -4), (4, 0), (4, 4), (0, 8), (-4, 4), (-4, 0))]                  # tall centre petal
       + sym(fr((-6, 4), (-6, 0), (-12, -2), (-12, 2)),                          # middle pair, 30 deg tilt
             fr((-1, 9), (-9, 9), (-13, 5), (-5, 5))))                           # outer pair, 60 deg tilt

VARIANTS = [
    ("H1 Soft Keystone", "reference", "Your pick, unchanged.", H1[3]),
    ("Lotus · pointed", "H1 + 24",
     "The walls become pointed petals; the centre petal grows tallest.",
     [PETAL] + sym(SIDE)),
    ("Lotus · two rings", "H1 + 24 + 19",
     "A second, lower ring of petals on a flat base — five petals, layered.",
     [PETAL] + sym(SIDE, OUTER)),
    ("Lotus · fan", "H1 + 24",
     "Five petal-shaped petals at 30° steps: tall centre, middle pair lower, outer pair lowest and widest.",
     FAN),
    ("Lotus · fan on water", "H1 + 24 + 19",
     "The fan resting on a water line.",
     FAN + [fr((-11, 10), (11, 10), (11, 11), (-11, 11))]),
]


def main():
    lines = kis_lines()
    tiles = []
    for i, (name, src, idea, polys) in enumerate(VARIANTS):
        validate(KIS, polys, name)
        xy = [[list(KIS.to_xy(p)) for p in poly] for poly in polys]
        pts = [p for poly in xy for p in poly]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        side = max(max(xs) - min(xs), max(ys) - min(ys)) * 1.16
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        tiles.append({"n": "H1" if i == 0 else f"L{i}", "name": name, "src": src, "idea": idea, "polys": xy,
                      "vb": [cx - side / 2, cy - side / 2, side, side], "lines": lines})
        print(tiles[-1]["n"], name, "offset", round(abs(cx - 60), 2))
    html = (OUT / "hybrids.template.html").read_text().replace("/*TILES*/[]", json.dumps(tiles))
    html = html.replace("Hybrids of 1 · 3 · 5 · 11 · 19 · 23 · 24 — one 30-60-90 grid, one corner radius",
                        "H1 → lotus · same grid, same corner radius")
    (OUT / "teresis-lotus.html").write_text(html)


if __name__ == "__main__":
    main()
