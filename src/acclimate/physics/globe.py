"""Black-globe temperature from a steady-state energy balance.

T_globe is returned by NEITHER FortyGuard nor Open-Meteo (constants.py section 5),
and it carries 0.2 of the outdoor WBGT weight, so it has to be modelled. Section
5a of constants.py states the substitution we made for Liljegren et al. (2008)
and the three ways it differs.

The balance solved here, per unit sphere surface area:

    alpha_g * S_sphere                                   absorbed shortwave
  + eps_g * sigma * (F * Ta^4 - Tg^4)                    net longwave
  - h_c * (Tg - Ta)                                      convection
  = 0

with the longwave environment factor

    F = 0.5 * (eps_sky + eps_grd + (1 - eps_grd) * eps_sky)

for a sky above and a ground at air temperature below, view factor 0.5 each, the
ground both emitting and reflecting the sky's downwelling longwave.

Air properties are evaluated at air temperature, not film temperature, so h_c is
independent of Tg. That makes the residual strictly decreasing in Tg, so the root
is unique and plain bisection cannot land on the wrong one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from acclimate import constants as C
from acclimate.errors import ConvergenceError
from acclimate.physics import psychrometrics as psy

_BISECTION_TOL_K = 1e-6
_BISECTION_MAX_ITER = 200


@dataclass(frozen=True)
class GlobeResult:
    globe_temperature_c: float
    excess_over_air_c: float
    sphere_shortwave_w_m2: float
    convective_coefficient_w_m2_k: float
    sky_emissivity: float
    iterations: int


def sphere_mean_shortwave_w_m2(
    dni_w_m2: float,
    dhi_w_m2: float,
    ghi_w_m2: float,
    ground_albedo: float = C.GROUND_ALBEDO,
) -> float:
    """Shortwave irradiance averaged over the whole sphere surface.

    Pure geometry (constants.py section 5a):
      - beam:  a sphere presents pi*r^2 of its 4*pi*r^2 surface -> DNI / 4
      - sky:   isotropic upper hemisphere, view factor 0.5      -> DHI / 2
      - ground: reflected global, view factor 0.5               -> albedo*GHI / 2
    """
    return (
        max(dni_w_m2, 0.0) / 4.0
        + max(dhi_w_m2, 0.0) / 2.0
        + ground_albedo * max(ghi_w_m2, 0.0) / 2.0
    )


def convective_coefficient_w_m2_k(
    air_temperature_c: float,
    air_speed_m_s: float,
    pressure_pa: float,
    diameter_m: float = C.GLOBE_DIAMETER_M,
) -> float:
    """Ranz & Marshall (1952) sphere correlation. constants.py section 5a.

    The air speed is floored at MIN_AIR_SPEED_M_S: at true zero the correlation
    collapses to Nu = 2 and the globe runs implausibly hot, because forced
    convection is the only ventilation this form models.
    """
    speed = max(air_speed_m_s, C.MIN_AIR_SPEED_M_S)
    nu = psy.air_kinematic_viscosity_m2_s(air_temperature_c, pressure_pa)
    k = psy.air_thermal_conductivity_w_m_k(air_temperature_c)
    reynolds = speed * diameter_m / nu
    nusselt = C.RANZ_MARSHALL_A + C.RANZ_MARSHALL_B * math.sqrt(reynolds) * C.AIR_PRANDTL ** (
        1.0 / 3.0
    )
    return nusselt * k / diameter_m


def globe_temperature(
    air_temperature_c: float,
    relative_humidity_pct: float,
    air_speed_m_s: float,
    dni_w_m2: float,
    dhi_w_m2: float,
    ghi_w_m2: float,
    cloud_fraction: float,
    elevation_m: float,
    ground_albedo: float = C.GROUND_ALBEDO,
) -> GlobeResult:
    """Solve the balance above for the globe temperature."""
    pressure_pa = psy.station_pressure_pa(elevation_m)
    s_sphere = sphere_mean_shortwave_w_m2(dni_w_m2, dhi_w_m2, ghi_w_m2, ground_albedo)
    h_c = convective_coefficient_w_m2_k(air_temperature_c, air_speed_m_s, pressure_pa)
    eps_sky = psy.sky_emissivity(air_temperature_c, relative_humidity_pct, cloud_fraction)

    t_air_k = psy.celsius_to_kelvin(air_temperature_c)
    # Effective longwave environment: sky above, ground below, view factor 0.5
    # each. The ground both EMITS (eps_grd) and REFLECTS the sky's downwelling
    # longwave (1 - eps_grd), and dropping the reflected part costs about half a
    # degree of globe temperature on an overcast night. With the reflection in,
    # an overcast sky (eps_sky = 1) gives a factor of exactly 1, so the globe
    # sits exactly at air temperature when there is no sun, which is the
    # identity test_globe_sits_at_air_temperature_under_a_black_sky pins.
    environment_factor = 0.5 * (
        eps_sky + C.GROUND_EMISSIVITY + (1.0 - C.GROUND_EMISSIVITY) * eps_sky
    )
    environment_t4 = environment_factor * t_air_k**4
    absorbed_sw = C.GLOBE_SOLAR_ABSORPTIVITY * s_sphere
    eps_sigma = C.GLOBE_EMISSIVITY * C.STEFAN_BOLTZMANN

    def residual(t_globe_k: float) -> float:
        return (
            absorbed_sw
            + eps_sigma * (environment_t4 - t_globe_k**4)
            - h_c * (t_globe_k - t_air_k)
        )

    # residual is strictly decreasing in t_globe_k, so widen until it brackets.
    lo, hi = t_air_k - 40.0, t_air_k + 120.0
    for _ in range(8):
        if residual(lo) > 0.0 and residual(hi) < 0.0:
            break
        lo -= 40.0
        hi += 120.0
    else:
        raise ConvergenceError(
            "globe balance did not bracket: Ta=%.2fC S=%.1f h=%.2f"
            % (air_temperature_c, s_sphere, h_c)
        )

    iterations = 0
    while hi - lo > _BISECTION_TOL_K and iterations < _BISECTION_MAX_ITER:
        mid = 0.5 * (lo + hi)
        if residual(mid) > 0.0:
            lo = mid
        else:
            hi = mid
        iterations += 1
    if iterations >= _BISECTION_MAX_ITER:
        raise ConvergenceError("globe balance hit the iteration cap")

    t_globe_c = psy.kelvin_to_celsius(0.5 * (lo + hi))
    return GlobeResult(
        globe_temperature_c=t_globe_c,
        excess_over_air_c=t_globe_c - air_temperature_c,
        sphere_shortwave_w_m2=s_sphere,
        convective_coefficient_w_m2_k=h_c,
        sky_emissivity=eps_sky,
        iterations=iterations,
    )
