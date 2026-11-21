/**
 * workspace-timeline.js — pure helpers for the research workspace's timeline.
 *
 * Formats, sorts, filters and groups events the investigator entered, and builds the
 * request bodies for events and correlations. Nothing here dates, links, verifies or
 * correlates events on its own; the only arithmetic is the time between two events.
 */

export const EVENT_CATEGORIES = [
  'communication', 'registration', 'publication', 'account_activity', 'infrastructure_change',
  'transaction', 'meeting', 'travel', 'legal', 'other',
];

export const EVENT_PROVENANCE = ['reported', 'observation', 'hypothesis', 'conclusion'];
export const EVENT_PROVENANCE_LABELS = {
  reported: 'Source-reported',
  observation: 'Analyst observation',
  hypothesis: 'Hypothesis',
  conclusion: 'Analyst conclusion',
};

export const DATE_PRECISIONS = ['exact', 'approximate', 'range'];
export const DATE_PRECISION_LABELS = {
  exact: 'Exact date',
  approximate: 'Approximate (year, month or day)',
  range: 'Date range',
};

export const CORRELATION_STATUS_LABELS = {
  hypothesis: 'Analyst hypothesis',
  documented: 'Documented — cites a finding or evidence',
};

export const LINK_KINDS = ['target', 'entity', 'finding', 'evidence', 'source'];
export const LINK_LABELS = {
  target: 'Targets', entity: 'Entities', finding: 'Findings', evidence: 'Evidence', source: 'Sources',
};

export const COMMON_TIMEZONES = [
  'UTC', 'Europe/London', 'Europe/Paris', 'Europe/Berlin', 'Europe/Moscow', 'America/New_York',
  'America/Chicago', 'America/Los_Angeles', 'America/Sao_Paulo', 'Asia/Dubai', 'Asia/Kolkata',
  'Asia/Shanghai', 'Asia/Tokyo', 'Australia/Sydney', 'Africa/Lagos',
];

/** How many events are drawn at once; "Show more" adds another page. */
export const PAGE_SIZE = 100;

export function categoryLabel(category) {
  const text = String(category || 'other').replace(/_/g, ' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** The event's date as entered, marked as exact, approximate or a range. */
export function formatEventDate(ev) {
  const at = (day, time) => (time ? `${day} ${time}` : day);
  const zone = ev.timezone && (ev.start_time || ev.end_time) ? ` (${ev.timezone})` : '';
  if (ev.date_precision === 'approximate') return `≈ ${at(ev.start_date, ev.start_time)}${zone}`;
  if (ev.date_precision === 'range') {
    return `${at(ev.start_date, ev.start_time)} → ${at(ev.end_date, ev.end_time)}${zone}`;
  }
  return `${at(ev.start_date, ev.start_time)}${zone}`;
}

/** A stable chronological order (the server's sort key, then creation). */
export function sortEvents(events, direction = 'asc') {
  const sorted = [...(events || [])].sort(
    (a, b) => (a.sort_key < b.sort_key ? -1 : a.sort_key > b.sort_key ? 1 : 0)
      || String(a.created_at).localeCompare(String(b.created_at)),
  );
  return direction === 'desc' ? sorted.reverse() : sorted;
}

/**
 * Filters: category, provenance, entityId, evidenceOnly (cites evidence), from / to
 * (YYYY-MM-DD, compared with the event's sort key), text (title, description, notes).
 */
export function filterEvents(events, f = {}) {
  const text = String(f.text || '').trim().toLowerCase();
  return (events || []).filter((ev) => {
    if (f.category && ev.category !== f.category) return false;
    if (f.provenance && ev.provenance !== f.provenance) return false;
    const links = ev.links || [];
    if (f.entityId && !links.some((l) => l.kind === 'entity' && l.id === f.entityId)) return false;
    if (f.evidenceOnly && !links.some((l) => l.kind === 'evidence')) return false;
    const key = String(ev.sort_key || '');
    if (f.from && key.slice(0, 10) < f.from) return false;
    if (f.to && key.slice(0, 10) > f.to) return false;
    if (text && ![ev.title, ev.description, ev.notes].some((s) => String(s || '').toLowerCase().includes(text))) {
      return false;
    }
    return true;
  });
}

/** Consecutive groups by year and month of the start date, for headings. */
export function groupByMonth(events) {
  const groups = [];
  for (const ev of events || []) {
    const label = String(ev.start_date || '').length >= 7 ? ev.start_date.slice(0, 7) : String(ev.start_date || '');
    const last = groups[groups.length - 1];
    if (last && last.label === label) last.events.push(ev);
    else groups.push({ label, events: [ev] });
  }
  return groups;
}

/**
 * Time from one event's start to the next, from their sort keys. Plain arithmetic: it
 * says nothing about whether the events are connected. Approximate dates are flagged.
 */
export function timeBetween(a, b) {
  // Only well-formed keys: Date.parse accepts far too much ("bad:00Z" is a date in 2000).
  const t = (ev) => (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(String(ev.sort_key))
    ? Date.parse(`${ev.sort_key}:00Z`) : NaN);
  const ms = t(b) - t(a);
  if (!Number.isFinite(ms)) return '';
  const minutes = Math.round(Math.abs(ms) / 60000);
  let text;
  if (minutes < 60) text = `${minutes} min`;
  else if (minutes < 48 * 60) text = `${Math.round(minutes / 60)} h`;
  else text = `${Math.round(minutes / 1440)} days`;
  const approx = a.date_precision === 'approximate' || b.date_precision === 'approximate'
    || ((a.timezone || '') === '') !== ((b.timezone || '') === '');
  return `${approx ? '≈ ' : ''}${text} ${ms < 0 ? 'earlier' : 'later'}`;
}

/** First problem with an event form, or '' (the server re-checks everything). */
export function validateEvent(v) {
  if (!String(v.title || '').trim()) return 'Title is required.';
  const precision = v.date_precision || 'exact';
  const start = String(v.start_date || '').trim();
  const full = /^\d{4}-\d{2}-\d{2}$/;
  if (!start) return 'Start date is required.';
  if (precision === 'approximate' ? !/^\d{4}(-\d{2}(-\d{2})?)?$/.test(start) : !full.test(start)) {
    return precision === 'approximate'
      ? 'An approximate date is YYYY, YYYY-MM or YYYY-MM-DD.'
      : 'Start date must be YYYY-MM-DD.';
  }
  if (v.start_time && !full.test(start)) return 'A time needs a full date.';
  if (precision === 'range') {
    const end = String(v.end_date || '').trim();
    if (!full.test(end)) return 'A range needs an end date (YYYY-MM-DD).';
    if (end < start || (end === start && v.start_time && v.end_time && v.end_time < v.start_time)) {
      return 'The range ends before it starts.';
    }
  }
  return '';
}

/** The JSON body for an event form; the five link pickers become one `links` list. */
export function eventPayload(values, { editing = false } = {}) {
  const body = {};
  for (const key of ['title', 'category', 'provenance', 'date_precision', 'start_date', 'start_time',
    'end_date', 'end_time', 'timezone', 'description', 'notes']) {
    const value = String(values[key] ?? '').trim();
    if (value === '' && !editing) continue;
    body[key] = value;
  }
  if (body.date_precision !== 'range') {
    delete body.end_date;
    delete body.end_time;
  }
  body.links = LINK_KINDS.flatMap((kind) => (values[`link_${kind}`] || []).map((id) => ({ kind, id })));
  return body;
}

/** Form values for editing an event: its links split back into the five pickers. */
export function eventFormValues(ev) {
  const values = { ...ev };
  for (const kind of LINK_KINDS) {
    values[`link_${kind}`] = (ev.links || []).filter((l) => l.kind === kind).map((l) => l.id);
  }
  return values;
}

export function validateCorrelation(v) {
  if (!String(v.title || '').trim()) return 'Title is required.';
  const events = Array.isArray(v.event_ids) ? v.event_ids : [];
  if (events.length < 2) return 'Choose at least two events.';
  const evidence = Array.isArray(v.evidence_ids) ? v.evidence_ids : [];
  if (v.status === 'documented' && !v.finding_id && !evidence.length) {
    return 'A documented correlation must cite a finding or evidence. Otherwise keep it a hypothesis.';
  }
  return '';
}
