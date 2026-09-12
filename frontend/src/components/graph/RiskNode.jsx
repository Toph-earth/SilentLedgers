import { Handle, Position } from 'reactflow';

function riskTier(risk) {
  if (risk >= 75) return { bg: '#2A1414', border: '#D14F4F', text: '#F1B4B4', tier: 'high' };
  if (risk >= 45) return { bg: '#2A2013', border: '#D69A2D', text: '#F0D399', tier: 'mid' };
  return { bg: '#132218', border: '#3FA867', text: '#B7E3C7', tier: 'low' };
}

function RiskNode({ data, selected }) {
  const c = riskTier(data.risk);
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
        {data.flagged && <span title="Flagged">⚑</span>}
      </div>
      <div className="mt-0.5 truncate text-[10px] opacity-80">{data.accountName}</div>
      <div className="mt-1 text-[10px] opacity-90">risk {data.risk}</div>
      <Handle type="source" position={Position.Right} style={{ background: c.border, width: 6, height: 6 }} />
    </div>
  );
}

export default RiskNode;
