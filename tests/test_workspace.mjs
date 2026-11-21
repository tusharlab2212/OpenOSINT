/**
 * Unit tests for the research workspace page's pure helpers (openosint/web/static/workspace.js).
 * Run: node tests/test_workspace.mjs
 */
import { register } from 'node:module';

register('./_static_resolver_loader.mjs', import.meta.url);

const ws = await import('../openosint/web/static/workspace.js');

let passed = 0, failed = 0;
function assert(cond, label) {
  if (cond) { console.log(`  ✓ ${label}`); passed++; }
  else { console.error(`  ✗ ${label}`); failed++; }
}
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);

console.log('\ndefaults: confidence is never preset above low');
assert(ws.defaultsFor('findings', '2026-01-02').confidence === 'low', 'new finding starts at low confidence');
assert(ws.defaultsFor('findings', '2026-01-02').kind === 'observation', 'new finding is an observation');
assert(ws.defaultsFor('findings', '2026-01-02').recorded_on === '2026-01-02', 'recorded today');
assert(ws.defaultsFor('evidence', '2026-01-02').collected_on === '2026-01-02', 'evidence collected today');
assert(ws.todayIso(new Date(2026, 0, 5)) === '2026-01-05', 'todayIso pads month and day');

console.log('\npayloadFromForm');
assert(
  eq(ws.payloadFromForm('findings', { title: '  MX record ', confidence: 'medium', kind: 'observation', source_url: '', target_id: '', description: '', notes: '', recorded_on: '2026-01-02' }),
     { title: 'MX record', kind: 'observation', confidence: 'medium', recorded_on: '2026-01-02' }),
  'create sends only filled fields, trimmed',
);
const edit = ws.payloadFromForm('evidence', { description: 'Screenshot', source_url: '', target_id: '', finding_id: '', collected_on: '2026-01-02', notes: '' }, { editing: true });
assert(edit.source_url === '' && edit.target_id === '' && edit.finding_id === '', 'edit sends cleared fields so links are removed');
assert(!('unknown' in ws.payloadFromForm('notes', { body: 'x', unknown: 'y' })), 'unknown fields are dropped');

console.log('\nvalidateForm');
assert(ws.validateForm('findings', { title: '' }) === 'Title is required.', 'required title');
assert(ws.validateForm('findings', { title: 'x', kind: 'observation', confidence: 'low', source_url: 'javascript:alert(1)' }).includes('http'), 'javascript: source URL rejected');
assert(ws.validateForm('sources', { url: 'ftp://example.com' }) !== '', 'non-http source rejected');
assert(ws.validateForm('sources', { url: 'https://example.com/page' }) === '', 'https source accepted');
assert(ws.validateForm('targets', { kind: 'domain', value: 'x'.repeat(501) }).includes('longer'), 'over-long identifier rejected');
assert(ws.validateForm('notes', { body: 'hello' }) === '', 'valid note');

console.log('\ngroupFindings keeps observations apart from assumptions and conclusions');
const groups = ws.groupFindings([
  { id: 1, kind: 'conclusion' }, { id: 2, kind: 'observation' }, { id: 3, kind: 'assumption' }, { id: 4, kind: 'weird' },
]);
assert(eq(Object.keys(groups), ['observation', 'assumption', 'conclusion']), 'fixed group order');
assert(eq(groups.observation.map((f) => f.id), [2, 4]), 'unknown kind falls under observations');
assert(groups.assumption.length === 1 && groups.conclusion.length === 1, 'assumption and conclusion grouped');
assert(eq(ws.groupFindings(undefined).observation, []), 'no findings: empty groups');

console.log('\napiErrorMessage');
assert(ws.apiErrorMessage(404, { detail: 'investigation not found' }) === 'investigation not found', 'string detail');
assert(ws.apiErrorMessage(422, { detail: [{ loc: ['body', 'confidence'], msg: 'bad value' }] }) === 'confidence: bad value', 'pydantic detail list');
assert(ws.apiErrorMessage(500, null).includes('500'), 'no body: status shown');

console.log('\ndeleteConfirmed requires the exact title');
assert(ws.deleteConfirmed('Case A', 'Case A'), 'exact title confirms');
assert(ws.deleteConfirmed('Case A', '  Case A  '), 'surrounding spaces ignored');
assert(!ws.deleteConfirmed('Case A', 'case a'), 'case must match');
assert(!ws.deleteConfirmed('Case A', ''), 'empty does not confirm');

console.log('\nlabels');
assert(ws.targetLabel('domain', 'example.com') === 'domain: example.com', 'target label');
assert(ws.targetLabel(null, null) === '', 'no target: empty');
assert(ws.formatTimestamp('') === '' && ws.formatTimestamp('nonsense') === 'nonsense', 'timestamps never throw');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
