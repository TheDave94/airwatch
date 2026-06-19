/**
 * airwatch-card.js — Lovelace custom card for AirWatch.
 *
 * Visual identity ADAPTED from the PollenWatch design system (the family
 * resemblance is deliberate): the card anatomy (mark · title · meta → hero
 * gauge → reading → breakdown rows), the status-pill treatment, and the
 * categorical severity GAUGE mechanics — needle resting at a segment centre
 * (never an interpolated value), "higher is worse", calm motion, and
 * gray-never-green for empty readings. See brand/README.md + brand/tokens.css.
 *
 * THEME-NATIVE chrome ("theme for the chrome, identity for the content", per
 * the Mushroom/Bubble precedent — see brand/HA_CARD_REVIEW.md): the surface,
 * text colours and typography all come from Home Assistant's theme (the
 * <ha-card> owns the surface; text inherits the theme font). The card's
 * identity lives in the CONTENT — the EEA gauge, the severity ramp, the
 * pollutant glyphs, the air accent — which never theme-shift. The Bricolage
 * brand face is opt-in (brand_font: true), scoped to the title + hero word.
 *
 * Domain swaps for air quality:
 *   - Severity ramp = the official EEA 6-band air-quality ramp (the
 *     science-anchored colours the data layer already emits in
 *     bands.eaqi_eea_2024.colour — the single source of truth; this card never
 *     invents severity colours). The 3-segment pollen dial becomes a 6-segment
 *     EEA dial; "higher is worse" is preserved.
 *   - Brand accent = an air/atmosphere azure (the --pw-gold analog) → --aw-sky.
 *   - Per-pollutant glyphs (PM2.5/PM10/NO2/O3/SO2/CO) replace the per-species
 *     grains, in the same color-neutral --aw-grain-* treatment.
 *
 * Progressive disclosure (unchanged): the everyday surface is the hero gauge
 * (worst revised-EEA sub-index) + a compact per-pollutant row each with its own
 * band; on tap, each row opens its multi-authority provenance (WHO 2021 / EU
 * 2024/2881 / classic-vs-revised EEA) and cross-source consensus (n/m, agree /
 * disagree).
 *
 * The card is a pure CONSUMER of the entity model the data layer produces (it
 * changes nothing server-side):
 *   - sensor.airwatch_<source>_<pollutant>          — current reading; attrs:
 *       level (0/1/2), level_label, bands {authority: …}, unit_of_measurement,
 *       value_ppm (CO), forecast, station.
 *   - sensor.airwatch_analytics_<pollutant>_consensus — good/elevated/high/
 *       mixed; attrs: source_levels {src: level}, source_count,
 *       max_possible_sources.
 *   - binary_sensor.airwatch_analytics_<pollutant>_divergence — sources
 *       disagree by >1 level.
 *
 * Auto-registered by the integration's __init__.py (one install delivers both)
 * via the /airwatch_card_static static path. Config (all optional):
 *   { type: 'custom:airwatch-card', title?, pollutants?: [...],
 *     sources?: [...], expanded_default?: false }
 */
(() => {
  const CARD_VERSION = '0.2.0';  // visual-identity pass (PollenWatch-adapted)

  // ── Severity palettes ────────────────────────────────────────────────
  // EEA European Air Quality Index palette — mirrors pollutant_registry.
  // EAQI_BANDS (the single source of truth server-side). Each raw sensor
  // already carries the resolved colour in bands.<authority>.colour, so the
  // card reads that where available and falls back to this table only for the
  // gauge/legend or a missing attribute. Band names + colours are shared by
  // the classic and the revised EEA index (same 6 bands, different cut-points).
  const EAQI_PALETTE = {
    1: { label: 'Good', colour: '#50f0e6' },
    2: { label: 'Fair', colour: '#50ccaa' },
    3: { label: 'Moderate', colour: '#f0e641' },
    4: { label: 'Poor', colour: '#ff5050' },
    5: { label: 'Very poor', colour: '#960032' },
    6: { label: 'Extremely poor', colour: '#7d2181' },
  };

  // The common 0/1/2 severity scale (analytics.LEVEL_LABELS). Used for CO —
  // which is NOT in the EAQI and whose severity is WHO/EU-driven — and for the
  // per-source level dots in the consensus breakdown. Deliberately a DIFFERENT,
  // 3-step semantic ramp (green/amber/red) so CO never masquerades as a 6-band
  // EAQI rating.
  const LEVEL_PALETTE = {
    0: { label: 'Good', colour: '#3DAE5A' },
    1: { label: 'Elevated', colour: '#F2A516' },
    2: { label: 'High', colour: '#E0492E' },
  };
  const UNKNOWN_COLOUR = '#AEB7C0';
  const SLATE = '#33414F';
  const SKY = '#2E7DD1';

  // ── Pollutant display identities ─────────────────────────────────────
  const POLLUTANT_DISPLAY = {
    pm2_5: { name: 'PM2.5', formula: 'PM₂.₅' },
    pm10: { name: 'PM10', formula: 'PM₁₀' },
    nitrogen_dioxide: { name: 'Nitrogen dioxide', formula: 'NO₂' },
    ozone: { name: 'Ozone', formula: 'O₃' },
    sulphur_dioxide: { name: 'Sulphur dioxide', formula: 'SO₂' },
    carbon_monoxide: { name: 'Carbon monoxide', formula: 'CO' },
    european_aqi: { name: 'European AQI', formula: 'EAQI' },
  };
  const POLLUTANT_ORDER = [
    'pm2_5', 'pm10', 'nitrogen_dioxide', 'ozone',
    'sulphur_dioxide', 'carbon_monoxide', 'european_aqi',
  ];
  // Pollutants that have a bundled glyph (served at /airwatch_card_static/icons).
  const GLYPH_KEYS = new Set([
    'pm2_5', 'pm10', 'nitrogen_dioxide', 'ozone', 'sulphur_dioxide',
    'carbon_monoxide',
  ]);

  // The five concentration pollutants that define the EEA aggregate index. The
  // hero gauge shows the WORST of these revised-EEA sub-indexes — the EAQI is,
  // by definition, the worst sub-index. CO (different basis) and european_aqi
  // (itself an aggregate) are excluded from the gauge so they don't
  // double-count, but they still render as their own rows.
  const EAQI_SUBINDEX_POLLUTANTS = new Set([
    'pm2_5', 'pm10', 'nitrogen_dioxide', 'ozone', 'sulphur_dioxide',
  ]);

  // Open-Meteo (CAMS) is primary, covers every pollutant, and always carries
  // band provenance, so it is the preferred "headline reading" source; the
  // citizen + official networks fill in / cross-validate.
  const SOURCE_PRIORITY = ['open_meteo', 'sensor_community', 'land_steiermark'];
  const SOURCE_LABELS = {
    open_meteo: 'Open-Meteo (CAMS)',
    sensor_community: 'Sensor.Community',
    land_steiermark: 'Land Steiermark',
  };

  const AUTHORITY_LABELS = {
    eaqi_eea_2024: 'EEA index (2024 revised)',
    eaqi_classic: 'EEA index (classic / Open-Meteo)',
    who_2021: 'WHO 2021 guidelines',
    who_retained: 'WHO (retained short-averaging)',
    eu_2024_2881: 'EU Directive 2024/2881',
    eu_2008_50_ec: 'EU Directive 2008/50/EC',
  };

  const DOMAIN = 'airwatch';

  // ── AirWatch brand mark (header lockup) ──────────────────────────────
  // Adapted from PollenWatch's flower mark: same warning-gauge construction
  // (arc + slate needle), with the pollen bloom → an air/wind swirl and the
  // pollen-grain sunbursts → drifting PM-particle dots. Arc uses EEA-anchored
  // cyan→yellow→red stops. Kept verbatim in brand/assets/icon.svg.
  const AW_MARK = `<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M24.32 41.66 A27 27 0 0 1 37.95 25.84" stroke="#50ccaa" stroke-width="8" fill="none" stroke-linecap="round"></path><path d="M40.1 24.88 A27 27 0 0 1 59.9 24.88" stroke="#f0e641" stroke-width="8" fill="none" stroke-linecap="round"></path><path d="M62.05 25.84 A27 27 0 0 1 75.68 41.66" stroke="#ff5050" stroke-width="8" fill="none" stroke-linecap="round"></path><g opacity="0.62" fill="none" stroke-linecap="round"><path d="M32 45 H54.5 a5 5 0 1 0 -4.6 -5" stroke="#2E7DD1" stroke-width="3.3"></path><path d="M30 52.5 H58.5 a5.6 5.6 0 1 1 -5.2 5.6" stroke="#2E7DD1" stroke-width="3.3"></path><path d="M34.5 60 H51.5 a4.4 4.4 0 1 0 -4.1 4.4" stroke="#7CC0F2" stroke-width="3.3"></path></g><g fill="#2E7DD1"><circle cx="77" cy="54" r="2.7" opacity="0.92"></circle><circle cx="68" cy="70.5" r="2.1" opacity="0.6"></circle><circle cx="50" cy="79" r="2.8" opacity="0.92"></circle><circle cx="32" cy="70.5" r="2.1" opacity="0.6"></circle><circle cx="23" cy="54" r="2.7" opacity="0.92"></circle></g><path d="M50 50 L67.84 33.94" stroke="#33414F" stroke-width="4.5" stroke-linecap="round"></path><circle cx="50" cy="50" r="3" fill="#33414F"></circle></svg>`;

  // ── Per-pollutant glyph loading (color-neutral; tinted by the card) ──
  const ICON_URL = (key) => `/airwatch_card_static/icons/${key}.svg`;
  const ICON_CACHE = new Map();
  async function loadGlyph(key) {
    if (ICON_CACHE.has(key)) return ICON_CACHE.get(key);
    try {
      const r = await fetch(ICON_URL(key));
      const svg = r.ok ? await r.text() : null;
      ICON_CACHE.set(key, svg);
      return svg;
    } catch (_e) {
      ICON_CACHE.set(key, null);
      return null;
    }
  }

  // ── Brand web-font loading — OPT-IN only (brand_font: true) ──────────
  // Default is theme-native (no external request). When the user opts in, the
  // Bricolage display face is fetched once per document and applied (scoped to
  // the title + hero word via .brand-font); if the fetch fails (offline, CSP),
  // those elements fall back to the theme font, so nothing breaks.
  let _fontsInjected = false;
  function ensureFonts() {
    if (_fontsInjected) return;
    _fontsInjected = true;
    try {
      const head = document.head;
      if (!head || head.querySelector('link[data-aw-fonts]')) return;
      const mk = (rel, href, cross) => {
        const l = document.createElement('link');
        l.rel = rel; l.href = href;
        if (cross) l.crossOrigin = 'anonymous';
        return l;
      };
      const css = mk('stylesheet',
        'https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700&display=swap');
      css.setAttribute('data-aw-fonts', '');
      head.append(
        mk('preconnect', 'https://fonts.googleapis.com'),
        mk('preconnect', 'https://fonts.gstatic.com', true),
        css,
      );
    } catch (_e) { /* best-effort */ }
  }

  // ── helpers ──────────────────────────────────────────────────────────
  const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
  const isNum = (v) => v !== null && v !== undefined && v !== '' && !Number.isNaN(Number(v));

  function bandLabel(key) {
    if (!key) return null;
    return cap(String(key).replace(/_/g, ' '));
  }

  // Black or white text for legibility on a band-colour chip (per-channel
  // luminance) — essential because the EEA ramp spans very light (cyan) to very
  // dark (purple) bands.
  function textOn(hex) {
    if (!hex || hex[0] !== '#' || hex.length < 7) return '#1c2530';
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    return lum > 0.6 ? '#1c2530' : '#ffffff';
  }

  function fmtReading(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return '—';
    if (Math.abs(n) >= 10) return String(Math.round(n));
    return String(Math.round(n * 10) / 10);
  }

  //   returns { colour, label, band, basis } | null
  function severityFor(pollutant, ent) {
    const bands = ent?.attributes?.bands || {};
    if (pollutant === 'carbon_monoxide') {
      const lvl = ent?.attributes?.level;
      if (lvl === null || lvl === undefined) return null;
      const p = LEVEL_PALETTE[lvl] || LEVEL_PALETTE[0];
      return { colour: p.colour, label: p.label, basis: 'WHO / EU', band: null };
    }
    if (pollutant === 'european_aqi') {
      const c = bands.eaqi_classic;
      if (!c) return null;
      return {
        colour: c.colour || EAQI_PALETTE[c.band_index]?.colour || UNKNOWN_COLOUR,
        label: bandLabel(c.band) || EAQI_PALETTE[c.band_index]?.label,
        basis: 'classic index', band: c.band_index,
      };
    }
    const r = bands.eaqi_eea_2024;
    if (!r) return null;
    return {
      colour: r.colour || EAQI_PALETTE[r.band_index]?.colour || UNKNOWN_COLOUR,
      label: bandLabel(r.band) || EAQI_PALETTE[r.band_index]?.label,
      basis: 'revised EEA', band: r.band_index,
    };
  }

  // ── per-pollutant resolution against hass.states ─────────────────────
  function resolvePollutant(hass, pollutant, sourceFilter) {
    const states = hass.states;
    let primary = null;
    for (const src of SOURCE_PRIORITY) {
      if (sourceFilter && !sourceFilter.has(src)) continue;
      const ent = states[`sensor.${DOMAIN}_${src}_${pollutant}`];
      if (ent && isNum(ent.state)) {
        primary = { src, ent };
        break;
      }
    }
    const consensus = states[`sensor.${DOMAIN}_analytics_${pollutant}_consensus`];
    const divergence = states[`binary_sensor.${DOMAIN}_analytics_${pollutant}_divergence`];

    const disp = POLLUTANT_DISPLAY[pollutant] || {
      name: cap(pollutant.replace(/_/g, ' ')), formula: pollutant,
    };

    if (!primary) {
      return {
        pollutant, ...disp, state: 'unknown',
        reading: null, unit: '', severity: null,
        source: null, consensus, divergence, bands: null,
      };
    }

    const ent = primary.ent;
    return {
      pollutant, ...disp, state: 'ok',
      reading: ent.state,
      unit: ent.attributes.unit_of_measurement || '',
      severity: severityFor(pollutant, ent),
      source: primary.src,
      sourceLabel: SOURCE_LABELS[primary.src] || primary.src,
      level: ent.attributes.level,
      levelLabel: ent.attributes.level_label,
      valuePpm: ent.attributes.value_ppm,
      bands: ent.attributes.bands || null,
      consensus, divergence,
    };
  }

  function consensusView(hass, pollutant, consensusEnt) {
    if (!consensusEnt) return null;
    const a = consensusEnt.attributes || {};
    const levels = a.source_levels || {};
    const count = a.source_count ?? Object.keys(levels).length;
    const max = a.max_possible_sources ?? count;
    const state = consensusEnt.state;
    const rows = Object.entries(levels).map(([src, level]) => {
      const raw = hass.states[`sensor.${DOMAIN}_${src}_${pollutant}`];
      return {
        src, level,
        label: SOURCE_LABELS[src] || src,
        value: raw && isNum(raw.state) ? raw.state : null,
        unit: raw?.attributes?.unit_of_measurement || '',
        station: raw?.attributes?.station || null,
      };
    });
    return { state, count, max, rows };
  }

  // ── EEA 6-band severity gauge (adapts the PollenWatch gauge mechanics) ─
  // A clean 180° dial (the brand guide's .gauge-big composition): the hub sits
  // ON the arc baseline and the viewBox is cropped tight, so the
  // arc→needle→hub reads as ONE connected gauge. 6 segments cyan→purple. The
  // needle rests at the ACTIVE band's segment centre (never interpolated) and
  // is removed for the unknown state (dashed gray track, gray-never-green); the
  // active segment thickens and the hub takes its colour ("status hub"). The
  // air motif lives in the header mark, not inside the dial.
  const GA = { CX: 60, CY: 58, R: 45, W: 11, H: 90, GAP: 3, N: 6, VH: 70 };
  const gpt = (r, deg) => {
    const a = (deg - 90) * Math.PI / 180;
    return [GA.CX + r * Math.cos(a), GA.CY + r * Math.sin(a)];
  };
  const gf = (n) => Math.round(n * 100) / 100;
  function gArc(a0, a1, col, w, op = 1, dash = null) {
    const [x0, y0] = gpt(GA.R, a0);
    const [x1, y1] = gpt(GA.R, a1);
    const large = (a1 - a0) > 180 ? 1 : 0;
    const d = dash ? ` stroke-dasharray="${dash}"` : '';
    return `<path d="M${gf(x0)} ${gf(y0)} A${GA.R} ${GA.R} 0 ${large} 1 ${gf(x1)} ${gf(y1)}" stroke="${col}" stroke-width="${w}" fill="none" stroke-linecap="round" opacity="${op}"${d}/>`;
  }
  function gBounds() {
    const span = 2 * GA.H;
    const segW = (span - GA.GAP * (GA.N - 1)) / GA.N;
    const out = [];
    for (let i = 0; i < GA.N; i++) {
      const s = -GA.H + i * (segW + GA.GAP);
      out.push([s, s + segW, (2 * s + segW) / 2]);
    }
    return out;
  }
  function gNeedle(deg) {
    const [nx, ny] = gpt(GA.R - 9, deg);
    return `<path class="aw-needle" d="M${GA.CX} ${GA.CY} L${gf(nx)} ${gf(ny)}" stroke="${SLATE}" stroke-width="3.6" stroke-linecap="round"/>`;
  }
  // band: 1..6 → active band; null → unknown (resting, no needle). `label`
  // is the screen-reader summary of the reading (a11y — the dial is role="img"
  // with a <title>). Callers pass an already-escaped label.
  function awGauge(band, label) {
    const B = gBounds();
    const attrs = label ? ` role="img" aria-label="${label}"` : '';
    const title = label ? `<title>${label}</title>` : '';
    const open = `<svg class="aw-gauge" viewBox="0 0 120 ${GA.VH}" xmlns="http://www.w3.org/2000/svg"${attrs}>${title}`;
    if (!band) {
      return `${open}${
        gArc(-GA.H, GA.H, UNKNOWN_COLOUR, GA.W, 0.9, '1.5 5')
      }<circle class="hub" cx="${GA.CX}" cy="${GA.CY}" r="5" fill="var(--aw-cloud,#fff)" stroke="${UNKNOWN_COLOUR}" stroke-width="2"/></svg>`;
    }
    const ai = band - 1;
    const col = EAQI_PALETTE[band].colour;
    const segs = B.map((b, i) =>
      gArc(b[0], b[1], EAQI_PALETTE[i + 1].colour, i === ai ? GA.W + 3 : GA.W, 1)).join('');
    return `${open}${segs}${gNeedle(B[ai][2])
    }<circle class="hub" cx="${GA.CX}" cy="${GA.CY}" r="5" fill="${col}"/></svg>`;
  }

  // ── CSS ──────────────────────────────────────────────────────────────
  const CARD_CSS = `
    :host {
      /* Brand accent — air/atmosphere azure (the --pw-gold analog). */
      --aw-sky: #2E7DD1; --aw-sky-light: #8FC7F0; --aw-sky-deep: #1F5C9E;
      /* Neutrals — theme-aware, with the PollenWatch paper palette as fallback. */
      --aw-ink: var(--primary-text-color, #2A3540);
      --aw-muted: var(--secondary-text-color, #7C8794);
      --aw-cloud: var(--ha-card-background, var(--card-background-color, #FFFFFF));
      --aw-edge: var(--divider-color, #ECE4D6);
      --aw-hover: var(--secondary-background-color, rgba(0,0,0,0.04));
      /* EEA 6-band severity ramp — science-anchored, NEVER theme-shifted. */
      --aw-eaqi-1: #50f0e6; --aw-eaqi-2: #50ccaa; --aw-eaqi-3: #f0e641;
      --aw-eaqi-4: #ff5050; --aw-eaqi-5: #960032; --aw-eaqi-6: #7d2181;
      /* Per-glyph tint (color-neutral SVGs read these). */
      --aw-grain-stroke: var(--aw-ink);
      --aw-grain-fill: var(--aw-edge);
      /* Typography is THEME-NATIVE: all text inherits Home Assistant's font.
         The brand display face (Bricolage) is opt-in (brand_font: true) and
         scoped to the title + hero word only — see .card.brand-font below. */
      --aw-r-pill: 999px;
      display: block;
    }
    /* The surface (background, border, radius, shadow) is owned by <ha-card> so
       it matches the user's theme — we add only padding + internal layout.
       Identity lives in the CONTENT (EEA gauge, ramp, glyphs, accent), not the
       chrome. */
    /* Base text colour comes from the theme (--primary-text-color, via
       --aw-ink) so every element that doesn't set its own colour inherits a
       legible, theme-derived value on ANY background — custom properties
       inherit through the shadow boundary, so this resolves to the user's
       theme even though the card is in a shadow root. */
    .card { padding: 16px 18px 14px; color: var(--aw-ink); }

    /* ── header: mark · title · meta ── */
    .header { display: flex; align-items: center; gap: 14px; }
    .mark { width: 48px; height: 48px; flex-shrink: 0; margin: 1px 2px 0 0; }
    .mark svg { width: 100%; height: 100%; display: block; }
    .titles { min-width: 0; }
    .title {
      font-weight: 600; font-size: 18px;
      letter-spacing: -0.015em; line-height: 1.15;
    }
    .submeta { font-size: 12.5px; color: var(--aw-muted); margin-top: 1px; }
    .meta { margin-left: auto; display: flex; align-items: center; }
    .badge {
      font-variant-numeric: tabular-nums;
      font-weight: 600; font-size: 12.5px; color: var(--aw-ink);
      padding: 3px 9px; border-radius: var(--aw-r-pill);
      background: var(--aw-edge);
    }
    /* Opt-in brand display face — scoped to ONLY the title + hero band word, so
       even when enabled the rest of the card stays on the theme font. Loaded
       best-effort (see ensureFonts); off by default → no external request. */
    .card.brand-font .title,
    .card.brand-font .reading .level {
      font-family: "Bricolage Grotesque", var(--ha-card-header-font-family, inherit);
    }

    /* ── hero: gauge + reading (even vertical rhythm) ── */
    .hero {
      display: flex; flex-direction: column; align-items: center; gap: 12px;
      padding: 16px 0; margin-top: 14px;
      border-top: 1px solid var(--aw-edge);
    }
    .gauge-wrap { width: 210px; max-width: 66%; }
    .aw-gauge { width: 100%; height: auto; display: block; }
    .aw-needle, .hub { transition: opacity 200ms; }
    .reading { text-align: center; }
    .reading .level {
      font-weight: 700; font-size: 30px;
      line-height: 1; letter-spacing: -0.02em; transition: color 200ms;
    }
    .reading .cap {
      font-size: 12px; color: var(--aw-muted); letter-spacing: 0.06em;
      text-transform: uppercase; margin-top: 6px;
    }

    /* ── rows ── */
    .rows {
      display: flex; flex-direction: column; gap: 1px;
      padding-top: 6px; border-top: 1px solid var(--aw-edge);
    }
    .row {
      display: block; width: 100%; text-align: left; padding: 0;
      background: transparent; border: none; color: inherit; font: inherit;
      border-radius: 12px; cursor: pointer;
    }
    /* Flex row that WRAPS: the name keeps a readable basis (never shrinks below
       it), and the reading+pill cluster drops to a second line when the row is
       too narrow — instead of crushing the name. Names wrap at word boundaries,
       never per-character, and never truncate. */
    .row-head {
      display: flex; flex-wrap: wrap; align-items: center; gap: 6px 10px;
      padding: 8px 10px; border-radius: 12px;
    }
    .row:hover .row-head, .row:focus-visible .row-head {
      background: var(--aw-hover); outline: none;
    }
    .glyph {
      width: 30px; height: 30px; flex: 0 0 30px;
      display: inline-flex; align-items: center; justify-content: center;
    }
    .glyph svg { width: 100%; height: 100%; display: block; }
    .p-name {
      flex: 1 1 130px; min-width: 0;
      font-weight: 600; font-size: 14.5px; line-height: 1.25;
      overflow-wrap: break-word;
    }
    .row-right {
      margin-left: auto; flex: 0 0 auto;
      display: inline-flex; align-items: center; gap: 10px;
    }
    .p-name .formula { color: var(--aw-muted); font-weight: 500; margin-left: 6px; font-size: 12.5px; }
    .diverge-flag { color: var(--warning-color, #C77700); margin-left: 6px; font-weight: 600; font-size: 11px; }
    .p-reading {
      font-variant-numeric: tabular-nums; font-size: 14px; white-space: nowrap;
      text-align: right; color: var(--aw-ink);
    }
    .p-reading .unit { color: var(--aw-muted); font-size: 12px; margin-left: 3px; }
    .pill {
      display: inline-flex; align-items: center; gap: 7px;
      padding: 5px 12px 5px 10px; border-radius: var(--aw-r-pill);
      font-weight: 600; font-size: 12px;
      white-space: nowrap;
    }
    .pill .pdot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
    .pill.unknown {
      background: transparent; border: 1px dashed var(--aw-edge); color: var(--aw-muted);
    }
    .chev {
      color: var(--aw-muted); justify-self: end; font-size: 12px;
      transition: transform 160ms;
    }
    .row[aria-expanded="true"] .chev { transform: rotate(90deg); }

    /* ── expanded provenance / consensus ──
       Left padding aligns the detail to the row's NAME column (row-head
       padding-left 10 + glyph 30 + gap 10 = 50), so the callout sits on the
       same vertical grid line as the pollutant names above/below. */
    .detail { display: none; padding: 2px 10px 14px 50px; }
    .row[aria-expanded="true"] + .detail { display: block; }
    .detail-block { margin-top: 12px; }
    .detail-block:first-child { margin-top: 4px; }
    .detail-h {
      font-weight: 600;
      font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase;
      color: var(--aw-muted); margin-bottom: 6px;
    }
    .src-row { display: flex; align-items: center; gap: 8px; font-size: 13px; padding: 2px 0; }
    .src-dot { width: 9px; height: 9px; border-radius: 999px; flex-shrink: 0; background: ${UNKNOWN_COLOUR}; }
    .src-label { font-weight: 500; }
    .src-value { margin-left: auto; font-variant-numeric: tabular-nums; color: var(--aw-muted); }
    .src-station { color: var(--aw-muted); font-size: 11px; font-style: italic; }
    .consensus-verdict { font-size: 12.5px; margin-top: 5px; }
    .consensus-verdict.mixed { color: var(--warning-color, #C77700); font-weight: 600; }
    .auth-row { font-size: 12.5px; padding: 3px 0; display: flex; gap: 8px; align-items: baseline; }
    .auth-name { color: var(--aw-muted); min-width: 96px; flex-shrink: 0; }
    .auth-body { line-height: 1.5; }
    .exceeds { color: var(--error-color, #D33A2C); font-weight: 600; }
    .within { color: var(--success-color, #2E8B57); font-weight: 600; }
    .it-targets { color: var(--aw-muted); font-size: 11.5px; }
    .basis-note {
      font-size: 12.5px; margin-bottom: 6px; padding: 7px 9px;
      background: var(--aw-hover); border-radius: 8px; line-height: 1.45;
    }
    .basis-note.differ { border-left: 3px solid var(--aw-sky); }

    /* ── footer ── */
    .footer { margin-top: 12px; display: flex; justify-content: center; }
    .toggle-all {
      font-weight: 600; font-size: 11px;
      letter-spacing: 0.08em; text-transform: uppercase;
      color: var(--aw-muted); background: transparent;
      border: 1px solid var(--aw-edge); border-radius: var(--aw-r-pill);
      padding: 6px 14px; cursor: pointer;
    }
    .toggle-all:hover { color: var(--aw-ink); border-color: var(--aw-muted); }
    .empty { padding: 18px; text-align: center; color: var(--aw-muted); font-size: 13px; }

    @media (prefers-reduced-motion: reduce) {
      .chev, .aw-needle, .reading .level { transition: none !important; }
    }
  `;

  // ── Card element ─────────────────────────────────────────────────────
  class AirWatchCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._expanded = new Set();
    }

    connectedCallback() {
      // Only fetch the brand webfont when the user opted in (brand_font: true);
      // theme-native is the default and makes no external request.
      if (this._config?.brand_font) ensureFonts();
    }

    setConfig(config) {
      if (!config || typeof config !== 'object') {
        throw new Error('airwatch-card: config object required');
      }
      const explicit = Array.isArray(config.pollutants)
        ? config.pollutants.slice()
        : (typeof config.pollutants === 'string' ? [config.pollutants] : null);
      const sources = Array.isArray(config.sources) && config.sources.length
        ? new Set(config.sources)
        : null;
      this._config = {
        title: 'Air quality',
        expanded_default: false,
        ...config,
        _explicitPollutants: explicit,
        _sourceFilter: sources,
      };
      this._expandedDefault = !!this._config.expanded_default;
      this._appliedDefault = false;
      this._discoveredPollutants = null;
      this._discoveryPromise = null;
      this._built = false;
      if (this._config.brand_font) ensureFonts();
      this._build();
    }

    set hass(hass) {
      const first = !this._hass;
      this._hass = hass;
      if (first) this._ensureDiscovery();
      if (this._built) this._render();
    }

    getCardSize() {
      const n = this._resolvePollutantKeys().length || 4;
      return 4 + n;
    }

    // Sections-view sizing (12-column grid; ~30px×56px cells). This is a rich
    // multi-metric card, so it defaults to full width but can go down to half;
    // height scales with the pollutant count (header + gauge + rows + footer),
    // with a sensible floor and ceiling. getCardSize above stays the masonry
    // fallback for the legacy layout.
    getGridOptions() {
      const n = this._resolvePollutantKeys().length || 6;
      return {
        columns: 12,
        min_columns: 6,
        rows: Math.max(6, Math.min(13, 5 + Math.ceil(n * 0.8))),
        min_rows: 5,
      };
    }

    static getStubConfig() {
      return { type: 'custom:airwatch-card' };
    }

    static getConfigElement() {
      return document.createElement('airwatch-card-editor');
    }

    _resolvePollutantKeys() {
      let keys;
      if (this._config?._explicitPollutants) keys = this._config._explicitPollutants.slice();
      else if (this._discoveredPollutants) keys = this._discoveredPollutants.slice();
      else keys = this._scanPollutants();
      const orderIdx = (k) => {
        const i = POLLUTANT_ORDER.indexOf(k);
        return i === -1 ? POLLUTANT_ORDER.length : i;
      };
      return keys.slice().sort((a, b) => orderIdx(a) - orderIdx(b) || a.localeCompare(b));
    }

    _scanPollutants() {
      const states = this._hass?.states;
      if (!states) return [];
      const prefix = `sensor.${DOMAIN}_analytics_`;
      const suffix = '_consensus';
      const out = [];
      for (const id of Object.keys(states)) {
        if (id.startsWith(prefix) && id.endsWith(suffix)) {
          out.push(id.slice(prefix.length, id.length - suffix.length));
        }
      }
      return out;
    }

    async _ensureDiscovery() {
      if (this._discoveryPromise) return this._discoveryPromise;
      if (!this._hass?.callWS) {
        this._discoveryPromise = Promise.resolve();
        return this._discoveryPromise;
      }
      this._discoveryPromise = (async () => {
        try {
          const entries = await this._hass.callWS({
            type: 'config_entries/get', domain: DOMAIN,
          });
          if (!Array.isArray(entries) || entries.length === 0) return;
          const result = await this._hass.callWS({
            type: 'airwatch/config', entry_id: entries[0].entry_id,
          });
          if (result?.selected_pollutants) {
            this._discoveredPollutants = result.selected_pollutants.slice();
            if (this._built) this._render();
          }
        } catch (_e) { /* fall back to scan — deliberately silent. */ }
      })();
      return this._discoveryPromise;
    }

    _build() {
      const brandClass = this._config.brand_font ? ' brand-font' : '';
      this.shadowRoot.innerHTML = `
        <style>${CARD_CSS}</style>
        <ha-card class="card${brandClass}" data-card>
          <div class="header">
            <span class="mark">${AW_MARK}</span>
            <div class="titles">
              <div class="title" data-title></div>
              <div class="submeta" data-submeta></div>
            </div>
            <span class="meta"><span class="badge" data-badge></span></span>
          </div>
          <div class="hero" data-hero>
            <div class="gauge-wrap" data-gauge></div>
            <div class="reading" data-reading></div>
          </div>
          <div class="rows" data-rows></div>
          <div class="footer">
            <button class="toggle-all" data-toggle-all aria-pressed="false"></button>
          </div>
        </ha-card>
      `;
      this.shadowRoot.querySelector('[data-title]').textContent = this._config.title;

      const rowsEl = this.shadowRoot.querySelector('[data-rows]');
      rowsEl.addEventListener('click', (e) => {
        const row = e.target.closest('.row[data-pollutant]');
        if (!row) return;
        this._toggleRow(row.getAttribute('data-pollutant'));
      });
      rowsEl.addEventListener('keydown', (e) => {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        const row = e.target.closest('.row[data-pollutant]');
        if (!row) return;
        e.preventDefault();
        this._toggleRow(row.getAttribute('data-pollutant'));
      });

      const toggleAll = this.shadowRoot.querySelector('[data-toggle-all]');
      toggleAll.addEventListener('click', () => {
        const keys = this._resolvePollutantKeys();
        const allOpen = keys.length > 0 && keys.every((k) => this._expanded.has(k));
        this._expanded = allOpen ? new Set() : new Set(keys);
        this._render();
      });

      this._built = true;
      if (this._hass) this._render();
    }

    _toggleRow(pollutant) {
      if (this._expanded.has(pollutant)) this._expanded.delete(pollutant);
      else this._expanded.add(pollutant);
      this._render();
    }

    _render() {
      if (!this._hass || !this._built) return;
      const keys = this._resolvePollutantKeys();
      const rowsEl = this.shadowRoot.querySelector('[data-rows]');
      const heroEl = this.shadowRoot.querySelector('[data-hero]');
      const badgeEl = this.shadowRoot.querySelector('[data-badge]');
      const submetaEl = this.shadowRoot.querySelector('[data-submeta]');
      const toggleAll = this.shadowRoot.querySelector('[data-toggle-all]');

      if (keys.length === 0) {
        heroEl.style.display = 'none';
        badgeEl.textContent = '';
        submetaEl.textContent = '';
        rowsEl.innerHTML = `<div class="empty">No AirWatch pollutants found yet.</div>`;
        toggleAll.style.display = 'none';
        return;
      }
      heroEl.style.display = '';
      toggleAll.style.display = '';

      if (this._expandedDefault && !this._appliedDefault) {
        this._expanded = new Set(keys);
        this._appliedDefault = true;
      }

      const rows = keys.map((k) =>
        resolvePollutant(this._hass, k, this._config._sourceFilter));

      this._renderHero(heroEl, rows);

      // Card-level n/m badge + "N sources" submeta.
      const counts = rows
        .map((r) => r.consensus?.attributes)
        .filter(Boolean)
        .map((a) => ({ c: a.source_count ?? 0, m: a.max_possible_sources ?? 0 }));
      if (counts.length) {
        const c = Math.max(...counts.map((x) => x.c));
        const m = Math.max(...counts.map((x) => x.m));
        badgeEl.textContent = m > 0 ? `${c}/${m}` : '';
        submetaEl.textContent = m > 0
          ? `${c} of ${m} ${m === 1 ? 'source' : 'sources'} reporting`
          : '';
      } else {
        badgeEl.textContent = '';
        submetaEl.textContent = '';
      }

      rowsEl.innerHTML = rows.map((r) => this._renderRow(r)).join('');
      this._inlineGlyphs(rowsEl);

      const allOpen = keys.every((k) => this._expanded.has(k));
      toggleAll.textContent = allOpen ? 'Hide provenance' : 'Show provenance';
      toggleAll.setAttribute('aria-pressed', String(allOpen));
    }

    _renderHero(el, rows) {
      // Worst revised sub-index among the EAQI-defining pollutants.
      let worst = null;
      for (const r of rows) {
        if (!EAQI_SUBINDEX_POLLUTANTS.has(r.pollutant)) continue;
        const sev = r.severity;
        if (!sev || sev.band == null) continue;
        if (!worst || sev.band > worst.sev.band) worst = { r, sev };
      }
      const gaugeEl = el.querySelector('[data-gauge]');
      const readingEl = el.querySelector('[data-reading]');
      if (!worst) {
        // Fail-safe: no EAQI sub-index reading → resting/unknown gauge, never
        // a fake green.
        gaugeEl.innerHTML = awGauge(null, 'Air quality: unknown — no current index reading');
        readingEl.innerHTML =
          `<div class="level" style="color:var(--aw-muted)">Unknown</div>` +
          `<div class="cap">No current air-quality index reading</div>`;
        return;
      }
      const { r, sev } = worst;
      const a11y = this._esc(`Air quality: ${sev.label} — worst sub-index ${r.name}`);
      gaugeEl.innerHTML = awGauge(sev.band, a11y);
      readingEl.innerHTML =
        `<div class="level" style="color:${sev.colour}">${this._esc(sev.label)}</div>` +
        `<div class="cap">Overall · worst sub-index ${this._esc(r.formula)}</div>`;
    }

    _renderRow(r) {
      const expanded = this._expanded.has(r.pollutant);
      const sev = r.severity;

      // Pill — band colour bg + contrast-aware text/dot, or a dashed outline
      // pill for unknown.
      let pill;
      if (r.state === 'unknown' || !sev) {
        pill = `<span class="pill unknown">Unknown</span>`;
      } else {
        const fg = textOn(sev.colour);
        const dot = fg === '#ffffff' ? 'rgba(255,255,255,0.92)' : 'rgba(0,0,0,0.45)';
        pill = `<span class="pill" style="background:${sev.colour};color:${fg}">` +
          `<span class="pdot" style="background:${dot}"></span>${this._esc(sev.label)}</span>`;
      }

      const reading = r.state === 'unknown'
        ? `<span class="p-reading">—</span>`
        : `<span class="p-reading">${this._esc(fmtReading(r.reading))}<span class="unit">${this._esc(r.unit)}</span></span>`;

      const diverged = r.divergence && r.divergence.state === 'on';
      const divergeFlag = diverged ? `<span class="diverge-flag">⚠ differ</span>` : '';

      // Glyph holder — color-neutral SVG inlined after render; a faint
      // severity wash tints the fill while the outline stays legible.
      const hasGlyph = GLYPH_KEYS.has(r.pollutant);
      const glyphTint = (sev && r.state !== 'unknown')
        ? ` style="--aw-grain-fill:${sev.colour}33"` : '';
      const glyph = hasGlyph
        ? `<span class="glyph" data-glyph="${this._esc(r.pollutant)}"${glyphTint} aria-hidden="true"></span>`
        : `<span class="glyph" aria-hidden="true"></span>`;

      return `
        <button class="row" data-pollutant="${this._esc(r.pollutant)}"
                aria-expanded="${expanded}"
                aria-label="${this._esc(r.name)} — ${this._esc(sev?.label || 'unknown')}">
          <span class="row-head">
            ${glyph}
            <span class="p-name">${this._esc(r.name)}<span class="formula">${this._esc(r.formula)}</span>${divergeFlag}</span>
            <span class="row-right">
              ${reading}
              ${pill}
              <span class="chev">▸</span>
            </span>
          </span>
        </button>
        <div class="detail">${expanded ? this._renderDetail(r) : ''}</div>
      `;
    }

    _inlineGlyphs(rowsEl) {
      rowsEl.querySelectorAll('[data-glyph]').forEach((holder) => {
        const key = holder.getAttribute('data-glyph');
        loadGlyph(key).then((svg) => {
          if (svg && holder.isConnected) holder.innerHTML = svg;
        });
      });
    }

    _renderDetail(r) {
      const parts = [];

      const cv = consensusView(this._hass, r.pollutant, r.consensus);
      if (cv) {
        const srcRows = cv.rows.map((s) => {
          const dot = LEVEL_PALETTE[s.level]?.colour || UNKNOWN_COLOUR;
          const val = s.value != null
            ? `${this._esc(fmtReading(s.value))} ${this._esc(s.unit)}`
            : 'missing';
          const station = s.station ? `<span class="src-station"> · ${this._esc(s.station)}</span>` : '';
          return `<div class="src-row">
            <span class="src-dot" style="background:${dot}"></span>
            <span class="src-label">${this._esc(s.label)}</span>${station}
            <span class="src-value">${val}</span>
          </div>`;
        }).join('');
        let verdict;
        if (cv.state === 'mixed') {
          verdict = `<div class="consensus-verdict mixed">Sources disagree by more than one level.</div>`;
        } else if (cv.count >= 2) {
          verdict = `<div class="consensus-verdict">${cv.count} of ${cv.max} sources agree (${this._esc(cv.state)}).</div>`;
        } else {
          verdict = `<div class="consensus-verdict">Single source — not yet cross-validated (${cv.count}/${cv.max}).</div>`;
        }
        parts.push(`<div class="detail-block">
          <div class="detail-h">Cross-source consensus</div>
          ${srcRows}${verdict}
        </div>`);
      }

      const basisNote = this._indexBasisNote(r);
      if (basisNote) parts.push(basisNote);

      const auth = this._renderAuthorities(r);
      if (auth) parts.push(auth);

      if (parts.length === 0) {
        parts.push(`<div class="detail-block"><div class="consensus-verdict">No provenance available for this reading.</div></div>`);
      }
      return parts.join('');
    }

    _indexBasisNote(r) {
      const b = r.bands;
      if (!b) return null;
      const classic = b.eaqi_classic;
      const revised = b.eaqi_eea_2024;
      if (r.pollutant === 'carbon_monoxide') {
        return `<div class="basis-note">CO is not part of the European AQI. Severity here is the
          WHO 2021 / EU 2024 basis: <strong>${this._esc(r.levelLabel || '—')}</strong>${
          r.valuePpm != null ? ` (≈ ${this._esc(String(r.valuePpm))} ppm)` : ''}.</div>`;
      }
      if (r.pollutant === 'european_aqi') {
        return classic
          ? `<div class="basis-note">Aggregate index on the classic EEA / Open-Meteo scale:
             <strong>${this._esc(bandLabel(classic.band))}</strong>.</div>`
          : null;
      }
      if (!classic || !revised) return null;
      const cl = bandLabel(classic.band);
      const rv = bandLabel(revised.band);
      if (classic.band_index !== revised.band_index) {
        return `<div class="basis-note differ">Index basis differs — Open-Meteo's classic index reads
          <strong>${this._esc(cl)}</strong>, the current official revised EEA index reads
          <strong>${this._esc(rv)}</strong>. The everyday colour follows the revised (official) index.</div>`;
      }
      return `<div class="basis-note">Official revised EEA index: <strong>${this._esc(rv)}</strong>
        (the classic Open-Meteo index agrees).</div>`;
    }

    _renderAuthorities(r) {
      const b = r.bands;
      if (!b) return null;
      const blocks = [];
      for (const key of ['who_2021', 'who_retained', 'eu_2024_2881']) {
        const list = b[key];
        if (!Array.isArray(list) || list.length === 0) continue;
        const rows = list.map((e) => this._authEntry(key, e)).join('');
        blocks.push(`<div class="auth-row">
          <span class="auth-name">${this._esc(AUTHORITY_LABELS[key] || key)}</span>
          <span class="auth-body">${rows}</span>
        </div>`);
      }
      if (blocks.length === 0) return null;
      return `<div class="detail-block">
        <div class="detail-h">Health &amp; legal thresholds</div>
        ${blocks.join('')}
      </div>`;
    }

    _authEntry(authority, e) {
      const verdict = e.exceeds
        ? `<span class="exceeds">exceeds</span>`
        : `<span class="within">within</span>`;
      let line = `${this._esc(e.averaging)}: ${this._esc(String(e.value))} µg/m³ — ${verdict}`;
      if (authority === 'eu_2024_2881' && e.attain_by) {
        line += ` <span class="it-targets">(${this._esc(e.kind || 'limit')}, by ${this._esc(String(e.attain_by))})</span>`;
      }
      if (Array.isArray(e.interim_targets) && e.interim_targets.length) {
        line += ` <span class="it-targets">· interim: ${e.interim_targets.map((t) => this._esc(String(t))).join(', ')}</span>`;
      }
      return `<div>${line}</div>`;
    }

    _esc(s) {
      return String(s ?? '')
        .replaceAll('&', '&amp;').replaceAll('"', '&quot;')
        .replaceAll('<', '&lt;').replaceAll('>', '&gt;');
    }
  }

  // ── Minimal config editor (ha-form) ──────────────────────────────────
  class AirWatchCardEditor extends HTMLElement {
    setConfig(config) {
      this._config = { ...config };
      this._render();
    }

    set hass(hass) {
      this._hass = hass;
      if (this._form) this._form.hass = hass;
    }

    _schema() {
      return [
        { name: 'title', selector: { text: {} } },
        { name: 'expanded_default', selector: { boolean: {} } },
        { name: 'brand_font', selector: { boolean: {} } },
        {
          name: 'pollutants',
          selector: {
            select: {
              multiple: true, mode: 'list', custom_value: true,
              options: POLLUTANT_ORDER.map((k) => ({
                value: k, label: (POLLUTANT_DISPLAY[k]?.name || k),
              })),
            },
          },
        },
        {
          name: 'sources',
          selector: {
            select: {
              multiple: true, mode: 'list', custom_value: true,
              options: SOURCE_PRIORITY.map((k) => ({
                value: k, label: SOURCE_LABELS[k] || k,
              })),
            },
          },
        },
      ];
    }

    _render() {
      if (this._form) {
        this._form.data = this._config;
        return;
      }
      const form = document.createElement('ha-form');
      form.schema = this._schema();
      form.data = this._config || {};
      form.computeLabel = (s) => ({
        title: 'Card title',
        expanded_default: 'Expand provenance by default',
        brand_font: 'Use the AirWatch brand font (Bricolage; loads a web font)',
        pollutants: 'Pollutants (blank = all configured)',
        sources: 'Sources (blank = all enabled)',
      }[s.name] || s.name);
      if (this._hass) form.hass = this._hass;
      form.addEventListener('value-changed', (e) => {
        this._config = e.detail.value;
        this.dispatchEvent(new CustomEvent('config-changed', {
          detail: { config: this._config }, bubbles: true, composed: true,
        }));
      });
      this.appendChild(form);
      this._form = form;
    }
  }

  if (!customElements.get('airwatch-card')) {
    customElements.define('airwatch-card', AirWatchCard);
  }
  if (!customElements.get('airwatch-card-editor')) {
    customElements.define('airwatch-card-editor', AirWatchCardEditor);
  }

  window.customCards = window.customCards || [];
  if (!window.customCards.some((c) => c.type === 'airwatch-card')) {
    window.customCards.push({
      type: 'airwatch-card',
      name: 'AirWatch',
      description: 'Multi-source air quality — the official EEA severity gauge at a glance, '
        + 'multi-authority provenance (WHO / EU) and cross-source consensus on tap.',
      preview: false,
      documentationURL: 'https://github.com/TheDave94/airwatch',
    });
  }

  /* eslint-disable no-console */
  console.info(
    `%c airwatch-card %c v${CARD_VERSION} `,
    'background:#2E7DD1;color:#EAF2FB;font-weight:600;padding:2px 6px;border-radius:3px 0 0 3px;',
    'background:#2A3540;color:#EAF2F0;padding:2px 6px;border-radius:0 3px 3px 0;'
  );
})();
