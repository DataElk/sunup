"""M1 evidence report — run this to see why the pipeline should be believed.

    python scripts/m1_report.py

Prints the exit-test result, the hourly WBGT it came from, the provenance of
every input, what changed when each assumed input was replaced by a measured
one, and the discrepancies M1 is required to record rather than resolve.

Makes no network calls. Reads only fixtures/.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from acclimate import constants as C  # noqa: E402
from acclimate import reference, wbgt  # noqa: E402
from acclimate.physics import diurnal  # noqa: E402

RULE = "=" * 78
THIN = "-" * 78
S = wbgt.SourceSelection


def heading(text):
    print("\n" + RULE)
    print(text)
    print(RULE)


def verdict(day):
    worst = max(
        abs(day.at(h).wbgt_c - t) for h, t in C.WBGT_REFERENCE_HOURS_C.items()
    )
    return worst, worst <= C.WBGT_REFERENCE_TOLERANCE_C


def main():
    case = reference.M1_REFERENCE
    grid, env = reference.load_inputs()
    day = reference.build()
    kw = dict(
        site_id=case.site_id, grid=grid, env=env,
        site_longitude=case.longitude, site_latitude=case.latitude,
    )

    heading("M1 - WBGT PIPELINE")
    print("case      %s, %s" % (case.site_id, case.date))
    print("site      %.4f, %.4f  (elevation %.0f m, UTC%+.0f)"
          % (case.latitude, case.longitude, day.elevation_m, env.utc_offset_hours))
    print("fixtures  %s" % case.heatmap_filter3_fixture)
    print("          %s" % case.env_params_fixture)
    print("          openmeteo/%.4f_%.4f_%s.json"
          % (case.latitude, case.longitude, case.date))
    print("          %s  (cross-check only)" % case.heatmap_snapshot_fixture)

    # ------------------------------------------------------------------ exit
    heading("EXIT TEST  (SPEC.md, M1)")
    print("Reproduce constants.py section 5 within +/-%.1f degC.\n"
          % C.WBGT_REFERENCE_TOLERANCE_C)
    print("  hour   reference   computed   error")
    for hour in sorted(C.WBGT_REFERENCE_HOURS_C):
        target = C.WBGT_REFERENCE_HOURS_C[hour]
        got = day.at(hour).wbgt_c
        print("  %02d:00     %5.1f      %6.2f   %+6.3f  %s"
              % (hour, target, got, got - target,
                 "PASS" if abs(got - target) <= C.WBGT_REFERENCE_TOLERANCE_C else "FAIL"))

    ral = C.WBGT_LIMIT_UNACCLIMATIZED[C.WorkClass.MODERATE]
    rel = C.WBGT_LIMIT_ACCLIMATIZED[C.WorkClass.MODERATE]
    worst, ok = verdict(day)
    print("\n  day spans %.2f -> %.2f degC-WBGT" % (min(day.series_c), max(day.series_c)))
    print("  crosses NIOSH RAL (moderate, unacclimatized) %.1f : %s"
          % (ral, "YES" if day.crosses(ral) else "NO"))
    print("  crosses NIOSH REL (moderate, acclimatized)   %.1f : %s"
          % (rel, "YES" if day.crosses(rel) else "NO"))
    print("\n  VERDICT: %s   (worst error %+.3f degC)"
          % ("PASS" if ok and day.crosses(ral) and day.crosses(rel) else "FAIL", worst))

    # --------------------------------------------------------- decomposition
    heading("WHAT EACH INPUT IS WORTH  -  measured vs assumed, one at a time")
    print("An Open-Meteo fixture was fetched 2026-08-24. Swapping four inputs at")
    print("once would hide which one mattered, so they go in separately.\n")
    print("  %-44s %-13s %-13s worst" % ("configuration", "06:00 (24.8)", "14:00 (31.0)"))
    print("  " + THIN)
    configs = [
        ("A  all offline assumptions", dict(use=S.none())),
        ("B  + measured wind only", dict(use=S.wind_only())),
        ("C  + all Open-Meteo (default)", dict(use=S())),
        ("D  C + ISO 7243 Annex D natural wet bulb",
         dict(use=S(), natural_wet_bulb_model=wbgt.NWB_ISO_ANNEX_D)),
        ("E  A + ISO Annex D", dict(use=S.none(),
                                    natural_wet_bulb_model=wbgt.NWB_ISO_ANNEX_D)),
    ]
    for label, opts in configs:
        d = reference.build(**opts)
        w, passed = verdict(d)
        print("  %-44s %5.2f %+5.2f  %5.2f %+5.2f  %5.2f %s"
              % (label,
                 d.at(6).wbgt_c, d.at(6).wbgt_c - C.WBGT_REFERENCE_HOURS_C[6],
                 d.at(14).wbgt_c, d.at(14).wbgt_c - C.WBGT_REFERENCE_HOURS_C[14],
                 w, "PASS" if passed else "FAIL"))
    print("\n  A -> B: the assumed 3.0 m/s was close to the measured 2.81 m/s mean,")
    print("          so measured wind moves 14:00 by only 0.07 degC. The offline")
    print("          result was sound, not lucky.")
    print("  B -> C: real hourly shape, solar and cloud cut the worst error from")
    print("          0.44 to 0.09 degC. This is now the default.")
    print("  C -> D: see the NATURAL WET BULB section below. This one is a")
    print("          decision, not a bug.")

    # ------------------------------------------------------------ provenance
    heading("PROVENANCE  -  where each input came from")
    for label, value in day.provenance.as_rows():
        print("  %-18s %s" % (label, value))
    if day.provenance.assumed_inputs:
        print("\n  ASSUMED, not retrieved:")
        for item in day.provenance.assumed_inputs:
            print("    - %s" % item)
    else:
        print("\n  Nothing assumed.")

    # ----------------------------------------------------------------- hours
    heading("HOURLY WBGT")
    print("  hr   WBGT   Tdry   Tnwb  Tglobe   dTg     GHI    DNI    DHI  elev cloud   RH  wind")
    print("  " + THIN)
    for h in day.hours:
        marker = " <" if h.hour in C.WBGT_REFERENCE_HOURS_C else "  "
        print("  %02d  %5.2f  %5.2f  %5.2f  %6.2f %+5.2f  %6.1f %6.1f %6.1f %5.1f %5.2f %4.1f %5.2f%s"
              % (h.hour, h.wbgt_c, h.dry_bulb_c, h.natural_wet_bulb_c, h.globe_c,
                 h.globe_excess_over_air_c, h.ghi_w_m2, h.dni_w_m2, h.dhi_w_m2,
                 h.solar_elevation_deg, h.cloud_fraction, h.relative_humidity_pct,
                 h.wind_speed_m_s, marker))
    shift = day.window(C.DEMO_SHIFT_START_HOUR, C.DEMO_SHIFT_END_HOUR)
    print("\n  demo shift %02d:00-%02d:00 : peak %.2f, degree-hours above RAL %.2f"
          % (C.DEMO_SHIFT_START_HOUR, C.DEMO_SHIFT_END_HOUR,
             max(h.wbgt_c for h in shift),
             day.degree_hours_above(ral, C.DEMO_SHIFT_START_HOUR, C.DEMO_SHIFT_END_HOUR)))

    # -------------------------------------------------------- reconstruction
    r = day.reconstruction
    heading("DRY BULB RECONSTRUCTION")
    print("  shape source     %s" % r.shape_source)
    print("  warp gamma       %.4f  (converged=%s, plausible band %s)"
          % (r.warp_gamma, r.warp_converged, str(C.DIURNAL_WARP_GAMMA_PLAUSIBLE)))
    print("  FortyGuard says  min %.4f   mean %.4f   max %.4f"
          % (r.target_min_c, r.target_mean_c, r.target_max_c))
    print("  reconstructed    min %.4f   mean %.4f   max %.4f"
          % (r.achieved_min_c, r.achieved_mean_c, r.achieved_max_c))
    print("  mean residual    %+.6f degC   (all three numbers preserved)"
          % r.mean_residual_c)

    offline = reference.build(use=S.none())
    print("\n  overnight cooling limb (real dry bulb falls monotonically):")
    for label, d in (("FortyGuard apparent temp", offline), ("Open-Meteo temp_2m", day)):
        rev, warm = diurnal.night_limb_reversals(
            d.reconstruction.dry_bulb_c, d.solar_day.sunset_local,
            d.solar_day.sunrise_local)
        print("    %-26s %d hour(s) warming, %.2f degC total" % (label, rev, warm))
    print("    FortyGuard apparent temperature carries humidity, which peaks")
    print("    overnight and puts a false warm bump on the cooling limb.")
    print("    Open-Meteo temperature_2m removes most of it.")

    check = reference.snapshot_cross_check(day)
    print("\n  INDEPENDENT CHECK - filter_type=1 snapshot at %02d:00, a separate call"
          % check["hour"])
    print("    reconstructed  %.4f degC" % check["reconstructed_dry_bulb_c"])
    print("    snapshot cell  %.4f degC" % check["snapshot_cell_c"])
    print("    residual       %+.4f degC" % check["residual_c"])

    # ----------------------------------------------------- amplitude (CLAUDE)
    heading("AMPLITUDE COMPARISON  (required by CLAUDE.md's data strategy)")
    a = day.amplitude_check
    print("  FortyGuard cell amplitude      %.3f degC" % a.fortyguard_amplitude_c)
    print("  %-30s %.3f degC" % (a.reference_source, a.reference_amplitude_c))
    print("  discrepancy                    %+.3f degC   (ratio %.4f)"
          % (a.discrepancy_c, a.ratio))
    print("  independent: %s" % a.is_independent)
    print("\n  FortyGuard reads about 94% of Open-Meteo's diurnal amplitude on this")
    print("  2024 archive day. That is mild — far milder than the ~40% narrowing")
    print("  fixtures/MANIFEST.md records for 2026 dates. A compressed amplitude")
    print("  under-estimates peak WBGT, hence stimulus, hence adaptation rate:")
    print("  conservative, but a bias, and it is WORSE on the demo window than here.")

    # ------------------------------------------------------------- solar
    s = day.solar_day
    heading("SOLAR")
    print("  sunrise %05.2f  solar noon %05.2f  sunset %05.2f (local, geometric)"
          % (s.sunrise_local, 0.5 * (s.sunrise_local + s.sunset_local), s.sunset_local))
    off = offline.solar_day
    print("\n  With Open-Meteo the hourly shortwave is measured. The offline path")
    print("  anchors a modelled clear-sky curve to FortyGuard's daily mean:")
    print("    FortyGuard clear-sky GHI       %.2f W/m2" % off.anchor_ghi_w_m2)
    print("    modelled daylight-hours mean   %.2f W/m2" % off.model_daylight_mean_ghi)
    print("    modelled 24-hour mean          %.2f W/m2" % off.model_24h_mean_ghi)
    print("    -> the FortyGuard figure is a DAYLIGHT mean, not a 24-hour mean")
    print("       (now recorded in FORTYGUARD_API_CONTRACT.md section 6, trap 5)")
    print("    anchor scale applied           %.4f" % off.anchor_scale)
    peak_model = max(off.ghi_w_m2)
    peak_measured = max(day.hours[h].ghi_w_m2 for h in range(24))
    print("\n  Anchored model peak %.0f W/m2 vs Open-Meteo measured peak %.0f W/m2"
          % (peak_model, peak_measured))
    print("  -> the offline anchoring lands within %.0f W/m2 of the measurement."
          % abs(peak_model - peak_measured))

    # ------------------------------------------------------- natural wet bulb
    heading("NATURAL WET BULB  -  the one open decision in M1")
    print("  ISO 7243:2017 Annex B.1, verbatim:")
    print('    "The natural wet bulb temperature is thus different from the')
    print('     thermo-dynamic temperature determined with a psychrometer."')
    print("\n  FortyGuard returns the psychrometric value. WBGT is defined on the")
    print("  natural one. ISO Annex D gives a method to convert; it is implemented")
    print("  and reproduces all 22 rows of ISO Table D.1 to within 0.50 degC")
    print("  (tests/test_natural_wet_bulb.py).\n")
    iso = reference.build(use=S(), natural_wet_bulb_model=wbgt.NWB_ISO_ANNEX_D)
    print("  hour  psychrometric   ISO Annex D   difference   t_r     wind")
    for h in (6, 10, 14, 18):
        hr = iso.at(h)
        print("  %02d:00     %6.2f        %6.2f       %+5.2f    %6.2f  %.2f"
              % (h, hr.psychrometric_wet_bulb_c, hr.natural_wet_bulb_c,
                 hr.natural_wet_bulb_c - hr.psychrometric_wet_bulb_c,
                 hr.mean_radiant_c, hr.wind_speed_m_s))
    w_iso, _ = verdict(iso)
    print("\n  Effect on the exit test: 14:00 goes %.2f -> %.2f degC (reference %.1f)."
          % (day.at(14).wbgt_c, iso.at(14).wbgt_c, C.WBGT_REFERENCE_HOURS_C[14]))
    print("  Worst error %.2f degC, so Annex D FAILS the +/-1 degC gate." % w_iso)
    print("\n  WHY IT IS NOT THE DEFAULT, and why that is not settled:")
    print("    - Annex D's own preamble says the calculation 'is neither simple")
    print("      nor reliable ... It is not recommended'.")
    print("    - Table D.1 tabulates air velocity only to %.1f m/s. Phoenix at"
          % C.ISO_TABLE_D1_MAX_SPEED_M_S)
    print("      14:00 runs %.2f m/s, so most hours are outside ISO's own domain."
          % iso.at(14).wind_speed_m_s)
    print("    - But the psychrometric simplification under-reads WBGT, and")
    print("      under-reading heat stress is the UNSAFE direction.")
    print("    - Either the section 5 reference itself embeds the simplification,")
    print("      or Annex D over-predicts here. This needs the project owner.")

    # ----------------------------------------------------------- sensitivity
    heading("SENSITIVITY")
    print("  WIND  (measured now, but M3 will backfill days with no coverage)")
    print("    v m/s   06:00   14:00   err@14   gate")
    lo, hi = C.WIND_BAND_REPRODUCING_REFERENCE_M_S
    for v in (0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0):
        d = wbgt.build_wbgt_day(wind_speed_m_s=v, **kw)
        err = d.at(14).wbgt_c - C.WBGT_REFERENCE_HOURS_C[14]
        print("    %5.1f  %6.2f  %6.2f  %+6.3f   %s%s"
              % (v, d.at(6).wbgt_c, d.at(14).wbgt_c, err,
                 "ok " if abs(err) <= C.WBGT_REFERENCE_TOLERANCE_C else "OUT",
                 "   <- offline default" if v == C.DEFAULT_WIND_SPEED_M_S else ""))
    print("    Offline reference reproduces over [%.1f, %.1f] m/s. Below that the"
          % (lo, hi))
    print("    modelled globe over-heats. Errs toward restricting work — safe.")

    print("\n  GROUND ALBEDO  (constants.py 5a, still [CHECK])")
    for a_val in (0.10, 0.20, 0.30):
        d = wbgt.build_wbgt_day(ground_albedo=a_val, **kw)
        print("    %.2f -> 14:00 %.3f degC%s"
              % (a_val, d.at(14).wbgt_c, "   <- assumed" if a_val == C.GROUND_ALBEDO else ""))
    print("    0.18 degC per 0.05 of albedo. Not a decisive term.")

    # ------------------------------------------------------ constants status
    heading("CONSTANTS VERIFICATION  (this pass, 2026-08-24)")
    print("  RESOLVED TO [VERIFIED] against a primary document:")
    for item, extra in (
        ("WBGT weights .......... ISO 7243:2017 Clause 5, Formulae (1) and (2)", None),
        ("globe diameter 150 mm . ISO 7243:2017 Annex B.2 a)", None),
        ("globe emissivity 0,95 . ISO 7243:2017 Annex B.2 b)",
         "a secondary source said 0,97 and was wrong"),
        ("natural wet bulb ...... ISO 7243:2017 Annex D, Formulae (D.1)/(D.2)",
         "validated against all 22 rows of Table D.1"),
        ("Nusselt correlation ... Liljegren's wbgt.c, citing BSL p.409", None),
        ("Haurwitz 1098 / 0.059 . pvlib reference impl. + Haurwitz 1945", None),
        ("Kasten-Czeplak ........ Solar Energy 24(2):177-189, 1980", None),
        ("Brutsaert 1.24, 1/7 ... Water Resources Research 11(5):742-744, 1975", None),
        ("Tetens 0.6108 ......... Tetens 1930, via FAO-56 Equation 11", None),
        ("NOAA solar equations .. NOAA GML solareqns, coefficient for coefficient", None),
        ("Stefan-Boltzmann ...... CODATA, exact since the 2019 SI redefinition", None),
    ):
        print("    [x] %s" % item)
        if extra:
            print("        %s" % extra)
    print("\n  STILL [CHECK] - could not be confirmed against a primary source:")
    for item, extra in (
        ("globe SHORTWAVE absorptivity",
         "ISO gives only the longwave emission coefficient. We set\n"
         "        absorptivity = emissivity, as Liljegren does."),
        ("ground emissivity 0.95 and ground albedo 0.20",
         "no primary source; albedo sensitivity measured above, and small."),
        ("air properties (Sutherland, Prandtl, conductivity, ISA pressure)", None),
        ("surface roughness length 0.1 m (10 m -> 2 m wind profile)", None),
        ("Meinel & Meinel 1976",
         "confirmed via secondary sources only; the 1976 book was not\n"
         "        opened. Least consequential of the set."),
        ("solar constant 1367 vs the modern 1361 (Kopp & Lean 2011)", None),
    ):
        print("    [ ] %s" % item)
        if extra:
            print("        %s" % extra)
    print("\n  NOT PART OF M1, still [CHECK]: sections 1-4 and 6 (ISO 8996 metabolic")
    print("  rates, NIOSH REL/RAL, work/rest ladder, ACGIH clothing, OSHA copy).")

    if day.notes:
        print("\n  PIPELINE NOTES")
        for note in day.notes:
            print("    - %s" % note)


if __name__ == "__main__":
    main()
