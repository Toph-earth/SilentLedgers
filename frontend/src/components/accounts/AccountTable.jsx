import { useAccounts } from '../../hooks/useAccounts.js';
import LoadingState from '../common/LoadingState.jsx';
import ErrorState from '../common/ErrorState.jsx';
import EmptyState from '../common/EmptyState.jsx';

function riskColor(risk) {
  if (risk >= 75) return 'text-risk-high';
  if (risk >= 45) return 'text-risk-mid';
  return 'text-risk-low';
}

export default function AccountTable({ selectedAccountId, onSelectAccount }) {
  const { status, data, error, refetch } = useAccounts();

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-ink-600 px-4 py-3">
        <h2 className="font-serif text-sm text-parchment-100">Accounts</h2>
      </div>
      <div className="scrollbar-thin flex-1 overflow-y-auto">
        {status === 'loading' && <LoadingState label="Loading accounts" />}
        {status === 'error' && <ErrorState message={error?.message} onRetry={refetch} />}
        {status === 'success' && data?.length === 0 && <EmptyState message="No accounts found." />}
        {status === 'success' && data && data.length > 0 && (
          <table className="w-full border-collapse text-xs">
            <thead className="sticky top-0 bg-ink-800 text-parchment-500">
              <tr>
                <th className="px-4 py-2 text-left font-normal">Account</th>
                <th className="px-2 py-2 text-right font-normal">Risk</th>
              </tr>
            </thead>
            <tbody>
              {data.map((a) => (
                <tr
                  key={a.id}
                  onClick={() => onSelectAccount(a.id)}
                  className={`cursor-pointer border-b border-ink-700 transition-colors hover:bg-ink-700 ${
                    a.id === selectedAccountId ? 'bg-ink-700' : ''
                  }`}
                >
                  <td className="px-4 py-2">
                    <div className="font-mono text-parchment-100">{a.id}</div>
                    <div className="truncate text-[11px] text-parchment-500">{a.name}</div>
                  </td>
                  <td className={`px-2 py-2 text-right font-mono ${riskColor(a.riskScore)}`}>
                    {a.riskScore}
                    {a.flagged && <span className="ml-1">⚑</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
