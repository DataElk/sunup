# Sunup submission copy

## Classification

- Primary track: Track 05, Model Designing
- Application track: Track 03, Industrial and Enterprise
- Product category: Workforce heat planning and operational decision support
- Primary buyer: A general contractor or HSE director responsible for outdoor crews
- Primary user: A site supervisor preparing and closing out daily work plans

Track 03 is where Sunup is used. Track 05 is what differentiates it.

## One sentence

Sunup converts FortyGuard site temperature and each worker's actual exposure history
into an individual work and rest plan, then shows which schedule change recovers the
most workable time without exceeding that worker's current limit.

## Short description

Calendar acclimatization schedules treat workers on the same job day as equally
ready, even when their shifts and recent heat exposure differ. Sunup uses FortyGuard
temperature tiles, hourly environmental drivers, and actual minutes worked to
maintain an individual exposure state. It produces an explainable hourly work plan,
compares it with the calendar rule, and tests pullable interventions such as an
earlier start, another site, or additional recovery time.

## Full project summary

New and returning workers are at disproportionate risk during their first days in
hot work. The proposed OSHA acclimatization schedule addresses that risk with a
calendar ramp, but a calendar has no term for when the worker was exposed, how much
work was completed, or whether the hottest hours prevented useful exposure entirely.

Sunup replaces that missing measurement with an explainable decision model. FortyGuard
anchors the selected site's daily thermal conditions with local heatmap tiles. Sunup
reconstructs the hourly profile, combines it with job-assigned workload, clothing,
shift timing, and actual heat-exposed minutes, and places the worker continuously
between the published NIOSH unacclimatized and acclimatized limits. The result is an
hourly work and recovery plan for each worker.

The supervisor sees who needs action, why the restriction exists, what changed from
the prior day, and which earlier shift can recover workable minutes. A comparison tool
can test another site, shift window, or recovery cap using the same start-of-shift
readiness. A crew optimizer then tests one shared start across every active worker,
rejects any schedule that reduces one worker's prescribed time, and ranks the
remaining plans by workers helped, total minutes recovered, and operational
disruption. At closeout, actual minutes feed the next eligible day's plan. Work
beyond the prescription is reported as overexposure rather than treated as
beneficial adaptation alone.

Each crew also has a print-ready daily field briefing. It converts the interactive
workspace into one stable handoff with hourly work and recovery instructions,
shared water, recovery-area, buddy-check, and emergency controls, individual
exceptions, supervisor review boxes, and closeout state.

The Today workspace includes an exception ledger for no-work plans, grouped missing
closeouts, unavailable weather, and recent actual minutes beyond the prescription.
Supervisors can acknowledge or reopen each event, and resolved acknowledgements
remain visible as browser-local history. Normal restricted plans stay in the Today
table instead of generating duplicate alert noise.

## Why FortyGuard is central

FortyGuard provides the daily local thermal anchor for every live site. Sunup uses the
selected cell's temporal minimum, mean, and maximum temperature after buffering the
request area and excluding edge cells. Those values set the amplitude and offset of
the hourly site curve. Regional hourly data supplies weather shape and environmental
drivers, but it cannot replace the local FortyGuard tile values used by the decision
model.

This division is intentional: FortyGuard contributes the local spatial product that
the regional source does not provide, while Sunup turns it into a worker-level
operational decision.

## What is innovative

Most heat products classify the environment. Sunup models the mismatch between the
environment, the assigned schedule, and the worker's accumulated job exposure.

The important unit is not a generic risk score. It is the number of workable minutes
for this worker today, with an hourly explanation and a counterfactual schedule. Two
workers at the same site, in the same trade, and on the same calendar day can receive
different instructions because their exposure histories differ.

The intervention comparison is also constrained to decisions an employer can pull:
site, shift time, and recovery allocation. It does not recommend changing a worker's
trade or use medical and demographic attributes.

## Impact and business value

The initial buyer is a general contractor or HSE organization managing newly assigned
outdoor workers across multiple sites. Sunup can support:

- Fewer blanket work restrictions when a safer schedule preserves workable time.
- Stronger protection for workers whose calendar day overstates their readiness.
- A documented reason for each worker-specific instruction.
- Faster start-of-shift prioritization across sites and crews.
- A shared crew schedule that improves workable time without trading away another
  worker's protection.
- A closeout record that connects actual work with later planning.
- Better targeting of scarce wearable monitoring toward the workers who need it most.

The prototype does not claim a measured financial return. Customer discovery and a
field validation study are the next steps before an operational deployment.

## Technical execution

- Static browser application deployed on GitHub Pages with no login requirement.
- Point and polygon site creation constrained to the Arizona key coverage area.
- Direct FortyGuard asynchronous submission and polling with persisted activity IDs.
- One geometry-validation history task before four concurrent initial days, partial
  success preservation, retry, and recoverable polling timeout.
- Fourteen observed days with background completion and six forecast days.
- Python and JavaScript implementations gated by golden vectors at 1e-9 agreement.
- Forbidden personal inputs rejected at the store boundary.
- Full CRUD, cascading deletes, browser persistence, cached demonstration data, and
  explicit live, cached, partial, and failed weather states.
- Automated model, API-contract, interface, environmental, and design verification.

## Reproducible evidence

- Shift timing 05:00 to 13:00 versus 10:00 to 18:00 changes the personal limit by
  1.07 °C on day 4 and 2.75 °C by day 14.
- The direction holds for all 84 tested gain and decay parameter pairs under both
  tested wet-bulb methods.
- The sign holds in 62 of 64 ladder, method, shift, and day configurations, including
  a continuous response with no rungs.
- Site assignment produced only a 0.23 °C difference and failed materiality in all 84
  parameter pairs. Sunup reports that negative result rather than promoting the
  original hypothesis.
- The raw site exposure ratio was corrected from an edge-artifact result to 1.28 after
  buffering, edge exclusion, percentile selection, and land-cover cross-checking.

## Limitations stated up front

- This is a hackathon prototype and is not validated for operational safety decisions.
- The four-rung work and recovery ladder is the project's construction, not a NIOSH
  table.
- The OSHA heat rule referenced by the project is proposed, not law.
- The default WBGT path uses psychrometric wet bulb as an approximation for natural wet
  bulb.
- The effective spatial scale measured in Phoenix is much smoother than the nominal
  tile size.
- Browser storage is local to one device and there is no shared organizational backend.
- Absolute prescriptions require prospective field validation. The comparative shift
  result is much better supported than the absolute ladder.

## Defensible answers to likely questions

### Why is this a model-design entry if it does not train a machine-learning model?

The challenge accepts decision models. No labelled dataset currently maps exposure
history to measured acclimatization state at the required scale. Training on synthetic
labels generated by the same equations would add opacity without independent evidence.
Sunup uses a bounded, falsifiable, sensitivity-tested state model because its output can
restrict a person's work.

### Why not use a wearable?

Wearables measure current strain well but require hardware on each worker. Sunup plans
accumulated readiness from site weather and work records the employer already has. The
two are complementary: Sunup can identify which workers most need real-time monitoring.

### Why not use the hottest site to accelerate adaptation?

The data did not support that assumption. The work and recovery rule removes the
hottest exposure from the completed work dose. Shift timing was the material lever;
site assignment was not.

### Can the absolute work plan be treated as a safety standard?

No. The comparative model is sensitivity-tested, but the absolute ladder remains an
unvalidated construction. A real deployment requires prospective validation and review
by occupational heat experts.
