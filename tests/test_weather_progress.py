"""Background weather progress must not replace the plan being read."""

import json
import os
import shutil
import subprocess

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node unavailable")


def node(expression):
    script = """
globalThis.window = globalThis;
globalThis.localStorage = { getItem: () => null, setItem: () => {} };
await import('./app/data/constants.js');
await import('./app/data/seed.js');
await import('./app/data/weather.js');
const store = await import('./app/js/store.js');
const { weatherProgressState } = await import('./app/js/weatherprogress.js');
await store.initStore();
const site = { id: 'test', name: 'Test site', weatherStatus: 'loading',
  weatherPhase: 'site-check', weatherProgress: { completed: 0, total: 14 },
  liveActivities: { '2026-08-24': 'pending' },
  weatherStartedAt: '2026-08-30T10:00:00Z' };
""" + "process.stdout.write(JSON.stringify(" + expression + "));"
    result = subprocess.run(["node", "--input-type=module", "-e", script],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_first_day_wait_reports_real_progress_without_an_invented_eta():
    result = node("weatherProgressState([site], true)")
    assert result["title"] == "Preparing the first schedule"
    assert result["completed"] == 0 and result["total"] == 14
    assert result["pending"] == 1
    assert result["running"] and not result["canApply"]
    assert "first day" in result["detail"]
    assert "several minutes" in result["detail"]
    assert "remaining" not in result


def test_new_days_can_be_applied_without_forcing_an_update():
    result = node("weatherProgressState([{...site, weatherStatus:'backfill',"
                  "weatherPhase:'backfill', weatherProgress:{completed:7,total:14}}],true)")
    assert result["completed"] == 7
    assert result["canApply"] and result["running"]
    assert "earlier" in result["detail"]
    assert not node("weatherProgressState([{...site,"
                    "weatherProgress:{completed:7,total:14}}],false)")["canApply"]


def test_completion_keeps_an_explicit_update_action_and_stops_elapsed_time():
    result = node("weatherProgressState([{...site, weatherStatus:'complete',"
                  "weatherProgress:{completed:14,total:14},liveActivities:{},"
                  "weatherFinishedAt:'2026-08-30T10:05:00Z'}],true)")
    assert result["title"] == "Weather history ready"
    assert result["canApply"] and not result["running"]
    assert result["finishedAt"] - result["startedAt"] == 300000
    assert result["retryIds"] == []


def test_partial_failures_preserve_days_and_offer_retry():
    result = node("weatherProgressState([{...site,weatherStatus:'partial',"
                  "weatherError:'Connection interrupted.',"
                  "weatherProgress:{completed:6,total:14}}],true)")
    assert result["title"] == "Weather history paused"
    assert result["retryIds"] == ["test"]
    assert result["canApply"] and not result["running"]
    assert "Connection interrupted." in result["detail"]
    assert "Completed days are saved" in result["detail"]


def test_multiple_site_progress_does_not_drop_a_finished_site_from_the_denominator():
    result = node("weatherProgressState([site,{...site,id:'finished',"
                  "weatherStatus:'complete',weatherProgress:{completed:14,total:14},"
                  "liveActivities:{}}],true)")
    assert result["completed"] == 14 and result["total"] == 28
    assert result["scope"] == "2 sites"


def test_weather_notifications_are_distinct_from_roster_edits():
    result = node("""(() => {
      const changes = [];
      store.subscribe((state, change) => changes.push({type:change.type,
        siteId:change.siteId, dataChanged:change.dataChanged, hasWorkers:!!state.workers}));
      store.updateSiteWeather('site_north', {weatherStatus:'loading'});
      store.saveWeatherSeries(store.site('site_north').seriesKey, {});
      store.updateWorker('wkr_reyes', {name:'Updated name'});
      return changes;
    })()""")
    assert result[0]["type"] == "weather" and not result[0]["dataChanged"]
    assert result[1]["type"] == "weather" and result[1]["dataChanged"]
    assert result[1]["siteId"] == "site_north"
    assert result[2]["type"] == "data"
    assert all(item["hasWorkers"] for item in result)


def test_background_handler_never_replaces_content_and_forms_still_render():
    with open(os.path.join(ROOT, "app", "js", "app.js"), encoding="utf-8") as source:
        app = source.read()
    listener = app[app.index("store.subscribe((state, change)"):]
    background = listener[listener.index("if (change && change.type === 'weather')"):
                          listener.index("if (!document.querySelector('.panel'))")]
    assert "updateWeatherProgress()" in background
    assert "return;" in background
    assert "render()" not in background and "replaceChildren" not in background
    assert "if (!document.querySelector('.panel')) render()" in listener
    assert "content.scrollTop = previousScroll" in app


def test_progress_is_accessible_stable_and_respects_reduced_motion():
    with open(os.path.join(ROOT, "app", "js", "weatherprogress.js"), encoding="utf-8") as source:
        progress = source.read()
    update = progress[progress.index("update(sites,"):]
    assert "replaceChildren" not in update
    assert "aria-valuetext" in update
    assert "weatherProgressState(sites, dirty)" in update
    with open(os.path.join(ROOT, "app", "styles", "components.css"), encoding="utf-8") as source:
        css = source.read()
    assert "#weather-progress-host { flex: none; }" in css
    assert ".weather-task-progress::-webkit-progress-value { transition: none; }" in css


def test_real_backfill_failure_emits_only_background_notifications_and_records_timing():
    result = node("""await (async () => {
      window.SUNUP_CONFIG = {weatherGateway:'https://weather.invalid'};
      globalThis.fetch = async () => { throw new Error('Offline test'); };
      const {startSiteBackfill} = await import('./app/js/siteweather.js');
      const item = store.addSite({id:'failure_test',location:{lat:33.46,lng:-112.16},
        polygon:{type:'FeatureCollection',features:[]}});
      const notifications=[];
      store.subscribe((state,change)=>notifications.push(change.type));
      const started=await startSiteBackfill(item.id);
      return {started,notifications,site:store.site(item.id)};
    })()""")
    assert result["started"] is False
    assert set(result["notifications"]) == {"weather"}
    site = result["site"]
    assert site["weatherStatus"] == "error"
    assert site["weatherPhase"] == "error"
    assert site["weatherProgress"]["completed"] == 0
    assert site["weatherProgress"]["total"] == 14
    assert site["weatherStartedAt"] and site["weatherFinishedAt"]
    assert "could not be reached" in site["weatherError"]
