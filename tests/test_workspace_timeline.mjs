/**
 * Unit tests for the workspace timeline helpers (openosint/web/static/workspace-timeline.js).
 * Run: node tests/test_workspace_timeline.mjs
 */
import { register } from 'node:module';

register('./_static_resolver_loader.mjs', import.meta.url);

const t = await import('../openosint/web/static/workspace-timeline.js');

let passed = 0, failed = 0;
function assert(cond, label) {
  if (cond) { console.log(`  ✓ ${label}`); passed++; }
  else { console.error(`  ✗ ${label}`); failed++; }
}
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);

const events = [
  { id: 'c', title: 'Campaign', sort_key: '2026-03-03T00:00', start_date: '2026-03-03', end_date: '2026-03-10', date_precision: 'range', category: 'publication', provenance: 'hypothesis', links: [], created_at: '3' },
  { id: 'a', title: 'Account', sort_key: '2026-02-01T00:00', start_date: '2026-02', date_precision: 'approximate', category: 'account_activity', provenance: 'reported', links: [], created_at: '1' },
  { id: 'r', title: 'Registered', sort_key: '2026-03-02T04:30', start_date: '2026-03-01', start_time: '23:30', timezone: 'America/New_York', date_precision: 'exact', category: 'registration', provenance: 'observation', description: 'Registry shows it', links: [{ kind: 'evidence', id: 'e1' }, { kind: 'entity', id: 'n1' }], created_at: '2' },
];

console.log('\nformatEventDate');
assert(t.formatEventDate(events[2]) === '2026-03-01 23:30 (America/New_York)', 'exact with time and zone');
assert(t.formatEventDate(events[1]) === '≈ 2026-02', 'approximate marked');
assert(t.formatEventDate(events[0]) === '2026-03-03 → 2026-03-10', 'range');
assert(t.formatEventDate({ start_date: '2026-03-01', date_precision: 'exact', timezone: 'UTC' }) === '2026-03-01', 'zone hidden for date-only events');

console.log('\nsortEvents');
assert(eq(t.sortEvents(events).map((e) => e.id), ['a', 'r', 'c']), 'ascending by sort key');
assert(eq(t.sortEvents(events, 'desc').map((e) => e.id), ['c', 'r', 'a']), 'descending');
assert(eq(t.sortEvents([{ id: 2, sort_key: 'x', created_at: '2' }, { id: 1, sort_key: 'x', created_at: '1' }]).map((e) => e.id), [1, 2]), 'ties by creation');
assert(events[0].id === 'c', 'input array not mutated');

console.log('\nfilterEvents');
assert(eq(t.filterEvents(events, { category: 'publication' }).map((e) => e.id), ['c']), 'by category');
assert(eq(t.filterEvents(events, { provenance: 'reported' }).map((e) => e.id), ['a']), 'by provenance');
assert(eq(t.filterEvents(events, { entityId: 'n1' }).map((e) => e.id), ['r']), 'by linked entity');
assert(eq(t.filterEvents(events, { evidenceOnly: true }).map((e) => e.id), ['r']), 'only events citing evidence');
assert(eq(t.filterEvents(events, { from: '2026-03-01' }).map((e) => e.id).sort(), ['c', 'r']), 'from date');
assert(eq(t.filterEvents(events, { to: '2026-02-28' }).map((e) => e.id), ['a']), 'to date');
assert(eq(t.filterEvents(events, { text: 'registry' }).map((e) => e.id), ['r']), 'text search in description');
assert(t.filterEvents(events, {}).length === 3 && t.filterEvents(undefined, {}).length === 0, 'no filters / no events');

console.log('\ngroupByMonth and timeBetween');
const groups = t.groupByMonth(t.sortEvents(events));
assert(eq(groups.map((g) => [g.label, g.events.length]), [['2026-02', 1], ['2026-03', 2]]), 'month headings');
assert(t.timeBetween({ sort_key: '2026-03-01T10:00', timezone: 'UTC' }, { sort_key: '2026-03-01T10:45', timezone: 'UTC' }) === '45 min later', 'minutes');
assert(t.timeBetween({ sort_key: '2026-03-01T00:00' }, { sort_key: '2026-03-06T00:00' }) === '5 days later', 'days');
assert(t.timeBetween({ sort_key: '2026-03-06T00:00' }, { sort_key: '2026-03-01T00:00' }) === '5 days earlier', 'earlier');
assert(t.timeBetween(events[1], events[2]).startsWith('≈'), 'approximate dates make the gap approximate');
assert(t.timeBetween({ sort_key: '2026-03-01T00:00', timezone: 'UTC' }, { sort_key: '2026-03-02T00:00' }).startsWith('≈'), 'mixing zoned and unzoned times is approximate');
assert(t.timeBetween({ sort_key: 'bad' }, { sort_key: 'worse' }) === '', 'bad keys give no gap');

console.log('\nvalidateEvent');
const ok = { title: 'x', date_precision: 'exact', start_date: '2026-03-01' };
assert(t.validateEvent(ok) === '', 'date-only exact event');
assert(t.validateEvent({ ...ok, title: ' ' }).includes('Title'), 'title required');
assert(t.validateEvent({ ...ok, start_date: '2026-03' }).includes('YYYY-MM-DD'), 'partial date needs approximate');
assert(t.validateEvent({ ...ok, date_precision: 'approximate', start_date: '2026' }) === '', 'approximate year');
assert(t.validateEvent({ ...ok, date_precision: 'approximate', start_date: '2026-03', start_time: '10:00' }).includes('full date'), 'time needs full date');
assert(t.validateEvent({ ...ok, date_precision: 'range' }).includes('end date'), 'range needs end');
assert(t.validateEvent({ ...ok, date_precision: 'range', end_date: '2026-02-01' }).includes('before'), 'range order');
assert(t.validateEvent({ ...ok, date_precision: 'range', end_date: '2026-03-01', start_time: '18:00', end_time: '09:00' }).includes('before'), 'same-day range order');

console.log('\neventPayload / eventFormValues');
const values = { ...ok, start_time: '', date_precision: 'exact', end_date: '2026-04-01', link_evidence: ['e1'], link_entity: ['n1', 'n2'], link_target: [] };
const body = t.eventPayload(values);
assert(!('end_date' in body) && !('start_time' in body), 'end fields dropped unless a range; empty fields omitted');
assert(eq(body.links, [{ kind: 'entity', id: 'n1' }, { kind: 'entity', id: 'n2' }, { kind: 'evidence', id: 'e1' }]), 'link pickers become one links list');
assert(t.eventPayload({ ...ok, notes: '' }, { editing: true }).notes === '', 'editing sends cleared fields');
const fv = t.eventFormValues(events[2]);
assert(eq(fv.link_evidence, ['e1']) && eq(fv.link_entity, ['n1']) && eq(fv.link_target, []), 'links split back into pickers');

console.log('\nvalidateCorrelation');
assert(t.validateCorrelation({ title: 'x', event_ids: ['a'] }).includes('two'), 'two events');
assert(t.validateCorrelation({ title: 'x', event_ids: ['a', 'b'] }) === '', 'hypothesis with two events');
assert(t.validateCorrelation({ title: 'x', event_ids: ['a', 'b'], status: 'documented' }).includes('cite'), 'documented needs citation');
assert(t.validateCorrelation({ title: 'x', event_ids: ['a', 'b'], status: 'documented', evidence_ids: ['e'] }) === '', 'documented with evidence');
assert(!t.EVENT_PROVENANCE.includes('verified'), 'no "verified" provenance');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
