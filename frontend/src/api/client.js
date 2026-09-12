// Single API client layer. Every network call in the app goes through the
// `api` object exported below — no component calls axios or fetch directly.
//
// Set VITE_API_BASE_URL to point at the backend. Mock mode has been removed.

import axios from 'axios';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

const http = axios.create({
  baseURL: BASE_URL,
  timeout: 15000,
});

// Normalizes axios errors into one shape components can branch on:
// { message, status }. FastAPI returns validation and error messages under
// `detail`, so we check that first.
function toAppError(err) {
  if (err?.isAxiosError) {
    const detail = err.response?.data?.detail;
    const message =
      (typeof detail === 'string' && detail) ||
      detail?.[0]?.msg ||
      err.response?.data?.message ||
      err.message ||
      'Request failed';
    return {
      message,
      status: err.response?.status ?? null,
    };
  }
  return { message: err?.message || 'Unknown error', status: null };
}

export const api = {
  async getSummary() {
    try {
      const { data } = await http.get('/api/summary');
      return data;
    } catch (err) {
      throw toAppError(err);
    }
  },

  async getAccounts({ minRisk } = {}) {
    try {
      const { data } = await http.get('/api/accounts', { params: { minRisk } });
      return data;
    } catch (err) {
      throw toAppError(err);
    }
  },

  async getGraph({ patternId, maxNodes, maxEdges } = {}) {
    try {
      const { data } = await http.get('/api/graph', {
        params: { patternId, maxNodes, maxEdges },
      });
      return data;
    } catch (err) {
      throw toAppError(err);
    }
  },

  async getPatterns() {
    try {
      const { data } = await http.get('/api/patterns');
      return data;
    } catch (err) {
      throw toAppError(err);
    }
  },

  async getAccountTimeline(accountId, { days } = {}) {
    try {
      const { data } = await http.get(`/api/account/${accountId}/timeline`, {
        params: { days },
      });
      return data;
    } catch (err) {
      throw toAppError(err);
    }
  },

  async regenerate() {
    try {
      const { data } = await http.post('/api/generate');
      return data;
    } catch (err) {
      throw toAppError(err);
    }
  },

  // Uploads CSV files. `transactions` is required; `accounts` is optional.
  // Backend parses, rebuilds the graph, runs detection, replaces the cache,
  // and returns { accountsCreated, transactionsCreated, warnings, generationTimeMs }.
  //
  // Accepts either:
  //   { transactions: File, accounts: File | undefined }
  // or a pre-built FormData via the `formData` option.
  async uploadCsv({ transactions, accounts, formData } = {}) {
    try {
      let form;
      if (formData instanceof FormData) {
        form = formData;
      } else {
        form = new FormData();
        if (transactions) form.append('transactions', transactions);
        if (accounts) form.append('accounts', accounts);
      }
      const { data } = await http.post('/api/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      return data;
    } catch (err) {
      throw toAppError(err);
    }
  },
};