# Fixtures — API Payload Manifest

Raw FortyGuard responses captured 2026-08-23. These are the **cache seed** and the
**regression fixtures**. Everything in `FORTYGUARD_API_CONTRACT.md` was established
from these files.

Do not regenerate them casually — they cost credits, and the contract's claims are
checked against these exact payloads.

All calls used the same downtown Phoenix parcel unless noted:

```
[-112.0790, 33.4450] [-112.0690, 33.4450] [-112.0690, 33.4550] [-112.0790, 33.4550]
```
≈1.0 km², 81 cells at 100 m granularity.

Metro AOI where noted:
```
[-112.20, 33.40] [-111.95, 33.40] [-111.95, 33.55] [-112.20, 33.55]
```
≈384 km², 38 569 cells at 100 m.

---

## `heatmap/` — `POST /v1/heatmap`

### Snapshot (`analytic_type="tcm"`)

| File | Call | Proves |
| --- | --- | --- |
| `phoenix_heatmap_raw.json` | `filter_type=1`, 2024-07-15 14:00 | The `tcm` response schema. Cell properties are `average/min/max_temperature`. Mean 39.71 °C, spatial spread 0.089 °C — **parcel-scale snapshot temperature is effectively flat.** |
| `phoenix_heatmap_historical_raw.json` | `filter_type=1`, 2024-07-01 14:00 | Historical retrieval returns genuinely different data (mean 39.53, spread 0.476), not a cached repeat. Geometry identical to the above; values are not. |
| `phoenix_heatmap_recent_raw.json` | `filter_type=1`, 2026-08-09 14:00 | Recent dates resolve. Mean 41.20 °C. Confirms the demo window is retrievable. |

### Single day (`filter_type=3`) — **the reconstruction fixtures**

| File | Date | Diurnal range | Role |
| --- | --- | --- | --- |
| `phoenix_singleday_filter3_raw.json` | 2024-07-15 | 10.87 °C | First proof that `filter_type=3` returns ONE grid carrying per-cell temporal min/max, not 24 hourly grids |
| `filter3_properties_2024-07-15.json` | 2024-07-15 | **11.38 °C** | **CONTROL.** Any future re-verification compares against this. |
| `filter3_properties_2026-08-09.json` | 2026-08-09 | 8.22 °C | 2026 dates carry diurnal range |
| `filter3_properties_2026-08-05.json` | 2026-08-05 | 5.81 °C | ” |
| `filter3_properties_2026-07-26.json` | 2026-07-26 | 6.66 °C | ” — first day of the demo backfill window |
| `temporal_range_verdict.json` | — | — | Summary of the four above. **PASS** — the one-call-per-site-day strategy is confirmed. |

> **Known bias, recorded here because it affects M1.** Recent dates are smoother than
> the archive: diurnal range ~40% narrower, parcel-scale spatial spread ~10× smaller
> (0.04 °C vs 0.36 °C). Real Phoenix August swings 12–14 °C, so both are compressed
> and 2026 more so. This under-estimates peak WBGT → stimulus → adaptation rate. The
> bias is conservative (under-clears rather than over-clears) but it is a bias.
> M1 must compare FortyGuard's amplitude against Open-Meteo's for the same site-day.

### Analysis heatmaps (`analytic_type="exceedance"`)

| File | Call | Proves |
| --- | --- | --- |
| `phoenix_threshold_sweep_summary.json` | Metro AOI, 2024-07-01→07, thresholds 34/36/38/40/42 °C | **Threshold selection.** 30 °C and 34 °C are saturated (92–99% of window); 42 °C is at the floor (2.9%). **40 °C is optimal** — mean 31% of window, best relative spread (0.50). Also captures the `min = -0.3176` at 42 °C that proves the field is interpolated, not counted. |
| `phoenix_40c_exceedance_sites.json` | Metro AOI, 2026-07-26→08-08, threshold 40 °C | **Core evidence, and the source of the project's most-corrected number.** Mean 95.6 h of 336. Raw hottest cell 7.63 h/day above 40 °C against coolest 4.14 — a ~~1.84×~~ ratio that is a **boundary artifact**: the top/bottom 5 cells all sit within 460 m of the west edge or 80 m of the north edge. After buffering and the 500 m edge discard the defensible figure is **1.28×** (see the site selection entry below). **Quote 1.28×, never 1.84×.** |
| `phoenix_5day_daily_stats.json` | Parcel, 2026-08-05→09, `filter_type=3` × 5 | Day-to-day variation in daily mean: 36.65 → 37.09 → 37.40 → 37.69 → 38.85 (**2.2 °C over five days**). This is the temporal signal the stimulus term feeds on. **NOTE:** this file contains only `stats_data`, which is the SPATIAL axis — the temporal ranges are in the `filter3_properties_*` files above. |

**Not captured:** the raw 38 569-cell exceedance grid (34 MB). Too large for the repo.
Re-fetch on demand; the derived statistics above are what the code needs.

---

## `openmeteo/` — `GET archive-api.open-meteo.com/v1/archive`

Fetched 2026-08-24 by `scripts/fetch_openmeteo.py --refresh`. Free, no key required.

| File | Call | Proves |
| --- | --- | --- |
| `33.4484_-112.0740_2024-07-15.json` | Point 33.4484/-112.0740, `hourly=temperature_2m,relative_humidity_2m,wet_bulb_temperature_2m,shortwave_radiation,wind_speed_10m,cloud_cover`, `timezone=auto`, `wind_speed_unit=ms` | The two things no FortyGuard endpoint returns: **hourly wind** and **hourly shortwave**. Also the independent temperature series the amplitude comparison needs. Timezone resolves to America/Phoenix (UTC−7), elevation 333 m — matching `env_params` exactly. |
| `33.4484_-112.0740_2026-07-26.json` | same fields, 2026-07-26 | M2 site-day. Hottest of the four by measured dose (37.62 °C·h above RAL over the 05:00–13:00 shift). |
| `33.4484_-112.0740_2026-08-05.json` | same fields, 2026-08-05 | M2 site-day. |
| `33.4484_-112.0740_2026-08-09.json` | same fields, 2026-08-09 | M2 site-day. Highest WBGT peak (33.01 °C). |

**Why wet bulb and relative humidity are fetched here [2026-08-24].** `env_params`
was only ever called for **one** site-day, so the other three have no FortyGuard wet
bulb at all. Open-Meteo supplies it instead. That substitution is justified rather
than convenient: the provenance audit showed FortyGuard's `wet_bulb_temperature_celsius`
agrees with Open-Meteo's `wet_bulb_temperature_2m` on 15 of 24 hours with a worst
difference of 0.1 °C, and the two are not independent sources anyway. See
`FORTYGUARD_API_CONTRACT.md` §6. It costs nothing, needs no key, and covers dates
FortyGuard was never asked about.

**UNITS TRAP: Open-Meteo defaults wind to km/h.** Request `wind_speed_unit=ms`
explicitly and assert `hourly_units` on the way in — 4.32 km/h read as 4.32 m/s would
over-ventilate the modelled globe and under-read WBGT. `fetch_openmeteo.py` refuses to
write the fixture if the reported units are not the expected ones.

**What it gave us:**

- **Wind** 0.81–7.19 m/s at 10 m → 0.53–4.68 m/s at 2 m after the log-profile
  conversion, mean **2.81 m/s**. The assumed constant had been 3.0 m/s, so the
  assumption was sound: swapping it for the measured series moves WBGT at 14:00 by
  0.07 °C.
- **Shortwave** peaks at 933 W/m². The offline anchored clear-sky model peaked at
  947 W/m² — within 14 W/m², which validates the anchoring strategy independently.
- **Amplitude comparison, now answered.** FortyGuard cell 11.133 °C vs Open-Meteo
  11.800 °C: discrepancy **−0.667 °C, ratio 0.944**. FortyGuard reads ~94% of the
  independent amplitude on this 2024 archive day — mild, and far milder than the ~40%
  narrowing recorded above for 2026 dates. The bias is conservative (under-reads peak
  WBGT → under-reads stimulus) but it is worse on the demo window than here.
- **Cloud** is byte-identical to FortyGuard's `cloud_cover_octas`. See
  `FORTYGUARD_API_CONTRACT.md` §6, trap 4 — the two are not independent sources.

**Effect on M1:** the exit-test worst error drops from 0.42 °C (all offline
assumptions) to **0.09 °C** with Open-Meteo supplying shape, solar, cloud and wind.
The overnight humidity artifact in the reconstructed dry bulb drops from 3 hours /
4.54 °C of false warming to 1 hour / 1.36 °C.

To extend coverage to the demo backfill window, re-run `fetch_openmeteo.py` per
site-day. Days with no Open-Meteo fixture still run — on tagged assumptions.

---

## The 14-day two-site backfill [2026-08-24]

28 `filter_type=3` parcel calls (14 days x 2 sites), 1 km-square AOIs centred on the
p5 and p95 sites. **Not committed as fixtures** — they live in the gitignored disk
cache, keyed on the request payload. Rebuild with:

```
python scripts/m3_fetch.py --backfill
```

Timing measured: **~4.7 min per call**, so the batch is a two-hour job. Open-Meteo
for both sites over the same window is 2 free range calls (`scripts/fetch_openmeteo.py`),
committed under `openmeteo/`.

**What the backfill settled**, all at the unchanged 6.0 °C·h normalisation, measured
on the personal limit in °C-WBGT across all 84 τ pairs:

| lever | psychrometric | ISO Annex D | gap |
| --- | --- | --- | --- |
| **shift assignment** 05–13 vs 10–18 | **84/84** | **84/84** | +1.07 °C at day 4, +2.75 by day 14 |
| **mild vs hot by worked dose** | **84/84** | **84/84** | +0.63 °C |
| mild vs hot by peak temperature | 36/84 | 54/84 | +0.27 °C |
| **site assignment** p5 vs p95 | **0/84** | **0/84** | +0.23 °C |

Three findings worth carrying into the writeup:

1. **Disjoint histories fixed mild-vs-hot.** M2 got 0/84 with four overlapping cached
   days; fourteen disjoint ones give 84/84 under both wet-bulb methods.
2. **The exceedance ratio does not survive duty-cycle weighting.** 1.284× of
   exceedance *hours* becomes **1.118×** of *worked dose*, because the extra hot hours
   at the p95 site are exactly the hours the work/rest rule prescribes at or near
   zero. Site assignment is the weakest of the three levers, not the strongest.
3. **Peak WBGT barely predicts adaptive dose** — correlation **+0.13** across the 14
   days. Ranking days by temperature and by dose gives almost unrelated orderings.

---

## `env_params/` — `POST /v1/env_params`

| File | Call | Proves |
| --- | --- | --- |
| `phoenix_env_params_raw.json` | Point 33.4484/-112.0740, 2024-07-15, `filter_type=3`, `analysis=[wet_bulb, solar_irradiance, relative_humidity]` | Response schema. **24 hourly values** for every parameter EXCEPT `solar_irradiance`, which is a single daily clear-sky mean (`ghi/dni/dhi`). Wet bulb 22.0–23.8 °C, RH 19–49% across the day. Also demonstrates the `heat_index_celsius` artifact — it peaks at 52.9 °C at 06:00 and bottoms at 38.4 °C mid-afternoon, because the endpoint holds the input `temperature` anchor fixed and varies only humidity. **Do not use `heat_index_celsius`.** |

**M1 regression target, derived from this file:**
downtown Phoenix 2024-07-15 → WBGT ≈ **31 °C at 14:00**, ≈ **24.8 °C at 06:00**.
The day crosses both the NIOSH RAL and REL curves for moderate work.

**M1 result [2026-08-24]:** the pipeline reproduces this. With FortyGuard fixtures
alone: **31.12 °C at 14:00** (+0.12) and **25.22 °C at 06:00** (+0.42). With the
Open-Meteo fixture supplying shape, solar, cloud and wind: **30.97 °C** (−0.03) and
**24.71 °C** (−0.09), the day spanning 23.18 → 31.16 °C-WBGT and crossing both curves.
`python scripts/m1_report.py` prints the evidence; `tests/test_m1_exit.py` is the gate.

Independent cross-check: the reconstructed 14:00 dry bulb lands **0.07 °C** from the
`filter_type=1` snapshot in `phoenix_heatmap_raw.json` — a separate call reading a
different axis.

Two further facts were established from this payload while building M1, and both are
now in `FORTYGUARD_API_CONTRACT.md` §6: `cloud_cover_octas` returns **percent**, not
octas, and `solar_irradiance.clear_sky` is a **daylight-hours** mean rather than a
24-hour one. A third is unresolved — the file carries 15 parameters although the call
is recorded above as requesting 3, so it is unknown whether `analysis` is applied at
all. M1 depends on `apparent_temperature_celsius` and `cloud_cover_octas` being
present, so confirm before the M3 backfill.

---

## `site_selection/` — derived from a live exceedance grid [2026-08-24]

| File | What it is |
| --- | --- |
| `phoenix_40c_selection.json` | The M3 site choice, with everything needed to defend it: buffered AOI, cell counts before/after edge discard, raw vs percentile ratios, and both selected centroids with their distance to the AOI edge. |

Produced by `scripts/m3_fetch.py --exceedance` from activity
`066b2c19-a3dd-4db2-95ba-ba8b2c150260` — a `filter_type=4` exceedance run over the
metro AOI **buffered by 1 km**, 2026-07-26 → 2026-08-08, threshold 40 °C.
**46 931 cells, 15.3 MB.** The raw grid is NOT committed (`data/` is gitignored);
re-fetch on demand, the derived record is what the code needs.

**The finding that corrects the project's headline number.** Raw min/max across the
grid is 55.27 / 106.89 h → **1.93×**. After the mandated mitigation — 1 km buffer,
500 m edge discard (4 201 cells, 9.0%), 5th/95th percentile ranking — it is
79.61 / 102.21 h → **1.28×**. The 1.84× once quoted in SPEC.md is a raw min/max figure,
i.e. exactly the boundary-artifact statistic `FORTYGUARD_API_CONTRACT.md` §5 warns
against. **Quote 1.28×.**

Selected sites, both far clear of the 500 m rule:

| Site | Centroid | Exceedance | Distance to edge | Percentile |
| --- | --- | --- | --- | --- |
| cool | −111.96359, 33.49963 | 79.61 h (5.69 h/day) | 2 261 m | p5 |
| hot | −112.16039, 33.46193 | 102.21 h (7.30 h/day) | 4 674 m | p95 |

**Gateway trap [2026-08-24]:** the 15 MB response intermittently returns HTTP 504
while being serialised. The activity was fine — the very next poll returned 200 and
a completed result. The M0 client now absorbs up to
`POLL_MAX_CONSECUTIVE_ERRORS` consecutive polling failures rather than discarding an
activity that has already been paid for.

---

## `satellite/` — `POST /v1/satellite`

### Captured [2026-08-24] — the M3 mitigation step 4 cross-check

| File | Site | Segments | Impervious |
| --- | --- | --- | --- |
| `hot_site_segmentation.json` | p95 site, −112.16039 / 33.46193 | road 51.79, earth/ground 32.51, tree 14.2, others 1.5 | **51.8%** |
| `cool_site_segmentation.json` | p5 site, −111.96359 / 33.49963 | tree 41.99, building 23.21, grass 20.23, earth 13.09, mountain 0.99, others 0.49 | **23.2%** |

Both at 2026-08-09 14:00, `filter_type=1`, granularity 100. Land cover
**independently corroborates both rankings**: the hot cell is a road corridor, the
cool cell is vegetated. That is the cross-check doing real work — if land cover had
not explained the ranking, the selection would be an artifact.

Note the check is **directional**. Applying the hot-site test to a cool site would
report a correct selection as a failure, so `siteselection.cross_check_site` takes an
explicit `expect="hot"|"cool"`.

`mountain, mount` was returned and is not in the impervious list — flagged as an
unrecognised class rather than raising, per §7's warning that labels are open-ended.

### Earlier, downtown Phoenix

Not committed to disk. The single call made returned, for downtown Phoenix
2024-07-15 14:00:

```json
{"building": 72.7, "sky": 1.04, "road, route": 12.47,
 "sidewalk, pavement": 8.9, "skyscraper": 2.04, "ship": 2.74, "others": 0.11}
```

Note `"ship": 2.74` in landlocked Phoenix — an ADE20K misclassification. Class labels
are open-ended; never assume a fixed set, never `KeyError` on a missing class.

**Most expensive endpoint measured: 14 400 credits per call.** Capture the raw payload
here the next time one is made.

---

## `INDEX.json` — what makes the cache work

A raw response on disk carries no record of what was asked for, so the cache
cannot resolve a request to it. `INDEX.json` supplies that missing half: one entry
per fixture, naming the client call that produced it.

```jsonc
{ "file": "heatmap/filter3_properties_2026-08-05.json",
  "role": "cache-seed",                     // or "derived"
  "method": "create_heatmap",
  "kwargs": { "polygon_aoi": {...}, "start_date": "2026-08-05", "filter_type": 3,
              "granularity": 100 },
  "note": "why this fixture exists" }
```

`scripts/seed_cache.py` replays those declarations through the **same payload
builders the live client uses** (`build_heatmap_payload`,
`build_env_params_payload`), so a seeded cache key and a live cache key cannot
drift apart. Change a builder and the seeded keys move with it.

- **`role: "cache-seed"`** — a raw API response. Gets a cache entry.
- **`role: "derived"`** — a summary or regression artefact (threshold sweeps,
  exceedance site lists, `temporal_range_verdict.json`, and the bare-result
  `filter3_properties_2024-07-15.json`, whose request is already covered by
  `phoenix_singleday_filter3_raw.json`). **Deliberately not cached** — a summary
  must never be able to masquerade as an API response.

**LIST ORDER MATTERS** in `analysis`. The cache key hashes the payload verbatim,
so `["a","b"]` and `["b","a"]` are different requests. The env_params entry
records the exact order `exploration/step3_phoenix_env_params.py` sent.

The cache itself (`data/cache/`) is derived and gitignored. On a fresh checkout:

```
python scripts/seed_cache.py
```

after which the demo runs with the network disconnected —
`tests/test_m0_client.py::test_every_indexed_fixture_request_serves_from_cache`
is the gate.

---

## Adding a fixture

1. Save the complete raw payload — never a summary.
2. Add a row above stating **what call produced it** and **what it proves**.
3. If it changes a claim in `FORTYGUARD_API_CONTRACT.md`, update that file too.

A fixture whose purpose is not written down is indistinguishable from noise.
