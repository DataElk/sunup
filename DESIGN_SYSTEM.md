# Sunup: Design System

The visual direction, the component inventory, and the rules that keep them intact.
`web/tokens.css` holds the values. `scripts/check-design.mjs` enforces them.

---

## Direction

**Microsoft Fluent.** Cool neutrals, Fluent communication blue as the single
interactive accent, Segoe UI, hairline borders instead of shadows, restrained radius,
and readable professional density.

This is a Microsoft-family enterprise tool and it should look like one. The user is a
safety professional doing their job on a workstation, not a consumer being delighted.

**What Fluent gives us that matters here:**

- **One accent, reserved for interaction.** Fluent blue means *clickable* or
  *selected*, never *cool* or *safe*. Every data colour comes from a separate ramp.
  Mixing the two is the most common failure in dashboards and it destroys legibility.
- **Semantic status colours that are already legible in sunlight**: deep, desaturated,
  and familiar from every Microsoft surface a supervisor has already used.
- **A neutral ramp with enough steps** to build hairline structure without shadows.

### Why this is also the strategically correct choice

Generic dashboards lean on rounded cards, soft shadows, oversized whitespace, one
large number per card, and decorative gradients. This system is defined by operational
hierarchy instead: compact decisions, stable navigation, restrained surfaces, and data
graphics that answer a specific question.

---

## The shell

One navigation surface combines primary destinations with the site and crew tree.
This follows Fluent's guidance that high-level navigation can contain a tree in its
flexible region, while keeping the content pane as the largest part of the screen.

```
+-------------------+---------------------------------------------+
| Sunup             | contextual command bar 48px                 |
| primary nav       +---------------------------------------------+
|                   | page title and context                      |
| sites             |                                             |
|   crews           | content: DetailsList, map, or worker        |
|                   |                                             |
| data status       |                                             |
+-------------------+---------------------------------------------+
```

Rules the shell exists to enforce:

1. Content is the largest thing on screen. A panel opens over it and closes; nothing
   permanent takes half the width.
2. Commands live in one bar and enable on selection. They do not appear and disappear,
   because a toolbar that reflows under the cursor cannot be learned.
3. No ribbon. A ribbon is a command surface for an application with dozens of commands
   over a large data canvas. This has a handful, so a 48px contextual bar is the correct weight.
4. Every level is addressable. `#/site/:id/crew/:id/worker/:id` survives a hard refresh,
   and the breadcrumb is the way back up.

---

## The signature: a decision profile

The worker page is remembered by a coordinated **decision profile**, not one mixed
chart. It has two related views:

- **Work capacity history** separates prescribed minutes from thermal load. Minutes
  use their own 0 to 480 scale. Peak WBGT and personal limit share a temperature scale
  in a second aligned panel. Actual minutes are hollow markers. Forecast segments are
  shaded and dashed.
- **Shift plan** plots hourly WBGT against the personal limit, then aligns recommended
  work minutes beneath the same hour axis. Stop-work hours receive a quiet risk band.

Minutes, temperature, and readiness never share an axis. A combined plot can conserve
space while making every relationship harder to read. Aligned panels keep the shared
time context without implying that unlike measures are directly comparable.

---

## Component inventory

These are the primitives. If a screen needs something that is not on this list, add it
to the list first, with a name, a definition and a token mapping. Never inline a one-off
variant into a screen. That is how a design system dies.

| Component | Purpose | Notes |
| --- | --- | --- |
| `SideNav` | Product identity, primary destinations, entity tree, and data status | 272px desktop, 64px compact, drawn SVG icons |
| `NavTree` | Site and crew hierarchy within the side navigation | 36px rows, twisty, icon, label, count, status dot |
| `CommandBar` | Single contextual command surface | 48px, 36px controls, icon and label, divider before destructive commands, overflow menu |
| `Breadcrumb` | The way up from a nested view | Links every level except the current one |
| `DetailsList` | The working grid | 40px sortable header with a caret, 28px check column, 44px rows |
| `StatusChip` | Prescription severity | Compact pill with a status dot, from the `--status-*` scale |
| `Tag` | Provenance and state marks: seed, derived, override, assumed | `--font-data`, never carries severity |
| `Sparkline` | 14 days in 86px, on a grid row | Height is peak WBGT, fill is the status band |
| `WorkerTrend` | Prescribed and actual minutes, then WBGT and personal limit | Two aligned panels with independent units and a shared date axis |
| `ShiftPlan` | Hourly thermal conditions and work allocation | Shared hour axis, exact values in a disclosure below |
| `DecisionCard` | Supervisor work window, recovery time, controls, and closeout | Derived from existing status and hourly allocation |
| `WorkerLocation` | Static Arizona location context for one worker | Site marker and direct action to the interactive site map |
| `CalculationFeedback` | Confirms a saved actual has recalculated the plan | Changed values show staggered calculation dots, then reveal in place; chart points and bars update with the same cadence; disabled by reduced-motion preference |
| `Panel` | Editors and confirmations | `--drawer-width` over a scrim, closes on Escape |
| `Callout` | A state the user must act on or account for | Kinds: info, warn, danger, assumed |
| `MapCanvas` | Exceedance choropleth and selection surface | Canvas, `--heat-*` ramp, quantile classes, crew markers are clickable |
| `MapBasemap` | Offline locator layer | `--map-road-*`, `--map-river`, `--map-park`. Build-time OSM fetch, cached |
| `DataStatus` | Persistent side navigation footer | Date, source, and browser store size |

Retired with the demonstration screen it belonged to: `Drawer` as a permanent detail
surface, `CrewStrip`, `Card`, `Counterfactual` as a standalone component, `ReasonTag`,
`MismatchBar`. The counterfactual survives as a column in `DetailsList`; the mismatch
survives as the sign and colour of that column.

---

## Non-negotiables

These map onto lint rules. A violation fails the build.

1. **No literal colour anywhere but `tokens.css`.** No hex, no `rgb()`. If the colour
   you need does not exist, add it as a *role*, not a value.
2. **No arbitrary radius.** `--radius-control` (2px) for controls,
   `--radius-surface` (4px) for surfaces, and `--radius-pill` only for compact badges.
3. **Shadows are Fluent depth tokens only**: `--elevation-card`, `--elevation-flyout`,
   `--elevation-dialog`. Inline elements use borders.
4. **No gradients, no backdrop blur.**
5. **No emoji as icons.** Drawn SVG only.
6. **All numerals are `--font-data` with `tabular-nums`.** Columns must align.
7. **Accent means interactive.** Data colour comes from `--heat-*`, `--status-*` and
   `--mismatch-*`. Never mix them. A blue that means "selected" in one place and "cool" in
   another destroys legibility.
8. **Focus is always visible.** `--focus-width` solid `--line-focus`, never removed.

### Product rules the lint also checks

9. **Every worker view shows the counterfactual**, and shows it as a *relationship*:
   what the calendar allows, what the model allows, and the signed gap between them.
   Two adjacent numbers with a strikethrough is not a relationship; it is a puzzle.
10. **Readiness never appears on a collapsed row.** The supervisor gets minutes.
    Worker detail may show readiness as a percentage; raw state decimals stay internal.
11. **Projected data is never visually confusable with observed data.** Past solid,
    future dashed at `--projected-alpha`. Honesty requirement, not stylistic.
12. **Colour encodes mismatch rather than temperature, and intensity encodes magnitude.**
    Every roster row carries a signed mismatch indicator from the `--mismatch-*` scale.
    **Hue carries the sign. Width and opacity carry the size.**
    - **`--mismatch-over` (magenta)**: the calendar allows MORE than the model.
      Under-protection. This is the dangerous direction and the product's whole argument.
    - **`--mismatch-under` (teal)**: the calendar allows LESS. Productive hours a
      blanket rule was discarding.
    - **`--mismatch-none`**: they agree.

    The indicator is driven by `--mismatch-weight`, set per row as
    |divergence| ÷ shift minutes: 2px and faint at the margin, 10px and solid at a
    whole shift. **A flag that fires on almost every row is not a signal.** The first
    implementation put a fixed 4px bar on five of six rows, which conveyed exactly as
    much as putting it on none of them. If under-protection is the common case, then
    "is under-protected" is not the finding. "By how much" is.

    Status chips stay severity-coloured; the mismatch indicator is a *separate* channel.
    A 40 °C day with an adapted crew is fine. A 32 °C day with four new hires is not.
13. **A restricted worker must say why**, and name the lever that would recover the
    hours, priced in minutes. "0 min" with no explanation is not an instruction.

    The **diagnosis** is read off the most restrictive hour (when this worker crosses his own
    limit, and by how much at the worst hour), so two workers cannot produce the same
    sentence unless they are genuinely in the same situation. The **action** is the
    largest lever an employer can actually pull, priced in minutes.

    A lever must be *pullable*. Reassigning a worker to a lighter NIOSH work class
    prices enormously (moderate RAL 25.0 °C vs light 28.0 °C) and is not an action:
    trades are not interchangeable, and you cannot answer "this man is over his limit"
    with "make him an electrician". A lever nobody can pull is noise in a column that
    exists to drive a decision.

    Corollary: **a column where most rows say the same thing has failed**, even when
    every row is telling the truth.

---

## What the screen is for

The demo crew is a **designed comparison, not a sample**. It is built around a matched
pair (same site, same trade, same day count, differing only in start time) placed
adjacent and visually marked.

That pair is the product. M3 measured shift timing as the strongest available lever
(+1.07 °C of personal limit at day 4, growing to +2.75 °C by day 14; 84/84 τ pairs,
both wet-bulb methods) while site
assignment did not reach materiality at all. A crew that varies trade, site, shift and
day count all at once means nothing on screen is comparable and the finding is
invisible.

**Shift time is the lever.** It is not 9px grey metadata; it is a primary column.

---

## Two densities, one grid

The desktop safety-manager view and the field supervisor view are the same tokens, the
same components and the same facts. Set `data-density="touch"` on the root; never write
a second stylesheet.

- Desktop: 14px body, 272px side navigation, 44px rows.
- Field: 16px body, 64px compact navigation, 64px rows, nothing tappable under 44px.

A density changes the metrics of the grid. It does not change the grid into something
else. An earlier draft of this page required a different layout at touch density, and
the build that followed it produced 450px cards showing two and a half workers per
screen, which is a slideshow rather than a roster. A supervisor reading a crew at 6 a.m.
wants the same list his manager sees, with rows he can hit.

The rule that survived from that draft is narrower and still worth keeping: if a density
token cannot bind, the density is not implemented, and shipping it anyway claims a
capability the build does not have. `--row-height` now binds because the grid row is
sized by the token rather than by a strip that dwarfs it.

The field view is used outdoors, in glare, one-handed, possibly gloved. It must answer
"who works today and for how long" in under ten seconds.

---

## How to keep this from drifting

**1. The lint blocks the build.**
```json
"scripts": {
  "check:design": "node scripts/check-design.mjs",
  "prebuild": "npm run check:design"
}
```
Run it after every screen. Not advisory.

**2. Screenshot and compare.** After building any screen, take a screenshot and put it
next to the previous one. Ask directly: do these look like one product? Drift is obvious
visually and nearly invisible in a diff.

**3. Inventory before implementation.** Needing a component that is not in the table
above is a signal to stop and extend the table, not to improvise.

**4. Never add an exception to the lint.** If a rule blocks you, the rule is almost
always right and the code is wrong. If the rule is genuinely wrong, change the rule
deliberately and write down why. Do not add a per-file ignore.

---


---

## The map

Two rules, both learned the hard way.

**Classing is quantile, never equal-interval.** The exceedance distribution is strongly
left-skewed (p5 79.3 h, p50 96.7 h, max 106.9 h), so equal steps in value are nothing
like equal steps in area. Equal-interval classing put **81% of cells in the top two
classes** and the whole metro rendered as one flat red smear. Six classes, one per
`--heat-*` stop, each holding a sixth of the cells. **The break values are printed in
the legend**: a quantile scale whose thresholds are hidden cannot be read back to a
number.

**A choropleth needs a locator.** Two markers 20 km apart on a field of colour cannot
be placed by anyone, which makes a spatial claim unauditable. The basemap is major
roads, the river and parks above 4 ha, fetched from OpenStreetMap **at build time** and
cached into a static module, a fixture exactly like every other input here. No tile
server is contacted at render time. It is drawn in `--map-*` neutrals over the
choropleth and must never be mistaken for data. Attribution is rendered in the legend.

**State the effective resolution, and scope the claim to the layer.** These tiles are
101 m, but the exceedance field they carry is far smoother: a 500 m box blur keeps
98.9% of its variance, and neighbouring tiles differ by 0.40% of the range on average.
Drawing that at tile resolution implies a precision it does not have, so the number is
printed on the map rather than left for a reader to discover by squinting.

The obvious objection is that exceedance counts hours across 336 of them, so of course
it is smooth. That was tested rather than assumed. **A metro-extent single-hour
retrieval over the identical 250 × 186 lattice scores 0.42% against exceedance's 0.40%,
and keeps 98.6% of its variance through a 500 m blur against 98.9%.** One instant is
exactly as smooth as the fortnight-long count built from it, so the smoothness is a
property of the field, not of the aggregation.

**Compare only at matched extent.** An earlier draft of this page reported the opposite,
because it compared parcel fixtures (0.8 × 1.1 km) against the metro grid and read the
"% of range" column across them. Absolute neighbour differences are ~0.004-0.006 °C in
both; only the denominator moved, because a 0.8 km window spans 0.09 °C and a 25 km
window spans 1.02 °C. Normalise by a window-dependent quantity and you measure your
window. `scripts/audit_resolution.py` now prints the absolute column first for that
reason.

**Then say what it means, with a yardstick you can reproduce.** At 14:00 on a day above
40 °C the entire Phoenix metro spans 1.02 °C. The same API's daily min/max product puts
the diurnal range at a *single point* at 5.8-11.4 °C. One location changes about eight
times more over a day than the whole metro varies at any instant. That is why the locator
basemap is drawn from OpenStreetMap rather than inferred from the data. The data does not
contain the roads. Take the comparison from your own fixtures, never from a remembered
figure.

---

## Anti-patterns: the specific things not to build

Named explicitly because these are common dashboard defaults, and naming the attractor
is the most reliable way to avoid it.

- A grid of rounded white cards with drop shadows
- A large number with a small grey label under it, repeated four across the top
- An indigo, violet or teal *accent* (teal is a data colour here, never chrome)
- Inter, system-ui alone, or a generic `font-sans` stack
- Generous whitespace in place of information
- A gradient hero band
- Emoji status indicators
- A chart library's default colour cycle
- **Chrome sized for an application larger than the one you are building**: a ribbon
  over eight rows, a permanent panel over an empty half-screen
- **A signature element rendered too small to read**
- A flag that fires on almost every row. If it marks five rows of six it marks none
- A column where most rows say the same true, useless thing
- A lever priced in the interface that nobody can actually pull
- Equal-interval classing on a skewed distribution
- A density token that cannot bind, shipped as a density feature
- A map with no way to locate anything on it
- Rendering data at a resolution finer than the data actually has
- "Modern", "clean", "sleek" as design goals. They describe nothing and produce the
  template
