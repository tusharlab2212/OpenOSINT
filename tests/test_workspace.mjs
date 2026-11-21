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
assert(eq(Object.keys(groups), ['observation', 'reported', 'assumption', 'conclusion']), 'fixed group order, reported claims apart from observations');
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

console.log('\nprovenance and reliability');
assert(ws.groupFindings([{ id: 9, kind: 'reported' }]).reported.length === 1, 'reported claims grouped on their own');
assert(eq(ws.EVIDENCE_KINDS, ['unspecified', 'observation', 'reported']), 'evidence provenance kinds');
assert(ws.defaultsFor('evidence', '2026-01-02').kind === 'observation', 'new evidence preselects direct observation');
assert(ws.defaultsFor('sources').reliability === 'unassessed', 'a new source starts unassessed');
assert(ws.reliabilityLabel('B') === 'B — Usually reliable', 'reliability label');
assert(ws.reliabilityLabel('Z') === 'Not assessed' && ws.reliabilityLabel(undefined) === 'Not assessed', 'unknown rating shown as not assessed');
assert(ws.validateForm('sources', { url: 'https://example.com/', reliability: 'B', reliability_rationale: '' }).includes('Why this rating'), 'rating without rationale rejected');
assert(ws.validateForm('sources', { url: 'https://example.com/', reliability: 'B', reliability_rationale: 'Official registry' }) === '', 'rating with rationale accepted');
assert(ws.validateForm('sources', { url: 'https://example.com/', reliability: 'unassessed' }) === '', 'unassessed needs no rationale');
assert(ws.validateForm('sources', { url: 'https://example.com/', original_url: 'javascript:x' }).includes('Original URL'), 'original URL must be http(s)');
const srcFields = ws.FIELDS.sources.map((f) => f.name);
for (const name of ['source_type', 'original_url', 'published_on', 'accessed_on', 'reliability', 'reliability_rationale', 'title']) {
  assert(srcFields.includes(name), `source form has ${name}`);
}
assert(ws.FIELDS.sources.find((f) => f.name === 'url').lockedOnEdit === true, 'source URL is read-only when editing');

console.log('\ntraceability');
const inv = {
  sources: [{ id: 's1', url: 'https://example.com/a' }, { id: 's2', url: 'https://example.com/b' }],
  findings: [
    { id: 'f1', title: 'cites s1', source_id: 's1' },
    { id: 'f2', title: 'via evidence', source_id: null },
    { id: 'f3', title: 'cites s1 and has its evidence', source_id: 's1' },
  ],
  evidence: [
    { id: 'e1', source_id: 's1', finding_id: 'f2' },
    { id: 'e2', source_id: 's1', finding_id: 'f3' },
    { id: 'e3', source_id: 's2', finding_id: 'f2' },
  ],
};
const tr = ws.sourceTrace(inv, 's1');
assert(eq(tr.findings.map((f) => f.id), ['f1', 'f3']), 'findings citing the source directly');
assert(eq(tr.evidence.map((e) => e.id), ['e1', 'e2']), 'evidence from the source');
assert(eq(tr.viaEvidence.map((f) => f.id), ['f2']), 'findings supported through its evidence, without duplicates');
const sup = ws.findingSupport(inv, 'f2');
assert(eq(sup.map((e) => [e.id, e.source.url]), [['e1', 'https://example.com/a'], ['e3', 'https://example.com/b']]), 'supporting evidence with its sources');
assert(eq(ws.sourceTrace({}, 'x'), { findings: [], evidence: [], viaEvidence: [] }), 'empty investigation traces to nothing');

console.log('\nreport settings');
assert(!ws.DEFAULT_REPORT_SECTIONS.includes('notes') && ws.DEFAULT_REPORT_SECTIONS.length === 9, 'notes are opt-in');
const url = new URL(ws.reportUrl('abc', { title: ' My report ', subtitle: '', sections: ['notes', 'findings', 'bogus'] }), 'http://x');
assert(url.pathname === '/api/investigations/abc/report', 'local report path');
assert(url.searchParams.get('sections') === 'findings,notes', 'known sections only, in report order');
assert(url.searchParams.get('title') === 'My report' && !url.searchParams.has('subtitle'), 'title trimmed; empty subtitle omitted');
assert(url.searchParams.get('format') === 'html' && !url.searchParams.has('download'), 'html by default, inline');
const pdf = new URL(ws.reportUrl('a/b?c', { format: 'pdf', download: true }), 'http://x');
assert(pdf.pathname === '/api/investigations/a%2Fb%3Fc/report' && pdf.searchParams.get('format') === 'pdf', 'id encoded; pdf format');
assert(pdf.searchParams.get('download') === 'true', 'download flag');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
