# AirWatch Lovelace card — HA-convention research & assessment

*Read-only research pass (2026-06-19). Grounds the card in real Home Assistant
card best-practices before changes. The "theme-native" set (P1–P4) was applied
in a follow-up pass; P5–P6 deferred.*

## Method
Cross-referenced the current `airwatch-card.js` against: the official HA
custom-card dev docs; the HA frontend theme-variable set; the Mushroom theming
architecture; the Bubble Card "HA default styling" retrofit; and adjacent
air-quality HACS cards (KadenThomp36, UrbanTechIO, et al.). Sources at the end.

## Core question: does the card respect the user's theme?
**Mostly yes for colour/surface neutrals, but it overrode typography and partly
overrode the card surface.** The `--aw-*` tokens fall back to HA theme variables
exactly the way Mushroom's `--mush-*` tokens do (`--aw-ink → --primary-text-color`,
`--aw-cloud → --ha-card-background/--card-background-color`,
`--aw-edge → --divider-color`, `--aw-r-card → --ha-card-border-radius`,
`box-shadow → --ha-card-box-shadow`) — the idiomatic, best-in-class pattern. The
two divergences from native were **typography** (forced Bricolage/Hanken applied
globally via an injected Google-Fonts `<link>`) and the **ha-card surface border**
(hard-set). The EEA severity colours are *intentionally* not themed — correct.

---

## (a) Conventions FOLLOWED vs VIOLATED

**Followed (keep):**
- Renders inside `<ha-card>`; `setConfig` throws on invalid; `hass` setter
  re-renders on update.
- `getConfigElement` (ha-form) + `getStubConfig` + `window.customCards`
  registration with `name`/`description`/`documentationURL`.
- Theme-aware neutrals via prefixed-token → HA-var fallbacks (the Mushroom pattern).
- Shadow-DOM encapsulation; `prefers-reduced-motion`; rows are real `<button>`s
  with `aria-expanded`/`aria-label`.
- Progressive disclosure (compact → tap-to-expand) — matches the KadenThomp36
  air-quality card.
- Severity ramp hard-coded (not themed) — consistent with HA's built-in Gauge
  card severity convention and with adjacent AQI cards (KadenThomp36, UrbanTechIO
  both use fixed pollution-level palettes).

**Violated / gaps:**
- **Typography override (main one).** Injected Google Fonts + applied
  Bricolage/Hanken to *all* text. Native/best-in-class cards inherit the theme
  font family and vary only size/weight (Mushroom). This is exactly what made
  Bubble Card look foreign until they shipped a module to "defer to whatever
  theme the user has selected." Plus an external network request.
- **Re-declaring the ha-card surface.** Set a hard `1px solid var(--divider-color)`
  border (+ background + radius) on `<ha-card>`, overriding themes that intend
  shadow-only cards and fighting the theme's `--ha-card-border-radius`.
- **No `getGridOptions`.** Only `getCardSize` (legacy masonry). The Sections view
  (default since 2024) sizes via a 12-column grid through `getGridOptions`.
- **Gauge SVG a11y.** The dial had no `role="img"`/`aria-label` summarising the
  reading.

---

## (b) Best-practices to adopt
1. Inherit the theme font for body/UI; scope the brand display font tightly (or drop it).
2. Let `ha-card` own the surface — set only internal padding; respect
   `--ha-card-border-width`/`-color`/`-backdrop-filter`.
3. Implement `getGridOptions` (keep `getCardSize` as masonry fallback).
4. Keep the token → HA-fallback discipline; keep severity colours fixed.
5. Add `aria-label`/`role="img"` to the gauge.

## (c) What the exemplars do that we don't
- **Mushroom** — varies only font size/weight over the theme font; no webfont;
  RGB-triplet colours for clean opacity.
- **Bubble Card** — learned to *defer* to HA surface/typography variables to
  avoid "jarring aesthetic discontinuity" (cautionary parallel to our overrides).
- **KadenThomp36 air-quality card** — same WHO-threshold + expand-to-detail model
  (validation); adds a compact mode (title + status badge) — the idea behind P5.
- **HA built-in Gauge / sensor cards** — the native baseline: fixed severity
  colours, theme-driven chrome.

## (d) Prioritised changes (impact on "feels native + looks good")
| # | Change | Impact | Effort |
|---|---|---|---|
| **P1** | Typography: inherit theme font; Bricolage only for title + hero word, behind a `brand_font` flag (default off); remove default webfont request | **High** | Low |
| **P2** | ha-card surface: drop the hard border/background/radius re-declaration; let `ha-card` render its themed surface; add only padding | **Med-High** | Low |
| **P3** | Add `getGridOptions` (default columns + `min_columns`/`min_rows`); keep `getCardSize` | **Med-High** | Low |
| **P4** | Gauge a11y: `role="img"` + `aria-label`; verify pill contrast | **Med** | Low |
| **P5** | Optional compact layout (title + status badge) for small grid placements | **Med** | Med |
| **P6** | RGB-triplet tints; drop redundant fallbacks | **Low** | Low |

Guiding principle (Mushroom/Bubble precedent): **theme for the chrome, identity
for the content.** AirWatch's identity is the EEA gauge, the severity ramp, the
pollutant glyphs, and the air accent — those stay fixed; the typeface and card
surface become theme-native.

---

### Sources
- [Custom card — HA Developer Docs](https://developers.home-assistant.io/docs/frontend/custom-ui/custom-card/)
- [A Home-Approved Dashboard, chapter 1: Sections view & grid system](https://www.home-assistant.io/blog/2024/03/04/dashboard-chapter-1/)
- [Frontend integration — theme variables](https://www.home-assistant.io/integrations/frontend/) · [color.globals.ts](https://github.com/home-assistant/frontend/blob/master/src/resources/theme/color/color.globals.ts)
- [Mushroom theming & styling (DeepWiki)](https://deepwiki.com/piitaya/lovelace-mushroom/5-theming-and-styling) · [Mushroom repo](https://github.com/piitaya/lovelace-mushroom)
- [Bubble Card — "HA default styling" discussion #1230](https://github.com/Clooos/Bubble-Card/discussions/1230) · [Bubble Card repo](https://github.com/Clooos/Bubble-Card)
- Adjacent AQI cards: [KadenThomp36/air-quality-card](https://github.com/KadenThomp36/air-quality-card) · [UrbanTechIO/air-quality-card](https://github.com/UrbanTechIO/air-quality-card) · [brunosabot/lovelace-nonow-aqi](https://github.com/brunosabot/lovelace-nonow-aqi) · [bairnhard/lovelace-aqi-dashboard](https://github.com/bairnhard/lovelace-aqi-dashboard)
