import { api } from '../api/client.js';
import { useApiResource } from './useApiResource.js';

// When no account is selected there is nothing to fetch. We still route
// through useApiResource so the component gets a consistent status, but the
// resolved value is `null` and TimelineChart treats that as its empty state
// rather than an error.
export function useTimeline(accountId) {
  return useApiResource(() => {
    if (!accountId) return Promise.resolve(null);
    return api.getAccountTimeline(accountId);
  }, [accountId]);
}
