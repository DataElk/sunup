"""Solar geometry and the hourly irradiance curve.

Why this module exists: FortyGuard returns ONE clear-sky daily mean for solar
(FORTYGUARD_API_CONTRACT.md section 6, trap 1) and the globe-temperature balance
needs 24 values. Open-Meteo has the hourly field but no fixture is cached, and
this build makes no live calls.

So the SHAPE comes from astronomy, exact, free, offline, and the LEVEL comes
from FortyGuard: the clear-sky GHI curve is scaled by one factor so its own
daylight-hours mean equals the number FortyGuard reported for that site-day.
There is no free parameter in that step.

All hourly values are evaluated at the labelled instant (HH:00 local), matching
how /v1/env_params timestamps its own 24 values.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from sunup import constants as C

HOURS = tuple(range(24))


@dataclass(frozen=True)
class SolarPosition:
    hour: int
    declination_deg: float
    equation_of_time_min: float
    hour_angle_deg: float
    cos_zenith: float          # clamped at 0; negative sun is night
    elevation_deg: float

    @property
    def is_daylight(self) -> bool:
        return self.elevation_deg > C.MIN_SOLAR_ELEVATION_DEG


@dataclass(frozen=True)
class SolarDay:
    """24 hourly irradiance values plus the diagnostics that justify them."""

    date: dt.date
    latitude: float
    longitude: float
    utc_offset_hours: float
    positions: Tuple[SolarPosition, ...]
    ghi_w_m2: Tuple[float, ...]
    dni_w_m2: Tuple[float, ...]
    dhi_w_m2: Tuple[float, ...]
    # Diagnostics -------------------------------------------------------------
    anchor_scale: float                  # FortyGuard GHI mean / model GHI mean
    model_daylight_mean_ghi: float
    model_24h_mean_ghi: float
    anchor_ghi_w_m2: Optional[float]     # what FortyGuard reported, or None
    dni_anchor_residual: Optional[float]  # anchored daylight mean - FortyGuard DNI
    dhi_anchor_residual: Optional[float]
    cloud_applied: bool
    sunrise_local: Optional[float]       # decimal local hours
    sunset_local: Optional[float]


def _fractional_year_rad(day_of_year: int, hour: float) -> float:
    return (2.0 * math.pi / 365.0) * (day_of_year - 1 + (hour - 12.0) / 24.0)


def equation_of_time_min(gamma: float) -> float:
    """NOAA / Spencer (1971) Fourier fit, minutes. constants.py section 5c."""
    return 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )


def solar_declination_rad(gamma: float) -> float:
    """NOAA / Spencer (1971) Fourier fit, radians. constants.py section 5c."""
    return (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )


def solar_position(
    date: dt.date, hour: float, latitude: float, longitude: float, utc_offset_hours: float
) -> SolarPosition:
    """NOAA solar calculator equations.

    ``longitude`` is degrees EAST (negative in the US); ``utc_offset_hours`` is
    hours east of Greenwich (-7 for Arizona, which never observes DST).
    """
    gamma = _fractional_year_rad(date.timetuple().tm_yday, hour)
    eqtime = equation_of_time_min(gamma)
    decl = solar_declination_rad(gamma)

    time_offset_min = eqtime + 4.0 * longitude - 60.0 * utc_offset_hours
    true_solar_time_min = hour * 60.0 + time_offset_min
    hour_angle_deg = true_solar_time_min / 4.0 - 180.0

    lat = math.radians(latitude)
    ha = math.radians(hour_angle_deg)
    cos_z = math.sin(lat) * math.sin(decl) + math.cos(lat) * math.cos(decl) * math.cos(ha)
    cos_z = min(max(cos_z, -1.0), 1.0)
    elevation = math.degrees(math.asin(cos_z))

    return SolarPosition(
        hour=int(hour),
        declination_deg=math.degrees(decl),
        equation_of_time_min=eqtime,
        hour_angle_deg=hour_angle_deg,
        cos_zenith=max(cos_z, 0.0),
        elevation_deg=elevation,
    )


def sunrise_sunset_local(
    date: dt.date, latitude: float, longitude: float, utc_offset_hours: float
) -> Optional[Tuple[float, float]]:
    """Decimal local hours of sunrise and sunset, or None for polar day/night."""
    gamma = _fractional_year_rad(date.timetuple().tm_yday, 12.0)
    eqtime = equation_of_time_min(gamma)
    decl = solar_declination_rad(gamma)
    cos_ha = -math.tan(math.radians(latitude)) * math.tan(decl)
    if not -1.0 <= cos_ha <= 1.0:
        return None
    ha = math.degrees(math.acos(cos_ha))
    time_offset_min = eqtime + 4.0 * longitude - 60.0 * utc_offset_hours
    solar_noon_min = 720.0 - time_offset_min
    return (
        (solar_noon_min - 4.0 * ha) / 60.0,
        (solar_noon_min + 4.0 * ha) / 60.0,
    )


def clear_sky_ghi_w_m2(cos_zenith: float) -> float:
    """Haurwitz (1945). constants.py section 5c."""
    if cos_zenith <= 0.0:
        return 0.0
    return C.HAURWITZ_A * cos_zenith * math.exp(-C.HAURWITZ_B / cos_zenith)


def clear_sky_dni_w_m2(cos_zenith: float) -> float:
    """Meinel & Meinel (1976). constants.py section 5c."""
    if cos_zenith <= 0.0:
        return 0.0
    air_mass = 1.0 / cos_zenith
    return C.SOLAR_CONSTANT_W_M2 * C.MEINEL_TAU ** (air_mass**C.MEINEL_AM_EXPONENT)


def diffuse_fraction(cos_zenith: float) -> float:
    """Model diffuse share of GHI, from the two clear-sky models above.

    Used only to SPLIT the FortyGuard-anchored GHI. Anchoring GHI, DNI and DHI
    independently would break the closure GHI = DNI*cos(z) + DHI; anchoring the
    total and splitting by this fraction keeps the closure exact and leaves the
    DNI/DHI residual visible as a diagnostic.
    """
    ghi = clear_sky_ghi_w_m2(cos_zenith)
    if ghi <= 0.0:
        return 1.0
    dhi = ghi - clear_sky_dni_w_m2(cos_zenith) * cos_zenith
    return min(max(dhi / ghi, 0.0), 1.0)


def cloud_attenuation_factor(cloud_fraction: float) -> float:
    """Kasten & Czeplak (1980) global-irradiance factor. constants.py section 5c."""
    c = min(max(cloud_fraction, 0.0), 1.0)
    return 1.0 - C.KASTEN_CZEPLAK_A * c**C.KASTEN_CZEPLAK_EXPONENT


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def solar_day(
    date: dt.date,
    latitude: float,
    longitude: float,
    utc_offset_hours: float,
    anchor_daily_ghi_w_m2: Optional[float] = None,
    anchor_daily_dni_w_m2: Optional[float] = None,
    anchor_daily_dhi_w_m2: Optional[float] = None,
    cloud_fraction: Optional[Sequence[float]] = None,
) -> SolarDay:
    """Hourly all-sky GHI/DNI/DHI for one local day.

    ``anchor_daily_ghi_w_m2`` is FortyGuard's clear-sky daily mean. When given,
    the whole clear-sky curve is scaled so its daylight-hours mean matches it.
    When absent the raw Haurwitz level is used and ``anchor_scale`` is 1.0, 
    which the provenance record then reports as unanchored.

    ``cloud_fraction`` is 24 values in [0, 1]. Cloud is applied AFTER anchoring,
    because the FortyGuard anchor is explicitly a CLEAR-SKY figure.
    """
    positions = tuple(
        solar_position(date, h, latitude, longitude, utc_offset_hours) for h in HOURS
    )
    clear_ghi = [clear_sky_ghi_w_m2(p.cos_zenith) for p in positions]
    daylight = [g for g, p in zip(clear_ghi, positions) if p.is_daylight]
    model_daylight_mean = _mean(daylight)
    model_24h_mean = _mean(clear_ghi)

    scale = 1.0
    if anchor_daily_ghi_w_m2 is not None and model_daylight_mean > 0.0:
        scale = anchor_daily_ghi_w_m2 / model_daylight_mean

    ghi = [g * scale for g in clear_ghi]
    kd = [diffuse_fraction(p.cos_zenith) for p in positions]
    dhi = [g * k for g, k in zip(ghi, kd)]
    # The beam cannot exceed the solar constant. It only can here if a large
    # anchor scale meets a sun close to the horizon; clamping the beam and
    # giving the remainder to diffuse keeps the closure exact either way.
    dni = [
        min((g - d) / p.cos_zenith, C.SOLAR_CONSTANT_W_M2) if p.cos_zenith > 0.0 else 0.0
        for g, d, p in zip(ghi, dhi, positions)
    ]
    dhi = [max(g - n * p.cos_zenith, 0.0) for g, n, p in zip(ghi, dni, positions)]

    dni_residual = dhi_residual = None
    if anchor_daily_dni_w_m2 is not None:
        modelled = _mean([v for v, p in zip(dni, positions) if p.is_daylight])
        dni_residual = modelled - anchor_daily_dni_w_m2
    if anchor_daily_dhi_w_m2 is not None:
        modelled = _mean([v for v, p in zip(dhi, positions) if p.is_daylight])
        dhi_residual = modelled - anchor_daily_dhi_w_m2

    cloud_applied = cloud_fraction is not None
    if cloud_applied:
        if len(cloud_fraction) != 24:
            raise ValueError("cloud_fraction must have 24 values, got %d" % len(cloud_fraction))
        for i, p in enumerate(positions):
            c = min(max(cloud_fraction[i], 0.0), 1.0)
            ghi[i] *= cloud_attenuation_factor(c)
            # Beam survives in proportion to the clear fraction; diffuse takes
            # the remainder so the closure holds at both endpoints exactly.
            dni[i] *= 1.0 - c
            dhi[i] = max(ghi[i] - dni[i] * p.cos_zenith, 0.0)

    rise_set = sunrise_sunset_local(date, latitude, longitude, utc_offset_hours)
    return SolarDay(
        date=date,
        latitude=latitude,
        longitude=longitude,
        utc_offset_hours=utc_offset_hours,
        positions=positions,
        ghi_w_m2=tuple(ghi),
        dni_w_m2=tuple(dni),
        dhi_w_m2=tuple(dhi),
        anchor_scale=scale,
        model_daylight_mean_ghi=model_daylight_mean,
        model_24h_mean_ghi=model_24h_mean,
        anchor_ghi_w_m2=anchor_daily_ghi_w_m2,
        dni_anchor_residual=dni_residual,
        dhi_anchor_residual=dhi_residual,
        cloud_applied=cloud_applied,
        sunrise_local=rise_set[0] if rise_set else None,
        sunset_local=rise_set[1] if rise_set else None,
    )
