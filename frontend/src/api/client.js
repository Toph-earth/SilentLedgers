// Single API client layer. Every network call in the app goes through the
// `api` object exported below — no component calls axios or fetch directly.
//
// Set VITE_API_BASE_URL to point at the backend. Mock mode has been removed;
// data comes from the backend, including the CSV upload flow.

import axios from 'axios';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

const http = axios.create({
  baseURL: BASE_URL,
  timeout: 15000,
});

// Normalizes axios errors into one shape components can branch on:
// { message, status }.
function toAppError(err) {
  if (err?.isAxiosError) {
    return {
      message: err.response?.data?.message || err.message || 'Request failed',
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

  async getGraph({ patternId } = {}) {
    try {
      const { data } = await http.get('/api/graph', { params: { patternId } });
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

  async getAccountTimeline(accountId) {
    try {
      const { data } = await http.get(`/api/account/${accountId}/timeline`);
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

  // Uploads a CSV of transactions. Backend parses it, builds the graph,
  // runs detection, and returns the standard payload. Response shape should
  // match what getSummary/getAccounts/getPatterns/getGraph return so the
  // dashboard can render without a refetch.
  async uploadTransactions(file, { name, institution } = {}) {
    try {
      const form = new FormData();
      form.append('file', file);
      if (name) form.append('name', name);
      if (institution) form.append('institution', institution);
      const { data } = await http.post('/api/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      return data;
    } catch (err) {
      throw toAppError(err);
    }
  },
};