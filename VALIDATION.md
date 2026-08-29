# Software verification

Sunup separates software verification from field validation. The checks below show
that the repository is internally consistent and that key calculations reproduce
their references. They do not prove that an absolute work prescription is safe for
operational use.

## Current automated gate

Run from the repository root:

```bash
python -m pytest
node scripts/check-design.mjs
```

On 2026-08-29, the full Python and JavaScript suite passed 381 tests. The design
checker passed with 31 non-blocking warnings, primarily reminders to confirm
tabular-number styling. GitHub Actions repeats the verification after each push.

## What is checked

| Area | Evidence |
| --- | --- |
| Python and browser parity | Generated golden vectors compare both engines at a tolerance of 1e-9 |
| Adaptation history | Worked days, explicit absences, returning-worker schedules, decay, and hire-date position have regression cases |
| Actual work allocation | Logged minutes cannot exceed the shift; hourly allocation cannot exceed 60 minutes; above-plan work is assigned conservatively to hotter hours |
| Weather composition | A full browser environment replay is compared with the Python WBGT pipeline |
| Spatial selection | Point and polygon selection, 500 m edge discard, interior median, and refusal of unsafe fallbacks are tested |
| API contract | FortyGuard request, polling, error, and fixture parsing behavior have contract tests |
| Data operations | CRUD structure, cascading deletes, persistence, reset, bulk closeout, and exception acknowledgement have interface guards |
| User interface | Route and control structure, empty states, copy, print, chart accessibility, and design-token rules are checked |

## What is not established

- No prospective field study has compared Sunup prescriptions with worker outcomes.
- No occupational physician or industrial hygienist has approved the absolute ladder.
- No third-party conformity assessment or product certification has been performed.
- The seven-day forecast backtest is diagnostic evidence, not a production accuracy
  estimate.
- Passing software tests does not establish legal compliance or operational safety.

See [STANDARDS.md](STANDARDS.md) for the standards traceability statement and
[WRITEUP.md](WRITEUP.md) for the model audits and limitations.
