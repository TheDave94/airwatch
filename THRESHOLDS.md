# AirWatch thresholds — cited evidence base

> **Purpose.** Trace every air-quality band/threshold AirWatch uses to its
> **primary source document**, with the exact value, averaging period, date, and
> URL — the PollenWatch "expose provenance, don't assert" standard applied to the
> pollutant registry. **This is Phase 1 + 2 (research + discrepancy report). No
> registry code is changed by this document.**
>
> **Research date:** 2026-06-19.

## Confidence legend

| Tag | Meaning |
|---|---|
| ✅ **VERIFIED** | Read directly from the cited primary/official source during this research (URL + date below). |
| 📥 **NEEDS-USER-FETCH** | The authoritative source could not be retrieved (403 / JS-only / PDF parse fail). Listed in §6 with the exact document + value needed. **No recalled number is substituted.** |
| ⚠️ **UNCERTAIN (candidate)** | A value obtained only from a search-engine summary or by indirect corroboration — **not** read from the primary. Listed so the user can confirm; must not be treated as verified. |

---

## 1. Source access status

| Source | What it authoritatively gives | URL | Status |
|---|---|---|---|
| Open-Meteo Air Quality API docs | The **classic EAQI** breakpoints AirWatch's `european_aqi` actually returns | https://open-meteo.com/en/docs/air-quality-api | ✅ fetched 2026-06-19 |
| EEA European Air Quality Index (live) | The **revised** (current official) EEA index bands | https://airindex.eea.europa.eu/AQI/index.html | ✅ fetched 2026-06-19 |
| European Commission — EU air quality standards | **2008/50/EC** limit & target values | https://environment.ec.europa.eu/topics/air/air-quality/eu-air-quality-standards_en | ✅ fetched 2026-06-19 |
| WHO 2021 Global AQG (full PDF, ISBN 978-92-4-003422-8) | WHO AQG levels **+ interim targets**, per averaging period | iris.who.int → user-supplied PDF `9789240034228-eng.pdf` (Table 0.1, p. xvii) | ✅ read 2026-06-19 (user-fetched; web 403) |
| Directive (EU) 2024/2881 (OJ L, 2024-11-20) | The **2024-revised** EU limit/target values (2026 + 2030 milestones) | eur-lex → user-supplied PDF `OJ_L_202402881_EN_TXT.pdf` (Annex I, pp. 30–32) | ✅ read 2026-06-19 (user-fetched; web blocked) |
| EEA ETC-HE Report 2024/17 (index revision methodology) | Methodology + side-by-side old/revised index bands | https://www.eionet.europa.eu/etcs/etc-he/products/etc-he-products/etc-he-reports/etc-he-report-2024-17-eeas-revision-of-the-european-air-quality-index-bands/ | 📥 **PDF fetch timed out** (live values captured from airindex instead) |

---

## 2. European Air Quality Index (EAQI)

**Critical finding:** there are **two different EEA indexes in circulation**, and they
diverge. AirWatch's primary source (Open-Meteo/CAMS) returns the **classic** set;
the **official EEA index was revised** (WHO-aligned) and now publishes different
bands. The registry uses the classic set (correct for matching `european_aqi`),
but its "EEA 2023 revision" note understates how different the revised bands are.

### 2a. Classic EAQI — what Open-Meteo/CAMS returns — ✅ VERIFIED

Source: Open-Meteo Air Quality API docs (fetched 2026-06-19). Bands: Good / Fair /
Moderate / Poor / Very poor / Extremely poor.

| Pollutant | Averaging | Good | Fair | Moderate | Poor | Very poor | Extremely poor |
|---|---|---|---|---|---|---|---|
| PM2.5 | 24-h rolling | 0–10 | 10–20 | 20–25 | 25–50 | 50–75 | 75–800 |
| PM10 | 24-h rolling | 0–20 | 20–40 | 40–50 | 50–100 | 100–150 | 150–1200 |
| NO₂ | 1-h | 0–40 | 40–90 | 90–120 | 120–230 | 230–340 | 340–1000 |
| O₃ | 1-h | 0–50 | 50–100 | 100–130 | 130–240 | 240–380 | 380–800 |
| SO₂ | 1-h | 0–100 | 100–200 | 200–350 | 350–500 | 500–750 | 750–1250 |

→ Upper bounds (bands 1–5): PM2.5 `(10,20,25,50,75)`, PM10 `(20,40,50,100,150)`,
NO₂ `(40,90,120,230,340)`, O₃ `(50,100,130,240,380)`, SO₂ `(100,200,350,500,750)`.
CO is **not** part of the EAQI. Overall index = the worst single-pollutant band in the hour.

### 2b. Revised EEA index — official, now live — ✅ VERIFIED

Source: airindex.eea.europa.eu (fetched 2026-06-19). All pollutants hourly; the
Good/Fair cut-points are aligned to WHO 2021. **These are the bands the registry
does *not* yet encode.**

| Pollutant | Good | Fair | Moderate | Poor | Very poor | Extremely poor |
|---|---|---|---|---|---|---|
| PM2.5 | 0–5 | 6–15 | 16–50 | 51–90 | 91–140 | >140 |
| PM10 | 0–15 | 16–45 | 46–120 | 121–195 | 196–270 | >270 |
| NO₂ | 0–10 | 11–25 | 26–60 | 61–100 | 101–150 | >150 |
| O₃ | 0–60 | 61–100 | 101–120 | 121–160 | 161–180 | >180 |
| SO₂ | 0–20 | 21–40 | 41–125 | 126–190 | 191–275 | >275 |

> Note the revised PM2.5 Good ≤5 (= WHO annual AQG) and Fair ≤15 (= WHO 24-h AQG);
> PM10 ≤15/≤45, NO₂ ≤10/≤25, O₃ ≤60/≤100 likewise mirror WHO. This is *indirect
> corroboration* of the WHO values in §3, but is not a substitute for reading the
> WHO table itself.

---

## 3. WHO 2021 Global Air Quality Guidelines

✅ **VERIFIED** — read directly from the WHO 2021 guidelines PDF
(`9789240034228-eng.pdf`, **Table 0.1**, p. xvii), user-supplied 2026-06-19.

### 3a. AQG levels + interim targets — ✅ VERIFIED (Table 0.1, verbatim)

| Pollutant | Averaging | IT-1 | IT-2 | IT-3 | IT-4 | **AQG** |
|---|---|---|---|---|---|---|
| PM2.5 (µg/m³) | annual | 35 | 25 | 15 | 10 | **5** |
| PM2.5 (µg/m³) | 24-hᵃ | 75 | 50 | 37.5 | 25 | **15** |
| PM10 (µg/m³) | annual | 70 | 50 | 30 | 20 | **15** |
| PM10 (µg/m³) | 24-hᵃ | 150 | 100 | 75 | 50 | **45** |
| O₃ (µg/m³) | peak seasonᵇ | 100 | 70 | – | – | **60** |
| O₃ (µg/m³) | 8-hᵃ | 160 | 120 | – | – | **100** |
| NO₂ (µg/m³) | annual | 40 | 30 | 20 | – | **10** |
| NO₂ (µg/m³) | 24-hᵃ | 120 | 50 | – | – | **25** |
| SO₂ (µg/m³) | 24-hᵃ | 125 | 50 | – | – | **40** |
| CO (mg/m³) | 24-hᵃ | 7 | – | – | – | **4** |

ᵃ 99th percentile (i.e. 3–4 exceedance days per year).
ᵇ Average of daily maximum 8-hour mean O₃ in the six consecutive months with the
highest six-month running-average O₃ concentration.

### 3b. Short-averaging WHO guidelines that REMAIN VALID — ✅ VERIFIED (Table 0.2)

Carried forward from the 2000/2005 editions; **not** re-evaluated in 2021 but still
in force. These matter for AirWatch because they are the **only sub-24-hour WHO
values**, i.e. the ones most comparable to an hourly reading.

| Pollutant | Averaging | WHO guideline |
|---|---|---|
| NO₂ (µg/m³) | 1-hour | 200 |
| SO₂ (µg/m³) | 10-minute | 500 |
| CO (mg/m³) | 8-hour | 10 |
| CO (mg/m³) | 1-hour | 35 |
| CO (mg/m³) | 15-minute | 100 |

> **Averaging-window caveat (surface, don't smooth):** the 2021 AQG are
> annual / 24-h / 8-h / peak-season means; AirWatch readings are **hourly**.
> Comparing an hourly value to a 24-h or annual guideline is an *approximation* —
> carry it as provenance (the `averaging` field), never assert a clean exceedance.
> Per-pollutant the headline differs by window: NO₂ annual **10** vs 24-h **25** vs
> 1-h **200**; PM2.5 annual **5** vs 24-h **15**. The 1-hour NO₂ (200) and CO 1-h/
> 8-h values (Table 0.2) are the genuinely hour-comparable WHO numbers.

---

## 4. EU ambient air quality standards

### 4a. Directive 2008/50/EC (currently in force) — ✅ VERIFIED

Source: European Commission air quality standards page (fetched 2026-06-19);
underlying primary = Directive 2008/50/EC Annexes XI–XIV, VII (EUR-Lex CELEX 32008L0050).

| Pollutant | Value | Averaging | Permitted exceedances |
|---|---|---|---|
| PM2.5 | 25 µg/m³ | calendar year | — (limit value, from 2015) |
| PM2.5 | 20 µg/m³ | calendar year | — (Stage-2 indicative, 2020) |
| PM10 | 50 µg/m³ | 24-h | 35 days/year |
| PM10 | 40 µg/m³ | calendar year | — |
| NO₂ | 200 µg/m³ | 1-h | 18 hours/year |
| NO₂ | 40 µg/m³ | calendar year | — |
| SO₂ | 350 µg/m³ | 1-h | 24 hours/year |
| SO₂ | 125 µg/m³ | 24-h | 3 days/year |
| O₃ | 120 µg/m³ | max daily 8-h mean | 25 days/year (3-yr avg) — target value |
| CO | 10 mg/m³ | max daily 8-h mean | — |

### 4b. Directive (EU) 2024/2881 — ✅ VERIFIED (Annex I, pp. 30–32)

Adopted 2024-10-23, OJ L 2024-11-20. **Repeals & replaces 2008/50/EC.** Annex I
sets **two milestones**: Table 2 (attain by **11 Dec 2026** — essentially the old
2008 values restated) and Table 1 (attain by **1 Jan 2030** — tightened toward WHO).
Read directly from the user-supplied OJ PDF.

**Table 1 — limit values to attain by 1 January 2030 (the new, tightened set):**

| Pollutant | Value | Averaging | Permitted exceedances |
|---|---|---|---|
| PM2.5 | 25 µg/m³ | 1 day | ≤18/year |
| PM2.5 | 10 µg/m³ | calendar year | — |
| PM10 | 45 µg/m³ | 1 day | ≤18/year |
| PM10 | 20 µg/m³ | calendar year | — |
| NO₂ | 200 µg/m³ | 1 hour | ≤3/year |
| NO₂ | 50 µg/m³ | 1 day | ≤18/year |
| NO₂ | 20 µg/m³ | calendar year | — |
| SO₂ | 350 µg/m³ | 1 hour | ≤3/year |
| SO₂ | 50 µg/m³ | 1 day | ≤18/year |
| SO₂ | 20 µg/m³ | calendar year | — |
| CO | 10 mg/m³ | max daily 8-hour mean | — |
| CO | 4 mg/m³ | 1 day | ≤18/year |

**Table 2 — limit values to attain by 11 December 2026 (interim ≈ old 2008 values):**

| Pollutant | Value | Averaging | Permitted exceedances |
|---|---|---|---|
| PM2.5 | 25 µg/m³ | calendar year | — |
| PM10 | 50 µg/m³ | 1 day | ≤35/year |
| PM10 | 40 µg/m³ | calendar year | — |
| NO₂ | 200 µg/m³ | 1 hour | ≤18/year |
| NO₂ | 40 µg/m³ | calendar year | — |
| SO₂ | 350 µg/m³ | 1 hour | ≤24/year |
| SO₂ | 125 µg/m³ | 1 day | ≤3/year |
| CO | 10 mg/m³ | max daily 8-hour mean | — |

**Ozone (Annex I, Section 2):**

| Objective | Value | Averaging | Note |
|---|---|---|---|
| Target value (human health) | 120 µg/m³ | max daily 8-hour mean | ≤18 days/yr (3-yr avg); until 2030, ≤25 days/yr (3-yr avg) |
| Long-term objective (by 2050) | 100 µg/m³ | max daily 8-hour mean | ≤3 days/yr (99th pct) |

> **Key 2024 changes vs 2008/50/EC:** new **daily** limits for PM2.5 (25), NO₂ (50),
> CO (4 mg/m³); much stricter annual values by 2030 (PM2.5 25→10, PM10 40→20,
> NO₂ 40→20); SO₂ gains an annual cap (20) and a daily limit (50); NO₂ 1-hour
> exceedance allowance drops 18→3. The O₃ target value (120) is unchanged in level
> but its exceedance allowance tightens (25→18 days) from 2030.
> (SO₂/NOx vegetation critical levels — Annex I §3 — noted but out of human-health scope.)

---

## 5. Phase 2 — discrepancy report vs the current `pollutant_registry`

Diffing the **VERIFIED** values against what `sources/pollutant_registry.py` codes
today. (WHO and EU-2024 rows are gated on the NEEDS-USER-FETCH confirmations.)

### 5a. EAQI bounds — ✅ no errors

`_EAQI_BOUNDS` and `_EAQI_AVERAGING` **exactly match** the VERIFIED classic
Open-Meteo set (§2a), including PM = 24-h, gases = 1-h. **No numeric discrepancy.**

- **Gap, not error:** the registry's `EEA_2023` authority is a *label only* — it
  does not encode the revised bands (§2b), which are now the live official EEA index
  and differ substantially (e.g. PM2.5 Good 0–5 vs classic 0–10; O₃ moderate cut
  120 vs 130; SO₂ moderate cut 125 vs 350). If AirWatch wants to surface the
  revised index as a real alternate, the numbers in §2b must be added.
- **Dating nuance:** the registry calls the revision "2023"; the methodology report
  is **2024** (ETC-HE 2024/17) and the revised bands are live now.

### 5b. EU 2008/50/EC — ✅ chosen values correct; secondary values omitted

Every value the registry codes matches the VERIFIED 2008/50/EC table:

| Pollutant | Registry `_EU_LIMITS` | VERIFIED 2008/50/EC | Verdict |
|---|---|---|---|
| PM2.5 | 25, annual | 25, calendar year (2015) | ✅ correct; omits Stage-2 20 (2020) |
| PM10 | 50, 24-h, ≤35 days | 50, 24-h, 35 days/yr | ✅ correct; omits annual 40 |
| NO₂ | 200, 1-h, ≤18 h | 200, 1-h, 18 h/yr | ✅ correct; omits annual 40 |
| O₃ | 120, 8-h target | 120, max daily 8-h, 25 days/yr | ✅ correct; omits the exceedance allowance text |
| SO₂ | 350, 1-h, ≤24 h | 350, 1-h, 24 h/yr | ✅ correct; omits 24-h 125 (≤3 days) |
| CO | 10000, 8-h | 10 mg/m³, max daily 8-h | ✅ correct |

→ **No factual error in the EU 2008 values.** The model carries one representative
threshold per pollutant; the WHO/EU "expose all of them" upgrade would add the
omitted annual/secondary limits.

### 5c. EU 2024/2881 — registry materially out of date (evidence ✅ VERIFIED)

The registry's `_EU_LIMITS` codes the **superseded 2008/50/EC** values and notes the
2024 revision only as free text on **PM2.5**. With Annex I now VERIFIED (§4b):

- **2008/50/EC is repealed** — the registry cites a directive no longer in force.
  Current law is 2024/2881 with **2026** (≈ old values) and **2030** (tightened) milestones.
- Unencoded 2024 changes: PM10 annual 40→**20**, NO₂ annual 40→**20**, PM2.5 annual 25→**10**;
  **new daily limits** PM2.5 **25**, NO₂ **50**, CO **4 mg/m³**; SO₂ new annual **20**;
  NO₂ 1-h exceedance allowance 18→**3**.
- The registry's PM2.5 note ("tightens to 10 µg/m³ annual by 2030") is ✅ correct but
  is the *only* 2024 value represented. This is the largest **legal-currency** gap.

### 5d. WHO 2021 — ✅ VERIFIED: values correct-for-window, but model omits most of the table

The registry stores **one** WHO value + window per pollutant. Against the now-VERIFIED
WHO Table 0.1 / 0.2 (§3):

| Pollutant | Registry `_WHO_2021` | VERIFIED match | Omitted (now confirmed to exist) |
|---|---|---|---|
| PM2.5 | 15, 24-h | ✅ = 24-h AQG 15 | annual AQG **5**; IT 35/25/15/10 (annual), 75/50/37.5/25 (24-h) |
| PM10 | 45, 24-h | ✅ = 24-h AQG 45 | annual AQG **15**; IT 70/50/30/20 (annual), 150/100/75/50 (24-h) |
| NO₂ | 25, 24-h | ✅ = 24-h AQG 25 | annual AQG **10**; **1-h 200** (Table 0.2); IT 120/50 (24-h), 40/30/20 (annual) |
| O₃ | 100, 8-h | ✅ = 8-h AQG 100 | peak-season AQG **60**; IT 160/120 (8-h), 100/70 (peak) |
| SO₂ | 40, 24-h | ✅ = 24-h AQG 40 | IT 125/50 (24-h); 10-min 500 (Table 0.2) |
| CO | 4000, 24-h | ✅ = 24-h AQG 4 mg/m³ | **8-h 10**, 1-h 35, 15-min 100 mg/m³ (Table 0.2) |

→ The registry's WHO numbers are **all correct** for the window it picked, but it
silently selects the 24-h/8-h value and **omits the stricter annual guidelines and
every interim target**. Most consequential: **NO₂ annual 10** (registry shows 25)
and the **NO₂ 1-hour 200** / **CO 1-h 35 / 8-h 10** — the genuinely hour-comparable
WHO values, which are exactly what an hourly reading should be checked against.

### 5e. CO level bucketing — ✅ now fully grounded

`_CO_LEVEL_BOUNDS = (4000, 10000)` uses WHO 24-h (4 mg/m³, VERIFIED §3a) and the EU
8-h limit (10 mg/m³, VERIFIED §4) as the 0/1/2 cut-points — both endpoints confirmed.
Note WHO also carries CO **1-h 35** / **8-h 10** mg/m³ (Table 0.2), which are more
hour-appropriate onset candidates than the 24-h 4 mg/m³ if the rewrite wants them.

---

## 6. NEEDS-USER-FETCH list — ✅ RESOLVED

Both blocked documents were supplied by the user (2026-06-19) as local PDFs and read
directly with `pdftotext -layout`:

1. ✅ **WHO 2021 Global AQG** — `9789240034228-eng.pdf` (Table 0.1 p. xvii, Table 0.2). Folded into §3.
2. ✅ **Directive (EU) 2024/2881** — `OJ_L_202402881_EN_TXT.pdf` (Annex I pp. 30–32). Folded into §4b.

*(Optional, still open — low priority)* **EEA ETC-HE Report 2024/17** (index-revision
methodology PDF, fetch timed out). Not blocking: the revised **values** are VERIFIED
from airindex (§2b); only the methodology/rationale narrative is missing.

---

## 7. Health-endpoint references — ✅ VERIFIED (WHO 2021 commissioned systematic reviews)

Read from the WHO 2021 document's own reference list (not recalled). Each AQG rests on
a meta-analysis published in the *Environment International* WHO AQG special issue
(Whaley et al., 2021):

- **PM2.5 / PM10 — long-term mortality:** Chen J, Hoek G (2020). *Long-term exposure to
  PM and all-cause and cause-specific mortality: a systematic review and meta-analysis.*
  Environ Int 143:105974. doi:10.1016/j.envint.2020.105974
- **NO₂ / O₃ — long-term mortality:** Huangfu P, Atkinson R (2020). *Long-term exposure
  to NO₂ and O₃ and all-cause and respiratory mortality…* Environ Int 144:105998.
  doi:10.1016/j.envint.2020.105998
- **PM10 / PM2.5 / NO₂ / O₃ — short-term mortality:** Orellano P, Reynoso J, Quaranta N,
  Bardach A, Ciapponi A (2020). *Short-term exposure to PM, NO₂ and O₃ and all-cause and
  cause-specific mortality…* Environ Int 142:105876. doi:10.1016/j.envint.2020.105876
- **SO₂ — short-term mortality:** Orellano P, Reynoso J, Quaranta N (2021). *Short-term
  exposure to sulphur dioxide (SO₂) and all-cause and respiratory mortality…* Environ Int
  150:106434. doi:10.1016/j.envint.2021.106434
- **CO — short-term, myocardial infarction:** Lee KK, Spath N, Miller MR, Mills NL, Shah
  ASV (2020). *Short-term exposure to carbon monoxide and myocardial infarction…* Environ
  Int 143:105901. doi:10.1016/j.envint.2020.105901
- **Overview / methodology:** Whaley P, Nieuwenhuijsen M, Burns J, eds. (2021). *Update of
  the WHO global air quality guidelines: systematic reviews.* Environ Int (special issue).

---

## Summary for review

Every threshold **value** is now ✅ **VERIFIED from a primary source** — no ⚠️/📥
tags remain on any number. (One *optional* item is still unfetched: the EEA ETC-HE
2024/17 methodology PDF in §1 — it blocks nothing, since the revised index values are
already verified from airindex.)

- **Registry is factually correct where it has numbers:** classic EAQI bounds match
  Open-Meteo's docs exactly; EU values match the 2008/50/EC text; WHO values match
  the WHO Table 0.1 for the window each one picked.
- **The gaps are omission + currency, not errors:**
  1. **WHO** — only one window/pollutant stored; the **annual AQG**, **all interim
     targets**, and the **hour-comparable values** (NO₂ 1-h 200; CO 1-h 35 / 8-h 10)
     are missing. Most consequential single number: **NO₂ annual 10** (registry shows 25).
  2. **EU** — registry cites the **repealed** 2008/50/EC. Current law is **2024/2881**
     with 2026 (≈ old) and 2030 (tightened) milestones; only PM2.5's 2030 note is present.
  3. **EEA** — registry encodes the classic index (correct for `european_aqi`) but only
     *labels* the revised official index; the revised bands (§2b) are not encoded.
- **Health-endpoint citations** for a PollenWatch-grade evidence basis are now in hand (§7).

**No registry code changed.** Ready for your review of this evidence base, then Phase 3
(rewrite the registry to carry the full provenance-tagged set).
