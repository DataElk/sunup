/* ============================================================================
   Fluent primitives.

   Modelled on the structure Outlook, the Azure Portal and SharePoint admin
   actually use, not just their palette:

     CommandBar    32px tall, icon + label buttons, a divider before destructive
                   actions, an overflow menu when the bar runs out of room, and
                   commands that ENABLE ON SELECTION rather than appearing and
                   disappearing.
     NavTree       expandable site > crew, selection persists, keyboard arrows.
     DetailsList   32-40px rows, sortable column headers with a direction
                   caret, a check column, and a selection count that drives the
                   command bar above it.
     Breadcrumb    the way back up from a third-level view.
     Panel         a right-hand surface that slides over content and closes,
                   not a permanent half-screen.

   The controls are plain DOM. There is no framework here and no need for one;
   what mattered was matching the metrics and the behaviour.
   ========================================================================== */

export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

/* --- Icons -----------------------------------------------------------------
   Drawn, not emoji. 16px grid to match Fluent's icon metrics. */

const PATHS = {
  add: 'M8 3v10M3 8h10',
  edit: 'M11.5 2.5l2 2L6 12l-3 1 1-3z',
  remove: 'M3.5 4.5h9M6.5 4.5V3h3v1.5M5 4.5l.6 8h4.8l.6-8',
  log: 'M3 3h10v10H3zM3 6.5h10M6.5 6.5V13',
  reset: 'M13 8a5 5 0 1 1-1.7-3.8M13 2v3h-3',
  site: 'M8 2l5 3v6l-5 3-5-3V5z',
  crew: 'M5.5 7a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM2 13c0-2 1.6-3.5 3.5-3.5S9 11 9 13M11 6.5a1.6 1.6 0 1 0 0-3.2M10.5 9.7c1.7 0 3 1.3 3 3.3',
  grid: 'M2.5 3.5h11v9h-11zM2.5 6.5h11M2.5 9.5h11M6 6.5v6',
  map: 'M2.5 4.5l3.5-1.5v9L2.5 13.5zM6 3l4 1.5v9L6 12zM10 4.5l3.5-1.5v9L10 13.5z',
  chart: 'M2.5 11.5l3-3.5 2.5 1.5 5.5-6',
  gear: 'M8 5.8A2.2 2.2 0 1 0 8 10.2 2.2 2.2 0 0 0 8 5.8zM8 1.8l.6 1.6 1.7-.3.5 1.6 1.5.9-.9 1.5.9 1.5-1.5.9-.5 1.6-1.7-.3L8 14.2l-.6-1.6-1.7.3-.5-1.6-1.5-.9.9-1.5-.9-1.5 1.5-.9.5-1.6 1.7.3z',
  more: 'M4 8h.01M8 8h.01M12 8h.01',
  copy: 'M3.5 3.5h6v6h-6zM6.5 6.5h6v6h-6z',
  close: 'M4 4l8 8M12 4l-8 8',
  chevron: 'M6 4l4 4-4 4',
  download: 'M8 2v8M5 7.5L8 10.5l3-3M3 13h10',
};

export function icon(name, size = 16) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('width', size);
  svg.setAttribute('height', size);
  svg.setAttribute('viewBox', '0 0 16 16');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.25');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS(ns, 'path');
  path.setAttribute('d', PATHS[name] || PATHS.more);
  svg.appendChild(path);
  return svg;
}

/* --- CommandBar -------------------------------------------------------------
   Commands are declared with an `enabled` predicate rather than being added and
   removed, so the bar does not reflow as a selection changes, which is what
   Office does and what makes the toolbar feel stable under the cursor. */

export function commandBar(commands, context) {
  const bar = el('div', 'cmdbar');
  bar.setAttribute('role', 'toolbar');

  const primary = commands.filter((c) => !c.overflow);
  const overflow = commands.filter((c) => c.overflow);

  for (const command of primary) {
    if (command.divider) { bar.appendChild(el('span', 'cmd-divider')); continue; }
    bar.appendChild(commandButton(command, context));
  }

  if (overflow.length) {
    bar.appendChild(el('span', 'cmd-divider'));
    bar.appendChild(overflowMenu(overflow, context));
  }
  return bar;
}

function commandButton(command, context) {
  const button = el('button', 'cmd');
  button.type = 'button';
  const enabled = command.enabled ? command.enabled(context) : true;
  button.disabled = !enabled;
  if (command.danger) button.classList.add('cmd-danger');
  button.appendChild(icon(command.icon));
  button.appendChild(el('span', null, command.label));
  if (command.title) button.title = command.title;
  button.addEventListener('click', () => command.run(context));
  return button;
}

function overflowMenu(commands, context) {
  const wrap = el('div', 'cmd-overflow');
  const button = el('button', 'cmd cmd-icononly');
  button.type = 'button';
  button.title = 'More commands';
  button.setAttribute('aria-haspopup', 'menu');
  button.setAttribute('aria-expanded', 'false');
  button.appendChild(icon('more'));

  const menu = el('div', 'cmd-menu');
  menu.setAttribute('role', 'menu');
  for (const command of commands) {
    const item = el('button', 'cmd-menuitem');
    item.type = 'button';
    item.setAttribute('role', 'menuitem');
    item.disabled = command.enabled ? !command.enabled(context) : false;
    if (command.danger) item.classList.add('cmd-danger');
    item.appendChild(icon(command.icon));
    item.appendChild(el('span', null, command.label));
    item.addEventListener('click', () => { close(); command.run(context); });
    menu.appendChild(item);
  }

  function open() {
    wrap.classList.add('open');
    button.setAttribute('aria-expanded', 'true');
    setTimeout(() => document.addEventListener('click', onAway), 0);
  }
  function close() {
    wrap.classList.remove('open');
    button.setAttribute('aria-expanded', 'false');
    document.removeEventListener('click', onAway);
  }
  function onAway(event) { if (!wrap.contains(event.target)) close(); }

  button.addEventListener('click', () => {
    if (wrap.classList.contains('open')) close(); else open();
  });
  wrap.append(button, menu);
  return wrap;
}

/* --- Breadcrumb -------------------------------------------------------------- */

export function breadcrumb(parts) {
  const nav = el('nav', 'crumbs');
  nav.setAttribute('aria-label', 'Breadcrumb');
  parts.forEach((part, index) => {
    if (index) {
      const sep = el('span', 'crumb-sep');
      sep.appendChild(icon('chevron', 12));
      nav.appendChild(sep);
    }
    if (part.href && index < parts.length - 1) {
      const link = el('a', 'crumb', part.label);
      link.href = part.href;
      nav.appendChild(link);
    } else {
      const current = el('span', 'crumb crumb-current', part.label);
      current.setAttribute('aria-current', 'page');
      nav.appendChild(current);
    }
  });
  return nav;
}

/* --- NavTree ----------------------------------------------------------------- */

export function navTree({ nodes, selectedId, expanded, onSelect, onToggle }) {
  const tree = el('div', 'tree');
  tree.setAttribute('role', 'tree');

  for (const node of nodes) {
    const isOpen = expanded.has(node.id);
    const row = el('div', 'tnode tnode-group');
    row.setAttribute('role', 'treeitem');
    row.setAttribute('aria-expanded', String(isOpen));
    row.tabIndex = 0;
    if (node.id === selectedId) row.classList.add('sel');

    const twisty = el('button', 'twisty');
    twisty.type = 'button';
    twisty.tabIndex = -1;
    twisty.setAttribute('aria-label', isOpen ? 'Collapse' : 'Expand');
    twisty.appendChild(icon('chevron', 12));
    if (isOpen) twisty.classList.add('open');
    twisty.addEventListener('click', (e) => { e.stopPropagation(); onToggle(node.id); });

    row.append(twisty, icon('site'), el('span', 'tlabel', node.label));
    if (node.badge) row.appendChild(statusDot(node.badge));
    row.addEventListener('click', () => onSelect(node));
    row.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(node); }
      if (e.key === 'ArrowRight' && !isOpen) onToggle(node.id);
      if (e.key === 'ArrowLeft' && isOpen) onToggle(node.id);
    });
    tree.appendChild(row);

    if (!isOpen) continue;
    for (const child of node.children || []) {
      const crow = el('div', 'tnode tnode-child');
      crow.setAttribute('role', 'treeitem');
      crow.tabIndex = 0;
      if (child.id === selectedId) crow.classList.add('sel');
      crow.append(icon('crew'), el('span', 'tlabel', child.label));
      if (child.count !== undefined) {
        crow.appendChild(el('span', 'tcount', String(child.count)));
      }
      if (child.badge) crow.appendChild(statusDot(child.badge));
      crow.addEventListener('click', () => onSelect(child));
      crow.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(child); }
      });
      tree.appendChild(crow);
    }
  }
  return tree;
}

export function statusDot(status) {
  const dot = el('span', 'sdot');
  dot.setAttribute('data-status', status);
  dot.title = status;
  return dot;
}

/* --- DetailsList -------------------------------------------------------------
   Sortable headers, a check column, 36px rows. `columns` entries carry a
   `sortKey` when sortable and a `render(row)` that returns a node or string. */

export function detailsList({ columns, rows, sort, onSort, selection, onSelectionChange,
                              onInvoke, rowKey, empty, selectable = true }) {
  const wrap = el('div', 'dlist-wrap');
  const table = el('div', 'dlist');
  table.setAttribute('role', 'grid');

  const template = `${selectable ? '28px ' : ''}${columns.map((c) => c.width || '1fr').join(' ')}`;

  const head = el('div', 'dl-head');
  head.style.gridTemplateColumns = template;
  head.setAttribute('role', 'row');

  if (selectable) {
    const all = el('input', 'dl-check');
    all.type = 'checkbox';
    all.setAttribute('aria-label', 'Select all');
    all.checked = rows.length > 0 && selection.size === rows.length;
    all.indeterminate = selection.size > 0 && selection.size < rows.length;
    all.addEventListener('change', () => {
      const next = new Set();
      if (all.checked) rows.forEach((r) => next.add(rowKey(r)));
      onSelectionChange(next);
    });
    head.appendChild(all);
  }

  for (const column of columns) {
    const cell = el('div', 'dl-th');
    cell.setAttribute('role', 'columnheader');
    if (column.numeric) cell.classList.add('num');
    if (column.sortKey) {
      const button = el('button', 'dl-sort');
      button.type = 'button';
      button.appendChild(el('span', null, column.label));
      if (sort && sort.key === column.sortKey) {
        cell.classList.add('sorted');
        const caret = el('span', 'dl-caret', sort.dir === 'asc' ? '▲' : '▼');
        button.appendChild(caret);
        cell.setAttribute('aria-sort',
          sort.dir === 'asc' ? 'ascending' : 'descending');
      }
      button.addEventListener('click', () => onSort(column.sortKey));
      cell.appendChild(button);
    } else {
      cell.appendChild(el('span', null, column.label));
    }
    head.appendChild(cell);
  }
  table.appendChild(head);

  if (!rows.length) {
    const none = el('div', 'dl-empty', empty || 'Nothing here yet.');
    table.appendChild(none);
    wrap.appendChild(table);
    return wrap;
  }

  for (const row of rows) {
    const key = rowKey(row);
    const line = el('div', 'dl-row');
    line.style.gridTemplateColumns = template;
    line.setAttribute('role', 'row');
    line.tabIndex = 0;
    if (selection.has(key)) line.classList.add('sel');

    if (selectable) {
      const check = el('input', 'dl-check');
      check.type = 'checkbox';
      check.checked = selection.has(key);
      check.setAttribute('aria-label', `Select ${key}`);
      check.addEventListener('click', (e) => e.stopPropagation());
      check.addEventListener('change', () => {
        const next = new Set(selection);
        if (check.checked) next.add(key); else next.delete(key);
        onSelectionChange(next);
      });
      line.appendChild(check);
    }

    for (const column of columns) {
      const cell = el('div', 'dl-td');
      if (column.numeric) cell.classList.add('num');
      const value = column.render(row);
      if (value instanceof Node) cell.appendChild(value);
      else cell.textContent = value === null || value === undefined ? '' : String(value);
      line.appendChild(cell);
    }

    if (onInvoke) {
      line.addEventListener('dblclick', () => onInvoke(row));
      line.addEventListener('click', () => onInvoke(row));
      line.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); onInvoke(row); }
      });
    }
    table.appendChild(line);
  }

  wrap.appendChild(table);
  return wrap;
}

/* --- Panel -------------------------------------------------------------------- */

let openPanel = null;

export function panel({ title, subtitle, body, footer, onClose }) {
  dismissPanel();
  const scrim = el('div', 'panel-scrim');
  const surface = el('aside', 'panel');
  surface.setAttribute('role', 'dialog');
  surface.setAttribute('aria-modal', 'false');
  surface.setAttribute('aria-label', title);

  const head = el('div', 'panel-head');
  const heading = el('div', 'panel-heading');
  heading.appendChild(el('h2', null, title));
  if (subtitle) heading.appendChild(el('div', 'panel-sub', subtitle));
  const close = el('button', 'panel-close');
  close.type = 'button';
  close.title = 'Close';
  close.setAttribute('aria-label', 'Close');
  close.appendChild(icon('close'));
  close.addEventListener('click', () => dismissPanel());
  head.append(heading, close);

  const content = el('div', 'panel-body');
  if (body) content.appendChild(body);
  surface.append(head, content);
  if (footer) surface.appendChild(footer);

  scrim.addEventListener('click', () => dismissPanel());
  document.body.append(scrim, surface);
  requestAnimationFrame(() => surface.classList.add('in'));

  openPanel = { scrim, surface, onClose };
  document.addEventListener('keydown', escClose);
  const first = surface.querySelector('input, select, button, textarea');
  if (first) first.focus();
  return surface;
}

function escClose(event) { if (event.key === 'Escape') dismissPanel(); }

export function dismissPanel() {
  if (!openPanel) return;
  const { scrim, surface, onClose } = openPanel;
  openPanel = null;
  document.removeEventListener('keydown', escClose);
  scrim.remove();
  surface.remove();
  if (onClose) onClose();
}

/* --- Small pieces -------------------------------------------------------------- */

export function chip(status, label) {
  const node = el('span', 'chip', label);
  node.setAttribute('data-status', status);
  return node;
}

export function tag(text, kind) {
  const node = el('span', 'tag', text);
  if (kind) node.setAttribute('data-kind', kind);
  return node;
}

export function field(label, control, hint) {
  const wrapsControl = control.matches('input, select, textarea');
  const wrap = el(wrapsControl ? 'label' : 'div', 'field');
  wrap.appendChild(el('span', 'field-label', label));
  wrap.appendChild(control);
  if (hint) wrap.appendChild(el('span', 'field-hint', hint));
  return wrap;
}

export function input(value, attrs = {}) {
  const node = el('input', 'ctl');
  node.value = value === null || value === undefined ? '' : value;
  Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
  return node;
}

export function select(value, options) {
  const node = el('select', 'ctl');
  for (const option of options) {
    const item = el('option', null, option.label);
    item.value = option.value;
    if (String(option.value) === String(value)) item.selected = true;
    node.appendChild(item);
  }
  return node;
}

export function toast(message) {
  const existing = document.querySelector('.toast');
  if (existing) existing.remove();
  const node = el('div', 'toast', message);
  node.setAttribute('role', 'status');
  document.body.appendChild(node);
  setTimeout(() => node.classList.add('in'), 10);
  setTimeout(() => { node.classList.remove('in'); setTimeout(() => node.remove(), 250); }, 3200);
}

export function confirmDialog({ title, message, confirmLabel, danger, onConfirm }) {
  const body = el('div', 'confirm-body');
  body.appendChild(el('p', null, message));
  const footer = el('div', 'panel-foot');
  const cancel = el('button', 'btn', 'Cancel');
  cancel.type = 'button';
  cancel.addEventListener('click', () => dismissPanel());
  const go = el('button', `btn btn-primary${danger ? ' btn-danger' : ''}`,
                confirmLabel || 'Confirm');
  go.type = 'button';
  go.addEventListener('click', () => { dismissPanel(); onConfirm(); });
  footer.append(cancel, go);
  panel({ title, body, footer });
}
