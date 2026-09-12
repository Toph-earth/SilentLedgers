"""
main.py — FastAPI application for Silent Ledger.

This file wires the pipeline together and exposes it over HTTP. The
pipeline itself (generate or load -> build graph -> detect -> score ->
cache) is factored into a single internal function `_run_pipeline`, so
that /api/generate and /api/upload share exactly one code path. The two
endpoints differ only in how they obtain (accounts, transactions,
ground_truth); everything downstream is identical.

What this file does:
  - Owns the in-memory cache (accounts, transactions, graph, matches,
    risk scores, summary).
  - Exposes 8 endpoints: /api/generate, /api/upload, /api/health,
    /api/summary, /api/accounts, /api/graph, /api/patterns,
    /api/account/{id}/timeline.
  - Configures CORS so the Vercel frontend can reach Railway.

What this file explicitly does NOT do:
  - Detect patterns (detectors.py).
  - Score risk (risk_scorer.py — may not exist yet; stubbed inline below).
  - Parse CSVs (csv_loader.py).
  - Build graphs (graph_builder.py).
  - Know anything about React Flow's layout. The frontend runs dagre on
    the positions we return; we send position {x: 0, y: 0} and let it
    overwrite.

Assumptions about other modules:
  - models.py exposes Account, Transaction, PatternType, PatternMatch,
    RiskScore, and the response shapes: AccountSummary, GraphNode,
    GraphEdge, GraphPayload, ExplanationPayload, RegenerateResponse,
    HealthResponse.
  - graph_builder.py exposes build_graph(transactions) and
    export_subgraph(G, center_id=None, ...).
  - detectors.py exposes detect_structuring(G), detect_layering(G),
    detect_round_tripping(G).
  - risk_scorer.py is assumed to exist by the time detection is wired.
    Until then, a local stub computes a placeholder score so the API
    still returns real shapes.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import networkx as nx
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from models import (
    Account,
    AccountType,
    PatternMatch,
    PatternType,
    RiskScore,
    Transaction,
)
from csv_loader import CSVLoadError, load_from_csv
from data_generator import generate_dataset
from graph_builder import build_graph, export_subgraph

# Detectors and scorer are imported lazily so this file can still boot
# and serve /api/health even if those modules are not written yet. The
# _run_pipeline function handles their absence gracefully.
try:
    from detectors import (
        detect_structuring,
        detect_layering,
        detect_round_tripping,
    )
    _DETECTORS_AVAILABLE = True
except ImportError:
    _DETECTORS_AVAILABLE = False

try:
    from risk_scorer import score_accounts
    _SCORER_AVAILABLE = True
except ImportError:
    _SCORER_AVAILABLE = False


# ---------------------------------------------------------------------------
# Application setup
# ---------------------------------------------------------------------------

app = FastAPI(title="Silent Ledger", version="0.1.0")

# CORS: allow the Vercel frontend to reach Railway. During development
# the frontend runs on localhost:5173, so allow that too.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten after the hackathon
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------
# A single dict is the entire state of the backend. The pipeline writes
# it, every read endpoint reads it. There is no database. Regeneration
# replaces the contents atomically at the end of the pipeline (see
# _run_pipeline), so partially-populated reads cannot happen.

_CACHE: Dict[str, object] = {
    "accounts": [],              # List[Account]
    "transactions": [],          # List[Transaction]
    "graph": None,               # nx.MultiDiGraph
    "matches": [],               # List[PatternMatch]
    "risk_by_account": {},       # Dict[str, RiskScore]
    "matches_by_account": {},    # Dict[str, List[PatternMatch]]
    "summary": None,             # precomputed summary dict
    "patterns_indexed": {},      # Dict[str, PatternMatch] for /api/graph?patternId=
    "generated_at": None,        # datetime
    "source": None,              # "generated" | "uploaded"
    "warnings": [],              # List[str] from CSV load
}


def _cache_get(key: str):
    return _CACHE[key]


def _cache_set(**kwargs) -> None:
    _CACHE.update(kwargs)


# ---------------------------------------------------------------------------
# Pipeline (shared by /api/generate and /api/upload)
# ---------------------------------------------------------------------------

def _build_patterns_index(
    matches: List[PatternMatch],
) -> Dict[str, PatternMatch]:
    """Index matches by match_id for fast lookup in /api/graph?patternId=."""
    return {m.match_id: m for m in matches}


def _build_matches_by_account(
    matches: List[PatternMatch],
) -> Dict[str, List[PatternMatch]]:
    """Group matches by every account involved, for /api/explain and scoring."""
    by_account: Dict[str, List[PatternMatch]] = {}
    for m in matches:
        for acc_id in m.accounts_involved:
            by_account.setdefault(acc_id, []).append(m)
    return by_account


def _fallback_score(
    account: Account,
    matches: List[PatternMatch],
    G: Optional[nx.MultiDiGraph],
) -> RiskScore:
    """Placeholder scorer used until risk_scorer.py exists.

    Produces a RiskScore with a simple weighted sum of match severities.
    This lets the rest of the API return real shapes so the frontend can
    be built in parallel. Once risk_scorer.py lands, _run_pipeline calls
    it instead and this function goes unused.
    """
    if not matches:
        return RiskScore(
            account_id=account.account_id,
            score=0,
            contributing_matches=[],
        )
    weighted = sum(m.severity for m in matches)
    # Scale to 0-100, capped. Not tuned — just non-zero so the UI has
    # something real to sort by.
    score = int(min(100, round(weighted * 40)))
    return RiskScore(
        account_id=account.account_id,
        score=score,
        contributing_matches=[m.match_id for m in matches],
    )


def _run_pipeline(
    accounts: List[Account],
    transactions: List[Transaction],
    ground_truth: Dict[str, str],
    source: str,
    warnings: Optional[List[str]] = None,
) -> Dict[str, object]:
    """Build graph, run detectors, score risk, and populate the cache.

    This is the single code path shared by /api/generate and /api/upload.
    The two endpoints differ only in how they produce (accounts,
    transactions, ground_truth). Everything from here down is identical.

    Writes into _CACHE in one shot at the end so readers never observe a
    half-updated state.
    """
    warnings = warnings or []

    # 1. Build the graph.
    G = build_graph(transactions)

    # 2. Run detectors if available; otherwise leave matches empty so the
    #    API still returns coherent shapes.
    matches: List[PatternMatch] = []
    if _DETECTORS_AVAILABLE:
        # Detectors return matches per pattern family. Concatenate.
        matches = (
            detect_structuring(G)
            + detect_layering(G)
            + detect_round_tripping(G)
        )

    # 3. Group matches by account (used by scoring and explain endpoint).
    matches_by_account = _build_matches_by_account(matches)

    # 4. Score risk per account.
    risk_by_account: Dict[str, RiskScore] = {}
    if _SCORER_AVAILABLE:
        # risk_scorer.py is expected to expose score_accounts(accounts,
        # matches_by_account, G) -> Dict[str, RiskScore].
        risk_by_account = score_accounts(accounts, matches_by_account, G)
    else:
        for acc in accounts:
            risk_by_account[acc.account_id] = _fallback_score(
                acc, matches_by_account.get(acc.account_id, []), G
            )

    # 5. Precompute the summary (aggregation on request is not allowed).
    summary = _compute_summary(accounts, matches, risk_by_account, transactions)

    # 6. Index patterns for /api/graph?patternId=.
    patterns_indexed = _build_patterns_index(matches)

    # 7. Atomic swap into the cache.
    generated_at = datetime.now(timezone.utc)
    _cache_set(
        accounts=accounts,
        transactions=transactions,
        graph=G,
        matches=matches,
        risk_by_account=risk_by_account,
        matches_by_account=matches_by_account,
        summary=summary,
        patterns_indexed=patterns_indexed,
        generated_at=generated_at,
        source=source,
        warnings=warnings,
    )

    return {
        "accountsCreated": len(accounts),
        "transactionsCreated": len(transactions),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Summary precomputation
# ---------------------------------------------------------------------------

def _compute_summary(
    accounts: List[Account],
    matches: List[PatternMatch],
    risk_by_account: Dict[str, RiskScore],
    transactions: List[Transaction],
) -> dict:
    """Precompute the KPI strip. Runs once per pipeline, not per request.

    Fields: totalAccounts, flaggedAccounts, activePatterns,
    totalFlaggedVolume30d, highestRiskScore, generatedAt.
    """
    flagged_ids = {
        acc_id
        for acc_id, rs in risk_by_account.items()
        if rs.score >= 60  # flag threshold; tune alongside risk_scorer
    }

    # Total volume in the last 30 days among transactions that touch a
    # flagged account. We intentionally do not filter by "was this
    # transaction part of a match" — an investigator cares about
    # everything flowing through a flagged account.
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    volume_30d = 0.0
    for t in transactions:
        if t.timestamp < cutoff:
            continue
        if t.source_account in flagged_ids or t.dest_account in flagged_ids:
            volume_30d += t.amount

    highest = max((rs.score for rs in risk_by_account.values()), default=0)

    return {
        "totalAccounts": len(accounts),
        "flaggedAccounts": len(flagged_ids),
        "activePatterns": len(matches),
        "totalFlaggedVolume30d": round(volume_30d, 2),
        "highestRiskScore": int(highest),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Endpoint: POST /api/generate
# ---------------------------------------------------------------------------

@app.post("/api/generate")
def api_generate():
    """Regenerate the synthetic dataset and rebuild the pipeline.

    Triggered manually before the demo, or on first boot. Not called by
    any UI component. Replaces the entire in-memory cache.
    """
    t0 = time.perf_counter()
    accounts, transactions, ground_truth = generate_dataset()
    result = _run_pipeline(
        accounts=accounts,
        transactions=transactions,
        ground_truth=ground_truth,
        source="generated",
    )
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    result["generationTimeMs"] = elapsed_ms
    return result


# ---------------------------------------------------------------------------
# Endpoint: POST /api/upload
# ---------------------------------------------------------------------------

@app.post("/api/upload")
async def api_upload(
    transactions_file: UploadFile = File(..., alias="transactions"),
    accounts_file: Optional[UploadFile] = File(default=None, alias="accounts"),
):
    """Load a user-uploaded CSV pair and rebuild the pipeline.

    Mirrors /api/generate's output shape. The only difference is how
    (accounts, transactions, ground_truth) is obtained — from CSV bytes
    instead of the generator. Everything downstream is the same
    _run_pipeline call.

    Accepts multipart form data with fields `transactions` (required)
    and `accounts` (optional). If accounts is omitted, accounts are
    derived from the transaction endpoints.

    Returns 400 with the CSVLoadError message on validation failure.
    Never returns a 500 for malformed input.
    """
    t0 = time.perf_counter()

    # Read bytes. Read both fully before parsing so a failure on the
    # second file does not leave the first half-consumed.
    try:
        txn_bytes = await transactions_file.read()
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Could not read transactions file: {e}",
        )

    acc_bytes: Optional[bytes] = None
    if accounts_file is not None:
        try:
            acc_bytes = await accounts_file.read()
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Could not read accounts file: {e}",
            )

    # Parse. Any CSVLoadError becomes a 400 with the specific message.
    try:
        accounts, transactions, ground_truth = load_from_csv(
            txn_bytes, acc_bytes=acc_bytes
        )
    except CSVLoadError as e:
        raise HTTPException(status_code=400, detail=str(e))

    warnings: List[str] = []
    # A future enhancement: csv_loader may return skipped-row counts.
    # For now, no warnings are produced.

    result = _run_pipeline(
        accounts=accounts,
        transactions=transactions,
        ground_truth=ground_truth,
        source="uploaded",
        warnings=warnings,
    )
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    result["generationTimeMs"] = elapsed_ms
    return result


# ---------------------------------------------------------------------------
# Endpoint: GET /api/health
# ---------------------------------------------------------------------------

@app.get("/api/health")
def api_health():
    """Railway health check target. No logic, no cache access."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Endpoint: GET /api/summary
# ---------------------------------------------------------------------------

@app.get("/api/summary")
def api_summary():
    """Return the precomputed KPI strip."""
    summary = _cache_get("summary")
    if summary is None:
        raise HTTPException(
            status_code=503,
            detail="No data loaded. Call POST /api/generate first.",
        )
    return summary


# ---------------------------------------------------------------------------
# Endpoint: GET /api/accounts
# ---------------------------------------------------------------------------

@app.get("/api/accounts")
def api_accounts(minRisk: Optional[int] = Query(default=None, ge=0, le=100)):
    """Return the account table, sorted by risk score descending.

    Optional minRisk filter is honored even though the frontend does not
    send it yet — costs nothing and makes the endpoint self-sufficient.
    """
    accounts: List[Account] = _cache_get("accounts")  # type: ignore
    if not accounts:
        raise HTTPException(
            status_code=503,
            detail="No data loaded. Call POST /api/generate first.",
        )

    risk_by_account: Dict[str, RiskScore] = _cache_get("risk_by_account")  # type: ignore
    matches_by_account: Dict[str, List[PatternMatch]] = _cache_get("matches_by_account")  # type: ignore
    graph: nx.MultiDiGraph = _cache_get("graph")  # type: ignore

    # Precompute net flow and 30-day volume per account from the graph.
    # These are cheap because graph_builder already rolled up totals.
    out: List[dict] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    for acc in accounts:
        rs = risk_by_account.get(
            acc.account_id,
            RiskScore(account_id=acc.account_id, score=0, contributing_matches=[]),
        )
        if minRisk is not None and rs.score < minRisk:
            continue

        node_attrs = graph.nodes[acc.account_id] if acc.account_id in graph else {}
        total_in = float(node_attrs.get("total_in", 0.0))
        total_out = float(node_attrs.get("total_out", 0.0))
        net_flow = total_in - total_out
        txn_count = int(node_attrs.get("txn_count", 0))

        # Determine the dominant flag type: the pattern with highest
        # severity among this account's matches, or None.
        acc_matches = matches_by_account.get(acc.account_id, [])
        flag_type: Optional[PatternType] = None
        if acc_matches:
            best = max(acc_matches, key=lambda m: m.severity)
            flag_type = best.pattern_type

        out.append(
            {
                "id": acc.account_id,
                "name": acc.name,
                "country": "US",  # placeholder; schema has no country yet
                "riskScore": rs.score,
                "flagged": rs.score >= 60,
                "totalVolume30d": round(total_in + total_out, 2),
                "flagType": flag_type.value if flag_type else None,
                "netFlow": round(net_flow, 2),
                "txnCount": txn_count,
            }
        )

    out.sort(key=lambda row: row["riskScore"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# Endpoint: GET /api/graph
# ---------------------------------------------------------------------------

@app.get("/api/graph")
def api_graph(
    patternId: Optional[str] = Query(default=None),
    maxNodes: int = Query(default=50, ge=5, le=200),
    maxEdges: int = Query(default=150, ge=5, le=500),
):
    """Return the graph in React Flow shape.

    With patternId: return only that pattern's subgraph (the accounts
    involved and the transactions between them).
    Without patternId: return the full graph, trimmed by degree.
    """
    graph: nx.MultiDiGraph = _cache_get("graph")  # type: ignore
    if graph is None or graph.number_of_nodes() == 0:
        raise HTTPException(
            status_code=503,
            detail="No data loaded. Call POST /api/generate first.",
        )

    risk_by_account: Dict[str, RiskScore] = _cache_get("risk_by_account")  # type: ignore
    risk_lookup = {
        acc_id: rs.score / 100.0 for acc_id, rs in risk_by_account.items()
    }

    if patternId is not None:
        patterns_indexed: Dict[str, PatternMatch] = _cache_get("patterns_indexed")  # type: ignore
        match = patterns_indexed.get(patternId)
        if match is None:
            raise HTTPException(
                status_code=404,
                detail=f"Pattern '{patternId}' not found.",
            )
        # Restrict the graph to accounts involved in this pattern. Use
        # export_subgraph with center=None after building a filtered
        # view — simplest correct implementation is to build a
        # subgraph of the MultiDiGraph limited to the involved accounts.
        involved = set(match.accounts_involved)
        sub = graph.subgraph(involved).copy()
        payload = export_subgraph(
            sub,
            center_id=None,
            max_nodes=len(involved),
            max_edges=1000,
            risk_lookup=risk_lookup,
        )
    else:
        payload = export_subgraph(
            graph,
            center_id=None,
            max_nodes=maxNodes,
            max_edges=maxEdges,
            risk_lookup=risk_lookup,
        )

    # Convert to React Flow shape. The frontend runs dagre, so position
    # is a placeholder. Stable IDs are load-bearing: edges[].id must not
    # change between calls for the same logical edge.
    rf_nodes = [
        {
            "id": n["id"],
            "type": "risk",
            "position": {"x": 0, "y": 0},
            "data": {
                "label": n["label"],
                "risk": n["risk"],
            },
        }
        for n in payload["nodes"]
    ]
    rf_edges = [
        {
            "id": f"{e['source']}->{e['target']}",  # stable across calls
            "source": e["source"],
            "target": e["target"],
            "data": {
                "amount": e["amount"],
                "timestamp": e["timestamp"],
            },
        }
        for e in payload["edges"]
    ]

    return {
        "nodes": rf_nodes,
        "edges": rf_edges,
        "meta": {
            "nodeCount": len(rf_nodes),
            "edgeCount": len(rf_edges),
            "truncated": len(payload["nodes"]) < graph.number_of_nodes(),
            "patternId": patternId,
        },
    }


# ---------------------------------------------------------------------------
# Endpoint: GET /api/patterns
# ---------------------------------------------------------------------------

@app.get("/api/patterns")
def api_patterns():
    """Return every detected pattern, sorted by risk score descending.

    Doubles as the source of valid patternId values for /api/graph.
    """
    matches: List[PatternMatch] = _cache_get("matches")  # type: ignore
    risk_by_account: Dict[str, RiskScore] = _cache_get("risk_by_account")  # type: ignore

    rows: List[dict] = []
    for m in matches:
        # Pattern-level risk: mean of member accounts' risk scores.
        member_scores = [
            risk_by_account.get(acc_id, RiskScore(account_id=acc_id, score=0, contributing_matches=[])).score
            for acc_id in m.accounts_involved
        ]
        pattern_risk = int(round(sum(member_scores) / len(member_scores))) if member_scores else 0

        rows.append(
            {
                "id": m.match_id,
                "type": m.pattern_type.value,
                "label": _human_label_for(m),
                "summary": m.evidence,
                "riskScore": pattern_risk,
                "memberAccounts": list(m.accounts_involved),
                "detectedAt": m.window_end.isoformat(),
            }
        )

    rows.sort(key=lambda r: r["riskScore"], reverse=True)
    return rows


def _human_label_for(m: PatternMatch) -> str:
    """Short display label for a pattern row in the sidebar."""
    if m.pattern_type == PatternType.STRUCTURING:
        return f"Structuring ring via {m.accounts_involved[0]}"
    if m.pattern_type == PatternType.LAYERING:
        return f"Layering chain of {len(m.accounts_involved)}"
    if m.pattern_type == PatternType.ROUND_TRIPPING:
        return f"Round-trip cycle of {len(m.accounts_involved)}"
    return m.match_id


# ---------------------------------------------------------------------------
# Endpoint: GET /api/account/{id}/timeline
# ---------------------------------------------------------------------------

@app.get("/api/account/{account_id}/timeline")
def api_account_timeline(account_id: str, days: int = Query(default=30, ge=1, le=180)):
    """Daily volume and transaction count for a single account.

    Called only after a user selects an account from an already-loaded
    list. Never on initial load. Returns one entry per day with no gaps —
    inactive days return volume: 0 and transactionCount: 0 rather than
    being omitted, so the frontend chart does not have to fill gaps.
    """
    graph: nx.MultiDiGraph = _cache_get("graph")  # type: ignore
    if graph is None or graph.number_of_nodes() == 0:
        raise HTTPException(
            status_code=503,
            detail="No data loaded. Call POST /api/generate first.",
        )

    accounts: List[Account] = _cache_get("accounts")  # type: ignore
    account_ids = {a.account_id for a in accounts}
    if account_id not in account_ids:
        raise HTTPException(
            status_code=404,
            detail=f"Account '{account_id}' not found.",
        )

    # Bucket transactions per day. Use the graph's edge list rather than
    # the flat transaction list so we only touch edges involving this
    # account. Both directions count toward "volume touching this
    # account" — the KPI on the frontend is "activity", not "money in".
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days - 1)

    # Pre-seed every day with zero so gaps are explicit.
    buckets: Dict[str, Dict[str, float]] = {}
    for i in range(days):
        day = (start + timedelta(days=i)).date().isoformat()
        buckets[day] = {"volume": 0.0, "transactionCount": 0}

    # Walk the graph edges once. O(E) is fine at our scale.
    for u, v, attrs in graph.edges(data=True):
        if u != account_id and v != account_id:
            continue
        ts_str = attrs.get("timestamp")
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str)
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts < start or ts > end:
            continue
        day = ts.date().isoformat()
        buckets[day]["volume"] += float(attrs.get("amount", 0.0))
        buckets[day]["transactionCount"] += 1

    points = [
        {
            "date": day,
            "volume": round(b["volume"], 2),
            "transactionCount": int(b["transactionCount"]),
        }
        for day, b in sorted(buckets.items())
    ]

    return {"accountId": account_id, "points": points}


# ---------------------------------------------------------------------------
# Startup: generate once so the demo has data even if nobody calls POST
# ---------------------------------------------------------------------------

@app.on_event("startup")
def _startup_generate():
    """Populate the cache on boot so the frontend has something to show.

    /api/generate can still be called manually to regenerate. This just
    removes the "empty until you POST" state for a demo-friendly boot.
    """
    accounts, transactions, ground_truth = generate_dataset()
    _run_pipeline(
        accounts=accounts,
        transactions=transactions,
        ground_truth=ground_truth,
        source="generated",
    )