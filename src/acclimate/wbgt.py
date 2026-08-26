"""M1, the WBGT pipeline.

    Environment  ->  WBGT  ->  daily stimulus s  ->  adaptation state A  ->  work/rest
                 ^^^^^^^^
                 this module

Composes FortyGuard dry bulb and wet bulb with solar, wind and a modelled globe
temperature into 24 hourly WBGT values for one site on one day.

Every hour carries the terms it was built from, and every day carries a
Provenance record naming the source of each input and listing which of them were
ASSUMED rather than retrieved. A WBGT number that came partly from an assumption
must never be indistinguishable from one that did not.

Input map (constants.py section 5):
    T_dry   FortyGuard /v1/heatmap filter_type=3, per-cell temporal min/mean/max,
            reconstructed to hourly against a diurnal shape (physics.diurnal)
    T_nwb   FortyGuard /v1/env_params wet_bulb_temperature_celsius. That is the
            PSYCHROMETRIC value; WBGT is defined on the NATURAL wet bulb. Two
            models are available, see NaturalWetBulbModel and constants.py 5b/5g.
    T_globe modelled, sphere energy balance (physics.globe)
    solar   Open-Meteo hourly when cached, else a modelled clear-sky curve
            anchored to FortyGuard's daily clear-sky mean (physics.solar)
    wind    Open-Meteo only. Assumed constant when not cached, and tagged.

SourceSelection controls which of those Open-Meteo supplies, so the effect of a
single input can be isolated rather than swapping four at once.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, Optional, Sequence, Tuple

from acclimate import constants as C
from acclimate.errors import ImplausibleValue
from acclimate.physics import diurnal, globe, solar
from acclimate.physics import natural_wet_bulb as nwb
from acclimate.physics import psychrometrics as psy
from acclimate.sources.fortyguard import EnvParamsDay, TemperatureGrid
from acclimate.sources.openmeteo import OpenMeteoDay

# --- natural wet bulb models ------------------------------------------------
# "psychrometric": use FortyGuard's psychrometric value as if it were the
#   natural wet bulb. A stated simplification (constants.py 5b). Biases WBGT
#   LOW, because a sunlit wick reads above the psychrometric value.
# "iso7243_annex_d": derive the natural wet bulb from ISO 7243:2017 Formula
#   (D.1). Correct by the standard, but the standard itself calls the method
#   "not recommended" and tabulates it only to 0.9 m/s (constants.py 5g).
NWB_PSYCHROMETRIC = "psychrometric"
NWB_ISO_ANNEX_D = "iso7243_annex_d"

SHAPE_OPEN_METEO = "openmeteo.temperature_2m"
SHAPE_FG_APPARENT = "fortyguard.env_params.apparent_temperature_celsius"

WIND_OPEN_METEO = "openmeteo.wind_speed_10m -> %.0f m (log profile)" % C.GLOBE_HEIGHT_M
WIND_ASSUMED = "ASSUMED constant %.1f m/s [constants.py 5d]"

SOLAR_ANCHORED = (
    "modelled clear-sky (Haurwitz/Meinel) anchored to "
    "fortyguard.env_params.solar_irradiance.clear_sky.ghi"
)
SOLAR_OPEN_METEO = "openmeteo.shortwave_radiation"

CLOUD_OPEN_METEO = "openmeteo.cloud_cover"
CLOUD_FORTYGUARD = "fortyguard.env_params.cloud_cover_octas read as percent"


@dataclass(frozen=True)
class SourceSelection:
    """Which inputs to take from Open-Meteo when a fixture is available.

    Defaults to all of them. Turning individual fields off is how the report
    attributes a change to one input instead of four, e.g. measured wind with
    everything else left on the FortyGuard-only path.
    """

    shape: bool = True
    solar: bool = True
    wind: bool = True
    cloud: bool = True

    @classmethod
    def none(cls) -> "SourceSelection":
        return cls(shape=False, solar=False, wind=False, cloud=False)

    @classmethod
    def wind_only(cls) -> "SourceSelection":
        return cls(shape=False, solar=False, wind=True, cloud=False)


@dataclass(frozen=True)
class Provenance:
    """Where each input actually came from, and which ones were assumed."""

    dry_bulb: str
    dry_bulb_shape: str
    wet_bulb: str
    natural_wet_bulb: str
    relative_humidity: str
    cloud: str
    solar: str
    wind: str
    globe_temperature: str
    assumed_inputs: Tuple[str, ...] = ()

    @property
    def fully_retrieved(self) -> bool:
        return not self.assumed_inputs

    def as_rows(self) -> Tuple[Tuple[str, str], ...]:
        return (
            ("dry bulb", self.dry_bulb),
            ("dry bulb shape", self.dry_bulb_shape),
            ("wet bulb", self.wet_bulb),
            ("natural wet bulb", self.natural_wet_bulb),
            ("relative humidity", self.relative_humidity),
            ("cloud", self.cloud),
            ("solar", self.solar),
            ("wind", self.wind),
            ("globe", self.globe_temperature),
        )


@dataclass(frozen=True)
class WBGTHour:
    hour: int
    wbgt_c: float
    dry_bulb_c: float
    natural_wet_bulb_c: float
    psychrometric_wet_bulb_c: float
    globe_c: float
    globe_excess_over_air_c: float
    mean_radiant_c: Optional[float]
    relative_humidity_pct: float
    cloud_fraction: float
    wind_speed_m_s: float
    ghi_w_m2: float
    dni_w_m2: float
    dhi_w_m2: float
    solar_elevation_deg: float
    solar_load_weights: bool  # True = ISO 7243 Formula (2), with solar load


@dataclass(frozen=True)
class WBGTDay:
    site_id: str
    date: dt.date
    latitude: float
    longitude: float
    elevation_m: float
    hours: Tuple[WBGTHour, ...]
    provenance: Provenance
    reconstruction: diurnal.DiurnalReconstruction
    solar_day: solar.SolarDay
    amplitude_check: diurnal.AmplitudeComparison
    natural_wet_bulb_model: str
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def at(self, hour: int) -> WBGTHour:
        return self.hours[hour]

    @property
    def series_c(self) -> Tuple[float, ...]:
        return tuple(h.wbgt_c for h in self.hours)

    @property
    def peak(self) -> WBGTHour:
        return max(self.hours, key=lambda h: h.wbgt_c)

    @property
    def trough(self) -> WBGTHour:
        return min(self.hours, key=lambda h: h.wbgt_c)

    def window(self, start_hour: int, end_hour: int) -> Tuple[WBGTHour, ...]:
        """Hours in [start_hour, end_hour). The demo shift is 05:00-13:00."""
        return tuple(h for h in self.hours if start_hour <= h.hour < end_hour)

    def crosses(self, limit_c: float) -> bool:
        """True when the day has hours both below and above ``limit_c``."""
        values = self.series_c
        return min(values) < limit_c < max(values)

    def degree_hours_above(
        self, limit_c: float, start_hour: int = 0, end_hour: int = 24
    ) -> float:
        """Sum of (WBGT - limit) over the hours that exceed it.

        The raw material for the M2 stimulus term. Hourly samples, so each hour
        counts once; this is a rectangle rule, not integer-hour precision.
        """
        return sum(
            max(h.wbgt_c - limit_c, 0.0) for h in self.window(start_hour, end_hour)
        )


def _wind_series(
    open_meteo: Optional[OpenMeteoDay],
    use_open_meteo: bool,
    override_m_s: Optional[float],
) -> Tuple[Tuple[float, ...], str, bool]:
    """(24 speeds at globe height, provenance string, was_assumed)."""
    if override_m_s is not None:
        return (
            tuple(override_m_s for _ in range(24)),
            WIND_ASSUMED % override_m_s,
            True,
        )
    if open_meteo is not None and use_open_meteo:
        return (
            tuple(psy.wind_at_height(v) for v in open_meteo.wind_speed_10m_m_s),
            WIND_OPEN_METEO,
            False,
        )
    return (
        tuple(C.DEFAULT_WIND_SPEED_M_S for _ in range(24)),
        WIND_ASSUMED % C.DEFAULT_WIND_SPEED_M_S,
        True,
    )


def build_wbgt_day(
    site_id: str,
    grid: TemperatureGrid,
    env: Optional[EnvParamsDay],
    site_longitude: float,
    site_latitude: float,
    open_meteo: Optional[OpenMeteoDay] = None,
    use: Optional[SourceSelection] = None,
    wind_speed_m_s: Optional[float] = None,
    ground_albedo: float = C.GROUND_ALBEDO,
    natural_wet_bulb_model: str = NWB_PSYCHROMETRIC,
) -> WBGTDay:
    """Hourly WBGT for one site on one day.

    ``grid`` must come from a ``filter_type=3`` call so its per-cell min/max
    carry the diurnal range; a ``filter_type=1`` grid collapses them to the
    snapshot value and the reconstruction would produce a flat day.

    ``wind_speed_m_s`` forces an assumed constant wind (already at globe height)
    and is what the sensitivity sweep uses. It overrides ``use.wind``.
    """
    if natural_wet_bulb_model not in (NWB_PSYCHROMETRIC, NWB_ISO_ANNEX_D):
        raise ValueError("unknown natural wet bulb model: %r" % natural_wet_bulb_model)

    use = use or SourceSelection()
    if open_meteo is None:
        use = SourceSelection.none()

    # env_params was only ever called for one site-day. On every other day
    # Open-Meteo supplies the wet bulb and humidity instead, justified by the
    # provenance audit, which showed the two agree to 0.1 degC and are not
    # independent sources anyway (FORTYGUARD_API_CONTRACT.md section 6).
    if env is None:
        if open_meteo is None or not open_meteo.can_replace_env_params:
            raise ImplausibleValue(
                "no env_params for this site-day and no Open-Meteo day carrying "
                "wet_bulb_temperature_2m / relative_humidity_2m to stand in for "
                "it. Fetch one with scripts/fetch_openmeteo.py."
            )
    date = env.date if env is not None else open_meteo.date
    elevation_m = env.elevation_m if env is not None else open_meteo.elevation_m
    utc_offset = (
        env.utc_offset_hours if env is not None else open_meteo.utc_offset_hours
    )

    cell = grid.cell_at(site_longitude, site_latitude)
    notes = []

    if cell.diurnal_range_c <= 0.0:
        raise ImplausibleValue(
            "cell %d has zero diurnal range. This looks like a filter_type=1 "
            "snapshot, where temporal min == avg == max (see "
            "FORTYGUARD_API_CONTRACT.md section 4). M1 needs filter_type=3."
            % cell.tile_id
        )

    # --- diurnal shape ------------------------------------------------------
    if use.shape or env is None:
        shape_values: Sequence[float] = open_meteo.temperature_2m_c
        shape_source = SHAPE_OPEN_METEO
    else:
        shape_values = env.hourly("apparent_temperature_celsius")
        shape_source = SHAPE_FG_APPARENT
        notes.append(
            "Diurnal shape came from FortyGuard apparent temperature, not "
            "Open-Meteo. It carries humidity and wind effects, so it is a proxy "
            "for the dry-bulb shape, not the shape itself."
        )

    reconstruction = diurnal.reconstruct_dry_bulb(
        shape=shape_values,
        daily_min_c=cell.min_c,
        daily_mean_c=cell.mean_c,
        daily_max_c=cell.max_c,
        shape_source=shape_source,
    )
    if not reconstruction.warp_converged:
        notes.append(
            "Diurnal warp did not converge; gamma clamped to %.3f. FortyGuard's "
            "daily mean is not reachable from this shape."
            % reconstruction.warp_gamma
        )
    elif not reconstruction.warp_gamma_plausible:
        notes.append(
            "Diurnal warp gamma %.3f is outside the plausible band %s, the "
            "shape source and FortyGuard disagree about where the day's mass sits."
            % (reconstruction.warp_gamma, C.DIURNAL_WARP_GAMMA_PLAUSIBLE)
        )

    dry_bulb = reconstruction.dry_bulb_c

    # --- humidity and wet bulb ---------------------------------------------
    if env is not None:
        wet_bulb = env.hourly("wet_bulb_temperature_celsius")
        humidity = env.hourly("relative_humidity_percent")
        wet_bulb_source = (
            "fortyguard.env_params.wet_bulb_temperature_celsius (psychrometric)"
        )
    else:
        wet_bulb = open_meteo.wet_bulb_temperature_c
        humidity = open_meteo.relative_humidity_pct
        wet_bulb_source = (
            "openmeteo.wet_bulb_temperature_2m (psychrometric), env_params was "
            "never called for this site-day; the two agree to 0.1 degC"
        )

    # --- cloud --------------------------------------------------------------
    # Cloud drives two different terms: solar attenuation and longwave sky
    # emissivity, so it should come from the same provider as the radiation.
    if use.cloud or env is None:
        cloud = open_meteo.cloud_cover_fraction
        cloud_source = CLOUD_OPEN_METEO
    else:
        cloud = env.cloud_fraction()
        cloud_source = CLOUD_FORTYGUARD
        if env.cloud_scale_ambiguous:
            notes.append(
                "Cloud cover values all fall at or below 8 on this day, so "
                "percent and octas cannot be told apart from the data. Read as "
                "percent."
            )

    # --- solar --------------------------------------------------------------
    if use.solar or env is None:
        solar_day = solar.solar_day(
            date=date,
            latitude=site_latitude,
            longitude=site_longitude,
            utc_offset_hours=utc_offset,
        )
        # Open-Meteo measures the total; the model only supplies the beam/diffuse
        # split. Clamp the beam: at a sun a fraction of a degree above the
        # horizon, dividing by cos(z) can otherwise return a DNI above the solar
        # constant, which is not a weather condition.
        ghi = open_meteo.shortwave_radiation_w_m2
        dhi = tuple(
            g * solar.diffuse_fraction(p.cos_zenith)
            for g, p in zip(ghi, solar_day.positions)
        )
        dni = tuple(
            min((g - d) / p.cos_zenith, C.SOLAR_CONSTANT_W_M2)
            if p.cos_zenith > 0
            else 0.0
            for g, d, p in zip(ghi, dhi, solar_day.positions)
        )
        dhi = tuple(
            max(g - n * p.cos_zenith, 0.0)
            for g, n, p in zip(ghi, dni, solar_day.positions)
        )
        solar_source = SOLAR_OPEN_METEO
    else:
        solar_day = solar.solar_day(
            date=date,
            latitude=site_latitude,
            longitude=site_longitude,
            utc_offset_hours=utc_offset,
            anchor_daily_ghi_w_m2=env.clear_sky_ghi_w_m2,
            anchor_daily_dni_w_m2=env.clear_sky_dni_w_m2,
            anchor_daily_dhi_w_m2=env.clear_sky_dhi_w_m2,
            cloud_fraction=cloud,
        )
        ghi, dni, dhi = solar_day.ghi_w_m2, solar_day.dni_w_m2, solar_day.dhi_w_m2
        solar_source = SOLAR_ANCHORED
        if env.clear_sky_ghi_w_m2 is None:
            notes.append(
                "env_params returned no clear-sky GHI, so the solar curve is "
                "unanchored Haurwitz. Level is modelled, not measured."
            )

    # --- wind ---------------------------------------------------------------
    wind, wind_source, wind_assumed = _wind_series(open_meteo, use.wind, wind_speed_m_s)

    # --- compose ------------------------------------------------------------
    nwb_weight, globe_weight, dry_weight = C.WBGT_OUTDOOR_WEIGHTS
    indoor_nwb, indoor_globe, _ = C.WBGT_INDOOR_WEIGHTS
    outside_iso_range = 0

    hours = []
    for h in range(24):
        result = globe.globe_temperature(
            air_temperature_c=dry_bulb[h],
            relative_humidity_pct=humidity[h],
            air_speed_m_s=wind[h],
            dni_w_m2=dni[h],
            dhi_w_m2=dhi[h],
            ghi_w_m2=ghi[h],
            cloud_fraction=cloud[h],
            elevation_m=elevation_m,
            ground_albedo=ground_albedo,
        )

        mean_radiant = None
        if natural_wet_bulb_model == NWB_ISO_ANNEX_D:
            iso = nwb.from_globe(
                globe_temperature_c=result.globe_temperature_c,
                air_temperature_c=dry_bulb[h],
                air_speed_m_s=wind[h],
                relative_humidity_pct=humidity[h],
            )
            natural = iso.natural_wet_bulb_c
            mean_radiant = iso.mean_radiant_temperature_c
            if not iso.within_iso_table_range:
                outside_iso_range += 1
        else:
            natural = wet_bulb[h]

        # ISO 7243 Formula (2) applies only when there IS a solar load; Formula
        # (1) otherwise. At night the globe sits at about air temperature, so
        # the two agree to within hundredths and the switch is not a jump.
        solar_load = ghi[h] > 0.0
        if solar_load:
            value = (
                nwb_weight * natural
                + globe_weight * result.globe_temperature_c
                + dry_weight * dry_bulb[h]
            )
        else:
            value = indoor_nwb * natural + indoor_globe * result.globe_temperature_c

        if not C.WBGT_PLAUSIBLE_MIN <= value <= C.WBGT_PLAUSIBLE_MAX:
            raise ImplausibleValue(
                "WBGT %.2f at hour %d is outside the sanity band %s. That is a "
                "bug, not weather (constants.py section 5)."
                % (value, h, (C.WBGT_PLAUSIBLE_MIN, C.WBGT_PLAUSIBLE_MAX))
            )

        hours.append(
            WBGTHour(
                hour=h,
                wbgt_c=value,
                dry_bulb_c=dry_bulb[h],
                natural_wet_bulb_c=natural,
                psychrometric_wet_bulb_c=wet_bulb[h],
                globe_c=result.globe_temperature_c,
                globe_excess_over_air_c=result.excess_over_air_c,
                mean_radiant_c=mean_radiant,
                relative_humidity_pct=humidity[h],
                cloud_fraction=cloud[h],
                wind_speed_m_s=wind[h],
                ghi_w_m2=ghi[h],
                dni_w_m2=dni[h],
                dhi_w_m2=dhi[h],
                solar_elevation_deg=solar_day.positions[h].elevation_deg,
                solar_load_weights=solar_load,
            )
        )

    if outside_iso_range:
        notes.append(
            "ISO 7243 Annex D was evaluated outside the domain Table D.1 "
            "tabulates (t_nw 15-30 degC, air speed <= %.1f m/s) for %d of 24 "
            "hours. Annex D's own preamble calls the method 'not recommended'."
            % (C.ISO_TABLE_D1_MAX_SPEED_M_S, outside_iso_range)
        )

    amplitude_check = diurnal.compare_amplitude(
        fortyguard_min_c=cell.min_c,
        fortyguard_max_c=cell.max_c,
        reference_hourly_c=(
            open_meteo.temperature_2m_c if open_meteo is not None else None
        ),
        reference_source=SHAPE_OPEN_METEO if open_meteo is not None else "none",
        is_independent=open_meteo is not None,
    )

    assumed = []
    if wind_assumed:
        assumed.append("wind")
    if not use.solar:
        assumed.append("hourly solar shape (anchored to FortyGuard's daily mean)")
    if natural_wet_bulb_model == NWB_PSYCHROMETRIC:
        assumed.append(
            "natural wet bulb = psychrometric wet bulb (constants.py 5b)"
        )

    if natural_wet_bulb_model == NWB_PSYCHROMETRIC:
        nwb_source = (
            "ASSUMED equal to the psychrometric value. ISO 7243:2017 B.1 says "
            "they differ; see constants.py 5b."
        )
    else:
        nwb_source = "ISO 7243:2017 Formula (D.1) from modelled globe via (D.2)"

    provenance = Provenance(
        dry_bulb="fortyguard.heatmap filter_type=3 cell %d (temporal min/mean/max)"
        % cell.tile_id,
        dry_bulb_shape=shape_source,
        wet_bulb=wet_bulb_source,
        natural_wet_bulb=nwb_source,
        relative_humidity=("fortyguard.env_params.relative_humidity_percent"
                           if env is not None else "openmeteo.relative_humidity_2m"),
        cloud=cloud_source,
        solar=solar_source,
        wind=wind_source,
        globe_temperature="modelled: sphere energy balance (constants.py 5a)",
        assumed_inputs=tuple(assumed),
    )

    return WBGTDay(
        site_id=site_id,
        date=date,
        latitude=site_latitude,
        longitude=site_longitude,
        elevation_m=elevation_m,
        hours=tuple(hours),
        provenance=provenance,
        reconstruction=reconstruction,
        solar_day=solar_day,
        amplitude_check=amplitude_check,
        natural_wet_bulb_model=natural_wet_bulb_model,
        notes=tuple(notes),
    )


def wind_sensitivity(
    site_id: str,
    grid: TemperatureGrid,
    env: EnvParamsDay,
    site_longitude: float,
    site_latitude: float,
    hour: int,
    speeds_m_s: Sequence[float],
    **kwargs,
) -> Dict[float, float]:
    """WBGT at one hour across a band of assumed wind speeds.

    Wind was the pipeline's only wholly unsourced input before an Open-Meteo
    fixture existed (constants.py 5d), so the honest presentation of a WBGT
    computed without one is a band, not a point.
    """
    out: Dict[float, float] = {}
    for speed in speeds_m_s:
        day = build_wbgt_day(
            site_id=site_id,
            grid=grid,
            env=env,
            site_longitude=site_longitude,
            site_latitude=site_latitude,
            wind_speed_m_s=speed,
            **kwargs
        )
        out[speed] = day.at(hour).wbgt_c
    return out
