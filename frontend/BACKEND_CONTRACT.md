# Backend Contract — Silent Ledger

This is what the frontend actually calls and actually parses. Every shape
here matches `src/mock/mockData.js` exactly — that file is the reference
implementation. If the real backend diverges from this doc, match this doc,
not your instinct for "cleaner" naming, or the frontend won't render.

All responses are `application/json`. All endpoints are read-only (`GET`).
Base URL is whatever `VITE_API_BASE_URL` is set to; paths below are relative
to that.

---

## 1. `GET /api/summary`

KPI strip in the header. Fetched once on load, no params, no polling.

- **Query params**: none
- **Consumed by**: `KPIBar` (top bar, always visible)
- **Max latency before UI degrades**: 1500ms — past this the header shows
  its loading spinner long enough to look broken. Precompute this rather
  than aggregating on request if it's expensive.

### Response 200

```json
{
  "totalAccounts": 44,
  "flaggedAccounts": 13,
  "activePatterns": 3,
  "totalFlaggedVolume30d": 1071900,
  "highestRiskScore": 91,
  "generatedAt": "2026-09-11T18:00:00Z"
}
```

| Field | Type | Notes |
|---|---|---|
| `totalAccounts` | integer | count of all known accounts |
| `flaggedAccounts` | integer | accounts with `flagged: true` |
| `activePatterns` | integer | length of the patterns list |
| `totalFlaggedVolume30d` | integer | sum of `totalVolume30d` across flagged accounts, in USD, no decimals |
| `highestRiskScore` | integer | 0-100 |
| `generatedAt` | string | ISO 8601 UTC timestamp |

### Errors

- `500` → `{ "message": "string describing what failed" }`. Frontend shows
  the message inline in the header region with a retry button; does not
  block the rest of the dashboard.

---

## 2. `GET /api/accounts`

Powers the account table (right rail, bottom). Fetched once on load.

- **Query params**:
  - `minRisk` (integer, optional) — return only accounts with
    `riskScore >= minRisk`. Omit to return all accounts. The frontend
    currently always omits this (client-side filtering isn't implemented
    yet) but the param must be honored if sent.
- **Consumed by**: `AccountTable`
- **Max latency before UI degrades**: 2000ms

### Response 200

Array, sorted by `riskScore` descending. The frontend does not re-sort —
sort order is the backend's responsibility.

```json
[
  {
    "id": "ACC_001",
    "name": "Coastal Trade Co",
    "country": "US",
    "riskScore": 91,
    "flagged": true,
    "totalVolume30d": 184320
  },
  {
    "id": "ACC_205",
    "name": "Foxglove Studio",
    "country": "US",
    "riskScore": 34,
    "flagged": false,
    "totalVolume30d": 7100
  }
]
```

| Field | Type | Notes |
|---|---|---|
| `id` | string | stable account identifier, format `ACC_###` |
| `name` | string | display name |
| `country` | string | ISO 3166-1 alpha-2 |
| `riskScore` | integer | 0-100 |
| `flagged` | boolean | true if any pattern references this account |
| `totalVolume30d` | integer | USD, no decimals |

### Empty case

`[]` is valid and expected on a fresh dataset. `AccountTable` renders its
empty state ("No accounts found.") rather than an error.

### Errors

- `500` → `{ "message": "string" }`

---

## 3. `GET /api/graph`

Powers the React Flow canvas. This is the endpoint the frontend is least
forgiving about — match the node/edge shape exactly (see below).

- **Query params**:
  - `patternId` (string, optional) — when present, return only the
    subgraph for that pattern (its member accounts and the edges between
    them). When absent, return the full graph.
- **Consumed by**: `TransactionGraph`
- **Max latency before UI degrades**: 2500ms. This is the slowest-feeling
  region if it's slow, because it's the visual centerpiece — if the real
  computation is slow, return a capped/sampled graph rather than blocking.

### Response 200

```json
{
  "nodes": [
    {
      "id": "ACC_001",
      "type": "risk",
      "data": {
        "label": "ACC_001",
        "accountName": "Coastal Trade Co",
        "risk": 91,
        "flagged": true
      },
      "position": { "x": 0, "y": 0 }
    }
  ],
  "edges": [
    {
      "id": "e-010-001",
      "source": "ACC_010",
      "target": "ACC_001",
      "data": { "amount": 9450, "count": 1 }
    }
  ],
  "meta": {
    "totalAccounts": 14,
    "truncated": false
  }
}
```

**This is a React Flow node/edge shape, not a generic graph shape.** Notes
that matter:

- `nodes[].type` must be the literal string `"risk"` — this selects the
  frontend's custom node renderer (`RiskNode`). Any other value falls back
  to React Flow's default box, which has no risk coloring.
- `nodes[].position` — send `{ "x": 0, "y": 0 }` for every node. The
  frontend recomputes real positions with dagre on the client and
  overwrites whatever you send. Don't spend backend time computing layout
  coordinates; it's discarded.
- `nodes[].data.label` is what's printed on the node — send the account id,
  not the display name, so the graph and account table use the same key
  the user can cross-reference.
- `edges[].id` must be globally unique and stable across requests (used as
  the React key; flickering ids cause visible remounts).
- `edges[].source` / `edges[].target` must reference ids present in
  `nodes[]` for that same response. A dangling edge (pointing to a node not
  in the list) is silently dropped by the frontend's layout step rather
  than crashing, but it means that transaction won't be visible — don't
  rely on that as a filtering mechanism.
- `data.amount` is a number (USD, decimals allowed), used both for edge
  styling (thickness/opacity) and for the $-labeled threshold at $15,000.
- `meta.truncated` — if the backend itself caps nodes before responding
  (e.g. for a huge account population), set this `true` and the frontend
  will not show its own "top N" banner on top of yours. If you're not
  truncating server-side, omit `meta` entirely or send
  `"truncated": false`; the frontend applies its own 60-node cap on
  whatever you return either way.

### Empty case

`{ "nodes": [], "edges": [], "meta": { "totalAccounts": 0, "truncated": false } }`
is valid — e.g. a `patternId` that matches zero accounts. `TransactionGraph`
renders its empty state.

### Errors

- `404` (unknown `patternId`) → `{ "message": "Unknown pattern <id>" }`.
  Frontend treats this the same as the error state, not the empty state —
  don't return `200` with empty arrays for an unknown id, that reads as
  zero suspicious activity rather than a bad request.
- `500` → `{ "message": "string" }`

---

## 4. `GET /api/patterns`

Powers the pattern list (left column). Fetched once on load.

- **Query params**: none
- **Consumed by**: `PatternList`
- **Max latency before UI degrades**: 1500ms

### Response 200

```json
[
  {
    "id": "P-STRUCT-1",
    "type": "structuring",
    "label": "Structuring into ACC_001",
    "summary": "5 accounts each send transfers just under the $10,000 reporting threshold into a single receiving account within a 36-hour window.",
    "riskScore": 91,
    "memberAccounts": ["ACC_001", "ACC_010", "ACC_011", "ACC_012", "ACC_013", "ACC_014"],
    "detectedAt": "2026-09-08T14:12:00Z"
  }
]
```

| Field | Type | Notes |
|---|---|---|
| `id` | string | stable id, used as the `patternId` param on `/api/graph` |
| `type` | string | one of `structuring`, `layering`, `round_tripping` — the frontend maps these three literal values to display labels; a fourth value renders but with no friendly label, so stick to these three or update `PatternList.jsx`'s `TYPE_LABEL` map alongside a new type |
| `label` | string | short human title, ~40 chars, shown in the card header |
| `summary` | string | 1-2 sentences, shown in full in the card |
| `riskScore` | integer | 0-100 |
| `memberAccounts` | array of strings | account ids in this pattern; must match ids returned by `/api/accounts` |
| `detectedAt` | string | ISO 8601 UTC |

Sort order: highest `riskScore` first. Frontend does not re-sort.

### Empty case

`[]` is valid — "no suspicious patterns detected." `PatternList` shows this
as a genuinely good outcome, not an error.

### Errors

- `500` → `{ "message": "string" }`

---

## 5. `GET /api/account/:id/timeline`

Powers the Recharts volume chart (right rail, top). Fetched only after the
user selects an account — never on initial load, so `:id` is always a real,
previously-returned account id.

- **Path param**: `id` — account id, e.g. `ACC_042`
- **Query params**: none
- **Consumed by**: `TimelineChart`
- **Max latency before UI degrades**: 1500ms

### Response 200

```json
{
  "accountId": "ACC_042",
  "points": [
    { "date": "2026-08-13", "volume": 640, "transactionCount": 2 },
    { "date": "2026-08-14", "volume": 715, "transactionCount": 1 }
  ]
}
```

| Field | Type | Notes |
|---|---|---|
| `accountId` | string | echo of the requested id |
| `points` | array | one entry per day, ascending by date, 30 entries expected |
| `points[].date` | string | `YYYY-MM-DD` |
| `points[].volume` | number | total USD moved that day |
| `points[].transactionCount` | integer | count of transactions that day |

The frontend does not sort or fill gaps — send exactly the days you want
plotted, in order, and if a day had zero activity, send `volume: 0` rather
than omitting the day (a gap in the x-axis reads as a data error, not as
zero).

### Empty case

`{ "accountId": "ACC_205", "points": [] }` → `TimelineChart` shows "No
transactions recorded for this account."

### Errors

- `404` (unknown account id) → `{ "message": "Unknown account ACC_999" }`
- `500` → `{ "message": "string" }`

---

## Cross-cutting

- **CORS**: the backend must send
  `Access-Control-Allow-Origin` for the Vercel deployment's origin (and
  `http://localhost:5173` for local dev). This is the single most common
  integration failure in a two-person hackathon split — verify it in the
  first sync, not the last one.
- **Error shape is uniform**: every non-2xx response body is
  `{ "message": string }`. The frontend's API client reads `.message` for
  every failure; anything else surfaces as "Request failed."
- **No auth**: no headers, tokens, or cookies are sent. Don't build auth
  into the hackathon backend; it's not part of this contract.
