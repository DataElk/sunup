# Standards and assurance status

Sunup is a hackathon prototype. It is not ISO certified, NIOSH endorsed, or
validated for operational safety decisions. ISO does not certify products or
organizations itself; third-party certification requires an external conformity
assessment body.

| Reference | What Sunup uses | What Sunup does not claim |
| --- | --- | --- |
| NIOSH 2016-106 | Recommended Alert Limit and Recommended Exposure Limit curves; new-worker and returning-worker calendar comparisons | The continuous readiness state, personal-limit interpolation, and 60/45/30/15 ladder are not NIOSH models or schedules |
| NIOSH 2017-127 | Confirms that NIOSH publishes work/rest schedules and examples | Sunup's ladder is not a transcription of that schedule |
| ISO 7243:2017 | Selected WBGT equations, clothing adjustment handling, and an Annex D calculation path checked against Table D.1 examples | No full conformity assessment or certification has been performed |
| OSHA heat rulemaking | The repository identifies the federal heat rule as proposed and points to current rulemaking status | Sunup is not a legal compliance determination |

## Evidence available in this repository

- Python and browser engines are compared with generated golden vectors at a
  numerical tolerance of 1e-9.
- The ISO Annex D calculation path is checked against the standard's worked table
  examples.
- Spatial selection tests enforce the 500 m request-edge discard and reject
  boundaries with no safe cell.
- The full automated test and design checks are documented in `VALIDATION.md`.

These checks are software verification and standards traceability. They are not
clinical validation, field validation, product certification, or proof that an
absolute prescription is safe for operational use.

## Primary references

- [NIOSH Criteria for a Recommended Standard, Publication 2016-106](https://www.cdc.gov/niosh/publications/numbered/2016-106.html)
- [NIOSH Heat Stress: Work/Rest Schedules, Publication 2017-127](https://www.cdc.gov/niosh/docs/2017-127/pdfs/2017-127.pdf)
- [NIOSH Workplace Recommendations](https://www.cdc.gov/niosh/heat-stress/recommendations/)
- [ISO 7243:2017 overview](https://www.iso.org/standard/67188.html)
- [ISO explanation of certification](https://www.iso.org/certification.html)
- [OSHA Heat Injury and Illness Prevention rulemaking](https://www.osha.gov/heat-exposure/rulemaking)
