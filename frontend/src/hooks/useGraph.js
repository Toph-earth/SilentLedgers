import { api } from '../api/client.js';
import { useApiResource } from './useApiResource.js';

export function useGraph({ patternId } = {}) {
  return useApiResource(() => api.getGraph({ patternId }), [patternId]);
}
