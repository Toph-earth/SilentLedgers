import { useMemo, useState } from 'react';
import { usePatterns } from '../../hooks/usePatterns.js';
import LoadingState from '../common/LoadingState.jsx';
import ErrorState from '../common/ErrorState.jsx';
import EmptyState from '../common/EmptyState.jsx';

const TYPE_LABEL = {
  structuring: 'Structuring',
  layering: 'Layering',
  round_tripping: 'Round-tripping',
};

// Tab order matters for the demo narrative (see GUIDE.md's demo script):
// structuring first, then layering, then round-tripping.
const TAB_ORDER = ['all', 'structuring', 'layering', 'round_tripping'];

function CategoryTabs({ counts, activeTab, onChange }) {
  return (
    <div className="flex flex-wrap gap-1.5 border-b border-ink-600 px-3 py-2">
      {TAB_ORDER.filter((t) => t === 'all' || counts[t] > 0).map((tab) => {
        const active = tab === activeTab;
        const label = tab === 'all' ? 'All' : TYPE_LABEL[tab];
        return (
          <button
            key={tab}
            onClick={() => onChange(tab)}
            className={`rounded-full border px-2.5 py-1 text-[11px] transition-colors ${
              active
                ? 'border-brass-500 bg-ink-700 text-brass-400'
                : 'border-ink-600 bg-ink-800 text-parchment-500 hover:border-ink-500 hover:text-parchment-300'
            }`}
          >
            {label}
            <span className="ml-1.5 font-mono opacity-70">{counts[tab] ?? 0}</span>
          </button>
        );
      })}
    </div>
  );
}

function PatternCard({ pattern, selected, onSelect }) {
  return (
    <button
      onClick={() => onSelect(selected ? null : pattern.id)}
      className={`w-full rounded border px-3 py-3 text-left transition-colors ${
        selected
          ? 'border-brass-500 bg-ink-700'
          : 'border-ink-600 bg-ink-800 hover:border-ink-500'
      }`}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs text-parchment-500">{TYPE_LABEL[pattern.type] || pattern.type}</span>
        <span className="font-mono text-xs text-risk-high">{pattern.riskScore}</span>
      </div>
      <div className="mt-1 font-serif text-[15px] leading-snug text-parchment-100">
        {pattern.label}
      </div>
      <p className="mt-1 text-xs leading-relaxed text-parchment-500">{pattern.summary}</p>
      <div className="mt-2 font-mono text-[11px] text-parchment-500">
        {pattern.memberAccounts.length} accounts
      </div>
    </button>
  );
}

export default function PatternList({ selectedPatternId, onSelectPattern, dataVersion }) {
  const { status, data, error, refetch } = usePatterns({ refreshKey: dataVersion });
  const [activeTab, setActiveTab] = useState('all');

  const counts = useMemo(() => {
    const c = { all: data?.length ?? 0, structuring: 0, layering: 0, round_tripping: 0 };
    data?.forEach((p) => {
      if (c[p.type] != null) c[p.type] += 1;
    });
    return c;
  }, [data]);

  const visible = useMemo(() => {
    if (!data) return [];
    if (activeTab === 'all') return data;
    return data.filter((p) => p.type === activeTab);
  }, [data, activeTab]);

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-ink-600 px-4 py-3">
        <h2 className="font-serif text-sm text-parchment-100">Detected patterns</h2>
      </div>

      {status === 'success' && data && data.length > 0 && (
        <CategoryTabs counts={counts} activeTab={activeTab} onChange={setActiveTab} />
      )}

      <div className="scrollbar-thin flex-1 space-y-2 overflow-y-auto px-3 py-3">
        {status === 'loading' && <LoadingState label="Scanning for patterns" />}
        {status === 'error' && <ErrorState message={error?.message} onRetry={refetch} />}
        {status === 'success' && data?.length === 0 && (
          <EmptyState message="No suspicious patterns detected in the current window." />
        )}
        {status === 'success' && data?.length > 0 && visible.length === 0 && (
          <EmptyState message={`No ${TYPE_LABEL[activeTab] || activeTab} patterns in this dataset.`} />
        )}
        {status === 'success' &&
          visible.map((p) => (
            <PatternCard
              key={p.id}
              pattern={p}
              selected={p.id === selectedPatternId}
              onSelect={onSelectPattern}
            />
          ))}
      </div>
    </div>
  );
}
