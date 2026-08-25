/* ============================================================================
   Text formatting shared by every view.

   The Python side emits ASCII — `degC`, `->` — deliberately: build_roster_data.py
   and the compliance record both have to survive being written to a file, pasted
   into a report, and read in a terminal, and a stray degree sign in a cp1252
   console is a crash, not a cosmetic problem.

   The browser is where that ASCII becomes typography. Keeping the conversion in
   one place is not tidiness: the roster prettified and the drawer did not, so the
   same worker's reason read two different ways depending on where you looked at
   it.
   ========================================================================== */

/** ASCII from the builders -> typography for the screen. */
export function pretty(text) {
  return String(text)
    /* Narrow no-break space: a value must never wrap away from its unit. The
       reason column broke "peak +5.6" onto one line and "degC" onto the next
       on all six rows. */
    .replace(/ degC/g, ' °C')
    .replace(/->/g, '→')
    .replace(/ - /g, ' · ');
}
