/**
 * airwatch-card.js — Lovelace custom card for AirWatch.
 *
 * Progressive disclosure (the decided model):
 *   - EVERYDAY SURFACE (always visible): a headline severity — the worst
 *     revised-EEA sub-index across the displayed pollutants, shown with the
 *     official EEA colour ramp — plus one compact row per pollutant carrying
 *     its current reading and its own revised-EEA band colour. This is the
 *     glance value: "what is the air doing now."
 *   - ON EXPAND / TAP (the depth): per pollutant, the multi-authority
 *     provenance — what WHO 2021 (per averaging window + interim targets),
 *     EU 2024/2881 (both milestones) and the classic-vs-revised EEA indexes
 *     each say about this reading — and the cross-source consensus (n/m
 *     sources, agree / disagree). Opt-in, not always-on.
 *
 * The card is a pure CONSUMER of the entity model the data layer already
 * produces (it changes nothing server-side):
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
 *
 * Mirrors PollenWatch's card conventions (vanilla-JS IIFE, shadow DOM, themed
 * CSS, WS discovery with a hass.states scan fallback) — but the severity model
 * is air-quality bands, not pollen levels.
 */
(() => {
  const CARD_VERSION = '0.1.0';

  // ── Severity palettes ────────────────────────────────────────────────
  // EEA European Air Quality Index palette — mirrors pollutant_registry.
  // EAQI_BANDS (the single source of truth server-side). Each raw sensor
  // already carries the resolved colour in bands.<authority>.colour, so the
  // card reads that where available and falls back to this table only for the
  // headline/legend or a missing attribute. Band names + colours are shared by
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
  // 3-step semantic ramp (green/amber/red, shared with the maintainer's
  // PollenWatch card) so CO never masquerades as a 6-band EAQI rating.
  const LEVEL_PALETTE = {
    0: { label: 'Good', colour: '#3DAE5A' },
    1: { label: 'Elevated', colour: '#F2A516' },
    2: { label: 'High', colour: '#E0492E' },
  };
  const UNKNOWN_COLOUR = '#AEB7C0';

  // ── Pollutant display identities ─────────────────────────────────────
  // Presentational only (subscripted formulae the WS pollutant_names map does
  // not carry). Names themselves come from the integration via WS / the sensor
  // friendly_name; this is the formula chip + ordering hint.
  const POLLUTANT_DISPLAY = {
    pm2_5: { name: 'PM2.5', formula: 'PM₂.₅' },
    pm10: { name: 'PM10', formula: 'PM₁₀' },
    nitrogen_dioxide: { name: 'Nitrogen dioxide', formula: 'NO₂' },
    ozone: { name: 'Ozone', formula: 'O₃' },
    sulphur_dioxide: { name: 'Sulphur dioxide', formula: 'SO₂' },
    carbon_monoxide: { name: 'Carbon monoxide', formula: 'CO' },
    european_aqi: { name: 'European AQI', formula: 'EAQI' },
  };
  // Stable display order; anything unknown sorts last alphabetically.
  const POLLUTANT_ORDER = [
    'pm2_5', 'pm10', 'nitrogen_dioxide', 'ozone',
    'sulphur_dioxide', 'carbon_monoxide', 'european_aqi',
  ];

  // The five concentration pollutants that define the EEA aggregate index.
  // The headline severity is the WORST of these revised-EEA sub-indexes — the
  // EAQI is, by definition, the worst sub-index. CO (different basis) and
  // european_aqi (itself an aggregate) are excluded from the headline so they
  // don't double-count, but they still render as their own rows.
  const EAQI_SUBINDEX_POLLUTANTS = new Set([
    'pm2_5', 'pm10', 'nitrogen_dioxide', 'ozone', 'sulphur_dioxide',
  ]);

  // Source resolution. Open-Meteo (CAMS) is the primary, covers every
  // pollutant, and always carries the band provenance, so it is the preferred
  // "headline reading" source; the citizen + official networks fill in / cross-
  // validate. The card reads the first available source in this order for the
  // glance reading, and shows all of them in the consensus breakdown.
  const SOURCE_PRIORITY = ['open_meteo', 'sensor_community', 'land_steiermark'];
  const SOURCE_LABELS = {
    open_meteo: 'Open-Meteo (CAMS)',
    sensor_community: 'Sensor.Community',
    land_steiermark: 'Land Steiermark',
  };

  // Authorities, in the order they read in the expanded provenance block.
  const AUTHORITY_LABELS = {
    eaqi_eea_2024: 'EEA index (2024 revised)',
    eaqi_classic: 'EEA index (classic / Open-Meteo)',
    who_2021: 'WHO 2021 guidelines',
    who_retained: 'WHO (retained short-averaging)',
    eu_2024_2881: 'EU Directive 2024/2881',
    eu_2008_50_ec: 'EU Directive 2008/50/EC',
  };

  const DOMAIN = 'airwatch';

  // ── helpers ──────────────────────────────────────────────────────────
  const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
  const isNum = (v) => v !== null && v !== undefined && v !== '' && !Number.isNaN(Number(v));

  // Prettify a registry band key ("very_poor" -> "Very poor").
  function bandLabel(key) {
    if (!key) return null;
    return cap(String(key).replace(/_/g, ' '));
  }

  // Black or white text for legibility on a band-colour chip (per-channel
  // luminance). Keeps the bright low bands readable and the dark high bands
  // inverted without a per-band lookup.
  function textOn(hex) {
    if (!hex || hex[0] !== '#' || hex.length < 7) return '#1c2530';
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    return lum > 0.6 ? '#1c2530' : '#ffffff';
  }

  // Round a reading for display without faking precision: integers stay
  // integers, sub-10 values keep one decimal.
  function fmtReading(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return '—';
    if (Math.abs(n) >= 10) return String(Math.round(n));
    return String(Math.round(n * 10) / 10);
  }

  // Pick the severity descriptor for one pollutant's headline reading. CO and
  // european_aqi are special-cased so we never invent a revised-EEA band for a
  // pollutant the EEA index doesn't define.
  //   returns { colour, label, band, basis, rank } | null
  // `rank` is the comparable magnitude for the headline (revised band index
  // 1–6, or CO/european level 0–2 lifted into the same axis only for display).
  function severityFor(pollutant, ent) {
    const bands = ent?.attributes?.bands || {};
    if (pollutant === 'carbon_monoxide') {
      const lvl = ent?.attributes?.level;
      if (lvl === null || lvl === undefined) return null;
      const p = LEVEL_PALETTE[lvl] || LEVEL_PALETTE[0];
      return { colour: p.colour, label: p.label, basis: 'WHO / EU', band: null, rank: lvl };
    }
    if (pollutant === 'european_aqi') {
      const c = bands.eaqi_classic;
      if (!c) return null;
      return {
        colour: c.colour || EAQI_PALETTE[c.band_index]?.colour || UNKNOWN_COLOUR,
        label: bandLabel(c.band) || EAQI_PALETTE[c.band_index]?.label,
        basis: 'classic index', band: c.band_index, rank: null,
      };
    }
    // The five concentration sub-indexes: the revised EEA band is the official
    // severity (the colour ramp the everyday surface shows).
    const r = bands.eaqi_eea_2024;
    if (!r) return null;
    return {
      colour: r.colour || EAQI_PALETTE[r.band_index]?.colour || UNKNOWN_COLOUR,
      label: bandLabel(r.band) || EAQI_PALETTE[r.band_index]?.label,
      basis: 'revised EEA', band: r.band_index, rank: r.band_index,
    };
  }

  // ── per-pollutant resolution against hass.states ─────────────────────
  // Builds the view-model row: the headline source + reading + severity, the
  // consensus overlay, and the divergence flag. Tolerant of every state the
  // data layer actually produces — a disabled source simply has no entity, a
  // stale/all-invalid source goes unavailable (the fail-safe), and a pollutant
  // with no readable source resolves to `unknown`.
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
      // No readable source for this pollutant: honest unknown (gray, no band).
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

  // Consensus overlay for a row: n/m badge + per-source mini-rows + the
  // mixed/agree verdict. Reads source_levels off the consensus sensor and the
  // matching raw sensors for the per-source values.
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

  // ── CSS ──────────────────────────────────────────────────────────────
  const CARD_CSS = `
    :host { display: block; }
    .card {
      background: var(--ha-card-background, var(--card-background-color, white));
      border: 1px solid var(--divider-color, #ECE4D6);
      border-radius: var(--ha-card-border-radius, 16px);
      padding: 16px;
      color: var(--primary-text-color, #2A3540);
      box-shadow: var(--ha-card-box-shadow, none);
    }
    .header { display: flex; align-items: baseline; gap: 10px; margin-bottom: 12px; }
    .title { font-weight: 600; font-size: 18px; letter-spacing: -0.015em; }
    .meta { margin-left: auto; display: flex; align-items: baseline; gap: 8px; }
    .badge {
      font-variant-numeric: tabular-nums; font-weight: 600; font-size: 13px;
      color: var(--primary-text-color, #2A3540);
      padding: 1px 6px; border-radius: 4px;
      background: var(--divider-color, #ECE4D6);
    }

    /* Headline — the dominant revised-EEA severity, big and colour-ramped. */
    .headline {
      display: flex; align-items: center; gap: 14px;
      border-radius: 12px; padding: 14px 16px; margin-bottom: 14px;
    }
    .headline .chip {
      flex-shrink: 0; min-width: 64px; text-align: center;
      font-weight: 700; font-size: 15px; letter-spacing: -0.01em;
      padding: 10px 12px; border-radius: 10px;
    }
    .headline .info { line-height: 1.3; }
    .headline .level { font-weight: 700; font-size: 22px; letter-spacing: -0.02em; }
    .headline .driver { color: var(--secondary-text-color, #7C8794); font-size: 12.5px; margin-top: 2px; }
    .headline.state-unknown { background: var(--secondary-background-color, rgba(0,0,0,0.04)); }
    .headline.state-unknown .chip { background: var(--divider-color, #ECE4D6); color: var(--secondary-text-color, #7C8794); }

    /* Pollutant rows */
    .rows { display: flex; flex-direction: column; gap: 2px; }
    .row {
      display: block; width: 100%; text-align: left;
      background: transparent; border: none; color: inherit; font: inherit;
      border-radius: 8px; padding: 0; cursor: pointer;
    }
    .row-head {
      display: grid;
      grid-template-columns: 14px minmax(64px, 1.2fr) auto auto 16px;
      align-items: center; gap: 10px;
      padding: 8px 8px; border-radius: 8px;
    }
    .row:hover .row-head, .row:focus-visible .row-head {
      background: var(--secondary-background-color, rgba(0,0,0,0.04));
      outline: none;
    }
    .swatch { width: 14px; height: 14px; border-radius: 4px; flex-shrink: 0; background: ${UNKNOWN_COLOUR}; }
    .p-name { font-weight: 600; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .p-name .formula { color: var(--secondary-text-color, #7C8794); font-weight: 500; margin-left: 6px; font-size: 12.5px; }
    .p-reading { font-variant-numeric: tabular-nums; font-size: 14px; white-space: nowrap; text-align: right; }
    .p-reading .unit { color: var(--secondary-text-color, #7C8794); font-size: 12px; margin-left: 3px; }
    .p-band {
      font-size: 12px; font-weight: 600; white-space: nowrap;
      padding: 2px 8px; border-radius: 999px; text-align: center;
    }
    .p-band.unknown { background: var(--divider-color, #ECE4D6); color: var(--secondary-text-color, #7C8794); }
    .diverge-flag { font-size: 11px; color: var(--warning-color, #C77700); margin-left: 6px; font-weight: 600; }
    .chev { color: var(--secondary-text-color, #7C8794); transition: transform 160ms; justify-self: end; font-size: 12px; }
    .row[aria-expanded="true"] .chev { transform: rotate(90deg); }

    /* Expanded provenance / consensus */
    .detail { display: none; padding: 4px 10px 12px 38px; }
    .row[aria-expanded="true"] + .detail { display: block; }
    .detail-block { margin-top: 10px; }
    .detail-block:first-child { margin-top: 2px; }
    .detail-h {
      font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase;
      color: var(--secondary-text-color, #7C8794); font-weight: 600; margin-bottom: 5px;
    }
    .src-row { display: flex; align-items: center; gap: 8px; font-size: 13px; padding: 2px 0; }
    .src-dot { width: 9px; height: 9px; border-radius: 999px; flex-shrink: 0; background: ${UNKNOWN_COLOUR}; }
    .src-label { font-weight: 500; }
    .src-value { margin-left: auto; font-variant-numeric: tabular-nums; color: var(--secondary-text-color, #7C8794); }
    .src-station { color: var(--secondary-text-color, #7C8794); font-size: 11px; font-style: italic; }
    .consensus-verdict { font-size: 12.5px; margin-top: 4px; }
    .consensus-verdict.mixed { color: var(--warning-color, #C77700); font-weight: 600; }
    .auth-row { font-size: 12.5px; padding: 3px 0; display: flex; gap: 8px; align-items: baseline; }
    .auth-name { color: var(--secondary-text-color, #7C8794); min-width: 92px; flex-shrink: 0; }
    .auth-body { line-height: 1.45; }
    .exceeds { color: var(--error-color, #D33A2C); font-weight: 600; }
    .within { color: var(--success-color, #2E8B57); font-weight: 600; }
    .it-targets { color: var(--secondary-text-color, #7C8794); font-size: 11.5px; }
    .basis-note {
      font-size: 12.5px; margin-bottom: 6px; padding: 6px 8px;
      background: var(--secondary-background-color, rgba(0,0,0,0.03));
      border-radius: 6px; line-height: 1.4;
    }
    .basis-note.differ { border-left: 3px solid var(--warning-color, #C77700); }

    .footer { margin-top: 12px; display: flex; align-items: center; }
    .toggle-all {
      background: transparent; border: none; color: var(--secondary-text-color, #7C8794);
      cursor: pointer; font: inherit; font-size: 11px; letter-spacing: 0.08em;
      text-transform: uppercase; padding: 4px 6px;
    }
    .toggle-all:hover { color: var(--primary-text-color, #2A3540); }
    .empty { padding: 18px; text-align: center; color: var(--secondary-text-color, #7C8794); font-size: 13px; }

    @media (prefers-reduced-motion: reduce) { .chev { transition: none !important; } }
  `;

  // ── Card element ─────────────────────────────────────────────────────
  class AirWatchCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._expanded = new Set();   // pollutant keys currently expanded
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
      return 2 + n;
    }

    static getStubConfig() {
      return { type: 'custom:airwatch-card' };
    }

    static getConfigElement() {
      return document.createElement('airwatch-card-editor');
    }

    // Pollutant list: explicit YAML > WS-discovered selection > hass.states
    // scan. Mirrors PollenWatch's layered species resolution.
    _resolvePollutantKeys() {
      let keys;
      if (this._config?._explicitPollutants) keys = this._config._explicitPollutants.slice();
      else if (this._discoveredPollutants) keys = this._discoveredPollutants.slice();
      else keys = this._scanPollutants();
      // Stable, human-sensible order.
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

    // One-shot WS discovery of the entry's selected_pollutants. Silent on
    // failure — the scan fallback covers older integrations / transient errors.
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
        } catch (_e) {
          // Endpoint absent / errored — fall back to scan. Deliberately silent.
        }
      })();
      return this._discoveryPromise;
    }

    _build() {
      this.shadowRoot.innerHTML = `
        <style>${CARD_CSS}</style>
        <ha-card class="card" data-card>
          <div class="header">
            <span class="title" data-title></span>
            <span class="meta"><span class="badge" data-badge></span></span>
          </div>
          <div class="headline" data-headline></div>
          <div class="rows" data-rows></div>
          <div class="footer">
            <button class="toggle-all" data-toggle-all aria-pressed="false"></button>
          </div>
        </ha-card>
      `;
      this.shadowRoot.querySelector('[data-title]').textContent = this._config.title;

      // Row expand/collapse via event delegation (rows are re-rendered on every
      // state push; delegating keeps a single stable listener).
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
      const headlineEl = this.shadowRoot.querySelector('[data-headline]');
      const badgeEl = this.shadowRoot.querySelector('[data-badge]');
      const toggleAll = this.shadowRoot.querySelector('[data-toggle-all]');

      if (keys.length === 0) {
        headlineEl.style.display = 'none';
        badgeEl.textContent = '';
        rowsEl.innerHTML = `<div class="empty">No AirWatch pollutants found yet.</div>`;
        toggleAll.style.display = 'none';
        return;
      }
      toggleAll.style.display = '';

      // First render with expand_default: open every row once.
      if (this._expandedDefault && !this._appliedDefault) {
        this._expanded = new Set(keys);
        this._appliedDefault = true;
      }

      const rows = keys.map((k) =>
        resolvePollutant(this._hass, k, this._config._sourceFilter));

      // Headline: worst revised-EEA sub-index across the 5 concentration
      // pollutants (the EAQI = worst sub-index by definition).
      this._renderHeadline(headlineEl, rows);

      // Card-level n/m badge: the best cross-validation available across rows.
      const counts = rows
        .map((r) => r.consensus?.attributes)
        .filter(Boolean)
        .map((a) => ({
          c: a.source_count ?? 0, m: a.max_possible_sources ?? 0,
        }));
      if (counts.length) {
        const c = Math.max(...counts.map((x) => x.c));
        const m = Math.max(...counts.map((x) => x.m));
        badgeEl.textContent = m > 0 ? `${c}/${m} sources` : '';
      } else {
        badgeEl.textContent = '';
      }

      rowsEl.innerHTML = rows.map((r) => this._renderRow(r)).join('');

      // Toggle-all label reflects the current aggregate state.
      const allOpen = keys.every((k) => this._expanded.has(k));
      toggleAll.textContent = allOpen ? 'Hide provenance' : 'Show provenance';
      toggleAll.setAttribute('aria-pressed', String(allOpen));
    }

    _renderHeadline(el, rows) {
      el.style.display = '';
      // Worst revised sub-index among the EAQI-defining pollutants.
      let worst = null;
      for (const r of rows) {
        if (!EAQI_SUBINDEX_POLLUTANTS.has(r.pollutant)) continue;
        const sev = r.severity;
        if (!sev || sev.band == null) continue;
        if (!worst || sev.band > worst.sev.band) worst = { r, sev };
      }
      if (!worst) {
        // No EAQI sub-index reading — fail-safe unknown headline (the data
        // layer's stale/all-invalid state surfaces here, not a fake green).
        el.className = 'headline state-unknown';
        el.innerHTML = `
          <span class="chip">—</span>
          <span class="info">
            <span class="level">Unknown</span>
            <span class="driver">No current air-quality index reading</span>
          </span>`;
        return;
      }
      const { r, sev } = worst;
      const fg = textOn(sev.colour);
      el.className = 'headline';
      el.innerHTML = `
        <span class="chip" style="background:${sev.colour};color:${fg}">${this._esc(sev.label)}</span>
        <span class="info">
          <span class="level">${this._esc(sev.label)}</span>
          <span class="driver">Worst sub-index: ${this._esc(r.formula)} · revised EEA index</span>
        </span>`;
    }

    _renderRow(r) {
      const expanded = this._expanded.has(r.pollutant);
      const sev = r.severity;
      const swatchColour = sev?.colour || UNKNOWN_COLOUR;

      let bandChip;
      if (r.state === 'unknown' || !sev) {
        bandChip = `<span class="p-band unknown">Unknown</span>`;
      } else {
        const fg = textOn(sev.colour);
        bandChip = `<span class="p-band" style="background:${sev.colour};color:${fg}">${this._esc(sev.label)}</span>`;
      }

      const reading = r.state === 'unknown'
        ? `<span class="p-reading">—</span>`
        : `<span class="p-reading">${this._esc(fmtReading(r.reading))}<span class="unit">${this._esc(r.unit)}</span></span>`;

      const diverged = r.divergence && r.divergence.state === 'on';
      const divergeFlag = diverged ? `<span class="diverge-flag">⚠ sources differ</span>` : '';

      return `
        <button class="row" data-pollutant="${this._esc(r.pollutant)}"
                aria-expanded="${expanded}"
                aria-label="${this._esc(r.name)} — ${this._esc(sev?.label || 'unknown')}">
          <span class="row-head">
            <span class="swatch" style="background:${swatchColour}"></span>
            <span class="p-name">${this._esc(r.name)}<span class="formula">${this._esc(r.formula)}</span>${divergeFlag}</span>
            ${reading}
            ${bandChip}
            <span class="chev">▸</span>
          </span>
        </button>
        <div class="detail">${expanded ? this._renderDetail(r) : ''}</div>
      `;
    }

    // The depth: consensus breakdown + multi-authority provenance. Only built
    // for an expanded row (keeps the DOM cheap when collapsed).
    _renderDetail(r) {
      const parts = [];

      // 1. Cross-source consensus (the project's whole point — opt-in).
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

      // 2. Index basis — surface the classic-vs-revised divergence explicitly.
      const basisNote = this._indexBasisNote(r);
      if (basisNote) parts.push(basisNote);

      // 3. Authority provenance — WHO / EU per averaging window.
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
      // WHO 2021 + retained, then EU in-force. Each entry is one averaging
      // window; `exceeds` is a real comparison done server-side.
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
      const unit = ' µg/m³';
      let line = `${this._esc(e.averaging)}: ${this._esc(String(e.value))}${unit} — ${verdict}`;
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
  // A light visual editor so the card configures from the UI; YAML config is
  // fully documented and works without it. Degrades cleanly if ha-form is not
  // available in the running frontend (the YAML editor still applies).
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

  // Register with HA's custom-card catalog so it shows in the card picker.
  window.customCards = window.customCards || [];
  if (!window.customCards.some((c) => c.type === 'airwatch-card')) {
    window.customCards.push({
      type: 'airwatch-card',
      name: 'AirWatch',
      description: 'Multi-source air quality — official EEA severity at a glance, '
        + 'multi-authority provenance (WHO / EU) and cross-source consensus on tap.',
      preview: false,
      documentationURL: 'https://github.com/TheDave94/airwatch',
    });
  }

  /* eslint-disable no-console */
  console.info(
    `%c airwatch-card %c v${CARD_VERSION} `,
    'background:#50ccaa;color:#10241f;font-weight:600;padding:2px 6px;border-radius:3px 0 0 3px;',
    'background:#2A3540;color:#EAF2F0;padding:2px 6px;border-radius:0 3px 3px 0;'
  );
})();
