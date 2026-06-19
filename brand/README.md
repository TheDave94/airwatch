# AirWatch — Brand & Design System

**AirWatch** is a Home Assistant integration that aggregates outdoor
**air-quality** data from multiple sources into one cross-validated reading,
with multi-authority provenance (WHO 2021, EU 2024/2881, classic-vs-revised
EEA). This folder is its visual system — the app icon, palette, typography, the
severity scale, and the core components.

It is **adapted from the PollenWatch design system** ([sibling
project](https://github.com/TheDave94/pollenwatch)) — the family resemblance is
deliberate. The defining idea transfers unchanged: **higher is worse.** Colour
and motion use a green/cool→amber→red *warning* ramp, never a "filling up =
good / signal strength" feel.

## What transfers unchanged (the family resemblance)
Typography, the neutral palette, radii/spacing/surface rules, the card anatomy
(mark · title · meta → hero gauge → reading → breakdown rows), the
status-pill treatment, and the categorical **gauge mechanics**: the needle rests
at a **segment centre** (never an interpolated value), is **removed** for empty
readings, empty states are **gray, never green**, and motion is calm (a rising
level is a warning, not an achievement).

## What's swapped for the air-quality domain
1. **Severity ramp → the official EEA 6-band air-quality scale.** The 3-segment
   pollen dial becomes a 6-segment EEA dial. Colours are **science-anchored**
   (the EEA European Air Quality Index palette — the exact values the data layer
   emits in `bands.eaqi_eea_2024.colour`); the UI never invents severity
   colours. "Higher is worse" is preserved.
2. **Brand accent → air/atmosphere azure** (`--aw-sky`, the `--pw-gold` analog),
   chosen to sit calmly behind the loud EEA ramp.
3. **Icon & wordmark → an air motif.** The flower/pollen mark becomes a wind
   swirl + drifting particulate-matter dots over the same warning-gauge arc and
   slate needle. Two-tone wordmark: **Air** + **Watch**.
4. **Per-pollutant glyphs** (PM2.5/PM10/NO₂/O₃/SO₂/CO) replace the per-species
   grains, in the same color-neutral treatment.

## Fidelity
High-fidelity. Colours, typography, the icon geometry, and the severity ramp are
final. The slate needle / azure swirl are intentionally low-contrast on dark
surfaces — the bright EEA dial carries the mark (shift them to `--aw-sky-light`
for a high-contrast dark lockup, keeping the silhouette identical).

---

## Design tokens
The full `--aw-*` set lives in [`tokens.css`](tokens.css) (the in-repo source of
truth, adapted 1:1 from PollenWatch's `--pw-*`). Summary:

### Colour
```
/* Brand accent — air/atmosphere (replaces pollen gold) */
--aw-sky:        #2E7DD1;   /* primary brand / "air" */
--aw-sky-light:  #8FC7F0;   /* haze / dark-lockup accent */
--aw-sky-deep:   #1F5C9E;

/* Neutrals (unchanged from PollenWatch) */
--aw-ink:   #2A3540;  --aw-slate: #33414F;  --aw-muted: #7C8794;
--aw-paper: #FBF7F0;  --aw-cloud: #FFFFFF;  --aw-edge:  #ECE4D6;

/* Severity ramp — the official EEA 6-band scale (science-anchored) */
--aw-eaqi-1: #50f0e6;  /* Good           */
--aw-eaqi-2: #50ccaa;  /* Fair           */
--aw-eaqi-3: #f0e641;  /* Moderate       */
--aw-eaqi-4: #ff5050;  /* Poor           */
--aw-eaqi-5: #960032;  /* Very poor      */
--aw-eaqi-6: #7d2181;  /* Extremely poor */

/* CO / common-level ramp (CO isn't in the EAQI — WHO/EU basis) */
--aw-level-0: #3DAE5A;  --aw-level-1: #F2A516;  --aw-level-2: #E0492E;
```
**Rule:** any severity-bearing surface (gauge segment, pill, swatch, reading)
MUST use the EEA ramp and map a higher band → a worse colour. CO uses the
3-step level ramp (its severity is WHO/EU-driven, not an EAQI band). Don't
introduce a blue/teal "good progress" treatment — the azure accent is for brand
chrome, never for severity.

### Typography (transfers unchanged)
Both families are on Google Fonts (free, OFL):
```html
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700&family=Hanken+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
```
| Role | Family | Weight | Notes |
|---|---|---|---|
| Wordmark / display | Bricolage Grotesque | 700 | letter-spacing −0.02em |
| Headings | Bricolage Grotesque | 600 | letter-spacing −0.015em |
| Body / UI | Hanken Grotesk | 400 / 500 | line-height 1.5–1.6 |
| Numeric / status | Hanken Grotesk | 600 | `font-variant-numeric: tabular-nums` |

The card loads these best-effort and falls back to the HA/system sans if they
fail (offline / CSP).

### Radius, spacing, surfaces (unchanged)
```
--aw-r-pill: 999px;   /* pills, chips */
--aw-r-card: 16–18px; /* cards */
Cards: 1px solid var(--aw-edge) on var(--aw-cloud); no heavy shadows.
```

### Wordmark
Two-tone: **"Air"** in `--aw-ink`, **"Watch"** in `--aw-sky` (on dark: white +
`--aw-sky-light`). Set in Bricolage Grotesque 700, one typographic unit — don't
add a space or change weights between the two words.

---

## Assets
In [`assets/`](assets/):
| File | Size | Use |
|---|---|---|
| `icon.svg` | vector | App UI, header mark — **prefer this in-app** |
| `icon.png` | 256×256 | Home Assistant brand icon (`icon.png` spec) |
| `icon@2x.png` | 512×512 | Home Assistant `icon@2x.png` spec |
| `pollutants/*.svg` | viewBox 64 | the six per-pollutant glyphs (color-neutral) |

The PNGs are transparent and trimmed to the artwork bounding box per the
[Home Assistant brands](https://github.com/home-assistant/brands) requirements.
For submission to that repo, place them at
`custom_integrations/airwatch/icon.png` and `icon@2x.png`. In-app, the card
serves the SVGs from its bundled static path (`/airwatch_card_static/…`) — the
served copies live in `custom_components/airwatch/frontend/icons/`.

### The mark
viewBox `0 0 100 100`. Anatomy: a three-stop warning arc (EEA-anchored
teal→yellow→red), an air/wind swirl (the `--pw` bloom analog) at ~0.6 opacity,
five drifting particulate-matter dots (the pollen-grain analog), and a slate
needle whose pivot sits at the swirl's centre and points into the warm zone.
Keep clearspace ≥ the dial stroke weight on all sides; min size 16px; never
recolour the EEA dial, restretch, or rotate.

---

## Components

### 1. Severity gauge (the signature element)
A categorical **6-band EEA dial** (viewBox `0 0 120 92`, opening downward). The
data is the worst revised-EEA *sub-index* across the displayed pollutants (the
EAQI is, by definition, the worst sub-index). Honesty rules carried from
PollenWatch's `GAUGE_SPEC`:
- The needle rests at a **band centre**, never an interpolated value.
- The active segment thickens and the hub takes its EEA colour ("status hub").
- For the **unknown** state (source stale / all-invalid → the data layer's
  fail-safe, or no sub-index reading) the dial is a single **dashed gray track**
  with a hollow gray hub and **no needle** — gray, never a fake green.
- Calm motion only; respect `prefers-reduced-motion`.

### 2. Status pill
`display:inline-flex; gap:7px; padding:5px 12px 5px 10px; border-radius:999px;`
background = the band's EEA colour, text contrast-aware (the ramp spans very
light to very dark bands), with a small contrast-matched dot. The **unknown**
pill is a dashed outline in `--aw-muted` (no fill) — never green.

### 3. Card anatomy
Header row = mark (≈40px) + title (Bricolage 600, 18px) + meta (`N of M sources`
+ an `n/m` badge). Hero = the big gauge, then the reading: the band name
(Bricolage 700, ~30px) in its EEA colour + an uppercase `OVERALL · WORST
SUB-INDEX <pollutant>` caption. Body = one row per pollutant (glyph · name ·
reading · pill), each expandable to its provenance.

### 4. Per-pollutant glyphs
Six marks, one per pollutant, in `assets/pollutants/`. Gases are molecule
diagrams (CO diatomic; NO₂ wide bent triatomic; O₃ symmetric bent triatomic;
SO₂ deep-V triatomic) and PM are particle clouds (PM2.5 = many fine dots, PM10 =
few coarse particles). Same hand as PollenWatch's grains: viewBox `0 0 64 64`,
outline 2.2, flat / 2-tone, color-neutral via `--aw-grain-stroke` /
`--aw-grain-fill` so the card tints them per severity (inline them, don't
`<img>`). Legible at 32px; the card always shows the name + formula alongside,
so the glyph is supportive identity, not the sole tell.

---

## Behaviour
- **Needle**: animate to the new band centre on update —
  `transition: transform 320ms cubic-bezier(.32,.72,.30,1)` (calm; no bounce).
- **Level change**: cross-fade the reading colour ~200ms. No celebratory motion.
- **Loading / unavailable**: show the resting unknown dial, never a value.
- **Reduced motion**: snap instead of animate.
