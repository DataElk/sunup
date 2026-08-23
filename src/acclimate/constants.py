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
# [CHECK] NIOSH Criteria for a Recommended Standard: Occupational Exposure to Heat
#         and Hot Environments, DHHS (NIOSH) Publication 2016-106.
#         REL = Recommended Exposure Limit, acclimatized workers.
#         RAL = Recommended Alert Limit, UNacclimatized workers.
#
# These are the two curves the whole product interpolates between. THEY MUST BE
# RIGHT. Read them off the NIOSH ceiling/REL/RAL figure for continuous (60 min/h)
# work at each metabolic rate, and record the figure number here when confirmed.
#
# Cross-reference: ACGIH TLV for Heat Stress is a closely related but distinct
# set of curves. Do not mix them. If you use ACGIH values, say ACGIH in the
# writeup, not NIOSH.
#
# Values below are °C-WBGT for CONTINUOUS work. [CHECK ALL SIX]

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
# worker's personal limit. [CHECK] against the NIOSH work/rest schedule table —
# NIOSH expresses this as work-rest regimens (75/25, 50/50, 25/75) at
# progressively lower WBGT for a given metabolic rate.
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

# Below this, a day contributes no adaptation at all.
STIMULUS_FLOOR_DEG = 0.0


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

WBGT_OUTDOOR_WEIGHTS = (0.7, 0.2, 0.1)   # (nwb, globe, dry)
WBGT_INDOOR_WEIGHTS = (0.7, 0.3, 0.0)

# Sanity band. Any computed WBGT outside this is a bug, not weather.
WBGT_PLAUSIBLE_MIN, WBGT_PLAUSIBLE_MAX = -20.0, 45.0

# [VERIFIED] Worked reference, downtown Phoenix 2024-07-15 14:00, from live API:
#   T_dry 39.7 °C, T_wb 23.7 °C, RH 22.9%  ->  WBGT ~ 31 °C
#   At 06:00 the same day: T_wb 22.0 °C, weak solar  ->  WBGT ~ 24.8 °C
# The day therefore crosses BOTH the RAL and REL curves for moderate work.
# Use this as the regression fixture for the WBGT pipeline.


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
