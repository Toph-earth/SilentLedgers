import { api } from '../api/client.js';
import { useApiResource } from './useApiResource.js';

export function useGraph({ patternId, refreshKey } = {}) {
  return useApiResource(() => api.getGraph({ patternId }), [patternId, refreshKey]);
}
