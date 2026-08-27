"""Emit the browser engine's constants FROM constants.py.

    python scripts/build_js_constants.py

constants.py is the single source of truth. Now that the per-worker maths runs
in the browser as well as in Python, the temptation is to keep a second copy of
the numbers in JavaScript, and a second copy of the NIOSH limits or the
work/rest ladder is exactly the kind of thing that drifts silently and then
decides whether a worker is told to stop.

So nothing here is typed by hand. Every value is read out of the Python module
and written to app/data/constants.js, which the engine imports. Changing a limit
means changing constants.py and re-running this; there is no other path.

The generated file carries a SOURCE HASH of the constants it was built from.
tests/test_js_engine.py recomputes that hash and fails if the generated file is
stale, so a constants.py edit that never reached the browser cannot ship.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from acclimate import constants as C  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                   "app", "data", "constants.js")


def payload() -> dict:
    """Exactly what the browser engine reads. Nothing else."""
    return {
        # Section 2: the exposure limits. [VERIFIED] against NIOSH 2016-106
        # Figures 8-1 and 8-2; see constants.py for the derivation table.
        "ralByClass": {k.value: v for k, v in C.WBGT_LIMIT_UNACCLIMATIZED.items()},
        "relByClass": {k.value: v for k, v in C.WBGT_LIMIT_ACCLIMATIZED.items()},

        # Section 2, OUR CONSTRUCTION, not a standard. Sensitivity-tested in
        # scripts/audit_ladder.py.
        "workRestLadder": [[float(x), int(m)] for x, m in C.WORK_REST_LADDER],
        "workRestStop": int(C.WORK_REST_STOP),

        # Section 1: job assignment, not a personal attribute.
        "tradeToWorkClass": {k: v.value for k, v in C.TRADE_TO_WORK_CLASS.items()},
        "metabolicRateWm2": {k.value: v for k, v in C.METABOLIC_RATE_W_M2.items()},

        # ISO 7243 Clause 7 Formula (3).
        "clothingAdjustmentC": dict(C.CLOTHING_ADJUSTMENT_C),

        # Section 3: the state model.
        "tauGainDays": float(C.TAU_GAIN_DAYS),
        "tauDecayDays": float(C.TAU_DECAY_DAYS),
        "degreeHoursFullStimulus": float(C.DEGREE_HOURS_FULL_STIMULUS),
        "stimulusFloorDeg": float(C.STIMULUS_FLOOR_DEG),

        # The rule the product compares itself against.
        "calendarRampPctByDay": {str(k): v for k, v in C.CALENDAR_RAMP_PCT_BY_DAY.items()},

        "defaultShiftStartHour": int(C.DEMO_SHIFT_START_HOUR),
        "defaultShiftEndHour": int(C.DEMO_SHIFT_END_HOUR),

        # Section 5: the browser composes live site weather with the same
        # physical constants as the Python WBGT pipeline. Keeping them nested
        # makes it clear that these are environmental inputs, not worker-model
        # tuning parameters.
        "environment": {
            "wbgtOutdoorWeights": list(C.WBGT_OUTDOOR_WEIGHTS),
            "wbgtIndoorWeights": list(C.WBGT_INDOOR_WEIGHTS),
            "globeDiameterM": C.GLOBE_DIAMETER_M,
            "globeEmissivity": C.GLOBE_EMISSIVITY,
            "globeSolarAbsorptivity": C.GLOBE_SOLAR_ABSORPTIVITY,
            "groundEmissivity": C.GROUND_EMISSIVITY,
            "groundAlbedo": C.GROUND_ALBEDO,
            "stefanBoltzmann": C.STEFAN_BOLTZMANN,
            "ranzMarshallA": C.RANZ_MARSHALL_A,
            "ranzMarshallB": C.RANZ_MARSHALL_B,
            "minAirSpeedMS": C.MIN_AIR_SPEED_M_S,
            "airSutherlandMu0PaS": C.AIR_SUTHERLAND_MU0_PA_S,
            "airSutherlandT0K": C.AIR_SUTHERLAND_T0_K,
            "airSutherlandSK": C.AIR_SUTHERLAND_S_K,
            "airGasConstantJKgK": C.AIR_GAS_CONSTANT_J_KG_K,
            "airPrandtl": C.AIR_PRANDTL,
            "airConductivityRefWMK": C.AIR_CONDUCTIVITY_REF_W_M_K,
            "airConductivityRefTK": C.AIR_CONDUCTIVITY_REF_T_K,
            "airConductivityExponent": C.AIR_CONDUCTIVITY_EXPONENT,
            "isaSeaLevelPressurePa": C.ISA_SEA_LEVEL_PRESSURE_PA,
            "isaLapseCoeff": C.ISA_LAPSE_COEFF,
            "isaLapseExponent": C.ISA_LAPSE_EXPONENT,
            "brutsaertA": C.BRUTSAERT_A,
            "brutsaertExponent": C.BRUTSAERT_EXPONENT,
            "magnusAKpa": C.MAGNUS_A_KPA,
            "magnusB": C.MAGNUS_B,
            "magnusC": C.MAGNUS_C,
            "windMeasurementHeightM": C.WIND_MEASUREMENT_HEIGHT_M,
            "globeHeightM": C.GLOBE_HEIGHT_M,
            "surfaceRoughnessLengthM": C.SURFACE_ROUGHNESS_LENGTH_M,
            "solarConstantWM2": C.SOLAR_CONSTANT_W_M2,
            "haurwitzA": C.HAURWITZ_A,
            "haurwitzB": C.HAURWITZ_B,
            "meinelTau": C.MEINEL_TAU,
            "meinelAmExponent": C.MEINEL_AM_EXPONENT,
            "diurnalWarpGammaBounds": list(C.DIURNAL_WARP_GAMMA_BOUNDS),
            "diurnalWarpGammaPlausible": list(C.DIURNAL_WARP_GAMMA_PLAUSIBLE),
        },

        # A legal constraint, not a preference. The store rejects any field
        # whose name matches one of these before it is ever written.
        "forbiddenInputs": sorted(C.FORBIDDEN_INPUTS),
    }


def source_hash(data: dict) -> str:
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def main():
    data = payload()
    digest = source_hash(data)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("/* GENERATED by scripts/build_js_constants.py from "
                 "src/acclimate/constants.py.\n"
                 "   DO NOT EDIT. constants.py is the single source of truth; a second\n"
                 "   hand-maintained copy of the exposure limits or the work/rest ladder\n"
                 "   is exactly the thing that drifts and then decides whether a worker\n"
                 "   is told to stop.\n"
                 "\n"
                 "   sourceHash is checked by tests/test_js_engine.py, if constants.py\n"
                 "   changed and this file was not regenerated, the suite fails. */\n")
        fh.write("window.ACCLIMATE_CONSTANTS = ")
        json.dump({"sourceHash": digest, **data}, fh, indent=1, sort_keys=True)
        fh.write(";\n")

    print("wrote %s (%d KB), sourceHash %s"
          % (os.path.relpath(OUT), os.path.getsize(OUT) // 1024 or 1, digest))
    print("  %d trades, %d work classes, %d ladder rungs, %d clothing options"
          % (len(data["tradeToWorkClass"]), len(data["ralByClass"]),
             len(data["workRestLadder"]), len(data["clothingAdjustmentC"])))
    print("  %d forbidden input names enforced in the browser"
          % len(data["forbiddenInputs"]))


if __name__ == "__main__":
    main()
