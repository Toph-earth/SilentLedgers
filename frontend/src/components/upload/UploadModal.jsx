import { useState } from 'react';
import { api } from '../../api/client.js';

// Mirrors the backend's own validation rules (API_REFERENCE.md ->
// POST /api/upload) so the required-column hint doesn't drift from what
// the server actually enforces.
const REQUIRED_COLUMNS = 'source_account, dest_account, amount, timestamp';

export default function UploadModal({ onClose, onSuccess }) {
  const [transactionsFile, setTransactionsFile] = useState(null);
  const [accountsFile, setAccountsFile] = useState(null);
  const [status, setStatus] = useState('idle'); // idle | loading | error
  const [error, setError] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!transactionsFile) {
      setStatus('error');
      setError('A transactions CSV is required.');
      return;
    }
    setStatus('loading');
    setError(null);
    try {
      const result = await api.uploadCsv({ transactionsFile, accountsFile });
      onSuccess(result);
    } catch (err) {
      // err.message here is the backend's own detail string, e.g.
      // "Transactions file: missing required column(s): timestamp." —
      // shown verbatim, no translation needed (see client.js toAppError).
      setStatus('error');
      setError(err.message);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-md rounded border border-ink-600 bg-ink-900 p-5 shadow-xl"
      >
        <h3 className="font-serif text-lg text-parchment-100">Upload transaction data</h3>
        <p className="mt-1 text-xs leading-relaxed text-parchment-500">
          Replaces the current dataset and re-runs detection. Required columns:{' '}
          <span className="font-mono text-parchment-300">{REQUIRED_COLUMNS}</span>.
        </p>

        <label className="mt-4 block text-xs text-parchment-300">
          Transactions CSV <span className="text-risk-high">*</span>
          <input
            type="file"
            accept=".csv"
            onChange={(e) => setTransactionsFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-xs text-parchment-500 file:mr-3 file:cursor-pointer file:rounded file:border file:border-ink-600 file:bg-ink-800 file:px-2 file:py-1 file:text-parchment-300 hover:file:border-brass-500"
          />
        </label>

        <label className="mt-3 block text-xs text-parchment-300">
          Accounts CSV (optional)
          <input
            type="file"
            accept=".csv"
            onChange={(e) => setAccountsFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-xs text-parchment-500 file:mr-3 file:cursor-pointer file:rounded file:border file:border-ink-600 file:bg-ink-800 file:px-2 file:py-1 file:text-parchment-300 hover:file:border-brass-500"
          />
        </label>

        {status === 'error' && (
          <p className="mt-3 rounded border border-risk-high/40 bg-risk-high/10 px-2 py-1.5 text-xs text-risk-high">
            {error}
          </p>
        )}

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={status === 'loading'}
            className="rounded border border-ink-600 px-3 py-1.5 text-xs text-parchment-300 hover:border-ink-500 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={status === 'loading'}
            className="rounded border border-brass-600 bg-ink-800 px-3 py-1.5 text-xs text-brass-400 hover:bg-ink-700 disabled:opacity-50"
          >
            {status === 'loading' ? 'Uploading…' : 'Upload & run detection'}
          </button>
        </div>
      </form>
    </div>
  );
}
