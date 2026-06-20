# AirWatch card screenshot harness

Reusable, committed tooling that regenerates the card screenshots embedded in the
project README. Re-run it after any visible change to `airwatch-card.js` (or to the
band/consensus logic) so the docs never drift from the shipped card.

## One command

```bash
cd tools/screenshots
npm install            # first time only — pulls Playwright (chromium is cached)
npx playwright install chromium   # first time only
npm run screenshots    # python3 gen.py && node shoot.mjs
```

Output → `docs/images/{collapsed,expanded}-{light,dark,custom}.png` (the paths the
README embeds).

## How it works

- **`gen.py` — faithful data generator.** Builds `states.json` by calling the
  integration's *own* shipped functions (`level_for_value`, `band_provenance`,
  `consensus`, `level_label`). Nothing is hand-written, so if a band threshold or
  the consensus rule changes, re-running regenerates correct attributes. To add or
  retune a scenario, edit the `SCEN` table and let the real code derive the rest —
  never fabricate attribute values by hand.
- **`harness.html` — render host.** Stubs HA's `<ha-card>` wrapper and loads the
  real card bundle.
- **`shoot.mjs` — renderer.** Starts a tiny static server (serves `harness.html` and
  maps `/airwatch_card_static/*` to `custom_components/airwatch/frontend/*`, exactly
  as HA mounts it), then renders the card across collapsed/expanded × light/dark/custom
  themes and writes the PNGs. `node shoot.mjs collapsed-light` renders one shot.

## Honesty & privacy properties (keep these)

- **Faithful data only.** Attributes come from the real integration code via `gen.py`.
  The scenario tunes `pm2_5` to a genuine divergence (clean regional value vs. a local
  sensor spike) and keeps carbon monoxide honest — it has no EAQI band authority, so
  the card shows it as the non-EAQI odd-one-out rather than inventing a band.
- **No location.** The fixture is a synthetic, location-free home — no coordinates,
  station IDs, or place names. Keep it that way.
