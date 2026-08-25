# Acclimate

**Per-worker heat acclimatization state for construction crews, built on FortyGuard's
temperature API.**

The OSHA heat rule ramps a new worker in on a calendar: 20% of a shift on day one, 40%
on day two, up to 100% on day five. The calendar does not know what the weather was on
those days, what hours the worker was rostered, or how hard the trade is. Two men on the
same crew, same trade, same day of employment get the identical instruction whether one
worked dawn-to-noon in 31 °C or the other worked noon-to-evening in 39 °C.

Acclimate estimates each worker's **physiological adaptation state** from what they were
actually exposed to, converts it into a personal exposure limit in °C-WBGT, and
prescribes minutes per hour against that limit instead of against the calendar.

---

## The finding

Two workers. Same site, same trade, same day of employment. One rostered 05:00–13:00,
the other 10:00–18:00. That is the only difference.

| day | model's separation | the calendar says |
| --- | --- | --- |
| 2 | +0.28 °C | 40% to both |
| 4 | **+1.07 °C** | 80% to both |
| 5 | +1.33 °C | **100% to both** |
| 8 | +1.87 °C | 100% to both |
| 11 | +2.46 °C | 100% to both |
| 14 | **+2.75 °C** | 100% to both |

Psychrometric wet bulb; ISO 7243 Annex D runs +0.73 °C at day 4 to +2.08 °C at day 14.
Material and correctly signed in **84 of 84 τ pairs from day 3 onward, under both
wet-bulb methods**.

**The calendar's error compounds.** From day 5 the OSHA ramp is saturated — it issues the
identical instruction on day 5 and on day 14, because it has no term that could ever
distinguish these two men. Over those same nine days the physiological gap between them
more than doubles again.

Reproduce: `python scripts/m3_report.py`, section 6.

### What does *not* work, and why that matters

We expected site assignment to be the lever. It is not.

| lever | survives | limit gap at day 4 |
| --- | --- | --- |
| **shift timing** | **84/84 both methods** | **+1.07 °C** |
| day selection, by worked dose | 84/84 both methods | +0.63 °C |
| day selection, by peak temperature | 36/84 and 54/84 | +0.27 °C |
| site assignment, p5 vs p95 | **0/84 both methods** | +0.23 °C |

The two sites differ by **1.284×** in hours above 40 °C. That becomes **1.118×** in
worked dose, because the extra hot hours at the hot site are precisely the hours the
work/rest rule already prescribes at or near zero. **correlation(peak WBGT, worked dose)
= +0.13.** Temperature barely predicts adaptation. *Scheduling* does.

This is the single most useful thing we learned, and it reframes what a temperature API
is for here: not to find the hot place, but to price the hot *hours* against a specific
roster.

---

## Methods

### Three claims revised by our own audits

Each audit is a script in this repository. Run them.

**1. The exposure ratio was a boundary artifact.** `scripts/m3_fetch.py --exceedance`

Our first headline was a 1.84× exposure ratio between the extreme cells of the metro
grid. It was wrong. The extremes sat on the AOI boundary, where the analysis grid is
computed against truncated neighbourhoods. Buffering the AOI, discarding everything
within 500 m of the edge, and ranking by percentile instead of raw min/max gives
**1.284×**. The map draws the discarded band rather than cropping it, because the band is
part of the result.

**2. The work/rest ladder is not NIOSH's.** `scripts/audit_ladder.py`

`constants.py` carried a note to verify our ladder against "the NIOSH work/rest schedule
table". We went to check it. **There is no such table.** NIOSH 2016-106 names work/rest
scheduling as an administrative control; its tables cover acclimatization. The familiar
75/25 – 50/50 – 25/75 screening table is **ACGIH's**, it is copyrighted, and the OSHA
Technical Manual explicitly declines to reprint it.

So the ladder is **our construction**, and it decides whether a worker is told to stop.
Correct attribution now reads: exposure limits from NIOSH 2016-106 Figures 8-1 and 8-2;
rung structure the standard four-step convention, applied to a *personal* limit rather
than a fixed category — which is the product, and is why no published table could have
supplied it.

**3. Normalising by a window-dependent quantity measures your window.**
`scripts/audit_resolution.py`

Auditing what spatial structure the API carries, we compared parcel fixtures (0.8 × 1.1
km) against the metro grid (25 × 19 km) using lag-1 roughness *as a percentage of each
layer's own range*. Single instants scored ~15× rougher, and we concluded that the
14-day exceedance count was manufacturing the smoothness.

That was wrong. The absolute neighbour difference is ~0.004–0.006 °C in **both**; only
the denominator moved, because a 0.8 km window spans 0.09 °C and a 25 km window spans
1.02 °C. We retrieved a metro-extent single-hour grid to settle it. Over the identical
250 × 186 lattice a single instant and the fortnight-long count are equally smooth —
lag-1 **0.42% vs 0.40%**, blur retention **98.6% vs 98.9%**. The script now prints the
absolute column first and refuses the cross-extent comparison in its own docstring.

**4. Our own validation metric was degenerate.** `scripts/build_overlay_data.py`

The same instinct, applied to our own scoreboard. In the forecast backtest, B. Osei
scores a **perfect 7/7** on prescription band. He also demonstrates nothing: he is
prescribed zero minutes on every day of the horizon, projected and actual, so the band
*cannot* be wrong. The builder detects the case and the interface strikes the number
through with the reason on the card. A metric that cannot be wrong is not a metric — and
7/7 is exactly the number that would have looked best in this document.

### What the temperature field actually resolves

At 14:00 on a day above 40 °C, the **entire Phoenix metro spans 1.02 °C**, and
neighbouring 100 m tiles differ by 0.004 °C. Published land-surface temperature for this
city at this hour separates an irrigated park from an asphalt lot by roughly 10 °C.

These 101 m tiles do not resolve roads, parks, or the Salt River corridor. That is why
the map's locator layer is drawn from OpenStreetMap rather than inferred from the data,
and why the map prints its own effective resolution (~2 km) instead of implying tile-level
precision. It is also the physical reason site assignment fails as a lever: there is no
fine-grained spatial structure to exploit.

### Validation: forecast vs actual

The 14-day backfill is split at 2026-08-01. The ramp is built from the days before it and
projected 7 days forward; the days after are then read as ground truth. The model did not
see them when it projected.

**The prescription band was correct on 4 of 7 days.** That is what a supervisor
experiences — being told *Reduced* when the day turned out *Restricted*. Behind it: mean
absolute error 34.3 minutes of a 480-minute shift, worst day 45, adaptation-state error
−0.039 at the horizon.

**Every miss was low, and we know why.** Not a warming trend — the held-out days average
0.30 °C *cooler*, and two are hotter. Not adaptation drift — on the first projected day
both arms carry an identical state and an identical limit, and the projection is still 45
minutes low.

The cause is that `repeat_day` freezes **one day's hourly shape**, and the frozen day was
unrepresentative in exactly the band that decides a prescription:

| | copied day vs held-out mean |
| --- | --- |
| peak hour | **−0.39 °C** (cooler) — and decides nothing, already zero minutes |
| 08:00–09:00 | **+0.41 °C** (hotter) — where the ladder is actually read |

The peak is a red herring: those hours are prescribed zero for everyone. The prescription
is decided mid-morning, and because the ladder quantises in 15-minute steps, half a degree
in one decisive hour costs a full rung. Two such hours cost 45 minutes.

This is the same phenomenon as `correlation(peak WBGT, worked dose) = +0.13`, appearing
again: **peak temperature is a poor summary statistic for this product.** The fix is to
carry a real hourly forecast rather than a repeated day — Open-Meteo's regional forecast,
which `acclimatization.project()` already names in its docstring. `repeat_day` exists
because M4 needed a projection before that was wired, not because it is right.

### Sensitivity

**τ (adaptation time constants).** Swept gain 3–6 days × decay 10–21 days, 84 pairs. The
headline survives all 84 under both wet-bulb methods.

**The work/rest ladder.** Our construction, so it is sensitivity-tested rather than merely
disclosed. **Start with the cleanest case: remove the ladder entirely.** Replace the four
rungs with a continuous response — 60 min/h at the limit falling linearly to zero 4 °C
above it, no steps — and the result holds: **+1.19 °C at day 4, correct sign in 84/84 τ
pairs, both wet-bulb methods.** *The finding does not require there to be rungs.*

Across all eight variants — boundaries ±0.5 °C, three rungs, five rungs, a crude two-rung,
an aggressive three-rung, and the no-rung case — the **sign holds in 62 of 64**
ladder × method × shift × day configurations, 84/84 τ pairs each. Materiality at the
0.5 °C threshold holds in **51 of 64**; failures concentrate in a deliberately aggressive
ladder that stops work 1.5 °C above the limit, compressing every worker toward zero.

> **The comparative claim is robust to the ladder. The absolute prescription is only as
> good as the ladder, and the ladder is ours.**

**Constants.** `scripts/audit_constants.py` perturbs each `[CHECK]`-tagged constant and
re-prescribes the whole crew from raw tiles. Only **two** can move a prescription;
**ten** move nothing at all.

---

## Caveats, stated plainly

**The most prescription-sensitive constant in the file is one we set ourselves.** ISO 7243
specifies only the *longwave* emission coefficient for the black globe. Shortwave
absorptivity is a different optical property and the standard does not give it. We set it
equal to the emissivity, following Liljegren's reference implementation. Moving
`GLOBE_SOLAR_ABSORPTIVITY` by ±0.05 shifts peak WBGT by 0.24 °C and moves a worker's
prescription by **30 minutes — two full rungs**. Of every constant feeding the WBGT
composition, the one that matters most is the one that is our step rather than ISO's. That
coincidence is uncomfortable and it is the first thing we would fix with more time.

**The work/rest ladder is unvalidated against any standard**, because no applicable
standard publishes one. See Methods.

**The OSHA heat standard is PROPOSED, not law.** Enforcement is active under the General
Duty Clause and the Heat National Emphasis Program. Every prescription here uses NIOSH
RAL/REL limits; nothing in this project should be read as a claim about legal compliance.

**The forecast validation is a backtest on 7 days at one site**, not a live forecast, and
one of its two subjects is degenerate. Treat 4-of-7 as an order of magnitude, not a
performance figure.

**Natural wet bulb is assumed psychrometric.** Every result is reported under both that
and ISO 7243 Annex D; where they disagree, both numbers are given.

**`env_params` is not independent of Open-Meteo.** 14 of 15 parameters match to rounding,
so agreement between them is circular and is never presented as corroboration.

**Sixteen constants remain `[CHECK]`-tagged.** ISO 8996 and the ACGIH TLV booklet are
paywalled. `constants.py` section 0b records which are load-bearing, which were measured
as inert, and which are simply unreachable from this demo. A zero there means "cannot
affect this demo", not "correct".

**Excluded by design, permanently.** No age, sex, gender, BMI, weight, height, fitness,
medical history, medication, hydration, home address, or ethnicity. Every input is
environmental or job-assigned. This is a legal constraint on a workplace tool, not a
modelling preference, and the engine raises `ForbiddenInput` rather than ignoring such a
field.

---

## Running it

```bash
python -m pytest tests -q          # 336 tests
node scripts/check-design.mjs      # design lint
python scripts/m3_report.py        # the evidence, section 6 is the headline
python scripts/audit_ladder.py     # the ladder sensitivity
python scripts/audit_resolution.py # what the API actually resolves
python scripts/audit_constants.py  # which constants can move a prescription
```

The interface is static: open `app/index.html`. **It makes zero network calls** — every
input is a cached fixture emitted as a JavaScript module, including the OpenStreetMap
locator layer. The demo cannot fail on stage because of an API.
