"""M4 exit test — the interface.

SPEC.md, milestone M4:

    Supervisor roster, ramp strip, counterfactual, compliance record export.
    Exit: every screen renders from the design tokens; a supervisor can answer
    "who works today and for how long" in under ten seconds; the adaptation
    number never appears on the collapsed row.

Three of those are checkable here and one is not. "Every screen renders from the
design tokens" is enforced by `node scripts/check-design.mjs`, which this module
shells out to. "The adaptation number never appears on a collapsed row" is
checked both by the lint's semantic rule and by reading the roster component
directly. The ten-second test is a human judgement; what IS testable is its
precondition — that the answer sits on the collapsed row and needs no
interaction to reach.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest

from acclimate import constants as C

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP = os.path.join(ROOT, "app")
DATA_FILE = os.path.join(APP, "data", "roster.js")


@pytest.fixture(scope="module")
def data():
    with open(DATA_FILE, "r", encoding="utf-8") as fh:
        text = fh.read()
    payload = text[text.index("{"): text.rindex("}") + 1]
    return json.loads(payload)


def read(*parts):
    with open(os.path.join(APP, *parts), "r", encoding="utf-8") as fh:
        return fh.read()


def strip_comments(source):
    """Executable JS only. A rule about what the code READS must not be
    satisfied or broken by what the comments SAY."""
    without_blocks = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return "\n".join(line for line in without_blocks.split("\n")
                     if not line.strip().startswith("//"))


# ---------------------------------------------------------------------------
# "Every screen renders from the design tokens"
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_the_design_lint_passes():
    """DESIGN_SYSTEM.md: the lint blocks the build, it is not advisory."""
    result = subprocess.run(
        ["node", os.path.join("scripts", "check-design.mjs")],
        cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_no_component_file_contains_a_literal_colour():
    """The rule the whole token system rests on."""
    css = read("styles", "components.css")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css)
    assert not re.search(r"\brgba?\s*\(", css)
    # And it does use the tokens, rather than avoiding colour altogether.
    assert css.count("var(--") > 80


def test_the_page_links_the_token_stylesheet_first():
    html = read("index.html")
    tokens = html.index("tokens.css")
    components = html.index("components.css")
    assert tokens < components, "components must be able to override nothing"


def test_no_emoji_anywhere_in_the_interface():
    """DESIGN_SYSTEM.md non-negotiable 5: drawn SVG only."""
    emoji = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
    for name in ("index.html", os.path.join("styles", "components.css")):
        assert not emoji.search(read(name)), name
    for name in ("roster.js", "detail.js", "rampstrip.js", "compliance.js", "main.js"):
        assert not emoji.search(read("js", name)), name


def test_icons_are_drawn_svg():
    html = read("index.html")
    assert html.count("<svg") >= 4
    assert "viewBox" in html


# ---------------------------------------------------------------------------
# "The adaptation number never appears on the collapsed row"
# ---------------------------------------------------------------------------


def test_the_roster_component_never_reads_the_adaptation_field():
    """DESIGN_SYSTEM.md non-negotiable 10, checked at the source.

    The field ships in the payload because the DETAIL view needs it. The roster
    must never touch it — a foreman gets minutes.
    """
    code = strip_comments(read("js", "roster.js"))
    assert "adaptation" not in code, "roster.js reads the adaptation state"


def test_the_detail_component_does_show_it():
    """The other half: it must be reachable when the foreman asks why."""
    detail = read("js", "detail.js")
    assert "adaptation" in detail
    assert "Adaptation state" in detail


def test_the_payload_carries_adaptation_for_the_detail_view(data):
    for worker in data["workers"]:
        assert "adaptation" in worker["today"]
        assert 0.0 <= worker["today"]["adaptation"] <= 1.0


# ---------------------------------------------------------------------------
# "Who works today and for how long" — the precondition for the ten-second test
# ---------------------------------------------------------------------------


def test_every_worker_answers_the_question_without_interaction(data):
    """Name, status and minutes are all on the collapsed row."""
    assert data["workers"], "empty roster"
    for worker in data["workers"]:
        assert worker["name"]
        today = worker["today"]
        assert isinstance(today["minutes"], int)
        assert today["status"] in {
            "cleared", "reduced", "restricted", "stop", "absent"}


def test_the_roster_row_renders_name_status_and_minutes():
    roster = read("js", "roster.js")
    for token in ("worker.name", "statusChip", "day.minutes"):
        assert token in roster, token


def test_rows_are_sorted_worst_first():
    """A supervisor scanning for who to intervene on reads from the top."""
    roster = read("js", "roster.js")
    assert "SEVERITY" in roster
    assert re.search(r"stop:\s*0", roster), "stop-work must sort first"


# ---------------------------------------------------------------------------
# The counterfactual — non-negotiable 9
# ---------------------------------------------------------------------------


def test_every_worker_carries_the_calendar_counterfactual(data):
    for worker in data["workers"]:
        today = worker["today"]
        assert "calendarMinutes" in today
        assert today["divergence"] == today["minutes"] - today["calendarMinutes"]


def test_the_calendar_figure_matches_the_osha_rule(data):
    for worker in data["workers"]:
        today = worker["today"]
        expected_pct = C.CALENDAR_RAMP_PCT_BY_DAY.get(today["dayOnJob"], 100)
        expected = round(expected_pct / 100.0 * worker["shiftHours"] * 60)
        assert today["calendarMinutes"] == expected, worker["name"]


def test_both_roster_and_detail_render_the_counterfactual():
    assert "counterfactualCell" in read("js", "roster.js")
    assert "counterfactual" in read("js", "detail.js")


def test_the_divergence_is_not_uniformly_one_directional(data):
    """The model is not simply "more cautious than OSHA". On a light trade early
    in the ramp it clears MORE than the calendar, and a demo that only ever
    shows restriction would misrepresent it."""
    signs = {(-1 if w["today"]["divergence"] < 0 else 1) for w in data["workers"]}
    assert signs == {-1, 1}, "expected divergence in both directions"


# ---------------------------------------------------------------------------
# The ramp strip — the signature
# ---------------------------------------------------------------------------


def test_the_strip_spans_seven_back_today_and_six_ahead(data):
    assert data["daysBehind"] == 7
    assert data["daysAhead"] == 6
    for worker in data["workers"]:
        assert len(worker["strip"]) == data["daysBehind"] + 1 + data["daysAhead"]


def test_projected_days_are_flagged_and_all_follow_today(data):
    """DESIGN_SYSTEM.md non-negotiable 11 — an honesty requirement."""
    for worker in data["workers"]:
        observed = [d for d in worker["strip"] if not d["projected"]]
        projected = [d for d in worker["strip"] if d["projected"]]
        assert len(projected) == data["daysAhead"]
        assert all(d["date"] <= data["today"] for d in observed)
        assert observed[-1]["date"] == data["today"]


def test_the_strip_draws_projection_differently():
    strip = read("js", "rampstrip.js")
    assert "cell-projected" in strip
    assert "adapt-line projected" in strip
    css = read("styles", "components.css")
    assert "--projected-dash" in css
    assert "--projected-alpha" in css


def test_colour_encodes_the_prescription_not_the_temperature():
    """DESIGN_SYSTEM.md non-negotiable 12. Bar HEIGHT carries heat; bar FILL
    carries the status band, which is the plan-vs-person fit."""
    strip = read("js", "rampstrip.js")
    assert "heatHeight" in strip
    assert "data-status" in strip
    css = read("styles", "components.css")
    for status in ("cleared", "reduced", "restricted", "stop"):
        assert '.ramp .bar[data-status="%s"]' % status in css


def test_the_strip_has_a_text_alternative():
    assert "aria-label" in read("js", "rampstrip.js")


# ---------------------------------------------------------------------------
# Compliance record
# ---------------------------------------------------------------------------


def test_the_record_states_the_regulatory_position_accurately():
    """constants.py section 6: the OSHA standard is PROPOSED, not law. A record
    that overstates it is worse than no record."""
    text = read("js", "compliance.js")
    assert "PROPOSED" in text
    assert "not finalised" in text
    assert "General Duty Clause" in text
    assert not re.search(r"OSHA (heat )?law\b", text)


def test_the_record_carries_provenance_and_names_its_assumptions(data):
    text = read("js", "compliance.js")
    assert "provenance" in text.lower()
    assert "ASSUMED" in text
    assert data["provenance"]["assumed"], "expected at least one assumed input"


def test_the_record_states_the_excluded_inputs():
    text = read("js", "compliance.js")
    for field in ("age", "sex", "BMI", "medical history", "residence"):
        assert field in text, field


def test_no_forbidden_input_appears_anywhere_in_the_payload(data):
    """constants.py section 7, enforced on what actually reaches the browser."""
    blob = json.dumps(data).lower()
    for field in C.FORBIDDEN_INPUTS:
        assert '"%s"' % field not in blob, field


# ---------------------------------------------------------------------------
# Offline
# ---------------------------------------------------------------------------


def test_the_interface_makes_no_network_calls():
    """SPEC.md hard constraint 6. The data is a script tag, not a fetch, so the
    page also works straight from file:// with no server."""
    for name in ("roster.js", "detail.js", "rampstrip.js", "compliance.js", "main.js"):
        source = read("js", name)
        for forbidden in ("fetch(", "XMLHttpRequest", "WebSocket", "import("):
            assert forbidden not in source, (name, forbidden)
    html = read("index.html")
    assert 'src="data/roster.js"' in html
    assert "http://" not in html


def test_the_data_file_is_generated_not_hand_edited():
    with open(DATA_FILE, "r", encoding="utf-8") as fh:
        first = fh.readline()
    assert "GENERATED" in first
    assert "build_roster_data.py" in first
