"""Seed roster and hourly weather for the browser app.

    python scripts/build_app_data.py

Emits two generated modules:

  app/data/weather.js   hourly WBGT per site-series per date. Worker-independent,
                        so it is computed once here and never recomputed in the
                        browser. This is the ONLY thing the Python pipeline still
                        hands to the app, everything per-worker now runs in
                        app/js/engine.js.

  app/data/seed.js      the starting roster: sites, crews, workers, day logs.

WHY THE SEED IS DATA AND NOT CONTENT. The old build baked finished prescriptions
into roster.js, so the demo crew was the application. Here the seed is written
into an empty localStorage store on first load and is thereafter ordinary
editable data, rename it, re-trade it, delete it, or put it back from Settings.
Every seeded record carries `seeded: true` so the interface can mark it.

Shipped as a script tag rather than JSON so the app still runs from file:// with
no server and no fetch. Same content, same purpose.

THE DAY LOGS ARE DELIBERATELY IMPERFECT. They include a worker who exceeded his
prescription, a worker who logged work on a stop-work day, and several days with
no entry at all, because a roster where every day is neatly logged would never
exercise the assumed-day fallback or the overexposure metric.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from acclimate import acclimatization as ac  # noqa: E402
from acclimate import backfill as bf  # noqa: E402
from acclimate import constants as C  # noqa: E402
from acclimate import wbgt  # noqa: E402
from acclimate.sources.fixtures import FixtureStore  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
WEATHER_OUT = os.path.join(HERE, "..", "app", "data", "weather.js")
SEED_OUT = os.path.join(HERE, "..", "app", "data", "seed.js")

MODEL = wbgt.NWB_PSYCHROMETRIC
SEED_VERSION = 1

SITES = [
    ("site_north", "North Yard", "hot_site", "p95 exceedance"),
    ("site_east", "East Lot", "cool_site", "p5 exceedance"),
]

CREWS = [
    ("crew_conc", "Concrete", "site_north"),
    ("crew_rebar", "Rebar", "site_north"),
    ("crew_roof", "Roofing", "site_north"),
    ("crew_carp", "Carpentry", "site_east"),
    ("crew_elec", "Electrical", "site_east"),
]

# name, crew, trade, clothing, shift, days on job at the demo date
SITE_BY_CREW = {cid: dict((s[0], s[2]) for s in SITES)[sid]
                for cid, _n, sid in CREWS}

CREW_ROSTER = [
    ("A. Reyes", "crew_conc", "concrete", "work_clothes", (5, 13), 5),
    ("B. Osei", "crew_conc", "concrete", "work_clothes", (10, 18), 5),
    ("M. Haddad", "crew_conc", "concrete", "work_clothes", (5, 13), 11),
    ("C. Duarte", "crew_rebar", "rebar", "work_clothes", (5, 13), 2),
    ("R. Nkemdirim", "crew_rebar", "rebar", "work_clothes", (6, 14), 9),
    ("F. Okoro", "crew_roof", "roofing", "work_clothes", (5, 13), 14),
    ("T. Lindqvist", "crew_roof", "roofing", "coveralls", (5, 13), 4),
    ("E. Nakamura", "crew_carp", "carpentry", "work_clothes", (5, 13), 7),
    ("J. Baptiste", "crew_carp", "carpentry", "work_clothes", (7, 15), 13),
    ("D. Whitfield", "crew_elec", "electrical", "work_clothes", (5, 13), 1),
    ("S. Varga", "crew_elec", "electrical", "work_clothes", (6, 14), 8),
]


def main():
    cache = bf.BackfillCache()
    dates = cache.shared_dates(MODEL)
    today = dates[-1]

    # ---- weather -------------------------------------------------------
    series = {}
    for _sid, _name, series_key, _note in SITES:
        series[series_key] = {
            d.isoformat(): [round(h.wbgt_c, 3) for h in cache.get(series_key, d, MODEL).hours]
            for d in dates
        }

    selection = FixtureStore().load("site_selection/phoenix_40c_selection.json")
    weather = {
        "model": MODEL,
        "today": today.isoformat(),
        "dates": [d.isoformat() for d in dates],
        "series": series,
        "siteMeta": {
            key: {
                "lon": selection[key]["centroid_lon_lat"][0],
                "lat": selection[key]["centroid_lon_lat"][1],
                "exceedanceHours": selection[key]["value_hours"],
                "percentile": round(selection[key]["percentile"], 1),
            }
            for _s, _n, key, _note in SITES
        },
    }

    write(WEATHER_OUT, "window.ACCLIMATE_WEATHER", weather, "build_app_data.py")

    # ---- seed roster ---------------------------------------------------
    sites = [
        {"id": sid, "name": name, "seriesKey": key, "weatherSource": "measured",
         "note": note, "polygon": None}
        for sid, name, key, note in SITES
    ]
    crews = [{"id": cid, "name": name, "siteId": sid} for cid, name, sid in CREWS]

    workers = []
    for name, crew_id, trade, clothing, shift, day_on_job in CREW_ROSTER:
        hire = today - dt.timedelta(days=day_on_job - 1)
        workers.append({
            "id": "wkr_" + name.split(".")[-1].strip().lower().replace(" ", ""),
            "name": name,
            "crewId": crew_id,
            "trade": trade,
            "workClassOverride": None,
            "clothing": clothing,
            "shiftStart": shift[0],
            "shiftEnd": shift[1],
            "hireDate": hire.isoformat(),
            "active": True,
        })

    day_logs = seed_day_logs(workers, dates, today, cache)

    seed = {
        "version": SEED_VERSION,
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "sites": sites,
        "crews": crews,
        "workers": workers,
        "dayLogs": day_logs,
    }
    write(SEED_OUT, "window.ACCLIMATE_SEED", seed, "build_app_data.py")

    logged = sum(len(v) for v in day_logs.values())
    print("  %d sites, %d crews, %d workers, %d logged days"
          % (len(sites), len(crews), len(workers), logged))
    print("  weather: %d series x %d dates x 24 h" % (len(series), len(dates)))


def seed_day_logs(workers, dates, today, cache):
    """A believable, incomplete log.

    Actuals are generated from the REAL prescription, the Python engine is run
    for each worker and each day, and the logged minutes sit close to what was
    prescribed, because that is what a compliant crew looks like. A flat
    percentage of the shift would have made every worker on a restricted
    schedule look permanently overexposed, which is a story the seed should not
    tell by accident.

    Three exceptions are deliberate, so the feedback loop has something to show
    on the first screen: a worker who ran over on two days, a worker who was
    asked to cover on a day the model prescribed zero, and one who was present
    and worked nothing. The most recent three days are left blank so the
    assumed-day fallback is visible too.
    """
    logs = {}
    by_name = {w["name"]: w for w in workers}
    recent = set(dates[-3:])

    def put(name, date, minutes, note=""):
        worker = by_name[name]
        logs.setdefault(worker["id"], {})[date.isoformat()] = {
            "minutes": int(minutes), "note": note}

    for worker in workers:
        site_key = SITE_BY_CREW[worker["crewId"]]
        hire = dt.date.fromisoformat(worker["hireDate"])
        history = [d for d in dates if d >= hire]
        if not history:
            continue
        engine_worker = ac.Worker(
            worker_id=worker["id"], trade=worker["trade"],
            clothing=worker["clothing"],
            shift_start_hour=worker["shiftStart"],
            shift_end_hour=worker["shiftEnd"])
        ramp = ac.simulate(
            engine_worker, [cache.get(site_key, d, MODEL) for d in history],
            full_stimulus_degree_hours=C.DEGREE_HOURS_FULL_STIMULUS)
        for record, date in zip(ramp.days, history):
            if date in recent:
                continue
            prescribed = record.shift_work_minutes
            # A crew that mostly does as it is told, with ordinary slippage.
            jitter = (hash((worker["id"], date.isoformat())) % 3 - 1) * 15
            put(worker["name"], date, max(0, prescribed + jitter))

    # The three deliberate cases.
    put("M. Haddad", dates[-5], 420, "pour ran long")
    put("M. Haddad", dates[-4], 400, "pour ran long")
    put("B. Osei", dates[-6], 180, "asked to cover an inspection")
    put("C. Duarte", dates[-4], 0, "sent home, felt unwell")
    return logs


def write(path, global_name, payload, generator):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("/* GENERATED by scripts/%s - do not edit. */\n" % generator)
        fh.write("%s = " % global_name)
        json.dump(payload, fh, separators=(",", ":"))
        fh.write(";\n")
    print("wrote %s (%d KB)" % (os.path.relpath(path), os.path.getsize(path) // 1024 or 1))


if __name__ == "__main__":
    main()
