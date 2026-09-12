import { api } from '../api/client.js';
import { useApiResource } from './useApiResource.js';

// refreshKey isn't sent to the backend — it's an extra dependency so the
// Regenerate/Upload actions in the header can force a refetch by bumping a
// counter, without this hook needing to know why it's refetching.
export function useAccounts({ minRisk, refreshKey } = {}) {
  return useApiResource(() => api.getAccounts({ minRisk }), [minRisk, refreshKey]);
}
