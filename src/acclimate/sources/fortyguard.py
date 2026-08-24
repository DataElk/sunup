"""Typed views over FortyGuard payloads.

Two endpoints matter to M1:

  /v1/heatmap with filter_type=3 -> per-cell TEMPORAL min/mean/max for one day.
      FORTYGUARD_API_CONTRACT.md section 4 flags the trap: the identically named
      stats under ``stats_data`` are the SPATIAL axis. This module only ever
      reads the per-cell properties for the temporal numbers, and exposes the
      spatial ones under names that cannot be confused with them.

  /v1/env_params with filter_type=3 -> 24 hourly values per parameter, EXCEPT
      solar_irradiance, which is a single daily clear-sky mean (section 6,
      trap 1). Spatially coarse: one call per metro per day, never per site
      (trap 3).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from acclimate import constants as C
from acclimate.errors import ImplausibleValue
from acclimate.sources.fixtures import unwrap_result

# FortyGuard documents this field as octas (0-8). The captured payload returns
# 0-100. See FORTYGUARD_API_CONTRACT.md section 6, trap 4.
CLOUD_FIELD = "cloud_cover_octas"
CLOUD_SCALE_PERCENT = "percent"
CLOUD_SCALE_OCTAS = "octas"


# ---------------------------------------------------------------------------
# /v1/heatmap
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TemperatureCell:
    """One tile. min/mean/max here are TEMPORAL — within the day, for this cell."""

    tile_id: int
    mean_c: float
    min_c: float
    max_c: float
    ring: Tuple[Tuple[float, float], ...]  # (lon, lat) vertices

    @property
    def diurnal_range_c(self) -> float:
        return self.max_c - self.min_c

    @property
    def centroid(self) -> Tuple[float, float]:
        lons = [p[0] for p in self.ring]
        lats = [p[1] for p in self.ring]
        return sum(lons) / len(lons), sum(lats) / len(lats)

    def contains(self, lon: float, lat: float) -> bool:
        return _point_in_ring(lon, lat, self.ring)


@dataclass(frozen=True)
class TemperatureGrid:
    cells: Tuple[TemperatureCell, ...]
    spatial_min_c: Optional[float]
    spatial_max_c: Optional[float]
    spatial_mean_c: Optional[float]
    spatial_std_c: Optional[float]

    @property
    def spatial_spread_c(self) -> Optional[float]:
        if self.spatial_min_c is None or self.spatial_max_c is None:
            return None
        return self.spatial_max_c - self.spatial_min_c

    def cell_at(self, lon: float, lat: float) -> TemperatureCell:
        """The cell containing the point, else the nearest cell centroid.

        Parcel-scale spatial spread is 0.04-0.36 degC (fixtures/MANIFEST.md), so
        the choice barely moves WBGT — but picking deterministically keeps the
        regression reproducible.
        """
        for cell in self.cells:
            if cell.contains(lon, lat):
                return cell
        return min(
            self.cells,
            key=lambda c: (c.centroid[0] - lon) ** 2 + (c.centroid[1] - lat) ** 2,
        )


def _point_in_ring(lon: float, lat: float, ring: Sequence[Tuple[float, float]]) -> bool:
    """Ray casting. Cells are axis-aligned grid rectangles, but this is general."""
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if (y1 > lat) != (y2 > lat):
            x_cross = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lon < x_cross:
                inside = not inside
    return inside


def parse_temperature_grid(payload: Dict[str, Any]) -> TemperatureGrid:
    """Parse a ``tcm`` heatmap response (filter_type 1 or 3)."""
    result = unwrap_result(payload)
    features = result.get("map_data", {}).get("features")
    if not features:
        raise ValueError("no map_data.features in payload")

    cells: List[TemperatureCell] = []
    for feature in features:
        props = feature.get("properties", {})
        if "average_temperature" not in props:
            raise ValueError(
                "properties has no average_temperature; keys=%s. An analysis "
                "heatmap (exceedance/persistence) uses properties.value instead "
                "— see FORTYGUARD_API_CONTRACT.md section 5." % sorted(props)
            )
        coords = feature.get("geometry", {}).get("coordinates", [[]])[0]
        cells.append(
            TemperatureCell(
                tile_id=int(props.get("tile_id", feature.get("id", len(cells)))),
                mean_c=float(props["average_temperature"]),
                min_c=float(props["min_temperature"]),
                max_c=float(props["max_temperature"]),
                ring=tuple((float(p[0]), float(p[1])) for p in coords),
            )
        )

    stats = result.get("stats_data", {}).get("temperature_stats", {})
    return TemperatureGrid(
        cells=tuple(cells),
        spatial_min_c=_opt_float(stats.get("minimum")),
        spatial_max_c=_opt_float(stats.get("maximum")),
        spatial_mean_c=_opt_float(stats.get("mean")),
        spatial_std_c=_opt_float(stats.get("standard_deviation")),
    )


def _opt_float(value: Any) -> Optional[float]:
    return None if value is None else float(value)


# ---------------------------------------------------------------------------
# /v1/env_params
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EnvParamsDay:
    date: dt.date
    latitude: float
    longitude: float
    elevation_m: float
    utc_offset_hours: float
    timestamps: Tuple[str, ...]
    parameters: Dict[str, Tuple[Optional[float], ...]]
    clear_sky_ghi_w_m2: Optional[float]
    clear_sky_dni_w_m2: Optional[float]
    clear_sky_dhi_w_m2: Optional[float]
    temperature_anchor_c: Optional[float]  # the value WE supplied, echoed back
    cloud_scale_ambiguous: bool

    def hourly(self, name: str) -> Tuple[float, ...]:
        """24 non-null values, or raise. Nulls are a data fault, not a zero.

        FORTYGUARD_API_CONTRACT.md section 6: methane_ppb and co2_ppm came back
        all-null on the verified call, so "the key exists" is not "the data
        exists".
        """
        if name not in self.parameters:
            raise KeyError(
                "%s not in this env_params response; available: %s"
                % (name, sorted(self.parameters))
            )
        values = self.parameters[name]
        missing = [i for i, v in enumerate(values) if v is None]
        if missing:
            raise ImplausibleValue(
                "%s has nulls at hours %s — refusing to substitute zeros" % (name, missing)
            )
        return tuple(float(v) for v in values)

    def cloud_fraction(self, scale: str = CLOUD_SCALE_PERCENT) -> Tuple[float, ...]:
        """Cloud cover as a fraction in [0, 1].

        The field is named ``cloud_cover_octas`` but the captured payload runs
        0-100, so it is PERCENT. ``cloud_scale_ambiguous`` is set when a given
        day's values all happen to fall at or below 8, where the two scales
        cannot be told apart from the data alone.
        """
        raw = self.hourly(CLOUD_FIELD)
        divisor = 100.0 if scale == CLOUD_SCALE_PERCENT else 8.0
        if scale == CLOUD_SCALE_PERCENT and max(raw) > 100.0:
            raise ImplausibleValue("cloud cover above 100: max=%.2f" % max(raw))
        return tuple(min(max(v / divisor, 0.0), 1.0) for v in raw)


def parse_env_params(payload: Dict[str, Any], location_index: int = 0) -> EnvParamsDay:
    result = unwrap_result(payload)
    metadata = result["metadata"]
    locations = result["locations"]
    if not locations:
        raise ValueError("env_params returned no locations")
    loc = locations[location_index]

    timestamps = tuple(metadata["timestamps"])
    if len(timestamps) != 24:
        raise ValueError("expected 24 hourly timestamps, got %d" % len(timestamps))
    date = dt.date.fromisoformat(timestamps[0][:10])

    parameters: Dict[str, Tuple[Optional[float], ...]] = {}
    for name, values in (loc.get("parameters") or {}).items():
        if isinstance(values, list) and len(values) == 24:
            parameters[name] = tuple(
                None if v is None else float(v) for v in values
            )

    solar = (loc.get("solar_irradiance") or {}).get("clear_sky") or {}
    cloud = parameters.get(CLOUD_FIELD)
    ambiguous = bool(cloud) and all(
        v is not None and v <= 8.0 for v in cloud
    )

    return EnvParamsDay(
        date=date,
        latitude=float(loc["lat"]),
        longitude=float(loc["lon"]),
        elevation_m=float(loc.get("elevation", 0.0)),
        utc_offset_hours=float(metadata.get("timezone_offset_hours", 0)),
        timestamps=timestamps,
        parameters=parameters,
        clear_sky_ghi_w_m2=_opt_float(solar.get("ghi")),
        clear_sky_dni_w_m2=_opt_float(solar.get("dni")),
        clear_sky_dhi_w_m2=_opt_float(solar.get("dhi")),
        temperature_anchor_c=_opt_float(loc.get("temperature")),
        cloud_scale_ambiguous=ambiguous,
    )


# ---------------------------------------------------------------------------
# /v1/heatmap — analysis types (exceedance / persistence / time_of_measure)
# ---------------------------------------------------------------------------
# FORTYGUARD_API_CONTRACT.md section 5. A DIFFERENT SCHEMA from `tcm`: cells
# carry `properties.value`, not `average_temperature`, and the unit is announced
# in `stats_data.units`. Code that reads the tcm field here finds nothing.


@dataclass(frozen=True)
class AnalysisCell:
    tile_id: int
    value: float          # clamped
    raw_value: float      # exactly what the API said
    ring: Tuple[Tuple[float, float], ...]

    @property
    def was_clamped(self) -> bool:
        return self.value != self.raw_value

    @property
    def centroid(self) -> Tuple[float, float]:
        lons = [p[0] for p in self.ring]
        lats = [p[1] for p in self.ring]
        return sum(lons) / len(lons), sum(lats) / len(lats)

    def contains(self, lon: float, lat: float) -> bool:
        return _point_in_ring(lon, lat, self.ring)


@dataclass(frozen=True)
class AnalysisGrid:
    """An exceedance/persistence grid, clamped at the parse boundary.

    `clamped_low` and `clamped_high` are the count of cells that had to be
    corrected. They are part of the result, not a log line: a grid where many
    cells clamp is telling you the threshold is badly chosen (contract section 5,
    "Threshold selection"), and that should be visible to whoever ranks sites.
    """

    cells: Tuple[AnalysisCell, ...]
    analytic_type: str
    units: str
    window_hours: float
    clamped_low: int
    clamped_high: int
    stats_min: Optional[float]
    stats_max: Optional[float]
    stats_mean: Optional[float]

    @property
    def clamped_total(self) -> int:
        return self.clamped_low + self.clamped_high

    @property
    def clamped_fraction(self) -> float:
        return self.clamped_total / len(self.cells) if self.cells else 0.0

    def values(self) -> Tuple[float, ...]:
        return tuple(c.value for c in self.cells)

    def percentile(self, q: float) -> float:
        """Rank by percentile, never absolute min/max — contract section 5
        mandates this because extremes cluster on the AOI boundary."""
        if not self.cells:
            raise ValueError("empty grid")
        ordered = sorted(self.values())
        if len(ordered) == 1:
            return ordered[0]
        position = (len(ordered) - 1) * min(max(q, 0.0), 100.0) / 100.0
        low = int(position)
        high = min(low + 1, len(ordered) - 1)
        return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def clamp_exceedance_hours(value: float, window_hours: float) -> float:
    """The mandatory clamp from FORTYGUARD_API_CONTRACT.md section 5.

        value = max(0.0, min(value, window_hours))

    The field is interpolated, not counted, so it goes negative and overshoots
    the window. A negative duration must never reach the stimulus term.
    """
    return max(C.EXCEEDANCE_CLAMP_MIN_H, min(float(value), float(window_hours)))


def parse_analysis_grid(
    payload: Dict[str, Any], window_hours: float
) -> AnalysisGrid:
    """Parse an analysis heatmap, clamping every cell on the way in.

    `window_hours` is the length of the requested window and must be supplied by
    the caller — the response does not carry it, and clamping to the wrong
    ceiling is worse than not clamping at all.
    """
    if window_hours <= 0:
        raise ValueError("window_hours must be positive; got %r" % window_hours)
    result = unwrap_result(payload)
    features = result.get("map_data", {}).get("features")
    if not features:
        raise ValueError("no map_data.features in payload")

    stats = result.get("stats_data", {}) or {}
    cells: List[AnalysisCell] = []
    low = high = 0
    for feature in features:
        props = feature.get("properties", {})
        if "value" not in props:
            raise ValueError(
                "properties has no `value`; keys=%s. A tcm heatmap uses "
                "average/min/max_temperature instead — see "
                "FORTYGUARD_API_CONTRACT.md section 5." % sorted(props)
            )
        raw = float(props["value"])
        if raw < -C.EXCEEDANCE_IMPLAUSIBLE_MARGIN_H or (
            raw > window_hours + C.EXCEEDANCE_IMPLAUSIBLE_MARGIN_H
        ):
            raise ImplausibleValue(
                "cell %s value %.4f is %.1f h outside a %.1f h window — that is a "
                "wrong window length or wrong units, not interpolation noise."
                % (props.get("tile_id"), raw,
                   max(-raw, raw - window_hours), window_hours)
            )
        clamped = clamp_exceedance_hours(raw, window_hours)
        if clamped > raw:
            low += 1
        elif clamped < raw:
            high += 1
        coords = feature.get("geometry", {}).get("coordinates", [[]])[0]
        cells.append(
            AnalysisCell(
                tile_id=int(props.get("tile_id", feature.get("id", len(cells)))),
                value=clamped,
                raw_value=raw,
                ring=tuple((float(p[0]), float(p[1])) for p in coords),
            )
        )

    return AnalysisGrid(
        cells=tuple(cells),
        analytic_type=str(stats.get("analytic_type", "unknown")),
        units=str(stats.get("units", "hour")),
        window_hours=float(window_hours),
        clamped_low=low,
        clamped_high=high,
        stats_min=_opt_float(stats.get("min")),
        stats_max=_opt_float(stats.get("max")),
        stats_mean=_opt_float(stats.get("mean")),
    )
