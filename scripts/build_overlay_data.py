"""Forecast-vs-actual overlay data for M5.

    python scripts/build_overlay_data.py

WHAT IS BEING VALIDATED
-----------------------
The ramp strip draws six days of projection past today. M4 marked them dashed
and called that honesty. M5 has to answer the harder question: WHEN WE
PROJECTED, WERE WE RIGHT?

The projection method is deliberately crude and labelled as such -- `repeat_day`
carries the last observed site-day forward, an "if conditions hold" forecast
(acclimatization.py). This measures what that crudeness costs.

HOW IT IS DONE WITHOUT A FORECAST API
-------------------------------------
The 14-day backfill is split. Standing at the AS-OF date, only the days before
it are used to build the ramp, and the projection runs forward from there. The
days after it are then read from the same backfill as GROUND TRUTH. Nothing is
retrieved that the demo did not already have, so the comparison costs no API
calls and reproduces offline -- but the model genuinely did not see the actual
days when it made the projection.

This is a backtest, not a live forecast. Said plainly in the UI, because a
backtest on 7 days at one site is weak evidence and presenting it as validation
would be the kind of overclaim the rest of this project spent its time removing.

WHAT IS REPORTED
----------------
Per projected day: predicted vs actual prescribed minutes, predicted vs actual
adaptation state, and the peak WBGT that drove each. Plus the three summary
numbers that matter to a supervisor:

  * mean absolute error in prescribed minutes
  * how often the prescription BAND (the status chip) was right, which is what
    a foreman actually acts on
  * the adaptation-state error at the end of the horizon, which is what
    compounds into tomorrow's projection
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

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                   "app", "data", "overlay.js")

MODEL = wbgt.NWB_PSYCHROMETRIC
NORM = C.DEGREE_HOURS_FULL_STIMULUS

# The matched pair, so the overlay speaks about the same two men the roster
# leads with. Same site, same trade, same day count; only the shift differs.
SUBJECTS = [
    ("A. Reyes", "concrete", (5, 13), "hot_site", "a"),
    ("B. Osei", "concrete", (10, 18), "hot_site", "b"),
]

HORIZON = 7


def status_for(minutes: int, shift_hours: int) -> str:
    full = shift_hours * 60
    if minutes <= 0:
        return "stop"
    if minutes >= full:
        return "cleared"
    return "restricted" if minutes < full * 0.5 else "reduced"


def day_payload(record, shift_hours, projected):
    return {
        "date": record.date.isoformat(),
        "dayOnJob": record.day_on_job,
        "projected": projected,
        "minutes": record.shift_work_minutes,
        "adaptation": round(record.adaptation_start, 4),
        "limit": round(record.personal_limit_c, 2),
        "peakWbgt": round(record.peak_effective_wbgt_c, 2),
        "status": status_for(record.shift_work_minutes, shift_hours),
    }


def main():
    cache = bf.BackfillCache()
    dates = cache.shared_dates(MODEL)
    if len(dates) < HORIZON + 2:
        raise SystemExit("need at least %d backfilled days, have %d"
                         % (HORIZON + 2, len(dates)))

    as_of = dates[-(HORIZON + 1)]
    observed_dates = dates[:len(dates) - HORIZON]
    future_dates = dates[len(dates) - HORIZON:]

    subjects = []
    for name, trade, shift, site, pair in SUBJECTS:
        worker = ac.Worker(worker_id=name, trade=trade,
                           shift_start_hour=shift[0], shift_end_hour=shift[1])
        hours = shift[1] - shift[0]

        observed = ac.simulate(
            worker, [cache.get(site, d, MODEL) for d in observed_dates],
            full_stimulus_degree_hours=NORM)

        # THE PROJECTION, made standing at as_of and seeing nothing past it.
        projected = ac.project(
            observed, ac.repeat_day(cache.get(site, as_of, MODEL), HORIZON))
        predicted = [d for d in projected.days if d.projected]

        # THE TRUTH, from the same backfill.
        truth = ac.simulate(
            worker, [cache.get(site, d, MODEL) for d in future_dates],
            initial_adaptation=observed.final_adaptation,
            full_stimulus_degree_hours=NORM,
            first_day_on_job=observed.worked_days + 1)

        pairs = []
        for pred, act in zip(predicted, truth.days):
            pairs.append({
                "predicted": day_payload(pred, hours, True),
                "actual": day_payload(act, hours, False),
                "minutesError": pred.shift_work_minutes - act.shift_work_minutes,
                "bandMatched": (status_for(pred.shift_work_minutes, hours)
                                == status_for(act.shift_work_minutes, hours)),
            })

        errors = [abs(p["minutesError"]) for p in pairs]
        signed = [p["minutesError"] for p in pairs]
        bands = sum(1 for p in pairs if p["bandMatched"])

        # DIRECTION matters more than magnitude for a safety product. A
        # projection that errs low prescribes less work than turned out to be
        # allowed: costly, but safe. One that errs high sends a man out for
        # longer than the day warranted. Report which way it leans.
        bias = sum(signed) / len(signed)

        # A worker prescribed zero every day, predicted and actual, scores a
        # perfect band match while demonstrating no forecast skill whatsoever.
        # Flag it rather than banking it: an accuracy number that cannot be
        # wrong is not an accuracy number.
        actual_minutes = {p["actual"]["minutes"] for p in pairs}
        predicted_minutes = {p["predicted"]["minutes"] for p in pairs}
        degenerate = len(actual_minutes | predicted_minutes) == 1
        subjects.append({
            "id": name,
            "name": name,
            "trade": trade,
            "pair": pair,
            "shift": "%02d:00" % shift[0],
            "shiftFull": "%02d:00-%02d:00" % shift,
            "shiftHours": hours,
            "site": site,
            "siteLabel": "p95 hot" if site == "hot_site" else "p5 cool",
            "history": [day_payload(d, hours, False) for d in observed.days],
            "pairs": pairs,
            "meanAbsMinutesError": round(sum(errors) / len(errors), 1),
            "meanSignedMinutesError": round(bias, 1),
            "biasDirection": ("conservative" if bias < 0
                              else ("permissive" if bias > 0 else "none")),
            "daysPermissive": sum(1 for e in signed if e > 0),
            "maxAbsMinutesError": max(errors),
            "bandsMatched": bands,
            "bandsTotal": len(pairs),
            "degenerate": degenerate,
            "degenerateNote": (
                "Prescribed zero minutes on every day, projected and actual. The "
                "band matches perfectly because it cannot do otherwise; this is "
                "not evidence of forecast skill." if degenerate else ""),
            "adaptationErrorAtHorizon": round(
                predicted[-1].adaptation_start - truth.days[-1].adaptation_start, 4),
        })

    payload = {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "asOf": as_of.isoformat(),
        "horizon": HORIZON,
        "firstProjected": future_dates[0].isoformat(),
        "lastProjected": future_dates[-1].isoformat(),
        "method": "repeat_day: the as-of site-day carried forward unchanged",
        "isBacktest": True,
        "caveat": ("A backtest on %d days at one site, not a live forecast. The "
                   "days after the as-of date come from the same 14-day backfill; "
                   "the model simply did not see them when it projected."
                   % HORIZON),
        "subjects": subjects,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("/* GENERATED by scripts/build_overlay_data.py - do not edit. */\n")
        fh.write("window.OVERLAY_DATA = ")
        json.dump(payload, fh, separators=(",", ":"))
        fh.write(";\n")

    print("wrote %s (%d KB)" % (os.path.relpath(OUT), os.path.getsize(OUT) // 1024))
    print("  as-of %s, projected %s..%s (%d days)"
          % (as_of, future_dates[0], future_dates[-1], HORIZON))
    for subject in subjects:
        print("  %-12s %s  mean |err| %5.1f min, max %3d, bands %d/%d, "
              "dA at horizon %+.3f%s"
              % (subject["name"], subject["shift"],
                 subject["meanAbsMinutesError"], subject["maxAbsMinutesError"],
                 subject["bandsMatched"], subject["bandsTotal"],
                 subject["adaptationErrorAtHorizon"],
                 "   DEGENERATE (always zero)" if subject["degenerate"] else ""))


if __name__ == "__main__":
    main()
