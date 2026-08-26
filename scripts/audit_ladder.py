"""Does the headline result survive perturbing the work/rest ladder?

    python scripts/audit_ladder.py

WHY THIS EXISTS
---------------
WORK_REST_LADDER is the model's largest unvalidated assumption. constants.py
section 2 records why: NIOSH 2016-106 publishes no work/rest lookup table, the
familiar 75/25 - 50/50 - 25/75 screening table is ACGIH's and is copyrighted,
and in any case ours reads against a PERSONAL limit rather than a fixed
category, so no published table could have supplied it. It is our construction.

It is also the single thing that decides whether a worker is told to stop. An
unvalidated assumption in that position has to be sensitivity-tested rather than
merely disclosed, exactly as TAU_GAIN and TAU_DECAY were.

The question is not whether the ladder is "right". There is no reference to be
right against. It is whether the PRODUCT'S CLAIM depends on it. Shift timing is
the headline: two workers, same site, same trade, same day count, differing only
in start time. If the separation survives every plausible ladder, the claim
rests on the physics and the schedule, not on four numbers we chose.

WHICH DATA
----------
The 14-day backfill (M3), not the four tile-anchored fixture days (M2). The
headline is an M3 claim and the two bases give very different magnitudes, see
the note printed at the end. Both arms take the SAME 14 site-days at the SAME
site; the only difference between the two workers is the assigned shift.

VARIANTS TESTED
---------------
  baseline     60/45/30/15 at 0.0 / 1.0 / 2.0 / 3.0 degC above the personal limit
  tighter      every boundary moved DOWN 0.5 degC  (stops work sooner)
  looser       every boundary moved UP 0.5 degC    (stops work later)
  three-rung   60/30/15 at 0.0 / 1.5 / 3.0
  five-rung    60/48/36/24/12 at 0.0 / 0.75 / 1.5 / 2.25 / 3.0
  coarse-two   60/30 at 0.0 / 2.0, deliberately crude
  steep        60/30/10 at 0.0 / 0.5 / 1.5, deliberately aggressive
  linear       no rungs at all: minutes fall continuously with excess
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from acclimate import acclimatization as ac  # noqa: E402
from acclimate import backfill as bf  # noqa: E402
from acclimate import constants as C  # noqa: E402
from acclimate import wbgt  # noqa: E402

NORM = C.DEGREE_HOURS_FULL_STIMULUS
MODELS = (wbgt.NWB_PSYCHROMETRIC, wbgt.NWB_ISO_ANNEX_D)
LABEL = {wbgt.NWB_PSYCHROMETRIC: "psychrometric", wbgt.NWB_ISO_ANNEX_D: "ISO Annex D"}
EARLY = (5, 13)
SITE = "hot_site"

LADDERS = {
    "baseline":   [(0.0, 60), (1.0, 45), (2.0, 30), (3.0, 15)],
    "tighter":    [(-0.5, 60), (0.5, 45), (1.5, 30), (2.5, 15)],
    "looser":     [(0.5, 60), (1.5, 45), (2.5, 30), (3.5, 15)],
    "three-rung": [(0.0, 60), (1.5, 30), (3.0, 15)],
    "five-rung":  [(0.0, 60), (0.75, 48), (1.5, 36), (2.25, 24), (3.0, 12)],
    "coarse-two": [(0.0, 60), (2.0, 30)],
    "steep":      [(0.0, 60), (0.5, 30), (1.5, 10)],
    # Not a rung structure at all: 60 min at the limit falling linearly to zero
    # 4 degC above it, quantised to the nearest minute. If the claim survives
    # this it does not depend on there being rungs.
    "linear":     [(i * 0.25, max(0, round(60 * (1 - i * 0.25 / 4.0))))
                   for i in range(17)],
}


def ramp(cache, shift, model, tau, dates):
    worker = ac.Worker(worker_id="w", trade="concrete",
                       shift_start_hour=shift[0], shift_end_hour=shift[1])
    return ac.simulate(worker, [cache.get(SITE, d, model) for d in dates],
                       tau=tau, full_stimulus_degree_hours=NORM)


def evaluate(cache, model, late_shift, sweep, dates, day):
    """Gap and tau survival AT A GIVEN DAY ON JOB.

    The day matters and SPEC.md's headline did not say which one it used. The
    separation grows monotonically: on the 14-day backfill it is +1.07 degC at
    day 4 and +2.75 degC at day 14 (psychrometric, 05:00 vs 10:00). Quoting one
    number without the day makes a growing effect look like a fixed one.
    """
    gaps = []
    for tau in sweep:
        early = ramp(cache, EARLY, model, tau, dates)
        late = ramp(cache, late_shift, model, tau, dates)
        gaps.append(ac.compare("shift", early, late, day).limit_gap_c)
    early = ramp(cache, EARLY, model, ac.Tau(), dates)
    late = ramp(cache, late_shift, model, ac.Tau(), dates)
    base = ac.compare("shift", early, late, day)
    material = sum(1 for g in gaps if abs(g) >= C.MATERIAL_LIMIT_GAP_C)
    signed = sum(1 for g in gaps if g > 0)
    return base, material, signed, len(sweep), min(gaps), max(gaps)


def main():
    cache = bf.BackfillCache()
    sweep = ac.default_tau_sweep()
    original = C.WORK_REST_LADDER

    print(__doc__.split("WHY THIS EXISTS")[0].strip())
    print()
    print("  Materiality threshold: |gap| >= %.2f degC (constants.py)"
          % C.MATERIAL_LIMIT_GAP_C)
    print("  Tau sweep: %d pairs, gain %s, decay %s"
          % (len(sweep), C.TAU_GAIN_SENSITIVITY_RANGE, C.TAU_DECAY_SENSITIVITY_RANGE))
    print("  Basis: 14-day backfill, %s, both arms on identical site-days." % SITE)

    survived = []
    for day_label, day in (("day 4, SPEC.md's headline day", 4),
                           ("day 14, end of the backfill", 14)):
        for late_shift in ((8, 16), (10, 18)):
            print("\n  ===== 05:00-13:00 vs %02d:00-%02d:00, %s ====="
                  % (late_shift[0], late_shift[1], day_label))
            print("  %-11s %-14s %10s %10s %9s %s"
                  % ("ladder", "wet bulb", "base gap", "material", "signed", "range"))
            print("  " + "-" * 76)
            for name, ladder in LADDERS.items():
                for model in MODELS:
                    dates = cache.shared_dates(model)
                    C.WORK_REST_LADDER = ladder
                    try:
                        base, material, signed, total, lo, hi = evaluate(
                            cache, model, late_shift, sweep, dates, day)
                    finally:
                        C.WORK_REST_LADDER = original
                    ok = material == total and signed == total
                    survived.append((ok, signed == total))
                    print("  %-11s %-14s %+9.2f %7d/%-3d %6d/%-3d %+.2f..%+.2f%s"
                          % (name, LABEL[model], base.limit_gap_c, material, total,
                             signed, total, lo, hi,
                             "" if ok else "   <-- not material"))

    material_ok = sum(1 for ok, _ in survived if ok)
    sign_ok = sum(1 for _, s in survived if s)
    print("\n  VERDICT")
    print("    sign correct in all %d tau pairs:   %d of %d configurations"
          % (len(sweep), sign_ok, len(survived)))
    print("    ALSO material in all %d tau pairs:  %d of %d configurations"
          % (len(sweep), material_ok, len(survived)))
    print("""
  WHAT THIS ESTABLISHES

  The DIRECTION of the shift-timing result is completely insensitive to the
  ladder. Across every variant, two rungs, five rungs, boundaries moved half a
  degree either way, and a continuous no-rung response, the early-start worker
  ends up better adapted in every one of the tau pairs. The finding is not an
  artifact of the four numbers we chose.

  MATERIALITY is not fully insensitive, and that is the honest caveat. The
  variants that fall below the 0.5 degC threshold in some tau pairs are the
  deliberately aggressive "steep" ladder, work stops 1.5 degC above the limit,
  which compresses every worker toward zero and leaves little room to differ --
  and, at the weaker 08:00 comparison and early days only, "looser" and
  "linear".

  WHAT IT DOES NOT ESTABLISH

  It does not validate the ladder as a safety instrument. PRESCRIBED MINUTES
  move a great deal between these variants. That is what changing them does --
  and nothing here says which variant a regulator would accept. What survives is
  the COMPARATIVE claim: this worker is better adapted than that one, and shift
  timing is why. The absolute prescription is only as good as the ladder, and
  the ladder is ours.
""")


if __name__ == "__main__":
    main()
