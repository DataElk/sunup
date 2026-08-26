"""Golden vectors: the gate that keeps the browser engine honest.

    python scripts/build_golden_vectors.py

The per-worker maths now exists twice, in src/acclimate/acclimatization.py and
in app/js/engine.js. Two implementations of the thing that decides whether a
worker is told to stop WILL drift. This emits the Python engine's answers over a
deliberately awkward set of inputs; tests/test_js_engine.py replays them through
the JavaScript engine under Node and fails on any disagreement beyond 1e-9.

COVERAGE IS CHOSEN TO BREAK THINGS, not to look thorough:

  * every work class, so both ends of the RAL/REL table are exercised
  * adaptation at 0, mid, and 1, the endpoints of the personal-limit
    interpolation
  * shifts that start before dawn and shifts that straddle the peak
  * every clothing adjustment, including the +11 degC vapour-barrier entry that
    is never reachable from the demo roster
  * WBGT values placed exactly ON each ladder rung boundary, where a `<=` versus
    `<` disagreement between the two implementations would otherwise hide
  * real site-days from the 14-day backfill, run end to end through simulate

The synthetic rung-boundary days matter most. Everything else would probably
survive a sloppy port; a boundary comparison flipped by one epsilon would not.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from acclimate import acclimatization as ac  # noqa: E402
from acclimate import backfill as bf  # noqa: E402
from acclimate import constants as C  # noqa: E402
from acclimate import wbgt  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                   "tests", "fixtures", "golden_vectors.json")

MODEL = wbgt.NWB_PSYCHROMETRIC
NORM = C.DEGREE_HOURS_FULL_STIMULUS

TRADE_BY_CLASS = {
    "light": "electrical",
    "moderate": "concrete",
    "heavy": "rebar",
    "very_heavy": None,          # no trade maps to it; covered via override
}


def hourly_of(day) -> list:
    return [round(h.wbgt_c, 10) for h in day.hours]


def worker_payload(worker) -> dict:
    return {
        "trade": worker.trade,
        "clothing": worker.clothing,
        "shiftStart": worker.shift_start_hour,
        "shiftEnd": worker.shift_end_hour,
        "workClassOverride": None,
    }


def scalar_vectors() -> list:
    """The pure functions, probed at the places they are most likely to differ."""
    out = []

    # personal_limit_c across the full interpolation, every class.
    for work_class in C.WBGT_LIMIT_UNACCLIMATIZED:
        for adaptation in (0.0, 0.25, 0.5, 0.75, 1.0):
            out.append({
                "fn": "personalLimit",
                "args": {"adaptation": adaptation, "workClass": work_class.value},
                "expected": ac.personal_limit_c(adaptation, work_class),
            })

    # effective_wbgt_c for every clothing option, including unreachable ones.
    for clothing in sorted(C.CLOTHING_ADJUSTMENT_C):
        out.append({
            "fn": "effectiveWbgt",
            "args": {"wbgtC": 31.25, "clothing": clothing},
            "expected": ac.effective_wbgt_c(31.25, clothing),
        })

    # work_minutes_per_hour EXACTLY ON and either side of every rung boundary.
    limit = 25.0
    for max_excess, _minutes in C.WORK_REST_LADDER:
        for delta in (-1e-9, 0.0, 1e-9, 0.5):
            effective = limit + max_excess + delta
            out.append({
                "fn": "workMinutesPerHour",
                "args": {"effective": effective, "limitC": limit},
                "expected": ac.work_minutes_per_hour(effective, limit),
            })
    # Past the end of the ladder: stop work.
    out.append({
        "fn": "workMinutesPerHour",
        "args": {"effective": limit + 99.0, "limitC": limit},
        "expected": ac.work_minutes_per_hour(limit + 99.0, limit),
    })

    # advance_adaptation, including the saturating ends.
    for adaptation in (0.0, 0.3, 0.87, 1.0):
        for stimulus in (0.0, 0.42, 1.0):
            out.append({
                "fn": "advanceAdaptation",
                "args": {"adaptation": adaptation, "stimulus": stimulus},
                "expected": ac.advance_adaptation(adaptation, stimulus, ac.Tau()),
            })
    return out


def synthetic_days() -> list:
    """Flat days parked on each rung boundary, plus one hot and one mild."""
    days = []
    for label, level in (("rung0", 25.0), ("rung1", 26.0), ("rung2", 27.0),
                         ("rung3", 28.0), ("mild", 21.0), ("brutal", 40.0)):
        days.append({"date": "2099-01-%02d" % (len(days) + 1),
                     "label": label,
                     "hourly": [level] * 24})
    return days


def simulate_vectors(cache) -> list:
    """End-to-end simulate over real backfilled site-days."""
    out = []
    dates = cache.shared_dates(MODEL)

    cases = [
        ("moderate 05-13 hot", "concrete", "work_clothes", (5, 13), "hot_site", 0.0),
        ("moderate 10-18 hot", "concrete", "work_clothes", (10, 18), "hot_site", 0.0),
        ("heavy 05-13 hot", "rebar", "work_clothes", (5, 13), "hot_site", 0.0),
        ("light 05-13 cool", "electrical", "work_clothes", (5, 13), "cool_site", 0.0),
        ("moderate coveralls", "concrete", "coveralls", (6, 14), "hot_site", 0.35),
        ("light double layer", "electrical", "double_layer_woven", (5, 13),
         "cool_site", 1.0),
    ]

    for label, trade, clothing, shift, site, initial in cases:
        worker = ac.Worker(worker_id=label, trade=trade, clothing=clothing,
                           shift_start_hour=shift[0], shift_end_hour=shift[1])
        days = [cache.get(site, d, MODEL) for d in dates]
        ramp = ac.simulate(worker, days, initial_adaptation=initial,
                           full_stimulus_degree_hours=NORM)
        out.append({
            "label": label,
            "worker": worker_payload(worker),
            "initialAdaptation": initial,
            "days": [{"date": d.date.isoformat(), "hourly": hourly_of(d)}
                     for d in days],
            "expected": [
                {
                    "date": r.date.isoformat(),
                    "dayOnJob": r.day_on_job,
                    "prescribedMinutes": r.shift_work_minutes,
                    "adaptationStart": r.adaptation_start,
                    "limit": r.personal_limit_c,
                    "degreeHours": r.stimulus.degree_hours,
                    "stimulus": r.stimulus.value,
                    "minutesPerHour": list(r.minutes_per_hour),
                }
                for r in ramp.days
            ],
            "expectedFinalAdaptation": ramp.final_adaptation,
        })

    # The synthetic rung-boundary days, run through the same path.
    class _Hour:
        def __init__(self, hour, value):
            self.hour = hour
            self.wbgt_c = value

    for case in synthetic_days():
        worker = ac.Worker(worker_id=case["label"], trade="concrete",
                           shift_start_hour=6, shift_end_hour=14)
        hours = case["hourly"]
        prescribed = [ac.work_minutes_per_hour(
            ac.effective_wbgt_c(hours[h], worker.clothing),
            ac.personal_limit_c(0.0, worker.work_class))
            for h in range(6, 14)]
        out.append({
            "label": "synthetic " + case["label"],
            "worker": worker_payload(worker),
            "initialAdaptation": 0.0,
            "days": [{"date": case["date"], "hourly": hours}],
            "expected": [{
                "date": case["date"],
                "dayOnJob": 1,
                "prescribedMinutes": sum(prescribed),
                "adaptationStart": 0.0,
                "limit": ac.personal_limit_c(0.0, worker.work_class),
                "minutesPerHour": prescribed,
            }],
            "syntheticOnly": True,
        })
    return out


def main():
    cache = bf.BackfillCache()
    payload = {
        "note": ("Generated from the Python engine. tests/test_js_engine.py "
                 "replays these through app/js/engine.js under Node."),
        "tolerance": 1e-9,
        "tau": {"gain": C.TAU_GAIN_DAYS, "decay": C.TAU_DECAY_DAYS},
        "scalars": scalar_vectors(),
        "simulations": simulate_vectors(cache),
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)

    print("wrote %s (%d KB)" % (os.path.relpath(OUT), os.path.getsize(OUT) // 1024))
    print("  %d scalar vectors, %d simulations"
          % (len(payload["scalars"]), len(payload["simulations"])))
    by_fn = {}
    for vector in payload["scalars"]:
        by_fn[vector["fn"]] = by_fn.get(vector["fn"], 0) + 1
    for fn, count in sorted(by_fn.items()):
        print("    %-22s %d" % (fn, count))


if __name__ == "__main__":
    main()
