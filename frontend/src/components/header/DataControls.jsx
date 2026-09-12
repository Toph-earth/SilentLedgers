import { useState } from 'react';
import { api, isMockMode } from '../../api/client.js';
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

  return (
    <div className="flex items-center gap-3">
      {regenError && <span className="max-w-[220px] truncate text-xs text-risk-high">{regenError}</span>}
      {!regenError && lastResult && (
        <span className="hidden text-[11px] text-parchment-500 lg:inline">
          {lastResult.accountsCreated} accts · {lastResult.transactionsCreated} txns
        </span>
      )}

      <button
        onClick={handleRegenerate}
        disabled={regenerating || isMockMode}
        title={isMockMode ? 'Set VITE_USE_MOCK=false to regenerate real data' : undefined}
        className="rounded border border-ink-600 px-3 py-1.5 text-xs text-parchment-300 transition-colors hover:border-brass-500 hover:text-brass-400 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {regenerating ? 'Regenerating…' : 'Regenerate'}
      </button>

      <button
        onClick={() => setUploadOpen(true)}
        disabled={isMockMode}
        title={isMockMode ? 'Set VITE_USE_MOCK=false to upload real data' : undefined}
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
