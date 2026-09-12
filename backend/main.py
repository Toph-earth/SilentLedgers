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
  - Score risk (risk_scorer.py).
  - Parse CSVs (csv_loader.py).
  - Build graphs (graph_builder.py).
  - Know anything about React Flow's layout.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
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

# Detectors and scorer imports
from detectors import (
        detect_structuring,
        detect_layering,
        detect_round_tripping,
        deduplicate_layering,
    )
_DETECTORS_AVAILABLE = True


from risk_scorer import score_accounts
_SCORER_AVAILABLE = True


# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------
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
# Application lifespan & setup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Populate the cache on boot before processing any incoming HTTP requests."""
    accounts, transactions, ground_truth = generate_dataset()
    _run_pipeline(
        accounts=accounts,
        transactions=transactions,
        ground_truth=ground_truth,
        source="generated",
    )
    yield
    _CACHE.clear()


app = FastAPI(title="Silent Ledger", version="0.1.0", lifespan=lifespan)

# CORS: allow the Vercel frontend to reach Railway.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    """Fallback scorer if risk_scorer.py is unavailable."""
    if not matches:
        return RiskScore(
            account_id=account.account_id,
            score=0,
            contributing_matches=[],
        )
    weighted = sum(m.severity for m in matches)
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
    """Build graph, run detectors, score risk, and populate the cache atomically."""
    warnings = warnings or []

    # 1. Build the graph.
    G = build_graph(transactions)

    # 2. Run detectors if available.
    matches: List[PatternMatch] = []
    if _DETECTORS_AVAILABLE:
        structuring_matches = detect_structuring(G)
        round_tripping_matches = detect_round_tripping(G)
        layering_matches = deduplicate_layering(
            detect_layering(G), round_tripping_matches
        )
        matches = structuring_matches + layering_matches + round_tripping_matches
    print(
        f"DEBUG detectors: _DETECTORS_AVAILABLE={_DETECTORS_AVAILABLE}  "
        f"structuring={len(matches) and len(structuring_matches)}  "
        f"layering={len(matches) and len(layering_matches)}  "
        f"round_tripping={len(matches) and len(round_tripping_matches)}  "
        f"total={len(matches)}",
        flush=True,
    )

    # 3. Group matches by account.
    matches_by_account = _build_matches_by_account(matches)

    # 4. Score risk per account.
    risk_by_account: Dict[str, RiskScore] = {}
    if _SCORER_AVAILABLE:
        risk_by_account = score_accounts(accounts, matches_by_account, G)
    else:
        for acc in accounts:
            risk_by_account[acc.account_id] = _fallback_score(
                acc, matches_by_account.get(acc.account_id, []), G
            )

    # 5. Precompute the summary KPI metrics.
    summary = _compute_summary(accounts, matches, risk_by_account, transactions)

    # 6. Index patterns for fast graph lookups.
    patterns_indexed = _build_patterns_index(matches)

    # 7. Atomic update into the global cache.
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
    """Precompute the KPI strip. Runs once per pipeline run."""
    flagged_ids = {
        acc_id
        for acc_id, rs in risk_by_account.items()
        if rs.score >= 60
    }

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
    """Regenerate the synthetic dataset and rebuild the pipeline."""
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
    transactions: UploadFile = File(...),
    accounts: Optional[UploadFile] = File(default=None),
):
    """Load a user-uploaded CSV pair and rebuild the pipeline."""
    t0 = time.perf_counter()

    try:
        txn_bytes = await transactions.read()
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Could not read transactions file: {e}",
        )

    acc_bytes: Optional[bytes] = None
    if accounts is not None:
        try:
            acc_bytes = await accounts.read()
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Could not read accounts file: {e}",
            )

    try:
        accounts_obj, transactions_obj, ground_truth = load_from_csv(
            txn_bytes, acc_bytes=acc_bytes
        )
    except CSVLoadError as e:
        raise HTTPException(status_code=400, detail=str(e))

    warnings: List[str] = []

    result = _run_pipeline(
        accounts=accounts_obj,
        transactions=transactions_obj,
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
    """Railway health check target."""
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
    """Return the account table, sorted by risk score descending."""
    accounts: List[Account] = _cache_get("accounts")  # type: ignore
    if not accounts:
        raise HTTPException(
            status_code=503,
            detail="No data loaded. Call POST /api/generate first.",
        )

    risk_by_account: Dict[str, RiskScore] = _cache_get("risk_by_account")  # type: ignore
    matches_by_account: Dict[str, List[PatternMatch]] = _cache_get("matches_by_account")  # type: ignore
    graph: nx.MultiDiGraph = _cache_get("graph")  # type: ignore

    out: List[dict] = []

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

        acc_matches = matches_by_account.get(acc.account_id, [])
        flag_type: Optional[PatternType] = None
        if acc_matches:
            best = max(acc_matches, key=lambda m: m.severity)
            flag_type = best.pattern_type

        out.append(
            {
                "id": acc.account_id,
                "name": acc.name,
                "country": "US",
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
    """Return the graph in React Flow shape."""
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
            "id": f"{e['source']}->{e['target']}",
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
    """Return every detected pattern, sorted by risk score descending."""
    matches: List[PatternMatch] = _cache_get("matches")  # type: ignore
    risk_by_account: Dict[str, RiskScore] = _cache_get("risk_by_account")  # type: ignore

    rows: List[dict] = []
    for m in matches:
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
    """Daily volume and transaction count for a single account."""
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

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days - 1)

    buckets: Dict[str, Dict[str, float]] = {}
    for i in range(days):
        day = (start + timedelta(days=i)).date().isoformat()
        buckets[day] = {"volume": 0.0, "transactionCount": 0}

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