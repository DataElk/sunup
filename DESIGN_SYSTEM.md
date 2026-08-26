# Acclimate: Design System

The visual direction, the component inventory, and the rules that keep them intact.
`web/tokens.css` holds the values. `scripts/check-design.mjs` enforces them.

---

## Direction

**Microsoft Fluent.** Cool neutrals, Fluent communication blue as the single
interactive accent, Segoe UI, hairline borders instead of shadows, near-zero radius,
dense professional layout.

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

The default output of any AI coding tool asked for a dashboard is: rounded cards, soft
drop shadows, an indigo or violet accent, generous whitespace, Inter, one large number
per card, a gradient somewhere. This system is defined largely by refusing those
things, and Fluent refuses them by default rather than by exception.

---

## The shell

Three levels of master and detail, which is the arrangement Outlook, the Azure Portal
and SharePoint admin all use. The frame is fixed so that a new view is a rail entry plus
a content component, never a restructuring.

```
+----+----------------+-------------------------------------------+
|    | nav pane 280px | command bar 40px, commands enable on       |
|rail|                | selection                                  |
|48px| sites          +-------------------------------------------+
|    |   crews        | breadcrumb                                 |
|    |                | content: DetailsList, or one worker        |
+----+----------------+-------------------------------------------+
|  status bar 24px: date / source / model / store                  |
+------------------------------------------------------------------+
```

Rules the shell exists to enforce:

1. Content is the largest thing on screen. A panel opens over it and closes; nothing
   permanent takes half the width.
2. Commands live in one bar and enable on selection. They do not appear and disappear,
   because a toolbar that reflows under the cursor cannot be learned.
3. No ribbon. A ribbon is a command surface for an application with dozens of commands
   over a large data canvas. This has a handful, so a 40px bar is the correct weight.
4. Every level is addressable. `#/site/:id/crew/:id/worker/:id` survives a hard refresh,
   and the breadcrumb is the way back up.

---

## The signature: the ramp strip

Every design needs one element it is remembered by. Here it is the **ramp strip**, the
horizontal run of day cells showing seven days behind, today, and six ahead.

It is the right signature because the paper shift card and the calendar ramp are
precisely the artifacts this product replaces.

**It must be the largest thing on a roster row.** An earlier version rendered it at
~13px per cell with pale fills and an adaptation line that was invisible; a signature
element you cannot read is not a signature. Give it real width, real cell size, and
enough contrast that the shape of a worker's history is legible at a glance across the
room.

- **Bar height** encodes heat (peak WBGT). A position encoding, so it costs no colour.
- **Bar fill** encodes the prescription band. Colour is for fit, never for temperature.
- **A line in ink** encodes adaptation, drawn across the cells in `--adapt-line`, and
  `--adapt-line-projected` beyond today. Deliberately not a third colour scale.
- **Past solid, future dashed** at `--projected-alpha`. An honesty requirement.

---

## Component inventory

These are the primitives. If a screen needs something that is not on this list, add it
to the list first, with a name, a definition and a token mapping. Never inline a one-off
variant into a screen. That is how a design system dies.

| Component | Purpose | Notes |
| --- | --- | --- |
| `NavRail` | Left icon rail, one entry per workspace | `--rail-width`, drawn SVG icons, current item marked |
| `NavPane` | Site and crew tree | 280px, 28px rows, twisty, icon, label, count, status dot |
| `CommandBar` | Single command surface | 40px, 32px controls, icon and label, divider before destructive commands, overflow menu |
| `Breadcrumb` | The way up from a nested view | Links every level except the current one |
| `DetailsList` | The working grid | 32px sortable header with a caret, 28px check column, 36px rows |
| `StatusChip` | Prescription severity | `--radius-control`, from the `--status-*` scale |
| `Tag` | Provenance and state marks: seed, derived, override, assumed | `--font-data`, never carries severity |
| `Sparkline` | 14 days in 86px, on a grid row | Height is peak WBGT, fill is the status band |
| `RampStrip` | The signature. Day cells with the adaptation line | Worker detail only, where there is room to read it |
| `Panel` | Editors and confirmations | `--drawer-width` over a scrim, closes on Escape |
| `Callout` | A state the user must act on or account for | Kinds: info, warn, danger, assumed |
| `MapCanvas` | Exceedance choropleth and selection surface | Canvas, `--heat-*` ramp, quantile classes, crew markers are clickable |
| `MapBasemap` | Offline locator layer | `--map-road-*`, `--map-river`, `--map-park`. Build-time OSM fetch, cached |
| `StatusBar` | Persistent bottom strip | Date, source, model assumptions, store size |

Retired with the demonstration screen it belonged to: `Drawer` as a permanent detail
surface, `CrewStrip`, `Card`, `Counterfactual` as a standalone component, `ReasonTag`,
`MismatchBar`. The counterfactual survives as a column in `DetailsList`; the mismatch
survives as the sign and colour of that column.

---

## Non-negotiables

These map onto lint rules. A violation fails the build.

1. **No literal colour anywhere but `tokens.css`.** No hex, no `rgb()`. If the colour
   you need does not exist, add it as a *role*, not a value.
2. **No radius above 4px.** `--radius-control` (2px) for controls,
   `--radius-surface` (4px) for surfaces. Nothing else exists.
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
10. **The adaptation state never appears on a collapsed row.** The foreman gets minutes.
    `A = 0.34` appears only in the drawer, when he opens it asking why.
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

    The **diagnosis** is read off the binding hour (when this worker crosses his own
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

- Desktop: 14px body, 48px rail, 36px rows.
- Field: 16px body, 56px rail, 44px rows, nothing tappable under 44px.

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
"% of range" column across them. Absolute neighbour differences are ~0.004–0.006 °C in
both; only the denominator moved, because a 0.8 km window spans 0.09 °C and a 25 km
window spans 1.02 °C. Normalise by a window-dependent quantity and you measure your
window. `scripts/audit_resolution.py` now prints the absolute column first for that
reason.

**Then say what it means, with a yardstick you can reproduce.** At 14:00 on a day above
40 °C the entire Phoenix metro spans 1.02 °C. The same API's daily min/max product puts
the diurnal range at a *single point* at 5.8–11.4 °C. One location changes about eight
times more over a day than the whole metro varies at any instant. That is why the locator
basemap is drawn from OpenStreetMap rather than inferred from the data. The data does not
contain the roads. Take the comparison from your own fixtures, never from a remembered
figure.

---

## Anti-patterns: the specific things not to build

Named explicitly because these are the defaults an AI coding tool falls back into, and
naming the attractor is the only reliable way to avoid it.

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
