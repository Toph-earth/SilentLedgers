import { useState } from 'react';
import { useSummary } from '../../hooks/useSummary.js';
import { api } from '../../api/client.js';
import LoadingState from '../common/LoadingState.jsx';
import ErrorState from '../common/ErrorState.jsx';

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

function RegenerateButton() {
  const [state, setState] = useState('idle');

  async function handleClick() {
    setState('loading');
    try {
      await api.regenerate();
      window.location.reload();
    } catch {
      setState('error');
      setTimeout(() => setState('idle'), 2000);
    }
  }

  const label =
    state === 'loading' ? 'Regenerating…' :
    state === 'error'   ? 'Failed' :
                          'Regenerate';

  return (
    <button
      onClick={handleClick}
      disabled={state === 'loading'}
      className="ml-6 rounded border border-ink-600 px-3 py-1.5 text-xs font-medium text-brass-400 transition hover:bg-brass-400/10 disabled:opacity-40"
    >
      {label}
    </button>
  );
}

export default function KPIBar() {
  const { status, data, error, refetch } = useSummary();

  return (
    <header className="flex h-[72px] shrink-0 items-center justify-between border-b border-ink-600 bg-ink-900 px-6">
      <div className="flex items-baseline gap-2">
        <span className="font-serif text-xl text-parchment-100">Silent Ledger</span>
        <span className="text-xs text-parchment-500">network view of transaction risk</span>
      </div>

      <div className="flex h-full items-center">
        {status === 'loading' && <LoadingState label="Loading summary" />}
        {status === 'error' && <ErrorState message={error?.message} onRetry={refetch} />}
        {status === 'success' && data && (
          <div className="flex items-center gap-6">
            <Stat label="accounts" value={data.totalAccounts} />
            <Stat label="flagged" value={data.flaggedAccounts} accent="text-risk-high" />
            <Stat label="active patterns" value={data.activePatterns} accent="text-brass-400" />
            <Stat label="flagged volume (30d)" value={currency(data.totalFlaggedVolume30d)} />
            <RegenerateButton />
          </div>
        )}
      </div>
    </header>
  );
}