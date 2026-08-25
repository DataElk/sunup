"""
Acclimate — physical, physiological and regulatory constants.

RULES FOR THIS FILE (read before editing):

  1. Every value carries a source. No exceptions.
  2. Confidence is marked on every block:
       [VERIFIED]  checked against a primary source or a live API response
       [CHECK]     from a standard we have not opened directly — must be confirmed
                   against the cited document before submission
       [TUNED]     a modelling choice, not a measured constant; it is defensible only
                   because its behaviour is stated and testable
  3. Do NOT infer, round, or "improve" a [CHECK] value from memory. Open the cited
     document, confirm, then change the tag to [VERIFIED] and note the date.
  4. Anything not in this file must not be a magic number elsewhere in the codebase.

Units are SI unless suffixed. Temperatures are °C. WBGT is °C-WBGT.
"""

from dataclasses import dataclass
from enum import Enum

# ============================================================================
# 1. METABOLIC WORKLOAD  —  ISO 8996
# ============================================================================
# [CHECK] ISO 8996:2004 "Ergonomics of the thermal environment — Determination of
#         metabolic rate", Table 1 (metabolic rate classes).
#         Values are W/m^2 of body surface area. Standard reference body surface
#         area is 1.8 m^2, so W/m^2 * 1.8 = watts total.
#         CONFIRM the class boundaries and representative values before submission.


class WorkClass(str, Enum):
    RESTING = "resting"
    LIGHT = "light"
    MODERATE = "moderate"
    HEAVY = "heavy"
    VERY_HEAVY = "very_heavy"


# Representative metabolic rate per class, W/m^2. [CHECK ISO 8996 Table 1]
METABOLIC_RATE_W_M2 = {
    WorkClass.RESTING: 65,
    WorkClass.LIGHT: 100,
    WorkClass.MODERATE: 165,
    WorkClass.HEAVY: 230,
    WorkClass.VERY_HEAVY: 290,
}

BODY_SURFACE_AREA_M2 = 1.8  # [CHECK] ISO 8996 standard reference body

# Trade -> work class. This is the ONLY question the user is asked, because a
# foreman can name his trade but cannot estimate W/m^2. The mapping is our
# judgement applied to the ISO activity examples, and it is auditable: the UI
# shows the resulting class as a caption.
TRADE_TO_WORK_CLASS = {
    "rebar":            WorkClass.HEAVY,
    "formwork":         WorkClass.HEAVY,
    "demolition":       WorkClass.HEAVY,
    "concrete":         WorkClass.MODERATE,
    "masonry":          WorkClass.MODERATE,
    "framing":          WorkClass.MODERATE,
    "carpentry":        WorkClass.MODERATE,
    "roofing":          WorkClass.MODERATE,
    "electrical":       WorkClass.LIGHT,
    "finish":           WorkClass.LIGHT,
    "inspection":       WorkClass.LIGHT,
    "layout":           WorkClass.LIGHT,
    "equipment_operator": WorkClass.LIGHT,
}


# ============================================================================
# 2. EXPOSURE LIMITS  —  NIOSH REL / RAL
# ============================================================================
# [VERIFIED 2026-08-25] NIOSH Criteria for a Recommended Standard: Occupational
#         Exposure to Heat and Hot Environments, DHHS (NIOSH) Publication
#         2016-106. RAL curves are Figure 8-1 (unacclimatized), REL curves are
#         Figure 8-2 (acclimatized).
#
# HOW THESE WERE VERIFIED. 2016-106 presents both limits GRAPHICALLY and states
# no equation. The analytic forms below are the standard representations of
# those curves, and the RAL form is attributed to NIOSH explicitly in the
# peer-reviewed literature (Ioannou et al., "Critical Assessment of the
# Recommended Alert Limit Curves for Occupational Heat Exposure", PMC12512090:
# "RAL = 59.9 - 14.1 log10 TWA-M", M in watts):
#
#     RAL = 59.9 - 14.1 * log10(M)      unacclimatized
#     REL = 56.7 - 11.5 * log10(M)      acclimatized
#
# with M the TOTAL metabolic heat production in watts -- section 1's W/m^2 value
# multiplied by BODY_SURFACE_AREA_M2. Evaluated at our four classes:
#
#     class        M (W)   RAL eq   ours    REL eq   ours
#     light          180    28.10   28.0     30.76   30.0
#     moderate       297    25.03   25.0     28.26   28.0
#     heavy          414    23.00   22.5     26.60   26.0
#     very_heavy     522    21.58   21.5     25.45   25.0
#
# Every stored value sits BELOW the curve, by 0.03-0.76 degC. The rounding is
# always toward more protection, never less, which is the only direction a
# rounding error is acceptable in.
#
# ATTRIBUTION CAVEAT, and it is a real one. The same coefficient pair
# (56.7/11.5, 59.9/14.1) is widely published as the ACGIH TLV and Action Limit.
# NIOSH's REL/RAL and ACGIH's TLV/AL are separate documents that happen to share
# these analytic forms. Our values are consistent with both. The writeup says
# "NIOSH RAL/REL" because that is the framing and the figure numbers we checked
# against; it should not be read as a claim that ACGIH would give a different
# number here.
#
# Values below are degC-WBGT for CONTINUOUS work.

WBGT_LIMIT_ACCLIMATIZED = {      # NIOSH REL
    WorkClass.LIGHT:    30.0,
    WorkClass.MODERATE: 28.0,
    WorkClass.HEAVY:    26.0,
    WorkClass.VERY_HEAVY: 25.0,
}

WBGT_LIMIT_UNACCLIMATIZED = {    # NIOSH RAL
    WorkClass.LIGHT:    28.0,
    WorkClass.MODERATE: 25.0,
    WorkClass.HEAVY:    22.5,
    WorkClass.VERY_HEAVY: 21.5,
}

# Work/rest allocation as a function of how far the environment exceeds the
# worker's personal limit.
#
# [RESOLVED 2026-08-25 — AND THE ORIGINAL PREMISE WAS WRONG]
#
# This block used to say "[CHECK] against the NIOSH work/rest schedule table".
# There is no such table. NIOSH 2016-106 was read for it: work/rest scheduling
# appears only as a named administrative control, and the document's tables
# cover acclimatization schedules (Table 4-1), not WBGT-versus-regimen
# screening. The familiar 75/25 - 50/50 - 25/75 screening table is ACGIH's, from
# the TLVs and BEIs booklet, and ACGIH's heat stress material is copyrighted and
# not publicly reproducible (OSHA Technical Manual III:4 says so explicitly and
# declines to reprint it).
#
# So this ladder is OUR CONSTRUCTION. It is not a standard, it is not NIOSH, and
# it must never be presented as either. What it borrows from ACGIH is only the
# STRUCTURE that everyone uses -- four rungs at 60/45/30/15 minutes of work per
# hour -- applied to a different independent variable: degrees above THIS
# worker's personal limit, rather than absolute WBGT against a fixed category.
# That substitution is the whole product, and it means no published table could
# have supplied these numbers.
#
# Load-bearing: this ladder alone decides whether a worker is told to stop.
# Treat it as the model's largest unvalidated assumption and say so in the
# writeup.
#
# Format: (max_excess_degC_above_personal_limit, work_min_per_hour)
WORK_REST_LADDER = [
    (0.0, 60),   # at or below limit: continuous work
    (1.0, 45),   # 75/25
    (2.0, 30),   # 50/50
    (3.0, 15),   # 25/75
]
WORK_REST_STOP = 0  # beyond the ladder: no work at this intensity


# ============================================================================
# 3. ACCLIMATIZATION DYNAMICS
# ============================================================================
# The state model:
#     A(t+1) = A + s * (1 - A) / TAU_GAIN  -  (1 - s) * A / TAU_DECAY
# with A in [0, 1] and s the normalised daily adaptive stimulus in [0, 1].
#
# [TUNED] TAU_GAIN and TAU_DECAY are modelling choices calibrated so the model
#         reproduces the two things the literature and the regulator agree on:
#
#   TAU_GAIN = 4.0 days
#       Reproduces ~75-80% of adaptation by day 4-5 and near-complete adaptation
#       by day 10-14, which is the consensus range in the heat acclimatization
#       literature (Périard et al., and the acclimatization discussion in the
#       NIOSH criteria document). [CHECK the exact percentages you quote.]
#
#   TAU_DECAY = 13.0 days
#       Gives A ~ 0.34 retained after 14 days of zero stimulus, consistent with
#       OSHA and NIOSH treating an absence of 14 days as requiring full
#       re-acclimatization. [CHECK the OSHA absence threshold — the proposed rule
#       and the existing NIOSH guidance may state different numbers of days.]
#
# The 3x asymmetry (gain faster than decay) is the physiologically important
# property: adaptation is earned in days and lost over weeks. If you re-tune,
# preserve the asymmetry.
#
# SENSITIVITY: report results across TAU_GAIN in [3, 6] and TAU_DECAY in [10, 21].
# A conclusion that only holds at one parameter set is not a conclusion.

TAU_GAIN_DAYS = 4.0
TAU_DECAY_DAYS = 13.0

A_MIN, A_MAX = 0.0, 1.0

# Stimulus normalisation. s = 1 on a day that delivers a full adaptation stimulus.
# [TUNED] Standard exertional heat acclimatization protocols use roughly 90-100
#         minutes of exercise in heat sufficient to raise core temperature ~1 °C.
#         We express the daily dose as degree-hours above the worker's personal
#         limit and normalise by DEGREE_HOURS_FULL_STIMULUS.
#         [CHECK] the protocol duration you cite.
DEGREE_HOURS_FULL_STIMULUS = 6.0   # °C-WBGT * hours above personal limit

# ############################################################################
# [RESOLVED 2026-08-24 — M2] THE CONSTANT WAS NEVER THE PROBLEM.
# ############################################################################
# The first M2 run found s pinned at 1.000 on every real Phoenix shift. Measured
# degree-hours over the 05:00-13:00 demo shift, moderate work, on the four
# site-days with cached FortyGuard tiles:
#
#     2024-07-15   19.76   ->  s = 1.000
#     2026-08-05   28.63   ->  s = 1.000
#     2026-08-09   29.23   ->  s = 1.000
#     2026-07-26   37.62   ->  s = 1.000
#
# With s = 1 for every worker every day the state update collapses to
#
#     A(t+1) = A + (1 - A)/TAU_GAIN
#
# a function of DAYS ELAPSED and nothing else — precisely the calendar the
# product exists to replace. Two workers with a 1.9x difference in measured heat
# dose received identical schedules.
#
# THE FIX WAS NOT TO RE-TUNE THIS NUMBER. 6.0 has a physiological meaning (the
# dose of a standard exertional acclimatization session) and re-scaling it to
# make a demo work is exactly the failure mode this file exists to prevent. The
# saturation was a symptom; the cause was that the stimulus was integrating the
# wrong thing. Section 3a records the corrected integrand.
#
# After the correction, on the same four site-days and the same 6.0:
#
#     unadapted (A=0)   0.66 .. 1.97 degC*h   ->  s = 0.11 .. 0.33
#
# No day saturates in any real ramp, under either wet-bulb method.

# Below this, a day contributes no adaptation at all.
STIMULUS_FLOOR_DEG = 0.0


# ----------------------------------------------------------------------------
# 3a. WHAT THE STIMULUS INTEGRATES  —  corrected 2026-08-24
# ----------------------------------------------------------------------------
# DEGREE_HOURS_FULL_STIMULUS stays at 6.0. What changed is the integrand, and
# the reason is that the first definition was wrong twice over.
#
#     dose = SUM over shift hours of  max(WBGTeff - RAL, 0) * (minutes worked / 60)
#
# CHANGE 1 — the threshold is the FIXED RAL for the workload class, not the
# worker's moving personal limit.
#
#   Integrating above the moving limit is circular. As a worker adapts his limit
#   rises, so the same weather yields fewer degree-hours, so he accumulates less
#   dose than an unadapted man standing beside him in identical conditions. That
#   is backwards: the environment does not know how adapted anyone is. Heat dose
#   is a property of the weather and the exposure, not of the person.
#
#   The personal limit still does real work — it sets the SCHEDULE. It just no
#   longer sets the threshold for measuring dose.
#
# CHANGE 2 — only hours ACTUALLY WORKED count, weighted by the prescribed duty
# cycle.
#
#   An hour spent resting in shade produces no adaptive stimulus. An hour
#   prescribed at 15 min/h therefore contributes a quarter of its degree-hours,
#   and an hour prescribed at 0 contributes nothing at all.
#
# WHAT THIS FIXED, measured over the 05:00-13:00 shift, moderate work, on the
# four site-days with cached FortyGuard tiles:
#
#     definition                       degree-hours       s at A=0
#     above moving limit, unweighted   19.76 .. 37.62     1.000 (all saturated)
#     above fixed RAL, duty-weighted    0.66 ..  1.97     0.110 .. 0.329
#
#   Saturation is gone from the range where it mattered. Across four real ramps
#   NO day saturates: s stays inside 0.11-0.59. Saturation only returns above
#   A ~ 0.55-0.90, where it is harmless because A is already near its ceiling
#   and s = 1 simply holds it there.
#
# A FEEDBACK LOOP THIS INTRODUCES, DELIBERATELY. The schedule depends on
# adaptation, so dose now depends on adaptation — but in the physically correct
# direction: a more adapted worker is cleared for more minutes, so he
# accumulates MORE dose. Gain, not loss. It is also self-limiting, because the
# hottest hours are exactly the ones prescribed at zero.
#
# THE UNCOMFORTABLE CONSEQUENCE, which the product must confront rather than
# bury: under this definition HOTTER DAYS CAN PRODUCE LESS ADAPTATION, because
# the protective schedule removes the exposure that would have adapted the
# worker. A 10:00-18:00 shift in Phoenix is prescribed zero minutes in every
# hour, so that worker never acclimatizes at all. The safety schedule is
# self-defeating for acclimatization.
#
#   That is not a modelling artefact. It is a real trade-off in every heat
#   standard that combines a ramp with a work/rest rule, and the model now
#   surfaces it. `Divergence.inverted` reports when the environmentally hotter
#   arm ended up the LESS adapted worker.
#
# CONSEQUENTLY: report the PERSONAL LIMIT in degC-WBGT as the primary divergence
# metric. It is continuous and monotone in accumulated dose. The prescription in
# minutes is quantised into 15-minute rungs of the NIOSH ladder, so whether a
# real separation shows up as a different instruction depends on where the
# worker happens to fall relative to a rung boundary. Limits first, minutes
# second, and never minutes alone.

# SPEC.md M2 requires the divergence to survive these ranges.
TAU_GAIN_SENSITIVITY_RANGE = (3.0, 6.0)
TAU_DECAY_SENSITIVITY_RANGE = (10.0, 21.0)

# One rung of WORK_REST_LADDER is 15 minutes per hour. A difference smaller than
# a rung is not a different instruction to a supervisor, so it does not count as
# a divergence however pleasing the decimals look.
MATERIAL_DIVERGENCE_MIN_PER_HOUR = 15

# The PRIMARY divergence metric is the personal limit in degC-WBGT, because it
# is continuous and monotone in accumulated dose while the prescription is
# quantised into 15-minute rungs. [TUNED] 0.25 degC is a quarter of the 3.0 degC
# span between RAL and REL for moderate work — a separation that would move a
# worker an eighth of the way along the NIOSH scale is not noise.
MATERIAL_LIMIT_GAP_C = 0.25




# ----------------------------------------------------------------------------
# 3b. CONTROLLED ACCLIMATIZATION IS AN OPTIMIZATION
# ----------------------------------------------------------------------------
# Section 3a records that the protective schedule removes the exposure that
# would have adapted the worker, so hotter conditions can produce LESS
# adaptation. Read that as a bug and it is depressing. Read it correctly and it
# is the most valuable thing the model does.
#
# It means acclimatization is not something that happens TO a worker as a
# by-product of the calendar. It is a CONTROL PROBLEM with a real optimum:
#
#     maximise   dA/dt          the rate the worker adapts
#     subject to strain <= ceiling   nobody is put at risk of heat illness
#     choosing   shift start, shift length, site assignment, work/rest schedule
#
# Both extremes lose. Work a new hire through the afternoon peak and the
# work/rest rule prescribes zero minutes: maximum protection, zero adaptation,
# and he is still unadapted on day 14. Work him only in the cool of the morning
# and he never crosses the RAL: also zero adaptation. The fastest safe ramp sits
# between them, and [MEASURED 2026-08-24, scripts/m3_report.py] it is a genuine
# interior maximum — for moderate work on the 05:00-13:00 shift the peak sits
# around 3 degC BELOW the measured Phoenix August day, and adaptation falls away
# on both sides.
#
# A CALENDAR CANNOT COMPUTE THIS. OSHA's "20% on day one, +20% per day" has no
# term for temperature, for shift timing, or for which site a man was sent to.
# It cannot tell you that moving a crew's start time forward by two hours would
# halve their ramp, because it does not know what the heat was. The model can,
# because it carries the two things the calendar lacks: a measured dose and a
# state that integrates it.
#
# WHAT THIS CHANGES ABOUT THE PRODUCT'S CLAIM. The pitch is not only "we can
# tell you this man is not as adapted as the calendar thinks". It is:
#
#     "Here is the schedule that gets him adapted fastest without exceeding the
#      strain ceiling — and here is how many days it saves."
#
# That is a scheduling recommendation an employer can act on, not just a warning
# they have to absorb. It also reframes the inversion finding from an awkward
# caveat into the reason the optimum exists at all.
#
# [NOT YET BUILT] The optimiser itself is not in M2 or M3. What exists is the
# diagnostic that proves the optimum is real and interior
# (diagnostics.weather_history_sweep) plus everything needed to evaluate a
# candidate schedule. Building the search is a natural M4/M5 addition; do not
# claim it is implemented until it is.
#
# THE STRAIN CEILING IS THE PART TO GET RIGHT. "Fastest ramp" without a
# constraint is just "work him in the hottest hours", which is how people die.
# The ceiling must be the NIOSH work/rest ladder at the worker's CURRENT
# personal limit, evaluated hour by hour — never a daily average, because a
# daily average hides the 14:00 peak that does the damage.


# ============================================================================
# 4. CLOTHING ADJUSTMENT  —  ACGIH CAV
# ============================================================================
# [CHECK] ACGIH TLVs and BEIs booklet, Heat Stress and Strain, clothing
#         adjustment factor table. Values are ADDED to measured WBGT (i.e. they
#         effectively lower the allowable environment).
#         THE TABLE HAS BEEN REVISED ACROSS EDITIONS — cite the edition you used.
#
# Most construction is baseline work clothes (0.0), so this is a crew setting
# that stays invisible by default. The extreme values matter enormously: a
# vapour-barrier coverall adjustment can dominate every other term in the model.

CLOTHING_ADJUSTMENT_C = {
    "work_clothes":            0.0,   # long-sleeve shirt and trousers — baseline
    "coveralls":               0.0,   # [CHECK] some editions list +0
    "double_layer_woven":      3.0,   # [CHECK]
    "sms_polypropylene":       0.5,   # [CHECK]
    "polyolefin_coveralls":    1.0,   # [CHECK]
    "vapor_barrier_limited":  11.0,   # [CHECK] — large; verify before quoting
}


# ============================================================================
# 5. WBGT COMPUTATION
# ============================================================================
# Outdoor with solar load (ISO 7243):
#     WBGT = 0.7 * T_nwb + 0.2 * T_globe + 0.1 * T_dry
# Indoor / no solar load:
#     WBGT = 0.7 * T_nwb + 0.3 * T_globe
#
# [VERIFIED against live API 2026-08-23] Input sources:
#   T_dry   : FortyGuard /v1/heatmap, properties.average_temperature (°C)
#   T_nwb   : FortyGuard /v1/env_params, wet_bulb_temperature_celsius (24 hourly)
#             NOTE: this is psychrometric wet bulb, NOT natural wet bulb. They
#             differ. [CHECK] whether to apply a correction, and say which you used.
#   T_globe : NOT PROVIDED by either API. Must be estimated from solar irradiance
#             and wind speed. Use the Liljegren et al. (2008) formulation
#             ("Modeling the Wet Bulb Globe Temperature Using Standard
#             Meteorological Measurements", J. Occup. Environ. Hyg.) or state
#             clearly which simpler approximation you substituted.
#   solar   : FortyGuard returns only a DAILY clear-sky mean. Hourly shortwave
#             radiation must come from Open-Meteo.
#   wind    : NOT AVAILABLE from FortyGuard at all. Open-Meteo only.

# [VERIFIED 2026-08-24 against ISO 7243:2017(E) Clause 5, Formulae (1) and (2)]
#   without solar load:  WBGT = 0,7 t_nw + 0,3 t_g          Formula (1)
#   with solar load:     WBGT = 0,7 t_nw + 0,2 t_g + 0,1 t_a Formula (2)
# Independently corroborated: ISO Table D.1's WBGT column only reproduces with
# Formula (1) — the outdoor form is out by up to 3,4 degC on those rows. See
# tests/test_natural_wet_bulb.py.
WBGT_OUTDOOR_WEIGHTS = (0.7, 0.2, 0.1)   # (nwb, globe, dry)
WBGT_INDOOR_WEIGHTS = (0.7, 0.3, 0.0)

# Sanity band. Any computed WBGT outside this is a bug, not weather.
WBGT_PLAUSIBLE_MIN, WBGT_PLAUSIBLE_MAX = -20.0, 45.0

# [VERIFIED] Worked reference, downtown Phoenix 2024-07-15 14:00, from live API:
#   T_dry 39.7 °C, T_wb 23.7 °C, RH 22.9%  ->  WBGT ~ 31 °C
#   At 06:00 the same day: T_wb 22.0 °C, weak solar  ->  WBGT ~ 24.8 °C
# The day therefore crosses BOTH the RAL and REL curves for moderate work.
# Use this as the regression fixture for the WBGT pipeline.

# Reference targets, machine-readable so the M1 exit test cannot drift from the
# prose above.
WBGT_REFERENCE_SITE = {"latitude": 33.4484, "longitude": -112.0740}
WBGT_REFERENCE_DATE = "2024-07-15"
WBGT_REFERENCE_HOURS_C = {14: 31.0, 6: 24.8}
WBGT_REFERENCE_TOLERANCE_C = 1.0


# ----------------------------------------------------------------------------
# 5a. BLACK GLOBE TEMPERATURE  —  T_globe is measured by neither API
# ----------------------------------------------------------------------------
# Section 5 requires either Liljegren et al. (2008) or an explicitly stated
# simpler substitution. WE SUBSTITUTED. What we solve is the steady-state energy
# balance of a standard 150 mm black globe:
#
#   alpha_g * S_sphere  +  eps_g * sigma * (F * Ta^4 - Tg^4)  -  h_c * (Tg - Ta) = 0
#
# with the longwave environment factor, sky above and ground below at view
# factor 0.5 each, the ground both emitting and reflecting downwelling sky
# longwave:
#
#   F = 0.5 * (eps_sky + eps_grd + (1 - eps_grd) * eps_sky)
#
# Under overcast (eps_sky = 1) this is exactly 1, so with no sun the globe sits
# exactly at air temperature. Dropping the reflected term — easy to do, and we
# did at first — costs about 0.5 degC of globe temperature on an overcast night.
#
# where S_sphere is shortwave irradiance averaged over the whole sphere surface.
# That average follows from geometry alone, not from a fitted constant:
#   - a collimated beam of intensity DNI presents pi*r^2 of a 4*pi*r^2 sphere
#     -> DNI / 4
#   - an isotropic hemisphere (sky) has view factor 0.5 -> DHI / 2
#   - ground-reflected shortwave, view factor 0.5       -> albedo * GHI / 2
#
# DIFFERENCES FROM LILJEGREN, stated so the writeup can state them:
#   1. Ground surface temperature is taken as air temperature. Liljegren does
#      the same; real asphalt at 14:00 is far hotter, so this UNDER-estimates
#      the globe, hence WBGT. Conservative direction, but a bias.
#   2. Liljegren also models the natural wet bulb thermometer. We do not — we
#      take FortyGuard psychrometric wet bulb directly (see 5b).
#   3. No correction for globe thermal mass / non-steady state.
#
# [VERIFIED 2026-08-24 against ISO 7243:2017(E) Annex B.2, which specifies the
#  globe normatively:
#     a) diameter: 150 mm.
#     b) mean emission coefficient: 0,95 (matte black globe);
#  A secondary source claimed 0,97 — it is wrong. The standard says 0,95.]
GLOBE_DIAMETER_M = 0.15            # [VERIFIED] ISO 7243:2017 Annex B.2 a)
GLOBE_EMISSIVITY = 0.95            # [VERIFIED] ISO 7243:2017 Annex B.2 b)

# [CHECK] ISO 7243 specifies only the LONGWAVE emission coefficient. Shortwave
#         absorptivity is a different optical property and the standard does not
#         give it. We set it equal to the emissivity, which is what Liljegren's
#         reference implementation does (its ALB_GLOBE is 0.05, i.e. absorptivity
#         0.95). Defensible for matte black paint, but it is our step, not ISO's.
GLOBE_SOLAR_ABSORPTIVITY = 0.95

# [CHECK] No primary source opened. Typical for built surfaces; the globe balance
#         is weakly sensitive to it because the ground term is halved by the view
#         factor and largely cancels against the sky term.
GROUND_EMISSIVITY = 0.95

# [CHECK] Typical urban albedo. Sensitivity is small and measured, not asserted:
#         across 0.10-0.30 the downtown Phoenix 14:00 WBGT moves 30.66 -> 31.39,
#         i.e. 0.18 degC per 0.05 of albedo. Reported by scripts/m1_report.py so
#         the number is never taken on trust.
GROUND_ALBEDO = 0.20

# [VERIFIED] Exact by definition since the 2019 SI redefinition of the kelvin.
#            CODATA: sigma = 5.670374419...e-8 W m^-2 K^-4.
STEFAN_BOLTZMANN = 5.670374419e-8

# Convection from a sphere in cross flow:
#   Nu = 2 + 0.6 * Re^0.5 * Pr^(1/3)
#
# [VERIFIED 2026-08-24 against Liljegren's own reference implementation
#  (github.com/mdljts/wbgt, src/wbgt.c, h_sphere_in_air), which computes
#     Nu = 2.0 + 0.6 * sqrt(Re) * pow(Pr,0.3333)
#  and cites it in-source as "Bird, Stewart, and Lightfoot (BSL), page 409".]
#
# NOTE ON ATTRIBUTION: this is the Ranz & Marshall (1952) correlation, but
# Liljegren cites it via BSL (Transport Phenomena) p.409. Cite BSL in the
# writeup, since that is the chain we actually verified.
RANZ_MARSHALL_A = 2.0     # [VERIFIED] conduction limit for a sphere, Nu -> 2
RANZ_MARSHALL_B = 0.6     # [VERIFIED]

# At zero wind the forced-convection correlation collapses to Nu = 2 and the
# globe runs implausibly hot. Real globes are ventilated by free convection.
# [TUNED] We floor the air speed rather than add a free-convection branch, and
#         say so. 0.5 m/s is below any measured urban daytime mean, so the floor
#         only binds on calm nights, where the solar load is zero anyway.
MIN_AIR_SPEED_M_S = 0.5

# Air properties. Dynamic viscosity via Sutherland's law. [CHECK] — no primary
# source opened for these five. They enter only through the convective
# coefficient h = Nu*k/D, and the measured wind sensitivity below shows the whole
# h term is worth well under 1 degC across a 20x range of wind, so a few percent
# on k or nu is not a decisive error. Verify before submission anyway.
AIR_SUTHERLAND_MU0_PA_S = 1.716e-5
AIR_SUTHERLAND_T0_K = 273.15
AIR_SUTHERLAND_S_K = 110.4
AIR_GAS_CONSTANT_J_KG_K = 287.05        # [CHECK] dry air
AIR_PRANDTL = 0.71                      # [CHECK] weakly temperature-dependent
AIR_CONDUCTIVITY_REF_W_M_K = 0.02624    # [CHECK] at 300 K
AIR_CONDUCTIVITY_REF_T_K = 300.0
AIR_CONDUCTIVITY_EXPONENT = 0.8646      # [CHECK] k(T) = k_ref * (T/T_ref)^n

# International Standard Atmosphere pressure vs geometric height. [CHECK]
ISA_SEA_LEVEL_PRESSURE_PA = 101325.0
ISA_LAPSE_COEFF = 2.25577e-5
ISA_LAPSE_EXPONENT = 5.25588


# ----------------------------------------------------------------------------
# 5b. NATURAL WET BULB  —  SETTLED 2026-08-24
# ----------------------------------------------------------------------------
# DECISION: the default is the PSYCHROMETRIC value FortyGuard returns, used
# unmodified as if it were the natural wet bulb. Settled by the project owner.
# ISO 7243:2017 Annex D remains implemented and selectable (see §5g); it is not
# the default, and nothing switches silently.
#
# THE FACTS BEHIND THE DECISION, so it can be defended rather than just asserted.
#
# 1. They are genuinely different instruments. ISO 7243:2017 Annex B.1:
#
#       "The natural wet bulb temperature is thus different from the
#        thermo-dynamic temperature determined with a psychrometer."
#
#    So this is a real approximation, not a naming quibble. Say so in the writeup.
#
# 2. ISO gives a conversion, and we implemented it. Annex D Formulae (D.1)/(D.2)
#    reproduce all 22 rows of the standard's own Table D.1 to within 0.50 °C
#    (tests/test_natural_wet_bulb.py). The implementation is not in doubt.
#
# 3. ISO does not trust it here, and neither should we. Annex D's own preamble:
#    the calculation "is neither simple nor reliable, especially when air
#    velocity is low ... It is not recommended". Table D.1 is tabulated only to
#    0,9 m/s; downtown Phoenix runs ~3,3 m/s at 14:00, so 23 of 24 hours fall
#    outside the domain ISO validates. The pipeline flags every such hour.
#
# 4. The §5 reference cannot arbitrate, because it shares our assumption. The
#    ≈31 °C was hand-computed using the psychrometric value in the 0.7 term. So
#    "psychrometric reproduces the reference and Annex D does not" is NOT
#    evidence that psychrometric is right — it is evidence they agree. SPEC.md's
#    M1 exit criterion now states this explicitly.
#
# WHAT THIS COSTS, stated plainly because it is the one bias that runs the wrong
# way. A sunlit wick absorbs radiation a shielded psychrometer does not, so the
# natural wet bulb reads HIGHER. Using the psychrometric value therefore
# UNDER-reads WBGT, which UNDER-reads heat stress. Every other simplification in
# this pipeline errs toward restricting work; this one errs toward permitting it.
# Measured on the reference site-day, Annex D would raise 14:00 by 1.10 °C.
#
# HOW THE PROJECT STAYS HONEST ABOUT IT:
#   - the choice is recorded in every day's provenance and listed under
#     `assumed_inputs`, so no result can be mistaken for a measurement;
#   - SPEC.md M2's exit test requires the two-worker divergence to survive BOTH
#     methods. If the headline claim only holds under one, it is an artifact of
#     that method and the claim is withdrawn;
#   - the writeup states the direction of the bias before a judge asks.
#
# Selectable at the call site: wbgt.NWB_PSYCHROMETRIC (default) or
# wbgt.NWB_ISO_ANNEX_D.


# ----------------------------------------------------------------------------
# 5c. HOURLY SOLAR — reconstructed, because no API gives it offline
# ----------------------------------------------------------------------------
# FortyGuard /v1/env_params returns ONE daily clear-sky mean (ghi/dni/dhi), not
# 24 values (FORTYGUARD_API_CONTRACT.md section 6, trap 1). Open-Meteo has the
# hourly field but no fixture is cached yet. So the hourly curve is computed from
# solar geometry and then ANCHORED to FortyGuard: the clear-sky GHI curve is
# scaled by a single factor so its own daylight-hours mean equals the value
# FortyGuard reported for that site-day.
#
# The shape is astronomy (exact); the level is FortyGuard (measured). Nothing
# here is a free parameter.
#
# Solar position: NOAA Global Monitoring Laboratory solar calculator equations.
# [VERIFIED 2026-08-24 against NOAA GML "General Solar Position Calculations"
#  (solareqns.PDF). Fractional year, equation of time, declination, true solar
#  time, hour angle and zenith all match coefficient for coefficient.
#  CONVENTION NOTE: NOAA writes time_offset = eqtime - 4*longitude + 60*timezone
#  with longitude and timezone POSITIVE WEST (it gives MST = +7). We use
#  positive EAST for both (-112.074, -7), so ours reads
#  time_offset = eqtime + 4*longitude - 60*timezone. Algebraically identical;
#  the double sign flip cancels. Empirically confirmed: the model puts Phoenix
#  solar noon at 12:34 local, sunrise 05:33, sunset 19:35 on 2024-07-15.]

# [CHECK] The modern best estimate of total solar irradiance is 1361 W/m^2
#         (Kopp & Lean 2011), not 1367. We keep 1367 because the Meinel DNI
#         formulation below was fitted against the older value, and because this
#         constant only scales the beam/diffuse SPLIT of a GHI curve that is
#         already anchored to FortyGuard. Revisit if DNI is ever used directly.
SOLAR_CONSTANT_W_M2 = 1367.0

# Haurwitz (1945) clear-sky global horizontal model:
#   GHI = 1098 * cos(z) * exp(-0.059 / cos(z))
# [VERIFIED 2026-08-24 against the pvlib-python reference implementation
#  (pvlib.clearsky.haurwitz), whose source line is
#     clearsky_ghi = 1098.0 * cos_zenith * np.exp(-0.059/cos_zenith)
#  citing B. Haurwitz, "Insolation in Relation to Cloudiness and Cloud Density",
#  Journal of Meteorology 2:154-166, 1945, and Reno, Hansen & Stein, "Global
#  Horizontal Irradiance Clear Sky Models", Sandia SAND2012-2389, 2012.]
HAURWITZ_A = 1098.0
HAURWITZ_B = 0.059

# Meinel & Meinel (1976) clear-sky direct normal model:
#   DNI = SOLAR_CONSTANT * 0.7 ^ (AM ^ 0.678),  AM = 1 / cos(z)
# [VERIFIED 2026-08-24 — but against SECONDARY sources only (PVEducation and the
#  clear-sky model literature, which reproduce it as DNI = I0 * 0.7^(AM^0.678)
#  and attribute it to Meinel, A.B. & Meinel, M.P., "Applied Solar Energy: An
#  Introduction", Addison-Wesley, 1976). The 1976 book itself was not opened.
#  This is the weakest citation in section 5c; it is also the least consequential,
#  because it only splits an already-anchored GHI into beam and diffuse.]
MEINEL_TAU = 0.7
MEINEL_AM_EXPONENT = 0.678

# Below this solar elevation the irradiance is treated as zero. [TUNED]
MIN_SOLAR_ELEVATION_DEG = 0.0

# Kasten & Czeplak (1980) cloud attenuation of global irradiance:
#   GHI / GHI_clear = 1 - 0.75 * (N/8)^3.4,  N = cloud cover in OCTAS (0-8)
# [VERIFIED 2026-08-24. Kasten, F. & Czeplak, G., "Solar and terrestrial
#  radiation dependent on the amount and type of cloud", Solar Energy 24(2):
#  177-189, 1980. Derived from 10 years of hourly data at Hamburg.]
# We pass cloud as a FRACTION (N/8 already applied), so the code reads
# 1 - 0.75 * c^3.4 with c in [0,1] — algebraically the same expression.
KASTEN_CZEPLAK_A = 0.75
KASTEN_CZEPLAK_EXPONENT = 3.4

# [TUNED] Beam attenuation under cloud. We assume the direct beam survives in
# proportion to the clear fraction, DNI_allsky = DNI_clear * (1 - C), and take
# diffuse as the remainder needed to close GHI = DNI*cos(z) + DHI. Both
# endpoints are exact by construction (C=0 -> clear sky; C=1 -> fully diffuse);
# only the interior is an assumption.
BEAM_SURVIVES_LINEARLY_IN_CLEAR_FRACTION = True


# ----------------------------------------------------------------------------
# 5d. WIND — available from NEITHER API. The pipeline weakest input.
# ----------------------------------------------------------------------------
# Section 5 already records it: "wind: NOT AVAILABLE from FortyGuard at all.
# Open-Meteo only." No Open-Meteo fixture is cached, so offline runs use an
# assumed constant. THIS IS TAGGED IN THE PROVENANCE OF EVERY RESULT — a run on
# assumed wind can never be mistaken for a run on retrieved wind.
#
# [RESOLVED 2026-08-24] An Open-Meteo fixture now exists for the reference
# site-day, so wind is MEASURED there and the default below is used only where
# no Open-Meteo coverage is cached. Which one a given result used is recorded in
# that day's provenance and must never be inferred.
#
# The assumption held up well. Measured 2024-07-15 downtown Phoenix, after the
# 10 m -> 2 m log-profile conversion:
#     min 0.53   mean 2.81   max 4.68 m/s      (06:00 1.42, 14:00 3.28)
# against the 3.0 m/s that was assumed. Swapping the assumption for the measured
# series moves WBGT at 14:00 by 0.07 degC, so the earlier offline result was not
# luck — pinned by test_measured_wind_did_not_rescue_a_broken_model.
DEFAULT_WIND_SPEED_M_S = 3.0

# The band of plausible daytime 2 m wind speeds the writeup reports over.
WIND_SENSITIVITY_BAND_M_S = (1.0, 8.0)

# [MEASURED 2026-08-24, scripts/m1_report.py] The sub-band over which the M1
# reference in section 5 actually reproduces to within +/-1 degC. It is NARROWER
# than the plausible band above, and that gap is a real limitation, not a
# rounding detail:
#
#   0.5 m/s -> 14:00 reads 32.69 degC (+1.69 over the reference)
#   1.0 m/s -> 14:00 reads 32.08 degC (+1.08)
#   1.5 m/s -> 14:00 reads 31.71 degC (+0.71)  <- gate reopens here
#   3.0 m/s -> 14:00 reads 31.12 degC (+0.12)  <- the assumed default
#  10.0 m/s -> 14:00 reads 30.24 degC (-0.76)
#
# So on a near-calm afternoon the pipeline over-reads WBGT by up to 1.7 degC.
# That errs toward restricting work rather than permitting it, which is the safe
# direction, but it is an error. It disappears the moment a real wind series is
# cached — see the Open-Meteo call in sources/openmeteo.py.
WIND_BAND_REPRODUCING_REFERENCE_M_S = (1.5, 10.0)

# Wind is reported at 10 m; the globe sits at roughly 2 m. Logarithmic wind
# profile, v(z) = v_ref * ln(z/z0) / ln(z_ref/z0). [CHECK] the roughness length
# for built-up terrain against a boundary-layer reference.
WIND_MEASUREMENT_HEIGHT_M = 10.0
GLOBE_HEIGHT_M = 2.0
SURFACE_ROUGHNESS_LENGTH_M = 0.1   # [CHECK] suburban / built-up


# ----------------------------------------------------------------------------
# 5e. LONGWAVE SKY EMISSIVITY AND VAPOUR PRESSURE
# ----------------------------------------------------------------------------
# Brutsaert (1975), clear-sky atmospheric emissivity from screen-level vapour
# pressure:  eps_cs = 1.24 * (e_a / T_a) ^ (1/7),  e_a in mbar, T_a in K
# [VERIFIED 2026-08-24. Brutsaert, W., "On a derivable formula for long-wave
#  radiation from clear skies", Water Resources Research 11(5):742-744, 1975,
#  doi:10.1029/WR011i005p00742. mbar == hPa, which is the unit we convert to.]
#
# NOTE: Liljegren's implementation uses a DIFFERENT sky emissivity form,
# 0.575 * e^0.143, attributed in-source to Oke. Ours is Brutsaert and is cited
# as Brutsaert. Do not describe the radiation scheme as "Liljegren's".
#
# Cloud raises emissivity toward unity in proportion to cover — our step, and
# exact at both endpoints (clear -> Brutsaert, overcast -> 1).
BRUTSAERT_A = 1.24
BRUTSAERT_EXPONENT = 1.0 / 7.0

# Tetens saturation vapour pressure over water, kPa, T in degC:
#   e_s = 0.6108 * exp(17.27 * T / (T + 237.3))
# [VERIFIED 2026-08-24. Tetens, O., "Uber einige meteorologische Begriffe",
#  Zeitschrift fur Geophysik 6:297-309, 1930, as reproduced in FAO Irrigation and
#  Drainage Paper 56 (Allen et al. 1998) Equation 11. Monteith & Unsworth note
#  values are within 1 Pa of exact up to 35 degC.
#  The primary form is sometimes written 0.61078; FAO-56 rounds to 0.6108. The
#  difference is 2e-5 kPa and we use the FAO-56 value.]
MAGNUS_A_KPA = 0.6108
MAGNUS_B = 17.27
MAGNUS_C = 237.3


# ----------------------------------------------------------------------------
# 5f. HOURLY DRY BULB RECONSTRUCTION
# ----------------------------------------------------------------------------
# FortyGuard filter_type=3 gives THREE numbers per cell for the whole day: min,
# mean and max (FORTYGUARD_API_CONTRACT.md section 4 — these are the TEMPORAL
# axis, not the spatial one). A separate source supplies the diurnal SHAPE.
# FortyGuard sets amplitude and offset; the shape provider sets shape.
#
# A shape mapped linearly onto [min, max] honours two of the three numbers and
# silently discards the third. We keep the third by warping the normalised shape
# with n -> n^gamma and solving gamma so the reconstructed daily mean equals
# FortyGuard. The warp is monotone and fixes both endpoints, so min and max
# survive exactly.
#
# gamma is a DIAGNOSTIC as much as a correction: gamma far from 1 means the
# shape source and FortyGuard disagree about where the day mass sits.
DIURNAL_WARP_GAMMA_BOUNDS = (0.05, 20.0)
DIURNAL_WARP_TOLERANCE_C = 1e-4

# Reported by the M1 amplitude check. A gamma outside this band is flagged, not
# silently applied. [TUNED]
DIURNAL_WARP_GAMMA_PLAUSIBLE = (0.4, 2.5)


# ----------------------------------------------------------------------------
# 5g. NATURAL WET BULB BY CALCULATION  —  ISO 7243:2017 Annex D
# ----------------------------------------------------------------------------
# [VERIFIED 2026-08-24 against ISO 7243:2017(E) Annex D, Formulae (D.1) and
#  (D.2), and validated against all 22 rows of the standard's own Table D.1 —
#  see tests/test_natural_wet_bulb.py, worst error 0.16 degC.]
#
# Formula (D.1), solved iteratively for t_nw:
#   4,18 * v^0,444 * (t_a - t_nw)
#     + 1e-8 * [(t_r + 273)^4 - (t_nw + 273)^4]
#     - 77,1 * v^0,421 * [p_as(t_nw) - RH * p_as(t_a)]  =  0
#
# Formula (D.2), mean radiant temperature from globe temperature:
#   t_r = [ (t_g+273)^4 + (1,1e8 * v^0,6)/(eps_g * d^0,4) * (t_g - t_a) ]^0,25 - 273
#
# The standard uses 273, not 273,15, in both. We keep ISO's value rather than
# "improving" it, because the coefficients were fitted against it.

ISO_KELVIN_OFFSET = 273.0          # [VERIFIED] as written in ISO 7243 D.1/D.2

ISO_NWB_CONVECTIVE_COEFF = 4.18    # [VERIFIED] ISO 7243:2017 Formula (D.1)
ISO_NWB_CONVECTIVE_EXPONENT = 0.444
ISO_NWB_RADIATIVE_COEFF = 1.0e-8
ISO_NWB_EVAPORATIVE_COEFF = 77.1
ISO_NWB_EVAPORATIVE_EXPONENT = 0.421

ISO_MRT_COEFFICIENT = 1.1e8        # [VERIFIED] ISO 7243:2017 Formula (D.2)
ISO_MRT_SPEED_EXPONENT = 0.6
ISO_MRT_DIAMETER_EXPONENT = 0.4

# The domain ISO actually tabulates. Outside it the standard offers no worked
# example, and Annex D's own preamble says the method "is not recommended".
# Phoenix afternoons run about 3 m/s — over 3x the tabulated ceiling.
ISO_TABLE_D1_TNW_RANGE_C = (15.0, 30.0)   # [VERIFIED] Table D.1 caption
ISO_TABLE_D1_MAX_SPEED_M_S = 0.9          # [VERIFIED] Table D.1 largest v_a

# FAO-56 (Allen et al. 1998) Equation 8: gamma = 0.665e-3 * P, P in kPa.
# [VERIFIED 2026-08-24] Used only to report the natural-vs-psychrometric gap.
PSYCHROMETRIC_CONSTANT_COEFF = 0.665e-3


# ============================================================================
# 6. REGULATORY CONTEXT  —  for copy, not for computation
# ============================================================================
# [VERIFIED 2026-08-23 via web sources — re-confirm before submission]
#
# STATUS: The federal OSHA heat standard is PROPOSED, NOT LAW. The NPRM "Heat
# Injury and Illness Prevention in Outdoor and Indoor Work Settings" published
# 2024-08-30. The informal public hearing closed 2025-07-02; post-hearing comment
# closed 2025-10-30. It has NOT been finalised. NEVER call it a law in the pitch.
#
# ENFORCEMENT IS NEVERTHELESS ACTIVE: the Heat National Emphasis Program was
# renewed 2026-04-10 (CPL 03-00-024) running to April 2031, and citations issue
# under the General Duty Clause. ~7,000 inspections and ~60 GDC citations since 2022.
#
# The compliance story is: liability exists NOW, with no finalised standard to
# comply with. That is the gap the product fills.

OSHA_INITIAL_HEAT_TRIGGER_HEAT_INDEX_F = 80.0   # [CHECK] proposed rule text
OSHA_HIGH_HEAT_TRIGGER_HEAT_INDEX_F = 90.0      # [CHECK] proposed rule text
OSHA_HIGH_HEAT_REST_MIN_PER_2H = 15             # [CHECK] proposed rule text

# OSHA "Rule of 20 Percent" — the calendar ramp the model is measured against.
# Day 1 = 20% of a normal shift, +20% per day.
CALENDAR_RAMP_PCT_BY_DAY = {1: 20, 2: 40, 3: 60, 4: 80, 5: 100}

# NIOSH variant, for comparison in the writeup. [CHECK]
NIOSH_RAMP_PCT_BY_DAY = {1: 50, 2: 60, 3: 80, 4: 100}

# [VERIFIED 2026-08-23] Statistics for the pitch. Cite the source next to each
# number wherever it appears in the UI or the writeup.
#   ~75% of US workplace heat fatalities occur in a worker's first week.
#   Cal/OSHA: almost half on the first day; ~80% within the first four days.
#   BLS: 48 US workers died of environmental heat exposure in 2024.
#   A review of 79 heat fatalities found 5% occurred below any heat-index warning
#     level and a further 20% on days rated only "Caution" — i.e. one in four
#     deaths on days the warning system called safe or nearly safe. THIS IS THE
#     STRONGEST SINGLE STATISTIC FOR THE PITCH.
# Undercount estimates (Public Citizen, ~2,000/yr) are ADVOCACY figures, not
# government counts. If quoted, label them as such. Do not blur the two.


# ============================================================================
# 7. INPUTS THAT ARE DELIBERATELY EXCLUDED
# ============================================================================
# The model must NEVER accept: age, sex, BMI, fitness, medical history,
# hydration status, or home address.
#
# The physiology literature says several of these matter. Employment law makes
# them unusable: restricting a worker's hours on the basis of age is age
# discrimination; on the basis of a medical condition, ADA exposure. Residence
# is excluded because nocturnal heat correlates with poverty and race, so scoring
# individuals on it would systematically cut hours for workers from the hottest,
# poorest neighbourhoods — penalising them for the exposure that endangers them.
#
# Every input is either environmental or job-assigned. The model restricts a
# worker for what he has been EXPOSED TO, never for who he is.
#
# The nocturnal-recovery effect is still shown, but ONLY aggregated to census
# tract, as a policy view. Never per worker.

FORBIDDEN_INPUTS = frozenset({
    "age", "sex", "gender", "bmi", "weight", "height", "fitness",
    "medical_history", "medication", "hydration", "home_address",
    "residence", "zip_code_of_residence", "ethnicity", "race",
})


# ============================================================================
# 8. DEMO CONFIGURATION
# ============================================================================
# "Today" is set two weeks in the past so that BOTH the 14-day backfill and the
# 7-day forward projection resolve to real retrievable data. FortyGuard covers
# 2021 -> today and rejects future dates, so a demo anchored on the real today
# would have no data behind its forward ramp.
#
# This also enables the strongest single demo move: project the ramp forward,
# then pull what actually happened, and show both curves.

DEMO_TODAY = "2026-08-09"
DEMO_BACKFILL_START = "2026-07-26"   # DEMO_TODAY - 14 days
DEMO_BACKFILL_END = "2026-08-08"
DEMO_FORWARD_START = "2026-08-10"
DEMO_FORWARD_END = "2026-08-16"

# If the requested date exceeds FortyGuard coverage, the forward leg falls back
# to Open-Meteo's 7-day forecast. That fallback IS the production path.

BACKFILL_DAYS = 14
FORWARD_DAYS = 7

# [VERIFIED via threshold sweep 2026-08-23] Phoenix summer only. Re-sweep for any
# other city or season — do not assume this transfers.
EXCEEDANCE_THRESHOLD_C = 40.0

# Phoenix construction runs an early summer shift. Using a 9-5 shift makes every
# worker read "stop work" and the demo goes flat.
DEMO_SHIFT_START_HOUR = 5
DEMO_SHIFT_END_HOUR = 13


@dataclass(frozen=True)
class SiteProfile:
    """Everything the employer supplies. Nothing else is permitted."""
    site_id: str
    name: str
    polygon_geojson: dict
    trade: str                      # -> TRADE_TO_WORK_CLASS
    clothing: str = "work_clothes"  # -> CLOTHING_ADJUSTMENT_C
    shift_start_hour: int = DEMO_SHIFT_START_HOUR
    shift_end_hour: int = DEMO_SHIFT_END_HOUR


# ============================================================================
# 9. API ACCESS  —  M0 client and cache
# ============================================================================
# [VERIFIED 2026-08-23/24 against FORTYGUARD_API_CONTRACT.md sections 1-8.]
# Transport-level facts only. Nothing here is physical or regulatory.

FORTYGUARD_BASE_URL = "https://api.fortyguard.com"
FORTYGUARD_DEV_BASE_URL = "https://tos-enterprise-api.dev.app.fortyguard.com"

# Contract section 1: the Python client polls at 3 s intervals.
POLL_INTERVAL_S = 3.0

# [TUNED] How long to wait before giving up on an activity. Two live env_params
# probes on 2026-08-24 sat at `Processing` for 3 and 30 minutes without ever
# completing, so a generous budget is not paranoia. On timeout the client raises
# with the activity_id attached: the call has already been paid for, so it must
# be retrieved rather than resubmitted.
POLL_TIMEOUT_S = 900.0

# [MEASURED 2026-08-24] Large responses intermittently 504 at the gateway while
# being serialised: a 46 931-cell exceedance grid (15 MB) failed one poll and
# succeeded on the very next. A transient error must not discard an activity
# that has already been paid for, so the client absorbs up to this many
# CONSECUTIVE polling failures before giving up.
POLL_MAX_CONSECUTIVE_ERRORS = 5

# Contract section 3: 60, 80 or 100 metres only. 60 m is the finest available.
ALLOWED_GRANULARITIES_M = frozenset({60, 80, 100})

# Contract section 5: these need `threshold` and `direction`, and a multi-hour or
# multi-day window (filter_type 2 or 4).
ANALYTIC_TYPES_NEEDING_THRESHOLD = frozenset({"exceedance", "persistence"})
ANALYTIC_TYPES = frozenset({"tcm", "time_of_measure", "exceedance", "persistence"})

# Contract section 2: Basic/Startup tiers are capped at 3 analysis parameters per
# /v1/env_params request. Whether the cap actually binds on the hackathon key is
# UNRESOLVED — see contract section 6, "analysis may not be applied". The client
# chunks to this size regardless, which is correct either way and free when the
# whole request fits in one chunk.
ENV_PARAMS_MAX_ANALYSIS = 3


# ----------------------------------------------------------------------------
# 9a. EXCEEDANCE CLAMPING  —  mandatory on ingest
# ----------------------------------------------------------------------------
# [VERIFIED 2026-08-23] Contract section 5: the exceedance field is INTERPOLATED,
# not counted. Measured pathologies on real responses:
#     min = -0.3176 h at threshold 42 degC   -- a negative duration
#     max = 168.62 h on a 168-hour window    -- 0.62 h past the ceiling
#
# Both are physically impossible. They are clamped at the parse boundary, in
# fortyguard.parse_analysis_grid, so an impossible duration cannot reach the
# stimulus term. The number of clamped cells is REPORTED, never swallowed: a
# grid where many cells clamp is a grid whose threshold is badly chosen.
#
# We never claim integer-hour precision from this field, and never plot it raw.
EXCEEDANCE_CLAMP_MIN_H = 0.0

# [TUNED] A cell landing further outside the window than this is a parse error —
# wrong window length, wrong units — not interpolation noise. Raise, do not clamp.
EXCEEDANCE_IMPLAUSIBLE_MARGIN_H = 24.0


# ============================================================================
# 10. SITE SELECTION  —  M3
# ============================================================================
# [VERIFIED 2026-08-23] FORTYGUARD_API_CONTRACT.md section 5 records the reason
# every value here exists: on the 14-day 40 degC Phoenix run, all 5 highest
# cells sat within 460 m of the west edge and all 5 lowest within 80 m of the
# north edge, each a contiguous scanline at a single latitude. The extremes of
# an exceedance grid are an artifact of the AOI boundary, not a fact about the
# city. A site chosen from them is chosen from noise.
#
# The mitigation is mandatory and has four parts. All four are enforced in
# siteselection.py and asserted by tests/test_m3_exit.py.

# 1. Request an AOI at least this much larger than the region of interest.
AOI_BUFFER_KM = 1.0

# 2. Discard cells within this distance of the AOI boundary before ranking.
EDGE_DISCARD_M = 500.0

# 3. Rank by percentile, never by absolute min/max.
RANK_PERCENTILE_LOW = 5.0
RANK_PERCENTILE_HIGH = 95.0

# 4. Cross-check any selected cell against satellite segmentation. A genuine hot
#    cell has a high impervious share; if land cover does not explain the
#    ranking, the cell is an artifact.
#
# [VERIFIED 2026-08-23] Contract section 7: class labels are ADE20K-style and
# open-ended — a landlocked downtown Phoenix tile returned "ship": 2.74. Derive
# impervious share by SUMMING the classes we recognise, never by subtracting
# from 100, because the unrecognised remainder is not necessarily pervious.
IMPERVIOUS_CLASSES = frozenset({
    "building", "skyscraper", "road, route", "sidewalk, pavement",
    "house", "wall", "fence", "bridge, span", "runway",
})

# [TUNED] A selected hot cell whose impervious share falls below this is flagged
# for review rather than silently accepted. Downtown Phoenix measured 96.1%
# impervious (building 72.7 + road 12.47 + sidewalk 8.9 + skyscraper 2.04), so
# this is a low bar deliberately: it catches artifacts, not marginal sites.
MIN_IMPERVIOUS_SHARE_FOR_HOT_SITE = 0.40

# Mean Earth radius, for the local equirectangular projection used to convert
# degrees to metres over a metro-scale AOI. [VERIFIED] IUGG mean radius.
EARTH_MEAN_RADIUS_M = 6371008.8
