# Teresis brand

## Logo files (`logo/`)

| File | Use |
| --- | --- |
| `teresis-lockup.svg` / `-white.svg` | Main horizontal lockup, for light / dark backgrounds |
| `teresis-lockup-stacked.svg` / `-white.svg` | Stacked lockup, for square spaces |
| `teresis-mark.svg` / `-white.svg` | Mark only (avatars, favicons, small sizes) |
| `teresis-app-icon.svg` | App icon: white mark on a black rounded square |

All files are pure vector. The wordmark is outlined, so no font needs to be installed to use them.

## The mark

A lotus fan: one tall centre petal, a middle pair tilted 30°, and an outer pair tilted 60°. It descends from
the "Keystone Facet" concept: the gem kept at the centre, held by the petals around it.

- Every corner lies on a 30-60-90 triangle grid (equilateral triangles cut by their medians). This is
  checked in code: the build fails if any edge leaves the grid.
- Every corner is rounded with one radius (4 grid units, about 40% of the channel between petals).
- 1-bit by design: it works in black, white and at 16 px.

## Wordmark

"Teresis" set in **Jost Medium (500)**, with the font's own kerning, outlined to vector.
Jost is licensed under the SIL Open Font License 1.1 (`fonts/OFL.txt`), so it is free for commercial use,
including logos. In the horizontal lockup the mark is 1.9 × cap height, with the cap height centred on the mark.

## Rebuild

```bash
cd brand/source
python3 final.py   # needs fontTools (pip install fonttools); rewrites logo/*.svg
```

`final.py` holds the mark geometry (via `lotus.py`), the rounding radius and the lockup proportions.
