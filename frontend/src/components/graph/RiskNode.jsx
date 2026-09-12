import { Handle, Position } from 'reactflow';
import { normalizeRisk, riskTier, isFlagged } from '../../utils/risk.js';

const TIER_STYLE = {
  high: { bg: '#2A1414', border: '#D14F4F', text: '#F1B4B4' },
  mid: { bg: '#2A2013', border: '#D69A2D', text: '#F0D399' },
  low: { bg: '#132218', border: '#3FA867', text: '#B7E3C7' },
};

function RiskNode({ data, selected }) {
  const score = normalizeRisk(data.risk);
  const c = TIER_STYLE[riskTier(data.risk)];
  // The live backend's /api/graph payload only sends { label, risk } —
  // accountName and flagged aren't part of it. flagged falls back to the
  // backend's own >=60 rule (see utils/risk.js) so the glyph still agrees
  // with the account table; accountName only renders if a caller (e.g.
  // mock mode) happens to provide one.
  const flagged = data.flagged ?? isFlagged(data.risk);

  return (
    <div
      className="rounded px-3 py-2 font-mono text-[11px] shadow-sm"
      style={{
        background: c.bg,
        border: `1.5px solid ${selected ? '#C9A227' : c.border}`,
        color: c.text,
        minWidth: 150,
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: c.border, width: 6, height: 6 }} />
      <div className="flex items-center justify-between gap-2">
        <span className="font-semibold">{data.label}</span>
        {flagged && <span title="Flagged">⚑</span>}
      </div>
      {data.accountName && (
        <div className="mt-0.5 truncate text-[10px] opacity-80">{data.accountName}</div>
      )}
      <div className="mt-1 text-[10px] opacity-90">risk {score}</div>
      <Handle type="source" position={Position.Right} style={{ background: c.border, width: 6, height: 6 }} />
    </div>
  );
}

export default RiskNode;
