/**
 * Unit tests for the workspace entity graph helpers (openosint/web/static/workspace-graph.js).
 * Run: node tests/test_workspace_graph.mjs
 */
import { register } from 'node:module';

register('./_static_resolver_loader.mjs', import.meta.url);

const g = await import('../openosint/web/static/workspace-graph.js');

let passed = 0, failed = 0;
function assert(cond, label) {
  if (cond) { console.log(`  ✓ ${label}`); passed++; }
  else { console.error(`  ✗ ${label}`); failed++; }
}
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);

const inv = {
  entities: [
    { id: 'a', kind: 'person', label: 'Jane Example', pos_x: 10, pos_y: 20 },
    { id: 'b', kind: 'organization', label: 'Example Org', pos_x: null, pos_y: null },
    { id: 'c', kind: 'martian', label: '<img src=x onerror=alert(1)>' },
  ],
  relationships: [
    { id: 'r1', from_entity_id: 'a', to_entity_id: 'b', label: 'works for', status: 'hypothesis', confidence: 'low' },
    { id: 'r2', from_entity_id: 'b', to_entity_id: 'c', label: 'owns', status: 'documented', confidence: 'high' },
    { id: 'r3', from_entity_id: 'b', to_entity_id: 'zzz', label: 'dangling', status: 'hypothesis', confidence: 'low' },
    { id: 'r4', from_entity_id: 'a', to_entity_id: 'c', label: 'x', status: 'documented', confidence: 'weird', unsupported: true },
  ],
};

console.log('\ngraphElements');
const els = g.graphElements(inv);
const nodes = els.filter((e) => e.group === 'nodes');
const edges = els.filter((e) => e.group === 'edges');
assert(nodes.length === 3, 'one node per entity');
assert(eq(nodes[0].position, { x: 10, y: 20 }), 'saved position used');
assert(nodes[1].position === undefined, 'no position when none saved');
assert(nodes[0].data.color === g.ENTITY_STYLE.person.color && nodes[0].data.shape === 'ellipse', 'type colour and shape');
assert(nodes[2].classes.includes('kind-custom') && nodes[2].data.shape === g.ENTITY_STYLE.custom.shape, 'unknown type falls back to custom');
assert(nodes[2].data.label === '<img src=x onerror=alert(1)>', 'labels passed through as data, never as markup');
assert(eq(edges.map((e) => e.data.id), ['r1', 'r2', 'r4']), 'edges to missing entities are dropped');
assert(edges[0].classes.includes('hypothesis') && !edges[0].classes.includes('documented'), 'hypothesis edge class');
assert(edges[1].classes.includes('documented') && edges[1].data.width > edges[0].data.width, 'documented edge, wider for high confidence');
assert(edges[2].classes.includes('unsupported') && edges[2].classes.includes('conf-low'), 'unsupported flagged; unknown confidence treated as low');
assert(eq(g.graphElements(undefined), []), 'no investigation: no elements');

console.log('\nwithDistinctPositions');
const placed = g.withDistinctPositions(g.graphElements({
  entities: [
    { id: 'p', kind: 'person', label: 'P', pos_x: 5, pos_y: 5 },
    { id: 'q', kind: 'person', label: 'Q', pos_x: 5, pos_y: 5 },
    { id: 'u1', kind: 'person', label: 'U1' },
    { id: 'u2', kind: 'person', label: 'U2' },
  ],
  relationships: [{ id: 'r', from_entity_id: 'u1', to_entity_id: 'u2', label: 'x', status: 'hypothesis', confidence: 'low' }],
}));
const pts = placed.filter((e) => e.group === 'nodes').map((e) => `${e.position.x},${e.position.y}`);
assert(new Set(pts).size === 4, 'every node ends up at a distinct point');
assert(pts[0] === '5,5', 'the first saved position is kept exactly');
assert(placed.find((e) => e.data.id === 'u1').position && placed.find((e) => e.data.id === 'u2').position, 'unplaced nodes get provisional positions');
assert(placed.some((e) => e.group === 'edges'), 'edges untouched');

console.log('\nlayout and performance');
assert(eq(g.unplacedIds(inv), ['b', 'c']), 'entities without a saved position');
assert(g.performanceOptions(50).hideEdgesOnViewport === false, 'small graphs keep full rendering');
assert(g.performanceOptions(1000).hideEdgesOnViewport === true && g.performanceOptions(1000).textureOnViewport === true, 'large graphs simplify while panning');
const style = g.graphStyle(1000);
assert(style.find((s) => s.selector === 'node').style['min-zoomed-font-size'] === 10, 'large graphs hide small labels');
assert(style.some((s) => s.selector === 'edge.hypothesis' && s.style['line-style'] === 'dashed'), 'hypotheses are dashed');
assert(style.some((s) => s.selector === 'edge.documented' && s.style['line-style'] === 'solid'), 'documented edges are solid');

console.log('\nvalidateRelationship');
const base = { from_entity_id: 'a', to_entity_id: 'b', label: 'works for', status: 'hypothesis', evidence_ids: [] };
assert(g.validateRelationship(base) === '', 'hypothesis needs no citation');
assert(g.validateRelationship({ ...base, to_entity_id: 'a' }).includes('different'), 'no self-links');
assert(g.validateRelationship({ ...base, from_entity_id: '' }).includes('both'), 'both ends required');
assert(g.validateRelationship({ ...base, label: '  ' }).includes('required'), 'label required');
assert(g.validateRelationship({ ...base, status: 'documented' }).includes('cite'), 'documented needs a citation');
assert(g.validateRelationship({ ...base, status: 'documented', evidence_ids: ['e1'] }) === '', 'documented with evidence');
assert(g.validateRelationship({ ...base, status: 'documented', finding_id: 'f1' }) === '', 'documented with a finding');

console.log('\nrelationshipsOf and presets');
assert(eq(g.relationshipsOf(inv, 'c').map((r) => r.id), ['r2', 'r4']), 'relationships touching an entity');
assert(g.RELATIONSHIP_STATUSES[0] === 'hypothesis', 'hypothesis listed first');
assert(g.RELATIONSHIP_PRESETS.includes('works for') && g.ENTITY_KINDS.length === 9, 'presets and entity types');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
