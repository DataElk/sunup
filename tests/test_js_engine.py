"""The browser engine must agree with the Python engine, and must be current.

The per-worker maths now runs in two places. That is a deliberate trade, an
editable roster cannot recompute anything if the model only exists in a build
script, but two implementations of the thing that decides whether a worker is
told to stop will drift unless something stops them.

Two gates here:

  1. AGREEMENT. tests/replay_golden.mjs runs app/js/engine.js under Node over
     vectors emitted by the Python engine and reports any disagreement beyond
     1e-9.

  2. CURRENCY. app/data/constants.js carries a hash of the constants it was
     generated from. If constants.py changed and the generator was not re-run,
     the browser is quietly running yesterday's exposure limits. That fails
     here rather than in the field.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GENERATED = os.path.join(ROOT, "app", "data", "constants.js")
VECTORS = os.path.join(ROOT, "tests", "fixtures", "golden_vectors.json")

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not available")


def _generated_payload():
    with open(GENERATED, "r", encoding="utf-8") as fh:
        text = fh.read()
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


# ---------------------------------------------------------------------------
# Currency
# ---------------------------------------------------------------------------


def test_the_generated_constants_are_not_stale():
    """constants.py is the single source of truth. This proves the browser copy
    was generated from the CURRENT one."""
    import sys
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import build_js_constants as gen

    expected = gen.source_hash(gen.payload())
    actual = _generated_payload()["sourceHash"]
    assert actual == expected, (
        "app/data/constants.js is stale. constants.py has changed since it was "
        "generated. Run: python scripts/build_js_constants.py")


def test_the_generated_file_says_it_is_generated():
    with open(GENERATED, "r", encoding="utf-8") as fh:
        head = fh.read(400)
    assert "GENERATED" in head
    assert "build_js_constants.py" in head
    assert "DO NOT EDIT" in head


def test_no_exposure_limit_is_hand_typed_into_the_engine():
    """Every number in engine.js must come through the generated constants."""
    with open(os.path.join(ROOT, "app", "js", "engine.js"), "r",
              encoding="utf-8") as fh:
        source = fh.read()
    body = source[source.index("const K ="):]
    for literal in ("22.5", "25.0", "26.0", "28.0", "30.0", "21.5",
                    "4.0", "14.0", "6.0"):
        assert literal not in body, (
            "%s appears literally in engine.js; it must come from "
            "SUNUP_CONSTANTS" % literal)


def test_the_forbidden_inputs_reach_the_browser():
    """A legal constraint, not a preference. The browser store enforces it too."""
    payload = _generated_payload()
    forbidden = set(payload["forbiddenInputs"])
    for name in ("age", "sex", "bmi", "weight", "height"):
        assert any(name in f for f in forbidden), name


# ---------------------------------------------------------------------------
# Agreement
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def replay():
    result = subprocess.run(
        ["node", os.path.join("tests", "replay_golden.mjs")],
        cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_the_vectors_actually_cover_something(replay):
    """A gate that checks nothing passes trivially."""
    assert replay["checked"] > 500, replay["checked"]


def test_the_browser_engine_agrees_with_python(replay):
    if not replay["ok"]:
        lines = ["%d disagreement(s), first %d shown:"
                 % (replay["totalFailures"], len(replay["failures"]))]
        for f in replay["failures"]:
            lines.append("  %-52s expected %r got %r (delta %s)"
                         % (f["what"], f["expected"], f["actual"], f["delta"]))
        pytest.fail("\n".join(lines))


def test_the_replay_used_the_current_constants(replay):
    assert replay["sourceHash"] == _generated_payload()["sourceHash"]


# ---------------------------------------------------------------------------
# The feedback loop has no Python counterpart, so it is checked directly
# ---------------------------------------------------------------------------


def _node(expression):
    script = (
        "import {readFileSync} from 'node:fs';"
        "globalThis.window=globalThis;"
        "(0,eval)(readFileSync('app/data/constants.js','utf8'));"
        "const e=await import('./app/js/engine.js');"
        "process.stdout.write(JSON.stringify(%s));" % expression
    )
    result = subprocess.run(["node", "--input-type=module", "-e", script],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def _node_compute(expression):
    script = (
        "import {readFileSync} from 'node:fs';"
        "globalThis.window=globalThis;"
        "globalThis.localStorage={getItem:()=>null,setItem:()=>{}};"
        "(0,eval)(readFileSync('app/data/constants.js','utf8'));"
        "(0,eval)(readFileSync('app/data/weather.js','utf8'));"
        "const c=await import('./app/js/compute.js');"
        "process.stdout.write(JSON.stringify(%s));" % expression
    )
    result = subprocess.run(["node", "--input-type=module", "-e", script],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


WORKER = ("{trade:'concrete',clothing:'work_clothes',shiftStart:6,shiftEnd:14,"
          "workClassOverride:null}")


def test_rule_a_scales_proportionally_and_preserves_shape():
    """Rule A: the hottest hours were prescribed least and must still weigh
    least. Halving the day's total must halve every hour's duty, not flatten
    them."""
    out = _node(
        "(()=>{const w=%s;"
        "const hours=[{minutes:60},{minutes:30},{minutes:15},{minutes:0}];"
        "const a=e.allocateActual(hours,105/2,w);"
        "return {rule:a.rule,duties:a.duties,unprescribed:a.unprescribedWork};})()"
        % WORKER)
    assert out["rule"] == "proportional"
    assert out["unprescribed"] is False
    # prescribed total 105; actual 52.5 -> factor 0.5 on every hour
    assert out["duties"] == pytest.approx([0.5, 0.25, 0.125, 0.0], abs=1e-12)


def test_unplanned_work_is_bounded_and_assigned_to_the_hottest_hours():
    """The case that matters most: told to stop, worked anyway."""
    out = _node(
        "(()=>{const w=%s;"
        "const hours=[{hour:6,minutes:0,overLimit:1,wbgt:28},"
        "{hour:7,minutes:0,overLimit:4,wbgt:31},"
        "{hour:8,minutes:0,overLimit:3,wbgt:30},"
        "{hour:9,minutes:0,overLimit:2,wbgt:29}];"
        "const a=e.allocateActual(hours,120,w);"
        "return {rule:a.rule,duties:a.duties,unprescribed:a.unprescribedWork};})()"
        % WORKER)
    assert out["rule"] == "bounded_conservative"
    assert out["unprescribed"] is True, "must be flagged, not averaged away"
    assert out["duties"] == pytest.approx([0.0, 1.0, 1.0, 0.0], abs=1e-12)


def test_work_above_plan_never_exceeds_one_hour_inside_a_clock_hour():
    out = _node(
        "(()=>{const w=%s;"
        "const hours=[{hour:6,minutes:60,overLimit:1,wbgt:28},"
        "{hour:7,minutes:30,overLimit:4,wbgt:31},"
        "{hour:8,minutes:15,overLimit:3,wbgt:30},"
        "{hour:9,minutes:30,overLimit:2,wbgt:29}];"
        "const a=e.allocateActual(hours,210,w);"
        "return {rule:a.rule,duties:a.duties,total:a.duties.reduce((s,x)=>s+x*60,0)};})()"
        % WORKER)
    assert out["rule"] == "bounded_conservative"
    assert max(out["duties"]) <= 1.0
    assert out["total"] == pytest.approx(210, abs=1e-12)


def test_a_zero_log_is_not_treated_as_no_log():
    """Logging 0 is a measurement. He was here and did not work. It must not
    fall back to the prescription."""
    out = _node(
        "(()=>{const w=%s;"
        "const hours=[{minutes:60},{minutes:60}];"
        "const a=e.allocateActual(hours,0,w);"
        "return {rule:a.rule,duties:a.duties,actual:a.actual};})()" % WORKER)
    assert out["rule"] == "proportional"
    assert out["actual"] == 0
    assert out["duties"] == pytest.approx([0.0, 0.0], abs=1e-12)


def test_an_explicit_absence_decays_state_without_advancing_the_ramp():
    out = _node(
        "(()=>{const w=%s;"
        "const days=["
        "{date:'2026-08-01',hourly:Array(24).fill(31.0)},"
        "{date:'2026-08-02',hourly:Array(24).fill(31.0)}];"
        "const logs={'2026-08-01':{minutes:0,note:'Absent',absent:true}};"
        "const r=e.simulate({worker:w,days,logs,initialAdaptation:0.5});"
        "return {first:r.records[0],second:r.records[1],next:r.nextDayOnJob};})()"
        % WORKER)
    assert out["first"]["absent"] is True
    assert out["first"]["dayOnJob"] == 1
    assert out["first"]["stimulus"] == 0
    assert out["first"]["adaptationEnd"] < out["first"]["adaptationStart"]
    assert out["second"]["dayOnJob"] == 1
    assert out["next"] == 2


def test_returning_worker_uses_the_published_calendar_comparator_only():
    returning = WORKER[:-1] + ",rampType:'returning'}"
    out = _node(
        "(()=>{const w=%s;return [1,2,3,4,5].map(d=>e.calendarMinutes(d,w));})()"
        % returning)
    assert out == [240, 288, 384, 480, 480]


def test_weather_window_does_not_restart_an_older_hire_at_day_one():
    out = _node_compute(
        "c.firstDayOnJob({hireDate:'2026-08-01'},'2026-08-08',"
        "{'2026-08-03':{minutes:0,note:'Absent'}})")
    assert out == 7


def test_overexposure_counts_only_unauthorised_hours_above_the_limit():
    out = _node(
        "(()=>{"
        "const hours=[{minutes:30,overLimit:2.0},{minutes:60,overLimit:-1.0},"
        "             {minutes:0,overLimit:4.0}];"
        "const alloc={duties:[1.0,1.0,0.5]};"
        "return e.overexposure(hours,alloc);})()")
    # hour 1: extra duty 0.5 over a 2.0 degC excess -> 1.0
    # hour 2: below the limit -> contributes nothing even though duty rose
    # hour 3: extra duty 0.5 over a 4.0 degC excess -> 2.0
    assert out == pytest.approx(3.0, abs=1e-12)


def test_an_unlogged_day_is_marked_assumed_and_uses_the_prescription():
    out = _node(
        "(()=>{const w=%s;"
        "const days=[{date:'2026-08-01',hourly:Array(24).fill(31.0)}];"
        "const r=e.simulate({worker:w,days,logs:{}});"
        "const d=r.records[0];"
        "return {assumed:d.assumed,rule:d.allocationRule,"
        "        actual:d.actualMinutes,prescribed:d.prescribedMinutes};})()"
        % WORKER)
    assert out["assumed"] is True
    assert out["rule"] == "prescribed"
    assert out["actual"] == out["prescribed"]


def test_the_demo_contains_one_evidence_based_full_heat_work_shift():
    out = _node(
        "(()=>{"
        "(0,eval)(readFileSync('app/data/weather.js','utf8'));"
        "(0,eval)(readFileSync('app/data/seed.js','utf8'));"
        "const w=window.SUNUP_SEED.workers.find(x=>x.id==='wkr_whitfield');"
        "const date=window.SUNUP_SEED.today;"
        "const hourly=window.SUNUP_WEATHER.series.cool_site[date];"
        "const record=e.simulate({worker:w,days:[{date,hourly}],logs:{}}).records[0];"
        "return {start:w.shiftStart,end:w.shiftEnd,minutes:record.prescribedMinutes,"
        "status:record.status,peak:record.peakWbgt};})()")
    assert out["start"] == 1
    assert out["end"] == 9
    assert out["minutes"] == 480
    assert out["status"] == "cleared"
    assert out["peak"] <= 28.0


def test_demo_v2_migrates_only_the_untouched_seed_worker():
    out = _node(
        "await (async()=>{"
        "(0,eval)(readFileSync('app/data/seed.js','utf8'));"
        "window.SUNUP_WEATHER={series:{}};"
        "const memory={};"
        "globalThis.localStorage={"
        "getItem:key=>Object.prototype.hasOwnProperty.call(memory,key)?memory[key]:null,"
        "setItem:(key,value)=>{memory[key]=value;}};"
        "const makeState=()=>({"
        "sites:window.SUNUP_SEED.sites.map(x=>({...x,seeded:true})),"
        "crews:window.SUNUP_SEED.crews.map(x=>({...x,seeded:true})),"
        "workers:window.SUNUP_SEED.workers.map(x=>({...x,seeded:true})),"
        "dayLogs:{},weatherSeries:{},exceptionAcknowledgements:{},seeded:1});"
        "const store=await import('./app/js/store.js');"
        "const untouched=makeState();"
        "Object.assign(untouched.workers.find(x=>x.id==='wkr_whitfield'),"
        "{shiftStart:5,shiftEnd:13});"
        "memory['sunup.store.v1']=JSON.stringify(untouched);"
        "await store.initStore();"
        "const migrated=store.worker('wkr_whitfield');"
        "const edited=makeState();"
        "Object.assign(edited.workers.find(x=>x.id==='wkr_whitfield'),"
        "{shiftStart:4,shiftEnd:12});"
        "memory['sunup.store.v1']=JSON.stringify(edited);"
        "await store.initStore();"
        "const preserved=store.worker('wkr_whitfield');"
        "return {migrated:[migrated.shiftStart,migrated.shiftEnd],"
        "preserved:[preserved.shiftStart,preserved.shiftEnd]};})()")
    assert out == {"migrated": [1, 9], "preserved": [4, 12]}


def test_day_logs_cannot_exceed_the_assigned_shift():
    out = _node(
        "await (async()=>{"
        "(0,eval)(readFileSync('app/data/seed.js','utf8'));"
        "window.SUNUP_WEATHER={series:{}};"
        "const memory={};"
        "globalThis.localStorage={getItem:key=>memory[key]||null,"
        "setItem:(key,value)=>{memory[key]=value;}};"
        "const store=await import('./app/js/store.js');"
        "await store.initStore();"
        "const w=window.SUNUP_SEED.workers[0];"
        "let error=''; try { store.setDayLog(w.id,'2026-08-09',481,''); }"
        "catch (e) { error=e.message; }"
        "return {error,stored:store.logsFor(w.id)['2026-08-09']||null};})()")
    assert "cannot exceed" in out["error"]
    assert out["stored"] is None


def test_saved_multiplicative_weather_estimates_are_removed_on_migration():
    out = _node(
        "await (async()=>{"
        "(0,eval)(readFileSync('app/data/seed.js','utf8'));"
        "window.SUNUP_WEATHER={series:{}};"
        "const memory={};"
        "const saved={sites:[{id:'s',weatherSource:'derived',seriesKey:'derived_s',"
        "derivedNote:'scaled'}],crews:[],workers:[],dayLogs:{},"
        "weatherSeries:{derived_s:{'2026-08-01':[30]}},"
        "exceptionAcknowledgements:{},seeded:2};"
        "memory['sunup.store.v1']=JSON.stringify(saved);"
        "globalThis.localStorage={getItem:key=>memory[key]||null,"
        "setItem:(key,value)=>{memory[key]=value;}};"
        "const store=await import('./app/js/store.js');"
        "await store.initStore(); const site=store.site('s');"
        "return {source:site.weatherSource,key:site.seriesKey,status:site.weatherStatus,"
        "error:site.weatherError,series:store.getState().weatherSeries};})()")
    assert out["source"] == "none"
    assert out["key"] is None
    assert out["status"] == "error"
    assert "not a site measurement" in out["error"]
    assert out["series"] == {}


def test_live_site_uses_the_current_arizona_forecast_as_its_active_plan():
    out = _node(
        "await (async()=>{"
        "const compute=await import('./app/js/compute.js');"
        "const today=compute.today();"
        "const value=new Date(today+'T00:00:00Z'); value.setUTCDate(value.getUTCDate()-1);"
        "const prior=value.toISOString().slice(0,10);"
        "window.SUNUP_WEATHER={dates:[prior],series:{live:{"
        "[prior]:Array(24).fill(29),[today]:Array(24).fill(30)}}};"
        "const memory={}; const saved={sites:[{id:'s',seriesKey:'live',"
        "weatherSource:'live',weatherDates:[prior],weatherForecastDates:[today],"
        "weatherAsOfDate:prior}],crews:[{id:'c',siteId:'s'}],workers:[{id:'w',"
        "crewId:'c',trade:'concrete',clothing:'work_clothes',shiftStart:5,shiftEnd:13,"
        "hireDate:prior,rampType:'new',active:true}],dayLogs:{},weatherSeries:{},"
        "exceptionAcknowledgements:{},seeded:2};"
        "memory['sunup.store.v1']=JSON.stringify(saved);"
        "globalThis.localStorage={getItem:key=>memory[key]||null,"
        "setItem:(key,data)=>{memory[key]=data;}};"
        "const store=await import('./app/js/store.js'); await store.initStore();"
        "const result=compute.forWorker('w');"
        "return {today,active:result.current.date,projected:result.current.projected,"
        "observed:result.observed.map(x=>x.date)};})()")
    assert out["active"] == out["today"]
    assert out["projected"] is True
    assert len(out["observed"]) == 1


def test_complete_live_sites_refresh_when_their_observation_window_is_stale():
    out = _node(
        "await (async()=>{"
        "const weather=await import('./app/js/siteweather.js');"
        "const site={weatherSource:'live',weatherAsOfDate:'2026-08-28',"
        "weatherDates:['2026-08-28'],weatherForecastDates:['2026-08-29']};"
        "return {current:weather.siteNeedsRefresh(site,'2026-08-28'),"
        "stale:weather.siteNeedsRefresh(site,'2026-08-29'),"
        "cached:weather.siteNeedsRefresh({...site,weatherSource:'cached'},'2026-08-29'),"
        "brokenForecast:weather.siteNeedsRefresh({...site,weatherForecastDates:[]},"
        "'2026-08-28')};})()")
    assert out == {
        "current": False,
        "stale": True,
        "cached": False,
        "brokenForecast": True,
    }


def test_intervention_uses_the_existing_engine_and_respects_an_hourly_cap():
    out = _node(
        "await (async()=>{"
        "const i=await import('./app/js/interventions.js');"
        "const w=%s;"
        "const base=i.evaluateIntervention({hourly:Array(24).fill(24),worker:w,adaptation:0});"
        "const capped=i.evaluateIntervention({hourly:Array(24).fill(24),worker:w,adaptation:0,capMinutes:30});"
        "return {base:base.plannedMinutes,capped:capped.plannedMinutes,"
        "recovery:capped.recoveryMinutes,hours:capped.hours.map(h=>h.minutes)};})()"
        % WORKER)
    assert out["base"] == 480
    assert out["capped"] == 240
    assert out["recovery"] == 240
    assert out["hours"] == [30] * 8


def test_intervention_suggestion_selects_a_better_available_site():
    out = _node(
        "await (async()=>{"
        "const i=await import('./app/js/interventions.js');"
        "const w=%s;"
        "const suggestion=i.suggestIntervention({"
        "sites:[{siteId:'hot',hourly:Array(24).fill(40)},"
        "{siteId:'cool',hourly:Array(24).fill(20)}],"
        "currentSiteId:'hot',worker:w,adaptation:0});"
        "const none=i.suggestIntervention({"
        "sites:[{siteId:'hot',hourly:Array(24).fill(40)},"
        "{siteId:'same',hourly:Array(24).fill(40)}],"
        "currentSiteId:'hot',worker:w,adaptation:0});"
        "return {siteId:suggestion.siteId,start:suggestion.shiftStart,"
        "end:suggestion.shiftEnd,gain:suggestion.gain,none:none===null};})()"
        % WORKER)
    assert out == {"siteId": "cool", "start": 6, "end": 14,
                   "gain": 480, "none": True}


def test_crew_optimizer_recovers_time_without_reducing_any_worker():
    out = _node(
        "await (async()=>{"
        "const i=await import('./app/js/interventions.js');"
        "const hourly=Array(24).fill(20);"
        "for(let h=8;h<18;h+=1) hourly[h]=40;"
        "const make=(id,start)=>{const w={id,trade:'concrete',clothing:'work_clothes',"
        "shiftStart:start,shiftEnd:start+8,workClassOverride:null,active:true};"
        "const base=i.evaluateIntervention({hourly,worker:w,adaptation:0});"
        "return {worker:w,currentHourly:hourly,current:{adaptationStart:0,"
        "prescribedMinutes:base.plannedMinutes}};};"
        "const result=i.optimizeCrewShift([make('a',6),make('b',7)]);"
        "const rec=result.recommendation;"
        "return {available:result.available,start:rec.shiftStart,gain:rec.gain,"
        "helped:rec.helped,noLoss:rec.workers.every(w=>w.gain>=0),"
        "durations:rec.workers.map(w=>w.shiftEnd-w.shiftStart)};})()")
    assert out["available"] is True
    assert out["start"] == 5
    assert out["gain"] > 0
    assert out["helped"] == 2
    assert out["noLoss"] is True
    assert out["durations"] == [8, 8]


def test_crew_optimizer_refuses_partial_weather_and_no_gain_plans():
    out = _node(
        "await (async()=>{"
        "const i=await import('./app/js/interventions.js');"
        "const w={id:'a',trade:'concrete',clothing:'work_clothes',shiftStart:5,"
        "shiftEnd:13,workClassOverride:null,active:true};"
        "const hourly=Array(24).fill(20);"
        "const plan=i.evaluateIntervention({hourly,worker:w,adaptation:0});"
        "const same=i.optimizeCrewShift([{worker:w,currentHourly:hourly,"
        "current:{adaptationStart:0,prescribedMinutes:plan.plannedMinutes}}]);"
        "const missing=i.optimizeCrewShift([{worker:w,unavailable:true}]);"
        "return {same:same.recommendation===null,missing:missing.available===false,"
        "reason:missing.reason};})()")
    assert out == {"same": True, "missing": True,
                   "reason": "weather-unavailable"}
