import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import { useTimeline } from '../../hooks/useTimeline.js';
import LoadingState from '../common/LoadingState.jsx';
import ErrorState from '../common/ErrorState.jsx';
import EmptyState from '../common/EmptyState.jsx';

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded border border-ink-600 bg-ink-800 px-3 py-2 text-xs">
      <div className="font-mono text-parchment-500">{label}</div>
      <div className="mt-1 font-mono text-parchment-100">
        ${payload[0].value.toLocaleString()}
      </div>
    </div>
  );
}

export default function TimelineChart({ accountId }) {
  const { status, data, error, refetch } = useTimeline(accountId);

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-ink-600 px-4 py-3">
        <h2 className="font-serif text-sm text-parchment-100">
          {accountId ? `Volume — ${accountId}` : 'Account timeline'}
        </h2>
      </div>
      <div className="flex-1 px-2 py-3">
        {!accountId && <EmptyState message="Select an account to see its 30-day transaction volume." />}
        {accountId && status === 'loading' && <LoadingState label="Loading timeline" />}
        {accountId && status === 'error' && <ErrorState message={error?.message} onRetry={refetch} />}
        {accountId && status === 'success' && (!data || data.points.length === 0) && (
          <EmptyState message="No transactions recorded for this account." />
        )}
        {accountId && status === 'success' && data && data.points.length > 0 && (
          <ResponsiveContainer width="100%" height="100%" minHeight={180}>
            <AreaChart data={data.points} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="volumeFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#C9A227" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="#C9A227" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#1B2230" vertical={false} />
              <XAxis
                dataKey="date"
                tick={{ fill: '#8B93A7', fontSize: 10, fontFamily: 'IBM Plex Mono' }}
                tickFormatter={(d) => d.slice(5)}
                axisLine={{ stroke: '#262E3D' }}
                tickLine={false}
                minTickGap={24}
              />
              <YAxis
                tick={{ fill: '#8B93A7', fontSize: 10, fontFamily: 'IBM Plex Mono' }}
                axisLine={false}
                tickLine={false}
                width={44}
              />
              <Tooltip content={<CustomTooltip />} />
              <Area
                type="monotone"
                dataKey="volume"
                stroke="#C9A227"
                strokeWidth={1.5}
                fill="url(#volumeFill)"
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
