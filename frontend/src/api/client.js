// Single API client layer. Every network call in the app goes through the
// `api` object exported below — no component calls axios or fetch directly.
//
// VITE_USE_MOCK=true short-circuits every method to the generated mock data
// in src/mock/mockData.js, with an artificial delay so loading states are
// visible in the demo. Flip VITE_USE_MOCK=false (and set VITE_API_BASE_URL)
// to hit the real backend. No component code needs to change either way.

import axios from 'axios';
import * as mock from '../mock/mockData.js';

const USE_MOCK = String(import.meta.env.VITE_USE_MOCK).toLowerCase() === 'true';
const BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

const http = axios.create({
  baseURL: BASE_URL,
  timeout: 8000,
});

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Normalizes axios errors and mock errors into one shape components can
// branch on: { message, status }.
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
      if (USE_MOCK) {
        await delay(300);
        return mock.getSummary();
      }
      const { data } = await http.get('/api/summary');
      return data;
    } catch (err) {
      throw toAppError(err);
    }
  },

  async getAccounts({ minRisk } = {}) {
    try {
      if (USE_MOCK) {
        await delay(450);
        return mock.getAccounts({ minRisk });
      }
      const { data } = await http.get('/api/accounts', { params: { minRisk } });
      return data;
    } catch (err) {
      throw toAppError(err);
    }
  },

  async getGraph({ patternId } = {}) {
    try {
      if (USE_MOCK) {
        await delay(550);
        return mock.getGraph({ patternId });
      }
      const { data } = await http.get('/api/graph', { params: { patternId } });
      return data;
    } catch (err) {
      throw toAppError(err);
    }
  },

  async getPatterns() {
    try {
      if (USE_MOCK) {
        await delay(350);
        return mock.getPatterns();
      }
      const { data } = await http.get('/api/patterns');
      return data;
    } catch (err) {
      throw toAppError(err);
    }
  },

  async getAccountTimeline(accountId) {
    try {
      if (USE_MOCK) {
        await delay(300);
        return mock.getAccountTimeline(accountId);
      }
      const { data } = await http.get(`/api/account/${accountId}/timeline`);
      return data;
    } catch (err) {
      throw toAppError(err);
    }
  },

  // Triggers the backend to generate a fresh batch of mock transactions
  // and re-run detection. In mock mode this is a no-op that resolves
  // immediately so the button still feels responsive.
  async regenerate() {
    try {
      if (USE_MOCK) {
        await delay(400);
        return { status: 'ok', mock: true };
      }
      const { data } = await http.post('/api/generate');
      return data;
    } catch (err) {
      throw toAppError(err);
    }
  },
};

export const isMockMode = USE_MOCK;