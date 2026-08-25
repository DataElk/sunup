"""Which [CHECK]-tagged constants actually change what a worker is told to do?

    python scripts/audit_constants.py

WHY THIS EXISTS
---------------
constants.py carries about thirty [CHECK] tags -- values taken from a standard
we have not opened directly. Verifying all of them against primary sources is
not possible before submission: ISO 8996 and the ACGIH TLV booklet are both
paywalled, and NIOSH publishes its limits as figures rather than tables.

Grinding through them in citation order would be the wrong response anyway. The
useful question is not "how many did we verify" but "which ones can move a
prescription". A constant that cannot change a single worker's minutes is not a
risk to a safety product no matter how thinly it is sourced; a constant that
moves the answer needs either a source or a stated caveat.

So this MEASURES it. Each constant is perturbed by a plausible amount -- the
alternative value a different source would give, or a range wide enough to
bracket the disagreement -- and the whole demo crew is re-prescribed from raw
tiles. What is reported is the largest change in prescribed minutes across the
crew, which is the number a foreman would actually see.

READ THE RESULT AS A TRIAGE, NOT A VALIDATION. A zero here means "cannot affect
the demo", not "correct". Several constants are zero only because the demo never
exercises them -- every worker wears `work_clothes`, so the other clothing
adjustments are unreachable. That is worth knowing and worth saying, but it is
not the same as having checked them.

NOT COVERED HERE. WORK_REST_LADDER is the largest unvalidated assumption and has
its own audit: scripts/audit_ladder.py. The exposure limits themselves are
verified in constants.py section 2 against NIOSH 2016-106 Figures 8-1/8-2.
"""

from __future__ import annotations

import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, HERE)

from acclimate import acclimatization as ac  # noqa: E402
from acclimate import backfill as bf  # noqa: E402
from acclimate import constants as C  # noqa: E402
from acclimate import wbgt  # noqa: E402

MODEL = wbgt.NWB_PSYCHROMETRIC
NORM = C.DEGREE_HOURS_FULL_STIMULUS

# The demo crew's trades, shifts, day counts and sites. Reconstructed here
# rather than imported, so this audit does not depend on app/data being
# built. Absolute minutes may differ slightly from the rendered roster;
# what is measured is the DIFFERENCE a perturbation makes, which does not.
CREW = [
    ("A. Reyes", "concrete", (5, 13), 5, "hot_site"),
    ("B. Osei", "concrete", (10, 18), 5, "hot_site"),
    ("C. Duarte", "rebar", (5, 13), 2, "hot_site"),
    ("D. Whitfield", "electrical", (5, 13), 1, "cool_site"),
    ("E. Nakamura", "carpentry", (5, 13), 7, "cool_site"),
    ("F. Okoro", "roofing", (5, 13), 14, "hot_site"),
]

# (constant, alternative value, why this alternative)
PERTURBATIONS = [
    ("GLOBE_SOLAR_ABSORPTIVITY", 0.90,
     "ISO gives only the longwave coefficient; shortwave is our step"),
    ("GLOBE_SOLAR_ABSORPTIVITY", 1.00, "upper bound for matte black"),
    ("GROUND_EMISSIVITY", 0.90, "no primary source opened"),
    ("GROUND_ALBEDO", 0.10, "dark asphalt end of the urban range"),
    ("GROUND_ALBEDO", 0.30, "light concrete end of the urban range"),
    ("SOLAR_CONSTANT_W_M2", 1361.0, "Kopp & Lean 2011 vs the 1367 we keep"),
    ("AIR_PRANDTL", 0.70, "weakly temperature-dependent"),
    ("AIR_GAS_CONSTANT_J_KG_K", 287.0, "rounding between references"),
    ("AIR_CONDUCTIVITY_REF_W_M_K", 0.02676, "+2%, spread between tabulations"),
    ("AIR_CONDUCTIVITY_EXPONENT", 0.8819, "+2%"),
    ("AIR_SUTHERLAND_MU0_PA_S", None, "+2%"),
    ("ISA_SEA_LEVEL_PRESSURE_PA", None, "+1%"),
    ("SURFACE_ROUGHNESS_LENGTH_M", 0.03, "open suburban rather than built-up"),
    ("SURFACE_ROUGHNESS_LENGTH_M", 0.30, "dense urban rather than built-up"),
    ("BODY_SURFACE_AREA_M2", 2.0, "a different reference body"),
]


def prescribe(cache, dates):
    """Today's prescribed minutes and personal limit for the whole crew."""
    out = {}
    for name, trade, shift, days, site in CREW:
        worker = ac.Worker(worker_id=name, trade=trade,
                           shift_start_hour=shift[0], shift_end_hour=shift[1])
        history = dates[-days:] if days <= len(dates) else dates
        ramp = ac.simulate(worker, [cache.get(site, d, MODEL) for d in history],
                           full_stimulus_degree_hours=NORM)
        record = ramp.days[-1]
        out[name] = (record.shift_work_minutes, record.personal_limit_c,
                     record.peak_effective_wbgt_c)
    return out


def run(cache, dates):
    cache._built.clear()
    return prescribe(cache, dates)


def main():
    cache = bf.BackfillCache()
    dates = cache.shared_dates(MODEL)

    print(__doc__.split("WHY THIS EXISTS")[0].strip())
    print()
    print("  Crew of %d, %s, model %s." % (len(CREW), dates[-1], MODEL))

    base = run(cache, dates)
    print("  Baseline minutes: %s"
          % ", ".join("%s %d" % (n.split(".")[-1].strip(), v[0])
                      for n, v in base.items()))
    print()
    print("  %-30s %10s %10s %8s  %s"
          % ("constant", "value", "->", "max dmin", "alternative because"))
    print("  " + "-" * 104)

    for name, alt, why in PERTURBATIONS:
        original = getattr(C, name)
        value = alt if alt is not None else original * (
            1.02 if "2%" in why else 1.01)
        setattr(C, name, value)
        try:
            moved = run(cache, dates)
        finally:
            setattr(C, name, original)
            cache._built.clear()

        dmin = max(abs(moved[n][0] - base[n][0]) for n in base)
        dlimit = max(abs(moved[n][1] - base[n][1]) for n in base)
        dwbgt = max(abs(moved[n][2] - base[n][2]) for n in base)
        flag = "" if dmin else "   (no effect on any worker)"
        print("  %-30s %10.5g %10.5g %8d  %s%s"
              % (name, original, value, dmin, why, flag))
        if dmin or dwbgt >= 0.01:
            print("  %-30s %32s dWBGT %.2f degC, dlimit %.2f degC"
                  % ("", "", dwbgt, dlimit))

    # Clothing is unreachable in the demo by construction, not by luck.
    worn = {w.clothing for w in
            [ac.Worker(worker_id=n, trade=t) for n, t, _, _, _ in CREW]}
    print("\n  CLOTHING_ADJUSTMENT_C: every demo worker wears %s (adjustment "
          "%+.1f degC)." % (", ".join(sorted(worn)), C.CLOTHING_ADJUSTMENT_C["work_clothes"]))
    print("  The other %d entries are unreachable from this demo, so their [CHECK]"
          % (len(C.CLOTHING_ADJUSTMENT_C) - 1))
    print("  tags cannot be closed by measurement here. They are flagged, not verified.")

    print("""
  HOW TO USE THIS

  Non-zero max dmin  -> load-bearing. Needs a source, or a caveat naming the
                        range over which the prescription moves.
  Zero max dmin      -> cannot change this demo's output. Still tagged [CHECK],
                        because "unreachable in one demo" is not "correct".

  The two constants that decide stop-work are handled elsewhere and are not in
  this table: the exposure limits (verified, constants.py section 2) and the
  work/rest ladder (our construction, sensitivity-tested in audit_ladder.py).
""")


if __name__ == "__main__":
    main()
