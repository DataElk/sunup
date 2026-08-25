"""M5 exit test — validation and packaging.

SPEC.md, milestone M5:

    Project the forward ramp, then retrieve what actually happened and overlay
    the two. Writeup, demo video, README with caveats stated up front.

    Exit: the forecast-vs-actual overlay renders from real data. Every [CHECK]
    tag in constants.py has been resolved to [VERIFIED] or explicitly flagged as
    an open caveat in the writeup.

"Renders from real data" is checkable here: the overlay payload is generated,
carries no hand-written numbers, and its predicted arm is genuinely blind to the
actual arm. The second clause is checked as a completeness property -- every
[CHECK] constant must be accounted for somewhere, either verified in place or
named in the triage.
"""

from __future__ import annotations

import json
import os
import re

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP = os.path.join(ROOT, "app")
OVERLAY = os.path.join(APP, "data", "overlay.js")
CONSTANTS = os.path.join(ROOT, "src", "acclimate", "constants.py")


@pytest.fixture(scope="module")
def overlay():
    with open(OVERLAY, "r", encoding="utf-8") as fh:
        text = fh.read()
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


def read(*parts):
    with open(os.path.join(APP, *parts), "r", encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# The overlay renders from real data
# ---------------------------------------------------------------------------


def test_the_overlay_is_generated_not_hand_edited():
    with open(OVERLAY, "r", encoding="utf-8") as fh:
        first = fh.readline()
    assert "GENERATED" in first
    assert "build_overlay_data.py" in first


def test_the_projection_is_blind_to_the_actual_days(overlay):
    """The whole point. Every projected day must fall strictly after the as-of
    date, so the model could not have seen it when it projected."""
    as_of = overlay["asOf"]
    for subject in overlay["subjects"]:
        for pair in subject["pairs"]:
            assert pair["predicted"]["date"] > as_of, subject["name"]
            assert pair["actual"]["date"] > as_of, subject["name"]
            assert pair["predicted"]["date"] == pair["actual"]["date"]
        for day in subject["history"]:
            assert day["date"] <= as_of, subject["name"]


def test_every_projected_day_has_a_measured_counterpart(overlay):
    for subject in overlay["subjects"]:
        assert len(subject["pairs"]) == overlay["horizon"]
        for pair in subject["pairs"]:
            assert pair["predicted"]["projected"] is True
            assert pair["actual"]["projected"] is False


def test_the_error_is_the_difference_it_claims_to_be(overlay):
    for subject in overlay["subjects"]:
        for pair in subject["pairs"]:
            assert (pair["minutesError"]
                    == pair["predicted"]["minutes"] - pair["actual"]["minutes"])


def test_the_summary_statistics_match_the_days(overlay):
    """No hand-written headline numbers."""
    for subject in overlay["subjects"]:
        errors = [abs(p["minutesError"]) for p in subject["pairs"]]
        signed = [p["minutesError"] for p in subject["pairs"]]
        assert subject["maxAbsMinutesError"] == max(errors)
        assert round(sum(errors) / len(errors), 1) == subject["meanAbsMinutesError"]
        assert round(sum(signed) / len(signed), 1) == subject["meanSignedMinutesError"]
        assert subject["bandsMatched"] == sum(
            1 for p in subject["pairs"] if p["bandMatched"])


def test_the_method_is_named_and_the_backtest_is_declared(overlay):
    """A backtest presented as a live forecast would be the exact kind of
    overclaim this project spent its time removing."""
    assert overlay["isBacktest"] is True
    assert "repeat_day" in overlay["method"]
    assert "backtest" in overlay["caveat"].lower()
    assert "not a live forecast" in overlay["caveat"]
    source = read("js", "overlay.js")
    assert "data.caveat" in source, "the caveat must reach the screen"


def test_a_degenerate_subject_is_flagged_not_banked(overlay):
    """A worker prescribed zero on every day scores a perfect band match while
    showing no skill. That number must not be presented as accuracy."""
    for subject in overlay["subjects"]:
        minutes = {p["actual"]["minutes"] for p in subject["pairs"]}
        minutes |= {p["predicted"]["minutes"] for p in subject["pairs"]}
        assert subject["degenerate"] == (len(minutes) == 1), subject["name"]
        if subject["degenerate"]:
            assert subject["degenerateNote"]
            assert subject["bandsMatched"] == subject["bandsTotal"]
    source = read("js", "overlay.js")
    assert "degenerate" in source
    assert "overlay-value-void" in source


def test_the_bias_direction_is_reported_not_just_the_magnitude(overlay):
    """Direction matters more than magnitude for a safety product: erring low
    costs hours, erring high sends a man out too long."""
    for subject in overlay["subjects"]:
        bias = subject["meanSignedMinutesError"]
        expected = "conservative" if bias < 0 else ("permissive" if bias > 0 else "none")
        assert subject["biasDirection"] == expected, subject["name"]
        assert subject["daysPermissive"] == sum(
            1 for p in subject["pairs"] if p["minutesError"] > 0)
    source = read("js", "overlay.js")
    assert "biasDirection" in source


def test_the_overlay_view_is_reachable_and_offline():
    html = read("index.html")
    assert 'data-view="overlay"' in html
    assert 'src="data/overlay.js"' in html
    assert "http://" not in html
    source = read("js", "overlay.js")
    for forbidden in ("fetch(", "XMLHttpRequest", "WebSocket"):
        assert forbidden not in source, forbidden


def test_the_chart_reuses_the_projected_treatment():
    """Projected is dashed at --projected-alpha everywhere else in the product;
    a second visual language for the same idea would be a defect."""
    css = read("styles", "components.css")
    block = css[css.index(".overlay-predicted-line"):]
    block = block[:block.index("}")]
    assert "--projected-stroke" in block
    assert "stroke-dasharray" in block
    assert "--projected-alpha" in block


# ---------------------------------------------------------------------------
# Every [CHECK] is accounted for
# ---------------------------------------------------------------------------


def test_every_check_tagged_constant_is_accounted_for():
    """Not "all verified" -- that is not achievable against paywalled standards.
    The requirement is that none is left silently unexamined: each one is either
    verified in place, or named in the section 0b triage, or sits inside a block
    that states why it cannot be closed."""
    with open(CONSTANTS, "r", encoding="utf-8") as fh:
        source = fh.read()
    assert "0b. VERIFICATION TRIAGE" in source
    triage = source[source.index("0b. VERIFICATION TRIAGE"):
                    source.index("# 1. METABOLIC WORKLOAD")]

    names = set()
    for line in source.split("\n"):
        match = re.match(r"^([A-Z][A-Z0-9_]{2,})\s*[:=]", line)
        if match and "[CHECK" in line:
            names.add(match.group(1))

    unexplained = [n for n in sorted(names) if n not in triage]
    assert not unexplained, (
        "these [CHECK] constants are not named in the section 0b triage: %s"
        % ", ".join(unexplained))


def test_the_load_bearing_constants_carry_their_measured_sensitivity():
    with open(CONSTANTS, "r", encoding="utf-8") as fh:
        source = fh.read()
    for name in ("GLOBE_SOLAR_ABSORPTIVITY", "AIR_CONDUCTIVITY_REF_W_M_K"):
        block = source[max(0, source.index(name) - 1200): source.index(name) + 200]
        assert "audit_constants.py" in block or "MEASURED SENSITIVITY" in block, name


def test_the_audits_are_runnable_scripts():
    """Three claims were revised by these audits. Each has to survive as
    something a reader can run, not a paragraph asserting a result."""
    for name in ("audit_resolution.py", "audit_ladder.py", "audit_constants.py"):
        path = os.path.join(ROOT, "scripts", name)
        assert os.path.exists(path), name
        with open(path, "r", encoding="utf-8") as fh:
            assert "def main(" in fh.read(), name
