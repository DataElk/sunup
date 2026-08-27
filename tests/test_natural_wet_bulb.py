"""ISO 7243:2017 Annex D, validated against the standard's own worked examples.

Table D.1 of ISO 7243:2017 tabulates 22 cases: given air temperature, 150 mm
globe temperature, air velocity and relative humidity, it gives the predicted
natural wet bulb temperature and the predicted WBGT. Reproducing that table is
the only way to know the implementation of Formulae (D.1) and (D.2) is right
without a wet wick and a wind tunnel.

Transcribed from ISO 7243:2017(E) Table D.1, pages 13-14.
"""

from __future__ import annotations

import pytest

from sunup import constants as C
from sunup.errors import ConvergenceError
from sunup.physics import natural_wet_bulb as nwb
from sunup.physics import psychrometrics as psy

# (t_a, t_g, v_a, RH%, t_nw, WBGT)
TABLE_D1 = [
    (25.0, 40.0, 0.3, 20, 17.3, 24.1),
    (25.0, 55.0, 0.3, 20, 21.1, 31.3),
    (25.0, 40.0, 0.9, 20, 16.7, 23.7),
    (25.0, 40.0, 0.3, 50, 21.7, 27.2),
    (25.0, 55.0, 0.3, 50, 25.0, 34.0),
    (25.0, 40.0, 0.9, 50, 21.4, 27.0),
    (25.0, 40.0, 0.3, 80, 25.5, 29.8),
    (25.0, 55.0, 0.3, 80, 28.4, 36.4),
    (25.0, 40.0, 0.9, 80, 25.3, 29.7),
    (35.0, 35.0, 0.3, 20, 19.7, 24.3),
    (35.0, 50.0, 0.3, 20, 23.1, 31.2),
    (35.0, 65.0, 0.3, 20, 26.4, 38.0),
    (35.0, 35.0, 0.9, 20, 19.1, 23.9),
    (35.0, 50.0, 0.9, 20, 22.5, 30.7),
    (35.0, 35.0, 0.3, 50, 26.5, 29.1),
    (35.0, 50.0, 0.3, 50, 29.2, 35.5),
    (35.0, 35.0, 0.9, 50, 26.3, 28.9),
    (35.0, 50.0, 0.9, 50, 28.9, 35.2),
    (45.0, 45.0, 0.3, 20, 26.1, 31.8),
    (45.0, 60.0, 0.3, 20, 29.0, 38.3),
    (45.0, 45.0, 0.9, 20, 25.6, 31.4),
    (45.0, 60.0, 0.9, 20, 28.3, 37.8),
]


@pytest.mark.parametrize("ta,tg,va,rh,tnw_iso,wbgt_iso", TABLE_D1)
def test_reproduces_iso_table_d1(ta, tg, va, rh, tnw_iso, wbgt_iso):
    result = nwb.from_globe(tg, ta, va, rh)
    assert result.natural_wet_bulb_c == pytest.approx(tnw_iso, abs=0.55), (
        "ta=%.0f tg=%.0f v=%.1f rh=%d: ISO says %.1f, we say %.2f"
        % (ta, tg, va, rh, tnw_iso, result.natural_wet_bulb_c)
    )


@pytest.mark.parametrize("ta,tg,va,rh,tnw_iso,wbgt_iso", TABLE_D1)
def test_reproduces_iso_table_d1_wbgt_column(ta, tg, va, rh, tnw_iso, wbgt_iso):
    """Table D.1's WBGT column uses ISO Formula (1), WITHOUT solar load.

    Checked by construction: with 0.7*tnw + 0.2*tg + 0.1*ta the column is out by
    up to 3.4 degC, and with 0.7*tnw + 0.3*tg it agrees to 0.4 degC. That is
    independent confirmation that the two ISO weightings are what the pipeline
    thinks they are.
    """
    result = nwb.from_globe(tg, ta, va, rh)
    indoor_nwb, indoor_globe, _ = C.WBGT_INDOOR_WEIGHTS
    wbgt = indoor_nwb * result.natural_wet_bulb_c + indoor_globe * tg
    assert wbgt == pytest.approx(wbgt_iso, abs=0.45)


def test_solar_load_form_would_not_match_table_d1():
    """Guards the claim above: the outdoor form is measurably wrong here."""
    nwb_w, globe_w, dry_w = C.WBGT_OUTDOOR_WEIGHTS
    worst = 0.0
    for ta, tg, va, rh, _tnw, wbgt_iso in TABLE_D1:
        result = nwb.from_globe(tg, ta, va, rh)
        outdoor = nwb_w * result.natural_wet_bulb_c + globe_w * tg + dry_w * ta
        worst = max(worst, abs(outdoor - wbgt_iso))
    assert worst > 3.0, worst


def test_worst_case_error_across_the_whole_table():
    errors = []
    for ta, tg, va, rh, tnw_iso, _wbgt in TABLE_D1:
        result = nwb.from_globe(tg, ta, va, rh)
        errors.append(abs(result.natural_wet_bulb_c - tnw_iso))
    assert max(errors) < 0.55, max(errors)
    assert sum(errors) / len(errors) < 0.30, sum(errors) / len(errors)


def test_no_radiant_load_puts_natural_close_to_psychrometric():
    """When the globe sits at air temperature there is no radiant enhancement,
    so the natural wet bulb collapses toward the psychrometric value. That is
    why constants.py 5b's simplification is defensible indoors and steadily
    worse as the sun comes up."""
    result = nwb.from_globe(35.0, 35.0, 0.5, 30.0)
    psychrometric = psy.psychrometric_wet_bulb_c(35.0, 30.0)
    assert abs(result.natural_wet_bulb_c - psychrometric) < 1.5


def test_radiant_load_pushes_natural_above_psychrometric():
    cool = nwb.from_globe(35.0, 35.0, 0.5, 30.0)
    hot = nwb.from_globe(65.0, 35.0, 0.5, 30.0)
    assert hot.natural_wet_bulb_c > cool.natural_wet_bulb_c
    assert hot.excess_over_psychrometric_c > 3.0


def test_wind_reduces_the_radiant_enhancement():
    calm = nwb.from_globe(55.0, 35.0, 0.3, 30.0)
    breezy = nwb.from_globe(55.0, 35.0, 3.0, 30.0)
    assert breezy.natural_wet_bulb_c < calm.natural_wet_bulb_c


def test_mean_radiant_equals_globe_when_globe_equals_air():
    """ISO Formula (D.2) degenerates correctly: no convective correction term."""
    assert nwb.mean_radiant_temperature_c(35.0, 35.0, 1.0) == pytest.approx(35.0)


def test_mean_radiant_exceeds_globe_when_globe_is_hotter_than_air():
    t_r = nwb.mean_radiant_temperature_c(50.0, 35.0, 0.3)
    assert t_r > 50.0


def test_phoenix_afternoon_falls_outside_the_iso_tabulated_domain():
    """The honest limit on Annex D here.

    Table D.1 tabulates air velocity only to 0.9 m/s, and Annex D's preamble
    says the calculation "is not recommended". Phoenix at 14:00 runs 3.3 m/s,
    so the flag must be raised, not swallowed.
    """
    result = nwb.from_globe(52.5, 40.2, 3.28, 22.9)
    assert not result.within_iso_table_range
    assert result.natural_wet_bulb_c > 24.0


def test_impossible_inputs_raise_rather_than_return_a_number():
    with pytest.raises(ConvergenceError):
        # A globe far colder than air at high wind drives D.2 negative.
        nwb.mean_radiant_temperature_c(-260.0, 50.0, 9.0)
