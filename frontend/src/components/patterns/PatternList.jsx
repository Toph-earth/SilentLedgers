import { usePatterns } from '../../hooks/usePatterns.js';
import LoadingState from '../common/LoadingState.jsx';
import ErrorState from '../common/ErrorState.jsx';
import EmptyState from '../common/EmptyState.jsx';

const TYPE_LABEL = {
  structuring: 'Structuring',
  layering: 'Layering',
  round_tripping: 'Round-tripping',
};

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

export default function PatternList({ selectedPatternId, onSelectPattern }) {
  const { status, data, error, refetch } = usePatterns();

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-ink-600 px-4 py-3">
        <h2 className="font-serif text-sm text-parchment-100">Detected patterns</h2>
      </div>
      <div className="scrollbar-thin flex-1 space-y-2 overflow-y-auto px-3 py-3">
        {status === 'loading' && <LoadingState label="Scanning for patterns" />}
        {status === 'error' && <ErrorState message={error?.message} onRetry={refetch} />}
        {status === 'success' && data?.length === 0 && (
          <EmptyState message="No suspicious patterns detected in the current window." />
        )}
        {status === 'success' &&
          data?.map((p) => (
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
