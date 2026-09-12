import { useMemo } from 'react';
import ReactFlow, { Background, Controls, MiniMap } from 'reactflow';
import 'reactflow/dist/style.css';

import { useGraph } from '../../hooks/useGraph.js';
import { computeLayout } from './layout.js';
import RiskNode from './RiskNode.jsx';
import LoadingState from '../common/LoadingState.jsx';
import ErrorState from '../common/ErrorState.jsx';
import EmptyState from '../common/EmptyState.jsx';
import { normalizeRisk, riskTier } from '../../utils/risk.js';

const nodeTypes = { risk: RiskNode };

// Hard cap on rendered nodes. Past this, React Flow gets slow and the graph
// stops being readable regardless of how good the layout is. We keep the
// highest-risk nodes and say so in the banner rather than silently dropping
// accounts, which is the failure mode that looks like a bug in a demo.
const NODE_CAP = 60;

// Edges below this amount are drawn thin and unlabeled; only edges that
// matter to the story get a dollar label, or 20+ edges turns into visual
// noise and the graph stops reading as anything.
const LABEL_THRESHOLD = 15000;

function capNodes(nodes, edges) {
  if (nodes.length <= NODE_CAP) return { nodes, edges, truncated: false, totalBeforeCap: nodes.length };

  const kept = [...nodes]
    .sort((a, b) => normalizeRisk(b.data.risk) - normalizeRisk(a.data.risk))
    .slice(0, NODE_CAP);
  const keptIds = new Set(kept.map((n) => n.id));
  const keptEdges = edges.filter((e) => keptIds.has(e.source) && keptIds.has(e.target));

  return { nodes: kept, edges: keptEdges, truncated: true, totalBeforeCap: nodes.length };
}

function toFlowEdges(edges) {
  return edges.map((e) => {
    const amount = e.data?.amount ?? 0;
    const heavy = amount >= LABEL_THRESHOLD;
    return {
      id: e.id,
      source: e.source,
      target: e.target,
      type: 'smoothstep',
      animated: heavy,
      label: heavy ? `$${Math.round(amount).toLocaleString()}` : undefined,
      labelStyle: { fill: '#AEB4C2', fontSize: 10, fontFamily: 'IBM Plex Mono, monospace' },
      labelBgStyle: { fill: '#131820', fillOpacity: 0.9 },
      style: {
        stroke: heavy ? '#C9A227' : '#3A4457',
        strokeWidth: heavy ? 2 : 1,
        opacity: heavy ? 1 : 0.55,
      },
      markerEnd: { type: 'arrowclosed', color: heavy ? '#C9A227' : '#3A4457', width: 16, height: 16 },
    };
  });
}

export default function TransactionGraph({ selectedPatternId, selectedAccountId, onSelectAccount, dataVersion }) {
  const { status, data, error, refetch } = useGraph({ patternId: selectedPatternId, refreshKey: dataVersion });

  const { flowNodes, flowEdges, truncated, totalBeforeCap, serverTruncated } = useMemo(() => {
    if (!data || data.nodes.length === 0) {
      return { flowNodes: [], flowEdges: [], truncated: false, totalBeforeCap: 0, serverTruncated: false };
    }
    const capped = capNodes(data.nodes, data.edges);
    const positioned = computeLayout(capped.nodes, capped.edges).map((n) => ({
      ...n,
      selected: n.id === selectedAccountId,
    }));
    return {
      flowNodes: positioned,
      flowEdges: toFlowEdges(capped.edges),
      truncated: capped.truncated,
      totalBeforeCap: capped.totalBeforeCap,
      // The backend already caps /api/graph to its highest-value accounts
      // (maxNodes=50 by default) before this ever reaches our own 60-node
      // cap above. Both banners are informational, not stacked — client-side
      // truncation takes priority since it's the more specific number.
      serverTruncated: Boolean(data.meta?.truncated),
    };
  }, [data, selectedAccountId]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-ink-600 px-4 py-3">
        <h2 className="font-serif text-sm text-parchment-100">Transaction network</h2>
        {truncated && (
          <span className="rounded border border-brass-600 bg-ink-800 px-2 py-0.5 text-[11px] text-brass-400">
            Showing top {NODE_CAP} of {totalBeforeCap} accounts by risk score
          </span>
        )}
        {!truncated && serverTruncated && (
          <span className="rounded border border-brass-600 bg-ink-800 px-2 py-0.5 text-[11px] text-brass-400">
            Server capped to the highest-value accounts and edges
          </span>
        )}
      </div>

      {/* This wrapper must have an explicit, non-zero height. React Flow
          measures its parent on mount; if the parent's height resolves to 0
          (a very common trap with flex children that default to min-height:
          auto), the canvas mounts but renders nothing. h-0 + flex-1 here
          forces the flex child to actually fill the remaining space. */}
      <div className="h-0 flex-1">
        {status === 'loading' && <LoadingState label="Loading transaction graph" />}
        {status === 'error' && <ErrorState message={error?.message} onRetry={refetch} />}
        {status === 'success' && flowNodes.length === 0 && (
          <EmptyState message="No transactions to show for this selection." />
        )}
        {status === 'success' && flowNodes.length > 0 && (
          <ReactFlow
            nodes={flowNodes}
            edges={flowEdges}
            nodeTypes={nodeTypes}
            onNodeClick={(_, node) => onSelectAccount(node.id)}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            minZoom={0.2}
            proOptions={{ hideAttribution: true }}
          >
            <Background color="#1B2230" gap={20} />
            <Controls showInteractive={false} />
            <MiniMap
              pannable
              zoomable
              nodeColor={(n) => {
                const tier = riskTier(n.data.risk);
                return tier === 'high' ? '#D14F4F' : tier === 'mid' ? '#D69A2D' : '#3FA867';
              }}
              maskColor="rgba(11,14,20,0.75)"
              style={{ background: '#131820', border: '1px solid #262E3D' }}
            />
          </ReactFlow>
        )}
      </div>
    </div>
  );
}
