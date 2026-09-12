import { api } from '../api/client.js';
import { useApiResource } from './useApiResource.js';

export function useSummary() {
  return useApiResource(() => api.getSummary(), []);
}
