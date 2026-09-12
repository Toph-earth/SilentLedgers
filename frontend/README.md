# Silent Ledger — Frontend

React 18 + Vite dashboard for visualizing transaction networks flagged for
structuring, layering, and round-tripping. Ships in mock data mode by
default so it's demoable before the backend exists.

## Install

```
npm install
```

## Run (dev)

```
cp .env.example .env
npm run dev
```

Opens on `http://localhost:5173`. With `VITE_USE_MOCK=true` (the default in
`.env.example`) the app never touches the network — everything renders from
`src/mock/mockData.js`.

## Build

```
npm run build
```

Outputs static files to `dist/`. Preview the production build locally with
`npm run preview`.

## Deploy (Vercel)

1. Push this repo to GitHub.
2. Import it in Vercel. Framework preset: **Vite**. No other config needed —
   `vercel.json` isn't required for a static Vite app.
3. Set environment variables in the Vercel project settings:
   - `VITE_API_BASE_URL` — your backend's public URL (Railway), no trailing slash
   - `VITE_USE_MOCK` — `false` once the backend is live, `true` to demo without it
4. Redeploy after changing env vars — Vite inlines them at build time, so
   they don't take effect until the next build.

## Environment variables

| Variable              | Purpose                                              | Example                                |
|------------------------|-------------------------------------------------------|-----------------------------------------|
| `VITE_API_BASE_URL`   | Base URL the axios client prefixes onto every request | `https://silent-ledger-api.up.railway.app` |
| `VITE_USE_MOCK`       | `true` = serve mock data, `false` = call the backend  | `true`                                  |

## Flipping between mock and live backend

Everything routes through `src/api/client.js`. No component ever imports
axios or the mock module directly. To switch:

1. Set `VITE_USE_MOCK=false` in `.env`.
2. Set `VITE_API_BASE_URL` to wherever the backend is running.
3. Restart `npm run dev` (env vars are read at build/start time, not
   hot-reloaded).

The backend must match the shapes in `BACKEND_CONTRACT.md` exactly,
especially the React Flow node/edge shape for `GET /api/graph` — the
frontend does not transform or rename fields from that endpoint.

## Project docs

- `BACKEND_CONTRACT.md` — exact API contract the backend must implement.
- `GUIDE.md` — build rationale, layout derivation, component ownership,
  the 24-hour build sequence, and demo script.
