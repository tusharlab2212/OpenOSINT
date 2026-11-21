/**
 * workspace-graph.js — pure helpers for the research workspace's entity relationship graph.
 *
 * Turns the investigation's entities and relationships into Cytoscape elements and a
 * stylesheet. Labels are drawn by Cytoscape on a canvas (never parsed as HTML). Nothing here
 * creates an entity or a relationship: every one comes from what the investigator entered.
 */

export const ENTITY_KINDS = [
  'person', 'organization', 'username', 'domain', 'email', 'phone', 'ip', 'location', 'custom',
];

/** Colour and shape per entity type, so types stay distinguishable without reading labels. */
export const ENTITY_STYLE = {
  person: { color: '#58a6ff', shape: 'ellipse', label: 'Person' },
  organization: { color: '#d29922', shape: 'round-rectangle', label: 'Organization' },
  username: { color: '#3fb950', shape: 'round-tag', label: 'Username' },
  domain: { color: '#a371f7', shape: 'hexagon', label: 'Domain' },
  email: { color: '#f778ba', shape: 'round-diamond', label: 'Email' },
  phone: { color: '#56d4dd', shape: 'round-triangle', label: 'Phone' },
  ip: { color: '#db6d28', shape: 'octagon', label: 'IP address' },
  location: { color: '#e3b341', shape: 'star', label: 'Location' },
  custom: { color: '#8b949e', shape: 'rectangle', label: 'Custom' },
};

export const RELATIONSHIP_STATUSES = ['hypothesis', 'documented'];
export const STATUS_LABELS = {
  hypothesis: 'Hypothesis — not established',
  documented: 'Documented fact — cites a finding or evidence',
};

export const RELATIONSHIP_PRESETS = [
  'owns', 'operates', 'works for', 'member of', 'uses', 'registered', 'hosted on',
  'linked to', 'same as', 'communicated with', 'located in',
];

const EDGE_WIDTH = { low: 1.5, medium: 2.5, high: 4 };

/** Cytoscape elements for an investigation. Node positions come from what was saved. */
export function graphElements(inv) {
  const entities = (inv && inv.entities) || [];
  const ids = new Set(entities.map((e) => e.id));
  const nodes = entities.map((e) => {
    const style = ENTITY_STYLE[e.kind] || ENTITY_STYLE.custom;
    const node = {
      group: 'nodes',
      data: { id: e.id, label: e.label, kind: e.kind, color: style.color, shape: style.shape },
      classes: `entity kind-${ENTITY_STYLE[e.kind] ? e.kind : 'custom'}`,
    };
    if (Number.isFinite(e.pos_x) && Number.isFinite(e.pos_y)) {
      node.position = { x: e.pos_x, y: e.pos_y };
    }
    return node;
  });
  const edges = ((inv && inv.relationships) || [])
    .filter((r) => ids.has(r.from_entity_id) && ids.has(r.to_entity_id))
    .map((r) => ({
      group: 'edges',
      data: {
        id: r.id,
        source: r.from_entity_id,
        target: r.to_entity_id,
        label: r.label,
        width: EDGE_WIDTH[r.confidence] || EDGE_WIDTH.low,
      },
      classes: [
        'rel',
        r.status === 'documented' ? 'documented' : 'hypothesis',
        `conf-${EDGE_WIDTH[r.confidence] ? r.confidence : 'low'}`,
        r.unsupported ? 'unsupported' : '',
      ].filter(Boolean).join(' '),
    }));
  return [...nodes, ...edges];
}

/**
 * Give every node a distinct position before Cytoscape draws it. Cytoscape 3.30 throws
 * ("reading 'corners'") on parallel edges between nodes at the same point, which is where
 * unplaced nodes would otherwise all start. Unplaced nodes get provisional grid spots (the
 * page's layout then places them); saved positions that coincide exactly are nudged apart.
 * Returns the same array, modified.
 */
export function withDistinctPositions(elements) {
  const taken = new Set();
  let provisional = 0;
  for (const element of elements) {
    if (element.group !== 'nodes') continue;
    if (!element.position) {
      const i = provisional++;
      element.position = { x: (i % 25) * 70, y: Math.floor(i / 25) * 70 - 100000 };
    }
    let { x, y } = element.position;
    while (taken.has(`${x},${y}`)) {
      x += 7;
      y += 5;
    }
    element.position = { x, y };
    taken.add(`${x},${y}`);
  }
  return elements;
}

/** Entities that have no saved position yet (they get an automatic first placement). */
export function unplacedIds(inv) {
  return ((inv && inv.entities) || [])
    .filter((e) => !(Number.isFinite(e.pos_x) && Number.isFinite(e.pos_y)))
    .map((e) => e.id);
}

/** Larger graphs drop expensive rendering while panning and hide small labels. */
export function performanceOptions(elementCount) {
  const large = elementCount > 300;
  return {
    hideEdgesOnViewport: large,
    textureOnViewport: large,
    minZoomedFontSize: large ? 10 : 6,
  };
}

export function graphStyle(elementCount = 0) {
  const { minZoomedFontSize } = performanceOptions(elementCount);
  return [
    {
      selector: 'node',
      style: {
        // Shape and colour come from one rule per type below, not from data mappers: a
        // data-mapped shape makes Cytoscape 3.30 throw on parallel edges ("corners").
        'background-color': ENTITY_STYLE.custom.color,
        shape: ENTITY_STYLE.custom.shape,
        label: 'data(label)',
        color: '#e6edf3',
        'font-size': 11,
        'text-valign': 'bottom',
        'text-margin-y': 4,
        'text-wrap': 'ellipsis',
        'text-max-width': 140,
        'min-zoomed-font-size': minZoomedFontSize,
        'border-width': 1,
        'border-color': '#0d1117',
        width: 26,
        height: 26,
      },
    },
    {
      selector: 'edge',
      style: {
        width: 'data(width)',
        'line-color': '#8b949e',
        'target-arrow-color': '#8b949e',
        'target-arrow-shape': 'triangle',
        'curve-style': 'bezier',
        label: 'data(label)',
        color: '#c9d1d9',
        'font-size': 9,
        'text-rotation': 'autorotate',
        'text-background-color': '#0d1117',
        'text-background-opacity': 0.85,
        'text-background-padding': 2,
        'min-zoomed-font-size': minZoomedFontSize + 2,
      },
    },
    ...Object.entries(ENTITY_STYLE).map(([kind, s]) => ({
      selector: `node.kind-${kind}`,
      style: { 'background-color': s.color, shape: s.shape },
    })),
    { selector: 'edge.documented', style: { 'line-style': 'solid', 'line-color': '#3fb950', 'target-arrow-color': '#3fb950' } },
    { selector: 'edge.hypothesis', style: { 'line-style': 'dashed', 'line-dash-pattern': [6, 4] } },
    { selector: 'edge.unsupported', style: { 'line-color': '#f85149', 'target-arrow-color': '#f85149', 'line-style': 'dotted' } },
    { selector: ':selected', style: { 'overlay-color': '#58a6ff', 'overlay-opacity': 0.25, 'overlay-padding': 6 } },
    { selector: 'node:selected', style: { 'border-width': 3, 'border-color': '#58a6ff' } },
  ];
}

/** First problem with a relationship form, or '' (the server re-checks everything). */
export function validateRelationship(values) {
  if (!values.from_entity_id || !values.to_entity_id) return 'Choose both entities.';
  if (values.from_entity_id === values.to_entity_id) {
    return 'A relationship must connect two different entities.';
  }
  if (!String(values.label || '').trim()) return 'Relationship is required.';
  const evidence = Array.isArray(values.evidence_ids) ? values.evidence_ids : [];
  if (values.status === 'documented' && !values.finding_id && !evidence.length) {
    return 'A documented relationship must cite a finding or evidence. Otherwise record it as a hypothesis.';
  }
  return '';
}

/** Relationships touching an entity, for its detail panel. */
export function relationshipsOf(inv, entityId) {
  return ((inv && inv.relationships) || []).filter(
    (r) => r.from_entity_id === entityId || r.to_entity_id === entityId,
  );
}
