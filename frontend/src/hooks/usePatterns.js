import { api } from '../api/client.js';
import { useApiResource } from './useApiResource.js';

export function usePatterns() {
  return useApiResource(() => api.getPatterns(), []);
}
