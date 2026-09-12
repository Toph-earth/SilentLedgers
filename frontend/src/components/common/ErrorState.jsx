export default function ErrorState({ message, onRetry }) {
  return (
    <div className="flex h-full min-h-[120px] flex-col items-center justify-center gap-2 px-4 text-center">
      <span className="text-sm text-risk-high">
        {message || 'Could not load this data.'}
      </span>
      {onRetry && (
        <button
          onClick={onRetry}
          className="rounded border border-ink-600 px-3 py-1 text-xs text-parchment-300 hover:border-brass-500 hover:text-brass-400"
        >
          Retry
        </button>
      )}
    </div>
  );
}
