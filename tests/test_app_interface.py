"""The application: entities, persistence, the feedback loop, and the shell.

Replaces tests/test_m4_interface.py and tests/test_m5_exit.py, which described
an architecture that no longer exists, a screen that rendered one frozen
roster payload. The properties those files protected are all still here; what
changed is where they live now that the roster is editable and the engine runs
in the browser.

Kept from the old files, because they were never about the old architecture:
rule 10 (adaptation is a detail-view number), the calendar counterfactual,
projected data being visually distinct, colour encoding prescription rather than
temperature, text alternatives, opt-in network calls, generated-not-hand-edited
data, the forbidden-input guard, the map's quantile classing and its resolution
caveat, and the refusal to bank a forecast score that cannot be wrong.

New here: the store's entities, the seed being resettable and deletable, CRUD
reaching every entity, and the day-log feedback loop.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP = os.path.join(ROOT, "app")


def read(*parts):
    with open(os.path.join(APP, *parts), "r", encoding="utf-8") as fh:
        return fh.read()


def generated(name):
    text = read("data", name)
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


def strip_comments(source):
    """Executable JS only. A rule about what the code READS must not be
    satisfied or broken by what the comments SAY."""
    without_blocks = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return "\n".join(line for line in without_blocks.split("\n")
                     if not line.strip().startswith("//"))


JS_FILES = ["app.js", "engine.js", "store.js", "compute.js", "ui.js",
            "views.js", "forms.js", "mapview.js", "extraviews.js",
            "interventions.js"]


# ---------------------------------------------------------------------------
# Design system
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_the_design_lint_passes():
    """DESIGN_SYSTEM.md: the lint blocks the build, it is not advisory."""
    result = subprocess.run(
        ["node", os.path.join("scripts", "check-design.mjs")],
        cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_no_component_file_contains_a_literal_colour():
    for name in JS_FILES:
        source = strip_comments(read("js", name))
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", source), name
    css = strip_comments(read("styles", "components.css"))
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css)


def test_no_emoji_anywhere_in_the_interface():
    for name in JS_FILES + ["index.html"]:
        source = read("js", name) if name.endswith(".js") else read(name)
        assert not re.search(r"[\U0001F300-\U0001FAFF☀-➿]", source), name


def test_icons_are_drawn_svg():
    source = read("js", "ui.js")
    assert "createElementNS" in source
    assert "viewBox" in source


# ---------------------------------------------------------------------------
# Rule 10: the adaptation number is a detail-view answer
# ---------------------------------------------------------------------------


def test_the_worker_grid_never_shows_the_adaptation_number():
    """A foreman gets minutes. A = 0.34 appears only when he opens a worker
    asking why. crewView builds the grid; it must not read the field."""
    source = strip_comments(read("js", "views.js"))
    grid = source[source.index("export function crewView"):
                  source.index("export function workerView")]
    assert "adaptationStart" not in grid
    assert "adaptation" not in grid


def test_the_worker_detail_does_show_it():
    source = strip_comments(read("js", "views.js"))
    detail = source[source.index("export function workerView"):]
    assert "adaptationStart" in detail
    assert "Heat readiness" in detail


# ---------------------------------------------------------------------------
# The counterfactual
# ---------------------------------------------------------------------------


def test_every_prescription_carries_the_calendar_comparison():
    """Remove the counterfactual and this is just another dashboard."""
    engine = strip_comments(read("js", "engine.js"))
    assert "calendarMinutes" in engine
    assert "divergence" in engine
    views = strip_comments(read("js", "views.js"))
    assert "divergenceCell" in views


def test_the_calendar_ramp_comes_from_constants_not_the_view():
    engine = strip_comments(read("js", "engine.js"))
    assert "calendarRampPctByDay" in engine
    assert generated("constants.js")["calendarRampPctByDay"]


def test_divergence_is_signed_in_both_directions_in_the_view():
    views = read("js", "views.js")
    assert "'over'" in views and "'under'" in views
    css = read("styles", "components.css")
    assert "--mismatch-over" in css and "--mismatch-under" in css


# ---------------------------------------------------------------------------
# Projected data, and colour meaning
# ---------------------------------------------------------------------------


def test_projected_days_are_visually_distinct():
    """Past solid, future dashed. An honesty requirement, not a style."""
    css = read("styles", "components.css")
    assert "--projected-alpha" in css
    assert "--projected-stroke" in css
    assert "stroke-dasharray" in css
    assert ".sbar-proj" in css


def test_colour_encodes_the_prescription_not_the_temperature():
    """Bar HEIGHT carries heat; bar FILL carries the status band."""
    views = strip_comments(read("js", "views.js"))
    assert "SPARK_FLOOR" in views and "SPARK_CEIL" in views
    assert "data-status" in views
    css = read("styles", "components.css")
    for status in ("cleared", "reduced", "restricted", "stop"):
        assert f'.sbar[data-status="{status}"]' in css


def test_the_strips_have_text_alternatives():
    views = strip_comments(read("js", "views.js"))
    assert "aria-label" in views
    assert "describeSpark" in views


# ---------------------------------------------------------------------------
# Entities and persistence
# ---------------------------------------------------------------------------


def test_the_store_defines_the_four_entities():
    source = strip_comments(read("js", "store.js"))
    for fn in ("addSite", "addCrew", "addWorker", "setDayLog"):
        assert f"export function {fn}" in source, fn
    for fn in ("updateSite", "updateCrew", "updateWorker"):
        assert f"export function {fn}" in source, fn
    for fn in ("removeSite", "removeCrew", "removeWorker"):
        assert f"export function {fn}" in source, fn


def test_deletes_cascade_so_nothing_is_orphaned():
    source = strip_comments(read("js", "store.js"))
    remove_site = source[source.index("export function removeSite"):
                         source.index("export function removeCrew")]
    assert "crews(id)" in remove_site
    assert "state.workers" in remove_site
    assert "dayLogs" in remove_site


def test_dynamic_weather_series_persist_and_hydrate():
    store = strip_comments(read("js", "store.js"))
    assert "weatherSeries" in store
    assert "function hydrateWeatherSeries" in store
    assert "export function saveWeatherSeries" in store
    assert "dropWeatherSeries(removed.seriesKey)" in store
    site_weather = strip_comments(read("js", "siteweather.js"))
    assert "store.saveWeatherSeries(key, series)" in site_weather
    forms = strip_comments(read("js", "forms.js"))
    assert "store.saveWeatherSeries(key" in forms


def test_site_rollup_does_not_present_missing_inputs_as_a_full_shift():
    views = strip_comments(read("js", "views.js"))
    site_view = views[views.index("export function siteView"):
                      views.index("export function crewView")]
    assert "r.unavailable || !r.workers" in site_view
    assert "'No workers'" in site_view
    assert "'Unavailable'" in site_view


def test_entry_pages_use_the_served_sunup_favicon():
    with open(os.path.join(APP, "index.html"), encoding="utf-8") as source:
        app_entry = source.read()
    with open(os.path.join(ROOT, "index.html"), encoding="utf-8") as source:
        root_entry = source.read()
    favicon = os.path.join(ROOT, "favicon.svg")
    assert 'href="../favicon.svg"' in app_entry
    assert 'href="favicon.svg"' in root_entry
    assert os.path.isfile(favicon)


def test_interrupted_live_weather_resumes_the_paid_activity():
    site_weather = strip_comments(read("js", "siteweather.js"))
    assert "liveActivities" in site_weather
    assert "pendingActivities(site)" in site_weather
    assert "fetchDay(current, date, drivers[date], null, activityId)" in site_weather
    assert "export function resumeSiteBackfills" in site_weather
    assert "Promise.allSettled" in site_weather
    app = strip_comments(read("js", "app.js"))
    assert "resumeSiteBackfills()" in app


def test_initial_live_weather_days_are_fetched_concurrently_and_saved_individually():
    source = strip_comments(read("js", "siteweather.js"))
    assert "const INITIAL_CONCURRENCY = 5" in source
    assert "async function runPool" in source
    assert "outcomes.push({ item, value: await work(item) })" in source
    assert "saveDailySeries(siteId, date, daily)" in source
    start = source[source.index("export async function startSiteBackfill"):]
    assert "INITIAL_CONCURRENCY" in start


def test_live_weather_polling_has_a_recoverable_timeout():
    client = strip_comments(read("js", "liveweather.js"))
    assert "const ACTIVITY_TIMEOUT_MS" in client
    assert "error.code = 'activity_timeout'" in client
    assert "resume the same task" in client


def test_live_weather_reports_freshness_and_skips_completed_days():
    site_weather = strip_comments(read("js", "siteweather.js"))
    assert "!dayReady(site, date)" in site_weather
    assert "weatherUpdatedAt: new Date().toISOString()" in site_weather
    views = strip_comments(read("js", "views.js"))
    assert "function weatherFreshness" in views
    assert "Live weather:" in views


def test_live_sites_use_a_rolling_history_and_real_forecast_series():
    site_weather = strip_comments(read("js", "siteweather.js"))
    assert "export function observedDateWindow" in site_weather
    assert "export function forecastDateWindow" in site_weather
    assert "fetchRegionalWeather" in site_weather
    assert "buildWbgtSeries(null, drivers[date], site.location)" in site_weather
    compute = strip_comments(read("js", "compute.js"))
    assert "forecastDatesForSite(site)" in compute
    assert "lastHourly" not in compute
    assert "hourly: lastHourly" not in compute


def test_live_weather_stops_on_the_last_complete_arizona_day():
    site_weather = strip_comments(read("js", "siteweather.js"))
    start = site_weather[site_weather.index("export async function startSiteBackfill"):]
    assert "const today = phoenixToday()" in start
    assert "const asOf = moveDate(today, -1)" in start
    assert "weatherDates: observedDateWindow(asOf)" in start
    assert "weatherForecastDates: forecastDateWindow(asOf)" in start


def test_key_test_distinguishes_rejection_from_service_failure():
    client = strip_comments(read("js", "liveweather.js"))
    assert "['api', 'fortyguard', 'com'].join('.')" in client
    assert "['api', 'forty', 'guard']" not in client
    test_key = client[client.index("export async function testKey"):
                      client.index("export async function submitHeatmap")]
    assert "const date = previousDate(asOfDate)" in test_key
    assert "error.status === 401 || error.status === 403" in test_key
    assert "error.status >= 500" in test_key
    assert "Key authentication failed" not in test_key
    settings = strip_comments(read("js", "extraviews.js"))
    assert "A key is saved in this browser" in settings
    assert "Test saved key" in settings
    assert "Save and test" in settings
    assert "if (key.value.trim())" in settings
    assert "liveWeather.saveKey(key.value)" in settings


def test_today_is_the_real_arizona_date_not_the_fixture_date():
    compute = strip_comments(read("js", "compute.js"))
    today = compute[compute.index("export function today"):
                    compute.index("export function observedDatesForSite")]
    assert "America/Phoenix" in today
    assert "W().today" not in today
    views = strip_comments(read("js", "views.js"))
    assert "Each row shows its active weather date" in views


def test_worker_feedback_makes_log_effects_visible_without_rewriting_history():
    engine = strip_comments(read("js", "engine.js"))
    assert "const adaptationEnd = advanceAdaptation" in engine
    assert "adaptationEnd," in engine
    views = strip_comments(read("js", "views.js"))
    assert "minutes prescribed for ${current.date}" in views
    assert "minutes prescribed today" not in views
    assert "Readiness at shift start" in views
    assert "After logged work" in views
    assert "Cached through ${current.date}" in views
    assert "cached demo history" not in views
    forms = strip_comments(read("js", "forms.js"))
    assert "The prescription already issued for this date stays unchanged" in forms
    assert "Later prescriptions recalculated" in forms


def test_failed_live_weather_has_a_retry_path():
    views = strip_comments(read("js", "views.js"))
    assert "function weatherFailureBanner" in views
    assert "function liveFetchButton" in views
    assert "Retry live fetch" in views
    assert "ctx.go('#/settings')" in views
    app = strip_comments(read("js", "app.js"))
    assert "if (!document.querySelector('.panel')) render()" in app


def test_the_seed_is_data_and_is_resettable_and_deletable():
    seed = generated("seed.js")
    assert seed["sites"] and seed["crews"] and seed["workers"]
    store = strip_comments(read("js", "store.js"))
    assert "resetToSeed" in store
    settings = read("js", "extraviews.js")
    assert "Reset to demo data" in settings
    assert "Delete everything" in settings


def test_seeded_records_are_stored_without_demo_badges():
    store = strip_comments(read("js", "store.js"))
    assert "seeded: true" in store
    views = strip_comments(read("js", "views.js"))
    assert "tag('seed'" not in views


def test_the_generated_data_says_it_is_generated():
    for name in ("seed.js", "weather.js", "constants.js"):
        head = read("data", name)[:300]
        assert "GENERATED" in head, name


# ---------------------------------------------------------------------------
# The forbidden-input guard, enforced rather than documented
# ---------------------------------------------------------------------------


def test_the_store_refuses_to_write_a_forbidden_field():
    source = strip_comments(read("js", "store.js"))
    assert "forbiddenInputs" in source
    assert "function reject" in source
    for fn in ("addSite", "addCrew", "addWorker"):
        block = source[source.index(f"export function {fn}"):]
        block = block[:block.index("emit()")]
        assert "reject(" in block, fn


def test_no_forbidden_input_appears_in_the_seed():
    seed = generated("seed.js")
    banned = set(generated("constants.js")["forbiddenInputs"])
    blob = json.dumps(seed).lower()
    for name in banned:
        flat = name.lower().replace("_", "").replace(" ", "")
        assert f'"{flat}"' not in blob.replace("_", ""), name


def test_the_worker_form_offers_only_job_facts():
    source = read("js", "forms.js")
    fields = source[source.index("export function editWorker"):]
    fields = fields[:fields.index("function save()")]
    for banned in ("age", "sex", "gender", "bmi", "weight", "height",
                   "fitness", "medical", "hydration", "ethnic"):
        assert f"field('{banned}" not in fields.lower(), banned


# ---------------------------------------------------------------------------
# The feedback loop
# ---------------------------------------------------------------------------


def test_the_state_update_uses_actual_minutes_not_prescribed():
    """The whole point of the day log."""
    engine = strip_comments(read("js", "engine.js"))
    assert "allocateActual" in engine
    sim = engine[engine.index("export function simulate"):]
    assert "allocateActual(hours, logged, worker)" in sim
    assert "dailyStimulus(hours, worker, allocation)" in sim


def test_an_unlogged_day_falls_back_and_is_marked_assumed():
    engine = strip_comments(read("js", "engine.js"))
    assert "assumed: logged === null" in engine
    views = read("js", "views.js")
    assert "assumed" in views
    assert "assumedRun" in views


def test_interface_copy_reports_state_without_explaining_methodology():
    app = strip_comments(read("js", "app.js"))
    for phrase in ("REGULATORY POSITION", "unvalidated assumption",
                   "natural wet bulb", "Cached seed", "seed data"):
        assert phrase not in app
    forms = strip_comments(read("js", "forms.js"))
    for phrase in ("ISO 7243", "by design", "feedback loop"):
        assert phrase not in forms
    views = strip_comments(read("js", "views.js"))
    for phrase in ("projection rather than a measurement",
                   "raised his adaptation", "tag('seed'"):
        assert phrase not in views
    settings = strip_comments(read("js", "extraviews.js"))
    for phrase in ("excluded as degenerate", "no skill shown", "Seed version",
                   "seed roster"):
        assert phrase not in settings


def test_shipped_temperature_units_never_use_a_dash_separator():
    dash_separators = re.compile(r"(?:°C|degC)[-\u2010-\u2015](?:WBGT|h)\b")
    for name in JS_FILES:
        assert not dash_separators.search(read("js", name)), name


def test_unprescribed_work_is_surfaced_not_just_recorded():
    """A supervisor who logged work on a stop-work day must SEE it flagged."""
    engine = strip_comments(read("js", "engine.js"))
    assert "unprescribedWork" in engine
    views = read("js", "views.js")
    assert "unprescribed" in views
    assert "tag('unprescribed', 'danger')" in views
    css = read("styles", "components.css")
    assert '.tag[data-kind="danger"]' in css


def test_the_crew_flags_column_has_room_for_both_alerts():
    views = strip_comments(read("js", "views.js"))
    site_view = views[views.index("export function siteView"):
                      views.index("export function crewView")]
    assert "{ label: 'Flags', width: '220px'" in site_view


def test_both_facts_are_reported_not_just_the_flattering_one():
    """Working over prescription raises adaptation AND accumulates strain."""
    engine = strip_comments(read("js", "engine.js"))
    assert "export function overexposure" in engine
    views = read("js", "views.js")
    assert "cumulativeOverexposure" in views
    assert "Overexp" in views


def test_editing_a_worker_reruns_the_prescription_immediately():
    """No build step between the form and the answer."""
    forms = strip_comments(read("js", "forms.js"))
    assert "compute.invalidate()" in forms
    compute = strip_comments(read("js", "compute.js"))
    assert "export function invalidate" in compute


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------


def test_routing_is_three_levels_deep_and_linkable():
    source = strip_comments(read("js", "app.js"))
    for route in ("today", "sites", "site", "crew", "worker", "map", "performance",
                  "settings"):
        assert f"'{route}'" in source, route
    assert "parts[0] === 'forecast'" in source, "old forecast links remain valid"
    assert "hashchange" in source


def test_today_is_the_default_start_of_shift_view():
    app = strip_comments(read("js", "app.js"))
    assert "location.hash = '#/today'" in app
    assert "label: 'Today'" in app
    assert "label: 'Sites and crews'" in app
    views = strip_comments(read("js", "views.js"))
    today = views[views.index("function todayAttention"):
                  views.index("export function sitesView")]
    assert "pageHeader('Today'" in today
    for label in ("Plan (min)", "Calendar", "vs prior", "Status",
                  "Next action"):
        assert f"label: '{label}'" in today
    assert "worker.active !== false" in today
    assert "selectable: false" in today
    assert "Close out ${row.previous.date.slice(5)}" in today
    assert "recommendationFor(result)" in today
    assert "+${row.recommendation.gain} min" in today
    assert "Compared with ${row.previous.date}" in today


def test_site_and_crew_rollups_count_workers_who_need_action():
    compute = strip_comments(read("js", "compute.js"))
    assert "function needsCloseout" in compute
    assert "actionRequired: rows.filter" in compute
    assert "actionRequired: crews.reduce" in compute
    views = strip_comments(read("js", "views.js"))
    sites = views[views.index("export function sitesView"):
                  views.index("export function crewView")]
    assert sites.count("label: 'Action'") == 2


def test_every_entity_route_has_a_real_page_heading():
    views = strip_comments(read("js", "views.js"))
    site = views[views.index("export function siteView"):
                 views.index("export function crewView")]
    crew = views[views.index("export function crewView"):
                 views.index("export function workerView")]
    worker = views[views.index("export function workerView"):
                   views.index("function fact")]
    assert "pageHeader(site.name" in site
    assert "pageHeader(crew.name" in crew
    assert "pageHeader(worker.name" in worker


def test_a_whole_crew_can_be_closed_out_without_selecting_workers():
    app = strip_comments(read("js", "app.js"))
    crew_commands = app[app.index("if (current.view === 'crew')"):
                        app.index("if (current.view === 'worker')")]
    assert "label: 'Log crew'" in crew_commands
    assert "forms.editCrewDayLog(current.crewId" in crew_commands
    forms = strip_comments(read("js", "forms.js"))
    bulk = forms[forms.index("export function editCrewDayLog"):
                 forms.index("export function confirmRemove")]
    assert "worker.active !== false" in bulk
    assert "Absent" in bulk
    assert "store.setDayLog" in bulk
    assert "footer('Save crew'" in bulk


def test_settings_imports_every_control_it_renders():
    source = strip_comments(read("js", "extraviews.js"))
    imports = source[:source.index("const HORIZON")]
    assert re.search(r"\binput\b", imports)
    assert "const key = input(" in source


def test_editors_use_human_labels_and_modal_focus_management():
    forms = strip_comments(read("js", "forms.js"))
    assert "subtitle: existing ? existing.id" not in forms
    assert "Use trade default" in forms
    assert "humanize(CONSTANTS.tradeToWorkClass[t])" in forms
    assert "worker-form" in forms
    ui = strip_comments(read("js", "ui.js"))
    panel = ui[ui.index("export function panel"):
               ui.index("export function chip")]
    assert "aria-modal', 'true" in panel
    assert "panelKeydown" in panel
    assert "returnFocus.focus()" in panel


def test_the_shell_has_a_command_bar_a_tree_and_breadcrumbs():
    html = read("index.html")
    for id_ in ("rail", "tree", "commandbar", "content", "statusbar"):
        assert f'id="{id_}"' in html, id_
    ui = strip_comments(read("js", "ui.js"))
    assert "export function commandBar" in ui
    assert "export function navTree" in ui
    assert "export function breadcrumb" in ui
    assert "export function pageHeader" in ui
    assert "export function detailsList" in ui


def test_desktop_navigation_is_one_surface_and_collapses_on_narrow_screens():
    css = read("styles", "components.css")
    assert "grid-template-columns: var(--rail-width-open) minmax(0, 1fr)" in css
    assert ".sidenav {" in css
    assert ".rail-label {" in css
    narrow = css[css.index("@media (max-width: 900px)"):]
    assert "grid-template-columns: var(--rail-width)" in narrow
    assert ".rail-label { display: none; }" in narrow


def test_current_site_can_stay_collapsed_and_day_log_has_no_checkboxes():
    app = strip_comments(read("js", "app.js"))
    assert "if (current.siteId) expanded.add(current.siteId)" not in app
    views = strip_comments(read("js", "views.js"))
    worker = views[views.index("export function workerView"):
                   views.index("function fact")]
    day_log = worker[worker.index("section('Day log'"):
                      worker.index("if (current.hours.length)")]
    assert "selectable: false" in day_log
    assert "label: 'Rule'" not in day_log
    assert "label: 'Adapt. after'" not in day_log


def test_commands_enable_on_selection_rather_than_appearing():
    """An Office toolbar does not reflow as the selection changes."""
    ui = strip_comments(read("js", "ui.js"))
    assert "command.enabled" in ui
    assert "button.disabled" in ui
    app = strip_comments(read("js", "app.js"))
    assert "enabled: () =>" in app


def test_the_grid_rows_use_the_readable_row_token():
    css = read("styles", "components.css")
    match = re.search(r"^\.dl-row \{(.*?)\}", css, flags=re.S | re.M)
    assert match, "no standalone .dl-row rule"
    assert "height: var(--row-height)" in match.group(1)
    with open(os.path.join(ROOT, "web", "tokens.css"), encoding="utf-8") as source:
        tokens = source.read()
    assert "--row-height:         44px" in tokens
    assert '[data-density="touch"] .dl-row' in css


def test_worker_detail_uses_separate_decision_charts_and_the_grid_gets_a_sparkline():
    views = strip_comments(read("js", "views.js"))
    grid = views[views.index("export function crewView"):
                 views.index("export function workerView")]
    assert "sparkline(" in grid
    detail = views[views.index("export function workerView"):]
    assert "historyChart(result.records, recalculation)" in detail
    assert "hourlyChart(current.hours, recalculation, current.date)" in detail
    assert "rampStrip(result.records)" not in detail


def test_worker_detail_adds_location_context_and_supervisor_actions():
    views = strip_comments(read("js", "views.js"))
    assert "function workerLocationCard" in views
    assert "sitePoint(site)" in views
    assert "Open site map" in views
    assert "function supervisorPlan" in views
    assert "planned work window" in views
    assert "shaded or cooled recovery area" in views


def test_worker_detail_explains_and_compares_pullable_interventions():
    views = strip_comments(read("js", "views.js"))
    interventions = strip_comments(read("js", "interventions.js"))
    assert "Compare an intervention" in views
    assert "Shift start" in views and "Shift end" in views
    assert "Hourly heat-work cap" in views
    assert "Both plans use ${current.date}" in views
    assert "function interventionSimulator" in views
    assert "export function evaluateIntervention" in interventions
    assert "export function suggestIntervention" in interventions
    assert "export function recommendationFor" in interventions
    assert "CONSTANTS.defaultShiftStartHour" in interventions
    assert "prescribeHours(hourly, candidate, adaptation)" in interventions
    assert "decision-explanation" in views
    assert "Recovery or non-heat work" in views
    assert "Use suggested plan" in views


def test_intervention_changes_animate_without_forcing_motion():
    views = strip_comments(read("js", "views.js"))
    css = read("styles", "components.css")
    assert "Calculating the scenario" in views
    assert "calculation-loader intervention-loader" in views
    assert "calculatedValue(scenarioText" in views
    assert ".intervention-loader span { animation: none; }" in css


def test_log_feedback_animates_the_recalculated_result_without_forcing_motion():
    forms = strip_comments(read("js", "forms.js"))
    views = strip_comments(read("js", "views.js"))
    css = read("styles", "components.css")
    assert "sunup:last-recalculation" in forms
    assert "recalculationSnapshot" in forms
    assert "recalculationChanges" in forms
    assert "Plan recalculated" in views
    assert "calculatedValue" in views
    assert "calculation-loader" in views
    assert "Changed values after logging" in views
    assert ".calculated-value" in css
    assert "calculation-result-reveal" in css
    assert "calculation-point-pop" in css
    assert "@media (prefers-reduced-motion: reduce)" in css


# ---------------------------------------------------------------------------
# The map is a selection surface
# ---------------------------------------------------------------------------


def test_the_map_is_interactive():
    """If it is not interactive it should be deleted, because it is a picture."""
    source = strip_comments(read("js", "mapview.js"))
    assert "map.on('click'" in source
    assert "forms.editSite" in source
    assert "isWithinArizona" in source
    assert "ctx.go(" in source


def test_the_map_uses_leaflet_and_constrains_site_selection_to_arizona():
    source = read("js", "mapview.js")
    geometry = read("js", "leaflet.js")
    assert "L.map" in source
    assert "tileLayer" in source
    assert "isWithinArizona" in geometry


def test_the_leaflet_map_has_osm_attribution():
    source = read("js", "mapview.js")
    assert "attribution" in source
    assert "tile.openstreetmap.org" in source


def test_the_live_map_fills_its_route_after_leaflet_mounts():
    css = read("styles", "components.css")
    assert ".content > .view-map" in css
    live_map = re.search(r"^\.live-map \{(.*?)\}", css, flags=re.S | re.M)
    assert live_map, "the live map needs its own sizing rule"
    assert "flex: 1" in live_map.group(1)
    assert "min-height: 0" in live_map.group(1)
    source = strip_comments(read("js", "mapview.js"))
    assert "map.invalidateSize" in source


def test_the_site_picker_keeps_leaflet_inside_the_panel():
    css = read("styles", "components.css")
    assert "isolation: isolate" in css
    assert ".site-picker-actions" in css
    assert "grid-template-columns: repeat(3" in css
    forms = strip_comments(read("js", "forms.js"))
    assert "site-picker-actions" in forms
    assert "map.invalidateSize" in forms
    assert "aria-pressed" in forms
    assert "disableClickPropagation" in forms
    map_view = strip_comments(read("js", "mapview.js"))
    assert "document.querySelector('.panel')" in map_view
    ui = strip_comments(read("js", "ui.js"))
    field = ui[ui.index("export function field"):
               ui.index("export function input")]
    assert "control.matches('input, select, textarea')" in field


def test_finished_boundary_remains_the_saved_geometry():
    forms = strip_comments(read("js", "forms.js"))
    finish = forms[forms.index("finish.addEventListener"):
                   forms.index("map.on('click'")]
    assert "showBoundary(L, picked)" in finish
    assert "onChange({ location, polygon: picked, mode: 'boundary' })" in finish
    assert "mode = 'area'" in finish
    assert "point.setAttribute('aria-pressed', 'false')" in finish
    save = forms[forms.index("const changes = {"):
                 forms.index("const saved =")]
    assert "polygon: polygon || pointFeature(chosen)" in save


# ---------------------------------------------------------------------------
# Model performance
# ---------------------------------------------------------------------------


def test_the_backtest_reads_each_workers_own_day_log():
    source = strip_comments(read("js", "extraviews.js"))
    assert "store.loggedMinutes(worker.id)" in source
    assert "logs: {}" in source, "the projection must be blind to the logs"


def test_the_backtest_declares_itself_and_refuses_a_score_that_cannot_be_wrong():
    source = read("js", "extraviews.js")
    assert "Not a live forecast" not in source
    assert "degenerate" in source
    assert "not counted" in source
    assert "workers without variation" in source


def test_model_performance_has_no_decorative_selection_controls():
    ui = strip_comments(read("js", "ui.js"))
    assert "selectable = true" in ui
    performance = strip_comments(read("js", "extraviews.js"))
    block = performance[performance.index("export function performanceView"):
                        performance.index("function metric")]
    assert "selectable: false" in block
    assert "Projected / actual" in block
    assert "fc-day-value" in block
    assert "fc-dot" not in block


def test_settings_groups_weather_and_browser_data():
    source = strip_comments(read("js", "extraviews.js"))
    settings = source[source.index("export function settingsView"):]
    assert "settings-grid" in settings
    assert "Weather access and browser data" in settings
    assert "save.disabled = !entered" in settings


# ---------------------------------------------------------------------------
# Offline
# ---------------------------------------------------------------------------


def test_live_network_access_is_opt_in():
    """A cold opening uses the cached seed until the user saves a key."""
    for name in JS_FILES:
        source = read("js", name)
        for forbidden in ("fetch(", "XMLHttpRequest", "WebSocket", "import("):
            assert forbidden not in source, (name, forbidden)
    client = read("js", "liveweather.js")
    backfill = read("js", "siteweather.js")
    assert "fetch(" in client
    assert "if (!hasConfiguredKey()) return false" in backfill
    html = read("index.html")
    assert "http://" not in html
    assert "https://" not in html
