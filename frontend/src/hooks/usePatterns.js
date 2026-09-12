import { api } from '../api/client.js';
import { useApiResource } from './useApiResource.js';

export function usePatterns({ refreshKey } = {}) {
  return useApiResource(() => api.getPatterns(), [refreshKey]);
}
