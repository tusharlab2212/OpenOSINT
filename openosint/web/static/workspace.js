/**
 * workspace.js — the research workspace page (/workspace).
 *
 * Talks only to this server's /api/investigations routes. Every value the user typed is
 * rendered with textContent (never as HTML) and every link goes through safeHttpUrl, so
 * a stored javascript:/data: URL can never become a clickable href. Nothing here fetches a
 * source URL or contacts a target: links open only when the investigator clicks them.
 *
 * The pure helpers are exported for tests/test_workspace.mjs; init() wires the page.
 */
import { safeHttpUrl } from '/static/url-safety.js';

export const TARGET_KINDS = ['username', 'domain', 'email', 'url', 'ip', 'phone', 'other'];
export const CONFIDENCE_LEVELS = ['low', 'medium', 'high'];
export const FINDING_KINDS = ['observation', 'assumption', 'conclusion'];

export const FINDING_KIND_LABELS = {
  observation: 'Observations — what a source shows',
  assumption: 'Assumptions — not yet supported by a source',
  conclusion: 'Conclusions — what you infer from the observations',
};

export const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'targets', label: 'Targets' },
  { id: 'findings', label: 'Findings' },
  { id: 'evidence', label: 'Evidence' },
  { id: 'sources', label: 'Sources' },
  { id: 'notes', label: 'Notes' },
];

/** Form fields per section. `ref` fields are filled with the investigation's own items. */
export const FIELDS = {
  targets: [
    { name: 'kind', label: 'Type', type: 'select', options: TARGET_KINDS, required: true },
    { name: 'value', label: 'Identifier', type: 'text', required: true, max: 500,
      placeholder: 'e.g. example.com or a username' },
    { name: 'notes', label: 'Notes', type: 'textarea' },
  ],
  findings: [
    { name: 'title', label: 'Title', type: 'text', required: true, max: 200 },
    { name: 'kind', label: 'Type', type: 'select', options: FINDING_KINDS, required: true },
    { name: 'confidence', label: 'Confidence', type: 'select', options: CONFIDENCE_LEVELS,
      required: true },
    { name: 'description', label: 'Description', type: 'textarea' },
    { name: 'source_url', label: 'Source URL', type: 'url', placeholder: 'https://…' },
    { name: 'target_id', label: 'Target', type: 'ref', ref: 'targets' },
    { name: 'recorded_on', label: 'Date recorded', type: 'date' },
    { name: 'notes', label: 'Investigator notes', type: 'textarea' },
  ],
  evidence: [
    { name: 'description', label: 'Description', type: 'textarea', required: true },
    { name: 'source_url', label: 'Source URL', type: 'url', placeholder: 'https://…' },
    { name: 'collected_on', label: 'Date collected', type: 'date' },
    { name: 'target_id', label: 'Target', type: 'ref', ref: 'targets' },
    { name: 'finding_id', label: 'Supports finding', type: 'ref', ref: 'findings' },
    { name: 'notes', label: 'Notes', type: 'textarea' },
  ],
  sources: [
    { name: 'url', label: 'URL', type: 'url', required: true, placeholder: 'https://…' },
    { name: 'title', label: 'Title', type: 'text', max: 200 },
    { name: 'notes', label: 'Notes', type: 'textarea' },
  ],
  notes: [{ name: 'body', label: 'Note', type: 'textarea', required: true }],
};

/** Defaults for a new item. Confidence starts low: it is never raised automatically. */
export function defaultsFor(section, today = todayIso()) {
  if (section === 'findings') {
    return { kind: 'observation', confidence: 'low', recorded_on: today };
  }
  if (section === 'evidence') return { collected_on: today };
  if (section === 'targets') return { kind: 'domain' };
  return {};
}

export function todayIso(now = new Date()) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/**
 * The JSON body for a create (only filled fields) or an edit (every field, so a cleared
 * field is cleared on the server). Text is trimmed; reference fields send '' to unlink.
 */
export function payloadFromForm(section, values, { editing = false } = {}) {
  const body = {};
  for (const field of FIELDS[section] || []) {
    const raw = values[field.name];
    const value = typeof raw === 'string' ? raw.trim() : raw ?? '';
    if (value === '' && !editing) continue;
    body[field.name] = value;
  }
  return body;
}

/** First problem with a form's values, or '' if none (the server re-checks everything). */
export function validateForm(section, values) {
  for (const field of FIELDS[section] || []) {
    const value = String(values[field.name] ?? '').trim();
    if (field.required && !value) return `${field.label} is required.`;
    if (field.max && value.length > field.max) {
      return `${field.label} is longer than ${field.max} characters.`;
    }
    if (field.type === 'url' && value && !safeHttpUrl(value)) {
      return `${field.label} must be an http:// or https:// URL.`;
    }
  }
  return '';
}

/** Findings grouped by kind, in a fixed order; unknown kinds fall under observations. */
export function groupFindings(findings) {
  const groups = Object.fromEntries(FINDING_KINDS.map((k) => [k, []]));
  for (const f of findings || []) (groups[f.kind] || groups.observation).push(f);
  return groups;
}

/** A readable message from a failed API response body. */
export function apiErrorMessage(status, body) {
  const detail = body && body.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail
      .map((d) => {
        const where = Array.isArray(d.loc) ? d.loc.filter((p) => p !== 'body').join('.') : '';
        return where ? `${where}: ${d.msg}` : d.msg;
      })
      .join('; ');
  }
  return `Request failed (HTTP ${status}).`;
}

export function formatTimestamp(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleString();
}

export function targetLabel(kind, value) {
  return kind && value ? `${kind}: ${value}` : '';
}

/** Deleting an investigation requires typing its exact title. */
export function deleteConfirmed(title, typed) {
  return typeof typed === 'string' && typed.trim() === String(title).trim() && typed.trim() !== '';
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (!res.ok) throw new Error(apiErrorMessage(res.status, data));
  return data;
}

/** Element builder: attrs are properties/attributes; children are nodes or text. */
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (key === 'text') node.textContent = value;
    else node.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function link(url) {
  const safe = safeHttpUrl(url || '');
  if (!safe) return url ? el('span', { class: 'mono', text: url }) : null;
  return el('a', { href: safe, target: '_blank', rel: 'noopener noreferrer', class: 'mono' }, url);
}

export function init(root = document) {
  const state = { list: [], current: null, tab: 'overview', editing: null, error: '' };
  const $ = (id) => root.getElementById(id);

  function setError(message) {
    state.error = message || '';
    const box = $('ws-error');
    box.textContent = state.error;
    box.hidden = !state.error;
  }

  async function guard(fn) {
    try {
      setError('');
      return await fn();
    } catch (err) {
      setError(err.message || String(err));
      return undefined;
    }
  }

  async function loadList() {
    await guard(async () => {
      state.list = (await api('GET', '/api/investigations')).investigations;
    });
    renderList();
  }

  async function open(id, tab = 'overview') {
    const data = await guard(() => api('GET', `/api/investigations/${encodeURIComponent(id)}`));
    if (!data) return;
    state.current = data;
    state.tab = tab;
    state.editing = null;
    history.replaceState(null, '', `#${id}`);
    render();
  }

  async function refresh() {
    if (state.current) await open(state.current.id, state.tab);
    await loadList();
  }

  // -- list ------------------------------------------------------------------

  function renderList() {
    const list = $('ws-list');
    list.replaceChildren();
    if (!state.list.length) {
      list.append(el('p', { class: 'muted', text: 'No investigations yet. Create one to start.' }));
    }
    for (const inv of state.list) {
      const total = Object.values(inv.counts || {}).reduce((a, b) => a + b, 0);
      list.append(
        el(
          'button',
          {
            class: 'inv' + (state.current && state.current.id === inv.id ? ' active' : ''),
            dataset: { testid: 'investigation', id: inv.id },
            onclick: () => open(inv.id),
          },
          el('span', { class: 'inv-title', text: inv.title }),
          el('span', { class: 'muted small', text: `Updated ${formatTimestamp(inv.updated_at)} · ${total} items` }),
        ),
      );
    }
  }

  function showCreate() {
    const form = buildForm(
      [
        { name: 'title', label: 'Title', type: 'text', required: true, max: 200 },
        { name: 'description', label: 'Description (optional)', type: 'textarea' },
      ],
      {},
      {
        submitLabel: 'Create investigation',
        testid: 'create-form',
        onSubmit: async (values) => {
          if (!values.title.trim()) return 'Title is required.';
          const created = await guard(() =>
            api('POST', '/api/investigations', {
              title: values.title.trim(),
              description: values.description.trim(),
            }),
          );
          if (!created) return state.error;
          $('ws-create').replaceChildren();
          await loadList();
          await open(created.id);
          return '';
        },
        onCancel: () => $('ws-create').replaceChildren(),
      },
    );
    $('ws-create').replaceChildren(form);
    form.querySelector('input').focus();
  }

  // -- forms -----------------------------------------------------------------

  function refOptions(ref) {
    const items = (state.current && state.current[ref]) || [];
    if (ref === 'targets') return items.map((t) => [t.id, targetLabel(t.kind, t.value)]);
    if (ref === 'findings') return items.map((f) => [f.id, f.title]);
    return [];
  }

  function buildForm(fields, values, { submitLabel, onSubmit, onCancel, testid }) {
    const inputs = {};
    const message = el('p', { class: 'form-error', hidden: true });
    const rows = fields.map((field) => {
      let input;
      const id = `f-${testid}-${field.name}`;
      if (field.type === 'textarea') {
        input = el('textarea', { id, rows: 3 });
      } else if (field.type === 'select' || field.type === 'ref') {
        input = el('select', { id });
        if (field.type === 'ref') input.append(el('option', { value: '', text: '— none —' }));
        const options =
          field.type === 'ref' ? refOptions(field.ref) : field.options.map((o) => [o, o]);
        for (const [value, label] of options) input.append(el('option', { value, text: label }));
      } else {
        input = el('input', {
          id,
          type: field.type === 'url' ? 'url' : field.type,
          maxlength: field.max,
          placeholder: field.placeholder,
        });
        if (field.type === 'url' && field.name === 'source_url') {
          input.setAttribute('list', 'ws-source-urls');
        }
      }
      input.name = field.name;
      input.value = values[field.name] ?? '';
      if (field.required) input.required = true;
      inputs[field.name] = input;
      return el('label', { class: 'field', for: id }, el('span', { text: field.label }), input);
    });
    const form = el(
      'form',
      { class: 'ws-form', dataset: { testid }, novalidate: true },
      ...rows,
      message,
      el(
        'div',
        { class: 'actions' },
        el('button', { type: 'submit', class: 'primary', text: submitLabel }),
        onCancel ? el('button', { type: 'button', text: 'Cancel', onclick: onCancel }) : null,
      ),
    );
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const current = Object.fromEntries(
        Object.entries(inputs).map(([name, input]) => [name, input.value]),
      );
      const problem = await onSubmit(current);
      message.textContent = problem || '';
      message.hidden = !problem;
    });
    return form;
  }

  function sectionForm(section, item) {
    const editing = !!item;
    const values = editing ? { ...item } : defaultsFor(section);
    return buildForm(FIELDS[section], values, {
      submitLabel: editing ? 'Save' : 'Add',
      testid: `${section}-${editing ? 'edit' : 'add'}-form`,
      onCancel: editing
        ? () => {
            state.editing = null;
            render();
          }
        : null,
      onSubmit: async (formValues) => {
        const problem = validateForm(section, formValues);
        if (problem) return problem;
        const body = payloadFromForm(section, formValues, { editing });
        const base = `/api/investigations/${state.current.id}/${section}`;
        const ok = await guard(() =>
          editing ? api('PATCH', `${base}/${item.id}`, body) : api('POST', base, body),
        );
        if (!ok) return state.error;
        state.editing = null;
        await refresh();
        return '';
      },
    });
  }

  async function removeItem(section, item, what) {
    if (!window.confirm(`Delete this ${what}? This cannot be undone.`)) return;
    const ok = await guard(() =>
      api('DELETE', `/api/investigations/${state.current.id}/${section}/${item.id}`),
    );
    if (ok) await refresh();
  }

  // -- workspace -------------------------------------------------------------

  function render() {
    renderList();
    const pane = $('ws-main');
    pane.replaceChildren();
    document.body.classList.toggle('has-current', !!state.current);
    if (!state.current) {
      pane.append(
        el(
          'div',
          { class: 'empty' },
          el('h2', { text: 'Research workspace' }),
          el('p', {
            text:
              'Organise an investigation: the targets you research, what you find, the sources ' +
              'and evidence behind it, and your notes. Everything is entered by you and stays ' +
              'in your data directory; nothing here contacts a target.',
          }),
        ),
      );
      return;
    }
    const inv = state.current;
    const datalist = el('datalist', { id: 'ws-source-urls' });
    for (const s of inv.sources) datalist.append(el('option', { value: s.url }));
    pane.append(
      datalist,
      el(
        'div',
        { class: 'ws-head' },
        el('button', { class: 'back', text: '← All investigations', onclick: () => {
          state.current = null;
          history.replaceState(null, '', '#');
          render();
        } }),
        el('h2', { dataset: { testid: 'ws-title' }, text: inv.title }),
      ),
      el(
        'nav',
        { class: 'tabs', role: 'tablist' },
        TABS.map((tab) => {
          const count = tab.id === 'overview' ? null : inv[tab.id].length;
          return el(
            'button',
            {
              role: 'tab',
              class: state.tab === tab.id ? 'active' : '',
              'aria-selected': state.tab === tab.id ? 'true' : 'false',
              dataset: { tab: tab.id },
              onclick: () => {
                state.tab = tab.id;
                state.editing = null;
                render();
              },
            },
            count === null ? tab.label : `${tab.label} (${count})`,
          );
        }),
      ),
      el('section', { class: 'tab-body' }, renderTab(inv)),
    );
  }

  function renderTab(inv) {
    switch (state.tab) {
      case 'targets':
        return renderSection('targets', 'target', inv.targets, (t) => [
          el('div', { class: 'card-title' }, el('span', { class: 'chip', text: t.kind }), ' ',
            el('span', { class: 'mono', text: t.value })),
          t.notes ? el('p', { class: 'pre', text: t.notes }) : null,
        ]);
      case 'findings':
        return renderFindings(inv);
      case 'evidence':
        return renderSection('evidence', 'evidence entry', inv.evidence, (e) => [
          el('p', { class: 'pre card-title', text: e.description }),
          meta([
            ['Collected', e.collected_on],
            ['Source', link(e.source_url)],
            ['Target', targetLabel(e.target_kind, e.target_value)],
            ['Supports finding', e.finding_title],
          ]),
          e.notes ? el('p', { class: 'pre muted', text: e.notes }) : null,
        ]);
      case 'sources':
        return renderSection('sources', 'source', inv.sources, (s) => [
          el('div', { class: 'card-title' }, link(s.url)),
          s.title ? el('p', { text: s.title }) : null,
          meta([
            ['Used by', `${s.finding_count} finding(s), ${s.evidence_count} evidence entr${s.evidence_count === 1 ? 'y' : 'ies'}`],
          ]),
          s.notes ? el('p', { class: 'pre muted', text: s.notes }) : null,
        ], 'Findings and evidence with a source URL add it here automatically.');
      case 'notes':
        return renderSection('notes', 'note', inv.notes, (n) => [
          el('p', { class: 'pre', text: n.body }),
          meta([['Updated', formatTimestamp(n.updated_at)]]),
        ]);
      default:
        return renderOverview(inv);
    }
  }

  function meta(pairs) {
    const shown = pairs.filter(([, v]) => v);
    if (!shown.length) return null;
    return el(
      'dl',
      { class: 'meta' },
      shown.map(([k, v]) => [el('dt', { text: k }), el('dd', {}, v)]),
    );
  }

  function itemCard(section, what, item, body) {
    if (state.editing === item.id) {
      return el('div', { class: 'card editing' }, sectionForm(section, item));
    }
    return el(
      'article',
      { class: 'card', dataset: { testid: `${section}-item`, id: item.id } },
      ...body(item),
      el(
        'div',
        { class: 'actions' },
        el('button', { text: 'Edit', onclick: () => {
          state.editing = item.id;
          render();
        } }),
        el('button', { class: 'danger', text: 'Delete', onclick: () => removeItem(section, item, what) }),
      ),
    );
  }

  function addBlock(section, what, hint) {
    return el(
      'details',
      { class: 'add', open: (state.current[section] || []).length === 0 },
      el('summary', { text: `Add ${what}` }),
      hint ? el('p', { class: 'muted small', text: hint }) : null,
      sectionForm(section, null),
    );
  }

  function renderSection(section, what, items, body, hint) {
    const wrap = el('div', {}, addBlock(section, what, hint));
    if (!items.length) wrap.append(el('p', { class: 'muted', text: `No ${section} yet.` }));
    for (const item of items) wrap.append(itemCard(section, what, item, body));
    return wrap;
  }

  function renderFindings(inv) {
    const wrap = el(
      'div',
      {},
      addBlock('findings', 'finding',
        'Record the type honestly: an observation is what a source shows; assumptions and ' +
        'conclusions are yours. Confidence starts at low — raise it only when the evidence supports it.'),
    );
    if (!inv.findings.length) wrap.append(el('p', { class: 'muted', text: 'No findings yet.' }));
    const groups = groupFindings(inv.findings);
    for (const kind of FINDING_KINDS) {
      if (!groups[kind].length) continue;
      wrap.append(el('h3', { class: `group ${kind}`, text: FINDING_KIND_LABELS[kind] }));
      for (const f of groups[kind]) {
        wrap.append(
          itemCard('findings', 'finding', f, () => [
            el('div', { class: 'card-title' },
              el('span', { class: `conf ${f.confidence}`, text: `${f.confidence} confidence` }), ' ',
              el('strong', { text: f.title })),
            f.description ? el('p', { class: 'pre', text: f.description }) : null,
            meta([
              ['Recorded', f.recorded_on],
              ['Source', link(f.source_url)],
              ['Target', targetLabel(f.target_kind, f.target_value)],
            ]),
            f.notes ? el('p', { class: 'pre muted' }, el('em', { text: 'Notes: ' }), f.notes) : null,
          ]),
        );
      }
    }
    return wrap;
  }

  function renderOverview(inv) {
    if (state.editing === 'overview') {
      return buildForm(
        [
          { name: 'title', label: 'Title', type: 'text', required: true, max: 200 },
          { name: 'description', label: 'Description', type: 'textarea' },
        ],
        inv,
        {
          submitLabel: 'Save',
          testid: 'overview-edit-form',
          onCancel: () => {
            state.editing = null;
            render();
          },
          onSubmit: async (values) => {
            if (!values.title.trim()) return 'Title is required.';
            const ok = await guard(() =>
              api('PATCH', `/api/investigations/${inv.id}`, {
                title: values.title.trim(),
                description: values.description.trim(),
              }),
            );
            if (!ok) return state.error;
            state.editing = null;
            await refresh();
            return '';
          },
        },
      );
    }
    return el(
      'div',
      {},
      inv.description
        ? el('p', { class: 'pre', dataset: { testid: 'ws-description' }, text: inv.description })
        : el('p', { class: 'muted', text: 'No description.' }),
      meta([
        ['Created', formatTimestamp(inv.created_at)],
        ['Updated', formatTimestamp(inv.updated_at)],
        ['Targets', String(inv.targets.length)],
        ['Findings', String(inv.findings.length)],
        ['Evidence', String(inv.evidence.length)],
        ['Sources', String(inv.sources.length)],
        ['Notes', String(inv.notes.length)],
      ]),
      el(
        'div',
        { class: 'actions' },
        el('button', { text: 'Rename / edit description', onclick: () => {
          state.editing = 'overview';
          render();
        } }),
        el('button', { class: 'danger', dataset: { testid: 'delete-investigation' },
          text: 'Delete investigation', onclick: () => confirmDelete(inv) }),
      ),
    );
  }

  function confirmDelete(inv) {
    const dialog = $('ws-delete');
    const input = $('ws-delete-input');
    $('ws-delete-title').textContent = inv.title;
    input.value = '';
    $('ws-delete-confirm').disabled = true;
    input.oninput = () => {
      $('ws-delete-confirm').disabled = !deleteConfirmed(inv.title, input.value);
    };
    $('ws-delete-cancel').onclick = () => dialog.close();
    $('ws-delete-confirm').onclick = async () => {
      if (!deleteConfirmed(inv.title, input.value)) return;
      dialog.close();
      const ok = await guard(() => api('DELETE', `/api/investigations/${inv.id}`));
      if (!ok) return;
      state.current = null;
      history.replaceState(null, '', '#');
      await loadList();
      render();
    };
    dialog.showModal();
    input.focus();
  }

  $('ws-new').addEventListener('click', showCreate);
  render();
  loadList().then(() => {
    const id = location.hash.slice(1);
    if (/^[0-9a-f]{32}$/.test(id)) open(id);
  });
}
