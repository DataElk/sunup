"""M2 evidence report — the acclimatization engine and the two-worker divergence.

    python scripts/m2_report.py

Answers the three questions the exit test turns on:
  1. how large is the divergence, in prescribed minutes per hour
  2. does it survive BOTH wet-bulb methods
  3. does it survive the full tau sweep (gain 3-6, decay 10-21)

Makes no network calls. Reads only fixtures/.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from acclimate import acclimatization as ac  # noqa: E402
from acclimate import constants as C  # noqa: E402
from acclimate import scenarios, wbgt  # noqa: E402

RULE = "=" * 78
THIN = "-" * 78
MODELS = (wbgt.NWB_PSYCHROMETRIC, wbgt.NWB_ISO_ANNEX_D)
MODEL_LABEL = {wbgt.NWB_PSYCHROMETRIC: "psychrometric (default)",
               wbgt.NWB_ISO_ANNEX_D: "ISO 7243 Annex D"}


def heading(text):
    print("\n" + RULE)
    print(text)
    print(RULE)


def run(scenario, cache, model, tau, norm):
    mild, hot = scenarios.build_ramps(scenario, cache, model, tau, norm)
    return ac.compare(scenario.label, mild, hot, scenario.day_on_job)


def main():
    cache = scenarios.SiteDayCache()

    heading("M2 - ACCLIMATIZATION ENGINE")
    print("Site      %s  (%.4f, %.4f)"
          % (scenarios.SITE_ID, scenarios.LATITUDE, scenarios.LONGITUDE))
    print("Trade     concrete -> %s work" % C.TRADE_TO_WORK_CLASS["concrete"].value)
    print("Limits    RAL %.1f (unadapted)  ->  REL %.1f (adapted) degC-WBGT"
          % (C.WBGT_LIMIT_UNACCLIMATIZED[C.WorkClass.MODERATE],
             C.WBGT_LIMIT_ACCLIMATIZED[C.WorkClass.MODERATE]))
    print("tau       gain %.1f d, decay %.1f d (asymmetry %.1fx)"
          % (C.TAU_GAIN_DAYS, C.TAU_DECAY_DAYS, C.TAU_DECAY_DAYS / C.TAU_GAIN_DAYS))

    # ---------------------------------------------------------------- inputs
    heading("REAL SITE-DAYS AVAILABLE  (FortyGuard tiles + Open-Meteo hourly)")
    print("  date         WBGT peak   shift 05-13 peak   degree-hours above RAL")
    for site in cache.ranked_by_dose(wbgt.NWB_PSYCHROMETRIC):
        shift = site.day.window(*scenarios.EARLY_SHIFT)
        print("  %s     %6.2f            %6.2f              %6.2f"
              % (site.iso, site.day.peak.wbgt_c,
                 max(h.wbgt_c for h in shift), site.shift_degree_hours_above_ral))
    print("\n  Ranked by measured dose, mildest first. Only 4 site-days have cached")
    print("  FortyGuard tiles; the 14-day backfill is M3's job.")

    # ------------------------------------------------------------ saturation
    heading("THE STIMULUS TERM SATURATES  -  read this before anything else")
    print("s = degree-hours above the personal limit / DEGREE_HOURS_FULL_STIMULUS,")
    print("clipped at 1. With the specified normalisation of %.1f degC*h:\n"
          % C.DEGREE_HOURS_FULL_STIMULUS)
    worker = ac.Worker(worker_id="probe", trade="concrete")
    print("  date         deg-hrs   s @ A=0   s @ A=1")
    for site in cache.ranked_by_dose(wbgt.NWB_PSYCHROMETRIC):
        s0 = ac.daily_stimulus(site.day, worker, 0.0, C.DEGREE_HOURS_FULL_STIMULUS)
        s1 = ac.daily_stimulus(site.day, worker, 1.0, C.DEGREE_HOURS_FULL_STIMULUS)
        print("  %s     %6.2f    %.3f     %.3f" % (site.iso, s0.degree_hours,
                                                   s0.value, s1.value))
    print("\n  Every real Phoenix shift saturates. When s = 1 for everyone every")
    print("  day, the state update becomes A(t+1) = A + (1-A)/tau_gain, which is")
    print("  a function of DAYS ELAPSED alone -- the calendar the product exists")
    print("  to replace. Two workers with a 1.9x dose difference get identical")
    print("  numbers. See constants.py section 3 for the owner's decision needed.")
    print("\n  The report therefore runs everything at BOTH normalisations:")
    print("    %5.1f degC*h  as specified   [DEGREE_HOURS_FULL_STIMULUS]"
          % C.DEGREE_HOURS_FULL_STIMULUS)
    print("    %5.1f degC*h  proposed       [DEGREE_HOURS_ALT_STIMULUS]"
          % C.DEGREE_HOURS_ALT_STIMULUS)

    norms = ((C.DEGREE_HOURS_FULL_STIMULUS, "as specified"),
             (C.DEGREE_HOURS_ALT_STIMULUS, "proposed"))
    scenario_builders = (scenarios.shift_assignment_scenario,
                         scenarios.mild_vs_hot_days_scenario)

    # --------------------------------------------------- Q1 and Q2: divergence
    heading("Q1 + Q2  DIVERGENCE IN PRESCRIBED MINUTES PER HOUR, BOTH WET-BULB METHODS")
    default_tau = ac.Tau()
    for build in scenario_builders:
        scenario = build(cache, wbgt.NWB_PSYCHROMETRIC)
        print("\n%s" % scenario.label.upper())
        print("  %s" % scenario.rationale)
        print("  mild history: %s  shift %02d-%02d"
              % (", ".join(scenario.mild_dates), *scenario.mild_shift))
        print("  hot  history: %s  shift %02d-%02d"
              % (", ".join(scenario.hot_dates), *scenario.hot_shift))
        print("  compared on : %s, shift %02d-%02d (SHARED - same weather, same"
              % (scenario.comparison_date, *scenario.comparison_shift))
        print("                shift, so the only difference is what they carry in)")
        if scenario.caveat:
            print("  CAVEAT: %s" % scenario.caveat)
        print("\n  %-14s %-24s %8s %8s %9s %9s %8s"
              % ("normalisation", "wet bulb model", "A mild", "A hot",
                 "min/h mild", "min/h hot", "GAP"))
        print("  " + THIN)
        for norm, norm_label in norms:
            for model in MODELS:
                d = run(scenario, cache, model, default_tau, norm)
                m = d.mild.at_day(d.day_on_job)
                h = d.hot.at_day(d.day_on_job)
                print("  %-14s %-24s %7.3f %7.3f %8d %8d %+7d %6d %s"
                      % (norm_label, MODEL_LABEL[model],
                         m.adaptation_start, h.adaptation_start,
                         m.shift_work_minutes, h.shift_work_minutes,
                         d.max_minutes_per_hour_gap,
                         d.hours_with_different_prescription,
                         "MATERIAL" if d.is_material else "-"))
        d = run(scenario, cache, wbgt.NWB_PSYCHROMETRIC, default_tau,
                C.DEGREE_HOURS_ALT_STIMULUS)
        m, h = d.mild.at_day(d.day_on_job), d.hot.at_day(d.day_on_job)
        print("\n  At the proposed normalisation, day %d in full:" % d.day_on_job)
        print("    calendar (OSHA rule of 20%%) prescribes %d%% of a shift to BOTH"
              % d.calendar_pct)
        print("    mild worker: A=%.3f  limit %.2f degC  %d min over the shift (%.0f%%)"
              % (m.adaptation_start, m.personal_limit_c, m.shift_work_minutes, m.model_pct))
        print("      per hour: %s" % list(m.minutes_per_hour))
        print("    hot  worker: A=%.3f  limit %.2f degC  %d min over the shift (%.0f%%)"
              % (h.adaptation_start, h.personal_limit_c, h.shift_work_minutes, h.model_pct))
        print("      per hour: %s" % list(h.minutes_per_hour))
        print("      hourly gap: %s" % list(d.per_hour_gaps))
        print("    GAP: max %+d min/h in one hour, %d of %d hours differ,"
              % (d.max_minutes_per_hour_gap, d.hours_with_different_prescription,
                 len(d.per_hour_gaps)))
        print("         %+d min per shift, %.2f degC of personal limit"
              % (d.shift_minutes_gap, d.limit_gap_c))

    # ------------------------------------------------------------ Q3: tau sweep
    heading("Q3  DOES IT SURVIVE THE FULL TAU SWEEP?  gain 3-6, decay 10-21")
    sweep = ac.default_tau_sweep()
    print("%d (gain, decay) pairs; gain in 0.5 steps, decay in 1-day steps.\n"
          % len(sweep))
    print("  %-30s %-24s %13s %8s %15s"
          % ("scenario / normalisation", "wet bulb model",
             "max/h gap min..max", "material", "shift-min gap"))
    print("  " + THIN)
    verdicts = []
    for build in scenario_builders:
        scenario = build(cache, wbgt.NWB_PSYCHROMETRIC)
        for norm, norm_label in norms:
            for model in MODELS:
                gaps, shift_gaps, limit_gaps = [], [], []
                for tau in sweep:
                    d = run(scenario, cache, model, tau, norm)
                    gaps.append(d.max_minutes_per_hour_gap)
                    shift_gaps.append(d.shift_minutes_gap)
                    limit_gaps.append(d.limit_gap_c)
                gaps.sort(); shift_gaps.sort(); limit_gaps.sort()
                material = sum(
                    1 for g in gaps if abs(g) >= C.MATERIAL_DIVERGENCE_MIN_PER_HOUR)
                pct = 100.0 * material / len(gaps)
                verdicts.append((scenario.label, norm_label, model, gaps[0],
                                 gaps[-1], pct, shift_gaps[0], shift_gaps[-1],
                                 limit_gaps[0], limit_gaps[-1]))
                print("  %-30s %-24s %+6d ..%+5d %7.0f%% %+7d ..%+5d"
                      % (("%s/%s" % (scenario.label[:16], norm_label))[:30],
                         MODEL_LABEL[model], gaps[0], gaps[-1], pct,
                         shift_gaps[0], shift_gaps[-1]))

    print("\n  The last column is the SAME divergence measured continuously,")
    print("  in working minutes per shift, before the 15-minute ladder quantises it.")

    # ------------------------------------------------------------------ verdict
    heading("VERDICT")
    survives_all = [v for v in verdicts if v[5] == 100.0]
    survives_none = [v for v in verdicts if v[5] == 0.0]
    continuous_always = [v for v in verdicts if v[6] != 0 and v[7] != 0]
    print("Configurations where the divergence is material across ALL %d tau pairs: %d/%d"
          % (len(sweep), len(survives_all), len(verdicts)))
    for v in survives_all:
        print("   PASS  %s / %s / %s   gap %+d..%+d min/h"
              % (v[0], v[1], MODEL_LABEL[v[2]], v[3], v[4]))
    print("\nConfigurations with NO material divergence anywhere: %d/%d"
          % (len(survives_none), len(verdicts)))
    for v in survives_none:
        print("   FAIL  %s / %s / %s   gap %+d..%+d min/h"
              % (v[0], v[1], MODEL_LABEL[v[2]], v[3], v[4]))
    print("\nConfigurations where the CONTINUOUS divergence (shift minutes) is")
    print("non-zero across every tau pair: %d/%d" % (len(continuous_always), len(verdicts)))
    for v in continuous_always:
        print("        %s / %s / %s   %+d..%+d min per shift, limit gap %.2f..%.2f degC"
              % (v[0][:34], v[1], MODEL_LABEL[v[2]], v[6], v[7], v[8], v[9]))

    print("""
HOW TO READ THIS  -  M2 EXIT TEST: FAIL AS SPECIFIED

  1. AT THE SPECIFIED NORMALISATION (6.0 degC*h) THE DIVERGENCE IS ZERO.
     Zero for both wet-bulb methods, zero across all %d tau pairs, zero in both
     scenarios. s is pinned at 1, so the state model is a day-counter and two
     workers with a 1.9x measured dose difference receive identical schedules.
     The exit test does not fail marginally here; it fails completely.

  2. AT THE PROPOSED NORMALISATION (40 degC*h) IT PARTLY SURVIVES.
     One configuration of eight is material across the whole tau range. The
     others fade in and out depending on tau, because the NIOSH work/rest ladder
     is quantised in 15-minute rungs and the effect is roughly one rung wide.

  3. THE UNDERLYING DIVERGENCE IS MORE ROBUST THAN THE PRESCRIPTION IS.
     Adaptation separates cleanly and monotonically (0.392 vs 0.556 on the
     headline case, a personal-limit gap of 0.49 degC). What is fragile is
     whether that gap lands either side of a ladder boundary. Report the
     continuous numbers as the finding and the minutes as the consequence --
     not the other way round.

  WHAT M3 NEEDS TO SETTLE THIS
     - the stimulus normalisation decision (constants.py section 3)
     - a 14-day backfill, so the two histories can be disjoint instead of
       overlapping on 2 of 3 days
     - ideally a second SITE, so the 1.84x metro dose ratio drives the
       divergence rather than shift timing alone
""" % len(sweep))


if __name__ == "__main__":
    main()
