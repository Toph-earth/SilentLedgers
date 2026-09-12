import { api } from '../api/client.js';
import { useApiResource } from './useApiResource.js';

export function useAccounts({ minRisk } = {}) {
  return useApiResource(() => api.getAccounts({ minRisk }), [minRisk]);
}
