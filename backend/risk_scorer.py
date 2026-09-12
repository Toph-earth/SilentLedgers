"""
risk_scorer.py — Aggregate pattern matches into per-account risk scores.

This module's single job is: pattern matches in, per-account risk scores
out. It does NOT detect patterns, does NOT build the graph, does NOT
know about the API.

What "risk" means here
----------------------
A compliance officer does not want to see every account that touched a
flagged transaction — they want a ranked queue of accounts to investigate
first, each with a defensible reason. The score is therefore a triage
ordering, not a probability and not a dollar amount.

Score composition (0-100):

    match_component      0-65   weighted, saturating aggregation of every
                                PatternMatch involving this account
    centrality_component 0-20   betweenness centrality percentile — rewards
                                accounts that sit on paths between otherwise
                                disconnected parts of the network
    volume_component     0-15   percentile rank of total flow through the
                                account — the weakest signal, capped low
                                because high volume is normal for businesses

Why these weights
-----------------
Base severity by pattern type reflects real AML triage: placement
(structuring) is the cheapest stage for the launderer and easiest to
explain innocently; integration (round-tripping) is the most deliberate
and hardest to explain innocently; layering is in between. But we do NOT
throw away the detector's own severity — each match's `severity` field
already encodes instance-level evidence strength (hop count, transfer
count, repeat count). The pattern type is the category prior; the
detector severity is the instance confidence. We multiply them.

Aggregation uses a saturating exponential rather than a raw sum so that
an account in two overlapping matches is not double-punished, and the
tenth weak match barely moves the needle past the first strong one.

Centrality is betweenness, not degree. Degree rewards high-volume
accounts, which the volume component already covers. Betweenness rewards
accounts that sit on paths between otherwise-disconnected parts of the
network — which is exactly what a layering intermediary looks like.

Determinism
-----------
Betweenness centrality is computed with k-sampling, which is randomized.
We seed the sampling so the same graph produces the same scores on every
regeneration. Non-determinism here would look like a bug in the demo.

API shape
---------
Exposes exactly one function, matching what main.py imports:

    score_accounts(accounts, matches_by_account, G) -> Dict[str, RiskScore]

Every account passed in appears in the returned dict, so callers can
look up by ID without a fallback. Accounts with no matches score 0.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

import networkx as nx

from models import Account, PatternMatch, PatternType, RiskScore


# ===========================================================================
# CONFIG — tune here, nowhere else
# ===========================================================================

# Base weight per pattern type, in [0, 1]. Multiplied by each match's own
# severity (also in [0, 1]) to get a per-match contribution in [0, 1].
# Ordering is load-bearing: integration > layering > placement.
PATTERN_BASE_WEIGHT: Dict[PatternType, float] = {
    PatternType.ROUND_TRIPPING: 0.95,
    PatternType.LAYERING:       0.75,
    PatternType.STRUCTURING:    0.45,
}

# Match component: 0 to MATCH_COMPONENT_MAX, saturating.
MATCH_COMPONENT_MAX = 65.0
MATCH_SATURATION = 0.9   # weighted_sum at which we reach ~63% of the max

# Centrality component: 0 to CENTRALITY_COMPONENT_MAX.
CENTRALITY_COMPONENT_MAX = 20.0
# Number of pivot nodes for approximate betweenness. Higher = more accurate,
# more expensive. On a 200-node graph, exact would be fine; on a 10k-node
# upload, sampling keeps this from blocking the request. We pick min(k, n)
# at call time.
CENTRALITY_SAMPLE_K = 100
CENTRALITY_SEED = 0x5EED  # deterministic

# Volume component: 0 to VOLUME_COMPONENT_MAX.
VOLUME_COMPONENT_MAX = 15.0

# Flag threshold used by main.py's summary computation. Kept here as a
# module constant only so this file and main.py can be checked against
# each other in tests; main.py owns the actual threshold.
FLAG_THRESHOLD = 60


# ===========================================================================
# Public entry point
# ===========================================================================

def score_accounts(
    accounts: Sequence[Account],
    matches_by_account: Dict[str, List[PatternMatch]],
    G: Optional[nx.MultiDiGraph],
) -> Dict[str, RiskScore]:
    """Score every account and return {account_id: RiskScore}.

    Parameters
    ----------
    accounts
        Every account in the current dataset. Used for the population
        over which volume percentiles are computed, and to guarantee
        that every account appears in the output.
    matches_by_account
        {account_id: [PatternMatch, ...]} as built by main.py's
        _build_matches_by_account. Accounts absent from this dict are
        treated as having zero matches.
    G
        The MultiDiGraph built by graph_builder.build_graph. Used for
        betweenness centrality and node-level flow totals. If None
        (defensive — main.py always passes a graph), centrality and
        volume components are zeroed and only matches contribute.

    Returns
    -------
    Dict[str, RiskScore]
        One entry per account in `accounts`. `contributing_matches` is
        ordered by each match's weighted contribution, descending, so
        callers can surface the strongest single piece of evidence by
        taking index 0.
    """
    if not accounts:
        return {}

    # --- Precompute graph-level components once -------------------------
    centrality = _betweenness_centrality(G) if G is not None else {}
    max_centrality = max(centrality.values(), default=0.0)

    flows = _account_flows(accounts, G)
    flow_percentiles = _percentile_ranks(flows)

    # --- Score each account ---------------------------------------------
    out: Dict[str, RiskScore] = {}
    for acc in accounts:
        acc_id = acc.account_id
        acc_matches = matches_by_account.get(acc_id, [])

        # Per-match weighted contributions, in [0, 1] each.
        contributions = _match_contributions(acc_matches)
        weighted_sum = sum(c for _, c in contributions)

        match_component = (
            MATCH_COMPONENT_MAX * (1.0 - math.exp(-weighted_sum / MATCH_SATURATION))
            if weighted_sum > 0
            else 0.0
        )

        centrality_component = 0.0
        if max_centrality > 0:
            centrality_component = (
                CENTRALITY_COMPONENT_MAX
                * (centrality.get(acc_id, 0.0) / max_centrality)
            )

        volume_component = (
            VOLUME_COMPONENT_MAX * flow_percentiles.get(acc_id, 0.0)
        )

        raw = match_component + centrality_component + volume_component
        score = int(round(_clip(raw, 0.0, 100.0)))

        # Order contributing_matches by weighted contribution descending.
        # Ties broken by match_id for determinism.
        ordered_match_ids = [
            m.match_id
            for m, _ in sorted(
                contributions,
                key=lambda mc: (-mc[1], mc[0].match_id),
            )
        ]

        out[acc_id] = RiskScore(
            account_id=acc_id,
            score=score,
            contributing_matches=ordered_match_ids,
        )

    return out


# ===========================================================================
# Component computations
# ===========================================================================

def _match_contributions(
    matches: List[PatternMatch],
) -> List[tuple]:
    """Return [(match, weighted_contribution), ...] for one account.

    weighted_contribution = base_weight[pattern_type] * match.severity,
    clipped to [0, 1]. The clip protects against a malformed match whose
    severity somehow exceeds 1 (Pydantic enforces it, but this function
    should not assume its inputs came through validation).
    """
    out: List[tuple] = []
    for m in matches:
        base = PATTERN_BASE_WEIGHT.get(m.pattern_type, 0.0)
        contribution = _clip(base * float(m.severity), 0.0, 1.0)
        out.append((m, contribution))
    return out


def _betweenness_centrality(
    G: nx.MultiDiGraph,
) -> Dict[str, float]:
    """Betweenness centrality, sampled for speed and seeded for determinism.

    Rationale for betweenness over degree: see module docstring. Rationale
    for sampling: exact betweenness is O(V*E); on a 200-node graph that is
    imperceptible, but csv_loader accepts arbitrary uploads and the same
    scorer must not become the bottleneck on a 10k-node file. k-sampling
    gives an approximation whose ranking is stable enough for triage.

    Rationale for seeding: the underlying sampler uses random pivots.
    Without a seed, regenerating the same dataset produces slightly
    different centrality values and therefore slightly different risk
    scores — which looks like a bug in a live demo.
    """
    n = G.number_of_nodes()
    if n == 0:
        return {}
    if n <= 2:
        # Betweenness is degenerate below 3 nodes.
        return {node: 0.0 for node in G.nodes}

    k = min(CENTRALITY_SAMPLE_K, n)
    try:
        bc = nx.betweenness_centrality(
            G,
            k=k,
            normalized=True,
            seed=CENTRALITY_SEED,
            weight=None,  # edge weight is dollar amount, not traversal cost
        )
    except Exception:
        # If betweenness fails for any reason (exotic graph shapes), fall
        # back to zero rather than crash the pipeline. The match component
        # still produces a meaningful ranking.
        return {node: 0.0 for node in G.nodes}
    return bc


def _account_flows(
    accounts: Sequence[Account],
    G: Optional[nx.MultiDiGraph],
) -> Dict[str, float]:
    """Total flow through each account: total_in + total_out.

    Reads the rollups graph_builder already computed on each node. If an
    account is absent from the graph (no transactions), its flow is 0.
    """
    flows: Dict[str, float] = {}
    for acc in accounts:
        if G is None or acc.account_id not in G:
            flows[acc.account_id] = 0.0
            continue
        attrs = G.nodes[acc.account_id]
        total_in = float(attrs.get("total_in", 0.0))
        total_out = float(attrs.get("total_out", 0.0))
        flows[acc.account_id] = total_in + total_out
    return flows


def _percentile_ranks(values: Dict[str, float]) -> Dict[str, float]:
    """Rank-normalize values to [0, 1] by percentile.

    Ties share the same percentile (the highest rank any of them would
    have achieved). A single-element population maps to 0.0, not 1.0 —
    one account is not "the highest-volume account", it is the only one,
    and giving it a full volume bonus would be misleading.
    """
    n = len(values)
    if n == 0:
        return {}
    if n == 1:
        return {next(iter(values)): 0.0}

    # Sort by value, assign ranks, then average ranks within tie groups so
    # tied accounts get identical percentiles.
    items = sorted(values.items(), key=lambda kv: kv[1])
    ranks: Dict[str, float] = {}
    i = 0
    while i < n:
        j = i
        # Find the run of equal values.
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        # Average rank across the tie group (0-indexed), then normalize.
        avg_rank = (i + j) / 2.0
        pct = avg_rank / (n - 1)  # maps [0, n-1] to [0, 1]
        for k in range(i, j + 1):
            ranks[items[k][0]] = pct
        i = j + 1
    return ranks


def _clip(value: float, lo: float, hi: float) -> float:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


# ===========================================================================
# Self-check
# ===========================================================================

if __name__ == "__main__":
    """
    Run standalone: python risk_scorer.py

    Generates the dataset, runs the full pipeline the same way main.py
    does, and prints a short summary. Not a substitute for
    verify_detection.py — just a sanity check that this module produces
    non-degenerate scores and every account appears in the output.
    """
    from collections import Counter

    from data_generator import generate_dataset
    from graph_builder import build_graph
    from detectors import (
        detect_structuring,
        detect_layering,
        detect_round_tripping,
        deduplicate_layering,
    )

    accounts, transactions, _gt = generate_dataset()
    G = build_graph(transactions)

    structuring = detect_structuring(G)
    round_tripping = detect_round_tripping(G)
    layering = deduplicate_layering(detect_layering(G), round_tripping)
    matches = structuring + layering + round_tripping

    matches_by_account: Dict[str, List[PatternMatch]] = {}
    for m in matches:
        for acc_id in m.accounts_involved:
            matches_by_account.setdefault(acc_id, []).append(m)

    scores = score_accounts(accounts, matches_by_account, G)

    print(f"Accounts scored: {len(scores)} / {len(accounts)}")
    print(f"Matches: {len(matches)} "
          f"(S={len(structuring)}, L={len(layering)}, RT={len(round_tripping)})")
    print()

    bucket = Counter()
    for s in scores.values():
        if s.score == 0:
            bucket["0"] += 1
        elif s.score < 30:
            bucket["1-29"] += 1
        elif s.score < 60:
            bucket["30-59"] += 1
        else:
            bucket["60-100"] += 1
    print("Score distribution:")
    for k in ("0", "1-29", "30-59", "60-100"):
        print(f"  {k:>7}: {bucket.get(k, 0)}")

    top = sorted(scores.values(), key=lambda s: s.score, reverse=True)[:10]
    print()
    print("Top 10 by score:")
    for s in top:
        print(f"  {s.account_id:>10}  {s.score:>3}  "
              f"({len(s.contributing_matches)} contributing match(es))")