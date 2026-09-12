import { useSummary } from '../../hooks/useSummary.js';
import LoadingState from '../common/LoadingState.jsx';
import ErrorState from '../common/ErrorState.jsx';
import DataControls from '../header/DataControls.jsx';

const currency = (n) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n);

function Stat({ label, value, accent }) {
  return (
    <div className="flex flex-col gap-0.5 border-l border-ink-600 pl-4 first:border-l-0 first:pl-0">
      <span className="text-xs text-parchment-500">{label}</span>
      <span className={`font-mono text-lg leading-none ${accent || 'text-parchment-100'}`}>{value}</span>
    </div>
  );
}

export default function KPIBar({ onDataChanged }) {
  const { status, data, error, refetch } = useSummary();

  return (
    <header className="flex h-[72px] shrink-0 items-center justify-between gap-4 border-b border-ink-600 bg-ink-900 px-6">
      <div className="flex items-baseline gap-2">
        <span className="font-serif text-xl text-parchment-100">Silent Ledger</span>
        <span className="hidden text-xs text-parchment-500 sm:inline">network view of transaction risk</span>
      </div>

      <div className="flex h-full items-center gap-6">
        {status === 'loading' && <LoadingState label="Loading summary" />}
        {status === 'error' && <ErrorState message={error?.message} onRetry={refetch} />}
        {status === 'success' && data && (
          <div className="flex items-center gap-6">
            <Stat label="accounts" value={data.totalAccounts} />
            <Stat label="flagged" value={data.flaggedAccounts} accent="text-risk-high" />
            <Stat label="active patterns" value={data.activePatterns} accent="text-brass-400" />
            <Stat label="flagged volume (30d)" value={currency(data.totalFlaggedVolume30d)} />
          </div>
        )}

        <DataControls
          onDataChanged={() => {
            refetch();
            onDataChanged?.();
          }}
        />
      </div>
    </header>
  );
}
