"""Generate the M4 interface's data file from the engine.

    python scripts/build_roster_data.py

Writes app/data/roster.json. The interface is a static page with no build step
and no network access — SPEC.md hard constraint 6 — so every number it shows is
computed here, once, from real retrieved site-days.

The roster itself (who is on the crew, which trade, which shift, how many days
in) is EMPLOYER data. constants.py section 7 governs what may appear here: trade,
clothing, shift and site are job assignments; nothing about the person is
permitted, and `Worker.from_mapping` rejects the forbidden set structurally.
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

MODEL = wbgt.NWB_PSYCHROMETRIC
NORM = C.DEGREE_HOURS_FULL_STIMULUS
DAYS_BEHIND = 7
DAYS_AHEAD = 6

# Emitted as a JS module, not JSON: the demo must open straight from file://
# and fetch() is blocked there. SPEC.md hard constraint 6 — a demo that needs a
# server is one more thing that can fail on stage.
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                   "app", "data", "roster.js")

# name, trade, shift, days already worked, site
CREW = [
    ("R. Alvarez",   "rebar",      (5, 13),  2, "hot_site"),
    ("D. Okonkwo",   "concrete",   (5, 13),  4, "hot_site"),
    ("M. Castillo",  "concrete",   (10, 18), 4, "hot_site"),
    ("J. Whitfield", "electrical", (5, 13),  1, "cool_site"),
    ("S. Traore",    "masonry",    (6, 14),  9, "cool_site"),
    ("P. Nguyen",    "roofing",    (5, 13), 14, "hot_site"),
    ("L. Baptiste",  "formwork",   (8, 16),  3, "hot_site"),
    ("K. Mensah",    "carpentry",  (5, 13),  7, "cool_site"),
]


def status_for(minutes: int, shift_hours: int) -> str:
    """StatusChip band. Derived from the prescription, never from temperature."""
    full = shift_hours * 60
    if minutes >= full:
        return "cleared"
    if minutes >= full * 0.5:
        return "reduced"
    if minutes > 0:
        return "restricted"
    return "stop"


def hour_payload(hour: ac.HourPrescription) -> dict:
    return {
        "hour": hour.hour,
        "wbgt": round(hour.effective_wbgt_c, 2),
        "limit": round(hour.personal_limit_c, 2),
        "overLimit": round(hour.excess_over_limit_c, 2),
        "overRal": round(hour.excess_over_ral_c, 2),
        "minutes": hour.minutes,
        "stop": hour.is_stop_work,
    }


def day_payload(record: ac.DayRecord, shift_hours: int) -> dict:
    full = shift_hours * 60
    calendar_minutes = int(round(record.calendar_pct / 100.0 * full))
    return {
        "date": record.date.isoformat(),
        "dayOnJob": record.day_on_job,
        "absent": record.absent,
        "projected": record.projected,
        "minutes": record.shift_work_minutes,
        "calendarMinutes": calendar_minutes,
        "divergence": record.shift_work_minutes - calendar_minutes,
        "limit": round(record.personal_limit_c, 2),
        # Adaptation ships in the payload because the DETAIL view needs it.
        # DESIGN_SYSTEM.md non-negotiable 10 forbids rendering it on a collapsed
        # row, which is a rendering rule enforced in the roster component.
        "adaptation": round(record.adaptation_start, 4),
        "peakWbgt": (None if record.absent
                     else round(record.peak_effective_wbgt_c, 2)),
        "status": ("absent" if record.absent
                   else status_for(record.shift_work_minutes, shift_hours)),
        "hours": [] if record.absent else [hour_payload(h) for h in record.hours],
    }


def main():
    cache = bf.BackfillCache()
    dates = cache.shared_dates(MODEL)
    if len(dates) < DAYS_BEHIND + 1:
        raise SystemExit("need %d backfilled days, have %d"
                         % (DAYS_BEHIND + 1, len(dates)))
    today = dates[-1]
    window = dates[-(DAYS_BEHIND + 1):]

    workers = []
    for name, trade, shift, worked, site in CREW:
        worker = ac.Worker.from_mapping({
            "worker_id": name, "trade": trade,
            "shift_start_hour": shift[0], "shift_end_hour": shift[1],
        })
        # Days before the worker started are absences, so the strip is the same
        # width for everyone and the state decays correctly across any gap.
        history = []
        for index, date in enumerate(window):
            remaining = len(window) - index
            if remaining > worked:
                history.append(ac.Absence(date, "not yet on this job"))
            else:
                history.append(cache.get(site, date, MODEL))
        observed = ac.simulate(worker, history, full_stimulus_degree_hours=NORM,
                               natural_wet_bulb_model=MODEL)
        forward = ac.project(observed, ac.repeat_day(cache.get(site, today, MODEL),
                                                     DAYS_AHEAD))

        strip = [day_payload(d, worker.shift_hours) for d in forward.days]
        current = next(d for d in strip if d["date"] == today.isoformat())
        workers.append({
            "id": name,
            "name": name,
            "trade": trade,
            "workClass": worker.work_class.value,
            "site": site,
            "shift": "%02d:00-%02d:00" % shift,
            "shiftHours": worker.shift_hours,
            "clothing": worker.clothing,
            "today": current,
            "strip": strip,
        })

    site_meta = {
        name: {
            "exceedanceHours": round(site.exceedance_hours, 2),
            "hoursPerDay": round(site.hours_per_day_above_threshold, 2),
            "percentile": site.percentile,
        }
        for name, site in cache.sites.items()
    }
    sample = cache.get("hot_site", today, MODEL)

    payload = {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "daysBehind": DAYS_BEHIND,
        "daysAhead": DAYS_AHEAD,
        "model": {
            "wetBulb": MODEL,
            "normalisation": NORM,
            "tauGain": C.TAU_GAIN_DAYS,
            "tauDecay": C.TAU_DECAY_DAYS,
        },
        "provenance": {
            "dryBulb": sample.provenance.dry_bulb,
            "shape": sample.provenance.dry_bulb_shape,
            "wetBulb": sample.provenance.wet_bulb,
            "wind": sample.provenance.wind,
            "assumed": list(sample.provenance.assumed_inputs),
        },
        "sites": site_meta,
        "workers": workers,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("/* GENERATED by scripts/build_roster_data.py - do not edit. */\n")
        fh.write("window.ROSTER_DATA = ")
        json.dump(payload, fh, indent=1)
        fh.write(";\n")
    print("wrote %s" % os.path.relpath(OUT))
    print("  today %s, %d workers, strip %d days (%d observed + %d projected)"
          % (today, len(workers), len(workers[0]["strip"]),
             DAYS_BEHIND + 1, DAYS_AHEAD))
    for w in workers:
        t = w["today"]
        print("    %-13s %-10s %-11s %3d min (calendar %3d, %+4d)  %s"
              % (w["name"], w["trade"], w["shift"], t["minutes"],
                 t["calendarMinutes"], t["divergence"], t["status"]))


if __name__ == "__main__":
    main()
