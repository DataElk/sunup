"""Moist-air properties.

Only what the globe-temperature balance needs: vapour pressure (for sky
emissivity), air density/viscosity/conductivity (for the convective coefficient),
and station pressure from elevation.

Wet bulb itself is NOT computed here — FortyGuard measures it and returns 24
hourly values. See constants.py section 5b for why we take that value unmodified.
"""

from __future__ import annotations

import math

from acclimate import constants as C

ZERO_CELSIUS_K = 273.15


def celsius_to_kelvin(t_c: float) -> float:
    return t_c + ZERO_CELSIUS_K


def kelvin_to_celsius(t_k: float) -> float:
    return t_k - ZERO_CELSIUS_K


def saturation_vapour_pressure_kpa(t_c: float) -> float:
    """Magnus/Tetens over water. constants.py section 5e."""
    return C.MAGNUS_A_KPA * math.exp(C.MAGNUS_B * t_c / (t_c + C.MAGNUS_C))


def vapour_pressure_kpa(t_c: float, relative_humidity_pct: float) -> float:
    """Actual vapour pressure from dry bulb and RH."""
    rh = min(max(relative_humidity_pct, 0.0), 100.0) / 100.0
    return rh * saturation_vapour_pressure_kpa(t_c)


def psychrometric_constant_kpa_per_c(pressure_pa: float) -> float:
    """FAO-56 Equation 8: gamma = 0.665e-3 * P, with P in kPa."""
    return C.PSYCHROMETRIC_CONSTANT_COEFF * (pressure_pa / 1000.0)


def vapour_pressure_from_wet_bulb_kpa(
    t_dry_c: float, t_wet_c: float, pressure_pa: float
) -> float:
    """Psychrometric equation: e = e_s(T_wet) - gamma * (T_dry - T_wet)."""
    gamma = psychrometric_constant_kpa_per_c(pressure_pa)
    return max(saturation_vapour_pressure_kpa(t_wet_c) - gamma * (t_dry_c - t_wet_c), 0.0)


def psychrometric_wet_bulb_c(
    t_dry_c: float,
    relative_humidity_pct: float,
    pressure_pa: float = None,
) -> float:
    """Invert the psychrometric equation for wet bulb, given dry bulb and RH.

    Needed only to report how far ISO 7243 Annex D's NATURAL wet bulb sits above
    the PSYCHROMETRIC value FortyGuard returns. The pipeline never substitutes
    this for FortyGuard's measurement.

    e_s(T_wet) - gamma * (T_dry - T_wet) is strictly increasing in T_wet, so
    bisection finds the unique root.
    """
    if pressure_pa is None:
        pressure_pa = C.ISA_SEA_LEVEL_PRESSURE_PA
    target = vapour_pressure_kpa(t_dry_c, relative_humidity_pct)
    gamma = psychrometric_constant_kpa_per_c(pressure_pa)

    def residual(t_wet: float) -> float:
        return saturation_vapour_pressure_kpa(t_wet) - gamma * (t_dry_c - t_wet) - target

    lo, hi = -80.0, t_dry_c
    if residual(hi) < 0.0:
        return t_dry_c
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if residual(mid) < 0.0:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-7:
            break
    return 0.5 * (lo + hi)


def station_pressure_pa(elevation_m: float) -> float:
    """ISA pressure at geometric height. constants.py section 5a."""
    factor = 1.0 - C.ISA_LAPSE_COEFF * elevation_m
    if factor <= 0.0:
        raise ValueError("elevation outside the ISA troposphere fit: %r" % elevation_m)
    return C.ISA_SEA_LEVEL_PRESSURE_PA * factor**C.ISA_LAPSE_EXPONENT


def air_density_kg_m3(t_c: float, pressure_pa: float) -> float:
    """Ideal gas, dry air. The moist correction is <1% at Phoenix humidities."""
    return pressure_pa / (C.AIR_GAS_CONSTANT_J_KG_K * celsius_to_kelvin(t_c))


def air_dynamic_viscosity_pa_s(t_c: float) -> float:
    """Sutherland's law. constants.py section 5a."""
    t_k = celsius_to_kelvin(t_c)
    t0, s = C.AIR_SUTHERLAND_T0_K, C.AIR_SUTHERLAND_S_K
    return C.AIR_SUTHERLAND_MU0_PA_S * ((t0 + s) / (t_k + s)) * (t_k / t0) ** 1.5


def air_kinematic_viscosity_m2_s(t_c: float, pressure_pa: float) -> float:
    return air_dynamic_viscosity_pa_s(t_c) / air_density_kg_m3(t_c, pressure_pa)


def air_thermal_conductivity_w_m_k(t_c: float) -> float:
    """Power-law fit anchored at 300 K. constants.py section 5a."""
    t_k = celsius_to_kelvin(t_c)
    return C.AIR_CONDUCTIVITY_REF_W_M_K * (
        t_k / C.AIR_CONDUCTIVITY_REF_T_K
    ) ** C.AIR_CONDUCTIVITY_EXPONENT


def sky_emissivity(
    t_air_c: float, relative_humidity_pct: float, cloud_fraction: float
) -> float:
    """Brutsaert (1975) clear sky, raised toward 1 by cloud.

    eps_sky = eps_clear + (1 - eps_clear) * cloud_fraction

    Overcast therefore gives exactly 1.0 (a black sky at air temperature) and
    clear gives Brutsaert unmodified. constants.py section 5e.
    """
    e_hpa = vapour_pressure_kpa(t_air_c, relative_humidity_pct) * 10.0
    t_k = celsius_to_kelvin(t_air_c)
    eps_clear = C.BRUTSAERT_A * (e_hpa / t_k) ** C.BRUTSAERT_EXPONENT
    eps_clear = min(max(eps_clear, 0.0), 1.0)
    c = min(max(cloud_fraction, 0.0), 1.0)
    return eps_clear + (1.0 - eps_clear) * c


def wind_at_height(
    speed_m_s: float,
    from_height_m: float = C.WIND_MEASUREMENT_HEIGHT_M,
    to_height_m: float = C.GLOBE_HEIGHT_M,
    roughness_length_m: float = C.SURFACE_ROUGHNESS_LENGTH_M,
) -> float:
    """Logarithmic wind profile. constants.py section 5d.

    Open-Meteo reports wind at 10 m; the globe sits at about 2 m. Skipping this
    step would over-ventilate the globe and under-read WBGT.
    """
    if to_height_m <= roughness_length_m or from_height_m <= roughness_length_m:
        raise ValueError("height must exceed the roughness length")
    ratio = math.log(to_height_m / roughness_length_m) / math.log(
        from_height_m / roughness_length_m
    )
    return max(speed_m_s * ratio, 0.0)
