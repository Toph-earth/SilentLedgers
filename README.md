# Silent Ledger

A graph-based Anti-Money Laundering (AML) detection system for small banks, fintechs, and cooperative institutions that cannot afford enterprise compliance tooling.

## The Insight

Money laundering is a graph problem, not a transaction problem. Individually boring transactions — small transfers, ordinary amounts, unremarkable counterparties — become suspicious when viewed as a network over time. Three pattern families account for most real-world laundering:

- **Structuring**: many small transfers, each just below the regulatory reporting threshold, funneling into one account from many senders within a short window.
- **Layering**: money passing through a chain of accounts, each hop forwarding slightly less than the previous, obscuring the origin.
- **Round-tripping**: money cycling back to its origin through a small ring of accounts, repeated multiple times.

Silent Ledger detects all three directly on the transaction graph and produces human-readable evidence for every flag.

## What It Does

1. Ingests transactions — either from a synthetic generator (200 accounts, ~3,000 transactions, 70 planted laundering accounts) or from an uploaded CSV.
2. Builds a directed multigraph where accounts are nodes and individual transfers are edges. Parallel edges are preserved so the exact evidence trail survives.
3. Runs three rule-based detectors on the graph.
4. Aggregates detections into a per-account risk score.
5. Exposes the results via a FastAPI backend with a React investigator dashboard.

Every detection comes with a written evidence string — for example, *"12 sub-threshold transfers from 8 distinct accounts to ACC_042 within 68 hours."* This sentence is the deliverable a compliance officer would attach to a Suspicious Activity Report. The score is secondary.

## Detection Performance

Measured against synthetic ground truth (241 structuring transactions, 83 layering, 331 round-tripping):

| Pattern | Precision | Recall | F1 |
|---|---|---|---|
| Structuring | 100.00% | 61.41% | 76.09% |
| Layering | 75.86% | 53.01% | 62.41% |
| Round-tripping | 100.00% | 38.07% | 55.14% |

**Tuned for precision over recall, deliberately.** A compliance officer's time is the scarce resource. A system that floods an analyst with false positives gets turned off within a week. Precision-perfect structuring and round-tripping mean zero false alarms on those patterns. Layering precision reflects overlapping pattern signatures that are deduplicated at the pipeline level.

## Tech Stack

**Backend**
- Python 3.11
- FastAPI + uvicorn
- NetworkX (graph construction and traversal)
- Pydantic (models and validation)
- No database; all state is in-memory

**Frontend**
- React 18 + Vite
- Tailwind CSS
- React Flow (graph visualization)
- Recharts (timeline charts)
- axios (API client)

**Deployment**
- Backend: Railway (root directory: `backend/`)
- Frontend: Vercel (root directory: `frontend/`)

## Running Locally

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```
The server starts at http://localhost:8000. The startup hook generates a synthetic dataset automatically, so the API serves data immediately. Interactive docs at http://localhost:8000/docs.
Run the smoke test to verify the foundation:
```bash
python smoke_test.py
```
Run detection verification to compute precision and recall:
```bash
cd frontend
npm install
echo "VITE_API_URL=http://localhost:8000" > .env
npm run dev
```
Open `http://localhost:5173`

## Deployed Instances

- **Backend**: `https://silentledgers-production.up.railway.app`
- **Frontend**: `https://silent-ledgers.vercel.app/`

## Project Structure

```text
SilentLedgers/
├── backend/
│   ├── models.py               Pydantic models — single source of truth
│   ├── data_generator.py       Synthetic dataset with planted patterns
│   ├── csv_loader.py           Parse uploaded CSV into generator shape
│   ├── graph_builder.py        MultiDiGraph construction and JSON export
│   ├── detectors.py            Three pattern detectors
│   ├── risk_scorer.py          Aggregates matches into per-account risk
│   ├── verify_detection.py     Precision/recall against ground truth
│   ├── smoke_test.py           End-to-end module test
│   ├── main.py                 FastAPI application
│   ├── API.md                  Full endpoint reference
│   ├── requirements.txt
│   ├── Procfile
│   ├── .python-version
│   └── fixtures/
│       └── sample_transactions.csv
├── frontend/
│   ├── src/
│   ├── package.json
│   ├── vite.config.js
│   └── .env
├── .gitignore
└── README.md
```

See [`backend/API.md`](backend/API.md) for full endpoint reference.

## Path to Production

The prototype runs in-memory on NetworkX and is optimized for clarity and explainability. Production deployment requires three changes, none of which alter the detection logic:

1. **Streaming ingestion.** Replace batch generation with a message queue (Kafka, RabbitMQ) consuming normalized transaction events from core banking systems. Each event updates the graph incrementally.

2. **Graph database.** Move from in-memory NetworkX to Neo4j or an equivalent graph store. The three detectors translate directly to Cypher queries — variable-length path patterns and cycle enumeration are native operations. This is the correct answer for datasets beyond ~10,000 accounts.

3. **Threshold calibration.** Current thresholds are tuned for the synthetic generator. Production thresholds would be learned from labeled cases — SAR filings the institution already has, plus analyst feedback on true/false positives. The rule engine stays the same; the numbers shift.

The detection logic itself — the graph-first framing and the specific evidence trail each detector produces — is the intellectual core. The production plumbing is engineering.

## Team

Built during a 24-hour hackathon by a two-person team. 
Backend and detection by G Bramarambika; Frontend and visualization by S Darshni.

## License

Not licensed for production use. Prototype code.
