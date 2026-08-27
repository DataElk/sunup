"""Open-Meteo hourly fields: wind, shortwave radiation, regional temperature.

constants.py section 5 records the gap this fills: wind is available from
NEITHER FortyGuard endpoint, and hourly solar is available from neither either.
Open-Meteo has both.

No Open-Meteo payload is cached yet, and this build makes no live calls, so
every accessor here raises OfflineDataUnavailable with the exact request that
would fill the gap. Nothing guesses. The pipeline degrades to an explicitly
tagged assumption (see WindProvenance) rather than to a silent one.

Expected fixture layout, matching how FortyGuard fixtures are keyed:

    fixtures/openmeteo/<lat>_<lon>_<YYYY-MM-DD>.json

holding the raw archive-API response for
    hourly=temperature_2m,shortwave_radiation,wind_speed_10m,cloud_cover
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from sunup.errors import OfflineDataUnavailable
from sunup.sources.fixtures import FixtureStore

ARCHIVE_HOURLY_FIELDS = (
    "temperature_2m",
    "relative_humidity_2m",
    "wet_bulb_temperature_2m",
    "shortwave_radiation",
    "wind_speed_10m",
    "cloud_cover",
)

# Wet bulb and relative humidity were added on 2026-08-24 so Open-Meteo can stand
# in for /v1/env_params on site-days where no env_params call was ever made.
#
# That substitution is justified, not convenient: the provenance audit
# (scripts/audit_env_params_provenance.py, and FORTYGUARD_API_CONTRACT.md
# section 6) established that FortyGuard's wet_bulb_temperature_celsius agrees
# with Open-Meteo's wet_bulb_temperature_2m on 15 of 24 hours with a worst
# difference of 0.1 degC, and its relative_humidity_percent agrees to within
# rounding. The two are not independent sources. Using Open-Meteo directly costs
# nothing, needs no key, and covers dates FortyGuard was never asked about.
ENV_PARAMS_SUBSTITUTE_FIELDS = ("relative_humidity_2m", "wet_bulb_temperature_2m")


@dataclass(frozen=True)
class OpenMeteoDay:
    date: dt.date
    latitude: float
    longitude: float
    temperature_2m_c: Tuple[float, ...]
    shortwave_radiation_w_m2: Tuple[float, ...]
    wind_speed_10m_m_s: Tuple[float, ...]
    cloud_cover_fraction: Tuple[float, ...]
    relative_humidity_pct: Tuple[float, ...] = ()
    wet_bulb_temperature_c: Tuple[float, ...] = ()
    elevation_m: float = 0.0
    utc_offset_hours: float = 0.0

    @property
    def can_replace_env_params(self) -> bool:
        """True when this day carries the two fields env_params would supply."""
        return len(self.relative_humidity_pct) == 24 and len(self.wet_bulb_temperature_c) == 24


def fixture_key(latitude: float, longitude: float, date: dt.date) -> str:
    return "openmeteo/%.4f_%.4f_%s.json" % (latitude, longitude, date.isoformat())


def _missing(latitude: float, longitude: float, date: dt.date, why: str) -> OfflineDataUnavailable:
    return OfflineDataUnavailable(
        "%s No Open-Meteo fixture at %s. Fetch once with:\n"
        "  https://archive-api.open-meteo.com/v1/archive"
        "?latitude=%.4f&longitude=%.4f&start_date=%s&end_date=%s"
        "&hourly=%s&timezone=auto\n"
        "and commit the raw response per fixtures/MANIFEST.md."
        % (
            why,
            fixture_key(latitude, longitude, date),
            latitude,
            longitude,
            date.isoformat(),
            date.isoformat(),
            ",".join(ARCHIVE_HOURLY_FIELDS),
        )
    )


def load_day(
    latitude: float,
    longitude: float,
    date: dt.date,
    store: Optional[FixtureStore] = None,
) -> OpenMeteoDay:
    """Load a cached Open-Meteo day, or explain exactly how to cache it."""
    store = store or FixtureStore()
    key = fixture_key(latitude, longitude, date)
    if not store.exists(key):
        raise _missing(latitude, longitude, date, "Open-Meteo is not cached.")

    payload = store.load(key)
    hourly = payload.get("hourly") or {}
    missing = [f for f in ARCHIVE_HOURLY_FIELDS if f not in hourly]
    if missing:
        raise OfflineDataUnavailable(
            "%s is cached but missing %s. Re-fetch with the full hourly list."
            % (key, missing)
        )

    def series(name: str) -> Tuple[float, ...]:
        values = hourly[name][:24]
        if len(values) != 24 or any(v is None for v in values):
            raise OfflineDataUnavailable(
                "%s in %s is not 24 complete hourly values" % (name, key)
            )
        return tuple(float(v) for v in values)

    cloud = series("cloud_cover")
    return OpenMeteoDay(
        date=date,
        latitude=latitude,
        longitude=longitude,
        temperature_2m_c=series("temperature_2m"),
        shortwave_radiation_w_m2=series("shortwave_radiation"),
        wind_speed_10m_m_s=series("wind_speed_10m"),
        cloud_cover_fraction=tuple(min(max(v / 100.0, 0.0), 1.0) for v in cloud),
        relative_humidity_pct=series("relative_humidity_2m"),
        wet_bulb_temperature_c=series("wet_bulb_temperature_2m"),
        elevation_m=float(payload.get("elevation", 0.0)),
        utc_offset_hours=float(payload.get("utc_offset_seconds", 0)) / 3600.0,
    )


def try_load_day(
    latitude: float,
    longitude: float,
    date: dt.date,
    store: Optional[FixtureStore] = None,
) -> Optional[OpenMeteoDay]:
    """load_day, but None instead of raising, for optional diagnostics only.

    Never use this on a path where the value is required. A required value that
    is missing must raise, so the gap is visible.
    """
    try:
        return load_day(latitude, longitude, date, store)
    except OfflineDataUnavailable:
        return None


def hourly_wind_at_globe(day: OpenMeteoDay) -> Sequence[float]:
    """10 m wind converted to globe height. See physics.psychrometrics."""
    from sunup.physics.psychrometrics import wind_at_height

    return tuple(wind_at_height(v) for v in day.wind_speed_10m_m_s)
