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
    for name in ("roster.js", "detail.js", "rampstrip.js", "compliance.js",
                 "main.js", "map.js", "format.js"):
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
    """Rendered as a RELATIONSHIP in both places -- one reading line carrying
    calendar, model and the signed gap -- never as two adjacent numbers with a
    strikethrough, which was a puzzle rather than a comparison."""
    for source in (read("js", "roster.js"), read("js", "detail.js")):
        assert "counterfactual" in source
        assert "cf-read" in source
        assert "line-through" not in source


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
        # Projected days must sit on consecutive dates AFTER today. They once
        # all carried today's date, which put the strip's "today" marker on
        # every future cell and made every projected tooltip claim to be today.
        dates = [d["date"] for d in projected]
        assert dates == sorted(set(dates)), worker["name"]
        assert all(d > data["today"] for d in dates), worker["name"]


def test_the_strip_draws_projection_differently():
    strip = read("js", "rampstrip.js")
    assert "cell-projected" in strip
    assert "adapt-line-projected" in strip
    css = read("styles", "components.css")
    # The dash pattern is a component decision, not a palette one, so it lives
    # in components.css; the palette owns the stroke colour and the alpha.
    assert "stroke-dasharray" in css
    assert "--projected-stroke" in css
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
    for name in ("roster.js", "detail.js", "rampstrip.js", "compliance.js",
                 "main.js", "map.js", "format.js"):
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


# ---------------------------------------------------------------------------
# The WHY column — rule 13, and the "five rows say the same thing" failure
# ---------------------------------------------------------------------------


def test_every_worker_gets_a_distinct_reason(data):
    """A column where five of six rows read "not yet adapted" is true and
    useless. The diagnosis is read off the binding hour, so it cannot collapse
    to one phrase unless the workers really are identical."""
    reasons = [w["levers"]["reason"] for w in data["workers"]]
    assert len(set(reasons)) == len(reasons), reasons


def test_every_worker_gets_a_distinct_priced_action(data):
    actions = [w["levers"]["short"] for w in data["workers"]]
    assert len(set(actions)) == len(actions), actions


def test_the_reason_names_the_hour_the_worker_goes_over(data):
    """The diagnosis has to be checkable against the hour table in the drawer."""
    for worker in data["workers"]:
        hours = worker["today"]["hours"]
        reason = worker["levers"]["reason"]
        over = [h for h in hours if h["overLimit"] > 0]
        if not over:
            assert "within limit" in reason, worker["name"]
            continue
        assert "%02d:00" % over[0]["hour"] in reason, (worker["name"], reason)
        worst = max(h["overLimit"] for h in over)
        assert ("%.1f" % worst) in reason, (worker["name"], reason)


def test_the_action_is_priced_in_minutes(data):
    for worker in data["workers"]:
        assert "min" in worker["levers"]["short"], worker["name"]


def test_the_worker_the_calendar_holds_back_is_named_as_such(data):
    """The teal case. Its reason must not read like a restriction."""
    held = [w for w in data["workers"] if w["today"]["mismatch"] == "under"]
    assert held, "the crew must retain at least one under-protective-calendar case"
    for worker in held:
        assert "calendar discards" in worker["levers"]["short"], worker["name"]


def test_a_lever_that_does_nothing_is_still_priced(data):
    """Site assignment is kept as a counterfactual precisely because M3
    measured it as NOT surviving. A lever you drop is a lever you cannot show
    to be worthless."""
    for worker in data["workers"]:
        assert "ifOtherSite" in worker["levers"], worker["name"]
        assert "ifEarlyShift" in worker["levers"]
        assert "ifFullyAdapted" in worker["levers"]


def test_no_lever_promises_a_trade_reassignment(data):
    """Rejected deliberately: moderate RAL 25.0 vs light 28.0 prices enormously
    but "make him an electrician" is not an action a foreman can take."""
    for worker in data["workers"]:
        assert "ifLighterWork" not in worker["levers"], worker["name"]


# ---------------------------------------------------------------------------
# Rule 12 — magnitude, not existence
# ---------------------------------------------------------------------------


def test_the_mismatch_indicator_encodes_magnitude():
    """A fixed stripe on five of six rows carries no information. The weight is
    |divergence| / shift and drives both width and opacity."""
    source = strip_comments(read("js", "roster.js"))
    assert "mismatch-weight" in source
    assert "divergence" in source

    css = read("styles", "components.css")
    assert "--mismatch-weight" in css
    assert "var(--mismatch-weight)" in css
    # Width and opacity must BOTH scale, otherwise the weakest cases vanish.
    stripe = css[css.index("td:first-child::before"):]
    stripe = stripe[:stripe.index("}")]
    assert "width" in stripe and "var(--mismatch-weight)" in stripe
    assert "opacity" in stripe


def test_the_mismatch_weights_actually_differ(data):
    """If every worker lands on the same weight the encoding is decorative."""
    weights = {round(abs(w["today"]["divergence"]) / (w["shiftHours"] * 60), 2)
               for w in data["workers"]}
    assert len(weights) >= 3, sorted(weights)


# ---------------------------------------------------------------------------
# The crew strip
# ---------------------------------------------------------------------------


def test_the_crew_strip_states_the_pair_and_the_discarded_hours():
    """The two stories the roster buries: the matched pair, which a reader
    otherwise has to diff by eye, and the teal case, which severity sorting
    pushes to the bottom of the list."""
    source = read("js", "roster.js")
    assert "crewStrip" in source
    assert "The matched pair" in source
    assert "Hours the calendar discards" in source


# ---------------------------------------------------------------------------
# Density — a different layout, not a padded table
# ---------------------------------------------------------------------------


def test_touch_density_renders_cards_not_a_table():
    """--row-height never binds: the ramp strip already makes rows ~100px, so
    "touch mode" was desktop with bigger type and nothing else."""
    source = strip_comments(read("js", "roster.js"))
    assert "renderCards" in source
    assert "renderTable" in source
    assert "data-density" in source
    css = read("styles", "components.css")
    assert ".cards" in css and ".card {" in css


def test_the_card_strip_is_height_bounded():
    """At width:100% in a card the strip scaled to 3.8x and stood 320px tall,
    so a single worker filled the screen."""
    css = read("styles", "components.css")
    rule = css[css.index(".card .ramp"):]
    rule = rule[:rule.index("}")]
    assert "height:" in rule
    assert "auto" not in rule.split("height:")[1]


def test_both_densities_render_the_same_facts():
    """Cards are a different layout, not a different dataset."""
    source = read("js", "roster.js")
    for part in ("counterfactual(", "reasonCell(", "rampStrip(", "statusChip("):
        assert source.count(part) >= 2, part


# ---------------------------------------------------------------------------
# The map
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def mapdata():
    with open(os.path.join(APP, "data", "map.js"), "r", encoding="utf-8") as fh:
        text = fh.read()
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


def test_the_choropleth_uses_quantile_classes(mapdata):
    """Equal-interval classing put 81% of cells in the top two classes and the
    metro rendered as one flat smear. The distribution is strongly left-skewed,
    so equal steps in value are nothing like equal steps in area."""
    breaks = mapdata["breaks"]
    assert breaks == sorted(breaks)
    assert len(breaks) == 5, "six classes, one per --heat-* stop"
    assert mapdata["min"] < breaks[0] and breaks[-1] < mapdata["max"]


def test_the_classes_are_actually_equally_occupied(mapdata):
    values = [v for v in mapdata["values"] if v is not None]
    counts = [0] * (len(mapdata["breaks"]) + 1)
    for value in values:
        k = 0
        while k < len(mapdata["breaks"]) and value >= mapdata["breaks"][k]:
            k += 1
        counts[k] += 1
    share = [c / len(values) for c in counts]
    # The raster is binned, so this is looser than the source-cell classing it
    # was derived from; it still must not degenerate the way equal-interval did.
    assert min(share) > 0.08, share
    assert max(share) < 0.30, share


def test_the_map_declares_its_effective_resolution(mapdata):
    """The tiles are 101 m but a 500 m blur destroys 1.1% of the variance.
    Rendering at tile resolution implies a precision the field does not have,
    so the number ships with the data and is printed on the map."""
    assert mapdata["tileResolutionM"] == 101
    assert mapdata["effectiveResolutionM"] >= 1000
    assert "effectiveResolution" in read("js", "map.js")


def test_the_smoothness_is_not_blamed_on_the_aggregation(mapdata):
    """The obvious objection to "this layer has no street-scale structure" is
    that exceedance counts 336 hours. It was tested, not assumed: a metro-extent
    single-hour retrieval over the identical lattice scores the same. An earlier
    version of this claim said the opposite, because it compared a 0.8 km window
    against a 25 km one and normalised each by its own range."""
    audit = mapdata["resolutionAudit"]
    assert audit["snapshotLag1PctOfRange"] < 1.0
    assert abs(audit["snapshotLag1PctOfRange"] - audit["lag1PctOfRange"]) < 0.2
    assert audit["snapshotBlur500VarianceKeptPct"] > 95
    assert audit["snapshotSpanC"] < 2.0, "whole metro, one instant"
    source = read("js", "map.js")
    assert "snapshotSpanC" in source
    assert "audit_resolution.py" in source


def test_the_basemap_is_cached_not_fetched():
    """SPEC.md hard constraint 6. A build-time fetch cached to a script tag is
    a fixture; a tile server at render time is a live dependency on stage."""
    html = read("index.html")
    assert 'src="data/basemap.js"' in html
    assert "http://" not in html
    source = read("js", "map.js")
    for forbidden in ("fetch(", "XMLHttpRequest", "tile.openstreetmap", "https://"):
        assert forbidden not in source, forbidden


def test_the_basemap_carries_its_attribution():
    """ODbL requires it, and it is also just honest."""
    with open(os.path.join(APP, "data", "basemap.js"), "r", encoding="utf-8") as fh:
        text = fh.read()
    payload = json.loads(text[text.index("{"): text.rindex("}") + 1])
    assert "OpenStreetMap" in payload["attribution"]
    assert payload["roads"] and payload["river"] and payload["parks"]
    assert "attribution" in read("js", "map.js")


def test_the_basemap_geometry_is_normalised_into_the_aoi():
    """Coordinates are 0..1 within the AOI so the renderer needs no projection
    code. Anything outside that range would draw off-canvas."""
    with open(os.path.join(APP, "data", "basemap.js"), "r", encoding="utf-8") as fh:
        text = fh.read()
    payload = json.loads(text[text.index("{"): text.rindex("}") + 1])
    for road in payload["roads"][:200]:
        for value in road[1:]:
            assert -0.5 <= value <= 1.5, value


# ---------------------------------------------------------------------------
# The redundant metadata
# ---------------------------------------------------------------------------


def test_the_reason_reads_the_same_everywhere_it_appears():
    """The builders emit ASCII on purpose; the browser is where it becomes
    typography. With the conversion duplicated, the roster prettified and the
    drawer did not, so one worker's reason read two different ways."""
    shared = read("js", "format.js")
    assert "export function pretty" in shared
    for name in ("roster.js", "detail.js"):
        source = read("js", name)
        assert "from './format.js'" in source, name
        assert "function pretty(" not in source, name


def test_the_roster_does_not_repeat_the_shift_length():
    """It read "8 h" on all six rows and the drawer already gives the window."""
    source = strip_comments(read("js", "roster.js"))
    assert "shiftHours} h" not in source
