"""Generate the M4 interface's data from the engine.

    python scripts/build_roster_data.py

Emitted as a JS module, not JSON: the demo must open straight from file:// and
fetch() is blocked there (SPEC.md hard constraint 6).

THE CREW IS A DESIGNED COMPARISON, NOT A SAMPLE. An earlier version varied
trade, site, shift and day count all at once across eight workers, so nothing on
screen was comparable and the finding was invisible. This one is built around a
MATCHED PAIR — same site, same trade, same day count, differing only in start
time — because that pair IS the product. M3 measured shift timing as the
strongest lever available (+1.07 degC of personal limit, 84/84 tau pairs, both
wet-bulb methods) and this is what that looks like on a roster.

Everyone else is context, and each one is there to show one thing.

constants.py section 7 governs what may appear: trade, clothing, shift and site
are job assignments. Nothing about the person is permitted, and
`Worker.from_mapping` rejects the forbidden set structurally.
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
EARLY_START = 5

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                   "app", "data", "roster.js")

# name, trade, shift, days worked, site, pair role, why this worker is here
CREW = [
    ("A. Reyes",     "concrete",   (5, 13),  5, "hot_site",  "a",
     "Matched pair: identical to B. Osei except the start time."),
    ("B. Osei",      "concrete",   (10, 18), 5, "hot_site",  "b",
     "Matched pair: same site, trade and day count as A. Reyes."),
    ("C. Duarte",    "rebar",      (5, 13),  2, "hot_site",  None,
     "Heavy trade, day 2. Lowest limit on the crew and no adaptation yet."),
    ("D. Whitfield", "electrical", (5, 13),  1, "cool_site", None,
     "Light trade, day 1. The case where the calendar is stricter than the model."),
    ("E. Nakamura",  "carpentry",  (5, 13),  7, "cool_site", None,
     "Mid-ramp on the cooler site."),
    ("F. Okoro",     "roofing",    (5, 13), 14, "hot_site",  None,
     "Fully ramped. What the model looks like when it agrees a worker is ready."),
]


def status_for(minutes: int, shift_hours: int) -> str:
    """Severity band for the chip. Derived from the prescription."""
    full = shift_hours * 60
    if minutes >= full:
        return "cleared"
    if minutes >= full * 0.5:
        return "reduced"
    if minutes > 0:
        return "restricted"
    return "stop"


def mismatch_for(divergence: int) -> str:
    """DESIGN_SYSTEM rule 12, as a signed relationship.

    'over'  = the calendar allows MORE than the model. Under-protection, the
              dangerous direction, and the product's whole argument.
    'under' = the calendar allows LESS. Productive hours a blanket rule was
              throwing away.
    """
    if divergence < 0:
        return "over"
    if divergence > 0:
        return "under"
    return "none"


def hour_payload(hour: ac.HourPrescription) -> dict:
    return {
        "hour": hour.hour,
        "wbgt": round(hour.effective_wbgt_c, 2),
        "limit": round(hour.personal_limit_c, 2),
        "overLimit": round(hour.excess_over_limit_c, 2),
        "minutes": hour.minutes,
        "stop": hour.is_stop_work,
    }


def day_payload(record: ac.DayRecord, shift_hours: int) -> dict:
    full = shift_hours * 60
    calendar = int(round(record.calendar_pct / 100.0 * full))
    divergence = record.shift_work_minutes - calendar
    return {
        "date": record.date.isoformat(),
        "dayOnJob": record.day_on_job,
        "absent": record.absent,
        "projected": record.projected,
        "minutes": record.shift_work_minutes,
        "calendarMinutes": calendar,
        "divergence": divergence,
        "mismatch": mismatch_for(divergence),
        "limit": round(record.personal_limit_c, 2),
        # Present because the DETAIL view needs it. DESIGN_SYSTEM rule 10
        # forbids rendering it on a collapsed row; that is enforced in the
        # roster component and asserted in tests/test_m4_interface.py.
        "adaptation": round(record.adaptation_start, 4),
        "peakWbgt": None if record.absent else round(record.peak_effective_wbgt_c, 2),
        "status": "absent" if record.absent
        else status_for(record.shift_work_minutes, shift_hours),
        "hours": [] if record.absent else [hour_payload(h) for h in record.hours],
    }


def levers(cache, worker, site, other_site, today, adaptation, minutes_now,
           calendar_minutes, day_on_job, hours):
    """Why THIS worker is where he is, and what would move him.

    Two separate jobs, and the previous versions kept collapsing them into one:

      REASON  a diagnosis. Read off the hour-by-hour prescription: the first
              hour his effective WBGT crosses his own limit, and by how much at
              the worst hour. Every worker has a different answer because every
              worker has a different limit and a different shift window, so the
              column stops repeating itself without anything being invented.

      SHORT   an action, priced in minutes. The largest of the levers an
              employer can actually pull.

    Levers considered:

      SHIFT       start at 05:00 instead of this worker's start
      ADAPTATION  this worker at A = 1.0 instead of today's state
      SITE        the same worker at the other selected site -- kept precisely
                  because M3 measured it as NOT surviving (0/84, +0.23 degC).
                  Pricing a lever that does nothing is how you show it does
                  nothing.

    Deliberately NOT a lever: reassigning the worker to a lighter NIOSH work
    class. It prices enormously -- moderate RAL 25.0 vs light 28.0 degC, per
    constants.py section 2 -- and it is not an action. Trades are not
    interchangeable; you cannot answer "this man is over his limit" with "make
    him an electrician". A lever nobody can pull is noise in a column that is
    supposed to drive a decision.
    """
    rung = C.MATERIAL_DIVERGENCE_MIN_PER_HOUR

    def variant(start=None, adapt=None, at_site=None):
        candidate = ac.Worker(
            worker_id=worker.worker_id,
            trade=worker.trade,
            clothing=worker.clothing,
            shift_start_hour=worker.shift_start_hour if start is None else start,
            shift_end_hour=(worker.shift_end_hour if start is None
                            else start + worker.shift_hours))
        target = cache.get(at_site or site, today, MODEL)
        return sum(h.minutes for h in ac.prescribe_hours(
            target, candidate, adaptation if adapt is None else adapt))

    if_early = variant(start=EARLY_START)
    if_adapted = variant(adapt=1.0)
    if_other_site = variant(at_site=other_site)

    # --- the diagnosis ----------------------------------------------------
    over = [h for h in hours if h["overLimit"] > 0]
    if not hours:
        reason = "no shift today"
    elif not over:
        reason = "within limit all shift"
    else:
        # Terse on purpose: this sits in a roster column, and the START column
        # two cells to the left already says whether that hour is the shift
        # start. The drawer carries the sentence.
        worst = max(over, key=lambda h: h["overLimit"])
        reason = ("over from %02d:00 - peak +%.1f degC"
                  % (over[0]["hour"], worst["overLimit"]))

    common = {
        "ifEarlyShift": if_early,
        "ifFullyAdapted": if_adapted,
        "ifOtherSite": if_other_site,
        "alreadyEarly": worker.shift_start_hour == EARLY_START,
        "reason": reason,
    }

    # --- the action -------------------------------------------------------
    # Where the model already clears MORE than the calendar, nothing is binding
    # on the worker and the lever is not his to pull. That is a different
    # sentence, not a smaller number.
    if calendar_minutes < minutes_now - rung:
        surplus = minutes_now - calendar_minutes
        pct = round(100.0 * calendar_minutes / (worker.shift_hours * 60))
        common.update({
            "short": "calendar discards %d min" % surplus,
            "detail": ("Nothing in today's conditions is binding on this worker. "
                       "The %d%% day-%d step of the OSHA ramp is, and it discards "
                       "%d min the model would clear."
                       % (pct, day_on_job, surplus)),
        })
        return common

    candidates = [
        (if_early - minutes_now,
         "start %02d:00 -> %d min (+%d)"
         % (EARLY_START, if_early, if_early - minutes_now),
         "Starting at %02d:00 instead of %02d:00 would allow %d min today (+%d)."
         % (EARLY_START, worker.shift_start_hour, if_early, if_early - minutes_now)),

        (if_adapted - minutes_now,
         "fully adapted -> %d min (+%d)" % (if_adapted, if_adapted - minutes_now),
         "A fully adapted worker in these exact conditions would be allowed "
         "%d min today (+%d). He is on day %d."
         % (if_adapted, if_adapted - minutes_now, day_on_job)),

        (if_other_site - minutes_now,
         "other site -> %d min (+%d)"
         % (if_other_site, if_other_site - minutes_now),
         "The same worker at the other selected site would be allowed %d min "
         "today (+%d). M3 measured site assignment as the weakest of the "
         "levers." % (if_other_site, if_other_site - minutes_now)),
    ]
    gain, short, detail = max(candidates, key=lambda c: c[0])

    # A lever has to be worth at least one rung of the work/rest ladder to be named.
    # Below that it is not a different instruction.
    if gain < rung:
        short = "no lever worth %d min" % rung
        detail = ("No single change -- shift, adaptation or site -- recovers "
                  "%d min for this worker today." % rung)

    common.update({"short": short, "detail": detail})
    return common


def main():
    cache = bf.BackfillCache()
    dates = cache.shared_dates(MODEL)
    if len(dates) < DAYS_BEHIND + 1:
        raise SystemExit("need %d backfilled days, have %d"
                         % (DAYS_BEHIND + 1, len(dates)))
    today = dates[-1]
    window = dates[-(DAYS_BEHIND + 1):]

    workers = []
    for name, trade, shift, worked, site, pair, note in CREW:
        worker = ac.Worker.from_mapping({
            "worker_id": name, "trade": trade,
            "shift_start_hour": shift[0], "shift_end_hour": shift[1],
        })
        history = []
        for index, date in enumerate(window):
            if len(window) - index > worked:
                history.append(ac.Absence(date, "not yet on this job"))
            else:
                history.append(cache.get(site, date, MODEL))
        observed = ac.simulate(worker, history, full_stimulus_degree_hours=NORM,
                               natural_wet_bulb_model=MODEL)
        forward = ac.project(observed,
                             ac.repeat_day(cache.get(site, today, MODEL), DAYS_AHEAD))

        strip = [day_payload(d, worker.shift_hours) for d in forward.days]
        current = next(d for d in strip if d["date"] == today.isoformat())
        workers.append({
            "id": name,
            "name": name,
            "trade": trade,
            "workClass": worker.work_class.value,
            "site": site,
            "siteLabel": "p95 hot" if site == "hot_site" else "p5 cool",
            "shift": "%02d:00" % shift[0],
            "shiftFull": "%02d:00-%02d:00" % shift,
            "shiftStart": shift[0],
            "shiftHours": worker.shift_hours,
            "pair": pair,
            "note": note,
            "today": current,
            "levers": levers(cache, worker, site,
                             "cool_site" if site == "hot_site" else "hot_site",
                             today, current["adaptation"], current["minutes"],
                             current["calendarMinutes"], current["dayOnJob"],
                             current["hours"]),
            "strip": strip,
        })

    sample = cache.get("hot_site", today, MODEL)
    payload = {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "daysBehind": DAYS_BEHIND,
        "daysAhead": DAYS_AHEAD,
        "earlyStart": EARLY_START,
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
        "sites": {
            name: {
                "exceedanceHours": round(site.exceedance_hours, 2),
                "hoursPerDay": round(site.hours_per_day_above_threshold, 2),
                "percentile": site.percentile,
            }
            for name, site in cache.sites.items()
        },
        "workers": workers,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("/* GENERATED by scripts/build_roster_data.py - do not edit. */\n")
        fh.write("window.ROSTER_DATA = ")
        json.dump(payload, fh, separators=(",", ":"))
        fh.write(";\n")

    print("wrote %s (%.0f KB)" % (os.path.relpath(OUT),
                                  os.path.getsize(OUT) / 1024))
    print("  today %s, %d workers" % (today, len(workers)))
    for w in workers:
        t = w["today"]
        mark = {"a": "PAIR A", "b": "PAIR B"}.get(w["pair"], "")
        print("    %-13s %-10s %s %-8s %3d min  cal %3d  %+4d  %-10s %-18s %s"
              % (w["name"], w["trade"], w["shift"], w["siteLabel"],
                 t["minutes"], t["calendarMinutes"], t["divergence"],
                 t["mismatch"], w["levers"]["reason"], mark))


if __name__ == "__main__":
    main()
