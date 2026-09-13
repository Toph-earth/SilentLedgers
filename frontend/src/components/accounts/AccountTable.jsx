import { Fragment } from 'react';
import { useAccounts } from '../../hooks/useAccounts.js';
import LoadingState from '../common/LoadingState.jsx';
import ErrorState from '../common/ErrorState.jsx';
import EmptyState from '../common/EmptyState.jsx';
import { riskColorClass } from '../../utils/risk.js';

const currency = (n) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n);

export default function AccountTable({ selectedAccountId, onSelectAccount, dataVersion }) {
  const { status, data, error, refetch } = useAccounts({ refreshKey: dataVersion });

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
                <th className="px-2 py-2 text-left font-normal">Pattern</th>
                <th className="px-2 py-2 text-right font-normal">Net flow</th>
                <th className="px-2 py-2 text-right font-normal">Risk</th>
              </tr>
            </thead>
            <tbody>
              {data.map((a) => (
                <Fragment key={a.id}>
                  <tr
                    onClick={() => onSelectAccount(a.id)}
                    className={`cursor-pointer border-b border-ink-700 transition-colors hover:bg-ink-700 ${
                      a.id === selectedAccountId ? 'bg-ink-700' : ''
                    } ${a.mlExplanation ? 'border-b-0' : ''}`}
                  >
                    <td className="px-4 py-2">
                      <div className="font-mono text-parchment-100">{a.id}</div>
                      <div className="truncate text-[11px] text-parchment-500">{a.name}</div>
                    </td>
                    <td className="px-2 py-2 text-[11px] text-parchment-500">
                      {a.flagType ? a.flagType.replace('_', ' ') : '—'}
                    </td>
                    <td className="px-2 py-2 text-right font-mono text-[11px] text-parchment-300">
                      {typeof a.netFlow === 'number' ? currency(a.netFlow) : '—'}
                    </td>
                    <td className={`px-2 py-2 text-right font-mono ${riskColorClass(a.riskScore)}`}>
                      {a.riskScore}
                      {a.flagged && <span className="ml-1">⚑</span>}
                    </td>
                  </tr>
                  {a.mlExplanation && (
                    <tr
                      onClick={() => onSelectAccount(a.id)}
                      className={`cursor-pointer border-b border-ink-700 transition-colors hover:bg-ink-700 ${
                        a.id === selectedAccountId ? 'bg-ink-700' : ''
                      }`}
                    >
                      <td colSpan={4} className="px-4 pb-2 pt-0 text-[11px] italic leading-relaxed text-brass-400">
                        {a.mlExplanation}
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}