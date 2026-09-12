"""
models.py — Pydantic models for the Silent Ledger backend.

This file is the single source of truth for what an Account, a Transaction,
a PatternMatch, and a RiskScore look like. It contains NO business logic —
no graph building, no detection, no risk scoring math. It exists so that:
  1. FastAPI gets automatic request validation and response serialization.
  2. Every other module (generator, CSV loader, graph builder, detectors,
     API) imports these shapes instead of redefining them.

Adjustments for CSV compatibility:
  - Account.is_laundering defaults to False, not required. Real CSVs have
    no ground-truth column.
  - Account.created_at defaults to "now" if absent, so accounts derived
    from a transaction log validate without a timestamp column.
  - Transaction.timestamp remains required — every detection is
    time-windowed, so a transaction without a timestamp cannot participate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AccountType(str, Enum):
    """Whether an account belongs to an individual or a business.

    Structuring detection cares about this: a business receiving 12 small
    payments a week is normal; an individual with no business reason doing
    the same is suspicious.
    """
    INDIVIDUAL = "individual"
    BUSINESS = "business"


class PatternType(str, Enum):
    """The three laundering pattern families we detect."""
    STRUCTURING = "structuring"
    LAYERING = "layering"
    ROUND_TRIPPING = "round_tripping"


# ---------------------------------------------------------------------------
# Core entities
# ---------------------------------------------------------------------------

class Account(BaseModel):
    """A bank account.

    `account_id` is the stable identifier referenced by transactions, the
    graph, and the API. `is_laundering` is a generator-only ground-truth
    field used for testing the detectors — it is never exposed on the
    public account view (see AccountSummary below).

    Both `is_laundering` and `created_at` tolerate absence so that accounts
    derived from a plain transaction-log CSV validate without modification.
    """

    account_id: str = Field(..., description="Stable identifier, e.g. ACC_001")
    name: str = Field(..., description="Display label for graph nodes")
    account_type: AccountType = Field(
        default=AccountType.INDIVIDUAL,
        description="Defaults to individual when the source does not specify.",
    )
    is_laundering: bool = Field(
        default=False,
        description="Ground truth for the synthetic generator and tests only. "
                    "Never exposed via the public account view. Defaults to "
                    "False for CSV-loaded data.",
    )
    created_at: datetime = Field(
        default_factory=_now_utc,
        description="Account opening date. Defaults to now when the source "
                    "does not provide one.",
    )


class Transaction(BaseModel):
    """A single directed transfer from one account to another.

    Directionality matters: funnels converge, chains flow one way, cycles
    return. Every detection we run is time-windowed, so `timestamp` is not
    optional flavor — it is load-bearing. A transaction without a
    timestamp cannot participate in any detection and is rejected at load.
    """

    transaction_id: str = Field(..., description="e.g. TXN_00001")
    source_account: str = Field(..., description="account_id of the sender")
    dest_account: str = Field(..., description="account_id of the receiver")
    amount: float = Field(..., gt=0, description="Positive transfer amount")
    timestamp: datetime
    currency: str = Field(
        default="USD",
        description="Optional in CSV sources; defaults to USD.",
    )


class PatternMatch(BaseModel):
    """A detection result — one flagged pattern instance.

    This is the evidence object. `transactions_involved` is the audit trail
    the frontend will highlight on the graph. `severity` is a raw score for
    this single match, NOT the final aggregated risk score per account.
    """

    match_id: str = Field(..., description="Unique ID for this detection")
    pattern_type: PatternType
    accounts_involved: List[str] = Field(
        ...,
        description="Ordered list of account_ids. Order matters for layering "
                    "and round-tripping (it is the hop sequence); order is "
                    "irrelevant for structuring.",
    )
    transactions_involved: List[str] = Field(
        ...,
        description="transaction_ids that constitute the evidence for this match.",
    )
    severity: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Raw per-match score before aggregation into account risk.",
    )
    window_start: datetime = Field(..., description="Earliest timestamp in the match")
    window_end: datetime = Field(..., description="Latest timestamp in the match")
    evidence: str = Field(
        ...,
        description="Human-readable summary, e.g. '5 accounts sent $8,200–$9,400 "
                    "to ACC_042 within 4 days'. Read directly during the demo.",
    )


class RiskScore(BaseModel):
    """Derived risk score for a single account.

    This is a computed view, not a stored entity. Do NOT persist RiskScore
    anywhere — it is recalculated on account lookup from the current set of
    PatternMatches. Storing it separately would create a sync bug risk for
    zero benefit in a 24-hour build.
    """

    account_id: str
    score: int = Field(
        ...,
        ge=0,
        le=100,
        description="Final risk score on a 0–100 scale.",
    )
    contributing_matches: List[str] = Field(
        default_factory=list,
        description="match_ids of every PatternMatch that contributed to this score.",
    )


# ---------------------------------------------------------------------------
# API response shapes
# ---------------------------------------------------------------------------

class AccountSummary(BaseModel):
    """Public account view returned by GET /api/accounts.

    Deliberately excludes `is_laundering` — that field is ground truth for
    testing, not something the API should ever expose.

    The `risk` field is a computed RiskScore, derived at request time from
    the current PatternMatches. It is not stored.
    """

    account_id: str
    name: str
    account_type: AccountType
    risk: RiskScore
    flag_type: Optional[PatternType] = Field(
        default=None,
        description="The dominant pattern flagged for this account, or None.",
    )
    net_flow: float = Field(..., description="total_in - total_out")
    txn_count: int = Field(..., ge=0)


class GraphNode(BaseModel):
    """A node in a graph payload sent to the frontend."""

    id: str
    label: str
    risk: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Normalized risk (0.0–1.0) for visual encoding. "
                    "Derived from RiskScore.score by dividing by 100.",
    )


class GraphEdge(BaseModel):
    """A directed edge in a graph payload sent to the frontend."""

    source: str
    target: str
    amount: float
    timestamp: datetime


class GraphPayload(BaseModel):
    """Response shape for GET /api/graph/{account_id} and /api/graph/full."""

    nodes: List[GraphNode]
    edges: List[GraphEdge]


class ExplanationPayload(BaseModel):
    """Response shape for GET /api/explain/{account_id}."""

    account_id: str
    pattern: Optional[PatternType] = None
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str
    chain: List[GraphEdge] = Field(
        default_factory=list,
        description="Ordered transaction chain that triggered the flag. "
                    "Empty when the account is not flagged.",
    )


class RegenerateResponse(BaseModel):
    """Response shape for POST /api/regenerate."""

    status: str = "ok"
    account_count: int
    txn_count: int


class HealthResponse(BaseModel):
    """Response shape for GET /api/health."""

    status: str = "ok"