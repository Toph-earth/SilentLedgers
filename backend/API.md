# Silent Ledger — API Reference

Base URL (production): https://silentledgers-production.up.railway.app
Base URL (local): http://localhost:8000

All endpoints return JSON. All timestamps are ISO 8601 strings in UTC.

Interactive docs (Swagger UI) are available at /docs on any running instance.

---

## POST /api/generate

Regenerate the synthetic dataset, rebuild the graph, run all three detectors, and replace the in-memory cache.

Triggered by: Manual call before a demo, or triggered by a "Regenerate" button in the frontend header. Not called automatically on a schedule.

Request body: None.

Response (200):

```json
{
  "accountsCreated": 200,
  "transactionsCreated": 3006,
  "warnings": [],
  "generationTimeMs": 842
}
```

Notes:
- Replaces the entire cache atomically. Any in-flight reads either see the old cache or the new one, never a partial state.
- The pipeline takes 1–3 seconds. The frontend should show a loading state.
- After the call resolves, the frontend should refetch /api/summary, /api/accounts, /api/patterns, and /api/graph.

---

## POST /api/upload

Load a user-uploaded transaction CSV (and optionally an accounts CSV), rebuild the graph, run detection, and replace the cache. Behaves identically to /api/generate from the response perspective.

Triggered by: User uploading a CSV through the frontend.

Request body: multipart/form-data

Field: transactions
  Type: file
  Required: Yes
  Description: CSV with required columns source_account, dest_account, amount, timestamp. Optional columns: transaction_id, currency, pattern_tag.

Field: accounts
  Type: file
  Required: No
  Description: CSV with required column account_id. Optional: name, account_type, created_at. If omitted, accounts are derived from transaction endpoints.

Response (200): Same shape as /api/generate.

Response (400):

```json
{
  "detail": "Transactions file: missing required column(s): timestamp."
}
```

The error message is specific and human-readable. It names the exact problem so the frontend can display it without translation.

Validation rules:
- Required transaction columns must be present.
- Timestamps must be parseable (ISO 8601 or common date formats).
- Amounts must be positive numbers. Commas and dollar signs are stripped automatically.
- Self-transfers (source equals dest) are rejected with the row number.
- If an accounts file is provided, every transaction endpoint must exist in it.

---

## GET /api/health

Liveness check for Railway and external monitoring.

Response (200):

```json
{ "status": "ok" }
```

No cache access, no computation. Returns instantly.

---

## GET /api/summary

Precomputed KPI strip for the frontend header. Fetched once on page load.

Response (200):

```json
{
  "totalAccounts": 200,
  "flaggedAccounts": 47,
  "activePatterns": 45,
  "totalFlaggedVolume30d": 1284500.75,
  "highestRiskScore": 94,
  "generatedAt": "2026-09-12T14:23:00+00:00"
}
```

Field definitions:
- totalAccounts (int): Total accounts in the current dataset
- flaggedAccounts (int): Accounts with risk score greater than or equal to 60
- activePatterns (int): Total number of PatternMatch objects detected
- totalFlaggedVolume30d (float): Sum of all transaction amounts in the last 30 days involving a flagged account
- highestRiskScore (int): Maximum risk score across all accounts (0–100)
- generatedAt (ISO string): Timestamp when the current cache was populated

Notes:
- Precomputed during the pipeline. Not aggregated per request.
- Returns 503 if no data has been loaded yet. In practice this never happens because the startup hook generates data on boot.

---

## GET /api/accounts

Account table for the main list view. Sorted by risk score descending — sorting is done server-side.

Query parameters:

Parameter: minRisk
  Type: int
  Required: No
  Description: Filter to accounts with risk score greater than or equal to this value. Range 0–100.

Response (200):

```json
[
  {
    "id": "ACC_042",
    "name": "Account 042",
    "country": "US",
    "riskScore": 94,
    "flagged": true,
    "totalVolume30d": 184500.75,
    "flagType": "structuring",
    "netFlow": -45200.00,
    "txnCount": 78
  }
]
```

Field definitions:
- id (string): Stable account identifier
- name (string): Display name
- country (string): Placeholder; current schema does not carry country
- riskScore (int): 0–100
- flagged (bool): True when riskScore is 60 or above
- totalVolume30d (float): Sum of incoming and outgoing amounts
- flagType (string or null): Dominant pattern (structuring, layering, round_tripping) or null
- netFlow (float): total_in minus total_out
- txnCount (int): Number of transactions touching this account

---

## GET /api/graph

Full transaction graph in React Flow shape, trimmed to the highest-degree nodes and highest-value edges.

Query parameters:

Parameter: patternId
  Type: string
  Default: none
  Description: If provided, return only the subgraph for that pattern. Returns 404 if the pattern does not exist.

Parameter: maxNodes
  Type: int
  Default: 50
  Description: Maximum nodes to include (range 5–200)

Parameter: maxEdges
  Type: int
  Default: 150
  Description: Maximum edges to include (range 5–500)

Response (200):

```json
{
  "nodes": [
    {
      "id": "ACC_042",
      "type": "risk",
      "position": { "x": 0, "y": 0 },
      "data": { "label": "Account 042", "risk": 0.94 }
    }
  ],
  "edges": [
    {
      "id": "ACC_108->ACC_117",
      "source": "ACC_108",
      "target": "ACC_117",
      "data": { "amount": 1540.58, "timestamp": "2026-06-14T06:49:54+00:00" }
    }
  ],
  "meta": {
    "nodeCount": 34,
    "edgeCount": 60,
    "truncated": true,
    "patternId": null
  }
}
```

React Flow notes:
- type is literally the string "risk". The frontend registers a custom node component under this name.
- position is always {x: 0, y: 0}. The frontend runs dagre client-side to compute real positions. Do not attempt to lay out on the server.
- edges[].id is the string source->target. Stable across calls. When parallel edges are collapsed for visualization, the amount is summed and the earliest timestamp is kept.

404 response for unknown patternId:

```json
{ "detail": "Pattern 'MS-STRUCT-9999' not found." }
```

An empty 200 is never returned for an unknown pattern.

---

## GET /api/patterns

List of all detected patterns, sorted by risk score descending.

Response (200):

```json
[
  {
    "id": "MS-STRUCT-0001",
    "type": "structuring",
    "label": "Structuring ring via ACC_042",
    "summary": "12 sub-threshold transfers (8,000-9,900) from 8 distinct accounts to ACC_042 within 68 hours. Total $104,200.",
    "riskScore": 87,
    "memberAccounts": ["ACC_042", "ACC_108", "ACC_117"],
    "detectedAt": "2026-06-14T06:49:54+00:00"
  }
]
```

Field definitions:
- id (string): Stable match identifier. Format MS-STRUCT-0001, MS-LAYER-0001, MS-RT-0001.
- type (string): One of structuring, layering, round_tripping
- label (string): Short human-readable label for the panel row
- summary (string): Full evidence string. Read directly during the demo.
- riskScore (int): Mean of member accounts' risk scores
- memberAccounts (array of strings): Ordered list of accounts involved. Order is the hop sequence for layering and round-tripping.
- detectedAt (ISO string): End of the detection window

Doubles as the source of valid patternId values for /api/graph?patternId=X.

---

## GET /api/account/{account_id}/timeline

Daily volume and transaction count for a single account. Called only after a user selects an account from an already-loaded list.

Path parameters:

Parameter: account_id
  Type: string
  Description: Account identifier, e.g. ACC_042

Query parameters:

Parameter: days
  Type: int
  Default: 30
  Description: Number of days to include (range 1–180)

Response (200):

```json
{
  "accountId": "ACC_042",
  "points": [
    { "date": "2026-08-14", "volume": 4520.00, "transactionCount": 3 },
    { "date": "2026-08-15", "volume": 0.0, "transactionCount": 0 },
    { "date": "2026-08-16", "volume": 12100.50, "transactionCount": 5 }
  ]
}
```

Notes:
- One point per day, no gaps. Inactive days return volume 0 and transactionCount 0 rather than being omitted. The frontend chart does not need to fill gaps.
- Both incoming and outgoing transactions count toward volume for this account. It is activity, not money in.
- 404 for unknown account ID.

404 response:

```json
{ "detail": "Account 'ACC_99999' not found." }
```

---

## Error Conventions

Status codes:
- 200: Success. Render the response.
- 400: Validation error (malformed CSV, bad query param). Display the detail message to the user.
- 404: Unknown pattern or account ID. Show a "not found" state, offer to reset the view.
- 503: No data loaded. Show a "loading" state, retry after a short delay.
- 500: Unexpected server error. Log the error, show a generic "something went wrong" message.

All errors return:

```json
{ "detail": "Human-readable message." }
```

---

## CORS

Development: allow_origins is ["*"].

Production: to be tightened to the specific Vercel origin once the frontend is deployed.

---

## Data Model Reference

Account (Pydantic, models.Account)
- account_id: str
- name: str
- account_type: "individual" | "business"
- is_laundering: bool — generator-only ground truth. Never returned by the API.
- created_at: datetime

Transaction (Pydantic, models.Transaction)
- transaction_id: str
- source_account: str
- dest_account: str
- amount: float
- timestamp: datetime
- currency: str (default "USD")

PatternMatch (Pydantic, models.PatternMatch)
- match_id: str
- pattern_type: "structuring" | "layering" | "round_tripping"
- accounts_involved: List[str] — ordered
- transactions_involved: List[str] — evidence trail
- severity: float (0.0–1.0)
- window_start: datetime
- window_end: datetime
- evidence: str — human-readable

RiskScore (Pydantic, models.RiskScore)
- account_id: str
- score: int (0–100)
- contributing_matches: List[str]
- Computed at request time. Never persisted.

---

## Endpoint Summary

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/generate` | Regenerate synthetic dataset |
| POST | `/api/upload` | Load user-uploaded CSV |
| GET | `/api/health` | Liveness check |
| GET | `/api/summary` | KPI strip |
| GET | `/api/accounts` | Account table |
| GET | `/api/graph` | Full or pattern-scoped graph |
| GET | `/api/patterns` | Pattern list |
| GET | `/api/account/{id}/timeline` | Daily activity for one account |
