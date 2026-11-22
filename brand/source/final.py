"""Teresis final mark (L3 lotus fan, radius 4) + outlined wordmark lockups + SVG exports.

    python3 final.py -> teresis-final.html and export/*.svg
Fonts: OFL (Jost, Outfit, Nunito) from google/fonts, outlined with fontTools; kerning read from GPOS.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

from build2 import KIS, validate
from lotus import FAN

OUT = Path(__file__).resolve().parent
FONTS = OUT.parent / "fonts"
EXPORT = OUT.parent / "logo"
RADIUS = 4.0


# ----------------------------------------------------------------------------- mark
def rounded(poly, r):
    """Fillet every corner with radius r (clamped so short edges keep 10% straight)."""
    n, segs = len(poly), []
    for i in range(n):
        P, A, B = poly[i], poly[i - 1], poly[(i + 1) % n]
        ax, ay, bx, by = A[0] - P[0], A[1] - P[1], B[0] - P[0], B[1] - P[1]
        la, lb = math.hypot(ax, ay), math.hypot(bx, by)
        th = math.acos(max(-1.0, min(1.0, (ax * bx + ay * by) / (la * lb))))
        if th > math.pi - 1e-3:
            segs.append((P, P, 0, 0))
            continue
        t = min(r / math.tan(th / 2), min(la, lb) * 0.45)
        reff = t * math.tan(th / 2)
        p1 = (P[0] + ax / la * t, P[1] + ay / la * t)
        p2 = (P[0] + bx / lb * t, P[1] + by / lb * t)
        turn = (P[0] - A[0]) * (B[1] - P[1]) - (P[1] - A[1]) * (B[0] - P[0])
        segs.append((p1, p2, reff, 1 if turn > 0 else 0))
    f = lambda p: f"{p[0]:.2f},{p[1]:.2f}"
    d = "M" + f(segs[0][0])
    for i, (p1, p2, reff, sweep) in enumerate(segs):
        if i:
            d += "L" + f(p1)
        if reff:
            d += f"A{reff:.2f},{reff:.2f} 0 0 {sweep} {f(p2)}"
    return d + "Z"


validate(KIS, FAN, "L3 fan")
MARK_POLYS = [[KIS.to_xy(p) for p in poly] for poly in FAN]
_xs = [p[0] for poly in MARK_POLYS for p in poly]
_ys = [p[1] for poly in MARK_POLYS for p in poly]
MX0, MY0, MX1, MY1 = min(_xs), min(_ys), max(_xs), max(_ys)
# normalise the mark so its box starts at 0,0
MARK_POLYS = [[(x - MX0, y - MY0) for x, y in poly] for poly in MARK_POLYS]
MW, MH = MX1 - MX0, MY1 - MY0
MARK_D = "".join(rounded(p, RADIUS) for p in MARK_POLYS)
GRID_D = KIS.lines_svg()  # in original grid space; drawn with a translate(-MX0, -MY0)


# ----------------------------------------------------------------------------- wordmark
def kern_table(font):
    """(left glyph, right glyph) -> x-advance adjustment, from GPOS PairPos lookups in 'kern'."""
    if "GPOS" not in font:
        return lambda a, b: 0
    gpos = font["GPOS"].table
    idx = set()
    for fr in gpos.FeatureList.FeatureRecord:
        if fr.FeatureTag == "kern":
            idx.update(fr.Feature.LookupListIndex)
    subs = []
    for i in sorted(idx):
        lk = gpos.LookupList.Lookup[i]
        for st in lk.SubTable:
            if lk.LookupType == 9:
                st = st.ExtSubTable
            if getattr(st, "LookupType", 2) == 2 or st.__class__.__name__ == "PairPos":
                subs.append(st)

    def kern(a, b):
        for st in subs:
            cov = st.Coverage.glyphs
            if a not in cov:
                continue
            if st.Format == 1:
                ps = st.PairSet[cov.index(a)]
                for rec in ps.PairValueRecord:
                    if rec.SecondGlyph == b:
                        return getattr(rec.Value1, "XAdvance", 0) or 0
            elif st.Format == 2:
                c1 = st.ClassDef1.classDefs.get(a, 0)
                c2 = st.ClassDef2.classDefs.get(b, 0)
                v = st.Class1Record[c1].Class2Record[c2].Value1
                adv = getattr(v, "XAdvance", 0) or 0
                if adv:
                    return adv
        return 0
    return kern


def outline(path, wght, text, tracking=0.0):
    """Outline `text` at `wght`; returns (svg path, width, cap height) in font units (y down)."""
    font = instancer.instantiateVariableFont(TTFont(path), {"wght": wght})
    cmap, gs, hmtx = font.getBestCmap(), font.getGlyphSet(), font["hmtx"]
    upm = font["head"].unitsPerEm
    cap = getattr(font["OS/2"], "sCapHeight", 0) or 0.7 * upm
    kern = kern_table(font)
    names = [cmap[ord(c)] for c in text]
    x, parts = 0.0, []
    for i, g in enumerate(names):
        pen = SVGPathPen(gs)
        gs[g].draw(TransformPen(pen, (1, 0, 0, -1, x, 0)))
        parts.append(pen.getCommands())
        x += hmtx[g][0] + tracking * upm
        if i + 1 < len(names):
            x += kern(g, names[i + 1])
    width = x - tracking * upm
    return " ".join(parts), width, cap, upm


WORDMARKS = [
    ("Jost", FONTS / "Jost.ttf", 500, 0.0, "Chosen. Geometric, Futura lineage, open licence (OFL)."),
]


def lockups(path_d, width, cap):
    """Return dicts for horizontal and stacked lockups (all in one coordinate space)."""
    # horizontal: mark height = 1.9 x cap height; cap centred on the mark's centre
    s_mark = 1.9 * cap / MH
    mw, mh = MW * s_mark, MH * s_mark
    gap = 0.42 * mw
    text_y = mh / 2 + cap / 2  # baseline
    h = {"w": mw + gap + width, "h": mh,
         "mark": f'<path transform="scale({s_mark:.5f})" d="{MARK_D}"/>',
         "word": f'<path transform="translate({mw + gap:.2f} {text_y:.2f})" d="{path_d}"/>'}
    # stacked: mark height = 3.1 x cap, centred above the word
    s2 = 3.1 * cap / MH
    mw2, mh2 = MW * s2, MH * s2
    W = max(mw2, width)
    v = {"w": W, "h": mh2 + 0.55 * cap + cap,
         "mark": f'<path transform="translate({(W - mw2) / 2:.2f} 0) scale({s2:.5f})" d="{MARK_D}"/>',
         "word": f'<path transform="translate({(W - width) / 2:.2f} {mh2 + 0.55 * cap + cap:.2f})" d="{path_d}"/>'}
    return h, v


def svg(lock, fill, bg=None, pad=0.08):
    p = pad * max(lock["w"], lock["h"])
    vb = f"{-p:.2f} {-p:.2f} {lock['w'] + 2 * p:.2f} {lock['h'] + 2 * p:.2f}"
    rect = f'<rect x="{-p:.2f}" y="{-p:.2f}" width="{lock["w"] + 2 * p:.2f}" height="{lock["h"] + 2 * p:.2f}" fill="{bg}"/>' if bg else ""
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}">{rect}<g fill="{fill}">{lock["mark"]}{lock["word"]}</g></svg>'


def main():
    EXPORT.mkdir(exist_ok=True)
    for old in EXPORT.glob("*.svg"):  # rebuild the set from scratch
        old.unlink()
    mark_svg = lambda fill, bg=None: svg({"w": MW, "h": MH, "mark": f'<path d="{MARK_D}"/>', "word": ""}, fill, bg)
    (EXPORT / "teresis-mark.svg").write_text(mark_svg("#000"))
    (EXPORT / "teresis-mark-white.svg").write_text(mark_svg("#fff"))
    # app icon: mark at 62% of a rounded square
    side = max(MW, MH) / 0.62
    icon = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {side:.2f} {side:.2f}">'
            f'<rect width="{side:.2f}" height="{side:.2f}" rx="{side * 0.225:.2f}" fill="#000"/>'
            f'<path transform="translate({(side - MW) / 2:.2f} {(side - MH) / 2 + MH * 0.02:.2f})" d="{MARK_D}" fill="#fff"/></svg>')
    (EXPORT / "teresis-app-icon.svg").write_text(icon)

    words = []
    for name, path, wght, track, why in WORDMARKS:
        d, width, cap, upm = outline(path, wght, "Teresis", track)
        h, v = lockups(d, width, cap)
        (EXPORT / "teresis-lockup.svg").write_text(svg(h, "#000"))
        (EXPORT / "teresis-lockup-white.svg").write_text(svg(h, "#fff"))
        (EXPORT / "teresis-lockup-stacked.svg").write_text(svg(v, "#000"))
        (EXPORT / "teresis-lockup-stacked-white.svg").write_text(svg(v, "#fff"))
        words.append({"name": name, "wght": wght, "why": why, "h": h, "v": v})
        print(f"{name:7} wght {wght}  word width {width:.0f}u  cap {cap}u  upm {upm}")

    data = {"mark": MARK_D, "mw": MW, "mh": MH, "grid": GRID_D, "gx": -MX0, "gy": -MY0, "icon": icon,
            "words": words}
    html = (OUT / "final.template.html").read_text().replace("/*DATA*/{}", json.dumps(data))
    (OUT / "teresis-final.html").write_text(html)
    print("exports:", ", ".join(sorted(p.name for p in EXPORT.iterdir())))


if __name__ == "__main__":
    main()
