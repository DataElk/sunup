"""Hourly dry-bulb reconstruction from a daily min/mean/max plus a shape.

CLAUDE.md's data strategy in one function: one `filter_type=3` call per site-day
gives that cell's own min, mean and max (the TEMPORAL axis, see
FORTYGUARD_API_CONTRACT.md section 4, which warns these are easily confused with
the spatial stats). A separate, spatially coarse source supplies the diurnal
shape. FortyGuard sets amplitude and offset; the shape provider sets shape.

The subtlety: mapping a shape linearly onto [min, max] honours two of
FortyGuard's three numbers and throws the third away. We keep it. The normalised
shape is warped by n -> n**gamma, with gamma solved so the reconstructed daily
mean equals FortyGuard's. The warp is monotone and fixes both endpoints, so min
and max still come out exact.

gamma is also the honest diagnostic: gamma far from 1 means the shape source and
FortyGuard disagree about where the day's mass sits, which is exactly the
recent-date smoothing bias recorded in fixtures/MANIFEST.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from sunup import constants as C
from sunup.errors import ImplausibleValue


@dataclass(frozen=True)
class DiurnalReconstruction:
    """24 hourly dry-bulb values and everything needed to defend them."""

    dry_bulb_c: Tuple[float, ...]
    shape_source: str
    warp_gamma: float
    warp_converged: bool
    warp_gamma_plausible: bool
    # What we were asked to reproduce, and what we actually reproduced.
    target_min_c: float
    target_mean_c: float
    target_max_c: float
    achieved_min_c: float
    achieved_mean_c: float
    achieved_max_c: float

    @property
    def mean_residual_c(self) -> float:
        return self.achieved_mean_c - self.target_mean_c

    @property
    def amplitude_c(self) -> float:
        return self.achieved_max_c - self.achieved_min_c


@dataclass(frozen=True)
class AmplitudeComparison:
    """CLAUDE.md: M1 must compare FortyGuard's daily amplitude against an
    independent source's for the same site-day and record the discrepancy."""

    fortyguard_amplitude_c: float
    reference_amplitude_c: Optional[float]
    reference_source: str
    is_independent: bool
    note: str

    @property
    def discrepancy_c(self) -> Optional[float]:
        if self.reference_amplitude_c is None:
            return None
        return self.fortyguard_amplitude_c - self.reference_amplitude_c

    @property
    def ratio(self) -> Optional[float]:
        if not self.reference_amplitude_c:
            return None
        return self.fortyguard_amplitude_c / self.reference_amplitude_c


def normalise_shape(values: Sequence[float]) -> Tuple[float, ...]:
    """Map a series onto [0, 1] by its own min and max."""
    lo, hi = min(values), max(values)
    if hi - lo <= 0.0:
        return tuple(0.5 for _ in values)
    return tuple((v - lo) / (hi - lo) for v in values)


def _warped_mean(normalised: Sequence[float], gamma: float) -> float:
    return sum(n**gamma if n > 0.0 else 0.0 for n in normalised) / len(normalised)


def solve_warp_gamma(
    normalised: Sequence[float], target_fraction: float
) -> Tuple[float, bool]:
    """Find gamma with mean(n**gamma) == target_fraction. Returns (gamma, converged).

    mean(n**gamma) is strictly decreasing in gamma on [0, 1]-valued shapes, so
    bisection is safe. If the target lies outside what the warp can reach, gamma
    is clamped to the bound and ``converged`` is False, never silently faked.
    """
    lo, hi = C.DIURNAL_WARP_GAMMA_BOUNDS
    if _warped_mean(normalised, lo) < target_fraction:
        return lo, False
    if _warped_mean(normalised, hi) > target_fraction:
        return hi, False
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if _warped_mean(normalised, mid) > target_fraction:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-9:
            break
    gamma = 0.5 * (lo + hi)
    converged = abs(_warped_mean(normalised, gamma) - target_fraction) < 1e-6
    return gamma, converged


def reconstruct_dry_bulb(
    shape: Sequence[float],
    daily_min_c: float,
    daily_mean_c: float,
    daily_max_c: float,
    shape_source: str,
    match_daily_mean: bool = True,
) -> DiurnalReconstruction:
    """Fit ``shape`` between FortyGuard's daily min and max, preserving its mean."""
    if len(shape) != 24:
        raise ValueError("shape must have 24 values, got %d" % len(shape))
    if not daily_min_c <= daily_mean_c <= daily_max_c:
        raise ImplausibleValue(
            "FortyGuard daily stats are not ordered: min=%.4f mean=%.4f max=%.4f"
            % (daily_min_c, daily_mean_c, daily_max_c)
        )

    amplitude = daily_max_c - daily_min_c
    normalised = normalise_shape(shape)

    gamma, converged = 1.0, True
    plausible = True
    if match_daily_mean and amplitude > 0.0:
        target_fraction = (daily_mean_c - daily_min_c) / amplitude
        gamma, converged = solve_warp_gamma(normalised, target_fraction)
        lo, hi = C.DIURNAL_WARP_GAMMA_PLAUSIBLE
        plausible = lo <= gamma <= hi

    warped = tuple(n**gamma if n > 0.0 else 0.0 for n in normalised)
    dry_bulb = tuple(daily_min_c + w * amplitude for w in warped)

    return DiurnalReconstruction(
        dry_bulb_c=dry_bulb,
        shape_source=shape_source,
        warp_gamma=gamma,
        warp_converged=converged,
        warp_gamma_plausible=plausible,
        target_min_c=daily_min_c,
        target_mean_c=daily_mean_c,
        target_max_c=daily_max_c,
        achieved_min_c=min(dry_bulb),
        achieved_mean_c=sum(dry_bulb) / len(dry_bulb),
        achieved_max_c=max(dry_bulb),
    )


def night_limb_reversals(
    dry_bulb_c: Sequence[float], sunset_hour: float, sunrise_hour: float
) -> Tuple[int, float]:
    """How badly the overnight limb fails to cool monotonically.

    Returns (number of hours that WARM overnight, total warming in degC).

    Real dry bulb falls monotonically from the evening peak to just after
    sunrise. A shape source that carries humidity, FortyGuard's apparent
    temperature does, puts a spurious bump on that limb, because relative
    humidity peaks in the small hours. This function is how much that costs, in
    degrees, instead of a hand-wave.

    It is a DIAGNOSTIC, not a correction. The fix is an Open-Meteo
    temperature_2m fixture, which the pipeline already prefers when present.
    """
    hours = [h % 24 for h in range(int(sunset_hour) + 1, int(sunset_hour) + 1 + 24)]
    limb = []
    for h in hours:
        limb.append(h)
        if h == int(sunrise_hour) + 1:
            break
    reversals = 0
    warming = 0.0
    for previous, current in zip(limb, limb[1:]):
        delta = dry_bulb_c[current] - dry_bulb_c[previous]
        if delta > 0.0:
            reversals += 1
            warming += delta
    return reversals, warming


def compare_amplitude(
    fortyguard_min_c: float,
    fortyguard_max_c: float,
    reference_hourly_c: Optional[Sequence[float]],
    reference_source: str,
    is_independent: bool,
) -> AmplitudeComparison:
    """Record the amplitude discrepancy CLAUDE.md requires M1 to report.

    A comparison against FortyGuard's own apparent temperature is NOT
    independent, same provider, same grid, so ``is_independent`` is carried
    through to the report rather than being inferred from whether a number
    happens to exist.
    """
    fg_amplitude = fortyguard_max_c - fortyguard_min_c
    if reference_hourly_c is None:
        return AmplitudeComparison(
            fortyguard_amplitude_c=fg_amplitude,
            reference_amplitude_c=None,
            reference_source=reference_source,
            is_independent=False,
            note=(
                "No independent hourly reference cached. Fill with one Open-Meteo "
                "archive call for this site-day (hourly=temperature_2m) and commit "
                "it under fixtures/openmeteo/."
            ),
        )
    ref_amplitude = max(reference_hourly_c) - min(reference_hourly_c)
    note = (
        "Independent: Open-Meteo regional reanalysis vs FortyGuard cell."
        if is_independent
        else (
            "NOT independent: same provider as the amplitude under test. Records "
            "internal consistency only, not the smoothing bias in "
            "fixtures/MANIFEST.md."
        )
    )
    return AmplitudeComparison(
        fortyguard_amplitude_c=fg_amplitude,
        reference_amplitude_c=ref_amplitude,
        reference_source=reference_source,
        is_independent=is_independent,
        note=note,
    )
