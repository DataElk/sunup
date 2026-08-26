# FortyGuard API: Verified Contract

**Every statement here was confirmed against live responses on 2026-08-23.**
Where something is unverified it says so explicitly. Do not "improve" values in this
file from memory or inference. If a field is not documented here, make a live call
and add it, with the raw payload committed to `fixtures/`.

---

## 1. Auth and transport

```
BASE_URL = https://api.fortyguard.com          # prod
BASE_URL = https://tos-enterprise-api.dev.app.fortyguard.com   # dev override
HEADER   = {"api-key": "<key>", "Content-Type": "application/json"}
```

All analysis endpoints are **asynchronous**:

```
POST /v1/<endpoint>          -> {"data": {"activity_id": "<uuid>"}}
GET  /v1/status/{activity_id} -> {"data": {"status": "...", "result": {...}}}
```

- Status strings are matched **case-insensitively**: `Completed` / `completed` / `succeeded`.
- Terminal failure status is `Failed`.
- The Python client (`FortyGuardClient`) polls for you at 3 s intervals and returns
  `{"activity_id": ..., "result": ...}`. Pass `wait=False` to poll yourself.
- **Failed tasks are free.** Credits are deducted only on `Completed`.

### Response envelope differs by access path

| Path | Shape |
| --- | --- |
| `client.create_heatmap(...)` | `{"activity_id", "result"}` |
| raw `GET /v1/status/{id}` | `{"error", "status_code", "message", "data": {"activity_id", "status", "result"}}` |

Always unwrap defensively:
```python
result = resp.get("result") or resp.get("data", {}).get("result", {})
```

---

## 2. Endpoints

| Endpoint | Method | Tier |
| --- | --- | --- |
| `/v1/heatmap` | `create_heatmap` | Both |
| `/v1/env_params` | `environmental_parameters` | Both (3-param cap on Basic/Startup) |
| `/v1/satellite` | `satellite_segmentation` | Premium |
| `/v1/streetview` | `street_view_segmentation` | Premium |
| `/v1/heat_intelligence` | `heat_intelligence` | Premium; **returns a PDF, not JSON** |
| `/v1/system/fetch-api-key-custom-usage` | `fetch_api_key_custom_usage` | Both |
| `/v1/status/{id}` | `get_status` / `wait_for` | Both |

**Hackathon plan behaves as Premium**: satellite segmentation succeeded on our key.

---

## 3. Hard limits

- **Coverage: United States only.** Non-US AOIs error or return empty. Do not spend credits testing them.
- **Date range: 2021-01-01 → today.** Future dates fail. Earlier dates fail with
  "no data available for this area and date".
- **Coordinates are `[longitude, latitude]`** (GeoJSON order).
- **Granularity: 60, 80, or 100 metres only.** 60 m is the finest available.
- `filter_type`:
  - `1` = single hour (requires `start_time`)
  - `2` = range of hours, same day (`start_time` + `end_time`)
  - `3` = single day, full 24 h (`start_time` ignored)
  - `4` = range of days (requires `end_date`, window capped ~31 days)

---

## 4. `/v1/heatmap`: `analytic_type="tcm"` (default)

**Request**
```python
client.create_heatmap(
    polygon_aoi=<GeoJSON FeatureCollection with a Polygon>,
    start_date="2026-08-09",
    start_time="14:00",
    filter_type=1,
    granularity=100,
)
```

**Response, verified**
```jsonc
{
  "activity_id": "83d4372b-...",
  "result": {
    "map_data": {
      "type": "FeatureCollection",
      "features": [
        { "id": "0", "type": "Feature",
          "properties": {
            "tile_id": 0,
            "average_temperature": 39.7029,   // °C
            "min_temperature":     39.7029,
            "max_temperature":     39.7029
          },
          "geometry": { "type": "Polygon", "coordinates": [[[lon,lat], ...]] } }
      ]
    },
    "stats_data": {
      "temperature_stats": { "minimum", "maximum", "mean", "standard_deviation" },
      "overall_temperature_distribution": [ /* 5 quantile values */ ],
      "normal_temperature_distribution":  { "x_axis": [100], "y_axis": [100] },
      "temperature_frequency":            { "x_axis": [...], "y_axis": [...] }
    }
  }
}
```

### CRITICAL: two different axes, easily confused

| Where | What it is |
| --- | --- |
| `stats_data.temperature_stats.{min,max}` | **SPATIAL**: across cells in the AOI |
| `features[i].properties.{min,max}_temperature` | **TEMPORAL**: within the day, for that cell |

With `filter_type=1` (single hour) the temporal min == avg == max, because there is one
timestep. With `filter_type=3` they differ and carry the diurnal range.

Verified example, `filter_type=3`, 2024-07-15, downtown Phoenix:
```
stats_data:            min 35.798  mean 36.032  max 36.155   (spatial, spread 0.36 °C)
features[0].properties: min 29.599  avg  36.148  max 40.469   (temporal, range 10.87 °C)
```

> **RESOLVED [VERIFIED 2026-08-23, re-checked from fixtures 2026-08-24]:** 2026 dates
> DO carry per-cell temporal min/max. Measured diurnal ranges: 8.22 °C (2026-08-09),
> 5.81 °C (2026-08-05), 6.66 °C (2026-07-26), against an 11.38 °C control on
> 2024-07-15. See `fixtures/temporal_range_verdict.json`. Recent dates are smoother
> than the archive (range ~40% narrower), which under-estimates peak WBGT. The
> one-call-per-site-day reconstruction is confirmed.

### `filter_type=3` returns ONE grid, not 24

A single day request returns one FeatureCollection with min/avg/max per cell, **not**
24 hourly grids. Hourly spatial grids would require 24 × `filter_type=1` calls per day.
Do not do this; see the reconstruction strategy in `CLAUDE.md`.

---

## 5. `/v1/heatmap`: analysis types

`analytic_type` ∈ `tcm` | `time_of_measure` | `exceedance` | `persistence`

| Type | Cell value | Units | Extra params |
| --- | --- | --- | --- |
| `tcm` | snapshot temperature | °C | — |
| `time_of_measure` | **UTC hour-of-day** of peak | hour | — |
| `exceedance` | **count of hours** past `threshold` | hour | `threshold` (°C), `direction` |
| `persistence` | longest continuous run of such hours | hour | `threshold` (°C), `direction` |

`threshold` is **°C** (same unit as tile temperatures). `direction` is `"above"` / `"below"`.
Both are required for `exceedance`/`persistence` and ignored otherwise.
Analysis types require a multi-hour or multi-day window (`filter_type` 2 or 4).

**Different schema from `tcm`:**
```jsonc
{
  "map_data": { "features": [ { "properties": { "tile_id": 0, "value": 6.03 }, "geometry": {...} } ] },
  "stats_data": { "activity_id", "analytic_type", "units": "hour", "n_cells", "min", "max", "mean" }
}
```

Code reading `properties.average_temperature` finds **nothing** on an analysis heatmap.
Read `properties.value` and interpret via `stats_data.units`.

### CRITICAL: the exceedance field is interpolated, not counted

Verified pathologies:
- `min = -0.3176` at threshold 42 °C, a negative duration
- `max = 168.62` on a 168-hour window, 0.62 h past the theoretical ceiling

**Always clamp on ingest:**
```python
value = max(0.0, min(value, window_hours))
```
Never claim integer-hour precision. Never plot an unclamped value.

### CRITICAL: boundary artifacts

Extremes cluster on the AOI edge. Verified on the 14-day 40 °C Phoenix run:
all 5 highest cells sat within 460 m of the west edge; all 5 lowest within 80 m of the
north edge; each set was a contiguous scanline at a single latitude.

**Mitigation, mandatory:**
1. Request an AOI at least 1 km larger than the region of interest.
2. Discard cells within 500 m of the AOI boundary before ranking.
3. Rank by 5th/95th percentile, not absolute min/max.
4. Cross-check any selected cell against satellite segmentation. A genuine hot cell
   has high impervious share. If land cover does not explain it, it is an artifact.

### Threshold selection

`exceedance` is only informative when the mean sits well away from 0 and from the window
length. Verified sweep, Phoenix, 2024-07-01→07 (168 h window, 38 569 cells):

| threshold | mean (h) | spread (h) | spread/mean | % of window |
| --- | --- | --- | --- | --- |
| 30 °C | 167.8 | 4.5 | 0.03 | 99.9, saturated and useless |
| 34 °C | 155.2 | 36.4 | 0.23 | 92.4, still saturated |
| 36 °C | 119.6 | 24.5 | 0.21 | 71.2 |
| 38 °C | 90.7 | 29.6 | 0.33 | 54.0 |
| **40 °C** | **52.3** | **25.9** | **0.50** | **31.1, best** |
| 42 °C | 4.9 | 7.8 | 1.60 | 2.9, at the floor |

**Use 40 °C for Phoenix summer.** Re-sweep for any other city or season; do not assume
this transfers.

Verified 14-day run, 2026-07-26 → 2026-08-08, threshold 40 °C:
```
n_cells 38569   min 57.93   max 106.86   mean 95.64   (336 h window)
=> hottest 7.63 h/day, coolest 4.14 h/day, ratio 1.84x
```

**That 1.84× is a RAW MIN/MAX and must not be quoted as a result.** It is precisely the
boundary-artifact statistic §5 of this document warns against: the extreme cells sit on
the AOI edge. After a 1 km buffer, a 500 m edge discard and 5th/95th percentile ranking
the defensible ratio is **1.28×**. See `fixtures/MANIFEST.md` and `WRITEUP.md`.

---

## 6. `/v1/env_params`

**Request** (note: `temperature` is an **input anchor you supply**, not an output)
```python
{
  "latitude": 33.4484, "longitude": -112.0740,
  "temperature": 39.5,
  "date_time": {"start_date": "2024-07-15", "filter_type": 3},
  "analysis": ["wet_bulb_temperature_celsius", "solar_irradiance", "relative_humidity_percent"]
}
```

**Basic / Startup tiers are capped at 3 parameters per request.** Premium has full access.
Omitting `analysis` returns all.

**Available parameters**
- Thermal/atmospheric: `heat_index_celsius`, `apparent_temperature_celsius`,
  `wet_bulb_temperature_celsius`, `relative_humidity_percent`, `precipitation_mm`,
  `cloud_cover_octas`, `elevation`
- Air quality: `air_quality:idx`, `air_quality_pm2p5:idx`, `air_quality_pm10:idx`,
  `air_quality_no2:idx`, `aqi_us_co`, `air_quality_o3:idx`, `air_quality_so2:idx`,
  `methane_ppb`, `co2_ppm`
- Solar: `solar_irradiance`

**Response, verified**
```jsonc
{
  "data": { "result": {
    "metadata": {
      "timezone": "GMT-7", "timezone_offset_hours": -7,
      "time_range": {"start","end","interval":"1h","count":24},
      "timestamps": [ /* 24 ISO strings, local time */ ]
    },
    "locations": [{
      "lat", "lon", "elevation",
      "temperature": 39.5,               // echoes your input anchor
      "parameters": {
        "wet_bulb_temperature_celsius": [ /* 24 hourly values */ ],
        "relative_humidity_percent":    [ /* 24 */ ],
        ...
      },
      "solar_irradiance": {
        "clear_sky": {"ghi": 576.92, "dni": 691.43, "dhi": 85.61},
        "description": "..."
      }
    }]
  }}
}
```

### Five traps

**1. `solar_irradiance` is ONE daily average, not a 24-element array.**
Every other parameter is hourly; this one is a single clear-sky daily mean. Hourly solar
must come from elsewhere (Open-Meteo `shortwave_radiation`).

**2. `heat_index_celsius` is an artifact. Do not use it.**
The endpoint applies your single `temperature` anchor across all 24 hours and varies only
humidity. Since humidity peaks overnight, the curve **peaks around 2 a.m.** Verified
2024-07-15 Phoenix: 52.9 °C at 06:00, 38.6 °C at 16:00, while real air temperature at
06:00 was far lower. It is a humidity-sensitivity curve at fixed temperature.
Use `apparent_temperature_celsius` for the real diurnal cycle.

**3. Spatially coarse.** Two points 1.36 km apart return byte-identical arrays. Treat
`env_params` as characterising the **district**, never as discriminating between sites.
One call per metro per day is sufficient. Do not call it per site.

**4. `cloud_cover_octas` returns PERCENT, not octas.**
The field name says octas (0–8). The captured payload runs 0–100, with a maximum of
exactly 100.0 on 2024-07-15. Dividing by 8 would put cloud fraction at 12.5x and
black out the solar term. Divide by 100.

Note the ambiguity this leaves: on a genuinely clear day every value would fall at or
below 8 and the two scales would be indistinguishable from the data alone. Read the
field as percent unconditionally, and flag days where `max <= 8` rather than
switching on them. `EnvParamsDay.cloud_scale_ambiguous` does this.

### CRITICAL: `/v1/env_params` IS NOT INDEPENDENT OF OPEN-METEO

**[VERIFIED 2026-08-24, full audit: `scripts/audit_env_params_provenance.py`]**

All 15 hourly parameters were compared against the closest Open-Meteo field for the
same point and day. **Fourteen of fifteen match to within rounding.** The one that
does not is the `heat_index_celsius` artifact, which FortyGuard computes itself from
the temperature anchor you supply, and which trap 2 already says not to use.

| FortyGuard parameter | Open-Meteo field | Verdict |
| --- | --- | --- |
| `cloud_cover_octas` | `cloud_cover` | **IDENTICAL**: all 24 values |
| `precipitation_mm` | `precipitation` | **IDENTICAL**: all 24 values |
| `relative_humidity_percent` | `relative_humidity_2m` | same to rounding (±0.5) |
| `air_quality:idx` | `us_aqi` | same to rounding (±0.5) |
| `air_quality_pm2p5:idx` | `us_aqi_pm2_5` | same to rounding (±0.5) |
| `air_quality_pm10:idx` | `us_aqi_pm10` | same to rounding (±0.5) |
| `air_quality_no2:idx` | `us_aqi_nitrogen_dioxide` | same to rounding (±0.5) |
| `air_quality_o3:idx` | `us_aqi_ozone` | same to rounding (±0.5) |
| `air_quality_so2:idx` | `us_aqi_sulphur_dioxide` | same to rounding (±0.5) |
| `aqi_us_co` | `us_aqi_carbon_monoxide` | same to rounding (±0.5) |
| `apparent_temperature_celsius` | `apparent_temperature` | 15/24 exact, worst 0.1 °C |
| **`wet_bulb_temperature_celsius`** | **`wet_bulb_temperature_2m`** | **15/24 exact, worst 0.1 °C** |
| `heat_index_celsius` | — | genuinely different (and an artifact) |
| `methane_ppb`, `co2_ppm` | — | all-null both sides |

It is **not a verbatim re-serve**: FortyGuard reports 0.1 precision where Open-Meteo's
ERA5 archive reports integers on several fields, so FortyGuard is not simply copying
Open-Meteo's output. The likeliest reading is that both derive from the same underlying
reanalysis (ERA5 for weather, CAMS for air quality). For every practical purpose the
conclusion is the same: **they are not independent sources.**

Three consequences that change what the project may claim and how it should be built:

1. **Agreement between them is not corroboration.** Never write "FortyGuard and
   Open-Meteo agree, so the value is confirmed". That is circular.
2. **The wet bulb carries the 0.7 weight in WBGT and is not FortyGuard-specific.**
   The single largest term in the heat index agrees with a free public API to 0.1 °C.
   Describe the pipeline accurately: FortyGuard supplies the *tiles*, not the wet bulb.
3. **`env_params` costs ~2 900 credits per metro-day for data available free.** The
   air-quality fields are US AQI sub-indices, and the overall `air_quality:idx` is the
   max of them, exactly as the US AQI is defined. If credits ever get tight, this
   endpoint is the first thing to replace.

**What IS genuinely FortyGuard:** `/v1/heatmap`, with its 60–100 m tiles, the per-cell
temporal min/mean/max, the exceedance and persistence fields. Those have no Open-Meteo
equivalent at any price, and the entire product rests on them. This audit strengthens
rather than weakens the case for the architecture in `CLAUDE.md`: it is right to take
amplitude and offset from the tiles and everything else from wherever is cheapest.

---

**[VERIFIED 2026-08-24] `cloud_cover_octas` is byte-identical to Open-Meteo's `cloud_cover`.**
All 24 values for downtown Phoenix 2024-07-15 match exactly:

```
FortyGuard cloud_cover_octas : 43 98 85 23 10 2 100 82 1 0 4 1 11 5 0 16 50 25 7 1 1 3 0 0
Open-Meteo  cloud_cover (%)  : 43 98 85 23 10 2 100 82 1 0 4 1 11 5 0 16 50 25 7 1 1 3 0 0
```

That settles the units beyond argument, and it strongly suggests `/v1/env_params` is
served from the same reanalysis backend Open-Meteo uses (ERA5 or similar) rather than
from FortyGuard's own tile model. Two consequences:

1. **`env_params` is not an independent check on Open-Meteo.** Do not present
   agreement between them as corroboration. For cloud it is a tautology.
2. It reinforces trap 3: `env_params` characterises the district, not the site. The
   per-cell tile data from `/v1/heatmap` is the part that is genuinely FortyGuard's.

Pinned by `tests/test_sources.py::test_fortyguard_cloud_is_byte_identical_to_open_meteo`.

**5. `solar_irradiance.clear_sky` is a DAYLIGHT-hours mean, not a 24-hour mean.**
The endpoint says "from 2024-07-15 00:00 to 2024-07-15 23:00", which reads like a
24-hour average. It is not. For downtown Phoenix on 2024-07-15 it reports
`ghi = 576.92 W/m²`; a clear-sky model for that site-day gives a 24-hour mean of
357.3 W/m² and a daylight-hours mean of 612.5 W/m². Only the second is close.

This matters: anchoring an hourly solar curve to the wrong window scales every
irradiance by ~1.7x, and the globe-temperature term with it.

**`methane_ppb` and `co2_ppm` returned all-null** on our verified call. Handle nulls.

### `analysis` may not be applied: UNRESOLVED

`fixtures/MANIFEST.md` records the captured call as
`analysis=[wet_bulb_temperature_celsius, solar_irradiance, relative_humidity_percent]`,
three parameters. The committed payload contains **fifteen**. Either the request
differed from what the manifest records, or `analysis` is ignored and the endpoint
always returns everything.

This is not academic. The WBGT pipeline additionally needs
`apparent_temperature_celsius` (diurnal shape) and `cloud_cover_octas` (solar
attenuation). If `analysis` IS applied and the tier cap is three, the M3 backfill
would silently lose both.

**[ATTEMPTED 2026-08-24, INCONCLUSIVE.]** Two live probes were submitted requesting a
single parameter (`analysis: ["wet_bulb_temperature_celsius"]`), via
`scripts/probe_env_params_analysis.py`. Both were accepted and returned an
`activity_id`, and both then sat at status `Processing` indefinitely, the first for
3 minutes before the runner gave up, the second for a full **30 minutes / 600 polls**
(activity `70dcdf72-7520-4f82-ad17-4cf246b255f7`) without ever reaching `Completed`.
No result was returned, so the question stands open.

Note for whoever retries: the original 3-parameter call in `exploration/` completed
normally, so a request that never finishes may itself be a signal about how `analysis`
is handled. Do not read that as established; it is one observation, twice.

**Because it is unresolved, the M0 client is built CAP-TOLERANT and does not depend on
the answer:** it chunks any `analysis` list into groups of `ENV_PARAMS_MAX_ANALYSIS`
and merges the responses, so it behaves correctly whether the cap binds or not. See
`FortyGuardClient.environmental_parameters`. Credits are the only cost of being wrong,
and chunking costs nothing when the cap does not bind because a single chunk is a
single call.

---

## 7. `/v1/satellite`: segmentation

**Request**
```python
{"sat": {"latitude": 33.4484, "longitude": -112.0740},
 "date_time": {"start_date": "2024-07-15", "start_time": "14:00", "filter_type": 1},
 "granularity": 100}
```

**Response**: `result.segmentation.segments` = `{class_name: percent}`,
`result.segmentation.image_legend` = `{class_name: [r,g,b]}`.

Verified, downtown Phoenix:
```json
{"building": 72.7, "sky": 1.04, "road, route": 12.47,
 "sidewalk, pavement": 8.9, "skyscraper": 2.04, "ship": 2.74, "others": 0.11}
```

**Class labels are ADE20K-style and open-ended.** `"ship": 2.74` in landlocked downtown
Phoenix is a misclassification. Never assume a fixed class list; never `KeyError` on a
missing class; tolerate implausible ones. Derive impervious share by summing the classes
you recognise (`building`, `skyscraper`, `road, route`, `sidewalk, pavement`) rather than
subtracting from 100.

Note `sky` appears as a class. The model segments a rendered view, so sky share is not
a land-cover fact.

**Most expensive endpoint measured: 14 400 credits for a single call.** Cache hard.

**[VERIFIED 2026-08-24] Two further calls, for the M3 site cross-check.** Both
completed in 1-2 polls, far faster than a heatmap call of comparable value.

```jsonc
// p95 site, -112.16039 / 33.46193  ->  51.8% impervious
{"road, route": 51.79, "earth, ground": 32.51, "tree": 14.2, "others": 1.5}
// p5 site,  -111.96359 / 33.49963  ->  23.2% impervious
{"tree": 41.99, "building": 23.21, "grass": 20.23, "earth, ground": 13.09,
 "mountain, mount": 0.99, "others": 0.49}
```

`mountain, mount` is a class not seen before. The label set is open-ended, exactly
as warned above. Both payloads are committed under `fixtures/satellite/`.

**The cross-check is DIRECTIONAL.** §5 states the rule for hot cells ("a genuine hot
cell has high impervious share"). Run backwards it validates a cool cell: a genuinely
cool cell in a desert city should be vegetated or bare, not paved. Applying the hot
test to a cool site reports a correct selection as a failure, so
`siteselection.cross_check_site` requires an explicit `expect="hot"|"cool"`.

---

## 8. Credits: measured

Hackathon plan, 2 000 000 credits, cycle 2026-08-23 → 2026-09-27.

| Activity | Credits | Calls | Per call |
| --- | --- | --- | --- |
| Heatmap Generation | 16 880 | 4 | ~4 220 avg |
| Tile Satellite Segmentation | 14 400 | 1 | 14 400 |
| Environment Parameter Analysis | 2 900 | 1 | 2 900 |

Heatmap cost scales with cell count: an 81-cell parcel call is far cheaper than a
38 569-cell metro call. Budget the metro exceedance calls carefully; parcel calls are cheap.

**Estimated full build: 200–300k credits with caching.** Roughly 6× headroom. There is no
need to work around the quota.

---

## 8a. Gateway behaviour on large responses: [VERIFIED 2026-08-24]

**Large responses intermittently return HTTP 504 while being serialised.** A
`filter_type=4` exceedance run over the metro AOI buffered by 1 km returned
**46 931 cells / 15.3 MB**. The first status poll returned `504 Gateway Timeout`;
the very next poll, twenty seconds later, returned `200` with a `Completed` result.

**The activity was never in trouble; the gateway was.** Treating that 504 as fatal
throws away an activity that has already been paid for and cannot be recovered
without the id.

Clients must therefore:
1. absorb transient polling failures rather than propagating them (the M0 client
   allows `POLL_MAX_CONSECUTIVE_ERRORS` consecutive failures before giving up);
2. persist the `activity_id` the instant it is issued, so a crashed poller can
   resume instead of resubmitting.

Timing measured the same day, for budgeting: an 81-cell parcel `filter_type=3` call
completes in **~40 polls (2 min)**; the same call against the two M3 sites took
**~4.7 min**. A 28-call backfill is therefore roughly a two-hour job, not a
two-minute one. Plan batches accordingly.

### `/v1/status/{id}` is also how you recover a hung request

Two `/v1/env_params` probes on 2026-08-24 sat at `Processing` for 3 and 30 minutes
and never completed (section 6). Heatmap and satellite calls submitted the same day
completed normally, so the stall is not a general API outage. If a submit succeeds
and polling stalls, keep the id: the work may still land.

---

## 9. Payload size

A metro AOI (~384 km²) at 100 m granularity returns **38 569 features**. Stream responses
to disk rather than holding them in memory, and never load a metro grid into the frontend.
Extract site polygons server-side and send only what renders.

---

## 10. Caching: required, not optional

The demo must run with zero live calls. Follow the pattern in the quickstart's parcel
notebooks: commit raw responses under `fixtures/`, key the cache on a hash of the full
request payload, and gate live calls behind a `REFRESH` flag defaulting to `False`.

A live demo that depends on the network is a demo that fails on stage.
