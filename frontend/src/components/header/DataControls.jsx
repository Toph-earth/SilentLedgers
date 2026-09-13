import { useState } from 'react';
import { api } from '../../api/client.js';
import UploadModal from '../upload/UploadModal.jsx';

// Both actions here replace the entire in-memory dataset server-side
// (POST /api/generate, POST /api/upload). On success they call
// onDataChanged(), which App.jsx uses to bump a shared refreshKey so every
// other region (summary, accounts, patterns, graph) refetches — this
// component doesn't refetch anyone else's data directly.
export default function DataControls({ onDataChanged }) {
  const [regenerating, setRegenerating] = useState(false);
  const [regenError, setRegenError] = useState(null);
  const [lastResult, setLastResult] = useState(null);
  const [uploadOpen, setUploadOpen] = useState(false);

  const [threshold, setThreshold] = useState(10000);
  const [applying, setApplying] = useState(false);
  const [thresholdError, setThresholdError] = useState(null);

  async function handleRegenerate() {
    setRegenerating(true);
    setRegenError(null);
    try {
      const result = await api.regenerate();
      setLastResult(result);
      onDataChanged();
    } catch (err) {
      setRegenError(err.message);
    } finally {
      setRegenerating(false);
    }
  }

  async function handleApplyThreshold() {
    const value = Number(threshold);
    if (!Number.isFinite(value) || value <= 0) {
      setThresholdError('Enter a positive number');
      setTimeout(() => setThresholdError(null), 2500);
      return;
    }
    setApplying(true);
    setThresholdError(null);
    try {
      await api.setConfig({ reportingThreshold: value });
      onDataChanged();
    } catch (err) {
      setThresholdError(err.message);
      setTimeout(() => setThresholdError(null), 2500);
    } finally {
      setApplying(false);
    }
  }

  return (
    <div className="flex items-center gap-3">
      {regenError && <span className="max-w-[220px] truncate text-xs text-risk-high">{regenError}</span>}
      {!regenError && lastResult && (
        <span className="hidden text-[11px] text-parchment-500 lg:inline">
          {lastResult.accountsCreated} accts · {lastResult.transactionsCreated} txns
        </span>
      )}

      <div className="flex items-center gap-2">
        <label
          htmlFor="reporting-threshold"
          className="text-[11px] text-parchment-500"
          title="Transfers at or above this amount are reported"
        >
          Threshold
        </label>
        <input
          id="reporting-threshold"
          type="number"
          min="1"
          step="100"
          value={threshold}
          onChange={(e) => setThreshold(e.target.value)}
          className="w-[90px] rounded border border-ink-600 bg-ink-800 px-2 py-1.5 font-mono text-xs text-parchment-100 outline-none transition-colors focus:border-brass-500"
        />
        <button
          onClick={handleApplyThreshold}
          disabled={applying}
          className="rounded border border-ink-600 px-3 py-1.5 text-xs text-parchment-300 transition-colors hover:border-brass-500 hover:text-brass-400 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {applying ? 'Applying…' : 'Apply'}
        </button>
        {thresholdError && (
          <span className="max-w-[180px] truncate text-[11px] text-risk-high">{thresholdError}</span>
        )}
      </div>

      <button
        onClick={handleRegenerate}
        disabled={regenerating}
        className="rounded border border-ink-600 px-3 py-1.5 text-xs text-parchment-300 transition-colors hover:border-brass-500 hover:text-brass-400 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {regenerating ? 'Regenerating…' : 'Regenerate'}
      </button>

      <button
        onClick={() => setUploadOpen(true)}
        className="rounded border border-brass-600 bg-ink-800 px-3 py-1.5 text-xs text-brass-400 transition-colors hover:bg-ink-700 disabled:cursor-not-allowed disabled:opacity-40"
      >
        Upload CSV
      </button>

      {uploadOpen && (
        <UploadModal
          onClose={() => setUploadOpen(false)}
          onSuccess={(result) => {
            setLastResult(result);
            setUploadOpen(false);
            onDataChanged();
          }}
        />
      )}
    </div>
  );
}