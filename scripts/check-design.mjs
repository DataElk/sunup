#!/usr/bin/env node
/**
 * check-design.mjs — machine-enforced design consistency.
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
    pattern: /border-radius\s*:\s*(?!0|2px|var\()|rounded-(?:md|lg|xl|2xl|3xl|full)/g,
    why: 'Radius above 2px. Rounded cards are the strongest single tell of a ' +
         'templated dashboard. Only --radius-none and --radius-sm exist, by design.',
  },
  {
    id: 'no-ad-hoc-shadow',
    severity: 'error',
    pattern: /box-shadow\s*:\s*(?!none|var\()|shadow-(?:sm|md|lg|xl|2xl)\b/g,
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
    pattern: /font-family\s*:\s*(?!var\()|['"]Inter['"]|\bfont-sans\b/g,
    skipTokenFile: true,
    why: 'Font declared outside tokens. Use var(--font-ui) or var(--font-data). ' +
         'Inter in particular is the default-look tell.',
  },
  {
    id: 'no-generic-accent',
    severity: 'error',
    pattern: /\b(?:indigo|violet|purple|fuchsia|teal|cyan|sky)-[3-9]00\b/g,
    why: 'Generic accent palette. Interactive color is --accent; data color comes ' +
         'from the ramps in tokens.css §6.',
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
    why: 'Formatted number found — confirm its container uses var(--font-data) and ' +
         'tabular-nums. Columns of figures must align.',
  },
];

/* ---------------------------------------------------------------------------
   SEMANTIC CHECKS — things a regex on one line cannot catch
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
      /A\s*=\s*\{|adaptationState.*toFixed|\{\s*A\.toFixed/i.test(text)) {
    record(warnings, file, 0, 'exposed-state-variable',
      'Adaptation state appears to render on a roster row. It belongs in the ' +
      'detail view only — the roster shows minutes.',
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
  console.log('check-design: no source files found yet — nothing to check.');
  process.exit(0);
}

for (const file of files) {
  const rel = relative(ROOT, file);
  const isTokenFile = TOKEN_FILES.has(basename(file));
  const text = readFileSync(file, 'utf8');
  const lines = text.split('\n');

  lines.forEach((lineText, i) => {
    // Skip comment lines — rationale often names colors it does not use.
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
