export default function LoadingState({ label = 'Loading' }) {
  return (
    <div className="flex h-full min-h-[120px] flex-col items-center justify-center gap-2 text-parchment-500">
      <div className="h-5 w-5 animate-spin rounded-full border-2 border-ink-600 border-t-brass-500" />
      <span className="text-sm">{label}</span>
    </div>
  );
}
