export default function EmptyState({ message }) {
  return (
    <div className="flex h-full min-h-[120px] flex-col items-center justify-center px-4 text-center">
      <span className="text-sm text-parchment-500">{message || 'Nothing here yet.'}</span>
    </div>
  );
}
