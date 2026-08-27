# Sunup

*Repository `sunup`; the product is **Sunup**. Only the repository name differs;
everything in the code, documents and interface says Sunup.*

Per-worker heat acclimatization state for construction crews, built on FortyGuard's
temperature API. FortyGuard Hackathon '26.

The OSHA heat rule ramps a new worker in on a calendar: 20% of a shift on day one, up to
100% on day five. It does not know what the weather was on those days or what hours the
worker was rostered. Sunup estimates each worker's adaptation state from actual
exposure, turns it into a personal limit in °C-WBGT, and prescribes minutes against that
limit instead.

---

## Read this first

**This is a hackathon prototype. Do not use it to make real decisions about real workers.**

- **The work/rest ladder, the thing that decides whether a worker is told to stop, is
  our own construction, not a standard.** We went to verify it against "the NIOSH
  work/rest schedule table" and found that no such table exists. It is sensitivity-tested
  (`scripts/audit_ladder.py`) but it is not validated.
- **The single most prescription-sensitive constant is one we set ourselves.** ISO 7243
  gives only the longwave globe coefficient; we set shortwave absorptivity equal to it.
  ±0.05 moves a prescription by 30 minutes.
- **The OSHA heat standard is PROPOSED, not law.** Nothing here is a compliance claim.
- **Forecast accuracy is a 7-day backtest at one site**, and one of its two subjects is
  degenerate. Not a performance figure.
- **16 constants remain unverified** against paywalled standards. `constants.py` section
  0b says which ones can actually move an answer (two) and which cannot (ten).

Full list in [WRITEUP.md](WRITEUP.md) under *Caveats, stated plainly*.

**Never accepted, by design:** age, sex, gender, BMI, weight, height, fitness, medical
history, medication, hydration, home address, ethnicity. Every input is environmental or
job-assigned. The engine raises `ForbiddenInput` rather than ignoring such a field.

---

## The result

Two workers, same site, same trade, same day of employment, differing only in shift:

| day | model's separation | the calendar says |
| --- | --- | --- |
| 4 | **+1.07 °C** | 80% to both |
| 5 | +1.33 °C | **100% to both** |
| 14 | **+2.75 °C** | 100% to both |

84/84 τ pairs, both wet-bulb methods, from day 3 onward. **The calendar's error compounds:**
from day 5 it is saturated and says the same thing about both men forever, while the
physiological gap between them more than doubles again.

Site assignment, by contrast, does not survive: 0/84. A 1.284× exceedance ratio
becomes 1.118× in worked dose, and `correlation(peak WBGT, worked dose) = +0.13`.
Temperature barely predicts adaptation; scheduling does.

---

## Run it

```bash
pip install -r requirements.txt
python -m pytest tests -q
```

The interface is static and **makes zero network calls**:

```bash
python -m http.server 8777
```

Then open `http://localhost:8777/app/index.html`. Four workspaces: roster, exposure map,
forecast vs actual. Every input is a cached fixture emitted as a JS module, so it also
works from `file://` and cannot fail on stage because of an API.

### The evidence

```bash
python scripts/m3_report.py        # section 6 is the headline trajectory
python scripts/audit_ladder.py     # ladder sensitivity, incl. the no-rung variant
python scripts/audit_resolution.py # what the API actually resolves spatially
python scripts/audit_constants.py  # which constants can move a prescription
node scripts/check-design.mjs      # design lint (blocks the build, not advisory)
```

### Rebuilding the data (needs an API key)

Not required, because derived data is committed. `FORTYGUARD_API_KEY` goes in `.env`.

```bash
python scripts/m3_fetch.py --probe           # one cheap call, check the API answers
python scripts/m3_fetch.py --exceedance      # metro grid for site selection
python scripts/m3_fetch.py --backfill        # 14 days x 2 sites
python scripts/m3_fetch.py --metro-snapshot  # single-hour metro grid for the audit
python scripts/build_roster_data.py
python scripts/build_map_data.py
python scripts/build_basemap.py --fetch      # OpenStreetMap locator layer
python scripts/build_overlay_data.py
```

---

## How it works

1. **WBGT** from FortyGuard tiles + Open-Meteo hourly. Black-globe temperature by
   radiative-convective energy balance (ISO 7243:2017 Annex B globe spec); natural wet
   bulb psychrometric, cross-checked against ISO 7243 Annex D.
2. **Daily stimulus** = degree-hours above the *fixed* RAL for the trade's workload class,
   counting only hours actually worked, weighted by the prescribed duty cycle. Integrating
   above the *moving* personal limit would be circular: an adapted worker would accrue
   less dose for identical weather.
3. **Adaptation state** `A(t+1) = A + s·(1−A)/τ_gain − (1−s)·A/τ_decay`, A ∈ [0,1].
4. **Personal limit** = `RAL + A·(REL − RAL)`, NIOSH 2016-106 Figures 8-1/8-2.
5. **Work/rest** read off the ladder at that limit. *Our construction; see caveats.*

## Layout

```
src/sunup/     engine: wbgt, globe, solar, psychrometrics, acclimatization
  constants.py     every constant, sourced and confidence-tagged; §0b is the triage
scripts/           fetch, build, report, and the four audits
app/               static interface: roster, map, forecast, settings
fixtures/          cached API responses; MANIFEST.md explains each
tests/             336 tests, including a per-milestone exit test
SPEC.md            the plan and the evidence
WRITEUP.md         the full account, including three self-corrections
DESIGN_SYSTEM.md   the interface rules and why each exists
```

## Provenance

FortyGuard supplies the tile temperature field and the exceedance analytics. Open-Meteo
supplies hourly wind, radiation and the diurnal shape. The map's locator layer is
OpenStreetMap data, © OpenStreetMap contributors, ODbL 1.0, fetched once at build time and
cached, so no tile server is contacted at render time.

`env_params` is not independent of Open-Meteo (14 of 15 parameters match to rounding),
so agreement between them is never presented as corroboration.
