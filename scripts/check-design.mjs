#!/usr/bin/env node
/**
 * check-design.mjs, machine-enforced design consistency.
 *
 * Prose style guides do not survive twelve days of edits. This does.
 * Wire it into the build:  "check:design": "node scripts/check-design.mjs"
 * and make it a prebuild step so a violation cannot ship.
 *
 * Zero dependencies. Run: node scripts/check-design.mjs [--fix-hints]
 */

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, extname, relative, basename } from 'node:path';

const ROOT = process.cwd();
const SCAN_DIRS = ['src', 'app', 'components'];
const SCAN_EXT = new Set(['.css', '.scss', '.ts', '.tsx', '.js', '.jsx', '.vue', '.svelte']);

// The only file allowed to hold literal visual values.
const TOKEN_FILES = new Set(['tokens.css']);

const errors = [];
const warnings = [];

const record = (list, file, line, rule, msg, snippet) =>
  list.push({ file, line, rule, msg, snippet: snippet.trim().slice(0, 100) });

/* ---------------------------------------------------------------------------
   RULES
   Each rule states WHY, because a rule whose reason is unclear gets worked
   around rather than followed.
   ------------------------------------------------------------------------ */
const RULES = [
  {
    id: 'no-literal-hex',
    severity: 'error',
    pattern: /#[0-9a-fA-F]{3,8}\b/g,
    skipTokenFile: true,
    why: 'Literal hex outside tokens.css. Every color must be a var(--token). ' +
         'If the color you need does not exist, add it to tokens.css with a role name.',
  },
  {
    id: 'no-literal-rgb',
    severity: 'error',
    pattern: /\brgba?\s*\(/g,
    skipTokenFile: true,
    why: 'Literal rgb()/rgba() outside tokens.css. Use a var(--token).',
  },
  {
    id: 'no-rounded-cards',
    severity: 'error',
    // FIXED 2026-08-25. The negative lookahead used to sit after `\s*`, which
    // can backtrack to zero width and land the lookahead on the space rather
    // than the value - so `border-radius: var(--radius-sm)` was reported as a
    // violation while a genuine `border-radius: 8px` still matched. Moving the
    // whitespace INSIDE the lookahead removes the backtracking path. Verified:
    // correct token usage passes, literal radii are still caught.
    pattern: /border-radius\s*:(?!\s*(?:0|2px|4px|var\())|rounded-(?:lg|xl|2xl|3xl|full)/g,
    why: 'Radius above 4px. Rounded cards are the strongest single tell of a ' +
         'templated dashboard. Fluent allows --radius-control (2px) for controls ' +
         'and --radius-surface (4px) for surfaces. Nothing else exists.',
  },
  {
    id: 'no-ad-hoc-shadow',
    severity: 'error',
    // FIXED 2026-08-25 - same backtracking bug as no-rounded-cards.
    pattern: /box-shadow\s*:(?!\s*(?:none|var\())|shadow-(?:sm|md|lg|xl|2xl)\b/g,
    skipTokenFile: true,
    why: 'Ad-hoc shadow. Exactly one elevation exists (--elevation-flyout) and it ' +
         'is for detached overlays. Inline elements are delineated by borders.',
  },
  {
    id: 'no-gradients',
    severity: 'error',
    pattern: /linear-gradient|radial-gradient|bg-gradient-|backdrop-blur/g,
    why: 'Gradients and blur are not in this visual language. Flat surfaces, hairline borders.',
  },
  {
    id: 'no-default-fonts',
    severity: 'error',
    // FIXED 2026-08-25 - same backtracking bug as no-rounded-cards.
    pattern: /font-family\s*:(?!\s*var\()|['"]Inter['"]|\bfont-sans\b/g,
    skipTokenFile: true,
    why: 'Font declared outside tokens. Use var(--font-ui), var(--font-display) ' +
         'or var(--font-data). Inter in particular is the default-look tell; ' +
         'Segoe UI belongs in tokens.css only.',
  },
  {
    id: 'no-generic-accent',
    severity: 'error',
    pattern: /\b(?:indigo|violet|purple|fuchsia|cyan|sky|emerald)-[3-9]00\b/g,
    why: 'Generic accent palette. Interactive color is --accent (Fluent blue); ' +
         'data color comes from --heat-*, --status-* and --mismatch-*.',
  },
  {
    id: 'no-emoji-icons',
    severity: 'error',
    pattern: /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/gu,
    why: 'Emoji used as an icon. This is a professional instrument; use drawn SVG icons.',
  },
  {
    id: 'no-raw-spacing',
    severity: 'warn',
    pattern: /(?:padding|margin|gap)(?:-(?:top|right|bottom|left|x|y))?\s*:\s*(?!0|var\()\d+px/g,
    why: 'Raw px spacing. Use the 4px scale: var(--space-1..7).',
  },
  {
    id: 'no-raw-font-size',
    severity: 'warn',
    pattern: /font-size\s*:\s*(?!var\()\d/g,
    why: 'Raw font-size. Use the type scale: var(--text-label..metric).',
  },
  {
    id: 'tabular-numerals',
    severity: 'warn',
    pattern: /toFixed\(|toLocaleString\(/g,
    why: 'Formatted number found, confirm its container uses var(--font-data) and ' +
         'tabular-nums. Columns of figures must align.',
  },
];

/* ---------------------------------------------------------------------------
   SEMANTIC CHECKS: things a regex on one line cannot catch
   ------------------------------------------------------------------------ */
function semanticChecks(file, text) {
  // The counterfactual is the product's entire argument. A roster or worker view
  // that never mentions the calendar comparison has quietly become a heat dashboard.
  if (/roster|worker.?row|crew/i.test(basename(file)) &&
      !/calendar|counterfactual|divergence|ramp.?rule/i.test(text)) {
    record(warnings, file, 0, 'missing-counterfactual',
      'A worker/roster view with no calendar comparison. Showing the model output ' +
      'without what the calendar would have said removes the reason this product exists.',
      basename(file));
  }

  // The adaptation state must never surface on a collapsed row. A foreman gets
  // minutes; the state variable appears only in the detail view.
  if (/roster|worker.?row/i.test(basename(file)) &&
      // FIXED 2026-08-25: `A\s*=` with no word boundary matched any
      // identifier ending in A, so the generated `window.ROSTER_DATA = {`
      // tripped it. The rule is about a bare adaptation variable; it needs \b.
      /\bA\s*=\s*\{|adaptationState.*toFixed|\{\s*A\.toFixed/i.test(text)) {
    record(warnings, file, 0, 'exposed-state-variable',
      'Adaptation state appears to render on a roster row. It belongs in the ' +
      'detail view only, the roster shows minutes.',
      basename(file));
  }

  // RULE 12. Colour encodes mismatch, not temperature. Every roster view must
  // carry a signed mismatch indicator from the --mismatch-* scale. This was
  // unimplemented for a whole milestone and the lint did not notice, which is
  // exactly the failure mode the lint exists to prevent.
  if (/roster|worker.?row|crew/i.test(basename(file)) &&
      /\.css$/i.test(file) === false &&
      !/mismatch/i.test(text)) {
    record(errors, file, 0, 'missing-mismatch-indicator',
      'A roster view with no --mismatch-* indicator. Rule 12: colour encodes ' +
      'whether the plan fits the person, not how hot it is. Status severity ' +
      'alone does not carry the calendar comparison.',
      basename(file));
  }

  // RULE 12, stylesheet half: the mismatch scale must actually be consumed.
  if (/\.css$/i.test(file) && /roster|grid|row/i.test(text) &&
      !/--mismatch-/.test(text)) {
    record(warnings, file, 0, 'unused-mismatch-scale',
      'Stylesheet defines row styling but never references --mismatch-*. The ' +
      'signed calendar comparison has no visual channel.',
      basename(file));
  }

  // RULE 13. A restricted worker must say why. "0 min" with no explanation is
  // not an instruction, and three workers at zero for three different reasons
  // must not look identical.
  if (/roster|worker.?row/i.test(basename(file)) &&
      /\.css$/i.test(file) === false &&
      !/reason|lever|why/i.test(text)) {
    record(warnings, file, 0, 'unexplained-restriction',
      'A roster view that never names why a worker is restricted. Rule 13: ' +
      'show the reason and the lever that recovers the hours, priced in minutes.',
      basename(file));
  }

  // Projected data must be visually distinct from observed data, always.
  if (/forecast|project|future|ramp/i.test(text) &&
      /forecast|project/i.test(basename(file)) &&
      !/dash|projected|--projected/i.test(text)) {
    record(warnings, file, 0, 'undifferentiated-projection',
      'Projected values with no --projected treatment. Observed and projected must ' +
      'never be visually confusable.',
      basename(file));
  }
}

/* ---------------------------------------------------------------------------
   WALK
   ------------------------------------------------------------------------ */
function walk(dir, out = []) {
  let entries;
  try { entries = readdirSync(dir); } catch { return out; }
  for (const e of entries) {
    if (e === 'node_modules' || e === 'dist' || e === 'build' || e.startsWith('.')) continue;
    const p = join(dir, e);
    const s = statSync(p);
    if (s.isDirectory()) walk(p, out);
    else if (SCAN_EXT.has(extname(p))) out.push(p);
  }
  return out;
}

const files = SCAN_DIRS.flatMap((d) => walk(join(ROOT, d)));

if (files.length === 0) {
  console.log('check-design: no source files found yet, nothing to check.');
  process.exit(0);
}

for (const file of files) {
  const rel = relative(ROOT, file);
  const isTokenFile = TOKEN_FILES.has(basename(file));
  const text = readFileSync(file, 'utf8');
  const lines = text.split('\n');

  lines.forEach((lineText, i) => {
    // Skip comment lines, rationale often names colors it does not use.
    const t = lineText.trim();
    if (t.startsWith('//') || t.startsWith('*') || t.startsWith('/*')) return;

    for (const rule of RULES) {
      if (isTokenFile && rule.skipTokenFile) continue;
      rule.pattern.lastIndex = 0;
      if (rule.pattern.test(lineText)) {
        record(rule.severity === 'error' ? errors : warnings,
               rel, i + 1, rule.id, rule.why, lineText);
      }
    }
  });

  semanticChecks(rel, text);
}

/* ---------------------------------------------------------------------------
   REPORT
   ------------------------------------------------------------------------ */
const fmt = (items, head) => {
  if (!items.length) return;
  console.log(`\n${head}\n${'─'.repeat(head.length)}`);
  const byRule = items.reduce((a, x) => ((a[x.rule] ??= []).push(x), a), {});
  for (const [rule, list] of Object.entries(byRule)) {
    console.log(`\n  ${rule}  (${list.length})`);
    console.log(`  ${list[0].msg}`);
    for (const x of list.slice(0, 8)) {
      console.log(`    ${x.file}:${x.line}  ${x.snippet}`);
    }
    if (list.length > 8) console.log(`    ... and ${list.length - 8} more`);
  }
};

console.log(`check-design: scanned ${files.length} files`);
fmt(warnings, 'WARNINGS');
fmt(errors, 'ERRORS');

if (errors.length) {
  console.log(`\n${errors.length} error(s). Build blocked.`);
  console.log('Fix by moving the value into tokens.css under a role name, then ' +
              'referencing var(--token). Do not add an exception to this script.\n');
  process.exit(1);
}

console.log(`\nPassed${warnings.length ? ` with ${warnings.length} warning(s)` : ''}.\n`);
