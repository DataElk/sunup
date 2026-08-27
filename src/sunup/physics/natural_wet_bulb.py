"""Natural wet bulb temperature, ISO 7243:2017 Annex D.

WHY THIS EXISTS. WBGT is defined on the NATURAL wet bulb temperature, and
ISO 7243:2017 Annex B.1 is explicit that this is not the psychrometric value:

    "The natural wet bulb temperature is thus different from the thermo-dynamic
     temperature determined with a psychrometer."

FortyGuard returns the psychrometric value. constants.py section 5b originally
took it unmodified because no correction could be cited. Annex D is that
citation, so the correction is now available and verified against the standard's
own worked examples (see tests/test_natural_wet_bulb.py, which reproduces all
22 rows of Table D.1).

ISO 7243:2017, Formula (D.1), solved iteratively for t_nw:

    4,18 * v^0,444 * (t_a - t_nw)
      + 1e-8 * [(t_r + 273)^4 - (t_nw + 273)^4]
      - 77,1 * v^0,421 * [p_as(t_nw) - RH * p_as(t_a)]
    = 0

convection + radiation - evaporation = 0 for a naturally ventilated wet wick.

ISO 7243:2017, Formula (D.2), mean radiant temperature from globe temperature:

    t_r = [ (t_g + 273)^4
            + (1,1e8 * v^0,6) / (eps_g * d^0,4) * (t_g - t_a) ]^(1/4) - 273

READ THE STANDARD'S OWN WARNING BEFORE USING THIS. Annex D opens:

    "The indirect evaluation of tnw by calculation is neither simple nor
     reliable, especially when air velocity is low and in conditions of natural
     convection. It is not recommended; however it can be of interest in some
     applications."

and Table D.1 is tabulated only for t_nw in 15-30 degC and air velocity up to
0,9 m/s. Phoenix afternoons run about 3 m/s, well outside that. This module is
therefore offered as a SELECTABLE model, not the default, see
constants.py section 5b for the decision and what it costs.
"""

from __future__ import annotations

from dataclasses import dataclass

from sunup import constants as C
from sunup.errors import ConvergenceError
from sunup.physics import psychrometrics as psy

_TOL_C = 1e-7
_MAX_ITER = 200


@dataclass(frozen=True)
class NaturalWetBulbResult:
    natural_wet_bulb_c: float
    mean_radiant_temperature_c: float
    excess_over_psychrometric_c: float
    iterations: int
    within_iso_table_range: bool


def mean_radiant_temperature_c(
    globe_temperature_c: float,
    air_temperature_c: float,
    air_speed_m_s: float,
    globe_diameter_m: float = C.GLOBE_DIAMETER_M,
    globe_emissivity: float = C.GLOBE_EMISSIVITY,
) -> float:
    """ISO 7243:2017 Formula (D.2)."""
    speed = max(air_speed_m_s, C.MIN_AIR_SPEED_M_S)
    forced = (
        C.ISO_MRT_COEFFICIENT
        * speed**C.ISO_MRT_SPEED_EXPONENT
        / (globe_emissivity * globe_diameter_m**C.ISO_MRT_DIAMETER_EXPONENT)
    )
    inner = (globe_temperature_c + C.ISO_KELVIN_OFFSET) ** 4 + forced * (
        globe_temperature_c - air_temperature_c
    )
    if inner <= 0.0:
        raise ConvergenceError(
            "ISO D.2 produced a non-positive fourth power: tg=%.2f ta=%.2f v=%.2f"
            % (globe_temperature_c, air_temperature_c, air_speed_m_s)
        )
    return inner**0.25 - C.ISO_KELVIN_OFFSET


def natural_wet_bulb_c(
    air_temperature_c: float,
    mean_radiant_temperature_c_: float,
    air_speed_m_s: float,
    relative_humidity_pct: float,
) -> NaturalWetBulbResult:
    """ISO 7243:2017 Formula (D.1), solved for t_nw by bisection.

    The residual is strictly decreasing in t_nw, every term loses heat faster as
    the wick warms, so the root is unique.
    """
    speed = max(air_speed_m_s, C.MIN_AIR_SPEED_M_S)
    rh = min(max(relative_humidity_pct, 0.0), 100.0) / 100.0
    p_air = psy.saturation_vapour_pressure_kpa(air_temperature_c)

    convective = C.ISO_NWB_CONVECTIVE_COEFF * speed**C.ISO_NWB_CONVECTIVE_EXPONENT
    evaporative = C.ISO_NWB_EVAPORATIVE_COEFF * speed**C.ISO_NWB_EVAPORATIVE_EXPONENT

    def residual(t_nw: float) -> float:
        return (
            convective * (air_temperature_c - t_nw)
            + C.ISO_NWB_RADIATIVE_COEFF
            * (
                (mean_radiant_temperature_c_ + C.ISO_KELVIN_OFFSET) ** 4
                - (t_nw + C.ISO_KELVIN_OFFSET) ** 4
            )
            - evaporative
            * (psy.saturation_vapour_pressure_kpa(t_nw) - rh * p_air)
        )

    lo = -60.0
    hi = max(air_temperature_c, mean_radiant_temperature_c_) + 5.0
    if residual(lo) < 0.0 or residual(hi) > 0.0:
        raise ConvergenceError(
            "ISO D.1 did not bracket: ta=%.2f tr=%.2f v=%.2f rh=%.1f"
            % (air_temperature_c, mean_radiant_temperature_c_, speed, relative_humidity_pct)
        )

    iterations = 0
    while hi - lo > _TOL_C and iterations < _MAX_ITER:
        mid = 0.5 * (lo + hi)
        if residual(mid) > 0.0:
            lo = mid
        else:
            hi = mid
        iterations += 1

    t_nw = 0.5 * (lo + hi)
    psychrometric = psy.psychrometric_wet_bulb_c(
        air_temperature_c, relative_humidity_pct
    )
    lo_t, hi_t = C.ISO_TABLE_D1_TNW_RANGE_C
    return NaturalWetBulbResult(
        natural_wet_bulb_c=t_nw,
        mean_radiant_temperature_c=mean_radiant_temperature_c_,
        excess_over_psychrometric_c=t_nw - psychrometric,
        iterations=iterations,
        within_iso_table_range=(
            lo_t <= t_nw <= hi_t and speed <= C.ISO_TABLE_D1_MAX_SPEED_M_S
        ),
    )


def from_globe(
    globe_temperature_c: float,
    air_temperature_c: float,
    air_speed_m_s: float,
    relative_humidity_pct: float,
) -> NaturalWetBulbResult:
    """Convenience: D.2 then D.1, the way the pipeline uses them."""
    t_r = mean_radiant_temperature_c(
        globe_temperature_c, air_temperature_c, air_speed_m_s
    )
    return natural_wet_bulb_c(
        air_temperature_c, t_r, air_speed_m_s, relative_humidity_pct
    )
