# Sunup

A per-worker heat acclimatization state estimator for construction workforces,
built on FortyGuard's temperature API. Submission for FortyGuard Hackathon'26.

---

## How to use this document

This file pins **facts, constraints and definitions of done**. It deliberately does
not tell you how to build anything.

- **Pinned, verify against the cited source, do not infer:** physical and regulatory constants
  (`constants.py`), the API's real behaviour (`FORTYGUARD_API_CONTRACT.md`), the
  design tokens, and the milestone exit tests below.
- **Open, your call:** architecture, module layout, libraries, algorithms, how to
  implement, how to debug, how to structure tests. Research freely. Try things.

If a needed fact is missing, **go find it and write it down**. Search the web, make
a live API call, read the standard. Do not fill a gap by inference and move on.
A wrong constant discovered on day 10 costs more than an hour of checking on day 1.

---

## What this is

**Three out of four US workplace heat fatalities occur in a worker's first week**,
before the body has physiologically acclimatized. OSHA's proposed rule manages this
with a calendar: 20% of a shift on day one, +20% per day.

**But acclimatization is driven by cumulative heat exposure, not by days elapsed.**
A worker whose first three days were mild is treated as adapted on day four when he
is not. The calendar is a proxy for a measurement nobody could take.

The obvious guess about what that measurement is turns out to be wrong, and finding
that out is the most valuable thing this project did.

### The measurement is not temperature

The intuition (hotter site, faster adaptation) does not survive contact with the
data. Measured across a 14-day two-site backfill, real retrieved:

> **correlation(shift peak WBGT, worked heat dose) = +0.13**

Peak temperature is very nearly **useless** as a predictor of adaptive dose. Two
mechanisms cause this, and both are real rather than modelling artifacts:

1. **The work/rest rule removes the exposure.** Hotter hours are exactly the hours
   the work/rest ladder prescribes at or near zero, so they contribute no adaptive
   stimulus. Heat that stops you working does not adapt you.
2. **Days differ in shape, not in level.** Real day-to-day variation is duration
   above the RAL, cloud, wind and timing, not a uniform temperature offset.

### The measurement is exposure duration, and shift timing controls it

What drives adaptation is **hours actually worked above the RAL**, and the employer
controls that directly through the roster. Measured on the personal limit in
°C-WBGT, across all 84 τ pairs, under **both** wet-bulb methods:

All gaps are quoted **at day 4 on the job**, on the 14-day backfill, but the point is
the curve, not the point. `scripts/m3_report.py` section 6 prints it in full:

| day | limit gap, psychrometric | limit gap, ISO Annex D | τ material | the calendar says |
| --- | --- | --- | --- | --- |
| 2 | +0.28 °C | +0.14 °C | 36/84, 0/84 | 40% to both |
| 3 | +0.60 °C | +0.37 °C | 84/84, 72/84 | 60% to both |
| **4** | **+1.07 °C** | **+0.73 °C** | 84/84 both | 80% to both |
| 5 | +1.33 °C | +0.96 °C | 84/84 both | **100% to both** |
| 8 | +1.87 °C | +1.14 °C | 84/84 both | 100% to both |
| 11 | +2.46 °C | +1.67 °C | 84/84 both | 100% to both |
| **14** | **+2.75 °C** | **+2.08 °C** | 84/84 both | 100% to both |

**The calendar's error compounds.** The OSHA ramp reaches 100% on day 5 and from then on
has no term that could distinguish these two men. It issues the identical instruction on
day 5 and on day 14. Over those same nine days the physiological gap between them more
than doubles again, from +1.33 °C to +2.75 °C. A single day-4 number made a compounding
effect look like a fixed one, and happened to quote it near the weak end of the curve.

| lever | survives | limit gap (day 4) | at day 14 |
| --- | --- | --- | --- |
| **shift timing** 05:00-13:00 vs 10:00-18:00 | **84/84 both methods** | **+1.07 °C** | **+2.75 °C** |
| shift timing 05:00-13:00 vs 08:00-16:00 | 84/84 both methods | +0.99 °C | +2.15 °C |
| day selection, ranked by worked dose | 84/84 both methods | +0.63 °C |  -  |
| day selection, ranked by peak temperature | 36/84 and 54/84 | +0.27 °C |  -  |
| site assignment, p5 vs p95 | **0/84 both methods** | +0.23 °C |  -  |

**The shift-timing result is not an artifact of our work/rest ladder.** The ladder is
our construction, not a standard (constants.py §2), so it was sensitivity-tested the way
τ was. `scripts/audit_ladder.py` reproduces all of this.

**Start with the cleanest case: remove the ladder entirely.** Replace the four rungs with
a continuous response (60 min/h at the limit falling linearly to zero 4 °C above it, no
steps at all) and the result still holds: +1.19 °C at day 4, sign correct in 84/84 τ
pairs under both wet-bulb methods. *The finding does not require there to be rungs.*
That is the direct answer to "did you tune the ladder to get the answer you wanted": the
answer survives having no ladder.

Across all eight variants (boundaries moved ±0.5 °C, three rungs, five rungs, a crude
two-rung, an aggressive three-rung, and the no-rung case) **the sign holds in 62 of 64
ladder × method × shift × day configurations, at 84/84 τ pairs each.** Materiality at the
0.5 °C threshold holds in **51 of 64**; the failures concentrate in a deliberately
aggressive ladder that stops work 1.5 °C above the limit and so compresses every worker
toward zero, leaving nothing to differ by.

The honest split: **the comparative claim does not depend on the ladder. The absolute
prescription is only as good as the ladder, and the ladder is ours.**

**The demo in one screen:** two workers, same crew, same trade, both on day four,
both given 80% by the calendar. One was rostered 05:00-13:00, the other 10:00-18:00.
They differ by **1.07 °C of personal limit**, a different written instruction, and
the calendar has no term that could ever tell them apart. Left on those rosters the gap
reaches 2.75 °C by day 14.

---

## Verified evidence this works

**[REBUILT 2026-08-25 after M3. The original claim on this line was an artifact and
the thesis it supported was wrong.]**

### The original number, and why it was withdrawn

> ~~Hottest cell: **7.63 hours/day** above 40 °C. Coolest cell: **4.14 hours/day**.~~
> ~~**A 1.84× difference in heat dose between two points in the same metro.**~~

That was a **raw min/max ratio**, exactly the statistic `FORTYGUARD_API_CONTRACT.md`
§5 says must never be used. Every one of the top-5 and bottom-5 cells it came from
sits inside the 500 m boundary-artifact band: the hottest 42.7 m from the west edge,
the coolest 78.5 m from the north.

### The site data, re-measured properly: now the CONTROL

Re-run 2026-08-24 with the mandated mitigation (AOI buffered 1 km, 46 931 cells,
4 201 dropped within 500 m of the edge, ranked at 5th/95th percentile):

> 95th-percentile site **7.30 h/day** above 40 °C, 5th-percentile site **5.69 h/day**,
> a **1.28×** difference. Both sites 2.3 km and 4.7 km clear of the AOI edge, and
> satellite segmentation corroborates both rankings independently: the hot cell is a
> road corridor (51.8% impervious), the cool cell is vegetated (42% tree, 20% grass).

**And it does not survive.** 1.284× of exceedance *hours* becomes only **1.118× of
worked dose**, because the extra hot hours at the p95 site are the ones prescribed at
or near zero. The resulting divergence is +0.23 °C, **below materiality, 0/84 τ
pairs, under both wet-bulb methods**.

That negative result is not a setback; it is what makes the positive one credible.
Two sites 20 km apart, differing by a genuine and independently corroborated 1.28× in
exposure hours, move the prescription **less** than moving one crew's start time by
five hours. The site comparison is the **control that isolates shift timing** as the
lever that actually matters.

### The inversion, and where it holds

A worker rostered 10:00-18:00 in Phoenix is prescribed **zero minutes in every hour**.
He accumulates no dose and **never acclimatizes at all**. Protection, applied without
regard to timing, is self-defeating.

- **Holds for shift timing**, strongly: 84/84 τ pairs, both wet-bulb methods. The
  later shift is always the *less* adapted worker.
- **Does not hold for day selection.** On the real 14-day series the higher-dose
  history produces the *more* adapted worker every time. The version of this claim
  in the M2 report was an artifact of four overlapping cached days.

Say both halves. The asymmetry is the point: timing decides whether heat adapts a
worker or merely endangers him, and the calendar cannot see timing at all.

### What may and may not be claimed

**May:** the calendar assigns two workers the same ramp when their measured exposure
differs enough to warrant different written instructions, and it has no term that
could separate them. The model separates them, explains why hour by hour, and can say
which schedule adapts a crew fastest without exceeding the strain ceiling
(`constants.py` §3b).

**May not:** that hotter sites adapt workers faster (they do not, +0.13 correlation);
that the site ratio is 1.84× (it is 1.28×, and it does not reach materiality); or that
weather history alone can separate workers by more than **1.02 °C, 34% of the
RAL→REL span**, which is a measured structural ceiling, not a data shortage.

---

## Tracks

- **Track 05, Model Designing**: the primary claim. The acclimatization state
  estimator is the decision model. This is what differentiates the submission.
- **Track 03, Industrial & Enterprise**: the application. Deployed as a workforce
  safety system.

Frame everything as: *Track 03 is where it is used. Track 05 is what it is.*

---

## Hard constraints

1. **US only.** FortyGuard serves no data outside the United States. The demo is Phoenix.
2. **No future dates.** Coverage is 2021 → today. See the `DEMO_TODAY` trick in
   `constants.py`. "Today" is set two weeks back so both the backfill and the
   forward projection resolve to real data.
3. **Never invent a constant.** Every physical, physiological and regulatory number
   lives in `constants.py` with a source and a confidence tag. Values tagged
   `[CHECK]` must be confirmed against the cited document before submission.
4. **Never claim the OSHA rule is law.** It is proposed and unfinalised. Enforcement
   is nevertheless active via the National Emphasis Program and the General Duty
   Clause. That gap is the product's premise, so state it accurately.
5. **Forbidden inputs are forbidden.** See `FORBIDDEN_INPUTS` in `constants.py`. No
   age, sex, BMI, fitness, medical history, or home address. Not ever, not anywhere, not
   even as an optional field. This is a legal constraint, not a preference.
6. **Cache everything.** The demo must run with zero live API calls. A demo that
   needs the network is a demo that fails on stage.
7. **Sites are user input.** Ship one fixture; never hardcode a site into logic.
   The system takes any GeoJSON.
8. **Commit directly to `master`. Never branch.** This is a single-developer
   repository with no remote and no review step, so a branch buys nothing and
   costs a merge. No feature branches, no PR flow: commit straight to `master`.
9. **One commit per milestone, minimum. Never fuse milestones into one commit.**
   A milestone is the unit of work that has its own exit test, so it is also the
   unit that has to be revertible on its own. If a milestone is large, split it
   further, but never merge M(n) and M(n+1) into a single commit, because that
   makes it impossible to bisect which milestone broke an exit test.

   *Recorded against ourselves:* commit `e15cf93` fused M0 and M1 and should have
   been two commits. History is left as-is; the rule applies from M2 onward.

---

## The model

```
Environment  ->  WBGT  ->  daily stimulus s  ->  adaptation state A  ->  work/rest
```

1. **WBGT** from FortyGuard dry bulb (the tiles) + hourly wet bulb, solar and wind.
   Weights and sources in `constants.py` §5.

   **Say this accurately.** [VERIFIED 2026-08-24] The wet bulb is served by
   FortyGuard `/v1/env_params`, but that endpoint is **not independent of
   Open-Meteo**: 14 of its 15 hourly parameters match Open-Meteo to within
   rounding, wet bulb included (15/24 hours exact, worst 0.1 °C). See
   `FORTYGUARD_API_CONTRACT.md` §6. So do not describe the wet bulb as
   FortyGuard-specific data, and never present FortyGuard/Open-Meteo agreement as
   corroboration. It is circular.

   What IS uniquely FortyGuard is `/v1/heatmap`: the 60-100 m tiles, the per-cell
   diurnal min/mean/max, and the exceedance field. That is the whole basis of the
   product, and it is enough. The architecture already takes amplitude and offset
   from the tiles and everything else from wherever is cheapest. This finding
   confirms that split rather than undermining it.
2. **Daily stimulus** `s ∈ [0,1]`: degree-hours above the worker's personal limit,
   normalised. Only exposure above threshold builds adaptation.
3. **State update**
   ```
   A(t+1) = A + s·(1-A)/τ_gain − (1-s)·A/τ_decay
   ```
   Gain ~3× faster than decay: earned in days, lost over weeks.
4. **Personal limit** interpolates continuously between NIOSH's two published
   curves, RAL (unacclimatized) and REL (acclimatized):
   ```
   WBGT_limit(A) = RAL + A·(REL − RAL)
   ```
   **This is the intellectual core.** NIOSH already publishes two limits and treats
   acclimatization as a binary switch. We place each worker continuously between
   them. We are not inventing a threshold.
5. **Work/rest** read off the work/rest ladder at that limit.

### Where ML belongs, and where it does not

**The core has no machine learning, deliberately.** There is no labelled dataset of
(exposure history → acclimatization state); it has never been measured at scale. Any
"trained" model would be fit to synthetic data from a physics model, which is circular and
strictly worse. The output restricts a man's working hours, so it must be explainable
to him, to a lawyer, and to an inspector. And heat waves are out-of-distribution by
definition, which is exactly when a model trained on history fails.

Say this out loud in the writeup. It reads as engineering maturity.

**One place ML genuinely earns its seat.** FortyGuard forecasts 12 hours; the ramp
projection needs 3-5 days. Open-Meteo forecasts a week but only regionally. So learn
the local anomaly:

```
Δ = T_fortyguard − T_regional = f(land cover, hour, solar, wind, season)
```

Train on historical pairs you can actually retrieve, with satellite segmentation as
features, then apply the learned anomaly to the longer regional forecast. Real
training data, hold-out validatable, and necessary. Gradient boosting on tabular
features, the standard result for this shape of problem.

---

## Data strategy

The expensive mistake to avoid: hourly spatial grids cost 24 calls per site per day
(336 for a 14-day backfill). Do not do that.

**Instead:**
- `filter_type=3`, **one call per site per day** → that cell's daily min/mean/max.
  14 calls per site for the whole backfill.
- **Open-Meteo hourly** for Phoenix → the diurnal *shape*.
- Reconstruct the site's hourly curve by fitting the shape between that cell's own
  min and max.

FortyGuard sets amplitude and offset (the part only it has); Open-Meteo sets shape.

`env_params` is spatially coarse: two points 1.36 km apart return byte-identical
arrays. **One call per metro per day**, never per site.

[VERIFIED 2026-08-23] 2026-dated filter_type=3 responses do carry per-cell
temporal min_temperature/max_temperature. Measured diurnal ranges: 8.22 °C
(2026-08-09), 5.81 °C (2026-08-05), 6.66 °C (2026-07-26), against an 11.38 °C
control on 2024-07-15. The one-call-per-site-day reconstruction is confirmed.

Known bias: recent dates are smoother than the archive, with diurnal range roughly
40% narrower, parcel-scale spatial spread ~10× smaller (0.04 °C vs 0.36 °C). Real
Phoenix August swings 12-14 °C, so both are compressed and 2026 more so. This
under-estimates peak WBGT, hence stimulus, hence adaptation rate, a conservative
bias, but a bias. M1 must compare FortyGuard's daily amplitude against
Open-Meteo's for the same site-day and record the discrepancy. State it as a
caveat in the writeup.

---

## Milestones

Each has a **falsifiable exit test**. "Done" means the test passes, not that the code
looks finished. Do not start the next milestone until the current one passes.

### M0: API client and cache
Typed client over the endpoints in `FORTYGUARD_API_CONTRACT.md`. Disk cache keyed on
a hash of the full request payload. `REFRESH` flag defaults to `False`.

**Exit:** with the network disconnected, every fixture request returns from cache.
Clamping is applied to exceedance values on ingest. A negative or over-window value
cannot reach the rest of the system.

### M1: WBGT pipeline
Compose dry bulb, wet bulb, solar and wind into hourly WBGT for a site-day.

**Exit, a REGRESSION ANCHOR rather than a validation against ground truth.** Reproduces
the reference in `constants.py` §5: downtown Phoenix 2024-07-15 gives ≈31 °C at 14:00
and ≈24.8 °C at 06:00, both within ±1 °C. The day crosses both the RAL and REL curves
for moderate work.

**Read that exit criterion for exactly what it is.** The ≈31 °C was hand-computed from
a single retrieved hour, and the hand computation used FortyGuard's **psychrometric**
wet bulb in the 0.7 term. WBGT is defined on the **natural** wet bulb, and
ISO 7243:2017 Annex B.1 says the two differ. So the reference and the pipeline share an
assumption, and passing the test proves they agree, not that either is right.

No black-globe thermometer stood in downtown Phoenix on 2024-07-15. There is no ground
truth available for this site-day, and the test does not pretend otherwise.

What it *does* buy, which is still worth having:
- it catches regressions: a refactor that moves WBGT by 1 °C fails loudly;
- it is a **coherence** check across four independent inputs (FortyGuard tiles,
  FortyGuard env_params, modelled solar geometry, Open-Meteo), which would not land
  within 0.1 °C of a separately hand-derived number by coincidence;
- the day crossing both NIOSH curves is what makes the site-day useful to M2 at all.

What it does **not** buy: any claim of absolute WBGT accuracy. Do not write "validated
to ±1 °C" in the writeup. Write "reproduces our recorded reference to ±0.1 °C, under
the same psychrometric assumption the reference was computed with."

Independent corroboration that *is* meaningful, and should be quoted instead:
the reconstructed 14:00 dry bulb lands **0.07 °C** from a `filter_type=1` snapshot
(a separate API call reading a different axis), and the anchored clear-sky solar curve
peaks within **14 W/m²** of Open-Meteo's measured shortwave.

### M2: Acclimatization engine
The state model, stimulus, personal limit, work/rest ladder.

**Exit:** the two-worker divergence reproduces from real retrieved data: same trade,
same day-on-job, mild vs hot first three days, materially different prescriptions.
Sensitivity report across τ_gain ∈ [3,6] and τ_decay ∈ [10,21] showing the divergence
survives the whole range.

**And it must survive BOTH wet-bulb methods.** Run the whole divergence under
`NWB_PSYCHROMETRIC` and again under `NWB_ISO_ANNEX_D` (see `constants.py` §5b/§5g).
The two differ by up to +2.5 °C on the natural wet bulb at midday, which carries the
0.7 weight, so this is the largest single modelling choice upstream of the state
model, larger than either τ.

If the divergence only appears under one method, it is an artifact of that method and
the claim collapses. If it survives both, the claim is that the *calendar cannot
separate these two workers and exposure history can*, which does not depend on
resolving the wet-bulb question at all. That is a much stronger thing to say to a
judge, and it is the reason this is in the exit test rather than the writeup.

Report both prescriptions side by side. If they differ in the work/rest step assigned,
say so and give both numbers.

### M3: Site selection and backfill
Ingest site GeoJSON, backfill 14 days, rank sites.

**Exit:** the boundary-artifact mitigation is in place (buffered AOI, 500 m edge
discard, percentile ranking) and selected cells are cross-checked against satellite
segmentation. No selected site sits within 500 m of an AOI edge.

### M4: Interface
Supervisor roster, ramp strip, counterfactual, plan record export.

**Exit:** every screen renders from the design tokens; a supervisor can answer
"who works today and for how long" in under ten seconds; the adaptation number never
appears on a grid row.

**Superseded by M6.** The M4 screen demonstrated the finding rather than doing the job.
It is described here as it was built, because the milestone history is the record of how
the project got where it did.

### M5: Validation and packaging
Project the forward ramp, then retrieve what actually happened and overlay the two.
Writeup, demo video, README with caveats stated up front.

**Exit:** the forecast-vs-actual overlay renders from real data. Every `[CHECK]` tag
in `constants.py` has been resolved to `[VERIFIED]` or explicitly flagged as an
open caveat in the writeup.


### M6: From a demonstration to a tool
Real entities and persistence, full CRUD, a day log that feeds actual worked minutes back
into the state, three-level master and detail navigation, and a map that selects rather
than illustrates.

**Exit:** the roster is editable and every edit re-prescribes immediately; a supervisor
can log what a worker actually did and see tomorrow's recommendation change; the seed
roster is visibly seed data and can be reset or deleted; nothing on screen explains the
demo scenario.

The plan record is no longer a panel. It is a command on the crew's command bar
that copies a plain-text record to the clipboard, which is what a supervisor does with it.

This milestone moved the per-worker maths into the browser, because an editable roster
cannot recompute anything if the model only exists in a build script. `constants.py`
remains the single source of truth: `scripts/build_js_constants.py` generates the
browser's constants from it, and `scripts/build_golden_vectors.py` plus
`tests/test_js_engine.py` fail the build if the two engines disagree beyond 1e-9 or if
the generated constants are stale.
---

## Interface principles

- **Never show the state variable on the roster.** A foreman gets minutes. `A = 0.34`
  appears only in the detail view, when he opens it asking *why*.
- **Always show the counterfactual.** Calendar says X%, model says Y%. Remove it and
  this is just another dashboard.
- **Colour by mismatch, not by temperature.** A 40 °C day with an adapted crew is
  green. A 32 °C day with four new hires is red. Every other heat dashboard colours
  by heat; this one colours by whether the plan fits the people. That inversion is
  the visual proof the product models people rather than weather.
- **Past is solid, future is dashed.** Observed and projected must never be
  visually confusable.
- The supervisor screen is used at 6 a.m., outdoors, in glare, one-handed. Design for
  that, not for a desk.

---

## Writeup: caveats to state before being asked

Volunteering these is worth more than any feature. Each pre-empts a question that
would otherwise land as a weakness.

- **"2 metres" is a measurement height, not a horizontal resolution.** Tiles are
  60-100 m. Say so.
- **Snapshot temperature is nearly flat below city scale** (~0.9 °C across a 1.2 km²
  parcel; 0.04 °C across our downtown test polygon). Exposure *duration* is what
  discriminates, hence the exceedance layer. This is why the architecture is what it is.
- **The exceedance field is interpolated rather than counted.** It can go negative and
  exceed the window. We clamp; we do not claim integer-hour precision.
- **Extremes cluster on AOI boundaries.** We buffer and discard edges. Say how.
- **τ values are tuned, not measured.** Report the sensitivity range.
- **We excluded personal physiological inputs deliberately**, and residence data
  from individual scoring, for the legal and equity reasons in `constants.py` §7.
  State this before a judge raises it.
- **Wearable competitors exist** (Kenzen, SlateSafety) and they measure current
  strain in real time via hardware. We estimate accumulated adaptation with no
  hardware, from data the employer already has. *Wearables are the smoke detector;
  this is the fire risk assessment, and it tells you which workers to put the
  expensive armbands on.*

---

## Reference files

| File | What it is |
| --- | --- |
| `constants.py` | Every physical, physiological and regulatory value, sourced and confidence-tagged |
| `FORTYGUARD_API_CONTRACT.md` | The API's verified real behaviour, including undocumented traps |
| `DESIGN_SYSTEM.md` | Visual direction, component inventory, and the lint that enforces them |
| `fixtures/` | Raw API payloads from live calls: the cache seed and regression fixtures |
| `exploration/` | Throwaway scripts used to reverse-engineer the API, reference only |

`exploration/` is not part of the codebase. Do not import from those scripts or
extend them. Everything they established is recorded in
`FORTYGUARD_API_CONTRACT.md`, which is the authority.
