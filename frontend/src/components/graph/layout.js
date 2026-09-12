import dagre from 'dagre';

const NODE_WIDTH = 170;
const NODE_HEIGHT = 58;

// Runs dagre layout and returns nodes with `position` set. Never mutates
// the input nodes. Throws if dagre chokes on malformed edges (dangling
// source/target ids) — callers should catch and fall back to layoutGrid.
export function layoutWithDagre(nodes, edges, direction = 'LR') {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: direction, nodesep: 36, ranksep: 96, marginx: 24, marginy: 24 });

  const nodeIds = new Set(nodes.map((n) => n.id));
  nodes.forEach((n) => g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT }));

  edges.forEach((e) => {
    if (!nodeIds.has(e.source) || !nodeIds.has(e.target)) {
      // Dangling edge — a node the edge points to wasn't in the node list
      // (e.g. filtered out by the node cap). Skip it rather than let dagre
      // throw and blank the whole graph.
      return;
    }
    g.setEdge(e.source, e.target);
  });

  dagre.layout(g);

  return nodes.map((n) => {
    const pos = g.node(n.id);
    if (!pos) {
      // dagre didn't place this node (shouldn't happen, but guards the trap
      // where a single unplaced node leaves position undefined and the
      // whole canvas renders blank).
      return { ...n, position: { x: 0, y: 0 } };
    }
    return {
      ...n,
      position: { x: pos.x - NODE_WIDTH / 2, y: pos.y - NODE_HEIGHT / 2 },
      targetPosition: direction === 'LR' ? 'left' : 'top',
      sourcePosition: direction === 'LR' ? 'right' : 'bottom',
    };
  });
}

// Deterministic grid fallback. Used when layoutWithDagre throws, or when
// the node/edge set is too irregular to trust an auto-layout with (e.g.
// disconnected components dagre stacks on top of each other). Guarantees
// every node gets a distinct, visible position.
export function layoutGrid(nodes, columns = 6) {
  return nodes.map((n, i) => ({
    ...n,
    position: {
      x: (i % columns) * (NODE_WIDTH + 40),
      y: Math.floor(i / columns) * (NODE_HEIGHT + 56),
    },
    targetPosition: 'left',
    sourcePosition: 'right',
  }));
}

export function computeLayout(nodes, edges) {
  try {
    if (nodes.length === 0) return [];
    const laidOut = layoutWithDagre(nodes, edges);
    const allPlaced = laidOut.every(
      (n) => Number.isFinite(n.position.x) && Number.isFinite(n.position.y)
    );
    if (!allPlaced) throw new Error('dagre left one or more nodes unplaced');
    return laidOut;
  } catch (err) {
    console.warn('[TransactionGraph] dagre layout failed, using grid fallback:', err.message);
    return layoutGrid(nodes);
  }
}
