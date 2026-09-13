"""
main.py — FastAPI application for Silent Ledger.

Wires the pipeline together and exposes it over HTTP. The pipeline
itself (generate or load -> build graph -> detect -> score -> cache) is
factored into a single internal function `_run_pipeline`, so that
/api/generate and /api/upload share exactly one code path.

Detectors produce PatternMatch objects (audit layer).
ml_detector produces per-account probabilities (evasion-resistance layer).
risk_scorer blends both into a single 0–100 risk score.

What this file does NOT do:
  - Detect patterns (detectors.py).
  - Score risk (risk_scorer.py).
  - Train the model (ml_detector.py).
  - Parse CSVs (csv_loader.py).
  - Build graphs (graph_builder.py).
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import networkx as nx
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from models import (
    Account,
    PatternMatch,
    PatternType,
    RiskScore,
    Transaction,
)
from csv_loader import CSVLoadError, load_from_csv
from data_generator import generate_dataset
from graph_builder import build_graph, export_subgraph

# --- Detectors --------------------------------------------------------------
try:
    from detectors import (
        detect_structuring,
        detect_layering,
        detect_round_tripping,
    )
    _DETECTORS_AVAILABLE = True
except ImportError as e:
    print(f"Detectors not available: {e}")
    _DETECTORS_AVAILABLE = False

# --- Risk scorer ------------------------------------------------------------
try:
    from risk_scorer import score_accounts
    _SCORER_AVAILABLE = True
except ImportError as e:
    print(f"Risk scorer not available: {e}")
    _SCORER_AVAILABLE = False

# --- ML detector ------------------------------------------------------------
try:
    from ml_detector import fit_and_score as ml_fit_and_score
    _ML_AVAILABLE = True
except ImportError as e:
    print(f"ML detector not available: {e}")
    _ML_AVAILABLE = False


# ---------------------------------------------------------------------------
# Application setup
# ---------------------------------------------------------------------------

app = FastAPI(title="Silent Ledger", version="0.2.0")

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

_CACHE: Dict[str, object] = {
    "accounts": [],
    "transactions": [],
    "graph": None,
    "matches": [],
    "risk_by_account": {},
    "matches_by_account": {},
    "ml_scores": {},
    "ml_explanations": {},
    "summary": None,
    "patterns_indexed": {},
    "generated_at": None,
    "source": None,
    "warnings": [],
    "ml_active": False,
}


def _cache_get(key: str):
    return _CACHE[key]


def _cache_set(**kwargs) -> None:
    _CACHE.update(kwargs)


# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------

def _build_patterns_index(matches: List[PatternMatch]) -> Dict[str, PatternMatch]:
    return {m.match_id: m for m in matches}


def _build_matches_by_account(
    matches: List[PatternMatch],
) -> Dict[str, List[PatternMatch]]:
    by_account: Dict[str, List[PatternMatch]] = {}
    for m in matches:
        for acc_id in m.accounts_involved:
            by_account.setdefault(acc_id, []).append(m)
    return by_account


def _fallback_scorer(
    accounts: List[Account],
    matches_by_account: Dict[str, List[PatternMatch]],
    G: nx.MultiDiGraph,
    ml_scores: Optional[Dict[str, float]] = None,
) -> Dict[str, RiskScore]:
    """Minimal scorer used only if risk_scorer.py is missing.

    Mirrors the shape of risk_scorer.score_accounts so downstream code
    does not have to branch. Does not apply centrality, does not blend
    ML. If you see this in production, risk_scorer.py failed to import.
    """
    out: Dict[str, RiskScore] = {}
    ml_scores = ml_scores or {}
    for acc in accounts:
        acc_matches = matches_by_account.get(acc.account_id, [])
        rule = min(100.0, sum(m.severity for m in acc_matches) * 100.0)
        ml = float(ml_scores.get(acc.account_id, 0.0)) * 100.0
        blended = 0.6 * rule + 0.4 * ml if acc.account_id in ml_scores else rule
        out[acc.account_id] = RiskScore(
            account_id=acc.account_id,
            score=int(round(blended)),
            contributing_matches=[m.match_id for m in acc_matches],
        )
    return out


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def _run_pipeline(
    accounts: List[Account],
    transactions: List[Transaction],
    ground_truth: Dict[str, str],
    source: str,
    warnings: Optional[List[str]] = None,
) -> Dict[str, object]:
    """Build graph, run detectors, fit ML model, score, and cache."""
    warnings = warnings or []

    # 1. Graph
    G = build_graph(transactions)

    # 2. Rule detectors
    matches: List[PatternMatch] = []
    if _DETECTORS_AVAILABLE:
        matches = (
            detect_structuring(G)
            + detect_layering(G)
            + detect_round_tripping(G)
        )

    matches_by_account = _build_matches_by_account(matches)

    # 3. ML detector (augment only; fails gracefully)
    ml_scores: Dict[str, float] = {}
    ml_explanations: Dict[str, str] = {}
    ml_active = False
    if _ML_AVAILABLE:
        try:
            ml_scores, ml_explanations = ml_fit_and_score(accounts, G)
            ml_active = bool(ml_scores)
        except Exception as e:
            print(f"ML detector failed at runtime, continuing without it: {e}")
            ml_scores, ml_explanations = {}, {}
            ml_active = False

    # 4. Risk scoring (blends rule + ML)
    if _SCORER_AVAILABLE:
        risk_by_account = score_accounts(
            accounts, matches_by_account, G, ml_scores=ml_scores
        )
    else:
        risk_by_account = _fallback_scorer(
            accounts, matches_by_account, G, ml_scores=ml_scores
        )

    # 5. Summary
    summary = _compute_summary(accounts, matches, risk_by_account, transactions)

    # 6. Patterns index
    patterns_indexed = _build_patterns_index(matches)

    # 7. Atomic cache swap
    _cache_set(
        accounts=accounts,
        transactions=transactions,
        graph=G,
        matches=matches,
        risk_by_account=risk_by_account,
        matches_by_account=matches_by_account,
        ml_scores=ml_scores,
        ml_explanations=ml_explanations,
        summary=summary,
        patterns_indexed=patterns_indexed,
        generated_at=datetime.now(timezone.utc),
        source=source,
        warnings=warnings,
        ml_active=ml_active,
    )

    return {
        "accountsCreated": len(accounts),
        "transactionsCreated": len(transactions),
        "warnings": warnings,
    }


def _compute_summary(
    accounts: List[Account],
    matches: List[PatternMatch],
    risk_by_account: Dict[str, RiskScore],
    transactions: List[Transaction],
) -> dict:
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
        "mlActive": bool(_CACHE.get("ml_active", False)),
    }


# ---------------------------------------------------------------------------
# POST /api/generate
# ---------------------------------------------------------------------------

@app.post("/api/generate")
def api_generate():
    t0 = time.perf_counter()
    accounts, transactions, ground_truth = generate_dataset()
    result = _run_pipeline(
        accounts=accounts,
        transactions=transactions,
        ground_truth=ground_truth,
        source="generated",
    )
    result["generationTimeMs"] = int((time.perf_counter() - t0) * 1000)
    return result


# ---------------------------------------------------------------------------
# POST /api/upload
# ---------------------------------------------------------------------------

@app.post("/api/upload")
async def api_upload(
    transactions: UploadFile = File(...),
    accounts: Optional[UploadFile] = File(default=None),
):
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

    result = _run_pipeline(
        accounts=accounts_obj,
        transactions=transactions_obj,
        ground_truth=ground_truth,
        source="uploaded",
        warnings=[],
    )
    result["generationTimeMs"] = int((time.perf_counter() - t0) * 1000)
    return result


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------

@app.get("/api/health")
def api_health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# GET /api/summary
# ---------------------------------------------------------------------------

@app.get("/api/summary")
def api_summary():
    summary = _cache_get("summary")
    if summary is None:
        raise HTTPException(
            status_code=503,
            detail="No data loaded. Call POST /api/generate first.",
        )
    return summary


# ---------------------------------------------------------------------------
# GET /api/accounts
# ---------------------------------------------------------------------------

@app.get("/api/accounts")
def api_accounts(minRisk: Optional[int] = Query(default=None, ge=0, le=100)):
    accounts: List[Account] = _cache_get("accounts")  # type: ignore
    if not accounts:
        raise HTTPException(
            status_code=503,
            detail="No data loaded. Call POST /api/generate first.",
        )

    risk_by_account: Dict[str, RiskScore] = _cache_get("risk_by_account")  # type: ignore
    matches_by_account: Dict[str, List[PatternMatch]] = _cache_get("matches_by_account")  # type: ignore
    ml_scores: Dict[str, float] = _cache_get("ml_scores")  # type: ignore
    ml_explanations: Dict[str, str] = _cache_get("ml_explanations")  # type: ignore
    graph: nx.MultiDiGraph = _cache_get("graph")  # type: ignore

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

        acc_matches = matches_by_account.get(acc.account_id, [])
        flag_type: Optional[PatternType] = None
        if acc_matches:
            best = max(acc_matches, key=lambda m: m.severity)
            flag_type = best.pattern_type

        ml_prob = ml_scores.get(acc.account_id)
        ml_score_int = int(round(ml_prob * 100)) if ml_prob is not None else None

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
                "mlScore": ml_score_int,
                "mlExplanation": ml_explanations.get(acc.account_id, ""),
            }
        )

    out.sort(key=lambda row: row["riskScore"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# GET /api/graph
# ---------------------------------------------------------------------------

@app.get("/api/graph")
def api_graph(
    patternId: Optional[str] = Query(default=None),
    maxNodes: int = Query(default=50, ge=5, le=200),
    maxEdges: int = Query(default=150, ge=5, le=500),
):
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
            "data": {"label": n["label"], "risk": n["risk"]},
        }
        for n in payload["nodes"]
    ]
    rf_edges = [
        {
            "id": f"{e['source']}->{e['target']}",
            "source": e["source"],
            "target": e["target"],
            "data": {"amount": e["amount"], "timestamp": e["timestamp"]},
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
# GET /api/patterns
# ---------------------------------------------------------------------------

@app.get("/api/patterns")
def api_patterns():
    matches: List[PatternMatch] = _cache_get("matches")  # type: ignore
    risk_by_account: Dict[str, RiskScore] = _cache_get("risk_by_account")  # type: ignore
    ml_explanations: Dict[str, str] = _cache_get("ml_explanations")  # type: ignore

    rows: List[dict] = []
    for m in matches:
        member_scores = [
            risk_by_account.get(
                acc_id,
                RiskScore(account_id=acc_id, score=0, contributing_matches=[]),
            ).score
            for acc_id in m.accounts_involved
        ]
        pattern_risk = (
            int(round(sum(member_scores) / len(member_scores)))
            if member_scores
            else 0
        )

        rows.append(
            {
                "id": m.match_id,
                "type": m.pattern_type.value,
                "label": _human_label_for(m),
                "summary": m.evidence,
                "riskScore": pattern_risk,
                "memberAccounts": list(m.accounts_involved),
                "detectedAt": m.window_end.isoformat(),
                "mlExplanations": {
                    acc_id: ml_explanations[acc_id]
                    for acc_id in m.accounts_involved
                    if acc_id in ml_explanations
                },
            }
        )

    rows.sort(key=lambda r: r["riskScore"], reverse=True)
    return rows


def _human_label_for(m: PatternMatch) -> str:
    if m.pattern_type == PatternType.STRUCTURING:
        return f"Structuring ring via {m.accounts_involved[0]}"
    if m.pattern_type == PatternType.LAYERING:
        return f"Layering chain of {len(m.accounts_involved)}"
    if m.pattern_type == PatternType.ROUND_TRIPPING:
        return f"Round-trip cycle of {len(m.accounts_involved)}"
    return m.match_id


# ---------------------------------------------------------------------------
# GET /api/account/{id}/timeline
# ---------------------------------------------------------------------------

@app.get("/api/account/{account_id}/timeline")
def api_account_timeline(
    account_id: str,
    days: int = Query(default=30, ge=1, le=180),
):
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


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
def _startup_generate():
    accounts, transactions, ground_truth = generate_dataset()
    _run_pipeline(
        accounts=accounts,
        transactions=transactions,
        ground_truth=ground_truth,
        source="generated",
    )