---
name: Teresis
description: Local long-term memory for AI agents, drawn as a lotus built on a 30-60-90 construction grid.
colors:
  ochre: "#d9af5b"
  ochre-bright: "#e6c174"
  ochre-deep: "#a67a2a"
  field: "#123a2a"
  deep: "#0c2b1f"
  cream: "#f1e9d6"
  sage: "#b8cbb4"
  pale-sage: "#a3b8a0"
  mute: "#7d9a84"
  line: "rgba(217, 175, 91, 0.22)"
  error-text: "#f0b8a6"
  error-stroke: "#e8907a"
typography:
  display:
    fontFamily: "Cormorant, 'Iowan Old Style', Georgia, serif"
    fontSize: "clamp(54px, 6.9vw, 96px)"
    fontWeight: 400
    lineHeight: 0.95
    letterSpacing: "-0.02em"
    fontFeature: "lnum"
  headline:
    fontFamily: "Cormorant, 'Iowan Old Style', Georgia, serif"
    fontSize: "clamp(40px, 5vw, 72px)"
    fontWeight: 400
    lineHeight: 1
    letterSpacing: "-0.015em"
    fontFeature: "lnum"
  title:
    fontFamily: "Cormorant, 'Iowan Old Style', Georgia, serif"
    fontSize: "clamp(30px, 3vw, 46px)"
    fontWeight: 400
    lineHeight: 1.05
    letterSpacing: "-0.01em"
    fontFeature: "lnum"
  body:
    fontFamily: "Allo, system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "17px"
    fontWeight: 400
    lineHeight: 1.55
  body-large:
    fontFamily: "Allo, system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "clamp(17px, 1.3vw, 19px)"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Allo, system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.55
  wordmark:
    fontFamily: "Allo, system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "22px"
    fontWeight: 300
    letterSpacing: "-0.04em"
  code:
    fontFamily: "'Fragment Mono', ui-monospace, 'SF Mono', Menlo, monospace"
    fontSize: "13.5px"
    fontWeight: 400
    lineHeight: 1.6
rounded:
  pill: "999px"
  panel: "12px"
  focus: "6px"
  bar-end: "4px"
spacing:
  gutter: "clamp(20px, 4.5vw, 64px)"
  section: "clamp(80px, 10vw, 140px)"
  stack: "18px"
  wrap: "1080px"
  story: "1280px"
components:
  button-primary:
    backgroundColor: "{colors.ochre}"
    textColor: "{colors.deep}"
    typography: "{typography.body}"
    rounded: "{rounded.pill}"
    padding: "0 22px"
    height: "48px"
  button-primary-hover:
    backgroundColor: "{colors.ochre-bright}"
  button-primary-compact:
    backgroundColor: "{colors.ochre}"
    textColor: "{colors.deep}"
    rounded: "{rounded.pill}"
    padding: "0 18px"
    height: "42px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.cream}"
    rounded: "{rounded.pill}"
    padding: "0 14px"
    height: "34px"
  button-ghost-hover:
    textColor: "{colors.ochre}"
  input-email:
    backgroundColor: "rgba(12, 43, 31, 0.55)"
    textColor: "{colors.cream}"
    rounded: "{rounded.pill}"
    padding: "0 18px"
    height: "48px"
  tab-active:
    backgroundColor: "rgba(217, 175, 91, 0.08)"
    textColor: "{colors.cream}"
    rounded: "{rounded.pill}"
    padding: "4px 10px"
  code-panel:
    backgroundColor: "rgba(12, 43, 31, 0.6)"
    textColor: "{colors.cream}"
    typography: "{typography.code}"
    rounded: "{rounded.panel}"
    padding: "20px"
---

# Design System: Teresis

## Overview

**Creative North Star: "The Construction Drawing of Keeping"**

Every Teresis surface is a construction drawing. A 30-60-90 grid (kisrhombille) is etched across the whole page in faint ochre hairlines. The lotus mark is built on that grid, one petal per idea, and it is the only solid shape in the drawing. The grid runs under every section, so the page reads as a single plate rather than a stack of cards. The content belongs to the drawing: a fact kept, a value replaced, a scope fenced off.

The ground is dark lotus-leaf green with a cool, still, botanical feel. Manuscript Ochre is the gold leaf on that plate. It marks the petals, the grid lines, key figures and the one action. Headlines are engraved Cormorant Garamond, the interface is Allo, a soft rounded sans, and Fragment Mono appears only where the reader is looking at code. Density is low and paced for scrolling. Long sections give each idea room, and the motion is slow assembly, never decoration.

The world rejects two things outright. One is the dark dev-tool hero: a terminal window, neon glow, a gradient mesh. The other is the cream editorial page. Teresis is dark and green, but it is botanical rather than technical.

**Key Characteristics:**
- A full-bleed kisrhombille grid on every section, aligned to the lotus lattice.
- One code-drawn lotus that assembles petal by petal: the grid draws first, then the solid lands.
- One ochre-filled action per view; every other control is a hairline.
- Engraved serif display with lining figures; a soft sans for UI; mono only for code.
- Flat tonal layers (field and deep) separated by ochre hairlines; no surface shadows.

## Colors

The palette is a deep green plate with a single warm metal and a ladder of sage greens for text.

### Primary
- **Manuscript Ochre** (`ochre`): petals, the etched grid, key figures, "Teresis keeps." in the headline, highlighted benchmark bars, focus rings and the one filled action. Text on ochre is Pond Deep.
- **Burnished Ochre** (`ochre-bright`): the hover state of filled ochre controls only.
- **Tarnished Ochre** (`ochre-deep`): the scrollbar thumb. It is a quiet metal for chrome, not for content.

### Neutral
- **Lotus-Leaf Field** (`field`): the page ground, the hero and the footer.
- **Pond Deep** (`deep`): the recessed tone for the proof section, the hero slip, the sticky bar, code and demo panels (at 55–92% alpha over the field), and text on ochre.
- **Vellum Cream** (`cream`): primary text, headings and values.
- **Sage** (`sage`): secondary text such as ledes, captions, nav links, step bodies and the footer.
- **Pale Sage** (`pale-sage`): input placeholders and the smallest notes, where Sage is too dim at 12–13px.
- **Lichen** (`mute`): non-highlighted data, such as comparison bars, superseded and struck-out values, and sibling scopes that are never read.
- **Etched Rule** (`line`): every hairline, including section borders, table rules, panel strokes and ghost-control outlines.

### Error
- **Rose Clay** (`error-text`, `error-stroke`): the form error message and the stroke of an invalid email field. This is the only off-palette hue, used only when something went wrong.

### Named Rules
**The One Ochre Action Rule.** Ochre fills exactly one kind of control: the waitlist action, as the nav pill, the form button and the sticky-bar button. Copy, tabs and every secondary control are transparent with an Etched Rule outline. A second filled ochre button in the same view is a defect.

**The Gold-Leaf Rule.** Ochre carries meaning: something kept, the answer, the thing to do. Highlight a benchmark bar in ochre only when it is Teresis; competitors stay Lichen.

## Typography

**Display Font:** Cormorant Garamond (served as `Cormorant`, with Iowan Old Style and Georgia as fallbacks)
**Body Font:** Allo (with system-ui as fallback)
**Label/Mono Font:** Fragment Mono, for code and machine output only

**Character:** an engraved, high-contrast book serif set large and quiet, over a soft, round-terminal sans that keeps the interface friendly. The serif carries the voice, and the sans carries the work.

Allo is self-hosted and instanced at optical size 14 with full roundness (ROND 100), with weight left variable. Cormorant is re-cut with lining (`lnum`) and tabular (`tnum`) figures. All three faces are OFL fonts, self-hosted and subset to woff2.

### Hierarchy
- **Display** (400, clamp 54–96px, line height 0.95, −0.02em): the hero headline only, on two lines, with the second sentence in ochre.
- **Headline** (400, clamp 40–72px, line height 1, −0.015em, max 18ch): section heads.
- **Title** (400, clamp 30–46px, line height 1.05, −0.01em): story steps and sub-heads.
- **Body** (Allo 400, 17px, line height 1.55): running text, with step bodies capped at 46ch.
- **Body Large** (Allo 400, clamp 17–19px): section ledes in Sage, max 62ch.
- **Label** (Allo 400, 13–15px): captions, tabs, nav links, table heads and the proof line; sentence case, never tracked uppercase.
- **Wordmark** (Allo 300, 22px, −0.04em): "Teresis" beside the mark. This is a stand-in until the custom grid wordmark is drawn.
- **Code** (Fragment Mono 400, 13.5–14.5px, line height 1.6): install commands and demo output.
- **Step Numeral** (Cormorant 400, 64px, or 44px on mobile, in ochre): the 1–5 assembly numbers in the story.

### Named Rules
**The Lining Figures Rule.** Every numeral set in Cormorant uses lining figures (`font-variant-numeric: lining-nums`), and every data column uses tabular figures. Old-style figures make "100 out of 100" read as text.

**The Mono Is Code Rule.** Fragment Mono appears only inside code panels and machine-output rows. Labels, captions and buttons are always Allo.

## Layout

The page is a full-bleed construction plate. The hero fills at least the viewport (minimum 760px) as a two-column grid: copy on the left, the lotus on the right (up to 620px). Under them, a full-width ruled slip in Pond Deep holds the email form, the install preview and the proof line. After the hero, the grid tile repeats under every section, about 38 × 67px per kisrhombille cell.

- **Gutter:** `gutter` on both sides of every band.
- **Section rhythm:** `section` padding top and bottom. Text sections center in a 1080px wrap; the story uses 1280px.
- **Story:** two columns with a sticky lotus plate (80vh tall) on the left and steps on the right. Each step is about 78vh, so one idea crosses the middle of the screen at a time. A final empty step returns the lotus to complete.
- **Breakpoints:** at 1080px the slip and benchmark pair go to two and one columns. At 860px the hero stacks (copy, lotus, slip), nav links hide, and the story plate becomes a slim sticky header: a 96px lotus beside its caption. At 420px the waitlist form stacks.

The build caps the display at 96px on two lines. The direction contract had sketched about 128px on three lines; the build wins.

## Elevation & Depth

The system is flat. Depth comes from two tonal layers, Lotus-Leaf Field and Pond Deep (often translucent over the grid), separated by Etched Rule hairlines. Panels never cast shadows.

### Shadow Vocabulary
- **Floating bar** (`box-shadow: 0 18px 40px -16px rgba(0, 0, 0, 0.6)`): only the sticky waitlist bar, because it actually floats over content.
- **Focus halo** (`box-shadow: 0 0 0 3px rgba(217, 175, 91, 0.25)`): the email field on focus.

### Named Rules
**The Flat Plate Rule.** Surfaces sit on the plate; they don't hover over it. The only object allowed a shadow is the one that moves over content.

## Shapes

The form language comes from the 30-60-90 lattice. The lotus mark has five petals: a center, a mid pair and an outer pair. Its vertices sit on the kisrhombille lattice (x = 60 + 6X, y = 10.392Y in mark units), and every corner is filleted at radius 4. The etched grid uses the same lattice, aligned by pattern offset so the hero grid and the lotus line up exactly.

Interface shapes have two radii. Controls are pills (`pill`), and panels (code and demo) use `panel`. Benchmark bars are square at the axis with a small rounded end (`bar-end`). Focus outlines use `focus` with a 3px offset.

### Named Rules
**The Pill and Panel Rule.** Controls are pills and containers are 12px panels. There is no third radius for interface shapes.

## Components

### Buttons
Soft and decisive: one filled metal action, everything else is a drawn outline.
- **Shape:** full pill (999px).
- **Primary:** Manuscript Ochre fill, Pond Deep text, Allo 500 at 16px, 48px tall with 22px side padding. The compact variant, used in the bar and the hero slip, is 42px tall with 18px padding.
- **Hover / Focus:** the fill steps to Burnished Ochre over 0.2s; focus shows a 2px ochre outline at a 3px offset. While a request is sending, the button drops to 60% opacity with a progress cursor.
- **Ghost (Copy):** transparent with an Etched Rule outline and cream text, 34px tall. On hover, the border and text turn ochre.
- **Nav pill:** the primary treatment at nav scale (15px, 10px × 18px padding).

### Inputs / Fields
- **Style:** a pill, 48px tall, with a translucent Pond Deep fill and an ochre stroke at 45% alpha. Cream text, Pale Sage placeholder.
- **Focus:** the stroke goes fully ochre and gains the 3px focus halo.
- **Error:** an invalid entry gets a Rose Clay stroke, and a Rose Clay message sits under the field, indented 18px to align with the text.

### Tabs (Install switcher)
- **Style:** text pills in Sage. The active tab gets cream text, an Etched Rule outline and an 8% ochre wash.

### Code Panel
- **Style:** a 12px panel in translucent Pond Deep with an Etched Rule stroke and Fragment Mono in cream. Each command line is its own block with a 2ch hanging indent, so wrapped lines stay under their command on narrow screens. On desktop the Copy ghost sits top right; at 860px and below it sits under the panel.

### Navigation
- **Style:** the mark plus the Allo-300 wordmark on the left; three Sage links (15px) pushed right; the ochre waitlist pill last. Links turn cream and underline on hover. At 860px and below, the links hide, leaving the mark and the pill.

### Lotus Plate (signature)
The lotus is drawn in code from generated paths on the 30-60-90 grid. Each petal has four states: off, new (full ochre), ghost (36% opacity) and on. In the hero, the grid draws on with a circular reveal from the lotus center (1.6s). The petals then assemble center, mid pair, outer pair; earlier petals ghost and then return to full. In the story, the pinned plate tracks the scroll: each step brings in its petal bright and ghosts the earlier ones, and a final sentinel returns all five to full under the caption "The lotus, complete". Under reduced motion, the grid and petals appear complete and still.

### Story Step
- **Style:** an ochre Cormorant numeral in a 64px column, then a title, a Sage body (46ch) and a demo panel. Inactive steps rest at 42% opacity and come to full as they cross the middle of the screen.
- **Demo rows:** machine facts render as Fragment Mono rows, label left in Sage and value right in ochre with tabular figures. They are never a big-number stat trio.

### Benchmark Bars
- **Style:** direct-labelled rows: label, a 10px track, the value, then the query time. Teresis rows fill ochre with a 500-weight label; competitors fill Lichen. Each chart has a caption above it in Sage. At 860px and below, the label moves above the bar.

### Sticky Bar
- **Style:** a floating Pond Deep pill (94% alpha) with an Etched Rule stroke and the floating-bar shadow. It holds the mark, one line of Sage text and the compact waitlist form. It slides up from below once the hero slip leaves the viewport and hides again at the closing section. When hidden it is inert and aria-hidden.

## Do's and Don'ts

### Do:
- **Do** run the etched kisrhombille grid under every section in Manuscript Ochre at low stroke opacity, aligned to the lotus lattice. Stroke opacity is 9% under sections, 20% in the hero and 40% inside the lotus plate.
- **Do** keep exactly one filled ochre action per view, and draw every other control as a hairline pill.
- **Do** set every Cormorant numeral with lining figures and every data column with tabular figures.
- **Do** build new marks, icons and illustrations on the 30-60-90 lattice, with corners filleted at radius 4 in mark units.
- **Do** separate depth with Lotus-Leaf Field and Pond Deep plus Etched Rule hairlines, not shadows.
- **Do** let motion assemble (grid first, then solid) with `cubic-bezier(0.16, 1, 0.3, 1)`, and show the finished state under reduced motion.
- **Do** keep the enchantment sweep on two elements only: the ochre hero line ("Teresis keeps.") and the ochre action (nav pill and waitlist buttons). It is a slow purple band over the existing ochre, CSS gradients clipped to the glyphs or painted in the button background. `prefers-reduced-motion` removes the sweep and leaves a static lavender tint. It is not a third brand color.

### Don't:
- **Don't** use a dark dev-tool hero (terminal window, neon glow, gradient mesh), and don't use the cream editorial page. The enchantment sweep above is the only glow, and it stays inside the hero line and the ochre action.
- **Don't** use Fragment Mono for labels, captions, buttons or headings.
- **Don't** present facts as a big-number stat trio; use direct-labelled bars or mono rows.
- **Don't** add a second filled ochre button, a third interface radius or a shadow on a panel.
- **Don't** fill a competitor's bar in ochre.
